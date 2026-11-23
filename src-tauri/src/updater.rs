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

        if let Err(err) = spawn_apply_helper(&self.config.slug, &staged_path, &pending.entry, relaunch) {
            self.apply_triggered.store(false, Ordering::SeqCst);
            self.set_error(&err);
            return Err(err);
        }

        if relaunch {
            // Give frontend a brief moment to paint "Đang áp dụng...", then exit cleanly.
            let app = self.app.clone();
            tauri::async_runtime::spawn(async move {
                tokio::time::sleep(Duration::from_millis(180)).await;
                app.exit(0);
            });
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
    if let Ok(exe) = std::env::current_exe() {
        let mut old_os = exe.as_os_str().to_os_string();
        old_os.push(".old");
        let old_path = PathBuf::from(old_os);
        if old_path.is_file() {
            let _ = fs::remove_file(&old_path);
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

fn ps_single_quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', "''"))
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

fn spawn_apply_helper(
    slug: &str,
    staged_path: &Path,
    entry: &UpdateFileEntry,
    relaunch: bool,
) -> Result<(), String> {
    let current_exe = std::env::current_exe()
        .map_err(|e| format!("Không xác định được đường dẫn ứng dụng đang chạy: {e}"))?;
    let target_dir = current_exe
        .parent()
        .ok_or_else(|| "Không xác định được thư mục chứa ứng dụng.".to_string())?;
    let pid = std::process::id();
    let relaunch_flag = if relaunch { "1" } else { "0" };

    let script_path = std::env::temp_dir().join(format!("{slug}-apply-update-{pid}.ps1"));
    let script_body = if entry.kind.eq_ignore_ascii_case("installer") {
        let is_msi = staged_path
            .extension()
            .is_some_and(|e| e.eq_ignore_ascii_case("msi"));
        let custom_args = entry.silent_args.clone().unwrap_or_default();
        let custom_args_ps = custom_args
            .iter()
            .map(|a| ps_single_quote(a))
            .collect::<Vec<_>>()
            .join(", ");

        format!(
            r#"$ErrorActionPreference = 'SilentlyContinue'
$OldPid = {pid}
$Staged = {staged}
$TargetExe = {target_exe}
$TargetDir = {target_dir}
$Relaunch = {relaunch_flag}
$IsMsi = {is_msi}
$CustomArgs = @({custom_args_ps})

try {{ Wait-Process -Id $OldPid -Timeout 25 -ErrorAction SilentlyContinue }} catch {{}}
Start-Sleep -Milliseconds 400

if (Test-Path -LiteralPath $Staged) {{
    if ($IsMsi) {{
        Start-Process -FilePath 'msiexec.exe' -ArgumentList @('/i', $Staged, '/qn', '/norestart') -Wait -WindowStyle Hidden
    }} else {{
        $argsList = if ($CustomArgs.Count -gt 0) {{ $CustomArgs }} else {{ @('/S') }}
        $hasD = $false
        foreach ($a in $argsList) {{ if ($a -like '/D=*') {{ $hasD = $true }} }}
        if (-not $hasD -and $TargetDir) {{
            $argsList = $argsList + @("/D=$TargetDir")
        }}
        Start-Process -FilePath $Staged -ArgumentList $argsList -Wait -WindowStyle Hidden
    }}
    Remove-Item -LiteralPath $Staged -Force -ErrorAction SilentlyContinue
}}

if ($Relaunch -eq 1 -and (Test-Path -LiteralPath $TargetExe)) {{
    Start-Process -FilePath $TargetExe
}}

Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
"#,
            pid = pid,
            staged = ps_single_quote(&staged_path.to_string_lossy()),
            target_exe = ps_single_quote(&current_exe.to_string_lossy()),
            target_dir = ps_single_quote(&target_dir.to_string_lossy()),
            relaunch_flag = relaunch_flag,
            is_msi = if is_msi { "$true" } else { "$false" },
            custom_args_ps = custom_args_ps,
        )
    } else {
        // Portable single-file exe atomic swap with automatic rollback on failure.
        format!(
            r#"$ErrorActionPreference = 'Stop'
$OldPid = {pid}
$Staged = {staged}
$TargetExe = {target_exe}
$NewTmp = "$TargetExe.new"
$OldBak = "$TargetExe.old"
$Relaunch = {relaunch_flag}

try {{ Wait-Process -Id $OldPid -Timeout 25 -ErrorAction SilentlyContinue }} catch {{}}
Start-Sleep -Milliseconds 350

try {{
    Copy-Item -LiteralPath $Staged -Destination $NewTmp -Force

    $movedOld = $false
    for ($i = 0; $i -lt 15; $i++) {{
        try {{
            if (Test-Path -LiteralPath $OldBak) {{
                Remove-Item -LiteralPath $OldBak -Force -ErrorAction SilentlyContinue
            }}
            if (Test-Path -LiteralPath $TargetExe) {{
                Move-Item -LiteralPath $TargetExe -Destination $OldBak -Force
            }}
            $movedOld = $true
            break
        }} catch {{
            Start-Sleep -Milliseconds 300
        }}
    }}

    if (-not $movedOld) {{
        throw "Could not release running executable"
    }}

    try {{
        Move-Item -LiteralPath $NewTmp -Destination $TargetExe -Force
    }} catch {{
        if (Test-Path -LiteralPath $OldBak) {{
            Move-Item -LiteralPath $OldBak -Destination $TargetExe -Force -ErrorAction SilentlyContinue
        }}
        throw
    }}

    Remove-Item -LiteralPath $OldBak -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $Staged -Force -ErrorAction SilentlyContinue
}} catch {{
    Remove-Item -LiteralPath $NewTmp -Force -ErrorAction SilentlyContinue
}}

if ($Relaunch -eq 1 -and (Test-Path -LiteralPath $TargetExe)) {{
    Start-Process -FilePath $TargetExe
}}

Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
"#,
            pid = pid,
            staged = ps_single_quote(&staged_path.to_string_lossy()),
            target_exe = ps_single_quote(&current_exe.to_string_lossy()),
            relaunch_flag = relaunch_flag,
        )
    };

    // Write with UTF-8 BOM so Windows PowerShell 5.1 reads Unicode paths correctly.
    let mut bytes = Vec::with_capacity(script_body.len() + 3);
    bytes.extend_from_slice(&[0xEF, 0xBB, 0xBF]);
    bytes.extend_from_slice(script_body.as_bytes());
    fs::write(&script_path, bytes)
        .map_err(|e| format!("Không tạo được script cài cập nhật: {e}"))?;

    let needs_uac = !entry.kind.eq_ignore_ascii_case("installer") && !can_write_directory(target_dir);

    #[cfg(target_os = "windows")]
    {
        if needs_uac {
            spawn_powershell_elevated(&script_path)?;
        } else {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            std::process::Command::new("powershell.exe")
                .args([
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-WindowStyle",
                    "Hidden",
                    "-File",
                ])
                .arg(&script_path)
                .creation_flags(CREATE_NO_WINDOW)
                .spawn()
                .map_err(|e| format!("Không chạy được tiến trình cập nhật: {e}"))?;
        }
    }

    #[cfg(not(target_os = "windows"))]
    {
        let _ = (needs_uac, script_path);
        return Err("Tự cập nhật hiện chỉ hỗ trợ Windows.".to_string());
    }

    Ok(())
}

#[cfg(target_os = "windows")]
fn spawn_powershell_elevated(script_path: &Path) -> Result<(), String> {
    let args = format!(
        "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File \"{}\"",
        script_path.to_string_lossy()
    );
    let ps_cmd = format!(
        "Start-Process -FilePath 'powershell.exe' -Verb RunAs -WindowStyle Hidden -ArgumentList {}",
        ps_single_quote(&args)
    );
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    std::process::Command::new("powershell.exe")
        .args(["-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", &ps_cmd])
        .creation_flags(CREATE_NO_WINDOW)
        .spawn()
        .map_err(|e| format!("Không thể yêu cầu quyền Admin để cập nhật: {e}"))?;
    Ok(())
}

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

/// Shows a native Windows 10/11 system toast notification (works for both portable & installed
/// apps, including when minimized to the system tray) via per-user HKCU AppUserModelId + WinRT.
#[cfg(target_os = "windows")]
fn show_windows_toast(slug: &str, app_name: &str, title: &str, body: &str) {
    let aumid = format!("com.{}.app", slug.to_ascii_lowercase());
    let toast_xml = format!(
        "<toast><visual><binding template=\"ToastGeneric\"><text>{}</text><text>{}</text></binding></visual></toast>",
        xml_escape(title),
        xml_escape(body),
    );
    let script = format!(
        r#"$ErrorActionPreference = 'SilentlyContinue'
$aumid = {aumid}
$regPath = "HKCU:\Software\Classes\AppUserModelId\$aumid"
if (-not (Test-Path $regPath)) {{ New-Item -Path $regPath -Force | Out-Null }}
Set-ItemProperty -Path $regPath -Name 'DisplayName' -Value {app_name}
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml({toast_xml})
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($aumid).Show($toast)
"#,
        aumid = ps_single_quote(&aumid),
        app_name = ps_single_quote(app_name),
        toast_xml = ps_single_quote(&toast_xml),
    );

    // UTF-16LE Base64 for PowerShell -EncodedCommand preserves full Vietnamese Unicode.
    let utf16_bytes: Vec<u8> = script
        .encode_utf16()
        .flat_map(|u| u.to_le_bytes())
        .collect();
    let encoded = base64::engine::general_purpose::STANDARD.encode(utf16_bytes);

    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let _ = std::process::Command::new("powershell.exe")
        .args([
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-EncodedCommand",
            &encoded,
        ])
        .creation_flags(CREATE_NO_WINDOW)
        .spawn();
}

#[cfg(not(target_os = "windows"))]
fn show_windows_toast(_slug: &str, _app_name: &str, _title: &str, _body: &str) {}

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
}
