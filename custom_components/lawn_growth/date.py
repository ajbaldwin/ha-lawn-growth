"""Per-area date pickers: set or correct a seeding, mow, fertilizer or PGR date."""
from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .entity import LawnGrowthEntity

DATE_KEYS = ("seeding_date", "last_mow", "last_fertilizer", "last_pgr")
_EVENT_KIND = {"last_fertilizer": "fert", "last_pgr": "pgr"}


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data
    async_add_entities(AreaDateEntity(coordinator, key, suffix)
                       for key in coordinator.areas for suffix in DATE_KEYS)


def _reject_future(value: date) -> None:
    if value > dt_util.now().date():
        raise ServiceValidationError(translation_domain=DOMAIN,
                                     translation_key="future_date")


class AreaDateEntity(LawnGrowthEntity, DateEntity):
    def __init__(self, coordinator, area_key: str, suffix: str) -> None:
        super().__init__(coordinator, area_key, suffix, "date")

    @property
    def native_value(self) -> date | None:
        if self._suffix == "seeding_date":
            return self.area_state.seeding_date
        if self._suffix == "last_mow":
            return self.area_state.last_mow
        return self.coordinator.store.latest_event_date(
            self._area_key, _EVENT_KIND[self._suffix])

    async def async_set_value(self, value: date) -> None:
        _reject_future(value)
        c, key = self.coordinator, self._area_key
        if self._suffix == "seeding_date":
            await c.async_log_seeding(key, on=value)
        elif self._suffix == "last_mow":
            await c.async_log_mow(key, on=value)
        else:
            await c.async_log_event(_EVENT_KIND[self._suffix], [key], on=value)
