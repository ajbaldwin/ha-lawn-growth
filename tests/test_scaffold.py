import json
import sys
from pathlib import Path

# Ensure custom_components is in sys.path
_root = Path(__file__).parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Import at module level
from custom_components.lawn_growth import const

ROOT = Path(__file__).parent.parent
PKG = ROOT / "custom_components" / "lawn_growth"


def test_manifest():
    m = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    assert m["domain"] == "lawn_growth"
    assert m["name"] == "Lawn Growth"
    assert m["version"] == "0.1.0-beta.2"
    assert m["iot_class"] == "calculated"
    assert m["config_flow"] is True
    assert m["single_config_entry"] is True
    assert m["requirements"] == []
    # hassfest: domain, name first, the rest sorted
    keys = list(m)
    assert keys[:2] == ["domain", "name"] and keys[2:] == sorted(keys[2:])


def test_hacs_json():
    h = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert h == {"name": "Lawn Growth", "homeassistant": "2026.3.0",
                 "hide_default_branch": True}


def test_const_domain():
    assert const.DOMAIN == "lawn_growth"
    assert const.DEFAULT_RUN_TIME == "05:00:00"
