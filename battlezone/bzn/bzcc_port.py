#!/usr/bin/env python3
"""Port BZ2/BZCC mission map data into a BZ98 Redux ASCII BZN.

Uses a Redux ASCII BZN as a schema and a set of object prototypes. Transfers
object transforms, mapped teams and labels, terrain reference, paths, and AOIs.
Game-specific object state is inherited from the matching Redux prototype.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from battlezone.odf.class_labels import OdfIndex, diff_classes, format_table, summary


class PortError(Exception):
    pass


FIELD = re.compile(r"^\s*([^\s=\[]+)(?:\s+\[(\d+)\])?\s*=\s*(.*)$")
NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
MATRIX_KEYS = ("right.x", "right.y", "right.z", "up.x", "up.y", "up.z",
               "front.x", "front.y", "front.z", "posit.x", "posit.y", "posit.z")
REDUX_TEAM_MAX = 15


@dataclass
class ObjectPlacement:
    odf: str
    seqno: int
    team: int
    label: str
    is_user: bool
    matrix: tuple[float, ...]


@dataclass
class AiPath:
    old_ptr: int
    label: str
    points: list[tuple[float, float]]
    path_type: int


@dataclass
class AOI:
    path: int
    team: int
    interesting: bool
    inside: bool
    value: int
    force: int


@dataclass
class MissionData:
    objects: list[ObjectPlacement]
    terrain: str
    mission: str
    paths: list[AiPath]
    aois: list[AOI]


@dataclass
class Token:
    kind: int
    value: bytes


def text_lines(data: bytes) -> list[str]:
    return data.decode("cp1252").splitlines()


def field_value(lines: list[str], name: str, start: int = 0, end: int | None = None,
                occurrence: int = 0) -> str | None:
    seen = 0
    for i in range(start, len(lines) if end is None else end):
        match = FIELD.match(lines[i])
        if not match or match.group(1).lower() != name.lower():
            continue
        if seen != occurrence:
            seen += 1
            continue
        if match.group(2) is not None:
            count = int(match.group(2))
            if count:
                return " ".join(lines[i + 1:i + 1 + count]).strip().strip('"')
        return match.group(3).strip().strip('"')
    return None


def required(lines: list[str], name: str, start: int, end: int) -> str:
    value = field_value(lines, name, start, end)
    if value is None:
        raise PortError(f"missing {name} in object near line {start + 1}")
    return value


def parse_int(value: str) -> int:
    value = value.strip()
    if value.lower() in ("true", "yes"):
        return 1
    if value.lower() in ("false", "no"):
        return 0
    if value.lower().startswith("0x"):
        return int(value, 16)
    return int(value)


def parse_team_map(value: object) -> dict[int, int]:
    """Read a JSON map of BZCC team numbers to Redux team numbers."""
    if not isinstance(value, dict):
        raise PortError("--team-map must be a JSON object of source team to Redux team")
    result = {}
    for source, target in value.items():
        if not isinstance(source, str) or not re.fullmatch(r"-?\d+", source):
            raise PortError(f"--team-map source team {source!r} must be an integer string")
        source_team = int(source)
        if source_team in result:
            raise PortError(f"--team-map repeats source team {source_team}")
        if type(target) is not int or not 0 <= target <= REDUX_TEAM_MAX:
            raise PortError(f"--team-map target for team {source_team} must be 0..{REDUX_TEAM_MAX}")
        result[source_team] = target
    return result


def redux_team(source: int, team_map: dict[int, int], context: str) -> int:
    target = team_map.get(source, source)
    if type(target) is not int or not 0 <= target <= REDUX_TEAM_MAX:
        raise PortError(f"{context} has source team {source}, which maps to {target}; "
                        f"Redux teams must be 0..{REDUX_TEAM_MAX}. Use --team-map.")
    return target


def matrix_from_ascii(lines: list[str], start: int, end: int) -> tuple[float, ...]:
    for i in range(start, end):
        match = FIELD.match(lines[i])
        if not match or match.group(1).lower() != "transform":
            continue
        values = {}
        for offset in range(i + 1, min(end, i + 34)):
            line = lines[offset]
            child = FIELD.match(line)
            if child and child.group(1).lower() in MATRIX_KEYS:
                raw = child.group(3).strip()
                if child.group(2) == "1" and not raw:
                    raw = lines[offset + 1].strip() if offset + 1 < end else ""
                found = NUMBER.search(raw)
                if found:
                    values[child.group(1).lower()] = float(found.group())
        if len(values) == 12:
            return tuple(values[key] for key in MATRIX_KEYS)
        # Some dumps print the twelve components as plain numbers.
        plain = []
        for line in lines[i + 1:min(end, i + 32)]:
            if FIELD.match(line) and plain:
                break
            if not FIELD.match(line):
                plain.extend(float(x) for x in NUMBER.findall(line))
        if len(plain) >= 12:
            return tuple(plain[:12])
    raise PortError(f"missing 12-component transform near line {start + 1}")


def object_spans(lines: list[str]) -> tuple[list[tuple[int, int]], int, int]:
    starts = [i for i, line in enumerate(lines) if line.strip().lower() == "[gameobject]"]
    tail = next((i for i, line in enumerate(lines) if line.strip().lower() == "[aimission]"), len(lines))
    size = next((i for i, line in enumerate(lines[:tail]) if FIELD.match(line)
                 and FIELD.match(line).group(1).lower() == "size"), -1)
    if size < 0 or (starts and starts[0] < size):
        raise PortError("BZN has no recognizable object count")
    spans = [(s, starts[j + 1] if j + 1 < len(starts) else tail)
             for j, s in enumerate(starts) if s < tail]
    return spans, size, tail


def read_ascii_source(data: bytes) -> list[ObjectPlacement]:
    lines = text_lines(data)
    version = parse_int(required(lines, "version", 0, min(len(lines), 12)))
    if not 1000 <= version < 2000 or field_value(lines, "saveType", 0, 12) is None:
        raise PortError("source does not look like a BZ2/BZCC BZN")
    spans, size, _ = object_spans(lines)
    declared = parse_int(required(lines, "size", size, size + 2))
    if declared != len(spans):
        raise PortError(f"object count is {declared}, but found {len(spans)} object markers")
    result = []
    for start, end in spans:
        odf = next((field_value(lines, key, start, end) for key in
                    ("objClass", "GetClass()", "config") if field_value(lines, key, start, end)), None)
        if not odf:
            raise PortError(f"object near line {start + 1} has no ODF/class name")
        raw_seq = required(lines, "seqno", start, end)
        seqno = (int(raw_seq, 16) if version >= 1101 else parse_int(raw_seq)) & ~0x800000
        team = parse_int(required(lines, "team", start, end))
        label = field_value(lines, "label", start, end) or ""
        is_user = bool(parse_int(field_value(lines, "isUser", start, end) or "0"))
        result.append(ObjectPlacement(odf, seqno, team, label, is_user,
                                      matrix_from_ascii(lines, start, end)))
    return result


def read_ascii_mission(data: bytes) -> MissionData:
    objects = read_ascii_source(data)
    lines = text_lines(data)
    terrain = field_value(lines, "g_TerrainName") or field_value(lines, "TerrainName") or ""
    ai_mission = next((i for i, line in enumerate(lines) if line.strip() == "[AiMission]"), -1)
    aoi_start = next((i for i, line in enumerate(lines) if line.strip() == "[AOIs]"), -1)
    path_start = next((i for i, line in enumerate(lines) if line.strip() == "[AiPaths]"), -1)
    if min(ai_mission, aoi_start, path_start) < 0 or not ai_mission < aoi_start < path_start:
        raise PortError("source mission has no recognizable AiMission/AOIs/AiPaths sections")
    mission = field_value(lines, "dllName", max(0, ai_mission - 5), ai_mission) or ""
    aois = []
    markers = [i for i in range(aoi_start + 1, path_start) if lines[i].strip() == "[AOI]"]
    declared_aois = parse_int(required(lines, "size", aoi_start + 1, path_start))
    if len(markers) != declared_aois:
        raise PortError("ASCII AOI count mismatch")
    for j, start in enumerate(markers):
        end = markers[j + 1] if j + 1 < len(markers) else path_start
        aois.append(AOI(int(required(lines, "path", start, end), 16),
                        parse_int(required(lines, "team", start, end)),
                        bool(parse_int(required(lines, "interesting", start, end))),
                        bool(parse_int(required(lines, "inside", start, end))),
                        parse_int(required(lines, "value", start, end)),
                        parse_int(required(lines, "force", start, end))))
    declared_paths = parse_int(required(lines, "count", path_start + 1, len(lines)))
    starts = [i for i in range(path_start + 1, len(lines))
              if FIELD.match(lines[i]) and FIELD.match(lines[i]).group(1) == "name"
              and field_value(lines, "name", i, min(i + 2, len(lines))) == "AiPath"]
    if len(starts) != declared_paths:
        raise PortError("ASCII AiPath count mismatch")
    paths = []
    for j, start in enumerate(starts):
        end = starts[j + 1] if j + 1 < len(starts) else len(lines)
        point_count = parse_int(required(lines, "pointCount", start, end))
        point_start = next((i for i in range(start, end) if FIELD.match(lines[i])
                            and FIELD.match(lines[i]).group(1) == "points"), -1)
        if point_start < 0:
            raise PortError("ASCII AiPath has no points")
        points = []
        for i in range(point_start + 1, min(end - 2, point_start + point_count * 4 + 1), 4):
            if not (FIELD.match(lines[i]) and FIELD.match(lines[i]).group(1) == "x"
                    and FIELD.match(lines[i + 2]) and FIELD.match(lines[i + 2]).group(1) == "z"):
                break
            points.append((float(lines[i + 1]), float(lines[i + 3])))
        if len(points) != point_count:
            raise PortError("ASCII AiPath point count mismatch")
        paths.append(AiPath(int(required(lines, "sObject", start, end), 16),
                            field_value(lines, "label", start, end) or "", points,
                            int(required(lines, "pathType", start, end), 16)))
    return MissionData(objects, terrain, mission, paths, aois)


def binary_tokens(data: bytes, offset: int) -> list[Token]:
    tokens = []
    while offset < len(data):
        if offset + 3 > len(data):
            raise PortError("truncated binary token header")
        kind = data[offset]
        size = int.from_bytes(data[offset + 1:offset + 3], "little")
        offset += 3
        if kind not in (*range(15), 255) or offset + size > len(data):
            raise PortError(f"invalid BZ2 binary token at byte {offset - 3}")
        tokens.append(Token(kind, data[offset:offset + size]))
        offset += size
    return tokens


def token_string(token: Token) -> str:
    return token.value.split(b"\0", 1)[0].decode("cp1252").strip()


def token_uint(token: Token) -> int:
    return int.from_bytes(token.value, "little")


def sized_string(tokens: list[Token], index: int, version: int) -> tuple[str, int]:
    if version > 1128:
        if tokens[index].kind != 2 or len(tokens[index].value) != 1:
            raise PortError("invalid sized string length")
        length = token_uint(tokens[index])
        index += 1
        if not length:
            return "", index
    if tokens[index].kind != 2:
        raise PortError("invalid sized string value")
    return token_string(tokens[index]), index + 1


def read_binary_mission(data: bytes) -> MissionData:
    match = re.match(rb"version\s+\[1\]\s*=\s*\r?\n(\d+)\r?\n"
                     rb"saveType\s+\[1\]\s*=\s*\r?\n(\d+)\r?\n"
                     rb"binarySave\s+\[1\]\s*=\s*\r?\n(?:1|true)\r?\n", data, re.I)
    if not match:
        raise PortError("binary source must start with a BZ2/BZCC version, saveType and binarySave header")
    version = int(match.group(1))
    if version < 1103:
        raise PortError("binary BZ2 versions before 1103 are not supported; export an ASCII BZN")
    tokens = binary_tokens(data, match.end())
    # Header: msn_filename, seq_count, saveType, terrain, object count.
    index = 0
    _, index = sized_string(tokens, index, version)
    if [tokens[index + j].kind for j in range(4)] != [4, 4, 2, 4]:
        raise PortError("unrecognized binary BZN header")
    terrain = token_string(tokens[index + 2])
    count = token_uint(tokens[index + 3])
    index += 4
    if count > 100000:
        raise PortError("unreasonable object count")
    result = []
    for object_index in range(count):
        try:
            odf, index = sized_string(tokens, index, version)
            seq, team = tokens[index:index + 2]
            expected_team = 2 if version >= 1145 else 4
            if seq.kind != 4 or team.kind != expected_team or len(team.value) != (1 if version >= 1145 else 4):
                raise PortError("invalid object preamble")
            index += 2
            seqno = token_uint(seq)
            if seqno & 0x800000:
                label = ""
            else:
                label, index = sized_string(tokens, index, version)
            expected_user = 1 if version >= 1145 else 4
            if [tokens[index + j].kind for j in range(3)] != [expected_user, 8, 12]:
                raise PortError("invalid object flags/pointer/transform")
            is_user = bool(token_uint(tokens[index]))
            matrix_data = tokens[index + 2].value
            if len(matrix_data) not in (48, 64):
                raise PortError("invalid MAT3D length")
            floats = struct.unpack("<" + "f" * (len(matrix_data) // 4), matrix_data)
            matrix = tuple(floats[j] for j in (0, 1, 2, 4, 5, 6, 8, 9, 10, 12, 13, 14)) if len(floats) == 16 else floats
            index += 3
            result.append(ObjectPlacement(odf, seqno & ~0x800000, token_uint(team),
                                          label, is_user, matrix))
            # The class-specific body has no delimiter in binary. Locate the next
            # preamble by its sized-string/seq/team/label/bool/ptr/matrix signature.
            if object_index + 1 < count:
                index = find_next_preamble(tokens, index, version)
        except (IndexError, struct.error) as exc:
            raise PortError(f"truncated object {object_index + 1}") from exc
    mission, aois, paths = read_binary_tail(tokens, index, version)
    return MissionData(result, terrain, mission, paths, aois)


def read_binary_source(data: bytes) -> list[ObjectPlacement]:
    return read_binary_mission(data).objects


def read_binary_tail(tokens: list[Token], start: int, version: int) -> tuple[str, list[AOI], list[AiPath]]:
    """Locate the BZ2 mission/AOI/path suffix after the variable class bodies."""
    for candidate in range(start, len(tokens)):
        try:
            i = candidate
            if version > 1165:
                if tokens[i].kind != 0 or len(tokens[i].value) != 640:
                    continue
                i += 1
            elif tokens[i].kind != 2 or len(tokens[i].value) != 40:
                continue
            mission, i = sized_string(tokens, i, version)
            if not mission or tokens[i].kind != 4 or len(tokens[i].value) != 4:
                continue
            aoi_count = token_uint(tokens[i]); i += 1
            if aoi_count > 10000:
                continue
            aois = []
            for _ in range(aoi_count):
                if [tokens[i + j].kind for j in range(6)] != [8, 4, 1, 1, 4, 4]:
                    raise PortError("invalid AOI")
                aois.append(AOI(token_uint(tokens[i]), token_uint(tokens[i + 1]),
                                bool(token_uint(tokens[i + 2])), bool(token_uint(tokens[i + 3])),
                                struct.unpack("<i", tokens[i + 4].value)[0], token_uint(tokens[i + 5])))
                i += 6
            if tokens[i].kind != 4 or len(tokens[i].value) != 4:
                continue
            path_count = token_uint(tokens[i]); i += 1
            if path_count > 10000:
                continue
            paths = []
            for _ in range(path_count):
                name, i = sized_string(tokens, i, version)
                if name != "AiPath" or tokens[i].kind != 8:
                    raise PortError("invalid AiPath header")
                old_ptr = token_uint(tokens[i]); i += 1
                if tokens[i].kind != 4:
                    raise PortError("invalid AiPath label length")
                label_length = token_uint(tokens[i]); i += 1
                label = ""
                if label_length:
                    if tokens[i].kind != 2:
                        raise PortError("invalid AiPath label")
                    label = token_string(tokens[i]); i += 1
                if tokens[i].kind != 4 or tokens[i + 1].kind != 10:
                    raise PortError("invalid AiPath points")
                point_count = token_uint(tokens[i]); i += 1
                raw_points = tokens[i].value; i += 1
                if len(raw_points) != point_count * 8:
                    raise PortError("AiPath point count mismatch")
                floats = struct.unpack("<" + "f" * (point_count * 2), raw_points)
                if tokens[i].kind != 0 or len(tokens[i].value) != 4:
                    raise PortError("invalid AiPath type")
                path_type = token_uint(tokens[i]); i += 1
                paths.append(AiPath(old_ptr, label,
                                    [(floats[j], floats[j + 1]) for j in range(0, len(floats), 2)],
                                    path_type))
            return mission, aois, paths
        except (IndexError, PortError, struct.error, UnicodeDecodeError):
            continue
    raise PortError("could not locate mission paths and AOIs in binary source")


def find_next_preamble(tokens: list[Token], start: int, version: int) -> int:
    for i in range(start, len(tokens) - 8):
        try:
            odf, j = sized_string(tokens, i, version)
            if not re.fullmatch(r"[A-Za-z0-9_./\\-]{2,64}", odf):
                continue
            expected_team = 2 if version >= 1145 else 4
            if tokens[j].kind != 4 or tokens[j + 1].kind != expected_team or len(tokens[j + 1].value) != (1 if version >= 1145 else 4):
                continue
            j += 2
            if not token_uint(tokens[j - 2]) & 0x800000:
                _, j = sized_string(tokens, j, version)
            expected_user = 1 if version >= 1145 else 4
            if [tokens[j + k].kind for k in range(3)] == [expected_user, 8, 12] and len(tokens[j + 2].value) in (48, 64):
                return i
        except (IndexError, PortError):
            pass
    raise PortError("could not find the next binary object; try an ASCII BZN")


def source_mission(data: bytes) -> MissionData:
    # One shipped BZCC playground map has a stray leading 'e'.
    if data.startswith(b"eversion [1] ="):
        data = data[1:]
    header = data[:512].decode("cp1252", errors="replace")
    if re.search(r"binarySave\s+\[1\]\s*=\s*\r?\n(?:1|true)\b", header, re.I):
        return read_binary_mission(data)
    return read_ascii_mission(data)


def source_objects(data: bytes) -> list[ObjectPlacement]:
    return source_mission(data).objects


def set_field(lines: list[str], name: str, value: str, occurrence: int = 0) -> bool:
    seen = 0
    for i, line in enumerate(lines):
        match = FIELD.match(line)
        if not match or match.group(1).lower() != name.lower():
            continue
        if seen != occurrence:
            seen += 1
            continue
        if match.group(2) is None:
            lines[i] = line[:match.start(3)] + value
        elif int(match.group(2)) == 1 and i + 1 < len(lines):
            lines[i + 1] = value
        else:
            return False
        return True
    return False


def set_field_at(lines: list[str], index: int, value: str) -> None:
    match = FIELD.match(lines[index])
    if not match:
        raise PortError(f"invalid field at line {index + 1}")
    if match.group(2) is None:
        lines[index] = lines[index][:match.start(3)] + value
    elif match.group(2) == "1" and index + 1 < len(lines):
        lines[index + 1] = value
    else:
        raise PortError(f"cannot replace field at line {index + 1}")


def fmt(value: float) -> str:
    return format(value, ".9g")


def set_vector(lines: list[str], name: str, xyz: tuple[float, ...], occurrence: int = 0) -> bool:
    seen = 0
    for i, line in enumerate(lines):
        match = FIELD.match(line)
        if not match or match.group(1).lower() != name.lower():
            continue
        if seen != occurrence:
            seen += 1
            continue
        if match.group(2) is None:
            return False
        children = {key: fmt(value) for key, value in zip(("x", "y", "z"), xyz)}
        found = set()
        for j in range(i + 1, min(i + 12, len(lines))):
            child = FIELD.match(lines[j])
            if child and child.group(1).lower() in children:
                key = child.group(1).lower()
                if child.group(2) == "1" and j + 1 < len(lines):
                    lines[j + 1] = children[key]
                    found.add(key)
                elif child.group(2) is None:
                    lines[j] = lines[j][:child.start(3)] + children[key]
                    found.add(key)
            elif child and found:
                break
        return found == set(children)
    return False


def set_matrix(lines: list[str], values: tuple[float, ...]) -> bool:
    for i, line in enumerate(lines):
        match = FIELD.match(line)
        if match and match.group(1).lower() == "transform":
            found = set()
            for j in range(i + 1, min(i + 34, len(lines))):
                child = FIELD.match(lines[j])
                if not child:
                    continue
                key = child.group(1).lower().replace("_", ".")
                if key not in MATRIX_KEYS:
                    if found:
                        break
                    continue
                value = fmt(values[MATRIX_KEYS.index(key)])
                if child.group(2) == "1" and j + 1 < len(lines):
                    lines[j + 1] = value
                    found.add(key)
                elif child.group(2) is None:
                    lines[j] = lines[j][:child.start(3)] + value
                    found.add(key)
            return len(found) == 12
    return False


def load_template(data: bytes) -> tuple[list[str], int, int, dict[str, list[str]]]:
    if b"\x00" in data or re.search(rb"binarySave\s+\[1\]\s*=\s*\r?\n(?:1|true)\b", data[:512], re.I):
        raise PortError("Redux template must be saved in ASCII mode")
    lines = text_lines(data)
    version = parse_int(required(lines, "version", 0, min(len(lines), 12)))
    if version < 2000 or field_value(lines, "saveType", 0, 12) is not None:
        raise PortError("template does not look like a BZ98 Redux BZN")
    spans, size, tail = object_spans(lines)
    mission_start = next((i for i in range(tail - 1, max(size, tail - 12), -1)
                          if FIELD.match(lines[i]) and FIELD.match(lines[i]).group(1) == "name"
                          and any(FIELD.match(lines[j]) and FIELD.match(lines[j]).group(1) == "sObject"
                                  for j in range(i + 1, tail))), -1)
    if mission_start < 0:
        raise PortError("Redux template has no recognizable mission name/pointer before [AiMission]")
    if spans:
        spans[-1] = (spans[-1][0], mission_start)
    tail = mission_start
    prototypes = {}
    for start, end in spans:
        block = lines[start:end]
        odf = field_value(block, "PrjID")
        if odf:
            prototypes[odf.casefold()] = block
    if not prototypes:
        raise PortError("template has no [GameObject] prototypes")
    return lines, size, tail, prototypes


def render_aoi(aoi: AOI) -> list[str]:
    return ["[AOI]", f"undefptr = {aoi.path:08X}",
            "team [1] =", str(aoi.team),
            "interesting [1] =", "true" if aoi.interesting else "false",
            "inside [1] =", "true" if aoi.inside else "false",
            "value [1] =", str(aoi.value), "force [1] =", str(aoi.force)]


def render_path(path: AiPath, target_version: int) -> list[str]:
    old_ptr = (f"old_ptr = {path.old_ptr:08X}" if target_version > 2011 else
               f"old_ptr = {struct.pack('<I', path.old_ptr & 0xffffffff).hex()}")
    lines = ["[AiPath]", old_ptr, "size [1] =", str(len(path.label.encode("cp1252")))]
    if path.label:
        lines.append(f"label = {path.label}")
    lines.extend(["pointCount [1] =", str(len(path.points)), f"points [{len(path.points)}] ="])
    for x, z in path.points:
        lines.extend(["  x [1] =", fmt(x), "  z [1] =", fmt(z)])
    lines.append(f"pathType = {struct.pack('<I', path.path_type & 0xffffffff).hex()}")
    return lines


def render_mission_tail(mission: MissionData, target_version: int) -> list[str]:
    lines = ["[AOIs]", "size [1] =", str(len(mission.aois))]
    for aoi in mission.aois:
        lines.extend(render_aoi(aoi))
    lines.extend(["[AiPaths]", "count [1] =", str(len(mission.paths))])
    for path in mission.paths:
        lines.extend(render_path(path, target_version))
    return lines


def apply_offset(mission: MissionData, offset: tuple[float, float, float]) -> None:
    """Move objects and paths into the converted terrain's world frame.

    BZ2/BZCC worlds are usually centred on the origin while Redux terrain
    starts at its TRN MinX/MinZ; the terrain port reports the offset it used.
    """
    dx, dy, dz = offset
    if not (dx or dy or dz):
        return
    for obj in mission.objects:
        m = list(obj.matrix)
        m[9] += dx; m[10] += dy; m[11] += dz
        obj.matrix = tuple(m)
    for path in mission.paths:
        path.points = [(x + dx, z + dz) for x, z in path.points]


def normalize_edge_path(mission: MissionData) -> tuple[AiPath | None, int]:
    """Keep BZR's edge_path at two or four points.

    BZCC maps may repeat the first corner at the end to close a four-corner
    polygon. Only that near-closure case can safely lose a point.
    """
    matches = [path for path in mission.paths if path.label.casefold() == "edge_path"]
    if len(matches) > 1:
        raise PortError("source BZN has multiple edge_path boundaries")
    if not matches:
        return None, 0
    boundary = matches[0]
    source_count = len(boundary.points)
    if source_count == 5:
        xs = [x for x, _ in boundary.points]
        zs = [z for _, z in boundary.points]
        diagonal = math.hypot(max(xs) - min(xs), max(zs) - min(zs))
        closure = math.dist(boundary.points[0], boundary.points[-1])
        if diagonal <= 0 or closure > max(1.0, diagonal * 0.01):
            raise PortError("five-point edge_path does not end near its first corner")
        boundary.points.pop()
    elif source_count not in (2, 4):
        raise PortError(f"Redux edge_path needs 2 or 4 points; source has {source_count}")
    return boundary, source_count


def terrain_report_offset(path: Path) -> tuple[float, float, float]:
    """Read object_offset_m from a WorldBuilder bz2_terrain_port report."""
    value = json.loads(path.read_text(encoding="utf-8")).get("object_offset_m")
    if not (isinstance(value, list) and len(value) == 3):
        raise PortError(f"{path} has no object_offset_m [x, y, z]")
    return tuple(float(v) for v in value)


def convert(source: bytes, template: bytes, mapping: dict, strict: bool,
            terrain_name: str | None = None, mission_name: str | None = None,
            mission_file: str | None = None,
            offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
            skip_reasons: dict[str, str] | None = None,
            team_map: dict[int, int] | None = None) -> tuple[bytes, dict]:
    mission = source_mission(source)
    apply_offset(mission, offset)
    boundary, boundary_source_count = normalize_edge_path(mission)
    team_map = team_map or {}
    applied_team_map = {}
    objects = mission.objects
    lines, size, tail, prototypes = load_template(template)
    target_version = parse_int(required(lines, "version", 0, min(len(lines), 12)))
    output_blocks = []
    skipped = []
    substitutions = {}
    skip_reasons = {k.casefold(): v for k, v in (skip_reasons or {}).items()}
    for obj in objects:
        if obj.odf.casefold() in skip_reasons:
            skipped.append({"source_odf": obj.odf, "target_odf": obj.odf, "prototype": "",
                            "reason": skip_reasons[obj.odf.casefold()]})
            continue
        rule = mapping.get(obj.odf.casefold(), obj.odf)
        if isinstance(rule, str):
            target = rule
            prototype_name = target
        elif isinstance(rule, dict):
            target = rule.get("odf", obj.odf)
            prototype_name = rule.get("prototype", target)
        else:
            raise PortError(f"invalid mapping for {obj.odf!r}")
        prototype = prototypes.get(prototype_name.casefold())
        if prototype is None:
            skipped.append({"source_odf": obj.odf, "target_odf": target,
                            "prototype": prototype_name, "reason": "no Redux prototype"})
            continue
        if len(target.encode("cp1252")) > 8:
            raise PortError(f"Redux PrjID {target!r} exceeds the 8-byte BZN ID limit")
        target_team = redux_team(obj.team, team_map, f"object {obj.label or obj.odf!r}")
        if target_team != obj.team:
            applied_team_map[obj.team] = target_team
        block = prototype.copy()
        # BZ1 stores the sequence number in both the descriptor and object.
        seq = obj.seqno & 0xffff
        edits = (
            set_field(block, "PrjID", target),
            set_field(block, "seqno", str(seq)),
            set_vector(block, "pos", (obj.matrix[9], obj.matrix[10], obj.matrix[11])),
            set_field(block, "team", str(target_team)),
            set_field(block, "label", obj.label[:39]),
            set_field(block, "isUser", "1" if obj.is_user else "0"),
            set_field(block, "obj_addr", "0" * (16 if target_version >= 2012 else 8)),
            set_matrix(block, obj.matrix),
        )
        if not all(edits):
            raise PortError(f"Redux prototype {target!r} lacks a required placement field")
        # The class body may have a second position and sequence number.
        set_vector(block, "pos", (obj.matrix[9], obj.matrix[10], obj.matrix[11]), 1)
        set_field(block, "seqNo", str(obj.seqno), 1)
        output_blocks.extend(block)
        if target.casefold() != obj.odf.casefold() or prototype_name.casefold() != target.casefold():
            key = (obj.odf, target, prototype_name)
            substitutions[key] = substitutions.get(key, 0) + 1
    if strict and skipped:
        names = ", ".join(sorted({f"{row['target_odf']} ({row['reason']})" for row in skipped}))
        raise PortError(f"objects cannot be ported: {names}")
    result = lines[:]
    match = FIELD.match(result[size])
    if not match:
        raise PortError("invalid Redux object count field")
    body_start = size + (2 if match.group(2) == "1" else 1)
    result[body_start:tail] = output_blocks
    if match and match.group(2) == "1":
        result[size + 1] = str(len(objects) - len(skipped))
    elif match:
        result[size] = result[size][:match.start(3)] + str(len(objects) - len(skipped))
    current_seq = field_value(result, "seq_count", 0, size)
    if current_seq is not None and objects:
        next_seq = max(parse_int(current_seq), max(obj.seqno & 0xffff for obj in objects) + 1)
        set_field(result, "seq_count", str(next_seq))
    destination_terrain = terrain_name or mission.terrain
    if destination_terrain and not set_field(result, "TerrainName", destination_terrain):
        raise PortError("Redux template has no TerrainName field")
    if mission_file and not set_field(result, "msn_filename", mission_file):
        raise PortError("Redux template has no msn_filename field")
    if mission_name:
        ai_marker = result.index("[AiMission]")
        name_index = next((i for i in range(ai_marker - 1, max(0, ai_marker - 12), -1)
                           if FIELD.match(result[i]) and FIELD.match(result[i]).group(1) == "name"), -1)
        if name_index < 0:
            raise PortError("Redux template has no mission name")
        set_field_at(result, name_index, mission_name)
    aoi_marker = next((i for i, line in enumerate(result) if line.strip() == "[AOIs]"), -1)
    if aoi_marker < 0:
        raise PortError("Redux template has no AOIs section")
    for aoi in mission.aois:
        target_team = redux_team(aoi.team, team_map, "AOI")
        if target_team != aoi.team:
            applied_team_map[aoi.team] = target_team
        aoi.team = target_team
    result[aoi_marker:] = render_mission_tail(mission, target_version)
    compact_substitutions = [
        {"source_odf": source, "target_odf": target, "prototype": prototype,
         "count": count}
        for (source, target, prototype), count in sorted(substitutions.items())
    ]
    report = {"source_objects": len(objects), "ported_objects": len(objects) - len(skipped),
              "skipped_objects": skipped, "substitutions": compact_substitutions,
              "source_terrain": mission.terrain, "output_terrain": destination_terrain,
              "source_mission": mission.mission,
              "applied_offset_m": list(offset),
              "applied_team_map": {str(source): target for source, target in sorted(applied_team_map.items())},
              "ported_paths": len(mission.paths), "ported_aois": len(mission.aois),
              "boundary_path": ({"name": boundary.label,
                                 "source_point_count": boundary_source_count,
                                 "point_count": len(boundary.points),
                                 "bounds_xz_m": [min(x for x, _ in boundary.points),
                                                 min(z for _, z in boundary.points),
                                                 max(x for x, _ in boundary.points),
                                                 max(z for _, z in boundary.points)]}
                                if boundary else None),
              "note": "Object class state comes from Redux prototypes. Port terrain, ODF/model assets and the mission script separately."}
    return ("\r\n".join(result) + "\r\n").encode("cp1252"), report


# Statuses where an object would be placed with a record or ODF Redux may
# misread. Other unsafe statuses leave the object without a prototype, so it
# is skipped instead.
BLOCKING_CLASS_STATUSES = frozenset({
    "prototype-mismatch", "unknown-prototype", "invalid-redux-label",
    "label-mismatch", "missing-redux-odf", "id-too-long",
})


def class_check(source: bytes, template: bytes, mapping: dict,
                args: argparse.Namespace) -> tuple[dict, dict[str, str]]:
    """Diff source classes against Redux; extend mapping; return skips."""
    if not (args.source_odfs and args.redux_odfs):
        raise PortError("the class check needs both --source-odfs and --redux-odfs")
    diffs = diff_classes([obj.odf for obj in source_mission(source).objects],
                         OdfIndex(args.source_odfs), OdfIndex(args.redux_odfs),
                         load_template(template)[3], mapping, args.allow_approximate)
    skip_reasons = {}
    for diff in diffs:
        if diff.safe and args.auto_map and diff.source_odf not in mapping:
            mapping[diff.source_odf] = {"odf": diff.target_odf, "prototype": diff.prototype}
        elif not diff.safe and diff.status not in BLOCKING_CLASS_STATUSES:
            skip_reasons[diff.source_odf] = f"class check: {diff.status}"
    blocking = [d for d in diffs if d.status in BLOCKING_CLASS_STATUSES]
    if blocking and not args.allow_unsafe_classes:
        print(format_table(diffs), file=sys.stderr)
        raise PortError(f"class check failed for {', '.join(d.source_odf for d in blocking)}; "
                        "fix the Redux ODFs or --map, or pass --allow-unsafe-classes")
    return summary(diffs), skip_reasons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="BZ2/BZCC .bzn")
    parser.add_argument("template", type=Path, help="ASCII BZ98 Redux .bzn with object prototypes")
    parser.add_argument("output", type=Path, help="output Redux .bzn")
    parser.add_argument("--map", dest="mapping", type=Path, help="JSON map of source ODF to Redux PrjID")
    parser.add_argument("--team-map", type=Path, metavar="JSON",
                        help="JSON map of BZCC team numbers to Redux teams 0..15")
    parser.add_argument("--terrain", help="override the source TerrainName")
    parser.add_argument("--mission", help="Redux mission class (for example LuaMission)")
    parser.add_argument("--report", type=Path, help="write a JSON conversion report")
    parser.add_argument("--allow-skips", action="store_true", help="write a partial map when objects lack Redux prototypes")
    parser.add_argument("--offset", nargs=3, type=float, metavar=("X", "Y", "Z"),
                        help="add this world offset to object positions and path points")
    parser.add_argument("--offset-from", type=Path, metavar="PORT_JSON",
                        help="take --offset from a WorldBuilder terrain port report (object_offset_m)")
    parser.add_argument("--source-odfs", type=Path, action="append", metavar="DIR",
                        help="BZ2/BZCC ODF directory for the class check (repeatable; first wins)")
    parser.add_argument("--redux-odfs", type=Path, action="append", metavar="DIR",
                        help="Redux ODF directory for the class check, mod before stock "
                             "(repeatable; first wins). Enables the class check.")
    parser.add_argument("--auto-map", action="store_true",
                        help="pick a class-compatible template prototype for unmapped ODFs")
    parser.add_argument("--allow-approximate", action="store_true",
                        help="let --auto-map use approximate classes (terrain props to buildings)")
    parser.add_argument("--allow-unsafe-classes", action="store_true",
                        help="write the map even when the class check finds unsafe objects")
    args = parser.parse_args(argv)
    try:
        if args.output.resolve() in (args.source.resolve(), args.template.resolve()):
            raise PortError("output must differ from source and template")
        mapping = json.loads(args.mapping.read_text(encoding="utf-8")) if args.mapping else {}
        team_map = parse_team_map(json.loads(args.team_map.read_text(encoding="utf-8"))) if args.team_map else {}
        if not isinstance(mapping, dict) or any(
            not isinstance(k, str) or not (
                isinstance(v, str) or (isinstance(v, dict)
                                       and all(key in ("odf", "prototype") and isinstance(value, str)
                                               for key, value in v.items())))
            for k, v in mapping.items()
        ):
            raise PortError("--map must map ODFs to names or {odf, prototype} objects")
        if args.offset and args.offset_from:
            raise PortError("use either --offset or --offset-from, not both")
        offset = (tuple(args.offset) if args.offset else
                  terrain_report_offset(args.offset_from) if args.offset_from else (0.0, 0.0, 0.0))
        if len(args.output.name.encode("cp1252")) > 16:
            raise PortError("output BZN filename exceeds the 16-byte msn_filename field")
        mapping = {k.casefold(): v for k, v in mapping.items()}
        source, template = args.source.read_bytes(), args.template.read_bytes()
        classes, skip_reasons = None, {}
        if args.redux_odfs or args.auto_map:
            classes, skip_reasons = class_check(source, template, mapping, args)
        output, report = convert(source, template, mapping, not args.allow_skips,
                                 terrain_name=args.terrain, mission_name=args.mission,
                                 mission_file=args.output.name, offset=offset,
                                 skip_reasons=skip_reasons, team_map=team_map)
        if classes is not None:
            report["class_labels"] = classes
        args.output.write_bytes(output)
        if args.report:
            args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Ported {report['ported_objects']}/{report['source_objects']} objects, "
              f"{report['ported_paths']} paths, {report['ported_aois']} AOIs "
              f"to {args.output}")
        if report["skipped_objects"]:
            print(f"Skipped {len(report['skipped_objects'])} objects; see report", file=sys.stderr)
        return 0
    except (OSError, ValueError, PortError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
