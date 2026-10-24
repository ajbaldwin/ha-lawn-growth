from dataclasses import replace
from datetime import date, timedelta

import pytest

from custom_components.lawn_growth.model import windows as wm
from custom_components.lawn_growth.model.applications import Application
from custom_components.lawn_growth.model.config import Tunables
from custom_components.lawn_growth.model.windows import AreaSignals, LawnSignals, Window

TUN = Tunables()
SPRING = date(2027, 4, 12)
FALL = date(2026, 10, 25)


def _pre(today=SPRING, gdd=None, areas=None, apps=(), w=None, horizon=()):
    lawn = LawnSignals(today=today, gdd=gdd, horizon=tuple(horizon))
    areas = areas if areas is not None else [AreaSignals("front"), AreaSignals("back")]
    return wm.update_pre_emergent(w or Window("pre_emergent", today.year), lawn, areas,
                                  list(apps), TUN)


def _herb(product, on, areas=("front", "back")):
    return Application("herbicide", on, tuple(areas), product)


def test_window_round_trip():
    w = Window("winterizer", 2026, "back", status="open", projected=date(2026, 11, 1),
               reached={"open": {"date": "2026-10-30", "source": "air", "value": None,
                                 "area": "back"}},
               notified=["open"], last_due=date(2026, 10, 1), cold_since=date(2026, 11, 2),
               wind_down_seen=True)
    assert Window.from_dict(w.to_dict()) == w
    assert w.key == "winterizer:2026:back"
    assert w.reached_on("open") == date(2026, 10, 30)


def test_pre_emergent_season_rolls_over_on_jul_1():
    assert wm.current_season("pre_emergent", date(2027, 6, 30), TUN) == 2027
    assert wm.current_season("pre_emergent", date(2027, 7, 1), TUN) == 2028
    assert wm.current_season("winterizer", date(2027, 12, 31), TUN) == 2027


# --- pre-emergent ------------------------------------------------------------------

def test_pre_emergent_tentative_without_signal():
    w = _pre(gdd=None)
    assert (w.status, w.reached, w.source) == ("tentative", {}, "")


@pytest.mark.parametrize("gdd,stages", [
    (74.0, []), (75.0, ["heads_up"]), (125.0, ["heads_up", "open"]),
    (175.0, ["heads_up", "open", "late"]),
    (200.0, ["heads_up", "open", "late", "germination"])])
def test_pre_emergent_gdd_thresholds(gdd, stages):
    w = _pre(gdd=gdd)
    assert [s for s in wm.PRE_STAGES if s in w.reached] == stages
    assert w.status == ("open" if "open" in stages else "tentative")
    if stages:
        assert w.reached[stages[-1]] == {"date": SPRING.isoformat(), "source": "gdd",
                                         "value": gdd, "area": ""}


@pytest.mark.parametrize("soil,prev,stage", [
    (46.9, 46.0, None), (47.2, 46.8, "heads_up"), (47.2, 47.5, None),
    (47.2, None, "heads_up"), (50.0, 51.0, "open"), (53.0, 52.0, "late"),
    (55.0, 54.0, "germination")])
def test_pre_emergent_soil_thresholds(soil, prev, stage):
    """Heads-up needs the soil rising; the later stages don't."""
    w = _pre(areas=[AreaSignals("front", soil5=soil, soil5_prev=prev)])
    got = [s for s in wm.PRE_STAGES if s in w.reached]
    assert (got[-1] if got else None) == stage
    if stage:
        assert w.reached[stage]["source"] == "geodrops"


def test_warmest_area_drives_the_lawn_window():
    w = _pre(areas=[AreaSignals("front", soil5=48.0), AreaSignals("back", soil5=50.4)])
    assert (w.status, w.set_by, w.source, w.value) == ("open", "back", "geodrops", 50.4)
    assert w.reached["open"]["area"] == "back"


def test_all_areas_on_probes_ignores_gdd():
    w = _pre(gdd=180.0, areas=[AreaSignals("front", soil5=45.0)])
    assert w.status == "tentative" and w.reached == {}


def test_mixed_probes_earlier_trigger_wins():
    areas = [AreaSignals("front", soil5=45.0), AreaSignals("back")]
    w = _pre(gdd=130.0, areas=areas)
    assert (w.status, w.source) == ("open", "gdd")
    areas = [AreaSignals("front", soil5=50.5), AreaSignals("back")]
    w = _pre(gdd=80.0, areas=areas)
    assert (w.status, w.source, w.set_by) == ("open", "geodrops", "front")


def test_open_window_survives_a_source_switch_without_repeating():
    w = _pre(gdd=130.0)
    probes_in = [AreaSignals("front", soil5=46.0), AreaSignals("back", soil5=45.0)]
    later = _pre(today=SPRING + timedelta(days=1), areas=probes_in, gdd=135.0, w=w)
    assert later.status == "open"
    assert later.reached == w.reached                   # nothing re-latched
    assert later.source == "geodrops"                   # the current signal moved on


def test_projected_from_the_gdd_forecast():
    w = _pre(gdd=110.0, horizon=[60.0] * 10)            # 10 GDD a day
    assert (w.status, w.projected) == ("projected", SPRING + timedelta(days=2))
    w = _pre(gdd=10.0, horizon=[55.0] * 10)             # 50 GDD in 10 days: not enough
    assert (w.status, w.projected) == ("tentative", None)


def test_projected_from_the_soil_trend():
    area = AreaSignals("front", soil5=48.0, soil5_prev=47.5, soil_slope=0.5)
    w = _pre(areas=[area])
    assert (w.status, w.projected) == ("projected", SPRING + timedelta(days=4))
    flat = replace(area, soil_slope=-0.1)
    assert _pre(areas=[flat]).status == "tentative"


def test_germination_sets_the_close_then_missed():
    w = _pre(gdd=205.0)
    assert w.expected_close == SPRING + timedelta(days=14)
    w = _pre(today=SPRING + timedelta(days=13), gdd=230.0, w=w)
    assert w.status == "open"
    w = _pre(today=SPRING + timedelta(days=14), gdd=240.0, w=w)
    assert (w.status, w.closed) == ("missed", SPRING + timedelta(days=14))
    assert w.reached_on("missed") == SPRING + timedelta(days=14)


def test_open_expected_close_projected_from_gdd_rate():
    w = _pre(gdd=130.0, horizon=[55.0] * 10)            # 5 GDD a day: 70 to go = 14 days
    assert w.expected_close == SPRING + timedelta(days=14 + 14)
    w = _pre(gdd=130.0)                                 # no forecast: fixed estimate
    assert w.expected_close == SPRING + timedelta(days=TUN.pre_open_estimate_days)


def test_logging_a_pre_emergent_makes_it_done():
    w = _pre(gdd=130.0, apps=[_herb("prodiamine", date(2027, 4, 8))])
    assert (w.status, w.done, w.product) == ("done", date(2027, 4, 8), "prodiamine")
    assert "open" in w.reached                          # stages still tracked


def test_mesotrione_and_last_years_logs_dont_count():
    apps = [_herb("mesotrione", date(2027, 4, 8), ("back",)),
            _herb("prodiamine", date(2026, 10, 1))]
    assert _pre(gdd=130.0, apps=apps).status == "open"


def test_a_late_log_turns_missed_into_done():
    w = Window("pre_emergent", 2027, status="missed", closed=date(2027, 5, 20))
    w = _pre(today=date(2027, 5, 25), w=w, apps=[_herb("dithiopyr", date(2027, 5, 24))])
    assert w.status == "done"


def test_skip_holds_until_something_is_logged():
    w = wm.skip(_pre(gdd=130.0), SPRING)
    assert (w.status, w.skipped) == ("skipped", SPRING)
    assert _pre(today=SPRING + timedelta(days=1), gdd=140.0, w=w).status == "skipped"
    w = _pre(today=SPRING + timedelta(days=2), w=w,
             apps=[_herb("prodiamine", SPRING + timedelta(days=2))])
    assert w.status == "done"
    assert wm.skip(w, SPRING).status == "done"          # a logged one isn't skipped


def test_split_reminder():
    first = _herb("prodiamine", date(2027, 4, 1))
    w = _pre(apps=[first])
    assert wm.split_reminder_date(w, [first], TUN) == date(2027, 5, 20)
    second = _herb("dithiopyr", date(2027, 5, 18))
    assert wm.split_reminder_date(w, [first, second], TUN) is None
    assert wm.split_reminder_date(w, [first], replace(TUN, split_reminder=False)) is None


def test_suggested_product():
    assert wm.suggested_pre_product(None) == "prodiamine"
    assert wm.suggested_pre_product(_pre(gdd=130.0)) == "prodiamine"
    assert wm.suggested_pre_product(_pre(gdd=201.0)) == "dithiopyr"
    assert wm.suggested_pre_product(_pre(apps=[_herb("prodiamine", SPRING)])) == "dithiopyr"
    # every area inside prodiamine's new-turf wait
    assert wm.suggested_pre_product(None, new_turf_everywhere=True) == "dithiopyr"
    assert wm.suggested_pre_product(_pre(gdd=130.0), new_turf_everywhere=True) == "dithiopyr"


def test_out_of_season_pre_emergent_is_not_evaluated():
    """Fall soil passes through 47-55 °F on the way down; that's not spring."""
    w = _pre(today=date(2026, 9, 20), w=Window("pre_emergent", 2027),
             areas=[AreaSignals("front", soil5=55.0)], gdd=1500.0)
    assert (w.status, w.reached) == ("tentative", {})


# --- update_all ---------------------------------------------------------------------

def test_update_all_creates_closes_and_prunes():
    old = Window("pre_emergent", 2027, status="open",
                 reached={"open": {"date": "2027-05-01"}})
    gone = Window("winterizer", 2027, "removed")
    ancient = Window("winterizer", 2025, "front", status="done")
    today = date(2027, 7, 1)
    out = wm.update_all({w.key: w for w in (old, gone, ancient)},
                        LawnSignals(today=today, gdd=900.0),
                        [AreaSignals("front"), AreaSignals("back", overseed_capable=False)],
                        [], TUN)
    assert set(out) == {"pre_emergent:2027:all", "pre_emergent:2028:all",
                        "winterizer:2027:front", "winterizer:2027:back",
                        "overseed:2027:front"}
    closed = out["pre_emergent:2027:all"]
    assert (closed.status, closed.closed) == ("missed", date(2027, 7, 1))
    assert out["pre_emergent:2028:all"].status == "tentative"


# --- winterizer ---------------------------------------------------------------------

def _wound_down(**over):
    base = dict(key="back", phase="wind_down", last_mow=FALL - timedelta(days=10))
    base.update(over)
    return AreaSignals(**base)


def _wint(a, today=FALL, apps=(), w=None):
    return wm.update_winterizer(w or Window("winterizer", today.year, a.key), today, a, (),
                                list(apps), TUN)


def test_winterizer_opens_when_all_three_hold():
    w = _wint(_wound_down())
    assert w.status == "open" and w.reached_on("open") == FALL
    assert w.source == "air"


@pytest.mark.parametrize("fert,opens_on", [(date(2026, 10, 3), date(2026, 10, 31)),
                                           (date(2026, 9, 21), date(2026, 10, 19))])
def test_winterizer_spacing_example(fert, opens_on):
    """Spec example: fertilized Oct 3 -> spacing met Oct 31; Sep 21 -> Oct 19."""
    apps = [Application("fert", fert, ("back",))]
    a = _wound_down(last_mow=date(2026, 10, 1))
    before = _wint(a, today=opens_on - timedelta(days=1), apps=apps)
    assert before.status != "open"
    assert _wint(a, today=opens_on, apps=apps).status == "open"


def test_winterizer_waits_for_ten_quiet_days_and_wind_down():
    assert _wint(_wound_down(last_mow=FALL - timedelta(days=9))).status != "open"
    assert _wint(_wound_down(phase="active")).status == "tentative"
    assert _wint(_wound_down(last_mow=None)).status == "tentative"


def test_winterizer_a_due_mow_since_the_last_mow_blocks_it():
    w = _wint(_wound_down(mow_due=True), today=FALL - timedelta(days=1))
    assert w.last_due == FALL - timedelta(days=1)
    assert _wint(_wound_down(), w=w).status != "open"


def test_winterizer_still_green_check():
    assert _wint(_wound_down(soil5=39.0)).status == "tentative"
    assert _wint(_wound_down(soil5=41.0)).status == "open"


def test_winterizer_projected_from_the_dates():
    a = _wound_down(last_mow=FALL - timedelta(days=6))
    w = _wint(a)
    assert (w.status, w.projected) == ("projected", FALL + timedelta(days=4))


def test_winterizer_missed_on_dormancy_or_three_cold_days():
    w = _wint(_wound_down())
    assert _wint(_wound_down(dormant=True), today=FALL + timedelta(days=1),
                 w=w).status == "missed"
    for n in range(3):
        w = _wint(_wound_down(soil5=38.0), today=FALL + timedelta(days=n + 1), w=w)
    assert (w.status, w.closed) == ("missed", FALL + timedelta(days=3))


def test_winterizer_summer_dormancy_isnt_a_miss():
    w = _wint(AreaSignals("back", dormant=True), today=date(2026, 8, 15))
    assert w.status == "tentative"


def test_winterizer_not_evaluated_before_august():
    w = _wint(_wound_down(last_mow=date(2026, 7, 1)), today=date(2026, 7, 20))
    assert w.status == "tentative" and w.reached == {}


def test_winterizer_log_makes_it_done():
    apps = [Application("winterizer", FALL, ("back",))]
    w = _wint(_wound_down(), apps=apps)
    assert (w.status, w.done) == ("done", FALL)


# --- fall overseed window ----------------------------------------------------------

def _ov(a, today=date(2026, 8, 20), apps=(), w=None, horizon=()):
    return wm.update_overseed(w or Window("overseed", today.year, a.key), today, a,
                              tuple(horizon), list(apps), TUN)


def test_overseed_opens_below_70_and_closes_below_55():
    w = _ov(AreaSignals("back", soil5=71.0, soil_slope=0.0))
    assert w.status == "tentative"
    w = _ov(AreaSignals("back", soil5=69.5), w=w)
    assert w.status == "open" and w.source == "geodrops"
    w = _ov(AreaSignals("back", soil5=72.0), w=w, today=date(2026, 8, 21))
    assert w.status == "open"                            # stays open
    w = _ov(AreaSignals("back", soil5=54.9), w=w, today=date(2026, 10, 10))
    assert (w.status, w.closed) == ("missed", date(2026, 10, 10))


def test_overseed_air_fallback_needs_t7_falling():
    warm = AreaSignals("back", air_means=(72.0,) * 7)
    assert _ov(warm, horizon=[74.0] * 7).status != "open"
    w = _ov(warm, horizon=[68.0] * 7)
    assert (w.status, w.source) == ("open", "air")
    cold = AreaSignals("back", air_means=(49.0,) * 7)
    assert _ov(cold, w=w, horizon=[48.0] * 7).status == "missed"


def test_overseed_closing_notice_when_close_is_a_week_out():
    a = AreaSignals("back", soil5=58.0, soil_slope=-0.6)  # 55 °F in 5 days
    w = _ov(a, today=date(2026, 9, 25))
    assert w.expected_close == date(2026, 9, 30)
    assert "closing" in w.reached
    a = AreaSignals("back", soil5=65.0, soil_slope=-0.6)
    assert "closing" not in _ov(a, today=date(2026, 9, 25)).reached


def test_overseed_projected_from_falling_soil():
    a = AreaSignals("back", soil5=71.0, soil_slope=-0.5)
    w = _ov(a)
    assert (w.status, w.projected) == ("projected", date(2026, 8, 23))   # 69.5 °F


def test_overseed_seeding_makes_it_done():
    apps = [Application("seeding", date(2026, 9, 5), ("back",))]
    w = _ov(AreaSignals("back", soil5=65.0), today=date(2026, 9, 6), apps=apps)
    assert (w.status, w.done) == ("done", date(2026, 9, 5))
    spring = [Application("seeding", date(2026, 5, 1), ("back",))]
    assert _ov(AreaSignals("back", soil5=65.0), apps=spring).status == "open"


def test_overseed_not_before_august():
    w = _ov(AreaSignals("back", soil5=65.0), today=date(2026, 7, 25))
    assert w.status == "tentative"


# --- projections --------------------------------------------------------------------

def test_projection_helpers():
    assert wm.trend_cross(48.0, 0.5, 50.0, rising=True, limit=10) == 4
    assert wm.trend_cross(48.0, 0.1, 50.0, rising=True, limit=10) is None
    assert wm.trend_cross(48.0, 0.1, 50.0, rising=True, limit=None) == 20
    assert wm.trend_cross(48.0, -0.1, 50.0, rising=True, limit=10) is None
    assert wm.trend_cross(56.0, -0.5, 55.0, rising=False, limit=10) == 2
    assert wm.gdd_cross(120.0, [52.0, 54.0], 50.0, 125.0) == 2
    assert wm.gdd_cross(120.0, [52.0], 50.0, 125.0) is None
    assert wm.gdd_extrapolate(120.0, [55.0, 55.0], 50.0, 200.0) == 16
    assert wm.t7_cross([52.0] * 7, [40.0] * 3, lambda t: t < 50.0) == 2
