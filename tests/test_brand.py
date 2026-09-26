import struct
from pathlib import Path

BRAND = Path(__file__).parent.parent / "custom_components" / "lawn_growth" / "brand"


def _size(path: Path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_brand_icons():
    assert _size(BRAND / "icon.png") == (256, 256)
    assert _size(BRAND / "icon@2x.png") == (512, 512)
    assert _size(BRAND / "logo.png") == (256, 256)
    assert _size(BRAND / "logo@2x.png") == (512, 512)


def test_changelog_has_first_beta():
    text = (Path(__file__).parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## 0.1.0-beta.1 — " in text
