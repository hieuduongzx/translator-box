use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DesktopApplication {
    pub application_id: String,
    pub name: String,
    pub title: String,
    pub label: String,
}

fn friendly_label(name: &str, title: &str) -> String {
    let key = name.to_lowercase();
    if matches!(key.as_str(), "applicationframehost" | "python" | "pythonw") && !title.is_empty() {
        return title.to_string();
    }
    match key.as_str() {
        "explorer" => "File Explorer".to_string(),
        "msedge" => "Microsoft Edge".to_string(),
        "steamwebhelper" => "Steam".to_string(),
        "systemsettings" => "Cài đặt Windows".to_string(),
        "textinputhost" => "Windows Text Input".to_string(),
        _ => name.to_string(),
    }
}

#[cfg(windows)]
fn process_image(pid: u32) -> Option<String> {
    use windows::core::PWSTR;
    use windows::Win32::Foundation::CloseHandle;
    use windows::Win32::System::Threading::{
        OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_WIN32,
        PROCESS_QUERY_LIMITED_INFORMATION,
    };

    unsafe {
        let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid).ok()?;
        let mut buf = vec![0u16; 1024];
        let mut len = buf.len() as u32;
        let ok = QueryFullProcessImageNameW(
            handle,
            PROCESS_NAME_WIN32,
            PWSTR(buf.as_mut_ptr()),
            &mut len,
        )
        .is_ok();
        let _ = CloseHandle(handle);
        if ok && len > 0 {
            Some(String::from_utf16_lossy(&buf[..len as usize]))
        } else {
            None
        }
    }
}

#[cfg(windows)]
fn app_identity(pid: u32) -> (String, String) {
    if let Some(image) = process_image(pid) {
        let stem = std::path::Path::new(&image)
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("App")
            .to_string();
        (image.to_lowercase(), stem)
    } else {
        (format!("pid:{pid}"), format!("PID {pid}"))
    }
}

#[cfg(windows)]
pub fn foreground_application_id() -> String {
    use windows::Win32::UI::WindowsAndMessaging::{GetForegroundWindow, GetWindowThreadProcessId};
    unsafe {
        let hwnd = GetForegroundWindow();
        if hwnd.0.is_null() {
            return String::new();
        }
        let mut pid = 0u32;
        GetWindowThreadProcessId(hwnd, Some(&mut pid));
        if pid == 0 {
            return String::new();
        }
        app_identity(pid).0
    }
}

#[cfg(not(windows))]
pub fn foreground_application_id() -> String {
    String::new()
}

#[cfg(windows)]
pub fn list_desktop_applications() -> Vec<DesktopApplication> {
    use std::collections::HashMap;
    use windows::Win32::Foundation::{BOOL, HWND, LPARAM};
    use windows::Win32::UI::WindowsAndMessaging::{
        EnumWindows, GetWindow, GetWindowLongW, GetWindowTextLengthW, GetWindowTextW,
        GetWindowThreadProcessId, IsWindowVisible, GWL_EXSTYLE, GW_OWNER, WS_EX_TOOLWINDOW,
    };

    struct CollectCtx {
        current_pid: u32,
        apps: HashMap<String, DesktopApplication>,
    }

    unsafe extern "system" fn enum_proc(hwnd: HWND, lparam: LPARAM) -> BOOL {
        let ctx = &mut *(lparam.0 as *mut CollectCtx);
        if !IsWindowVisible(hwnd).as_bool() {
            return BOOL(1);
        }
        if let Ok(owner) = GetWindow(hwnd, GW_OWNER) {
            if !owner.0.is_null() {
                return BOOL(1);
            }
        }
        let ex_style = GetWindowLongW(hwnd, GWL_EXSTYLE) as u32;
        if (ex_style & WS_EX_TOOLWINDOW.0) != 0 {
            return BOOL(1);
        }
        let title_len = GetWindowTextLengthW(hwnd);
        if title_len <= 0 {
            return BOOL(1);
        }
        let mut pid = 0u32;
        GetWindowThreadProcessId(hwnd, Some(&mut pid));
        if pid == 0 || pid == ctx.current_pid {
            return BOOL(1);
        }
        let mut buf = vec![0u16; (title_len + 1) as usize];
        let written = GetWindowTextW(hwnd, &mut buf);
        let raw_title = String::from_utf16_lossy(&buf[..written as usize]);
        let title: String = raw_title
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" ")
            .chars()
            .take(80)
            .collect();
        if title.is_empty() {
            return BOOL(1);
        }
        let (app_id, name) = app_identity(pid);
        ctx.apps.entry(app_id.clone()).or_insert_with(|| {
            let label = friendly_label(&name, &title);
            DesktopApplication {
                application_id: app_id,
                name,
                title,
                label,
            }
        });
        BOOL(1)
    }

    let mut ctx = CollectCtx {
        current_pid: std::process::id(),
        apps: HashMap::new(),
    };
    unsafe {
        let _ = EnumWindows(Some(enum_proc), LPARAM(&mut ctx as *mut CollectCtx as isize));
    }
    let mut list: Vec<DesktopApplication> = ctx.apps.into_values().collect();
    list.sort_by(|a, b| a.label.to_lowercase().cmp(&b.label.to_lowercase()));
    list
}

#[cfg(not(windows))]
pub fn list_desktop_applications() -> Vec<DesktopApplication> {
    Vec::new()
}

/// Rising-edge detector for LMB (0x01), Enter (0x0D), Space (0x20) via GetAsyncKeyState.
pub struct InputTriggerMonitor {
    keys: [i32; 3],
    previous: [bool; 3],
}

impl InputTriggerMonitor {
    pub fn new() -> Self {
        let keys = [0x01, 0x0D, 0x20];
        let previous = Self::read_state(&keys);
        Self { keys, previous }
    }

    #[cfg(windows)]
    fn read_state(keys: &[i32; 3]) -> [bool; 3] {
        use windows::Win32::UI::Input::KeyboardAndMouse::GetAsyncKeyState;
        unsafe {
            [
                (GetAsyncKeyState(keys[0]) as u16 & 0x8000) != 0,
                (GetAsyncKeyState(keys[1]) as u16 & 0x8000) != 0,
                (GetAsyncKeyState(keys[2]) as u16 & 0x8000) != 0,
            ]
        }
    }

    #[cfg(not(windows))]
    fn read_state(_keys: &[i32; 3]) -> [bool; 3] {
        [false, false, false]
    }

    pub fn poll_triggered(&mut self) -> bool {
        let current = Self::read_state(&self.keys);
        let triggered = self
            .previous
            .iter()
            .zip(current.iter())
            .any(|(&prev, &now)| now && !prev);
        self.previous = current;
        triggered
    }

    pub fn reset(&mut self) {
        self.previous = Self::read_state(&self.keys);
    }
}
