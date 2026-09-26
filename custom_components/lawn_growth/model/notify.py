"""Which pushes to send after an evaluation (deduplicated via AreaState). Pure Python."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

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

    if result.mode == "first_mow_ready" and not s.ready_notified:
        out.append(Message(TITLE, f"{name}: first mow ready — cut at "
                                  f"{result.first_mow_target_in:.2f}″."))
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
