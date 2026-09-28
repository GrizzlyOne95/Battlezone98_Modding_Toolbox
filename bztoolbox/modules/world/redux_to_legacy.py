"""Redux -> Battlezone 1.5: the legacy port run backwards.

Takes a Redux world or mission folder and writes a folder 1.5 can load:

* **Terrain tiles** - every ``.map`` a ``[TextureTypeN]`` section names is cut
  out of the ``[Atlases]`` material's diffuse atlas (via its CSV), flipped to
  MAP's bottom-up rows and written at the legacy sizes: 256/128/64/32 px for
  levels 0-3 (``PM00S0.MAP`` ... ``PM00S3.MAP``), as 8-bit palette MAPs.
  Level digits the TRN leaves out (a TRN made by the legacy port only lists
  level 0) are added.
* **Palette** - 1.5 draws everything through the world palette. An ACT that
  keeps the stock shared entries (0-95, 224-255) is used as is; otherwise
  (Redux never reads the ACT, so Redux-era ACTs are often placeholders) a new
  one is built: a stock world's shared entries plus 128 colours fitted to the
  atlas. A new palette gets LUM/TBL/ALB tables transferred from that stock
  world's (read from the game's bzone.zfs).
* **TRN** - ``[Atlases]`` goes, missing levels and the new ``[Color]`` files
  are filled in; everything else is kept as written.
* **Sky** - SkyTexture/BackdropTexture, cloud and star MAPs defined by a
  material in the folder are rendered from its texture (index 0 is clear for
  clouds and stars). Names with no material are left to 1.5's stock files.
* **Heightmap, light map, mission** - HG2 -> HGT (keeping the legacy
  vertices), LGT 256 -> 128 cells per zone, BZN 2016 -> 1045; MAT is the
  same file in both games and is copied.

    bztoolbox terrain to-legacy "Polar Mars" out/polarmars
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

from battlezone.terrain import colortables as ct
from battlezone.terrain.atlas import (
    AtlasCell, MaterialDef, read_atlas_csv, read_atlas_default, read_materials, tile_family, tile_level,
)
from battlezone.terrain.palettes import get_stock_act_bytes, has_stock_palette
from battlezone.terrain.trn import TRNDocument, parse_number

LEVELS = 4
TILE_SIZES = (128, 256, 512)
MAP_FORMATS = ("indexed", "565")
MISSING_TILE_MODES = ("default", "solid", "none")
PALETTE_MODES = ("auto", "trn", "rebuild")
SKY_SECTIONS = {"sky": "sky", "clouds": "cloud", "stars": "star", "starlist": "star"}

# Redux-only files that have no use in 1.5.
REDUX_ONLY = {".ini", ".material", ".dds", ".csv", ".mesh", ".skeleton", ".program", ".cg", ".hlsl", ".glsl",
              ".png", ".tga", ".jpg", ".jpeg", ".paint", ".xcf", ".psd", ".dll", ".exe", ".zip", ".ogg", ".sta",
              ".particle", ".compositor", ".fontdef", ".overlay", ".log"}
HANDLED = {".trn", ".hg2", ".hgt", ".lgt", ".bzn", ".act", ".lum", ".tbl", ".alb"}
REPORT_NAME = "redux_to_legacy_report.txt"


@dataclass
class LegacyExportOptions:
    tile_size: int = 256                  # level 0; levels 1-3 halve it
    map_format: str = "indexed"           # "indexed" (every renderer) or "565" (hardware 16-bit only)
    palette: str = "auto"                 # auto | trn | rebuild | path to an .act
    base_world: Optional[str] = None      # stock world for shared entries and tables (default: from the TRN)
    dither: bool = False
    color_tables: bool = True             # LUM/TBL/ALB for a new palette
    sky_size: int = 256
    game_dir: Optional[str] = None        # Redux install: stock tables and stock atlases
    search_dirs: Sequence[str] = ()       # more folders for materials, CSVs and textures
    heightmaps: bool = True
    bzn: bool = True
    allow_bzn_loss: bool = False
    missing_tiles: str = "default"        # MAT slots the TRN lacks: default (Redux's tile) | solid | none
    sprites: bool = True                  # Redux .sta sprites (e.g. a custom SunTexture) -> 1.5 sprite tables
    legacy_dir: Optional[str] = None      # Battlezone 1.5 install: the stock sprite tables to extend


@dataclass
class LegacyExportReport:
    source: str
    output: str
    written: List[str] = field(default_factory=list)
    copied: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    palette: Optional[str] = None
    tiles: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    def lines(self) -> List[str]:
        out = [f"{self.source} -> {self.output}"]
        if self.palette:
            out.append(f"palette: {self.palette}")
        out.append(f"{self.tiles} terrain tile MAP(s), {len(self.written)} file(s) written, "
                   f"{len(self.copied)} copied, {len(self.skipped)} left out")
        out += [f"note: {n}" for n in dict.fromkeys(self.notes)]
        out += [f"WARNING: {w}" for w in dict.fromkeys(self.warnings)]
        out += [f"ERROR: {e}" for e in dict.fromkeys(self.errors)]
        if self.skipped:
            out.append("left out (Redux only): " + ", ".join(sorted(self.skipped, key=str.lower)))
        return out


# ---------------------------------------------------------------------------
# MAP encoding
# ---------------------------------------------------------------------------

def encode_indexed_map(indices: np.ndarray) -> bytes:
    """(h, w) palette indices, already bottom-up -> MAP bytes (type 0)."""
    height, width = indices.shape
    return struct.pack("<HHI", width, 0, height) + np.ascontiguousarray(indices, dtype=np.uint8).tobytes()


def encode_rgb_map(image: Image.Image, transparent: bool = False) -> bytes:
    """RGBA image, already bottom-up -> R5G6B5 MAP (or A4R4G4B4 when ``transparent``)."""
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint16)
    r, g, b, a = rgba[..., 0], rgba[..., 1], rgba[..., 2], rgba[..., 3]
    if transparent:
        words, fmt = ((a >> 4) << 12) | ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4), 1
    else:
        words, fmt = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3), 2
    height, width = words.shape
    return struct.pack("<HHI", width * 2, fmt, height) + words.astype("<u2").tobytes()


# ---------------------------------------------------------------------------
# TRN rewrite
# ---------------------------------------------------------------------------

_HEADER = re.compile(r"^\s*\[([^\]]*)\]")
_ENTRY = re.compile(r"^(\s*)([^=\s;/][^=]*?)(\s*=\s*)([^\s;/]+)(.*)$")
_TEXTURE_TYPE = re.compile(r"texturetype\d+$", re.IGNORECASE)
_LEVEL_DIGIT = re.compile(r"(\d)(\.map)$", re.IGNORECASE)
EXTRA_COMMENT = "// Added by the Redux -> 1.5 port: 1.5 draws a checkerboard where Redux drew its default tile"


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text or "\n" not in text else "\n"


def rewrite_trn_for_legacy(text: str, *, color: Optional[Dict[str, str]] = None, levels: int = LEVELS,
                           extra: Optional[Dict[int, List[Tuple[str, str]]]] = None,
                           values: Optional[Dict[Tuple[str, str], str]] = None) -> Tuple[str, List[str]]:
    """Redux TRN text -> 1.5 TRN text, plus a list of what changed.

    Drops ``[Atlases]``; after each level-0 texture entry adds the level 1..3
    entries its section lacks; sets the ``[Color]`` keys in ``color``
    (Palette/Luma/Translucency/Alpha), adding the section if needed; appends
    ``extra`` entries (key, value) to ``[TextureTypeN]`` sections, adding the
    sections that do not exist; ``values`` {(section, key): value} (lower-case)
    replaces existing entries. Comments and layout of everything else are kept.
    """
    changes: List[str] = []
    if "\r\r\n" in text:
        # Some editors save CR CR LF; splitlines() would read each as two line breaks.
        text = text.replace("\r\r\n", "\r\n")
        changes.append("CR CR LF line endings normalised to CR LF")
    nl = _newline(text)
    lines = text.splitlines()
    color = dict(color or {})

    # Keys present in each section (by header position), to know what to add.
    keys_by_section: Dict[int, set] = {}
    current = -1
    for number, raw in enumerate(lines):
        if _HEADER.match(raw):
            current = number
            keys_by_section[current] = set()
            continue
        match = _ENTRY.match(raw.split("//", 1)[0])
        if match and current >= 0:
            keys_by_section[current].add(match.group(2).strip().lower())

    out: List[str] = []
    section, section_at = "", -1
    added_levels = 0
    color_seen = set()
    color_done = False
    extra = {int(k): list(v) for k, v in (extra or {}).items() if v}
    extra_done = set()

    def flush_extra(type_index: int) -> None:
        entries = extra.get(type_index)
        if not entries or type_index in extra_done:
            return
        blanks = 0
        while out and not out[-1].strip():
            out.pop()
            blanks += 1
        out.append(EXTRA_COMMENT)
        out.extend(f"{k:<15}= {v}" for k, v in entries)
        out.extend([""] * max(1, blanks))
        extra_done.add(type_index)
        changes.append(f"[TextureType{type_index}]: added {len(entries)} entries for tiles the MAT uses")

    def section_type(name: str) -> Optional[int]:
        return int(name[len("texturetype"):]) if _TEXTURE_TYPE.fullmatch(name) else None

    def flush_color() -> None:
        nonlocal color_done
        missing = [k for k in color if k.lower() not in color_seen]
        if missing:
            while out and not out[-1].strip():
                out.pop()
            out.extend(f"{k}={color[k]}" for k in missing)
            out.append("")
            changes.append("[Color]: added " + ", ".join(f"{k}={color[k]}" for k in missing))
        color_done = True

    for number, raw in enumerate(lines):
        header = _HEADER.match(raw)
        if header:
            if section.lower() == "color" and not color_done:
                flush_color()
            if section_type(section) is not None:
                flush_extra(section_type(section))
            section, section_at = header.group(1).strip(), number
            if section.lower() == "atlases":
                changes.append("removed [Atlases] (Redux only)")
                continue
            out.append(raw)
            continue
        if section.lower() == "atlases":
            continue
        match = _ENTRY.match(raw)
        replacement = (values or {}).get((section.lower(), match.group(2).strip().lower())) if match else None
        if replacement is not None and match.group(4) != replacement:
            changes.append(f"[{section}] {match.group(2).strip()}: {match.group(4)} -> {replacement}")
            raw = f"{match.group(1)}{match.group(2)}{match.group(3)}{replacement}{match.group(5)}"
            match = _ENTRY.match(raw)
        if match and section.lower() == "color":
            key = match.group(2).strip()
            wanted = next((k for k in color if k.lower() == key.lower()), None)
            if wanted is not None:
                color_seen.add(key.lower())
                if match.group(4) != color[wanted]:
                    changes.append(f"[Color] {key}: {match.group(4)} -> {color[wanted]}")
                raw = f"{match.group(1)}{match.group(2)}{match.group(3)}{color[wanted]}{match.group(5)}"
        out.append(raw)
        if match and _TEXTURE_TYPE.fullmatch(section):
            key, value = match.group(2).strip(), match.group(4)
            digit = _LEVEL_DIGIT.search(value)
            if key.endswith("0") and digit and digit.group(1) == "0":
                present = keys_by_section.get(section_at, set())
                for level in range(1, levels):
                    new_key = key[:-1] + str(level)
                    if new_key.lower() in present:
                        continue
                    new_value = value[:digit.start(1)] + str(level) + value[digit.end(1):]
                    out.append(f"{match.group(1)}{new_key}{match.group(3)}{new_value}")
                    added_levels += 1
    if section.lower() == "color" and not color_done:
        flush_color()
    if section_type(section) is not None:
        flush_extra(section_type(section))
    for type_index in sorted(set(extra) - extra_done):
        while out and not out[-1].strip():
            out.pop()
        out += ["", f"[TextureType{type_index}]"]
        flush_extra(type_index)
        changes[-1] = f"added [TextureType{type_index}] for tiles the MAT uses"
    if color and not color_done and not any(_HEADER.match(l) and _HEADER.match(l).group(1).strip().lower() == "color"
                                            for l in lines):
        while out and not out[-1].strip():
            out.pop()
        out += ["", "[Color]"] + [f"{k}={v}" for k, v in color.items()]
        changes.append("added [Color]: " + ", ".join(f"{k}={v}" for k, v in color.items()))
    if added_levels:
        changes.append(f"added {added_levels} texture entries for levels 1-{levels - 1}")
    return nl.join(out) + nl, changes


# ---------------------------------------------------------------------------
# Finding things
# ---------------------------------------------------------------------------

class _Finder:
    """Case-insensitive file lookup over the source folder, extra folders and the game's assets."""

    def __init__(self, source: Path, search_dirs: Sequence, game_dir: Optional[Path]):
        self.roots = [source] + [Path(d) for d in search_dirs if d]
        self.game_dir = game_dir
        self._index: Optional[Dict[str, Path]] = None
        self._game_index: Optional[Dict[str, Path]] = None
        self._materials: Optional[Dict[str, MaterialDef]] = None
        self._game_materials: Optional[Dict[str, MaterialDef]] = None

    @staticmethod
    def _walk(roots: Iterable[Path]) -> Dict[str, Path]:
        index: Dict[str, Path] = {}
        for root in roots:
            if not root.is_dir():
                continue
            for dirpath, _dirs, files in os.walk(root):
                for name in files:
                    index.setdefault(name.lower(), Path(dirpath) / name)
        return index

    def _assets(self) -> List[Path]:
        if not self.game_dir:
            return []
        return [p for p in (self.game_dir / "BZ_ASSETS", self.game_dir / "addon") if p.is_dir()]

    def file(self, name: str) -> Optional[Path]:
        key = os.path.basename(name.replace("\\", "/")).lower()
        if self._index is None:
            self._index = self._walk(self.roots)
        found = self._index.get(key)
        if found is None and self._assets():
            if self._game_index is None:
                self._game_index = self._walk(self._assets())
            found = self._game_index.get(key)
        return found

    def texture(self, name: str) -> Optional[Path]:
        found = self.file(name)
        if found is not None:
            return found
        stem = os.path.splitext(os.path.basename(name))[0]
        for ext in (".dds", ".tga", ".png", ".bmp", ".jpg"):
            found = self.file(stem + ext)
            if found is not None:
                return found
        return None

    def material(self, name: str) -> Optional[MaterialDef]:
        key = name.lower()
        if self._materials is None:
            self._materials = {}
            for root in self.roots:
                if root.is_dir():
                    for k, v in read_materials(root, recursive=True).items():
                        self._materials.setdefault(k, v)
        if key in self._materials:
            return self._materials[key]
        if self._assets():
            if self._game_materials is None:
                self._game_materials = {}
                for root in self._assets():
                    for k, v in read_materials(root, recursive=True).items():
                        self._game_materials.setdefault(k, v)
            return self._game_materials.get(key)
        return None

    def local_material(self, name: str) -> Optional[MaterialDef]:
        self.material("")
        return (self._materials or {}).get(name.lower())


def _open_image(path: Path) -> Image.Image:
    if path.suffix.lower() == ".dds":
        # Pillow decodes uncompressed DDS pixel by pixel in Python (minutes for 8192x8192).
        from bztoolbox.modules.textures.bcpack import Unsupported, read_dds

        try:
            levels, _info = read_dds(path, max_levels=1)
            return Image.fromarray(levels[0], "RGBA")
        except Unsupported:
            pass                               # block-compressed: Pillow decodes those in C
    limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = None      # 8192x8192 atlases are normal
    try:
        with Image.open(path) as image:
            image.load()
            return image.convert("RGBA")
    finally:
        Image.MAX_IMAGE_PIXELS = limit


def stock_color_tables(game_dir: Optional[Path], world: str) -> Optional[Dict[str, bytes]]:
    """``{"lum": ..., "tbl": ..., "alb": ...}`` for a stock world from the game's bzone.zfs."""
    if not game_dir:
        return None
    archive_path = Path(game_dir) / "bzone.zfs"
    if not archive_path.is_file():
        return None
    from battlezone.archives.zfs import ZFSArchive

    try:
        archive = ZFSArchive(archive_path)
        names = {e.name.lower(): e.name for e in archive}
        tables = {}
        for kind in ct.TABLE_KINDS:
            name = f"{world}.{kind}"
            if name not in names:
                return None
            data = archive.read(names[name])
            if len(data) != 65536:
                return None
            tables[kind] = data
        return tables
    except (OSError, ValueError, KeyError):
        return None


def _world_from_trn(doc: TRNDocument) -> Optional[str]:
    for key in ("Luma", "Translucency", "Alpha", "Palette"):
        value = doc.get("color", key)
        if value:
            stem = os.path.splitext(os.path.basename(value.strip().strip('"')))[0].lower()
            if stem in ct.STOCK_WORLDS:
                return stem
    return None


# ---------------------------------------------------------------------------
# The port
# ---------------------------------------------------------------------------

@dataclass
class _Tile:
    name: str            # as the TRN spells it
    level: int
    family: str
    cell: AtlasCell
    atlas: Path


@dataclass
class _Sky:
    name: str
    kind: str            # sky | cloud | star
    texture: Path


@dataclass
class _Atlas:
    texture: Path
    cells: Dict[str, AtlasCell]
    default: Optional[AtlasCell]      # the CSV's nameless row: Redux's tile for undefined MAT slots


def _plan_tiles(doc: TRNDocument, finder: _Finder, report: LegacyExportReport, atlases: Dict[Path, Image.Image],
                layouts: Optional[Dict[str, _Atlas]] = None) -> List[_Tile]:
    material_name = doc.material_name
    trn_name = Path(doc.path or "?").name
    if not material_name:
        report.notes.append(f"{trn_name}: no [Atlases] section; its texture MAPs are expected beside it")
        return []
    material = finder.material(material_name)
    if material is None or not material.diffuse:
        report.errors.append(f"{trn_name}: material {material_name} (from [Atlases]) was not found in the folder"
                             + ("" if finder.game_dir else " (set the game folder to look in Redux's assets)"))
        return []
    texture = finder.texture(material.diffuse)
    if texture is None:
        report.errors.append(f"{trn_name}: atlas texture {material.diffuse} of material {material.name} was not found")
        return []
    csv_path = finder.file(material_name + ".csv")
    if csv_path is None:
        report.errors.append(f"{trn_name}: {material_name}.csv (the atlas layout) was not found")
        return []
    cells = read_atlas_csv(csv_path)
    if layouts is not None:
        layouts[(doc.path or "").lower()] = _Atlas(texture, cells, read_atlas_default(csv_path))
    by_family: Dict[str, AtlasCell] = {}
    for key, cell in cells.items():
        by_family.setdefault(tile_family(key), cell)
    if texture not in atlases:
        atlases[texture] = _open_image(texture)
        width, height = atlases[texture].size
        report.notes.append(f"atlas {texture.name}: {width}x{height}, {len(cells)} cells in {csv_path.name}")

    tiles: List[_Tile] = []
    missing: List[str] = []
    for section in doc.texture_types().values():
        keys = {e.key.lower() for e in section.entries}
        for entry in section.entries:
            value = entry.value.strip().strip('"')
            if not value.lower().endswith(".map"):
                continue
            cell = cells.get(value.upper()) or by_family.get(tile_family(value))
            if cell is None:
                if finder.file(value) is None:
                    missing.append(value)
                continue
            tiles.append(_Tile(value, tile_level(value), tile_family(value), cell, texture))
            # The levels rewrite_trn_for_legacy adds for a TRN that lists only level 0.
            digit = _LEVEL_DIGIT.search(value)
            if entry.key.endswith("0") and digit and digit.group(1) == "0":
                for level in range(1, LEVELS):
                    if entry.key[:-1].lower() + str(level) not in keys:
                        name = value[:digit.start(1)] + str(level) + value[digit.end(1):]
                        tiles.append(_Tile(name, level, tile_family(value), cell, texture))
    if missing:
        report.errors.append(f"{trn_name}: {len(missing)} texture(s) are in neither {csv_path.name} nor the folder: "
                             + ", ".join(sorted(set(missing))[:12]) + (" ..." if len(set(missing)) > 12 else ""))
    return tiles


def _plan_sky(doc: TRNDocument, finder: _Finder, report: LegacyExportReport) -> List[_Sky]:
    out: List[_Sky] = []
    for section, _key, value in doc.map_references():
        kind = SKY_SECTIONS.get(section.lower())
        if kind is None:
            continue
        if finder.file(value) is not None:
            continue                                 # a legacy MAP is already in the folder
        material = finder.local_material(value)
        if material is None or not material.diffuse:
            report.notes.append(f"{value} ([{section}]) has no material in the folder; 1.5's stock file is used")
            continue
        texture = finder.texture(material.diffuse)
        if texture is None:
            report.warnings.append(f"{value}: texture {material.diffuse} of its material was not found")
            continue
        out.append(_Sky(value, kind, texture))
    return out


def _resolve_palette(docs: List[TRNDocument], finder: _Finder, options: LegacyExportOptions,
                     report: LegacyExportReport, samples: Callable[[], np.ndarray]
                     ) -> Tuple[np.ndarray, str, bool, Optional[Path], str]:
    """(palette, ACT file name, is_new, source ACT path, base world)."""
    trn_palette = next((d.palette for d in docs if d.palette), None)
    world = (options.base_world or next((w for w in map(_world_from_trn, docs) if w), None) or "mars").lower()
    if world not in ct.STOCK_WORLDS:
        raise ValueError(f"base world {world!r} is not one of {', '.join(ct.STOCK_WORLDS)}")
    reference = ct.palette_array(get_stock_act_bytes(world + ".act"))
    choice = options.palette

    if choice not in PALETTE_MODES:
        path = Path(choice)
        data = path.read_bytes()
        if len(data) < 768:
            raise ValueError(f"{path.name} is not a 256-colour ACT ({len(data)} bytes)")
        palette = ct.palette_array(data)
        safe, why = ct.palette_is_legacy_safe(palette, reference)
        if not safe:
            report.warnings.append(f"{path.name}: {why}")
        return palette, trn_palette or path.name, True, path, world

    if trn_palette and has_stock_palette(trn_palette) and choice != "rebuild":
        report.notes.append(f"{trn_palette} is a stock 1.5 palette; used as is")
        return ct.palette_array(get_stock_act_bytes(trn_palette)), trn_palette, False, None, world

    source = finder.file(trn_palette) if trn_palette else None
    if choice in ("auto", "trn") and source is not None:
        palette = ct.palette_array(source.read_bytes())
        safe, why = ct.palette_is_legacy_safe(palette, reference)
        if safe or choice == "trn":
            (report.notes if safe else report.warnings).append(f"{source.name}: {why}")
            return palette, trn_palette, True, source, world
        report.warnings.append(f"{source.name} cannot be used in 1.5 ({why}); building a new palette from the atlas")
    elif choice == "trn":
        raise ValueError(f"the TRN's palette {trn_palette or '(none)'} was not found; choose auto or rebuild")

    name = trn_palette if trn_palette and not has_stock_palette(trn_palette) else \
        Path(docs[0].path or "world").stem + ".act"
    palette = ct.build_world_palette(samples(), reference)
    report.notes.append(f"built {name}: {world}.act's shared entries (0-95, 224-255) + 128 colours fitted to the atlas")
    return palette, name, True, None, world


def port_redux_to_legacy(source, output, options: Optional[LegacyExportOptions] = None,
                         log: Optional[Callable[[str], None]] = None) -> LegacyExportReport:
    """Port a Redux world/mission folder to a 1.5 folder. See the module docstring."""
    options = options or LegacyExportOptions()
    source, output = Path(source), Path(output)
    say = log or (lambda _m: None)
    report = LegacyExportReport(str(source), str(output))
    if not source.is_dir():
        raise NotADirectoryError(f"{source} is not a folder")
    if source.resolve() == output.resolve():
        raise ValueError("write the 1.5 port to a different folder than the Redux source")
    if options.tile_size not in TILE_SIZES:
        raise ValueError(f"tile size must be one of {TILE_SIZES}")
    if options.map_format not in MAP_FORMATS:
        raise ValueError(f"map format must be one of {MAP_FORMATS}")
    if options.missing_tiles not in MISSING_TILE_MODES:
        raise ValueError(f"missing tiles must be one of {MISSING_TILE_MODES}")
    output.mkdir(parents=True, exist_ok=True)
    game_dir = Path(options.game_dir) if options.game_dir else None
    finder = _Finder(source, options.search_dirs, game_dir)
    files = sorted((p for p in source.iterdir() if p.is_file()), key=lambda p: p.name.lower())
    trn_paths = [p for p in files if p.suffix.lower() == ".trn"]
    if not trn_paths:
        report.errors.append("no .trn in the folder")
        return report
    docs = [TRNDocument.read(p) for p in trn_paths]

    # --- plan -------------------------------------------------------------
    atlases: Dict[Path, Image.Image] = {}
    layouts: Dict[str, _Atlas] = {}
    tiles: Dict[str, _Tile] = {}
    for doc in docs:
        say(f"Reading {Path(doc.path).name}")
        for tile in _plan_tiles(doc, finder, report, atlases, layouts):
            tiles.setdefault(tile.name.lower(), tile)
    fills: Dict[str, Dict[int, List[Tuple[str, str]]]] = {}
    for doc in docs:
        extra, new_tiles = _plan_mat_fills(doc, source, layouts.get((doc.path or "").lower()), options, report)
        fills[(doc.path or "").lower()] = extra
        for tile in new_tiles:
            tiles.setdefault(tile.name.lower(), tile)
    skies: Dict[str, _Sky] = {}
    for doc in docs:
        for sky in _plan_sky(doc, finder, report):
            skies.setdefault(sky.name.lower(), sky)

    size = options.tile_size
    base_tiles: Dict[Tuple[Path, str], Image.Image] = {}
    for tile in tiles.values():
        key = (tile.atlas, tile.family)
        if key not in base_tiles:
            atlas = atlases[tile.atlas]
            crop = atlas.crop(tile.cell.box(*atlas.size))
            base_tiles[key] = crop.resize((size, size), Image.Resampling.LANCZOS)
    sky_images = {name: _open_image(sky.texture).resize((options.sky_size, options.sky_size),
                                                        Image.Resampling.LANCZOS)
                  for name, sky in skies.items()}

    sun_names = {d.get("sky", "SunTexture").strip().lower() for d in docs if (d.get("sky", "SunTexture") or "").strip()}
    legacy_dir = Path(options.legacy_dir) if options.legacy_dir else None
    stock_sprites = stock_sprite_tables(legacy_dir) if legacy_dir else None
    sheets = _plan_sprites(source, finder, report, sun_names) if options.sprites else []

    def samples() -> np.ndarray:
        # A sky fills half the screen, so it gets the weight of several tiles; a sun is small but bright.
        sky = [img for n, img in sky_images.items() if skies[n].kind == "sky"]
        suns = [s.image for s in sheets if s.has_sun]
        return np.vstack([ct.sample_pixels(base_tiles.values()),
                          ct.sample_pixels(sky, per_image=4096 * max(4, len(base_tiles) // 4), seed=1),
                          ct.sample_pixels(suns, per_image=2048, seed=2)])

    # --- palette and tables -------------------------------------------------
    indexed = options.map_format == "indexed"
    try:
        palette, act_name, new_palette, act_source, world = _resolve_palette(docs, finder, options, report, samples)
    except (OSError, ValueError) as exc:
        report.errors.append(f"palette: {exc}")
        return report
    report.palette = act_name
    color: Dict[str, str] = {}
    if new_palette:
        act_path = output / act_name
        act_path.write_bytes(ct.act_bytes(palette))
        report.written.append(act_name)
        color["Palette"] = act_name
        stem = os.path.splitext(act_name)[0]
        local_tables = {k: finder.file(f"{stem}.{k}") for k in ct.TABLE_KINDS} if act_source else {}
        if local_tables and all(local_tables.values()):
            for kind, path in local_tables.items():
                shutil.copy2(path, output / path.name)
                report.copied.append(path.name)
            color.update(Luma=local_tables["lum"].name, Translucency=local_tables["tbl"].name,
                         Alpha=local_tables["alb"].name)
        elif options.color_tables:
            stock = stock_color_tables(game_dir, world)
            if stock is None:
                report.warnings.append(f"{world}.lum/.tbl/.alb were not found (set the Redux game folder); the TRN "
                                       "keeps its colour tables, which were made for another palette, so software "
                                       "rendering and translucent effects may show wrong colours")
            else:
                base = ct.palette_array(get_stock_act_bytes(world + ".act"))
                keys = {"lum": "Luma", "tbl": "Translucency", "alb": "Alpha"}
                for kind, data in stock.items():
                    table = ct.transfer_table(np.frombuffer(data, np.uint8), base, palette, kind)
                    name = f"{stem}.{kind}"
                    (output / name).write_bytes(table.tobytes())
                    report.written.append(name)
                    color[keys[kind]] = name
                report.notes.append(f"LUM/TBL/ALB transferred from {world}'s tables onto {act_name}")

    # --- tiles ---------------------------------------------------------------
    say(f"Writing {len(tiles)} terrain tiles")
    for tile in sorted(tiles.values(), key=lambda t: t.name.lower()):
        side = max(1, size >> tile.level)
        image = base_tiles[(tile.atlas, tile.family)]
        if side != size:
            image = image.resize((side, side), Image.Resampling.LANCZOS)
        image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        if indexed:
            data = encode_indexed_map(ct.quantize(image, palette, ct.TERRAIN_INDICES, dither=options.dither))
        else:
            data = encode_rgb_map(image)
        (output / tile.name).write_bytes(data)
        report.tiles += 1

    for name, sky in sorted(skies.items()):
        image = sky_images[name].transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        clear = sky.kind != "sky"
        if indexed:
            data = encode_indexed_map(ct.quantize(image, palette, ct.TERRAIN_INDICES, dither=options.dither,
                                                  transparent_index=0 if clear else None))
        else:
            data = encode_rgb_map(image, transparent=clear)
        (output / sky.name).write_bytes(data)
        report.written.append(sky.name)
        report.notes.append(f"{sky.name}: {sky.kind} from {sky.texture.name}"
                            + (" (index 0 is clear)" if clear and indexed else ""))

    # --- sprites --------------------------------------------------------------
    known_sprites = _write_sprites(sheets, stock_sprites, output, palette, options, report, sun_names)
    values: Dict[Tuple[str, str], str] = {}
    for sun in sorted(sun_names):
        if known_sprites is not None and sun in known_sprites:
            continue
        if known_sprites is None and sun == "sun.0":
            continue
        values[("sky", "suntexture")] = "sun.0"
        why = ("its sprite could not be added: " + ("no 1.5 install with the stock sprite tables was found"
                                                    if stock_sprites is None else "no .sta entry or texture for it"))
        report.warnings.append(f"SunTexture {sun} is not a 1.5 sprite ({why}); set to the stock sun.0")

    # --- TRNs ----------------------------------------------------------------
    for path, doc in zip(trn_paths, docs):
        text = path.read_bytes().decode("cp1252", errors="replace")
        rewritten, changes = rewrite_trn_for_legacy(text, color=color, extra=fills.get(str(path).lower()),
                                                    values={**values, **star_dome_values(doc)})
        (output / path.name).write_bytes(rewritten.encode("cp1252", errors="replace"))
        report.written.append(path.name)
        report.notes += [f"{path.name}: {c}" for c in changes]

    # --- heightmaps, light maps, missions and the rest --------------------------
    stems_with_hg2 = {p.stem.lower() for p in files if p.suffix.lower() == ".hg2"}
    for path in files:
        ext = path.suffix.lower()
        try:
            if ext == ".hg2" and options.heightmaps:
                _port_heightmap(path, output, report)
            elif ext == ".hgt":
                if path.stem.lower() in stems_with_hg2 and options.heightmaps:
                    continue                          # the HG2 is converted (with this HGT's flags)
                shutil.copy2(path, output / path.name)
                report.copied.append(path.name)
            elif ext == ".lgt" and options.heightmaps:
                _port_lightmap(path, output, report)
            elif ext == ".bzn" and options.bzn:
                _port_bzn(path, output, report, options, source)
            elif ext in HANDLED or ext == ".map" and path.name.lower() in tiles:
                continue
            elif ext in REDUX_ONLY or path.name.lower() in ("thumbnail.jpg", "desktop.ini"):
                report.skipped.append(path.name)
            elif ext == ".lua":
                report.skipped.append(path.name)
                report.warnings.append(f"{path.name}: 1.5 has no Lua; missions that need it will not run")
            else:
                shutil.copy2(path, output / path.name)
                report.copied.append(path.name)
        except Exception as exc:                        # keep going; every file is reported
            report.errors.append(f"{path.name}: {exc}")
    (output / REPORT_NAME).write_text("\n".join(report.lines()) + "\n", encoding="utf-8")
    return report


_SLOT_KEY = re.compile(r"^(solid|capto(\d)_|diagonalto(\d)_)([a-d])0$", re.IGNORECASE)
_KIND_NAMES = {"S": "Solid", "C": "CapTo", "D": "DiagonalTo"}


def defined_slots(doc: TRNDocument) -> set:
    """``(type, kind, next, variant)`` slots a TRN defines at level 0; kind is S(olid), C(ap) or D(iagonal)."""
    slots = set()
    for type_index, section in doc.texture_types().items():
        for entry in section.entries:
            match = _SLOT_KEY.match(entry.key.strip())
            if not match or not entry.value.strip():
                continue
            if match.group(1).lower() == "solid":
                kind, other = "S", type_index
            else:
                kind, other = ("C", int(match.group(2))) if match.group(2) else ("D", int(match.group(3)))
            slots.add((type_index, kind, other, "abcd".index(match.group(4).lower())))
    return slots


def mat_slot_usage(entries: np.ndarray) -> Dict[Tuple[int, str, int, int], int]:
    """Cells per ``(type, kind, next, variant)`` in a MAT, the way 1.5 looks tiles up."""
    entries = np.asarray(entries, dtype=np.uint16)
    base, other = entries >> 12, (entries >> 8) & 15
    cap, variant = (entries >> 7) & 1, entries & 3
    kind = np.where(base == other, 0, np.where(cap == 1, 1, 2))
    code = ((base.astype(np.int64) * 16 + other) * 4 + kind) * 4 + variant
    values, counts = np.unique(code, return_counts=True)
    out = {}
    for value, count in zip(values.tolist(), counts.tolist()):
        variant, value = value % 4, value // 4
        kind, value = "SCD"[value % 4], value // 4
        out[(value // 16, kind, value % 16, variant)] = count
    return out


def _level_name(level0: str, level: int) -> str:
    digit = _LEVEL_DIGIT.search(level0)
    return level0[:digit.start(1)] + str(level) + level0[digit.end(1):] if digit else level0


def _plan_mat_fills(doc: TRNDocument, source: Path, layout: Optional[_Atlas], options: LegacyExportOptions,
                    report: LegacyExportReport) -> Tuple[Dict[int, List[Tuple[str, str]]], List[_Tile]]:
    """TRN entries (and tiles) for MAT slots the TRN leaves undefined.

    1.5 draws its checkerboard ``badTexture`` for a type/transition/variant
    slot no TRN key fills (a variant falls back to a lower letter, nothing
    else does); Redux draws the atlas CSV's nameless default cell instead.
    """
    trn_name = Path(doc.path or "?").name
    stem = Path(doc.path or "").stem.lower()
    mat = next((p for p in source.iterdir() if p.suffix.lower() == ".mat" and p.stem.lower() == stem), None)
    if mat is None or not doc.texture_types():
        return {}, []
    usage = mat_slot_usage(np.fromfile(mat, dtype="<u2"))
    defined = defined_slots(doc)
    beyond = sum(n for (t, _k, o, _v), n in usage.items() if t > 7 or o > 7)
    if beyond:
        report.warnings.append(f"{mat.name}: {beyond} cell(s) use texture types above 7, which 1.5 cannot draw")
    missing: Dict[Tuple[int, str, int], int] = {}
    for (t, kind, other, variant), count in usage.items():
        if t > 7 or other > 7:
            continue
        if not any((t, kind, other, v) in defined for v in range(variant + 1)):
            missing[(t, kind, other)] = missing.get((t, kind, other), 0) + count
    if not missing:
        return {}, []
    cells = sum(missing.values())
    listed = ", ".join(f"{t}{'->' + str(o) if k != 'S' else ''} {_KIND_NAMES[k]} ({n})"
                       for (t, k, o), n in sorted(missing.items()))
    if options.missing_tiles == "none":
        report.warnings.append(f"{mat.name}: {cells} cell(s) use slots {trn_name} leaves undefined; 1.5 draws them "
                               f"as a checkerboard: {listed}")
        return {}, []

    # The tile to fill with: Redux's default cell, or the base type's own solid tile.
    level0_of: Dict[str, str] = {}        # family -> the TRN's level-0 spelling
    for section in doc.texture_types().values():
        for entry in section.entries:
            value = entry.value.strip().strip('"')
            if value.lower().endswith(".map") and tile_level(value) == 0:
                level0_of.setdefault(tile_family(value), value)
    new_tiles: List[_Tile] = []
    default_name: Optional[str] = None
    if layout is not None and layout.default is not None:
        box = (layout.default.u, layout.default.v, layout.default.width, layout.default.height)
        for key, cell in layout.cells.items():
            if abs(cell.u - box[0]) + abs(cell.v - box[1]) + abs(cell.width - box[2]) + abs(cell.height - box[3]) < 1e-6 \
                    and tile_family(key) in level0_of:
                default_name = level0_of[tile_family(key)]
                break
        if default_name is None:
            prefix = os.path.commonprefix(list(level0_of))[:2] or stem[:2].upper()
            default_name = f"{prefix}DEF0.MAP"
            for level in range(LEVELS):
                new_tiles.append(_Tile(_level_name(default_name, level), level, tile_family(default_name),
                                       layout.default, layout.texture))

    extra: Dict[int, List[Tuple[str, str]]] = {}
    solid_used = default_used = 0
    for (t, kind, other), _count in sorted(missing.items()):
        fill = None
        if options.missing_tiles == "solid" or default_name is None:
            section = doc.texture_types().get(t)
            solid = section.get("SolidA0") if section is not None else None
            fill = solid.strip().strip('"') if solid else None
            solid_used += fill is not None
        if fill is None:
            fill = default_name
            default_used += fill is not None
        if fill is None:
            report.warnings.append(f"{mat.name}: nothing to fill {_KIND_NAMES[kind]} of type {t} with")
            continue
        key = "SolidA" if kind == "S" else f"{_KIND_NAMES[kind]}{other}_A"
        extra.setdefault(t, []).extend((f"{key}{level}", _level_name(fill, level)) for level in range(LEVELS))
    how = []
    if default_used:
        how.append(f"the atlas default tile {tile_family(default_name)} (what Redux draws)")
    if solid_used:
        how.append("each type's own solid tile")
    report.notes.append(f"{mat.name}: {cells} cell(s) use slots {trn_name} leaves undefined (1.5 would draw a "
                        f"checkerboard); filled with {' and '.join(how)}: {listed}")
    return extra, new_tiles


LEGACY_INSTALL_GUESSES = (r"C:\Program Files (x86)\Battlezone", r"C:\Program Files\Battlezone",
                          r"C:\GOG Games\Battlezone", r"C:\Games\Battlezone")
SPRITE_SHEET_MAX = 256              # 1.5's stock sprite sheets are 128 px; 1998 cards stop at 256
SUN_SPRITE_SIZE = 64                # sun.0 is 63x63 and is drawn at its table size in screen pixels
STAR_DOME_RADIUS = 1000             # [Stars] Radius in every stock 1.5 TRN (and the engine default)


def star_dome_values(doc: TRNDocument) -> Dict[Tuple[str, str], str]:
    """``[Stars]`` Radius/SizeNN scaled down to 1.5's dome, keeping every angular size.

    1.5 (``Submit_Stars``) draws each star as a camera polygon ``Radius`` away,
    ``Size / 2`` across; the stock dome is 1000. Redux skyboxes are built
    further out (ROTBD: a cube of 8192 faces at 4096), which 1.5 does not draw.
    """
    stars = doc.section("stars")
    radius = stars.number("radius") if stars is not None else None
    if not radius or radius <= STAR_DOME_RADIUS:
        return {}
    factor = STAR_DOME_RADIUS / radius
    out = {("stars", "radius"): str(STAR_DOME_RADIUS)}
    for entry in stars.entries:
        if re.fullmatch(r"size\d+", entry.key, re.IGNORECASE):
            size = parse_number(entry.value)
            if size is not None:
                out[("stars", entry.key.lower())] = str(max(1, int(round(size * factor))))
    return out


def default_legacy_dir() -> Optional[str]:
    """A Battlezone 1.5 install (bzone.exe beside its ZFS archives), if one is in a usual place."""
    for guess in LEGACY_INSTALL_GUESSES:
        folder = Path(guess)
        if (folder / "bzone.exe").is_file() and any(folder.glob("*.zfs")):
            return str(folder)
    return None


def stock_sprite_tables(legacy_dir: Optional[Path]) -> Optional[Dict[str, List["SpriteEntry"]]]:
    """``{"spritea.stb": [...], "sprite8.stb": [...]}`` from a 1.5 install's archives."""
    from battlezone.archives.zfs import ZFSArchive
    from battlezone.images.sprites import SPRITE_TABLES, read_stb

    if not legacy_dir or not Path(legacy_dir).is_dir():
        return None
    found: Dict[str, List] = {}
    archives = sorted(Path(legacy_dir).glob("*.zfs"), key=lambda p: (p.name.lower() != "bzone152.zfs", p.name.lower()))
    for path in archives:
        try:
            archive = ZFSArchive(path)
            for entry in archive:
                name = entry.name.lower()
                if name in SPRITE_TABLES and name not in found:
                    found[name] = read_stb(archive.read(entry.name))
        except (OSError, ValueError, KeyError):
            continue
    return found if len(found) == len(SPRITE_TABLES) else None


@dataclass
class _SpriteSheet:
    texture: Path
    image: Image.Image
    entries: List["StaEntry"]
    has_sun: bool


def _plan_sprites(source: Path, finder: _Finder, report: LegacyExportReport, sun_names: set) -> List[_SpriteSheet]:
    """Redux .sta entries in the folder, grouped by the texture of their material."""
    from battlezone.images.sprites import read_sta

    sta_files = sorted(p for p in source.iterdir() if p.is_file() and p.suffix.lower() == ".sta")
    if not sta_files:
        if any(name not in ("", "sun.0") for name in sun_names):
            report.notes.append("no .sta sprite table in the folder for the custom SunTexture")
        return []
    by_texture: Dict[Path, List] = {}
    missing = []
    for path in sta_files:
        for entry in read_sta(path.read_text(encoding="cp1252", errors="replace")):
            material = finder.material(entry.material)
            texture = finder.texture(material.diffuse) if material is not None and material.diffuse else None
            if texture is None:
                missing.append(entry.name)
                continue
            by_texture.setdefault(texture, []).append(entry)
    if missing:
        report.notes.append(f"{len(missing)} sprite(s) in {', '.join(p.name for p in sta_files)} have no material "
                            f"or texture in the folder and were left out (add their folder with --search): "
                            + ", ".join(missing[:8]) + (" ..." if len(missing) > 8 else ""))
    return [_SpriteSheet(texture, _open_image(texture), entries,
                         any(e.name.lower() in sun_names for e in entries))
            for texture, entries in by_texture.items()]


def _pow2(value: float) -> int:
    side = 8
    while side < value and side < SPRITE_SHEET_MAX:
        side *= 2
    return side


def _write_sprites(sheets: List[_SpriteSheet], stock: Optional[Dict[str, List]], output: Path, palette: np.ndarray,
                   options: LegacyExportOptions, report: LegacyExportReport, sun_names: set) -> Optional[set]:
    """Sprite sheet MAPs and the stock tables plus the Redux entries. Returns the sprite names 1.5 will know."""
    from battlezone.images.sprites import MAX_SPRITES, SpriteEntry, find_entry, write_stb

    if stock is None:
        if sheets:
            report.warnings.append(f"{sum(len(s.entries) for s in sheets)} Redux sprite(s) were not converted: "
                                   "no Battlezone 1.5 install with the stock sprite tables was found (set the 1.5 "
                                   "game folder); 1.5 draws unknown sprites as nothing")
        return None
    stock_sun = find_entry(stock["spritea.stb"], "sun.0")
    taken = {e.texture.lower() for table in stock.values() for e in table}

    def unique(stem: str) -> str:
        name, n = stem[:8], 0
        while name in taken:
            n += 1
            name = f"{stem[:8 - len(str(n))]}{n}"
        taken.add(name)
        return name

    added: Dict[str, List[SpriteEntry]] = {"spritea.stb": [], "sprite8.stb": []}
    for sheet in sheets:
        # Sizes follow the .sta's own pixel space (its declared image size), which is what the
        # sprite rectangles, and so the on-screen sizes, were authored in, not the texture's resolution.
        width, height = sheet.entries[0].image_width, sheet.entries[0].image_height
        scale = min(1.0, SPRITE_SHEET_MAX / max(width, height, 1))
        for entry in (e for e in sheet.entries if e.name.lower() in sun_names):
            scale = min(scale, SUN_SPRITE_SIZE / max(entry.width, entry.height, 1))
        sheet_w, sheet_h = _pow2(width * scale), _pow2(height * scale)
        stem = re.sub(r"[^A-Za-z0-9_]", "", sheet.texture.stem).lower() or "sprite"
        image = sheet.image.resize((sheet_w, sheet_h), Image.Resampling.LANCZOS)   # sprite MAPs are top-down
        # Direct3D draws sprites alpha-blended, and the stock 16-bit sheets are A4R4G4B4, so the
        # spritea.stb sheet keeps the alpha; the software renderer only has the index-255 key.
        d3d, soft = unique(stem), unique(stem[:7] + "8")
        (output / f"{d3d.upper()}.MAP").write_bytes(encode_rgb_map(image, transparent=True))
        (output / f"{soft.upper()}.MAP").write_bytes(encode_indexed_map(
            ct.quantize(image, palette, ct.TERRAIN_INDICES, dither=options.dither, transparent_index=255)))
        report.written += [f"{d3d.upper()}.MAP", f"{soft.upper()}.MAP"]
        for entry in sheet.entries:
            fx, fy = sheet_w / entry.image_width, sheet_h / entry.image_height
            existing = find_entry(stock["spritea.stb"], entry.name)
            if entry.name.lower() in sun_names:
                flags = stock_sun.flags if stock_sun else 0
            else:
                flags = existing.flags & ~0xF if existing else 0
            rect = dict(u=int(round(entry.u * fx)), v=int(round(entry.v * fy)),
                        width=max(1, int(round(entry.width * fx))), height=max(1, int(round(entry.height * fy))))
            added["spritea.stb"].append(SpriteEntry(entry.name, d3d, flags=flags, **rect))
            added["sprite8.stb"].append(SpriteEntry(entry.name, soft, flags=flags, **rect))
        report.notes.append(f"sprite sheet {sheet.texture.name} -> {d3d.upper()}.MAP (A4R4G4B4) and "
                            f"{soft.upper()}.MAP (8-bit, software), {sheet_w}x{sheet_h}: "
                            + ", ".join(e.name for e in sheet.entries[:6]) + (" ..." if len(sheet.entries) > 6 else ""))
    if not added["spritea.stb"]:
        return {e.name.lower() for e in stock["spritea.stb"]}
    known = set()
    for table_name, table in stock.items():
        merged = list(table)
        index = {e.name.lower(): i for i, e in enumerate(merged)}
        for entry in added[table_name]:
            if entry.name.lower() in index:
                merged[index[entry.name.lower()]] = entry
            else:
                index[entry.name.lower()] = len(merged)
                merged.append(entry)
        if len(merged) > MAX_SPRITES:
            report.warnings.append(f"{table_name}: {len(merged)} sprites; 1.5 reads the first {MAX_SPRITES}")
        (output / table_name).write_bytes(write_stb(merged))
        report.written.append(table_name)
        known |= {e.name.lower() for e in merged[:MAX_SPRITES]}
    report.notes.append(f"{len(added['spritea.stb'])} Redux sprite(s) added to 1.5's stock sprite tables (spritea.stb, sprite8.stb). "
                        "These replace the stock tables for everything while installed; merge them with any other "
                        "mod's tables")
    return known


def _port_heightmap(path: Path, output: Path, report: LegacyExportReport) -> None:
    from battlezone.terrain.hg2 import read_hg2_header
    from bztoolbox.modules.terrain_generator.heightmap_convert import convert_hg2_to_hgt

    target = output / (path.stem + ".hgt")
    flags = next((p for p in path.parent.iterdir()
                  if p.suffix.lower() == ".hgt" and p.stem.lower() == path.stem.lower()), None)
    if flags is not None:
        header = read_hg2_header(path)
        if flags.stat().st_size != header.zones_x * header.zones_z * 0x8000:
            flags = None
    result = convert_hg2_to_hgt(path, target, flags_from=flags, overflow="clamp")
    report.written.append(target.name)
    report.notes += [f"{path.name}: {n}" for n in result.notes]
    report.warnings += [f"{path.name}: {w}" for w in result.warnings]


def _port_lightmap(path: Path, output: Path, report: LegacyExportReport) -> None:
    from battlezone.terrain.lgt import read_lgt, write_lgt

    lightmap, zones_x, zones_z, zone_size = read_lgt(path)
    if zone_size == 128:
        shutil.copy2(path, output / path.name)
        report.copied.append(path.name)
        return
    write_lgt(output / path.name, lightmap[::2, ::2], zones_x, zones_z)
    report.written.append(path.name)
    report.notes.append(f"{path.name}: 256 -> 128 light cells per zone (every other cell)")


def _port_bzn(path: Path, output: Path, report: LegacyExportReport, options: LegacyExportOptions,
              source: Path) -> None:
    from battlezone.bzn.version_convert import DEFAULT_15_VERSION, ConversionError, convert_bzn

    odf_dirs = [str(source)] + [str(d) for d in options.search_dirs if d]
    try:
        result = convert_bzn(path, "1.5", odf_dirs=odf_dirs, allow_loss=options.allow_bzn_loss)
    except ConversionError as exc:
        report.errors.append(f"{path.name}: {exc}")
        if exc.result is not None:
            report.errors += [f"{path.name}: {line}" for line in exc.result.summary_lines(detail=3)[1:]
                              if line.startswith(("LOSS", "    ", "VERIFY"))]
        return
    if result.source_version <= DEFAULT_15_VERSION:
        shutil.copy2(path, output / path.name)
        report.copied.append(path.name)
        report.notes.append(f"{path.name}: already version {result.source_version}")
        return
    (output / path.name).write_bytes(result.data)
    report.written.append(path.name)
    report.notes.append(f"{path.name}: version {result.source_version} -> {result.target_version}, "
                        f"{result.objects} objects")
    report.warnings += [f"{path.name}: {a}" for a in result.ambiguous]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_game_dir() -> Optional[str]:
    try:
        from bztoolbox import external

        found = external.detect_game_installs()
        return str(found[0]) if found else None
    except Exception:
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bztoolbox terrain to-legacy",
        description="Port a Battlezone 98 Redux world or mission folder to Battlezone 1.5: atlas -> MAP tiles, "
                    "palette and LUM/TBL/ALB, TRN, sky, HG2 -> HGT, LGT and BZN.")
    parser.add_argument("source", help="Redux folder (TRN, atlas material/CSV/texture, HG2, BZN ...)")
    parser.add_argument("output", help="new folder for the 1.5 files")
    parser.add_argument("--palette", default="auto",
                        help="auto (default), trn (use the TRN's ACT as is), rebuild, or an .act file")
    parser.add_argument("--base-world", choices=ct.STOCK_WORLDS,
                        help="stock world for the shared palette entries and colour tables (default: from the TRN)")
    parser.add_argument("--tile-size", type=int, default=256, choices=TILE_SIZES, help="level-0 tile size (256)")
    parser.add_argument("--format", dest="map_format", default="indexed", choices=MAP_FORMATS,
                        help="indexed (every renderer, default) or 565 (hardware 16-bit only)")
    parser.add_argument("--dither", action="store_true", help="Floyd-Steinberg dithering when quantising")
    parser.add_argument("--no-tables", action="store_true", help="do not write LUM/TBL/ALB for a new palette")
    parser.add_argument("--game-dir", help="Battlezone 98 Redux install (default: detected)")
    parser.add_argument("--legacy-dir", help="Battlezone 1.5 install, for the stock sprite tables (default: detected)")
    parser.add_argument("--no-sprites", action="store_true", help="do not convert .sta sprites (a custom SunTexture "
                                                                  "becomes sun.0)")
    parser.add_argument("--search", action="append", default=[], metavar="DIR",
                        help="more folders with materials, CSVs, textures or ODFs (repeatable)")
    parser.add_argument("--no-heightmaps", action="store_true", help="leave HG2/LGT alone")
    parser.add_argument("--no-bzn", action="store_true", help="leave BZNs alone")
    parser.add_argument("--missing-tiles", default="default", choices=MISSING_TILE_MODES,
                        help="MAT slots the TRN leaves undefined (1.5 draws a checkerboard): fill with the atlas "
                             "default tile like Redux (default), the type's solid tile, or leave them (none)")
    parser.add_argument("--allow-bzn-loss", action="store_true", help="write BZNs even if values have no 1.5 field")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    options = LegacyExportOptions(
        tile_size=args.tile_size, map_format=args.map_format, palette=args.palette, base_world=args.base_world,
        dither=args.dither, color_tables=not args.no_tables, game_dir=args.game_dir or _default_game_dir(),
        search_dirs=tuple(args.search), heightmaps=not args.no_heightmaps, bzn=not args.no_bzn,
        allow_bzn_loss=args.allow_bzn_loss, missing_tiles=args.missing_tiles, sprites=not args.no_sprites,
        legacy_dir=args.legacy_dir or default_legacy_dir())
    try:
        report = port_redux_to_legacy(args.source, args.output, options, log=lambda m: print(m, flush=True))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for line in report.lines():
        print(line)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
