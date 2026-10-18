"""Turn weather.get_forecasts responses into today's high/low + a daily horizon. Pure Python."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
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


# --- spray-day detail: daily highs and precipitation probability, hourly wind ------

_TO_MPH = {"mph": 1.0, "km/h": 0.621371, "m/s": 2.236936, "kn": 1.150779,
           "ft/s": 0.681818}


def to_mph(value: float, unit: str) -> Optional[float]:
    factor = _TO_MPH.get(unit)
    return None if factor is None else float(value) * factor


@dataclass(frozen=True)
class DayDetail:
    high_f: Optional[float] = None
    rain_pct: Optional[float] = None        # daily precipitation probability


@dataclass(frozen=True)
class HourDetail:
    when: datetime                          # local start of the hour
    temp_f: Optional[float] = None
    wind_mph: Optional[float] = None
    rain_pct: Optional[float] = None


@dataclass(frozen=True)
class ForecastDetail:
    """What the spray-day check reads. Every field is optional in HA's forecast
    schema, so each one is None when the weather integration doesn't give it."""
    days: dict = field(default_factory=dict)      # date -> DayDetail
    hours: tuple = ()                             # HourDetail, ascending

    def high_f(self, day: date) -> Optional[float]:
        d = self.days.get(day)
        if d is not None and d.high_f is not None:
            return d.high_f
        temps = [h.temp_f for h in self.hours if h.when.date() == day
                 and h.temp_f is not None]
        return max(temps) if temps else None


def _num(entry: dict, key: str) -> Optional[float]:
    try:
        value = float(entry[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value


def detail_from(daily, hourly, *, temp_unit: str, wind_unit: str,
                local_date: Callable[[str], date],
                local_dt: Callable[[str], datetime]) -> ForecastDetail:
    days = {}
    for e in daily or []:
        try:
            d = local_date(e["datetime"])
        except (KeyError, TypeError, ValueError):
            continue
        high = _num(e, "temperature")
        days.setdefault(d, DayDetail(None if high is None else to_f(high, temp_unit),
                                     _num(e, "precipitation_probability")))
    hours = []
    for e in hourly or []:
        try:
            when = local_dt(e["datetime"])
        except (KeyError, TypeError, ValueError):
            continue
        temp, wind = _num(e, "temperature"), _num(e, "wind_speed")
        hours.append(HourDetail(when, None if temp is None else to_f(temp, temp_unit),
                                None if wind is None else to_mph(wind, wind_unit),
                                _num(e, "precipitation_probability")))
    hours.sort(key=lambda h: h.when)
    return ForecastDetail(days, tuple(hours))
