"""Legacy ``.map`` texture decoding, and an uncompressed DDS writer.

MAP layout: ``u16 row bytes, u16 format, u32 height`` then the rows, top
first. Formats: 0 8-bit palette index, 1 A4R4G4B4, 2 R5G6B5, 3 A8R8G8B8,
4 X8R8G8B8 (the 32-bit ones stored B, G, R, A in memory). Indexed maps carry
no palette; the stock unit textures use the object range every stock world
palette shares, so any world ACT decodes them (checked against the 16-bit
copies in the 1.5 ``bzhw16q.zfs``). The full MakeMAP clone, with encoding,
lives in ``bztoolbox.modules.textures.makemap_compat``.
"""

from __future__ import annotations

import struct
from typing import Optional, Sequence, Tuple

import numpy as np

__all__ = ["MapError", "decode_map", "palette_from_act", "encode_dds_rgba"]

_BPP = {0: 1, 1: 2, 2: 2, 3: 4, 4: 4}


class MapError(ValueError):
    """Not a MAP texture, or one this decoder cannot read."""


def palette_from_act(data: bytes) -> list:
    """RGB triples from an ``.act`` file (256 x RGB, optional trailer ignored)."""
    if len(data) < 3:
        raise MapError("palette is empty")
    return [tuple(data[i:i + 3]) for i in range(0, min(len(data) // 3, 256) * 3, 3)]


def decode_map(data: bytes, palette: Optional[Sequence[Tuple[int, int, int]]] = None
               ) -> Tuple[int, int, np.ndarray]:
    """``(width, height, rgba)`` with ``rgba`` a ``height x width x 4`` uint8 array, top row first."""
    if len(data) < 8:
        raise MapError("MAP file is smaller than its 8-byte header")
    row_bytes, fmt, height = struct.unpack_from("<HHI", data, 0)
    bpp = _BPP.get(fmt)
    if bpp is None:
        raise MapError(f"unknown MAP pixel format {fmt}")
    if row_bytes == 0 or row_bytes % bpp:
        raise MapError(f"invalid MAP row size {row_bytes} for format {fmt}")
    width = row_bytes // bpp
    end = 8 + row_bytes * height
    if len(data) < end:
        raise MapError(f"truncated MAP data: expected {end} bytes, got {len(data)}")
    payload = data[8:end]
    rgba = np.empty((height, width, 4), dtype=np.uint8)
    if fmt == 0:
        if not palette:
            raise MapError("an 8-bit MAP needs a palette")
        table = np.zeros((256, 4), dtype=np.uint8)
        table[:, 3] = 255
        for i, colour in enumerate(list(palette)[:256]):
            table[i, :3] = colour[:3]
        rgba[:] = table[np.frombuffer(payload, dtype=np.uint8).reshape(height, width)]
    elif fmt in (1, 2):
        words = np.frombuffer(payload, dtype="<u2").reshape(height, width).astype(np.uint16)
        if fmt == 1:
            for channel, shift in ((3, 12), (0, 8), (1, 4), (2, 0)):
                value = (words >> shift) & 0xF
                rgba[..., channel] = (value << 4) | value
        else:
            r, g, b = (words >> 11) & 0x1F, (words >> 5) & 0x3F, words & 0x1F
            rgba[..., 0] = (r << 3) | (r >> 2)
            rgba[..., 1] = (g << 2) | (g >> 4)
            rgba[..., 2] = (b << 3) | (b >> 2)
            rgba[..., 3] = 255
    else:
        packed = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 4)
        rgba[..., 0], rgba[..., 1], rgba[..., 2] = packed[..., 2], packed[..., 1], packed[..., 0]
        rgba[..., 3] = packed[..., 3] if fmt == 3 else 255
    return width, height, rgba


def encode_dds_rgba(rgba: np.ndarray) -> bytes:
    """An uncompressed 32-bit (A8R8G8B8) DDS with no mipmaps, top row first."""
    height, width = rgba.shape[:2]
    header = struct.pack(
        "<4s7I44x" "2I4s5I" "4I4x",
        b"DDS ", 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x8, height, width, width * 4, 0, 1,
        32, 0x1 | 0x40, b"\0\0\0\0", 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000,
        0x1000, 0, 0, 0)
    bgra = np.ascontiguousarray(rgba[..., [2, 1, 0, 3]], dtype=np.uint8)
    return header + bgra.tobytes()
