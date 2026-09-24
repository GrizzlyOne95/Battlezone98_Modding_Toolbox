import os
import re
import numpy as np
import pytest

from bztoolbox.modules.world import map_preview as mp


def test_ingame_bmp_size_is_the_shell_convention():
    # Every stock and community map that ships a preview uses exactly this.
    assert mp.INGAME_BMP_SIZE == (108, 89)


def test_parse_trn_reads_atlas_and_solids(tmp_path):
    trn = tmp_path / "demo.trn"
    trn.write_text(
        "[Size]\nWidth=2560\nDepth=2560\n\n"
        "[Atlases]\nMaterialName\t= mn_detail_atlas\n\n"
        "[TextureType0]\nSolidA0 = MN00SA0.MAP\n\n"
        "[TextureType3]\nSolidA0 = MN33SA0.MAP  // with a trailing note\n",
        newline="\r\n")
    info = mp.parse_trn(str(trn))
    assert info["material"] == "mn_detail_atlas"
    assert info["solids"] == {0: "MN00SA0.MAP", 3: "MN33SA0.MAP"}
    assert info["size"]["width"] == 2560


def test_parse_trn_survives_a_value_with_a_comment(tmp_path):
    trn = tmp_path / "c.trn"
    trn.write_text("[TextureType1]\nSolidA0 = AB11SA0.MAP // not used\n", newline="\r\n")
    assert mp.parse_trn(str(trn))["solids"] == {1: "AB11SA0.MAP"}


def test_parse_trn_accepts_a_header_labelled_without_a_comment_marker(tmp_path):
    # 60 of the 236 shipped TRNs name the header this way, with no "//" to make
    # the label a comment. Requiring "]" to end the line dropped every section
    # after the first: the map then painted as one texture type and the preview
    # came out monochrome.
    trn = tmp_path / "bare.trn"
    trn.write_text(
        "[Atlases]\nMaterialName = eg_detail_atlas\n\n"
        "[TextureType0] Sand\nSolidA0 = EG00SA0.MAP\n\n"
        "[TextureType1] Liquid Sulphur\nSolidA0 = EG11SA0.MAP\n\n"
        "[TextureType3]\tLava Pool\t\nSolidA0 = EG33SA0.MAP\n",
        newline="\r\n")
    info = mp.parse_trn(str(trn))
    assert info["material"] == "eg_detail_atlas"
    assert info["solids"] == {
        0: "EG00SA0.MAP",
        1: "EG11SA0.MAP",
        3: "EG33SA0.MAP",
    }


def test_parse_trn_does_not_leak_a_later_section_into_an_earlier_body(tmp_path):
    # The failure mode was silent: type 0 simply swallowed the rest of the file
    # and still parsed, so only the picture showed that anything was wrong.
    trn = tmp_path / "leak.trn"
    trn.write_text(
        "[TextureType0] Sand\nSolidA0 = EG00SA0.MAP\n\n"
        "[TextureType1] Liquid Sulphur\nSolidA0 = EG11SA0.MAP\n",
        newline="\r\n")
    parts = mp._SECT.split(mp._strip_comments(trn.read_text()))
    bodies = {parts[i].lower(): parts[i + 1] for i in range(1, len(parts), 2)}
    assert set(bodies) == {"texturetype0", "texturetype1"}
    assert "EG11SA0.MAP" not in bodies["texturetype0"]
    # The label itself is part of the header and must not survive as a key.
    assert "Liquid" not in bodies["texturetype1"]


def test_parse_trn_is_unchanged_for_a_plainly_headed_trn(tmp_path):
    # The widening must not alter any of the TRNs that already parsed, which is
    # what keeps an untouched port re-rendering to the same bytes.
    trn = tmp_path / "plain.trn"
    trn.write_text(
        "[Size]\nWidth=2560\nDepth=2560\n\n"
        "[Atlases]\nMaterialName = mn_detail_atlas\n\n"
        "[TextureType0]\nSolidA0 = MN00SA0.MAP\n\n"
        "[TextureType2]\nSolidB0 = MN22SB0.MAP\n",
        newline="\r\n")
    info = mp.parse_trn(str(trn))
    assert info == {
        "material": "mn_detail_atlas",
        "solids": {0: "MN00SA0.MAP", 2: "MN22SB0.MAP"},
        "size": {"width": 2560.0, "depth": 2560.0},
    }


def test_section_regex_still_requires_a_header_to_own_its_line(tmp_path):
    # "[..]" mid-line is a value, not a section, and widening the tail must not
    # turn one into a section split.
    assert mp._SECT.search("SolidA0 = [TextureType4] EG00SA0.MAP\n") is None
    assert mp._SECT.search("  [TextureType4] a note\n") is not None


def test_hillshade_is_flat_for_flat_ground():
    assert mp._hillshade(np.zeros((16, 16), np.float32)) is None


def test_hillshade_centres_on_one():
    h = np.tile(np.linspace(0, 40, 32, dtype=np.float32), (32, 1))
    shade = mp._hillshade(h)
    assert shade.shape == (32, 32)
    assert 0.35 <= shade.min() and shade.max() <= 1.65


def test_downsample_area_averages_a_clean_factor():
    a = np.arange(64, dtype=np.float32).reshape(8, 8)
    out = mp._downsample(a, 4)
    assert out.shape == (4, 4)
    assert out[0, 0] == pytest.approx(a[0:2, 0:2].mean())


def test_downsample_is_identity_at_matching_size():
    a = np.zeros((5, 5), np.float32)
    assert mp._downsample(a, 5) is a


ADDON = os.path.join(mp.GAME_ROOT, "addon")
# A shipped port whose TRN uses only plain "[Section]" headers, so the widened
# regex cannot change how it parses. Re-rendering it must still land on the
# exact bytes that ship, which is the guard that the rest of the preview
# pipeline was left alone.
UNAFFECTED_PORT = "IAMP_TheAvengers"


@pytest.mark.skipif(not os.path.isdir(os.path.join(ADDON, UNAFFECTED_PORT)),
                    reason="Redux addon folder not installed")
def test_an_unaffected_port_still_re_renders_to_its_shipped_bytes(tmp_path):
    folder = os.path.join(ADDON, UNAFFECTED_PORT)
    trn = next(f for f in sorted(os.listdir(folder)) if f.lower().endswith(".trn"))
    stem = os.path.splitext(trn)[0]
    jpg, bmp = mp.write_previews(os.path.join(folder, trn), 512, out_dir=str(tmp_path))

    shipped_jpg = os.path.join(folder, f"{stem}_preview.jpg")
    shipped_bmp = next(f for f in os.listdir(folder)
                       if f.lower() == f"{stem}.bmp".lower())
    assert open(jpg, "rb").read() == open(shipped_jpg, "rb").read()
    assert open(bmp, "rb").read() == open(os.path.join(folder, shipped_bmp), "rb").read()


@pytest.mark.skipif(not os.path.isdir(ADDON), reason="Redux addon folder not installed")
def test_every_shipped_trn_parses_at_least_one_texture_type():
    # The bug read as a map defect until the count came out: a TRN that resolves
    # exactly one texture type while declaring several is the signature.
    thin = []
    for entry in sorted(os.listdir(ADDON)):
        folder = os.path.join(ADDON, entry)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.lower().endswith(".trn"):
                continue
            path = os.path.join(folder, name)
            declared = len(re.findall(r"(?mi)^[ \t]*\[TextureType\d+\]", open(
                path, "r", errors="ignore").read()))
            found = len(mp.parse_trn(path)["solids"])
            if declared > 1 and found <= 1:
                thin.append((os.path.join(entry, name), declared, found))
    assert not thin, f"TRNs that lost their texture types: {thin}"
