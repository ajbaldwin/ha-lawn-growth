"""Mirror mode against Home Assistant's real Local Calendar integration."""
from datetime import date, timedelta

from homeassistant.components.calendar import DATA_COMPONENT
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lawn_growth import const

from .common import area, daily, make_entry, register_weather, setup

NOW = "2026-09-26 12:00:00+00:00"        # 05:00 local
TODAY = date(2026, 9, 26)
TARGET = "calendar.yard_log"
WARM = [(80.0, 70.0)] * 11
KEY = "Lawn Growth key: "


async def _events(hass) -> list:
    entity = hass.data[DATA_COMPONENT].get_entity(TARGET)
    start = dt_util.start_of_local_day(TODAY - timedelta(days=30))
    return await entity.async_get_events(hass, start, start + timedelta(days=500))


def _ours(events) -> dict:
    out = {}
    for e in events:
        for line in (e.description or "").splitlines():
            if line.startswith(KEY):
                out.setdefault(line.removeprefix(KEY), []).append(e)
    return out


async def test_mirror_keeps_a_local_calendar_in_step(hass, freezer, tmp_path):
    hass.config.config_dir = str(tmp_path)          # Local Calendar writes its .ics here
    (tmp_path / ".storage").mkdir()
    hass.config.units = US_CUSTOMARY_SYSTEM
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, WARM))
    local = MockConfigEntry(domain="local_calendar", data={"calendar_name": "Yard log"})
    local.add_to_hass(hass)
    assert await hass.config_entries.async_setup(local.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        "calendar", "create_event",
        {"entity_id": TARGET, "summary": "Aerate", "start_date": "2026-09-27",
         "end_date": "2026-09-28"}, blocking=True)

    entry = make_entry(hass, areas=[area(key="front", name="Front"),
                                    area(key="back", name="Back")],
                       **{const.CONF_CALENDARS: [TARGET]})
    await setup(hass, entry)
    c = entry.runtime_data

    def expected() -> dict:
        return {e.key: e for e in c.calendar}

    mirrored = _ours(await _events(hass))
    assert mirrored and set(mirrored) == set(expected())     # estimates included
    assert all(len(v) == 1 for v in mirrored.values())

    # a new log is added; a skipped window's estimate is removed
    await c.async_log_event("fert", None, on=date(2026, 9, 20))
    assert "lawn_growth-fert-2026-all-applied-2026-09-20" in _ours(await _events(hass))
    estimates = [k for k in _ours(await _events(hass)) if k.startswith("lawn_growth-winterizer")]
    assert estimates
    await c.async_skip_application("winterizer")
    mirrored = _ours(await _events(hass))
    assert set(mirrored) == set(expected())
    assert not set(estimates) & set(mirrored)

    # an event edited in the calendar is put back, in place (same uid)
    key, [event] = next(iter(mirrored.items()))
    entity = hass.data[DATA_COMPONENT].get_entity(TARGET)
    await entity.async_update_event(event.uid, {
        "dtstart": event.start, "dtend": event.end, "summary": "edited",
        "description": event.description})
    await c.async_run()
    [restored] = _ours(await _events(hass))[key]
    assert restored.uid == event.uid and restored.summary == expected()[key].summary

    # the user's own event is untouched
    assert [e.summary for e in await _events(hass)
            if KEY not in (e.description or "")] == ["Aerate"]
