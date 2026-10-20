"""Copy application-calendar events to the calendars picked under Lawn settings
(model/calwriter.py decides what).

Calendars that can only create events get firm events, once each, through the core
calendar.create_event service. Calendars that can also delete events are mirrored:
Lawn Growth's whole calendar, estimates included, kept in step. HA has no service to
update or delete an event, so those go to the calendar entity's own methods, the
way HA's calendar websocket API calls them."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from homeassistant.components.calendar import (
    DATA_COMPONENT, WEBSOCKET_EVENT_SCHEMA, CalendarEntityFeature)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CoreState
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import CONF_CALENDARS, DOMAIN
from .model import calwriter

_LOGGER = logging.getLogger(__name__)
ISSUE_PREFIX = "calendar_unavailable_"
FAILING_DAYS = 3
MIRROR_PAST_DAYS = 365      # older mirrored events are left alone (the log keeps 400)
MIRROR_AHEAD_DAYS = 400


def issue_id(entity_id: str) -> str:
    return ISSUE_PREFIX + entity_id.replace(".", "_")


def _status(hass, entity_id: str) -> str:
    """missing (no such entity), unavailable, or ok."""
    st = hass.states.get(entity_id)
    if st is None:
        return "unavailable" if er.async_get(hass).async_get(entity_id) else "missing"
    return "unavailable" if st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) else "ok"


def _name(hass, entity_id: str) -> str:
    st = hass.states.get(entity_id)
    if st is not None and st.name:
        return st.name
    entry = er.async_get(hass).async_get(entity_id)
    return (entry.name or entry.original_name or entity_id) if entry else entity_id


def _clear_issues(hass, keep: set) -> None:
    registry = ir.async_get(hass)
    for domain, issue in list(registry.issues):
        if domain == DOMAIN and issue.startswith(ISSUE_PREFIX) and issue not in keep:
            ir.async_delete_issue(hass, DOMAIN, issue)


async def async_write(coordinator) -> bool:
    """Write what's due to every target calendar. Returns True when a ledger changed
    (the caller saves the Store). Never raises: a failed write is retried later."""
    hass = coordinator.hass
    targets = list(coordinator.config_entry.options.get(CONF_CALENDARS) or [])
    issue_ids = {issue_id(t) for t in targets}
    _clear_issues(hass, issue_ids)
    # A calendar taken out of the setting keeps its ledger, so adding it back later
    # doesn't write everything a second time.
    store = coordinator.store
    if not targets or hass.state is not CoreState.running:
        return False
    today = dt_util.now().date()
    events = [e for e in coordinator.calendar if calwriter.writable(e)]
    live = {a for e in events for a in calwriter.atoms(e)}
    names = {k: c.name for k, c in coordinator.areas.items()}
    changed = False
    for target in targets:
        ledger = store.calendar_ledgers.get(target) or calwriter.Ledger()
        status = _status(hass, target)
        entity = _entity(hass, target) if status == "ok" else None
        if entity is not None and _can(entity, CalendarEntityFeature.DELETE_EVENT):
            ok = await _async_mirror(hass, target, entity, coordinator.calendar, today,
                                     quiet=ledger.failing_since is not None)
            new = calwriter.Ledger(ledger.written, ledger.pending, ledger.dropped,
                                   None if ok else ledger.failing_since or today)
            if new != ledger:
                store.calendar_ledgers[target] = new
                changed = True
            _update_issue(hass, target, calwriter.failing(new, today, FAILING_DAYS))
            continue
        writes = calwriter.plan(events, ledger, names)
        ok, failed = [], []
        for w in writes:
            if status != "ok":
                failed.extend(w.atoms)
                continue
            try:
                await hass.services.async_call(
                    "calendar", "create_event", {"entity_id": target, **w.service_data()},
                    blocking=True)
            except Exception as err:  # noqa: BLE001 - a failed write never fails the run
                if not set(w.atoms) <= set(ledger.pending):
                    _LOGGER.warning("Lawn Growth could not add \"%s\" to %s (will retry): %s",
                                    w.summary, target, err)
                failed.extend(w.atoms)
            else:
                ok.extend(w.atoms)
        new, given_up = calwriter.record(ledger, today, ok=ok, failed=failed,
                                         reachable=status == "ok", live=live)
        for atom in given_up:
            _LOGGER.warning("Lawn Growth gave up adding %s to %s after %d days", atom, target,
                            FAILING_DAYS)
        if new != ledger:
            store.calendar_ledgers[target] = new
            changed = True
        _update_issue(hass, target, status == "missing" or calwriter.failing(new, today,
                                                                            FAILING_DAYS))
    return changed


def _entity(hass, entity_id: str):
    component = hass.data.get(DATA_COMPONENT)
    return component.get_entity(entity_id) if component is not None else None


def _can(entity, feature) -> bool:
    return bool((entity.supported_features or 0) & feature)


def _day(value) -> date:
    return value.date() if isinstance(value, datetime) else value


async def _async_mirror(hass, target: str, entity, events, today: date, *,
                        quiet: bool) -> bool:
    """Make the calendar's Lawn Growth events match `events`. Returns False when
    reading it or any change failed (the next run tries again)."""
    first = today - timedelta(days=MIRROR_PAST_DAYS)
    last = max([e.end for e in events] + [today + timedelta(days=MIRROR_AHEAD_DAYS)])
    events = [e for e in events if e.end > first]
    log = _LOGGER.debug if quiet else _LOGGER.warning
    try:
        found = await entity.async_get_events(hass, dt_util.start_of_local_day(first),
                                              dt_util.start_of_local_day(last))
    except Exception as err:  # noqa: BLE001 - a failed sync never fails the run
        log("Lawn Growth could not read %s (will retry): %s", target, err)
        return False
    existing = [calwriter.Existing(e.uid, calwriter.key_of(e.description), e.summary,
                                   e.description or "", _day(e.start), _day(e.end))
                for e in found]
    creates, updates, deletes = calwriter.mirror_plan(events, existing)
    ok = True

    async def attempt(what: str, call) -> bool:
        nonlocal ok
        try:
            await call()
        except Exception as err:  # noqa: BLE001
            log("Lawn Growth could not %s on %s (will retry): %s", what, target, err)
            ok = False
            return False
        return True

    async def create(w) -> None:
        await hass.services.async_call(
            "calendar", "create_event", {"entity_id": target, **w.service_data()},
            blocking=True)

    for uid in deletes:
        await attempt("remove an event", lambda uid=uid: entity.async_delete_event(uid))
    for uid, w in updates:
        if _can(entity, CalendarEntityFeature.UPDATE_EVENT):
            data = w.service_data()
            event = WEBSOCKET_EVENT_SCHEMA({
                "summary": data["summary"], "description": data["description"],
                "dtstart": w.start, "dtend": w.end})
            await attempt(f'update "{w.summary}"',
                          lambda uid=uid, event=event: entity.async_update_event(uid, event))
        elif await attempt(f'replace "{w.summary}"',
                           lambda uid=uid: entity.async_delete_event(uid)):
            await attempt(f'replace "{w.summary}"', lambda w=w: create(w))
    for w in creates:
        await attempt(f'add "{w.summary}"', lambda w=w: create(w))
    return ok


def _update_issue(hass, target: str, broken: bool) -> None:
    iid = issue_id(target)
    if not broken:
        ir.async_delete_issue(hass, DOMAIN, iid)
        return
    if ir.async_get(hass).async_get_issue(DOMAIN, iid) is None:
        _LOGGER.warning("Lawn Growth can't write to the calendar %s; pick another calendar "
                        "or clear it under Lawn settings", target)
    ir.async_create_issue(hass, DOMAIN, iid, is_fixable=False, is_persistent=False,
                          severity=ir.IssueSeverity.WARNING,
                          translation_key="calendar_unavailable",
                          translation_placeholders={"calendar": _name(hass, target),
                                                    "entity_id": target})
