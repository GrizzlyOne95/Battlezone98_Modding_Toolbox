"""Build Battlezone 98 Redux font atlases (``bzfont.dds``/``bzfont_ru.dds``) from a vector font.

The engine reads glyph slots from ``bzfont.st`` (Windows-1252) or, for
Russian, ``bzfont_ru.st`` (Windows-1251). Each slot is a fixed rectangle on a
128-unit reference grid, and the renderer sizes the on-screen quad from the
slot itself, so a replacement sheet has to fill the stock slots exactly.
``stock_layouts.json`` holds both stock tables (code -> u, v, w, h in units).

Glyphs are drawn at a high source resolution and fitted into their slots:

* every glyph shares one baseline and one capital height;
* glyphs wider than their slot are condensed with their vertical stems kept
  at the font's stroke weight, rather than squeezed thin;
* accents above capitals are compacted into the space above the cap line;
* characters the font lacks (Cyrillic for Latin-only faces, the euro sign,
  small-cap forms) are assembled from the font's own glyphs where a recipe
  exists, so they match its stroke weight and proportions.

The DDS output carries a full mip chain, as the stock sheets do; without one
the HUD samples a 72-pixel glyph down to ~20 pixels and aliases.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFont

ATLAS_SIZE = 1024
REFERENCE_SIZE = 128
ATLAS_SCALE = ATLAS_SIZE // REFERENCE_SIZE
# Baseline position inside a slot, in atlas pixels from the slot top. Capitals
# sit on it; 9-unit slots keep 4 pixels below it for commas and Q tails, and the
# 10-unit Cyrillic descender slots keep 12.
BASELINE = 68
TOP_MARGIN = 1
SOURCE_CAP_HEIGHT = 420

CODEPAGES = {"cp1252": "bzfont", "cp1251": "bzfont_ru"}

# Characters that render as another character when the font lacks them.
SUBSTITUTES = {"\u00ad": "-"}


def load_stock_layout(codepage: str) -> Dict[int, Tuple[int, int, int, int]]:
    """Return {code: (x, y, w, h)} in atlas pixels for the stock table."""
    data = json.loads((Path(__file__).resolve().parent / "stock_layouts.json").read_text(encoding="utf-8"))
    return {
        int(code): (u * ATLAS_SCALE, v * ATLAS_SCALE, w * ATLAS_SCALE, h * ATLAS_SCALE)
        for code, (u, v, w, h) in data[codepage].items()
    }


def code_to_char(code: int, codepage: str) -> Optional[str]:
    try:
        return bytes([code]).decode(codepage)
    except UnicodeDecodeError:
        return None


# ---------------------------------------------------------------------------
# Ink: a coverage bitmap positioned relative to the pen origin on the baseline
# ---------------------------------------------------------------------------

@dataclass
class Ink:
    """An 8-bit coverage image whose top-left corner sits at (x, y) relative
    to the pen origin; y is negative above the baseline."""

    img: Image.Image
    x: float = 0.0
    y: float = 0.0

    @property
    def width(self) -> int:
        return self.img.width

    @property
    def height(self) -> int:
        return self.img.height

    @property
    def right(self) -> float:
        return self.x + self.img.width

    @property
    def bottom(self) -> float:
        return self.y + self.img.height

    @staticmethod
    def rect(x0: float, y0: float, x1: float, y1: float) -> "Ink":
        x0, y0, x1, y1 = (round(v) for v in (x0, y0, x1, y1))
        return Ink(Image.new("L", (max(1, x1 - x0), max(1, y1 - y0)), 255), x0, y0)

    def trimmed(self) -> Optional["Ink"]:
        box = self.img.getbbox()
        if box is None:
            return None
        return Ink(self.img.crop(box), self.x + box[0], self.y + box[1])

    def shifted(self, dx: float = 0.0, dy: float = 0.0) -> "Ink":
        return Ink(self.img, self.x + dx, self.y + dy)

    def at_left(self, x: float = 0.0) -> "Ink":
        return Ink(self.img, x, self.y)

    def mirrored(self) -> "Ink":
        return Ink(self.img.transpose(Image.Transpose.FLIP_LEFT_RIGHT), self.x, self.y)

    def flipped_about(self, axis_y: float) -> "Ink":
        """Flip vertically about the horizontal line y = axis_y."""
        return Ink(self.img.transpose(Image.Transpose.FLIP_TOP_BOTTOM), self.x, 2 * axis_y - self.bottom)

    def crop(self, x0=None, y0=None, x1=None, y1=None) -> Optional["Ink"]:
        """Keep the part inside a pen-coordinate box (None = unbounded)."""
        left = 0 if x0 is None else max(0, round(x0 - self.x))
        top = 0 if y0 is None else max(0, round(y0 - self.y))
        right = self.width if x1 is None else min(self.width, round(x1 - self.x))
        bottom = self.height if y1 is None else min(self.height, round(y1 - self.y))
        if right <= left or bottom <= top:
            return None
        return Ink(self.img.crop((left, top, right, bottom)), self.x + left, self.y + top).trimmed()

    def erase(self, x0, y0, x1, y1) -> "Ink":
        img = self.img.copy()
        ImageDraw.Draw(img).rectangle(
            [round(x0 - self.x), round(y0 - self.y), round(x1 - self.x) - 1, round(y1 - self.y) - 1], fill=0
        )
        return Ink(img, self.x, self.y)

    def scaled(self, factor: float, anchor_x: Optional[float] = None, anchor_y: float = 0.0) -> "Ink":
        """Uniformly scale about (anchor_x, anchor_y); anchor_x defaults to the ink centre."""
        if anchor_x is None:
            anchor_x = self.x + self.width / 2
        size = (max(1, round(self.width * factor)), max(1, round(self.height * factor)))
        return Ink(
            self.img.resize(size, Image.Resampling.LANCZOS),
            anchor_x + (self.x - anchor_x) * factor,
            anchor_y + (self.y - anchor_y) * factor,
        )

    def resized(self, width: int, height: int) -> "Ink":
        return Ink(self.img.resize((max(1, width), max(1, height)), Image.Resampling.LANCZOS), self.x, self.y)


def union(*inks: Optional[Ink]) -> Optional[Ink]:
    inks = [ink for ink in inks if ink is not None]
    if not inks:
        return None
    x0 = min(round(i.x) for i in inks)
    y0 = min(round(i.y) for i in inks)
    x1 = max(round(i.x) + i.width for i in inks)
    y1 = max(round(i.y) + i.height for i in inks)
    canvas = Image.new("L", (x1 - x0, y1 - y0))
    for ink in inks:
        layer = Image.new("L", canvas.size)
        layer.paste(ink.img, (round(ink.x) - x0, round(ink.y) - y0))
        canvas = ImageChops.lighter(canvas, layer)
    return Ink(canvas, x0, y0)


def hstack_rows(top: Ink, bottom: Ink) -> Ink:
    """Join two horizontal bands of the same glyph, top above bottom."""
    width = max(top.width, bottom.width)
    canvas = Image.new("L", (width, top.height + bottom.height))
    canvas.paste(top.img, (round(top.x) - round(min(top.x, bottom.x)), 0))
    canvas.paste(bottom.img, (round(bottom.x) - round(min(top.x, bottom.x)), top.height))
    return Ink(canvas, min(top.x, bottom.x), top.y)


def dilate(img: Image.Image, dx: int, dy: int = 0) -> Image.Image:
    """Grow coverage by dx pixels horizontally and dy vertically (box structuring element)."""

    def grow(image: Image.Image, amount: int, horizontal: bool) -> Image.Image:
        if amount <= 0:
            return image
        pad = (amount, 0) if horizontal else (0, amount)
        size = (image.width + pad[0], image.height + pad[1])
        out = Image.new("L", size)
        out.paste(image, (0, 0))
        span = 1
        # Union of shifts 0..amount via doubling: O(log amount) passes.
        while span * 2 <= amount + 1:
            shifted = Image.new("L", size)
            shifted.paste(out, (span, 0) if horizontal else (0, span))
            out = ImageChops.lighter(out, shifted)
            span *= 2
        rest = amount + 1 - span
        if rest > 0:
            shifted = Image.new("L", size)
            shifted.paste(out, (rest, 0) if horizontal else (0, rest))
            out = ImageChops.lighter(out, shifted)
        return out

    return grow(grow(img, dx, True), dy, False)


# ---------------------------------------------------------------------------
# Glyph source: font rendering, recipes and fallbacks
# ---------------------------------------------------------------------------

@dataclass
class CaseMetrics:
    cap: float     # height of H (or small-cap h)
    stem: float    # width of I (or i)
    bar: float     # thickness of E's top arm
    width: float   # width of H
    gap: float     # space between a capital and its accent


class GlyphSource:
    """Supplies source-resolution Ink for characters, building what the font lacks."""

    def __init__(self, letter_font: str, symbol_font: Optional[str] = None, fallback_font: Optional[str] = None):
        self.letter_font = self._sized(letter_font)
        self.symbol_font = self._sized(symbol_font) if symbol_font and symbol_font != letter_font else self.letter_font
        self.fallback_font = self._sized(fallback_font) if fallback_font else None
        self.upper = self._measure("H", "I", "E", "\u00cb")
        lower = self._font_ink(self.letter_font, "h")
        self.lower = self._measure("h", "i", "e", "\u00eb") if lower is not None else self.upper
        # Bank Gothic's lowercase are small caps (h has no ascender). For fonts
        # with true lowercase, most Cyrillic lowercase are small-cap forms and
        # must be built from capitals, not from b, h, m or t.
        x = self._font_ink(self.letter_font, "x")
        self.x_height = x.height if x is not None else self.lower.cap
        self.small_caps = lower is None or lower.height <= 1.08 * self.x_height
        self.constructed: List[str] = []
        self.missing: List[str] = []

    # -- font plumbing ----------------------------------------------------
    @staticmethod
    def _sized(path: str) -> ImageFont.FreeTypeFont:
        probe = ImageFont.truetype(path, 1000)
        box = probe.getbbox("H", anchor="ls")
        cap = max(1, box[3] - box[1])
        return ImageFont.truetype(path, max(8, round(1000 * SOURCE_CAP_HEIGHT / cap)))

    @staticmethod
    def has_glyph(font: ImageFont.FreeTypeFont, char: str) -> bool:
        """FreeType draws .notdef for unmapped characters; compare against a surely-unmapped one."""
        if char.isspace():
            return True
        mask = font.getmask(char)
        if mask.getbbox() is None:
            return False
        notdef = font.getmask("\U0010fffd")
        return not (mask.size == notdef.size and bytes(mask) == bytes(notdef))

    def _font_ink(self, font: ImageFont.FreeTypeFont, char: str) -> Optional[Ink]:
        if not self.has_glyph(font, char):
            return None
        box = font.getbbox(char, anchor="ls")
        img = Image.new("L", (max(1, box[2] - box[0]), max(1, box[3] - box[1])))
        ImageDraw.Draw(img).text((-box[0], -box[1]), char, font=font, anchor="ls", fill=255)
        return Ink(img, box[0], box[1]).trimmed()

    def _measure(self, h: str, i: str, e: str, e_accent: str) -> CaseMetrics:
        H = self._font_ink(self.letter_font, h)
        I = self._font_ink(self.letter_font, i)
        E = self._font_ink(self.letter_font, e)
        cap = H.height
        stem = I.width if I is not None else cap * 0.15
        bar = cap * 0.15
        if E is not None:
            column = E.img.crop((E.width * 3 // 5, 0, E.width * 3 // 5 + 1, E.height)).tobytes()
            run = 0
            while run < len(column) and column[run] > 127:
                run += 1
            bar = run or bar
        gap = cap * 0.12
        accented = self._font_ink(self.letter_font, e_accent)
        if accented is not None and E is not None:
            rows = accented.img.crop((0, 0, accented.width, max(1, round(E.y - accented.y)))).getbbox()
            if rows is not None:
                gap = max(1.0, E.y - (accented.y + rows[3]))
        return CaseMetrics(cap=cap, stem=stem, bar=bar, width=H.width, gap=gap)

    def font_for(self, char: str) -> ImageFont.FreeTypeFont:
        return self.letter_font if char.isalpha() else self.symbol_font

    # -- public -----------------------------------------------------------
    def get(self, char: str) -> Optional[Ink]:
        preferred = PREFER_RECIPE.get(char)
        if preferred is not None:
            self.constructed.append(char)
            return preferred(Recipe(self, lower=False)).trimmed()
        ink = self._font_ink(self.font_for(char), char)
        if ink is not None:
            return ink
        substitute = SUBSTITUTES.get(char)
        if substitute is not None:
            return self.get(substitute)
        if not self.small_caps and char in LOWERCASE_LOOKALIKES:
            ink = self._font_ink(self.letter_font, LOWERCASE_LOOKALIKES[char])
            if ink is not None:
                self.constructed.append(char)
                return ink
        recipe = RECIPES.get(char.upper()) if char.isalpha() else RECIPES.get(char)
        if recipe is not None and char.isalpha() and char.islower() and not self.small_caps:
            built = recipe(Recipe(self, lower=False))
            if built is not None:
                self.constructed.append(char)
                return built.trimmed().scaled(self.x_height / self.upper.cap, anchor_x=0, anchor_y=0)
        if recipe is not None:
            built = recipe(Recipe(self, lower=char.isalpha() and char.islower()))
            if built is not None:
                self.constructed.append(char)
                return built.trimmed()
        if char.isalpha() and char.islower():
            upper = self._font_ink(self.letter_font, char.upper())
            if upper is not None:
                self.constructed.append(char)
                return upper.scaled(self.lower.cap / self.upper.cap, anchor_x=upper.x)
        if self.fallback_font is not None:
            ink = self._font_ink(self.fallback_font, char)
            if ink is not None:
                self.constructed.append(char)
                return ink
        self.missing.append(char)
        return None


class Recipe:
    """Helpers for assembling a missing glyph from the font's own parts.

    Recipes are written once for capitals; for lowercase they use the font's
    lowercase (small-cap, for faces like Bank Gothic) parts and metrics.
    """

    def __init__(self, source: GlyphSource, lower: bool):
        self.source = source
        self.lower = lower
        m = source.lower if lower else source.upper
        self.C, self.S, self.T, self.W, self.gap = m.cap, m.stem, m.bar, m.width, m.gap
        self.D = 0.22 * self.C  # descender depth

    def g(self, latin: str) -> Ink:
        """A Latin letter (or digit) in this recipe's case, left edge at x=0."""
        char = latin.lower() if self.lower and latin.isalpha() else latin
        ink = self.source._font_ink(self.source.letter_font, char)
        if ink is None and char != latin:
            ink = self.source._font_ink(self.source.letter_font, latin)
            if ink is not None:
                ink = ink.scaled(self.C / self.source.upper.cap, anchor_x=ink.x)
        if ink is not None and not latin.isalpha():
            # Digits and marks: bring them to this case's cap height.
            if latin.isdigit() and abs(ink.height - self.C) > 1:
                ink = ink.scaled(self.C / ink.height, anchor_x=ink.x)
        return ink.at_left(0)

    def rect(self, x0, y0, x1, y1) -> Ink:
        return Ink.rect(x0, y0, x1, y1)

    def stem(self, x, top=None, bottom=0.0) -> Ink:
        return Ink.rect(x, -self.C if top is None else top, x + self.S, bottom)

    def hbar(self, x0, x1, y) -> Ink:
        """A horizontal bar whose top edge is at y."""
        return Ink.rect(x0, y, x1, y + self.T)

    def mark(self, base: Ink, mark_char: str) -> Optional[Ink]:
        mark = self.source._font_ink(self.source.letter_font, mark_char)
        if base is None or mark is None:
            return base
        mark = mark.shifted(base.x + base.width / 2 - (mark.x + mark.width / 2), base.y - self.gap - mark.bottom)
        return union(base, mark)

    def bowl_bottom(self) -> Ink:
        """Soft-sign shape: P turned upside down about the middle of the cap height."""
        return self.g("P").flipped_about(-self.C / 2)


def _build_be(r: Recipe):
    return union(r.bowl_bottom(), r.g("E").crop(y1=-r.C + r.T + 1))


def _build_ghe(r: Recipe):
    E = r.g("E")
    return union(E.crop(y1=-r.C + r.T + 1), E.crop(x1=r.S))


def _build_ghe_upturn(r: Recipe):
    ghe = _build_ghe(r)
    return union(ghe, r.rect(ghe.right - r.S, -r.C - 0.2 * r.C, ghe.right, -r.C + r.T))


def _build_de(r: Recipe):
    w, inset = r.W * 1.05, r.W * 0.2
    return union(
        r.hbar(inset, w, -r.C), r.stem(inset, bottom=-r.T + 1), r.stem(w - r.S),
        r.hbar(0, w, -r.T), r.rect(0, -r.T, r.S, r.D), r.rect(w - r.S, -r.T, w, r.D),
    )


def _build_zhe(r: Recipe):
    K = r.g("K")
    left = K.mirrored()
    return union(left, K.at_left(left.width - r.S))


def _build_ze(r: Recipe):
    return r.g("3")


def _build_i(r: Recipe):
    return r.g("N").mirrored()


def _build_short_i(r: Recipe):
    return r.mark(_build_i(r), "\u02d8")


def _build_el(r: Recipe):
    w, inset = r.W, r.W * 0.18
    return union(r.hbar(inset, w, -r.C), r.stem(inset), r.stem(w - r.S), r.hbar(0, inset + r.S, -r.T))


def _build_pe(r: Recipe):
    H = r.g("H")
    return union(H.crop(x1=r.S), H.crop(x0=H.width - r.S), r.hbar(0, H.width, -r.C))


def _build_u(r: Recipe):
    X = r.g("X")
    middle = X.width / 2
    return X.erase(middle, -r.C / 2, X.width + 1, 1)


def _build_ef(r: Recipe):
    O = r.g("O")
    cut = 0.15 * r.C
    top = O.crop(y1=-r.C / 2 - cut)
    bottom = O.crop(y0=-r.C / 2 + cut)
    ring = hstack_rows(top, bottom)
    ring = ring.shifted(0, -r.C / 2 - ring.height / 2 - ring.y)
    return union(ring, r.stem(O.width / 2 - r.S / 2))


def _build_tse(r: Recipe):
    w = r.W
    return union(r.stem(0), r.stem(w - r.S), r.hbar(0, w, -r.T), r.rect(w - r.S, -r.T, w, r.D))


def _build_che(r: Recipe):
    w, m = r.W, -0.45 * r.C
    return union(r.stem(0, bottom=m + r.T), r.hbar(0, w, m), r.stem(w - r.S))


def _build_sha(r: Recipe, descender: bool = False):
    w = r.W * 1.45
    parts = [r.stem(0), r.stem((w - r.S) / 2), r.stem(w - r.S), r.hbar(0, w, -r.T)]
    if descender:
        parts.append(r.rect(w - r.S, -r.T, w, r.D))
    return union(*parts)


def _build_hard_sign(r: Recipe):
    arm = 0.35 * r.W
    return union(r.hbar(0, arm + r.S, -r.C), r.bowl_bottom().at_left(arm))


def _build_yeru(r: Recipe):
    soft = r.bowl_bottom()
    return union(soft, r.stem(soft.width + 0.3 * r.W))


def _build_e_reversed(r: Recipe):
    C = r.g("C").mirrored()
    return union(C, r.hbar(0.45 * C.width, C.width, -r.C / 2 - r.T / 2))


def _build_yu(r: Recipe):
    O = r.g("O")
    gap = 0.3 * r.W
    return union(r.stem(0), r.hbar(r.S, r.S + gap + r.S, -r.C / 2 - r.T / 2), O.at_left(r.S + gap))


def _build_ya(r: Recipe):
    return r.g("R").mirrored()


def _build_ukrainian_ie(r: Recipe):
    C = r.g("C")
    return union(C, r.hbar(0, 0.72 * C.width, -r.C / 2 - r.T / 2))


def _build_tshe(r: Recipe, hook: bool = False):
    w, a, m = r.W, 0.22 * r.W, -0.55 * r.C
    parts = [r.hbar(0, 0.75 * w, -r.C), r.stem(a), r.hbar(a, w, m), r.stem(w - r.S, top=m)]
    if hook:
        parts[-1] = r.stem(w - r.S, top=m, bottom=r.D * 0.6)
        parts.append(r.hbar(0.62 * w, w, r.D * 0.6 - r.T))
    return union(*parts)


def _build_lje(r: Recipe):
    el = _build_el(r)
    return union(el, r.bowl_bottom().at_left(el.width - r.S))


def _build_nje(r: Recipe):
    H = r.g("H")
    return union(H, r.bowl_bottom().at_left(H.width - r.S))


def _build_dzhe(r: Recipe):
    w = r.W
    return union(r.stem(0), r.stem(w - r.S), r.hbar(0, w, -r.T), r.rect(w / 2 - r.S / 2, -r.T, w / 2 + r.S / 2, r.D))


def _build_numero(r: Recipe):
    N = r.g("N")
    o = r.source._font_ink(r.source.letter_font, "O")
    o = o.scaled(0.45 * r.C / o.height, anchor_x=o.x, anchor_y=0)
    o = o.at_left(N.width + 0.25 * r.S).shifted(0, -r.C - o.y)
    line_top = o.bottom + 0.12 * r.C
    return union(N, o, Ink.rect(o.x, line_top, o.right, line_top + 0.6 * r.T))


def _build_sharp_s(r: Recipe):
    """Single-width sharp s. The font's own \u00df is a wide SS ligature that turns
    into a blob when condensed into a 5-unit slot."""
    w, mid = 0.9 * r.W, -0.55 * r.C
    shoulder = 0.75 * w
    return union(
        r.stem(0), r.hbar(0, shoulder, -r.C), r.rect(shoulder - r.S, -r.C, shoulder, mid + r.T),
        r.hbar(0.35 * w, w, mid), r.rect(w - r.S, mid, w, 0), r.hbar(0.35 * w, w, -r.T),
    )


def _build_eth(r: Recipe):
    D = r.g("D").at_left(0.12 * r.W)
    return union(D, r.hbar(0, D.x + r.S + 0.3 * r.W, -r.C / 2 - r.T / 2))


def _build_o_slash(r: Recipe):
    O = r.g("O")
    pad = 0.1 * r.C
    w, h = round(O.width + 2 * pad), round(r.C + 2 * pad)
    img = Image.new("L", (w, h))
    ImageDraw.Draw(img).line([(0, h), (w, 0)], fill=255, width=max(1, round(0.8 * r.T)))
    return union(O, Ink(img, -pad, -r.C - pad))


def _build_thorn(r: Recipe):
    P = r.g("P")
    bowl = P.crop(x0=r.S)
    return union(r.stem(0), bowl.shifted(0, 0.2 * r.C))


def _build_caret(r: Recipe):
    caret = r.g("V").flipped_about(-r.C / 2)
    return caret.scaled(0.45, anchor_y=-r.C)


def _build_euro(r: Recipe):
    C = r.g("C").at_left(0.18 * r.W)
    t = 0.7 * r.T
    return union(C, Ink.rect(0, -0.62 * r.C, 0.62 * C.right, -0.62 * r.C + t),
                 Ink.rect(0, -0.38 * r.C - t, 0.62 * C.right, -0.38 * r.C))


ALIASES = {
    "\u0410": "A", "\u0412": "B", "\u0415": "E", "\u041a": "K", "\u041c": "M", "\u041d": "H",
    "\u041e": "O", "\u0420": "P", "\u0421": "C", "\u0422": "T", "\u0425": "X", "\u0405": "S",
    "\u0406": "I", "\u0408": "J", "\u0407": "\u00cf", "\u0401": "\u00cb",
}

# Cyrillic lowercase whose shape matches a Latin lowercase letter in fonts
# with true lowercase; the rest are small-cap forms of their capitals.
LOWERCASE_LOOKALIKES = {
    "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c", "\u0445": "x",
    "\u0443": "y", "\u0455": "s", "\u0456": "i", "\u0458": "j", "\u0451": "\u00eb", "\u0457": "\u00ef",
}

RECIPES: Dict[str, Callable[[Recipe], Optional[Ink]]] = {
    "\u0411": _build_be, "\u0413": _build_ghe, "\u0490": _build_ghe_upturn, "\u0414": _build_de,
    "\u0416": _build_zhe, "\u0417": _build_ze, "\u0418": _build_i, "\u0419": _build_short_i,
    "\u041b": _build_el, "\u041f": _build_pe, "\u0423": _build_u, "\u0424": _build_ef,
    "\u0426": _build_tse, "\u0427": _build_che, "\u0428": _build_sha,
    "\u0429": lambda r: _build_sha(r, descender=True), "\u042a": _build_hard_sign,
    "\u042b": _build_yeru, "\u042c": lambda r: r.bowl_bottom(), "\u042d": _build_e_reversed,
    "\u042e": _build_yu, "\u042f": _build_ya, "\u0404": _build_ukrainian_ie,
    "\u040b": _build_tshe, "\u0402": lambda r: _build_tshe(r, hook=True), "\u0409": _build_lje,
    "\u040a": _build_nje, "\u040f": _build_dzhe,
    "\u0403": lambda r: r.mark(_build_ghe(r), "\u00b4"),
    "\u040c": lambda r: r.mark(r.g("K"), "\u00b4"),
    "\u040e": lambda r: r.mark(_build_u(r), "\u02d8"),
    "\u2116": _build_numero, "\u20ac": _build_euro, "^": _build_caret,
    "\u00d0": _build_eth, "\u00d8": _build_o_slash, "\u00de": _build_thorn,
}

# Characters drawn from a recipe even when the font has them: glyphs whose
# natural form cannot survive the stock slot width. Built at capital height.
PREFER_RECIPE = {"\u00df": _build_sharp_s}
for _cyrillic, _latin in ALIASES.items():
    RECIPES[_cyrillic] = (lambda latin: (lambda r: r.g(latin) if latin.isascii() else _accented(r, latin)))(_latin)


def _accented(r: Recipe, latin: str) -> Optional[Ink]:
    char = latin.lower() if r.lower else latin
    return r.source._font_ink(r.source.letter_font, char)


# ---------------------------------------------------------------------------
# Fitting a glyph into its slot
# ---------------------------------------------------------------------------

@dataclass
class FitOptions:
    cap_height: int = 56          # atlas pixels from baseline to the top of H
    weight: float = 0.0           # extra stroke radius, atlas pixels (grows each side)
    preserve_stems: bool = True   # keep vertical stems at stroke weight when condensing
    h_nudge: int = 0
    v_nudges: Dict[str, int] = field(default_factory=dict)  # "upper"/"lower"/"digit"/"symbol"


def _nudge_key(char: str) -> str:
    return "upper" if char.isupper() else "lower" if char.islower() else "digit" if char.isdigit() else "symbol"


def _compact_marks(ink: Ink, cap: float, limit_top: float) -> Ink:
    """Shrink accents that rise above limit_top into the space above the cap line."""
    if ink.y >= limit_top:
        return ink
    rows = ink.img.tobytes()
    width = ink.width
    split = None
    # First empty row above the cap line separates a mark from its letter.
    for row in range(min(ink.height - 1, round(-cap - ink.y) - 1), -1, -1):
        if not any(rows[row * width:(row + 1) * width]):
            split = row
            break
    if split is None or split <= 0:
        # One connected shape (a tall symbol): scale it whole about the baseline.
        return ink.scaled(limit_top / ink.y, anchor_x=ink.x + ink.width / 2, anchor_y=0)
    mark = Ink(ink.img.crop((0, 0, width, split)), ink.x, ink.y).trimmed()
    body = Ink(ink.img.crop((0, split, width, ink.height)), ink.x, ink.y + split).trimmed()
    if mark is None or body is None:
        return ink
    gap = body.y - mark.bottom
    available = body.y - limit_top
    factor = min(1.0, available / (mark.height + gap))
    mark = mark.scaled(factor, anchor_y=body.y)
    return union(body, mark)


def fit_glyph(ink: Optional[Ink], char: str, slot_w: int, slot_h: int, source: GlyphSource, options: FitOptions) -> Image.Image:
    """Render ink into a slot_w x slot_h coverage image with the shared baseline."""
    slot = Image.new("L", (slot_w, slot_h))
    if ink is None:
        return slot
    scale = options.cap_height / source.upper.cap
    limit_top = -(BASELINE - TOP_MARGIN) / scale
    ink = _compact_marks(ink, source.upper.cap, limit_top)
    limit_bottom = (slot_h - BASELINE) / scale
    if ink.y >= 0 and ink.bottom > limit_bottom:
        # Wholly below the baseline (underscore): lift it to the slot bottom.
        ink = ink.shifted(0, limit_bottom - ink.bottom)
    elif ink.bottom > limit_bottom:
        # Squash only what hangs below the baseline.
        above = Ink(ink.img.crop((0, 0, ink.width, max(1, round(-ink.y)))), ink.x, ink.y) if ink.y < 0 else None
        below = Ink(ink.img.crop((0, max(0, round(-ink.y)), ink.width, ink.height)), ink.x, max(0.0, ink.y))
        below = below.resized(below.width, max(1, round(limit_bottom - below.y)))
        ink = hstack_rows(above, below) if above is not None else below

    max_w = slot_w if slot_w <= ATLAS_SCALE else slot_w - 2
    natural = ink.width * scale
    metrics = source.lower if char.islower() else source.upper
    extra = 0
    if natural > max_w and options.preserve_stems and max_w / scale > 2 * metrics.bar:
        # Condense around the stems: widen vertical strokes before the
        # horizontal squeeze so that afterwards they match the horizontal bars,
        # giving the even stroke of the font at its natural width instead of
        # hairline verticals under heavy horizontals.
        squeeze = (max_w / scale - metrics.bar) / max(1.0, ink.width - metrics.stem)
        extra = max(0, round(metrics.bar / squeeze - metrics.stem))
    weight = max(0, round(2 * options.weight / scale))
    img = dilate(ink.img, extra + weight, weight)
    ink = Ink(img, ink.x - (extra + weight) / 2, ink.y - weight / 2).trimmed() or ink

    out_w = min(max_w, max(1, round(ink.width * scale)))
    out_h = max(1, round(ink.height * scale))
    glyph = ink.img.resize((out_w, out_h), Image.Resampling.BOX)
    top = BASELINE + round(ink.y * scale) - options.v_nudges.get(_nudge_key(char), 0)
    left = (slot_w - out_w) // 2 + options.h_nudge
    slot.paste(glyph, (left, top))
    return slot


# ---------------------------------------------------------------------------
# Atlas and DDS
# ---------------------------------------------------------------------------

@dataclass
class AtlasResult:
    image: Image.Image
    codepage: str
    constructed: List[str]
    missing: List[str]


def build_atlas(source: GlyphSource, codepage: str = "cp1252", options: Optional[FitOptions] = None,
                show_grid: bool = False) -> AtlasResult:
    options = options or FitOptions()
    source.constructed, source.missing = [], []
    alpha = Image.new("L", (ATLAS_SIZE, ATLAS_SIZE))
    for code, (x, y, w, h) in sorted(load_stock_layout(codepage).items()):
        char = code_to_char(code, codepage)
        if char is None:
            continue
        alpha.paste(fit_glyph(source.get(char), char, w, h, source, options), (x, y))
    image = Image.new("RGBA", alpha.size, (255, 255, 255, 0))
    image.putalpha(alpha)
    if show_grid:
        draw = ImageDraw.Draw(image)
        for x, y, w, h in load_stock_layout(codepage).values():
            draw.rectangle([x, y, x + w - 1, y + h - 1], outline=(0, 255, 255, 120))
    return AtlasResult(image, codepage, list(source.constructed), list(source.missing))


def mip_chain(image: Image.Image) -> List[Image.Image]:
    """Area-averaged mip levels down to 1x1, each computed from the full-size image."""
    levels = [image]
    size = image.width
    while size > 1:
        size //= 2
        levels.append(image.resize((size, size), Image.Resampling.BOX))
    return levels


def save_dds(image: Image.Image, filename, mipmaps: bool = True) -> None:
    """Write uncompressed 32-bit RGBA DDS, with a full mip chain by default."""
    levels = mip_chain(image.convert("RGBA")) if mipmaps else [image.convert("RGBA")]
    width, height = image.size
    flags = 0x1 | 0x2 | 0x4 | 0x8 | 0x1000 | (0x20000 if mipmaps else 0)
    caps = 0x1000 | ((0x8 | 0x400000) if mipmaps else 0)
    with open(filename, "wb") as f:
        f.write(b"DDS ")
        f.write(struct.pack("<IIIIIII", 124, flags, height, width, width * 4, 0, len(levels) if mipmaps else 0))
        f.write(b"\x00" * 44)
        f.write(struct.pack("<IIIIIIII", 32, 0x41, 0, 32, 0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000))
        f.write(struct.pack("<IIIII", caps, 0, 0, 0, 0))
        for level in levels:
            f.write(level.tobytes())


def preview_text(atlas: Image.Image, codepage: str, text: str, unit: int = 3, background=(10, 18, 10, 255),
                 color=(120, 255, 120)) -> Image.Image:
    """Approximate how a line of text reads in game at `unit` screen pixels per reference unit."""
    layout = load_stock_layout(codepage)
    tinted = Image.new("RGBA", atlas.size, color + (0,))
    tinted.putalpha(atlas.getchannel("A"))
    level = atlas.width // REFERENCE_SIZE  # atlas pixels per unit
    glyphs = []
    pen = 0
    for char in text:
        code = char.encode(codepage, errors="replace")[0]
        if char == " " or code not in layout:
            pen += 4 * unit
            continue
        x, y, w, h = layout[code]
        sprite = tinted.crop((x, y, x + w, y + h))
        size = (max(1, w * unit // level), max(1, h * unit // level))
        glyphs.append((pen, sprite.resize(size, Image.Resampling.BOX)))
        pen += size[0] + unit
    canvas = Image.new("RGBA", (pen + 2 * unit, 11 * unit), background)
    for x, sprite in glyphs:
        canvas.alpha_composite(sprite, (x + unit, unit))
    return canvas
