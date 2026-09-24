"""Map resolved BZ2/BZCC texture slots to Redux atlas materials.

The material IDs supplied by the companion TRN resolver drive solid and
requested cap/diagonal atlas entries. MAT reduction happens upstream.
"""
from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable
from io import BytesIO

from PIL import Image

from bztoolbox.modules.world.custom_atlas_builder import build_custom_atlas
from bztoolbox.modules.world.bz2_pak import PakArchive


def _open_source_texture(source):
    """Open TGA/DDS, normalizing DX10 BC1/BC3 sRGB tags for Pillow."""
    data = source.read_bytes() if isinstance(source, Path) else source.getvalue()
    if data[:4] == b"DDS " and data[84:88] == b"DX10" and len(data) >= 132:
        dxgi = int.from_bytes(data[128:132], "little")
        if dxgi in (72, 78):  # BC1/BC3 sRGB: same blocks as UNORM.
            adjusted = bytearray(data)
            adjusted[128:132] = (dxgi - 1).to_bytes(4, "little")
            data = bytes(adjusted)
    return Image.open(BytesIO(data))


def build_bz2_direct_atlas(manifest: dict, output_dir: str | Path, prefix: str,
                           tile_res: int = 512, export_dds: bool = True,
                           export_png: bool = False,
                           cap_pairs: Iterable[tuple[int, int]] | None = None,
                           diagonal_pairs: Iterable[tuple[int, int]] | None = None) -> dict:
    """Build atlas entries using each source slot's mapped Redux material ID."""
    if not manifest.get("ready_for_atlas"):
        unresolved = manifest.get("unresolved_used_slots", [])
        raise ValueError(f"Cannot build BZ2 atlas with unresolved texture slots: {unresolved}")
    if tile_res <= 0:
        raise ValueError("Atlas tile resolution must be positive")
    if not prefix or not prefix.isascii() or not prefix.isalnum():
        raise ValueError("Atlas prefix must be non-empty ASCII alphanumeric text")

    groups = {}
    source_slots = {}
    target_by_source = {}
    for entry in manifest.get("slots", []):
        if not entry.get("used"):
            continue
        # BZ2/BZCC commonly leave upper-layer zero nibbles unbound when the
        # companion TRN starts at TileTexture1.  The resolver records that
        # case explicitly as ``empty``; it is not a texture that belongs in
        # the solid atlas.  An explicitly declared TileTexture0 remains a
        # normal resolved slot and is still emitted below.
        if entry.get("status") == "empty":
            continue
        slot = int(entry["slot"])
        target = entry.get("redux_material")
        if type(target) is not int or not 0 <= target <= 15:
            raise ValueError(f"Texture slot {slot} has invalid Redux material {target!r}")
        if target in groups:
            raise ValueError(f"Texture slots map to the same Redux material {target}")
        if entry.get("status") != "resolved" or not (
                entry.get("source_path") or
                (entry.get("source_archive") and entry.get("source_member"))):
            raise ValueError(f"Texture slot {slot} is not resolved")

        if entry.get("source_path"):
            path = Path(entry["source_path"])
            if not path.is_file():
                raise FileNotFoundError(f"Resolved texture slot {slot} is missing: {path}")
            image_source = path
            provenance = str(path.resolve())
        else:
            archive = PakArchive(entry["source_archive"])
            member = entry["source_member"]
            image_source = BytesIO(archive.read(member))
            provenance = f"{archive.path}!{member}"
        with _open_source_texture(image_source) as source:
            image = source.convert("RGBA").resize(
                (tile_res, tile_res), Image.Resampling.LANCZOS
            )
        groups[target] = {"A": image}
        source_slots[slot] = provenance
        target_by_source[slot] = target

    if not groups:
        raise ValueError("BZ2 atlas manifest contains no used texture slots")

    explicit_pairs = cap_pairs is not None or diagonal_pairs is not None
    normalized_caps = frozenset(tuple(map(int, pair)) for pair in (cap_pairs or ()))
    normalized_diagonals = frozenset(
        tuple(map(int, pair)) for pair in (diagonal_pairs or ())
    )

    result = build_custom_atlas({
        "res": tile_res,
        "prfx": prefix.lower(),
        "mode": "ExplicitPairs" if explicit_pairs else "SolidsOnly",
        "out_dir": str(Path(output_dir)),
        "exp_dds": export_dds,
        "exp_png": export_png,
        "exp_normal": False,
        "exp_specular": False,
        "exp_emissive": False,
        "exp_csv": True,
        "exp_trn": True,
        "exp_mat": True,
        "exp_neutral_detail": True,
        "mapping_filename": f"{prefix.lower()}_detail_atlas.csv",
        "style": "Square/Blocky",
        "seed": 0,
        "depth": 0.0,
        "teeth": 1,
        "jitter": 0.0,
        "softness": 0,
        "groups": groups,
        "index_format": "hex",
        "cap_pairs": normalized_caps,
        "diagonal_pairs": normalized_diagonals,
    })
    result["source_slots"] = source_slots
    result["source_to_redux_material"] = target_by_source
    result["slot_to_atlas_alias"] = {
        slot: result["trn_blocks"][target_by_source[slot]]["solids"][0][1]
        for slot in sorted(source_slots)
    }
    result["transition_policy"] = (
        "exact_pairs_from_encoded_MAT"
        if explicit_pairs
        else "none_until_MAT_reduction_proves_required_pairs"
    )
    result["cap_pairs"] = sorted(normalized_caps)
    result["diagonal_pairs"] = sorted(normalized_diagonals)
    return result
