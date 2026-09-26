from datetime import date

import pytest
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lawn_growth import inputs

from .common import NOW, TODAY, WEATHER, daily, register_weather


async def test_read_temps_daily(hass, freezer):
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, [(59, 54), (62, 54)]))
    t = await inputs.async_read_temps(hass, WEATHER, TODAY)
    assert (t.today_high_f, t.today_low_f) == (59.0, 54.0)
    assert t.horizon == [(date(2026, 9, 27), 58.0)]


async def test_read_temps_falls_back_to_hourly(hass, freezer):
    freezer.move_to(NOW)
    hourly = [{"datetime": "2026-09-26T20:00:00+00:00", "temperature": 60},
              {"datetime": "2026-09-26T23:00:00+00:00", "temperature": 50}]
    calls = register_weather(hass, hourly_rows=hourly)
    t = await inputs.async_read_temps(hass, WEATHER, TODAY)
    assert calls == ["daily", "hourly"]
    assert (t.today_high_f, t.today_low_f) == (60.0, 50.0)


async def test_read_temps_none_without_any_forecast(hass, freezer):
    freezer.move_to(NOW)
    register_weather(hass)
    assert await inputs.async_read_temps(hass, WEATHER, TODAY) is None


async def test_read_temps_converts_celsius(hass, freezer):
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, [(20, 10)]), unit="°C")
    t = await inputs.async_read_temps(hass, WEATHER, TODAY)
    assert (t.today_high_f, t.today_low_f) == pytest.approx((68.0, 50.0))


async def test_moisture_plain_sensors_averaged(hass):
    hass.states.async_set("sensor.a", "30")
    hass.states.async_set("sensor.b", "40")
    hass.states.async_set("sensor.c", "unavailable")
    assert inputs.read_moisture(hass, ["sensor.a", "sensor.b", "sensor.c", "sensor.gone"]) \
        == (35.0, ("sensor.a", "sensor.b"))


async def test_moisture_geodrops_quality_gate(hass):
    geo = MockConfigEntry(domain="geodrops")
    geo.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=geo.entry_id, identifiers={("geodrops", "ABC123")})
    reg = er.async_get(hass)
    dom = reg.async_get_or_create("sensor", "geodrops", "ABC123_moisture",
                                  config_entry=geo, device_id=device.id)
    quals = [reg.async_get_or_create("sensor", "geodrops", f"ABC123_qcn_d{i}",
                                     config_entry=geo, device_id=device.id) for i in (1, 2, 3)]
    hass.states.async_set(dom.entity_id, "74.7")
    for q, s in zip(quals, ("Good", "training", "Training")):
        hass.states.async_set(q.entity_id, s)
    assert inputs.read_moisture(hass, [dom.entity_id]) == (None, ())
    hass.states.async_set(quals[1].entity_id, "good")          # 0.6+ lowercase state
    assert inputs.read_moisture(hass, [dom.entity_id]) == (74.7, (dom.entity_id,))


async def test_in_season(hass):
    assert inputs.in_season(hass, None) is True
    hass.states.async_set("input_boolean.season", "on")
    assert inputs.in_season(hass, "input_boolean.season") is True
    hass.states.async_set("input_boolean.season", "off")
    assert inputs.in_season(hass, "input_boolean.season") is False
    hass.states.async_set("input_boolean.season", "unavailable")
    assert inputs.in_season(hass, "input_boolean.season") is None
    assert inputs.in_season(hass, "input_boolean.missing") is None
