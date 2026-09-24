from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import Tuple

import numpy as np

HG2_HEADER = struct.Struct("<HHHHI")
HG2_STRUCTURE_VERSION = 1
HG2_MAP_VERSION = 10
HG2_STORAGE_MASK = 0x1FFF
HG2_STORAGE_MAX_HEIGHT = HG2_STORAGE_MASK
HG2_SAFE_MAX_HEIGHT = 0x0FFF
DEFAULT_ZONE_BITS = 8


@dataclass(frozen=True)
class HG2Header:
    structure_version: int
    zone_bits: int
    zones_x: int
    zones_z: int
    map_version: int

    @property
    def zone_size(self) -> int:
        return 1 << self.zone_bits

    @property
    def shape(self) -> Tuple[int, int]:
        return self.zones_z * self.zone_size, self.zones_x * self.zone_size

    @property
    def sample_count(self) -> int:
        return self.zones_x * self.zones_z * self.zone_size * self.zone_size


def _validate_header(header: HG2Header) -> None:
    if header.zones_x <= 0 or header.zones_z <= 0:
        raise ValueError(f"Invalid HG2 zone dimensions: {header.zones_x}x{header.zones_z}")
    if not 1 <= header.zone_bits <= 12:
        raise ValueError(f"Invalid HG2 zone_bits value: {header.zone_bits}")


def read_hg2_header(path: os.PathLike | str) -> HG2Header:
    with open(path, "rb") as stream:
        raw = stream.read(HG2_HEADER.size)
    if len(raw) != HG2_HEADER.size:
        raise ValueError("HG2 header is truncated")
    header = HG2Header(*HG2_HEADER.unpack(raw))
    _validate_header(header)
    return header


def read_hg2(path: os.PathLike | str) -> tuple[HG2Header, np.ndarray]:
    with open(path, "rb") as stream:
        raw_header = stream.read(HG2_HEADER.size)
        if len(raw_header) != HG2_HEADER.size:
            raise ValueError("HG2 header is truncated")
        header = HG2Header(*HG2_HEADER.unpack(raw_header))
        _validate_header(header)
        payload = stream.read()

    expected_bytes = header.sample_count * 2
    if len(payload) != expected_bytes:
        raise ValueError(
            f"HG2 payload size mismatch: expected {expected_bytes} bytes, found {len(payload)}"
        )

    raw = np.frombuffer(payload, dtype="<u2") & HG2_STORAGE_MASK
    full = np.empty(header.shape, dtype=np.uint16)
    cursor = 0
    zone_size = header.zone_size
    zone_samples = zone_size * zone_size
    for zone_z in range(header.zones_z):
        for zone_x in range(header.zones_x):
            zone = raw[cursor : cursor + zone_samples].reshape((zone_size, zone_size))
            z0 = zone_z * zone_size
            x0 = zone_x * zone_size
            full[z0 : z0 + zone_size, x0 : x0 + zone_size] = zone
            cursor += zone_samples

    return header, full


def write_hg2(
    path: os.PathLike | str,
    heights: np.ndarray,
    zones_x: int,
    zones_z: int,
    zone_bits: int = DEFAULT_ZONE_BITS,
    structure_version: int = HG2_STRUCTURE_VERSION,
    map_version: int = HG2_MAP_VERSION,
) -> None:
    header = HG2Header(structure_version, zone_bits, zones_x, zones_z, map_version)
    _validate_header(header)

    array = np.asarray(heights)
    if array.shape != header.shape:
        raise ValueError(f"Height shape {array.shape} does not match HG2 dimensions {header.shape}")
    if array.size and (np.min(array) < 0 or np.max(array) > HG2_STORAGE_MAX_HEIGHT):
        raise ValueError(f"HG2 samples must be in the range 0..{HG2_STORAGE_MAX_HEIGHT}")

    encoded = np.rint(array).astype("<u2") & HG2_STORAGE_MASK
    zone_size = header.zone_size
    with open(path, "wb") as stream:
        stream.write(
            HG2_HEADER.pack(
                header.structure_version,
                header.zone_bits,
                header.zones_x,
                header.zones_z,
                header.map_version,
            )
        )
        for zone_z in range(header.zones_z):
            for zone_x in range(header.zones_x):
                z0 = zone_z * zone_size
                x0 = zone_x * zone_size
                zone = encoded[z0 : z0 + zone_size, x0 : x0 + zone_size]
                stream.write(zone.astype("<u2", copy=False).tobytes(order="C"))


def hg2_to_png16_array(heights: np.ndarray) -> np.ndarray:
    array = np.asarray(heights)
    if array.size and (np.min(array) < 0 or np.max(array) > HG2_STORAGE_MAX_HEIGHT):
        raise ValueError(f"HG2 samples must be in the range 0..{HG2_STORAGE_MAX_HEIGHT}")
    return (array.astype(np.uint32) * 8).astype(np.uint16)


def png16_to_hg2_array(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=np.uint32)
    return np.clip(array // 8, 0, HG2_STORAGE_MAX_HEIGHT).astype(np.uint16)
