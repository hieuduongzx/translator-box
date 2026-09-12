from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import QEvent, QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from config import AppConfig  # noqa: E402
from constants import HOTKEY_ACTIONS  # noqa: E402
from desktop_apps import DesktopApplication  # noqa: E402
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
            mock.patch("hud_window.UpdateController", return_value=mock.Mock()),
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

        self.assertFalse(self.window._settings_win.background_enabled_check.isChecked())
        self.assertFalse(self.window._settings_win.background_color_btn.isEnabled())

    def test_transparent_button_forces_background_off_regardless_of_config(self) -> None:
        self.assertTrue(self.window.output._background_enabled)

        self.window.transparent_button.setChecked(True)

        self.assertTrue(self.config.hud_frame_transparent)
        self.assertFalse(self.window.output._background_enabled)
        self.config.save.assert_called()

        self.window.transparent_button.setChecked(False)

        self.assertFalse(self.config.hud_frame_transparent)
        self.assertTrue(self.window.output._background_enabled)

    def test_clipboard_change_translates_when_auto_enabled(self) -> None:
        self.app.clipboard().setText("Hello")
        self.config.auto_translate_clipboard = True
        self.window._clipboard_watch_text = ""

        with mock.patch.object(
            self.window.workflow, "translate_clipboard_text"
        ) as translate:
            self.window._on_clipboard_changed()

        translate.assert_called_once_with("Hello")
        self.config.auto_translate_clipboard = False
        self.app.clipboard().clear()

    def test_clipboard_change_is_ignored_when_auto_disabled(self) -> None:
        self.app.clipboard().setText("Hello")
        self.config.auto_translate_clipboard = False
        self.window._clipboard_watch_text = ""

        with mock.patch.object(
            self.window.workflow, "translate_clipboard_text"
        ) as translate:
            self.window._on_clipboard_changed()

        translate.assert_not_called()
        self.app.clipboard().clear()

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

    def test_audio_controls_live_in_one_bar_menu(self) -> None:
        self.assertEqual(self.window.audio_button.text(), "Âm thanh")
        self.assertFalse(self.window.audio_button.icon().isNull())
        self.assertEqual(self.window.audio_button.objectName(), "barAction")
        self.assertEqual(
            set(self.window._audio_option_actions),
            {
                "soniox_audio_source",
                "soniox_target_language",
                "soniox_display_mode",
                "soniox_text_alignment",
            },
        )
        self.assertEqual(
            self.window.audio_toggle_action.text(), "Bắt đầu dịch audio"
        )
        checked = {
            setting: [value for value, action in options.items() if action.isChecked()]
            for setting, options in self.window._audio_option_actions.items()
        }
        self.assertEqual(checked["soniox_audio_source"], ["system"])
        self.assertEqual(checked["soniox_display_mode"], ["bilingual"])
        self.assertEqual(checked["soniox_text_alignment"], ["center"])

    def test_audio_menu_options_update_shared_soniox_config(self) -> None:
        options = self.window._audio_option_actions

        options["soniox_audio_source"]["microphone"].trigger()
        options["soniox_display_mode"]["translation"].trigger()
        options["soniox_target_language"]["ja"].trigger()
        options["soniox_text_alignment"]["right"].trigger()

        self.assertEqual(self.config.soniox_audio_source, "microphone")
        self.assertEqual(self.config.soniox_display_mode, "translation")
        self.assertEqual(self.config.soniox_target_language, "ja")
        self.assertEqual(self.config.soniox_text_alignment, "right")
        self.assertGreaterEqual(self.config.save.call_count, 4)

        # Chọn lại đúng giá trị hiện tại không được ghi đĩa thêm lần nữa.
        saves = self.config.save.call_count
        options["soniox_text_alignment"]["right"].trigger()
        self.assertEqual(self.config.save.call_count, saves)

    def test_audio_menu_reflects_config_changed_elsewhere(self) -> None:
        self.config.soniox_audio_source = "microphone"
        self.config.soniox_target_language = "ko"

        self.window.sync_audio_controls()

        options = self.window._audio_option_actions
        self.assertTrue(options["soniox_audio_source"]["microphone"].isChecked())
        self.assertFalse(options["soniox_audio_source"]["system"].isChecked())
        self.assertTrue(options["soniox_target_language"]["ko"].isChecked())

    def test_active_audio_marks_bar_button_and_updates_toggle_label(self) -> None:
        self.window.audio_session._source = "system"
        self.window.audio_session._state = "listening"

        self.window._on_audio_state_changed("listening")

        self.assertTrue(self.window.audio_button.property("live"))
        self.assertEqual(self.window.audio_toggle_action.text(), "Dừng dịch audio")
        self.assertTrue(self.window.audio_button.isEnabled())

        self.window.audio_session._state = "idle"
        self.window._on_audio_state_changed("idle")

        self.assertFalse(self.window.audio_button.property("live"))
        self.assertEqual(
            self.window.audio_toggle_action.text(), "Bắt đầu dịch audio"
        )

    def test_drag_position_snaps_to_each_edge_of_pointer_screen(self) -> None:
        screen = mock.Mock()
        screen.availableGeometry.return_value = QRect(-1280, 0, 1280, 1024)
        pointer = QPoint(-900, 300)
        self.window.resize(600, 200)

        with mock.patch(
            "hud_window.QGuiApplication.screenAt", return_value=screen
        ) as screen_at:
            top_left = self.window._snapped_position(QPoint(-1271, 9), pointer)
            bottom_right = self.window._snapped_position(QPoint(-612, 813), pointer)
            free = self.window._snapped_position(QPoint(-1240, 40), pointer)

        self.assertEqual(top_left, QPoint(-1280, 0))
        self.assertEqual(bottom_right, QPoint(-600, 824))
        self.assertEqual(free, QPoint(-1240, 40))
        screen_at.assert_any_call(pointer)

    def test_bar_groups_commands_and_compacts_low_priority_controls(
        self,
    ) -> None:
        group_buttons = self.window._action_group_buttons
        self.assertEqual(list(group_buttons), ["screen", "clipboard", "text"])
        self.assertEqual(
            [button.text() for button in group_buttons.values()],
            ["Màn hình", "Ảnh", "Văn bản"],
        )
        self.assertTrue(
            all(
                button.objectName() == "barAction"
                for button in group_buttons.values()
            )
        )

        self.window.show()
        self.app.processEvents()

        self.window.resize(640, 200)
        self.app.processEvents()
        self.assertTrue(self.window.service_combo.isHidden())
        self.assertTrue(self.window.copy_button.isHidden())
        self.assertTrue(self.window.clear_button.isHidden())
        self.assertTrue(self.window.status_strip.isHidden())
        self.assertTrue(self.window.pin_button.isHidden())
        self.assertTrue(all(not button.isHidden() for button in group_buttons.values()))
        self.assertFalse(self.window.audio_button.isHidden())

        # Hẹp nhất: nhóm lệnh rút về chỉ còn icon, tooltip vẫn mô tả đủ.
        self.window.resize(self.window.minimumWidth(), 200)
        self.app.processEvents()
        self.assertEqual(
            [button.text() for button in group_buttons.values()], ["", "", ""]
        )
        self.assertEqual(self.window.audio_button.text(), "")
        self.assertTrue(
            all(button.toolTip() for button in group_buttons.values())
        )

        self.window.resize(980, 200)
        self.app.processEvents()
        self.assertFalse(self.window.service_combo.isHidden())
        self.assertFalse(self.window.copy_button.isHidden())
        self.assertFalse(self.window.clear_button.isHidden())
        self.assertFalse(self.window.status_strip.isHidden())
        self.assertFalse(self.window.pin_button.isHidden())
        self.assertEqual(
            [button.text() for button in group_buttons.values()],
            ["Màn hình", "Ảnh", "Văn bản"],
        )

    def test_bar_exposes_every_translation_action_inside_group_menus(self) -> None:
        expected = {action for _label, action in HOTKEY_ACTIONS if action != "quit"}

        self.window.show()
        self.app.processEvents()
        self.assertEqual(set(self.window._translation_actions), expected)
        for action in expected:
            menu_action = self.window._translation_actions[action]
            self.assertIn("Phím tắt:", menu_action.toolTip())
            self.assertNotIn("Chưa đặt", menu_action.text())
        for button in self.window._action_group_buttons.values():
            right = button.mapTo(self.window._bar, button.rect().topLeft()).x()
            self.assertLessEqual(right + button.width(), self.window._bar.width())

    def test_group_toggle_opens_menu_upward_and_dispatches_action(self) -> None:
        self.window.move(80, 360)
        self.window.show()
        self.app.processEvents()
        button = self.window._action_group_buttons["screen"]
        menu = self.window._action_group_menus["screen"]

        button.click()
        self.app.processEvents()

        button_top = button.mapToGlobal(button.rect().topLeft()).y()
        self.assertTrue(button.isChecked())
        self.assertTrue(menu.isVisible())
        self.assertLess(menu.geometry().bottom(), button_top)

        with mock.patch.object(self.window.workflow, "handle_action") as handle:
            self.window._translation_actions["region_to_overlay"].trigger()
        handle.assert_called_once_with("region_to_overlay")

        self.window.set_live_action_checked("region_to_live", True)
        self.assertTrue(self.window._translation_actions["region_to_live"].isChecked())
        self.assertTrue(button.property("live"))
        self.window.set_live_action_checked("region_to_live", False)
        self.assertFalse(button.property("live"))

        menu.hide()
        self.app.processEvents()
        self.assertFalse(button.isChecked())

    def test_screen_menu_selects_application_focus_filter(self) -> None:
        application = DesktopApplication(
            "c:/apps/reader.exe", "Reader", "Tài liệu đang đọc"
        )
        with mock.patch(
            "hud_window.list_desktop_applications", return_value=[application]
        ):
            self.window._populate_application_menu()

        screen_menu = self.window._action_group_menus["screen"]
        self.assertIn(self.window._application_menu.menuAction(), screen_menu.actions())
        self.assertEqual(self.window._application_menu.title(), "Chỉ dịch khi focus")
        actions = [
            action
            for action in self.window._application_menu.actions()
            if not action.isSeparator()
        ]
        self.assertEqual(
            [action.text() for action in actions],
            ["Mọi ứng dụng", "Reader"],
        )

        actions[1].trigger()
        self.assertEqual(self.config.live_focus_app_id, "c:/apps/reader.exe")
        self.assertEqual(self.config.live_focus_app_label, "Reader")

        with mock.patch("hud_window.list_desktop_applications", return_value=[]):
            self.window._populate_application_menu()
        self.window._application_menu.actions()[0].trigger()
        self.assertEqual(self.config.live_focus_app_id, "")

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
        self.assertEqual(self.window.status_strip._dot.property("state"), "ok")

    def test_missing_dependency_is_reported_at_startup(self) -> None:
        """Thiếu gói import lười phải hiện ngay ở trạng thái, không đợi phím tắt."""
        with mock.patch(
            "hud_window.services.missing_runtime_packages",
            return_value="Thiếu thư viện 'pyperclip'.",
        ):
            window = HUDWindow()

        try:
            self.assertEqual(window._status_state, "error")
            self.assertIn("pyperclip", window._status_text)
            self.assertEqual(window.status_strip._dot.property("state"), "error")
        finally:
            window._quitting = True
            window.close()

    def test_repeated_status_updates_are_ignored(self) -> None:
        """Live gọi lại đúng chuỗi này mỗi frame; không được làm gì thêm."""
        self.window.set_status("● Đang dịch trực tiếp.", "busy")
        strip = self.window.status_strip
        before = strip._label.text()

        with mock.patch.object(strip, "set_state") as set_state:
            self.window.set_status("● Đang dịch trực tiếp.", "busy")

        set_state.assert_not_called()
        self.assertEqual(strip._label.text(), before)

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
