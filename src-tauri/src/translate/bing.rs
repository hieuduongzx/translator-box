use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::Value;

use crate::translate::google::BROWSER_UA;
use crate::translate::split_proportionally;

const BING_TRANSLATOR_URL: &str = "https://www.bing.com/translator";
const BING_TRANSLATE_URL: &str = "https://www.bing.com/ttranslatev3";
const BING_MAX_CHARS: usize = 1000;

static IG_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r#"IG:"([^"]+)""#).unwrap());
static IID_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r#"data-iid="([^"]+)""#).unwrap());
static HELPER_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"var params_AbusePreventionHelper\s*=\s*\[([^\]]+)\]").unwrap());

static BING_CLIENT: Lazy<reqwest::Client> = Lazy::new(|| {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .user_agent(BROWSER_UA)
        .build()
        .expect("Failed to build Bing HTTP client")
});

#[derive(Clone)]
struct BingSession {
    ig: String,
    iid: String,
    key: String,
    token: String,
    expires: Instant,
}

static BING_SESSION: Lazy<tokio::sync::Mutex<Option<BingSession>>> =
    Lazy::new(|| tokio::sync::Mutex::new(None));
static BING_COUNTER: AtomicU64 = AtomicU64::new(1);

fn bing_lang(code: &str) -> &str {
    match code {
        "zh-CN" => "zh-Hans",
        "zh-TW" => "zh-Hant",
        other => other,
    }
}

fn bing_source(source: &str) -> &str {
    let trimmed = source.trim();
    if trimmed.is_empty() || trimmed.eq_ignore_ascii_case("auto") {
        "auto-detect"
    } else {
        bing_lang(trimmed)
    }
}

fn parse_bing_bootstrap(page: &str) -> Option<BingSession> {
    let ig = IG_RE.captures(page)?.get(1)?.as_str().to_string();
    let iid = IID_RE.captures(page)?.get(1)?.as_str().to_string();
    let helper = HELPER_RE.captures(page)?.get(1)?.as_str();
    let parts: Vec<&str> = helper
        .split(',')
        .map(|p| p.trim().trim_matches('"'))
        .collect();
    if parts.len() < 2 || parts[0].is_empty() || parts[1].is_empty() {
        return None;
    }
    let ttl_secs = parts
        .get(2)
        .and_then(|p| {
            let digits: String = p.chars().filter(|c| c.is_ascii_digit()).collect();
            digits.parse::<u64>().ok()
        })
        .map(|ms| (ms as f64 / 1000.0).max(120.0))
        .unwrap_or(1800.0);
    Some(BingSession {
        ig,
        iid,
        key: parts[0].to_string(),
        token: parts[1].to_string(),
        expires: Instant::now() + Duration::from_secs_f64((ttl_secs - 60.0).max(60.0)),
    })
}

async fn get_bing_session(force: bool) -> Result<BingSession, String> {
    let mut guard = BING_SESSION.lock().await;
    if !force {
        if let Some(ref s) = *guard {
            if Instant::now() < s.expires {
                return Ok(s.clone());
            }
        }
    }
    let resp = BING_CLIENT
        .get(BING_TRANSLATOR_URL)
        .header("Accept", "text/html,application/xhtml+xml")
        .header("Accept-Language", "en-US,en;q=0.9")
        .send()
        .await
        .map_err(|_| "Không kết nối được Bing Dịch, vui lòng thử lại sau.".to_string())?;
    let page = resp
        .text()
        .await
        .map_err(|e| format!("Lỗi đọc trang Bing: {e}"))?;
    let session = parse_bing_bootstrap(&page)
        .ok_or_else(|| "Không lấy được token Bing (trang dịch đã đổi định dạng).".to_string())?;
    *guard = Some(session.clone());
    Ok(session)
}

fn bing_chunks(text: &str) -> Vec<String> {
    let mut chunks = Vec::new();
    let mut current = String::new();
    for line in text.split('\n') {
        let mut rem = line;
        while rem.chars().count() > BING_MAX_CHARS {
            if !current.is_empty() {
                chunks.push(std::mem::take(&mut current));
            }
            let split_byte = rem
                .char_indices()
                .nth(BING_MAX_CHARS)
                .map(|(i, _)| i)
                .unwrap_or(rem.len());
            chunks.push(rem[..split_byte].to_string());
            rem = &rem[split_byte..];
        }
        let candidate_len = if current.is_empty() {
            rem.chars().count()
        } else {
            current.chars().count() + 1 + rem.chars().count()
        };
        if !current.is_empty() && candidate_len > BING_MAX_CHARS {
            chunks.push(std::mem::take(&mut current));
            current = rem.to_string();
        } else if current.is_empty() {
            current = rem.to_string();
        } else {
            current.push('\n');
            current.push_str(rem);
        }
    }
    if !current.is_empty() || chunks.is_empty() {
        chunks.push(current);
    }
    chunks
}

async fn translate_bing_chunk(text: &str, from: &str, to: &str) -> Result<String, String> {
    let mut last_err = None;
    for attempt in 0..2 {
        let session = get_bing_session(attempt > 0).await?;
        let count = BING_COUNTER.fetch_add(1, Ordering::Relaxed);
        let url = format!(
            "{BING_TRANSLATE_URL}?isVertical=1&&IG={}&IID={}.{count}",
            session.ig, session.iid
        );
        let body = format!(
            "fromLang={}&text={}&to={}&token={}&key={}",
            urlencoding::encode(from),
            urlencoding::encode(text),
            urlencoding::encode(to),
            urlencoding::encode(&session.token),
            urlencoding::encode(&session.key)
        );
        let resp = BING_CLIENT
            .post(&url)
            .header("Content-Type", "application/x-www-form-urlencoded")
            .body(body)
            .send()
            .await
            .map_err(|_| "Không kết nối được Bing Dịch, vui lòng thử lại sau.".to_string())?;
        let status = resp.status().as_u16();
        if matches!(status, 400 | 401 | 403) && attempt == 0 {
            last_err = Some(format!("Bing trả HTTP {status}"));
            continue;
        }
        if status >= 400 {
            return Err(format!("Bing trả HTTP {status}."));
        }
        let data: Value = resp
            .json()
            .await
            .map_err(|_| "Bing trả dữ liệu JSON không hợp lệ.".to_string())?;
        let Some(arr) = data.as_array() else {
            let sc = data.get("statusCode").and_then(Value::as_i64);
            last_err = Some(format!("Bing từ chối yêu cầu (statusCode {sc:?})."));
            if attempt == 0 {
                continue;
            }
            return Err(last_err.unwrap());
        };
        if let Some(translated) = arr
            .first()
            .and_then(|v| v.get("translations"))
            .and_then(Value::as_array)
            .and_then(|t| t.first())
            .and_then(|t| t.get("text"))
            .and_then(Value::as_str)
        {
            return Ok(translated.to_string());
        }
        return Err("Bing không trả về bản dịch.".to_string());
    }
    Err(last_err.unwrap_or_else(|| "Bing không trả về bản dịch.".to_string()))
}

pub async fn translate_bing(text: &str, source: &str, target: &str) -> Result<String, String> {
    let from = bing_source(source);
    let to = bing_lang(target);
    let mut parts = Vec::new();
    for chunk in bing_chunks(text) {
        parts.push(translate_bing_chunk(&chunk, from, to).await?);
    }
    Ok(parts.join("\n"))
}

pub async fn translate_bing_many(
    texts: &[String],
    source: &str,
    target: &str,
) -> Result<Vec<String>, String> {
    if texts.len() == 1 {
        return Ok(vec![translate_bing(&texts[0], source, target).await?]);
    }
    let flat: Vec<String> = texts
        .iter()
        .map(|t| t.split_whitespace().collect::<Vec<_>>().join(" "))
        .collect();
    let combined = translate_bing(&flat.join("\n"), source, target).await?;
    let lines: Vec<String> = combined
        .lines()
        .map(|l| l.trim().to_string())
        .filter(|l| !l.is_empty())
        .collect();
    if lines.len() == flat.len() {
        Ok(lines)
    } else {
        Ok(split_proportionally(&lines.join(" "), &flat))
    }
}
