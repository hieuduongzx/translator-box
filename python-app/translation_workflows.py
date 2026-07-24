"""Điều phối capture, OCR, dịch và live translation."""

from __future__ import annotations

import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from PySide6.QtWidgets import QApplication

import overlay
import services
from ui_utils import _image_signature, _sig_differs

if TYPE_CHECKING:
    from hud_window import HUDWindow

TranslationMode = Literal["overlay", "frame"]


@dataclass(frozen=True)
class TranslationOptions:
    """Snapshot cấu hình để worker không đọc state UI đang thay đổi."""

    language: str
    engine: str
    model: str
    backend: str
    target: str
    service: str
    llm_endpoint: str
    llm_api_key: str
    llm_model: str


@dataclass
class LiveSession:
    """State có kiểu rõ ràng của một phiên live."""

    bbox: tuple[int, int, int, int]
    mode: TranslationMode
    options: TranslationOptions
    interval_seconds: float
    action: str
    stop_event: threading.Event = field(default_factory=threading.Event)
    token: object = field(default_factory=object)
    thread: threading.Thread | None = None


class TranslationWorkflowController:
    """Use-case controller; không chứa code dựng giao diện HUD."""

    def __init__(self, hud: "HUDWindow") -> None:
        self.hud = hud
        self._busy = False
        self._live: LiveSession | None = None
        self._live_overlay: overlay.TranslationOverlay | None = None

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def live_running(self) -> bool:
        return self._live is not None

    def _options(self) -> TranslationOptions:
        config = self.hud.config
        return TranslationOptions(
            language=config.ocr_language,
            engine=config.ocr_engine,
            model=config.ocr_model,
            backend=config.ocr_backend if config.ocr_acceleration else "cpu",
            target=config.target_language,
            service=config.translator,
            llm_endpoint=config.llm_endpoint,
            llm_api_key=config.llm_api_key,
            llm_model=config.llm_model,
        )

    def _emit(self, callback) -> None:
        self.hud.bridge.run.emit(callback)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.hud.set_busy(busy)

    @staticmethod
    def _translate_text(text: str, options: TranslationOptions) -> str:
        return services.translate(
            text,
            options.target,
            options.service,
            llm_endpoint=options.llm_endpoint,
            llm_api_key=options.llm_api_key,
            llm_model=options.llm_model,
        )

    @staticmethod
    def _translate_regions(regions, options: TranslationOptions) -> list[str]:
        return services.translate_regions(
            regions,
            options.target,
            options.service,
            llm_endpoint=options.llm_endpoint,
            llm_api_key=options.llm_api_key,
            llm_model=options.llm_model,
        )

    def handle_action(self, action: str) -> None:
        if action == "quit":
            self.hud.quit_app()
            return
        if action in ("region_to_live", "region_to_live_frame"):
            if self.live_running:
                self.stop_live()
            elif not self.busy:
                mode: TranslationMode = (
                    "frame" if action == "region_to_live_frame" else "overlay"
                )
                self.start_live(mode, action)
            return
        if self.busy:
            return
        actions = {
            "selected_text": self._translate_selected_text,
            "region_to_text": self.start_region_capture,
            "region_to_overlay": self.start_region_overlay,
            "fullscreen": self.start_fullscreen_capture,
        }
        handler = actions.get(action)
        if handler is not None:
            handler()

    def _translate_selected_text(self) -> None:
        self._set_busy(True)
        self.hud.set_status("Đang lấy văn bản chọn…", "busy")
        options = self._options()

        def job() -> tuple[str, str]:
            source = services.copy_selected_text()
            self._emit(lambda: self._show_source_pending())
            return source, self._translate_text(source, options)

        self._run_text_worker(job)

    def start_region_capture(self) -> None:
        self._set_busy(True)
        self.hud.set_status("Kéo để chọn vùng · Esc huỷ", "busy")
        hidden_overlays = overlay.hide_translations_for_capture()
        self.hud.hide()
        QApplication.processEvents()
        bbox = overlay.select_region(self.hud)
        if not bbox:
            overlay.restore_translations(hidden_overlays)
            self.hud.ensure_visible()
            self._set_busy(False)
            self.hud.set_status("Đã huỷ.", "ready")
            return
        self._capture_to_frame(bbox, hidden_overlays)

    def start_fullscreen_capture(self) -> None:
        self._set_busy(True)
        self.hud.set_status("Đang OCR toàn màn hình…", "busy")
        hidden_overlays = overlay.hide_translations_for_capture()
        self.hud.hide()
        QApplication.processEvents()
        self._capture_to_frame(services.full_screen_bbox(), hidden_overlays)

    def _capture_to_frame(self, bbox, hidden_overlays: list) -> None:
        options = self._options()

        def job() -> tuple[str, str]:
            time.sleep(0.15)
            image_path = self._new_temp_image()
            restored = False
            try:
                services.capture(bbox, image_path)
                self._emit(
                    lambda: self._restore_after_capture(hidden_overlays, show_hud=True)
                )
                restored = True
                source = services.ocr_text_reflow(
                    image_path,
                    options.language,
                    options.engine,
                    options.model,
                    options.backend,
                )
                if not source:
                    raise RuntimeError("Không nhận diện được chữ.")
                self._emit(lambda: self._show_source_pending())
                translated = self._translate_text(source, options)
                return source, translated
            finally:
                if not restored:
                    self._emit(
                        lambda: self._restore_after_capture(
                            hidden_overlays, show_hud=True
                        )
                    )
                self._remove_temp_image(image_path)

        self._run_text_worker(job)

    def start_region_overlay(self) -> None:
        self._set_busy(True)
        self.hud.set_status("Kéo để chọn vùng · Esc huỷ", "busy")
        hidden_overlays = overlay.hide_translations_for_capture()
        QApplication.processEvents()
        bbox = overlay.select_region(self.hud)
        if not bbox:
            overlay.restore_translations(hidden_overlays)
            self._set_busy(False)
            self.hud.set_status("Đã huỷ.", "ready")
            return
        options = self._options()

        def runner() -> None:
            image_path = self._new_temp_image()
            restored = False
            try:
                time.sleep(0.15)
                services.capture(bbox, image_path)
                self._emit(
                    lambda: self._restore_after_capture(hidden_overlays, show_hud=False)
                )
                restored = True
                regions = services.merge_regions_into_lines(
                    services.ocr_layout(
                        image_path,
                        options.language,
                        options.engine,
                        options.model,
                        options.backend,
                    )
                )
                if not regions:
                    raise RuntimeError("Không nhận diện được chữ.")
                translated_lines = self._translate_regions(regions, options)
                image_size, visuals = services.reconstruct_layout(image_path, regions)
                paint_regions = self._paint_regions(regions, translated_lines, visuals)
                translated = "\n".join(translated_lines)
                self._emit(
                    lambda: self._apply_overlay(
                        translated, bbox, paint_regions, image_size
                    )
                )
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                self._emit(lambda: self._finish_overlay_error(message))
            finally:
                if not restored:
                    self._emit(
                        lambda: self._restore_after_capture(
                            hidden_overlays, show_hud=False
                        )
                    )
                self._remove_temp_image(image_path)

        threading.Thread(target=runner, daemon=True).start()

    @staticmethod
    def _paint_regions(regions, translated_lines, visuals):
        return [
            overlay.OverlayRegion(
                region.bbox,
                translated_text,
                visual.bg,
                visual.fg,
                visual.rect,
                visual.patch_rgb,
                visual.patch_size,
            )
            for region, translated_text, visual in zip(
                regions, translated_lines, visuals
            )
        ]

    def _restore_after_capture(self, hidden_overlays, show_hud: bool) -> None:
        overlay.restore_translations(hidden_overlays)
        if show_hud:
            self.hud.ensure_visible()

    def _apply_overlay(self, translated, bbox, paint_regions, image_size) -> None:
        self._set_busy(False)
        self.hud.set_output(translated)
        overlay.show_translation(bbox, paint_regions, image_size)
        self.hud.set_status("Overlay sẵn sàng — trái đóng ô · phải xoá hết.", "ok")

    def _finish_overlay_error(self, message: str) -> None:
        self._set_busy(False)
        self.hud.ensure_visible()
        self.hud.set_status(message, "error")

    def start_live(self, mode: TranslationMode, action: str) -> None:
        self.hud.set_status("Kéo để chọn vùng live · Esc huỷ", "busy")
        hidden_overlays = overlay.hide_translations_for_capture()
        QApplication.processEvents()
        bbox = overlay.select_region(self.hud)
        overlay.restore_translations(hidden_overlays)
        if not bbox:
            self.hud.set_live_action_checked(action, False)
            self.hud.set_status("Đã huỷ.", "ready")
            return
        session = LiveSession(
            bbox=bbox,
            mode=mode,
            options=self._options(),
            interval_seconds=self.hud.config.live_interval_ms / 1000.0,
            action=action,
        )
        self._live = session
        self._live_overlay = None
        self.hud.set_live_action_checked(action, True)
        if mode == "frame":
            self.hud.ensure_visible()
        self._set_live_status(mode)
        session.thread = threading.Thread(
            target=self._live_loop, args=(session,), daemon=True
        )
        session.thread.start()

    def _set_live_status(self, mode: TranslationMode) -> None:
        if mode == "frame":
            text = "● LIVE (khung) — chuột phải/Esc hoặc phím tắt để dừng."
        else:
            text = "● LIVE — chuột phải/Esc hoặc bấm phím tắt để dừng."
        self.hud.set_status(text, "busy")

    def _live_loop(self, session: LiveSession) -> None:
        image_path = self._new_temp_image()
        previous_signature = None
        try:
            while not session.stop_event.is_set():
                started_at = time.perf_counter()
                try:
                    services.capture(session.bbox, image_path)
                    signature = _image_signature(image_path)
                    if _sig_differs(previous_signature, signature):
                        previous_signature = signature
                        self._live_process(session, image_path)
                except Exception as exc:  # noqa: BLE001
                    message = str(exc)
                    self._emit(
                        lambda: self._live_error_if_current(session.token, message)
                    )
                elapsed = time.perf_counter() - started_at
                session.stop_event.wait(max(0.05, session.interval_seconds - elapsed))
        finally:
            self._remove_temp_image(image_path)

    def _live_process(self, session: LiveSession, image_path: str) -> None:
        options = session.options
        if session.mode == "frame":
            source = services.ocr_text_reflow(
                image_path,
                options.language,
                options.engine,
                options.model,
                options.backend,
            )
            if source:
                translated = self._translate_text(source, options)
                self._emit(lambda: self._live_apply_frame(session.token, translated))
            return
        regions = services.merge_regions_into_lines(
            services.ocr_layout(
                image_path,
                options.language,
                options.engine,
                options.model,
                options.backend,
            )
        )
        if not regions:
            return
        translated_lines = self._translate_regions(regions, options)
        image_size, visuals = services.reconstruct_layout(image_path, regions)
        paint_regions = self._paint_regions(regions, translated_lines, visuals)
        self._emit(
            lambda: self._live_apply_overlay(
                session.token, session.bbox, paint_regions, image_size
            )
        )

    def _is_current(self, token: object) -> bool:
        return self._live is not None and self._live.token is token

    def _live_apply_overlay(
        self, token: object, bbox, paint_regions, image_size
    ) -> None:
        if not self._is_current(token):
            return
        if self._live_overlay is None:
            widget = overlay.show_translation(bbox, paint_regions, image_size)
            widget.set_live(True)
            widget.dismiss_callback = self.stop_live
            self._live_overlay = widget
        else:
            self._live_overlay.update_content(paint_regions, image_size)
        self._set_live_status("overlay")

    def _live_apply_frame(self, token: object, translated: str) -> None:
        if self._is_current(token):
            self.hud.set_output(translated)
            self._set_live_status("frame")

    def _live_error_if_current(self, token: object, message: str) -> None:
        if self._is_current(token):
            self.hud.set_status(f"Live: {message}", "error")

    def stop_live(self, message: str = "Đã dừng live.") -> None:
        session, self._live = self._live, None
        if session is not None:
            session.stop_event.set()
        if self._live_overlay is not None:
            self._live_overlay.dismiss_callback = None
            self._live_overlay.close()
            self._live_overlay = None
        for action in ("region_to_live", "region_to_live_frame"):
            self.hud.set_live_action_checked(action, False)
        self.hud.set_status(message, "ready")

    def dismiss_all_overlays(self) -> None:
        if self.live_running:
            self.stop_live()
        overlay.close_all_translations()

    def shutdown(self) -> None:
        if self.live_running:
            self.stop_live("Đang thoát…")

    def _run_text_worker(self, job) -> None:
        def runner() -> None:
            try:
                _source, translated = job()
                self._emit(lambda: self._apply_result(translated))
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                self._emit(lambda: self._apply_error(message))

        threading.Thread(target=runner, daemon=True).start()

    def _show_source_pending(self) -> None:
        self.hud.set_status("Đang dịch…", "busy")
        self.hud.ensure_visible()

    def _apply_result(self, translated: str) -> None:
        self.hud.set_output(translated)
        self._set_busy(False)
        self.hud.set_status("Đã dịch.", "ok")
        self.hud.ensure_visible()

    def _apply_error(self, message: str) -> None:
        self._set_busy(False)
        self.hud.ensure_visible()
        self.hud.set_status(message, "error")

    @staticmethod
    def _new_temp_image() -> str:
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        handle.close()
        return handle.name

    @staticmethod
    def _remove_temp_image(path: str) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass
