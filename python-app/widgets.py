"""Các widget tái sử dụng trong HUD và cửa sổ cài đặt."""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Protocol, Sequence

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config import HUD_STYLE_DEFAULTS
from theme import TOKENS
from ui_utils import (
    ICON_ACTIVE,
    AlphaLayerCache,
    _combo_from_event,
    _fmt_hotkey,
    _state_icon,
)

# Trạng thái hợp lệ của chấm trạng thái trên bar.
_STATUS_STATES = ("ready", "ok", "busy", "error")

# Font có glyph CJK cho transcript; tra một lần thay vì dựng dict mỗi block.
_CJK_FONT_FAMILIES = {
    "ja": "Yu Gothic",
    "ko": "Malgun Gothic",
    "zh": "Microsoft YaHei UI",
}


@lru_cache(maxsize=4)
def _checker_brush(cell: int) -> QBrush:
    """Brush lát 2×2 ô bàn cờ — một lệnh fill thay cho hàng nghìn drawRect."""
    tile = QPixmap(cell * 2, cell * 2)
    tile.fill(QColor("#27272a"))
    painter = QPainter(tile)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#18181b"))
    painter.drawRect(0, 0, cell, cell)
    painter.drawRect(cell, cell, cell, cell)
    painter.end()
    return QBrush(tile)


class DraggableWindow(Protocol):
    """Giao tiếp tối thiểu mà thanh kéo cần từ HUD."""

    def _try_start_resize(self, global_position: QPoint) -> bool: ...
    def _move_with_snap(self, position: QPoint, pointer: QPoint) -> None: ...

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


class BarComboBox(QComboBox):
    """Dropdown của HUD mở sát bên dưới thay vì phủ lên control hiện tại."""

    MAX_VISIBLE_ITEMS = 8

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMaxVisibleItems(self.MAX_VISIBLE_ITEMS)
        self.view().setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    def showPopup(self) -> None:
        super().showPopup()
        popup = self.view().window()
        row_height = max(22, self.view().sizeHintForRow(0))
        visible_rows = max(1, min(self.count(), self.MAX_VISIBLE_ITEMS))
        popup_height = row_height * visible_rows + 26
        popup_width = max(self.width(), self.view().minimumWidth(), popup.width())

        anchor = self.mapToGlobal(QPoint(0, self.height() + 2))
        screen = QGuiApplication.screenAt(anchor)
        if screen is None:
            popup.setGeometry(anchor.x(), anchor.y(), popup_width, popup_height)
            return

        available = screen.availableGeometry()
        x = min(
            max(anchor.x(), available.left()),
            max(available.left(), available.right() - popup_width + 1),
        )
        space_below = available.bottom() - anchor.y() + 1
        space_above = self.mapToGlobal(QPoint(0, 0)).y() - available.top() - 2
        if space_below >= popup_height or space_below >= space_above:
            y = anchor.y()
            height = min(popup_height, max(row_height + 16, space_below))
        else:
            height = min(popup_height, max(row_height + 16, space_above))
            y = self.mapToGlobal(QPoint(0, 0)).y() - height - 2
        popup.setGeometry(x, y, popup_width, height)


class BarButton(QPushButton):
    """Nút icon nhỏ trên thanh công cụ HUD.

    Icon dùng QIcon nhiều mode/state nên Qt tự đổi màu glyph khi hover, khi nút
    được check hoặc khi bị vô hiệu hoá.
    """

    def __init__(
        self,
        kind: str,
        parent: QWidget | None = None,
        *,
        emphasized: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("barBtn")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(28, 28)
        self.setIconSize(QSize(17, 17))
        self.setIcon(_state_icon(kind, idle_color=ICON_ACTIVE if emphasized else None))


class BarMenuButton(QPushButton):
    """Nút mở một nhóm lệnh dịch; menu ưu tiên mở ngược lên trên HUD."""

    def __init__(self, kind: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(label, parent)
        self.setObjectName("barAction")
        self.setProperty("live", False)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(28)
        self.setIconSize(QSize(16, 16))
        self.setIcon(_state_icon(kind))
        self._label = label
        self._menu: QMenu | None = None
        self.clicked.connect(self._toggle_menu)

    def attach_menu(self, menu: QMenu) -> None:
        self._menu = menu
        menu.aboutToHide.connect(self._menu_hidden)

    def set_live(self, live: bool) -> None:
        """Tô accent khi nhóm đang có một phiên Live chạy."""
        if bool(self.property("live")) == live:
            return
        self.setProperty("live", live)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_compact(self, compact: bool) -> None:
        """Bỏ nhãn, chỉ giữ icon khi HUD quá hẹp (tooltip vẫn mô tả đủ)."""
        wanted = "" if compact else self._label
        if self.text() == wanted:
            return
        self.setText(wanted)

    def _toggle_menu(self, checked: bool) -> None:
        if self._menu is None:
            self.setChecked(False)
            return
        if not checked:
            self._menu.hide()
            return
        self._menu.ensurePolished()
        size = self._menu.sizeHint()
        top_left = self.mapToGlobal(QPoint(0, 0))
        screen = QGuiApplication.screenAt(top_left)
        if screen is None:
            self._menu.popup(QPoint(top_left.x(), top_left.y() - size.height() - 4))
            return
        available = screen.availableGeometry()
        x = min(
            max(top_left.x(), available.left()),
            max(available.left(), available.right() - size.width() + 1),
        )
        above_y = top_left.y() - size.height() - 4
        y = (
            above_y
            if above_y >= available.top()
            else self.mapToGlobal(QPoint(0, self.height() + 4)).y()
        )
        self._menu.popup(QPoint(x, y))

    def _menu_hidden(self) -> None:
        self.setChecked(False)


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
            self._window._move_with_snap(
                global_position - self._drag_offset, global_position
            )
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
    """Thanh bar của HUD: nền và viền do QSS lo, widget chỉ nhận kéo/resize."""


class BusyBar(QWidget):
    """Vạch tiến trình vô định 2px: beam accent đặc, không gradient."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFixedHeight(2)
        self._phase = 0.0
        self._active = False
        self._beam = QColor(TOKENS["FOCUS"])
        self._timer = QTimer(self)
        # 20 fps đủ mượt cho một vạch 2px và rẻ hơn 25 fps cũ khi live chạy dài.
        self._timer.setInterval(50)
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
        self.setVisible(active)
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.022) % 1.0
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._active or self.width() <= 0:
            return
        painter = QPainter(self)
        width = self.width()
        span = max(48.0, width * 0.22)
        left = -span + (width + span) * self._phase
        painter.fillRect(QRectF(left, 0.0, span, self.height()), self._beam)
        painter.end()


class StatusStrip(QWidget):
    """Chấm trạng thái + mô tả ngắn, dựng bằng widget thật (không tự vẽ).

    Bản trước vẽ tay cả viên pill kèm QTimer nhấp nháy 90 ms — tức repaint liên
    tục suốt phiên live chỉ để làm một chấm mờ dần. Ở đây chấm là QFrame do QSS
    tô màu theo property `state`, chữ là QLabel elide bằng chính Qt: không timer,
    không paintEvent, và đổi trạng thái chỉ tốn một lần polish.
    """

    MAX_WIDTH = 300
    DOT_SIZE = 6
    SPACING = 7

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(self.SPACING)
        self._dot = QFrame(self)
        self._dot.setObjectName("statusDot")
        self._dot.setFixedSize(self.DOT_SIZE, self.DOT_SIZE)
        self._dot.setProperty("state", "ready")
        self._label = QLabel(self)
        self._label.setObjectName("statusText")
        # Ignored theo trục ngang: nhãn nhận đúng chỗ mà `sizeHint` của cả dải xin
        # được, và co về 0 khi bar hẹp thay vì đẩy bề rộng tối thiểu của bar lên.
        self._label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self._dot, 0, Qt.AlignVCenter)
        layout.addWidget(self._label, 1, Qt.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._text = ""
        self._state = "ready"

    def sizeHint(self) -> QSize:
        height = max(self.DOT_SIZE, self._label.sizeHint().height())
        if not self._text:
            return QSize(self.DOT_SIZE, height)
        text_width = self._label.fontMetrics().horizontalAdvance(self._text)
        return QSize(
            min(self.MAX_WIDTH, self.DOT_SIZE + self.SPACING + text_width), height
        )

    def minimumSizeHint(self) -> QSize:
        return QSize(self.DOT_SIZE, max(self.DOT_SIZE, self._label.sizeHint().height()))

    def set_state(self, text: str, state: str) -> None:
        text = (text or "").replace("\n", " ").strip()
        state = state if state in _STATUS_STATES else "ready"
        if text == self._text and state == self._state:
            return
        self._text = text
        if state != self._state:
            self._state = state
            self._dot.setProperty("state", state)
            self._dot.style().unpolish(self._dot)
            self._dot.style().polish(self._dot)
        self.updateGeometry()
        self._sync_elide()

    def _sync_elide(self) -> None:
        available = self._label.width()
        if not self._text:
            self._label.clear()
            return
        if available <= 0:
            self._label.setText(self._text)
            return
        metrics = self._label.fontMetrics()
        self._label.setText(metrics.elidedText(self._text, Qt.ElideRight, available))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_elide()


class TranscriptBlockView(Protocol):
    kind: str
    text: str
    language: str | None
    speaker: str | None
    is_final: bool


class HudTextView(QWidget):
    """Vẽ bản dịch với font, viền và màu nền do người dùng chọn.

    Layout chữ (`QTextDocument`) và lớp ARGB trung gian đều được cache: nội dung
    chỉ đổi khi có bản dịch mới, còn `paintEvent` thì Qt gọi lại vì rất nhiều lý
    do khác (di chuyển cửa sổ, vùng bị che, đổi focus). Dựng lại document mỗi lần
    vẽ là chỗ tốn nhất của khung dịch, nhất là ở transcript realtime.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._text = ""
        self._image: QImage | None = None
        self._transcript_blocks: tuple[TranscriptBlockView, ...] = ()
        self._transcript_display_mode = "bilingual"
        self._transcript_alignment = "center"
        self._font_family = HUD_STYLE_DEFAULTS["hud_font_family"]
        self._font_size = HUD_STYLE_DEFAULTS["hud_font_size"]
        self._color = QColor(HUD_STYLE_DEFAULTS["hud_text_color"])
        self._border_width = HUD_STYLE_DEFAULTS["hud_border_width"]
        self._border_color = QColor(HUD_STYLE_DEFAULTS["hud_border_color"])
        self._background_color = QColor(HUD_STYLE_DEFAULTS["hud_background_color"])
        self._background_enabled = HUD_STYLE_DEFAULTS["hud_background_enabled"]
        self._shadow_radius = HUD_STYLE_DEFAULTS["hud_shadow_radius"]
        self._shadow_color = QColor(HUD_STYLE_DEFAULTS["hud_shadow_color"])
        self._layer_cache = AlphaLayerCache()
        self._cached_width = -1
        self._cached_main: QTextDocument | None = None
        self._cached_shadow: QTextDocument | None = None
        self._cached_outline: QTextDocument | None = None

    def _invalidate(self) -> None:
        """Bỏ layout đã cache; lần vẽ tới sẽ dựng lại đúng một lần."""
        self._cached_main = None
        self._cached_shadow = None
        self._cached_outline = None
        self._cached_width = -1
        self.update()

    def setText(self, text: str) -> None:
        self._text = text or ""
        self._image = None
        self._transcript_blocks = ()
        self.setAccessibleDescription(
            "Nội dung bản dịch dạng văn bản" if self._text else "Khung dịch đang trống"
        )
        self._invalidate()

    def text(self) -> str:
        return self._text

    def set_transcript(
        self,
        blocks: Sequence[TranscriptBlockView],
        *,
        display_mode: str,
        alignment: str,
    ) -> None:
        """Hiện unified transcript stream với phân cấp lời gốc/bản dịch."""
        self._transcript_blocks = tuple(blocks)
        self._transcript_display_mode = (
            display_mode
            if display_mode in {"bilingual", "translation"}
            else "bilingual"
        )
        self._transcript_alignment = (
            alignment if alignment in {"left", "center", "right"} else "center"
        )
        self._text = self._transcript_plain_text()
        self._image = None
        self.setAccessibleDescription(
            "Transcript audio song ngữ"
            if self._transcript_display_mode == "bilingual"
            else "Bản dịch audio"
        )
        self._invalidate()

    def _visible_blocks(self) -> list[TranscriptBlockView]:
        if self._transcript_display_mode == "bilingual":
            return list(self._transcript_blocks)
        return [
            block for block in self._transcript_blocks if block.kind == "translation"
        ]

    def _transcript_plain_text(self) -> str:
        parts: list[str] = []
        current_speaker: str | None = None
        visible = self._visible_blocks()
        for block in visible:
            if block.speaker is not None and block.speaker != current_speaker:
                if parts:
                    parts.append("")
                parts.append(f"Người nói {block.speaker}")
                current_speaker = block.speaker
            parts.append(block.text.strip())
        if visible and not visible[-1].is_final:
            parts[-1] += " ▌"
        return "\n".join(part for part in parts if part).strip()

    def setImage(self, image: QImage) -> None:
        """Hiện ảnh đã dịch trong chính vùng trong suốt của HUD."""
        self._image = None if image.isNull() else image.copy()
        self._text = ""
        self._transcript_blocks = ()
        self.setAccessibleDescription(
            "Ảnh đã dịch" if self._image is not None else "Khung dịch đang trống"
        )
        self._invalidate()

    def image(self) -> QImage:
        return self._image.copy() if self._image is not None else QImage()

    def has_content(self) -> bool:
        return bool(self._text.strip()) or self._image is not None

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
        background_enabled: bool = True,
    ) -> None:
        self._font_family = font_family or "Yu Gothic"
        self._font_size = max(8, int(font_size))
        self._color = QColor(text_color)
        self._border_width = max(0.0, float(border_width))
        self._border_color = QColor(border_color)
        self._background_color = QColor(background_color)
        self._background_enabled = bool(background_enabled)
        self._shadow_radius = max(0.0, float(shadow_radius))
        self._shadow_color = QColor(shadow_color)
        self._invalidate()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Layout phụ thuộc bề rộng nên chỉ cần bỏ cache khi bề rộng thật sự đổi.
        if event.oldSize().width() != event.size().width():
            self._invalidate()

    def _outline_pen(self) -> QPen | None:
        if not self._border_width:
            return None
        pen = QPen(self._border_color)
        pen.setWidthF(self._border_width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    def _document(
        self, font: QFont, color: QColor, width: int, *, outline: bool, fill: bool = True
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
        # Lớp viền chỉ tô nét (foreground trong suốt); lớp chữ chỉ tô đặc.
        text_format.setForeground(color if fill else QColor(0, 0, 0, 0))
        pen = self._outline_pen() if outline else None
        if pen is not None:
            text_format.setTextOutline(pen)
        cursor = QTextCursor(document)
        cursor.insertText(self._text, text_format)
        document.setTextWidth(width)
        return document

    def _transcript_document(
        self, font: QFont, color: QColor, width: int, *, outline: bool, fill: bool = True
    ) -> QTextDocument:
        """Layout caption: lời gốc nhỏ/mờ, bản dịch lớn ở dòng bên dưới."""
        document = QTextDocument()
        document.setDocumentMargin(0)
        option = document.defaultTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        document.setDefaultTextOption(option)

        alignment = {
            "left": Qt.AlignLeft,
            "center": Qt.AlignHCenter,
            "right": Qt.AlignRight,
        }[self._transcript_alignment]
        block_format = QTextBlockFormat()
        block_format.setAlignment(alignment)
        block_format.setBottomMargin(3.0)
        outline_pen = self._outline_pen() if outline else None

        def text_format(
            current_font: QFont, current_color: QColor, *, with_outline: bool
        ) -> QTextCharFormat:
            result = QTextCharFormat()
            result.setFont(current_font)
            result.setForeground(current_color if fill else QColor(0, 0, 0, 0))
            if with_outline and outline_pen is not None:
                result.setTextOutline(outline_pen)
            return result

        original_font = QFont(font)
        original_font.setPointSizeF(max(8.0, font.pointSizeF() * 0.72))
        original_font.setWeight(QFont.Medium)
        label_font = QFont(font)
        label_font.setPointSizeF(max(8.0, font.pointSizeF() * 0.5))
        label_font.setWeight(QFont.Medium)
        muted = QColor(color)
        muted.setAlphaF(max(0.28, color.alphaF() * 0.58))
        label_text_format = text_format(label_font, muted, with_outline=False)

        # Font thay thế cho chữ CJK: tính một lần thay vì mỗi block mỗi lần vẽ.
        speech_formats: dict[str, QTextCharFormat] = {}
        translation_formats: dict[str, QTextCharFormat] = {}

        def content_format(block: TranscriptBlockView) -> QTextCharFormat:
            language = (block.language or "").split("-", 1)[0].lower()
            is_speech = block.kind == "speech"
            cache = speech_formats if is_speech else translation_formats
            cached = cache.get(language)
            if cached is not None:
                return cached
            block_font = QFont(original_font if is_speech else font)
            family = _CJK_FONT_FAMILIES.get(language)
            if family is not None:
                block_font.setFamily(family)
            result = text_format(
                block_font,
                muted if is_speech else color,
                with_outline=not is_speech,
            )
            cache[language] = result
            return result

        visible = self._visible_blocks()
        cursor = QTextCursor(document)
        first_line = True
        current_speaker: str | None = None

        def begin_line(*, top_margin: float = 0.0) -> None:
            nonlocal first_line
            if not first_line:
                cursor.insertBlock()
            current_block = QTextBlockFormat(block_format)
            current_block.setTopMargin(top_margin)
            cursor.setBlockFormat(current_block)
            first_line = False

        last_index = len(visible) - 1
        for index, block in enumerate(visible):
            if block.speaker is not None and block.speaker != current_speaker:
                begin_line(top_margin=5.0 if not first_line else 0.0)
                cursor.insertText(f"Người nói {block.speaker}", label_text_format)
                current_speaker = block.speaker

            begin_line(top_margin=4.0 if block.kind == "translation" else 0.0)
            is_pending = index == last_index and not block.is_final
            cursor_text = " ▌" if is_pending else ""
            cursor.insertText(block.text.strip() + cursor_text, content_format(block))

        document.setTextWidth(width)
        return document

    def _content_document(
        self, font: QFont, color: QColor, width: int, *, outline: bool, fill: bool = True
    ) -> QTextDocument:
        if self._transcript_blocks:
            return self._transcript_document(
                font, color, width, outline=outline, fill=fill
            )
        return self._document(font, color, width, outline=outline, fill=fill)

    def _documents(
        self, font: QFont, width: int, *, with_shadow: bool
    ) -> tuple[QTextDocument, QTextDocument | None, QTextDocument | None]:
        """Layout đã cache cho (chữ chính, bóng, lớp viền) ở bề rộng `width`."""
        needs_outline = self._border_width > 0
        if self._cached_width == width and self._cached_main is not None:
            if (not with_shadow or self._cached_shadow is not None) and (
                not needs_outline or self._cached_outline is not None
            ):
                return self._cached_main, self._cached_shadow, self._cached_outline
        self._cached_width = width
        # Viền vẽ ở lớp riêng phía dưới, chữ tô đặc ở lớp trên. Nếu để Qt vừa viền
        # vừa tô trong cùng một lần, nét viền (canh giữa) ăn vào thân chữ — nét
        # mảnh CJK bị đứt, chữ trông "vỡ". Tách lớp giữ viền nằm ngoài nét chữ.
        self._cached_outline = (
            self._content_document(
                font, self._border_color, width, outline=True, fill=False
            )
            if needs_outline
            else None
        )
        self._cached_main = self._content_document(
            font, self._color, width, outline=False
        )
        self._cached_shadow = (
            self._content_document(font, self._shadow_color, width, outline=False)
            if with_shadow
            else None
        )
        return self._cached_main, self._cached_shadow, self._cached_outline

    def _document_top(self, document: QTextDocument, rect: QRectF) -> float:
        if not self._transcript_blocks:
            return rect.top()
        overflow = max(0.0, document.size().height() - rect.height())
        return rect.top() - overflow

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
        if self._background_enabled and self._background_color.alpha() > 0:
            painter.fillRect(self.rect(), self._background_color)
        if self._image is not None:
            available = self.rect().adjusted(3, 2, -3, -2)
            fitted = self._image.size()
            fitted.scale(available.size(), Qt.KeepAspectRatio)
            target = QRectF(
                available.center().x() - fitted.width() / 2,
                available.center().y() - fitted.height() / 2,
                fitted.width(),
                fitted.height(),
            )
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawImage(target, self._image)
            painter.end()
            return
        if not self._text:
            painter.end()
            return
        rect = self.rect().adjusted(3, 2, -3, -2)
        font = QFont(self._font_family, self._font_size)
        font.setWeight(QFont.Bold)
        with_shadow = self._shadow_radius > 0 and self._shadow_color.alpha() > 0
        document, shadow, outline = self._documents(
            font, rect.width(), with_shadow=with_shadow
        )
        # Vẽ chữ qua lớp ARGB trong suốt: nếu vẽ thẳng lên nền đục (người dùng chọn
        # màu nền) thì Windows bật ClearType và để lại riềm đỏ/xanh quanh nét chữ.
        layer = self._layer_cache.acquire(self.size())
        target = QPainter(layer) if layer is not None else painter
        target.setRenderHint(QPainter.Antialiasing, True)
        target.setRenderHint(QPainter.TextAntialiasing, True)

        if shadow is not None:
            # Một document bóng, vẽ lại ở nhiều vị trí → xấp xỉ blur rất rẻ.
            offsets = self._shadow_offsets()
            shadow_top = self._document_top(shadow, rect)
            target.save()
            target.setOpacity(min(1.0, 2.0 / len(offsets)))
            target.setClipRect(rect)
            for dx, dy in offsets:
                target.save()
                target.translate(rect.left() + dx, shadow_top + dy)
                shadow.drawContents(target)
                target.restore()
            target.restore()

        if outline is not None:
            # Lớp viền nằm dưới lớp chữ, nên thân chữ không bị nét viền ăn mất.
            # Mỗi lớp tự save/restore để trạng thái painter không rò sang lớp chữ.
            target.save()
            target.setClipRect(rect)
            target.translate(rect.left(), self._document_top(outline, rect))
            outline.drawContents(target)
            target.restore()
        target.save()
        target.setClipRect(rect)
        target.translate(rect.left(), self._document_top(document, rect))
        document.drawContents(target)
        target.restore()
        if layer is not None:
            target.end()
            painter.drawImage(0, 0, layer)


def paint_checkerboard(painter: QPainter, rect: QRectF, cell: int = 8) -> None:
    """Ô bàn cờ mờ phía sau màu có alpha — để thấy rõ phần trong suốt.

    Dùng một brush hoa văn lát 2×2 ô: Qt lặp nó trong một lệnh fill thay vì hàng
    nghìn `drawRect` như trước.
    """
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrushOrigin(rect.topLeft().toPoint())
    painter.fillRect(rect, _checker_brush(cell))
    painter.restore()


class ColorButton(QPushButton):
    """Nút chọn màu: vẽ ô màu thật, có bàn cờ khi màu trong suốt."""

    picked = Signal()
    previewed = Signal()
    RADIUS = 4.0

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
        return QColor(TOKENS["FOCUS_INK"]) if luminance > 150 else QColor(TOKENS["TEXT"])

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = self.RADIUS
        if self._color.alpha() < 255:
            painter.save()
            painter.setClipRect(rect)
            paint_checkerboard(painter, rect)
            painter.restore()
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawRoundedRect(rect, radius, radius)

        border = QColor(TOKENS["LINE_HI"])
        if self.isDown():
            border = QColor(TOKENS["FOCUS"])
        elif self.underMouse() or self.hasFocus():
            border = QColor(TOKENS["FOCUS_LINE"])
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)

        text = self.text()
        if text:
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
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(0)
        self._has_content = False
        self._row_leading: dict[QWidget, QWidget] = {}
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
            self._layout.addSpacing(12)
        self._has_content = True

    def add_divider(self) -> QWidget:
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 12, 0, 0)
        holder_layout.setSpacing(0)
        divider = QFrame()
        divider.setObjectName("rowDivider")
        divider.setFixedHeight(1)
        holder_layout.addWidget(divider)
        self._layout.addWidget(holder)
        self._has_content = True
        return holder

    def add_row(
        self,
        label: str,
        control: QWidget,
        hint: str = "",
        *,
        control_width: int | None = None,
    ) -> QWidget:
        """Một hàng cài đặt; trả về widget hàng để ẩn/hiện theo ngữ cảnh."""
        leading = self.add_divider() if self._has_content else None
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 12, 0, 0)
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
        if leading is not None:
            self._row_leading[row] = leading
        return row

    def set_row_visible(self, row: QWidget, visible: bool) -> None:
        """Ẩn cả hàng và kẻ ngăn đứng ngay trước hàng đó."""
        row.setVisible(visible)
        leading = self._row_leading.get(row)
        if leading is not None:
            leading.setVisible(visible)

    def add_block(self, widget: QWidget) -> QWidget:
        """Khối tự do (hàng nút, gợi ý dài…) chiếm hết bề rộng thẻ."""
        self._spaced()
        self._layout.addWidget(widget)
        return widget


class CodeField(QFrame):
    """Ô chỉ-đọc cho giá trị kỹ thuật (endpoint, repo) kèm nút copy."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("codeBlock")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._edit = QLineEdit(text)
        self._edit.setObjectName("codeField")
        self._edit.setReadOnly(True)
        self._edit.setCursorPosition(0)
        self._copy_btn = QPushButton("Copy")
        self._copy_btn.setObjectName("codeCopyBtn")
        self._copy_btn.setCursor(Qt.PointingHandCursor)
        self._copy_btn.setToolTip("Copy vào clipboard")
        self._copy_btn.clicked.connect(self._copy)
        layout.addWidget(self._edit, 1)
        layout.addWidget(self._copy_btn, 0)

        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.setInterval(1100)
        self._reset_timer.timeout.connect(lambda: self._copy_btn.setText("Copy"))

    def setText(self, text: str) -> None:
        self._edit.setText(text)
        self._edit.setCursorPosition(0)

    def text(self) -> str:
        return self._edit.text()

    def _copy(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is None or not self._edit.text():
            return
        clipboard.setText(self._edit.text())
        self._copy_btn.setText("Đã copy")
        self._reset_timer.start()


class CheckerFrame(QFrame):
    """Nền bàn cờ cho khung xem trước — thấy ngay phần nền trong suốt."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("previewSurface")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        paint_checkerboard(painter, QRectF(self.rect()).adjusted(1, 1, -1, -1))
        painter.end()
        super().paintEvent(event)
