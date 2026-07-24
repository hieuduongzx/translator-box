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
from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from config import AppConfig  # noqa: E402
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
            labels, ["Dịch", "OCR", "Khung dịch", "Phím tắt", "Giới thiệu"]
        )
        self.assertEqual(self.window.pages.count(), 5)
        self.assertEqual(
            self.window.navigation.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )

    def test_left_navigation_switches_current_page(self) -> None:
        self.window.navigation.setCurrentRow(2)

        self.assertEqual(self.window.pages.currentIndex(), 2)

    def test_hud_controls_use_requested_defaults(self) -> None:
        font_families = [
            self.window.font_family_box.itemData(index)
            for index in range(self.window.font_family_box.count())
        ]

        self.assertEqual(font_families, ["Yu Gothic", "Arial"])
        self.assertEqual(self.window.font_family_box.currentData(), "Yu Gothic")
        self.assertEqual(self.window.font_size_spin.value(), 16)
        self.assertEqual(self.window.text_color_btn.color_hex(), "#000000")
        self.assertEqual(self.window.border_width_spin.value(), 1)
        self.assertEqual(self.window.border_color_btn.color_hex(), "#ffffff")
        self.assertEqual(self.window.background_color_btn.color_value(), "#00000000")

    def test_border_width_accepts_subpixel_values(self) -> None:
        self.window.border_width_spin.setValue(0.5)

        self.assertEqual(self.window.border_width_spin.value(), 0.5)
        self.assertEqual(self.window.config.hud_border_width, 0.5)

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
