"""Lawn-wide Pre-emergent product: the product the Last pre-emergent picker logs."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity

from .entity import LawnEntity
from .model.applications import PRE_EMERGENT_PRODUCTS

SELECT_KEYS = ("pre_emergent_product",)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([PreEmergentProductSelect(entry.runtime_data)])


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
