"""OCR ngoại tuyến/Windows, chụp màn hình và dịch Google/Bing/LLM.

- OCR: Auto (Windows → RapidOCR), Windows OCR hoặc RapidOCR đa model/backend.
- Dịch: Google, Bing hoặc endpoint LLM chuẩn OpenAI-compatible.
"""

from __future__ import annotations

import importlib.util
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import ocr_runtime

_UA = "ScreenTranslator2K-Py/0.1"


@dataclass(frozen=True)
class TextRegion:
    """Một dòng OCR cùng hộp giới hạn theo tọa độ pixel của ảnh nguồn."""

    text: str
    bbox: tuple[int, int, int, int]


def ocr(
    image_path: str | Path,
    language: str,
    engine: str = "rapidocr",
    model: str = "ppocrv5_mobile",
    backend: str = "auto",
) -> str:
    """OCR ảnh theo engine đã chọn. Auto thử engine nhanh nhất trước."""
    errors: list[str] = []
    ran = False
    for candidate in _ocr_candidates(engine):
        available, detail = ocr_engine_status(candidate)
        if not available:
            errors.append(detail)
            continue
        try:
            text = _ocr_text_with(
                candidate, image_path, language, model=model, backend=backend
            )
        except Exception as exc:  # noqa: BLE001
            if engine != "auto":
                raise
            errors.append(f"{_OCR_ENGINE_LABELS[candidate]}: {exc}")
            continue
        ran = True
        if text.strip() or engine != "auto":
            return text.strip()
    if errors and (engine != "auto" or not ran):
        message = errors[-1] if engine != "auto" else " | ".join(errors)
        raise RuntimeError(message)
    return ""


def ocr_layout(
    image_path: str | Path,
    language: str,
    engine: str = "rapidocr",
    model: str = "ppocrv5_mobile",
    backend: str = "auto",
) -> list[TextRegion]:
    """OCR theo từng dòng, giữ bounding box để dựng bản dịch đúng vị trí."""
    errors: list[str] = []
    ran = False
    for candidate in _ocr_candidates(engine):
        available, detail = ocr_engine_status(candidate)
        if not available:
            errors.append(detail)
            continue
        try:
            text, regions = _ocr_layout_with(
                candidate, image_path, language, model=model, backend=backend
            )
        except Exception as exc:  # noqa: BLE001
            if engine != "auto":
                raise
            errors.append(f"{_OCR_ENGINE_LABELS[candidate]}: {exc}")
            continue
        ran = True
        if regions:
            return regions
        if text.strip():
            from PIL import Image

            with Image.open(image_path) as image:
                width, height = image.size
            return [TextRegion(text.strip(), (0, 0, width, height))]
        if engine != "auto":
            return []
    if errors and (engine != "auto" or not ran):
        message = errors[-1] if engine != "auto" else " | ".join(errors)
        raise RuntimeError(message)
    return []


def _is_cjk(ch: str) -> bool:
    """True nếu ký tự thuộc hệ chữ CJK (Trung/Nhật/Hàn) — không dùng dấu cách."""
    code = ord(ch)
    return (
        0x3040 <= code <= 0x30FF  # Hiragana + Katakana
        or 0x3400 <= code <= 0x4DBF  # CJK Ext A
        or 0x4E00 <= code <= 0x9FFF  # CJK Unified
        or 0xF900 <= code <= 0xFAFF  # CJK Compatibility
        or 0xAC00 <= code <= 0xD7A3  # Hangul
        or 0x3000 <= code <= 0x303F  # CJK punctuation
        or 0xFF00 <= code <= 0xFFEF  # Fullwidth
    )


def _join_wrapped(prev: str, nxt: str) -> str:
    """Nối hai dòng bị wrap: bỏ dấu cách với CJK, gộp gạch nối cuối dòng."""
    prev = prev.rstrip()
    nxt = nxt.lstrip()
    if not prev:
        return nxt
    if not nxt:
        return prev
    a, b = prev[-1], nxt[0]
    if a == "-" and b.islower():  # gạch nối ngắt từ ở cuối dòng → ghép liền
        return prev[:-1] + nxt
    if _is_cjk(a) or _is_cjk(b):  # CJK không chèn dấu cách
        return prev + nxt
    return prev + " " + nxt


def _group_into_lines(regions: list[TextRegion]) -> tuple[list[dict], float]:
    """Gom các ô OCR có cùng tâm dọc thành từng *dòng*, sắp trái→phải.

    OCR (nhất là PP-OCR) hay tách một dòng hiển thị thành nhiều ô cỡ từ/cụm,
    đặc biệt khi keyword được tô màu. Trả về danh sách dòng (mỗi dòng gồm các ô
    đã xếp theo trục ngang + top/bottom) và chiều cao dòng trung vị.
    """
    items = [r for r in regions if r.text.strip()]
    if not items:
        return [], 1.0
    heights = sorted(max(1, r.bbox[3] - r.bbox[1]) for r in items)
    median_h = float(heights[len(heights) // 2])

    def y_center(region: TextRegion) -> float:
        return (region.bbox[1] + region.bbox[3]) / 2

    items.sort(key=y_center)
    lines: list[dict] = []
    for region in items:
        center = y_center(region)
        if lines and abs(center - lines[-1]["center"]) <= median_h * 0.6:
            line = lines[-1]
            line["regions"].append(region)
            line["top"] = min(line["top"], region.bbox[1])
            line["bottom"] = max(line["bottom"], region.bbox[3])
            line["center"] = (line["top"] + line["bottom"]) / 2
        else:
            lines.append(
                {
                    "regions": [region],
                    "top": region.bbox[1],
                    "bottom": region.bbox[3],
                    "center": center,
                }
            )
    for line in lines:
        line["regions"].sort(key=lambda r: r.bbox[0])  # trái → phải
    return lines, median_h


def _line_text(line: dict) -> str:
    text = ""
    for region in line["regions"]:
        piece = region.text.strip()
        text = _join_wrapped(text, piece) if text else piece
    return text


def merge_regions_into_lines(regions: list[TextRegion]) -> list[TextRegion]:
    """Gộp các ô cỡ-từ thành một ô/1 dòng — cho overlay & live dịch theo dòng.

    Nhờ vậy mỗi ô overlay phủ trọn một dòng (thay vì từng mẩu chữ rời rạc bị
    dịch & vẽ chồng lộn xộn khi engine trả nhiều box nhỏ như PP-OCRv5).
    """
    lines, _ = _group_into_lines(regions)
    merged: list[TextRegion] = []
    for line in lines:
        text = _line_text(line)
        if not text:
            continue
        boxes = line["regions"]
        left = min(r.bbox[0] for r in boxes)
        top = min(r.bbox[1] for r in boxes)
        right = max(r.bbox[2] for r in boxes)
        bottom = max(r.bbox[3] for r in boxes)
        merged.append(TextRegion(text, (left, top, right, bottom)))
    return merged


def reflow_regions(regions: list[TextRegion]) -> str:
    """Ghép các dòng OCR bị wrap thành đoạn văn để dịch cho liền mạch.

    Gom ô thành dòng, rồi gộp các dòng sát nhau thành đoạn — chỉ giữ ngắt dòng
    khi khoảng trống dọc lớn (đoạn mới). Trong một đoạn, các dòng được nối lại
    (dấu cách cho Latinh, liền cho CJK) — nhờ vậy trình dịch nhận trọn câu thay
    vì từng mẩu bị cắt.
    """
    lines, median_h = _group_into_lines(regions)
    if not lines:
        return ""
    paragraphs: list[str] = []
    current = ""
    prev_bottom: int | None = None
    for line in lines:
        text = _line_text(line)
        if not text:
            continue
        top, bottom = line["top"], line["bottom"]
        if prev_bottom is not None and (top - prev_bottom) > median_h * 0.8:
            if current:
                paragraphs.append(current)
            current = text
        else:
            current = _join_wrapped(current, text) if current else text
        prev_bottom = bottom
    if current:
        paragraphs.append(current)
    return "\n".join(paragraphs)


def ocr_text_reflow(
    image_path: str | Path,
    language: str,
    engine: str = "rapidocr",
    model: str = "ppocrv5_mobile",
    backend: str = "auto",
) -> str:
    """OCR rồi ghép dòng wrap thành đoạn — dùng cho khung dịch (Ctrl+B/vùng)."""
    regions = ocr_layout(image_path, language, engine, model, backend)
    return reflow_regions(regions)


_OCR_ENGINE_LABELS = {
    "windows": "Windows OCR",
    "rapidocr": "OCR ngoại tuyến",
}
_AUTO_OCR_ENGINES = ("windows", "rapidocr")


def _ocr_candidates(engine: str) -> tuple[str, ...]:
    if engine == "auto":
        return _AUTO_OCR_ENGINES
    if engine not in _OCR_ENGINE_LABELS:
        raise RuntimeError(f"Engine OCR không được hỗ trợ: {engine}")
    return (engine,)


def ocr_engine_status(
    engine: str,
    model: str = "ppocrv5_mobile",
    backend: str = "auto",
) -> tuple[bool, str]:
    """Kiểm tra nhẹ, không tải model hay khởi tạo engine."""
    if engine == "auto":
        ready = [
            _OCR_ENGINE_LABELS[name]
            for name in _AUTO_OCR_ENGINES
            if ocr_engine_status(name, model, backend)[0]
        ]
        if ready:
            return True, "Khả dụng: " + " → ".join(ready) + "."
        return False, "Chưa có engine OCR nào khả dụng."
    if engine == "windows":
        if os.name != "nt":
            return False, "Windows OCR chỉ hoạt động trên Windows."
        if importlib.util.find_spec("winsdk") is None:
            return False, "Thiếu winsdk · chạy: pip install winsdk"
        return True, "Offline · dùng gói ngôn ngữ đã cài trong Windows."
    if engine == "rapidocr":
        missing = [
            package
            for package in ("rapidocr", "onnxruntime")
            if importlib.util.find_spec(package) is None
        ]
        if missing:
            return False, "Thiếu " + ", ".join(missing) + " · cài requirements.txt"
        backend_ready, backend_detail = ocr_runtime.backend_status(backend)
        model_detail = (
            "Model đã sẵn sàng."
            if ocr_runtime.model_installed(model)
            else "Model chưa tải."
        )
        return backend_ready, f"{model_detail} {backend_detail}"
    return False, f"Engine OCR không được hỗ trợ: {engine}"


def _ocr_text_with(
    engine: str,
    image_path: str | Path,
    language: str,
    model: str = "ppocrv5_mobile",
    backend: str = "auto",
) -> str:
    if engine == "windows":
        return _ocr_windows(image_path, language)
    text, _regions = _ocr_rapid_data(image_path, model, backend)
    return text


def _ocr_layout_with(
    engine: str,
    image_path: str | Path,
    language: str,
    model: str = "ppocrv5_mobile",
    backend: str = "auto",
) -> tuple[str, list[TextRegion]]:
    if engine == "windows":
        return _ocr_windows_data(image_path, language)
    return _ocr_rapid_data(image_path, model, backend)


# Mã ngôn ngữ UI → thẻ BCP-47 mà Windows OCR dùng.
_WIN_OCR_LANG = {
    "multi": "en",
    "jpn+eng": "ja",
    "jpn": "ja",
    "eng": "en",
    "vie": "vi",
    "kor": "ko",
    "chi_sim": "zh-Hans",
    "chi_tra": "zh-Hant",
    "latin": "en",
    "eslav": "ru",
}


def _ocr_rapid_data(
    image_path: str | Path,
    model: str = "ppocrv5_mobile",
    backend: str = "auto",
) -> tuple[str, list[TextRegion]]:
    """OCR bằng model PaddleOCR tối ưu ONNX, trả text và hộp từng dòng."""
    result = ocr_runtime.get_rapid_engine(model, backend)(
        str(image_path), use_cls=False
    )
    txts = tuple(getattr(result, "txts", None) or ())
    boxes = getattr(result, "boxes", None)
    regions: list[TextRegion] = []
    if boxes is not None:
        for text, box in zip(txts, boxes):
            clean = str(text).strip()
            if not clean:
                continue
            points = list(box)
            if not points:
                continue
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            left, top = int(round(min(xs))), int(round(min(ys)))
            right, bottom = int(round(max(xs))), int(round(max(ys)))
            if right > left and bottom > top:
                regions.append(TextRegion(clean, (left, top, right, bottom)))
    text = "\n".join(str(value).strip() for value in txts if str(value).strip())
    return text, regions


def _ocr_windows(image_path: str | Path, language: str) -> str:
    """OCR bằng Windows.Media.Ocr (offline, có sẵn trên Win10/11)."""
    text, _regions = _ocr_windows_data(image_path, language)
    return text


def _create_windows_ocr_engine(ocr_engine_type, language_type, lang_tag: str):
    """Chọn engine theo ngôn ngữ, rồi fallback về profile Windows."""
    engine = None
    try:
        language = language_type(lang_tag)
        if ocr_engine_type.is_language_supported(language):
            engine = ocr_engine_type.try_create_from_language(language)
    except Exception:  # noqa: BLE001
        engine = None
    return engine or ocr_engine_type.try_create_from_user_profile_languages()


def _windows_line_region(line) -> TextRegion | None:
    """Chuyển một Windows OCR line sang model trung lập của ứng dụng."""
    line_text = (line.text or "").strip()
    if not line_text:
        return None
    boxes: list[tuple[int, int, int, int]] = []
    for word in getattr(line, "words", []):
        rect = getattr(word, "bounding_rect", None)
        if rect is None:
            continue
        left = int(round(rect.x))
        top = int(round(rect.y))
        boxes.append(
            (
                left,
                top,
                left + max(1, int(round(rect.width))),
                top + max(1, int(round(rect.height))),
            )
        )
    if not boxes:
        return None
    return TextRegion(
        line_text,
        (
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        ),
    )


def _ocr_windows_data(
    image_path: str | Path, language: str
) -> tuple[str, list[TextRegion]]:
    """Trả cả nội dung và bounding box từng dòng từ Windows.Media.Ocr."""
    try:
        import asyncio

        from winsdk.windows.globalization import Language
        from winsdk.windows.graphics.imaging import BitmapDecoder
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.storage import FileAccessMode, StorageFile
    except ImportError as exc:
        raise RuntimeError(
            "Windows OCR cần gói 'winsdk'. Cài bằng: pip install winsdk"
        ) from exc

    lang_tag = _WIN_OCR_LANG.get(language, "en")

    async def _run() -> tuple[str, list[TextRegion]]:
        path = str(Path(image_path).resolve())
        file = await StorageFile.get_file_from_path_async(path)
        stream = await file.open_async(FileAccessMode.READ)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()

        engine = _create_windows_ocr_engine(OcrEngine, Language, lang_tag)
        if engine is None:
            raise RuntimeError(
                f"Windows chưa cài gói OCR cho ngôn ngữ '{lang_tag}'. Mở Settings → "
                "Time & Language → Language & region, thêm ngôn ngữ kèm gói OCR."
            )

        result = await engine.recognize_async(bitmap)
        lines = [ln.text for ln in result.lines if ln.text]
        regions = [
            region
            for line in result.lines
            if (region := _windows_line_region(line)) is not None
        ]
        text = "\n".join(lines) if lines else (result.text or "")
        return text.strip(), regions

    return asyncio.run(_run())


def full_screen_bbox() -> tuple[int, int, int, int]:
    """bbox=(left, top, right, bottom) của toàn bộ desktop ảo."""
    import ctypes

    user32 = ctypes.windll.user32
    x = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    y = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    w = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    h = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    return (x, y, x + max(1, w), y + max(1, h))


def capture(bbox: tuple[int, int, int, int], path: str | Path) -> None:
    """Chụp vùng bbox=(left, top, right, bottom) và lưu PNG."""
    from PIL import ImageGrab

    image = ImageGrab.grab(bbox=bbox, all_screens=True)
    longest = max(image.size)
    if longest > 1800:
        scale = 1800 / longest
        image = image.resize(
            (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
        )
    image.save(path)


def _dominant_ring_color(image) -> tuple[int, int, int] | None:
    """Tìm màu thật của bucket phổ biến trên các vòng sát biên ảnh."""
    from collections import Counter

    width, height = image.size
    pixels = image.load()
    counts: Counter = Counter()
    sums: dict[tuple[int, int, int], list[int]] = {}

    def add_sample(color: tuple[int, int, int]) -> None:
        bucket = tuple(channel // 12 * 12 for channel in color)
        counts[bucket] += 1
        total = sums.setdefault(bucket, [0, 0, 0, 0])
        for index, channel in enumerate(color):
            total[index] += channel
        total[3] += 1

    max_inset = max(0, (min(width, height) - 1) // 2)
    inset = min(4, max_inset)
    ring_count = min(3, max(1, max_inset - inset + 1))
    for offset in range(inset, inset + ring_count):
        left, right = offset, width - 1 - offset
        top, bottom = offset, height - 1 - offset
        if left > right or top > bottom:
            break
        for x in range(left, right + 1):
            add_sample(pixels[x, top])
            if bottom != top:
                add_sample(pixels[x, bottom])
        for y in range(top + 1, bottom):
            add_sample(pixels[left, y])
            if right != left:
                add_sample(pixels[right, y])
    if not counts:
        return None
    winning_sum = sums[counts.most_common(1)[0][0]]
    return tuple(round(winning_sum[index] / winning_sum[3]) for index in range(3))


def _contrasting_text_color(
    background: tuple[int, int, int],
) -> tuple[int, int, int]:
    luminance = 0.299 * background[0] + 0.587 * background[1] + 0.114 * background[2]
    return (24, 24, 24) if luminance > 140 else (240, 240, 240)


def analyze_colors(
    image_path: str | Path,
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Đoán (màu_nền, màu_chữ) của vùng ảnh để vẽ overlay dịch cho liền mạch.

    - Màu nền: lấy từ vài vòng pixel lùi vào trong thay vì hàng pixel ngoài cùng.
      Nhờ vậy khung chọn/viền cửa sổ còn sót không thể trở thành màu nền.
      Các sắc gần giống được gom nhóm, nhưng màu trả về là trung bình thật của
      nhóm áp đảo chứ không phải màu đã lượng tử hoá.
    - Màu chữ: màu trong lòng vùng phổ biến nhất mà khác nền rõ; nếu không có thì
      dùng màu tương phản theo độ sáng nền.
    """
    from PIL import Image

    with Image.open(image_path) as source:
        image = source.convert("RGB")
    width, height = image.size
    scale = max(width, height) / 160
    if scale > 1:
        image = image.resize((max(1, int(width / scale)), max(1, int(height / scale))))
    background = _dominant_ring_color(image)
    if background is None:
        return (32, 34, 40), (235, 236, 240)
    return background, _contrasting_text_color(background)


def _surrounding_samples(pixels, size, bbox) -> list[tuple[int, int, int]]:
    """Lấy pixel nằm quanh bbox, không lấy phần chữ ở bên trong."""
    width, height = size
    left, top, right, bottom = bbox
    left = max(0, min(left, width - 1))
    top = max(0, min(top, height - 1))
    right = max(left + 1, min(right, width))
    bottom = max(top + 1, min(bottom, height))
    pad = max(2, min(8, (bottom - top) // 3))
    outer_left, outer_top = max(0, left - pad), max(0, top - pad)
    outer_right, outer_bottom = min(width, right + pad), min(height, bottom + pad)
    coordinates = (
        ((x, y) for y in range(outer_top, top) for x in range(outer_left, outer_right)),
        (
            (x, y)
            for y in range(bottom, outer_bottom)
            for x in range(outer_left, outer_right)
        ),
        ((x, y) for y in range(top, bottom) for x in range(outer_left, left)),
        ((x, y) for y in range(top, bottom) for x in range(right, outer_right)),
    )
    return [pixels[x, y] for group in coordinates for x, y in group]


def _dominant_sample_color(samples: list[tuple[int, int, int]]):
    """Giữ màu exact khi nền phẳng; trung bình bucket khi nền có nhiễu."""
    from collections import Counter

    exact: Counter = Counter(samples)
    top_color, top_count = exact.most_common(1)[0]
    if top_count >= len(samples) * 0.45:
        return top_color
    buckets: Counter = Counter(
        (color[0] // 8, color[1] // 8, color[2] // 8) for color in samples
    )
    winning = buckets.most_common(1)[0][0]
    matched = [
        color
        for color in samples
        if (color[0] // 8, color[1] // 8, color[2] // 8) == winning
    ]
    return tuple(
        round(sum(color[index] for color in matched) / len(matched))
        for index in range(3)
    )


def analyze_layout_colors(
    image_path: str | Path, regions: list[TextRegion]
) -> tuple[tuple[int, int], list[tuple[tuple[int, int, int], tuple[int, int, int]]]]:
    """Lấy màu nền cục bộ quanh từng dòng, đồng thời trả kích thước ảnh nguồn."""
    from PIL import Image

    with Image.open(image_path) as source:
        image = source.convert("RGB")
    width, height = image.size
    pixels = image.load()
    fallback = analyze_colors(image_path)
    colors = []

    for region in regions:
        samples = _surrounding_samples(pixels, image.size, region.bbox)
        if not samples:
            colors.append(fallback)
            continue
        background = _dominant_sample_color(samples)
        colors.append((background, _contrasting_text_color(background)))

    return (width, height), colors


@dataclass(frozen=True)
class RegionVisual:
    """Dữ liệu vẽ 1 dòng dịch: nền thật đã xoá chữ (inpaint) + màu chữ.

    - rect: hình chữ nhật (toạ độ ảnh nguồn) mà miếng nền phủ lên.
    - patch_rgb / patch_size: ảnh nền đã dựng lại (RGB888) hoặc None nếu không
      dựng được → khi đó dùng `bg` tô đặc như fallback.
    """

    rect: tuple[int, int, int, int]
    patch_rgb: bytes | None
    patch_size: tuple[int, int] | None
    bg: tuple[int, int, int]
    fg: tuple[int, int, int]


def _cv2_available() -> bool:
    return (
        importlib.util.find_spec("cv2") is not None
        and importlib.util.find_spec("numpy") is not None
    )


def reconstruct_layout(
    image_path: str | Path, regions: list[TextRegion]
) -> tuple[tuple[int, int], list[RegionVisual]]:
    """Dựng lại nền cho từng dòng theo kiểu Google Dịch ảnh.

    Với mỗi dòng: cắt vùng có đệm quanh chữ, tạo mặt nạ nét chữ, rồi dùng
    `cv2.inpaint` để xoá chữ gốc và vá lại nền từ pixel xung quanh — giữ nguyên
    gradient/hoạ tiết. Màu chữ dịch lấy theo màu chữ gốc nếu đủ tương phản.
    Nếu thiếu cv2/numpy hoặc lỗi thì trả về miếng tô đặc như trước.
    """
    if not _cv2_available():
        # Fallback: lấy màu nền bằng đường cũ, tô đặc, không inpaint.
        (width, height), colors = analyze_layout_colors(image_path, regions)
        visuals = []
        for region, (bg, fg) in zip(regions, colors):
            rect = _padded_rect(region.bbox, width, height)
            visuals.append(RegionVisual(rect, None, None, bg, fg))
        return (width, height), visuals

    import cv2  # type: ignore
    import numpy as np  # type: ignore
    from PIL import Image

    # Chỉ mở & nạp ảnh MỘT lần; tính màu nền bằng numpy (không vòng lặp Python).
    with Image.open(image_path) as source:
        arr = np.asarray(source.convert("RGB"), dtype=np.uint8)
    height, width = arr.shape[:2]

    visuals: list[RegionVisual] = []
    for region in regions:
        outer_left, outer_top, outer_right, outer_bottom = _padded_rect(
            region.bbox, width, height
        )
        rect = (outer_left, outer_top, outer_right, outer_bottom)
        patch = arr[outer_top:outer_bottom, outer_left:outer_right]
        ph, pw = patch.shape[:2]

        inner_left = max(0, min(region.bbox[0], width) - outer_left)
        inner_top = max(0, min(region.bbox[1], height) - outer_top)
        inner_right = min(pw, max(0, min(region.bbox[2], width) - outer_left))
        inner_bottom = min(ph, max(0, min(region.bbox[3], height) - outer_top))

        bg = _bg_from_patch(np, patch, inner_left, inner_top, inner_right, inner_bottom)
        lum_bg0 = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
        fg = (24, 24, 24) if lum_bg0 > 140 else (240, 240, 240)

        if ph < 2 or pw < 2:
            visuals.append(RegionVisual(rect, None, None, bg, fg))
            continue

        # Mặt nạ nét chữ: chỉ trong vùng chữ gốc, pixel lệch xa màu nền.
        bg_arr = np.array(bg, dtype=np.int16)
        diff = np.abs(patch.astype(np.int16) - bg_arr).max(axis=2)
        mask = np.zeros((ph, pw), dtype=np.uint8)
        if inner_right > inner_left and inner_bottom > inner_top:
            region_diff = diff[inner_top:inner_bottom, inner_left:inner_right]
            mask[inner_top:inner_bottom, inner_left:inner_right] = np.where(
                region_diff > 55, 255, 0
            ).astype(np.uint8)

        stroke = mask > 0
        stroke_count = int(stroke.sum())
        # Mặt nạ bất thường (bg sai → xoá gần hết) → không inpaint, tô đặc.
        if stroke_count < 4 or stroke_count > 0.7 * ph * pw:
            visuals.append(RegionVisual(rect, None, None, bg, fg))
            continue

        # Màu chữ dịch = màu chữ gốc (trung bình pixel nét chữ) để trông giống
        # bản gốc; chỉ thay bằng đen/trắng khi màu gốc quá sát nền (mất tương phản).
        text_mean = patch[stroke].mean(axis=0)
        text_color = tuple(int(round(v)) for v in text_mean)
        lum_bg = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
        lum_text = 0.299 * text_color[0] + 0.587 * text_color[1] + 0.114 * text_color[2]
        chosen_fg = text_color if abs(lum_text - lum_bg) >= 70 else fg

        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
        clean = cv2.inpaint(np.ascontiguousarray(patch), mask, 3, cv2.INPAINT_TELEA)
        rgb = np.ascontiguousarray(clean, dtype=np.uint8).tobytes()
        visuals.append(RegionVisual(rect, rgb, (pw, ph), bg, chosen_fg))

    return (width, height), visuals


def _bg_from_patch(np, patch, inner_left, inner_top, inner_right, inner_bottom):
    """Ước lượng màu nền từ dải viền quanh chữ, vector hoá bằng numpy.

    Cùng logic với analyze_layout_colors (màu pixel chính xác chiếm ưu thế →
    dùng đúng màu; nếu không → trung bình cụm bucket mịn) nhưng nhanh hơn nhiều.
    """
    ph, pw = patch.shape[:2]
    bands = []
    if inner_top > 0:
        bands.append(patch[:inner_top, :])
    if inner_bottom < ph:
        bands.append(patch[inner_bottom:, :])
    if inner_right > inner_left and inner_bottom > inner_top:
        if inner_left > 0:
            bands.append(patch[inner_top:inner_bottom, :inner_left])
        if inner_right < pw:
            bands.append(patch[inner_top:inner_bottom, inner_right:])
    if not bands:
        bands = [patch]
    border = np.concatenate([b.reshape(-1, 3) for b in bands], axis=0)
    if border.size == 0:
        return (32, 34, 40)
    r = border[:, 0].astype(np.uint32)
    g = border[:, 1].astype(np.uint32)
    b = border[:, 2].astype(np.uint32)
    # Gói RGB thành 1 số → np.unique 1D nhanh hơn nhiều so với unique theo hàng.
    codes = (r << 16) | (g << 8) | b
    vals, counts = np.unique(codes, return_counts=True)
    top = int(counts.argmax())
    if counts[top] >= 0.45 * len(border):
        code = int(vals[top])
        return ((code >> 16) & 255, (code >> 8) & 255, code & 255)
    qcodes = ((r >> 3) << 20) | ((g >> 3) << 10) | (b >> 3)
    qvals, qcounts = np.unique(qcodes, return_counts=True)
    win = qvals[qcounts.argmax()]
    sel = qcodes == win
    mean = border[sel].mean(axis=0)
    return tuple(int(round(v)) for v in mean)


def _padded_rect(
    bbox: tuple[int, int, int, int], width: int, height: int
) -> tuple[int, int, int, int]:
    """Hộp chữ đã kẹp trong ảnh và nới thêm đệm nhỏ để phủ trọn nét chữ."""
    left, top, right, bottom = bbox
    left = max(0, min(left, width - 1))
    top = max(0, min(top, height - 1))
    right = max(left + 1, min(right, width))
    bottom = max(top + 1, min(bottom, height))
    # Đệm ngang rộng (phủ trọn nét chữ), nhưng đệm DỌC nhỏ để patch của dòng này
    # không lấn sang dòng kề khi các dòng sát nhau (tránh overlay đè lên nhau).
    pad_x = max(2, min(8, (bottom - top) // 4))
    pad_y = max(1, min(3, (bottom - top) // 10))
    return (
        max(0, left - pad_x),
        max(0, top - pad_y),
        min(width, right + pad_x),
        min(height, bottom + pad_y),
    )


def translate_regions(
    regions: list[TextRegion],
    target: str,
    service: str = "google",
    *,
    llm_endpoint: str = "",
    llm_api_key: str = "",
    llm_model: str = "",
) -> list[str]:
    """Dịch các dòng và cố giữ ánh xạ 1:1 với bounding box OCR."""
    if not regions:
        return []
    if len(regions) == 1:
        return [
            translate(
                regions[0].text,
                target,
                service,
                llm_endpoint=llm_endpoint,
                llm_api_key=llm_api_key,
                llm_model=llm_model,
            )
        ]

    joined = "\n".join(region.text for region in regions)
    combined = translate(
        joined,
        target,
        service,
        llm_endpoint=llm_endpoint,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
    )
    lines = [line.strip() for line in combined.splitlines() if line.strip()]
    if len(lines) == len(regions):
        return lines

    # Một số dịch vụ gộp dòng; khi đó ưu tiên đúng layout hơn một request duy nhất.
    return [
        translate(
            region.text,
            target,
            service,
            llm_endpoint=llm_endpoint,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
        )
        for region in regions
    ]


def translate(
    text: str,
    target: str,
    service: str = "google",
    *,
    llm_endpoint: str = "",
    llm_api_key: str = "",
    llm_model: str = "",
) -> str:
    """Dịch text sang `target` bằng Google, Bing hoặc LLM AI.

    Bing dùng endpoint keyless của Edge; nếu lỗi sẽ tự fallback về Google
    để không làm gián đoạn người dùng.
    """
    text = text.strip()
    if not text:
        return ""
    if service == "llm":
        return _translate_llm(
            text,
            target,
            llm_endpoint,
            llm_api_key,
            llm_model,
        )
    if service == "bing":
        try:
            result = _translate_bing(text, target)
            if result:
                return result
        except Exception:  # noqa: BLE001 — hỏng thì lặng lẽ dùng Google
            pass
    return _translate_google(text, target)


_TARGET_LANGUAGE_NAMES = {
    "vi": "Vietnamese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "zh-CN": "Simplified Chinese",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
}


def _translate_llm(
    text: str,
    target: str,
    endpoint: str,
    api_key: str,
    model: str,
) -> str:
    """Gọi endpoint chat/completions tương thích OpenAI, không log API key."""
    endpoint = endpoint.strip().rstrip("/")
    if not endpoint.startswith(("http://", "https://")):
        raise RuntimeError("Endpoint LLM không hợp lệ.")
    if not api_key.strip():
        raise RuntimeError("LLM AI chưa có API key. Mở Cài đặt → Dịch để nhập key.")
    if not model.strip():
        raise RuntimeError("Chưa chọn model LLM.")

    language = _TARGET_LANGUAGE_NAMES.get(target, target)
    payload = {
        "model": model,
        "temperature": 0.1,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    f"Translate the user's text into {language}. "
                    "Return only the translation, preserve line breaks and meaning. "
                    "Do not add explanations, labels, quotes, or markdown."
                ),
            },
            {"role": "user", "content": text},
        ],
    }
    request = urllib.request.Request(
        endpoint + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": "Bearer " + api_key.strip(),
            "Content-Type": "application/json",
            "User-Agent": _UA,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"LLM AI trả về HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Không kết nối được endpoint LLM: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("Endpoint LLM phản hồi quá thời gian cho phép.") from exc
    except UnicodeError as exc:
        raise RuntimeError("Endpoint LLM trả về dữ liệu không hợp lệ.") from exc

    content = _llm_content_from_body(raw)
    if not content.strip():
        raise RuntimeError("LLM AI không trả về bản dịch.")
    return content.strip()


def _content_from_message(content: object) -> str:
    """Chuẩn hoá 'content' của message: str, hoặc list mảnh {type, text}."""
    if isinstance(content, list):
        return "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") in (None, "text")
        )
    return content if isinstance(content, str) else ""


def _content_from_completion(payload: object) -> str:
    """Lấy nội dung từ một object chat.completion (không streaming)."""
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not (isinstance(choices, list) and choices and isinstance(choices[0], dict)):
        return ""
    message = choices[0].get("message")
    return _content_from_message(message.get("content")) if isinstance(message, dict) else ""


def _llm_content_from_body(raw: str) -> str:
    """Rút bản dịch từ body chat/completions — chấp nhận cả JSON lẫn SSE.

    Một số endpoint (vd LiteLLM) trả text/event-stream dù không yêu cầu stream:
    object JSON đầy đủ rồi bám thêm 'data: [DONE]', hoặc nhiều mẩu 'data: {delta}'.
    json.loads thẳng cả body sẽ báo "Extra data", nên phải bóc tách riêng.
    """
    raw = raw.strip()
    if not raw:
        return ""
    # Đọc object JSON đầu tiên; raw_decode bỏ qua phần 'data: [DONE]' bám theo sau.
    try:
        payload, _end = json.JSONDecoder().raw_decode(raw)
        content = _content_from_completion(payload)
        if content:
            return content
    except json.JSONDecodeError:
        pass
    # SSE streaming thật sự: gộp nội dung từ các dòng 'data: {...}'.
    deltas: list[str] = []
    completion = ""
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            payload = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not (isinstance(choices, list) and choices and isinstance(choices[0], dict)):
            continue
        delta = choices[0].get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("content"), str):
            deltas.append(delta["content"])
        completion = _content_from_completion(payload) or completion
    return "".join(deltas) or completion


def _translate_google(text: str, target: str) -> str:
    params = urllib.parse.urlencode(
        {"client": "gtx", "sl": "auto", "tl": target, "dt": "t", "q": text}
    )
    url = "https://translate.googleapis.com/translate_a/single?" + params
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Không kết nối được dịch vụ dịch: {exc}") from exc
    chunks = data[0] if data and isinstance(data[0], list) else []
    translated = "".join(chunk[0] for chunk in chunks if chunk and chunk[0])
    if not translated:
        raise RuntimeError("Dịch vụ không trả về bản dịch.")
    return translated


# Mã ngôn ngữ đích của app → mã Microsoft Translator dùng.
_BING_TARGET = {"zh-CN": "zh-Hans"}
# Token JWT của Edge translate (hết hạn ~10 phút) — cache để đỡ gọi lại.
_bing_token: dict = {"value": None, "ts": 0.0}


def _bing_get_token(force: bool = False) -> str:
    now = time.time()
    if force or not _bing_token["value"] or now - _bing_token["ts"] > 480:
        req = urllib.request.Request(
            "https://edge.microsoft.com/translate/auth",
            headers={"User-Agent": _UA},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            _bing_token["value"] = resp.read().decode("utf-8").strip()
            _bing_token["ts"] = now
    return _bing_token["value"]


def _translate_bing(text: str, target: str) -> str:
    to = _BING_TARGET.get(target, target)
    url = (
        "https://api.cognitive.microsofttranslator.com/translate"
        "?api-version=3.0&to=" + urllib.parse.quote(to)
    )
    body = json.dumps([{"Text": text}]).encode("utf-8")
    last_exc: Exception | None = None
    for attempt in range(2):  # token hết hạn → làm mới rồi thử lại 1 lần
        token = _bing_get_token(force=attempt > 0)
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "User-Agent": _UA,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            translations = data[0].get("translations") if data else None
            if not translations:
                raise RuntimeError("Bing không trả về bản dịch.")
            return translations[0].get("text", "")
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in (401, 403) and attempt == 0:
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("Bing không trả về bản dịch.")


def copy_selected_text() -> str:
    """Mô phỏng Ctrl+C rồi đọc clipboard để lấy văn bản đang bôi đen."""
    import keyboard
    import pyperclip

    time.sleep(0.12)
    previous = ""
    try:
        previous = pyperclip.paste()
    except Exception:  # noqa: BLE001
        pass
    try:
        pyperclip.copy("")
    except Exception:  # noqa: BLE001
        pass
    keyboard.send("ctrl+c")
    time.sleep(0.22)
    text = ""
    try:
        text = (pyperclip.paste() or "").strip()
    except Exception:  # noqa: BLE001
        pass
    if not text:
        try:
            pyperclip.copy(previous)
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError("Chưa thấy văn bản được chọn.")
    return text
