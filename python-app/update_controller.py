"""Điều phối kiểm tra & cài đặt cập nhật; tách khỏi code dựng UI."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

import updater
from version import APP_NAME, GITHUB_RELEASES_URL

if TYPE_CHECKING:
    from hud_window import HUDWindow


class UpdateController:
    """Kiểm tra GitHub Releases và chạy luồng cập nhật một chạm."""

    def __init__(self, hud: "HUDWindow") -> None:
        self.hud = hud
        self.available: updater.ReleaseInfo | None = None
        self._checking = False
        self._installing = False

    @property
    def busy(self) -> bool:
        return self._checking or self._installing

    # ----- kiểm tra -----
    def check_on_startup(self) -> None:
        if self.hud.config.auto_update:
            self._check(silent=True)

    def check_manual(self) -> None:
        self._check(silent=False)

    def _check(self, silent: bool) -> None:
        if self.busy:
            return
        self._checking = True
        self._sync_settings()
        if not silent:
            self.hud.set_status("Đang kiểm tra cập nhật…", "busy")

        def worker() -> None:
            release = updater.find_update()
            self.hud.bridge.run.emit(lambda: self._on_checked(release, silent))

        threading.Thread(target=worker, daemon=True).start()

    def _on_checked(self, release: updater.ReleaseInfo | None, silent: bool) -> None:
        self._checking = False
        self.available = release
        self._sync_settings()
        if release is None:
            if not silent:
                self.hud.set_status("Bạn đang dùng bản mới nhất.", "ok")
            return
        self.hud.set_status(f"Có bản cập nhật {release.version}.", "ok")
        skipped = silent and release.version == self.hud.config.skipped_update_version
        if not skipped:
            self._prompt(release)

    def _prompt(self, release: updater.ReleaseInfo) -> None:
        box = QMessageBox(self.hud)
        box.setWindowTitle("Có bản cập nhật")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"{APP_NAME} {release.version} đã sẵn sàng.")
        notes = release.notes.strip()
        if len(notes) > 700:
            notes = notes[:700].rstrip() + "…"
        box.setInformativeText(
            notes or "Nhấn “Cập nhật ngay” để tải và cài đặt bản mới."
        )
        update_btn = box.addButton("Cập nhật ngay", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Để sau", QMessageBox.ButtonRole.RejectRole)
        skip_btn = box.addButton(
            "Bỏ qua bản này", QMessageBox.ButtonRole.DestructiveRole
        )
        box.setDefaultButton(update_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is update_btn:
            self.start_install(release)
        elif clicked is skip_btn:
            self.hud.config.skipped_update_version = release.version
            self.hud.config.save()

    # ----- cài đặt -----
    def start_install(self, release: updater.ReleaseInfo | None = None) -> None:
        release = release or self.available
        if release is None or self._installing:
            return
        # Bản chạy từ source không thể tự thay bằng installer — mở trang tải.
        if not updater.is_frozen() or not release.asset_url:
            self.hud.set_status("Mở trang tải bản mới trên GitHub…", "ok")
            QDesktopServices.openUrl(QUrl(release.html_url or GITHUB_RELEASES_URL))
            return
        self._installing = True
        self.hud.set_busy(True)
        self._sync_settings()
        self.hud.set_status(f"Đang tải bản {release.version}… 0%", "busy")

        def worker() -> None:
            try:
                path = updater.download_asset(release, self._emit_progress)
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                self.hud.bridge.run.emit(lambda: self._fail(message))
                return
            self.hud.bridge.run.emit(lambda: self._run_installer(path))

        threading.Thread(target=worker, daemon=True).start()

    def _emit_progress(self, downloaded: int, total: int) -> None:
        percent = int(downloaded * 100 / total) if total else 0
        version = self.available.version if self.available else ""
        self.hud.bridge.run.emit(
            lambda: self.hud.set_status(
                f"Đang tải bản {version}… {percent}%", "busy"
            )
        )

    def _run_installer(self, path: str) -> None:
        self.hud.set_status("Đang cài đặt — ứng dụng sẽ khởi động lại…", "busy")
        try:
            updater.run_installer(path)
        except Exception as exc:  # noqa: BLE001
            self._fail(str(exc))
            return
        QTimer.singleShot(500, self.hud.quit_app)

    def _fail(self, message: str) -> None:
        self._installing = False
        self.hud.set_busy(False)
        self._sync_settings()
        self.hud.set_status(f"Cập nhật lỗi: {message}", "error")

    def _sync_settings(self) -> None:
        settings = self.hud._settings_win
        if settings is not None:
            settings.refresh_update_state()
