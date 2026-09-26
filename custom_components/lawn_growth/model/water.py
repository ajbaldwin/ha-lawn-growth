"""Soil-moisture growth factor. Pure Python."""
from __future__ import annotations


def water_factor(moisture: float, wilting: float, comfortable: float) -> float:
    """0.0 at/below wilting, 1.0 at/above comfortable, linear between."""
    if comfortable <= wilting:
        raise ValueError("comfortable must exceed wilting")
    if moisture <= wilting:
        return 0.0
    if moisture >= comfortable:
        return 1.0
    return (moisture - wilting) / (comfortable - wilting)
