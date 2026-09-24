"""PyInstaller runtime hook: make bundled native helpers loadable.

Ogre's plugin loader and Windows ``LoadLibrary`` search ``PATH``; add the
bundle root and the ogre-python package directory so the optional mesh
preview's render-system plugins resolve.
"""

import os
import sys

_base = getattr(sys, "_MEIPASS", None)
if _base:
    extra = [
        _base,
        os.path.join(_base, "Ogre"),
    ]
    os.environ["PATH"] = os.pathsep.join([p for p in extra if os.path.isdir(p)] + [os.environ.get("PATH", "")])
