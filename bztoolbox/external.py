"""External programs some modules use, and how the toolbox finds them.

Only individual features depend on these; the toolbox itself runs without
any of them. Resolution order for every tool:

1. the path the user chose on the Settings page,
2. a copy bundled with the toolbox (``bztoolbox/resources/bin`` or the
   owning module's ``bin`` folder),
3. the system ``PATH`` (and a few well-known install locations).
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from bztoolbox import paths
from bztoolbox.settings import get_settings

IS_WINDOWS = sys.platform == "win32"
_EXE = ".exe" if IS_WINDOWS else ""
_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


@dataclass(frozen=True)
class ExternalTool:
    id: str
    name: str
    purpose: str
    used_by: Sequence[str]
    kind: str                          # "bundled" | "optional" | "external"
    executables: Sequence[str]         # candidate file names, without .exe
    bundled: Sequence[str] = ()        # package-relative bundled locations
    well_known: Sequence[str] = ()     # glob patterns for common installs
    version_args: Optional[Sequence[str]] = ("-version",)
    windows_only: bool = False
    url: str = ""


@dataclass
class ToolStatus:
    tool: ExternalTool
    path: str = ""
    source: str = ""                   # "settings" | "bundled" | "PATH" | "installed"
    version: str = ""
    problems: List[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.path)


TOOLS: dict[str, ExternalTool] = {t.id: t for t in (
    ExternalTool(
        "ffmpeg", "FFmpeg", "Audio transcoding and radio VO mastering.",
        ("Assets > Audio",), "optional", ("ffmpeg",),
        bundled=("resources/bin/ffmpeg", "modules/audio/bin/ffmpeg"),
        url="https://ffmpeg.org/download.html",
    ),
    ExternalTool(
        "steamcmd", "SteamCMD", "Uploading and updating Steam Workshop items.",
        ("Project > Publish",), "external", ("steamcmd",),
        well_known=(r"C:\steamcmd\steamcmd.exe", r"C:\Program Files*\steamcmd\steamcmd.exe",
                    "~/steamcmd/steamcmd.sh", "/usr/games/steamcmd"),
        version_args=None,
        url="https://developer.valvesoftware.com/wiki/SteamCMD",
    ),
    ExternalTool(
        "blender", "Blender", "Ogre mesh to glTF conversion (animated/rigged meshes).",
        ("Assets > Meshes",), "external", ("blender",),
        well_known=(r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
                    "/Applications/Blender.app/Contents/MacOS/Blender", "/usr/bin/blender",
                    "/snap/bin/blender"),
        version_args=("--version",),
        url="https://www.blender.org/download/",
    ),
    ExternalTool(
        "ogrexmlconverter", "OgreXMLConverter", "Ogre .mesh <-> XML conversion.",
        ("Assets > Meshes",), "bundled", ("OgreXMLConverter",),
        bundled=("modules/meshes/bin/OgreXMLConverter",),
        version_args=None, windows_only=True,
    ),
    ExternalTool(
        "ogremeshupgrader", "OgreMeshUpgrader", "Ogre mesh version upgrades and LOD generation.",
        ("Assets > Meshes",), "bundled", ("OgreMeshUpgrader",),
        bundled=("modules/meshes/bin/OgreMeshUpgrader",),
        version_args=None, windows_only=True,
    ),
    ExternalTool(
        "lzo_bridge", "LZO bridge", "Compressed ZFS archive support (GPL-2.0 component).",
        ("Archives > ZFS",), "bundled", ("lzo_bridge.dll",),
        bundled=("modules/zfs/native/lzo_bridge.dll",),
        version_args=None, windows_only=True,
    ),
)}


def _candidate_names(tool: ExternalTool) -> List[str]:
    names = []
    for name in tool.executables:
        if name.endswith((".dll", ".exe", ".sh")):
            names.append(name)
        else:
            names.append(name + _EXE)
            if not IS_WINDOWS:
                names.append(name + ".exe")   # Windows helpers shipped in-tree
    return names


def _bundled_path(tool: ExternalTool) -> str:
    for rel in tool.bundled:
        base = paths.PACKAGE_DIR / rel
        for candidate in (base, base.with_name(base.name + _EXE)):
            if candidate.is_file():
                return str(candidate)
    return ""


def resolve(tool_id: str, settings=None) -> ToolStatus:
    tool = TOOLS[tool_id]
    settings = settings or get_settings()
    status = ToolStatus(tool)
    if tool.windows_only and not IS_WINDOWS:
        status.problems.append("Only available on Windows.")
        return status

    chosen = settings.tool_path(tool_id)
    if chosen:
        expanded = os.path.expanduser(chosen)
        resolved = expanded if os.path.isfile(expanded) else shutil.which(expanded)
        if resolved:
            status.path, status.source = resolved, "settings"
            return status
        status.problems.append(f"Configured path not found: {chosen}")

    bundled = _bundled_path(tool)
    if bundled:
        status.path, status.source = bundled, "bundled"
        return status

    for name in _candidate_names(tool):
        found = shutil.which(name)
        if found:
            status.path, status.source = found, "PATH"
            return status

    for pattern in tool.well_known:
        matches = sorted(glob.glob(os.path.expanduser(pattern)), reverse=True)
        if matches:
            status.path, status.source = matches[0], "installed"
            return status
    return status


def probe_version(status: ToolStatus, timeout: float = 5.0) -> ToolStatus:
    """Fill ``status.version`` by running the tool (slow: call off the UI thread)."""
    args = status.tool.version_args
    if not status.found or not args:
        return status
    try:
        result = subprocess.run([status.path, *args], capture_output=True, text=True,
                                timeout=timeout, creationflags=_NO_WINDOW)
        first = (result.stdout or result.stderr).strip().splitlines()
        status.version = first[0][:120] if first else ""
    except (OSError, subprocess.SubprocessError) as exc:
        status.problems.append(f"Could not run: {exc}")
    return status


def resolve_all(settings=None) -> List[ToolStatus]:
    return [resolve(tool_id, settings) for tool_id in TOOLS]


def executable(tool_id: str, fallback: str = "") -> str:
    """Path to use when launching ``tool_id`` (``fallback`` when not found)."""
    status = resolve(tool_id)
    return status.path or fallback


# ---------------------------------------------------------------------------
# Game install detection
# ---------------------------------------------------------------------------

BZ98R_STEAM_APPID = "301650"
BZ98R_FOLDER_NAMES = ("Battlezone 98 Redux",)


def _steam_roots() -> List[Path]:
    roots: List[Path] = []
    if IS_WINDOWS:
        try:
            import winreg  # type: ignore

            for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
                try:
                    with winreg.OpenKey(hive, key) as handle:
                        for value_name in ("SteamPath", "InstallPath"):
                            try:
                                roots.append(Path(winreg.QueryValueEx(handle, value_name)[0]))
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
        roots += [Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")]
    else:
        home = Path.home()
        roots += [home / ".steam" / "steam", home / ".local" / "share" / "Steam",
                  home / "Library" / "Application Support" / "Steam"]
    seen, unique = set(), []
    for root in roots:
        key = str(root).lower()
        if key not in seen and root.is_dir():
            seen.add(key)
            unique.append(root)
    return unique


def _steam_libraries(steam_root: Path) -> List[Path]:
    libraries = [steam_root]
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return libraries
    import re

    for match in re.finditer(r'"path"\s+"([^"]+)"', text):
        libraries.append(Path(match.group(1).replace("\\\\", "\\")))
    return libraries


def detect_game_installs(extra_checks: Callable[[], List[Path]] | None = None) -> List[Path]:
    """Folders that look like a Battlezone 98 Redux install."""
    found: List[Path] = []
    for root in _steam_roots():
        for library in _steam_libraries(root):
            for name in BZ98R_FOLDER_NAMES:
                candidate = library / "steamapps" / "common" / name
                if candidate.is_dir() and candidate not in found:
                    found.append(candidate)
    if IS_WINDOWS:
        for pattern in (r"C:\GOG Games\Battlezone 98 Redux", r"C:\Program Files*\GOG Galaxy\Games\Battlezone 98 Redux"):
            for match in glob.glob(pattern):
                path = Path(match)
                if path.is_dir() and path not in found:
                    found.append(path)
    if extra_checks:
        found.extend(p for p in extra_checks() if p not in found)
    return found


def workshop_content_dir(game_dir: Path) -> Optional[Path]:
    """``steamapps/workshop/content/301650`` for a Steam install, if present."""
    try:
        steamapps = game_dir.parents[1]
    except IndexError:
        return None
    candidate = steamapps / "workshop" / "content" / BZ98R_STEAM_APPID
    return candidate if candidate.is_dir() else None
