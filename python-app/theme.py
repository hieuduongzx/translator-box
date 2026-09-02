"""Design token + Qt stylesheet dùng chung của ứng dụng.

Một nguồn sự thật duy nhất cho màu/bán kính/kiểu chữ: `TOKENS` được thay vào
`STYLE` (placeholder dạng `@TÊN@`) bởi `build_style()`. Code Python cần màu thì
đọc `TOKENS` qua `color()` thay vì rải hex khắp nơi.

Hướng thị giác — "Swiss Tactical Terminal" (phẳng, chính xác, near-monochrome),
pha 3 yếu tố:
  - Swiss/International Typographic: nền gần đen, lưới đều, hairline 1px, nhãn
    hoa tracking rộng có chọn lọc, phân cấp bằng khoảng trắng thay vì shadow.
  - Terminal/CLI: IBM Plex Mono cho heading + số liệu, tiêu đề có prefix "// ",
    danh sách đánh số kiểu "[01]", ô dữ liệu kỹ thuật là block `.cmd` có prompt
    và nút copy thật.
  - Blueprint/schematic: ngoặc góc (crop-mark) ở panel nổi bật — mượn từ dấu
    cắt in ấn/bản vẽ kỹ thuật.
Quy tắc: HOÀN TOÀN PHẲNG — không shadow, không gradient. Bán kính bo góc ≤4px
CHỈ ở control; mọi khung/panel chứa bo góc = 0. Accent duy nhất là xanh chanh
neon #c8ff4d cho CTA/trạng thái active. Bốn màu semantic và sáu hue categorical
chỉ xuất hiện trên badge/tag dữ liệu; phần còn lại near-monochrome.
"""

from __future__ import annotations

import re

TOKENS: dict[str, str] = {
    # ---- lớp nền: tactical dark, không dùng đen tuyệt đối ----
    "BG": "#0a0a0b",
    "SURFACE": "#101012",
    "SUNKEN": "#070708",
    "RAISED": "#171719",
    "HOVER": "#202024",
    "PRESSED": "#29292e",
    # ---- hairline ----
    "LINE_SOFT": "#202024",
    "LINE": "#2c2c31",
    "LINE_STRONG": "#414149",
    "LINE_HI": "#62626d",
    # ---- chữ ----
    "TEXT": "#f4f4f5",
    "TEXT_DIM": "#c5c5cb",
    "TEXT_MUTED": "#8b8b95",
    "TEXT_OFF": "#5c5c65",
    # ---- accent duy nhất: xanh chanh neon ----
    "FOCUS": "#c8ff4d",
    "FOCUS_INK": "#0a0a0b",
    "FOCUS_HOVER": "#d5ff73",
    "FOCUS_PRESSED": "#b6ed38",
    "FOCUS_SOFT": "rgba(200, 255, 77, 0.08)",
    "FOCUS_LINE": "rgba(200, 255, 77, 0.46)",
    # ---- 4 màu semantic: chỉ cho badge/tag trạng thái ----
    "OK": "#48d597",
    "OK_SOFT": "rgba(72, 213, 151, 0.12)",
    "BUSY": "#ffca5c",
    "BUSY_SOFT": "rgba(255, 202, 92, 0.12)",
    "DANGER": "#ff6475",
    "DANGER_HOVER_TEXT": "#ff8c99",
    "DANGER_SOFT": "rgba(255, 100, 117, 0.12)",
    "INFO": "#66a3ff",
    "INFO_SOFT": "rgba(102, 163, 255, 0.12)",
    "LIVE": "#c8ff4d",
    # ---- 6 hue categorical: chỉ cho badge/tag phân loại ----
    "CAT_1": "#59dbe8",
    "CAT_1_SOFT": "rgba(89, 219, 232, 0.12)",
    "CAT_2": "#ad8cff",
    "CAT_2_SOFT": "rgba(173, 140, 255, 0.12)",
    "CAT_3": "#ff9d57",
    "CAT_3_SOFT": "rgba(255, 157, 87, 0.12)",
    "CAT_4": "#ed72bb",
    "CAT_4_SOFT": "rgba(237, 114, 187, 0.12)",
    "CAT_5": "#6d8cff",
    "CAT_5_SOFT": "rgba(109, 140, 255, 0.12)",
    "CAT_6": "#5bd6b1",
    "CAT_6_SOFT": "rgba(91, 214, 177, 0.12)",
    # ---- HUD phẳng, đục, không glass/shadow ----
    "BAR": "rgba(10, 10, 11, 0.98)",
    "BAR_LINE": "rgba(244, 244, 245, 0.22)",
    "BAR_HOVER": "rgba(244, 244, 245, 0.08)",
    "BAR_PRESSED": "rgba(244, 244, 245, 0.13)",
    "BAR_FILL": "rgba(244, 244, 245, 0.05)",
    "BAR_FILL_LINE": "rgba(244, 244, 245, 0.18)",
    "BAR_SEP": "rgba(244, 244, 245, 0.18)",
    # ---- terminal `.cmd` ----
    "CODE_BG": "#050506",
    "CODE_BORDER": "#35353c",
    "CODE_TEXT": "#f4f4f5",
    "CODE_PROMPT": "#c8ff4d",
    "CODE_HEADER": "#101012",
    "CODE_BTN_BG": "#101012",
    "CODE_BTN_TEXT": "#a7a7b0",
    "CODE_BTN_HOVER_BG": "#c8ff4d",
    "CODE_BTN_HOVER_TEXT": "#0a0a0b",
    "CODE_BTN_PRESSED_BG": "#b6ed38",
    # ---- kiểu chữ ----
    "FONT": (
        "'Segoe UI Variable Text', 'Segoe UI', 'Segoe UI Emoji', system-ui, sans-serif"
    ),
    "FONT_DISPLAY": (
        "'IBM Plex Mono', 'Cascadia Mono', 'JetBrains Mono', 'Consolas', monospace"
    ),
    "FONT_MONO": (
        "'IBM Plex Mono', 'Cascadia Mono', 'JetBrains Mono', 'Consolas', monospace"
    ),
}


STYLE = """
/* ======================= Nền tảng ======================= */
* {
    font-family: @FONT@;
    font-size: 13px;
    /* Windows vẽ khung focus chấm chấm (PE_FrameFocusRect) đè lên MỌI viền QSS —
       ẩn nó đi và tự vẽ focus bằng :focus/:checked ở từng nơi cần. */
    outline: none;
}
QWidget { color: @TEXT@; background: transparent; }
QLabel { background: transparent; border: none; }
QLabel:disabled, QCheckBox:disabled { color: @TEXT_OFF@; }
QToolTip {
    background: @SURFACE@; color: @TEXT@; border: 1px solid @LINE_STRONG@;
    border-radius: 0px; padding: 7px 10px; font-size: 12px;
}
QMenu {
    background: @SURFACE@; color: @TEXT_DIM@; border: 1px solid @LINE_STRONG@;
    padding: 4px; border-radius: 0px;
}
QMenu::item { padding: 8px 26px 8px 12px; border-radius: 3px; }
QMenu::item:selected { background: @FOCUS@; color: @FOCUS_INK@; }
QMenu::item:disabled { color: @TEXT_OFF@; }
QMenu::separator { height: 1px; background: @LINE@; margin: 5px 8px; }

/* Hộp thoại hệ thống (thông báo cập nhật, xác nhận xoá…) theo cùng shell. */
QDialog, QMessageBox { background: @BG@; }
QMessageBox QLabel { color: @TEXT@; }

/* ======================= HUD tactical ======================= */
/* Thanh bar phẳng, góc vuông, nền gần đen. Ngoặc góc do HudBar tự vẽ. */
QFrame#hudBar {
    background: @BAR@;
    border: 1px solid @BAR_LINE@;
    border-radius: 0px;
}
/* Vùng bản dịch: trong suốt hoàn toàn — chỉ thấy chữ nổi trên desktop. */
QFrame#hudDisplay { background: transparent; border: none; }
QPushButton#barBtn {
    background: transparent; border: 1px solid transparent; border-radius: 3px;
}
QPushButton#barBtn:hover {
    background: @BAR_HOVER@; border-color: @BAR_FILL_LINE@;
}
QPushButton#barBtn:pressed { background: @BAR_PRESSED@; }
QPushButton#barBtn:checked {
    background: @FOCUS@; border-color: @FOCUS@;
}
QPushButton#barBtn:checked:hover { background: @FOCUS_HOVER@; }
QPushButton#barBtn:focus { border-color: @FOCUS@; }
QPushButton#barBtn:disabled { background: transparent; border-color: transparent; }
QPushButton#barBtn[emphasized="true"] {
    background: @FOCUS_SOFT@; border-color: @FOCUS_LINE@;
}
QPushButton#barBtn[emphasized="true"]:hover {
    background: @BAR_HOVER@; border-color: @FOCUS@;
}
QPushButton#barModeButton {
    color: @FOCUS@; background: @FOCUS_SOFT@; border: 1px solid @FOCUS_LINE@;
    border-radius: 3px; padding: 0 10px;
    font-family: @FONT_MONO@; font-size: 11px; font-weight: 600;
}
QPushButton#barModeButton:hover { background: @BAR_HOVER@; border-color: @FOCUS@; }
QPushButton#barModeButton:pressed { background: @BAR_PRESSED@; }
QPushButton#barModeButton:disabled { color: @TEXT_OFF@; border-color: @BAR_FILL_LINE@; }
QPushButton#barGroupToggle {
    color: @TEXT_DIM@; background: @BAR_FILL@; border: 1px solid @BAR_FILL_LINE@;
    border-radius: 3px; padding: 0 9px;
    font-family: @FONT_MONO@; font-size: 10px; font-weight: 600;
}
QPushButton#barGroupToggle:hover {
    color: @TEXT@; background: @BAR_HOVER@; border-color: @LINE_HI@;
}
QPushButton#barGroupToggle[live="true"] {
    color: @FOCUS@; background: @FOCUS_SOFT@; border-color: @FOCUS_LINE@;
}
QPushButton#barGroupToggle:checked {
    color: @FOCUS_INK@; background: @FOCUS@; border-color: @FOCUS@;
}
QPushButton#barGroupToggle:disabled {
    color: @TEXT_OFF@; background: transparent; border-color: @BAR_PRESSED@;
}
QMenu#barActionMenu {
    min-width: 238px; padding: 4px; border: 1px solid @LINE_STRONG@;
}
QMenu#barActionMenu::item {
    min-height: 24px; padding: 6px 18px 6px 9px;
    font-family: @FONT_MONO@; font-size: 11px;
}
QFrame#barSep { background: @BAR_SEP@; max-width: 1px; border: none; }
QComboBox#barCombo {
    background: @BAR_FILL@; border: 1px solid @BAR_FILL_LINE@;
    border-radius: 3px; padding: 4px 8px; min-height: 20px; color: @TEXT@;
    font-family: @FONT_MONO@; font-size: 11px;
}
QComboBox#barCombo:hover { background: @BAR_HOVER@; border-color: @FOCUS_LINE@; }
QComboBox#barCombo:focus, QComboBox#barCombo:on { border-color: @FOCUS@; }
QComboBox#barCombo:disabled { color: @TEXT_OFF@; border-color: @BAR_PRESSED@; }
QComboBox#barCombo::drop-down { border: none; width: 18px; }
QComboBox#barCombo::down-arrow { image: url("@CHEVRON@"); width: 11px; height: 11px; }
QComboBox QAbstractItemView {
    background: @SURFACE@; border: 1px solid @LINE_STRONG@; border-radius: 0px;
    selection-background-color: @FOCUS@; selection-color: @FOCUS_INK@;
    color: @TEXT_DIM@; outline: none; padding: 3px;
}
QComboBox QAbstractItemView::item { min-height: 26px; border-radius: 2px; }
QSizeGrip { background: transparent; width: 14px; height: 14px; }

/* ======================= Cửa sổ Cài đặt ======================= */
QWidget#settingsRoot { background: @BG@; }
QFrame#divider { background: @LINE@; max-height: 1px; border: none; }
QFrame#vDivider { background: @LINE@; max-width: 1px; border: none; }
QFrame#settingsSidebar {
    background: @SUNKEN@; border: none; border-right: 1px solid @LINE@;
}
QLabel#sidebarLabel {
    color: @TEXT_MUTED@; font-family: @FONT_MONO@; font-size: 10px; font-weight: 600;
}
QLabel#sidebarHint { color: @TEXT_MUTED@; font-size: 11px; }
QLabel#brandWordmark {
    font-family: @FONT_DISPLAY@; color: @TEXT@; font-size: 14px; font-weight: 500;
}
QLabel#brandVersion {
    color: @TEXT_DIM@; font-size: 11px; font-family: @FONT_MONO@;
    background: @RAISED@; border: 1px solid @LINE@; border-radius: 3px;
    padding: 2px 7px;
}
QLabel#muted, QLabel#footerHint { color: @TEXT_MUTED@; font-size: 12px; }
QLabel#pageTitle, QLabel#tabTitle {
    font-family: @FONT_DISPLAY@; color: @TEXT@; font-size: 19px; font-weight: 500;
}
QLabel#pageSubtitle, QLabel#tabDescription { color: @TEXT_DIM@; font-size: 12px; }
QLabel#fieldLabel {
    color: @TEXT_DIM@; font-family: @FONT_MONO@; font-size: 11px; font-weight: 600;
}

QListWidget#settingsNav {
    background: transparent; border: none; padding: 0; outline: none;
    font-family: @FONT_MONO@;
}
QListWidget#settingsNav::item {
    color: @TEXT_DIM@; font-size: 12px; border: 1px solid transparent;
    border-radius: 0px; padding: 10px 11px; margin: 0;
}
QListWidget#settingsNav::item:hover { color: @TEXT@; background: @SURFACE@; }
QListWidget#settingsNav::item:selected,
QListWidget#settingsNav::item:selected:active,
QListWidget#settingsNav::item:selected:!active {
    color: @FOCUS_INK@; background: @FOCUS@; border-color: @FOCUS@;
}
QStackedWidget#settingsPages { background: transparent; }

/* ---- panel: góc vuông, phân cấp bằng hairline + khoảng trắng ---- */
QFrame#card, QFrame#surface, QFrame#engineInfo, QFrame#cardFeatured {
    background: @SURFACE@; border: 1px solid @LINE@; border-radius: 0px;
}
QFrame#cardFeatured { border-color: @LINE_STRONG@; }
QFrame#cardSunken, QFrame#modelMeta {
    background: @SUNKEN@; border: 1px solid @LINE@; border-radius: 0px;
}
/* Khung xem trước: nền bàn cờ do widget tự vẽ nên chỉ giữ lại viền + crop-mark. */
QFrame#previewSurface {
    background: transparent; border: 1px solid @LINE@; border-radius: 0px;
}
QLabel#cardTitle {
    color: @TEXT@; font-family: @FONT_DISPLAY@; font-size: 12px; font-weight: 500;
}
QLabel#cardHint { color: @TEXT_MUTED@; font-size: 12px; }
QLabel#rowLabel, QLabel#hotkeyLabel { color: @TEXT@; font-size: 13px; }
QLabel#rowHint, QLabel#engineHint { color: @TEXT_MUTED@; font-size: 12px; }
QLabel#aiProviderStatus {
    font-family: @FONT_MONO@; font-size: 10px; font-weight: 600;
    border-radius: 2px; padding: 4px 8px;
}
QLabel#aiProviderStatus[state="active"] {
    color: @FOCUS@; background: @FOCUS_SOFT@; border: 1px solid @FOCUS_LINE@;
}
QLabel#aiProviderStatus[state="inactive"] {
    color: @TEXT_MUTED@; background: @RAISED@; border: 1px solid @LINE@;
}
QFrame#rowDivider { background: @LINE_SOFT@; max-height: 1px; border: none; }

/* ---- ô nhập ---- */
QLineEdit {
    background: @SUNKEN@; border: 1px solid @LINE@; border-radius: 3px;
    padding: 8px 11px; color: @TEXT@;
    selection-background-color: @FOCUS@; selection-color: @FOCUS_INK@;
}
QLineEdit:hover { border-color: @LINE_STRONG@; }
QLineEdit:focus { border-color: @FOCUS@; }
QLineEdit:read-only { color: @TEXT_DIM@; background: @PRESSED@; }
QLineEdit:disabled { color: @TEXT_OFF@; background: @PRESSED@; }
QLineEdit#hotkey {
    font-family: @FONT_MONO@; font-size: 12px; padding: 7px 10px; color: @TEXT@;
    background: @RAISED@; border: 1px solid @LINE_STRONG@; border-radius: 3px;
}
QLineEdit#hotkey:hover { border-color: @LINE_HI@; }
QLineEdit#hotkey[recording="true"] {
    border-color: @FOCUS@; color: @FOCUS@; background: @PRESSED@;
}
QLineEdit#hotkey[conflict="true"] { border-color: @DANGER@; color: @DANGER@; }

/* ---- block `.cmd`: header, prompt, lệnh và nút copy thực ---- */
QFrame#codeBlock {
    background: @CODE_BG@; border: 1px solid @CODE_BORDER@; border-radius: 0px;
}
QFrame#codeHeader {
    background: @CODE_HEADER@; border: none; border-bottom: 1px solid @CODE_BORDER@;
}
QLabel#codeTitle {
    color: @TEXT_MUTED@; font-family: @FONT_MONO@; font-size: 10px; font-weight: 600;
}
QLabel#codePrompt {
    color: @CODE_PROMPT@; font-family: @FONT_MONO@; font-size: 12px; font-weight: 600;
}
QLineEdit#codeField {
    font-family: @FONT_MONO@; font-size: 12px; color: @CODE_TEXT@;
    background: transparent; border: none; border-radius: 0px; padding: 8px 8px 9px 0;
}
QLineEdit#codeField:focus { color: @CODE_TEXT@; }
QPushButton#codeCopyBtn {
    font-family: @FONT_MONO@; font-size: 10px; font-weight: 600;
    color: @CODE_BTN_TEXT@; background: @CODE_BTN_BG@;
    border: none; border-left: 1px solid @CODE_BORDER@;
    border-radius: 0px; padding: 6px 12px;
}
QPushButton#codeCopyBtn:hover {
    background: @CODE_BTN_HOVER_BG@; color: @CODE_BTN_HOVER_TEXT@;
}
QPushButton#codeCopyBtn:pressed { background: @CODE_BTN_PRESSED_BG@; }

QComboBox {
    background: @SUNKEN@; border: 1px solid @LINE@; border-radius: 3px;
    padding: 7px 11px; min-height: 20px; color: @TEXT@;
}
QComboBox:hover { border-color: @LINE_STRONG@; }
QComboBox:focus, QComboBox:on { border-color: @FOCUS@; }
QComboBox:disabled { color: @TEXT_OFF@; background: @PRESSED@; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: url("@CHEVRON@"); width: 12px; height: 12px; }
QComboBox::down-arrow:disabled { image: url("@CHEVRON_OFF@"); }

QSpinBox, QDoubleSpinBox {
    background: @SUNKEN@; border: 1px solid @LINE@; border-radius: 3px;
    padding: 7px 30px 7px 11px; min-height: 20px; color: @TEXT@;
    selection-background-color: @FOCUS@; selection-color: @FOCUS_INK@;
}
QSpinBox:hover, QDoubleSpinBox:hover { border-color: @LINE_STRONG@; }
QSpinBox:focus, QDoubleSpinBox:focus { border-color: @FOCUS@; }
QSpinBox:disabled, QDoubleSpinBox:disabled { color: @TEXT_OFF@; background: @PRESSED@; }
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: transparent; border: none; width: 22px; border-radius: 0px;
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
    width: 17px; height: 17px; border: 1px solid @LINE_HI@;
    border-radius: 2px; background: @SUNKEN@;
}
QCheckBox::indicator:hover { border-color: @FOCUS@; }
QCheckBox::indicator:checked {
    background: @FOCUS@; border-color: @FOCUS@; image: url("@CHECK@");
}
QCheckBox::indicator:checked:hover { background: @FOCUS_HOVER@; }
QCheckBox::indicator:disabled { border-color: @LINE@; background: @PRESSED@; }
QCheckBox::indicator:checked:disabled {
    background: @LINE_HI@; border-color: @LINE_HI@;
}

/* ---- nút ---- */
QPushButton {
    background: @RAISED@; border: 1px solid @LINE_STRONG@; border-radius: 3px;
    padding: 8px 14px; color: @TEXT@; font-weight: 500;
}
QPushButton:hover { background: @HOVER@; border-color: @LINE_HI@; }
QPushButton:pressed { background: @PRESSED@; }
QPushButton:focus { border-color: @FOCUS@; }
QPushButton:disabled { color: @TEXT_OFF@; background: @PRESSED@; border-color: @LINE@; }
QPushButton#primary {
    background: @FOCUS@; border-color: @FOCUS@; color: @FOCUS_INK@; font-weight: 600;
    padding: 8px 16px;
}
QPushButton#primary:hover { background: @FOCUS_HOVER@; border-color: @FOCUS_HOVER@; }
QPushButton#primary:pressed { background: @FOCUS_PRESSED@; border-color: @FOCUS_PRESSED@; }
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
    background: @DANGER_SOFT@; border-color: @DANGER@; color: @DANGER_HOVER_TEXT@;
}
QPushButton#modelDownload { padding: 7px 13px; }

/* ---- badge/tag: semantic và categorical là hai bảng màu riêng ---- */
QLabel#engineBadge, QLabel#stateBadge, QLabel#categoryBadge {
    font-family: @FONT_MONO@; font-size: 10px; font-weight: 600;
    border-radius: 2px; padding: 3px 8px; border: 1px solid transparent;
}
QLabel#engineBadge[state="ready"], QLabel#stateBadge[state="ready"] {
    color: @OK@; background: @OK_SOFT@;
}
QLabel#engineBadge[state="fallback"], QLabel#stateBadge[state="fallback"] {
    color: @INFO@; background: @INFO_SOFT@;
}
QLabel#engineBadge[state="busy"], QLabel#stateBadge[state="busy"] {
    color: @BUSY@; background: @BUSY_SOFT@;
}
QLabel#engineBadge[state="missing"], QLabel#stateBadge[state="missing"] {
    color: @DANGER@; background: @DANGER_SOFT@;
}
QLabel#categoryBadge[category="1"] { color: @CAT_1@; background: @CAT_1_SOFT@; }
QLabel#categoryBadge[category="2"] { color: @CAT_2@; background: @CAT_2_SOFT@; }
QLabel#categoryBadge[category="3"] { color: @CAT_3@; background: @CAT_3_SOFT@; }
QLabel#categoryBadge[category="4"] { color: @CAT_4@; background: @CAT_4_SOFT@; }
QLabel#categoryBadge[category="5"] { color: @CAT_5@; background: @CAT_5_SOFT@; }
QLabel#categoryBadge[category="6"] { color: @CAT_6@; background: @CAT_6_SOFT@; }
QLabel#statChip {
    font-family: @FONT_MONO@; font-size: 11px; color: @TEXT_DIM@;
    background: @RAISED@; border: 1px solid @LINE@; border-radius: 2px;
    padding: 4px 8px;
}
QLabel#kbd {
    font-family: @FONT_MONO@; font-size: 11px; color: @TEXT_DIM@;
    background: @RAISED@; border: 1px solid @LINE_STRONG@; border-radius: 2px;
    padding: 2px 7px;
}
QLabel#modelTitle { color: @TEXT@; font-size: 13px; font-weight: 600; }
QLabel#modelDownloadStatus { color: @TEXT_DIM@; font-size: 12px; }
QLabel#modelDownloadStatus[state="ready"] { color: @OK@; }
QLabel#modelDownloadStatus[state="busy"] { color: @BUSY@; }
QLabel#modelDownloadStatus[state="error"] { color: @DANGER@; }
QLabel#modelMetrics { color: @TEXT_DIM@; font-size: 11px; font-family: @FONT_MONO@; }
QLabel#modelLanguages { color: @TEXT_MUTED@; font-size: 12px; }
QLabel#link, QLabel#llmRegistration {
    color: @FOCUS@; font-size: 12px;
}
/* ---- danh sách (dialog provider) ---- */
QListWidget {
    background: @SUNKEN@; border: 1px solid @LINE@; border-radius: 0px;
    padding: 4px; outline: none; color: @TEXT_DIM@;
}
QListWidget::item { padding: 6px 8px; border-radius: 2px; }
QListWidget::item:hover { background: @RAISED@; color: @TEXT@; }
QListWidget::item:selected { background: @FOCUS@; color: @FOCUS_INK@; }

/* ---- vùng cuộn ---- */
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical {
    background: @LINE_STRONG@; border-radius: 0px; min-height: 32px;
}
QScrollBar::handle:vertical:hover { background: @LINE_HI@; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal {
    background: @LINE_STRONG@; border-radius: 0px; min-width: 32px;
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
