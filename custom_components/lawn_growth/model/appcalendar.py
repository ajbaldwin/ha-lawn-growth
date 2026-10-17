"""The application calendar: windows and logged applications as all-day events.
Pure Python.

`calendar_events(state)` is the one builder, shared by Lawn Growth's calendar entity
and the calendar writer (model/calwriter.py). Each event has a stable key,
`lawn_growth-{kind}-{season}-{area|all}-{event}`, which doesn't change when a
projection moves. Events of the same kind and status on the same date across areas
merge into one ("Apply winterizer — Front & Side, Back"). `firm` marks events whose
date is final (a window opening, a logged application); projections are not firm.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from .applications import (PRODUCTS, fmt_day, is_post_emergent, is_pre_emergent,
                           product_label, seeding_block)
from .postemergent import LABELS, followups, no_mow_until
from .windows import LAWN, POST_KINDS, split_reminder_date, typical_date

_DAY = timedelta(days=1)
_SOURCES = {"geodrops": "GeoDrops soil probes",
            "gdd": "growing degree days (estimated from air temperatures)",
            "air": "air temperatures, 7-day mean (estimated)",
            "flag": "weeds flagged (lawn_growth.flag_weeds)"}
_LOG_LABELS = {"fert": "Fertilizer", "pgr": "PGR", "winterizer": "Winterizer",
               "seeding": "Seeding", "mow": "Mow"}
_SEEDING_NOTE = ("Note: mesotrione at seeding keeps many weeds out of new grass "
                 "without harming the seedlings.")


@dataclass(frozen=True)
class CalEvent:
    key: str
    kind: str
    summary: str
    description: str
    start: date
    end: date                   # exclusive
    firm: bool = False
    season: int = 0
    event: str = ""             # the key's last part: open, late, applied-<date>, ...
    areas: tuple = ()           # the areas it covers (a whole-lawn log lists each one)
    title: str = ""             # the summary before the area label


@dataclass(frozen=True)
class AreaCalendar:
    name: str
    planned_seed: Optional[date] = None     # prep_overseed's seed date
    earliest_seed: Optional[date] = None    # earliest seed date prep can reach from today
    prep_days: Optional[int] = None         # days the overseed descent needs
    buffer_days: int = 7


@dataclass(frozen=True)
class CalendarState:
    today: date
    tunables: object
    windows: dict                           # key -> windows.Window
    applications: tuple = ()                # applications.Application
    areas: dict = field(default_factory=dict)   # key -> AreaCalendar, configured order
    mows: tuple = ()                        # (date, area key)


@dataclass
class _Raw:
    kind: str
    season: int
    area: str
    event: str
    summary: str
    description: str
    start: date
    end: date
    firm: bool
    status: str = ""


def _signal(source: str, value, area: str, names: dict) -> str:
    if source == "flag":
        return "weeds flagged"
    if value is None:
        return "no signal yet"
    if source == "geodrops":
        return f"soil {value:.1f} °F" + (f" ({names[area]})" if area in names else "")
    if source == "gdd":
        return f"{value:.0f} growing degree days"
    return f"7-day air mean {value:.1f} °F"


def _describe(w, names: dict, *, info: Optional[dict] = None, extra=()) -> str:
    source, value, area = ((info.get("source", ""), info.get("value"), info.get("area", ""))
                           if info else (w.source, w.value, w.set_by))
    lines = [f"Status: {w.status}"]
    if source:
        lines += [f"Trigger: {_signal(source, value, area, names)}",
                  f"Source: {_SOURCES.get(source, source)}"]
    lines += [line for line in extra if line]
    if w.updated:
        lines.append(f"Updated: {w.updated.isoformat()}")
    return "\n".join(lines)


def _open_end(w, opened: date, today: date) -> date:
    """Exclusive end of an open window's span."""
    if w.status == "done" and w.done:
        end = w.done
    elif w.status == "skipped" and w.skipped:
        end = w.skipped
    elif w.status == "missed" and w.closed:
        end = w.closed
    elif w.expected_close:
        end = max(w.expected_close, today) + _DAY
    else:
        end = today + _DAY
    return max(opened + _DAY, end)


def _window_events(w, state: CalendarState, names: dict) -> list:
    tun, today = state.tunables, state.today
    title = {"pre_emergent": "Pre-emergent", "winterizer": "Winterizer",
             "overseed": "Overseed"}[w.kind]
    area_cal = state.areas.get(w.area)
    out = []

    def add(event, summary, start, end=None, *, firm, description, status=w.status):
        out.append(_Raw(w.kind, w.season, w.area, event, summary, description, start,
                        end or start + _DAY, firm, status))

    extra = []
    if w.kind == "overseed" and area_cal is not None:
        if overseed_ideal_now(w, tun):
            extra.append("Ideal: soil is 60–70 °F")
        if area_cal.earliest_seed and w.status in ("projected", "open"):
            extra.append(f"Earliest seed date overseed prep can reach from today: "
                         f"{fmt_day(area_cal.earliest_seed)}")
        block = seeding_block(state.applications, w.area,
                              area_cal.planned_seed or today, tun)
        if block:
            extra.append(block.text())

    planned = area_cal.planned_seed if (w.kind == "overseed" and area_cal) else None
    if w.status in ("tentative", "projected") and not planned:
        if w.status == "tentative":
            add("window", f"{title} (estimated)", max(typical_date(w.kind, w.season, tun),
                                                     today),
                firm=False, description=_describe(w, names, extra=extra))
        else:
            add("window", f"{title} window ~{fmt_day(w.projected)}", w.projected,
                firm=False, description=_describe(w, names, extra=extra))

    opened = w.reached_on("open")
    if opened is not None and not (w.kind == "overseed" and planned):
        summary = {"pre_emergent": "Apply pre-emergent", "winterizer": "Apply winterizer",
                   "overseed": "Overseed window"}[w.kind]
        add("open", summary, opened, _open_end(w, opened, today), firm=True,
            description=_describe(w, names, info=w.reached.get("open"), extra=extra))
    late = w.reached_on("late")
    if w.kind == "pre_emergent" and late and not (w.done and w.done <= late):
        add("late", "Pre-emergent late — apply now", late, firm=True,
            description=_describe(w, names, info=w.reached.get("late")))
    if w.status == "missed" and w.closed:
        add("missed", f"{title} window missed", w.closed, firm=True,
            description=_describe(w, names))

    if w.kind == "pre_emergent":
        reminder = split_reminder_date(w, state.applications, tun)
        if reminder is not None:
            add("split", "Second pre-emergent (dithiopyr)", reminder, firm=True,
                status="split",
                description=(f"Split application: {product_label(w.product)} went down "
                             f"{fmt_day(w.done)}; dithiopyr now extends crabgrass "
                             f"control."))

    if w.kind == "overseed" and area_cal is not None and w.status in ("projected", "open"):
        if planned:
            add("seed", "Overseed — seed date", planned, firm=False,
                description=_describe(w, names, extra=extra))
        elif area_cal.prep_days is not None:
            window_day = w.projected or today
            start = max(today, window_day - timedelta(days=area_cal.prep_days
                                                      + area_cal.buffer_days))
            add("prep", "Start overseed prep", start, firm=False,
                description=("Run Prepare for overseeding (lawn_growth.prep_overseed) with "
                             "your seed date to step the cut height down.\n"
                             + _describe(w, names, extra=extra)))
    return out


def _post_window_events(w, state: CalendarState, names: dict) -> list:
    """A post-emergent window: estimated or projected while upcoming; once open, one
    span from the open day to its close (it stays open through applications)."""
    tun, today = state.tunables, state.today
    label = LABELS[w.kind]
    out = []

    def add(event, summary, start, end=None, *, firm, description):
        out.append(_Raw(w.kind, w.season, w.area, event, summary, description, start,
                        end or start + _DAY, firm, w.status))

    if w.status == "tentative":
        add("window", f"Post-emergent (estimated, {label})",
            max(typical_date(w.kind, w.season, tun), today), firm=False,
            description=_describe(w, names))
    elif w.status == "projected" and w.projected:
        add("window", f"Post-emergent window ~{fmt_day(w.projected)} ({label})",
            w.projected, firm=False, description=_describe(w, names))
    opened = w.reached_on("open")
    if opened is not None:
        if w.closed:
            end = w.closed
        elif w.status == "skipped" and w.skipped:
            end = w.skipped
        elif w.expected_close:
            end = max(w.expected_close, today) + _DAY
        else:
            end = today + _DAY
        extra = [f"Applied: {product_label(w.product)} {fmt_day(w.done)}"
                 if w.done else ""]
        add("open", f"Post-emergent window open ({label})", opened,
            max(opened + _DAY, end), firm=True,
            description=_describe(w, names, info=w.reached.get("open"), extra=extra))
    return out


def _followup_events(state: CalendarState) -> list:
    out = []
    for f in followups(state.applications, state.tunables):
        for area in f.app.areas:
            if area in state.areas:
                out.append(_Raw(f.app.product, f.due.year, area,
                                f"followup-{f.app.date.isoformat()}",
                                "Post-emergent follow-up",
                                f"{product_label(f.app.product)} went down "
                                f"{fmt_day(f.app.date)}; a second application finishes "
                                f"off the weeds that survived.",
                                f.due, f.due + _DAY, True, "followup"))
    return out


def overseed_ideal_now(w, tun) -> bool:
    return (w.source == "geodrops" and w.value is not None
            and tun.overseed_ideal_low_f <= w.value <= tun.overseed_open_soil_f)


def _log_events(state: CalendarState) -> list:
    tun = state.tunables
    configured = list(state.areas)
    out = []
    for app in state.applications:
        if app.kind == "herbicide":
            product = PRODUCTS.get(app.product)
            spot = product is not None and product.post_emergent and not product.pre_emergent
            summary = product_label(app.product) + (" spot" if spot else "")
            kind = app.product or "herbicide"
            lines = []
            if is_pre_emergent(app):
                lines.append("Pre-emergent applied.")
            blocks = {a: seeding_block(state.applications, a, app.date, tun)
                      for a in app.areas}
            mine = [b for b in blocks.values()
                    if b and b.applied == app.date and b.product == app.product]
            if mine:
                lines.append(f"Seeding blocked until {fmt_day(mine[0].until)}.")
            if is_post_emergent(app):
                lines.append(f"Don't mow until {fmt_day(no_mow_until(app.date, tun))}.")
            description = " ".join(lines)
        else:
            summary, kind = _LOG_LABELS.get(app.kind, app.kind), app.kind
            description = _SEEDING_NOTE if app.kind == "seeding" else ""
        areas = [a for a in configured if a in app.areas]
        if not areas:
            continue
        whole = len(configured) > 1 and len(areas) == len(configured)
        for area in ([LAWN] if whole else areas):
            out.append(_Raw(kind, app.date.year, area, f"applied-{app.date.isoformat()}",
                            summary, description, app.date, app.date + _DAY, True,
                            "applied"))
    if tun.calendar_show_mows:
        for day, area in state.mows:
            if area in state.areas:
                out.append(_Raw("mow", day.year, area, f"applied-{day.isoformat()}", "Mow",
                                "", day, day + _DAY, True, "applied"))
    return out


def _merge(raws: list, state: CalendarState, names: dict) -> list:
    order = {k: i for i, k in enumerate([LAWN, *state.areas])}
    groups: dict = {}
    for r in raws:
        groups.setdefault((r.kind, r.event, r.status, r.start, r.summary), []).append(r)
    events = []
    for (kind, event, _, start, summary), rs in groups.items():
        areas = sorted({r.area for r in rs}, key=lambda a: order.get(a, len(order)))
        whole = (event.startswith("applied-") and len(state.areas) > 1
                 and set(areas) >= set(state.areas))
        if event.startswith("applied-") and LAWN in areas:
            whole = True
        members = tuple(state.areas) if whole else tuple(areas)
        if LAWN in areas or whole:
            areas = [LAWN]
        season = rs[0].season
        key = f"lawn_growth-{kind}-{season}-{'+'.join(areas)}-{event}"
        if areas == [LAWN]:
            label = "" if kind == "pre_emergent" else " — whole lawn"
            # one lawn-wide event; same-day lawn-wide logs of one kind collapse
            description = rs[0].description
        else:
            label = " — " + ", ".join(names.get(a, a) for a in areas)
            seen, parts = set(), []
            for r in sorted(rs, key=lambda r: order.get(r.area, len(order))):
                if r.area in seen or not r.description:
                    continue
                seen.add(r.area)
                parts.append(r.description if len(areas) == 1
                             else f"{names.get(r.area, r.area)}:\n{r.description}")
            description = "\n\n".join(dict.fromkeys(parts)) if len(areas) > 1 else (
                parts[0] if parts else "")
        events.append(CalEvent(key=key, kind=kind, summary=summary + label,
                               description=description, start=start,
                               end=max(r.end for r in rs), firm=all(r.firm for r in rs),
                               season=season, event=event, areas=members, title=summary))
    return sorted(events, key=lambda e: (e.start, e.summary, e.key))


def calendar_events(state: CalendarState) -> list:
    names = {k: a.name for k, a in state.areas.items()}
    raws = []
    for w in state.windows.values():
        if w.kind in POST_KINDS:
            if w.area in state.areas:
                raws += _post_window_events(w, state, names)
        elif w.area == LAWN or w.area in state.areas:
            raws += _window_events(w, state, names)
    raws += _log_events(state)
    raws += _followup_events(state)
    return _merge(raws, state, names)
