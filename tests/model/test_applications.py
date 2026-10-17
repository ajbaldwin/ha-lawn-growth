from datetime import date

from custom_components.lawn_growth.model import applications as ap
from custom_components.lawn_growth.model.applications import Application
from custom_components.lawn_growth.model.config import Tunables

TUN = Tunables()


def _herb(product, on, areas=("front", "back")):
    return Application("herbicide", on, tuple(areas), product)


def test_round_trip_and_prune():
    a = _herb("prodiamine", date(2026, 4, 8))
    assert Application.from_dict(a.to_dict()) == a
    fert = Application("fert", date(2026, 5, 1), ("front",))
    assert "product" not in fert.to_dict()
    old = Application("pgr", date(2025, 1, 1), ("front",))
    assert ap.prune([old, fert], date(2026, 5, 2), 400) == [fert]


def test_products_decide_pre_emergent():
    on = date(2026, 4, 8)
    assert [p for p in ap.PRODUCTS if ap.is_pre_emergent(_herb(p, on))] == [
        "prodiamine", "dithiopyr", "other_pre_emergent"]
    assert not ap.is_pre_emergent(Application("fert", on, ("front",)))
    assert ap.PRE_EMERGENT_PRODUCTS == ("prodiamine", "dithiopyr", "other_pre_emergent")


def test_prodiamine_blocks_seeding_for_16_weeks():
    apps = [_herb("prodiamine", date(2026, 4, 8))]
    block = ap.seeding_block(apps, "back", date(2026, 6, 1), TUN)
    assert block.until == date(2026, 7, 29)
    assert block.text() == "Prodiamine applied Apr 8 — seeding blocked until Jul 29"
    assert ap.seeding_block(apps, "back", date(2026, 7, 29), TUN) is None
    assert ap.seeding_block(apps, "back", date(2026, 4, 7), TUN) is None
    assert ap.seeding_block(apps, "side", date(2026, 6, 1), TUN) is None


def test_mesotrione_never_blocks():
    apps = [_herb("mesotrione", date(2026, 9, 1), ("back",))]
    assert ap.seeding_block(apps, "back", date(2026, 9, 1), TUN) is None


def test_the_block_that_ends_last_wins():
    apps = [_herb("prodiamine", date(2026, 4, 1)),
            _herb("triclopyr_ester", date(2026, 6, 1), ("back",))]
    assert ap.seeding_block(apps, "back", date(2026, 6, 10), TUN).product == "prodiamine"
    apps.append(_herb("dithiopyr", date(2026, 6, 1)))
    block = ap.seeding_block(apps, "back", date(2026, 6, 10), TUN)
    assert (block.product, block.until) == ("dithiopyr", date(2026, 8, 24))


def test_latest_by_kind():
    apps = [Application("fert", date(2026, 9, 1), ("front",)),
            Application("winterizer", date(2026, 10, 1), ("front",)),
            Application("fert", date(2026, 9, 20), ("back",))]
    assert ap.latest(apps, "front", ("fert",)) == date(2026, 9, 1)
    assert ap.latest(apps, "front", ("fert", "winterizer")) == date(2026, 10, 1)
    assert ap.latest(apps, "side", ("fert",)) is None
