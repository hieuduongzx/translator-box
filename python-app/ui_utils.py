"""Tiện ích Qt/Windows dùng chung cho các cửa sổ."""

from __future__ import annotations

import ctypes
import os
import sys
import tempfile

from PySide6.QtCore import QEvent, QLineF, QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

# Một accent phẳng duy nhất — không gradient. Glyph trắng trên nền accent.
BRAND = QColor("#5b62f0")


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


def _make_icon(kind: str, color: QColor, px: int = 48) -> QIcon:  # noqa: C901
    """Vẽ icon nét mảnh kiểu Lucide — không cần file asset ngoài."""
    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
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
    elif kind == "settings":  # bánh răng đơn giản: vòng + 8 răng
        import math

        # `line` tự scale từ lưới 40×40; giữ tâm ở đơn vị thiết kế để tránh
        # scale hai lần khi icon được render ở kích thước khác 40 px.
        cx, cy = 20, 20
        for i in range(8):
            ang = math.radians(i * 45)
            dx, dy = math.cos(ang), math.sin(ang)
            line(cx + dx * 9, cy + dy * 9, cx + dx * 13.5, cy + dy * 13.5)
        painter.drawEllipse(QPointF(cx * s, cy * s), 6.5 * s, 6.5 * s)
    elif kind == "copy":  # hai tờ giấy chồng
        painter.drawRoundedRect(QRectF(14 * s, 14 * s, 18 * s, 18 * s), 3 * s, 3 * s)
        painter.drawRoundedRect(QRectF(8 * s, 8 * s, 18 * s, 18 * s), 3 * s, 3 * s)
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
    painter.end()
    return QIcon(pixmap)


def _ui_assets() -> dict[str, str]:
    """Sinh PNG nhỏ cho QSS (mũi tên combo) trong thư mục temp, trả về url()."""
    cache = os.path.join(tempfile.gettempdir(), "screen-translator-2k-assets")
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, "chevron-down.png")
    if not os.path.exists(path):
        px = QPixmap(24, 24)
        px.fill(Qt.transparent)
        painter = QPainter(px)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor("#8b8b93"))
        pen.setWidthF(2.2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(QLineF(6.0, 9.5, 12.0, 15.5))
        painter.drawLine(QLineF(12.0, 15.5, 18.0, 9.5))
        painter.end()
        px.save(path, "PNG")
    return {"chevron": "file:///" + path.replace(os.sep, "/")}


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
