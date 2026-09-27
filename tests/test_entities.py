from datetime import timedelta

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from custom_components.lawn_growth.binary_sensor import BINARY_KEYS
from custom_components.lawn_growth.button import AREA_BUTTONS
from custom_components.lawn_growth.date import DATE_KEYS
from custom_components.lawn_growth.sensor import SENSOR_SPECS

from .common import FLAT_68, NOW, TODAY, area, daily, make_entry, register_weather, setup


async def _setup(hass, freezer):
    hass.config.units = US_CUSTOMARY_SYSTEM
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    entry = make_entry(hass, areas=[area(key="front_side", name="Front & Side")])
    await setup(hass, entry)
    return entry


async def test_entity_ids_and_names(hass, freezer):
    entry = await _setup(hass, freezer)
    ids = {e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass),
                                                                   entry.entry_id)}
    p = "lawn_growth_front_side"
    assert ids == ({f"sensor.{p}_{s.key}" for s in SENSOR_SPECS}
                   | {f"binary_sensor.{p}_{k}" for k in BINARY_KEYS}
                   | {f"button.{p}_{k}" for k in AREA_BUTTONS}
                   | {"button.lawn_growth_evaluate_now"}
                   | {f"date.{p}_{k}" for k in DATE_KEYS})
    due = hass.states.get(f"sensor.{p}_days_until_due")
    assert due.state == "5" and due.attributes["days"] == 5
    assert due.attributes["friendly_name"] == "Front & Side Days until mow due"
    assert hass.states.get(f"sensor.{p}_mode").state == "normal"
    assert hass.states.get(f"sensor.{p}_last_cut_height").state == "3.9"
    assert hass.states.get(f"binary_sensor.{p}_mow_due").state == "off"
    allowed = hass.states.get(f"binary_sensor.{p}_mowing_allowed")
    assert allowed.state == "on" and allowed.attributes["reason"] == ""
    moist = hass.states.get(f"sensor.{p}_soil_moisture_used")
    assert moist.attributes["source"] == "fallback"


async def test_buttons(hass, freezer):
    entry = await _setup(hass, freezer)
    p = "lawn_growth_front_side"

    async def press(eid):
        await hass.services.async_call("button", "press", {"entity_id": eid}, blocking=True)

    with pytest.raises(HomeAssistantError):
        await press(f"button.{p}_seedlings_ready")
    await press(f"button.{p}_log_seeding")
    assert hass.states.get(f"sensor.{p}_mode").state == "establishment"
    assert hass.states.get(f"binary_sensor.{p}_mowing_allowed").state == "off"
    await press(f"button.{p}_seedlings_ready")
    assert hass.states.get(f"sensor.{p}_mode").state == "first_mow_ready"
    await press(f"button.{p}_log_mow")
    # a mow on the seeding day itself does not end establishment
    state = entry.runtime_data.store.areas["front_side"]
    assert state.last_mow == TODAY and state.seeding_date == TODAY
    await press(f"button.{p}_log_fertilizer")
    assert [e.kind for e in entry.runtime_data.store.events_for("front_side")] == ["fert"]
    await press("button.lawn_growth_evaluate_now")


def test_growth_potential_shows_three_decimals():
    spec = next(s for s in SENSOR_SPECS if s.key == "growth_potential")    # 3 dp
    assert spec.precision == 3


async def test_seeding_date_entity(hass, freezer):
    entry = await _setup(hass, freezer)
    p = "lawn_growth_front_side"
    eid = f"date.{p}_seeding_date"

    async def set_date(value: str):
        await hass.services.async_call("date", "set_value",
                                       {"entity_id": eid, "date": value}, blocking=True)

    assert hass.states.get(eid).state == "unknown"

    past = TODAY - timedelta(days=5)
    await set_date(past.isoformat())
    assert hass.states.get(eid).state == past.isoformat()
    state = entry.runtime_data.store.areas["front_side"]
    assert state.seeding_date == past
    assert hass.states.get(f"sensor.{p}_mode").state == "establishment"
    assert hass.states.get(f"binary_sensor.{p}_mowing_allowed").state == "off"

    future = TODAY + timedelta(days=1)
    with pytest.raises(ServiceValidationError):
        await set_date(future.isoformat())

    # the button still logs "seeded today", overwriting the earlier date entirely
    await hass.services.async_call("button", "press",
                                   {"entity_id": f"button.{p}_log_seeding"}, blocking=True)
    assert hass.states.get(eid).state == TODAY.isoformat()


async def test_overseed_status_reports_seeding_attributes(hass, freezer):
    entry = await _setup(hass, freezer)
    p = "lawn_growth_front_side"
    seed = TODAY - timedelta(days=3)
    await hass.services.async_call(
        "date", "set_value", {"entity_id": f"date.{p}_seeding_date",
                              "date": seed.isoformat()}, blocking=True)

    st = hass.states.get(f"sensor.{p}_overseed_status")
    assert st.state == "establishing"
    assert st.attributes["seeding_date"] == seed.isoformat()
    assert st.attributes["days_since_seeding"] == 3
    assert st.attributes["seedling_height_in"] == 0.0     # before germination
    assert 3.0 <= st.attributes["first_mow_target_in"] <= 3.9


async def test_last_mow_date_entity(hass, freezer):
    entry = await _setup(hass, freezer)
    p = "lawn_growth_front_side"
    eid = f"date.{p}_last_mow"

    async def set_date(value: str):
        await hass.services.async_call("date", "set_value",
                                       {"entity_id": eid, "date": value}, blocking=True)

    assert hass.states.get(eid).state == "unknown"

    past = TODAY - timedelta(days=2)
    await set_date(past.isoformat())
    assert hass.states.get(eid).state == past.isoformat()
    state = entry.runtime_data.store.areas["front_side"]
    assert state.last_mow == past
    assert state.mow_records[-1].height_in == 3.9 and state.mow_records[-1].source == "manual"

    future = TODAY + timedelta(days=1)
    with pytest.raises(ServiceValidationError):
        await set_date(future.isoformat())

    # a date older than the stored last mow is kept as history only (existing
    # model rule) -- the entity keeps showing the newer date.
    older = TODAY - timedelta(days=10)
    await set_date(older.isoformat())
    assert hass.states.get(eid).state == past.isoformat()
    assert len(entry.runtime_data.store.areas["front_side"].mow_records) == 2


async def test_last_fertilizer_and_pgr_date_entities(hass, freezer):
    entry = await _setup(hass, freezer)
    p = "lawn_growth_front_side"

    async def set_date(eid: str, value: str):
        await hass.services.async_call("date", "set_value",
                                       {"entity_id": eid, "date": value}, blocking=True)

    for suffix, kind in (("last_fertilizer", "fert"), ("last_pgr", "pgr")):
        eid = f"date.{p}_{suffix}"
        assert hass.states.get(eid).state == "unknown"

        past = TODAY - timedelta(days=4)
        await set_date(eid, past.isoformat())
        assert hass.states.get(eid).state == past.isoformat()
        events = entry.runtime_data.store.events_for("front_side")
        assert any(e.kind == kind and e.applied == past for e in events)

        future = TODAY + timedelta(days=1)
        with pytest.raises(ServiceValidationError):
            await set_date(eid, future.isoformat())


async def test_date_entity_set_value_noop_when_unchanged(hass, freezer):
    entry = await _setup(hass, freezer)
    p = "lawn_growth_front_side"

    async def set_date(eid: str, value: str):
        await hass.services.async_call("date", "set_value",
                                       {"entity_id": eid, "date": value}, blocking=True)

    # seeding_date: re-setting the shown date must not clear seedlings_ready
    seed = TODAY - timedelta(days=25)
    await set_date(f"date.{p}_seeding_date", seed.isoformat())
    await hass.services.async_call("button", "press",
                                   {"entity_id": f"button.{p}_seedlings_ready"}, blocking=True)
    state = entry.runtime_data.store.areas["front_side"]
    assert state.seedlings_ready is True
    await set_date(f"date.{p}_seeding_date", seed.isoformat())
    assert entry.runtime_data.store.areas["front_side"].seedlings_ready is True

    # last_mow: re-setting the shown date must not add a duplicate record
    mow_date = TODAY - timedelta(days=1)
    await set_date(f"date.{p}_last_mow", mow_date.isoformat())
    count = len(entry.runtime_data.store.areas["front_side"].mow_records)
    await set_date(f"date.{p}_last_mow", mow_date.isoformat())
    assert len(entry.runtime_data.store.areas["front_side"].mow_records) == count

    # last_fertilizer / last_pgr: re-setting the shown date must not add a
    # duplicate event
    for suffix, kind in (("last_fertilizer", "fert"), ("last_pgr", "pgr")):
        eid = f"date.{p}_{suffix}"
        d = TODAY - timedelta(days=3)
        await set_date(eid, d.isoformat())
        count = len([e for e in entry.runtime_data.store.events_for("front_side")
                    if e.kind == kind])
        await set_date(eid, d.isoformat())
        assert len([e for e in entry.runtime_data.store.events_for("front_side")
                   if e.kind == kind]) == count


async def test_date_entity_updates_after_mutation_when_forecast_fails(hass, freezer):
    entry = await _setup(hass, freezer)
    p = "lawn_growth_front_side"
    eid = f"date.{p}_last_mow"

    # Simulate the weather integration losing its forecast (both kinds unsupported):
    # the run inside the mutation raises UpdateFailed, but the Store write already
    # happened and the date picker must still show it.
    register_weather(hass)

    past = TODAY - timedelta(days=1)
    await hass.services.async_call("date", "set_value",
                                   {"entity_id": eid, "date": past.isoformat()}, blocking=True)
    assert hass.states.get(eid).state == past.isoformat()
    assert entry.runtime_data.store.areas["front_side"].last_mow == past
