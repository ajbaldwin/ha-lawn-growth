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


def test_prodiamine_blocks_seeding_for_4_months():
    """The label's shortest interval (2.3 lb/1,000 sq ft); higher rates need longer."""
    apps = [_herb("prodiamine", date(2026, 4, 8))]
    block = ap.seeding_block(apps, "back", date(2026, 6, 1), TUN)
    assert block.until == date(2026, 8, 8)
    assert block.text() == "Prodiamine applied Apr 8 — seeding blocked until Aug 8"
    assert ap.seeding_block(apps, "back", date(2026, 8, 8), TUN) is None
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


def test_triclopyr_ester_blocks_seeding_for_3_weeks():
    apps = [_herb("triclopyr_ester", date(2026, 6, 1), ("back",))]
    assert ap.seeding_block(apps, "back", date(2026, 6, 21), TUN).until == date(2026, 6, 22)
    assert ap.seeding_block(apps, "back", date(2026, 6, 22), TUN) is None


# --- pre-emergent on new turf (prodiamine label: 60 days and 2 mows) ---------------

SEEDED = date(2026, 9, 1)


def test_prodiamine_waits_60_days_after_seeding():
    mows = (date(2026, 9, 20), date(2026, 9, 27))
    assert ap.new_turf_wait("prodiamine", SEEDED, mows, date(2026, 10, 1), TUN) == (
        "the label says to wait 60 days and 2 mows after seeding (seeded Sep 1: "
        "30 days, 2 mows so far)")
    assert ap.new_turf_wait("prodiamine", SEEDED, mows, date(2026, 10, 31), TUN) is None


def test_prodiamine_waits_for_the_second_mow():
    mows = (date(2026, 8, 25), date(2026, 10, 15))      # one before the seeding
    assert ap.new_turf_wait("prodiamine", SEEDED, mows, date(2026, 11, 5), TUN) == (
        "the label says to wait 60 days and 2 mows after seeding (seeded Sep 1: "
        "65 days, 1 mow so far)")


def test_new_turf_wait_only_for_prodiamine_and_a_recent_seeding():
    assert ap.new_turf_wait("dithiopyr", SEEDED, (), date(2026, 9, 10), TUN) is None
    assert ap.new_turf_wait("prodiamine", None, (), date(2026, 9, 10), TUN) is None
    # a seeding after the application date isn't on the treated grass
    assert ap.new_turf_wait("prodiamine", SEEDED, (), date(2026, 8, 20), TUN) is None
    assert ap.new_turf_wait("prodiamine", SEEDED, (), date(2027, 9, 10), TUN) is None
