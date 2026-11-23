import type { AppConfig } from "../types";

export const LANGUAGES: [string, string][] = [
  ["Tiếng Việt", "vi"],
  ["English", "en"],
  ["日本語", "ja"],
  ["한국어", "ko"],
  ["中文", "zh-CN"],
  ["Français", "fr"],
  ["Español", "es"],
  ["Deutsch", "de"],
];

export const SOURCE_LANGUAGES: [string, string][] = [
  ["Tự nhận diện", "auto"],
  ...LANGUAGES,
];

export const SONIOX_LANGUAGES: [string, string][] = [
  ["Tiếng Việt", "vi"],
  ["English", "en"],
  ["日本語", "ja"],
  ["한국어", "ko"],
  ["中文", "zh"],
  ["Français", "fr"],
  ["Español", "es"],
  ["Deutsch", "de"],
  ["Русский", "ru"],
  ["Português", "pt"],
  ["Italiano", "it"],
  ["ไทย", "th"],
  ["Bahasa Indonesia", "id"],
  ["العربية", "ar"],
  ["हिन्दी", "hi"],
  ["Türkçe", "tr"],
  ["Nederlands", "nl"],
  ["Polski", "pl"],
  ["Українська", "uk"],
];

export const OCR_LANGUAGES: [string, string][] = [
  ["Đa ngôn ngữ", "multi"],
  ["Nhật + Anh", "jpn+eng"],
  ["Nhật", "jpn"],
  ["Anh", "eng"],
  ["Việt", "vie"],
  ["Hàn", "kor"],
  ["Trung giản thể", "chi_sim"],
  ["Trung phồn thể", "chi_tra"],
  ["Bảng chữ cái Latinh", "latin"],
  ["Đông Slav", "eslav"],
];

export const OCR_ENGINES: { label: string; value: "auto" | "windows" | "rapidocr"; desc: string }[] = [
  {
    label: "Tự động",
    value: "auto",
    desc: "Ưu tiên Windows OCR, sau đó dùng model ONNX ngoại tuyến.",
  },
  {
    label: "Windows OCR",
    value: "windows",
    desc: "Nhanh, ngoại tuyến, tốn ít tài nguyên nhất trên Windows 10/11.",
  },
  {
    label: "OCR ngoại tuyến (ONNX)",
    value: "rapidocr",
    desc: "Chạy PP-OCRv5/v6 trực tiếp bằng ONNX Runtime (CPU / DirectML).",
  },
];

export const OCR_BACKENDS: [string, string][] = [
  ["Tự động", "auto"],
  ["CPU · ONNX Runtime", "cpu"],
  ["GPU · DirectML", "directml"],
];

export const LIVE_TRIGGER_MODES: { label: string; value: "hybrid" | "auto" | "input" }[] = [
  { label: "Tự động + Chuột/Phím (Nhanh nhất)", value: "hybrid" },
  { label: "Tự động theo màn hình (Phim / Phụ đề)", value: "auto" },
  { label: "Chỉ khi bấm Chuột / Enter / Space (Game)", value: "input" },
];

export const BUILTIN_AI_PROVIDERS = [
  {
    id: "llm",
    name: "Translator2k AI",
    endpoint: "http://103.38.236.38:20128/v1",
    register: "http://103.38.236.38:20128/",
    models: [
      { label: "Deepseek V4 Flash", id: "deepseek-v4-flash" },
      { label: "Deepseek V4 Pro", id: "deepseek-v4-pro" },
    ],
  },
  {
    id: "openai",
    name: "OpenAI",
    endpoint: "https://api.openai.com/v1",
    register: "https://platform.openai.com/api-keys",
    models: [
      { label: "GPT-6 Luna", id: "gpt-6-luna" },
      { label: "GPT-6.1 Terra", id: "gpt-6.1-terra" },
    ],
  },
  {
    id: "gemini",
    name: "Google Gemini",
    endpoint: "https://generativelanguage.googleapis.com/v1beta/openai",
    register: "https://aistudio.google.com/apikey",
    models: [
      { label: "Gemini 3.8 Flash", id: "gemini-3.8-flash" },
      { label: "Gemini 3.5 Flash-Lite", id: "gemini-3.5-flash-lite" },
      { label: "Gemini 3.1 Pro (preview)", id: "gemini-3.1-pro-preview" },
    ],
  },
] as const;

export const SOURCE_KIND_LABELS: Record<string, string> = {
  text: "Văn bản",
  region: "Vùng màn hình",
  overlay: "Overlay tại chỗ",
  image: "Ảnh clipboard",
  clipboard: "Tự dịch Copy",
  replace: "Dịch & thay thế",
};

export const HOTKEY_ACTIONS: { label: string; action: string; hint: string }[] = [
  { label: "Dịch & thay thế tại chỗ", action: "selected_text_replace", hint: "Sao chép đoạn đang bôi đen, dịch rồi dán đè" },
  { label: "Mở dịch văn bản nhập", action: "quick_translate", hint: "Đưa cửa sổ dịch nhanh lên trước" },
  { label: "Dịch ảnh clipboard (thay chữ)", action: "clipboard_image_replace", hint: "Xoá chữ gốc và vẽ bản dịch đè lên ảnh" },
  { label: "Ảnh clipboard → Khung dịch", action: "clipboard_image_to_text", hint: "OCR ảnh clipboard ra văn bản dịch" },
  { label: "Vùng màn hình → Khung dịch", action: "region_to_text", hint: "Chọn vùng và đưa bản dịch vào khung" },
  { label: "Vùng màn hình → Overlay tại chỗ", action: "region_to_overlay", hint: "Chọn vùng và vẽ đè bản dịch tại chỗ" },
  { label: "Live: thêm vùng overlay", action: "region_to_live", hint: "Thêm vùng dịch liên tục kiểu overlay" },
  { label: "Live: thêm vùng vào khung", action: "region_to_live_frame", hint: "Thêm vùng dịch liên tục kiểu khung nổi" },
  { label: "Live: bắt đầu / dừng", action: "live_toggle", hint: "Bật hoặc dừng toàn bộ vùng Live" },
  { label: "Live: quét lại ngay", action: "live_rescan", hint: "Ép OCR và dịch lại ngay các vùng Live" },
  { label: "Bật/tắt tự dịch khi copy", action: "toggle_auto_clipboard", hint: "Tự dịch mỗi khi nhấn Ctrl+C" },
  { label: "Thoát ứng dụng", action: "quit", hint: "Đóng hoàn toàn Translator2k" },
];

export const HUD_FONT_OPTIONS: [string, string][] = [
  ["Segoe UI", "Unicode"],
  ["Yu Gothic", "Nhật · Unicode"],
  ["Arial", "Latin · Unicode"],
  ["Calibri", "Latin · Unicode"],
  ["Tahoma", "Unicode"],
  ["Times New Roman", "Unicode"],
  ["Meiryo", "Nhật"],
  ["Microsoft YaHei UI", "Trung giản thể"],
  ["Microsoft JhengHei UI", "Trung phồn thể"],
  ["Malgun Gothic", "Hàn"],
  ["Noto Sans", "Đa ngôn ngữ"],
];

export const HUD_STYLE_PRESETS: {
  id: string;
  name: string;
  desc: string;
  values: Partial<AppConfig>;
}[] = [
  {
    id: "subtitle",
    name: "Phụ đề phim",
    desc: "Không nền hộp, chữ trắng viền đen dày + bóng mềm.",
    values: {
      hud_font_family: "Segoe UI",
      hud_font_size: 22,
      hud_text_color: "#ffffff",
      hud_border_width: 2.6,
      hud_border_color: "#000000",
      hud_background_color: "#00000000",
      hud_background_enabled: false,
      hud_shadow_radius: 6.0,
      hud_shadow_color: "#b3000000",
    },
  },
  {
    id: "readable",
    name: "Dễ đọc nhất",
    desc: "Chữ trắng, viền đen, nền tối 70%.",
    values: {
      hud_font_family: "Segoe UI",
      hud_font_size: 20,
      hud_text_color: "#ffffff",
      hud_border_width: 2.0,
      hud_border_color: "#000000",
      hud_background_color: "#b3101216",
      hud_background_enabled: true,
      hud_shadow_radius: 0.0,
      hud_shadow_color: "#00000000",
    },
  },
  {
    id: "yellow",
    name: "Vàng phụ đề",
    desc: "Vàng ấm dễ phân biệt với chữ trắng của game.",
    values: {
      hud_font_family: "Segoe UI",
      hud_font_size: 22,
      hud_text_color: "#ffe066",
      hud_border_width: 2.4,
      hud_border_color: "#000000",
      hud_background_color: "#00000000",
      hud_background_enabled: false,
      hud_shadow_radius: 6.0,
      hud_shadow_color: "#99000000",
    },
  },
  {
    id: "light",
    name: "Nền sáng",
    desc: "Chữ đen trên nền trắng giống tài liệu.",
    values: {
      hud_font_family: "Segoe UI",
      hud_font_size: 19,
      hud_text_color: "#18181b",
      hud_border_width: 0.0,
      hud_border_color: "#000000",
      hud_background_color: "#f2fafafa",
      hud_background_enabled: true,
      hud_shadow_radius: 0.0,
      hud_shadow_color: "#00000000",
    },
  },
];

export function formatHotkey(combo: string): string {
  if (!combo.trim()) return "Chưa đặt";
  return combo
    .split("+")
    .map((part) => {
      const p = part.trim().toLowerCase();
      if (p === "ctrl") return "Ctrl";
      if (p === "alt") return "Alt";
      if (p === "shift") return "Shift";
      if (p === "win") return "Win";
      return p.length === 1 ? p.toUpperCase() : p[0].toUpperCase() + p.slice(1);
    })
    .join(" + ");
}

export const DEFAULT_HUD_BG_COLOR = "#b3101216";

export function argbHexAlpha(argb: string): number {
  if (!/^#[0-9a-fA-F]{8}$/.test(argb)) return 0;
  return parseInt(argb.slice(1, 3), 16);
}

export function argbHexToRgbaCss(argb: string): string {
  if (!/^#[0-9a-fA-F]{8}$/.test(argb)) return "transparent";
  const a = parseInt(argb.slice(1, 3), 16) / 255;
  const r = parseInt(argb.slice(3, 5), 16);
  const g = parseInt(argb.slice(5, 7), 16);
  const b = parseInt(argb.slice(7, 9), 16);
  return `rgba(${r}, ${g}, ${b}, ${a.toFixed(2)})`;
}

export function argbToColorAndAlpha(argb: string): { hex: string; opacity: number } {
  const effective = argbHexAlpha(argb) > 0 ? argb : DEFAULT_HUD_BG_COLOR;
  const alpha = parseInt(effective.slice(1, 3), 16);
  return {
    hex: `#${effective.slice(3, 9).toLowerCase()}`,
    opacity: Math.round((alpha / 255) * 100),
  };
}

export function colorAndAlphaToArgb(hex: string, opacityPercent: number): string {
  const clean = /^#[0-9a-fA-F]{6}$/.test(hex) ? hex.slice(1) : "101216";
  const clamped = Math.max(0, Math.min(100, Math.round(opacityPercent)));
  const a = Math.round((clamped / 100) * 255)
    .toString(16)
    .padStart(2, "0");
  return `#${a}${clean.toLowerCase()}`;
}

export function resolveHudBackgroundCss(config: AppConfig | null): string {
  if (!config || !config.hud_background_enabled || config.hud_frame_transparent) {
    return "transparent";
  }
  const color =
    argbHexAlpha(config.hud_background_color) > 0
      ? config.hud_background_color
      : DEFAULT_HUD_BG_COLOR;
  return argbHexToRgbaCss(color);
}

export function buildHudBackgroundPatch(
  config: AppConfig,
  enabled: boolean
): Partial<AppConfig> {
  if (!enabled) {
    return { hud_background_enabled: false };
  }
  return {
    hud_background_enabled: true,
    hud_frame_transparent: false,
    ...(argbHexAlpha(config.hud_background_color) === 0
      ? { hud_background_color: DEFAULT_HUD_BG_COLOR }
      : {}),
  };
}

export function getServiceOptions(config: AppConfig): { label: string; value: string }[] {
  const opts: { label: string; value: string }[] = [
    { label: "Google Dịch", value: "google" },
    { label: "Bing Translator", value: "bing" },
  ];
  for (const p of BUILTIN_AI_PROVIDERS) {
    const key = p.id === "llm" ? config.llm_api_key : config.ai_keys[p.id] || "";
    if (!key.trim()) continue;
    const disabled = new Set(config.ai_disabled_models[p.id] || []);
    const extras = config.ai_models[p.id] || [];
    const ids = [...p.models.map((m) => m.id), ...extras.filter((e) => !p.models.some((m) => m.id === e))].filter(
      (id) => !disabled.has(id)
    );
    for (const modelId of ids) {
      const found = p.models.find((m) => m.id === modelId);
      opts.push({
        label: `${p.name} · ${found ? found.label : modelId}`,
        value: `${p.id}::${modelId}`,
      });
    }
  }
  for (const cp of config.custom_providers) {
    if (!cp.api_key.trim()) continue;
    for (const modelId of cp.models) {
      opts.push({
        label: `${cp.name} · ${modelId}`,
        value: `custom:${cp.id}::${modelId}`,
      });
    }
  }
  return opts;
}

export function currentServiceValue(config: AppConfig): string {
  if (config.translator === "google" || config.translator === "bing") {
    return config.translator;
  }
  return `${config.translator}::${config.llm_model}`;
}

export function parseServiceValue(val: string): { translator: string; llm_model?: string } {
  const idx = val.indexOf("::");
  if (idx === -1) return { translator: val };
  return {
    translator: val.slice(0, idx),
    llm_model: val.slice(idx + 2),
  };
}

export function currentTextServiceValue(config: AppConfig): string {
  if (!config.text_translator?.trim()) return "";
  if (config.text_translator === "google" || config.text_translator === "bing") {
    return config.text_translator;
  }
  const model = config.text_llm_model?.trim() || config.llm_model;
  return `${config.text_translator}::${model}`;
}

export function parseTextServiceValue(val: string): {
  text_translator: string;
  text_llm_model: string;
} {
  if (!val.trim()) {
    return { text_translator: "", text_llm_model: "" };
  }
  const idx = val.indexOf("::");
  if (idx === -1) {
    return { text_translator: val, text_llm_model: "" };
  }
  return {
    text_translator: val.slice(0, idx),
    text_llm_model: val.slice(idx + 2),
  };
}

export function eventToCombo(e: KeyboardEvent): string | null {
  const key = e.key.toLowerCase();
  if (["control", "alt", "shift", "meta"].includes(key)) return null;
  const parts: string[] = [];
  if (e.ctrlKey) parts.push("ctrl");
  if (e.altKey) parts.push("alt");
  if (e.shiftKey) parts.push("shift");
  if (e.metaKey) parts.push("win");

  const mapped =
    key === " "
      ? "space"
      : key === "arrowup"
        ? "up"
        : key === "arrowdown"
          ? "down"
          : key === "arrowleft"
            ? "left"
            : key === "arrowright"
              ? "right"
              : key;
  parts.push(mapped);
  return parts.join("+");
}
