"""Toolbox-wide settings, stored as one JSON file in the user data directory."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from bztoolbox import paths

DEFAULTS: dict[str, Any] = {
    "game_dir": "",                # Battlezone 98 Redux install folder
    "tool_paths": {},              # external tool id -> user-chosen executable
    "recent_limit": 12,
    "last_page": "home",
    "confirm_exit_with_jobs": True,
}


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else paths.user_data_dir() / "settings.json"
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self._data = {**DEFAULTS, **(data if isinstance(data, dict) else {})}

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self.path)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any, save: bool = True) -> None:
        self._data[key] = value
        if save:
            self.save()

    def tool_path(self, tool_id: str) -> str:
        return (self._data.get("tool_paths") or {}).get(tool_id, "")

    def set_tool_path(self, tool_id: str, value: str) -> None:
        tools = dict(self._data.get("tool_paths") or {})
        if value:
            tools[tool_id] = value
        else:
            tools.pop(tool_id, None)
        self.set("tool_paths", tools)


_instance: Settings | None = None


def get_settings() -> Settings:
    global _instance
    if _instance is None:
        _instance = Settings()
    return _instance
