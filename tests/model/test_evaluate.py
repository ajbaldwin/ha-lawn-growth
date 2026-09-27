from dataclasses import replace
from datetime import date, timedelta

import pytest

from custom_components.lawn_growth.model import config, evaluate, phases
from custom_components.lawn_growth.model.state import (
    AreaState, DayRecord, MowRecord, OverseedState)

T = config.Tunables()
CFG = config.AreaConfig(key="lawn", name="Lawn", grass="tttf_kbg", curve="cool",
                        opt_temp_f=68.0, temp_spread_f=10.0, cut_min_in=3.0,
                        cut_max_in=3.9, overseed_target_in=2.5)
TODAY = date(2026, 8, 9)
BUDGET_39 = 3.9 * 25.4 / 3.0     # 33.02 mm


def inp(**over):
    base = dict(today=TODAY, in_season=True, high_f=68.0, low_f=68.0,
                horizon=[(TODAY + timedelta(days=i), 68.0) for i in range(1, 11)],
                moisture=70.0, moisture_source="sensors", events=[])
    base.update(over)
    return evaluate.DayInputs(**base)


def run(state=None, accrue=True, **over):
    return evaluate.evaluate_area(CFG, T, state or AreaState(), inp(**over), accrue=accrue)


def test_normal_accrues_today_once():
    r, s = run()
    assert r.mode == "normal" and r.gp == 1.0
    assert r.growth_today_mm == pytest.approx(6.5)
    assert s.accumulated_mm == pytest.approx(6.5) and s.last_accrual == TODAY
    assert r.budget_mm == pytest.approx(BUDGET_39)      # no mow yet -> cut range max


def test_accrue_false_does_not_advance():
    r, s = run(AreaState(accumulated_mm=10.0, last_accrual=TODAY), accrue=False)
    assert s.accumulated_mm == 10.0 and r.accumulated_mm == 10.0


def test_state_not_mutated():
    st = AreaState()
    run(st)
    assert st == AreaState()


def test_budget_uses_last_cut_height():
    st = AreaState(mow_records=[MowRecord(date(2026, 8, 1), 3.0, "manual")],
                   last_mow=date(2026, 8, 1))
    r, _ = run(st)
    assert r.budget_mm == pytest.approx(25.4) and r.last_cut_in == 3.0


def test_days_until_due_counts_from_tomorrow():
    # 6.5 accrued today; 33.02 budget; +6.5/day from tomorrow -> day 5 (39.0).
    # Counting today again as day 1 would answer 4.
    r, _ = run()
    assert r.days_until_due == 5 and r.days_until_due_display == "5"


def test_mow_due_when_budget_reached():
    r, _ = run(AreaState(accumulated_mm=33.0))
    assert r.mow_due is True and r.days_until_due == 0


def test_flat_projection_when_no_horizon():
    r, _ = run(horizon=[])
    assert r.days_until_due == 5


def test_out_of_season_freezes():
    r, s = run(AreaState(accumulated_mm=20.0), in_season=False)
    assert r.mode == "out_of_season" and r.growth_today_mm == 0.0
    assert s.accumulated_mm == 20.0 and r.mow_due is False


def test_establishment_blocks_mowing_and_reports_first_mow_target():
    r, s = run(AreaState(seeding_date=date(2026, 8, 1), accumulated_mm=10.0))
    assert r.mode == "establishment"
    assert r.mowing_allowed is False and r.mowing_allowed_reason == "establishing seedlings"
    assert s.accumulated_mm == 0.0 and r.mow_due is False
    assert r.first_mow_target_in == phases.phase_target(CFG, "active") == 3.45
    assert r.recommended_cut_in == 3.45


def test_establishment_reports_overseed_status_establishing():
    # "inactive" would read as if nothing were happening while seedlings grow in.
    r, _ = run(AreaState(seeding_date=date(2026, 8, 1), accumulated_mm=10.0))
    assert r.overseed_status == "establishing"
    assert r.overseed_active is False


def test_seedlings_ready_override_gives_first_mow_ready():
    r, _ = run(AreaState(seeding_date=date(2026, 8, 1), seedlings_ready=True))
    assert r.mode == "first_mow_ready"
    assert r.mow_due is True and r.days_until_due == 0 and r.mowing_allowed is True


def test_first_mow_ready_reports_overseed_status():
    r, _ = run(AreaState(seeding_date=date(2026, 8, 1), seedlings_ready=True))
    assert r.overseed_status == "first mow ready"
    assert r.overseed_active is False


def test_ready_from_seedling_estimate():
    seed = date(2026, 7, 1)
    hist = [DayRecord(seed + timedelta(days=i), 68.0, 1.0, 6.5) for i in range(10, 39)]
    r, _ = run(AreaState(seeding_date=seed, history=hist))
    assert r.mode == "first_mow_ready"
    assert r.seedling_height_in > 1.5 * 3.45


def test_heat_hold_uses_moisture_midpoint():
    r, _ = run(high_f=90.0, low_f=70.0, moisture=50.0)
    assert r.mode == "heat_hold"
    r, _ = run(high_f=90.0, low_f=70.0, moisture=60.0)
    assert r.mode == "normal"


def test_catch_up_accrues_missed_days_from_stored_forecast():
    st = AreaState(last_accrual=date(2026, 8, 6),
                   forecast_means={"2026-08-07": 68.0, "2026-08-08": 68.0})
    r, s = run(st)
    assert s.accumulated_mm == pytest.approx(6.5 * 3)
    assert [h.date for h in s.history] == [date(2026, 8, 7), date(2026, 8, 8), TODAY]


@pytest.mark.parametrize("last_mow, days_accrued", [
    (date(2026, 8, 1), 3),          # mow before the gap: every missed day counts
    (date(2026, 8, 7), 2),          # 08-08 + today
    (date(2026, 8, 8), 1),          # today only
])
def test_catch_up_skips_missed_days_up_to_the_last_mow(last_mow, days_accrued):
    """A mow applied while a catch-up was pending (logged during HA startup, or while
    the forecast was down) already reset the accumulator: the missed days up to its
    date grew before it (a day accrues before that day's mows) and must not land on
    the accumulator after it. They still enter the history."""
    st = AreaState(last_accrual=date(2026, 8, 6), last_mow=last_mow,
                   forecast_means={"2026-08-07": 68.0, "2026-08-08": 68.0})
    r, s = run(st)
    assert s.accumulated_mm == pytest.approx(6.5 * days_accrued)
    assert [h.date for h in s.history] == [date(2026, 8, 7), date(2026, 8, 8), TODAY]


def test_dormant_never_due():
    r, _ = run(AreaState(low_gp_streak=9, accumulated_mm=40.0), high_f=40.0, low_f=40.0)
    assert r.mode == "dormant" and r.mow_due is False and r.days_until_due is None


def test_dormancy_exit_starts_green_up():
    r, s = run(AreaState(low_gp_streak=10))
    assert s.green_up_start == TODAY and r.phase == "green_up"
    assert r.recommended_cut_in == phases.phase_target(CFG, "green_up")


def test_season_switch_on_starts_green_up():
    r, s = run(AreaState(was_in_season=False))
    assert s.green_up_start == TODAY and r.phase == "green_up"


def test_lowering_target_uses_one_third_safe_pass():
    st = AreaState(mow_records=[MowRecord(date(2026, 8, 1), 3.9, "manual")],
                   last_mow=date(2026, 8, 1), target_in=3.0,
                   target_changed_on=date(2026, 7, 1))
    # wind-down: trailing mean 54, forecast cooler
    st.history = [DayRecord(TODAY - timedelta(days=i), 54.0, 0.4, 2.0) for i in range(7, 0, -1)]
    r, _ = run(st, high_f=58.0, low_f=50.0,
               horizon=[(TODAY + timedelta(days=i), 50.0) for i in range(1, 11)])
    assert r.phase == "wind_down"
    assert r.recommended_cut_in == 3.0
    assert r.next_pass_in == pytest.approx(3.47)


def test_overseed_descending_overlay():
    st = AreaState(mow_records=[MowRecord(date(2026, 8, 1), 3.9, "manual")],
                   last_mow=date(2026, 8, 1),
                   overseed=OverseedState(seed_date=date(2026, 8, 20)))
    r, _ = run(st)
    assert r.mode == "overseed_prep" and r.overseed_active is True
    assert r.overseed_status == "descending"
    assert r.next_pass_in < 3.9 and r.days_until_due <= 3
    assert r.overseed_target_in == 2.5


def test_overseed_ignored_for_warm_season():
    warm = replace(CFG, curve="warm", opt_temp_f=88.0, temp_spread_f=12.0,
                   overseed_target_in=None)
    st = AreaState(overseed=OverseedState(seed_date=date(2026, 8, 20)))
    r, _ = evaluate.evaluate_area(warm, T, st, inp(), accrue=True)
    assert r.overseed_active is False


def test_moisture_source_passes_through():
    r, _ = run(moisture_source="fallback", moisture_sensors_used=())
    assert r.moisture_source == "fallback" and r.moisture_sensors_used == ()
