from datetime import date, timedelta

from custom_components.lawn_growth.model import calwriter
from custom_components.lawn_growth.model.appcalendar import (
    AreaCalendar, CalendarState, calendar_events)
from custom_components.lawn_growth.model.applications import Application
from custom_components.lawn_growth.model.calwriter import Ledger, plan, record
from custom_components.lawn_growth.model.config import Tunables
from custom_components.lawn_growth.model.windows import Window

TUN = Tunables()
AREAS = {"front": AreaCalendar("Front & Side"), "back": AreaCalendar("Back")}
NAMES = {k: a.name for k, a in AREAS.items()}
DAY = date(2026, 10, 20)


def _events(windows=(), apps=(), today=DAY, mows=()):
    return calendar_events(CalendarState(
        today=today, tunables=TUN, windows={w.key: w for w in windows},
        applications=tuple(apps), areas=AREAS, mows=tuple(mows)))


def _open(on, area):
    return {"open": {"date": on.isoformat(), "source": "air", "value": None, "area": area}}


def _write_all(events, ledger, today=DAY):
    writes = plan(events, ledger, NAMES)
    ledger, _ = record(ledger, today, ok=[a for w in writes for a in w.atoms],
                       reachable=True, live=_live(events))
    return writes, ledger


def _live(events):
    return {a for e in events if calwriter.writable(e) for a in calwriter.atoms(e)}


def test_only_firm_events_are_written():
    ws = [Window("pre_emergent", 2027),                                     # tentative
          Window("overseed", 2026, "back", status="projected", projected=DAY),
          Window("winterizer", 2026, "back", status="open", reached=_open(DAY, "back"))]
    tun_mows = [(DAY, "back")]
    writes = plan(_events(ws, mows=tun_mows), Ledger(), NAMES)
    assert [w.summary for w in writes] == ["Apply winterizer — Back"]


def test_missed_windows_and_mows_are_not_written():
    w = Window("winterizer", 2026, "back", status="missed", closed=DAY)
    events = [e for e in _events([w])]
    assert all(not calwriter.writable(e) for e in events)


def test_service_data_is_an_all_day_event_with_the_key():
    apps = [Application("fert", DAY, ("back",))]
    [w] = plan(_events(apps=apps), Ledger(), NAMES)
    assert w.service_data() == {
        "summary": "Fertilizer — Back",
        "description": "Lawn Growth key: lawn_growth-fert-2026-back-applied-2026-10-20",
        "start_date": "2026-10-20", "end_date": "2026-10-21"}


def test_each_event_is_written_once():
    apps = [Application("fert", DAY, ("front", "back"))]
    events = _events(apps=apps)
    writes, ledger = _write_all(events, Ledger())
    assert [w.summary for w in writes] == ["Fertilizer — whole lawn"]
    assert set(ledger.written) == {"lawn_growth-fert-2026-front-applied-2026-10-20",
                                   "lawn_growth-fert-2026-back-applied-2026-10-20"}
    assert plan(events, ledger, NAMES) == []
    assert plan(events, Ledger.from_dict(ledger.to_dict()), NAMES) == []   # a restart


def test_a_second_area_on_the_same_day_writes_only_that_area():
    first = [Application("fert", DAY, ("back",))]
    _, ledger = _write_all(_events(apps=first), Ledger())
    both = first + [Application("fert", DAY, ("front",))]
    [w] = plan(_events(apps=both), ledger, NAMES)
    assert w.summary == "Fertilizer — Front & Side"
    assert w.key == "lawn_growth-fert-2026-front-applied-2026-10-20"


def test_merged_window_openings_keep_their_atoms():
    ws = [Window("winterizer", 2026, k, status="open", reached=_open(DAY, k))
          for k in ("front", "back")]
    writes, ledger = _write_all(_events(ws), Ledger())
    assert [w.summary for w in writes] == ["Apply winterizer — Front & Side, Back"]
    later = _events(ws, today=DAY + timedelta(days=5))       # the span grows, same key
    assert plan(later, ledger, NAMES) == []


def test_failures_are_retried_then_dropped_only_while_others_succeed():
    a, b = "atom-a", "atom-b"
    ledger, _ = record(Ledger(), DAY, failed=[a], reachable=True, live={a, b})
    assert ledger.pending == {a: DAY} and ledger.failing_since == DAY
    # every write fails for a week: kept, the streak runs
    for n in range(1, 8):
        ledger, dropped = record(ledger, DAY + timedelta(days=n), failed=[a],
                                 reachable=True, live={a, b})
        assert dropped == []
    assert calwriter.failing(ledger, DAY + timedelta(days=2))
    assert not calwriter.failing(Ledger(failing_since=DAY), DAY + timedelta(days=1))
    # another write succeeds: the streak ends and the stale one is given up
    ledger, dropped = record(ledger, DAY + timedelta(days=8), ok=[b], failed=[a],
                             reachable=True, live={a, b})
    assert dropped == [a] and ledger.dropped == {a: DAY + timedelta(days=8)}
    assert ledger.failing_since is None and ledger.pending == {}
    assert plan([], ledger, NAMES) == []


def test_a_recent_failure_is_not_dropped():
    ledger, _ = record(Ledger(), DAY, failed=["a"], reachable=True, live={"a", "b"})
    ledger, dropped = record(ledger, DAY + timedelta(days=1), ok=["b"], failed=["a"],
                             reachable=True, live={"a", "b"})
    assert dropped == [] and ledger.pending == {"a": DAY}


def test_a_healthy_run_with_nothing_to_write_ends_the_streak():
    ledger = Ledger(failing_since=DAY)
    assert record(ledger, DAY, reachable=False)[0].failing_since == DAY
    assert record(ledger, DAY, reachable=True)[0].failing_since is None


def test_old_entries_for_events_no_longer_on_the_calendar_are_pruned():
    old, recent = DAY - timedelta(days=40), DAY - timedelta(days=5)
    ledger = Ledger(written={"gone-old": old, "gone-recent": recent, "live-old": old},
                    pending={"gone": DAY}, dropped={"dropped-old": old})
    new, _ = record(ledger, DAY, reachable=True, live={"live-old"})
    assert new.written == {"gone-recent": recent, "live-old": old}
    assert new.pending == {} and new.dropped == {}
