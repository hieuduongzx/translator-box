use std::collections::{HashMap, VecDeque};
use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use futures_util::StreamExt;
use image::{imageops, RgbImage};
use ndarray::Array4;
use once_cell::sync::Lazy;
use ort::session::{builder::GraphOptimizationLevel, Session};
use ort::value::Tensor;
use parking_lot::Mutex;
use regex::Regex;
use serde::{Deserialize, Serialize};

use crate::config::config_dir;
use crate::ocr::{OcrEngineStatusInfo, TextRegion};
use crate::tasks::OcrDownloadProgressEvent;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OcrModelInfo {
    pub id: String,
    pub label: String,
    pub languages: String,
    pub size_mb: f32,
    pub installed: bool,
    pub det_filename: String,
    pub rec_filename: String,
    pub dict_filename: String,
}

struct ModelSpec {
    id: &'static str,
    label: &'static str,
    languages: &'static str,
    size_mb: f32,
    det_file: &'static str,
    rec_file: &'static str,
    dict_file: &'static str,
    det_url: &'static str,
    rec_url: &'static str,
    dict_url: &'static str,
}

const MODEL_SPECS: &[ModelSpec] = &[
    ModelSpec {
        id: "ppocrv5_mobile",
        label: "PP-OCRv5 mobile",
        languages: "Trung giản thể/phồn thể, Anh, Nhật",
        size_mb: 17.7,
        det_file: "ch_PP-OCRv5_det_mobile.onnx",
        rec_file: "ch_PP-OCRv5_rec_mobile.onnx",
        dict_file: "ppocrv5_dict.txt",
        det_url: "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv5/det/ch_PP-OCRv5_det_mobile.onnx",
        rec_url: "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv5/rec/ch_PP-OCRv5_rec_mobile.onnx",
        dict_url: "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/paddle/PP-OCRv5/rec/ch_PP-OCRv5_rec_mobile/ppocrv5_dict.txt",
    },
    ModelSpec {
        id: "ppocrv6_tiny",
        label: "PP-OCRv6 tiny",
        languages: "49 ngôn ngữ (không gồm tiếng Nhật)",
        size_mb: 5.45,
        det_file: "PP-OCRv6_det_tiny.onnx",
        rec_file: "PP-OCRv6_rec_tiny.onnx",
        dict_file: "ppocrv6_tiny_dict.txt",
        det_url: "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv6/det/PP-OCRv6_det_tiny.onnx",
        rec_url: "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv6/rec/PP-OCRv6_rec_tiny.onnx",
        dict_url: "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/paddle/PP-OCRv6/rec/PP-OCRv6_rec_tiny/ppocrv6_tiny_dict.txt",
    },
    ModelSpec {
        id: "ppocrv6_small",
        label: "PP-OCRv6 small",
        languages: "50 ngôn ngữ",
        size_mb: 25.2,
        det_file: "PP-OCRv6_det_small.onnx",
        rec_file: "PP-OCRv6_rec_small.onnx",
        dict_file: "ppocrv6_dict.txt",
        det_url: "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv6/det/PP-OCRv6_det_small.onnx",
        rec_url: "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv6/rec/PP-OCRv6_rec_small.onnx",
        dict_url: "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/paddle/PP-OCRv6/rec/PP-OCRv6_rec_small/ppocrv6_dict.txt",
    },
    ModelSpec {
        id: "ppocrv6_medium",
        label: "PP-OCRv6 medium",
        languages: "50 ngôn ngữ",
        size_mb: 99.7,
        det_file: "PP-OCRv6_det_medium.onnx",
        rec_file: "PP-OCRv6_rec_medium.onnx",
        dict_file: "ppocrv6_dict.txt",
        det_url: "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv6/det/PP-OCRv6_det_medium.onnx",
        rec_url: "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv6/rec/PP-OCRv6_rec_medium.onnx",
        dict_url: "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/paddle/PP-OCRv6/rec/PP-OCRv6_rec_medium/ppocrv6_dict.txt",
    },
];

fn spec_for(model_id: &str) -> &'static ModelSpec {
    MODEL_SPECS
        .iter()
        .find(|m| m.id == model_id)
        .unwrap_or(&MODEL_SPECS[0])
}

pub fn model_root() -> PathBuf {
    config_dir().join("models").join("rapidocr")
}

pub fn model_paths(model_id: &str) -> (PathBuf, PathBuf, PathBuf) {
    let spec = spec_for(model_id);
    let root = model_root();
    (
        root.join(spec.det_file),
        root.join(spec.rec_file),
        root.join(spec.dict_file),
    )
}

pub fn model_installed(model_id: &str) -> bool {
    let (det, rec, dict) = model_paths(model_id);
    [det, rec, dict]
        .iter()
        .all(|p| fs::metadata(p).map(|m| m.is_file() && m.len() > 0).unwrap_or(false))
}

pub fn list_models() -> Vec<OcrModelInfo> {
    MODEL_SPECS
        .iter()
        .map(|s| OcrModelInfo {
            id: s.id.to_string(),
            label: s.label.to_string(),
            languages: s.languages.to_string(),
            size_mb: s.size_mb,
            installed: model_installed(s.id),
            det_filename: s.det_file.to_string(),
            rec_filename: s.rec_file.to_string(),
            dict_filename: s.dict_file.to_string(),
        })
        .collect()
}

pub fn status(model_id: &str, backend: &str) -> OcrEngineStatusInfo {
    let installed = model_installed(model_id);
    let backend_note = match backend {
        "directml" => "GPU DirectML (ONNX Runtime).",
        "cpu" => "CPU (ONNX Runtime).",
        "auto" => "Tự động chọn DirectML / CPU (ONNX Runtime).",
        _ => "CPU fallback (ONNX Runtime).",
    };
    if installed {
        OcrEngineStatusInfo {
            available: true,
            detail: format!("Model đã sẵn sàng. {backend_note}"),
        }
    } else {
        OcrEngineStatusInfo {
            available: false,
            detail: format!(
                "Model '{}' chưa tải. Vào mục OCR để tải model ngoại tuyến. {backend_note}",
                spec_for(model_id).label
            ),
        }
    }
}

pub fn model_label(model_id: &str) -> &'static str {
    spec_for(model_id).label
}

async fn download_file_with_progress<F>(
    url: &str,
    dest: &PathBuf,
    cancel: &AtomicBool,
    mut on_chunk: F,
) -> Result<u64, String>
where
    F: FnMut(u64, Option<u64>),
{
    if let Ok(meta) = fs::metadata(dest) {
        if meta.is_file() && meta.len() > 0 {
            let len = meta.len();
            on_chunk(len, Some(len));
            return Ok(len);
        }
    }
    if cancel.load(Ordering::SeqCst) {
        return Err("CANCELLED".to_string());
    }
    if let Some(parent) = dest.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("Không tạo được thư mục model: {e}"))?;
    }
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(300))
        .user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Translator2k/2.1")
        .build()
        .map_err(|_| "Không khởi tạo được kết nối mạng, vui lòng thử lại sau.".to_string())?;
    let resp = client
        .get(url)
        .send()
        .await
        .map_err(|_| "Không kết nối được để tải mô hình OCR, vui lòng thử lại sau.".to_string())?;
    if !resp.status().is_success() {
        return Err("Tải mô hình OCR không thành công, vui lòng thử lại sau.".to_string());
    }
    let content_len = resp.content_length();
    on_chunk(0, content_len);

    let tmp = dest.with_extension("download");
    let mut file =
        fs::File::create(&tmp).map_err(|e| format!("Không tạo được file model tạm: {e}"))?;
    let mut stream = resp.bytes_stream();
    let mut downloaded: u64 = 0;
    let mut last_emit = Instant::now() - Duration::from_secs(1);

    while let Some(chunk) = stream.next().await {
        if cancel.load(Ordering::SeqCst) {
            drop(file);
            let _ = fs::remove_file(&tmp);
            return Err("CANCELLED".to_string());
        }
        let bytes = match chunk {
            Ok(b) => b,
            Err(_) => {
                drop(file);
                let _ = fs::remove_file(&tmp);
                return Err("Tải mô hình OCR bị gián đoạn, vui lòng thử lại sau.".to_string());
            }
        };
        if let Err(e) = file.write_all(&bytes) {
            drop(file);
            let _ = fs::remove_file(&tmp);
            return Err(format!("Lỗi ghi file model: {e}"));
        }
        downloaded += bytes.len() as u64;
        if last_emit.elapsed() >= Duration::from_millis(60) {
            on_chunk(downloaded, content_len);
            last_emit = Instant::now();
        }
    }
    on_chunk(downloaded, content_len.or(Some(downloaded)));
    drop(file);
    if cancel.load(Ordering::SeqCst) {
        let _ = fs::remove_file(&tmp);
        return Err("CANCELLED".to_string());
    }
    let _ = fs::remove_file(dest);
    fs::rename(&tmp, dest).map_err(|e| format!("Không lưu được file model: {e}"))?;
    Ok(downloaded)
}

pub async fn download_model_with_progress<F>(
    model_id: &str,
    cancel: Arc<AtomicBool>,
    on_progress: F,
) -> Result<(), String>
where
    F: Fn(OcrDownloadProgressEvent) + Send + Sync,
{
    let spec = spec_for(model_id);
    let (det, rec, dict) = model_paths(model_id);
    let est_total_bytes = ((spec.size_mb as f64) * 1024.0 * 1024.0).round().max(1.0) as u64;
    let steps: [(&str, &PathBuf, &str); 3] = [
        (spec.det_url, &det, "Mô hình phát hiện chữ"),
        (spec.rec_url, &rec, "Mô hình nhận dạng chữ"),
        (spec.dict_url, &dict, "Từ điển ký tự"),
    ];
    let file_total = steps.len();
    let mut completed_bytes: u64 = 0;

    for (idx, (url, dest, label)) in steps.iter().enumerate() {
        let file_index = idx + 1;
        let step_done = download_file_with_progress(url, dest, &cancel, |cur_dl, cur_total| {
            let total_dl = completed_bytes.saturating_add(cur_dl);
            let approx_total = est_total_bytes.max(
                completed_bytes.saturating_add(cur_total.unwrap_or(cur_dl)),
            );
            let raw_pct = if approx_total > 0 {
                (total_dl as f64 / approx_total as f64) * 100.0
            } else {
                ((file_index.saturating_sub(1)) as f64 / file_total as f64) * 100.0
            };
            let percent = raw_pct.clamp(0.0, 99.5);
            on_progress(OcrDownloadProgressEvent {
                model_id: spec.id.to_string(),
                model_label: spec.label.to_string(),
                file_index,
                file_total,
                current_file: (*label).to_string(),
                downloaded_bytes: total_dl,
                total_bytes: approx_total,
                percent,
            });
        })
        .await?;
        completed_bytes = completed_bytes.saturating_add(step_done);
    }

    on_progress(OcrDownloadProgressEvent {
        model_id: spec.id.to_string(),
        model_label: spec.label.to_string(),
        file_index: file_total,
        file_total,
        current_file: "Hoàn tất".to_string(),
        downloaded_bytes: completed_bytes,
        total_bytes: completed_bytes.max(est_total_bytes),
        percent: 100.0,
    });
    forget_engines();
    Ok(())
}

pub async fn download_model(model_id: &str) -> Result<(), String> {
    download_model_with_progress(model_id, Arc::new(AtomicBool::new(false)), |_| {}).await
}

struct OnnxEngine {
    det: Session,
    rec: Session,
    charset: Vec<String>,
}

static ENGINES: Lazy<Mutex<HashMap<(String, String), OnnxEngine>>> =
    Lazy::new(|| Mutex::new(HashMap::new()));

pub fn forget_engines() {
    ENGINES.lock().clear();
}

fn inference_threads() -> usize {
    let cpus = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4);
    (cpus / 2).clamp(2, 8)
}

static ORT_ENV: Lazy<Result<ort::environment::Environment, String>> = Lazy::new(|| {
    ort::init()
        .build()
        .map_err(|e| format!("Không khởi tạo được môi trường ONNX Runtime: {e}"))
});

fn build_session(path: &PathBuf, backend: &str) -> Result<Session, String> {
    let env = ORT_ENV.as_ref().map_err(|e| e.clone())?;
    let threads = inference_threads();
    let mut builder = Session::builder(env)
        .map_err(|e| format!("Lỗi khởi tạo ONNX Runtime: {e}"))?
        .with_optimization_level(GraphOptimizationLevel::Level3)
        .map_err(|e| format!("Lỗi cấu hình ONNX: {e}"))?
        .with_intra_threads(threads)
        .map_err(|e| format!("Lỗi cấu hình luồng ONNX: {e}"))?
        .with_inter_threads(1)
        .map_err(|e| format!("Lỗi cấu hình luồng ONNX: {e}"))?;

    if backend == "directml" || backend == "auto" {
        if let Ok(with_dml) =
            builder
                .clone()
                .with_execution_providers([ort::ep::DirectML::default().build()])
        {
            builder = with_dml;
        }
    }

    builder
        .commit_from_file(path)
        .map_err(|e| format!("Không nạp được model ONNX {}: {e}", path.display()))
}

fn load_charset(path: &PathBuf) -> Result<Vec<String>, String> {
    let raw = fs::read_to_string(path)
        .map_err(|e| format!("Không đọc được từ điển ký tự OCR: {e}"))?;
    let mut chars = vec!["blank".to_string()];
    for line in raw.lines() {
        chars.push(line.trim_end_matches('\r').to_string());
    }
    chars.push(" ".to_string());
    Ok(chars)
}

fn run_det(session: &mut Session, img: &RgbImage, max_side: u32) -> Result<Vec<[i32; 4]>, String> {
    let orig_w = img.width();
    let orig_h = img.height();
    let longest = orig_w.max(orig_h);
    let ratio = if longest > max_side {
        max_side as f32 / longest as f32
    } else {
        1.0
    };
    let rw = (((orig_w as f32 * ratio) / 32.0).round() as u32 * 32).max(32);
    let rh = (((orig_h as f32 * ratio) / 32.0).round() as u32 * 32).max(32);
    let resized = imageops::resize(img, rw, rh, imageops::FilterType::Triangle);

    let mean = [0.485f32, 0.456, 0.406];
    let std = [0.229f32, 0.224, 0.225];
    let mut input = Array4::<f32>::zeros((1, 3, rh as usize, rw as usize));
    for y in 0..rh as usize {
        for x in 0..rw as usize {
            let p = resized.get_pixel(x as u32, y as u32);
            input[[0, 0, y, x]] = (p[0] as f32 / 255.0 - mean[0]) / std[0];
            input[[0, 1, y, x]] = (p[1] as f32 / 255.0 - mean[1]) / std[1];
            input[[0, 2, y, x]] = (p[2] as f32 / 255.0 - mean[2]) / std[2];
        }
    }

    let tensor = Tensor::from_array(input).map_err(|e| format!("Lỗi tạo tensor det: {e}"))?;
    let outputs = session
        .run(ort::inputs![tensor])
        .map_err(|e| format!("Lỗi chạy model det: {e}"))?;
    let (shape, data) = outputs[0]
        .try_extract_tensor::<f32>()
        .map_err(|e| format!("Lỗi đọc output det: {e}"))?;
    if shape.len() < 4 || shape[2] <= 0 || shape[3] <= 0 {
        return Err(format!("Kích thước output det không hợp lệ: {shape:?}"));
    }

    let mh = shape[2] as usize;
    let mw = shape[3] as usize;
    if data.len() < mw * mh {
        return Err("Dữ liệu bản đồ phát hiện chữ bị thiếu.".to_string());
    }
    let mut visited = vec![false; mw * mh];
    let mut boxes = Vec::new();
    let sx = orig_w as f32 / mw as f32;
    let sy = orig_h as f32 / mh as f32;

    for y in 0..mh {
        for x in 0..mw {
            let idx = y * mw + x;
            if visited[idx] || data[idx] < 0.3 {
                continue;
            }
            let mut q = VecDeque::new();
            q.push_back((x, y));
            visited[idx] = true;
            let (mut min_x, mut min_y, mut max_x, mut max_y) = (x, y, x, y);
            let mut count = 0usize;
            let mut score_sum = 0.0f32;

            while let Some((cx, cy)) = q.pop_front() {
                count += 1;
                score_sum += data[cy * mw + cx];
                min_x = min_x.min(cx);
                min_y = min_y.min(cy);
                max_x = max_x.max(cx);
                max_y = max_y.max(cy);

                for (nx, ny) in [
                    (cx.wrapping_sub(1), cy),
                    (cx + 1, cy),
                    (cx, cy.wrapping_sub(1)),
                    (cx, cy + 1),
                ] {
                    if nx < mw && ny < mh {
                        let nidx = ny * mw + nx;
                        if !visited[nidx] && data[nidx] >= 0.3 {
                            visited[nidx] = true;
                            q.push_back((nx, ny));
                        }
                    }
                }
            }

            let bw = (max_x - min_x + 1) as f32;
            let bh = (max_y - min_y + 1) as f32;
            if count < 8 || bw < 3.0 || bh < 3.0 || (score_sum / count as f32) < 0.5 {
                continue;
            }
            // DBNet unclip expansion
            let area = bw * bh;
            let perim = 2.0 * (bw + bh);
            let expand = (area * 1.6 / perim).clamp(1.0, 20.0);
            let l = ((min_x as f32 - expand) * sx).floor().clamp(0.0, orig_w as f32) as i32;
            let t = ((min_y as f32 - expand) * sy).floor().clamp(0.0, orig_h as f32) as i32;
            let r = ((max_x as f32 + 1.0 + expand) * sx)
                .ceil()
                .clamp(0.0, orig_w as f32) as i32;
            let b = ((max_y as f32 + 1.0 + expand) * sy)
                .ceil()
                .clamp(0.0, orig_h as f32) as i32;
            if r - l >= 4 && b - t >= 4 {
                boxes.push([l, t, r, b]);
            }
        }
    }

    boxes.sort_by(|a, b| a[1].cmp(&b[1]).then(a[0].cmp(&b[0])));
    Ok(boxes)
}

fn run_rec(session: &mut Session, charset: &[String], crop: &RgbImage) -> Result<(String, f32), String> {
    let target_h = 48u32;
    let aspect = crop.width() as f32 / crop.height().max(1) as f32;
    let target_w = ((target_h as f32 * aspect).ceil() as u32).clamp(16, 1600);
    let resized = imageops::resize(crop, target_w, target_h, imageops::FilterType::Triangle);

    let mut input = Array4::<f32>::zeros((1, 3, target_h as usize, target_w as usize));
    for y in 0..target_h as usize {
        for x in 0..target_w as usize {
            let p = resized.get_pixel(x as u32, y as u32);
            input[[0, 0, y, x]] = (p[0] as f32 / 255.0 - 0.5) / 0.5;
            input[[0, 1, y, x]] = (p[1] as f32 / 255.0 - 0.5) / 0.5;
            input[[0, 2, y, x]] = (p[2] as f32 / 255.0 - 0.5) / 0.5;
        }
    }

    let tensor = Tensor::from_array(input).map_err(|e| format!("Lỗi tạo tensor rec: {e}"))?;
    let outputs = session
        .run(ort::inputs![tensor])
        .map_err(|e| format!("Lỗi chạy model rec: {e}"))?;
    let (shape, data) = outputs[0]
        .try_extract_tensor::<f32>()
        .map_err(|e| format!("Lỗi đọc output rec: {e}"))?;
    if shape.len() < 3 || shape[1] <= 0 || shape[2] <= 0 {
        return Err(format!("Kích thước output rec không hợp lệ: {shape:?}"));
    }

    let steps = shape[1] as usize;
    let classes = shape[2] as usize;
    if data.len() < steps * classes {
        return Err("Dữ liệu nhận dạng chữ bị thiếu.".to_string());
    }
    let mut text = String::new();
    let mut last_idx = 0usize;
    let mut conf_sum = 0.0f32;
    let mut conf_cnt = 0usize;

    for t in 0..steps {
        let row = &data[t * classes..(t + 1) * classes];
        let mut best_i = 0usize;
        let mut best_v = f32::NEG_INFINITY;
        for (i, &v) in row.iter().enumerate() {
            if v > best_v {
                best_v = v;
                best_i = i;
            }
        }
        if best_i != 0 && best_i != last_idx {
            if let Some(ch) = charset.get(best_i) {
                text.push_str(ch);
                conf_sum += best_v;
                conf_cnt += 1;
            }
        }
        last_idx = best_i;
    }

    let avg_conf = if conf_cnt > 0 {
        conf_sum / conf_cnt as f32
    } else {
        0.0
    };
    Ok((text.trim().to_string(), avg_conf))
}

static GLUED_ICON_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#"^[^\w\s"'(\[{¿¡#@$€£¥+\-]+\s*"#).unwrap());

fn latin_like(text: &str) -> bool {
    !text.chars().any(crate::ocr::is_cjk)
        && text.chars().filter(|c| c.is_ascii_alphabetic()).count() >= 3
}

fn strip_icon_prefix(text: &str) -> String {
    let trimmed = text.trim();
    if let Some(m) = GLUED_ICON_RE.find(trimmed) {
        let rest = trimmed[m.end()..].trim();
        if latin_like(rest) {
            return rest.to_string();
        }
    }
    // Single leading digit glued directly before a Capitalized word (e.g. "8Tool" -> "Tool", keeping "3D"/"2nd")
    let mut chars = trimmed.chars();
    if let (Some(c0), Some(c1), Some(c2)) = (chars.next(), chars.next(), chars.next()) {
        if c0.is_ascii_digit() && c1.is_ascii_uppercase() && c2.is_ascii_lowercase() {
            let rest = trimmed[c0.len_utf8()..].trim();
            if latin_like(rest) {
                return rest.to_string();
            }
        }
    }
    trimmed.to_string()
}

/// Upscale low-saturation monochrome manga/scan images by 1.6x during detail pass for crisper OCR.
fn maybe_upscale_grayscale(img: &RgbImage) -> Option<(RgbImage, f32)> {
    let (w, h) = img.dimensions();
    if w < 24 || h < 24 {
        return None;
    }
    let longest = w.max(h) as f32;
    let sample_scale = (128.0 / longest).min(1.0);
    let sw = (w as f32 * sample_scale).round().max(1.0) as u32;
    let sh = (h as f32 * sample_scale).round().max(1.0) as u32;
    let sample = imageops::resize(img, sw, sh, imageops::FilterType::Triangle);
    let total = (sw * sh).max(1) as usize;
    let mut low_sat = 0usize;
    for px in sample.pixels() {
        let max_c = px[0].max(px[1]).max(px[2]);
        let min_c = px[0].min(px[1]).min(px[2]);
        let sat = if max_c == 0 {
            0u16
        } else {
            ((max_c - min_c) as u16 * 255) / (max_c as u16)
        };
        if sat < 28 {
            low_sat += 1;
        }
    }
    if (low_sat as f32 / total as f32) < 0.82 {
        return None;
    }
    let scale = (2400.0 / longest).min(1.6);
    if scale < 1.15 {
        return None;
    }
    let nw = (w as f32 * scale).round().max(1.0) as u32;
    let nh = (h as f32 * scale).round().max(1.0) as u32;
    Some((imageops::resize(img, nw, nh, imageops::FilterType::Lanczos3), scale))
}

pub fn recognize(
    img: &RgbImage,
    model_id: &str,
    backend: &str,
    detail_pass: bool,
) -> Result<(String, Vec<TextRegion>), String> {
    if !model_installed(model_id) {
        return Err(format!(
            "Model '{}' chưa được tải. Vào mục OCR để tải model.",
            spec_for(model_id).label
        ));
    }

    let (work_img_owned, coord_scale) = if detail_pass {
        if let Some((up, sc)) = maybe_upscale_grayscale(img) {
            (Some(up), sc)
        } else {
            (None, 1.0)
        }
    } else {
        (None, 1.0)
    };
    let work_img = work_img_owned.as_ref().unwrap_or(img);

    let key = (model_id.to_string(), backend.to_string());
    let mut guard = ENGINES.lock();
    if !guard.contains_key(&key) {
        let (det_p, rec_p, dict_p) = model_paths(model_id);
        let det = build_session(&det_p, backend)?;
        let rec = build_session(&rec_p, backend)?;
        let charset = load_charset(&dict_p)?;
        guard.insert(key.clone(), OnnxEngine { det, rec, charset });
    }
    let engine = guard.get_mut(&key).unwrap();
    let max_side = if detail_pass { 1280 } else { 960 };
    let boxes = run_det(&mut engine.det, work_img, max_side)?;

    let mut regions = Vec::new();
    let mut texts = Vec::new();
    for bbox in boxes {
        let [l, t, r, b] = bbox;
        let w = (r - l) as u32;
        let h = (b - t) as u32;
        if w < 4 || h < 4 {
            continue;
        }
        let crop = imageops::crop_imm(work_img, l as u32, t as u32, w, h).to_image();
        if let Ok((raw_txt, score)) = run_rec(&mut engine.rec, &engine.charset, &crop) {
            let txt = strip_icon_prefix(&raw_txt);
            if !txt.is_empty() && score >= 0.45 {
                let scaled_bbox = [
                    (l as f32 / coord_scale).round() as i32,
                    (t as f32 / coord_scale).round() as i32,
                    (r as f32 / coord_scale).round() as i32,
                    (b as f32 / coord_scale).round() as i32,
                ];
                if scaled_bbox[2] > scaled_bbox[0] && scaled_bbox[3] > scaled_bbox[1] {
                    texts.push(txt.clone());
                    regions.push(TextRegion::new(txt, scaled_bbox));
                }
            }
        }
    }

    Ok((texts.join("\n"), regions))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strips_glued_icon_prefixes_safely() {
        assert_eq!(strip_icon_prefix("</>Programming"), "Programming");
        assert_eq!(strip_icon_prefix("8Tool"), "Tool");
        assert_eq!(strip_icon_prefix("3D Model"), "3D Model");
        assert_eq!(strip_icon_prefix("こんにちは"), "こんにちは");
    }
}
