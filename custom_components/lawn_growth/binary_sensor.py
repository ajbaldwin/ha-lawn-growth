"""Per-area binary sensors: mow due, mowing allowed, good spray day."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity

from .entity import LawnGrowthEntity

BINARY_KEYS = ("mow_due", "mowing_allowed", "good_spray_day")


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data
    async_add_entities(AreaBinarySensor(coordinator, key, suffix)
                       for key in coordinator.areas for suffix in BINARY_KEYS)


class AreaBinarySensor(LawnGrowthEntity, BinarySensorEntity):
    def __init__(self, coordinator, area_key: str, suffix: str) -> None:
        super().__init__(coordinator, area_key, suffix, "binary_sensor")

    @property
    def _spray(self):
        return self.coordinator.spray_days.get(self._area_key)

    @property
    def is_on(self):
        r = self.result
        if r is None:
            return None
        if self._suffix == "good_spray_day":
            # Today passes the spray-day check inside an open post-emergent window.
            return bool(self._spray and self._spray[0].good)
        return r.mow_due if self._suffix == "mow_due" else r.mowing_allowed

    @property
    def extra_state_attributes(self):
        r = self.result
        if r is None or self._suffix == "mow_due":
            return None
        if self._suffix == "good_spray_day":
            today, tomorrow = self._spray or (None, None)
            return {"window_open": self._spray is not None,
                    "failed": list(today.failed) if today else [],
                    "not_checked": list(today.skipped) if today else [],
                    "reasons": list(today.reasons) if today else [],
                    "tomorrow": tomorrow.good if tomorrow else None}
        return {"reason": r.mowing_allowed_reason}
