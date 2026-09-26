"""Quality-gated soil-moisture reading. Pure Python.

A GeoDrops reading is trusted only when its dominant value is numeric AND at
least MIN_USABLE_DEPTHS of its depth-quality states are good/poor (compared
case-insensitively: older GeoDrops releases report "Good", 0.6+ report "good").
A sensor with no quality sensors (any non-GeoDrops sensor) is trusted when numeric.
"""
from __future__ import annotations

from typing import Optional

_UNAVAILABLE = {"unknown", "unavailable", "none", ""}
_USABLE_QUALITY = {"good", "poor"}
MIN_USABLE_DEPTHS = 2


def usable_moisture(dominant_raw, qualities) -> Optional[float]:
    dom = (dominant_raw or "").strip()
    if dom.lower() in _UNAVAILABLE:
        return None
    try:
        value = float(dom)
    except ValueError:
        return None
    if not qualities:
        return value
    usable = sum(1 for q in qualities if (q or "").strip().lower() in _USABLE_QUALITY)
    return value if usable >= MIN_USABLE_DEPTHS else None


def average_usable(readings) -> Optional[float]:
    """Average of the trusted (dominant_raw, qualities) readings; None if none."""
    vals = [v for v in (usable_moisture(d, q) for d, q in readings) if v is not None]
    return sum(vals) / len(vals) if vals else None
