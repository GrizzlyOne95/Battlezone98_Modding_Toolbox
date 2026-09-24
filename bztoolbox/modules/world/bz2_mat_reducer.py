"""Reduce authored BZ2/BZCC terrain layers to Redux MAT-cell coverage.

Redux stores one MAT entry per 20 m cell, while BZ2/BZCC stores four source
texture slots and three alpha planes at the TER sample resolution.  This
module integrates the source-proven sequential blend weights over each MAT
cell and reports the two strongest contributing Redux material slots.  It does
not encode MAT transition bits yet; keeping the coverage data separate makes
that later quantization auditable instead of silently choosing one alpha byte.
"""
from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from bztoolbox.modules.world.bz2_ter_codec import SourceTerrain
from bztoolbox.modules.world.bz2_texture_blend import sequential_layer_weights

if TYPE_CHECKING:
    from bztoolbox.modules.world.bz2_terrain_port import PortGeometry


MAT_CELL_M = 20
MATERIAL_COUNT = 16


@dataclass(frozen=True)
class MatReduction:
    """Area-integrated material coverage on the Redux MAT lattice."""

    weights: np.ndarray
    primary_material: np.ndarray
    secondary_material: np.ndarray
    secondary_weight: np.ndarray
    sample_counts: np.ndarray
    corner_materials: np.ndarray


def _window(start_m: int, end_m: int, source_min_m: int,
            spacing_m: int, sample_count: int) -> tuple[int, int]:
    """Return the source sample window intersecting one world-space interval."""
    first = int(np.floor((start_m - source_min_m) / spacing_m))
    last = int(np.ceil((end_m - source_min_m) / spacing_m))
    first = max(0, min(sample_count, first))
    last = max(0, min(sample_count, last))
    if first < last:
        return first, last

    # A padded cell can lie entirely outside the authored source.  The height
    # path edge-clamps these cells; use the nearest authored texture sample for
    # the same deterministic edge behavior rather than dropping the cell.
    center = int(round(((start_m + end_m) * 0.5 - source_min_m) / spacing_m))
    center = max(0, min(sample_count - 1, center))
    return center, center + 1


def _sample_slot_maps(source: SourceTerrain, texture_indices: np.ndarray) -> np.ndarray:
    """Expand per-cluster TER texture slots to the source sample lattice."""
    height, width = source.heights_m.shape
    cluster = 4 if source.version == 3 else 16
    sample_slots = np.empty((4, height, width), dtype=np.uint8)
    for layer in range(4):
        expanded = np.repeat(np.repeat(texture_indices[layer], cluster, axis=0),
                             cluster, axis=1)
        sample_slots[layer] = expanded[:height, :width]
    return sample_slots


def _dominant_source_materials(effective: np.ndarray,
                               sample_slots: np.ndarray) -> np.ndarray:
    """Return the strongest accumulated TER material at each source sample."""
    height, width = sample_slots.shape[1:]
    dominant = np.zeros((height, width), dtype=np.uint8)
    best = np.full((height, width), -1.0, dtype=np.float32)
    for material in range(MATERIAL_COUNT):
        total = np.zeros((height, width), dtype=np.float32)
        for layer in range(4):
            total += effective[layer] * (sample_slots[layer] == material)
        mask = total > best
        dominant[mask] = material
        best[mask] = total[mask]
    return dominant


def _corner_material_grid(source: SourceTerrain, geometry: "PortGeometry",
                          dominant: np.ndarray) -> np.ndarray:
    """Sample the four Redux MAT-cell corners from the source material field."""
    cells_z = geometry.depth_m // MAT_CELL_M
    cells_x = geometry.width_m // MAT_CELL_M
    x_world = geometry.min_x + np.arange(cells_x + 1) * MAT_CELL_M
    z_world = geometry.min_z + np.arange(cells_z + 1) * MAT_CELL_M
    x_index = np.rint(
        (x_world - geometry.source_target_min_x) / source.spacing_m
    ).astype(np.intp)
    z_index = np.rint(
        (z_world - geometry.source_target_min_z) / source.spacing_m
    ).astype(np.intp)
    x_index = np.clip(x_index, 0, dominant.shape[1] - 1)
    z_index = np.clip(z_index, 0, dominant.shape[0] - 1)

    a = dominant[np.ix_(z_index[:-1], x_index[:-1])]
    b = dominant[np.ix_(z_index[:-1], x_index[1:])]
    c = dominant[np.ix_(z_index[1:], x_index[1:])]
    d = dominant[np.ix_(z_index[1:], x_index[:-1])]
    return np.stack((a, b, c, d)).astype(np.uint8, copy=False)


def fill_unbound_base_slots(texture_indices: np.ndarray,
                            ignored_slots: Collection[int]) -> tuple[np.ndarray, int]:
    """Replace unbound layer-0 cluster slots with the nearest bound base slot.

    BZCC maps (for example isdf01) can leave TER slot 0 undeclared in the TRN
    yet use it as a cluster's base layer, normally under near-opaque upper
    layers. Layer 0 must name a real Redux material, so each such cluster takes
    the most common bound base slot in the smallest surrounding square
    that has one. Ties pick the lower slot.
    """
    ignored = tuple(int(slot) for slot in ignored_slots)
    base = texture_indices[0]
    bad = np.isin(base, ignored) if ignored else np.zeros(base.shape, dtype=bool)
    if not bad.any():
        return texture_indices, 0
    if bad.all():
        raise ValueError("Every BZ2 layer-0 cluster uses an unbound texture slot")
    result = texture_indices.copy()
    rows, cols = base.shape
    for cz, cx in np.argwhere(bad):
        radius = 1
        while True:
            z0, z1 = max(0, cz - radius), min(rows, cz + radius + 1)
            x0, x1 = max(0, cx - radius), min(cols, cx + radius + 1)
            window = base[z0:z1, x0:x1][~bad[z0:z1, x0:x1]]
            if window.size:
                result[0, cz, cx] = np.bincount(window, minlength=MATERIAL_COUNT).argmax()
                break
            radius += 1
    return result, int(bad.sum())


def reduce_bz2_mat_cells(source: SourceTerrain,
                         geometry: "PortGeometry",
                         ignored_slots: Collection[int] = ()) -> MatReduction:
    """Integrate four-layer BZ2 weights into 20 m Redux MAT cells.

    Texture slots remain the numeric TER slots 0..15.  For each MAT cell,
    ``weights[slot]`` is the mean effective sequential-blend coverage of that
    slot over the source samples contributing to the cell.  Ties select the
    lower slot, which makes the diagnostic deterministic.
    """
    if source.heights_m.ndim != 2:
        raise ValueError("Source TER heights must be a two-dimensional raster")
    if source.alphas.shape[1:] != source.heights_m.shape:
        raise ValueError("Source TER alpha maps must match the height raster")
    if geometry.width_m <= 0 or geometry.depth_m <= 0:
        raise ValueError("Port geometry must have positive dimensions")
    if geometry.width_m % MAT_CELL_M or geometry.depth_m % MAT_CELL_M:
        raise ValueError("Redux terrain dimensions must be divisible by the 20 m MAT cell size")

    source_height, source_width = source.heights_m.shape
    source_cluster = 4 if source.version == 3 else 16
    if source.info.shape != (
        (source_height + source_cluster - 1) // source_cluster,
        (source_width + source_cluster - 1) // source_cluster,
    ):
        raise ValueError("Source TER InfoMap dimensions do not match the terrain raster")

    ignored = frozenset(int(slot) for slot in ignored_slots)
    if any(slot < 0 or slot >= MATERIAL_COUNT for slot in ignored):
        raise ValueError("Ignored BZ2 texture slots must be in the 0..15 range")
    texture_indices, _ = fill_unbound_base_slots(source.texture_indices, ignored)
    sample_slots = _sample_slot_maps(source, texture_indices)

    alphas = source.alphas
    if ignored:
        alphas = source.alphas.copy()
        for layer in range(1, 4):
            mask = np.isin(sample_slots[layer], tuple(ignored))
            alphas[layer - 1][mask] = 0

    effective = sequential_layer_weights(alphas)
    dominant = _dominant_source_materials(effective, sample_slots)
    cells_z = geometry.depth_m // MAT_CELL_M
    cells_x = geometry.width_m // MAT_CELL_M
    weights = np.zeros((MATERIAL_COUNT, cells_z, cells_x), dtype=np.float32)
    sample_counts = np.zeros((cells_z, cells_x), dtype=np.uint32)

    for mat_z in range(cells_z):
        start_z = geometry.min_z + mat_z * MAT_CELL_M
        z0, z1 = _window(start_z, start_z + MAT_CELL_M,
                          geometry.source_target_min_z, source.spacing_m, source_height)
        for mat_x in range(cells_x):
            start_x = geometry.min_x + mat_x * MAT_CELL_M
            x0, x1 = _window(start_x, start_x + MAT_CELL_M,
                              geometry.source_target_min_x, source.spacing_m, source_width)
            count = (z1 - z0) * (x1 - x0)
            sample_counts[mat_z, mat_x] = count
            totals = np.zeros(MATERIAL_COUNT, dtype=np.float64)
            for layer in range(4):
                slot_grid = sample_slots[layer, z0:z1, x0:x1]
                np.add.at(
                    totals,
                    slot_grid.ravel(),
                    effective[layer, z0:z1, x0:x1].ravel(),
                )
            weights[:, mat_z, mat_x] = (totals / count).astype(np.float32)

    # Stable descending order: mergesort preserves slot order for equal weights.
    order = np.argsort(-weights, axis=0, kind="stable")
    primary = order[0].astype(np.uint8)
    secondary = order[1].astype(np.uint8)
    secondary_weight = np.take_along_axis(weights, order[1:2], axis=0)[0]
    corner_materials = _corner_material_grid(source, geometry, dominant)
    return MatReduction(
        weights, primary, secondary, secondary_weight, sample_counts, corner_materials
    )
