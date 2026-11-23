use image::RgbImage;

use crate::ocr::{OcrEngineStatusInfo, TextRegion};

fn win_ocr_lang(language: &str) -> &'static str {
    match language {
        "multi" => "en",
        "jpn+eng" | "jpn" => "ja",
        "eng" | "latin" => "en",
        "vie" => "vi",
        "kor" => "ko",
        "chi_sim" => "zh-Hans",
        "chi_tra" => "zh-Hant",
        "eslav" => "ru",
        _ => "en",
    }
}

pub fn status() -> OcrEngineStatusInfo {
    #[cfg(windows)]
    {
        OcrEngineStatusInfo {
            available: true,
            detail: "Offline · dùng gói ngôn ngữ có sẵn trong Windows (WinRT).".to_string(),
        }
    }
    #[cfg(not(windows))]
    {
        OcrEngineStatusInfo {
            available: false,
            detail: "Windows OCR chỉ hoạt động trên Windows.".to_string(),
        }
    }
}

#[cfg(windows)]
pub fn recognize(img: &RgbImage, language: &str) -> Result<(String, Vec<TextRegion>), String> {
    use windows::core::HSTRING;
    use windows::Globalization::Language;
    use windows::Graphics::Imaging::{BitmapPixelFormat, SoftwareBitmap};
    use windows::Media::Ocr::OcrEngine;
    use windows::Storage::Streams::DataWriter;

    let lang_tag = win_ocr_lang(language);
    let engine = Language::CreateLanguage(&HSTRING::from(lang_tag))
        .ok()
        .and_then(|lang| {
            if OcrEngine::IsLanguageSupported(&lang).unwrap_or(false) {
                OcrEngine::TryCreateFromLanguage(&lang).ok()
            } else {
                None
            }
        })
        .or_else(|| OcrEngine::TryCreateFromUserProfileLanguages().ok())
        .ok_or_else(|| {
            format!(
                "Windows chưa cài gói OCR cho ngôn ngữ '{lang_tag}'. Mở Settings → Time & Language → Language & region để thêm gói ngôn ngữ."
            )
        })?;

    // Convert RgbImage to RGBA8 bytes directly in memory (zero disk I/O)
    let w = img.width();
    let h = img.height();
    let mut rgba = Vec::with_capacity((w * h * 4) as usize);
    for px in img.pixels() {
        rgba.push(px[0]);
        rgba.push(px[1]);
        rgba.push(px[2]);
        rgba.push(255);
    }

    let writer = DataWriter::new().map_err(|e| format!("WinRT DataWriter lỗi: {e}"))?;
    writer
        .WriteBytes(&rgba)
        .map_err(|e| format!("WinRT WriteBytes lỗi: {e}"))?;
    let buffer = writer
        .DetachBuffer()
        .map_err(|e| format!("WinRT DetachBuffer lỗi: {e}"))?;

    let bitmap = SoftwareBitmap::CreateCopyFromBuffer(
        &buffer,
        BitmapPixelFormat::Rgba8,
        w as i32,
        h as i32,
    )
    .map_err(|e| format!("Tạo SoftwareBitmap thất bại: {e}"))?;

    let op = engine
        .RecognizeAsync(&bitmap)
        .map_err(|e| format!("Windows OCR lỗi khởi chạy: {e}"))?;
    let result = op.get().map_err(|e| format!("Windows OCR lỗi nhận dạng: {e}"))?;

    let lines = result
        .Lines()
        .map_err(|e| format!("Không đọc được dòng Windows OCR: {e}"))?;
    let mut text_lines = Vec::new();
    let mut regions = Vec::new();

    for line in lines {
        let line_text = line.Text().map(|s| s.to_string()).unwrap_or_default();
        let trimmed = line_text.trim().to_string();
        if trimmed.is_empty() {
            continue;
        }
        text_lines.push(trimmed.clone());

        if let Ok(words) = line.Words() {
            let mut min_x = i32::MAX;
            let mut min_y = i32::MAX;
            let mut max_x = i32::MIN;
            let mut max_y = i32::MIN;
            let mut has_word = false;
            for word in words {
                if let Ok(rect) = word.BoundingRect() {
                    let l = rect.X.round() as i32;
                    let t = rect.Y.round() as i32;
                    let r = l + (rect.Width.round() as i32).max(1);
                    let b = t + (rect.Height.round() as i32).max(1);
                    min_x = min_x.min(l);
                    min_y = min_y.min(t);
                    max_x = max_x.max(r);
                    max_y = max_y.max(b);
                    has_word = true;
                }
            }
            if has_word && max_x > min_x && max_y > min_y {
                regions.push(TextRegion::new(trimmed, [min_x, min_y, max_x, max_y]));
            }
        }
    }

    let full_text = if text_lines.is_empty() {
        result
            .Text()
            .map(|s| s.to_string())
            .unwrap_or_default()
            .trim()
            .to_string()
    } else {
        text_lines.join("\n")
    };
    Ok((full_text, regions))
}

#[cfg(not(windows))]
pub fn recognize(_img: &RgbImage, _language: &str) -> Result<(String, Vec<TextRegion>), String> {
    Err("Windows OCR chỉ hỗ trợ Windows.".to_string())
}
