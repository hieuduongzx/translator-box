use std::collections::HashMap;
use std::num::NonZeroUsize;

use image::RgbImage;
use lru::LruCache;
use once_cell::sync::Lazy;
use parking_lot::Mutex;

use crate::ocr::TextRegion;

#[derive(Debug, Clone)]
pub struct RegionVisual {
    pub rect: [i32; 4],
    pub patch_rgb: Option<Vec<u8>>,
    pub patch_size: Option<(u32, u32)>,
    pub bg: [u8; 3],
    pub fg: [u8; 3],
    pub ink_rect: Option<[i32; 4]>,
    pub stroke_thickness: f32,
    pub line_ink: f32,
    pub outline: Option<[u8; 3]>,
    pub room: Option<[i32; 4]>,
}

type CachedPayload = (
    [u8; 3],
    [u8; 3],
    Option<Vec<u8>>,
    Option<[i32; 4]>,
    f32,
    f32,
    Option<[u8; 3]>,
);

static INPAINT_CACHE: Lazy<Mutex<LruCache<[u8; 32], CachedPayload>>> =
    Lazy::new(|| Mutex::new(LruCache::new(NonZeroUsize::new(96).unwrap())));

fn luma(c: [u8; 3]) -> f32 {
    0.299 * c[0] as f32 + 0.587 * c[1] as f32 + 0.114 * c[2] as f32
}

fn contrasting_text(bg: [u8; 3]) -> [u8; 3] {
    if luma(bg) > 140.0 {
        [24, 24, 24]
    } else {
        [240, 240, 240]
    }
}

fn readable_on(color: [u8; 3], bg: [u8; 3]) -> [u8; 3] {
    let lum_bg = luma(bg);
    if (luma(color) - lum_bg).abs() >= 75.0 {
        return color;
    }
    let toward = if lum_bg < 128.0 {
        [255u8, 255, 255]
    } else {
        [0u8, 0, 0]
    };
    for step in 1..=10 {
        let t = step as f32 / 10.0;
        let mixed = [
            (color[0] as f32 + (toward[0] as f32 - color[0] as f32) * t).round() as u8,
            (color[1] as f32 + (toward[1] as f32 - color[1] as f32) * t).round() as u8,
            (color[2] as f32 + (toward[2] as f32 - color[2] as f32) * t).round() as u8,
        ];
        if (luma(mixed) - lum_bg).abs() >= 75.0 {
            return mixed;
        }
    }
    toward
}

fn padded_rect(bbox: [i32; 4], width: i32, height: i32) -> [i32; 4] {
    let left = bbox[0].clamp(0, (width - 1).max(0));
    let top = bbox[1].clamp(0, (height - 1).max(0));
    let right = bbox[2].clamp(left + 1, width);
    let bottom = bbox[3].clamp(top + 1, height);
    let h = bottom - top;
    let pad_x = (h / 4).clamp(2, 8);
    let pad_y = (h / 10).clamp(1, 3);
    [
        (left - pad_x).max(0),
        (top - pad_y).max(0),
        (right + pad_x).min(width),
        (bottom + pad_y).min(height),
    ]
}

fn dominant_border_bg(
    patch: &[u8],
    pw: usize,
    ph: usize,
    inner: [usize; 4],
) -> [u8; 3] {
    let [il, it, ir, ib] = inner;
    let mut samples: Vec<[u8; 3]> = Vec::new();
    for y in 0..ph {
        for x in 0..pw {
            if x >= il && x < ir && y >= it && y < ib {
                continue;
            }
            let idx = (y * pw + x) * 3;
            samples.push([patch[idx], patch[idx + 1], patch[idx + 2]]);
        }
    }
    if samples.is_empty() {
        for chunk in patch.chunks_exact(3) {
            samples.push([chunk[0], chunk[1], chunk[2]]);
        }
    }
    if samples.is_empty() {
        return [32, 34, 40];
    }
    let mut exact: HashMap<u32, usize> = HashMap::new();
    for c in &samples {
        let code = ((c[0] as u32) << 16) | ((c[1] as u32) << 8) | (c[2] as u32);
        *exact.entry(code).or_insert(0) += 1;
    }
    if let Some((&best_code, &best_count)) = exact.iter().max_by_key(|(_, &cnt)| cnt) {
        if best_count * 100 >= samples.len() * 45 {
            return [
                ((best_code >> 16) & 255) as u8,
                ((best_code >> 8) & 255) as u8,
                (best_code & 255) as u8,
            ];
        }
    }
    let mut buckets: HashMap<u32, (u64, u64, u64, usize)> = HashMap::new();
    for c in &samples {
        let q = (((c[0] >> 3) as u32) << 10) | (((c[1] >> 3) as u32) << 5) | ((c[2] >> 3) as u32);
        let entry = buckets.entry(q).or_insert((0, 0, 0, 0));
        entry.0 += c[0] as u64;
        entry.1 += c[1] as u64;
        entry.2 += c[2] as u64;
        entry.3 += 1;
    }
    if let Some((_, &(sr, sg, sb, n))) = buckets.iter().max_by_key(|(_, v)| v.3) {
        return [
            (sr as f64 / n as f64).round() as u8,
            (sg as f64 / n as f64).round() as u8,
            (sb as f64 / n as f64).round() as u8,
        ];
    }
    [32, 34, 40]
}

fn median_color(patch: &[u8], mask: &[bool]) -> Option<[u8; 3]> {
    let mut rs = Vec::new();
    let mut gs = Vec::new();
    let mut bs = Vec::new();
    for (i, &m) in mask.iter().enumerate() {
        if m {
            let p = i * 3;
            rs.push(patch[p]);
            gs.push(patch[p + 1]);
            bs.push(patch[p + 2]);
        }
    }
    if rs.is_empty() {
        return None;
    }
    rs.sort_unstable();
    gs.sort_unstable();
    bs.sort_unstable();
    let mid = rs.len() / 2;
    Some([rs[mid], gs[mid], bs[mid]])
}

fn otsu_threshold(values: &[f32]) -> f32 {
    let mut hist = [0f64; 64];
    for &v in values {
        let bin = ((v / 256.0) * 64.0).floor().clamp(0.0, 63.0) as usize;
        hist[bin] += 1.0;
    }
    let total: f64 = hist.iter().sum();
    if total <= 0.0 {
        return 128.0;
    }
    let mut sum_all = 0.0;
    for (i, &h) in hist.iter().enumerate() {
        sum_all += h * ((i as f64 + 0.5) * 4.0);
    }
    let mut w_low = 0.0;
    let mut sum_low = 0.0;
    let mut best_var = -1.0;
    let mut best_bin = 32usize;
    for (i, &h) in hist.iter().enumerate() {
        w_low += h;
        let w_high = total - w_low;
        if w_low <= 0.0 || w_high <= 0.0 {
            continue;
        }
        sum_low += h * ((i as f64 + 0.5) * 4.0);
        let m_low = sum_low / w_low;
        let m_high = (sum_all - sum_low) / w_high;
        let var = w_low * w_high * (m_low - m_high).powi(2);
        if var > best_var {
            best_var = var;
            best_bin = i;
        }
    }
    ((best_bin + 1) as f32) * 4.0
}

fn dilate_mask(mask: &[bool], w: usize, h: usize, radius: usize) -> Vec<bool> {
    let mut out = vec![false; w * h];
    for y in 0..h {
        let y0 = y.saturating_sub(radius);
        let y1 = (y + radius).min(h - 1);
        for x in 0..w {
            if !mask[y * w + x] {
                continue;
            }
            let x0 = x.saturating_sub(radius);
            let x1 = (x + radius).min(w - 1);
            for yy in y0..=y1 {
                for xx in x0..=x1 {
                    out[yy * w + xx] = true;
                }
            }
        }
    }
    out
}

/// Fast multi-pass boundary-seeded diffusion inpainting (reconstructs smooth gradients & backgrounds
/// behind masked text strokes in ~1-3ms per region without requiring OpenCV).
fn inpaint_patch(patch: &[u8], mask: &[bool], w: usize, h: usize, fallback_bg: [u8; 3]) -> Vec<u8> {
    let n = w * h;
    let mut cur: Vec<[f32; 3]> = vec![[0.0; 3]; n];
    let mut known: Vec<bool> = vec![false; n];
    let mut unknown_count = 0usize;

    for i in 0..n {
        if !mask[i] {
            cur[i] = [
                patch[i * 3] as f32,
                patch[i * 3 + 1] as f32,
                patch[i * 3 + 2] as f32,
            ];
            known[i] = true;
        } else {
            cur[i] = [
                fallback_bg[0] as f32,
                fallback_bg[1] as f32,
                fallback_bg[2] as f32,
            ];
            unknown_count += 1;
        }
    }
    if unknown_count == 0 {
        return patch.to_vec();
    }

    // Phase 1: Onion-peel inward fill from known border pixels (fast propagation like Telea)
    let mut frontier_known = known.clone();
    let max_peel = (w.max(h)).min(48);
    for _ in 0..max_peel {
        let mut newly_filled: Vec<(usize, [f32; 3])> = Vec::new();
        for y in 0..h {
            for x in 0..w {
                let idx = y * w + x;
                if frontier_known[idx] {
                    continue;
                }
                let mut sum = [0.0f32; 3];
                let mut weight = 0.0f32;
                for dy in -1isize..=1 {
                    let ny = y as isize + dy;
                    if ny < 0 || ny >= h as isize {
                        continue;
                    }
                    for dx in -1isize..=1 {
                        if dx == 0 && dy == 0 {
                            continue;
                        }
                        let nx = x as isize + dx;
                        if nx < 0 || nx >= w as isize {
                            continue;
                        }
                        let nidx = ny as usize * w + nx as usize;
                        if frontier_known[nidx] {
                            let w_dir = if dx == 0 || dy == 0 { 1.0 } else { 0.7 };
                            sum[0] += cur[nidx][0] * w_dir;
                            sum[1] += cur[nidx][1] * w_dir;
                            sum[2] += cur[nidx][2] * w_dir;
                            weight += w_dir;
                        }
                    }
                }
                if weight > 0.0 {
                    newly_filled.push((idx, [sum[0] / weight, sum[1] / weight, sum[2] / weight]));
                }
            }
        }
        if newly_filled.is_empty() {
            break;
        }
        for (idx, val) in newly_filled {
            cur[idx] = val;
            frontier_known[idx] = true;
        }
    }

    // Phase 2: Harmonic smoothing passes inside the masked area for seamless gradients
    let mut next = cur.clone();
    for _ in 0..8 {
        for y in 0..h {
            for x in 0..w {
                let idx = y * w + x;
                if !mask[idx] {
                    continue;
                }
                let mut sum = [0.0f32; 3];
                let mut cnt = 0.0f32;
                if x > 0 {
                    let c = cur[idx - 1];
                    sum[0] += c[0];
                    sum[1] += c[1];
                    sum[2] += c[2];
                    cnt += 1.0;
                }
                if x + 1 < w {
                    let c = cur[idx + 1];
                    sum[0] += c[0];
                    sum[1] += c[1];
                    sum[2] += c[2];
                    cnt += 1.0;
                }
                if y > 0 {
                    let c = cur[idx - w];
                    sum[0] += c[0];
                    sum[1] += c[1];
                    sum[2] += c[2];
                    cnt += 1.0;
                }
                if y + 1 < h {
                    let c = cur[idx + w];
                    sum[0] += c[0];
                    sum[1] += c[1];
                    sum[2] += c[2];
                    cnt += 1.0;
                }
                if cnt > 0.0 {
                    next[idx] = [sum[0] / cnt, sum[1] / cnt, sum[2] / cnt];
                }
            }
        }
        cur.copy_from_slice(&next);
    }

    let mut out = vec![0u8; n * 3];
    for i in 0..n {
        out[i * 3] = cur[i][0].round().clamp(0.0, 255.0) as u8;
        out[i * 3 + 1] = cur[i][1].round().clamp(0.0, 255.0) as u8;
        out[i * 3 + 2] = cur[i][2].round().clamp(0.0, 255.0) as u8;
    }
    out
}

fn analyze_region_payload(
    patch: &[u8],
    pw: usize,
    ph: usize,
    inner: [usize; 4],
) -> CachedPayload {
    let [il, it, ir, ib] = inner;
    let bg = dominant_border_bg(patch, pw, ph, inner);
    let fallback_fg = contrasting_text(bg);
    if pw < 2 || ph < 2 {
        return (bg, fallback_fg, None, None, 0.0, 0.0, None);
    }

    let n = pw * ph;
    let mut diff = vec![0u8; n];
    let mut stroke = vec![false; n];
    let mut stroke_count = 0usize;

    for y in 0..ph {
        for x in 0..pw {
            let idx = y * pw + x;
            let p = idx * 3;
            let d = patch[p]
                .abs_diff(bg[0])
                .max(patch[p + 1].abs_diff(bg[1]))
                .max(patch[p + 2].abs_diff(bg[2]));
            diff[idx] = d;
            if x >= il && x < ir && y >= it && y < ib && d > 55 {
                stroke[idx] = true;
                stroke_count += 1;
            }
        }
    }

    if stroke_count < 4 || stroke_count * 10 > n * 7 {
        return (bg, fallback_fg, None, None, 0.0, 0.0, None);
    }

    // Separate core text color vs optional outline color (e.g. white text with black border)
    let mut rim_color: Option<[u8; 3]> = None;
    let mut core_color: Option<[u8; 3]> = None;
    let mut core_mask = stroke.clone();

    if stroke_count >= 40 {
        let mut stroke_lumas = Vec::with_capacity(stroke_count);
        for i in 0..n {
            if stroke[i] {
                stroke_lumas.push(luma([patch[i * 3], patch[i * 3 + 1], patch[i * 3 + 2]]));
            }
        }
        let thr = otsu_threshold(&stroke_lumas);
        let mut dark = vec![false; n];
        let mut light = vec![false; n];
        let mut n_dark = 0usize;
        let mut n_light = 0usize;
        for i in 0..n {
            if stroke[i] {
                let l = luma([patch[i * 3], patch[i * 3 + 1], patch[i * 3 + 2]]);
                if l < thr {
                    dark[i] = true;
                    n_dark += 1;
                } else {
                    light[i] = true;
                    n_light += 1;
                }
            }
        }
        if n_dark.min(n_light) * 100 >= stroke_count * 12 {
            // Count border pixels touching non-stroke background
            let mut edge_dark = 0usize;
            let mut edge_light = 0usize;
            for y in 0..ph {
                for x in 0..pw {
                    let idx = y * pw + x;
                    if !stroke[idx] {
                        continue;
                    }
                    let touches_bg = x == 0
                        || y == 0
                        || x + 1 == pw
                        || y + 1 == ph
                        || !stroke[idx - 1]
                        || !stroke[idx + 1]
                        || !stroke[idx - pw]
                        || !stroke[idx + pw];
                    if touches_bg {
                        if dark[idx] {
                            edge_dark += 1;
                        } else {
                            edge_light += 1;
                        }
                    }
                }
            }
            let r_dark = edge_dark as f32 / n_dark as f32;
            let r_light = edge_light as f32 / n_light as f32;
            let (rim_m, c_m, rim_edge, core_edge) = if r_dark > r_light {
                (&dark, &light, r_dark, r_light)
            } else {
                (&light, &dark, r_light, r_dark)
            };
            if let (Some(rim), Some(core)) = (median_color(patch, rim_m), median_color(patch, c_m)) {
                let lum_c = luma(core);
                let lum_r = luma(rim);
                let lum_b = luma(bg);
                let antialias = lum_r >= lum_c.min(lum_b) - 20.0
                    && lum_r <= lum_c.max(lum_b) + 20.0;
                if !antialias
                    && (lum_r - lum_c).abs() >= 90.0
                    && rim_edge >= core_edge + 0.12
                {
                    core_color = Some(core);
                    rim_color = Some(rim);
                    core_mask = c_m.clone();
                }
            }
        }
    }

    if core_color.is_none() {
        let mut diffs: Vec<u8> = (0..n).filter(|&i| stroke[i]).map(|i| diff[i]).collect();
        diffs.sort_unstable();
        let q60 = diffs[(diffs.len() * 60) / 100];
        let pure: Vec<bool> = (0..n).map(|i| stroke[i] && diff[i] >= q60).collect();
        let pure_cnt = pure.iter().filter(|&&b| b).count();
        core_color = median_color(patch, if pure_cnt >= 3 { &pure } else { &stroke });
    }

    let chosen_fg = match (core_color, rim_color) {
        (None, _) => fallback_fg,
        (Some(c), Some(_)) => c,
        (Some(c), None) => readable_on(c, bg),
    };

    // Ink metrics (tight bounding box & stroke thickness)
    let near_stroke = dilate_mask(&stroke, pw, ph, 2);
    let outline_mask: Vec<bool> = if rim_color.is_some() {
        core_mask.clone()
    } else {
        (0..n)
            .map(|i| {
                let x = i % pw;
                let y = i / pw;
                x >= il && x < ir && y >= it && y < ib && diff[i] > 26 && near_stroke[i]
            })
            .collect()
    };

    let mut min_x = pw;
    let mut min_y = ph;
    let mut max_x = 0usize;
    let mut max_y = 0usize;
    let mut any_ink = false;
    let mut row_has_ink = vec![false; ph];

    for y in 0..ph {
        for x in 0..pw {
            if outline_mask[y * pw + x] {
                any_ink = true;
                row_has_ink[y] = true;
                min_x = min_x.min(x);
                min_y = min_y.min(y);
                max_x = max_x.max(x);
                max_y = max_y.max(y);
            }
        }
    }

    let ink_box = if any_ink {
        Some([min_x as i32, min_y as i32, (max_x + 1) as i32, (max_y + 1) as i32])
    } else {
        None
    };

    let mut starts = 0usize;
    let mut core_sum = 0usize;
    for y in 0..ph {
        for x in 0..pw {
            let cur = core_mask[y * pw + x];
            if cur {
                core_sum += 1;
                if x == 0 || !core_mask[y * pw + x - 1] {
                    starts += 1;
                }
            }
        }
    }
    let thickness = core_sum as f32 / starts.max(1) as f32;

    // Single-line ink height in multi-line blocks
    let mut bands = Vec::new();
    let mut start: Option<usize> = None;
    let mut end = 0usize;
    let mut gap = 0usize;
    for (y, &has) in row_has_ink.iter().enumerate() {
        if has {
            if start.is_none() {
                start = Some(y);
            }
            end = y;
            gap = 0;
        } else if let Some(s) = start {
            gap += 1;
            if gap > 2 {
                bands.push(end - s + 1);
                start = None;
            }
        }
    }
    if let Some(s) = start {
        bands.push(end - s + 1);
    }
    let line_ink = if bands.len() >= 2 {
        let tallest = *bands.iter().max().unwrap_or(&0) as f32;
        let mut kept: Vec<usize> = bands
            .into_iter()
            .filter(|&b| (b as f32) >= tallest * 0.35)
            .collect();
        kept.sort_unstable();
        if kept.len() >= 2 {
            kept[kept.len() / 2] as f32
        } else {
            0.0
        }
    } else {
        0.0
    };

    let dilated = dilate_mask(&stroke, pw, ph, 1);
    let cleaned = inpaint_patch(patch, &dilated, pw, ph, bg);
    (bg, chosen_fg, Some(cleaned), ink_box, thickness, line_ink, rim_color)
}

fn hard_edge_integral(img: &RgbImage) -> (usize, usize, Vec<u32>) {
    let w = img.width() as usize;
    let h = img.height() as usize;
    let raw = img.as_raw();
    let mut table = vec![0u32; (w + 1) * (h + 1)];
    for y in 0..h {
        let mut row_sum = 0u32;
        for x in 0..w {
            let p = (y * w + x) * 3;
            let mut edge = 0u32;
            if x + 1 < w {
                let q = p + 3;
                let d = raw[p]
                    .abs_diff(raw[q])
                    .max(raw[p + 1].abs_diff(raw[q + 1]))
                    .max(raw[p + 2].abs_diff(raw[q + 2]));
                if d > 40 {
                    edge = 1;
                }
            }
            if edge == 0 && y + 1 < h {
                let q = p + w * 3;
                let d = raw[p]
                    .abs_diff(raw[q])
                    .max(raw[p + 1].abs_diff(raw[q + 1]))
                    .max(raw[p + 2].abs_diff(raw[q + 2]));
                if d > 40 {
                    edge = 1;
                }
            }
            row_sum += edge;
            table[(y + 1) * (w + 1) + (x + 1)] = table[y * (w + 1) + (x + 1)] + row_sum;
        }
    }
    (w, h, table)
}

fn rect_is_clean(w: usize, table: &[u32], x0: i32, y0: i32, x1: i32, y1: i32) -> bool {
    if x1 <= x0 || y1 <= y0 {
        return false;
    }
    let stride = w + 1;
    let (x0, y0, x1, y1) = (x0 as usize, y0 as usize, x1 as usize, y1 as usize);
    let sum = table[y1 * stride + x1] + table[y0 * stride + x0]
        - table[y0 * stride + x1]
        - table[y1 * stride + x0];
    sum == 0
}

fn free_room(w: usize, h: usize, table: &[u32], start: [i32; 4], line_h: i32) -> [i32; 4] {
    let left = start[0].max(0);
    let top = start[1].max(0);
    let right = start[2].min(w as i32);
    let bottom = start[3].min(h as i32);
    if right - left < 2 || bottom - top < 2 {
        return [left, top, right, bottom];
    }
    let limit_x = (right - left).max(line_h * 8);
    let limit_y = line_h * 3;
    let bounds = [
        (left - limit_x).max(0),
        (top - limit_y).max(0),
        (right + limit_x).min(w as i32),
        (bottom + limit_y).min(h as i32),
    ];
    let mut b = [left, top, right, bottom];
    let mut moving = [true; 4];
    while moving.iter().any(|&m| m) {
        for side in [0usize, 2, 1, 3] {
            if !moving[side] {
                continue;
            }
            let ok = match side {
                0 => {
                    let nw = (b[0] - 2).max(bounds[0]);
                    if nw < b[0] && rect_is_clean(w, table, nw, b[1], b[0], b[3]) {
                        b[0] = nw;
                        true
                    } else {
                        false
                    }
                }
                2 => {
                    let nw = (b[2] + 2).min(bounds[2]);
                    if nw > b[2] && rect_is_clean(w, table, b[2], b[1], nw, b[3]) {
                        b[2] = nw;
                        true
                    } else {
                        false
                    }
                }
                1 => {
                    let nh = (b[1] - 2).max(bounds[1]);
                    if nh < b[1] && rect_is_clean(w, table, b[0], nh, b[2], b[1]) {
                        b[1] = nh;
                        true
                    } else {
                        false
                    }
                }
                _ => {
                    let nh = (b[3] + 2).min(bounds[3]);
                    if nh > b[3] && rect_is_clean(w, table, b[0], b[3], b[2], nh) {
                        b[3] = nh;
                        true
                    } else {
                        false
                    }
                }
            };
            moving[side] = ok;
        }
    }
    b
}

pub fn reconstruct_layout(img: &RgbImage, regions: &[TextRegion]) -> ((u32, u32), Vec<RegionVisual>) {
    let w = img.width();
    let h = img.height();
    let raw = img.as_raw();
    let mut visuals = Vec::with_capacity(regions.len());
    let mut edge_table: Option<(usize, usize, Vec<u32>)> = None;

    for region in regions {
        let rect = padded_rect(region.bbox, w as i32, h as i32);
        let [ol, ot, or, ob] = rect;
        let pw = (or - ol).max(1) as usize;
        let ph = (ob - ot).max(1) as usize;
        let mut patch = vec![0u8; pw * ph * 3];
        for y in 0..ph {
            let src_start = (((ot as usize + y) * w as usize) + ol as usize) * 3;
            let dst_start = y * pw * 3;
            patch[dst_start..dst_start + pw * 3]
                .copy_from_slice(&raw[src_start..src_start + pw * 3]);
        }

        let inner = [
            (region.bbox[0].clamp(0, w as i32) - ol).max(0) as usize,
            (region.bbox[1].clamp(0, h as i32) - ot).max(0) as usize,
            ((region.bbox[2].clamp(0, w as i32) - ol).max(0) as usize).min(pw),
            ((region.bbox[3].clamp(0, h as i32) - ot).max(0) as usize).min(ph),
        ];

        let mut hasher = blake3::Hasher::new();
        hasher.update(format!("{pw}x{ph}:{inner:?}\n").as_bytes());
        hasher.update(&patch);
        let key: [u8; 32] = *hasher.finalize().as_bytes();

        let payload = {
            let mut cache = INPAINT_CACHE.lock();
            cache.get(&key).cloned()
        }
        .unwrap_or_else(|| {
            let computed = analyze_region_payload(&patch, pw, ph, inner);
            INPAINT_CACHE.lock().put(key, computed.clone());
            computed
        });

        let (bg, fg, rgb, ink_box, thickness, line_ink, rim) = payload;
        if rgb.is_none() {
            visuals.push(RegionVisual {
                rect,
                patch_rgb: None,
                patch_size: None,
                bg,
                fg,
                ink_rect: None,
                stroke_thickness: 0.0,
                line_ink: 0.0,
                outline: None,
                room: None,
            });
            continue;
        }
        let ink_rect = ink_box.map(|[l, t, r, b]| [ol + l, ot + t, ol + r, ot + b]);
        let lines = region.line_count.max(1) as i32;
        let line_h = ((ob - ot) / lines).max(4);
        let (tw, th, tbl) = edge_table.get_or_insert_with(|| hard_edge_integral(img));
        let room = free_room(*tw, *th, tbl, rect, line_h);
        visuals.push(RegionVisual {
            rect,
            patch_rgb: rgb,
            patch_size: Some((pw as u32, ph as u32)),
            bg,
            fg,
            ink_rect,
            stroke_thickness: thickness,
            line_ink,
            outline: rim,
            room: Some(room),
        });
    }

    ((w, h), visuals)
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::Rgb;

    #[test]
    fn reconstructs_solid_background_with_dark_text() {
        let mut img = RgbImage::from_pixel(120, 40, Rgb([240, 240, 240]));
        for y in 12..28 {
            for x in 20..80 {
                if (x + y) % 3 == 0 {
                    img.put_pixel(x, y, Rgb([15, 15, 15]));
                }
            }
        }
        let regions = vec![TextRegion::new("Sample".into(), [18, 10, 82, 30])];
        let ((w, h), visuals) = reconstruct_layout(&img, &regions);
        assert_eq!((w, h), (120, 40));
        assert_eq!(visuals.len(), 1);
        assert!(visuals[0].patch_rgb.is_some());
        assert_eq!(visuals[0].bg, [240, 240, 240]);
    }
}
