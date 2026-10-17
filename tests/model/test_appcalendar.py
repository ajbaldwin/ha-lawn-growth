from dataclasses import replace
from datetime import date, timedelta

from custom_components.lawn_growth.model.appcalendar import (
    AreaCalendar, CalendarState, calendar_events)
from custom_components.lawn_growth.model.applications import Application
from custom_components.lawn_growth.model.config import Tunables
from custom_components.lawn_growth.model.windows import Window

TUN = Tunables()
AREAS = {"front": AreaCalendar("Front & Side"), "back": AreaCalendar("Back")}


def _events(windows=(), apps=(), today=date(2027, 3, 1), areas=None, tun=TUN, mows=()):
    return calendar_events(CalendarState(
        today=today, tunables=tun, windows={w.key: w for w in windows},
        applications=tuple(apps), areas=areas if areas is not None else AREAS,
        mows=tuple(mows)))


def _open(on: date, source="gdd", value=126.0, area=""):
    return {"open": {"date": on.isoformat(), "source": source, "value": value,
                     "area": area}}


def test_tentative_event_on_the_typical_date():
    [e] = _events([Window("pre_emergent", 2027, updated=date(2027, 1, 1))])
    assert (e.key, e.summary, e.start, e.end, e.firm) == (
        "lawn_growth-pre_emergent-2027-all-window", "Pre-emergent (estimated)",
        date(2027, 4, 10), date(2027, 4, 11), False)
    assert e.description == "Status: tentative\nUpdated: 2027-01-01"
    [late] = _events([Window("pre_emergent", 2027)], today=date(2027, 4, 20))
    assert late.start == date(2027, 4, 20)              # never shown in the past


def test_a_moved_projection_keeps_its_key():
    w = Window("pre_emergent", 2027, status="projected", projected=date(2027, 4, 12),
               source="gdd", value=110.0)
    [a] = _events([w])
    [b] = _events([replace(w, projected=date(2027, 4, 15))])
    assert a.key == b.key and a.summary == "Pre-emergent window ~Apr 12"
    assert b.start == date(2027, 4, 15)
    assert "Trigger: 110 growing degree days" in a.description
    assert "Source: growing degree days (estimated from air temperatures)" in a.description


def test_open_window_spans_to_the_expected_close_and_is_firm():
    w = Window("pre_emergent", 2027, status="open", reached=_open(date(2027, 4, 12)),
               expected_close=date(2027, 5, 10), source="geodrops", value=51.0,
               set_by="back")
    [e] = _events([w], today=date(2027, 4, 14))
    assert (e.summary, e.start, e.end, e.firm) == (
        "Apply pre-emergent", date(2027, 4, 12), date(2027, 5, 11), True)
    assert "Trigger: 126 growing degree days" in e.description    # what opened it


def test_done_window_shows_history_and_the_split_reminder():
    w = Window("pre_emergent", 2027, status="done", done=date(2027, 4, 15),
               product="prodiamine", reached=_open(date(2027, 4, 12)))
    apps = [Application("herbicide", date(2027, 4, 15), ("front", "back"), "prodiamine")]
    events = _events([w], apps, today=date(2027, 4, 16))
    assert [(e.summary, e.start, e.end) for e in events] == [
        ("Apply pre-emergent", date(2027, 4, 12), date(2027, 4, 15)),
        ("Prodiamine — whole lawn", date(2027, 4, 15), date(2027, 4, 16)),
        ("Second pre-emergent (dithiopyr)", date(2027, 6, 3), date(2027, 6, 4))]
    log = events[1]
    assert log.key == "lawn_growth-prodiamine-2027-all-applied-2027-04-15"
    assert log.description == "Pre-emergent applied. Seeding blocked until Aug 5."
    assert all(e.firm for e in events)


def test_late_and_missed_events():
    w = Window("pre_emergent", 2027, status="missed", closed=date(2027, 5, 20),
               reached={**_open(date(2027, 4, 12)),
                        "late": {"date": "2027-04-25", "source": "gdd", "value": 176.0,
                                 "area": ""}})
    events = _events([w], today=date(2027, 5, 21))
    assert [(e.summary, e.start) for e in events] == [
        ("Apply pre-emergent", date(2027, 4, 12)),
        ("Pre-emergent late — apply now", date(2027, 4, 25)),
        ("Pre-emergent window missed", date(2027, 5, 20))]
    assert events[0].end == date(2027, 5, 20)


def test_skipped_window_leaves_the_upcoming_list():
    w = Window("pre_emergent", 2027, status="skipped", skipped=date(2027, 3, 1))
    assert _events([w]) == []


def test_same_day_area_events_merge():
    ws = [Window("winterizer", 2026, k, status="open",
                 reached=_open(date(2026, 10, 30), source="air", value=None, area=k))
          for k in ("back", "front")]
    [e] = _events(ws, today=date(2026, 10, 30))
    assert e.summary == "Apply winterizer — Front & Side, Back"
    assert e.key == "lawn_growth-winterizer-2026-front+back-open"
    other_day = [ws[0], replace(ws[1], reached=_open(date(2026, 10, 31), source="air",
                                                     value=None, area="front"))]
    assert len(_events(other_day, today=date(2026, 10, 31))) == 2


def test_logged_history():
    apps = [Application("fert", date(2026, 9, 1), ("back",)),
            Application("fert", date(2026, 9, 1), ("front",)),
            Application("herbicide", date(2026, 9, 5), ("back",), "mesotrione"),
            Application("seeding", date(2026, 9, 5), ("back",)),
            Application("winterizer", date(2026, 11, 2), ("front", "back"))]
    events = _events(apps=apps, today=date(2026, 11, 3))
    assert [e.summary for e in events] == [
        "Fertilizer — whole lawn", "Mesotrione spot — Back", "Seeding — Back",
        "Winterizer — whole lawn"]
    assert "mesotrione at seeding" in events[2].description
    assert events[1].description == ""


def test_mows_only_when_enabled():
    mows = [(date(2026, 9, 3), "back")]
    assert _events(mows=mows, today=date(2026, 9, 4)) == []
    [e] = _events(mows=mows, today=date(2026, 9, 4),
                  tun=replace(TUN, calendar_show_mows=True))
    assert e.summary == "Mow — Back"


def test_overseed_window_with_prep_milestone_then_a_planned_seed_supersedes_it():
    w = Window("overseed", 2026, "back", status="projected", projected=date(2026, 8, 28),
               source="geodrops", value=71.0, set_by="back")
    areas = {"back": AreaCalendar("Back", earliest_seed=date(2026, 8, 26), prep_days=6,
                                  buffer_days=7)}
    events = _events([w], areas=areas, today=date(2026, 8, 20))
    assert [(e.summary, e.start) for e in events] == [
        ("Start overseed prep — Back", date(2026, 8, 20)),
        ("Overseed window ~Aug 28 — Back", date(2026, 8, 28))]
    assert "Earliest seed date overseed prep can reach from today: Aug 26" in \
        events[1].description
    planned = {"back": replace(areas["back"], planned_seed=date(2026, 9, 10))}
    [seed] = _events([w], areas=planned, today=date(2026, 8, 20))
    assert (seed.summary, seed.start, seed.firm) == ("Overseed — seed date — Back",
                                                     date(2026, 9, 10), False)


def test_overseed_window_shows_a_seeding_block():
    w = Window("overseed", 2026, "back", status="open",
               reached=_open(date(2026, 8, 20), source="geodrops", value=69.0,
                             area="back"), source="geodrops", value=66.0)
    apps = [Application("herbicide", date(2026, 6, 1), ("front", "back"), "dithiopyr")]
    events = _events([w], apps, areas={"back": AreaCalendar("Back")},
                     today=date(2026, 8, 21))
    window = next(e for e in events if e.summary == "Overseed window — Back")
    assert "Dithiopyr applied Jun 1 — seeding blocked until Aug 24" in window.description
    assert "Ideal: soil is 60–70 °F" in window.description


def test_events_for_removed_areas_are_left_out():
    w = Window("winterizer", 2026, "gone", status="open", reached=_open(date(2026, 11, 1)))
    assert _events([w], today=date(2026, 11, 2)) == []
    assert _events(apps=[Application("fert", date(2026, 9, 1), ("gone",))]) == []


def test_tentative_dates_per_kind():
    ws = [Window("winterizer", 2026, "back"), Window("overseed", 2026, "back")]
    events = _events(ws, areas={"back": AreaCalendar("Back")}, today=date(2026, 3, 1))
    assert [(e.summary, e.start) for e in events] == [
        ("Overseed (estimated) — Back", date(2026, 8, 25)),
        ("Winterizer (estimated) — Back", date(2026, 11, 5))]
    assert all(e.end == e.start + timedelta(days=1) for e in events)
