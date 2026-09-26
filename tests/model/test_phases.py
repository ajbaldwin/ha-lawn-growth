from dataclasses import replace
from datetime import date, timedelta

import pytest

from custom_components.lawn_growth.model import config, phases
from custom_components.lawn_growth.model.state import DayRecord

T = config.Tunables()
COOL = config.AreaConfig(key="a", name="A", grass="tttf_kbg", curve="cool",
                         opt_temp_f=68.0, temp_spread_f=10.0, cut_min_in=3.0,
                         cut_max_in=4.0, overseed_target_in=2.5)
WARM = replace(COOL, grass="bermuda_zoysia", curve="warm", opt_temp_f=88.0,
               temp_spread_f=12.0, cut_min_in=1.0, cut_max_in=2.0, overseed_target_in=None)
TODAY = date(2026, 10, 1)


def _detect(cfg=COOL, *, t7, f7=None, green_up_start=None, hh=False):
    return phases.detect_phase(cfg, T, today=TODAY, t7=t7, f7=t7 if f7 is None else f7,
                               green_up_start=green_up_start, heat_hold_today=hh)


def test_trailing_mean_temp():
    hist = [DayRecord(TODAY - timedelta(days=i), float(50 + i), 0.5, 1.0) for i in range(10)]
    hist.reverse()
    # last 7 records are days 6..0 -> 56..50 -> mean 53
    assert phases.trailing_mean_temp(hist, 99.0) == pytest.approx(53.0)
    assert phases.trailing_mean_temp([], 61.0) == 61.0


def test_cool_phases():
    assert _detect(t7=68) == "active"
    assert _detect(t7=80) == "stress"                       # opt + 12
    assert _detect(t7=70, hh=True) == "stress"
    assert _detect(t7=54, f7=50) == "wind_down"             # below 55 and cooling
    assert _detect(t7=54, f7=58) == "active"                # spring warm-up, not wind-down
    assert _detect(t7=68, green_up_start=TODAY - timedelta(days=13)) == "green_up"
    assert _detect(t7=68, green_up_start=TODAY - timedelta(days=14)) == "active"


def test_warm_phases():
    assert _detect(WARM, t7=85) == "active"
    assert _detect(WARM, t7=85, hh=True) == "stress"
    assert _detect(WARM, t7=65, f7=60) == "wind_down"
    assert _detect(WARM, t7=65, f7=70) == "active"


def test_phase_targets():
    assert [phases.phase_target(COOL, p) for p in phases.PHASES] == [3.25, 3.5, 4.0, 3.0]
    assert [phases.phase_target(WARM, p) for p in phases.PHASES] == [1.0, 1.25, 1.5, 2.0]


def test_update_target_first_time_takes_new():
    assert phases.update_target(None, None, 3.5, "active", TODAY, T) == (3.5, TODAY)


def test_update_target_ignores_small_changes():
    prev = TODAY - timedelta(days=30)
    assert phases.update_target(3.5, prev, 3.3, "active", TODAY, T) == (3.5, prev)


def test_update_target_holds_for_seven_days():
    recent = TODAY - timedelta(days=6)
    assert phases.update_target(3.5, recent, 3.0, "wind_down", TODAY, T) == (3.5, recent)
    older = TODAY - timedelta(days=7)
    assert phases.update_target(3.5, older, 3.0, "wind_down", TODAY, T) == (3.0, TODAY)


def test_stress_raise_is_immediate():
    recent = TODAY - timedelta(days=1)
    assert phases.update_target(3.5, recent, 4.0, "stress", TODAY, T) == (4.0, TODAY)


def test_next_pass_raises_immediately():
    assert phases.next_pass(3.0, 3.5, 1 / 3, 1 / 3) == 3.5


def test_next_pass_lowers_by_one_third_of_standing():
    # standing at mow time = 3.9 * 4/3 = 5.2; 2/3 of that = 3.4667
    assert phases.next_pass(3.9, 3.0, 1 / 3, 1 / 3) == pytest.approx(3.47)


def test_next_pass_clamps_to_target():
    assert phases.next_pass(3.2, 3.0, 1 / 3, 1 / 3) == 3.0
