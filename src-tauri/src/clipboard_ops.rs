use std::sync::atomic::{AtomicBool, AtomicU32, AtomicUsize, Ordering};
use std::time::{Duration, Instant};

use parking_lot::Mutex;

/// Default maximum chars for auto-translate on Ctrl+C (avoid translating whole source files).
pub const DEFAULT_AUTO_CLIPBOARD_MAX_CHARS: usize = 5000;

#[cfg(windows)]
pub fn is_clipboard_sensitive() -> bool {
    use windows::core::w;
    use windows::Win32::System::DataExchange::{
        IsClipboardFormatAvailable, RegisterClipboardFormatW,
    };

    unsafe {
        let fmt = RegisterClipboardFormatW(w!("ExcludeClipboardContentFromMonitorProcessing"));
        fmt != 0 && IsClipboardFormatAvailable(fmt).is_ok()
    }
}

#[cfg(not(windows))]
pub fn is_clipboard_sensitive() -> bool {
    false
}

#[cfg(windows)]
pub fn clipboard_sequence_number() -> u32 {
    use windows::Win32::System::DataExchange::GetClipboardSequenceNumber;
    unsafe { GetClipboardSequenceNumber() }
}

#[cfg(not(windows))]
pub fn clipboard_sequence_number() -> u32 {
    0
}

#[cfg(windows)]
pub fn read_clipboard_text() -> Option<String> {
    use windows::Win32::Foundation::HGLOBAL;
    use windows::Win32::System::DataExchange::{
        CloseClipboard, GetClipboardData, IsClipboardFormatAvailable, OpenClipboard,
    };
    use windows::Win32::System::Memory::{GlobalLock, GlobalUnlock};

    const CF_UNICODETEXT: u32 = 13;

    unsafe {
        if IsClipboardFormatAvailable(CF_UNICODETEXT).is_err() {
            return None;
        }
        if OpenClipboard(None).is_err() {
            return None;
        }
        let result = (|| -> Option<String> {
            let handle = GetClipboardData(CF_UNICODETEXT).ok()?;
            let hglobal = HGLOBAL(handle.0);
            let ptr = GlobalLock(hglobal) as *const u16;
            if ptr.is_null() {
                return None;
            }
            let mut len = 0usize;
            while *ptr.add(len) != 0 {
                len += 1;
                if len > 2_000_000 {
                    break;
                }
            }
            let slice = std::slice::from_raw_parts(ptr, len);
            let text = String::from_utf16_lossy(slice);
            let _ = GlobalUnlock(hglobal);
            Some(text)
        })();
        let _ = CloseClipboard();
        result
    }
}

#[cfg(not(windows))]
pub fn read_clipboard_text() -> Option<String> {
    None
}

#[cfg(windows)]
pub fn write_clipboard_text(text: &str) -> Result<(), String> {
    use windows::Win32::Foundation::HANDLE;
    use windows::Win32::System::DataExchange::{
        CloseClipboard, EmptyClipboard, OpenClipboard, SetClipboardData,
    };
    use windows::Win32::System::Memory::{GlobalAlloc, GlobalLock, GlobalUnlock, GMEM_MOVEABLE};

    const CF_UNICODETEXT: u32 = 13;

    let mut utf16: Vec<u16> = text.encode_utf16().collect();
    utf16.push(0);
    let byte_len = utf16.len() * 2;

    unsafe {
        for attempt in 0..5 {
            if OpenClipboard(None).is_ok() {
                let res = (|| -> Result<(), String> {
                    EmptyClipboard().map_err(|e| format!("EmptyClipboard lỗi: {e}"))?;
                    let hmem = GlobalAlloc(GMEM_MOVEABLE, byte_len)
                        .map_err(|e| format!("GlobalAlloc lỗi: {e}"))?;
                    let ptr = GlobalLock(hmem) as *mut u16;
                    if ptr.is_null() {
                        return Err("GlobalLock thất bại.".to_string());
                    }
                    std::ptr::copy_nonoverlapping(utf16.as_ptr(), ptr, utf16.len());
                    let _ = GlobalUnlock(hmem);
                    SetClipboardData(CF_UNICODETEXT, HANDLE(hmem.0))
                        .map_err(|e| format!("SetClipboardData lỗi: {e}"))?;
                    Ok(())
                })();
                let _ = CloseClipboard();
                return res;
            }
            if attempt < 4 {
                std::thread::sleep(Duration::from_millis(15));
            }
        }
        Err("Không mở được clipboard để ghi dữ liệu.".to_string())
    }
}

#[cfg(not(windows))]
pub fn write_clipboard_text(_text: &str) -> Result<(), String> {
    Err("Clipboard chỉ hỗ trợ Windows.".to_string())
}

#[cfg(windows)]
fn wait_modifiers_released(timeout: Duration) {
    use windows::Win32::UI::Input::KeyboardAndMouse::{
        GetAsyncKeyState, VK_CONTROL, VK_LCONTROL, VK_LMENU, VK_LSHIFT, VK_MENU, VK_RCONTROL,
        VK_RMENU, VK_RSHIFT, VK_SHIFT,
    };

    let keys = [
        VK_CONTROL.0 as i32,
        VK_LCONTROL.0 as i32,
        VK_RCONTROL.0 as i32,
        VK_MENU.0 as i32,
        VK_LMENU.0 as i32,
        VK_RMENU.0 as i32,
        VK_SHIFT.0 as i32,
        VK_LSHIFT.0 as i32,
        VK_RSHIFT.0 as i32,
    ];
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        let held = unsafe { keys.iter().any(|&vk| (GetAsyncKeyState(vk) as u16 & 0x8000) != 0) };
        if !held {
            return;
        }
        std::thread::sleep(Duration::from_millis(25));
    }
}

#[cfg(windows)]
fn send_ctrl_key(vk_char: u16) {
    use windows::Win32::UI::Input::KeyboardAndMouse::{
        SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP, VIRTUAL_KEY,
        VK_CONTROL,
    };

    let make = |vk: VIRTUAL_KEY, up: bool| INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: vk,
                wScan: 0,
                dwFlags: if up { KEYEVENTF_KEYUP } else { Default::default() },
                time: 0,
                dwExtraInfo: 0,
            },
        },
    };

    let inputs = [
        make(VK_CONTROL, false),
        make(VIRTUAL_KEY(vk_char), false),
        make(VIRTUAL_KEY(vk_char), true),
        make(VK_CONTROL, true),
    ];
    unsafe {
        SendInput(&inputs, std::mem::size_of::<INPUT>() as i32);
    }
}

/// Simulate Ctrl+C to capture currently selected text from the focused window.
#[cfg(windows)]
pub fn copy_selected_text(preserve_whitespace: bool) -> Result<(String, Option<String>), String> {
    wait_modifiers_released(Duration::from_secs(1));
    let previous = read_clipboard_text();
    let seq_before = clipboard_sequence_number();
    let _ = write_clipboard_text("");
    std::thread::sleep(Duration::from_millis(30));
    send_ctrl_key(0x43); // 'C'

    let deadline = Instant::now() + Duration::from_millis(600);
    while Instant::now() < deadline {
        if clipboard_sequence_number() != seq_before {
            if let Some(txt) = read_clipboard_text() {
                if !txt.trim().is_empty() {
                    let captured = if preserve_whitespace {
                        txt
                    } else {
                        txt.trim().to_string()
                    };
                    return Ok((captured, previous));
                }
            }
        }
        std::thread::sleep(Duration::from_millis(12));
    }
    if let Some(ref prev) = previous {
        let _ = write_clipboard_text(prev);
    }
    Err("Chưa thấy văn bản được chọn.".to_string())
}

#[cfg(not(windows))]
pub fn copy_selected_text(_preserve_whitespace: bool) -> Result<(String, Option<String>), String> {
    Err("Chức năng chỉ hỗ trợ Windows.".to_string())
}

/// Paste translated text into the currently focused window via Ctrl+V and optionally restore previous clipboard.
#[cfg(windows)]
pub fn paste_replacement(
    text: &str,
    restore: Option<&str>,
    paste_delay_ms: u64,
) -> Result<(), String> {
    write_clipboard_text(text)?;
    wait_modifiers_released(Duration::from_secs(1));
    std::thread::sleep(Duration::from_millis(paste_delay_ms.clamp(20, 500)));
    send_ctrl_key(0x56); // 'V'
    std::thread::sleep(Duration::from_millis(160));
    if let Some(old) = restore {
        let _ = write_clipboard_text(old);
    }
    Ok(())
}

#[cfg(not(windows))]
pub fn paste_replacement(
    _text: &str,
    _restore: Option<&str>,
    _paste_delay_ms: u64,
) -> Result<(), String> {
    Err("Chức năng chỉ hỗ trợ Windows.".to_string())
}

/// Manages suppression & monitoring for auto-translate on Ctrl+C.
pub struct ClipboardWatcher {
    enabled: AtomicBool,
    max_chars: AtomicUsize,
    suppress_until_seq: AtomicU32,
    last_seen_text: Mutex<String>,
}

impl ClipboardWatcher {
    pub fn new(enabled: bool, max_chars: usize) -> Self {
        Self {
            enabled: AtomicBool::new(enabled),
            max_chars: AtomicUsize::new(max_chars.clamp(200, 20_000)),
            suppress_until_seq: AtomicU32::new(clipboard_sequence_number()),
            last_seen_text: Mutex::new(read_clipboard_text().unwrap_or_default()),
        }
    }

    pub fn set_enabled(&self, enabled: bool) {
        self.enabled.store(enabled, Ordering::Relaxed);
        if enabled {
            self.suppress_until_seq
                .store(clipboard_sequence_number(), Ordering::Relaxed);
            *self.last_seen_text.lock() = read_clipboard_text().unwrap_or_default();
        }
    }

    pub fn set_max_chars(&self, max_chars: usize) {
        self.max_chars
            .store(max_chars.clamp(200, 20_000), Ordering::Relaxed);
    }

    pub fn is_enabled(&self) -> bool {
        self.enabled.load(Ordering::Relaxed)
    }

    /// Suppress the next clipboard write (e.g. when the app itself copies a translation).
    pub fn mark_internal_write(&self, text: &str) {
        self.suppress_until_seq
            .store(clipboard_sequence_number(), Ordering::Relaxed);
        *self.last_seen_text.lock() = text.to_string();
    }

    pub fn poll_new_text(&self) -> Option<String> {
        if !self.is_enabled() {
            return None;
        }
        let seq = clipboard_sequence_number();
        let prev = self.suppress_until_seq.load(Ordering::Relaxed);
        if seq == prev {
            return None;
        }
        self.suppress_until_seq.store(seq, Ordering::Relaxed);
        if is_clipboard_sensitive() {
            return None;
        }
        let text = read_clipboard_text()?;
        let trimmed = text.trim();
        let limit = self.max_chars.load(Ordering::Relaxed);
        if trimmed.is_empty() || trimmed.chars().count() > limit {
            return None;
        }
        let mut last = self.last_seen_text.lock();
        if *last == trimmed {
            return None;
        }
        *last = trimmed.to_string();
        Some(trimmed.to_string())
    }
}
