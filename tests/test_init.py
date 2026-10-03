import asyncio
import logging
from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed, async_mock_service)

from custom_components.lawn_growth import const, inputs
from custom_components.lawn_growth.model.state import MowRecord

from .common import FLAT_68, NOW, TODAY, area, daily, make_entry, register_weather, setup


def _seed_store(hass_storage, entry, data):
    key = f"{const.DOMAIN}.{entry.entry_id}"
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key,
                         "data": {"areas": data, "events": [], "session": None}}


async def test_setup_accrues_once_then_unloads(hass, freezer):
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    entry = make_entry(hass)
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    coord = entry.runtime_data
    assert coord.data["lawn"].mode == "normal"
    assert coord.data["lawn"].accumulated_mm == pytest.approx(6.5)
    await coord.async_run()
    assert coord.data["lawn"].accumulated_mm == pytest.approx(6.5)   # same day: no re-accrual
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_no_forecast_means_setup_retry(hass, freezer):
    freezer.move_to(NOW)
    register_weather(hass)
    entry = make_entry(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_state_survives_reload(hass, freezer, hass_storage):
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    entry = make_entry(hass)
    await setup(hass, entry)
    await entry.runtime_data.async_log_mow("lawn", height_in=3.0)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.data["lawn"].last_cut_in == 3.0


async def test_daily_run_notifies_once_and_startup_does_not(hass, freezer, hass_storage):
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    calls = async_mock_service(hass, "notify", "phone")
    entry = make_entry(hass, **{const.CONF_NOTIFY: "notify.phone"})
    _seed_store(hass_storage, entry, {"lawn": {"accumulated_mm": 30.0,
                                               "last_accrual": "2026-09-25"}})
    await setup(hass, entry)
    assert entry.runtime_data.data["lawn"].mow_due is True
    assert calls == []                                       # startup run never notifies

    freezer.move_to("2026-09-27 12:00:00+00:00")            # next day, 05:00 local
    register_weather(hass, daily_rows=daily(TODAY.replace(day=27), FLAT_68))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert len(calls) == 1 and "mow due" in calls[0].data["message"]

    await entry.runtime_data.async_run(send_notifications=True)
    assert len(calls) == 1                                   # once per due episode


async def test_coordinator_mutations(hass, freezer):
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    entry = make_entry(hass)
    await setup(hass, entry)
    c = entry.runtime_data
    with pytest.raises(ValueError):
        await c.async_correct_last_mow("lawn", 3.1)
    with pytest.raises(ValueError):
        await c.async_seedlings_ready("lawn")
    await c.async_log_mow("lawn")
    assert c.data["lawn"].last_cut_in == 3.9                 # default = cut range max
    await c.async_log_seeding("lawn")
    assert c.data["lawn"].mode == "establishment"
    await c.async_seedlings_ready("lawn")
    assert c.data["lawn"].mode == "first_mow_ready"
    await c.async_log_event("fert", ["lawn"])
    assert [e.kind for e in c.store.events_for("lawn")] == ["fert"]


async def test_concurrent_runs_are_serialized(hass, freezer, monkeypatch):
    """Evaluations go through async_evaluate under a per-entry lock,
    so concurrent triggers (daily run, a mutation's re-evaluate, Evaluate now, ...)
    never overlap. Instrument inputs.async_read_temps — called once per evaluation,
    deep inside the locked section — with a counter of in-flight calls; it must never
    exceed 1. Without `async with self._lock` in the coordinator this fails, because
    asyncio.gather would let more than one evaluation call it at the same time."""
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    entry = make_entry(hass)
    await setup(hass, entry)
    c = entry.runtime_data

    in_flight = 0
    max_in_flight = 0
    original = inputs.async_read_temps

    async def guarded(hass_, weather_entity, today):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0)          # yield so a second call could overlap if unlocked
        try:
            return await original(hass_, weather_entity, today)
        finally:
            in_flight -= 1

    monkeypatch.setattr(inputs, "async_read_temps", guarded)

    await asyncio.gather(
        c.async_run(),
        c.async_log_mow("lawn", height_in=3.0),
        c.async_run(),
    )

    assert max_in_flight == 1
    assert len(c.store.areas["lawn"].mow_records) == 1


async def test_mutation_during_notify_is_not_overwritten(hass, freezer, hass_storage):
    """A daily run publishes its results before it awaits the notify sends: a mow
    logged while a (slow) send is in flight must not be overwritten by the run's
    older, pre-mow results when the send finally returns."""
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    release = asyncio.Event()
    sent: list = []

    async def slow_notify(call):
        sent.append(call.data["message"])
        await release.wait()

    hass.services.async_register("notify", "phone", slow_notify)
    entry = make_entry(hass, **{const.CONF_NOTIFY: "notify.phone"})
    _seed_store(hass_storage, entry, {"lawn": {"accumulated_mm": 30.0,
                                               "last_accrual": "2026-09-25"}})
    await setup(hass, entry)
    c = entry.runtime_data
    run = hass.async_create_task(c.async_run(send_notifications=True))
    while not sent:                                        # the send is now blocked
        await asyncio.sleep(0)
    await c.async_log_mow("lawn", height_in=3.0)
    assert c.data["lawn"].mow_due is False
    release.set()
    await run
    assert c.data["lawn"].mow_due is False                 # not the run's stale results
    assert c.data["lawn"].last_cut_in == 3.0
    assert c.data["lawn"].accumulated_mm == 0.0


async def test_notify_failure_of_any_kind_is_logged_not_raised(hass, freezer, hass_storage,
                                                               caplog):
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))

    async def broken(call):
        raise ValueError("bad payload")

    hass.services.async_register("notify", "phone", broken)
    entry = make_entry(hass, **{const.CONF_NOTIFY: "notify.phone"})
    _seed_store(hass_storage, entry, {"lawn": {"accumulated_mm": 30.0,
                                               "last_accrual": "2026-09-25"}})
    await setup(hass, entry)
    await entry.runtime_data.async_run(send_notifications=True)     # must not raise
    assert "could not notify via notify.phone" in caplog.text
    assert entry.runtime_data.data["lawn"].mow_due is True


async def test_no_notify_target_latches_nothing(hass, freezer, hass_storage):
    """Notifications only when a target is set — without one, the due latch
    must stay clear so a target added later still gets this episode's push."""
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    entry = make_entry(hass)
    _seed_store(hass_storage, entry, {"lawn": {"accumulated_mm": 30.0,
                                               "last_accrual": "2026-09-25"}})
    await setup(hass, entry)
    c = entry.runtime_data
    await c.async_run(send_notifications=True)
    assert c.data["lawn"].mow_due is True
    assert c.store.areas["lawn"].due_notified is False


@pytest.mark.parametrize("boot_state", [CoreState.not_running, CoreState.starting])
async def test_setup_during_bootstrap_accrues_at_ha_start(hass, freezer, boot_state):
    """Set up while HA is still starting (moisture sensors not up yet), the first run
    must not lock in today's accrual with the fallback moisture: it evaluates without
    accruing, and the run at HA start accrues once with the live inputs."""
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    hass.set_state(boot_state)
    entry = make_entry(hass, areas=[area(moisture_sensors=["sensor.soil"])])
    await setup(hass, entry)
    c = entry.runtime_data
    assert c.data["lawn"].moisture_source == "fallback"
    assert c.data["lawn"].accumulated_mm == 0.0
    assert c.store.areas["lawn"].last_accrual is None

    hass.states.async_set("sensor.soil", "53.5")             # sensors come up
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    r = c.data["lawn"]
    assert r.moisture_source == "sensors"
    assert 0.0 < r.growth_today_mm < 6.5                     # water-limited
    assert r.accumulated_mm == pytest.approx(r.growth_today_mm)
    assert c.store.areas["lawn"].last_accrual == TODAY
    await c.async_run()
    assert c.data["lawn"].accumulated_mm == pytest.approx(r.accumulated_mm)   # once only


async def test_flat_projection_warned_once(hass, freezer, caplog):
    """No forecast beyond today -> flat projection, logged at warning once."""
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, [(68.0, 68.0)]))    # today only
    entry = make_entry(hass)
    await setup(hass, entry)
    await entry.runtime_data.async_run()
    await entry.runtime_data.async_run()
    flat = [r for r in caplog.records if "flat projection" in r.getMessage()]
    assert [r.levelno for r in flat] == [logging.WARNING]


async def test_establishment_mow_keeps_seeding_until_ready(hass, freezer, caplog):
    """A mow after seeding but before ready is an establishment mow (logged at
    info); after Seedlings ready, the next mow ends establishment."""
    caplog.set_level(logging.INFO, logger="custom_components.lawn_growth")
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    entry = make_entry(hass)
    await setup(hass, entry)
    c = entry.runtime_data
    seeded = TODAY.replace(day=20)
    await c.async_log_seeding("lawn", on=seeded)
    assert c.data["lawn"].mode == "establishment"
    await c.async_log_mow("lawn", height_in=3.5)
    assert c.data["lawn"].mode == "establishment"
    assert c.store.areas["lawn"].seeding_date == seeded
    assert c.store.areas["lawn"].last_mow == TODAY
    assert any("establishment mow" in r.getMessage() and r.levelno == logging.INFO
               for r in caplog.records)
    await c.async_seedlings_ready("lawn")
    assert c.data["lawn"].mode == "first_mow_ready"
    await c.async_log_mow("lawn", height_in=3.5)
    assert c.data["lawn"].mode == "normal"
    assert c.store.areas["lawn"].seeding_date is None


COUNTER = "input_number.lawn_mow_count"


async def test_counter_mow_at_startup_lands_after_the_catch_up(hass, freezer, hass_storage):
    """A counter change made while HA was down is caught at startup
    (mow dated today), and the missed days are caught up from the stored forecast.
    Growth for days before the mow must not land on the accumulator after it: the run
    at HA start accrues the catch-up days and today first (the daily run accrues a day
    before that day's mows), then the mow resets the accumulator -> exactly 0.0."""
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    hass.set_state(CoreState.starting)
    entry = make_entry(hass, areas=[area(mow_source_entity=COUNTER)])
    _seed_store(hass_storage, entry, {"lawn": {
        "accumulated_mm": 10.0, "last_accrual": "2026-09-23",
        "forecast_means": {"2026-09-24": 68.0, "2026-09-25": 68.0},
        "mow_source_last": "3.0"}})
    hass.states.async_set(COUNTER, "4.0")                    # mowed while HA was down
    await setup(hass, entry)
    c = entry.runtime_data

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    s = c.store.areas["lawn"]
    assert s.last_mow == TODAY and s.mow_records[-1].source == "counter"
    assert s.last_accrual == TODAY
    assert [h.date for h in s.history][-3:] == [TODAY.replace(day=24),
                                                 TODAY.replace(day=25), TODAY]
    assert c.data["lawn"].accumulated_mm == 0.0
    assert c.data["lawn"].mow_due is False
    assert s.mow_source_last == "4.0"


async def test_unload_before_ha_start_leaves_no_watchers(hass, freezer, hass_storage, caplog):
    """Unloaded while HA is still starting: HA reaching STARTED afterwards must not run
    the entry or start its mow watchers, and a later counter/mower change does nothing."""
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    hass.set_state(CoreState.starting)
    hass.states.async_set(COUNTER, "3.0")
    act, blade, loc = "sensor.mower_activity", "sensor.mower_blade", "sensor.mower_area"
    hass.states.async_set(act, "idle")
    hass.states.async_set(blade, "3.5", {"unit_of_measurement": "in"})
    hass.states.async_set(loc, "Front")
    entry = make_entry(hass, areas=[area(mow_source_entity=COUNTER, mower_locations=["Front"])],
                       **{const.CONF_MOWER: {const.MOWER_ACTIVITY: act,
                                             const.MOWER_WORKING: ["mowing"],
                                             const.MOWER_BLADE: blade,
                                             const.MOWER_LOCATION: loc}})
    await setup(hass, entry)
    c = entry.runtime_data
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    hass.states.async_set(COUNTER, "4.0")
    hass.states.async_set(act, "mowing")
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=5))
    await hass.async_block_till_done()
    assert c.store.areas["lawn"].mow_records == []
    assert c.store.areas["lawn"].last_accrual is None        # the STARTED run never ran
    assert c.store.session is None
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_mower_tracker_starts_when_ha_starts(hass, freezer):
    """Set up during bootstrap, the mower tracker starts with the run at HA start and
    then captures sessions as usual (state listeners and the minute tick are live)."""
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    hass.set_state(CoreState.starting)
    act, blade, loc = "sensor.mower_activity", "sensor.mower_blade", "sensor.mower_area"
    hass.states.async_set(act, "mowing")
    hass.states.async_set(blade, "3.5", {"unit_of_measurement": "in"})
    hass.states.async_set(loc, "Front")
    entry = make_entry(hass, areas=[area(mower_locations=["Front"])],
                       **{const.CONF_MOWER: {const.MOWER_ACTIVITY: act,
                                             const.MOWER_WORKING: ["mowing"],
                                             const.MOWER_BLADE: blade,
                                             const.MOWER_LOCATION: loc,
                                             const.MOWER_GRACE: 15,
                                             const.MOWER_MIN_AREA: 10}})
    await setup(hass, entry)
    c = entry.runtime_data

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert c.store.session is not None                       # the tracker saw it working
    freezer.tick(timedelta(minutes=30))
    hass.states.async_set(act, "idle")
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=16))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert c.store.session is None
    assert c.store.areas["lawn"].mow_records[-1] == MowRecord(TODAY, 3.5, "mower_session")


async def test_mow_logged_during_bootstrap_drops_the_catch_up(hass, freezer, hass_storage):
    """A mow logged while HA is still starting (Log mow button, an automation) is applied
    before the accruing run at HA start. The missed days before it must not land on
    the reset accumulator; only today's growth (accrued after the mow) does."""
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    hass.set_state(CoreState.starting)
    entry = make_entry(hass)
    _seed_store(hass_storage, entry, {"lawn": {
        "accumulated_mm": 10.0, "last_accrual": "2026-09-23",
        "forecast_means": {"2026-09-24": 68.0, "2026-09-25": 68.0}}})
    await setup(hass, entry)
    c = entry.runtime_data
    await c.async_log_mow("lawn", height_in=3.5)
    assert c.data["lawn"].accumulated_mm == 0.0

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert c.store.areas["lawn"].last_accrual == TODAY
    assert c.data["lawn"].accumulated_mm == pytest.approx(6.5)


async def test_failed_run_at_ha_start_still_starts_mow_capture(hass, freezer, hass_storage,
                                                               caplog, monkeypatch):
    """An unexpected error in the run at HA start must not leave mow capture off for the
    whole HA session (a mutation saves the record before it evaluates): the error is
    logged and the watchers start anyway."""
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    hass.set_state(CoreState.starting)
    entry = make_entry(hass, areas=[area(mow_source_entity=COUNTER)])
    _seed_store(hass_storage, entry, {"lawn": {"mow_source_last": "3.0"}})
    hass.states.async_set(COUNTER, "3.0")
    await setup(hass, entry)
    c = entry.runtime_data
    original, calls = c.async_run, []

    async def fail_first(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("boom")
        await original(**kwargs)

    monkeypatch.setattr(c, "async_run", fail_first)
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "run at Home Assistant start failed" in errors[0].getMessage()
    assert "boom" in (errors[0].exc_text or "")              # traceback kept in the log

    hass.states.async_set(COUNTER, "4.0")                    # a mow after HA started
    await hass.async_block_till_done()
    assert c.store.areas["lawn"].last_mow == TODAY
