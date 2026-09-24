"""Texture-slot manifest contract for BZ2/BZCC terrain ports.

This stage intentionally does not guess source filenames. It records the 16 TER
slots exactly as authored so the package resolver and atlas builder can consume a
stable, deterministic mapping later.
"""
from __future__ import annotations

import copy
import re
from collections.abc import Iterable
from pathlib import Path, PureWindowsPath

from bztoolbox.modules.world.bz2_ter_codec import SourceTerrain
from bztoolbox.modules.world.bz2_pak import PakArchive, safe_member_name


def build_texture_slot_manifest(source: SourceTerrain) -> dict:
    """Return a stable 0..15 source-slot manifest without renumbering."""
    counts = [0] * 16
    for value in source.texture_indices.ravel():
        counts[int(value)] += 1

    slots = []
    unresolved = []
    for slot, usage_count in enumerate(counts):
        used = usage_count > 0
        status = "unresolved" if used else "unused"
        if used:
            unresolved.append(slot)
        slots.append({
            "slot": slot,
            "used": used,
            "usage_count": usage_count,
            "status": status,
            "source_name": None,
            "source_path": None,
            "redux_material": slot,
            "atlas_tile": None,
        })

    return {
        "schema_version": 1,
        "policy": "preserve TER texture slot numbers 0-15; never renumber by filename or discovery order",
        "slots": slots,
        "empty_used_slots": [],
        "unresolved_used_slots": unresolved,
        "resolved_used_slots": [],
        "ready_for_atlas": not unresolved,
    }


def extract_trn_texture_slots(trn_path: str | Path) -> dict[int, str]:
    """Read direct ``TileTextureN`` names from a BZ2/BZCC companion TRN.

    BZ2 terrain InfoMap nibbles use the same numeric ``N`` as the legacy TRN
    key.  Slot 0 is therefore preserved when explicitly authored, while a
    missing key remains unresolved instead of being guessed from filenames.
    """
    result: dict[int, str] = {}
    in_texture_section = False
    with open(trn_path, "r", encoding="cp1252", errors="replace") as stream:
        for raw in stream:
            header = re.match(r"^\s*\[([^\]]+)\]", raw)
            if header:
                in_texture_section = header.group(1).strip().casefold() == "texture"
                continue
            if not in_texture_section:
                continue
            match = re.match(r"^\s*TileTexture(\d+)\s*=\s*(.*?)\s*$", raw,
                             flags=re.IGNORECASE)
            if not match:
                continue
            slot = int(match.group(1))
            if not 0 <= slot < 16:
                raise ValueError(f"TRN texture slot {slot} is outside the supported 0..15 range")
            value = match.group(2).strip()
            if value.startswith('"') and value.endswith('"') and len(value) >= 2:
                value = value[1:-1]
            if not value:
                raise ValueError(f"TRN texture slot {slot} has an empty source name")
            previous = result.get(slot)
            if previous is not None and previous != value:
                raise ValueError(f"TRN declares conflicting names for texture slot {slot}")
            result[slot] = value
    return result


def resolve_trn_texture_slots(manifest: dict, trn_path: str | Path,
                              asset_root: str | Path) -> dict:
    """Resolve manifest slots using names from one explicit companion TRN."""
    names = extract_trn_texture_slots(trn_path)
    result = resolve_named_texture_slots(
        manifest, names, asset_root
    )
    # Redux's first texture type is 0. Companion BZ2/BZCC TRNs that begin at
    # TileTexture1 use source slot 0 as an unbound layer sentinel, so move the
    # declared slots down by one. A real TileTexture0 keeps identity mapping.
    material_shift = 0 if 0 in names else -1
    for entry in result["slots"]:
        slot = entry["slot"]
        entry["redux_material"] = (slot + material_shift
                                   if slot + material_shift >= 0 else None)
    result["material_index_offset"] = material_shift
    # The shipped BZ2/BZCC TRNs use TileTexture1..N; InfoMap zero is the
    # unbound/no-texture sentinel in those files. Keep an explicitly authored
    # TileTexture0 valid, but do not make ordinary upper-layer zero slots block
    # atlas generation.
    empty = []
    by_slot = {entry["slot"]: entry for entry in result["slots"]}
    if 0 not in names and by_slot.get(0, {}).get("used"):
        by_slot[0]["status"] = "empty"
        empty.append(0)
    result["empty_used_slots"] = empty
    result["unresolved_used_slots"] = sorted(
        entry["slot"] for entry in result["slots"]
        if entry["used"] and entry["status"] not in ("resolved", "empty")
    )
    result["ready_for_atlas"] = not result["unresolved_used_slots"]
    return result


def find_texture_asset_root(manifest: dict, trn_path: str | Path,
                            candidates: Iterable[str | Path]) -> Path | None:
    """Find the first folder resolving all required textures, loose or packed."""
    seen = set()
    for candidate in candidates:
        root = Path(candidate).resolve()
        if root in seen or not root.is_dir():
            continue
        seen.add(root)
        try:
            if resolve_trn_texture_slots(manifest, trn_path, root)["ready_for_atlas"]:
                return root
        except ValueError:
            continue
    return None


# Keep older callers working while adopting the more accurate name.
find_loose_texture_root = find_texture_asset_root


def _resolve_relative_case_insensitive(asset_root: Path, relative_name: str) -> Path | None:
    """Resolve one exact relative path below asset_root without filename guessing."""
    windows_name = PureWindowsPath(relative_name)
    relative = Path(relative_name.replace("\\", "/"))
    if (relative.is_absolute() or windows_name.is_absolute() or windows_name.drive
            or relative_name.startswith(("/", "\\"))
            or ".." in relative.parts):
        raise ValueError(f"Texture path must stay below asset root: {relative_name!r}")

    current = asset_root
    for part in relative.parts:
        if part in ("", "."):
            continue
        if not current.is_dir():
            return None
        matches = [child for child in current.iterdir() if child.name.casefold() == part.casefold()]
        if not matches:
            return None
        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous case-insensitive texture path component {part!r} below {current}"
            )
        current = matches[0]
    return current if current.is_file() else None


def resolve_named_texture_slots(manifest: dict, slot_names: dict[int, str],
                                asset_root: str | Path) -> dict:
    """Resolve explicitly supplied TER slot names against one asset root.

    Slot numbers are never changed. Names must be exact relative paths. Loose
    files take precedence over exact members of PAK archives in the root.
    """
    root = Path(asset_root).resolve()
    if not root.is_dir():
        raise ValueError(f"Texture asset root does not exist or is not a directory: {root}")

    result = copy.deepcopy(manifest)
    result["asset_root"] = str(root)

    archives = None

    def packed_match(name: str):
        nonlocal archives
        if archives is None:
            archives = [PakArchive(path) for path in sorted(root.iterdir(), key=lambda p: p.name.casefold())
                        if path.is_file() and path.suffix.casefold() == ".pak"]
        matches = [(archive, entry) for archive in archives
                   if (entry := archive.get(name)) is not None]
        if len(matches) > 1:
            raise ValueError(f"Texture {name!r} appears in multiple PAK archives below {root}")
        return matches[0] if matches else None

    def baked_dds_match(name: str) -> Path | None:
        # Some shipped TRNs still name legacy TGA files omitted from the PAKs.
        # BZCC's baked diffuse DDS is a usable exact-stem replacement.
        if Path(name).suffix.casefold() != ".tga":
            return None
        baked_worlds = root / "bz2r_res" / "baked" / "Worlds"
        if not baked_worlds.is_dir():
            return None
        wanted = Path(name.replace("\\", "/")).with_suffix(".dds").name.casefold()
        matches = [path for path in baked_worlds.rglob("*.dds")
                   if path.name.casefold() == wanted]
        if len(matches) > 1:
            raise ValueError(f"Ambiguous baked DDS replacement for {name!r}: {matches}")
        return matches[0] if matches else None

    by_slot = {entry["slot"]: entry for entry in result["slots"]}
    for slot, source_name in slot_names.items():
        if slot not in by_slot:
            raise ValueError(f"Texture slot {slot} is outside the supported 0..15 range")
        if not isinstance(source_name, str) or not source_name.strip():
            raise ValueError(f"Texture slot {slot} has an empty source name")

        entry = by_slot[slot]
        entry["source_name"] = source_name
        resolved = _resolve_relative_case_insensitive(root, source_name)
        try:
            safe_member_name(source_name)
        except ValueError as exc:
            raise ValueError(f"Texture path must stay below asset root: {source_name!r}") from exc
        if resolved is None:
            entry["source_path"] = None
            packed = packed_match(source_name)
            if packed:
                archive, member = packed
                entry["source_archive"] = str(archive.path)
                entry["source_member"] = member.name
                entry["status"] = "resolved" if entry["used"] else "unused"
            else:
                baked = baked_dds_match(source_name)
                if baked:
                    entry["source_path"] = str(baked.resolve())
                    entry["source_substitution"] = "baked_dds_same_stem"
                    entry["status"] = "resolved" if entry["used"] else "unused"
                else:
                    entry["status"] = "missing" if entry["used"] else "unused"
        else:
            entry["source_path"] = str(resolved.resolve())
            entry.pop("source_archive", None)
            entry.pop("source_member", None)
            entry["status"] = "resolved" if entry["used"] else "unused"

    resolved_used = sorted(
        entry["slot"] for entry in result["slots"]
        if entry["used"] and entry["status"] == "resolved"
    )
    unresolved_used = sorted(
        entry["slot"] for entry in result["slots"]
        if entry["used"] and entry["status"] != "resolved"
    )
    result["resolved_used_slots"] = resolved_used
    result["unresolved_used_slots"] = unresolved_used
    result["ready_for_atlas"] = not unresolved_used
    return result
