"""Các lựa chọn và metadata giao diện dùng chung."""

from __future__ import annotations

LANGUAGES = [
    ("Tiếng Việt", "vi"),
    ("English", "en"),
    ("日本語", "ja"),
    ("한국어", "ko"),
    ("中文", "zh-CN"),
    ("Français", "fr"),
    ("Español", "es"),
    ("Deutsch", "de"),
]
OCR_LANGUAGES = [
    ("Đa ngôn ngữ", "multi"),
    ("Nhật + Anh", "jpn+eng"),
    ("Nhật", "jpn"),
    ("Anh", "eng"),
    ("Việt", "vie"),
    ("Hàn", "kor"),
    ("Trung giản thể", "chi_sim"),
    ("Trung phồn thể", "chi_tra"),
    ("Bảng chữ cái Latinh", "latin"),
    ("Đông Slav", "eslav"),
]
HOTKEY_ACTIONS = [
    ("Dịch văn bản chọn", "selected_text"),
    ("Vùng → Khung dịch", "region_to_text"),
    ("Vùng → Live vào khung", "region_to_live_frame"),
    ("Vùng → Overlay", "region_to_overlay"),
    ("Vùng → Live overlay", "region_to_live"),
    ("Toàn màn hình", "fullscreen"),
    ("Thoát", "quit"),
]
OCR_ENGINES = [
    ("OCR ngoại tuyến", "rapidocr"),
    ("Windows OCR", "windows"),
    ("Tự động", "auto"),
]
OCR_ENGINE_DESCRIPTIONS = {
    "auto": "Ưu tiên Windows OCR, sau đó dùng model ngoại tuyến đã chọn.",
    "windows": "Nhanh, offline, tốn ít tài nguyên nhất trên Windows.",
    "rapidocr": "OCR tích hợp chạy hoàn toàn ngoại tuyến bằng RapidOCR.",
}
TRANSLATORS = [
    ("Google", "google"),
    ("Bing", "bing"),
    ("LLM AI", "llm"),
]
LLM_MODELS = [
    ("Mistral Small", "mistral/mistral-small-latest"),
    ("GPT-OSS 120B", "groq/openai/gpt-oss-120b"),
]

# Tiền tố key cho combo dịch vụ trên thanh bar khi item là một model LLM.
_LLM_BAR_PREFIX = "llm::"


def bar_service_key(translator: str, llm_model: str) -> str:
    """Key combo trên bar: mã dịch vụ, hoặc 'llm::<model_id>' cho từng model LLM."""
    return f"{_LLM_BAR_PREFIX}{llm_model}" if translator == "llm" else translator


def parse_bar_service_key(key: str) -> tuple[str, str | None]:
    """Giải mã key combo bar → (translator, llm_model | None)."""
    if key.startswith(_LLM_BAR_PREFIX):
        return "llm", key[len(_LLM_BAR_PREFIX) :]
    return key, None


def bar_translator_entries() -> list[tuple[str, str]]:
    """(nhãn, key) cho combo dịch vụ trên bar — mỗi model LLM hiện thành mục riêng."""
    entries = [(label, code) for label, code in TRANSLATORS if code != "llm"]
    entries += [
        (label, bar_service_key("llm", model_id)) for label, model_id in LLM_MODELS
    ]
    return entries


DEFAULT_LLM_ENDPOINT = "http://103.38.236.38:20128/v1"
LLM_REGISTRATION_URL = "http://103.38.236.38:20128/"

# Danh mục font HUD có giới hạn. Qt vẫn tự ghép font fallback cho glyph còn thiếu.
HUD_FONT_OPTIONS = (
    ("Yu Gothic", "Nhật · Unicode"),
    ("Segoe UI", "Unicode"),
    ("Arial", "Latin · Unicode"),
    ("Calibri", "Latin · Unicode"),
    ("Tahoma", "Unicode"),
    ("Times New Roman", "Unicode"),
    ("Meiryo", "Nhật"),
    ("Microsoft YaHei UI", "Trung giản thể"),
    ("Microsoft JhengHei UI", "Trung phồn thể"),
    ("Malgun Gothic", "Hàn"),
    ("Leelawadee UI", "Đông Nam Á"),
    ("Noto Sans", "Đa ngôn ngữ"),
    ("Arial Unicode MS", "Đa ngôn ngữ"),
)
HUD_FONT_FAMILIES = frozenset(family for family, _coverage in HUD_FONT_OPTIONS)

# Nút bar HUD chia 2 nhóm: (kind icon, nhãn, action, tooltip gợi ý).
# Nhóm 1 — dịch OVERLAY (đè tại chỗ trên màn hình).
BAR_GROUP_OVERLAY = [
    ("overlay", "Overlay", "region_to_overlay", "Dịch đè ngay tại chỗ trên màn hình"),
    (
        "live",
        "Live overlay",
        "region_to_live",
        "Dịch overlay liên tục một vùng (bấm lại để dừng)",
    ),
]
# Nhóm 2 — dịch đưa vào KHUNG (vùng trong suốt của HUD).
BAR_GROUP_FRAME = [
    (
        "scan",
        "Chọn vùng → khung",
        "region_to_text",
        "Chọn vùng, OCR rồi dịch vào khung",
    ),
    (
        "liveframe",
        "Live → khung",
        "region_to_live_frame",
        "OCR liên tục một vùng, đổ bản dịch vào khung (bấm lại để dừng)",
    ),
    ("fullscreen", "Toàn màn hình", "fullscreen", "OCR cả màn hình rồi dịch vào khung"),
    (
        "text",
        "Dịch văn bản chọn",
        "selected_text",
        "Copy văn bản đang bôi đen rồi dịch",
    ),
]
BAR_ACTIONS = BAR_GROUP_OVERLAY + BAR_GROUP_FRAME

SERVER_NAME = "ScreenTranslator2K.Python.Instance"
