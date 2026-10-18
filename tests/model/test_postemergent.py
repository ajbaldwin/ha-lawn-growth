from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from custom_components.lawn_growth.model import postemergent as pm
from custom_components.lawn_growth.model.applications import Application
from custom_components.lawn_growth.model.config import Tunables
from custom_components.lawn_growth.model.weather import DayDetail, ForecastDetail, HourDetail
from custom_components.lawn_growth.model.windows import (
    AreaSignals, LawnSignals, Window, window_key)

TUN = Tunables()
MAY = date(2027, 5, 3)
OCT = date(2026, 10, 1)


def _post(product, on, areas=("front",)):
    return Application("herbicide", on, tuple(areas), product)


def _run(today, areas=None, windows=None, apps=(), gdd=None, horizon=(), highs=()):
    lawn = LawnSignals(today=today, gdd=gdd, horizon=tuple(horizon), highs=tuple(highs))
    areas = areas if areas is not None else [AreaSignals("front")]
    return pm.update_all(dict(windows or {}), lawn, areas, list(apps), TUN)


def _w(windows, kind, area="front", season=None):
    return windows.get(window_key(kind, season or next(iter(windows.values())).season,
                                  area))


# --- spring broadleaf ---------------------------------------------------------------

def test_spring_opens_at_55_soil_and_stays_open_through_a_spray():
    ws = _run(MAY, [AreaSignals("front", soil5=54.0, soil_slope=0.5)])
    w = _w(ws, pm.SPRING)
    assert (w.status, w.projected) == ("projected", MAY + timedelta(days=2))
    ws = _run(MAY, [AreaSignals("front", soil5=55.2)], ws)
    w = _w(ws, pm.SPRING)
    assert w.status == "open" and w.reached["open"]["source"] == "geodrops"
    assert w.expected_close == date(2027, 6, 30)
    later = MAY + timedelta(days=5)
    ws = _run(later, [AreaSignals("front", soil5=58.0)], ws,
              apps=[_post("mesotrione", later)])
    w = _w(ws, pm.SPRING)
    assert (w.status, w.done, w.product) == ("open", later, "mesotrione")
    ws = _run(date(2027, 7, 1), [AreaSignals("front", soil5=70.0)], ws,
              apps=[_post("mesotrione", later)])
    w = _w(ws, pm.SPRING, season=2027)
    assert (w.status, w.closed) == ("done", date(2027, 7, 1))


def test_spring_gdd_fallback_and_the_closed_status_without_a_spray():
    ws = _run(MAY, gdd=240.0, horizon=[60.0] * 10)
    w = _w(ws, pm.SPRING)
    assert (w.status, w.source, w.projected) == ("projected", "gdd", MAY + timedelta(days=1))
    ws = _run(MAY, gdd=251.0, windows=ws)
    assert _w(ws, pm.SPRING).status == "open"
    ws = _run(date(2027, 7, 1), gdd=900.0, windows=ws)
    assert _w(ws, pm.SPRING, season=2027).status == "closed"


def test_spring_heat_close_and_its_projection():
    assert pm.heat_close_in([86, 70, 87, 88, 60], TUN) == 0
    assert pm.heat_close_in([70, 86, 87, 70, 88, 60, 60], TUN) == 0
    assert pm.heat_close_in([70, 70, 86, 87, 88], TUN) == 0      # 3 of the next 5
    assert pm.heat_close_in([70, 70, 70, 86, 87, 88], TUN) == 1
    assert pm.heat_close_in([84] * 10, TUN) is None
    open_ = [AreaSignals("front", soil5=60.0)]
    ws = _run(MAY, open_, highs=[70, 70, 70, 86, 87, 88])
    assert _w(ws, pm.SPRING).expected_close == MAY             # closes tomorrow
    ws = _run(MAY + timedelta(days=1), open_, ws, highs=[70, 70, 86, 87, 88])
    w = _w(ws, pm.SPRING)
    assert (w.status, w.closed) == ("closed", MAY + timedelta(days=1))


# --- fall broadleaf -----------------------------------------------------------------

def test_fall_opens_on_t7_from_aug_15_and_closes_on_dormancy():
    cool = AreaSignals("front", air_means=(69.0,) * 7)
    assert _w(_run(date(2026, 8, 10), [cool]), pm.FALL).status == "tentative"
    ws = _run(date(2026, 8, 20), [cool])
    w = _w(ws, pm.FALL)
    assert (w.status, w.source, w.value) == ("open", "air", 69.0)
    ws = _run(OCT, [replace(cool, dormant=True)], ws)
    assert _w(ws, pm.FALL).status == "closed"


def test_fall_projection_and_cold_before_open_closes_silently():
    warm = AreaSignals("front", air_means=(72.0,) * 7)
    ws = _run(date(2026, 9, 1), [warm], horizon=[66.0] * 10)
    w = _w(ws, pm.FALL)
    assert w.status == "projected" and w.projected == date(2026, 9, 4)
    cold = AreaSignals("front", air_means=(40.0,) * 7)
    ws = _run(date(2026, 12, 1), [cold])
    w = _w(ws, pm.FALL)
    assert w.status == "closed" and "open" not in w.reached


def test_last_years_open_window_closes_at_the_year_end():
    w = Window(pm.FALL, 2026, "front", status="open",
               reached={"open": {"date": "2026-09-10", "source": "air", "value": 69.0,
                                 "area": "front"}})
    ws = _run(date(2027, 1, 2), windows={w.key: w})
    assert (ws[w.key].status, ws[w.key].closed) == ("closed", date(2027, 1, 1))


# --- young crabgrass ----------------------------------------------------------------

def _pre(germination=date(2027, 5, 1), done=None):
    reached = {"germination": {"date": germination.isoformat(), "source": "gdd",
                               "value": 201.0, "area": ""}}
    w = Window("pre_emergent", 2027, status="done" if done else "open", done=done,
               reached=reached)
    return {w.key: w}


def test_no_crabgrass_window_when_the_pre_emergent_went_down_in_time():
    assert _w(_run(MAY, windows=_pre(done=date(2027, 4, 10))), pm.CRABGRASS) is None
    assert _w(_run(MAY), pm.CRABGRASS) is None                   # no germination yet


def test_crabgrass_window_after_a_missed_or_late_pre_emergent():
    ws = _run(MAY, windows=_pre())
    w = _w(ws, pm.CRABGRASS)
    assert (w.status, w.projected) == ("projected", date(2027, 5, 15))
    ws = _run(date(2027, 5, 15), windows=ws)
    w = _w(ws, pm.CRABGRASS)
    assert w.status == "open" and w.expected_close == date(2027, 6, 25)
    ws = _run(date(2027, 6, 26), windows=ws)
    assert _w(ws, pm.CRABGRASS).status == "closed"
    late = _run(date(2027, 5, 20), windows=_pre(done=date(2027, 5, 5)))
    assert _w(late, pm.CRABGRASS).status == "open"


# --- flag_weeds and skip -----------------------------------------------------------

def test_flag_broadleaf_opens_spring_early_then_fall_after_jun_30():
    w = pm.flag({}, "front", "broadleaf", date(2027, 4, 1), TUN)
    assert (w.kind, w.status, w.flagged) == (pm.SPRING, "open", date(2027, 4, 1))
    assert w.reached["open"]["source"] == "flag" and "open" in w.notified
    ws = _run(date(2027, 4, 2), windows={w.key: w})
    assert _w(ws, pm.SPRING).status == "open"                 # stays open (no soil signal)
    w = pm.flag({}, "front", "broadleaf", date(2027, 7, 10), TUN)
    assert w.kind == pm.FALL


def test_flag_crabgrass_and_an_ended_window():
    w = pm.flag({}, "front", "crabgrass", date(2027, 7, 1), TUN)
    ws = _run(date(2027, 7, 2), windows={w.key: w})
    c = _w(ws, pm.CRABGRASS)
    assert c.status == "open" and c.expected_close == date(2027, 8, 11)
    ended = replace(c, status="closed")
    with pytest.raises(pm.WindowEnded):
        pm.flag({ended.key: ended}, "front", "crabgrass", date(2027, 8, 20), TUN)
    skipped = Window(pm.SPRING, 2027, "front", status="skipped", skipped=date(2027, 4, 1))
    reopened = pm.flag({skipped.key: skipped}, "front", "broadleaf", date(2027, 4, 9), TUN)
    assert (reopened.status, reopened.skipped) == ("open", None)


def test_skip_takes_the_open_window_else_the_next_one():
    ws = _run(MAY, [AreaSignals("front", soil5=60.0)])
    [s] = pm.skip(ws, "front", MAY, TUN)
    assert (s.kind, s.status) == (pm.SPRING, "skipped")
    ws = _run(MAY, [AreaSignals("front", soil5=40.0)])
    [s] = pm.skip(ws, "front", MAY, TUN)
    assert s.kind == pm.SPRING                                  # May 10 before Sep 20


def test_current_window_for_the_sensor():
    ws = _run(MAY, [AreaSignals("front", soil5=40.0)])
    assert pm.current(ws, "front", MAY, TUN).kind == pm.SPRING
    ws = _run(date(2027, 7, 2), [AreaSignals("front", soil5=40.0)], ws)
    assert pm.current(ws, "front", date(2027, 7, 2), TUN).kind == pm.FALL


# --- the mowing hold and follow-ups --------------------------------------------------

def test_hold_until_after_the_latest_post_emergent():
    apps = [_post("mesotrione", MAY), _post("prodiamine", MAY + timedelta(days=1))]
    assert pm.hold_until(apps, "front", MAY, TUN) == MAY + timedelta(days=2)
    assert pm.hold_until(apps, "front", MAY + timedelta(days=1), TUN) == MAY + timedelta(days=2)
    assert pm.hold_until(apps, "front", MAY + timedelta(days=2), TUN) is None
    assert pm.hold_until(apps, "back", MAY, TUN) is None
    off = replace(TUN, post_hold_mowing=False)
    assert pm.hold_until(apps, "front", MAY, off) is None


def test_followups_only_for_products_with_one():
    apps = [_post("triclopyr_ester", MAY), _post("mesotrione", MAY)]
    [f] = pm.followups(apps, TUN)
    assert f.due == MAY + timedelta(days=21) and f.app.product == "triclopyr_ester"
    assert not pm.superseded(f, apps)
    assert pm.superseded(f, apps + [_post("mesotrione", MAY + timedelta(days=10))])


# --- the spray-day check -----------------------------------------------------------

def _hours(day, *, wind=5.0, rain=10.0, temp=72.0, start=0, count=48):
    first = datetime(day.year, day.month, day.day)
    return tuple(HourDetail(first + timedelta(hours=start + i), temp, wind, rain)
                 for i in range(count))


def _fc(day=MAY, high=75.0, next_high=75.0, **hours):
    days = {day: DayDetail(high, 10.0), day + timedelta(days=1): DayDetail(next_high, 10.0)}
    return ForecastDetail(days, _hours(day, **hours))


CTX = pm.SprayContext(product="mesotrione", last_mow=MAY - timedelta(days=3),
                      days_until_due=5)


def _check(fc=None, ctx=CTX, day=MAY):
    return pm.spray_day(day, MAY, ctx, fc or _fc(), TUN)


def test_a_good_spray_day():
    v = _check()
    assert v.good and v.failed == () and v.skipped == ()


def test_temperature_check():
    assert _check(_fc(high=58.0)).failed == ("temperature",)
    assert _check(_fc(high=86.0)).failed == ("temperature",)
    tric = replace(CTX, product="triclopyr_ester")
    assert _check(_fc(high=81.0), tric).failed == ("temperature",)
    v = _check(_fc(high=78.0, next_high=82.0), tric)
    assert v.failed == ("temperature",) and "next day's high 82" in v.reasons[0]


def test_rain_check_hourly_then_daily_then_skipped():
    assert _check(_fc(rain=40.0)).failed == ("rain",)
    no_hourly_rain = _fc(rain=None)
    assert _check(no_hourly_rain).good                        # daily 10 %
    wet_day = replace(no_hourly_rain, days={MAY: DayDetail(75.0, 60.0)})
    assert _check(wet_day).failed == ("rain",)
    nothing = ForecastDetail({MAY: DayDetail(75.0, None)}, ())
    v = _check(nothing)
    assert v.good and set(v.skipped) == {"rain", "wind"}


def test_wind_check_uses_the_morning_hours():
    assert _check(_fc(wind=12.0)).failed == ("wind",)
    calm_morning = ForecastDetail(_fc().days, tuple(
        replace(h, wind_mph=20.0 if h.when.hour >= 12 else 4.0) for h in _hours(MAY)))
    assert _check(calm_morning).good
    v = _check(_fc(wind=None))
    assert v.good and v.skipped == ("wind",)


def test_mowing_check():
    v = _check(ctx=replace(CTX, last_mow=MAY - timedelta(days=1)))
    assert v.failed == ("mowing",) and not v.mow_first
    v = _check(ctx=replace(CTX, days_until_due=2))
    assert v.failed == ("mowing",) and v.mow_first
    v = _check(ctx=replace(CTX, mow_due=True))
    assert v.mow_first
    tomorrow = pm.spray_day(MAY + timedelta(days=1), MAY, replace(CTX, days_until_due=3),
                            _fc(), TUN)
    assert tomorrow.mow_first                                 # due 2 days after spraying
    assert _check(ctx=replace(CTX, days_until_due=3)).good


def test_stress_check():
    assert _check(ctx=replace(CTX, dormant=True)).failed == ("stress",)
    assert _check(ctx=replace(CTX, heat_hold={MAY: True})).failed == ("stress",)
    assert _check(ctx=replace(CTX, water_factor=0.3)).failed == ("stress",)


def test_seedling_rules_per_product():
    seeded = replace(CTX, seeding_date=date(2026, 9, 10))
    v = _check(ctx=seeded)
    assert v.failed == ("seedlings",) and "Seedlings ready" in v.reasons[0]
    ready = replace(seeded, seedlings_ready=True, ready_on=date(2027, 4, 20))
    assert _check(ctx=ready).good                             # mesotrione: ready is enough
    tric = replace(ready, product="triclopyr_ester",
                   mows=(date(2027, 4, 22), date(2027, 4, 29)))
    v = _check(ctx=tric)
    assert v.failed == ("seedlings",) and "(2 so far)" in v.reasons[0]
    assert _check(ctx=replace(tric, mows=tric.mows + (date(2027, 4, 30),))).good
    # after the first mow the seeding date is cleared; the ready date still counts
    assert not _check(ctx=replace(tric, seeding_date=None, seedlings_ready=False)).good
    assert _check(ctx=replace(tric, seeding_date=None, seedlings_ready=False,
                              ready_on=date(2025, 9, 1))).good   # a year ago


def test_verdict_dict():
    assert _check(_fc(wind=None)).to_dict() == {
        "date": "2027-05-03", "good": True, "failed": [], "not_checked": ["wind"],
        "reasons": []}
