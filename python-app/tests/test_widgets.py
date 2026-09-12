from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QTextCursor  # noqa: E402
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


class HudTextOutlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _first_format(document):
        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        return cursor.charFormat()

    def test_outline_is_a_separate_layer_below_a_clean_fill(self) -> None:
        """Viền phải ở lớp riêng để nét viền không ăn vào thân chữ (chữ khỏi 'vỡ')."""
        view = HudTextView()
        view.resize(400, 60)
        view.apply_style(
            "Segoe UI",
            24,
            "#fafafa",
            3.0,
            "#09090b",
            "#00000000",
            0.0,
            "#00000000",
            False,
        )
        view.setText("Xin chào")

        main, _shadow, outline = view._documents(  # noqa: SLF001
            QFont("Segoe UI", 24), 380, with_shadow=False
        )

        main_format = self._first_format(main)
        self.assertEqual(main_format.textOutline().style(), Qt.NoPen)
        self.assertEqual(main_format.foreground().color().alpha(), 255)

        self.assertIsNotNone(outline)
        outline_format = self._first_format(outline)
        self.assertNotEqual(outline_format.textOutline().style(), Qt.NoPen)
        self.assertEqual(outline_format.textOutline().widthF(), 3.0)
        self.assertEqual(outline_format.foreground().color().alpha(), 0)

    def test_no_outline_layer_when_border_disabled(self) -> None:
        view = HudTextView()
        view.apply_style(
            "Segoe UI",
            24,
            "#fafafa",
            0.0,
            "#09090b",
            "#00000000",
            0.0,
            "#00000000",
            False,
        )
        view.setText("Xin chào")

        _main, _shadow, outline = view._documents(  # noqa: SLF001
            QFont("Segoe UI", 24), 380, with_shadow=False
        )

        self.assertIsNone(outline)


if __name__ == "__main__":
    unittest.main()
