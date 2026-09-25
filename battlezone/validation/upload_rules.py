"""Content rules the official Battlezone 98 Redux Uploader enforces.

Recovered from ``UploaderApp.exe`` (Steam, "Battlezone 98 Redux - Uploader
Tool"). The toolbox publishes through SteamCMD, which skips these checks, so
an item that passes here but breaks them uploads fine yet does not follow the
rules Rebellion set for Workshop content:

* the content folder may only contain language subfolders (``au en fr de es it
  pt ru``), holding ``.otf .des .inf .wav .txt`` files;
* ``.odf .inf .vdf .sdf .geo .map`` names are at most 8 characters before the
  extension (the whole name at most 12);
* ``.hgt`` terrain is refused (Redux uses ``.hg2``);
* core shader, material and font files may not be overridden.

The ``.ini`` / mapType / gameType rules live in the ``structure`` check.
"""

from __future__ import annotations

import fnmatch
import os
from typing import Iterator

LANGUAGE_FOLDERS = ("au", "en", "fr", "de", "es", "it", "pt", "ru")
LANGUAGE_EXTS = (".otf", ".des", ".inf", ".wav", ".txt")
SHORT_NAME_EXTS = (".odf", ".inf", ".vdf", ".sdf", ".geo", ".map")
MAX_FILE_NAME = 12            # 8 characters, the dot and a 3-letter extension
FORBIDDEN_OVERRIDES = (
    "sprites.material", "bzbase.material", "bzmaterialsgroup.material", "bzterrainbase.material",
    "bzvehiclebuildingbase.material", "ui.material", "uitexmat.material",
    "base.*", "terrain.*", "base-fragment.*", "terrain-fragment.*", "untextured*.*",
    "bzfont.dds", "bzfont_ru.dds",
)


def _issue(severity, message, path, rule, suggestion=""):
    from battlezone.validation.engine import Issue
    return Issue(severity, "upload-rules", message, path, rule_id=rule, suggestion=suggestion)


def check_upload_rules(ctx) -> Iterator:
    try:
        entries = sorted(os.listdir(ctx.root), key=str.lower)
    except OSError as exc:
        yield _issue("error", f"Could not list the content folder: {exc}", "", "upload-read-error")
        return
    for name in entries:
        path = os.path.join(ctx.root, name)
        lower = name.lower()
        if os.path.isdir(path):
            if lower not in LANGUAGE_FOLDERS:
                yield _issue("warning", f"Subfolder '{name}' is not a language folder; the official uploader "
                             "only accepts " + ", ".join(LANGUAGE_FOLDERS), name, "upload-subfolder",
                             "Move its files to the content root, or keep it out of the upload.")
                continue
            for root, _dirs, files in os.walk(path):
                for file_name in files:
                    if os.path.splitext(file_name)[1].lower() not in LANGUAGE_EXTS:
                        rel = ctx.rel(os.path.join(root, file_name))
                        yield _issue("warning", f"'{file_name}' is not allowed in a language folder (only "
                                     + " ".join(LANGUAGE_EXTS) + ")", rel, "upload-language-file",
                                     "Language folders only override text, fonts and speech.")
            continue
        ext = os.path.splitext(lower)[1]
        if ext in SHORT_NAME_EXTS and len(name) > MAX_FILE_NAME:
            yield _issue("warning", f"'{name}' is longer than 8 characters before the extension; the official "
                         f"uploader refuses long {ext} names", name, "upload-long-name",
                         "Rename it (and every reference to it) to 8 characters or fewer.")
        if ext == ".hgt":
            yield _issue("error", f"'{name}' is legacy .hgt terrain; Redux uses .hg2", name, "upload-hgt",
                         "Convert the terrain to .hg2 and remove the .hgt.")
        for pattern in FORBIDDEN_OVERRIDES:
            if fnmatch.fnmatch(lower, pattern):
                yield _issue("warning", f"'{name}' overrides a core game file the official uploader forbids "
                             "replacing", name, "upload-forbidden-override",
                             "Overriding it changes every map and UI; rename your copy unless that is intended.")
                break
