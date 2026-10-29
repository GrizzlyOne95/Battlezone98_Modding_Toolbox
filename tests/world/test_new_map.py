import math
import os
import tempfile
import unittest

from battlezone.bzn.bz1 import read_bzn, write_bzn
from bztoolbox.modules.world.hg2_codec import read_hg2
from bztoolbox.modules.world.mat_codec import parse_trn_painter
from bztoolbox.modules.world.new_map import STOCK_MIN_Z, create_new_map
from bztoolbox.modules.world.new_map_bzn import new_map_bzn, spawn_points


class NewMapBznTests(unittest.TestCase):
    def test_instant_action_holds_only_the_player_tank(self):
        bzn = read_bzn(new_map_bzn("arena", "instant_action", (0, 99840, 2560, 2560), lambda x, z: 50.0).write())
        self.assertEqual((bzn.version, bzn.mission_name, bzn.terrain_name), (2016, "LuaMission", "arena"))
        self.assertEqual([(o.class_label, o.prjid) for o in bzn.objects], [("wingman", "avtank")])
        player = bzn.objects[0].fields
        self.assertEqual(player["isUser"].value, 1)
        self.assertEqual(player["pos"].value, [(1280.0, 51.0, 101120.0)])

    def test_multiplayer_adds_spawn_points_and_survives_binary(self):
        bzn = new_map_bzn("arena", "multiplayer", (0, 0, 1280, 1280), lambda x, z: 0.0, players=4,
                          mission_class="MultSTMission")
        back = read_bzn(write_bzn(read_bzn(bzn.write()), 2016, binary=True))
        self.assertEqual(back.mission_name, "MultSTMission")
        self.assertEqual([o.class_label for o in back.objects], ["wingman"] + ["spawnpnt"] * 4)
        addrs = [o.fields["obj_addr"].value for o in back.objects]
        self.assertEqual(len(set(addrs)), len(addrs))
        # The player starts on the first spawn point.
        self.assertEqual(back.objects[0].fields["pos"].value, back.objects[1].fields["pos"].value)

    def test_spawn_points_face_the_centre(self):
        for x, z, yaw in spawn_points((0.0, 0.0), 100.0, 3):
            self.assertAlmostEqual(x + 100.0 * math.sin(yaw), 0.0, places=6)
            self.assertAlmostEqual(z + 100.0 * math.cos(yaw), 0.0, places=6)


class CreateNewMapTests(unittest.TestCase):
    def test_writes_a_complete_multiplayer_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = create_new_map(tmp, "nmtest", mode="multiplayer", world="Mars", zones=2,
                                    layout="Simple Arena", max_players=3)
            names = sorted(os.path.basename(f) for f in result.files)
            self.assertEqual(names, sorted(f"nmtest.{e}" for e in ("trn", "hg2", "mat", "lgt", "bmp", "des", "ini", "bzn")))
            self.assertEqual(sorted(os.listdir(result.folder)), names)
            header, heights = read_hg2(os.path.join(result.folder, "nmtest.hg2"))
            self.assertEqual(heights.shape, (512, 512))
            trn = parse_trn_painter(os.path.join(result.folder, "nmtest.trn"))
            self.assertEqual((trn.min_z, trn.width), (STOCK_MIN_Z, 2560))
            bzn = read_bzn(os.path.join(result.folder, "nmtest.bzn"))
            self.assertEqual((bzn.mission_name, bzn.terrain_name, len(bzn.objects)), ("MultDMMission", "nmtest", 4))
            ini = open(os.path.join(result.folder, "nmtest.ini"), encoding="utf-8").read()
            self.assertIn('mapType = "multiplayer"', ini)
            self.assertIn('maxPlayers = "3"', ini)

    def test_map_check_passes_new_maps_and_catches_a_wrong_class(self):
        from battlezone.validation.mod_scanner import ModScanner

        with tempfile.TemporaryDirectory() as tmp:
            folder = create_new_map(tmp, "nmtest", mode="multiplayer", zones=2, max_players=3).folder
            self.assertEqual(ModScanner().validate_content_structure(folder, remove_system_files=False)[0], [])
            ini = os.path.join(folder, "nmtest.ini")
            with open(ini, encoding="utf-8") as stream:
                text = stream.read()
            with open(ini, "w", encoding="utf-8") as stream:
                stream.write(text.replace('"multiplayer"', '"instant_action"'))
            errors, _ = ModScanner().validate_content_structure(folder, remove_system_files=False)
            self.assertTrue(any("MultDMMission" in e and "Instant Action" in e for e in errors))

        with tempfile.TemporaryDirectory() as tmp:
            folder = create_new_map(tmp, "nmtest", zones=2).folder
            self.assertEqual(ModScanner().validate_content_structure(folder, remove_system_files=False)[0], [])
            ini = os.path.join(folder, "nmtest.ini")
            with open(ini, encoding="utf-8") as stream:
                text = stream.read()
            with open(ini, "w", encoding="utf-8") as stream:
                stream.write(text.replace('"instant_action"', '"multiplayer"'))
            errors, _ = ModScanner().validate_content_structure(folder, remove_system_files=False)
            self.assertTrue(any("no spawn point" in e for e in errors))

    def test_map_check_warns_when_spawn_points_are_fewer_than_max_players(self):
        from battlezone.validation.mod_scanner import ModScanner

        with tempfile.TemporaryDirectory() as tmp:
            folder = create_new_map(tmp, "nmtest", mode="multiplayer", zones=2, max_players=3).folder
            _, warnings = ModScanner().validate_content_structure(folder, remove_system_files=False)
            self.assertFalse(any("spawn point" in w for w in warnings))
            ini = os.path.join(folder, "nmtest.ini")
            with open(ini, encoding="utf-8") as stream:
                text = stream.read()
            with open(ini, "w", encoding="utf-8") as stream:
                stream.write(text.replace('maxPlayers = "3"', 'maxPlayers = "5"'))
            errors, warnings = ModScanner().validate_content_structure(folder, remove_system_files=False)
            self.assertEqual(errors, [])
            self.assertTrue(any("3 spawn points but maxPlayers is 5" in w for w in warnings))

    def test_saves_supplied_heights_at_their_own_size(self):
        from battlezone.validation.mod_scanner import ModScanner
        import numpy as np

        heights = np.zeros((512, 768), dtype=np.uint16)     # 3 zones wide, 2 deep
        heights[:, 384:] = 400                              # a 40 m step on the east half
        with tempfile.TemporaryDirectory() as tmp:
            folder = create_new_map(tmp, "nmsave", mode="multiplayer", heights=heights, max_players=2).folder
            _, saved = read_hg2(os.path.join(folder, "nmsave.hg2"))
            self.assertTrue(np.array_equal(saved, heights))
            trn = parse_trn_painter(os.path.join(folder, "nmsave.trn"))
            self.assertEqual((trn.width, trn.depth), (3840, 2560))
            self.assertEqual(ModScanner().validate_content_structure(folder, remove_system_files=False)[0], [])
            with self.assertRaises(ValueError):
                create_new_map(tmp, "nmbad", heights=np.zeros((300, 512), dtype=np.uint16))
            with self.assertRaises(ValueError):
                create_new_map(tmp, "nmbad", heights=np.full((256, 256), 6000, dtype=np.uint16))

    def test_rejects_bad_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            for kwargs in ({"mode": "mod"}, {"layout": "Nope"}, {"game_type": "K"}, {"min_players": 5}, {"max_players": 17}):
                with self.assertRaises(ValueError):
                    create_new_map(tmp, "nmtest", **kwargs)
            with self.assertRaises(ValueError):
                create_new_map(tmp, "too_long_name")


if __name__ == "__main__":
    unittest.main()
