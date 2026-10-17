from datetime import date, timedelta

import pytest

from custom_components.lawn_growth.model import gdd
from custom_components.lawn_growth.model.config import Tunables

TUN = Tunables()
FEB15 = Tunables(gdd_start_month=2, gdd_start_day=15)


def test_state_round_trip():
    s = gdd.GddState(2026, 1234.5, date(2026, 10, 16), "sensor", 2890.0)
    assert gdd.GddState.from_dict(s.to_dict()) == s
    assert gdd.GddState.from_dict({}) == gdd.GddState()
    import json
    json.dumps(s.to_dict())


def test_copy_is_independent():
    s = gdd.GddState(2026, 10.0)
    c = s.copy()
    c.total = 99.0
    assert s.total == 10.0


def test_gdd_day_and_mean_clamp():
    assert gdd.gdd_day(70, 50, 50) == 10.0
    assert gdd.gdd_day(55, 35, 50) == 0.0
    assert gdd.gdd_from_mean(62.5, 50) == 12.5
    assert gdd.gdd_from_mean(40, 50) == 0.0


def test_season_start():
    assert gdd.season_start(2026, TUN) == date(2026, 1, 1)
    assert gdd.season_start(2026, FEB15) == date(2026, 2, 15)


def test_days_to_process_from_none_jan1():
    days = gdd.days_to_process(gdd.GddState(), date(2026, 1, 5), TUN)
    assert days == [date(2026, 1, d) for d in range(1, 6)]


def test_days_to_process_from_none_feb15_after_start():
    days = gdd.days_to_process(gdd.GddState(), date(2026, 2, 17), FEB15)
    assert days == [date(2026, 2, 15), date(2026, 2, 16), date(2026, 2, 17)]


def test_days_to_process_from_none_feb15_before_start_uses_last_year():
    days = gdd.days_to_process(gdd.GddState(), date(2026, 2, 10), FEB15)
    assert days[0] == date(2025, 2, 15) and days[-1] == date(2026, 2, 10)
    assert len(days) == (date(2026, 2, 10) - date(2025, 2, 15)).days + 1


def test_days_to_process_capped_to_most_recent():
    tun = Tunables(gdd_max_backfill_days=10)
    days = gdd.days_to_process(gdd.GddState(), date(2026, 10, 16), tun)
    assert days == [date(2026, 10, 7) + timedelta(days=i) for i in range(10)]
    full = gdd.days_to_process(gdd.GddState(), date(2026, 10, 16), TUN)
    assert full[0] == date(2026, 1, 1) and len(full) == 289


def test_days_to_process_after_last_day():
    s = gdd.GddState(2026, 5.0, date(2026, 10, 14))
    assert gdd.days_to_process(s, date(2026, 10, 16), TUN) == [
        date(2026, 10, 15), date(2026, 10, 16)]
    assert gdd.days_to_process(s, date(2026, 10, 14), TUN) == []


def test_accrue_adds_and_does_not_mutate():
    s = gdd.GddState(2026, 100.0, date(2026, 10, 15), "forecast")
    n = gdd.accrue(s, date(2026, 10, 16), 7.5, "sensor", TUN)
    assert (n.total, n.last_day, n.source, n.year) == (107.5, date(2026, 10, 16), "sensor", 2026)
    assert s.total == 100.0 and s.last_day == date(2026, 10, 15)


def test_accrue_ignores_duplicate_and_older_day():
    s = gdd.GddState(2026, 100.0, date(2026, 10, 15), "sensor")
    assert gdd.accrue(s, date(2026, 10, 15), 5.0, "sensor", TUN) == s
    assert gdd.accrue(s, date(2026, 10, 1), 5.0, "sensor", TUN) == s


def test_accrue_none_value_advances_last_day_only():
    s = gdd.GddState(2026, 100.0, date(2026, 10, 15), "sensor")
    n = gdd.accrue(s, date(2026, 10, 16), None, "forecast", TUN)
    assert (n.total, n.last_day, n.source) == (100.0, date(2026, 10, 16), "sensor")


def test_accrue_pre_season_day_feb15_start():
    s = gdd.GddState(2025, 2500.0, date(2026, 1, 9), "sensor")
    n = gdd.accrue(s, date(2026, 1, 10), 3.0, "sensor", FEB15)
    assert (n.year, n.total, n.last_day, n.last_season_total) == (
        2025, 2500.0, date(2026, 1, 10), None)
    n = gdd.accrue(n, date(2026, 2, 15), 2.0, "sensor", FEB15)
    assert (n.year, n.total, n.last_season_total) == (2026, 2.0, 2500.0)


def test_accrue_year_rollover():
    s = gdd.GddState(2025, 2890.0, date(2025, 12, 31), "sensor", 2700.0)
    n = gdd.accrue(s, date(2026, 1, 1), 0.0, "sensor", TUN)
    assert (n.year, n.total, n.last_season_total, n.last_day) == (
        2026, 0.0, 2890.0, date(2026, 1, 1))


def test_accrue_first_season_keeps_no_last_total():
    n = gdd.accrue(gdd.GddState(), date(2026, 1, 1), 1.5, "forecast", TUN)
    assert (n.year, n.total, n.last_season_total, n.source) == (2026, 1.5, None, "forecast")


def test_accrues_through_winter():
    s = gdd.GddState()
    for day in gdd.days_to_process(s, date(2026, 12, 31), TUN):
        s = gdd.accrue(s, day, 1.0, "sensor", TUN)
    assert s.total == pytest.approx(365.0) and s.last_day == date(2026, 12, 31)
