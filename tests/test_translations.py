import json
import re
from pathlib import Path

from custom_components.lawn_growth.binary_sensor import BINARY_KEYS
from custom_components.lawn_growth.button import AREA_BUTTONS
from custom_components.lawn_growth.model.modes import MODES
from custom_components.lawn_growth.sensor import SENSOR_SPECS

ROOT = Path(__file__).parent.parent / "custom_components" / "lawn_growth"
KEY = re.compile(r"^[a-z0-9_-]+$")      # hassfest translation-key rule


def _load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_en_json_matches_strings_json():
    assert _load("translations/en.json") == _load("strings.json")


def test_every_entity_has_a_name_and_no_extras():
    ent = _load("strings.json")["entity"]
    assert set(ent["sensor"]) == {s.key for s in SENSOR_SPECS}
    assert set(ent["binary_sensor"]) == set(BINARY_KEYS)
    assert set(ent["button"]) == set(AREA_BUTTONS) | {"evaluate_now"}
    for platform in ent.values():
        for entry in platform.values():
            assert entry["name"]


def test_mode_states_translated():
    assert set(_load("strings.json")["entity"]["sensor"]["mode"]["state"]) == set(MODES)


def test_icons_reference_real_entities():
    icons = _load("icons.json")["entity"]
    ent = _load("strings.json")["entity"]
    for platform, keys in icons.items():
        assert set(keys) <= set(ent[platform]), platform


def test_keys_pass_hassfest_validation():
    keys = []
    for platform in _load("strings.json")["entity"].values():
        for key, entry in platform.items():
            keys += [key, *entry.get("state", {})]
    assert [k for k in keys if not KEY.match(k)] == []
