//! Thành phần OCR ngoại tuyến (ONNX Runtime) tải khi cần.
//!
//! Bản cài không còn nhúng ONNX Runtime. Lần đầu dùng OCR ONNX, app tải một lần
//! `onnxruntime.dll` (bản DirectML của Microsoft) về `%LOCALAPPDATA%\Translator2k\runtime\…`,
//! kiểm SHA-256 ghim cứng + chữ ký số Microsoft rồi mới nạp. Cập nhật app không phải tải lại.

use std::fs;
use std::path::{Path, PathBuf};

use once_cell::sync::OnceCell;
use parking_lot::Mutex;
use sha2::{Digest, Sha256};

/// Tên thư mục theo phiên bản: đổi phiên bản runtime thì tải bản mới, bản cũ không bị ghi đè.
const RUNTIME_DIR_NAME: &str = "onnxruntime-1.24.4-directml";
const RUNTIME_FILE: &str = "onnxruntime.dll";
pub const RUNTIME_SIZE: u64 = 17_328_152;
const RUNTIME_SHA256: &str = "e7eedec6a6f26dc39dc948276a75ef6d2bee3fff944d874ceed0bbd3b97bff40";
pub const RUNTIME_URL: &str =
    "https://builds.amri2k.com/builds/translator2k/runtime/onnxruntime-1.24.4-directml/onnxruntime.dll";
const EXPECTED_SIGNER: &str = "Microsoft Corporation";

/// Môi trường ORT chỉ được tạo sau khi DLL đã được xác minh và nạp thành công.
static ORT_ENV: OnceCell<ort::environment::Environment> = OnceCell::new();
static INIT_LOCK: Mutex<()> = Mutex::new(());

pub fn runtime_dir() -> PathBuf {
    let base = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .or_else(dirs::data_local_dir)
        .unwrap_or_else(|| PathBuf::from("."));
    base.join("Translator2k").join("runtime").join(RUNTIME_DIR_NAME)
}

pub fn runtime_path() -> PathBuf {
    runtime_dir().join(RUNTIME_FILE)
}

/// Có file đúng cỡ (kiểm nhanh, không băm). Xác minh đầy đủ diễn ra trước khi nạp.
pub fn runtime_installed() -> bool {
    fs::metadata(runtime_path())
        .map(|m| m.is_file() && m.len() == RUNTIME_SIZE)
        .unwrap_or(false)
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let bytes = fs::read(path).map_err(|_| "Không đọc được thành phần OCR.".to_string())?;
    Ok(format!("{:x}", Sha256::digest(&bytes)))
}

/// Kiểm SHA-256 ghim cứng và chữ ký số Microsoft. Sai thì xoá file để lần sau tải lại.
pub fn verify_runtime_file(path: &Path) -> Result<(), String> {
    let bad = |path: &Path| {
        let _ = fs::remove_file(path);
        Err("Thành phần OCR tải về không hợp lệ, vui lòng tải lại.".to_string())
    };
    match sha256_file(path) {
        Ok(h) if h.eq_ignore_ascii_case(RUNTIME_SHA256) => {}
        Ok(_) => return bad(path),
        Err(e) => return Err(e),
    }
    match signer_name(path) {
        Some(name) if name == EXPECTED_SIGNER => Ok(()),
        _ => bad(path),
    }
}

/// Trả về môi trường ORT; nạp DLL (đã xác minh) ở lần gọi đầu tiên.
pub fn environment() -> Result<&'static ort::environment::Environment, String> {
    if let Some(env) = ORT_ENV.get() {
        return Ok(env);
    }
    let _guard = INIT_LOCK.lock();
    if let Some(env) = ORT_ENV.get() {
        return Ok(env);
    }
    let path = runtime_path();
    if !runtime_installed() {
        return Err(
            "Thành phần OCR ngoại tuyến chưa được tải. Vào mục OCR và bấm tải mô hình.".to_string(),
        );
    }
    verify_runtime_file(&path)?;
    let builder = ort::init_from(&path)
        .map_err(|_| "Không nạp được thành phần OCR, vui lòng tải lại trong mục OCR.".to_string())?;
    let env = builder
        .build()
        .map_err(|_| "Không khởi tạo được thành phần OCR.".to_string())?;
    let _ = ORT_ENV.set(env);
    ORT_ENV
        .get()
        .ok_or_else(|| "Không khởi tạo được thành phần OCR.".to_string())
}

#[cfg(windows)]
fn signer_name(path: &Path) -> Option<String> {
    use std::ffi::c_void;
    use std::os::windows::ffi::OsStrExt;
    use windows::core::PCWSTR;
    use windows::Win32::Foundation::HWND;
    use windows::Win32::Security::Cryptography::{CertGetNameStringW, CERT_NAME_SIMPLE_DISPLAY_TYPE};
    use windows::Win32::Security::WinTrust::{
        WTHelperGetProvSignerFromChain, WTHelperProvDataFromStateData, WinVerifyTrust,
        WINTRUST_ACTION_GENERIC_VERIFY_V2, WINTRUST_DATA, WINTRUST_DATA_0, WINTRUST_FILE_INFO,
        WTD_CHOICE_FILE, WTD_REVOKE_NONE, WTD_STATEACTION_CLOSE, WTD_STATEACTION_VERIFY,
        WTD_UI_NONE,
    };

    let wide: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    let mut file_info = WINTRUST_FILE_INFO {
        cbStruct: std::mem::size_of::<WINTRUST_FILE_INFO>() as u32,
        pcwszFilePath: PCWSTR(wide.as_ptr()),
        ..Default::default()
    };
    let mut data = WINTRUST_DATA {
        cbStruct: std::mem::size_of::<WINTRUST_DATA>() as u32,
        dwUIChoice: WTD_UI_NONE,
        fdwRevocationChecks: WTD_REVOKE_NONE,
        dwUnionChoice: WTD_CHOICE_FILE,
        Anonymous: WINTRUST_DATA_0 {
            pFile: &mut file_info,
        },
        dwStateAction: WTD_STATEACTION_VERIFY,
        ..Default::default()
    };
    let mut action = WINTRUST_ACTION_GENERIC_VERIFY_V2;

    unsafe {
        let status = WinVerifyTrust(
            HWND::default(),
            &mut action,
            &mut data as *mut WINTRUST_DATA as *mut c_void,
        );
        let mut name = None;
        if status == 0 {
            let prov = WTHelperProvDataFromStateData(data.hWVTStateData);
            if !prov.is_null() {
                let signer = WTHelperGetProvSignerFromChain(prov, 0, false, 0);
                if !signer.is_null() && (*signer).csCertChain > 0 && !(*signer).pasCertChain.is_null() {
                    let cert = (*(*signer).pasCertChain).pCert;
                    if !cert.is_null() {
                        let mut buf = [0u16; 256];
                        let n = CertGetNameStringW(
                            cert,
                            CERT_NAME_SIMPLE_DISPLAY_TYPE,
                            0,
                            None,
                            Some(&mut buf),
                        );
                        if n > 1 {
                            name = Some(String::from_utf16_lossy(&buf[..(n as usize - 1)]));
                        }
                    }
                }
            }
        }
        data.dwStateAction = WTD_STATEACTION_CLOSE;
        let _ = WinVerifyTrust(
            HWND::default(),
            &mut action,
            &mut data as *mut WINTRUST_DATA as *mut c_void,
        );
        name
    }
}

#[cfg(not(windows))]
fn signer_name(_path: &Path) -> Option<String> {
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runtime_path_is_versioned_under_localappdata() {
        let p = runtime_path();
        let s = p.to_string_lossy();
        assert!(s.contains("Translator2k"));
        assert!(s.contains(RUNTIME_DIR_NAME));
        assert!(s.ends_with(RUNTIME_FILE));
    }

    #[test]
    fn tampered_file_is_rejected_and_removed() {
        let dir = std::env::temp_dir().join("t2k-ort-test");
        let _ = fs::create_dir_all(&dir);
        let f = dir.join("onnxruntime.dll");
        fs::write(&f, b"not a dll").unwrap();
        assert!(verify_runtime_file(&f).is_err());
        assert!(!f.exists());
    }
}
