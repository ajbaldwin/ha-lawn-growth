"""Application windows: at most one per kind per season, lawn-wide (pre-emergent) or
per area (winterizer, fall overseed). Pure Python.

    tentative -> projected -> open -> done   (or skipped / missed)

Transitions are latched in `reached` with the date, source and value that set them,
so a window that opened stays open when the soil source switches, and a source
switch never repeats a transition. Notifications read `reached` (see notify.py).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from .applications import for_area, is_pre_emergent, latest

KINDS = ("pre_emergent", "winterizer", "overseed")
STATUSES = ["tentative", "projected", "open", "done", "skipped", "missed"]
ACTIVE = ("tentative", "projected", "open")
LAWN = "all"
PRE_STAGES = ("heads_up", "open", "late", "germination")
# Transitions in order, per kind (notify.py decides which ones push).
TRANSITIONS = {"pre_emergent": (*PRE_STAGES, "missed"),
               "winterizer": ("open", "missed"),
               "overseed": ("open", "closing", "missed")}
FALLBACK_SOURCES = ("gdd", "air")      # estimated from air temperatures


def _d(value) -> Optional[date]:
    return date.fromisoformat(value) if value else None


def _s(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None


def window_key(kind: str, season: int, area: str = LAWN) -> str:
    return f"{kind}:{season}:{area}"


@dataclass
class Window:
    kind: str
    season: int
    area: str = LAWN
    status: str = "tentative"
    projected: Optional[date] = None        # projected open date (status projected)
    expected_close: Optional[date] = None
    done: Optional[date] = None             # first application / seeding this season
    product: str = ""
    skipped: Optional[date] = None
    closed: Optional[date] = None           # date it went missed
    source: str = ""                        # current signal: geodrops | gdd | air
    value: Optional[float] = None
    set_by: str = ""                        # area key behind the current signal
    updated: Optional[date] = None          # last status change
    reached: dict = field(default_factory=dict)  # transition -> {date, source, value, area}
    notified: list = field(default_factory=list)
    last_due: Optional[date] = None         # winterizer: last day a mow was due
    cold_since: Optional[date] = None       # winterizer: first day of Soil5 < 40 °F
    wind_down_seen: bool = False

    @property
    def key(self) -> str:
        return window_key(self.kind, self.season, self.area)

    def reached_on(self, transition: str) -> Optional[date]:
        info = self.reached.get(transition)
        return _d(info.get("date")) if info else None

    def copy(self) -> "Window":
        return Window.from_dict(self.to_dict())

    def to_dict(self) -> dict:
        return {"kind": self.kind, "season": self.season, "area": self.area,
                "status": self.status, "projected": _s(self.projected),
                "expected_close": _s(self.expected_close), "done": _s(self.done),
                "product": self.product, "skipped": _s(self.skipped),
                "closed": _s(self.closed), "source": self.source, "value": self.value,
                "set_by": self.set_by, "updated": _s(self.updated),
                "reached": {k: dict(v) for k, v in self.reached.items()},
                "notified": list(self.notified), "last_due": _s(self.last_due),
                "cold_since": _s(self.cold_since), "wind_down_seen": self.wind_down_seen}

    @classmethod
    def from_dict(cls, d: dict) -> "Window":
        return cls(kind=d["kind"], season=int(d["season"]), area=d.get("area", LAWN),
                   status=d.get("status", "tentative"), projected=_d(d.get("projected")),
                   expected_close=_d(d.get("expected_close")), done=_d(d.get("done")),
                   product=d.get("product", ""), skipped=_d(d.get("skipped")),
                   closed=_d(d.get("closed")), source=d.get("source", ""),
                   value=d.get("value"), set_by=d.get("set_by", ""),
                   updated=_d(d.get("updated")),
                   reached={k: dict(v) for k, v in (d.get("reached") or {}).items()},
                   notified=list(d.get("notified") or []), last_due=_d(d.get("last_due")),
                   cold_since=_d(d.get("cold_since")),
                   wind_down_seen=bool(d.get("wind_down_seen", False)))


@dataclass(frozen=True)
class AreaSignals:
    """One area's inputs for the day (built by the coordinator)."""
    key: str
    soil5: Optional[float] = None
    soil5_prev: Optional[float] = None      # Soil5 a day earlier ("rising")
    soil_slope: Optional[float] = None      # °F/day trend of the daily soil means
    air_means: tuple = ()                   # recent daily air means, oldest first
    phase: str = "active"
    mow_due: bool = False
    days_until_due: Optional[int] = None
    dormant: bool = False
    last_mow: Optional[date] = None
    overseed_capable: bool = True


@dataclass(frozen=True)
class LawnSignals:
    today: date
    gdd: Optional[float]                    # this year's GDD50 total; None if unknown
    horizon: tuple = ()                     # forecast daily means after today


# --- seasons ---------------------------------------------------------------------

def current_season(kind: str, today: date, tun) -> int:
    if kind == "pre_emergent" and today.month >= tun.pre_season_end_month:
        return today.year + 1
    return today.year


def season_start(kind: str, season: int, tun) -> date:
    if kind == "pre_emergent":
        return date(season, 1, 1)
    month = tun.winterizer_from_month if kind == "winterizer" else tun.overseed_from_month
    return date(season, month, 1)


def season_end(kind: str, season: int, tun) -> date:
    """The first day the season's window is no longer evaluated."""
    if kind == "pre_emergent":
        return date(season, tun.pre_season_end_month, 1)
    return date(season + 1, 1, 1)


def typical_date(kind: str, season: int, tun) -> date:
    month, day = {"pre_emergent": tun.pre_typical, "winterizer": tun.winterizer_typical,
                  "overseed": tun.overseed_typical}[kind]
    return date(season, month, day)


def _active(kind: str, season: int, today: date, tun) -> bool:
    return season_start(kind, season, tun) <= today < season_end(kind, season, tun)


# --- projections -------------------------------------------------------------------

def _mean(values) -> Optional[float]:
    values = list(values)
    return sum(values) / len(values) if values else None


def trend_cross(value: Optional[float], slope: Optional[float], threshold: float, *,
                rising: bool, limit: Optional[int]) -> Optional[int]:
    """Days from today (>= 1) until a linear trend crosses the threshold; None if it
    is heading the other way or doesn't get there within `limit` days."""
    if value is None or slope is None:
        return None
    if rising and slope > 0:
        need = (threshold - value) / slope
    elif not rising and slope < 0:
        need = (value - threshold) / -slope
    else:
        return None
    days = max(1, math.ceil(need - 1e-9))
    return days if limit is None or days <= limit else None


def gdd_cross(total: float, horizon, base_f: float, threshold: float) -> Optional[int]:
    """Days from today until forecast GDD reach the threshold, within the horizon."""
    acc = total
    for i, mean_f in enumerate(horizon, start=1):
        acc += max(0.0, mean_f - base_f)
        if acc >= threshold:
            return i
    return None


def gdd_extrapolate(total: float, horizon, base_f: float, threshold: float) -> Optional[int]:
    """Days until the threshold at the forecast's average daily rate (past the horizon)."""
    rate = _mean(max(0.0, m - base_f) for m in horizon)
    if not rate:
        return None
    return max(1, math.ceil((threshold - total) / rate - 1e-9))


def t7_cross(air_means, horizon, test) -> Optional[int]:
    """Days from today until the trailing 7-day air mean, rolled forward through the
    forecast, satisfies `test`."""
    series = list(air_means)
    for i, mean_f in enumerate(horizon, start=1):
        series.append(mean_f)
        if test(sum(series[-7:]) / len(series[-7:])):
            return i
    return None


def _t7(a: AreaSignals) -> Optional[float]:
    return _mean(a.air_means[-7:])


# --- helpers ------------------------------------------------------------------------

def _set_status(w: Window, status: str, today: date) -> None:
    if w.status != status:
        w.status = status
        w.updated = today


def _reach(w: Window, transition: str, on: date, source: str = "",
           value: Optional[float] = None, area: str = "") -> None:
    if transition not in w.reached:
        w.reached[transition] = {"date": on.isoformat(), "source": source,
                                 "value": None if value is None else round(value, 1),
                                 "area": area}


def _done(w: Window, first: date, today: date, product: str = "") -> None:
    w.projected = None
    if w.status != "done" or w.done != first:
        w.done, w.product = first, product
        w.status, w.updated = "done", today


def skip(w: Window, today: date) -> Window:
    """skip_application: the user won't apply this season. A logged application
    still wins (the window then reads done)."""
    w = w.copy()
    if w.status != "done":
        w.skipped = today
        w.projected = None
        _set_status(w, "skipped", today)
    return w


# --- pre-emergent (lawn-wide) -------------------------------------------------------

def _stage(value: Optional[float], thresholds, rising: bool) -> int:
    """Highest stage index reached (-1 for none). Heads-up also needs a rising trend."""
    best = -1
    if value is None:
        return best
    for i, threshold in enumerate(thresholds):
        if value >= threshold and (i > 0 or rising):
            best = i
    return best


def pre_emergent_logs(apps, season: int) -> list:
    return sorted((a for a in apps if is_pre_emergent(a) and a.date.year == season),
                  key=lambda a: a.date)


def split_reminder_date(w: Window, apps, tun) -> Optional[date]:
    """The second (split) application reminder: N weeks after the first, until a
    second pre-emergent is logged."""
    if not tun.split_reminder or w.kind != "pre_emergent" or w.done is None:
        return None
    if any(a.date > w.done for a in pre_emergent_logs(apps, w.season)):
        return None
    return w.done + timedelta(days=tun.split_reminder_days)


def suggested_pre_product(w: Optional[Window]) -> str:
    """Prodiamine first; dithiopyr for the split, or once germination is expected
    (it still controls very young crabgrass)."""
    if w is not None and (w.done is not None or "germination" in w.reached):
        return "dithiopyr"
    return "prodiamine"


def update_pre_emergent(w: Window, lawn: LawnSignals, areas, apps, tun) -> Window:
    w = w.copy()
    today = lawn.today
    probes = [a for a in areas if a.soil5 is not None]
    use_gdd = lawn.gdd is not None and len(probes) < len(areas)
    active = _active(w.kind, w.season, today, tun)

    if active:
        warm = max(probes, key=lambda a: a.soil5) if probes else None
        soil_rank = (_stage(warm.soil5, tun.pre_soil_f,
                            warm.soil5_prev is None or warm.soil5 > warm.soil5_prev)
                     if warm else -1)
        gdd_rank = _stage(lawn.gdd, tun.pre_gdd, True) if use_gdd else -1
        if warm is not None and (not use_gdd or soil_rank >= gdd_rank):
            source, value, area, rank = "geodrops", warm.soil5, warm.key, soil_rank
        elif use_gdd:
            source, value, area, rank = "gdd", lawn.gdd, "", gdd_rank
        else:
            source, value, area, rank = "", None, "", -1
        w.source, w.value, w.set_by = source, value, area
        for stage in PRE_STAGES[:rank + 1]:
            _reach(w, stage, today, source, value, area)

    logs = pre_emergent_logs(apps, w.season)
    if logs:
        _done(w, logs[0].date, today, logs[0].product)
        return w
    if w.status in ("skipped", "missed") or not active:
        return w

    if "open" in w.reached:
        w.projected = None
        germination = w.reached_on("germination")
        if germination is not None:
            w.expected_close = germination + timedelta(days=tun.pre_close_days)
            if today >= w.expected_close:
                w.closed = w.expected_close
                _reach(w, "missed", w.closed)
                _set_status(w, "missed", today)
                return w
        else:
            days = [d for d in (
                *(trend_cross(a.soil5, a.soil_slope, tun.pre_soil_f[3], rising=True,
                              limit=None) for a in probes),
                gdd_extrapolate(lawn.gdd, lawn.horizon, tun.gdd_base_f, tun.pre_gdd[3])
                if use_gdd else None) if d is not None]
            if days:
                w.expected_close = today + timedelta(days=min(days) + tun.pre_close_days)
            else:
                w.expected_close = (w.reached_on("open")
                                    + timedelta(days=tun.pre_open_estimate_days))
        _set_status(w, "open", today)
        return w

    horizon_days = tun.forecast_horizon_days
    days = [d for d in (
        *(trend_cross(a.soil5, a.soil_slope, tun.pre_soil_f[1], rising=True,
                      limit=horizon_days) for a in probes),
        gdd_cross(lawn.gdd, lawn.horizon[:horizon_days], tun.gdd_base_f, tun.pre_gdd[1])
        if use_gdd else None) if d is not None]
    if days:
        w.projected = today + timedelta(days=min(days))
        _set_status(w, "projected", today)
    else:
        w.projected = None
        _set_status(w, "tentative", today)
    return w


# --- winterizer (per area) ----------------------------------------------------------

def last_fertilizer(apps, area: str) -> Optional[date]:
    return latest(apps, area, ("fert", "winterizer"))


def winterizer_conditions(w: Window, today: date, a: AreaSignals, apps, tun) -> dict:
    """The three opening conditions (spec §2.2), each True/False."""
    pending_due = w.last_due is not None and (a.last_mow is None or w.last_due > a.last_mow)
    wound_down = (a.phase == "wind_down" and a.last_mow is not None and not pending_due
                  and (today - a.last_mow).days >= tun.winterizer_quiet_days)
    fert = last_fertilizer(apps, a.key)
    spacing = fert is None or (today - fert).days >= tun.winterizer_spacing_days
    green = not a.dormant and (a.soil5 is None or a.soil5 >= tun.winterizer_min_soil_f)
    return {"wound_down": wound_down, "spacing": spacing, "green": green}


def update_winterizer(w: Window, today: date, a: AreaSignals, horizon, apps,
                      tun) -> Window:
    w = w.copy()
    if a.mow_due:
        w.last_due = today
    active = _active(w.kind, w.season, today, tun)
    if active:
        w.wind_down_seen = w.wind_down_seen or a.phase == "wind_down"
        if a.soil5 is not None and a.soil5 < tun.winterizer_min_soil_f:
            w.cold_since = w.cold_since or today
        else:
            w.cold_since = None
        w.source = "geodrops" if a.soil5 is not None else "air"
        w.value, w.set_by = a.soil5, a.key

    start = season_start(w.kind, w.season, tun)
    logs = sorted(x.date for x in for_area(apps, a.key, ("winterizer",))
                  if start <= x.date < season_end(w.kind, w.season, tun))
    if logs:
        _done(w, logs[0], today)
        return w
    if w.status in ("skipped", "missed") or not active:
        return w

    cold = (w.cold_since is not None
            and (today - w.cold_since).days >= tun.winterizer_cold_days - 1)
    if (a.dormant or cold) and (w.status == "open" or w.wind_down_seen):
        w.closed, w.projected = today, None
        _reach(w, "missed", today, w.source, a.soil5, a.key)
        _set_status(w, "missed", today)
        return w
    if w.status == "open":
        return w
    conds = winterizer_conditions(w, today, a, apps, tun)
    if all(conds.values()):
        w.projected = None
        _reach(w, "open", today, w.source, a.soil5, a.key)
        _set_status(w, "open", today)
        return w

    # Projected: conditions 1 and 2 are date-driven once growth has wound down.
    pending_due = w.last_due is not None and (a.last_mow is None or w.last_due > a.last_mow)
    w.projected = None
    if a.phase == "wind_down" and a.last_mow is not None and not pending_due \
            and conds["green"]:
        fert = last_fertilizer(apps, a.key)
        when = max(a.last_mow + timedelta(days=tun.winterizer_quiet_days),
                   fert + timedelta(days=tun.winterizer_spacing_days) if fert else today,
                   today + timedelta(days=1))
        n = (when - today).days
        if n <= tun.forecast_horizon_days and (a.days_until_due is None
                                               or a.days_until_due > n):
            w.projected = when
    _set_status(w, "projected" if w.projected else "tentative", today)
    return w


# --- fall overseed window (per area) ------------------------------------------------

def overseed_close_days(a: AreaSignals, horizon, tun) -> Optional[int]:
    days = [d for d in (
        trend_cross(a.soil5, a.soil_slope, tun.overseed_close_soil_f, rising=False,
                    limit=tun.forecast_horizon_days),
        t7_cross(a.air_means, horizon[:tun.forecast_horizon_days],
                 lambda t7: t7 < tun.overseed_close_air_t7_f)) if d is not None]
    return min(days) if days else None


def update_overseed(w: Window, today: date, a: AreaSignals, horizon, apps, tun) -> Window:
    w = w.copy()
    active = _active(w.kind, w.season, today, tun)
    t7, f7 = _t7(a), _mean(horizon[:7])
    if active:
        w.source = "geodrops" if a.soil5 is not None else "air"
        w.value = a.soil5 if a.soil5 is not None else t7
        w.set_by = a.key

    start = season_start(w.kind, w.season, tun)
    seeded = sorted(x.date for x in for_area(apps, a.key, ("seeding",))
                    if start <= x.date < season_end(w.kind, w.season, tun))
    if seeded:
        _done(w, seeded[0], today)
        return w
    if w.status in ("skipped", "missed") or not active:
        return w

    if a.soil5 is not None:
        opens = a.soil5 < tun.overseed_open_soil_f
    else:
        opens = (t7 is not None and t7 <= tun.overseed_open_air_t7_f
                 and f7 is not None and f7 < t7)
    closes = ((a.soil5 is not None and a.soil5 < tun.overseed_close_soil_f)
              or (t7 is not None and t7 < tun.overseed_close_air_t7_f))

    if closes:
        # Closed with nothing logged (also when it closed before Lawn Growth saw it open).
        w.closed, w.projected, w.expected_close = today, None, None
        _reach(w, "missed", today, w.source, w.value, a.key)
        _set_status(w, "missed", today)
        return w
    if w.status == "open" or opens:
        w.projected = None
        _reach(w, "open", today, w.source, w.value, a.key)
        n = overseed_close_days(a, horizon, tun)
        w.expected_close = today + timedelta(days=n) if n is not None else None
        if n is not None and n <= tun.overseed_closing_notice_days:
            _reach(w, "closing", today, w.source, w.value, a.key)
        _set_status(w, "open", today)
        return w

    limit = tun.forecast_horizon_days
    days = [d for d in (
        trend_cross(a.soil5, a.soil_slope, tun.overseed_open_soil_f - 1e-6, rising=False,
                    limit=limit) if a.soil5 is not None else None,
        t7_cross(a.air_means, horizon[:limit],
                 lambda v: v <= tun.overseed_open_air_t7_f)
        if a.soil5 is None else None) if d is not None]
    w.projected = today + timedelta(days=min(days)) if days else None
    _set_status(w, "projected" if w.projected else "tentative", today)
    return w


# --- all windows --------------------------------------------------------------------

def update_all(windows: dict, lawn: LawnSignals, areas, apps, tun) -> dict:
    """Advance every window for today. Windows of earlier seasons still open are
    closed as missed; windows of areas no longer configured, or older than last
    season, are dropped."""
    today = lawn.today
    out = {k: w.copy() for k, w in windows.items()}
    for w in out.values():
        if w.season < current_season(w.kind, today, tun) and w.status in ACTIVE:
            w.closed = season_end(w.kind, w.season, tun)
            w.projected = None
            _reach(w, "missed", w.closed)
            _set_status(w, "missed", today)

    def advance(kind, area, fn):
        season = current_season(kind, today, tun)
        key = window_key(kind, season, area)
        out[key] = fn(out.get(key) or Window(kind, season, area))

    advance("pre_emergent", LAWN, lambda w: update_pre_emergent(w, lawn, areas, apps, tun))
    for a in areas:
        advance("winterizer", a.key,
                lambda w, a=a: update_winterizer(w, today, a, lawn.horizon, apps, tun))
        if a.overseed_capable:
            advance("overseed", a.key,
                    lambda w, a=a: update_overseed(w, today, a, lawn.horizon, apps, tun))
    keep = {a.key for a in areas} | {LAWN}
    return {k: w for k, w in out.items()
            if w.area in keep and w.season >= today.year - 1}


def current(windows: dict, kind: str, today: date, tun, area: str = LAWN) -> Optional[Window]:
    return windows.get(window_key(kind, current_season(kind, today, tun), area))
