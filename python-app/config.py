"""Cấu hình ứng dụng, lưu JSON tại %USERPROFILE%\\.screen-translator-2k."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from constants import (
    BUILTIN_AI_ENDPOINTS,
    BUILTIN_AI_IDS,
    BUILTIN_AI_MODEL_IDS,
    DEFAULT_LLM_ENDPOINT,
    HUD_FONT_FAMILIES,
    LLM_MODELS,
    SONIOX_LANGUAGE_CODES,
)

# Bộ kiểu chữ mặc định cho khung dịch: chữ trắng, viền đen mảnh, không glow.
# Viền giữ nét trên nền sáng; thân chữ trắng đọc được trên nền tối. Phẳng tuyệt
# đối — không bóng đổ, không màu accent thừa. Đây cũng là giá trị nút "Đặt lại
# mặc định" ở tab Khung dịch dùng.
HUD_STYLE_DEFAULTS: dict[str, Any] = {
    "hud_font_family": "Segoe UI",
    "hud_font_size": 18,
    "hud_text_color": "#fafafa",
    "hud_border_width": 0.7,
    "hud_border_color": "#09090b",
    # Đen, alpha 50/255 — đủ để tách chữ khỏi desktop lộn xộn phía sau mà vẫn
    # thấy được nội dung gốc; bật mặc định, tắt được bằng checkbox riêng.
    "hud_background_color": "#32000000",
    "hud_background_enabled": True,
    "hud_shadow_radius": 0.0,
    "hud_shadow_color": "#00000000",
}

# Chỉ dùng để nhận ra chính xác preset mặc định của bản trước. Kiểu do người dùng
# tự chỉnh không bị ghi đè khi nâng cấp.
_LEGACY_HUD_STYLE_DEFAULTS: dict[str, Any] = {
    "hud_font_family": "Segoe UI",
    "hud_font_size": 18,
    "hud_text_color": "#ffffff",
    "hud_border_width": 0.5,
    "hud_border_color": "#101114",
    "hud_background_color": "#00000000",
    "hud_shadow_radius": 6.0,
    "hud_shadow_color": "#cc000000",
}

DEFAULT_HOTKEYS = {
    "selected_text": "ctrl+b",
    "selected_text_replace": "alt+b",
    "clipboard_image_replace": "ctrl+alt+v",
    "clipboard_image_to_text": "ctrl+alt+t",
    "region_to_text": "ctrl+alt+a",
    "region_to_overlay": "ctrl+alt+d",
    "region_to_live": "ctrl+alt+l",
    "region_to_live_frame": "ctrl+alt+f",
    "quit": "ctrl+alt+q",
}

_OCR_ENGINES = {"auto", "windows", "rapidocr"}
_OCR_MODELS = {
    "ppocrv5_mobile",
    "ppocrv6_tiny",
    "ppocrv6_small",
    "ppocrv6_medium",
}
_OCR_BACKENDS = {"auto", "cpu", "directml", "cuda", "openvino"}
_TRANSLATORS = {"google", "bing", *BUILTIN_AI_IDS}
_LLM_MODEL_IDS = {
    model_id for models in BUILTIN_AI_MODEL_IDS.values() for model_id in models
}
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_HEX_ARGB_COLOR = re.compile(r"^#[0-9a-fA-F]{8}$")
_SONIOX_TRANSLATION_MODES = {"one_way", "two_way"}
_SONIOX_AUDIO_SOURCES = {"microphone", "system"}
_SONIOX_DISPLAY_MODES = {"bilingual", "translation"}
_SONIOX_TEXT_ALIGNMENTS = {"left", "center", "right"}


def config_path() -> Path:
    return Path.home() / ".screen-translator-2k" / "python-config.json"


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    if not math.isfinite(parsed):
        parsed = default
    return round(max(minimum, min(maximum, parsed)), 1)


def _string(value: Any, default: str) -> str:
    return value if isinstance(value, str) and value.strip() else default


def _boolean(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _optional_string(value: Any, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:maximum]


def _http_endpoint(value: Any) -> str:
    endpoint = _optional_string(value, 2048).rstrip("/")
    if endpoint.startswith(("http://", "https://")):
        return endpoint
    return DEFAULT_LLM_ENDPOINT


def _color(value: Any, default: str) -> str:
    return value if isinstance(value, str) and _HEX_COLOR.fullmatch(value) else default


def _argb_color(value: Any, default: str) -> str:
    return (
        value.lower()
        if isinstance(value, str) and _HEX_ARGB_COLOR.fullmatch(value)
        else default
    )


def _font_family(value: Any) -> str:
    if isinstance(value, str):
        requested = value.strip().casefold()
        for family in HUD_FONT_FAMILIES:
            if family.casefold() == requested:
                return family
    return HUD_STYLE_DEFAULTS["hud_font_family"]


def _clean_models(value: Any) -> list[str]:
    """Danh sách model id đã làm sạch, giữ thứ tự, bỏ trùng và rỗng."""
    models: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                cleaned = item.strip()[:128]
                if cleaned not in models:
                    models.append(cleaned)
    return models


def _ai_keys(value: Any) -> dict[str, str]:
    """API key của các provider AI tích hợp khác 'llm' (openai, gemini…)."""
    keys: dict[str, str] = {}
    if isinstance(value, dict):
        for pid, key in value.items():
            if pid in BUILTIN_AI_IDS and pid != "llm" and isinstance(key, str):
                keys[pid] = key.strip()[:512]
    return keys


def _ai_models(value: Any) -> dict[str, list[str]]:
    """Model bổ sung do người dùng thêm cho provider AI tích hợp."""
    models: dict[str, list[str]] = {}
    if isinstance(value, dict):
        for provider_id, entries in value.items():
            if provider_id in BUILTIN_AI_IDS:
                cleaned = _clean_models(entries)
                if cleaned:
                    models[provider_id] = cleaned
    return models


def _custom_providers(value: Any) -> list[dict[str, Any]]:
    """Provider AI tùy chỉnh hợp lệ: {id, name, endpoint http(s), api_key, models[]}."""
    providers: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return providers
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        pid = item.get("id")
        if not isinstance(pid, str) or not pid.strip() or pid in seen:
            continue
        name = _optional_string(item.get("name"), 64)
        endpoint = _optional_string(item.get("endpoint"), 2048).rstrip("/")
        models = _clean_models(item.get("models"))
        if not name or not endpoint.startswith(("http://", "https://")) or not models:
            continue
        seen.add(pid)
        providers.append(
            {
                "id": pid,
                "name": name,
                "endpoint": endpoint,
                "api_key": _optional_string(item.get("api_key"), 512),
                "models": models,
            }
        )
    return providers


class AppConfig:
    """Validated in-memory config với persistence nguyên tử."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        source = data if isinstance(data, dict) else {}
        self.target_language = _string(source.get("target_language"), "vi")
        # Ngôn ngữ đích RIÊNG cho "Dịch & thay thế tại chỗ" (Ctrl+Alt+B) — mặc định
        # tiếng Anh, độc lập với ngôn ngữ đích của các chức năng còn lại.
        self.replace_target_language = _string(
            source.get("replace_target_language"), "en"
        )
        self.soniox_api_key = _optional_string(source.get("soniox_api_key"), 512)
        soniox_source = source.get("soniox_audio_source")
        self.soniox_audio_source = (
            soniox_source
            if isinstance(soniox_source, str) and soniox_source in _SONIOX_AUDIO_SOURCES
            else "system"
        )
        self.soniox_input_device = _optional_string(
            source.get("soniox_input_device"), 1024
        )
        self.soniox_system_device = _optional_string(
            source.get("soniox_system_device"), 1024
        )
        soniox_mode = source.get("soniox_translation_mode")
        self.soniox_translation_mode = (
            soniox_mode
            if isinstance(soniox_mode, str) and soniox_mode in _SONIOX_TRANSLATION_MODES
            else "one_way"
        )
        soniox_target = source.get("soniox_target_language")
        self.soniox_target_language = (
            soniox_target
            if isinstance(soniox_target, str) and soniox_target in SONIOX_LANGUAGE_CODES
            else "vi"
        )
        soniox_language_a = source.get("soniox_language_a")
        self.soniox_language_a = (
            soniox_language_a
            if isinstance(soniox_language_a, str)
            and soniox_language_a in SONIOX_LANGUAGE_CODES
            else "en"
        )
        soniox_language_b = source.get("soniox_language_b")
        self.soniox_language_b = (
            soniox_language_b
            if isinstance(soniox_language_b, str)
            and soniox_language_b in SONIOX_LANGUAGE_CODES
            else "vi"
        )
        if self.soniox_language_a == self.soniox_language_b:
            self.soniox_language_b = "vi" if self.soniox_language_a != "vi" else "en"
        speaker_setting_is_current = source.get("soniox_speaker_setting_version") == 2
        self.soniox_speaker_diarization = (
            _boolean(source.get("soniox_speaker_diarization"), False)
            if speaker_setting_is_current
            else False
        )
        self.soniox_speaker_setting_version = 2
        display_mode = source.get("soniox_display_mode")
        self.soniox_display_mode = (
            display_mode
            if isinstance(display_mode, str) and display_mode in _SONIOX_DISPLAY_MODES
            else "bilingual"
        )
        text_alignment = source.get("soniox_text_alignment")
        self.soniox_text_alignment = (
            text_alignment
            if isinstance(text_alignment, str)
            and text_alignment in _SONIOX_TEXT_ALIGNMENTS
            else "center"
        )
        self.ocr_language = _string(source.get("ocr_language"), "jpn+eng")

        engine = source.get("ocr_engine")
        self.ocr_engine = (
            engine if isinstance(engine, str) and engine in _OCR_ENGINES else "rapidocr"
        )
        model = source.get("ocr_model")
        self.ocr_model = (
            model
            if isinstance(model, str) and model in _OCR_MODELS
            else "ppocrv5_mobile"
        )
        backend = source.get("ocr_backend")
        self.ocr_backend = (
            backend if isinstance(backend, str) and backend in _OCR_BACKENDS else "auto"
        )
        self.ocr_acceleration = _boolean(source.get("ocr_acceleration"), False)
        self.custom_providers = _custom_providers(source.get("custom_providers"))
        custom_ids = {provider["id"] for provider in self.custom_providers}
        translator = source.get("translator")
        self.translator = (
            translator
            if isinstance(translator, str)
            and (
                translator in _TRANSLATORS
                or (
                    translator.startswith("custom:")
                    and translator.split(":", 1)[1] in custom_ids
                )
            )
            else "google"
        )
        self.llm_endpoint = _http_endpoint(source.get("llm_endpoint"))
        self.llm_api_key = _optional_string(source.get("llm_api_key"), 512)
        self.ai_keys = _ai_keys(source.get("ai_keys"))
        self.ai_models = _ai_models(source.get("ai_models"))
        if not self.ai_provider_configured(self.translator):
            self.translator = (
                self.translator if self.translator in ("google", "bing") else "google"
            )
        # Model hợp lệ = model tích hợp ∪ model bổ sung ∪ model provider tùy chỉnh.
        valid_models = (
            _LLM_MODEL_IDS
            | {model for models in self.ai_models.values() for model in models}
            | {
                model
                for provider in self.custom_providers
                for model in provider["models"]
            }
        )
        llm_model = source.get("llm_model")
        self.llm_model = (
            llm_model
            if isinstance(llm_model, str) and llm_model in valid_models
            else LLM_MODELS[0][1]
        )

        self.auto_update = _boolean(source.get("auto_update"), True)
        self.skipped_update_version = _optional_string(
            source.get("skipped_update_version"), 32
        )

        self.live_focus_app_id = _optional_string(
            source.get("live_focus_app_id"), 32768
        ).casefold()
        self.live_focus_app_label = _optional_string(
            source.get("live_focus_app_label"), 256
        )

        self.live_interval_ms = _bounded_int(
            source.get("live_interval_ms"), 900, 300, 5000
        )
        geometry = source.get("hud_geometry")
        geometry = geometry if isinstance(geometry, dict) else {}
        self.hud_geometry = {
            key: geometry.get(key)
            if isinstance(geometry.get(key), (int, float))
            else None
            for key in ("x", "y", "w", "h")
        }
        defaults = HUD_STYLE_DEFAULTS
        uses_legacy_default = all(
            source.get(key) == value
            for key, value in _LEGACY_HUD_STYLE_DEFAULTS.items()
        )
        style_source = defaults if uses_legacy_default else source
        self.hud_font_family = _font_family(
            style_source.get("hud_font_family", defaults["hud_font_family"])
        )
        self.hud_font_size = _bounded_int(
            style_source.get("hud_font_size"), defaults["hud_font_size"], 8, 96
        )
        self.hud_text_color = _color(
            style_source.get("hud_text_color"), defaults["hud_text_color"]
        )
        self.hud_border_width = _bounded_float(
            style_source.get("hud_border_width"),
            defaults["hud_border_width"],
            0.0,
            8.0,
        )
        self.hud_border_color = _color(
            style_source.get("hud_border_color"), defaults["hud_border_color"]
        )
        self.hud_background_color = _argb_color(
            style_source.get("hud_background_color"),
            defaults["hud_background_color"],
        )
        self.hud_background_enabled = _boolean(
            style_source.get("hud_background_enabled"),
            defaults["hud_background_enabled"],
        )
        # Glow dùng lại khoá `shadow` trong file config để không làm mất tuỳ chỉnh
        # đã lưu. Config cũ có kiểu chữ riêng vẫn giữ glow tắt như trước.
        shadow_default = defaults["hud_shadow_radius"]
        if "hud_shadow_radius" not in style_source and "hud_text_color" in style_source:
            shadow_default = 0.0
        self.hud_shadow_radius = _bounded_float(
            style_source.get("hud_shadow_radius"), shadow_default, 0.0, 16.0
        )
        self.hud_shadow_color = _argb_color(
            style_source.get("hud_shadow_color"), defaults["hud_shadow_color"]
        )
        self.hud_pinned = _boolean(source.get("hud_pinned"), True)

        configured_hotkeys = source.get("hotkeys")
        configured_hotkeys = (
            configured_hotkeys if isinstance(configured_hotkeys, dict) else {}
        )
        # Bản trước dùng Ctrl+Alt+V cho chế độ ảnh → text. Khi tách thành hai
        # chức năng, giữ Ctrl+Alt+V cho ảnh đã thay chữ và chuyển text sang phím mới.
        if (
            "clipboard_image_replace" not in configured_hotkeys
            and configured_hotkeys.get("clipboard_image_to_text") == "ctrl+alt+v"
        ):
            configured_hotkeys = dict(configured_hotkeys)
            configured_hotkeys["clipboard_image_to_text"] = DEFAULT_HOTKEYS[
                "clipboard_image_to_text"
            ]
        self.hotkeys = {
            action: (
                configured_hotkeys[action].strip().lower()
                if isinstance(configured_hotkeys.get(action), str)
                else default
            )
            for action, default in DEFAULT_HOTKEYS.items()
        }

    def active_provider(self) -> dict[str, Any] | None:
        """Provider tùy chỉnh đang chọn, hoặc None nếu không phải custom."""
        if self.translator.startswith("custom:"):
            pid = self.translator.split(":", 1)[1]
            for provider in self.custom_providers:
                if provider["id"] == pid:
                    return provider
        return None

    def provider_api_key(self, provider_id: str) -> str:
        """API key của một provider AI tích hợp ('llm' dùng field riêng)."""
        if provider_id == "llm":
            return self.llm_api_key
        return self.ai_keys.get(provider_id, "")

    def set_provider_api_key(self, provider_id: str, key: str) -> None:
        cleaned = key.strip()[:512]
        if provider_id == "llm":
            self.llm_api_key = cleaned
        elif provider_id in BUILTIN_AI_IDS:
            if cleaned:
                self.ai_keys[provider_id] = cleaned
            else:
                self.ai_keys.pop(provider_id, None)

    def provider_models(self, provider_id: str) -> list[str]:
        """Danh sách model hiệu lực của provider, giữ thứ tự và bỏ trùng."""
        if provider_id in BUILTIN_AI_IDS:
            models = list(BUILTIN_AI_MODEL_IDS[provider_id])
            for model in self.ai_models.get(provider_id, []):
                if model not in models:
                    models.append(model)
            return models
        if provider_id.startswith("custom:"):
            custom_id = provider_id.split(":", 1)[1]
            for provider in self.custom_providers:
                if provider["id"] == custom_id:
                    return list(provider["models"])
        return []

    def ai_provider_configured(self, provider_id: str) -> bool:
        """Provider chỉ sẵn sàng chọn model khi đã có API key."""
        if provider_id in BUILTIN_AI_IDS:
            return bool(self.provider_api_key(provider_id))
        if provider_id.startswith("custom:"):
            custom_id = provider_id.split(":", 1)[1]
            return any(
                provider["id"] == custom_id and bool(provider["api_key"])
                for provider in self.custom_providers
            )
        return provider_id in ("google", "bing")

    def configured_ai_provider_ids(self) -> set[str]:
        configured = {
            provider_id
            for provider_id in BUILTIN_AI_IDS
            if self.ai_provider_configured(provider_id)
        }
        configured.update(
            f"custom:{provider['id']}"
            for provider in self.custom_providers
            if provider["api_key"]
        )
        return configured

    def resolve_llm(self) -> tuple[str, str, str, str]:
        """(service, endpoint, api_key, model) cho dịch vụ đang chọn.

        - google/bing: service tương ứng, tham số LLM bỏ trống.
        - Provider AI tích hợp (Translator Box/OpenAI/Gemini): endpoint CỐ ĐỊNH,
          key + model do người dùng nhập/chọn.
        - Provider tùy chỉnh: endpoint/key theo provider, model kẹp về danh sách.
        """
        if self.translator in ("google", "bing"):
            return self.translator, "", "", ""
        if not self.ai_provider_configured(self.translator):
            return "google", "", "", ""
        if self.translator in BUILTIN_AI_IDS:
            models = self.provider_models(self.translator)
            model = (
                self.llm_model
                if self.llm_model in models
                else (models[0] if models else "")
            )
            return (
                "llm",
                BUILTIN_AI_ENDPOINTS[self.translator],
                self.provider_api_key(self.translator),
                model,
            )
        provider = self.active_provider()
        if provider is not None:
            models = provider["models"]
            model = (
                self.llm_model
                if self.llm_model in models
                else (models[0] if models else "")
            )
            return "llm", provider["endpoint"], provider["api_key"], model
        return "google", "", "", ""

    @classmethod
    def load(cls) -> "AppConfig":
        path = config_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return cls()
        return cls(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_language": self.target_language,
            "replace_target_language": self.replace_target_language,
            "soniox_api_key": self.soniox_api_key,
            "soniox_audio_source": self.soniox_audio_source,
            "soniox_input_device": self.soniox_input_device,
            "soniox_system_device": self.soniox_system_device,
            "soniox_translation_mode": self.soniox_translation_mode,
            "soniox_target_language": self.soniox_target_language,
            "soniox_language_a": self.soniox_language_a,
            "soniox_language_b": self.soniox_language_b,
            "soniox_speaker_diarization": self.soniox_speaker_diarization,
            "soniox_speaker_setting_version": self.soniox_speaker_setting_version,
            "soniox_display_mode": self.soniox_display_mode,
            "soniox_text_alignment": self.soniox_text_alignment,
            "ocr_language": self.ocr_language,
            "ocr_engine": self.ocr_engine,
            "ocr_model": self.ocr_model,
            "ocr_backend": self.ocr_backend,
            "ocr_acceleration": self.ocr_acceleration,
            "translator": self.translator,
            "llm_endpoint": self.llm_endpoint,
            "llm_api_key": self.llm_api_key,
            "llm_model": self.llm_model,
            "ai_keys": self.ai_keys,
            "ai_models": self.ai_models,
            "custom_providers": self.custom_providers,
            "auto_update": self.auto_update,
            "skipped_update_version": self.skipped_update_version,
            "live_focus_app_id": self.live_focus_app_id,
            "live_focus_app_label": self.live_focus_app_label,
            "live_interval_ms": self.live_interval_ms,
            "hud_geometry": self.hud_geometry,
            "hud_font_family": self.hud_font_family,
            "hud_font_size": self.hud_font_size,
            "hud_text_color": self.hud_text_color,
            "hud_border_width": self.hud_border_width,
            "hud_border_color": self.hud_border_color,
            "hud_background_color": self.hud_background_color,
            "hud_background_enabled": self.hud_background_enabled,
            "hud_shadow_radius": self.hud_shadow_radius,
            "hud_shadow_color": self.hud_shadow_color,
            "hud_pinned": self.hud_pinned,
            "hotkeys": self.hotkeys,
        }

    def save(self) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)
