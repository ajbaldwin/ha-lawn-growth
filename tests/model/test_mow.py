from datetime import date

import pytest

from custom_components.lawn_growth.model import mow
from custom_components.lawn_growth.model.state import AreaState, MowRecord


def _rec(d, h=3.0, src="manual"):
    return MowRecord(d, h, src)


def test_mow_resets_accumulator_and_sets_last_cut():
    s = AreaState(accumulated_mm=40.0, due_notified=True)
    out = mow.apply_mow(s, _rec(date(2026, 9, 26), 3.2, "mower_session"))
    assert out.accumulated_mm == 0.0
    assert out.last_mow == date(2026, 9, 26)
    assert out.last_cut_in == 3.2
    assert out.due_notified is False
    assert s.accumulated_mm == 40.0          # input not mutated


def test_backdated_older_mow_is_history_only():
    s = mow.apply_mow(AreaState(), _rec(date(2026, 9, 20), 3.0))
    s.accumulated_mm = 12.0
    out = mow.apply_mow(s, _rec(date(2026, 9, 10), 3.5))
    assert out.accumulated_mm == 12.0
    assert out.last_mow == date(2026, 9, 20)
    assert out.last_cut_in == 3.0
    assert [r.date for r in out.mow_records] == [date(2026, 9, 10), date(2026, 9, 20)]


def test_same_day_second_mow_counts():
    s = mow.apply_mow(AreaState(), _rec(date(2026, 9, 20), 3.0))
    out = mow.apply_mow(s, _rec(date(2026, 9, 20), 2.8))
    assert out.last_cut_in == 2.8


def test_mow_after_seeding_ends_establishment():
    s = AreaState(seeding_date=date(2026, 9, 20), seedlings_ready=True, ready_notified=True)
    out = mow.apply_mow(s, _rec(date(2026, 10, 20), 3.0))
    assert (out.seeding_date, out.seedlings_ready, out.ready_notified) == (None, False, False)


def test_mow_on_seeding_date_keeps_establishment():
    s = AreaState(seeding_date=date(2026, 9, 20))
    out = mow.apply_mow(s, _rec(date(2026, 9, 20), 3.0))
    assert out.seeding_date == date(2026, 9, 20)


def test_records_capped():
    s = AreaState()
    for day in range(1, 26):
        s = mow.apply_mow(s, _rec(date(2026, 8, day)))
    assert len(s.mow_records) == mow.MAX_RECORDS
    assert s.mow_records[-1].date == date(2026, 8, 25)


def test_correct_last_mow():
    s = mow.apply_mow(AreaState(), _rec(date(2026, 9, 20), 3.0, "mower_session"))
    out = mow.correct_last_mow(s, 3.25)
    assert out.last_cut_in == 3.25 and out.mow_records[-1].source == "manual"
    assert out.mow_records[-1].date == date(2026, 9, 20)


def test_correct_without_records_raises():
    with pytest.raises(ValueError):
        mow.correct_last_mow(AreaState(), 3.0)
