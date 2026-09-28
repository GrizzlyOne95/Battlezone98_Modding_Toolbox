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
from battlezone.meshes.legacy_port import PortOptions, build_port, port_legacy_model, write_port
from battlezone.meshes.ogre_skeleton import Animation, Bone, Keyframe, Skeleton, Track, read_skeleton, write_skeleton

IDENTITY = (1, 0, 0, 0, 1, 0, 0, 0, 1)
FIXTURES = Path(__file__).parent / "fixtures"


def make_geo(name, positions, faces):
    """``faces``: (corner vertex indices, corner uvs, plane normal, texture[, colour])."""
    out = struct.pack("<4si16siii", b"OEG.", 0, name.encode(), len(positions), len(faces), 0)
    out += b"".join(struct.pack("<3f", *p) for p in positions)
    out += b"".join(struct.pack("<3f", 0, 1, 0) for _ in positions)
    for index, face in enumerate(faces):
        corners, uvs, normal, texture = face[:4]
        colour = face[4] if len(face) > 4 else (10, 20, 30)
        out += struct.pack("<iiBBBffffi3s13sii", index, len(corners), *colour, *normal, 0.0, 0,
                           b"\x04\x01\x00", texture.encode(), -1, 0)
        out += b"".join(struct.pack("<iiff", v, v, *uv) for v, uv in zip(corners, uvs))
    return out


def top_quad(name, texture="tex00", size=1.0):
    """A square in the XZ plane; corners in the stock order (inward plane normal -Y)."""
    positions = [(0, 0, 0), (size, 0, 0), (size, 0, size), (0, 0, size)]
    uvs = [(0, 0), (1, 0), (1, 1), (0, 1)]
    return make_geo(name, positions, [([0, 1, 2, 3], uvs, (0, -1, 0), texture)])


def make_bwd(kind, name, records, bands, anim=b""):
    """``records``: (band, slot, name, matrix12, parent, class); ``anim``: an ANIM chunk (make_anim)."""
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
    return (header + body + struct.pack("<4sii", geo_tag, 12 + len(table), count) + bytes(table) + anim
            + struct.pack("<4si", b"EXIT", 8))


def make_anim(sequences, tracks):
    """``sequences``: (index, start, signed length); ``tracks``: name -> (rotations, positions)
    with rotations [(frame, (w, x, y, z) as stored)] and positions [(frame, (x, y, z))]."""
    seq = b"".join(struct.pack("<i128xiiif", index, start, length, 1, 10.0) for index, start, length in sequences)
    parts, rots, poss = b"", b"", b""
    nr = np_ = 0
    for name, (rotations, positions) in tracks.items():
        parts += struct.pack("<8si96x6i", name.encode(), 0, nr, len(rotations), 0, 0, np_, len(positions))
        rots += b"".join(struct.pack("<i4f", f, *q) for f, q in rotations)
        poss += b"".join(struct.pack("<i3f", f, *p) for f, p in positions)
        nr, np_ = nr + len(rotations), np_ + len(positions)
    body = (b"anim".ljust(16, b"\0") + struct.pack("<5i", len(sequences), len(tracks), nr, 0, np_) + bytes(28)
            + seq + parts + rots + poss)
    return struct.pack("<4si", b"ANIM", len(body) + 8) + body


def stored(axis, degrees):
    """The ANIM file's quaternion for a legacy rotation about ``axis``: the conjugated Hamilton one."""
    s, c = math.sin(math.radians(degrees) / 2), math.cos(math.radians(degrees) / 2)
    return (c, *(-s * a for a in axis))


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
            (4, 4, "xb21ext", matrix(position=(0, 0, 1)), "xb21zzz", 60),    # ... and no model part in its slot
            (8, 0, "xb31bda", matrix(position=(0, 0.5, 0)), "WORLD", 60),
        ], 28)

    def test_bands_cockpit_and_hardpoints(self):
        result = build_port(self.vdf, "vdf", "xbtest", loader(self.files))
        names = [b.name for b in result.skeleton.bones]
        self.assertNotIn("xb31bda", names)                     # low-detail band 8 is not ported
        self.assertIn("xb11gc1", names)                        # hardpoints are bones
        self.assertIn("HLGT0_ffffff", names)                   # at the headlight mask
        # a cockpit part rides the model part of its slot, whatever parent its record names
        gun = result.skeleton.bone("xb21gun")
        self.assertEqual((result.skeleton.bones[gun.parent].name, gun.position), ("xb11tur", (-0.0, 0.0, 0.0)))
        self.assertIsNone(result.cockpit_mesh)                 # nothing animates: one mesh
        ext = result.skeleton.bone("xb21ext")                  # no slot partner: its band's root
        self.assertEqual(result.skeleton.bones[ext.parent].name, "xb21bda")
        self.assertTrue(any("xb21zzz" in w for w in result.warnings))
        cockpit = [s for s in result.mesh.submeshes if s.material.endswith("_cockpit")]
        self.assertEqual([s.material for s in cockpit], ["xbtest_cock00_cockpit"])
        gun_points = {tuple(round(c, 5) for c in p) for p in cockpit[0].geometry.attribute(1)}
        self.assertIn((-0.0, 1.5, 0.0), gun_points)            # baked at xb11tur (0, 1.5, 0)
        self.assertIn("material xbtest_cock00_cockpit : BZBaseCockpit", result.material_text)
        hardpoint = next(p for p in result.parts if p.name == "xb11gc1")
        self.assertEqual(hardpoint.geo, "")
        self.assertEqual(result.skeleton.animations, [])       # no ANIM chunk, no seqNN

    def test_bands_option(self):
        result = build_port(self.vdf, "vdf", "xbtest", loader(self.files), PortOptions(bands=(0,)))
        self.assertFalse(any(s.material.endswith("_cockpit") for s in result.mesh.submeshes))


def same_rotation(test, a, b, places=5):
    """Quaternions equal up to sign."""
    test.assertAlmostEqual(abs(sum(x * y for x, y in zip(a, b))), 1.0, places=places)


def assert_close(test, a, b, places=5):
    for x, y in zip(a, b):
        test.assertAlmostEqual(x, y, places=places)


X_AXIS, Y_AXIS = (1, 0, 0), (0, 1, 0)


class PersonTests(unittest.TestCase):
    """A pilot: named skeletal animations, a separate first-person mesh and a sniper scope."""

    def setUp(self):
        self.files = {"asp11ctr.geo": top_quad("asp11ctr", "aspilo00"),
                      "asp21mg1.geo": top_quad("asp21mg1", "aspgun00", 0.2)}
        self.records = [
            (0, 0, "asp11ctr", matrix(position=(0, 1, 0)), "WORLD", 60),
            (0, 1, "asp11mg1", matrix(position=(0.2, 1.1, 0.5)), "WORLD", 60),
            (0, 2, "asp11gc1", matrix(position=(0, 0, 0.6)), "asp11mg1", 71),
            (0, 3, "asp11pov", matrix(position=(0, 1.5, 0)), "WORLD", 40),
            (4, 1, "asp21mg1", matrix(position=(0.2, 1.1, 0.5)), "WORLD", 60),
        ]
        self.anim = make_anim(
            [(0, 0, 5), (1, 4, -5), (2, 0, -1), (3, 4, -1), (4, 10, 3)],
            {"asp11ctr": ([(0, stored(Y_AXIS, 0)), (4, stored(Y_AXIS, 90))], [(0, (0, 1, 0)), (4, (0, 0.5, 0))]),
             "asp11pov": ([(0, stored(X_AXIS, 0)), (4, stored(X_AXIS, 30)), (11, stored(X_AXIS, 10))],
                          [(0, (0, 1.5, 0)), (4, (0, 1.0, 0.2)), (11, (0, 1.6, 0))]),
             "asp11gc1": ([(0, stored(Y_AXIS, 45))], [(0, (0, 0, 0.6))])})

    def port(self, **options):
        vdf = make_bwd("vdf", "Pilot", self.records, 28, self.anim)
        return build_port(vdf, "vdf", "aspilo", loader(self.files), PortOptions(**options))

    def track(self, result, animation, bone):
        anim = next(a for a in result.skeleton.animations if a.name == animation)
        handle = result.skeleton.bone(bone).handle
        return next((t.keyframes for t in anim.tracks if t.bone == handle), None)

    def test_person_layout(self):
        result = self.port()
        self.assertTrue(result.person)
        self.assertEqual(result.cockpit_name, "aspilo_fp")     # the eyepoint animates
        self.assertEqual([s.material for s in result.mesh.submeshes], ["aspilo_aspilo00"])
        self.assertEqual([s.material for s in result.cockpit_mesh.submeshes], ["aspilo_aspgun00_cockpit", "scope"])
        self.assertEqual(result.cockpit_mesh.skeleton, "aspilo_fp.skeleton")
        self.assertNotIn("material scope", result.material_text)      # Redux's own
        gun = result.skeleton.bone("asp21mg1")
        self.assertEqual(result.skeleton.bones[gun.parent].name, "asp11mg1")
        hardpoint = result.skeleton.bone("asp11gc1")           # on the gun's origin, never keyed
        self.assertEqual(hardpoint.position, (-0.0, 0.0, 0.0))
        self.assertTrue(all(self.track(result, a.name, "asp11gc1") is None for a in result.skeleton.animations))

    def test_animation_names_and_lengths(self):
        result = self.port()
        self.assertEqual([(a.name, a.length) for a in result.skeleton.animations],
                         [(name, length) for _, name, length, _ in legacy_port.PERSON_ANIMATIONS])
        death = next(a for a in result.skeleton.animations if a.name == "death1")
        self.assertEqual(death.tracks, [])                     # sequence 8 is absent: empty

    def test_keys_are_offsets_from_the_bind_pose(self):
        result = self.port()
        body = self.track(result, "stand2Kneel", "asp11ctr")
        self.assertEqual([round(k.time, 6) for k in body], [0.0, round(29 / 30, 6)])
        same_rotation(self, body[0].orientation, (0, 0, 0, 1))
        # +90 degrees about Y in 1.5 space is -90 about Y once mirrored in X
        same_rotation(self, body[-1].orientation, (0, -math.sqrt(0.5), 0, math.sqrt(0.5)))
        assert_close(self, body[-1].translation, (0, -0.5, 0))
        back = self.track(result, "kneel2stand", "asp11ctr")  # the same frames, played backwards
        same_rotation(self, back[0].orientation, body[-1].orientation)
        same_rotation(self, back[-1].orientation, body[0].orientation)

    def test_eyepoint_pitch_is_flipped_and_scope_follows(self):
        result = self.port()
        pov = self.track(result, "stand2Kneel", "asp11pov")
        s, c = math.sin(math.radians(15)), math.cos(math.radians(15))
        same_rotation(self, pov[-1].orientation, (-s, 0, 0, c))
        assert_close(self, pov[-1].translation, (0, -0.5, 0.2))
        self.assertEqual(result.scope, "fixed")
        scope = result.skeleton.bone("scope")
        self.assertEqual((scope.parent, scope.position), (None, result.skeleton.bone("asp11pov").position))
        same_rotation(self, self.track(result, "stand2Kneel", "scope")[-1].orientation, (s, 0, 0, c))
        # crouched: the scope comes 0.1 + 1.0 ahead of its hiding place behind the camera
        crouched = self.track(result, "fireRecoilSniper", "scope")
        self.assertEqual(len(crouched), 1)
        ahead = 1.1
        assert_close(self, crouched[0].translation,
                     (0, -0.5 - ahead * math.sin(math.radians(30)), 0.2 + ahead * math.cos(math.radians(30))))
        quad = result.cockpit_mesh.submeshes[1].geometry.attribute(1)
        scale = 0.1 / 6
        self.assertIn(round(-(2.975 + 1) * scale, 5), {round(p[0], 5) for p in quad})    # American placement
        self.assertTrue(all(abs(p[2] + 1.0) < 1e-6 for p in quad))                        # hidden behind

    def test_run_keys_and_no_pov_rotations(self):
        result = self.port()
        run = self.track(result, "runForward", "asp11pov")
        self.assertEqual(len(run), 3)                          # frames 10, 11 (a key), 12
        assert_close(self, run[1].translation, (0, 0.1, 0))
        still = self.port(pov_rotations=False)
        run = self.track(still, "runForward", "asp11pov")
        self.assertTrue(all(k.orientation == (0.0, 0.0, 0.0, 1.0) for k in run))
        assert_close(self, run[1].translation, (0, 0.1, 0))

    def test_options(self):
        plain = self.port(person=False)
        self.assertFalse(plain.person)
        self.assertEqual([a.name for a in plain.skeleton.animations], ["seq00", "seq01", "seq02", "seq03", "seq04"])
        self.assertEqual(plain.scope, "")
        self.assertIsNotNone(plain.skeleton.bone("asp11gc1"))
        self.assertNotEqual(plain.skeleton.bone("asp11gc1").position, (-0.0, 0.0, 0.0))
        together = self.port(cockpit_files=False)
        self.assertIsNone(together.cockpit_mesh)
        self.assertIn("scope", [s.material for s in together.mesh.submeshes])
        attached = self.port(scope_type="attached", scope_gun="asp11mg1",
                             scope_transform=(0.1, 0, 0, 0, 0.1, 0, 0, 0, 0.1, 0, 0.2, 0.3))
        scope = attached.skeleton.bone("scope")
        self.assertEqual(attached.skeleton.bones[scope.parent].name, "asp11mg1")
        self.assertIsNone(self.track(attached, "stand2Kneel", "scope"))
        self.assertIsNone(self.port(scope=False).skeleton.bone("scope"))
        soviet = self.port(scope_nation="soviet").cockpit_mesh.submeshes[1].geometry.attribute(1)
        self.assertIn(round(-(2.58 + 1) * 0.1 / 6, 5), {round(p[0], 5) for p in soviet})

    def test_geometry_scope(self):
        self.files["asp21mg1.geo"] = top_quad("asp21mg1", "__scope", 0.2)
        result = self.port()
        self.assertEqual(result.scope, "geometry")
        self.assertEqual([s.material for s in result.cockpit_mesh.submeshes], ["scope"])
        self.assertIsNone(result.skeleton.bone("scope"))
        self.assertNotIn("__scope", result.texture_files)


class AnimationChunkTests(unittest.TestCase):
    def test_reader_and_stub_sequences(self):
        anim = make_anim([(0, 0, 121), (1, 120, -121)],
                         {"htw11bda": ([], [(120, (0, 1, 0)), (0, (0, 0, 0))])})
        sdf = make_bwd("sdf", "Tower", [(0, 0, "htw11bda", matrix(), "WORLD", 61)], 6, anim)
        model = read_sdf(sdf)
        self.assertEqual([(s.index, s.frames) for s in model.sequences], [(0, (0, 120)), (1, (120, 0))])
        self.assertEqual([f for f, _ in model.track("HTW11BDA").positions], [0, 120])     # sorted
        result = build_port(sdf, "sdf", "tower", loader({"htw11bda.geo": top_quad("htw11bda")}))
        # what every straight-converted stock skeleton carries (hbptow, obhavc, ...)
        self.assertEqual([(a.name, a.length, a.tracks) for a in result.skeleton.animations],
                         [("seq00", 1.0, []), ("seq01", 1.0, [])])


class TextureTests(unittest.TestCase):
    def geo(self):
        positions = [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1), (2, 0, 0), (2, 0, 1)]
        uvs = [(0, 0), (1, 0), (1, 1), (0, 1)]
        return make_geo("flat", positions, [([0, 1, 2, 3], uvs, (0, -1, 0), "", (200, 0, 0)),
                                            ([1, 4, 5, 2], uvs, (0, -1, 0), "", (0, 0, 200)),
                                            ([0, 1, 2, 3], uvs, (0, -1, 0), "tex00"),
                                            ([1, 4, 5, 2], uvs, (0, -1, 0), "TEX00")])

    def test_flat_colour_palette(self):
        sdf = make_bwd("sdf", "Flat", [(0, 0, "flat", matrix(), "WORLD", 61)], 6)
        result = build_port(sdf, "sdf", "flat", loader({"flat.geo": self.geo()}))
        # untextured faces share a palette texture; tex00 and TEX00 are one material
        self.assertEqual([s.material for s in result.mesh.submeshes], ["flat_flat", "flat_tex00"])
        self.assertEqual(result.flat_palette, [(200, 0, 0), (0, 0, 200)])
        self.assertEqual(sorted(set(result.mesh.submeshes[0].geometry.attribute(7))), [(0.25, 0.5), (0.75, 0.5)])
        self.assertEqual(result.texture_files[""], "flat_flat_D.png")
        with tempfile.TemporaryDirectory() as tmp:
            write_port(result, tmp, loader({}))
            from PIL import Image
            image = Image.open(Path(tmp, "flat_flat_D.png")).convert("RGB")
            self.assertEqual((image.size, image.getpixel((0, 0)), image.getpixel((1, 0))),
                             ((2, 1), (200, 0, 0), (0, 0, 200)))
        everything = build_port(sdf, "sdf", "flat", loader({"flat.geo": self.geo()}), PortOptions(flat_colours=True))
        self.assertEqual([s.material for s in everything.mesh.submeshes], ["flat_flat"])

    def test_bounds_scale_and_material_suffix(self):
        sdf = make_bwd("sdf", "Flat", [(0, 0, "flat", matrix(), "WORLD", 61)], 6)
        result = build_port(sdf, "sdf", "flat", loader({"flat.geo": self.geo()}),
                            PortOptions(bounds_scale=(2, 1, 1), material_suffix="_port"))
        self.assertEqual(result.mesh.bounds[:6], (-3.0, 0.0, 0.0, 1.0, 0.0, 1.0))
        self.assertIn(Path("out", "flat_port.material"), legacy_port.planned_files(result, "out"))


class InputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name, "src")
        self.src.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_geo_map_and_odf(self):
        (self.src / "part.geo").write_bytes(top_quad("part", "tex00"))
        (self.src / "tex00.map").write_bytes(struct.pack("<HHI", 2, 2, 1) + b"\x00\xf8")
        result = legacy_port.port_file(self.src / "part.geo", Path(self.tmp.name, "geo"))
        self.assertEqual(([b.name for b in result.skeleton.bones], result.mesh.submeshes[0].material),
                         (["part"], "part_tex00"))
        self.assertTrue(Path(self.tmp.name, "geo", "part_tex00_D.png").is_file())
        texture = legacy_port.port_file(self.src / "tex00.map", Path(self.tmp.name, "map"))
        self.assertEqual(texture.written, [Path(self.tmp.name, "map", "tex00_D.png")])

        (self.src / "xspilo.vdf").write_bytes(make_bwd("vdf", "P", [(0, 0, "xsp11ctr", matrix(), "WORLD", 60)], 28))
        (self.src / "xsp11ctr.geo").write_bytes(top_quad("xsp11ctr"))
        (self.src / "mypilot.odf").write_text('[GameObjectClass]\nbaseName = "xspilo" // model\n'
                                              'classLabel = "person"\nnation = "soviet"\n')
        result = legacy_port.port_file(self.src / "mypilot.odf", Path(self.tmp.name, "odf"), dry_run=True)
        self.assertEqual((result.name, result.kind, result.person, result.options.scope_nation),
                         ("xspilo", "vdf", True, "soviet"))
        self.assertFalse(Path(self.tmp.name, "odf").exists())
        (self.src / "hut.sdf").write_bytes(make_bwd("sdf", "H", [(0, 0, "xsp11ctr", matrix(), "WORLD", 61)], 6))
        (self.src / "hut.odf").write_text('[GameObject]\nmaxHealth = 5\n')          # no class label
        self.assertEqual(legacy_port.port_file(self.src / "hut.odf", self.src, dry_run=True).kind, "sdf")

    def test_cli_many_files(self):
        (self.src / "a.sdf").write_bytes(make_bwd("sdf", "A", [(0, 0, "abda", matrix(), "WORLD", 61)], 6))
        (self.src / "abda.geo").write_bytes(top_quad("abda"))
        (self.src / "b.geo").write_bytes(top_quad("b"))
        files = [str(self.src / "a.sdf"), str(self.src / "b.geo")]
        self.assertEqual(legacy_port.main([*files, "--dry-run", "--format", "none"]), 0)
        self.assertFalse((self.src / "a_redux").exists())
        self.assertEqual(legacy_port.main([*files, "--format", "none"]), 0)
        self.assertTrue((self.src / "a_redux" / "a.mesh").is_file())             # beside each input
        self.assertTrue((self.src / "b_redux" / "b.mesh").is_file())
        (self.src / "a_redux" / "a.mesh").write_bytes(b"keep")
        self.assertEqual(legacy_port.main([files[0], "--skip-existing"]), 0)
        self.assertEqual((self.src / "a_redux" / "a.mesh").read_bytes(), b"keep")
        with self.assertRaises(SystemExit):
            legacy_port.main([*files, "--name", "x"])                             # --name needs one input
        found = []
        legacy_port.main([files[1], "--game15", "auto", "--dry-run"], find_game15=lambda: found.append(1))
        self.assertEqual(found, [1])


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


REDUX = next((p for p in (Path(r"C:\Program Files (x86)\Steam\steamapps\common\Battlezone 98 Redux"),
                          Path(r"C:\Program Files (x86)\GOG Galaxy\Games\Battlezone 98 Redux"))
              if (p / "bzone.zfs").is_file()), Path("missing"))


def absolute_position(skeleton, name):
    bones = {b.handle: b for b in skeleton.bones}
    bone = skeleton.bone(name)
    position = bone.position
    while bone.parent is not None:
        bone = bones[bone.parent]
        position = tuple(a + b for a, b in zip(legacy_port._rotate(bone.orientation, position), bone.position))
    return position


@unittest.skipUnless((REDUX / "bzone.zfs").is_file(), "Battlezone 98 Redux is not installed")
class StockComparisonTests(unittest.TestCase):
    """hbptow and obhavc ship in Redux as straight conversions of their 1.5 models."""

    @classmethod
    def setUpClass(cls):
        from battlezone.archives.zfs import ZFSArchive
        cls.source = legacy_port.AssetSource([], [ZFSArchive(REDUX / "bzone.zfs")])
        cls.models = REDUX / "BZ_ASSETS" / "common" / "models"

    def test_matches_redux_conversion(self):
        source, models = self.source, self.models
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
            # one empty seqNN per ANIM sequence, as the stock conversion has
            self.assertEqual([(a.name, a.length, len(a.tracks)) for a in result.skeleton.animations],
                             [(a.name, a.length, len(a.tracks)) for a in stock_skeleton.animations])

    def test_pilot_and_walker_file_layout(self):
        # the remastered stock pilots and walkers are not conversions, but they fix the file
        # names Redux loads and the pilot animation names
        for name, cockpit in (("aspilo", "aspilo_fp"), ("sspilo", "sspilo_fp"), ("avwalk", "avwalk_c")):
            result = build_port(self.source(name + ".vdf"), "vdf", name, self.source)
            self.assertEqual(result.cockpit_name, cockpit)
            self.assertTrue((self.models / f"{cockpit}.mesh").is_file())
        stock = {a.name for a in read_skeleton(self.models / "aspilo.skeleton").animations}
        pilot = build_port(self.source("aspilo.vdf"), "vdf", "aspilo", self.source)
        self.assertTrue(pilot.person)
        self.assertLessEqual({a.name for a in pilot.skeleton.animations}, stock)

    def test_cockpit_parts_ride_their_slot(self):
        # avartl's cockpit guns name a parent that does not exist (aar21tx1); Redux puts each
        # exactly on the model gun of its slot, and so does the port
        result = build_port(self.source("avartl.vdf"), "vdf", "avartl", self.source)
        stock = read_skeleton(self.models / "avartl.skeleton")
        for cockpit, model in (("aar21bga", "aar11bga"), ("aar21bgb", "aar11bgb"), ("aar21bgc", "aar11bgc"),
                               ("aar21bgd", "aar11bgd")):
            self.assertLess(math.dist(absolute_position(stock, cockpit), absolute_position(stock, model)), 0.03)
            self.assertLess(math.dist(absolute_position(result.skeleton, cockpit),
                                      absolute_position(result.skeleton, model)), 1e-6)


if __name__ == "__main__":
    unittest.main()
