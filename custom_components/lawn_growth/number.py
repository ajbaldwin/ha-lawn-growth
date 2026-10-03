"""Per-area Log mow height: the cut height the Log mow button, the Last mow date
picker and a mow counter record."""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfLength

from .entity import LawnGrowthEntity

MIN_HEIGHT_IN = 0.5
MAX_HEIGHT_IN = 6.0


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data
    async_add_entities(LogMowHeightEntity(coordinator, key) for key in coordinator.areas)


class LogMowHeightEntity(LawnGrowthEntity, NumberEntity):
    _attr_native_min_value = MIN_HEIGHT_IN
    _attr_native_max_value = MAX_HEIGHT_IN
    _attr_native_step = 0.05
    _attr_native_unit_of_measurement = UnitOfLength.INCHES
    _attr_device_class = NumberDeviceClass.DISTANCE
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, area_key: str) -> None:
        super().__init__(coordinator, area_key, "log_mow_height", "number")

    @property
    def native_value(self) -> float:
        return self.coordinator.default_height(self._area_key)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_log_mow_height(self._area_key, value)
