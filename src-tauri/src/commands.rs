use std::collections::BTreeMap;
use std::fs;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;

use chrono::Local;
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, State, WebviewUrl, WebviewWindowBuilder};

use crate::capture::{capture_region, encode_rgb_to_data_url, grab_clipboard_image};
use crate::clipboard_ops::{
    copy_selected_text, paste_replacement, write_clipboard_text, ClipboardWatcher,
};
use crate::config::{history_path, AppConfig, MainWindowGeometry};
use crate::constants::DEFAULT_HOTKEYS;
use crate::desktop_apps::{list_desktop_applications, DesktopApplication};
use crate::hotkeys::HotkeyManager;
use crate::inpaint::reconstruct_layout;
use crate::live::{LiveController, LiveRegionInfo, LiveStatePayload};
use crate::ocr::{
    merge_regions_into_blocks, merge_regions_into_lines, ocr_engine_status, ocr_layout,
    onnx_ocr::{download_model, list_models, OcrModelInfo},
    OcrEngineStatusInfo,
};
use crate::overlay_win32::{
    edit_screen_region, exclude_hwnd_from_capture, render_translated_image, select_screen_region,
    OverlayItem, OverlayManager,
};
use crate::soniox::{
    list_audio_devices, AudioDeviceOption, SonioxManager, SonioxStartParams, SonioxStatePayload,
};
use crate::translate::{
    translate_regions, translate_text, translate_text_with_formatting, TranslateParams,
};
use crate::version::{APP_ID, APP_NAME, APP_VERSION, PUBLISHER};

static NEXT_ONCE_OVERLAY_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HistoryEntry {
    pub id: String,
    pub timestamp: String,
    pub source_kind: String,
    pub original: String,
    pub translated: String,
    pub target_language: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReplaceCompletedPayload {
    pub original: String,
    pub translated: String,
    pub target_language: String,
    pub timestamp: String,
}

pub fn load_persisted_history(cfg: &AppConfig) -> Vec<HistoryEntry> {
    if !cfg.text_keep_history || !cfg.text_persist_history {
        return Vec::new();
    }
    let path = history_path();
    let Ok(raw) = fs::read_to_string(&path) else {
        return Vec::new();
    };
    let mut entries = serde_json::from_str::<Vec<HistoryEntry>>(&raw).unwrap_or_default();
    entries.truncate(cfg.text_history_limit.clamp(5, 200) as usize);
    entries
}

fn save_persisted_history(entries: &[HistoryEntry]) {
    let path = history_path();
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Ok(payload) = serde_json::to_string_pretty(entries) {
        let tmp = path.with_extension("json.tmp");
        if fs::write(&tmp, payload.as_bytes()).is_ok() {
            let _ = fs::rename(&tmp, &path).or_else(|_| {
                let _ = fs::remove_file(&path);
                fs::rename(&tmp, &path)
            });
        }
    }
}

fn clear_persisted_history() {
    let _ = fs::remove_file(history_path());
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppMeta {
    pub version: String,
    pub name: String,
    pub app_id: String,
    pub publisher: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TranslateResultPayload {
    pub original: String,
    pub translated: String,
    pub image_data_url: Option<String>,
}

pub struct AppState {
    pub config: Arc<Mutex<AppConfig>>,
    pub history: Mutex<Vec<HistoryEntry>>,
    pub hotkeys: HotkeyManager,
    pub clipboard: Arc<ClipboardWatcher>,
    pub overlays: Arc<OverlayManager>,
    pub live: Arc<LiveController>,
    pub soniox: Arc<SonioxManager>,
    pub live_main_geometry: Mutex<MainWindowGeometry>,
    pub pending_main_maximize: AtomicBool,
}

impl AppState {
    pub fn record_history(
        &self,
        app: &AppHandle,
        source_kind: &str,
        original: &str,
        translated: &str,
        target: &str,
    ) {
        if translated.trim().is_empty() {
            return;
        }
        let (keep, persist, limit) = {
            let cfg = self.config.lock();
            (
                cfg.text_keep_history,
                cfg.text_persist_history,
                cfg.text_history_limit.clamp(5, 200) as usize,
            )
        };
        let entry = HistoryEntry {
            id: uuid::Uuid::new_v4().to_string(),
            timestamp: Local::now().format("%H:%M:%S").to_string(),
            source_kind: source_kind.to_string(),
            original: original.to_string(),
            translated: translated.to_string(),
            target_language: target.to_string(),
        };
        if keep {
            let mut guard = self.history.lock();
            guard.insert(0, entry.clone());
            guard.truncate(limit);
            if persist {
                save_persisted_history(&guard);
            }
        }
        let _ = app.emit("translation-result", entry);
    }

    pub fn build_translate_params(&self, target_override: Option<&str>) -> TranslateParams {
        let cfg = self.config.lock();
        let (service, llm_endpoint, llm_api_key, llm_model) = cfg.resolve_llm();
        TranslateParams {
            service,
            source: "auto".to_string(),
            target: target_override
                .map(String::from)
                .unwrap_or_else(|| cfg.target_language.clone()),
            llm_endpoint,
            llm_api_key,
            llm_model,
            glossary: cfg.translation_glossary.clone(),
        }
    }

    pub fn build_text_translate_params(
        &self,
        source_override: Option<&str>,
        target_override: Option<&str>,
    ) -> TranslateParams {
        let cfg = self.config.lock();
        let (service, llm_endpoint, llm_api_key, llm_model) = cfg.resolve_text_llm();
        let source = source_override
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(String::from)
            .unwrap_or_else(|| cfg.text_source_language.clone());
        let target = target_override
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(String::from)
            .unwrap_or_else(|| cfg.text_target_language.clone());
        TranslateParams {
            service,
            source,
            target,
            llm_endpoint,
            llm_api_key,
            llm_model,
            glossary: cfg.translation_glossary.clone(),
        }
    }

    pub fn maybe_auto_copy(&self, translated: &str) {
        if translated.trim().is_empty() {
            return;
        }
        if self.config.lock().text_auto_copy_result {
            if write_clipboard_text(translated).is_ok() {
                self.clipboard.mark_internal_write(translated);
            }
        }
    }
}

pub fn emit_status(app: &AppHandle, text: &str, state: &str) {
    let _ = app.emit(
        "app-status",
        serde_json::json!({ "text": text, "state": state }),
    );
}

#[tauri::command]
pub fn get_app_meta() -> AppMeta {
    AppMeta {
        version: APP_VERSION.to_string(),
        name: APP_NAME.to_string(),
        app_id: APP_ID.to_string(),
        publisher: PUBLISHER.to_string(),
    }
}

#[tauri::command]
pub fn get_config(state: State<'_, Arc<AppState>>) -> AppConfig {
    state.config.lock().clone()
}

#[tauri::command]
pub fn save_config(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
    mut config: AppConfig,
) -> Result<AppConfig, String> {
    // Always preserve Rust-tracked main window geometry so frontend edits never clobber it.
    config.main_window_geometry = state.config.lock().main_window_geometry.clone();
    config.sanitize();
    let prev_effective_hotkeys = state.config.lock().effective_hotkeys();
    let next_effective_hotkeys = config.effective_hotkeys();
    let hotkeys_changed = prev_effective_hotkeys != next_effective_hotkeys;
    let auto_clip = config.auto_translate_clipboard;
    let auto_clip_max = config.auto_clipboard_max_chars as usize;
    let keep_history = config.text_keep_history;
    let persist_history = config.text_persist_history;
    let history_limit = config.text_history_limit.clamp(5, 200) as usize;

    config.save()?;
    *state.config.lock() = config.clone();
    state.clipboard.set_max_chars(auto_clip_max);
    state.clipboard.set_enabled(auto_clip);

    {
        let mut hist = state.history.lock();
        if hist.len() > history_limit {
            hist.truncate(history_limit);
        }
        if keep_history && persist_history {
            save_persisted_history(&hist);
        } else if !persist_history {
            clear_persisted_history();
        }
    }

    if hotkeys_changed {
        if let Err(warn) = state.hotkeys.apply(&next_effective_hotkeys) {
            emit_status(&app, &warn, "error");
        }
    }
    let _ = app.emit("config-updated", config.clone());
    Ok(config)
}

#[tauri::command]
pub fn get_history(state: State<'_, Arc<AppState>>) -> Vec<HistoryEntry> {
    state.history.lock().clone()
}

#[tauri::command]
pub fn clear_history(state: State<'_, Arc<AppState>>) {
    state.history.lock().clear();
    clear_persisted_history();
}

#[tauri::command]
pub fn copy_text(state: State<'_, Arc<AppState>>, text: String) -> Result<(), String> {
    write_clipboard_text(&text)?;
    state.clipboard.mark_internal_write(&text);
    Ok(())
}

#[tauri::command]
pub async fn translate_text_cmd(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
    text: String,
    target: Option<String>,
    source: Option<String>,
) -> Result<TranslateResultPayload, String> {
    let params = state.build_text_translate_params(source.as_deref(), target.as_deref());
    emit_status(&app, "Đang dịch văn bản…", "busy");
    match translate_text(&text, &params).await {
        Ok(translated) => {
            state.maybe_auto_copy(&translated);
            state.record_history(&app, "text", &text, &translated, &params.target);
            emit_status(&app, "Đã dịch xong", "ready");
            Ok(TranslateResultPayload {
                original: text,
                translated,
                image_data_url: None,
            })
        }
        Err(err) => {
            emit_status(&app, &err, "error");
            Err(err)
        }
    }
}

pub async fn run_region_to_text(
    app: &AppHandle,
    state: &Arc<AppState>,
) -> Result<TranslateResultPayload, String> {
    emit_status(app, "Chọn vùng màn hình cần dịch…", "busy");
    state.overlays.set_esc_suspended(true);
    let sel_res = tokio::task::spawn_blocking(select_screen_region).await;
    state.overlays.set_esc_suspended(false);
    let bbox = sel_res.map_err(|e| format!("Lỗi chọn vùng: {e}"))??;
    let Some(bbox) = bbox else {
        emit_status(app, "Đã huỷ chọn vùng", "ready");
        return Ok(TranslateResultPayload {
            original: String::new(),
            translated: String::new(),
            image_data_url: None,
        });
    };

    emit_status(app, "Đang OCR & dịch vùng màn hình…", "busy");
    let frame = tokio::task::spawn_blocking(move || capture_region(bbox))
        .await
        .map_err(|e| format!("Lỗi chụp màn hình: {e}"))??;

    let (lang, engine, model, backend) = {
        let c = state.config.lock();
        (
            c.ocr_language.clone(),
            c.ocr_engine.clone(),
            c.ocr_model.clone(),
            c.ocr_backend.clone(),
        )
    };
    let img = frame.image;
    let regions = tokio::task::spawn_blocking(move || {
        ocr_layout(&img, &lang, &engine, &model, &backend, true)
    })
    .await
    .map_err(|e| format!("Lỗi OCR: {e}"))??;
    let merged = merge_regions_into_lines(&regions);
    let original = merged
        .iter()
        .map(|r| r.text.as_str())
        .collect::<Vec<_>>()
        .join("\n");
    if original.trim().is_empty() {
        emit_status(app, "Không tìm thấy chữ trong vùng đã chọn", "ready");
        return Err("Không tìm thấy chữ trong vùng đã chọn.".to_string());
    }

    let params = state.build_translate_params(None);
    let translated = translate_text(&original, &params).await?;
    state.maybe_auto_copy(&translated);
    state.record_history(app, "screen", &original, &translated, &params.target);
    emit_status(app, "Đã dịch vùng màn hình", "ready");
    Ok(TranslateResultPayload {
        original,
        translated,
        image_data_url: None,
    })
}

pub async fn run_region_to_overlay(
    app: &AppHandle,
    state: &Arc<AppState>,
) -> Result<TranslateResultPayload, String> {
    emit_status(app, "Chọn vùng để vẽ overlay bản dịch…", "busy");
    state.overlays.set_esc_suspended(true);
    let sel_res = tokio::task::spawn_blocking(select_screen_region).await;
    state.overlays.set_esc_suspended(false);
    let bbox = sel_res.map_err(|e| format!("Lỗi chọn vùng: {e}"))??;
    let Some(bbox) = bbox else {
        emit_status(app, "Đã huỷ chọn vùng", "ready");
        return Ok(TranslateResultPayload {
            original: String::new(),
            translated: String::new(),
            image_data_url: None,
        });
    };

    emit_status(app, "Đang OCR, dựng nền & dịch overlay…", "busy");
    let frame = tokio::task::spawn_blocking(move || capture_region(bbox))
        .await
        .map_err(|e| format!("Lỗi chụp màn hình: {e}"))??;

    let (lang, engine, model, backend) = {
        let c = state.config.lock();
        (
            c.ocr_language.clone(),
            c.ocr_engine.clone(),
            c.ocr_model.clone(),
            c.ocr_backend.clone(),
        )
    };
    let img = frame.image;
    let raw_regions = tokio::task::spawn_blocking({
        let img = img.clone();
        move || ocr_layout(&img, &lang, &engine, &model, &backend, true)
    })
    .await
    .map_err(|e| format!("Lỗi OCR: {e}"))??;
    let merged = merge_regions_into_blocks(&raw_regions);
    if merged.is_empty() {
        emit_status(app, "Không tìm thấy chữ trong vùng chọn", "ready");
        return Err("Không tìm thấy chữ trong vùng đã chọn.".to_string());
    }

    // Run inpainting in parallel with network translation
    let inpaint_handle = tokio::task::spawn_blocking({
        let img = img.clone();
        let merged = merged.clone();
        move || reconstruct_layout(&img, &merged)
    });

    let params = state.build_translate_params(None);
    let translated_list = translate_regions(&merged, &params).await?;
    let ((sw, sh), visuals) = inpaint_handle
        .await
        .map_err(|e| format!("Lỗi dựng nền overlay: {e}"))?;

    let items: Vec<OverlayItem> = merged
        .iter()
        .zip(visuals.into_iter())
        .zip(translated_list.iter())
        .map(|((reg, vis), text)| OverlayItem {
            bbox: reg.bbox,
            text: text.clone(),
            source_text: reg.text.clone(),
            bg: vis.bg,
            fg: vis.fg,
            patch_rect: Some(vis.rect),
            patch_rgb: vis.patch_rgb,
            patch_size: vis.patch_size,
            ink_rect: vis.ink_rect,
            stroke_thickness: vis.stroke_thickness,
            source_lines: reg.line_count,
            line_ink: vis.line_ink,
            outline: vis.outline,
            align: reg.align.clone(),
            room: vis.room,
        })
        .collect();

    let overlay_key = format!(
        "once-{}",
        NEXT_ONCE_OVERLAY_ID.fetch_add(1, Ordering::Relaxed)
    );
    state.overlays.show(&overlay_key, bbox, (sw, sh), items);
    let original = merged
        .iter()
        .map(|r| r.text.as_str())
        .collect::<Vec<_>>()
        .join("\n");
    let translated = translated_list.join("\n");
    state.record_history(app, "overlay", &original, &translated, &params.target);
    emit_status(
        app,
        "Đã hiện overlay (bấm vào overlay hoặc nhấn Esc để đóng)",
        "ready",
    );
    Ok(TranslateResultPayload {
        original,
        translated,
        image_data_url: None,
    })
}

pub async fn run_clipboard_image(
    app: &AppHandle,
    state: &Arc<AppState>,
    replace_image: bool,
) -> Result<TranslateResultPayload, String> {
    emit_status(app, "Đang đọc & OCR ảnh từ clipboard…", "busy");
    let img = tokio::task::spawn_blocking(grab_clipboard_image)
        .await
        .map_err(|e| format!("Lỗi đọc ảnh clipboard: {e}"))??;

    let (lang, engine, model, backend) = {
        let c = state.config.lock();
        (
            c.ocr_language.clone(),
            c.ocr_engine.clone(),
            c.ocr_model.clone(),
            c.ocr_backend.clone(),
        )
    };
    let raw_regions = tokio::task::spawn_blocking({
        let img = img.clone();
        move || ocr_layout(&img, &lang, &engine, &model, &backend, true)
    })
    .await
    .map_err(|e| format!("Lỗi OCR ảnh clipboard: {e}"))??;

    let merged = if replace_image {
        merge_regions_into_blocks(&raw_regions)
    } else {
        merge_regions_into_lines(&raw_regions)
    };
    if merged.is_empty() {
        emit_status(app, "Không thấy chữ trong ảnh clipboard", "ready");
        return Err("Không tìm thấy chữ trong ảnh clipboard.".to_string());
    }

    let params = state.build_translate_params(None);
    let translated_list = translate_regions(&merged, &params).await?;
    let original = merged
        .iter()
        .map(|r| r.text.as_str())
        .collect::<Vec<_>>()
        .join("\n");
    let translated = translated_list.join("\n");

    let image_data_url = if replace_image {
        let img_clone = img.clone();
        let merged_clone = merged.clone();
        let tr_clone = translated_list.clone();
        let rendered = tokio::task::spawn_blocking(move || {
            let ((_sw, _sh), visuals) = reconstruct_layout(&img_clone, &merged_clone);
            let items: Vec<OverlayItem> = merged_clone
                .iter()
                .zip(visuals.into_iter())
                .zip(tr_clone.into_iter())
                .map(|((reg, vis), text)| OverlayItem {
                    bbox: reg.bbox,
                    text,
                    source_text: reg.text.clone(),
                    bg: vis.bg,
                    fg: vis.fg,
                    patch_rect: Some(vis.rect),
                    patch_rgb: vis.patch_rgb,
                    patch_size: vis.patch_size,
                    ink_rect: vis.ink_rect,
                    stroke_thickness: vis.stroke_thickness,
                    source_lines: reg.line_count,
                    line_ink: vis.line_ink,
                    outline: vis.outline,
                    align: reg.align.clone(),
                    room: vis.room,
                })
                .collect();
            let out_img = render_translated_image(&img_clone, &items);
            encode_rgb_to_data_url(&out_img)
        })
        .await
        .map_err(|e| format!("Lỗi dựng ảnh dịch: {e}"))??;
        Some(rendered)
    } else {
        None
    };

    if !replace_image {
        state.maybe_auto_copy(&translated);
    }
    state.record_history(app, "clipboard-image", &original, &translated, &params.target);
    emit_status(app, "Đã dịch ảnh clipboard", "ready");
    Ok(TranslateResultPayload {
        original,
        translated,
        image_data_url,
    })
}

pub async fn run_selected_text_replace(
    app: &AppHandle,
    state: &Arc<AppState>,
) -> Result<TranslateResultPayload, String> {
    let (
        replace_enabled,
        replace_target,
        preserve_formatting,
        show_undo_original,
        restore_clipboard,
        paste_delay_ms,
    ) = {
        let cfg = state.config.lock();
        (
            cfg.replace_enabled,
            cfg.replace_target_language.clone(),
            cfg.replace_preserve_formatting,
            cfg.replace_show_undo_original,
            cfg.replace_restore_clipboard,
            cfg.replace_paste_delay_ms as u64,
        )
    };
    if !replace_enabled {
        let msg = "Chế độ Dịch & thay thế tại chỗ đang tắt trong Cài đặt → Dịch văn bản.";
        emit_status(app, msg, "ready");
        return Err(msg.to_string());
    }

    emit_status(app, "Đang lấy văn bản đang bôi đen…", "busy");
    let (selected, previous_clip) =
        tokio::task::spawn_blocking(move || copy_selected_text(preserve_formatting))
            .await
            .map_err(|e| format!("Lỗi đọc vùng chọn: {e}"))??;
    state.clipboard.mark_internal_write(&selected);

    let params = state.build_text_translate_params(None, Some(&replace_target));
    emit_status(app, "Đang dịch để thay thế tại chỗ…", "busy");
    let translated =
        translate_text_with_formatting(&selected, &params, preserve_formatting).await?;

    let tr_clone = translated.clone();
    let restore_clone = if restore_clipboard {
        previous_clip.clone()
    } else {
        None
    };
    state.clipboard.mark_internal_write(&translated);
    tokio::task::spawn_blocking(move || {
        paste_replacement(&tr_clone, restore_clone.as_deref(), paste_delay_ms)
    })
    .await
    .map_err(|e| format!("Lỗi dán bản dịch: {e}"))??;
    if restore_clipboard {
        if let Some(ref prev) = previous_clip {
            state.clipboard.mark_internal_write(prev);
        }
    }

    state.record_history(app, "replace", &selected, &translated, &params.target);
    if show_undo_original {
        let _ = app.emit(
            "replace-completed",
            ReplaceCompletedPayload {
                original: selected.clone(),
                translated: translated.clone(),
                target_language: params.target.clone(),
                timestamp: Local::now().format("%H:%M:%S").to_string(),
            },
        );
    }
    emit_status(app, "Đã thay thế văn bản tại chỗ", "ready");
    Ok(TranslateResultPayload {
        original: selected,
        translated,
        image_data_url: None,
    })
}

#[tauri::command]
pub async fn action_region_to_text(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
) -> Result<TranslateResultPayload, String> {
    run_region_to_text(&app, &state).await
}

#[tauri::command]
pub async fn action_region_to_overlay(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
) -> Result<TranslateResultPayload, String> {
    run_region_to_overlay(&app, &state).await
}

#[tauri::command]
pub async fn action_clipboard_image_replace(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
) -> Result<TranslateResultPayload, String> {
    run_clipboard_image(&app, &state, true).await
}

#[tauri::command]
pub async fn action_clipboard_image_to_text(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
) -> Result<TranslateResultPayload, String> {
    run_clipboard_image(&app, &state, false).await
}

#[tauri::command]
pub async fn action_selected_text_replace(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
) -> Result<TranslateResultPayload, String> {
    run_selected_text_replace(&app, &state).await
}

#[tauri::command]
pub fn clear_overlays(state: State<'_, Arc<AppState>>) {
    state.overlays.clear_all();
}

#[cfg(windows)]
pub fn exclude_hwnd_from_capture_pub(hwnd_raw: isize) {
    exclude_hwnd_from_capture(hwnd_raw);
}

#[tauri::command]
pub fn start_window_drag(window: tauri::WebviewWindow) -> Result<(), String> {
    #[cfg(windows)]
    {
        use windows::Win32::Foundation::{HWND, LPARAM, WPARAM};
        use windows::Win32::UI::Input::KeyboardAndMouse::ReleaseCapture;
        use windows::Win32::UI::WindowsAndMessaging::{PostMessageW, WM_SYSCOMMAND};
        let hwnd = window
            .hwnd()
            .map_err(|e| format!("Không lấy được HWND: {e}"))?;
        unsafe {
            let _ = ReleaseCapture();
            // SC_MOVE (0xF010) | HTCAPTION (0x0002) = 0xF012:
            // Kéo cửa sổ native ngay lập tức tại vị trí chuột hiện tại.
            let _ = PostMessageW(
                HWND(hwnd.0 as _),
                WM_SYSCOMMAND,
                WPARAM(0xF012),
                LPARAM(0),
            );
        }
        Ok(())
    }
    #[cfg(not(windows))]
    {
        window.start_dragging().map_err(|e| e.to_string())
    }
}

#[tauri::command]
pub async fn toggle_hud_window(app: AppHandle) -> Result<bool, String> {
    if let Some(win) = app.get_webview_window("hud") {
        let _ = win.close();
        return Ok(false);
    }
    crate::open_or_focus_hud_window(&app)?;
    Ok(true)
}

#[tauri::command]
pub async fn open_main_window(app: AppHandle, page: Option<String>) {
    crate::open_or_focus_main_window(&app);
    if let Some(p) = page {
        let _ = app.emit("navigate", p);
    }
}

#[tauri::command]
pub fn show_main_window(app: AppHandle, state: State<'_, Arc<AppState>>) {
    if let Some(win) = app.get_webview_window("main") {
        let should_max = state.pending_main_maximize.swap(false, Ordering::SeqCst);
        if should_max {
            let _ = win.maximize();
        }
        let _ = win.show();
        let _ = win.set_focus();
    }
}

#[tauri::command]
pub fn quit_app(app: AppHandle, state: State<'_, Arc<AppState>>) {
    crate::persist_main_window_geometry(&app);
    crate::request_explicit_quit();
    state.overlays.clear_all();
    state.soniox.stop();
    app.exit(0);
}

// ---------------------------------------------------------------------------
// Live Translation Commands
// ---------------------------------------------------------------------------

#[tauri::command]
pub fn get_live_state(state: State<'_, Arc<AppState>>) -> LiveStatePayload {
    state.live.snapshot()
}

#[tauri::command]
pub async fn live_add_region(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
    mode: String,
) -> Result<Option<LiveRegionInfo>, String> {
    emit_status(&app, "Kéo chọn vùng màn hình cho Live…", "busy");
    state.overlays.set_esc_suspended(true);
    let sel_res = tokio::task::spawn_blocking(select_screen_region).await;
    state.overlays.set_esc_suspended(false);
    let bbox = sel_res.map_err(|e| format!("Lỗi chọn vùng: {e}"))??;
    let Some(bbox) = bbox else {
        emit_status(&app, "Đã huỷ thêm vùng Live", "ready");
        return Ok(None);
    };
    let info = state.live.add_region(bbox, &mode)?;
    {
        let mut cfg = state.config.lock();
        cfg.live_regions = state.live.saved_regions();
        let _ = cfg.save();
    }
    let _ = app.emit("live-state", state.live.snapshot());
    emit_status(&app, "Đã thêm vùng Live mới", "ready");
    Ok(Some(info))
}

#[tauri::command]
pub async fn live_edit_region(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
    id: u64,
) -> Result<LiveStatePayload, String> {
    let target = state
        .live
        .snapshot()
        .regions
        .into_iter()
        .find(|r| r.id == id)
        .ok_or_else(|| "Không tìm thấy vùng Live cần sửa.".to_string())?;
    emit_status(
        &app,
        "Kéo di chuyển/đổi cỡ vùng Live (Enter hoặc nháy đúp để lưu, Esc huỷ)…",
        "busy",
    );
    let initial = target.bbox;
    let mode = target.mode;
    state.overlays.set_esc_suspended(true);
    let edit_res = tokio::task::spawn_blocking(move || edit_screen_region(initial, &mode)).await;
    state.overlays.set_esc_suspended(false);
    let edited = edit_res.map_err(|e| format!("Lỗi chỉnh vùng: {e}"))??;
    if let Some(new_bbox) = edited {
        state.live.update_region_bbox(id, new_bbox);
        {
            let mut cfg = state.config.lock();
            cfg.live_regions = state.live.saved_regions();
            let _ = cfg.save();
        }
        state.live.force_rescan();
        emit_status(&app, "Đã cập nhật vị trí vùng Live", "ready");
    } else {
        emit_status(&app, "Đã huỷ chỉnh vùng Live", "ready");
    }
    let snap = state.live.snapshot();
    let _ = app.emit("live-state", snap.clone());
    Ok(snap)
}

#[tauri::command]
pub fn live_remove_region(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
    id: u64,
) -> LiveStatePayload {
    state.live.remove_region(id);
    if let Some(win) = app.get_webview_window(&format!("live-output-{id}")) {
        let _ = win.close();
    }
    {
        let mut cfg = state.config.lock();
        cfg.live_regions = state.live.saved_regions();
        let _ = cfg.save();
    }
    let snap = state.live.snapshot();
    let _ = app.emit("live-state", snap.clone());
    snap
}

#[tauri::command]
pub fn live_clear_regions(app: AppHandle, state: State<'_, Arc<AppState>>) -> LiveStatePayload {
    state.live.stop(&app);
    state.live.clear_regions();
    {
        let mut cfg = state.config.lock();
        cfg.live_regions.clear();
        let _ = cfg.save();
    }
    let snap = state.live.snapshot();
    let _ = app.emit("live-state", snap.clone());
    snap
}

#[tauri::command]
pub async fn live_start(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
) -> Result<LiveStatePayload, String> {
    let snap_before = state.live.snapshot();
    for r in &snap_before.regions {
        if r.mode == "frame" {
            let _ = open_live_output_window(app.clone(), r.id, r.bbox).await;
        }
    }
    state.live.start(app.clone(), state.config.clone())?;
    emit_status(&app, "Đang chạy dịch Live…", "ready");
    Ok(state.live.snapshot())
}

#[tauri::command]
pub fn live_stop(app: AppHandle, state: State<'_, Arc<AppState>>) -> LiveStatePayload {
    state.live.stop(&app);
    emit_status(&app, "Đã dừng dịch Live", "ready");
    state.live.snapshot()
}

#[tauri::command]
pub fn live_rescan(state: State<'_, Arc<AppState>>) {
    state.live.force_rescan();
}

#[tauri::command]
pub async fn open_live_output_window(
    app: AppHandle,
    region_id: u64,
    bbox: [i32; 4],
) -> Result<(), String> {
    let label = format!("live-output-{region_id}");
    if let Some(win) = app.get_webview_window(&label) {
        let _ = win.show();
        return Ok(());
    }
    let w = (bbox[2] - bbox[0]).max(420).min(900) as f64;
    let h = 156.0;
    let win = WebviewWindowBuilder::new(&app, &label, WebviewUrl::App("index.html".into()))
        .title(format!("Bản dịch vùng {region_id}"))
        .position(bbox[0] as f64, (bbox[3] + 8) as f64)
        .inner_size(w, h)
        .min_inner_size(280.0, 76.0)
        .decorations(false)
        .maximizable(false)
        .transparent(true)
        .shadow(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .build()
        .map_err(|e| format!("Không tạo được khung output vùng Live: {e}"))?;

    #[cfg(windows)]
    if let Ok(hwnd) = win.hwnd() {
        exclude_hwnd_from_capture(hwnd.0 as isize);
    }
    Ok(())
}

#[tauri::command]
pub fn list_desktop_apps() -> Vec<DesktopApplication> {
    list_desktop_applications()
}

// ---------------------------------------------------------------------------
// OCR Commands
// ---------------------------------------------------------------------------

#[tauri::command]
pub fn get_ocr_status(engine: String, model: String, backend: String) -> OcrEngineStatusInfo {
    ocr_engine_status(&engine, &model, &backend)
}

#[tauri::command]
pub fn list_ocr_models() -> Vec<OcrModelInfo> {
    list_models()
}

#[tauri::command]
pub async fn download_ocr_model(app: AppHandle, model_id: String) -> Result<Vec<OcrModelInfo>, String> {
    emit_status(&app, &format!("Đang tải model OCR {model_id}…"), "busy");
    download_model(&model_id).await?;
    emit_status(&app, "Đã tải xong model OCR ngoại tuyến", "ready");
    Ok(list_models())
}

// ---------------------------------------------------------------------------
// Audio / Soniox Commands
// ---------------------------------------------------------------------------

#[tauri::command]
pub fn list_audio_devices_cmd(is_system: bool) -> Vec<AudioDeviceOption> {
    list_audio_devices(is_system)
}

#[tauri::command]
pub fn get_soniox_state(state: State<'_, Arc<AppState>>) -> SonioxStatePayload {
    state.soniox.snapshot()
}

#[tauri::command]
pub async fn soniox_start(app: AppHandle, state: State<'_, Arc<AppState>>) -> Result<(), String> {
    let cfg = state.config.lock().clone();
    let params = SonioxStartParams {
        api_key: cfg.soniox_api_key,
        audio_source: cfg.soniox_audio_source,
        device_id: cfg.soniox_input_device,
        system_device: cfg.soniox_system_device,
        translation_mode: cfg.soniox_translation_mode,
        target_language: cfg.soniox_target_language,
        language_a: cfg.soniox_language_a,
        language_b: cfg.soniox_language_b,
        speaker_diarization: cfg.soniox_speaker_diarization,
        context_text: cfg.soniox_context_text,
        context_terms: cfg.soniox_context_terms,
    };
    state.soniox.start(params, move |payload| {
        let _ = app.emit("soniox-state", payload);
    })
}

#[tauri::command]
pub fn soniox_stop(app: AppHandle, state: State<'_, Arc<AppState>>) -> SonioxStatePayload {
    state.soniox.stop();
    let snap = state.soniox.snapshot();
    let _ = app.emit("soniox-state", snap.clone());
    snap
}

#[tauri::command]
pub fn soniox_clear(app: AppHandle, state: State<'_, Arc<AppState>>) -> SonioxStatePayload {
    state.soniox.clear_transcript();
    let snap = state.soniox.snapshot();
    let _ = app.emit("soniox-state", snap.clone());
    snap
}

// ---------------------------------------------------------------------------
// Hotkeys & Updater Commands
// ---------------------------------------------------------------------------

#[tauri::command]
pub fn reset_hotkeys(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
) -> Result<AppConfig, String> {
    let mut defaults = BTreeMap::new();
    for &(action, combo) in DEFAULT_HOTKEYS {
        defaults.insert(action.to_string(), combo.to_string());
    }
    let updated = {
        let mut cfg = state.config.lock();
        cfg.hotkeys = defaults;
        cfg.save()?;
        cfg.clone()
    };
    let _ = state.hotkeys.apply(&updated.effective_hotkeys());
    let _ = app.emit("config-updated", updated.clone());
    Ok(updated)
}
