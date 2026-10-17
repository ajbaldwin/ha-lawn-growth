"""Copy firm application-calendar events to the calendars picked under Lawn settings,
through the core calendar.create_event service (model/calwriter.py decides what)."""
from __future__ import annotations

import logging

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CoreState
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import CONF_CALENDARS, DOMAIN
from .model import calwriter

_LOGGER = logging.getLogger(__name__)
ISSUE_PREFIX = "calendar_unavailable_"
FAILING_DAYS = 3


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
