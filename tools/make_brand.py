"""Generate the brand PNGs (green rounded square, three light grass blades)."""
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "lawn_growth" / "brand"
GREEN, LIGHT = (46, 125, 50), (165, 214, 167)
BLADES = ((0.32, 0.40, 0.07), (0.50, 0.22, 0.08), (0.68, 0.40, 0.07))   # (x, top, half-width)


def _png(size: int, pixel) -> bytes:
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            rows.extend(pixel(x / size, y / size))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


def _pixel(u: float, v: float):
    r = 0.18
    dx, dy = max(abs(u - 0.5) - (0.5 - r), 0), max(abs(v - 0.5) - (0.5 - r), 0)
    if dx * dx + dy * dy > r * r:
        return (0, 0, 0, 0)
    for cx, top, half in BLADES:
        if top <= v <= 0.82 and abs(u - cx) <= half * (v - top) / (0.82 - top):
            return (*LIGHT, 255)
    return (*GREEN, 255)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size in (("icon.png", 256), ("icon@2x.png", 512),
                       ("logo.png", 256), ("logo@2x.png", 512)):
        (OUT / name).write_bytes(_png(size, _pixel))
        print("wrote", OUT / name)
