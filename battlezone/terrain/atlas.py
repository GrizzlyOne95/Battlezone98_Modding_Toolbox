"""Redux terrain atlases: the detail-atlas CSV and the Ogre materials that name the atlas.

A Redux TRN's ``[Atlases] MaterialName`` names an Ogre material (usually
``import * from "BZTerrainBase.material"`` plus ``set_texture_alias DiffuseMap
<atlas>``) and a CSV of the same name. Each CSV row is a legacy tile name and
its rectangle in the atlas, in fractions of the image, top-left origin::

    ,0,0,0.25,0.25                  <- header row: no name, the cell size
    PM11S0.MAP,0,0,0.25,0.25
    PM00S0.MAP,0.25,0,0.25,0.25

Legacy MAP files store rows bottom-up, so an atlas cell is the tile flipped
vertically (checked against the stock Mars atlas and 1.5's ma01da0.map).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

__all__ = ["AtlasCell", "read_atlas_csv", "read_atlas_default", "MaterialDef", "parse_materials", "read_materials",
           "tile_level", "tile_family"]

_LEVEL = re.compile(r"^(.*?)(\d)(\.map)?$", re.IGNORECASE)


@dataclass(frozen=True)
class AtlasCell:
    name: str
    u: float
    v: float
    width: float
    height: float

    def box(self, image_width: int, image_height: int) -> Tuple[int, int, int, int]:
        """Pixel box (left, top, right, bottom) in an image of that size."""
        left = int(round(self.u * image_width))
        top = int(round(self.v * image_height))
        right = int(round((self.u + self.width) * image_width))
        bottom = int(round((self.v + self.height) * image_height))
        return left, top, max(right, left + 1), max(bottom, top + 1)


def read_atlas_csv(path) -> Dict[str, AtlasCell]:
    """Named cells by upper-cased name. The nameless header row is skipped."""
    cells: Dict[str, AtlasCell] = {}
    text = Path(path).read_text(encoding="cp1252", errors="replace")
    for number, raw in enumerate(text.splitlines(), 1):
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) < 5 or not parts[0]:
            continue
        try:
            u, v, w, h = (float(p) for p in parts[1:5])
        except ValueError as exc:
            raise ValueError(f"{Path(path).name} line {number}: {raw!r} is not NAME,u,v,width,height") from exc
        cells.setdefault(parts[0].upper(), AtlasCell(parts[0], u, v, w, h))
    return cells


def read_atlas_default(path) -> Optional[AtlasCell]:
    """The nameless header row's cell: the tile Redux draws for a MAT slot the TRN leaves undefined."""
    text = Path(path).read_text(encoding="cp1252", errors="replace")
    for raw in text.splitlines():
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) >= 5 and not parts[0]:
            try:
                u, v, w, h = (float(p) for p in parts[1:5])
            except ValueError:
                return None
            return AtlasCell("", u, v, w, h)
    return None


def tile_level(name: str) -> int:
    """Mip level of a legacy tile name: the digit before ``.map`` (``PM00S3.MAP`` -> 3), else 0."""
    match = _LEVEL.match(os.path.basename(name))
    return int(match.group(2)) if match else 0


def tile_family(name: str) -> str:
    """The name without its level digit and extension, upper-cased (``pm00s3.map`` -> ``PM00S``)."""
    base = os.path.basename(name)
    match = _LEVEL.match(base)
    stem = match.group(1) if match else os.path.splitext(base)[0]
    return stem.upper()


@dataclass
class MaterialDef:
    name: str
    parent: Optional[str] = None
    aliases: Dict[str, str] = field(default_factory=dict)   # lower-cased alias -> texture
    textures: List[str] = field(default_factory=list)       # ``texture`` lines, in order
    path: Optional[str] = None

    @property
    def diffuse(self) -> Optional[str]:
        """The colour texture: ``DiffuseMap`` alias, else the first ``texture``."""
        return self.aliases.get("diffusemap") or (self.textures[0] if self.textures else None)


def _strip(line: str) -> str:
    return line.split("//", 1)[0].strip()


def _unquote(token: str) -> str:
    return token.strip().strip('"').strip("'")


def parse_materials(text: str, path: Optional[str] = None) -> List[MaterialDef]:
    """Top-level ``material`` blocks of an Ogre .material script."""
    out: List[MaterialDef] = []
    depth = 0
    current: Optional[MaterialDef] = None
    for raw in text.splitlines():
        line = _strip(raw)
        if not line:
            continue
        tokens = line.replace("{", " { ").replace("}", " } ").split()
        if depth == 0 and tokens and tokens[0] == "material" and len(tokens) > 1:
            header = line[len("material"):].split("{", 1)[0]
            name, _, parent = header.partition(":")
            current = MaterialDef(_unquote(name), _unquote(parent) or None, path=path)
            out.append(current)
        elif current is not None and tokens:
            keyword = tokens[0].lower()
            if keyword == "set_texture_alias" and len(tokens) >= 3:
                current.aliases.setdefault(tokens[1].lower(), _unquote(tokens[2]))
            elif keyword == "texture" and len(tokens) >= 2 and tokens[1] not in ("{", "}"):
                current.textures.append(_unquote(tokens[1]))
        depth += tokens.count("{") - tokens.count("}")
        if depth <= 0:
            depth = 0
    return out


def read_materials(folder, recursive: bool = False) -> Dict[str, MaterialDef]:
    """Every material defined in ``folder``'s .material files, by lower-cased name (first wins)."""
    folder = Path(folder)
    found: Dict[str, MaterialDef] = {}
    pattern = "**/*" if recursive else "*"
    for path in sorted(folder.glob(pattern)):
        if path.is_file() and path.suffix.lower() == ".material":
            text = path.read_text(encoding="utf-8", errors="replace")
            for material in parse_materials(text, str(path)):
                found.setdefault(material.name.lower(), material)
    return found
