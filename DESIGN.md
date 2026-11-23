# Design

Tuân thủ **Chuẩn giao diện chung cho các app *2k bản Rust** (`tauri-ui-standard.md`).

- Cửa sổ chính không viền (`decorations: false`), mặc định `1100×720`, tối thiểu `860×560`.
- Thanh tiêu đề tự vẽ cao `36px` (`data-tauri-drag-region`), icon + tên app bên trái, nút thu nhỏ / phóng to / đóng bên phải.
- Sidebar trái `220px` (thu gọn `56px` chỉ icon), cuối sidebar là Cài đặt.
- Vùng nội dung padding `24px`, tiêu đề trang `20px`, cỡ chữ `14px`, dòng `1.5`, khoảng cách bội số `4px`.
- Tokens cố định trong `src/styles/tokens.css` (Sáng / Tối / Theo hệ thống).
- Bộ thành phần chung đặt tại `src/components/ui/`: `TitleBar`, `Sidebar`, `Button`, `Card`, `Dialog`, `Toast`, `Toggle`. Icon duy nhất: `lucide-react`. Giao diện tiếng Việt.
