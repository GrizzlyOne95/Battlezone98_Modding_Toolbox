"""LGT terrain light maps.

One unsigned byte per light cell, zone by zone (row-major zones, each zone
row-major, south-west origin). 0 is ambient only (25% brightness), 255 full.

* Redux: ``(zones + 1) * zone_size**2`` bytes, where the first block is a
  border chunk filled with one value; 256 cells per zone side (5 m).
* Classic/legacy: no border, 128 cells per zone side (10 m).

Arrays are south-first (row 0 = south), the same orientation as
:class:`battlezone.terrain.hg2.HG2Map` heights. :func:`lgt_to_image` and
:func:`image_to_lgt` convert to and from north-up images.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from battlezone.terrain.hg2 import read_hg2_header

# LGT ambient floor: 0 in file = 25% brightness, 255 = 100%.
LGT_AMBIENT_FRACTION = 0.25
LGT_RANGE_FRACTION = 0.75
LGT_ZONE_SIZES = (128, 256)


def lgt_to_brightness(lgt: np.ndarray, ambient: float = LGT_AMBIENT_FRACTION) -> np.ndarray:
    """Convert LGT 0..255 values to linear brightness 0.25..1.0."""
    a = np.asarray(lgt, dtype=np.float32) / 255.0
    return ambient + (1.0 - ambient) * a


def write_lgt(path: str | Path, lightmap: np.ndarray, zones_x: int, zones_z: int,
              border: int | None = None) -> None:
    """Write a Redux-style LGT file (border chunk + zoned blocks).

    This replicates the layout observed on disk and written by Z64Tools
    terrain_pack.py: first zone_size*zone_size bytes are a border chunk,
    followed by row-major zone blocks starting at the southwest corner.
    Z64Tools flips a north-at-top PNG first; this API already accepts a
    south-first array and therefore writes it without another flip.

    Parameters
    ----------
    path:
        Output .lgt path.
    lightmap:
        2-D uint8 array shape ``(zones_z*zone_size, zones_x*zone_size)``,
        row 0 = south, same orientation as HG2Map.heights.
    zones_x, zones_z:
        Zone counts, must match lightmap shape.
    border:
        Fill value of the leading border chunk. Defaults to the south-west
        (file origin) sample; BzrLgt-compatible packers pass the north-west
        sample (the top-left pixel of a north-up image).
    """
    lm = np.asarray(lightmap, dtype=np.uint8)
    if lm.ndim != 2:
        raise ValueError("lightmap must be 2-D")
    zones_x, zones_z = int(zones_x), int(zones_z)
    if zones_x <= 0 or zones_z <= 0:
        raise ValueError("zone counts must be positive")
    h, w = lm.shape
    if h % zones_z != 0 or w % zones_x != 0:
        raise ValueError("lightmap shape not divisible by zones")
    zone_size_x = w // zones_x
    zone_size_z = h // zones_z
    if zone_size_x != zone_size_z:
        raise ValueError("non-square LGT zones not supported")
    zone_size = int(zone_size_x)
    if zone_size not in (128, 256):
        raise ValueError("LGT zone size must be 128 or 256")
    if lm.shape != (zones_z * zone_size, zones_x * zone_size):
        raise ValueError("lightmap shape mismatch")

    border = int(lm[0, 0]) if border is None else int(border)
    out = bytearray(bytes([border]) * (zone_size * zone_size))
    for zy in range(zones_z):
        for zx in range(zones_x):
            zone = lm[zy * zone_size : (zy + 1) * zone_size, zx * zone_size : (zx + 1) * zone_size]
            out.extend(zone.tobytes())
    Path(path).write_bytes(out)


def _companion_hg2_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        for candidate in path.parent.iterdir():
            if candidate.is_file() and candidate.stem.casefold() == path.stem.casefold() and candidate.suffix.casefold() == ".hg2":
                header = read_hg2_header(candidate)
                return header.zones_x, header.zones_z
    except (OSError, ValueError):
        return None
    return None


def read_lgt(
    path: str | Path,
    zones_x: int | None = None,
    zones_z: int | None = None,
    *,
    zone_size: int | None = None,
) -> tuple[np.ndarray, int, int, int]:
    """Read an LGT file, returning (lightmap, zones_x, zones_z, zone_size).

    Handles bordered Redux and unbordered legacy layouts. Zone dimensions are
    taken from explicit arguments or a same-stem companion HG2. File size
    alone cannot distinguish 1x4, 2x2, and 4x1 maps, so ambiguous standalone
    files raise instead of silently choosing the wrong layout. Returns a
    south-first lightmap matching ``HG2Map.heights``.
    """
    data = Path(path).read_bytes()
    n = len(data)
    arr = np.frombuffer(data, dtype=np.uint8)
    lgt_path = Path(path)
    if (zones_x is None) != (zones_z is None):
        raise ValueError("zones_x and zones_z must be provided together")
    if zones_x is None:
        companion = _companion_hg2_dimensions(lgt_path)
        if companion is not None:
            zones_x, zones_z = companion

    candidate_zone_sizes = (int(zone_size),) if zone_size is not None else (256, 128)
    if any(size not in (128, 256) for size in candidate_zone_sizes):
        raise ValueError("LGT zone size must be 128 or 256")
    candidates: list[tuple[int, int, int, bool]] = []
    x_values = (int(zones_x),) if zones_x is not None else range(1, 9)
    z_values = (int(zones_z),) if zones_z is not None else range(1, 9)
    for zs in candidate_zone_sizes:
        for zx in x_values:
            for zz in z_values:
                if n == zx * zz * zs * zs:
                    candidates.append((zx, zz, zs, False))
                if n == (zx * zz + 1) * zs * zs:
                    candidates.append((zx, zz, zs, True))
    if not candidates:
        raise ValueError(f"LGT size {n} does not match the requested or inferred dimensions")
    best_rank = max((candidate[3], candidate[2]) for candidate in candidates)
    finalists = [candidate for candidate in candidates if (candidate[3], candidate[2]) == best_rank]
    if len(finalists) != 1:
        possibilities = ", ".join(f"{zx}x{zz}@{zs}" for zx, zz, zs, _ in finalists)
        raise ValueError(f"Ambiguous LGT dimensions ({possibilities}); provide zones_x and zones_z")
    zones_x, zones_z, zone_size, has_border = finalists[0]
    if has_border:
        content = arr[zone_size * zone_size :]
    else:
        content = arr
    lightmap = np.empty((zones_z * zone_size, zones_x * zone_size), dtype=np.uint8)
    idx = 0
    for zy in range(zones_z):
        for zx in range(zones_x):
            block = content[idx : idx + zone_size * zone_size]
            idx += zone_size * zone_size
            lightmap[zy * zone_size : (zy + 1) * zone_size, zx * zone_size : (zx + 1) * zone_size] = block.reshape(
                zone_size, zone_size
            )
    return lightmap, zones_x, zones_z, zone_size


def lgt_to_image(lightmap: np.ndarray) -> np.ndarray:
    """South-first light map -> north-up image rows."""
    return np.flipud(np.asarray(lightmap, dtype=np.uint8))


def image_to_lgt(image: np.ndarray) -> np.ndarray:
    """North-up image rows -> south-first light map."""
    return np.flipud(np.asarray(image, dtype=np.uint8))
