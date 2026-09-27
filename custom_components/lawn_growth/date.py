"""Per-area seeding-date entity: set it to log or correct a seeding."""
from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .entity import LawnGrowthEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data
    async_add_entities(SeedingDateEntity(coordinator, key) for key in coordinator.areas)


class SeedingDateEntity(LawnGrowthEntity, DateEntity):
    def __init__(self, coordinator, area_key: str) -> None:
        super().__init__(coordinator, area_key, "seeding_date", "date")

    @property
    def native_value(self) -> date | None:
        return self.area_state.seeding_date

    async def async_set_value(self, value: date) -> None:
        if value > dt_util.now().date():
            raise ServiceValidationError(translation_domain=DOMAIN,
                                         translation_key="future_date")
        await self.coordinator.async_log_seeding(self._area_key, on=value)
