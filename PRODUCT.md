# Product

## Platform

Windows Desktop (x64)

## Stack

**Tauri 2 + Rust core + React + TypeScript + Vite + Win32 Native Overlays**.
- Lõi hệ thống viết hoàn toàn bằng Rust: Win32 GDI `BitBlt`, Windows OCR (WinRT), PP-OCRv5/v6 ONNX (`ort` CPU/DirectML), background inpainting thuần Rust, Google/Bing/LLM translator, Soniox WebSocket STT + WASAPI loopback/mic, phím tắt toàn cục `RegisterHotKey`, clipboard monitor, single-instance, auto-updater.
- Giao diện tuân thủ chuẩn chung dòng ứng dụng *2k (`tauri-ui-standard.md`): Tauri 2, không viền (`decorations: false`), thanh tiêu đề tự vẽ 36px, sidebar 220px (thu gọn 56px), bộ tokens Sáng/Tối/Theo hệ thống, icon `lucide-react`, CSS thuần.
- Chạy nền bằng Rust thuần: đóng cửa sổ chính sẽ giải phóng toàn bộ WebView2, mở lại tức thì từ khay hệ thống.
- Lớp phủ trực tiếp (chọn vùng, chỉnh sửa vùng Live, vẽ bản dịch đè chữ gốc) dùng Win32 Layered native (`WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WDA_EXCLUDEFROMCAPTURE`).
