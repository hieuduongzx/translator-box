"""Các widget tái sử dụng trong HUD và cửa sổ cài đặt."""

from __future__ import annotations

import math
from typing import Protocol

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)
from PySide6.QtWidgets import (
    QColorDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config import HUD_STYLE_DEFAULTS
from theme import TOKENS
from ui_utils import (
    _combo_from_event,
    _fmt_hotkey,
    _state_icon,
    alpha_text_layer,
)

# Màu của chấm trạng thái theo state do workflow gửi lên.
_STATE_COLORS = {
    "ready": TOKENS["TEXT_MUTED"],
    "ok": TOKENS["OK"],
    "busy": TOKENS["BUSY"],
    "error": TOKENS["DANGER"],
}


class DraggableWindow(Protocol):
    """Giao tiếp tối thiểu mà thanh kéo cần từ HUD."""

    def _try_start_resize(self, global_position: QPoint) -> bool: ...

    def _edges_for_global(self, global_position: QPoint): ...

    def _cursor_for_edges(self, edges): ...

    def _persist_geometry(self) -> None: ...

    def _toggle_bar(self) -> None: ...

    def frameGeometry(self): ...

    def move(self, position: QPoint) -> None: ...


class HotkeyEdit(QLineEdit):
    """Ô ghi tổ hợp phím, tránh phải nhập cú pháp bằng tay."""

    changed = Signal()

    def __init__(self, combo: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("hotkey")
        self.setReadOnly(True)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Bấm rồi nhấn tổ hợp phím. Esc: huỷ · Del: tắt phím này.")
        self._combo = (combo or "").strip().lower()
        self._recording = False
        self.setProperty("conflict", "false")
        self._render()

    def combo(self) -> str:
        return self._combo

    def set_combo(self, combo: str) -> None:
        """Đặt tổ hợp từ code (vd. khi khôi phục mặc định)."""
        normalized = (combo or "").strip().lower()
        if normalized == self._combo:
            return
        self._combo = normalized
        self._render()
        self.changed.emit()

    def set_conflict(self, conflict: bool) -> None:
        """Tô đỏ ô đang trùng phím với một hành động khác."""
        flag = "true" if conflict else "false"
        if self.property("conflict") == flag:
            return
        self.setProperty("conflict", flag)
        self.style().unpolish(self)
        self.style().polish(self)

    def _render(self) -> None:
        self.setText(
            "Đang ghi… (Esc huỷ · Del tắt)"
            if self._recording
            else _fmt_hotkey(self._combo)
        )

    def _set_recording(self, recording: bool) -> None:
        self._recording = recording
        self.setProperty("recording", "true" if recording else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self._render()

    def _commit(self, combo: str) -> None:
        changed = combo != self._combo
        self._combo = combo
        self.clearFocus()
        if changed:
            self.changed.emit()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self._set_recording(True)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self._set_recording(False)

    def mousePressEvent(self, event) -> None:
        if not self._recording:
            self.setFocus(Qt.MouseFocusReason)
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if not self._recording:
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key_Escape:
            self.clearFocus()
            return
        if event.key() in (Qt.Key_Backspace, Qt.Key_Delete):
            self._commit("")
            return
        combo = _combo_from_event(event)
        if combo:
            self._commit(combo)


class BarButton(QPushButton):
    """Nút icon nhỏ trên thanh công cụ HUD.

    Icon dùng QIcon nhiều mode/state nên Qt tự đổi màu glyph khi hover, khi nút
    được check hoặc khi bị vô hiệu hoá.
    """

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("barBtn")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(30, 30)
        self.setIconSize(QSize(18, 18))
        self.setIcon(_state_icon(kind))


class DragBar(QFrame):
    """Vùng kéo/resize cho cửa sổ frameless."""

    def __init__(self, window: DraggableWindow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._drag_offset: QPoint | None = None
        self.setMouseTracking(True)
        self.setCursor(Qt.SizeAllCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            global_position = event.globalPosition().toPoint()
            if self._window._try_start_resize(global_position):
                self._drag_offset = None
            else:
                self._drag_offset = (
                    global_position - self._window.frameGeometry().topLeft()
                )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        global_position = event.globalPosition().toPoint()
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self._window.move(global_position - self._drag_offset)
            event.accept()
            return
        if not (event.buttons() & Qt.LeftButton):
            edges = self._window._edges_for_global(global_position)
            cursor = (
                self._window._cursor_for_edges(edges)
                if edges is not None
                else Qt.SizeAllCursor
            )
            self.setCursor(cursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None and event.button() == Qt.LeftButton:
            self._drag_offset = None
            self._window._persist_geometry()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self._drag_offset = None
        self._window._toggle_bar()
        event.accept()


class HudBar(DragBar):
    """Thanh bar glass: thêm vệt sáng 1px ở mép trên cho cảm giác vật liệu thật."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        gradient = QLinearGradient(
            rect.topLeft(), QPointF(rect.left(), rect.bottom())
        )
        gradient.setColorAt(0.0, QColor(255, 255, 255, 30))
        gradient.setColorAt(0.55, QColor(255, 255, 255, 0))
        gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QBrush(gradient), 1.0))
        painter.drawRoundedRect(rect, 13.0, 13.0)
        painter.end()


class BusyBar(QWidget):
    """Vạch tiến trình vô định 2px: chỉ chạy khi app đang xử lý."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFixedHeight(2)
        self._phase = 0.0
        self._active = False
        self._timer = QTimer(self)
        # 25 fps là đủ mượt cho một vạch chạy, và bar có drop shadow nên mỗi lần
        # vẽ lại tốn hơn bình thường — không cần 60 fps.
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        if active:
            self._phase = 0.0
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.018) % 1.0
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._active or self.width() <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        width = self.width()
        span = max(48.0, width * 0.28)
        # Đi hết chiều rộng rồi lặp lại, luôn dính hai mép để không "nhảy".
        left = -span + (width + span) * self._phase
        gradient = QLinearGradient(left, 0.0, left + span, 0.0)
        accent = QColor(TOKENS["ACCENT"])
        edge = QColor(accent)
        edge.setAlpha(0)
        gradient.setColorAt(0.0, edge)
        gradient.setColorAt(0.5, accent)
        gradient.setColorAt(1.0, edge)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(QRectF(left, 0.0, span, self.height()), 1.0, 1.0)
        painter.end()


class StatusPill(QWidget):
    """Chấm trạng thái + mô tả ngắn ngay trên bar (trước đây chỉ có tooltip)."""

    MAX_WIDTH = 260

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._text = ""
        self._state = "ready"
        self._pulse = 0.0
        self._font = QFont()
        self._font.setPointSizeF(9.0)
        self._timer = QTimer(self)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._tick)
        self.setFixedHeight(24)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def set_state(self, text: str, state: str) -> None:
        self._text = (text or "").replace("\n", " ").strip()
        self._state = state if state in _STATE_COLORS else "ready"
        if self._state == "busy":
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self._pulse = 0.0
        self.updateGeometry()
        self.update()

    def _tick(self) -> None:
        self._pulse = (self._pulse + 0.14) % (math.pi * 2)
        self.update()

    def _text_width(self) -> int:
        return QFontMetrics(self._font).horizontalAdvance(self._text)

    def sizeHint(self) -> QSize:
        if not self._text:
            return QSize(0, 24)
        return QSize(min(self.MAX_WIDTH, 36 + self._text_width()), 24)

    def minimumSizeHint(self) -> QSize:
        return QSize(0 if not self._text else 34, 24)

    def paintEvent(self, _event) -> None:
        if not self._text or self.width() < 20:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        rect = QRectF(self.rect())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 12))
        painter.drawRoundedRect(rect, 8.0, 8.0)

        dot = QColor(_STATE_COLORS[self._state])
        if self._state == "busy":
            dot.setAlphaF(0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._pulse)))
        center_y = rect.center().y()
        painter.setBrush(dot)
        painter.drawEllipse(QRectF(9.0, center_y - 3.5, 7.0, 7.0))

        painter.setFont(self._font)
        painter.setPen(QColor(TOKENS["TEXT_DIM"]))
        text_rect = rect.adjusted(23.0, 0.0, -10.0, 0.0)
        metrics = QFontMetrics(self._font)
        painter.drawText(
            text_rect,
            Qt.AlignVCenter | Qt.AlignLeft,
            metrics.elidedText(self._text, Qt.ElideRight, int(text_rect.width())),
        )
        painter.end()


class HudTextView(QWidget):
    """Vẽ bản dịch với font, viền và màu nền do người dùng chọn."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._text = ""
        self._placeholder = ""
        self._font_family = HUD_STYLE_DEFAULTS["hud_font_family"]
        self._font_size = HUD_STYLE_DEFAULTS["hud_font_size"]
        self._color = QColor(HUD_STYLE_DEFAULTS["hud_text_color"])
        self._border_width = HUD_STYLE_DEFAULTS["hud_border_width"]
        self._border_color = QColor(HUD_STYLE_DEFAULTS["hud_border_color"])
        self._background_color = QColor(HUD_STYLE_DEFAULTS["hud_background_color"])
        self._shadow_radius = HUD_STYLE_DEFAULTS["hud_shadow_radius"]
        self._shadow_color = QColor(HUD_STYLE_DEFAULTS["hud_shadow_color"])

    def setText(self, text: str) -> None:
        self._text = text or ""
        self.update()

    def text(self) -> str:
        return self._text

    def set_placeholder(self, text: str) -> None:
        """Gợi ý hiện khi chưa có bản dịch — cho biết vùng này dùng để làm gì."""
        self._placeholder = text or ""
        self.update()

    def apply_style(
        self,
        font_family: str,
        font_size: int,
        text_color: str,
        border_width: float,
        border_color: str,
        background_color: str,
        shadow_radius: float = 0.0,
        shadow_color: str = "#00000000",
    ) -> None:
        self._font_family = font_family or "Yu Gothic"
        self._font_size = max(8, int(font_size))
        self._color = QColor(text_color)
        self._border_width = max(0.0, float(border_width))
        self._border_color = QColor(border_color)
        self._background_color = QColor(background_color)
        self._shadow_radius = max(0.0, float(shadow_radius))
        self._shadow_color = QColor(shadow_color)
        self.update()

    def _paint_placeholder(self, painter: QPainter) -> None:
        """Viên gợi ý tối, mờ — đọc được trên mọi nền desktop mà không ồn ào."""
        font = QFont()
        font.setPointSizeF(9.5)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        text = metrics.elidedText(
            self._placeholder, Qt.ElideRight, max(80, self.width() - 40)
        )
        width = metrics.horizontalAdvance(text) + 26
        height = metrics.height() + 12
        rect = QRectF(2.0, 2.0, width, height)
        path = QPainterPath()
        path.addRoundedRect(rect, height / 2, height / 2)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.fillPath(path, QColor(12, 14, 19, 168))
        painter.setPen(QPen(QColor(255, 255, 255, 26), 1.0))
        painter.drawPath(path)
        painter.setPen(QColor(TOKENS["TEXT_MUTED"]))
        painter.drawText(rect, Qt.AlignCenter, text)

    def _document(
        self, font: QFont, color: QColor, width: int, *, outline: bool
    ) -> QTextDocument:
        """Layout bản dịch một lần, dùng lại được cho cả bóng và chữ chính."""
        document = QTextDocument()
        document.setDocumentMargin(0)
        document.setDefaultFont(font)
        option = document.defaultTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        document.setDefaultTextOption(option)
        text_format = QTextCharFormat()
        text_format.setFont(font)
        text_format.setForeground(color)
        if outline and self._border_width:
            pen = QPen(self._border_color)
            pen.setWidthF(self._border_width)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            text_format.setTextOutline(pen)
        cursor = QTextCursor(document)
        cursor.insertText(self._text, text_format)
        document.setTextWidth(width)
        return document

    def _shadow_offsets(self) -> list[tuple[float, float]]:
        """Tâm + vòng mẫu cân xứng để tạo glow, không làm chữ lệch như bóng đổ."""
        spread = self._shadow_radius * 0.50
        offsets = [(0.0, 0.0)]
        for index in range(8):
            angle = math.pi * 2 * index / 8
            offsets.append((math.cos(angle) * spread, math.sin(angle) * spread))
        return offsets

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self._background_color.alpha() > 0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._background_color)
            painter.drawRoundedRect(self.rect(), 8, 8)
        if not self._text:
            if self._placeholder:
                self._paint_placeholder(painter)
            painter.end()
            return
        rect = self.rect().adjusted(3, 2, -3, -2)
        font = QFont(self._font_family, self._font_size)
        font.setWeight(QFont.Bold)
        content = QRectF(0, 0, rect.width(), rect.height())
        # Vẽ chữ qua lớp ARGB trong suốt: nếu vẽ thẳng lên nền đục (người dùng chọn
        # màu nền) thì Windows bật ClearType và để lại riềm đỏ/xanh quanh nét chữ.
        layer = alpha_text_layer(self.size())
        target = QPainter(layer) if layer is not None else painter
        target.setRenderHint(QPainter.Antialiasing, True)
        target.setRenderHint(QPainter.TextAntialiasing, True)

        if self._shadow_radius > 0 and self._shadow_color.alpha() > 0:
            # Một document bóng, vẽ lại ở nhiều vị trí → xấp xỉ blur rất rẻ.
            shadow = self._document(
                font, self._shadow_color, rect.width(), outline=False
            )
            offsets = self._shadow_offsets()
            target.save()
            target.setOpacity(min(1.0, 2.0 / len(offsets)))
            for dx, dy in offsets:
                target.save()
                target.translate(rect.topLeft().x() + dx, rect.topLeft().y() + dy)
                shadow.drawContents(target, content)
                target.restore()
            target.restore()

        document = self._document(font, self._color, rect.width(), outline=True)
        target.save()
        target.translate(rect.topLeft())
        document.drawContents(target, content)
        target.restore()
        if layer is not None:
            target.end()
            painter.drawImage(0, 0, layer)


def paint_checkerboard(
    painter: QPainter, rect: QRectF, cell: int = 7, radius: float = 0.0
) -> None:
    """Ô bàn cờ mờ phía sau màu có alpha — để thấy rõ phần trong suốt."""
    painter.save()
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.setClipPath(path)
    painter.fillRect(rect, QColor("#232833"))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#1a1e26"))
    rows = int(rect.height() // cell) + 1
    columns = int(rect.width() // cell) + 1
    for row in range(rows):
        for column in range(columns):
            if (row + column) % 2:
                continue
            painter.drawRect(
                QRectF(
                    rect.left() + column * cell,
                    rect.top() + row * cell,
                    cell,
                    cell,
                )
            )
    painter.restore()


class ColorButton(QPushButton):
    """Nút chọn màu: vẽ ô màu thật, có bàn cờ khi màu trong suốt."""

    picked = Signal()
    previewed = Signal()

    def __init__(
        self,
        color: str,
        parent: QWidget | None = None,
        *,
        allow_alpha: bool = False,
    ) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._allow_alpha = allow_alpha
        self.setCursor(Qt.PointingHandCursor)
        if allow_alpha:
            self.setFixedHeight(32)
            self.setMinimumWidth(142)
            self.setMaximumWidth(190)
        else:
            self.setFixedSize(64, 30)
        self.clicked.connect(self._pick)
        self._sync()

    def color_hex(self) -> str:
        return self._color.name()

    def color_value(self) -> str:
        if self._allow_alpha:
            return self._color.name(QColor.NameFormat.HexArgb)
        return self.color_hex()

    def set_color(self, color: str) -> None:
        """Đặt màu từ code (khôi phục mặc định) — không phát signal."""
        parsed = QColor(color)
        if parsed.isValid():
            self._color = parsed
            self._sync()

    def _sync(self) -> None:
        alpha = self._color.alpha()
        if self._allow_alpha:
            opacity = round(alpha / 255 * 100)
            self.setText(
                "Trong suốt"
                if alpha == 0
                else f"{self._color.name().upper()} · {opacity}%"
            )
        else:
            self.setText("")
        self.setToolTip(f"{self.color_value().upper()} — bấm để chọn màu")
        self.update()

    def _ink(self) -> QColor:
        """Màu chữ tương phản với ô màu phía sau."""
        if self._color.alpha() < 120:
            return QColor(TOKENS["TEXT"])
        luminance = (
            self._color.red() * 0.299
            + self._color.green() * 0.587
            + self._color.blue() * 0.114
        )
        return QColor("#0a0a0c") if luminance > 150 else QColor("#fafafa")

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = 8.0
        if self._color.alpha() < 255:
            paint_checkerboard(painter, rect, radius=radius)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawRoundedRect(rect, radius, radius)

        border = QColor(TOKENS["LINE_HI"])
        if self.isDown():
            border = QColor(TOKENS["ACCENT"])
        elif self.underMouse() or self.hasFocus():
            border = QColor(TOKENS["ACCENT_LINE"])
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)

        text = self.text()
        if text:
            font = QFont()
            font.setPointSizeF(8.5)
            font.setWeight(QFont.Medium)
            painter.setFont(font)
            painter.setPen(self._ink())
            painter.drawText(rect, Qt.AlignCenter, text)
        painter.end()

    def _pick(self) -> None:
        original = QColor(self._color)
        dialog = QColorDialog(self._color, self)
        dialog.setWindowTitle("Chọn màu")
        dialog.setOption(
            QColorDialog.ColorDialogOption.ShowAlphaChannel, self._allow_alpha
        )
        dialog.currentColorChanged.connect(self._preview)
        if dialog.exec():
            chosen = dialog.currentColor()
            if chosen.isValid():
                self._color = chosen
                self._sync()
                self.picked.emit()
            return
        self._color = original
        self._sync()
        self.previewed.emit()

    def _preview(self, color: QColor) -> None:
        if not color.isValid():
            return
        self._color = color
        self._sync()
        self.previewed.emit()


class Card(QFrame):
    """Thẻ cài đặt: tiêu đề tuỳ chọn + các hàng "nhãn · gợi ý · điều khiển"."""

    ROW_CONTROL_WIDTH = 210

    def __init__(
        self,
        title: str = "",
        hint: str = "",
        parent: QWidget | None = None,
        *,
        sunken: bool = False,
        trailing: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("cardSunken" if sunken else "card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(15, 13, 15, 13)
        self._layout.setSpacing(0)
        self._has_content = False
        if title or trailing is not None:
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(8)
            titles = QVBoxLayout()
            titles.setContentsMargins(0, 0, 0, 0)
            titles.setSpacing(2)
            if title:
                label = QLabel(title)
                label.setObjectName("cardTitle")
                titles.addWidget(label)
            if hint:
                subtitle = QLabel(hint)
                subtitle.setObjectName("cardHint")
                subtitle.setWordWrap(True)
                titles.addWidget(subtitle)
            header.addLayout(titles, 1)
            if trailing is not None:
                header.addWidget(trailing, 0, Qt.AlignTop)
            self._layout.addLayout(header)
            self._has_content = True

    def _spaced(self) -> None:
        """Chèn khoảng/kẻ ngăn giữa các khối trong thẻ."""
        if self._has_content:
            self._layout.addSpacing(11)
        self._has_content = True

    def add_divider(self) -> None:
        divider = QFrame()
        divider.setObjectName("rowDivider")
        divider.setFixedHeight(1)
        self._layout.addSpacing(11)
        self._layout.addWidget(divider)
        self._has_content = True

    def add_row(
        self,
        label: str,
        control: QWidget,
        hint: str = "",
        *,
        control_width: int | None = None,
    ) -> QWidget:
        """Một hàng cài đặt; trả về widget hàng để ẩn/hiện theo ngữ cảnh."""
        if self._has_content:
            self.add_divider()
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 11, 0, 0)
        layout.setSpacing(14)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(2)
        name = QLabel(label)
        name.setObjectName("rowLabel")
        texts.addWidget(name)
        if hint:
            note = QLabel(hint)
            note.setObjectName("rowHint")
            note.setWordWrap(True)
            texts.addWidget(note)
        layout.addLayout(texts, 1)
        width = self.ROW_CONTROL_WIDTH if control_width is None else control_width
        if width and control.maximumWidth() >= width:
            control.setMinimumWidth(width)
        layout.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
        self._layout.addWidget(row)
        self._has_content = True
        return row

    def add_block(self, widget: QWidget) -> QWidget:
        """Khối tự do (hàng nút, gợi ý dài…) chiếm hết bề rộng thẻ."""
        self._spaced()
        self._layout.addWidget(widget)
        return widget

    def add_layout(self, layout) -> None:
        self._spaced()
        self._layout.addLayout(layout)


class CheckerFrame(QFrame):
    """Nền bàn cờ cho khung xem trước — thấy ngay phần nền trong suốt."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("previewSurface")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        paint_checkerboard(
            painter, QRectF(self.rect()).adjusted(1, 1, -1, -1), cell=8, radius=11.0
        )
        painter.end()
        super().paintEvent(event)
