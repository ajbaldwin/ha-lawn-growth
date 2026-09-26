"""Accrue days the daily run missed (HA was down) from the stored forecast. Pure Python."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from . import growth
from .state import DayRecord

_LOGGER = logging.getLogger(__name__)


def missed_days(last_accrual: Optional[date], today: date, max_days: int) -> list:
    """Days strictly between the last accrual and today (most recent `max_days`)."""
    if last_accrual is None:
        return []
    gap = (today - last_accrual).days - 1
    if gap <= 0:
        return []
    n = min(gap, max_days)
    return [today - timedelta(days=i) for i in range(n, 0, -1)]


def catchup_records(missed, forecast_means: dict, cfg, water_factor: float,
                    management_factor: float) -> list:
    """One DayRecord per missed day whose mean the last run's forecast predicted."""
    out, skipped = [], []
    for d in missed:
        mean = forecast_means.get(d.isoformat())
        if mean is None:
            skipped.append(d.isoformat())
            continue
        gp = growth.growth_potential(mean, cfg.opt_temp_f, cfg.temp_spread_f)
        out.append(DayRecord(d, float(mean), gp, growth.predicted_growth_mm(
            cfg.max_growth_rate_mm, gp, water_factor, management_factor)))
    if skipped:
        _LOGGER.info("%s: no stored forecast for missed day(s) %s; they are not caught up",
                     cfg.name, ", ".join(skipped))
    return out
