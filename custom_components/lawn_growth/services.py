"""Lawn Growth services. Every service except evaluate_now targets mowing-area devices."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.util import dt as dt_util

from .const import DOMAIN

ATTR_DATE = "date"
ATTR_HEIGHT = "height_in"
ATTR_KIND = "kind"
ATTR_SEED_DATE = "seed_date"
ATTR_TARGET = "target_in"
ATTR_BUFFER = "buffer_days"

_DEVICE = {vol.Required(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string])}
_HEIGHT = vol.All(vol.Coerce(float), vol.Range(min=0.5, max=8.0))

SCHEMAS = {
    "log_mow": vol.Schema({**_DEVICE, vol.Optional(ATTR_DATE): cv.date,
                           vol.Optional(ATTR_HEIGHT): _HEIGHT}),
    "correct_last_mow": vol.Schema({**_DEVICE, vol.Required(ATTR_HEIGHT): _HEIGHT}),
    "log_seeding": vol.Schema({**_DEVICE, vol.Optional(ATTR_DATE): cv.date}),
    "seedlings_ready": vol.Schema(_DEVICE),
    "log_event": vol.Schema({**_DEVICE, vol.Required(ATTR_KIND): vol.In(["fert", "pgr"]),
                             vol.Optional(ATTR_DATE): cv.date}),
    "prep_overseed": vol.Schema({**_DEVICE, vol.Required(ATTR_SEED_DATE): cv.date,
                                 vol.Optional(ATTR_TARGET): _HEIGHT,
                                 vol.Optional(ATTR_BUFFER): vol.All(vol.Coerce(int),
                                                                    vol.Range(min=0, max=30))}),
    "cancel_overseed": vol.Schema(_DEVICE),
    "evaluate_now": vol.Schema({}),
}


def _error(key: str, **placeholders) -> ServiceValidationError:
    return ServiceValidationError(translation_domain=DOMAIN, translation_key=key,
                                  translation_placeholders=placeholders or None)


def _logged_date(call: ServiceCall):
    """The optional `date` of something that already happened: never in the future
    (a future-dated mow would make every real mow before it look backdated)."""
    on = call.data.get(ATTR_DATE)
    if on is not None and on > dt_util.now().date():
        raise _error("future_date")
    return on


def _loaded(hass: HomeAssistant) -> list:
    return [e for e in hass.config_entries.async_entries(DOMAIN)
            if e.state is ConfigEntryState.LOADED]


def _targets(hass: HomeAssistant, call: ServiceCall) -> list:
    """[(coordinator, area_key)] for every targeted mowing-area device."""
    registry = dr.async_get(hass)
    out = []
    for device_id in call.data[ATTR_DEVICE_ID]:
        device = registry.async_get(device_id)
        match = None
        for entry in _loaded(hass):
            prefix = f"{entry.entry_id}_"
            for domain, ident in (device.identifiers if device else ()):
                key = ident[len(prefix):] if ident.startswith(prefix) else None
                if domain == DOMAIN and key in entry.runtime_data.areas:
                    match = (entry.runtime_data, key)
        if match is None:
            raise _error("not_an_area", device_id=device_id)
        out.append(match)
    return out


@callback
def async_register(hass: HomeAssistant) -> None:
    async def log_mow(call: ServiceCall) -> None:
        on = _logged_date(call)
        for coord, key in _targets(hass, call):
            await coord.async_log_mow(key, on=on,
                                      height_in=call.data.get(ATTR_HEIGHT))

    async def correct_last_mow(call: ServiceCall) -> None:
        for coord, key in _targets(hass, call):
            try:
                await coord.async_correct_last_mow(key, call.data[ATTR_HEIGHT])
            except ValueError as err:
                raise _error("no_mow") from err

    async def log_seeding(call: ServiceCall) -> None:
        on = _logged_date(call)
        for coord, key in _targets(hass, call):
            await coord.async_log_seeding(key, on=on)

    async def seedlings_ready(call: ServiceCall) -> None:
        for coord, key in _targets(hass, call):
            try:
                await coord.async_seedlings_ready(key)
            except ValueError as err:
                raise _error("no_seeding") from err

    async def log_event(call: ServiceCall) -> None:
        on = _logged_date(call)
        grouped: dict = {}
        for coord, key in _targets(hass, call):
            grouped.setdefault(id(coord), (coord, []))[1].append(key)
        for coord, keys in grouped.values():
            await coord.async_log_event(call.data[ATTR_KIND], keys, on=on)

    async def prep_overseed(call: ServiceCall) -> None:
        targets = _targets(hass, call)
        for coord, key in targets:
            if coord.areas[key].overseed_target_in is None:
                raise _error("no_overseed", area=coord.areas[key].name)
        for coord, key in targets:
            await coord.async_prep_overseed(key, call.data[ATTR_SEED_DATE],
                                            call.data.get(ATTR_TARGET),
                                            call.data.get(ATTR_BUFFER))

    async def cancel_overseed(call: ServiceCall) -> None:
        for coord, key in _targets(hass, call):
            await coord.async_cancel_overseed(key)

    async def evaluate_now(call: ServiceCall) -> None:
        for entry in _loaded(hass):
            await entry.runtime_data.async_run(send_notifications=True)

    handlers = {"log_mow": log_mow, "correct_last_mow": correct_last_mow,
                "log_seeding": log_seeding, "seedlings_ready": seedlings_ready,
                "log_event": log_event, "prep_overseed": prep_overseed,
                "cancel_overseed": cancel_overseed, "evaluate_now": evaluate_now}
    for name, handler in handlers.items():
        hass.services.async_register(DOMAIN, name, handler, schema=SCHEMAS[name])
