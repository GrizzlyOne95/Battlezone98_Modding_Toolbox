"""Ogre binary ``.mesh`` reader (pure Python, every platform).

Replaces the Windows-only ``OgreXMLConverter.exe`` for the toolbox's needs:

* :func:`read_mesh` parses a binary mesh (serializer v1.0 - v1.100, either
  byte order) into plain Python data;
* :func:`to_xml` produces the same ``.mesh.xml`` layout OgreXMLConverter
  writes (geometry, submeshes, skeleton link, bone assignments, submesh
  names), so XML-based tools keep working unchanged;
* :func:`patch_normals` writes recalculated normals back into the binary file
  in place, leaving every other byte untouched.

Level-of-detail, edge list, pose and animation chunks are skipped; they are
not needed to export geometry or to fix normals.
"""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

__all__ = ["MeshError", "OgreMesh", "SubMesh", "Geometry", "VertexElement", "read_mesh", "to_xml",
           "write_xml", "mesh_to_xml_file", "patch_normals", "normals_from_xml"]

# --- chunk ids -------------------------------------------------------------------
M_HEADER = 0x1000
M_MESH = 0x3000
M_SUBMESH = 0x4000
M_SUBMESH_OPERATION = 0x4010
M_SUBMESH_BONE_ASSIGNMENT = 0x4100
M_SUBMESH_TEXTURE_ALIAS = 0x4200
M_GEOMETRY = 0x5000
M_GEOMETRY_VERTEX_DECLARATION = 0x5100
M_GEOMETRY_VERTEX_ELEMENT = 0x5110
M_GEOMETRY_VERTEX_BUFFER = 0x5200
M_GEOMETRY_VERTEX_BUFFER_DATA = 0x5210
M_MESH_SKELETON_LINK = 0x6000
M_MESH_BONE_ASSIGNMENT = 0x7000
M_MESH_BOUNDS = 0x9000
M_SUBMESH_NAME_TABLE = 0xA000
M_SUBMESH_NAME_TABLE_ELEMENT = 0xA100

# --- vertex element semantics and types ----------------------------------------------
SEMANTICS = {1: "position", 2: "blend_weights", 3: "blend_indices", 4: "normal", 5: "diffuse",
             6: "specular", 7: "texcoord", 8: "binormal", 9: "tangent"}

# type id -> (struct code, count, normalise divisor or None)
TYPES: Dict[int, Tuple[str, int, Optional[float]]] = {
    0: ("f", 1, None), 1: ("f", 2, None), 2: ("f", 3, None), 3: ("f", 4, None),
    4: ("I", 1, None), 10: ("I", 1, None), 11: ("I", 1, None),        # packed colours
    5: ("h", 1, None), 6: ("h", 2, None), 7: ("h", 3, None), 8: ("h", 4, None),
    9: ("B", 4, None),
    12: ("d", 1, None), 13: ("d", 2, None), 14: ("d", 3, None), 15: ("d", 4, None),
    16: ("H", 1, None), 17: ("H", 2, None), 18: ("H", 3, None), 19: ("H", 4, None),
    20: ("i", 1, None), 21: ("i", 2, None), 22: ("i", 3, None), 23: ("i", 4, None),
    24: ("I", 1, None), 25: ("I", 2, None), 26: ("I", 3, None), 27: ("I", 4, None),
    28: ("b", 4, None), 29: ("b", 4, 127.0), 30: ("B", 4, 255.0),
    31: ("h", 2, 32767.0), 32: ("h", 4, 32767.0), 33: ("H", 2, 65535.0), 34: ("H", 4, 65535.0),
}
COLOUR_TYPES = {4: "argb", 10: "argb", 11: "abgr"}
FLOAT3 = 2

OPERATIONS = {1: "point_list", 2: "line_list", 3: "line_strip", 4: "triangle_list",
              5: "triangle_strip", 6: "triangle_fan"}


class MeshError(ValueError):
    """Not an Ogre binary mesh, or a structure this reader does not understand."""


@dataclass
class VertexElement:
    source: int
    type: int
    semantic: int
    offset: int
    index: int

    @property
    def size(self) -> int:
        code, count, _ = TYPES.get(self.type, ("B", 0, None))
        return struct.calcsize(code) * count


@dataclass
class VertexBuffer:
    bind_index: int
    vertex_size: int
    data: bytes
    file_offset: int                   # where the raw data starts in the file


@dataclass
class Geometry:
    vertex_count: int
    elements: List[VertexElement] = field(default_factory=list)
    buffers: Dict[int, VertexBuffer] = field(default_factory=dict)

    def attribute(self, semantic: int, index: int = 0) -> Optional[List[tuple]]:
        """Decoded values of one attribute for every vertex, or None if absent."""
        element = next((e for e in self.elements if e.semantic == semantic and e.index == index), None)
        return None if element is None else self.decode(element)

    def decode(self, element: VertexElement) -> List[tuple]:
        buffer = self.buffers.get(element.source)
        if buffer is None or element.type not in TYPES:
            return []
        code, count, norm = TYPES[element.type]
        fmt = struct.Struct(f"{self._endian}{count}{code}")
        values = []
        for i in range(self.vertex_count):
            start = i * buffer.vertex_size + element.offset
            value = fmt.unpack_from(buffer.data, start)
            if norm:
                value = tuple(max(-1.0, v / norm) for v in value)
            values.append(value)
        return values

    _endian: str = "<"


@dataclass
class SubMesh:
    material: str
    uses_shared_vertices: bool
    indices: List[int]
    use32bit: bool
    operation: int = 4
    geometry: Optional[Geometry] = None
    bone_assignments: List[Tuple[int, int, float]] = field(default_factory=list)
    name: str = ""

    def triangles(self) -> List[Tuple[int, int, int]]:
        """Faces as triangle-list index triples (strips and fans expanded)."""
        idx = self.indices
        if self.operation == 4:
            return [tuple(idx[i:i + 3]) for i in range(0, len(idx) - 2, 3)]
        if self.operation == 5:
            tris = []
            for i in range(len(idx) - 2):
                a, b, c = idx[i], idx[i + 1], idx[i + 2]
                tri = (a, b, c) if i % 2 == 0 else (b, a, c)
                if len(set(tri)) == 3:          # skip degenerate joins
                    tris.append(tri)
            return tris
        if self.operation == 6:
            return [(idx[0], idx[i], idx[i + 1]) for i in range(1, len(idx) - 1)]
        return []


@dataclass
class OgreMesh:
    version: str
    endian: str
    skeletally_animated: bool = False
    shared_geometry: Optional[Geometry] = None
    submeshes: List[SubMesh] = field(default_factory=list)
    skeleton: str = ""
    bone_assignments: List[Tuple[int, int, float]] = field(default_factory=list)
    bounds: Optional[Tuple[float, ...]] = None
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.e = "<"

    def eof(self) -> bool:
        return self.pos >= len(self.data)

    def unpack(self, fmt: str):
        s = struct.Struct(self.e + fmt)
        if self.pos + s.size > len(self.data):
            raise MeshError(f"unexpected end of file at byte {self.pos}")
        values = s.unpack_from(self.data, self.pos)
        self.pos += s.size
        return values

    def u16(self) -> int:
        return self.unpack("H")[0]

    def u32(self) -> int:
        return self.unpack("I")[0]

    def boolean(self) -> bool:
        return bool(self.unpack("B")[0])

    def string(self) -> str:
        end = self.data.find(b"\n", self.pos)
        if end < 0:
            raise MeshError("unterminated string")
        text = self.data[self.pos:end].decode("utf-8", errors="replace")
        self.pos = end + 1
        return text

    def chunk(self) -> Tuple[int, int]:
        """Read a chunk header; returns (id, end position)."""
        start = self.pos
        cid, size = self.unpack("HI")
        return cid, start + size

    def peek_chunk(self) -> Optional[int]:
        if self.pos + 6 > len(self.data):
            return None
        return struct.unpack_from(self.e + "H", self.data, self.pos)[0]


def read_mesh(source: Union[str, Path, bytes]) -> OgreMesh:
    data = bytes(source) if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
    r = _Reader(data)
    if len(data) < 2:
        raise MeshError("file is too small")
    header = struct.unpack_from("<H", data)[0]
    if header == M_HEADER:
        r.e = "<"
    elif header == 0x0010:
        r.e = ">"
    else:
        raise MeshError("not an Ogre binary mesh (bad header)")
    r.pos = 2
    version = r.string()
    if not version.startswith("[MeshSerializer_v"):
        raise MeshError(f"unexpected serializer header {version!r}")
    mesh = OgreMesh(version=version.strip("[]"), endian="little" if r.e == "<" else "big")

    while not r.eof():
        cid, end = r.chunk()
        if cid == M_MESH:
            _read_mesh_chunk(r, mesh, end)
        else:
            r.pos = end
    return mesh


def _read_mesh_chunk(r: _Reader, mesh: OgreMesh, end: int) -> None:
    mesh.skeletally_animated = r.boolean()
    while r.pos < end and not r.eof():
        cid, chunk_end = r.chunk()
        if cid == M_GEOMETRY:
            mesh.shared_geometry = _read_geometry(r, chunk_end)
        elif cid == M_SUBMESH:
            mesh.submeshes.append(_read_submesh(r, chunk_end))
        elif cid == M_MESH_SKELETON_LINK:
            mesh.skeleton = r.string()
        elif cid == M_MESH_BONE_ASSIGNMENT:
            mesh.bone_assignments.append(_read_bone_assignment(r))
        elif cid == M_MESH_BOUNDS:
            mesh.bounds = r.unpack("7f")
        elif cid == M_SUBMESH_NAME_TABLE:
            while r.pos < chunk_end and r.peek_chunk() == M_SUBMESH_NAME_TABLE_ELEMENT:
                r.chunk()
                index = r.u16()
                name = r.string()
                if index < len(mesh.submeshes):
                    mesh.submeshes[index].name = name
        r.pos = chunk_end


def _read_bone_assignment(r: _Reader) -> Tuple[int, int, float]:
    vertex, bone, weight = r.unpack("IHf")
    return vertex, bone, weight


def _read_submesh(r: _Reader, end: int) -> SubMesh:
    material = r.string()
    shared = r.boolean()
    index_count = r.u32()
    use32 = r.boolean()
    if index_count:
        indices = list(r.unpack(f"{index_count}{'I' if use32 else 'H'}"))
    else:
        indices = []
    sub = SubMesh(material, shared, indices, use32)
    while r.pos < end and not r.eof():
        cid, chunk_end = r.chunk()
        if cid == M_GEOMETRY:
            sub.geometry = _read_geometry(r, chunk_end)
        elif cid == M_SUBMESH_OPERATION:
            sub.operation = r.u16()
        elif cid == M_SUBMESH_BONE_ASSIGNMENT:
            sub.bone_assignments.append(_read_bone_assignment(r))
        r.pos = chunk_end
    return sub


def _read_geometry(r: _Reader, end: int) -> Geometry:
    geometry = Geometry(r.u32())
    geometry._endian = r.e
    while r.pos < end and not r.eof():
        cid, chunk_end = r.chunk()
        if cid == M_GEOMETRY_VERTEX_DECLARATION:
            while r.pos < chunk_end and r.peek_chunk() == M_GEOMETRY_VERTEX_ELEMENT:
                _, element_end = r.chunk()
                geometry.elements.append(VertexElement(*r.unpack("5H")))
                r.pos = element_end
        elif cid == M_GEOMETRY_VERTEX_BUFFER:
            bind, vertex_size = r.unpack("HH")
            data_id, _ = r.chunk()
            if data_id != M_GEOMETRY_VERTEX_BUFFER_DATA:
                raise MeshError("vertex buffer without data")
            size = geometry.vertex_count * vertex_size
            if r.pos + size > len(r.data):
                raise MeshError("vertex buffer data is truncated")
            geometry.buffers[bind] = VertexBuffer(bind, vertex_size, r.data[r.pos:r.pos + size], r.pos)
            r.pos += size
        r.pos = chunk_end
    return geometry


# ---------------------------------------------------------------------------
# XML (the OgreXMLConverter layout)
# ---------------------------------------------------------------------------

def _fmt(value: float) -> str:
    return f"{value:.6g}"


def _geometry_xml(parent: ET.Element, tag: str, geometry: Geometry) -> None:
    geom = ET.SubElement(parent, tag, vertexcount=str(geometry.vertex_count))
    for source in sorted({e.source for e in geometry.elements}):
        elements = sorted((e for e in geometry.elements if e.source == source), key=lambda e: e.offset)
        attrs = {}
        texcoords = [e for e in elements if e.semantic == 7]
        for e in elements:
            name = SEMANTICS.get(e.semantic)
            if name == "position":
                attrs["positions"] = "true"
            elif name == "normal":
                attrs["normals"] = "true"
            elif name == "diffuse":
                attrs["colours_diffuse"] = "true"
            elif name == "specular":
                attrs["colours_specular"] = "true"
            elif name == "tangent":
                attrs["tangents"] = "true"
                attrs["tangent_dimensions"] = str(TYPES.get(e.type, ("f", 3, None))[1])
            elif name == "binormal":
                attrs["binormals"] = "true"
        if texcoords:
            attrs["texture_coords"] = str(len(texcoords))
            for n, e in enumerate(texcoords):
                attrs[f"texture_coord_dimensions_{n}"] = f"float{TYPES.get(e.type, ('f', 2, None))[1]}"
        vb = ET.SubElement(geom, "vertexbuffer", attrs)
        decoded = {id(e): geometry.decode(e) for e in elements}
        for i in range(geometry.vertex_count):
            vertex = ET.SubElement(vb, "vertex")
            for e in elements:
                values = decoded[id(e)]
                if i >= len(values):
                    continue
                v = values[i]
                name = SEMANTICS.get(e.semantic)
                if name in ("position", "normal", "binormal"):
                    ET.SubElement(vertex, name, x=_fmt(v[0]), y=_fmt(v[1]), z=_fmt(v[2]) if len(v) > 2 else "0")
                elif name == "tangent":
                    attrs = dict(x=_fmt(v[0]), y=_fmt(v[1]), z=_fmt(v[2]))
                    if len(v) > 3:
                        attrs["w"] = _fmt(v[3])
                    ET.SubElement(vertex, "tangent", attrs)
                elif name == "texcoord":
                    keys = ("u", "v", "w", "x")
                    ET.SubElement(vertex, "texcoord", {keys[k]: _fmt(v[k]) for k in range(len(v))})
                elif name in ("diffuse", "specular"):
                    ET.SubElement(vertex, f"colour_{name}", value=_colour(e.type, v))
    return None


def _colour(type_id: int, value: tuple) -> str:
    if type_id in COLOUR_TYPES:
        packed = value[0]
        if COLOUR_TYPES[type_id] == "argb":
            a, r, g, b = (packed >> 24) & 255, (packed >> 16) & 255, (packed >> 8) & 255, packed & 255
        else:
            a, b, g, r = (packed >> 24) & 255, (packed >> 16) & 255, (packed >> 8) & 255, packed & 255
        return " ".join(_fmt(c / 255.0) for c in (r, g, b, a))
    return " ".join(_fmt(float(c)) for c in value)


def to_xml(mesh: OgreMesh) -> ET.ElementTree:
    root = ET.Element("mesh")
    if mesh.shared_geometry is not None:
        _geometry_xml(root, "sharedgeometry", mesh.shared_geometry)
    subs = ET.SubElement(root, "submeshes")
    for sub in mesh.submeshes:
        triangles = sub.triangles()
        el = ET.SubElement(subs, "submesh", material=sub.material,
                           usesharedvertices="true" if sub.uses_shared_vertices else "false",
                           use32bitindexes="true" if sub.use32bit else "false",
                           operationtype=OPERATIONS.get(sub.operation, "triangle_list")
                           if sub.operation not in (5, 6) else "triangle_list")
        faces = ET.SubElement(el, "faces", count=str(len(triangles)))
        for a, b, c in triangles:
            ET.SubElement(faces, "face", v1=str(a), v2=str(b), v3=str(c))
        if sub.geometry is not None and not sub.uses_shared_vertices:
            _geometry_xml(el, "geometry", sub.geometry)
        if sub.bone_assignments:
            bones = ET.SubElement(el, "boneassignments")
            for v, b, w in sub.bone_assignments:
                ET.SubElement(bones, "vertexboneassignment", vertexindex=str(v), boneindex=str(b), weight=_fmt(w))
    if mesh.skeleton:
        ET.SubElement(root, "skeletonlink", name=mesh.skeleton)
    if mesh.bone_assignments:
        bones = ET.SubElement(root, "boneassignments")
        for v, b, w in mesh.bone_assignments:
            ET.SubElement(bones, "vertexboneassignment", vertexindex=str(v), boneindex=str(b), weight=_fmt(w))
    if any(sub.name for sub in mesh.submeshes):
        names = ET.SubElement(root, "submeshnames")
        for i, sub in enumerate(mesh.submeshes):
            if sub.name:
                ET.SubElement(names, "submeshname", name=sub.name, index=str(i))
    return ET.ElementTree(root)


def write_xml(mesh: OgreMesh, path: Union[str, Path]) -> Path:
    tree = to_xml(mesh)
    ET.indent(tree, space="    ")
    tree.write(str(path), encoding="utf-8", xml_declaration=False)
    return Path(path)


def mesh_to_xml_file(mesh_path: Union[str, Path], xml_path: Optional[Union[str, Path]] = None) -> Path:
    """Convert ``foo.mesh`` to ``foo.mesh.xml`` (what OgreXMLConverter did)."""
    mesh_path = Path(mesh_path)
    target = Path(xml_path) if xml_path else mesh_path.with_name(mesh_path.name + ".xml")
    return write_xml(read_mesh(mesh_path), target)


# ---------------------------------------------------------------------------
# Writing normals back
# ---------------------------------------------------------------------------

def normals_from_xml(xml_path: Union[str, Path]) -> List[Optional[List[Tuple[float, float, float]]]]:
    """Normals per geometry in :func:`to_xml` order: shared geometry first (or
    None), then one entry per submesh (None when it uses shared vertices)."""
    root = ET.parse(str(xml_path)).getroot()

    def geometry_normals(geom) -> Optional[List[Tuple[float, float, float]]]:
        if geom is None:
            return None
        for vb in geom.findall("vertexbuffer"):
            if vb.get("normals") == "true":
                out = []
                for vertex in vb.findall("vertex"):
                    n = vertex.find("normal")
                    out.append((float(n.get("x", 0)), float(n.get("y", 0)), float(n.get("z", 0)))
                               if n is not None else None)
                return out
        return None

    result = [geometry_normals(root.find("sharedgeometry"))]
    subs = root.find("submeshes")
    for sub in (subs.findall("submesh") if subs is not None else []):
        result.append(None if sub.get("usesharedvertices") == "true" else geometry_normals(sub.find("geometry")))
    return result


def patch_normals(mesh_path: Union[str, Path], normals: Sequence[Optional[Sequence]]) -> int:
    """Overwrite FLOAT3 normals in a binary mesh in place; returns vertices written.

    ``normals`` is the structure :func:`normals_from_xml` returns.
    """
    mesh_path = Path(mesh_path)
    data = bytearray(mesh_path.read_bytes())
    mesh = read_mesh(bytes(data))
    e = "<" if mesh.endian == "little" else ">"
    geometries = [mesh.shared_geometry] + [None if s.uses_shared_vertices else s.geometry for s in mesh.submeshes]
    written = 0
    for geometry, values in zip(geometries, normals):
        if geometry is None or not values:
            continue
        element = next((el for el in geometry.elements if el.semantic == 4 and el.index == 0), None)
        if element is None:
            continue
        if element.type != FLOAT3:
            raise MeshError("normals are not stored as FLOAT3; cannot patch in place")
        buffer = geometry.buffers[element.source]
        pack = struct.Struct(e + "3f")
        for i, normal in enumerate(values[:geometry.vertex_count]):
            if normal is None:
                continue
            pack.pack_into(data, buffer.file_offset + i * buffer.vertex_size + element.offset, *normal)
            written += 1
    mesh_path.write_bytes(bytes(data))
    return written
