"""Navigation model: every page of the toolbox, grouped by workflow area.

Pages are declared here and imported lazily, so opening the toolbox does not
import SciPy, customtkinter, Ogre, ... until a page that needs them is shown.

``kind="native"``  - a page written for the shell; ``factory(parent, shell)``
                     returns a widget.
``kind="legacy"``  - a migrated tool UI hosted through
                     :mod:`bztoolbox.app.host`; ``factory(container)`` returns
                     ``(root_widget, app)``.
"""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

SECTIONS: Sequence[tuple[str, str]] = (
    ("home", "Home"),
    ("project", "Project"),
    ("missions", "Missions"),
    ("world", "World & Terrain"),
    ("assets", "Assets"),
    ("archives", "Archives"),
    ("tools", "Tools"),
    ("settings", "Settings"),
)


@dataclass(frozen=True)
class PageSpec:
    id: str
    section: str
    title: str
    summary: str
    factory: str                       # "package.module:function"
    kind: str = "native"
    origin: str = ""                   # the standalone tool this replaces
    requires: Sequence[str] = ()       # external tool ids (bztoolbox.external)
    project_hook: Optional[str] = None # "package.module:function(app, project)"
    keywords: Sequence[str] = field(default_factory=tuple)
    package: str = ""                  # module package; page hidden if absent from a build

    @property
    def available(self) -> bool:
        if not self.package:
            return True
        try:
            return importlib.util.find_spec(self.package) is not None
        except (ImportError, ValueError):
            return False

    def load_factory(self) -> Callable:
        return _resolve(self.factory)

    def load_project_hook(self) -> Optional[Callable]:
        return _resolve(self.project_hook) if self.project_hook else None


def _resolve(dotted: str) -> Callable:
    module_name, _, attr = dotted.partition(":")
    return getattr(importlib.import_module(module_name), attr)


_L = "bztoolbox.modules.legacy"
_P = "bztoolbox.app.pages"

PAGES: Sequence[PageSpec] = (
    # --- Home -------------------------------------------------------------
    PageSpec("home", "home", "Home", "Recent projects, quick actions and install detection.",
             f"{_P}.home:HomePage"),

    # --- Project ----------------------------------------------------------
    PageSpec("project.overview", "project", "Overview",
             "The open mod: metadata shared by every module and what the folder contains.",
             f"{_P}.project:ProjectPage"),
    PageSpec("project.validation", "project", "Validation",
             "One validation engine for missions, ODFs, assets and Workshop layout.",
             f"{_P}.validation:ValidationPage", keywords=("odf", "preflight", "check")),
    PageSpec("project.localization", "project", "Localization",
             "Scan ODF unit names and build Redux localization tables.",
             f"{_L}:localization", kind="legacy", package="bztoolbox.modules.localization", origin="Localization Tool",
             project_hook=f"{_L}:localization_project"),
    PageSpec("project.publish", "project", "Workshop / Publish",
             "Readiness checks, content fixes and Steam Workshop uploads.",
             f"{_L}:publishing", kind="legacy", package="bztoolbox.modules.publishing", origin="Workshop Uploader", requires=("steamcmd",),
             project_hook=f"{_L}:publishing_project"),

    # --- Missions ---------------------------------------------------------
    PageSpec("missions.inspector", "missions", "Mission Inspector",
             "BZN dependencies, ODF validation and BZ2/BZCC to Redux mission ports.",
             f"{_L}:missions", kind="legacy", package="bztoolbox.modules.missions", origin="BZN Toolbox", keywords=("bzn", "odf", "bzcc")),

    # --- World & Terrain --------------------------------------------------
    PageSpec("world.builder", "world", "World Builder",
             "Create worlds, legacy/BZ2 terrain ports, auto-painting, atlases, skies and mission preview.",
             f"{_L}:world", kind="legacy", package="bztoolbox.modules.world", origin="WorldBuilder",
             keywords=("trn", "hg2", "mat", "atlas", "sky", "legacy")),
    PageSpec("world.generate", "world", "Generate Terrain",
             "Procedural HG2 terrain with live HG2/LGT preview.",
             f"{_L}:terrain_generator", kind="legacy", package="bztoolbox.modules.terrain_generator", origin="HeightmapGen", keywords=("hg2", "lgt", "heightmap")),

    # --- Assets -----------------------------------------------------------
    PageSpec("assets.textures", "assets", "Textures & Images",
             "ACT palettes, texture conversion, MAP/MakeMAP, LGT, DXTBZ2 and channel packing.",
             f"{_L}:textures", kind="legacy", package="bztoolbox.modules.textures", origin="TextureManager", keywords=("dds", "map", "act", "lgt")),
    PageSpec("assets.fonts", "assets", "Fonts",
             "Generate bzfont.dds font sheets.",
             f"{_L}:fonts", kind="legacy", package="bztoolbox.modules.fonts", origin="Font Generator"),
    PageSpec("assets.holotext", "assets", "Holographic Text",
             "Holo text sprites, materials, ODFs and Lua.",
             f"{_L}:holotext", kind="legacy", package="bztoolbox.modules.holotext", origin="HoloTextGen"),
    PageSpec("assets.meshes", "assets", "Models & Meshes",
             "Ogre mesh normal fixes and OBJ export with live preview.",
             f"{_L}:meshes", kind="legacy", package="bztoolbox.modules.meshes", origin="OgreMeshTools"),
    PageSpec("assets.audio", "assets", "Audio",
             "Radio VO mastering, engine WAV conversion, music OGG and timing manifests.",
             f"{_L}:audio", kind="legacy", package="bztoolbox.modules.audio", origin="AudioTool"),

    # --- Archives ---------------------------------------------------------
    PageSpec("archives.zfs", "archives", "ZFS Archives",
             "Browse, extract, verify and pack ZFS archives (LZO1X/LZO1Y, encrypted).",
             "bztoolbox.modules.archives.zfs_page:ZFSPage", origin="ZFS Specialist", keywords=("zfs", "lzo", "pak")),

    # --- Tools ------------------------------------------------------------
    PageSpec("tools.tasks", "tools", "Background Tasks", "Everything running in the background.",
             f"{_P}.tasks:TasksPage"),

    # --- Settings ---------------------------------------------------------
    PageSpec("settings.general", "settings", "General", "Game install and data folders.",
             f"{_P}.settings:SettingsPage"),
    PageSpec("settings.external", "settings", "External Tools", "SteamCMD for Workshop uploads.",
             f"{_P}.settings:ExternalToolsPage"),
)

PAGES_BY_ID = {page.id: page for page in PAGES}


def pages_in(section: str) -> list[PageSpec]:
    return [page for page in PAGES if page.section == section and page.available]
