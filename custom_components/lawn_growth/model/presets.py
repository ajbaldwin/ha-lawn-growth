"""Grass-type presets: growth curve + reference cut heights. Pure Python.

Heights are typical university-extension ranges; every value is editable per area.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import AreaConfig

CURVES = {"cool": (68.0, 10.0), "warm": (88.0, 12.0)}
DEFAULT_PRESET = "tttf_kbg"


@dataclass(frozen=True)
class Preset:
    key: str
    curve: str
    cut_min_in: float
    cut_max_in: float
    overseed_target_in: Optional[float]


PRESETS = {p.key: p for p in (
    Preset("tttf_kbg", "cool", 3.0, 4.0, 2.5),
    Preset("kbg", "cool", 2.5, 3.5, 2.0),
    Preset("ryegrass", "cool", 2.0, 3.0, 2.0),
    Preset("fine_fescue", "cool", 2.5, 4.0, 2.0),
    Preset("bermuda_zoysia", "warm", 1.0, 2.0, None),
    Preset("st_augustine", "warm", 2.5, 4.0, None),
    Preset("custom", "cool", 3.0, 4.0, 2.5),
)}


def area_from_options(opts: dict) -> AreaConfig:
    """Build an AreaConfig from one entry.options['areas'] dict."""
    curve = opts["curve"]
    opt_f, spread_f = CURVES[curve]
    target = opts.get("overseed_target_in")
    return AreaConfig(
        key=opts["key"],
        name=opts["name"],
        grass=opts["grass"],
        curve=curve,
        opt_temp_f=opt_f,
        temp_spread_f=spread_f,
        cut_min_in=float(opts["cut_min_in"]),
        cut_max_in=float(opts["cut_max_in"]),
        overseed_target_in=float(target) if target and curve == "cool" else None,
        wilting_moisture=float(opts.get("wilting_moisture", 40.0)),
        comfortable_moisture=float(opts.get("comfortable_moisture", 67.0)),
        max_growth_rate_mm=float(opts.get("max_growth_rate_mm", 6.5)),
    )
