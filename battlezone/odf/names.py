"""Player-visible names from ODFs (used by Localization and asset reports)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, Optional, Tuple, Union

from battlezone.odf.validator import ODFDocument, parse_odf


def clean_value(raw: str) -> str:
    """An ODF value without trailing ``//`` comment, ``;`` and surrounding quotes."""
    value = raw.split("//", 1)[0].strip().rstrip(";").strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1].strip()
    return value


def unit_name(doc: ODFDocument) -> Optional[str]:
    """The first ``unitName`` in the ODF (any section), or None.

    Internal file names and other fields are deliberately not used as a
    fallback: only the name players see is localizable.
    """
    for entries in doc.sections.values():
        for key, value, _line in entries:
            if key.strip().lower() == "unitname":
                return clean_value(value) or None
    return None


def read_unit_name(path: Union[str, os.PathLike]) -> Optional[str]:
    return unit_name(parse_odf(Path(path)))


def scan_unit_names(folder: Union[str, os.PathLike]) -> Iterator[Tuple[str, Optional[str]]]:
    """(path, unitName or None) for every ``.odf`` under ``folder``."""
    for root, _dirs, files in os.walk(folder):
        for name in sorted(files, key=str.lower):
            if name.lower().endswith(".odf"):
                path = os.path.join(root, name)
                try:
                    yield path, read_unit_name(path)
                except OSError:
                    yield path, None
