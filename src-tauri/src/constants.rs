use serde::Serialize;

pub const DEFAULT_LLM_ENDPOINT: &str = "http://103.38.236.38:20128/v1";
pub const LLM_REGISTRATION_URL: &str = "http://103.38.236.38:20128/";

#[derive(Debug, Clone, Serialize)]
pub struct BuiltinAiProvider {
    pub id: &'static str,
    pub name: &'static str,
    pub endpoint: &'static str,
    pub models: &'static [(&'static str, &'static str)],
    pub register: &'static str,
}

pub const BUILTIN_AI_PROVIDERS: &[BuiltinAiProvider] = &[
    BuiltinAiProvider {
        id: "llm",
        name: "Translator Box",
        endpoint: DEFAULT_LLM_ENDPOINT,
        models: &[
            ("Deepseek V4 Flash", "deepseek-v4-flash"),
            ("Deepseek V4 Pro", "deepseek-v4-pro"),
        ],
        register: LLM_REGISTRATION_URL,
    },
    BuiltinAiProvider {
        id: "openai",
        name: "OpenAI",
        endpoint: "https://api.openai.com/v1",
        models: &[
            ("GPT-6 Luna", "gpt-6-luna"),
            ("GPT-6.1 Terra", "gpt-6.1-terra"),
        ],
        register: "https://platform.openai.com/api-keys",
    },
    BuiltinAiProvider {
        id: "gemini",
        name: "Google Gemini",
        endpoint: "https://generativelanguage.googleapis.com/v1beta/openai",
        models: &[
            ("Gemini 3.8 Flash", "gemini-3.8-flash"),
            ("Gemini 3.5 Flash-Lite", "gemini-3.5-flash-lite"),
            ("Gemini 3.1 Pro (preview)", "gemini-3.1-pro-preview"),
        ],
        register: "https://aistudio.google.com/apikey",
    },
];

pub fn builtin_provider_by_id(id: &str) -> Option<&'static BuiltinAiProvider> {
    BUILTIN_AI_PROVIDERS.iter().find(|p| p.id == id)
}

pub fn retired_model_replacement(model: &str) -> Option<&'static str> {
    match model {
        "gpt-4o" | "gpt-4o-mini" | "gpt-4.1-mini" => Some("gpt-6-luna"),
        "gpt-4.1" => Some("gpt-6.1-terra"),
        "gemini-2.0-flash" | "gemini-2.5-flash" => Some("gemini-3.8-flash"),
        "gemini-2.0-flash-lite" => Some("gemini-3.5-flash-lite"),
        "gemini-2.5-pro" => Some("gemini-3.1-pro-preview"),
        _ => None,
    }
}

pub fn target_language_name(code: &str) -> &str {
    match code {
        "vi" => "Vietnamese",
        "en" => "English",
        "ja" => "Japanese",
        "ko" => "Korean",
        "zh-CN" | "zh" => "Simplified Chinese",
        "zh-TW" => "Traditional Chinese",
        "fr" => "French",
        "es" => "Spanish",
        "de" => "German",
        "ru" => "Russian",
        "pt" => "Portuguese",
        "it" => "Italian",
        "th" => "Thai",
        "id" => "Indonesian",
        other => other,
    }
}

pub const HUD_FONT_FAMILIES: &[&str] = &[
    "Yu Gothic",
    "Segoe UI",
    "Arial",
    "Calibri",
    "Tahoma",
    "Times New Roman",
    "Meiryo",
    "Microsoft YaHei UI",
    "Microsoft JhengHei UI",
    "Malgun Gothic",
    "Leelawadee UI",
    "Noto Sans",
    "Arial Unicode MS",
];

pub const DEFAULT_HOTKEYS: &[(&str, &str)] = &[
    ("selected_text_replace", "alt+b"),
    ("quick_translate", "ctrl+alt+e"),
    ("clipboard_image_replace", "ctrl+alt+v"),
    ("clipboard_image_to_text", "ctrl+alt+t"),
    ("region_to_text", "ctrl+alt+a"),
    ("region_to_overlay", "ctrl+alt+d"),
    ("region_to_live", "ctrl+alt+l"),
    ("region_to_live_frame", "ctrl+alt+f"),
    ("live_toggle", "ctrl+alt+s"),
    ("live_rescan", "ctrl+alt+r"),
    ("toggle_auto_clipboard", "ctrl+alt+c"),
    ("quit", "ctrl+alt+q"),
];

pub const LIVE_REGION_LIMIT: usize = 12;
pub const GLOSSARY_LIMIT: usize = 200;

pub const SONIOX_LANGUAGE_CODES: &[&str] = &[
    "vi", "en", "ja", "ko", "zh", "fr", "es", "de", "ru", "pt", "it", "th", "id", "af", "sq",
    "ar", "az", "eu", "be", "bn", "bs", "bg", "ca", "hr", "cs", "da", "nl", "et", "fi", "gl",
    "el", "gu", "he", "hi", "hu", "kn", "kk", "lv", "lt", "mk", "ms", "ml", "mr", "no", "fa",
    "pl", "pa", "ro", "sr", "sk", "sl", "sw", "sv", "tl", "ta", "te", "tr", "uk", "ur", "cy",
];
