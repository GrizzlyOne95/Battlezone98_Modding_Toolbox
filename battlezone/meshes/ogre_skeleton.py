"""Ogre binary ``.skeleton`` reader and writer (``[Serializer_v1.80]``).

Chunks, all ``u16 id, u32 size`` with the size counting the 6-byte header::

    0x1000 header      the version string, newline terminated (no size field)
    0x1010 blend mode  u16 (0 = average)
    0x2000 bone        name\\n, u16 handle, 3f position, 4f orientation (x y z w),
                       3f scale only when it is not (1, 1, 1)
    0x3000 parent      u16 child handle, u16 parent handle
    0x4000 animation   name\\n, f length, then 0x4100 tracks
    0x4100 track       u16 bone handle, then 0x4110 keyframes
    0x4110 keyframe    f time, 4f orientation, 3f translation, 3f scale if present

Ogre writes a bone chunk's size without its name (a long-standing quirk of
``SkeletonSerializer::calcBoneSize``) and its reader only compares that size
against the no-scale size, so the writer does the same and the reader walks
bone chunks field by field instead of trusting the size. Stock Redux
skeletons (``[Serializer_v1.80]``) round-trip byte for byte.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Union

__all__ = ["SkeletonError", "Bone", "Keyframe", "Track", "Animation", "Skeleton", "read_skeleton",
           "write_skeleton"]

SKELETON_HEADER = 0x1000
SKELETON_BLENDMODE = 0x1010
SKELETON_BONE = 0x2000
SKELETON_BONE_PARENT = 0x3000
SKELETON_ANIMATION = 0x4000
SKELETON_ANIMATION_BASEINFO = 0x4010
SKELETON_ANIMATION_TRACK = 0x4100
SKELETON_ANIMATION_TRACK_KEYFRAME = 0x4110
SKELETON_ANIMATION_LINK = 0x5000
SERIALIZER_VERSION = "[Serializer_v1.80]"
_BONE_SIZE_NO_SCALE = 6 + 2 + 12 + 16


class SkeletonError(ValueError):
    """Not an Ogre binary skeleton, or cut short."""


@dataclass
class Bone:
    name: str
    handle: int
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    orientation: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)    # x, y, z, w
    scale: Optional[Tuple[float, float, float]] = None
    parent: Optional[int] = None


@dataclass
class Keyframe:
    time: float
    orientation: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    translation: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: Optional[Tuple[float, float, float]] = None


@dataclass
class Track:
    bone: int
    keyframes: List[Keyframe] = field(default_factory=list)


@dataclass
class Animation:
    name: str
    length: float
    tracks: List[Track] = field(default_factory=list)


@dataclass
class Skeleton:
    bones: List[Bone] = field(default_factory=list)
    animations: List[Animation] = field(default_factory=list)
    blend_mode: int = 0
    version: str = SERIALIZER_VERSION

    def bone(self, name: str) -> Optional[Bone]:
        return next((b for b in self.bones if b.name == name), None)


def _string(data: bytes, pos: int) -> Tuple[str, int]:
    end = data.find(b"\n", pos)
    if end < 0:
        raise SkeletonError("unterminated string")
    return data[pos:end].decode("utf-8", "replace"), end + 1


def read_skeleton(source: Union[str, Path, bytes]) -> Skeleton:
    data = bytes(source) if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
    if len(data) < 2 or struct.unpack_from("<H", data)[0] != SKELETON_HEADER:
        raise SkeletonError("not an Ogre binary skeleton (bad header)")
    version, pos = _string(data, 2)
    skeleton = Skeleton(version=version)
    by_handle = {}
    try:
        while pos + 6 <= len(data):
            cid, size = struct.unpack_from("<HI", data, pos)
            body = pos + 6
            if cid == SKELETON_BONE:
                name, p = _string(data, body)
                handle, = struct.unpack_from("<H", data, p)
                values = struct.unpack_from("<7f", data, p + 2)
                p += 30
                scale = None
                if size > _BONE_SIZE_NO_SCALE:
                    scale = struct.unpack_from("<3f", data, p)
                    p += 12
                bone = Bone(name, handle, values[:3], values[3:], scale)
                skeleton.bones.append(bone)
                by_handle[handle] = bone
                pos = p
                continue
            if size < 6:
                raise SkeletonError(f"chunk {cid:#x} at byte {pos} has size {size}")
            end = pos + size
            if cid == SKELETON_BLENDMODE:
                skeleton.blend_mode, = struct.unpack_from("<H", data, body)
            elif cid == SKELETON_BONE_PARENT:
                child, parent = struct.unpack_from("<HH", data, body)
                if child in by_handle:
                    by_handle[child].parent = parent
            elif cid == SKELETON_ANIMATION:
                skeleton.animations.append(_read_animation(data, body, end))
            pos = end
    except struct.error as exc:
        raise SkeletonError(f"cut short: {exc}") from None
    return skeleton


def _read_animation(data: bytes, pos: int, end: int) -> Animation:
    name, pos = _string(data, pos)
    length, = struct.unpack_from("<f", data, pos)
    animation = Animation(name, length)
    pos += 4
    while pos + 6 <= end:
        cid, size = struct.unpack_from("<HI", data, pos)
        if size < 6:
            break
        if cid == SKELETON_ANIMATION_TRACK:
            bone, = struct.unpack_from("<H", data, pos + 6)
            track = Track(bone)
            k, track_end = pos + 8, pos + size
            while k + 6 <= track_end:
                kid, ksize = struct.unpack_from("<HI", data, k)
                if kid == SKELETON_ANIMATION_TRACK_KEYFRAME and ksize >= 6 + 32:
                    values = struct.unpack_from("<8f", data, k + 6)
                    scale = struct.unpack_from("<3f", data, k + 38) if ksize >= 6 + 44 else None
                    track.keyframes.append(Keyframe(values[0], values[1:5], values[5:8], scale))
                k += max(ksize, 6)
            animation.tracks.append(track)
        pos += size
    return animation


def _chunk(cid: int, body: bytes) -> bytes:
    return struct.pack("<HI", cid, len(body) + 6) + body


def _is_unit(scale) -> bool:
    return scale is None or all(abs(s - 1.0) < 1e-6 for s in scale)


def write_skeleton(skeleton: Skeleton, path: Optional[Union[str, Path]] = None) -> bytes:
    """Serialize ``skeleton``; returns the bytes and writes ``path`` when given."""
    out = [struct.pack("<H", SKELETON_HEADER), skeleton.version.encode() + b"\n"]
    if skeleton.version != "[Serializer_v1.10]":         # v1.10 predates the blend mode chunk
        out.append(_chunk(SKELETON_BLENDMODE, struct.pack("<H", skeleton.blend_mode)))
    for bone in skeleton.bones:
        fields = struct.pack("<H7f", bone.handle, *bone.position, *bone.orientation)
        size = _BONE_SIZE_NO_SCALE
        if not _is_unit(bone.scale):
            fields += struct.pack("<3f", *bone.scale)
            size += 12
        out.append(struct.pack("<HI", SKELETON_BONE, size) + bone.name.encode("utf-8") + b"\n" + fields)
    for bone in skeleton.bones:
        if bone.parent is not None:
            out.append(_chunk(SKELETON_BONE_PARENT, struct.pack("<HH", bone.handle, bone.parent)))
    for animation in skeleton.animations:
        body = animation.name.encode("utf-8") + b"\n" + struct.pack("<f", animation.length)
        for track in animation.tracks:
            keys = b""
            for key in track.keyframes:
                kbody = struct.pack("<8f", key.time, *key.orientation, *key.translation)
                if not _is_unit(key.scale):
                    kbody += struct.pack("<3f", *key.scale)
                keys += _chunk(SKELETON_ANIMATION_TRACK_KEYFRAME, kbody)
            body += _chunk(SKELETON_ANIMATION_TRACK, struct.pack("<H", track.bone) + keys)
        out.append(_chunk(SKELETON_ANIMATION, body))
    data = b"".join(out)
    if path is not None:
        Path(path).write_bytes(data)
    return data
