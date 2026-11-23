$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "1/2 Building Translator2k React + TypeScript frontend..."
bun install --frozen-lockfile
bun run build

Write-Host "2/2 Building Translator2k Rust + Tauri 2 release & NSIS installer..."
bun run tauri build

$nsisDir = "src-tauri\target\release\bundle\nsis"
if (Test-Path $nsisDir) {
  New-Item -ItemType Directory -Force -Path dist | Out-Null
  Copy-Item "$nsisDir\*.exe" dist\ -Force
  Write-Host "Done! Translator2k installer copied to dist\."
}
