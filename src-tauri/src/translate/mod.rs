pub mod bing;
pub mod google;
pub mod llm;

use std::num::NonZeroUsize;

use lru::LruCache;
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use regex::{Regex, RegexBuilder};

use crate::config::GlossaryEntry;
use crate::ocr::TextRegion;

static TRANSLATION_CACHE: Lazy<Mutex<LruCache<(String, String, String), String>>> =
    Lazy::new(|| Mutex::new(LruCache::new(NonZeroUsize::new(2048).unwrap())));

#[derive(Debug, Clone)]
pub struct TranslateParams {
    pub service: String,
    pub target: String,
    pub llm_endpoint: String,
    pub llm_api_key: String,
    pub llm_model: String,
    pub glossary: Vec<GlossaryEntry>,
}

fn normalize_glossary(entries: &[GlossaryEntry]) -> Vec<(String, String)> {
    let mut pairs: Vec<(String, String)> = entries
        .iter()
        .filter_map(|e| {
            let s = e.source.trim();
            let t = e.target.trim();
            if !s.is_empty() && !t.is_empty() {
                Some((s.to_string(), t.to_string()))
            } else {
                None
            }
        })
        .collect();
    pairs.sort_by(|a, b| b.0.len().cmp(&a.0.len()));
    pairs
}

fn glossary_regex(source: &str) -> Option<Regex> {
    let escaped = regex::escape(source);
    let is_ascii_word = source.is_ascii()
        && source.chars().next().is_some_and(|c| c.is_alphanumeric())
        && source.chars().last().is_some_and(|c| c.is_alphanumeric());
    let pat = if is_ascii_word {
        format!(r"\b{escaped}\b")
    } else {
        escaped
    };
    RegexBuilder::new(&pat).case_insensitive(true).build().ok()
}

fn apply_glossary_placeholders(
    texts: &[String],
    entries: &[(String, String)],
) -> (Vec<String>, Vec<(String, String)>) {
    if entries.is_empty() {
        return (texts.to_vec(), Vec::new());
    }
    let mut protected = texts.to_vec();
    let mut mapping = Vec::new();
    for (source, target) in entries {
        let Some(re) = glossary_regex(source) else {
            continue;
        };
        let token = format!("QZX{}Q", mapping.len());
        let mut matched = false;
        for text in &mut protected {
            if re.is_match(text) {
                *text = re.replace_all(text, token.as_str()).into_owned();
                matched = true;
            }
        }
        if matched {
            mapping.push((token, target.clone()));
        }
    }
    (protected, mapping)
}

fn restore_glossary_placeholders(texts: Vec<String>, mapping: &[(String, String)]) -> Vec<String> {
    if mapping.is_empty() {
        return texts;
    }
    let mut restored = texts;
    for (token, target) in mapping {
        if let Ok(re) = RegexBuilder::new(&regex::escape(token))
            .case_insensitive(true)
            .build()
        {
            for text in &mut restored {
                *text = re
                    .replace_all(text, regex::NoExpand(target.as_str()))
                    .into_owned();
            }
        }
    }
    restored
}

pub fn glossary_prompt_hint(text: &str, entries: &[GlossaryEntry]) -> String {
    let normalized = normalize_glossary(entries);
    if normalized.is_empty() {
        return String::new();
    }
    let matched: Vec<String> = normalized
        .iter()
        .filter(|(src, _)| glossary_regex(src).is_some_and(|re| re.is_match(text)))
        .map(|(src, tgt)| format!("{src} => {tgt}"))
        .collect();
    if matched.is_empty() {
        String::new()
    } else {
        format!(
            " Mandatory glossary (use exact translations): {}.",
            matched.join("; ")
        )
    }
}

pub fn split_proportionally(translated: &str, sources: &[String]) -> Vec<String> {
    let count = sources.len();
    if count == 0 {
        return Vec::new();
    }
    let clean = translated.split_whitespace().collect::<Vec<_>>().join(" ");
    let has_cjk = clean.chars().any(|c| (c as u32) >= 0x2E80);
    let spaced = clean.contains(' ') || !has_cjk;
    let units: Vec<String> = if spaced {
        clean.split(' ').map(String::from).collect()
    } else {
        clean.chars().map(|c| c.to_string()).collect()
    };
    let joiner = if spaced { " " } else { "" };
    if units.is_empty() {
        return vec![String::new(); count];
    }
    let weights: Vec<usize> = sources.iter().map(|s| s.trim().chars().count().max(1)).collect();
    let total: usize = weights.iter().sum();
    let mut result = Vec::with_capacity(count);
    let mut start = 0usize;
    let mut acc = 0usize;
    for (idx, w) in weights.iter().enumerate() {
        acc += w;
        let end = if idx == count - 1 {
            units.len()
        } else {
            let mut e = ((units.len() as f64 * acc as f64) / total as f64).round() as usize;
            e = e.min(units.len().saturating_sub(count - idx - 1));
            e = e.max((start + 1).min(units.len()));
            e.max(start)
        };
        result.push(units[start..end].join(joiner));
        start = end;
    }
    result
}

pub async fn translate_text(text: &str, params: &TranslateParams) -> Result<String, String> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Ok(String::new());
    }
    if params.service == "llm" {
        return llm::translate_llm(
            trimmed,
            &params.target,
            &params.llm_endpoint,
            &params.llm_api_key,
            &params.llm_model,
            &params.glossary,
        )
        .await;
    }
    let list = translate_many(&[trimmed.to_string()], params).await?;
    Ok(list.into_iter().next().unwrap_or_default())
}

pub async fn translate_many(
    texts: &[String],
    params: &TranslateParams,
) -> Result<Vec<String>, String> {
    if texts.is_empty() {
        return Ok(Vec::new());
    }
    let entries = normalize_glossary(&params.glossary);
    let gloss_hash = if entries.is_empty() {
        String::new()
    } else {
        let joined = entries
            .iter()
            .map(|(s, t)| format!("{s}={t}"))
            .collect::<Vec<_>>()
            .join("|");
        format!("|g:{}", blake3::hash(joined.as_bytes()).to_hex())
    };
    let service_key = format!("{}{}", params.service, gloss_hash);

    let mut results = vec![String::new(); texts.len()];
    let mut pending: Vec<(String, Vec<usize>)> = Vec::new();
    let mut pending_idx = std::collections::HashMap::<String, usize>::new();

    {
        let mut cache = TRANSLATION_CACHE.lock();
        for (i, raw) in texts.iter().enumerate() {
            let clean = raw.trim();
            if clean.is_empty() {
                continue;
            }
            let norm = clean.split_whitespace().collect::<Vec<_>>().join(" ");
            let key = (service_key.clone(), params.target.clone(), norm);
            if let Some(hit) = cache.get(&key) {
                results[i] = hit.clone();
            } else if let Some(&pos) = pending_idx.get(clean) {
                pending[pos].1.push(i);
            } else {
                pending_idx.insert(clean.to_string(), pending.len());
                pending.push((clean.to_string(), vec![i]));
            }
        }
    }

    if pending.is_empty() {
        return Ok(results);
    }

    let unique: Vec<String> = pending.iter().map(|(s, _)| s.clone()).collect();
    let (outbound, mapping) = apply_glossary_placeholders(&unique, &entries);
    let raw_translated = translate_service_many(&outbound, &params.target, &params.service).await?;
    let translated = restore_glossary_placeholders(raw_translated, &mapping);

    let mut cache = TRANSLATION_CACHE.lock();
    for ((src, indices), val) in pending.into_iter().zip(translated.into_iter()) {
        for idx in indices {
            results[idx] = val.clone();
        }
        if !val.is_empty() {
            let norm = src.split_whitespace().collect::<Vec<_>>().join(" ");
            cache.put((service_key.clone(), params.target.clone(), norm), val);
        }
    }
    Ok(results)
}

async fn translate_service_many(
    texts: &[String],
    target: &str,
    service: &str,
) -> Result<Vec<String>, String> {
    if service == "bing" {
        if let Ok(res) = bing::translate_bing_many(texts, target).await {
            if res.len() == texts.len() && res.iter().all(|s| !s.trim().is_empty()) {
                return Ok(res);
            }
        }
        return google::translate_google_many(texts, target).await;
    }

    if google::google_cooldown_remaining() > 0.0 {
        return translate_bing_while_google_cools(texts, target).await;
    }
    match google::translate_google_many(texts, target).await {
        Ok(res) => Ok(res),
        Err(err) if err.contains("429") || err.contains("giới hạn") => {
            translate_bing_while_google_cools(texts, target).await
        }
        Err(err) => Err(err),
    }
}

async fn translate_bing_while_google_cools(
    texts: &[String],
    target: &str,
) -> Result<Vec<String>, String> {
    if let Ok(res) = bing::translate_bing_many(texts, target).await {
        if res.len() == texts.len() && res.iter().all(|s| !s.trim().is_empty()) {
            return Ok(res);
        }
    }
    let secs = google::google_cooldown_remaining().round().max(1.0) as u64;
    Err(format!(
        "Google Translate đang giới hạn request (429) và Bing không phản hồi. Tự thử lại Google sau khoảng {secs} giây."
    ))
}

pub async fn translate_regions(
    regions: &[TextRegion],
    params: &TranslateParams,
) -> Result<Vec<String>, String> {
    if regions.is_empty() {
        return Ok(Vec::new());
    }
    let wordless: Vec<bool> = regions
        .iter()
        .map(|r| !r.text.chars().any(|c| c.is_alphabetic()))
        .collect();
    if wordless.iter().any(|&w| w) {
        let wordy: Vec<TextRegion> = regions
            .iter()
            .zip(wordless.iter())
            .filter_map(|(r, &skip)| if skip { None } else { Some(r.clone()) })
            .collect();
        let translated = if wordy.is_empty() {
            Vec::new()
        } else {
            Box::pin(translate_regions(&wordy, params)).await?
        };
        let mut iter = translated.into_iter();
        return Ok(regions
            .iter()
            .zip(wordless.iter())
            .map(|(r, &skip)| {
                if skip {
                    r.text.clone()
                } else {
                    iter.next().unwrap_or_default()
                }
            })
            .collect());
    }

    let texts: Vec<String> = regions.iter().map(|r| r.text.clone()).collect();
    if params.service != "llm" {
        return translate_many(&texts, params).await;
    }

    if regions.len() == 1 {
        let one = translate_text(&regions[0].text, params).await?;
        return Ok(vec![one]);
    }
    let flat: Vec<String> = texts
        .iter()
        .map(|t| t.split_whitespace().collect::<Vec<_>>().join(" "))
        .collect();
    let combined = translate_text(&flat.join("\n"), params).await?;
    let lines: Vec<String> = combined
        .lines()
        .map(|l| l.trim().to_string())
        .filter(|l| !l.is_empty())
        .collect();
    if lines.len() == regions.len() {
        Ok(lines)
    } else {
        Ok(split_proportionally(&lines.join(" "), &flat))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn glossary_placeholders_roundtrip() {
        let entries = vec![("HP".to_string(), "Máu".to_string())];
        let input = vec!["Restore 50 HP now".to_string()];
        let (protected, mapping) = apply_glossary_placeholders(&input, &entries);
        assert_eq!(protected[0], "Restore 50 QZX0Q now");
        let restored = restore_glossary_placeholders(
            vec!["Hồi phục 50 qzx0q ngay".to_string()],
            &mapping,
        );
        assert_eq!(restored[0], "Hồi phục 50 Máu ngay");
    }

    #[test]
    fn splits_proportionally_across_lines() {
        let sources = vec!["Short".to_string(), "A much longer sentence here".to_string()];
        let parts = split_proportionally("Ngắn Một câu dài hơn rất nhiều ở đây", &sources);
        assert_eq!(parts.len(), 2);
        assert!(!parts[0].is_empty());
        assert!(!parts[1].is_empty());
    }
}
