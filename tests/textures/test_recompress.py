"""recompress: terrain protection, 4-alignment, mip append, quality gate, previews."""
import os
import struct

import numpy as np
from PIL import Image

from bztoolbox.modules.textures import bcpack, recompress, shrink_previews


def _smooth(w, h, alpha=False):
    y, x = np.mgrid[0:h, 0:w]
    rgba = np.empty((h, w, 4), np.uint8)
    rgba[..., 0] = (x * 255 // max(1, w - 1)).astype(np.uint8)
    rgba[..., 1] = (y * 255 // max(1, h - 1)).astype(np.uint8)
    rgba[..., 2] = 96
    rgba[..., 3] = ((x + y) % 200).astype(np.uint8) if alpha else 255
    return rgba


def _header(path):
    with open(path, "rb") as f:
        h = f.read(128)
    flags, height, width = struct.unpack("<3I", h[8:20])
    mips = struct.unpack("<I", h[28:32])[0] if flags & bcpack.DDSD_MIPMAPCOUNT else 1
    return h[84:88], width, height, mips


def test_normal_map_names():
    for name in ("x_n.dds", "x_nm.dds", "xnorm.dds", "abport_abport_Normal.dds",
                 "svshtnk_Material_Normal_Raw.dds"):
        assert recompress.is_normal_map(name), name
    assert not recompress.is_normal_map("abport_abport_BaseMap.dds")


def test_terrain_textures_are_left_alone(tmp_path):
    bcpack.write_dds_uncompressed(str(tmp_path / "moon_atlas_d.dds"), [_smooth(256, 256)])
    bcpack.write_dds_uncompressed(str(tmp_path / "skyface.dds"), [_smooth(256, 256)])
    (tmp_path / "moon.trn").write_text("[Sky]\nSkyTexture = skyface\n")
    trn = recompress.terrain_textures(str(tmp_path))
    for n in ("moon_atlas_d.dds", "skyface.dds"):
        r = recompress.convert(str(tmp_path / n), str(tmp_path / "bk"), False, {}, trn)
        assert "terrain texture" in r["skipped"]


def test_ui_by_name_is_skipped(tmp_path):
    bcpack.write_dds_uncompressed(str(tmp_path / "reticlesheet1.dds"), [_smooth(256, 256)])
    r = recompress.convert(str(tmp_path / "reticlesheet1.dds"), str(tmp_path / "bk"))
    assert r["skipped"] == "UI by name"


def test_small_unaligned_is_skipped(tmp_path):
    p = str(tmp_path / "sheet.dds")
    bcpack.write_dds_uncompressed(p, [_smooth(779, 528)])
    r = recompress.convert(p, str(tmp_path / "bk"))
    assert "not 4-aligned" in r["skipped"]


def test_large_unaligned_is_resampled_to_a_legal_bc_size(tmp_path):
    p = str(tmp_path / "port_d.dds")
    bcpack.write_dds_uncompressed(p, [_smooth(1254, 1254)])
    r = recompress.convert(p, str(tmp_path / "bk"))
    assert r["mips"] == "resampled 1254x1254->1256x1256"
    fourcc, w, h, mips = _header(p)
    assert (fourcc, w, h, mips) == (b"DXT1", 1256, 1256, 11)
    assert os.path.exists(tmp_path / "bk" / "port_d.dds")


def test_mipless_bc_gets_a_chain_and_keeps_level_zero(tmp_path):
    p = str(tmp_path / "big_d.dds")
    src = _smooth(256, 128, alpha=True)
    bcpack.write_dds(p, 256, 128, [bcpack.encode_level(src, "DXT5")], "DXT5")
    level0 = open(p, "rb").read()[128:]
    r = recompress.convert(p, str(tmp_path / "bk"))
    assert r["mips"] == "appended"
    fourcc, w, h, mips = _header(p)
    assert (fourcc, w, h, mips) == (b"DXT5", 256, 128, 9)
    assert open(p, "rb").read()[128:128 + len(level0)] == level0
    # second run: already compressed with a chain, nothing to do
    assert "already compressed" in recompress.convert(p, str(tmp_path / "bk2"))["skipped"]


def test_quality_gate_keeps_noise_normals_uncompressed(tmp_path):
    rng = np.random.default_rng(1)
    v = rng.normal(size=(256, 256, 3))
    v[..., 2] = np.abs(v[..., 2]) + 0.2
    v /= np.linalg.norm(v, axis=-1, keepdims=True)
    rgba = np.empty((256, 256, 4), np.uint8)
    rgba[..., :3] = np.clip((v + 1) * 127.5, 0, 255).astype(np.uint8)
    rgba[..., 3] = 255
    p = str(tmp_path / "noise_n.dds")
    bcpack.write_dds_uncompressed(p, [rgba])
    r = recompress.convert(p, str(tmp_path / "bk"))
    assert r.get("gated", "").startswith("kept uncompressed, mips added")
    levels, info = bcpack.read_dds(p)
    assert info["levels"] == 9 and np.array_equal(levels[0], rgba)
    # and with the gate off the BC result stands
    p2 = str(tmp_path / "noise2_n.dds")
    bcpack.write_dds_uncompressed(p2, [rgba])
    r2 = recompress.convert(p2, str(tmp_path / "bk"), quality_gate=False)
    assert r2["fmt"] == "DXT1" and not r2.get("gated")


def test_shrink_previews(tmp_path):
    Image.new("RGB", (2048, 1536), (10, 200, 30)).save(tmp_path / "msn01.bmp")
    Image.new("RGB", (2048, 2048), (1, 2, 3)).save(tmp_path / "notamission.bmp")
    (tmp_path / "msn01.bzn").write_bytes(b"x")
    n, before, after = shrink_previews.shrink(str(tmp_path), str(tmp_path / "bk"), 1024,
                                              log=lambda *_: None)
    assert n == 1 and after < before
    with Image.open(tmp_path / "msn01.bmp") as im:
        assert im.size == (1024, 768) and im.format == "BMP"
    with Image.open(tmp_path / "notamission.bmp") as im:
        assert im.size == (2048, 2048)
    assert (tmp_path / "bk" / "msn01.bmp").exists()
