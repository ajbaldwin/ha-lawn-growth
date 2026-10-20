"""Copying firm application-calendar events to other calendars. Pure Python.

The core `calendar.create_event` service can only add events (no id comes back, and
not every calendar supports updates), so an event is written once its date is final
(`CalEvent.firm`) and never changed. Projections stay on Lawn Growth's own calendar.

A ledger per target calendar records what was written as *atoms*, one per area:
`lawn_growth-{kind}-{season}-{area}-{event}`. An event that later merges with another
area's on the same day (the same product logged for a second area) then writes only
the new area, never the first one again.

Calendars that can also delete events (Local Calendar, Google Calendar) are
*mirrored* instead: every event on Lawn Growth's calendar, estimates included, is
kept in step there (`mirror_plan`), matched by the key line in each description.
Events without that line are never touched.

A failed write is retried on later runs. An event that keeps failing is dropped after
`retry_days` once other writes to the same calendar succeed; while every write fails
(the calendar is down) nothing is dropped, so the backlog lands when it comes back.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

KEY_PREFIX = "Lawn Growth key: "
PRUNE_DAYS = 30            # ledger entries for events no longer on the calendar


def writable(event) -> bool:
    """Firm events except mows (a robot mower usually logs its own) and missed
    windows."""
    return event.firm and event.kind != "mow" and event.event != "missed"


def atoms(event) -> tuple:
    return tuple(f"lawn_growth-{event.kind}-{event.season}-{a}-{event.event}"
                 for a in event.areas)


@dataclass
class Ledger:
    written: dict = field(default_factory=dict)     # atom -> date written
    pending: dict = field(default_factory=dict)     # atom -> first failed write
    dropped: dict = field(default_factory=dict)     # atom -> date given up
    failing_since: Optional[date] = None            # first day of a failing streak

    def to_dict(self) -> dict:
        def iso(d):
            return {k: v.isoformat() for k, v in d.items()}
        return {"written": iso(self.written), "pending": iso(self.pending),
                "dropped": iso(self.dropped),
                "failing_since": self.failing_since.isoformat() if self.failing_since
                else None}

    @classmethod
    def from_dict(cls, d: dict) -> "Ledger":
        def dates(raw):
            return {k: date.fromisoformat(v) for k, v in (raw or {}).items()}
        since = d.get("failing_since")
        return cls(dates(d.get("written")), dates(d.get("pending")), dates(d.get("dropped")),
                   date.fromisoformat(since) if since else None)


@dataclass(frozen=True)
class Write:
    key: str
    atoms: tuple
    summary: str
    description: str
    start: date
    end: date                   # exclusive

    def service_data(self) -> dict:
        """calendar.create_event data: an all-day event (end = start + days)."""
        description = (f"{self.description}\n\n" if self.description else "") \
            + KEY_PREFIX + self.key
        return {"summary": self.summary, "description": description,
                "start_date": self.start.isoformat(), "end_date": self.end.isoformat()}


def plan(events, ledger: Ledger, names: dict) -> list:
    """The writes due: each writable event with atoms not yet written or dropped.
    When only some of its areas are new, the event is written for those areas."""
    done = set(ledger.written) | set(ledger.dropped)
    out = []
    for e in events:
        if not writable(e):
            continue
        mine = atoms(e)
        new = [(a, atom) for a, atom in zip(e.areas, mine) if atom not in done]
        if not new:
            continue
        if len(new) == len(mine):
            key, summary = e.key, e.summary
        else:
            areas = [a for a, _ in new]
            key = f"lawn_growth-{e.kind}-{e.season}-{'+'.join(areas)}-{e.event}"
            summary = f"{e.title} — " + ", ".join(names.get(a, a) for a in areas)
        out.append(Write(key, tuple(atom for _, atom in new), summary, e.description,
                         e.start, e.end))
    return out


def record(ledger: Ledger, today: date, *, ok=(), failed=(), reachable: bool,
           live=(), retry_days: int = 3) -> tuple[Ledger, list]:
    """The ledger after a run's writes, and the atoms given up on. `reachable`: the
    calendar existed and was available; `live`: every writable atom on the calendar
    now (older entries for events no longer on it are pruned)."""
    written, pending = dict(ledger.written), dict(ledger.pending)
    dropped, since = dict(ledger.dropped), ledger.failing_since
    for a in ok:
        written[a] = today
        pending.pop(a, None)
    for a in failed:
        pending.setdefault(a, today)
    given_up = []
    if ok:
        since = None
        cutoff = today - timedelta(days=retry_days)
        given_up = [a for a in failed if pending[a] <= cutoff]
        for a in given_up:
            dropped[a] = today
            del pending[a]
    elif failed:
        since = since or today
    elif reachable:
        since = None
    live = set(live)
    old = today - timedelta(days=PRUNE_DAYS)
    written = {a: d for a, d in written.items() if a in live or d > old}
    dropped = {a: d for a, d in dropped.items() if a in live or d > old}
    pending = {a: d for a, d in pending.items() if a in live}
    return Ledger(written, pending, dropped, since), given_up


def failing(ledger: Ledger, today: date, days: int = 3) -> bool:
    """Writes have failed on `days` consecutive days (today included)."""
    return (ledger.failing_since is not None
            and (today - ledger.failing_since).days >= days - 1)


# --- mirror mode --------------------------------------------------------------------

@dataclass(frozen=True)
class Existing:
    """An event read back from a mirrored calendar."""
    uid: Optional[str]
    key: Optional[str]          # from its "Lawn Growth key:" line; None: not ours
    summary: str
    description: str
    start: date
    end: date


def key_of(description: Optional[str]) -> Optional[str]:
    for line in (description or "").splitlines():
        if line.startswith(KEY_PREFIX):
            return line[len(KEY_PREFIX):].strip() or None
    return None


def _write(e) -> Write:
    return Write(e.key, atoms(e), e.summary, e.description, e.start, e.end)


def _same(w: Write, x: Existing) -> bool:
    data = w.service_data()
    return (x.summary == data["summary"] and (x.description or "").strip()
            == data["description"].strip() and (x.start, x.end) == (w.start, w.end))


def mirror_plan(events, existing) -> tuple[list, list, list]:
    """(creates, updates as (uid, Write), deletes as uid) that make a calendar's
    Lawn Growth events match `events` exactly. Only events with a key are touched; a
    key found twice keeps its first event."""
    want = {e.key: _write(e) for e in events}
    seen: dict = {}
    updates, deletes = [], []
    for x in existing:
        if x.key is None or x.uid is None:
            continue
        if x.key not in want or x.key in seen:
            deletes.append(x.uid)
            continue
        seen[x.key] = x
        if not _same(want[x.key], x):
            updates.append((x.uid, want[x.key]))
    creates = [w for k, w in want.items() if k not in seen]
    return creates, updates, deletes
