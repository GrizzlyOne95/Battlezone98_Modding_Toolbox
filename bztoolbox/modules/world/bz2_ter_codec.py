"""Read BZ2/BZCC TERR v3-v5 terrain without losing authored channels.

The cluster layout follows Nielk1/bz2terraineditor's Terrain.Read.  Data is
stored in file order, with array axes [z, x]; compass orientation is not
inferred from the file itself.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class SourceTerrain:
    version: int
    grid_min_x: int
    grid_min_z: int
    grid_max_x: int
    grid_max_z: int
    heights_m: np.ndarray
    colors: np.ndarray
    alphas: np.ndarray
    cells: np.ndarray
    info: np.ndarray

    @property
    def spacing_m(self) -> int:
        return 8 if self.version < 4 else 2

    @property
    def texture_indices(self) -> np.ndarray:
        return np.stack([((self.info >> (4 * layer)) & 15).astype(np.uint8)
                         for layer in range(4)])

    @property
    def visibility_mask(self) -> np.ndarray:
        """Four per-layer cluster visibility bits from InfoMap bits 16..19."""
        return ((self.info >> 16) & 0x0F).astype(np.uint8)

    @property
    def owner_team(self) -> np.ndarray:
        """Cluster owner-team nibble from InfoMap bits 20..23."""
        return ((self.info >> 20) & 0x0F).astype(np.uint8)

    @property
    def build_type(self) -> np.ndarray:
        """Cluster build-type value from InfoMap bits 24..25."""
        return ((self.info >> 24) & 0x03).astype(np.uint8)


class _Reader:
    def __init__(self, data: bytes):
        self.data = memoryview(data)
        self.offset = 0

    def take(self, length: int) -> memoryview:
        if length < 0 or self.offset + length > len(self.data):
            raise ValueError(f"Truncated TER at byte {self.offset}: need {length} bytes")
        result = self.data[self.offset:self.offset + length]
        self.offset += length
        return result

    def scalar(self, fmt: str):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]


def read_ter(path: str | Path) -> SourceTerrain:
    return decode_ter(Path(path).read_bytes())


def decode_ter(data: bytes) -> SourceTerrain:
    reader = _Reader(data)
    if reader.take(4).tobytes() != b"TERR":
        raise ValueError("TER must begin with TERR (headerless v0-v2 not supported)")
    version = reader.scalar("<I")
    if version not in (3, 4, 5):
        raise ValueError(f"Unsupported TER version {version}; expected 3, 4 or 5")
    min_x, min_z, max_x, max_z = struct.unpack("<hhhh", reader.take(8))
    width, depth = max_x - min_x, max_z - min_z
    cluster = 4 if version == 3 else 16
    if width <= 0 or depth <= 0 or width % cluster or depth % cluster:
        raise ValueError(f"Invalid TER bounds {width}x{depth} for {cluster}-sample clusters")
    if width * depth > 32_000_000:
        raise ValueError("TER dimensions exceed the safe 32-million-sample limit")

    heights = np.empty((depth, width), dtype=np.float32)
    colors = np.empty((depth, width, 3), dtype=np.uint8)
    alphas = np.empty((3, depth, width), dtype=np.uint8)
    cells = np.empty((depth, width), dtype=np.uint8)
    info = np.empty((depth // cluster, width // cluster), dtype=np.uint32)

    def field(dtype: str, count: int, expanded: bool) -> np.ndarray:
        values = np.frombuffer(reader.take(np.dtype(dtype).itemsize * (count if expanded else 1)), dtype=dtype)
        return values if expanded else np.full(count, values[0], dtype=dtype)

    for z in range(0, depth, cluster):
        for x in range(0, width, cluster):
            flags = reader.scalar("<B") if version == 5 else 0x3F
            if flags & ~0x3F:
                raise ValueError(f"Unknown TER compression flags 0x{flags:02x}")
            count = cluster * cluster
            height_dtype = "<i2" if version == 3 else "<f4"
            height_values = field(height_dtype, count, bool(flags & 1)).reshape(cluster, cluster)
            heights[z:z + cluster, x:x + cluster] = height_values * (0.1 if version == 3 else 1.0)
            if version == 3:
                reader.take(count)  # stored normals, not needed for HG2
            if flags & 2:
                rgb = np.frombuffer(reader.take(count * 3), dtype=np.uint8).reshape(count, 3)
            else:
                rgb = np.broadcast_to(np.frombuffer(reader.take(3), dtype=np.uint8), (count, 3))
            colors[z:z + cluster, x:x + cluster] = rgb.reshape(cluster, cluster, 3)
            for layer in range(3):
                a = field("u1", count, bool(flags & (1 << (layer + 2))))
                alphas[layer, z:z + cluster, x:x + cluster] = a.reshape(cluster, cluster)
            c = field("u1", count, bool(flags & 32))
            cells[z:z + cluster, x:x + cluster] = c.reshape(cluster, cluster)
            info[z // cluster, x // cluster] = reader.scalar("<I")

    if reader.offset != len(data):
        raise ValueError(f"TER has {len(data) - reader.offset} unexpected trailing bytes")
    if not np.isfinite(heights).all():
        raise ValueError("TER contains non-finite elevations")
    return SourceTerrain(version, min_x, min_z, max_x, max_z,
                         heights, colors, alphas, cells, info)
