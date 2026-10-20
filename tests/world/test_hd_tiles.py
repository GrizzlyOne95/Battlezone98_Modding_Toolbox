"""Offline contracts for authored tiles, portable bundles and native v2 mapping."""
import copy
import json
import shutil
import struct
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from battlezone.images import dds
from battlezone.terrain.hd_tiles import (
    MANIFEST, RUNTIME_SCHEMA, build_bundle, check_bundle, inspect_dds,
    load_project, new_project, read_layout, save_project,
)


@pytest.fixture
def project(tmp_path):
    sources = tmp_path / "art"
    sources.mkdir()
    layout = sources / "map.csv"
    layout.write_text(",0,0,.25,.25\nMA00SA0.MAP,.25,0,.25,.25\n"
                      "MA00SB0.MAP,.5,0,.25,.25\nMA00SA0.MAP,.75,0,.25,.25\n")
    for alias, color in (("ma00sa0", (220, 70, 20)), ("ma00sb0", (30, 190, 80))):
        for c, rgb in (("d", color), ("n", (180, 220, 240)), ("s", (80, 80, 80))):
            Image.new("RGB", (16, 16), rgb).save(sources / f"{alias}_{c}.png")
    return new_project(sources, layout, material="TEST_MARS", diffuse_resource="mars_d.dds",
                       normal_resource="mars_n.dds", specular_resource="mars_s.dds",
                       default_alias="MA00SA0.MAP", tile_size=16, prefix="MyMod")


def test_portable_bundle_round_trip_preserves_all_rectangles(project, tmp_path):
    output = tmp_path / "bundle"
    report = build_bundle(project, output)
    assert (report["slices"], report["rectangles"], report["resourceCount"]) == (2, 4, 6)
    assert report["conversion"] == {"preserved": 0, "converted": 6}
    assert report["processRamEstimate"] is None
    assert report["estimatedGpuArrayBytes"] > 0
    binding = json.loads((output / MANIFEST).read_text())["materials"]["TEST_MARS"]
    assert [r["slice"] for r in binding["tileRects"]] == [0, 0, 1, 0]
    assert binding["normal"]["encoding"] == "rgb-xyz-linear"
    assert binding["normal"]["sourceResource"] == "mars_n.dds"
    assert binding["releaseSourceTextures"] is True
    assert "TerrainHdEnabled=1" in (output / "README.txt").read_text()
    moved = tmp_path / "moved"
    output.rename(moved)
    shutil.rmtree(tmp_path / "art")
    assert check_bundle(moved)["sha256"] == report["sha256"]
    rebuilt = build_bundle(load_project(moved), tmp_path / "rebuilt")
    assert rebuilt["sha256"] == report["sha256"]


def test_rgb24_normals_renormalized_and_opengl_flips_green(project, tmp_path):
    project["normalSpace"] = "opengl"
    out = tmp_path / "bundle"
    build_bundle(project, out)
    path = out / "resources/MyMod_ma00sa0_n.dds"
    assert inspect_dds(path)["format"] == "RGB24"
    levels, _ = dds.read_dds(str(path))
    assert len(levels) == 5 and levels[0][0, 0, 1] == 35
    for mip in levels[1:]:
        vectors = mip[:, :, :3].astype(float) / 127.5 - 1
        np.testing.assert_allclose(np.linalg.norm(vectors, axis=2), 1, atol=.012)


def test_authored_dds_mips_are_preserved_byte_for_byte(project, tmp_path):
    original = tmp_path / "first"
    report = build_bundle(project, original)
    imported = load_project(original)
    for alias, channels in imported["tiles"].items():
        for channel in channels:
            channels[channel] = str(original / "resources" / f"MyMod_{alias[:-4].lower()}_{channel.lower()}.dds")
    second = build_bundle(imported, tmp_path / "second")
    assert second["conversion"] == {"preserved": 6, "converted": 0}
    assert second["sha256"] == report["sha256"]


def test_recipe_paths_are_relative_and_existing_output_is_protected(project, tmp_path):
    recipe = tmp_path / "authoring.json"
    save_project(recipe, project)
    assert json.loads(recipe.read_text())["layout"] == "art/map.csv"
    assert load_project(recipe) == project
    with pytest.raises(FileExistsError):
        save_project(recipe, project)
    output = tmp_path / "output"
    output.mkdir()
    (output / "keep.txt").write_text("untouched")
    with pytest.raises(ValueError, match="already exists"):
        build_bundle(project, output)
    assert (output / "keep.txt").read_text() == "untouched"


@pytest.mark.parametrize("mutation,match", [
    (lambda p: p.update(tileSize=32), "no upscaling"),
    (lambda p: p["tiles"]["MA00SA0.MAP"].pop("N"), "Missing normal"),
    (lambda p: p.update(prefix="../oops"), "simple resource"),
    (lambda p: p.update(normalSpace="packed-ag"), "normalSpace"),
    (lambda p: p["resources"].update(D="MyMod_ma00sa0_d.dds"), "collides"),
])
def test_invalid_inputs_fail_without_partial_outputs(project, tmp_path, mutation, match):
    mutation(project)
    with pytest.raises(ValueError, match=match):
        build_bundle(project, tmp_path / "output")
    assert not (tmp_path / "output").exists()
    assert not list(tmp_path.glob(".output-*"))


def test_cancel_cleans_own_temporary_directory(project, tmp_path):
    class Cancelled(Exception):
        pass
    def cancel():
        raise Cancelled()
    with pytest.raises(Cancelled):
        build_bundle(project, tmp_path / "output", check_cancelled=cancel)
    assert not (tmp_path / "output").exists()
    assert not list(tmp_path.glob(".output-*"))


@pytest.mark.parametrize("rows", [
    "MA00SA0.MAP,0,0,.25,.25\nMA00SB0.MAP,.0000005,0,.25,.25\n",
    "MA00SA0.MAP,nan,0,.25,.25\n",
    "MA00SA0.MAP,.8,0,.25,.25\n",
])
def test_bad_or_ambiguous_rectangles_are_rejected(tmp_path, rows):
    layout = tmp_path / "bad.csv"
    layout.write_text(rows)
    with pytest.raises(ValueError):
        read_layout(layout, "MA00SA0.MAP")


@pytest.mark.parametrize("damage", ["truncate", "dx10", "cube", "mips", "pitch"])
def test_dds_validation_rejects_unsupported_containers(project, tmp_path, damage):
    out = tmp_path / "bundle"
    build_bundle(project, out)
    path = out / "resources/MyMod_ma00sa0_n.dds"
    blob = bytearray(path.read_bytes())
    if damage == "truncate":
        blob.pop()
    elif damage == "dx10":
        struct.pack_into("<I", blob, 80, 4)
        blob[84:88] = b"DX10"
    elif damage == "cube":
        struct.pack_into("<I", blob, 112, 0x200)
    elif damage == "mips":
        struct.pack_into("<I", blob, 28, 99)
    else:
        struct.pack_into("<I", blob, 20, 256)
    path.write_bytes(blob)
    with pytest.raises(ValueError):
        check_bundle(out)


def test_runtime_mapping_and_guards_must_match_recipe(project, tmp_path):
    out = tmp_path / "bundle"
    build_bundle(project, out)
    manifest = json.loads((out / MANIFEST).read_text())
    binding = manifest["materials"]["TEST_MARS"]
    for mutation in (lambda b: b.update(diffuseResource="wrong.dds"),
                     lambda b: b["tileRects"][2].update(slice=0),
                     lambda b: b["normal"]["tiles"].pop("1"),
                     lambda b: b["tiles"].update({"0": "../outside.dds"})):
        changed = copy.deepcopy(manifest)
        mutation(changed["materials"]["TEST_MARS"])
        (out / MANIFEST).write_text(json.dumps(changed))
        with pytest.raises(ValueError):
            check_bundle(out)


def test_import_cr_export_without_cr_scripts_or_atlas_pixels(project, tmp_path):
    original = tmp_path / "original"
    report = build_bundle(project, original)
    export = tmp_path / "cr-export"
    shutil.copytree(original / "resources", export)
    shutil.copyfile(project["layout"], export / "native_layout.csv")
    manifest = json.loads((original / MANIFEST).read_text())
    assert manifest["schema"] == RUNTIME_SCHEMA
    (export / "cr_mars_hd.json").write_text(json.dumps(manifest))
    aliases = {a: {c: f"MyMod_{a[:-4].lower()}_{c.lower()}.dds" for c in ("D", "N", "S")}
               for a in project["tiles"]}
    (export / "source_tiles.json").write_text(json.dumps({
        "schema": "cr-mars-hd-source-tiles-v1", "aliases": aliases,
        "tileSize": 16, "defaultAlias": "MA00SA0.MAP"}))
    imported = load_project(export)
    imported["prefix"] = "MyMod"
    result = build_bundle(imported, tmp_path / "result")
    assert result["sha256"] == report["sha256"]
    assert result["conversion"]["preserved"] == 6


def test_cli_init_build_check_and_json_error(project, tmp_path, capsys):
    from bztoolbox import cli
    recipe = tmp_path / "recipe.json"
    assert cli.main(["terrain", "hd-tiles", "init", str(tmp_path / "art"),
                     "--layout", project["layout"], "--material", "TEST", "--diffuse-resource", "mars_d.dds",
                     "--default-alias", "MA00SA0.MAP", "--tile-size", "16", "--out", str(recipe), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["tiles"] == 2
    out = tmp_path / "bundle"
    assert cli.main(["terrain", "hd-tiles", "build", str(recipe), "--out", str(out), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["resourceCount"] == 2
    assert cli.main(["terrain", "hd-tiles", "check", str(out), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["slices"] == 2
    assert cli.main(["terrain", "hd-tiles", "build", str(recipe), "--out", str(out), "--json"]) == 2
    assert "already exists" in json.loads(capsys.readouterr().out)["error"]


def test_emissive_channel_is_explicit_and_complete(project, tmp_path):
    project["resources"]["E"] = "mars_e.dds"
    for alias in project["tiles"]:
        path = tmp_path / (alias + "_e.png")
        Image.new("RGB", (16, 16), (255, 50, 0)).save(path)
        project["tiles"][alias]["E"] = str(path)
    output = tmp_path / "bundle"
    report = build_bundle(project, output)
    assert report["resourceCount"] == 8
    entry = json.loads((output / MANIFEST).read_text())["materials"]["TEST_MARS"]["emissive"]
    assert entry["sourceResource"] == "mars_e.dds"
    assert len(entry["tiles"]) == 2


def test_partial_authored_normal_chain_selects_matching_mip_then_generates_tail(project, tmp_path):
    rgba = np.full((16, 16, 4), (128, 128, 255, 255), np.uint8)
    authored = np.full((8, 8, 4), (64, 192, 225, 255), np.uint8)
    source = tmp_path / "authored.dds"
    dds.write_dds_uncompressed(str(source), [rgba, authored], alpha=False)
    project["tiles"]["MA00SA0.MAP"]["N"] = str(source)
    project["tileSize"] = 8
    output = tmp_path / "bundle"
    build_bundle(project, output)
    levels, _ = dds.read_dds(str(output / "resources/MyMod_ma00sa0_n.dds"))
    np.testing.assert_array_equal(levels[0], authored)
    assert [lv.shape[:2] for lv in levels] == [(8, 8), (4, 4), (2, 2), (1, 1)]


def test_alpha_data_is_rejected_and_failed_conversion_cleans_staging(project, tmp_path):
    source = Path(project["tiles"]["MA00SB0.MAP"]["S"])
    Image.new("RGBA", (16, 16), (80, 80, 80, 254)).save(source)
    with pytest.raises(ValueError, match="alpha data"):
        build_bundle(project, tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()
    assert not list(tmp_path.glob(".bundle-*"))


def test_legacy_rgba_dds_writer_keeps_channels_and_authored_mips(tmp_path):
    from bztoolbox.modules.textures import bcpack
    levels = [np.random.default_rng(4).integers(0, 256, (8, 8, 4), dtype=np.uint8),
              np.full((4, 4, 4), (33, 66, 99, 123), np.uint8)]
    path = tmp_path / "legacy.dds"
    bcpack.write_dds_uncompressed(str(path), levels)
    decoded, info = bcpack.read_dds(str(path))
    assert info["bits"] == 32 and info["levels"] == 2
    for a, b in zip(decoded, levels):
        np.testing.assert_array_equal(a, b)
