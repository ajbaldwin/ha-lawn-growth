from dataclasses import fields
from datetime import date

from custom_components.lawn_growth.model import evaluate, notify
from custom_components.lawn_growth.model.state import AreaState

TODAY = date(2026, 9, 26)


def _result(**over):
    base = {f.name: None for f in fields(evaluate.AreaResult)}
    base.update(mode="normal", phase="active", gp=1.0, growth_today_mm=6.5,
                accumulated_mm=34.0, budget_mm=33.0, pct_budget=103.0, mow_due=True,
                days_until_due=0, days_until_due_display="0", last_cut_in=3.9,
                recommended_cut_in=3.45, next_pass_in=3.45, cut_note="",
                mowing_allowed=True, mowing_allowed_reason="", moisture=70.0,
                moisture_source="sensors", moisture_sensors_used=(), low_gp_streak=0,
                overseed_active=False, overseed_status="inactive", overseed_feasible=True)
    base.update(over)
    return evaluate.AreaResult(**base)


def _decide(result, state=None):
    return notify.decide("Back", result, state or AreaState(), today=TODAY,
                         min_interval_days=3)


def test_mow_due_once_per_episode():
    msgs, s = _decide(_result())
    assert [m.message for m in msgs] == [
        "Back: mow due (103% of the growth budget). Cut at 3.45″."]
    assert s.due_notified is True
    msgs, _ = _decide(_result(), s)
    assert msgs == []


def test_heat_hold_wording():
    msgs, _ = _decide(_result(mode="heat_hold"))
    assert "hold off" in msgs[0].message


def test_no_due_push_during_overseed_prep_or_when_not_due():
    assert _decide(_result(mode="overseed_prep"))[0] == []
    assert _decide(_result(mow_due=False))[0] == []


def test_first_mow_ready_once():
    r = _result(mode="first_mow_ready", first_mow_target_in=3.0)
    msgs, s = _decide(r)
    assert [m.message for m in msgs] == ["Back: first mow ready — cut at 3.00″."]
    assert _decide(r, s)[0] == []


def test_overseed_pass_push_deduped_by_last_mow():
    st = AreaState(last_mow=date(2026, 9, 22))
    r = _result(mode="overseed_prep", mow_due=False, overseed_active=True,
                overseed_status="descending", overseed_target_in=2.5, next_pass_in=3.11)
    msgs, s = _decide(r, st)
    assert [m.message for m in msgs] == ["Back overseed prep: mow now at 3.11″."]
    assert s.overseed.notified == "pass:2026-09-22"
    assert _decide(r, s)[0] == []


def test_overseed_pass_waits_for_min_interval():
    st = AreaState(last_mow=date(2026, 9, 25))
    r = _result(mode="overseed_prep", mow_due=False, overseed_active=True,
                overseed_status="descending", overseed_target_in=2.5, next_pass_in=3.11)
    assert _decide(r, st)[0] == []


def test_overseed_infeasible_and_arrived():
    r = _result(mow_due=False, overseed_active=True, overseed_feasible=False,
                overseed_status="infeasible: cannot reach target by seed date",
                overseed_target_in=2.5, overseed_earliest_date="2026-10-02")
    msgs, s = _decide(r)
    assert "Earliest safe seed date: 2026-10-02" in msgs[0].message
    r2 = _result(mow_due=False, overseed_active=True,
                 overseed_status="target reached; holding until seed date",
                 overseed_target_in=2.5)
    msgs, s = _decide(r2, s)
    assert msgs[0].message == "Back overseed: reached 2.50″ — holding until the seed date."
    assert s.overseed.notified == "arrived"
