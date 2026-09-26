"""Condition-driven seasonal cut-height phases. Pure Python.

No calendar: the phase comes from smoothed temperature (T7 = trailing 7-day mean,
F7 = next-7-day forecast mean), dormancy exit / season start (green-up), and heat
hold. Each phase maps to a position inside the area's cut range. Hysteresis keeps
the target from flip-flopping (>= 0.25" change and >= 7 days between changes,
except an immediate raise when entering summer stress).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

PHASES = ("green_up", "active", "stress", "wind_down")

_POSITION = {
    "cool": {"green_up": 0.25, "active": 0.5, "stress": 1.0, "wind_down": 0.0},
    "warm": {"green_up": 0.0, "active": 0.25, "stress": 0.5, "wind_down": 1.0},
}


def trailing_mean_temp(history, fallback: float, days: int = 7) -> float:
    recent = [h.mean_f for h in history[-days:]]
    return sum(recent) / len(recent) if recent else fallback


def detect_phase(cfg, tun, *, today: date, t7: float, f7: float,
                 green_up_start: Optional[date], heat_hold_today: bool) -> str:
    if green_up_start is not None and 0 <= (today - green_up_start).days < tun.green_up_days:
        return "green_up"
    if cfg.curve == "cool":
        if heat_hold_today or t7 >= cfg.opt_temp_f + tun.stress_above_opt_f:
            return "stress"
        if t7 < cfg.opt_temp_f - tun.winddown_below_opt_f and f7 < t7:
            return "wind_down"
        return "active"
    if heat_hold_today:
        return "stress"
    if t7 < tun.warm_winddown_f and f7 < t7:
        return "wind_down"
    return "active"


def phase_target(cfg, phase: str) -> float:
    pos = _POSITION[cfg.curve][phase]
    return round(cfg.cut_min_in + pos * (cfg.cut_max_in - cfg.cut_min_in), 2)


def update_target(prev_target: Optional[float], prev_changed_on: Optional[date],
                  new_target: float, phase: str, today: date, tun):
    if prev_target is None:
        return new_target, today
    if phase == "stress" and new_target > prev_target:
        return new_target, today
    if abs(new_target - prev_target) < tun.target_min_change_in - 1e-9:
        return prev_target, prev_changed_on
    if prev_changed_on is not None and (today - prev_changed_on).days < tun.target_hold_days:
        return prev_target, prev_changed_on
    return new_target, today


def next_pass(last_cut_in: float, target_in: float, budget_fraction: float,
              max_removal_fraction: float) -> float:
    """The deck height for the next mow. Raising is immediate; lowering never
    removes more than `max_removal_fraction` of the standing height, where the
    standing height at mow time is the last cut plus one full growth budget."""
    if target_in >= last_cut_in:
        return target_in
    standing = last_cut_in * (1.0 + budget_fraction)
    return round(max(target_in, standing * (1.0 - max_removal_fraction)), 2)
