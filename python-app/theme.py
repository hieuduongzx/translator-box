"""Design token + Qt stylesheet dùng chung của ứng dụng.

Một nguồn sự thật duy nhất cho màu/bán kính/kiểu chữ: `TOKENS` được thay vào
`STYLE` (placeholder dạng `@TÊN@`) bởi `build_style()`. Code Python cần màu thì
đọc `TOKENS` thay vì rải hex khắp nơi.

Hướng thị giác — tối giản, phẳng, im lặng:
  - Một font hệ thống cho toàn bộ chữ. Mono CHỈ dùng cho giá trị kỹ thuật thật
    (phím tắt, endpoint, số phiên bản) — không dùng cho tiêu đề hay nhãn.
  - Không tiền tố "// ", không nhãn HOA giãn chữ, không đánh số "[01]", không
    ngoặc góc trang trí. Phân cấp bằng khoảng trắng, cỡ chữ và một hairline.
  - Không shadow, không gradient. Bán kính bo góc theo hai bậc: @RADIUS@ cho
    control, @RADIUS_LG@ cho panel/khung.
  - Một accent duy nhất (lime thương hiệu) cho CTA/trạng thái đang bật. Ba màu
    trạng thái (ok/busy/danger) chỉ xuất hiện ở badge và chấm trạng thái.
"""

from __future__ import annotations

import re

TOKENS: dict[str, str] = {
    # ---- bán kính: chỉ hai bậc cho toàn app ----
    "RADIUS": "4px",
    "RADIUS_LG": "6px",
    # ---- lớp nền ----
    "BG": "#0f0f11",
    "SURFACE": "#16161a",
    "SUNKEN": "#101013",
    "RAISED": "#1d1d22",
    "HOVER": "#26262c",
    "PRESSED": "#2e2e35",
    # ---- hairline ----
    "LINE": "#26262c",
    "LINE_STRONG": "#33333b",
    "LINE_HI": "#4a4a54",
    # ---- chữ ----
    "TEXT": "#f2f2f3",
    "TEXT_DIM": "#b9b9c0",
    "TEXT_MUTED": "#86868f",
    "TEXT_OFF": "#5a5a63",
    # ---- accent duy nhất ----
    "FOCUS": "#c8ff4d",
    "FOCUS_INK": "#0f0f11",
    "FOCUS_HOVER": "#d6ff77",
    "FOCUS_PRESSED": "#b4ed36",
    "FOCUS_SOFT": "rgba(200, 255, 77, 0.10)",
    "FOCUS_LINE": "rgba(200, 255, 77, 0.42)",
    # ---- trạng thái: chỉ cho badge và chấm trạng thái ----
    "OK": "#4ad295",
    "OK_SOFT": "rgba(74, 210, 149, 0.12)",
    "BUSY": "#ffc95c",
    "BUSY_SOFT": "rgba(255, 201, 92, 0.12)",
    "DANGER": "#ff6b7a",
    "DANGER_SOFT": "rgba(255, 107, 122, 0.12)",
    "INFO": "#6ea8ff",
    "INFO_SOFT": "rgba(110, 168, 255, 0.12)",
    # ---- HUD: phẳng, đục, không glass ----
    "BAR": "rgba(15, 15, 17, 0.97)",
    "BAR_LINE": "rgba(242, 242, 243, 0.16)",
    "BAR_HOVER": "rgba(242, 242, 243, 0.08)",
    "BAR_PRESSED": "rgba(242, 242, 243, 0.13)",
    "BAR_FILL": "rgba(242, 242, 243, 0.05)",
    "BAR_FILL_LINE": "rgba(242, 242, 243, 0.14)",
    # ---- kiểu chữ ----
    "FONT": (
        "'Segoe UI Variable Text', 'Segoe UI', 'Segoe UI Emoji', system-ui, sans-serif"
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
    border-radius: @RADIUS@; padding: 6px 9px; font-size: 12px;
}
QMenu {
    background: @SURFACE@; color: @TEXT_DIM@; border: 1px solid @LINE_STRONG@;
    padding: 5px; border-radius: @RADIUS_LG@;
}
QMenu::item { padding: 7px 24px 7px 11px; border-radius: @RADIUS@; }
QMenu::item:selected { background: @HOVER@; color: @TEXT@; }
QMenu::item:checked { color: @FOCUS@; }
QMenu::item:disabled { color: @TEXT_OFF@; }
QMenu::separator { height: 1px; background: @LINE@; margin: 5px 7px; }

/* Hộp thoại hệ thống (thông báo cập nhật, xác nhận xoá…) theo cùng shell. */
QDialog, QMessageBox { background: @BG@; }
QMessageBox QLabel { color: @TEXT@; }

/* ======================= HUD ======================= */
QFrame#hudBar {
    background: @BAR@;
    border: 1px solid @BAR_LINE@;
    border-radius: @RADIUS_LG@;
}
/* Vùng bản dịch: trong suốt hoàn toàn — chỉ thấy chữ nổi trên desktop. */
QFrame#hudDisplay { background: transparent; border: none; }
QPushButton#barBtn {
    background: transparent; border: 1px solid transparent;
    border-radius: @RADIUS@;
}
QPushButton#barBtn:hover { background: @BAR_HOVER@; }
QPushButton#barBtn:pressed { background: @BAR_PRESSED@; }
QPushButton#barBtn:checked { background: @FOCUS@; border-color: @FOCUS@; }
QPushButton#barBtn:checked:hover { background: @FOCUS_HOVER@; }
QPushButton#barBtn:focus { border-color: @FOCUS_LINE@; }
QPushButton#barBtn:disabled { background: transparent; border-color: transparent; }
QPushButton#barAction {
    color: @TEXT_DIM@; background: transparent;
    border: 1px solid transparent; border-radius: @RADIUS@;
    padding: 0 10px 0 8px; text-align: left;
}
QPushButton#barAction:hover { color: @TEXT@; background: @BAR_HOVER@; }
QPushButton#barAction:pressed { background: @BAR_PRESSED@; }
QPushButton#barAction:checked { color: @TEXT@; background: @BAR_PRESSED@; }
QPushButton#barAction:focus { border-color: @FOCUS_LINE@; }
QPushButton#barAction[live="true"] {
    color: @FOCUS@; background: @FOCUS_SOFT@; border-color: @FOCUS_LINE@;
}
QPushButton#barAction:disabled { color: @TEXT_OFF@; background: transparent; }
QComboBox#barCombo {
    background: @BAR_FILL@; border: 1px solid @BAR_FILL_LINE@;
    border-radius: @RADIUS@; padding: 4px 6px 4px 9px; min-height: 20px;
    color: @TEXT_DIM@;
}
QComboBox#barCombo:hover { color: @TEXT@; background: @BAR_HOVER@; }
QComboBox#barCombo:focus, QComboBox#barCombo:on { border-color: @FOCUS_LINE@; }
QComboBox#barCombo:disabled { color: @TEXT_OFF@; border-color: @BAR_PRESSED@; }
QComboBox#barCombo::drop-down { border: none; width: 16px; }
QComboBox#barCombo::down-arrow { image: url("@CHEVRON@"); width: 11px; height: 11px; }
QComboBox QAbstractItemView {
    background: @SURFACE@; border: 1px solid @LINE_STRONG@;
    border-radius: @RADIUS_LG@;
    selection-background-color: @HOVER@; selection-color: @TEXT@;
    color: @TEXT_DIM@; outline: none; padding: 4px;
}
QComboBox QAbstractItemView::item { min-height: 26px; border-radius: @RADIUS@; }
QSizeGrip { background: transparent; width: 14px; height: 14px; }

/* Chấm + nhãn trạng thái trên bar. */
QFrame#statusDot { border: none; border-radius: 3px; background: @TEXT_MUTED@; }
QFrame#statusDot[state="ok"] { background: @OK@; }
QFrame#statusDot[state="busy"] { background: @BUSY@; }
QFrame#statusDot[state="error"] { background: @DANGER@; }
QLabel#statusText { color: @TEXT_MUTED@; font-size: 12px; }

/* ======================= Cửa sổ Cài đặt ======================= */
QWidget#settingsRoot { background: @BG@; }
QFrame#settingsSidebar {
    background: @SUNKEN@; border: none; border-right: 1px solid @LINE@;
}
QLabel#sidebarHint { color: @TEXT_MUTED@; font-size: 11px; }
QLabel#brandWordmark { color: @TEXT@; font-size: 14px; font-weight: 600; }
QLabel#brandVersion {
    color: @TEXT_MUTED@; font-size: 11px; font-family: @FONT_MONO@;
}
QLabel#muted { color: @TEXT_MUTED@; font-size: 12px; }
QLabel#pageTitle { color: @TEXT@; font-size: 20px; font-weight: 600; }
QLabel#pageSubtitle { color: @TEXT_MUTED@; font-size: 12px; }
QLabel#fieldLabel { color: @TEXT_DIM@; font-size: 12px; }

QListWidget#settingsNav {
    background: transparent; border: none; padding: 0; outline: none;
}
QListWidget#settingsNav::item {
    color: @TEXT_DIM@; font-size: 13px; border: 1px solid transparent;
    border-radius: @RADIUS@; padding: 8px 10px; margin: 1px 0;
}
QListWidget#settingsNav::item:hover { color: @TEXT@; background: @SURFACE@; }
QListWidget#settingsNav::item:selected,
QListWidget#settingsNav::item:selected:active,
QListWidget#settingsNav::item:selected:!active {
    color: @TEXT@; background: @RAISED@; border-color: @LINE_STRONG@;
}
QStackedWidget#settingsPages { background: transparent; }

/* ---- panel ---- */
QFrame#card, QFrame#engineInfo {
    background: @SURFACE@; border: 1px solid @LINE@; border-radius: @RADIUS_LG@;
}
QFrame#cardSunken, QFrame#modelMeta {
    background: @SUNKEN@; border: 1px solid @LINE@; border-radius: @RADIUS_LG@;
}
/* Khung xem trước: nền bàn cờ do widget tự vẽ nên chỉ giữ lại viền. */
QFrame#previewSurface {
    background: transparent; border: 1px solid @LINE@; border-radius: @RADIUS_LG@;
}
QLabel#cardTitle { color: @TEXT@; font-size: 13px; font-weight: 600; }
QLabel#cardHint { color: @TEXT_MUTED@; font-size: 12px; }
QLabel#rowLabel { color: @TEXT@; font-size: 13px; }
QLabel#rowHint, QLabel#engineHint { color: @TEXT_MUTED@; font-size: 12px; }
QFrame#rowDivider { background: @LINE@; max-height: 1px; border: none; }

/* ---- ô nhập ---- */
QLineEdit {
    background: @SUNKEN@; border: 1px solid @LINE_STRONG@; border-radius: @RADIUS@;
    padding: 7px 10px; color: @TEXT@;
    selection-background-color: @FOCUS@; selection-color: @FOCUS_INK@;
}
QLineEdit:hover { border-color: @LINE_HI@; }
QLineEdit:focus { border-color: @FOCUS@; }
QLineEdit:read-only { color: @TEXT_DIM@; }
QLineEdit:disabled { color: @TEXT_OFF@; background: @PRESSED@; }
QLineEdit#hotkey {
    font-family: @FONT_MONO@; font-size: 12px; color: @TEXT@;
    background: @RAISED@; border: 1px solid @LINE_STRONG@;
}
QLineEdit#hotkey:hover { border-color: @LINE_HI@; }
QLineEdit#hotkey[recording="true"] {
    border-color: @FOCUS@; color: @FOCUS@; background: @PRESSED@;
}
QLineEdit#hotkey[conflict="true"] { border-color: @DANGER@; color: @DANGER@; }

/* ---- ô giá trị kỹ thuật (endpoint, repo) + nút copy ---- */
QFrame#codeBlock {
    background: @SUNKEN@; border: 1px solid @LINE_STRONG@;
    border-radius: @RADIUS@;
}
QLineEdit#codeField {
    font-family: @FONT_MONO@; font-size: 12px; color: @TEXT_DIM@;
    background: transparent; border: none; border-radius: 0px; padding: 6px 0 6px 10px;
}
QPushButton#codeCopyBtn {
    font-size: 12px; color: @TEXT_MUTED@; background: transparent;
    border: none; border-radius: @RADIUS@; padding: 6px 10px;
}
QPushButton#codeCopyBtn:hover { color: @TEXT@; background: @HOVER@; }
QPushButton#codeCopyBtn:pressed { background: @PRESSED@; }

QComboBox {
    background: @SUNKEN@; border: 1px solid @LINE_STRONG@; border-radius: @RADIUS@;
    padding: 6px 10px; min-height: 20px; color: @TEXT@;
}
QComboBox:hover { border-color: @LINE_HI@; }
QComboBox:focus, QComboBox:on { border-color: @FOCUS@; }
QComboBox:disabled { color: @TEXT_OFF@; background: @PRESSED@; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: url("@CHEVRON@"); width: 12px; height: 12px; }
QComboBox::down-arrow:disabled { image: url("@CHEVRON_OFF@"); }

QSpinBox, QDoubleSpinBox {
    background: @SUNKEN@; border: 1px solid @LINE_STRONG@; border-radius: @RADIUS@;
    padding: 6px 28px 6px 10px; min-height: 20px; color: @TEXT@;
    selection-background-color: @FOCUS@; selection-color: @FOCUS_INK@;
}
QSpinBox:hover, QDoubleSpinBox:hover { border-color: @LINE_HI@; }
QSpinBox:focus, QDoubleSpinBox:focus { border-color: @FOCUS@; }
QSpinBox:disabled, QDoubleSpinBox:disabled { color: @TEXT_OFF@; background: @PRESSED@; }
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: transparent; border: none; width: 20px;
    border-radius: @RADIUS@; margin: 2px 3px 2px 0;
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

QCheckBox { color: @TEXT@; spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border: 1px solid @LINE_HI@;
    border-radius: @RADIUS@; background: @SUNKEN@;
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
    background: @RAISED@; border: 1px solid @LINE_STRONG@; border-radius: @RADIUS@;
    padding: 7px 13px; color: @TEXT@;
}
QPushButton:hover { background: @HOVER@; border-color: @LINE_HI@; }
QPushButton:pressed { background: @PRESSED@; }
QPushButton:focus { border-color: @FOCUS@; }
QPushButton:disabled { color: @TEXT_OFF@; background: @PRESSED@; border-color: @LINE@; }
QPushButton#primary {
    background: @FOCUS@; border-color: @FOCUS@; color: @FOCUS_INK@; font-weight: 600;
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
    background: @DANGER_SOFT@; border-color: @DANGER@; color: @DANGER@;
}

/* ---- badge trạng thái ---- */
QLabel#engineBadge, QLabel#stateBadge, QLabel#statusBadge {
    font-size: 12px; border-radius: @RADIUS@; padding: 3px 8px;
    border: 1px solid transparent;
}
QLabel#engineBadge[state="ready"], QLabel#stateBadge[state="ready"],
QLabel#statusBadge[state="ready"] { color: @OK@; background: @OK_SOFT@; }
QLabel#engineBadge[state="fallback"], QLabel#stateBadge[state="fallback"],
QLabel#statusBadge[state="fallback"] { color: @INFO@; background: @INFO_SOFT@; }
QLabel#engineBadge[state="busy"], QLabel#stateBadge[state="busy"],
QLabel#statusBadge[state="busy"] { color: @BUSY@; background: @BUSY_SOFT@; }
QLabel#engineBadge[state="missing"], QLabel#stateBadge[state="missing"],
QLabel#statusBadge[state="missing"] { color: @DANGER@; background: @DANGER_SOFT@; }
QLabel#statusBadge[state="active"] {
    color: @FOCUS@; background: @FOCUS_SOFT@; border-color: @FOCUS_LINE@;
}
QLabel#statusBadge[state="inactive"] {
    color: @TEXT_MUTED@; background: @RAISED@; border-color: @LINE@;
}
QLabel#kbd {
    font-family: @FONT_MONO@; font-size: 11px; color: @TEXT_DIM@;
    background: @RAISED@; border: 1px solid @LINE_STRONG@; border-radius: @RADIUS@;
    padding: 2px 6px;
}
QLabel#modelTitle { color: @TEXT@; font-size: 13px; font-weight: 600; }
QLabel#modelDownloadStatus { color: @TEXT_DIM@; font-size: 12px; }
QLabel#modelDownloadStatus[state="ready"] { color: @OK@; }
QLabel#modelDownloadStatus[state="busy"] { color: @BUSY@; }
QLabel#modelDownloadStatus[state="error"] { color: @DANGER@; }
QLabel#modelMetrics { color: @TEXT_MUTED@; font-size: 12px; }
QLabel#modelLanguages { color: @TEXT_MUTED@; font-size: 12px; }
QLabel#link, QLabel#llmRegistration { font-size: 12px; }

/* ---- danh sách (dialog provider) ---- */
QListWidget {
    background: @SUNKEN@; border: 1px solid @LINE@; border-radius: @RADIUS@;
    padding: 4px; outline: none; color: @TEXT_DIM@;
}
QListWidget::item { padding: 6px 8px; border-radius: @RADIUS@; }
QListWidget::item:hover { background: @RAISED@; color: @TEXT@; }
QListWidget::item:selected { background: @RAISED@; color: @TEXT@; }

/* ---- vùng cuộn ---- */
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical {
    background: @LINE_STRONG@; border-radius: 3px; min-height: 32px;
}
QScrollBar::handle:vertical:hover { background: @LINE_HI@; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal {
    background: @LINE_STRONG@; border-radius: 3px; min-width: 32px;
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
