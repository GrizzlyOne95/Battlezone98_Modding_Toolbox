"""Battlezone Modding Toolbox: one application for Battlezone 98 Redux modding."""

from pathlib import Path

APP_NAME = "Battlezone Modding Toolbox"
APP_ID = "GrizzlyOne95.BattlezoneModdingToolbox"


def _read_version() -> str:
    for candidate in (Path(__file__).with_name("VERSION"), Path(__file__).parents[1] / "VERSION"):
        try:
            return candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    return "0.0.0"


__version__ = _read_version()
