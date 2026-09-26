from datetime import date
from pathlib import Path

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.service import _SERVICES_SCHEMA
from homeassistant.util.yaml import load_yaml

from custom_components.lawn_growth.const import DOMAIN

from .common import FLAT_68, NOW, TODAY, area, daily, make_entry, register_weather, setup


async def _setup(hass, freezer):
    freezer.move_to(NOW)
    register_weather(hass, daily_rows=daily(TODAY, FLAT_68))
    entry = make_entry(hass, areas=[area(key="front", name="Front"),
                                    area(key="back", name="Back")])
    await setup(hass, entry)
    reg = dr.async_get(hass)
    dev = {k: reg.async_get_device(identifiers={(DOMAIN, f"{entry.entry_id}_{k}")}).id
           for k in ("front", "back")}
    return entry.runtime_data, dev


async def _call(hass, service, **data):
    await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_log_mow_with_height_and_date(hass, freezer):
    c, dev = await _setup(hass, freezer)
    await _call(hass, "log_mow", device_id=dev["back"], date="2026-09-20", height_in=3.0)
    s = c.store.areas["back"]
    assert (s.last_mow, s.last_cut_in, s.mow_records[-1].source) == (date(2026, 9, 20), 3.0,
                                                                       "manual")
    assert c.store.areas["front"].last_mow is None


async def test_correct_last_mow(hass, freezer):
    c, dev = await _setup(hass, freezer)
    with pytest.raises(ServiceValidationError):
        await _call(hass, "correct_last_mow", device_id=dev["back"], height_in=3.1)
    await _call(hass, "log_mow", device_id=dev["back"], height_in=3.0)
    await _call(hass, "correct_last_mow", device_id=dev["back"], height_in=3.1)
    assert c.store.areas["back"].last_cut_in == 3.1


async def test_seeding_and_ready(hass, freezer):
    c, dev = await _setup(hass, freezer)
    with pytest.raises(ServiceValidationError):
        await _call(hass, "seedlings_ready", device_id=dev["back"])
    await _call(hass, "log_seeding", device_id=dev["back"], date="2026-09-20")
    assert c.data["back"].mode == "establishment"
    await _call(hass, "seedlings_ready", device_id=dev["back"])
    assert c.data["back"].mode == "first_mow_ready"


async def test_log_event_for_several_areas(hass, freezer):
    c, dev = await _setup(hass, freezer)
    await _call(hass, "log_event", device_id=[dev["front"], dev["back"]], kind="pgr")
    assert c.store.events == [{"kind": "pgr", "date": "2026-09-26",
                               "areas": ["front", "back"]}]


async def test_prep_and_cancel_overseed(hass, freezer):
    c, dev = await _setup(hass, freezer)
    await _call(hass, "prep_overseed", device_id=dev["back"], seed_date="2026-10-10",
                target_in=2.5, buffer_days=5)
    ov = c.store.areas["back"].overseed
    assert (ov.seed_date, ov.target_in, ov.buffer_days) == (date(2026, 10, 10), 2.5, 5)
    assert c.data["back"].overseed_active is True
    await _call(hass, "cancel_overseed", device_id=dev["back"])
    assert c.store.areas["back"].overseed.seed_date is None


async def test_unknown_device_rejected(hass, freezer):
    await _setup(hass, freezer)
    with pytest.raises(ServiceValidationError):
        await _call(hass, "log_mow", device_id="not-a-device")


async def test_evaluate_now(hass, freezer):
    c, _ = await _setup(hass, freezer)
    await _call(hass, "evaluate_now")
    assert c.data["back"].mode == "normal"


@pytest.mark.parametrize("service,extra", [("log_mow", {}), ("log_seeding", {}),
                                           ("log_event", {"kind": "fert"})])
async def test_future_dates_rejected(hass, freezer, service, extra):
    c, dev = await _setup(hass, freezer)
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, service, device_id=dev["back"], date="2026-09-27", **extra)
    assert err.value.translation_key == "future_date"
    s = c.store.areas["back"]
    assert (s.mow_records, s.seeding_date, c.store.events) == ([], None, [])
    await _call(hass, service, device_id=dev["back"], date="2026-09-26", **extra)  # today ok


async def test_prep_overseed_seed_date_may_be_future(hass, freezer):
    c, dev = await _setup(hass, freezer)
    await _call(hass, "prep_overseed", device_id=dev["back"], seed_date="2026-10-20")
    assert c.store.areas["back"].overseed.seed_date == date(2026, 10, 20)


def test_services_yaml_has_no_target_device_filter():
    """hassfest (current HA dev) rejects any "device" key on a service target with "Services
    do not support device filters on target, use a device selector instead" -- so services
    must not declare `target: device: ...` at all, regardless of which filter keys it uses.
    Mowing areas are instead selected via a required `device_id` field (a device selector),
    checked below."""
    services = load_yaml(Path(__file__).parent.parent / "custom_components" / "lawn_growth"
                         / "services.yaml")
    _SERVICES_SCHEMA(services)                          # HA's own services.yaml schema
    for name, spec in services.items():
        assert "device" not in (spec.get("target") or {}), name


def test_services_yaml_area_services_require_device_id_field():
    """Every mowing-area service (all but evaluate_now) must declare a required `device_id`
    field with a device selector filtered to this integration's mowing-area devices -- the
    replacement for the target device filter hassfest now rejects. The lawn-level device
    (Evaluate now's) is kept out of the area pickers by the "Mowing area" model filter, and
    out of the area logic entirely by the not_an_area check in entity.py."""
    services = load_yaml(Path(__file__).parent.parent / "custom_components" / "lawn_growth"
                         / "services.yaml")
    for name, spec in services.items():
        if name == "evaluate_now":
            assert not spec
            continue
        field = spec["fields"]["device_id"]
        assert field["required"] is True, name
        device_filter = field["selector"]["device"]["filter"]
        filters = device_filter if isinstance(device_filter, list) else [device_filter]
        assert len(filters) == 1, name
        assert set(filters[0]) == {"integration", "model"}, name
        assert filters[0]["integration"] == DOMAIN, name
        assert filters[0]["model"] == "Mowing area", name
        assert list(spec["fields"])[0] == "device_id", name
