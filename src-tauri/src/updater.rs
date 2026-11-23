use base64::Engine;
use chrono::Utc;
use ed25519_dalek::{Signature, VerifyingKey};
use futures_util::StreamExt;
use semver::Version;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager, State};

pub const DEFAULT_BASE_URL: &str = "https://builds.amri2k.com";
pub const DEFAULT_PUBLIC_KEY_B64: &str = "vTwdIZ/PH1/OvOq1eSxoFTLTwBN3lAxo975k9PVeZJE=";
pub const DEFAULT_CHECK_INTERVAL_SECS: u64 = 6 * 3600; // 6 hours
pub const DEFAULT_STARTUP_DELAY_SECS: u64 = 3;
pub const UPDATER_STATE_EVENT: &str = "updater-state";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum InstallKind {
    Auto,
    Portable,
    Installer,
}

#[derive(Debug, Clone)]
pub struct UpdaterConfig {
    pub slug: String,
    pub app_name: String,
    pub current_version: String,
    pub default_base_url: String,
    pub public_key_b64: String,
    pub install_kind: InstallKind,
    pub check_interval_secs: u64,
    pub startup_delay_secs: u64,
}

impl UpdaterConfig {
    pub fn new(slug: impl Into<String>, app_name: impl Into<String>, current_version: impl Into<String>) -> Self {
        let default_base_url = option_env!("AMRI2K_UPDATER_BASE_URL")
            .unwrap_or(DEFAULT_BASE_URL)
            .trim_end_matches('/')
            .to_string();
        let startup_delay_secs = std::env::var("AMRI2K_UPDATER_STARTUP_DELAY_SECS")
            .ok()
            .and_then(|v| v.parse::<u64>().ok())
            .unwrap_or(DEFAULT_STARTUP_DELAY_SECS);
        Self {
            slug: slug.into().to_ascii_lowercase(),
            app_name: app_name.into(),
            current_version: current_version.into(),
            default_base_url,
            public_key_b64: DEFAULT_PUBLIC_KEY_B64.to_string(),
            install_kind: InstallKind::Auto,
            check_interval_secs: DEFAULT_CHECK_INTERVAL_SECS,
            startup_delay_secs,
        }
    }

    pub fn with_install_kind(mut self, kind: InstallKind) -> Self {
        self.install_kind = kind;
        self
    }

    #[allow(dead_code)]
    pub fn with_public_key(mut self, public_key_b64: impl Into<String>) -> Self {
        self.public_key_b64 = public_key_b64.into();
        self
    }

    pub fn effective_base_url(&self) -> (String, bool) {
        if let Ok(over) = std::env::var("AMRI2K_UPDATER_BASE_URL") {
            let trimmed = over.trim().trim_end_matches('/');
            if !trimmed.is_empty() {
                return (trimmed.to_string(), true);
            }
        }
        (self.default_base_url.trim_end_matches('/').to_string(), false)
    }

    pub fn manifest_url(&self) -> String {
        let (base, _) = self.effective_base_url();
        format!("{}/builds/{}/latest.json", base, self.slug)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdaterSettings {
    #[serde(default = "default_true")]
    pub auto_update: bool,
}

fn default_true() -> bool {
    true
}

impl Default for UpdaterSettings {
    fn default() -> Self {
        Self { auto_update: true }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateManifest {
    #[serde(default = "default_schema_version")]
    pub schema_version: u32,
    pub app: String,
    pub version: String,
    #[serde(default)]
    pub pub_date: String,
    #[serde(default)]
    pub notes: Vec<String>,
    #[serde(default)]
    pub files: HashMap<String, UpdateFileEntry>,
}

fn default_schema_version() -> u32 {
    1
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateFileEntry {
    pub kind: String,
    #[serde(default)]
    pub platform: String,
    pub filename: String,
    pub object_key: String,
    pub url: String,
    pub size: u64,
    pub sha256: String,
    #[serde(default)]
    pub signature: Option<String>,
    #[serde(default)]
    pub silent_args: Option<Vec<String>>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateInfoDto {
    pub version: String,
    pub pub_date: String,
    pub notes: Vec<String>,
    pub kind: String,
    pub filename: String,
    pub size: u64,
    pub sha256: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdaterStateDto {
    pub status: String,
    pub current_version: String,
    pub detected_kind: String,
    pub auto_update: bool,
    pub last_checked_at: Option<String>,
    pub available: Option<UpdateInfoDto>,
    pub downloaded_bytes: u64,
    pub total_bytes: u64,
    pub speed_bps: u64,
    pub install_on_exit: bool,
    pub error: Option<String>,
    pub manifest_url: String,
}

#[derive(Debug, Clone)]
struct PendingUpdate {
    manifest_version: String,
    pub_date: String,
    notes: Vec<String>,
    entry: UpdateFileEntry,
    staged_path: Option<PathBuf>,
}

struct InnerState {
    status: String,
    auto_update: bool,
    last_checked_at: Option<String>,
    pending: Option<PendingUpdate>,
    downloaded_bytes: u64,
    total_bytes: u64,
    speed_bps: u64,
    install_on_exit: bool,
    error: Option<String>,
}

pub struct UpdaterManager {
    config: UpdaterConfig,
    detected_kind: String,
    inner: Mutex<InnerState>,
    last_toast: Mutex<Option<(String, String)>>,
    cancel_download: Arc<AtomicBool>,
    apply_triggered: AtomicBool,
    app: AppHandle,
}

impl UpdaterManager {
    pub fn init(app: &AppHandle, config: UpdaterConfig) -> Arc<Self> {
        let detected_kind = detect_install_kind(config.install_kind);
        let settings = load_settings(&config.app_name);

        // Clean up any leftover `.old` exe or outdated staged files from prior updates.
        cleanup_leftovers(&config.app_name, &config.current_version);

        let manager = Arc::new(Self {
            config: config.clone(),
            detected_kind,
            inner: Mutex::new(InnerState {
                status: "idle".to_string(),
                auto_update: settings.auto_update,
                last_checked_at: None,
                pending: None,
                downloaded_bytes: 0,
                total_bytes: 0,
                speed_bps: 0,
                install_on_exit: false,
                error: None,
            }),
            last_toast: Mutex::new(None),
            cancel_download: Arc::new(AtomicBool::new(false)),
            apply_triggered: AtomicBool::new(false),
            app: app.clone(),
        });

        app.manage(manager.clone());

        // Background startup check + periodic 6-hour check loop.
        let bg = manager.clone();
        tauri::async_runtime::spawn(async move {
            if bg.config.startup_delay_secs > 0 {
                tokio::time::sleep(Duration::from_secs(bg.config.startup_delay_secs)).await;
            }
            if bg.is_auto_update_enabled() {
                let _ = bg.check_for_update(true).await;
            }
            let interval_secs = bg.config.check_interval_secs.max(300);
            let mut interval = tokio::time::interval(Duration::from_secs(interval_secs));
            interval.tick().await; // consume first immediate tick
            loop {
                interval.tick().await;
                if bg.is_auto_update_enabled() && !bg.is_busy_or_ready() {
                    let _ = bg.check_for_update(true).await;
                }
            }
        });

        manager
    }

    pub fn is_auto_update_enabled(&self) -> bool {
        self.inner.lock().map(|s| s.auto_update).unwrap_or(true)
    }

    fn is_busy_or_ready(&self) -> bool {
        self.inner
            .lock()
            .map(|s| {
                matches!(
                    s.status.as_str(),
                    "checking" | "downloading" | "verifying" | "ready" | "installing"
                )
            })
            .unwrap_or(false)
    }

    pub fn snapshot(&self) -> UpdaterStateDto {
        let guard = self.inner.lock().unwrap();
        UpdaterStateDto {
            status: guard.status.clone(),
            current_version: self.config.current_version.clone(),
            detected_kind: self.detected_kind.clone(),
            auto_update: guard.auto_update,
            last_checked_at: guard.last_checked_at.clone(),
            available: guard.pending.as_ref().map(|p| UpdateInfoDto {
                version: p.manifest_version.clone(),
                pub_date: p.pub_date.clone(),
                notes: p.notes.clone(),
                kind: p.entry.kind.clone(),
                filename: p.entry.filename.clone(),
                size: p.entry.size,
                sha256: p.entry.sha256.clone(),
            }),
            downloaded_bytes: guard.downloaded_bytes,
            total_bytes: guard.total_bytes,
            speed_bps: guard.speed_bps,
            install_on_exit: guard.install_on_exit,
            error: guard.error.clone(),
            manifest_url: self.config.manifest_url(),
        }
    }

    fn emit_state(&self) {
        let dto = self.snapshot();
        let _ = self.app.emit(UPDATER_STATE_EVENT, dto);
    }

    pub fn set_auto_update(&self, enabled: bool) -> UpdaterStateDto {
        if let Ok(mut guard) = self.inner.lock() {
            guard.auto_update = enabled;
        }
        save_settings(&self.config.app_name, &UpdaterSettings { auto_update: enabled });
        self.emit_state();
        self.snapshot()
    }

    pub fn set_install_on_exit(&self, enabled: bool) -> UpdaterStateDto {
        if let Ok(mut guard) = self.inner.lock() {
            guard.install_on_exit = enabled;
        }
        self.emit_state();
        self.snapshot()
    }

    pub fn cancel_download(&self) -> UpdaterStateDto {
        self.cancel_download.store(true, Ordering::SeqCst);
        self.snapshot()
    }

    pub async fn check_for_update(self: &Arc<Self>, auto_download: bool) -> Result<UpdaterStateDto, String> {
        // Avoid overlapping checks/downloads.
        {
            let mut guard = self.inner.lock().unwrap();
            if matches!(guard.status.as_str(), "checking" | "downloading" | "verifying" | "installing") {
                return Ok(self.snapshot());
            }
            guard.status = "checking".to_string();
            guard.error = None;
        }
        self.emit_state();

        let manifest_url = self.config.manifest_url();
        let client = reqwest::Client::builder()
            .user_agent(format!("{}/{}", self.config.app_name, self.config.current_version))
            .timeout(Duration::from_secs(20))
            .build()
            .map_err(|e| {
                eprintln!("[updater] failed to build HTTP client: {e}");
                let user_err = "Không kết nối được, thử lại sau.".to_string();
                self.set_error(&user_err);
                user_err
            })?;

        let fetch_res = client
            .get(&manifest_url)
            .header(reqwest::header::CACHE_CONTROL, "no-cache")
            .send()
            .await;

        let manifest: UpdateManifest = match fetch_res {
            Ok(resp) => {
                if !resp.status().is_success() {
                    eprintln!(
                        "[updater] manifest fetch {} returned HTTP {}",
                        manifest_url,
                        resp.status().as_u16()
                    );
                    let err = "Không kết nối được, thử lại sau.".to_string();
                    self.set_error(&err);
                    return Err(err);
                }
                match resp.json::<UpdateManifest>().await {
                    Ok(m) => m,
                    Err(e) => {
                        eprintln!("[updater] invalid update manifest JSON from {manifest_url}: {e}");
                        let err = "Tệp cập nhật không hợp lệ, thử lại sau.".to_string();
                        self.set_error(&err);
                        return Err(err);
                    }
                }
            }
            Err(e) => {
                eprintln!("[updater] failed to fetch manifest {manifest_url}: {e}");
                let err = "Không kết nối được, thử lại sau.".to_string();
                self.set_error(&err);
                return Err(err);
            }
        };

        let now_iso = Utc::now().to_rfc3339();
        if !manifest.app.eq_ignore_ascii_case(&self.config.slug) {
            eprintln!(
                "[updater] manifest app mismatch: got '{}', expected '{}'",
                manifest.app, self.config.slug
            );
            let err = "Tệp cập nhật không hợp lệ, thử lại sau.".to_string();
            self.set_error(&err);
            return Err(err);
        }

        if !is_newer_version(&self.config.current_version, &manifest.version) {
            {
                let mut guard = self.inner.lock().unwrap();
                guard.status = "up-to-date".to_string();
                guard.last_checked_at = Some(now_iso);
                guard.pending = None;
                guard.error = None;
                guard.downloaded_bytes = 0;
                guard.total_bytes = 0;
                guard.speed_bps = 0;
            }
            self.emit_state();
            return Ok(self.snapshot());
        }

        let Some(entry) = select_file_entry(&manifest, &self.detected_kind) else {
            eprintln!(
                "[updater] no matching artifact for kind '{}' in v{}",
                self.detected_kind, manifest.version
            );
            let err = "Chưa có bản cập nhật phù hợp cho máy này.".to_string();
            self.set_error(&err);
            return Err(err);
        };

        let staged_candidate = staged_file_path(&self.config.app_name, &manifest.version, &entry.filename);
        let already_verified = staged_candidate.is_file()
            && verify_staged_file(&staged_candidate, &self.config, &manifest.version, &entry).is_ok();

        {
            let mut guard = self.inner.lock().unwrap();
            guard.last_checked_at = Some(now_iso);
            guard.error = None;
            guard.pending = Some(PendingUpdate {
                manifest_version: manifest.version.clone(),
                pub_date: manifest.pub_date.clone(),
                notes: manifest.notes.clone(),
                entry: entry.clone(),
                staged_path: if already_verified { Some(staged_candidate.clone()) } else { None },
            });
            if already_verified {
                guard.status = "ready".to_string();
                guard.downloaded_bytes = entry.size;
                guard.total_bytes = entry.size;
                guard.speed_bps = 0;
            } else {
                guard.status = "available".to_string();
                guard.downloaded_bytes = 0;
                guard.total_bytes = entry.size;
                guard.speed_bps = 0;
            }
        }
        self.emit_state();

        if already_verified {
            self.notify_system_toast(
                &manifest.version,
                "ready",
                &format!("Đã tải xong {} v{}", self.config.app_name, manifest.version),
                &format!(
                    "Mở {} và nhấn Khởi động lại để hoàn tất cập nhật.",
                    self.config.app_name
                ),
            );
        } else {
            let body = if auto_download {
                "Đang tự động tải nền — sẽ thông báo khi sẵn sàng cài đặt.".to_string()
            } else {
                manifest
                    .notes
                    .first()
                    .cloned()
                    .unwrap_or_else(|| format!("Mở {} để tải và cập nhật ngay.", self.config.app_name))
            };
            self.notify_system_toast(
                &manifest.version,
                "available",
                &format!("Có bản cập nhật mới {} v{}", self.config.app_name, manifest.version),
                &body,
            );
        }

        if !already_verified && auto_download {
            let mgr = self.clone();
            tauri::async_runtime::spawn(async move {
                let _ = mgr.download_update().await;
            });
        }

        Ok(self.snapshot())
    }

    pub async fn download_update(self: &Arc<Self>) -> Result<UpdaterStateDto, String> {
        let pending = {
            let mut guard = self.inner.lock().unwrap();
            if guard.status == "downloading" || guard.status == "verifying" {
                return Ok(self.snapshot());
            }
            let Some(p) = guard.pending.clone() else {
                return Err("Chưa có bản cập nhật nào để tải.".to_string());
            };
            if p.staged_path.as_ref().is_some_and(|path| path.is_file()) {
                guard.status = "ready".to_string();
                return Ok(self.snapshot());
            }
            guard.status = "downloading".to_string();
            guard.downloaded_bytes = 0;
            guard.total_bytes = p.entry.size;
            guard.speed_bps = 0;
            guard.error = None;
            p
        };

        self.cancel_download.store(false, Ordering::SeqCst);
        self.emit_state();

        let download_url = resolve_download_url(&self.config, &pending.entry);
        let staged_path = staged_file_path(
            &self.config.app_name,
            &pending.manifest_version,
            &pending.entry.filename,
        );
        if let Some(parent) = staged_path.parent() {
            if let Err(e) = fs::create_dir_all(parent) {
                eprintln!("[updater] failed to create staging dir {:?}: {e}", parent);
                let err = "Không lưu được tệp cập nhật, thử lại sau.".to_string();
                self.set_error(&err);
                return Err(err);
            }
        }
        let part_path = staged_path.with_extension("part");

        let client = reqwest::Client::builder()
            .user_agent(format!("{}/{}", self.config.app_name, self.config.current_version))
            .connect_timeout(Duration::from_secs(20))
            .build()
            .map_err(|e| {
                eprintln!("[updater] failed to build download HTTP client: {e}");
                let user_err = "Không kết nối được, thử lại sau.".to_string();
                self.set_error(&user_err);
                user_err
            })?;

        let resp = match client.get(&download_url).send().await {
            Ok(r) if r.status().is_success() => r,
            Ok(r) => {
                eprintln!(
                    "[updater] download {} returned HTTP {}",
                    download_url,
                    r.status().as_u16()
                );
                let err = "Không tải được bản cập nhật, thử lại sau.".to_string();
                self.set_error(&err);
                return Err(err);
            }
            Err(e) => {
                eprintln!("[updater] download failed for {download_url}: {e}");
                let err = "Không kết nối được, thử lại sau.".to_string();
                self.set_error(&err);
                return Err(err);
            }
        };

        let total_bytes = resp
            .content_length()
            .filter(|&n| n > 0)
            .unwrap_or(pending.entry.size);
        {
            let mut guard = self.inner.lock().unwrap();
            guard.total_bytes = total_bytes;
        }
        self.emit_state();

        let mut file = match File::create(&part_path) {
            Ok(f) => f,
            Err(e) => {
                eprintln!("[updater] failed to create temp file {:?}: {e}", part_path);
                let err = "Không lưu được tệp cập nhật, thử lại sau.".to_string();
                self.set_error(&err);
                return Err(err);
            }
        };

        let mut hasher = Sha256::new();
        let mut downloaded: u64 = 0;
        let started_at = Instant::now();
        let mut last_emit = Instant::now();
        let mut stream = resp.bytes_stream();

        while let Some(chunk_res) = stream.next().await {
            if self.cancel_download.load(Ordering::SeqCst) {
                drop(file);
                let _ = fs::remove_file(&part_path);
                {
                    let mut guard = self.inner.lock().unwrap();
                    guard.status = "available".to_string();
                    guard.downloaded_bytes = 0;
                    guard.speed_bps = 0;
                    guard.error = None;
                }
                self.emit_state();
                return Ok(self.snapshot());
            }

            let chunk = match chunk_res {
                Ok(c) => c,
                Err(e) => {
                    drop(file);
                    let _ = fs::remove_file(&part_path);
                    eprintln!("[updater] download stream interrupted for {download_url}: {e}");
                    let err = "Tải xuống bị gián đoạn, thử lại sau.".to_string();
                    self.set_error(&err);
                    return Err(err);
                }
            };

            if let Err(e) = file.write_all(&chunk) {
                drop(file);
                let _ = fs::remove_file(&part_path);
                eprintln!("[updater] write error to {:?}: {e}", part_path);
                let err = "Không lưu được tệp cập nhật, thử lại sau.".to_string();
                self.set_error(&err);
                return Err(err);
            }

            hasher.update(&chunk);
            downloaded = downloaded.saturating_add(chunk.len() as u64);

            if last_emit.elapsed() >= Duration::from_millis(100) {
                let elapsed_secs = started_at.elapsed().as_secs_f64().max(0.05);
                let speed_bps = (downloaded as f64 / elapsed_secs) as u64;
                {
                    let mut guard = self.inner.lock().unwrap();
                    guard.downloaded_bytes = downloaded;
                    guard.speed_bps = speed_bps;
                }
                self.emit_state();
                last_emit = Instant::now();
            }
        }

        if let Err(e) = file.flush() {
            drop(file);
            let _ = fs::remove_file(&part_path);
            eprintln!("[updater] flush error on {:?}: {e}", part_path);
            let err = "Không lưu được tệp cập nhật, thử lại sau.".to_string();
            self.set_error(&err);
            return Err(err);
        }
        drop(file);

        {
            let mut guard = self.inner.lock().unwrap();
            guard.status = "verifying".to_string();
            guard.downloaded_bytes = downloaded;
            guard.speed_bps = 0;
        }
        self.emit_state();

        let actual_sha = hex_encode(&hasher.finalize());
        if let Err(err) = verify_hash_and_signature(
            downloaded,
            &actual_sha,
            &self.config,
            &pending.manifest_version,
            &pending.entry,
        ) {
            let _ = fs::remove_file(&part_path);
            self.set_error(&err);
            return Err(err);
        }

        if staged_path.exists() {
            let _ = fs::remove_file(&staged_path);
        }
        if let Err(e) = fs::rename(&part_path, &staged_path) {
            let _ = fs::remove_file(&part_path);
            eprintln!("[updater] rename {:?} -> {:?} failed: {e}", part_path, staged_path);
            let err = "Không lưu được tệp cập nhật, thử lại sau.".to_string();
            self.set_error(&err);
            return Err(err);
        }

        {
            let mut guard = self.inner.lock().unwrap();
            guard.status = "ready".to_string();
            guard.downloaded_bytes = downloaded;
            guard.total_bytes = downloaded;
            guard.speed_bps = 0;
            guard.error = None;
            if let Some(p) = guard.pending.as_mut() {
                p.staged_path = Some(staged_path);
            }
        }
        self.emit_state();
        self.notify_system_toast(
            &pending.manifest_version,
            "ready",
            &format!("Đã tải xong {} v{}", self.config.app_name, pending.manifest_version),
            &format!(
                "Mở {} và nhấn Khởi động lại để hoàn tất cập nhật.",
                self.config.app_name
            ),
        );
        Ok(self.snapshot())
    }

    pub fn install_now(&self, relaunch: bool) -> Result<(), String> {
        let pending = {
            let mut guard = self.inner.lock().unwrap();
            let Some(p) = guard.pending.clone() else {
                return Err("Không có bản cập nhật sẵn sàng để cài đặt.".to_string());
            };
            if p.staged_path.as_ref().is_none_or(|path| !path.is_file()) {
                return Err("Tệp cập nhật chưa được tải xong.".to_string());
            }
            guard.status = "installing".to_string();
            guard.error = None;
            p
        };

        if self.apply_triggered.swap(true, Ordering::SeqCst) {
            return Ok(());
        }
        self.emit_state();

        let staged_path = pending.staged_path.unwrap();
        // Re-verify integrity right before applying!
        if let Err(err) = verify_staged_file(&staged_path, &self.config, &pending.manifest_version, &pending.entry) {
            self.apply_triggered.store(false, Ordering::SeqCst);
            self.set_error(&err);
            return Err(err);
        }

        let followup = match spawn_apply_helper(&self.config.slug, &staged_path, &pending.entry, relaunch) {
            Ok(f) => f,
            Err(err) => {
                self.apply_triggered.store(false, Ordering::SeqCst);
                self.set_error(&err);
                return Err(err);
            }
        };

        match followup {
            ApplyFollowup::ExitSoon => {
                if relaunch {
                    // Give frontend a brief moment to paint "Đang áp dụng...", then exit cleanly.
                    let app = self.app.clone();
                    tauri::async_runtime::spawn(async move {
                        tokio::time::sleep(Duration::from_millis(180)).await;
                        app.exit(0);
                    });
                }
            }
            #[cfg(target_os = "windows")]
            ApplyFollowup::WaitInstallerAndRelaunch {
                process_handle,
                staged_path,
                target_exe,
            } => {
                // Hide windows while the silent installer finishes, then relaunch new binary & exit.
                for win in self.app.webview_windows().values() {
                    let _ = win.hide();
                }
                let app = self.app.clone();
                std::thread::spawn(move || {
                    win32_ffi::wait_and_close_handle(process_handle, 180_000);
                    let _ = fs::remove_file(&staged_path);
                    if target_exe.is_file() {
                        let _ = std::process::Command::new(&target_exe).spawn();
                    }
                    app.exit(0);
                });
            }
        }
        Ok(())
    }

    /// Call from `RunEvent::Exit` or window close handler to apply a staged update when
    /// the user chose "Cài khi thoát" (install on exit).
    pub fn apply_on_exit_if_scheduled(&self) {
        let should_apply = self
            .inner
            .lock()
            .map(|g| {
                g.install_on_exit
                    && g.status == "ready"
                    && g.pending
                        .as_ref()
                        .and_then(|p| p.staged_path.as_ref())
                        .is_some_and(|p| p.is_file())
            })
            .unwrap_or(false);

        if should_apply {
            let _ = self.install_now(false);
        }
    }

    fn set_error(&self, msg: &str) {
        if let Ok(mut guard) = self.inner.lock() {
            guard.status = "error".to_string();
            guard.error = Some(msg.to_string());
            guard.speed_bps = 0;
        }
        self.emit_state();
    }

    fn notify_system_toast(&self, version: &str, stage: &str, title: &str, body: &str) {
        if std::env::var("AMRI2K_UPDATER_NO_TOAST")
            .ok()
            .is_some_and(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        {
            return;
        }
        if let Ok(mut last) = self.last_toast.lock() {
            let key = (version.to_string(), stage.to_string());
            if last.as_ref() == Some(&key) {
                return;
            }
            *last = Some(key);
        }
        let slug = self.config.slug.clone();
        let app_name = self.config.app_name.clone();
        let title_owned = title.to_string();
        let body_owned = body.to_string();
        std::thread::spawn(move || {
            show_windows_toast(&slug, &app_name, &title_owned, &body_owned);
        });
    }
}

// ── Tauri Commands ────────────────────────────────────────────────────────────

#[tauri::command]
pub fn updater_get_state(updater: State<'_, Arc<UpdaterManager>>) -> UpdaterStateDto {
    updater.snapshot()
}

#[tauri::command]
pub async fn updater_check(
    auto_download: Option<bool>,
    updater: State<'_, Arc<UpdaterManager>>,
) -> Result<UpdaterStateDto, String> {
    let mgr = updater.inner().clone();
    let dl = auto_download.unwrap_or_else(|| mgr.is_auto_update_enabled());
    mgr.check_for_update(dl).await
}

#[tauri::command]
pub async fn updater_download(
    updater: State<'_, Arc<UpdaterManager>>,
) -> Result<UpdaterStateDto, String> {
    let mgr = updater.inner().clone();
    mgr.download_update().await
}

#[tauri::command]
pub fn updater_cancel_download(updater: State<'_, Arc<UpdaterManager>>) -> UpdaterStateDto {
    updater.cancel_download()
}

#[tauri::command]
pub fn updater_install_now(
    relaunch: Option<bool>,
    updater: State<'_, Arc<UpdaterManager>>,
) -> Result<(), String> {
    updater.install_now(relaunch.unwrap_or(true))
}

#[tauri::command]
pub fn updater_set_auto_update(
    enabled: bool,
    updater: State<'_, Arc<UpdaterManager>>,
) -> UpdaterStateDto {
    updater.set_auto_update(enabled)
}

#[tauri::command]
pub fn updater_set_install_on_exit(
    enabled: bool,
    updater: State<'_, Arc<UpdaterManager>>,
) -> UpdaterStateDto {
    updater.set_install_on_exit(enabled)
}

// ── Helpers: Version, Selection, Crypto, Storage, Windows Apply ───────────────

pub fn canonical_sign_payload(
    slug: &str,
    version: &str,
    kind: &str,
    filename: &str,
    size: u64,
    sha256_lower: &str,
) -> String {
    format!(
        "2k-update-v1\n{}\n{}\n{}\n{}\n{}\n{}\n",
        slug.trim().to_ascii_lowercase(),
        version.trim().trim_start_matches(['v', 'V']),
        kind.trim().to_ascii_lowercase(),
        filename.trim(),
        size,
        sha256_lower.trim().to_ascii_lowercase()
    )
}

pub fn is_newer_version(current: &str, candidate: &str) -> bool {
    let cur = Version::parse(current.trim().trim_start_matches(['v', 'V']));
    let cand = Version::parse(candidate.trim().trim_start_matches(['v', 'V']));
    match (cur, cand) {
        (Ok(c), Ok(n)) => n > c,
        _ => false,
    }
}

fn detect_install_kind(configured: InstallKind) -> String {
    match configured {
        InstallKind::Portable => return "portable".to_string(),
        InstallKind::Installer => return "installer".to_string(),
        InstallKind::Auto => {}
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            if dir.join("uninstall.exe").is_file() || dir.join("unins000.exe").is_file() {
                return "installer".to_string();
            }
            let dir_lower = dir.to_string_lossy().to_ascii_lowercase();
            if dir_lower.contains("\\program files\\")
                || dir_lower.contains("\\program files (x86)\\")
                || dir_lower.contains("\\appdata\\local\\programs\\")
                || dir_lower.contains("\\programs\\_2k\\")
            {
                return "installer".to_string();
            }
        }
    }
    "portable".to_string()
}

pub fn select_file_entry(manifest: &UpdateManifest, detected_kind: &str) -> Option<UpdateFileEntry> {
    let primary_key = if detected_kind == "installer" {
        "windows-x86_64-installer"
    } else {
        "windows-x86_64-portable"
    };
    let fallback_key = if detected_kind == "installer" {
        "windows-x86_64-portable"
    } else {
        "windows-x86_64-installer"
    };

    manifest
        .files
        .get(primary_key)
        .or_else(|| manifest.files.get(fallback_key))
        .or_else(|| manifest.files.values().find(|f| f.kind.eq_ignore_ascii_case(detected_kind)))
        .or_else(|| manifest.files.values().next())
        .cloned()
}

pub fn resolve_download_url(config: &UpdaterConfig, entry: &UpdateFileEntry) -> String {
    let (base, is_override) = config.effective_base_url();
    if is_override && !entry.object_key.trim().is_empty() {
        return format!("{}/{}", base, entry.object_key.trim_start_matches('/'));
    }
    if entry.url.starts_with("http://") || entry.url.starts_with("https://") {
        entry.url.clone()
    } else if !entry.object_key.trim().is_empty() {
        format!("{}/{}", base, entry.object_key.trim_start_matches('/'))
    } else {
        format!("{}/{}", base, entry.url.trim_start_matches('/'))
    }
}

pub fn verify_hash_and_signature(
    actual_size: u64,
    actual_sha256: &str,
    config: &UpdaterConfig,
    manifest_version: &str,
    entry: &UpdateFileEntry,
) -> Result<(), String> {
    if entry.size > 0 && actual_size != entry.size {
        eprintln!(
            "[updater] size mismatch for {}: got {} bytes, expected {} bytes",
            entry.filename, actual_size, entry.size
        );
        return Err("Tệp cập nhật không hợp lệ, thử lại sau.".to_string());
    }

    if !actual_sha256.eq_ignore_ascii_case(entry.sha256.trim()) {
        eprintln!(
            "[updater] SHA-256 mismatch for {}: got {}, expected {}",
            entry.filename, actual_sha256, entry.sha256
        );
        return Err("Tệp cập nhật không hợp lệ, thử lại sau.".to_string());
    }

    if !config.public_key_b64.trim().is_empty() {
        let Some(sig_b64) = entry
            .signature
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
        else {
            eprintln!("[updater] missing Ed25519 signature for {}", entry.filename);
            return Err("Tệp cập nhật không hợp lệ, thử lại sau.".to_string());
        };

        verify_ed25519_signature(
            &config.public_key_b64,
            sig_b64,
            &config.slug,
            manifest_version,
            &entry.kind,
            &entry.filename,
            actual_size,
            actual_sha256,
        )?;
    }

    Ok(())
}

pub fn verify_ed25519_signature(
    public_key_b64: &str,
    signature_b64: &str,
    slug: &str,
    version: &str,
    kind: &str,
    filename: &str,
    size: u64,
    sha256: &str,
) -> Result<(), String> {
    let invalid = || "Tệp cập nhật không hợp lệ, thử lại sau.".to_string();

    let pub_bytes = base64::engine::general_purpose::STANDARD
        .decode(public_key_b64.trim())
        .map_err(|e| {
            eprintln!("[updater] invalid Ed25519 public key base64: {e}");
            invalid()
        })?;
    let pub_arr: [u8; 32] = pub_bytes.try_into().map_err(|_| {
        eprintln!("[updater] Ed25519 public key length must be 32 bytes");
        invalid()
    })?;
    let verifying_key = VerifyingKey::from_bytes(&pub_arr).map_err(|e| {
        eprintln!("[updater] failed to parse Ed25519 public key: {e}");
        invalid()
    })?;

    let sig_bytes = base64::engine::general_purpose::STANDARD
        .decode(signature_b64.trim())
        .map_err(|e| {
            eprintln!("[updater] invalid Ed25519 signature base64: {e}");
            invalid()
        })?;
    let sig_arr: [u8; 64] = sig_bytes.try_into().map_err(|_| {
        eprintln!("[updater] Ed25519 signature length must be 64 bytes");
        invalid()
    })?;
    let signature = Signature::from_bytes(&sig_arr);

    let payload = canonical_sign_payload(slug, version, kind, filename, size, sha256);
    verifying_key
        .verify_strict(payload.as_bytes(), &signature)
        .map_err(|_| {
            eprintln!("[updater] Ed25519 signature verification failed for {slug} v{version} ({filename})");
            invalid()
        })
}

fn verify_staged_file(
    path: &Path,
    config: &UpdaterConfig,
    manifest_version: &str,
    entry: &UpdateFileEntry,
) -> Result<(), String> {
    let mut file = File::open(path).map_err(|e| {
        eprintln!("[updater] failed to open staged file {:?}: {e}", path);
        "Tệp cập nhật không hợp lệ, thử lại sau.".to_string()
    })?;
    let mut hasher = Sha256::new();
    let mut buf = [0u8; 64 * 1024];
    let mut size: u64 = 0;
    loop {
        let n = std::io::Read::read(&mut file, &mut buf).map_err(|e| {
            eprintln!("[updater] failed to read staged file {:?}: {e}", path);
            "Tệp cập nhật không hợp lệ, thử lại sau.".to_string()
        })?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
        size = size.saturating_add(n as u64);
    }
    let sha = hex_encode(&hasher.finalize());
    verify_hash_and_signature(size, &sha, config, manifest_version, entry)
}

fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0f) as usize] as char);
    }
    out
}

fn app_data_dir(app_name: &str) -> PathBuf {
    let base = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir);
    base.join(app_name)
}

fn settings_file_path(app_name: &str) -> PathBuf {
    app_data_dir(app_name).join("updater-settings.json")
}

fn updates_dir(app_name: &str) -> PathBuf {
    app_data_dir(app_name).join("updates")
}

fn staged_file_path(app_name: &str, version: &str, filename: &str) -> PathBuf {
    let safe_ver: String = version
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | '_') { c } else { '-' })
        .collect();
    let safe_name: String = Path::new(filename)
        .file_name()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| "update.exe".to_string());
    updates_dir(app_name).join(safe_ver).join(safe_name)
}

fn load_settings(app_name: &str) -> UpdaterSettings {
    let path = settings_file_path(app_name);
    fs::read_to_string(&path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

fn save_settings(app_name: &str, settings: &UpdaterSettings) {
    let path = settings_file_path(app_name);
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Ok(json) = serde_json::to_string_pretty(settings) {
        let tmp = path.with_extension("json.tmp");
        if fs::write(&tmp, &json).is_ok() {
            let _ = fs::rename(&tmp, &path).or_else(|_| fs::write(&path, &json));
        }
    }
}

fn cleanup_leftovers(app_name: &str, current_version: &str) {
    // 1. Remove leftover `<current_exe>.old` next to running portable exe.
    //    If the previous process is still exiting for a few hundred ms, retry briefly in background.
    if let Ok(exe) = std::env::current_exe() {
        let mut old_os = exe.as_os_str().to_os_string();
        old_os.push(".old");
        let old_path = PathBuf::from(old_os);
        if old_path.is_file() && fs::remove_file(&old_path).is_err() {
            std::thread::spawn(move || {
                for _ in 0..12 {
                    std::thread::sleep(Duration::from_millis(250));
                    if !old_path.exists() || fs::remove_file(&old_path).is_ok() {
                        break;
                    }
                }
            });
        }
    }

    // 2. Remove staged update folders for versions <= current_version.
    let root = updates_dir(app_name);
    if let Ok(entries) = fs::read_dir(&root) {
        for entry in entries.flatten() {
            let p = entry.path();
            if p.is_dir() {
                if let Some(ver_name) = p.file_name().and_then(|s| s.to_str()) {
                    if !is_newer_version(current_version, ver_name) {
                        let _ = fs::remove_dir_all(&p);
                    }
                }
            }
        }
    }
}

enum ApplyFollowup {
    ExitSoon,
    #[cfg(target_os = "windows")]
    WaitInstallerAndRelaunch {
        process_handle: usize,
        staged_path: PathBuf,
        target_exe: PathBuf,
    },
}

fn append_file_suffix(path: &Path, suffix: &str) -> PathBuf {
    let mut os = path.as_os_str().to_os_string();
    os.push(suffix);
    PathBuf::from(os)
}

fn can_write_directory(dir: &Path) -> bool {
    let probe = dir.join(format!(".2k-update-probe-{}.tmp", std::process::id()));
    match File::create(&probe) {
        Ok(_) => {
            let _ = fs::remove_file(&probe);
            true
        }
        Err(_) => false,
    }
}

fn quote_win_arg(arg: &str) -> String {
    if arg.is_empty() || arg.contains([' ', '\t', '"']) {
        format!("\"{}\"", arg.replace('"', "\\\""))
    } else {
        arg.to_string()
    }
}

fn build_installer_command_and_args(
    staged_path: &Path,
    entry: &UpdateFileEntry,
    target_dir: &Path,
) -> (PathBuf, String) {
    let is_msi = staged_path
        .extension()
        .is_some_and(|e| e.eq_ignore_ascii_case("msi"));
    if is_msi {
        let sys_root = std::env::var("SystemRoot").unwrap_or_else(|_| r"C:\Windows".to_string());
        let msiexec = PathBuf::from(sys_root).join("System32").join("msiexec.exe");
        let params = format!(
            "/i {} /qn /norestart",
            quote_win_arg(&staged_path.to_string_lossy())
        );
        return (msiexec, params);
    }

    let mut args_vec = entry
        .silent_args
        .clone()
        .filter(|v| !v.is_empty())
        .unwrap_or_else(|| vec!["/S".to_string()]);

    let is_nsis = args_vec.iter().any(|a| a.eq_ignore_ascii_case("/S"));
    let has_dir_arg = args_vec.iter().any(|a| {
        let upper = a.to_ascii_uppercase();
        upper.starts_with("/D=") || upper.starts_with("/DIR=")
    });

    let mut parts: Vec<String> = args_vec.drain(..).map(|a| quote_win_arg(&a)).collect();
    if is_nsis && !has_dir_arg {
        // NSIS requires /D=<dir> to be the last unquoted argument.
        parts.push(format!("/D={}", target_dir.to_string_lossy()));
    }
    (staged_path.to_path_buf(), parts.join(" "))
}

fn swap_portable_binary(staged_path: &Path, target_exe: &Path) -> Result<(), String> {
    let old_bak = append_file_suffix(target_exe, ".old");
    let new_tmp = append_file_suffix(target_exe, ".new");

    let _ = fs::remove_file(&new_tmp);
    fs::copy(staged_path, &new_tmp)
        .map_err(|e| format!("Không sao chép được bản cập nhật mới: {e}"))?;

    let mut moved_old = false;
    for _ in 0..15 {
        if old_bak.exists() {
            let _ = fs::remove_file(&old_bak);
        }
        if !target_exe.exists() || fs::rename(target_exe, &old_bak).is_ok() {
            moved_old = true;
            break;
        }
        std::thread::sleep(Duration::from_millis(250));
    }

    if !moved_old {
        let _ = fs::remove_file(&new_tmp);
        return Err("Không thể thay thế tệp ứng dụng đang chạy.".to_string());
    }

    if let Err(e) = fs::rename(&new_tmp, target_exe) {
        if old_bak.exists() {
            let _ = fs::rename(&old_bak, target_exe);
        }
        let _ = fs::remove_file(&new_tmp);
        return Err(format!("Không thể hoàn tất thay thế bản mới: {e}"));
    }

    let _ = fs::remove_file(&old_bak);
    Ok(())
}

/// Optional early-entry handler for `--apply-portable-update <old_pid> <target_exe> <relaunch_0_or_1>`,
/// used when an `asInvoker` portable binary lives in a protected directory (e.g. `Program Files`)
/// and delegates atomic replacement to the verified staged executable via UAC (`ShellExecuteExW`).
#[cfg(target_os = "windows")]
#[allow(dead_code)]
pub fn maybe_run_apply_update_mode() -> Option<i32> {
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).map(String::as_str) != Some("--apply-portable-update") {
        return None;
    }
    if args.len() < 5 {
        return Some(1);
    }
    let old_pid: u32 = args[2].parse().unwrap_or(0);
    let target_exe = PathBuf::from(&args[3]);
    let relaunch = args[4] == "1";

    if old_pid != 0 {
        win32_ffi::wait_for_pid_exit(old_pid, 25_000);
        std::thread::sleep(Duration::from_millis(250));
    }

    let Ok(self_exe) = std::env::current_exe() else {
        return Some(1);
    };
    if swap_portable_binary(&self_exe, &target_exe).is_err() {
        return Some(1);
    }
    if relaunch && target_exe.is_file() {
        let _ = std::process::Command::new(&target_exe).spawn();
    }
    Some(0)
}

#[cfg(not(target_os = "windows"))]
#[allow(dead_code)]
pub fn maybe_run_apply_update_mode() -> Option<i32> {
    None
}

fn spawn_apply_helper(
    _slug: &str,
    staged_path: &Path,
    entry: &UpdateFileEntry,
    relaunch: bool,
) -> Result<ApplyFollowup, String> {
    #[cfg(not(target_os = "windows"))]
    {
        let _ = (staged_path, entry, relaunch);
        return Err("Tự cập nhật hiện chỉ hỗ trợ Windows.".to_string());
    }

    #[cfg(target_os = "windows")]
    {
        let current_exe = std::env::current_exe()
            .map_err(|e| format!("Không xác định được đường dẫn ứng dụng đang chạy: {e}"))?;
        let target_dir = current_exe
            .parent()
            .ok_or_else(|| "Không xác định được thư mục chứa ứng dụng.".to_string())?;
        let writable = can_write_directory(target_dir);

        if entry.kind.eq_ignore_ascii_case("installer") {
            let (file, params) = build_installer_command_and_args(staged_path, entry, target_dir);
            if writable {
                // Rename running exe so silent NSIS/Inno/MSI can write the new binary immediately.
                let old_bak = append_file_suffix(&current_exe, ".old");
                let _ = fs::remove_file(&old_bak);
                let _ = fs::rename(&current_exe, &old_bak);

                let handle_opt = win32_ffi::launch_installer_silent(&file, &params, false)?;
                if relaunch {
                    if let Some(h) = handle_opt {
                        return Ok(ApplyFollowup::WaitInstallerAndRelaunch {
                            process_handle: h,
                            staged_path: staged_path.to_path_buf(),
                            target_exe: current_exe,
                        });
                    }
                } else if let Some(h) = handle_opt {
                    win32_ffi::close_handle(h);
                }
            } else {
                // Protected directory: launch elevated silent installer and exit cleanly.
                let handle_opt = win32_ffi::launch_installer_silent(&file, &params, true)?;
                if let Some(h) = handle_opt {
                    win32_ffi::close_handle(h);
                }
            }
            return Ok(ApplyFollowup::ExitSoon);
        }

        // Portable single-file exe atomic swap via native Win32 rename (allowed while running).
        if writable {
            swap_portable_binary(staged_path, &current_exe)?;
            let _ = fs::remove_file(staged_path);
            if relaunch {
                std::process::Command::new(&current_exe)
                    .spawn()
                    .map_err(|e| format!("Đã cập nhật nhưng không mở lại được ứng dụng: {e}"))?;
            }
        } else {
            // Target folder requires elevation: run verified staged exe via UAC ShellExecuteExW.
            let pid = std::process::id();
            let relaunch_flag = if relaunch { "1" } else { "0" };
            let params = format!(
                "--apply-portable-update {pid} {} {relaunch_flag}",
                quote_win_arg(&current_exe.to_string_lossy())
            );
            let h = win32_ffi::shell_execute(Some("runas"), staged_path, Some(&params), true, false)?;
            if let Some(handle) = h {
                win32_ffi::close_handle(handle);
            }
        }

        Ok(ApplyFollowup::ExitSoon)
    }
}

#[allow(dead_code)]
pub fn xml_escape(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    for ch in input.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&apos;"),
            _ => out.push(ch),
        }
    }
    out
}

/// Shows a native Windows 10/11 system notification via pure Win32 `Shell_NotifyIconW` (`NIF_INFO`)
/// with zero PowerShell/cmd child processes and zero extra Cargo dependencies.
#[cfg(target_os = "windows")]
fn show_windows_toast(_slug: &str, app_name: &str, title: &str, body: &str) {
    win32_ffi::show_tray_balloon_notification(app_name, title, body);
}

#[cfg(not(target_os = "windows"))]
fn show_windows_toast(_slug: &str, _app_name: &str, _title: &str, _body: &str) {}

#[cfg(target_os = "windows")]
mod win32_ffi {
    use std::ffi::{c_void, OsStr};
    use std::os::windows::ffi::OsStrExt;
    use std::path::Path;
    use std::ptr;
    use std::time::Duration;

    const PROCESS_SYNCHRONIZE: u32 = 0x0010_0000;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    const STARTF_USESHOWWINDOW: u32 = 0x0000_0001;
    const ERROR_ACCESS_DENIED: u32 = 5;
    const ERROR_ELEVATION_REQUIRED: u32 = 740;
    const SEE_MASK_NOCLOSEPROCESS: u32 = 0x0000_0040;
    const SW_HIDE: i32 = 0;
    const SW_SHOWNORMAL: i32 = 1;

    const HWND_MESSAGE: *mut c_void = (-3isize) as *mut c_void;
    const NIM_ADD: u32 = 0x0000_0000;
    const NIM_DELETE: u32 = 0x0000_0002;
    const NIF_ICON: u32 = 0x0000_0002;
    const NIF_TIP: u32 = 0x0000_0004;
    const NIF_INFO: u32 = 0x0000_0010;
    const NIIF_INFO: u32 = 0x0000_0001;
    const NIIF_RESPECT_QUIET_TIME: u32 = 0x0000_0080;
    const IDI_APPLICATION: *const u16 = 32512usize as *const u16;

    #[repr(C)]
    struct StartupInfoW {
        cb: u32,
        lp_reserved: *mut u16,
        lp_desktop: *mut u16,
        lp_title: *mut u16,
        dw_x: u32,
        dw_y: u32,
        dw_x_size: u32,
        dw_y_size: u32,
        dw_x_count_chars: u32,
        dw_y_count_chars: u32,
        dw_fill_attribute: u32,
        dw_flags: u32,
        w_show_window: u16,
        cb_reserved2: u16,
        lp_reserved2: *mut u8,
        h_std_input: *mut c_void,
        h_std_output: *mut c_void,
        h_std_error: *mut c_void,
    }

    #[repr(C)]
    struct ProcessInformation {
        h_process: *mut c_void,
        h_thread: *mut c_void,
        dw_process_id: u32,
        dw_thread_id: u32,
    }

    #[repr(C)]
    struct ShellExecuteInfoW {
        cb_size: u32,
        f_mask: u32,
        hwnd: *mut c_void,
        lp_verb: *const u16,
        lp_file: *const u16,
        lp_parameters: *const u16,
        lp_directory: *const u16,
        n_show: i32,
        h_inst_app: *mut c_void,
        lp_id_list: *mut c_void,
        lp_class: *const u16,
        hkey_class: *mut c_void,
        dw_hot_key: u32,
        h_icon_or_monitor: *mut c_void,
        h_process: *mut c_void,
    }

    #[repr(C)]
    struct Guid {
        data1: u32,
        data2: u16,
        data3: u16,
        data4: [u8; 8],
    }

    #[repr(C)]
    struct NotifyIconDataW {
        cb_size: u32,
        hwnd: *mut c_void,
        u_id: u32,
        u_flags: u32,
        u_callback_message: u32,
        h_icon: *mut c_void,
        sz_tip: [u16; 128],
        dw_state: u32,
        dw_state_mask: u32,
        sz_info: [u16; 256],
        u_timeout_or_version: u32,
        sz_info_title: [u16; 64],
        dw_info_flags: u32,
        guid_item: Guid,
        h_balloon_icon: *mut c_void,
    }

    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn OpenProcess(dw_desired_access: u32, b_inherit_handle: i32, dw_process_id: u32)
            -> *mut c_void;
        fn WaitForSingleObject(h_handle: *mut c_void, dw_milliseconds: u32) -> u32;
        fn CloseHandle(h_object: *mut c_void) -> i32;
        fn GetLastError() -> u32;
        fn CreateProcessW(
            lp_application_name: *const u16,
            lp_command_line: *mut u16,
            lp_process_attributes: *mut c_void,
            lp_thread_attributes: *mut c_void,
            b_inherit_handles: i32,
            dw_creation_flags: u32,
            lp_environment: *mut c_void,
            lp_current_directory: *const u16,
            lp_startup_info: *const StartupInfoW,
            lp_process_information: *mut ProcessInformation,
        ) -> i32;
    }

    #[link(name = "shell32")]
    unsafe extern "system" {
        fn ShellExecuteExW(p_exec_info: *mut ShellExecuteInfoW) -> i32;
        fn Shell_NotifyIconW(dw_message: u32, lp_data: *const NotifyIconDataW) -> i32;
        fn ExtractIconExW(
            lpsz_file: *const u16,
            n_icon_index: i32,
            phicon_large: *mut *mut c_void,
            phicon_small: *mut *mut c_void,
            n_icons: u32,
        ) -> u32;
    }

    #[link(name = "user32")]
    unsafe extern "system" {
        fn CreateWindowExW(
            dw_ex_style: u32,
            lp_class_name: *const u16,
            lp_window_name: *const u16,
            dw_style: u32,
            x: i32,
            y: i32,
            n_width: i32,
            n_height: i32,
            h_wnd_parent: *mut c_void,
            h_menu: *mut c_void,
            h_instance: *mut c_void,
            lp_param: *mut c_void,
        ) -> *mut c_void;
        fn DestroyWindow(h_wnd: *mut c_void) -> i32;
        fn DestroyIcon(h_icon: *mut c_void) -> i32;
        fn LoadIconW(h_instance: *mut c_void, lp_icon_name: *const u16) -> *mut c_void;
    }

    fn to_wide_z(s: &str) -> Vec<u16> {
        OsStr::new(s).encode_wide().chain(std::iter::once(0)).collect()
    }

    fn copy_wide_trunc(dst: &mut [u16], src: &str) {
        if dst.is_empty() {
            return;
        }
        let max_chars = dst.len() - 1;
        let mut i = 0;
        for u in OsStr::new(src).encode_wide() {
            if i >= max_chars {
                break;
            }
            dst[i] = u;
            i += 1;
        }
        dst[i] = 0;
    }

    pub fn wait_for_pid_exit(pid: u32, timeout_ms: u32) {
        unsafe {
            let h = OpenProcess(PROCESS_SYNCHRONIZE, 0, pid);
            if !h.is_null() {
                let _ = WaitForSingleObject(h, timeout_ms);
                let _ = CloseHandle(h);
            }
        }
    }

    pub fn wait_and_close_handle(raw_handle: usize, timeout_ms: u32) {
        let h = raw_handle as *mut c_void;
        if !h.is_null() {
            unsafe {
                let _ = WaitForSingleObject(h, timeout_ms);
                let _ = CloseHandle(h);
            }
        }
    }

    pub fn close_handle(raw_handle: usize) {
        let h = raw_handle as *mut c_void;
        if !h.is_null() {
            unsafe {
                let _ = CloseHandle(h);
            }
        }
    }

    pub fn shell_execute(
        verb: Option<&str>,
        file: &Path,
        params: Option<&str>,
        hidden: bool,
        want_process_handle: bool,
    ) -> Result<Option<usize>, String> {
        let wverb = verb.map(to_wide_z);
        let wfile = to_wide_z(&file.to_string_lossy());
        let wparams = params.map(to_wide_z);
        let wdir = file.parent().map(|p| to_wide_z(&p.to_string_lossy()));

        let mut sei = ShellExecuteInfoW {
            cb_size: std::mem::size_of::<ShellExecuteInfoW>() as u32,
            f_mask: if want_process_handle {
                SEE_MASK_NOCLOSEPROCESS
            } else {
                0
            },
            hwnd: ptr::null_mut(),
            lp_verb: wverb.as_ref().map_or(ptr::null(), |v| v.as_ptr()),
            lp_file: wfile.as_ptr(),
            lp_parameters: wparams.as_ref().map_or(ptr::null(), |p| p.as_ptr()),
            lp_directory: wdir.as_ref().map_or(ptr::null(), |d| d.as_ptr()),
            n_show: if hidden { SW_HIDE } else { SW_SHOWNORMAL },
            h_inst_app: ptr::null_mut(),
            lp_id_list: ptr::null_mut(),
            lp_class: ptr::null(),
            hkey_class: ptr::null_mut(),
            dw_hot_key: 0,
            h_icon_or_monitor: ptr::null_mut(),
            h_process: ptr::null_mut(),
        };

        let ok = unsafe { ShellExecuteExW(&mut sei) };
        if ok == 0 {
            let err = unsafe { GetLastError() };
            return Err(format!("Không thể khởi chạy tiến trình cập nhật (mã lỗi {err})."));
        }

        if want_process_handle && !sei.h_process.is_null() {
            Ok(Some(sei.h_process as usize))
        } else {
            if !sei.h_process.is_null() {
                unsafe {
                    let _ = CloseHandle(sei.h_process);
                }
            }
            Ok(None)
        }
    }

    pub fn launch_installer_silent(
        file: &Path,
        params: &str,
        force_elevate: bool,
    ) -> Result<Option<usize>, String> {
        if force_elevate {
            return shell_execute(Some("runas"), file, Some(params), true, true);
        }

        let cmd_line_str = if params.is_empty() {
            format!("\"{}\"", file.to_string_lossy())
        } else {
            format!("\"{}\" {}", file.to_string_lossy(), params)
        };
        let mut cmd_line = to_wide_z(&cmd_line_str);
        let wdir = file.parent().map(|p| to_wide_z(&p.to_string_lossy()));

        let si = StartupInfoW {
            cb: std::mem::size_of::<StartupInfoW>() as u32,
            lp_reserved: ptr::null_mut(),
            lp_desktop: ptr::null_mut(),
            lp_title: ptr::null_mut(),
            dw_x: 0,
            dw_y: 0,
            dw_x_size: 0,
            dw_y_size: 0,
            dw_x_count_chars: 0,
            dw_y_count_chars: 0,
            dw_fill_attribute: 0,
            dw_flags: STARTF_USESHOWWINDOW,
            w_show_window: SW_HIDE as u16,
            cb_reserved2: 0,
            lp_reserved2: ptr::null_mut(),
            h_std_input: ptr::null_mut(),
            h_std_output: ptr::null_mut(),
            h_std_error: ptr::null_mut(),
        };
        let mut pi = ProcessInformation {
            h_process: ptr::null_mut(),
            h_thread: ptr::null_mut(),
            dw_process_id: 0,
            dw_thread_id: 0,
        };

        let ok = unsafe {
            CreateProcessW(
                ptr::null(),
                cmd_line.as_mut_ptr(),
                ptr::null_mut(),
                ptr::null_mut(),
                0,
                CREATE_NO_WINDOW,
                ptr::null_mut(),
                wdir.as_ref().map_or(ptr::null(), |d| d.as_ptr()),
                &si,
                &mut pi,
            )
        };

        if ok != 0 {
            if !pi.h_thread.is_null() {
                unsafe {
                    let _ = CloseHandle(pi.h_thread);
                }
            }
            if !pi.h_process.is_null() {
                return Ok(Some(pi.h_process as usize));
            }
            return Ok(None);
        }

        let err = unsafe { GetLastError() };
        if err == ERROR_ELEVATION_REQUIRED || err == ERROR_ACCESS_DENIED {
            return shell_execute(Some("runas"), file, Some(params), true, true);
        }
        Err(format!("Không thể chạy bộ cài cập nhật (mã lỗi {err})."))
    }

    pub fn show_tray_balloon_notification(app_name: &str, title: &str, body: &str) {
        let class_name = to_wide_z("STATIC");
        let win_name = to_wide_z(app_name);
        let hwnd = unsafe {
            CreateWindowExW(
                0,
                class_name.as_ptr(),
                win_name.as_ptr(),
                0,
                0,
                0,
                0,
                0,
                HWND_MESSAGE,
                ptr::null_mut(),
                ptr::null_mut(),
                ptr::null_mut(),
            )
        };
        if hwnd.is_null() {
            return;
        }

        let mut extracted_icon: *mut c_void = ptr::null_mut();
        let mut owned_icon = false;
        if let Ok(exe) = std::env::current_exe() {
            let wexe = to_wide_z(&exe.to_string_lossy());
            let mut small: *mut c_void = ptr::null_mut();
            let count = unsafe { ExtractIconExW(wexe.as_ptr(), 0, ptr::null_mut(), &mut small, 1) };
            if count > 0 && !small.is_null() {
                extracted_icon = small;
                owned_icon = true;
            }
        }
        if extracted_icon.is_null() {
            extracted_icon = unsafe { LoadIconW(ptr::null_mut(), IDI_APPLICATION) };
        }

        let mut nid = NotifyIconDataW {
            cb_size: std::mem::size_of::<NotifyIconDataW>() as u32,
            hwnd,
            u_id: 0x2A01,
            u_flags: NIF_ICON | NIF_TIP | NIF_INFO,
            u_callback_message: 0,
            h_icon: extracted_icon,
            sz_tip: [0; 128],
            dw_state: 0,
            dw_state_mask: 0,
            sz_info: [0; 256],
            u_timeout_or_version: 5000,
            sz_info_title: [0; 64],
            dw_info_flags: NIIF_INFO | NIIF_RESPECT_QUIET_TIME,
            guid_item: Guid {
                data1: 0,
                data2: 0,
                data3: 0,
                data4: [0; 8],
            },
            h_balloon_icon: extracted_icon,
        };
        copy_wide_trunc(&mut nid.sz_tip, app_name);
        copy_wide_trunc(&mut nid.sz_info_title, title);
        copy_wide_trunc(&mut nid.sz_info, body);

        let added = unsafe { Shell_NotifyIconW(NIM_ADD, &nid) };
        if added != 0 {
            std::thread::sleep(Duration::from_secs(6));
            unsafe {
                let _ = Shell_NotifyIconW(NIM_DELETE, &nid);
            }
        }

        if owned_icon && !extracted_icon.is_null() {
            unsafe {
                let _ = DestroyIcon(extracted_icon);
            }
        }
        unsafe {
            let _ = DestroyWindow(hwnd);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signer, SigningKey};

    #[test]
    fn semver_comparison_works() {
        assert!(is_newer_version("2.0.0", "2.0.1"));
        assert!(is_newer_version("v2.0.0", "v2.1.0"));
        assert!(is_newer_version("2.0.9", "2.0.10"));
        assert!(!is_newer_version("2.0.0", "2.0.0"));
        assert!(!is_newer_version("2.0.1", "2.0.0"));
        assert!(!is_newer_version("2.0.0", "not-a-semver"));
    }

    #[test]
    fn ed25519_verification_accepts_valid_and_rejects_tampered() {
        let signing_key = SigningKey::from_bytes(&[7u8; 32]);
        let verifying_key = signing_key.verifying_key();
        let pub_b64 = base64::engine::general_purpose::STANDARD.encode(verifying_key.as_bytes());

        let payload = canonical_sign_payload(
            "optimizer2k",
            "2.0.1",
            "portable",
            "Optimizer2k.exe",
            5557248,
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        );
        let sig = signing_key.sign(payload.as_bytes());
        let sig_b64 = base64::engine::general_purpose::STANDARD.encode(sig.to_bytes());

        assert!(verify_ed25519_signature(
            &pub_b64,
            &sig_b64,
            "optimizer2k",
            "2.0.1",
            "portable",
            "Optimizer2k.exe",
            5557248,
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        .is_ok());

        // Cross-app substitution must fail
        assert!(verify_ed25519_signature(
            &pub_b64,
            &sig_b64,
            "tree2k",
            "2.0.1",
            "portable",
            "Optimizer2k.exe",
            5557248,
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        .is_err());

        // Tampered hash must fail
        assert!(verify_ed25519_signature(
            &pub_b64,
            &sig_b64,
            "optimizer2k",
            "2.0.1",
            "portable",
            "Optimizer2k.exe",
            5557248,
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        )
        .is_err());
    }

    #[test]
    fn file_entry_selection_prefers_matching_kind_and_falls_back() {
        let mut files = HashMap::new();
        files.insert(
            "windows-x86_64-portable".to_string(),
            UpdateFileEntry {
                kind: "portable".into(),
                platform: "Windows x64".into(),
                filename: "App.exe".into(),
                object_key: "builds/app/2.0.1/App.exe".into(),
                url: "https://builds.amri2k.com/builds/app/2.0.1/App.exe".into(),
                size: 100,
                sha256: "00".repeat(32),
                signature: None,
                silent_args: None,
            },
        );
        files.insert(
            "windows-x86_64-installer".to_string(),
            UpdateFileEntry {
                kind: "installer".into(),
                platform: "Windows x64".into(),
                filename: "App_2.0.1_x64-setup.exe".into(),
                object_key: "builds/app/2.0.1/App_2.0.1_x64-setup.exe".into(),
                url: "https://builds.amri2k.com/builds/app/2.0.1/App_2.0.1_x64-setup.exe".into(),
                size: 200,
                sha256: "11".repeat(32),
                signature: None,
                silent_args: Some(vec!["/S".into()]),
            },
        );

        let manifest = UpdateManifest {
            schema_version: 1,
            app: "app".into(),
            version: "2.0.1".into(),
            pub_date: "2026-11-23T00:00:00Z".into(),
            notes: vec![],
            files,
        };

        assert_eq!(select_file_entry(&manifest, "portable").unwrap().kind, "portable");
        assert_eq!(select_file_entry(&manifest, "installer").unwrap().kind, "installer");
    }

    #[test]
    fn xml_escape_handles_special_chars_and_vietnamese() {
        assert_eq!(
            xml_escape("Có bản mới <2.0> & \"tốt\""),
            "Có bản mới &lt;2.0&gt; &amp; &quot;tốt&quot;"
        );
    }

    #[test]
    fn installer_command_builder_supports_nsis_inno_and_msi() {
        let dir = Path::new(r"C:\Apps\Demo2k");
        let nsis_entry = UpdateFileEntry {
            kind: "installer".into(),
            platform: "Windows x64".into(),
            filename: "Demo2k_2.0.1_x64-setup.exe".into(),
            object_key: "builds/demo2k/2.0.1/Demo2k_2.0.1_x64-setup.exe".into(),
            url: "".into(),
            size: 1,
            sha256: "00".repeat(32),
            signature: None,
            silent_args: Some(vec!["/S".into()]),
        };
        let (f_nsis, a_nsis) =
            build_installer_command_and_args(Path::new(r"C:\tmp\setup.exe"), &nsis_entry, dir);
        assert_eq!(f_nsis, PathBuf::from(r"C:\tmp\setup.exe"));
        assert_eq!(a_nsis, r"/S /D=C:\Apps\Demo2k");

        let inno_entry = UpdateFileEntry {
            silent_args: Some(vec!["/VERYSILENT".into(), "/NORESTART".into()]),
            ..nsis_entry.clone()
        };
        let (_, a_inno) =
            build_installer_command_and_args(Path::new(r"C:\tmp\inno.exe"), &inno_entry, dir);
        assert_eq!(a_inno, "/VERYSILENT /NORESTART");

        let (f_msi, a_msi) =
            build_installer_command_and_args(Path::new(r"C:\tmp\app setup.msi"), &nsis_entry, dir);
        assert!(f_msi.to_string_lossy().to_ascii_lowercase().ends_with("msiexec.exe"));
        assert_eq!(a_msi, r#"/i "C:\tmp\app setup.msi" /qn /norestart"#);
    }

    #[test]
    fn portable_swap_replaces_target_atomically() {
        let tmp_dir = std::env::temp_dir().join(format!("2k-swap-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&tmp_dir);
        fs::create_dir_all(&tmp_dir).unwrap();
        let target = tmp_dir.join("App.exe");
        let staged = tmp_dir.join("App-new.exe");
        fs::write(&target, b"old-binary").unwrap();
        fs::write(&staged, b"new-binary-v2").unwrap();

        swap_portable_binary(&staged, &target).unwrap();
        assert_eq!(fs::read(&target).unwrap(), b"new-binary-v2");
        assert!(!append_file_suffix(&target, ".new").exists());
        let _ = fs::remove_dir_all(&tmp_dir);
    }
}
