"""Minimal DDS writer: DXT1 with an explicit mip chain, matching what Redux ships."""
import struct

DDSD = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000 | 0x20000     # CAPS HEIGHT WIDTH PF LINEARSIZE MIPCOUNT
CAPS = 0x1000 | 0x8 | 0x400000                           # TEXTURE COMPLEX MIPMAP


def write_dxt1(path, width, height, levels):
    """levels: list of BC1 byte strings, mip 0 first."""
    linear = max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * 8
    h = struct.pack("<4s7I", b"DDS ", 124, DDSD, height, width, linear, 0, len(levels))
    h += b"\0" * 44                                       # dwReserved1[11]
    h += struct.pack("<II4s5I", 32, 0x4, b"DXT1", 0, 0, 0, 0, 0)
    h += struct.pack("<5I", CAPS, 0, 0, 0, 0)
    assert len(h) == 128, len(h)
    with open(path, "wb") as f:
        f.write(h)
        for lv in levels:
            f.write(lv)
