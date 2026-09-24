import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bztoolbox.modules.localization import localization


class OdfDisplayNameTests(unittest.TestCase):
    def setUp(self):
        self.app = localization.BZ98GuiApp.__new__(localization.BZ98GuiApp)
        self.app.log = lambda _message: None

    def _write_odf(self, text, filename="internal_unit_id.odf"):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / filename
        path.write_text(text, encoding="utf-8")
        return path

    def test_extracts_player_visible_unit_name(self):
        path = self._write_odf(
            """
            [GameObjectClass]
            classLabel = "wingman"
            aiName = "internal_ai_name"
            unitName = "Thunderbolt"
            """
        )

        self.assertEqual(self.app.extract_unit_name(path), "Thunderbolt")

    def test_does_not_fall_back_to_internal_odf_filename(self):
        path = self._write_odf(
            """
            [GameObjectClass]
            classLabel = "wingman"
            aiName = "internal_ai_name"
            """
        )

        self.assertIsNone(self.app.extract_unit_name(path))

    def test_ignores_commented_out_unit_name(self):
        path = self._write_odf(
            """
            // unitName = "Old Internal Name"
            classLabel = "wingman"
            """
        )

        self.assertIsNone(self.app.extract_unit_name(path))


class ExistingKeyEncodingTests(unittest.TestCase):
    def setUp(self):
        self.app = localization.BZ98GuiApp.__new__(localization.BZ98GuiApp)
        self.messages = []
        self.app.log = self.messages.append
        self.app._translator_cache = {}
        self.app._last_translation_request = 0.0
        self.app._translation_min_interval = 0.0

    def test_reads_keys_when_translated_columns_contain_legacy_bytes(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "localization_table.csv"
        path.write_bytes(
            b"names:eviscerator~Eviscerator~\xc8viscerateur\n"
            b"names:scout~Scout~Scout\n"
        )

        class CsvPath:
            def get(self_inner):
                return str(path)

        self.app.csv_path = CsvPath()

        self.assertEqual(
            self.app.get_existing_keys(),
            {"names:eviscerator", "names:scout"},
        )
        self.assertEqual(self.messages, [])


class LocalizationFormatTests(unittest.TestCase):
    def setUp(self):
        self.app = localization.BZ98GuiApp.__new__(localization.BZ98GuiApp)

    def test_names_key_preserves_stock_case_spaces_and_punctuation(self):
        self.assertEqual(
            self.app.make_names_key("Heavy Tank"),
            "names:Heavy Tank",
        )
        self.assertEqual(
            self.app.make_names_key("Day Wrecker"),
            "names:Day Wrecker",
        )
        self.assertEqual(
            self.app.make_names_key("apc_1"),
            "names:apc_1",
        )

    def test_row_encoding_matches_stock_mixed_codepages_and_crlf(self):
        row = [
            "names:Heavy Tank",
            "Heavy Tank",
            "Char lourd",
            "Schwerer Panzer",
            "Tanque pesado",
            "Carro pesante",
            "Тяжёлый танк",
            "Tanque pesado",
        ]

        encoded = self.app._encode_localization_row(row)

        self.assertTrue(encoded.endswith(b"\r\n"))
        fields = encoded[:-2].split(b"~")
        self.assertEqual(len(fields), 8)
        self.assertEqual(fields[0].decode("cp1252"), "names:Heavy Tank")
        self.assertEqual(fields[2].decode("cp1252"), "Char lourd")
        self.assertEqual(fields[6].decode("cp1251"), "Тяжёлый танк")
        self.assertEqual(fields[7].decode("cp1252"), "Tanque pesado")

    def test_row_writer_rejects_delimiter_inside_field(self):
        row = [
            "names:Bad~Key",
            "Bad",
            "Bad",
            "Bad",
            "Bad",
            "Bad",
            "Плохо",
            "Bad",
        ]

        with self.assertRaises(ValueError):
            self.app._encode_localization_row(row)

    def test_target_table_requires_stock_header(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "localization_table.csv"
        path.write_bytes(
            localization.LOCALIZATION_HEADER
            + b"\r\n"
            + b"~~~~~~~\r\n"
        )

        class CsvPath:
            def get(self_inner):
                return str(path)

        self.app.csv_path = CsvPath()
        self.app.validate_target_table_format()

    def test_target_table_rejects_wrong_header(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "localization_table.csv"
        path.write_bytes(b"Key,English,French\r\n")

        class CsvPath:
            def get(self_inner):
                return str(path)

        self.app.csv_path = CsvPath()

        with self.assertRaises(ValueError):
            self.app.validate_target_table_format()


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.app = localization.BZ98GuiApp.__new__(localization.BZ98GuiApp)
        self.app.languages = ["French", "German"]
        self.app.lang_codes = {"French": "fr", "German": "de"}
        self.messages = []
        self.app.log = self.messages.append
        self.app._translator_cache = {}
        self.app._last_translation_request = 0.0
        self.app._translation_min_interval = 0.0

    def test_translate_text_returns_real_target_results(self):
        class FakeTranslator:
            def __init__(self, source, target):
                self.source = source
                self.target = target

            def translate(self, text):
                return f"{self.target}:{text}"

        with patch.object(localization, "GoogleTranslator", FakeTranslator), patch.object(
            localization.time, "sleep", lambda _seconds: None
        ):
            translated = self.app.translate_text("Scout")

        self.assertEqual(translated, ["fr:Scout", "de:Scout"])

    def test_translation_failure_raises_instead_of_returning_english(self):
        class FailingTranslator:
            def __init__(self, source, target):
                pass

            def translate(self, text):
                raise RuntimeError("translator unavailable")

        with patch.object(localization, "GoogleTranslator", FailingTranslator), patch.object(
            localization.time, "sleep", lambda _seconds: None
        ):
            with self.assertRaises(RuntimeError):
                self.app.translate_text("Scout", retries=2)

    def test_rate_limit_uses_longer_cooldown_before_retry(self):
        attempts = {"count": 0}
        sleeps = []

        class ThrottledTranslator:
            def __init__(self, source, target):
                pass

            def translate(self, text):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise RuntimeError("429 Too many requests")
                return "translated"

        self.app.languages = ["French"]
        self.app.lang_codes = {"French": "fr"}

        with patch.object(localization, "GoogleTranslator", ThrottledTranslator), patch.object(
            localization.time, "sleep", sleeps.append
        ):
            translated = self.app.translate_text("Scout", retries=2)

        self.assertEqual(translated, ["translated"])
        self.assertIn(15, sleeps)

    def test_persistent_rate_limit_raises_circuit_breaker_error(self):
        class AlwaysThrottledTranslator:
            def __init__(self, source, target):
                pass

            def translate(self, text):
                raise RuntimeError("429 Too many requests")

        self.app.languages = ["French"]
        self.app.lang_codes = {"French": "fr"}

        with patch.object(
            localization, "GoogleTranslator", AlwaysThrottledTranslator
        ), patch.object(localization.time, "sleep", lambda _seconds: None):
            with self.assertRaises(localization.TranslationRateLimitError):
                self.app.translate_text("Scout", retries=2)

    def test_reuses_translator_instances_for_repeated_work(self):
        created = []

        class ReusedTranslator:
            def __init__(self, source, target):
                created.append(target)
                self.target = target

            def translate(self, text):
                return f"{self.target}:{text}"

        with patch.object(localization, "GoogleTranslator", ReusedTranslator), patch.object(
            localization.time, "sleep", lambda _seconds: None
        ):
            self.app.translate_text("Scout")
            self.app.translate_text("Tank")

        self.assertEqual(created, ["fr", "de"])


class CloudBatchTranslationTests(unittest.TestCase):
    def setUp(self):
        self.app = localization.BZ98GuiApp.__new__(localization.BZ98GuiApp)
        self.app.languages = ["French", "German"]
        self.app.lang_codes = {"French": "fr", "German": "de"}
        self.messages = []
        self.app.log = self.messages.append

    def test_321_names_use_one_request_per_language(self):
        texts = [f"Unit {index}" for index in range(321)]
        calls = []

        class DummyCredentials:
            token = "test-token"

        class FakeResponse:
            status_code = 200
            text = ""

            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

        def fake_post(url, headers, json, timeout):
            calls.append(
                {
                    "url": url,
                    "headers": headers,
                    "json": json,
                    "timeout": timeout,
                }
            )
            target = json["targetLanguageCode"]
            return FakeResponse(
                {
                    "translations": [
                        {"translatedText": f"{target}:{text}"}
                        for text in json["contents"]
                    ]
                }
            )

        with patch.object(
            self.app,
            "_load_cloud_credentials",
            return_value=("battlezone-test", DummyCredentials()),
        ), patch.object(localization.requests, "post", side_effect=fake_post):
            translated = self.app.translate_batch_cloud(texts)

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["json"]["contents"], texts)
        self.assertEqual(calls[1]["json"]["contents"], texts)
        self.assertEqual(
            [call["json"]["targetLanguageCode"] for call in calls],
            ["fr", "de"],
        )
        self.assertEqual(translated[0], ["fr:Unit 0", "de:Unit 0"])
        self.assertEqual(
            translated[-1],
            ["fr:Unit 320", "de:Unit 320"],
        )

    def test_cloud_response_count_must_match_source_count(self):
        class DummyCredentials:
            token = "test-token"

        class FakeResponse:
            status_code = 200
            text = ""

            def json(self):
                return {"translations": [{"translatedText": "only one"}]}

        self.app.languages = ["French"]
        self.app.lang_codes = {"French": "fr"}

        with patch.object(
            self.app,
            "_load_cloud_credentials",
            return_value=("battlezone-test", DummyCredentials()),
        ), patch.object(localization.requests, "post", return_value=FakeResponse()):
            with self.assertRaises(localization.CloudTranslationError):
                self.app.translate_batch_cloud(["Scout", "Tank"])

    def test_large_input_is_chunked_only_when_cloud_limits_require_it(self):
        texts = ["x" * 100 for _ in range(301)]
        chunks = self.app._chunk_cloud_contents(texts)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[0]), 300)
        self.assertEqual(len(chunks[1]), 1)


class FreeHttpBatchTranslationTests(unittest.TestCase):
    def setUp(self):
        self.app = localization.BZ98GuiApp.__new__(localization.BZ98GuiApp)
        self.app.languages = ["French", "German"]
        self.app.lang_codes = {"French": "fr", "German": "de"}
        self.messages = []
        self.app.log = self.messages.append

    def test_321_short_names_use_one_free_request_per_language(self):
        texts = [f"Unit {index}" for index in range(321)]
        calls = []

        def fake_request(source_text, target):
            calls.append((target, source_text))
            return "\n".join(
                f"{target}:{line}" for line in source_text.split("\n")
            )

        with patch.object(
            self.app, "_request_free_http_translation", side_effect=fake_request
        ):
            translated = self.app.translate_batch_free_http(texts)

        self.assertEqual(len(calls), 2)
        self.assertEqual([call[0] for call in calls], ["fr", "de"])
        self.assertEqual(calls[0][1], "\n".join(texts))
        self.assertEqual(translated[0], ["fr:Unit 0", "de:Unit 0"])
        self.assertEqual(
            translated[-1],
            ["fr:Unit 320", "de:Unit 320"],
        )

    def test_line_boundary_mismatch_retries_with_markers(self):
        calls = []

        def fake_request(source_text, target):
            calls.append(source_text)
            if "[[BZ0]]" not in source_text:
                return "Char Réservoir"
            return "[[BZ0]] Char\n[[BZ1]] Réservoir"

        self.app.languages = ["French"]
        self.app.lang_codes = {"French": "fr"}

        with patch.object(
            self.app, "_request_free_http_translation", side_effect=fake_request
        ):
            translated = self.app.translate_batch_free_http(["Tank", "Reservoir"])

        self.assertEqual(len(calls), 2)
        self.assertEqual(translated, [["Char"], ["Réservoir"]])

    def test_rpc_request_uses_mkewbc_batchexecute(self):
        translated = "Char\nRéservoir"
        inner = [
            None,
            [[[None, None, None, False, None, [[translated]]]]],
        ]
        envelope = [["wrb.fr", "MkEWBc", localization.json.dumps(inner)]]

        class FakeResponse:
            status_code = 200
            text = "\n" + localization.json.dumps(envelope) + "\n"

        with patch.object(localization.requests, "post", return_value=FakeResponse()) as post:
            result = self.app._request_free_rpc_translation("Tank\nReservoir", "fr")

        self.assertEqual(result, translated)
        _, kwargs = post.call_args
        self.assertEqual(kwargs["params"]["rpcids"], "MkEWBc")
        self.assertIn("f.req", kwargs["data"])
        self.assertIn("MkEWBc", kwargs["data"]["f.req"])

    def test_free_provider_chain_falls_back_to_clients5(self):
        with patch.object(
            self.app,
            "_request_free_rpc_translation",
            side_effect=localization.FreeTranslationError("RPC blocked"),
        ), patch.object(
            self.app,
            "_request_free_clients5_translation",
            return_value="Char",
        ) as clients5, patch.object(
            self.app,
            "_request_free_legacy_translation",
        ) as legacy:
            translated = self.app._request_free_http_translation("Tank", "fr")

        self.assertEqual(translated, "Char")
        clients5.assert_called_once_with("Tank", "fr")
        legacy.assert_not_called()
        self.assertTrue(
            any("fallback succeeded via Chrome-extension endpoint" in msg for msg in self.messages)
        )

    def test_clients5_endpoint_uses_required_client_id(self):
        class FakeResponse:
            status_code = 200
            text = ""

            def json(self):
                return {"sentences": [{"trans": "Char"}]}

        with patch.object(localization.requests, "get", return_value=FakeResponse()) as get:
            translated = self.app._request_free_clients5_translation("Tank", "fr")

        self.assertEqual(translated, "Char")
        _, kwargs = get.call_args
        self.assertEqual(kwargs["params"]["client"], "dict-chrome-ex")
        self.assertEqual(kwargs["params"]["sl"], "en")
        self.assertEqual(kwargs["params"]["tl"], "fr")

    def test_legacy_429_error_is_concise(self):
        class FakeResponse:
            status_code = 429
            text = "<html><body><h1>We're sorry...</h1>" + ("x" * 5000) + "</body></html>"

            def json(self):
                raise ValueError("not json")

        with patch.object(localization.requests, "post", return_value=FakeResponse()):
            with self.assertRaises(localization.FreeTranslationError) as cm:
                self.app._request_free_legacy_translation("Scout", "fr")

        message = str(cm.exception)
        self.assertIn("HTTP 429", message)
        self.assertNotIn("<html>", message)
        self.assertLess(len(message), 300)

    def test_all_free_routes_fail_with_summary(self):
        error = localization.FreeTranslationError("blocked")
        with patch.object(
            self.app, "_request_free_rpc_translation", side_effect=error
        ), patch.object(
            self.app, "_request_free_clients5_translation", side_effect=error
        ), patch.object(
            self.app, "_request_free_legacy_translation", side_effect=error
        ):
            with self.assertRaises(localization.FreeTranslationError) as cm:
                self.app._request_free_http_translation("Scout", "fr")

        message = str(cm.exception)
        self.assertIn("web RPC", message)
        self.assertIn("Chrome-extension endpoint", message)
        self.assertIn("legacy endpoint", message)


if __name__ == "__main__":
    unittest.main()
