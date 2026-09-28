"""Sprite tables: Battlezone 1.5's binary ``.stb`` and Redux's text ``.sta``.

1.5 reads ``spritea.stb`` (Direct3D) or ``sprite8.stb`` (software) from its
archives (``ReadSpriteTableFile``). Each 52-byte record is::

    0x00  char[32]  sprite name (looked up case-insensitively, e.g. by TRN SunTexture)
    0x20  char[8]   texture: loaded as "%.8s.MAP" ("%.8s_%c.MAP" in software mode when flags & 0xF)
    0x28  u16 x4    u, v, width, height in texture pixels (width/height are pixel counts)
    0x30  u32       flags (the stock sun.0 has 0x10)

The table replaces the stock one as a whole, so a mod ships the stock
entries plus its own. An unknown name resolves to entry 0, the engine's
bad sprite. Sprite MAPs are stored top-down (unlike terrain tiles); in 8-bit
sheets index 255 (magenta) is transparent.

A Redux ``.sta`` line is::

    "NAME"  MATERIAL  u v width height image_width image_height 0xFLAGS

with pixels measured in an image of the stated size; ``MATERIAL`` names an
Ogre material whose texture holds the sheet.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, replace
from typing import Iterable, List, Optional

__all__ = ["SpriteEntry", "StaEntry", "read_stb", "write_stb", "read_sta", "find_entry", "STB_RECORD_SIZE",
           "SPRITE_TABLES", "MAX_SPRITES"]

MAX_SPRITES = 0x7FF                        # entry 0 is the engine's bad sprite; 0x800 slots in all

_RECORD = struct.Struct("<32s8s4HI")
STB_RECORD_SIZE = _RECORD.size            # 52
SPRITE_TABLES = ("spritea.stb", "sprite8.stb")
_STA_LINE = re.compile(r'^\s*"([^"]*)"\s+(\S+)\s+(-?\d+)\s+(-?\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)(?:\s+(0x[0-9a-fA-F]+|\d+))?')


def _text(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("latin-1")


@dataclass(frozen=True)
class SpriteEntry:
    name: str
    texture: str                 # up to 8 characters, without .MAP
    u: int
    v: int
    width: int
    height: int
    flags: int = 0

    def with_(self, **changes) -> "SpriteEntry":
        return replace(self, **changes)


@dataclass(frozen=True)
class StaEntry:
    name: str
    material: str
    u: int
    v: int
    width: int
    height: int
    image_width: int
    image_height: int
    flags: int = 0


def read_stb(data: bytes) -> List[SpriteEntry]:
    if len(data) % STB_RECORD_SIZE:
        raise ValueError(f"sprite table is {len(data)} bytes, not a multiple of {STB_RECORD_SIZE}")
    out = []
    for offset in range(0, len(data), STB_RECORD_SIZE):
        name, texture, u, v, w, h, flags = _RECORD.unpack_from(data, offset)
        out.append(SpriteEntry(_text(name), _text(texture), u, v, w, h, flags))
    return out


def write_stb(entries: Iterable[SpriteEntry]) -> bytes:
    out = bytearray()
    for e in entries:
        name, texture = e.name.encode("latin-1"), e.texture.encode("latin-1")
        if len(name) > 31:
            raise ValueError(f"sprite name {e.name!r} is longer than 31 characters")
        if len(texture) > 8:
            raise ValueError(f"sprite texture {e.texture!r} is longer than 8 characters")
        out += _RECORD.pack(name, texture, e.u, e.v, e.width, e.height, e.flags)
    return bytes(out)


def read_sta(text: str) -> List[StaEntry]:
    """Entries of a Redux ``.sta``; ``#`` comments and blank lines are skipped."""
    out = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0]
        match = _STA_LINE.match(line)
        if not match:
            continue
        name, material, u, v, w, h, iw, ih, flags = match.groups()
        out.append(StaEntry(name, material, int(u), int(v), int(w), int(h), int(iw), int(ih),
                            int(flags, 0) if flags else 0))
    return out


def find_entry(entries: Iterable[SpriteEntry], name: str) -> Optional[SpriteEntry]:
    wanted = name.lower()
    return next((e for e in entries if e.name.lower() == wanted), None)
