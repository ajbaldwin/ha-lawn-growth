import asyncio
from datetime import date, timedelta

import pytest
from homeassistant.core import SupportsResponse
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.lawn_growth import const as c
from custom_components.lawn_growth.mow_sources import fired
from custom_components.lawn_growth.model.state import MowRecord

from .common import FLAT_68, NOW, TODAY, WEATHER, area, daily, make_entry, register_weather, setup

COUNTER = "input_number.back_mow_count"
ACT, BLADE, LOC = ("sensor.mower_activity", "sensor.mower_blade_height",
                   "sensor.mower_location")


def test_fired():
    assert fired(c.MOW_MODE_INCREASES, "3.0", "4.0") is True
    assert fired(c.MOW_MODE_INCREASES, "4.0", "0.0") is False      # weekly reset
    assert fired(c.MOW_MODE_INCREASES, "4.0", "x") is False
    assert fired(c.MOW_MODE_ANY, "a", "b") is True
    assert fired(c.MOW_MODE_ANY, "a", "a") is False


async def _counter_setup(hass, freezer, value="3.0"):
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    hass.states.async_set(COUNTER, value)
    entry = make_entry(hass, areas=[area(key="back", name="Back", mow_source_entity=COUNTER)])
    await setup(hass, entry)
    return entry.runtime_data


async def test_counter_increase_logs_a_mow(hass, freezer):
    coord = await _counter_setup(hass, freezer)
    assert coord.store.areas["back"].mow_source_last == "3.0"
    assert coord.store.areas["back"].last_mow is None           # first value only primes
    hass.states.async_set(COUNTER, "4.0")
    await hass.async_block_till_done()
    rec = coord.store.areas["back"].mow_records[-1]
    assert (rec.date, rec.height_in, rec.source) == (TODAY, 3.9, "counter")


async def test_restart_transition_and_reset_are_not_mows(hass, freezer):
    coord = await _counter_setup(hass, freezer)
    hass.states.async_set(COUNTER, "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set(COUNTER, "3.0")
    await hass.async_block_till_done()
    hass.states.async_set(COUNTER, "0.0")
    await hass.async_block_till_done()
    assert coord.store.areas["back"].mow_records == []


async def test_increase_while_down_is_caught_at_startup(hass, freezer, hass_storage):
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    entry = make_entry(hass, areas=[area(key="back", name="Back", mow_source_entity=COUNTER)])
    key = f"{c.DOMAIN}.{entry.entry_id}"
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": {
        "areas": {"back": {"mow_source_last": "3.0"}}, "events": [], "session": None}}
    hass.states.async_set(COUNTER, "4.0")
    await setup(hass, entry)
    assert entry.runtime_data.store.areas["back"].last_mow == TODAY


async def _mower_setup(hass, freezer):
    hass.config.units = US_CUSTOMARY_SYSTEM
    freezer.move_to("2026-09-17 12:00:00-07:00")
    register_weather(hass, daily_rows=daily(date(2026, 9, 17), FLAT_68))
    hass.states.async_set(ACT, "MODE_READY")
    hass.states.async_set(BLADE, "3.54", {"unit_of_measurement": "in"})
    hass.states.async_set(LOC, "Not working")
    entry = make_entry(
        hass, areas=[area(key="back", name="Back",
                          mower_locations=["Backyard", "Backyard - Slope"])],
        **{c.CONF_MOWER: {c.MOWER_ACTIVITY: ACT, c.MOWER_WORKING: ["MODE_WORKING", "MODE_PAUSE"],
                          c.MOWER_BLADE: BLADE, c.MOWER_LOCATION: LOC,
                          c.MOWER_GRACE: 15, c.MOWER_MIN_AREA: 10}})
    await setup(hass, entry)
    return entry


async def _at(hass, freezer, hhmm, *changes):
    freezer.move_to(f"2026-09-17 {hhmm}:00-07:00")
    for eid, value in changes:
        attrs = {"unit_of_measurement": "in"} if eid == BLADE else {}
        hass.states.async_set(eid, value, attrs)
    await hass.async_block_till_done()


async def _replay_until_returning(hass, freezer):
    await _at(hass, freezer, "12:25", (LOC, "Backyard"), (ACT, "MODE_WORKING"))
    await _at(hass, freezer, "12:27", (ACT, "MODE_PAUSE"))
    await _at(hass, freezer, "12:28", (ACT, "MODE_WORKING"))
    await _at(hass, freezer, "12:36", (BLADE, "2.95"))
    await _at(hass, freezer, "13:30", (LOC, "Backyard - Slope"))
    await _at(hass, freezer, "14:42", (ACT, "MODE_READY"))
    await _at(hass, freezer, "14:43", (ACT, "MODE_WORKING"))
    await _at(hass, freezer, "14:54", (LOC, "path"))
    await _at(hass, freezer, "14:58", (ACT, "MODE_RETURNING"))


async def test_mower_session_replay_0917(hass, freezer):
    entry = await _mower_setup(hass, freezer)
    await _replay_until_returning(hass, freezer)
    await _at(hass, freezer, "15:03", (ACT, "MODE_READY"), (LOC, "Not working"))
    assert entry.runtime_data.store.session is not None          # still inside the grace period
    await _at(hass, freezer, "15:14")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    store = entry.runtime_data.store
    assert store.session is None
    assert store.areas["back"].mow_records[-1] == MowRecord(date(2026, 9, 17), 2.99,
                                                            "mower_session")
    assert entry.runtime_data.data["back"].last_cut_in == 2.99


async def test_mower_session_survives_reload(hass, freezer):
    entry = await _mower_setup(hass, freezer)
    await _replay_until_returning(hass, freezer)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.store.session is not None
    await _at(hass, freezer, "15:14")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    rec = entry.runtime_data.store.areas["back"].mow_records[-1]
    assert rec.source == "mower_session" and rec.height_in == pytest.approx(2.99, abs=0.01)


async def test_mower_session_reload_mid_gap_keeps_ticked_time(hass, freezer):
    """The 1-minute tick persists the open session, so a restart in a long stretch
    with no state changes (13:30-14:42 on the slope) keeps the time accrued up to the
    last tick instead of falling back to the last state change's save."""
    entry = await _mower_setup(hass, freezer)
    await _at(hass, freezer, "12:25", (LOC, "Backyard"), (ACT, "MODE_WORKING"))
    await _at(hass, freezer, "12:27", (ACT, "MODE_PAUSE"))
    await _at(hass, freezer, "12:28", (ACT, "MODE_WORKING"))
    await _at(hass, freezer, "12:36", (BLADE, "2.95"))
    await _at(hass, freezer, "13:30", (LOC, "Backyard - Slope"))
    await _at(hass, freezer, "14:30")
    async_fire_time_changed(hass, dt_util.utcnow())         # ticks run; no state change
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await _at(hass, freezer, "14:42", (ACT, "MODE_READY"))
    await _at(hass, freezer, "14:43", (ACT, "MODE_WORKING"))
    await _at(hass, freezer, "14:54", (LOC, "path"))
    await _at(hass, freezer, "14:58", (ACT, "MODE_RETURNING"))
    await _at(hass, freezer, "15:14")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    store = entry.runtime_data.store
    assert store.session is None
    rec = store.areas["back"].mow_records[-1]
    assert rec.source == "mower_session" and rec.height_in == pytest.approx(2.99, abs=0.01)


async def test_stale_session_closes_after_12_hours(hass, freezer):
    # A mower session stale for > 12 h is closed with what it has,
    # even if the mower is still reporting a working state.
    entry = await _mower_setup(hass, freezer)
    await _at(hass, freezer, "12:25", (LOC, "Backyard"), (ACT, "MODE_WORKING"))
    session_start = dt_util.utcnow()
    store = entry.runtime_data.store

    # Negative control: well inside the 12 h window the session must still be open.
    freezer.move_to(session_start + timedelta(hours=11, minutes=55))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert store.session is not None

    # Keep sampling in a working state well past the 12 h staleness window, without
    # ever leaving the working states -- the grace-period close path can't fire.
    freezer.move_to(session_start + timedelta(hours=12, minutes=5))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert store.session is None
    rec = store.areas["back"].mow_records[-1]
    assert rec.source == "mower_session"
    assert rec.date == date(2026, 9, 17)
    assert rec.height_in == pytest.approx(3.54, abs=0.01)     # blade never changed


async def test_blade_unavailable_mid_session_keeps_last_height(hass, freezer):
    # An invalid blade reading must not
    # clear the session's tracked height -- the gap should keep accruing under the
    # last known valid height rather than being dropped from the weighting.
    entry = await _mower_setup(hass, freezer)
    await _at(hass, freezer, "12:05", (LOC, "Backyard"), (ACT, "MODE_WORKING"))
    await _at(hass, freezer, "12:15", (BLADE, "unavailable"))
    await _at(hass, freezer, "12:25", (BLADE, "2.95"))
    await _at(hass, freezer, "12:35", (ACT, "MODE_READY"))
    await _at(hass, freezer, "12:56")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    store = entry.runtime_data.store
    assert store.session is None
    rec = store.areas["back"].mow_records[-1]
    assert rec.source == "mower_session"
    # 3.54 in for 12:05-12:25 (20 min, including the unavailable gap held at the last
    # known height) and 2.95 in for 12:25-12:35 (10 min):
    # (3.54*1200 + 2.95*600) / 1800 = 3.343... -> 3.34
    assert rec.height_in == pytest.approx(3.34, abs=0.01)


async def test_overlapping_counter_updates_do_not_double_log(hass, freezer):
    # Race: several state-changed events for the same entity fired back-to-back
    # (before an intervening async_block_till_done) each spawn their own check task.
    # A real weather integration's get_forecasts service yields control while it
    # fetches; the test's forecast handler does the same (an explicit sleep(0)) so
    # the overlapping checks actually interleave the way they would in production,
    # rather than each running start-to-finish before the next begins (which is all
    # this test harness's fully-synchronous mocked storage/service calls allow by
    # default). An attribute-only update at the same value, plus a genuine further
    # increase, must not read a stale `mow_source_last` and log a phantom/duplicate mow.
    freezer.move_to(NOW)

    async def handler(call):
        await asyncio.sleep(0)
        return {WEATHER: {"forecast": daily(TODAY, FLAT_68)}}

    hass.services.async_register("weather", "get_forecasts", handler,
                                 supports_response=SupportsResponse.ONLY)
    hass.states.async_set(WEATHER, "sunny", {"temperature_unit": "°F"})
    hass.states.async_set(COUNTER, "3.0")
    entry = make_entry(hass, areas=[area(key="back", name="Back", mow_source_entity=COUNTER)])
    await setup(hass, entry)
    coord = entry.runtime_data

    hass.states.async_set(COUNTER, "4.0")
    hass.states.async_set(COUNTER, "4.0", {"unit_of_measurement": "ct"})   # attrs-only
    hass.states.async_set(COUNTER, "5.0")
    await hass.async_block_till_done()
    records = coord.store.areas["back"].mow_records
    assert [(r.height_in, r.source) for r in records] == [(3.9, "counter"), (3.9, "counter")]
    assert coord.store.areas["back"].mow_source_last == "5.0"
