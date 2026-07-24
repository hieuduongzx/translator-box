from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from translation_workflows import TranslationWorkflowController  # noqa: E402


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
            translator="google",
            llm_endpoint="http://example.test/v1",
            llm_api_key="test-key",
            llm_model="test-model",
            live_interval_ms=900,
        )
        self.bridge = SimpleNamespace(run=ImmediateSignal())
        self.statuses = []
        self.busy_values = []
        self.output = ""
        self.output_history = []
        self.ensure_visible_calls = 0

    def set_status(self, text, state="ready"):
        self.statuses.append((text, state))

    def set_busy(self, busy):
        self.busy_values.append(busy)

    def set_output(self, text):
        self.output = text
        self.output_history.append(text)

    def ensure_visible(self):
        self.ensure_visible_calls += 1

    def set_live_action_checked(self, _action, _checked):
        pass

    def quit_app(self):
        pass


class TranslationWorkflowTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
