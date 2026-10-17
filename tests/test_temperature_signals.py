"""Soil temperature (GeoDrops, quality-gated) and growing degree days, HA layer."""
from datetime import date, datetime, timedelta

import pytest
from homeassistant.core import State
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lawn_growth import const, inputs

from .common import FLAT_68, NOW, TODAY, area, daily, make_entry, register_weather, setup

SOIL = "sensor.lawn_growth_lawn_soil_temperature"
GDD = "sensor.lawn_growth_gdd"


def _geodrops_probe(hass, serial="ABC123", *, depths=("d1", "d2", "d3")) -> dict:
    """A GeoDrops device with moisture, per-depth quality/temperature and health
    entities. Returns {suffix: entity_id}."""
    geo = MockConfigEntry(domain="geodrops")
    geo.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=geo.entry_id, identifiers={("geodrops", serial)})
    reg = er.async_get(hass)
    suffixes = ["moisture", "status", *(f"qcn_{d}" for d in depths),
                *(f"temp_{d}" for d in depths)]
    return {s: reg.async_get_or_create("sensor", "geodrops", f"{serial}_{s}", config_entry=geo,
                                       device_id=device.id).entity_id for s in suffixes}


class _Recorder:
    """Stands in for recorder.get_instance(hass): runs jobs in the hass executor."""

    def __init__(self, hass):
        self._hass = hass

    async def async_add_executor_job(self, fn, *args):
        return await self._hass.async_add_executor_job(fn, *args)


# --- inputs -------------------------------------------------------------------------

async def test_soil_probes_found_from_moisture_sensors(hass):
    probe = _geodrops_probe(hass)
    hass.states.async_set("sensor.plain", "40")
    found = inputs.soil_probes(hass, ["sensor.plain", probe["moisture"], probe["moisture"]],
                               "d2")
    assert found == (inputs.SoilProbe(probe["temp_d2"], probe["qcn_d2"], probe["status"]),)
    assert inputs.soil_probes(hass, [probe["moisture"]], "d3")[0].temp == probe["temp_d3"]


async def test_soil_probes_skip_a_device_missing_the_depth(hass):
    probe = _geodrops_probe(hass, depths=("d1",))
    assert inputs.soil_probes(hass, [probe["moisture"]], "d2") == ()


async def test_soil_day_reads_history_and_converts_celsius(hass, monkeypatch):
    day = date(2026, 9, 25)
    start = dt_util.start_of_local_day(day)
    seen = {}

    def fake_history(_hass, s, e, ids, **kwargs):
        seen.update(start=s, end=e, ids=ids, kwargs=kwargs)
        return {"sensor.t": [State("sensor.t", "10.0", {"unit_of_measurement": "°C"},
                                   last_updated=start - timedelta(hours=1)),
                             State("sensor.t", "unavailable", {}, last_updated=start
                                   + timedelta(hours=6))],
                "sensor.q": [State("sensor.q", "good", last_updated=start)],
                "sensor.h": [State("sensor.h", "ok", last_updated=start)]}

    monkeypatch.setattr(inputs.history, "get_significant_states", fake_history)
    monkeypatch.setattr(inputs, "get_instance", _Recorder)
    [series] = await inputs.async_soil_day(
        hass, [inputs.SoilProbe("sensor.t", "sensor.q", "sensor.h")], day)
    temp, quality, health, s, e = series
    assert (s, e) == (start, dt_util.start_of_local_day(day + timedelta(days=1)))
    assert seen["ids"] == ["sensor.t", "sensor.q", "sensor.h"]
    assert seen["kwargs"]["include_start_time_state"] is True
    assert [v for _, v in temp] == [pytest.approx(50.0), None]
    assert quality == [(start, "good")] and health == [(start, "ok")]


async def test_daily_min_max_from_hourly_statistics(hass, monkeypatch):
    full = dt_util.start_of_local_day(date(2026, 9, 24))
    part = dt_util.start_of_local_day(date(2026, 9, 25))
    rows = [{"start": (full + timedelta(hours=h)).timestamp(), "max": 60 + h, "min": 50 - h}
            for h in range(24)]
    rows += [{"start": (part + timedelta(hours=h)).timestamp(), "max": 70, "min": 55}
             for h in range(inputs.MIN_STAT_HOURS - 1)]
    rows.append({"start": full.timestamp(), "max": None, "min": None})
    monkeypatch.setattr(inputs, "statistics_during_period",
                        lambda *args: {"sensor.out": rows})
    monkeypatch.setattr(inputs, "get_instance", _Recorder)
    got = await inputs.async_daily_min_max(hass, "sensor.out", date(2026, 9, 24),
                                           date(2026, 9, 25))
    assert got == {date(2026, 9, 24): (83, 27)}         # the short day doesn't count


# --- coordinator and sensors -----------------------------------------------------

def _good_day(temp_f, quality="good", health="ok"):
    def series(_hass, probes, day):
        start = dt_util.start_of_local_day(day)
        end = dt_util.start_of_local_day(day + timedelta(days=1))
        return [([(start, temp_f)], [(start, quality)], [(start, health)], start, end)
                for _ in probes]
    return series


async def _setup_signals(hass, freezer, monkeypatch, *, soil=None, minmax=None, **options):
    hass.config.units = US_CUSTOMARY_SYSTEM
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    probe = _geodrops_probe(hass)
    calls = {"soil": [], "minmax": []}

    async def fake_soil(h, probes, day):
        calls["soil"].append(day)
        return (soil or _good_day(50.0))(h, probes, day)

    async def fake_minmax(h, entity_id, first, last):
        calls["minmax"].append((entity_id, first, last))
        return minmax or {}

    monkeypatch.setattr(inputs, "recorder_ready", lambda h: True)
    monkeypatch.setattr(inputs, "async_soil_day", fake_soil)
    monkeypatch.setattr(inputs, "async_daily_min_max", fake_minmax)
    entry = make_entry(hass, areas=[area(**{const.AREA_MOISTURE: [probe["moisture"]]})],
                       **options)
    await setup(hass, entry)
    return entry, probe, calls


async def test_soil_temperature_from_good_probe_days(hass, freezer, monkeypatch):
    entry, probe, calls = await _setup_signals(hass, freezer, monkeypatch)
    st = hass.states.get(SOIL)
    assert float(st.state) == pytest.approx(50.0)
    assert st.attributes["source"] == "geodrops" and st.attributes["valid_days"] == 5
    assert st.attributes["depth"] == "d2" and st.attributes["probes"] == [probe["temp_d2"]]
    assert st.attributes["yesterday_f"] == 50.0 and st.attributes["yesterday_coverage"] == 1.0
    assert sorted(calls["soil"]) == [TODAY - timedelta(days=n) for n in range(7, 0, -1)]
    # a later run the same day reads nothing new
    await hass.services.async_call("button", "press",
                                   {"entity_id": "button.lawn_growth_evaluate_now"},
                                   blocking=True)
    assert len(calls["soil"]) == 7


async def test_soil_temperature_unknown_while_probe_is_training(hass, freezer, monkeypatch):
    await _setup_signals(hass, freezer, monkeypatch,
                         soil=_good_day(50.0, quality="training", health="calibrating"))
    st = hass.states.get(SOIL)
    assert st.state == "unknown"
    assert st.attributes["source"] == "gdd" and st.attributes["valid_days"] == 0


async def test_soil_temperature_ignores_hardware_check(hass, freezer, monkeypatch):
    await _setup_signals(hass, freezer, monkeypatch,
                         soil=_good_day(52.0, health="hardware_check"))
    assert float(hass.states.get(SOIL).state) == pytest.approx(52.0)


async def test_gdd_from_outdoor_sensor_statistics(hass, freezer, monkeypatch):
    yesterday = TODAY - timedelta(days=1)
    _, _, calls = await _setup_signals(
        hass, freezer, monkeypatch, minmax={yesterday: (80.0, 60.0),
                                            yesterday - timedelta(days=1): (60.0, 40.0)},
        **{const.CONF_OUTDOOR_TEMP: "sensor.outdoor"})
    assert calls["minmax"] == [("sensor.outdoor", date(2026, 1, 1), yesterday)]
    st = hass.states.get(GDD)
    assert float(st.state) == pytest.approx(20.0)        # (80+60)/2-50; the 50 °F day adds 0
    assert st.attributes["source"] == "sensor" and st.attributes["base_f"] == 50.0
    assert st.attributes["season_start"] == "2026-01-01"
    assert st.attributes["last_day"] == yesterday.isoformat()


async def test_gdd_falls_back_to_forecast_history(hass, freezer, monkeypatch):
    entry, _, calls = await _setup_signals(hass, freezer, monkeypatch)
    assert calls["minmax"] == []                         # no outdoor sensor configured
    assert float(hass.states.get(GDD).state) == 0.0      # no history yet on day one
    freezer.move_to(datetime.fromisoformat(NOW) + timedelta(days=1))
    await entry.runtime_data.async_run()
    await hass.async_block_till_done()
    st = hass.states.get(GDD)
    assert float(st.state) == pytest.approx(18.0)        # yesterday's 68 °F forecast mean
    assert st.attributes["source"] == "forecast"


async def test_no_recorder_skips_signals(hass, freezer, monkeypatch):
    hass.config.units = US_CUSTOMARY_SYSTEM
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    called = []
    monkeypatch.setattr(inputs, "recorder_ready", lambda h: False)
    monkeypatch.setattr(inputs, "async_daily_min_max",
                        lambda *a: called.append(a))
    await setup(hass, make_entry(hass))
    assert called == []
    assert hass.states.get(GDD).state == "unknown"
    assert hass.states.get(SOIL).attributes["source"] == "gdd"


async def test_recorder_failure_does_not_fail_the_run(hass, freezer, monkeypatch, caplog):
    hass.config.units = US_CUSTOMARY_SYSTEM
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))

    async def boom(*args):
        raise RuntimeError("recorder down")

    monkeypatch.setattr(inputs, "recorder_ready", lambda h: True)
    monkeypatch.setattr(inputs, "async_daily_min_max", boom)
    await setup(hass, make_entry(hass, **{const.CONF_OUTDOOR_TEMP: "sensor.outdoor"}))
    assert hass.states.get("sensor.lawn_growth_lawn_days_until_due").state == "5"
    assert "recorder down" in caplog.text


async def test_gdd_recounted_when_outdoor_sensor_added(hass, freezer, monkeypatch):
    """GDD first counted from the forecast; adding an outdoor sensor later recounts
    the whole season from that sensor's history."""
    yesterday = TODAY - timedelta(days=1)
    entry, _, calls = await _setup_signals(hass, freezer, monkeypatch,
                                           minmax={yesterday: (80.0, 60.0)})
    assert calls["minmax"] == []                         # no sensor yet: forecast only
    assert hass.states.get(GDD).attributes["last_day"] == yesterday.isoformat()
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, const.CONF_OUTDOOR_TEMP: "sensor.outdoor"})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert calls["minmax"] == [("sensor.outdoor", date(2026, 1, 1), yesterday)]
    st = hass.states.get(GDD)
    assert float(st.state) == pytest.approx(20.0) and st.attributes["source"] == "sensor"
    # a reload with the same sensor doesn't recount
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(calls["minmax"]) == 1


async def test_gdd_keeps_counting_out_of_season(hass, freezer, monkeypatch):
    """Daily runs accrue out of season too (only mowing advice changes), so growing
    degree days count through winter."""
    hass.states.async_set("input_boolean.mowing_season", "off")
    entry, _, _ = await _setup_signals(
        hass, freezer, monkeypatch, **{const.CONF_SEASON: "input_boolean.mowing_season"})
    assert entry.runtime_data.data["lawn"].mode == "out_of_season"
    freezer.move_to(datetime.fromisoformat(NOW) + timedelta(days=1))
    await entry.runtime_data.async_run()
    await hass.async_block_till_done()
    assert float(hass.states.get(GDD).state) == pytest.approx(18.0)
