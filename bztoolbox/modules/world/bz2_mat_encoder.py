"""Encode reduced BZ2/BZCC material data into Redux MAT entries.

The reducer supplies four source-derived corner material IDs for every 20 m
Redux MAT cell.  Redux can represent solid cells plus a constrained set of
two-material cap/diagonal patterns.  Unsupported checkerboards or cells with
three or more corner materials fall back to the cell's strongest integrated
material instead of inventing an orientation.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from bztoolbox.modules.world.bz2_mat_reducer import MatReduction
from bztoolbox.modules.world.mat_codec import MSVCRand, decode_entry, encode_make_trn_tile, encode_mix_entry


@dataclass(frozen=True)
class EncodedBz2Mat:
    entries: np.ndarray
    cap_pairs: frozenset[tuple[int, int]]
    diagonal_pairs: frozenset[tuple[int, int]]
    solid_cells: int
    cap_cells: int
    diagonal_cells: int
    ambiguous_cells: int


def encode_bz2_mat(reduction: MatReduction,
                   material_map: dict[int, int] | None = None) -> EncodedBz2Mat:
    """Encode one deterministic Redux MAT entry per reduced 20 m cell."""
    primary = np.asarray(reduction.primary_material)
    corners = np.asarray(reduction.corner_materials)
    if primary.ndim != 2:
        raise ValueError("Reduced BZ2 primary material grid must be two-dimensional")
    if corners.shape != (4, *primary.shape):
        raise ValueError(
            f"Reduced BZ2 corner grid must have shape {(4, *primary.shape)}; "
            f"found {corners.shape}"
        )

    def target_material(source: int) -> int:
        if material_map is None:
            return source
        if source not in material_map:
            raise ValueError(f"Reduced MAT uses unresolved source texture slot {source}")
        target = material_map[source]
        if not 0 <= target <= 15:
            raise ValueError(f"Redux material {target} is outside the 0..15 range")
        return target

    entries = np.empty(primary.shape, dtype=np.uint16)
    caps: set[tuple[int, int]] = set()
    diagonals: set[tuple[int, int]] = set()
    solid_cells = cap_cells = diagonal_cells = ambiguous_cells = 0

    for z in range(primary.shape[0]):
        for x in range(primary.shape[1]):
            cell_corners = tuple(target_material(int(value)) for value in corners[:, z, x])
            fallback = target_material(int(primary[z, x]))
            if len(set(cell_corners)) > 2:
                entries[z, x] = encode_mix_entry(fallback, fallback, 0, variant=0)
                ambiguous_cells += 1
                continue

            # A fresh seed makes source-authored MAT conversion deterministic
            # and selects variant/mirror zero for the canonical pattern.
            entry, kind = encode_make_trn_tile(cell_corners, MSVCRand(1))
            if kind == "ambiguous":
                entries[z, x] = encode_mix_entry(fallback, fallback, 0, variant=0)
                ambiguous_cells += 1
                continue

            entries[z, x] = entry
            decoded = decode_entry(int(entry))
            if kind == "solid":
                solid_cells += 1
            elif kind == "cap":
                caps.add((decoded.base, decoded.next))
                cap_cells += 1
            elif kind == "diagonal":
                diagonals.add((decoded.base, decoded.next))
                diagonal_cells += 1
            else:
                raise AssertionError(f"Unexpected MAT transition kind: {kind}")

    return EncodedBz2Mat(
        entries=entries,
        cap_pairs=frozenset(caps),
        diagonal_pairs=frozenset(diagonals),
        solid_cells=solid_cells,
        cap_cells=cap_cells,
        diagonal_cells=diagonal_cells,
        ambiguous_cells=ambiguous_cells,
    )
