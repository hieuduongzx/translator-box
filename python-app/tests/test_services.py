from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import services  # noqa: E402
from ui_utils import _sig_differs as services_sig_differs  # noqa: E402


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


class MissingDependencyTests(unittest.TestCase):
    def test_missing_module_reports_install_command(self) -> None:
        """Thiếu gói phải nói tên gói pip và câu lệnh, không phải lỗi thô."""
        real_import = services.importlib.import_module

        def fail_pyperclip(name: str):
            if name == "pyperclip":
                raise ImportError("No module named 'pyperclip'")
            return real_import(name)

        with mock.patch.object(
            services.importlib, "import_module", side_effect=fail_pyperclip
        ):
            with self.assertRaises(RuntimeError) as caught:
                services.paste_replacement("Xin chào")

        message = str(caught.exception)
        self.assertIn("pyperclip", message)
        self.assertIn("requirements.txt", message)
        self.assertNotIn("No module named", message)

    def test_startup_warning_lists_every_missing_package(self) -> None:
        services._package_available.cache_clear()
        try:
            with mock.patch.object(
                services,
                "_package_available",
                side_effect=lambda name: name not in {"pyperclip", "PIL"},
            ):
                message = services.missing_runtime_packages()
        finally:
            services._package_available.cache_clear()

        self.assertIn("pyperclip", message)
        self.assertIn("Pillow", message)  # tên gói pip, không phải tên module
        self.assertNotIn("keyboard", message)
        self.assertIn("requirements.txt", message)

    def test_startup_warning_is_empty_when_dependencies_present(self) -> None:
        with mock.patch.object(services, "_package_available", return_value=True):
            self.assertEqual(services.missing_runtime_packages(), "")


class CaptureTests(unittest.TestCase):
    def test_capture_writes_png_and_returns_signature_without_rereading_file(
        self,
    ) -> None:
        """Chữ ký tính ngay từ ảnh trong RAM, không mở lại file vừa ghi."""
        grabbed = Image.new("RGB", (120, 60), (20, 30, 40))
        ImageDraw.Draw(grabbed).rectangle((10, 10, 60, 40), fill=(240, 240, 240))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frame.png"
            with mock.patch.object(
                services, "_grab_screen", return_value=grabbed
            ) as grab:
                signature = services.capture((0, 0, 120, 60), path)

            self.assertEqual(grab.call_count, 1)
            self.assertTrue(path.exists())
            self.assertEqual(len(signature), 48 * 48)
            expected = (
                grabbed.convert("L")
                .resize((48, 48), Image.Resampling.BILINEAR)
                .tobytes()
            )
            self.assertEqual(signature, expected)

    def test_capture_signature_tracks_visible_change(self) -> None:
        first = Image.new("RGB", (120, 60), (250, 250, 250))
        second = first.copy()
        ImageDraw.Draw(second).rectangle((0, 0, 119, 59), fill=(10, 10, 10))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frame.png"
            with mock.patch.object(services, "_grab_screen", return_value=first):
                before = services.capture((0, 0, 120, 60), path)
            with mock.patch.object(services, "_grab_screen", return_value=first.copy()):
                same = services.capture((0, 0, 120, 60), path)
            with mock.patch.object(services, "_grab_screen", return_value=second):
                after = services.capture((0, 0, 120, 60), path)

        self.assertFalse(services_sig_differs(before, same))
        self.assertTrue(services_sig_differs(before, after))


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

    def test_normal_line_spacing_stays_in_one_block(self) -> None:
        """Đoạn 2+ dòng giãn cách tới ~2 lần chiều cao vẫn là một khối để dịch liền."""
        regions = [
            services.TextRegion("Wait, do you mean that the", (10, 100, 250, 120)),
            services.TextRegion("whole plan was a secret from", (10, 140, 245, 160)),
            services.TextRegion("the very beginning?!", (10, 180, 170, 200)),
        ]

        blocks = services.merge_regions_into_blocks(regions)

        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].line_count, 3)
        self.assertEqual(
            blocks[0].text,
            "Wait, do you mean that the whole plan was a secret from "
            "the very beginning?!",
        )

    def test_vertical_cjk_columns_read_right_to_left(self) -> None:
        """Cột chữ dọc Nhật phải nối theo thứ tự phải→trái, không đảo ngược."""
        regions = [
            services.TextRegion("これは", (300, 40, 320, 140)),
            services.TextRegion("テスト", (280, 40, 300, 140)),
            services.TextRegion("です", (260, 40, 280, 140)),
        ]

        blocks = services.merge_regions_into_blocks(regions)

        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].text, "これはテストです")

    def test_manga_blocks_do_not_merge_parallel_speech_bubbles(self) -> None:
        regions = [
            services.TextRegion("THIS IS", (100, 100, 160, 118)),
            services.TextRegion("SO...", (166, 100, 205, 118)),
            services.TextRegion("THE NEXT", (105, 122, 185, 140)),
            services.TextRegion("MISSION?", (108, 144, 182, 162)),
            services.TextRegion("YOU", (320, 103, 360, 121)),
            services.TextRegion("SEEM", (314, 125, 368, 143)),
            services.TextRegion("MAD...", (316, 147, 367, 165)),
        ]

        blocks = services.merge_regions_into_blocks(regions)

        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].text, "THIS IS SO... THE NEXT MISSION?")
        self.assertEqual(blocks[0].line_count, 3)
        self.assertEqual(blocks[1].text, "YOU SEEM MAD...")
        self.assertEqual(blocks[1].line_count, 3)

    def test_manga_detail_pass_maps_boxes_back_to_source_image(self) -> None:
        result = mock.Mock(
            txts=("SMALL TEXT",),
            boxes=[
                [[16.0, 12.8], [160.0, 12.8], [160.0, 48.0], [16.0, 48.0]]
            ],
        )
        engine = mock.Mock(return_value=result)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "manga.png"
            Image.new("RGB", (200, 100), (245, 245, 245)).save(source)
            with mock.patch.object(
                services.ocr_runtime, "get_rapid_engine", return_value=engine
            ):
                _text, regions = services._ocr_rapid_data(
                    source, "ppocrv5_mobile", "cpu"
                )

        prepared_path = Path(engine.call_args.args[0])
        self.assertNotEqual(prepared_path, source)
        self.assertFalse(prepared_path.exists())
        self.assertEqual(regions[0].bbox, (10, 8, 100, 30))

    def test_reconstructed_line_keeps_original_text_colour(self) -> None:
        """Màu chữ dịch phải sát màu gốc, không bị pixel khử răng làm nhạt."""
        from PIL import ImageFont

        text_rgb = (220, 30, 30)
        image = Image.new("RGB", (320, 60), (255, 255, 255))
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 22)
        draw.text((16, 16), "Sample gy", font=font, fill=text_rgb)
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "line.png")
            image.save(path)
            box = draw.textbbox((16, 16), "Sample gy", font=font)
            region = services.TextRegion("Sample gy", box)
            _size, visuals = services.reconstruct_layout(path, [region])

        visual = visuals[0]
        for channel, expected in zip(visual.fg, text_rgb):
            self.assertLess(
                abs(channel - expected),
                40,
                f"màu chữ lệch quá xa: {visual.fg} vs {text_rgb}",
            )
        # Hộp ink phải nằm gọn trong hộp OCR và đúng chiều cao nét chữ.
        self.assertIsNotNone(visual.ink_rect)
        self.assertGreaterEqual(visual.ink_rect[1], box[1] - 2)
        self.assertLessEqual(visual.ink_rect[3], box[3] + 2)
        self.assertGreater(visual.stroke_thickness, 0)

    def test_identical_region_reuses_inpainted_background(self) -> None:
        """Live chụp lại cùng một vùng → không inpaint lại miếng nền không đổi."""
        from PIL import ImageFont

        image = Image.new("RGB", (320, 60), (255, 255, 255))
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 22)
        draw.text((16, 16), "Sample gy", font=font, fill=(30, 30, 30))
        box = draw.textbbox((16, 16), "Sample gy", font=font)
        region = services.TextRegion("Sample gy", box)

        services._inpaint_cache.clear()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "line.png")
            image.save(path)
            import cv2  # type: ignore

            with mock.patch.object(
                cv2, "inpaint", wraps=cv2.inpaint
            ) as inpaint:
                first_size, first = services.reconstruct_layout(path, [region])
                second_size, second = services.reconstruct_layout(path, [region])

        self.assertEqual(inpaint.call_count, 1)
        self.assertEqual(first_size, second_size)
        self.assertEqual(first[0].patch_rgb, second[0].patch_rgb)
        self.assertEqual(first[0].ink_rect, second[0].ink_rect)
        self.assertEqual(first[0].fg, second[0].fg)

    def test_per_line_fallback_runs_in_parallel_and_keeps_order(self) -> None:
        """Dịch vụ gộp dòng → dịch lại từng dòng, song song nhưng đúng thứ tự."""
        regions = [
            services.TextRegion(f"line{index}", (0, index * 12, 20, index * 12 + 10))
            for index in range(4)
        ]
        active = 0
        peak = 0
        lock = threading.Lock()

        def fake_translate(text: str, *_args, **_kwargs) -> str:
            nonlocal active, peak
            if "\n" in text:  # lần gộp: trả về ít dòng hơn để kích fallback
                return "mọi thứ dồn một dòng"
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return "dịch:" + text

        with mock.patch.object(services, "translate", side_effect=fake_translate):
            translated = services.translate_regions(regions, "vi")

        self.assertEqual(
            translated, ["dịch:line0", "dịch:line1", "dịch:line2", "dịch:line3"]
        )
        self.assertGreater(peak, 1)

    def test_clipboard_wait_returns_as_soon_as_text_appears(self) -> None:
        values = ["", "", "Xin chào"]

        with mock.patch.dict(
            sys.modules, {"pyperclip": mock.MagicMock(paste=lambda: values.pop(0))}
        ):
            started = time.perf_counter()
            text = services._wait_clipboard_text(timeout=2.0)
            elapsed = time.perf_counter() - started

        self.assertEqual(text, "Xin chào")
        self.assertLess(elapsed, 0.5)

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
