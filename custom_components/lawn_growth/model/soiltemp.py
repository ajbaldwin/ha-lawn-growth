"""Quality-gated daily soil temperature from GeoDrops probes. Pure Python.

A temperature reading is usable only while the probe's depth quality is good and
its health is one that doesn't affect temperature (hardware_check is ignored on
purpose, spec D9). A probe's day mean is time-weighted over the usable part of
the day; an area's day counts only when a probe covers enough of it. Soil5 is the
mean of the valid days among the trailing window ending yesterday.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from datetime import date, datetime, timedelta
from typing import Optional

USABLE_QUALITY = frozenset({"good"})
USABLE_HEALTH = frozenset({"ok", "max_moisture_required", "wick_renewal_needed",
                           "hardware_check"})

_MISSING = object()                 # before an entity's first state: unknown


def reading_usable(temp_f: Optional[float], quality: Optional[str],
                   health: Optional[str]) -> bool:
    if temp_f is None or not isinstance(temp_f, (int, float)) or math.isnan(temp_f):
        return False
    return ((quality or "").strip().lower() in USABLE_QUALITY
            and (health or "").strip().lower() in USABLE_HEALTH)


def _value_at(series, times, t):
    i = bisect_right(times, t)
    return series[i - 1][1] if i else _MISSING


def probe_day_mean(temp, quality, health, start: datetime,
                   end: datetime) -> tuple[Optional[float], float]:
    """Time-weighted mean of usable temp over [start, end) and the usable fraction."""
    total = (end - start).total_seconds()
    if total <= 0:
        return None, 0.0
    series = (temp, quality, health)
    times = [[t for t, _ in s] for s in series]
    cuts = sorted({start, end} | {t for ts in times for t in ts if start < t < end})
    usable_s = 0.0
    weighted = 0.0
    for a, b in zip(cuts, cuts[1:]):
        tv, qv, hv = (_value_at(s, ts, a) for s, ts in zip(series, times))
        if _MISSING in (tv, qv, hv) or not reading_usable(tv, qv, hv):
            continue
        secs = (b - a).total_seconds()
        usable_s += secs
        weighted += tv * secs
    if usable_s <= 0:
        return None, 0.0
    return weighted / usable_s, min(1.0, usable_s / total)


def area_day(probes: list[tuple[Optional[float], float]],
             min_coverage: float) -> tuple[Optional[float], float]:
    """Mean of the qualifying probe means (None if none) and the best coverage."""
    good = [m for m, c in probes if m is not None and c >= min_coverage]
    best = max((c for _, c in probes), default=0.0)
    return (sum(good) / len(good) if good else None), best


def soil5(days: dict[date, Optional[float]], today: date, window: int = 5,
          min_valid: int = 3) -> tuple[Optional[float], int]:
    """Mean of the valid days in [today - window, today - 1]; None below min_valid."""
    vals = [days.get(today - timedelta(days=n)) for n in range(1, window + 1)]
    vals = [v for v in vals if v is not None]
    if len(vals) < min_valid:
        return None, len(vals)
    return sum(vals) / len(vals), len(vals)


def trend(days: dict[date, Optional[float]], today: date, window: int = 7,
          min_valid: int = 3) -> Optional[float]:
    """Least-squares slope (°F/day) of the valid daily means in the trailing window
    ending yesterday; None below min_valid days."""
    pts = [(-n, days[today - timedelta(days=n)]) for n in range(window, 0, -1)
           if days.get(today - timedelta(days=n)) is not None]
    if len(pts) < min_valid:
        return None
    mx = sum(x for x, _ in pts) / len(pts)
    my = sum(y for _, y in pts) / len(pts)
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    return sum((x - mx) * (y - my) for x, y in pts) / sxx


def source_for(soil5_value: Optional[float]) -> str:
    return "geodrops" if soil5_value is not None else "gdd"


def prune_days(days: dict[str, dict], today: date, keep: int) -> dict[str, dict]:
    oldest = today - timedelta(days=keep)
    out = {}
    for key, rec in days.items():
        try:
            d = date.fromisoformat(key)
        except (TypeError, ValueError):
            continue
        if oldest <= d < today:
            out[key] = dict(rec)
    return out


def days_by_date(days: dict[str, dict]) -> dict[date, Optional[float]]:
    out = {}
    for key, rec in days.items():
        try:
            out[date.fromisoformat(key)] = rec.get("mean_f")
        except (TypeError, ValueError):
            continue
    return out
