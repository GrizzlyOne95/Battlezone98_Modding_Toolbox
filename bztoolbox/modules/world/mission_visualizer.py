from __future__ import annotations

import math
import os
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from bztoolbox.modules.world.hg2_codec import HG2Header

BZ_ZONE_WORLD_SIZE = 1280.0
_FIELD_RE_TEMPLATE = r"^\s*{name}(?:\s*\[\s*\d+\s*\])?\s*=\s*(.*)$"

DATA_VOID = 0
DATA_BOOL = 1
DATA_CHAR = 2
DATA_SHORT = 3
DATA_LONG = 4
DATA_FLOAT = 5
DATA_DOUBLE = 6
DATA_ID = 7
DATA_PTR = 8
DATA_VEC3D = 9
DATA_VEC2D = 10
DATA_MAT3DOLD = 11
DATA_MAT3D = 12
DATA_STRING = 13
DATA_QUAT = 14
_MAX_BINARY_FIELD_TYPE = DATA_QUAT


@dataclass(frozen=True)
class _BinaryToken:
    type: int
    raw_type: int
    data: bytes
    offset: int
    end: int


@dataclass(frozen=True)
class _BinaryHeader:
    version: int
    binary_offset: int
    terrain_name: str | None
    object_count: int
    objects_offset: int


def hg2_world_size(header: HG2Header) -> tuple[float, float]:
    """Return the Battlezone world width/depth represented by an HG2."""
    return (
        float(header.zones_x) * BZ_ZONE_WORLD_SIZE,
        float(header.zones_z) * BZ_ZONE_WORLD_SIZE,
    )


def hg2_north_up(heights: np.ndarray) -> np.ndarray:
    """Convert HG2's south-first row convention to a north-at-top display array."""
    array = np.asarray(heights)
    if array.ndim != 2:
        raise ValueError("HG2 height data must be a 2D array")
    return np.flipud(array)


def world_to_canvas(
    world_x: float,
    world_z: float,
    *,
    min_x: float,
    min_z: float,
    world_width: float,
    world_depth: float,
    draw_rect: tuple[float, float, float, float],
) -> tuple[float, float]:
    """Map Battlezone +X/+Z coordinates into a north-at-top canvas rectangle."""
    if world_width <= 0 or world_depth <= 0:
        raise ValueError("Mission world width/depth must be positive")

    left, top, pixel_width, pixel_height = draw_rect
    rel_x = (float(world_x) - float(min_x)) / float(world_width)
    rel_z = (float(world_z) - float(min_z)) / float(world_depth)

    return (
        float(left) + rel_x * float(pixel_width),
        float(top) + (1.0 - rel_z) * float(pixel_height),
    )


def _clean_bzn_value(value: str) -> str:
    return value.strip().strip('"').strip("'").rstrip("\x00").strip()


def _next_scalar(lines: list[str], start: int) -> str | None:
    for index in range(start, len(lines)):
        value = lines[index].strip()
        if not value:
            continue
        # A new structure marker/field before a scalar means the requested
        # field did not have a simple next-line value.
        if value.startswith("[") or re.match(r"^[A-Za-z_][^=]*=", value):
            return None
        return _clean_bzn_value(value)
    return None


def _ascii_prefix_lines(raw: bytes, limit: int = 65536) -> list[tuple[str, int]]:
    """Return decoded prefix lines paired with their byte end offsets."""
    prefix = raw[:limit]
    lines: list[tuple[str, int]] = []
    offset = 0
    for chunk in prefix.splitlines(keepends=True):
        offset += len(chunk)
        text = chunk.rstrip(b"\r\n").decode("cp1252", errors="replace")
        lines.append((text, offset))
    if prefix and (not lines or lines[-1][1] < len(prefix)):
        tail = prefix[offset:]
        lines.append((tail.decode("cp1252", errors="replace"), len(prefix)))
    return lines


def _find_ascii_bzn_field(
    raw: bytes,
    field_names: Iterable[str],
) -> tuple[str | None, int | None]:
    """Find a scalar in the ASCII prefix and return value plus its line-end offset."""
    lines = _ascii_prefix_lines(raw)
    for name in field_names:
        pattern = re.compile(_FIELD_RE_TEMPLATE.format(name=re.escape(name)), re.IGNORECASE)
        for index, (line, line_end) in enumerate(lines):
            match = pattern.match(line)
            if not match:
                continue
            inline = _clean_bzn_value(match.group(1))
            if inline:
                return inline, line_end
            for next_index in range(index + 1, len(lines)):
                value, value_end = lines[next_index]
                stripped = value.strip()
                if not stripped:
                    continue
                if stripped.startswith("[") or re.match(r"^[A-Za-z_][^=]*=", stripped):
                    return None, None
                return _clean_bzn_value(stripped), value_end
    return None, None


def extract_ascii_bzn_field(path: os.PathLike | str, field_names: Iterable[str]) -> str | None:
    """Read a simple scalar field from the ASCII portion of a BZN."""
    raw = Path(path).read_bytes()
    value, _ = _find_ascii_bzn_field(raw, field_names)
    return value


def _binary_switch(raw: bytes) -> tuple[bool, int | None]:
    value, end = _find_ascii_bzn_field(raw, ("binarySave",))
    if value is None:
        return False, None
    normalized = value.strip().casefold()
    enabled = normalized in {"1", "true", "yes", "on"}
    return enabled, end if enabled else None


def is_binary_bzn(path: os.PathLike | str) -> bool:
    """Return True for normal BZ1 hybrid BZNs whose binarySave flag is enabled."""
    raw = Path(path).read_bytes()
    enabled, _ = _binary_switch(raw)
    return enabled


def _read_binary_token(raw: bytes, offset: int) -> tuple[_BinaryToken, int]:
    if offset < 0 or offset + 4 > len(raw):
        raise ValueError(f"Truncated binary BZN token header at 0x{offset:X}.")
    raw_type, size = struct.unpack_from("<HH", raw, offset)
    field_type = raw_type & 0xFF
    if field_type > _MAX_BINARY_FIELD_TYPE:
        raise ValueError(
            f"Invalid binary BZN field type {field_type} (raw 0x{raw_type:04X}) at 0x{offset:X}."
        )
    data_start = offset + 4
    end = data_start + size
    if end > len(raw):
        raise ValueError(
            f"Truncated binary BZN field at 0x{offset:X}: size {size} exceeds file length."
        )
    return _BinaryToken(field_type, raw_type, raw[data_start:end], offset, end), end


def _expect_binary_token(raw: bytes, offset: int, field_type: int, field_name: str) -> tuple[_BinaryToken, int]:
    token, next_offset = _read_binary_token(raw, offset)
    if token.type != field_type:
        raise ValueError(
            f"Unsupported/malformed binary BZN: expected {field_name} type {field_type} "
            f"at 0x{offset:X}, got {token.type}."
        )
    return token, next_offset


def _decode_bzn_string(data: bytes) -> str:
    return _clean_bzn_value(data.split(b"\x00", 1)[0].decode("cp1252", errors="replace"))


def _int32(data: bytes) -> int:
    if len(data) < 4:
        raise ValueError("Binary BZN LONG field is shorter than four bytes.")
    return struct.unpack_from("<i", data)[0]


def _uint32(data: bytes) -> int:
    if len(data) < 4:
        raise ValueError("Binary BZN 32-bit field is shorter than four bytes.")
    return struct.unpack_from("<I", data)[0]


def _parse_binary_header(raw: bytes) -> _BinaryHeader:
    version_text, _ = _find_ascii_bzn_field(raw, ("version",))
    if version_text is None:
        raise ValueError("Binary BZN is missing its ASCII version header.")
    try:
        version = int(version_text, 0)
    except ValueError as exc:
        raise ValueError(f"Invalid BZN version value: {version_text!r}.") from exc

    binary, offset = _binary_switch(raw)
    if not binary or offset is None:
        raise ValueError("BZN does not enable binarySave.")
    if version <= 1022:
        raise ValueError(
            f"Binary Mission Visualizer support currently targets BZ1/Redux hybrid BZNs "
            f"(version > 1022); got version {version}."
        )

    # BZNTools/BZ1 serialization order after binarySave:
    # msn_filename, seq_count, missionSave, TerrainName, [size/object count].
    _, offset = _expect_binary_token(raw, offset, DATA_CHAR, "msn_filename")
    _, offset = _expect_binary_token(raw, offset, DATA_LONG, "seq_count")
    mission_token, offset = _expect_binary_token(raw, offset, DATA_BOOL, "missionSave")
    mission_save = bool(mission_token.data[0]) if mission_token.data else False
    terrain_token, offset = _expect_binary_token(raw, offset, DATA_CHAR, "TerrainName")
    terrain_name = _decode_bzn_string(terrain_token.data) or None

    # BZNTools shows BZ1 save-games may insert start_time here. Normal mission
    # BZNs do not, but accepting it costs nothing and keeps the reader honest.
    next_token, next_offset = _read_binary_token(raw, offset)
    if not mission_save and version > 1002 and next_token.type == DATA_FLOAT:
        offset = next_offset
    size_token, offset = _expect_binary_token(raw, offset, DATA_LONG, "GameObject size")
    object_count = _int32(size_token.data)
    if object_count < 0 or object_count > 1_000_000:
        raise ValueError(f"Invalid binary BZN GameObject count: {object_count}.")

    return _BinaryHeader(
        version=version,
        binary_offset=_binary_switch(raw)[1] or 0,
        terrain_name=terrain_name,
        object_count=object_count,
        objects_offset=offset,
    )


def parse_mission_bzn(
    path: os.PathLike | str,
    ascii_parser,
) -> tuple[list[dict], list[dict]]:
    """Dispatch a mission to the binary overlay reader or the existing ASCII parser."""
    if is_binary_bzn(path):
        return parse_binary_bzn_overlay(path)
    return ascii_parser(path)


def _install_world_builder_core_binary_bridge() -> None:
    """Bridge WorldBuilder's legacy BZNParser call without creating an import cycle.

    world_builder.py imports world_builder_core before this module and calls
    extract_terrain_name() immediately before core.BZNParser.parse(). Installing
    the wrapper only when a binary mission is actually selected keeps the ASCII
    parser untouched and localizes binary format knowledge in this module.
    """
    core = sys.modules.get("bztoolbox.modules.world.world_builder_core")
    if core is None or not hasattr(core, "BZNParser"):
        return

    parser_class = core.BZNParser
    current = parser_class.parse
    if getattr(current, "_mission_visualizer_binary_bridge", False):
        return

    original = current

    def dispatch(path):
        return parse_mission_bzn(path, original)

    dispatch._mission_visualizer_binary_bridge = True
    dispatch._mission_visualizer_ascii_parser = original
    parser_class.parse = staticmethod(dispatch)


def extract_terrain_name(path: os.PathLike | str) -> str | None:
    raw = Path(path).read_bytes()
    binary, _ = _binary_switch(raw)
    if binary:
        _install_world_builder_core_binary_bridge()
        return _parse_binary_header(raw).terrain_name
    value, _ = _find_ascii_bzn_field(raw, ("TerrainName", "g_TerrainName"))
    return value


def _tokenize_binary_tail(raw: bytes, offset: int) -> list[_BinaryToken]:
    tokens: list[_BinaryToken] = []
    while offset < len(raw):
        remainder = raw[offset:]
        if not remainder or all(byte in b"\x00\r\n\t " for byte in remainder):
            break
        token, offset = _read_binary_token(raw, offset)
        tokens.append(token)
    return tokens


def _plausible_identifier(data: bytes) -> bool:
    value = _decode_bzn_string(data)
    if not value or len(value) > 256:
        return False
    # BZ ODF/PrjID strings are ordinary single-byte identifiers. Keep this
    # deliberately permissive for custom mods while rejecting binary noise.
    return "\ufffd" not in value and all(
        ch.isprintable() and ch not in "\r\n\t" for ch in value
    )


def _parse_object_descriptor(tokens: list[_BinaryToken], index: int) -> dict | None:
    signature = (
        DATA_ID,
        DATA_SHORT,
        DATA_VEC3D,
        DATA_LONG,
        DATA_CHAR,
        DATA_LONG,
        DATA_PTR,
        DATA_MAT3DOLD,
    )
    if index + len(signature) > len(tokens):
        return None
    window = tokens[index:index + len(signature)]
    if tuple(token.type for token in window) != signature:
        return None

    prjid, seq_token, pos_token, team_token, label_token, user_token, ptr_token, transform_token = window
    if not _plausible_identifier(prjid.data):
        return None
    if len(seq_token.data) < 2 or len(pos_token.data) < 12:
        return None
    if len(team_token.data) < 4 or len(user_token.data) < 4 or len(ptr_token.data) < 4:
        return None
    if len(transform_token.data) < 48:
        return None

    x, y, z = struct.unpack_from("<fff", pos_token.data)
    if not all(math.isfinite(value) for value in (x, y, z)):
        return None

    is_user = _uint32(user_token.data)
    if is_user not in (0, 1):
        return None

    odf = _decode_bzn_string(prjid.data)
    label = _decode_bzn_string(label_token.data)
    seqno = struct.unpack_from("<H", seq_token.data)[0]
    team = _uint32(team_token.data)
    return {
        "name": label or odf,
        "odf": odf,
        "pos": (x, y, z),
        "rot": 0,
        "label": label or None,
        "team": team,
        "seqno": seqno,
    }


def _extract_binary_objects(
    tokens: list[_BinaryToken],
    expected_count: int,
) -> tuple[list[dict], int]:
    objects: list[dict] = []
    index = 0
    last_descriptor_end = 0

    while index < len(tokens) and len(objects) < expected_count:
        obj = _parse_object_descriptor(tokens, index)
        if obj is None:
            index += 1
            continue
        objects.append(obj)
        index += 8
        last_descriptor_end = index

    if len(objects) != expected_count:
        raise ValueError(
            "Binary BZN object table could not be decoded safely: "
            f"header says {expected_count}, recovered {len(objects)} descriptors."
        )
    return objects, last_descriptor_end


def _parse_path_record(
    tokens: list[_BinaryToken],
    index: int,
    version: int,
) -> tuple[dict, int] | None:
    if index >= len(tokens):
        return None
    expected_ptr_type = DATA_PTR if version > 2011 else DATA_VOID
    if tokens[index].type != expected_ptr_type:
        return None
    index += 1

    if index >= len(tokens) or tokens[index].type != DATA_LONG:
        return None
    try:
        label_size = _uint32(tokens[index].data)
    except ValueError:
        return None
    index += 1
    if label_size > 1_000_000:
        return None

    label = ""
    if label_size:
        if index >= len(tokens) or tokens[index].type != DATA_CHAR:
            return None
        label_token = tokens[index]
        label = _decode_bzn_string(label_token.data)
        if len(label_token.data) < label_size:
            return None
        index += 1

    if index >= len(tokens) or tokens[index].type != DATA_LONG:
        return None
    try:
        point_count = _int32(tokens[index].data)
    except ValueError:
        return None
    index += 1
    if point_count < 0 or point_count > 1_000_000:
        return None

    if index >= len(tokens) or tokens[index].type != DATA_VEC2D:
        return None
    points_token = tokens[index]
    index += 1
    if len(points_token.data) != point_count * 8:
        return None
    points = [
        struct.unpack_from("<ff", points_token.data, point_index * 8)
        for point_index in range(point_count)
    ]
    if not all(math.isfinite(x) and math.isfinite(z) for x, z in points):
        return None

    if index >= len(tokens) or tokens[index].type != DATA_VOID:
        return None
    path_type_token = tokens[index]
    index += 1
    if len(path_type_token.data) < 4:
        return None
    path_type = _uint32(path_type_token.data)

    return {
        "label": label,
        "points": points,
        "type": path_type,
    }, index


def _extract_binary_paths(
    tokens: list[_BinaryToken],
    start_index: int,
    version: int,
) -> list[dict]:
    # BZN tail data contains several count fields. Rather than guessing every
    # class-specific GameObject length, find the first count followed by a run
    # of records that satisfies the exact BZ1 AiPath schema from BZNTools.
    for count_index in range(max(0, start_index), len(tokens)):
        count_token = tokens[count_index]
        if count_token.type != DATA_LONG or len(count_token.data) < 4:
            continue
        try:
            count = _int32(count_token.data)
        except ValueError:
            continue
        if count <= 0 or count > 100_000:
            continue

        paths: list[dict] = []
        index = count_index + 1
        for _ in range(count):
            parsed = _parse_path_record(tokens, index, version)
            if parsed is None:
                paths = []
                break
            path, index = parsed
            paths.append(path)
        if len(paths) == count:
            return paths
    return []


def parse_binary_bzn_overlay(path: os.PathLike | str) -> tuple[list[dict], list[dict]]:
    """Extract visualizer-level GameObjects and AI paths from a BZ1/Redux binary BZN.

    This intentionally decodes only the stable serialization surfaces required
    by Mission Visualizer. It does not attempt to interpret class-specific
    GameObject payloads, mission DLL state, or save-game runtime state.
    """
    raw = Path(path).read_bytes()
    header = _parse_binary_header(raw)
    tokens = _tokenize_binary_tail(raw, header.objects_offset)
    objects, last_descriptor_end = _extract_binary_objects(tokens, header.object_count)
    paths = _extract_binary_paths(tokens, last_descriptor_end, header.version)
    return objects, paths


def _case_insensitive_child(directory: Path, name: str) -> Path | None:
    """Return the actual directory entry matching name, preserving on-disk casing."""
    if not directory.is_dir():
        return None

    # Enumerate instead of returning ``directory / name`` after is_file().
    # On case-insensitive filesystems (notably default macOS/Windows), that
    # synthetic Path can exist while carrying casing that differs from the
    # real directory entry. Returning the entry itself keeps behavior stable
    # across platforms and makes diagnostics show the actual filename.
    target = name.casefold()
    folded_match = None
    for child in directory.iterdir():
        if not child.is_file():
            continue
        if child.name == name:
            return child
        if folded_match is None and child.name.casefold() == target:
            folded_match = child
    return folded_match


def _canonical_file(path: Path) -> Path | None:
    """Resolve a file path while preserving the actual final-component casing."""
    return _case_insensitive_child(path.parent, path.name)


def resolve_mission_trn(
    bzn_path: os.PathLike | str,
    terrain_name: str | None = None,
) -> Path | None:
    """Resolve the terrain config referenced by BZN TerrainName, then same-stem fallback."""
    bzn = Path(bzn_path)
    directory = bzn.parent
    candidates: list[str] = []

    if terrain_name:
        normalized = _clean_bzn_value(terrain_name).replace("\\", "/")
        terrain_path = Path(normalized)
        names = [normalized, terrain_path.name]
        for name in names:
            if not name:
                continue
            candidates.append(name)
            if Path(name).suffix.lower() != ".trn":
                candidates.append(name + ".trn")

    candidates.append(bzn.stem + ".trn")

    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)

        candidate_path = Path(candidate)
        if candidate_path.is_absolute():
            resolved = _canonical_file(candidate_path)
            if resolved is not None:
                return resolved
            continue

        # Try the referenced relative path first, while returning the actual
        # on-disk entry rather than a synthetic differently-cased Path.
        relative = directory / candidate_path
        resolved = _canonical_file(relative)
        if resolved is not None:
            return resolved

        # If TerrainName carried a directory component that is not present in
        # the extracted package, also try its basename next to the BZN.
        sibling = _case_insensitive_child(directory, candidate_path.name)
        if sibling is not None:
            return sibling

    return None


def resolve_companion_hg2(trn_path: os.PathLike | str | None) -> Path | None:
    if not trn_path:
        return None
    trn = Path(trn_path)
    return _case_insensitive_child(trn.parent, trn.stem + ".hg2")
