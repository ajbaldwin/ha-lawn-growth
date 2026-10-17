from datetime import date, datetime, timedelta, timezone

import pytest

from custom_components.lawn_growth.model import soiltemp as st

TZ = timezone(timedelta(hours=-4))


def _t(day, hour=0, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


DAY = (_t(10), _t(11))


# --- reading_usable ---------------------------------------------------------

@pytest.mark.parametrize("quality,ok", [
    ("good", True), ("Good", True), (" good ", True), ("poor", False), ("bad", False),
    ("training", False), ("unknown", False), ("unavailable", False), (None, False),
    ("", False)])
def test_reading_usable_quality(quality, ok):
    assert st.reading_usable(55.0, quality, "ok") is ok


@pytest.mark.parametrize("health,ok", [
    ("ok", True), ("calibrating", False), ("max_moisture_required", True),
    ("wick_renewal_needed", True), ("hardware_check", True), ("error", False),
    ("unknown", False), ("unavailable", False), (None, False), ("", False), ("OK", True)])
def test_reading_usable_health(health, ok):
    assert st.reading_usable(55.0, "good", health) is ok


def test_reading_usable_temp():
    assert st.reading_usable(None, "good", "ok") is False
    assert st.reading_usable(float("nan"), "good", "ok") is False
    assert st.reading_usable(50, "good", "ok") is True


# --- probe_day_mean ---------------------------------------------------------

def _good(at):
    return [(at, "good")], [(at, "ok")]


def test_steady_good_day_full_coverage():
    q, h = _good(_t(9, 12))
    assert st.probe_day_mean([(_t(9, 12), 55.0)], q, h, *DAY) == (55.0, 1.0)


def test_time_weighted_mean():
    q, h = _good(_t(10))
    temp = [(_t(10), 50.0), (_t(10, 18), 60.0)]
    mean, cov = st.probe_day_mean(temp, q, h, *DAY)
    assert mean == pytest.approx(52.5) and cov == 1.0


def test_quality_training_mid_day_reduces_coverage():
    temp = [(_t(10), 50.0), (_t(10, 18), 60.0)]
    q = [(_t(10), "good"), (_t(10, 12), "training")]
    mean, cov = st.probe_day_mean(temp, q, [(_t(10), "ok")], *DAY)
    assert mean == pytest.approx(50.0) and cov == pytest.approx(0.5)


def test_unavailable_gap():
    temp = [(_t(10), 50.0), (_t(10, 6), None), (_t(10, 12), 60.0)]
    q, h = _good(_t(10))
    mean, cov = st.probe_day_mean(temp, q, h, *DAY)
    assert cov == pytest.approx(0.75)
    assert mean == pytest.approx((50 * 6 + 60 * 12) / 18)


def test_unknown_before_first_item():
    q, h = _good(_t(9))
    mean, cov = st.probe_day_mean([(_t(10, 6), 54.0)], q, h, *DAY)
    assert (mean, cov) == (54.0, pytest.approx(0.75))
    q2 = [(_t(10, 12), "good")]
    mean, cov = st.probe_day_mean([(_t(9), 54.0)], q2, [(_t(9), "ok")], *DAY)
    assert (mean, cov) == (54.0, pytest.approx(0.5))


def test_items_before_start_are_clipped():
    temp = [(_t(8), 40.0), (_t(9, 12), 70.0), (_t(10, 12), 50.0)]
    q, h = _good(_t(1))
    mean, cov = st.probe_day_mean(temp, q, h, *DAY)
    assert mean == pytest.approx(60.0) and cov == 1.0


def test_change_exactly_at_end_ignored():
    temp = [(_t(10), 50.0), (_t(11), 90.0)]
    q = [(_t(10), "good"), (_t(11), "bad")]
    assert st.probe_day_mean(temp, q, [(_t(10), "ok")], *DAY) == (50.0, 1.0)


def test_no_data_or_empty_window():
    assert st.probe_day_mean([], [], [], *DAY) == (None, 0.0)
    q, h = _good(_t(9))
    assert st.probe_day_mean([(_t(9), 50.0)], q, h, _t(10), _t(10)) == (None, 0.0)


# --- probe replay after install ---------------------------------------------

def _installed_probe():
    temp = [(_t(7, 20), 58.1), (_t(8, 6), 54.0), (_t(8, 15), 61.0), (_t(9, 6), 53.5),
            (_t(9, 15), 60.2), (_t(9, 18), 57.0), (_t(10, 6), 52.0), (_t(10, 15), 59.0)]
    quality = [(_t(7, 20), "training"), (_t(9, 8, 28), "training"),
               (_t(9, 17, 28), "good")]
    health = [(_t(7, 20), "calibrating"), (_t(9, 8, 28), "calibrating"),
              (_t(9, 15, 28), "max_moisture_required"), (_t(9, 17, 28), "ok")]
    return temp, quality, health


def test_installed_probe_replay():
    temp, q, h = _installed_probe()
    assert st.probe_day_mean(temp, q, h, _t(8), _t(9)) == (None, 0.0)

    mean9, cov9 = st.probe_day_mean(temp, q, h, _t(9), _t(10))
    assert 0 < cov9 < 0.75
    assert cov9 == pytest.approx((6 * 60 + 32) / (24 * 60))
    assert mean9 == pytest.approx((60.2 * 32 + 57.0 * 360) / 392)
    assert st.area_day([(mean9, cov9)], 0.75) == (None, cov9)

    mean10, cov10 = st.probe_day_mean(temp, q, h, _t(10), _t(11))
    assert cov10 == 1.0
    assert mean10 == pytest.approx((57.0 * 6 + 52.0 * 9 + 59.0 * 9) / 24)
    assert st.area_day([(mean10, cov10)], 0.75) == (pytest.approx(mean10), 1.0)


# --- area_day ---------------------------------------------------------------

def test_area_day_mixes():
    assert st.area_day([(50.0, 1.0), (54.0, 0.8)], 0.75) == (52.0, 1.0)
    assert st.area_day([(50.0, 1.0), (70.0, 0.5)], 0.75) == (50.0, 1.0)
    assert st.area_day([(50.0, 0.75), (None, 0.0)], 0.75) == (50.0, 0.75)
    assert st.area_day([(50.0, 0.6), (None, 0.0)], 0.75) == (None, 0.6)


def test_area_day_empty():
    assert st.area_day([], 0.75) == (None, 0.0)


# --- soil5 / source ---------------------------------------------------------

TODAY = date(2026, 10, 17)


def _days(vals):
    """vals[0] is yesterday, vals[1] two days ago, ..."""
    return {TODAY - timedelta(days=i + 1): v for i, v in enumerate(vals)}


def test_soil5_five_valid():
    assert st.soil5(_days([50, 52, 54, 56, 58]), TODAY) == (54.0, 5)


def test_soil5_exactly_three_valid():
    assert st.soil5(_days([50, None, 53, None, 56]), TODAY) == (53.0, 3)


def test_soil5_two_valid_is_none():
    assert st.soil5(_days([50, None, None, 52, None]), TODAY) == (None, 2)


def test_soil5_ignores_today_and_older_days():
    days = _days([50, 50, 50, None, None, 90, 90])
    days[TODAY] = 90
    assert st.soil5(days, TODAY) == (50.0, 3)
    assert st.soil5(days, TODAY, window=7, min_valid=3) == (pytest.approx(66.0), 5)


def test_source_for():
    assert st.source_for(51.0) == "geodrops"
    assert st.source_for(0.0) == "geodrops"
    assert st.source_for(None) == "gdd"


# --- store helpers ----------------------------------------------------------

def test_prune_days_and_days_by_date():
    store = {(TODAY - timedelta(days=i)).isoformat(): {"mean_f": 50.0 + i, "coverage": 1.0}
             for i in range(0, 10)}
    store["2026-10-12"] = {"mean_f": None, "coverage": 0.2}
    pruned = st.prune_days(store, TODAY, 7)
    assert sorted(pruned) == [(TODAY - timedelta(days=i)).isoformat() for i in range(7, 0, -1)]
    assert pruned is not store
    pruned["2026-10-16"]["mean_f"] = 0
    assert store["2026-10-16"]["mean_f"] == 51.0
    by = st.days_by_date(st.prune_days(store, TODAY, 7))
    assert by[date(2026, 10, 16)] == 51.0 and by[date(2026, 10, 12)] is None
    assert st.soil5(by, TODAY) == (pytest.approx((51 + 52 + 53 + 54) / 4), 4)
