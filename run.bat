@echo off
setlocal
cd /d "%~dp0"

if exist "src-tauri\target\release\Translator2k.exe" (
    start "" "src-tauri\target\release\Translator2k.exe"
    exit /b 0
)

where bun >nul 2>nul
if %errorlevel%==0 (
    bun run tauri:dev
    exit /b %errorlevel%
)

npm run tauri:dev
