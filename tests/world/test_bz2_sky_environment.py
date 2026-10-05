import struct
import tempfile
import unittest
from pathlib import Path

from bztoolbox.modules.world.bz2_sky_environment import act_with_sky_fog, read_sky_environment


class SkyEnvironmentTests(unittest.TestCase):
    def test_global_fog_and_act_preserve_unrelated_palette_entries(self):
        payload = struct.pack("<7f", 110/255, 135/255, 20/255, 1, -50, 450, 500) + bytes(200)
        data = struct.pack("<III", 0x534B595F, 4, 0x10000)
        data += struct.pack("<II", 0x534B5931, len(payload)) + payload
        with tempfile.TemporaryDirectory() as directory:
            sky = Path(directory) / "ground0.SKY"
            sky.write_bytes(data)
            environment = read_sky_environment(sky)
            self.assertEqual(environment["fog_rgb8"], [110, 135, 20])
            self.assertEqual(environment["fog_start_m"], -50)
            base = bytes(range(256)) * 3
            act = act_with_sky_fog(base, environment)
            self.assertEqual(act[627:630], bytes((110, 135, 20)))
            self.assertEqual(act[:627] + act[630:], base[:627] + base[630:])
            sky.write_bytes(data[:-1])
            with self.assertRaisesRegex(ValueError, "Truncated"):
                read_sky_environment(sky)

    def test_local_fog_chunk_is_not_used_as_global_color(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "only_volumes.sky"
            path.write_bytes(struct.pack("<III", 0x534B595F, 4, 0x10000)
                             + struct.pack("<II", 0x464F4720, 28) + bytes(28))
            with self.assertRaisesRegex(ValueError, "no global"):
                read_sky_environment(path)

    def test_time_and_lighting_use_authored_values_and_multipliers(self):
        payload = bytearray(212)
        struct.pack_into('<7f',payload,0,.4,.5,.1,1,-50,450,500)
        struct.pack_into('<2f',payload,28,24,8.5)
        struct.pack_into('<4f',payload,44,1,.4,.08,.5)
        struct.pack_into('<4f',payload,60,.06,.2,.02,2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'authored.sky'
            path.write_bytes(struct.pack('<III',0x534B595F,4,0x10000)
                             + struct.pack('<II',0x534B5931,len(payload)) + payload)
            env = read_sky_environment(path)
            self.assertEqual(env['redux_time_hhmm'],830)
            self.assertEqual(env['day_length_hours'],24)
            for actual,expected in zip(env['sun_diffuse_rgb'],(.5,.2,.04)):
                self.assertAlmostEqual(actual,expected)
            for actual,expected in zip(env['sun_ambient_rgb'],(.12,.4,.04)):
                self.assertAlmostEqual(actual,expected)
