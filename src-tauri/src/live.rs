use std::collections::{HashMap, HashSet};
use std::num::NonZeroUsize;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use lru::LruCache;
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use strsim::normalized_levenshtein;
use tauri::{AppHandle, Emitter};

use crate::capture::{capture_region, signature_differs};
use crate::config::{AppConfig, SavedLiveRegion};
use crate::constants::LIVE_REGION_LIMIT;
use crate::desktop_apps::{foreground_application_id, InputTriggerMonitor};
use crate::inpaint::reconstruct_layout;
use crate::ocr::{merge_regions_into_blocks, merge_regions_into_lines, ocr_layout};
use crate::overlay_win32::{OverlayItem, OverlayManager};
use crate::translate::{translate_regions, TranslateParams};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LiveRegionInfo {
    pub id: u64,
    pub bbox: [i32; 4],
    pub mode: String,
    pub output: Option<[i32; 4]>,
    pub last_text: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LiveStatePayload {
    pub running: bool,
    pub paused_by_focus: bool,
    pub regions: Vec<LiveRegionInfo>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LiveFrameUpdate {
    pub region_id: u64,
    pub number: usize,
    pub text: String,
    pub bbox: [i32; 4],
    pub output: Option<[i32; 4]>,
}

struct RegionRuntimeState {
    prev_sig: Option<Vec<u8>>,
    last_sig: Option<Vec<u8>>,
    animating_frames: u32,
    last_ocr_at: Instant,
    empty_frames: u32,
    has_output: bool,
    unstable: HashSet<String>,
    held_frames: u32,
    translated_once: bool,
}

impl Default for RegionRuntimeState {
    fn default() -> Self {
        Self {
            prev_sig: None,
            last_sig: None,
            animating_frames: 0,
            last_ocr_at: Instant::now() - Duration::from_secs(60),
            empty_frames: 0,
            has_output: false,
            unstable: HashSet::new(),
            held_frames: 0,
            translated_once: false,
        }
    }
}

fn normalize_live_key(text: &str) -> String {
    let mapped: String = text
        .chars()
        .map(|c| match c {
            '！' => '!',
            '？' => '?',
            '，' => ',',
            '。' => '.',
            '：' => ':',
            '；' => ';',
            '（' => '(',
            '）' => ')',
            '「' | '」' | '『' | '』' => '"',
            '　' => ' ',
            other => other,
        })
        .collect();
    mapped.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn digits_only(text: &str) -> String {
    text.chars().filter(|c| c.is_ascii_digit()).collect()
}

fn fuzzy_memo_lookup(memo: &LruCache<String, String>, text: &str) -> Option<String> {
    let has_cjk = text.chars().any(|c| (c as u32) >= 0x2E80);
    let min_len = if has_cjk { 3 } else { 6 };
    let text_len = text.chars().count();
    if text_len < min_len || memo.is_empty() {
        return None;
    }
    let d = digits_only(text);
    let mut best_score = 0.90f64;
    let mut best: Option<String> = None;
    for (src, translated) in memo.iter() {
        let src_len = src.chars().count();
        if src_len.abs_diff(text_len) > ((text_len as f64 * 0.12) as usize + 1) {
            continue;
        }
        if digits_only(src) != d {
            continue;
        }
        let ratio = normalized_levenshtein(src, text);
        if ratio >= best_score {
            best_score = ratio;
            best = Some(translated.clone());
        }
    }
    best
}

pub struct LiveController {
    next_id: AtomicU64,
    running: Arc<AtomicBool>,
    paused_by_focus: Arc<AtomicBool>,
    force_rescan: Arc<AtomicBool>,
    regions: Arc<Mutex<Vec<LiveRegionInfo>>>,
    overlays: Arc<OverlayManager>,
}

impl LiveController {
    pub fn new(initial: &[SavedLiveRegion], overlays: Arc<OverlayManager>) -> Self {
        let mut regions = Vec::new();
        let mut id = 1u64;
        for saved in initial.iter().take(LIVE_REGION_LIMIT) {
            regions.push(LiveRegionInfo {
                id,
                bbox: saved.bbox,
                mode: saved.mode.clone(),
                output: saved.output,
                last_text: String::new(),
            });
            id += 1;
        }
        Self {
            next_id: AtomicU64::new(id),
            running: Arc::new(AtomicBool::new(false)),
            paused_by_focus: Arc::new(AtomicBool::new(false)),
            force_rescan: Arc::new(AtomicBool::new(false)),
            regions: Arc::new(Mutex::new(regions)),
            overlays,
        }
    }

    pub fn is_running(&self) -> bool {
        self.running.load(Ordering::Relaxed)
    }

    pub fn snapshot(&self) -> LiveStatePayload {
        LiveStatePayload {
            running: self.is_running(),
            paused_by_focus: self.paused_by_focus.load(Ordering::Relaxed),
            regions: self.regions.lock().clone(),
        }
    }

    pub fn saved_regions(&self) -> Vec<SavedLiveRegion> {
        self.regions
            .lock()
            .iter()
            .map(|r| SavedLiveRegion {
                bbox: r.bbox,
                mode: r.mode.clone(),
                output: r.output,
            })
            .collect()
    }

    pub fn add_region(&self, bbox: [i32; 4], mode: &str) -> Result<LiveRegionInfo, String> {
        let mut guard = self.regions.lock();
        if guard.len() >= LIVE_REGION_LIMIT {
            return Err(format!("Đã đạt giới hạn tối đa {LIVE_REGION_LIMIT} vùng Live."));
        }
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let info = LiveRegionInfo {
            id,
            bbox,
            mode: if mode == "frame" {
                "frame".to_string()
            } else {
                "overlay".to_string()
            },
            output: None,
            last_text: String::new(),
        };
        guard.push(info.clone());
        Ok(info)
    }

    pub fn remove_region(&self, id: u64) {
        self.regions.lock().retain(|r| r.id != id);
        self.overlays.close(&format!("live-{id}"));
    }

    pub fn clear_regions(&self) {
        let ids: Vec<u64> = self.regions.lock().iter().map(|r| r.id).collect();
        self.regions.lock().clear();
        for id in ids {
            self.overlays.close(&format!("live-{id}"));
        }
    }

    pub fn update_region_bbox(&self, id: u64, bbox: [i32; 4]) -> Option<LiveRegionInfo> {
        let mut guard = self.regions.lock();
        if let Some(r) = guard.iter_mut().find(|r| r.id == id) {
            r.bbox = bbox;
            self.overlays.close(&format!("live-{id}"));
            return Some(r.clone());
        }
        None
    }

    pub fn update_region_output(&self, id: u64, rect: [i32; 4]) {
        if let Some(r) = self.regions.lock().iter_mut().find(|r| r.id == id) {
            r.output = Some(rect);
        }
    }

    pub fn force_rescan(&self) {
        self.force_rescan.store(true, Ordering::Relaxed);
    }

    pub fn stop(&self, app: &AppHandle) {
        self.running.store(false, Ordering::Relaxed);
        self.paused_by_focus.store(false, Ordering::Relaxed);
        let ids: Vec<u64> = self.regions.lock().iter().map(|r| r.id).collect();
        for id in ids {
            self.overlays.close(&format!("live-{id}"));
        }
        let _ = app.emit("live-state", self.snapshot());
    }

    pub fn start(&self, app: AppHandle, config_arc: Arc<Mutex<AppConfig>>) -> Result<(), String> {
        if self.regions.lock().is_empty() {
            return Err("Chưa có vùng Live nào. Hãy thêm vùng trước khi bắt đầu.".to_string());
        }
        if self.running.swap(true, Ordering::SeqCst) {
            return Ok(());
        }

        let running = self.running.clone();
        let paused_by_focus = self.paused_by_focus.clone();
        let force_rescan = self.force_rescan.clone();
        let regions_arc = self.regions.clone();
        let overlays = self.overlays.clone();

        let _ = app.emit("live-state", self.snapshot());

        tauri::async_runtime::spawn(async move {
            let mut memo: LruCache<String, String> =
                LruCache::new(NonZeroUsize::new(512).unwrap());
            let mut states: HashMap<u64, RegionRuntimeState> = HashMap::new();
            let mut input_mon = InputTriggerMonitor::new();
            let mut last_auto_tick = Instant::now() - Duration::from_secs(10);

            while running.load(Ordering::Relaxed) {
                let cfg = config_arc.lock().clone();
                let focus_id = cfg.live_focus_app_id.trim().to_lowercase();
                if !focus_id.is_empty() {
                    let cur_fg = foreground_application_id();
                    if cur_fg != focus_id {
                        if !paused_by_focus.swap(true, Ordering::Relaxed) {
                            let _ = app.emit(
                                "live-state",
                                LiveStatePayload {
                                    running: true,
                                    paused_by_focus: true,
                                    regions: regions_arc.lock().clone(),
                                },
                            );
                        }
                        tokio::time::sleep(Duration::from_millis(200)).await;
                        continue;
                    } else if paused_by_focus.swap(false, Ordering::Relaxed) {
                        let _ = app.emit(
                            "live-state",
                            LiveStatePayload {
                                running: true,
                                paused_by_focus: false,
                                regions: regions_arc.lock().clone(),
                            },
                        );
                    }
                }

                let forced = force_rescan.swap(false, Ordering::Relaxed);
                let input_hit = input_mon.poll_triggered();
                let interval = Duration::from_millis(cfg.live_interval_ms.clamp(300, 5000) as u64);
                let auto_due = last_auto_tick.elapsed() >= interval;

                let should_scan = match cfg.live_trigger_mode.as_str() {
                    "input" => forced || input_hit,
                    "auto" => forced || auto_due,
                    _ => forced || input_hit || auto_due, // hybrid
                };

                if !should_scan {
                    tokio::time::sleep(Duration::from_millis(30)).await;
                    continue;
                }
                if input_hit {
                    // Brief pause for game text fade-in after click/Enter/Space
                    tokio::time::sleep(Duration::from_millis(90)).await;
                }
                last_auto_tick = Instant::now();

                let snapshot_regions = regions_arc.lock().clone();
                if snapshot_regions.is_empty() {
                    running.store(false, Ordering::Relaxed);
                    break;
                }

                let (service, llm_endpoint, llm_api_key, llm_model) = cfg.resolve_llm();
                let tparams = TranslateParams {
                    service,
                    target: cfg.target_language.clone(),
                    llm_endpoint,
                    llm_api_key,
                    llm_model,
                    glossary: cfg.translation_glossary.clone(),
                };

                for (idx, region) in snapshot_regions.iter().enumerate() {
                    if !running.load(Ordering::Relaxed) {
                        break;
                    }
                    let st = states.entry(region.id).or_default();
                    let Ok(frame) = capture_region(region.bbox) else {
                        continue;
                    };

                    if !forced {
                        if let Some(ref prev) = st.prev_sig {
                            if !signature_differs(prev, &frame.signature) {
                                st.last_sig = Some(frame.signature);
                                st.animating_frames = 0;
                                continue;
                            }
                        }
                        if let Some(ref last) = st.last_sig {
                            if signature_differs(last, &frame.signature)
                                && st.animating_frames < 4
                                && st.last_ocr_at.elapsed() < interval
                            {
                                st.last_sig = Some(frame.signature);
                                st.animating_frames += 1;
                                continue;
                            }
                        }
                    }

                    st.last_sig = Some(frame.signature.clone());
                    st.prev_sig = Some(frame.signature);
                    st.animating_frames = 0;
                    st.last_ocr_at = Instant::now();

                    let img = frame.image;
                    let ocr_lang = cfg.ocr_language.clone();
                    let ocr_engine = cfg.ocr_engine.clone();
                    let ocr_model = cfg.ocr_model.clone();
                    let ocr_backend = cfg.ocr_backend.clone();

                    let raw_regions = match tokio::task::spawn_blocking({
                        let img = img.clone();
                        move || ocr_layout(&img, &ocr_lang, &ocr_engine, &ocr_model, &ocr_backend, false)
                    })
                    .await
                    {
                        Ok(Ok(regs)) => regs,
                        _ => continue,
                    };

                    let merged = if region.mode == "overlay" {
                        merge_regions_into_blocks(&raw_regions)
                    } else {
                        merge_regions_into_lines(&raw_regions)
                    };

                    if merged.is_empty() {
                        st.empty_frames += 1;
                        if st.has_output && st.empty_frames >= 2 {
                            st.has_output = false;
                            if region.mode == "overlay" {
                                overlays.close(&format!("live-{}", region.id));
                            } else {
                                let _ = app.emit(
                                    "live-frame-text",
                                    LiveFrameUpdate {
                                        region_id: region.id,
                                        number: idx + 1,
                                        text: String::new(),
                                        bbox: region.bbox,
                                        output: region.output,
                                    },
                                );
                            }
                        }
                        continue;
                    }
                    st.empty_frames = 0;

                    // Resolve cached / fuzzy / uncached translations
                    let mut out_texts: Vec<Option<String>> = vec![None; merged.len()];
                    let mut to_translate_idx = Vec::new();
                    let mut to_translate_regs = Vec::new();
                    let mut new_unstable = HashSet::new();

                    for (ri, reg) in merged.iter().enumerate() {
                        let key = normalize_live_key(&reg.text);
                        if let Some(hit) = memo.get(&key) {
                            out_texts[ri] = Some(hit.clone());
                        } else if let Some(fuzzy) = fuzzy_memo_lookup(&memo, &key) {
                            out_texts[ri] = Some(fuzzy);
                        } else if !forced
                            && st.translated_once
                            && st.held_frames < 2
                            && !st.unstable.contains(&key)
                        {
                            new_unstable.insert(key);
                        } else {
                            to_translate_idx.push((ri, key));
                            to_translate_regs.push(reg.clone());
                        }
                    }

                    if !new_unstable.is_empty() && to_translate_regs.is_empty() {
                        st.unstable = new_unstable;
                        st.held_frames += 1;
                        continue;
                    }
                    st.unstable.clear();
                    st.held_frames = 0;

                    if !to_translate_regs.is_empty() {
                        match translate_regions(&to_translate_regs, &tparams).await {
                            Ok(translated) => {
                                for ((ri, key), tr) in
                                    to_translate_idx.into_iter().zip(translated.into_iter())
                                {
                                    memo.put(key, tr.clone());
                                    out_texts[ri] = Some(tr);
                                }
                            }
                            Err(err) => {
                                let _ = app.emit("app-status", serde_json::json!({
                                    "text": err,
                                    "state": "error"
                                }));
                                continue;
                            }
                        }
                    }

                    let final_texts: Vec<String> = out_texts
                        .into_iter()
                        .enumerate()
                        .map(|(i, opt)| opt.unwrap_or_else(|| merged[i].text.clone()))
                        .collect();
                    st.translated_once = true;
                    st.has_output = true;

                    let joined = final_texts.join("\n");
                    if let Some(r) = regions_arc.lock().iter_mut().find(|r| r.id == region.id) {
                        r.last_text = joined.clone();
                    }

                    if region.mode == "overlay" {
                        let ((sw, sh), visuals) = reconstruct_layout(&img, &merged);
                        let items: Vec<OverlayItem> = merged
                            .iter()
                            .zip(visuals.into_iter())
                            .zip(final_texts.into_iter())
                            .map(|((reg, vis), text)| OverlayItem {
                                bbox: reg.bbox,
                                text,
                                source_text: reg.text.clone(),
                                bg: vis.bg,
                                fg: vis.fg,
                                patch_rect: Some(vis.rect),
                                patch_rgb: vis.patch_rgb,
                                patch_size: vis.patch_size,
                                ink_rect: vis.ink_rect,
                                stroke_thickness: vis.stroke_thickness,
                                source_lines: reg.line_count,
                                line_ink: vis.line_ink,
                                outline: vis.outline,
                                align: reg.align.clone(),
                                room: vis.room,
                            })
                            .collect();
                        overlays.show(&format!("live-{}", region.id), region.bbox, (sw, sh), items);
                    } else {
                        let _ = app.emit(
                            "live-frame-text",
                            LiveFrameUpdate {
                                region_id: region.id,
                                number: idx + 1,
                                text: joined,
                                bbox: region.bbox,
                                output: region.output,
                            },
                        );
                    }
                }
            }

            let _ = app.emit(
                "live-state",
                LiveStatePayload {
                    running: false,
                    paused_by_focus: false,
                    regions: regions_arc.lock().clone(),
                },
            );
        });

        Ok(())
    }
}
