"""Date pickers: seeding_date replaces the stored date; the others log a new
record/event on the chosen date. Per area, plus the lawn-wide Last pre-emergent.
Last pre-emergent and Last post-emergent log with their Product select's product."""
from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .entity import LawnEntity, LawnGrowthEntity
from .model import applications

DATE_KEYS = ("seeding_date", "last_mow", "last_fertilizer", "last_pgr", "last_winterizer",
             "last_post_emergent")
LAWN_DATE_KEYS = ("last_pre_emergent",)
_EVENT_KIND = {"last_fertilizer": "fert", "last_pgr": "pgr"}


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data
    async_add_entities([*(AreaDateEntity(coordinator, key, suffix)
                          for key in coordinator.areas for suffix in DATE_KEYS),
                        LastPreEmergentEntity(coordinator)])


def _reject_future(value: date) -> None:
    if value > dt_util.now().date():
        raise ServiceValidationError(translation_domain=DOMAIN,
                                     translation_key="future_date")


class AreaDateEntity(LawnGrowthEntity, DateEntity):
    def __init__(self, coordinator, area_key: str, suffix: str) -> None:
        super().__init__(coordinator, area_key, suffix, "date")

    @property
    def native_value(self) -> date | None:
        today = dt_util.now().date()
        if self._suffix == "seeding_date":
            return self.area_state.seeding_date
        if self._suffix == "last_mow":
            return self.area_state.last_mow
        if self._suffix == "last_winterizer":
            return applications.latest(self.coordinator.applications(today),
                                       self._area_key, ("winterizer",))
        if self._suffix == "last_post_emergent":
            dates = [a.date for a in applications.for_area(
                self.coordinator.applications(today), self._area_key, ("herbicide",))
                     if applications.is_post_emergent(a)]
            return max(dates) if dates else None
        return self.coordinator.store.latest_event_date(
            self._area_key, _EVENT_KIND[self._suffix], today)

    async def async_set_value(self, value: date) -> None:
        _reject_future(value)
        if value == self.native_value:
            # Already showing this date: logging it again would add a duplicate
            # fert/PGR event, reset the growth accumulator on a same-day mow, or
            # (for seeding_date) clear seedlings_ready for no reason.
            return
        c, key = self.coordinator, self._area_key
        if self._suffix == "seeding_date":
            await c.async_log_seeding(key, on=value)
        elif self._suffix == "last_mow":
            await c.async_log_mow(key, on=value)
        elif self._suffix == "last_winterizer":
            await c.async_log_event("winterizer", [key], on=value)
        elif self._suffix == "last_post_emergent":
            await c.async_log_post_emergent(key, on=value)
        else:
            await c.async_log_event(_EVENT_KIND[self._suffix], [key], on=value)


class LastPreEmergentEntity(LawnEntity, DateEntity):
    """Logs a pre-emergent for every area, with the Pre-emergent product select's
    product (like Log mow and Log mow height)."""

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "last_pre_emergent", "date")

    @property
    def native_value(self) -> date | None:
        apps = self.coordinator.applications(dt_util.now().date())
        dates = [a.date for a in apps if applications.is_pre_emergent(a)]
        return max(dates) if dates else None

    async def async_set_value(self, value: date) -> None:
        _reject_future(value)
        if value == self.native_value:
            return                     # already logged: don't add a duplicate
        await self.coordinator.async_log_pre_emergent(on=value)
