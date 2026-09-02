from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from soniox_realtime import TranscriptBlock  # noqa: E402
from widgets import BarComboBox, ColorButton, HudTextView  # noqa: E402


class BarComboBoxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_popup_opens_below_bar_and_shows_multiple_choices(self) -> None:
        combo = BarComboBox()
        combo.addItems([f"Lựa chọn {index}" for index in range(8)])
        combo.move(100, 100)
        combo.show()
        self.app.processEvents()

        combo.showPopup()
        self.app.processEvents()
        popup = combo.view().window()
        combo_bottom = combo.mapToGlobal(combo.rect().bottomLeft()).y()
        row_height = combo.view().sizeHintForRow(0)

        self.assertGreater(popup.y(), combo_bottom)
        self.assertGreaterEqual(popup.height(), row_height * 8 + 24)

        combo.hidePopup()
        combo.close()


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


class HudTranscriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.blocks = (
            TranscriptBlock("speech", "こんにちは。", "ja", None, True),
            TranscriptBlock("translation", "Xin chào.", "vi", None, True),
        )

    def test_bilingual_plain_text_keeps_original_above_translation(self) -> None:
        view = HudTextView()
        view.set_transcript(self.blocks, display_mode="bilingual", alignment="center")

        self.assertEqual(view.text(), "こんにちは。\nXin chào.")

    def test_translation_only_hides_original_and_applies_right_alignment(self) -> None:
        view = HudTextView()
        view.set_transcript(self.blocks, display_mode="translation", alignment="right")
        document = view._transcript_document(  # noqa: SLF001
            QFont("Arial", 20), QColor("#ffffff"), 400, outline=False
        )

        self.assertEqual(view.text(), "Xin chào.")
        self.assertEqual(document.begin().blockFormat().alignment(), Qt.AlignRight)

    def test_original_typography_is_smaller_than_translation(self) -> None:
        view = HudTextView()
        view.set_transcript(self.blocks, display_mode="bilingual", alignment="left")
        document = view._transcript_document(  # noqa: SLF001
            QFont("Arial", 20), QColor("#ffffff"), 400, outline=False
        )
        original = document.begin()
        translation = original.next()

        def largest_font_size(block) -> float:
            iterator = block.begin()
            sizes: list[float] = []
            while not iterator.atEnd():
                sizes.append(iterator.fragment().charFormat().fontPointSize())
                iterator += 1
            return max(sizes)

        self.assertLess(largest_font_size(original), largest_font_size(translation))


if __name__ == "__main__":
    unittest.main()
