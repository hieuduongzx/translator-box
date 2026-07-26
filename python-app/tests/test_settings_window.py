from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QLineEdit,
    QPushButton,
)

from config import HUD_STYLE_DEFAULTS, AppConfig  # noqa: E402
from settings_window import SettingsWindow, available_hud_font_options  # noqa: E402


class FakeHud:
    def __init__(self) -> None:
        self.config = AppConfig()
        self.config.save = mock.Mock()
        self.app_icon = QIcon()
        self.bridge = SimpleNamespace(
            run=SimpleNamespace(emit=lambda callback: callback())
        )
        self.hotkeys = SimpleNamespace(apply=lambda _mapping: None)
        self.background_toggle_button = QPushButton()
        self.background_toggle_button.setCheckable(True)
        self.background_toggle_button.setChecked(self.config.hud_background_enabled)

    def _sync_background_toggle_tooltip(self) -> None:
        pass

    def sync_target_combo(self) -> None:
        pass

    def sync_translation_controls(self) -> None:
        pass

    def set_status(self, *_args) -> None:
        pass

    def apply_hud_text_style(self) -> None:
        pass

    def preview_hud_text_style(self, *_args) -> None:
        pass

    def refresh_bar_tooltips(self) -> None:
        pass


class SettingsWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        patches = (
            mock.patch(
                "settings_window.services.ocr_engine_status",
                return_value=(True, "Sẵn sàng"),
            ),
            mock.patch("settings_window.model_installed", return_value=True),
            mock.patch(
                "settings_window.backend_status",
                return_value=(True, "Sẵn sàng"),
            ),
            mock.patch(
                "settings_window.QFontDatabase.families",
                return_value=["Yu Gothic", "Arial", "Comic Sans MS"],
            ),
        )
        self.patches = patches
        for patcher in patches:
            patcher.start()
        self.window = SettingsWindow(FakeHud())

    def tearDown(self) -> None:
        self.window._quitting = True
        self.window.close()
        for patcher in reversed(self.patches):
            patcher.stop()

    def test_left_navigation_contains_all_settings_tabs(self) -> None:
        labels = [
            self.window.navigation.item(index).text()
            for index in range(self.window.navigation.count())
        ]

        self.assertEqual(
            labels,
            [
                "[01]  DỊCH",
                "[02]  DỊCH VỤ AI",
                "[03]  OCR",
                "[04]  KHUNG DỊCH",
                "[05]  PHÍM TẮT",
                "[06]  GIỚI THIỆU",
            ],
        )
        self.assertEqual(self.window.pages.count(), 6)
        self.assertEqual(
            self.window.navigation.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self.window.resize(self.window.minimumSize())
        self.window.show()
        self.app.processEvents()
        last_item = self.window.navigation.item(self.window.navigation.count() - 1)
        last_rect = self.window.navigation.visualItemRect(last_item)
        self.assertLessEqual(
            last_rect.bottom(), self.window.navigation.viewport().rect().bottom()
        )
        self.assertEqual(self.window.navigation.verticalScrollBar().maximum(), 0)

    def test_left_navigation_switches_current_page(self) -> None:
        self.window.navigation.setCurrentRow(1)

        self.assertEqual(self.window.pages.currentIndex(), 1)
        self.assertEqual(
            self.window.navigation.currentItem().text(), "[02]  DỊCH VỤ AI"
        )

    def test_ai_services_has_explicit_provider_management(self) -> None:
        service_entries = [
            self.window.service_box.itemText(index)
            for index in range(self.window.service_box.count())
        ]

        self.assertNotIn("＋ Thêm provider tùy chỉnh…", service_entries)
        self.assertEqual(self.window.add_provider_btn.text(), "Thêm provider")
        self.assertGreaterEqual(self.window.ai_provider_box.count(), 3)
        self.assertFalse(self.window.llm_frame.isHidden())

    def test_ai_provider_requires_key_before_activation(self) -> None:
        openai_index = self.window.ai_provider_box.findData("openai")
        self.window.ai_provider_box.setCurrentIndex(openai_index)

        self.assertEqual(self.window.llm_endpoint_edit.text(), "https://api.openai.com/v1")
        self.assertFalse(self.window.activate_ai_btn.isEnabled())
        self.assertEqual(self.window.ai_provider_state.text(), "CHƯA CÓ API KEY")
        self.assertEqual(self.window.service_box.findData("openai::gpt-4o"), -1)

        self.window.llm_key_edit.setText("sk-test")
        self.window._on_key_changed()
        self.assertTrue(self.window.activate_ai_btn.isEnabled())
        self.assertGreaterEqual(self.window.service_box.findData("openai::gpt-4o"), 0)
        self.window._activate_ai_provider()

        self.assertEqual(self.window.config.translator, "openai")
        self.assertEqual(self.window.service_box.currentData(), "openai::gpt-4o-mini")
        self.assertFalse(self.window.activate_ai_btn.isEnabled())
        self.assertEqual(self.window.ai_provider_state.text(), "ĐANG DÙNG")

    def test_add_provider_registers_and_selects_custom_ai_service(self) -> None:
        payload = {
            "name": "Local AI",
            "endpoint": "http://127.0.0.1:11434/v1",
            "api_key": "local-key",
            "models": ["qwen2.5"],
        }
        with mock.patch("settings_window.ProviderDialog") as dialog_type:
            dialog_type.return_value.exec.return_value = QDialog.DialogCode.Accepted
            dialog_type.return_value.data.return_value = payload

            self.window._add_provider()

        code = "custom:cp1"
        self.assertEqual(self.window.config.translator, code)
        self.assertEqual(self.window.ai_provider_box.currentData(), code)
        self.assertGreaterEqual(
            self.window.service_box.findData("custom::cp1::qwen2.5"), 0
        )
        self.assertEqual(self.window.llm_endpoint_edit.text(), payload["endpoint"])

    def test_builtin_provider_supports_inline_model_add_and_remove(self) -> None:
        openai_index = self.window.ai_provider_box.findData("openai")
        self.window.ai_provider_box.setCurrentIndex(openai_index)
        self.window.llm_key_edit.setText("sk-test")
        self.window._on_key_changed()
        self.window.model_id_input.setText("gpt-5-mini-preview")

        self.window._add_ai_model()

        self.assertIn("gpt-5-mini-preview", self.window.config.ai_models["openai"])
        self.assertGreaterEqual(
            self.window.service_box.findData("openai::gpt-5-mini-preview"), 0
        )
        model_index = self.window.llm_model_box.findData("gpt-5-mini-preview")
        self.window.llm_model_box.setCurrentIndex(model_index)
        self.assertTrue(self.window.remove_ai_model_btn.isEnabled())

        self.window._remove_ai_model()

        self.assertEqual(self.window.llm_model_box.findData("gpt-5-mini-preview"), -1)
        self.assertEqual(
            self.window.service_box.findData("openai::gpt-5-mini-preview"), -1
        )

    def test_hud_controls_use_requested_defaults(self) -> None:
        font_families = [
            self.window.font_family_box.itemData(index)
            for index in range(self.window.font_family_box.count())
        ]
        defaults = HUD_STYLE_DEFAULTS

        self.assertEqual(font_families, ["Yu Gothic", "Arial"])
        self.assertEqual(self.window.font_family_box.currentData(), "Yu Gothic")
        self.assertEqual(self.window.font_size_spin.value(), defaults["hud_font_size"])
        self.assertEqual(
            self.window.text_color_btn.color_hex(), defaults["hud_text_color"]
        )
        self.assertEqual(
            self.window.border_width_spin.value(), defaults["hud_border_width"]
        )
        self.assertEqual(
            self.window.border_color_btn.color_hex(), defaults["hud_border_color"]
        )
        self.assertEqual(
            self.window.background_color_btn.color_value(),
            defaults["hud_background_color"],
        )
        self.assertEqual(
            self.window.background_enabled_check.isChecked(),
            defaults["hud_background_enabled"],
        )
        self.assertEqual(
            self.window.shadow_radius_spin.value(), defaults["hud_shadow_radius"]
        )
        self.assertEqual(
            self.window.shadow_color_btn.color_value(), defaults["hud_shadow_color"]
        )

    def test_hud_style_reset_restores_legible_defaults(self) -> None:
        self.window.font_size_spin.setValue(40)
        self.window.shadow_radius_spin.setValue(0.0)
        self.window.text_color_btn.set_color("#123456")
        self.window.border_width_spin.setValue(0.0)
        self.window.background_enabled_check.setChecked(False)

        self.window._reset_hud_style()

        defaults = HUD_STYLE_DEFAULTS
        self.assertEqual(self.window.font_size_spin.value(), defaults["hud_font_size"])
        self.assertEqual(
            self.window.shadow_radius_spin.value(), defaults["hud_shadow_radius"]
        )
        self.assertEqual(
            self.window.text_color_btn.color_hex(), defaults["hud_text_color"]
        )
        self.assertEqual(self.window.config.hud_border_width, defaults["hud_border_width"])
        self.assertEqual(self.window.config.hud_shadow_color, defaults["hud_shadow_color"])
        self.assertEqual(
            self.window.background_enabled_check.isChecked(),
            defaults["hud_background_enabled"],
        )
        self.assertEqual(
            self.window.background_color_btn.isEnabled(),
            defaults["hud_background_enabled"],
        )

    def test_hud_style_values_include_shadow_for_preview(self) -> None:
        self.window.shadow_radius_spin.setValue(4.5)

        values = self.window._hud_style_values()

        self.assertEqual(len(values), 9)
        self.assertEqual(values[6], 4.5)
        self.assertEqual(values[7], HUD_STYLE_DEFAULTS["hud_shadow_color"])
        self.assertEqual(values[8], HUD_STYLE_DEFAULTS["hud_background_enabled"])

    def test_border_width_accepts_subpixel_values(self) -> None:
        self.window.border_width_spin.setValue(0.5)

        self.assertEqual(self.window.border_width_spin.value(), 0.5)
        self.assertEqual(self.window.config.hud_border_width, 0.5)

    def test_clipboard_image_hotkeys_are_configurable(self) -> None:
        self.assertEqual(
            self.window.hotkey_edits["clipboard_image_replace"].combo(),
            "ctrl+alt+v",
        )
        self.assertEqual(
            self.window.hotkey_edits["clipboard_image_to_text"].combo(),
            "ctrl+alt+t",
        )

    def test_ocr_model_dropdown_marks_download_state(self) -> None:
        with mock.patch(
            "settings_window.model_installed",
            side_effect=lambda model_id: model_id
            in {"ppocrv5_mobile", "ppocrv6_tiny"},
        ):
            self.window._refresh_ocr_model_options("ppocrv6_tiny")

        labels = {
            self.window.model_box.itemData(index): self.window.model_box.itemText(index)
            for index in range(self.window.model_box.count())
        }
        self.assertEqual(len(labels), 4)
        self.assertEqual(
            labels["ppocrv5_mobile"], "✓ PP-OCRv5 mobile · Tích hợp"
        )
        self.assertEqual(labels["ppocrv6_tiny"], "✓ PP-OCRv6 tiny · Đã tải")
        self.assertIn("Chưa tải", labels["ppocrv6_small"])
        self.assertIn("25.2 MB", labels["ppocrv6_small"])

    def test_ocr_download_error_replaces_unsupported_jargon(self) -> None:
        self.window._finish_model_download(
            "ppocrv6_tiny",
            "Unsupported det.lang_type='multi' for PP-OCRv6 tiny model.",
        )

        message = self.window.model_download_status.text()
        self.assertFalse(self.window.model_download_status.isHidden())
        self.assertIn("không tương thích", message)
        self.assertNotIn("Unsupported", message)

    def test_llm_fields_use_public_endpoint_and_require_user_key(self) -> None:
        self.window.service_box.setCurrentIndex(self.window.service_box.findData("llm"))

        self.assertFalse(self.window.llm_frame.isHidden())
        self.assertEqual(
            self.window.llm_endpoint_edit.text(),
            "http://103.38.236.38:20128/v1",
        )
        self.assertEqual(self.window.llm_key_edit.text(), "")
        self.assertEqual(
            self.window.llm_key_edit.echoMode(), QLineEdit.EchoMode.Password
        )
        self.assertEqual(self.window.llm_model_box.count(), 2)
        self.assertIn(
            "http://103.38.236.38:20128/",
            self.window.llm_registration_link.text(),
        )

    def test_font_catalog_filters_unknown_fonts_and_keeps_order(self) -> None:
        options = available_hud_font_options(
            ["Arial", "Comic Sans MS", "Yu Gothic", "Malgun Gothic"]
        )

        self.assertEqual(
            [family for family, _coverage in options],
            ["Yu Gothic", "Arial", "Malgun Gothic"],
        )

    def test_font_catalog_has_safe_fallback_when_system_list_is_empty(self) -> None:
        options = available_hud_font_options([])

        self.assertEqual(
            [family for family, _coverage in options],
            ["Yu Gothic", "Segoe UI", "Arial"],
        )


if __name__ == "__main__":
    unittest.main()
