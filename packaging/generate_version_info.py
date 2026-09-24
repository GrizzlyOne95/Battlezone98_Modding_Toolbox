#!/usr/bin/env python3
"""Generate the PyInstaller Windows version resource for the toolbox."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

COMPANY_NAME = "GrizzlyOne95"
FILE_DESCRIPTION = "Battlezone Modding Toolbox"
INTERNAL_NAME = "BZModdingToolbox"
ORIGINAL_FILENAME = "BZModdingToolbox.exe"
PRODUCT_NAME = "Battlezone Modding Tools"


def normalize_version(value: str) -> tuple[tuple[int, int, int, int], str]:
    display = value.strip()
    if display.lower().startswith("v"):
        display = display[1:]
    match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?", display)
    if not match:
        return (0, 0, 0, 0), display or "0.0.0"
    parts = [int(part) if part is not None else 0 for part in match.groups(default="0")]
    return tuple(parts), display  # type: ignore[return-value]


def build_version_info(version: str) -> str:
    numeric, display = normalize_version(version)
    numbers = ", ".join(str(part) for part in numeric)
    strings = {
        "CompanyName": COMPANY_NAME,
        "FileDescription": FILE_DESCRIPTION,
        "FileVersion": display,
        "InternalName": INTERNAL_NAME,
        "OriginalFilename": ORIGINAL_FILENAME,
        "ProductName": PRODUCT_NAME,
        "ProductVersion": display,
    }
    table = ",\n".join(f"          StringStruct(u'{k}', u'{v}')" for k, v in strings.items())
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers=({numbers}), prodvers=({numbers}), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [
{table}
        ])
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="release version, e.g. 1.2.3 or v1.2.3")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_version_info(args.version), encoding="utf-8")


if __name__ == "__main__":
    main()
