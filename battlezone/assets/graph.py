"""Asset dependency graph for a mod folder.

Nodes are the files in the project, plus referenced names that are not in it
(stock assets, or missing ones). Edges come from the format parsers:

======================  =====================================================
``ini-mission``         mission ``.ini`` ``missionName`` -> ``.bzn`` / ``.trn``
``bzn-odf``             objects a mission places (BZN, ASCII or binary)
``bzn-trn``             a mission's same-named terrain
``odf-odf``             weapons, ordnance, payloads, build items, ...
``odf-asset``           ``geometryName`` / ``cockpitName`` / ... files
``mesh-material``       Ogre submesh materials -> the ``.material`` defining them
``mesh-skeleton``       Ogre skeleton link
``material-texture``    ``texture`` / ``set_texture_alias`` / ``cubic_texture``
``trn-terrain``         same-named ``.hg2`` / ``.mat`` / ``.lgt``
``trn-palette``         ``[Color] Palette``
``trn-texture``         ``.map`` textures a TRN names
``trn-material``        ``[Atlases] MaterialName``
``model-part``          legacy binary models: ``.vdf``/``.sdf`` -> ``.geo`` parts,
                        ``.geo`` -> textures (names embedded in the file)
``text``                any other file name mentioned in a text file
======================  =====================================================

Names resolve case-insensitively by file name anywhere in the project, like
the game's resource lookup. The graph answers "what uses this" (what breaks if
it is renamed), "what does this need", which references are not in the
project, which files nothing references, and estimated texture memory.
"""

from __future__ import annotations

import os
import re
import struct
import threading
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

__all__ = ["AssetNode", "AssetEdge", "AssetGraph", "build_graph", "kind_of", "GraphCancelled"]

KINDS: Dict[str, Tuple[str, ...]] = {
    "mission": (".bzn",),
    "mission-ini": (".ini",),
    "odf": (".odf",),
    "terrain": (".trn", ".hg2", ".mat", ".lgt", ".hgt"),
    "model": (".mesh", ".skeleton", ".xsi", ".x", ".geo", ".3ds", ".obj", ".vdf", ".sdf"),
    "material": (".material", ".program", ".cg", ".hlsl", ".glsl", ".frag", ".vert", ".compositor"),
    "texture": (".dds", ".png", ".tga", ".bmp", ".jpg", ".jpeg", ".tif", ".tiff", ".map", ".pic"),
    "palette": (".act",),
    "audio": (".wav", ".ogg", ".mp3"),
    "script": (".lua", ".inf", ".des", ".vxt", ".txt", ".cfg", ".st"),
    "archive": (".zfs", ".zip", ".pak"),
}
_KIND_BY_EXT = {ext: kind for kind, exts in KINDS.items() for ext in exts}
TEXT_EXTS = (".odf", ".material", ".program", ".inf", ".lua", ".ini", ".txt", ".des", ".vxt", ".cfg",
             ".compositor")
# Files a player or the game opens directly; nothing needs to reference them.
ROOT_KINDS = ("mission-ini",)

_MODEL_KEYS = re.compile(r"^(geometryName|cockpitName|turretName|animName\w*|\w*geometry\w*)$", re.I)
_ODF_REF_KEYS = re.compile(
    r"^(weaponName\d*|ordName|payloadName|xpl[A-Za-z]+|buildItem\d+|powerName\d*|scrapName|"
    r"explosionName|chunkName|wreckName|deathName|ejectName|podName|pilotName|soldierName\d*|"
    r"ordnanceName|shotName|mineName|dropName|config\w*)$", re.I)
_MATERIAL_DEF = re.compile(r"^\s*material\s+([^\s:{]+)", re.I | re.M)
_MATERIAL_TEX = re.compile(
    r"\b(?:texture\s+([^\s{}]+)|set_texture_alias\s+\S+\s+([^\s{}]+)|cubic_texture\s+([^\s{}]+))", re.I)
_QUOTED = re.compile(r"[\"']([^\"'\r\n]+)[\"']")
_ASSIGNED = re.compile(r"=\s*([\w.\-]+)")
BINARY_MODEL_EXTS = (".vdf", ".sdf", ".geo")
_BINARY_NAME = re.compile(rb"[A-Za-z0-9_\-]{2,}(?:\.[A-Za-z0-9]{2,4})?")


def kind_of(name: str) -> str:
    return _KIND_BY_EXT.get(os.path.splitext(name)[1].lower(), "other")


class GraphCancelled(Exception):
    pass


@dataclass
class AssetNode:
    key: str                    # project-relative path (files) or "<name>" (not in project)
    name: str                   # file name
    kind: str
    in_project: bool
    size: int = 0
    stock: bool = False         # a known stock asset (only ODFs and palettes are known)
    texture_bytes: int = 0      # estimated GPU memory for textures

    @property
    def path(self) -> str:
        return self.key if self.in_project else ""


@dataclass(frozen=True)
class AssetEdge:
    source: str
    target: str
    kind: str
    detail: str = ""            # e.g. the ODF key or material name
    line: int = 0


@dataclass
class AssetGraph:
    root: str
    nodes: Dict[str, AssetNode] = field(default_factory=dict)
    edges: List[AssetEdge] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def __post_init__(self):
        self._out: Dict[str, List[AssetEdge]] = defaultdict(list)
        self._in: Dict[str, List[AssetEdge]] = defaultdict(list)

    def _index(self) -> None:
        self._out.clear()
        self._in.clear()
        for edge in self.edges:
            self._out[edge.source].append(edge)
            self._in[edge.target].append(edge)

    # --- queries ------------------------------------------------------------
    def uses(self, key: str) -> List[AssetEdge]:
        """Direct dependencies of ``key``."""
        return list(self._out.get(key, ()))

    def used_by(self, key: str) -> List[AssetEdge]:
        """Direct dependents of ``key``: what breaks if it is renamed or removed."""
        return list(self._in.get(key, ()))

    def closure(self, key: str, reverse: bool = False) -> List[str]:
        """All keys reachable from ``key`` (dependencies, or dependents when reverse)."""
        adjacency = self._in if reverse else self._out
        seen: Set[str] = {key}
        order: List[str] = []
        queue = deque([key])
        while queue:
            current = queue.popleft()
            for edge in adjacency.get(current, ()):
                nxt = edge.source if reverse else edge.target
                if nxt not in seen:
                    seen.add(nxt)
                    order.append(nxt)
                    queue.append(nxt)
        return order

    def find(self, name: str) -> Optional[AssetNode]:
        """A node by project path or file name (case-insensitive)."""
        wanted = name.replace("\\", "/").lower()
        for node in self.nodes.values():
            if node.key.lower() == wanted or node.name.lower() == wanted:
                return node
        return None

    def not_in_project(self, include_stock: bool = False) -> List[Tuple[AssetNode, List[AssetEdge]]]:
        """Referenced names that are not project files, with who references them.

        ODFs and palettes are checked against the stock lists; for other kinds
        the toolbox cannot tell a stock asset from a missing one.
        """
        out = []
        for node in self.nodes.values():
            if node.in_project or (node.stock and not include_stock):
                continue
            refs = self.used_by(node.key)
            if refs:
                out.append((node, refs))
        return sorted(out, key=lambda item: (not _is_definitely_missing(item[0]), item[0].name.lower()))

    def missing(self) -> List[Tuple[AssetNode, List[AssetEdge]]]:
        """References that are certainly missing (not in the project and not stock)."""
        return [item for item in self.not_in_project() if _is_definitely_missing(item[0])]

    def unreferenced(self) -> List[AssetNode]:
        """Project files nothing in the project refers to (excluding entry points)."""
        out = []
        for node in self.nodes.values():
            if not node.in_project or node.kind in ROOT_KINDS or self._in.get(node.key):
                continue
            if node.kind == "mission" and not self._has_ini:
                continue   # without a mission .ini the missions are the entry points
            out.append(node)
        return sorted(out, key=lambda n: n.key.lower())

    def textures_by_memory(self) -> List[AssetNode]:
        return sorted((n for n in self.nodes.values() if n.texture_bytes),
                      key=lambda n: n.texture_bytes, reverse=True)

    def mission_texture_memory(self) -> List[Tuple[AssetNode, int, int]]:
        """``(mission, bytes, texture count)`` for the project textures each mission pulls in.

        This is the closer estimate of what one mission loads; the summary's
        ``texture_bytes`` adds up every texture in the mod as if all were
        loaded at once. Stock textures (not in the project) are not counted.
        """
        out = []
        for node in self.nodes.values():
            if node.kind != "mission" or not node.in_project:
                continue
            textures = [self.nodes[k] for k in self.closure(node.key) if k in self.nodes
                        and self.nodes[k].texture_bytes]
            out.append((node, sum(t.texture_bytes for t in textures), len(textures)))
        return sorted(out, key=lambda item: item[1], reverse=True)

    @property
    def _has_ini(self) -> bool:
        return any(n.kind == "mission-ini" and n.in_project for n in self.nodes.values())

    @property
    def files(self) -> List[AssetNode]:
        return sorted((n for n in self.nodes.values() if n.in_project), key=lambda n: n.key.lower())

    def summary(self) -> Dict[str, int]:
        return {
            "files": len(self.files),
            "references": len(self.edges),
            "missing": len(self.missing()),
            "not_in_project": len(self.not_in_project()),
            "unreferenced": len(self.unreferenced()),
            "texture_bytes": sum(n.texture_bytes for n in self.nodes.values()),
        }

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "summary": self.summary(),
            "nodes": [asdict(n) for n in self.nodes.values()],
            "edges": [asdict(e) for e in self.edges],
            "missing": [n.name for n, _ in self.missing()],
            "unreferenced": [n.key for n in self.unreferenced()],
            "warnings": list(self.warnings),
        }


def _is_definitely_missing(node: AssetNode) -> bool:
    return not node.in_project and not node.stock and node.kind in ("odf", "palette", "mission")


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[float, str], None]


class _Builder:
    def __init__(self, root: Path, cancel: Optional[threading.Event]):
        self.root = root
        self.cancel = cancel
        self.graph = AssetGraph(str(root))
        self.by_name: Dict[str, List[str]] = defaultdict(list)   # lower file name -> keys
        self.by_stem: Dict[str, List[str]] = defaultdict(list)   # lower stem -> keys
        self.material_defs: Dict[str, str] = {}                   # lower material name -> key
        self._seen_edges: Set[Tuple[str, str]] = set()

    # --- helpers --------------------------------------------------------------
    def check_cancel(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            raise GraphCancelled()

    def index_files(self) -> List[str]:
        keys = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for filename in filenames:
                full = Path(dirpath) / filename
                key = full.relative_to(self.root).as_posix()
                try:
                    size = full.stat().st_size
                except OSError:
                    size = 0
                self.graph.nodes[key] = AssetNode(key, filename, kind_of(filename), True, size)
                self.by_name[filename.lower()].append(key)
                self.by_stem[os.path.splitext(filename)[0].lower()].append(key)
                keys.append(key)
        return sorted(keys, key=str.lower)

    def resolve(self, name: str, alternatives: Sequence[str] = ()) -> Optional[str]:
        """Project key for a referenced file name, trying alternative extensions."""
        base = os.path.basename(name.strip().strip('"').strip("'").replace("\\", "/")).lower()
        if not base:
            return None
        hits = self.by_name.get(base)
        if hits:
            return hits[0]
        stem = os.path.splitext(base)[0]
        for ext in alternatives:
            hits = self.by_name.get(stem + ext)
            if hits:
                return hits[0]
        return None

    def external(self, name: str, kind: Optional[str] = None, stock: bool = False) -> str:
        base = os.path.basename(name.strip().strip('"').strip("'").replace("\\", "/"))
        key = f"<{base.lower()}>"
        node = self.graph.nodes.get(key)
        if node is None:
            self.graph.nodes[key] = AssetNode(key, base, kind or kind_of(base), False, stock=stock)
        elif stock:
            node.stock = True
        return key

    def link(self, source: str, target: Optional[str], kind: str, detail: str = "", line: int = 0) -> None:
        if not target or target == source or (source, target) in self._seen_edges:
            return
        self._seen_edges.add((source, target))
        self.graph.edges.append(AssetEdge(source, target, kind, detail, line))

    def full(self, key: str) -> Path:
        return self.root / key

    def read_text(self, key: str) -> str:
        try:
            return self.full(key).read_text(encoding="latin-1")
        except OSError as exc:
            self.graph.warnings.append(f"{key}: {exc}")
            return ""

    # --- per format -----------------------------------------------------------
    def mission_ini(self, key: str) -> None:
        text = self.read_text(key)
        match = re.search(r"^\s*missionName\s*=\s*\"?([^\"\r\n;]+)", text, re.I | re.M)
        if match:
            stem = match.group(1).strip()
            for ext in (".bzn", ".trn"):
                target = self.resolve(stem + ext)
                self.link(key, target, "ini-mission", "missionName")
        self.text_refs(key, text)

    def mission(self, key: str) -> None:
        from battlezone.bzn.scan import STOCK_SET, BZNParser

        try:
            names = BZNParser(str(self.full(key))).parse()
        except Exception as exc:  # binary variants the parser does not know
            self.graph.warnings.append(f"{key}: could not read mission ({exc})")
            names = []
        for base in sorted(set(names), key=str.lower):
            filename = f"{base}.odf"
            target = self.resolve(filename)
            if target is None:
                target = self.external(filename, "odf", stock=filename.lower() in STOCK_SET)
            self.link(key, target, "bzn-odf")
        stem = os.path.splitext(os.path.basename(key))[0]
        self.link(key, self.resolve(stem + ".trn"), "bzn-trn")

    def odf(self, key: str) -> None:
        from battlezone.bzn.scan import STOCK_SET
        from battlezone.odf.validator import parse_odf

        try:
            doc = parse_odf(self.full(key))
        except OSError as exc:
            self.graph.warnings.append(f"{key}: {exc}")
            return
        for section, entries in doc.sections.items():
            for field_key, raw, line in entries:
                value = _clean_value(raw)
                if not value:
                    continue
                if _MODEL_KEYS.match(field_key) and "." in value:
                    target = self.resolve(value, (".mesh",))
                    self.link(key, target or self.external(value, "model"), "odf-asset", field_key, line)
                elif _ODF_REF_KEYS.match(field_key) and re.fullmatch(r"[\w\-]+(\.odf)?", value, re.I):
                    filename = value if value.lower().endswith(".odf") else f"{value}.odf"
                    target = self.resolve(filename)
                    if target is None:
                        target = self.external(filename, "odf", stock=filename.lower() in STOCK_SET)
                    self.link(key, target, "odf-odf", field_key, line)
                else:
                    self._value_ref(key, value, line, field_key)

    def mesh(self, key: str) -> None:
        from battlezone.meshes.ogre import MeshError, read_mesh

        try:
            mesh = read_mesh(self.full(key))
        except (OSError, MeshError) as exc:
            self.graph.warnings.append(f"{key}: {exc}")
            return
        for sub in mesh.submeshes:
            if not sub.material:
                continue
            target = self.material_defs.get(sub.material.lower())
            self.link(key, target or self.external(sub.material, "material"), "mesh-material", sub.material)
        if mesh.skeleton:
            target = self.resolve(mesh.skeleton)
            self.link(key, target or self.external(mesh.skeleton, "model"), "mesh-skeleton")

    def material(self, key: str, text: str) -> None:
        for match in _MATERIAL_TEX.finditer(text):
            name = next(g for g in match.groups() if g)
            line = text.count("\n", 0, match.start()) + 1
            target = self.resolve(name, (".dds", ".png", ".tga"))
            self.link(key, target or self.external(name, "texture"), "material-texture", "texture", line)

    def trn(self, key: str) -> None:
        from battlezone.terrain.palettes import has_stock_palette
        from battlezone.terrain.trn import TRNDocument

        try:
            doc = TRNDocument.read(self.full(key))
        except OSError as exc:
            self.graph.warnings.append(f"{key}: {exc}")
            return
        stem = os.path.splitext(os.path.basename(key))[0]
        for ext in (".hg2", ".mat", ".lgt"):
            self.link(key, self.resolve(stem + ext), "trn-terrain", ext[1:].upper())
        if doc.palette:
            target = self.resolve(doc.palette)
            if target is None:
                target = self.external(doc.palette, "palette", stock=has_stock_palette(doc.palette))
            self.link(key, target, "trn-palette", "Palette")
        for section, field_key, value in doc.map_references():
            target = self.resolve(value, (".dds", ".png", ".tga"))
            self.link(key, target or self.external(value, "texture"), "trn-texture", f"[{section}] {field_key}")
        if doc.material_name:
            target = self.material_defs.get(doc.material_name.lower())
            self.link(key, target or self.external(doc.material_name, "material"), "trn-material",
                      "MaterialName")

    def binary_model(self, key: str) -> None:
        """Names embedded in legacy VDF/SDF/GEO files: GEO parts by name or stem, textures by name."""
        try:
            data = self.full(key).read_bytes()
        except OSError as exc:
            self.graph.warnings.append(f"{key}: {exc}")
            return
        for raw in set(_BINARY_NAME.findall(data)):
            name = raw.decode("ascii").lower()
            hits = self.by_name.get(name)
            if not hits and "." not in name and not key.lower().endswith(".geo"):
                hits = self.by_name.get(name + ".geo")
            for target in hits or ():
                self.link(key, target, "model-part", os.path.basename(target))

    def text_refs(self, key: str, text: str) -> None:
        for number, raw in enumerate(text.splitlines(), 1):
            line = raw.split("//", 1)[0]
            for token in _QUOTED.findall(line) + _ASSIGNED.findall(line):
                self._value_ref(key, token.strip(), number)

    def _value_ref(self, key: str, value: str, line: int, detail: str = "") -> None:
        """A generic mention of another project file (by name, or by stem for assets)."""
        base = os.path.basename(value.replace("\\", "/")).lower()
        if not base or len(base) < 3:
            return
        hits = self.by_name.get(base)
        if not hits and "." not in base:
            hits = [k for k in self.by_stem.get(base, ()) if kind_of(k) not in ("odf", "other")]
        for target in hits or ():
            self.link(key, target, "text", detail, line)


def _clean_value(raw: str) -> str:
    value = raw.split("//", 1)[0].strip().rstrip(";").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def _texture_bytes(path: Path) -> int:
    """Estimated GPU memory: DDS from its header, other images as RGBA8 with mips."""
    try:
        with open(path, "rb") as stream:
            head = stream.read(128)
        if head[:4] == b"DDS " and len(head) >= 128:
            height, width = struct.unpack_from("<II", head, 12)
            mips = max(1, struct.unpack_from("<I", head, 28)[0])
            fourcc = head[84:88]
            bits = struct.unpack_from("<I", head, 88)[0]
            per_pixel = {b"DXT1": 0.5, b"BC4U": 0.5, b"ATI1": 0.5}.get(fourcc)
            if per_pixel is None:
                per_pixel = 1.0 if fourcc.strip(b"\0") else max(bits, 8) / 8
            base = width * height * per_pixel
            return int(base * (4 / 3 if mips > 1 else 1))
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
        return int(width * height * 4 * 4 / 3)
    except Exception:
        return 0


def build_graph(root, progress: Optional[ProgressCallback] = None,
                cancel: Optional[threading.Event] = None) -> AssetGraph:
    """Scan ``root`` and build its :class:`AssetGraph`."""
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(f"Not a folder: {root}")
    b = _Builder(root, cancel)
    if progress:
        progress(0.0, "Indexing files")
    keys = b.index_files()

    # material definitions first, so meshes and TRNs can resolve names
    material_texts = {}
    for key in keys:
        if key.lower().endswith(".material"):
            text = b.read_text(key)
            material_texts[key] = text
            for match in _MATERIAL_DEF.finditer(text):
                b.material_defs.setdefault(match.group(1).strip().strip('"').lower(), key)

    for index, key in enumerate(keys):
        b.check_cancel()
        if progress and index % 25 == 0:
            progress(0.05 + 0.9 * index / max(len(keys), 1), key)
        node = b.graph.nodes[key]
        ext = os.path.splitext(key)[1].lower()
        try:
            if ext == ".ini":
                b.mission_ini(key)
            elif ext == ".bzn":
                b.mission(key)
            elif ext == ".odf":
                b.odf(key)
            elif ext == ".mesh":
                b.mesh(key)
            elif ext == ".material":
                b.material(key, material_texts[key])
                b.text_refs(key, material_texts[key])
            elif ext == ".trn":
                b.trn(key)
            elif ext in BINARY_MODEL_EXTS:
                b.binary_model(key)
            elif ext in TEXT_EXTS:
                b.text_refs(key, b.read_text(key))
            if node.kind == "texture" and ext != ".map":
                node.texture_bytes = _texture_bytes(b.full(key))
        except GraphCancelled:
            raise
        except Exception as exc:  # one bad file must not stop the scan
            b.graph.warnings.append(f"{key}: {exc}")
    b.graph._index()
    if progress:
        progress(1.0, "Done")
    return b.graph
