from datetime import date, datetime, timezone

from custom_components.lawn_growth.model import session
from custom_components.lawn_growth.model.management import ManagementEvent
from custom_components.lawn_growth.model.state import AreaState
from custom_components.lawn_growth.store import LawnStore


async def test_round_trip(hass, hass_storage):
    store = LawnStore(hass, "abc")
    await store.async_load(["lawn"])
    assert store.areas == {"lawn": AreaState()} and store.session is None
    store.areas["lawn"].accumulated_mm = 12.0
    store.add_event("fert", date(2026, 9, 20), ["lawn"], date(2026, 9, 26))
    store.session = session.start(datetime(2026, 9, 26, 12, tzinfo=timezone.utc),
                                  area="lawn", height_in=3.0)
    await store.async_save()

    again = LawnStore(hass, "abc")
    await again.async_load(["lawn"])
    assert again.areas["lawn"].accumulated_mm == 12.0
    assert again.events_for("lawn") == [ManagementEvent("fert", date(2026, 9, 20))]
    assert again.events_for("other") == []
    assert again.session == store.session


async def test_areas_follow_configuration(hass, hass_storage):
    store = LawnStore(hass, "abc")
    await store.async_load(["old"])
    store.areas["old"].accumulated_mm = 5.0
    await store.async_save()
    again = LawnStore(hass, "abc")
    await again.async_load(["new"])
    assert set(again.areas) == {"new"}


async def test_events_pruned_after_35_days(hass):
    store = LawnStore(hass, "abc")
    await store.async_load(["lawn"])
    store.add_event("pgr", date(2026, 8, 1), ["lawn"], date(2026, 8, 1))
    store.add_event("fert", date(2026, 9, 26), ["lawn"], date(2026, 9, 26))
    assert [e["kind"] for e in store.events] == ["fert"]
