from datetime import date

import pytest

from custom_components.lawn_growth.model import overseed


def test_safe_next_cut_caps_removal_at_one_third():
    # standing 4.0, 1/3 rule -> lowest safe cut is 2/3 * 4.0 = 2.667
    assert overseed.safe_next_cut(4.0, 2.5, 1.0 / 3.0) == pytest.approx(4.0 * (2.0 / 3.0))


def test_safe_next_cut_clamps_to_target():
    # 2/3 * 3.0 = 2.0 which is below target 2.5 -> clamp to target
    assert overseed.safe_next_cut(3.0, 2.5, 1.0 / 3.0) == 2.5


def test_passes_needed_zero_when_already_at_target():
    assert overseed.passes_needed(2.5, 2.5, 1.0 / 3.0, 0.1) == 0
    assert overseed.passes_needed(2.0, 2.5, 1.0 / 3.0, 0.1) == 0


def test_passes_needed_counts_ratchet_passes():
    # 3.9 -> ~2.6 -> 2.5 with small regrowth ~= 2 passes
    assert overseed.passes_needed(3.9, 2.5, 1.0 / 3.0, 0.1) == 2


def test_passes_needed_none_when_regrowth_stalls_descent():
    # regrowth huge relative to height: 2/3*(3.0+3.0)=4.0 >= 3.0 -> cannot descend
    assert overseed.passes_needed(3.0, 2.5, 1.0 / 3.0, 3.0) is None


_KW = dict(target_in=2.5, buffer_days=7, regrowth_per_day_in=0.03,
           min_mow_interval_days=3, max_removal_fraction=1.0 / 3.0,
           heat_frozen=False)


def test_plan_inactive_without_seed_date():
    p = overseed.plan(current_cut_in=3.9, seed_date=None,
                      today=date(2026, 8, 22), **_KW)
    assert p.active is False
    assert p.recommended_cut_in == 3.9
    assert p.status == "inactive"


def test_plan_arrived_holds_at_target():
    p = overseed.plan(current_cut_in=2.5, seed_date=date(2026, 9, 5),
                      today=date(2026, 8, 30), **_KW)
    assert p.active is True
    assert p.recommended_cut_in == 2.5
    assert p.next_mow_in_days is None
    assert p.status.startswith("target reached")


def test_plan_scheduled_before_window_opens():
    # seed far out -> window not open yet -> hold, no pulled mow
    p = overseed.plan(current_cut_in=3.9, seed_date=date(2026, 10, 1),
                      today=date(2026, 8, 22), **_KW)
    assert p.active is True
    assert p.next_mow_in_days is None
    assert p.feasible is True
    assert p.status.startswith("scheduled")


def test_plan_descending_when_window_open():
    # arrival = 09-05 - 7 = 08-29; passes=2 -> min_days_needed=3.
    # 08-27: days_to_arrival=2 <= 3 -> window open; days_to_seed=9 >= 3 -> feasible.
    p = overseed.plan(current_cut_in=3.9, seed_date=date(2026, 9, 5),
                      today=date(2026, 8, 27), **_KW)
    assert p.active is True
    assert p.next_mow_in_days == 3
    assert p.feasible is True
    assert p.status == "descending"


def test_plan_infeasible_warns_with_earliest_date():
    # seed tomorrow, can't descend 3.9->2.5 safely by arrival -> infeasible
    p = overseed.plan(current_cut_in=3.9, seed_date=date(2026, 8, 24),
                      today=date(2026, 8, 22), **_KW)
    assert p.feasible is False
    assert p.earliest_seed_date is not None
    assert p.earliest_seed_date > date(2026, 8, 24)


def test_plan_paused_under_heat():
    # Same feasible/window-open day as the descending test, but heat freezes it.
    p = overseed.plan(current_cut_in=3.9, seed_date=date(2026, 9, 5),
                      today=date(2026, 8, 27),
                      **{**_KW, "heat_frozen": True})
    assert p.active is True
    assert p.next_mow_in_days is None
    assert p.status == "paused (heat hold)"


def test_plan_infeasible_when_growth_too_vigorous_to_descend():
    # Regrowth so large each safe cut is >= the current height -> passes_needed
    # returns None -> the "growth too vigorous" infeasible branch.
    p = overseed.plan(current_cut_in=3.9, seed_date=date(2026, 10, 1),
                      today=date(2026, 8, 22),
                      **{**_KW, "regrowth_per_day_in": 1.0})
    assert p.active is True
    assert p.feasible is False
    assert p.earliest_seed_date is None
    assert p.status == "infeasible: growth too vigorous to descend"


def test_plan_descending_recommends_the_safe_next_cut_not_the_frozen_height():
    # The descent recommendation is the deck height to cut to THIS pass: the
    # 1/3-safe cut of the projected standing, not the current (frozen) height.
    # Returning the current height meant "mow now at 3.9" never descended, yet
    # the mow ratchet still credited a full step down -> belief ran ahead of the
    # deck the operator was told to use (the live 3.1"-vs-2.5" mismatch).
    p = overseed.plan(current_cut_in=3.9, seed_date=date(2026, 9, 5),
                      today=date(2026, 8, 29), **_KW)
    assert p.status == "descending"
    regrowth_per_pass = _KW["regrowth_per_day_in"] * _KW["min_mow_interval_days"]
    expected = overseed.safe_next_cut(3.9 + regrowth_per_pass, 2.5, 1.0 / 3.0)
    assert p.recommended_cut_in == pytest.approx(expected)
    assert p.recommended_cut_in < 3.9


def test_descending_recommendation_ratchets_to_target_over_passes():
    # Feeding each pass's recommended cut back as the next standing floor must
    # ratchet down to the target and stop. The old bug returned the current
    # height unchanged, so the descent stalled forever at the start height.
    cut = 3.9
    for _ in range(20):
        p = overseed.plan(current_cut_in=cut, seed_date=date(2026, 9, 5),
                          today=date(2026, 8, 29), **_KW)
        if p.status.startswith("target reached"):
            break
        assert p.recommended_cut_in < cut, "descent stalled: no progress toward target"
        cut = p.recommended_cut_in
    else:
        raise AssertionError("descent never reached the target")
    assert cut == pytest.approx(2.5)
