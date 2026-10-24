"""Lawn Growth coordinator: one evaluation at a time, state kept in the Store."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import calendar_writer, inputs
from .const import (AREA_KEY, AREA_MOISTURE, AREA_SOIL_DEPTH, CONF_AREAS, CONF_NOTIFY,
                    CONF_OUTDOOR_TEMP, CONF_SEASON, CONF_WEATHER, DEFAULT_SOIL_DEPTH, DOMAIN)
from .model import (applications, appcalendar, establishment, evaluate, gdd, heat, mow,
                    notify, overseed, postemergent, presets, soiltemp, water, windows)
from .model.weather import ForecastDetail
from .model.config import Tunables
from .model.state import MowRecord, OverseedState
from .store import LawnStore

_LOGGER = logging.getLogger(__name__)
RETRY_MINUTES = 15       # a run that couldn't get a forecast is retried after this


class LawnGrowthCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass, entry, store: LawnStore) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=None)
        self.store = store
        self.tunables = Tunables()
        self.area_options = {a[AREA_KEY]: a for a in entry.options.get(CONF_AREAS, [])}
        self.areas = {k: presets.area_from_options(a) for k, a in self.area_options.items()}
        self.soil_probes: dict[str, tuple] = {}     # area key -> inputs.SoilProbe tuple
        self._soil_read = False                     # this run read soil history
        self._lock = asyncio.Lock()
        # Off while HA is still starting: inputs such as soil-moisture sensors may not
        # be up yet, and today's accrual happens once. The run at HA start turns it on.
        self.accrual_enabled = True
        self._flat_warned = False
        self._retry_unsub = None
        self._retry_notify = False
        self.area_calendar: dict[str, appcalendar.AreaCalendar] = {}
        self.last_signals: dict[str, windows.AreaSignals] = {}
        self.calendar: list[appcalendar.CalEvent] = []
        # area -> (today, tomorrow) spray-day verdicts while a post-emergent window
        # is open, else None
        self.spray_days: dict[str, tuple | None] = {}
        self._write_lock = asyncio.Lock()       # one calendar copy at a time

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
            # Expected while HA is still starting (a cloud weather integration may not
            # be up yet), so only a warning once HA is running.
            level = logging.WARNING if self.accrual_enabled else logging.INFO
            _LOGGER.log(level, "Lawn Growth evaluation skipped, retrying in %d minutes: %s",
                        RETRY_MINUTES, err)
            self._schedule_retry(send_notifications)
            # A mutation (e.g. a date picker) may have just saved to the Store even
            # though today's evaluation couldn't run; refresh store-backed entities
            # so they show it without waiting for the forecast to come back.
            self.async_update_listeners()
            return
        self.cancel_retry()
        # Publish before awaiting the sends: a mutation that runs while a send is in
        # flight publishes newer results, which these must not overwrite afterwards.
        self.async_set_updated_data(results)
        for msg in messages:
            await self._async_send(msg)
        await self._async_write_calendars()

    async def _async_write_calendars(self) -> None:
        """Copy firm events to the calendars under Lawn settings. Runs after the
        pushes, outside the evaluation lock (a write can be slow); its own lock keeps
        two runs from writing the same event."""
        try:
            async with self._write_lock:
                if await calendar_writer.async_write(self):
                    async with self._lock:
                        await self.store.async_save()
        except Exception:  # noqa: BLE001 - calendar copies must never fail a run
            _LOGGER.exception("Lawn Growth could not copy events to calendars")

    @callback
    def _schedule_retry(self, send_notifications: bool) -> None:
        """One pending retry at a time; it sends notifications if any failed run would
        have (a missed daily run still pushes once the forecast is back)."""
        self._retry_notify = self._retry_notify or send_notifications
        if self._retry_unsub is not None:
            return

        async def _retry(_now) -> None:
            self._retry_unsub = None
            notify, self._retry_notify = self._retry_notify, False
            await self.async_run(send_notifications=notify)

        self._retry_unsub = async_call_later(self.hass, RETRY_MINUTES * 60, _retry)

    @callback
    def cancel_retry(self) -> None:
        if self._retry_unsub is not None:
            self._retry_unsub()
            self._retry_unsub = None
        self._retry_notify = False

    @property
    def waiting_for_weather(self) -> bool:
        """True while the last run failed (or none succeeded yet)."""
        return self._retry_unsub is not None or self.data is None

    async def _evaluate(self, *, send_notifications: bool) -> tuple[dict, list]:
        """Evaluate every area under the lock and save the Store. Returns the results
        and the notifications to send; the caller publishes, then sends."""
        messages = []
        notify_enabled = send_notifications and bool(self._opts.get(CONF_NOTIFY))
        async with self._lock:
            today = dt_util.now().date()
            weather_state = self.hass.states.get(self._opts[CONF_WEATHER])
            if weather_state is None or weather_state.state in (STATE_UNAVAILABLE,
                                                                STATE_UNKNOWN):
                raise UpdateFailed(f"{self._opts[CONF_WEATHER]} is not available yet")
            temps = await inputs.async_read_temps(self.hass, self._opts[CONF_WEATHER], today)
            if temps is None:
                raise UpdateFailed(f"no temperature forecast from {self._opts[CONF_WEATHER]}")
            if not temps.horizon and not self._flat_warned:
                _LOGGER.warning("%s has no forecast beyond today; days until due use a flat "
                                "projection from today's mean", self._opts[CONF_WEATHER])
                self._flat_warned = True
            try:
                detail = await inputs.async_read_detail(self.hass, self._opts[CONF_WEATHER])
            except Exception as err:  # noqa: BLE001 - optional detail never fails a run
                _LOGGER.debug("No forecast detail from %s: %s", self._opts[CONF_WEATHER], err)
                detail = ForecastDetail()
            season = inputs.in_season(self.hass, self._opts.get(CONF_SEASON))
            self._find_soil_probes()
            self._soil_read = False
            if self.accrual_enabled and inputs.recorder_ready(self.hass):
                await self._async_update_temperature_signals(today)
            results = {}
            apps = self.applications(today)
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
                    events=self.store.events_for(key), moisture_sensors_used=used,
                    no_mow_until=postemergent.hold_until(apps, key, today, self.tunables))
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
            messages.extend(self._update_windows(today, temps, detail, results,
                                                 send_notifications=send_notifications))
            await self.store.async_save()
        return results, messages

    # --- application windows and calendar ---------------------------------------

    def _area_signals(self, key: str, result, today: date) -> windows.AreaSignals:
        tun, state = self.tunables, self.store.areas[key]
        soil5, _ = self.soil5(key, today)
        prev = slope = None
        if soil5 is not None:
            days = soiltemp.days_by_date(state.soil_days)
            prev, _ = soiltemp.soil5(days, today - timedelta(days=1), tun.soil_window_days,
                                     tun.soil_min_valid_days)
            slope = soiltemp.trend(days, today, tun.soil_days_kept, tun.soil_min_valid_days)
        return windows.AreaSignals(
            key=key, soil5=soil5, soil5_prev=prev, soil_slope=slope,
            air_means=tuple(h.mean_f for h in state.history[-7:]), phase=result.phase,
            mow_due=result.mow_due, days_until_due=result.days_until_due,
            dormant=state.low_gp_streak >= tun.dormant_days, last_mow=state.last_mow,
            overseed_capable=self.areas[key].overseed_target_in is not None)

    def _area_calendar(self, key: str, result, today: date) -> appcalendar.AreaCalendar:
        tun, cfg, state = self.tunables, self.areas[key], self.store.areas[key]
        days = None
        if cfg.overseed_target_in is not None:
            days = overseed.prep_days(
                current_cut_in=result.last_cut_in,
                target_in=state.overseed.target_in or cfg.overseed_target_in,
                regrowth_per_day_in=result.growth_today_mm / 25.4,
                min_mow_interval_days=tun.overseed_min_mow_interval_days,
                max_removal_fraction=tun.overseed_max_removal_fraction)
        buffer = (state.overseed.buffer_days if state.overseed.buffer_days is not None
                  else tun.overseed_buffer_days)
        return appcalendar.AreaCalendar(
            name=cfg.name, planned_seed=state.overseed.seed_date,
            earliest_seed=today + timedelta(days=days) if days is not None else None,
            prep_days=days, buffer_days=buffer)

    def _spray_context(self, key: str, result, today: date, temps,
                       detail) -> postemergent.SprayContext:
        tun, cfg, state = self.tunables, self.areas[key], self.store.areas[key]

        def hot(high):
            return high is not None and heat.heat_hold(
                high, result.moisture, cfg.wilting_moisture, cfg.comfortable_moisture, tun,
                warm=(cfg.curve == "warm"))

        tomorrow = today + timedelta(days=1)
        return postemergent.SprayContext(
            product=self.post_emergent_product(key), last_mow=state.last_mow,
            mow_due=result.mow_due, days_until_due=result.days_until_due,
            dormant=state.low_gp_streak >= tun.dormant_days,
            heat_hold={today: hot(temps.today_high_f), tomorrow: hot(detail.high_f(tomorrow))},
            water_factor=water.water_factor(result.moisture, cfg.wilting_moisture,
                                            cfg.comfortable_moisture),
            seeding_date=state.seeding_date, seedlings_ready=state.seedlings_ready,
            ready_on=state.seedlings_ready_on,
            mows=tuple(r.date for r in state.mow_records))

    def _update_windows(self, today: date, temps, detail, results: dict, *,
                        send_notifications: bool) -> list:
        """Advance the application windows, rebuild the calendar and return the
        window pushes. Pushes are decided on daily runs only, and their flags are
        stored even without a notify target, so setting one up later doesn't replay
        the season."""
        tun = self.tunables
        apps = self.applications(today)
        gdd_total = self.store.gdd.total if self.store.gdd.year == today.year else None
        highs = []
        for i in range(1, tun.forecast_horizon_days + 1):
            high = detail.high_f(today + timedelta(days=i))
            if high is None:
                break
            highs.append(high)
        lawn = windows.LawnSignals(today=today, gdd=gdd_total,
                                   horizon=tuple(m for _, m in temps.horizon),
                                   highs=tuple(highs))
        signals = [self._area_signals(k, r, today) for k, r in results.items()]
        self.last_signals = {a.key: a for a in signals}
        self.store.windows = postemergent.update_all(
            windows.update_all(self.store.windows, lawn, signals, apps, tun),
            lawn, signals, apps, tun)
        self.spray_days = {}
        for k, r in results.items():
            if postemergent.open_windows(self.store.windows, k, today):
                ctx = self._spray_context(k, r, today, temps, detail)
                self.spray_days[k] = tuple(
                    postemergent.spray_day(today + timedelta(days=i), today, ctx, detail, tun)
                    for i in (0, 1))
            else:
                self.spray_days[k] = None
        self.area_calendar = {k: self._area_calendar(k, r, today) for k, r in results.items()}
        messages = []
        if send_notifications:
            blocks = {k: applications.seeding_block(apps, k, today, tun) for k in results}
            names = {k: c.name for k, c in self.areas.items()}
            messages, self.store.windows = notify.decide_windows(
                self.store.windows, names, apps=apps, tun=tun, today=today, blocks=blocks,
                new_turf=self.new_turf_waits(today))
            spray, self.store.windows = notify.decide_spray(
                self.store.windows, {k: v[1] for k, v in self.spray_days.items() if v},
                names, today=today, tun=tun)
            followups, self.store.followups_notified = notify.decide_followups(
                apps, names, self.store.followups_notified, today=today, tun=tun)
            messages += spray + followups + self._decide_probes(names)
        self.calendar = appcalendar.calendar_events(self.calendar_state(today))
        return messages

    def _decide_probes(self, names: dict) -> list:
        """The probes-back-online push; records each area's soil source for the next
        daily run. Skipped when this run couldn't read soil history: missing days then
        say nothing about the probes."""
        if not self._soil_read:
            return []
        now = {k: (soiltemp.source_for(a.soil5) if self.soil_probes.get(k) else None)
               for k, a in self.last_signals.items()}
        messages, recorded = notify.decide_probes(
            {k: self.store.areas[k].soil_source_last for k in now}, now, names)
        for k, source in recorded.items():
            self.store.areas[k].soil_source_last = source
        return messages

    def applications(self, today: date) -> list:
        return self.store.logged_applications(today, self.tunables.application_retention_days)

    def calendar_state(self, today: date) -> appcalendar.CalendarState:
        return appcalendar.CalendarState(
            today=today, tunables=self.tunables, windows=self.store.windows,
            applications=tuple(self.applications(today)), areas=dict(self.area_calendar),
            mows=tuple((r.date, k) for k, s in self.store.areas.items()
                       for r in s.mow_records))

    def new_turf_waits(self, today: date) -> dict:
        """{area key: why} for the areas where prodiamine must wait on new turf."""
        mows = {k: tuple(r.date for r in s.mow_records)
                for k, s in self.store.areas.items() if k in self.areas}
        return applications.new_turf_waits(self.applications(today), mows, today,
                                           self.tunables)

    def new_turf_everywhere(self, today: date) -> bool:
        """True when prodiamine must wait in every configured area."""
        return bool(self.areas) and len(self.new_turf_waits(today)) == len(self.areas)

    def window(self, kind: str, area: str = windows.LAWN):
        return windows.current(self.store.windows, kind, dt_util.now().date(),
                               self.tunables, area)

    def post_emergent_product(self, key: str) -> str:
        """An area's Post-emergent product select (default mesotrione)."""
        return self.store.post_emergent_products.get(key) or "mesotrione"

    async def async_set_post_emergent_product(self, key: str, product: str) -> None:
        async with self._lock:
            self.store.post_emergent_products[key] = product
            await self.store.async_save()
        await self.async_run()          # the spray-day check depends on the product

    @property
    def pre_emergent_product(self) -> str:
        """The Pre-emergent product select: the user's pick, else the suggestion."""
        return (self.store.pre_emergent_product
                or windows.suggested_pre_product(
                    self.window("pre_emergent"),
                    self.new_turf_everywhere(dt_util.now().date())))

    def _find_soil_probes(self) -> None:
        self.soil_probes = {
            key: inputs.soil_probes(self.hass, opts.get(AREA_MOISTURE, []),
                                    opts.get(AREA_SOIL_DEPTH, DEFAULT_SOIL_DEPTH))
            for key, opts in self.area_options.items()}

    async def _async_update_temperature_signals(self, today: date) -> None:
        """Fill in the completed days not yet recorded: lawn-wide GDD and each area's
        daily soil temperature. Only missing days are read, so after the first run of
        the day this costs nothing. A recorder failure skips the update; the next run
        retries the same days."""
        yesterday = today - timedelta(days=1)
        try:
            await self._async_update_gdd(yesterday)
            for key, probes in self.soil_probes.items():
                if probes:
                    await self._async_update_soil(key, probes, today)
            self._soil_read = True
        except Exception as err:  # noqa: BLE001 - signals must never fail the run
            _LOGGER.warning("Lawn Growth could not read soil/outdoor temperature "
                            "history: %s", err)

    async def _async_update_gdd(self, yesterday: date) -> None:
        tun = self.tunables
        sensor = self._opts.get(CONF_OUTDOOR_TEMP)
        # A newly added or changed outdoor sensor restarts the season, so it is
        # recounted from that sensor's history.
        state = gdd.for_sensor(self.store.gdd, sensor or "")
        days = gdd.days_to_process(state, yesterday, tun)
        if not days:
            self.store.gdd = state
            return
        observed = (await inputs.async_daily_min_max(self.hass, sensor, days[0], days[-1])
                    if sensor else {})
        forecast = {h.date: h.mean_f for s in self.store.areas.values() for h in s.history}
        gaps = 0
        for day in days:
            if day in observed:
                tmax, tmin = observed[day]
                value, source = gdd.gdd_day(tmax, tmin, tun.gdd_base_f), "sensor"
            elif day in forecast:
                value, source = gdd.gdd_from_mean(forecast[day], tun.gdd_base_f), "forecast"
            else:
                value, source = None, ""
                gaps += 1
            state = gdd.accrue(state, day, value, source, tun)
        if gaps:
            _LOGGER.info("Lawn Growth: no temperature data for %d of %d GDD days (%s to %s)",
                         gaps, len(days), days[0], days[-1])
        self.store.gdd = state

    async def _async_update_soil(self, key: str, probes, today: date) -> None:
        tun = self.tunables
        state = self.store.areas[key].copy()
        days = soiltemp.prune_days(state.soil_days, today, tun.soil_days_kept)
        for back in range(tun.soil_days_kept, 0, -1):
            day = today - timedelta(days=back)
            if day.isoformat() in days:
                continue
            series = await inputs.async_soil_day(self.hass, probes, day)
            mean, coverage = soiltemp.area_day(
                [soiltemp.probe_day_mean(*s) for s in series], tun.soil_min_coverage)
            days[day.isoformat()] = {"mean_f": mean, "coverage": round(coverage, 3)}
        state.soil_days = days
        self.store.areas[key] = state

    def soil5(self, key: str, today: date) -> tuple[float | None, int]:
        if not self.soil_probes.get(key):
            return None, 0
        tun = self.tunables
        return soiltemp.soil5(soiltemp.days_by_date(self.store.areas[key].soil_days), today,
                              tun.soil_window_days, tun.soil_min_valid_days)

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
        """Height for a mow logged without one: the Log mow height, else the last
        cut, else the top of the cut range."""
        s = self.store.areas[key]
        for h in (s.log_mow_height_in, s.last_cut_in):
            if h is not None:
                return h
        return self.areas[key].cut_max_in

    async def async_set_log_mow_height(self, key: str, height_in: float) -> None:
        def fn(s):
            c = s.copy()
            c.log_mow_height_in = float(height_in)
            return c
        await self._async_mutate(key, fn)

    async def async_log_mow(self, key: str, *, on: date | None = None,
                            height_in: float | None = None, source: str = "manual") -> None:
        record = MowRecord(on or dt_util.now().date(),
                           float(height_in) if height_in is not None else self.default_height(key),
                           source)
        def fn(s):
            new = mow.apply_mow(s, record)
            if s.seeding_date is not None and new.seeding_date is not None                     and record.date > s.seeding_date:
                _LOGGER.info("%s: mow on %s logged as an establishment mow (seeded %s); "
                             "press Seedlings ready to end establishment",
                             self.areas[key].name, record.date, s.seeding_date)
            return new
        await self._async_mutate(key, fn)

    async def async_correct_last_mow(self, key: str, height_in: float) -> None:
        await self._async_mutate(key, lambda s: mow.correct_last_mow(s, height_in))

    async def async_log_seeding(self, key: str, *, on: date | None = None) -> None:
        today = dt_util.now().date()
        seeded = on or today
        async with self._lock:
            # A seeding logged while one is on record replaces it (the Seeding date
            # picker corrects the date), so its application-log entry moves with it.
            self.store.add_application(
                "seeding", seeded, [key], today, replaces=self.store.areas[key].seeding_date,
                retention_days=self.tunables.application_retention_days)
            self.store.areas[key] = establishment.log_seeding(self.store.areas[key], seeded)
            await self.store.async_save()
        await self.async_run()

    async def async_seedlings_ready(self, key: str) -> None:
        today = dt_util.now().date()
        await self._async_mutate(key, lambda s: establishment.mark_ready(s, today))

    async def async_log_event(self, kind: str, keys=None, *, on: date | None = None,
                              product: str = "") -> None:
        """Log an application for these areas (None: every area). Fertilizer, PGR
        and winterizer also feed the growth model; herbicides only the log."""
        today = dt_util.now().date()
        on = on or today
        keys = list(keys) if keys is not None else list(self.areas)
        warnings = []
        async with self._lock:
            if kind in ("fert", "pgr", "winterizer"):
                self.store.add_event(kind, on, keys, today)
            self.store.add_application(kind, on, keys, today, product=product,
                                       retention_days=self.tunables.application_retention_days)
            post = kind == "herbicide" and product in applications.POST_EMERGENT_PRODUCTS
            if post:
                for key in keys:
                    s = self.store.areas[key]
                    why = postemergent.seedling_check(product, postemergent.SprayContext(
                        product=product, seeding_date=s.seeding_date,
                        seedlings_ready=s.seedlings_ready, ready_on=s.seedlings_ready_on,
                        mows=tuple(r.date for r in s.mow_records)), on, self.tunables)
                    if why:
                        warnings.append(f"{self.areas[key].name}: "
                                        f"{applications.product_label(product)} logged, but "
                                        f"{why}. It can injure new grass.")
            elif kind == "herbicide" and applications.block_days(product, self.tunables) > 0:
                earlier = [a for a in self.store.applications if a.date <= on]
                for key in keys:
                    s = self.store.areas[key]
                    if s.seeding_date is not None and not s.seedlings_ready:
                        warnings.append(
                            f"{self.areas[key].name} is establishing new grass (seeded "
                            f"{applications.fmt_day(s.seeding_date)}): "
                            f"{applications.product_label(product)} can keep the "
                            f"seedlings from rooting.")
                        continue
                    why = applications.new_turf_wait(
                        product, applications.latest(earlier, key, ("seeding",)),
                        tuple(r.date for r in s.mow_records), on, self.tunables)
                    if why:
                        warnings.append(f"{self.areas[key].name}: "
                                        f"{applications.product_label(product)} logged, but "
                                        f"{why}. It can injure new grass.")
            await self.store.async_save()
        await self.async_run()
        for text in warnings:
            await self._async_warn(text)
        until = postemergent.no_mow_until(on, self.tunables) if post else None
        if until is not None and until > today:
            await self._async_send(notify.Message(notify.POST_TITLE, notify.dont_mow_text(
                [self.areas[k].name for k in keys], product, until,
                self.tunables.post_hold_mowing)))

    async def async_log_post_emergent(self, key: str, *, on: date | None = None) -> None:
        """The Last post-emergent picker: this area, with its Post-emergent product."""
        await self.async_log_event("herbicide", [key], on=on,
                                   product=self.post_emergent_product(key))

    async def async_flag_weeds(self, key: str, target: str) -> None:
        """flag_weeds: open the matching post-emergent window for this area today.
        Raises postemergent.WindowEnded when it already closed this season."""
        today = dt_util.now().date()
        async with self._lock:
            w = postemergent.flag(self.store.windows, key, target, today, self.tunables)
            self.store.windows[w.key] = w
            await self.store.async_save()
        await self.async_run()

    async def async_log_pre_emergent(self, *, on: date | None = None) -> None:
        """The Last pre-emergent picker: every area, with the selected product. The
        select then follows the suggestion again (the split reminder's dithiopyr)."""
        product = self.pre_emergent_product
        async with self._lock:
            self.store.pre_emergent_product = None
        await self.async_log_event("herbicide", None, on=on, product=product)

    async def async_set_pre_emergent_product(self, product: str) -> None:
        async with self._lock:
            self.store.pre_emergent_product = product
            await self.store.async_save()
        self.async_update_listeners()

    async def async_skip_application(self, kind: str, keys=None) -> None:
        """skip_application: this season's window for the kind. Pre-emergent is
        lawn-wide; the others apply to these areas (None: every area)."""
        today = dt_util.now().date()
        areas = [windows.LAWN] if kind == "pre_emergent" else (
            list(keys) if keys is not None else list(self.areas))
        if kind == "post_emergent":
            async with self._lock:
                for area in areas:
                    for w in postemergent.skip(self.store.windows, area, today,
                                               self.tunables):
                        self.store.windows[w.key] = w
                await self.store.async_save()
            await self.async_run()
            return
        season = windows.current_season(kind, today, self.tunables)
        async with self._lock:
            for area in areas:
                if kind == "overseed" and self.areas[area].overseed_target_in is None:
                    continue
                key = windows.window_key(kind, season, area)
                current = self.store.windows.get(key) or windows.Window(kind, season, area)
                self.store.windows[key] = windows.skip(current, today)
            await self.store.async_save()
        await self.async_run()

    async def _async_warn(self, text: str) -> None:
        _LOGGER.warning("Lawn Growth: %s", text)
        await self._async_send(notify.Message(notify.TITLE, text))

    async def async_prep_overseed(self, key: str, seed_date: date,
                                  target_in: float | None = None,
                                  buffer_days: int | None = None) -> None:
        def fn(s):
            c = s.copy()
            c.overseed = OverseedState(seed_date, target_in, buffer_days, "")
            return c
        await self._async_mutate(key, fn)
        block = applications.seeding_block(self.applications(dt_util.now().date()), key,
                                           seed_date, self.tunables)
        if block is not None:
            await self._async_warn(f"{self.areas[key].name}: {block.text()} (seed date "
                                   f"{applications.fmt_day(seed_date)}).")

    async def async_cancel_overseed(self, key: str) -> None:
        def fn(s):
            c = s.copy()
            c.overseed = OverseedState()
            return c
        await self._async_mutate(key, fn)

    async def async_save_store(self) -> None:
        async with self._lock:
            await self.store.async_save()
