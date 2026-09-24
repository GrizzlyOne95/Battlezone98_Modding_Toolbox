import numpy as np
import pytest

from battlezone.terrain import hg2, lgt, mat, palettes
from battlezone.terrain.trn import TRNDocument, parse_number

TRN = (
    "[Size]\r\nMinX = -2560\r\nMinZ=-2560 // comment\r\nWidth=5120.0f\r\nDepth = 5120\r\nHeight=100\r\n"
    "[Size]\r\nWidth=3840\r\nDepth=3840\r\n"
    "[Color]\r\nPalette = \"..\\\\data\\\\MARS.ACT\" ; trailing\r\n"
    "[Atlases]\r\nMaterialName = marsatlas extra\r\n"
    "[TextureType3]\r\nSolidA0 = mars3sa0.map\r\nCapTo1_A0 = x.map\r\n"
    "[TextureType0]\r\nSolidA0 = mars0sa0.map\r\n"
    "[Sky]\r\nSkyTexture = redsky.map\r\n"
)


def test_trn_document():
    doc = TRNDocument.parse(TRN)
    assert doc.line_endings == "crlf"
    assert doc.size.width == 5120 and doc.size.min_z == -2560   # the first [Size] wins
    assert doc.zone_counts() == (4, 4)
    assert len(doc.duplicate_sections("size")) == 1
    assert doc.palette == "MARS.ACT"
    assert doc.material_name == "marsatlas"
    assert list(doc.texture_types()) == [0, 3]
    assert ("Sky", "SkyTexture", "redsky.map") in doc.map_references()
    assert doc.get("size", "HEIGHT") == "100"
    assert TRNDocument.parse("[Size]\nWidth=5000\nDepth=5120\n").zone_counts() is None
    assert TRNDocument.parse("a\nb\r\n").line_endings == "mixed"
    assert parse_number("12.5f") == 12.5 and parse_number("x") is None


def test_trn_read_file(tmp_path):
    path = tmp_path / "t.trn"
    path.write_bytes(TRN.encode("cp1252"))
    assert TRNDocument.read(path).line_endings == "crlf"
    path.write_bytes(TRN.replace("\r\n", "\n").encode())
    assert TRNDocument.read(path).line_endings == "lf"


def test_hg2_roundtrip(tmp_path):
    heights = (np.arange(2 * 256 * 3 * 256) % 8192).reshape(2 * 256, 3 * 256).astype(np.uint16)
    path = tmp_path / "t.hg2"
    hg2.write_hg2(path, heights, zones_x=3, zones_z=2)
    header, back = hg2.read_hg2(path)
    assert (header.zones_x, header.zones_z, header.zone_bits) == (3, 2, 8)
    assert np.array_equal(back, heights)
    m = hg2.HG2Map.read(path)
    assert m.world_size == (3 * 1280.0, 2 * 1280.0)
    path.write_bytes(path.read_bytes()[:-2])
    with pytest.raises(ValueError, match="mismatch"):
        hg2.read_hg2(path)


def test_lgt_roundtrip_and_border(tmp_path):
    rng = np.random.default_rng(3)
    light = rng.integers(0, 256, size=(256, 512), dtype=np.uint8)
    path = tmp_path / "t.lgt"
    lgt.write_lgt(path, light, 2, 1)
    raw = path.read_bytes()
    assert len(raw) == 3 * 256 * 256 and raw[0] == light[0, 0]
    back, zx, zz, size = lgt.read_lgt(path, 2, 1)
    assert (zx, zz, size) == (2, 1, 256) and np.array_equal(back, light)
    # TextureManager's BzrLgt-compatible packing: the border is the north-west pixel
    image = lgt.lgt_to_image(light)
    lgt.write_lgt(path, lgt.image_to_lgt(image), 2, 1, border=int(image[0, 0]))
    assert path.read_bytes()[0] == light[-1, 0]


def test_mat_roundtrip(tmp_path):
    entries = np.array([[mat.encode_entry(i % 8, (i + 1) % 8, rotation=i % 4) for i in range(128)]] * 64,
                       dtype=np.uint16)
    path = tmp_path / "t.mat"
    mat.write_mat(path, entries, 2, 1)
    assert np.array_equal(mat.read_mat(path, 2, 1), entries)
    assert mat.decode_entry(int(entries[0, 5])).base == 5


def test_one_palette_set():
    from bztoolbox.modules.textures import stock_palettes as tex
    from bztoolbox.modules.world import stock_palettes as world

    assert len(palettes.STOCK_ACT_NAMES) == 33
    for name in palettes.STOCK_ACT_NAMES:
        assert tex.get_stock_palette_bytes(name) == world.get_stock_act_bytes(name)
    with pytest.raises(KeyError):
        tex.get_stock_palette("nope.act")
    assert world.get_stock_palette("nope.act") is None
