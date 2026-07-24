from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from hotkeys import HotkeyManager  # noqa: E402


class FakeKeyboard:
    def __init__(self) -> None:
        self.added: list[str] = []
        self.removed: list[str] = []

    def add_hotkey(self, combo, _callback):
        if combo == "invalid":
            raise ValueError("invalid combo")
        self.added.append(combo)
        return f"handle:{combo}"

    def remove_hotkey(self, handle):
        self.removed.append(handle)


class HotkeyManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = HotkeyManager(lambda _action: None)
        self.keyboard = FakeKeyboard()
        self.manager._keyboard = self.keyboard

    def test_rejects_duplicates_before_registration(self) -> None:
        error = self.manager.apply({"one": "ctrl+a", "two": "ctrl+a"})

        self.assertEqual(error, "Phím tắt bị trùng.")
        self.assertEqual(self.keyboard.added, [])

    def test_failed_update_keeps_previous_mapping(self) -> None:
        self.assertIsNone(self.manager.apply({"one": "ctrl+a"}))

        error = self.manager.apply({"two": "ctrl+b", "bad": "invalid"})

        self.assertIn("invalid combo", error)
        self.assertNotIn("handle:ctrl+a", self.keyboard.removed)
        self.assertIn("handle:ctrl+b", self.keyboard.removed)


if __name__ == "__main__":
    unittest.main()
