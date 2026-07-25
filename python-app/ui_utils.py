"""Tiện ích Qt/Windows dùng chung cho các cửa sổ."""

from __future__ import annotations

import ctypes
import os
import sys
import tempfile

from PySide6.QtCore import (
    QEvent,
    QLineF,
    QObject,
    QPointF,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QImage,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QWidget

from theme import TOKENS

# Một accent phẳng duy nhất — không gradient. Glyph trắng trên nền accent.
BRAND = QColor("#5b62f0")

# Bảng màu icon dùng chung cho HUD bar và sidebar cài đặt.
ICON_IDLE = QColor("#b7bfcd")
ICON_ACTIVE = QColor("#ffffff")
ICON_ON = QColor(TOKENS["ACCENT_HI"])
ICON_OFF = QColor(TOKENS["TEXT_OFF"])


class TranslatorApplication(QApplication):
    """Không cho Qt tự kết thúc khi cửa sổ cuối bị ẩn/đóng xuống tray."""

    def __init__(self, argv) -> None:
        super().__init__(argv)
        self.allow_quit = False
        self.setQuitOnLastWindowClosed(False)

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.Quit and not self.allow_quit:
            return True
        return super().event(event)


class Bridge(QObject):
    """Chuyển lệnh từ thread nền về main thread (Qt queued signal)."""

    run = Signal(object)


def alpha_text_layer(size: QSize) -> QImage | None:
    """Lớp ARGB trong suốt để vẽ chữ rồi dán lên — buộc Qt dùng AA xám.

    Trên Windows, chữ vẽ TRỰC TIẾP lên vùng đục luôn bị bật ClearType (subpixel
    AA) và `QFont.NoSubpixelAntialias` bị bỏ qua; riềm đỏ/xanh của ClearType lộ ra
    thành đốm nâu/tím, làm bản dịch trông sai màu so với chữ gốc. Vẽ vào lớp trong
    suốt rồi dán lại thì Qt buộc dùng AA xám, giữ đúng màu chữ mà nét vẫn nguyên.
    """
    if size.width() <= 0 or size.height() <= 0:
        return None
    layer = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    layer.fill(Qt.transparent)
    return layer


def _render_icon_pixmap(size: int) -> QPixmap:
    """Mark: tile bo góc accent phẳng, chữ 'T' trắng — không gradient."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    margin = max(1, round(size * 0.07))
    radius = max(2, round(size * 0.28))
    tile = QRectF(margin, margin, size - margin * 2, size - margin * 2)
    painter.setBrush(BRAND)
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(tile, radius, radius)
    font = QFont("Segoe UI", max(8, int(size * 0.52)), QFont.Bold)
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "T")
    painter.end()
    return pixmap


def asset_path(name: str) -> str | None:
    """Đường dẫn tới file trong assets/ — chạy cả khi đóng gói (PyInstaller)."""
    bases = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        bases.append(os.path.join(bundle, "assets"))
    bases.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets"))
    for base in bases:
        candidate = os.path.join(base, name)
        if os.path.exists(candidate):
            return candidate
    return None


def _create_app_icon() -> QIcon:
    """Icon đa độ phân giải — ưu tiên icon.ico đóng gói, nếu không thì vẽ tay."""
    path = asset_path("icon.ico")
    if path:
        icon = QIcon(path)
        if not icon.isNull():
            return icon
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128):
        icon.addPixmap(_render_icon_pixmap(size))
    return icon


def _brand_pixmap(size: int, ratio: float = 2.0) -> QPixmap:
    """Mark thương hiệu ở kích thước bất kỳ — ưu tiên icon đóng gói cho sắc nét."""
    physical = max(1, round(size * ratio))
    path = asset_path("icon.png") or asset_path("icon.ico")
    if path:
        icon = QIcon(path)
        if not icon.isNull():
            pixmap = icon.pixmap(physical, physical)
            if not pixmap.isNull():
                pixmap.setDevicePixelRatio(ratio)
                return pixmap
    pixmap = _render_icon_pixmap(physical)
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def _enable_dark_titlebar(window: QWidget) -> None:
    """Title bar Windows tối theo theme (DWMWA_USE_IMMERSIVE_DARK_MODE)."""
    if os.name != "nt":
        return
    try:
        hwnd = int(window.winId())
        value = ctypes.c_int(1)
        dwm = ctypes.windll.dwmapi
        for attr in (20, 19):
            if (
                dwm.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
                )
                == 0
            ):
                break
    except Exception:  # noqa: BLE001
        pass


def _paint_glyph(painter: QPainter, kind: str, px: float, color: QColor) -> None:  # noqa: C901
    """Vẽ glyph nét mảnh kiểu Lucide trên lưới thiết kế 40×40, không cần asset."""
    pen = QPen(color)
    pen.setWidthF(px * 0.062)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    s = px / 40.0  # toạ độ thiết kế trên lưới 40x40

    def line(x1: float, y1: float, x2: float, y2: float) -> None:
        painter.drawLine(QLineF(x1 * s, y1 * s, x2 * s, y2 * s))

    if kind == "text":  # 3 dòng chữ
        line(8, 12, 32, 12)
        line(8, 20, 26, 20)
        line(8, 28, 30, 28)
    elif kind == "replace":  # hai mũi tên ngược chiều — dịch & thay thế tại chỗ
        line(10, 16, 29, 16)
        line(29, 16, 25, 12)
        line(29, 16, 25, 20)
        line(30, 25, 11, 25)
        line(11, 25, 15, 21)
        line(11, 25, 15, 29)
    elif kind == "image":  # ảnh + hai mũi tên: thay chữ trực tiếp trong ảnh
        painter.drawRoundedRect(QRectF(7 * s, 9 * s, 26 * s, 22 * s), 3 * s, 3 * s)
        painter.drawEllipse(QPointF(14 * s, 16 * s), 2.3 * s, 2.3 * s)
        line(11, 27, 17, 21)
        line(17, 21, 22, 25)
        line(25, 18, 31, 18)
        line(31, 18, 28, 15)
        line(31, 18, 28, 21)
    elif kind == "image-text":  # ảnh + dòng chữ: OCR ảnh vào khung
        painter.drawRoundedRect(QRectF(7 * s, 9 * s, 26 * s, 22 * s), 3 * s, 3 * s)
        painter.drawEllipse(QPointF(14 * s, 16 * s), 2.3 * s, 2.3 * s)
        line(11, 26, 17, 21)
        line(17, 21, 20, 24)
        line(23, 21, 30, 21)
        line(23, 25, 30, 25)
    elif kind == "scan":  # khung quét 4 góc + vạch ngang giữa
        line(9, 15, 9, 9)
        line(9, 9, 15, 9)
        line(25, 9, 31, 9)
        line(31, 9, 31, 15)
        line(31, 25, 31, 31)
        line(31, 31, 25, 31)
        line(15, 31, 9, 31)
        line(9, 31, 9, 25)
        line(14, 20, 26, 20)
    elif kind == "overlay":  # hai lớp chồng nhau
        painter.drawRoundedRect(QRectF(8 * s, 8 * s, 18 * s, 18 * s), 3 * s, 3 * s)
        painter.drawRoundedRect(QRectF(16 * s, 16 * s, 18 * s, 18 * s), 3 * s, 3 * s)
    elif kind == "live":  # sóng phát + chấm tâm
        painter.setBrush(color)
        painter.drawEllipse(QPointF(20 * s, 20 * s), 3.2 * s, 3.2 * s)
        painter.setBrush(Qt.NoBrush)
        rect_inner = QRectF(12 * s, 12 * s, 16 * s, 16 * s)
        rect_outer = QRectF(7 * s, 7 * s, 26 * s, 26 * s)
        painter.drawArc(rect_inner, -45 * 16, 90 * 16)
        painter.drawArc(rect_inner, 135 * 16, 90 * 16)
        painter.drawArc(rect_outer, -45 * 16, 90 * 16)
        painter.drawArc(rect_outer, 135 * 16, 90 * 16)
    elif kind == "liveframe":  # khung + chấm live ở giữa
        painter.drawRoundedRect(QRectF(8 * s, 10 * s, 24 * s, 20 * s), 3 * s, 3 * s)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(20 * s, 20 * s), 2.6 * s, 2.6 * s)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(pen)
        painter.drawArc(QRectF(14 * s, 14 * s, 12 * s, 12 * s), -50 * 16, 100 * 16)
        painter.drawArc(QRectF(14 * s, 14 * s, 12 * s, 12 * s), 130 * 16, 100 * 16)
    elif kind == "pin":  # ghim cửa sổ
        line(14, 9, 26, 9)
        line(16, 9, 17, 18)
        line(23, 18, 24, 9)
        line(13, 18, 27, 18)
        line(20, 18, 20, 32)
        line(17, 32, 20, 28)
        line(23, 32, 20, 28)
    elif kind == "settings":  # 3 thanh trượt — rõ nghĩa "cài đặt" hơn bánh răng
        for x, knob_y in ((12, 16), (20, 24), (28, 14)):
            line(x, 9, x, 31)
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(x * s, knob_y * s), 3.1 * s, 3.1 * s)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(pen)
    elif kind == "copy":  # bảng kẹp (clipboard) — không lẫn với icon overlay
        painter.drawRoundedRect(QRectF(11 * s, 10 * s, 18 * s, 22 * s), 3 * s, 3 * s)
        painter.drawRoundedRect(QRectF(16 * s, 6.5 * s, 8 * s, 6 * s), 2 * s, 2 * s)
    elif kind == "clear":  # thùng rác
        line(9, 12, 31, 12)
        line(16, 12, 16, 9)
        line(16, 9, 24, 9)
        line(24, 9, 24, 12)
        line(12, 12, 13, 32)
        line(13, 32, 27, 32)
        line(27, 32, 28, 12)
        line(20, 16, 20, 28)
    elif kind == "hide":  # mũi tên xuống khay
        line(20, 9, 20, 24)
        line(14, 18, 20, 24)
        line(26, 18, 20, 24)
        line(11, 31, 29, 31)
    elif kind == "globe":  # quả cầu — nhóm cài đặt "Dịch"
        painter.drawEllipse(QPointF(20 * s, 20 * s), 12 * s, 12 * s)
        line(8, 20, 32, 20)
        # Kinh tuyến: ellipse hẹp lồng trong quả cầu.
        painter.drawEllipse(QPointF(20 * s, 20 * s), 6.5 * s, 12 * s)
    elif kind == "ai":  # chip xử lý — nhóm cấu hình provider AI
        painter.drawRoundedRect(
            QRectF(11 * s, 11 * s, 18 * s, 18 * s), 4 * s, 4 * s
        )
        for offset in (15, 20, 25):
            line(offset, 7, offset, 11)
            line(offset, 29, offset, 33)
            line(7, offset, 11, offset)
            line(29, offset, 33, offset)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(20 * s, 20 * s), 3.2 * s, 3.2 * s)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(pen)
    elif kind == "keyboard":  # bàn phím — nhóm "Phím tắt"
        painter.drawRoundedRect(
            QRectF(7 * s, 12 * s, 26 * s, 17 * s), 3.5 * s, 3.5 * s
        )
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        for x in (12, 17, 22, 27):
            painter.drawEllipse(QPointF(x * s, 18.5 * s), 1.1 * s, 1.1 * s)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(pen)
        line(14, 24.5, 26, 24.5)
    elif kind == "info":  # thông tin — nhóm "Giới thiệu"
        painter.drawEllipse(QPointF(20 * s, 20 * s), 12 * s, 12 * s)
        line(20, 18.5, 20, 26)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(20 * s, 14.5 * s), 1.3 * s, 1.3 * s)
    elif kind == "type":  # chữ "A" + gạch chân — nhóm "Khung dịch"
        line(11, 28, 19, 12)
        line(19, 12, 27, 28)
        line(14, 23, 24, 23)
        line(9, 32, 31, 32)


def _glyph_pixmap(
    kind: str, color: QColor, logical: int, ratio: float = 2.0
) -> QPixmap:
    """Pixmap glyph theo devicePixelRatio → nét sắc ở mọi mức DPI."""
    physical = max(1, round(logical * ratio))
    pixmap = QPixmap(physical, physical)
    pixmap.fill(Qt.transparent)
    pixmap.setDevicePixelRatio(ratio)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    # QPainter làm việc theo toạ độ LOGIC khi pixmap có devicePixelRatio, nên vẽ
    # trên lưới `physical / ratio`; backing store 2x lo phần sắc nét.
    _paint_glyph(painter, kind, physical / ratio, color)
    painter.end()
    return pixmap


def _make_icon(kind: str, color: QColor, px: int = 48) -> QIcon:
    """Icon một màu (dùng khi chỉ cần một trạng thái)."""
    return QIcon(_glyph_pixmap(kind, color, px, 1.0))


def _state_icon(kind: str, logical: int = 18) -> QIcon:
    """Icon đa trạng thái: thường / hover (Active) / bật (On) / mờ (Disabled).

    Qt tự chọn pixmap theo mode+state nên nút không cần tự đổi icon khi hover
    hay khi được check.
    """
    icon = QIcon()
    variants = (
        (ICON_IDLE, QIcon.Mode.Normal, QIcon.State.Off),
        (ICON_ACTIVE, QIcon.Mode.Active, QIcon.State.Off),
        (ICON_ACTIVE, QIcon.Mode.Selected, QIcon.State.Off),
        (ICON_OFF, QIcon.Mode.Disabled, QIcon.State.Off),
        (ICON_ON, QIcon.Mode.Normal, QIcon.State.On),
        (ICON_ON, QIcon.Mode.Active, QIcon.State.On),
        (ICON_ON, QIcon.Mode.Selected, QIcon.State.On),
        (ICON_OFF, QIcon.Mode.Disabled, QIcon.State.On),
    )
    for glyph_color, mode, state in variants:
        icon.addPixmap(_glyph_pixmap(kind, glyph_color, logical), mode, state)
    return icon


def _nav_icon(kind: str, logical: int = 17) -> QIcon:
    """Icon sidebar: xám khi thường, chuyển accent khi mục được chọn."""
    icon = QIcon()
    icon.addPixmap(
        _glyph_pixmap(kind, ICON_IDLE, logical), QIcon.Mode.Normal, QIcon.State.Off
    )
    icon.addPixmap(
        _glyph_pixmap(kind, ICON_ON, logical), QIcon.Mode.Selected, QIcon.State.Off
    )
    icon.addPixmap(
        _glyph_pixmap(kind, ICON_ACTIVE, logical), QIcon.Mode.Active, QIcon.State.Off
    )
    return icon


def _stroke_pixmap(draw, color: QColor, size: int = 24, width: float = 2.2) -> QPixmap:
    """Khung vẽ chung cho các glyph nhỏ dùng làm asset của QSS."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(color)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    draw(painter)
    painter.end()
    return pixmap


def _chevron(down: bool):
    def draw(painter: QPainter) -> None:
        if down:
            painter.drawLine(QLineF(6.5, 9.5, 12.0, 15.0))
            painter.drawLine(QLineF(12.0, 15.0, 17.5, 9.5))
        else:
            painter.drawLine(QLineF(6.5, 14.5, 12.0, 9.0))
            painter.drawLine(QLineF(12.0, 9.0, 17.5, 14.5))

    return draw


def _checkmark(painter: QPainter) -> None:
    painter.drawLine(QLineF(6.0, 12.5, 10.0, 16.5))
    painter.drawLine(QLineF(10.0, 16.5, 18.0, 7.5))


# Đổi số này khi sửa hình dạng asset để bỏ qua file PNG cache của bản cũ.
_ASSET_REVISION = 2


def _ui_assets() -> dict[str, str]:
    """Sinh PNG nhỏ cho QSS (mũi tên, dấu tích) vào temp, trả về url() từng cái."""
    cache = os.path.join(tempfile.gettempdir(), "screen-translator-2k-assets")
    os.makedirs(cache, exist_ok=True)
    arrow = QColor(TOKENS["TEXT_DIM"])
    arrow_off = QColor(TOKENS["TEXT_OFF"])
    recipes = {
        "chevron": (_chevron(True), arrow, 2.2),
        "chevron_up": (_chevron(False), arrow, 2.2),
        "chevron_off": (_chevron(True), arrow_off, 2.2),
        "chevron_up_off": (_chevron(False), arrow_off, 2.2),
        "check": (_checkmark, QColor("#ffffff"), 2.6),
    }
    assets: dict[str, str] = {}
    for name, (draw, glyph_color, width) in recipes.items():
        path = os.path.join(cache, f"{name}-r{_ASSET_REVISION}.png")
        if not os.path.exists(path):
            _stroke_pixmap(draw, glyph_color, 24, width).save(path, "PNG")
        # QSS url() cần đường dẫn thuần; dạng "file:///…" Qt KHÔNG nạp được.
        assets[name] = path.replace(os.sep, "/")
    return assets


def apply_dark_palette(app: QApplication) -> None:
    """Palette tối cho các hộp thoại Qt dựng sẵn (chọn màu, thông báo, tooltip).

    Stylesheet không chạm tới mọi widget con của QColorDialog/QMessageBox nên nếu
    thiếu bước này, chúng hiện ra theo palette sáng mặc định của Windows và chữ
    trắng sẽ mất hút.
    """
    palette = QPalette()
    bg = QColor(TOKENS["BG"])
    surface = QColor(TOKENS["SURFACE"])
    sunken = QColor(TOKENS["SUNKEN"])
    text = QColor(TOKENS["TEXT"])
    muted = QColor(TOKENS["TEXT_OFF"])
    accent = QColor(TOKENS["ACCENT"])
    for group in (QPalette.Active, QPalette.Inactive):
        palette.setColor(group, QPalette.Window, bg)
        palette.setColor(group, QPalette.WindowText, text)
        palette.setColor(group, QPalette.Base, sunken)
        palette.setColor(group, QPalette.AlternateBase, surface)
        palette.setColor(group, QPalette.Text, text)
        palette.setColor(group, QPalette.Button, surface)
        palette.setColor(group, QPalette.ButtonText, text)
        palette.setColor(group, QPalette.ToolTipBase, surface)
        palette.setColor(group, QPalette.ToolTipText, text)
        palette.setColor(group, QPalette.Highlight, accent)
        palette.setColor(group, QPalette.HighlightedText, QColor("#ffffff"))
        palette.setColor(group, QPalette.Link, QColor(TOKENS["ACCENT_HI"]))
        palette.setColor(group, QPalette.PlaceholderText, QColor(TOKENS["TEXT_MUTED"]))
    for role in (
        QPalette.WindowText,
        QPalette.Text,
        QPalette.ButtonText,
        QPalette.PlaceholderText,
    ):
        palette.setColor(QPalette.Disabled, role, muted)
    palette.setColor(QPalette.Disabled, QPalette.Window, bg)
    palette.setColor(QPalette.Disabled, QPalette.Base, bg)
    palette.setColor(QPalette.Disabled, QPalette.Button, QColor(TOKENS["PRESSED"]))
    app.setPalette(palette)


def _fmt_hotkey(raw: str) -> str:
    """Hiển thị phím tắt dạng Ctrl+Alt+A."""
    if not raw or not raw.strip():
        return "Tắt"
    parts = [p.strip() for p in raw.lower().replace(" ", "").split("+") if p.strip()]
    pretty = []
    for p in parts:
        if p in ("ctrl", "control"):
            pretty.append("Ctrl")
        elif p == "alt":
            pretty.append("Alt")
        elif p in ("shift", "shft"):
            pretty.append("Shift")
        elif p in ("win", "windows", "cmd", "super"):
            pretty.append("Win")
        elif len(p) == 1:
            pretty.append(p.upper())
        else:
            pretty.append(p.capitalize())
    return "+".join(pretty) if pretty else "Tắt"


# Phím bổ trợ / phím không thể dùng một mình làm hotkey.
_MODIFIER_KEYS = {
    Qt.Key_Control,
    Qt.Key_Shift,
    Qt.Key_Alt,
    Qt.Key_AltGr,
    Qt.Key_Meta,
    Qt.Key_CapsLock,
    Qt.Key_NumLock,
    Qt.Key_ScrollLock,
}
_SPECIAL_KEYS = {
    Qt.Key_Space: "space",
    Qt.Key_Tab: "tab",
    Qt.Key_Return: "enter",
    Qt.Key_Enter: "enter",
    Qt.Key_Home: "home",
    Qt.Key_End: "end",
    Qt.Key_PageUp: "page up",
    Qt.Key_PageDown: "page down",
    Qt.Key_Insert: "insert",
    Qt.Key_Left: "left",
    Qt.Key_Right: "right",
    Qt.Key_Up: "up",
    Qt.Key_Down: "down",
    Qt.Key_Print: "print screen",
}


def _key_name(key: int) -> str | None:
    """Tên phím chính theo cú pháp thư viện `keyboard`, hoặc None nếu không hỗ trợ."""
    if Qt.Key_A <= key <= Qt.Key_Z:
        return chr(key).lower()
    if Qt.Key_0 <= key <= Qt.Key_9:
        return chr(key)
    if Qt.Key_F1 <= key <= Qt.Key_F35:
        return f"f{key - Qt.Key_F1 + 1}"
    return _SPECIAL_KEYS.get(key)


def _combo_from_event(event) -> str | None:
    """Chuyển sự kiện phím Qt thành 'ctrl+alt+a'. None nếu chưa có phím chính."""
    name = _key_name(event.key())
    if name is None:
        return None
    mods = event.modifiers()
    parts = []
    if mods & Qt.ControlModifier:
        parts.append("ctrl")
    if mods & Qt.AltModifier:
        parts.append("alt")
    if mods & Qt.ShiftModifier:
        parts.append("shift")
    if mods & Qt.MetaModifier:
        parts.append("windows")
    parts.append(name)
    return "+".join(parts)


def _image_signature(path: str) -> bytes:
    """Tạo ảnh xám nhỏ để phát hiện vùng màn hình có thay đổi."""
    from PIL import Image

    with Image.open(path) as image:
        return image.convert("L").resize((48, 48)).tobytes()


def _sig_differs(first: bytes | None, second: bytes | None) -> bool:
    """Trả về True khi số pixel thay đổi vượt ngưỡng chống nhiễu."""
    if first is None or second is None or len(first) != len(second):
        return True
    changed = sum(1 for left, right in zip(first, second) if abs(left - right) > 24)
    return changed > 16


def _bring_to_front(window: QWidget) -> None:
    """Khôi phục cửa sổ; chỉ giữ topmost khi cờ cửa sổ yêu cầu."""
    window.setWindowState(
        (window.windowState() & ~Qt.WindowState.WindowMinimized)
        | Qt.WindowState.WindowActive
    )
    window.show()
    window.showNormal()
    window.raise_()
    window.activateWindow()
    if os.name != "nt":
        return
    try:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        hwnd = int(window.winId())
        flags = 0x0001 | 0x0002 | 0x0040
        insert_after = (
            -1 if bool(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) else 0
        )
        user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, flags)
        user32.SetForegroundWindow(hwnd)
    except Exception:  # noqa: BLE001
        pass
