"""Port a Battlezone 1.5 model (``.vdf`` / ``.sdf`` + ``.geo`` parts + ``.map``
textures) to the Ogre assets Redux loads: ``<model>.mesh``, ``<model>.skeleton``,
``<model>.material`` and one diffuse texture per legacy texture.

Conventions, taken from the stock Redux meshes that are straight conversions
of their 1.5 models (hbptow, hbchar, obhavc, obheph, hvsrb, hvrckt, ...):

* one bone per part, named exactly as the part, parented as in the VDF/SDF;
  parts whose parent is WORLD are root bones (no extra model bone). Bone
  position and orientation are the part's local transform.
* every vertex is baked into model space (the bind pose) and weighted 1.0 to
  its part's bone; one submesh per material, however many parts share it.
* handedness: Ogre = legacy with X negated. Positions ``(-x, y, z)``; bone
  orientations are the mirrored rotation ``M R M`` (``M = diag(-1, 1, 1)``).
  GEO face order is kept as is (the mirror turns it into Ogre's
  counter-clockwise front face); legacy normals point inward, so the Ogre
  normal is ``-(M n)``.
* UVs are copied unchanged (``.map`` rows are top first, like DDS/PNG).
* one Ogre vertex per GEO vertex and UV; normals default to the average of
  the (unit) face normals meeting at that position within the part, which
  is the closest match to the stock conversions' normals.
* vertex format as stock: buffer 0 float3 position + float3 normal, buffer 1
  ARGB colour (white) + float2 UV; 16-bit indices unless a submesh needs more.
* VDF band 0 is the model, band 4 (lod slot 1) the cockpit; both are ported,
  the cockpit on ``BZBaseCockpit`` materials. Low-detail band 8 and the
  damage bands are not. Hardpoints, the eyepoint, headlight masks and
  emitters get bones but no geometry.
* the ANIM chunk becomes one empty ``seqNN`` animation per sequence (what
  all 30 straight conversions carry; the game moves the bones itself from
  the VDF/SDF). Persons (pilots) instead get the named skeletal animations
  Redux plays on them (``idle``, ``runForward``, ``stand2Kneel``, ...), keyed
  from their ANIM sequences, as DivisionByZero's BZRModelPorter does.
* a VDF whose cockpit or eyepoint animates (pilots, walkers), or a turret
  or howitzer (Redux ships avartl_c, svturr_c, ...), writes the
  cockpit to its own ``<model>_fp`` / ``_c`` / ``_cockpit`` mesh, each
  cockpit part hanging from the model part in its slot; persons also get a
  sniper scope (a screen quad, a quad on the gun, or faces textured
  ``__scope``) on Redux's ``scope`` material.

The VDF/SDF and GEO files stay in the mod: Redux still reads them for
collision, hardpoints and the ANIM keys that drive the bones. The ODF needs
no change when the mesh is named after the VDF/SDF.

Not converted: damage states, low-detail models.
"""

from __future__ import annotations

import io
import math
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from battlezone.meshes.legacy import (AnimSequence, AnimTrack, BwdModel, GeoFile, ModelError, Part, read_geo,
                                      read_sdf, read_vdf)
from battlezone.meshes.ogre import Geometry, OgreMesh, SubMesh, VertexBuffer, VertexElement, write_mesh
from battlezone.meshes.ogre_skeleton import Animation, Bone, Keyframe, Skeleton, Track, write_skeleton

__all__ = ["PortOptions", "PortedPart", "PortResult", "AssetSource", "build_port", "build_geo_port", "write_port",
           "planned_files", "port_legacy_model", "port_file", "odf_model", "legacy_archives", "resolve_palette", "main",
           "INVISIBLE_CLASSES", "COCKPIT_BAND", "PERSON_ANIMATIONS", "cockpit_suffix", "PORTABLE_SUFFIXES"]

# Classes whose .geo the game never draws: headlight mask, eyepoint,
# hardpoints, flame/smoke/dust emitters (bzbwd2.nonrendering_class_id_set).
INVISIBLE_CLASSES = frozenset({38, 40, 70, 71, 72, 73, 74, 75, 76, 77})
HARDPOINT_CLASSES = frozenset({70, 71, 72, 73, 74})
HEADLIGHT_CLASS = 38
EYEPOINT_CLASS = 40
COCKPIT_BAND = 4
WHITE = 0xFFFFFFFF
IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
PORTABLE_SUFFIXES = (".vdf", ".sdf", ".geo", ".odf", ".map")
LoadBytes = Callable[[str], Optional[bytes]]

# Cockpit mesh names Redux asks for (strings in the exe); every other model
# uses <model>_cockpit. cvartl/cvturr are deliberately absent.
COCKPIT_SUFFIXES = {"avartl": "_c", "bvartl": "_c", "svartl": "_c", "avturr": "_c", "bvturr": "_c",
                    "svturr": "_c", "avwalk": "_c", "bvwalk": "_c", "cvwalk": "_c", "svwalk": "_c",
                    "aspilo": "_fp", "bspilo": "_fp", "cspilo": "_fp", "sspilo": "_fp", "bsheav": "_fp"}

# Person ANIM sequence -> Redux animation: (sequence index, name, length in
# seconds, seconds the sequence's frames are spread over). Names and times
# are BZRModelPorter's; sequences 9-11 are Redux additions a 1.5 pilot does
# not have, so those animations are written empty.
PERSON_ANIMATIONS: Tuple[Tuple[int, str, float, float], ...] = (
    (3, "fireRecoilSniper", 1 / 30, 1 / 30),     # crouched (scoped) pose
    (2, "idle", 1.5, 1.5),                       # standing pose
    (9, "idleParachute", 59 / 30, 59 / 30),
    (11, "jump", 1.2, 1.2),
    (10, "landParachute", 7 / 6, 7 / 6),
    (8, "death1", 1.0, 1.0),                     # sniped
    (4, "runForward", 0.63, 0.63),
    (5, "runBackward", 0.9, 0.9),
    (6, "runLeft", 0.9, 0.9),
    (7, "runRight", 0.9, 0.9),
    (0, "stand2Kneel", 1.0, 29 / 30),
    (1, "kneel2stand", 1.0, 29 / 30),
)
MOVEMENT_SEQUENCES = frozenset({4, 5, 6, 7})
SCOPE_MATERIAL = "scope"          # stock BZ_ASSETS_CORE/common/programs/scope.material
_SCOPE = "\0scope"                # group key of scope faces
# Fixed scope placement on screen (x, y in units of the scope scale), from BZRModelPorter.
SCOPE_PLACEMENT = {"american": (2.975, 0.23), "soviet": (2.58, 0.27)}

# ODF classLabel -> model kind (BZRModelPorter's lists).
TURRET_CLASSES = frozenset({"turret", "turrettank", "howitzer"})
VDF_CLASSES = frozenset({"apc", "hover", "howitzer", "minelayer", "sav", "scavenger", "tug", "turrettank", "walker",
                         "wingman", "armory", "constructionrig", "factory", "producer", "recycler", "turret",
                         "person", "ammopack", "camerapod", "daywrecker", "powerup", "repairkit", "dropoff",
                         "torpedo", "wpnpower"})
SDF_CLASSES = frozenset({"animbuilding", "artifact", "barracks", "commtower", "geyser", "i76building", "portal",
                         "powerplant", "repairdepot", "scrapfield", "scrapsilo", "shieldtower", "supplydepot",
                         "i76building2", "flare", "i76sign", "magnet", "proximity", "spawnpnt", "spraybomb",
                         "weaponmine", "scrap"})


@dataclass
class PortOptions:
    bands: Optional[Sequence[int]] = None      # None: VDF (0, 4), SDF (0,)
    material_names: str = "model"              # "model": <model>_<tex>; "texture": <tex> (stock style)
    normals: str = "smooth"                    # "smooth", "flat" or "stored" (the GEO's own normals)
    texture_format: str = "png"                # "png", "dds" or "none"
    headlights: bool = True                    # add HLGT<n>_ffffff bones at headlight-mask parts
    face_colours: bool = False                 # vertex colour from the GEO face colour instead of white
    flat_colours: bool = False                 # every face from a palette of GEO face colours, no .map
    person: Optional[bool] = None              # None: the name's second letter is "s" (aspilo, sspilo)
    animations: Optional[bool] = None          # person skeletal animations; None: when a person
    cockpit_files: Optional[bool] = None       # separate cockpit mesh; None: when it animates or a turret
    turret: Optional[bool] = None              # turret/howitzer: the cockpit gets its own mesh; None: a stock
                                               # name Redux asks a _c cockpit for (avartl, svturr, ...)
    pov_rotations: bool = True                 # False: the eyepoint keeps its bind rotation while running
    scope: Optional[bool] = None               # sniper scope; None: persons
    scope_type: str = "auto"                   # auto (geometry if __scope faces, else fixed), fixed, attached, geometry
    scope_nation: str = ""                     # fixed: "s..." Soviet placement, anything else American; "": the name
    scope_screen: Optional[Sequence[float]] = None      # fixed: x, y, z, scale, distance behind the camera
    scope_gun: str = ""                        # attached: the part the scope hangs from
    scope_transform: Optional[Sequence[float]] = None   # attached: right, up, front, position (12 floats)
    scope_texture: str = "__scope"             # geometry: faces with this texture use the scope material
    bounds_scale: Optional[Sequence[float]] = None      # scale the bounding box about its centre
    material_suffix: str = ""                  # material file <model><suffix>.material


@dataclass
class PortedPart:
    name: str
    parent: str                    # bone parent name, "" for a root bone
    band: int
    klass: int
    bone: int
    geo: str = ""                  # "" when the part has no geometry
    vertices: int = 0
    triangles: int = 0
    note: str = ""


@dataclass
class PortResult:
    name: str
    kind: str
    mesh: OgreMesh
    skeleton: Skeleton
    parts: List[PortedPart] = field(default_factory=list)
    materials: Dict[Tuple[str, bool], str] = field(default_factory=dict)   # (texture, cockpit) -> material
    texture_files: Dict[str, str] = field(default_factory=dict)            # texture -> output file name
    material_text: str = ""
    warnings: List[str] = field(default_factory=list)
    written: List[Path] = field(default_factory=list)
    options: PortOptions = field(default_factory=PortOptions)
    cockpit_mesh: Optional[OgreMesh] = None    # set when the cockpit gets its own mesh
    cockpit_name: str = ""                     # <model>_fp, _c or _cockpit
    flat_palette: List[Tuple[int, int, int]] = field(default_factory=list)   # the flat texture's colours
    person: bool = False
    scope: str = ""                            # "", "fixed", "attached" or "geometry"

    def meshes(self) -> List[Tuple[str, OgreMesh]]:
        out = [(self.name, self.mesh)]
        if self.cockpit_mesh is not None:
            out.append((self.cockpit_name, self.cockpit_mesh))
        return out

    @property
    def vertex_count(self) -> int:
        return sum(s.geometry.vertex_count for _, m in self.meshes() for s in m.submeshes if s.geometry)

    @property
    def triangle_count(self) -> int:
        return sum(len(s.indices) // 3 for _, m in self.meshes() for s in m.submeshes)

    def summary(self) -> str:
        submeshes = sum(len(m.submeshes) for _, m in self.meshes())
        lines = [f"{self.name} ({self.kind.upper()}{', person' if self.person else ''}): "
                 f"{len(self.skeleton.bones)} bones, {submeshes} submeshes, {self.vertex_count} vertices, "
                 f"{self.triangle_count} triangles"]
        for mesh_name, mesh in self.meshes():
            for sub in mesh.submeshes:
                lines.append(f"  {mesh_name}.mesh submesh {sub.name}: material {sub.material}, "
                             f"{sub.geometry.vertex_count if sub.geometry else 0} vertices, "
                             f"{len(sub.indices) // 3} triangles")
        for part in self.parts:
            detail = f"{part.geo}: {part.vertices} vertices, {part.triangles} triangles" if part.geo else "bone only"
            lines.append(f"  bone {part.bone} {part.name} (band {part.band}, class {part.klass}, "
                         f"parent {part.parent or '-'}): {detail}{'; ' + part.note if part.note else ''}")
        for anim in self.skeleton.animations:
            lines.append(f"  animation {anim.name}: {anim.length:.3f} s, {len(anim.tracks)} tracks")
        if self.scope:
            lines.append(f"  sniper scope: {self.scope}")
        lines.extend(f"  warning: {w}" for w in self.warnings)
        lines.extend(f"  wrote {p}" for p in self.written)
        return "\n".join(lines)


def cockpit_suffix(model: str) -> str:
    """The cockpit mesh suffix Redux looks for: ``_fp`` (pilots), ``_c`` (walkers...) or ``_cockpit``."""
    return COCKPIT_SUFFIXES.get(model.lower(), "_cockpit")


# ---------------------------------------------------------------------------
# Finding files
# ---------------------------------------------------------------------------

class AssetSource:
    """Case-insensitive lookup of loose files in folders, then in ZFS archives."""

    def __init__(self, folders: Iterable[Union[str, Path]] = (), archives: Iterable = ()):
        self._files: Dict[str, Path] = {}
        for folder in folders:
            folder = Path(folder)
            if folder.is_dir():
                for entry in folder.iterdir():
                    if entry.is_file():
                        self._files.setdefault(entry.name.lower(), entry)
        self._archives = []
        for archive in archives:
            if isinstance(archive, (str, Path)):
                from battlezone.archives.zfs import ZFSArchive
                archive = ZFSArchive(archive)
            self._archives.append(archive)

    def __call__(self, name: str) -> Optional[bytes]:
        path = self._files.get(name.lower())
        if path is not None:
            return path.read_bytes()
        for archive in self._archives:
            entry = archive.get(name) or archive.get(name.lower())
            if entry is not None:
                return archive.read(entry)
        return None


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------

Mat = List[List[float]]          # 4x4, column vectors
Rot = List[List[float]]          # 3x3, column vectors


def _local_matrix(m: Sequence[float]) -> Mat:
    right, up, front, pos = m[0:3], m[3:6], m[6:9], m[9:12]
    return [[right[0], up[0], front[0], pos[0]],
            [right[1], up[1], front[1], pos[1]],
            [right[2], up[2], front[2], pos[2]],
            [0.0, 0.0, 0.0, 1.0]]


def _mul(a: Mat, b: Mat) -> Mat:
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _apply(m: Mat, p: Sequence[float]) -> Tuple[float, float, float]:
    return tuple(m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3] for i in range(3))


def _det3(m: Mat) -> float:
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def _normal_matrix(m: Mat) -> List[List[float]]:
    """Inverse transpose of the 3x3 part (the cofactor matrix; scale is dropped by normalising)."""
    c = [[0.0] * 3 for _ in range(3)]
    for i in range(3):
        for j in range(3):
            r = [x for x in range(3) if x != i]
            s = [x for x in range(3) if x != j]
            minor = m[r[0]][s[0]] * m[r[1]][s[1]] - m[r[0]][s[1]] * m[r[1]][s[0]]
            c[i][j] = minor if (i + j) % 2 == 0 else -minor
    return c


def _unit(v: Sequence[float]) -> Tuple[float, float, float]:
    length = math.sqrt(sum(x * x for x in v))
    return (0.0, 0.0, 0.0) if length < 1e-12 else tuple(x / length for x in v)


def _quaternion(r: Sequence[Sequence[float]]) -> Tuple[float, float, float, float]:
    """(x, y, z, w) of an orthonormal 3x3 rotation (column vectors)."""
    trace = r[0][0] + r[1][1] + r[2][2]
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        w, x, y, z = 0.25 * s, (r[2][1] - r[1][2]) / s, (r[0][2] - r[2][0]) / s, (r[1][0] - r[0][1]) / s
    elif r[0][0] > r[1][1] and r[0][0] > r[2][2]:
        s = math.sqrt(1.0 + r[0][0] - r[1][1] - r[2][2]) * 2
        w, x, y, z = (r[2][1] - r[1][2]) / s, 0.25 * s, (r[0][1] + r[1][0]) / s, (r[0][2] + r[2][0]) / s
    elif r[1][1] > r[2][2]:
        s = math.sqrt(1.0 + r[1][1] - r[0][0] - r[2][2]) * 2
        w, x, y, z = (r[0][2] - r[2][0]) / s, (r[0][1] + r[1][0]) / s, 0.25 * s, (r[1][2] + r[2][1]) / s
    else:
        s = math.sqrt(1.0 + r[2][2] - r[0][0] - r[1][1]) * 2
        w, x, y, z = (r[1][0] - r[0][1]) / s, (r[0][2] + r[2][0]) / s, (r[1][2] + r[2][1]) / s, 0.25 * s
    q = _unit((x, y, z, w)) if (x or y or z or w) else (0.0, 0.0, 0.0, 1.0)
    return tuple(0.0 if abs(c) < 1e-7 else c for c in q)


def _rotation(matrix: Sequence[float]) -> Tuple[Rot, List[float]]:
    """The unit-axis rotation (rows of R) and axis lengths of a legacy local matrix."""
    axes = [matrix[0:3], matrix[3:6], matrix[6:9]]
    scale = [math.sqrt(sum(c * c for c in axis)) or 1.0 for axis in axes]
    cols = [[c / s for c in axis] for axis, s in zip(axes, scale)]
    return [[cols[j][i] for j in range(3)] for i in range(3)], scale


def _mirrored(rot: Rot) -> Rot:
    mirror = (-1.0, 1.0, 1.0)
    return [[mirror[i] * rot[i][j] * mirror[j] for j in range(3)] for i in range(3)]


def _bone_transform(matrix: Sequence[float]):
    """Ogre (position, orientation, scale) of a legacy local matrix; mirrored in X."""
    rot, scale = _rotation(matrix)
    position = (-matrix[9], matrix[10], matrix[11])
    unit = all(abs(s - 1.0) < 1e-4 for s in scale)
    return position, _quaternion(_mirrored(rot)), None if unit else tuple(scale)


def _quat_rotation(w: float, x: float, y: float, z: float) -> Rot:
    """3x3 rotation (column vectors) of a Hamilton quaternion."""
    n = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    w, x, y, z = w / n, x / n, y / n, z / n
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]]


def _slerp(a: Sequence[float], b: Sequence[float], t: float) -> Tuple[float, ...]:
    """Shortest-path spherical interpolation of two (w, x, y, z) quaternions."""
    dot = sum(p * q for p, q in zip(a, b))
    if dot < 0:
        b, dot = [-q for q in b], -dot
    if dot > 0.9995:
        out = [p + (q - p) * t for p, q in zip(a, b)]
    else:
        theta = math.acos(min(1.0, dot))
        sa, sb = math.sin((1 - t) * theta), math.sin(t * theta)
        out = [(p * sa + q * sb) / math.sin(theta) for p, q in zip(a, b)]
    n = math.sqrt(sum(c * c for c in out)) or 1.0
    return tuple(c / n for c in out)


def _rotate(q: Sequence[float], v: Sequence[float]) -> Tuple[float, float, float]:
    """Rotate ``v`` by the Ogre (x, y, z, w) quaternion ``q``."""
    x, y, z, w = q
    r = _quat_rotation(w, x, y, z)
    return tuple(sum(r[i][k] * v[k] for k in range(3)) for i in range(3))


def _sample(keys: Sequence[Tuple[int, Sequence[float]]], frame: float, rotation: bool):
    """A channel's value at ``frame``: held before the first and after the last key, else interpolated."""
    if frame <= keys[0][0]:
        return keys[0][1]
    if frame >= keys[-1][0]:
        return keys[-1][1]
    for (f0, v0), (f1, v1) in zip(keys, keys[1:]):
        if f0 <= frame <= f1:
            t = 0.0 if f1 == f0 else (frame - f0) / (f1 - f0)
            return _slerp(v0, v1, t) if rotation else tuple(a + (b - a) * t for a, b in zip(v0, v1))
    return keys[-1][1]


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def _default_bands(kind: str) -> Tuple[int, ...]:
    return (0, COCKPIT_BAND) if kind == "vdf" else (0,)


def _is_root(part: Part) -> bool:
    return part.parent.lower() in ("", "world", "null")


def _looks_like_person(name: str, kind: str) -> bool:
    """1.5 naming: the second letter of a pilot's model is "s" (aspilo, sspilo, bsheav)."""
    return kind == "vdf" and len(name) > 1 and name[1].lower() == "s"


def _resolve_parent(part: Part, chosen: Dict[str, Part]) -> Tuple[Optional[Part], bool]:
    """The included part a record hangs from (None for WORLD) and whether it was guessed.

    Cockpit parts with a model part in the same slot never get here (they
    ride that part). A record naming a parent its band leaves empty hangs
    from its band's root part; failing that, it becomes a root bone.
    """
    if _is_root(part):
        return None, False
    parent = chosen.get(part.parent.lower())
    if parent is not None and parent is not part:
        return parent, False
    roots = [p for p in chosen.values() if p.band == part.band and p is not part and _is_root(p)]
    return (roots[0] if roots else None), True


def _varies(keys) -> bool:
    return len(keys) > 1 and any(value != keys[0][1] for _, value in keys)


def _cockpit_animates(model: BwdModel, primary: Dict[int, Part], cockpit: Sequence[Part],
                      geos: Dict[int, Optional[GeoFile]]) -> bool:
    """BZRModelPorter's test for a separate cockpit mesh: a slot with cockpit
    geometry, or the eyepoint, has model-part keys that change over time."""
    drawn = {c.slot for c in cockpit if geos.get(id(c)) is not None}
    for slot, part in primary.items():
        if slot not in drawn and part.klass != EYEPOINT_CLASS:
            continue
        track = model.track(part.name)
        if track is not None and (_varies(track.positions) or _varies(track.rotations)):
            return True
    return False


def build_port(model_data: bytes, kind: str, name: str, load: LoadBytes,
               options: Optional[PortOptions] = None) -> PortResult:
    """Convert one VDF/SDF (its bytes) using ``load(filename)`` to fetch ``.geo`` parts.

    Pure: nothing is written; see :func:`write_port`.
    """
    options = options or PortOptions()
    kind = kind.lower().lstrip(".")
    if kind not in ("vdf", "sdf"):
        raise ModelError(f"expected a VDF or SDF, not {kind!r}")
    model = read_vdf(model_data) if kind == "vdf" else read_sdf(model_data)
    bands = tuple(options.bands) if options.bands is not None else _default_bands(kind)
    result = PortResult(name, kind, OgreMesh(version="MeshSerializer_v1.100", endian="little"), Skeleton(),
                        options=options)
    result.person = options.person if options.person is not None else _looks_like_person(name, kind)
    animate = options.animations if options.animations is not None else result.person

    records = [p for p in model.parts if p.band in bands and p.name.upper() != "NULL"]
    records.sort(key=lambda p: (bands.index(p.band), p.slot))
    chosen: Dict[str, Part] = {}
    for part in records:
        if part.name.lower() in chosen:
            result.warnings.append(f"part name {part.name} appears twice; the band {part.band} copy is skipped")
            continue
        chosen[part.name.lower()] = part
    parts = list(chosen.values())
    primary = {p.slot: p for p in parts if p.band == 0}
    cockpit = [p for p in parts if kind == "vdf" and p.band == COCKPIT_BAND]

    # every drawn part's .geo, read up front: the cockpit and scope choices depend on them
    geos: Dict[int, Optional[GeoFile]] = {}
    notes: Dict[int, str] = {}
    for p in parts:
        if p.klass in INVISIBLE_CLASSES:
            continue
        data = load(p.name + ".geo")
        if data is None:
            notes[id(p)] = "no .geo found"
            result.warnings.append(f"{p.name}.geo not found; the part has no geometry")
            continue
        try:
            geo = read_geo(data)
        except ModelError as exc:
            notes[id(p)] = f"unreadable .geo ({exc})"
            result.warnings.append(f"{p.name}.geo: {exc}")
            continue
        geos[id(p)] = geo if geo.faces else None

    if not cockpit:
        separate = False
    elif options.cockpit_files is not None:
        separate = options.cockpit_files
    else:
        # Redux ships every howitzer, turret tank and walker with a _c cockpit
        # (avartl_c, svturr_c, ...); BZRModelPorter left this as a TODO
        turret = options.turret if options.turret is not None else cockpit_suffix(name) == "_c"
        separate = turret or _cockpit_animates(model, primary, cockpit, geos)
    if separate:
        result.cockpit_name = name + cockpit_suffix(name)
        result.cockpit_mesh = OgreMesh(version="MeshSerializer_v1.100", endian="little")

    matrix_of = {id(p): p.matrix for p in parts}
    parent_of: Dict[int, Optional[Part]] = {}
    for p in parts:
        follows = primary.get(p.slot) if p in cockpit else None
        if follows is not None:
            # the game draws a cockpit part with the matrix of the model part in its slot
            # (BZRModelPorter; Redux's avartl has aar21bgc exactly on aar11bgc)
            parent_of[id(p)], matrix_of[id(p)] = follows, IDENTITY
            continue
        parent, guessed = _resolve_parent(p, chosen)
        parent_of[id(p)] = parent
        if guessed:
            where = f"hung from {parent.name}" if parent else "made a root bone"
            result.warnings.append(f"{p.name}: parent {p.parent} is not a ported part; {where}")
    if separate:
        for p in parts:
            parent = parent_of[id(p)]
            if p.band == 0 and p.klass == EYEPOINT_CLASS and parent is not None:
                seat = next((c for c in cockpit if c.slot == parent.slot), None)
                if seat is not None:
                    parent_of[id(p)] = seat         # the camera rides the cockpit
    if animate:
        # the pilot's gun fires from its hardpoint bone; BZRModelPorter puts it on the gun's origin
        for p in parts:
            if p.klass in HARDPOINT_CLASSES:
                matrix_of[id(p)] = IDENTITY

    # depth-first bone order, as the stock skeletons have it
    children: Dict[Optional[int], List[Part]] = {}
    for p in parts:
        parent = parent_of[id(p)]
        children.setdefault(id(parent) if parent else None, []).append(p)
    ordered: List[Part] = []

    def visit(key):
        for child in children.get(key, []):
            ordered.append(child)
            visit(id(child))
    visit(None)
    if len(ordered) != len(parts):              # a parent cycle; keep the rest as roots
        for p in parts:
            if p not in ordered:
                result.warnings.append(f"{p.name}: parent cycle; made a root bone")
                parent_of[id(p)] = None
                ordered.append(p)

    handles = {id(p): i for i, p in enumerate(ordered)}
    absolute: Dict[int, Mat] = {}
    for p in ordered:
        local = _local_matrix(matrix_of[id(p)])
        parent = parent_of[id(p)]
        absolute[id(p)] = _mul(absolute[id(parent)], local) if parent else local
        position, orientation, scale = _bone_transform(matrix_of[id(p)])
        bone = Bone(p.name, handles[id(p)], position, orientation, scale,
                    handles[id(parent)] if parent else None)
        result.skeleton.bones.append(bone)
        if scale is not None:
            result.warnings.append(f"{p.name}: scaled transform {tuple(round(s, 4) for s in scale)}; "
                                   "check the part in game")
        result.parts.append(PortedPart(p.name, parent.name if parent else "", p.band, p.klass, bone.handle,
                                       note=notes.get(id(p), "")))

    if options.headlights:
        lights = [p for p in ordered if p.klass == HEADLIGHT_CLASS and p.band == 0]
        for n, light in enumerate(lights):
            parent = parent_of[id(light)]
            position, orientation, scale = _bone_transform(light.matrix)
            result.skeleton.bones.append(Bone(f"HLGT{n}_ffffff", len(result.skeleton.bones), position,
                                              orientation, None, handles[id(parent)] if parent else None))

    # the sniper scope: which kind, if any
    scope_texture = options.scope_texture.lower()
    use_scope = options.scope if options.scope is not None else result.person
    scope_type = options.scope_type.lower() if use_scope else ""
    if scope_type == "auto":
        textured = any(f.texture.lower() == scope_texture for g in geos.values() if g for f in g.faces)
        scope_type = "geometry" if textured else "fixed"
    result.scope = scope_type

    # geometry, grouped by (texture, cockpit)
    groups: Dict[Tuple[str, bool], _Group] = {}
    palette: Dict[Tuple[int, int, int], int] = {}
    for p, info in zip(ordered, result.parts):
        geo = geos.get(id(p))
        if geo is None:
            continue
        info.geo = p.name + ".geo"
        in_cockpit = p.band == COCKPIT_BAND and kind == "vdf"
        added = _add_part(groups, geo, absolute[id(p)], handles[id(p)], in_cockpit, options, result.warnings,
                          p.name, palette, scope_texture if scope_type == "geometry" else None)
        info.vertices, info.triangles = added

    pov = next((p for p in reversed(ordered) if p.band == 0 and p.klass == EYEPOINT_CLASS), None)
    scope_bone = None
    if scope_type in ("fixed", "attached"):
        scope_bone = _add_scope(result, groups, scope_type, options, pov, ordered, handles, absolute, parent_of)

    if animate:
        result.skeleton.animations = _person_animations(model, ordered, handles, matrix_of, options, pov,
                                                        scope_bone, result.warnings)
    else:
        seen = set()
        for seq in model.sequences:                 # empty, as in every straight conversion
            if seq.index not in seen:
                seen.add(seq.index)
                result.skeleton.animations.append(Animation(f"seq{seq.index:02d}", 1.0))

    _finish(result, groups, palette, separate)
    return result


def _add_scope(result: PortResult, groups, scope_type: str, options: PortOptions, pov: Optional[Part],
               ordered: List[Part], handles, absolute, parent_of) -> Optional[Tuple[int, float]]:
    """Add the scope quad and its bone; returns (bone handle, crouch offset) for a fixed scope."""
    skeleton = result.skeleton
    handle = len(skeleton.bones)
    if scope_type == "fixed":
        if pov is None:
            result.warnings.append("no eyepoint part; the fixed sniper scope was not added")
            result.scope = ""
            return None
        if options.scope_screen:
            x, y, z, scale, behind = (float(v) for v in options.scope_screen)
        else:
            nation = (options.scope_nation or result.name)[:1].lower()
            px, py = SCOPE_PLACEMENT["soviet" if nation == "s" else "american"]
            z, behind = 0.1, 1.0
            scale = z / 6.0
            x, y = px * scale, py * scale
        # hidden behind the camera; the crouched pose (fireRecoilSniper) brings it z ahead
        local = (scale, 0, 0, 0, scale, 0, 0, 0, scale, x, y, -behind)
        frame = _mul(absolute[id(pov)], _local_matrix(local))
        pov_bone = skeleton.bones[handles[id(pov)]]
        skeleton.bones.append(Bone("scope", handle, pov_bone.position, pov_bone.orientation, None, pov_bone.parent))
        crouch = (handle, z + behind)
    else:
        gun = None
        if options.scope_gun:
            gun = next((p for p in ordered if p.name.lower() == options.scope_gun.lower()), None)
            if gun is None:
                result.warnings.append(f"scope gun {options.scope_gun} is not a part; the scope is a root bone")
        local = tuple(options.scope_transform) if options.scope_transform else IDENTITY
        frame = _mul(absolute[id(gun)], _local_matrix(local)) if gun else _local_matrix(local)
        skeleton.bones.append(Bone("scope", handle, parent=handles[id(gun)] if gun else None))
        crouch = None
    group = groups.setdefault((_SCOPE, True), _Group())
    normal = _unit([sum(_normal_matrix(frame)[i][k] * n for k, n in enumerate((0.0, 0.0, 1.0))) for i in range(3)])
    normal = (normal[0], -normal[1], -normal[2])
    s0, s1 = 0.001, 0.999
    base = len(group.positions)
    for corner, uv in (((-1, -1), (s0, s1)), ((1, -1), (s1, s1)), ((1, 1), (s1, s0)), ((-1, 1), (s0, s0))):
        px, py, pz = _apply(frame, (corner[0], corner[1], 0.0))
        group.add((-px, py, pz), normal, uv, WHITE, handle)
    group.indices += [base, base + 1, base + 2, base, base + 2, base + 3]
    return crouch


def _person_animations(model: BwdModel, ordered: List[Part], handles, matrix_of, options: PortOptions,
                       pov: Optional[Part], scope_bone, warnings: List[str]) -> List[Animation]:
    """Redux's named person animations from the ANIM sequences (see PERSON_ANIMATIONS)."""
    sequences = {s.index: s for s in model.sequences}      # a repeated index: the last one wins
    moving = [p for p in ordered if p.band == 0 and p.klass not in HARDPOINT_CLASSES]
    if not model.sequences:
        warnings.append("no ANIM sequences; the person animations are empty")
    animations = []
    for index, name, length, span in PERSON_ANIMATIONS:
        animation = Animation(name, length)
        animations.append(animation)
        seq = sequences.get(index)
        if seq is None or seq.length == 0:
            continue
        step = span / (abs(seq.length) - 1) if abs(seq.length) > 1 else 0.0
        for p in moving:
            eyepoint = p is pov
            still = eyepoint and not options.pov_rotations and index in MOVEMENT_SEQUENCES
            keys = _sequence_keys(model.track(p.name), seq, matrix_of[id(p)], rotate=not still)
            if eyepoint:
                # flipped pitch fixes the camera's up/down in game (BZRModelPorter)
                animation.tracks.append(Track(handles[id(p)], [
                    Keyframe(f * step, (-r[0], r[1], r[2], r[3]), t) for f, r, t in keys]))
                if scope_bone is not None:
                    bone, ahead = scope_bone
                    frames = []
                    for f, r, t in keys:
                        if name == "fireRecoilSniper":
                            shift = _rotate(r, (0.0, 0.0, ahead))
                            t = tuple(a + b for a, b in zip(t, shift))
                        frames.append(Keyframe(f * step, r, t))
                    animation.tracks.append(Track(bone, frames))
            else:
                animation.tracks.append(Track(handles[id(p)], [Keyframe(f * step, r, t) for f, r, t in keys]))
        animation.tracks.sort(key=lambda t: t.bone)
    return animations


def _sequence_keys(track: Optional[AnimTrack], seq: AnimSequence, bind: Sequence[float], rotate: bool = True):
    """(frame from the sequence start, Ogre rotation, Ogre translation) keys of one part.

    The legacy keys are the part's full parent-space transform; Ogre keys are
    offsets from the bind pose: translation ``M (P - p)`` and rotation
    ``M (R_bind^T R) M``. A key lands on both ends of the sequence and on
    every legacy key in between; parts without keys hold the bind pose.
    """
    start, end = seq.frames
    step = 1 if seq.length >= 0 else -1
    lo, hi = min(start, end), max(start, end)
    frames = {start, end}
    if track is not None:
        frames.update(f for f, _ in track.positions + track.rotations if lo <= f <= hi)
    bind_rot, _scale = _rotation(bind)
    bind_t = [[bind_rot[j][i] for j in range(3)] for i in range(3)]
    keys = []
    for frame in sorted(frames, key=lambda f: (f - start) * step):
        translation = (0.0, 0.0, 0.0)
        if track is not None and track.positions:
            px, py, pz = _sample(track.positions, frame, False)
            translation = (-(px - bind[9]), py - bind[10], pz - bind[11])
        orientation = (0.0, 0.0, 0.0, 1.0)
        if rotate and track is not None and track.rotations:
            w, x, y, z = _sample(track.rotations, frame, True)
            posed = _quat_rotation(w, -x, -y, -z)          # stored conjugated
            delta = [[sum(bind_t[i][k] * posed[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
            orientation = _quaternion(_mirrored(delta))
        keys.append(((frame - start) * step, orientation, translation))
    return keys


class _Group:
    def __init__(self):
        self.positions: List[Tuple[float, float, float]] = []
        self.normals: List[Tuple[float, float, float]] = []
        self.uvs: List[Tuple[float, float]] = []
        self.colours: List[int] = []
        self.bones: List[int] = []
        self.indices: List[int] = []
        self.lookup: Dict[tuple, int] = {}
        self.flat: List[int] = []          # palette index per vertex of the flat-colour group

    def add(self, position, normal, uv, colour, bone) -> int:
        self.positions.append(position)
        self.normals.append(normal)
        self.uvs.append(uv)
        self.colours.append(colour)
        self.bones.append(bone)
        return len(self.positions) - 1

    def submesh(self, material: str) -> SubMesh:
        count = len(self.positions)
        block0 = io.BytesIO()
        block1 = io.BytesIO()
        pack0, pack1 = struct.Struct("<6f"), struct.Struct("<I2f")
        for i in range(count):
            block0.write(pack0.pack(*self.positions[i], *self.normals[i]))
            block1.write(pack1.pack(self.colours[i], *self.uvs[i]))
        geometry = Geometry(count, [VertexElement(0, 2, 1, 0, 0), VertexElement(0, 2, 4, 12, 0),
                                    VertexElement(1, 10, 5, 0, 0), VertexElement(1, 1, 7, 4, 0)],
                            {0: VertexBuffer(0, 24, block0.getvalue(), 0),
                             1: VertexBuffer(1, 12, block1.getvalue(), 0)})
        return SubMesh(material, False, list(self.indices), count > 0xFFFF, 4, geometry,
                       [(i, bone, 1.0) for i, bone in enumerate(self.bones)], material)


def _add_part(groups, geo: GeoFile, matrix: Mat, bone: int, cockpit: bool, options: PortOptions,
              warnings: List[str], part: str, palette: Optional[Dict[Tuple[int, int, int], int]] = None,
              scope_texture: Optional[str] = None) -> Tuple[int, int]:
    normal_matrix = _normal_matrix(matrix)
    flip = _det3(matrix) < 0
    positions = [_apply(matrix, p) for p in geo.positions]
    palette = {} if palette is None else palette

    def to_ogre_normal(n):
        if not all(math.isfinite(c) for c in n):
            return (0.0, 0.0, 0.0)
        v = [sum(normal_matrix[i][k] * n[k] for k in range(3)) for i in range(3)]
        return _unit((v[0], -v[1], -v[2]))          # -(M n): inward legacy normal, mirrored

    def face_normal(face):
        # Newell normal of the corners in GEO order, in Ogre space (the mirror
        # turns the legacy inward-facing order into Ogre's outward CCW); the
        # stored plane is the fallback for degenerate polygons.
        pts = [positions[vi] for vi in face.vertices if 0 <= vi < len(positions)]
        pts = [(-x, y, z) for x, y, z in pts]
        n = [0.0, 0.0, 0.0]
        for a, b in zip(pts, pts[1:] + pts[:1]):
            n[0] += (a[1] - b[1]) * (a[2] + b[2])
            n[1] += (a[2] - b[2]) * (a[0] + b[0])
            n[2] += (a[0] - b[0]) * (a[1] + b[1])
        unit = _unit(n)
        if flip:
            unit = tuple(-c for c in unit)
        if unit == (0.0, 0.0, 0.0) or not all(math.isfinite(c) for c in unit):
            unit = to_ogre_normal(face.plane[:3])
        return unit if unit != (0.0, 0.0, 0.0) else (0.0, 1.0, 0.0)

    def texture_key(texture: str, cockpit: bool) -> Tuple[str, bool]:
        # one material per texture whatever its case (aspilo uses aspilo00 and ASPILO00);
        # the first spelling seen names it
        low = texture.lower()
        return next((k[0] for k in groups if k[0].lower() == low), texture), cockpit

    face_normals = [face_normal(face) for face in geo.faces]
    smooth: Dict[Tuple[float, float, float], List[float]] = {}
    if options.normals == "smooth":
        for face, normal in zip(geo.faces, face_normals):
            for vi in set(face.vertices):
                if 0 <= vi < len(positions):
                    acc = smooth.setdefault(_key(positions[vi]), [0.0, 0.0, 0.0])
                    for k in range(3):
                        acc[k] += normal[k]

    vertices = triangles = 0
    bad_refs = 0
    for face, face_normal in zip(geo.faces, face_normals):
        if len(face.vertices) < 3:
            continue
        if any(not 0 <= vi < len(positions) for vi in face.vertices):
            bad_refs += 1
            continue
        flat = None
        if scope_texture is not None and face.texture.lower() == scope_texture:
            key = (_SCOPE, cockpit)
        elif options.flat_colours or not face.texture:
            key = ("", cockpit)
            flat = palette.setdefault(tuple(face.colour), len(palette))
        else:
            key = texture_key(face.texture, cockpit)
        group = groups.get(key)
        if group is None:
            group = groups[key] = _Group()
        corners = []
        for corner, vi in enumerate(face.vertices):
            u, v = face.uvs[corner] if corner < len(face.uvs) else (0.0, 0.0)
            if flat is not None:
                u, v = float(flat), 0.5          # re-pointed at the palette texel in _finish
            if options.normals == "flat":
                normal = face_normal
            elif options.normals == "stored" and vi < len(geo.normals):
                normal = to_ogre_normal(geo.normals[vi])
            else:
                normal = _unit(smooth.get(_key(positions[vi]), face_normal))
            colour = WHITE
            if options.face_colours:
                r, g, b = face.colour
                colour = 0xFF000000 | (r << 16) | (g << 8) | b
            key = (bone, vi, round(u, 6), round(v, 6), normal if options.normals == "flat" else None, colour)
            index = group.lookup.get(key)
            if index is None:
                x, y, z = positions[vi]
                index = group.lookup[key] = group.add((-x, y, z), normal, (u, v), colour, bone)
                if flat is not None:
                    group.flat.append(index)
                vertices += 1
            corners.append(index)
        for k in range(1, len(corners) - 1):
            tri = (corners[0], corners[k + 1], corners[k]) if flip else (corners[0], corners[k], corners[k + 1])
            if len(set(tri)) == 3:
                group.indices.extend(tri)
                triangles += 1
    if bad_refs:
        warnings.append(f"{part}.geo: {bad_refs} faces reference missing vertices and were dropped")
    return vertices, triangles


def _finish(result: PortResult, groups: Dict[Tuple[str, bool], _Group], palette, separate: bool) -> None:
    """Submeshes, materials, bounds and texture names from the filled groups."""
    name, options = result.name, result.options
    result.flat_palette = sorted(palette, key=palette.get)
    for group in groups.values():
        for i in group.flat:                     # a 1 x N texture, one texel per face colour
            group.uvs[i] = ((group.uvs[i][0] + 0.5) / len(result.flat_palette), 0.5)
    for (texture, cockpit), group in groups.items():
        material = SCOPE_MATERIAL if texture == _SCOPE else _material_name(name, texture, cockpit, options)
        result.materials[(texture, cockpit)] = material
        target = result.cockpit_mesh if separate and cockpit else result.mesh
        target.submeshes.append(group.submesh(material))
    bounds = _mesh_bounds([s for _, m in result.meshes() for s in m.submeshes])
    if options.bounds_scale:
        centre = [(bounds[k] + bounds[k + 3]) / 2 for k in range(3)]
        half = [(bounds[k + 3] - bounds[k]) / 2 * float(options.bounds_scale[k]) for k in range(3)]
        bounds = (*(c - h for c, h in zip(centre, half)), *(c + h for c, h in zip(centre, half)), bounds[6])
    for mesh_name, mesh in result.meshes():
        mesh.skeleton = mesh_name + ".skeleton"
        mesh.skeletally_animated = True
        mesh.bounds = bounds
    for texture, cockpit in result.materials:
        if texture != _SCOPE:
            result.texture_files.setdefault(texture, _texture_file(name, texture, options))
    result.material_text = _material_script(result, options)
    if not any(m.submeshes for _, m in result.meshes()):
        result.warnings.append("no geometry was ported")


def build_geo_port(geo_data: bytes, name: str, options: Optional[PortOptions] = None) -> PortResult:
    """A single ``.geo`` as a one-bone model (bone and mesh named ``name``), untransformed."""
    options = options or PortOptions()
    result = PortResult(name, "geo", OgreMesh(version="MeshSerializer_v1.100", endian="little"),
                        Skeleton([Bone(name, 0)]), options=options)
    geo = read_geo(geo_data)
    info = PortedPart(name, "", 0, 60, 0, name + ".geo")
    result.parts.append(info)
    groups: Dict[Tuple[str, bool], _Group] = {}
    palette: Dict[Tuple[int, int, int], int] = {}
    info.vertices, info.triangles = _add_part(groups, geo, _local_matrix(IDENTITY), 0, False, options,
                                              result.warnings, name, palette)
    _finish(result, groups, palette, False)
    return result


def _key(p: Sequence[float]) -> Tuple[float, float, float]:
    return (round(p[0], 4), round(p[1], 4), round(p[2], 4))


def _mesh_bounds(submeshes: Sequence[SubMesh]) -> Tuple[float, ...]:
    points = [p for s in submeshes if s.geometry for p in (s.geometry.attribute(1) or [])]
    if not points:
        return (0.0,) * 7
    lo = [min(p[k] for p in points) for k in range(3)]
    hi = [max(p[k] for p in points) for k in range(3)]
    return (*lo, *hi, max(math.sqrt(sum(c * c for c in p)) for p in points))


def _safe(text: str) -> str:
    return re.sub(r"[^\w\-]", "_", text) or "untextured"


def _material_name(model: str, texture: str, cockpit: bool, options: PortOptions) -> str:
    base = _safe(texture) if texture else "flat"
    name = base if options.material_names == "texture" and texture else f"{model}_{base}"
    return name + "_cockpit" if cockpit else name


def _texture_file(model: str, texture: str, options: PortOptions) -> str:
    base = _safe(texture) if texture else "flat"
    stem = base if options.material_names == "texture" and texture else f"{model}_{base}"
    return f"{stem}_D.{'dds' if options.texture_format == 'dds' else 'png'}"


def _material_script(result: PortResult, options: PortOptions) -> str:
    lines = ['import * from "BZBase.material"', ""]
    for (texture, cockpit), material in result.materials.items():
        if texture == _SCOPE:
            continue                              # Redux's own scope material
        lines += [f"material {material} : {'BZBaseCockpit' if cockpit else 'BZBase'}", "{",
                  f"\tset_texture_alias DiffuseMap {result.texture_files[texture]}",
                  "\tset_texture_alias NormalMap flat_N.dds",
                  "\tset_texture_alias SpecularMap black.dds",
                  "\tset_texture_alias EmissiveMap black.dds",
                  "",
                  '\tset $diffuse "1 1 1"',
                  '\tset $ambient "1 1 1"',
                  '\tset $specular ".7 .7 .7"',
                  '\tset $shininess "127"',
                  '\tset $glow "1 1 1"',
                  "}", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def planned_files(result: PortResult, out_dir: Union[str, Path]) -> List[Path]:
    """Every file :func:`write_port` writes for ``result``, textures included."""
    out = Path(out_dir)
    files = []
    for mesh_name, _mesh in result.meshes():
        files += [out / f"{mesh_name}.mesh", out / f"{mesh_name}.skeleton"]
    files.append(out / f"{result.name}{result.options.material_suffix}.material")
    if result.options.texture_format != "none":
        files += [out / f for f in result.texture_files.values()]
    return files


def write_port(result: PortResult, out_dir: Union[str, Path], load: LoadBytes,
               palette: Optional[Sequence[Tuple[int, int, int]]] = None) -> List[Path]:
    """Write mesh(es), skeleton(s), material and textures into ``out_dir``.

    ``load(filename)`` fetches ``<texture>.map``; ``palette`` decodes 8-bit
    maps (RGB triples). Missing or unreadable textures are reported in
    ``result.warnings`` and skipped. A separate cockpit mesh gets its own
    copy of the skeleton (``<model>_fp.skeleton``), as Redux's stock pilots
    and walkers have.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    skeleton = write_skeleton(result.skeleton)
    for mesh_name, mesh in result.meshes():
        write_mesh(mesh, out / f"{mesh_name}.mesh")
        (out / f"{mesh_name}.skeleton").write_bytes(skeleton)
        written += [out / f"{mesh_name}.mesh", out / f"{mesh_name}.skeleton"]
    material = out / f"{result.name}{result.options.material_suffix}.material"
    material.write_text(result.material_text, encoding="utf-8", newline="\n")
    written.append(material)
    if result.texture_files and result.options.texture_format != "none":
        written += _write_textures(result, out, load, palette)
    result.written = written
    return written


def _save_texture(rgba, target: Path) -> None:
    if target.suffix.lower() == ".dds":
        from battlezone.images.legacy_map import encode_dds_rgba
        target.write_bytes(encode_dds_rgba(rgba))
    else:
        from PIL import Image
        Image.fromarray(rgba, "RGBA").save(target)


def _write_textures(result: PortResult, out: Path, load: LoadBytes, palette) -> List[Path]:
    import numpy as np
    from battlezone.images.legacy_map import MapError, decode_map
    written = []
    for texture, filename in result.texture_files.items():
        target = out / filename
        if not texture:
            colours = result.flat_palette or [(160, 160, 160)]
            rgba = np.full((1, len(colours), 4), 255, dtype=np.uint8)
            rgba[0, :, :3] = colours
        else:
            data = load(texture + ".map")
            if data is None:
                result.warnings.append(f"{texture}.map not found; {filename} was not written")
                continue
            try:
                _w, _h, rgba = decode_map(data, palette)
            except MapError as exc:
                result.warnings.append(f"{texture}.map: {exc}; {filename} was not written")
                continue
        _save_texture(rgba, target)
        written.append(target)
    return written


# ---------------------------------------------------------------------------
# Inputs: VDF/SDF, a lone GEO, an ODF, a MAP
# ---------------------------------------------------------------------------

def _odf_values(text: str) -> Dict[str, str]:
    """``classLabel``, ``baseName`` and ``nation`` of an ODF's [GameObjectClass] (or [GameObject])."""
    values: Dict[str, str] = {}
    section = ""
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        header = re.match(r"^\[(.+?)\]", line)
        if header:
            section = header.group(1).strip().lower()
            continue
        if section not in ("gameobjectclass", "gameobject") or "=" not in line:
            continue
        key, value = (s.strip() for s in line.split("=", 1))
        if key.lower() in ("classlabel", "basename", "nation"):
            values.setdefault(key.lower(), value.strip("\"' \t"))
    return values


def odf_model(odf_text: str, odf_name: str, load: LoadBytes) -> Tuple[str, str, bytes, Optional[bool], str]:
    """(model name, kind, model bytes, person, nation) an ODF points at.

    The class label decides VDF or SDF and whether it is a person; without
    one (walker ODFs use ``[GameObject]`` and some inherit it) the model
    named ``baseName`` (or the ODF) is taken from whichever of .vdf/.sdf exists.
    """
    values = _odf_values(odf_text)
    base = values.get("basename") or Path(odf_name).stem
    label = values.get("classlabel", "").lower()
    kinds = ("vdf",) if label in VDF_CLASSES else ("sdf",) if label in SDF_CLASSES else ("vdf", "sdf")
    for kind in kinds:
        data = load(f"{base}.{kind}")
        if data is not None:
            person = (label == "person") if label else None
            return base.lower(), kind, data, person, values.get("nation", "")
    raise ModelError(f"{odf_name}: model {base}.{'/'.join(kinds)} not found")


def port_legacy_model(model_path: Union[str, Path], out_dir: Union[str, Path], *,
                      search: Iterable[Union[str, Path]] = (), archives: Iterable = (),
                      palette: Optional[Sequence[Tuple[int, int, int]]] = None,
                      options: Optional[PortOptions] = None) -> PortResult:
    """Port the VDF/SDF at ``model_path`` into ``out_dir``.

    GEO parts and MAP textures are looked up (case-insensitively) next to the
    model, then in ``search`` folders, then in ``archives`` (ZFS paths or
    :class:`~battlezone.archives.zfs.ZFSArchive` objects).
    """
    return port_file(model_path, out_dir, search=search, archives=archives, palette=palette, options=options)


def port_file(path: Union[str, Path], out_dir: Union[str, Path], *, search: Iterable[Union[str, Path]] = (),
              archives: Iterable = (), palette: Optional[Sequence[Tuple[int, int, int]]] = None,
              options: Optional[PortOptions] = None, name: str = "", dry_run: bool = False) -> PortResult:
    """Port a ``.vdf``/``.sdf`` (a model), ``.geo`` (one part), ``.odf`` (the
    model it names, person and scope nation from its class) or ``.map``
    (just the texture) into ``out_dir``. ``dry_run`` builds without writing."""
    options = options or PortOptions()
    path = Path(path)
    suffix = path.suffix.lower()
    source = AssetSource([path.parent, *search], archives)
    if suffix in (".vdf", ".sdf"):
        result = build_port(path.read_bytes(), suffix, name or path.stem.lower(), source, options)
    elif suffix == ".odf":
        model, kind, data, person, nation = odf_model(path.read_text(errors="replace"), path.name, source)
        if options.person is None and person is not None:
            options = _replace(options, person=person)
        if not options.scope_nation and nation:
            options = _replace(options, scope_nation=nation)
        label = _odf_values(path.read_text(errors="replace")).get("classlabel", "").lower()
        if options.turret is None and label:
            options = _replace(options, turret=label in TURRET_CLASSES)
        result = build_port(data, kind, name or model, source, options)
    elif suffix == ".geo":
        result = build_geo_port(path.read_bytes(), name or path.stem.lower(), options)
    elif suffix == ".map":
        return _port_map(path, out_dir, name or path.stem.lower(), options, palette, dry_run)
    else:
        raise ModelError(f"{path.name}: expected one of {', '.join(PORTABLE_SUFFIXES)}")
    if dry_run:
        result.written = []
    else:
        write_port(result, out_dir, source, palette)
    return result


def _replace(options: PortOptions, **changes) -> PortOptions:
    from dataclasses import replace
    return replace(options, **changes)


def _port_map(path: Path, out_dir, name: str, options: PortOptions, palette, dry_run: bool) -> PortResult:
    from battlezone.images.legacy_map import MapError, decode_map
    result = PortResult(name, "map", OgreMesh(version="MeshSerializer_v1.100", endian="little"), Skeleton(),
                        options=options)
    filename = f"{name}_D.{'dds' if options.texture_format == 'dds' else 'png'}"
    result.texture_files[name] = filename
    try:
        _w, _h, rgba = decode_map(path.read_bytes(), palette)
    except MapError as exc:
        raise ModelError(f"{path.name}: {exc}") from None
    if not dry_run:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        _save_texture(rgba, Path(out_dir) / filename)
        result.written = [Path(out_dir) / filename]
    return result


# 1.5 archives in lookup order: data first, then the 16-bit texture set (no
# palette needed), then the 8-bit sets.
LEGACY_ARCHIVES = ("bzone152.zfs", "bzone.zfs", "bzhw16q.zfs", "bzhw16l.zfs", "bzhw16.zfs", "bz15hw16l.zfs",
                   "bz15hw16.zfs", "bzsw.zfs", "bzhw.zfs", "bz15sw.zfs", "bz15hw.zfs")


def legacy_archives(install_dir: Union[str, Path]) -> List[Path]:
    """The Battlezone 1.5 install's ZFS archives that exist, in lookup order."""
    install = Path(install_dir)
    present = {p.name.lower(): p for p in install.glob("*.zfs")} if install.is_dir() else {}
    return [present[name] for name in LEGACY_ARCHIVES if name in present]


def resolve_palette(value: Optional[str]):
    """RGB triples from an ``.act`` path or a stock palette name; ``moon.act`` when empty."""
    from battlezone.images.legacy_map import palette_from_act
    from battlezone.terrain.palettes import get_stock_palette
    if not value:
        return get_stock_palette("moon.act")
    if Path(value).is_file():
        return palette_from_act(Path(value).read_bytes())
    stock = get_stock_palette(value)
    if stock is None:
        raise ValueError(f"{value}: neither an .act file nor a stock palette name")
    return stock


def _tristate(value: str) -> Optional[bool]:
    return {"auto": None, "yes": True, "no": False}[value]


def main(argv: Optional[Sequence[str]] = None,
         find_game15: Optional[Callable[[], Optional[Union[str, Path]]]] = None) -> int:
    """``bztoolbox meshes port-legacy``; ``find_game15`` resolves ``--game15 auto``."""
    import argparse
    tri = ("auto", "yes", "no")
    parser = argparse.ArgumentParser(
        prog="bztoolbox meshes port-legacy",
        description="Port Battlezone 1.5 models (.vdf/.sdf + .geo + .map) to Redux .mesh/.skeleton/.material "
                    "and textures. Also takes an .odf (ports the model it names; a person class gets pilot "
                    "animations), a lone .geo (one-bone mesh) or a .map (texture only).",
        epilog="@FILE reads more arguments from FILE, one per line (BZRModelPorter's config.cfg: e.g. "
               "--palette, --textures and --game15 lines).",
        fromfile_prefix_chars="@")
    parser.add_argument("files", nargs="+", metavar="FILE", help=".vdf, .sdf, .odf, .geo or .map (any number)")
    parser.add_argument("--out", help="output folder (default: <name>_redux beside each file)")
    parser.add_argument("--name", help="output model name (one input only; default: the file name)")
    parser.add_argument("--textures", action="append", default=[], metavar="DIR",
                        help="extra folder searched for .geo and .map files (repeatable)")
    parser.add_argument("--zfs", action="append", default=[], metavar="FILE",
                        help="ZFS archive searched after the folders (repeatable)")
    parser.add_argument("--game15", metavar="DIR",
                        help="Battlezone 1.5 install: search its ZFS archives for stock parts and textures "
                             "('auto' finds it)")
    parser.add_argument("--palette", help="ACT file or stock palette name for 8-bit maps (default moon)")
    parser.add_argument("--bands", help="comma-separated VDF/SDF bands to port (default VDF 0,4; SDF 0)")
    parser.add_argument("--material-names", choices=("model", "texture"), default="model",
                        help="model: <model>_<texture> (default, cannot clash with stock); "
                             "texture: the legacy texture name, as stock conversions do")
    parser.add_argument("--material-suffix", default="", metavar="TEXT",
                        help="material file <model>TEXT.material (BZRModelPorter used _port)")
    parser.add_argument("--normals", choices=("smooth", "flat", "stored"), default="smooth")
    parser.add_argument("--format", choices=("png", "dds", "none"), default="png",
                        help="diffuse texture format (none: write no textures)")
    parser.add_argument("--flat-colours", "--flatcolors", action="store_true",
                        help="colour every face from its GEO face colour (a palette texture) instead of its .map")
    parser.add_argument("--no-headlights", action="store_true", help="no HLGT bones at headlight parts")
    parser.add_argument("--person", choices=tri, default="auto",
                        help="treat as a person (pilot): skeletal animations, hardpoints on the gun, scope "
                             "(auto: the ODF class, else a name like ?s????)")
    parser.add_argument("--animations", choices=tri, default="auto", help="person skeletal animations")
    parser.add_argument("--cockpit", choices=tri, default="auto",
                        help="write the cockpit as its own <model>_fp/_c/_cockpit mesh (auto: when it animates)")
    parser.add_argument("--turret", choices=tri, default="auto",
                        help="turret/howitzer: write the cockpit as its own _c mesh (auto: the ODF class, else "
                             "the stock names Redux asks a _c cockpit for)")
    parser.add_argument("--no-pov-rotations", action="store_true",
                        help="the eyepoint does not rotate in the four run animations")
    parser.add_argument("--scope", choices=tri, default="auto", help="person sniper scope (auto: persons)")
    parser.add_argument("--scope-type", choices=("auto", "fixed", "attached", "geometry"), default="auto",
                        help="fixed: a square on screen shown while crouched (classic); attached: a square on "
                             "the gun; geometry: faces textured --scope-texture; auto: geometry when such "
                             "faces exist, else fixed")
    parser.add_argument("--scope-nation", default="", help="fixed: s... Soviet screen placement, else American")
    parser.add_argument("--scope-screen", nargs=5, type=float, metavar=("X", "Y", "Z", "SCALE", "BEHIND"),
                        help="fixed: camera-relative placement, size and hidden distance behind the camera")
    parser.add_argument("--scope-gun", default="", help="attached: part the scope hangs from")
    parser.add_argument("--scope-transform", nargs=12, type=float,
                        metavar=("RX", "RY", "RZ", "UX", "UY", "UZ", "FX", "FY", "FZ", "PX", "PY", "PZ"),
                        help="attached: gun-relative right, up, front and position")
    parser.add_argument("--scope-texture", default="__scope", help="geometry: texture name that becomes the scope")
    parser.add_argument("--bounds-scale", nargs=3, type=float, metavar=("X", "Y", "Z"),
                        help="scale the mesh bounding box about its centre")
    parser.add_argument("--skip-existing", action="store_true", help="skip a model whose .mesh is already there")
    parser.add_argument("--dry-run", action="store_true", help="build and report, write nothing")
    args = parser.parse_args(argv)

    files = [Path(f) for f in args.files]
    for f in files:
        if f.suffix.lower() not in PORTABLE_SUFFIXES or not f.is_file():
            parser.error(f"{f}: expected an existing {', '.join(PORTABLE_SUFFIXES)} file")
    if args.name and len(files) > 1:
        parser.error("--name needs a single input file")
    try:
        palette = resolve_palette(args.palette)
        bands = [int(b) for b in args.bands.split(",")] if args.bands else None
    except ValueError as exc:
        parser.error(str(exc))
    game15 = args.game15
    if game15 and game15.lower() == "auto":
        game15 = find_game15() if find_game15 else None
        if game15:
            print(f"Battlezone 1.5: {game15}")
    archives = [*args.zfs, *(legacy_archives(game15) if game15 else [])]
    options = PortOptions(bands=bands, material_names=args.material_names, normals=args.normals,
                          texture_format=args.format, headlights=not args.no_headlights,
                          flat_colours=args.flat_colours, person=_tristate(args.person),
                          animations=_tristate(args.animations), cockpit_files=_tristate(args.cockpit),
                          turret=_tristate(args.turret),
                          pov_rotations=not args.no_pov_rotations, scope=_tristate(args.scope),
                          scope_type=args.scope_type, scope_nation=args.scope_nation,
                          scope_screen=args.scope_screen, scope_gun=args.scope_gun,
                          scope_transform=args.scope_transform, scope_texture=args.scope_texture,
                          bounds_scale=args.bounds_scale, material_suffix=args.material_suffix)
    failures = 0
    for f in files:
        out = Path(args.out) if args.out else f.with_name(f.stem.lower() + "_redux")
        stem = (args.name or f.stem).lower()
        if args.skip_existing and (out / f"{stem}.mesh").is_file():
            print(f"{f.name}: {stem}.mesh already in {out}; skipped")
            continue
        try:
            result = port_file(f, out, search=args.textures, archives=archives, palette=palette,
                               options=options, name=(args.name or "").lower(), dry_run=args.dry_run)
        except (ModelError, OSError) as exc:
            print(f"{f.name}: error: {exc}")
            failures += 1
            continue
        if result.kind == "map":
            print(f"{f.name}: texture {result.texture_files[result.name]}"
                  + (f" -> {out}" if result.written else " (dry run)"))
            continue
        print(result.summary())
        if args.dry_run:
            print("  dry run, would write: " + ", ".join(p.name for p in planned_files(result, out)))
        if not any(m.submeshes for _, m in result.meshes()):
            failures += 1
    return 1 if failures else 0
