"""Winter-dormancy detection. Pure Python."""
from __future__ import annotations


def update_dormancy(streak: int, gp_today: float, tun) -> tuple[int, bool]:
    """Advance the low-Growth-Potential streak; report dormant when sustained.

    Returns (new_streak, dormant). A single day of growth resets the streak.
    """
    if gp_today <= tun.dormant_gp_threshold:
        streak = streak + 1
    else:
        streak = 0
    return streak, streak >= tun.dormant_days
