import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from battlezone.bzn import bzcc_port
from battlezone.odf.class_labels import (OdfIndex, diff_classes, resolve_source, rewrite_label,
                          write_redux_odfs)
from tests.missions.test_bzcc_port import SOURCE, TEMPLATE


def write_odfs(root: Path, labels: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, label in labels.items():
        (root / f"{name}.odf").write_text(
            f'[GameObjectClass]\r\nclassLabel = "{label}"  ; comment\r\n', encoding="latin-1")
    return root


class ClassLabelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bzcc = OdfIndex([write_odfs(self.root / "bzcc", {
            "ivscout": "wingman", "ivplysct": "ivscout", "peclif01": "terrain",
            "ibcrat00": "artifact", "ibrecy": "recycler", "pbsign": "i76sign",
            "loopa": "loopb", "loopb": "loopa",
        })])
        self.redux = OdfIndex([write_odfs(self.root / "redux", {
            "ivscout": "wingman", "ivplysct": "wingman", "ibcrat00": "artifact",
            "peclif01": "i76building", "pbsign": "i76sign", "ubtart": "i76building",
            "ibcrate1": "i76sign", "ibrecy": "recycler",
        })])

    def tearDown(self):
        self.tmp.cleanup()

    def diff(self, odf, prototypes=("ivscout", "ubtart", "ibcrate1"), mapping=None,
             approximate=False):
        return diff_classes([odf], self.bzcc, self.redux, prototypes, mapping, approximate)[0]

    def test_source_chain_resolves_to_engine_class(self):
        source = resolve_source("IVPLYSCT", self.bzcc)
        self.assertEqual(source.chain, ["ivplysct", "ivscout"])
        self.assertEqual(source.engine_label, "wingman")
        self.assertEqual(resolve_source("loopa", self.bzcc).problem, "classLabel cycle")

    def test_exact_class_is_auto_mapped_with_note_on_inheritance(self):
        diff = self.diff("ivplysct")
        self.assertEqual((diff.status, diff.prototype), ("ok", "ivscout"))
        self.assertTrue(any("inherits from ivscout" in note for note in diff.notes))

    def test_approximate_class_needs_opt_in(self):
        self.assertEqual(self.diff("peclif01").status, "approximate")
        diff = self.diff("peclif01", approximate=True)
        self.assertEqual((diff.status, diff.prototype), ("ok", "ubtart"))

    def test_static_record_classes_share_prototypes(self):
        diff = self.diff("pbsign", prototypes=("ubtart",))
        self.assertEqual((diff.status, diff.prototype), ("ok", "ubtart"))

    def test_mismatched_prototype_is_rejected(self):
        diff = self.diff("ivplysct", mapping={"ivplysct": {"odf": "ivplysct", "prototype": "ubtart"}})
        self.assertEqual(diff.status, "prototype-mismatch")
        self.assertEqual(self.diff("ivplysct", prototypes=("ubtart",)).status, "no-prototype")
        # Artifacts save only GameObject fields, like signs and buildings.
        diff = self.diff("ibcrat00", mapping={"ibcrat00": {"odf": "ibcrat00", "prototype": "ibcrate1"}})
        self.assertEqual(diff.status, "ok")

    def test_role_changed_class_is_never_automatic(self):
        diff = self.diff("ibrecy", approximate=True)
        self.assertEqual(diff.status, "role-changed")

    def test_invalid_redux_label_and_long_ids(self):
        write_odfs(self.root / "redux", {"peclif01": "terrain"})
        redux = OdfIndex([self.root / "redux"])
        diff = diff_classes(["peclif01"], self.bzcc, redux, ("ubtart",), None, True)[0]
        self.assertEqual(diff.status, "invalid-redux-label")
        write_odfs(self.root / "bzcc", {"pbtele01a": "i76building"})
        diff = diff_classes(["pbtele01a"], OdfIndex([self.root / "bzcc"]), redux, ("ubtart",))[0]
        self.assertEqual(diff.status, "id-too-long")

    def test_bzcc_tunnel_is_noted(self):
        (self.root / "bzcc" / "pbatun03.odf").write_text(
            '[GameObjectClass]\nclassLabel = "i76building"\n[BuildingClass]\ntunnelCount = 1\n')
        diff = diff_classes(["pbatun03"], OdfIndex([self.root / "bzcc"]), self.redux, ())[0]
        self.assertTrue(any(note.startswith("BZCC tunnel") for note in diff.notes))

    def test_rewrite_label_keeps_layout(self):
        text = '[GameObjectClass]\r\nclassLabel = "terrain"  ; prop\r\n'
        self.assertEqual(rewrite_label(text, "i76building"),
                         '[GameObjectClass]\r\nclassLabel = "i76building"  ; prop\r\n')

    def test_write_redux_odfs_skips_inherited_and_unsafe(self):
        diffs = diff_classes(["peclif01", "ivplysct", "ibrecy"], self.bzcc, self.redux,
                             ("ubtart",), None, True)
        written = write_redux_odfs(diffs, self.bzcc, self.root / "out", allow_approximate=True)
        self.assertEqual([Path(w["output"]).name for w in written], ["peclif01.odf"])
        self.assertIn('"i76building"', (self.root / "out" / "peclif01.odf").read_text())


class PortClassCheckTests(unittest.TestCase):
    """bzcc_port --redux-odfs: the test template's only prototype is avscout."""

    def run_port(self, redux_labels, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src.bzn").write_bytes(SOURCE)
            (root / "tpl.bzn").write_bytes(  # the CLI always sets msn_filename
                TEMPLATE.replace(b"TerrainName", b"msn_filename = x.bzn\r\nTerrainName"))
            write_odfs(root / "bzcc", {"ivscout": "wingman"})
            write_odfs(root / "redux", redux_labels)
            args = [str(root / "src.bzn"), str(root / "tpl.bzn"), str(root / "out.bzn"),
                    "--source-odfs", str(root / "bzcc"), "--redux-odfs", str(root / "redux"),
                    "--report", str(root / "r.json"), *extra]
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                code = bzcc_port.main(args)
            report = json.loads((root / "r.json").read_text()) if (root / "r.json").exists() else None
            return code, report

    def test_auto_map_picks_class_compatible_prototype(self):
        code, report = self.run_port({"ivscout": "wingman", "avscout": "wingman"}, "--auto-map")
        self.assertEqual(code, 0)
        self.assertEqual(report["ported_objects"], 1)
        self.assertEqual(report["substitutions"][0]["prototype"], "avscout")
        self.assertEqual(report["class_labels"]["safe"], 1)

    def test_mismatched_explicit_prototype_blocks_the_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            mapping = Path(tmp) / "map.json"
            mapping.write_text('{"ivscout": {"odf": "ivscout", "prototype": "avscout"}}')
            code, report = self.run_port({"ivscout": "wingman", "avscout": "turrettank"},
                                         "--map", str(mapping))
        self.assertEqual(code, 1)
        code, report = self.run_port({"ivscout": "wingman", "avscout": "turrettank"},
                                     "--allow-unsafe-classes", "--allow-skips")
        self.assertEqual(code, 0)
        self.assertEqual(report["class_labels"]["by_status"], {"no-prototype": 1})


if __name__ == "__main__":
    unittest.main()
