"""Turn weather.get_forecasts responses into today's high/low + a daily horizon. Pure Python."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional


def to_f(value: float, unit: str) -> float:
    return float(value) * 9.0 / 5.0 + 32.0 if unit in ("°C", "C") else float(value)


@dataclass(frozen=True)
class DailyTemps:
    today_high_f: float
    today_low_f: float
    horizon: list          # [(date, mean °F)] for days AFTER today, ascending


def from_daily(entries, today: date, unit: str,
               local_date: Callable[[str], date]) -> Optional[DailyTemps]:
    """Daily forecast rows: day 0 (today) gives high/low; later days form the horizon.
    Rows without a numeric `templow` are skipped (their mean would be wrong)."""
    today_hl = None
    horizon = []
    for e in entries or []:
        try:
            d = local_date(e["datetime"])
            hi = to_f(float(e["temperature"]), unit)
            lo = to_f(float(e["templow"]), unit)
        except (KeyError, TypeError, ValueError):
            continue
        if d == today and today_hl is None:
            today_hl = (hi, lo)
        elif d > today:
            horizon.append((d, (hi + lo) / 2.0))
    if today_hl is None:
        return None
    horizon.sort()
    return DailyTemps(today_hl[0], today_hl[1], horizon)


def from_hourly(entries, today: date, unit: str,
                local_date: Callable[[str], date]) -> Optional[DailyTemps]:
    """Fallback: group hourly rows by local date and use each day's max/min.
    Today's high/low only covers the remaining hours — an approximation."""
    by_day: dict = {}
    for e in entries or []:
        try:
            d = local_date(e["datetime"])
            t = to_f(float(e["temperature"]), unit)
        except (KeyError, TypeError, ValueError):
            continue
        by_day.setdefault(d, []).append(t)
    if today not in by_day:
        return None
    temps = by_day[today]
    horizon = sorted((d, (max(v) + min(v)) / 2.0) for d, v in by_day.items() if d > today)
    return DailyTemps(max(temps), min(temps), horizon)
