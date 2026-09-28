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
Ogre material whose texture holds the sheet. :class:`StaDocument` edits a
table in place: comment and unrecognised lines, and whatever follows an
entry's columns on its line, are kept as written.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, replace
from typing import Iterable, List, Optional, Tuple

__all__ = ["SpriteEntry", "StaEntry", "StaDocument", "read_stb", "write_stb", "read_sta", "format_sta_entry",
           "validate_sta_entry", "find_entry", "STB_RECORD_SIZE", "SPRITE_TABLES", "MAX_SPRITES"]

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


def _parse_sta_line(raw: str) -> Tuple[Optional[StaEntry], int]:
    """The entry on one ``.sta`` line and where its columns end (-1 if none)."""
    match = _STA_LINE.match(raw.split("#", 1)[0])
    if not match:
        return None, -1
    name, material, u, v, w, h, iw, ih, flags = match.groups()
    entry = StaEntry(name, material, int(u), int(v), int(w), int(h), int(iw), int(ih),
                     int(flags, 0) if flags else 0)
    return entry, match.end()


def read_sta(text: str) -> List[StaEntry]:
    """Entries of a Redux ``.sta``; ``#`` comments and blank lines are skipped."""
    out = []
    for raw in text.splitlines():
        entry, _end = _parse_sta_line(raw)
        if entry is not None:
            out.append(entry)
    return out


def format_sta_entry(entry: StaEntry) -> str:
    """One ``.sta`` line in the stock ``spritea.st`` column layout."""
    numbers = (entry.u, entry.v, entry.width, entry.height, entry.image_width, entry.image_height)
    return (f'{chr(34) + entry.name + chr(34):<34} {entry.material:<16}'
            + "".join(f" {n:5d}" for n in numbers) + f" 0x{entry.flags:08x}")


def validate_sta_entry(entry: StaEntry) -> List[str]:
    """Problems that would stop the line reading back as the same entry."""
    problems = []
    if not entry.name or any(c in entry.name for c in '"#\r\n'):
        problems.append("the name must be non-empty, without quotes or #")
    if not entry.material or any(c.isspace() or c in '"#' for c in entry.material):
        problems.append("the material must be one word, without quotes or #")
    if min(entry.u, entry.v, entry.width, entry.height) < 0:
        problems.append("u, v, width and height cannot be negative")
    if entry.image_width <= 0 or entry.image_height <= 0:
        problems.append("the reference image size must be positive")
    if not 0 <= entry.flags <= 0xFFFFFFFF:
        problems.append("flags must fit in 32 bits")
    return problems


class StaDocument:
    """A ``.sta`` as lines, editable entry by entry without losing its comments.

    Entries are addressed by their index among the entry lines (the order of
    :attr:`entries`). New entries go after the last entry line.
    """

    def __init__(self, text: str = ""):
        self.newline = "\r\n" if "\r\n" in text else "\n"
        self.trailing_newline = not text or text.endswith(("\n", "\r"))
        # [line text, entry or None, text after the entry's columns]
        self._lines: List[list] = []
        for raw in text.splitlines():
            entry, end = _parse_sta_line(raw)
            self._lines.append([raw, entry, raw[end:] if entry is not None else ""])

    @property
    def entries(self) -> List[StaEntry]:
        return [line[1] for line in self._lines if line[1] is not None]

    def _position(self, index: int) -> int:
        found = [i for i, line in enumerate(self._lines) if line[1] is not None]
        if not 0 <= index < len(found):
            raise IndexError(f"no sprite entry {index}")
        return found[index]

    def replace(self, index: int, entry: StaEntry) -> None:
        line = self._lines[self._position(index)]
        if entry != line[1]:
            line[0], line[1] = format_sta_entry(entry) + line[2], entry

    def add(self, entry: StaEntry) -> int:
        """Insert after the last entry line; returns the new entry's index."""
        count = len(self.entries)
        at = self._position(count - 1) + 1 if count else len(self._lines)
        self._lines.insert(at, [format_sta_entry(entry), entry, ""])
        return count

    def delete(self, index: int) -> None:
        del self._lines[self._position(index)]

    def text(self) -> str:
        body = self.newline.join(line[0] for line in self._lines)
        return body + self.newline if self.trailing_newline and self._lines else body


def find_entry(entries: Iterable[SpriteEntry], name: str) -> Optional[SpriteEntry]:
    wanted = name.lower()
    return next((e for e in entries if e.name.lower() == wanted), None)
