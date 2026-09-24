from __future__ import annotations

import os
import re
import shutil
import sys

from bztoolbox.modules.world import legacy_port
from bztoolbox.modules.world.legacy_preflight import validate_legacy_port_folder


def _copy_runtime_support_files(source_dir: os.PathLike | str, output_dir: os.PathLike | str) -> int:
    """Copy runtime companions while excluding legacy conversion-source files."""
    source_dir = os.path.abspath(os.fspath(source_dir))
    output_dir = os.path.abspath(os.fspath(output_dir))
    if os.path.normcase(source_dir) == os.path.normcase(output_dir):
        return 0
    os.makedirs(output_dir, exist_ok=True)

    copied = 0
    for name in sorted(os.listdir(source_dir), key=str.lower):
        source = os.path.join(source_dir, name)
        if not os.path.isfile(source):
            continue
        ext = os.path.splitext(name)[1].lower()
        # HGT/TRN are replaced by generated Redux terrain files. Legacy MAPs
        # are conversion inputs only: Redux TRN .MAP tokens resolve Ogre
        # material names, while the generated material points at PNG/DDS data.
        # The original indexed MAP bytes therefore never belong in the launch
        # folder, including custom sky/cloud/star MAPs.
        if ext in {".hgt", ".trn", ".map", ".exe", ".com"}:
            continue
        destination = os.path.join(output_dir, name)
        if os.path.exists(destination):
            continue
        shutil.copy2(source, destination)
        copied += 1
    return copied


def _runtime_map_refs_from_trn(path: str) -> list[str]:
    """Return non-terrain MAP lookup names exactly as authored in the TRN."""
    refs: list[str] = []
    section = ""
    with open(path, "r", encoding="cp1252", errors="ignore") as stream:
        for raw in stream:
            line = raw.split("//", 1)[0].split(";", 1)[0].strip()
            if not line:
                continue
            match = re.match(r"^\[([^\]]+)\]", line)
            if match:
                section = match.group(1).strip().lower()
                continue
            if re.fullmatch(r"texturetype\d+", section) or "=" not in line:
                continue
            _key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            if value.lower().endswith(".map") and value not in refs:
                refs.append(os.path.basename(value))
    return refs


def _repair_generated_material_names(source_dir: str, output_dir: str) -> int:
    """Make custom Ogre material names match the TRN lookup spelling exactly.

    Legacy packages are often authored on case-insensitive Windows filesystems,
    so a TRN can say `blusky.map` while the physical file is `BLUSKY.MAP`.
    Redux looks these resources up by material name; keeping the TRN spelling is
    deterministic across Windows/Linux and is what the preflight validates.
    """
    repaired = 0
    trns = sorted(
        os.path.join(source_dir, name)
        for name in os.listdir(source_dir)
        if name.lower().endswith(".trn") and os.path.isfile(os.path.join(source_dir, name))
    )
    for trn in trns:
        for reference in _runtime_map_refs_from_trn(trn):
            stem = os.path.splitext(reference)[0].lower()
            candidates = [
                os.path.join(output_dir, stem + ".material"),
                os.path.join(output_dir, stem + "_sky.material"),
            ]
            material_path = next((path for path in candidates if os.path.isfile(path)), None)
            if not material_path:
                continue
            with open(material_path, "r", encoding="utf-8", errors="ignore") as stream:
                text = stream.read()
            rendered, count = re.subn(
                r"(^\s*material\s+)([^\s:{]+)",
                lambda match: match.group(1) + reference,
                text,
                count=1,
                flags=re.IGNORECASE | re.MULTILINE,
            )
            if count and rendered != text:
                with open(material_path, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(rendered)
                repaired += 1
    return repaired


def install_world_builder_legacy_preflight_patch() -> None:
    """Make READY TO LAUNCH depend on a real package preflight."""
    core = sys.modules.get("bztoolbox.modules.world.world_builder_core")
    if core is None:
        return
    base = getattr(core, "BZ98TRNArchitect", None)
    if base is None or getattr(base, "_legacy_preflight_installed", False):
        return

    # finalize_legacy_port_folder resolves this function from the legacy_port
    # module at call time, so replacing it here keeps all legacy MAP conversion
    # sources out of the final launch folder without changing atlas/sky input.
    legacy_port.copy_legacy_support_files = _copy_runtime_support_files

    original_worker = base._generate_legacy_worker

    def generate_legacy_worker_with_preflight(self, src, out):
        original_worker(self, src, out)
        if getattr(self, "legacy_auto_package", None) is None or not self.legacy_auto_package.get():
            return

        try:
            repaired = _repair_generated_material_names(src, out)
            if repaired:
                self.log(
                    f"Legacy materials: normalized {repaired} generated material name(s) to exact TRN spelling.",
                    "success",
                )
        except Exception as exc:
            self.log(f"Legacy material-name normalization failed: {exc}", "warning")

        explicit = self.legacy_pal_path.get().strip() if hasattr(self, "legacy_pal_path") else ""
        try:
            validation = validate_legacy_port_folder(
                src,
                out,
                explicit_palette=explicit or None,
                prepare_extras=True,
                write_report=True,
            )
        except Exception as exc:
            self.log(f"Redux package preflight failed to run: {exc}", "error")
            if hasattr(self, "legacy_package_info"):
                self.legacy_package_info.set(f"PORT NOT READY: preflight failed ({exc})")
            return

        for check in validation.global_checks:
            level = "success" if check.level == "pass" else check.level
            self.log(f"Preflight [{check.code}]: {check.message}", level)
        for mission in validation.missions:
            for check in mission.checks:
                if check.level == "pass":
                    continue
                self.log(
                    f"Preflight {mission.mission} [{check.code}]: {check.message}",
                    check.level,
                )

        report = os.path.basename(validation.report_path) if validation.report_path else "legacy_port_report.txt"
        if validation.ready:
            message = (
                f"PORT COMPLETE - READY TO LAUNCH | {len(validation.missions)} mission(s), "
                f"{validation.warning_count} warning(s) | report: {report}"
            )
            self.log(message, "success")
        else:
            message = (
                f"PORT NOT READY | {validation.error_count} error(s), "
                f"{validation.warning_count} warning(s) | report: {report}"
            )
            self.log(message, "error")

        if hasattr(self, "legacy_package_info"):
            self.legacy_package_info.set(message)

    base._generate_legacy_worker = generate_legacy_worker_with_preflight
    base._legacy_preflight_installed = True
