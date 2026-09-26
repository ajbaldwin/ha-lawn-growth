"""Read Home Assistant state for an evaluation: forecast, soil moisture, season."""
from __future__ import annotations

import logging
import re
from datetime import date

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .model import moisture as moisture_model
from .model import weather

_LOGGER = logging.getLogger(__name__)
_GEODROPS_QUALITY_UID = re.compile(r"_qcn_d[123]$")


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


def in_season(hass: HomeAssistant, entity_id: str | None) -> bool | None:
    """True/False from the season entity; None when it is missing or unavailable
    (the caller then keeps the area's previous season state)."""
    if not entity_id:
        return True
    st = hass.states.get(entity_id)
    if st is None or st.state not in ("on", "off"):
        return None
    return st.state == "on"
