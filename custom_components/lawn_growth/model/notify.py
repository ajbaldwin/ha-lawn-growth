"""Which pushes to send after an evaluation (deduplicated via AreaState). Pure Python."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .applications import fmt_day, product_label
from .windows import FALLBACK_SOURCES, TRANSITIONS, split_reminder_date

TITLE = "Lawn Growth"


@dataclass(frozen=True)
class Message:
    title: str
    message: str


def decide(name: str, result, state, *, today: date, min_interval_days: int):
    s = state.copy()
    out = []
    if result.mow_due and result.mode in ("normal", "heat_hold") and not s.due_notified:
        pct = int(round(result.pct_budget))
        if result.mode == "heat_hold":
            text = (f"{name}: growth budget reached ({pct}%), but hold off — heat stress. "
                    f"If you must, mow early in the morning.")
        else:
            text = (f"{name}: mow due ({pct}% of the growth budget). "
                    f"Cut at {result.next_pass_in:.2f}″.")
        out.append(Message(TITLE, text))
        s.due_notified = True

    if (result.mode == "establishment" and result.seedlings_look_ready
            and not s.ready_notified):
        out.append(Message(TITLE, f"{name}: seedlings look ready for a first mow at "
                                  f"{result.first_mow_target_in:.2f}″. Press Seedlings "
                                  f"ready to allow mowing."))
        s.ready_notified = True

    if result.overseed_active:
        token = text = None
        if not result.overseed_feasible:
            token = f"infeasible:{result.overseed_earliest_date}"
            if result.overseed_earliest_date:
                text = (f"{name} overseed: can't reach {result.overseed_target_in:.2f}″ "
                        f"safely by the seed date. Earliest safe seed date: "
                        f"{result.overseed_earliest_date}.")
            else:
                text = (f"{name} overseed: growth is too vigorous to lower the height "
                        f"safely right now.")
        elif result.overseed_status.startswith("target reached"):
            token = "arrived"
            text = (f"{name} overseed: reached {result.overseed_target_in:.2f}″ — "
                    f"holding until the seed date.")
        elif result.mode == "overseed_prep":
            last = s.last_mow
            if last is None or (today - last).days >= min_interval_days:
                token = f"pass:{last.isoformat() if last else 'start'}"
                text = f"{name} overseed prep: mow now at {result.next_pass_in:.2f}″."
        if token and text and s.overseed.notified != token:
            out.append(Message(f"{TITLE} — overseed", text))
            s.overseed.notified = token
    return out, s


# --- application windows ----------------------------------------------------------

AIR_NOTE = ("Estimated from air temperatures — confirm with a soil thermometer or put "
            "the probes in.")
# Which transitions push, per kind (windows.TRANSITIONS lists them all, in order).
WINDOW_PUSHES = {"pre_emergent": {"heads_up", "open", "late", "germination", "missed"},
                 "winterizer": {"open"},
                 "overseed": {"open", "closing"}}
_TITLES = {"pre_emergent": "pre-emergent", "winterizer": "winterizer",
           "overseed": "overseed"}


def _names(windows, names: dict) -> str:
    return ", ".join(names.get(w.area, w.area) for w in windows)


def _signal(info: dict, names: dict) -> str:
    value = info.get("value")
    if value is None:
        return ""
    if info.get("source") == "geodrops":
        where = f" in {names[info['area']]}" if info.get("area") in names else ""
        return f"soil {value:.1f} °F{where}"
    if info.get("source") == "gdd":
        return f"{value:.0f} growing degree days"
    return f"7-day air mean {value:.1f} °F"


def _pre_text(transition: str, w, names: dict, tun) -> str:
    info = w.reached.get(transition, {})
    signal = _signal(info, names)
    gdd = info.get("source") == "gdd"
    mark = (lambda i: f"{tun.pre_gdd[i]:.0f} GDD") if gdd else (
        lambda i: f"{tun.pre_soil_f[i]:.0f} °F")
    if transition == "heads_up":
        text = (f"Pre-emergent heads-up: {signal}. Time to buy product — the window "
                f"opens at {mark(1)}.")
    elif transition == "open":
        text = (f"Apply pre-emergent now: {signal}. Crabgrass germination is expected "
                f"around {mark(3)}.")
    elif transition == "late":
        text = f"Pre-emergent late — apply now: {signal}. Crabgrass germination is close."
    elif transition == "germination":
        close = fmt_day(w.expected_close) if w.expected_close else "soon"
        text = (f"Crabgrass germination expected ({signal}) and no pre-emergent logged. "
                f"Dithiopyr still controls very young crabgrass — apply by {close}, "
                f"when the window closes.")
    else:
        when = fmt_day(w.closed) if w.closed else "the close date"
        return f"Pre-emergent window missed: nothing logged by {when}."
    return f"{text}\n{AIR_NOTE}" if info.get("source") in FALLBACK_SOURCES else text


def _area_text(kind: str, transition: str, ws, names: dict, blocks: dict) -> str:
    if kind == "winterizer":
        return (f"Winterizer window open — {_names(ws, names)}: growth has wound down "
                f"and the grass is still green. Apply before the ground freezes.")
    if transition == "closing":
        parts = [f"{names.get(w.area, w.area)} (around {fmt_day(w.expected_close)})"
                 if w.expected_close else names.get(w.area, w.area) for w in ws]
        return f"Overseed window closing in about a week — {', '.join(parts)}."
    parts = []
    for w in ws:
        signal = _signal(dict(w.reached.get("open", {}), area=""), names)
        parts.append(f"{names.get(w.area, w.area)} ({signal})" if signal
                     else names.get(w.area, w.area))
    text = f"Overseed window open — {', '.join(parts)}. Best while soil is 60–70 °F."
    for w in ws:
        if blocks.get(w.area):
            text += f"\n{names.get(w.area, w.area)}: {blocks[w.area].text()}."
    if any(w.reached.get("open", {}).get("source") in FALLBACK_SOURCES for w in ws):
        text += f"\n{AIR_NOTE}"
    return text


def decide_windows(windows: dict, names: dict, *, apps, tun, today: date,
                   blocks: dict | None = None):
    """Pushes for window transitions not yet notified: once per transition per window
    per season. Only the latest new transition of a window pushes (a first run in
    late spring doesn't send four pre-emergent alerts); areas crossing the same
    transition on the same run share one message. Done and skipped windows push
    nothing except the split-application reminder."""
    out_windows = {k: w.copy() for k, w in windows.items()}
    pending: dict = {}
    for key, w in out_windows.items():
        if w.kind == "pre_emergent":
            reminder = split_reminder_date(w, apps, tun)
            if reminder is not None and today >= reminder and "split" not in w.notified:
                w.notified.append("split")
                first = product_label(w.product) if w.product else "The first application"
                pending.setdefault(("pre_emergent", "split"), []).append(
                    (w, f"Second pre-emergent due: {first} went down {fmt_day(w.done)}. "
                        f"A split application of dithiopyr keeps crabgrass control "
                        f"going."))
        new = [t for t in TRANSITIONS[w.kind] if t in w.reached and t not in w.notified]
        if not new:
            continue
        w.notified.extend(new)
        if w.status in ("done", "skipped") or new[-1] not in WINDOW_PUSHES[w.kind]:
            continue
        pending.setdefault((w.kind, new[-1]), []).append((w, None))

    messages = []
    for (kind, transition), items in pending.items():
        title = f"{TITLE} — {_TITLES[kind]}"
        if kind == "pre_emergent":
            for w, text in items:
                messages.append(Message(title, text or _pre_text(transition, w, names, tun)))
        else:
            messages.append(Message(title, _area_text(kind, transition,
                                                      [w for w, _ in items], names,
                                                      blocks or {})))
    return messages, out_windows
