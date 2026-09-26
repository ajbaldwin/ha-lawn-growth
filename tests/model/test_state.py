from datetime import date

from custom_components.lawn_growth.model.state import (
    AreaState, DayRecord, MowRecord, OverseedState)


def _full():
    return AreaState(
        accumulated_mm=12.5, last_accrual=date(2026, 9, 25), last_mow=date(2026, 9, 20),
        low_gp_streak=2, seeding_date=date(2026, 9, 20), seedlings_ready=True,
        ready_notified=True, due_notified=True,
        mow_records=[MowRecord(date(2026, 9, 20), 3.0, "manual")],
        overseed=OverseedState(date(2026, 10, 5), 2.5, 7, "arrived"),
        forecast_means={"2026-09-26": 56.5}, last_water_factor=0.8,
        last_management_factor=1.2,
        history=[DayRecord(date(2026, 9, 25), 55.0, 0.6, 3.9)],
        target_in=3.45, phase="active", target_changed_on=date(2026, 9, 21),
        green_up_start=date(2026, 3, 30), was_in_season=True, mow_source_last="7.0")


def test_round_trip_every_field():
    s = _full()
    assert AreaState.from_dict(s.to_dict()) == s


def test_to_dict_is_json_safe():
    import json
    json.dumps(_full().to_dict())


def test_from_empty_dict_is_defaults():
    s = AreaState.from_dict({})
    assert s == AreaState()
    assert s.last_cut_in is None


def test_last_cut_in_is_latest_record():
    s = AreaState(mow_records=[MowRecord(date(2026, 9, 1), 3.5, "counter"),
                               MowRecord(date(2026, 9, 20), 3.0, "manual")])
    assert s.last_cut_in == 3.0


def test_copy_is_deep():
    s = _full()
    c = s.copy()
    c.mow_records.append(MowRecord(date(2026, 9, 26), 3.1, "manual"))
    c.overseed.notified = "x"
    assert len(s.mow_records) == 1 and s.overseed.notified == "arrived"
