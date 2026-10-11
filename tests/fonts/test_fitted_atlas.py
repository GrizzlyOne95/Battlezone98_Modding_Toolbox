"""Fitted bzfont atlases: stock slots, both code pages, built glyphs and mipmapped DDS."""

import pytest
from PIL import Image, ImageChops

from bztoolbox.modules.fonts import atlas
from bztoolbox.modules.fonts.bz_generator import generate_sheet_image, resource_path

FONT_PATH = resource_path("Orbitron-Bold.ttf")


@pytest.fixture(scope="module")
def source():
    return atlas.GlyphSource(FONT_PATH)


@pytest.fixture(scope="module")
def sheets(source):
    options = atlas.FitOptions(cap_height=56)
    return {cp: atlas.build_atlas(source, cp, options) for cp in atlas.CODEPAGES}


def slot_alpha(result, char):
    x, y, w, h = atlas.load_stock_layout(result.codepage)[char.encode(result.codepage)[0]]
    return result.image.getchannel("A").crop((x, y, x + w, y + h))


def test_stock_layouts_cover_both_code_pages_inside_the_atlas():
    western, russian = atlas.load_stock_layout("cp1252"), atlas.load_stock_layout("cp1251")
    assert len(western) == 215 and len(russian) == 220
    assert ord("A") in western and "Ж".encode("cp1251")[0] in russian
    for layout in (western, russian):
        for x, y, w, h in layout.values():
            assert 0 <= x and x + w <= atlas.ATLAS_SIZE and 0 <= y and y + h <= atlas.ATLAS_SIZE
    # Cyrillic descender letters get the taller 10-unit slots.
    assert russian["Щ".encode("cp1251")[0]][3] == 10 * atlas.ATLAS_SCALE


@pytest.mark.parametrize("codepage", list(atlas.CODEPAGES))
def test_every_slot_is_drawn_and_nothing_spills_into_neighbors(sheets, codepage):
    result = sheets[codepage]
    # Orbitron lacks some typographic punctuation; letters and digits never go missing.
    required = lambda c: (c.isascii() and c.isalnum()) or ("À" <= c <= "ÿ" and c.isalpha())         or "Ѐ" <= c <= "ӿ" or c in "^€№"
    assert not [c for c in result.missing if required(c)]
    allowed = Image.new("L", result.image.size)
    alpha = result.image.getchannel("A")
    for code, (x, y, w, h) in atlas.load_stock_layout(codepage).items():
        allowed.paste(255, (x, y, x + w, y + h))
        char = atlas.code_to_char(code, codepage)
        if char and not char.isspace() and char != "­" and char not in result.missing:
            assert alpha.crop((x, y, x + w, y + h)).getbbox() is not None, f"blank glyph {char!r}"
    assert ImageChops.multiply(alpha, ImageChops.invert(allowed)).getbbox() is None


def test_cyrillic_is_built_from_a_latin_only_font(sheets):
    built = set(sheets["cp1251"].constructed)
    assert set("БГДЖИЙЛПУФЦЧШЩЪЫЬЭЮЯбгджийлпуфцчшщъыьэюя") <= built
    # Shapes shared with Latin come straight from the font.
    a_cyr = slot_alpha(sheets["cp1251"], "А")
    a_lat = slot_alpha(sheets["cp1252"], "A")
    assert a_cyr.tobytes() == a_lat.tobytes()


def test_capitals_share_height_and_baseline_and_accents_fit_above(sheets):
    for char in "AMWIЖШ":
        result = sheets["cp1251" if char in "ЖШ" else "cp1252"]
        ink = slot_alpha(result, char).point(lambda a: 255 if a > 127 else 0).getbbox()
        assert ink[3] == atlas.BASELINE, char
        assert abs((ink[3] - ink[1]) - 56) <= 1, char
    for char in "ÄÉÖÜ":
        ink = slot_alpha(sheets["cp1252"], char).getbbox()
        assert ink[1] >= atlas.TOP_MARGIN - 1 and ink[3] <= atlas.BASELINE + 1, char
    underscore = slot_alpha(sheets["cp1252"], "_").getbbox()
    assert underscore is not None and underscore[3] <= 72


def test_condensed_stems_keep_stroke_weight(source):
    def stem_to_bar(preserve):
        options = atlas.FitOptions(cap_height=56, preserve_stems=preserve)
        img = atlas.fit_glyph(source.get("H"), "H", 40, 72, source, options)
        row = img.crop((0, 30, 40, 31)).tobytes()
        stem = sum(1 for v in row[:20] if v > 127)
        column = img.crop((20, 0, 21, 72)).tobytes()
        bar = sum(1 for v in column if v > 127)
        return stem / bar

    assert stem_to_bar(False) < 0.85
    assert 0.8 <= stem_to_bar(True) <= 1.35


def test_weight_and_nudges(source):
    plain = atlas.fit_glyph(source.get("H"), "H", 40, 72, source, atlas.FitOptions())
    heavy = atlas.fit_glyph(source.get("H"), "H", 40, 72, source, atlas.FitOptions(weight=1))
    coverage = lambda img: sum(i * n for i, n in enumerate(img.histogram()))
    assert coverage(heavy) > coverage(plain)
    raised = atlas.fit_glyph(source.get("H"), "H", 40, 72, source, atlas.FitOptions(v_nudges={"upper": 5}))
    assert raised.getbbox()[3] == plain.getbbox()[3] - 5
    gone = atlas.fit_glyph(source.get("H"), "H", 40, 72, source, atlas.FitOptions(h_nudge=100))
    assert gone.getbbox() is None


def test_dds_has_full_mip_chain_and_round_trips(sheets, tmp_path):
    image = sheets["cp1252"].image
    path = tmp_path / "bzfont.dds"
    atlas.save_dds(image, path)
    header = path.read_bytes()[:128]
    assert int.from_bytes(header[28:32], "little") == 11
    assert path.stat().st_size == 128 + sum(4 * (1024 >> i) ** 2 for i in range(11))
    with Image.open(path) as reloaded:
        assert reloaded.size == (1024, 1024)
        assert reloaded.convert("RGBA").tobytes() == image.tobytes()
        assert reloaded.getpixel((1000, 1000)) == (255, 255, 255, 0)


def test_gui_fit_mode_uses_the_atlas_builder():
    _, layer = generate_sheet_image(FONT_PATH, FONT_PATH, 0, 0, 0, 0, 0, 56, False, False,
                                    fit_to_slots=True, codepage="cp1251")
    x, y, w, h = atlas.load_stock_layout("cp1251")["Я".encode("cp1251")[0]]
    assert layer.getchannel("A").crop((x, y, x + w, y + h)).getbbox() is not None
