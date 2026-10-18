"""Read Home Assistant state for an evaluation: forecast, soil moisture and
temperature, outdoor temperature statistics, season."""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from homeassistant.components.recorder import get_instance, history
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .model import moisture as moisture_model
from .model import weather

_LOGGER = logging.getLogger(__name__)
_GEODROPS_QUALITY_UID = re.compile(r"_qcn_d[123]$")
MIN_STAT_HOURS = 20      # hourly statistics a day needs for its min/max to count


def local_date(value: str) -> date:
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        raise ValueError(f"not a datetime: {value!r}")
    return dt_util.as_local(parsed).date()


async def async_read_temps(hass: HomeAssistant, weather_entity: str,
                           today: date) -> weather.DailyTemps | None:
    """Daily forecast first, hourly as a fallback; None when neither yields today."""
    st = hass.states.get(weather_entity)
    unit = (st.attributes.get("temperature_unit") if st else None) \
        or hass.config.units.temperature_unit
    for kind, parse in (("daily", weather.from_daily), ("hourly", weather.from_hourly)):
        try:
            resp = await hass.services.async_call(
                "weather", "get_forecasts", {"type": kind},
                target={"entity_id": weather_entity}, blocking=True, return_response=True)
        except HomeAssistantError as err:
            _LOGGER.debug("%s has no %s forecast: %s", weather_entity, kind, err)
            continue
        entries = ((resp or {}).get(weather_entity) or {}).get("forecast") or []
        temps = parse(entries, today, unit, local_date)
        if temps is not None:
            return temps
    return None


def local_naive(value: str) -> datetime:
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        raise ValueError(f"not a datetime: {value!r}")
    return dt_util.as_local(parsed).replace(tzinfo=None)


async def async_read_detail(hass: HomeAssistant, weather_entity: str) -> weather.ForecastDetail:
    """Daily highs and precipitation chance, hourly wind and precipitation chance, for
    the spray-day check and the spring window's heat close. Every field is optional:
    a forecast type the entity doesn't offer just leaves its fields empty."""
    st = hass.states.get(weather_entity)
    attrs = st.attributes if st else {}
    rows = {}
    for kind in ("daily", "hourly"):
        try:
            resp = await hass.services.async_call(
                "weather", "get_forecasts", {"type": kind},
                target={"entity_id": weather_entity}, blocking=True, return_response=True)
        except HomeAssistantError as err:
            _LOGGER.debug("%s has no %s forecast: %s", weather_entity, kind, err)
            continue
        rows[kind] = ((resp or {}).get(weather_entity) or {}).get("forecast") or []
    return weather.detail_from(
        rows.get("daily"), rows.get("hourly"),
        temp_unit=attrs.get("temperature_unit") or hass.config.units.temperature_unit,
        wind_unit=attrs.get("wind_speed_unit") or hass.config.units.wind_speed_unit,
        local_date=local_date, local_dt=local_naive)


def _geodrops_qualities(hass: HomeAssistant, registry, entity_id: str) -> tuple:
    """Depth-quality states for a GeoDrops moisture sensor (same device), else ()."""
    entry = registry.async_get(entity_id)
    if entry is None or entry.platform != "geodrops" or entry.device_id is None:
        return ()
    out = []
    for other in er.async_entries_for_device(registry, entry.device_id):
        if other.platform == "geodrops" and _GEODROPS_QUALITY_UID.search(other.unique_id or ""):
            qs = hass.states.get(other.entity_id)
            out.append(qs.state if qs else "")
    return tuple(out)


def read_moisture(hass: HomeAssistant, sensor_ids) -> tuple:
    """Average of the trusted readings and the sensors that were used."""
    registry = er.async_get(hass)
    values, used = [], []
    for eid in sensor_ids or []:
        st = hass.states.get(eid)
        value = moisture_model.usable_moisture(st.state if st else "",
                                               _geodrops_qualities(hass, registry, eid))
        if value is not None:
            values.append(value)
            used.append(eid)
    return (sum(values) / len(values) if values else None), tuple(used)


@dataclass(frozen=True)
class SoilProbe:
    temp: str           # temperature at the chosen depth
    quality: str        # that depth's Reading Quality
    health: str         # Probe Health


def soil_probes(hass: HomeAssistant, moisture_ids, depth: str) -> tuple[SoilProbe, ...]:
    """The GeoDrops probes behind an area's moisture sensors (same device), with the
    temperature, quality and health entities for one depth. Non-GeoDrops sensors and
    devices missing any of the three are skipped."""
    registry = er.async_get(hass)
    probes, seen = [], set()
    for eid in moisture_ids or []:
        entry = registry.async_get(eid)
        if entry is None or entry.platform != "geodrops" or entry.device_id is None \
                or entry.device_id in seen:
            continue
        seen.add(entry.device_id)
        by_suffix = {}
        for other in er.async_entries_for_device(registry, entry.device_id):
            uid = other.unique_id or ""
            for suffix in (f"_temp_{depth}", f"_qcn_{depth}", "_status"):
                if other.platform == "geodrops" and uid.endswith(suffix):
                    by_suffix[suffix] = other.entity_id
        if len(by_suffix) == 3:
            probes.append(SoilProbe(by_suffix[f"_temp_{depth}"], by_suffix[f"_qcn_{depth}"],
                                    by_suffix["_status"]))
    return tuple(probes)


def recorder_ready(hass: HomeAssistant) -> bool:
    return "recorder" in hass.config.components


def _temp_f(state) -> float | None:
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    if math.isnan(value):
        return None
    unit = state.attributes.get("unit_of_measurement") or UnitOfTemperature.FAHRENHEIT
    if unit == UnitOfTemperature.FAHRENHEIT:
        return value
    try:
        return TemperatureConverter.convert(value, unit, UnitOfTemperature.FAHRENHEIT)
    except HomeAssistantError:
        return None


def _text(state) -> str:
    return state.state


def _series(states, value) -> list:
    return [(st.last_updated, value(st)) for st in states]


async def async_soil_day(hass: HomeAssistant, probes, day: date) -> list:
    """probe_day_mean inputs for one local day: per probe, the (temp, quality, health)
    state series from the recorder, each starting with the state at midnight."""
    start = dt_util.start_of_local_day(day)
    end = dt_util.start_of_local_day(day + timedelta(days=1))
    ids = [eid for p in probes for eid in (p.temp, p.quality, p.health)]

    def _fetch():
        return history.get_significant_states(
            hass, start, end, ids, include_start_time_state=True,
            significant_changes_only=False, minimal_response=False, no_attributes=False)

    states = await get_instance(hass).async_add_executor_job(_fetch)
    return [(_series(states.get(p.temp, []), _temp_f),
             _series(states.get(p.quality, []), _text),
             _series(states.get(p.health, []), _text), start, end) for p in probes]


async def async_daily_min_max(hass: HomeAssistant, entity_id: str, first: date,
                              last: date) -> dict:
    """{local day: (max °F, min °F)} from the recorder's hourly statistics for
    first..last. A day needs MIN_STAT_HOURS hours of statistics to count."""
    start = dt_util.start_of_local_day(first)
    end = dt_util.start_of_local_day(last + timedelta(days=1))

    def _fetch():
        return statistics_during_period(
            hass, start, end, {entity_id}, "hour",
            {"temperature": UnitOfTemperature.FAHRENHEIT}, {"min", "max"})

    rows = (await get_instance(hass).async_add_executor_job(_fetch)).get(entity_id, [])
    days: dict = {}
    for row in rows:
        if row.get("max") is None or row.get("min") is None:
            continue
        begun = row["start"]
        when = dt_util.utc_from_timestamp(begun) if isinstance(begun, (int, float)) else begun
        hours = days.setdefault(dt_util.as_local(when).date(), [])
        hours.append((row["max"], row["min"]))
    return {d: (max(h[0] for h in hours), min(h[1] for h in hours))
            for d, hours in days.items() if len(hours) >= MIN_STAT_HOURS}


def in_season(hass: HomeAssistant, entity_id: str | None) -> bool | None:
    """True/False from the season entity; None when it is missing or unavailable
    (the caller then keeps the area's previous season state)."""
    if not entity_id:
        return True
    st = hass.states.get(entity_id)
    if st is None or st.state not in ("on", "off"):
        return None
    return st.state == "on"
