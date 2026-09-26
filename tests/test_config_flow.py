from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.lawn_growth import const as c

from .common import area

DETAILS = {c.AREA_CUT_MIN: 3.0, c.AREA_CUT_MAX: 3.9, c.AREA_OVERSEED_TARGET: 2.5,
           c.AREA_MOISTURE: [], c.AREA_WILTING: 40, c.AREA_COMFORTABLE: 67,
           c.AREA_MOW_MODE: c.MOW_MODE_INCREASES, c.AREA_MAX_RATE: 6.5}


@pytest.fixture(autouse=True)
def _no_real_setup():
    with patch("custom_components.lawn_growth.async_setup_entry", return_value=True):
        yield


def _fields(result) -> set:
    return {str(k) for k in result["data_schema"].schema}


def _defaults(result) -> dict:
    out = {}
    for k in result["data_schema"].schema:
        if callable(getattr(k, "default", None)):
            out[str(k)] = k.default()
        elif isinstance(getattr(k, "description", None), dict) and \
                "suggested_value" in k.description:
            out[str(k)] = k.description["suggested_value"]
    return out


async def _start(hass):
    hass.states.async_set("weather.home", "sunny")
    async_mock_service(hass, "notify", "phone")
    r = await hass.config_entries.flow.async_init(c.DOMAIN, context={"source": "user"})
    assert r["step_id"] == "user"
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"], {c.CONF_WEATHER: "weather.home", c.CONF_NOTIFY: "notify.phone",
                       c.CONF_RUN_TIME: "05:00:00"})
    assert r["step_id"] == "area_basics"
    return r


async def test_full_setup_creates_entry(hass):
    r = await _start(hass)
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"], {c.AREA_NAME: "Front & Side", c.AREA_GRASS: "tttf_kbg"})
    assert r["step_id"] == "area_details"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], DETAILS)
    assert r["type"] is FlowResultType.CREATE_ENTRY
    opts = r["result"].options
    assert opts[c.CONF_WEATHER] == "weather.home" and opts[c.CONF_NOTIFY] == "notify.phone"
    a = opts[c.CONF_AREAS][0]
    assert (a[c.AREA_KEY], a[c.AREA_NAME], a[c.AREA_CURVE]) == ("front_side", "Front & Side", "cool")
    assert (a[c.AREA_CUT_MIN], a[c.AREA_CUT_MAX], a[c.AREA_OVERSEED_TARGET]) == (3.0, 3.9, 2.5)


async def test_invalid_ranges_show_errors(hass):
    r = await _start(hass)
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"], {c.AREA_NAME: "Lawn", c.AREA_GRASS: "tttf_kbg"})
    bad = {**DETAILS, c.AREA_CUT_MIN: 4.0, c.AREA_CUT_MAX: 3.0, c.AREA_WILTING: 70}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], bad)
    assert r["type"] is FlowResultType.FORM
    assert r["errors"] == {c.AREA_CUT_MAX: "cut_range", c.AREA_COMFORTABLE: "moisture_band"}


async def test_preset_shapes_the_form(hass):
    r = await _start(hass)
    r2 = await hass.config_entries.flow.async_configure(
        r["flow_id"], {c.AREA_NAME: "Lawn", c.AREA_GRASS: "bermuda_zoysia"})
    assert c.AREA_OVERSEED_TARGET not in _fields(r2) and c.AREA_CURVE not in _fields(r2)
    r = await _start(hass)
    r3 = await hass.config_entries.flow.async_configure(
        r["flow_id"], {c.AREA_NAME: "Lawn", c.AREA_GRASS: "custom"})
    assert {c.AREA_CURVE, c.AREA_OVERSEED_TARGET} <= _fields(r3)


def _entry(hass, **options) -> MockConfigEntry:
    opts = {c.CONF_WEATHER: "weather.home", c.CONF_RUN_TIME: "05:00:00",
            c.CONF_AREAS: [area(key="back", name="Back")]}
    opts.update(options)
    entry = MockConfigEntry(domain=c.DOMAIN, data={}, options=opts)
    entry.add_to_hass(hass)
    return entry


async def _menu(hass, entry, step):
    r = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": step})


async def test_add_area_gets_unique_key(hass):
    entry = _entry(hass)
    r = await _menu(hass, entry, "area_basics")
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {c.AREA_NAME: "Back", c.AREA_GRASS: "kbg"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], DETAILS)
    assert [a[c.AREA_KEY] for a in entry.options[c.CONF_AREAS]] == ["back", "back_2"]


async def test_edit_area_keeps_key(hass):
    entry = _entry(hass)
    r = await _menu(hass, entry, "edit_area")
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"area": "back"})
    assert r["step_id"] == "area_basics"
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {c.AREA_NAME: "Back", c.AREA_GRASS: "tttf_kbg"})
    assert r["step_id"] == "area_details"
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {**DETAILS, c.AREA_CUT_MAX: 3.5})
    [a] = entry.options[c.CONF_AREAS]
    assert (a[c.AREA_KEY], a[c.AREA_CUT_MAX]) == ("back", 3.5)


async def test_edit_area_can_change_name_and_grass(hass):
    # area key="back", name="Back", grass="tttf_kbg", with distinctive stored values on
    # fields the new preset does not touch.
    stored = area(key="back", name="Back", max_growth_rate_mm=9.9, mow_source_mode=c.MOW_MODE_ANY)
    entry = _entry(hass, **{c.CONF_AREAS: [stored]})
    r = await _menu(hass, entry, "edit_area")
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"area": "back"})
    assert r["step_id"] == "area_basics"
    assert _defaults(r)[c.AREA_NAME] == "Back" and _defaults(r)[c.AREA_GRASS] == "tttf_kbg"
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {c.AREA_NAME: "Back Lawn", c.AREA_GRASS: "kbg"})
    assert r["step_id"] == "area_details"
    d = _defaults(r)   # kbg preset: cool, 2.5-3.5in, overseed 2.0in
    assert (d[c.AREA_CUT_MIN], d[c.AREA_CUT_MAX], d[c.AREA_OVERSEED_TARGET]) == (2.5, 3.5, 2.0)
    assert d[c.AREA_MAX_RATE] == 9.9 and d[c.AREA_MOW_MODE] == c.MOW_MODE_ANY  # stored, kept
    r = await hass.config_entries.options.async_configure(r["flow_id"], DETAILS)
    [a] = entry.options[c.CONF_AREAS]
    assert (a[c.AREA_KEY], a[c.AREA_NAME], a[c.AREA_GRASS]) == ("back", "Back Lawn", "kbg")


async def test_remove_area(hass):
    entry = _entry(hass, **{c.CONF_AREAS: [area(key="front", name="Front"),
                                           area(key="back", name="Back")]})
    reg = dr.async_get(hass)
    device = reg.async_get_or_create(config_entry_id=entry.entry_id,
                                     identifiers={(c.DOMAIN, f"{entry.entry_id}_back")})
    r = await _menu(hass, entry, "remove_area")
    await hass.config_entries.options.async_configure(r["flow_id"], {"area": "back"})
    assert [a[c.AREA_KEY] for a in entry.options[c.CONF_AREAS]] == ["front"]
    assert reg.async_get(device.id) is None
    r = await _menu(hass, entry, "remove_area")
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "last_area"


async def test_settings(hass):
    entry = _entry(hass, **{c.CONF_NOTIFY: "notify.phone"})
    hass.states.async_set("weather.other", "sunny")
    r = await _menu(hass, entry, "settings")
    await hass.config_entries.options.async_configure(
        r["flow_id"], {c.CONF_WEATHER: "weather.other", c.CONF_RUN_TIME: "06:30:00"})
    assert entry.options[c.CONF_WEATHER] == "weather.other"
    assert c.CONF_NOTIFY not in entry.options            # cleared when left empty
    assert entry.options[c.CONF_AREAS][0][c.AREA_KEY] == "back"


async def test_mower_setup_and_location_mapping(hass):
    entry = _entry(hass)
    hass.states.async_set("sensor.loc", "Not working", {"options": ["Backyard", "Front Yard"]})
    r = await _menu(hass, entry, "mower")
    await hass.config_entries.options.async_configure(r["flow_id"], {
        c.MOWER_ACTIVITY: "sensor.act", c.MOWER_WORKING: ["MODE_WORKING"],
        c.MOWER_BLADE: "sensor.blade", c.MOWER_LOCATION: "sensor.loc",
        c.MOWER_GRACE: 15, c.MOWER_MIN_AREA: 10})
    assert entry.options[c.CONF_MOWER][c.MOWER_WORKING] == ["MODE_WORKING"]

    r = await _menu(hass, entry, "edit_area")
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"area": "back"})
    assert r["step_id"] == "area_basics"
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {c.AREA_NAME: "Back", c.AREA_GRASS: "tttf_kbg"})
    assert c.AREA_LOCATIONS in _fields(r)
    await hass.config_entries.options.async_configure(
        r["flow_id"], {**DETAILS, c.AREA_LOCATIONS: ["Backyard"]})
    assert entry.options[c.CONF_AREAS][0][c.AREA_LOCATIONS] == ["Backyard"]

    r = await _menu(hass, entry, "area_basics")
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {c.AREA_NAME: "Front", c.AREA_GRASS: "tttf_kbg"})
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {**DETAILS, c.AREA_LOCATIONS: ["Backyard"]})
    assert r["errors"] == {c.AREA_LOCATIONS: "location_in_use"}


async def test_mower_removed_when_activity_cleared(hass):
    entry = _entry(hass, **{c.CONF_MOWER: {c.MOWER_ACTIVITY: "sensor.act"},
                            c.CONF_AREAS: [area(key="back", name="Back",
                                                mower_locations=["Backyard"])]})
    r = await _menu(hass, entry, "mower")
    await hass.config_entries.options.async_configure(r["flow_id"], {
        c.MOWER_GRACE: 15, c.MOWER_MIN_AREA: 10})
    assert c.CONF_MOWER not in entry.options
    assert entry.options[c.CONF_AREAS][0][c.AREA_LOCATIONS] == []


def _options(result, field) -> list:
    [selector] = [v for k, v in result["data_schema"].schema.items() if str(k) == field]
    return list(selector.config["options"])


async def test_blank_area_name_rejected(hass):
    r = await _start(hass)
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"], {c.AREA_NAME: "   ", c.AREA_GRASS: "tttf_kbg"})
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "area_basics"
    assert r["errors"] == {c.AREA_NAME: "invalid_name"}
    entry = _entry(hass)
    r = await _menu(hass, entry, "area_basics")
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {c.AREA_NAME: " ", c.AREA_GRASS: "kbg"})
    assert r["step_id"] == "area_basics" and r["errors"] == {c.AREA_NAME: "invalid_name"}


async def test_notify_choices_skip_send_message_and_keep_saved_target(hass):
    async_mock_service(hass, "notify", "phone")
    async_mock_service(hass, "notify", "send_message")     # entity service: needs a target
    entry = _entry(hass, **{c.CONF_NOTIFY: "notify.old_phone"})   # no longer registered
    r = await _menu(hass, entry, "settings")
    assert _options(r, c.CONF_NOTIFY) == ["notify.old_phone", "notify.phone"]
    await hass.config_entries.options.async_configure(
        r["flow_id"], {c.CONF_WEATHER: "weather.home", c.CONF_NOTIFY: "notify.old_phone",
                       c.CONF_RUN_TIME: "05:00:00"})
    assert entry.options[c.CONF_NOTIFY] == "notify.old_phone"
