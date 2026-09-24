"""TRN terrain descriptions.

A TRN is INI-style text (cp1252): ``[Section]`` headers followed by
``Key = Value`` lines. ``//`` and ``;`` start comments. Sections can repeat
(``[TextureType3]`` ... and, in some stock files, ``[Size]``); keys are
case-insensitive. The first ``[Size]`` section is the one the engine uses.

:class:`TRNDocument` keeps every section and entry in file order with line
numbers, so both simple lookups and validation (duplicate sections, line
endings) work from one parse.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple, Union

__all__ = ["TRNEntry", "TRNSection", "TRNSize", "TRNDocument", "read_trn", "parse_number",
           "ZONE_WORLD_SIZE", "LEGACY_ZONE_BITS"]

ZONE_WORLD_SIZE = 1280.0          # metres per terrain zone
LEGACY_ZONE_BITS = 7              # the engine computes (int)(size * 0.1) >> 7

_HEADER = re.compile(r"^\s*\[([^\]]*)\]")
_TEXTURE_TYPE = re.compile(r"texturetype(\d+)", re.IGNORECASE)


def parse_number(value: str) -> Optional[float]:
    """``"5120"``, ``"5120.0f"`` -> 5120.0; anything else -> None."""
    text = value.strip().rstrip("fF")
    try:
        return float(text)
    except ValueError:
        return None


def _strip_comment(line: str) -> str:
    return line.split("//", 1)[0].split(";", 1)[0]


@dataclass
class TRNEntry:
    key: str
    value: str
    line: int


@dataclass
class TRNSection:
    name: str
    line: int
    entries: List[TRNEntry] = field(default_factory=list)

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """First value for ``key`` (case-insensitive)."""
        wanted = key.lower()
        for entry in self.entries:
            if entry.key.lower() == wanted:
                return entry.value
        return default

    def get_all(self, key: str) -> List[str]:
        wanted = key.lower()
        return [e.value for e in self.entries if e.key.lower() == wanted]

    def number(self, key: str, default: Optional[float] = None) -> Optional[float]:
        value = self.get(key)
        parsed = parse_number(value) if value is not None else None
        return default if parsed is None else parsed

    def as_dict(self) -> Dict[str, str]:
        """Lower-cased keys; the first occurrence of a key wins."""
        out: Dict[str, str] = {}
        for entry in self.entries:
            out.setdefault(entry.key.lower(), entry.value)
        return out


@dataclass(frozen=True)
class TRNSize:
    width: Optional[float]
    depth: Optional[float]
    min_x: float = 0.0
    min_z: float = 0.0
    height: Optional[float] = None


@dataclass
class TRNDocument:
    sections: List[TRNSection] = field(default_factory=list)
    line_endings: str = "crlf"                 # "crlf", "lf", "cr" or "mixed"
    path: Optional[str] = None

    # --- parsing ------------------------------------------------------------
    @classmethod
    def parse(cls, text: str, path: Optional[str] = None) -> "TRNDocument":
        doc = cls(path=path, line_endings=_line_endings(text))
        current: Optional[TRNSection] = None
        for number, raw in enumerate(text.splitlines(), 1):
            header = _HEADER.match(raw)
            if header:
                current = TRNSection(header.group(1).strip(), number)
                doc.sections.append(current)
                continue
            line = _strip_comment(raw).strip()
            if not line or "=" not in line or current is None:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key:
                current.entries.append(TRNEntry(key, value.strip(), number))
        return doc

    @classmethod
    def read(cls, path: Union[str, os.PathLike]) -> "TRNDocument":
        with open(path, "r", encoding="cp1252", errors="replace", newline="") as stream:
            return cls.parse(stream.read(), os.fspath(path))

    # --- lookups ------------------------------------------------------------
    def __iter__(self) -> Iterator[TRNSection]:
        return iter(self.sections)

    def sections_named(self, name: str) -> List[TRNSection]:
        wanted = name.lower()
        return [s for s in self.sections if s.name.lower() == wanted]

    def section(self, name: str) -> Optional[TRNSection]:
        """The first section with this name (the one the engine reads)."""
        found = self.sections_named(name)
        return found[0] if found else None

    def get(self, section: str, key: str, default: Optional[str] = None) -> Optional[str]:
        found = self.section(section)
        return found.get(key, default) if found is not None else default

    def duplicate_sections(self, name: str) -> List[TRNSection]:
        """Repeats after the first section of this name."""
        return self.sections_named(name)[1:]

    # --- well-known values ----------------------------------------------------
    @property
    def size(self) -> TRNSize:
        found = self.section("size")
        if found is None:
            return TRNSize(None, None)
        return TRNSize(found.number("width"), found.number("depth"), found.number("minx", 0.0),
                       found.number("minz", 0.0), found.number("height"))

    def zone_counts(self) -> Optional[Tuple[int, int]]:
        """Terrain zones from the first ``[Size]``, as the engine computes them.

        None unless Width/Depth exist and are exact multiples of 1280 m (the
        engine refuses other terrains).
        """
        size = self.size
        if size.width is None or size.depth is None:
            return None
        zones_x = int(size.width * 0.1) >> LEGACY_ZONE_BITS
        zones_z = int(size.depth * 0.1) >> LEGACY_ZONE_BITS
        if zones_x <= 0 or zones_z <= 0:
            return None
        if size.width != zones_x * ZONE_WORLD_SIZE or size.depth != zones_z * ZONE_WORLD_SIZE:
            return None
        return zones_x, zones_z

    @property
    def material_name(self) -> Optional[str]:
        value = self.get("atlases", "MaterialName")
        return value.split()[0] if value else None

    @property
    def palette(self) -> Optional[str]:
        """``[Color] Palette=`` as a bare file name."""
        value = self.get("color", "palette")
        if not value:
            return None
        return os.path.basename(value.strip().strip('"').replace("\\", "/"))

    def texture_types(self) -> Dict[int, TRNSection]:
        """``[TextureTypeN]`` sections by N (first of each)."""
        out: Dict[int, TRNSection] = {}
        for section in self.sections:
            match = _TEXTURE_TYPE.fullmatch(section.name)
            if match:
                out.setdefault(int(match.group(1)), section)
        return dict(sorted(out.items()))

    def map_references(self) -> List[Tuple[str, str, str]]:
        """Every ``.map`` value as (section, key, value), in file order."""
        refs = []
        for section in self.sections:
            for entry in section.entries:
                value = entry.value.strip().strip('"').strip("'")
                if value.lower().endswith(".map"):
                    refs.append((section.name, entry.key, value))
        return refs


def read_trn(path: Union[str, os.PathLike]) -> TRNDocument:
    return TRNDocument.read(path)


def _line_endings(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    kinds = [name for name, count in (("crlf", crlf), ("lf", lf), ("cr", cr)) if count]
    if not kinds:
        return "crlf"
    return kinds[0] if len(kinds) == 1 else "mixed"
