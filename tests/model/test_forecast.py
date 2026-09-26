import math

import pytest

from custom_components.lawn_growth.model import forecast


def test_already_due_is_zero():
    assert forecast.days_until_due(35.0, 33.0, [5, 5, 5]) == 0


def test_counts_days_to_cross_budget():
    # 20 + 5 + 5 + 5 = 35 >= 33 on day 3
    assert forecast.days_until_due(20.0, 33.0, [5, 5, 5, 5]) == 3


def test_none_when_beyond_horizon():
    assert forecast.days_until_due(0.0, 33.0, [1, 1, 1]) is None


def test_crosses_on_first_day():
    assert forecast.days_until_due(30.0, 33.0, [5, 5]) == 1


# --- growth_forecast_mm: per-day growth projection from a daily-mean forecast ---

def test_growth_forecast_one_entry_per_day():
    means = [68.0, 65.0, 60.0, 55.0]
    out = forecast.growth_forecast_mm(means, 6.0, 68.0, 10.0, 1.0, 1.0)
    assert len(out) == len(means)


def test_growth_forecast_empty_means_is_empty():
    assert forecast.growth_forecast_mm([], 6.0, 68.0, 10.0, 1.0, 1.0) == []


def test_growth_forecast_at_optimum_is_full_rate_times_factors():
    # mean == opt -> GP == 1.0 -> growth == max_rate * wf * mf
    out = forecast.growth_forecast_mm([68.0], 6.0, 68.0, 10.0, 0.5, 1.0)
    assert out[0] == pytest.approx(6.0 * 1.0 * 0.5 * 1.0)


def test_growth_forecast_warmer_day_grows_more_than_colder_day():
    # 68 is the optimum; 58 sits one spread away -> less growth.
    out = forecast.growth_forecast_mm([68.0, 58.0], 6.0, 68.0, 10.0, 0.5, 1.0)
    assert out[0] > out[1]
    assert out[1] == pytest.approx(6.0 * math.exp(-0.5) * 0.5 * 1.0)


def test_growth_forecast_zero_water_factor_zeros_growth():
    out = forecast.growth_forecast_mm([68.0, 60.0], 6.0, 68.0, 10.0, 0.0, 1.0)
    assert out == [0.0, 0.0]


# --- days_until_due_label: human-readable presentation of the (Optional) count ---

def test_due_label_numeric_is_plain_string():
    assert forecast.days_until_due_label(5, 10) == "5"
    assert forecast.days_until_due_label(0, 10) == "0"


def test_due_label_at_horizon_is_still_the_number():
    # Reached ON the last horizon day -> a real value, distinct from beyond.
    assert forecast.days_until_due_label(10, 10) == "10"


def test_due_label_none_means_beyond_horizon():
    # None = budget not reached within the horizon -> ">10", not "unknown".
    assert forecast.days_until_due_label(None, 10) == ">10"
