"""Model configuration: lawn-wide tunables and per-area settings. Pure Python."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Tunables:
    """Model constants. Lawn-wide; not exposed in the UI in v1."""
    budget_fraction: float = 1.0 / 3.0
    # heat hold (warm-season presets shift both thresholds up by the offset)
    heat_temp_f: float = 88.0
    heat_extreme_f: float = 95.0
    warm_heat_offset_f: float = 10.0
    # management events
    fert_peak_days: float = 8.0
    fert_duration_days: float = 28.0
    fert_peak_factor: float = 1.5
    pgr_duration_days: float = 21.0
    pgr_suppression: float = 0.5
    # dormancy
    dormant_gp_threshold: float = 0.1
    dormant_days: int = 10
    # overseed prep
    overseed_buffer_days: int = 7
    overseed_max_removal_fraction: float = 1.0 / 3.0
    overseed_min_mow_interval_days: int = 3
    # establishment / first mow
    germination_days: int = 10
    min_establishment_days: int = 21
    first_mow_ratio: float = 1.5
    # seasonal cut-height phases
    green_up_days: int = 14
    stress_above_opt_f: float = 12.0
    winddown_below_opt_f: float = 13.0
    warm_winddown_f: float = 70.0
    target_min_change_in: float = 0.25
    target_hold_days: int = 7
    # horizons
    forecast_horizon_days: int = 10
    history_days: int = 45
    max_catchup_days: int = 10


@dataclass(frozen=True)
class AreaConfig:
    """One mowing area's settings (built from the config entry by presets.area_from_options)."""
    key: str
    name: str
    grass: str
    curve: str                      # "cool" | "warm"
    opt_temp_f: float
    temp_spread_f: float
    cut_min_in: float
    cut_max_in: float
    overseed_target_in: Optional[float]
    wilting_moisture: float = 40.0
    comfortable_moisture: float = 67.0
    max_growth_rate_mm: float = 6.5
