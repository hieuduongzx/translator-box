"""Các widget tái sử dụng trong HUD và cửa sổ cài đặt."""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)
from PySide6.QtWidgets import (
    QColorDialog,
    QFrame,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from ui_utils import _combo_from_event, _fmt_hotkey, _make_icon


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

    def __init__(self, combo: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("hotkey")
        self.setReadOnly(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Bấm rồi nhấn tổ hợp phím. Esc: huỷ · Del: tắt phím này.")
        self._combo = (combo or "").strip().lower()
        self._recording = False
        self._render()

    def combo(self) -> str:
        return self._combo

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
            self._combo = ""
            self.clearFocus()
            return
        combo = _combo_from_event(event)
        if combo:
            self._combo = combo
            self.clearFocus()


class BarButton(QPushButton):
    """Nút icon nhỏ trên thanh công cụ HUD."""

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("barBtn")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(28, 28)
        self.setIconSize(QSize(16, 16))
        self._icon_off = _make_icon(kind, QColor("#c7ccd6"))
        self._icon_on = _make_icon(kind, QColor("#ffffff"))
        self.setIcon(self._icon_off)
        self.toggled.connect(self._sync_icon)

    def _sync_icon(self, checked: bool) -> None:
        self.setIcon(self._icon_on if checked else self._icon_off)


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


class HudTextView(QWidget):
    """Vẽ bản dịch với font, viền và màu nền do người dùng chọn."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._text = ""
        self._font_family = "Yu Gothic"
        self._font_size = 16
        self._color = QColor("#000000")
        self._border_width = 1.0
        self._border_color = QColor("#ffffff")
        self._background_color = QColor("#00000000")

    def setText(self, text: str) -> None:
        self._text = text or ""
        self.update()

    def apply_style(
        self,
        font_family: str,
        font_size: int,
        text_color: str,
        border_width: float,
        border_color: str,
        background_color: str,
    ) -> None:
        self._font_family = font_family or "Yu Gothic"
        self._font_size = max(8, int(font_size))
        self._color = QColor(text_color)
        self._border_width = max(0.0, float(border_width))
        self._border_color = QColor(border_color)
        self._background_color = QColor(background_color)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self._background_color.alpha() > 0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._background_color)
            painter.drawRoundedRect(self.rect(), 8, 8)
        if not self._text:
            painter.end()
            return
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        rect = self.rect().adjusted(3, 2, -3, -2)
        font = QFont(self._font_family, self._font_size)
        font.setWeight(QFont.DemiBold)

        document = QTextDocument()
        document.setDocumentMargin(0)
        document.setDefaultFont(font)
        option = document.defaultTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        document.setDefaultTextOption(option)
        text_format = QTextCharFormat()
        text_format.setFont(font)
        text_format.setForeground(self._color)
        if self._border_width:
            outline = QPen(self._border_color)
            outline.setWidthF(self._border_width)
            outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            text_format.setTextOutline(outline)
        cursor = QTextCursor(document)
        cursor.insertText(self._text, text_format)
        document.setTextWidth(rect.width())

        painter.save()
        painter.translate(rect.topLeft())
        document.drawContents(
            painter,
            QRectF(0, 0, rect.width(), rect.height()),
        )
        painter.restore()


class ColorButton(QPushButton):
    """Nút chọn màu có preview."""

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
        if allow_alpha:
            self.setFixedHeight(30)
            self.setMinimumWidth(126)
            self.setMaximumWidth(180)
        else:
            self.setFixedSize(52, 26)
        self.clicked.connect(self._pick)
        self._sync()

    def color_hex(self) -> str:
        return self._color.name()

    def color_value(self) -> str:
        if self._allow_alpha:
            return self._color.name(QColor.NameFormat.HexArgb)
        return self.color_hex()

    def _sync(self) -> None:
        alpha = self._color.alpha()
        if self._allow_alpha:
            opacity = round(alpha / 255 * 100)
            self.setText(
                "Trong suốt"
                if alpha == 0
                else f"{self._color.name().upper()} · {opacity}%"
            )
            luminance = (
                self._color.red() * 0.299
                + self._color.green() * 0.587
                + self._color.blue() * 0.114
            )
            foreground = "#09090b" if alpha > 150 and luminance > 150 else "#f4f4f5"
        else:
            self.setText("")
            foreground = "#f4f4f5"
        self.setStyleSheet(
            f"background: rgba({self._color.red()}, {self._color.green()}, "
            f"{self._color.blue()}, {alpha}); color: {foreground}; "
            "border: 1px solid #3f3f46; border-radius: 6px;"
        )

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
