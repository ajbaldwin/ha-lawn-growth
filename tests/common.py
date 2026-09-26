"""Shared helpers for the HA-layer tests."""
from __future__ import annotations

from datetime import date, timedelta

from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lawn_growth import const

WEATHER = "weather.home"
NOW = "2026-09-26 12:00:00+00:00"       # 05:00 local (tests run in US/Pacific)
TODAY = date(2026, 9, 26)
FLAT_68 = [(68.0, 68.0)] * 11


def daily(start: date, rows) -> list:
    return [{"datetime": f"{start + timedelta(days=i)}T12:00:00+00:00",
             "temperature": hi, "templow": lo} for i, (hi, lo) in enumerate(rows)]


def register_weather(hass, *, daily_rows=None, hourly_rows=None, unit="°F") -> list:
    """Fake weather entity + weather.get_forecasts. Returns the forecast types requested."""
    hass.states.async_set(WEATHER, "sunny", {"temperature_unit": unit})
    calls: list = []

    async def handler(call):
        kind = call.data["type"]
        calls.append(kind)
        rows = daily_rows if kind == "daily" else hourly_rows
        if rows is None:
            raise HomeAssistantError(f"{kind} forecast not supported")
        return {WEATHER: {"forecast": rows}}

    hass.services.async_register("weather", "get_forecasts", handler,
                                 supports_response=SupportsResponse.ONLY)
    return calls


def area(**over) -> dict:
    base = {const.AREA_KEY: "lawn", const.AREA_NAME: "Lawn", const.AREA_GRASS: "tttf_kbg",
            const.AREA_CURVE: "cool", const.AREA_CUT_MIN: 3.0, const.AREA_CUT_MAX: 3.9,
            const.AREA_OVERSEED_TARGET: 2.5, const.AREA_MOISTURE: [],
            const.AREA_WILTING: 40.0, const.AREA_COMFORTABLE: 67.0,
            const.AREA_MOW_SOURCE: None, const.AREA_MOW_MODE: const.MOW_MODE_INCREASES,
            const.AREA_LOCATIONS: [], const.AREA_MAX_RATE: 6.5}
    base.update(over)
    return base


def make_entry(hass, *, areas=None, **options) -> MockConfigEntry:
    opts = {const.CONF_WEATHER: WEATHER, const.CONF_RUN_TIME: const.DEFAULT_RUN_TIME,
            const.CONF_AREAS: areas if areas is not None else [area()]}
    opts.update(options)
    entry = MockConfigEntry(domain=const.DOMAIN, title="Lawn Growth", data={}, options=opts)
    entry.add_to_hass(hass)
    return entry


async def setup(hass, entry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
