from __future__ import annotations

import os
import struct
from dataclasses import dataclass

import numpy as np


CHUNK_HEADER_BYTES = 8
ZMAP_GRID_SIDE = 80
TER_ZONE_SIDE = 256
TER_ZONE_BYTES = TER_ZONE_SIDE * TER_ZONE_SIDE * 2
METERS_PER_TER_ZONE = 1280


@dataclass(frozen=True)
class MSNTerrain:
    heights: np.ndarray
    zones_x: int
    zones_z: int
    min_x_meters: int
    min_z_meters: int
    zone_count: int
    missing_zone_ids: tuple[int, ...] = ()


def _find_chunk(blob: bytes | memoryview, tag: bytes, *, start: int = 0) -> memoryview:
    """Find a MakeTRN/I76 chunk whose little-endian size includes its 8-byte header."""
    if len(tag) != 4:
        raise ValueError("chunk tag must be exactly four bytes")
    view = memoryview(blob)
    pos = int(start)
    while pos + CHUNK_HEADER_BYTES <= len(view):
        size = struct.unpack_from("<i", view, pos + 4)[0]
        if size < CHUNK_HEADER_BYTES:
            raise ValueError(f"invalid chunk size {size} at offset 0x{pos:X}")
        end = pos + size
        if end > len(view):
            raise ValueError(
                f"chunk {bytes(view[pos:pos+4])!r} at 0x{pos:X} extends beyond the input"
            )
        if bytes(view[pos : pos + 4]) == tag:
            return view[pos:end]
        pos = end
    raise ValueError(f"could not find {tag.decode('ascii', errors='replace')} chunk")


def extract_zmap(msn_payload: bytes) -> tuple[int, np.ndarray]:
    """Extract MakeTRN's TDEF/ZMAP zone-count byte and 80x80 zone-ID map."""
    tdef = _find_chunk(msn_payload, b"TDEF")
    zmap_chunk = _find_chunk(tdef, b"ZMAP", start=CHUNK_HEADER_BYTES)
    payload = zmap_chunk[CHUNK_HEADER_BYTES:]
    required = 1 + ZMAP_GRID_SIDE * ZMAP_GRID_SIDE
    if len(payload) < required:
        raise ValueError(
            f"ZMAP payload is too short: expected at least {required} bytes, found {len(payload)}"
        )
    zone_count = int(payload[0])
    zone_map = np.frombuffer(
        payload[1:required], dtype=np.uint8, count=ZMAP_GRID_SIDE * ZMAP_GRID_SIDE
    ).reshape((ZMAP_GRID_SIDE, ZMAP_GRID_SIDE)).copy()
    if not np.any(zone_map != 0xFF):
        raise ValueError("all ZONES in ZMAP are 0xFF")
    return zone_count, zone_map


def _resolve_companion_ter(msn_path: os.PathLike | str) -> str:
    path = os.path.abspath(os.fspath(msn_path))
    stem = os.path.splitext(path)[0]
    direct = stem + ".TER"
    if os.path.exists(direct):
        return direct

    parent = os.path.dirname(path) or os.curdir
    wanted = (os.path.basename(stem) + ".ter").lower()
    try:
        for name in os.listdir(parent):
            if name.lower() == wanted:
                return os.path.join(parent, name)
    except OSError:
        pass
    raise FileNotFoundError(f"companion TER not found for {path}")


def read_msn_ter(
    msn_path: os.PathLike | str,
    ter_path: os.PathLike | str | None = None,
) -> MSNTerrain:
    """Reproduce MakeTRN 2.1.2's working Interstate '76 MSN+TER terrain import.

    The MSN's TDEF contains a nested ZMAP chunk. ZMAP payload byte 0 is the
    number of TER blocks, followed by an 80x80 byte grid where 0xFF means no
    terrain and every other value identifies one sequential 256x256 TER block.
    MakeTRN crops to the occupied rectangle, uses the first row-major placement
    of each zone ID, masks every TER sample to 12 bits, leaves missing cells at
    zero, and preserves the cropped ZMAP origin as TRN MinX/MinZ in 1280 m units.
    """
    msn_path = os.path.abspath(os.fspath(msn_path))
    if ter_path is None:
        ter_path = _resolve_companion_ter(msn_path)
    else:
        ter_path = os.path.abspath(os.fspath(ter_path))

    with open(msn_path, "rb") as stream:
        zone_count, zone_map = extract_zmap(stream.read())

    occupied = np.argwhere(zone_map != 0xFF)
    min_row, min_col = occupied.min(axis=0)
    max_row, max_col = occupied.max(axis=0)
    zones_z = int(max_row - min_row + 1)
    zones_x = int(max_col - min_col + 1)

    with open(ter_path, "rb") as stream:
        ter_payload = stream.read()
    required = zone_count * TER_ZONE_BYTES
    if len(ter_payload) < required:
        raise ValueError(
            f"TER is truncated: expected {required} bytes for {zone_count} zones, "
            f"found {len(ter_payload)}"
        )

    heights = np.zeros(
        (zones_z * TER_ZONE_SIDE, zones_x * TER_ZONE_SIDE), dtype=np.uint16
    )
    missing: list[int] = []

    for zone_id in range(zone_count):
        matches = np.argwhere(zone_map == zone_id)
        if matches.size == 0:
            missing.append(zone_id)
            continue
        row, col = (int(value) for value in matches[0])
        offset = zone_id * TER_ZONE_BYTES
        zone = (
            np.frombuffer(
                ter_payload,
                dtype="<u2",
                count=TER_ZONE_SIDE * TER_ZONE_SIDE,
                offset=offset,
            )
            .reshape((TER_ZONE_SIDE, TER_ZONE_SIDE))
            .copy()
        )
        zone &= 0x0FFF
        dst_row = (row - int(min_row)) * TER_ZONE_SIDE
        dst_col = (col - int(min_col)) * TER_ZONE_SIDE
        heights[
            dst_row : dst_row + TER_ZONE_SIDE,
            dst_col : dst_col + TER_ZONE_SIDE,
        ] = zone

    return MSNTerrain(
        heights=heights,
        zones_x=zones_x,
        zones_z=zones_z,
        min_x_meters=int(min_col) * METERS_PER_TER_ZONE,
        min_z_meters=int(min_row) * METERS_PER_TER_ZONE,
        zone_count=zone_count,
        missing_zone_ids=tuple(missing),
    )
