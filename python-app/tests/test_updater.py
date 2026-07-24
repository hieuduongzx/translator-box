from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import updater  # noqa: E402


class VersionCompareTests(unittest.TestCase):
    def test_parse_strips_prefix_and_suffix(self) -> None:
        self.assertEqual(updater.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(updater.parse_version("1.0.0-beta"), (1, 0, 0))
        self.assertEqual(updater.parse_version(""), (0,))

    def test_is_newer_compares_numerically(self) -> None:
        self.assertTrue(updater.is_newer("1.0.1", "1.0.0"))
        self.assertTrue(updater.is_newer("v1.1", "1.0.9"))
        self.assertFalse(updater.is_newer("1.0.0", "1.0.0"))
        self.assertFalse(updater.is_newer("0.9.0", "1.0.0"))

    def test_is_newer_handles_uneven_length(self) -> None:
        self.assertTrue(updater.is_newer("1.0.1", "1.0"))
        self.assertFalse(updater.is_newer("1.0", "1.0.0"))


class AssetSelectionTests(unittest.TestCase):
    def test_prefers_exe_installer_over_zip(self) -> None:
        assets = [
            {"name": "notes.txt", "browser_download_url": "u0", "size": 1},
            {"name": "app-1.0.0-win64.zip", "browser_download_url": "u1", "size": 2},
            {"name": "app-1.0.0-setup.exe", "browser_download_url": "u2", "size": 3},
        ]
        url, name, size = updater._pick_asset(assets)
        self.assertEqual((url, name, size), ("u2", "app-1.0.0-setup.exe", 3))

    def test_falls_back_to_zip_when_no_exe(self) -> None:
        assets = [{"name": "app.zip", "browser_download_url": "z", "size": 9}]
        url, name, _size = updater._pick_asset(assets)
        self.assertEqual((url, name), ("z", "app.zip"))

    def test_returns_none_without_installable_asset(self) -> None:
        self.assertEqual(updater._pick_asset([{"name": "x.txt"}]), (None, None, 0))


class CheckLatestTests(unittest.TestCase):
    def _response(self, payload: dict) -> mock.MagicMock:
        response = mock.MagicMock()
        response.read.return_value = json.dumps(payload).encode("utf-8")
        response.__enter__.return_value = response
        return response

    def test_parses_release_and_selects_asset(self) -> None:
        payload = {
            "tag_name": "v1.2.0",
            "name": "Bản 1.2.0",
            "body": "- Sửa lỗi",
            "html_url": "https://example/releases/v1.2.0",
            "assets": [
                {
                    "name": "Setup.exe",
                    "browser_download_url": "https://example/Setup.exe",
                    "size": 123,
                }
            ],
        }
        with mock.patch.object(
            updater.urllib.request, "urlopen", return_value=self._response(payload)
        ):
            release = updater.check_latest("owner/repo")
        self.assertIsNotNone(release)
        self.assertEqual(release.version, "1.2.0")
        self.assertEqual(release.asset_url, "https://example/Setup.exe")

    def test_ignores_prerelease_and_draft(self) -> None:
        for payload in ({"tag_name": "v2", "prerelease": True}, {"draft": True}):
            with mock.patch.object(
                updater.urllib.request, "urlopen", return_value=self._response(payload)
            ):
                self.assertIsNone(updater.check_latest("owner/repo"))

    def test_returns_none_on_network_error(self) -> None:
        with mock.patch.object(
            updater.urllib.request,
            "urlopen",
            side_effect=updater.urllib.error.URLError("offline"),
        ):
            self.assertIsNone(updater.check_latest("owner/repo"))

    def test_find_update_skips_when_not_newer(self) -> None:
        payload = {"tag_name": f"v{updater.APP_VERSION}"}
        with mock.patch.object(
            updater.urllib.request, "urlopen", return_value=self._response(payload)
        ):
            self.assertIsNone(updater.find_update("owner/repo"))


if __name__ == "__main__":
    unittest.main()
