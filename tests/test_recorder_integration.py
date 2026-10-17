"""Soil temperature and GDD against a real recorder (no stand-ins for its API)."""
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done)

from custom_components.lawn_growth import const

from .common import FLAT_68, NOW, TODAY, area, daily, make_entry, register_weather
from .test_temperature_signals import GDD, SOIL, _geodrops_probe


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """The recorder must be set up before hass, so request it first."""
    yield


async def _probe_states(hass, probe):
    hass.states.async_set(probe["moisture"], "70")
    for d in ("d1", "d2", "d3"):
        hass.states.async_set(probe[f"qcn_{d}"], "good")
        hass.states.async_set(probe[f"temp_{d}"], "10.0", {"unit_of_measurement": "°C",
                                                          "device_class": "temperature"})
    hass.states.async_set(probe["status"], "ok")
    await async_wait_recording_done(hass)


async def test_setup_without_outdoor_sensor(hass, freezer):
    hass.config.units = US_CUSTOMARY_SYSTEM
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    probe = _geodrops_probe(hass)
    await _probe_states(hass, probe)
    entry = make_entry(hass, areas=[area(**{const.AREA_MOISTURE: [probe["moisture"]]})])
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(GDD) is not None
    assert hass.states.get(SOIL) is not None


async def test_setup_with_outdoor_sensor_without_statistics(hass, freezer):
    hass.config.units = US_CUSTOMARY_SYSTEM
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    hass.states.async_set("sensor.outdoor", "60", {"unit_of_measurement": "°F",
                                                   "device_class": "temperature",
                                                   "state_class": "measurement"})
    entry = make_entry(hass, **{const.CONF_OUTDOOR_TEMP: "sensor.outdoor"})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_setup_during_startup_without_outdoor_sensor(hass, freezer):
    hass.config.units = US_CUSTOMARY_SYSTEM
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    probe = _geodrops_probe(hass)
    await _probe_states(hass, probe)
    hass.set_state(CoreState.starting)
    entry = make_entry(hass, areas=[area(**{const.AREA_MOISTURE: [probe["moisture"]]})])
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.lawn_growth_lawn_days_until_due").state == "5"
