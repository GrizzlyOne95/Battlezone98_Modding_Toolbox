"""The 33 stock Battlezone ACT palettes, embedded.

Used for legacy MAP decoding (WorldBuilder) and the MAP converter
(TextureManager); both used to carry their own copy.

The bundled stock palette pack contains 33 ACT files. Each ACT is exactly
768 bytes (256 RGB triplets). They are concatenated in STOCK_ACT_NAMES order
and stored as one zlib/base64 payload so packaged WorldBuilder builds can
resolve stock TRN palette references without requiring loose game files.
"""

from __future__ import annotations

import base64
import hashlib
import os
import zlib

STOCK_ACT_NAMES = (
    "achilles.act", "black.act", "brown.act", "elysium.act", "europa.act",
    "explode.act", "ganymede.act", "grey.act", "hblack.act", "hblue.act",
    "hbrown.act", "hcyan.act", "hgreen.act", "hgrey.act", "hplasblu.act",
    "hplasgrn.act", "hplasred.act", "hred.act", "htan.act", "hwhite.act",
    "hyellow.act", "interface.act", "io.act", "mars.act", "moon.act",
    "objects.act", "plasblue.act", "plasgrn.act", "plasred.act", "tan.act",
    "titan.act", "venus.act", "white.act",
)

_STOCK_ACT_BYTES = 768
_STOCK_ACT_BLOB_SHA256 = "f33ca06ffa4082900448bfb9f9b75b333d8b0dcd890be3e83be75b6a83f3a97d"
_STOCK_ACT_BLOB_ZLIB_B64 = "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"


def normalize_act_name(name: os.PathLike | str) -> str:
    value = os.path.basename(os.fspath(name)).strip().lower()
    if value and not value.endswith(".act"):
        value += ".act"
    return value


def stock_palette_names() -> tuple[str, ...]:
    return STOCK_ACT_NAMES


def has_stock_palette(name: os.PathLike | str) -> bool:
    return normalize_act_name(name) in STOCK_ACT_NAMES


def _all_stock_bytes() -> bytes:
    raw = zlib.decompress(base64.b64decode(_STOCK_ACT_BLOB_ZLIB_B64))
    expected = len(STOCK_ACT_NAMES) * _STOCK_ACT_BYTES
    if len(raw) != expected:
        raise ValueError(
            f"Embedded stock ACT blob decoded to {len(raw)} bytes, expected {expected}"
        )
    if hashlib.sha256(raw).hexdigest() != _STOCK_ACT_BLOB_SHA256:
        raise ValueError("Embedded stock ACT blob failed SHA-256 validation")
    return raw


def get_stock_act_bytes(name: os.PathLike | str) -> bytes | None:
    key = normalize_act_name(name)
    try:
        index = STOCK_ACT_NAMES.index(key)
    except ValueError:
        return None
    raw = _all_stock_bytes()
    start = index * _STOCK_ACT_BYTES
    return raw[start:start + _STOCK_ACT_BYTES]


def get_stock_palette(name: os.PathLike | str) -> list[tuple[int, int, int]] | None:
    raw = get_stock_act_bytes(name)
    if raw is None:
        return None
    return [tuple(raw[i:i + 3]) for i in range(0, _STOCK_ACT_BYTES, 3)]


# Names used by the TextureManager API.
STOCK_PALETTE_NAMES = STOCK_ACT_NAMES


def get_stock_palette_bytes(name: str) -> bytes:
    """The exact 768-byte RGB payload of a stock palette; KeyError if unknown."""
    raw = get_stock_act_bytes(name)
    if raw is None:
        raise KeyError(f"Unknown stock palette: {name}")
    return raw
