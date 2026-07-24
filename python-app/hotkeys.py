"""Phím tắt toàn cục dựa trên thư viện `keyboard`."""

from __future__ import annotations

from typing import Callable


class HotkeyManager:
    def __init__(self, dispatch: Callable[[str], None]):
        # dispatch(action) phải an toàn khi gọi từ thread nền.
        self._dispatch = dispatch
        self._keyboard = None
        self._handles: list = []
        try:
            import keyboard  # type: ignore

            self._keyboard = keyboard
        except Exception:  # noqa: BLE001
            self._keyboard = None

    @property
    def available(self) -> bool:
        return self._keyboard is not None

    def apply(self, mapping: dict[str, str]) -> str | None:
        """Đăng ký mapping mới; giữ mapping cũ nếu có phím không hợp lệ."""
        if not self.available:
            return "Thiếu thư viện 'keyboard' — phím tắt bị tắt. Chạy: pip install keyboard"
        normalized = {
            action: (combo or "").strip().lower()
            for action, combo in mapping.items()
            if isinstance(combo, str)
        }
        enabled = [combo for combo in normalized.values() if combo]
        if len(enabled) != len(set(enabled)):
            return "Phím tắt bị trùng."

        new_handles = []
        errors: list[str] = []
        for action, combo in normalized.items():
            if not combo:
                continue
            try:
                handle = self._keyboard.add_hotkey(
                    combo, lambda action=action: self._dispatch(action)
                )
                new_handles.append(handle)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{combo}: {exc}")
                break
        if errors:
            self._remove_handles(new_handles)
            return " · ".join(errors)
        self._remove_handles(self._handles)
        self._handles = new_handles
        return None

    def clear(self) -> None:
        self._remove_handles(self._handles)
        self._handles = []

    def _remove_handles(self, handles: list) -> None:
        if self.available:
            for handle in handles:
                try:
                    self._keyboard.remove_hotkey(handle)
                except Exception:  # noqa: BLE001
                    pass
