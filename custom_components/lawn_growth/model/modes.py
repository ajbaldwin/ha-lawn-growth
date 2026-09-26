"""Per-area mode resolution by precedence. Pure Python."""
from __future__ import annotations

MODES = ["out_of_season", "establishment", "first_mow_ready", "dormant", "heat_hold",
         "overseed_prep", "normal"]


def resolve_mode(in_season: bool, establishment: bool, first_mow_ready: bool,
                 dormant: bool, heat_hold: bool) -> str:
    """`overseed_prep` is an overlay applied later by evaluate, never returned here."""
    if not in_season:
        return "out_of_season"
    if establishment:
        return "establishment"
    if first_mow_ready:
        return "first_mow_ready"
    if dormant:
        return "dormant"
    if heat_hold:
        return "heat_hold"
    return "normal"
