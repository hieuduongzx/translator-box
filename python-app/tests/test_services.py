from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import services  # noqa: E402


class AnalyzeColorsTests(unittest.TestCase):
    def analyze(self, image: Image.Image):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.png"
            image.save(path)
            return services.analyze_colors(path)

    def test_ignores_selection_overlay_chrome(self) -> None:
        background = (37, 55, 74)
        image = Image.new("RGB", (96, 48), background)
        draw = ImageDraw.Draw(image)
        for offset in range(4):
            draw.rectangle(
                (offset, offset, 95 - offset, 47 - offset),
                outline=(243, 178, 63),
            )

        bg, fg = self.analyze(image)

        self.assertEqual(bg, background)
        self.assertEqual(fg, (240, 240, 240))

    def test_layout_color_comes_from_around_each_text_box(self) -> None:
        background = (76, 91, 108)
        image = Image.new("RGB", (120, 60), background)
        ImageDraw.Draw(image).rectangle((24, 20, 94, 38), fill=(245, 245, 245))
        regions = [services.TextRegion("Source text", (24, 20, 95, 39))]

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "layout.png"
            image.save(path)
            image_size, colors = services.analyze_layout_colors(path, regions)

        self.assertEqual(image_size, (120, 60))
        self.assertEqual(colors, [(background, (240, 240, 240))])

    def test_keeps_real_color_instead_of_quantized_bucket(self) -> None:
        background = (203, 211, 219)
        bg, fg = self.analyze(Image.new("RGB", (64, 32), background))

        self.assertEqual(bg, background)
        self.assertEqual(fg, (24, 24, 24))

    def test_handles_tiny_regions(self) -> None:
        background = (24, 25, 26)
        bg, fg = self.analyze(Image.new("RGB", (3, 3), background))

        self.assertEqual(bg, background)
        self.assertEqual(fg, (240, 240, 240))


class LayoutOcrTests(unittest.TestCase):
    def test_rapidocr_converts_quads_to_overlay_regions(self) -> None:
        result = mock.Mock(
            txts=("日本語", "Hello"),
            boxes=[
                [[12.2, 8.1], [68.7, 9.0], [67.9, 27.8], [11.6, 26.9]],
                [[10.0, 35.0], [60.0, 35.0], [60.0, 50.0], [10.0, 50.0]],
            ],
        )
        engine = mock.Mock(return_value=result)
        with mock.patch.object(
            services.ocr_runtime, "get_rapid_engine", return_value=engine
        ) as get_engine:
            text, regions = services._ocr_rapid_data(
                "capture.png", "ppocrv6_small", "cpu"
            )

        self.assertEqual(text, "日本語\nHello")
        self.assertEqual(
            regions,
            [
                services.TextRegion("日本語", (12, 8, 69, 28)),
                services.TextRegion("Hello", (10, 35, 60, 50)),
            ],
        )
        engine.assert_called_once_with("capture.png", use_cls=False)
        get_engine.assert_called_once_with("ppocrv6_small", "cpu")

    def test_auto_ocr_falls_back_to_next_available_engine(self) -> None:
        with (
            mock.patch.object(
                services, "ocr_engine_status", return_value=(True, "ready")
            ),
            mock.patch.object(
                services,
                "_ocr_text_with",
                side_effect=[RuntimeError("language pack missing"), "Recognized"],
            ) as run,
        ):
            text = services.ocr("capture.png", "eng", "auto")

        self.assertEqual(text, "Recognized")
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            ["windows", "rapidocr"],
        )

    def test_auto_candidates_only_use_supported_engines(self) -> None:
        self.assertEqual(services._ocr_candidates("auto"), ("windows", "rapidocr"))

    def test_unknown_ocr_engine_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "không được hỗ trợ"):
            services.ocr("capture.png", "eng", "unknown")

    def test_translation_keeps_one_result_per_region(self) -> None:
        regions = [
            services.TextRegion("Hello", (0, 0, 20, 10)),
            services.TextRegion("World", (0, 12, 20, 22)),
        ]
        with mock.patch.object(
            services, "translate", return_value="Xin chào\nThế giới"
        ) as translate:
            translated = services.translate_regions(regions, "vi")

        self.assertEqual(translated, ["Xin chào", "Thế giới"])
        translate.assert_called_once_with(
            "Hello\nWorld",
            "vi",
            "google",
            llm_endpoint="",
            llm_api_key="",
            llm_model="",
        )

    def test_llm_translation_uses_openai_compatible_chat_endpoint(self) -> None:
        response = mock.MagicMock()
        response.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "Xin chào"}}]}
        ).encode()
        response.__enter__.return_value = response

        with mock.patch.object(
            services.urllib.request, "urlopen", return_value=response
        ) as urlopen:
            translated = services.translate(
                "Hello",
                "vi",
                "llm",
                llm_endpoint="http://example.test/v1",
                llm_api_key="test-key",
                llm_model="mistral/mistral-small-latest",
            )

        self.assertEqual(translated, "Xin chào")
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "http://example.test/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(payload["model"], "mistral/mistral-small-latest")
        self.assertIn("Vietnamese", payload["messages"][0]["content"])

    def test_llm_translation_parses_event_stream_with_done_trailer(self) -> None:
        # LiteLLM trả text/event-stream: object JSON đầy đủ rồi bám 'data: [DONE]'.
        response = mock.MagicMock()
        response.read.return_value = (
            b'{"choices": [{"message": {"content": "Xin ch\xc3\xa0o"}}]}'
            b"data: [DONE]\n\n"
        )
        response.__enter__.return_value = response

        with mock.patch.object(
            services.urllib.request, "urlopen", return_value=response
        ):
            translated = services.translate(
                "Hello",
                "vi",
                "llm",
                llm_endpoint="http://example.test/v1",
                llm_api_key="test-key",
                llm_model="mistral/mistral-small-latest",
            )

        self.assertEqual(translated, "Xin chào")

    def test_llm_translation_parses_streaming_deltas(self) -> None:
        response = mock.MagicMock()
        response.read.return_value = (
            b'data: {"choices": [{"delta": {"content": "Xin "}}]}\n\n'
            b'data: {"choices": [{"delta": {"content": "ch\xc3\xa0o"}}]}\n\n'
            b"data: [DONE]\n\n"
        )
        response.__enter__.return_value = response

        with mock.patch.object(
            services.urllib.request, "urlopen", return_value=response
        ):
            translated = services.translate(
                "Hello",
                "vi",
                "llm",
                llm_endpoint="http://example.test/v1",
                llm_api_key="test-key",
                llm_model="mistral/mistral-small-latest",
            )

        self.assertEqual(translated, "Xin chào")

    def test_llm_translation_requires_api_key_before_network_request(self) -> None:
        with (
            mock.patch.object(services.urllib.request, "urlopen") as urlopen,
            self.assertRaisesRegex(RuntimeError, "chưa có API key"),
        ):
            services.translate(
                "Hello",
                "vi",
                "llm",
                llm_endpoint="http://example.test/v1",
                llm_api_key="",
                llm_model="mistral/mistral-small-latest",
            )

        urlopen.assert_not_called()

    def test_llm_translation_rejects_malformed_success_response(self) -> None:
        response = mock.MagicMock()
        response.read.return_value = b'{"choices": {"unexpected": true}}'
        response.__enter__.return_value = response

        with (
            mock.patch.object(
                services.urllib.request, "urlopen", return_value=response
            ),
            self.assertRaisesRegex(RuntimeError, "không trả về bản dịch"),
        ):
            services.translate(
                "Hello",
                "vi",
                "llm",
                llm_endpoint="http://example.test/v1",
                llm_api_key="test-key",
                llm_model="mistral/mistral-small-latest",
            )


if __name__ == "__main__":
    unittest.main()
