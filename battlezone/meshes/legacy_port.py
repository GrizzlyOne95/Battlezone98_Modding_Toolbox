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

The VDF/SDF and GEO files stay in the mod: Redux still reads them for
collision, hardpoints and the ANIM keys that drive the bones. The ODF needs
no change when the mesh is named after the VDF/SDF.

Not converted: ANIM sequences (the game animates the named bones itself),
damage states, low-detail models.
"""

from __future__ import annotations

import io
import math
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from battlezone.meshes.legacy import BwdModel, GeoFile, ModelError, Part, read_geo, read_sdf, read_vdf
from battlezone.meshes.ogre import Geometry, OgreMesh, SubMesh, VertexBuffer, VertexElement, write_mesh
from battlezone.meshes.ogre_skeleton import Bone, Skeleton, write_skeleton

__all__ = ["PortOptions", "PortedPart", "PortResult", "AssetSource", "build_port", "write_port",
           "port_legacy_model", "legacy_archives", "resolve_palette", "main", "INVISIBLE_CLASSES", "COCKPIT_BAND"]

# Classes whose .geo the game never draws: headlight mask, eyepoint,
# hardpoints, flame/smoke/dust emitters (bzbwd2.nonrendering_class_id_set).
INVISIBLE_CLASSES = frozenset({38, 40, 70, 71, 72, 73, 74, 75, 76, 77})
HEADLIGHT_CLASS = 38
COCKPIT_BAND = 4
WHITE = 0xFFFFFFFF
LoadBytes = Callable[[str], Optional[bytes]]


@dataclass
class PortOptions:
    bands: Optional[Sequence[int]] = None      # None: VDF (0, 4), SDF (0,)
    material_names: str = "model"              # "model": <model>_<tex>; "texture": <tex> (stock style)
    normals: str = "smooth"                    # "smooth", "flat" or "stored" (the GEO's own normals)
    texture_format: str = "png"                # "png", "dds" or "none"
    headlights: bool = True                    # add HLGT<n>_ffffff bones at headlight-mask parts
    face_colours: bool = False                 # vertex colour from the GEO face colour instead of white


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

    @property
    def vertex_count(self) -> int:
        return sum(s.geometry.vertex_count for s in self.mesh.submeshes if s.geometry)

    @property
    def triangle_count(self) -> int:
        return sum(len(s.indices) // 3 for s in self.mesh.submeshes)

    def summary(self) -> str:
        lines = [f"{self.name} ({self.kind.upper()}): {len(self.skeleton.bones)} bones, "
                 f"{len(self.mesh.submeshes)} submeshes, {self.vertex_count} vertices, "
                 f"{self.triangle_count} triangles"]
        for sub in self.mesh.submeshes:
            lines.append(f"  submesh {sub.name}: material {sub.material}, "
                         f"{sub.geometry.vertex_count if sub.geometry else 0} vertices, {len(sub.indices) // 3} triangles")
        for part in self.parts:
            detail = f"{part.geo}: {part.vertices} vertices, {part.triangles} triangles" if part.geo else "bone only"
            lines.append(f"  bone {part.bone} {part.name} (band {part.band}, class {part.klass}, "
                         f"parent {part.parent or '-'}): {detail}{'; ' + part.note if part.note else ''}")
        lines.extend(f"  warning: {w}" for w in self.warnings)
        lines.extend(f"  wrote {p}" for p in self.written)
        return "\n".join(lines)


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


def _bone_transform(matrix: Sequence[float]):
    """Ogre (position, orientation, scale) of a legacy local matrix; mirrored in X."""
    axes = [matrix[0:3], matrix[3:6], matrix[6:9]]
    scale = [math.sqrt(sum(c * c for c in axis)) or 1.0 for axis in axes]
    cols = [[c / s for c in axis] for axis, s in zip(axes, scale)]
    rot = [[cols[j][i] for j in range(3)] for i in range(3)]            # rows of R
    mirror = (-1.0, 1.0, 1.0)
    mirrored = [[mirror[i] * rot[i][j] * mirror[j] for j in range(3)] for i in range(3)]
    position = (-matrix[9], matrix[10], matrix[11])
    unit = all(abs(s - 1.0) < 1e-4 for s in scale)
    return position, _quaternion(mirrored), None if unit else tuple(scale)


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def _default_bands(kind: str) -> Tuple[int, ...]:
    return (0, COCKPIT_BAND) if kind == "vdf" else (0,)


def _is_root(part: Part) -> bool:
    return part.parent.lower() in ("", "world", "null")


def _resolve_parent(part: Part, chosen: Dict[str, Part]) -> Tuple[Optional[Part], bool]:
    """The included part a record hangs from (None for WORLD) and whether it was guessed.

    A cockpit record may name a parent its band leaves empty (avtank's
    ``AGR21bga`` under ``AGR21TUR``). It then hangs from its band's root part
    (``agr21bda``), which puts the gun where Redux's own avtank skeleton has
    ``AGR21bga`` (within 0.07). Failing that, it becomes a root bone.
    """
    if _is_root(part):
        return None, False
    parent = chosen.get(part.parent.lower())
    if parent is not None and parent is not part:
        return parent, False
    roots = [p for p in chosen.values() if p.band == part.band and p is not part and _is_root(p)]
    return (roots[0] if roots else None), True


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

    records = [p for p in model.parts if p.band in bands and p.name.upper() != "NULL"]
    records.sort(key=lambda p: (bands.index(p.band), p.slot))
    chosen: Dict[str, Part] = {}
    for part in records:
        if part.name.lower() in chosen:
            result.warnings.append(f"part name {part.name} appears twice; the band {part.band} copy is skipped")
            continue
        chosen[part.name.lower()] = part
    parts = list(chosen.values())
    parent_of: Dict[int, Optional[Part]] = {}
    for p in parts:
        parent, guessed = _resolve_parent(p, chosen)
        parent_of[id(p)] = parent
        if guessed:
            where = f"hung from {parent.name}" if parent else "made a root bone"
            result.warnings.append(f"{p.name}: parent {p.parent} is not a ported part; {where}")

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
        local = _local_matrix(p.matrix)
        parent = parent_of[id(p)]
        absolute[id(p)] = _mul(absolute[id(parent)], local) if parent else local
        position, orientation, scale = _bone_transform(p.matrix)
        bone = Bone(p.name, handles[id(p)], position, orientation, scale,
                    handles[id(parent)] if parent else None)
        result.skeleton.bones.append(bone)
        if scale is not None:
            result.warnings.append(f"{p.name}: scaled transform {tuple(round(s, 4) for s in scale)}; "
                                   "check the part in game")
        result.parts.append(PortedPart(p.name, parent.name if parent else "", p.band, p.klass, bone.handle))

    if options.headlights:
        lights = [p for p in ordered if p.klass == HEADLIGHT_CLASS and p.band == 0]
        for n, light in enumerate(lights):
            parent = parent_of[id(light)]
            position, orientation, scale = _bone_transform(light.matrix)
            result.skeleton.bones.append(Bone(f"HLGT{n}_ffffff", len(result.skeleton.bones), position,
                                              orientation, None, handles[id(parent)] if parent else None))

    # geometry, grouped by (texture, cockpit)
    groups: Dict[Tuple[str, bool], _Group] = {}
    for p, info in zip(ordered, result.parts):
        if p.klass in INVISIBLE_CLASSES:
            continue
        data = load(p.name + ".geo")
        if data is None:
            info.note = "no .geo found"
            result.warnings.append(f"{p.name}.geo not found; the part has no geometry")
            continue
        try:
            geo = read_geo(data)
        except ModelError as exc:
            info.note = f"unreadable .geo ({exc})"
            result.warnings.append(f"{p.name}.geo: {exc}")
            continue
        info.geo = p.name + ".geo"
        cockpit = p.band == COCKPIT_BAND and kind == "vdf"
        added = _add_part(groups, geo, absolute[id(p)], handles[id(p)], cockpit, options, result.warnings, p.name)
        info.vertices, info.triangles = added

    for (texture, cockpit), group in groups.items():
        material = _material_name(name, texture, cockpit, options)
        result.materials[(texture, cockpit)] = material
        result.mesh.submeshes.append(group.submesh(material))
    result.mesh.skeleton = name + ".skeleton"
    result.mesh.skeletally_animated = True
    result.mesh.bounds = _mesh_bounds(result.mesh)
    for texture, cockpit in result.materials:
        result.texture_files.setdefault(texture, _texture_file(name, texture, options))
    result.material_text = _material_script(result, options)
    if not result.mesh.submeshes:
        result.warnings.append("no geometry was ported")
    return result


class _Group:
    def __init__(self):
        self.positions: List[Tuple[float, float, float]] = []
        self.normals: List[Tuple[float, float, float]] = []
        self.uvs: List[Tuple[float, float]] = []
        self.colours: List[int] = []
        self.bones: List[int] = []
        self.indices: List[int] = []
        self.lookup: Dict[tuple, int] = {}

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
              warnings: List[str], part: str) -> Tuple[int, int]:
    normal_matrix = _normal_matrix(matrix)
    flip = _det3(matrix) < 0
    positions = [_apply(matrix, p) for p in geo.positions]

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
        group = groups.get((face.texture, cockpit))
        if group is None:
            group = groups[(face.texture, cockpit)] = _Group()
        corners = []
        for corner, vi in enumerate(face.vertices):
            u, v = face.uvs[corner] if corner < len(face.uvs) else (0.0, 0.0)
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
                index = group.lookup[key] = len(group.positions)
                x, y, z = positions[vi]
                group.positions.append((-x, y, z))
                group.normals.append(normal)
                group.uvs.append((u, v))
                group.colours.append(colour)
                group.bones.append(bone)
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


def _key(p: Sequence[float]) -> Tuple[float, float, float]:
    return (round(p[0], 4), round(p[1], 4), round(p[2], 4))


def _mesh_bounds(mesh: OgreMesh) -> Tuple[float, ...]:
    points = [p for s in mesh.submeshes if s.geometry for p in (s.geometry.attribute(1) or [])]
    if not points:
        return (0.0,) * 7
    lo = [min(p[k] for p in points) for k in range(3)]
    hi = [max(p[k] for p in points) for k in range(3)]
    return (*lo, *hi, max(math.sqrt(sum(c * c for c in p)) for p in points))


def _safe(text: str) -> str:
    return re.sub(r"[^\w\-]", "_", text) or "untextured"


def _material_name(model: str, texture: str, cockpit: bool, options: PortOptions) -> str:
    base = _safe(texture) if texture else "untextured"
    name = base if options.material_names == "texture" and texture else f"{model}_{base}"
    return name + "_cockpit" if cockpit else name


def _texture_file(model: str, texture: str, options: PortOptions) -> str:
    base = _safe(texture) if texture else "untextured"
    stem = base if options.material_names == "texture" and texture else f"{model}_{base}"
    return f"{stem}_D.{'dds' if options.texture_format == 'dds' else 'png'}"


def _material_script(result: PortResult, options: PortOptions) -> str:
    lines = ['import * from "BZBase.material"', ""]
    for (texture, cockpit), material in result.materials.items():
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
                  "}", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def write_port(result: PortResult, out_dir: Union[str, Path], load: LoadBytes,
               palette: Optional[Sequence[Tuple[int, int, int]]] = None) -> List[Path]:
    """Write mesh, skeleton, material and textures into ``out_dir``.

    ``load(filename)`` fetches ``<texture>.map``; ``palette`` decodes 8-bit
    maps (RGB triples). Missing or unreadable textures are reported in
    ``result.warnings`` and skipped.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = [out / f"{result.name}.mesh", out / f"{result.name}.skeleton", out / f"{result.name}.material"]
    write_mesh(result.mesh, written[0])
    write_skeleton(result.skeleton, written[1])
    written[2].write_text(result.material_text, encoding="utf-8", newline="\n")
    if result.texture_files and result.options.texture_format != "none":
        written += _write_textures(result, out, load, palette)
    result.written = written
    return written


def _write_textures(result: PortResult, out: Path, load: LoadBytes, palette) -> List[Path]:
    import numpy as np
    from battlezone.images.legacy_map import MapError, decode_map, encode_dds_rgba
    written = []
    for texture, filename in result.texture_files.items():
        target = out / filename
        if not texture:
            rgba = np.full((8, 8, 4), 160, dtype=np.uint8)
            rgba[..., 3] = 255
            result.warnings.append("faces without a texture use a flat grey map")
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
        if filename.lower().endswith(".dds"):
            target.write_bytes(encode_dds_rgba(rgba))
        else:
            from PIL import Image
            Image.fromarray(rgba, "RGBA").save(target)
        written.append(target)
    return written


def port_legacy_model(model_path: Union[str, Path], out_dir: Union[str, Path], *,
                      search: Iterable[Union[str, Path]] = (), archives: Iterable = (),
                      palette: Optional[Sequence[Tuple[int, int, int]]] = None,
                      options: Optional[PortOptions] = None) -> PortResult:
    """Port the VDF/SDF at ``model_path`` into ``out_dir``.

    GEO parts and MAP textures are looked up (case-insensitively) next to the
    model, then in ``search`` folders, then in ``archives`` (ZFS paths or
    :class:`~battlezone.archives.zfs.ZFSArchive` objects).
    """
    options = options or PortOptions()
    model_path = Path(model_path)
    source = AssetSource([model_path.parent, *search], archives)
    result = build_port(model_path.read_bytes(), model_path.suffix, model_path.stem.lower(), source, options)
    write_port(result, out_dir, source, palette)
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="bztoolbox meshes port-legacy",
        description="Port a Battlezone 1.5 model (.vdf/.sdf + .geo + .map) to Redux "
                    ".mesh/.skeleton/.material and textures.")
    parser.add_argument("model", help="the .vdf or .sdf")
    parser.add_argument("--out", help="output folder (default: MODEL_redux beside the model)")
    parser.add_argument("--textures", action="append", default=[], metavar="DIR",
                        help="extra folder searched for .geo and .map files (repeatable)")
    parser.add_argument("--zfs", action="append", default=[], metavar="FILE",
                        help="ZFS archive searched after the folders (repeatable)")
    parser.add_argument("--game15", metavar="DIR",
                        help="Battlezone 1.5 install: search its ZFS archives for stock parts and textures")
    parser.add_argument("--palette", help="ACT file or stock palette name for 8-bit maps (default moon)")
    parser.add_argument("--bands", help="comma-separated VDF/SDF bands to port (default VDF 0,4; SDF 0)")
    parser.add_argument("--material-names", choices=("model", "texture"), default="model",
                        help="model: <model>_<texture> (default, cannot clash with stock); "
                             "texture: the legacy texture name, as stock conversions do")
    parser.add_argument("--normals", choices=("smooth", "flat", "stored"), default="smooth")
    parser.add_argument("--format", choices=("png", "dds", "none"), default="png",
                        help="diffuse texture format (none: write no textures)")
    parser.add_argument("--no-headlights", action="store_true", help="no HLGT bones at headlight parts")
    args = parser.parse_args(argv)

    model = Path(args.model)
    if model.suffix.lower() not in (".vdf", ".sdf") or not model.is_file():
        parser.error(f"{model}: expected an existing .vdf or .sdf")
    try:
        palette = resolve_palette(args.palette)
        bands = [int(b) for b in args.bands.split(",")] if args.bands else None
    except ValueError as exc:
        parser.error(str(exc))
    archives = [*args.zfs, *(legacy_archives(args.game15) if args.game15 else [])]
    options = PortOptions(bands=bands, material_names=args.material_names, normals=args.normals,
                          texture_format=args.format, headlights=not args.no_headlights)
    out = Path(args.out) if args.out else model.with_name(model.stem.lower() + "_redux")
    try:
        result = port_legacy_model(model, out, search=args.textures, archives=archives, palette=palette,
                                   options=options)
    except (ModelError, OSError) as exc:
        print(f"error: {exc}")
        return 1
    print(result.summary())
    return 0 if result.mesh.submeshes else 1
