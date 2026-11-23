use std::collections::HashMap;
use std::sync::mpsc;
use std::thread;

use cosmic_text::{
    Align, Attrs, Buffer, Color, Family, FontSystem, Metrics, Shaping, SwashCache, Weight, Wrap,
};
use image::RgbImage;
use once_cell::sync::Lazy;
use parking_lot::Mutex;

#[derive(Debug, Clone)]
pub struct OverlayItem {
    pub bbox: [i32; 4],
    pub text: String,
    pub source_text: String,
    pub bg: [u8; 3],
    pub fg: [u8; 3],
    pub patch_rect: Option<[i32; 4]>,
    pub patch_rgb: Option<Vec<u8>>,
    pub patch_size: Option<(u32, u32)>,
    pub ink_rect: Option<[i32; 4]>,
    pub stroke_thickness: f32,
    pub source_lines: usize,
    pub line_ink: f32,
    pub outline: Option<[u8; 3]>,
    pub align: String,
    pub room: Option<[i32; 4]>,
}

static FONT_ENGINE: Lazy<Mutex<(FontSystem, SwashCache)>> =
    Lazy::new(|| Mutex::new((FontSystem::new(), SwashCache::new())));

fn comparable(text: &str) -> String {
    text.to_lowercase()
        .chars()
        .filter(|c| c.is_alphanumeric())
        .collect()
}

fn needs_repaint(item: &OverlayItem) -> bool {
    if item.source_text.is_empty() {
        return true;
    }
    if !item.source_text.chars().any(|c| c.is_alphabetic()) {
        return false;
    }
    comparable(&item.text) != comparable(&item.source_text)
}

fn blend_pixel(buf: &mut [u8], w: usize, h: usize, x: i32, y: i32, r: u8, g: u8, b: u8, a: u8) {
    if x < 0 || y < 0 || x >= w as i32 || y >= h as i32 || a == 0 {
        return;
    }
    let idx = (y as usize * w + x as usize) * 4;
    let alpha = a as f32 / 255.0;
    let inv = 1.0 - alpha;
    let dst_a = buf[idx + 3] as f32 / 255.0;
    let out_a = alpha + dst_a * inv;
    if out_a <= 0.0 {
        return;
    }
    buf[idx] = ((r as f32 * alpha + buf[idx] as f32 * dst_a * inv) / out_a)
        .round()
        .clamp(0.0, 255.0) as u8;
    buf[idx + 1] = ((g as f32 * alpha + buf[idx + 1] as f32 * dst_a * inv) / out_a)
        .round()
        .clamp(0.0, 255.0) as u8;
    buf[idx + 2] = ((b as f32 * alpha + buf[idx + 2] as f32 * dst_a * inv) / out_a)
        .round()
        .clamp(0.0, 255.0) as u8;
    buf[idx + 3] = (out_a * 255.0).round().clamp(0.0, 255.0) as u8;
}

fn draw_items_onto_rgba(
    rgba: &mut [u8],
    canvas_w: u32,
    canvas_h: u32,
    src_w: u32,
    src_h: u32,
    items: &[OverlayItem],
) {
    let cw = canvas_w as usize;
    let ch = canvas_h as usize;
    let sx = canvas_w as f32 / src_w.max(1) as f32;
    let sy = canvas_h as f32 / src_h.max(1) as f32;

    let mut engine = FONT_ENGINE.lock();
    let (ref mut font_system, ref mut swash_cache) = *engine;

    for item in items {
        if !needs_repaint(item) || item.text.trim().is_empty() {
            continue;
        }
        let patch_rect = item.patch_rect.unwrap_or(item.bbox);
        let pl = (patch_rect[0] as f32 * sx).floor().max(0.0) as i32;
        let pt = (patch_rect[1] as f32 * sy).floor().max(0.0) as i32;
        let pr = (patch_rect[2] as f32 * sx).ceil().min(canvas_w as f32) as i32;
        let pb = (patch_rect[3] as f32 * sy).ceil().min(canvas_h as f32) as i32;
        if pr <= pl || pb <= pt {
            continue;
        }

        // 1. Paint reconstructed background patch (or solid fallback bg)
        if let (Some(ref rgb), Some((pw, ph))) = (&item.patch_rgb, item.patch_size) {
            let pw = pw.max(1);
            let ph = ph.max(1);
            let dst_w = (pr - pl) as usize;
            let dst_h = (pb - pt) as usize;
            for dy in 0..dst_h {
                let src_y = ((dy * ph as usize) / dst_h.max(1)).min(ph as usize - 1);
                for dx in 0..dst_w {
                    let src_x = ((dx * pw as usize) / dst_w.max(1)).min(pw as usize - 1);
                    let sidx = (src_y * pw as usize + src_x) * 3;
                    let didx = ((pt as usize + dy) * cw + (pl as usize + dx)) * 4;
                    rgba[didx] = rgb[sidx];
                    rgba[didx + 1] = rgb[sidx + 1];
                    rgba[didx + 2] = rgb[sidx + 2];
                    rgba[didx + 3] = 255;
                }
            }
        } else {
            for y in pt..pb {
                for x in pl..pr {
                    let didx = (y as usize * cw + x as usize) * 4;
                    rgba[didx] = item.bg[0];
                    rgba[didx + 1] = item.bg[1];
                    rgba[didx + 2] = item.bg[2];
                    rgba[didx + 3] = 255;
                }
            }
        }

        // 2. Determine text box (allow expanding into free room when translation is longer)
        let ink = item.ink_rect.unwrap_or(item.bbox);
        let il = (ink[0] as f32 * sx).round() as i32;
        let it = (ink[1] as f32 * sy).round() as i32;
        let ir = (ink[2] as f32 * sx).round() as i32;
        let ib = (ink[3] as f32 * sy).round() as i32;
        let room = item.room.unwrap_or(patch_rect);
        let rl = (room[0] as f32 * sx).round() as i32;
        let rt = (room[1] as f32 * sy).round() as i32;
        let rr = (room[2] as f32 * sx).round() as i32;
        let rb = (room[3] as f32 * sy).round() as i32;

        let max_w = ((rr - rl).max(ir - il).max(24)) as f32;
        let max_h = ((rb - rt).max(ib - it).max(14)) as f32;

        let base_line_h = if item.line_ink > 2.0 {
            item.line_ink * sy
        } else {
            ((ib - it) as f32) / item.source_lines.max(1) as f32
        };
        let mut font_size = (base_line_h * 1.18).clamp(11.0, 64.0);
        let is_bold = item.stroke_thickness > 0.0 && (item.stroke_thickness * sy) >= font_size * 0.14;
        let align = if item.align == "left" {
            Align::Left
        } else {
            Align::Center
        };

        // Shrink font slightly until wrapped text fits comfortably inside available room
        let mut buffer = Buffer::new(font_system, Metrics::new(font_size, font_size * 1.25));
        for _ in 0..10 {
            buffer.set_metrics(font_system, Metrics::new(font_size, font_size * 1.22));
            buffer.set_wrap(font_system, Wrap::WordOrGlyph);
            buffer.set_size(font_system, Some(max_w), None);
            let attrs = Attrs::new()
                .family(Family::SansSerif)
                .weight(if is_bold { Weight::BOLD } else { Weight::NORMAL });
            buffer.set_text(font_system, item.text.trim(), attrs, Shaping::Advanced);
            for line in buffer.lines.iter_mut() {
                line.set_align(Some(align));
            }
            buffer.shape_until_scroll(font_system, false);

            let layout_lines = buffer.layout_runs().count().max(1);
            let total_h = layout_lines as f32 * font_size * 1.22;
            if total_h <= max_h * 1.15 || font_size <= 11.0 {
                break;
            }
            font_size = (font_size * 0.88).max(11.0);
        }

        let layout_lines = buffer.layout_runs().count().max(1);
        let text_h = layout_lines as f32 * font_size * 1.22;
        let center_x = (il + ir) as f32 / 2.0;
        let center_y = (it + ib) as f32 / 2.0;
        let origin_x = (center_x - max_w / 2.0)
            .clamp(rl as f32, (rr as f32 - max_w).max(rl as f32))
            .round() as i32;
        let origin_y = (center_y - text_h / 2.0)
            .clamp(rt as f32, (rb as f32 - text_h).max(rt as f32))
            .round() as i32;

        // 3. Draw optional outline first (circular ring offsets)
        if let Some(out_rgb) = item.outline {
            let radius = (font_size * 0.09).clamp(1.2, 3.0);
            let steps = 12usize;
            for s in 0..steps {
                let ang = std::f32::consts::TAU * (s as f32 / steps as f32);
                let ox = (radius * ang.cos()).round() as i32;
                let oy = (radius * ang.sin()).round() as i32;
                buffer.draw(
                    font_system,
                    swash_cache,
                    Color::rgb(out_rgb[0], out_rgb[1], out_rgb[2]),
                    |gx, gy, _w, _h, col| {
                        blend_pixel(
                            rgba,
                            cw,
                            ch,
                            origin_x + gx + ox,
                            origin_y + gy + oy,
                            col.r(),
                            col.g(),
                            col.b(),
                            col.a(),
                        );
                    },
                );
            }
        }

        // 4. Draw foreground text
        buffer.draw(
            font_system,
            swash_cache,
            Color::rgb(item.fg[0], item.fg[1], item.fg[2]),
            |gx, gy, _w, _h, col| {
                blend_pixel(
                    rgba,
                    cw,
                    ch,
                    origin_x + gx,
                    origin_y + gy,
                    col.r(),
                    col.g(),
                    col.b(),
                    col.a(),
                );
            },
        );
    }
}

/// Render translated text items directly onto a copy of an RGB image (used for Clipboard Image Replace).
pub fn render_translated_image(base: &RgbImage, items: &[OverlayItem]) -> RgbImage {
    let w = base.width();
    let h = base.height();
    let mut rgba = vec![0u8; (w * h * 4) as usize];
    for (i, px) in base.pixels().enumerate() {
        rgba[i * 4] = px[0];
        rgba[i * 4 + 1] = px[1];
        rgba[i * 4 + 2] = px[2];
        rgba[i * 4 + 3] = 255;
    }
    draw_items_onto_rgba(&mut rgba, w, h, w, h, items);

    let mut rgb = vec![0u8; (w * h * 3) as usize];
    for i in 0..(w * h) as usize {
        rgb[i * 3] = rgba[i * 4];
        rgb[i * 3 + 1] = rgba[i * 4 + 1];
        rgb[i * 3 + 2] = rgba[i * 4 + 2];
    }
    RgbImage::from_raw(w, h, rgb).unwrap_or_else(|| base.clone())
}

// ---------------------------------------------------------------------------
// Exclude Tauri / Win32 windows from screen capture (WDA_EXCLUDEFROMCAPTURE)
// ---------------------------------------------------------------------------

#[cfg(windows)]
pub fn exclude_hwnd_from_capture(hwnd_raw: isize) -> bool {
    use windows::Win32::Foundation::HWND;
    use windows::Win32::UI::WindowsAndMessaging::{SetWindowDisplayAffinity, WINDOW_DISPLAY_AFFINITY};
    const WDA_EXCLUDEFROMCAPTURE: u32 = 0x0000_0011;
    unsafe {
        SetWindowDisplayAffinity(
            HWND(hwnd_raw as *mut std::ffi::c_void),
            WINDOW_DISPLAY_AFFINITY(WDA_EXCLUDEFROMCAPTURE),
        )
        .is_ok()
    }
}

#[cfg(not(windows))]
pub fn exclude_hwnd_from_capture(_hwnd_raw: isize) -> bool {
    false
}

// ---------------------------------------------------------------------------
// Native Win32 Transparent Click-to-Dismiss Translation Overlay Manager
// ---------------------------------------------------------------------------

enum OverlayCmd {
    Show {
        key: String,
        bbox: [i32; 4],
        src_size: (u32, u32),
        items: Vec<OverlayItem>,
    },
    Close(String),
    ClearAll,
    SetEscSuspended(bool),
    #[cfg(all(test, windows))]
    ListHwnds(mpsc::Sender<Vec<isize>>),
}

pub struct OverlayManager {
    tx: Mutex<Option<mpsc::Sender<OverlayCmd>>>,
    active_count: std::sync::Arc<std::sync::atomic::AtomicUsize>,
    #[cfg(windows)]
    thread_id: std::sync::atomic::AtomicU32,
}

impl OverlayManager {
    pub fn new() -> Self {
        let (tx, rx) = mpsc::channel::<OverlayCmd>();
        let active_count = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let active_clone = active_count.clone();
        #[cfg(windows)]
        let tid = std::sync::Arc::new(std::sync::atomic::AtomicU32::new(0));
        #[cfg(windows)]
        let tid_clone = tid.clone();

        thread::Builder::new()
            .name("win32-overlays".into())
            .spawn(move || {
                #[cfg(windows)]
                run_overlay_window_thread(rx, tid_clone, active_clone);
                #[cfg(not(windows))]
                {
                    let _ = (rx, active_clone);
                }
            })
            .expect("Failed to spawn overlay manager thread");

        #[cfg(windows)]
        {
            for _ in 0..50 {
                if tid.load(std::sync::atomic::Ordering::Acquire) != 0 {
                    break;
                }
                thread::sleep(std::time::Duration::from_millis(5));
            }
            Self {
                tx: Mutex::new(Some(tx)),
                active_count,
                thread_id: std::sync::atomic::AtomicU32::new(
                    tid.load(std::sync::atomic::Ordering::Acquire),
                ),
            }
        }
        #[cfg(not(windows))]
        {
            Self {
                tx: Mutex::new(Some(tx)),
                active_count,
            }
        }
    }

    pub fn active_count(&self) -> usize {
        self.active_count.load(std::sync::atomic::Ordering::Acquire)
    }

    pub fn show(&self, key: &str, bbox: [i32; 4], src_size: (u32, u32), items: Vec<OverlayItem>) {
        if let Some(ref tx) = *self.tx.lock() {
            let _ = tx.send(OverlayCmd::Show {
                key: key.to_string(),
                bbox,
                src_size,
                items,
            });
            self.wake();
        }
    }

    pub fn close(&self, key: &str) {
        if let Some(ref tx) = *self.tx.lock() {
            let _ = tx.send(OverlayCmd::Close(key.to_string()));
            self.wake();
        }
    }

    pub fn clear_all(&self) {
        if let Some(ref tx) = *self.tx.lock() {
            let _ = tx.send(OverlayCmd::ClearAll);
            self.wake();
        }
    }

    /// Temporarily suspend global Esc dismissal (e.g. while interactive region selector is open).
    pub fn set_esc_suspended(&self, suspended: bool) {
        if let Some(ref tx) = *self.tx.lock() {
            let _ = tx.send(OverlayCmd::SetEscSuspended(suspended));
            self.wake();
        }
    }

    #[cfg(all(test, windows))]
    fn list_hwnds(&self) -> Vec<isize> {
        let (reply_tx, reply_rx) = mpsc::channel();
        if let Some(ref tx) = *self.tx.lock() {
            let _ = tx.send(OverlayCmd::ListHwnds(reply_tx));
            self.wake();
        }
        reply_rx
            .recv_timeout(std::time::Duration::from_secs(2))
            .unwrap_or_default()
    }

    fn wake(&self) {
        #[cfg(windows)]
        {
            use windows::Win32::Foundation::{LPARAM, WPARAM};
            use windows::Win32::UI::WindowsAndMessaging::{PostThreadMessageW, WM_APP};
            let tid = self.thread_id.load(std::sync::atomic::Ordering::Acquire);
            if tid != 0 {
                unsafe {
                    let _ = PostThreadMessageW(tid, WM_APP + 2, WPARAM(0), LPARAM(0));
                }
            }
        }
    }
}

#[cfg(windows)]
fn update_layered_rgba(
    hwnd: windows::Win32::Foundation::HWND,
    x: i32,
    y: i32,
    w: i32,
    h: i32,
    rgba: &[u8],
) {
    use std::ffi::c_void;
    use windows::Win32::Foundation::{POINT, SIZE};
    use windows::Win32::Graphics::Gdi::{
        CreateCompatibleDC, CreateDIBSection, DeleteDC, DeleteObject, GetDC, ReleaseDC,
        SelectObject, AC_SRC_ALPHA, AC_SRC_OVER, BITMAPINFO, BITMAPINFOHEADER, BI_RGB,
        BLENDFUNCTION, DIB_RGB_COLORS,
    };
    use windows::Win32::UI::WindowsAndMessaging::{UpdateLayeredWindow, ULW_ALPHA};

    if w <= 0 || h <= 0 {
        return;
    }

    unsafe {
        let screen_dc = GetDC(None);
        let mem_dc = CreateCompatibleDC(screen_dc);
        let bmi = BITMAPINFO {
            bmiHeader: BITMAPINFOHEADER {
                biSize: std::mem::size_of::<BITMAPINFOHEADER>() as u32,
                biWidth: w,
                biHeight: -h,
                biPlanes: 1,
                biBitCount: 32,
                biCompression: BI_RGB.0,
                ..Default::default()
            },
            bmiColors: [Default::default()],
        };
        let mut bits: *mut c_void = std::ptr::null_mut();
        if let Ok(hbmp) = CreateDIBSection(mem_dc, &bmi, DIB_RGB_COLORS, &mut bits, None, 0) {
            if !bits.is_null() {
                let dst = std::slice::from_raw_parts_mut(bits as *mut u8, (w * h * 4) as usize);
                // Convert straight RGBA -> premultiplied BGRA for UpdateLayeredWindow
                for i in 0..(w * h) as usize {
                    let s = i * 4;
                    let a = rgba[s + 3] as u16;
                    dst[s] = ((rgba[s + 2] as u16 * a) / 255) as u8;     // B
                    dst[s + 1] = ((rgba[s + 1] as u16 * a) / 255) as u8; // G
                    dst[s + 2] = ((rgba[s] as u16 * a) / 255) as u8;     // R
                    dst[s + 3] = a as u8;
                }
                let old = SelectObject(mem_dc, hbmp);
                let pt_dst = POINT { x, y };
                let size = SIZE { cx: w, cy: h };
                let pt_src = POINT { x: 0, y: 0 };
                let blend = BLENDFUNCTION {
                    BlendOp: AC_SRC_OVER as u8,
                    BlendFlags: 0,
                    SourceConstantAlpha: 255,
                    AlphaFormat: AC_SRC_ALPHA as u8,
                };
                let _ = UpdateLayeredWindow(
                    hwnd,
                    screen_dc,
                    Some(&pt_dst),
                    Some(&size),
                    mem_dc,
                    Some(&pt_src),
                    windows::Win32::Foundation::COLORREF(0),
                    Some(&blend),
                    ULW_ALPHA,
                );
                SelectObject(mem_dc, old);
            }
            let _ = DeleteObject(hbmp);
        }
        let _ = DeleteDC(mem_dc);
        ReleaseDC(None, screen_dc);
    }
}

#[cfg(windows)]
fn run_overlay_window_thread(
    rx: mpsc::Receiver<OverlayCmd>,
    tid_out: std::sync::Arc<std::sync::atomic::AtomicU32>,
    active_count: std::sync::Arc<std::sync::atomic::AtomicUsize>,
) {
    use windows::core::w;
    use windows::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
    use windows::Win32::System::LibraryLoader::GetModuleHandleW;
    use windows::Win32::System::Threading::GetCurrentThreadId;
    use windows::Win32::UI::HiDpi::{
        SetThreadDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE,
    };
    use windows::Win32::UI::Input::KeyboardAndMouse::{
        GetAsyncKeyState, RegisterHotKey, UnregisterHotKey, MOD_NOREPEAT,
    };
    use windows::Win32::UI::WindowsAndMessaging::{
        CreateWindowExW, DefWindowProcW, DestroyWindow, DispatchMessageW, GetMessageW, KillTimer,
        LoadCursorW, PeekMessageW, PostThreadMessageW, RegisterClassW, SetCursor, SetTimer,
        ShowWindow, IDC_HAND, MA_NOACTIVATE, MSG, PM_NOREMOVE, SW_SHOWNOACTIVATE, WM_APP,
        WM_HOTKEY, WM_KEYDOWN, WM_LBUTTONDOWN, WM_MOUSEACTIVATE, WM_RBUTTONDOWN, WM_SETCURSOR,
        WM_TIMER, WNDCLASSW, WS_EX_LAYERED, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST,
        WS_POPUP,
    };

    const WM_OVERLAY_CMD: u32 = WM_APP + 2;
    const WM_OVERLAY_DISMISS_ONE: u32 = WM_APP + 3;
    const WM_OVERLAY_DISMISS_ALL: u32 = WM_APP + 4;
    const OVERLAY_ESC_HOTKEY_ID: i32 = 0x544B;
    const OVERLAY_ESC_TIMER_ID: usize = 0x544C;
    const VK_ESCAPE: u32 = 0x1B;

    unsafe extern "system" fn wnd_proc(
        hwnd: HWND,
        msg: u32,
        wparam: WPARAM,
        lparam: LPARAM,
    ) -> LRESULT {
        match msg {
            WM_MOUSEACTIVATE => {
                // Clicks dismiss without stealing focus from the app underneath.
                return LRESULT(MA_NOACTIVATE as isize);
            }
            WM_SETCURSOR => {
                if let Ok(hand) = LoadCursorW(None, IDC_HAND) {
                    SetCursor(hand);
                    return LRESULT(1);
                }
            }
            WM_LBUTTONDOWN => {
                let _ = PostThreadMessageW(
                    GetCurrentThreadId(),
                    WM_OVERLAY_DISMISS_ONE,
                    WPARAM(hwnd.0 as usize),
                    LPARAM(0),
                );
                return LRESULT(0);
            }
            WM_RBUTTONDOWN => {
                let _ = PostThreadMessageW(
                    GetCurrentThreadId(),
                    WM_OVERLAY_DISMISS_ALL,
                    WPARAM(0),
                    LPARAM(0),
                );
                return LRESULT(0);
            }
            WM_KEYDOWN => {
                if wparam.0 == VK_ESCAPE as usize {
                    let _ = PostThreadMessageW(
                        GetCurrentThreadId(),
                        WM_OVERLAY_DISMISS_ALL,
                        WPARAM(0),
                        LPARAM(0),
                    );
                    return LRESULT(0);
                }
            }
            _ => {}
        }
        DefWindowProcW(hwnd, msg, wparam, lparam)
    }

    unsafe {
        let _ = SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE);
        let hinst = GetModuleHandleW(None).unwrap_or_default();
        let class_name = w!("TranslatorBoxOverlayClass");
        let wc = WNDCLASSW {
            lpfnWndProc: Some(wnd_proc),
            hInstance: hinst.into(),
            hCursor: LoadCursorW(None, IDC_HAND).unwrap_or_default(),
            lpszClassName: class_name,
            ..Default::default()
        };
        RegisterClassW(&wc);

        let mut dummy = MSG::default();
        let _ = PeekMessageW(&mut dummy, None, 0, 0, PM_NOREMOVE);
        tid_out.store(GetCurrentThreadId(), std::sync::atomic::Ordering::Release);

        let mut windows_map: HashMap<String, HWND> = HashMap::new();
        let mut esc_suspended = false;
        let mut esc_hotkey_active = false;
        let mut esc_timer_id: usize = 0;
        let mut esc_was_down = false;

        let sync_state = |map: &HashMap<String, HWND>,
                          suspended: bool,
                          hk_active: &mut bool,
                          timer_id: &mut usize,
                          was_down: &mut bool| {
            active_count.store(map.len(), std::sync::atomic::Ordering::Release);
            let want_esc = !map.is_empty() && !suspended;
            if want_esc {
                if !*hk_active && *timer_id == 0 {
                    if RegisterHotKey(None, OVERLAY_ESC_HOTKEY_ID, MOD_NOREPEAT, VK_ESCAPE).is_ok()
                    {
                        *hk_active = true;
                    } else {
                        *was_down = (GetAsyncKeyState(VK_ESCAPE as i32) as u16 & 0x8000) != 0;
                        *timer_id = SetTimer(None, OVERLAY_ESC_TIMER_ID, 50, None);
                    }
                }
            } else {
                if *hk_active {
                    let _ = UnregisterHotKey(None, OVERLAY_ESC_HOTKEY_ID);
                    *hk_active = false;
                }
                if *timer_id != 0 {
                    let _ = KillTimer(None, *timer_id);
                    *timer_id = 0;
                }
                *was_down = false;
            }
        };

        let mut msg = MSG::default();

        while GetMessageW(&mut msg, None, 0, 0).as_bool() {
            match msg.message {
                WM_OVERLAY_CMD => {
                    while let Ok(cmd) = rx.try_recv() {
                        match cmd {
                            OverlayCmd::Show {
                                key,
                                bbox,
                                src_size,
                                items,
                            } => {
                                let [l, t, r, b] = bbox;
                                let w = (r - l).max(1);
                                let h = (b - t).max(1);
                                let mut rgba = vec![0u8; (w as usize) * (h as usize) * 4];
                                draw_items_onto_rgba(
                                    &mut rgba,
                                    w as u32,
                                    h as u32,
                                    src_size.0,
                                    src_size.1,
                                    &items,
                                );
                                let has_visible = rgba.chunks_exact(4).any(|px| px[3] > 0);
                                if !has_visible {
                                    if let Some(old_hwnd) = windows_map.remove(&key) {
                                        let _ = DestroyWindow(old_hwnd);
                                    }
                                    continue;
                                }

                                // Notice: WS_EX_LAYERED without WS_EX_TRANSPARENT gives per-pixel
                                // alpha hit-testing via UpdateLayeredWindow(ULW_ALPHA):
                                // alpha == 0 pixels pass clicks straight through to apps underneath,
                                // while painted text patches (alpha > 0) receive clicks to dismiss!
                                let hwnd = *windows_map.entry(key).or_insert_with(|| {
                                    let h_win = CreateWindowExW(
                                        WS_EX_LAYERED
                                            | WS_EX_TOPMOST
                                            | WS_EX_TOOLWINDOW
                                            | WS_EX_NOACTIVATE,
                                        class_name,
                                        w!("Translator2k Overlay"),
                                        WS_POPUP,
                                        l,
                                        t,
                                        w,
                                        h,
                                        None,
                                        None,
                                        hinst,
                                        None,
                                    )
                                    .unwrap_or_default();
                                    if !h_win.0.is_null() {
                                        exclude_hwnd_from_capture(h_win.0 as isize);
                                        let _ = ShowWindow(h_win, SW_SHOWNOACTIVATE);
                                    }
                                    h_win
                                });
                                if !hwnd.0.is_null() {
                                    update_layered_rgba(hwnd, l, t, w, h, &rgba);
                                }
                            }
                            OverlayCmd::Close(key) => {
                                if let Some(hwnd) = windows_map.remove(&key) {
                                    let _ = DestroyWindow(hwnd);
                                }
                            }
                            OverlayCmd::ClearAll => {
                                for (_, hwnd) in windows_map.drain() {
                                    let _ = DestroyWindow(hwnd);
                                }
                            }
                            OverlayCmd::SetEscSuspended(suspended) => {
                                esc_suspended = suspended;
                            }
                            #[cfg(all(test, windows))]
                            OverlayCmd::ListHwnds(reply) => {
                                let list: Vec<isize> =
                                    windows_map.values().map(|h| h.0 as isize).collect();
                                let _ = reply.send(list);
                            }
                        }
                    }
                    sync_state(
                        &windows_map,
                        esc_suspended,
                        &mut esc_hotkey_active,
                        &mut esc_timer_id,
                        &mut esc_was_down,
                    );
                }
                WM_OVERLAY_DISMISS_ONE => {
                    let target_ptr = msg.wParam.0 as *mut std::ffi::c_void;
                    let found_key = windows_map
                        .iter()
                        .find_map(|(k, h)| if h.0 == target_ptr { Some(k.clone()) } else { None });
                    if let Some(key) = found_key {
                        if let Some(hwnd) = windows_map.remove(&key) {
                            let _ = DestroyWindow(hwnd);
                        }
                    }
                    sync_state(
                        &windows_map,
                        esc_suspended,
                        &mut esc_hotkey_active,
                        &mut esc_timer_id,
                        &mut esc_was_down,
                    );
                }
                WM_OVERLAY_DISMISS_ALL => {
                    for (_, hwnd) in windows_map.drain() {
                        let _ = DestroyWindow(hwnd);
                    }
                    sync_state(
                        &windows_map,
                        esc_suspended,
                        &mut esc_hotkey_active,
                        &mut esc_timer_id,
                        &mut esc_was_down,
                    );
                }
                WM_HOTKEY if msg.wParam.0 as i32 == OVERLAY_ESC_HOTKEY_ID => {
                    for (_, hwnd) in windows_map.drain() {
                        let _ = DestroyWindow(hwnd);
                    }
                    sync_state(
                        &windows_map,
                        esc_suspended,
                        &mut esc_hotkey_active,
                        &mut esc_timer_id,
                        &mut esc_was_down,
                    );
                }
                WM_TIMER if esc_timer_id != 0 && msg.wParam.0 == esc_timer_id => {
                    let is_down = (GetAsyncKeyState(VK_ESCAPE as i32) as u16 & 0x8000) != 0;
                    if is_down && !esc_was_down {
                        for (_, hwnd) in windows_map.drain() {
                            let _ = DestroyWindow(hwnd);
                        }
                        sync_state(
                            &windows_map,
                            esc_suspended,
                            &mut esc_hotkey_active,
                            &mut esc_timer_id,
                            &mut esc_was_down,
                        );
                    } else {
                        esc_was_down = is_down;
                    }
                }
                _ => {
                    DispatchMessageW(&msg);
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Native Win32 Fullscreen Interactive Region Selector
// ---------------------------------------------------------------------------

#[cfg(windows)]
pub fn select_screen_region() -> Result<Option<[i32; 4]>, String> {
    use windows::core::w;
    use windows::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
    use windows::Win32::System::LibraryLoader::GetModuleHandleW;
    use windows::Win32::UI::HiDpi::{
        SetThreadDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE,
    };
    use windows::Win32::UI::Input::KeyboardAndMouse::{ReleaseCapture, SetCapture};
    use windows::Win32::UI::WindowsAndMessaging::{
        CreateWindowExW, DefWindowProcW, DestroyWindow, DispatchMessageW, GetMessageW,
        GetSystemMetrics, GetWindowLongPtrW, LoadCursorW, PostQuitMessage, RegisterClassW,
        SetForegroundWindow, SetWindowLongPtrW, ShowWindow, TranslateMessage, GWLP_USERDATA,
        IDC_CROSS, MSG, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN, SM_XVIRTUALSCREEN,
        SM_YVIRTUALSCREEN, SW_SHOW, WM_KEYDOWN, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE,
        WM_RBUTTONDOWN, WNDCLASSW, WS_EX_LAYERED, WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_POPUP,
    };

    struct SelectorState {
        vx: i32,
        vy: i32,
        vw: i32,
        vh: i32,
        dragging: bool,
        start: (i32, i32),
        current: (i32, i32),
        result: Option<[i32; 4]>,
    }

    fn repaint_selector(hwnd: HWND, st: &SelectorState) {
        let w = st.vw as usize;
        let h = st.vh as usize;
        // Fast dim overlay: RGBA(9, 9, 11, 130)
        let mut rgba = vec![0u8; w * h * 4];
        for px in rgba.chunks_exact_mut(4) {
            px[0] = 9;
            px[1] = 9;
            px[2] = 11;
            px[3] = 130;
        }

        if st.dragging {
            let l = st.start.0.min(st.current.0).clamp(0, st.vw - 1) as usize;
            let t = st.start.1.min(st.current.1).clamp(0, st.vh - 1) as usize;
            let r = st.start.0.max(st.current.0).clamp(0, st.vw - 1) as usize;
            let b = st.start.1.max(st.current.1).clamp(0, st.vh - 1) as usize;

            // Cut out clear hole inside selection (alpha = 1 so mouse stays active)
            for y in t..=b {
                for x in l..=r {
                    let idx = (y * w + x) * 4;
                    rgba[idx] = 59;
                    rgba[idx + 1] = 130;
                    rgba[idx + 2] = 246;
                    rgba[idx + 3] = 18;
                }
            }
            // Crisp 2px blue border (#3b82f6)
            for thickness in 0..2 {
                let top_y = t.saturating_add(thickness).min(h - 1);
                let bot_y = b.saturating_sub(thickness).min(h - 1);
                for x in l..=r {
                    for yy in [top_y, bot_y] {
                        let idx = (yy * w + x) * 4;
                        rgba[idx] = 59;
                        rgba[idx + 1] = 130;
                        rgba[idx + 2] = 246;
                        rgba[idx + 3] = 255;
                    }
                }
                let left_x = l.saturating_add(thickness).min(w - 1);
                let right_x = r.saturating_sub(thickness).min(w - 1);
                for y in t..=b {
                    for xx in [left_x, right_x] {
                        let idx = (y * w + xx) * 4;
                        rgba[idx] = 59;
                        rgba[idx + 1] = 130;
                        rgba[idx + 2] = 246;
                        rgba[idx + 3] = 255;
                    }
                }
            }
        } else {
            // Draw crosshair at cursor
            let cx = st.current.0.clamp(0, st.vw - 1) as usize;
            let cy = st.current.1.clamp(0, st.vh - 1) as usize;
            for x in 0..w {
                let idx = (cy * w + x) * 4;
                rgba[idx] = 250;
                rgba[idx + 1] = 250;
                rgba[idx + 2] = 250;
                rgba[idx + 3] = 110;
            }
            for y in 0..h {
                let idx = (y * w + cx) * 4;
                rgba[idx] = 250;
                rgba[idx + 1] = 250;
                rgba[idx + 2] = 250;
                rgba[idx + 3] = 110;
            }
        }

        update_layered_rgba(hwnd, st.vx, st.vy, st.vw, st.vh, &rgba);
    }

    unsafe extern "system" fn selector_proc(
        hwnd: HWND,
        msg: u32,
        wparam: WPARAM,
        lparam: LPARAM,
    ) -> LRESULT {
        let ptr = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *mut SelectorState;
        if ptr.is_null() {
            return DefWindowProcW(hwnd, msg, wparam, lparam);
        }
        let st = &mut *ptr;
        let x = (lparam.0 & 0xFFFF) as i16 as i32;
        let y = ((lparam.0 >> 16) & 0xFFFF) as i16 as i32;

        match msg {
            WM_KEYDOWN => {
                if wparam.0 == 0x1B {
                    // ESC cancels
                    st.result = None;
                    let _ = DestroyWindow(hwnd);
                    PostQuitMessage(0);
                    return LRESULT(0);
                }
            }
            WM_RBUTTONDOWN => {
                st.result = None;
                let _ = DestroyWindow(hwnd);
                PostQuitMessage(0);
                return LRESULT(0);
            }
            WM_LBUTTONDOWN => {
                st.dragging = true;
                st.start = (x, y);
                st.current = (x, y);
                SetCapture(hwnd);
                repaint_selector(hwnd, st);
                return LRESULT(0);
            }
            WM_MOUSEMOVE => {
                st.current = (x, y);
                repaint_selector(hwnd, st);
                return LRESULT(0);
            }
            WM_LBUTTONUP => {
                if st.dragging {
                    st.dragging = false;
                    let _ = ReleaseCapture();
                    let l = st.vx + st.start.0.min(x);
                    let t = st.vy + st.start.1.min(y);
                    let r = st.vx + st.start.0.max(x);
                    let b = st.vy + st.start.1.max(y);
                    if r - l >= 8 && b - t >= 8 {
                        st.result = Some([l, t, r, b]);
                    }
                    let _ = DestroyWindow(hwnd);
                    PostQuitMessage(0);
                }
                return LRESULT(0);
            }
            _ => {}
        }
        DefWindowProcW(hwnd, msg, wparam, lparam)
    }

    let (tx, rx) = mpsc::channel();
    thread::Builder::new()
        .name("region-selector".into())
        .spawn(move || unsafe {
            let _ = SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE);
            let vx = GetSystemMetrics(SM_XVIRTUALSCREEN);
            let vy = GetSystemMetrics(SM_YVIRTUALSCREEN);
            let vw = GetSystemMetrics(SM_CXVIRTUALSCREEN).max(1);
            let vh = GetSystemMetrics(SM_CYVIRTUALSCREEN).max(1);

            let hinst = GetModuleHandleW(None).unwrap_or_default();
            let class_name = w!("TranslatorBoxRegionSelector");
            let wc = WNDCLASSW {
                lpfnWndProc: Some(selector_proc),
                hInstance: hinst.into(),
                hCursor: LoadCursorW(None, IDC_CROSS).unwrap_or_default(),
                lpszClassName: class_name,
                ..Default::default()
            };
            RegisterClassW(&wc);

            let mut state = Box::new(SelectorState {
                vx,
                vy,
                vw,
                vh,
                dragging: false,
                start: (vw / 2, vh / 2),
                current: (vw / 2, vh / 2),
                result: None,
            });

            let hwnd = match CreateWindowExW(
                WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
                class_name,
                w!("Chọn vùng cần dịch"),
                WS_POPUP,
                vx,
                vy,
                vw,
                vh,
                None,
                None,
                hinst,
                None,
            ) {
                Ok(h) => h,
                Err(e) => {
                    let _ = tx.send(Err(format!("Không mở được lớp chọn vùng: {e}")));
                    return;
                }
            };

            SetWindowLongPtrW(hwnd, GWLP_USERDATA, (&mut *state as *mut SelectorState) as isize);
            exclude_hwnd_from_capture(hwnd.0 as isize);
            let _ = ShowWindow(hwnd, SW_SHOW);
            let _ = SetForegroundWindow(hwnd);
            repaint_selector(hwnd, &state);

            let mut msg = MSG::default();
            while GetMessageW(&mut msg, None, 0, 0).as_bool() {
                let _ = TranslateMessage(&msg);
                DispatchMessageW(&msg);
            }

            let _ = tx.send(Ok(state.result));
        })
        .map_err(|e| format!("Không tạo được luồng chọn vùng: {e}"))?;

    rx.recv()
        .map_err(|_| "Chọn vùng bị huỷ bất ngờ.".to_string())?
}

#[cfg(not(windows))]
pub fn select_screen_region() -> Result<Option<[i32; 4]>, String> {
    Err("Chọn vùng màn hình chỉ hỗ trợ Windows.".to_string())
}

// ---------------------------------------------------------------------------
// Native Win32 Interactive Live Region Editor (move + 8-way resize)
// ---------------------------------------------------------------------------

#[cfg(windows)]
pub fn edit_screen_region(initial: [i32; 4], mode: &str) -> Result<Option<[i32; 4]>, String> {
    use windows::core::w;
    use windows::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
    use windows::Win32::System::LibraryLoader::GetModuleHandleW;
    use windows::Win32::UI::HiDpi::{
        SetThreadDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE,
    };
    use windows::Win32::UI::Input::KeyboardAndMouse::{ReleaseCapture, SetCapture};
    use windows::Win32::UI::WindowsAndMessaging::{
        CreateWindowExW, DefWindowProcW, DestroyWindow, DispatchMessageW, GetMessageW,
        GetSystemMetrics, GetWindowLongPtrW, LoadCursorW, PostQuitMessage, RegisterClassW,
        SetForegroundWindow, SetWindowLongPtrW, ShowWindow, TranslateMessage, GWLP_USERDATA,
        IDC_SIZEALL, MSG, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN, SM_XVIRTUALSCREEN,
        SM_YVIRTUALSCREEN, SW_SHOW, WM_KEYDOWN, WM_LBUTTONDBLCLK, WM_LBUTTONDOWN, WM_LBUTTONUP,
        WM_MOUSEMOVE, WM_RBUTTONDOWN, WNDCLASSW, WS_EX_LAYERED, WS_EX_TOOLWINDOW, WS_EX_TOPMOST,
        WS_POPUP,
    };

    const EDGE: i32 = 12;
    const MIN_W: i32 = 24;
    const MIN_H: i32 = 16;

    struct EditorState {
        vx: i32,
        vy: i32,
        vw: i32,
        vh: i32,
        rect: [i32; 4], // local to virtual screen
        color: [u8; 3],
        drag_kind: Option<u8>, // 0=move, bitflags: 1=L, 2=T, 4=R, 8=B
        drag_start: (i32, i32),
        orig_rect: [i32; 4],
        result: Option<[i32; 4]>,
    }

    fn hit_test(r: [i32; 4], x: i32, y: i32) -> Option<u8> {
        if x < r[0] - EDGE || x > r[2] + EDGE || y < r[1] - EDGE || y > r[3] + EDGE {
            return None;
        }
        let mut flags = 0u8;
        if (x - r[0]).abs() <= EDGE {
            flags |= 1;
        } else if (x - r[2]).abs() <= EDGE {
            flags |= 4;
        }
        if (y - r[1]).abs() <= EDGE {
            flags |= 2;
        } else if (y - r[3]).abs() <= EDGE {
            flags |= 8;
        }
        Some(flags)
    }

    fn repaint_editor(hwnd: HWND, st: &EditorState) {
        let w = st.vw as usize;
        let h = st.vh as usize;
        let mut rgba = vec![0u8; w * h * 4];
        for px in rgba.chunks_exact_mut(4) {
            px[0] = 9;
            px[1] = 9;
            px[2] = 11;
            px[3] = 75;
        }
        let l = st.rect[0].clamp(0, st.vw - 1) as usize;
        let t = st.rect[1].clamp(0, st.vh - 1) as usize;
        let r = st.rect[2].clamp(l as i32 + 1, st.vw - 1) as usize;
        let b = st.rect[3].clamp(t as i32 + 1, st.vh - 1) as usize;
        let [cr, cg, cb] = st.color;

        for y in t..=b {
            for x in l..=r {
                let idx = (y * w + x) * 4;
                rgba[idx] = cr;
                rgba[idx + 1] = cg;
                rgba[idx + 2] = cb;
                rgba[idx + 3] = 28;
            }
        }
        // Dashed 2px border
        for thickness in 0..2 {
            let ty = t.saturating_add(thickness).min(h - 1);
            let by = b.saturating_sub(thickness).min(h - 1);
            for x in l..=r {
                if ((x - l) / 6) % 2 == 0 {
                    for yy in [ty, by] {
                        let idx = (yy * w + x) * 4;
                        rgba[idx] = cr;
                        rgba[idx + 1] = cg;
                        rgba[idx + 2] = cb;
                        rgba[idx + 3] = 255;
                    }
                }
            }
            let lx = l.saturating_add(thickness).min(w - 1);
            let rx = r.saturating_sub(thickness).min(w - 1);
            for y in t..=b {
                if ((y - t) / 6) % 2 == 0 {
                    for xx in [lx, rx] {
                        let idx = (y * w + xx) * 4;
                        rgba[idx] = cr;
                        rgba[idx + 1] = cg;
                        rgba[idx + 2] = cb;
                        rgba[idx + 3] = 255;
                    }
                }
            }
        }
        // Corner handles (8x8 white-filled colored squares)
        for &(hx, hy) in &[(l, t), (r, t), (l, b), (r, b)] {
            let x0 = hx.saturating_sub(4);
            let y0 = hy.saturating_sub(4);
            let x1 = (hx + 4).min(w - 1);
            let y1 = (hy + 4).min(h - 1);
            for y in y0..=y1 {
                for x in x0..=x1 {
                    let is_edge = x == x0 || x == x1 || y == y0 || y == y1;
                    let idx = (y * w + x) * 4;
                    rgba[idx] = if is_edge { cr } else { 255 };
                    rgba[idx + 1] = if is_edge { cg } else { 255 };
                    rgba[idx + 2] = if is_edge { cb } else { 255 };
                    rgba[idx + 3] = 255;
                }
            }
        }
        update_layered_rgba(hwnd, st.vx, st.vy, st.vw, st.vh, &rgba);
    }

    unsafe extern "system" fn editor_proc(
        hwnd: HWND,
        msg: u32,
        wparam: WPARAM,
        lparam: LPARAM,
    ) -> LRESULT {
        let ptr = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *mut EditorState;
        if ptr.is_null() {
            return DefWindowProcW(hwnd, msg, wparam, lparam);
        }
        let st = &mut *ptr;
        let x = (lparam.0 & 0xFFFF) as i16 as i32;
        let y = ((lparam.0 >> 16) & 0xFFFF) as i16 as i32;

        match msg {
            WM_KEYDOWN => {
                if wparam.0 == 0x1B {
                    st.result = None;
                    let _ = DestroyWindow(hwnd);
                    PostQuitMessage(0);
                    return LRESULT(0);
                }
                if wparam.0 == 0x0D || wparam.0 == 0x20 {
                    st.result = Some([
                        st.vx + st.rect[0],
                        st.vy + st.rect[1],
                        st.vx + st.rect[2],
                        st.vy + st.rect[3],
                    ]);
                    let _ = DestroyWindow(hwnd);
                    PostQuitMessage(0);
                    return LRESULT(0);
                }
            }
            WM_LBUTTONDBLCLK => {
                st.result = Some([
                    st.vx + st.rect[0],
                    st.vy + st.rect[1],
                    st.vx + st.rect[2],
                    st.vy + st.rect[3],
                ]);
                let _ = DestroyWindow(hwnd);
                PostQuitMessage(0);
                return LRESULT(0);
            }
            WM_RBUTTONDOWN => {
                st.result = Some([
                    st.vx + st.rect[0],
                    st.vy + st.rect[1],
                    st.vx + st.rect[2],
                    st.vy + st.rect[3],
                ]);
                let _ = DestroyWindow(hwnd);
                PostQuitMessage(0);
                return LRESULT(0);
            }
            WM_LBUTTONDOWN => {
                if let Some(kind) = hit_test(st.rect, x, y) {
                    st.drag_kind = Some(kind);
                    st.drag_start = (x, y);
                    st.orig_rect = st.rect;
                    SetCapture(hwnd);
                } else {
                    // Clicking outside confirms current box
                    st.result = Some([
                        st.vx + st.rect[0],
                        st.vy + st.rect[1],
                        st.vx + st.rect[2],
                        st.vy + st.rect[3],
                    ]);
                    let _ = DestroyWindow(hwnd);
                    PostQuitMessage(0);
                }
                return LRESULT(0);
            }
            WM_MOUSEMOVE => {
                if let Some(kind) = st.drag_kind {
                    let dx = x - st.drag_start.0;
                    let dy = y - st.drag_start.1;
                    let [mut l, mut t, mut r, mut b] = st.orig_rect;
                    if kind == 0 {
                        let rw = r - l;
                        let rh = b - t;
                        l = (l + dx).clamp(0, (st.vw - rw).max(0));
                        t = (t + dy).clamp(0, (st.vh - rh).max(0));
                        r = l + rw;
                        b = t + rh;
                    } else {
                        if (kind & 1) != 0 {
                            l = (l + dx).clamp(0, r - MIN_W);
                        }
                        if (kind & 4) != 0 {
                            r = (r + dx).clamp(l + MIN_W, st.vw - 1);
                        }
                        if (kind & 2) != 0 {
                            t = (t + dy).clamp(0, b - MIN_H);
                        }
                        if (kind & 8) != 0 {
                            b = (b + dy).clamp(t + MIN_H, st.vh - 1);
                        }
                    }
                    st.rect = [l, t, r, b];
                    repaint_editor(hwnd, st);
                }
                return LRESULT(0);
            }
            WM_LBUTTONUP => {
                if st.drag_kind.is_some() {
                    st.drag_kind = None;
                    let _ = ReleaseCapture();
                }
                return LRESULT(0);
            }
            _ => {}
        }
        DefWindowProcW(hwnd, msg, wparam, lparam)
    }

    let color = if mode == "frame" {
        [34, 197, 94]
    } else {
        [59, 130, 246]
    };
    let (tx, rx) = mpsc::channel();
    thread::Builder::new()
        .name("region-editor".into())
        .spawn(move || unsafe {
            let _ = SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE);
            let vx = GetSystemMetrics(SM_XVIRTUALSCREEN);
            let vy = GetSystemMetrics(SM_YVIRTUALSCREEN);
            let vw = GetSystemMetrics(SM_CXVIRTUALSCREEN).max(1);
            let vh = GetSystemMetrics(SM_CYVIRTUALSCREEN).max(1);

            let hinst = GetModuleHandleW(None).unwrap_or_default();
            let class_name = w!("TranslatorBoxRegionEditor");
            let wc = WNDCLASSW {
                style: windows::Win32::UI::WindowsAndMessaging::CS_DBLCLKS,
                lpfnWndProc: Some(editor_proc),
                hInstance: hinst.into(),
                hCursor: LoadCursorW(None, IDC_SIZEALL).unwrap_or_default(),
                lpszClassName: class_name,
                ..Default::default()
            };
            RegisterClassW(&wc);

            let local_rect = [
                (initial[0] - vx).clamp(0, vw - MIN_W),
                (initial[1] - vy).clamp(0, vh - MIN_H),
                (initial[2] - vx).clamp(MIN_W, vw - 1),
                (initial[3] - vy).clamp(MIN_H, vh - 1),
            ];
            let mut state = Box::new(EditorState {
                vx,
                vy,
                vw,
                vh,
                rect: local_rect,
                color,
                drag_kind: None,
                drag_start: (0, 0),
                orig_rect: local_rect,
                result: None,
            });

            let hwnd = match CreateWindowExW(
                WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
                class_name,
                w!("Chỉnh sửa vùng Live (Enter / nháy đúp / click ngoài để lưu, Esc huỷ)"),
                WS_POPUP,
                vx,
                vy,
                vw,
                vh,
                None,
                None,
                hinst,
                None,
            ) {
                Ok(h) => h,
                Err(e) => {
                    let _ = tx.send(Err(format!("Không mở được trình sửa vùng: {e}")));
                    return;
                }
            };

            SetWindowLongPtrW(hwnd, GWLP_USERDATA, (&mut *state as *mut EditorState) as isize);
            exclude_hwnd_from_capture(hwnd.0 as isize);
            let _ = ShowWindow(hwnd, SW_SHOW);
            let _ = SetForegroundWindow(hwnd);
            repaint_editor(hwnd, &state);

            let mut msg = MSG::default();
            while GetMessageW(&mut msg, None, 0, 0).as_bool() {
                let _ = TranslateMessage(&msg);
                DispatchMessageW(&msg);
            }
            let _ = tx.send(Ok(state.result));
        })
        .map_err(|e| format!("Không tạo được luồng sửa vùng: {e}"))?;

    rx.recv()
        .map_err(|_| "Sửa vùng bị huỷ bất ngờ.".to_string())?
}

#[cfg(not(windows))]
pub fn edit_screen_region(_initial: [i32; 4], _mode: &str) -> Result<Option<[i32; 4]>, String> {
    Err("Chỉnh vùng màn hình chỉ hỗ trợ Windows.".to_string())
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;
    use std::time::{Duration, Instant};
    use windows::Win32::Foundation::{HWND, LPARAM, WPARAM};
    use windows::Win32::UI::WindowsAndMessaging::{
        GetWindowLongW, IsWindow, PostMessageW, GWL_EXSTYLE, WM_KEYDOWN, WM_LBUTTONDOWN,
        WM_RBUTTONDOWN, WS_EX_TRANSPARENT,
    };

    fn sample_item(text: &str) -> OverlayItem {
        OverlayItem {
            bbox: [4, 4, 180, 40],
            text: text.to_string(),
            source_text: "Hello".to_string(),
            bg: [20, 20, 24],
            fg: [255, 255, 255],
            patch_rect: Some([4, 4, 180, 40]),
            patch_rgb: None,
            patch_size: None,
            ink_rect: Some([8, 8, 176, 36]),
            stroke_thickness: 1.0,
            source_lines: 1,
            line_ink: 18.0,
            outline: None,
            align: "left".to_string(),
            room: Some([4, 4, 180, 40]),
        }
    }

    fn wait_until(cond: impl Fn() -> bool) -> bool {
        let start = Instant::now();
        while start.elapsed() < Duration::from_secs(2) {
            if cond() {
                return true;
            }
            thread::sleep(Duration::from_millis(15));
        }
        cond()
    }

    #[test]
    fn overlay_dismisses_on_click_and_clear_without_blocking() {
        let mgr = OverlayManager::new();
        mgr.show("once-1", [100, 100, 320, 180], (220, 80), vec![sample_item("Xin chào")]);
        mgr.show("once-2", [360, 100, 580, 180], (220, 80), vec![sample_item("Thế giới")]);
        assert!(wait_until(|| mgr.active_count() == 2));

        let hwnds = mgr.list_hwnds();
        assert_eq!(hwnds.len(), 2);
        let hwnd1 = HWND(hwnds[0] as *mut std::ffi::c_void);
        let ex_style = unsafe { GetWindowLongW(hwnd1, GWL_EXSTYLE) as u32 };
        assert_eq!(ex_style & WS_EX_TRANSPARENT.0, 0);

        // Left-clicking one overlay dismisses ONLY that overlay and destroys its HWND
        unsafe {
            let _ = PostMessageW(hwnd1, WM_LBUTTONDOWN, WPARAM(1), LPARAM(0x0014_0014));
        }
        assert!(wait_until(|| mgr.active_count() == 1));
        assert!(wait_until(|| unsafe { !IsWindow(hwnd1).as_bool() }));

        // Remaining overlay dismisses on right-click (dismiss all) and destroys its HWND
        let rem = mgr.list_hwnds();
        assert_eq!(rem.len(), 1);
        let hwnd2 = HWND(rem[0] as *mut std::ffi::c_void);
        unsafe {
            let _ = PostMessageW(hwnd2, WM_RBUTTONDOWN, WPARAM(2), LPARAM(0x0014_0014));
        }
        assert!(wait_until(|| mgr.active_count() == 0));
        assert!(wait_until(|| unsafe { !IsWindow(hwnd2).as_bool() }));
    }

    #[test]
    fn fullscreen_and_multi_overlays_dismiss_on_esc_and_clear() {
        let mgr = OverlayManager::new();
        mgr.show("full", [0, 0, 1280, 720], (1280, 720), vec![sample_item("Toàn màn hình")]);
        mgr.show("live-1", [40, 40, 260, 120], (220, 80), vec![sample_item("Vùng live 1")]);
        mgr.show("live-2", [300, 40, 520, 120], (220, 80), vec![sample_item("Vùng live 2")]);
        assert!(wait_until(|| mgr.active_count() == 3));

        let hwnds = mgr.list_hwnds();
        assert_eq!(hwnds.len(), 3);
        let first = HWND(hwnds[0] as *mut std::ffi::c_void);
        // Pressing Escape on any overlay dismisses ALL overlays
        unsafe {
            let _ = PostMessageW(first, WM_KEYDOWN, WPARAM(0x1B), LPARAM(0));
        }
        assert!(wait_until(|| mgr.active_count() == 0));
        for raw in hwnds {
            let h = HWND(raw as *mut std::ffi::c_void);
            assert!(wait_until(|| unsafe { !IsWindow(h).as_bool() }));
        }
    }
}
