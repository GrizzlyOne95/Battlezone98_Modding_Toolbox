from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class MissionProfile:
    mission_type: str
    map_type: str
    game_type: str | None = None
    default_max_players: int | None = None


@dataclass(frozen=True)
class LegacyMissionMetadata:
    mission_name: str
    max_players: int | None = None
    legacy_game_type: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class LegacyMissionIniResult:
    bzn_path: str
    ini_path: str | None
    mission_type: str | None
    status: str
    message: str


@dataclass(frozen=True)
class LegacyTrnResult:
    source_path: str
    output_path: str
    status: str


@dataclass(frozen=True)
class LegacyPortSummary:
    copied_files: int
    trn_results: tuple[LegacyTrnResult, ...]
    ini_results: tuple[LegacyMissionIniResult, ...]
    missing_hg2: tuple[str, ...]


MISSION_PROFILES = {
    "MultSTMission": MissionProfile("MultSTMission", "multiplayer", "S", 4),
    "MultDMMission": MissionProfile("MultDMMission", "multiplayer", "D", 8),
    "LuaMission": MissionProfile("LuaMission", "instant_action"),
    "Inst4XMission": MissionProfile("Inst4XMission", "instant_action"),
    "EmptyMission": MissionProfile("EmptyMission", "mod"),
}

# Historical files use both Inst4XMission and Inst4xMission spellings. Mission
# detection is case-insensitive and canonicalizes both forms to Inst4XMission.
_MISSION_ALIASES = {name.lower(): name for name in MISSION_PROFILES}


def _find_file_ci(directory: os.PathLike | str, filename: str) -> str | None:
    directory = os.path.abspath(os.fspath(directory))
    wanted = filename.lower()
    try:
        for name in os.listdir(directory):
            if name.lower() == wanted:
                path = os.path.join(directory, name)
                if os.path.isfile(path):
                    return path
    except OSError:
        pass
    return None


def _same_stem_file(directory: os.PathLike | str, stem: str, extension: str) -> str | None:
    return _find_file_ci(directory, stem + extension)


def detect_bzn_mission_type_bytes(data: bytes) -> str | None:
    """Detect a supported Battlezone mission class from raw BZN bytes.

    The mission class is serialized as a string in both ASCII and binary BZNs,
    so a raw byte scan is more robust for legacy porting than depending on one
    BZN structure version. Unknown files are left unclassified rather than
    guessed. Multiple distinct supported classes are treated as ambiguous.
    """
    lowered = data.lower()
    matches = []
    for alias, canonical in _MISSION_ALIASES.items():
        if alias.encode("ascii") in lowered and canonical not in matches:
            matches.append(canonical)
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError("ambiguous mission classes: " + ", ".join(matches))
    return matches[0]


def detect_bzn_mission_type(path: os.PathLike | str) -> str | None:
    with open(path, "rb") as stream:
        return detect_bzn_mission_type_bytes(stream.read())


def _read_text(path: str) -> str:
    with open(path, "r", encoding="cp1252", errors="ignore") as stream:
        return stream.read()


def _parse_legacy_mad(path: str, stem: str) -> LegacyMissionMetadata | None:
    # netmis/MAD format used by classic multiplayer map packages:
    # map.bzn map.des N N vehicle.txt S Display Name
    pattern = re.compile(
        r"^\s*(\S+\.bzn)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\S+)\s+([A-Za-z])\s+(.+?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    text = _read_text(path)
    for match in pattern.finditer(text):
        bzn_name, _des, count_a, count_b, _vehicles, game_type, display_name = match.groups()
        if os.path.splitext(os.path.basename(bzn_name))[0].lower() != stem.lower():
            continue
        return LegacyMissionMetadata(
            mission_name=display_name.strip(),
            max_players=max(int(count_a), int(count_b)),
            legacy_game_type=game_type.upper(),
            source=os.path.basename(path),
        )
    return None


def _parse_legacy_des(path: str) -> LegacyMissionMetadata | None:
    lines = [line.strip() for line in _read_text(path).splitlines() if line.strip()]
    if not lines:
        return None
    players = None
    for line in lines[1:4]:
        match = re.search(r"\b(\d+)\s*[- ]*players?\b", line, re.IGNORECASE)
        if match:
            players = int(match.group(1))
            break
    return LegacyMissionMetadata(
        mission_name=lines[0],
        max_players=players,
        source=os.path.basename(path),
    )


def _parse_legacy_map_text(path: str, stem: str) -> LegacyMissionMetadata | None:
    text = _read_text(path)
    name_match = re.search(r"^\s*Map\s*:\s*(.+?)\s*$", text, re.IGNORECASE | re.MULTILINE)
    players_match = re.search(r"^\s*Players?\s*:\s*(\d+)\s*$", text, re.IGNORECASE | re.MULTILINE)
    if not name_match and not players_match:
        return None
    return LegacyMissionMetadata(
        mission_name=name_match.group(1).strip() if name_match else stem,
        max_players=int(players_match.group(1)) if players_match else None,
        source=os.path.basename(path),
    )


def resolve_legacy_mission_metadata(
    bzn_path: os.PathLike | str,
    profile: MissionProfile | None = None,
) -> LegacyMissionMetadata:
    """Recover the authored display name/player capacity from classic companions."""
    bzn_path = os.path.abspath(os.fspath(bzn_path))
    directory = os.path.dirname(bzn_path)
    stem = os.path.splitext(os.path.basename(bzn_path))[0]

    mad = _same_stem_file(directory, stem, ".mad")
    des = _same_stem_file(directory, stem, ".des")
    txt = _same_stem_file(directory, stem, ".txt")

    candidates = []
    if mad:
        parsed = _parse_legacy_mad(mad, stem)
        if parsed:
            candidates.append(parsed)
    if des:
        parsed = _parse_legacy_des(des)
        if parsed:
            candidates.append(parsed)
    if txt:
        parsed = _parse_legacy_map_text(txt, stem)
        if parsed:
            candidates.append(parsed)

    name = next((item.mission_name for item in candidates if item.mission_name), stem)
    max_players = next((item.max_players for item in candidates if item.max_players), None)
    legacy_game_type = next((item.legacy_game_type for item in candidates if item.legacy_game_type), None)
    source = next((item.source for item in candidates if item.source), None)

    if max_players is None and profile is not None:
        max_players = profile.default_max_players

    return LegacyMissionMetadata(
        mission_name=name,
        max_players=max_players,
        legacy_game_type=legacy_game_type,
        source=source,
    )


def _sanitize_ini_value(value: str) -> str:
    return value.replace('"', "'").strip() or "Untitled Map"


def render_redux_map_ini(profile: MissionProfile, metadata: LegacyMissionMetadata) -> str:
    """Render a minimal Redux map configuration for a classified mission."""
    lines = [
        "[DESCRIPTION]",
        f'missionName = "{_sanitize_ini_value(metadata.mission_name)}"',
        "",
        "[WORKSHOP]",
        f'mapType = "{profile.map_type}"',
    ]
    if profile.map_type == "multiplayer":
        max_players = metadata.max_players or profile.default_max_players or 4
        lines.extend(
            [
                "",
                "[MULTIPLAYER]",
                'minPlayers = "2"',
                f'maxPlayers = "{max_players}"',
                f'gameType = "{profile.game_type}"',
            ]
        )
    return "\n".join(lines) + "\n"


def generate_redux_ini_for_bzn(
    bzn_path: os.PathLike | str,
    output_dir: os.PathLike | str,
) -> LegacyMissionIniResult:
    """Generate a same-stem Redux INI, preserving an authored INI when present."""
    bzn_path = os.path.abspath(os.fspath(bzn_path))
    output_dir = os.path.abspath(os.fspath(output_dir))
    os.makedirs(output_dir, exist_ok=True)

    directory = os.path.dirname(bzn_path)
    stem = os.path.splitext(os.path.basename(bzn_path))[0]
    source_ini = _same_stem_file(directory, stem, ".ini")
    output_ini = os.path.join(output_dir, stem + ".ini")

    if os.path.isfile(output_ini):
        return LegacyMissionIniResult(
            bzn_path, output_ini, None, "preserved", "existing output INI preserved"
        )
    if source_ini and os.path.normcase(os.path.abspath(source_ini)) != os.path.normcase(output_ini):
        shutil.copy2(source_ini, output_ini)
        return LegacyMissionIniResult(
            bzn_path, output_ini, None, "copied_existing", "existing source INI copied verbatim"
        )

    try:
        mission_type = detect_bzn_mission_type(bzn_path)
    except ValueError as exc:
        return LegacyMissionIniResult(bzn_path, None, None, "ambiguous", str(exc))

    if mission_type is None:
        return LegacyMissionIniResult(
            bzn_path, None, None, "unknown", "no supported mission class string found"
        )

    profile = MISSION_PROFILES[mission_type]
    metadata = resolve_legacy_mission_metadata(bzn_path, profile)
    with open(output_ini, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(render_redux_map_ini(profile, metadata))

    details = [f"{mission_type} -> {profile.map_type}"]
    if profile.game_type:
        details.append(f"gameType={profile.game_type}")
    if metadata.max_players:
        details.append(f"maxPlayers={metadata.max_players}")
    if metadata.mission_name != stem:
        details.append(f'name="{metadata.mission_name}"')
    return LegacyMissionIniResult(
        bzn_path, output_ini, mission_type, "generated", ", ".join(details)
    )


def generate_legacy_bzn_ini_folder(
    source_dir: os.PathLike | str,
    output_dir: os.PathLike | str,
) -> list[LegacyMissionIniResult]:
    source_dir = os.path.abspath(os.fspath(source_dir))
    bzns = sorted(
        os.path.join(source_dir, name)
        for name in os.listdir(source_dir)
        if name.lower().endswith(".bzn") and os.path.isfile(os.path.join(source_dir, name))
    )
    return [generate_redux_ini_for_bzn(path, output_dir) for path in bzns]


def _generated_trn_fragment(output_dir: os.PathLike | str) -> str | None:
    path = os.path.join(os.path.abspath(os.fspath(output_dir)), "TRN_Entries.txt")
    if not os.path.isfile(path):
        return None
    text = _read_text(path)
    match = re.search(r"^\s*\[Atlases\]\s*$", text, re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    return text[match.start():].strip() + "\n"


def rewrite_legacy_trn_text(trn_text: str, redux_fragment: str) -> str:
    """Preserve authored TRN behavior while replacing legacy texture bindings."""
    kept = []
    skip = False
    for raw in trn_text.splitlines(keepends=True):
        section = re.match(r"^\s*\[([^\]]+)\]", raw)
        if section:
            name = section.group(1).strip().lower()
            skip = name == "atlases" or bool(re.fullmatch(r"texturetype\d+", name))
        if not skip:
            kept.append(raw)

    base = "".join(kept).rstrip() + "\n\n"
    return base + redux_fragment.strip() + "\n"


def build_full_redux_trns(
    source_dir: os.PathLike | str,
    output_dir: os.PathLike | str,
) -> list[LegacyTrnResult]:
    """Write complete Redux TRNs instead of a manual TRN_Entries snippet."""
    source_dir = os.path.abspath(os.fspath(source_dir))
    output_dir = os.path.abspath(os.fspath(output_dir))
    os.makedirs(output_dir, exist_ok=True)
    fragment = _generated_trn_fragment(output_dir)

    trn_paths = sorted(
        os.path.join(source_dir, name)
        for name in os.listdir(source_dir)
        if name.lower().endswith(".trn") and os.path.isfile(os.path.join(source_dir, name))
    )
    results = []
    for source_path in trn_paths:
        output_path = os.path.join(output_dir, os.path.basename(source_path))
        text = _read_text(source_path)
        if fragment:
            rendered = rewrite_legacy_trn_text(text, fragment)
            status = "rewritten"
        else:
            rendered = text
            status = "copied_no_atlas_fragment"
        with open(output_path, "w", encoding="cp1252", errors="replace", newline="\n") as stream:
            stream.write(rendered)
        results.append(LegacyTrnResult(source_path, output_path, status))

    entries_path = os.path.join(output_dir, "TRN_Entries.txt")
    if fragment and results and os.path.isfile(entries_path):
        os.remove(entries_path)
    return results


def copy_legacy_support_files(
    source_dir: os.PathLike | str,
    output_dir: os.PathLike | str,
) -> int:
    """Copy mission companions/assets while excluding files replaced by the port."""
    source_dir = os.path.abspath(os.fspath(source_dir))
    output_dir = os.path.abspath(os.fspath(output_dir))
    if os.path.normcase(source_dir) == os.path.normcase(output_dir):
        return 0
    os.makedirs(output_dir, exist_ok=True)

    copied = 0
    for name in sorted(os.listdir(source_dir)):
        source = os.path.join(source_dir, name)
        if not os.path.isfile(source):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in {".hgt", ".trn", ".exe", ".com"}:
            continue
        destination = os.path.join(output_dir, name)
        if os.path.exists(destination):
            continue
        shutil.copy2(source, destination)
        copied += 1
    return copied


def _missing_converted_hg2(
    source_dir: os.PathLike | str,
    output_dir: os.PathLike | str,
) -> tuple[str, ...]:
    missing = []
    for name in os.listdir(source_dir):
        if not name.lower().endswith(".hgt"):
            continue
        stem = os.path.splitext(name)[0]
        expected = _find_file_ci(output_dir, stem + ".hg2")
        if expected is None:
            missing.append(stem + ".hg2")
    return tuple(sorted(missing, key=str.lower))


def finalize_legacy_port_folder(
    source_dir: os.PathLike | str,
    output_dir: os.PathLike | str,
) -> LegacyPortSummary:
    """Turn Legacy Atlas output into a self-contained Redux mission folder."""
    copied = copy_legacy_support_files(source_dir, output_dir)
    trn_results = tuple(build_full_redux_trns(source_dir, output_dir))
    ini_results = tuple(generate_legacy_bzn_ini_folder(source_dir, output_dir))
    missing_hg2 = _missing_converted_hg2(source_dir, output_dir)
    return LegacyPortSummary(copied, trn_results, ini_results, missing_hg2)


def install_world_builder_legacy_package_patch() -> None:
    """Attach full mission-package finalization to the Legacy Atlas page."""
    core = sys.modules.get("bztoolbox.modules.world.world_builder_core")
    if core is None:
        return
    base = getattr(core, "BZ98TRNArchitect", None)
    if base is None or getattr(base, "_legacy_package_port_installed", False):
        return

    original_setup = base.setup_legacy_tab
    original_scan = base.scan_legacy_folder
    original_worker = base._generate_legacy_worker

    def setup_legacy_tab_with_package(self):
        original_setup(self)
        self.legacy_auto_package = core.tk.BooleanVar(value=True)
        self.legacy_package_info = core.tk.StringVar(
            value="Redux mission package: waiting for a legacy source folder."
        )
        frame = core.ttk.LabelFrame(
            self.tab_legacy,
            text=" Launchable Redux Mission Package ",
            padding=10,
        )
        frame.pack(fill="x", padx=20, pady=(0, 10))
        core.ttk.Checkbutton(
            frame,
            text="Build full TRN + Redux INI + copy mission/support files",
            variable=self.legacy_auto_package,
        ).pack(anchor="w")
        core.ttk.Label(
            frame,
            text=(
                "Preserves authored TRN world/sky/fog/size sections, replaces legacy TextureType "
                "bindings with the generated Redux atlas, classifies BZN mission type, and copies "
                "BZN/MAT/LGT/DES/LUA/AIP/ODF/WAV/custom assets into the output folder."
            ),
            foreground="#888888",
            wraplength=1050,
        ).pack(anchor="w", pady=(3, 4))
        core.ttk.Label(
            frame,
            textvariable=self.legacy_package_info,
            foreground=core.BZ_CYAN,
            font=("Consolas", 9),
        ).pack(anchor="w")

    def scan_legacy_folder_with_package(self, path):
        original_scan(self, path)
        if not hasattr(self, "legacy_package_info"):
            return
        try:
            bzns = sorted(name for name in os.listdir(path) if name.lower().endswith(".bzn"))
            if not bzns:
                self.legacy_package_info.set("No BZN found; terrain/atlas assets only.")
                return
            summaries = []
            for name in bzns[:4]:
                bzn_path = os.path.join(path, name)
                try:
                    mission_type = detect_bzn_mission_type(bzn_path) or "unknown"
                    profile = MISSION_PROFILES.get(mission_type)
                    metadata = resolve_legacy_mission_metadata(bzn_path, profile)
                    suffix = f" / {metadata.max_players}p" if metadata.max_players else ""
                    summaries.append(f"{os.path.splitext(name)[0]}={mission_type}{suffix}")
                except Exception as exc:
                    summaries.append(f"{os.path.splitext(name)[0]}=error ({exc})")
            extra = f" +{len(bzns) - 4} more" if len(bzns) > 4 else ""
            self.legacy_package_info.set(
                f"Detected {len(bzns)} BZN mission(s): " + "; ".join(summaries) + extra
            )
        except Exception as exc:
            self.legacy_package_info.set(f"Mission package scan failed: {exc}")

    def generate_legacy_worker_with_package(self, src, out):
        # Let the existing HGT upgrader + atlas converter finish first. Its
        # TRN_Entries file becomes an internal intermediate that we fold back
        # into complete same-stem TRNs below.
        original_worker(self, src, out)
        if getattr(self, "legacy_auto_package", None) is None or not self.legacy_auto_package.get():
            return
        try:
            summary = finalize_legacy_port_folder(src, out)
            for trn in summary.trn_results:
                self.log(
                    f"Legacy TRN: {os.path.basename(trn.source_path)} -> full Redux TRN ({trn.status}).",
                    "success" if trn.status == "rewritten" else "warning",
                )
            for ini in summary.ini_results:
                level = "success" if ini.status in {"generated", "copied_existing", "preserved"} else "warning"
                if ini.ini_path:
                    self.log(
                        f"Redux INI: {os.path.basename(ini.ini_path)} | {ini.message}.",
                        level,
                    )
                else:
                    self.log(
                        f"Redux INI skipped for {os.path.basename(ini.bzn_path)}: {ini.message}.",
                        level,
                    )
            self.log(f"Mission package: copied {summary.copied_files} companion/source asset(s).", "info")
            if summary.missing_hg2:
                self.log(
                    "Mission package WARNING: missing converted HG2: " + ", ".join(summary.missing_hg2),
                    "error",
                )
            else:
                self.log("Mission package ready: all authored HGTs have matching HG2 output.", "success")
        except Exception as exc:
            self.log(f"Mission package finalization failed: {exc}", "error")

    base.setup_legacy_tab = setup_legacy_tab_with_package
    base.scan_legacy_folder = scan_legacy_folder_with_package
    base._generate_legacy_worker = generate_legacy_worker_with_package
    base._legacy_package_port_installed = True
