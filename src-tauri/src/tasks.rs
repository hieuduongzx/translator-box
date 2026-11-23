use std::collections::HashSet;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct OcrDownloadProgressEvent {
    pub model_id: String,
    pub model_label: String,
    pub file_index: usize,
    pub file_total: usize,
    pub current_file: String,
    pub downloaded_bytes: u64,
    pub total_bytes: u64,
    pub percent: f64,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct OcrTaskSnapshot {
    pub downloading_model_id: Option<String>,
    pub download_progress: Option<OcrDownloadProgressEvent>,
    pub last_error: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TranslateTaskSnapshot {
    pub busy: bool,
    pub action: Option<String>,
    pub status_text: Option<String>,
    pub last_source: Option<String>,
    pub last_result: Option<String>,
    pub last_image_data_url: Option<String>,
    pub last_error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TaskSnapshotDto {
    pub active_tasks: Vec<String>,
    pub ocr: OcrTaskSnapshot,
    pub translate: TranslateTaskSnapshot,
}

pub struct TaskGuard {
    key: String,
    active: Arc<Mutex<HashSet<String>>>,
}

impl Drop for TaskGuard {
    fn drop(&mut self) {
        self.active.lock().remove(&self.key);
    }
}

pub struct TaskRegistry {
    active: Arc<Mutex<HashSet<String>>>,
    ocr_cancel: Arc<AtomicBool>,
}

impl Default for TaskRegistry {
    fn default() -> Self {
        Self::new()
    }
}

impl TaskRegistry {
    pub fn new() -> Self {
        Self {
            active: Arc::new(Mutex::new(HashSet::new())),
            ocr_cancel: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn try_acquire(&self, key: &str) -> Option<TaskGuard> {
        self.try_acquire_exclusive(key, &[key])
    }

    pub fn try_acquire_exclusive(&self, key: &str, conflicts: &[&str]) -> Option<TaskGuard> {
        let mut set = self.active.lock();
        if set.contains(key) || conflicts.iter().any(|c| set.contains(*c)) {
            return None;
        }
        set.insert(key.to_string());
        Some(TaskGuard {
            key: key.to_string(),
            active: self.active.clone(),
        })
    }

    pub fn active_keys(&self) -> Vec<String> {
        let mut keys: Vec<String> = self.active.lock().iter().cloned().collect();
        keys.sort();
        keys
    }

    pub fn reset_cancel(&self, scope: &str) -> Arc<AtomicBool> {
        let token = self.cancel_token(scope);
        token.store(false, Ordering::SeqCst);
        token
    }

    pub fn cancel_token(&self, scope: &str) -> Arc<AtomicBool> {
        match scope {
            "ocr" => self.ocr_cancel.clone(),
            _ => self.ocr_cancel.clone(),
        }
    }

    pub fn cancel(&self, scope: Option<&str>) {
        match scope {
            Some("ocr") | None => self.ocr_cancel.store(true, Ordering::SeqCst),
            _ => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn duplicate_guard_blocks_second_acquire_and_releases_on_drop() {
        let reg = TaskRegistry::new();
        let g1 = reg.try_acquire("ocr:download");
        assert!(g1.is_some());
        assert!(reg.try_acquire("ocr:download").is_none());
        assert_eq!(reg.active_keys(), vec!["ocr:download".to_string()]);
        drop(g1);
        assert!(reg.active_keys().is_empty());
        assert!(reg.try_acquire("ocr:download").is_some());
    }

    #[test]
    fn exclusive_guard_blocks_conflicting_task_but_allows_unrelated() {
        let reg = TaskRegistry::new();
        let g_action =
            reg.try_acquire_exclusive("translate:action", &["translate:action", "live:select"]);
        assert!(g_action.is_some());
        assert!(reg
            .try_acquire_exclusive("live:select", &["translate:action", "live:select"])
            .is_none());

        let g_ocr = reg.try_acquire("ocr:download");
        assert!(g_ocr.is_some());

        drop(g_action);
        assert!(reg
            .try_acquire_exclusive("live:select", &["translate:action", "live:select"])
            .is_some());
    }

    #[test]
    fn ocr_cancel_flag_resets_and_sets() {
        let reg = TaskRegistry::new();
        let token = reg.reset_cancel("ocr");
        assert!(!token.load(Ordering::SeqCst));
        reg.cancel(Some("ocr"));
        assert!(token.load(Ordering::SeqCst));
        let token2 = reg.reset_cancel("ocr");
        assert!(!token2.load(Ordering::SeqCst));
    }
}
