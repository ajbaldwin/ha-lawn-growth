"""Persistent state for one Lawn Growth entry (a Home Assistant Store)."""
from __future__ import annotations

from datetime import date, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_MINOR_VERSION, STORAGE_VERSION
from .model import applications
from .model.applications import Application
from .model.calwriter import Ledger
from .model.gdd import GddState
from .model.management import ManagementEvent
from .model.session import MowerSession
from .model.state import AreaState
from .model.windows import Window

EVENT_RETENTION_DAYS = 35     # beyond the fert (28 d) and PGR (21 d) effect windows
GROWTH_KINDS = ("fert", "pgr", "winterizer")     # the kinds the growth model reads


class _StoreFile(Store[dict]):
    async def _async_migrate_func(self, old_major_version, old_minor_version, old_data):
        data = dict(old_data)
        if old_minor_version < 2:
            # 1.2: the application log, seeded from the fert/PGR events and seedings
            # still on record.
            apps = [dict(e) for e in data.get("events", [])]
            for key, area in (data.get("areas") or {}).items():
                if area.get("seeding_date"):
                    apps.append({"kind": "seeding", "date": area["seeding_date"],
                                 "areas": [key]})
            data["applications"] = sorted(apps, key=lambda a: a["date"])
            data.setdefault("windows", {})
        return data


class LawnStore:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = _StoreFile(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}",
                                 minor_version=STORAGE_MINOR_VERSION)
        self.areas: dict[str, AreaState] = {}
        self.events: list[dict] = []           # {"kind", "date", "areas": [keys]}
        self.session: MowerSession | None = None
        self.gdd = GddState()                  # lawn-wide growing degree days
        self.applications: list[Application] = []   # 400-day application log
        self.windows: dict[str, Window] = {}   # windows.window_key -> Window
        self.pre_emergent_product: str | None = None  # None: follow the suggestion
        self.calendar_ledgers: dict[str, Ledger] = {}  # target calendar -> what's written

    async def async_load(self, area_keys) -> None:
        raw = await self._store.async_load() or {}
        stored = raw.get("areas", {})
        self.areas = {k: AreaState.from_dict(stored.get(k, {})) for k in area_keys}
        self.events = list(raw.get("events", []))
        sess = raw.get("session")
        self.session = MowerSession.from_dict(sess) if sess else None
        self.gdd = GddState.from_dict(raw.get("gdd") or {})
        self.applications = [Application.from_dict(a) for a in raw.get("applications", [])]
        self.windows = {k: Window.from_dict(w) for k, w in (raw.get("windows") or {}).items()}
        self.pre_emergent_product = raw.get("pre_emergent_product")
        self.calendar_ledgers = {k: Ledger.from_dict(v)
                                 for k, v in (raw.get("calendar_ledgers") or {}).items()}

    async def async_save(self) -> None:
        await self._store.async_save({
            "areas": {k: s.to_dict() for k, s in self.areas.items()},
            "events": self.events,
            "session": self.session.to_dict() if self.session else None,
            "gdd": self.gdd.to_dict(),
            "applications": [a.to_dict() for a in self.applications],
            "windows": {k: w.to_dict() for k, w in self.windows.items()},
            "pre_emergent_product": self.pre_emergent_product,
            "calendar_ledgers": {k: v.to_dict() for k, v in self.calendar_ledgers.items()},
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

    def latest_event_date(self, area_key: str, kind: str, today: date) -> date | None:
        """Most recent stored date for this area/kind, ignoring anything older than
        the retention window (matches add_event's pruning, for events that predate
        the last add_event prune but have since aged out)."""
        cutoff = today - timedelta(days=EVENT_RETENTION_DAYS)
        dates = [date.fromisoformat(e["date"]) for e in self.events
                 if area_key in e["areas"] and e["kind"] == kind
                 and date.fromisoformat(e["date"]) >= cutoff]
        return max(dates) if dates else None

    def add_application(self, kind: str, on: date, area_keys, today: date, *,
                        product: str = "", replaces: date | None = None,
                        retention_days: int = 400) -> None:
        """Append to the application log, pruning past the retention. `replaces`
        drops this kind's entry for the same area(s) on that date first (a seeding
        date corrected rather than a new seeding)."""
        keys = tuple(area_keys)
        apps = applications.prune(self.applications, today, retention_days)
        if replaces is not None:
            apps = [a for a in apps
                    if not (a.kind == kind and a.date == replaces and a.areas == keys)]
        apps.append(Application(kind, on, keys, product))
        self.applications = sorted(apps, key=lambda a: a.date)

    def logged_applications(self, today: date, retention_days: int = 400) -> list:
        """The log within its retention (entries age out between appends too)."""
        return applications.prune(self.applications, today, retention_days)
