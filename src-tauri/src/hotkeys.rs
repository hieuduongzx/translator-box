use std::collections::{BTreeMap, HashMap, HashSet};
use std::sync::mpsc;
use std::thread;

use parking_lot::Mutex;

#[derive(Debug)]
enum HotkeyCmd {
    Apply(BTreeMap<String, String>, mpsc::Sender<Result<(), String>>),
    Clear,
}

pub struct HotkeyManager {
    tx: Mutex<Option<mpsc::Sender<HotkeyCmd>>>,
    #[cfg(windows)]
    thread_id: std::sync::atomic::AtomicU32,
}

impl HotkeyManager {
    pub fn new<F>(on_action: F) -> Self
    where
        F: Fn(String) + Send + Sync + 'static,
    {
        let (tx, rx) = mpsc::channel::<HotkeyCmd>();
        #[cfg(windows)]
        let tid = std::sync::Arc::new(std::sync::atomic::AtomicU32::new(0));
        #[cfg(windows)]
        let tid_clone = tid.clone();

        thread::Builder::new()
            .name("global-hotkeys".into())
            .spawn(move || {
                #[cfg(windows)]
                run_win32_hotkey_loop(rx, on_action, tid_clone);
                #[cfg(not(windows))]
                {
                    let _ = (rx, on_action);
                }
            })
            .expect("Failed to spawn global hotkey thread");

        // Wait briefly for thread_id to populate
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
                thread_id: std::sync::atomic::AtomicU32::new(
                    tid.load(std::sync::atomic::Ordering::Acquire),
                ),
            }
        }
        #[cfg(not(windows))]
        {
            Self {
                tx: Mutex::new(Some(tx)),
            }
        }
    }

    pub fn apply(&self, mapping: &BTreeMap<String, String>) -> Result<(), String> {
        // Validate duplicates before messaging thread
        let mut seen = HashSet::new();
        for combo in mapping.values() {
            let norm = combo.trim().to_lowercase();
            if !norm.is_empty() && !seen.insert(norm.clone()) {
                return Err(format!("Phím tắt bị trùng: {norm}"));
            }
        }
        let guard = self.tx.lock();
        let Some(ref tx) = *guard else {
            return Err("Dịch vụ phím tắt chưa khởi tạo.".to_string());
        };
        let (reply_tx, reply_rx) = mpsc::channel();
        tx.send(HotkeyCmd::Apply(mapping.clone(), reply_tx))
            .map_err(|_| "Không gửi được cấu hình phím tắt.".to_string())?;
        self.wake_loop();
        reply_rx
            .recv_timeout(std::time::Duration::from_secs(2))
            .map_err(|_| "Quá thời gian chờ đăng ký phím tắt.".to_string())?
    }

    pub fn clear(&self) {
        if let Some(ref tx) = *self.tx.lock() {
            let _ = tx.send(HotkeyCmd::Clear);
            self.wake_loop();
        }
    }

    fn wake_loop(&self) {
        #[cfg(windows)]
        {
            use windows::Win32::Foundation::{LPARAM, WPARAM};
            use windows::Win32::UI::WindowsAndMessaging::{PostThreadMessageW, WM_APP};
            let tid = self.thread_id.load(std::sync::atomic::Ordering::Acquire);
            if tid != 0 {
                unsafe {
                    let _ = PostThreadMessageW(tid, WM_APP + 1, WPARAM(0), LPARAM(0));
                }
            }
        }
    }
}

#[cfg(windows)]
fn parse_hotkey_combo(combo: &str) -> Result<(u32, u32), String> {
    use windows::Win32::UI::Input::KeyboardAndMouse::{
        MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, MOD_WIN,
    };

    let mut mods = MOD_NOREPEAT.0;
    let mut vk: Option<u32> = None;

    for raw_part in combo.split('+') {
        let part = raw_part.trim().to_lowercase();
        if part.is_empty() {
            continue;
        }
        match part.as_str() {
            "ctrl" | "control" => mods |= MOD_CONTROL.0,
            "alt" => mods |= MOD_ALT.0,
            "shift" => mods |= MOD_SHIFT.0,
            "win" | "meta" | "super" => mods |= MOD_WIN.0,
            k => {
                let code = key_name_to_vk(k)
                    .ok_or_else(|| format!("Phím không hợp lệ trong tổ hợp '{combo}': '{k}'"))?;
                vk = Some(code);
            }
        }
    }

    let vk = vk.ok_or_else(|| format!("Tổ hợp phím '{combo}' thiếu phím chính."))?;
    Ok((mods, vk))
}

#[cfg(windows)]
fn key_name_to_vk(name: &str) -> Option<u32> {
    if name.len() == 1 {
        let ch = name.chars().next()?;
        if ch.is_ascii_alphabetic() {
            return Some(ch.to_ascii_uppercase() as u32);
        }
        if ch.is_ascii_digit() {
            return Some(ch as u32);
        }
    }
    if let Some(num) = name.strip_prefix('f') {
        if let Ok(n) = num.parse::<u32>() {
            if (1..=24).contains(&n) {
                return Some(0x70 + n - 1);
            }
        }
    }
    match name {
        "space" => Some(0x20),
        "enter" | "return" => Some(0x0D),
        "tab" => Some(0x09),
        "esc" | "escape" => Some(0x1B),
        "backspace" => Some(0x08),
        "delete" | "del" => Some(0x2E),
        "insert" | "ins" => Some(0x2D),
        "home" => Some(0x24),
        "end" => Some(0x23),
        "pageup" | "pgup" => Some(0x21),
        "pagedown" | "pgdn" => Some(0x22),
        "up" => Some(0x26),
        "down" => Some(0x28),
        "left" => Some(0x25),
        "right" => Some(0x27),
        "-" | "minus" => Some(0xBD),
        "=" | "equal" => Some(0xBB),
        "[" => Some(0xDB),
        "]" => Some(0xDD),
        ";" => Some(0xBA),
        "'" => Some(0xDE),
        "," => Some(0xBC),
        "." => Some(0xBE),
        "/" => Some(0xBF),
        "`" => Some(0xC0),
        _ => None,
    }
}

#[cfg(windows)]
fn run_win32_hotkey_loop<F>(
    rx: mpsc::Receiver<HotkeyCmd>,
    on_action: F,
    tid_out: std::sync::Arc<std::sync::atomic::AtomicU32>,
) where
    F: Fn(String) + Send + Sync + 'static,
{
    use windows::Win32::System::Threading::GetCurrentThreadId;
    use windows::Win32::UI::Input::KeyboardAndMouse::{
        RegisterHotKey, UnregisterHotKey, HOT_KEY_MODIFIERS,
    };
    use windows::Win32::UI::WindowsAndMessaging::{
        GetMessageW, PeekMessageW, MSG, PM_NOREMOVE, WM_APP, WM_HOTKEY,
    };

    unsafe {
        // Force creation of Win32 message queue before publishing thread ID
        let mut dummy = MSG::default();
        let _ = PeekMessageW(&mut dummy, None, 0, 0, PM_NOREMOVE);
        tid_out.store(GetCurrentThreadId(), std::sync::atomic::Ordering::Release);

        let mut registered: HashMap<i32, String> = HashMap::new();
        let mut msg = MSG::default();

        while GetMessageW(&mut msg, None, 0, 0).as_bool() {
            if msg.message == WM_HOTKEY {
                let id = msg.wParam.0 as i32;
                if let Some(action) = registered.get(&id) {
                    on_action(action.clone());
                }
            } else if msg.message == WM_APP + 1 {
                while let Ok(cmd) = rx.try_recv() {
                    match cmd {
                        HotkeyCmd::Clear => {
                            for &id in registered.keys() {
                                let _ = UnregisterHotKey(None, id);
                            }
                            registered.clear();
                        }
                        HotkeyCmd::Apply(mapping, reply) => {
                            let mut parsed: Vec<(String, u32, u32, String)> = Vec::new();
                            let mut err_list = Vec::new();
                            for (action, combo) in mapping {
                                let norm = combo.trim().to_lowercase();
                                if norm.is_empty() {
                                    continue;
                                }
                                match parse_hotkey_combo(&norm) {
                                    Ok((mods, vk)) => parsed.push((action, mods, vk, norm)),
                                    Err(e) => err_list.push(e),
                                }
                            }
                            if !err_list.is_empty() {
                                let _ = reply.send(Err(err_list.join(" · ")));
                                continue;
                            }
                            // Unregister old, register new
                            for &id in registered.keys() {
                                let _ = UnregisterHotKey(None, id);
                            }
                            registered.clear();
                            let mut next_id = 1i32;
                            let mut reg_warnings = Vec::new();
                            for (action, mods, vk, combo) in parsed {
                                if RegisterHotKey(None, next_id, HOT_KEY_MODIFIERS(mods), vk)
                                    .is_ok()
                                {
                                    registered.insert(next_id, action);
                                    next_id += 1;
                                } else {
                                    reg_warnings.push(format!("{combo} (đang bị ứng dụng khác chiếm)"));
                                }
                            }
                            if reg_warnings.is_empty() {
                                let _ = reply.send(Ok(()));
                            } else {
                                let _ = reply.send(Err(format!(
                                    "Một số phím tắt không đăng ký được: {}",
                                    reg_warnings.join(", ")
                                )));
                            }
                        }
                    }
                }
            }
        }
    }
}
