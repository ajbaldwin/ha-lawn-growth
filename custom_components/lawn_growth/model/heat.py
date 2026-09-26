"""Heat-stress mow-hold predicate. Pure Python."""
from __future__ import annotations


def heat_hold(high_temp_f: float, moisture: float, wilting: float, comfortable: float,
              tun, warm: bool = False) -> bool:
    """Extreme heat always holds; ordinary heat holds when the soil is also dry.

    "Dry" = at or below the midpoint of the area's wilting..comfortable band, so the
    rule works on any moisture scale. Warm-season grass shifts both thresholds up.
    """
    offset = tun.warm_heat_offset_f if warm else 0.0
    if high_temp_f >= tun.heat_extreme_f + offset:
        return True
    dry = moisture <= (wilting + comfortable) / 2.0
    return high_temp_f >= tun.heat_temp_f + offset and dry
