"""Cấu hình ứng dụng, lưu JSON tại %USERPROFILE%\\.screen-translator-2k."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from constants import DEFAULT_LLM_ENDPOINT, HUD_FONT_FAMILIES, LLM_MODELS

DEFAULT_HOTKEYS = {
    "selected_text": "ctrl+b",
    "region_to_text": "ctrl+alt+a",
    "region_to_overlay": "ctrl+alt+d",
    "region_to_live": "ctrl+alt+l",
    "region_to_live_frame": "ctrl+alt+f",
    "fullscreen": "ctrl+alt+x",
    "quit": "ctrl+alt+q",
}

_OCR_ENGINES = {"auto", "windows", "rapidocr"}
_OCR_MODELS = {
    "ppocrv5_mobile",
    "ppocrv6_tiny",
    "ppocrv6_small",
    "ppocrv6_medium",
    "ppocrv5_server",
    "eslav_ppocrv5_mobile",
    "korean_ppocrv5_mobile",
    "latin_ppocrv5_mobile",
}
_OCR_BACKENDS = {"auto", "cpu", "directml", "cuda", "openvino"}
_TRANSLATORS = {"google", "bing", "llm"}
_LLM_MODEL_IDS = {model_id for _label, model_id in LLM_MODELS}
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_HEX_ARGB_COLOR = re.compile(r"^#[0-9a-fA-F]{8}$")


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
    return "Yu Gothic"


class AppConfig:
    """Validated in-memory config với persistence nguyên tử."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        source = data if isinstance(data, dict) else {}
        self.target_language = _string(source.get("target_language"), "vi")
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
        translator = source.get("translator")
        self.translator = (
            translator
            if isinstance(translator, str) and translator in _TRANSLATORS
            else "google"
        )
        self.llm_endpoint = _http_endpoint(source.get("llm_endpoint"))
        self.llm_api_key = _optional_string(source.get("llm_api_key"), 512)
        llm_model = source.get("llm_model")
        self.llm_model = (
            llm_model
            if isinstance(llm_model, str) and llm_model in _LLM_MODEL_IDS
            else LLM_MODELS[0][1]
        )

        self.auto_update = _boolean(source.get("auto_update"), True)
        self.skipped_update_version = _optional_string(
            source.get("skipped_update_version"), 32
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
        self.hud_font_family = _font_family(source.get("hud_font_family"))
        self.hud_font_size = _bounded_int(source.get("hud_font_size"), 16, 8, 96)
        self.hud_text_color = _color(source.get("hud_text_color"), "#000000")
        self.hud_border_width = _bounded_float(
            source.get("hud_border_width"), 1.0, 0.0, 8.0
        )
        self.hud_border_color = _color(source.get("hud_border_color"), "#ffffff")
        self.hud_background_color = _argb_color(
            source.get("hud_background_color"), "#00000000"
        )
        self.hud_pinned = _boolean(source.get("hud_pinned"), True)

        configured_hotkeys = source.get("hotkeys")
        configured_hotkeys = (
            configured_hotkeys if isinstance(configured_hotkeys, dict) else {}
        )
        self.hotkeys = {
            action: (
                configured_hotkeys[action].strip().lower()
                if isinstance(configured_hotkeys.get(action), str)
                else default
            )
            for action, default in DEFAULT_HOTKEYS.items()
        }

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
            "ocr_language": self.ocr_language,
            "ocr_engine": self.ocr_engine,
            "ocr_model": self.ocr_model,
            "ocr_backend": self.ocr_backend,
            "ocr_acceleration": self.ocr_acceleration,
            "translator": self.translator,
            "llm_endpoint": self.llm_endpoint,
            "llm_api_key": self.llm_api_key,
            "llm_model": self.llm_model,
            "auto_update": self.auto_update,
            "skipped_update_version": self.skipped_update_version,
            "live_interval_ms": self.live_interval_ms,
            "hud_geometry": self.hud_geometry,
            "hud_font_family": self.hud_font_family,
            "hud_font_size": self.hud_font_size,
            "hud_text_color": self.hud_text_color,
            "hud_border_width": self.hud_border_width,
            "hud_border_color": self.hud_border_color,
            "hud_background_color": self.hud_background_color,
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
