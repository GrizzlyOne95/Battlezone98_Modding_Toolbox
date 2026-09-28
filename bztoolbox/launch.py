"""Test a mod in the game: find the installs, deploy the project, launch a mission, read the logs.

Both games take the same command line (``ProcessCommandLine`` in 1.5,
``FUN_007d5120`` in Redux): tokens starting with ``/`` or ``-`` (Redux also
``+``) are options, and a bare token is a mission, which is loaded straight
away with the shell skipped (``battlezone98redux.exe misn05.bzn``). The
option lists below are the ones those parsers accept; anything else can go in
the free-form extra arguments.

Deploying copies the project into ``<install>/addon/<name>``, where both games
pick files up ahead of their archives, copying only what changed since the last
deploy.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

REDUX_EXE = "battlezone98redux.exe"
LEGACY_EXE = "bzone.exe"
REDUX_STEAM_APP_ID = "301650"
LEGACY_INSTALL_GUESSES = (r"C:\Program Files (x86)\Battlezone", r"C:\Program Files\Battlezone",
                          r"C:\GOG Games\Battlezone", r"C:\Games\Battlezone")
# Files a deploy never copies: version control, editor sources, caches.
DEPLOY_SKIP_DIRS = {".git", ".svn", "__pycache__", ".vs", ".idea"}
DEPLOY_SKIP_SUFFIXES = {".xcf", ".psd", ".blend", ".blend1", ".bak", ".tmp", ".kra", ".pdn"}
ERROR_WORDS = ("error", "not found", "couldn't", "could not", "missing", "failed", "exception", "assert",
               "cannot", "can't", "unable", "invalid", "warning")


@dataclass(frozen=True)
class LaunchFlag:
    key: str
    label: str
    arg: str
    help: str = ""


REDUX_FLAGS: Sequence[LaunchFlag] = (
    LaunchFlag("win", "Windowed", "/win", "Run in a window instead of fullscreen."),
    LaunchFlag("nointro", "Skip intro movie", "/nointro"),
    LaunchFlag("edit", "Editor available", "/edit", "Enables the in-game editor (Ctrl+E)."),
    LaunchFlag("startedit", "Start in the editor", "/startedit", "Implies /edit."),
    LaunchFlag("develop", "Developer mode", "/develop", "Debug commands such as drawcoll."),
    LaunchFlag("console", "Console", "/console"),
    LaunchFlag("nobodyhome", "No AI (nobodyhome)", "/nobodyhome", "Load the mission without its AI."),
    LaunchFlag("disablemods", "Disable Workshop mods", "/disablemods",
               "Only stock files and the addon folder; subscribed mods stay off."),
    LaunchFlag("nohgtsmoothing", "No HGT smoothing", "/nohgtsmoothing",
               "Load legacy .hgt terrain without Redux's 3x3 blur."),
    LaunchFlag("exitafterload", "Exit after load", "/exitafterload", "Quit once the mission has loaded: a load test."),
)

LEGACY_FLAGS: Sequence[LaunchFlag] = (
    LaunchFlag("win", "Windowed", "/win"),
    LaunchFlag("nointro", "Skip intro movie", "/nointro"),
    LaunchFlag("edit", "Editor available", "/edit"),
    LaunchFlag("startedit", "Start in the editor", "/startedit", "Implies /edit."),
    LaunchFlag("console", "Console", "/console"),
    LaunchFlag("nobodyhome", "No AI (nobodyhome)", "/nobodyhome"),
    LaunchFlag("sw", "Software renderer", "/SW"),
)


@dataclass(frozen=True)
class GameInstall:
    kind: str                 # "redux" | "1.5"
    path: Path
    store: str = ""           # "steam" | "gog" | ""

    @property
    def exe(self) -> Path:
        return self.path / (REDUX_EXE if self.kind == "redux" else LEGACY_EXE)

    @property
    def addon(self) -> Path:
        return self.path / "addon"

    @property
    def flags(self) -> Sequence[LaunchFlag]:
        return REDUX_FLAGS if self.kind == "redux" else LEGACY_FLAGS

    @property
    def label(self) -> str:
        game = "Battlezone 98 Redux" if self.kind == "redux" else "Battlezone 1.5"
        store = {"steam": " (Steam)", "gog": " (GOG)"}.get(self.store, "")
        return f"{game}{store} - {self.path}"

    @property
    def log_files(self) -> List[Path]:
        if self.kind == "redux":
            # Stock Redux logs in the game folder; with OpenShim installed they move to logs\.
            names = ("BZLogger.txt", "BZOgreLogfile.log", "openshim.log", "openshim_crash.log")
            return [folder / name for folder in (self.path, self.path / "logs") for name in names] + \
                [self.path / "bzloader.log"]
        return [self.path / name for name in ("symlog.txt", "bz15_shim.log")]


def _store_of(path: Path) -> str:
    text = str(path).lower()
    if "steamapps" in text:
        return "steam"
    if "gog" in text:
        return "gog"
    return ""


def install_at(path, kind: Optional[str] = None) -> Optional[GameInstall]:
    """The install in ``path`` (``kind`` from the executable found there when not given)."""
    folder = Path(path)
    if not folder.is_dir():
        return None
    for candidate, exe in (("redux", REDUX_EXE), ("1.5", LEGACY_EXE)):
        if kind in (None, candidate) and (folder / exe).is_file():
            return GameInstall(candidate, folder, _store_of(folder))
    return None


def detect_installs(settings=None) -> List[GameInstall]:
    """Every Redux and 1.5 install found: the configured game folder, Steam/GOG, the usual 1.5 folders."""
    candidates: List[Path] = []
    if settings is not None:
        for key in ("game_dir", "legacy_game_dir"):
            value = settings.get(key, "") if hasattr(settings, "get") else ""
            if value:
                candidates.append(Path(value))
    try:
        from bztoolbox import external

        candidates += external.detect_game_installs()
    except Exception:
        pass
    candidates += [Path(p) for p in LEGACY_INSTALL_GUESSES]
    found: List[GameInstall] = []
    seen = set()
    for folder in candidates:
        install = install_at(folder)
        if install is None:
            continue
        key = os.path.normcase(os.path.abspath(install.path))
        if key not in seen:
            seen.add(key)
            found.append(install)
    return found


def steam_exe() -> Optional[Path]:
    try:
        from bztoolbox import external

        for root in external._steam_roots():
            exe = Path(root) / "steam.exe"
            if exe.is_file():
                return exe
    except Exception:
        pass
    return None


@dataclass
class LaunchPlan:
    argv: List[str]
    cwd: str
    via_steam: bool = False

    def command_line(self) -> str:
        return subprocess.list2cmdline(self.argv)


def build_launch(install: GameInstall, mission: str = "", flags: Iterable[str] = (), extra: str = "",
                 via_steam: bool = False) -> LaunchPlan:
    """The command for ``install``; ``flags`` are :class:`LaunchFlag` keys, ``extra`` free-form arguments."""
    known = {flag.key: flag for flag in install.flags}
    unknown = [key for key in flags if key not in known]
    if unknown:
        raise ValueError(f"not a {install.kind} option: {', '.join(unknown)}")
    args = [known[key].arg for key in known if key in set(flags)]
    if extra.strip():
        args += shlex.split(extra, posix=False)
    if mission.strip():
        args.append(os.path.basename(mission.strip()))
    if via_steam:
        steam = steam_exe()
        if install.kind != "redux" or install.store != "steam" or steam is None:
            raise ValueError("launching through Steam needs the Steam copy of Redux and steam.exe")
        return LaunchPlan([str(steam), "-applaunch", REDUX_STEAM_APP_ID, *args], str(install.path), True)
    if not install.exe.is_file():
        raise FileNotFoundError(f"{install.exe} is missing")
    return LaunchPlan([str(install.exe), *args], str(install.path))


def start(plan: LaunchPlan) -> subprocess.Popen:
    """Start the game without tying it to this process (it outlives the toolbox)."""
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(plan.argv, cwd=plan.cwd, creationflags=flags, close_fds=True)


# ---------------------------------------------------------------------------
# Deploying
# ---------------------------------------------------------------------------

@dataclass
class DeployResult:
    target: Path
    copied: List[str] = field(default_factory=list)
    unchanged: int = 0
    skipped: List[str] = field(default_factory=list)


def deploy_name(project_dir) -> str:
    return Path(project_dir).name.strip() or "toolbox_test"


def deploy_project(project_dir, install: GameInstall, name: Optional[str] = None) -> DeployResult:
    """Copy the project into ``<install>/addon/<name>``, only files that are new or changed."""
    source = Path(project_dir)
    if not source.is_dir():
        raise NotADirectoryError(f"{source} is not a folder")
    target = install.addon / (name or deploy_name(source))
    if os.path.normcase(os.path.abspath(target)) == os.path.normcase(os.path.abspath(source)):
        raise ValueError("the project already lives in that addon folder")
    result = DeployResult(target)
    for dirpath, dirnames, filenames in os.walk(source):
        dirnames[:] = [d for d in dirnames if d not in DEPLOY_SKIP_DIRS]
        for filename in filenames:
            src = Path(dirpath) / filename
            rel = src.relative_to(source)
            if src.suffix.lower() in DEPLOY_SKIP_SUFFIXES:
                result.skipped.append(rel.as_posix())
                continue
            dst = target / rel
            stat = src.stat()
            if dst.is_file():
                other = dst.stat()
                if other.st_size == stat.st_size and int(other.st_mtime) == int(stat.st_mtime):
                    result.unchanged += 1
                    continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            result.copied.append(rel.as_posix())
    return result


def remove_deployment(install: GameInstall, name: str) -> bool:
    target = install.addon / name
    if not name or not target.is_dir() or target.resolve().parent != install.addon.resolve():
        return False
    shutil.rmtree(target)
    return True


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

class LogWatch:
    """Remembers how long each log was at launch, then returns only what the run added."""

    def __init__(self, install: GameInstall):
        self.install = install
        self.started = time.time()
        self.offsets: Dict[Path, int] = {p: (p.stat().st_size if p.is_file() else 0) for p in install.log_files}
        self.mtimes: Dict[Path, float] = {p: (p.stat().st_mtime if p.is_file() else 0.0) for p in install.log_files}

    def new_lines(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for path, offset in self.offsets.items():
            if not path.is_file():
                continue
            stat = path.stat()
            size = stat.st_size
            # BZLogger.txt and the Ogre log are rewritten from scratch each run: a newer file that is
            # not longer than before is a new log, not an unchanged one.
            if size < offset or (stat.st_mtime > self.mtimes.get(path, 0.0) and size <= offset):
                offset = 0
            if size == offset:
                continue
            with open(path, "rb") as stream:
                stream.seek(offset)
                text = stream.read().decode("utf-8", errors="replace")
            lines = [line.rstrip() for line in text.splitlines() if line.strip()]
            if lines:
                out[path.name] = lines
        return out


_PROBLEM = re.compile(r"\b(" + "|".join(re.escape(w) for w in ERROR_WORDS) + r")\b", re.IGNORECASE)
# Lines every stock run writes; they say nothing about the mod.
LOG_NOISE = (
    "Invalid target for D3D11 shader",          # Ogre probing HLSL4 profiles on every start
    "Information Queue Exceptions",
    "GalaxyPeer library location",              # GOG build started outside Galaxy
    "try/catch failure error no: GalaxyRuntimeError",
    "[INFO]",                                   # OpenShim status lines ("failed=0 of 78")
)
_TIMESTAMP = re.compile(r"^[\d:\-. ]+")


def flagged(lines: Iterable[str]) -> List[str]:
    """Lines that look like problems (missing files, errors, warnings), stock noise and repeats removed."""
    out, seen = [], set()
    for line in lines:
        if not _PROBLEM.search(line) or any(noise in line for noise in LOG_NOISE):
            continue
        key = _TIMESTAMP.sub("", line)
        if key not in seen:
            seen.add(key)
            out.append(line)
    return out


def missions_in(folder) -> List[str]:
    root = Path(folder)
    if not root.is_dir():
        return []
    return sorted({p.name for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".bzn"}, key=str.lower)
