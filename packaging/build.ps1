<#
.SYNOPSIS
    Build Screen Translator 2K: PyInstaller (onedir) + Inno Setup installer.
.DESCRIPTION
    Đọc phiên bản từ python-app/version.py, sinh version-resource cho exe,
    đóng gói onedir rồi biên dịch installer. Chạy từ bất kỳ đâu:
        pwsh -File packaging/build.ps1
    Tham số:
        -SkipInstaller   chỉ build exe, bỏ qua Inno Setup.
#>
[CmdletBinding()]
param([switch]$SkipInstaller)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# ---- Phiên bản (nguồn duy nhất: version.py) ----
$versionPy = Get-Content "$root\python-app\version.py" -Raw
if ($versionPy -notmatch 'APP_VERSION\s*=\s*"([^"]+)"') {
    throw "Không đọc được APP_VERSION trong version.py"
}
$version = $Matches[1]
$parts = ($version -split '[.\-+]' | Where-Object { $_ -match '^\d+$' })
while ($parts.Count -lt 4) { $parts += "0" }
$fv = ($parts[0..3] -join ",")
Write-Host "==> Building Screen Translator 2K $version" -ForegroundColor Cyan

# ---- Icon (đảm bảo tồn tại) ----
if (-not (Test-Path "$root\python-app\assets\icon.ico")) {
    Write-Host "==> Sinh icon..." -ForegroundColor Cyan
    python "$root\tools\make_icon.py"
}

# ---- Version resource cho exe ----
$verInfo = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($fv), prodvers=($fv),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'hieuduongzx'),
      StringStruct('FileDescription', 'Screen Translator 2K'),
      StringStruct('FileVersion', '$version'),
      StringStruct('InternalName', 'ScreenTranslator2K'),
      StringStruct('LegalCopyright', 'Copyright (c) hieuduongzx'),
      StringStruct('OriginalFilename', 'ScreenTranslator2K.exe'),
      StringStruct('ProductName', 'Screen Translator 2K'),
      StringStruct('ProductVersion', '$version')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@
Set-Content -Path "$root\packaging\file_version_info.txt" -Value $verInfo -Encoding UTF8

# ---- Dọn build cũ ----
Remove-Item "$root\build","$root\dist\ScreenTranslator2K" -Recurse -Force -ErrorAction SilentlyContinue

# ---- PyInstaller ----
Write-Host "==> PyInstaller..." -ForegroundColor Cyan
python -m PyInstaller "$root\packaging\ScreenTranslator2K.spec" --noconfirm --distpath "$root\dist" --workpath "$root\build"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller thất bại (exit $LASTEXITCODE)" }
$exe = "$root\dist\ScreenTranslator2K\ScreenTranslator2K.exe"
if (-not (Test-Path $exe)) { throw "Không thấy $exe sau khi build" }
Write-Host "==> Đóng gói onedir xong: $exe" -ForegroundColor Green

if ($SkipInstaller) { Write-Host "Bỏ qua installer (theo yêu cầu)."; return }

# ---- Inno Setup ----
$iscc = $null
foreach ($p in @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
    if (Test-Path $p) { $iscc = $p; break }
}
if (-not $iscc) { $iscc = (Get-Command iscc -ErrorAction SilentlyContinue)?.Source }
if (-not $iscc) {
    Write-Warning "Chưa cài Inno Setup (ISCC.exe). Cài: winget install JRSoftware.InnoSetup"
    Write-Warning "Đã có bản onedir tại dist\ScreenTranslator2K — chạy lại script sau khi cài Inno."
    return
}
Write-Host "==> Inno Setup ($iscc)..." -ForegroundColor Cyan
& $iscc "/DAppVersion=$version" "$root\packaging\installer.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup thất bại (exit $LASTEXITCODE)" }
$setup = "$root\dist\ScreenTranslator2K-$version-setup.exe"
Write-Host "==> Installer: $setup" -ForegroundColor Green
