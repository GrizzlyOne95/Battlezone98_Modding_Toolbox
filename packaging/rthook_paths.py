"""PyInstaller runtime hook: make bundled native helpers loadable.

Ogre's plugin loader and Windows ``LoadLibrary`` search ``PATH``; add the
bundle root, the ogre-python package directory and the toolbox's own helper
folders so render-system plugins and the Ogre command-line tools resolve.
"""

import os
import sys

_base = getattr(sys, "_MEIPASS", None)
if _base:
    extra = [
        _base,
        os.path.join(_base, "Ogre"),
        os.path.join(_base, "bztoolbox", "modules", "meshes", "bin"),
        os.path.join(_base, "bztoolbox", "modules", "zfs", "native"),
    ]
    os.environ["PATH"] = os.pathsep.join([p for p in extra if os.path.isdir(p)] + [os.environ.get("PATH", "")])
