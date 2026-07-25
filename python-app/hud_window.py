"""Cửa sổ HUD chính và vòng đời giao diện."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSystemTrayIcon,
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
    bar_service_key,
    bar_translator_entries,
    parse_bar_service_key,
)
from hotkeys import HotkeyManager
from settings_window import SettingsWindow
from translation_workflows import TranslationWorkflowController
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
from widgets import BarButton, BusyBar, DragBar, HudBar, HudTextView, StatusPill


class HUDWindow(QWidget):
    """HUD trong suốt; delegate nghiệp vụ dịch cho workflow controller."""

    RESIZE_MARGIN = 12

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
        self._sync_placeholder()
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

        logo = QLabel()
        logo.setPixmap(_brand_pixmap(19))
        logo.setFixedSize(19, 19)
        logo.setToolTip("Kéo để di chuyển · Nhấp đúp để ẩn/hiện thanh công cụ.")
        layout.addWidget(logo)
        layout.addSpacing(6)

        self.pin_button = BarButton("pin")
        self.pin_button.setAccessibleName("Ghim khung dịch")
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(self.config.hud_pinned)
        self.pin_button.toggled.connect(self._set_pinned)
        layout.addWidget(self.pin_button)
        layout.addWidget(self._bar_separator())

        self._action_btns: dict[str, BarButton] = {}
        self._add_action_group(layout, BAR_GROUP_OVERLAY)
        layout.addWidget(self._bar_separator())
        self._add_action_group(layout, BAR_GROUP_CLIPBOARD)
        layout.addWidget(self._bar_separator())
        self._add_action_group(layout, BAR_GROUP_FRAME)
        layout.addWidget(self._bar_separator())

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

        self.service_combo = QComboBox()
        self.service_combo.setObjectName("barCombo")
        self.service_combo.setAccessibleName("Dịch vụ dịch")
        self.service_combo.setToolTip("Chọn dịch vụ dịch")
        self.service_combo.setMinimumWidth(104)
        self.service_combo.setMaximumWidth(196)
        for label, key in self._service_entries():
            self.service_combo.addItem(label, key)

        self.target_combo = QComboBox()
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
        layout.addWidget(self.service_combo)
        layout.addWidget(self.target_combo)
        layout.addWidget(self._bar_separator())

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

        shadow = QGraphicsDropShadowEffect(bar)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 150))
        bar.setGraphicsEffect(shadow)

        self.refresh_bar_tooltips()
        self._sync_pin_tooltip()
        self._sync_output_actions()
        return bar

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

    def _add_action_group(self, layout: QHBoxLayout, group: list) -> None:
        for kind, label, action, _tooltip in group:
            button = BarButton(kind)
            button.setAccessibleName(label)
            button.setCheckable(action in ("region_to_live", "region_to_live_frame"))
            button.clicked.connect(
                lambda _checked=False, current=action: self.workflow.handle_action(
                    current
                )
            )
            self._action_btns[action] = button
            layout.addWidget(button)

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
        self.apply_hud_text_style()
        layout.addWidget(self.output, 1)
        return display

    def _copy_output(self) -> None:
        text = self.output.text().strip()
        if not text:
            self.set_status("Khung dịch đang trống.", "error")
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            self.set_status("Không truy cập được clipboard.", "error")
            return
        clipboard.setText(text)
        self.set_status("Đã copy bản dịch vào clipboard.", "ok")

    def _clear_output(self) -> None:
        if not self.output.text():
            return
        self.set_output("")
        self.set_status("Đã xoá khung dịch.", "ready")

    def _sync_output_actions(self) -> None:
        """Copy/Xoá chỉ bấm được khi trong khung đang có bản dịch."""
        has_text = bool(self.output.text().strip()) if hasattr(self, "output") else False
        for button in (self.copy_button, self.clear_button):
            button.setEnabled(has_text)

    def _sync_placeholder(self) -> None:
        """Gợi ý trong khung trống: nói rõ vùng này để làm gì + phím tắt."""
        if not hasattr(self, "output"):
            return
        hotkey = _fmt_hotkey(self.config.hotkeys.get("region_to_text", ""))
        suffix = f" · {hotkey}" if hotkey != "Tắt" else ""
        self.output.set_placeholder(f"Bản dịch hiện ở đây{suffix}")

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
            button = self._action_btns.get(action)
            if button is not None:
                hotkey = _fmt_hotkey(self.config.hotkeys.get(action, ""))
                button.setToolTip(f"{label} · {tooltip}\nPhím tắt: {hotkey}")
        self._sync_placeholder()

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
                lambda: self.bridge.run.emit(self.workflow.dismiss_all_overlays)
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
        for action, button in self._action_btns.items():
            if action not in ("region_to_live", "region_to_live_frame"):
                button.setEnabled(not busy)
        self.target_combo.setEnabled(not busy)
        self.service_combo.setEnabled(not busy)
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
            ):
                control.setEnabled(not busy)
            if not busy:
                self._settings_win._update_engine_info()

    def set_output(self, text: str) -> None:
        self.output.setText(text)
        self._sync_output_actions()

    def ensure_visible(self) -> None:
        if not self.isVisible() or self.isMinimized():
            _bring_to_front(self)
        else:
            self.raise_()

    def set_live_action_checked(self, action: str, checked: bool) -> None:
        button = self._action_btns.get(action)
        if button is not None:
            button.setChecked(checked)

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
