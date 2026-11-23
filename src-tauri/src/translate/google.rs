use std::collections::HashMap;
use std::time::{Duration, Instant};

use once_cell::sync::Lazy;
use parking_lot::Mutex;
use rand::Rng;
use regex::Regex;
use serde_json::Value;

use crate::translate::split_proportionally;

pub const BROWSER_UA: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0";
const GOOGLE_PA_KEY: &str = "AIzaSyATBXajvzQLTDHEQbcpq0Ihe0vWDHmO520";
const GOOGLE_BACKENDS: &[&str] = &["translate-pa", "dict-chrome-ex", "dict-chrome-ex-c5", "gtx"];
const GOOGLE_BATCH_CHARS: usize = 4000;
const GOOGLE_BATCH_ITEMS: usize = 64;
const GOOGLE_TIMEOUT_SECS: u64 = 8;
const GOOGLE_MIN_INTERVAL_MS: u64 = 150;
const GOOGLE_COOLDOWN_BASE: f64 = 8.0;
const GOOGLE_COOLDOWN_MAX: f64 = 120.0;

static BR_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"(?i)<br\s*/?>").unwrap());

static HTTP_CLIENT: Lazy<reqwest::Client> = Lazy::new(|| {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(GOOGLE_TIMEOUT_SECS))
        .pool_max_idle_per_host(4)
        .user_agent(BROWSER_UA)
        .build()
        .expect("Failed to build Google HTTP client")
});

static RATE_STATE: Lazy<tokio::sync::Mutex<Instant>> =
    Lazy::new(|| tokio::sync::Mutex::new(Instant::now() - Duration::from_secs(10)));

struct CooldownState {
    preferred: String,
    backends: HashMap<String, (Instant, u32)>,
}

static COOLDOWN: Lazy<Mutex<CooldownState>> = Lazy::new(|| {
    Mutex::new(CooldownState {
        preferred: String::new(),
        backends: HashMap::new(),
    })
});

enum GoogleCallError {
    RateLimit(String),
    Server5xx(String),
    Other(String),
}

fn backend_cooldown_remaining(backend: &str) -> f64 {
    let state = COOLDOWN.lock();
    if let Some(&(until, _)) = state.backends.get(backend) {
        let now = Instant::now();
        if until > now {
            return (until - now).as_secs_f64();
        }
    }
    0.0
}

pub fn google_cooldown_remaining() -> f64 {
    GOOGLE_BACKENDS
        .iter()
        .map(|b| backend_cooldown_remaining(b))
        .fold(f64::INFINITY, f64::min)
}

fn enter_cooldown(backend: &str) -> f64 {
    let mut state = COOLDOWN.lock();
    let strikes = state.backends.get(backend).map(|(_, s)| *s).unwrap_or(0);
    let secs = (GOOGLE_COOLDOWN_BASE * 2f64.powi(strikes as i32)).min(GOOGLE_COOLDOWN_MAX);
    state.backends.insert(
        backend.to_string(),
        (Instant::now() + Duration::from_secs_f64(secs), strikes + 1),
    );
    secs
}

fn reset_cooldown(backend: &str) {
    let mut state = COOLDOWN.lock();
    state.backends.remove(backend);
    state.preferred = backend.to_string();
}

async fn wait_rate_limit() {
    let mut last = RATE_STATE.lock().await;
    let elapsed = last.elapsed();
    let min_gap = Duration::from_millis(GOOGLE_MIN_INTERVAL_MS);
    if elapsed < min_gap {
        tokio::time::sleep(min_gap - elapsed).await;
    }
    *last = Instant::now();
}

fn google_batches(texts: &[String]) -> Vec<Vec<usize>> {
    let mut batches = Vec::new();
    let mut current = Vec::new();
    let mut size = 0usize;
    for (idx, text) in texts.iter().enumerate() {
        let len = text.len();
        if !current.is_empty()
            && (size + len > GOOGLE_BATCH_CHARS || current.len() >= GOOGLE_BATCH_ITEMS)
        {
            batches.push(current);
            current = Vec::new();
            size = 0;
        }
        current.push(idx);
        size += len;
    }
    if !current.is_empty() {
        batches.push(current);
    }
    batches
}

pub async fn translate_google_many(
    texts: &[String],
    source: &str,
    target: &str,
) -> Result<Vec<String>, String> {
    let sl = if source.trim().is_empty() { "auto" } else { source.trim() };
    let mut results = vec![String::new(); texts.len()];
    for batch in google_batches(texts) {
        let slice: Vec<String> = batch.iter().map(|&i| texts[i].clone()).collect();
        let translated = translate_google_batch(&slice, sl, target).await?;
        for (idx, val) in batch.into_iter().zip(translated.into_iter()) {
            results[idx] = val;
        }
    }
    Ok(results)
}

async fn translate_google_batch(
    texts: &[String],
    source: &str,
    target: &str,
) -> Result<Vec<String>, String> {
    let mut last_err: Option<String> = None;
    let mut rate_limited = false;

    for attempt in 0..2 {
        let mut transient = false;
        rate_limited = false;
        let preferred = COOLDOWN.lock().preferred.clone();
        let mut order: Vec<&str> = GOOGLE_BACKENDS.to_vec();
        order.sort_by_key(|&b| b != preferred.as_str());

        for backend in order {
            if backend_cooldown_remaining(backend) > 0.0 {
                rate_limited = true;
                continue;
            }
            match call_once_more_on_5xx(backend, texts, source, target).await {
                Ok(translated) => {
                    reset_cooldown(backend);
                    return Ok(translated);
                }
                Err(GoogleCallError::RateLimit(msg)) => {
                    rate_limited = true;
                    last_err = Some(msg);
                }
                Err(GoogleCallError::Server5xx(msg)) | Err(GoogleCallError::Other(msg)) => {
                    transient = true;
                    last_err = Some(msg);
                }
            }
        }
        if !transient || attempt == 1 {
            break;
        }
        let jitter: f64 = rand::thread_rng().gen_range(0.8..1.2);
        tokio::time::sleep(Duration::from_secs_f64(jitter)).await;
    }

    if rate_limited {
        let secs = google_cooldown_remaining().round().max(1.0) as u64;
        return Err(format!(
            "Google Translate đang giới hạn request (429) trên mọi endpoint. Tự thử lại sau khoảng {secs} giây."
        ));
    }
    Err(last_err.unwrap_or_else(|| "Dịch vụ không trả về bản dịch.".to_string()))
}

async fn call_once_more_on_5xx(
    backend: &str,
    texts: &[String],
    source: &str,
    target: &str,
) -> Result<Vec<String>, GoogleCallError> {
    match call_backend(backend, texts, source, target).await {
        Err(GoogleCallError::Server5xx(_)) => call_backend(backend, texts, source, target).await,
        other => other,
    }
}

fn parse_dict_chrome(data: &Value, expected: usize) -> Vec<String> {
    if let Some(s) = data.as_str() {
        return if expected == 1 {
            vec![s.to_string()]
        } else {
            Vec::new()
        };
    }
    let Some(arr) = data.as_array() else {
        return Vec::new();
    };
    if expected == 1 {
        if let Some(s) = arr.first().and_then(Value::as_str) {
            return vec![s.to_string()];
        }
    }
    let mut results = Vec::with_capacity(expected);
    for i in 0..expected {
        let Some(item) = arr.get(i) else {
            results.push(String::new());
            continue;
        };
        if let Some(s) = item.as_str() {
            results.push(s.to_string());
            continue;
        }
        let first = item.as_array().and_then(|a| a.first());
        let text = match first {
            Some(Value::String(s)) => s.clone(),
            Some(Value::Array(inner)) => inner
                .first()
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string(),
            _ => String::new(),
        };
        results.push(text);
    }
    results
}

async fn post_google(
    backend: &str,
    url: &str,
    body: Vec<u8>,
    content_type: &str,
    extra_api_key: Option<&str>,
) -> Result<Value, GoogleCallError> {
    wait_rate_limit().await;
    let mut req = HTTP_CLIENT
        .post(url)
        .header("Content-Type", content_type)
        .body(body);
    if let Some(key) = extra_api_key {
        req = req.header("X-Goog-API-Key", key);
    }
    let resp = req
        .send()
        .await
        .map_err(|_| {
            GoogleCallError::Other("Không kết nối được dịch vụ dịch, vui lòng thử lại sau.".to_string())
        })?;

    let status = resp.status().as_u16();
    let final_url = resp.url().to_string();
    if status == 429 || (status == 403 && matches!(backend, "dict-chrome-ex" | "dict-chrome-ex-c5"))
    {
        let secs = enter_cooldown(backend).round() as u64;
        return Err(GoogleCallError::RateLimit(format!(
            "Google ({backend}) giới hạn request ({status}), nghỉ {secs} s."
        )));
    }
    if status >= 500 {
        return Err(GoogleCallError::Server5xx(format!(
            "Dịch vụ dịch trả về HTTP {status}."
        )));
    }
    if status >= 400 {
        return Err(GoogleCallError::Other(format!(
            "Dịch vụ dịch trả về HTTP {status}."
        )));
    }
    if final_url.contains("/sorry") {
        let secs = enter_cooldown(backend).round() as u64;
        return Err(GoogleCallError::RateLimit(format!(
            "Google ({backend}) yêu cầu captcha, nghỉ {secs} s."
        )));
    }
    let text = resp
        .text()
        .await
        .map_err(|e| GoogleCallError::Other(format!("Lỗi đọc phản hồi dịch: {e}")))?;
    serde_json::from_str(&text)
        .map_err(|_| GoogleCallError::Other("Dịch vụ dịch trả về dữ liệu không hợp lệ.".to_string()))
}

async fn call_backend(
    backend: &str,
    texts: &[String],
    source: &str,
    target: &str,
) -> Result<Vec<String>, GoogleCallError> {
    let translated = match backend {
        "dict-chrome-ex" | "dict-chrome-ex-c5" => {
            let host = if backend == "dict-chrome-ex" {
                "translate.googleapis.com"
            } else {
                "clients5.google.com"
            };
            let url = format!(
                "https://{host}/translate_a/t?client=dict-chrome-ex&sl={}&tl={}&tbb=1&ie=UTF-8&oe=UTF-8",
                urlencoding::encode(source),
                urlencoding::encode(target)
            );
            let form_body = texts
                .iter()
                .map(|t| format!("q={}", urlencoding::encode(t)))
                .collect::<Vec<_>>()
                .join("&");
            let data = post_google(
                backend,
                &url,
                form_body.into_bytes(),
                "application/x-www-form-urlencoded;charset=UTF-8",
                None,
            )
            .await?;
            parse_dict_chrome(&data, texts.len())
        }
        "translate-pa" => {
            let items: Vec<String> = texts
                .iter()
                .map(|t| {
                    t.split('\n')
                        .map(|line| html_escape::encode_text(line).into_owned())
                        .collect::<Vec<_>>()
                        .join("<br>")
                })
                .collect();
            let payload = serde_json::json!([[items, source, target], "te_lib"]);
            let body = serde_json::to_vec(&payload).unwrap_or_default();
            let data = post_google(
                backend,
                "https://translate-pa.googleapis.com/v1/translateHtml",
                body,
                "application/json+protobuf",
                Some(GOOGLE_PA_KEY),
            )
            .await?;
            let raw_items = data
                .as_array()
                .and_then(|a| a.first())
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            raw_items
                .into_iter()
                .take(texts.len())
                .map(|v| {
                    let s = v.as_str().unwrap_or("");
                    BR_RE
                        .split(s)
                        .map(|part| html_escape::decode_html_entities(part).trim().to_string())
                        .collect::<Vec<_>>()
                        .join("\n")
                })
                .collect()
        }
        _ => {
            // gtx fallback
            let flat = if texts.len() == 1 {
                texts[0].clone()
            } else {
                texts
                    .iter()
                    .map(|t| t.split_whitespace().collect::<Vec<_>>().join(" "))
                    .collect::<Vec<_>>()
                    .join("\n")
            };
            let url = format!(
                "https://translate.googleapis.com/translate_a/single?client=gtx&sl={}&tl={}&dt=t",
                urlencoding::encode(source),
                urlencoding::encode(target)
            );
            let body = format!("q={}", urlencoding::encode(&flat));
            let data = post_google(
                backend,
                &url,
                body.into_bytes(),
                "application/x-www-form-urlencoded;charset=UTF-8",
                None,
            )
            .await?;
            let joined: String = data
                .as_array()
                .and_then(|a| a.first())
                .and_then(Value::as_array)
                .map(|chunks| {
                    chunks
                        .iter()
                        .filter_map(|c| c.as_array()?.first()?.as_str())
                        .collect::<String>()
                })
                .unwrap_or_default();
            if texts.len() == 1 {
                vec![joined]
            } else {
                let lines: Vec<String> = joined
                    .lines()
                    .map(|l| l.trim().to_string())
                    .filter(|l| !l.is_empty())
                    .collect();
                if lines.len() == texts.len() {
                    lines
                } else {
                    split_proportionally(&lines.join(" "), texts)
                }
            }
        }
    };

    if translated.len() != texts.len() || translated.iter().any(|s| s.trim().is_empty()) {
        return Err(GoogleCallError::Other(
            "Dịch vụ không trả về đủ bản dịch.".to_string(),
        ));
    }
    Ok(translated)
}
