use image::{imageops, DynamicImage, RgbImage};

#[derive(Debug, Clone)]
pub struct CapturedFrame {
    pub image: RgbImage,
    pub signature: Vec<u8>,
}

/// Fast Win32 GDI BitBlt capture of a virtual-desktop rectangle `(left, top, right, bottom)`.
/// Automatically uses per-monitor DPI awareness and excludes layered windows (overlays).
#[cfg(windows)]
pub fn grab_screen_rgb(bbox: [i32; 4]) -> Result<RgbImage, String> {
    use std::ffi::c_void;
    use windows::Win32::Graphics::Gdi::{
        BitBlt, CreateCompatibleDC, CreateDIBSection, DeleteDC, DeleteObject, GetDC, ReleaseDC,
        SelectObject, BITMAPINFO, BITMAPINFOHEADER, BI_RGB, DIB_RGB_COLORS, SRCCOPY,
    };
    use windows::Win32::UI::HiDpi::{
        SetThreadDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE,
    };

    let [left, top, right, bottom] = bbox;
    let width = right - left;
    let height = bottom - top;
    if width <= 0 || height <= 0 {
        return Err(format!("Vùng chụp không hợp lệ: {bbox:?}"));
    }

    unsafe {
        let prev_dpi = SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE);
        let screen_dc = GetDC(None);
        if screen_dc.is_invalid() {
            if !prev_dpi.0.is_null() {
                let _ = SetThreadDpiAwarenessContext(prev_dpi);
            }
            return Err("Không lấy được DC màn hình (GetDC thất bại).".to_string());
        }

        let mem_dc = CreateCompatibleDC(screen_dc);
        if mem_dc.is_invalid() {
            ReleaseDC(None, screen_dc);
            if !prev_dpi.0.is_null() {
                let _ = SetThreadDpiAwarenessContext(prev_dpi);
            }
            return Err("CreateCompatibleDC thất bại.".to_string());
        }

        let bmi = BITMAPINFO {
            bmiHeader: BITMAPINFOHEADER {
                biSize: std::mem::size_of::<BITMAPINFOHEADER>() as u32,
                biWidth: width,
                biHeight: -height, // top-down
                biPlanes: 1,
                biBitCount: 32,
                biCompression: BI_RGB.0,
                biSizeImage: 0,
                biXPelsPerMeter: 0,
                biYPelsPerMeter: 0,
                biClrUsed: 0,
                biClrImportant: 0,
            },
            bmiColors: [Default::default()],
        };

        let mut bits: *mut c_void = std::ptr::null_mut();
        let hbitmap = CreateDIBSection(mem_dc, &bmi, DIB_RGB_COLORS, &mut bits, None, 0);
        let result = match hbitmap {
            Ok(hbmp) if !hbmp.is_invalid() && !bits.is_null() => {
                let old_obj = SelectObject(mem_dc, hbmp);
                let blt_ok = BitBlt(mem_dc, 0, 0, width, height, screen_dc, left, top, SRCCOPY);
                let out = if blt_ok.is_ok() {
                    let pixel_count = (width as usize) * (height as usize);
                    let src = std::slice::from_raw_parts(bits as *const u8, pixel_count * 4);
                    let mut rgb = vec![0u8; pixel_count * 3];
                    for i in 0..pixel_count {
                        let s = i * 4;
                        let d = i * 3;
                        rgb[d] = src[s + 2];     // R
                        rgb[d + 1] = src[s + 1]; // G
                        rgb[d + 2] = src[s];     // B
                    }
                    RgbImage::from_raw(width as u32, height as u32, rgb)
                        .ok_or_else(|| "Không dựng được ảnh RGB từ bộ đệm màn hình.".to_string())
                } else {
                    Err("BitBlt chụp màn hình thất bại.".to_string())
                };
                SelectObject(mem_dc, old_obj);
                let _ = DeleteObject(hbmp);
                out
            }
            _ => Err("CreateDIBSection thất bại.".to_string()),
        };

        let _ = DeleteDC(mem_dc);
        ReleaseDC(None, screen_dc);
        if !prev_dpi.0.is_null() {
            let _ = SetThreadDpiAwarenessContext(prev_dpi);
        }
        result
    }
}

#[cfg(not(windows))]
pub fn grab_screen_rgb(_bbox: [i32; 4]) -> Result<RgbImage, String> {
    Err("Chụp màn hình GDI chỉ hỗ trợ Windows.".to_string())
}

/// Capture a screen region, downscaling if longest side > 1800px, and compute a 48x48 grayscale signature.
pub fn capture_region(bbox: [i32; 4]) -> Result<CapturedFrame, String> {
    let mut img = grab_screen_rgb(bbox)?;
    let longest = img.width().max(img.height());
    if longest > 1800 {
        let scale = 1800.0 / longest as f32;
        let nw = (img.width() as f32 * scale).round().max(1.0) as u32;
        let nh = (img.height() as f32 * scale).round().max(1.0) as u32;
        img = imageops::resize(&img, nw, nh, imageops::FilterType::Triangle);
    }
    let sig = image_signature(&img);
    Ok(CapturedFrame {
        image: img,
        signature: sig,
    })
}

/// 48x48 grayscale signature used to detect whether a Live region's pixels changed.
pub fn image_signature(img: &RgbImage) -> Vec<u8> {
    let gray = DynamicImage::ImageRgb8(img.clone()).into_luma8();
    imageops::resize(&gray, 48, 48, imageops::FilterType::Triangle).into_raw()
}

/// Returns true if two 48x48 signatures differ meaningfully (matches Python `_sig_differs`).
pub fn signature_differs(prev: &[u8], curr: &[u8]) -> bool {
    if prev.len() != curr.len() || prev.is_empty() {
        return true;
    }
    let mut total_diff: u64 = 0;
    let mut changed_pixels: usize = 0;
    for (&a, &b) in prev.iter().zip(curr.iter()) {
        let d = a.abs_diff(b);
        total_diff += d as u64;
        if d >= 18 {
            changed_pixels += 1;
        }
    }
    let mean_diff = total_diff as f64 / prev.len() as f64;
    mean_diff >= 1.8 || changed_pixels >= 12
}

/// Read an image from the Windows clipboard (`CF_DIB`).
#[cfg(windows)]
pub fn grab_clipboard_image() -> Result<RgbImage, String> {
    use windows::Win32::Foundation::HGLOBAL;
    use windows::Win32::Graphics::Gdi::BITMAPINFOHEADER;
    use windows::Win32::System::DataExchange::{
        CloseClipboard, GetClipboardData, IsClipboardFormatAvailable, OpenClipboard,
    };
    use windows::Win32::System::Memory::{GlobalLock, GlobalSize, GlobalUnlock};

    const CF_DIB: u32 = 8;

    unsafe {
        if IsClipboardFormatAvailable(CF_DIB).is_err() {
            return Err("Clipboard hiện không có ảnh.".to_string());
        }
        if OpenClipboard(None).is_err() {
            return Err("Không mở được clipboard.".to_string());
        }
        let result = (|| -> Result<RgbImage, String> {
            let handle = GetClipboardData(CF_DIB)
                .map_err(|_| "Không đọc được dữ liệu ảnh từ clipboard.".to_string())?;
            let hglobal = HGLOBAL(handle.0);
            let size = GlobalSize(hglobal);
            if size < std::mem::size_of::<BITMAPINFOHEADER>() {
                return Err("Dữ liệu ảnh clipboard không hợp lệ.".to_string());
            }
            let ptr = GlobalLock(hglobal);
            if ptr.is_null() {
                return Err("Không khóa được bộ nhớ ảnh clipboard.".to_string());
            }
            let raw = std::slice::from_raw_parts(ptr as *const u8, size).to_vec();
            let _ = GlobalUnlock(hglobal);

            // Prepend 14-byte BITMAPFILEHEADER so `image` crate decodes any DIB cleanly.
            let header_size = u32::from_le_bytes([raw[0], raw[1], raw[2], raw[3]]);
            let bit_count = u16::from_le_bytes([raw[14], raw[15]]);
            let compression = u32::from_le_bytes([raw[16], raw[17], raw[18], raw[19]]);
            let clr_used = u32::from_le_bytes([raw[32], raw[33], raw[34], raw[35]]);
            let palette_bytes = if bit_count <= 8 {
                (if clr_used == 0 { 1u32 << bit_count } else { clr_used }) * 4
            } else if compression == 3 && header_size == 40 {
                12 // BI_BITFIELDS masks
            } else {
                0
            };
            let pixel_offset = 14u32 + header_size + palette_bytes;
            let file_size = 14u32 + raw.len() as u32;
            let mut bmp = Vec::with_capacity(file_size as usize);
            bmp.extend_from_slice(b"BM");
            bmp.extend_from_slice(&file_size.to_le_bytes());
            bmp.extend_from_slice(&0u32.to_le_bytes());
            bmp.extend_from_slice(&pixel_offset.to_le_bytes());
            bmp.extend_from_slice(&raw);

            let dyn_img = image::load_from_memory_with_format(&bmp, image::ImageFormat::Bmp)
                .map_err(|e| format!("Không giải mã được ảnh clipboard: {e}"))?;
            Ok(dyn_img.into_rgb8())
        })();
        let _ = CloseClipboard();
        result
    }
}

#[cfg(not(windows))]
pub fn grab_clipboard_image() -> Result<RgbImage, String> {
    Err("Đọc ảnh clipboard chỉ hỗ trợ Windows.".to_string())
}

/// Encode an RgbImage as base64 PNG data URL for displaying in the Tauri UI.
pub fn encode_rgb_to_data_url(img: &RgbImage) -> Result<String, String> {
    use base64::Engine;
    use std::io::Cursor;

    let mut buf = Cursor::new(Vec::new());
    DynamicImage::ImageRgb8(img.clone())
        .write_to(&mut buf, image::ImageFormat::Png)
        .map_err(|e| format!("Không mã hoá được ảnh PNG: {e}"))?;
    let b64 = base64::engine::general_purpose::STANDARD.encode(buf.into_inner());
    Ok(format!("data:image/png;base64,{b64}"))
}
