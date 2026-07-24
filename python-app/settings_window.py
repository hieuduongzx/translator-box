"""Cửa sổ cấu hình ứng dụng."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import Qt
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
from constants import (
    ADD_PROVIDER_KEY,
    BUILTIN_AI_BY_ID,
    BUILTIN_AI_IDS,
    BUILTIN_AI_MODEL_IDS,
    HOTKEY_ACTIONS,
    HUD_FONT_OPTIONS,
    LANGUAGES,
    LLM_MODELS,
    LLM_REGISTRATION_URL,
    OCR_ENGINE_DESCRIPTIONS,
    OCR_ENGINES,
    OCR_LANGUAGES,
    TRANSLATORS,
)
from ui_utils import _enable_dark_titlebar, _fmt_hotkey, _render_icon_pixmap
from version import APP_NAME, APP_VERSION, GITHUB_RELEASES_URL, GITHUB_REPO
from widgets import ColorButton, HotkeyEdit

if TYPE_CHECKING:
    from hud_window import HUDWindow


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


class ProviderDialog(QDialog):
    """Tạo/sửa một provider AI tùy chỉnh: tên, endpoint, API key, nhiều model."""

    def __init__(self, parent: QWidget | None = None, provider: dict | None = None):
        super().__init__(parent)
        source = provider or {}
        self.setObjectName("settingsRoot")
        self.setWindowTitle("Sửa provider" if provider else "Thêm provider tùy chỉnh")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        form = QFormLayout()
        form.setSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.name_edit = QLineEdit(source.get("name", ""))
        self.name_edit.setPlaceholderText("Tên hiển thị, vd: OpenRouter")
        self.endpoint_edit = QLineEdit(source.get("endpoint", ""))
        self.endpoint_edit.setPlaceholderText("http://host:port/v1")
        self.key_edit = QLineEdit(source.get("api_key", ""))
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("API key (tùy chọn)")
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
            self.error_label.setText("Endpoint phải bắt đầu bằng http:// hoặc https://.")
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
        self.resize(820, 700)
        self.setMinimumSize(700, 560)
        self._build_ui()
        _enable_dark_titlebar(self)

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

    @staticmethod
    def _surface() -> tuple[QFrame, QFormLayout]:
        frame = QFrame()
        frame.setObjectName("surface")
        form = QFormLayout(frame)
        form.setContentsMargins(14, 12, 14, 12)
        form.setSpacing(12)
        form.setHorizontalSpacing(16)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        return frame, form

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        header.setContentsMargins(22, 18, 22, 12)
        header.setSpacing(10)
        mark = QLabel()
        mark.setPixmap(_render_icon_pixmap(26))
        mark.setFixedSize(26, 26)
        wordmark = QLabel(APP_NAME)
        wordmark.setObjectName("brandWordmark")
        version_tag = QLabel(APP_VERSION)
        version_tag.setObjectName("brandVersion")
        header.addWidget(mark)
        header.addWidget(wordmark)
        header.addWidget(version_tag)
        header.addStretch(1)
        root.addLayout(header)

        content = QHBoxLayout()
        content.setContentsMargins(14, 4, 14, 14)
        content.setSpacing(14)

        self.navigation = QListWidget()
        self.navigation.setObjectName("settingsNav")
        self.navigation.setFixedWidth(168)
        self.navigation.setAccessibleName("Nhóm cài đặt")
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.navigation.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for label in ("Dịch", "OCR", "Khung dịch", "Phím tắt", "Giới thiệu"):
            self.navigation.addItem(label)

        self.pages = QStackedWidget()
        self.pages.setObjectName("settingsPages")
        for page in (
            self._build_translation_page(),
            self._build_ocr_page(),
            self._build_hud_page(),
            self._build_hotkeys_page(),
            self._build_about_page(),
        ):
            self.pages.addWidget(page)
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)

        content.addWidget(self.navigation)
        content.addWidget(self.pages, 1)
        root.addLayout(content, 1)
        self._update_engine_info()

    @staticmethod
    def _page(title: str, description: str) -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setObjectName("settingsPage")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 4, 8, 12)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("tabTitle")
        summary = QLabel(description)
        summary.setObjectName("tabDescription")
        summary.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(summary)
        layout.addSpacing(4)
        scroll.setWidget(body)
        return scroll, layout

    def _build_translation_page(self) -> QScrollArea:
        page, layout = self._page(
            "Dịch",
            "Chọn dịch vụ và ngôn ngữ nhận kết quả.",
        )
        translate_frame, translate_form = self._surface()
        self.service_box = QComboBox()
        self.service_box.setToolTip(
            "Google/Bing dịch nhanh; Translator Box và provider tùy chỉnh dùng AI."
        )
        self._populate_service_box()
        self.service_box.currentIndexChanged.connect(self._on_service_selected)
        self.target_box = self._combo(
            LANGUAGES, self.config.target_language, self._on_target_changed
        )
        translate_form.addRow("Dịch vụ", self.service_box)
        translate_form.addRow("Ngôn ngữ đích", self.target_box)
        layout.addWidget(translate_frame)

        replace_hotkey = _fmt_hotkey(self.config.hotkeys.get("selected_text_replace", ""))
        replace_heading = QLabel(f"Dịch & thay thế tại chỗ ({replace_hotkey})")
        replace_heading.setObjectName("fieldLabel")
        layout.addWidget(replace_heading)
        replace_frame, replace_form = self._surface()
        self.replace_target_box = self._combo(
            LANGUAGES,
            self.config.replace_target_language,
            self._on_replace_target_changed,
        )
        replace_hint = QLabel(
            "Ngôn ngữ đích riêng khi bôi đen rồi thay thế văn bản — độc lập với "
            "“Ngôn ngữ đích” ở trên. Dùng chung dịch vụ/provider đang chọn."
        )
        replace_hint.setObjectName("engineHint")
        replace_hint.setWordWrap(True)
        replace_form.addRow("Ngôn ngữ khi thay thế", self.replace_target_box)
        replace_form.addRow("", replace_hint)
        layout.addWidget(replace_frame)

        self.llm_frame, llm_form = self._surface()
        self.llm_endpoint_edit = QLineEdit(self.config.llm_endpoint)
        self.llm_endpoint_edit.setReadOnly(True)
        self.llm_key_edit = QLineEdit(self.config.llm_api_key)
        self.llm_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.llm_key_edit.setPlaceholderText("Nhập API key sau khi đăng ký")
        self.llm_key_edit.setClearButtonEnabled(True)
        self.llm_key_edit.editingFinished.connect(self._on_key_changed)
        self.llm_model_box = QComboBox()
        for label, model_id in LLM_MODELS:
            self.llm_model_box.addItem(label, model_id)
        model_index = self.llm_model_box.findData(self.config.llm_model)
        self.llm_model_box.setCurrentIndex(max(0, model_index))
        self.llm_model_box.currentIndexChanged.connect(self._on_model_changed)
        self.llm_registration_link = QLabel(
            f'<a href="{LLM_REGISTRATION_URL}">'
            '<span style="color:#a5b4fc;">'
            "Đăng ký tài khoản và lấy API key</span></a>"
        )
        self.llm_registration_link.setObjectName("llmRegistration")
        self.llm_registration_link.setOpenExternalLinks(True)
        self.llm_registration_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        manage_row = QHBoxLayout()
        manage_row.setContentsMargins(0, 0, 0, 0)
        manage_row.setSpacing(8)
        self.provider_edit_btn = QPushButton("Chỉnh sửa provider")
        self.provider_edit_btn.clicked.connect(self._edit_provider)
        self.provider_delete_btn = QPushButton("Xóa provider")
        self.provider_delete_btn.clicked.connect(self._delete_provider)
        manage_row.addWidget(self.provider_edit_btn)
        manage_row.addWidget(self.provider_delete_btn)
        manage_row.addStretch(1)
        self.provider_manage_widget = QWidget()
        self.provider_manage_widget.setLayout(manage_row)
        llm_form.addRow("Endpoint", self.llm_endpoint_edit)
        llm_form.addRow("API key", self.llm_key_edit)
        llm_form.addRow("Model", self.llm_model_box)
        llm_form.addRow("", self.llm_registration_link)
        llm_form.addRow("", self.provider_manage_widget)
        layout.addWidget(self.llm_frame)
        self._update_llm_controls()
        layout.addStretch(1)
        return page

    def _populate_service_box(self) -> None:
        """Google/Bing/Translator Box + provider tùy chỉnh + mục thêm mới."""
        box = self.service_box
        box.blockSignals(True)
        box.clear()
        for label, code in TRANSLATORS:
            box.addItem(label, code)
        for provider in self.config.custom_providers:
            box.addItem(provider["name"], f"custom:{provider['id']}")
        box.addItem("＋ Thêm provider tùy chỉnh…", ADD_PROVIDER_KEY)
        index = box.findData(self.config.translator)
        box.setCurrentIndex(max(0, index))
        box.blockSignals(False)

    def _build_ocr_page(self) -> QScrollArea:
        page, layout = self._page(
            "OCR",
            "Chọn engine, mô hình và thiết bị xử lý nhận dạng ngoại tuyến.",
        )
        ocr_frame, ocr_form = self._surface()
        self.engine_box = self._combo(
            OCR_ENGINES, self.config.ocr_engine, self._on_ocr_changed
        )
        model_options = [
            (
                f"{model.label}{' · tích hợp' if model.builtin else ''}",
                model.id,
            )
            for model in OCR_MODELS
        ]
        self.model_box = self._combo(
            model_options, self.config.ocr_model, self._on_ocr_changed
        )
        self.backend_box = self._combo(
            list(OCR_BACKENDS), self.config.ocr_backend, self._on_ocr_changed
        )
        self.acceleration_check = QCheckBox("Sử dụng GPU / OpenVINO")
        self.acceleration_check.setChecked(self.config.ocr_acceleration)
        self.acceleration_check.setToolTip(
            "Tắt để luôn dùng CPU. Bật để cho phép backend tăng tốc đã chọn."
        )
        self.acceleration_check.toggled.connect(self._on_ocr_changed)
        self.ocr_box = self._combo(
            OCR_LANGUAGES, self.config.ocr_language, self._on_ocr_changed
        )
        ocr_form.addRow("Engine", self.engine_box)
        ocr_form.addRow("Mô hình", self.model_box)
        ocr_form.addRow("Tăng tốc", self.acceleration_check)
        ocr_form.addRow("Backend tăng tốc", self.backend_box)
        ocr_form.addRow("Ngôn ngữ", self.ocr_box)
        layout.addWidget(ocr_frame)

        engine_info = QFrame()
        engine_info.setObjectName("engineInfo")
        info_layout = QHBoxLayout(engine_info)
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
        model_meta_layout.setContentsMargins(12, 10, 12, 10)
        model_meta_layout.setSpacing(5)
        self.model_title = QLabel()
        self.model_title.setObjectName("modelTitle")
        self.model_metrics = QLabel()
        self.model_metrics.setObjectName("modelMetrics")
        self.model_metrics.setWordWrap(True)
        self.model_languages = QLabel()
        self.model_languages.setObjectName("modelLanguages")
        self.model_languages.setWordWrap(True)
        model_action_row = QHBoxLayout()
        model_action_row.setContentsMargins(0, 4, 0, 0)
        self.model_download_button = QPushButton("Tải mô hình")
        self.model_download_button.setObjectName("modelDownload")
        self.model_download_button.clicked.connect(self._download_selected_model)
        model_action_row.addWidget(self.model_download_button)
        model_action_row.addStretch(1)
        model_meta_layout.addWidget(self.model_title)
        model_meta_layout.addWidget(self.model_metrics)
        model_meta_layout.addWidget(self.model_languages)
        model_meta_layout.addLayout(model_action_row)
        layout.addWidget(model_meta)
        layout.addStretch(1)
        return page

    def _build_hud_page(self) -> QScrollArea:
        page, layout = self._page(
            "Khung dịch",
            "Kiểu chữ và màu được áp dụng trực tiếp lên nội dung bản dịch.",
        )
        hud_frame, hud_form = self._surface()
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
        self.border_width_spin = QDoubleSpinBox()
        self.border_width_spin.setRange(0.0, 8.0)
        self.border_width_spin.setDecimals(1)
        self.border_width_spin.setSingleStep(0.1)
        self.border_width_spin.setValue(self.config.hud_border_width)
        self.border_width_spin.setSuffix(" px")
        self.text_color_btn = ColorButton(self.config.hud_text_color)
        self.border_color_btn = ColorButton(self.config.hud_border_color)
        self.background_color_btn = ColorButton(
            self.config.hud_background_color, allow_alpha=True
        )
        self.font_family_box.currentIndexChanged.connect(self._on_hud_style_changed)
        self.font_size_spin.valueChanged.connect(self._on_hud_style_changed)
        self.border_width_spin.valueChanged.connect(self._on_hud_style_changed)
        self.text_color_btn.picked.connect(self._on_hud_style_changed)
        self.border_color_btn.picked.connect(self._on_hud_style_changed)
        self.background_color_btn.picked.connect(self._on_hud_style_changed)
        self.text_color_btn.previewed.connect(self._preview_hud_style)
        self.border_color_btn.previewed.connect(self._preview_hud_style)
        self.background_color_btn.previewed.connect(self._preview_hud_style)
        hud_form.addRow("Font chữ", self.font_family_box)
        hud_form.addRow("Cỡ chữ", self.font_size_spin)
        hud_form.addRow("Màu chữ", self.text_color_btn)
        hud_form.addRow("Viền chữ", self.border_width_spin)
        hud_form.addRow("Màu viền", self.border_color_btn)
        hud_form.addRow("Màu nền", self.background_color_btn)
        layout.addWidget(hud_frame)
        layout.addStretch(1)
        return page

    def _build_hotkeys_page(self) -> QScrollArea:
        page, layout = self._page(
            "Phím tắt",
            "Ghi tổ hợp phím toàn cục. Nhấn Del trong một ô để tắt phím đó.",
        )
        hint = QLabel("Bấm vào ô rồi nhấn tổ hợp phím. Del để tắt phím đó.")
        hint.setObjectName("muted")
        layout.addWidget(hint)
        hotkey_frame = QFrame()
        hotkey_frame.setObjectName("surface")
        hotkey_layout = QVBoxLayout(hotkey_frame)
        self.hotkey_edits: dict[str, HotkeyEdit] = {}
        for label, action in HOTKEY_ACTIONS:
            row = QHBoxLayout()
            row.addWidget(QLabel(label), 1)
            edit = HotkeyEdit(self.config.hotkeys.get(action, ""))
            edit.setMinimumWidth(160)
            self.hotkey_edits[action] = edit
            row.addWidget(edit)
            hotkey_layout.addLayout(row)
        layout.addWidget(hotkey_frame)

        save_button = QPushButton("Lưu phím tắt")
        save_button.setObjectName("primary")
        save_button.clicked.connect(self._apply_hotkeys)
        layout.addWidget(save_button, alignment=Qt.AlignLeft)
        layout.addStretch(1)
        return page

    def _build_about_page(self) -> QScrollArea:
        page, layout = self._page(
            "Giới thiệu",
            f"{APP_NAME} {APP_VERSION} · kho mã {GITHUB_REPO}.",
        )

        update_frame = QFrame()
        update_frame.setObjectName("surface")
        update_layout = QVBoxLayout(update_frame)
        update_layout.setContentsMargins(16, 14, 16, 14)
        update_layout.setSpacing(10)
        self.update_status_label = QLabel()
        self.update_status_label.setObjectName("engineHint")
        self.update_status_label.setWordWrap(True)
        update_layout.addWidget(self.update_status_label)
        self.auto_update_check = QCheckBox("Tự động kiểm tra cập nhật khi mở app")
        self.auto_update_check.setChecked(self.config.auto_update)
        self.auto_update_check.toggled.connect(self._on_auto_update_toggled)
        update_layout.addWidget(self.auto_update_check)
        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.check_update_button = QPushButton("Kiểm tra cập nhật")
        self.check_update_button.clicked.connect(self._check_updates)
        self.install_update_button = QPushButton("Cài đặt bản mới")
        self.install_update_button.setObjectName("primary")
        self.install_update_button.clicked.connect(self._install_update)
        button_row.addWidget(self.check_update_button)
        button_row.addWidget(self.install_update_button)
        button_row.addStretch(1)
        update_layout.addLayout(button_row)
        layout.addWidget(update_frame)

        links = QLabel(
            f'<a href="{GITHUB_RELEASES_URL}"><span style="color:#a5b4fc;">'
            "Xem tất cả phiên bản trên GitHub</span></a>"
        )
        links.setObjectName("llmRegistration")
        links.setOpenExternalLinks(True)
        links.setTextInteractionFlags(Qt.TextBrowserInteraction)
        layout.addWidget(links)
        layout.addStretch(1)
        self.refresh_update_state()
        return page

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

    def _on_target_changed(self) -> None:
        self.config.target_language = self.target_box.currentData()
        self.config.save()
        self.hud.sync_translation_controls()

    def _on_replace_target_changed(self) -> None:
        self.config.replace_target_language = self.replace_target_box.currentData()
        self.config.save()

    def _on_service_selected(self) -> None:
        data = self.service_box.currentData()
        if data == ADD_PROVIDER_KEY:
            self._add_provider()
            return
        self.config.translator = data
        if data.startswith("custom:"):
            provider = self.config.active_provider()
            models = provider["models"] if provider else []
        elif data in BUILTIN_AI_IDS:
            models = BUILTIN_AI_MODEL_IDS[data]
        else:
            models = []
        if models and self.config.llm_model not in models:
            self.config.llm_model = models[0]
        self.config.save()
        self._update_llm_controls()
        self.hud.sync_translation_controls()
        if data in BUILTIN_AI_IDS and not self.config.provider_api_key(data):
            name = BUILTIN_AI_BY_ID[data]["name"]
            self.hud.set_status(f"{name} đã chọn — nhập API key để sử dụng.", "ready")
        else:
            self.hud.set_status("Đã cập nhật cấu hình dịch.", "ready")

    def _on_key_changed(self) -> None:
        if self.config.translator in BUILTIN_AI_IDS:
            self.config.set_provider_api_key(
                self.config.translator, self.llm_key_edit.text().strip()
            )
            self.config.save()

    def _on_model_changed(self) -> None:
        data = self.llm_model_box.currentData()
        if data is None:
            return
        self.config.llm_model = data
        self.config.save()
        self.hud.sync_translation_controls()

    def _update_llm_controls(self) -> None:
        translator = self.config.translator
        is_builtin = translator in BUILTIN_AI_IDS
        is_custom = translator.startswith("custom:")
        self.llm_frame.setVisible(is_builtin or is_custom)
        if not (is_builtin or is_custom):
            return
        self.llm_model_box.blockSignals(True)
        self.llm_model_box.clear()
        if is_builtin:
            spec = BUILTIN_AI_BY_ID[translator]
            for label, model_id in spec["models"]:
                self.llm_model_box.addItem(label, model_id)
            self.llm_endpoint_edit.setText(spec["endpoint"])
            self.llm_key_edit.setReadOnly(False)
            self.llm_key_edit.setText(self.config.provider_api_key(translator))
            self.llm_registration_link.setText(
                f'<a href="{spec["register"]}"><span style="color:#a5b4fc;">'
                "Đăng ký tài khoản và lấy API key</span></a>"
            )
            self.llm_registration_link.setVisible(True)
            self.provider_manage_widget.setVisible(False)
        else:
            provider = self.config.active_provider() or {
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
        model_index = self.llm_model_box.findData(self.config.llm_model)
        self.llm_model_box.setCurrentIndex(max(0, model_index))
        self.llm_model_box.blockSignals(False)

    def sync_service_controls(self) -> None:
        """Đồng bộ combo dịch vụ + khung LLM theo config (gọi từ bar)."""
        self.service_box.blockSignals(True)
        index = self.service_box.findData(self.config.translator)
        self.service_box.setCurrentIndex(max(0, index))
        self.service_box.blockSignals(False)
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
            self.config.custom_providers = self.config.custom_providers + [provider]
            self.config.translator = f"custom:{provider['id']}"
            self.config.llm_model = data["models"][0]
            self.config.save()
            self._refresh_providers(f"Đã thêm provider “{data['name']}”.")
        else:
            self.sync_service_controls()

    def _edit_provider(self) -> None:
        provider = self.config.active_provider()
        if provider is None:
            return
        dialog = ProviderDialog(self, provider)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            provider.update(dialog.data())
            if self.config.llm_model not in provider["models"]:
                self.config.llm_model = provider["models"][0]
            self.config.save()
            self._refresh_providers(f"Đã cập nhật “{provider['name']}”.")

    def _delete_provider(self) -> None:
        provider = self.config.active_provider()
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
        self.config.translator = "google"
        self.config.save()
        self._refresh_providers(f"Đã xóa “{provider['name']}”.")

    def _refresh_providers(self, message: str) -> None:
        self._populate_service_box()
        self._update_llm_controls()
        if hasattr(self.hud, "rebuild_service_combo"):
            self.hud.rebuild_service_combo()
        else:
            self.hud.sync_translation_controls()
        self.hud.set_status(message, "ready")

    def _on_ocr_changed(self) -> None:
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
            badge, state = "TỰ ĐỘNG", "fallback"
        elif engine == "rapidocr" and not model_installed(model_id):
            badge, state = "CẦN TẢI", "missing"
        elif available:
            badge, state = "SẴN SÀNG", "ready"
        else:
            badge, state = "CẦN CÀI", "missing"
        self.engine_badge.setText(badge)
        self.engine_badge.setProperty("state", state)
        self.engine_badge.style().unpolish(self.engine_badge)
        self.engine_badge.style().polish(self.engine_badge)
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
        self.model_title.setText(
            f"{model.label}  ·  {'Đã tích hợp' if model.builtin else 'Tải theo nhu cầu'}"
        )
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
            button_text = "Đã sẵn sàng"
        else:
            button_text = f"Tải mô hình · {model.size_mb:g} MB"
        self.model_download_button.setText(button_text)

    def _download_selected_model(self) -> None:
        if self._model_download_running:
            return
        model_id = self.model_box.currentData()
        self._model_download_running = True
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
        self._update_engine_info()
        if error_message:
            self.hud.set_status(
                f"Không tải được {model_spec(model_id).label}: {error_message}",
                "error",
            )
        else:
            self.hud.set_status(f"Đã cài {model_spec(model_id).label}.", "ok")

    def _on_hud_style_changed(self) -> None:
        self.config.hud_font_family = self.font_family_box.currentData()
        self.config.hud_font_size = self.font_size_spin.value()
        self.config.hud_text_color = self.text_color_btn.color_hex()
        self.config.hud_border_width = self.border_width_spin.value()
        self.config.hud_border_color = self.border_color_btn.color_hex()
        self.config.hud_background_color = self.background_color_btn.color_value()
        self.config.save()
        self.hud.apply_hud_text_style()

    def _preview_hud_style(self) -> None:
        self.hud.preview_hud_text_style(
            self.font_family_box.currentData(),
            self.font_size_spin.value(),
            self.text_color_btn.color_hex(),
            self.border_width_spin.value(),
            self.border_color_btn.color_hex(),
            self.background_color_btn.color_value(),
        )

    def _apply_hotkeys(self) -> None:
        mapping = {action: edit.combo() for action, edit in self.hotkey_edits.items()}
        enabled = [combo for combo in mapping.values() if combo]
        if len(enabled) != len(set(enabled)):
            self.hud.set_status("Phím tắt bị trùng.", "error")
            return
        error = self.hud.hotkeys.apply(mapping)
        if error:
            self.hud.set_status(error, "error")
            return
        self.config.hotkeys = mapping
        self.config.save()
        self.hud.refresh_bar_tooltips()
        self.hud.set_status("Đã lưu phím tắt.", "ok")

    def closeEvent(self, event) -> None:
        if self._quitting:
            event.accept()
        else:
            event.ignore()
            self.hide()
