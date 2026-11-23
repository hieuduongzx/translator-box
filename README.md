# Translator2k

Ứng dụng dịch màn hình, overlay tại chỗ, dịch Live đa vùng, dịch ảnh clipboard và dịch Audio realtime trên Windows — viết lại hoàn toàn bằng **Rust + Tauri 2**.

## Tính năng chính

- **Vùng màn hình → Overlay tại chỗ**: OCR ngoại tuyến, tự xoá chữ gốc, dựng lại nền (inpaint) và vẽ bản dịch khớp màu/viền ngay trên chữ gốc (`WDA_EXCLUDEFROMCAPTURE`, click xuyên qua game/app).
- **Live đa vùng**: tối đa 12 vùng độc lập (Overlay hoặc Khung nổi riêng), kéo/đổi cỡ vùng trực tiếp trên màn hình, chế độ Hybrid / Tự động / Chuột-Phím (Game), lọc theo ứng dụng đang focus.
- **Ảnh & Văn bản**: Dịch ảnh clipboard (thay chữ trong ảnh hoặc trích xuất text), tự dịch khi Copy (`Ctrl+C`, tự bỏ qua mật khẩu), dịch & thay thế tại chỗ (`Alt+B`), dịch nhanh & lịch sử dịch.
- **Dịch Audio Realtime (Soniox `stt-rt-v6`)**: Thu âm thanh hệ thống (WASAPI loopback) hoặc Microphone bằng Win32 COM thuần Rust, hỗ trợ 1 chiều / 2 chiều, tách người nói, tự động `standby` tiết kiệm chi phí khi im lặng.
- **OCR ngoại tuyến**: Windows OCR (`Windows.Media.Ocr` WinRT trực tiếp từ RAM) và PP-OCRv5/v6 chạy bằng ONNX Runtime (`ort` CPU / DirectML).
- **Dịch vụ dịch**: Google (4 endpoints + circuit breaker 429), Bing keyless, Translator Box AI, OpenAI, Google Gemini, Provider OpenAI-compatible tùy chỉnh và Từ điển thuật ngữ (Glossary).
- **Siêu nhẹ khi chạy nền**: Đóng cửa sổ chính sẽ giải phóng hoàn toàn WebView2, chỉ giữ 1 tiến trình Rust thuần ở khay hệ thống (`~2.3 MB` Working Set / `~9.6 MB` Private RAM).

## Yêu cầu & Cách chạy

- Rust toolchain (`x86_64-pc-windows-msvc`)
- Bun (hoặc Node.js)

```powershell
# Cài dependencies frontend
bun install

# Chạy chế độ phát triển (Tauri 2 + Vite)
bun run tauri:dev

# Chạy kiểm thử Rust
cargo test --manifest-path src-tauri/Cargo.toml

# Đóng gói bản release & bộ cài đặt Windows (NSIS)
pwsh -NoProfile -File packaging/build.ps1
```

Hoặc chạy nhanh bằng `run.bat` (mở trực tiếp `src-tauri\target\release\Translator2k.exe` nếu đã build, ngược lại chạy `bun run tauri:dev`).
