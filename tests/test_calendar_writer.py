"""Copying firm events to other calendars, through HA's real calendar.create_event."""
from datetime import date, timedelta

from homeassistant.components.calendar import (
    DATA_COMPONENT, CalendarEntity, CalendarEntityFeature, CalendarEvent)
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from custom_components.lawn_growth import const
from custom_components.lawn_growth.calendar_writer import issue_id

from .common import area, daily, make_entry, register_weather, setup

FALL_NOW = "2026-09-26 12:00:00+00:00"        # 05:00 local
FALL = date(2026, 9, 26)
TARGET = "calendar.yard_log"
WARM_75 = [(80.0, 70.0)] * 11


class FakeCalendar(CalendarEntity):
    _attr_supported_features = CalendarEntityFeature.CREATE_EVENT

    def __init__(self, name="Yard log", features=None) -> None:
        self._attr_name = name
        self._attr_unique_id = name
        if features is not None:
            self._attr_supported_features = features
        self.created: list = []
        self.fail = False

    @property
    def event(self):
        return None

    async def async_get_events(self, hass, start_date, end_date):
        return []

    async def async_create_event(self, **kwargs) -> None:
        if self.fail:
            raise HomeAssistantError("calendar is down")
        self.created.append(kwargs)


async def _calendars(hass, *cals):
    await async_setup_component(hass, "calendar", {})
    await hass.data[DATA_COMPONENT].async_add_entities(list(cals))
    await hass.async_block_till_done()


async def _setup(hass, freezer, *targets, cals=None):
    hass.config.units = US_CUSTOMARY_SYSTEM
    freezer.move_to(FALL_NOW)
    # 75 °F: no fall window opens on the first run, so only logs are written
    register_weather(hass, daily_rows=daily(FALL, WARM_75))
    cals = cals if cals is not None else [FakeCalendar()]
    await _calendars(hass, *cals)
    options = {const.CONF_CALENDARS: list(targets)} if targets else {}
    entry = make_entry(hass, areas=[area(key="front", name="Front"),
                                    area(key="back", name="Back")], **options)
    await setup(hass, entry)
    return entry, cals


async def _log(hass, kind="fert", **data):
    await hass.services.async_call(const.DOMAIN, "log_event", {"kind": kind, **data},
                                   blocking=True)


async def _next_day(hass, freezer, entry, days=1):
    freezer.tick(timedelta(days=days))
    await entry.runtime_data.async_run(send_notifications=True)
    await hass.async_block_till_done()


async def test_nothing_is_written_without_the_setting(hass, freezer):
    entry, [cal] = await _setup(hass, freezer)
    await _log(hass)
    assert cal.created == []
    assert entry.runtime_data.store.calendar_ledgers == {}


async def test_logged_applications_are_written_once(hass, freezer, hass_storage):
    entry, [cal] = await _setup(hass, freezer, TARGET)
    assert cal.created == []                      # tentative/projected: nothing yet
    await _log(hass, date="2026-09-20")
    assert len(cal.created) == 1
    created = cal.created[0]
    assert (created["summary"], created["dtstart"], created["dtend"]) == (
        "Fertilizer — whole lawn", date(2026, 9, 20), date(2026, 9, 21))
    assert created["description"] == \
        "Lawn Growth key: lawn_growth-fert-2026-all-applied-2026-09-20"
    await _next_day(hass, freezer, entry)
    assert len(cal.created) == 1
    # across a restart: the ledger is in the Store
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await _next_day(hass, freezer, entry)
    assert len(cal.created) == 1


async def test_a_second_area_on_the_same_day_adds_only_that_area(hass, freezer):
    _, [cal] = await _setup(hass, freezer, TARGET)
    entry = hass.config_entries.async_entries(const.DOMAIN)[0]
    c = entry.runtime_data
    await c.async_log_event("fert", ["back"], on=date(2026, 9, 20))
    await c.async_log_event("fert", ["front"], on=date(2026, 9, 20))
    assert [e["summary"] for e in cal.created] == ["Fertilizer — Back", "Fertilizer — Front"]


async def test_several_calendars_each_get_the_events(hass, freezer):
    local, google = FakeCalendar("Yard log"), FakeCalendar("Phone")
    _, _ = await _setup(hass, freezer, TARGET, "calendar.phone", cals=[local, google])
    await _log(hass)
    assert len(local.created) == 1 and len(google.created) == 1


async def test_a_failed_write_is_retried_and_raises_a_repair(hass, freezer):
    entry, [cal] = await _setup(hass, freezer, TARGET)
    cal.fail = True
    await _log(hass)
    registry = ir.async_get(hass)
    assert cal.created == [] and registry.async_get_issue(const.DOMAIN, issue_id(TARGET)) is None
    await _next_day(hass, freezer, entry)
    assert registry.async_get_issue(const.DOMAIN, issue_id(TARGET)) is None
    await _next_day(hass, freezer, entry)                 # third day failing
    issue = registry.async_get_issue(const.DOMAIN, issue_id(TARGET))
    assert issue is not None and issue.translation_key == "calendar_unavailable"
    assert issue.translation_placeholders["calendar"] == "Yard log"
    cal.fail = False
    await _next_day(hass, freezer, entry)
    assert [e["summary"] for e in cal.created] == ["Fertilizer — whole lawn"]
    assert registry.async_get_issue(const.DOMAIN, issue_id(TARGET)) is None


async def test_an_unavailable_calendar_is_not_called(hass, freezer):
    entry, [cal] = await _setup(hass, freezer, TARGET)
    hass.states.async_set(TARGET, STATE_UNAVAILABLE)
    await _log(hass)
    assert cal.created == []
    ledger = entry.runtime_data.store.calendar_ledgers[TARGET]
    assert ledger.pending and ledger.failing_since == FALL


async def test_a_missing_calendar_raises_a_repair_until_cleared(hass, freezer):
    entry, _ = await _setup(hass, freezer, "calendar.gone")
    registry = ir.async_get(hass)
    assert registry.async_get_issue(const.DOMAIN, issue_id("calendar.gone")) is not None
    hass.config_entries.async_update_entry(entry, options={
        k: v for k, v in entry.options.items() if k != const.CONF_CALENDARS})
    await hass.async_block_till_done()
    await entry.runtime_data.async_run()
    assert registry.async_get_issue(const.DOMAIN, issue_id("calendar.gone")) is None


async def test_settings_reject_a_calendar_that_cannot_create_events(hass, freezer):
    read_only = FakeCalendar("Holidays", features=0)
    entry, _ = await _setup(hass, freezer, cals=[FakeCalendar(), read_only])
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"})
    base = {const.CONF_WEATHER: "weather.home", const.CONF_RUN_TIME: "05:00:00"}
    for bad in (["calendar.holidays"], ["calendar.nope"], ["sensor.x"]):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**base, const.CONF_CALENDARS: bad})
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {const.CONF_CALENDARS: "calendar_not_writable"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, const.CONF_CALENDARS: [TARGET]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[const.CONF_CALENDARS] == [TARGET]


# --- mirror mode: calendars that can delete (and update) events ---------------------

ALL_FEATURES = (CalendarEntityFeature.CREATE_EVENT | CalendarEntityFeature.DELETE_EVENT
                | CalendarEntityFeature.UPDATE_EVENT)


class MirrorCalendar(FakeCalendar):
    """Keeps its events, like Local Calendar: all-day CalendarEvents with uids."""

    def __init__(self, name="Yard log", features=ALL_FEATURES) -> None:
        super().__init__(name, features)
        self.events: dict = {}
        self.ops: list = []
        self._next = 0

    def add(self, summary, start, description=""):
        self._next += 1
        uid = f"uid-{self._next}"
        self.events[uid] = CalendarEvent(start=start, end=start + timedelta(days=1),
                                         summary=summary, description=description, uid=uid)
        return uid

    async def async_get_events(self, hass, start_date, end_date):
        if self.fail:
            raise HomeAssistantError("calendar is down")
        return [e for e in self.events.values()
                if e.start_datetime_local < end_date and e.end_datetime_local > start_date]

    async def async_create_event(self, **kwargs) -> None:
        await super().async_create_event(**kwargs)
        self.ops.append("create")
        self.add(kwargs["summary"], kwargs["dtstart"], kwargs.get("description", ""))

    async def async_update_event(self, uid, event, recurrence_id=None,
                                 recurrence_range=None) -> None:
        self.ops.append("update")
        self.events[uid] = CalendarEvent(start=event["dtstart"], end=event["dtend"],
                                         summary=event["summary"],
                                         description=event.get("description"), uid=uid)

    async def async_delete_event(self, uid, recurrence_id=None, recurrence_range=None):
        self.ops.append("delete")
        del self.events[uid]

    def by_key(self) -> dict:
        out = {}
        for e in self.events.values():
            for line in (e.description or "").splitlines():
                if line.startswith("Lawn Growth key: "):
                    out.setdefault(line.removeprefix("Lawn Growth key: "), []).append(e)
        return out


def _expected(entry) -> dict:
    return {e.key: e for e in entry.runtime_data.calendar}


async def test_mirror_matches_lawn_growths_calendar_including_estimates(hass, freezer):
    cal = MirrorCalendar()
    entry, _ = await _setup(hass, freezer, TARGET, cals=[cal])
    await _log(hass, date="2026-09-20")
    expected = _expected(entry)
    assert any(not e.firm for e in expected.values())        # estimates are there too
    mirrored = cal.by_key()
    assert set(mirrored) == set(expected)
    for key, [event] in mirrored.items():
        assert (event.summary, event.start, event.end) == (
            expected[key].summary, expected[key].start, expected[key].end)
    cal.ops.clear()
    await _next_day(hass, freezer, entry)
    assert set(cal.by_key()) == set(_expected(entry))
    assert all(len(v) == 1 for v in cal.by_key().values())


async def test_mirror_never_touches_events_without_a_key(hass, freezer):
    cal = MirrorCalendar()
    mine = cal.add("Aerate", FALL, "rent the core aerator")
    entry, _ = await _setup(hass, freezer, TARGET, cals=[cal])
    await _next_day(hass, freezer, entry)
    assert cal.events[mine].summary == "Aerate"


async def test_mirror_removes_what_lawn_growth_dropped(hass, freezer):
    cal = MirrorCalendar()
    entry, _ = await _setup(hass, freezer, TARGET, cals=[cal])
    stale = cal.add("Fertilizer — Back", FALL - timedelta(days=3),
                    "Lawn Growth key: lawn_growth-fert-2026-back-applied-2026-09-23")
    dup_key = next(iter(_expected(entry)))
    dup = cal.add("dup", FALL, f"Lawn Growth key: {dup_key}")
    await _next_day(hass, freezer, entry)
    assert stale not in cal.events and dup not in cal.events
    assert set(cal.by_key()) == set(_expected(entry))


async def test_mirror_updates_changed_events_in_place(hass, freezer):
    cal = MirrorCalendar()
    entry, _ = await _setup(hass, freezer, TARGET, cals=[cal])
    key, event = next(iter(cal.by_key().items()))
    uid = event[0].uid
    cal.events[uid] = CalendarEvent(start=event[0].start + timedelta(days=9),
                                    end=event[0].end + timedelta(days=9), summary="old",
                                    description=event[0].description, uid=uid)
    cal.ops.clear()
    await _next_day(hass, freezer, entry, days=0)
    assert "update" in cal.ops and cal.events[uid].summary == _expected(entry)[key].summary


async def test_mirror_without_update_support_deletes_and_recreates(hass, freezer):
    cal = MirrorCalendar(features=CalendarEntityFeature.CREATE_EVENT
                         | CalendarEntityFeature.DELETE_EVENT)
    entry, _ = await _setup(hass, freezer, TARGET, cals=[cal])
    key, [event] = next(iter(cal.by_key().items()))
    cal.events[event.uid] = CalendarEvent(start=event.start, end=event.end, summary="old",
                                          description=event.description, uid=event.uid)
    cal.ops.clear()
    await _next_day(hass, freezer, entry, days=0)
    assert cal.ops == ["delete", "create"]
    assert cal.by_key()[key][0].summary == _expected(entry)[key].summary


async def test_a_failing_mirror_raises_the_repair_after_3_days(hass, freezer):
    cal = MirrorCalendar()
    entry, _ = await _setup(hass, freezer, TARGET, cals=[cal])
    cal.fail = True
    registry = ir.async_get(hass)
    await _next_day(hass, freezer, entry)
    await _next_day(hass, freezer, entry)
    assert registry.async_get_issue(const.DOMAIN, issue_id(TARGET)) is None
    await _next_day(hass, freezer, entry)
    assert registry.async_get_issue(const.DOMAIN, issue_id(TARGET)) is not None
    cal.fail = False
    await _next_day(hass, freezer, entry)
    assert registry.async_get_issue(const.DOMAIN, issue_id(TARGET)) is None
    assert set(cal.by_key()) == set(_expected(entry))
