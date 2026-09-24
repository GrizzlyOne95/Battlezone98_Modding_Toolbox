"""The Battlezone UI font, registered for this process on every platform.

``BZONE.ttf`` ships once, in ``bztoolbox/resources/fonts``. It is registered
privately for the running process (nothing is installed on the system):

* Windows - ``AddFontResourceExW(..., FR_PRIVATE)``
* Linux   - fontconfig ``FcConfigAppFontAddFile`` (Tk uses Xft/fontconfig)
* macOS   - CoreText ``CTFontManagerRegisterFontsForURL`` (process scope)

Headers across the toolbox and the hosted tools use :func:`bz_font`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional, Set

from bztoolbox import paths

BZ_FONT_FILE = paths.resource("fonts", "BZONE.ttf")
BZ_FONT_FAMILY = "BZONE"

_registered: Set[str] = set()
_failed: Set[str] = set()


def _register_windows(path: str) -> bool:
    import ctypes

    FR_PRIVATE = 0x10
    return ctypes.windll.gdi32.AddFontResourceExW(path, FR_PRIVATE, 0) > 0  # type: ignore[attr-defined]


def _register_fontconfig(path: str) -> bool:
    import ctypes
    import ctypes.util

    name = ctypes.util.find_library("fontconfig")
    if not name:
        return False
    lib = ctypes.CDLL(name)
    lib.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.FcConfigAppFontAddFile.restype = ctypes.c_int
    return bool(lib.FcConfigAppFontAddFile(None, os.fsencode(path)))


def _register_coretext(path: str) -> bool:
    import ctypes

    cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    ct = ctypes.CDLL("/System/Library/Frameworks/CoreText.framework/CoreText")
    cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
    cf.CFURLCreateFromFileSystemRepresentation.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long,
                                                          ctypes.c_bool]
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
    ct.CTFontManagerRegisterFontsForURL.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
    raw = os.fsencode(path)
    url = cf.CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), False)
    if not url:
        return False
    try:
        kCTFontManagerScopeProcess = 1
        return bool(ct.CTFontManagerRegisterFontsForURL(url, kCTFontManagerScopeProcess, None))
    finally:
        cf.CFRelease(url)


def register_font_file(path) -> bool:
    """Make a TTF/OTF usable by Tk in this process; True on success."""
    path = str(Path(path).resolve())
    if path in _registered:
        return True
    if path in _failed or not os.path.exists(path):
        return False
    try:
        if sys.platform == "win32":
            ok = _register_windows(path)
        elif sys.platform == "darwin":
            ok = _register_coretext(path)
        else:
            ok = _register_fontconfig(path)
    except (ImportError, OSError, AttributeError, ValueError, TypeError):
        ok = False
    (_registered if ok else _failed).add(path)
    return ok


def bz_font(fallback: str = "Consolas") -> str:
    """The Battlezone font family if it could be registered, else ``fallback``."""
    return BZ_FONT_FAMILY if register_font_file(BZ_FONT_FILE) else fallback


def bz_font_path() -> Optional[str]:
    """File path of the Battlezone font, for tools that render text themselves."""
    return str(BZ_FONT_FILE) if BZ_FONT_FILE.exists() else None
