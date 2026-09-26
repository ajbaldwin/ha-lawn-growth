"""Mower session accumulator: time per mowing area and per blade height. Pure Python.

The HA layer feeds it state transitions (working / location / blade height); on
close, each area mowed long enough gets its time-weighted blade height.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

UNSET = object()


@dataclass
class MowerSession:
    started: datetime
    last_sample: datetime
    last_working: datetime
    working: bool = True
    area: Optional[str] = None
    height_in: Optional[float] = None
    area_seconds: dict = field(default_factory=dict)       # area -> seconds
    height_seconds: dict = field(default_factory=dict)     # area -> {"2.95": seconds}

    def to_dict(self) -> dict:
        return {"started": self.started.isoformat(),
                "last_sample": self.last_sample.isoformat(),
                "last_working": self.last_working.isoformat(), "working": self.working,
                "area": self.area, "height_in": self.height_in,
                "area_seconds": dict(self.area_seconds),
                "height_seconds": {k: dict(v) for k, v in self.height_seconds.items()}}

    @classmethod
    def from_dict(cls, d: dict) -> "MowerSession":
        return cls(datetime.fromisoformat(d["started"]),
                   datetime.fromisoformat(d["last_sample"]),
                   datetime.fromisoformat(d["last_working"]), d["working"], d["area"],
                   d["height_in"], dict(d["area_seconds"]),
                   {k: dict(v) for k, v in d["height_seconds"].items()})


def start(now: datetime, *, area: Optional[str], height_in: Optional[float]) -> MowerSession:
    return MowerSession(started=now, last_sample=now, last_working=now, working=True,
                        area=area, height_in=height_in)


def _accrue(s: MowerSession, now: datetime) -> None:
    if s.working and s.area is not None:
        dt = max(0.0, (now - s.last_sample).total_seconds())
        s.area_seconds[s.area] = s.area_seconds.get(s.area, 0.0) + dt
        if s.height_in is not None:
            bucket = s.height_seconds.setdefault(s.area, {})
            key = f"{s.height_in:.2f}"
            bucket[key] = bucket.get(key, 0.0) + dt
    s.last_sample = now


def update(s: MowerSession, now: datetime, *, working=UNSET, area=UNSET,
           height_in=UNSET) -> None:
    _accrue(s, now)
    if working is not UNSET:
        if working or s.working:
            s.last_working = now        # still working, or the moment work stopped
        s.working = bool(working)
    if area is not UNSET:
        s.area = area
    if height_in is not UNSET:
        s.height_in = height_in


def ready_to_close(s: MowerSession, now: datetime, grace_s: float) -> bool:
    return (not s.working) and (now - s.last_working).total_seconds() >= grace_s


def results(s: MowerSession, min_area_s: float) -> list:
    out = []
    for area, secs in sorted(s.area_seconds.items()):
        if secs < min_area_s:
            continue
        hs = s.height_seconds.get(area, {})
        total = sum(hs.values())
        height = round(sum(float(h) * v for h, v in hs.items()) / total, 2) if total else None
        out.append((area, height))
    return out
