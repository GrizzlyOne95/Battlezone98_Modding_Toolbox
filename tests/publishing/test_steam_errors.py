import os
import tempfile
import time
import unittest
from datetime import datetime
from types import SimpleNamespace

from bztoolbox.modules.publishing import steam_errors
from bztoolbox.modules.publishing.workshop_backend import WorkshopBackend


class TestSteamErrors(unittest.TestCase):
    def test_every_eresult_up_to_130_is_documented(self):
        # 4 was retired from the SDK; every other code has a name and a meaning.
        for code in [0, 1, 2, 3] + list(range(5, 131)):
            info = steam_errors.eresult_info(code)
            self.assertIsNotNone(info, code)
            self.assertTrue(info.name and info.meaning, code)

    def test_workshop_relevant_codes_say_what_to_do(self):
        for code in (2, 3, 8, 9, 15, 16, 17, 20, 21, 24, 25, 29, 33, 34, 37, 44, 54, 84, 86, 112):
            self.assertTrue(steam_errors.eresult_info(code).fix, code)

    def test_describe_eresult_uses_stage_specific_wording(self):
        text = steam_errors.describe_eresult(15, "create")
        self.assertIn("EResult 15: AccessDenied", text)
        self.assertIn("own a license", text)
        self.assertIn("What to do:", text)
        self.assertIn("preview image", steam_errors.describe_eresult(15, "submit"))

    def test_unknown_eresult_still_reports_the_number(self):
        self.assertIn("EResult 999", steam_errors.describe_eresult(999))

    def test_names_resolve_as_steamcmd_spells_them(self):
        self.assertEqual(steam_errors.eresult_info("Access Denied").code, 15)
        self.assertEqual(steam_errors.eresult_info("Failure").code, 2)
        self.assertEqual(steam_errors.eresult_info("Two-factor code mismatch").code, 88)
        self.assertEqual(steam_errors.eresult_info("Rate Limit Exceeded").code, 84)

    def test_steamcmd_output_is_explained(self):
        found = steam_errors.diagnose_steamcmd_output(
            "Logging in user 'modder' to Steam Public...OK\n"
            "ERROR! Failed to update workshop item (Limit Exceeded).\n"
            "ERROR! Timeout uploading manifest (Failure)\n"
            "FAILED (Rate Limit Exceeded)\n")
        titles = [d["title"] for d in found]
        self.assertIn("Limit Exceeded (EResult 25)", titles)
        self.assertIn("Upload timed out", titles)
        self.assertIn("Rate Limit Exceeded (EResult 84)", titles)
        self.assertNotIn("Failure (EResult 2)", titles)   # the manifest timeout explains it
        text = steam_errors.format_diagnoses(found)
        self.assertIn("1 MB", text)
        self.assertIn("Log line: ERROR! Failed to update workshop item (Limit Exceeded).", text)

    def test_unrecognised_errors_are_kept_verbatim(self):
        found = steam_errors.diagnose_steamcmd_output("ERROR! Something new went wrong\n")
        self.assertEqual(found[0]["line"], "ERROR! Something new went wrong")

    def test_steamworks_messages_gain_a_fix(self):
        text = steam_errors.explain_steamworks_message("SetItemTitle returned failure.")
        self.assertIn("128 characters", text)
        self.assertEqual(steam_errors.explain_steamworks_message(text), text)   # idempotent
        self.assertEqual(steam_errors.explain_steamworks_message("odd"), "odd")

    def test_init_results_and_http_statuses(self):
        self.assertIn("NoSteamClient", steam_errors.describe_init_result(2))
        self.assertIn("publisher", steam_errors.describe_http_status(403))
        self.assertIn("EResult 15 AccessDenied", steam_errors.describe_http_status(403, "15"))
        self.assertIn("HTTP 418", steam_errors.describe_http_status(418))

    def test_steamcmd_exit_codes(self):
        self.assertIn("InvalidPassword", steam_errors.describe_steamcmd_exit(5))
        self.assertIn("code 7", steam_errors.describe_steamcmd_exit(7))
        self.assertIn("crashed", steam_errors.describe_steamcmd_exit(-1))

    def test_reference_lists_every_code(self):
        headings = [h for h, _ in steam_errors.reference_entries()]
        self.assertIn("EResult 25: LimitExceeded", headings)
        self.assertIn("Steam Web API HTTP 429", headings)
        self.assertTrue(any(h.startswith("SteamCMD: ") for h in headings))

    def test_documentation_lists_every_code(self):
        doc_path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "publishing", "STEAM_ERRORS.md")
        with open(doc_path, encoding="utf-8") as f:
            doc = f.read()
        for info in steam_errors.ERESULTS.values():
            self.assertIn(f"| {info.code} | `{info.name}` |", doc)
        for status in steam_errors.HTTP_STATUS_TEXT:
            self.assertIn(f"| {status} |", doc)


class TestSteamCmdLogDiagnosis(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.exe = os.path.join(self.dir, "steamcmd.exe")
        os.makedirs(os.path.join(self.dir, "logs"))
        self.backend = WorkshopBackend(SimpleNamespace())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir)

    def _console_log(self, *lines):
        with open(os.path.join(self.dir, "logs", "console_log.txt"), "w") as f:
            f.write("\n".join(lines) + "\n")

    def test_only_errors_from_this_upload_are_reported(self):
        now = time.time()
        stamp = lambda t: datetime.fromtimestamp(t).strftime("[%Y-%m-%d %H:%M:%S]")
        self._console_log(
            f"{stamp(now - 3600)} ERROR! Failed to update workshop item (Access Denied).",
            f"{stamp(now + 1)} ERROR! Failed to update workshop item (Limit Exceeded).")
        found = self.backend.diagnose_last_upload(self.exe, "301650", since=now)
        self.assertEqual([d["title"] for d in found], ["Limit Exceeded (EResult 25)"])
        self.assertIn("Limit Exceeded", self.backend.analyze_last_upload_log(self.exe, "301650", since=now))

    def test_logs_untouched_since_the_upload_are_ignored(self):
        self._console_log("ERROR! Failed to update workshop item (Access Denied).")
        self.assertEqual(self.backend.diagnose_last_upload(self.exe, "301650", since=time.time() + 60), [])


if __name__ == "__main__":
    unittest.main()
