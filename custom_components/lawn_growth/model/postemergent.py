"""Post-emergent: three windows per area, the spray-day check and the mowing hold
after a spray. Pure Python.

    spring broadleaf  opens  Soil5 >= 55 °F (GDD fallback: 250 GDD50)
                      closes forecast highs >= 85 °F on 3 of the next 5 days, or Jun 30
    fall broadleaf    opens  from Aug 15, air T7 <= 70 °F
                      closes dormancy, or air T7 < 45 °F
    young crabgrass   opens  14 days after "germination expected" (pre-emergent window),
                             only when the pre-emergent was missed, skipped or went
                             down after germination
                      closes 6 weeks later, as crabgrass starts tillering

An open window stays open through applications: post-emergent often takes a
follow-up. When it closes it reads `done` if a post-emergent was logged in it, else
`closed` (no weeds to spray isn't a miss). `flag_weeds` opens one early.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from .applications import (fmt_day, followup_days, for_area, heat_limit_f,
                           is_post_emergent, product_label,
                           rainfree_hours, seedling_mows)
from .windows import (LAWN, POST_KINDS, Window, _mean, _reach, _set_status, gdd_cross,
                      t7_cross, trend_cross, typical_date, window_key)

SPRING, FALL, CRABGRASS = POST_KINDS
STATUSES = ["tentative", "projected", "open", "done", "skipped", "closed"]
ENDED = ("done", "skipped", "closed")
UPCOMING = ("tentative", "projected")
TARGETS = {"broadleaf": (SPRING, FALL), "crabgrass": (CRABGRASS,)}
LABELS = {SPRING: "spring broadleaf", FALL: "fall broadleaf", CRABGRASS: "young crabgrass"}
CHECKS = ("temperature", "rain", "wind", "mowing", "stress", "seedlings")
_DAY = timedelta(days=1)


class WindowEnded(ValueError):
    """flag_weeds: the matching window already ended this season."""


# --- windows ------------------------------------------------------------------------

def spring_last(season: int, tun) -> date:
    return date(season, *tun.post_spring_last)


def _logs(apps, area: str, start: date, end: Optional[date] = None) -> list:
    return sorted((a for a in for_area(apps, area, ("herbicide",))
                   if is_post_emergent(a) and a.date >= start
                   and (end is None or a.date < end)), key=lambda a: a.date)


def _track_logs(w: Window, apps) -> None:
    """The first post-emergent logged since the window opened (it stays open)."""
    opened = w.reached_on("open")
    logs = _logs(apps, w.area, opened, w.closed) if opened else []
    w.done = logs[0].date if logs else None
    w.product = logs[0].product if logs else ""


def _end(w: Window, on: date, today: date) -> None:
    """Close the window on `on` (the first day it's no longer open)."""
    w.closed, w.projected = on, None
    _reach(w, "closed", on, w.source, w.value, w.area)
    _set_status(w, "done" if w.done else "closed", today)


def heat_close_in(highs, tun) -> Optional[int]:
    """Days from today until the spring window's heat close: the first day whose next
    N forecast highs reach the limit on enough days. 0 = today. None when the
    forecast doesn't show it."""
    n, need, limit = tun.post_heat_close_window, tun.post_heat_close_days, tun.post_heat_close_f
    for start in range(0, max(0, len(highs) - need + 1)):
        ahead = highs[start:start + n]
        if sum(1 for h in ahead if h >= limit) >= need:
            return start
    return None


def _update_spring(w: Window, today: date, a, lawn, apps, tun) -> Window:
    w = w.copy()
    last = spring_last(w.season, tun)
    active = date(w.season, 1, 1) <= today <= last
    if active:
        if a.soil5 is not None:
            w.source, w.value = "geodrops", a.soil5
        elif lawn.gdd is not None:
            w.source, w.value = "gdd", lawn.gdd
        else:
            w.source, w.value = "", None
        w.set_by = a.key
    _track_logs(w, apps)
    if w.status in ENDED:
        return w
    if today > last:
        _end(w, last + _DAY, today)
        return w

    if "open" not in w.reached:
        threshold = (tun.post_spring_open_soil_f if w.source == "geodrops"
                     else tun.post_spring_open_gdd)
        if w.value is not None and w.value >= threshold:
            _reach(w, "open", today, w.source, w.value, a.key)
    if "open" in w.reached:
        w.projected = None
        heat = heat_close_in(lawn.highs, tun)
        if heat == 0:
            _end(w, today, today)
            return w
        w.expected_close = min(last, today + timedelta(days=heat - 1)) if heat else last
        _set_status(w, "open", today)
        return w

    limit = tun.forecast_horizon_days
    if w.source == "geodrops":
        days = trend_cross(a.soil5, a.soil_slope, tun.post_spring_open_soil_f, rising=True,
                           limit=limit)
    elif w.source == "gdd":
        days = gdd_cross(lawn.gdd, lawn.horizon[:limit], tun.gdd_base_f,
                         tun.post_spring_open_gdd)
    else:
        days = None
    w.projected = today + timedelta(days=days) if days is not None else None
    _set_status(w, "projected" if w.projected else "tentative", today)
    return w


def _update_fall(w: Window, today: date, a, lawn, apps, tun) -> Window:
    w = w.copy()
    start = date(w.season, *tun.post_fall_from)
    active = start <= today
    t7 = _mean(a.air_means[-7:])
    w.source, w.value, w.set_by = "air", t7, a.key
    _track_logs(w, apps)
    if w.status in ENDED:
        return w
    cold = t7 is not None and t7 < tun.post_fall_close_air_t7_f
    if "open" not in w.reached and active and not cold \
            and t7 is not None and t7 <= tun.post_fall_open_air_t7_f:
        _reach(w, "open", today, "air", t7, a.key)
    horizon = lawn.horizon[:tun.forecast_horizon_days]
    if "open" in w.reached:
        if a.dormant or cold:
            _end(w, today, today)
            return w
        w.projected = None
        n = t7_cross(a.air_means, horizon, lambda v: v < tun.post_fall_close_air_t7_f)
        w.expected_close = today + timedelta(days=n - 1) if n else None
        _set_status(w, "open", today)
        return w
    if active and cold:
        _end(w, today, today)             # closed before it was seen open (silently)
        return w
    n = (t7_cross(a.air_means, horizon, lambda v: v <= tun.post_fall_open_air_t7_f)
         if active else None)
    w.projected = today + timedelta(days=n) if n else None
    _set_status(w, "projected" if w.projected else "tentative", today)
    return w


def crabgrass_trigger(pre: Optional[Window]) -> Optional[dict]:
    """The pre-emergent's "germination expected" info when young crabgrass is likely:
    germination was reached and no pre-emergent went down before it."""
    if pre is None or "germination" not in pre.reached:
        return None
    germination = pre.reached_on("germination")
    if pre.done is not None and pre.done < germination:
        return None
    return pre.reached["germination"]


def _update_crabgrass(w: Optional[Window], today: date, area: str, season: int,
                      pre: Optional[Window], apps, tun) -> Optional[Window]:
    """None: no young-crabgrass window for this area (the pre-emergent did its job,
    or germination isn't expected yet, and nothing was flagged)."""
    info = crabgrass_trigger(pre)
    if w is None and info is None:
        return None
    w = (w or Window(CRABGRASS, season, area)).copy()
    opens = None
    if info is not None:
        opens = date.fromisoformat(info["date"]) + timedelta(days=tun.post_crabgrass_after_days)
    if w.flagged and (opens is None or w.flagged < opens):
        opens = w.flagged
    if opens is None and "open" not in w.reached:
        return None
    if info is not None and not w.flagged:
        w.source, w.value, w.set_by = info.get("source", ""), info.get("value"), area
    _track_logs(w, apps)
    if w.status in ENDED:
        return w
    if "open" not in w.reached:
        if today < opens:
            w.projected = opens
            w.expected_close = opens + timedelta(days=tun.post_crabgrass_days - 1)
            _set_status(w, "projected", today)
            return w
        _reach(w, "open", opens, w.source, w.value, area)
    w.projected = None
    close = w.reached_on("open") + timedelta(days=tun.post_crabgrass_days)
    w.expected_close = close - _DAY
    if today >= close:
        _end(w, close, today)
        return w
    _set_status(w, "open", today)
    return w


def update_all(windows: dict, lawn, areas, apps, tun) -> dict:
    """Advance every area's post-emergent windows for today (after windows.update_all,
    so the pre-emergent's germination stage is current). Windows of an earlier year
    still open close at the year's end."""
    today = lawn.today
    out = dict(windows)
    for key, w in windows.items():
        if w.kind in POST_KINDS and w.season < today.year and w.status not in ENDED:
            w = w.copy()
            _track_logs(w, apps)
            _end(w, date(w.season + 1, 1, 1), today)
            out[key] = w
    pre = windows.get(window_key("pre_emergent", today.year, LAWN))
    for a in areas:
        for kind, fn in ((SPRING, _update_spring), (FALL, _update_fall)):
            key = window_key(kind, today.year, a.key)
            out[key] = fn(out.get(key) or Window(kind, today.year, a.key), today, a,
                          lawn, apps, tun)
        key = window_key(CRABGRASS, today.year, a.key)
        w = _update_crabgrass(out.get(key), today, a.key, today.year, pre, apps, tun)
        if w is None:
            out.pop(key, None)
        else:
            out[key] = w
    return out


def area_windows(windows: dict, area: str, season: int) -> list:
    return [w for k in POST_KINDS
            if (w := windows.get(window_key(k, season, area))) is not None]


def open_windows(windows: dict, area: str, today: date) -> list:
    return [w for w in area_windows(windows, area, today.year) if w.status == "open"]


def _upcoming_date(w: Window, today: date, tun) -> date:
    return w.projected or max(typical_date(w.kind, w.season, tun), today)


def current(windows: dict, area: str, today: date, tun) -> Optional[Window]:
    """The window the Post-emergent sensor shows: the open one (earliest opened),
    else the next to open, else the one that ended last."""
    ws = area_windows(windows, area, today.year)
    opened = sorted((w for w in ws if w.status == "open"), key=lambda w: w.reached_on("open"))
    if opened:
        return opened[0]
    upcoming = sorted((w for w in ws if w.status in UPCOMING),
                      key=lambda w: _upcoming_date(w, today, tun))
    if upcoming:
        return upcoming[0]
    ended = sorted((w for w in ws if w.status in ENDED),
                   key=lambda w: w.closed or w.skipped or date.min)
    return ended[-1] if ended else None


def flag(windows: dict, area: str, target: str, today: date, tun) -> Window:
    """flag_weeds: open the target's window for this area today. Broadleaf flags the
    spring window through its last day, the fall window after. A window already
    open stays as it is; a skipped one reopens. Raises WindowEnded when the window
    already closed this season."""
    kinds = TARGETS[target]
    if target == "broadleaf" and today > spring_last(today.year, tun):
        kinds = (FALL,)
    for kind in kinds:
        w = windows.get(window_key(kind, today.year, area)) or Window(kind, today.year, area)
        if w.status in ("done", "closed"):
            continue
        w = w.copy()
        if w.status == "open":
            return w
        w.skipped, w.projected = None, None
        w.flagged = today
        if "open" not in w.reached:
            w.source, w.value, w.set_by = "flag", None, area
            _reach(w, "open", today, "flag", None, area)
        w.notified = list(dict.fromkeys([*w.notified, "open"]))   # the user knows
        _set_status(w, "open", today)
        return w
    raise WindowEnded(target)


def skip(windows: dict, area: str, today: date, tun) -> list:
    """skip_application for post-emergent: every open window of the area, else the
    next one to open. Returns the changed windows."""
    from .windows import skip as skip_window
    targets = open_windows(windows, area, today)
    if not targets:
        upcoming = sorted((w for w in area_windows(windows, area, today.year)
                           if w.status in UPCOMING),
                          key=lambda w: _upcoming_date(w, today, tun))
        targets = upcoming[:1]
    return [skip_window(w, today) for w in targets]


# --- after a spray: mowing hold and follow-up ---------------------------------------

def no_mow_until(app_date: date, tun) -> date:
    """The first day mowing is fine again after a post-emergent on `app_date`."""
    return app_date + timedelta(days=tun.post_no_mow_days)


def hold_until(apps, area: str, today: date, tun) -> Optional[date]:
    """D15: Mowing allowed is held for the area until this date (exclusive) after
    its latest post-emergent; None when no hold applies today."""
    if not tun.post_hold_mowing:
        return None
    dates = [a.date for a in for_area(apps, area, ("herbicide",))
             if is_post_emergent(a) and a.date <= today]
    if not dates:
        return None
    until = no_mow_until(max(dates), tun)
    return until if today < until else None


@dataclass(frozen=True)
class FollowUp:
    app: object                 # the Application
    due: date

    @property
    def key(self) -> str:
        return f"{self.app.product}:{self.app.date.isoformat()}:{'+'.join(self.app.areas)}"


def followups(apps, tun) -> list:
    """Follow-up reminders: logged date + the product's follow-up days (0: none)."""
    out = []
    for a in apps:
        days = followup_days(a.product, tun) if is_post_emergent(a) else 0
        if days > 0:
            out.append(FollowUp(a, a.date + timedelta(days=days)))
    return out


def superseded(f: FollowUp, apps) -> bool:
    """A later post-emergent on every one of its areas already did the follow-up."""
    return all(any(is_post_emergent(b) and area in b.areas and f.app.date < b.date <= f.due
                   for b in apps) for area in f.app.areas)


# --- the spray-day check ------------------------------------------------------------

@dataclass(frozen=True)
class SprayContext:
    """One area's state for the spray-day check (built by the coordinator)."""
    product: str
    last_mow: Optional[date] = None
    mow_due: bool = False
    days_until_due: Optional[int] = None
    dormant: bool = False
    heat_hold: dict = None                   # date -> bool
    water_factor: float = 1.0
    seeding_date: Optional[date] = None
    seedlings_ready: bool = False
    ready_on: Optional[date] = None
    mows: tuple = ()                         # mow dates


@dataclass(frozen=True)
class SprayDay:
    day: date
    good: bool
    failed: tuple = ()          # CHECKS that failed
    skipped: tuple = ()         # CHECKS the forecast couldn't answer
    reasons: tuple = ()         # one line per failed check
    mow_first: bool = False     # only the mowing check failed: a mow is due soon

    def to_dict(self) -> dict:
        return {"date": self.day.isoformat(), "good": self.good,
                "failed": list(self.failed), "not_checked": list(self.skipped),
                "reasons": list(self.reasons)}


def seedling_check(product: str, ctx: SprayContext, day: date, tun) -> Optional[str]:
    """None when the product may go on this area's grass; else why not."""
    if ctx.seeding_date is not None and not ctx.seedlings_ready:
        return (f"new seedlings (seeded {fmt_day(ctx.seeding_date)}): wait for "
                f"Seedlings ready")
    need = seedling_mows(product, tun)
    since = ctx.ready_on or (ctx.seeding_date if ctx.seedlings_ready else None)
    if need <= 0 or since is None or (day - since).days > tun.post_seeding_relevant_days:
        return None
    mows = sum(1 for m in ctx.mows if since <= m <= day)
    if mows >= need:
        return None
    return (f"{product_label(product)} needs {need} mows after Seedlings ready "
            f"({mows} so far)")


def spray_day(day: date, today: date, ctx: SprayContext, fc, tun) -> SprayDay:
    """Is `day` (today or tomorrow) a good day to spray this area? Each check whose
    forecast field is missing is skipped and named."""
    failed, skipped, reasons = [], [], []

    def fail(check, reason):
        failed.append(check)
        reasons.append(reason)

    # 1. temperature: high within range; a heat-limited product also checks the next day
    limit = heat_limit_f(ctx.product, tun)
    high = fc.high_f(day)
    if high is None:
        skipped.append("temperature")
    elif high < tun.spray_min_high_f:
        fail("temperature", f"high {high:.0f} °F (below {tun.spray_min_high_f:.0f} °F)")
    elif high > limit:
        fail("temperature", f"high {high:.0f} °F (limit {limit:.0f} °F)")
    elif limit < tun.spray_max_high_f:
        after = fc.high_f(day + _DAY)
        if after is not None and after > limit:
            fail("temperature", f"next day's high {after:.0f} °F (limit {limit:.0f} °F "
                                f"for {product_label(ctx.product)})")

    # 2. rain-free after a morning application: hourly probability, else daily
    start = datetime(day.year, day.month, day.day, tun.spray_start_hour)
    end = start + timedelta(hours=rainfree_hours(ctx.product, tun))
    pops = [h.rain_pct for h in fc.hours if start <= h.when < end and h.rain_pct is not None]
    if not pops:
        info = fc.days.get(day)
        pops = [info.rain_pct] if info is not None and info.rain_pct is not None else []
    if not pops:
        skipped.append("rain")
    elif max(pops) >= tun.spray_max_rain_pct:
        fail("rain", f"rain chance {max(pops):.0f}% within "
                     f"{rainfree_hours(ctx.product, tun)} h")

    # 3. wind in the morning, from the hourly forecast
    first, last = tun.spray_morning_hours
    winds = [h.wind_mph for h in fc.hours if h.when.date() == day
             and first <= h.when.hour < last and h.wind_mph is not None]
    if not winds:
        skipped.append("wind")
    elif max(winds) >= tun.spray_max_wind_mph:
        fail("wind", f"wind up to {max(winds):.0f} mph in the morning")

    # 4. mowing: none in the last N days, none due in the next N
    gap = tun.spray_mow_gap_days
    mow_first = False
    if ctx.last_mow is not None and (day - ctx.last_mow).days < gap:
        fail("mowing", f"mowed {fmt_day(ctx.last_mow)}: wait {gap} days after mowing")
    else:
        due_in = (0 if ctx.mow_due else ctx.days_until_due)
        offset = (day - today).days
        if due_in is not None and due_in - offset <= gap:
            fail("mowing", f"a mow is due soon: mow first, spray {gap} days later")
            mow_first = True

    # 5. grass not stressed
    if ctx.dormant:
        fail("stress", "dormant")
    elif (ctx.heat_hold or {}).get(day):
        fail("stress", "heat stress")
    elif ctx.water_factor < tun.spray_min_water_factor:
        fail("stress", "soil dry")

    # 6. the product's seedling rule
    why = seedling_check(ctx.product, ctx, day, tun)
    if why:
        fail("seedlings", why)

    return SprayDay(day, not failed, tuple(failed), tuple(skipped), tuple(reasons),
                    mow_first and failed == ["mowing"])
