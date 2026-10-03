"""Durable per-area model state and its JSON (de)serialization. Pure Python."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


def _d(value) -> Optional[date]:
    return date.fromisoformat(value) if value else None


def _s(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None


@dataclass
class MowRecord:
    date: date
    height_in: float
    source: str                     # "mower_session" | "counter" | "manual"

    def to_dict(self) -> dict:
        return {"date": self.date.isoformat(), "height_in": self.height_in,
                "source": self.source}

    @classmethod
    def from_dict(cls, d: dict) -> "MowRecord":
        return cls(date.fromisoformat(d["date"]), float(d["height_in"]), d["source"])


@dataclass
class DayRecord:
    date: date
    mean_f: float
    gp: float
    growth_mm: float                # predicted growth before any mode zeroing

    def to_dict(self) -> dict:
        return {"date": self.date.isoformat(), "mean_f": self.mean_f, "gp": self.gp,
                "growth_mm": self.growth_mm}

    @classmethod
    def from_dict(cls, d: dict) -> "DayRecord":
        return cls(date.fromisoformat(d["date"]), float(d["mean_f"]), float(d["gp"]),
                   float(d["growth_mm"]))


@dataclass
class OverseedState:
    seed_date: Optional[date] = None
    target_in: Optional[float] = None
    buffer_days: Optional[int] = None
    notified: str = ""

    def to_dict(self) -> dict:
        return {"seed_date": _s(self.seed_date), "target_in": self.target_in,
                "buffer_days": self.buffer_days, "notified": self.notified}

    @classmethod
    def from_dict(cls, d: dict) -> "OverseedState":
        return cls(_d(d.get("seed_date")), d.get("target_in"), d.get("buffer_days"),
                   d.get("notified", ""))


@dataclass
class AreaState:
    accumulated_mm: float = 0.0
    last_accrual: Optional[date] = None
    last_mow: Optional[date] = None
    low_gp_streak: int = 0
    seeding_date: Optional[date] = None
    seedlings_ready: bool = False
    ready_notified: bool = False
    due_notified: bool = False
    mow_records: list = field(default_factory=list)        # list[MowRecord], date-ascending
    overseed: OverseedState = field(default_factory=OverseedState)
    forecast_means: dict = field(default_factory=dict)     # iso date -> mean °F
    last_water_factor: float = 1.0
    last_management_factor: float = 1.0
    history: list = field(default_factory=list)            # list[DayRecord], date-ascending
    target_in: Optional[float] = None
    phase: Optional[str] = None
    target_changed_on: Optional[date] = None
    green_up_start: Optional[date] = None
    was_in_season: Optional[bool] = None
    mow_source_last: Optional[str] = None
    log_mow_height_in: Optional[float] = None    # Log mow height; None = last cut

    @property
    def last_cut_in(self) -> Optional[float]:
        return self.mow_records[-1].height_in if self.mow_records else None

    def copy(self) -> "AreaState":
        return AreaState.from_dict(self.to_dict())

    def to_dict(self) -> dict:
        return {
            "accumulated_mm": self.accumulated_mm,
            "last_accrual": _s(self.last_accrual),
            "last_mow": _s(self.last_mow),
            "low_gp_streak": self.low_gp_streak,
            "seeding_date": _s(self.seeding_date),
            "seedlings_ready": self.seedlings_ready,
            "ready_notified": self.ready_notified,
            "due_notified": self.due_notified,
            "mow_records": [r.to_dict() for r in self.mow_records],
            "overseed": self.overseed.to_dict(),
            "forecast_means": dict(self.forecast_means),
            "last_water_factor": self.last_water_factor,
            "last_management_factor": self.last_management_factor,
            "history": [h.to_dict() for h in self.history],
            "target_in": self.target_in,
            "phase": self.phase,
            "target_changed_on": _s(self.target_changed_on),
            "green_up_start": _s(self.green_up_start),
            "was_in_season": self.was_in_season,
            "mow_source_last": self.mow_source_last,
            "log_mow_height_in": self.log_mow_height_in,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AreaState":
        return cls(
            accumulated_mm=float(d.get("accumulated_mm", 0.0)),
            last_accrual=_d(d.get("last_accrual")),
            last_mow=_d(d.get("last_mow")),
            low_gp_streak=int(d.get("low_gp_streak", 0)),
            seeding_date=_d(d.get("seeding_date")),
            seedlings_ready=bool(d.get("seedlings_ready", False)),
            ready_notified=bool(d.get("ready_notified", False)),
            due_notified=bool(d.get("due_notified", False)),
            mow_records=[MowRecord.from_dict(r) for r in d.get("mow_records", [])],
            overseed=OverseedState.from_dict(d.get("overseed", {})),
            forecast_means=dict(d.get("forecast_means", {})),
            last_water_factor=float(d.get("last_water_factor", 1.0)),
            last_management_factor=float(d.get("last_management_factor", 1.0)),
            history=[DayRecord.from_dict(h) for h in d.get("history", [])],
            target_in=d.get("target_in"),
            phase=d.get("phase"),
            target_changed_on=_d(d.get("target_changed_on")),
            green_up_start=_d(d.get("green_up_start")),
            was_in_season=d.get("was_in_season"),
            mow_source_last=d.get("mow_source_last"),
            log_mow_height_in=d.get("log_mow_height_in"),
        )
