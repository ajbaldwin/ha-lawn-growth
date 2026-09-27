"""Lawn Growth — condition-driven mowing advice for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.start import async_at_started

from . import services
from .const import (AREA_KEY, AREA_LOCATIONS, AREA_MOW_MODE, AREA_MOW_SOURCE, CONF_AREAS,
                    CONF_MOWER, CONF_RUN_TIME, DEFAULT_RUN_TIME, DOMAIN, MOW_MODE_INCREASES)
from .coordinator import LawnGrowthCoordinator
from .mow_sources import CounterWatcher, MowerTracker
from .store import LawnStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON,
                             Platform.DATE]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type LawnGrowthConfigEntry = ConfigEntry[LawnGrowthCoordinator]


def _run_time(value: str) -> tuple[int, int, int]:
    parts = [int(p) for p in value.split(":")] + [0, 0]
    return parts[0], parts[1], parts[2]


async def async_setup(hass: HomeAssistant, config) -> bool:
    services.async_register(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LawnGrowthConfigEntry) -> bool:
    store = LawnStore(hass, entry.entry_id)
    await store.async_load([a[AREA_KEY] for a in entry.options.get(CONF_AREAS, [])])
    coordinator = LawnGrowthCoordinator(hass, entry, store)
    # During HA startup, evaluate without accruing; the run once HA has started
    # accrues the day with live inputs. A reload/options change accrues right away.
    starting = hass.state is not CoreState.running
    coordinator.accrual_enabled = not starting
    await coordinator.async_config_entry_first_refresh()     # startup run (no notifications)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    hour, minute, second = _run_time(entry.options.get(CONF_RUN_TIME, DEFAULT_RUN_TIME))

    async def _daily(now) -> None:
        await coordinator.async_run(send_notifications=True)

    entry.async_on_unload(async_track_time_change(
        hass, _daily, hour=hour, minute=minute, second=second))

    watchers: list = []
    for key, opts in coordinator.area_options.items():
        if opts.get(AREA_MOW_SOURCE):
            watchers.append(CounterWatcher(hass, coordinator, key, opts[AREA_MOW_SOURCE],
                                           opts.get(AREA_MOW_MODE, MOW_MODE_INCREASES)))
    mower = entry.options.get(CONF_MOWER)
    if mower:
        location_map = {value: key for key, opts in coordinator.area_options.items()
                        for value in opts.get(AREA_LOCATIONS, [])}
        watchers.append(MowerTracker(hass, coordinator, mower, location_map))

    unloaded = False

    @callback
    def _stop_watchers() -> None:
        nonlocal unloaded
        unloaded = True
        for watcher in watchers:
            watcher.stop()

    entry.async_on_unload(_stop_watchers)

    async def _start_watchers() -> None:
        for watcher in watchers:
            if unloaded:
                return
            await watcher.async_start()
            if unloaded:                 # unloaded while this one was starting
                watcher.stop()

    if not starting:
        await _start_watchers()
    else:
        # The mow watchers start only after the run that accrues the day: a mow they
        # catch at startup (a counter change while HA was down) must reset the
        # accumulator after the missed days' growth has landed on it, not before.
        async def _started(_hass: HomeAssistant) -> None:
            coordinator.accrual_enabled = True
            try:
                await coordinator.async_run()                # no notifications at startup
            except Exception:  # noqa: BLE001 - mow capture must start regardless
                _LOGGER.exception("Lawn Growth run at Home Assistant start failed")
            await _start_watchers()

        entry.async_on_unload(async_at_started(hass, _started))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LawnGrowthConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: LawnGrowthConfigEntry) -> None:
    await LawnStore(hass, entry.entry_id).async_remove()
