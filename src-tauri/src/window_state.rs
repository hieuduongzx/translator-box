use tauri::{PhysicalPosition, Position, Size, WebviewWindow};

use crate::config::MainWindowGeometry;

pub const MIN_WINDOW_W: f64 = 860.0;
pub const MIN_WINDOW_H: f64 = 560.0;

pub const DEFAULT_MIN_W: f64 = 1280.0;
pub const DEFAULT_MIN_H: f64 = 820.0;
pub const DEFAULT_MAX_W: f64 = 1760.0;
pub const DEFAULT_MAX_H: f64 = 1100.0;

pub const DEFAULT_WIDTH_RATIO: f64 = 0.80;
pub const DEFAULT_HEIGHT_RATIO: f64 = 0.85;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct MonitorWorkArea {
    pub left: i32,
    pub top: i32,
    pub right: i32,
    pub bottom: i32,
    pub scale_factor: f64,
    pub is_primary: bool,
}

impl MonitorWorkArea {
    pub fn width(&self) -> i32 {
        (self.right - self.left).max(1)
    }

    pub fn height(&self) -> i32 {
        (self.bottom - self.top).max(1)
    }

    pub fn safe_scale(&self) -> f64 {
        if self.scale_factor.is_finite() && self.scale_factor > 0.25 && self.scale_factor <= 8.0 {
            self.scale_factor
        } else {
            1.0
        }
    }

    pub fn logical_width(&self) -> f64 {
        self.width() as f64 / self.safe_scale()
    }

    pub fn logical_height(&self) -> f64 {
        self.height() as f64 / self.safe_scale()
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ResolvedWindowPlacement {
    pub x_phys: i32,
    pub y_phys: i32,
    pub w_logical: f64,
    pub h_logical: f64,
    pub maximized: bool,
}

/// Compute first-open default placement for the given monitor's work area (excluding taskbar):
/// 80% width x 85% height in logical pixels, clamped to [1280..1760] x [820..1100], centered.
/// If the monitor's logical work area is smaller than 1280x820, open maximized.
pub fn compute_default_placement(mon: &MonitorWorkArea) -> ResolvedWindowPlacement {
    let scale = mon.safe_scale();
    let work_w_log = mon.logical_width();
    let work_h_log = mon.logical_height();

    if work_w_log < DEFAULT_MIN_W || work_h_log < DEFAULT_MIN_H {
        let normal_w = work_w_log.clamp(MIN_WINDOW_W.min(work_w_log), DEFAULT_MIN_W);
        let normal_h = work_h_log.clamp(MIN_WINDOW_H.min(work_h_log), DEFAULT_MIN_H);
        let w_phys = (normal_w * scale).round() as i32;
        let h_phys = (normal_h * scale).round() as i32;
        let x_phys = mon.left + ((mon.width() - w_phys) / 2).max(0);
        let y_phys = mon.top + ((mon.height() - h_phys) / 2).max(0);
        return ResolvedWindowPlacement {
            x_phys,
            y_phys,
            w_logical: normal_w.round(),
            h_logical: normal_h.round(),
            maximized: true,
        };
    }

    let w_logical = (work_w_log * DEFAULT_WIDTH_RATIO)
        .round()
        .clamp(DEFAULT_MIN_W, DEFAULT_MAX_W)
        .min(work_w_log.floor());
    let h_logical = (work_h_log * DEFAULT_HEIGHT_RATIO)
        .round()
        .clamp(DEFAULT_MIN_H, DEFAULT_MAX_H)
        .min(work_h_log.floor());

    let w_phys = (w_logical * scale).round() as i32;
    let h_phys = (h_logical * scale).round() as i32;
    let x_phys = mon.left + ((mon.width() - w_phys) / 2).max(0);
    let y_phys = mon.top + ((mon.height() - h_phys) / 2).max(0);

    ResolvedWindowPlacement {
        x_phys,
        y_phys,
        w_logical,
        h_logical,
        maximized: false,
    }
}

/// Resolve initial main window placement from saved geometry + currently connected monitors.
/// Falls back to `compute_default_placement` on the active monitor if no valid saved geometry
/// exists or if the saved position is off-screen (e.g., an unplugged secondary monitor).
pub fn resolve_window_placement(
    saved: &MainWindowGeometry,
    monitors: &[MonitorWorkArea],
    current_idx: usize,
) -> ResolvedWindowPlacement {
    if monitors.is_empty() {
        return ResolvedWindowPlacement {
            x_phys: 100,
            y_phys: 80,
            w_logical: DEFAULT_MIN_W,
            h_logical: DEFAULT_MIN_H,
            maximized: false,
        };
    }
    let active_mon = &monitors[current_idx.min(monitors.len() - 1)];

    let (Some(sx), Some(sy), Some(sw), Some(sh)) = (saved.x, saved.y, saved.w, saved.h) else {
        return compute_default_placement(active_mon);
    };
    if (sw as f64) < MIN_WINDOW_W || (sh as f64) < MIN_WINDOW_H {
        return compute_default_placement(active_mon);
    }

    // Find the monitor with the largest visible intersection with the saved rectangle.
    let mut best_mon: Option<(&MonitorWorkArea, i64)> = None;
    for mon in monitors {
        let scale = mon.safe_scale();
        let w_phys = ((sw as f64) * scale).round() as i32;
        let h_phys = ((sh as f64) * scale).round() as i32;

        let inter_l = sx.max(mon.left);
        let inter_t = sy.max(mon.top);
        let inter_r = (sx + w_phys).min(mon.right);
        let inter_b = (sy + h_phys).min(mon.bottom);
        let inter_w = inter_r - inter_l;
        let inter_h = inter_b - inter_t;

        let min_visible_w = ((160.0 * scale).round() as i32).min(w_phys / 2).max(60);
        let min_visible_h = ((60.0 * scale).round() as i32).min(h_phys / 2).max(36);
        let titlebar_margin = (16.0 * scale).round() as i32;
        let titlebar_min_bottom = (48.0 * scale).round() as i32;
        let titlebar_reachable =
            sy >= mon.top - titlebar_margin && sy <= mon.bottom - titlebar_min_bottom;

        if inter_w >= min_visible_w && inter_h >= min_visible_h && titlebar_reachable {
            let area = (inter_w as i64) * (inter_h as i64);
            if best_mon.map(|(_, a)| area > a).unwrap_or(true) {
                best_mon = Some((mon, area));
            }
        }
    }

    let Some((mon, _)) = best_mon else {
        return compute_default_placement(active_mon);
    };

    let scale = mon.safe_scale();
    let max_w = mon.logical_width().floor().max(MIN_WINDOW_W);
    let max_h = mon.logical_height().floor().max(MIN_WINDOW_H);
    let w_logical = (sw as f64).clamp(MIN_WINDOW_W, max_w).round();
    let h_logical = (sh as f64).clamp(MIN_WINDOW_H, max_h).round();
    let w_phys = (w_logical * scale).round() as i32;
    let h_phys = (h_logical * scale).round() as i32;

    // Keep titlebar reachable and prevent the window from starting completely outside the work area.
    let min_keep_x = ((160.0 * scale).round() as i32).min(w_phys);
    let min_x = mon.left - w_phys + min_keep_x;
    let max_x = mon.right - min_keep_x;
    let x_phys = if sx < min_x || sx > max_x {
        mon.left + ((mon.width() - w_phys) / 2).max(0)
    } else {
        sx
    };

    let min_y = mon.top;
    let max_y = (mon.bottom - ((64.0 * scale).round() as i32).min(h_phys)).max(mon.top);
    let y_phys = sy.clamp(min_y, max_y);

    ResolvedWindowPlacement {
        x_phys,
        y_phys,
        w_logical,
        h_logical,
        maximized: saved.maximized,
    }
}

#[cfg(windows)]
pub fn enumerate_monitors_and_current() -> (Vec<MonitorWorkArea>, usize) {
    use windows::Win32::Foundation::{BOOL, LPARAM, POINT, RECT};
    use windows::Win32::Graphics::Gdi::{
        EnumDisplayMonitors, GetMonitorInfoW, MonitorFromPoint, HDC, HMONITOR, MONITORINFO,
        MONITOR_DEFAULTTOPRIMARY,
    };
    use windows::Win32::UI::HiDpi::{GetDpiForMonitor, MDT_EFFECTIVE_DPI};
    use windows::Win32::UI::WindowsAndMessaging::{GetCursorPos, MONITORINFOF_PRIMARY};

    struct CollectCtx {
        target: HMONITOR,
        monitors: Vec<MonitorWorkArea>,
        current_idx: Option<usize>,
    }

    unsafe extern "system" fn enum_proc(
        hmon: HMONITOR,
        _hdc: HDC,
        _rc: *mut RECT,
        lparam: LPARAM,
    ) -> BOOL {
        let ctx = &mut *(lparam.0 as *mut CollectCtx);
        let mut info = MONITORINFO {
            cbSize: std::mem::size_of::<MONITORINFO>() as u32,
            ..Default::default()
        };
        if GetMonitorInfoW(hmon, &mut info).as_bool() {
            let mut dpi_x: u32 = 96;
            let mut dpi_y: u32 = 96;
            let scale = if GetDpiForMonitor(hmon, MDT_EFFECTIVE_DPI, &mut dpi_x, &mut dpi_y).is_ok()
                && dpi_x >= 48
            {
                dpi_x as f64 / 96.0
            } else {
                1.0
            };
            let idx = ctx.monitors.len();
            let is_primary = (info.dwFlags & MONITORINFOF_PRIMARY) != 0;
            ctx.monitors.push(MonitorWorkArea {
                left: info.rcWork.left,
                top: info.rcWork.top,
                right: info.rcWork.right,
                bottom: info.rcWork.bottom,
                scale_factor: scale,
                is_primary,
            });
            if hmon == ctx.target {
                ctx.current_idx = Some(idx);
            }
        }
        BOOL(1)
    }

    unsafe {
        let mut pt = POINT::default();
        let target = if GetCursorPos(&mut pt).is_ok() {
            MonitorFromPoint(pt, MONITOR_DEFAULTTOPRIMARY)
        } else {
            MonitorFromPoint(POINT { x: 0, y: 0 }, MONITOR_DEFAULTTOPRIMARY)
        };

        let mut ctx = CollectCtx {
            target,
            monitors: Vec::new(),
            current_idx: None,
        };
        let _ = EnumDisplayMonitors(
            HDC::default(),
            None,
            Some(enum_proc),
            LPARAM(&mut ctx as *mut CollectCtx as isize),
        );

        let fallback_idx = ctx
            .monitors
            .iter()
            .position(|m| m.is_primary)
            .unwrap_or(0);
        let current_idx = ctx.current_idx.unwrap_or(fallback_idx);
        (ctx.monitors, current_idx)
    }
}

#[cfg(not(windows))]
pub fn enumerate_monitors_and_current() -> (Vec<MonitorWorkArea>, usize) {
    (
        vec![MonitorWorkArea {
            left: 0,
            top: 0,
            right: 1920,
            bottom: 1040,
            scale_factor: 1.0,
            is_primary: true,
        }],
        0,
    )
}

pub fn resolve_initial_main_placement(saved: &MainWindowGeometry) -> ResolvedWindowPlacement {
    let (monitors, current_idx) = enumerate_monitors_and_current();
    resolve_window_placement(saved, &monitors, current_idx)
}

/// Apply pre-computed placement to a hidden window so there is no jump/flicker when shown.
pub fn apply_placement_hidden(win: &WebviewWindow, placement: &ResolvedWindowPlacement) {
    // Move to the target monitor first so Windows adopts that monitor's DPI scale factor,
    // then set the logical inner size and re-apply position.
    let _ = win.set_position(Position::Physical(PhysicalPosition::new(
        placement.x_phys,
        placement.y_phys,
    )));
    let _ = win.set_size(Size::Logical(tauri::LogicalSize::new(
        placement.w_logical,
        placement.h_logical,
    )));
    let _ = win.set_position(Position::Physical(PhysicalPosition::new(
        placement.x_phys,
        placement.y_phys,
    )));
}

/// Snapshot current window position/size/maximized state into a `MainWindowGeometry`.
/// Preserves the last normal (unmaximized) position & size when minimized or maximized.
pub fn capture_window_geometry(
    win: &WebviewWindow,
    prev: &MainWindowGeometry,
) -> MainWindowGeometry {
    let minimized = win.is_minimized().unwrap_or(false);
    if minimized {
        return prev.clone();
    }

    let maximized = win.is_maximized().unwrap_or(false);
    if maximized {
        let mut out = prev.clone();
        out.maximized = true;
        return out;
    }

    let scale = win
        .scale_factor()
        .ok()
        .filter(|s| s.is_finite() && *s > 0.25 && *s <= 8.0)
        .unwrap_or(1.0);

    let mut out = prev.clone();
    out.maximized = false;

    if let Ok(pos) = win.outer_position() {
        // Ignore sentinel coordinates that Windows uses when iconic (-32000).
        if pos.x > -30000 && pos.y > -30000 {
            out.x = Some(pos.x);
            out.y = Some(pos.y);
        }
    }
    if let Ok(size) = win.inner_size() {
        let w_log = (size.width as f64 / scale).round() as u32;
        let h_log = (size.height as f64 / scale).round() as u32;
        if w_log >= MIN_WINDOW_W as u32 && h_log >= MIN_WINDOW_H as u32 {
            out.w = Some(w_log);
            out.h = Some(h_log);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mon(l: i32, t: i32, r: i32, b: i32, scale: f64, primary: bool) -> MonitorWorkArea {
        MonitorWorkArea {
            left: l,
            top: t,
            right: r,
            bottom: b,
            scale_factor: scale,
            is_primary: primary,
        }
    }

    #[test]
    fn default_2560x1440_clamps_to_max_1760x1100_centered() {
        let m = mon(0, 0, 2560, 1392, 1.0, true);
        let p = compute_default_placement(&m);
        assert!(!p.maximized);
        assert_eq!(p.w_logical, 1760.0);
        assert_eq!(p.h_logical, 1100.0);
        assert_eq!(p.x_phys, (2560 - 1760) / 2);
        assert_eq!(p.y_phys, (1392 - 1100) / 2);
    }

    #[test]
    fn default_1920x1080_uses_80x85_percent_centered() {
        let m = mon(0, 0, 1920, 1032, 1.0, true);
        let p = compute_default_placement(&m);
        assert!(!p.maximized);
        assert_eq!(p.w_logical, 1536.0);
        assert_eq!(p.h_logical, 877.0);
        assert_eq!(p.x_phys, (1920 - 1536) / 2);
        assert_eq!(p.y_phys, (1032 - 877) / 2);
    }

    #[test]
    fn default_1920x1080_125dpi_clamps_to_min_1280x820() {
        let m = mon(0, 0, 1920, 1032, 1.25, true);
        let p = compute_default_placement(&m);
        assert!(!p.maximized);
        assert_eq!(p.w_logical, 1280.0);
        assert_eq!(p.h_logical, 820.0);
        // 1280 * 1.25 = 1600, 820 * 1.25 = 1025
        assert_eq!(p.x_phys, (1920 - 1600) / 2);
        assert_eq!(p.y_phys, (1032 - 1025) / 2);
    }

    #[test]
    fn default_small_screen_opens_maximized() {
        // 1366x768 laptop (work area 1366x720) -> height < 820 -> maximized
        let m = mon(0, 0, 1366, 720, 1.0, true);
        let p = compute_default_placement(&m);
        assert!(p.maximized);

        // 1920x1080 at 150% DPI (logical 1280x688) -> height < 820 -> maximized
        let m2 = mon(0, 0, 1920, 1032, 1.5, true);
        let p2 = compute_default_placement(&m2);
        assert!(p2.maximized);
    }

    #[test]
    fn restores_valid_saved_geometry_including_maximized() {
        let monitors = vec![
            mon(-1920, 0, 0, 1032, 1.0, false),
            mon(0, 0, 2560, 1392, 1.0, true),
        ];
        let saved = MainWindowGeometry {
            x: Some(-1700),
            y: Some(100),
            w: Some(1400),
            h: Some(860),
            maximized: true,
        };
        let p = resolve_window_placement(&saved, &monitors, 1);
        assert_eq!(p.x_phys, -1700);
        assert_eq!(p.y_phys, 100);
        assert_eq!(p.w_logical, 1400.0);
        assert_eq!(p.h_logical, 860.0);
        assert!(p.maximized);
    }

    #[test]
    fn falls_back_to_default_when_saved_monitor_unplugged() {
        // Secondary left monitor (-1920..0) was unplugged; only primary remains.
        let monitors = vec![mon(0, 0, 2560, 1392, 1.0, true)];
        let saved = MainWindowGeometry {
            x: Some(-1700),
            y: Some(100),
            w: Some(1400),
            h: Some(860),
            maximized: false,
        };
        let p = resolve_window_placement(&saved, &monitors, 0);
        assert!(!p.maximized);
        assert_eq!(p.w_logical, 1760.0);
        assert_eq!(p.h_logical, 1100.0);
        assert_eq!(p.x_phys, 400);
        assert_eq!(p.y_phys, 146);
    }
}
