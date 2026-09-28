import tempfile
import unittest
from pathlib import Path

from battlezone.validation import validate_project
from battlezone.validation.script_checks import LuaSyntaxError, lua_calls, lua_tokens, parse_aip
from tests.missions.test_bzn_version_convert import redux_bzn

SCRIPT = """-- GetHandle("commented_out")
--[[ BuildObject("nosuch_in_comment", 1, "nowhere") ]]
local exu = require("exu")
local helper = require "helper"
local gone = require("gone")
function Start()
    local tank = GetHandle("unit_one")
    local lost = GetHandle("no_label")
    local nav = GetHandle("path_1")
    BuildObject("avtank", 1, "path_1")
    BuildObject("mytank", 1, "tower")
    BuildObject("notank", 1, "no_path")
    BuildObject("notank", 1, GetPosition(tank))
    BuildObject(odfName, 1, "path_" .. i)
    local h = BuildObject("avtank", 2, "path_1")
    SetLabel(h, "spawned")
    Goto(GetHandle("spawned"), [[path_1]])
    SetAIP("misn05.aip", 2)
    SetAIP("custom.aip", 2)
    SetAIP("missing.aip", 3)
    M.BuildObject("ignored", 1, "ignored")
    if IsOdf(tank, "nosuchodf") then end
    local s = 'it\\'s "quoted"'
end
"""


class LuaTokenTests(unittest.TestCase):
    def test_comments_strings_and_calls(self):
        calls, defined = lua_calls(lua_tokens(SCRIPT))
        names = [c.name for c in calls]
        self.assertNotIn("ignored", [t.value for c in calls for a in c.args for t in a if c.name == "BuildObject"])
        self.assertEqual(names.count("GetHandle"), 4)
        self.assertIn("Start", defined)
        require = [c for c in calls if c.name == "require"]
        self.assertEqual([c.args[0][0].value for c in require], ["exu", "helper", "gone"])
        self.assertEqual(require[1].line, 4)

    def test_unfinished_string(self):
        with self.assertRaises(LuaSyntaxError) as ctx:
            lua_tokens('local a = 1\nlocal s = "open\n')
        self.assertEqual(ctx.exception.line, 2)


class LuaCheckTests(unittest.TestCase):
    def issues(self, root):
        return [(i.rule_id, i.severity, i.path, i.line, i.message) for i in validate_project(root, ["lua"]).issues]

    def test_mission_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.bzn").write_bytes(redux_bzn())
            (root / "m.lua").write_text(SCRIPT, encoding="latin-1")
            (root / "helper.lua").write_text("BuildObject('zzhelp', 1, 'anywhere')\n", encoding="latin-1")
            (root / "mytank.odf").write_text("[GameObjectClass]\n", encoding="latin-1")
            (root / "custom.aip").write_text("", encoding="latin-1")
            (root / "lonely.bzn").write_bytes(redux_bzn())
            found = {(rule, severity, path, line) for rule, severity, path, line, _ in self.issues(root)}
            self.assertEqual(found, {
                ("lua-missing-module", "warning", "m.lua", 5),
                ("lua-missing-label", "warning", "m.lua", 8),
                ("lua-missing-label", "warning", "m.lua", 9),
                ("lua-missing-odf", "warning", "m.lua", 12),
                ("lua-missing-path", "warning", "m.lua", 12),
                ("lua-missing-aip", "warning", "m.lua", 20),
                ("lua-unknown-odf", "info", "m.lua", 22),
                ("lua-external-module", "info", "m.lua", 3),
                ("lua-missing-odf", "info", "helper.lua", 1),     # shared module: no mission of its own
                ("lua-missing-script", "warning", "lonely.bzn", 0),
            })
            messages = {(rule, line): message for rule, _s, path, line, message in self.issues(root)
                        if path == "m.lua"}
            self.assertIn("(it is a path)", messages["lua-missing-label", 9])
            self.assertEqual(messages["lua-missing-odf", 12],
                             'BuildObject("notank"): no stock or project ODF of that name (and 1 more use)')
            self.assertTrue(messages["lua-missing-path", 12].startswith('BuildObject(..., ..., "no_path")'))

    def test_syntax_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "broken.lua").write_text("--[[ never closed\nGetHandle('x')\n", encoding="latin-1")
            self.assertEqual([i[:4] for i in self.issues(tmp)], [("lua-syntax", "error", "broken.lua", 1)])

    def test_search_path_and_preload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bundle.lua").write_text("package.preload['tiny'] = function() end\n", encoding="latin-1")
            (root / "a.lua").write_text("local t = require('tiny')\n", encoding="latin-1")
            (root / "b.lua").write_text("package.path = package.path .. ';x/?.lua'\nrequire('far')\n",
                                        encoding="latin-1")
            self.assertEqual([i[:2] for i in self.issues(root)], [("lua-external-module", "info")])


STOCK_LIKE_AIP = """/* header */
#include "aipdef.h"
int recompute_strategy_period = 10;
float relaxation_coefficient = .5;
UNIT_CONSTRUCTION_PROGRAM unit_construction_program[MAX_UCP_LENGTH];
#DATA
     "Slush_fund",          50,             100;
     "Offensive",           50,             UNLIMITED;
#END_DATA
ACCOUNT Slush_fund[MAX_ACCOUNT_LENGTH];
#DATA
    16,          "svturr",              NUMBER_TO_HAVE,         6;
    16,          "svwalk",
                 NUMBER_TO_HAVE,         1;
    16,          "zzcustom",            NUMBER_TO_HAVE,         1;
#END_DATA
FORCE_MATCHING My_Matchings[MAX_FORCE_MATCHING];
#DATA
   "svfigh",       1.0;
   "zzmissing",    1.0;
   "svtank".       1.5;
#END_DATA
//BUILDING_MATCHING My_Building_Matchings[MAX_BUILDINGS];
//#DATA
  "svmuf",                          2.00,             CENTER_OF_BASE;
#END_DATA
int persistence_priority = 90
"""


class AipCheckTests(unittest.TestCase):
    def test_parse(self):
        rows, tables, problems = parse_aip(STOCK_LIKE_AIP)
        self.assertEqual(set(tables), {"unit_construction_program", "Slush_fund", "My_Matchings"})
        self.assertIn(("ACCOUNT", ("16", '"svwalk"', "NUMBER_TO_HAVE", "1")),
                      [(r.struct, r.fields) for r in rows])
        self.assertEqual([(p.line, p.severity, p.rule) for p in problems], [
            (21, "warning", "aip-syntax"),              # "svtank". 1.5
            (25, "info", "aip-orphan-data"),            # rows of a commented-out table
            (27, "warning", "aip-syntax"),              # missing ';'
        ])

    def test_unclosed_block_and_comment(self):
        problems = parse_aip("ACCOUNT A[5];\n#DATA\n 1, \"svturr\", 0, 1;\n/* open\n")[2]
        self.assertEqual({(p.line, p.severity) for p in problems}, {(2, "error"), (4, "error")})

    def test_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "plan.aip").write_text(STOCK_LIKE_AIP, encoding="latin-1")
            (root / "zzcustom.odf").write_text("[GameObjectClass]\n", encoding="latin-1")
            found = [(i.rule_id, i.line) for i in validate_project(root, ["aip"]).issues
                     if i.rule_id not in ("aip-syntax", "aip-orphan-data")]
            self.assertEqual(sorted(found), [("aip-missing-account", 8), ("aip-missing-odf", 20)])


if __name__ == "__main__":
    unittest.main()
