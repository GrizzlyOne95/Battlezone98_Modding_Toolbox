import shutil
import struct
from pathlib import Path

import pytest

from battlezone.assets import build_graph
from battlezone.assets.graph import GraphCancelled

MESH = Path(__file__).parents[1] / "meshes" / "fixtures" / "basic_1_10_little.mesh"   # materials MatA, MatB


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\n", "\r\n").encode("latin-1"))


def dds(path: Path, width: int, height: int, fourcc: bytes, mips: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    head = bytearray(128)
    head[:4] = b"DDS "
    struct.pack_into("<II", head, 12, height, width)
    struct.pack_into("<I", head, 28, mips)
    head[84:88] = fourcc
    path.write_bytes(bytes(head))


@pytest.fixture
def mod(tmp_path):
    root = tmp_path / "mymod"
    write(root / "mymod.ini", '[DESCRIPTION]\nmissionName = "mymod"\n')
    write(root / "mymod.bzn", "PrjID [1] =\nmytank\nPrjID [1] =\navtank\nPrjID [1] =\nghost\n")
    write(root / "mymod.trn", "[Size]\nWidth=2560\nDepth=2560\n[Color]\nPalette = mars.act\n"
                              "[Atlases]\nMaterialName = mymodatlas\n[Sky]\nSkyTexture = mysky.map\n")
    for ext in (".hg2", ".mat", ".lgt"):
        (root / f"mymod{ext}").write_bytes(b"\0")
    write(root / "odf" / "mytank.odf", '[GameObjectClass]\nclassLabel = "wingman"\n'
                                        'geometryName = "mytank.xsi" // comment\nweaponName1 = "mygun"\n'
                                        'weaponName2 = "gspstab"\n')
    write(root / "odf" / "mygun.odf", '[WeaponClass]\nordName = "missingord"\n')
    shutil.copy(MESH, root / "mytank.mesh")
    write(root / "materials" / "tank.material",
          "material MatA\n{\n technique { pass { texture_unit { texture mytank_d.dds } } }\n}\n"
          "material mymodatlas\n{\n technique { pass { texture_unit { texture atlas.png } } }\n}\n")
    dds(root / "textures" / "mytank_d.dds", 256, 256, b"DXT1", mips=9)
    (root / "textures" / "mysky.dds").write_bytes(b"DDS " + b"\0" * 124)
    (root / "textures" / "unused.tga").write_bytes(b"x")
    return root


def test_edges(mod):
    g = build_graph(mod)
    kinds = {(e.source, e.target, e.kind) for e in g.edges}
    assert ("mymod.ini", "mymod.bzn", "ini-mission") in kinds
    assert ("mymod.bzn", "odf/mytank.odf", "bzn-odf") in kinds
    assert ("odf/mytank.odf", "mytank.mesh", "odf-asset") in kinds         # .xsi resolves to the .mesh
    assert ("odf/mytank.odf", "odf/mygun.odf", "odf-odf") in kinds
    assert ("mytank.mesh", "materials/tank.material", "mesh-material") in kinds
    assert ("materials/tank.material", "textures/mytank_d.dds", "material-texture") in kinds
    assert ("mymod.trn", "mymod.hg2", "trn-terrain") in kinds
    assert ("mymod.trn", "textures/mysky.dds", "trn-texture") in kinds     # .map -> converted texture
    assert ("mymod.trn", "materials/tank.material", "trn-material") in kinds


def test_queries(mod):
    g = build_graph(mod)
    # what breaks if the texture is renamed: the material, the mesh, the ODF, the mission, the ini
    dependents = g.closure("textures/mytank_d.dds", reverse=True)
    assert dependents[0] == "materials/tank.material"
    assert set(dependents) == {"materials/tank.material", "mytank.mesh", "mymod.trn", "odf/mytank.odf",
                               "mymod.bzn", "mymod.ini"}
    assert "textures/mytank_d.dds" in g.closure("mymod.ini")
    missing = {node.name for node, _ in g.missing()}
    assert missing == {"ghost.odf", "missingord.odf"}                       # avtank/gspstab are stock
    stock = {n.name for n, _ in g.not_in_project(include_stock=True) if n.stock}
    assert {"avtank.odf", "gspstab.odf", "mars.act"} <= stock
    assert [n.key for n in g.unreferenced()] == ["textures/unused.tga"]
    assert g.find("MYTANK_D.DDS").texture_bytes == int(256 * 256 * 0.5 * 4 / 3)
    assert g.summary()["missing"] == 2
    assert g.to_dict()["unreferenced"] == ["textures/unused.tga"]


def test_cancel(mod):
    import threading

    event = threading.Event()
    event.set()
    with pytest.raises(GraphCancelled):
        build_graph(mod, cancel=event)


def test_cli(mod, capsys):
    from bztoolbox.cli import main

    assert main(["deps", str(mod)]) == 1                 # missing references -> exit 1
    out = capsys.readouterr().out
    assert "ghost.odf" in out and "unused.tga" in out
    assert main(["deps", str(mod), "--why", "mytank_d.dds"]) == 0
    assert "mymod.ini" in capsys.readouterr().out
    assert main(["deps", str(mod), "--json"]) == 1
