"""Qt stylesheet dùng chung của ứng dụng."""

from __future__ import annotations

# "Dark Shell" tối kiểu Linear/Vercel cho cửa sổ Cài đặt; HUD dùng lớp glass
# bán trong suốt (rgba) để nhìn xuyên xuống desktop mà chữ vẫn đọc rõ.
STYLE = """
* {
    font-family: 'Segoe UI Variable', 'Segoe UI', 'Segoe UI Emoji', system-ui, sans-serif;
    font-size: 13px;
}
QWidget { color: #f4f4f5; background: transparent; }
QLabel { background: transparent; border: none; }
QLabel:disabled { color: #4b4b52; }
QToolTip {
    background: #1a1a1e; color: #f4f4f5; border: 1px solid #2e2e33;
    border-radius: 6px; padding: 6px 9px;
}
QMenu {
    background: #141416; color: #f4f4f5; border: 1px solid #26262b;
    padding: 4px; border-radius: 10px;
}
QMenu::item { padding: 7px 24px 7px 10px; border-radius: 6px; }
QMenu::item:selected { background: #232328; color: #ffffff; }
QMenu::separator { height: 1px; background: #232327; margin: 4px 6px; }

/* ---------- HUD trong suốt ---------- */
/* Thanh bar: lớp glass tối, gần đục để bấm chính xác. */
QFrame#hudBar {
    background: rgba(16, 18, 24, 0.94);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
}
/* Vùng hiển thị bản dịch: TRONG SUỐT hoàn toàn (không nền) — chỉ thấy chữ
   nổi trên desktop; chữ có bóng đổ (drop shadow) để đọc rõ trên mọi nền. */
QFrame#hudDisplay {
    background: transparent;
    border: none;
}
QLabel#hudLogo {
    background: #5b62f0; color: #ffffff; border-radius: 6px;
    font-size: 11px; font-weight: 800;
}
QPushButton#barBtn {
    background: transparent; border: 1px solid transparent; border-radius: 7px;
}
QPushButton#barBtn:hover { background: rgba(255, 255, 255, 0.09); }
QPushButton#barBtn:pressed { background: rgba(255, 255, 255, 0.05); }
QPushButton#barBtn:checked {
    background: rgba(129, 140, 248, 0.22); border-color: rgba(129, 140, 248, 0.55);
}
QPushButton#barBtn:focus { border-color: #6366f1; }
QPushButton#barBtn:disabled { background: transparent; }
QFrame#barSep { background: rgba(255, 255, 255, 0.10); max-width: 1px; border: none; }
QComboBox#barCombo {
    background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(255,255,255,0.10);
    border-radius: 7px; padding: 3px 7px; min-height: 13px; color: #f4f4f5;
    font-size: 12px;
}
QComboBox#barCombo:hover { border-color: rgba(255,255,255,0.22); }
QComboBox#barCombo:focus { border-color: #6366f1; }
QComboBox#barCombo::drop-down { border: none; width: 20px; }
QComboBox#barCombo::down-arrow { image: url(@CHEVRON@); width: 12px; height: 12px; }
QComboBox QAbstractItemView {
    background: #161619; border: 1px solid #2c2c32; border-radius: 10px;
    selection-background-color: #2c2c32; selection-color: #ffffff;
    color: #f4f4f5; outline: none; padding: 4px;
}
QSizeGrip { background: transparent; width: 14px; height: 14px; }

/* ---------- Cửa sổ Cài đặt (dark shell) ---------- */
QWidget#settingsRoot { background: #0a0a0b; color: #f4f4f5; }
QLabel#pageTitle { font-size: 18px; font-weight: 600; color: #fafafa; }
QLabel#pageSubtitle { color: #77777f; font-size: 12px; }
QLabel#brandWordmark { color: #fafafa; font-size: 14px; font-weight: 600; }
QLabel#brandVersion {
    color: #a1a1aa; font-size: 11px; font-weight: 500;
    background: #17171b; border: 1px solid #26262b; border-radius: 5px;
    padding: 2px 7px;
}
QLabel#muted { color: #77777f; font-size: 12px; }
QLabel#tabTitle { color: #fafafa; font-size: 17px; font-weight: 600; }
QLabel#tabDescription { color: #8b8b93; font-size: 12px; }
QLabel#fieldLabel { font-weight: 600; color: #77777f; font-size: 11px; }
QLabel#hotkeyLabel { font-size: 13px; color: #e4e4e7; }

QListWidget#settingsNav {
    background: #0e0e10; border: 1px solid #232327; border-radius: 10px;
    padding: 6px; outline: none;
}
QListWidget#settingsNav::item {
    color: #9b9ba3; border: 1px solid transparent; border-radius: 7px;
    padding: 10px 11px; margin: 1px 0;
}
QListWidget#settingsNav::item:hover {
    color: #e4e4e7; background: #18181b;
}
QListWidget#settingsNav::item:selected {
    color: #ffffff; background: #232328; border-color: #34343a;
}
QListWidget#settingsNav::item:selected:active,
QListWidget#settingsNav::item:selected:!active {
    color: #ffffff; background: #232328; border-color: #34343a;
}
QStackedWidget#settingsPages { background: transparent; }

QLineEdit {
    background: #111113; border: 1px solid #26262b; border-radius: 8px;
    padding: 9px 11px; color: #f4f4f5;
    selection-background-color: #3f3f46; selection-color: #fafafa;
}
QLineEdit:focus { border: 1px solid #6366f1; }
QLineEdit#hotkey {
    font-family: 'Cascadia Mono', 'JetBrains Mono', 'Consolas', monospace;
    font-size: 12px; padding: 7px 10px; color: #e4e4e7;
}
QLineEdit#hotkey[recording="true"] {
    border: 1px solid #6366f1; color: #a5b4fc; background: #16161c;
}
QComboBox {
    background: #111113; border: 1px solid #26262b; border-radius: 8px;
    padding: 6px 11px; min-height: 18px; color: #f4f4f5;
}
QComboBox:hover { border-color: #3f3f46; }
QComboBox:focus { border-color: #6366f1; }
QComboBox:disabled { color: #5b5b63; background: #0e0e10; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: url(@CHEVRON@); width: 12px; height: 12px; }
QSpinBox, QDoubleSpinBox {
    background: #111113; border: 1px solid #26262b; border-radius: 8px;
    padding: 6px 26px 6px 11px; min-height: 18px; color: #f4f4f5;
    selection-background-color: #3f3f46; selection-color: #fafafa;
}
QSpinBox:hover, QDoubleSpinBox:hover { border-color: #3f3f46; }
QSpinBox:focus, QDoubleSpinBox:focus { border-color: #6366f1; }
QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: #5b5b63; background: #0e0e10;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: #18181b; border: none; border-left: 1px solid #2c2c32;
    width: 20px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button {
    border-top-right-radius: 7px;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    border-bottom-right-radius: 7px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background: #29292f;
}
QCheckBox { color: #e4e4e7; spacing: 9px; }
QCheckBox:disabled { color: #5b5b63; }
QCheckBox::indicator {
    width: 17px; height: 17px; border: 1px solid #3f3f46;
    border-radius: 5px; background: #111113;
}
QCheckBox::indicator:hover { border-color: #6366f1; }
QCheckBox::indicator:checked {
    background: #6366f1; border-color: #818cf8;
}
QPushButton {
    background: #1a1a1e; border: 1px solid #2c2c32; border-radius: 8px;
    padding: 8px 14px; color: #e4e4e7; font-weight: 500;
}
QPushButton:hover { background: #222227; border-color: #3f3f46; }
QPushButton:pressed { background: #141416; }
QPushButton:focus { border-color: #6366f1; }
QPushButton:disabled { color: #5b5b63; background: #101012; border-color: #1e1e22; }
QPushButton#primary {
    background: #fafafa; border: 1px solid #fafafa; color: #09090b;
    font-weight: 600; padding: 9px 16px;
}
QPushButton#primary:hover { background: #ffffff; border-color: #ffffff; }
QPushButton#primary:pressed { background: #d4d4d8; border-color: #d4d4d8; }
QPushButton#primary:disabled {
    background: #17171b; color: #5b5b63; border-color: #26262b;
}

QFrame#surface { background: #111113; border: 1px solid #232327; border-radius: 10px; }
QFrame#engineInfo { background: #111113; border: 1px solid #232327; border-radius: 10px; }
QFrame#modelMeta {
    background: #0e0e10; border: 1px solid #232327; border-radius: 10px;
}
QLabel#engineBadge {
    font-family: 'Cascadia Mono', 'JetBrains Mono', 'Consolas', monospace;
    font-size: 10px; font-weight: 600; border-radius: 6px; padding: 3px 8px;
}
QLabel#engineBadge[state="ready"] { color: #34d399; background: rgba(52, 211, 153, 0.13); }
QLabel#engineBadge[state="fallback"] { color: #a5b4fc; background: rgba(129, 140, 248, 0.15); }
QLabel#engineBadge[state="missing"] { color: #f87171; background: rgba(248, 113, 113, 0.13); }
QLabel#engineHint { color: #8b8b93; font-size: 12px; }
QLabel#modelTitle { color: #f4f4f5; font-size: 13px; font-weight: 600; }
QLabel#modelMetrics {
    color: #a5b4fc; font-size: 11px;
    font-family: 'Cascadia Mono', 'JetBrains Mono', 'Consolas', monospace;
}
QLabel#modelLanguages { color: #8b8b93; font-size: 12px; }
QLabel#llmRegistration { color: #a5b4fc; font-size: 12px; }
QLabel#llmRegistration:hover { color: #c7d2fe; }
QPushButton#modelDownload {
    background: #18181b; border-color: #34343a; padding: 7px 12px;
}
QPushButton#modelDownload:hover { background: #232328; border-color: #52525b; }
QFrame#rowDivider { background: #1e1e22; max-height: 1px; border: none; }

QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 4px 2px; }
QScrollBar::handle:vertical { background: #2c2c32; border-radius: 4px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: #4b4b52; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""
