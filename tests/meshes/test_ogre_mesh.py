import math
import shutil
from pathlib import Path

import pytest

from battlezone.meshes import ogre
from bztoolbox.modules.meshes import MeshToObj, recalculate_normals

FIXTURES = Path(__file__).parent / "fixtures"
ALL = sorted(FIXTURES.glob("*.mesh"))


def _grid_height(x, z):
    return math.sin(x * 0.7) + math.cos(z * 0.5)


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.stem)
def test_reads_ogre_output(path):
    mesh = ogre.read_mesh(path)
    assert mesh.version in ("MeshSerializer_v1.8", "MeshSerializer_v1.100")
    assert mesh.endian == ("big" if "big" in path.stem else "little")
    if path.stem.startswith("shared"):
        geo = mesh.shared_geometry
        assert geo.vertex_count == 4
        assert [s.name for s in mesh.submeshes] == ["Left", "Right"]
        assert [s.indices for s in mesh.submeshes] == [[0, 2, 1], [1, 2, 3]]
        assert all(s.use32bit and s.uses_shared_vertices for s in mesh.submeshes)
        assert geo.attribute(7) == [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
        return
    grid, tri = mesh.submeshes
    assert grid.material == "MatA" and tri.material == "MatB"
    positions = grid.geometry.attribute(1)
    assert len(positions) == 36
    for i in range(6):
        for j in range(6):
            x, y, z = positions[i * 6 + j]
            assert (x, z) == (i - 3, j - 3)
            assert y == pytest.approx(_grid_height(x, z), abs=1e-5)
    if path.stem.startswith("strip"):
        assert grid.operation == 5
        assert all(len(set(t)) == 3 for t in grid.triangles())
    else:
        assert grid.operation == 4 and len(grid.triangles()) == 50
    assert tri.triangles() == [(0, 1, 2)]
    if path.stem.startswith("colour2uv"):
        assert grid.geometry.attribute(7, 1)[7] == pytest.approx((0.2, 0.2))
        assert "colour_diffuse" in _xml_text(mesh)


def _xml_text(mesh):
    import xml.etree.ElementTree as ET
    return ET.tostring(ogre.to_xml(mesh).getroot()).decode()


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.stem)
def test_obj_export(tmp_path, path):
    xml = MeshToObj.OgreXMLConverter().convert_to_xml(path, tmp_path)
    assert xml and Path(xml).exists()
    obj = tmp_path / "out.obj"
    MeshToObj.OgreXMLToOBJ().convert(xml, obj, create_mtl=True, texture_search_roots=[tmp_path])
    text = obj.read_text()
    assert text.count("\nv ") == (4 if "shared" in path.stem else 39)
    assert "usemtl" in text and (tmp_path / "out.mtl").exists()


def test_obj_cli_batch(tmp_path, monkeypatch):
    src = tmp_path / "in" / "sub"
    src.mkdir(parents=True)
    shutil.copy(FIXTURES / "basic_1_10_little.mesh", src / "tank.mesh")
    out = tmp_path / "out"
    monkeypatch.setattr("sys.argv", ["MeshToObj", "--batch", str(tmp_path / "in"), "-o", str(out)])
    assert MeshToObj.main() == 0
    assert (out / "sub" / "tank.obj").exists()


@pytest.mark.parametrize("name", ["shared_1_8_little.mesh", "basic_1_8_big.mesh", "basic_1_10_little.mesh"])
def test_recalculated_normals_are_written_back(tmp_path, name):
    target = tmp_path / name
    shutil.copy(FIXTURES / name, target)
    before = target.read_bytes()
    xml = ogre.mesh_to_xml_file(target, tmp_path / "tmp.xml")
    status = recalculate_normals.recalculate_normals(str(xml))
    assert status in ("CHANGED", "UNCHANGED")
    written = ogre.patch_normals(target, ogre.normals_from_xml(xml))
    after = target.read_bytes()
    assert len(after) == len(before)
    mesh = ogre.read_mesh(target)
    if name.startswith("shared"):
        assert status == "CHANGED" and written == 4
        # the quad lies in the XZ plane, wound so that its normal points up +Y
        for normal in mesh.shared_geometry.attribute(4):
            assert normal == pytest.approx((0.0, 1.0, 0.0), abs=1e-5)
    # only normal bytes may change: positions and texcoords are untouched
    original = ogre.read_mesh(before)
    for new, old in zip([mesh.shared_geometry] + [s.geometry for s in mesh.submeshes],
                        [original.shared_geometry] + [s.geometry for s in original.submeshes]):
        if new is None:
            continue
        assert new.attribute(1) == old.attribute(1)
        assert new.attribute(7) == old.attribute(7)


def test_rejects_other_files(tmp_path):
    bad = tmp_path / "x.mesh"
    bad.write_bytes(b"not a mesh at all")
    with pytest.raises(ogre.MeshError):
        ogre.read_mesh(bad)
    assert MeshToObj.OgreXMLConverter().convert_to_xml(bad, tmp_path) is None
