"""Lawn-wide growing degree days (simple-average method). Pure Python.

One accumulator per lawn, reset at the season start (Jan 1 by default). Days are
processed once each, in order; a day with no temperature data advances the
cursor without adding. The previous season's final total is kept for tuning.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


def _d(value) -> Optional[date]:
    return date.fromisoformat(value) if value else None


@dataclass
class GddState:
    year: Optional[int] = None              # season the total belongs to
    total: float = 0.0
    last_day: Optional[date] = None         # last day processed (accrued or skipped)
    source: str = ""                        # "sensor" | "forecast" for the last accrued day
    last_season_total: Optional[float] = None

    def copy(self) -> "GddState":
        return GddState.from_dict(self.to_dict())

    def to_dict(self) -> dict:
        return {"year": self.year, "total": self.total,
                "last_day": self.last_day.isoformat() if self.last_day else None,
                "source": self.source, "last_season_total": self.last_season_total}

    @classmethod
    def from_dict(cls, d: dict) -> "GddState":
        year = d.get("year")
        lst = d.get("last_season_total")
        return cls(int(year) if year is not None else None, float(d.get("total", 0.0)),
                   _d(d.get("last_day")), d.get("source", ""),
                   float(lst) if lst is not None else None)


def gdd_day(tmax_f: float, tmin_f: float, base_f: float) -> float:
    return max(0.0, (tmax_f + tmin_f) / 2 - base_f)


def gdd_from_mean(mean_f: float, base_f: float) -> float:
    return max(0.0, mean_f - base_f)


def season_start(year: int, tun) -> date:
    return date(year, tun.gdd_start_month, tun.gdd_start_day)


def days_to_process(state: GddState, yesterday: date, tun) -> list[date]:
    """Unprocessed days through yesterday, ascending, capped to the most recent."""
    if state.last_day is not None:
        first = state.last_day + timedelta(days=1)
    else:
        first = season_start(yesterday.year, tun)
        if first > yesterday:
            first = season_start(yesterday.year - 1, tun)
    n = (yesterday - first).days + 1
    if n <= 0:
        return []
    n = min(n, tun.gdd_max_backfill_days)
    return [yesterday - timedelta(days=i) for i in range(n - 1, -1, -1)]


def accrue(state: GddState, day: date, value: Optional[float], source: str,
           tun) -> GddState:
    """Process one day's GDD (None = no data). Returns a new state."""
    s = state.copy()
    if s.last_day is not None and day <= s.last_day:
        return s
    if day >= season_start(day.year, tun) and s.year != day.year:
        if s.year is not None:
            s.last_season_total = s.total
        s.total = 0.0
        s.year = day.year
    if day >= season_start(day.year, tun) and value is not None:
        s.total += value
        s.source = source
    s.last_day = day
    return s
