"""Base entity: one device per mowing area, explicit entity ids."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import LawnGrowthCoordinator


class LawnGrowthEntity(CoordinatorEntity[LawnGrowthCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: LawnGrowthCoordinator, area_key: str, suffix: str,
                 platform: str) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._area_key = area_key
        self._suffix = suffix
        self._attr_translation_key = suffix
        self._attr_unique_id = f"{entry_id}_{area_key}_{suffix}"
        self.entity_id = f"{platform}.{DOMAIN}_{area_key}_{suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{area_key}")},
            name=coordinator.areas[area_key].name,
            manufacturer="Lawn Growth", model="Mowing area")

    @property
    def result(self):
        return (self.coordinator.data or {}).get(self._area_key)

    @property
    def area_state(self):
        return self.coordinator.store.areas[self._area_key]

    @property
    def available(self) -> bool:
        return super().available and self.result is not None
