from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import config  # noqa: E402


class AppConfigTests(unittest.TestCase):
    def test_invalid_values_fall_back_without_crashing(self) -> None:
        settings = config.AppConfig(
            {
                "ocr_engine": "invalid",
                "ocr_acceleration": "yes",
                "translator": [],
                "live_interval_ms": "not-a-number",
                "hud_font_size": None,
                "hud_border_width": 99,
                "hud_text_color": "red",
                "hud_font_family": " ",
                "hud_background_color": "transparent",
                "llm_endpoint": "file:///tmp/invalid",
                "llm_api_key": 123,
                "llm_model": "unknown",
                "hud_geometry": "invalid",
                "hotkeys": {"selected_text": 12},
            }
        )

        self.assertEqual(settings.ocr_engine, "rapidocr")
        self.assertEqual(settings.ocr_model, "ppocrv5_mobile")
        self.assertEqual(settings.ocr_backend, "auto")
        self.assertFalse(settings.ocr_acceleration)
        self.assertEqual(settings.translator, "google")
        self.assertEqual(settings.live_interval_ms, 900)
        self.assertEqual(settings.hud_font_size, 16)
        self.assertEqual(settings.hud_border_width, 8)
        self.assertEqual(settings.hud_text_color, "#000000")
        self.assertEqual(settings.hud_border_color, "#ffffff")
        self.assertEqual(settings.hud_font_family, "Yu Gothic")
        self.assertEqual(settings.hud_background_color, "#00000000")
        self.assertEqual(settings.llm_endpoint, "http://103.38.236.38:20128/v1")
        self.assertEqual(settings.llm_api_key, "")
        self.assertEqual(settings.llm_model, "mistral/mistral-small-latest")
        self.assertTrue(settings.hud_pinned)
        self.assertEqual(
            settings.hotkeys["selected_text"],
            config.DEFAULT_HOTKEYS["selected_text"],
        )

    def test_save_uses_replace_and_leaves_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            with mock.patch.object(config, "config_path", return_value=path):
                settings = config.AppConfig({"target_language": "en"})
                settings.save()

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["target_language"], "en")
            self.assertFalse(payload["ocr_acceleration"])
            self.assertTrue(payload["hud_pinned"])
            self.assertEqual(payload["hud_font_family"], "Yu Gothic")
            self.assertEqual(payload["hud_font_size"], 16)
            self.assertEqual(payload["hud_text_color"], "#000000")
            self.assertEqual(payload["hud_border_width"], 1)
            self.assertEqual(payload["hud_border_color"], "#ffffff")
            self.assertEqual(payload["hud_background_color"], "#00000000")
            self.assertEqual(payload["llm_endpoint"], "http://103.38.236.38:20128/v1")
            self.assertEqual(payload["llm_api_key"], "")
            self.assertEqual(payload["llm_model"], "mistral/mistral-small-latest")
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_font_family_is_limited_to_supported_catalog(self) -> None:
        unsupported = config.AppConfig({"hud_font_family": "Comic Sans MS"})
        normalized = config.AppConfig({"hud_font_family": "yu gothic"})

        self.assertEqual(unsupported.hud_font_family, "Yu Gothic")
        self.assertEqual(normalized.hud_font_family, "Yu Gothic")


if __name__ == "__main__":
    unittest.main()
