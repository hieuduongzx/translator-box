use std::time::Duration;

use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::{json, Map, Value};
use url::Url;

use crate::config::GlossaryEntry;
use crate::constants::target_language_name;
use crate::translate::glossary_prompt_hint;

static LLM_CLIENT: Lazy<reqwest::Client> = Lazy::new(|| {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(45))
        .user_agent("Translator2k-Rust/2.1")
        .build()
        .expect("Failed to build LLM HTTP client")
});

static OPENAI_NO_REASONING: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^gpt-(6(\.\d+)?-(luna|terra)|5\.[1-9])").unwrap());
static OPENAI_REASONING: Lazy<Regex> = Lazy::new(|| Regex::new(r"^(gpt-[5-9]|o\d)").unwrap());

fn request_tuning(endpoint: &str, model: &str) -> Map<String, Value> {
    let host = Url::parse(endpoint)
        .ok()
        .and_then(|u| u.host_str().map(|s| s.to_lowercase()))
        .unwrap_or_default();
    let name = model
        .trim()
        .to_lowercase()
        .rsplit('/')
        .next()
        .unwrap_or("")
        .to_string();

    let mut map = Map::new();
    if host == "api.openai.com" {
        if OPENAI_NO_REASONING.is_match(&name) {
            map.insert("reasoning_effort".into(), json!("none"));
        } else if OPENAI_REASONING.is_match(&name) {
            map.insert("reasoning_effort".into(), json!("low"));
        } else {
            map.insert("temperature".into(), json!(0.1));
        }
        return map;
    }
    if host == "generativelanguage.googleapis.com" {
        if name.starts_with("gemini-2.5-flash") {
            map.insert("reasoning_effort".into(), json!("none"));
            map.insert("temperature".into(), json!(0.1));
        } else if name.starts_with("gemini-2.5") {
            map.insert("reasoning_effort".into(), json!("low"));
            map.insert("temperature".into(), json!(0.1));
        } else if name.starts_with("gemini-") {
            map.insert("reasoning_effort".into(), json!("low"));
        } else {
            map.insert("temperature".into(), json!(0.1));
        }
        return map;
    }
    map.insert("temperature".into(), json!(0.1));
    map
}

fn format_http_error(code: u16, detail: &str) -> String {
    let base = match code {
        400 => "Yêu cầu tới provider AI không hợp lệ (HTTP 400). Kiểm tra lại tên model trong Dịch vụ AI.".to_string(),
        401 => "API key không hợp lệ hoặc đã hết hạn (HTTP 401). Mở Dịch vụ AI để kiểm tra lại key.".to_string(),
        403 => "API key không có quyền truy cập model này (HTTP 403). Kiểm tra quyền hoặc đổi model trong Dịch vụ AI.".to_string(),
        404 => "Không tìm thấy model hoặc endpoint (HTTP 404). Kiểm tra lại tên model và URL trong Dịch vụ AI.".to_string(),
        429 => "Provider AI đang giới hạn tần suất hoặc hết hạn mức (HTTP 429). Chờ ít giây rồi thử lại hoặc đổi dịch vụ.".to_string(),
        c if c >= 500 => format!("Máy chủ provider AI đang gặp sự cố tạm thời (HTTP {c}). Thử lại sau hoặc chuyển sang Google/Bing."),
        c => format!("Provider AI trả về HTTP {c}."),
    };
    if detail.is_empty() {
        base
    } else {
        format!("{base} Chi tiết: {detail}")
    }
}

fn extract_error_detail(body: &str) -> String {
    let trimmed = body.trim();
    if trimmed.is_empty() {
        return String::new();
    }
    if let Ok(val) = serde_json::from_str::<Value>(trimmed) {
        let obj = if let Some(arr) = val.as_array() {
            arr.first().unwrap_or(&val)
        } else {
            &val
        };
        let candidates = [
            obj.get("error").and_then(|e| e.get("message")).and_then(Value::as_str),
            obj.get("error").and_then(|e| e.get("status")).and_then(Value::as_str),
            obj.get("error").and_then(Value::as_str),
            obj.get("message").and_then(Value::as_str),
            obj.get("detail").and_then(Value::as_str),
        ];
        for c in candidates.into_iter().flatten() {
            let clean = c.split_whitespace().collect::<Vec<_>>().join(" ");
            if !clean.is_empty() {
                return clean.chars().take(180).collect();
            }
        }
    }
    trimmed
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .chars()
        .take(160)
        .collect()
}

fn content_from_message(val: &Value) -> String {
    if let Some(s) = val.as_str() {
        return s.to_string();
    }
    if let Some(arr) = val.as_array() {
        return arr
            .iter()
            .filter_map(|item| {
                let kind = item.get("type").and_then(Value::as_str);
                if matches!(kind, None | Some("text")) {
                    item.get("text").and_then(Value::as_str)
                } else {
                    None
                }
            })
            .collect::<String>();
    }
    String::new()
}

fn content_from_completion(payload: &Value) -> String {
    payload
        .get("choices")
        .and_then(Value::as_array)
        .and_then(|c| c.first())
        .and_then(|c| c.get("message"))
        .and_then(|m| m.get("content"))
        .map(content_from_message)
        .unwrap_or_default()
}

fn llm_content_from_body(raw: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return String::new();
    }
    // Try decoding first JSON object (handles trailing `data: [DONE]`).
    let mut de = serde_json::Deserializer::from_str(trimmed).into_iter::<Value>();
    if let Some(Ok(val)) = de.next() {
        let content = content_from_completion(&val);
        if !content.is_empty() {
            return content;
        }
    }
    // SSE fallback
    let mut deltas = Vec::new();
    let mut completion = String::new();
    for line in trimmed.lines() {
        let l = line.trim();
        let Some(rest) = l.strip_prefix("data:") else {
            continue;
        };
        let chunk = rest.trim();
        if chunk.is_empty() || chunk == "[DONE]" {
            continue;
        }
        if let Ok(payload) = serde_json::from_str::<Value>(chunk) {
            if let Some(delta) = payload
                .get("choices")
                .and_then(Value::as_array)
                .and_then(|c| c.first())
                .and_then(|c| c.get("delta"))
                .and_then(|d| d.get("content"))
                .and_then(Value::as_str)
            {
                deltas.push(delta.to_string());
            }
            let comp = content_from_completion(&payload);
            if !comp.is_empty() {
                completion = comp;
            }
        }
    }
    let joined = deltas.join("");
    if !joined.is_empty() {
        joined
    } else {
        completion
    }
}

pub async fn translate_llm(
    text: &str,
    source: &str,
    target: &str,
    endpoint: &str,
    api_key: &str,
    model: &str,
    glossary: &[GlossaryEntry],
    preserve_formatting: bool,
) -> Result<String, String> {
    let endpoint = endpoint.trim().trim_end_matches('/');
    if !endpoint.starts_with("http://") && !endpoint.starts_with("https://") {
        return Err("Endpoint LLM không hợp lệ.".to_string());
    }
    if api_key.trim().is_empty() {
        return Err("Provider AI chưa có API key. Mở Dịch vụ AI để nhập key.".to_string());
    }
    if model.trim().is_empty() {
        return Err("Chưa chọn model LLM.".to_string());
    }

    let language = target_language_name(target);
    let source_clause = if source.trim().is_empty() || source.eq_ignore_ascii_case("auto") {
        String::new()
    } else {
        format!(" from {}", target_language_name(source.trim()))
    };
    let format_clause = if preserve_formatting {
        "preserve line breaks, paragraph spacing, and meaning"
    } else {
        "merge unnecessary hard line wraps into clean natural text while preserving meaning"
    };
    let glossary_hint = glossary_prompt_hint(text, glossary);
    let system_prompt = format!(
        "Translate the user's text{source_clause} into {language}. Return only the translation, {format_clause}. Do not add explanations, labels, quotes, or markdown.{glossary_hint}"
    );

    let base_payload = json!({
        "model": model,
        "stream": false,
        "messages": [
            { "role": "system", "content": system_prompt },
            { "role": "user", "content": text }
        ]
    });

    let tuning = request_tuning(endpoint, model);
    let mut tuned_payload = base_payload.clone();
    if let Some(obj) = tuned_payload.as_object_mut() {
        for (k, v) in &tuning {
            obj.insert(k.clone(), v.clone());
        }
    }

    let url = format!("{endpoint}/chat/completions");
    let send_once = |body: Value| {
        let url = url.clone();
        let key = api_key.trim().to_string();
        async move {
            let resp = LLM_CLIENT
                .post(&url)
                .header("Authorization", format!("Bearer {key}"))
                .header("Content-Type", "application/json")
                .json(&body)
                .send()
                .await
                .map_err(|e| {
                    if e.is_timeout() {
                        "Endpoint LLM phản hồi quá thời gian cho phép. Thử lại sau hoặc chọn model nhanh hơn.".to_string()
                    } else {
                        format!("Không kết nối được endpoint LLM: {e}. Kiểm tra mạng hoặc URL endpoint.")
                    }
                })?;
            let status = resp.status().as_u16();
            let raw = resp
                .text()
                .await
                .map_err(|_| "Endpoint LLM trả về dữ liệu không hợp lệ.".to_string())?;
            Ok::<(u16, String), String>((status, raw))
        }
    };

    let (status, raw) = send_once(tuned_payload).await?;
    let (status, raw) = if status == 400 && !tuning.is_empty() {
        send_once(base_payload).await?
    } else {
        (status, raw)
    };

    if status >= 400 {
        let detail = extract_error_detail(&raw);
        return Err(format_http_error(status, &detail));
    }
    let content = llm_content_from_body(&raw);
    let trimmed = content.trim();
    if trimmed.is_empty() {
        return Err("Provider AI không trả về bản dịch.".to_string());
    }
    Ok(trimmed.to_string())
}
