"""Các widget tái sử dụng trong HUD và cửa sổ cài đặt."""

from __future__ import annotations

import math
from typing import Protocol, Sequence

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
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
    _combo_from_event,
    _fmt_hotkey,
    _state_icon,
    _tracked,
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
        self.setProperty("emphasized", emphasized)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(30, 30)
        self.setIconSize(QSize(18, 18))
        self.setIcon(_state_icon(kind, idle_color=ICON_ACTIVE if emphasized else None))


class BarMenuButton(QPushButton):
    """Toggle nhóm dịch; menu ưu tiên mở ngược lên trên HUD."""

    def __init__(self, kind: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(f"{label}  ↑", parent)
        self.setObjectName("barGroupToggle")
        self.setProperty("live", False)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(30)
        self.setIconSize(QSize(16, 16))
        self.setIcon(_state_icon(kind))
        self._menu: QMenu | None = None
        self.clicked.connect(self._toggle_menu)

    def attach_menu(self, menu: QMenu) -> None:
        self._menu = menu
        menu.aboutToHide.connect(self._menu_hidden)

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


def draw_crop_marks(
    painter: QPainter,
    rect: QRectF,
    length: float = 9.0,
    color: QColor | None = None,
    alpha: int = 210,
) -> None:
    """Ngoặc góc kiểu dấu cắt in ấn/bản vẽ kỹ thuật (blueprint crop-mark).

    Panel giờ góc vuông (không bo tròn) nên ngoặc chạm đúng mép — cùng ngôn
    ngữ với khung chọn vùng (overlay.py), dành riêng cho panel nổi bật. `color`
    mặc định lấy từ TOKENS["FOCUS"] (mực chính của theme đang áp dụng) để tự
    khớp nền sáng/tối của panel gọi hàm; truyền riêng khi panel có nền cố định
    khác theme trang (vd. bàn cờ preview luôn tối).
    """
    mark = QColor(color) if color is not None else QColor(TOKENS["FOCUS"])
    mark.setAlpha(alpha)
    pen = QPen(mark)
    pen.setWidthF(1.0)
    pen.setCapStyle(Qt.SquareCap)
    painter.save()
    painter.setPen(pen)
    left, top, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
    painter.drawLine(QPointF(left, top), QPointF(left + length, top))
    painter.drawLine(QPointF(left, top), QPointF(left, top + length))
    painter.drawLine(QPointF(right, top), QPointF(right - length, top))
    painter.drawLine(QPointF(right, top), QPointF(right, top + length))
    painter.drawLine(QPointF(left, bottom), QPointF(left + length, bottom))
    painter.drawLine(QPointF(left, bottom), QPointF(left, bottom - length))
    painter.drawLine(QPointF(right, bottom), QPointF(right - length, bottom))
    painter.drawLine(QPointF(right, bottom), QPointF(right, bottom - length))
    painter.restore()


class HudBar(DragBar):
    """Thanh bar phẳng, góc vuông: vẽ thêm ngoặc góc (crop-mark) — cùng ngôn
    ngữ với khung chọn vùng (overlay.py) — để nhận ra ngay đây là dụng cụ
    chụp/dịch, không phải khung chat bo tròn chung chung."""

    CORNER = 8.0

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        draw_crop_marks(painter, rect, length=self.CORNER)
        painter.end()


class BusyBar(QWidget):
    """Vạch tiến trình vô định 2px: beam lime đặc, không gradient."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFixedHeight(2)
        self._phase = 0.0
        self._active = False
        self._timer = QTimer(self)
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
        width = self.width()
        span = max(48.0, width * 0.22)
        left = -span + (width + span) * self._phase
        painter.fillRect(
            QRectF(left, 0.0, span, self.height()), QColor(TOKENS["FOCUS"])
        )
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
        self._font = QFont("IBM Plex Mono", 9)
        self._font.setWeight(QFont.Medium)
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
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(TOKENS["LINE"]), 1.0))
        painter.setBrush(QColor(TOKENS["RAISED"]))
        painter.drawRoundedRect(rect, 2.0, 2.0)

        dot = QColor(_STATE_COLORS[self._state])
        if self._state == "busy":
            dot.setAlphaF(0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._pulse)))
        center_y = rect.center().y()
        painter.setPen(Qt.NoPen)
        painter.setBrush(dot)
        painter.drawEllipse(QRectF(9.0, center_y - 3.0, 6.0, 6.0))

        painter.setFont(self._font)
        painter.setPen(QColor(TOKENS["TEXT_DIM"]))
        text_rect = rect.adjusted(22.0, 0.0, -9.0, 0.0)
        metrics = QFontMetrics(self._font)
        painter.drawText(
            text_rect,
            Qt.AlignVCenter | Qt.AlignLeft,
            metrics.elidedText(self._text, Qt.ElideRight, int(text_rect.width())),
        )
        painter.end()


class TranscriptBlockView(Protocol):
    kind: str
    text: str
    language: str | None
    speaker: str | None
    is_final: bool


class HudTextView(QWidget):
    """Vẽ bản dịch với font, viền và màu nền do người dùng chọn."""

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

    def setText(self, text: str) -> None:
        self._text = text or ""
        self._image = None
        self._transcript_blocks = ()
        self.setAccessibleDescription(
            "Nội dung bản dịch dạng văn bản" if self._text else "Khung dịch đang trống"
        )
        self.update()

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
        self.update()

    def _transcript_plain_text(self) -> str:
        parts: list[str] = []
        current_speaker: str | None = None
        visible = [
            block
            for block in self._transcript_blocks
            if self._transcript_display_mode == "bilingual"
            or block.kind == "translation"
        ]
        for block in visible:
            if block.speaker is not None and block.speaker != current_speaker:
                if parts:
                    parts.append("")
                parts.append(f"NGƯỜI NÓI {block.speaker}")
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
        self.update()

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
        self.update()

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

    def _transcript_document(
        self, font: QFont, color: QColor, width: int, *, outline: bool
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

        def text_format(
            current_font: QFont, current_color: QColor, *, with_outline: bool
        ) -> QTextCharFormat:
            result = QTextCharFormat()
            result.setFont(current_font)
            result.setForeground(current_color)
            if with_outline and outline and self._border_width:
                pen = QPen(self._border_color)
                pen.setWidthF(self._border_width)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                result.setTextOutline(pen)
            return result

        original_font = QFont(font)
        original_font.setPointSizeF(max(8.0, font.pointSizeF() * 0.72))
        original_font.setWeight(QFont.Medium)
        label_font = QFont(TOKENS["FONT_MONO"].split(",")[0].strip("'"))
        label_font.setPointSizeF(max(7.5, font.pointSizeF() * 0.48))
        label_font.setWeight(QFont.DemiBold)
        muted = QColor(color)
        muted.setAlphaF(max(0.28, color.alphaF() * 0.58))
        label_text_format = text_format(label_font, muted, with_outline=False)

        def content_format(block: TranscriptBlockView) -> QTextCharFormat:
            block_font = QFont(original_font if block.kind == "speech" else font)
            language = (block.language or "").split("-", 1)[0].lower()
            cjk_families = {
                "ja": "Yu Gothic",
                "ko": "Malgun Gothic",
                "zh": "Microsoft YaHei UI",
            }
            if language in cjk_families:
                block_font.setFamily(cjk_families[language])
            return text_format(
                block_font,
                muted if block.kind == "speech" else color,
                with_outline=block.kind == "translation",
            )

        visible = [
            block
            for block in self._transcript_blocks
            if self._transcript_display_mode == "bilingual"
            or block.kind == "translation"
        ]
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

        for index, block in enumerate(visible):
            if block.speaker is not None and block.speaker != current_speaker:
                begin_line(top_margin=5.0 if not first_line else 0.0)
                cursor.insertText(f"// NGƯỜI NÓI {block.speaker}", label_text_format)
                current_speaker = block.speaker

            begin_line(top_margin=4.0 if block.kind == "translation" else 0.0)
            is_pending = index == len(visible) - 1 and not block.is_final
            cursor_text = " ▌" if is_pending else ""
            cursor.insertText(block.text.strip() + cursor_text, content_format(block))

        document.setTextWidth(width)
        return document

    def _content_document(
        self, font: QFont, color: QColor, width: int, *, outline: bool
    ) -> QTextDocument:
        if self._transcript_blocks:
            return self._transcript_document(font, color, width, outline=outline)
        return self._document(font, color, width, outline=outline)

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
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self._background_enabled and self._background_color.alpha() > 0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._background_color)
            painter.drawRect(self.rect())
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
        # Vẽ chữ qua lớp ARGB trong suốt: nếu vẽ thẳng lên nền đục (người dùng chọn
        # màu nền) thì Windows bật ClearType và để lại riềm đỏ/xanh quanh nét chữ.
        layer = alpha_text_layer(self.size())
        target = QPainter(layer) if layer is not None else painter
        target.setRenderHint(QPainter.Antialiasing, True)
        target.setRenderHint(QPainter.TextAntialiasing, True)

        if self._shadow_radius > 0 and self._shadow_color.alpha() > 0:
            # Một document bóng, vẽ lại ở nhiều vị trí → xấp xỉ blur rất rẻ.
            shadow = self._content_document(
                font, self._shadow_color, rect.width(), outline=False
            )
            offsets = self._shadow_offsets()
            target.save()
            target.setOpacity(min(1.0, 2.0 / len(offsets)))
            target.setClipRect(rect)
            for dx, dy in offsets:
                target.save()
                target.translate(
                    rect.left() + dx, self._document_top(shadow, rect) + dy
                )
                shadow.drawContents(target)
                target.restore()
            target.restore()

        document = self._content_document(font, self._color, rect.width(), outline=True)
        target.save()
        target.setClipRect(rect)
        target.translate(rect.left(), self._document_top(document, rect))
        document.drawContents(target)
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
    painter.fillRect(rect, QColor("#27272a"))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#18181b"))
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
            border = QColor(TOKENS["FOCUS"])
        elif self.underMouse() or self.hasFocus():
            border = QColor(TOKENS["FOCUS_LINE"])
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
        featured: bool = False,
        trailing: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._featured = featured
        name = "cardFeatured" if featured else ("cardSunken" if sunken else "card")
        self.setObjectName(name)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(17, 15, 17, 15)
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
                label = QLabel(f"// {title.upper()}")
                label.setObjectName("cardTitle")
                _tracked(label, 108.0)
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

    def add_divider(self) -> QWidget:
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 11, 0, 0)
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

    def add_layout(self, layout) -> None:
        self._spaced()
        self._layout.addLayout(layout)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._featured:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        draw_crop_marks(painter, rect, length=10.0, alpha=210)
        painter.end()


class CodeField(QFrame):
    """Block `.cmd` có chrome terminal, prompt và nút copy thật."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("codeBlock")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("codeHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 0, 0, 0)
        header_layout.setSpacing(8)
        title = QLabel("SCREEN_TRANSLATOR.CMD")
        title.setObjectName("codeTitle")
        _tracked(title, 110.0)
        self._copy_btn = QPushButton("COPY")
        self._copy_btn.setObjectName("codeCopyBtn")
        self._copy_btn.setCursor(Qt.PointingHandCursor)
        self._copy_btn.setToolTip("Copy vào clipboard")
        self._copy_btn.clicked.connect(self._copy)
        header_layout.addWidget(title)
        header_layout.addStretch(1)
        header_layout.addWidget(self._copy_btn)

        command = QWidget()
        command_layout = QHBoxLayout(command)
        command_layout.setContentsMargins(10, 0, 6, 0)
        command_layout.setSpacing(8)
        prompt = QLabel("PS>")
        prompt.setObjectName("codePrompt")
        self._edit = QLineEdit(text)
        self._edit.setObjectName("codeField")
        self._edit.setReadOnly(True)
        self._edit.setCursorPosition(0)
        command_layout.addWidget(prompt)
        command_layout.addWidget(self._edit, 1)

        layout.addWidget(header)
        layout.addWidget(command)

        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.setInterval(1100)
        self._reset_timer.timeout.connect(lambda: self._copy_btn.setText("COPY"))

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
        self._copy_btn.setText("COPIED")
        self._reset_timer.start()


class CheckerFrame(QFrame):
    """Nền bàn cờ cho khung xem trước — thấy ngay phần nền trong suốt."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("previewSurface")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        paint_checkerboard(painter, rect, cell=8, radius=0.0)
        # Preview là panel nổi bật nên dùng cùng crop-mark lime của blueprint shell.
        draw_crop_marks(painter, rect, length=10.0, alpha=210)
        painter.end()
        super().paintEvent(event)
