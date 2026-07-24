from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from PySide6.QtWidgets import QApplication  # noqa: E402

from widgets import ColorButton  # noqa: E402


class ColorButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_alpha_color_keeps_argb_value(self) -> None:
        button = ColorButton("#80445566", allow_alpha=True)

        self.assertEqual(button.color_value(), "#80445566")
        self.assertIn("50%", button.text())

    def test_fully_transparent_color_has_clear_label(self) -> None:
        button = ColorButton("#00000000", allow_alpha=True)

        self.assertEqual(button.color_value(), "#00000000")
        self.assertEqual(button.text(), "Trong suốt")


if __name__ == "__main__":
    unittest.main()
