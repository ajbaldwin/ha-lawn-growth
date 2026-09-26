import logging
from datetime import date

import pytest

from custom_components.lawn_growth.model import catchup, config

CFG = config.AreaConfig(key="lawn", name="Lawn", grass="tttf_kbg", curve="cool",
                        opt_temp_f=68.0, temp_spread_f=10.0, cut_min_in=3.0,
                        cut_max_in=4.0, overseed_target_in=2.5)


def test_no_missed_days():
    assert catchup.missed_days(None, date(2026, 9, 26), 10) == []
    assert catchup.missed_days(date(2026, 9, 25), date(2026, 9, 26), 10) == []
    assert catchup.missed_days(date(2026, 9, 26), date(2026, 9, 26), 10) == []


def test_missed_days_between():
    assert catchup.missed_days(date(2026, 9, 23), date(2026, 9, 26), 10) == [
        date(2026, 9, 24), date(2026, 9, 25)]


def test_missed_days_capped_to_most_recent():
    assert catchup.missed_days(date(2026, 9, 1), date(2026, 9, 26), 3) == [
        date(2026, 9, 23), date(2026, 9, 24), date(2026, 9, 25)]


def test_catchup_uses_stored_forecast_and_skips_unknown_days():
    recs = catchup.catchup_records([date(2026, 9, 24), date(2026, 9, 25)],
                                   {"2026-09-25": 68.0}, CFG, 1.0, 1.0)
    assert len(recs) == 1
    r = recs[0]
    assert (r.date, r.mean_f, r.gp) == (date(2026, 9, 25), 68.0, 1.0)
    assert r.growth_mm == pytest.approx(6.5)


def test_skipped_catchup_days_are_logged(caplog):
    caplog.set_level(logging.INFO, logger="custom_components.lawn_growth")
    catchup.catchup_records([date(2026, 9, 23), date(2026, 9, 24), date(2026, 9, 25)],
                            {"2026-09-25": 68.0}, CFG, 1.0, 1.0)
    [rec] = caplog.records
    assert "Lawn" in rec.getMessage() and "2026-09-23, 2026-09-24" in rec.getMessage()
    caplog.clear()
    catchup.catchup_records([date(2026, 9, 25)], {"2026-09-25": 68.0}, CFG, 1.0, 1.0)
    assert caplog.records == []                         # nothing skipped, nothing logged
