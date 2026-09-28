"""Legacy .vdf/.sdf + .geo + .map -> Redux .mesh/.skeleton/.material."""

import math
import os
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from battlezone.images.legacy_map import decode_map, encode_dds_rgba
from battlezone.meshes import legacy_port, ogre
from battlezone.meshes.legacy import read_geo, read_sdf
from battlezone.meshes.legacy_port import PortOptions, build_port, port_legacy_model
from battlezone.meshes.ogre_skeleton import Animation, Bone, Keyframe, Skeleton, Track, read_skeleton, write_skeleton

IDENTITY = (1, 0, 0, 0, 1, 0, 0, 0, 1)
FIXTURES = Path(__file__).parent / "fixtures"


def make_geo(name, positions, faces):
    """``faces``: (corner vertex indices, corner uvs, plane normal, texture)."""
    out = struct.pack("<4si16siii", b"OEG.", 0, name.encode(), len(positions), len(faces), 0)
    out += b"".join(struct.pack("<3f", *p) for p in positions)
    out += b"".join(struct.pack("<3f", 0, 1, 0) for _ in positions)
    for index, (corners, uvs, normal, texture) in enumerate(faces):
        out += struct.pack("<iiBBBffffi3s13sii", index, len(corners), 10, 20, 30, *normal, 0.0, 0,
                           b"\x04\x01\x00", texture.encode(), -1, 0)
        out += b"".join(struct.pack("<iiff", v, v, *uv) for v, uv in zip(corners, uvs))
    return out


def top_quad(name, texture="tex00", size=1.0):
    """A square in the XZ plane; corners in the stock order (inward plane normal -Y)."""
    positions = [(0, 0, 0), (size, 0, 0), (size, 0, size), (0, 0, size)]
    uvs = [(0, 0), (1, 0), (1, 1), (0, 1)]
    return make_geo(name, positions, [([0, 1, 2, 3], uvs, (0, -1, 0), texture)])


def make_bwd(kind, name, records, bands):
    """``records``: (band, slot, name, matrix12, parent, class)."""
    count = max(slot for _, slot, *_ in records) + 1
    fmt = struct.Struct("<8s12f8s7fii" if kind == "vdf" else "<8s12f8s7fiii4f")
    table = bytearray(fmt.size * count * bands)
    for band, slot, part, matrix, parent, klass in records:
        extra = (0,) * 5 if kind == "sdf" else ()
        fields = (part.encode(), *matrix, parent.encode(), 0, 0, 0, 1, 1, 1, 1, klass, 0) + extra
        fmt.pack_into(table, (band * count + slot) * fmt.size, *fields)
    block = (b"VDFC" if kind == "vdf" else b"SDFC")
    size = 68 if kind == "vdf" else 78
    header = struct.pack("<4si4sii", b"BWD2", 8, b"REV\0", 12, 0)
    body = struct.pack("<4si", block, size) + name.encode().ljust(size - 8, b"\0")
    geo_tag = b"VGEO" if kind == "vdf" else b"SGEO"
    return header + body + struct.pack("<4sii", geo_tag, 12 + len(table), count) + bytes(table)


def matrix(rotation=IDENTITY, position=(0, 0, 0)):
    return tuple(rotation) + tuple(position)


def rot_y(degrees):
    """Legacy right/up/front axes of a rotation about +Y (right-handed, column vectors)."""
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return (c, 0, -s, 0, 1, 0, s, 0, c)


def loader(files):
    lowered = {k.lower(): v for k, v in files.items()}
    return lambda name: lowered.get(name.lower())


class StructureTests(unittest.TestCase):
    def setUp(self):
        self.files = {"root.geo": top_quad("root"), "arm.geo": top_quad("arm", "tex01")}
        self.sdf = make_bwd("sdf", "Test", [
            (0, 0, "root", matrix(position=(1, 2, 3)), "WORLD", 61),
            (0, 1, "arm", matrix(rot_y(90), (0.5, 0, 0)), "root", 61),
        ], 6)

    def port(self, **options):
        return build_port(self.sdf, "sdf", "test", loader(self.files), PortOptions(**options))

    def test_bones_mirror_x(self):
        result = self.port()
        root, arm = result.skeleton.bones
        self.assertEqual((root.name, root.parent), ("root", None))
        self.assertEqual((arm.name, arm.parent), ("arm", 0))
        self.assertEqual(root.position, (-1, 2, 3))
        self.assertEqual(arm.position, (-0.5, 0, 0))
        # +90 about Y mirrored in X is -90 about Y
        x, y, z, w = arm.orientation
        self.assertAlmostEqual(y, -math.sqrt(0.5), places=6)
        self.assertAlmostEqual(w, math.sqrt(0.5), places=6)
        self.assertEqual((x, z), (0.0, 0.0))

    def test_vertices_in_model_space_and_weighted(self):
        result = self.port()
        self.assertEqual(len(result.mesh.submeshes), 2)          # one per texture
        root, arm = result.mesh.submeshes
        self.assertEqual(root.material, "test_tex00")
        points = root.geometry.attribute(1)
        self.assertEqual(sorted(points), sorted([(-1, 2, 3), (-2, 2, 3), (-2, 2, 4), (-1, 2, 4)]))
        self.assertEqual({b for _, b, w in arm.bone_assignments}, {1})
        self.assertTrue(all(w == 1.0 for _, _, w in arm.bone_assignments))
        # arm corner (1, 0, 0) rotated +90 about Y is (0, 0, -1), plus (0.5, 0, 0) and the root's (1, 2, 3)
        arm_points = {tuple(round(c, 5) for c in p) for p in arm.geometry.attribute(1)}
        self.assertIn((-1.5, 2.0, 2.0), arm_points)

    def test_winding_and_normals_face_outward(self):
        result = self.port()
        sub = result.mesh.submeshes[0]
        points = sub.geometry.attribute(1)
        self.assertEqual(len(sub.triangles()), 2)
        for a, b, c in sub.triangles():
            e1 = np.subtract(points[b], points[a])
            e2 = np.subtract(points[c], points[a])
            self.assertGreater(np.cross(e1, e2)[1], 0)            # CCW seen from above = front face up
        for normal in sub.geometry.attribute(4):
            self.assertAlmostEqual(normal[1], 1.0, places=6)

    def test_uvs_unchanged_and_vertex_format(self):
        sub = self.port().mesh.submeshes[0]
        self.assertEqual(sorted(sub.geometry.attribute(7)), [(0, 0), (0, 1), (1, 0), (1, 1)])
        layout = [(e.source, e.type, e.semantic, e.offset) for e in sub.geometry.elements]
        self.assertEqual(layout, [(0, 2, 1, 0), (0, 2, 4, 12), (1, 10, 5, 0), (1, 1, 7, 4)])
        self.assertEqual({c[0] for c in sub.geometry.attribute(5)}, {0xFFFFFFFF})

    def test_texture_material_names(self):
        result = self.port(material_names="texture")
        self.assertEqual([s.material for s in result.mesh.submeshes], ["tex00", "tex01"])
        self.assertIn("material tex00 : BZBase", result.material_text)
        self.assertIn("set_texture_alias DiffuseMap tex00_D.png", result.material_text)

    def test_missing_geo_is_reported(self):
        del self.files["arm.geo"]
        result = self.port()
        self.assertEqual(len(result.mesh.submeshes), 1)
        self.assertTrue(any("arm.geo not found" in w for w in result.warnings))

    def test_serialized_files_read_back(self):
        result = self.port()
        mesh = ogre.read_mesh(ogre.write_mesh(result.mesh))
        self.assertEqual(mesh.version, "MeshSerializer_v1.100")
        self.assertEqual(mesh.skeleton, "test.skeleton")
        self.assertEqual([s.name for s in mesh.submeshes], ["test_tex00", "test_tex01"])
        self.assertEqual(mesh.submeshes[1].geometry.attribute(1), result.mesh.submeshes[1].geometry.attribute(1))
        skeleton = read_skeleton(write_skeleton(result.skeleton))
        self.assertEqual([(b.name, b.parent) for b in skeleton.bones], [("root", None), ("arm", 0)])


class VehicleTests(unittest.TestCase):
    def setUp(self):
        self.files = {"xb11bda.geo": top_quad("xb11bda"), "xb11tur.geo": top_quad("xb11tur"),
                      "xb21bda.geo": top_quad("xb21bda", "cock00"), "xb21gun.geo": top_quad("xb21gun", "cock00"),
                      "xb31bda.geo": top_quad("xb31bda")}
        self.vdf = make_bwd("vdf", "Vehicle", [
            (0, 0, "xb11bda", matrix(position=(0, 0.5, 0)), "WORLD", 60),
            (0, 1, "xb11tur", matrix(position=(0, 1, 0)), "xb11bda", 65),
            (0, 2, "xb11gc1", matrix(position=(0, 0, 2)), "xb11tur", 71),
            (0, 3, "xb11lgt", matrix(position=(0, 0, 3)), "xb11bda", 38),
            (4, 0, "xb21bda", matrix(position=(0, 0.5, 0)), "WORLD", 60),
            (4, 1, "xb21gun", matrix(position=(0, 1, 1)), "xb21tur", 60),    # parent missing from its band
            (8, 0, "xb31bda", matrix(position=(0, 0.5, 0)), "WORLD", 60),
        ], 28)

    def test_bands_cockpit_and_hardpoints(self):
        result = build_port(self.vdf, "vdf", "xbtest", loader(self.files))
        names = [b.name for b in result.skeleton.bones]
        self.assertNotIn("xb31bda", names)                     # low-detail band 8 is not ported
        self.assertIn("xb11gc1", names)                        # hardpoints are bones
        self.assertIn("HLGT0_ffffff", names)                   # at the headlight mask
        gun = result.skeleton.bone("xb21gun")
        self.assertEqual(result.skeleton.bones[gun.parent].name, "xb21bda")
        self.assertTrue(any("xb21tur" in w for w in result.warnings))
        cockpit = [s for s in result.mesh.submeshes if s.material.endswith("_cockpit")]
        self.assertEqual([s.material for s in cockpit], ["xbtest_cock00_cockpit"])
        self.assertIn("material xbtest_cock00_cockpit : BZBaseCockpit", result.material_text)
        hardpoint = next(p for p in result.parts if p.name == "xb11gc1")
        self.assertEqual(hardpoint.geo, "")

    def test_bands_option(self):
        result = build_port(self.vdf, "vdf", "xbtest", loader(self.files), PortOptions(bands=(0,)))
        self.assertFalse(any(s.material.endswith("_cockpit") for s in result.mesh.submeshes))


class WriterTests(unittest.TestCase):
    def test_mesh_writer_round_trips_fixtures(self):
        for path in sorted(FIXTURES.glob("*.mesh")):
            mesh = ogre.read_mesh(path)
            again = ogre.read_mesh(ogre.write_mesh(mesh))
            self.assertEqual(len(again.submeshes), len(mesh.submeshes), path.name)
            for a, b in zip(again.submeshes, mesh.submeshes):
                self.assertEqual((a.material, a.name, a.indices, a.operation), (b.material, b.name, b.indices, b.operation))
                if b.geometry:
                    self.assertEqual(a.geometry.attribute(1), b.geometry.attribute(1))
                    self.assertEqual(a.geometry.attribute(7), b.geometry.attribute(7))

    def test_skeleton_round_trip(self):
        skeleton = Skeleton(bones=[Bone("a", 0), Bone("b", 1, (1, 2, 3), (0, 0.6, 0, 0.8), (2, 2, 2), 0)],
                            animations=[Animation("seq00", 1.5, [Track(1, [Keyframe(0.0), Keyframe(1.5, scale=(1, 2, 1))])])])
        data = write_skeleton(skeleton)
        again = read_skeleton(data)
        self.assertEqual(write_skeleton(again), data)
        self.assertEqual(again.bones[1].scale, (2, 2, 2))
        self.assertEqual(again.bones[1].parent, 0)
        self.assertEqual(len(again.animations[0].tracks[0].keyframes), 2)
        # Ogre sizes a bone chunk without its name
        self.assertEqual(struct.unpack_from("<I", data, data.index(b"\x00\x20") + 2)[0], 36)


class MapTests(unittest.TestCase):
    def test_indexed_and_565(self):
        indexed = struct.pack("<HHI", 2, 0, 1) + bytes([1, 2])
        palette = [(0, 0, 0), (255, 0, 0), (0, 0, 255)]
        width, height, rgba = decode_map(indexed, palette)
        self.assertEqual((width, height), (2, 1))
        self.assertEqual(rgba[0, 0].tolist(), [255, 0, 0, 255])
        self.assertEqual(rgba[0, 1].tolist(), [0, 0, 255, 255])
        rgb565 = struct.pack("<HHI", 2, 2, 1) + struct.pack("<H", 0x07E0)
        self.assertEqual(decode_map(rgb565)[2][0, 0].tolist(), [0, 255, 0, 255])

    def test_dds_header(self):
        data = encode_dds_rgba(np.zeros((4, 2, 4), dtype=np.uint8))
        self.assertEqual(len(data), 128 + 4 * 2 * 4)
        self.assertEqual(struct.unpack_from("<4sIIII", data), (b"DDS ", 124, 0x100F, 4, 2))


class EndToEndTests(unittest.TestCase):
    def test_port_folder_with_map_texture(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, "src")
            src.mkdir()
            (src / "unit.sdf").write_bytes(make_bwd("sdf", "Unit", [(0, 0, "unt11bda", matrix(), "WORLD", 61)], 6))
            (src / "UNT11BDA.GEO").write_bytes(top_quad("unt11bda", "unit00"))
            (src / "unit00.map").write_bytes(struct.pack("<HHI", 2, 2, 2) + b"\x00\xf8" * 4)
            out = Path(tmp, "out")
            code = legacy_port.main([str(src / "unit.sdf"), "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                             ["unit.material", "unit.mesh", "unit.skeleton", "unit_unit00_D.png"])
            from PIL import Image
            self.assertEqual(Image.open(out / "unit_unit00_D.png").convert("RGB").getpixel((0, 0)), (255, 0, 0))
            self.assertEqual(ogre.read_mesh(out / "unit.mesh").submeshes[0].material, "unit_unit00")


REDUX = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Battlezone 98 Redux")


@unittest.skipUnless((REDUX / "bzone.zfs").is_file(), "Battlezone 98 Redux is not installed")
class StockComparisonTests(unittest.TestCase):
    """hbptow and obhavc ship in Redux as straight conversions of their 1.5 models."""

    def test_matches_redux_conversion(self):
        from battlezone.archives.zfs import ZFSArchive
        archive = ZFSArchive(REDUX / "bzone.zfs")
        source = legacy_port.AssetSource([], [archive])
        models = REDUX / "BZ_ASSETS" / "common" / "models"
        for name in ("hbptow", "obhavc"):
            result = build_port(source(name + ".sdf"), "sdf", name, source)
            stock = ogre.read_mesh(models / f"{name}.mesh")
            stock_skeleton = read_skeleton(models / f"{name}.skeleton")
            self.assertEqual(result.vertex_count, sum(s.geometry.vertex_count for s in stock.submeshes))
            self.assertEqual(result.triangle_count, sum(len(s.indices) // 3 for s in stock.submeshes))
            for mine, theirs in zip(result.mesh.bounds[:6], stock.bounds[:6]):
                self.assertAlmostEqual(mine, theirs, places=2)
            stock_bones = {b.name: b for b in stock_skeleton.bones}
            for bone in result.skeleton.bones:
                ref = stock_bones[bone.name]
                self.assertLess(math.dist(bone.position, ref.position), 1e-3)
                self.assertGreater(abs(sum(a * b for a, b in zip(bone.orientation, ref.orientation))), 0.9999)


if __name__ == "__main__":
    unittest.main()
