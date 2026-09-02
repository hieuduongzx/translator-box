from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontMetricsF, QImage
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import overlay  # noqa: E402


class TranslationOverlayPaintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_only_text_regions_are_painted(self) -> None:
        background = (37, 55, 74)
        widget = overlay.TranslationOverlay(
            (0, 0, 160, 48),
            [
                overlay.OverlayRegion(
                    (10, 5, 70, 19),
                    "Bản dịch",
                    background,
                    (242, 242, 242),
                )
            ],
            (80, 24),
        )
        widget.show()
        self.app.processEvents()
        image = widget.grab().toImage()

        # Ngoài vùng chữ: hoàn toàn trong suốt (chỉ vẽ đúng ô chữ, không phủ nền).
        outside = image.pixelColor(0, widget.height() - 1)
        self.assertEqual(outside.alpha(), 0)

        # Trong ô: có nền bg đục được vẽ (quét tìm ít nhất một pixel bằng bg,
        # bền vững trước thay đổi cỡ/hướng chữ).
        rect = widget._paint_regions[0].patch
        found = False
        for y in range(rect.top() + 1, rect.bottom() - 1):
            for x in range(rect.left() + 1, rect.right() - 1):
                color = image.pixelColor(x, y)
                if (color.red(), color.green(), color.blue()) == background and (
                    color.alpha() == 255
                ):
                    found = True
                    break
            if found:
                break
        self.assertTrue(found, "Không thấy pixel nền bg trong ô chữ")

        widget.close()

    def test_translated_image_replaces_only_detected_text_regions(self) -> None:
        source_color = QColor("#203040")
        replacement_color = (226, 232, 240)
        source = QImage(80, 30, QImage.Format.Format_RGB32)
        source.fill(source_color)
        region = overlay.OverlayRegion(
            (10, 5, 70, 25),
            "Translated",
            replacement_color,
            (20, 24, 30),
        )

        result = overlay.render_translated_image(source, [region], (80, 30))

        self.assertEqual(result.size(), source.size())
        self.assertEqual(result.pixelColor(0, 29), source_color)
        compositor = overlay.TranslationOverlay((0, 0, 80, 30), [region], (80, 30))
        patch = compositor._paint_regions[0].patch
        compositor.close()
        changed = any(
            result.pixelColor(x, y) != source_color
            for y in range(patch.top(), patch.bottom() + 1)
            for x in range(patch.left(), patch.right() + 1)
        )
        self.assertTrue(changed)

    @staticmethod
    def _region(
        text: str, bbox, ink=None, thickness=0.0, source_lines=1
    ) -> overlay.OverlayRegion:
        return overlay.OverlayRegion(
            bbox,
            text,
            (240, 240, 240),
            (20, 20, 20),
            bbox,
            None,
            None,
            ink,
            thickness,
            source_lines,
        )

    def test_font_size_follows_original_ink_not_loose_ocr_box(self) -> None:
        """Hộp OCR lỏng hơn nét chữ; bám hộp sẽ vẽ chữ to hơn bản gốc."""
        loose_box = (10, 4, 200, 40)  # cao 36
        ink = (10, 12, 200, 32)  # ink thật chỉ cao 20
        with_ink = overlay.TranslationOverlay(
            (0, 0, 260, 60), [self._region("Bản dịch", loose_box, ink)], (260, 60)
        )
        without_ink = overlay.TranslationOverlay(
            (0, 0, 260, 60), [self._region("Bản dịch", loose_box)], (260, 60)
        )

        sized_by_ink = with_ink._paint_regions[0].font.pixelSize()
        sized_by_box = without_ink._paint_regions[0].font.pixelSize()
        self.assertLess(sized_by_ink, sized_by_box)
        self.assertLessEqual(sized_by_ink, ink[3] - ink[1] + 2)
        with_ink.close()
        without_ink.close()

    def test_lines_of_one_block_share_font_size(self) -> None:
        """Dòng toàn chữ thấp (ink nhỏ) vẫn lấy cỡ chữ của cả khối.

        Ô rất rộng để phép co theo bề rộng không xen vào phép đo này.
        """
        regions = [
            self._region("Dòng có chữ hoa", (10, 10, 1500, 30), (10, 12, 1500, 28)),
            self._region("dòng thấp", (10, 34, 1500, 54), (10, 40, 1500, 50)),
            self._region("Dòng khác", (10, 58, 1500, 78), (10, 60, 1500, 76)),
        ]
        widget = overlay.TranslationOverlay((0, 0, 1600, 100), regions, (1600, 100))

        sizes = {line.font.pixelSize() for line in widget._paint_regions}
        self.assertEqual(len(sizes), 1)
        widget.close()

    def test_block_keeps_one_size_even_when_line_lengths_differ_a_lot(self) -> None:
        """Dòng dịch dài gấp đôi không được làm mỗi dòng một cỡ.

        Trước đây mỗi dòng tự co theo bề rộng của riêng nó → khối chữ to nhỏ so le.
        """
        regions = [
            self._region("Ngắn", (10, 10, 340, 32), (10, 12, 340, 30)),
            self._region(
                "Dòng dịch dài hơn hẳn bản gốc " * 3,
                (10, 36, 340, 58),
                (10, 38, 340, 56),
            ),
            self._region("Vừa phải thôi", (10, 62, 340, 84), (10, 64, 340, 82)),
        ]
        widget = overlay.TranslationOverlay((0, 0, 360, 100), regions, (360, 100))

        sizes = {line.font.pixelSize() for line in widget._paint_regions}
        self.assertEqual(len(sizes), 1, f"khối chữ bị nhiều cỡ: {sizes}")
        widget.close()

    def test_window_stays_inside_selected_region(self) -> None:
        region = self._region("Bản dịch", (10, 10, 200, 40), (10, 12, 200, 38))
        widget = overlay.TranslationOverlay((0, 0, 220, 60), [region], (220, 60))

        self.assertEqual(widget.width(), 220)
        self.assertEqual(widget.height(), 60)
        text_rect = widget._line_text_rect(widget._paint_regions[0])
        self.assertLessEqual(text_rect.right(), widget.rect().right())
        self.assertLessEqual(text_rect.bottom(), widget.rect().bottom())
        widget.close()

    def test_long_translation_is_shrunk_towards_original_width(self) -> None:
        box = (10, 10, 120, 30)
        ink = (10, 12, 120, 28)
        short = overlay.TranslationOverlay(
            (0, 0, 400, 60), [self._region("Ngắn", box, ink)], (400, 60)
        )
        long_text = overlay.TranslationOverlay(
            (0, 0, 400, 60),
            [self._region("Bản dịch dài hơn hẳn ô gốc " * 3, box, ink)],
            (400, 60),
        )

        self.assertLess(
            long_text._paint_regions[0].font.pixelSize(),
            short._paint_regions[0].font.pixelSize(),
        )
        short.close()
        long_text.close()

    def test_manga_block_wraps_inside_original_speech_bubble(self) -> None:
        widget = overlay.TranslationOverlay(
            (0, 0, 240, 160),
            [
                self._region(
                    "Đây là bản dịch dài cần xuống nhiều dòng",
                    (60, 30, 180, 130),
                    (65, 35, 175, 125),
                    source_lines=4,
                )
            ],
            (240, 160),
        )

        line = widget._paint_regions[0]
        text_rect = widget._line_text_rect(line)
        metrics = QFontMetricsF(line.font)
        self.assertEqual(line.source_lines, 4)
        self.assertLessEqual(text_rect.width(), line.patch.width())
        self.assertGreater(
            metrics.horizontalAdvance(line.text),
            text_rect.width(),
            "Bản dịch đủ dài để kiểm tra word-wrap thực sự",
        )
        widget.close()

    def test_width_fitting_uses_original_footprint(self) -> None:
        ink = (10, 12, 120, 28)
        widget = overlay.TranslationOverlay(
            (0, 0, 220, 60),
            [self._region("Longer text", (10, 10, 120, 30), ink)],
            (220, 60),
        )

        line = widget._paint_regions[0]
        budget = round(line.ink.width() * widget.WIDTH_SLACK)
        advance = QFontMetricsF(line.font).horizontalAdvance(line.text)
        self.assertLessEqual(advance, budget + 1)
        widget.close()

    def test_different_original_heights_do_not_share_font_size(self) -> None:
        regions = [
            self._region("Chú thích", (10, 10, 900, 30), (10, 14, 900, 26)),
            self._region("Tiêu đề", (10, 40, 900, 70), (10, 43, 900, 67)),
        ]
        widget = overlay.TranslationOverlay((0, 0, 1000, 90), regions, (1000, 90))

        small, large = widget._paint_regions
        self.assertLess(small.font.pixelSize(), large.font.pixelSize())
        widget.close()

    def test_thick_original_strokes_render_bold(self) -> None:
        box = (10, 10, 190, 34)
        ink = (10, 12, 190, 32)
        thin = overlay.TranslationOverlay(
            (0, 0, 220, 60), [self._region("Chữ thường", box, ink, 2.0)], (220, 60)
        )
        thick = overlay.TranslationOverlay(
            (0, 0, 220, 60), [self._region("Chữ đậm", box, ink, 6.0)], (220, 60)
        )

        self.assertLess(
            thin._paint_regions[0].font.weight(),
            thick._paint_regions[0].font.weight(),
        )
        thin.close()
        thick.close()

    def test_live_overlay_ignores_mouse_clicks_and_escape(self) -> None:
        widget = overlay.TranslationOverlay(
            (0, 0, 220, 60),
            [self._region("Live", (10, 10, 190, 34))],
            (220, 60),
        )
        widget.set_live(True)
        widget.show()
        self.app.processEvents()

        QTest.mouseClick(widget, Qt.MouseButton.RightButton)
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        QTest.keyClick(widget, Qt.Key.Key_Escape)
        self.app.processEvents()

        self.assertTrue(widget.isVisible())
        self.assertIn("bar", widget.toolTip())
        widget.close()


if __name__ == "__main__":
    unittest.main()
