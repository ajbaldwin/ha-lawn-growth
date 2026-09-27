"""Per-area log buttons and the lawn-level Evaluate now button."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .entity import LawnGrowthEntity

AREA_BUTTONS = ("log_mow", "seedlings_ready")
# Replaced by the Seeding date / Last fertilizer / Last PGR pickers in 0.1.0-beta.4.
RETIRED_AREA_BUTTONS = ("log_seeding", "log_fertilizer", "log_pgr")


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data
    entities: list = [AreaButton(coordinator, key, suffix)
                      for key in coordinator.areas for suffix in AREA_BUTTONS]
    entities.append(EvaluateNowButton(coordinator))
    async_add_entities(entities)


class AreaButton(LawnGrowthEntity, ButtonEntity):
    def __init__(self, coordinator, area_key: str, suffix: str) -> None:
        super().__init__(coordinator, area_key, suffix, "button")

    async def async_press(self) -> None:
        c, key = self.coordinator, self._area_key
        if self._suffix == "log_mow":
            await c.async_log_mow(key)
        elif self._suffix == "seedlings_ready":
            try:
                await c.async_seedlings_ready(key)
            except ValueError as err:
                raise HomeAssistantError(translation_domain=DOMAIN,
                                         translation_key="no_seeding") from err


class EvaluateNowButton(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "evaluate_now"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_evaluate_now"
        self.entity_id = f"button.{DOMAIN}_evaluate_now"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry_id)},
                                            name="Lawn Growth", manufacturer="Lawn Growth",
                                            model="Lawn")

    async def async_press(self) -> None:
        await self.coordinator.async_run(send_notifications=True)
