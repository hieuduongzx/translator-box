"""Điều phối capture, OCR, dịch và live translation."""

from __future__ import annotations

import os
import tempfile
import threading
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

import overlay
import services
from desktop_apps import foreground_application_id
from ui_utils import _sig_differs

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
    focus_application_id: str = ""
    focus_application_label: str = ""
    stop_event: threading.Event = field(default_factory=threading.Event)
    token: object = field(default_factory=object)
    thread: threading.Thread | None = None
    # Bản dịch đã lấy trong phiên này, theo đúng chuỗi gốc. Live chụp lại cùng
    # một vùng nên phần lớn dòng không đổi giữa các frame; không có memo thì mỗi
    # frame lại bắn một request mạng cho đúng câu vừa dịch xong.
    translations: dict[str, str] = field(default_factory=dict)


# Giới hạn memo của một phiên live để phiên dài không phình bộ nhớ.
_LIVE_TRANSLATION_MEMO_LIMIT = 512


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

    def set_live_focus_application(
        self, application_id: str, application_label: str
    ) -> None:
        application_id = application_id.strip().casefold()
        application_label = application_label.strip()
        self.hud.config.live_focus_app_id = application_id
        self.hud.config.live_focus_app_label = application_label
        self.hud.config.save()
        if self._live is not None:
            self._live.focus_application_id = application_id
            self._live.focus_application_label = application_label
        if application_id:
            self.hud.set_status(
                f"Live chỉ dịch khi đang focus: {application_label}.", "ok"
            )
        elif self._live is not None:
            self._set_live_status(self._live.mode)
        else:
            self.hud.set_status("Live sẽ dịch trên mọi ứng dụng.", "ready")

    def _options(self) -> TranslationOptions:
        config = self.hud.config
        service, endpoint, api_key, model = config.resolve_llm()
        return TranslationOptions(
            language=config.ocr_language,
            engine=config.ocr_engine,
            model=config.ocr_model,
            backend=config.ocr_backend if config.ocr_acceleration else "cpu",
            target=config.target_language,
            service=service,
            llm_endpoint=endpoint,
            llm_api_key=api_key,
            llm_model=model,
        )

    def _emit(self, callback) -> None:
        self.hud.bridge.run.emit(callback)

    def _capture_settle_delay(self) -> float:
        """Thời gian chờ trước khi chụp, sau khi overlay chọn vùng vừa đóng.

        Khi Windows hỗ trợ `WDA_EXCLUDEFROMCAPTURE` (Win10 2004+) thì cửa sổ của
        app không bao giờ xuất hiện trong ảnh chụp, nên chỉ cần một nhịp frame để
        desktop bên dưới vẽ lại. Máy không hỗ trợ mới cần chờ lâu để cửa sổ thật
        sự biến mất khỏi màn hình.
        """
        return 0.03 if getattr(self.hud, "_capture_excluded", False) else 0.15

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

    @staticmethod
    def _ocr_lines(image_path: str, options: TranslationOptions):
        """OCR và gom các dòng gần nhau thành speech bubble/khối ngữ cảnh."""
        return services.merge_regions_into_blocks(
            services.ocr_layout(
                image_path,
                options.language,
                options.engine,
                options.model,
                options.backend,
            )
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
            "clipboard_image_replace": self._translate_clipboard_image_replace,
            "clipboard_image_to_text": self._translate_clipboard_image_to_text,
            "selected_text_replace": self._translate_selected_text_replace,
            "region_to_text": self.start_region_capture,
            "region_to_overlay": self.start_region_overlay,
        }
        handler = actions.get(action)
        if handler is not None:
            handler()

    def translate_clipboard_text(self, text: str) -> None:
        """Dịch văn bản vừa được copy vào khung (chế độ tự dịch clipboard).

        Được gọi từ HUD khi clipboard đổi nội dung dạng văn bản; không cần phím
        tắt riêng vì Ctrl+C của người dùng chính là thao tác kích hoạt.
        """
        text = (text or "").strip()
        if not text:
            return
        self._set_busy(True)
        self.hud.set_status("Đang dịch văn bản vừa copy…", "busy")
        options = self._options()

        def job() -> tuple[str, str]:
            self._emit(self._show_source_pending)
            return text, self._translate_text(text, options)

        self._run_text_worker(job)

    def _translate_clipboard_image_replace(self) -> None:
        """OCR ảnh clipboard, xoá chữ gốc và hiện ảnh đã chèn bản dịch."""
        self._set_busy(True)
        self.hud.set_status("Đang đọc ảnh từ clipboard…", "busy")
        options = self._options()
        image_path = self._new_temp_image()
        try:
            self._save_clipboard_image(image_path)
        except Exception as exc:  # noqa: BLE001
            self._remove_temp_image(image_path)
            self._apply_error(str(exc))
            return

        self.hud.set_status("Đang nhận dạng chữ trong ảnh…", "busy")

        def runner() -> None:
            try:
                regions = self._ocr_lines(image_path, options)
                if not regions:
                    raise RuntimeError("Không nhận diện được chữ trong ảnh clipboard.")
                translated_lines = self._translate_regions(regions, options)
                image_size, visuals = services.reconstruct_layout(image_path, regions)
                paint_regions = self._paint_regions(regions, translated_lines, visuals)
                source = QImage(image_path)
                if source.isNull():
                    raise RuntimeError("Không đọc được ảnh nguồn từ clipboard.")
                self._emit(
                    lambda: self._apply_clipboard_translated_image(
                        source, paint_regions, image_size
                    )
                )
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                self._emit(lambda: self._apply_error(message))
            finally:
                self._remove_temp_image(image_path)

        threading.Thread(target=runner, daemon=True).start()

    def _translate_clipboard_image_to_text(self) -> None:
        """OCR ảnh clipboard, dịch từng dòng và đưa text vào khung HUD."""
        self._set_busy(True)
        self.hud.set_status("Đang đọc ảnh từ clipboard…", "busy")
        options = self._options()
        image_path = self._new_temp_image()
        try:
            self._save_clipboard_image(image_path)
        except Exception as exc:  # noqa: BLE001
            self._remove_temp_image(image_path)
            self._apply_error(str(exc))
            return

        self.hud.set_status("Đang nhận dạng chữ trong ảnh…", "busy")

        def job() -> tuple[str, str]:
            try:
                regions = self._ocr_lines(image_path, options)
                if not regions:
                    raise RuntimeError("Không nhận diện được chữ trong ảnh clipboard.")
                self._emit(self._show_source_pending)
                translated_lines = self._translate_regions(regions, options)
                source = "\n".join(region.text for region in regions)
                return source, "\n".join(translated_lines)
            finally:
                self._remove_temp_image(image_path)

        self._run_text_worker(job)

    def _translate_selected_text_replace(self) -> None:
        """Dịch văn bản đang bôi đen rồi DÁN ĐÈ tại chỗ (thay input của app khác).

        Không đưa HUD lên trước khi dán — nếu HUD giành focus thì Ctrl+V sẽ rơi
        vào HUD thay vì ô nhập của người dùng (Discord…).
        """
        self._set_busy(True)
        self.hud.set_status("Đang lấy văn bản chọn…", "busy")
        # Dùng ngôn ngữ đích RIÊNG của chức năng thay thế (không chung với target chung).
        options = replace(
            self._options(), target=self.hud.config.replace_target_language
        )

        def job() -> tuple[str, str]:
            original_clipboard = services.read_clipboard()
            source = services.copy_selected_text()
            self._emit(lambda: self.hud.set_status("Đang dịch để thay thế…", "busy"))
            translated = self._translate_text(source, options)
            services.paste_replacement(translated, restore=original_clipboard)
            return source, translated

        self._run_text_worker(job, on_success=self._apply_replaced)

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

    def _capture_to_frame(self, bbox, hidden_overlays: list) -> None:
        options = self._options()
        settle = self._capture_settle_delay()

        def job() -> tuple[str, str]:
            time.sleep(settle)
            image_path = self._new_temp_image()
            restored = False
            try:
                services.capture(bbox, image_path)
                self._emit(
                    lambda: self._restore_after_capture(hidden_overlays, show_hud=True)
                )
                restored = True
                regions = self._ocr_lines(image_path, options)
                if not regions:
                    raise RuntimeError("Không nhận diện được chữ.")
                self._emit(lambda: self._show_source_pending())
                translated_lines = self._translate_regions(regions, options)
                source = "\n".join(region.text for region in regions)
                return source, "\n".join(translated_lines)
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
        settle = self._capture_settle_delay()

        def runner() -> None:
            image_path = self._new_temp_image()
            restored = False
            try:
                time.sleep(settle)
                services.capture(bbox, image_path)
                self._emit(
                    lambda: self._restore_after_capture(hidden_overlays, show_hud=False)
                )
                restored = True
                regions = self._ocr_lines(image_path, options)
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
                visual.ink_rect,
                visual.stroke_thickness,
                getattr(region, "line_count", 1),
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
        # Overlay vẽ bản dịch ĐÈ TẠI CHỖ trên màn hình → không đổ vào khung HUD.
        self._set_busy(False)
        overlay.show_translation(bbox, paint_regions, image_size)
        self.hud.set_status("Overlay sẵn sàng — trái đóng ô · phải xoá hết.", "ok")

    def _finish_overlay_error(self, message: str) -> None:
        self._set_busy(False)
        self.hud.set_output(f"⚠ {message}")
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
            focus_application_id=self.hud.config.live_focus_app_id,
            focus_application_label=self.hud.config.live_focus_app_label,
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
        target = "khung" if mode == "frame" else "overlay"
        self.hud.set_status(
            f"● LIVE ({target}) — bấm lại trên bar hoặc phím tắt để dừng.", "busy"
        )

    def _live_loop(self, session: LiveSession) -> None:
        image_path = self._new_temp_image()
        previous_signature = None
        paused_for = ""
        try:
            while not session.stop_event.is_set():
                required_application = session.focus_application_id
                if (
                    required_application
                    and foreground_application_id() != required_application
                ):
                    if paused_for != required_application:
                        label = session.focus_application_label or "ứng dụng đã chọn"
                        self._emit(
                            lambda current_label=label: (
                                self._live_focus_paused_if_current(
                                    session.token, current_label
                                )
                            )
                        )
                    paused_for = required_application
                    session.stop_event.wait(max(0.05, session.interval_seconds))
                    continue
                if paused_for:
                    paused_for = ""
                    previous_signature = None
                    self._emit(
                        lambda: self._live_focus_resumed_if_current(session.token)
                    )
                started_at = time.perf_counter()
                try:
                    signature = services.capture(session.bbox, image_path)
                    if _sig_differs(previous_signature, signature):
                        previous_signature = signature
                        self._live_process(session, image_path)
                except Exception as exc:  # noqa: BLE001
                    message = str(exc)
                    self._emit(
                        lambda: self._live_error_if_current(session.token, message)
                    )
                elapsed = time.perf_counter() - started_at
                # Một frame nặng (OCR + dịch qua mạng + inpaint) dễ vượt cả chu kỳ.
                # Sàn cũ 0,05 s khiến vòng lặp chạy gần như liên tục và ghim CPU
                # suốt phiên; luôn nghỉ ít nhất một phần tư chu kỳ để máy thở.
                idle = max(
                    session.interval_seconds - elapsed, session.interval_seconds * 0.25
                )
                session.stop_event.wait(idle)
        finally:
            self._remove_temp_image(image_path)

    def _live_process(self, session: LiveSession, image_path: str) -> None:
        options = session.options
        regions = self._ocr_lines(image_path, options)
        if not regions:
            return
        translated_lines = self._live_translate(session, regions)
        if session.mode == "frame":
            translated = "\n".join(translated_lines)
            self._emit(lambda: self._live_apply_frame(session.token, translated))
            return
        image_size, visuals = services.reconstruct_layout(image_path, regions)
        paint_regions = self._paint_regions(regions, translated_lines, visuals)
        self._emit(
            lambda: self._live_apply_overlay(
                session.token, session.bbox, paint_regions, image_size
            )
        )

    def _live_translate(self, session: LiveSession, regions) -> list[str]:
        """Dịch các dòng của một frame live, tái dùng bản dịch đã có."""
        memo = session.translations
        pending = [region for region in regions if region.text not in memo]
        if pending:
            fresh = self._translate_regions(pending, session.options)
            if len(memo) > _LIVE_TRANSLATION_MEMO_LIMIT:
                memo.clear()
            for region, translated in zip(pending, fresh):
                memo[region.text] = translated
        return [memo.get(region.text, region.text) for region in regions]

    def _is_current(self, token: object) -> bool:
        return self._live is not None and self._live.token is token

    def _live_focus_matches(self, session: LiveSession) -> bool:
        return (
            not session.focus_application_id
            or foreground_application_id() == session.focus_application_id
        )

    def _live_focus_paused_if_current(self, token: object, label: str) -> None:
        if not self._is_current(token):
            return
        if self._live_overlay is not None:
            self._live_overlay.hide()
        self.hud.set_status(f"● LIVE TẠM DỪNG — chờ focus: {label}.", "busy")

    def _live_focus_resumed_if_current(self, token: object) -> None:
        if self._is_current(token) and self._live is not None:
            self._set_live_status(self._live.mode)

    def _live_apply_overlay(
        self, token: object, bbox, paint_regions, image_size
    ) -> None:
        if not self._is_current(token) or self._live is None:
            return
        if not self._live_focus_matches(self._live):
            label = self._live.focus_application_label or "ứng dụng đã chọn"
            self._live_focus_paused_if_current(token, label)
            return
        if self._live_overlay is None:
            widget = overlay.show_translation(bbox, paint_regions, image_size)
            widget.set_live(True)
            self._live_overlay = widget
        else:
            self._live_overlay.update_content(paint_regions, image_size)
            self._live_overlay.show()
        self._set_live_status("overlay")

    def _live_apply_frame(self, token: object, translated: str) -> None:
        if not self._is_current(token) or self._live is None:
            return
        if not self._live_focus_matches(self._live):
            label = self._live.focus_application_label or "ứng dụng đã chọn"
            self._live_focus_paused_if_current(token, label)
            return
        self.hud.set_output(translated)
        self._set_live_status("frame")

    def _live_error_if_current(self, token: object, message: str) -> None:
        if self._is_current(token):
            self.hud.set_output(f"⚠ {message}")
            self.hud.set_status(f"Live: {message}", "error")

    def stop_live(self, message: str = "Đã dừng live.") -> None:
        session, self._live = self._live, None
        if session is not None:
            session.stop_event.set()
        if self._live_overlay is not None:
            self._live_overlay.close()
            self._live_overlay = None
        for action in ("region_to_live", "region_to_live_frame"):
            self.hud.set_live_action_checked(action, False)
        self.hud.set_status(message, "ready")

    def dismiss_transient_overlays(self) -> None:
        overlay.close_all_translations(include_live=False)

    def shutdown(self) -> None:
        if self.live_running:
            self.stop_live("Đang thoát…")

    def _run_text_worker(self, job, on_success=None) -> None:
        handler = on_success or self._apply_result

        def runner() -> None:
            try:
                _source, translated = job()
                self._emit(lambda: handler(translated))
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

    def _apply_replaced(self, _translated: str) -> None:
        # Thay chữ TRỰC TIẾP trong ô nhập của app đích → không đổ vào khung HUD,
        # cũng không ensure_visible (giữ focus ở app đích sau khi dán đè).
        self._set_busy(False)
        self.hud.set_status("Đã thay thế bằng bản dịch tại chỗ.", "ok")

    def _apply_clipboard_translated_image(
        self, source: QImage, paint_regions, image_size: tuple[int, int]
    ) -> None:
        try:
            image = overlay.render_translated_image(source, paint_regions, image_size)
        except Exception as exc:  # noqa: BLE001
            self._apply_error(str(exc))
            return
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setImage(image)
        self.hud.set_output_image(image)
        self._set_busy(False)
        self.hud.ensure_visible()
        self.hud.set_status(
            "Ảnh dịch đang hiện trong khung và đã copy vào clipboard.", "ok"
        )

    def _apply_error(self, message: str) -> None:
        self._set_busy(False)
        self.hud.set_output(f"⚠ {message}")
        self.hud.ensure_visible()
        self.hud.set_status(message, "error")

    @staticmethod
    def _save_clipboard_image(path: str) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is None:
            raise RuntimeError("Không truy cập được clipboard.")
        image = clipboard.image()
        if image.isNull():
            raise RuntimeError(
                "Clipboard không có ảnh. Hãy copy ảnh hoặc chụp bằng Win+Shift+S."
            )
        if not image.save(path, "PNG"):
            raise RuntimeError("Không đọc được ảnh từ clipboard.")

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
