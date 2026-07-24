from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

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
        rect = widget._paint_regions[0][0]
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


if __name__ == "__main__":
    unittest.main()
