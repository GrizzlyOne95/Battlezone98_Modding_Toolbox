# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for the Battlezone Modding Toolbox (one folder).

    python -m PyInstaller packaging/bztoolbox.spec --noconfirm

Environment switches:
  BZTOOLBOX_EXCLUDE_GPL=1   build without the GPL-2.0 ZFS/LZO component; the
                            result is MIT-only and simply has no Archives page.
  BZTOOLBOX_VERSION_FILE    Windows version resource (packaging/generate_version_info.py).

Every module keeps its package layout inside the bundle, so resources that
live beside a module (fonts, icons, rule lists, helper binaries) resolve the
same way as from source.
"""

import importlib.util
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parent
# collect_submodules() imports the packages, so they must be importable here.
sys.path.insert(0, str(ROOT))
EXCLUDE_GPL = os.environ.get("BZTOOLBOX_EXCLUDE_GPL") == "1"
GPL_PACKAGE = "bztoolbox/modules/zfs"

# --- our own data files, at their package paths --------------------------------
datas = [(str(ROOT / "VERSION"), "bztoolbox")]
binaries = []
for package in ("bztoolbox", "battlezone"):
    for path in (ROOT / package).rglob("*"):
        if not path.is_file() or path.suffix in (".py", ".pyc") or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(ROOT)
        if EXCLUDE_GPL and rel.as_posix().startswith(GPL_PACKAGE):
            continue
        target = (binaries if path.suffix.lower() in (".dll", ".exe") else datas)
        target.append((str(path), str(rel.parent)))
# Blender runs these scripts from disk, so they ship as files too.
datas += [(str(p), str(p.relative_to(ROOT).parent))
          for p in (ROOT / "bztoolbox/modules/meshes/blender").glob("*.py")]

# --- third-party data ------------------------------------------------------------
datas += collect_data_files("customtkinter")
datas += copy_metadata("imageio")
for optional in ("tkinterdnd2",):
    if importlib.util.find_spec(optional):
        datas += collect_data_files(optional)

# ogre-python (optional): Ogre DLLs, .pyd modules and Media for the mesh preview.
ogre_spec = importlib.util.find_spec("Ogre")
if ogre_spec is not None:
    ogre_pkg = Path(ogre_spec.submodule_search_locations[0]) if ogre_spec.submodule_search_locations \
        else Path(ogre_spec.origin).parent
    for f in ogre_pkg.iterdir():
        if f.suffix.lower() in (".dll", ".pyd", ".so"):
            binaries.append((str(f), "Ogre"))
    for candidate in (ogre_pkg / "Media", ogre_pkg.parent / "Media", ogre_pkg.parents[2] / "Media"):
        if candidate.is_dir():
            datas.append((str(candidate), "Ogre/Media"))
            break

# --- modules the registry imports lazily by name ------------------------------------
excluded = ["bztoolbox.modules.zfs"] if EXCLUDE_GPL else []
hiddenimports = [
    name for name in collect_submodules("bztoolbox") + collect_submodules("battlezone")
    if not any(name.startswith(prefix) for prefix in excluded)
    # research scripts and Blender-side scripts are not part of the app
    and ".research" not in name and ".blender" not in name
]
# ImageTk is often imported inside functions, which the analysis cannot see.
hiddenimports += ["PIL.ImageTk", "PIL._tkinter_finder"]
if not any(name.startswith("bztoolbox.modules.") for name in hiddenimports):
    raise SystemExit("collect_submodules found no toolbox modules; the bundle would be incomplete")

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[str(ROOT / "packaging" / "rthook_paths.py")],
    excludes=excluded + ["pytest", "bpy", "bmesh", "mathutils"],
    noarchive=False,
)
pyz = PYZ(a.pure)

version_file = os.environ.get("BZTOOLBOX_VERSION_FILE") or None
icon = str(ROOT / "bztoolbox" / "resources" / "branding" / "app_icon.ico")

# Windowed launcher for users, plus a console twin for the command line
# (a windowed .exe cannot print to a terminal on Windows). Both share one
# folder of libraries.
gui_exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="BZModdingToolbox",
    icon=icon, version=version_file, console=False, upx=False,
)
cli_exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="bztoolbox",
    icon=icon, version=version_file, console=True, upx=False,
)
coll = COLLECT(gui_exe, cli_exe, a.binaries, a.datas, name="BZModdingToolbox", upx=False)
