"""Mow detection: a per-area mow-signal watcher and mower session capture."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event, async_track_time_interval)
from homeassistant.util import dt as dt_util

from . import const as c
from .model import session

_LOGGER = logging.getLogger(__name__)
_INVALID = ("unknown", "unavailable", "")
_TO_INCHES = {"in": 1.0, "mm": 1 / 25.4, "cm": 1 / 2.54}
STALE_SESSION = timedelta(hours=12)


def fired(mode: str, previous: str, current: str) -> bool:
    if mode == c.MOW_MODE_INCREASES:
        try:
            return float(current) > float(previous)
        except ValueError:
            return False
    return current != previous


class CounterWatcher:
    """Logs a mow when the area's mow signal changes. The comparison is always with
    the last valid value saved in the Store, so an HA restart (unavailable -> N)
    never fakes a mow and a change made while HA was down is still caught."""

    def __init__(self, hass: HomeAssistant, coordinator, area_key: str, entity_id: str,
                 mode: str) -> None:
        self.hass = hass
        self._coord = coordinator
        self._key = area_key
        self._entity_id = entity_id
        self._mode = mode
        self._unsub = None

    async def async_start(self) -> None:
        await self._async_check(self.hass.states.get(self._entity_id))
        self._unsub = async_track_state_change_event(self.hass, [self._entity_id],
                                                     self._on_change)

    def stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    def _on_change(self, event: Event) -> None:
        self.hass.async_create_task(self._async_check(event.data["new_state"]))

    async def _async_check(self, st) -> None:
        if st is None or st.state in _INVALID:
            return
        area_state = self._coord.store.areas[self._key]
        last = area_state.mow_source_last
        if last == st.state:
            return
        fire = last is not None and fired(self._mode, last, st.state)
        # Update the in-memory value synchronously, before any await: overlapping
        # checks for the same entity (e.g. an attribute-only update queued right
        # behind a real change) must never both read the same stale `last` and log
        # a duplicate/phantom mow, or race each other's final persisted value.
        # The coordinator's mutations are copy-based and always start from the
        # current store.areas[key] object, so this carries forward correctly.
        area_state.mow_source_last = st.state
        if fire:
            await self._coord.async_log_mow(self._key, source="counter")
        await self._coord.async_save_store()


class MowerTracker:
    """Turns mower activity/location/blade-height changes into per-area mow records
    with the time-weighted blade height. Works however the run was started."""

    def __init__(self, hass: HomeAssistant, coordinator, mower: dict,
                 location_map: dict) -> None:
        self.hass = hass
        self._coord = coordinator
        self._m = mower
        self._map = location_map
        self._grace_s = float(mower.get(c.MOWER_GRACE, c.DEFAULT_GRACE_MINUTES)) * 60
        self._min_area_s = float(mower.get(c.MOWER_MIN_AREA, c.DEFAULT_MIN_AREA_MINUTES)) * 60
        self._unsubs: list = []

    async def async_start(self) -> None:
        now = dt_util.utcnow()
        current = self._coord.store.session
        if current is not None:
            current.last_sample = now          # don't credit time HA was down to an area
        ids = [self._m[c.MOWER_ACTIVITY], self._m[c.MOWER_BLADE], self._m[c.MOWER_LOCATION]]
        self._unsubs.append(async_track_state_change_event(self.hass, ids, self._on_change))
        self._unsubs.append(async_track_time_interval(self.hass, self._async_tick,
                                                      timedelta(minutes=1)))
        self._sample(now)
        await self._coord.async_save_store()

    def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    def _working(self) -> bool:
        st = self.hass.states.get(self._m[c.MOWER_ACTIVITY])
        return st is not None and st.state in self._m.get(c.MOWER_WORKING, [])

    def _area(self):
        st = self.hass.states.get(self._m[c.MOWER_LOCATION])
        return self._map.get(st.state) if st else None

    def _height(self):
        """The current blade height in inches, or session.UNSET for an invalid/unavailable
        reading -- an invalid sample must not clear the session's tracked height;
        it keeps accruing under the last known valid height."""
        st = self.hass.states.get(self._m[c.MOWER_BLADE])
        if st is None or st.state in _INVALID:
            return session.UNSET
        try:
            value = float(st.state)
        except ValueError:
            return session.UNSET
        factor = _TO_INCHES.get(st.attributes.get("unit_of_measurement") or "in")
        return round(value * factor, 2) if factor else session.UNSET

    def _sample(self, now) -> None:
        store = self._coord.store
        height = self._height()
        if store.session is None:
            if self._working():
                store.session = session.start(
                    now, area=self._area(),
                    height_in=None if height is session.UNSET else height)
            return
        session.update(store.session, now, working=self._working(), area=self._area(),
                       height_in=height)

    @callback
    def _on_change(self, event: Event) -> None:
        self._sample(dt_util.utcnow())
        self.hass.async_create_task(self._coord.async_save_store())

    async def _async_tick(self, _now=None) -> None:
        store = self._coord.store
        if store.session is None:
            return
        now = dt_util.utcnow()
        self._sample(now)
        s = store.session
        stale = now - s.started > STALE_SESSION
        if not (session.ready_to_close(s, now, self._grace_s) or stale):
            # Persist the time accrued by this tick: on restart async_start resumes
            # from the saved session (last_sample = now), so anything since the last
            # save would otherwise be lost in a long stretch without state changes.
            await self._coord.async_save_store()
            return
        if stale:
            _LOGGER.debug("Mower session started %s is stale (> %s); closing with "
                         "whatever it has", s.started, STALE_SESSION)
        results = session.results(s, self._min_area_s)
        mowed_on = dt_util.as_local(s.started).date()
        store.session = None
        await self._coord.async_save_store()
        for key, height in results:
            if key in self._coord.areas:
                await self._coord.async_log_mow(key, on=mowed_on, height_in=height,
                                                source="mower_session")
