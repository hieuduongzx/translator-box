"""Design token + Qt stylesheet dùng chung của ứng dụng.

Một nguồn sự thật duy nhất cho màu/bán kính/kiểu chữ: `TOKENS` được thay vào
`STYLE` (placeholder dạng `@TÊN@`) bởi `build_style()`. Code Python cần màu thì
đọc `TOKENS` qua `color()` thay vì rải hex khắp nơi.

Ngôn ngữ thị giác: nền gần đen hơi lạnh, bề mặt nâng dần (bg → surface → raised
→ hover), viền 1px thay cho đổ bóng, accent chàm dùng RẤT tiết chế (focus, mục
đang chọn, live) và nút xác nhận dùng mực trắng. Màu ngữ nghĩa: xanh lá = xong,
hổ phách = đang chạy, hồng = lỗi/live.
"""

from __future__ import annotations

import re

TOKENS: dict[str, str] = {
    # ---- lớp nền ----
    "BG": "#0b0c0f",  # nền cửa sổ
    "SURFACE": "#12141a",  # thẻ (card)
    "SUNKEN": "#0d0f14",  # ô nhập, vùng lõm
    "RAISED": "#171a21",  # nút, chip
    "HOVER": "#1e222b",
    "PRESSED": "#0f1116",
    # ---- viền ----
    "LINE_SOFT": "#191d25",  # kẻ giữa các hàng trong thẻ
    "LINE": "#232833",
    "LINE_STRONG": "#2e3440",
    "LINE_HI": "#3b4351",
    # ---- chữ ----
    "TEXT": "#e9ebf0",
    "TEXT_DIM": "#a8afbd",
    "TEXT_MUTED": "#737b8a",
    "TEXT_OFF": "#565d6b",  # disabled
    # ---- accent & ngữ nghĩa ----
    "ACCENT": "#6c77f5",
    "ACCENT_HI": "#aeb6ff",
    "ACCENT_SOFT": "rgba(108, 119, 245, 0.20)",
    "ACCENT_SOFT_HI": "rgba(108, 119, 245, 0.30)",
    "ACCENT_LINE": "rgba(140, 150, 255, 0.55)",
    "OK": "#34d399",
    "OK_SOFT": "rgba(52, 211, 153, 0.14)",
    "BUSY": "#fbbf24",
    "BUSY_SOFT": "rgba(251, 191, 36, 0.14)",
    "DANGER": "#fb7185",
    "DANGER_SOFT": "rgba(251, 113, 133, 0.14)",
    "LIVE": "#f43f5e",
    # ---- lớp glass của HUD (nằm trên desktop nên dùng rgba) ----
    "GLASS": "rgba(12, 14, 19, 0.94)",
    "GLASS_LINE": "rgba(255, 255, 255, 0.09)",
    "GLASS_HOVER": "rgba(255, 255, 255, 0.08)",
    "GLASS_PRESSED": "rgba(255, 255, 255, 0.04)",
    "GLASS_FILL": "rgba(255, 255, 255, 0.055)",
    "GLASS_FILL_LINE": "rgba(255, 255, 255, 0.10)",
    "GLASS_SEP": "rgba(255, 255, 255, 0.11)",
    # ---- kiểu chữ ----
    "FONT": (
        "'Segoe UI Variable Text', 'Segoe UI', 'Segoe UI Emoji', system-ui, sans-serif"
    ),
    "FONT_DISPLAY": "'Segoe UI Variable Display', 'Segoe UI', system-ui, sans-serif",
    "FONT_MONO": "'Cascadia Mono', 'JetBrains Mono', 'Consolas', monospace",
}


STYLE = """
/* ======================= Nền tảng ======================= */
* {
    font-family: @FONT@;
    font-size: 13px;
}
QWidget { color: @TEXT@; background: transparent; }
QLabel { background: transparent; border: none; }
QLabel:disabled, QCheckBox:disabled { color: @TEXT_OFF@; }
QToolTip {
    background: #16181f; color: @TEXT@; border: 1px solid @LINE_STRONG@;
    border-radius: 8px; padding: 7px 10px; font-size: 12px;
}
QMenu {
    background: @SURFACE@; color: @TEXT_DIM@; border: 1px solid @LINE_STRONG@;
    padding: 5px; border-radius: 12px;
}
QMenu::item { padding: 8px 26px 8px 12px; border-radius: 8px; }
QMenu::item:selected { background: @HOVER@; color: #ffffff; }
QMenu::item:disabled { color: @TEXT_OFF@; }
QMenu::separator { height: 1px; background: @LINE@; margin: 5px 8px; }

/* Hộp thoại hệ thống (thông báo cập nhật, xác nhận xoá…) theo cùng dark shell. */
QDialog, QMessageBox { background: @BG@; }
QMessageBox QLabel { color: @TEXT@; }

/* ======================= HUD trong suốt ======================= */
/* Thanh bar: lớp glass tối gần đục để bấm chính xác trên mọi nền desktop. */
QFrame#hudBar {
    background: @GLASS@;
    border: 1px solid @GLASS_LINE@;
    border-radius: 14px;
}
/* Vùng bản dịch: trong suốt hoàn toàn — chỉ thấy chữ nổi trên desktop. */
QFrame#hudDisplay { background: transparent; border: none; }
QPushButton#barBtn {
    background: transparent; border: 1px solid transparent; border-radius: 9px;
}
QPushButton#barBtn:hover {
    background: @GLASS_HOVER@; border-color: @GLASS_FILL_LINE@;
}
QPushButton#barBtn:pressed { background: @GLASS_PRESSED@; }
QPushButton#barBtn:checked {
    background: @ACCENT_SOFT@; border-color: @ACCENT_LINE@;
}
QPushButton#barBtn:checked:hover { background: @ACCENT_SOFT_HI@; }
QPushButton#barBtn:focus { border-color: @ACCENT@; }
QPushButton#barBtn:disabled { background: transparent; border-color: transparent; }
QFrame#barSep { background: @GLASS_SEP@; max-width: 1px; border: none; }
QComboBox#barCombo {
    background: @GLASS_FILL@; border: 1px solid @GLASS_FILL_LINE@;
    border-radius: 9px; padding: 4px 8px; min-height: 20px; color: @TEXT@;
    font-size: 12px;
}
QComboBox#barCombo:hover { background: @GLASS_HOVER@; border-color: @ACCENT_LINE@; }
QComboBox#barCombo:focus, QComboBox#barCombo:on { border-color: @ACCENT@; }
QComboBox#barCombo:disabled { color: @TEXT_OFF@; border-color: @GLASS_PRESSED@; }
QComboBox#barCombo::drop-down { border: none; width: 18px; }
QComboBox#barCombo::down-arrow { image: url("@CHEVRON@"); width: 11px; height: 11px; }
QComboBox QAbstractItemView {
    background: @SURFACE@; border: 1px solid @LINE_STRONG@; border-radius: 10px;
    selection-background-color: @HOVER@; selection-color: #ffffff;
    color: @TEXT_DIM@; outline: none; padding: 4px;
}
QComboBox QAbstractItemView::item { min-height: 26px; border-radius: 7px; }
QSizeGrip { background: transparent; width: 14px; height: 14px; }

/* ======================= Cửa sổ Cài đặt ======================= */
QWidget#settingsRoot { background: @BG@; }
QFrame#divider { background: @LINE@; max-height: 1px; border: none; }
QFrame#vDivider { background: @LINE@; max-width: 1px; border: none; }
QFrame#settingsSidebar {
    background: @SUNKEN@; border: none; border-right: 1px solid @LINE@;
}
QLabel#sidebarLabel {
    color: @TEXT_MUTED@; font-size: 10px; font-weight: 600;
}
QLabel#sidebarHint { color: @TEXT_MUTED@; font-size: 11px; }
QLabel#brandWordmark {
    font-family: @FONT_DISPLAY@; color: #ffffff; font-size: 15px; font-weight: 600;
}
QLabel#brandVersion {
    color: @TEXT_DIM@; font-size: 11px; font-family: @FONT_MONO@;
    background: @RAISED@; border: 1px solid @LINE@; border-radius: 6px;
    padding: 2px 7px;
}
QLabel#muted, QLabel#footerHint { color: @TEXT_MUTED@; font-size: 12px; }
QLabel#pageTitle, QLabel#tabTitle {
    font-family: @FONT_DISPLAY@; color: #ffffff; font-size: 22px; font-weight: 600;
}
QLabel#pageSubtitle, QLabel#tabDescription { color: @TEXT_DIM@; font-size: 12px; }
QLabel#fieldLabel { color: @TEXT_DIM@; font-size: 12px; font-weight: 600; }

QListWidget#settingsNav {
    background: transparent; border: none; padding: 0; outline: none;
}
QListWidget#settingsNav::item {
    color: @TEXT_DIM@; border: 1px solid transparent; border-radius: 10px;
    padding: 10px 11px; margin: 2px 0;
}
QListWidget#settingsNav::item:hover { color: @TEXT@; background: @SURFACE@; }
QListWidget#settingsNav::item:selected,
QListWidget#settingsNav::item:selected:active,
QListWidget#settingsNav::item:selected:!active {
    color: #ffffff; background: @ACCENT_SOFT@; border-color: @ACCENT_LINE@;
}
QStackedWidget#settingsPages { background: transparent; }

/* ---- thẻ & hàng cài đặt ---- */
QFrame#card, QFrame#surface, QFrame#engineInfo {
    background: @SURFACE@; border: 1px solid @LINE@; border-radius: 12px;
}
QFrame#cardSunken, QFrame#modelMeta {
    background: @SUNKEN@; border: 1px solid @LINE@; border-radius: 12px;
}
/* Khung xem trước: nền bàn cờ do widget tự vẽ nên chỉ giữ lại viền. */
QFrame#previewSurface {
    background: transparent; border: 1px solid @LINE@; border-radius: 12px;
}
QLabel#cardTitle { color: @TEXT@; font-size: 13px; font-weight: 600; }
QLabel#cardHint { color: @TEXT_MUTED@; font-size: 12px; }
QLabel#rowLabel, QLabel#hotkeyLabel { color: @TEXT@; font-size: 13px; }
QLabel#rowHint, QLabel#engineHint { color: @TEXT_MUTED@; font-size: 12px; }
QLabel#aiProviderStatus {
    font-size: 10px; font-weight: 600; border-radius: 7px; padding: 4px 8px;
}
QLabel#aiProviderStatus[state="active"] {
    color: @OK@; background: @OK_SOFT@;
}
QLabel#aiProviderStatus[state="inactive"] {
    color: @TEXT_MUTED@; background: @RAISED@;
}
QFrame#rowDivider { background: @LINE_SOFT@; max-height: 1px; border: none; }

/* ---- ô nhập ---- */
QLineEdit {
    background: @SUNKEN@; border: 1px solid @LINE@; border-radius: 9px;
    padding: 8px 11px; color: @TEXT@;
    selection-background-color: @ACCENT@; selection-color: #ffffff;
}
QLineEdit:hover { border-color: @LINE_STRONG@; }
QLineEdit:focus { border-color: @ACCENT@; }
QLineEdit:read-only { color: @TEXT_DIM@; background: @PRESSED@; }
QLineEdit:disabled { color: @TEXT_OFF@; background: @PRESSED@; }
QLineEdit#hotkey {
    font-family: @FONT_MONO@; font-size: 12px; padding: 7px 10px; color: @TEXT@;
    background: @RAISED@; border: 1px solid @LINE_STRONG@;
}
QLineEdit#hotkey:hover { border-color: @LINE_HI@; }
QLineEdit#hotkey[recording="true"] {
    border-color: @ACCENT@; color: @ACCENT_HI@; background: @PRESSED@;
}
QLineEdit#hotkey[conflict="true"] { border-color: @DANGER@; color: @DANGER@; }

QComboBox {
    background: @SUNKEN@; border: 1px solid @LINE@; border-radius: 9px;
    padding: 7px 11px; min-height: 20px; color: @TEXT@;
}
QComboBox:hover { border-color: @LINE_STRONG@; }
QComboBox:focus, QComboBox:on { border-color: @ACCENT@; }
QComboBox:disabled { color: @TEXT_OFF@; background: @PRESSED@; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: url("@CHEVRON@"); width: 12px; height: 12px; }
QComboBox::down-arrow:disabled { image: url("@CHEVRON_OFF@"); }

QSpinBox, QDoubleSpinBox {
    background: @SUNKEN@; border: 1px solid @LINE@; border-radius: 9px;
    padding: 7px 30px 7px 11px; min-height: 20px; color: @TEXT@;
    selection-background-color: @ACCENT@; selection-color: #ffffff;
}
QSpinBox:hover, QDoubleSpinBox:hover { border-color: @LINE_STRONG@; }
QSpinBox:focus, QDoubleSpinBox:focus { border-color: @ACCENT@; }
QSpinBox:disabled, QDoubleSpinBox:disabled { color: @TEXT_OFF@; background: @PRESSED@; }
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: transparent; border: none; width: 22px; border-radius: 6px;
    margin: 2px 3px 2px 0;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background: @HOVER@;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url("@CHEVRON_UP@"); width: 10px; height: 10px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url("@CHEVRON@"); width: 10px; height: 10px;
}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled {
    image: url("@CHEVRON_UP_OFF@");
}
QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {
    image: url("@CHEVRON_OFF@");
}

QCheckBox { color: @TEXT@; spacing: 9px; }
QCheckBox::indicator {
    width: 18px; height: 18px; border: 1px solid @LINE_HI@;
    border-radius: 6px; background: @SUNKEN@;
}
QCheckBox::indicator:hover { border-color: @ACCENT@; }
QCheckBox::indicator:checked {
    background: @ACCENT@; border-color: @ACCENT@; image: url("@CHECK@");
}
QCheckBox::indicator:checked:hover { background: #7d87ff; }
QCheckBox::indicator:disabled { border-color: @LINE@; background: @PRESSED@; }
QCheckBox::indicator:checked:disabled {
    background: @LINE_HI@; border-color: @LINE_HI@;
}

/* ---- nút ---- */
QPushButton {
    background: @RAISED@; border: 1px solid @LINE_STRONG@; border-radius: 9px;
    padding: 8px 14px; color: @TEXT@; font-weight: 500;
}
QPushButton:hover { background: @HOVER@; border-color: @LINE_HI@; }
QPushButton:pressed { background: @PRESSED@; }
QPushButton:focus { border-color: @ACCENT@; }
QPushButton:disabled { color: @TEXT_OFF@; background: @PRESSED@; border-color: @LINE@; }
QPushButton#primary {
    background: #fafafa; border-color: #fafafa; color: #0a0a0c; font-weight: 600;
    padding: 8px 16px;
}
QPushButton#primary:hover { background: #ffffff; border-color: #ffffff; }
QPushButton#primary:pressed { background: #d8dae0; border-color: #d8dae0; }
QPushButton#primary:disabled {
    background: @RAISED@; color: @TEXT_OFF@; border-color: @LINE@;
}
QPushButton#ghost {
    background: transparent; border-color: transparent; color: @TEXT_DIM@;
}
QPushButton#ghost:hover { background: @RAISED@; color: @TEXT@; }
QPushButton#ghost:disabled { background: transparent; border-color: transparent; }
QPushButton#danger { color: @DANGER@; }
QPushButton#danger:hover {
    background: @DANGER_SOFT@; border-color: @DANGER@; color: #ffe4e9;
}
QPushButton#modelDownload { padding: 7px 13px; }

/* ---- huy hiệu & chip ---- */
QLabel#engineBadge, QLabel#stateBadge {
    font-family: @FONT_MONO@; font-size: 10px; font-weight: 600;
    border-radius: 6px; padding: 3px 8px;
}
QLabel#engineBadge[state="ready"], QLabel#stateBadge[state="ready"] {
    color: @OK@; background: @OK_SOFT@;
}
QLabel#engineBadge[state="fallback"], QLabel#stateBadge[state="fallback"] {
    color: @ACCENT_HI@; background: @ACCENT_SOFT@;
}
QLabel#engineBadge[state="busy"], QLabel#stateBadge[state="busy"] {
    color: @BUSY@; background: @BUSY_SOFT@;
}
QLabel#engineBadge[state="missing"], QLabel#stateBadge[state="missing"] {
    color: @DANGER@; background: @DANGER_SOFT@;
}
QLabel#statChip {
    font-family: @FONT_MONO@; font-size: 11px; color: @TEXT_DIM@;
    background: @RAISED@; border: 1px solid @LINE@; border-radius: 7px;
    padding: 4px 8px;
}
QLabel#kbd {
    font-family: @FONT_MONO@; font-size: 11px; color: @TEXT_DIM@;
    background: @RAISED@; border: 1px solid @LINE_STRONG@; border-radius: 6px;
    padding: 2px 7px;
}
QLabel#modelTitle { color: @TEXT@; font-size: 13px; font-weight: 600; }
QLabel#modelMetrics { color: @TEXT_DIM@; font-size: 11px; font-family: @FONT_MONO@; }
QLabel#modelLanguages { color: @TEXT_MUTED@; font-size: 12px; }
QLabel#link, QLabel#llmRegistration { color: @ACCENT_HI@; font-size: 12px; }
QLabel#link:hover, QLabel#llmRegistration:hover { color: #d5daff; }

/* ---- danh sách (dialog provider) ---- */
QListWidget {
    background: @SUNKEN@; border: 1px solid @LINE@; border-radius: 10px;
    padding: 5px; outline: none; color: @TEXT_DIM@;
}
QListWidget::item { padding: 6px 8px; border-radius: 7px; }
QListWidget::item:hover { background: @RAISED@; color: @TEXT@; }
QListWidget::item:selected { background: @ACCENT_SOFT@; color: #ffffff; }

/* ---- vùng cuộn ---- */
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical {
    background: @LINE_STRONG@; border-radius: 5px; min-height: 32px;
}
QScrollBar::handle:vertical:hover { background: @LINE_HI@; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal {
    background: @LINE_STRONG@; border-radius: 5px; min-width: 32px;
}
QScrollBar::handle:horizontal:hover { background: @LINE_HI@; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""

_PLACEHOLDER = re.compile(r"@([A-Z0-9_]+)@")


def build_style(assets: dict[str, str] | None = None) -> str:
    """Thay token + đường dẫn asset (mũi tên, dấu tích) vào stylesheet."""
    values = dict(TOKENS)
    for key, value in (assets or {}).items():
        values[key.upper()] = value

    def replace(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name not in values:
            raise KeyError(f"Token stylesheet chưa định nghĩa: @{name}@")
        return values[name]

    return _PLACEHOLDER.sub(replace, STYLE)
