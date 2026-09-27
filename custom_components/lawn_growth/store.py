"""Persistent state for one Lawn Growth entry (a Home Assistant Store)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION
from .model.management import ManagementEvent
from .model.session import MowerSession
from .model.state import AreaState

EVENT_RETENTION_DAYS = 35     # beyond the fert (28 d) and PGR (21 d) effect windows


class LawnStore:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")
        self.areas: dict[str, AreaState] = {}
        self.events: list[dict] = []           # {"kind", "date", "areas": [keys]}
        self.session: MowerSession | None = None

    async def async_load(self, area_keys) -> None:
        raw = await self._store.async_load() or {}
        stored = raw.get("areas", {})
        self.areas = {k: AreaState.from_dict(stored.get(k, {})) for k in area_keys}
        self.events = list(raw.get("events", []))
        sess = raw.get("session")
        self.session = MowerSession.from_dict(sess) if sess else None

    async def async_save(self) -> None:
        await self._store.async_save({
            "areas": {k: s.to_dict() for k, s in self.areas.items()},
            "events": self.events,
            "session": self.session.to_dict() if self.session else None,
        })

    async def async_remove(self) -> None:
        await self._store.async_remove()

    def add_event(self, kind: str, on: date, area_keys, today: date) -> None:
        cutoff = today - timedelta(days=EVENT_RETENTION_DAYS)
        self.events = [e for e in self.events if date.fromisoformat(e["date"]) >= cutoff]
        self.events.append({"kind": kind, "date": on.isoformat(), "areas": list(area_keys)})

    def events_for(self, area_key: str) -> list[ManagementEvent]:
        return [ManagementEvent(kind=e["kind"], applied=date.fromisoformat(e["date"]))
                for e in self.events if area_key in e["areas"]]

    def latest_event_date(self, area_key: str, kind: str) -> Optional[date]:
        dates = [date.fromisoformat(e["date"]) for e in self.events
                if area_key in e["areas"] and e["kind"] == kind]
        return max(dates) if dates else None
