"""Fertilizer and PGR growth-modifier curves. Pure Python."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ManagementEvent:
    kind: str          # "fert" | "pgr"
    applied: date


def _fert_factor(days: int, tun) -> float:
    """Ramp 1.0 -> peak by fert_peak_days, then decay to 1.0 by fert_duration."""
    if days < 0 or days > tun.fert_duration_days:
        return 1.0
    peak = tun.fert_peak_factor
    if days <= tun.fert_peak_days:
        frac = days / tun.fert_peak_days if tun.fert_peak_days else 1.0
        return 1.0 + (peak - 1.0) * frac
    span = tun.fert_duration_days - tun.fert_peak_days
    frac = (days - tun.fert_peak_days) / span if span else 1.0
    return peak - (peak - 1.0) * frac


def _pgr_factor(days: int, tun) -> float:
    """Suppression strongest at application, decaying back to 1.0 by pgr_duration."""
    if days < 0 or days > tun.pgr_duration_days:
        return 1.0
    supp = tun.pgr_suppression
    frac = days / tun.pgr_duration_days if tun.pgr_duration_days else 1.0
    return supp + (1.0 - supp) * frac


def management_factor(events, today: date, tun) -> float:
    factor = 1.0
    for e in events:
        days = (today - e.applied).days
        if e.kind == "fert":
            factor *= _fert_factor(days, tun)
        elif e.kind == "pgr":
            factor *= _pgr_factor(days, tun)
    return factor
