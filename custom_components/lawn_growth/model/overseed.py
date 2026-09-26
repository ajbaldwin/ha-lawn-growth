"""Overseed-prep descent + feasibility math. Pure Python.

Paces the recommended cut height down toward an overseed target ahead of a seed
date, respecting the 1/3 rule (never remove more than 1/3 of standing height per
pass). Advisory only — nothing here touches HA or the mower.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


def safe_next_cut(standing_in: float, target_in: float,
                  max_removal_fraction: float) -> float:
    """Lowest safe cut for one pass: never remove more than
    `max_removal_fraction` of the standing height, never below `target_in`.
    Cutting from a shorter standing plant reaches a lower absolute height, so
    frequent light mows ratchet the height down fastest."""
    return max(target_in, standing_in * (1.0 - max_removal_fraction))


def passes_needed(start_in: float, target_in: float, max_removal_fraction: float,
                  regrowth_in: float) -> Optional[int]:
    """Passes to descend from start to target, assuming `regrowth_in` of regrowth
    before each pass. None if the descent stalls (a safe cut never lowers the
    height because regrowth is too vigorous)."""
    if start_in <= target_in:
        return 0
    current = start_in
    passes = 0
    while current > target_in:
        nxt = safe_next_cut(current + regrowth_in, target_in, max_removal_fraction)
        if nxt >= current:
            return None
        current = nxt
        passes += 1
        if passes > 100:  # guard against pathological inputs
            return None
    return passes


@dataclass(frozen=True)
class OverseedPlan:
    active: bool
    recommended_cut_in: float
    next_mow_in_days: Optional[int]
    feasible: bool
    earliest_seed_date: Optional[date]
    arrival_date: Optional[date]
    status: str
    target_in: float


def plan(*, current_cut_in: float, target_in: float, seed_date: Optional[date],
         buffer_days: int, today: date, regrowth_per_day_in: float,
         min_mow_interval_days: int, max_removal_fraction: float,
         heat_frozen: bool) -> OverseedPlan:
    """Decide the overseed-prep state for one zone on one day. Pure."""
    if seed_date is None:
        return OverseedPlan(active=False, recommended_cut_in=current_cut_in,
                            next_mow_in_days=None, feasible=True,
                            earliest_seed_date=None, arrival_date=None,
                            status="inactive", target_in=target_in)

    arrival = seed_date - timedelta(days=buffer_days)

    if current_cut_in <= target_in:
        return OverseedPlan(active=True, recommended_cut_in=target_in,
                            next_mow_in_days=None, feasible=True,
                            earliest_seed_date=None, arrival_date=arrival,
                            status="target reached; holding until seed date",
                            target_in=target_in)

    regrowth_per_pass = regrowth_per_day_in * min_mow_interval_days
    passes = passes_needed(current_cut_in, target_in, max_removal_fraction,
                           regrowth_per_pass)
    if passes is None:
        return OverseedPlan(active=True, recommended_cut_in=current_cut_in,
                            next_mow_in_days=None, feasible=False,
                            earliest_seed_date=None, arrival_date=arrival,
                            status="infeasible: growth too vigorous to descend",
                            target_in=target_in)

    # `passes` mows, first today, each min_mow_interval_days apart -> the last
    # falls min_days_needed days from now.
    min_days_needed = max(0, passes - 1) * min_mow_interval_days

    if (seed_date - today).days < min_days_needed:
        earliest_seed = today + timedelta(days=min_days_needed)
        return OverseedPlan(active=True, recommended_cut_in=current_cut_in,
                            next_mow_in_days=None, feasible=False,
                            earliest_seed_date=earliest_seed, arrival_date=arrival,
                            status="infeasible: cannot reach target by seed date",
                            target_in=target_in)

    if heat_frozen:
        return OverseedPlan(active=True, recommended_cut_in=current_cut_in,
                            next_mow_in_days=None, feasible=True,
                            earliest_seed_date=None, arrival_date=arrival,
                            status="paused (heat hold)", target_in=target_in)

    if (arrival - today).days > min_days_needed:
        return OverseedPlan(active=True, recommended_cut_in=current_cut_in,
                            next_mow_in_days=None, feasible=True,
                            earliest_seed_date=None, arrival_date=arrival,
                            status="scheduled; descent not yet started",
                            target_in=target_in)

    # The recommended cut for this pass is the 1/3-safe deck height (below the
    # current standing), so cutting there actually descends. Returning the
    # current height instead left the descent recommendation frozen while the
    # mow ratchet still stepped the belief down — belief then ran ahead of the
    # deck the operator was told to use.
    next_cut = safe_next_cut(current_cut_in + regrowth_per_pass, target_in,
                             max_removal_fraction)
    return OverseedPlan(active=True, recommended_cut_in=next_cut,
                        next_mow_in_days=min_mow_interval_days, feasible=True,
                        earliest_seed_date=None, arrival_date=arrival,
                        status="descending", target_in=target_in)
