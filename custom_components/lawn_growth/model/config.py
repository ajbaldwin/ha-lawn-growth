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
    # soil temperature / GDD
    gdd_base_f: float = 50.0
    gdd_start_month: int = 1
    gdd_start_day: int = 1
    gdd_max_backfill_days: int = 366
    soil_min_coverage: float = 0.75
    soil_window_days: int = 5
    soil_min_valid_days: int = 3
    soil_days_kept: int = 7
    # application log and herbicide seeding waits (label placeholders: check the label)
    application_retention_days: int = 400
    prodiamine_seeding_block_days: int = 112            # 16 weeks
    dithiopyr_seeding_block_days: int = 84              # 12 weeks
    triclopyr_ester_seeding_block_days: int = 28        # 4 weeks
    other_pre_emergent_seeding_block_days: int = 84
    other_post_emergent_seeding_block_days: int = 28
    # pre-emergent window (lawn-wide; spring). Soil5 °F / GDD50 per stage:
    # heads-up (soil also rising), open, late warning, germination expected
    pre_soil_f: tuple = (47.0, 50.0, 53.0, 55.0)
    pre_gdd: tuple = (75.0, 125.0, 175.0, 200.0)
    pre_close_days: int = 14                 # missed this long after germination
    pre_open_estimate_days: int = 35         # open -> expected close, when unprojectable
    pre_typical: tuple = (4, 10)             # (month, day) of the tentative event
    pre_season_end_month: int = 7            # from Jul 1 the next spring's window shows
    split_reminder: bool = True
    split_reminder_days: int = 49            # 7 weeks after the first application
    # winterizer (per area; late fall)
    winterizer_typical: tuple = (11, 5)
    winterizer_from_month: int = 8
    winterizer_quiet_days: int = 10          # after the last mow, with no mow due
    winterizer_spacing_days: int = 28        # since the last fertilizer
    winterizer_min_soil_f: float = 40.0
    winterizer_cold_days: int = 3
    # fall overseed window (per area)
    overseed_typical: tuple = (8, 25)
    overseed_from_month: int = 8
    overseed_open_soil_f: float = 70.0
    overseed_ideal_low_f: float = 60.0
    overseed_close_soil_f: float = 55.0
    overseed_open_air_t7_f: float = 72.0
    overseed_close_air_t7_f: float = 50.0
    overseed_closing_notice_days: int = 7
    # application calendar
    calendar_show_mows: bool = False


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
