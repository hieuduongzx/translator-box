pub mod capture;
pub mod clipboard_ops;
pub mod commands;
pub mod config;
pub mod constants;
pub mod desktop_apps;
pub mod hotkeys;
pub mod inpaint;
pub mod live;
pub mod ocr;
pub mod overlay_win32;
pub mod soniox;
pub mod translate;
pub mod updater;
pub mod version;
pub mod window_state;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use parking_lot::Mutex;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent};

static EXPLICIT_QUIT: AtomicBool = AtomicBool::new(false);

pub fn request_explicit_quit() {
    EXPLICIT_QUIT.store(true, Ordering::SeqCst);
}

pub fn persist_main_window_geometry(app: &AppHandle) {
    let Some(state) = app.try_state::<Arc<AppState>>() else {
        return;
    };
    let final_geom = if let Some(win) = app.get_webview_window("main") {
        let mut live = state.live_main_geometry.lock();
        if win.is_visible().unwrap_or(false) {
            *live = window_state::capture_window_geometry(&win, &live);
        }
        live.clone()
    } else {
        return;
    };
    let mut cfg = state.config.lock();
    if cfg.main_window_geometry != final_geom {
        cfg.main_window_geometry = final_geom;
        let _ = cfg.save();
    }
}

pub fn open_or_focus_main_window(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.show();
        let _ = win.unminimize();
        let _ = win.set_focus();
        return;
    }

    let saved = app
        .try_state::<Arc<AppState>>()
        .map(|st| st.config.lock().main_window_geometry.clone())
        .unwrap_or_default();
    let placement = window_state::resolve_initial_main_placement(&saved);

    if let Some(st) = app.try_state::<Arc<AppState>>() {
        st.pending_main_maximize
            .store(placement.maximized, Ordering::SeqCst);
        *st.live_main_geometry.lock() = config::MainWindowGeometry {
            x: Some(placement.x_phys),
            y: Some(placement.y_phys),
            w: Some(placement.w_logical.round() as u32),
            h: Some(placement.h_logical.round() as u32),
            maximized: placement.maximized,
        };
    }

    let Ok(win) = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("Translator2k")
        .inner_size(placement.w_logical, placement.h_logical)
        .min_inner_size(window_state::MIN_WINDOW_W, window_state::MIN_WINDOW_H)
        .decorations(false)
        .resizable(true)
        .visible(false)
        .build()
    else {
        return;
    };

    window_state::apply_placement_hidden(&win, &placement);

    let app_for_events = app.clone();
    let win_for_events = win.clone();
    win.on_window_event(move |event| match event {
        WindowEvent::Moved(_) | WindowEvent::Resized(_) => {
            if !win_for_events.is_visible().unwrap_or(false) {
                return;
            }
            if let Some(st) = app_for_events.try_state::<Arc<AppState>>() {
                let mut live = st.live_main_geometry.lock();
                *live = window_state::capture_window_geometry(&win_for_events, &live);
            }
        }
        WindowEvent::CloseRequested { .. } => {
            persist_main_window_geometry(&app_for_events);
        }
        _ => {}
    });
}

pub fn open_or_focus_hud_window(app: &AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("hud") {
        let _ = win.show();
        let _ = win.unminimize();
        let _ = win.set_focus();
        let _ = app.emit("hud-show-bar", ());
        return Ok(());
    }

    let (saved_pos, saved_size, pinned) = app
        .try_state::<Arc<AppState>>()
        .map(|st| {
            let cfg = st.config.lock();
            let g = &cfg.hud_geometry;
            let pos = match (g.x, g.y) {
                (Some(x), Some(y)) if x > -2000 && y > -2000 => Some((x as f64, y as f64)),
                _ => None,
            };
            let w = (g.w.unwrap_or(780) as f64).clamp(560.0, 1400.0);
            let h = (g.h.unwrap_or(240) as f64).clamp(150.0, 700.0);
            (pos, (w, h), cfg.hud_pinned)
        })
        .unwrap_or((None, (780.0, 240.0), true));

    let mut builder = WebviewWindowBuilder::new(app, "hud", WebviewUrl::App("index.html".into()))
        .title("Translator2k HUD")
        .inner_size(saved_size.0, saved_size.1)
        .min_inner_size(560.0, 150.0)
        .decorations(false)
        .maximizable(false)
        .transparent(true)
        .shadow(false)
        .always_on_top(pinned)
        .skip_taskbar(true);

    if let Some((x, y)) = saved_pos {
        builder = builder.position(x, y);
    } else {
        builder = builder.center();
    }

    let win = builder
        .build()
        .map_err(|e| format!("Không tạo được cửa sổ HUD nổi: {e}"))?;

    #[cfg(windows)]
    if let Ok(hwnd) = win.hwnd() {
        commands::exclude_hwnd_from_capture_pub(hwnd.0 as isize);
    }
    Ok(())
}

#[cfg(windows)]
fn trim_working_set() {
    use windows::Win32::System::Threading::{GetCurrentProcess, SetProcessWorkingSetSize};
    unsafe {
        let _ = SetProcessWorkingSetSize(GetCurrentProcess(), usize::MAX, usize::MAX);
    }
}

#[cfg(not(windows))]
fn trim_working_set() {}

use crate::clipboard_ops::ClipboardWatcher;
use crate::commands::{
    emit_status, run_clipboard_image, run_region_to_overlay, run_region_to_text,
    run_selected_text_replace, AppState,
};
use crate::config::AppConfig;
use crate::hotkeys::HotkeyManager;
use crate::live::LiveController;
use crate::overlay_win32::OverlayManager;
use crate::soniox::SonioxManager;
use crate::translate::translate_text;

fn dispatch_hotkey_action(app: AppHandle, action: String) {
    let state = app.state::<Arc<AppState>>().inner().clone();
    tauri::async_runtime::spawn(async move {
        let res: Result<(), String> = match action.as_str() {
            "region_to_text" => run_region_to_text(&app, &state).await.map(|_| ()),
            "region_to_overlay" => run_region_to_overlay(&app, &state).await.map(|_| ()),
            "clipboard_image_replace" => run_clipboard_image(&app, &state, true).await.map(|_| ()),
            "clipboard_image_to_text" => run_clipboard_image(&app, &state, false).await.map(|_| ()),
            "selected_text_replace" => run_selected_text_replace(&app, &state).await.map(|_| ()),
            "quick_translate" => {
                open_or_focus_main_window(&app);
                let _ = app.emit("navigate", "translate");
                Ok(())
            }
            "region_to_live" => {
                if let Ok(Some(bbox)) =
                    tokio::task::spawn_blocking(overlay_win32::select_screen_region)
                        .await
                        .unwrap_or(Ok(None))
                {
                    if state.live.add_region(bbox, "overlay").is_ok() {
                        let mut cfg = state.config.lock();
                        cfg.live_regions = state.live.saved_regions();
                        let _ = cfg.save();
                        let _ = app.emit("live-state", state.live.snapshot());
                    }
                }
                Ok(())
            }
            "region_to_live_frame" => {
                if let Ok(Some(bbox)) =
                    tokio::task::spawn_blocking(overlay_win32::select_screen_region)
                        .await
                        .unwrap_or(Ok(None))
                {
                    if let Ok(added) = state.live.add_region(bbox, "frame") {
                        {
                            let mut cfg = state.config.lock();
                            cfg.live_regions = state.live.saved_regions();
                            let _ = cfg.save();
                        }
                        let _ = commands::open_live_output_window(app.clone(), added.id, added.bbox).await;
                        let _ = app.emit("live-state", state.live.snapshot());
                    }
                }
                Ok(())
            }
            "live_toggle" => {
                if state.live.is_running() {
                    state.live.stop(&app);
                    emit_status(&app, "Đã dừng dịch Live", "ready");
                } else {
                    for r in &state.live.snapshot().regions {
                        if r.mode == "frame" {
                            let _ = commands::open_live_output_window(app.clone(), r.id, r.bbox).await;
                        }
                    }
                    if let Err(e) = state.live.start(app.clone(), state.config.clone()) {
                        emit_status(&app, &e, "error");
                    } else {
                        emit_status(&app, "Đang chạy dịch Live…", "ready");
                    }
                }
                Ok(())
            }
            "live_rescan" => {
                state.live.force_rescan();
                Ok(())
            }
            "toggle_auto_clipboard" => {
                let next = !state.clipboard.is_enabled();
                state.clipboard.set_enabled(next);
                let cfg_snap = {
                    let mut cfg = state.config.lock();
                    cfg.auto_translate_clipboard = next;
                    let _ = cfg.save();
                    cfg.clone()
                };
                let _ = app.emit("config-updated", cfg_snap);
                emit_status(
                    &app,
                    if next {
                        "Đã bật tự dịch khi Copy (Ctrl+C)"
                    } else {
                        "Đã tắt tự dịch khi Copy"
                    },
                    "ready",
                );
                Ok(())
            }
            "quit" => {
                persist_main_window_geometry(&app);
                EXPLICIT_QUIT.store(true, Ordering::SeqCst);
                state.overlays.clear_all();
                state.soniox.stop();
                app.exit(0);
                Ok(())
            }
            _ => Ok(()),
        };
        if let Err(err) = res {
            emit_status(&app, &err, "error");
        }
    });
}

fn spawn_clipboard_loop(app: AppHandle, state: Arc<AppState>) {
    tauri::async_runtime::spawn(async move {
        let mut tick = tokio::time::interval(Duration::from_millis(140));
        loop {
            tick.tick().await;
            if let Some(copied) = state.clipboard.poll_new_text() {
                let params = state.build_translate_params(None);
                emit_status(&app, "Đang tự dịch clipboard…", "busy");
                match translate_text(&copied, &params).await {
                    Ok(translated) => {
                        state.record_history(&app, "clipboard", &copied, &translated, &params.target);
                        emit_status(&app, "Đã dịch văn bản vừa copy", "ready");
                    }
                    Err(err) => emit_status(&app, &err, "error"),
                }
            }
        }
    });
}

fn setup_tray(app: &AppHandle) -> tauri::Result<()> {
    let hud_i = MenuItem::with_id(app, "tray_hud", "Bật / ẩn thanh HUD", true, None::<&str>)?;
    let hud_bar_i = MenuItem::with_id(
        app,
        "tray_hud_bar",
        "Hiện thanh công cụ HUD",
        true,
        None::<&str>,
    )?;
    let show_i = MenuItem::with_id(app, "tray_show", "Mở bảng cài đặt…", true, None::<&str>)?;
    let overlay_i = MenuItem::with_id(
        app,
        "tray_overlay",
        "Chọn vùng → Overlay tại chỗ",
        true,
        None::<&str>,
    )?;
    let text_i = MenuItem::with_id(
        app,
        "tray_text",
        "Chọn vùng → Khung dịch",
        true,
        None::<&str>,
    )?;
    let live_i = MenuItem::with_id(
        app,
        "tray_live",
        "Live: Bắt đầu / Dừng",
        true,
        None::<&str>,
    )?;
    let clear_i = MenuItem::with_id(
        app,
        "tray_clear_overlays",
        "Xoá mọi overlay đang hiện",
        true,
        None::<&str>,
    )?;
    let quit_i = MenuItem::with_id(app, "tray_quit", "Thoát", true, None::<&str>)?;

    let menu = Menu::with_items(
        app,
        &[&hud_i, &hud_bar_i, &show_i, &overlay_i, &text_i, &live_i, &clear_i, &quit_i],
    )?;

    let mut builder = TrayIconBuilder::new()
        .menu(&menu)
        .tooltip("Translator2k")
        .on_menu_event(|app, event| match event.id.as_ref() {
            "tray_show" => open_or_focus_main_window(app),
            "tray_hud" => {
                let app_clone = app.clone();
                tauri::async_runtime::spawn(async move {
                    let _ = commands::toggle_hud_window(app_clone).await;
                });
            }
            "tray_hud_bar" => {
                let app_clone = app.clone();
                tauri::async_runtime::spawn(async move {
                    let _ = open_or_focus_hud_window(&app_clone);
                });
            }
            "tray_overlay" => dispatch_hotkey_action(app.clone(), "region_to_overlay".into()),
            "tray_text" => dispatch_hotkey_action(app.clone(), "region_to_text".into()),
            "tray_live" => dispatch_hotkey_action(app.clone(), "live_toggle".into()),
            "tray_clear_overlays" => {
                app.state::<Arc<AppState>>().overlays.clear_all();
            }
            "tray_quit" => {
                persist_main_window_geometry(app);
                EXPLICIT_QUIT.store(true, Ordering::SeqCst);
                let st = app.state::<Arc<AppState>>();
                st.overlays.clear_all();
                st.soniox.stop();
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let app_clone = tray.app_handle().clone();
                tauri::async_runtime::spawn(async move {
                    let _ = open_or_focus_hud_window(&app_clone);
                });
            }
        });

    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            let app_clone = app.clone();
            tauri::async_runtime::spawn(async move {
                let _ = open_or_focus_hud_window(&app_clone);
            });
        }))
        .setup(|app| {
            let cfg = AppConfig::load();
            let auto_clip = cfg.auto_translate_clipboard;
            let initial_regions = cfg.live_regions.clone();
            let initial_hotkeys = cfg.hotkeys.clone();
            let overlays = Arc::new(OverlayManager::new());
            let live = Arc::new(LiveController::new(&initial_regions, overlays.clone()));
            let clipboard = Arc::new(ClipboardWatcher::new(auto_clip));
            let soniox = Arc::new(SonioxManager::new());

            let app_handle_hk = app.handle().clone();
            let hotkeys = HotkeyManager::new(move |action| {
                dispatch_hotkey_action(app_handle_hk.clone(), action);
            });
            let _ = hotkeys.apply(&initial_hotkeys);

            let initial_main_geom = cfg.main_window_geometry.clone();
            let state = Arc::new(AppState {
                config: Arc::new(Mutex::new(cfg)),
                history: Mutex::new(Vec::new()),
                hotkeys,
                clipboard,
                overlays,
                live,
                soniox,
                live_main_geometry: Mutex::new(initial_main_geom),
                pending_main_maximize: AtomicBool::new(false),
            });
            app.manage(state.clone());

            let _ = setup_tray(app.handle());
            spawn_clipboard_loop(app.handle().clone(), state);

            // Khi khởi động: chỉ mở thanh HUD nổi gọn nhẹ, không bật bảng điều khiển to.
            let _ = open_or_focus_hud_window(app.handle());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_app_meta,
            commands::get_config,
            commands::save_config,
            commands::get_history,
            commands::clear_history,
            commands::copy_text,
            commands::translate_text_cmd,
            commands::action_region_to_text,
            commands::action_region_to_overlay,
            commands::action_clipboard_image_replace,
            commands::action_clipboard_image_to_text,
            commands::action_selected_text_replace,
            commands::clear_overlays,
            commands::toggle_hud_window,
            commands::start_window_drag,
            commands::open_main_window,
            commands::show_main_window,
            commands::quit_app,
            commands::get_live_state,
            commands::live_add_region,
            commands::live_edit_region,
            commands::live_remove_region,
            commands::live_clear_regions,
            commands::live_start,
            commands::live_stop,
            commands::live_rescan,
            commands::open_live_output_window,
            commands::list_desktop_apps,
            commands::get_ocr_status,
            commands::list_ocr_models,
            commands::download_ocr_model,
            commands::list_audio_devices_cmd,
            commands::get_soniox_state,
            commands::soniox_start,
            commands::soniox_stop,
            commands::soniox_clear,
            commands::reset_hotkeys,
            commands::check_for_update,
            commands::install_update,
        ])
        .build(tauri::generate_context!())
        .expect("Lỗi khởi tạo Translator2k")
        .run(|_app_handle, event| {
            // Khi người dùng đóng cửa sổ chính: WebView2 được giải phóng hoàn toàn,
            // chỉ giữ lõi Rust chạy nền ở khay hệ thống (phím tắt, clipboard, live, overlay).
            if let RunEvent::ExitRequested { api, .. } = event {
                if !EXPLICIT_QUIT.load(Ordering::SeqCst) {
                    api.prevent_exit();
                    trim_working_set();
                }
            }
        });
}
