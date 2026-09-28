"""LGT terrain light maps.

One unsigned byte per light cell, zone by zone (row-major zones, each zone
row-major, south-west origin). 0 is ambient only (25% brightness), 255 full.

* Redux: ``(zones + 1) * zone_size**2`` bytes, where the first block is a
  border chunk filled with one value; 256 cells per zone side (5 m).
* Battlezone 1.5: 128 cells per zone side (10 m), also after a border chunk
  (stock misn05.lgt is (9 + 1) * 128**2 bytes). Older files may lack the border.

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


# --- Redux's own bake -------------------------------------------------------------
# Fitted to the stock LGT/HG2 pairs in bzone.zfs (misn02/05/10, misns1/4/7): a sun due
# east 80 degrees up, Lambert shading with no cast shadows, and
# value = clip(360 * lambert - 106, 56, 255); the border block holds 56. It reproduces
# the stock files to within 3-6 levels on average, which is why they never go below 56.
REDUX_SUN_AZIMUTH_DEG = 90.0
REDUX_SUN_ALTITUDE_DEG = 80.0
REDUX_LGT_SCALE = 360.0
REDUX_LGT_OFFSET = -106.0
REDUX_LGT_FLOOR = 56
_ZONE_WORLD_SIZE = 1280.0
_HEIGHT_UNIT = 0.1


def lambert_shading(heights: np.ndarray, zones_x: int, zones_z: int, cell_zone_size: int = 256,
                    azimuth_deg: float = REDUX_SUN_AZIMUTH_DEG,
                    altitude_deg: float = REDUX_SUN_ALTITUDE_DEG) -> np.ndarray:
    """0..1 Lambert shading of south-first HG2 heights, averaged to ``cell_zone_size`` cells per zone."""
    import math

    a = np.asarray(heights, dtype=np.float64) * _HEIGHT_UNIT
    h, w = a.shape
    vertex_zone = w // int(zones_x)
    if vertex_zone * int(zones_x) != w or h != vertex_zone * int(zones_z):
        raise ValueError("heights do not divide into the zone counts")
    if vertex_zone % cell_zone_size:
        raise ValueError(f"{cell_zone_size} cells per zone do not divide {vertex_zone} samples per zone")
    spacing = _ZONE_WORLD_SIZE / vertex_zone
    grad_z, grad_x = np.gradient(a, spacing, spacing)
    az, alt = math.radians(azimuth_deg), math.radians(altitude_deg)
    sun_x, sun_y, sun_z = math.cos(alt) * math.sin(az), math.sin(alt), math.cos(alt) * math.cos(az)
    shade = np.clip((-grad_x * sun_x + sun_y - grad_z * sun_z) / np.sqrt(grad_x ** 2 + grad_z ** 2 + 1.0), 0.0, 1.0)
    factor = vertex_zone // cell_zone_size
    if factor > 1:
        shade = shade.reshape(h // factor, factor, w // factor, factor).mean(axis=(1, 3))
    return shade


def bake_redux_lgt(heights: np.ndarray, zones_x: int, zones_z: int, cell_zone_size: int = 256) -> np.ndarray:
    """An LGT lit the way Redux's stock maps are (the REDUX_* constants above)."""
    shade = lambert_shading(heights, zones_x, zones_z, cell_zone_size)
    return np.clip(np.rint(REDUX_LGT_SCALE * shade + REDUX_LGT_OFFSET), REDUX_LGT_FLOOR, 255).astype(np.uint8)


def rebake_lgt_file(hg2_path, lgt_path) -> np.ndarray:
    """Write ``lgt_path`` baked from ``hg2_path``, keeping the existing file's cells per zone (default 256)."""
    from battlezone.terrain.hg2 import HG2Map

    hg2 = HG2Map.read(hg2_path)
    cells = 256
    if Path(lgt_path).is_file():
        try:
            cells = read_lgt(lgt_path, hg2.zones_x, hg2.zones_z)[3]
        except ValueError:
            pass
    baked = bake_redux_lgt(hg2.heights, hg2.zones_x, hg2.zones_z, cells)
    write_lgt(lgt_path, baked, hg2.zones_x, hg2.zones_z, border=REDUX_LGT_FLOOR)
    return baked
