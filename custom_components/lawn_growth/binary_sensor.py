"""Per-area binary sensors: mow due, mowing allowed."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity

from .entity import LawnGrowthEntity

BINARY_KEYS = ("mow_due", "mowing_allowed")


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data
    async_add_entities(AreaBinarySensor(coordinator, key, suffix)
                       for key in coordinator.areas for suffix in BINARY_KEYS)


class AreaBinarySensor(LawnGrowthEntity, BinarySensorEntity):
    def __init__(self, coordinator, area_key: str, suffix: str) -> None:
        super().__init__(coordinator, area_key, suffix, "binary_sensor")

    @property
    def is_on(self):
        r = self.result
        if r is None:
            return None
        return r.mow_due if self._suffix == "mow_due" else r.mowing_allowed

    @property
    def extra_state_attributes(self):
        r = self.result
        if r is None or self._suffix != "mowing_allowed":
            return None
        return {"reason": r.mowing_allowed_reason}
