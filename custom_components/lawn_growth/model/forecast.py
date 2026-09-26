"""Forward-simulate accumulation to the mow-due day. Pure Python."""
from __future__ import annotations

from . import growth


def growth_forecast_mm(daily_means, max_growth_rate_mm, opt_temp_f, temp_spread_f,
                       water_factor, management_factor) -> list:
    """Per-day predicted growth (mm) from forecast daily mean temps (°F).

    GP varies per day; water and management factors are held at today's values.
    `daily_means` must start TOMORROW — today's growth is already accrued.
    """
    return [
        growth.predicted_growth_mm(
            max_growth_rate_mm,
            growth.growth_potential(mean, opt_temp_f, temp_spread_f),
            water_factor,
            management_factor,
        )
        for mean in daily_means
    ]


def days_until_due(accumulated_mm: float, budget_mm: float, growth_forecast_mm):
    """0 if already due; 1-based day index of the crossing; None past the horizon."""
    if accumulated_mm >= budget_mm:
        return 0
    total = accumulated_mm
    for i, g in enumerate(growth_forecast_mm, start=1):
        total += g
        if total >= budget_mm:
            return i
    return None


def days_until_due_label(due, horizon) -> str:
    """"5" for a count; ">10" when not due within the horizon."""
    return str(due) if due is not None else f">{horizon}"
