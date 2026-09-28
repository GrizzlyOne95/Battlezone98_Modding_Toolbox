"""Readers for the legacy binary model formats: ``.geo``, ``.vdf`` and ``.sdf``.

Decoded: GEO vertices, normals and faces (with per-corner UVs, face colour
and plane), and the part records of VDF (vehicle) and SDF (structure) files
with their transforms. Validation and the Redux porter
(:mod:`battlezone.meshes.legacy_port`) use them. Layouts follow the BZ98R
Blender ToolKit's readers.

GEO::

    header   4s magic ("OEG."), i, 16s name, i vertex count, i face count, i
    vertices count x 3f, then count x 3f normals
    faces    i index, i vertex count, 3B colour, 4f plane, i, 3s, 13s texture,
             i parent, i node; then vertex count x (i vertex, i normal, 2f uv)

VDF / SDF::

    BWD2 header (20 bytes), then the VDFC (68) or SDFC (78) block
    VDF: EXIT, VGEO header, 28 bands x count x 100-byte part records,
         then tagged chunks (EXIT, ANIM, COLP, SCPS, VLOC, ...)
    SDF: SGEO header, 6 bands x count x 120-byte part records, optional ANIM

A part record starts ``8s name, 12f matrix, 8s parent, 3f centre, f radius,
3f half extents, i class, i flags``. The matrix is the part's right, up and
front axes then its position, all in the parent's space (so
``parent_point = x*right + y*up + z*front + position``). VDF bands are
``lod_slot * 4 + damage_state``; band 0 holds the parts the model is built
from, band 4 (lod slot 1) the cockpit, band 8 the low-detail model.

ANIM (VDF and SDF)::

    16s name, 5i counts (sequences, parts, rotation, scale and position
    keys), 7i runtime pointers
    sequences  count x (i index, 32i, i start frame, i signed length,
               i loop, f frames per second)
    parts      count x (8s name, i flags, 12f, 12f, then start and count
               of its rotation, scale and position keys)
    keys       i frame + 4f (w, x, y, z), i frame + 3f, i frame + 3f

All sequences share one timeline; a sequence plays ``abs(length)`` frames
from ``start``, backwards when the length is negative. Keys are the part's
full transform in its parent's space (not an offset from the record). The
stored rotation is the conjugate of the Hamilton quaternion of the part's
column matrix: sbcomm's ``sbc11an3`` record has quaternion y = -0.0022 and
its first key stores +0.0022.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Union

__all__ = ["ModelError", "GeoFace", "GeoFile", "Part", "AnimSequence", "AnimTrack", "BwdModel", "read_geo",
           "read_vdf", "read_sdf", "read_model"]

VDF_BANDS = 28
SDF_BANDS = 6
_GEO_HEADER = struct.Struct("<4si16siii")
_GEO_FACE = struct.Struct("<iiBBBffffi3s13sii")
_FACE_VERT = struct.Struct("<iiff")
_BWD_HEADER = struct.Struct("<4si4sii")
_VDF_RECORD = struct.Struct("<8s12f8s7fii")         # 100 bytes
_SDF_RECORD = struct.Struct("<8s12f8s7fiii4f")      # 120 bytes
_SECTION = struct.Struct("<4si")
_ANIM_SEQUENCE = struct.Struct("<i128xiiif")         # 148 bytes
_ANIM_PART = struct.Struct("<8si96x6i")              # 132 bytes


class ModelError(ValueError):
    """The file is not a readable model (bad magic, or cut short)."""


def _text(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("ascii", "replace").strip()


# ---------------------------------------------------------------------------
# GEO
# ---------------------------------------------------------------------------

@dataclass
class GeoFace:
    index: int
    vertices: List[int]
    normals: List[int]
    texture: str
    uvs: List[Tuple[float, float]] = field(default_factory=list)   # one per corner
    colour: Tuple[int, int, int] = (0, 0, 0)
    plane: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # stock normals point inward


@dataclass
class GeoFile:
    name: str
    vertex_count: int
    faces: List[GeoFace] = field(default_factory=list)
    bad_vertices: int = 0            # vertices with a NaN or infinite coordinate
    declared_faces: int = 0
    positions: List[Tuple[float, float, float]] = field(default_factory=list)
    normals: List[Tuple[float, float, float]] = field(default_factory=list)


def read_geo(source: Union[str, Path, bytes]) -> GeoFile:
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    if len(data) < _GEO_HEADER.size:
        raise ModelError("file is too small to be a GEO")
    magic, _unknown, name, vertex_count, face_count, _unknown2 = _GEO_HEADER.unpack_from(data, 0)
    if b"OEG" not in magic and b"GEO" not in magic:    # stock files store ".GEO" as a little-endian int
        raise ModelError(f"not a GEO file (magic {magic!r})")
    if vertex_count < 0 or face_count < 0:
        raise ModelError(f"negative vertex or face count ({vertex_count}, {face_count})")
    pos = _GEO_HEADER.size
    end = pos + vertex_count * 24
    if end > len(data):
        raise ModelError(f"cut short: {vertex_count} vertices declared, the file ends first")
    positions = [struct.unpack_from("<3f", data, pos + i * 12) for i in range(vertex_count)]
    bad = sum(1 for p in positions if not all(math.isfinite(v) for v in p))
    geo = GeoFile(_text(name), vertex_count, bad_vertices=bad, declared_faces=face_count,
                  positions=positions)
    normals_at = pos + vertex_count * 12
    geo.normals = [struct.unpack_from("<3f", data, normals_at + i * 12) for i in range(vertex_count)]
    pos = end
    for _ in range(face_count):
        if pos + _GEO_FACE.size > len(data):
            raise ModelError(f"cut short: {face_count} faces declared, only {len(geo.faces)} present")
        fields = _GEO_FACE.unpack_from(data, pos)
        index, count, texture = fields[0], fields[1], fields[11]
        pos += _GEO_FACE.size
        if count < 0 or pos + count * _FACE_VERT.size > len(data):
            raise ModelError(f"face {len(geo.faces)} declares {count} vertices, past the end of the file")
        verts, normals, uvs = [], [], []
        for _ in range(count):
            vert, normal, u, v = _FACE_VERT.unpack_from(data, pos)
            pos += _FACE_VERT.size
            verts.append(vert)
            normals.append(normal)
            uvs.append((u, v))
        geo.faces.append(GeoFace(index, verts, normals, _text(texture), uvs,
                                 (fields[2], fields[3], fields[4]), tuple(fields[5:9])))
    return geo


# ---------------------------------------------------------------------------
# VDF / SDF
# ---------------------------------------------------------------------------

@dataclass
class Part:
    name: str
    parent: str
    klass: int
    flags: int
    band: int
    slot: int
    matrix: Tuple[float, ...] = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)


@dataclass
class AnimSequence:
    index: int                        # what the game asks for (person: 0 crouch, 1 stand, 2 standing, ...)
    start: int                        # first frame on the shared timeline
    length: int                       # frame count; negative plays backwards from start
    loop: int
    speed: float                      # frames per second

    @property
    def frames(self) -> Tuple[int, ...]:
        """First and last timeline frame, in playback order."""
        step = 1 if self.length >= 0 else -1
        return self.start, self.start + (abs(self.length) - 1) * step


@dataclass
class AnimTrack:
    name: str                         # the part it moves
    flags: int = 0
    rotations: List[Tuple[int, Tuple[float, float, float, float]]] = field(default_factory=list)  # (w, x, y, z)
    positions: List[Tuple[int, Tuple[float, float, float]]] = field(default_factory=list)
    scales: List[Tuple[int, Tuple[float, float, float]]] = field(default_factory=list)


@dataclass
class BwdModel:
    kind: str                         # "vdf" or "sdf"
    name: str
    geocount: int
    parts: List[Part] = field(default_factory=list)       # every named record, all bands
    chunks: List[str] = field(default_factory=list)       # tags after the part records
    canonical_header: bool = True
    sequences: List[AnimSequence] = field(default_factory=list)   # from the ANIM chunk
    tracks: List[AnimTrack] = field(default_factory=list)

    def band(self, band: int) -> List[Part]:
        return [part for part in self.parts if part.band == band]

    def track(self, name: str) -> Optional[AnimTrack]:
        low = name.lower()
        return next((t for t in self.tracks if t.name.lower() == low), None)


def _read_parts(data: bytes, pos: int, geocount: int, bands: int, record: struct.Struct,
                model: BwdModel) -> int:
    needed = geocount * bands * record.size
    if pos + needed > len(data):
        raise ModelError(f"cut short: {geocount} parts x {bands} bands declared, the file ends first")
    for index in range(geocount * bands):
        fields = record.unpack_from(data, pos + index * record.size)
        name = _text(fields[0])
        if name:
            band, slot = divmod(index, geocount)
            model.parts.append(Part(name, _text(fields[13]), fields[21], fields[22] & 0xFFFFFFFF, band, slot,
                                    tuple(fields[1:13])))
    return pos + needed


def _walk_chunks(data: bytes, pos: int, model: BwdModel) -> None:
    while pos + 8 <= len(data):
        tag, length = _SECTION.unpack_from(data, pos)
        name = tag.decode("ascii", "replace").rstrip("\0")
        model.chunks.append(name)
        if tag == b"EXIT":
            pos += 8
        elif 8 <= length <= len(data) - pos:
            if tag == b"ANIM" and not model.sequences:
                _read_anim(data[pos + 8:pos + length], model)
            pos += length
        else:
            return   # a length we cannot trust; the rest is opaque


def _read_anim(body: bytes, model: BwdModel) -> None:
    """Sequences and per-part keys of an ANIM chunk body; a short or odd chunk is left unread."""
    if len(body) < 64:
        return
    counts = struct.unpack_from("<5i", body, 16)
    n_seq, n_parts, n_rot, n_scale, n_pos = counts
    if min(counts) < 0 or 64 + n_seq * 148 + n_parts * 132 + n_rot * 20 + (n_scale + n_pos) * 16 > len(body):
        return
    pos = 64
    sequences = []
    for _ in range(n_seq):
        index, start, length, loop, speed = _ANIM_SEQUENCE.unpack_from(body, pos)
        sequences.append(AnimSequence(index, start, length, loop, speed))
        pos += _ANIM_SEQUENCE.size
    ranges = []
    for _ in range(n_parts):
        name, flags, r0, rn, s0, sn, p0, pn = _ANIM_PART.unpack_from(body, pos)
        ranges.append((_text(name), flags, r0, rn, s0, sn, p0, pn))
        pos += _ANIM_PART.size
    rotations = [struct.unpack_from("<i4f", body, pos + i * 20) for i in range(n_rot)]
    pos += n_rot * 20
    scales = [struct.unpack_from("<i3f", body, pos + i * 16) for i in range(n_scale)]
    pos += n_scale * 16
    positions = [struct.unpack_from("<i3f", body, pos + i * 16) for i in range(n_pos)]

    def keys(table, start, count):
        return sorted(((k[0], tuple(k[1:])) for k in table[max(start, 0):max(start, 0) + max(count, 0)]),
                      key=lambda k: k[0])
    model.sequences = sequences
    model.tracks = [AnimTrack(name, flags, keys(rotations, r0, rn), keys(positions, p0, pn), keys(scales, s0, sn))
                    for name, flags, r0, rn, s0, sn, p0, pn in ranges]


def _read_bwd(data: bytes, kind: str) -> BwdModel:
    if len(data) < _BWD_HEADER.size + 8:
        raise ModelError(f"file is too small to be a {kind.upper()}")
    bwd, version, rev, section, tail = _BWD_HEADER.unpack_from(data, 0)
    if bwd != b"BWD2" or rev[:3] != b"REV":
        raise ModelError(f"not a {kind.upper()} file (missing BWD2/REV header)")
    pos = _BWD_HEADER.size
    tag, length = _SECTION.unpack_from(data, pos)
    expected = b"VDFC" if kind == "vdf" else b"SDFC"
    if tag != expected:
        raise ModelError(f"expected a {expected.decode()} block, found {tag!r}")
    name = _text(data[pos + 8:pos + 24])
    model = BwdModel(kind, name, 0, canonical_header=(version == 8 and section == 12))
    pos += length if 8 <= length <= len(data) - pos else (68 if kind == "vdf" else 78)
    while pos + 8 <= len(data) and data[pos:pos + 4] == b"EXIT":
        pos += 8
    geo_tag = b"VGEO" if kind == "vdf" else b"SGEO"
    if data[pos:pos + 4] != geo_tag:
        raise ModelError(f"expected a {geo_tag.decode()} block, found {data[pos:pos + 4]!r}")
    model.geocount = struct.unpack_from("<i", data, pos + 8)[0]
    if model.geocount < 0 or model.geocount > 10000:
        raise ModelError(f"implausible part count {model.geocount}")
    pos += 12
    if kind == "vdf":
        pos = _read_parts(data, pos, model.geocount, VDF_BANDS, _VDF_RECORD, model)
    else:
        pos = _read_parts(data, pos, model.geocount, SDF_BANDS, _SDF_RECORD, model)
    _walk_chunks(data, pos, model)
    return model


def read_vdf(source: Union[str, Path, bytes]) -> BwdModel:
    return _read_bwd(source if isinstance(source, bytes) else Path(source).read_bytes(), "vdf")


def read_sdf(source: Union[str, Path, bytes]) -> BwdModel:
    return _read_bwd(source if isinstance(source, bytes) else Path(source).read_bytes(), "sdf")


def read_model(path: Union[str, Path]) -> Optional[Union[GeoFile, BwdModel]]:
    """Read a ``.geo``, ``.vdf`` or ``.sdf`` by extension; ``None`` for anything else."""
    suffix = Path(path).suffix.lower()
    reader = {".geo": read_geo, ".vdf": read_vdf, ".sdf": read_sdf}.get(suffix)
    return reader(path) if reader else None
