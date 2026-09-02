from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from translation_workflows import (  # noqa: E402
    LiveSession,
    TranslationWorkflowController,
)


class ImmediateSignal:
    def emit(self, callback) -> None:
        callback()


class FakeHud:
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            ocr_language="eng",
            ocr_engine="rapidocr",
            ocr_model="ppocrv5_mobile",
            ocr_backend="cuda",
            ocr_acceleration=False,
            target_language="vi",
            replace_target_language="en",
            translator="google",
            llm_endpoint="http://example.test/v1",
            llm_api_key="test-key",
            llm_model="test-model",
            live_interval_ms=900,
            live_focus_app_id="",
            live_focus_app_label="",
        )
        self.config.resolve_llm = lambda: (
            "google",
            self.config.llm_endpoint,
            self.config.llm_api_key,
            self.config.llm_model,
        )
        self.config.save = mock.Mock()
        self.bridge = SimpleNamespace(run=ImmediateSignal())
        self.statuses = []
        self.busy_values = []
        self.output = ""
        self.output_history = []
        self.output_image = None
        self.ensure_visible_calls = 0

    def set_status(self, text, state="ready"):
        self.statuses.append((text, state))

    def set_busy(self, busy):
        self.busy_values.append(busy)

    def set_output(self, text):
        self.output = text
        self.output_history.append(text)

    def set_output_image(self, image):
        self.output_image = image.copy()

    def ensure_visible(self):
        self.ensure_visible_calls += 1

    def set_live_action_checked(self, _action, _checked):
        pass

    def quit_app(self):
        pass


class TranslationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_unknown_action_is_ignored(self) -> None:
        hud = FakeHud()
        controller = TranslationWorkflowController(hud)

        controller.handle_action("unknown")

        self.assertFalse(controller.busy)
        self.assertEqual(hud.statuses, [])

    def test_ocr_options_force_cpu_when_acceleration_is_off(self) -> None:
        hud = FakeHud()
        controller = TranslationWorkflowController(hud)

        options = controller._options()

        self.assertEqual(options.model, "ppocrv5_mobile")
        self.assertEqual(options.backend, "cpu")

    def test_ocr_options_use_selected_backend_when_acceleration_is_on(self) -> None:
        hud = FakeHud()
        hud.config.ocr_acceleration = True

        options = TranslationWorkflowController(hud)._options()

        self.assertEqual(options.backend, "cuda")

    def test_selected_text_uses_snapshot_and_applies_result(self) -> None:
        hud = FakeHud()
        controller = TranslationWorkflowController(hud)

        with (
            mock.patch(
                "translation_workflows.services.copy_selected_text",
                return_value="Hello",
            ),
            mock.patch(
                "translation_workflows.services.translate",
                return_value="Xin chào",
            ) as translate,
            mock.patch("translation_workflows.threading.Thread") as thread_type,
        ):
            thread_type.return_value.start.side_effect = lambda: (
                thread_type.call_args.kwargs["target"]()
            )
            controller.handle_action("selected_text")

        translate.assert_called_once_with(
            "Hello",
            "vi",
            "google",
            llm_endpoint="http://example.test/v1",
            llm_api_key="test-key",
            llm_model="test-model",
        )
        self.assertEqual(hud.output, "Xin chào")
        self.assertEqual(hud.output_history, ["Xin chào"])
        self.assertEqual(hud.busy_values, [True, False])
        self.assertGreaterEqual(hud.ensure_visible_calls, 2)

    def test_clipboard_image_is_saved_as_png(self) -> None:
        controller = TranslationWorkflowController(FakeHud())
        image = QImage(8, 5, QImage.Format.Format_RGB32)
        image.fill(QColor("#2f81f7"))
        self.app.clipboard().setImage(image)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clipboard.png"
            controller._save_clipboard_image(str(path))
            saved = QImage(str(path))

        self.assertFalse(saved.isNull())
        self.assertEqual(saved.size(), image.size())
        self.assertEqual(saved.pixelColor(0, 0), QColor("#2f81f7"))
        self.app.clipboard().clear()

    def test_clipboard_image_replaces_text_inside_hud(self) -> None:
        hud = FakeHud()
        controller = TranslationWorkflowController(hud)
        regions = [
            SimpleNamespace(text="Source", bbox=(4, 4, 100, 28)),
        ]
        visual = SimpleNamespace(
            bg=(20, 24, 30),
            fg=(240, 240, 240),
            rect=(2, 2, 104, 30),
            patch_rgb=None,
            patch_size=None,
            ink_rect=(4, 4, 100, 28),
            stroke_thickness=1.0,
        )
        source_image = mock.Mock()
        source_image.isNull.return_value = False
        translated_image = QImage(120, 40, QImage.Format.Format_RGB32)
        translated_image.fill(QColor("#e2e8f0"))

        with (
            mock.patch.object(controller, "_save_clipboard_image"),
            mock.patch.object(
                controller, "_new_temp_image", return_value="clipboard.png"
            ),
            mock.patch.object(controller, "_remove_temp_image") as remove_temp_image,
            mock.patch(
                "translation_workflows.services.ocr_layout", return_value=regions
            ),
            mock.patch(
                "translation_workflows.services.translate_regions",
                return_value=["Bản dịch"],
            ),
            mock.patch(
                "translation_workflows.services.reconstruct_layout",
                return_value=((120, 40), [visual]),
            ),
            mock.patch("translation_workflows.QImage", return_value=source_image),
            mock.patch(
                "translation_workflows.overlay.render_translated_image",
                return_value=translated_image,
            ) as render_image,
            mock.patch("translation_workflows.threading.Thread") as thread_type,
        ):
            thread_type.return_value.start.side_effect = lambda: (
                thread_type.call_args.kwargs["target"]()
            )
            controller.handle_action("clipboard_image_replace")

        shown_source, shown_regions, shown_size = render_image.call_args.args
        self.assertIs(shown_source, source_image)
        self.assertEqual(shown_regions[0].text, "Bản dịch")
        self.assertEqual(shown_size, (120, 40))
        self.assertIsNotNone(hud.output_image)
        self.assertEqual(hud.output_image.size(), translated_image.size())
        self.assertEqual(hud.output_history, [])
        self.assertEqual(hud.busy_values, [True, False])
        self.assertEqual(
            hud.statuses[-1],
            ("Ảnh dịch đang hiện trong khung và đã copy vào clipboard.", "ok"),
        )
        remove_temp_image.assert_called_once_with("clipboard.png")

    def test_clipboard_image_ocr_translates_lines_into_hud(self) -> None:
        hud = FakeHud()
        controller = TranslationWorkflowController(hud)
        regions = [
            SimpleNamespace(text="First line", bbox=(0, 0, 120, 20)),
            SimpleNamespace(text="Second line", bbox=(0, 24, 120, 44)),
        ]

        with (
            mock.patch.object(
                controller, "_save_clipboard_image"
            ) as save_clipboard_image,
            mock.patch.object(
                controller, "_new_temp_image", return_value="clipboard.png"
            ),
            mock.patch.object(controller, "_remove_temp_image") as remove_temp_image,
            mock.patch(
                "translation_workflows.services.ocr_layout", return_value=regions
            ),
            mock.patch(
                "translation_workflows.services.translate_regions",
                return_value=["Dòng một và dòng hai"],
            ) as translate_regions,
            mock.patch("translation_workflows.threading.Thread") as thread_type,
        ):
            thread_type.return_value.start.side_effect = lambda: (
                thread_type.call_args.kwargs["target"]()
            )
            controller.handle_action("clipboard_image_to_text")

        save_clipboard_image.assert_called_once_with("clipboard.png")
        translated_regions = translate_regions.call_args.args[0]
        self.assertEqual(
            [region.text for region in translated_regions],
            ["First line Second line"],
        )
        self.assertEqual(hud.output, "Dòng một và dòng hai")
        self.assertEqual(hud.busy_values, [True, False])
        self.assertGreaterEqual(hud.ensure_visible_calls, 2)
        remove_temp_image.assert_called_once_with("clipboard.png")

    def test_clipboard_image_action_reports_missing_image(self) -> None:
        hud = FakeHud()
        controller = TranslationWorkflowController(hud)

        with (
            mock.patch.object(
                controller,
                "_save_clipboard_image",
                side_effect=RuntimeError("Clipboard không có ảnh."),
            ),
            mock.patch.object(
                controller, "_new_temp_image", return_value="clipboard.png"
            ),
            mock.patch.object(controller, "_remove_temp_image") as remove_temp_image,
            mock.patch("translation_workflows.threading.Thread") as thread_type,
        ):
            controller.handle_action("clipboard_image_replace")

        thread_type.assert_not_called()
        remove_temp_image.assert_called_once_with("clipboard.png")
        self.assertEqual(hud.output, "⚠ Clipboard không có ảnh.")
        self.assertEqual(hud.busy_values, [True, False])

    def test_region_capture_preserves_detected_lines_in_hud(self) -> None:
        hud = FakeHud()
        controller = TranslationWorkflowController(hud)
        regions = [
            SimpleNamespace(text="First line", bbox=(0, 0, 120, 20)),
            SimpleNamespace(text="Second line", bbox=(0, 24, 120, 44)),
        ]

        with (
            mock.patch("translation_workflows.services.capture"),
            mock.patch(
                "translation_workflows.services.ocr_layout", return_value=regions
            ),
            mock.patch(
                "translation_workflows.services.translate_regions",
                return_value=["Dòng một và dòng hai"],
            ) as translate_regions,
            mock.patch("translation_workflows.time.sleep"),
            mock.patch.object(
                controller, "_new_temp_image", return_value="capture.png"
            ),
            mock.patch.object(controller, "_remove_temp_image"),
            mock.patch("translation_workflows.threading.Thread") as thread_type,
        ):
            thread_type.return_value.start.side_effect = lambda: (
                thread_type.call_args.kwargs["target"]()
            )
            controller._capture_to_frame((0, 0, 120, 48), [])

        translated_regions = translate_regions.call_args.args[0]
        self.assertEqual(
            [region.text for region in translated_regions],
            ["First line Second line"],
        )
        self.assertEqual(hud.output, "Dòng một và dòng hai")

    def test_selected_text_replace_pastes_translation_and_keeps_focus(self) -> None:
        hud = FakeHud()
        controller = TranslationWorkflowController(hud)

        with (
            mock.patch(
                "translation_workflows.services.read_clipboard",
                return_value="orig-clip",
            ),
            mock.patch(
                "translation_workflows.services.copy_selected_text",
                return_value="Xin chào",
            ),
            mock.patch(
                "translation_workflows.services.translate",
                return_value="Hello",
            ) as translate,
            mock.patch("translation_workflows.services.paste_replacement") as paste,
            mock.patch("translation_workflows.threading.Thread") as thread_type,
        ):
            thread_type.return_value.start.side_effect = lambda: (
                thread_type.call_args.kwargs["target"]()
            )
            controller.handle_action("selected_text_replace")

        # Dùng ngôn ngữ đích RIÊNG của chức năng thay thế ("en"), không phải "vi".
        self.assertEqual(translate.call_args.args[1], "en")
        # Dán bản dịch đè vùng chọn và khôi phục clipboard gốc.
        paste.assert_called_once_with("Hello", restore="orig-clip")
        self.assertEqual(hud.busy_values, [True, False])
        # KHÔNG đổ bản dịch vào khung HUD (đã thay tại chỗ trong app đích).
        self.assertEqual(hud.output_history, [])
        # KHÔNG kéo HUD lên (giữ focus ở app đích để Ctrl+V dán đúng chỗ).
        self.assertEqual(hud.ensure_visible_calls, 0)

    def test_live_focus_selection_persists_and_updates_running_session(self) -> None:
        hud = FakeHud()
        controller = TranslationWorkflowController(hud)
        session = LiveSession(
            (0, 0, 100, 50),
            "frame",
            controller._options(),
            0.9,
            "region_to_live_frame",
        )
        controller._live = session

        controller.set_live_focus_application("C:/Apps/Reader.exe", "Reader")

        self.assertEqual(hud.config.live_focus_app_id, "c:/apps/reader.exe")
        self.assertEqual(hud.config.live_focus_app_label, "Reader")
        self.assertEqual(session.focus_application_id, "c:/apps/reader.exe")
        hud.config.save.assert_called_once_with()

    def test_live_focus_filter_skips_capture_while_other_app_is_focused(
        self,
    ) -> None:
        hud = FakeHud()
        controller = TranslationWorkflowController(hud)
        session = LiveSession(
            (0, 0, 100, 50),
            "frame",
            controller._options(),
            0.05,
            "region_to_live_frame",
            "c:/apps/reader.exe",
            "Reader",
        )
        controller._live = session

        def lose_focus() -> str:
            session.stop_event.set()
            return "c:/apps/browser.exe"

        with (
            mock.patch(
                "translation_workflows.foreground_application_id",
                side_effect=lose_focus,
            ),
            mock.patch("translation_workflows.services.capture") as capture,
            mock.patch.object(controller, "_new_temp_image", return_value="live.png"),
            mock.patch.object(controller, "_remove_temp_image"),
        ):
            controller._live_loop(session)

        capture.assert_not_called()
        self.assertIn("TẠM DỪNG", hud.statuses[-1][0])

    def test_live_result_is_applied_only_while_selected_app_is_focused(
        self,
    ) -> None:
        hud = FakeHud()
        controller = TranslationWorkflowController(hud)
        session = LiveSession(
            (0, 0, 100, 50),
            "frame",
            controller._options(),
            0.9,
            "region_to_live_frame",
            "c:/apps/reader.exe",
            "Reader",
        )
        controller._live = session

        with mock.patch(
            "translation_workflows.foreground_application_id",
            return_value="c:/apps/browser.exe",
        ):
            controller._live_apply_frame(session.token, "Không áp dụng")
        self.assertEqual(hud.output, "")

        with mock.patch(
            "translation_workflows.foreground_application_id",
            return_value="c:/apps/reader.exe",
        ):
            controller._live_apply_frame(session.token, "Đã áp dụng")
        self.assertEqual(hud.output, "Đã áp dụng")

    def test_global_right_click_closes_only_transient_overlays(self) -> None:
        controller = TranslationWorkflowController(FakeHud())

        with mock.patch(
            "translation_workflows.overlay.close_all_translations"
        ) as close:
            controller.dismiss_transient_overlays()

        close.assert_called_once_with(include_live=False)


if __name__ == "__main__":
    unittest.main()
