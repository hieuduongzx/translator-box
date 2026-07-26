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
    ("Dịch & thay thế tại chỗ", "selected_text_replace"),
    ("Dịch ảnh clipboard", "clipboard_image_replace"),
    ("Ảnh clipboard → Khung dịch", "clipboard_image_to_text"),
    ("Vùng → Khung dịch", "region_to_text"),
    ("Vùng → Live vào khung", "region_to_live_frame"),
    ("Vùng → Overlay", "region_to_overlay"),
    ("Vùng → Live overlay", "region_to_live"),
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
DEFAULT_LLM_ENDPOINT = "http://103.38.236.38:20128/v1"
LLM_REGISTRATION_URL = "http://103.38.236.38:20128/"

# Provider AI tích hợp sẵn — endpoint CỐ ĐỊNH (OpenAI-compatible), user chỉ nhập
# API key và chọn model. "id" cũng là mã translator lưu trong config.
BUILTIN_AI_PROVIDERS = [
    {
        "id": "llm",
        "name": "Translator Box",
        "endpoint": DEFAULT_LLM_ENDPOINT,
        "models": [
            ("Deepseek V4 Flash", "deepseek-v4-flash"),
            ("Deepseek V4 Pro", "deepseek-v4-pro"),
        ],
        "register": LLM_REGISTRATION_URL,
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "endpoint": "https://api.openai.com/v1",
        "models": [
            ("GPT-4o mini", "gpt-4o-mini"),
            ("GPT-4o", "gpt-4o"),
            ("GPT-4.1 mini", "gpt-4.1-mini"),
        ],
        "register": "https://platform.openai.com/api-keys",
    },
    {
        "id": "gemini",
        "name": "Google Gemini",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai",
        "models": [
            ("Gemini 2.5 Flash", "gemini-2.5-flash"),
            ("Gemini 2.5 Pro", "gemini-2.5-pro"),
            ("Gemini 2.0 Flash", "gemini-2.0-flash"),
        ],
        "register": "https://aistudio.google.com/apikey",
    },
]

BUILTIN_AI_IDS = tuple(provider["id"] for provider in BUILTIN_AI_PROVIDERS)
BUILTIN_AI_BY_ID = {provider["id"]: provider for provider in BUILTIN_AI_PROVIDERS}
BUILTIN_AI_ENDPOINTS = {p["id"]: p["endpoint"] for p in BUILTIN_AI_PROVIDERS}
BUILTIN_AI_MODEL_IDS = {
    p["id"]: [model_id for _label, model_id in p["models"]]
    for p in BUILTIN_AI_PROVIDERS
}
# Model của provider "Translator Box" — giữ tên cũ cho tương thích.
LLM_MODELS = BUILTIN_AI_BY_ID["llm"]["models"]


_CUSTOM_BAR_PREFIX = "custom::"


def bar_service_key(translator: str, llm_model: str) -> str:
    """Key combo bar: 'google'/'bing', '<ai_id>::<model>', 'custom::<pid>::<model>'."""
    if translator in ("google", "bing"):
        return translator
    if translator.startswith("custom:"):
        pid = translator.split(":", 1)[1]
        return f"{_CUSTOM_BAR_PREFIX}{pid}::{llm_model}"
    return f"{translator}::{llm_model}"  # provider AI tích hợp (llm/openai/gemini)


def parse_bar_service_key(key: str) -> tuple[str, str | None]:
    """Giải mã key combo bar → (translator, model | None)."""
    if "::" not in key:
        return key, None  # google/bing
    head, _, rest = key.partition("::")
    if head == "custom":
        pid, _, model = rest.partition("::")
        return f"custom:{pid}", model or None
    return head, rest or None  # provider AI tích hợp


def bar_translator_entries(
    custom_providers: list | None = None,
    *,
    builtin_models: dict[str, list[str]] | None = None,
    enabled_providers: set[str] | None = None,
) -> list[tuple[str, str]]:
    """Các lựa chọn dịch: Google/Bing + model của provider đã cấu hình key."""
    entries: list[tuple[str, str]] = [("Google", "google"), ("Bing", "bing")]
    for provider in BUILTIN_AI_PROVIDERS:
        provider_id = provider["id"]
        if enabled_providers is not None and provider_id not in enabled_providers:
            continue
        labels = {model_id: label for label, model_id in provider["models"]}
        models = (
            builtin_models.get(provider_id, [])
            if builtin_models is not None
            else list(labels)
        )
        for model_id in models:
            label = labels.get(model_id, model_id)
            entries.append((f"{provider['name']} · {label}", f"{provider_id}::{model_id}"))
    for provider in custom_providers or []:
        code = f"custom:{provider['id']}"
        if enabled_providers is not None and code not in enabled_providers:
            continue
        for model_id in provider.get("models", []):
            label = f"{provider['name']} · {model_id}"
            entries.append((label, f"{_CUSTOM_BAR_PREFIX}{provider['id']}::{model_id}"))
    return entries

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
# Nhóm 2 — xử lý ảnh đang có trong clipboard.
BAR_GROUP_CLIPBOARD = [
    (
        "image",
        "Dịch ảnh clipboard",
        "clipboard_image_replace",
        "OCR, xoá chữ gốc rồi hiện ảnh dịch trong khung trong suốt",
    ),
    (
        "image-text",
        "Ảnh clipboard → khung",
        "clipboard_image_to_text",
        "OCR ảnh clipboard rồi đưa bản dịch dạng text vào khung",
    ),
]

# Nhóm 3 — dịch đưa vào KHUNG (vùng trong suốt của HUD).
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
    (
        "text",
        "Dịch văn bản chọn",
        "selected_text",
        "Copy văn bản đang bôi đen rồi dịch",
    ),
    (
        "replace",
        "Dịch & thay thế",
        "selected_text_replace",
        "Bôi đen văn bản rồi thay bằng bản dịch (dán đè tại chỗ)",
    ),
]
BAR_ACTIONS = BAR_GROUP_OVERLAY + BAR_GROUP_CLIPBOARD + BAR_GROUP_FRAME

SERVER_NAME = "ScreenTranslator2K.Python.Instance"
