"""Liệt kê ứng dụng desktop và nhận diện ứng dụng đang foreground trên Windows."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_GW_OWNER = 4
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_FRIENDLY_EXECUTABLE_NAMES = {
    "explorer": "File Explorer",
    "msedge": "Microsoft Edge",
    "steamwebhelper": "Steam",
    "systemsettings": "Cài đặt Windows",
    "textinputhost": "Windows Text Input",
}
_TITLE_AS_APPLICATION_NAME = {"applicationframehost", "python", "pythonw"}


@dataclass(frozen=True)
class DesktopApplication:
    """Một ứng dụng có ít nhất một cửa sổ top-level đang hiển thị."""

    application_id: str
    name: str
    title: str

    @property
    def label(self) -> str:
        key = self.name.casefold()
        if key in _TITLE_AS_APPLICATION_NAME and self.title:
            return self.title
        return _FRIENDLY_EXECUTABLE_NAMES.get(key, self.name)


def _windows_api():
    if os.name != "nt":
        return None
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetForegroundWindow.restype = wintypes.HWND
    kernel32.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return user32, kernel32


def _process_image(kernel32, process_id: int) -> str:
    process = kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, process_id
    )
    if not process:
        return ""
    try:
        capacity = 32768
        size = wintypes.DWORD(capacity)
        buffer = ctypes.create_unicode_buffer(capacity)
        if not kernel32.QueryFullProcessImageNameW(
            process, 0, buffer, ctypes.byref(size)
        ):
            return ""
        return buffer.value
    finally:
        kernel32.CloseHandle(process)


def _window_process_id(user32, hwnd: int) -> int:
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    return process_id.value


def _application_identity(kernel32, process_id: int) -> tuple[str, str]:
    image = _process_image(kernel32, process_id)
    if image:
        return image.casefold(), Path(image).stem
    return f"pid:{process_id}", f"PID {process_id}"


def foreground_application_id() -> str:
    """ID ổn định theo executable của ứng dụng đang nhận input."""

    api = _windows_api()
    if api is None:
        return ""
    user32, kernel32 = api
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    process_id = _window_process_id(user32, hwnd)
    if not process_id:
        return ""
    return _application_identity(kernel32, process_id)[0]


def list_desktop_applications() -> list[DesktopApplication]:
    """Danh sách ứng dụng có cửa sổ hiển thị, gộp theo executable."""

    api = _windows_api()
    if api is None:
        return []
    user32, kernel32 = api
    current_process_id = os.getpid()
    applications: dict[str, DesktopApplication] = {}

    def collect(hwnd, _lparam) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, _GW_OWNER):
            return True
        if user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & _WS_EX_TOOLWINDOW:
            return True
        title_length = user32.GetWindowTextLengthW(hwnd)
        if title_length <= 0:
            return True
        process_id = _window_process_id(user32, hwnd)
        if not process_id or process_id == current_process_id:
            return True
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)
        title = " ".join(title_buffer.value.split())[:80]
        if not title:
            return True
        application_id, name = _application_identity(kernel32, process_id)
        applications.setdefault(
            application_id,
            DesktopApplication(application_id, name, title),
        )
        return True

    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    callback = callback_type(collect)
    user32.EnumWindows(callback, 0)
    return sorted(applications.values(), key=lambda app: app.label.casefold())
