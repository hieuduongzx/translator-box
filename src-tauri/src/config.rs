use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::path::PathBuf;
use std::time::Duration;

use once_cell::sync::Lazy;
use parking_lot::Mutex;
use regex::Regex;
use serde::{Deserialize, Serialize};

use crate::constants::{
    builtin_provider_by_id, retired_model_replacement, BUILTIN_AI_PROVIDERS, DEFAULT_HOTKEYS,
    DEFAULT_LLM_ENDPOINT, GLOSSARY_LIMIT, HUD_FONT_FAMILIES, LIVE_REGION_LIMIT,
    SONIOX_LANGUAGE_CODES,
};

static SAVE_LOCK: Lazy<Mutex<()>> = Lazy::new(|| Mutex::new(()));
static HEX_COLOR_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"^#[0-9a-fA-F]{6}$").unwrap());
static HEX_ARGB_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"^#[0-9a-fA-F]{8}$").unwrap());

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct GlossaryEntry {
    pub source: String,
    pub target: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CustomAiProvider {
    pub id: String,
    pub name: String,
    pub endpoint: String,
    #[serde(default)]
    pub api_key: String,
    pub models: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SavedLiveRegion {
    pub bbox: [i32; 4],
    #[serde(default = "default_region_mode")]
    pub mode: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub output: Option<[i32; 4]>,
}

fn default_region_mode() -> String {
    "overlay".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct HudGeometry {
    pub x: Option<i32>,
    pub y: Option<i32>,
    pub w: Option<i32>,
    pub h: Option<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
#[serde(default)]
pub struct MainWindowGeometry {
    pub x: Option<i32>,
    pub y: Option<i32>,
    pub w: Option<u32>,
    pub h: Option<u32>,
    pub maximized: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct AppConfig {
    // UI standard settings
    pub ui_theme: String,
    pub sidebar_collapsed: bool,
    pub main_window_geometry: MainWindowGeometry,

    // Translation settings
    pub target_language: String,
    pub replace_target_language: String,
    pub auto_translate_clipboard: bool,
    pub translator: String,
    pub llm_endpoint: String,
    pub llm_api_key: String,
    pub llm_model: String,
    pub ai_keys: HashMap<String, String>,
    pub ai_models: HashMap<String, Vec<String>>,
    pub ai_disabled_models: HashMap<String, Vec<String>>,
    pub custom_providers: Vec<CustomAiProvider>,
    pub translation_glossary: Vec<GlossaryEntry>,

    // Dedicated Text Translation & Replace settings
    pub text_source_language: String,
    pub text_target_language: String,
    pub text_translator: String,
    pub text_llm_model: String,
    pub text_auto_copy_result: bool,
    pub text_keep_history: bool,
    pub text_persist_history: bool,
    pub text_history_limit: u32,
    pub text_submit_shortcut: String,
    pub auto_clipboard_max_chars: u32,
    pub replace_enabled: bool,
    pub replace_preserve_formatting: bool,
    pub replace_show_undo_original: bool,
    pub replace_restore_clipboard: bool,
    pub replace_paste_delay_ms: u32,

    // Soniox Realtime Audio settings
    pub soniox_api_key: String,
    pub soniox_audio_source: String,
    pub soniox_input_device: String,
    pub soniox_system_device: String,
    pub soniox_translation_mode: String,
    pub soniox_target_language: String,
    pub soniox_language_a: String,
    pub soniox_language_b: String,
    pub soniox_speaker_diarization: bool,
    pub soniox_speaker_setting_version: u32,
    pub soniox_display_mode: String,
    pub soniox_show_history: bool,
    pub soniox_text_alignment: String,
    pub soniox_context_text: String,
    pub soniox_context_terms: String,

    // OCR settings
    pub ocr_language: String,
    pub ocr_engine: String,
    pub ocr_model: String,
    pub ocr_backend: String,
    pub ocr_acceleration: bool,

    // Update settings
    pub auto_update: bool,
    pub skipped_update_version: String,

    // Live translation settings
    pub live_focus_app_id: String,
    pub live_focus_app_label: String,
    pub live_interval_ms: u32,
    pub live_trigger_mode: String,
    pub live_regions: Vec<SavedLiveRegion>,

    // HUD & floating frame appearance
    pub hud_geometry: HudGeometry,
    pub hud_font_family: String,
    pub hud_font_size: u32,
    pub hud_text_color: String,
    pub hud_border_width: f32,
    pub hud_border_color: String,
    pub hud_background_color: String,
    pub hud_background_enabled: bool,
    pub hud_frame_transparent: bool,
    pub hud_shadow_radius: f32,
    pub hud_shadow_color: String,
    pub hud_pinned: bool,
    pub hud_text_align: String,
    pub hud_text_valign: String,

    // Global hotkeys
    pub hotkeys: BTreeMap<String, String>,
}

impl Default for AppConfig {
    fn default() -> Self {
        let mut hotkeys = BTreeMap::new();
        for &(action, combo) in DEFAULT_HOTKEYS {
            hotkeys.insert(action.to_string(), combo.to_string());
        }
        Self {
            ui_theme: "system".to_string(),
            sidebar_collapsed: false,
            main_window_geometry: MainWindowGeometry::default(),

            target_language: "vi".to_string(),
            replace_target_language: "en".to_string(),
            auto_translate_clipboard: false,
            translator: "google".to_string(),
            llm_endpoint: DEFAULT_LLM_ENDPOINT.to_string(),
            llm_api_key: String::new(),
            llm_model: "deepseek-v4-flash".to_string(),
            ai_keys: HashMap::new(),
            ai_models: HashMap::new(),
            ai_disabled_models: HashMap::new(),
            custom_providers: Vec::new(),
            translation_glossary: Vec::new(),

            text_source_language: "auto".to_string(),
            text_target_language: String::new(),
            text_translator: String::new(),
            text_llm_model: String::new(),
            text_auto_copy_result: false,
            text_keep_history: true,
            text_persist_history: true,
            text_history_limit: 30,
            text_submit_shortcut: "ctrl_enter".to_string(),
            auto_clipboard_max_chars: 5000,
            replace_enabled: true,
            replace_preserve_formatting: true,
            replace_show_undo_original: true,
            replace_restore_clipboard: true,
            replace_paste_delay_ms: 60,

            soniox_api_key: String::new(),
            soniox_audio_source: "system".to_string(),
            soniox_input_device: String::new(),
            soniox_system_device: String::new(),
            soniox_translation_mode: "one_way".to_string(),
            soniox_target_language: "vi".to_string(),
            soniox_language_a: "en".to_string(),
            soniox_language_b: "vi".to_string(),
            soniox_speaker_diarization: false,
            soniox_speaker_setting_version: 2,
            soniox_display_mode: "bilingual".to_string(),
            soniox_show_history: true,
            soniox_text_alignment: "center".to_string(),
            soniox_context_text: String::new(),
            soniox_context_terms: String::new(),

            ocr_language: "jpn+eng".to_string(),
            ocr_engine: "auto".to_string(),
            ocr_model: "ppocrv5_mobile".to_string(),
            ocr_backend: "auto".to_string(),
            ocr_acceleration: false,

            auto_update: true,
            skipped_update_version: String::new(),

            live_focus_app_id: String::new(),
            live_focus_app_label: String::new(),
            live_interval_ms: 900,
            live_trigger_mode: "hybrid".to_string(),
            live_regions: Vec::new(),

            hud_geometry: HudGeometry::default(),
            hud_font_family: "Segoe UI".to_string(),
            hud_font_size: 22,
            hud_text_color: "#ffffff".to_string(),
            hud_border_width: 2.6,
            hud_border_color: "#000000".to_string(),
            hud_background_color: "#00000000".to_string(),
            hud_background_enabled: false,
            hud_frame_transparent: false,
            hud_shadow_radius: 6.0,
            hud_shadow_color: "#b3000000".to_string(),
            hud_pinned: true,
            hud_text_align: "center".to_string(),
            hud_text_valign: "center".to_string(),

            hotkeys,
        }
    }
}

pub fn config_dir() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".screen-translator-2k")
}

pub fn config_path() -> PathBuf {
    config_dir().join("config.json")
}

pub fn legacy_python_config_path() -> PathBuf {
    config_dir().join("python-config.json")
}

pub fn history_path() -> PathBuf {
    config_dir().join("history.json")
}

impl AppConfig {
    pub fn load() -> Self {
        let primary = config_path();
        let raw = fs::read_to_string(&primary)
            .or_else(|_| fs::read_to_string(legacy_python_config_path()));
        let mut cfg = match raw {
            Ok(text) => serde_json::from_str::<AppConfig>(&text).unwrap_or_default(),
            Err(_) => Self::default(),
        };
        cfg.sanitize();
        cfg
    }

    pub fn save(&self) -> Result<(), String> {
        let mut clean = self.clone();
        clean.sanitize();
        let payload = serde_json::to_string_pretty(&clean)
            .map_err(|e| format!("Không mã hoá được cấu hình: {e}"))?;
        let _guard = SAVE_LOCK.lock();
        let path = config_path();
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .map_err(|e| format!("Không tạo được thư mục cấu hình: {e}"))?;
        }
        let tmp_path = path.with_extension("json.tmp");
        fs::write(&tmp_path, payload.as_bytes())
            .map_err(|e| format!("Không ghi được file tạm cấu hình: {e}"))?;
        for attempt in 0..3 {
            match fs::rename(&tmp_path, &path) {
                Ok(()) => return Ok(()),
                Err(err) if attempt < 2 => {
                    let _ = fs::remove_file(&path);
                    std::thread::sleep(Duration::from_millis(20 * (attempt + 1) as u64));
                    if fs::rename(&tmp_path, &path).is_ok() {
                        return Ok(());
                    }
                    if attempt == 1 {
                        let _ = fs::remove_file(&tmp_path);
                        return Err(format!("Không lưu được cấu hình: {err}"));
                    }
                }
                Err(err) => {
                    let _ = fs::remove_file(&tmp_path);
                    return Err(format!("Không lưu được cấu hình: {err}"));
                }
            }
        }
        Ok(())
    }

    pub fn sanitize(&mut self) {
        if !matches!(self.ui_theme.as_str(), "system" | "light" | "dark") {
            self.ui_theme = "system".to_string();
        }
        if let Some(w) = self.main_window_geometry.w {
            if !(860..=10000).contains(&w) {
                self.main_window_geometry.w = None;
            }
        }
        if let Some(h) = self.main_window_geometry.h {
            if !(560..=10000).contains(&h) {
                self.main_window_geometry.h = None;
            }
        }
        if self.target_language.trim().is_empty() {
            self.target_language = "vi".to_string();
        }
        if self.replace_target_language.trim().is_empty() {
            self.replace_target_language = "en".to_string();
        }
        if self.text_source_language.trim().is_empty() {
            self.text_source_language = "auto".to_string();
        } else {
            self.text_source_language = self.text_source_language.trim().to_string();
        }
        if self.text_target_language.trim().is_empty() {
            self.text_target_language = self.target_language.clone();
        } else {
            self.text_target_language = self.text_target_language.trim().to_string();
        }
        if let Some(replacement) = retired_model_replacement(&self.text_llm_model) {
            self.text_llm_model = replacement.to_string();
        }
        self.text_translator = self.text_translator.trim().to_string();
        self.text_llm_model = self.text_llm_model.trim().to_string();
        if !self.text_translator.is_empty()
            && self.text_translator != "google"
            && self.text_translator != "bing"
            && !self.ai_provider_configured(&self.text_translator)
        {
            self.text_translator.clear();
            self.text_llm_model.clear();
        }
        self.text_history_limit = self.text_history_limit.clamp(5, 200);
        if !matches!(self.text_submit_shortcut.as_str(), "ctrl_enter" | "enter") {
            self.text_submit_shortcut = "ctrl_enter".to_string();
        }
        self.auto_clipboard_max_chars = self.auto_clipboard_max_chars.clamp(200, 20_000);
        self.replace_paste_delay_ms = self.replace_paste_delay_ms.clamp(20, 500);
        if !matches!(self.soniox_audio_source.as_str(), "microphone" | "system") {
            self.soniox_audio_source = "system".to_string();
        }
        if !matches!(self.soniox_translation_mode.as_str(), "one_way" | "two_way") {
            self.soniox_translation_mode = "one_way".to_string();
        }
        if !SONIOX_LANGUAGE_CODES.contains(&self.soniox_target_language.as_str()) {
            self.soniox_target_language = "vi".to_string();
        }
        if !SONIOX_LANGUAGE_CODES.contains(&self.soniox_language_a.as_str()) {
            self.soniox_language_a = "en".to_string();
        }
        if !SONIOX_LANGUAGE_CODES.contains(&self.soniox_language_b.as_str()) {
            self.soniox_language_b = "vi".to_string();
        }
        if self.soniox_language_a == self.soniox_language_b {
            self.soniox_language_b = if self.soniox_language_a != "vi" {
                "vi".to_string()
            } else {
                "en".to_string()
            };
        }
        if !matches!(self.soniox_display_mode.as_str(), "bilingual" | "translation") {
            self.soniox_display_mode = "bilingual".to_string();
        }
        if !matches!(self.soniox_text_alignment.as_str(), "left" | "center" | "right") {
            self.soniox_text_alignment = "center".to_string();
        }
        self.soniox_context_text = self.soniox_context_text.trim().chars().take(4000).collect();
        self.soniox_context_terms = self.soniox_context_terms.trim().chars().take(2000).collect();

        if !matches!(self.ocr_engine.as_str(), "auto" | "windows" | "rapidocr") {
            self.ocr_engine = "auto".to_string();
        }
        if !matches!(
            self.ocr_model.as_str(),
            "ppocrv5_mobile" | "ppocrv6_tiny" | "ppocrv6_small" | "ppocrv6_medium"
        ) {
            self.ocr_model = "ppocrv5_mobile".to_string();
        }
        if !matches!(
            self.ocr_backend.as_str(),
            "auto" | "cpu" | "directml" | "cuda" | "openvino"
        ) {
            self.ocr_backend = "auto".to_string();
        }
        if !self.llm_endpoint.starts_with("http://") && !self.llm_endpoint.starts_with("https://") {
            self.llm_endpoint = DEFAULT_LLM_ENDPOINT.to_string();
        } else {
            self.llm_endpoint = self.llm_endpoint.trim().trim_end_matches('/').to_string();
        }
        self.llm_api_key = self.llm_api_key.trim().chars().take(512).collect();

        // Sanitize custom providers
        let mut seen_custom = HashSet::new();
        self.custom_providers.retain_mut(|p| {
            p.id = p.id.trim().to_string();
            p.name = p.name.trim().chars().take(64).collect();
            p.endpoint = p.endpoint.trim().trim_end_matches('/').chars().take(2048).collect();
            p.api_key = p.api_key.trim().chars().take(512).collect();
            let mut seen_m = HashSet::new();
            p.models.retain_mut(|m| {
                *m = m.trim().chars().take(128).collect();
                !m.is_empty() && seen_m.insert(m.clone())
            });
            !p.id.is_empty()
                && !p.name.is_empty()
                && (p.endpoint.starts_with("http://") || p.endpoint.starts_with("https://"))
                && !p.models.is_empty()
                && seen_custom.insert(p.id.clone())
        });

        // Retire old AI models
        if let Some(replacement) = retired_model_replacement(&self.llm_model) {
            self.llm_model = replacement.to_string();
        }

        // Validate translator
        let translator_ok = self.translator == "google"
            || self.translator == "bing"
            || self.ai_provider_configured(&self.translator);
        if !translator_ok {
            self.translator = "google".to_string();
        }

        self.live_interval_ms = self.live_interval_ms.clamp(300, 5000);
        if !matches!(self.live_trigger_mode.as_str(), "hybrid" | "auto" | "input") {
            self.live_trigger_mode = "hybrid".to_string();
        }
        self.live_focus_app_id = self.live_focus_app_id.trim().to_lowercase();
        self.live_focus_app_label = self.live_focus_app_label.trim().chars().take(256).collect();

        // Clean glossary
        let mut seen_gloss = HashSet::new();
        self.translation_glossary.retain_mut(|g| {
            g.source = g.source.trim().chars().take(128).collect();
            g.target = g.target.trim().chars().take(128).collect();
            !g.source.is_empty()
                && !g.target.is_empty()
                && seen_gloss.insert(g.source.to_lowercase())
        });
        self.translation_glossary.truncate(GLOSSARY_LIMIT);

        // Clean live regions
        self.live_regions.retain_mut(|r| {
            let [l, t, ri, b] = r.bbox;
            if ri - l < 8 || b - t < 8 {
                return false;
            }
            if r.mode != "overlay" && r.mode != "frame" {
                r.mode = "overlay".to_string();
            }
            if let Some([_, _, w, h]) = r.output {
                if w < 80 || h < 30 {
                    r.output = None;
                }
            }
            true
        });
        self.live_regions.truncate(LIVE_REGION_LIMIT);

        // Clean HUD style
        if let Some(found) = HUD_FONT_FAMILIES
            .iter()
            .find(|f| f.eq_ignore_ascii_case(self.hud_font_family.trim()))
        {
            self.hud_font_family = (*found).to_string();
        } else {
            self.hud_font_family = "Segoe UI".to_string();
        }
        self.hud_font_size = self.hud_font_size.clamp(8, 96);
        if !HEX_COLOR_RE.is_match(&self.hud_text_color) {
            self.hud_text_color = "#ffffff".to_string();
        }
        self.hud_border_width = self.hud_border_width.clamp(0.0, 8.0);
        if !HEX_COLOR_RE.is_match(&self.hud_border_color) {
            self.hud_border_color = "#000000".to_string();
        }
        if !HEX_ARGB_RE.is_match(&self.hud_background_color) {
            self.hud_background_color = "#00000000".to_string();
        }
        self.hud_shadow_radius = self.hud_shadow_radius.clamp(0.0, 16.0);
        if !HEX_ARGB_RE.is_match(&self.hud_shadow_color) {
            self.hud_shadow_color = "#b3000000".to_string();
        }
        if !matches!(self.hud_text_align.as_str(), "left" | "center" | "right") {
            self.hud_text_align = "center".to_string();
        }
        if !matches!(self.hud_text_valign.as_str(), "top" | "center" | "bottom") {
            self.hud_text_valign = "center".to_string();
        }

        // Fill any missing hotkey keys with defaults
        for &(action, default_combo) in DEFAULT_HOTKEYS {
            self.hotkeys
                .entry(action.to_string())
                .and_modify(|v| *v = v.trim().to_lowercase())
                .or_insert_with(|| default_combo.to_string());
        }
    }

    pub fn provider_api_key(&self, provider_id: &str) -> String {
        if provider_id == "llm" {
            self.llm_api_key.clone()
        } else {
            self.ai_keys.get(provider_id).cloned().unwrap_or_default()
        }
    }

    pub fn provider_models(&self, provider_id: &str) -> Vec<String> {
        if let Some(builtin) = builtin_provider_by_id(provider_id) {
            let disabled: HashSet<&str> = self
                .ai_disabled_models
                .get(provider_id)
                .map(|v| v.iter().map(|s| s.as_str()).collect())
                .unwrap_or_default();
            let mut models: Vec<String> = builtin
                .models
                .iter()
                .map(|(_, id)| (*id).to_string())
                .filter(|id| !disabled.contains(id.as_str()))
                .collect();
            if let Some(extra) = self.ai_models.get(provider_id) {
                for m in extra {
                    if !models.contains(m) && !disabled.contains(m.as_str()) {
                        models.push(m.clone());
                    }
                }
            }
            return models;
        }
        if let Some(cid) = provider_id.strip_prefix("custom:") {
            if let Some(p) = self.custom_providers.iter().find(|p| p.id == cid) {
                return p.models.clone();
            }
        }
        Vec::new()
    }

    pub fn ai_provider_configured(&self, provider_id: &str) -> bool {
        if builtin_provider_by_id(provider_id).is_some() {
            return !self.provider_api_key(provider_id).is_empty();
        }
        if let Some(cid) = provider_id.strip_prefix("custom:") {
            return self
                .custom_providers
                .iter()
                .any(|p| p.id == cid && !p.api_key.is_empty());
        }
        provider_id == "google" || provider_id == "bing"
    }

    /// Resolve active translator into `(service, endpoint, api_key, model)`.
    pub fn resolve_llm(&self) -> (String, String, String, String) {
        self.resolve_provider(&self.translator, &self.llm_model)
    }

    /// Resolve dedicated text translator (falls back to global translator when empty).
    pub fn resolve_text_llm(&self) -> (String, String, String, String) {
        if self.text_translator.trim().is_empty() {
            return self.resolve_llm();
        }
        let model = if self.text_llm_model.trim().is_empty() {
            &self.llm_model
        } else {
            &self.text_llm_model
        };
        self.resolve_provider(&self.text_translator, model)
    }

    fn resolve_provider(&self, translator: &str, model_pref: &str) -> (String, String, String, String) {
        if translator == "google" || translator == "bing" {
            return (translator.to_string(), String::new(), String::new(), String::new());
        }
        if !self.ai_provider_configured(translator) {
            return ("google".to_string(), String::new(), String::new(), String::new());
        }
        if let Some(builtin) = builtin_provider_by_id(translator) {
            let models = self.provider_models(translator);
            let model = if models.iter().any(|m| m == model_pref) {
                model_pref.to_string()
            } else {
                models.first().cloned().unwrap_or_default()
            };
            return (
                "llm".to_string(),
                builtin.endpoint.to_string(),
                self.provider_api_key(translator),
                model,
            );
        }
        if let Some(cid) = translator.strip_prefix("custom:") {
            if let Some(p) = self.custom_providers.iter().find(|p| p.id == cid) {
                let model = if p.models.iter().any(|m| m == model_pref) {
                    model_pref.to_string()
                } else {
                    p.models.first().cloned().unwrap_or_default()
                };
                return ("llm".to_string(), p.endpoint.clone(), p.api_key.clone(), model);
            }
        }
        let _ = BUILTIN_AI_PROVIDERS;
        ("google".to_string(), String::new(), String::new(), String::new())
    }

    /// Effective hotkey map for OS registration (disables replace hotkey when replace mode is off).
    pub fn effective_hotkeys(&self) -> BTreeMap<String, String> {
        let mut map = self.hotkeys.clone();
        if !self.replace_enabled {
            map.insert("selected_text_replace".to_string(), String::new());
        }
        map
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_config_is_valid() {
        let mut cfg = AppConfig::default();
        cfg.sanitize();
        assert_eq!(cfg.target_language, "vi");
        assert_eq!(cfg.text_source_language, "auto");
        assert_eq!(cfg.text_target_language, "vi");
        assert_eq!(cfg.replace_target_language, "en");
        assert_eq!(cfg.ui_theme, "system");
        assert!(cfg.replace_enabled);
        assert!(cfg.replace_preserve_formatting);
        assert!(cfg.replace_show_undo_original);
        assert!(cfg.replace_restore_clipboard);
        assert_eq!(cfg.replace_paste_delay_ms, 60);
        assert_eq!(cfg.text_history_limit, 30);
        assert_eq!(cfg.text_submit_shortcut, "ctrl_enter");
        assert_eq!(cfg.auto_clipboard_max_chars, 5000);
        assert_eq!(cfg.hotkeys.get("selected_text_replace").map(String::as_str), Some("alt+b"));
    }

    #[test]
    fn retires_deprecated_models() {
        let mut cfg = AppConfig::default();
        cfg.llm_model = "gpt-4o".to_string();
        cfg.text_llm_model = "gemini-2.5-flash".to_string();
        cfg.sanitize();
        assert_eq!(cfg.llm_model, "gpt-6-luna");
        assert_eq!(cfg.text_llm_model, "gemini-3.8-flash");
    }

    #[test]
    fn text_translator_overrides_and_falls_back() {
        let mut cfg = AppConfig::default();
        cfg.translator = "google".to_string();
        cfg.text_translator = "bing".to_string();
        cfg.sanitize();
        assert_eq!(cfg.resolve_llm().0, "google");
        assert_eq!(cfg.resolve_text_llm().0, "bing");

        cfg.text_translator = String::new();
        assert_eq!(cfg.resolve_text_llm().0, "google");
    }

    #[test]
    fn disabling_replace_clears_effective_hotkey_but_preserves_saved_combo() {
        let mut cfg = AppConfig::default();
        cfg.replace_enabled = false;
        cfg.sanitize();
        assert_eq!(cfg.hotkeys.get("selected_text_replace").map(String::as_str), Some("alt+b"));
        assert_eq!(
            cfg.effective_hotkeys()
                .get("selected_text_replace")
                .map(String::as_str),
            Some("")
        );
    }

    #[test]
    fn sanitizes_text_translation_bounds() {
        let mut cfg = AppConfig::default();
        cfg.text_history_limit = 999;
        cfg.auto_clipboard_max_chars = 10;
        cfg.replace_paste_delay_ms = 5;
        cfg.text_submit_shortcut = "invalid".to_string();
        cfg.sanitize();
        assert_eq!(cfg.text_history_limit, 200);
        assert_eq!(cfg.auto_clipboard_max_chars, 200);
        assert_eq!(cfg.replace_paste_delay_ms, 20);
        assert_eq!(cfg.text_submit_shortcut, "ctrl_enter");
    }
}
