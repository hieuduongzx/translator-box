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
        defaults = config.HUD_STYLE_DEFAULTS
        self.assertEqual(settings.hud_font_size, defaults["hud_font_size"])
        self.assertEqual(settings.hud_border_width, 8)  # 99 bị kẹp về trần 8px
        self.assertEqual(settings.hud_text_color, defaults["hud_text_color"])
        self.assertEqual(settings.hud_border_color, defaults["hud_border_color"])
        self.assertEqual(settings.hud_font_family, defaults["hud_font_family"])
        self.assertEqual(
            settings.hud_background_color, defaults["hud_background_color"]
        )
        # Config này đã có kiểu chữ riêng → không tự bật bóng chữ.
        self.assertEqual(settings.hud_shadow_radius, 0.0)
        self.assertEqual(settings.hud_shadow_color, defaults["hud_shadow_color"])
        self.assertEqual(settings.llm_endpoint, "http://103.38.236.38:20128/v1")
        self.assertEqual(settings.llm_api_key, "")
        self.assertEqual(settings.llm_model, "deepseek-v4-flash")
        self.assertTrue(settings.hud_pinned)
        self.assertEqual(
            settings.hotkeys["selected_text"],
            config.DEFAULT_HOTKEYS["selected_text"],
        )
        self.assertEqual(settings.hotkeys["clipboard_image_replace"], "ctrl+alt+v")
        self.assertEqual(settings.hotkeys["clipboard_image_to_text"], "ctrl+alt+t")

    def test_previous_clipboard_image_hotkey_migrates_to_split_actions(self) -> None:
        settings = config.AppConfig(
            {"hotkeys": {"clipboard_image_to_text": "ctrl+alt+v"}}
        )

        self.assertEqual(settings.hotkeys["clipboard_image_replace"], "ctrl+alt+v")
        self.assertEqual(settings.hotkeys["clipboard_image_to_text"], "ctrl+alt+t")

    def test_removed_ocr_model_falls_back_to_v5_mobile(self) -> None:
        settings = config.AppConfig({"ocr_model": "ppocrv5_server"})

        self.assertEqual(settings.ocr_model, "ppocrv5_mobile")

    def test_live_focus_application_is_normalized_and_persisted(self) -> None:
        settings = config.AppConfig(
            {
                "live_focus_app_id": " C:/Apps/Reader.EXE ",
                "live_focus_app_label": " Reader ",
            }
        )

        self.assertEqual(settings.live_focus_app_id, "c:/apps/reader.exe")
        self.assertEqual(settings.live_focus_app_label, "Reader")
        self.assertEqual(settings.to_dict()["live_focus_app_id"], "c:/apps/reader.exe")
        invalid = config.AppConfig(
            {"live_focus_app_id": 123, "live_focus_app_label": object()}
        )
        self.assertEqual(invalid.live_focus_app_id, "")
        self.assertEqual(invalid.live_focus_app_label, "")

    def test_fresh_config_uses_legible_hud_preset(self) -> None:
        settings = config.AppConfig({})

        for key, value in config.HUD_STYLE_DEFAULTS.items():
            self.assertEqual(getattr(settings, key), value, key)

    def test_soniox_defaults_and_validation_keep_language_pair_distinct(self) -> None:
        defaults = config.AppConfig()
        self.assertEqual(defaults.soniox_api_key, "")
        self.assertEqual(defaults.soniox_audio_source, "system")
        self.assertEqual(defaults.soniox_system_device, "")
        self.assertEqual(defaults.soniox_translation_mode, "one_way")
        self.assertEqual(defaults.soniox_target_language, "vi")
        self.assertEqual(
            (defaults.soniox_language_a, defaults.soniox_language_b), ("en", "vi")
        )
        self.assertFalse(defaults.soniox_speaker_diarization)
        self.assertEqual(defaults.soniox_display_mode, "bilingual")
        self.assertEqual(defaults.soniox_text_alignment, "center")

        normalized = config.AppConfig(
            {
                "soniox_api_key": 123,
                "soniox_audio_source": "invalid",
                "soniox_system_device": "Headphones [Loopback]",
                "soniox_translation_mode": "invalid",
                "soniox_target_language": "zh-CN",
                "soniox_language_a": "ja",
                "soniox_language_b": "ja",
                "soniox_speaker_diarization": "yes",
                "soniox_display_mode": "invalid",
                "soniox_text_alignment": "justify",
            }
        )
        self.assertEqual(normalized.soniox_api_key, "")
        self.assertEqual(normalized.soniox_audio_source, "system")
        self.assertEqual(normalized.soniox_system_device, "Headphones [Loopback]")
        self.assertEqual(normalized.soniox_translation_mode, "one_way")
        self.assertEqual(normalized.soniox_target_language, "vi")
        self.assertEqual(
            (normalized.soniox_language_a, normalized.soniox_language_b), ("ja", "vi")
        )
        self.assertFalse(normalized.soniox_speaker_diarization)
        self.assertEqual(normalized.soniox_display_mode, "bilingual")
        self.assertEqual(normalized.soniox_text_alignment, "center")
        self.assertFalse(
            config.AppConfig(
                {"soniox_speaker_diarization": True}
            ).soniox_speaker_diarization
        )
        self.assertTrue(
            config.AppConfig(
                {
                    "soniox_speaker_diarization": True,
                    "soniox_speaker_setting_version": 2,
                }
            ).soniox_speaker_diarization
        )

    def test_previous_default_preset_upgrades_to_new_glow_preset(self) -> None:
        legacy = {
            "hud_font_family": "Segoe UI",
            "hud_font_size": 18,
            "hud_text_color": "#ffffff",
            "hud_border_width": 0.5,
            "hud_border_color": "#101114",
            "hud_background_color": "#00000000",
            "hud_shadow_radius": 6.0,
            "hud_shadow_color": "#cc000000",
        }

        settings = config.AppConfig(legacy)

        for key, value in config.HUD_STYLE_DEFAULTS.items():
            self.assertEqual(getattr(settings, key), value, key)

    def test_config_from_older_version_keeps_text_shadow_off(self) -> None:
        """Người dùng cũ mở bản mới không bị đổi giao diện khung dịch."""
        settings = config.AppConfig(
            {
                "hud_font_family": "Segoe UI",
                "hud_font_size": 20,
                "hud_text_color": "#ff0004",
                "hud_border_width": 0.0,
            }
        )

        self.assertEqual(settings.hud_shadow_radius, 0.0)
        self.assertEqual(settings.hud_text_color, "#ff0004")
        self.assertEqual(settings.hud_font_size, 20)

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
            for key, value in config.HUD_STYLE_DEFAULTS.items():
                self.assertEqual(payload[key], value)
            self.assertEqual(payload["llm_endpoint"], "http://103.38.236.38:20128/v1")
            self.assertEqual(payload["llm_api_key"], "")
            self.assertEqual(payload["llm_model"], "deepseek-v4-flash")
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_builtin_llm_endpoint_is_fixed_regardless_of_stored_value(self) -> None:
        settings = config.AppConfig(
            {
                "translator": "llm",
                "llm_endpoint": "http://other.test/v1",
                "llm_api_key": "k",
                "llm_model": "deepseek-v4-pro",
            }
        )
        service, endpoint, key, model = settings.resolve_llm()
        self.assertEqual(service, "llm")
        self.assertEqual(endpoint, "http://103.38.236.38:20128/v1")
        self.assertEqual((key, model), ("k", "deepseek-v4-pro"))

    def test_builtin_openai_and_gemini_providers(self) -> None:
        openai = config.AppConfig(
            {
                "translator": "openai",
                "llm_model": "gpt-4o",
                "ai_keys": {"openai": "sk-oa", "gemini": "sk-gm"},
            }
        )
        service, endpoint, key, model = openai.resolve_llm()
        self.assertEqual(service, "llm")
        self.assertEqual(endpoint, "https://api.openai.com/v1")
        self.assertEqual((key, model), ("sk-oa", "gpt-4o"))

        gemini = config.AppConfig(
            {"translator": "gemini", "ai_keys": {"gemini": "sk-gm"}}
        )
        service, endpoint, key, _model = gemini.resolve_llm()
        self.assertEqual(
            endpoint, "https://generativelanguage.googleapis.com/v1beta/openai"
        )
        self.assertEqual(key, "sk-gm")
        # Model mặc định rơi về model đầu tiên của provider khi chưa hợp lệ.
        self.assertEqual(gemini.provider_api_key("gemini"), "sk-gm")

    def test_ai_models_are_normalized_and_unconfigured_provider_cannot_run(
        self,
    ) -> None:
        settings = config.AppConfig(
            {
                "ai_models": {
                    "openai": [" gpt-custom ", "gpt-custom", "", 12],
                    "unknown": ["ignored"],
                }
            }
        )

        self.assertEqual(settings.ai_models, {"openai": ["gpt-custom"]})
        self.assertIn("gpt-custom", settings.provider_models("openai"))
        self.assertEqual(settings.configured_ai_provider_ids(), set())
        settings.translator = "openai"
        settings.llm_model = "gpt-custom"
        self.assertEqual(settings.resolve_llm(), ("google", "", "", ""))
        self.assertEqual(settings.to_dict()["ai_models"], {"openai": ["gpt-custom"]})

    def test_google_resolves_without_llm_params(self) -> None:
        settings = config.AppConfig({"translator": "google"})
        self.assertEqual(settings.resolve_llm(), ("google", "", "", ""))

    def test_custom_provider_round_trips_and_resolves(self) -> None:
        settings = config.AppConfig(
            {
                "translator": "custom:cp1",
                "llm_model": "gpt-4o-mini",
                "custom_providers": [
                    {
                        "id": "cp1",
                        "name": "OpenRouter",
                        "endpoint": "https://openrouter.ai/api/v1/",
                        "api_key": "sk-x",
                        "models": ["gpt-4o-mini", "llama-3"],
                    }
                ],
            }
        )
        self.assertEqual(settings.translator, "custom:cp1")
        self.assertEqual(settings.active_provider()["name"], "OpenRouter")
        service, endpoint, key, model = settings.resolve_llm()
        self.assertEqual(service, "llm")
        self.assertEqual(endpoint, "https://openrouter.ai/api/v1")  # trailing / trimmed
        self.assertEqual((key, model), ("sk-x", "gpt-4o-mini"))

    def test_invalid_custom_provider_and_dangling_selection_fall_back(self) -> None:
        settings = config.AppConfig(
            {
                "translator": "custom:ghost",
                "custom_providers": [
                    {"id": "bad", "name": "", "endpoint": "ftp://x", "models": []},
                ],
            }
        )
        self.assertEqual(settings.custom_providers, [])
        self.assertEqual(settings.translator, "google")

    def test_font_family_is_limited_to_supported_catalog(self) -> None:
        unsupported = config.AppConfig({"hud_font_family": "Comic Sans MS"})
        normalized = config.AppConfig({"hud_font_family": "yu gothic"})

        self.assertEqual(
            unsupported.hud_font_family,
            config.HUD_STYLE_DEFAULTS["hud_font_family"],
        )
        self.assertEqual(normalized.hud_font_family, "Yu Gothic")


if __name__ == "__main__":
    unittest.main()
