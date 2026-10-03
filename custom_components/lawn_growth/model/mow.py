"""Mow records: the only source of an area's Last cut height. Pure Python."""
from __future__ import annotations

from .state import AreaState, MowRecord

MAX_RECORDS = 20


def apply_mow(state: AreaState, record: MowRecord) -> AreaState:
    """Add a mow record. A record at/after the stored last mow resets the growth
    accumulator; an older (backdated) record is kept as history only.

    A mow after the seeding date ends establishment only once Seedlings ready was
    pressed. Earlier mows are establishment mows -- seedlings often get a few
    careful cuts before they can take routine mowing -- and keep the seeding."""
    s = state.copy()
    s.mow_records.append(record)
    s.mow_records.sort(key=lambda r: r.date)          # stable: same-day newest stays last
    s.mow_records = s.mow_records[-MAX_RECORDS:]
    if s.last_mow is not None and record.date < s.last_mow:
        return s
    s.accumulated_mm = 0.0
    s.last_mow = record.date
    s.due_notified = False
    if (s.seeding_date is not None and record.date > s.seeding_date
            and s.seedlings_ready):
        s.seeding_date = None
        s.seedlings_ready = False
        s.ready_notified = False
    return s


def correct_last_mow(state: AreaState, height_in: float) -> AreaState:
    """Fix the most recent record's height (e.g. a mis-read blade height)."""
    if not state.mow_records:
        raise ValueError("no mow has been recorded yet")
    s = state.copy()
    last = s.mow_records[-1]
    s.mow_records[-1] = MowRecord(last.date, float(height_in), "manual")
    return s
