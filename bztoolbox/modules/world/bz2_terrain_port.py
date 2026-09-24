"""First stage of an authored BZ2/BZCC-to-Redux terrain port.

Preserves the TER channels for the subsequent texture-atlas/MAT stage and
exports a world-scale HG2. It intentionally does not claim mission launchability.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from bztoolbox.modules.world.bz2_ter_codec import SourceTerrain, read_ter
from bztoolbox.modules.world.bz2_mat_encoder import encode_bz2_mat
from bztoolbox.modules.world.bz2_mat_reducer import reduce_bz2_mat_cells
from bztoolbox.modules.world.bz2_texture_resolver import build_texture_slot_manifest
from bztoolbox.modules.world.hg2_codec import write_hg2
from bztoolbox.modules.world.mat_codec import write_mat

ZONE_M = 1280
HG2_STEP_M = 5
SAFE_MAX_DM = 4095


@dataclass(frozen=True)
class PortGeometry:
    min_x: int
    min_z: int
    width_m: int
    depth_m: int
    zones_x: int
    zones_z: int
    source_min_x: int
    source_min_z: int
    source_width_m: int
    source_depth_m: int
    vertical_offset_m: float

    @property
    def source_target_min_x(self) -> int:
        """Authored source X origin after placing the padded terrain in the target world."""
        natural_min_x = (self.source_min_x // ZONE_M) * ZONE_M
        return self.min_x + (self.source_min_x - natural_min_x)

    @property
    def object_offset_m(self) -> tuple[int, float, int]:
        """Add to source BZN positions/paths to land on this terrain (x, y, z)."""
        return (self.source_target_min_x - self.source_min_x, self.vertical_offset_m,
                self.source_target_min_z - self.source_min_z)

    @property
    def source_target_min_z(self) -> int:
        """Authored source Z origin after placing the padded terrain in the target world."""
        natural_min_z = (self.source_min_z // ZONE_M) * ZONE_M
        return self.min_z + (self.source_min_z - natural_min_z)


def geometry_for(source: SourceTerrain, *, target_min_x: int | None = None,
                 target_min_z: int | None = None) -> PortGeometry:
    step = source.spacing_m
    x0, z0 = source.grid_min_x * step, source.grid_min_z * step
    x1, z1 = source.grid_max_x * step, source.grid_max_z * step
    natural_min_x, natural_min_z = (x0 // ZONE_M) * ZONE_M, (z0 // ZONE_M) * ZONE_M
    natural_max_x, natural_max_z = math.ceil(x1 / ZONE_M) * ZONE_M, math.ceil(z1 / ZONE_M) * ZONE_M
    min_x = natural_min_x if target_min_x is None else int(target_min_x)
    min_z = natural_min_z if target_min_z is None else int(target_min_z)
    width, depth = natural_max_x - natural_min_x, natural_max_z - natural_min_z
    if (width // HG2_STEP_M) * (depth // HG2_STEP_M) > 32_000_000:
        raise ValueError("Padded HG2 exceeds the safe 32-million-sample limit")
    low, high = float(source.heights_m.min()), float(source.heights_m.max())
    # Offset only as much as needed; no rescaling or normalization.
    offset_dm = max(0, math.ceil(-low * 10 - 1e-6))
    if math.ceil((high * 10) + offset_dm - 1e-6) > SAFE_MAX_DM:
        raise ValueError(f"Source elevation span {high-low:.2f} m cannot fit the 0..409.5 m safe Redux range")
    return PortGeometry(min_x, min_z, width, depth, width // ZONE_M, depth // ZONE_M,
                        x0, z0, x1 - x0, z1 - z0, offset_dm / 10)


def resample_hg2(source: SourceTerrain, geometry: PortGeometry) -> np.ndarray:
    """Bilinear height interpolation in meters; clamp outside authored bounds."""
    src = source.heights_m
    step = source.spacing_m
    # Preserve the source's authored offset inside its padded Redux zone.  A
    # target-origin override moves the whole padded terrain, not the source
    # raster independently of that padding.
    xx = (geometry.min_x + np.arange(geometry.width_m // HG2_STEP_M) * HG2_STEP_M
          - geometry.source_target_min_x) / step
    zz = (geometry.min_z + np.arange(geometry.depth_m // HG2_STEP_M) * HG2_STEP_M
          - geometry.source_target_min_z) / step
    xx = np.clip(xx, 0, src.shape[1] - 1)
    zz = np.clip(zz, 0, src.shape[0] - 1)
    xlo = np.floor(xx).astype(np.intp)
    zlo = np.floor(zz).astype(np.intp)
    xhi = np.minimum(xlo + 1, src.shape[1] - 1)
    zhi = np.minimum(zlo + 1, src.shape[0] - 1)
    tx, tz = (xx - xlo).astype(np.float32), (zz - zlo).astype(np.float32)
    output = np.empty((len(zz), len(xx)), dtype=np.uint16)
    # Row-wise computation avoids allocating multiple full-size float rasters.
    for row in range(len(zz)):
        a = src[zlo[row], xlo] * (1 - tx) + src[zlo[row], xhi] * tx
        b = src[zhi[row], xlo] * (1 - tx) + src[zhi[row], xhi] * tx
        values = (a * (1 - tz[row]) + b * tz[row] + geometry.vertical_offset_m) * 10
        output[row] = np.floor(values + 0.5).astype(np.uint16)
    return output


def convert_ter_height(ter_path: str | Path, output_dir: str | Path, name: str,
                       *, target_min_x: int | None = None,
                       target_min_z: int | None = None,
                       write_diagnostic_mat: bool = True) -> dict:
    """Write HG2, lossless decoded-channel archive, previews, and provenance.

    Existing output files are never replaced; use a fresh output directory/name.
    """
    if not name or len(name) > 8 or not name.isascii() or not name.isalnum():
        raise ValueError("Redux terrain name must be 1–8 ASCII letters/digits")
    source = read_ter(ter_path)
    geo = geometry_for(source, target_min_x=target_min_x, target_min_z=target_min_z)
    heights = resample_hg2(source, geo)
    output_dir = Path(output_dir)
    names = [f"{name}.hg2", f"{name}_ter_channels.npz", f"{name}_port.json",
             f"{name}_height.png", f"{name}_cells.png", f"{name}_source_manifest.json",
             f"{name}_mat_reduction.npz", f"{name}_reduced.MAT"]
    output_names = names if write_diagnostic_mat else names[:-1]
    if any((output_dir / filename).exists() for filename in output_names):
        raise FileExistsError("One or more port outputs already exist; choose an empty destination/name")
    output_dir.mkdir(parents=True, exist_ok=True)
    write_hg2(output_dir / names[0], heights, geo.zones_x, geo.zones_z)
    np.savez_compressed(output_dir / names[1], heights_m=source.heights_m,
                        colors=source.colors, alphas=source.alphas,
                        cells=source.cells, info=source.info,
                        texture_indices=source.texture_indices,
                        visibility_mask=source.visibility_mask,
                        owner_team=source.owner_team,
                        build_type=source.build_type)
    preview = Image.fromarray(np.clip(heights.astype(np.uint32) * 16, 0, 65535).astype(np.uint16))
    preview.thumbnail((2048, 2048))
    preview.save(output_dir / names[3])
    flags = Image.fromarray(source.cells)
    flags.thumbnail((2048, 2048), Image.Resampling.NEAREST)
    flags.save(output_dir / names[4])
    texture_manifest = build_texture_slot_manifest(source)
    (output_dir / names[5]).write_text(json.dumps(texture_manifest, indent=2) + "\n", encoding="utf-8")
    mat_reduction = reduce_bz2_mat_cells(source, geo)
    np.savez_compressed(
        output_dir / names[6],
        weights=mat_reduction.weights,
        primary_material=mat_reduction.primary_material,
        secondary_material=mat_reduction.secondary_material,
        secondary_weight=mat_reduction.secondary_weight,
        sample_counts=mat_reduction.sample_counts,
        corner_materials=mat_reduction.corner_materials,
    )
    encoded_mat = encode_bz2_mat(mat_reduction)
    if write_diagnostic_mat:
        write_mat(output_dir / names[7], encoded_mat.entries, geo.zones_x, geo.zones_z)
    report = {
        "status": "height_and_source_channels_only_not_a_launchable_map",
        "source_ter": str(Path(ter_path).resolve()),
        "source_version": source.version,
        "source_spacing_m": source.spacing_m,
        "source_grid_bounds": [source.grid_min_x, source.grid_min_z,
                               source.grid_max_x, source.grid_max_z],
        "source_world_bounds_m": [geo.source_min_x, geo.source_min_z,
                                  geo.source_min_x + geo.source_width_m,
                                  geo.source_min_z + geo.source_depth_m],
        "redux_world_bounds_m": [geo.min_x, geo.min_z,
                                 geo.min_x + geo.width_m, geo.min_z + geo.depth_m],
        "redux_source_world_bounds_m": [geo.source_target_min_x, geo.source_target_min_z,
                                        geo.source_target_min_x + geo.source_width_m,
                                        geo.source_target_min_z + geo.source_depth_m],
        "target_origin_override_m": ([geo.min_x, geo.min_z]
                                      if target_min_x is not None or target_min_z is not None
                                      else None),
        "redux_zones": [geo.zones_x, geo.zones_z],
        "vertical_offset_m": geo.vertical_offset_m,
        "object_offset_m": list(geo.object_offset_m),
        "source_elevation_range_m": [float(source.heights_m.min()), float(source.heights_m.max())],
        "redux_elevation_range_m": [float(heights.min()) / 10, float(heights.max()) / 10],
        "declared_texture_indices": sorted(int(i) for i in np.unique(source.texture_indices)),
        "used_texture_slots": sorted(int(i) for i in np.unique(source.texture_indices)),
        "texture_manifest": names[5],
        "unresolved_texture_slots": texture_manifest["unresolved_used_slots"],
        "mat_reduction": {
            "path": names[6],
            "cell_size_m": 20,
            "shape": [int(mat_reduction.primary_material.shape[1]),
                      int(mat_reduction.primary_material.shape[0])],
            "material_slots": sorted(
                int(slot) for slot in np.unique(
                    np.concatenate((mat_reduction.primary_material.ravel(),
                                    mat_reduction.secondary_material.ravel()))
                )
            ),
            "algorithm": "mean source-sample coverage using sequential BZ2 layer weights",
            "encoded_mat": names[7] if write_diagnostic_mat else None,
            "transition_encoding": "source-corner cap/diagonal encoding; unsupported cells collapse to the strongest integrated material",
            "cap_pairs": [list(pair) for pair in sorted(encoded_mat.cap_pairs)],
            "diagonal_pairs": [list(pair) for pair in sorted(encoded_mat.diagonal_pairs)],
            "solid_cells": encoded_mat.solid_cells,
            "cap_cells": encoded_mat.cap_cells,
            "diagonal_cells": encoded_mat.diagonal_cells,
            "ambiguous_cells": encoded_mat.ambiguous_cells,
        },
        "cluster_info": {
            "visibility_masks": sorted(int(i) for i in np.unique(source.visibility_mask)),
            "owner_teams": sorted(int(i) for i in np.unique(source.owner_team)),
            "build_types": sorted(int(i) for i in np.unique(source.build_type)),
        },
        "orientation": "raw TER row order preserved; compass orientation requires in-game verification",
        "height_resampling": "bilinear at 5-meter world coordinates, edge-clamped in padded zones",
        "texture_blend_model": "sequential: layer0 base, then lerp layers 1, 2, 3 by AlphaMap1..3 / 255",
        "texture_blend_source": "original BZ2 bz2edit decompile: MapCluster::GetAlpha, MapRadar::FillTerrainMap, TerrainClass::ComputeLayer",
        "next_stage": "Emit only the encoded MAT's required cap/diagonal atlas transitions and resolved TRN",
    }
    (output_dir / names[2]).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
