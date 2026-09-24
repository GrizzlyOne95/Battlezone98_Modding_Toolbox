# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for the Battlezone Modding Toolbox (one folder).

    python -m PyInstaller packaging/bztoolbox.spec --noconfirm

Builds on Windows, macOS and Linux from the same spec:

* ``dist/BZModdingToolbox/`` - the windowed ``BZModdingToolbox`` launcher and
  the console ``bztoolbox`` command, sharing one folder of libraries;
* macOS additionally gets ``dist/BZModdingToolbox.app``.

Every module keeps its package layout inside the bundle, so resources that
live beside a module (fonts, icons, rule lists) resolve the same way as from
source. Nothing in the toolbox needs a native helper program any more.

Environment: ``BZTOOLBOX_VERSION_FILE`` - Windows version resource
(packaging/generate_version_info.py).
"""

import importlib.util
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parent
# collect_submodules() imports the packages, so they must be importable here.
sys.path.insert(0, str(ROOT))
VERSION = (ROOT / "VERSION").read_text().strip()

# --- our own data files, at their package paths --------------------------------
datas = [(str(ROOT / "VERSION"), "bztoolbox")]
for package in ("bztoolbox", "battlezone"):
    for path in (ROOT / package).rglob("*"):
        if not path.is_file() or path.suffix in (".py", ".pyc") or "__pycache__" in path.parts:
            continue
        datas.append((str(path), str(path.relative_to(ROOT).parent)))

# --- third-party data ------------------------------------------------------------
datas += collect_data_files("customtkinter")
datas += copy_metadata("imageio")
binaries = []
for optional in ("tkinterdnd2",):
    if importlib.util.find_spec(optional):
        datas += collect_data_files(optional)

# ogre-python (optional): Ogre libraries and Media for the live mesh preview.
ogre_spec = importlib.util.find_spec("Ogre")
if ogre_spec is not None:
    ogre_pkg = Path(ogre_spec.submodule_search_locations[0]) if ogre_spec.submodule_search_locations \
        else Path(ogre_spec.origin).parent
    for f in ogre_pkg.iterdir():
        if f.suffix.lower() in (".dll", ".pyd", ".so", ".dylib") or ".so." in f.name:
            binaries.append((str(f), "Ogre"))
    for candidate in (ogre_pkg / "Media", ogre_pkg.parent / "Media", ogre_pkg.parents[2] / "Media"):
        if candidate.is_dir():
            datas.append((str(candidate), "Ogre/Media"))
            break

# --- modules the registry imports lazily by name ------------------------------------
hiddenimports = [
    name for name in collect_submodules("bztoolbox") + collect_submodules("battlezone")
    if ".research" not in name   # research scripts are not part of the app
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
    excludes=["pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

branding = ROOT / "bztoolbox" / "resources" / "branding"
icon = str(branding / ("app_icon.ico" if sys.platform == "win32" else "app_icon.png"))
version_file = (os.environ.get("BZTOOLBOX_VERSION_FILE") or None) if sys.platform == "win32" else None
if version_file:
    # PyInstaller resolves relative paths against the spec's folder; the
    # variable is relative to the repository root.
    version_file = str((ROOT / version_file).resolve())

# Windowed launcher for users, plus a console twin for the command line
# (a windowed Windows .exe cannot print to a terminal). Both share one folder.
gui_exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="BZModdingToolbox",
    icon=icon, version=version_file, console=False, upx=False,
)
cli_exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="bztoolbox",
    icon=icon, version=version_file, console=True, upx=False,
)
coll = COLLECT(gui_exe, cli_exe, a.binaries, a.datas, name="BZModdingToolbox", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="BZModdingToolbox.app",
        icon=icon,
        bundle_identifier="io.github.grizzlyone95.bzmoddingtoolbox",
        version=VERSION,
        info_plist={
            "CFBundleName": "BZ Modding Toolbox",
            "CFBundleDisplayName": "Battlezone Modding Toolbox",
            "CFBundleShortVersionString": VERSION,
            "NSHighResolutionCapable": True,
        },
    )
