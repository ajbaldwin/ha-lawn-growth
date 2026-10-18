"""Post-emergent windows, the spray-day check and the mowing hold, HA layer."""
from datetime import date, datetime, timedelta

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.lawn_growth import const
from custom_components.lawn_growth.model.applications import Application

from .common import FLAT_68, area, daily, make_entry, register_weather, setup

NOW = "2026-09-26 12:00:00+00:00"          # 05:00 local
TODAY = date(2026, 9, 26)
POST = "sensor.lawn_growth_front_post_emergent"
SPRAY = "binary_sensor.lawn_growth_front_good_spray_day"
ALLOWED = "binary_sensor.lawn_growth_front_mowing_allowed"
PRODUCT = "select.lawn_growth_front_post_emergent_product"
LAST = "date.lawn_growth_front_last_post_emergent"


def _hourly(start: date, *, wind=4.0, rain=5.0, hours=72):
    """Hourly rows from local midnight (tests run in US/Pacific: -07:00 in September)."""
    first = datetime(start.year, start.month, start.day)
    return [{"datetime": f"{(first + timedelta(hours=h)).isoformat()}-07:00",
             "temperature": 68.0, "wind_speed": wind, "precipitation_probability": rain}
            for h in range(hours)]


async def _setup(hass, freezer, *, rows=FLAT_68, hourly=None, notify=False):
    hass.config.units = US_CUSTOMARY_SYSTEM
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, rows), hourly_rows=hourly)
    calls = async_mock_service(hass, "notify", "phone") if notify else None
    options = {const.CONF_NOTIFY: "notify.phone"} if notify else {}
    entry = make_entry(hass, areas=[area(key="front", name="Front"),
                                    area(key="back", name="Back")], **options)
    await setup(hass, entry)
    reg = dr.async_get(hass)
    dev = {k: reg.async_get_device(identifiers={(const.DOMAIN, f"{entry.entry_id}_{k}")}).id
           for k in ("front", "back")}
    return entry.runtime_data, dev, calls


async def _call(hass, service, **data):
    await hass.services.async_call(const.DOMAIN, service, data, blocking=True)


async def test_fall_window_and_good_spray_day(hass, freezer):
    await _setup(hass, freezer)
    post = hass.states.get(POST)
    assert post.state == "open"                    # 7-day air mean 68 °F after Aug 15
    assert post.attributes["window"] == "fall_broadleaf"
    assert post.attributes["open_windows"] == ["fall_broadleaf"]
    assert post.attributes["product"] == "mesotrione"
    assert post.attributes["today"]["good"] is True
    spray = hass.states.get(SPRAY)
    assert spray.state == "on"
    # a daily-only forecast: rain falls back to nothing, wind can't be checked
    assert spray.attributes["not_checked"] == ["rain", "wind"]


async def test_hourly_wind_and_rain_are_checked(hass, freezer):
    await _setup(hass, freezer, hourly=_hourly(TODAY, wind=15.0))
    spray = hass.states.get(SPRAY)
    assert spray.state == "off"
    assert spray.attributes["failed"] == ["wind"] and spray.attributes["not_checked"] == []


async def test_logging_a_post_emergent_holds_mowing(hass, freezer):
    c, _, calls = await _setup(hass, freezer, notify=True)
    await hass.services.async_call("select", "select_option",
                                   {"entity_id": PRODUCT, "option": "triclopyr_ester"},
                                   blocking=True)
    assert hass.states.get(PRODUCT).state == "triclopyr_ester"
    await hass.services.async_call("date", "set_value",
                                   {"entity_id": LAST, "date": TODAY.isoformat()},
                                   blocking=True)
    assert c.store.applications[-1] == Application("herbicide", TODAY, ("front",),
                                                   "triclopyr_ester")
    assert hass.states.get(LAST).state == TODAY.isoformat()
    allowed = hass.states.get(ALLOWED)
    assert allowed.state == "off"
    assert allowed.attributes["reason"] == "post-emergent sprayed: don't mow until Sep 28"
    assert hass.states.get("sensor.lawn_growth_front_mode").state == "spray_hold"
    assert hass.states.get("binary_sensor.lawn_growth_back_mowing_allowed").state == "on"
    assert [m.data["message"] for m in calls] == [
        "Front: Triclopyr ester logged — don't mow until Sep 28 so it can work. "
        "Mowing allowed stays off until then."]
    post = hass.states.get(POST).attributes
    assert post["dont_mow_until"] == "2026-09-28"
    assert post["followup_date"] == "2026-10-17"
    assert post["applied_date"] == TODAY.isoformat()


async def test_a_post_emergent_on_new_seedlings_warns(hass, freezer):
    c, dev, calls = await _setup(hass, freezer, notify=True)
    await _call(hass, "log_seeding", device_id=dev["front"], date="2026-09-10")
    await _call(hass, "log_event", device_id=dev["front"], kind="herbicide",
                product="mesotrione")
    assert any("Mesotrione logged, but new seedlings (seeded Sep 10)" in m.data["message"]
               for m in calls)
    allowed = hass.states.get(ALLOWED)
    assert allowed.state == "off" and allowed.attributes["reason"].startswith(
        "establishing seedlings; post-emergent sprayed")
    assert hass.states.get("sensor.lawn_growth_front_mode").state == "establishment"
    assert hass.states.get(SPRAY).attributes["failed"] == ["seedlings"]


async def test_flag_weeds_and_skip(hass, freezer):
    c, dev, _ = await _setup(hass, freezer)
    await _call(hass, "flag_weeds", device_id=dev["front"], target="crabgrass")
    post = hass.states.get(POST).attributes
    assert sorted(post["open_windows"]) == ["fall_broadleaf", "young_crabgrass"]
    await _call(hass, "skip_application", device_id=dev["front"], kind="post_emergent")
    assert hass.states.get(POST).state == "skipped"
    assert hass.states.get(SPRAY).state == "off"
    assert hass.states.get("sensor.lawn_growth_back_post_emergent").state == "open"
    w = c.window("young_crabgrass", "front")
    c.store.windows[w.key] = type(w).from_dict({**w.to_dict(), "status": "closed"})
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "flag_weeds", device_id=dev["front"], target="crabgrass")
    assert err.value.translation_key == "window_ended"


async def test_daily_run_pushes_window_open_then_spray_day(hass, freezer):
    c, _, calls = await _setup(hass, freezer, notify=True)
    await c.async_run(send_notifications=True)
    messages = [m.data["message"] for m in calls]
    assert messages[0].startswith("Post-emergent window open (fall broadleaf) — Front "
                                  "(7-day air mean 68.0 °F), Back (7-day air mean 68.0 °F)")
    assert messages[1].startswith("Good spray day tomorrow (Sep 27) — Front, Back.")
    await c.async_run(send_notifications=True)
    assert len(calls) == 2                         # once per window; spray every 3 days
