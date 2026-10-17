"""Per-area sensors, plus the lawn-wide growing degree days."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorStateClass)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfLength, UnitOfTemperature
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import AREA_SOIL_DEPTH, DEFAULT_SOIL_DEPTH, DOMAIN
from .entity import LawnGrowthEntity
from .model import gdd as gdd_model
from .model import soiltemp
from .model.modes import MODES


@dataclass(frozen=True, kw_only=True)
class AreaSensorSpec:
    key: str
    value: Callable[[Any, Any], Any]                 # (AreaResult, AreaState) -> state
    attrs: Callable[[Any, Any], dict] | None = None
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    precision: int | None = None
    options: list[str] | None = None
    diagnostic: bool = False


def _last_record(r, s) -> dict:
    rec = s.mow_records[-1] if s.mow_records else None
    return {"date": rec.date.isoformat() if rec else None,
            "source": rec.source if rec else None}


def _overseed_attrs(r, s) -> dict:
    seeding_date = s.seeding_date
    days_since = (dt_util.now().date() - seeding_date).days if seeding_date else None
    seedling_in = None if r.seedling_height_in is None else round(r.seedling_height_in, 2)
    return {"target_in": r.overseed_target_in,
            "arrival_date": r.overseed_arrival_date,
            "feasible": r.overseed_feasible,
            "earliest_seed_date": r.overseed_earliest_date,
            "seeding_date": seeding_date.isoformat() if seeding_date else None,
            "days_since_seeding": days_since,
            "seedling_height_in": seedling_in,
            "first_mow_target_in": r.first_mow_target_in}


_IN = dict(unit=UnitOfLength.INCHES, device_class=SensorDeviceClass.DISTANCE, precision=2)
_MM = dict(unit=UnitOfLength.MILLIMETERS, device_class=SensorDeviceClass.DISTANCE, precision=2)

SENSOR_SPECS = (
    AreaSensorSpec(key="days_until_due", value=lambda r, s: r.days_until_due_display,
                   attrs=lambda r, s: {"days": r.days_until_due}),
    AreaSensorSpec(key="budget_used", value=lambda r, s: round(r.pct_budget, 1),
                   unit=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT, precision=0),
    AreaSensorSpec(key="growth_today", value=lambda r, s: round(r.growth_today_mm, 3), **_MM),
    AreaSensorSpec(key="accumulated_growth", value=lambda r, s: round(r.accumulated_mm, 3),
                   **_MM),
    AreaSensorSpec(key="growth_potential", value=lambda r, s: round(r.gp, 3), precision=3),
    AreaSensorSpec(key="mode", value=lambda r, s: r.mode,
                   device_class=SensorDeviceClass.ENUM, options=MODES),
    AreaSensorSpec(key="recommended_cut_height", value=lambda r, s: r.recommended_cut_in,
                   attrs=lambda r, s: {"phase": r.phase, "note": r.cut_note,
                                       "next_pass_in": r.next_pass_in}, **_IN),
    AreaSensorSpec(key="last_cut_height", value=lambda r, s: r.last_cut_in,
                   attrs=_last_record, **_IN),
    AreaSensorSpec(key="overseed_status", value=lambda r, s: r.overseed_status,
                   attrs=_overseed_attrs),
    AreaSensorSpec(key="soil_moisture_used", value=lambda r, s: round(r.moisture, 1),
                   precision=1, diagnostic=True,
                   attrs=lambda r, s: {"source": r.moisture_source,
                                       "sensors_used": list(r.moisture_sensors_used)}),
    AreaSensorSpec(key="seedling_height_estimate",
                   value=lambda r, s: (None if r.seedling_height_in is None
                                       else round(r.seedling_height_in, 2)),
                   diagnostic=True, **{**_IN, "precision": 1}),
)


# Sensors outside SENSOR_SPECS (their values don't come from the area result).
EXTRA_SENSOR_KEYS = ("soil_temperature", "gdd")


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data
    async_add_entities([
        *(AreaSensor(coordinator, key, spec)
          for key in coordinator.areas for spec in SENSOR_SPECS),
        *(SoilTemperatureSensor(coordinator, key) for key in coordinator.areas),
        GddSensor(coordinator),
    ])


class AreaSensor(LawnGrowthEntity, SensorEntity):
    def __init__(self, coordinator, area_key: str, spec: AreaSensorSpec) -> None:
        super().__init__(coordinator, area_key, spec.key, "sensor")
        self._spec = spec
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_device_class = spec.device_class
        self._attr_state_class = spec.state_class
        self._attr_suggested_display_precision = spec.precision
        self._attr_options = spec.options
        if spec.diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        r = self.result
        return None if r is None else self._spec.value(r, self.area_state)

    @property
    def extra_state_attributes(self):
        r = self.result
        if r is None or self._spec.attrs is None:
            return None
        return self._spec.attrs(r, self.area_state)


class SoilTemperatureSensor(LawnGrowthEntity, SensorEntity):
    """Soil5: the mean of the last 5 days' soil temperature from the area's GeoDrops
    probes; unknown while the area relies on growing degree days."""
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, area_key: str) -> None:
        super().__init__(coordinator, area_key, "soil_temperature", "sensor")

    @property
    def native_value(self):
        value, _ = self.coordinator.soil5(self._area_key, dt_util.now().date())
        return None if value is None else round(value, 2)

    @property
    def extra_state_attributes(self):
        today = dt_util.now().date()
        value, valid = self.coordinator.soil5(self._area_key, today)
        probes = self.coordinator.soil_probes.get(self._area_key, ())
        days = self.area_state.soil_days
        last = days.get((today - timedelta(days=1)).isoformat()) or {}
        return {"source": soiltemp.source_for(value),
                "valid_days": valid,
                "depth": self.coordinator.area_options[self._area_key].get(
                    AREA_SOIL_DEPTH, DEFAULT_SOIL_DEPTH),
                "probes": [p.temp for p in probes],
                "yesterday_f": last.get("mean_f"),
                "yesterday_coverage": last.get("coverage")}


class GddSensor(CoordinatorEntity, SensorEntity):
    """Growing degree days (base 50 °F) since the season start, lawn-wide."""
    _attr_has_entity_name = True
    _attr_translation_key = "gdd"
    _attr_native_unit_of_measurement = "GDD"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_gdd"
        self.entity_id = f"sensor.{DOMAIN}_gdd"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry_id)},
                                            name="Lawn Growth", manufacturer="Lawn Growth",
                                            model="Lawn")

    @property
    def native_value(self):
        state = self.coordinator.store.gdd
        return None if state.year is None else round(state.total, 1)

    @property
    def extra_state_attributes(self):
        state, tun = self.coordinator.store.gdd, self.coordinator.tunables
        return {"base_f": tun.gdd_base_f,
                "season_start": (gdd_model.season_start(state.year, tun).isoformat()
                                 if state.year is not None else None),
                "last_day": state.last_day.isoformat() if state.last_day else None,
                "source": state.source or None,
                "last_season_total": state.last_season_total}
