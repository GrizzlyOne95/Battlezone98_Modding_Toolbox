"""Headless font sheet build: ``bztoolbox fonts build --font X.otf --out DIR``.

Writes ``bzfont.dds`` (Windows-1252) and ``bzfont_ru.dds`` (Windows-1251)
fitted to the stock slots, plus optional PNG previews.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence

from PIL import Image

from bztoolbox.modules.fonts import atlas

PREVIEW_TEXT = {
    "cp1252": ["ISDF COMMAND: Hauptquartier MW 0123456789", "Größe Übung ÄÖÜ äöü ß € éèçñ ÉÈ"],
    "cp1251": ["СВЯЗЬ С БАЗОЙ: ЖДИТЕ ПОДКРЕПЛЕНИЯ №7",
               "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ", "абвгдеёжзийклмнопрстуфхцчшщъыьэюя ЂЃЉЊЌЋЏЎЈҐЄЇІЅ"],
}


def write_preview(result: atlas.AtlasResult, path: Path) -> None:
    rows = [atlas.preview_text(result.image, result.codepage, line, unit=unit)
            for line in PREVIEW_TEXT[result.codepage] for unit in (5, 3)]
    canvas = Image.new("RGBA", (max(r.width for r in rows), sum(r.height for r in rows)), (10, 18, 10, 255))
    y = 0
    for row in rows:
        canvas.paste(row, (0, y))
        y += row.height
    canvas.save(path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="bztoolbox fonts build", description=__doc__.splitlines()[0])
    parser.add_argument("--font", required=True, help="Letter font (.ttf/.otf)")
    parser.add_argument("--symbol-font", help="Font for digits and punctuation (default: --font)")
    parser.add_argument("--fallback-font", help="Font for characters neither the font nor a recipe covers")
    parser.add_argument("--cap-height", type=int, default=56, help="Capital height in atlas pixels (default 56)")
    parser.add_argument("--weight", type=float, default=0.0, help="Extra stroke radius in atlas pixels (default 0)")
    parser.add_argument("--codepage", choices=["cp1252", "cp1251", "both"], default="both")
    parser.add_argument("--no-mipmaps", action="store_true", help="Write only the top level (not recommended)")
    parser.add_argument("--preview", action="store_true", help="Also write <sheet>.preview.png")
    parser.add_argument("--out", required=True, help="Output directory")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    source = atlas.GlyphSource(args.font, args.symbol_font, args.fallback_font)
    options = atlas.FitOptions(cap_height=args.cap_height, weight=args.weight)
    codepages = list(atlas.CODEPAGES) if args.codepage == "both" else [args.codepage]
    status = 0
    for codepage in codepages:
        name = atlas.CODEPAGES[codepage]
        result = atlas.build_atlas(source, codepage, options)
        atlas.save_dds(result.image, out / f"{name}.dds", mipmaps=not args.no_mipmaps)
        if args.preview:
            write_preview(result, out / f"{name}.preview.png")
        print(f"{name}.dds: built {len(result.constructed)} glyphs the font lacks"
              + (f"; no glyph for {''.join(result.missing)!r}" if result.missing else ""))
        if result.missing:
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
