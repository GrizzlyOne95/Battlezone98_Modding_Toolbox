import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from battlezone.bzn.bz1 import Field, compare_fields, read_bzn, write_bzn
from battlezone.bzn.class_replace import (
    PRESERVED, ReplacementError, apply_replacement, main, preview_replacement,
)
from tests.missions.test_bzn_version_convert import redux_bzn


def fixtures(root, binary=False):
    mission = read_bzn(redux_bzn())
    mission.objects[0].fields["obj_addr"] = Field("ptr", 0x1234)
    mission.objects[1].fields["obj_addr"] = Field("ptr", 0x5678)
    # A surviving object refers to the object being replaced.
    mission.objects[0].fields["nextCmd.where"] = Field("ptr", 0x5678)
    source = root / "source.bzn"
    source.write_bytes(write_bzn(mission, 2016, binary=binary))
    donor = copy.deepcopy(mission)
    donor.objects[1].class_label = "turrettank"
    donor.objects[1].fields["PrjID"] = Field("id", b"avturr")
    donor.objects[1].fields["curHealth"] = Field("long", 888)
    donor.objects[1].fields["nextCmd.where"] = Field("ptr", 0xdeadbeef)
    donor.objects[1].fields["nextCmd.who"] = Field("long", 91)
    template = root / "prototype.bzn"
    # The fixture writer supplies class defaults, as a game-created prototype would.
    template.write_bytes(write_bzn(donor, 2016, binary=binary))
    odf = root / "condor.odf"
    odf.write_text('[GameObjectClass]\nclassLabel = "turrettank"\n')
    return source, template, odf


class ClassReplacementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source, self.template, self.odf = fixtures(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def preview(self):
        return preview_replacement(self.source, self.template, [1], 1, self.odf)

    def test_preserves_identity_incoming_references_and_unselected_content(self):
        original = self.source.read_bytes()
        before = read_bzn(original)
        plan = self.preview()
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(len(list(self.root.iterdir())), 3)
        after = read_bzn(plan.data, hints={"condor": ["turrettank"]})
        old, new = before.objects[1], after.objects[1]
        for key in PRESERVED:
            if key in old.fields:
                self.assertEqual(old.fields[key].value, new.fields[key].value, key)
        self.assertEqual(new.class_label, "turrettank")
        self.assertEqual(new.prjid, "condor")
        self.assertEqual(new.fields["curHealth"].value, 888)
        self.assertEqual(new.fields["nextCmd.where"].value, 0)
        self.assertEqual(new.fields["nextCmd.who"].value, 0)
        self.assertEqual(after.objects[0].fields["nextCmd.where"].value, new.fields["obj_addr"].value)
        self.assertEqual(compare_fields(before.objects[0].fields, after.objects[0].fields, "untouched"), [])
        self.assertEqual(compare_fields(before.mission, after.mission, "mission"), [])
        self.assertEqual(compare_fields(before.paths[0], after.paths[0], "path"), [])
        self.assertEqual(plan.report["reference_warnings"], [])

    def test_binary_records_and_pointer_identity(self):
        self.source, self.template, self.odf = fixtures(self.root, binary=True)
        plan = self.preview()
        output = read_bzn(plan.data)
        self.assertTrue(output.binary)
        self.assertEqual(output.objects[1].fields["obj_addr"].value, 0x5678)
        self.assertEqual(output.objects[0].fields["nextCmd.where"].value, 0x5678)

    def test_in_place_apply_keeps_backup_and_report(self):
        old = self.source.read_bytes()
        odf_bytes = self.odf.read_bytes()
        plan = self.preview()
        result = apply_replacement(plan, self.source)
        self.assertEqual(Path(result["backup"]).read_bytes(), old)
        self.assertEqual(self.source.read_bytes(), plan.data)
        self.assertEqual(self.odf.read_bytes(), odf_bytes)
        self.assertEqual(json.loads(Path(result["report"]).read_text())["target_class"], "turrettank")

    def test_rejects_stale_inputs(self):
        for path in (self.source, self.template, self.odf):
            with self.subTest(path=path.name):
                plan = self.preview()
                old = path.read_bytes()
                path.write_bytes(old + b"\r\n")
                with self.assertRaisesRegex(ReplacementError, "Input changed"):
                    apply_replacement(plan, self.root / "out.bzn")
                self.assertFalse((self.root / "out.bzn").exists())
                path.write_bytes(old)

    def test_rejects_wrong_prototype_and_different_version(self):
        with self.assertRaisesRegex(ReplacementError, "does not fit"):
            preview_replacement(self.source, self.source, [1], 1, self.odf)
        donor = read_bzn(self.template)
        self.template.write_bytes(write_bzn(donor, 2011))
        with self.assertRaisesRegex(ReplacementError, "same version"):
            self.preview()

    def test_target_odf_cannot_leave_unselected_incompatible_records(self):
        mission = read_bzn(self.source)
        for obj in mission.objects:
            obj.fields["PrjID"] = Field("id", b"condor")
        self.source.write_bytes(write_bzn(mission, 2016))
        with self.assertRaisesRegex(ReplacementError, "also uses condor"):
            self.preview()
        plan = preview_replacement(self.source, self.template, [0, 1], 1, self.odf)
        self.assertEqual(len(plan.report["objects"]), 2)

    def test_rejects_duplicate_nonzero_identity(self):
        mission = read_bzn(self.source)
        mission.objects[1].fields["obj_addr"] = copy.deepcopy(mission.objects[0].fields["obj_addr"])
        self.source.write_bytes(write_bzn(mission, 2016))
        with self.assertRaisesRegex(ReplacementError, "Duplicate nonzero"):
            self.preview()

    def test_rejects_invalid_selection_before_sorting(self):
        for indices in ([], [1, "2"], [True], [999]):
            with self.subTest(indices=indices), self.assertRaisesRegex(ReplacementError, "valid source object"):
                preview_replacement(self.source, self.template, indices, 1, self.odf)

    def test_zero_addresses_and_unresolved_existing_reference_are_reported(self):
        mission = read_bzn(self.source)
        for obj in mission.objects:
            obj.fields["obj_addr"] = Field("ptr", 0)
        self.source.write_bytes(write_bzn(mission, 2016))
        self.assertEqual(len(self.preview().report["reference_warnings"]), 1)

    def test_rejects_saved_game_and_bad_target(self):
        mission = read_bzn(self.source)
        mission.save = True
        self.source.write_bytes(write_bzn(mission, 2016))
        with self.assertRaisesRegex(ReplacementError, "saved game"):
            self.preview()
        self.source, self.template, self.odf = fixtures(self.root)
        self.odf.write_text('[GameObjectClass]\nclassLabel="madeup"\n')
        with self.assertRaisesRegex(ReplacementError, "no supported"):
            self.preview()

    def test_cli_preview_does_not_write(self):
        out = self.root / "out.bzn"
        args = [str(self.source), "--template", str(self.template), "--object", "1",
                "--prototype-index", "1", "--target-odf", str(self.odf), "-o", str(out)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 0)
        self.assertFalse(out.exists())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(args + ["--apply"]), 0)
        self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
