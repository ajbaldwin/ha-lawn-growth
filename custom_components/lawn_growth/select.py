"""Product selects the date pickers log with: the lawn-wide Pre-emergent product
(Last pre-emergent) and each area's Post-emergent product (Last post-emergent)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity

from .entity import LawnEntity, LawnGrowthEntity
from .model.applications import POST_EMERGENT_PRODUCTS, PRE_EMERGENT_PRODUCTS

SELECT_KEYS = ("pre_emergent_product", "post_emergent_product")


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data
    async_add_entities([PreEmergentProductSelect(coordinator),
                        *(PostEmergentProductSelect(coordinator, key)
                          for key in coordinator.areas)])


class PreEmergentProductSelect(LawnEntity, SelectEntity):
    """Follows the suggestion (prodiamine, then dithiopyr for the split) until set;
    logging a pre-emergent returns it to the suggestion."""
    _attr_options = list(PRE_EMERGENT_PRODUCTS)

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "pre_emergent_product", "select")

    @property
    def current_option(self) -> str:
        return self.coordinator.pre_emergent_product

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_pre_emergent_product(option)


class PostEmergentProductSelect(LawnGrowthEntity, SelectEntity):
    """The product an area's Last post-emergent logs and its spray-day check uses
    (heat limit, rain-free hours, seedling rule). Default mesotrione; it stays set."""
    _attr_options = list(POST_EMERGENT_PRODUCTS)

    def __init__(self, coordinator, area_key: str) -> None:
        super().__init__(coordinator, area_key, "post_emergent_product", "select")

    @property
    def current_option(self) -> str:
        return self.coordinator.post_emergent_product(self._area_key)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_post_emergent_product(self._area_key, option)
