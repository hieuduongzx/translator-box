export interface GlossaryEntry {
  source: string;
  target: string;
}

export interface CustomAiProvider {
  id: string;
  name: string;
  endpoint: string;
  api_key: string;
  models: string[];
}

export interface SavedLiveRegion {
  bbox: [number, number, number, number];
  mode: "overlay" | "frame";
  output?: [number, number, number, number];
}

export interface HudGeometry {
  x: number | null;
  y: number | null;
  w: number | null;
  h: number | null;
}

export interface MainWindowGeometry {
  x: number | null;
  y: number | null;
  w: number | null;
  h: number | null;
  maximized: boolean;
}

export interface AppConfig {
  ui_theme: "system" | "light" | "dark";
  sidebar_collapsed: boolean;
  main_window_geometry?: MainWindowGeometry;

  target_language: string;
  replace_target_language: string;
  auto_translate_clipboard: boolean;
  translator: string;
  llm_endpoint: string;
  llm_api_key: string;
  llm_model: string;
  ai_keys: Record<string, string>;
  ai_models: Record<string, string[]>;
  ai_disabled_models: Record<string, string[]>;
  custom_providers: CustomAiProvider[];
  translation_glossary: GlossaryEntry[];

  text_source_language: string;
  text_target_language: string;
  text_translator: string;
  text_llm_model: string;
  text_auto_copy_result: boolean;
  text_keep_history: boolean;
  text_persist_history: boolean;
  text_history_limit: number;
  text_submit_shortcut: "ctrl_enter" | "enter";
  auto_clipboard_max_chars: number;
  replace_enabled: boolean;
  replace_preserve_formatting: boolean;
  replace_show_undo_original: boolean;
  replace_restore_clipboard: boolean;
  replace_paste_delay_ms: number;

  soniox_api_key: string;
  soniox_audio_source: "microphone" | "system";
  soniox_input_device: string;
  soniox_system_device: string;
  soniox_translation_mode: "one_way" | "two_way";
  soniox_target_language: string;
  soniox_language_a: string;
  soniox_language_b: string;
  soniox_speaker_diarization: boolean;
  soniox_speaker_setting_version: number;
  soniox_display_mode: "bilingual" | "translation";
  soniox_show_history: boolean;
  soniox_text_alignment: "left" | "center" | "right";
  soniox_context_text: string;
  soniox_context_terms: string;

  ocr_language: string;
  ocr_engine: "auto" | "windows" | "rapidocr";
  ocr_model: string;
  ocr_backend: string;
  ocr_acceleration: boolean;

  auto_update: boolean;
  skipped_update_version: string;

  live_focus_app_id: string;
  live_focus_app_label: string;
  live_interval_ms: number;
  live_trigger_mode: "hybrid" | "auto" | "input";
  live_regions: SavedLiveRegion[];

  hud_geometry: HudGeometry;
  hud_font_family: string;
  hud_font_size: number;
  hud_text_color: string;
  hud_border_width: number;
  hud_border_color: string;
  hud_background_color: string;
  hud_background_enabled: boolean;
  hud_frame_transparent: boolean;
  hud_shadow_radius: number;
  hud_shadow_color: string;
  hud_pinned: boolean;
  hud_text_align: "left" | "center" | "right";
  hud_text_valign: "top" | "center" | "bottom";

  hotkeys: Record<string, string>;
}

export interface AppMeta {
  version: string;
  name: string;
  app_id: string;
  publisher: string;
}

export interface HistoryEntry {
  id: string;
  timestamp: string;
  source_kind: string;
  original: string;
  translated: string;
  target_language: string;
}

export interface ReplaceCompletedPayload {
  original: string;
  translated: string;
  target_language: string;
  timestamp: string;
}

export interface TranslateResultPayload {
  original: string;
  translated: string;
  image_data_url: string | null;
}

export interface LiveRegionInfo {
  id: number;
  bbox: [number, number, number, number];
  mode: "overlay" | "frame";
  output: [number, number, number, number] | null;
  last_text: string;
}

export interface LiveStatePayload {
  running: boolean;
  paused_by_focus: boolean;
  regions: LiveRegionInfo[];
}

export interface LiveFrameUpdate {
  region_id: number;
  number: number;
  text: string;
  bbox: [number, number, number, number];
  output: [number, number, number, number] | null;
}

export interface DesktopApplication {
  application_id: string;
  name: string;
  title: string;
  label: string;
}

export interface OcrEngineStatusInfo {
  available: boolean;
  detail: string;
}

export interface OcrModelInfo {
  id: string;
  label: string;
  languages: string;
  size_mb: number;
  installed: boolean;
  det_filename: string;
  rec_filename: string;
  dict_filename: string;
}

export interface AudioDeviceOption {
  label: string;
  id: string;
}

export interface TranscriptBlock {
  kind: "speech" | "translation";
  text: string;
  language: string | null;
  speaker: string | null;
  is_final: boolean;
}

export interface SonioxStatePayload {
  state: "idle" | "connecting" | "listening" | "reconnecting" | "standby" | "stopping";
  source: string;
  error: string | null;
  blocks: TranscriptBlock[];
}

export interface StatusEvent {
  text: string;
  state: "ready" | "busy" | "error";
}
