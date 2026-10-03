"""Post-seeding establishment and first-mow readiness. Pure Python."""
from __future__ import annotations

from datetime import date, timedelta

from .state import AreaState, OverseedState


def log_seeding(state: AreaState, seeded_on: date) -> AreaState:
    s = state.copy()
    s.seeding_date = seeded_on
    s.seedlings_ready = False
    s.ready_notified = False
    s.accumulated_mm = 0.0
    s.overseed = OverseedState()          # seeding hands off from overseed prep
    return s


def mark_ready(state: AreaState) -> AreaState:
    if state.seeding_date is None:
        raise ValueError("no seeding has been logged for this area")
    s = state.copy()
    s.seedlings_ready = True
    return s


def seedling_height_in(history, seeding_date: date, germination_days: int) -> float:
    """Estimated seedling height: modelled growth summed from germination on."""
    start = seeding_date + timedelta(days=germination_days)
    return sum(h.growth_mm for h in history if h.date >= start) / 25.4


def looks_ready(state: AreaState, *, today: date, seedling_in: float,
                first_mow_target_in: float, tun) -> bool:
    """The model's estimate that the seedlings could take a first mow. Advisory
    only: mowing stays held until the operator presses Seedlings ready."""
    if state.seeding_date is None:
        return False
    if (today - state.seeding_date).days < tun.min_establishment_days:
        return False
    return seedling_in >= tun.first_mow_ratio * first_mow_target_in
