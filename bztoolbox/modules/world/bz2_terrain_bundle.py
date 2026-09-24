"""Build a resolved BZ2/BZCC terrain bundle for Redux validation.

This joins the independently tested TER, texture resolver, MAT reducer/encoder
and atlas stages.  The generated full TRN preserves non-texture sections from
the companion BZ2/BZCC TRN, replaces its source texture declaration with Redux
atlas bindings, and rewrites [Size] for the converted terrain geometry.

The result is a terrain-validation candidate, not a claim that BZN objects,
paths, water/hazard gameplay semantics, or every BZ2-specific TRN section have
already been ported.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from bztoolbox.modules.world.bz2_atlas_port import build_bz2_direct_atlas
from bztoolbox.modules.world.bz2_mat_encoder import encode_bz2_mat
from bztoolbox.modules.world.bz2_mat_reducer import fill_unbound_base_slots, reduce_bz2_mat_cells
from bztoolbox.modules.world.bz2_ter_codec import read_ter
from bztoolbox.modules.world.bz2_terrain_port import convert_ter_height, geometry_for
from bztoolbox.modules.world.bz2_texture_resolver import build_texture_slot_manifest, resolve_trn_texture_slots
from bztoolbox.modules.world.mat_codec import write_mat


def _read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="cp1252", errors="replace")


def _source_height_setting(trn_text: str) -> str:
    current = ""
    for raw in trn_text.splitlines():
        section = re.match(r"^\s*\[([^\]]+)\]", raw)
        if section:
            current = section.group(1).strip().casefold()
            continue
        if current == "size":
            match = re.match(r"^\s*Height\s*=\s*(.*?)\s*$", raw, re.IGNORECASE)
            if match and match.group(1):
                return match.group(1)
    return "100"


def rewrite_bz2_trn_for_redux(source_text: str, atlas_fragment: str, geometry) -> str:
    """Preserve source environment sections while replacing terrain bindings."""
    kept = []
    skip = False
    for raw in source_text.splitlines(keepends=True):
        section = re.match(r"^\s*\[([^\]]+)\]", raw)
        if section:
            name = section.group(1).strip().casefold()
            skip = (
                name in {"size", "texture", "atlases"}
                or bool(re.fullmatch(r"texturetype\d+", name))
            )
        if not skip:
            kept.append(raw)

    height = _source_height_setting(source_text)
    size = (
        "[Size]\n"
        f"MinX={geometry.min_x}\n"
        f"MinZ={geometry.min_z}\n"
        f"Width={geometry.width_m}\n"
        f"Depth={geometry.depth_m}\n"
        f"Height={height}\n"
    )
    preserved = "".join(kept).strip()
    parts = [size.rstrip()]
    if preserved:
        parts.append(preserved)
    parts.append(atlas_fragment.strip())
    return "\n\n".join(parts) + "\n"


def build_bz2_terrain_bundle(
    ter_path: str | Path,
    trn_path: str | Path,
    asset_root: str | Path,
    output_dir: str | Path,
    name: str,
    *,
    atlas_prefix: str | None = None,
    tile_res: int = 512,
    export_dds: bool = True,
    export_png: bool = False,
    target_min_x: int | None = None,
    target_min_z: int | None = None,
) -> dict:
    """Build the resolved terrain-side Redux package for in-game validation."""
    output_dir = Path(output_dir)
    trn_path = Path(trn_path)
    if not trn_path.is_file():
        raise ValueError(f"Companion BZ2/BZCC TRN does not exist: {trn_path}")

    # Resolve every texture dependency before the stage-1 writer creates any
    # output files. A missing package asset must fail without leaving a partial
    # "fresh" destination behind.
    source = read_ter(ter_path)
    geometry = geometry_for(
        source, target_min_x=target_min_x, target_min_z=target_min_z
    )
    manifest = resolve_trn_texture_slots(
        build_texture_slot_manifest(source), trn_path, asset_root
    )
    if not manifest["ready_for_atlas"]:
        raise ValueError(
            "Companion TRN texture resolution is incomplete; unresolved used slots: "
            f"{manifest['unresolved_used_slots']}"
        )

    # Stage-1 writer owns the common HG2/channel/provenance outputs and enforces
    # the fresh-destination contract once all read-only preflight checks pass.
    report = convert_ter_height(
        ter_path, output_dir, name,
        target_min_x=target_min_x, target_min_z=target_min_z,
        write_diagnostic_mat=False,
    )

    manifest_path = output_dir / f"{name}_source_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    ignored_slots = frozenset(manifest.get("empty_used_slots", ()))
    reduction = reduce_bz2_mat_cells(source, geometry, ignored_slots=ignored_slots)
    material_map = {
        int(entry["slot"]): int(entry["redux_material"])
        for entry in manifest["slots"] if entry["used"] and entry["status"] == "resolved"
    }
    encoded = encode_bz2_mat(reduction, material_map=material_map)

    reduction_path = output_dir / f"{name}_mat_reduction.npz"
    np.savez_compressed(
        reduction_path,
        weights=reduction.weights,
        primary_material=reduction.primary_material,
        secondary_material=reduction.secondary_material,
        secondary_weight=reduction.secondary_weight,
        sample_counts=reduction.sample_counts,
        corner_materials=reduction.corner_materials,
    )
    mat_path = output_dir / f"{name}.mat"
    write_mat(mat_path, encoded.entries, geometry.zones_x, geometry.zones_z)

    prefix = atlas_prefix or name
    atlas = build_bz2_direct_atlas(
        manifest,
        output_dir,
        prefix,
        tile_res=tile_res,
        export_dds=export_dds,
        export_png=export_png,
        cap_pairs=encoded.cap_pairs,
        diagonal_pairs=encoded.diagonal_pairs,
    )

    fragment_path = output_dir / f"{prefix.upper()}_CONFIG.TRN"
    fragment = _read_text(fragment_path)
    full_trn_path = output_dir / f"{name}.trn"
    full_trn_path.write_text(
        rewrite_bz2_trn_for_redux(_read_text(trn_path), fragment, geometry),
        encoding="cp1252",
        errors="replace",
        newline="\n",
    )

    report["status"] = "resolved_terrain_bundle_candidate_requires_in_game_validation"
    report["companion_trn"] = str(trn_path.resolve())
    report["asset_root"] = str(Path(asset_root).resolve())
    report["unresolved_texture_slots"] = []
    report["empty_texture_slots"] = sorted(ignored_slots)
    report["source_to_redux_material"] = {
        str(source): target for source, target in sorted(material_map.items())
    }
    report["mat_reduction"].update({
        "encoded_mat": mat_path.name,
        "cap_pairs": [list(pair) for pair in sorted(encoded.cap_pairs)],
        "diagonal_pairs": [list(pair) for pair in sorted(encoded.diagonal_pairs)],
        "solid_cells": encoded.solid_cells,
        "cap_cells": encoded.cap_cells,
        "diagonal_cells": encoded.diagonal_cells,
        "ambiguous_cells": encoded.ambiguous_cells,
        "empty_slots_suppressed": sorted(ignored_slots),
        "unbound_base_clusters_filled": fill_unbound_base_slots(
            source.texture_indices, ignored_slots)[1],
    })
    report["atlas"] = {
        "prefix": atlas["prefix"],
        "tile_count": atlas["tile_count"],
        "source_to_redux_material": atlas["source_to_redux_material"],
        "mapping_file": Path(atlas["mapping_file"]).name if atlas["mapping_file"] else None,
        "material_file": f"{prefix.lower()}_detail_atlas.material",
        "trn_fragment": fragment_path.name,
        "full_trn": full_trn_path.name,
        "transition_policy": atlas["transition_policy"],
    }
    report["next_stage"] = (
        "Validate orientation/material transitions in BZR, then port BZN objects, "
        "paths, water and hazard semantics"
    )
    report_path = output_dir / f"{name}_port.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
