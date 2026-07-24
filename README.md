# Translator Box

**Phiên bản 1.0.1** · Ứng dụng dịch màn hình native Windows viết bằng Python + PySide6 (Qt).

> Tải bản cài đặt mới nhất tại [GitHub Releases](https://github.com/hieuduongzx/translator-box/releases). App tự kiểm tra và cập nhật một chạm khi có bản mới.

Hai giao diện:

- **HUD trong suốt** (cửa sổ chính): frameless, luôn trên cùng, nền bán trong suốt nhìn xuyên desktop. Thanh bar glass ở trên chứa các nút chức năng (chọn vùng, overlay, live, toàn màn hình, dịch văn bản chọn) + combo ngôn ngữ đích + nút Cài đặt/Ẩn; kéo thanh bar để di chuyển, kéo góc phải-dưới để co giãn. Bên dưới là **vùng trong suốt hiển thị bản dịch** (kết quả Ctrl+B, chọn vùng → dịch vào khung), kèm nút Gốc/Sao chép/Xoá.
- **Cửa sổ Cài đặt** (dark shell riêng): dịch vụ dịch (Google / Bing), ngôn ngữ đích, engine OCR + ngôn ngữ OCR (kèm trạng thái engine), và phím tắt toàn cục.

Chạy không hiện CMD, OCR offline đa engine.

## Tính năng

| Phím mặc định | Chức năng |
|---|---|
| `Ctrl+B` | Sao chép văn bản đang bôi đen, dịch và đổ vào khung HUD |
| `Ctrl+Alt+B` | **Dịch & thay thế tại chỗ**: bôi đen văn bản trong ô nhập bất kỳ (vd Discord), nhấn phím tắt → hệ thống dịch sang ngôn ngữ đích và **dán đè** thay thế trực tiếp (không cần rời khỏi ô nhập). Clipboard cũ được khôi phục |
| `Ctrl+Alt+A` | Kéo chọn vùng (overlay làm tối màn hình + khung chọn), OCR rồi đổ bản dịch vào khung HUD |
| `Ctrl+Alt+D` | Kéo chọn vùng, OCR layout và **hiển thị từng dòng dịch đúng vị trí trên màn hình** — nền thật được dựng lại (inpaint xoá chữ gốc, giữ gradient/hoạ tiết như Google Dịch ảnh); ảnh/icon xung quanh giữ nguyên. Không kéo cửa sổ app lên. Chuột trái: đóng ô đó · Chuột phải/Esc: xoá hết |
| `Ctrl+Alt+L` | **Live dịch một vùng**: chọn vùng rồi dịch overlay **liên tục** — tự chụp lại theo chu kỳ (`live_interval_ms`, mặc định 900ms) và chỉ OCR/dịch lại khi nội dung vùng thay đổi (badge **● LIVE**). Bấm lại phím tắt, chuột phải hoặc Esc để dừng |
| `Ctrl+Alt+Q` | Thoát ứng dụng |

- **HUD trong suốt**: bar chức năng phía trên + vùng trong suốt hiển thị bản
  dịch phía dưới; dịch vụ và ngôn ngữ đích chỉnh nhanh ngay trên bar. Kéo thanh
  bar để di chuyển, kéo góc phải-dưới để co giãn.
- **Kiểu chữ HUD**: chọn font, cỡ chữ, màu chữ, viền và màu nền có độ trong
  suốt; mặc định Yu Gothic 16pt, chữ đen, viền trắng 1px và nền trong suốt.
  Viền hỗ trợ giá trị subpixel từ 0.0–8.0px theo bước 0.1px.
  Dropdown chỉ hiện một danh mục font phổ biến đã cài và dùng font fallback của
  Windows cho Unicode Việt/Nhật/Trung/Hàn/Ả Rập/emoji.
- **Cửa sổ Cài đặt** (nút bánh răng trên bar hoặc menu khay): điều hướng tab
  dọc bên trái cho Dịch, OCR, Khung dịch và Phím tắt.
- **Chạy nền ở khay hệ thống**: bấm **Ẩn** (hoặc thu nhỏ) để ẩn HUD nhưng giữ phím tắt. Nhấp icon **T** để mở lại; chuột phải → **Thoát**.
- **OCR ngoại tuyến**: tích hợp sẵn **PP-OCRv5 mobile** cho Trung/Nhật/Anh. Có thể tải thêm PP-OCRv6 tiny/small/medium, PP-OCRv5 server và các model Hàn/Latinh/Đông Slav ngay trong Cài đặt.
- **Tăng tốc OCR**: mặc định tắt và luôn dùng CPU ONNX Runtime; chỉ dùng GPU
  DirectML, NVIDIA CUDA hoặc Intel OpenVINO khi người dùng chủ động bật.
- **Ghim HUD**: mặc định ghim trên cùng. Khi bỏ ghim, HUD tự ẩn lúc chuyển sang
  ứng dụng khác; `Ctrl+B` sẽ gọi HUD hiện lại để trả kết quả dịch văn bản bôi đen.
- **Windows OCR**: lựa chọn nhẹ dành cho Windows 10/11, sử dụng language pack của hệ điều hành.
- **Dịch vụ dịch**: Google, Bing/Microsoft, và các provider AI tích hợp
  **Translator Box** (`http://103.38.236.38:20128/v1`), **OpenAI**
  (`https://api.openai.com/v1`), **Google Gemini**
  (`https://generativelanguage.googleapis.com/v1beta/openai`) — endpoint cố định,
  chỉ cần nhập API key và chọn model. Ngoài ra thêm được **provider tùy chỉnh**
  (endpoint + API key + nhiều model bất kỳ) qua **Cài đặt → Dịch → ＋ Thêm provider
  tùy chỉnh**. Trên thanh bar, **mỗi model của mỗi provider hiện thành một mục
  riêng**. API key không đóng gói sẵn. Endpoint trả về dạng event-stream
  (`data: [DONE]`) vẫn bóc tách đúng. Mọi lỗi dịch/AI được in thẳng vào khung dịch.
- **Cập nhật tự động**: khi mở app sẽ kiểm tra [GitHub Releases](https://github.com/hieuduongzx/translator-box/releases);
  có bản mới thì hiện thông báo, bấm **Cập nhật ngay** để tải + cài + khởi động
  lại một chạm. Kiểm tra thủ công và bật/tắt trong **Cài đặt → Giới thiệu**.
- Config: `%USERPROFILE%\.screen-translator-2k\python-config.json`.

## Cài đặt

Yêu cầu Python 3.10+ (máy đã cài Python310). Cài thư viện:

```text
python -m pip install -r python-app/requirements.txt
```

(PySide6 — giao diện Qt, Pillow — chụp màn hình, keyboard — phím tắt toàn cục, pyperclip — clipboard, winsdk — Windows OCR, RapidOCR + ONNX Runtime — OCR AI ngoại tuyến. PP-OCRv5 mobile được đóng gói trong RapidOCR; các model khác được tải theo nhu cầu vào `%USERPROFILE%\.screen-translator-2k\models\rapidocr`.)

### Mô hình OCR ngoại tuyến

| Mô hình | Detection Hmean | Recognition | Ngôn ngữ | Dung lượng |
|---|---:|---:|---|---:|
| PP-OCRv6 tiny | 80.6% | 73.5% | 49 ngôn ngữ, không gồm Nhật | 5.45 MB |
| PP-OCRv6 small | 84.1% | 81.3% | 50 ngôn ngữ | 25.2 MB |
| PP-OCRv6 medium | 86.2% | 83.2% | 50 ngôn ngữ | 99.7 MB |
| PP-OCRv5 mobile | 79.0% | 81.29% | Trung giản/phồn thể, Anh, Nhật | 17.7 MB |
| PP-OCRv5 server | 83.8% | 86.38% | Trung giản/phồn thể, Anh, Nhật | 148 MB |
| Đông Slav · PP-OCRv5 mobile | 79.0% | 81.6% | Đông Slav | 11.2 MB |
| Hàn · PP-OCRv5 mobile | 79.0% | 88.0% | Hàn | 12.2 MB |
| Latinh · PP-OCRv5 mobile | 79.0% | 84.7% | Các ngôn ngữ Latinh | 11.3 MB |

PP-OCRv5 mobile có sẵn ngay sau khi cài dependencies. Chọn model khác trong **Cài đặt → OCR → Mô hình**, sau đó bấm **Tải mô hình**. Các model chỉ được tải một lần và dùng hoàn toàn ngoại tuyến sau đó.

Backend tăng tốc tuỳ chọn:

```text
# GPU Windows phổ thông
python -m pip install onnxruntime-directml

# GPU NVIDIA (yêu cầu CUDA/cuDNN tương thích)
python -m pip install onnxruntime-gpu

# Intel CPU/GPU/NPU
python -m pip install openvino
```

Chỉ nên cài một biến thể ONNX Runtime trong cùng môi trường. Trạng thái backend và lệnh khắc phục được hiển thị trực tiếp trong Cài đặt.

## Chạy

Double-click `run.vbs` (chạy bằng `pythonw`, không hiện CMD).

Hoặc chạy trực tiếp:

```text
pythonw python-app\main.py
```

Ghi chú: phím tắt toàn cục dùng thư viện `keyboard`. Nếu app khác đang chạy với quyền admin mà phím tắt không bắt được khi app đó đang focus, hãy chạy Screen Translator với quyền admin.

## Đóng gói (build exe + installer)

Yêu cầu: `pip install pyinstaller` và [Inno Setup 6](https://jrsoftware.org/isdl.php)
(`winget install JRSoftware.InnoSetup`). Sau đó:

```powershell
pwsh -File packaging/build.ps1
```

Script đọc phiên bản từ `python-app/version.py`, đóng gói **onedir** bằng
PyInstaller (`packaging/ScreenTranslator2K.spec`), rồi biên dịch installer bằng
Inno Setup (`packaging/installer.iss`). Kết quả:

- `dist/ScreenTranslator2K/` — thư mục app (exe + `_internal`).
- `dist/ScreenTranslator2K-<version>-setup.exe` — file cài đặt.

Chỉ build exe (bỏ installer): `pwsh -File packaging/build.ps1 -SkipInstaller`.
Đổi icon: sửa `tools/make_icon.py` rồi chạy `python tools/make_icon.py`.

## Phát hành & CI

Đẩy tag `vX.Y.Z` (khớp `APP_VERSION`) lên GitHub → workflow
`.github/workflows/release.yml` tự cài dependencies + Inno Setup trên
`windows-latest`, build installer và tạo Release đính kèm file `.exe`. App đang
cài sẽ thấy bản mới qua GitHub Releases API và cập nhật một chạm.

```powershell
# ví dụ phát hành 1.0.1
git tag v1.0.1
git push origin v1.0.1
```

## Cấu trúc

```text
python-app/
  main.py                    entry point tối thiểu
  application.py             composition root, Qt runtime và single-instance
  hud_window.py              cửa sổ HUD, tray và vòng đời UI
  settings_window.py         cửa sổ Cài đặt (Dịch/OCR/Khung/Phím tắt/Giới thiệu)
  translation_workflows.py   controller capture/OCR/dịch/live
  update_controller.py       điều phối kiểm tra & cài đặt cập nhật (UI)
  updater.py                 gọi GitHub Releases API, so phiên bản, tải asset
  version.py                 nguồn phiên bản + owner/repo duy nhất
  widgets.py                 widget Qt dùng lại
  ui_utils.py                icon thương hiệu, hotkey formatting, helper Windows/Qt
  constants.py               metadata ngôn ngữ/action + entry LLM cho bar
  theme.py                   Qt stylesheet
  config.py                  config JSON có validation và atomic save
  hotkeys.py                 quản lý phím tắt toàn cục (keyboard)
  services.py                OCR + chụp màn hình + dịch (Google/Bing/LLM)
  overlay.py                 overlay chọn vùng và hiển thị bản dịch
  assets/icon.ico|png        icon thương hiệu (dùng cho app + installer)
  tests/                     regression/unit tests
  requirements.txt
packaging/
  ScreenTranslator2K.spec    cấu hình PyInstaller (onedir, windowed)
  installer.iss              script Inno Setup
  build.ps1                  orchestrator: version → PyInstaller → Inno Setup
tools/
  make_icon.py               sinh assets/icon.ico|png từ nhận diện thương hiệu
.github/workflows/release.yml  build + publish installer khi đẩy tag v*
```
