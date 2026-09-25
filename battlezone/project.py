"""The Battlezone project: one mod folder plus the metadata every module shares.

A project is the mod's content folder. Its metadata (title, Workshop item,
preview image, ...) is stored *outside* the folder, in the toolbox's user data
directory, so it is never uploaded to the Workshop with the content. The
profile layout is the one the Workshop Uploader already used (``mod_path``,
``title``, ``item_id``, ...), so existing upload profiles can be imported
as-is.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

GAMES = {
    "bz98r": "Battlezone 98 Redux",
}

# File kinds the overview groups by. Anything else is counted as "other".
FILE_KINDS = {
    "Mission files": (".bzn", ".ini", ".des", ".vxt", ".lua"),
    "World files": (".trn", ".hg2", ".mat", ".lgt", ".hgt"),
    "Object files": (".odf", ".xsi", ".mesh", ".skeleton", ".material", ".program"),
    "Textures": (".dds", ".tga", ".png", ".bmp", ".map", ".act", ".pic", ".jpg"),
    "Audio": (".wav", ".ogg", ".mp3"),
    "Archives": (".zfs", ".zip", ".pak"),
}


@dataclass
class Project:
    mod_path: str
    title: str = ""
    game: str = "bz98r"
    description: str = ""
    item_id: str = "0"
    preview_path: str = ""
    tags: str = ""
    visibility: str = "0"
    change_note: str = ""
    author: str = ""
    notes: str = ""
    # Free-form per-module state, keyed by module id.
    modules: Dict[str, dict] = field(default_factory=dict)
    # Everything else found in the profile (e.g. Workshop upload history) is
    # preserved untouched so round-tripping never loses data.
    extra: Dict[str, object] = field(default_factory=dict)
    profile_path: str = ""
    last_opened: str = ""

    @property
    def root(self) -> Path:
        return Path(self.mod_path)

    @property
    def name(self) -> str:
        return self.title or self.root.name or "Untitled project"

    @property
    def game_name(self) -> str:
        return GAMES.get(self.game, self.game)

    @property
    def workshop_id(self) -> str:
        return "" if self.item_id in ("", "0", None) else str(self.item_id)

    def to_profile(self) -> dict:
        data = {k: v for k, v in asdict(self).items() if k not in ("extra",)}
        data.update(self.extra)
        # Keep the Workshop Uploader's field name for the display name.
        data.setdefault("project_name", self.root.name)
        return data

    @classmethod
    def from_profile(cls, data: dict) -> "Project":
        known = {f.name for f in fields(cls)} - {"extra"}
        kwargs = {k: v for k, v in data.items() if k in known}
        extra = {k: v for k, v in data.items() if k not in known}
        project = cls(**kwargs)
        project.extra = extra
        return project

    def summarize(self) -> "ProjectSummary":
        return summarize_folder(self.root)


@dataclass
class ProjectSummary:
    file_count: int = 0
    total_bytes: int = 0
    kinds: Dict[str, int] = field(default_factory=dict)
    extensions: Dict[str, int] = field(default_factory=dict)
    missions: List[str] = field(default_factory=list)
    worlds: List[str] = field(default_factory=list)            # every .trn in the folder
    planets: Dict[str, int] = field(default_factory=dict)      # missions per planet, largest first


# The stock planet palettes. A mission's planet is read from its terrain.
PLANETS = ("Achilles", "Elysium", "Europa", "Ganymede", "Io", "Mars", "Moon", "Titan", "Venus")
UNKNOWN_PLANET = "Custom / unknown"


def planet_of_trn(path: Path) -> str:
    """Planet of a terrain: its ``[Color] Palette``, else a planet named in its atlas material."""
    from battlezone.terrain.trn import read_trn

    try:
        trn = read_trn(path)
    except (OSError, ValueError):
        return UNKNOWN_PLANET
    candidates = [os.path.splitext(trn.palette or "")[0], trn.material_name or ""]
    for candidate in candidates:
        lowered = candidate.lower()
        for planet in PLANETS:
            if lowered == planet.lower():
                return planet
    for candidate in candidates:   # e.g. "MarsAtlas", "venus2"
        lowered = candidate.lower()
        for planet in PLANETS:
            if planet != "Io" and lowered.startswith(planet.lower()):
                return planet
    return UNKNOWN_PLANET


def summarize_folder(root: Path) -> ProjectSummary:
    summary = ProjectSummary()
    if not root.is_dir():
        return summary
    ext_counter: Counter = Counter()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        summary.file_count += 1
        try:
            summary.total_bytes += path.stat().st_size
        except OSError:
            pass
        ext = path.suffix.lower()
        ext_counter[ext] += 1
        if ext == ".bzn":
            summary.missions.append(path.relative_to(root).as_posix())
        elif ext == ".trn":
            summary.worlds.append(path.relative_to(root).as_posix())
    summary.extensions = dict(ext_counter.most_common())
    kinds = Counter()
    for ext, count in ext_counter.items():
        kind = next((k for k, exts in FILE_KINDS.items() if ext in exts), "Other")
        kinds[kind] += count
    summary.kinds = {k: kinds[k] for k in list(FILE_KINDS) + ["Other"] if kinds.get(k)}
    summary.missions.sort(key=str.lower)
    summary.worlds.sort(key=str.lower)
    terrains = {os.path.splitext(rel)[0].lower(): rel for rel in summary.worlds}
    planets: Counter = Counter()
    for mission in summary.missions:
        trn = terrains.get(os.path.splitext(mission)[0].lower())
        planets[planet_of_trn(root / trn) if trn else UNKNOWN_PLANET] += 1
    summary.planets = dict(planets.most_common())
    return summary


def folder_fingerprint(root: str | Path) -> str:
    """Hash of every file's path, size and modification time under ``root``.

    Cheap next to a full scan; pages use it to re-run only when the folder
    changed since their last result.
    """
    digest = hashlib.sha1()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            digest.update(f"{path}|{stat.st_size}|{stat.st_mtime_ns}\n".encode("utf-8", "surrogateescape"))
    return digest.hexdigest()


class ProjectStore:
    """Profiles on disk, one JSON file per mod folder (Workshop Uploader layout)."""

    def __init__(self, profiles_dir: str | Path):
        self.profiles_dir = Path(profiles_dir)

    @staticmethod
    def _slugify(value: str) -> str:
        text = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
        return text or "project"

    def profile_path_for(self, mod_path: str | Path) -> Path:
        normalized = os.path.abspath(str(mod_path or "")).lower()
        digest = hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()[:10]
        label = self._slugify(os.path.basename(normalized) or "project")
        return self.profiles_dir / f"{label}-{digest}.json"

    def list(self) -> List[Project]:
        projects = []
        if self.profiles_dir.is_dir():
            for path in sorted(self.profiles_dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(data, dict) and data.get("mod_path"):
                    data["profile_path"] = str(path)
                    projects.append(Project.from_profile(data))
        projects.sort(key=lambda p: p.last_opened or "", reverse=True)
        return projects

    def find(self, mod_path: str | Path) -> Optional[Project]:
        path = self.profile_path_for(mod_path)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["profile_path"] = str(path)
                return Project.from_profile(data)
            except (OSError, ValueError):
                return None
        canonical = os.path.abspath(str(mod_path))
        for project in self.list():
            if os.path.abspath(project.mod_path) == canonical:
                return project
        return None

    def open(self, mod_path: str | Path) -> Project:
        """Return the stored project for ``mod_path`` or a fresh one, and save it."""
        project = self.find(mod_path) or Project(mod_path=os.path.abspath(str(mod_path)))
        self.save(project)
        return project

    def save(self, project: Project) -> Path:
        path = Path(project.profile_path) if project.profile_path else self.profile_path_for(project.mod_path)
        project.profile_path = str(path)
        project.last_opened = datetime.now(timezone.utc).isoformat()
        # Other writers (the Publish module records upload history here) may
        # have updated fields this Project object does not manage; the copy on
        # disk wins for those.
        known = {f.name for f in fields(Project)}
        try:
            on_disk = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            on_disk = {}
        if isinstance(on_disk, dict):
            project.extra.update({k: v for k, v in on_disk.items() if k not in known})
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(project.to_profile(), indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return path

    def reload(self, project: Project) -> Project:
        """Fresh copy of ``project`` from disk (after another module saved it)."""
        return self.find(project.mod_path) or project

    def forget(self, project: Project) -> None:
        path = Path(project.profile_path) if project.profile_path else self.profile_path_for(project.mod_path)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def import_profile(self, profile_file: str | Path) -> Project:
        """Adopt a Workshop Uploader profile JSON."""
        data = json.loads(Path(profile_file).read_text(encoding="utf-8"))
        if not data.get("mod_path"):
            raise ValueError("Profile has no mod_path")
        data.pop("profile_path", None)
        project = Project.from_profile(data)
        self.save(project)
        return project
