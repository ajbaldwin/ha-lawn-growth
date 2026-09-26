"""Lawn Growth coordinator: one evaluation at a time, state kept in the Store."""
from __future__ import annotations

import asyncio
import logging
from datetime import date

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import inputs
from .const import (AREA_KEY, AREA_MOISTURE, CONF_AREAS, CONF_NOTIFY, CONF_SEASON,
                    CONF_WEATHER, DOMAIN)
from .model import establishment, evaluate, mow, notify, presets
from .model.config import Tunables
from .model.state import MowRecord, OverseedState
from .store import LawnStore

_LOGGER = logging.getLogger(__name__)


class LawnGrowthCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass, entry, store: LawnStore) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=None)
        self.store = store
        self.tunables = Tunables()
        self.area_options = {a[AREA_KEY]: a for a in entry.options.get(CONF_AREAS, [])}
        self.areas = {k: presets.area_from_options(a) for k, a in self.area_options.items()}
        self._lock = asyncio.Lock()
        # Off while HA is still starting: inputs such as soil-moisture sensors may not
        # be up yet, and today's accrual happens once. The run at HA start turns it on.
        self.accrual_enabled = True
        self._flat_warned = False

    @property
    def _opts(self) -> dict:
        return self.config_entry.options

    async def _async_update_data(self) -> dict:
        results, _ = await self._evaluate(send_notifications=False)
        return results

    async def async_run(self, *, send_notifications: bool = False) -> None:
        try:
            results, messages = await self._evaluate(send_notifications=send_notifications)
        except UpdateFailed as err:
            _LOGGER.warning("Lawn Growth evaluation skipped: %s", err)
            return
        # Publish before awaiting the sends: a mutation that runs while a send is in
        # flight publishes newer results, which these must not overwrite afterwards.
        self.async_set_updated_data(results)
        for msg in messages:
            await self._async_send(msg)

    async def _evaluate(self, *, send_notifications: bool) -> tuple[dict, list]:
        """Evaluate every area under the lock and save the Store. Returns the results
        and the notifications to send; the caller publishes, then sends."""
        messages = []
        notify_enabled = send_notifications and bool(self._opts.get(CONF_NOTIFY))
        async with self._lock:
            today = dt_util.now().date()
            temps = await inputs.async_read_temps(self.hass, self._opts[CONF_WEATHER], today)
            if temps is None:
                raise UpdateFailed(f"no temperature forecast from {self._opts[CONF_WEATHER]}")
            if not temps.horizon and not self._flat_warned:
                _LOGGER.warning("%s has no forecast beyond today; days until due use a flat "
                                "projection from today's mean", self._opts[CONF_WEATHER])
                self._flat_warned = True
            season = inputs.in_season(self.hass, self._opts.get(CONF_SEASON))
            results = {}
            for key, cfg in self.areas.items():
                state = self.store.areas[key]
                moist, used = inputs.read_moisture(
                    self.hass, self.area_options[key].get(AREA_MOISTURE, []))
                if season is not None:
                    in_season = season
                else:
                    in_season = state.was_in_season if state.was_in_season is not None else True
                inp = evaluate.DayInputs(
                    today=today, in_season=in_season,
                    high_f=temps.today_high_f, low_f=temps.today_low_f,
                    horizon=temps.horizon,
                    moisture=moist if moist is not None else cfg.comfortable_moisture,
                    moisture_source="sensors" if moist is not None else "fallback",
                    events=self.store.events_for(key), moisture_sensors_used=used)
                result, new_state = evaluate.evaluate_area(
                    cfg, self.tunables, state, inp,
                    accrue=self.accrual_enabled and state.last_accrual != today)
                if notify_enabled:
                    msgs, new_state = notify.decide(
                        cfg.name, result, new_state, today=today,
                        min_interval_days=self.tunables.overseed_min_mow_interval_days)
                    messages.extend(msgs)
                self.store.areas[key] = new_state
                results[key] = result
            await self.store.async_save()
        return results, messages

    async def _async_send(self, msg) -> None:
        target = self._opts.get(CONF_NOTIFY)
        if not target:
            return
        domain, _, service = target.partition(".")
        try:
            await self.hass.services.async_call(
                domain, service, {"title": msg.title, "message": msg.message}, blocking=True)
        except Exception as err:  # noqa: BLE001 - a failed push must never fail the run
            _LOGGER.warning("Lawn Growth could not notify via %s: %s", target, err)

    # --- mutations: change state under the lock, then re-evaluate -----------------

    async def _async_mutate(self, key: str, fn) -> None:
        async with self._lock:
            self.store.areas[key] = fn(self.store.areas[key])
            await self.store.async_save()
        await self.async_run()

    def default_height(self, key: str) -> float:
        last = self.store.areas[key].last_cut_in
        return last if last is not None else self.areas[key].cut_max_in

    async def async_log_mow(self, key: str, *, on: date | None = None,
                            height_in: float | None = None, source: str = "manual") -> None:
        record = MowRecord(on or dt_util.now().date(),
                           float(height_in) if height_in is not None else self.default_height(key),
                           source)
        def fn(s):
            new = mow.apply_mow(s, record)
            last = (self.data or {}).get(key)
            if (s.seeding_date is not None and new.seeding_date is None
                    and last is not None and last.mode == "establishment"):
                _LOGGER.info("%s: mow on %s ends establishment (seeded %s) before the "
                             "seedlings were ready; treating the stand as ready",
                             self.areas[key].name, record.date, s.seeding_date)
            return new
        await self._async_mutate(key, fn)

    async def async_correct_last_mow(self, key: str, height_in: float) -> None:
        await self._async_mutate(key, lambda s: mow.correct_last_mow(s, height_in))

    async def async_log_seeding(self, key: str, *, on: date | None = None) -> None:
        seeded = on or dt_util.now().date()
        await self._async_mutate(key, lambda s: establishment.log_seeding(s, seeded))

    async def async_seedlings_ready(self, key: str) -> None:
        await self._async_mutate(key, establishment.mark_ready)

    async def async_log_event(self, kind: str, keys, *, on: date | None = None) -> None:
        today = dt_util.now().date()
        async with self._lock:
            self.store.add_event(kind, on or today, keys, today)
            await self.store.async_save()
        await self.async_run()

    async def async_prep_overseed(self, key: str, seed_date: date,
                                  target_in: float | None = None,
                                  buffer_days: int | None = None) -> None:
        def fn(s):
            c = s.copy()
            c.overseed = OverseedState(seed_date, target_in, buffer_days, "")
            return c
        await self._async_mutate(key, fn)

    async def async_cancel_overseed(self, key: str) -> None:
        def fn(s):
            c = s.copy()
            c.overseed = OverseedState()
            return c
        await self._async_mutate(key, fn)

    async def async_save_store(self) -> None:
        async with self._lock:
            await self.store.async_save()
