"""Per-area sensors."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorStateClass)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfLength

from .entity import LawnGrowthEntity
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
                   attrs=lambda r, s: {"target_in": r.overseed_target_in,
                                       "arrival_date": r.overseed_arrival_date,
                                       "feasible": r.overseed_feasible,
                                       "earliest_seed_date": r.overseed_earliest_date}),
    AreaSensorSpec(key="soil_moisture_used", value=lambda r, s: round(r.moisture, 1),
                   precision=1, diagnostic=True,
                   attrs=lambda r, s: {"source": r.moisture_source,
                                       "sensors_used": list(r.moisture_sensors_used)}),
    AreaSensorSpec(key="seedling_height_estimate",
                   value=lambda r, s: (None if r.seedling_height_in is None
                                       else round(r.seedling_height_in, 2)),
                   diagnostic=True, **{**_IN, "precision": 1}),
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data
    async_add_entities(AreaSensor(coordinator, key, spec)
                       for key in coordinator.areas for spec in SENSOR_SPECS)


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
