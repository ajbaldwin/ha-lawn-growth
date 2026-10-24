"""Application windows, the application log and the calendar, HA layer."""
from datetime import date, timedelta

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.lawn_growth import const
from custom_components.lawn_growth.model.applications import Application

from .common import FLAT_68, area, daily, make_entry, register_weather, setup

SPRING_NOW = "2027-04-12 12:00:00+00:00"        # 05:00 local
SPRING = date(2027, 4, 12)
FALL_NOW = "2026-09-26 12:00:00+00:00"
FALL = date(2026, 9, 26)
PRE = "sensor.lawn_growth_pre_emergent"
CAL = "calendar.lawn_growth_applications"


def _storage(hass_storage, entry, *, gdd=None, minor=2, **data):
    key = f"{const.DOMAIN}.{entry.entry_id}"
    body = {"areas": {}, "events": [], "session": None}
    if gdd is not None:
        body["gdd"] = {"year": SPRING.year, "total": gdd,
                       "last_day": (SPRING - timedelta(days=1)).isoformat()}
    body.update(data)
    hass_storage[key] = {"version": 1, "minor_version": minor, "key": key, "data": body}


async def _setup(hass, freezer, hass_storage=None, *, now=FALL_NOW, today=FALL, gdd=None,
                 notify=False, **storage):
    hass.config.units = US_CUSTOMARY_SYSTEM
    freezer.move_to(now)
    register_weather(hass, daily_rows=daily(today, FLAT_68))
    calls = async_mock_service(hass, "notify", "phone") if notify else None
    options = {const.CONF_NOTIFY: "notify.phone"} if notify else {}
    entry = make_entry(hass, areas=[area(key="front", name="Front"),
                                    area(key="back", name="Back")], **options)
    if hass_storage is not None and (gdd is not None or storage):
        _storage(hass_storage, entry, gdd=gdd, **storage)
    await setup(hass, entry)
    reg = dr.async_get(hass)
    dev = {k: reg.async_get_device(identifiers={(const.DOMAIN, f"{entry.entry_id}_{k}")}).id
           for k in ("front", "back")}
    return entry.runtime_data, dev, calls


async def _call(hass, service, **data):
    await hass.services.async_call(const.DOMAIN, service, data, blocking=True)


async def _set_date(hass, entity_id, value):
    await hass.services.async_call("date", "set_value",
                                   {"entity_id": entity_id, "date": value.isoformat()},
                                   blocking=True)


# --- services and the application log ----------------------------------------------

async def test_herbicide_without_a_device_logs_every_area(hass, freezer):
    c, _, _ = await _setup(hass, freezer)
    await _call(hass, "log_event", kind="herbicide", product="prodiamine",
                date="2026-09-20")
    assert c.store.applications == [
        Application("herbicide", date(2026, 9, 20), ("front", "back"), "prodiamine")]
    assert c.store.events == []                  # herbicides don't touch the growth model


async def test_log_event_product_validation(hass, freezer):
    _, dev, _ = await _setup(hass, freezer)
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "log_event", kind="herbicide")
    assert err.value.translation_key == "product_required"
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "log_event", device_id=dev["back"], kind="fert",
                    product="mesotrione")
    assert err.value.translation_key == "product_herbicide_only"


async def test_winterizer_counts_as_fertilizer(hass, freezer):
    c, dev, _ = await _setup(hass, freezer)
    before = c.data["back"].growth_today_mm
    await _call(hass, "log_event", device_id=dev["back"], kind="winterizer",
                date="2026-09-22")
    assert c.store.events == [{"kind": "winterizer", "date": "2026-09-22",
                               "areas": ["back"]}]
    assert c.store.applications[-1].kind == "winterizer"
    assert c.data["back"].growth_today_mm > before
    assert hass.states.get("date.lawn_growth_back_last_winterizer").state == "2026-09-22"
    assert hass.states.get("date.lawn_growth_back_last_fertilizer").state == "unknown"
    assert hass.states.get("date.lawn_growth_front_last_winterizer").state == "unknown"


async def test_last_winterizer_picker_logs(hass, freezer):
    c, _, _ = await _setup(hass, freezer)
    await _set_date(hass, "date.lawn_growth_front_last_winterizer", FALL)
    await _set_date(hass, "date.lawn_growth_front_last_winterizer", FALL)   # no-op
    assert [a.kind for a in c.store.applications] == ["winterizer"]
    with pytest.raises(ServiceValidationError):
        await _set_date(hass, "date.lawn_growth_front_last_winterizer",
                        FALL + timedelta(days=1))


async def test_application_log_outlives_the_growth_events(hass, freezer):
    c, dev, _ = await _setup(hass, freezer)
    await _call(hass, "log_event", device_id=dev["back"], kind="fert", date="2026-08-01")
    await _call(hass, "log_event", device_id=dev["back"], kind="pgr")
    assert [e["kind"] for e in c.store.events] == ["pgr"]          # 35-day prune
    assert [a.kind for a in c.store.applications] == ["fert", "pgr"]


async def test_seeding_is_logged_and_corrected(hass, freezer):
    c, dev, _ = await _setup(hass, freezer)
    await _set_date(hass, "date.lawn_growth_back_seeding_date", FALL - timedelta(days=5))
    await _set_date(hass, "date.lawn_growth_back_seeding_date", FALL - timedelta(days=3))
    assert c.store.applications == [
        Application("seeding", FALL - timedelta(days=3), ("back",))]


async def test_skip_application(hass, freezer):
    c, dev, _ = await _setup(hass, freezer, now=SPRING_NOW, today=SPRING)
    await _call(hass, "skip_application", kind="pre_emergent")
    assert hass.states.get(PRE).state == "skipped"
    assert hass.states.get(PRE).attributes["skipped_date"] == SPRING.isoformat()
    await _call(hass, "skip_application", kind="winterizer", device_id=dev["back"])
    assert hass.states.get("sensor.lawn_growth_back_winterizer").state == "skipped"
    assert hass.states.get("sensor.lawn_growth_front_winterizer").state == "tentative"


async def test_skip_overseed_on_a_warm_season_area_is_rejected(hass, freezer):
    hass.config.units = US_CUSTOMARY_SYSTEM
    freezer.move_to(FALL_NOW)
    register_weather(hass, daily_rows=daily(FALL, FLAT_68))
    entry = make_entry(hass, areas=[area(key="warm", name="Warm", grass="bermuda_zoysia",
                                         curve="warm", **{const.AREA_OVERSEED_TARGET: None})])
    await setup(hass, entry)
    assert hass.states.get("sensor.lawn_growth_warm_overseed_window") is None
    device = dr.async_get(hass).async_get_device(
        identifiers={(const.DOMAIN, f"{entry.entry_id}_warm")})
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "skip_application", kind="overseed", device_id=device.id)
    assert err.value.translation_key == "no_overseed"


# --- pre-emergent sensor, picker, select, notifications ----------------------------

async def test_pre_emergent_from_gdd_with_one_alert(hass, freezer, hass_storage):
    c, _, calls = await _setup(hass, freezer, hass_storage, now=SPRING_NOW, today=SPRING,
                               gdd=130.0, notify=True)
    st = hass.states.get(PRE)
    assert st.state == "open"
    assert st.attributes["source"] == "gdd" and st.attributes["trigger_unit"] == "GDD"
    assert st.attributes["stage"] == "open" and st.attributes["open_date"] == "2027-04-12"
    assert st.attributes["suggested_product"] == "prodiamine"
    assert calls == []                                       # startup run: no pushes
    await _call(hass, "evaluate_now")
    assert len(calls) == 1
    msg = calls[0].data["message"]
    assert msg.startswith("Apply pre-emergent now: 130 growing degree days.")
    assert "Estimated from air temperatures" in msg
    await _call(hass, "evaluate_now")
    assert len(calls) == 1                                   # once per transition



async def test_pre_emergent_push_names_areas_inside_prodiamines_wait(hass, freezer,
                                                                    hass_storage):
    seeded = [{"kind": "seeding", "date": "2027-03-01", "areas": ["back"]}]
    c, _, calls = await _setup(hass, freezer, hass_storage, now=SPRING_NOW, today=SPRING,
                               gdd=130.0, notify=True, applications=seeded)
    assert hass.states.get(PRE).attributes["suggested_product"] == "prodiamine"
    await _call(hass, "evaluate_now")
    [msg] = [call.data["message"] for call in calls]
    assert ("\nBack: skip it or use dithiopyr there — for prodiamine, the label says to "
            "wait 60 days and 2 mows after seeding (seeded Mar 1: 42 days, 0 mows so "
            "far).\n") in msg
    assert "Front:" not in msg


async def test_pre_emergent_suggests_dithiopyr_while_every_area_is_new_turf(
        hass, freezer, hass_storage):
    seeded = [{"kind": "seeding", "date": "2027-03-01", "areas": ["front", "back"]}]
    await _setup(hass, freezer, hass_storage, now=SPRING_NOW, today=SPRING, gdd=130.0,
                 applications=seeded)
    assert hass.states.get(PRE).attributes["suggested_product"] == "dithiopyr"
    assert hass.states.get("select.lawn_growth_pre_emergent_product").state == "dithiopyr"

async def test_last_pre_emergent_logs_every_area_with_the_select(hass, freezer,
                                                                 hass_storage):
    c, _, _ = await _setup(hass, freezer, hass_storage, now=SPRING_NOW, today=SPRING,
                           gdd=130.0)
    sel = "select.lawn_growth_pre_emergent_product"
    assert hass.states.get(sel).state == "prodiamine"
    await hass.services.async_call("select", "select_option",
                                   {"entity_id": sel, "option": "other_pre_emergent"},
                                   blocking=True)
    assert hass.states.get(sel).state == "other_pre_emergent"
    await _set_date(hass, "date.lawn_growth_last_pre_emergent", SPRING)
    assert c.store.applications == [
        Application("herbicide", SPRING, ("front", "back"), "other_pre_emergent")]
    st = hass.states.get(PRE)
    assert st.state == "done" and st.attributes["product"] == "other_pre_emergent"
    assert st.attributes["seeding_blocked_until"] == (SPRING + timedelta(days=84)).isoformat()
    assert st.attributes["split_reminder_date"] == (SPRING + timedelta(days=49)).isoformat()
    assert hass.states.get(sel).state == "dithiopyr"         # back to the suggestion
    assert hass.states.get("date.lawn_growth_last_pre_emergent").state == SPRING.isoformat()
    await _set_date(hass, "date.lawn_growth_last_pre_emergent", SPRING)        # no-op
    assert len(c.store.applications) == 1


async def test_blocking_product_on_an_establishing_area_warns(hass, freezer, caplog):
    c, dev, calls = await _setup(hass, freezer, notify=True)
    await _set_date(hass, "date.lawn_growth_back_seeding_date", FALL - timedelta(days=5))
    await _call(hass, "log_event", kind="herbicide", product="prodiamine")
    assert [call.data["message"] for call in calls] == [
        "Back is establishing new grass (seeded Sep 21): Prodiamine can keep the "
        "seedlings from rooting."]
    assert "establishing new grass" in caplog.text
    assert hass.states.get("binary_sensor.lawn_growth_back_mowing_allowed").state == "off"


async def test_prodiamine_on_young_grass_warns_after_seedlings_ready(hass, freezer):
    c, dev, calls = await _setup(hass, freezer, notify=True)
    await _call(hass, "log_seeding", device_id=dev["back"], date="2026-09-10")
    await _call(hass, "seedlings_ready", device_id=dev["back"])
    await _call(hass, "log_event", kind="herbicide", product="prodiamine")
    assert [call.data["message"] for call in calls][-1:] == [
        "Back: Prodiamine logged, but the label says to wait 60 days and 2 mows after "
        "seeding (seeded Sep 10: 16 days, 0 mows so far). It can injure new grass."]
    await _call(hass, "log_event", kind="herbicide", product="dithiopyr")
    assert not any("Dithiopyr" in call.data["message"] for call in calls)


async def test_prep_overseed_inside_a_seeding_block_warns(hass, freezer):
    c, dev, calls = await _setup(hass, freezer, notify=True)
    await _call(hass, "log_event", kind="herbicide", product="dithiopyr",
                date="2026-08-01")
    await _call(hass, "prep_overseed", device_id=dev["back"], seed_date="2026-10-10")
    assert calls[-1].data["message"] == (
        "Back: Dithiopyr applied Aug 1 — seeding blocked until Oct 24 (seed date Oct 10).")
    st = hass.states.get("sensor.lawn_growth_back_overseed_window")
    assert st.attributes["planned_seed_date"] == "2026-10-10"
    assert st.attributes["seeding_blocked_until"] == "2026-10-24"


# --- per-area windows and the calendar ---------------------------------------------

async def test_area_window_sensors(hass, freezer):
    await _setup(hass, freezer)
    win = hass.states.get("sensor.lawn_growth_back_winterizer")
    assert win.state == "tentative" and win.attributes["season"] == 2026
    assert win.attributes["estimated_date"] == "2026-11-05"
    assert win.attributes["conditions"] == {"wound_down": False, "spacing": True,
                                            "green": True}
    ov = hass.states.get("sensor.lawn_growth_back_overseed_window")
    # no probes: a 68 °F 7-day air mean is cool enough, but not falling yet
    assert ov.state == "projected" and ov.attributes["source"] == "air"
    assert ov.attributes["projected_date"] == (FALL + timedelta(days=1)).isoformat()
    assert ov.attributes["estimated_date"] is None
    pre = hass.states.get(PRE)
    assert pre.state == "tentative" and pre.attributes["estimated_date"] == "2027-04-10"


async def test_calendar_entity(hass, freezer, hass_storage):
    c, _, _ = await _setup(hass, freezer, hass_storage, now=SPRING_NOW, today=SPRING,
                           gdd=130.0)
    await _call(hass, "log_event", kind="fert", date="2027-04-01")
    st = hass.states.get(CAL)
    assert st.attributes["message"] == "Apply pre-emergent"
    assert st.attributes["all_day"] is True
    start = dt_util.start_of_local_day(date(2027, 3, 1))
    resp = await hass.services.async_call(
        "calendar", "get_events", {"start_date_time": start.isoformat(),
                                   "end_date_time": (start + timedelta(days=90)).isoformat()},
        target={"entity_id": CAL}, blocking=True, return_response=True)
    events = resp[CAL]["events"]
    assert [(e["summary"], e["start"]) for e in events][:2] == [
        ("Fertilizer — whole lawn", "2027-04-01"), ("Apply pre-emergent", "2027-04-12")]
    assert "Trigger: 130 growing degree days" in events[1]["description"]
    assert {e.key for e in c.calendar} >= {"lawn_growth-pre_emergent-2027-all-open",
                                           "lawn_growth-fert-2027-all-applied-2027-04-01"}


# --- storage ------------------------------------------------------------------------

async def test_store_migration_seeds_the_application_log(hass, freezer, hass_storage):
    c, _, _ = await _setup(
        hass, freezer, hass_storage, minor=1,
        events=[{"kind": "fert", "date": "2026-09-10", "areas": ["back"]}],
        areas={"back": {"seeding_date": "2026-09-01"}})
    assert c.store.applications == [Application("seeding", date(2026, 9, 1), ("back",)),
                                    Application("fert", date(2026, 9, 10), ("back",))]
    assert hass_storage[f"{const.DOMAIN}.{c.config_entry.entry_id}"]["minor_version"] == 2


async def test_windows_and_flags_survive_a_reload(hass, freezer, hass_storage):
    c, _, calls = await _setup(hass, freezer, hass_storage, now=SPRING_NOW, today=SPRING,
                               gdd=130.0, notify=True)
    await _call(hass, "evaluate_now")
    assert len(calls) == 1
    assert await hass.config_entries.async_reload(c.config_entry.entry_id)
    await hass.async_block_till_done()
    await _call(hass, "evaluate_now")
    assert len(calls) == 1
    assert hass.states.get(PRE).state == "open"
