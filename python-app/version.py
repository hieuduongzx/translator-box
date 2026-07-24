"""Nguồn phiên bản duy nhất — dùng bởi app, updater, PyInstaller và Inno Setup."""

from __future__ import annotations

APP_VERSION = "1.0.2"
APP_NAME = "Translator Box"
# Tên thư mục/exe không dấu cách để đóng gói và ghi shortcut cho gọn.
APP_ID = "ScreenTranslator2K"
PUBLISHER = "hieuduongzx"

# owner/repo trên GitHub — updater gọi API releases của repo này.
GITHUB_REPO = "hieuduongzx/translator-box"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
