"""Import the standalone Battlezone tool repositories into the unified toolbox.

This is the reproducible, mechanical first step of the consolidation. It
copies each legacy repository's sources into its new package location and
rewrites the flat ``import foo`` / ``from foo import bar`` statements the
standalone apps relied on into package imports. Nothing else about the code
is changed here; behaviour-level adaptations (embedding in the shell,
resource lookups) are made by hand afterwards and live in normal commits.

Usage::

    python scripts/migration/import_legacy_tools.py <dir-containing-clones> [--only NAME ...]

``<dir-containing-clones>`` must contain a clone of every repository listed in
``TOOLS`` (directory name == repository name). Re-running the script
overwrites the imported files, so only use it before the manual adaptation
commits, or to diff an upstream change against the imported copy.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Flat module name -> fully-qualified module in the unified tree. Shared by
# every tool so cross-tool references (e.g. odf_validator) resolve to the one
# shared copy in ``battlezone``.
CORE_MODULES = {
    "odf_validator": "battlezone.odf.validator",
    "odf_schema": "battlezone.odf.schema",
    "odf_evidence": "battlezone.odf.evidence",
    "odf_inheritance": "battlezone.odf.inheritance",
    "class_labels": "battlezone.odf.class_labels",
    "bzcc_port": "battlezone.bzn.bzcc_port",
}


@dataclass
class Tool:
    repo: str
    package: str                      # e.g. bztoolbox.modules.world
    # source path (relative to repo) -> destination path relative to package dir
    files: dict[str, str] = field(default_factory=dict)
    # flat module name -> destination module path relative to package
    modules: dict[str, str] = field(default_factory=dict)
    # source files copied verbatim (no import rewriting), e.g. Blender scripts
    verbatim: dict[str, str] = field(default_factory=dict)
    tests: dict[str, str] = field(default_factory=dict)   # src -> tests/<name>/...
    docs: dict[str, str] = field(default_factory=dict)    # src -> repo-relative dest
    prefixes: dict[str, str] = field(default_factory=dict)  # package-name prefix remaps

    @property
    def package_dir(self) -> Path:
        return REPO_ROOT / Path(*self.package.split("."))


def _py(names: list[str]) -> dict[str, str]:
    return {f"{n}.py": f"{n}.py" for n in names}


def build_tools() -> list[Tool]:
    tools: list[Tool] = []

    # --- BZN Toolbox -> Missions (+ shared ODF/BZN core) -------------------
    t = Tool("Battlezone98Redux_BZN_Toolbox", "bztoolbox.modules.missions")
    t.files = {"toolbox_app.py": "toolbox_app.py",
               "icon.ico": "icon.ico",
               "branding/app_icon.ico": "branding/app_icon.ico",
               "branding/app_icon.png": "branding/app_icon.png"}
    t.modules = {"toolbox_app": "toolbox_app", "bzn_scan": "bzn_scan"}
    t.tests = {f"tests/{n}": f"tests/missions/{n}" for n in (
        "test_bzcc_port.py", "test_class_labels.py", "test_odf_inheritance.py",
        "test_odf_inheritance_edges.py", "test_odf_mined_rules.py", "test_odf_provenance.py",
        "test_odf_schema_safety.py", "test_odf_validator.py", "test_toolbox_port.py")}
    t.docs = {"docs/BZCC_TO_BZR_PORT.md": "docs/missions/BZCC_TO_BZR_PORT.md",
              "docs/ODF_VALIDATION_SCHEMA.md": "docs/missions/ODF_VALIDATION_SCHEMA.md",
              "docs/examples/isdf01_mapping.json": "docs/missions/examples/isdf01_mapping.json",
              "docs/examples/isdf01_team_mapping.json": "docs/missions/examples/isdf01_team_mapping.json",
              "README.md": "docs/missions/README.md"}
    tools.append(t)

    # --- WorldBuilder -> World & Terrain ----------------------------------
    wb_modules = [
        "bz2_atlas_port", "bz2_mat_encoder", "bz2_mat_reducer", "bz2_pak", "bz2_ter_codec",
        "bz2_terrain_bundle", "bz2_terrain_port", "bz2_texture_blend", "bz2_texture_resolver",
        "bzpaint", "custom_atlas_builder", "hg2_codec", "legacy_batch", "legacy_batch_gui",
        "legacy_palette", "legacy_port", "legacy_port_cli", "legacy_preflight",
        "legacy_preflight_hook", "maketrn_compat", "map_preview", "mat_codec",
        "mission_visualizer", "msn2terrain", "msn_ter_codec", "stock_map_creator",
        "stock_palettes", "terrain_obj", "world_builder", "world_builder_core",
    ]
    t = Tool("Battlezone98Redux_WorldBuilder", "bztoolbox.modules.world")
    t.files = {**_py(wb_modules), "BZONE.ttf": "BZONE.ttf", "wb.ico": "wb.ico",
               "branding/app_icon.ico": "branding/app_icon.ico",
               "branding/app_icon.png": "branding/app_icon.png"}
    t.modules = {n: n for n in wb_modules}
    t.tests = {f"tests/{n}": f"tests/world/{n}" for n in (
        "test_bz2_atlas_port.py", "test_bz2_mat_encoder.py", "test_bz2_mat_reducer.py",
        "test_bz2_pak.py", "test_bz2_terrain_bundle.py", "test_bz2_terrain_port.py",
        "test_bz2_texture_blend.py", "test_bz2_texture_resolver.py", "test_bzpaint_cli.py",
        "test_custom_atlas_builder.py", "test_hg2_codec.py", "test_legacy_batch.py",
        "test_legacy_palette.py", "test_legacy_port.py", "test_legacy_preflight.py",
        "test_maketrn_compat.py", "test_map_preview.py", "test_mat_codec.py",
        "test_mission_visualizer.py", "test_msn2terrain.py", "test_msn_ter_codec.py",
        "test_stock_map_creator.py", "test_stock_palettes.py", "test_terrain_obj.py")}
    t.docs = {"README.md": "docs/world/README.md"}
    for n in ("BZ2_TO_BZR_PORT.md", "LEGACY_PORT_CLI.md", "MAKETRN_REVERSE_ENGINEERING.md",
              "MAT_FORMAT_VALIDATION.md"):
        t.docs[f"docs/{n}"] = f"docs/world/{n}"
    tools.append(t)

    # --- HeightmapGen -> World & Terrain / Generate -----------------------
    t = Tool("Battlezone98Redux_HeightmapGen", "bztoolbox.modules.terrain_generator")
    hm = ["__init__", "analysis", "approved_planetary", "builder", "contrast", "gui", "gui_logic",
          "hg2", "hgt", "lgt", "natural_finish", "noise", "planetary", "planetary_detail",
          "planetary_surface", "preview", "recipes", "settings", "stock_detail",
          "stock_detail_v2", "stock_detail_v5", "urban"]
    t.files = {f"bzr_heightmap/{n}.py": f"{n}.py" for n in hm}
    t.files.update({"heightmap_generator.py": "cli.py",
                    "bzr_heightmap.ico": "bzr_heightmap.ico",
                    "branding/app_icon.ico": "branding/app_icon.ico",
                    "branding/app_icon.png": "branding/app_icon.png"})
    for n in ("analyze_local_corpus", "audit_all_natural", "audit_stock_detail",
              "convert_legacy_hgt", "generate_planetary_samples", "generate_samples"):
        t.files[f"scripts/{n}.py"] = f"research/{n}.py"
    t.modules = {"heightmap_generator": "cli"}
    t.prefixes = {"bzr_heightmap": "", "scripts": "research"}
    t.tests = {f"tests/{n}": f"tests/terrain_generator/{n}" for n in (
        "test_contrast_preview.py", "test_corpus_gui_logic.py", "test_heightmap_generator.py",
        "test_hg2.py", "test_hgt.py", "test_lgt.py", "test_natural_finish.py",
        "test_planetary_detail.py", "test_planetary_surface.py", "test_stock_detail.py")}
    t.docs = {f"docs/{n}": f"docs/terrain_generator/{n}" for n in (
        "BZMAPIO_AUTHORING_REFERENCE.md", "HG2_CORPUS_ANALYSIS_20260828.md",
        "HG2_CORPUS_SUMMARY.md", "LEGACY_HGT_TO_HG2.md")}
    t.docs["README.md"] = "docs/terrain_generator/README.md"
    tools.append(t)

    # --- Localization Tool -> Project / Localization ----------------------
    t = Tool("Battlezone98Redux_LocalizationTool", "bztoolbox.modules.localization")
    t.files = {"localization.py": "localization.py", "bzlocal.ico": "bzlocal.ico",
               "BZONE.ttf": "BZONE.ttf",
               "branding/app_icon.ico": "branding/app_icon.ico",
               "branding/app_icon.png": "branding/app_icon.png"}
    t.modules = {"localization": "localization"}
    t.tests = {"tests/test_localization.py": "tests/localization/test_localization.py"}
    t.docs = {"README.md": "docs/localization/README.md",
              "THIRD_PARTY_NOTICES.md": "docs/localization/THIRD_PARTY_NOTICES.md"}
    tools.append(t)

    # --- Workshop Uploader -> Project / Publish ---------------------------
    wu = ["app_file_manager", "content_fixes", "memory_analyzer", "mod_scanner", "project_store",
          "steam_service", "steamworks_tags", "upload_preflight", "uploader", "workshop_backend"]
    t = Tool("Battlezone98Redux_WorkshopUploader", "bztoolbox.modules.publishing")
    t.files = {**_py(wu), "bzrODFparams.txt": "bzrODFparams.txt",
               "odfHeaderList.txt": "odfHeaderList.txt", "icon.ico": "icon.ico",
               "BZONE.ttf": "BZONE.ttf",
               "branding/app_icon.ico": "branding/app_icon.ico",
               "branding/app_icon.png": "branding/app_icon.png"}
    t.modules = {n: n for n in wu}
    t.tests = {"tests/test_uploader.py": "tests/publishing/test_uploader.py"}
    t.docs = {"README.md": "docs/publishing/README.md"}
    tools.append(t)

    # --- HoloTextGen -> Assets / Holographic Text -------------------------
    t = Tool("Battlezone98Redux_HoloTextGen", "bztoolbox.modules.holotext")
    t.files = {"hud_gen.py": "hud_gen.py", "BZONE.ttf": "BZONE.ttf", "icon.ico": "icon.ico"}
    t.modules = {"hud_gen": "hud_gen"}
    t.docs = {"README.md": "docs/holotext/README.md"}
    tools.append(t)

    # --- Font Generator -> Assets / Fonts ---------------------------------
    t = Tool("Battlezone98ReduxFontGenerator", "bztoolbox.modules.fonts")
    t.files = {"bz_generator.py": "bz_generator.py", "BZONE.ttf": "BZONE.ttf",
               "Orbitron-Bold.ttf": "Orbitron-Bold.ttf", "icon.ico": "icon.ico",
               "tools/dump_bzfont_st.py": "dump_bzfont_st.py",
               "branding/app_icon.ico": "branding/app_icon.ico",
               "branding/app_icon.png": "branding/app_icon.png"}
    t.modules = {"bz_generator": "bz_generator", "dump_bzfont_st": "dump_bzfont_st"}
    t.docs = {"README.md": "docs/fonts/README.md"}
    tools.append(t)

    # --- OgreMeshTools -> Assets / Meshes ---------------------------------
    t = Tool("Battlezone98Redux_OgreMeshTools", "bztoolbox.modules.meshes")
    t.files = {**_py(["MeshToObj", "ogre_mesh_tools_gui", "ogre_preview", "recalculate_normals"]),
               "BZONE.ttf": "BZONE.ttf", "BZBase.material": "BZBase.material",
               "icon.ico": "icon.ico",
               "branding/app_icon.ico": "branding/app_icon.ico",
               "branding/app_icon.png": "branding/app_icon.png"}
    # Ogre command-line helpers are Windows binaries shipped with the tool.
    for n in ("OgreMain.dll", "OgreMeshLodGenerator.dll", "OgreMeshMagick.exe",
              "OgreMeshUpgrader.exe", "OgreXMLConverter.exe", "zlib.dll"):
        t.files[n] = f"bin/{n}"
    # Blender runs these as standalone scripts (blender -b -P ...): keep them
    # byte-for-byte, including their own sys.path handling.
    t.verbatim = {"batch_ogre_to_gltf.py": "blender/batch_ogre_to_gltf.py",
                  "OgreImport.py": "blender/OgreImport.py"}
    t.modules = {n: n for n in ("MeshToObj", "ogre_mesh_tools_gui", "ogre_preview",
                                 "recalculate_normals")}
    t.docs = {"README.md": "docs/meshes/README.md", "HEALTH_CHECK.md": "docs/meshes/HEALTH_CHECK.md"}
    tools.append(t)

    # --- ZFS Specialist -> Archives (GPL-2.0 component) -------------------
    t = Tool("Battlezone98Redux_ZFSSpecialist", "bztoolbox.modules.zfs")
    t.files = {"src/unzfs.py": "unzfs.py", "zfs.ico": "zfs.ico", "BZONE.ttf": "BZONE.ttf",
               "LICENSE": "LICENSE",
               "dll_source/lzo_bridge.dll": "native/lzo_bridge.dll",
               "dll_source/bridge.cpp": "native/bridge.cpp"}
    t.modules = {"unzfs": "unzfs"}
    t.docs = {"README.md": "docs/zfs/README.md", "CHANGELOG.md": "docs/zfs/CHANGELOG.md"}
    tools.append(t)

    # --- TextureManager -> Assets / Textures ------------------------------
    tm = ["bc1", "bcpack", "makemap_compat", "recompress", "stock_palettes", "tex_man",
          "tex_man_entry", "tex_man_stock_palette_entry", "uiscan"]
    t = Tool("Battlezone98Redux_TextureManager", "bztoolbox.modules.textures")
    t.files = {f"src/{n}.py": f"{n}.py" for n in tm}
    t.files.update({"bzrtex.ico": "bzrtex.ico", "BZONE.ttf": "BZONE.ttf",
                    "branding/app_icon.ico": "branding/app_icon.ico",
                    "branding/app_icon.png": "branding/app_icon.png"})
    t.modules = {n: n for n in tm}
    t.tests = {f"tests/{n}": f"tests/textures/{n}" for n in (
        "test_makemap_compat.py", "test_stock_palettes.py")}
    t.docs = {"README.md": "docs/textures/README.md",
              "docs/MAKEMAP_COMPATIBILITY.md": "docs/textures/MAKEMAP_COMPATIBILITY.md"}
    tools.append(t)

    # --- AudioTool -> Assets / Audio --------------------------------------
    t = Tool("Battlezone98Redux_AudioTool", "bztoolbox.modules.audio")
    t.files = {"audio.py": "audio.py", "commbeep.wav": "commbeep.wav",
               "unitbeep.wav": "unitbeep.wav", "bzradio.ico": "bzradio.ico",
               "BZONE.ttf": "BZONE.ttf",
               "branding/app_icon.ico": "branding/app_icon.ico",
               "branding/app_icon.png": "branding/app_icon.png"}
    t.modules = {"audio": "audio"}
    t.docs = {"README.md": "docs/audio/README.md"}
    tools.append(t)
    return tools


# ---------------------------------------------------------------------------
# Import rewriting
# ---------------------------------------------------------------------------

_IMPORT_RE = re.compile(r"^(?P<indent>[ \t]*)import (?P<body>[A-Za-z_][\w., \t]*?)(?P<trail>[ \t]*(#.*)?)$")
_FROM_RE = re.compile(r"^(?P<indent>[ \t]*)from (?P<mod>[A-Za-z_][\w.]*) import (?P<rest>.*)$")
_STRING_REF_RE = re.compile(
    r"(?P<pre>(?:patch|sys\.modules\.get|sys\.modules\[|import_module)\(?\s*)"
    r"(?P<q>[\"'])(?P<mod>[A-Za-z_]\w*)(?P<tail>(?:\.[\w.]*)?)(?P=q)")


def _resolve(name: str, table: dict[str, str], prefixes: dict[str, str], package: str) -> str | None:
    head, _, rest = name.partition(".")
    if head in table and not rest:
        return table[head]
    if head in table and rest:
        return f"{table[head]}.{rest}"
    if head in prefixes:
        base = package if not prefixes[head] else f"{package}.{prefixes[head]}"
        return f"{base}.{rest}" if rest else base
    return None


def rewrite_imports(text: str, table: dict[str, str], prefixes: dict[str, str], package: str) -> str:
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        eol = "\n" if line.endswith("\n") else ""
        raw = line[:-1] if eol else line
        m = _FROM_RE.match(raw)
        if m:
            target = _resolve(m["mod"], table, prefixes, package)
            if target:
                raw = f"{m['indent']}from {target} import {m['rest']}"
            out.append(raw + eol)
            continue
        m = _IMPORT_RE.match(raw)
        if m and not raw.lstrip().startswith("import *"):
            parts = [p.strip() for p in m["body"].split(",")]
            if any(_resolve(p.split(" as ")[0].strip(), table, prefixes, package) for p in parts):
                lines = []
                for part in parts:
                    name, _, alias = (s.strip() for s in part.partition(" as "))
                    target = _resolve(name, table, prefixes, package)
                    if not target:
                        lines.append(f"{m['indent']}import {part}")
                        continue
                    if "." in name and not alias:
                        # ``import pkg.mod`` binds ``pkg``; keep that binding.
                        head = name.split(".")[0]
                        lines.append(f"{m['indent']}import {target}")
                        lines.append(f"{m['indent']}{head} = sys.modules[{_resolve(head, table, prefixes, package)!r}]")
                        continue
                    parent, _, leaf = target.rpartition(".")
                    bind = alias or name
                    suffix = "" if bind == leaf else f" as {bind}"
                    lines.append(f"{m['indent']}from {parent} import {leaf}{suffix}")
                lines[-1] += m["trail"] or ""
                out.append("\n".join(lines) + eol)
                continue
        # String references used by mock.patch / sys.modules lookups.
        def _sub(sm: re.Match) -> str:
            target = _resolve(sm["mod"], table, prefixes, package)
            if not target:
                return sm.group(0)
            return f"{sm['pre']}{sm['q']}{target}{sm['tail']}{sm['q']}"
        out.append(_STRING_REF_RE.sub(_sub, raw) + eol)
    return "".join(out)


def split_bzn_scan(src: Path) -> tuple[str, str]:
    """Split bzn_scan.py into the GUI-free core and the Tk analyzer window."""
    text = src.read_text(encoding="utf-8")
    marker = "class BZNAnalyzer:"
    core, gui = text.split(marker, 1)
    core = core.replace("import tkinter as tk\n", "").replace(
        "from tkinter import filedialog, messagebox, ttk\n", "")
    core = ('"""BZN dependency scanning: stock ODF list and ASCII/binary BZN parser.\n\n'
            "Extracted unchanged from the BZN Toolbox ``bzn_scan`` module.\n\"\"\"\n") + core.rstrip() + "\n"
    gui = ("import os\nimport tkinter as tk\nfrom tkinter import filedialog, messagebox, ttk\n\n"
           "from battlezone.bzn.scan import (  # noqa: F401 - re-exported for legacy callers\n"
           "    STOCK_ODF_LIST, STOCK_SET, BinaryFieldType, BZNParser,\n)\n\n\n" + marker + gui)
    return core, gui


def import_tool(tool: Tool, src_root: Path) -> None:
    repo = src_root / tool.repo
    if not repo.is_dir():
        raise SystemExit(f"missing clone: {repo}")
    table = dict(CORE_MODULES)
    table.update({flat: f"{tool.package}.{dest}" for flat, dest in tool.modules.items()})
    pkg_dir = tool.package_dir
    pkg_dir.mkdir(parents=True, exist_ok=True)
    init = pkg_dir / "__init__.py"
    if not init.exists():
        init.write_text("", encoding="utf-8")

    def copy(src_rel: str, dest: Path, rewrite: bool, test_pkg: str | None = None) -> None:
        src = repo / src_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if rewrite and src.suffix == ".py":
            text = src.read_text(encoding="utf-8")
            tbl = dict(table)
            if test_pkg:
                tbl["tests"] = test_pkg
            dest.write_text(rewrite_imports(text, tbl, tool.prefixes, tool.package), encoding="utf-8")
        else:
            shutil.copy2(src, dest)

    for src_rel, dest_rel in tool.files.items():
        copy(src_rel, pkg_dir / dest_rel, rewrite=True)
    for src_rel, dest_rel in tool.verbatim.items():
        copy(src_rel, pkg_dir / dest_rel, rewrite=False)
    for sub in {Path(d).parent for d in tool.files.values() if d.endswith(".py")} - {Path(".")}:
        (pkg_dir / sub / "__init__.py").touch()
    for src_rel, dest_rel in tool.tests.items():
        test_pkg = ".".join(Path(dest_rel).parent.parts)
        copy(src_rel, REPO_ROOT / dest_rel, rewrite=True, test_pkg=test_pkg)
        for d in (REPO_ROOT / "tests", (REPO_ROOT / dest_rel).parent):
            (d / "__init__.py").touch()
    for src_rel, dest_rel in tool.docs.items():
        copy(src_rel, REPO_ROOT / dest_rel, rewrite=False)

    commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    version = (repo / "VERSION").read_text(encoding="utf-8").strip() if (repo / "VERSION").exists() else ""
    print(f"{tool.repo:40s} {version:8s} {commit}  -> {tool.package}")


def import_core(src_root: Path) -> None:
    """Move the GUI-free BZN/ODF modules of BZN Toolbox into ``battlezone``."""
    repo = src_root / "Battlezone98Redux_BZN_Toolbox"
    for flat, dotted in CORE_MODULES.items():
        dest = REPO_ROOT / Path(*dotted.split(".")).with_suffix(".py")
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = (repo / f"{flat}.py").read_text(encoding="utf-8")
        table = dict(CORE_MODULES)
        table["bzn_scan"] = "battlezone.bzn.scan"
        dest.write_text(rewrite_imports(text, table, {}, "battlezone"), encoding="utf-8")
    core, gui = split_bzn_scan(repo / "bzn_scan.py")
    (REPO_ROOT / "battlezone/bzn/scan.py").write_text(core, encoding="utf-8")
    gui_dest = REPO_ROOT / "bztoolbox/modules/missions/bzn_scan.py"
    gui_dest.parent.mkdir(parents=True, exist_ok=True)
    gui_dest.write_text(gui, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--only", nargs="*", help="repository names to import")
    args = parser.parse_args(argv)
    tools = build_tools()
    if args.only:
        tools = [t for t in tools if t.repo in args.only]
    for tool in tools:
        import_tool(tool, args.source_root)
    if not args.only or "Battlezone98Redux_BZN_Toolbox" in args.only:
        import_core(args.source_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
