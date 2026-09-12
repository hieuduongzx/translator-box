"""Overlay chọn vùng (PySide6): làm tối desktop, khoét trong suốt vùng chọn."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from functools import lru_cache

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
    QCursor,
    QFont,
    QFontMetrics,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
    QRegion,
)
from PySide6.QtWidgets import QWidget

from theme import TOKENS
from ui_utils import AlphaLayerCache

# Overlay dùng chung substrate tối và accent duy nhất của shell.
DIM = QColor(15, 15, 17, 168)
ACCENT = QColor(TOKENS["FOCUS"])
ACCENT_SOFT = QColor(200, 255, 77, 20)
CROSSHAIR = QColor(200, 255, 77, 46)
HINT_BG = QColor(15, 15, 17, 242)
HINT_LINE = QColor(TOKENS["LINE_STRONG"])
HINT_FG = QColor(TOKENS["TEXT"])
HINT_MUTED = QColor(TOKENS["TEXT_MUTED"])
BADGE_FG = QColor(TOKENS["TEXT"])
RADIUS = 4.0

# Windows 10 2004+: cửa sổ vẫn hiện với người dùng nhưng bị loại khỏi ảnh chụp.
WDA_EXCLUDEFROMCAPTURE = 0x00000011


@dataclass(frozen=True)
class OverlayRegion:
    """Một dòng/khối dịch và cách phủ nền theo tọa độ của ảnh OCR.

    Nếu có `patch_rgb` (nền thật đã xoá chữ gốc bằng inpaint) thì overlay dán
    ảnh đó làm nền — liền mạch như Google Dịch ảnh. Nếu None thì tô đặc `bg`.
    `patch_rect` là hình chữ nhật (toạ độ ảnh nguồn) mà nền phủ lên; mặc định
    bằng `bbox` khi không truyền.
    `ink_rect` là hộp bao sát nét chữ gốc — nguồn chuẩn để suy cỡ chữ (hộp OCR
    lỏng hơn nét chữ nên bám theo nó sẽ vẽ to hơn bản gốc). `stroke_thickness` là
    độ dày nét chữ gốc (pixel ảnh nguồn) để quyết định vẽ đậm hay thường.
    """

    bbox: tuple[int, int, int, int]
    text: str
    bg: tuple[int, int, int]
    fg: tuple[int, int, int]
    patch_rect: tuple[int, int, int, int] | None = None
    patch_rgb: bytes | None = None
    patch_size: tuple[int, int] | None = None
    ink_rect: tuple[int, int, int, int] | None = None
    stroke_thickness: float = 0.0
    source_lines: int = 1


@dataclass
class PaintedLine:
    """Một dòng/khối đã sẵn sàng vẽ."""

    patch: QRect
    ink: QRect
    text: str
    bg: QColor
    fg: QColor
    font: QFont
    image: QImage | None
    source_lines: int = 1
    # Hộp vẽ chữ và cờ word-wrap tính một lần khi build, dùng lại ở mọi paint.
    text_rect: QRect | None = None
    text_flags: int = 0


# Chuỗi tham chiếu để quy đổi "chiều cao ink" ↔ "cỡ em" của font: có cả chữ hoa
# và phần đuôi xuống dưới baseline, tức đúng biên trên–dưới mà OCR nhìn thấy.
_INK_REFERENCE = "Hg"
_REFERENCE_EM = 100
_ink_ratio_cache: dict[tuple[str, int], float] = {}


def _ink_to_em_ratio(family: str, weight: QFont.Weight) -> float:
    """Chiều cao ink của chuỗi tham chiếu khi em = 1 (đo một lần rồi cache)."""
    key = (family, int(weight))
    cached = _ink_ratio_cache.get(key)
    if cached is not None:
        return cached
    font = QFont(family)
    font.setWeight(weight)
    font.setPixelSize(_REFERENCE_EM)
    height = QFontMetricsF(font).tightBoundingRect(_INK_REFERENCE).height()
    ratio = height / _REFERENCE_EM if height > 0 else 0.9
    _ink_ratio_cache[key] = ratio
    return ratio


def _probe_font(family: str, weight: int, pixel_size: int) -> QFont:
    font = QFont(family)
    font.setWeight(QFont.Weight(weight))
    font.setPixelSize(pixel_size)
    return font


# Ba phép đo dưới đây bị gọi lặp trong lúc dò cỡ chữ VÀ lại lặp cho mỗi frame
# live với cùng đối số. `tightBoundingRect` phải đọc outline của glyph nên là
# phép đắt nhất của QFontMetrics — cache theo (text, family, weight, size).
@lru_cache(maxsize=4096)
def _ink_height(text: str, family: str, weight: int, pixel_size: int) -> float:
    metrics = QFontMetricsF(_probe_font(family, weight, pixel_size))
    return metrics.tightBoundingRect(text).height()


@lru_cache(maxsize=4096)
def _text_advance(text: str, family: str, weight: int, pixel_size: int) -> int:
    metrics = QFontMetricsF(_probe_font(family, weight, pixel_size))
    return round(metrics.horizontalAdvance(text))


@lru_cache(maxsize=4096)
def _wrapped_fits(
    text: str, family: str, weight: int, pixel_size: int, width: int, height: int
) -> bool:
    metrics = QFontMetrics(_probe_font(family, weight, pixel_size))
    measured = metrics.boundingRect(
        QRect(0, 0, width, height * 4),
        Qt.TextWordWrap | Qt.AlignHCenter | Qt.AlignVCenter,
        text,
    )
    return measured.width() <= width and measured.height() <= height


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
        # Vị trí con trỏ để vẽ crosshair khi chưa bắt đầu kéo.
        self._cursor: QPoint | None = None
        self.setMouseTracking(True)

        self._hint_font = QFont("Segoe UI", 11)
        self._badge_font = QFont("Segoe UI", 10)
        self._hint_metrics = QFontMetrics(self._hint_font)
        self._badge_metrics = QFontMetrics(self._badge_font)

    # ----- vòng đời -----
    def run(self) -> tuple[int, int, int, int] | None:
        # show() với geometry của toàn desktop ảo → phủ mọi màn hình
        # (showFullScreen chỉ phủ một màn hình).
        self.setGeometry(self._vgeo)
        self._cursor = self.mapFromGlobal(QCursor.pos())
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

    def _selection_rect(self) -> QRect | None:
        if self._origin is None or self._current is None:
            return None
        return QRect(self._origin, self._current).normalized()

    def mouseMoveEvent(self, event) -> None:
        position = event.position().toPoint()
        if self._selecting:
            # Chỉ vẽ lại hợp của khung cũ và khung mới (đã nới cho viền + badge)
            # thay vì cả desktop ảo — với hai màn hình đó là ~6 Mpx mỗi lần di.
            previous = self._selection_rect()
            self._current = position
            current = self._selection_rect()
            if previous is None or current is None:
                self.update()
                return
            dirty = previous.united(current).adjusted(-4, -4, 4, 4)
            badge_height = self._badge_metrics.height() + 22
            self.update(dirty.adjusted(0, -badge_height, 0, badge_height))
            return
        # Chưa kéo: chỉ vẽ lại hai dải mảnh của crosshair (cũ + mới).
        previous_point = self._cursor
        self._cursor = position
        for point in (previous_point, position):
            if point is None:
                continue
            self.update(0, point.y() - 1, self.width(), 3)
            self.update(point.x() - 1, 0, 3, self.height())

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
    def _hint_anchor(self, pill_width: int) -> QPoint:
        """Đặt viên gợi ý giữa MÀN HÌNH đang có con trỏ, không giữa desktop ảo.

        Với nhiều màn hình, canh giữa desktop ảo có thể rơi vào khe giữa hai
        màn hình và người dùng không đọc được gì.
        """
        screen = (
            QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        )
        if screen is None:
            return QPoint((self.width() - pill_width) // 2, 28)
        geometry = screen.geometry()
        x = geometry.center().x() - self._vgeo.left() - pill_width // 2
        y = geometry.top() - self._vgeo.top() + 30
        return QPoint(x, y)

    def _draw_crosshair(self, painter: QPainter) -> None:
        """Hai đường mảnh theo con trỏ — canh mép vùng cần chọn cho chính xác."""
        if self._cursor is None:
            return
        painter.setPen(QPen(CROSSHAIR, 1.0))
        painter.drawLine(0, self._cursor.y(), self.width(), self._cursor.y())
        painter.drawLine(self._cursor.x(), 0, self._cursor.x(), self.height())

    def _draw_hint(self, painter: QPainter) -> None:
        """Một dòng hướng dẫn duy nhất, không chip phím hay vạch ngăn."""
        label = "Kéo để chọn vùng · Esc để huỷ"
        metrics = self._hint_metrics
        pad_x, pad_y = 14, 9
        pill_w = metrics.horizontalAdvance(label) + pad_x * 2
        pill_h = metrics.height() + pad_y * 2
        anchor = self._hint_anchor(pill_w)
        rect = QRectF(anchor.x(), anchor.y(), pill_w, pill_h)
        painter.setPen(QPen(HINT_LINE, 1.0))
        painter.setBrush(HINT_BG)
        painter.drawRoundedRect(rect, RADIUS, RADIUS)
        painter.setFont(self._hint_font)
        painter.setPen(HINT_FG)
        painter.drawText(rect, Qt.AlignCenter, label)

    def _draw_size_badge(self, painter: QPainter, rect: QRect) -> None:
        label = f"{rect.width()} × {rect.height()}"
        metrics = self._badge_metrics
        pad_x, pad_y = 9, 5
        bw = metrics.horizontalAdvance(label) + pad_x * 2
        bh = metrics.height() + pad_y * 2
        # Ưu tiên dưới khung; nếu sát đáy màn hình thì đưa lên trên.
        bx = rect.center().x() - bw // 2
        by = rect.bottom() + 8
        if by + bh > self.height() - 8:
            by = rect.top() - bh - 8
        if by < 8:
            by = rect.top() + 8
        bx = max(8, min(bx, self.width() - bw - 8))

        badge_rect = QRectF(bx, by, bw, bh)
        painter.setPen(QPen(HINT_LINE, 1.0))
        painter.setBrush(HINT_BG)
        painter.drawRoundedRect(badge_rect, RADIUS, RADIUS)
        painter.setFont(self._badge_font)
        painter.setPen(BADGE_FG)
        painter.drawText(badge_rect, Qt.AlignCenter, label)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        # Chỉ tô lớp mờ trong vùng Qt yêu cầu vẽ lại.
        painter.fillRect(event.rect(), DIM)

        rect = self._selection_rect()
        if rect is not None:
            # Khoét trong suốt đúng vùng chọn (thấy rõ nội dung bên dưới).
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(rect, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

            painter.fillRect(rect, ACCENT_SOFT)
            painter.setPen(QPen(ACCENT, 1.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)

            if rect.width() >= 24 and rect.height() >= 16:
                self._draw_size_badge(painter, rect)
        else:
            # Chưa kéo: crosshair + gợi ý; khi đã kéo thì bỏ để không che nội dung.
            self._draw_crosshair(painter)
            self._draw_hint(painter)
        painter.end()


def select_region(_parent=None) -> tuple[int, int, int, int] | None:
    """Hiện overlay, trả về bbox=(left, top, right, bottom) hoặc None nếu huỷ."""
    return _RegionOverlay().run()


# Giữ tham chiếu mạnh tới các ô dịch đang hiện (tránh bị GC + để xoá hàng loạt).
_live_overlays: list["TranslationOverlay"] = []


def close_all_translations(*, include_live: bool = True) -> None:
    """Đóng các ô dịch nổi; có thể giữ nguyên overlay của phiên Live."""
    for widget in list(_live_overlays):
        if include_live or not widget._live:
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

    FONT_FAMILY = "Segoe UI"
    MIN_FONT_PX = 8
    MAX_FONT_PX = 64
    # Bản dịch chỉ được nới nhẹ so với bề rộng ink gốc rồi phải co lại. Cửa sổ
    # luôn đúng bằng vùng người dùng đã chọn nên chữ không thể tràn ra desktop.
    WIDTH_SLACK = 1.15
    # Chỉ các dòng có chiều cao hộp gốc lệch tối đa 20% mới dùng chung cỡ chữ.
    # Ngưỡng rộng hơn dễ gom chú thích nhỏ với body và làm chú thích bị phóng to.
    FONT_GROUP_TOLERANCE = 0.20
    # Dấu tiếng Việt (ầ, ẫ, ộ…) vươn cao hơn chữ hoa nên ink bản dịch được phép
    # cao hơn ink chữ gốc chừng này; chỉ vượt mức đó mới co chữ. Nếu siết đúng
    # bằng ink gốc thì THÂN chữ bị nhỏ đi ~30% chỉ vì mấy cái dấu.
    INK_OVERFLOW = 1.22

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
        self._paint_regions = []
        self._layer_cache = AlphaLayerCache()
        self._mask_key: tuple | None = None
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

        def to_widget(source_rect: tuple[int, int, int, int]) -> QRect:
            left, top, right, bottom = source_rect
            return QRect(
                round(left * scale_x),
                round(top * scale_y),
                max(1, round((right - left) * scale_x)),
                max(1, round((bottom - top) * scale_y)),
            )

        # Bước 1: dựng hộp nền (patch), hộp ink và ảnh nền cho từng dòng.
        built: list[dict] = []
        for region in regions:
            box = to_widget(region.bbox)
            if region.patch_rect is None:
                pad_x = max(2, min(8, box.height() // 8))
                pad_y = max(1, min(3, box.height() // 10))
                patch_rect = box.adjusted(-pad_x, -pad_y, pad_x, pad_y)
            else:
                patch_rect = to_widget(region.patch_rect)
            patch_rect = patch_rect.intersected(self.rect())
            # Không có ink_rect (thiếu cv2 hoặc mặt nạ bất thường) → dùng hộp OCR
            # thu nhỏ nhẹ, vì hộp phát hiện luôn lỏng hơn nét chữ thật.
            ink = to_widget(region.ink_rect) if region.ink_rect else box

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
                    "box": box,
                    "ink": ink,
                    "measured": region.ink_rect is not None,
                    "text": region.text,
                    "bg": QColor(*region.bg),
                    "fg": QColor(*region.fg),
                    # Độ dày nét đổi sang đơn vị của widget để so với cỡ chữ.
                    "thickness": region.stroke_thickness * scale_y,
                    "image": image,
                    "source_lines": max(1, region.source_lines),
                }
            )

        # Bước 2: khử chồng lấn dọc — nếu patch dòng trên trùm xuống dòng dưới,
        # cắt tại điểm giữa để hai ô không đè lên nhau.
        order = sorted(range(len(built)), key=lambda i: built[i]["rect"].top())
        for prev_i, next_i in zip(order, order[1:]):
            top_rect = built[prev_i]["rect"]
            bottom_rect = built[next_i]["rect"]
            horizontal_overlap = (
                min(top_rect.right(), bottom_rect.right())
                - max(top_rect.left(), bottom_rect.left())
                + 1
            )
            if bottom_rect.top() < top_rect.bottom() and horizontal_overlap > 0:
                mid = (bottom_rect.top() + top_rect.bottom()) // 2
                top_rect.setBottom(mid)
                bottom_rect.setTop(mid + 1)

        # Bước 3: cỡ chữ suy từ ink CHỮ GỐC rồi co cho vừa bề rộng (như Google
        # Dịch ảnh) — xem `_line_fonts`.
        self._paint_regions = [
            PaintedLine(
                patch=item["rect"],
                ink=item["ink"],
                text=item["text"],
                bg=item["bg"],
                fg=item["fg"],
                font=font,
                image=item["image"],
                source_lines=item["source_lines"],
            )
            for item, font in zip(built, self._line_fonts(built))
        ]
        # Hộp vẽ chữ và cờ align cố định theo layout → tính sẵn, khỏi tính lại ở
        # mỗi paintEvent lẫn mỗi lần dựng input mask.
        for line in self._paint_regions:
            line.text_rect = self._compute_text_rect(line)
            line.text_flags = (
                Qt.TextWordWrap | Qt.AlignHCenter | Qt.AlignVCenter
                if line.source_lines > 1
                else Qt.AlignLeft | Qt.AlignVCenter
            )
        self._apply_input_mask()

    def _compute_text_rect(self, line: PaintedLine) -> QRect:
        """Hộp vẽ chữ: canh theo ink gốc, cao hơn ink để dấu/đuôi chữ không bị cắt."""
        if line.source_lines > 1:
            margin_x = max(1, min(4, line.patch.width() // 20))
            margin_y = max(1, min(3, line.patch.height() // 20))
            return line.patch.adjusted(margin_x, margin_y, -margin_x, -margin_y)
        height = max(line.ink.height(), round(line.font.pixelSize() * 1.7))
        return QRect(
            line.ink.left(),
            line.ink.center().y() - height // 2,
            max(1, self.width() - line.ink.left()),
            height,
        )

    def _apply_input_mask(self) -> None:
        """Chỉ vùng thật sự có vẽ mới nhận chuột.

        Phần còn lại của vùng chọn trong suốt và phải tiếp tục cho click xuyên
        xuống ứng dụng bên dưới. `setMask` đổi window region ở tầng compositor —
        thao tác đắt trên Windows — nên bỏ qua khi hình dạng không đổi (live
        thường vẽ lại đúng cùng một layout).
        """
        if not self._paint_regions:
            if self._mask_key is not None:
                self._mask_key = None
                self.clearMask()
            return
        rects: list[QRect] = []
        for line in self._paint_regions:
            rects.append(line.patch.adjusted(-1, -1, 1, 1))
            text_rect = line.text_rect or self._compute_text_rect(line)
            if line.source_lines > 1:
                rects.append(text_rect)
                continue
            advance = _text_advance(
                line.text, line.font.family(), int(line.font.weight()),
                line.font.pixelSize(),
            )
            rects.append(
                QRect(
                    text_rect.left(),
                    text_rect.top(),
                    min(advance + 6, text_rect.width()),
                    text_rect.height(),
                )
            )
        key = tuple((r.left(), r.top(), r.width(), r.height()) for r in rects)
        if key == self._mask_key:
            return
        self._mask_key = key
        region = QRegion()
        for rect in rects:
            region = region.united(rect)
        self.setMask(region)

    def _line_fonts(self, built: list[dict]) -> list[QFont]:
        """Chọn một cỡ chung cho các dòng có chiều cao gốc tương đương.

        Các hộp được xếp theo chiều cao rồi chia nhóm với dung sai 20%. Mỗi nhóm
        lấy ink đại diện và siết theo dòng dài nhất, nên body vẫn đồng đều nhưng
        chú thích/tiêu đề không bị phóng về cùng cỡ với body.
        """
        if not built:
            return []

        groups: list[list[dict]] = []

        def source_line_height(item: dict) -> float:
            return max(1.0, item["box"].height() / item["source_lines"])

        for item in sorted(built, key=source_line_height):
            height = source_line_height(item)
            if not groups:
                groups.append([item])
                continue
            anchor = source_line_height(groups[-1][0])
            if height > anchor * (1.0 + self.FONT_GROUP_TOLERANCE):
                groups.append([item])
            else:
                groups[-1].append(item)

        sizes: dict[int, int] = {}
        target_inks: dict[int, float] = {}
        for group in groups:
            target_ink = self._reference_ink(group)
            size = self._block_size(group, target_ink)
            for item in group:
                sizes[id(item)] = size
                target_inks[id(item)] = target_ink

        fonts: list[QFont] = []
        for item in built:
            font = QFont(self.FONT_FAMILY)
            font.setWeight(
                QFont.DemiBold
                if self._is_bold(item, target_inks[id(item)])
                else QFont.Normal
            )
            font.setPixelSize(sizes[id(item)])
            fonts.append(font)
        return fonts

    @staticmethod
    def _reference_ink(items: list[dict]) -> float:
        """Chiều cao ink đại diện của một khối (percentile 90, chống nhiễu OCR)."""
        heights = sorted(
            max(1.0, item["ink"].height() / item["source_lines"]) for item in items
        )
        reference = heights[min(len(heights) - 1, int(len(heights) * 0.9))]
        # Hộp OCR chưa đo được ink thật thì trừ bớt phần lỏng thường thấy (~12%).
        if not any(item["measured"] for item in items):
            return max(6.0, reference * 0.88)
        return float(reference)

    def _block_size(self, items: list[dict], target_ink: float) -> int:
        """Cỡ chữ dùng chung cho cả khối: vừa chiều cao ink, vừa bề rộng chỗ trống."""
        family = self.FONT_FAMILY
        ratio = _ink_to_em_ratio(family, QFont.Normal)
        size = max(self.MIN_FONT_PX, min(self.MAX_FONT_PX, round(target_ink / ratio)))
        max_ink = target_ink * self.INK_OVERFLOW
        weight = int(QFont.Normal)
        for item in items:
            size = min(size, self._fit_ink_height(item["text"], max_ink, size, weight))
            if item["source_lines"] > 1:
                size = min(size, self._wrapped_size(item, size, weight))
            else:
                size = min(size, self._width_size(item, size, weight))
        return max(self.MIN_FONT_PX, size)

    def _largest_fitting(self, upper: int, fits) -> int:
        """Cỡ chữ lớn nhất trong [MIN_FONT_PX, upper] còn thoả `fits`.

        Bản trước dò tuyến tính 1px mỗi bước và mỗi bước lại layout/đo lại toàn
        bộ chuỗi — từ 64px xuống 8px là tới 56 lần đo cho MỘT khối. Phép đo đơn
        điệu theo cỡ chữ nên nhị phân chỉ cần ~6 lần.
        """
        low = self.MIN_FONT_PX
        if upper <= low:
            return low
        if fits(upper):
            return upper
        high = upper
        while low < high:
            middle = (low + high + 1) // 2
            if fits(middle):
                low = middle
            else:
                high = middle - 1
        return low

    def _wrapped_size(self, item: dict, size: int, weight: int) -> int:
        """Co khối dịch cho vừa speech bubble, có word-wrap và khoảng thở."""
        box = item["rect"]
        margin_x = max(1, min(4, box.width() // 20))
        margin_y = max(1, min(3, box.height() // 20))
        width = max(1, box.width() - margin_x * 2)
        height = max(1, box.height() - margin_y * 2)
        text = item["text"]
        return self._largest_fitting(
            size,
            lambda candidate: _wrapped_fits(
                text, self.FONT_FAMILY, weight, candidate, width, height
            ),
        )

    @staticmethod
    def _is_bold(item: dict, target_ink: float) -> bool:
        """Chữ gốc có đậm không: so độ dày nét với CỠ CHỮ của khối, không phải với
        ink riêng của dòng (dòng toàn chữ thấp có ink nhỏ sẽ bị coi là đậm oan).

        Ngưỡng `0.14·h + 0.7` hiệu chỉnh trên Segoe UI light→bold ở 12–34px: nét
        regular luôn nằm dưới, semibold/bold luôn nằm trên.
        """
        thickness = item.get("thickness") or 0.0
        return thickness > 0 and thickness >= 0.14 * target_ink + 0.7

    def _fit_ink_height(
        self, text: str, max_ink: float, size: int, weight: int
    ) -> int:
        """Co cỡ chữ khi ink bản dịch cao QUÁ mức cho phép so với chữ gốc.

        Chỉ CO chứ không nới — dòng nào bản dịch toàn chữ thấp (không dấu, không
        đuôi xuống) thì giữ cỡ suy từ chuỗi tham chiếu, không phình to.
        """
        if not text or max_ink <= 0:
            return size
        ink = _ink_height(text, self.FONT_FAMILY, weight, size)
        if ink <= max_ink or ink <= 0:
            return size
        return self._largest_fitting(
            size,
            lambda candidate: _ink_height(
                text, self.FONT_FAMILY, weight, candidate
            )
            <= max_ink,
        )

    def _width_size(self, item: dict, size: int, weight: int) -> int:
        """Cỡ chữ lớn nhất vừa footprint gốc và phần còn lại của vùng chọn."""
        ink = item["ink"]
        wanted = max(round(ink.width() * self.WIDTH_SLACK), 28)
        available = max(1, self._w - ink.left() - 2)
        budget = min(wanted, available)
        text = item["text"]
        advance = _text_advance(text, self.FONT_FAMILY, weight, size)
        if advance <= budget or advance <= 0:
            return size
        return self._largest_fitting(
            size,
            lambda candidate: _text_advance(
                text, self.FONT_FAMILY, weight, candidate
            )
            <= budget,
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
            self.setToolTip(
                "Đang dịch trực tiếp · Dừng bằng nút Màn hình trên bar hoặc phím tắt"
            )
        else:
            self.setToolTip("Trái: đóng ô này · Phải: đóng tất cả")

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for line in self._paint_regions:
            if line.image is not None:
                # Nền thật đã xoá chữ gốc → dán vào đúng chỗ, liền mạch với desktop.
                painter.drawImage(line.patch, line.image)
            else:
                painter.fillRect(line.patch, line.bg)
        self._paint_text(painter)
        if self._live:
            self._draw_live_badge(painter)
        painter.end()

    def _paint_text(self, painter: QPainter) -> None:
        """Vẽ mọi dòng dịch qua một lớp ARGB để giữ đúng màu chữ (AA xám).

        Vẽ trực tiếp lên miếng nền đục sẽ bị Windows bật ClearType, để lại riềm
        đỏ/xanh quanh nét chữ — nhìn ra màu khác hẳn bản gốc.
        """
        if not self._paint_regions:
            return
        layer = self._layer_cache.acquire(self.size())
        target = QPainter(layer) if layer is not None else painter
        target.setRenderHint(QPainter.TextAntialiasing, True)
        for line in self._paint_regions:
            target.setFont(line.font)
            # Chỉ vẽ chữ, không halo/viền: nền đã dựng lại (inpaint) và màu chữ
            # lấy theo bản gốc nên đã đủ tương phản — halo chỉ tạo riềm màu thừa.
            target.setPen(line.fg)
            target.drawText(
                line.text_rect or self._compute_text_rect(line),
                line.text_flags,
                line.text,
            )
        if layer is not None:
            target.end()
            painter.drawImage(0, 0, layer)

    def _draw_live_badge(self, painter: QPainter) -> None:
        """Chấm accent nhỏ ở góc, báo overlay đang tự cập nhật."""
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(QColor(TOKENS["FOCUS"]))
        painter.setPen(QPen(QColor(15, 15, 17, 200), 1.0))
        painter.drawEllipse(QRectF(7.0, 7.0, 7.0, 7.0))

    def mousePressEvent(self, event) -> None:
        if self._live:
            event.accept()
            return
        if event.button() == Qt.RightButton:
            close_all_translations()
        else:
            self.close()

    def keyPressEvent(self, event) -> None:
        if self._live:
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            close_all_translations()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        try:
            _live_overlays.remove(self)
        except ValueError:
            pass
        super().closeEvent(event)


def render_translated_image(
    source: QImage,
    regions: list[OverlayRegion],
    image_size: tuple[int, int],
) -> QImage:
    """Ghép nền đã inpaint và chữ dịch lên toàn bộ ảnh clipboard."""
    if source.isNull():
        raise RuntimeError("Không đọc được ảnh nguồn từ clipboard.")
    result = source.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    compositor = TranslationOverlay(
        (0, 0, result.width(), result.height()), regions, image_size
    )
    painter = QPainter(result)
    try:
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for line in compositor._paint_regions:
            if line.image is not None:
                painter.drawImage(line.patch, line.image)
            else:
                painter.fillRect(line.patch, line.bg)
        compositor._paint_text(painter)
    finally:
        painter.end()
        compositor.close()
    return result


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
