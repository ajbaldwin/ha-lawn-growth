"""Compose one mowing area's evaluation for one day. Pure Python."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from . import (catchup, establishment, forecast, growth, heat, management, modes,
               overseed, phases, season, water)
from .state import AreaState, DayRecord

DUE_MODES = ("normal", "heat_hold")

_PHASE_NOTES = {
    "green_up": "spring green-up: a slightly lower cut clears dormant tissue",
    "active": "active growth: mid-range height",
    "stress": "stress: keep it tall",
    "wind_down": "fall wind-down: step down toward the final cut",
}


@dataclass(frozen=True)
class DayInputs:
    today: date
    in_season: bool
    high_f: float
    low_f: float
    horizon: list                   # [(date, mean °F)] for days AFTER today, ascending
    moisture: float
    moisture_source: str            # "sensors" | "fallback"
    events: list                    # [management.ManagementEvent]
    moisture_sensors_used: tuple = ()


@dataclass(frozen=True)
class AreaResult:
    mode: str
    phase: str
    gp: float
    growth_today_mm: float
    accumulated_mm: float
    budget_mm: float
    pct_budget: float
    mow_due: bool
    days_until_due: Optional[int]
    days_until_due_display: str
    last_cut_in: float
    recommended_cut_in: float
    next_pass_in: float
    cut_note: str
    mowing_allowed: bool
    mowing_allowed_reason: str
    seedling_height_in: Optional[float]
    first_mow_target_in: Optional[float]
    moisture: float
    moisture_source: str
    moisture_sensors_used: tuple
    low_gp_streak: int
    overseed_active: bool
    overseed_status: str
    overseed_target_in: Optional[float]
    overseed_arrival_date: Optional[str]
    overseed_feasible: bool
    overseed_earliest_date: Optional[str]
    seedlings_look_ready: bool = False


def _accrue(s, cfg, tun, inp, mean_f, gp, potential_mm, wf, mf) -> None:
    """Advance history, dormancy streak and missed days by one calendar day.

    A missed (catch-up) day on or before the last mow enters the history but not
    the accumulator: it grew before that mow (a day accrues before its mows), and
    the mow -- applied while this catch-up was pending -- already reset the
    accumulator. Today's growth still accrues, even after a mow dated today."""
    was_dormant = s.low_gp_streak >= tun.dormant_days
    missed = catchup.missed_days(s.last_accrual, inp.today, tun.max_catchup_days)
    for rec in catchup.catchup_records(missed, s.forecast_means, cfg,
                                       s.last_water_factor, s.last_management_factor):
        s.history.append(rec)
        s.low_gp_streak, _ = season.update_dormancy(s.low_gp_streak, rec.gp, tun)
        after_mow = s.last_mow is None or rec.date > s.last_mow
        if inp.in_season and s.seeding_date is None and after_mow:
            s.accumulated_mm += rec.growth_mm
    s.history.append(DayRecord(inp.today, mean_f, gp, potential_mm))
    s.history = s.history[-tun.history_days:]
    s.low_gp_streak, dormant = season.update_dormancy(s.low_gp_streak, gp, tun)
    if was_dormant and not dormant:
        s.green_up_start = inp.today
    s.last_accrual = inp.today
    s.forecast_means = {d.isoformat(): m for d, m in inp.horizon}
    s.last_water_factor, s.last_management_factor = wf, mf


def evaluate_area(cfg, tun, state: AreaState, inp: DayInputs, *, accrue: bool):
    s = state.copy()
    today = inp.today
    mean_f = (inp.high_f + inp.low_f) / 2.0
    gp = growth.growth_potential(mean_f, cfg.opt_temp_f, cfg.temp_spread_f)
    wf = water.water_factor(inp.moisture, cfg.wilting_moisture, cfg.comfortable_moisture)
    mf = management.management_factor(inp.events, today, tun)
    potential_mm = growth.predicted_growth_mm(cfg.max_growth_rate_mm, gp, wf, mf)

    if inp.in_season and s.was_in_season is False:
        s.green_up_start = today                   # the season switch just turned on
    s.was_in_season = inp.in_season
    if accrue:
        _accrue(s, cfg, tun, inp, mean_f, gp, potential_mm, wf, mf)
    dormant = s.low_gp_streak >= tun.dormant_days

    last_cut = s.last_cut_in if s.last_cut_in is not None else cfg.cut_max_in
    budget = last_cut * 25.4 * tun.budget_fraction
    hh = heat.heat_hold(inp.high_f, inp.moisture, cfg.wilting_moisture,
                        cfg.comfortable_moisture, tun, warm=(cfg.curve == "warm"))

    # Seasonal phase -> target height (smoothed, with hysteresis)
    t7 = phases.trailing_mean_temp(s.history, mean_f)
    next7 = [m for _, m in inp.horizon[:7]]
    f7 = sum(next7) / len(next7) if next7 else t7
    phase = phases.detect_phase(cfg, tun, today=today, t7=t7, f7=f7,
                                green_up_start=s.green_up_start, heat_hold_today=hh)
    in_range = s.target_in is not None and cfg.cut_min_in <= s.target_in <= cfg.cut_max_in
    s.target_in, s.target_changed_on = phases.update_target(
        s.target_in if in_range else None, s.target_changed_on if in_range else None,
        phases.phase_target(cfg, phase), phase, today, tun)
    s.phase = phase
    target = s.target_in

    # Establishment / first mow
    # Only Seedlings ready ends the hold; the model's estimate just says so.
    seedling_in = first_target = None
    look_ready = False
    if s.seeding_date is not None:
        seedling_in = establishment.seedling_height_in(s.history, s.seeding_date,
                                                       tun.germination_days)
        first_target = target
        look_ready = establishment.looks_ready(s, today=today, seedling_in=seedling_in,
                                               first_mow_target_in=first_target, tun=tun)
    seeded = s.seeding_date is not None
    ready = s.seedlings_ready
    mode = modes.resolve_mode(inp.in_season, seeded and not ready, seeded and ready,
                              dormant, hh)

    growth_today = potential_mm
    if mode == "out_of_season":
        growth_today = 0.0
    elif mode in ("establishment", "first_mow_ready"):
        growth_today = 0.0
        s.accumulated_mm = 0.0
    elif accrue:
        s.accumulated_mm += potential_mm

    pct = s.accumulated_mm / budget * 100.0 if budget > 0 else 0.0
    if mode == "first_mow_ready":
        mow_due, dud = True, 0
    elif mode in DUE_MODES:
        means = ([m for _, m in inp.horizon[:tun.forecast_horizon_days]]
                 or [mean_f] * tun.forecast_horizon_days)
        fc = forecast.growth_forecast_mm(means, cfg.max_growth_rate_mm, cfg.opt_temp_f,
                                         cfg.temp_spread_f, wf, mf)
        mow_due = s.accumulated_mm >= budget
        dud = forecast.days_until_due(s.accumulated_mm, budget, fc)
    else:
        mow_due, dud = False, None

    if mode in ("establishment", "first_mow_ready"):
        rec = nxt = first_target
        note = "first mow: cut at this height once the seedlings are ready"
    elif mode in ("dormant", "out_of_season"):
        rec = nxt = target
        note = "no mowing needed"
    else:
        rec = target
        nxt = phases.next_pass(last_cut, target, tun.budget_fraction,
                               tun.overseed_max_removal_fraction)
        note = _PHASE_NOTES[phase]

    # Overseed-prep overlay (cool-season areas in normal / heat_hold only)
    ov = s.overseed
    seed = ov.seed_date if (mode in DUE_MODES and cfg.overseed_target_in is not None) else None
    op = overseed.plan(
        current_cut_in=last_cut,
        target_in=ov.target_in or cfg.overseed_target_in or target,
        seed_date=seed,
        buffer_days=ov.buffer_days if ov.buffer_days is not None else tun.overseed_buffer_days,
        today=today,
        regrowth_per_day_in=potential_mm / 25.4,
        min_mow_interval_days=tun.overseed_min_mow_interval_days,
        max_removal_fraction=tun.overseed_max_removal_fraction,
        heat_frozen=(mode == "heat_hold"),
    )
    if op.active:
        rec, nxt, note = op.target_in, op.recommended_cut_in, op.status
        if op.next_mow_in_days is not None:
            dud = op.next_mow_in_days if dud is None else min(dud, op.next_mow_in_days)
            mode = "overseed_prep"

    # While seedlings establish, overseed prep can't be active (it only overlays
    # DUE_MODES), so the plain "inactive" status would misleadingly read as if
    # nothing is going on. Report the establishment stage instead.
    overseed_status = op.status
    if not op.active and s.seeding_date is not None:
        if mode == "establishment":
            overseed_status = "seedlings look ready" if look_ready else "establishing"
        elif mode == "first_mow_ready":
            overseed_status = "first mow ready"

    allowed = mode != "establishment"
    result = AreaResult(
        mode=mode, phase=phase, gp=gp, growth_today_mm=growth_today,
        accumulated_mm=s.accumulated_mm, budget_mm=budget, pct_budget=pct,
        mow_due=mow_due, days_until_due=dud,
        days_until_due_display=forecast.days_until_due_label(dud, tun.forecast_horizon_days),
        last_cut_in=last_cut, recommended_cut_in=round(rec, 2), next_pass_in=round(nxt, 2),
        cut_note=note, mowing_allowed=allowed,
        mowing_allowed_reason="" if allowed else "establishing seedlings",
        seedling_height_in=seedling_in, first_mow_target_in=first_target,
        moisture=inp.moisture, moisture_source=inp.moisture_source,
        moisture_sensors_used=tuple(inp.moisture_sensors_used),
        low_gp_streak=s.low_gp_streak, overseed_active=op.active,
        overseed_status=overseed_status,
        overseed_target_in=op.target_in if op.active else None,
        overseed_arrival_date=op.arrival_date.isoformat() if op.arrival_date else None,
        overseed_feasible=op.feasible,
        overseed_earliest_date=(op.earliest_seed_date.isoformat()
                                if op.earliest_seed_date else None),
        seedlings_look_ready=look_ready,
    )
    return result, s
