"""Lawn Growth services. All but evaluate_now target mowing-area devices; log_event
and skip_application default to every area when no device is given."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .model.applications import PRODUCTS
from .model.windows import KINDS

ATTR_DATE = "date"
ATTR_HEIGHT = "height_in"
ATTR_KIND = "kind"
ATTR_SEED_DATE = "seed_date"
ATTR_TARGET = "target_in"
ATTR_BUFFER = "buffer_days"
ATTR_PRODUCT = "product"

LOG_KINDS = ("fert", "pgr", "winterizer", "herbicide")

_DEVICE = {vol.Required(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string])}
_ANY_DEVICE = {vol.Optional(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string])}
_HEIGHT = vol.All(vol.Coerce(float), vol.Range(min=0.5, max=8.0))

SCHEMAS = {
    "log_mow": vol.Schema({**_DEVICE, vol.Optional(ATTR_DATE): cv.date,
                           vol.Optional(ATTR_HEIGHT): _HEIGHT}),
    "correct_last_mow": vol.Schema({**_DEVICE, vol.Required(ATTR_HEIGHT): _HEIGHT}),
    "log_seeding": vol.Schema({**_DEVICE, vol.Optional(ATTR_DATE): cv.date}),
    "seedlings_ready": vol.Schema(_DEVICE),
    "log_event": vol.Schema({**_ANY_DEVICE, vol.Required(ATTR_KIND): vol.In(LOG_KINDS),
                             vol.Optional(ATTR_PRODUCT): vol.In(list(PRODUCTS)),
                             vol.Optional(ATTR_DATE): cv.date}),
    "skip_application": vol.Schema({**_ANY_DEVICE,
                                    vol.Required(ATTR_KIND): vol.In(KINDS)}),
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


def _grouped(hass: HomeAssistant, call: ServiceCall) -> list:
    """[(coordinator, area keys)]; with no device_id, every area of every entry."""
    if not call.data.get(ATTR_DEVICE_ID):
        return [(e.runtime_data, None) for e in _loaded(hass)]
    grouped: dict = {}
    for coord, key in _targets(hass, call):
        grouped.setdefault(id(coord), (coord, []))[1].append(key)
    return list(grouped.values())


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
        kind, product = call.data[ATTR_KIND], call.data.get(ATTR_PRODUCT, "")
        if kind == "herbicide" and not product:
            raise _error("product_required")
        if kind != "herbicide" and product:
            raise _error("product_herbicide_only")
        for coord, keys in _grouped(hass, call):
            await coord.async_log_event(kind, keys, on=on, product=product)

    async def skip_application(call: ServiceCall) -> None:
        kind = call.data[ATTR_KIND]
        groups = _grouped(hass, call)
        if kind == "overseed":
            for coord, keys in groups:
                for key in keys or []:
                    if coord.areas[key].overseed_target_in is None:
                        raise _error("no_overseed", area=coord.areas[key].name)
        for coord, keys in groups:
            await coord.async_skip_application(kind, keys)

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
                "log_event": log_event, "skip_application": skip_application,
                "prep_overseed": prep_overseed,
                "cancel_overseed": cancel_overseed, "evaluate_now": evaluate_now}
    for name, handler in handlers.items():
        hass.services.async_register(DOMAIN, name, handler, schema=SCHEMAS[name])
