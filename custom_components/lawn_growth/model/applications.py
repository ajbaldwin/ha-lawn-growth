"""The application log (400 days) and herbicide products. Pure Python.

Separate from the 35-day growth-model events: those only feed the fertilizer and
PGR curves, while this log is the history the application calendar, the seeding
conflict check and the window state machines read.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

LOG_KINDS = ("fert", "pgr", "winterizer", "herbicide", "seeding")


@dataclass(frozen=True)
class Product:
    key: str
    label: str
    pre_emergent: bool          # a blanket pre-emergent: logging it closes the window
    post_emergent: bool
    block_field: str = ""       # Tunables field: days seeding is blocked after it
    # Post-emergent label settings (Tunables fields; empty: none)
    rainfree_field: str = ""    # hours with no rain after spraying
    heat_field: str = ""        # a lower heat limit than the spray-day default
    followup_field: str = ""    # days to a follow-up reminder (0: off)
    seedling_field: str = ""    # mows after Seedlings ready before it may go on
    # Pre-emergent label settings: days and mows after seeding before it may go on
    new_turf_days_field: str = ""
    new_turf_mows_field: str = ""


# Label settings live in Tunables ("other" products' are placeholders).
PRODUCTS = {p.key: p for p in (
    Product("prodiamine", "Prodiamine", True, False, "prodiamine_seeding_block_days",
            new_turf_days_field="prodiamine_new_turf_days",
            new_turf_mows_field="prodiamine_new_turf_mows"),
    Product("dithiopyr", "Dithiopyr", True, False, "dithiopyr_seeding_block_days"),
    Product("mesotrione", "Mesotrione", False, True,
            rainfree_field="mesotrione_rainfree_hours"),
    Product("triclopyr_ester", "Triclopyr ester", False, True,
            "triclopyr_ester_seeding_block_days", "triclopyr_ester_rainfree_hours",
            "triclopyr_ester_heat_limit_f", "triclopyr_ester_followup_days",
            "triclopyr_ester_seedling_mows"),
    Product("other_pre_emergent", "Other pre-emergent", True, False,
            "other_pre_emergent_seeding_block_days"),
    Product("other_post_emergent", "Other post-emergent", False, True,
            "other_post_emergent_seeding_block_days", "other_post_emergent_rainfree_hours",
            "", "other_post_emergent_followup_days", "other_post_emergent_seedling_mows"),
)}
PRE_EMERGENT_PRODUCTS = tuple(k for k, p in PRODUCTS.items() if p.pre_emergent)
POST_EMERGENT_PRODUCTS = tuple(k for k, p in PRODUCTS.items() if p.post_emergent)


def product_label(key: str) -> str:
    p = PRODUCTS.get(key)
    return p.label if p else key


def _setting(product: str, attr: str, tun, default=0):
    p = PRODUCTS.get(product)
    name = getattr(p, attr) if p else ""
    return getattr(tun, name) if name else default


def block_days(product: str, tun) -> int:
    return int(_setting(product, "block_field", tun))


def rainfree_hours(product: str, tun) -> int:
    return int(_setting(product, "rainfree_field", tun, 24))


def heat_limit_f(product: str, tun) -> float:
    """The highest forecast high a spray day allows for this product."""
    return min(tun.spray_max_high_f,
               float(_setting(product, "heat_field", tun, tun.spray_max_high_f)))


def followup_days(product: str, tun) -> int:
    return int(_setting(product, "followup_field", tun))


def seedling_mows(product: str, tun) -> int:
    return int(_setting(product, "seedling_field", tun))


def new_turf_wait(product: str, seeded: Optional[date], mows, day: date,
                  tun) -> Optional[str]:
    """None when this pre-emergent may go on grass seeded on `seeded`; else why not.
    `mows` are the area's mow dates; only those after the seeding count."""
    days = int(_setting(product, "new_turf_days_field", tun))
    need = int(_setting(product, "new_turf_mows_field", tun))
    if (days <= 0 and need <= 0) or seeded is None or seeded > day             or (day - seeded).days > tun.post_seeding_relevant_days:
        return None
    elapsed = (day - seeded).days
    done = sum(1 for m in mows if seeded < m <= day)
    if elapsed >= days and done >= need:
        return None
    return (f"the label says to wait {days} days and {need} mows after seeding (seeded "
            f"{fmt_day(seeded)}: {elapsed} day{'' if elapsed == 1 else 's'}, {done} mow{'' if done == 1 else 's'} "
            f"so far)")


@dataclass(frozen=True)
class Application:
    kind: str                   # LOG_KINDS
    date: date
    areas: tuple                # area keys
    product: str = ""           # herbicide only

    def to_dict(self) -> dict:
        out = {"kind": self.kind, "date": self.date.isoformat(), "areas": list(self.areas)}
        if self.product:
            out["product"] = self.product
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "Application":
        return cls(d["kind"], date.fromisoformat(d["date"]), tuple(d.get("areas", ())),
                   d.get("product", ""))


def prune(apps: list, today: date, retention_days: int) -> list:
    cutoff = today - timedelta(days=retention_days)
    return [a for a in apps if a.date >= cutoff]


def is_pre_emergent(app: Application) -> bool:
    return app.kind == "herbicide" and app.product in PRE_EMERGENT_PRODUCTS


def is_post_emergent(app: Application) -> bool:
    return app.kind == "herbicide" and app.product in POST_EMERGENT_PRODUCTS


def for_area(apps, area: str, kinds=None) -> list:
    return [a for a in apps if area in a.areas and (kinds is None or a.kind in kinds)]


def latest(apps, area: str, kinds) -> Optional[date]:
    dates = [a.date for a in for_area(apps, area, kinds)]
    return max(dates) if dates else None


@dataclass(frozen=True)
class SeedingBlock:
    product: str
    applied: date
    until: date                 # first day seeding is no longer blocked

    def text(self) -> str:
        return (f"{product_label(self.product)} applied {fmt_day(self.applied)} — "
                f"seeding blocked until {fmt_day(self.until)}")


def seeding_block(apps, area: str, day: date, tun) -> Optional[SeedingBlock]:
    """The herbicide block covering `day` on this area: of the logged products whose
    wait-before-seeding period includes the day, the one that ends last."""
    best = None
    for a in for_area(apps, area, ("herbicide",)):
        days = block_days(a.product, tun)
        if days <= 0:
            continue
        until = a.date + timedelta(days=days)
        if a.date <= day < until and (best is None or until > best.until):
            best = SeedingBlock(a.product, a.date, until)
    return best


def fmt_day(d: date) -> str:
    return f"{d:%b} {d.day}"
