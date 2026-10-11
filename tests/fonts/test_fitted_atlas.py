"""Regression coverage for fonts that are too wide for the engine's sprite slots."""

from PIL import Image, ImageChops, ImageFont

from bztoolbox.modules.fonts.bz_generator import (
    GLYPH_LAYOUT,
    generate_sheet_image,
    render_fitted_glyph,
    resource_path,
    save_as_dds_native,
)


FONT_PATH = resource_path("Orbitron-Bold.ttf")


def test_wide_capitals_fill_height_without_spilling_into_neighbors():
    _, atlas = generate_sheet_image(
        FONT_PATH, FONT_PATH, 0, 0, 0, 0, 0, 56, False, False,
        fit_to_slots=True, stroke_width=2,
    )
    allowed = Image.new("L", atlas.size)
    for char, (x, y, w, h) in GLYPH_LAYOUT.items():
        allowed.paste(255, (x, y, x + w, y + h))
        ink = atlas.crop((x, y, x + w, y + h)).getchannel("A").getbbox()
        assert ink is not None, f"Missing glyph: {char}"
        if char in "AMWI":
            assert ink[3] - ink[1] == 56
            assert ink[3] == 68
    assert ImageChops.multiply(atlas.getchannel("A"), ImageChops.invert(allowed)).getbbox() is None


def test_nudges_clip_within_slot_and_weight_increases_coverage():
    font = ImageFont.truetype(FONT_PATH, 224)
    thin = render_fitted_glyph(font, "H", 40, 72, 56, 0, 0, 0)
    thick = render_fitted_glyph(font, "H", 40, 72, 56, 2, 0, 0)
    assert sum(value * count for value, count in enumerate(thick.histogram())) > sum(
        value * count for value, count in enumerate(thin.histogram())
    )
    shifted = render_fitted_glyph(font, "H", 40, 72, 56, 2, 100, 0)
    assert shifted.size == (40, 72)
    assert shifted.getbbox() is None
    raised = render_fitted_glyph(font, "H", 40, 72, 56, 2, 0, 5)
    assert raised.getbbox()[3] == thick.getbbox()[3] - 5


def test_dds_preserves_alpha_and_white_transparent_texels(tmp_path):
    _, atlas = generate_sheet_image(
        FONT_PATH, FONT_PATH, 0, 0, 0, 0, 0, 56, False, False,
        fit_to_slots=True, stroke_width=2,
    )
    output = tmp_path / "bzfont.dds"
    save_as_dds_native(atlas, output)
    with Image.open(output) as reloaded:
        assert reloaded.size == (1024, 1024)
        assert reloaded.convert("RGBA").tobytes() == atlas.tobytes()
        assert reloaded.getpixel((1000, 1000)) == (255, 255, 255, 0)
