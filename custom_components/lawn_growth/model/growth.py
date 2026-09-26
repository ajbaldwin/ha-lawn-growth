"""Cool-season Growth Potential and predicted daily growth. Pure Python."""
from __future__ import annotations

import math


def growth_potential(mean_temp_f: float, opt_temp_f: float = 68.0,
                     spread_f: float = 10.0) -> float:
    """Temperature-driven Growth Potential, 0.0–1.0.

    A Gaussian centered on the cool-season optimum: 1.0 at the optimum, falling
    off symmetrically as the daily mean temperature departs from it.
    """
    if spread_f <= 0:
        raise ValueError("spread_f must be positive")
    z = (mean_temp_f - opt_temp_f) / spread_f
    return math.exp(-0.5 * z * z)


def predicted_growth_mm(max_rate_mm: float, gp: float, water_factor: float,
                        management_factor: float) -> float:
    """Predicted vertical growth for the day, in millimetres."""
    return max_rate_mm * gp * water_factor * management_factor
