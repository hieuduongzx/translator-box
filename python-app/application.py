"""Khởi tạo Qt, single-instance server và cửa sổ chính."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from constants import SERVER_NAME
from hud_window import HUDWindow
from theme import build_style
from ui_utils import (
    TranslatorApplication,
    _bring_to_front,
    _create_app_icon,
    _ui_assets,
    apply_dark_palette,
)


class SingleInstanceServer:
    """Đảm bảo chỉ một process; process sau yêu cầu process đầu hiện HUD."""

    def __init__(self, server_name: str) -> None:
        self.server_name = server_name
        self.server = QLocalServer()

    def notify_existing_instance(self) -> bool:
        probe = QLocalSocket()
        probe.connectToServer(self.server_name)
        if not probe.waitForConnected(300):
            return False
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(500)
        probe.disconnectFromServer()
        return True

    def listen(self, on_message: Callable[[], None]) -> bool:
        QLocalServer.removeServer(self.server_name)
        if not self.server.listen(self.server_name):
            return False

        def consume_connection() -> None:
            connection = self.server.nextPendingConnection()
            if connection is not None:
                connection.disconnectFromServer()
            on_message()

        self.server.newConnection.connect(consume_connection)
        return True


class ApplicationRuntime:
    """Composition root của ứng dụng."""

    def run(self) -> int:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        app = TranslatorApplication([])
        app.setWindowIcon(_create_app_icon())

        single_instance = SingleInstanceServer(SERVER_NAME)
        if single_instance.notify_existing_instance():
            return 0

        apply_dark_palette(app)
        app.setStyleSheet(build_style(_ui_assets()))
        window = HUDWindow()
        if not single_instance.listen(lambda: _bring_to_front(window)):
            window.set_status(
                "Không thể mở kênh single-instance; app vẫn tiếp tục.", "error"
            )

        window.show()
        _bring_to_front(window)
        return app.exec()


def main() -> int:
    return ApplicationRuntime().run()
