"""Cửa sổ HUD chính và vòng đời giao diện."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QTimer, Qt
from PySide6.QtGui import QAction, QGuiApplication, QImage
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSystemTrayIcon,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import overlay
from config import AppConfig
from constants import (
    BAR_ACTIONS,
    BAR_GROUP_CLIPBOARD,
    BAR_GROUP_FRAME,
    BAR_GROUP_OVERLAY,
    BUILTIN_AI_IDS,
    LANGUAGES,
    SONIOX_LANGUAGES,
    bar_service_key,
    bar_translator_entries,
    parse_bar_service_key,
)
from desktop_apps import list_desktop_applications
from hotkeys import HotkeyManager
from settings_window import SettingsWindow
from translation_workflows import TranslationWorkflowController
from soniox_realtime import SonioxRealtimeSession
from update_controller import UpdateController
from version import APP_NAME
from ui_utils import (
    ICON_IDLE,
    Bridge,
    TranslatorApplication,
    _bring_to_front,
    _brand_pixmap,
    _create_app_icon,
    _fmt_hotkey,
    _make_icon,
)
from widgets import (
    BarButton,
    BarMenuButton,
    BarComboBox,
    BusyBar,
    DragBar,
    HudBar,
    HudTextView,
    StatusPill,
)


class HUDWindow(QWidget):
    """HUD trong suốt; delegate nghiệp vụ dịch cho workflow controller."""

    RESIZE_MARGIN = 12
    SNAP_DISTANCE = 18

    def __init__(self) -> None:
        super().__init__()
        self.config = AppConfig.load()
        self._quitting = False
        self._hiding_to_tray = False
        self._tray_hint_shown = False
        self._capture_excluded = False
        self._settings_win: SettingsWindow | None = None
        self._mouse = None
        self._status_text = "Sẵn sàng"
        self._status_state = "ready"

        self.bridge = Bridge()
        self.bridge.run.connect(lambda callback: callback())
        self.app_icon = _create_app_icon()

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(self.app_icon)
        flags = Qt.FramelessWindowHint
        if self.config.hud_pinned:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        # Đủ rộng để thanh công cụ không bị bóp méo, vẫn nhỏ gọn trên màn hình.
        self.setMinimumSize(600, 150)
        self.setMouseTracking(True)

        self._build_ui()
        self.audio_session = SonioxRealtimeSession(self)
        self.audio_session.state_changed.connect(self._on_audio_state_changed)
        self.audio_session.transcript_changed.connect(self._on_audio_transcript)
        self.audio_session.failed.connect(self._on_audio_failed)
        self.audio_session.finished.connect(self._on_audio_finished)
        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.timeout.connect(self._persist_geometry)
        self._restore_geometry()

        self.workflow = TranslationWorkflowController(self)
        self.hotkeys = HotkeyManager(
            lambda action: self.bridge.run.emit(
                lambda: self.workflow.handle_action(action)
            )
        )
        warning = self.hotkeys.apply(self.config.hotkeys)
        self.set_status(warning or "Sẵn sàng", "error" if warning else "ready")
        self._setup_tray()
        self._setup_mouse_hook()

        self.updater = UpdateController(self)
        # Kiểm tra cập nhật sau khi vòng lặp UI ổn định (không chặn lúc mở app).
        QTimer.singleShot(1800, self.updater.check_on_startup)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        # Chừa lề quanh bar để bóng đổ không bị cắt ở mép cửa sổ.
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)
        self._bar = self._build_bar()
        self._display = self._build_display()
        root.addWidget(self._bar)
        root.addWidget(self._display, 1)
        self._sync_output_actions()

    def _build_bar(self) -> QWidget:
        bar = HudBar(self)
        bar.setObjectName("hudBar")
        shell = QVBoxLayout(bar)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        layout = QHBoxLayout()
        layout.setContentsMargins(8, 5, 8, 3)
        layout.setSpacing(2)
        self._standard_mode_widgets: list[QWidget] = []
        self._audio_mode_widgets: list[QWidget] = []
        self._audio_mode = False

        def add_standard(widget: QWidget) -> None:
            layout.addWidget(widget)
            self._standard_mode_widgets.append(widget)

        def add_audio(widget: QWidget) -> None:
            layout.addWidget(widget)
            self._audio_mode_widgets.append(widget)

        logo = QLabel()
        logo.setPixmap(_brand_pixmap(19))
        logo.setFixedSize(19, 19)
        logo.setToolTip(
            "Kéo để di chuyển · Kéo gần cạnh màn hình để tự hít · "
            "Nhấp đúp để ẩn/hiện thanh công cụ."
        )
        layout.addWidget(logo)
        layout.addSpacing(6)

        # Audio mode là một workspace riêng trên cùng thanh HUD. Các control
        # được tạo sẵn để chuyển mode không làm layout nhảy hoặc tạo lại widget.
        self.audio_mode_back_button = QPushButton("← AUDIO")
        self.audio_mode_back_button.setObjectName("barModeButton")
        self.audio_mode_back_button.setAccessibleName("Thoát chế độ dịch audio")
        self.audio_mode_back_button.setToolTip(
            "Quay lại các công cụ dịch ảnh và văn bản"
        )
        self.audio_mode_back_button.setFixedHeight(30)
        self.audio_mode_back_button.clicked.connect(self._exit_audio_mode)
        add_audio(self.audio_mode_back_button)
        add_audio(self._bar_separator())

        self.audio_button = BarButton("audio")
        self.audio_button.setAccessibleName("Bắt đầu dịch audio realtime")
        self.audio_button.setToolTip(
            "Bắt đầu/dừng phiên dịch audio với cấu hình đang chọn"
        )
        self.audio_button.setCheckable(True)
        self.audio_button.clicked.connect(self.toggle_audio_realtime)
        add_audio(self.audio_button)

        self.audio_source_combo = BarComboBox()
        self.audio_source_combo.setObjectName("barCombo")
        self.audio_source_combo.setAccessibleName("Nguồn audio Soniox")
        self.audio_source_combo.setToolTip(
            "Chọn âm thanh đang phát trên máy hoặc microphone"
        )
        self.audio_source_combo.setMinimumWidth(104)
        self.audio_source_combo.setMaximumWidth(132)
        self.audio_source_combo.addItem("HỆ THỐNG", "system")
        self.audio_source_combo.addItem("MICROPHONE", "microphone")
        add_audio(self.audio_source_combo)

        self.audio_display_combo = BarComboBox()
        self.audio_display_combo.setObjectName("barCombo")
        self.audio_display_combo.setAccessibleName("Chế độ hiển thị transcript")
        self.audio_display_combo.setToolTip(
            "Hiện song ngữ hoặc chỉ hiện bản dịch trong HUD"
        )
        self.audio_display_combo.setMinimumWidth(96)
        self.audio_display_combo.setMaximumWidth(112)
        self.audio_display_combo.addItem("SONG NGỮ", "bilingual")
        self.audio_display_combo.addItem("CHỈ DỊCH", "translation")
        add_audio(self.audio_display_combo)

        self.audio_target_combo = BarComboBox()
        self.audio_target_combo.setObjectName("barCombo")
        self.audio_target_combo.setAccessibleName("Ngôn ngữ đích audio")
        self.audio_target_combo.setToolTip(
            "Chọn ngôn ngữ đích cho dịch audio một chiều"
        )
        self.audio_target_combo.setMinimumWidth(94)
        self.audio_target_combo.setMaximumWidth(132)
        for label, code in SONIOX_LANGUAGES:
            self.audio_target_combo.addItem(f"→ {label}", code)
        add_audio(self.audio_target_combo)

        self.audio_alignment_combo = BarComboBox()
        self.audio_alignment_combo.setObjectName("barCombo")
        self.audio_alignment_combo.setAccessibleName("Căn lề transcript")
        self.audio_alignment_combo.setToolTip("Căn trái, giữa hoặc phải transcript")
        self.audio_alignment_combo.setMinimumWidth(82)
        self.audio_alignment_combo.setMaximumWidth(104)
        self.audio_alignment_combo.addItem("CĂN TRÁI", "left")
        self.audio_alignment_combo.addItem("CĂN GIỮA", "center")
        self.audio_alignment_combo.addItem("CĂN PHẢI", "right")
        add_audio(self.audio_alignment_combo)
        add_audio(self._bar_separator())

        for combo in (
            self.audio_source_combo,
            self.audio_display_combo,
            self.audio_target_combo,
            self.audio_alignment_combo,
        ):
            self._fit_popup(combo)
        self.sync_audio_controls()
        self.audio_source_combo.currentIndexChanged.connect(self._audio_source_changed)
        self.audio_display_combo.currentIndexChanged.connect(
            self._audio_display_changed
        )
        self.audio_target_combo.currentIndexChanged.connect(self._audio_target_changed)
        self.audio_alignment_combo.currentIndexChanged.connect(
            self._audio_alignment_changed
        )

        self.pin_button = BarButton("pin")
        self.pin_button.setAccessibleName("Ghim khung dịch")
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(self.config.hud_pinned)
        self.pin_button.toggled.connect(self._set_pinned)
        add_standard(self.pin_button)

        self.background_toggle_button = BarButton("bgtoggle")
        self.background_toggle_button.setAccessibleName("Nền khung dịch")
        self.background_toggle_button.setCheckable(True)
        self.background_toggle_button.setChecked(self.config.hud_background_enabled)
        self.background_toggle_button.toggled.connect(self._toggle_hud_background)
        add_standard(self.background_toggle_button)
        add_standard(self._bar_separator())

        self._translation_actions: dict[str, QAction] = {}
        self._action_group_buttons: dict[str, BarMenuButton] = {}
        self._action_group_menus: dict[str, QMenu] = {}
        self._action_group_for_action: dict[str, str] = {}
        self._group_actions: dict[str, tuple[str, ...]] = {}
        action_groups = (
            (
                "screen",
                BAR_GROUP_OVERLAY + BAR_GROUP_FRAME[:2],
                "scan",
                "MÀN HÌNH",
            ),
            ("clipboard", BAR_GROUP_CLIPBOARD, "image", "ẢNH"),
            ("text", BAR_GROUP_FRAME[2:], "text", "VĂN BẢN"),
        )
        for group_id, actions, kind, label in action_groups:
            add_standard(self._build_action_menu(group_id, actions, kind, label))
        add_standard(self._bar_separator())

        self.audio_mode_button = QPushButton("Audio")
        self.audio_mode_button.setIcon(_make_icon("audio", ICON_IDLE, 18))
        self.audio_mode_button.setObjectName("barGroupToggle")
        self.audio_mode_button.setAccessibleName("Mở điều khiển dịch audio")
        self.audio_mode_button.setToolTip(
            "Mở Audio mode để chọn nguồn, ngôn ngữ và cách hiển thị"
        )
        self.audio_mode_button.setCheckable(True)
        self.audio_mode_button.setFixedHeight(30)
        self.audio_mode_button.setCursor(Qt.PointingHandCursor)
        self.audio_mode_button.clicked.connect(self._enter_audio_mode)
        add_standard(self.audio_mode_button)
        add_standard(self._bar_separator())

        self.copy_button = BarButton("copy")
        self.copy_button.setAccessibleName("Copy bản dịch")
        self.copy_button.setToolTip("Copy bản dịch trong khung vào clipboard")
        self.copy_button.clicked.connect(self._copy_output)
        layout.addWidget(self.copy_button)
        self.clear_button = BarButton("clear")
        self.clear_button.setAccessibleName("Xoá khung dịch")
        self.clear_button.setToolTip("Xoá nội dung đang hiện trong khung dịch")
        self.clear_button.clicked.connect(self._clear_output)
        layout.addWidget(self.clear_button)
        layout.addStretch(1)

        self.status_pill = StatusPill()
        self.status_pill.setAccessibleName("Trạng thái")
        layout.addWidget(self.status_pill)
        layout.addSpacing(4)
        layout.addWidget(self._bar_separator())

        self.service_combo = BarComboBox()
        self.service_combo.setObjectName("barCombo")
        self.service_combo.setAccessibleName("Dịch vụ dịch")
        self.service_combo.setToolTip("Chọn dịch vụ dịch")
        self.service_combo.setMinimumWidth(104)
        self.service_combo.setMaximumWidth(196)
        for label, key in self._service_entries():
            self.service_combo.addItem(label, key)

        self.target_combo = BarComboBox()
        self.target_combo.setObjectName("barCombo")
        self.target_combo.setAccessibleName("Ngôn ngữ đích")
        self.target_combo.setToolTip("Chọn ngôn ngữ đích của bản dịch")
        self.target_combo.setMinimumWidth(88)
        self.target_combo.setMaximumWidth(132)
        for label, code in LANGUAGES:
            self.target_combo.addItem(label, code)
        self.sync_translation_controls()
        self._fit_popup(self.service_combo)
        self._fit_popup(self.target_combo)
        self.service_combo.currentIndexChanged.connect(self._service_changed)
        self.target_combo.currentIndexChanged.connect(self._target_changed)
        add_standard(self.service_combo)
        add_standard(self.target_combo)
        add_standard(self._bar_separator())

        settings_button = BarButton("settings")
        settings_button.setAccessibleName("Cài đặt")
        settings_button.setToolTip("Mở cài đặt")
        settings_button.clicked.connect(self._open_settings)
        layout.addWidget(settings_button)
        hide_button = BarButton("hide")
        hide_button.setAccessibleName("Ẩn vào khay")
        hide_button.setToolTip("Ẩn vào khay hệ thống (nhấp icon khay để mở lại)")
        hide_button.clicked.connect(self._hide_to_tray)
        layout.addWidget(hide_button)
        shell.addLayout(layout)

        # Vạch tiến trình mảnh sát mép dưới bar, chỉ chạy khi đang xử lý.
        busy_row = QHBoxLayout()
        busy_row.setContentsMargins(10, 0, 10, 4)
        self.busy_bar = BusyBar()
        busy_row.addWidget(self.busy_bar)
        shell.addLayout(busy_row)

        self._set_audio_mode(False)
        self.refresh_bar_tooltips()
        self._sync_pin_tooltip()
        self._sync_background_toggle_tooltip()
        self._sync_output_actions()
        return bar

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index < 0 or index == combo.currentIndex():
            return
        combo.blockSignals(True)
        combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def sync_audio_controls(self) -> None:
        """Đồng bộ Audio mode với cấu hình dùng chung của cửa sổ Cài đặt."""
        if not hasattr(self, "audio_source_combo"):
            return
        self._set_combo_value(self.audio_source_combo, self.config.soniox_audio_source)
        self._set_combo_value(self.audio_display_combo, self.config.soniox_display_mode)
        self._set_combo_value(
            self.audio_target_combo, self.config.soniox_target_language
        )
        self._set_combo_value(
            self.audio_alignment_combo, self.config.soniox_text_alignment
        )

    def _set_audio_mode(self, enabled: bool) -> None:
        self._audio_mode = enabled
        self.audio_mode_button.setChecked(enabled)
        for widget in self._standard_mode_widgets:
            widget.setVisible(not enabled)
        for widget in self._audio_mode_widgets:
            widget.setVisible(enabled)
        active = bool(getattr(getattr(self, "audio_session", None), "is_active", False))
        self.audio_mode_back_button.setEnabled(not active)
        self._sync_bar_density()

    def _sync_bar_density(self) -> None:
        if not hasattr(self, "status_pill"):
            return
        width = self.width()
        if self._audio_mode:
            show_output = width >= 820
            self.copy_button.setVisible(show_output)
            self.clear_button.setVisible(show_output)
            self.status_pill.setVisible(show_output)
            return
        show_output = width >= 720
        self.copy_button.setVisible(show_output)
        self.clear_button.setVisible(show_output)
        self.status_pill.setVisible(width >= 900)
        self.service_combo.setVisible(width >= 700)

    def _enter_audio_mode(self) -> None:
        self.sync_audio_controls()
        self._set_audio_mode(True)

    def _exit_audio_mode(self) -> None:
        if self.audio_session.is_active:
            return
        self._set_audio_mode(False)

    def _sync_open_soniox_controls(self) -> None:
        if self._settings_win is not None:
            self._settings_win.sync_soniox_controls()

    def _audio_source_changed(self) -> None:
        source = self.audio_source_combo.currentData()
        if not isinstance(source, str):
            return
        self.config.soniox_audio_source = source
        self.config.save()
        self._sync_open_soniox_controls()

    def _audio_display_changed(self) -> None:
        display_mode = self.audio_display_combo.currentData()
        if not isinstance(display_mode, str):
            return
        self.config.soniox_display_mode = display_mode
        self.config.save()
        self.refresh_audio_transcript_display()
        self._sync_open_soniox_controls()

    def _audio_target_changed(self) -> None:
        language = self.audio_target_combo.currentData()
        if not isinstance(language, str):
            return
        self.config.soniox_target_language = language
        self.config.save()
        self._sync_open_soniox_controls()

    def _audio_alignment_changed(self) -> None:
        alignment = self.audio_alignment_combo.currentData()
        if not isinstance(alignment, str):
            return
        self.config.soniox_text_alignment = alignment
        self.config.save()
        self.refresh_audio_transcript_display()
        self._sync_open_soniox_controls()

    def _service_entries(self) -> list[tuple[str, str]]:
        models = {
            provider_id: self.config.provider_models(provider_id)
            for provider_id in BUILTIN_AI_IDS
        }
        return bar_translator_entries(
            self.config.custom_providers,
            builtin_models=models,
            enabled_providers=self.config.configured_ai_provider_ids(),
        )

    @staticmethod
    def _fit_popup(combo: QComboBox) -> None:
        """Danh sách bật lên rộng theo nội dung dù combo trên bar bị giới hạn.

        Nhãn kiểu “Translator Box · Mistral Small” dài hơn combo; nếu không nới
        popup thì cả danh sách cũng bị cắt và không phân biệt được model nào.
        """
        metrics = combo.fontMetrics()
        widest = max(
            (
                metrics.horizontalAdvance(combo.itemText(index))
                for index in range(combo.count())
            ),
            default=0,
        )
        combo.view().setMinimumWidth(widest + 46)

    def _build_action_menu(
        self, group_id: str, actions: list, kind: str, label: str
    ) -> BarMenuButton:
        button = BarMenuButton(kind, label)
        button.setAccessibleName(f"Nhóm dịch {label}")
        button.setToolTip(f"Nhấn để mở nhóm dịch {label.lower()} ở phía trên")
        menu = QMenu(button)
        menu.setObjectName("barActionMenu")
        menu.setAccessibleName(f"Chức năng dịch {label}")
        action_ids: list[str] = []
        for icon_kind, accessible_name, action, _tooltip in actions:
            menu_action = QAction(
                _make_icon(icon_kind, ICON_IDLE, 18), accessible_name, menu
            )
            menu_action.setCheckable(
                action in ("region_to_live", "region_to_live_frame")
            )
            menu_action.triggered.connect(
                lambda _checked=False, current=action: self.workflow.handle_action(
                    current
                )
            )
            menu.addAction(menu_action)
            self._translation_actions[action] = menu_action
            self._action_group_for_action[action] = group_id
            action_ids.append(action)
        if group_id == "screen":
            menu.addSeparator()
            self._application_menu = QMenu("Chọn ứng dụng", menu)
            self._application_menu.setObjectName("applicationFocusMenu")
            self._application_menu.setAccessibleName(
                "Chọn ứng dụng được phép dịch Live"
            )
            self._application_menu.setIcon(_make_icon("scan", ICON_IDLE, 18))
            self._application_menu.aboutToShow.connect(self._populate_application_menu)
            menu.addMenu(self._application_menu)
        button.attach_menu(menu)
        self._action_group_buttons[group_id] = button
        self._action_group_menus[group_id] = menu
        self._group_actions[group_id] = tuple(action_ids)
        return button

    def _populate_application_menu(self) -> None:
        menu = self._application_menu
        menu.clear()
        selected_id = self.config.live_focus_app_id

        all_apps = QAction("Mọi ứng dụng", menu)
        all_apps.setCheckable(True)
        all_apps.setChecked(not selected_id)
        all_apps.triggered.connect(
            lambda _checked=False: self._select_live_focus_application("", "")
        )
        menu.addAction(all_apps)
        menu.addSeparator()

        applications = list_desktop_applications()
        known_ids = {application.application_id for application in applications}
        if selected_id and selected_id not in known_ids:
            unavailable = QAction(
                f"{self.config.live_focus_app_label or 'Ứng dụng đã chọn'} (không mở)",
                menu,
            )
            unavailable.setCheckable(True)
            unavailable.setChecked(True)
            unavailable.setEnabled(False)
            menu.addAction(unavailable)
            menu.addSeparator()
        if not applications:
            empty = QAction("Không tìm thấy ứng dụng đang mở", menu)
            empty.setEnabled(False)
            menu.addAction(empty)
            return
        for application in applications:
            action = QAction(application.label, menu)
            action.setCheckable(True)
            action.setChecked(application.application_id == selected_id)
            action.setToolTip(
                f"Live chỉ dịch khi {application.name} là ứng dụng đang focus"
            )
            action.triggered.connect(
                lambda _checked=False, current=application: (
                    self._select_live_focus_application(
                        current.application_id, current.label
                    )
                )
            )
            menu.addAction(action)

    def _select_live_focus_application(
        self, application_id: str, application_label: str
    ) -> None:
        self.workflow.set_live_focus_application(application_id, application_label)

    def _bar_separator(self) -> QFrame:
        separator = QFrame()
        separator.setObjectName("barSep")
        separator.setFixedSize(1, 18)
        wrapper = QWidget(self)
        wrapper_layout = QHBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(5, 0, 5, 0)
        wrapper_layout.addWidget(separator)
        wrapper.setFixedWidth(11)
        return wrapper

    def _build_display(self) -> QWidget:
        display = DragBar(self)
        display.setObjectName("hudDisplay")
        display.setToolTip(
            "Khung nhận bản dịch · Kéo để di chuyển · Nhấp đúp để ẩn/hiện thanh công cụ"
        )
        layout = QVBoxLayout(display)
        layout.setContentsMargins(14, 8, 14, 10)
        layout.setSpacing(0)

        self.output = HudTextView()
        self.output.setAccessibleName("Nội dung bản dịch")
        self.apply_hud_text_style()
        layout.addWidget(self.output, 1)
        return display

    def _copy_output(self) -> None:
        text = self.output.text().strip()
        image = self.output.image()
        if not text and image.isNull():
            self.set_status("Khung dịch đang trống.", "error")
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            self.set_status("Không truy cập được clipboard.", "error")
            return
        if not image.isNull():
            clipboard.setImage(image)
            self.set_status("Đã copy ảnh dịch vào clipboard.", "ok")
        else:
            clipboard.setText(text)
            self.set_status("Đã copy bản dịch vào clipboard.", "ok")

    def _clear_output(self) -> None:
        if not self.output.has_content():
            return
        self.set_output("")
        self.set_status("Đã xoá khung dịch.", "ready")

    def toggle_audio_realtime(self) -> None:
        """Bật/tắt phiên dịch mic hoặc audio hệ thống từ HUD/Cài đặt."""
        if self.audio_session.is_active:
            self.audio_session.stop()
            return
        if not self.audio_session.is_active:
            self._enter_audio_mode()
        started = self.audio_session.start(
            api_key=self.config.soniox_api_key,
            audio_source=self.config.soniox_audio_source,
            device_id=self.config.soniox_input_device,
            system_device=self.config.soniox_system_device,
            translation_mode=self.config.soniox_translation_mode,
            target_language=self.config.soniox_target_language,
            language_a=self.config.soniox_language_a,
            language_b=self.config.soniox_language_b,
            speaker_diarization=self.config.soniox_speaker_diarization,
        )
        if started:
            self.set_output("")
            self.ensure_visible()

    def _on_audio_state_changed(self, state: str) -> None:
        active = state != "idle"
        if active:
            self._set_audio_mode(True)
        self.audio_button.blockSignals(True)
        self.audio_button.setChecked(active)
        self.audio_button.blockSignals(False)
        self.set_busy(active)
        self.audio_button.setEnabled(state != "stopping")
        self.audio_mode_back_button.setEnabled(not active)
        self.audio_button.setAccessibleName(
            "Dừng dịch audio realtime" if active else "Bắt đầu dịch audio realtime"
        )
        self.audio_button.setToolTip(
            "Dừng và hoàn tất transcript đang nghe"
            if active
            else "Bắt đầu phiên dịch audio với cấu hình đang chọn"
        )
        source_label = (
            "audio hệ thống" if self.audio_session.source == "system" else "microphone"
        )
        if state == "connecting":
            self.set_status(f"Đang kết nối Soniox · {source_label}…", "busy")
        elif state == "listening":
            self.set_status(f"Đang nghe và dịch {source_label}…", "busy")
        elif state == "stopping":
            self.set_status("Đang hoàn tất transcript Soniox…", "busy")
        if self._settings_win is not None:
            self._settings_win.sync_soniox_state(state)
            self._settings_win.sync_soniox_controls()

    def _on_audio_transcript(self, text: str) -> None:
        self.refresh_audio_transcript_display(fallback=text)
        self.ensure_visible()

    def refresh_audio_transcript_display(self, fallback: str = "") -> None:
        """Áp dụng chế độ/căn lề mới mà không cần khởi động lại phiên."""
        blocks = self.audio_session.transcript_blocks
        if not blocks:
            if fallback:
                self.set_output(fallback)
            return
        self.output.set_transcript(
            blocks,
            display_mode=self.config.soniox_display_mode,
            alignment=self.config.soniox_text_alignment,
        )
        self._sync_output_actions()

    def _on_audio_failed(self, message: str) -> None:
        self.set_status(message, "error")
        self.ensure_visible()

    def _on_audio_finished(self) -> None:
        self.set_status("Đã kết thúc phiên dịch audio.", "ok")

    def _sync_output_actions(self) -> None:
        """Copy/Xoá chỉ bấm được khi trong khung đang có bản dịch."""
        has_content = self.output.has_content() if hasattr(self, "output") else False
        for button in (self.copy_button, self.clear_button):
            button.setEnabled(has_content)
        if hasattr(self, "output") and not self.output.image().isNull():
            self.copy_button.setAccessibleName("Copy ảnh dịch")
            self.copy_button.setToolTip("Copy ảnh đã dịch vào clipboard")
        else:
            self.copy_button.setAccessibleName("Copy bản dịch")
            self.copy_button.setToolTip("Copy bản dịch trong khung vào clipboard")

    def apply_hud_text_style(self) -> None:
        self.preview_hud_text_style(
            self.config.hud_font_family,
            self.config.hud_font_size,
            self.config.hud_text_color,
            self.config.hud_border_width,
            self.config.hud_border_color,
            self.config.hud_background_color,
            self.config.hud_shadow_radius,
            self.config.hud_shadow_color,
            self.config.hud_background_enabled,
        )

    def preview_hud_text_style(
        self,
        font_family: str,
        font_size: int,
        text_color: str,
        border_width: float,
        border_color: str,
        background_color: str,
        shadow_radius: float = 0.0,
        shadow_color: str = "#00000000",
        background_enabled: bool = True,
    ) -> None:
        self.output.apply_style(
            font_family,
            font_size,
            text_color,
            border_width,
            border_color,
            background_color,
            shadow_radius,
            shadow_color,
            background_enabled,
        )

    def _sync_pin_tooltip(self) -> None:
        if self.pin_button.isChecked():
            self.pin_button.setToolTip(
                "Đang ghim trên cùng · Bấm để tự ẩn khi chuyển sang ứng dụng khác"
            )
        else:
            self.pin_button.setToolTip(
                "Đã bỏ ghim · Khung dịch sẽ ẩn khi chuyển sang ứng dụng khác"
            )

    def _set_pinned(self, pinned: bool) -> None:
        if self.config.hud_pinned == pinned:
            self._sync_pin_tooltip()
            return
        was_visible = self.isVisible()
        geometry = self.geometry()
        self.config.hud_pinned = pinned
        self.config.save()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, pinned)
        self.setGeometry(geometry)
        self._sync_pin_tooltip()
        if was_visible:
            _bring_to_front(self)

    def _sync_background_toggle_tooltip(self) -> None:
        if self.background_toggle_button.isChecked():
            self.background_toggle_button.setToolTip(
                "Nền khung dịch: BẬT · Bấm để xem chữ trong suốt trên desktop"
            )
        else:
            self.background_toggle_button.setToolTip(
                "Nền khung dịch: TẮT · Bấm để tô màu nền đã chọn ở Cài đặt"
            )

    def _toggle_hud_background(self, enabled: bool) -> None:
        self._sync_background_toggle_tooltip()
        if self.config.hud_background_enabled == enabled:
            return
        self.config.hud_background_enabled = enabled
        self.config.save()
        self.apply_hud_text_style()
        if self._settings_win is not None:
            self._settings_win.sync_hud_background_toggle()
        self.set_status(
            "Đã bật nền khung dịch." if enabled else "Đã tắt nền khung dịch.", "ready"
        )

    def _active_window_belongs_to_settings(self) -> bool:
        active = QApplication.activeWindow()
        while active is not None:
            if active is self or active is self._settings_win:
                return True
            active = active.parentWidget()
        return False

    def _hide_if_unpinned_inactive(self) -> None:
        if (
            self._quitting
            or self.config.hud_pinned
            or not self.isVisible()
            or self._active_window_belongs_to_settings()
        ):
            return
        self._persist_geometry()
        self.hide()

    def _toggle_bar(self) -> None:
        self._bar.setVisible(not self._bar.isVisible())

    def _edges_for_global(self, global_position: QPoint):
        if not self._bar.isVisible():
            return None
        position = self.mapFromGlobal(global_position)
        rect = self.rect()
        if not rect.contains(position):
            return None
        edges = Qt.Edges()
        if position.y() <= self.RESIZE_MARGIN:
            edges |= Qt.TopEdge
        elif position.y() >= rect.height() - self.RESIZE_MARGIN:
            edges |= Qt.BottomEdge
        if position.x() <= self.RESIZE_MARGIN:
            edges |= Qt.LeftEdge
        elif position.x() >= rect.width() - self.RESIZE_MARGIN:
            edges |= Qt.RightEdge
        return edges if edges else None

    @staticmethod
    def _cursor_for_edges(edges):
        if edges is None:
            return Qt.ArrowCursor
        top, bottom = bool(edges & Qt.TopEdge), bool(edges & Qt.BottomEdge)
        left, right = bool(edges & Qt.LeftEdge), bool(edges & Qt.RightEdge)
        if (top and left) or (bottom and right):
            return Qt.SizeFDiagCursor
        if (top and right) or (bottom and left):
            return Qt.SizeBDiagCursor
        if left or right:
            return Qt.SizeHorCursor
        return Qt.SizeVerCursor if top or bottom else Qt.ArrowCursor

    def _try_start_resize(self, global_position: QPoint) -> bool:
        edges = self._edges_for_global(global_position)
        handle = self.windowHandle()
        if edges is None or handle is None:
            return False
        handle.startSystemResize(edges)
        return True

    def mouseMoveEvent(self, event) -> None:
        self.setCursor(
            self._cursor_for_edges(
                self._edges_for_global(event.globalPosition().toPoint())
            )
        )
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._try_start_resize(
            event.globalPosition().toPoint()
        ):
            event.accept()
            return
        super().mousePressEvent(event)

    def refresh_bar_tooltips(self) -> None:
        for _kind, label, action, tooltip in BAR_ACTIONS:
            menu_action = self._translation_actions.get(action)
            if menu_action is None:
                continue
            hotkey = _fmt_hotkey(self.config.hotkeys.get(action, ""))
            menu_action.setText(f"{label}\t{hotkey}")
            menu_action.setToolTip(f"{tooltip}\nPhím tắt: {hotkey}")
            menu_action.setStatusTip(tooltip)

    def _restore_geometry(self) -> None:
        geometry = self.config.hud_geometry
        width = int(geometry.get("w") or 977)
        height = int(geometry.get("h") or 252)
        self.resize(width, height)
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.move(50, 50)
            return
        x, y = geometry.get("x"), geometry.get("y")
        if x is None or y is None:
            available = screen.availableGeometry()
            x = available.left() + (available.width() - width) // 2
            y = available.top() + 60
        virtual = screen.virtualGeometry()
        max_x = max(virtual.left(), virtual.right() - width)
        max_y = max(virtual.top(), virtual.bottom() - height)
        self.move(
            max(virtual.left(), min(int(x), max_x)),
            max(virtual.top(), min(int(y), max_y)),
        )

    def _snapped_position(self, position: QPoint, pointer: QPoint) -> QPoint:
        """Hít mép HUD vào cạnh vùng làm việc của màn hình đang kéo tới."""
        screen = QGuiApplication.screenAt(pointer)
        if screen is None:
            screen = QGuiApplication.screenAt(
                position + QPoint(self.width() // 2, self.height() // 2)
            )
        if screen is None:
            return position
        available = screen.availableGeometry()
        right = max(available.left(), available.right() - self.width() + 1)
        bottom = max(available.top(), available.bottom() - self.height() + 1)

        def snap(value: int, first: int, second: int) -> int:
            target = min((first, second), key=lambda edge: abs(value - edge))
            return target if abs(value - target) <= self.SNAP_DISTANCE else value

        return QPoint(
            snap(position.x(), available.left(), right),
            snap(position.y(), available.top(), bottom),
        )

    def _move_with_snap(self, position: QPoint, pointer: QPoint) -> None:
        self.move(self._snapped_position(position, pointer))

    def _persist_geometry(self) -> None:
        if self._quitting:
            return
        self.config.hud_geometry = {
            "x": self.x(),
            "y": self.y(),
            "w": self.width(),
            "h": self.height(),
        }
        self.config.save()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_bar_density()
        if not self._quitting and self.isVisible():
            self._geometry_timer.start(400)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._capture_excluded:
            self._capture_excluded = bool(overlay._exclude_from_capture(self))

    def _open_settings(self) -> None:
        if self._settings_win is None:
            self._settings_win = SettingsWindow(self)
        _bring_to_front(self._settings_win)

    def sync_translation_controls(self) -> None:
        key = bar_service_key(self.config.translator, self.config.llm_model)
        service_index = self.service_combo.findData(key)
        if service_index >= 0 and service_index != self.service_combo.currentIndex():
            self.service_combo.blockSignals(True)
            self.service_combo.setCurrentIndex(service_index)
            self.service_combo.blockSignals(False)
        index = self.target_combo.findData(self.config.target_language)
        if index >= 0 and index != self.target_combo.currentIndex():
            self.target_combo.blockSignals(True)
            self.target_combo.setCurrentIndex(index)
            self.target_combo.blockSignals(False)

    def sync_target_combo(self) -> None:
        """Tương thích với caller cũ; đồng bộ cả dịch vụ và ngôn ngữ."""
        self.sync_translation_controls()

    def _service_changed(self) -> None:
        key = self.service_combo.currentData()
        if key is None:
            return
        service, llm_model = parse_bar_service_key(key)
        self.config.translator = service
        if llm_model is not None:
            self.config.llm_model = llm_model
        self.config.save()
        if self._settings_win is not None:
            self._settings_win.sync_service_controls()

    def rebuild_service_combo(self) -> None:
        """Dựng lại danh sách dịch vụ trên bar sau khi provider tùy chỉnh đổi."""
        self.service_combo.blockSignals(True)
        self.service_combo.clear()
        for label, key in self._service_entries():
            self.service_combo.addItem(label, key)
        self.service_combo.blockSignals(False)
        self._fit_popup(self.service_combo)
        self.sync_translation_controls()

    def _target_changed(self) -> None:
        code = self.target_combo.currentData()
        if code is None:
            return
        self.config.target_language = code
        self.config.save()
        if self._settings_win is not None:
            index = self._settings_win.target_box.findData(code)
            self._settings_win.target_box.blockSignals(True)
            self._settings_win.target_box.setCurrentIndex(index)
            self._settings_win.target_box.blockSignals(False)

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(self.app_icon, QApplication.instance())
        self.tray.setToolTip(f"{APP_NAME} — {self._status_text}")
        menu = QMenu()
        icons = {
            "Mở HUD": "overlay",
            "Hiện thanh công cụ": "text",
            "Dịch audio": "audio",
            "Cài đặt…": "settings",
            "Ẩn": "hide",
        }
        for label, callback in self._tray_commands():
            action = QAction(label, menu)
            kind = icons.get(label)
            if kind is not None:
                action.setIcon(_make_icon(kind, ICON_IDLE, 20))
            action.triggered.connect(callback)
            menu.addAction(action)
        menu.addSeparator()
        quit_action = QAction("Thoát", menu)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self._tray_menu = menu
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_commands(self) -> tuple[tuple[str, object], ...]:
        return (
            ("Mở HUD", self._restore_from_tray),
            ("Hiện thanh công cụ", self.show_toolbar),
            ("Dịch audio", self.toggle_audio_realtime),
            ("Cài đặt…", self._open_settings),
            ("Ẩn", self._hide_to_tray),
        )

    def _tray_activated(self, reason) -> None:
        if reason not in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.MiddleClick,
        ):
            return
        if self.isVisible() and not self.isMinimized():
            self._hide_to_tray()
        else:
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self._hiding_to_tray = False
        _bring_to_front(self)

    def show_toolbar(self) -> None:
        """Khôi phục cả HUD và thanh công cụ từ menu icon khay."""
        self._bar.show()
        self._hiding_to_tray = False
        _bring_to_front(self)

    def _hide_to_tray(self) -> None:
        if self._quitting or self._hiding_to_tray:
            return
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.showMinimized()
            self.set_status("Khay hệ thống không dùng được — đã thu nhỏ.", "error")
            return
        self._hiding_to_tray = True
        try:
            self._persist_geometry()
            self.hide()
            if not self._tray_hint_shown and QSystemTrayIcon.supportsMessages():
                self.tray.showMessage(
                    "Đang chạy nền",
                    "Nhấp icon T để mở · Chuột phải → Hiện thanh công cụ.",
                    QSystemTrayIcon.MessageIcon.Information,
                    4000,
                )
                self._tray_hint_shown = True
        finally:
            self._hiding_to_tray = False

    def _setup_mouse_hook(self) -> None:
        try:
            import mouse

            self._mouse = mouse
            mouse.on_right_click(
                lambda: self.bridge.run.emit(self.workflow.dismiss_transient_overlays)
            )
        except Exception:  # noqa: BLE001
            self._mouse = None

    def set_status(self, text: str, state: str = "ready") -> None:
        self._status_text = text
        self._status_state = state
        if hasattr(self, "status_pill"):
            self.status_pill.set_state(text, state)
            self.status_pill.setToolTip(text)
        if hasattr(self, "tray"):
            self.tray.setToolTip(f"{APP_NAME} — {text}")

    def set_busy(self, busy: bool) -> None:
        if hasattr(self, "busy_bar"):
            self.busy_bar.set_active(busy)
        for action, menu_action in self._translation_actions.items():
            is_live = action in ("region_to_live", "region_to_live_frame")
            menu_action.setEnabled(not busy or is_live)
        for group_id, button in self._action_group_buttons.items():
            button.setEnabled(
                any(
                    self._translation_actions[action].isEnabled()
                    for action in self._group_actions[group_id]
                )
            )
        self.target_combo.setEnabled(not busy)
        self.service_combo.setEnabled(not busy)
        self.audio_mode_button.setEnabled(not busy)
        self.audio_source_combo.setEnabled(not busy)
        self.audio_target_combo.setEnabled(not busy)
        if hasattr(self, "audio_button"):
            self.audio_button.setEnabled(self.audio_session.is_active or not busy)
        if self._settings_win is not None:
            for control in (
                self._settings_win.service_box,
                self._settings_win.target_box,
                self._settings_win.llm_endpoint_edit,
                self._settings_win.llm_key_edit,
                self._settings_win.llm_model_box,
                self._settings_win.engine_box,
                self._settings_win.model_box,
                self._settings_win.backend_box,
                self._settings_win.acceleration_check,
                self._settings_win.ocr_box,
                self._settings_win.soniox_key_edit,
                self._settings_win.soniox_source_box,
                self._settings_win.soniox_microphone_box,
                self._settings_win.soniox_system_device_box,
                self._settings_win.soniox_mode_box,
                self._settings_win.soniox_target_box,
                self._settings_win.soniox_language_a_box,
                self._settings_win.soniox_language_b_box,
                self._settings_win.soniox_diarization_check,
            ):
                control.setEnabled(not busy)
            if not busy:
                self._settings_win._update_engine_info()

    def set_output(self, text: str) -> None:
        self.output.setText(text)
        self._sync_output_actions()

    def set_output_image(self, image: QImage) -> None:
        self.output.setImage(image)
        self._sync_output_actions()

    def ensure_visible(self) -> None:
        if not self.isVisible() or self.isMinimized():
            _bring_to_front(self)
        else:
            self.raise_()

    def set_live_action_checked(self, action: str, checked: bool) -> None:
        menu_action = self._translation_actions.get(action)
        group_id = self._action_group_for_action.get(action)
        if menu_action is None or group_id is None:
            return
        menu_action.setChecked(checked)
        group_button = self._action_group_buttons[group_id]
        group_live = any(
            self._translation_actions[group_action].isChecked()
            for group_action in self._group_actions[group_id]
        )
        group_button.setProperty("live", group_live)
        group_button.style().unpolish(group_button)
        group_button.style().polish(group_button)
        group_button.update()

    def event(self, event) -> bool:
        result = super().event(event)
        if (
            not self._quitting
            and not self._hiding_to_tray
            and event.type() == QEvent.Type.WindowDeactivate
            and not self.config.hud_pinned
        ):
            QTimer.singleShot(0, self._hide_if_unpinned_inactive)
        return result

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if (
            not self._quitting
            and not self._hiding_to_tray
            and event.type() == QEvent.Type.WindowStateChange
            and bool(self.windowState() & Qt.WindowState.WindowMinimized)
        ):
            QTimer.singleShot(0, self._hide_to_tray)

    def quit_app(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self._geometry_timer.stop()
        self.workflow.shutdown()
        self.audio_session.shutdown()
        self.config.hud_geometry = {
            "x": self.x(),
            "y": self.y(),
            "w": self.width(),
            "h": self.height(),
        }
        self.config.save()
        app = QApplication.instance()
        if isinstance(app, TranslatorApplication):
            app.allow_quit = True
        if hasattr(self, "tray"):
            self.tray.hide()
        if self._settings_win is not None:
            self._settings_win._quitting = True
            self._settings_win.close()
        self.close()
        if app is not None:
            app.quit()

    def closeEvent(self, event) -> None:
        if not self._quitting:
            event.ignore()
            QTimer.singleShot(0, self._hide_to_tray)
            return
        self.hotkeys.clear()
        if self._mouse is not None:
            try:
                self._mouse.unhook_all()
            except Exception:  # noqa: BLE001
                pass
        overlay.close_all_translations()
        if hasattr(self, "tray"):
            self.tray.hide()
        event.accept()
