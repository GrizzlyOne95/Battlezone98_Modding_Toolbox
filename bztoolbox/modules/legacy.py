"""Mount the migrated tool UIs as shell pages.

Each loader receives the page container and returns ``(root_widget, app)``:
``root_widget`` is what the shell packs into the page (an embedded root, see
:mod:`bztoolbox.app.host`), ``app`` is the tool's own application object.

Project hooks (``*_project``) push the open project into a tool when the
user switches projects, so modules stop asking "Select folder..." for a
folder the toolbox already knows.
"""

from __future__ import annotations

from bztoolbox.app.host import EmbeddedRoot


def _hosted(container, app_cls, *args):
    root = EmbeddedRoot(container)
    return root, app_cls(root, *args)


# --- Project -----------------------------------------------------------------

def localization(container):
    from bztoolbox.modules.localization.localization import BZ98GuiApp

    return _hosted(container, BZ98GuiApp)


def localization_project(app, project) -> None:
    app.scan_folder_path.set(str(project.root))


def publishing(container):
    from bztoolbox.modules.publishing.uploader import WorkshopUploader

    return _hosted(container, WorkshopUploader)


def publishing_project(app, project) -> None:
    # The uploader loads (or creates) the shared project profile for this
    # folder itself, then offers to link it to an installed Workshop item with
    # the same mission files when it has none.
    if app.mod_path.get() != str(project.root):
        app._activate_content_folder(str(project.root), quiet=True)
        app.root.after(500, app.suggest_workshop_link)


# --- World & Terrain -----------------------------------------------------------

def world(container):
    from bztoolbox.modules.world.world_builder import BZ98TRNArchitect

    return _hosted(container, BZ98TRNArchitect)


def terrain_generator(container):
    from bztoolbox.modules.terrain_generator.gui import run_gui

    root = EmbeddedRoot(container)
    run_gui(root)
    return root, None


# --- Assets --------------------------------------------------------------------

_TEXTURES_INSTALLED = False


def textures(container):
    global _TEXTURES_INSTALLED
    from bztoolbox.modules.textures import tex_man, tex_man_entry, tex_man_stock_palette_entry

    if not _TEXTURES_INSTALLED:
        # Same integration order as the standalone tex_man_stock_palette_entry.main().
        tex_man_stock_palette_entry.install_stock_palette_integration()
        tex_man_entry.install_makemap_integration()
        _TEXTURES_INSTALLED = True
    return _hosted(container, tex_man.BZReduxSuite)


def fonts(container):
    from bztoolbox.modules.fonts.bz_generator import BzoneApp

    return _hosted(container, BzoneApp)


def holotext(container):
    from bztoolbox.modules.holotext.hud_gen import BZFontGenerator

    return _hosted(container, BZFontGenerator)


def meshes(container):
    from bztoolbox.modules.meshes.ogre_mesh_tools_gui import OgreMeshToolsGUI

    app = OgreMeshToolsGUI(container)
    return app, app


def audio(container):
    from bztoolbox.modules.audio.audio import BZRadio

    app = BZRadio(container)
    return app, app
