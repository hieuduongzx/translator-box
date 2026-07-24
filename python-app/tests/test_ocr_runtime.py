from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import ocr_runtime  # noqa: E402


class OCRRuntimeTests(unittest.TestCase):
    def test_registry_contains_requested_ppocrv6_variants(self) -> None:
        self.assertEqual(
            {
                "ppocrv6_tiny",
                "ppocrv6_small",
                "ppocrv6_medium",
            }
            - set(ocr_runtime.OCR_MODEL_BY_ID),
            set(),
        )

    def test_builtin_model_uses_package_directory(self) -> None:
        with mock.patch.object(
            ocr_runtime, "_rapidocr_package_models", return_value=Path("bundled")
        ):
            detection, recognition = ocr_runtime.model_files("ppocrv5_mobile")

        self.assertEqual(detection, Path("bundled/ch_PP-OCRv5_det_mobile.onnx"))
        self.assertEqual(recognition, Path("bundled/ch_PP-OCRv5_rec_mobile.onnx"))

    def test_auto_backend_prefers_cuda_then_directml(self) -> None:
        with mock.patch.object(
            ocr_runtime,
            "available_onnx_providers",
            return_value=("DmlExecutionProvider", "CUDAExecutionProvider"),
        ):
            self.assertEqual(ocr_runtime.resolve_backend("auto"), "cuda")

    def test_missing_backend_has_actionable_message(self) -> None:
        with mock.patch.object(
            ocr_runtime, "available_onnx_providers", return_value=()
        ):
            ready, detail = ocr_runtime.backend_status("directml")

        self.assertFalse(ready)
        self.assertIn("onnxruntime-directml", detail)

    def test_directml_config_applies_to_entire_pipeline(self) -> None:
        with mock.patch.object(
            ocr_runtime,
            "available_onnx_providers",
            return_value=("DmlExecutionProvider", "CPUExecutionProvider"),
        ):
            params = ocr_runtime._engine_params(
                ocr_runtime.model_spec("ppocrv6_small"), "directml"
            )

        self.assertTrue(params["EngineConfig.onnxruntime.use_dml"])
        self.assertEqual(params["Det.engine_type"].value, "onnxruntime")
        self.assertEqual(params["Rec.engine_type"].value, "onnxruntime")
        self.assertEqual(params["Cls.engine_type"].value, "onnxruntime")


if __name__ == "__main__":
    unittest.main()
