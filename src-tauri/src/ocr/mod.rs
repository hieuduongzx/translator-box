pub mod onnx_ocr;
pub mod windows_ocr;

use image::RgbImage;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TextRegion {
    pub text: String,
    pub bbox: [i32; 4],
    pub line_count: usize,
    pub align: String,
}

impl TextRegion {
    pub fn new(text: String, bbox: [i32; 4]) -> Self {
        Self {
            text,
            bbox,
            line_count: 1,
            align: String::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OcrEngineStatusInfo {
    pub available: bool,
    pub detail: String,
}

pub fn ocr_engine_status(engine: &str, model: &str, backend: &str) -> OcrEngineStatusInfo {
    match engine {
        "auto" => {
            let win = ocr_engine_status("windows", model, backend);
            let rapid = ocr_engine_status("rapidocr", model, backend);
            let mut ready = Vec::new();
            if win.available {
                ready.push("Windows OCR");
            }
            if rapid.available {
                ready.push("OCR ngoại tuyến");
            }
            if ready.is_empty() {
                OcrEngineStatusInfo {
                    available: false,
                    detail: "Chưa có engine OCR nào khả dụng.".to_string(),
                }
            } else {
                OcrEngineStatusInfo {
                    available: true,
                    detail: format!("Khả dụng: {}.", ready.join(" → ")),
                }
            }
        }
        "windows" => windows_ocr::status(),
        "rapidocr" => onnx_ocr::status(model, backend),
        other => OcrEngineStatusInfo {
            available: false,
            detail: format!("Engine OCR không được hỗ trợ: {other}"),
        },
    }
}

pub fn ocr_layout(
    img: &RgbImage,
    language: &str,
    engine: &str,
    model: &str,
    backend: &str,
    detail_pass: bool,
) -> Result<Vec<TextRegion>, String> {
    let candidates: &[&str] = match engine {
        "auto" => &["windows", "rapidocr"],
        "windows" => &["windows"],
        "rapidocr" => &["rapidocr"],
        other => return Err(format!("Engine OCR không được hỗ trợ: {other}")),
    };

    let mut errors = Vec::new();
    let mut ran = false;

    for &cand in candidates {
        let st = ocr_engine_status(cand, model, backend);
        if !st.available {
            errors.push(st.detail);
            continue;
        }
        let res = match cand {
            "windows" => windows_ocr::recognize(img, language),
            "rapidocr" => onnx_ocr::recognize(img, model, backend, detail_pass),
            _ => unreachable!(),
        };
        match res {
            Ok((text, regions)) => {
                ran = true;
                if !regions.is_empty() {
                    return Ok(regions);
                }
                if !text.trim().is_empty() {
                    return Ok(vec![TextRegion::new(
                        text.trim().to_string(),
                        [0, 0, img.width() as i32, img.height() as i32],
                    )]);
                }
                if engine != "auto" {
                    return Ok(Vec::new());
                }
            }
            Err(e) => {
                if engine != "auto" {
                    return Err(e);
                }
                let label = if cand == "windows" {
                    "Windows OCR"
                } else {
                    "OCR ngoại tuyến"
                };
                errors.push(format!("{label}: {e}"));
            }
        }
    }

    if !errors.is_empty() && (engine != "auto" || !ran) {
        return Err(if engine != "auto" {
            errors.last().cloned().unwrap_or_default()
        } else {
            errors.join(" | ")
        });
    }
    Ok(Vec::new())
}

// ---------------------------------------------------------------------------
// Layout merging (lines & speech-bubble/dialogue blocks)
// ---------------------------------------------------------------------------

pub fn is_cjk(ch: char) -> bool {
    let code = ch as u32;
    (0x3040..=0x30FF).contains(&code)
        || (0x3400..=0x4DBF).contains(&code)
        || (0x4E00..=0x9FFF).contains(&code)
        || (0xF900..=0xFAFF).contains(&code)
        || (0xAC00..=0xD7A3).contains(&code)
        || (0x3000..=0x303F).contains(&code)
        || (0xFF00..=0xFFEF).contains(&code)
}

fn is_vertical_cjk(r: &TextRegion) -> bool {
    let w = (r.bbox[2] - r.bbox[0]).max(1) as f32;
    let h = (r.bbox[3] - r.bbox[1]).max(1) as f32;
    h > w * 1.35 && r.text.chars().any(is_cjk)
}

fn join_wrapped(prev: &str, nxt: &str) -> String {
    let prev = prev.trim_end();
    let nxt = nxt.trim_start();
    if prev.is_empty() {
        return nxt.to_string();
    }
    if nxt.is_empty() {
        return prev.to_string();
    }
    let a = prev.chars().last().unwrap();
    let b = nxt.chars().next().unwrap();
    if a == '-' && b.is_lowercase() {
        let mut s = prev.to_string();
        s.pop();
        s.push_str(nxt);
        return s;
    }
    if is_cjk(a) || is_cjk(b) {
        format!("{prev}{nxt}")
    } else {
        format!("{prev} {nxt}")
    }
}

fn horizontal_gap(a: &TextRegion, b: &TextRegion) -> i32 {
    (a.bbox[0].max(b.bbox[0]) - a.bbox[2].min(b.bbox[2])).max(0)
}

fn axis_overlap(a0: i32, a1: i32, b0: i32, b1: i32) -> i32 {
    (a1.min(b1) - a0.max(b0)).max(0)
}

struct LineGroup {
    regions: Vec<TextRegion>,
    top: i32,
    bottom: i32,
    center: f32,
    vertical: bool,
}

fn group_into_lines(regions: &[TextRegion]) -> Vec<LineGroup> {
    let mut items: Vec<TextRegion> = regions
        .iter()
        .filter(|r| !r.text.trim().is_empty())
        .cloned()
        .collect();
    if items.is_empty() {
        return Vec::new();
    }
    let mut heights: Vec<i32> = items.iter().map(|r| (r.bbox[3] - r.bbox[1]).max(1)).collect();
    heights.sort_unstable();
    let median_h = heights[heights.len() / 2] as f32;

    items.sort_by(|a, b| {
        let ca = (a.bbox[1] + a.bbox[3]) as f32 / 2.0;
        let cb = (b.bbox[1] + b.bbox[3]) as f32 / 2.0;
        ca.partial_cmp(&cb)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.bbox[0].cmp(&b.bbox[0]))
    });

    let center_cutoff = median_h * 0.78;
    let mut lines: Vec<LineGroup> = Vec::new();

    for region in items {
        let center = (region.bbox[1] + region.bbox[3]) as f32 / 2.0;
        let region_vertical = is_vertical_cjk(&region);
        let mut best_idx: Option<(usize, i32, f32)> = None;

        if !region_vertical {
            for (li, line) in lines.iter().enumerate() {
                if line.vertical {
                    continue;
                }
                let center_delta = (center - line.center).abs();
                if center_delta > center_cutoff {
                    continue;
                }
                let gap = line
                    .regions
                    .iter()
                    .map(|item| horizontal_gap(&region, item))
                    .min()
                    .unwrap_or(i32::MAX);
                let limit = median_h * if gap > 0 { 0.78 } else { 0.55 };
                if center_delta > limit {
                    continue;
                }
                if (gap as f32) <= (median_h * 1.8).max(12.0) {
                    let better = match best_idx {
                        None => true,
                        Some((_, bg, bd)) => gap < bg || (gap == bg && center_delta < bd),
                    };
                    if better {
                        best_idx = Some((li, gap, center_delta));
                    }
                }
            }
        }

        if let Some((li, _, _)) = best_idx {
            let line = &mut lines[li];
            line.top = line.top.min(region.bbox[1]);
            line.bottom = line.bottom.max(region.bbox[3]);
            line.center = (line.top + line.bottom) as f32 / 2.0;
            line.regions.push(region);
        } else {
            lines.push(LineGroup {
                top: region.bbox[1],
                bottom: region.bbox[3],
                center,
                vertical: region_vertical,
                regions: vec![region],
            });
        }
    }

    for line in &mut lines {
        line.regions.sort_by_key(|r| r.bbox[0]);
    }
    lines
}

fn line_text(line: &LineGroup) -> String {
    let mut out = String::new();
    for r in &line.regions {
        let piece = r.text.trim();
        if piece.is_empty() {
            continue;
        }
        if out.is_empty() {
            out.push_str(piece);
        } else {
            out = join_wrapped(&out, piece);
        }
    }
    out
}

fn line_bbox(line: &LineGroup) -> [i32; 4] {
    let mut l = i32::MAX;
    let mut t = i32::MAX;
    let mut r = i32::MIN;
    let mut b = i32::MIN;
    for reg in &line.regions {
        l = l.min(reg.bbox[0]);
        t = t.min(reg.bbox[1]);
        r = r.max(reg.bbox[2]);
        b = b.max(reg.bbox[3]);
    }
    [l, t, r, b]
}

pub fn merge_regions_into_lines(regions: &[TextRegion]) -> Vec<TextRegion> {
    group_into_lines(regions)
        .into_iter()
        .filter_map(|line| {
            let text = line_text(&line);
            if text.is_empty() {
                None
            } else {
                Some(TextRegion::new(text, line_bbox(&line)))
            }
        })
        .collect()
}

fn all_caps(text: &str) -> bool {
    let mut has_alpha = false;
    for ch in text.chars() {
        if ch.is_alphabetic() {
            has_alpha = true;
            if ch.is_lowercase() {
                return false;
            }
        }
    }
    has_alpha
}

fn ends_with_continuation(text: &str) -> bool {
    text.ends_with([',', '-', '–', '—', '、', '，', '…', ':', ';'])
}

fn label_like(text: &str) -> bool {
    let t = text.trim();
    if t.is_empty() || t.chars().any(is_cjk) {
        return false;
    }
    let words = t.split_whitespace().count();
    let first = t.chars().next().unwrap();
    words <= 4
        && (first.is_uppercase() || first.is_ascii_digit())
        && t.chars().any(|c| c.is_lowercase())
        && !ends_with_continuation(t)
        && !t.ends_with(['.', '?', '!', '…', '。', '？', '！'])
}

fn continues_sentence(upper: &TextRegion, lower: &TextRegion, caps_rule: bool) -> bool {
    let top = upper.text.trim_end();
    let bottom = lower.text.trim_start();
    if top.is_empty() || bottom.is_empty() {
        return false;
    }
    let last_c = top.chars().last().unwrap();
    let first_c = bottom.chars().next().unwrap();
    if is_cjk(last_c) || is_cjk(first_c) {
        return true;
    }
    if caps_rule && all_caps(top) && all_caps(bottom) {
        return true;
    }
    ends_with_continuation(top) || first_c.is_lowercase()
}

fn heading_caps(text: &str) -> bool {
    all_caps(text) && text.chars().filter(|c| c.is_alphabetic()).count() >= 4
}

fn style_break(upper: &TextRegion, lower: &TextRegion) -> bool {
    let top = upper.text.trim();
    let bottom = lower.text.trim();
    if top.is_empty() || bottom.is_empty() || bottom.chars().next().unwrap().is_lowercase() {
        return false;
    }
    if top.chars().any(is_cjk) || bottom.chars().any(is_cjk) {
        return false;
    }
    let mixed_top = top.chars().any(|c| c.is_lowercase());
    let mixed_bottom = bottom.chars().any(|c| c.is_lowercase());
    (heading_caps(top) && mixed_bottom) || (mixed_top && heading_caps(bottom))
}

fn row_siblings(lines: &[TextRegion]) -> Vec<bool> {
    let mut flags = vec![false; lines.len()];
    for i in 0..lines.len() {
        let [al, at, ar, ab] = lines[i].bbox;
        for j in (i + 1)..lines.len() {
            let [bl, bt, br, bb] = lines[j].bbox;
            let h = (ab - at).min(bb - bt).max(1) as f32;
            if (axis_overlap(at, ab, bt, bb) as f32) < h * 0.5 {
                continue;
            }
            if (al.max(bl) - ar.min(br)) as f32 > h * 1.5 {
                flags[i] = true;
                flags[j] = true;
            }
        }
    }
    flags
}

fn same_text_block(a: &TextRegion, b: &TextRegion, in_row: bool) -> bool {
    let [al, at, ar, ab] = a.bbox;
    let [bl, bt, br, bb] = b.bbox;
    let aw = (ar - al).max(1) as f32;
    let ah = (ab - at).max(1) as f32;
    let bw = (br - bl).max(1) as f32;
    let bh = (bb - bt).max(1) as f32;

    let vgap = (at.max(bt) - ab.min(bb)).max(0) as f32;
    let hgap = (al.max(bl) - ar.min(br)).max(0) as f32;
    let x_ov = axis_overlap(al, ar, bl, br) as f32;
    let y_ov = axis_overlap(at, ab, bt, bb) as f32;

    let centers_close = (((al + ar) - (bl + br)).abs() as f32) / 2.0 <= aw.max(bw) * 0.58;
    let aligned = x_ov >= aw.min(bw) * 0.18 || centers_close;
    let tight = vgap <= (ah.min(bh) * 0.6).max(6.0);
    let loose = vgap <= (ah.min(bh) * 1.1).max(12.0);
    let (upper, lower) = if at <= bt { (a, b) } else { (b, a) };
    let cont = continues_sentence(upper, lower, true);
    let list_items = !cont && label_like(&upper.text) && label_like(&lower.text);
    let separate = list_items || style_break(upper, lower);
    let joined = if in_row {
        tight && continues_sentence(upper, lower, false)
    } else {
        tight || (loose && cont)
    };
    let stacked = aligned && !separate && joined;

    let adj_cols = is_vertical_cjk(a)
        && is_vertical_cjk(b)
        && hgap <= (aw.min(bw) * 1.5).max(8.0)
        && y_ov >= ah.min(bh) * 0.3;

    stacked || adj_cols
}

fn block_alignment(items: &[TextRegion]) -> String {
    let mut min_l = i32::MAX;
    let mut max_l = i32::MIN;
    let mut min_c = f32::INFINITY;
    let mut max_c = f32::NEG_INFINITY;
    let mut heights: Vec<i32> = items.iter().map(|r| r.bbox[3] - r.bbox[1]).collect();
    heights.sort_unstable();
    let med_h = heights[heights.len() / 2].max(1) as f32;

    for r in items {
        min_l = min_l.min(r.bbox[0]);
        max_l = max_l.max(r.bbox[0]);
        let c = (r.bbox[0] + r.bbox[2]) as f32 / 2.0;
        min_c = min_c.min(c);
        max_c = max_c.max(c);
    }
    let left_spread = (max_l - min_l) as f32;
    let center_spread = max_c - min_c;
    if left_spread <= (med_h * 0.5).max(4.0) && left_spread < center_spread {
        "left".to_string()
    } else {
        "center".to_string()
    }
}

pub fn merge_regions_into_blocks(regions: &[TextRegion]) -> Vec<TextRegion> {
    let line_regions = merge_regions_into_lines(regions);
    let n = line_regions.len();
    if n == 0 {
        return Vec::new();
    }
    let mut parents: Vec<usize> = (0..n).collect();
    let find = |parents: &mut Vec<usize>, mut x: usize| -> usize {
        while parents[x] != x {
            parents[x] = parents[parents[x]];
            x = parents[x];
        }
        x
    };

    let in_row = row_siblings(&line_regions);
    for i in 0..n {
        for j in (i + 1)..n {
            if same_text_block(&line_regions[i], &line_regions[j], in_row[i] || in_row[j]) {
                let ra = find(&mut parents, i);
                let rb = find(&mut parents, j);
                if ra != rb {
                    parents[rb] = ra;
                }
            }
        }
    }

    let mut groups: std::collections::HashMap<usize, Vec<TextRegion>> =
        std::collections::HashMap::new();
    for (i, reg) in line_regions.into_iter().enumerate() {
        let root = find(&mut parents, i);
        groups.entry(root).or_default().push(reg);
    }

    let mut merged: Vec<TextRegion> = groups
        .into_values()
        .map(|mut items| {
            let vertical = items.iter().all(is_vertical_cjk);
            if vertical {
                items.sort_by(|a, b| b.bbox[0].cmp(&a.bbox[0]).then(a.bbox[1].cmp(&b.bbox[1])));
            } else {
                items.sort_by(|a, b| a.bbox[1].cmp(&b.bbox[1]).then(a.bbox[0].cmp(&b.bbox[0])));
            }
            let mut text = String::new();
            let mut l = i32::MAX;
            let mut t = i32::MAX;
            let mut r = i32::MIN;
            let mut b = i32::MIN;
            for it in &items {
                if text.is_empty() {
                    text = it.text.trim().to_string();
                } else {
                    text = join_wrapped(&text, &it.text);
                }
                l = l.min(it.bbox[0]);
                t = t.min(it.bbox[1]);
                r = r.max(it.bbox[2]);
                b = b.max(it.bbox[3]);
            }
            let align = if items.len() > 1 {
                if vertical {
                    "center".to_string()
                } else {
                    block_alignment(&items)
                }
            } else {
                String::new()
            };
            TextRegion {
                text,
                bbox: [l, t, r, b],
                line_count: items.len(),
                align,
            }
        })
        .collect();

    merged.sort_by(|a, b| a.bbox[1].cmp(&b.bbox[1]).then(a.bbox[0].cmp(&b.bbox[0])));
    merged
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn merges_word_boxes_into_single_line() {
        let regions = vec![
            TextRegion::new("Hello".into(), [10, 20, 60, 40]),
            TextRegion::new("world!".into(), [66, 21, 120, 41]),
        ];
        let lines = merge_regions_into_lines(&regions);
        assert_eq!(lines.len(), 1);
        assert_eq!(lines[0].text, "Hello world!");
        assert_eq!(lines[0].bbox, [10, 20, 120, 41]);
    }

    #[test]
    fn merges_stacked_dialogue_lines_into_block() {
        let regions = vec![
            TextRegion::new("This is the first".into(), [10, 10, 180, 30]),
            TextRegion::new("line of dialogue.".into(), [12, 34, 170, 54]),
        ];
        let blocks = merge_regions_into_blocks(&regions);
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].text, "This is the first line of dialogue.");
        assert_eq!(blocks[0].line_count, 2);
        assert_eq!(blocks[0].align, "left");
    }

    #[test]
    fn joins_cjk_without_spaces() {
        let regions = vec![
            TextRegion::new("こんにちは".into(), [10, 10, 100, 30]),
            TextRegion::new("世界".into(), [104, 10, 140, 30]),
        ];
        let lines = merge_regions_into_lines(&regions);
        assert_eq!(lines.len(), 1);
        assert_eq!(lines[0].text, "こんにちは世界");
    }
}
