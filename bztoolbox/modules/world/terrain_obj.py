from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Mapping

import numpy as np

from bztoolbox.modules.world.hg2_codec import DEFAULT_ZONE_BITS, HG2_STORAGE_MAX_HEIGHT, read_hg2

METERS_PER_ZONE = 1280.0
HEIGHT_UNITS_PER_METER = 10.0
OBJ_METADATA_PREFIX = "# bzr_"
OBJ_METADATA_VERSION = 1


@dataclass(frozen=True)
class TerrainOBJ:
    path: str
    heights: np.ndarray
    samples_x: int
    samples_z: int
    zones_x: int | None
    zones_z: int | None
    zone_bits: int | None
    spacing: float | None
    used_metadata: bool

    @property
    def shape(self) -> tuple[int, int]:
        return self.samples_z, self.samples_x


def sample_spacing(zone_bits: int) -> float:
    if not 1 <= int(zone_bits) <= 12:
        raise ValueError(f"Invalid HG2 zone_bits value: {zone_bits}")
    return METERS_PER_ZONE / float(1 << int(zone_bits))


def _format_float(value: float) -> str:
    text = f"{value:.6f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _write_batch(stream, lines: list[str]) -> None:
    if lines:
        stream.write("".join(lines))
        lines.clear()


def write_heightfield_obj(
    path: os.PathLike | str,
    heights: np.ndarray,
    *,
    zones_x: int,
    zones_z: int,
    zone_bits: int = DEFAULT_ZONE_BITS,
) -> None:
    """Write an HG2-compatible heightfield as a regular Wavefront OBJ grid.

    The OBJ is centered around the origin for convenient editing. Sample zero is
    placed at the minimum X / maximum Z edge of the full HG2 world extent, and
    each subsequent sample advances by the HG2 sample spacing. That mirrors the
    game's Width = samples_x * spacing convention rather than centering the
    sample *centers* half a cell inward.
    """
    array = np.asarray(heights)
    zone_size = 1 << int(zone_bits)
    expected_shape = (int(zones_z) * zone_size, int(zones_x) * zone_size)
    if array.shape != expected_shape:
        raise ValueError(f"Height shape {array.shape} does not match HG2 dimensions {expected_shape}")
    if array.size and (np.min(array) < 0 or np.max(array) > HG2_STORAGE_MAX_HEIGHT):
        raise ValueError(f"HG2 samples must be in the range 0..{HG2_STORAGE_MAX_HEIGHT}")

    samples_z, samples_x = array.shape
    spacing = sample_spacing(zone_bits)
    world_width = samples_x * spacing
    world_depth = samples_z * spacing
    x0 = -world_width / 2.0
    z0 = world_depth / 2.0

    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Battlezone 98 Redux WorldBuilder terrain mesh\n")
        stream.write("# Edit vertex Y (height). Keep the X/Z grid intact for safe re-import.\n")
        stream.write(f"# bzr_version={OBJ_METADATA_VERSION}\n")
        stream.write("# bzr_format=HG2\n")
        stream.write(f"# bzr_zones_x={int(zones_x)}\n")
        stream.write(f"# bzr_zones_z={int(zones_z)}\n")
        stream.write(f"# bzr_zone_bits={int(zone_bits)}\n")
        stream.write(f"# bzr_samples_x={samples_x}\n")
        stream.write(f"# bzr_samples_z={samples_z}\n")
        stream.write(f"# bzr_spacing={_format_float(spacing)}\n")
        stream.write(f"# bzr_height_units_per_meter={_format_float(HEIGHT_UNITS_PER_METER)}\n")
        stream.write("o BZR_Terrain\n")

        batch: list[str] = []
        for row in range(samples_z):
            z = z0 - row * spacing
            row_heights = array[row]
            for col in range(samples_x):
                x = x0 + col * spacing
                y = float(row_heights[col]) / HEIGHT_UNITS_PER_METER
                batch.append(f"v {_format_float(x)} {_format_float(y)} {_format_float(z)}\n")
                if len(batch) >= 4096:
                    _write_batch(stream, batch)
        _write_batch(stream, batch)

        # Quads keep heightfield OBJ files substantially smaller than two triangles per cell.
        # Winding produces +Y-facing normals on an unmodified heightfield.
        for row in range(samples_z - 1):
            base = row * samples_x + 1
            next_base = (row + 1) * samples_x + 1
            for col in range(samples_x - 1):
                a = base + col
                b = a + 1
                d = next_base + col
                c = d + 1
                batch.append(f"f {a} {b} {c} {d}\n")
                if len(batch) >= 4096:
                    _write_batch(stream, batch)
        _write_batch(stream, batch)


def export_hg2_to_obj(hg2_path: os.PathLike | str, obj_path: os.PathLike | str) -> None:
    header, heights = read_hg2(hg2_path)
    write_heightfield_obj(
        obj_path,
        heights,
        zones_x=header.zones_x,
        zones_z=header.zones_z,
        zone_bits=header.zone_bits,
    )


def _parse_metadata_line(line: str, metadata: dict[str, str]) -> None:
    stripped = line.strip()
    if not stripped.startswith(OBJ_METADATA_PREFIX):
        return
    payload = stripped[len(OBJ_METADATA_PREFIX):]
    if "=" not in payload:
        return
    key, value = payload.split("=", 1)
    metadata[key.strip().lower()] = value.strip()


def _int_meta(metadata: Mapping[str, str], key: str) -> int | None:
    value = metadata.get(key)
    if value is None:
        return None
    try:
        return int(value, 0)
    except ValueError as exc:
        raise ValueError(f"Invalid OBJ metadata {key}={value!r}") from exc


def _float_meta(metadata: Mapping[str, str], key: str) -> float | None:
    value = metadata.get(key)
    if value is None:
        return None
    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid OBJ metadata {key}={value!r}") from exc
    if not math.isfinite(result):
        raise ValueError(f"Invalid OBJ metadata {key}={value!r}")
    return result


def _validate_metadata(metadata: Mapping[str, str]) -> None:
    if not metadata:
        return

    version = _int_meta(metadata, "version")
    if version is not None and version != OBJ_METADATA_VERSION:
        raise ValueError(
            f"Unsupported WorldBuilder terrain OBJ metadata version {version}; "
            f"expected {OBJ_METADATA_VERSION}"
        )

    fmt = metadata.get("format")
    if fmt is not None and fmt.strip().upper() != "HG2":
        raise ValueError(f"Unsupported WorldBuilder terrain OBJ format {fmt!r}; expected 'HG2'")

    height_units = _float_meta(metadata, "height_units_per_meter")
    if height_units is not None:
        tolerance = max(1e-8, HEIGHT_UNITS_PER_METER * 1e-6)
        if abs(height_units - HEIGHT_UNITS_PER_METER) > tolerance:
            raise ValueError(
                f"OBJ height scale is {height_units:g} units/m; "
                f"WorldBuilder HG2 expects {HEIGHT_UNITS_PER_METER:g} units/m"
            )


def _regular_axis(values: np.ndarray, *, descending: bool = False) -> tuple[np.ndarray, float | None]:
    # Round only for coordinate bucketing; WorldBuilder exports at <= 6 decimal places.
    unique = np.unique(np.round(values.astype(np.float64), 6))
    if descending:
        unique = unique[::-1]
    if len(unique) <= 1:
        return unique, None
    diffs = np.abs(np.diff(unique))
    spacing = float(np.median(diffs))
    tolerance = max(1e-5, spacing * 1e-4)
    if spacing <= 0 or np.max(np.abs(diffs - spacing)) > tolerance:
        raise ValueError("OBJ X/Z coordinates do not form a regular terrain grid")
    return unique, spacing


def _grid_from_vertices(
    vertices: np.ndarray,
    *,
    samples_x: int | None,
    samples_z: int | None,
    spacing: float | None,
) -> tuple[np.ndarray, int, int, float]:
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) == 0:
        raise ValueError("OBJ contains no usable vertex positions")

    xs = vertices[:, 0]
    zs = vertices[:, 2]
    x_axis, x_spacing = _regular_axis(xs, descending=False)
    z_axis, z_spacing = _regular_axis(zs, descending=True)

    inferred_x = len(x_axis)
    inferred_z = len(z_axis)
    if inferred_x * inferred_z != len(vertices):
        raise ValueError(
            f"OBJ vertices are not a complete rectangular grid: "
            f"{len(vertices)} vertices vs {inferred_x}x{inferred_z}"
        )
    if samples_x is not None and samples_x != inferred_x:
        raise ValueError(f"OBJ metadata expects {samples_x} X samples; file contains {inferred_x}")
    if samples_z is not None and samples_z != inferred_z:
        raise ValueError(f"OBJ metadata expects {samples_z} Z samples; file contains {inferred_z}")

    candidates = [value for value in (spacing, x_spacing, z_spacing) if value is not None]
    resolved_spacing = float(candidates[0]) if candidates else 0.0
    for value in candidates[1:]:
        tolerance = max(1e-5, max(abs(resolved_spacing), abs(value)) * 1e-4)
        if abs(value - resolved_spacing) > tolerance:
            raise ValueError(
                f"OBJ grid spacing mismatch: expected {resolved_spacing:g}, found {value:g}"
            )

    x_lookup = {float(value): index for index, value in enumerate(x_axis)}
    z_lookup = {float(value): index for index, value in enumerate(z_axis)}
    heights = np.empty((inferred_z, inferred_x), dtype=np.uint16)
    seen = np.zeros((inferred_z, inferred_x), dtype=np.bool_)

    for x, y, z in vertices:
        key_x = float(round(float(x), 6))
        key_z = float(round(float(z), 6))
        col = x_lookup.get(key_x)
        row = z_lookup.get(key_z)
        if col is None or row is None:
            raise ValueError("OBJ contains a vertex outside the regular X/Z terrain grid")
        if seen[row, col]:
            raise ValueError(f"OBJ contains duplicate terrain vertex at X={x:g}, Z={z:g}")
        raw_height = int(round(float(y) * HEIGHT_UNITS_PER_METER))
        if raw_height < 0 or raw_height > HG2_STORAGE_MAX_HEIGHT:
            raise ValueError(
                f"OBJ height {y:g} m maps to HG2 value {raw_height}, "
                f"outside 0..{HG2_STORAGE_MAX_HEIGHT}"
            )
        heights[row, col] = raw_height
        seen[row, col] = True

    if not np.all(seen):
        raise ValueError("OBJ terrain grid has missing X/Z samples")
    return heights, inferred_x, inferred_z, resolved_spacing


def read_terrain_obj(path: os.PathLike | str) -> TerrainOBJ:
    metadata: dict[str, str] = {}
    vertices: list[tuple[float, float, float]] = []

    with open(path, "r", encoding="utf-8", errors="replace") as stream:
        for line_number, raw in enumerate(stream, 1):
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                _parse_metadata_line(line, metadata)
                continue
            parts = line.split()
            if not parts or parts[0] != "v":
                continue
            if len(parts) < 4:
                raise ValueError(f"Malformed OBJ vertex on line {line_number}")
            try:
                xyz = tuple(float(part) for part in parts[1:4])
            except ValueError as exc:
                raise ValueError(f"Malformed OBJ vertex on line {line_number}") from exc
            if not all(math.isfinite(value) for value in xyz):
                raise ValueError(f"Non-finite OBJ vertex on line {line_number}")
            vertices.append(xyz)

    if not vertices:
        raise ValueError("OBJ contains no vertex records")

    _validate_metadata(metadata)
    samples_x = _int_meta(metadata, "samples_x")
    samples_z = _int_meta(metadata, "samples_z")
    zones_x = _int_meta(metadata, "zones_x")
    zones_z = _int_meta(metadata, "zones_z")
    zone_bits = _int_meta(metadata, "zone_bits")
    spacing = _float_meta(metadata, "spacing")

    if samples_x is not None and samples_x <= 0:
        raise ValueError("OBJ metadata samples_x must be positive")
    if samples_z is not None and samples_z <= 0:
        raise ValueError("OBJ metadata samples_z must be positive")
    if zones_x is not None and zones_x <= 0:
        raise ValueError("OBJ metadata zones_x must be positive")
    if zones_z is not None and zones_z <= 0:
        raise ValueError("OBJ metadata zones_z must be positive")
    if spacing is not None and spacing <= 0:
        raise ValueError("OBJ metadata spacing must be positive")

    heights, inferred_x, inferred_z, inferred_spacing = _grid_from_vertices(
        np.asarray(vertices, dtype=np.float64),
        samples_x=samples_x,
        samples_z=samples_z,
        spacing=spacing,
    )

    if zone_bits is not None:
        expected_spacing = sample_spacing(zone_bits)
        tolerance = max(1e-5, expected_spacing * 1e-4)
        if inferred_spacing and abs(inferred_spacing - expected_spacing) > tolerance:
            raise ValueError(
                f"OBJ zone_bits={zone_bits} implies {expected_spacing:g} m spacing, "
                f"but grid uses {inferred_spacing:g} m"
            )

    if zone_bits is not None and zones_x is not None and zones_z is not None:
        zone_size = 1 << zone_bits
        expected_shape = (zones_z * zone_size, zones_x * zone_size)
        if heights.shape != expected_shape:
            raise ValueError(
                f"OBJ metadata describes HG2 shape {expected_shape}, "
                f"but grid is {heights.shape}"
            )

    return TerrainOBJ(
        path=os.path.abspath(os.fspath(path)),
        heights=heights,
        samples_x=inferred_x,
        samples_z=inferred_z,
        zones_x=zones_x,
        zones_z=zones_z,
        zone_bits=zone_bits,
        spacing=inferred_spacing or spacing,
        used_metadata=bool(metadata),
    )


def _validate_resolved_spacing(mesh: TerrainOBJ, zone_bits: int) -> None:
    if not mesh.spacing:
        return
    expected = sample_spacing(zone_bits)
    tolerance = max(1e-5, expected * 1e-4)
    if abs(mesh.spacing - expected) > tolerance:
        raise ValueError(
            f"OBJ grid uses {mesh.spacing:g} m/sample, but HG2 zone_bits={zone_bits} "
            f"requires {expected:g} m/sample. Scale the OBJ X/Z grid or start from an "
            "HG2 exported by WorldBuilder."
        )


def resolve_hg2_geometry(
    mesh: TerrainOBJ,
    *,
    preferred_zones_x: int | None = None,
    preferred_zones_z: int | None = None,
) -> tuple[int, int, int]:
    if mesh.zone_bits is not None and mesh.zones_x is not None and mesh.zones_z is not None:
        _validate_resolved_spacing(mesh, mesh.zone_bits)
        return mesh.zones_x, mesh.zones_z, mesh.zone_bits

    zone_bits = DEFAULT_ZONE_BITS
    zone_size = 1 << zone_bits

    if preferred_zones_x and preferred_zones_z:
        expected = (int(preferred_zones_z) * zone_size, int(preferred_zones_x) * zone_size)
        if mesh.heights.shape == expected:
            _validate_resolved_spacing(mesh, zone_bits)
            return int(preferred_zones_x), int(preferred_zones_z), zone_bits

    if mesh.samples_x % zone_size == 0 and mesh.samples_z % zone_size == 0:
        _validate_resolved_spacing(mesh, zone_bits)
        return mesh.samples_x // zone_size, mesh.samples_z // zone_size, zone_bits

    raise ValueError(
        "OBJ has no WorldBuilder HG2 metadata and its grid is not an exact "
        "256-samples-per-zone Redux HG2 size. Export an HG2 to OBJ first, or set "
        "matching target zone dimensions before converting."
    )
