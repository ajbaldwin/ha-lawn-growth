from datetime import date

import pytest

from custom_components.lawn_growth.model import weather

TODAY = date(2026, 9, 26)


def _ld(value: str) -> date:
    return date.fromisoformat(value[:10])


def _day(d, hi, lo="missing"):
    e = {"datetime": f"{d}T12:00:00+00:00", "temperature": hi}
    if lo != "missing":
        e["templow"] = lo
    return e


def test_to_f():
    assert weather.to_f(20.0, "°C") == pytest.approx(68.0)
    assert weather.to_f(68.0, "°F") == 68.0


def test_from_daily_splits_today_from_horizon():
    # Regression for the day-0 double count: today's entry is NOT in the horizon.
    t = weather.from_daily([_day("2026-09-26", 59, 54), _day("2026-09-27", 62, 54),
                            _day("2026-09-28", 64, 54)], TODAY, "°F", _ld)
    assert (t.today_high_f, t.today_low_f) == (59.0, 54.0)
    assert t.horizon == [(date(2026, 9, 27), 58.0), (date(2026, 9, 28), 59.0)]


def test_from_daily_skips_rows_without_templow_or_garbage():
    t = weather.from_daily([_day("2026-09-26", 59, 54), _day("2026-09-27", 62),
                            {"datetime": "nope"}, _day("2026-09-28", 64, 54)],
                           TODAY, "°F", _ld)
    assert t.horizon == [(date(2026, 9, 28), 59.0)]


def test_from_daily_none_without_today():
    assert weather.from_daily([_day("2026-09-27", 62, 54)], TODAY, "°F", _ld) is None


def test_from_daily_celsius_and_sorting():
    t = weather.from_daily([_day("2026-09-28", 20, 10), _day("2026-09-26", 20, 10),
                            _day("2026-09-27", 20, 10)], TODAY, "°C", _ld)
    assert (t.today_high_f, t.today_low_f) == pytest.approx((68.0, 50.0))
    assert [d for d, _ in t.horizon] == [date(2026, 9, 27), date(2026, 9, 28)]


def test_from_hourly_groups_by_local_date():
    rows = [{"datetime": f"{d}T{h}:00:00+00:00", "temperature": v} for d, h, v in (
        ("2026-09-26", "18", 60), ("2026-09-26", "21", 55),
        ("2026-09-27", "03", 50), ("2026-09-27", "15", 66))]
    t = weather.from_hourly(rows, TODAY, "°F", _ld)
    assert (t.today_high_f, t.today_low_f) == (60.0, 55.0)
    assert t.horizon == [(date(2026, 9, 27), 58.0)]


def test_from_hourly_none_without_today():
    rows = [{"datetime": "2026-09-27T03:00:00+00:00", "temperature": 50}]
    assert weather.from_hourly(rows, TODAY, "°F", _ld) is None
