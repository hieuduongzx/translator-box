"""Kiểm tra và áp dụng cập nhật từ GitHub Releases.

Luồng "một chạm": `check_latest()` hỏi API releases mới nhất → nếu phiên bản
lớn hơn, tải asset installer về temp → `run_installer()` chạy Inno Setup ở chế
độ im lặng rồi app tự thoát để installer thay file và mở lại app.

Toàn bộ thao tác mạng dùng `urllib` (stdlib), không thêm dependency.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass

from version import APP_ID, APP_VERSION, GITHUB_REPO

_UA = f"ScreenTranslator2K/{APP_VERSION}"
_API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"


@dataclass(frozen=True)
class ReleaseInfo:
    """Bản phát hành lấy từ GitHub, đã chọn sẵn asset installer để tải."""

    version: str
    tag: str
    name: str
    notes: str
    html_url: str
    asset_url: str | None
    asset_name: str | None
    asset_size: int


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.3' → (1, 2, 3). Bỏ tiền tố 'v' và hậu tố -beta/+build."""
    cleaned = (text or "").strip().lstrip("vV")
    numbers: list[int] = []
    for part in re.split(r"[.\-+]", cleaned):
        match = re.match(r"\d+", part)
        if not match:
            break
        numbers.append(int(match.group()))
    return tuple(numbers) or (0,)


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    """True nếu phiên bản remote lớn hơn local (so sánh theo số, đệm 0)."""
    remote_parts = parse_version(remote)
    local_parts = parse_version(local)
    length = max(len(remote_parts), len(local_parts))
    remote_padded = remote_parts + (0,) * (length - len(remote_parts))
    local_padded = local_parts + (0,) * (length - len(local_parts))
    return remote_padded > local_padded


def _pick_asset(assets: list) -> tuple[str | None, str | None, int]:
    """Ưu tiên installer .exe (setup), sau đó .zip; trả (url, tên, cỡ byte)."""
    if not isinstance(assets, list):
        return None, None, 0
    valid = [
        asset
        for asset in assets
        if isinstance(asset, dict) and asset.get("browser_download_url")
    ]

    def rank(asset: dict) -> int:
        name = str(asset.get("name", "")).lower()
        if name.endswith(".exe"):
            return 0
        if name.endswith(".zip"):
            return 1
        return 2

    for asset in sorted(valid, key=rank):
        name = str(asset.get("name", "")).lower()
        if name.endswith((".exe", ".zip")):
            return (
                asset["browser_download_url"],
                asset.get("name"),
                int(asset.get("size") or 0),
            )
    return None, None, 0


def check_latest(repo: str = GITHUB_REPO, timeout: float = 8.0) -> ReleaseInfo | None:
    """Hỏi release mới nhất. Trả None nếu lỗi mạng / repo chưa có / không parse được."""
    request = urllib.request.Request(
        _API_LATEST.format(repo=repo),
        headers={"User-Agent": _UA, "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    if not tag:
        return None
    asset_url, asset_name, asset_size = _pick_asset(data.get("assets"))
    return ReleaseInfo(
        version=parse_version_str(tag),
        tag=tag,
        name=str(data.get("name") or tag),
        notes=str(data.get("body") or "").strip(),
        html_url=str(data.get("html_url") or ""),
        asset_url=asset_url,
        asset_name=asset_name,
        asset_size=asset_size,
    )


def parse_version_str(tag: str) -> str:
    """Chuỗi phiên bản chuẩn hoá từ tag (bỏ 'v') để hiển thị và so sánh."""
    return ".".join(str(number) for number in parse_version(tag))


def find_update(repo: str = GITHUB_REPO, timeout: float = 8.0) -> ReleaseInfo | None:
    """Trả release chỉ khi nó MỚI HƠN phiên bản đang chạy; ngược lại None."""
    release = check_latest(repo, timeout)
    if release is None or not is_newer(release.version):
        return None
    return release


def download_asset(
    release: ReleaseInfo,
    on_progress=None,
    timeout: float = 30.0,
) -> str:
    """Tải asset installer về thư mục temp, trả đường dẫn file.

    on_progress(downloaded_bytes, total_bytes) được gọi định kỳ (total=0 nếu
    server không báo Content-Length).
    """
    if not release.asset_url:
        raise RuntimeError("Bản phát hành không có file cài đặt để tải.")
    name = release.asset_name or f"{APP_ID}-{release.version}-setup.exe"
    target_dir = os.path.join(tempfile.gettempdir(), "screen-translator-2k-update")
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, name)

    request = urllib.request.Request(release.asset_url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        total = int(response.headers.get("Content-Length") or release.asset_size or 0)
        downloaded = 0
        with open(target, "wb") as handle:
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded += len(chunk)
                if on_progress is not None:
                    on_progress(downloaded, total)
    return target


def is_frozen() -> bool:
    """True khi đang chạy dưới dạng exe đóng gói (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def run_installer(installer_path: str) -> None:
    """Chạy installer Inno Setup im lặng; installer sẽ đóng app và mở lại.

    Dùng cờ Inno: /SILENT (hiện progress), /NORESTART. Installer nên bật
    `CloseApplications` để tự đóng bản đang chạy trước khi ghi đè.
    """
    if not os.path.isfile(installer_path):
        raise RuntimeError("Không tìm thấy file cài đặt đã tải.")
    # /CLOSEAPPLICATIONS: installer tự đóng bản đang chạy nếu còn khoá file.
    # App tự thoát ngay sau khi gọi hàm này; installer.iss dùng [Run] để mở lại.
    flags = ["/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS"]
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
    subprocess.Popen(  # noqa: S603 — đường dẫn do updater tạo, không phải input người dùng
        [installer_path, *flags],
        creationflags=creationflags,
        close_fds=True,
    )
