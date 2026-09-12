"""Cửa sổ cấu hình ứng dụng."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import services
from ocr_runtime import (
    OCR_BACKENDS,
    OCR_MODELS,
    backend_label,
    backend_status,
    download_model,
    model_installed,
    model_spec,
)
from config import DEFAULT_HOTKEYS, HUD_STYLE_DEFAULTS
from constants import (
    BUILTIN_AI_BY_ID,
    BUILTIN_AI_IDS,
    HOTKEY_ACTIONS,
    HUD_FONT_OPTIONS,
    LANGUAGES,
    LLM_REGISTRATION_URL,
    OCR_ENGINE_DESCRIPTIONS,
    OCR_ENGINES,
    OCR_LANGUAGES,
    bar_service_key,
    bar_translator_entries,
    SONIOX_LANGUAGES,
    parse_bar_service_key,
)
from soniox_realtime import audio_input_options, system_audio_input_options
from theme import TOKENS
from ui_utils import (
    _brand_pixmap,
    _enable_dark_titlebar,
    _fmt_hotkey,
    _nav_icon,
)
from version import APP_NAME, APP_VERSION, GITHUB_RELEASES_URL, GITHUB_REPO
from widgets import Card, CheckerFrame, CodeField, ColorButton, HotkeyEdit, HudTextView

if TYPE_CHECKING:
    from hud_window import HUDWindow

# Nhóm cài đặt bên trái: (nhãn, icon, mô tả trang).
NAV_SECTIONS = (
    ("Dịch", "globe", "Chọn dịch vụ và ngôn ngữ nhận kết quả."),
    ("Dịch vụ AI", "ai", "API key, model và provider OpenAI-compatible."),
    (
        "Audio",
        "audio",
        "Dịch microphone hoặc audio hệ thống bằng Soniox, nhận diện từng người nói.",
    ),
    ("OCR", "scan", "Engine, mô hình và thiết bị xử lý nhận dạng ngoại tuyến."),
    ("Khung dịch", "type", "Kiểu chữ và màu của bản dịch hiện trên màn hình."),
    ("Phím tắt", "keyboard", "Tổ hợp phím toàn cục cho từng lệnh dịch."),
    ("Giới thiệu", "info", "Phiên bản, cập nhật và mã nguồn."),
)

PREVIEW_SAMPLE = "Xin chào · Hello · こんにちは"

# Đổi kiểu chữ khung dịch bằng spinbox phát signal mỗi nhịp mũi tên; gom lại rồi
# mới ghi config một lần để giữ phím mũi tên/lăn chuột mượt và không đập ổ đĩa.
_STYLE_SAVE_DELAY_MS = 260


def available_hud_font_options(
    installed_families: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Giữ danh mục ngắn và chỉ hiện font phổ biến đã cài trên máy."""
    installed = installed_families
    if installed is None:
        installed = QFontDatabase.families()
    normalized = {family.casefold() for family in installed}
    available = [
        option for option in HUD_FONT_OPTIONS if option[0].casefold() in normalized
    ]
    return available or list(HUD_FONT_OPTIONS[:3])


def _link_label(url: str, text: str) -> QLabel:
    """Nhãn dạng link mở bằng trình duyệt hệ thống."""
    label = QLabel(
        f'<a href="{url}" style="color:{TOKENS["TEXT"]};'
        'text-decoration:underline;">'
        f"{text}</a>"
    )
    label.setObjectName("link")
    label.setOpenExternalLinks(True)
    label.setTextInteractionFlags(Qt.TextBrowserInteraction)
    return label


def _kbd(combo: str) -> QLabel:
    """Chip hiển thị tổ hợp phím."""
    label = QLabel(_fmt_hotkey(combo))
    label.setObjectName("kbd")
    return label


def _button_row(*buttons: QWidget) -> QWidget:
    """Hàng nút căn trái, dùng cho các khối trong thẻ."""
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for button in buttons:
        layout.addWidget(button)
    layout.addStretch(1)
    return holder


class ProviderDialog(QDialog):
    """Tạo/sửa một provider AI tùy chỉnh: tên, endpoint, API key, nhiều model."""

    def __init__(self, parent: QWidget | None = None, provider: dict | None = None):
        super().__init__(parent)
        source = provider or {}
        self.setObjectName("settingsRoot")
        self.setWindowTitle("Sửa provider" if provider else "Thêm provider tùy chỉnh")
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)
        heading = QLabel("Provider OpenAI-compatible")
        heading.setObjectName("pageTitle")
        subtitle = QLabel(
            "Bất kỳ endpoint chuẩn OpenAI nào cũng dùng được: OpenRouter, "
            "LM Studio, Ollama hoặc proxy nội bộ."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(subtitle)

        form = QFormLayout()
        form.setSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.name_edit = QLineEdit(source.get("name", ""))
        self.name_edit.setPlaceholderText("Tên hiển thị, vd: OpenRouter")
        self.endpoint_edit = QLineEdit(source.get("endpoint", ""))
        self.endpoint_edit.setPlaceholderText("http://host:port/v1")
        self.key_edit = QLineEdit(source.get("api_key", ""))
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("API key (cần để hiện model ở tab Dịch)")
        self.key_edit.setClearButtonEnabled(True)
        form.addRow("Tên", self.name_edit)
        form.addRow("Endpoint", self.endpoint_edit)
        form.addRow("API key", self.key_edit)
        layout.addLayout(form)

        models_label = QLabel("Model (thêm được nhiều)")
        models_label.setObjectName("fieldLabel")
        layout.addWidget(models_label)
        self.model_list = QListWidget()
        self.model_list.setFixedHeight(116)
        for model_id in source.get("models", []):
            self.model_list.addItem(model_id)
        layout.addWidget(self.model_list)
        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("model id, vd: gpt-4o-mini")
        self.model_input.returnPressed.connect(self._add_model)
        add_button = QPushButton("Thêm model")
        add_button.clicked.connect(self._add_model)
        remove_button = QPushButton("Xóa model")
        remove_button.setObjectName("ghost")
        remove_button.clicked.connect(self._remove_model)
        add_row.addWidget(self.model_input, 1)
        add_row.addWidget(add_button)
        add_row.addWidget(remove_button)
        layout.addLayout(add_row)

        self.error_label = QLabel("")
        self.error_label.setObjectName("muted")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Lưu")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        _enable_dark_titlebar(self)

    def _add_model(self) -> None:
        text = self.model_input.text().strip()
        if text and text not in self._models():
            self.model_list.addItem(text)
        self.model_input.clear()

    def _remove_model(self) -> None:
        for item in self.model_list.selectedItems():
            self.model_list.takeItem(self.model_list.row(item))

    def _models(self) -> list[str]:
        return [self.model_list.item(i).text() for i in range(self.model_list.count())]

    def _try_accept(self) -> None:
        if not self.name_edit.text().strip():
            self.error_label.setText("Nhập tên provider.")
            return
        endpoint = self.endpoint_edit.text().strip().rstrip("/")
        if not endpoint.startswith(("http://", "https://")):
            self.error_label.setText(
                "Endpoint phải bắt đầu bằng http:// hoặc https://."
            )
            return
        if not self._models():
            self.error_label.setText("Thêm ít nhất một model.")
            return
        self.accept()

    def data(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "endpoint": self.endpoint_edit.text().strip().rstrip("/"),
            "api_key": self.key_edit.text().strip(),
            "models": self._models(),
        }


class SettingsWindow(QWidget):
    """Chỉnh cấu hình và đồng bộ thay đổi về HUD."""

    def __init__(self, hud: "HUDWindow") -> None:
        super().__init__()
        self.hud = hud
        self.config = hud.config
        self._quitting = False
        self._model_download_running = False
        self.setObjectName("settingsRoot")
        self.setWindowTitle(f"Cài đặt — {APP_NAME}")
        self.setWindowIcon(hud.app_icon)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.resize(940, 720)
        self.setMinimumSize(820, 600)
        # Gom nhiều lần đổi kiểu chữ liền nhau thành một lần ghi config.
        self._style_save_timer = QTimer(self)
        self._style_save_timer.setSingleShot(True)
        self._style_save_timer.setInterval(_STYLE_SAVE_DELAY_MS)
        self._style_save_timer.timeout.connect(self._flush_hud_style)
        self._build_ui()
        _enable_dark_titlebar(self)

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _combo(
        options: list[tuple[str, str]], selected_code: str, on_change: Callable
    ) -> QComboBox:
        combo = QComboBox()
        for label, code in options:
            combo.addItem(label, code)
        index = combo.findData(selected_code)
        combo.setCurrentIndex(max(0, index))
        combo.currentIndexChanged.connect(on_change)
        return combo

    # -------------------------------------------------------------------- shell
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("settingsSidebar")
        sidebar.setFixedWidth(206)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 18, 12, 16)
        sidebar_layout.setSpacing(0)
        sidebar_layout.addWidget(self._build_header())
        sidebar_layout.addSpacing(22)

        self.navigation = QListWidget()
        self.navigation.setObjectName("settingsNav")
        self.navigation.setAccessibleName("Nhóm cài đặt")
        self.navigation.setIconSize(QSize(17, 17))
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.navigation.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for label, icon_kind, description in NAV_SECTIONS:
            item = QListWidgetItem(_nav_icon(icon_kind), label)
            item.setToolTip(description)
            self.navigation.addItem(item)
        navigation_height = sum(
            self.navigation.sizeHintForRow(row)
            for row in range(self.navigation.count())
        )
        self.navigation.setFixedHeight(
            navigation_height + self.navigation.frameWidth() * 2
        )
        sidebar_layout.addWidget(self.navigation)
        sidebar_layout.addStretch(1)
        sidebar_layout.addWidget(self._build_footer())

        self.pages = QStackedWidget()
        self.pages.setObjectName("settingsPages")
        for page in (
            self._build_translation_page(),
            self._build_ai_page(),
            self._build_soniox_page(),
            self._build_ocr_page(),
            self._build_hud_page(),
            self._build_hotkeys_page(),
            self._build_about_page(),
        ):
            self.pages.addWidget(page)
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)

        content = QVBoxLayout()
        content.setContentsMargins(24, 22, 22, 18)
        content.addWidget(self.pages)
        root.addWidget(sidebar)
        root.addLayout(content, 1)
        # `ocr_engine_status` nạp onnxruntime (DLL native, hàng trăm ms) — hoãn
        # sang sau khi cửa sổ đã hiện để lần bấm "Cài đặt" đầu tiên không đứng.
        QTimer.singleShot(0, self._update_engine_info)

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(2, 0, 0, 0)
        layout.setSpacing(9)
        mark = QLabel()
        mark.setPixmap(_brand_pixmap(24))
        mark.setFixedSize(24, 24)
        wordmark = QLabel(APP_NAME)
        wordmark.setObjectName("brandWordmark")
        version_tag = QLabel(APP_VERSION)
        version_tag.setObjectName("brandVersion")
        version_tag.setToolTip("Phiên bản đang chạy")
        layout.addWidget(mark)
        layout.addWidget(wordmark)
        layout.addStretch(1)
        layout.addWidget(version_tag, 0, Qt.AlignVCenter)
        return header

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        layout = QVBoxLayout(footer)
        layout.setContentsMargins(2, 0, 0, 0)
        layout.setSpacing(10)
        hint = QLabel("Thay đổi được lưu tự động.")
        hint.setObjectName("sidebarHint")
        hint.setWordWrap(True)
        close_button = QPushButton("Đóng")
        close_button.clicked.connect(self.hide)
        close_button.setCursor(Qt.PointingHandCursor)
        layout.addWidget(hint)
        layout.addWidget(close_button)
        return footer

    @staticmethod
    def _page(title: str, description: str) -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 10, 18)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        summary = QLabel(description)
        summary.setObjectName("pageSubtitle")
        summary.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(summary)
        layout.addSpacing(6)
        scroll.setWidget(body)
        return scroll, layout

    # ---------------------------------------------------------------- trang Dịch
    def _build_translation_page(self) -> QScrollArea:
        page, layout = self._page("Dịch", NAV_SECTIONS[0][2])

        service_card = Card(
            "Model & ngôn ngữ",
            "Chọn trực tiếp model đã sẵn sàng; provider chưa có API key sẽ bị ẩn.",
        )
        self.service_box = QComboBox()
        self.service_box.setAccessibleName("Model hoặc dịch vụ dịch")
        self.service_box.setToolTip(
            "Google/Bing luôn khả dụng; model AI chỉ hiện sau khi provider có API key."
        )
        self._populate_service_box()
        self.service_box.currentIndexChanged.connect(self._on_service_selected)
        self.target_box = self._combo(
            LANGUAGES, self.config.target_language, self._on_target_changed
        )
        service_card.add_row(
            "Model dịch",
            self.service_box,
            "Mỗi model là một lựa chọn riêng; cấu hình provider ở tab Dịch vụ AI.",
        )
        service_card.add_row("Ngôn ngữ đích", self.target_box)
        layout.addWidget(service_card)

        replace_combo = self.config.hotkeys.get("selected_text_replace", "")
        replace_card = Card(
            "Dịch & thay thế tại chỗ",
            "Bôi đen văn bản trong ứng dụng khác rồi dán đè bằng bản dịch.",
            trailing=_kbd(replace_combo),
        )
        self.replace_target_box = self._combo(
            LANGUAGES,
            self.config.replace_target_language,
            self._on_replace_target_changed,
        )
        replace_card.add_row(
            "Ngôn ngữ khi thay thế",
            self.replace_target_box,
            "Độc lập với “Ngôn ngữ đích” ở trên; dùng chung dịch vụ đang chọn.",
        )
        layout.addWidget(replace_card)

        clipboard_card = Card(
            "Tự dịch khi copy",
            "Bật: mỗi lần Ctrl+C, văn bản vừa copy tự dịch vào khung — "
            "không cần phím tắt riêng cho chức năng này.",
        )
        self.auto_clipboard_check = QCheckBox()
        self.auto_clipboard_check.setChecked(self.config.auto_translate_clipboard)
        self.auto_clipboard_check.setAccessibleName("Tự dịch văn bản khi copy")
        self.auto_clipboard_check.setToolTip(
            "Bật để Ctrl+C ở bất kỳ ứng dụng nào cũng tự động dịch vào khung."
        )
        self.auto_clipboard_check.toggled.connect(self._on_auto_clipboard_toggled)
        clipboard_card.add_row(
            "Tự dịch clipboard",
            self.auto_clipboard_check,
            "Ảnh copy vào clipboard không bị ảnh hưởng; chỉ xử lý văn bản.",
            control_width=0,
        )
        layout.addWidget(clipboard_card)

        layout.addStretch(1)
        return page

    def _on_auto_clipboard_toggled(self, enabled: bool) -> None:
        self.config.auto_translate_clipboard = bool(enabled)
        self.config.save()
        self.hud.sync_clipboard_auto_state()
        self.hud.set_status(
            "Đã bật tự dịch văn bản khi copy."
            if enabled
            else "Đã tắt tự dịch văn bản khi copy.",
            "ready",
        )

    # ---------------------------------------------------------- trang Dịch vụ AI
    def _build_ai_page(self) -> QScrollArea:
        page, layout = self._page("Dịch vụ AI", NAV_SECTIONS[1][2])

        self.ai_provider_state = QLabel()
        self.ai_provider_state.setObjectName("statusBadge")
        provider_card = Card(
            "Provider & API key",
            "Chỉ provider đã có API key mới hiện model trong tab Dịch.",
            trailing=self.ai_provider_state,
        )
        self.ai_provider_box = QComboBox()
        self.ai_provider_box.setAccessibleName("Provider AI cần cấu hình")
        self._populate_ai_provider_box()
        self.ai_provider_box.currentIndexChanged.connect(self._on_ai_provider_selected)
        provider_card.add_row(
            "Provider AI",
            self.ai_provider_box,
            "Chọn provider để xem API key, endpoint và model tương ứng.",
            control_width=280,
        )
        self.activate_ai_btn = QPushButton("Dùng model đã chọn")
        self.activate_ai_btn.setObjectName("primary")
        self.activate_ai_btn.clicked.connect(self._activate_ai_provider)
        self.add_provider_btn = QPushButton("Thêm provider")
        self.add_provider_btn.clicked.connect(self._add_provider)
        provider_card.add_block(
            _button_row(self.activate_ai_btn, self.add_provider_btn)
        )
        layout.addWidget(provider_card)

        self.llm_frame = Card(
            "Kết nối & model",
            "Xem kết nối, chọn model hoặc thêm model ID riêng cho provider.",
        )
        self.llm_endpoint_edit = CodeField()
        self.llm_key_edit = QLineEdit()
        self.llm_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.llm_key_edit.setPlaceholderText(
            "Nhập API key để model xuất hiện ở tab Dịch"
        )
        self.llm_key_edit.setClearButtonEnabled(True)
        self.llm_key_edit.editingFinished.connect(self._on_key_changed)
        self.llm_model_box = QComboBox()
        self.llm_model_box.currentIndexChanged.connect(self._on_model_changed)
        self.llm_registration_link = _link_label(
            LLM_REGISTRATION_URL, "Đăng ký tài khoản và lấy API key →"
        )
        self.llm_registration_link.setObjectName("llmRegistration")
        self.provider_edit_btn = QPushButton("Chỉnh sửa provider")
        self.provider_edit_btn.clicked.connect(self._edit_provider)
        self.provider_delete_btn = QPushButton("Xóa provider")
        self.provider_delete_btn.setObjectName("danger")
        self.provider_delete_btn.clicked.connect(self._delete_provider)
        self.provider_manage_widget = _button_row(
            self.provider_edit_btn, self.provider_delete_btn
        )
        self.llm_frame.add_row("Endpoint", self.llm_endpoint_edit, control_width=300)
        self.llm_frame.add_row("API key", self.llm_key_edit, control_width=300)
        self.llm_frame.add_row("Model", self.llm_model_box, control_width=300)
        self.model_id_input = QLineEdit()
        self.model_id_input.setPlaceholderText("Model ID, vd: gpt-4.1-mini")
        self.model_id_input.returnPressed.connect(self._add_ai_model)
        self.add_ai_model_btn = QPushButton("Thêm model")
        self.add_ai_model_btn.clicked.connect(self._add_ai_model)
        self.remove_ai_model_btn = QPushButton("Xóa model")
        self.remove_ai_model_btn.setObjectName("ghost")
        self.remove_ai_model_btn.clicked.connect(self._remove_ai_model)
        model_actions = QWidget()
        model_actions_layout = QHBoxLayout(model_actions)
        model_actions_layout.setContentsMargins(0, 0, 0, 0)
        model_actions_layout.setSpacing(8)
        model_actions_layout.addWidget(self.model_id_input, 1)
        model_actions_layout.addWidget(self.add_ai_model_btn)
        model_actions_layout.addWidget(self.remove_ai_model_btn)
        self.llm_frame.add_block(model_actions)
        self.llm_frame.add_block(self.llm_registration_link)
        self.llm_frame.add_block(self.provider_manage_widget)
        layout.addWidget(self.llm_frame)
        self._update_llm_controls()
        layout.addStretch(1)
        return page

    def _populate_ai_provider_box(self, selected: str | None = None) -> None:
        box = self.ai_provider_box
        current = selected or box.currentData()
        if current is None and (
            self.config.translator in BUILTIN_AI_IDS
            or self.config.translator.startswith("custom:")
        ):
            current = self.config.translator
        box.blockSignals(True)
        box.clear()
        for provider_id in BUILTIN_AI_IDS:
            box.addItem(BUILTIN_AI_BY_ID[provider_id]["name"], provider_id)
        for provider in self.config.custom_providers:
            box.addItem(provider["name"], f"custom:{provider['id']}")
        index = box.findData(current)
        box.setCurrentIndex(index if index >= 0 else 0)
        box.blockSignals(False)

    def _configured_service_entries(self) -> list[tuple[str, str]]:
        models = {
            provider_id: self.config.provider_models(provider_id)
            for provider_id in BUILTIN_AI_IDS
        }
        return bar_translator_entries(
            self.config.custom_providers,
            builtin_models=models,
            enabled_providers=self.config.configured_ai_provider_ids(),
        )

    def _populate_service_box(self) -> None:
        """Google/Bing + từng model thuộc provider đã có API key."""
        box = self.service_box
        selected = bar_service_key(self.config.translator, self.config.llm_model)
        box.blockSignals(True)
        box.clear()
        for label, key in self._configured_service_entries():
            box.addItem(label, key)
        index = box.findData(selected)
        box.setCurrentIndex(index if index >= 0 else 0)
        box.blockSignals(False)

    # --------------------------------------------------------------- trang Audio
    def _build_soniox_page(self) -> QScrollArea:
        page, layout = self._page("Audio", NAV_SECTIONS[2][2])

        self.soniox_state = QLabel()
        self.soniox_state.setObjectName("statusBadge")
        connection_card = Card(
            "Soniox realtime",
            "Stream PCM từ microphone hoặc âm thanh hệ thống; transcript và bản "
            "dịch về cùng một kết nối.",
            trailing=self.soniox_state,
        )
        self.soniox_connection_card = connection_card
        self.soniox_key_edit = QLineEdit(self.config.soniox_api_key)
        self.soniox_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.soniox_key_edit.setPlaceholderText("Nhập Soniox API key")
        self.soniox_key_edit.setClearButtonEnabled(True)
        self.soniox_key_edit.editingFinished.connect(self._on_soniox_key_changed)
        connection_card.add_row(
            "API key",
            self.soniox_key_edit,
            "Tạo tại console.soniox.com; key chỉ lưu trong file cấu hình cục bộ.",
            control_width=300,
        )
        self.soniox_source_box = self._combo(
            [
                ("Microphone", "microphone"),
                ("Âm thanh hệ thống", "system"),
            ],
            self.config.soniox_audio_source,
            self._on_soniox_source_changed,
        )
        connection_card.add_row(
            "Nguồn âm thanh",
            self.soniox_source_box,
            "Audio hệ thống dùng WASAPI loopback của thiết bị đang phát.",
            control_width=300,
        )

        self.soniox_microphone_box = self._combo(
            audio_input_options(),
            self.config.soniox_input_device,
            self._on_soniox_microphone_changed,
        )
        self.soniox_microphone_row = connection_card.add_row(
            "Microphone",
            self.soniox_microphone_box,
            "Thiết bị mặc định được tra lại mỗi khi bắt đầu phiên.",
            control_width=300,
        )
        self.soniox_system_device_box = self._combo(
            system_audio_input_options(),
            self.config.soniox_system_device,
            self._on_soniox_system_device_changed,
        )
        self.soniox_system_device_row = connection_card.add_row(
            "Thiết bị phát",
            self.soniox_system_device_box,
            "Thu toàn bộ âm thanh đang phát qua loa/tai nghe đã chọn.",
            control_width=300,
        )
        connection_card.add_block(
            _link_label("https://console.soniox.com/", "Mở Soniox Console →")
        )
        layout.addWidget(connection_card)

        translation_card = Card(
            "Dịch & phân tách người nói",
            "Model stt-rt-v5 nhận dạng ngôn ngữ, gắn nhãn speaker và dịch khi đang nói.",
        )
        self.soniox_translation_card = translation_card
        self.soniox_mode_box = self._combo(
            [("Một chiều → ngôn ngữ đích", "one_way"), ("Hai chiều A ↔ B", "two_way")],
            self.config.soniox_translation_mode,
            self._on_soniox_mode_changed,
        )
        translation_card.add_row("Chế độ", self.soniox_mode_box)
        self.soniox_target_box = self._combo(
            SONIOX_LANGUAGES,
            self.config.soniox_target_language,
            self._on_soniox_target_changed,
        )
        self.soniox_target_row = translation_card.add_row(
            "Ngôn ngữ đích",
            self.soniox_target_box,
            "Mọi ngôn ngữ được phát hiện sẽ dịch sang ngôn ngữ này.",
        )
        self.soniox_language_a_box = self._combo(
            SONIOX_LANGUAGES,
            self.config.soniox_language_a,
            self._on_soniox_language_a_changed,
        )
        self.soniox_language_a_row = translation_card.add_row(
            "Ngôn ngữ A", self.soniox_language_a_box
        )
        self.soniox_language_b_box = self._combo(
            SONIOX_LANGUAGES,
            self.config.soniox_language_b,
            self._on_soniox_language_b_changed,
        )
        self.soniox_language_b_row = translation_card.add_row(
            "Ngôn ngữ B", self.soniox_language_b_box
        )
        self.soniox_diarization_check = QCheckBox("Hiện nhãn người nói")
        self.soniox_diarization_check.setChecked(self.config.soniox_speaker_diarization)
        self.soniox_diarization_check.toggled.connect(
            self._on_soniox_diarization_changed
        )
        translation_card.add_row(
            "Nhận diện người nói",
            self.soniox_diarization_check,
            "Soniox ước lượng người nói; có thể nhầm khi giọng giống nhau hoặc nói chồng.",
        )
        layout.addWidget(translation_card)

        display_card = Card(
            "Hiển thị phụ đề",
            "Chọn lượng thông tin và cách căn transcript trong khung HUD.",
        )
        self.soniox_display_mode_box = self._combo(
            [
                ("Song ngữ · lời gốc + bản dịch", "bilingual"),
                ("Chỉ bản dịch", "translation"),
            ],
            self.config.soniox_display_mode,
            self._on_soniox_display_mode_changed,
        )
        display_card.add_row(
            "Nội dung",
            self.soniox_display_mode_box,
            "Song ngữ: lời gốc nhỏ và mờ; bản dịch lớn ở dòng bên dưới.",
            control_width=300,
        )
        self.soniox_alignment_box = self._combo(
            [("Căn trái", "left"), ("Căn giữa", "center"), ("Căn phải", "right")],
            self.config.soniox_text_alignment,
            self._on_soniox_alignment_changed,
        )
        display_card.add_row(
            "Căn lề",
            self.soniox_alignment_box,
            "Áp dụng ngay cho transcript đang hiển thị.",
            control_width=300,
        )
        layout.addWidget(display_card)

        self.soniox_toggle_button = QPushButton("Bắt đầu dịch audio")
        self.soniox_toggle_button.setObjectName("primary")
        self.soniox_toggle_button.clicked.connect(self.hud.toggle_audio_realtime)
        controls = Card(
            "Điều khiển phiên",
            "Cũng có thể bật/tắt bằng nút audio trên thanh HUD.",
        )
        controls.add_block(_button_row(self.soniox_toggle_button))
        layout.addWidget(controls)
        self._sync_soniox_source_rows()
        self._sync_soniox_mode_rows()
        self.sync_soniox_state(self.hud.audio_session.state)
        layout.addStretch(1)
        return page

    # ----------------------------------------------------------------- trang OCR
    def _build_ocr_page(self) -> QScrollArea:
        page, layout = self._page("OCR", NAV_SECTIONS[3][2])

        ocr_card = Card(
            "Nhận dạng ký tự",
            "Ảnh chụp vùng được xử lý ngay trên máy, không gửi lên dịch vụ nào.",
        )
        self.engine_box = self._combo(
            OCR_ENGINES, self.config.ocr_engine, self._on_ocr_changed
        )
        model_options = [
            (self._ocr_model_option_label(model), model.id) for model in OCR_MODELS
        ]
        self.model_box = self._combo(
            model_options, self.config.ocr_model, self._on_ocr_changed
        )
        self._refresh_ocr_model_options(self.config.ocr_model)
        self.backend_box = self._combo(
            list(OCR_BACKENDS), self.config.ocr_backend, self._on_ocr_changed
        )
        self.acceleration_check = QCheckBox()
        self.acceleration_check.setChecked(self.config.ocr_acceleration)
        self.acceleration_check.setAccessibleName("Sử dụng GPU / OpenVINO")
        self.acceleration_check.setToolTip(
            "Tắt để luôn dùng CPU. Bật để cho phép backend tăng tốc đã chọn."
        )
        self.acceleration_check.toggled.connect(self._on_ocr_changed)
        self.ocr_box = self._combo(
            OCR_LANGUAGES, self.config.ocr_language, self._on_ocr_changed
        )
        ocr_card.add_row("Engine", self.engine_box)
        ocr_card.add_row("Mô hình", self.model_box)
        ocr_card.add_row("Ngôn ngữ nguồn", self.ocr_box)
        ocr_card.add_row(
            "Tăng tốc phần cứng",
            self.acceleration_check,
            "Tắt để luôn chạy trên CPU. Đây là chế độ ổn định nhất.",
            control_width=0,
        )
        ocr_card.add_row("Backend tăng tốc", self.backend_box)
        layout.addWidget(ocr_card)

        engine_info = QFrame()
        engine_info.setObjectName("engineInfo")
        info_layout = QHBoxLayout(engine_info)
        info_layout.setContentsMargins(15, 13, 15, 13)
        info_layout.setSpacing(12)
        self.engine_badge = QLabel()
        self.engine_badge.setObjectName("engineBadge")
        self.engine_hint = QLabel()
        self.engine_hint.setObjectName("engineHint")
        self.engine_hint.setWordWrap(True)
        info_layout.addWidget(self.engine_badge, 0, Qt.AlignTop)
        info_layout.addWidget(self.engine_hint, 1)
        layout.addWidget(engine_info)

        model_meta = QFrame()
        model_meta.setObjectName("modelMeta")
        model_meta_layout = QVBoxLayout(model_meta)
        model_meta_layout.setContentsMargins(15, 13, 15, 13)
        model_meta_layout.setSpacing(7)
        self.model_title = QLabel()
        self.model_title.setObjectName("modelTitle")
        self.model_metrics = QLabel()
        self.model_metrics.setObjectName("modelMetrics")
        self.model_metrics.setWordWrap(True)
        self.model_languages = QLabel()
        self.model_languages.setObjectName("modelLanguages")
        self.model_languages.setWordWrap(True)
        self.model_download_button = QPushButton("Tải mô hình")
        self.model_download_button.clicked.connect(self._download_selected_model)
        self.model_download_status = QLabel()
        self.model_download_status.setObjectName("modelDownloadStatus")
        self.model_download_status.setWordWrap(True)
        self.model_download_status.hide()
        model_meta_layout.addWidget(self.model_title)
        model_meta_layout.addWidget(self.model_metrics)
        model_meta_layout.addWidget(self.model_languages)
        model_meta_layout.addWidget(self.model_download_status)
        model_meta_layout.addSpacing(2)
        model_meta_layout.addWidget(_button_row(self.model_download_button))
        layout.addWidget(model_meta)
        layout.addStretch(1)
        return page

    # ---------------------------------------------------------- trang Khung dịch
    def _build_hud_page(self) -> QScrollArea:
        page, layout = self._page("Khung dịch", NAV_SECTIONS[4][2])

        preview_card = Card(
            "Xem trước",
            "Nền bàn cờ chỉ minh hoạ phần trong suốt. Khi dùng thật, bạn sẽ "
            "thấy desktop phía sau.",
        )
        preview_surface = CheckerFrame()
        preview_surface.setMinimumHeight(96)
        preview_layout = QVBoxLayout(preview_surface)
        preview_layout.setContentsMargins(14, 12, 14, 12)
        self.preview_view = HudTextView()
        self.preview_view.setMinimumHeight(64)
        self.preview_view.setText(PREVIEW_SAMPLE)
        preview_layout.addWidget(self.preview_view)
        preview_card.add_block(preview_surface)
        layout.addWidget(preview_card)

        text_card = Card("Chữ")
        self.font_family_box = QComboBox()
        self.font_family_box.setAccessibleName("Font chữ cho bản dịch")
        self.font_family_box.setToolTip(
            "Chỉ hiện font phổ biến đã cài. Ký tự Unicode thiếu glyph sẽ dùng "
            "font fallback của Windows."
        )
        for family, coverage in available_hud_font_options():
            self.font_family_box.addItem(f"{family} · {coverage}", family)
            index = self.font_family_box.count() - 1
            self.font_family_box.setItemData(
                index, QFont(family), Qt.ItemDataRole.FontRole
            )
        font_index = self.font_family_box.findData(self.config.hud_font_family)
        self.font_family_box.setCurrentIndex(max(0, font_index))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 96)
        self.font_size_spin.setValue(self.config.hud_font_size)
        self.font_size_spin.setSuffix(" pt")
        self.text_color_btn = ColorButton(self.config.hud_text_color)
        text_card.add_row(
            "Font chữ",
            self.font_family_box,
            "Chọn font có glyph cho ngôn ngữ đích để tránh ô vuông.",
            control_width=240,
        )
        text_card.add_row("Cỡ chữ", self.font_size_spin, control_width=110)
        text_card.add_row("Màu chữ", self.text_color_btn, control_width=0)
        layout.addWidget(text_card)

        edge_card = Card(
            "Viền, glow & nền",
            "Viền tối giữ nét trên nền sáng; glow cyan làm chữ bật trên nền tối.",
        )
        self.border_width_spin = QDoubleSpinBox()
        self.border_width_spin.setRange(0.0, 8.0)
        self.border_width_spin.setDecimals(1)
        self.border_width_spin.setSingleStep(0.1)
        self.border_width_spin.setValue(self.config.hud_border_width)
        self.border_width_spin.setSuffix(" px")
        self.border_color_btn = ColorButton(self.config.hud_border_color)
        self.shadow_radius_spin = QDoubleSpinBox()
        self.shadow_radius_spin.setRange(0.0, 16.0)
        self.shadow_radius_spin.setDecimals(1)
        self.shadow_radius_spin.setSingleStep(0.5)
        self.shadow_radius_spin.setValue(self.config.hud_shadow_radius)
        self.shadow_radius_spin.setSuffix(" px")
        self.shadow_radius_spin.setToolTip("0 px = tắt glow chữ")
        self.shadow_color_btn = ColorButton(
            self.config.hud_shadow_color, allow_alpha=True
        )
        self.background_color_btn = ColorButton(
            self.config.hud_background_color, allow_alpha=True
        )
        self.background_enabled_check = QCheckBox()
        self.background_enabled_check.setChecked(self.config.hud_background_enabled)
        self.background_enabled_check.setAccessibleName("Bật nền khung dịch")
        self.background_color_btn.setEnabled(self.config.hud_background_enabled)
        edge_card.add_row("Độ dày viền", self.border_width_spin, control_width=110)
        edge_card.add_row("Màu viền", self.border_color_btn, control_width=0)
        edge_card.add_row(
            "Độ rộng glow",
            self.shadow_radius_spin,
            "Quầng sáng mềm quanh chữ · 0 px là tắt.",
            control_width=110,
        )
        edge_card.add_row("Màu glow", self.shadow_color_btn, control_width=0)
        edge_card.add_row(
            "Nền khung dịch",
            self.background_enabled_check,
            "Tô một lớp màu phía sau chữ để tách khỏi desktop lộn xộn.",
            control_width=0,
        )
        edge_card.add_row(
            "Màu nền",
            self.background_color_btn,
            "Chỉ áp dụng khi bật “Nền khung dịch” ở trên.",
            control_width=0,
        )
        layout.addWidget(edge_card)

        self.font_family_box.currentIndexChanged.connect(self._on_hud_style_changed)
        self.font_size_spin.valueChanged.connect(self._on_hud_style_changed)
        self.border_width_spin.valueChanged.connect(self._on_hud_style_changed)
        self.shadow_radius_spin.valueChanged.connect(self._on_hud_style_changed)
        self.background_enabled_check.toggled.connect(self._on_hud_style_changed)
        self.background_enabled_check.toggled.connect(
            self.background_color_btn.setEnabled
        )
        for button in (
            self.text_color_btn,
            self.border_color_btn,
            self.shadow_color_btn,
            self.background_color_btn,
        ):
            button.picked.connect(self._on_hud_style_changed)
            button.previewed.connect(self._preview_hud_style)

        reset_button = QPushButton("Đặt lại mặc định")
        reset_button.setObjectName("ghost")
        reset_button.setToolTip(
            "Trả về chữ trắng · viền đen mảnh · không glow; phẳng trên mọi nền."
        )
        reset_button.clicked.connect(self._reset_hud_style)
        layout.addWidget(_button_row(reset_button))
        self._sync_preview()
        layout.addStretch(1)
        return page

    # ----------------------------------------------------------- trang Phím tắt
    def _build_hotkeys_page(self) -> QScrollArea:
        page, layout = self._page("Phím tắt", NAV_SECTIONS[5][2])

        card = Card(
            "Tổ hợp phím toàn cục",
            "Bấm vào ô rồi nhấn tổ hợp phím · Del để tắt · Esc để huỷ.",
        )
        self.hotkey_edits: dict[str, HotkeyEdit] = {}
        for label, action in HOTKEY_ACTIONS:
            edit = HotkeyEdit(self.config.hotkeys.get(action, ""))
            edit.setFixedWidth(178)
            edit.changed.connect(self._mark_hotkey_conflicts)
            self.hotkey_edits[action] = edit
            card.add_row(label, edit, control_width=0)
        layout.addWidget(card)

        self.hotkey_warning = QLabel("")
        self.hotkey_warning.setObjectName("stateBadge")
        self.hotkey_warning.setProperty("state", "missing")
        self.hotkey_warning.setVisible(False)
        layout.addWidget(self.hotkey_warning)

        save_button = QPushButton("Lưu phím tắt")
        save_button.setObjectName("primary")
        save_button.clicked.connect(self._apply_hotkeys)
        reset_button = QPushButton("Đặt lại mặc định")
        reset_button.setObjectName("ghost")
        reset_button.clicked.connect(self._reset_hotkeys)
        layout.addWidget(_button_row(save_button, reset_button))
        layout.addStretch(1)
        return page

    # ---------------------------------------------------------- trang Giới thiệu
    def _build_about_page(self) -> QScrollArea:
        page, layout = self._page("Giới thiệu", NAV_SECTIONS[6][2])

        about_card = Card()
        identity = QWidget()
        identity_layout = QHBoxLayout(identity)
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.setSpacing(14)
        mark = QLabel()
        mark.setPixmap(_brand_pixmap(44))
        mark.setFixedSize(44, 44)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(3)
        name = QLabel(APP_NAME)
        name.setObjectName("cardTitle")
        version = QLabel(f"Phiên bản {APP_VERSION}")
        version.setObjectName("cardHint")
        texts.addWidget(name)
        texts.addWidget(version)
        identity_layout.addWidget(mark, 0, Qt.AlignTop)
        identity_layout.addLayout(texts, 1)
        about_card.add_block(identity)
        repo_field = CodeField(f"github.com/{GITHUB_REPO}")
        about_card.add_block(repo_field)
        layout.addWidget(about_card)

        update_card = Card("Cập nhật", "Tải và cài bản mới trực tiếp từ GitHub.")
        self.update_status_label = QLabel()
        self.update_status_label.setObjectName("engineHint")
        self.update_status_label.setWordWrap(True)
        update_card.add_block(self.update_status_label)
        self.auto_update_check = QCheckBox()
        self.auto_update_check.setChecked(self.config.auto_update)
        self.auto_update_check.toggled.connect(self._on_auto_update_toggled)
        update_card.add_row(
            "Tự kiểm tra khi mở app",
            self.auto_update_check,
            "Chỉ đọc danh sách release công khai, không gửi dữ liệu của bạn.",
            control_width=0,
        )
        self.check_update_button = QPushButton("Kiểm tra cập nhật")
        self.check_update_button.clicked.connect(self._check_updates)
        self.install_update_button = QPushButton("Cài đặt bản mới")
        self.install_update_button.setObjectName("primary")
        self.install_update_button.clicked.connect(self._install_update)
        update_card.add_block(
            _button_row(self.install_update_button, self.check_update_button)
        )
        layout.addWidget(update_card)

        layout.addWidget(
            _link_label(GITHUB_RELEASES_URL, "Xem tất cả phiên bản trên GitHub →")
        )
        layout.addStretch(1)
        self.refresh_update_state()
        return page

    # ------------------------------------------------------------------ cập nhật
    def _on_auto_update_toggled(self, checked: bool) -> None:
        self.config.auto_update = checked
        self.config.save()

    def _check_updates(self) -> None:
        controller = getattr(self.hud, "updater", None)
        if controller is not None:
            controller.check_manual()

    def _install_update(self) -> None:
        controller = getattr(self.hud, "updater", None)
        if controller is not None:
            controller.start_install()

    def refresh_update_state(self) -> None:
        """Đồng bộ nhãn/nút theo trạng thái của UpdateController (nếu đã có UI)."""
        controller = getattr(self.hud, "updater", None)
        if controller is None or not hasattr(self, "update_status_label"):
            return
        checking = controller._checking
        installing = controller._installing
        release = controller.available
        self.check_update_button.setEnabled(not (checking or installing))
        self.install_update_button.setVisible(release is not None)
        self.install_update_button.setEnabled(release is not None and not installing)
        if not self.install_update_button.isVisible():
            self.install_update_button.setText("Cài đặt bản mới")
        if installing:
            self.update_status_label.setText("Đang tải và cài đặt bản mới…")
        elif checking:
            self.update_status_label.setText("Đang kiểm tra cập nhật…")
        elif release is not None:
            self.install_update_button.setText(f"Cài đặt bản {release.version}")
            self.update_status_label.setText(
                f"Có bản cập nhật {release.version}. "
                "Nhấn nút bên dưới để tải và cài tự động."
            )
        else:
            self.update_status_label.setText(
                f"Bạn đang dùng bản mới nhất ({APP_VERSION})."
            )

    # -------------------------------------------------------------------- dịch
    def _on_target_changed(self) -> None:
        self.config.target_language = self.target_box.currentData()
        self.config.save()
        self.hud.sync_translation_controls()

    def _on_replace_target_changed(self) -> None:
        self.config.replace_target_language = self.replace_target_box.currentData()
        self.config.save()

    # -------------------------------------------------------------- Soniox
    def _on_soniox_key_changed(self) -> None:
        self.config.soniox_api_key = self.soniox_key_edit.text().strip()[:512]
        self.config.save()
        self.sync_soniox_state(self.hud.audio_session.state)

    def _on_soniox_source_changed(self) -> None:
        source = self.soniox_source_box.currentData()
        if isinstance(source, str):
            self.config.soniox_audio_source = source
            self.config.save()
        self._sync_soniox_source_rows()
        self.sync_soniox_state(self.hud.audio_session.state)
        self._sync_hud_audio_controls()

    def _sync_soniox_source_rows(self) -> None:
        system = self.soniox_source_box.currentData() == "system"
        self.soniox_connection_card.set_row_visible(
            self.soniox_microphone_row, not system
        )
        self.soniox_connection_card.set_row_visible(
            self.soniox_system_device_row, system
        )

    def _on_soniox_microphone_changed(self) -> None:
        device_id = self.soniox_microphone_box.currentData()
        self.config.soniox_input_device = (
            device_id if isinstance(device_id, str) else ""
        )
        self.config.save()

    def _on_soniox_system_device_changed(self) -> None:
        device_name = self.soniox_system_device_box.currentData()
        self.config.soniox_system_device = (
            device_name if isinstance(device_name, str) else ""
        )
        self.config.save()

    def _on_soniox_mode_changed(self) -> None:
        mode = self.soniox_mode_box.currentData()
        if isinstance(mode, str):
            self.config.soniox_translation_mode = mode
            self.config.save()
        self._sync_soniox_mode_rows()

    def _sync_soniox_mode_rows(self) -> None:
        two_way = self.soniox_mode_box.currentData() == "two_way"
        self.soniox_translation_card.set_row_visible(
            self.soniox_target_row, not two_way
        )
        self.soniox_translation_card.set_row_visible(
            self.soniox_language_a_row, two_way
        )
        self.soniox_translation_card.set_row_visible(
            self.soniox_language_b_row, two_way
        )

    def _on_soniox_target_changed(self) -> None:
        language = self.soniox_target_box.currentData()
        if isinstance(language, str):
            self.config.soniox_target_language = language
            self.config.save()
        self._sync_hud_audio_controls()

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index < 0:
            return
        combo.blockSignals(True)
        combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _on_soniox_language_a_changed(self) -> None:
        language_a = self.soniox_language_a_box.currentData()
        if not isinstance(language_a, str):
            return
        self.config.soniox_language_a = language_a
        if language_a == self.config.soniox_language_b:
            self.config.soniox_language_b = "vi" if language_a != "vi" else "en"
            self._set_combo_data(
                self.soniox_language_b_box, self.config.soniox_language_b
            )
        self.config.save()

    def _on_soniox_language_b_changed(self) -> None:
        language_b = self.soniox_language_b_box.currentData()
        if not isinstance(language_b, str):
            return
        self.config.soniox_language_b = language_b
        if language_b == self.config.soniox_language_a:
            self.config.soniox_language_a = "en" if language_b != "en" else "vi"
            self._set_combo_data(
                self.soniox_language_a_box, self.config.soniox_language_a
            )
        self.config.save()

    def _on_soniox_diarization_changed(self, enabled: bool) -> None:
        self.config.soniox_speaker_diarization = enabled
        self.config.save()

    def _on_soniox_display_mode_changed(self) -> None:
        display_mode = self.soniox_display_mode_box.currentData()
        if not isinstance(display_mode, str):
            return
        self.config.soniox_display_mode = display_mode
        self.config.save()
        self._sync_hud_audio_controls()
        self.hud.refresh_audio_transcript_display()

    def _on_soniox_alignment_changed(self) -> None:
        alignment = self.soniox_alignment_box.currentData()
        if not isinstance(alignment, str):
            return
        self.config.soniox_text_alignment = alignment
        self.config.save()
        self._sync_hud_audio_controls()
        self.hud.refresh_audio_transcript_display()

    def _sync_hud_audio_controls(self) -> None:
        sync = getattr(self.hud, "sync_audio_controls", None)
        if callable(sync):
            sync()

    def sync_soniox_controls(self) -> None:
        """Nhận thay đổi Audio mode từ HUD mà không phát signal ngược."""
        if not hasattr(self, "soniox_source_box"):
            return
        for combo, value in (
            (self.soniox_source_box, self.config.soniox_audio_source),
            (self.soniox_target_box, self.config.soniox_target_language),
            (self.soniox_display_mode_box, self.config.soniox_display_mode),
            (self.soniox_alignment_box, self.config.soniox_text_alignment),
        ):
            self._set_combo_data(combo, value)
        self._sync_soniox_source_rows()

    def sync_soniox_state(self, state: str) -> None:
        if not hasattr(self, "soniox_state"):
            return
        labels = {
            "connecting": ("Đang kết nối", "busy"),
            "listening": ("Đang nghe", "busy"),
            "stopping": ("Đang hoàn tất", "busy"),
        }
        active = state != "idle"
        configured = bool(self.config.soniox_api_key)
        text, badge_state = labels.get(
            state,
            ("Sẵn sàng", "ready") if configured else ("Thiếu API key", "missing"),
        )
        self.soniox_state.setText(text)
        self._set_badge_state(self.soniox_state, badge_state)
        self.soniox_toggle_button.setText(
            "Dừng phiên realtime" if active else "Bắt đầu dịch audio"
        )
        self.soniox_toggle_button.setEnabled(active or configured)

    @staticmethod
    def _set_badge_state(badge: QLabel, state: str) -> None:
        """Đổi màu badge qua property `state`; bỏ qua khi không đổi."""
        if badge.property("state") == state:
            return
        badge.setProperty("state", state)
        badge.style().unpolish(badge)
        badge.style().polish(badge)

    def _on_service_selected(self) -> None:
        key = self.service_box.currentData()
        if not isinstance(key, str):
            return
        translator, model = parse_bar_service_key(key)
        self.config.translator = translator
        if model is not None:
            self.config.llm_model = model
        self.config.save()
        if translator in BUILTIN_AI_IDS or translator.startswith("custom:"):
            self.ai_provider_box.blockSignals(True)
            index = self.ai_provider_box.findData(translator)
            self.ai_provider_box.setCurrentIndex(max(0, index))
            self.ai_provider_box.blockSignals(False)
            self._update_llm_controls(model)
        else:
            self._sync_ai_state()
        self.hud.sync_translation_controls()
        self.hud.set_status("Đã cập nhật model dịch.", "ready")

    def _selected_ai_code(self) -> str:
        data = self.ai_provider_box.currentData()
        return data if isinstance(data, str) else BUILTIN_AI_IDS[0]

    def _custom_provider(self, code: str) -> dict | None:
        if not code.startswith("custom:"):
            return None
        provider_id = code.split(":", 1)[1]
        return next(
            (
                provider
                for provider in self.config.custom_providers
                if provider["id"] == provider_id
            ),
            None,
        )

    def _on_ai_provider_selected(self) -> None:
        self._update_llm_controls()

    def _activate_ai_provider(self) -> None:
        code = self._selected_ai_code()
        if not self.config.ai_provider_configured(code):
            self.hud.set_status("Nhập API key trước khi dùng provider này.", "error")
            return
        self.config.translator = code
        model = self.llm_model_box.currentData()
        if isinstance(model, str):
            self.config.llm_model = model
        self.config.save()
        self._populate_service_box()
        self._sync_ai_state()
        self._notify_service_entries_changed()
        self.hud.set_status("Đã chuyển sang model AI đã chọn.", "ok")

    def _on_key_changed(self) -> None:
        code = self._selected_ai_code()
        if code not in BUILTIN_AI_IDS:
            return
        key = self.llm_key_edit.text().strip()
        self.config.set_provider_api_key(code, key)
        if not key and self.config.translator == code:
            self.config.translator = "google"
        self.config.save()
        self._populate_service_box()
        self._sync_ai_state()
        self._notify_service_entries_changed()

    def _on_model_changed(self) -> None:
        model = self.llm_model_box.currentData()
        if model is None or self._selected_ai_code() != self.config.translator:
            self._update_model_remove_state()
            return
        self.config.llm_model = model
        self.config.save()
        self._populate_service_box()
        self._update_model_remove_state()
        self.hud.sync_translation_controls()

    def _add_ai_model(self) -> None:
        model_id = self.model_id_input.text().strip()
        if not model_id:
            return
        code = self._selected_ai_code()
        if model_id in self.config.provider_models(code):
            self.hud.set_status("Model này đã có trong provider.", "ready")
            return
        if code in BUILTIN_AI_IDS:
            self.config.ai_models.setdefault(code, []).append(model_id)
        else:
            provider = self._custom_provider(code)
            if provider is None:
                return
            provider["models"].append(model_id)
        if self.config.translator == code:
            self.config.llm_model = model_id
        self.config.save()
        self.model_id_input.clear()
        self._refresh_model_choices(model_id)
        self.hud.set_status(f"Đã thêm model “{model_id}”.", "ok")

    def _remove_ai_model(self) -> None:
        code = self._selected_ai_code()
        model_id = self.llm_model_box.currentData()
        if not isinstance(model_id, str):
            return
        if code in BUILTIN_AI_IDS:
            extras = self.config.ai_models.get(code, [])
            if model_id not in extras:
                self.hud.set_status("Model tích hợp không thể xóa.", "error")
                return
            extras.remove(model_id)
            if not extras:
                self.config.ai_models.pop(code, None)
        else:
            provider = self._custom_provider(code)
            if provider is None or len(provider["models"]) <= 1:
                self.hud.set_status("Provider phải còn ít nhất một model.", "error")
                return
            provider["models"].remove(model_id)
        models = self.config.provider_models(code)
        replacement = models[0] if models else ""
        if self.config.translator == code and self.config.llm_model == model_id:
            self.config.llm_model = replacement
        self.config.save()
        self._refresh_model_choices(replacement)
        self.hud.set_status(f"Đã xóa model “{model_id}”.", "ready")

    def _refresh_model_choices(self, preferred_model: str | None = None) -> None:
        self._populate_service_box()
        self._update_llm_controls(preferred_model)
        self._notify_service_entries_changed()

    def _notify_service_entries_changed(self) -> None:
        if hasattr(self.hud, "rebuild_service_combo"):
            self.hud.rebuild_service_combo()
        else:
            self.hud.sync_translation_controls()

    def _sync_ai_state(self) -> None:
        code = self._selected_ai_code()
        configured = self.config.ai_provider_configured(code)
        active = configured and code == self.config.translator
        if active:
            label = "Đang dùng"
        elif configured:
            label = "Sẵn sàng"
        else:
            label = "Chưa có API key"
        self.ai_provider_state.setText(label)
        self._set_badge_state(
            self.ai_provider_state, "active" if active else "inactive"
        )
        self.activate_ai_btn.setEnabled(configured and not active)
        if active:
            button_text = "Đang sử dụng"
        elif configured:
            button_text = "Dùng model đã chọn"
        else:
            button_text = "Nhập API key để dùng"
        self.activate_ai_btn.setText(button_text)

    def _update_model_remove_state(self) -> None:
        code = self._selected_ai_code()
        model_id = self.llm_model_box.currentData()
        if code in BUILTIN_AI_IDS:
            removable = model_id in self.config.ai_models.get(code, [])
        else:
            provider = self._custom_provider(code)
            removable = bool(provider and len(provider["models"]) > 1)
        self.remove_ai_model_btn.setEnabled(removable)

    def _update_llm_controls(self, preferred_model: str | None = None) -> None:
        code = self._selected_ai_code()
        is_builtin = code in BUILTIN_AI_IDS
        self.llm_model_box.blockSignals(True)
        self.llm_model_box.clear()
        if is_builtin:
            spec = BUILTIN_AI_BY_ID[code]
            labels = {model_id: label for label, model_id in spec["models"]}
            for model_id in self.config.provider_models(code):
                self.llm_model_box.addItem(labels.get(model_id, model_id), model_id)
            self.llm_endpoint_edit.setText(spec["endpoint"])
            self.llm_key_edit.setReadOnly(False)
            self.llm_key_edit.setText(self.config.provider_api_key(code))
            self.llm_registration_link.setText(
                f'<a href="{spec["register"]}" '
                f'style="color:{TOKENS["TEXT"]};text-decoration:underline;">'
                "Đăng ký tài khoản và lấy API key →</a>"
            )
            self.llm_registration_link.setVisible(True)
            self.provider_manage_widget.setVisible(False)
        else:
            provider = self._custom_provider(code) or {
                "endpoint": "",
                "api_key": "",
                "models": [],
            }
            for model_id in provider["models"]:
                self.llm_model_box.addItem(model_id, model_id)
            self.llm_endpoint_edit.setText(provider["endpoint"])
            self.llm_key_edit.setReadOnly(True)
            self.llm_key_edit.setText(provider["api_key"])
            self.llm_registration_link.setVisible(False)
            self.provider_manage_widget.setVisible(True)
        selected = preferred_model or self.config.llm_model
        model_index = self.llm_model_box.findData(selected)
        self.llm_model_box.setCurrentIndex(max(0, model_index))
        self.llm_model_box.blockSignals(False)
        self._update_model_remove_state()
        self._sync_ai_state()

    def sync_service_controls(self) -> None:
        """Đồng bộ model đang dùng và trang quản lý AI theo config."""
        self._populate_service_box()
        if (
            self.config.translator in BUILTIN_AI_IDS
            or self.config.translator.startswith("custom:")
        ):
            self.ai_provider_box.blockSignals(True)
            index = self.ai_provider_box.findData(self.config.translator)
            self.ai_provider_box.setCurrentIndex(max(0, index))
            self.ai_provider_box.blockSignals(False)
        self._update_llm_controls()

    def _next_provider_id(self) -> str:
        numbers = [
            int(provider["id"][2:])
            for provider in self.config.custom_providers
            if provider["id"].startswith("cp") and provider["id"][2:].isdigit()
        ]
        return f"cp{(max(numbers) + 1) if numbers else 1}"

    def _add_provider(self) -> None:
        dialog = ProviderDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.data()
            provider = {"id": self._next_provider_id(), **data}
            code = f"custom:{provider['id']}"
            self.config.custom_providers = self.config.custom_providers + [provider]
            if data["api_key"]:
                self.config.translator = code
                self.config.llm_model = data["models"][0]
            self.config.save()
            self._refresh_providers(
                f"Đã thêm provider “{data['name']}”.", selected=code
            )
        else:
            self._update_llm_controls()

    def _edit_provider(self) -> None:
        code = self._selected_ai_code()
        provider = self._custom_provider(code)
        if provider is None:
            return
        dialog = ProviderDialog(self, provider)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            provider.update(dialog.data())
            if code == self.config.translator:
                if not provider["api_key"]:
                    self.config.translator = "google"
                elif self.config.llm_model not in provider["models"]:
                    self.config.llm_model = provider["models"][0]
            self.config.save()
            self._refresh_providers(f"Đã cập nhật “{provider['name']}”.", selected=code)

    def _delete_provider(self) -> None:
        code = self._selected_ai_code()
        provider = self._custom_provider(code)
        if provider is None:
            return
        confirm = QMessageBox.question(
            self, "Xóa provider", f"Xóa provider “{provider['name']}”?"
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.config.custom_providers = [
            item
            for item in self.config.custom_providers
            if item["id"] != provider["id"]
        ]
        if self.config.translator == code:
            self.config.translator = "google"
        self.config.save()
        self._refresh_providers(
            f"Đã xóa “{provider['name']}”.", selected=BUILTIN_AI_IDS[0]
        )

    def _refresh_providers(self, message: str, selected: str | None = None) -> None:
        self._populate_service_box()
        self._populate_ai_provider_box(selected)
        self._update_llm_controls()
        self._notify_service_entries_changed()
        self.hud.set_status(message, "ready")

    # --------------------------------------------------------------------- OCR
    @staticmethod
    def _ocr_model_option_label(model) -> str:
        if model_installed(model.id):
            status = "Tích hợp" if model.builtin else "Đã tải"
            return f"✓ {model.label} · {status}"
        return f"↓ {model.label} · Chưa tải · {model.size_mb:g} MB"

    def _refresh_ocr_model_options(self, selected: str | None = None) -> None:
        """Cập nhật dấu đã tải trong dropdown mà không phát tín hiệu đổi model."""
        selected = selected or self.model_box.currentData() or self.config.ocr_model
        self.model_box.blockSignals(True)
        self.model_box.clear()
        for model in OCR_MODELS:
            installed = model_installed(model.id)
            self.model_box.addItem(self._ocr_model_option_label(model), model.id)
            index = self.model_box.count() - 1
            tooltip = (
                "Mô hình đã có trên máy và có thể dùng ngay."
                if installed
                else f"Chưa tải về máy · dung lượng khoảng {model.size_mb:g} MB."
            )
            self.model_box.setItemData(index, tooltip, Qt.ItemDataRole.ToolTipRole)
        index = self.model_box.findData(selected)
        self.model_box.setCurrentIndex(index if index >= 0 else 0)
        self.model_box.blockSignals(False)

    def _set_model_download_status(self, text: str = "", state: str = "") -> None:
        self.model_download_status.setText(text)
        self.model_download_status.setProperty("state", state)
        self.model_download_status.setVisible(bool(text))
        self.model_download_status.style().unpolish(self.model_download_status)
        self.model_download_status.style().polish(self.model_download_status)

    @staticmethod
    def _friendly_model_download_error(message: str) -> str:
        """Đổi lỗi thư viện thành nguyên nhân và hướng khắc phục dễ hiểu."""
        lowered = message.casefold()
        if "unsupported" in lowered or "not support" in lowered:
            return (
                "Mô hình này không tương thích với phiên bản RapidOCR đang dùng. "
                "Hãy cập nhật ứng dụng hoặc chọn một mô hình khác."
            )
        if "checksum" in lowered or "sha256" in lowered:
            return "Tệp tải về bị lỗi kiểm tra toàn vẹn. Hãy kiểm tra mạng rồi tải lại."
        if any(
            token in lowered
            for token in ("timed out", "timeout", "connection", "network", "urlopen")
        ):
            return "Không kết nối được máy chủ model. Hãy kiểm tra mạng rồi tải lại."
        if "permission" in lowered or "access is denied" in lowered:
            return (
                "Ứng dụng không có quyền ghi model vào thư mục dữ liệu. "
                "Hãy kiểm tra quyền thư mục rồi thử lại."
            )
        return f"Tải model thất bại. Chi tiết: {message}"

    def _on_ocr_changed(self) -> None:
        if not self._model_download_running:
            self._set_model_download_status()
        self.config.ocr_engine = self.engine_box.currentData()
        self.config.ocr_model = self.model_box.currentData()
        self.config.ocr_backend = self.backend_box.currentData()
        self.config.ocr_acceleration = self.acceleration_check.isChecked()
        self.config.ocr_language = self.ocr_box.currentData()
        self.config.save()
        self._update_engine_info()
        self.hud.set_status("Đã cập nhật cấu hình OCR.", "ready")

    def _update_engine_info(self) -> None:
        engine = self.engine_box.currentData()
        model_id = self.model_box.currentData()
        backend = self._effective_backend()
        available, detail = services.ocr_engine_status(engine, model_id, backend)
        if engine == "auto":
            badge, state = "Tự động", "fallback"
        elif engine == "rapidocr" and not model_installed(model_id):
            badge, state = "Cần tải", "missing"
        elif available:
            badge, state = "Sẵn sàng", "ready"
        else:
            badge, state = "Cần cài", "missing"
        self.engine_badge.setText(badge)
        self._set_badge_state(self.engine_badge, state)
        description = OCR_ENGINE_DESCRIPTIONS.get(engine, "")
        self.engine_hint.setText(f"{description}\n{detail}" if detail else description)
        self._update_model_card(engine, model_id, backend)

    def _effective_backend(self) -> str:
        if not self.acceleration_check.isChecked():
            return "cpu"
        return self.backend_box.currentData()

    def _update_model_card(self, engine: str, model_id: str, backend: str) -> None:
        model = model_spec(model_id)
        installed = model_installed(model_id)
        _backend_ready, backend_detail = backend_status(backend)
        uses_offline_model = engine != "windows"
        if not self._model_download_running:
            self.model_box.setEnabled(uses_offline_model)
            self.acceleration_check.setEnabled(uses_offline_model)
            self.backend_box.setEnabled(
                uses_offline_model and self.acceleration_check.isChecked()
            )
        if not installed:
            model_state = "Chưa tải"
        else:
            model_state = "Đã tích hợp" if model.builtin else "Đã tải"
        self.model_title.setText(f"{model.label}  ·  {model_state}")
        self.model_metrics.setText(
            f"Detection Hmean {model.detection_hmean:.1f}%  ·  "
            f"Recognition {model.recognition_accuracy:g}%  ·  {model.size_mb:g} MB"
        )
        resolved_backend = backend_label(backend)
        if not self.acceleration_check.isChecked():
            backend_detail = f"{backend_detail} Tăng tốc phần cứng đang tắt."
        self.model_languages.setText(
            f"Hỗ trợ: {model.languages}\n"
            f"Thiết bị: {resolved_backend} · {backend_detail}"
        )
        show_download = uses_offline_model
        self.model_download_button.setVisible(show_download)
        self.model_download_button.setEnabled(
            show_download and not installed and not self._model_download_running
        )
        if self._model_download_running:
            button_text = "Đang tải và kiểm tra…"
        elif installed:
            button_text = (
                "✓ Đã tích hợp và sẵn sàng" if model.builtin else "✓ Đã tải và sẵn sàng"
            )
        else:
            button_text = f"Tải mô hình · {model.size_mb:g} MB"
        self.model_download_button.setText(button_text)

    def _download_selected_model(self) -> None:
        if self._model_download_running:
            return
        model_id = self.model_box.currentData()
        self._model_download_running = True
        self._set_model_download_status(
            f"Đang tải {model_spec(model_id).label} và kiểm tra tệp…", "busy"
        )
        self._update_engine_info()
        self.hud.set_status("Đang tải mô hình OCR…", "busy")

        def worker() -> None:
            try:
                # Model ONNX dùng chung giữa CPU/GPU/OpenVINO; dùng CPU để tải
                # không phụ thuộc backend người dùng đang cấu hình.
                download_model(model_id, "cpu")
                self.hud.bridge.run.emit(
                    lambda: self._finish_model_download(model_id, None)
                )
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                self.hud.bridge.run.emit(
                    lambda: self._finish_model_download(model_id, message)
                )

        threading.Thread(target=worker, daemon=True).start()

    def _finish_model_download(self, model_id: str, error_message: str | None) -> None:
        self._model_download_running = False
        self._refresh_ocr_model_options(model_id)
        self._update_engine_info()
        if error_message:
            friendly_error = self._friendly_model_download_error(error_message)
            self._set_model_download_status(
                f"Không tải được {model_spec(model_id).label}. {friendly_error}",
                "error",
            )
            self.hud.set_status(
                f"Không tải được {model_spec(model_id).label}. {friendly_error}",
                "error",
            )
        else:
            self._set_model_download_status(
                f"✓ {model_spec(model_id).label} đã tải xong và có thể dùng ngay.",
                "ready",
            )
            self.hud.set_status(f"Đã cài {model_spec(model_id).label}.", "ok")

    # ------------------------------------------------------------- khung dịch
    def _hud_style_values(
        self,
    ) -> tuple[str, int, str, float, str, str, float, str, bool]:
        return (
            self.font_family_box.currentData(),
            self.font_size_spin.value(),
            self.text_color_btn.color_hex(),
            self.border_width_spin.value(),
            self.border_color_btn.color_hex(),
            self.background_color_btn.color_value(),
            self.shadow_radius_spin.value(),
            self.shadow_color_btn.color_value(),
            self.background_enabled_check.isChecked(),
        )

    def _sync_preview(self) -> None:
        if hasattr(self, "preview_view"):
            values = list(self._hud_style_values())
            # Nút "trong suốt" thắng cài đặt nền, kể cả trong bản xem trước.
            values[-1] = values[-1] and not self.config.hud_frame_transparent
            self.preview_view.apply_style(*values)

    def sync_frame_transparent_state(self) -> None:
        """Cập nhật xem trước sau khi bật/tắt nhanh từ nút trên bar."""
        self._sync_preview()

    def _on_hud_style_changed(self) -> None:
        """Áp dụng ngay lên UI; việc ghi config để timer gom lại.

        Spinbox cỡ chữ/độ dày viền/glow phát signal mỗi nhịp mũi tên, nên ghi đĩa
        ngay tại đây sẽ thành hàng chục lần `json.dumps` + ghi file khi người dùng
        chỉ giữ phím mũi tên.
        """
        (
            self.config.hud_font_family,
            self.config.hud_font_size,
            self.config.hud_text_color,
            self.config.hud_border_width,
            self.config.hud_border_color,
            self.config.hud_background_color,
            self.config.hud_shadow_radius,
            self.config.hud_shadow_color,
            self.config.hud_background_enabled,
        ) = self._hud_style_values()
        self.hud.apply_hud_text_style()
        self._sync_preview()
        self._sync_bar_background_toggle()
        self._style_save_timer.start()

    def _flush_hud_style(self) -> None:
        self.config.save()

    def _sync_bar_background_toggle(self) -> None:
        """Đồng bộ nút bật/tắt nền trên thanh HUD sau khi đổi ở Cài đặt."""
        button = self.hud.background_toggle_button
        if button.isChecked() == self.config.hud_background_enabled:
            return
        button.blockSignals(True)
        button.setChecked(self.config.hud_background_enabled)
        button.blockSignals(False)
        self.hud._sync_background_toggle_tooltip()

    def sync_hud_background_toggle(self) -> None:
        """Đồng bộ checkbox Cài đặt sau khi bật/tắt nhanh từ nút trên bar."""
        self.background_enabled_check.blockSignals(True)
        self.background_enabled_check.setChecked(self.config.hud_background_enabled)
        self.background_enabled_check.blockSignals(False)
        self.background_color_btn.setEnabled(self.config.hud_background_enabled)
        self._sync_preview()

    def _preview_hud_style(self) -> None:
        self.hud.preview_hud_text_style(*self._hud_style_values())
        self._sync_preview()

    def _reset_hud_style(self) -> None:
        """Trả kiểu chữ khung dịch về bộ mặc định dễ đọc trên mọi nền."""
        defaults = HUD_STYLE_DEFAULTS
        controls = (
            self.font_family_box,
            self.font_size_spin,
            self.border_width_spin,
            self.shadow_radius_spin,
            self.background_enabled_check,
        )
        for control in controls:
            control.blockSignals(True)
        family_index = self.font_family_box.findData(defaults["hud_font_family"])
        if family_index >= 0:
            self.font_family_box.setCurrentIndex(family_index)
        self.font_size_spin.setValue(defaults["hud_font_size"])
        self.border_width_spin.setValue(defaults["hud_border_width"])
        self.shadow_radius_spin.setValue(defaults["hud_shadow_radius"])
        self.background_enabled_check.setChecked(defaults["hud_background_enabled"])
        for control in controls:
            control.blockSignals(False)
        self.background_color_btn.setEnabled(defaults["hud_background_enabled"])
        self.text_color_btn.set_color(defaults["hud_text_color"])
        self.border_color_btn.set_color(defaults["hud_border_color"])
        self.shadow_color_btn.set_color(defaults["hud_shadow_color"])
        self.background_color_btn.set_color(defaults["hud_background_color"])
        self._on_hud_style_changed()
        self.hud.set_status("Đã đặt lại kiểu chữ khung dịch về mặc định.", "ok")

    # ---------------------------------------------------------------- phím tắt
    def _duplicate_combos(self) -> set[str]:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for edit in self.hotkey_edits.values():
            combo = edit.combo()
            if not combo:
                continue
            if combo in seen:
                duplicates.add(combo)
            seen.add(combo)
        return duplicates

    def _mark_hotkey_conflicts(self) -> bool:
        """Tô đỏ các ô trùng nhau ngay khi ghi phím, trước lúc bấm Lưu."""
        duplicates = self._duplicate_combos()
        for edit in self.hotkey_edits.values():
            edit.set_conflict(bool(edit.combo()) and edit.combo() in duplicates)
        if hasattr(self, "hotkey_warning"):
            self.hotkey_warning.setVisible(bool(duplicates))
            if duplicates:
                pretty = " · ".join(sorted(_fmt_hotkey(c) for c in duplicates))
                self.hotkey_warning.setText(f"Trùng phím: {pretty}")
        return bool(duplicates)

    def _reset_hotkeys(self) -> None:
        for action, edit in self.hotkey_edits.items():
            edit.set_combo(DEFAULT_HOTKEYS.get(action, ""))
        self._mark_hotkey_conflicts()
        self.hud.set_status("Đã nạp phím tắt mặc định. Bấm Lưu để áp dụng.", "ready")

    def _apply_hotkeys(self) -> None:
        if self._mark_hotkey_conflicts():
            self.hud.set_status("Phím tắt bị trùng.", "error")
            return
        mapping = {action: edit.combo() for action, edit in self.hotkey_edits.items()}
        error = self.hud.hotkeys.apply(mapping)
        if error:
            self.hud.set_status(error, "error")
            return
        self.config.hotkeys = mapping
        self.config.save()
        self.hud.refresh_bar_tooltips()
        self.hud.set_status("Đã lưu phím tắt.", "ok")

    # ------------------------------------------------------------------ vòng đời
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def hideEvent(self, event) -> None:
        # Đóng cửa sổ giữa lúc timer debounce đang chờ thì vẫn phải ghi config.
        if self._style_save_timer.isActive():
            self._style_save_timer.stop()
            self._flush_hud_style()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        if self._style_save_timer.isActive():
            self._style_save_timer.stop()
            self._flush_hud_style()
        if self._quitting:
            event.accept()
        else:
            event.ignore()
            self.hide()
