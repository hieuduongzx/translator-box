"""Registry model OCR và backend suy luận ngoại tuyến."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config import config_path


@dataclass(frozen=True)
class OCRModelSpec:
    """Metadata và cấu hình RapidOCR của một model có thể chọn."""

    id: str
    label: str
    version: str
    model_type: str
    rec_language: str
    detection_hmean: float
    recognition_accuracy: float
    languages: str
    size_mb: float
    builtin: bool
    det_filename: str
    rec_filename: str


OCR_MODELS = (
    OCRModelSpec(
        "ppocrv5_mobile",
        "PP-OCRv5 mobile",
        "PPOCRV5",
        "MOBILE",
        "CH",
        79.0,
        81.29,
        "Trung giản thể/phồn thể, Anh, Nhật",
        17.7,
        True,
        "ch_PP-OCRv5_det_mobile.onnx",
        "ch_PP-OCRv5_rec_mobile.onnx",
    ),
    OCRModelSpec(
        "ppocrv6_tiny",
        "PP-OCRv6 tiny",
        "PPOCRV6",
        "TINY",
        "CH",
        80.6,
        73.5,
        "49 ngôn ngữ (không gồm tiếng Nhật)",
        5.45,
        False,
        "PP-OCRv6_det_tiny.onnx",
        "PP-OCRv6_rec_tiny.onnx",
    ),
    OCRModelSpec(
        "ppocrv6_small",
        "PP-OCRv6 small",
        "PPOCRV6",
        "SMALL",
        "CH",
        84.1,
        81.3,
        "50 ngôn ngữ",
        25.2,
        False,
        "PP-OCRv6_det_small.onnx",
        "PP-OCRv6_rec_small.onnx",
    ),
    OCRModelSpec(
        "ppocrv6_medium",
        "PP-OCRv6 medium",
        "PPOCRV6",
        "MEDIUM",
        "CH",
        86.2,
        83.2,
        "50 ngôn ngữ",
        99.7,
        False,
        "PP-OCRv6_det_medium.onnx",
        "PP-OCRv6_rec_medium.onnx",
    ),
)
OCR_MODEL_BY_ID = {model.id: model for model in OCR_MODELS}

OCR_BACKENDS = (
    ("Tự động", "auto"),
    ("CPU · ONNX Runtime", "cpu"),
    ("GPU · DirectML", "directml"),
    ("GPU · NVIDIA CUDA", "cuda"),
    ("Intel · OpenVINO", "openvino"),
)

_engine_cache: dict[tuple[str, str], object] = {}


def model_root() -> Path:
    return config_path().parent / "models" / "rapidocr"


def model_spec(model_id: str) -> OCRModelSpec:
    return OCR_MODEL_BY_ID.get(model_id, OCR_MODEL_BY_ID["ppocrv5_mobile"])


@lru_cache(maxsize=None)
def _rapidocr_package_models() -> Path | None:
    """`find_spec` quét sys.path nên chỉ tra một lần: gói không tự mọc thêm."""
    spec = importlib.util.find_spec("rapidocr")
    if spec is None or spec.origin is None:
        return None
    return Path(spec.origin).resolve().parent / "models"


def model_files(model_id: str) -> tuple[Path, Path]:
    model = model_spec(model_id)
    root = _rapidocr_package_models() if model.builtin else model_root()
    if root is None:
        root = model_root()
    return root / model.det_filename, root / model.rec_filename


def model_installed(model_id: str) -> bool:
    return all(
        path.is_file() and path.stat().st_size > 0 for path in model_files(model_id)
    )


@lru_cache(maxsize=1)
def available_onnx_providers() -> tuple[str, ...]:
    """Provider của ONNX Runtime — hằng số trong một process nên cache.

    `import onnxruntime` nạp DLL native (hàng trăm ms lần đầu) và `backend_status`
    lại gọi hàm này nhiều lần cho mỗi lần kiểm tra engine.
    """
    try:
        import onnxruntime as ort

        return tuple(ort.get_available_providers())
    except (ImportError, OSError):
        return ()


@lru_cache(maxsize=1)
def _openvino_available() -> bool:
    return importlib.util.find_spec("openvino") is not None


def backend_status(backend: str) -> tuple[bool, str]:
    providers = available_onnx_providers()
    if backend == "auto":
        resolved = resolve_backend(backend)
        ready, detail = backend_status(resolved)
        return ready, f"Tự động chọn {backend_label(resolved)}. {detail}"
    if backend == "cpu":
        ready = "CPUExecutionProvider" in providers
        return ready, (
            "ONNX Runtime CPU sẵn sàng."
            if ready
            else "Thiếu onnxruntime · chạy: pip install onnxruntime"
        )
    if backend == "directml":
        ready = "DmlExecutionProvider" in providers
        return ready, (
            "DirectML sẵn sàng cho GPU Windows."
            if ready
            else "Thiếu DirectML · chạy: pip install onnxruntime-directml"
        )
    if backend == "cuda":
        ready = "CUDAExecutionProvider" in providers
        return ready, (
            "CUDA sẵn sàng cho GPU NVIDIA."
            if ready
            else "Thiếu CUDA provider · cài onnxruntime-gpu và CUDA/cuDNN tương thích."
        )
    if backend == "openvino":
        ready = _openvino_available()
        return ready, (
            "OpenVINO sẵn sàng cho thiết bị Intel."
            if ready
            else "Thiếu OpenVINO · chạy: pip install openvino"
        )
    return False, f"Backend OCR không được hỗ trợ: {backend}"


def resolve_backend(backend: str) -> str:
    if backend != "auto":
        return backend
    providers = available_onnx_providers()
    if "CUDAExecutionProvider" in providers:
        return "cuda"
    if "DmlExecutionProvider" in providers:
        return "directml"
    if _openvino_available():
        return "openvino"
    return "cpu"


def backend_label(backend: str) -> str:
    return next((label for label, value in OCR_BACKENDS if value == backend), backend)


def _engine_params(model: OCRModelSpec, backend: str) -> dict:
    from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion

    resolved = resolve_backend(backend)
    engine_type = (
        EngineType.OPENVINO if resolved == "openvino" else EngineType.ONNXRUNTIME
    )
    params = {
        "Det.engine_type": engine_type,
        # RapidOCR 3.9 dùng tên file ``multi_PP-OCRv6_*`` nhưng resolver lại
        # yêu cầu một ngôn ngữ cụ thể (vd. ``ch``), không chấp nhận ``multi``.
        # Truyền LangDet.MULTI làm mọi model v6 báo "Unsupported det.lang_type".
        "Det.lang_type": LangDet.CH,
        "Det.model_type": getattr(ModelType, model.model_type),
        "Det.ocr_version": getattr(OCRVersion, model.version),
        "Rec.engine_type": engine_type,
        "Rec.lang_type": getattr(LangRec, model.rec_language),
        "Rec.model_type": getattr(ModelType, model.model_type),
        "Rec.ocr_version": getattr(OCRVersion, model.version),
        "Cls.engine_type": engine_type,
    }
    if not model.builtin:
        params["Global.model_root_dir"] = str(model_root())
    if resolved == "directml":
        params["EngineConfig.onnxruntime.use_dml"] = True
    elif resolved == "cuda":
        params["EngineConfig.onnxruntime.use_cuda"] = True
    return params


def get_rapid_engine(model_id: str, backend: str):
    """Khởi tạo lười; RapidOCR tự tải model còn thiếu vào thư mục ứng dụng."""
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise RuntimeError(
            "OCR ngoại tuyến cần rapidocr và onnxruntime. Cài requirements.txt."
        ) from exc

    model = model_spec(model_id)
    resolved = resolve_backend(backend)
    # Engine đã dựng thì trả ngay: kiểm tra lại backend + file model là I/O đĩa
    # và truy vấn provider native, mà OCR live gọi hàm này mỗi frame.
    engine = _engine_cache.get((model.id, resolved))
    if engine is not None:
        return engine
    ready, detail = backend_status(resolved)
    if not ready:
        raise RuntimeError(detail)
    model_root().mkdir(parents=True, exist_ok=True)
    engine = RapidOCR(params=_engine_params(model, resolved))
    _engine_cache[(model.id, resolved)] = engine
    return engine


def forget_engines() -> None:
    """Bỏ engine đã cache (sau khi tải model mới) để lần sau dựng lại."""
    _engine_cache.clear()


def download_model(model_id: str, backend: str = "cpu") -> None:
    """Tải và kiểm tra model bằng chính loader có checksum của RapidOCR."""
    forget_engines()
    get_rapid_engine(model_id, backend)
    if not model_installed(model_id):
        paths = ", ".join(str(path) for path in model_files(model_id))
        raise RuntimeError(f"Model tải xong nhưng chưa tìm thấy file: {paths}")
