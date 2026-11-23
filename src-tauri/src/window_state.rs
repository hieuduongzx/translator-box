use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use tauri::{LogicalSize, Monitor, PhysicalPosition, State, WebviewWindow, WindowEvent};

pub const MIN_DEFAULT_W: f64 = 1280.0;
pub const MIN_DEFAULT_H: f64 = 820.0;
pub const MAX_DEFAULT_W: f64 = 1760.0;
pub const MAX_DEFAULT_H: f64 = 1100.0;
pub const MIN_WINDOW_W: f64 = 860.0;
pub const MIN_WINDOW_H: f64 = 560.0;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct WorkArea {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
    pub scale_factor: f64,
}

impl WorkArea {
    pub fn from_monitor(m: &Monitor) -> Self {
        let wa = m.work_area();
        Self {
            x: wa.position.x,
            y: wa.position.y,
            width: wa.size.width,
            height: wa.size.height,
            scale_factor: m.scale_factor().max(0.5),
        }
    }

    pub fn logical_width(&self) -> f64 {
        self.width as f64 / self.scale_factor
    }

    pub fn logical_height(&self) -> f64 {
        self.height as f64 / self.scale_factor
    }

    pub fn right(&self) -> i32 {
        self.x.saturating_add(self.width as i32)
    }

    pub fn bottom(&self) -> i32 {
        self.y.saturating_add(self.height as i32)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SavedWindowState {
    pub x: i32,
    pub y: i32,
    pub width: f64,
    pub height: f64,
    pub maximized: bool,
}

pub fn state_file_path(app_name: &str) -> PathBuf {
    let base = std::env::var_os("LOCALAPPDATA")
        .or_else(|| std::env::var_os("APPDATA"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    base.join(app_name).join("window-state.json")
}

pub fn load_state(path: &Path) -> Option<SavedWindowState> {
    let raw = std::fs::read_to_string(path).ok()?;
    let st: SavedWindowState = serde_json::from_str(raw.trim_start_matches('\u{FEFF}')).ok()?;
    if !st.width.is_finite()
        || !st.height.is_finite()
        || st.width < MIN_WINDOW_W
        || st.height < MIN_WINDOW_H
        || st.width > 16384.0
        || st.height > 16384.0
    {
        return None;
    }
    Some(st)
}

pub fn save_state(path: &Path, state: &SavedWindowState) {
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    if let Ok(json) = serde_json::to_string_pretty(state) {
        let tmp = path.with_extension("json.tmp");
        if std::fs::write(&tmp, &json).is_ok() {
            let _ = std::fs::rename(&tmp, path).or_else(|_| std::fs::write(path, &json));
        }
    }
}

/// Tính vị trí và kích thước mặc định cho lần mở đầu tiên trong `wa`:
/// - Rộng 80% × cao 85% vùng làm việc (trừ taskbar), giới hạn [1280×820 .. 1760×1100] (logical DIP), căn giữa.
/// - Nếu vùng làm việc nhỏ hơn 1280×820 thì mở maximize.
pub fn compute_default_state(wa: WorkArea) -> SavedWindowState {
    let wa_w = wa.logical_width();
    let wa_h = wa.logical_height();

    let (w_dip, h_dip, maximized) = if wa_w < MIN_DEFAULT_W || wa_h < MIN_DEFAULT_H {
        let fallback_w = (wa_w * 0.90).round().clamp(MIN_WINDOW_W.min(wa_w), wa_w);
        let fallback_h = (wa_h * 0.90).round().clamp(MIN_WINDOW_H.min(wa_h), wa_h);
        (fallback_w, fallback_h, true)
    } else {
        let target_w = (wa_w * 0.80)
            .round()
            .clamp(MIN_DEFAULT_W, MAX_DEFAULT_W)
            .min(wa_w);
        let target_h = (wa_h * 0.85)
            .round()
            .clamp(MIN_DEFAULT_H, MAX_DEFAULT_H)
            .min(wa_h);
        (target_w, target_h, false)
    };

    let phys_w = (w_dip * wa.scale_factor).round() as i32;
    let phys_h = (h_dip * wa.scale_factor).round() as i32;
    let x = wa.x + ((wa.width as i32 - phys_w) / 2).max(0);
    let y = wa.y + ((wa.height as i32 - phys_h) / 2).max(0);

    SavedWindowState {
        x,
        y,
        width: w_dip,
        height: h_dip,
        maximized,
    }
}

/// Kiểm tra trạng thái đã lưu với danh sách màn hình hiện có.
/// Nếu thanh tiêu đề nằm ngoài màn hình (ví dụ rút màn hình phụ), quay về mặc định trên `primary`.
pub fn resolve_window_state(
    saved: Option<SavedWindowState>,
    monitors: &[WorkArea],
    primary: WorkArea,
) -> SavedWindowState {
    let Some(st) = saved else {
        return compute_default_state(primary);
    };

    let mut best_match: Option<(i64, WorkArea)> = None;
    for &m in monitors {
        let phys_w = (st.width * m.scale_factor).round() as i32;
        let title_h = (40.0 * m.scale_factor).round().max(24.0) as i32;

        let ix1 = st.x.max(m.x);
        let iy1 = st.y.max(m.y);
        let ix2 = st.x.saturating_add(phys_w).min(m.right());
        let iy2 = st.y.saturating_add(title_h).min(m.bottom());

        let overlap_w = ix2 - ix1;
        let overlap_h = iy2 - iy1;
        let min_w = (120.0 * m.scale_factor).round() as i32;
        let min_h = (20.0 * m.scale_factor).round() as i32;

        if overlap_w >= min_w && overlap_h >= min_h {
            let area = (overlap_w as i64) * (overlap_h as i64);
            if best_match.as_ref().map_or(true, |(best_a, _)| area > *best_a) {
                best_match = Some((area, m));
            }
        }
    }

    let Some((_, m)) = best_match else {
        return compute_default_state(primary);
    };

    let wa_w = m.logical_width();
    let wa_h = m.logical_height();
    let clamped_w = st.width.clamp(MIN_WINDOW_W.min(wa_w), wa_w);
    let clamped_h = st.height.clamp(MIN_WINDOW_H.min(wa_h), wa_h);
    let phys_w = (clamped_w * m.scale_factor).round() as i32;

    let max_x = m.right().saturating_sub((120.0 * m.scale_factor).round() as i32);
    let min_x = m
        .x
        .saturating_sub(phys_w)
        .saturating_add((120.0 * m.scale_factor).round() as i32);
    let clamped_x = st.x.clamp(min_x.min(m.x), max_x.max(m.x));
    let max_y = m.bottom().saturating_sub((48.0 * m.scale_factor).round() as i32);
    let clamped_y = st.y.clamp(m.y, max_y.max(m.y));

    SavedWindowState {
        x: clamped_x,
        y: clamped_y,
        width: clamped_w,
        height: clamped_h,
        maximized: st.maximized,
    }
}

pub struct WindowLifecycle {
    should_maximize: AtomicBool,
    revealed: AtomicBool,
}

impl WindowLifecycle {
    /// Áp dụng vị trí & kích thước đã lưu (hoặc mặc định) lên cửa sổ đang ẩn,
    /// đồng thời gắn listener tự lưu lại vị trí/kích thước/maximize khi đóng.
    pub fn init_and_apply(window: &WebviewWindow, app_name: &str) -> Self {
        let state_path = state_file_path(app_name);
        let monitors: Vec<WorkArea> = window
            .available_monitors()
            .unwrap_or_default()
            .iter()
            .map(WorkArea::from_monitor)
            .collect();

        let primary = window
            .current_monitor()
            .ok()
            .flatten()
            .or_else(|| window.primary_monitor().ok().flatten())
            .map(|m| WorkArea::from_monitor(&m))
            .or_else(|| monitors.first().copied())
            .unwrap_or(WorkArea {
                x: 0,
                y: 0,
                width: 1920,
                height: 1040,
                scale_factor: 1.0,
            });

        let saved = load_state(&state_path);
        let resolved = resolve_window_state(saved, &monitors, primary);

        let _ = window.set_min_size(Some(LogicalSize::new(MIN_WINDOW_W, MIN_WINDOW_H)));
        let _ = window.set_position(PhysicalPosition::new(resolved.x, resolved.y));
        let _ = window.set_size(LogicalSize::new(resolved.width, resolved.height));

        let tracked = Arc::new(Mutex::new(resolved.clone()));
        let lifecycle = Self {
            should_maximize: AtomicBool::new(resolved.maximized),
            revealed: AtomicBool::new(false),
        };

        let win_clone = window.clone();
        let tracked_clone = tracked;
        let path_clone = state_path;

        window.on_window_event(move |event| match event {
            WindowEvent::Moved(_) | WindowEvent::Resized(_) => {
                if !win_clone.is_visible().unwrap_or(false)
                    || win_clone.is_minimized().unwrap_or(false)
                {
                    return;
                }
                capture_into(&win_clone, &tracked_clone);
            }
            WindowEvent::CloseRequested { .. } | WindowEvent::Destroyed => {
                if !win_clone.is_minimized().unwrap_or(false) {
                    capture_into(&win_clone, &tracked_clone);
                }
                if let Ok(guard) = tracked_clone.lock() {
                    save_state(&path_clone, &guard);
                }
            }
            _ => {}
        });

        lifecycle
    }

    /// Hiện cửa sổ (và maximize nếu cần) đúng một lần sau khi frontend vẽ xong để tránh chớp trắng.
    pub fn reveal(&self, window: &WebviewWindow) {
        if self.revealed.swap(true, Ordering::SeqCst) {
            return;
        }
        if self.should_maximize.load(Ordering::SeqCst) {
            let _ = window.maximize();
        }
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn capture_into(win: &WebviewWindow, tracked: &Arc<Mutex<SavedWindowState>>) {
    let Ok(is_max) = win.is_maximized() else {
        return;
    };
    if let Ok(mut guard) = tracked.lock() {
        guard.maximized = is_max;
        if !is_max {
            if let (Ok(pos), Ok(size), Ok(scale)) =
                (win.outer_position(), win.inner_size(), win.scale_factor())
            {
                let scale = scale.max(0.5);
                let w_dip = (size.width as f64 / scale).round();
                let h_dip = (size.height as f64 / scale).round();
                if w_dip >= MIN_WINDOW_W && h_dip >= MIN_WINDOW_H {
                    guard.x = pos.x;
                    guard.y = pos.y;
                    guard.width = w_dip;
                    guard.height = h_dip;
                }
            }
        }
    }
}

#[tauri::command]
pub fn window_reveal(window: WebviewWindow, lifecycle: State<'_, WindowLifecycle>) {
    lifecycle.reveal(&window);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_size_on_2560x1440_clamps_to_1760x1100_centered() {
        let wa = WorkArea {
            x: 0,
            y: 0,
            width: 2560,
            height: 1392,
            scale_factor: 1.0,
        };
        let st = compute_default_state(wa);
        assert!(!st.maximized);
        assert_eq!(st.width, 1760.0);
        assert_eq!(st.height, 1100.0);
        assert_eq!(st.x, (2560 - 1760) / 2);
        assert_eq!(st.y, (1392 - 1100) / 2);
    }

    #[test]
    fn default_size_on_1920x1080_uses_80_by_85_percent() {
        let wa = WorkArea {
            x: 0,
            y: 0,
            width: 1920,
            height: 1040,
            scale_factor: 1.0,
        };
        let st = compute_default_state(wa);
        assert!(!st.maximized);
        assert_eq!(st.width, 1536.0);
        assert_eq!(st.height, 884.0);
        assert_eq!(st.x, (1920 - 1536) / 2);
        assert_eq!(st.y, (1040 - 884) / 2);
    }

    #[test]
    fn default_size_on_1920x1080_dpi_125_clamps_to_min_1280x820() {
        let wa = WorkArea {
            x: 0,
            y: 0,
            width: 1920,
            height: 1030,
            scale_factor: 1.25,
        };
        let st = compute_default_state(wa);
        assert!(!st.maximized);
        assert_eq!(st.width, 1280.0);
        assert_eq!(st.height, 820.0);
    }

    #[test]
    fn default_size_on_small_or_high_dpi_screen_maximizes() {
        let wa = WorkArea {
            x: 0,
            y: 0,
            width: 1920,
            height: 1020,
            scale_factor: 1.5,
        };
        let st = compute_default_state(wa);
        assert!(st.maximized);
    }

    #[test]
    fn saved_state_offscreen_falls_back_to_default() {
        let primary = WorkArea {
            x: 0,
            y: 0,
            width: 2560,
            height: 1392,
            scale_factor: 1.0,
        };
        let unplugged = SavedWindowState {
            x: 3200,
            y: 120,
            width: 1400.0,
            height: 900.0,
            maximized: false,
        };
        let resolved = resolve_window_state(Some(unplugged), &[primary], primary);
        assert_eq!(resolved, compute_default_state(primary));
    }

    #[test]
    fn saved_state_on_valid_monitor_is_restored() {
        let primary = WorkArea {
            x: 0,
            y: 0,
            width: 2560,
            height: 1392,
            scale_factor: 1.0,
        };
        let saved = SavedWindowState {
            x: 200,
            y: 100,
            width: 1440.0,
            height: 920.0,
            maximized: true,
        };
        let resolved = resolve_window_state(Some(saved.clone()), &[primary], primary);
        assert_eq!(resolved, saved);
    }
}
