"""Sprite table support for Assets > Sprites: stock table, sheet lookup and previews.

A ``.sta`` entry names an Ogre material; the material's diffuse texture is
the sheet and the entry's rectangle is measured in its reference image size
(``image_width`` x ``image_height``), so it is scaled to the texture's real
resolution before cropping. Lookups reuse the Redux -> 1.5 port's finder:
the table's folder (recursively), then the game's ``BZ_ASSETS`` and ``addon``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

from battlezone.images.sprites import StaEntry

STOCK_TABLE = "spritea.st"
PROJECT_TABLES = ("spritea.sta",)


def stock_sta_text(game_dir) -> Optional[str]:
    """Redux's stock ``spritea.st`` from ``bzone.zfs`` in ``game_dir``, or None."""
    from battlezone.archives.zfs import ZFSArchive

    if not game_dir:
        return None
    archive_path = Path(game_dir) / "bzone.zfs"
    if not archive_path.is_file():
        return None
    try:
        archive = ZFSArchive(archive_path)
        entry = next((e for e in archive if e.name.lower() == STOCK_TABLE), None)
        return archive.read(entry).decode("cp1252", errors="replace") if entry is not None else None
    except (OSError, ValueError, KeyError):
        return None


def find_project_table(mod_path) -> Optional[Path]:
    """The project's sprite table: ``spritea.sta`` if present, else the first ``.sta``."""
    if not mod_path or not os.path.isdir(mod_path):
        return None
    found = []
    for dirpath, _dirs, files in os.walk(mod_path):
        for name in files:
            if name.lower().endswith(".sta"):
                found.append(Path(dirpath) / name)
    found.sort(key=lambda p: (p.name.lower() not in PROJECT_TABLES, len(p.parts), str(p).lower()))
    return found[0] if found else None


def crop_box(entry: StaEntry, width: int, height: int) -> tuple:
    """The entry's rectangle in a ``width`` x ``height`` texture (clamped to it)."""
    fx = width / max(1, entry.image_width)
    fy = height / max(1, entry.image_height)
    left = min(width, max(0, round(entry.u * fx)))
    top = min(height, max(0, round(entry.v * fy)))
    right = min(width, max(left + 1, round((entry.u + entry.width) * fx)))
    bottom = min(height, max(top + 1, round((entry.v + entry.height) * fy)))
    return left, top, right, bottom


class SpriteSheets:
    """Material -> texture -> image lookups for one table, cached."""

    def __init__(self, folder=None, game_dir=None, search_dirs=()):
        from bztoolbox.modules.world.redux_to_legacy import _Finder

        roots = Path(folder) if folder else Path(os.devnull)
        self._finder = _Finder(roots, search_dirs, Path(game_dir) if game_dir else None)
        self._textures: Dict[str, Optional[Path]] = {}
        self._images: Dict[Path, object] = {}

    def texture(self, material: str) -> Optional[Path]:
        key = material.lower()
        if key not in self._textures:
            found = self._finder.material(material)
            self._textures[key] = self._finder.texture(found.diffuse) if found is not None and found.diffuse else None
        return self._textures[key]

    def explain(self, material: str) -> str:
        """Why a material has no preview, or where its sheet is."""
        texture = self.texture(material)
        if texture is not None:
            return str(texture)
        found = self._finder.material(material)
        if found is None:
            return f"no material {material} in the table's folder or the game's assets"
        if not found.diffuse:
            return f"material {material} names no texture"
        return f"texture {found.diffuse} (material {material}) was not found"

    def image(self, path: Path):
        if path not in self._images:
            from bztoolbox.modules.world.redux_to_legacy import _open_image

            self._images[path] = _open_image(path)
        return self._images[path]

    def crop(self, entry: StaEntry):
        """The sprite as an RGBA Pillow image, or None when its sheet cannot be found."""
        path = self.texture(entry.material)
        if path is None:
            return None
        image = self.image(path)
        return image.crop(crop_box(entry, *image.size))
