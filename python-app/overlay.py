"""Overlay chọn vùng (PySide6): làm tối desktop, khoét trong suốt vùng chọn."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass

from PySide6.QtCore import (
    QEasingCurve,
    QEventLoop,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

# Bản sắc dark shell: accent trắng trên lớp làm tối — khung chọn nổi bật
# trên mọi nội dung desktop.
DIM = QColor(9, 9, 11, 140)
ACCENT = QColor("#fafafa")
ACCENT_SOFT = QColor(250, 250, 250, 28)
HINT_BG = QColor(24, 24, 27, 242)
HINT_FG = QColor("#fafafa")
HINT_MUTED = QColor("#a1a1aa")
SIZE_BG = QColor(24, 24, 27, 242)
SIZE_FG = QColor("#fafafa")
CORNER = 10  # độ dài góc khung chọn

# Windows 10 2004+: cửa sổ vẫn hiện với người dùng nhưng bị loại khỏi ảnh chụp.
WDA_EXCLUDEFROMCAPTURE = 0x00000011


@dataclass(frozen=True)
class OverlayRegion:
    """Một dòng dịch và cách phủ nền theo tọa độ của ảnh OCR.

    Nếu có `patch_rgb` (nền thật đã xoá chữ gốc bằng inpaint) thì overlay dán
    ảnh đó làm nền — liền mạch như Google Dịch ảnh. Nếu None thì tô đặc `bg`.
    `patch_rect` là hình chữ nhật (toạ độ ảnh nguồn) mà nền phủ lên; mặc định
    bằng `bbox` khi không truyền.
    """

    bbox: tuple[int, int, int, int]
    text: str
    bg: tuple[int, int, int]
    fg: tuple[int, int, int]
    patch_rect: tuple[int, int, int, int] | None = None
    patch_rgb: bytes | None = None
    patch_size: tuple[int, int] | None = None


def _exclude_from_capture(widget: QWidget) -> bool:
    """Loại cửa sổ Qt của app khỏi các API chụp màn hình trên Windows.

    Trả về False trên nền tảng/phiên Windows không hỗ trợ để luồng gọi có thể
    tiếp tục dùng fallback ẩn cửa sổ. Không dùng WDA_MONITOR vì fallback đó tạo
    một hình chữ nhật đen trong ảnh — vẫn làm hỏng OCR và phép lấy màu nền.
    """
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        set_affinity = user32.SetWindowDisplayAffinity
        set_affinity.argtypes = [wintypes.HWND, wintypes.DWORD]
        set_affinity.restype = wintypes.BOOL
        hwnd = wintypes.HWND(int(widget.winId()))
        return bool(set_affinity(hwnd, WDA_EXCLUDEFROMCAPTURE))
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _animations_enabled() -> bool:
    """Tôn trọng cài đặt 'Show animations in Windows'."""
    if os.name != "nt":
        return True
    try:
        value = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            0x1042,
            0,
            ctypes.byref(value),
            0,  # SPI_GETCLIENTAREAANIMATION
        )
        return bool(ok) and bool(value.value)
    except Exception:  # noqa: BLE001
        return True


class _RegionOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.CrossCursor)
        # Phủ toàn bộ desktop ảo (mọi màn hình).
        self._vgeo: QRect = QGuiApplication.primaryScreen().virtualGeometry()
        self.setGeometry(self._vgeo)

        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self._selecting = False
        self.bbox: tuple[int, int, int, int] | None = None
        self._loop = QEventLoop()

        self._hint_font = QFont("Segoe UI", 12)
        self._hint_font.setWeight(QFont.Medium)
        self._size_font = QFont("Cascadia Mono", 11)
        # Fallback nếu máy không có Cascadia Mono.
        if self._size_font.family() != "Cascadia Mono":
            self._size_font = QFont("Consolas", 11)

    # ----- vòng đời -----
    def run(self) -> tuple[int, int, int, int] | None:
        # show() với geometry của toàn desktop ảo → phủ mọi màn hình
        # (showFullScreen chỉ phủ một màn hình).
        self.setGeometry(self._vgeo)
        self.show()
        _exclude_from_capture(self)
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.OtherFocusReason)
        self.grabKeyboard()  # đảm bảo Esc luôn nhận được
        try:
            self._loop.exec()
        finally:
            self.releaseKeyboard()
        return self.bbox

    def _finish(self, bbox: tuple[int, int, int, int] | None) -> None:
        self.bbox = bbox
        self.close()
        if self._loop.isRunning():
            self._loop.quit()

    # ----- sự kiện chuột/phím -----
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._selecting = True
            self._origin = event.position().toPoint()
            self._current = self._origin
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._selecting:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or not self._selecting:
            return
        self._selecting = False
        self._current = event.position().toPoint()
        rect = QRect(self._origin, self._current).normalized()
        if rect.width() < 5 or rect.height() < 5:
            self._finish(None)
            return
        # Đổi sang toạ độ màn hình tuyệt đối cho việc chụp.
        left = rect.left() + self._vgeo.left()
        top = rect.top() + self._vgeo.top()
        self._finish((left, top, left + rect.width(), top + rect.height()))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self._finish(None)

    # ----- vẽ -----
    def _draw_hint_pill(self, painter: QPainter) -> None:
        text = "Kéo để chọn vùng · Esc huỷ"
        painter.setFont(self._hint_font)
        metrics = QFontMetrics(self._hint_font)
        tw = metrics.horizontalAdvance(text)
        th = metrics.height()
        pad_x, pad_y = 18, 10
        pill_w = tw + pad_x * 2
        pill_h = th + pad_y * 2
        x = (self.width() - pill_w) // 2
        y = 28
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, pill_w, pill_h), 10, 10)
        painter.fillPath(path, HINT_BG)
        painter.setPen(QPen(QColor(63, 63, 70), 1))
        painter.drawPath(path)
        painter.setPen(HINT_FG)
        painter.drawText(QRect(x, y, pill_w, pill_h), Qt.AlignCenter, text)

    def _draw_corners(self, painter: QPainter, rect: QRect) -> None:
        pen = QPen(ACCENT, 2.5, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin)
        painter.setPen(pen)
        left, top = rect.left(), rect.top()
        right, bottom = rect.right(), rect.bottom()
        corner = CORNER
        # top-left
        painter.drawLine(left, top, left + corner, top)
        painter.drawLine(left, top, left, top + corner)
        # top-right
        painter.drawLine(right, top, right - corner, top)
        painter.drawLine(right, top, right, top + corner)
        # bottom-left
        painter.drawLine(left, bottom, left + corner, bottom)
        painter.drawLine(left, bottom, left, bottom - corner)
        # bottom-right
        painter.drawLine(right, bottom, right - corner, bottom)
        painter.drawLine(right, bottom, right, bottom - corner)

    def _draw_size_badge(self, painter: QPainter, rect: QRect) -> None:
        label = f"{rect.width()} × {rect.height()}"
        painter.setFont(self._size_font)
        metrics = QFontMetrics(self._size_font)
        tw = metrics.horizontalAdvance(label)
        th = metrics.height()
        pad_x, pad_y = 10, 5
        bw = tw + pad_x * 2
        bh = th + pad_y * 2
        # Ưu tiên dưới khung; nếu sát đáy màn hình thì đưa lên trên.
        bx = rect.center().x() - bw // 2
        by = rect.bottom() + 10
        if by + bh > self.height() - 8:
            by = rect.top() - bh - 10
        if by < 8:
            by = rect.top() + 8
        bx = max(8, min(bx, self.width() - bw - 8))

        path = QPainterPath()
        path.addRoundedRect(QRectF(bx, by, bw, bh), 6, 6)
        painter.fillPath(path, SIZE_BG)
        painter.setPen(SIZE_FG)
        painter.drawText(QRect(bx, by, bw, bh), Qt.AlignCenter, label)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), DIM)

        if self._origin and self._current:
            rect = QRect(self._origin, self._current).normalized()
            # Khoét trong suốt đúng vùng chọn (thấy rõ nội dung bên dưới).
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(rect, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

            # Viền mỏng + fill accent rất nhạt
            painter.fillRect(rect, ACCENT_SOFT)
            pen = QPen(ACCENT, 1.5)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
            self._draw_corners(painter, rect)

            if rect.width() >= 24 and rect.height() >= 16:
                self._draw_size_badge(painter, rect)

        self._draw_hint_pill(painter)
        painter.end()


def select_region(_parent=None) -> tuple[int, int, int, int] | None:
    """Hiện overlay, trả về bbox=(left, top, right, bottom) hoặc None nếu huỷ."""
    return _RegionOverlay().run()


# Giữ tham chiếu mạnh tới các ô dịch đang hiện (tránh bị GC + để xoá hàng loạt).
_live_overlays: list["TranslationOverlay"] = []


def close_all_translations() -> None:
    """Đóng toàn bộ ô dịch nổi đang hiển thị."""
    for widget in list(_live_overlays):
        widget.close()


def hide_translations_for_capture() -> list["TranslationOverlay"]:
    """Ẩn tạm overlay dịch để OCR luôn nhìn thấy nội dung màn hình gốc.

    Đây là fallback chủ động cho Windows cũ và cũng giúp người dùng chọn lại
    đúng vùng chữ đang bị một overlay trước đó che phủ.
    """
    hidden: list[TranslationOverlay] = []
    for widget in list(_live_overlays):
        if widget.isVisible():
            widget.hide()
            hidden.append(widget)
    return hidden


def restore_translations(widgets: list["TranslationOverlay"]) -> None:
    """Hiện lại các overlay còn sống sau khi ảnh nguồn đã được chụp."""
    for widget in widgets:
        if widget in _live_overlays and not widget.isVisible():
            widget.show()
            _exclude_from_capture(widget)
            widget.raise_()


class TranslationOverlay(QWidget):
    """Overlay trong suốt, chỉ che và vẽ lại đúng các dòng chữ OCR."""

    def __init__(
        self,
        bbox: tuple[int, int, int, int],
        regions: list[OverlayRegion],
        image_size: tuple[int, int],
    ) -> None:
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        left, top, right, bottom = bbox
        self._w = max(1, right - left)
        self._h = max(1, bottom - top)
        self.setGeometry(left, top, self._w, self._h)
        self._live = False
        # Callback thay cho hành vi đóng mặc định (dùng cho chế độ live).
        self.dismiss_callback = None
        self._paint_regions = []
        self._build_paint_regions(regions, image_size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Chuột trái: đóng ô này · Chuột phải (bất kỳ đâu): xoá hết")
        _live_overlays.append(self)

    def _build_paint_regions(
        self, regions: list[OverlayRegion], image_size: tuple[int, int]
    ) -> None:
        source_w, source_h = image_size
        scale_x = self._w / max(1, source_w)
        scale_y = self._h / max(1, source_h)

        # Bước 1: dựng patch_rect + ảnh nền cho từng dòng.
        built: list[dict] = []
        for region in regions:
            source_rect = region.patch_rect
            if source_rect is None:
                region_left, region_top, region_right, region_bottom = region.bbox
                x = round(region_left * scale_x)
                y = round(region_top * scale_y)
                w = max(1, round((region_right - region_left) * scale_x))
                h = max(1, round((region_bottom - region_top) * scale_y))
                text_rect = QRect(x, y, w, h)
                pad_x = max(2, min(8, text_rect.height() // 8))
                pad_y = max(1, min(3, text_rect.height() // 10))
                patch_rect = text_rect.adjusted(-pad_x, -pad_y, pad_x, pad_y)
            else:
                sl, st, sr, sb = source_rect
                x = round(sl * scale_x)
                y = round(st * scale_y)
                patch_rect = QRect(
                    x,
                    y,
                    max(1, round((sr - sl) * scale_x)),
                    max(1, round((sb - st) * scale_y)),
                )
            patch_rect = patch_rect.intersected(self.rect())

            image = None
            if region.patch_rgb and region.patch_size:
                pw, ph = region.patch_size
                # QImage không sao chép buffer → .copy() để tự sở hữu dữ liệu.
                image = QImage(
                    region.patch_rgb, pw, ph, pw * 3, QImage.Format_RGB888
                ).copy()
            built.append(
                {
                    "rect": patch_rect,
                    "text": region.text,
                    "bg": QColor(*region.bg),
                    "fg": QColor(*region.fg),
                    "image": image,
                }
            )

        # Chiều cao dòng trung vị (trước khi cắt) → đại diện cỡ chữ gốc.
        raw_heights = sorted(item["rect"].height() for item in built) or [16]
        median_h = raw_heights[len(raw_heights) // 2]

        # Bước 2: khử chồng lấn dọc — nếu patch dòng trên trùm xuống dòng dưới,
        # cắt tại điểm giữa để hai ô không đè lên nhau.
        order = sorted(range(len(built)), key=lambda i: built[i]["rect"].top())
        for prev_i, next_i in zip(order, order[1:]):
            top_rect = built[prev_i]["rect"]
            bottom_rect = built[next_i]["rect"]
            if bottom_rect.top() < top_rect.bottom():
                mid = (bottom_rect.top() + top_rect.bottom()) // 2
                top_rect.setBottom(mid)
                bottom_rect.setTop(mid + 1)

        # Bước 3: MỘT cỡ font chung cho mọi dòng, lấy theo chiều cao trung vị
        # (bám sát cỡ chữ gốc, đồng đều không to nhỏ lẫn lộn). Vì chữ được phép
        # tràn sang phải nên không cần co theo bề rộng.
        uniform = self._fit_font_size(QRect(0, 0, 1, median_h), "")
        self._paint_regions = []
        for item in built:
            self._paint_regions.append(
                (
                    item["rect"],
                    item["text"],
                    item["bg"],
                    item["fg"],
                    QFont("Segoe UI", uniform),
                    item["image"],
                )
            )

    def update_content(
        self, regions: list[OverlayRegion], image_size: tuple[int, int]
    ) -> None:
        """Vẽ lại nội dung tại chỗ (cho live) — không tạo widget mới, đỡ nháy."""
        self._build_paint_regions(regions, image_size)
        self.update()

    def set_live(self, on: bool) -> None:
        self._live = on
        if on:
            self.setToolTip("Đang LIVE dịch · Chuột phải hoặc Esc để dừng")
        self.update()

    def _fit_font_size(self, rect: QRect, text: str) -> int:
        """Cỡ font lớn nhất để MỘT dòng cao vừa `rect`.

        Chỉ ràng buộc theo CHIỀU CAO (bám sát cỡ chữ gốc); bề rộng để chữ tràn
        sang phải khi bản dịch dài hơn — tránh co chữ nhỏ lại như trước.
        """
        size = max(8, min(rect.height(), 48))
        while size >= 8:
            font = QFont("Segoe UI", size)
            if QFontMetrics(font).height() <= rect.height():
                return size
            size -= 1
        return 8

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        # Một dòng, KHÔNG word-wrap; cho phép chữ tràn sang phải (bản dịch dài
        # hơn gốc) thay vì co nhỏ hay xuống dòng làm đè lên dòng dưới.
        flags = Qt.AlignLeft | Qt.AlignVCenter
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for rect, text, bg, fg, font, image in self._paint_regions:
            if image is not None:
                # Nền thật đã xoá chữ gốc → dán vào đúng chỗ, liền mạch với desktop.
                painter.drawImage(rect, image)
            else:
                painter.fillRect(rect, bg)
            painter.setFont(font)
            # Mở rộng vùng vẽ chữ tới mép phải widget để không bị cắt khi tràn.
            text_rect = QRect(
                rect.left() + 2,
                rect.top(),
                max(rect.width() - 4, self.width() - rect.left() - 2),
                rect.height(),
            )
            # Chỉ vẽ chữ, không halo/viền: nền đã dựng lại (inpaint) và màu chữ
            # lấy theo bản gốc nên đã đủ tương phản — halo chỉ tạo riềm màu thừa.
            painter.setPen(fg)
            painter.drawText(text_rect, flags, text)
        if self._live:
            self._draw_live_badge(painter)
        painter.end()

    def _draw_live_badge(self, painter: QPainter) -> None:
        """Chấm đỏ + chữ LIVE ở góc trên trái, báo overlay đang tự cập nhật."""
        painter.setRenderHint(QPainter.Antialiasing, True)
        font = QFont("Segoe UI", 9)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        label = "LIVE"
        dot_d = 7
        gap = 6
        pad_x, pad_y = 9, 5
        tw = metrics.horizontalAdvance(label)
        th = metrics.height()
        pill_w = pad_x * 2 + dot_d + gap + tw
        pill_h = pad_y * 2 + max(th, dot_d)
        x, y = 6, 6
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, pill_w, pill_h), pill_h / 2, pill_h / 2)
        painter.fillPath(path, QColor(24, 24, 27, 235))
        cy = y + pill_h / 2
        painter.setBrush(QColor("#f43f5e"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(x + pad_x, cy - dot_d / 2, dot_d, dot_d))
        painter.setPen(QColor("#fafafa"))
        painter.drawText(
            QRectF(x + pad_x + dot_d + gap, y, tw + 4, pill_h),
            Qt.AlignVCenter | Qt.AlignLeft,
            label,
        )

    def mousePressEvent(self, event) -> None:
        if self.dismiss_callback is not None:
            self.dismiss_callback()
            return
        if event.button() == Qt.RightButton:
            close_all_translations()
        else:
            self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            if self.dismiss_callback is not None:
                self.dismiss_callback()
                return
            close_all_translations()

    def closeEvent(self, event) -> None:
        try:
            _live_overlays.remove(self)
        except ValueError:
            pass
        super().closeEvent(event)


def show_translation(
    bbox: tuple[int, int, int, int],
    regions: list[OverlayRegion],
    image_size: tuple[int, int],
) -> TranslationOverlay:
    widget = TranslationOverlay(bbox, regions, image_size)
    # Hiện đè lên trên nhưng KHÔNG cướp focus của ứng dụng người dùng đang dùng.
    widget.setAttribute(Qt.WA_ShowWithoutActivating, True)
    if _animations_enabled():
        # Fade vào nhẹ (~170ms) — chỉ đổi opacity, giữ nguyên vị trí che chữ gốc.
        widget.setWindowOpacity(0.0)
        widget.show()
        _exclude_from_capture(widget)
        widget.raise_()
        anim = QPropertyAnimation(widget, b"windowOpacity", widget)
        anim.setDuration(170)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        widget._entrance_anim = anim  # giữ tham chiếu tránh bị GC
    else:
        widget.show()
        _exclude_from_capture(widget)
        widget.raise_()
    return widget
