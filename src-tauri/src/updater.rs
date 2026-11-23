use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use std::io::Write;
use std::path::PathBuf;

use crate::version::{APP_ID, APP_VERSION, GITHUB_REPO};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReleaseInfo {
    pub version: String,
    pub tag: String,
    pub name: String,
    pub notes: String,
    pub html_url: String,
    pub asset_url: Option<String>,
    pub asset_name: Option<String>,
    pub asset_size: u64,
}

pub fn parse_version(text: &str) -> Vec<u32> {
    let cleaned = text.trim().trim_start_matches(['v', 'V']);
    let mut nums = Vec::new();
    for part in cleaned.split(['.', '-', '+']) {
        let digits: String = part.chars().take_while(|c| c.is_ascii_digit()).collect();
        if digits.is_empty() {
            break;
        }
        if let Ok(n) = digits.parse::<u32>() {
            nums.push(n);
        } else {
            break;
        }
    }
    if nums.is_empty() {
        vec![0]
    } else {
        nums
    }
}

pub fn parse_version_str(tag: &str) -> String {
    parse_version(tag)
        .into_iter()
        .map(|n| n.to_string())
        .collect::<Vec<_>>()
        .join(".")
}

pub fn is_newer(remote: &str, local: &str) -> bool {
    let r = parse_version(remote);
    let l = parse_version(local);
    let len = r.len().max(l.len());
    for i in 0..len {
        let rv = *r.get(i).unwrap_or(&0);
        let lv = *l.get(i).unwrap_or(&0);
        if rv != lv {
            return rv > lv;
        }
    }
    false
}

#[derive(Deserialize)]
struct GhAsset {
    name: Option<String>,
    browser_download_url: Option<String>,
    size: Option<u64>,
}

#[derive(Deserialize)]
struct GhRelease {
    tag_name: Option<String>,
    name: Option<String>,
    body: Option<String>,
    html_url: Option<String>,
    draft: Option<bool>,
    prerelease: Option<bool>,
    assets: Option<Vec<GhAsset>>,
}

pub async fn check_latest() -> Result<Option<ReleaseInfo>, String> {
    let url = format!("https://api.github.com/repos/{GITHUB_REPO}/releases/latest");
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(8))
        .build()
        .map_err(|e| format!("Lỗi HTTP client: {e}"))?;
    let resp = client
        .get(&url)
        .header("User-Agent", format!("{APP_ID}/{APP_VERSION}"))
        .header("Accept", "application/vnd.github+json")
        .send()
        .await
        .map_err(|e| format!("Không kiểm tra được cập nhật: {e}"))?;

    if !resp.status().is_success() {
        return Ok(None);
    }
    let data: GhRelease = resp
        .json()
        .await
        .map_err(|e| format!("Dữ liệu phát hành không hợp lệ: {e}"))?;
    if data.draft.unwrap_or(false) || data.prerelease.unwrap_or(false) {
        return Ok(None);
    }
    let tag = data.tag_name.unwrap_or_default();
    if tag.is_empty() {
        return Ok(None);
    }

    let mut chosen: Option<(String, String, u64)> = None;
    if let Some(assets) = data.assets {
        let mut valid: Vec<GhAsset> = assets
            .into_iter()
            .filter(|a| a.browser_download_url.is_some())
            .collect();
        valid.sort_by_key(|a| {
            let n = a.name.as_deref().unwrap_or("").to_lowercase();
            if n.ends_with(".exe") {
                0
            } else if n.ends_with(".zip") {
                1
            } else {
                2
            }
        });
        for asset in valid {
            let name = asset.name.clone().unwrap_or_default();
            let lower = name.to_lowercase();
            if lower.ends_with(".exe") || lower.ends_with(".zip") {
                chosen = Some((
                    asset.browser_download_url.unwrap_or_default(),
                    name,
                    asset.size.unwrap_or(0),
                ));
                break;
            }
        }
    }

    let (asset_url, asset_name, asset_size) = match chosen {
        Some((u, n, s)) => (Some(u), Some(n), s),
        None => (None, None, 0),
    };

    Ok(Some(ReleaseInfo {
        version: parse_version_str(&tag),
        tag: tag.clone(),
        name: data.name.unwrap_or(tag),
        notes: data.body.unwrap_or_default().trim().to_string(),
        html_url: data.html_url.unwrap_or_default(),
        asset_url,
        asset_name,
        asset_size,
    }))
}

pub async fn find_update() -> Result<Option<ReleaseInfo>, String> {
    let release = check_latest().await?;
    Ok(release.filter(|r| is_newer(&r.version, APP_VERSION)))
}

pub async fn download_asset<F>(release: &ReleaseInfo, mut on_progress: F) -> Result<PathBuf, String>
where
    F: FnMut(u64, u64),
{
    let url = release
        .asset_url
        .as_deref()
        .ok_or_else(|| "Bản phát hành không có file cài đặt để tải.".to_string())?;
    let name = release
        .asset_name
        .clone()
        .unwrap_or_else(|| format!("{APP_ID}-{}-setup.exe", release.version));
    let target_dir = std::env::temp_dir().join("screen-translator-2k-update");
    std::fs::create_dir_all(&target_dir)
        .map_err(|e| format!("Không tạo được thư mục tạm: {e}"))?;
    let target = target_dir.join(name);

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(120))
        .build()
        .map_err(|e| format!("Lỗi HTTP client: {e}"))?;
    let resp = client
        .get(url)
        .header("User-Agent", format!("{APP_ID}/{APP_VERSION}"))
        .send()
        .await
        .map_err(|e| format!("Không tải được file cập nhật: {e}"))?;
    if !resp.status().is_success() {
        return Err(format!("Tải cập nhật thất bại (HTTP {}).", resp.status()));
    }
    let total = resp.content_length().unwrap_or(release.asset_size);
    let mut file =
        std::fs::File::create(&target).map_err(|e| format!("Không tạo được file cài đặt: {e}"))?;
    let mut stream = resp.bytes_stream();
    let mut downloaded = 0u64;
    while let Some(chunk) = stream.next().await {
        let bytes = chunk.map_err(|e| format!("Lỗi khi tải file cập nhật: {e}"))?;
        file.write_all(&bytes)
            .map_err(|e| format!("Lỗi ghi file cập nhật: {e}"))?;
        downloaded += bytes.len() as u64;
        on_progress(downloaded, total);
    }
    Ok(target)
}

pub fn run_installer(installer_path: &PathBuf) -> Result<(), String> {
    if !installer_path.is_file() {
        return Err("Không tìm thấy file cài đặt đã tải.".to_string());
    }
    let mut cmd = std::process::Command::new(installer_path);
    cmd.args(["/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS"]);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
        const DETACHED_PROCESS: u32 = 0x0000_0008;
        cmd.creation_flags(CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS);
    }
    cmd.spawn()
        .map_err(|e| format!("Không khởi chạy được trình cài đặt: {e}"))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_comparison() {
        assert!(is_newer("v2.1.0", "2.0.0"));
        assert!(is_newer("2.0.1", "2.0.0"));
        assert!(!is_newer("2.0.0", "2.0.0"));
        assert!(!is_newer("1.9.9", "2.0.0"));
    }
}
