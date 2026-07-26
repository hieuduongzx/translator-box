from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from config import AppConfig  # noqa: E402
from constants import HOTKEY_ACTIONS  # noqa: E402
from hud_window import HUDWindow  # noqa: E402


class HUDWindowBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.config = AppConfig({"hud_pinned": True})
        self.config.save = mock.Mock()
        hotkeys = mock.Mock()
        hotkeys.apply.return_value = None
        self.patches = [
            mock.patch("hud_window.AppConfig.load", return_value=self.config),
            mock.patch("hud_window.HotkeyManager", return_value=hotkeys),
            mock.patch.object(HUDWindow, "_setup_tray"),
            mock.patch.object(HUDWindow, "_setup_mouse_hook"),
            mock.patch("hud_window.overlay._exclude_from_capture", return_value=True),
        ]
        for patcher in self.patches:
            patcher.start()
        self.window = HUDWindow()

    def tearDown(self) -> None:
        self.window._quitting = True
        self.window.close()
        for patcher in reversed(self.patches):
            patcher.stop()

    def test_hud_is_pinned_by_default(self) -> None:
        self.assertTrue(self.window.pin_button.isChecked())
        self.assertTrue(
            bool(self.window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        )

    def test_background_toggle_button_reflects_config_and_updates_it(self) -> None:
        self.assertTrue(self.window.background_toggle_button.isChecked())
        self.assertTrue(self.config.hud_background_enabled)

        self.window.background_toggle_button.setChecked(False)

        self.assertFalse(self.config.hud_background_enabled)
        self.assertFalse(self.window.output._background_enabled)
        self.config.save.assert_called()

    def test_background_toggle_syncs_open_settings_window(self) -> None:
        self.window._open_settings()

        self.window.background_toggle_button.setChecked(False)

        self.assertFalse(
            self.window._settings_win.background_enabled_check.isChecked()
        )
        self.assertFalse(self.window._settings_win.background_color_btn.isEnabled())

    def test_bar_service_dropdown_updates_translator(self) -> None:
        self.window.service_combo.setCurrentIndex(
            self.window.service_combo.findData("bing")
        )

        self.assertEqual(self.config.translator, "bing")
        self.config.save.assert_called()

    def test_bar_service_dropdown_hides_ai_until_key_is_configured(self) -> None:
        keys = [
            self.window.service_combo.itemData(i)
            for i in range(self.window.service_combo.count())
        ]
        self.assertEqual(keys, ["google", "bing"])

        self.config.llm_api_key = "key"
        self.window.rebuild_service_combo()
        keys = [
            self.window.service_combo.itemData(i)
            for i in range(self.window.service_combo.count())
        ]
        self.assertIn("llm::deepseek-v4-flash", keys)
        self.assertIn("llm::deepseek-v4-pro", keys)
        self.assertNotIn("llm", keys)

    def test_bar_service_dropdown_selects_llm_model(self) -> None:
        self.config.llm_api_key = "key"
        self.window.rebuild_service_combo()
        self.window.service_combo.setCurrentIndex(
            self.window.service_combo.findData("llm::deepseek-v4-pro")
        )

        self.assertEqual(self.config.translator, "llm")
        self.assertEqual(self.config.llm_model, "deepseek-v4-pro")

    def test_bar_exposes_every_translation_action_with_hotkey_tooltip(self) -> None:
        expected = {
            action for _label, action in HOTKEY_ACTIONS if action != "quit"
        }

        self.window.show()
        self.app.processEvents()
        self.assertEqual(set(self.window._action_btns), expected)
        for action in expected:
            tooltip = self.window._action_btns[action].toolTip()
            self.assertIn("Phím tắt:", tooltip)
            self.assertNotIn("Chưa đặt", tooltip)
            button = self.window._action_btns[action]
            right = button.mapTo(self.window._bar, button.rect().topLeft()).x()
            self.assertLessEqual(right + button.width(), self.window._bar.width())

    def test_unpinned_hud_hides_after_window_deactivation(self) -> None:
        self.window.show()
        self.window._set_pinned(False)
        self.assertFalse(
            bool(self.window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        )

        with mock.patch.object(
            self.window, "_active_window_belongs_to_settings", return_value=False
        ):
            QApplication.sendEvent(self.window, QEvent(QEvent.Type.WindowDeactivate))
            self.app.processEvents()

        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.config.hud_pinned)

    def test_pinned_hud_ignores_window_deactivation(self) -> None:
        self.window.show()

        with mock.patch.object(
            self.window, "_active_window_belongs_to_settings", return_value=False
        ):
            QApplication.sendEvent(self.window, QEvent(QEvent.Type.WindowDeactivate))
            self.app.processEvents()

        self.assertTrue(self.window.isVisible())

    def test_show_toolbar_restores_hidden_toolbar_and_hud(self) -> None:
        self.window._bar.hide()
        self.window.hide()

        with mock.patch("hud_window._bring_to_front") as bring_to_front:
            self.window.show_toolbar()

        self.assertFalse(self.window._bar.isHidden())
        bring_to_front.assert_called_once_with(self.window)

    def test_tray_menu_exposes_show_toolbar_recovery(self) -> None:
        labels = [label for label, _callback in self.window._tray_commands()]

        self.assertIn("Hiện thanh công cụ", labels)

    def test_status_is_kept_out_of_translation_content(self) -> None:
        self.window.set_output("Nội dung dịch")
        self.window.set_status("Đã dịch.", "ok")

        self.assertEqual(self.window.output._text, "Nội dung dịch")
        self.assertEqual(self.window._status_text, "Đã dịch.")

    def test_hud_style_preview_applies_font_and_argb_background(self) -> None:
        self.window.preview_hud_text_style(
            "Arial",
            24,
            "#ffffff",
            2,
            "#000000",
            "#80445566",
        )

        self.assertEqual(self.window.output._font_family, "Arial")
        self.assertEqual(self.window.output._font_size, 24)
        self.assertEqual(self.window.output._background_color.alpha(), 128)
        self.assertEqual(self.window.output._background_color.red(), 68)
        self.assertTrue(self.window.output._background_enabled)

    def test_hud_style_preview_can_disable_background(self) -> None:
        self.window.preview_hud_text_style(
            "Arial",
            24,
            "#ffffff",
            2,
            "#000000",
            "#80445566",
            background_enabled=False,
        )

        self.assertFalse(self.window.output._background_enabled)

    def test_hud_style_preview_applies_centered_glow(self) -> None:
        self.window.preview_hud_text_style(
            "Arial",
            18,
            "#ffffff",
            2.0,
            "#101114",
            "#00000000",
            6.0,
            "#804bcbff",
        )

        self.assertEqual(self.window.output._shadow_radius, 6.0)
        self.assertEqual(self.window.output._shadow_color.alpha(), 128)
        offsets = self.window.output._shadow_offsets()
        self.assertEqual(len(offsets), 9)
        self.assertAlmostEqual(sum(x for x, _y in offsets), 0.0)
        self.assertAlmostEqual(sum(y for _x, y in offsets), 0.0)

    def test_hud_style_preview_without_shadow_arguments_disables_shadow(self) -> None:
        self.window.preview_hud_text_style(
            "Arial", 18, "#ffffff", 2.0, "#101114", "#00000000"
        )

        self.assertEqual(self.window.output._shadow_radius, 0.0)

    def test_hud_style_preview_keeps_fractional_border_width(self) -> None:
        self.window.preview_hud_text_style(
            "Yu Gothic",
            16,
            "#000000",
            0.1,
            "#ffffff",
            "#00000000",
        )

        self.assertEqual(self.window.output._border_width, 0.1)

    def test_translation_content_preserves_unicode_scripts(self) -> None:
        content = "Tiếng Việt · 日本語 · 中文 · 한국어 · العربية · 😀"

        self.window.set_output(content)

        self.assertEqual(self.window.output._text, content)

    def test_translated_image_uses_hud_output_and_copy_clear_actions(self) -> None:
        image = QImage(160, 90, QImage.Format.Format_RGB32)
        image.fill(QColor("#e2e8f0"))
        self.window.set_output("Bản dịch cũ")

        self.window.set_output_image(image)

        self.assertEqual(self.window.output.text(), "")
        self.assertEqual(self.window.output.image().size(), image.size())
        self.assertTrue(self.window.copy_button.isEnabled())
        self.assertTrue(self.window.clear_button.isEnabled())
        self.assertEqual(self.window.copy_button.accessibleName(), "Copy ảnh dịch")

        self.window._copy_output()
        clipboard_image = self.app.clipboard().image()
        self.assertEqual(clipboard_image.size(), image.size())

        self.window._clear_output()
        self.assertTrue(self.window.output.image().isNull())
        self.assertFalse(self.window.copy_button.isEnabled())
        self.app.clipboard().clear()


if __name__ == "__main__":
    unittest.main()
