from __future__ import annotations

import json
import os
import re
import shutil
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

from bztoolbox.modules.world.hg2_codec import DEFAULT_ZONE_BITS, read_hg2_header
from bztoolbox.modules.world.legacy_palette import resolve_legacy_palette, scan_trn_palette_references
from bztoolbox.modules.world.maketrn_compat import METERS_PER_ZONE, read_legacy_trn_zone_geometry
from bztoolbox.modules.world.mission_visualizer import extract_terrain_name


MAT_CELLS_PER_ZONE = 64
MAT_ENTRY_BYTES = 2
_CLASSIC_LGT_ZONE_SIZE = 128
_REDUX_LGT_ZONE_SIZE = 256
_TERRAIN_MAP_RE = re.compile(r"^[A-Za-z]{2}\d\d[scd][A-Za-z]\d\.map$", re.IGNORECASE)
_FILE_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z0-9_./\\-]{1,160}\.(?:"
    r"map|wav|odf|aip|lua|bmp|png|dds|material|act|lum|tbl|alb|geo|xsi|msh|"
    r"trn|hg2|hgt|mat|lgt|des|ini|txt))(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PortCheck:
    level: str
    code: str
    message: str


@dataclass(frozen=True)
class MissionPortValidation:
    mission: str
    terrain: str
    ready: bool
    checks: tuple[PortCheck, ...]


@dataclass(frozen=True)
class LegacyPortValidation:
    ready: bool
    missions: tuple[MissionPortValidation, ...]
    global_checks: tuple[PortCheck, ...]
    palette_file: str | None
    preview_files: tuple[str, ...]
    report_path: str | None = None
    json_path: str | None = None

    @property
    def error_count(self) -> int:
        return sum(
            1
            for check in self.global_checks
            if check.level == "error"
        ) + sum(
            1
            for mission in self.missions
            for check in mission.checks
            if check.level == "error"
        )

    @property
    def warning_count(self) -> int:
        return sum(
            1
            for check in self.global_checks
            if check.level == "warning"
        ) + sum(
            1
            for mission in self.missions
            for check in mission.checks
            if check.level == "warning"
        )


def is_legacy_terrain_map_name(name: os.PathLike | str) -> bool:
    """Return True for classic terrain MAP mip files packed into the Redux atlas."""
    return bool(_TERRAIN_MAP_RE.fullmatch(os.path.basename(os.fspath(name))))


def _find_file_ci(directory: os.PathLike | str, filename: str) -> str | None:
    wanted = os.path.basename(os.fspath(filename)).lower()
    try:
        for name in os.listdir(directory):
            path = os.path.join(os.fspath(directory), name)
            if name.lower() == wanted and os.path.isfile(path):
                return path
    except OSError:
        pass
    return None


def _read_text(path: os.PathLike | str) -> str:
    with open(path, "r", encoding="cp1252", errors="ignore") as stream:
        return stream.read()


def _source_missions(source_dir: str) -> list[str]:
    return sorted(
        (
            name
            for name in os.listdir(source_dir)
            if name.lower().endswith(".bzn") and os.path.isfile(os.path.join(source_dir, name))
        ),
        key=str.lower,
    )


def _terrain_stem_for_bzn(bzn_path: str) -> tuple[str, str | None]:
    mission_stem = os.path.splitext(os.path.basename(bzn_path))[0]
    try:
        terrain = extract_terrain_name(bzn_path)
    except Exception as exc:
        return mission_stem, f"BZN TerrainName could not be parsed ({exc}); using same-stem terrain"
    if not terrain:
        return mission_stem, "BZN does not expose TerrainName; using same-stem terrain"
    terrain = os.path.basename(terrain.strip().strip('"').strip("'"))
    stem, ext = os.path.splitext(terrain)
    if ext.lower() in {".trn", ".hg2", ".hgt", ".mat", ".lgt", ".bzn"}:
        terrain = stem
    return terrain or mission_stem, None


def _atlas_material_name(trn_path: str) -> str | None:
    text = _read_text(trn_path)
    section = ""
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].split(";", 1)[0].strip()
        if not line:
            continue
        match = re.match(r"^\[([^\]]+)\]", line)
        if match:
            section = match.group(1).strip().lower()
            continue
        if section == "atlases" and "=" in line:
            key, value = (part.strip() for part in line.split("=", 1))
            if key.lower() == "materialname" and value:
                return value.strip().strip('"').strip("'")
    return None


def _material_alias(material_path: str, alias: str) -> str | None:
    text = _read_text(material_path)
    match = re.search(
        rf"^\s*set_texture_alias\s+{re.escape(alias)}\s+([^\s;]+)",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if not match:
        return None
    return match.group(1).strip().strip('"').strip("'")


def _material_names(output_dir: str) -> dict[str, set[str]]:
    names: dict[str, set[str]] = {}
    for filename in os.listdir(output_dir):
        if not filename.lower().endswith(".material"):
            continue
        path = os.path.join(output_dir, filename)
        try:
            text = _read_text(path)
        except OSError:
            continue
        for match in re.finditer(r"^\s*material\s+([^\s:{]+)", text, re.IGNORECASE | re.MULTILINE):
            name = match.group(1).strip().strip('"').strip("'")
            names.setdefault(name.lower(), set()).add(name)
    return names


def _validate_mat(path: str, zones_x: int, zones_z: int) -> list[PortCheck]:
    checks: list[PortCheck] = []
    expected = zones_x * zones_z * MAT_CELLS_PER_ZONE * MAT_CELLS_PER_ZONE * MAT_ENTRY_BYTES
    actual = os.path.getsize(path)
    if actual != expected:
        return [
            PortCheck(
                "error",
                "mat-size",
                f"{os.path.basename(path)} is {actual} bytes; expected {expected} for {zones_x}x{zones_z} zones",
            )
        ]

    with open(path, "rb") as stream:
        payload = stream.read()
    invalid_materials: set[int] = set()
    for (value,) in struct.iter_unpack("<H", payload):
        base = (value >> 12) & 0x0F
        next_mat = (value >> 8) & 0x0F
        if base > 7:
            invalid_materials.add(base)
        if next_mat > 7:
            invalid_materials.add(next_mat)
    if invalid_materials:
        checks.append(
            PortCheck(
                "error",
                "mat-material-range",
                f"{os.path.basename(path)} references material IDs outside MakeTRN 0..7: "
                + ", ".join(str(value) for value in sorted(invalid_materials)),
            )
        )
    else:
        checks.append(
            PortCheck(
                "pass",
                "mat",
                f"MAT valid: {actual} bytes, {zones_x * MAT_CELLS_PER_ZONE}x{zones_z * MAT_CELLS_PER_ZONE} cells, material IDs 0..7",
            )
        )
    return checks


def _validate_lgt(path: str, zones_x: int, zones_z: int) -> PortCheck:
    actual = os.path.getsize(path)
    zones = zones_x * zones_z
    classic = (zones + 1) * _CLASSIC_LGT_ZONE_SIZE * _CLASSIC_LGT_ZONE_SIZE
    redux = (zones + 1) * _REDUX_LGT_ZONE_SIZE * _REDUX_LGT_ZONE_SIZE
    if actual == classic:
        return PortCheck(
            "pass",
            "lgt-classic",
            f"LGT valid: classic bordered 128-per-zone layout ({actual} bytes)",
        )
    if actual == redux:
        return PortCheck(
            "pass",
            "lgt-redux",
            f"LGT valid: Redux bordered 256-per-zone layout ({actual} bytes)",
        )
    return PortCheck(
        "error",
        "lgt-size",
        f"{os.path.basename(path)} is {actual} bytes; expected {classic} (classic 128) or {redux} (Redux 256)",
    )


def emit_resolved_palette(
    source_dir: os.PathLike | str,
    output_dir: os.PathLike | str,
    explicit_palette: os.PathLike | str | None = None,
) -> tuple[str | None, PortCheck]:
    """Emit the palette used for MAP decoding so the output package is self-contained."""
    source_dir = os.path.abspath(os.fspath(source_dir))
    output_dir = os.path.abspath(os.fspath(output_dir))
    resolution = resolve_legacy_palette(source_dir, explicit_palette)
    if not resolution.ok or not resolution.path:
        return None, PortCheck("error", "palette", resolution.message)

    references = scan_trn_palette_references(source_dir)
    declared = [value for value in references.values() if value]
    target_name = os.path.basename(declared[0]) if declared else os.path.basename(resolution.path)
    target_path = os.path.join(output_dir, target_name)
    os.makedirs(output_dir, exist_ok=True)

    if os.path.normcase(os.path.abspath(resolution.path)) != os.path.normcase(os.path.abspath(target_path)):
        shutil.copyfile(resolution.path, target_path)

    return target_path, PortCheck(
        "pass",
        "palette",
        f"Palette emitted: {target_name} ({resolution.status}; {resolution.message})",
    )


def convert_legacy_previews(source_dir: os.PathLike | str, output_dir: os.PathLike | str) -> tuple[str, ...]:
    """Convert same-stem legacy BMP mission previews to PNG without altering originals."""
    source_dir = os.path.abspath(os.fspath(source_dir))
    output_dir = os.path.abspath(os.fspath(output_dir))
    made: list[str] = []
    for bzn_name in _source_missions(source_dir):
        stem = os.path.splitext(bzn_name)[0]
        bmp = _find_file_ci(source_dir, stem + ".bmp")
        if not bmp:
            continue
        output = os.path.join(output_dir, stem + "_preview.png")
        try:
            with Image.open(bmp) as image:
                if image.mode not in {"RGB", "RGBA"}:
                    image = image.convert("RGBA")
                image.save(output, format="PNG")
            made.append(output)
        except Exception:
            # Preview conversion is optional and will be reported by the caller if absent.
            continue
    return tuple(made)


def _collect_runtime_refs(trn_path: str, bzn_path: str) -> set[str]:
    refs: set[str] = set()

    # TRN: ignore [TextureTypeN] MAP names because they are atlas cell identifiers
    # after the port, not loose runtime files/material lookups.
    section = ""
    for raw in _read_text(trn_path).splitlines():
        line = raw.split("//", 1)[0].split(";", 1)[0].strip()
        if not line:
            continue
        match = re.match(r"^\[([^\]]+)\]", line)
        if match:
            section = match.group(1).strip().lower()
            continue
        if re.fullmatch(r"texturetype\d+", section):
            continue
        if "=" in line:
            _, value = line.split("=", 1)
            for found in _FILE_REF_RE.findall(value):
                refs.add(os.path.basename(found))
            for numeric_ext in re.findall(r"(?<![A-Za-z0-9_])([A-Za-z0-9_-]+\.0)(?![A-Za-z0-9_])", value):
                refs.add(os.path.basename(numeric_ext))

    # BZN: printable filename strings survive both ASCII and hybrid binary saves.
    try:
        raw = Path(bzn_path).read_bytes().decode("cp1252", errors="ignore")
        for found in _FILE_REF_RE.findall(raw):
            refs.add(os.path.basename(found))
    except OSError:
        pass
    return refs


def _audit_runtime_refs(
    source_dir: str,
    output_dir: str,
    trn_path: str,
    bzn_path: str,
) -> list[PortCheck]:
    checks: list[PortCheck] = []
    material_names = _material_names(output_dir)
    external: list[str] = []

    for ref in sorted(_collect_runtime_refs(trn_path, bzn_path), key=str.lower):
        if _find_file_ci(output_dir, ref):
            continue

        if ref.lower().endswith(".map") and ref.lower() in material_names:
            # Custom legacy MAP converted into a Redux Ogre material using the exact
            # TRN lookup name. Case equality matters here.
            exact = material_names[ref.lower()]
            if ref not in exact:
                checks.append(
                    PortCheck(
                        "error",
                        "material-case",
                        f"TRN references {ref}, but generated material name case is {', '.join(sorted(exact))}",
                    )
                )
            continue

        source = _find_file_ci(source_dir, ref)
        if source:
            checks.append(
                PortCheck(
                    "error",
                    "custom-asset-missing",
                    f"Custom source asset {ref} exists in the legacy package but is missing from output",
                )
            )
        else:
            external.append(ref)

    if external:
        checks.append(
            PortCheck(
                "warning",
                "external-assets",
                "Runtime references not bundled with the legacy map; treating as stock/external dependencies: "
                + ", ".join(external),
            )
        )
    else:
        checks.append(PortCheck("pass", "runtime-assets", "All discovered custom runtime references resolve locally"))
    return checks


def _validate_one_mission(source_dir: str, output_dir: str, bzn_name: str) -> MissionPortValidation:
    checks: list[PortCheck] = []
    mission_stem = os.path.splitext(bzn_name)[0]
    source_bzn = os.path.join(source_dir, bzn_name)
    terrain_stem, terrain_warning = _terrain_stem_for_bzn(source_bzn)
    if terrain_warning:
        checks.append(PortCheck("warning", "terrain-name", terrain_warning))

    for extension, label in ((".bzn", "BZN"), (".ini", "Redux INI")):
        path = _find_file_ci(output_dir, mission_stem + extension)
        if path:
            checks.append(PortCheck("pass", label.lower().replace(" ", "-"), f"{label}: {os.path.basename(path)}"))
        else:
            checks.append(PortCheck("error", label.lower().replace(" ", "-"), f"Missing launch-critical {mission_stem + extension}"))

    trn = _find_file_ci(output_dir, terrain_stem + ".trn")
    if not trn:
        checks.append(PortCheck("error", "trn", f"Missing launch-critical {terrain_stem}.trn"))
        return MissionPortValidation(mission_stem, terrain_stem, False, tuple(checks))

    try:
        zones_x, zones_z = read_legacy_trn_zone_geometry(trn)
        checks.append(
            PortCheck(
                "pass",
                "trn",
                f"TRN valid: {os.path.basename(trn)}, {zones_x}x{zones_z} zones ({zones_x * int(METERS_PER_ZONE)}x{zones_z * int(METERS_PER_ZONE)})",
            )
        )
    except Exception as exc:
        checks.append(PortCheck("error", "trn", f"TRN geometry invalid: {exc}"))
        return MissionPortValidation(mission_stem, terrain_stem, False, tuple(checks))

    hg2 = _find_file_ci(output_dir, terrain_stem + ".hg2")
    if not hg2:
        checks.append(PortCheck("error", "hg2", f"Missing launch-critical {terrain_stem}.hg2"))
    else:
        try:
            header = read_hg2_header(hg2)
            if header.zone_bits != DEFAULT_ZONE_BITS:
                checks.append(PortCheck("error", "hg2", f"HG2 zone_bits={header.zone_bits}; expected {DEFAULT_ZONE_BITS}"))
            elif (header.zones_x, header.zones_z) != (zones_x, zones_z):
                checks.append(
                    PortCheck(
                        "error",
                        "hg2",
                        f"HG2 is {header.zones_x}x{header.zones_z} zones but TRN is {zones_x}x{zones_z}",
                    )
                )
            else:
                checks.append(
                    PortCheck(
                        "pass",
                        "hg2",
                        f"HG2 valid: {header.zones_x}x{header.zones_z} zones, {1 << header.zone_bits} samples/zone",
                    )
                )
        except Exception as exc:
            checks.append(PortCheck("error", "hg2", f"HG2 parse failed: {exc}"))

    mat = _find_file_ci(output_dir, terrain_stem + ".mat")
    if not mat:
        checks.append(PortCheck("error", "mat", f"Missing launch-critical {terrain_stem}.mat"))
    else:
        checks.extend(_validate_mat(mat, zones_x, zones_z))

    source_lgt = _find_file_ci(source_dir, terrain_stem + ".lgt")
    lgt = _find_file_ci(output_dir, terrain_stem + ".lgt")
    if lgt:
        checks.append(_validate_lgt(lgt, zones_x, zones_z))
    elif source_lgt:
        checks.append(PortCheck("error", "lgt", f"Legacy package supplied {terrain_stem}.lgt but it is missing from output"))
    else:
        checks.append(
            PortCheck(
                "warning",
                "lgt",
                "No LGT supplied. Redux can regenerate lighting, but this output does not preserve authored legacy lighting.",
            )
        )

    atlas_material = _atlas_material_name(trn)
    if not atlas_material:
        checks.append(PortCheck("error", "atlas", "TRN has no [Atlases] MaterialName binding"))
    else:
        material = _find_file_ci(output_dir, atlas_material + ".material")
        csv = _find_file_ci(output_dir, atlas_material + ".csv")
        if not material:
            checks.append(PortCheck("error", "atlas-material", f"Missing {atlas_material}.material"))
        if not csv:
            checks.append(PortCheck("error", "atlas-csv", f"Missing {atlas_material}.csv"))
        if material:
            diffuse = _material_alias(material, "DiffuseMap")
            if not diffuse:
                checks.append(PortCheck("error", "atlas-texture", f"{os.path.basename(material)} has no DiffuseMap alias"))
            elif not _find_file_ci(output_dir, diffuse):
                checks.append(PortCheck("error", "atlas-texture", f"Atlas texture {diffuse} referenced by material is missing"))
            else:
                checks.append(
                    PortCheck(
                        "pass",
                        "atlas",
                        f"Atlas chain valid: {atlas_material} -> {os.path.basename(csv or '')} + {diffuse}",
                    )
                )

    output_bzn = _find_file_ci(output_dir, mission_stem + ".bzn") or source_bzn
    checks.extend(_audit_runtime_refs(source_dir, output_dir, trn, output_bzn))
    ready = not any(check.level == "error" for check in checks)
    return MissionPortValidation(mission_stem, terrain_stem, ready, tuple(checks))


def _render_report(validation: LegacyPortValidation) -> str:
    lines = [
        "Battlezone98Redux WorldBuilder - Legacy Port Report",
        "=" * 57,
        f"STATUS: {'READY TO LAUNCH' if validation.ready else 'NOT READY'}",
        f"Errors: {validation.error_count}",
        f"Warnings: {validation.warning_count}",
        "",
    ]
    if validation.palette_file:
        lines.append(f"Palette: {os.path.basename(validation.palette_file)}")
    if validation.preview_files:
        lines.append("Preview PNG: " + ", ".join(os.path.basename(path) for path in validation.preview_files))
    if validation.global_checks:
        lines.extend(["", "Package checks", "--------------"])
        for check in validation.global_checks:
            lines.append(f"[{check.level.upper()}] {check.message}")
    for mission in validation.missions:
        lines.extend(
            [
                "",
                f"Mission: {mission.mission}",
                f"Terrain: {mission.terrain}",
                f"Status: {'READY' if mission.ready else 'NOT READY'}",
                "-" * 40,
            ]
        )
        for check in mission.checks:
            lines.append(f"[{check.level.upper()}] {check.message}")
    return "\n".join(lines).rstrip() + "\n"


def _validation_dict(validation: LegacyPortValidation) -> dict:
    return {
        "ready": validation.ready,
        "error_count": validation.error_count,
        "warning_count": validation.warning_count,
        "palette_file": validation.palette_file,
        "preview_files": list(validation.preview_files),
        "global_checks": [asdict(check) for check in validation.global_checks],
        "missions": [
            {
                "mission": mission.mission,
                "terrain": mission.terrain,
                "ready": mission.ready,
                "checks": [asdict(check) for check in mission.checks],
            }
            for mission in validation.missions
        ],
    }


def validate_legacy_port_folder(
    source_dir: os.PathLike | str,
    output_dir: os.PathLike | str,
    *,
    explicit_palette: os.PathLike | str | None = None,
    prepare_extras: bool = True,
    write_report: bool = True,
) -> LegacyPortValidation:
    """Validate a converted legacy folder before WorldBuilder calls it launchable."""
    source_dir = os.path.abspath(os.fspath(source_dir))
    output_dir = os.path.abspath(os.fspath(output_dir))
    os.makedirs(output_dir, exist_ok=True)

    global_checks: list[PortCheck] = []
    palette_file: str | None = None
    preview_files: tuple[str, ...] = ()

    if prepare_extras:
        palette_file, palette_check = emit_resolved_palette(source_dir, output_dir, explicit_palette)
        global_checks.append(palette_check)
        preview_files = convert_legacy_previews(source_dir, output_dir)
        if preview_files:
            global_checks.append(
                PortCheck(
                    "pass",
                    "preview",
                    "Converted legacy preview BMP(s): "
                    + ", ".join(os.path.basename(path) for path in preview_files),
                )
            )

    missions = tuple(
        _validate_one_mission(source_dir, output_dir, bzn_name)
        for bzn_name in _source_missions(source_dir)
    )
    if not missions:
        global_checks.append(PortCheck("error", "missions", "No BZN missions found in source folder"))

    ready = (
        bool(missions)
        and all(mission.ready for mission in missions)
        and not any(check.level == "error" for check in global_checks)
    )
    validation = LegacyPortValidation(
        ready=ready,
        missions=missions,
        global_checks=tuple(global_checks),
        palette_file=palette_file,
        preview_files=preview_files,
    )

    if not write_report:
        return validation

    report_path = os.path.join(output_dir, "legacy_port_report.txt")
    json_path = os.path.join(output_dir, "legacy_port_report.json")
    with open(report_path, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(_render_report(validation))
    with open(json_path, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(_validation_dict(validation), stream, indent=2)
        stream.write("\n")

    return LegacyPortValidation(
        ready=validation.ready,
        missions=validation.missions,
        global_checks=validation.global_checks,
        palette_file=validation.palette_file,
        preview_files=validation.preview_files,
        report_path=report_path,
        json_path=json_path,
    )


def render_validation_report(validation: LegacyPortValidation) -> str:
    return _render_report(validation)
