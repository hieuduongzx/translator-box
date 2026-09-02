"""Thu microphone/audio hệ thống và stream tới Soniox STT realtime."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
import pyaudiowpatch as pyaudio

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import (
    QAudio,
    QAudioDevice,
    QAudioFormat,
    QAudioSource,
    QMediaDevices,
)
from PySide6.QtWebSockets import QWebSocket, QWebSocketProtocol

SONIOX_WEBSOCKET_URL = "wss://stt-rt.soniox.com/transcribe-websocket"
SONIOX_MODEL = "stt-rt-v5"
_MAX_PENDING_AUDIO_BYTES = 1_048_576


@dataclass(frozen=True)
class TranscriptBlock:
    """Một khối liên tiếp cùng speaker, ngôn ngữ và loại token."""

    kind: str
    text: str
    language: str | None
    speaker: str | None
    is_final: bool


@dataclass
class TranscriptBuffer:
    """Tích lũy token final và thay thế toàn bộ token non-final mỗi response."""

    final_tokens: list[dict[str, Any]] = field(default_factory=list)
    non_final_tokens: list[dict[str, Any]] = field(default_factory=list)

    def clear(self) -> None:
        self.final_tokens.clear()
        self.non_final_tokens.clear()

    def ingest(self, tokens: list[dict[str, Any]]) -> None:
        non_final: list[dict[str, Any]] = []
        for token in tokens:
            if not isinstance(token, dict):
                continue
            text = str(token.get("text") or "")
            if not text or text.strip() == "<end>":
                continue
            if token.get("is_final"):
                self.final_tokens.append(token)
            else:
                non_final.append(token)
        self.non_final_tokens = non_final

    def blocks(self) -> tuple[TranscriptBlock, ...]:
        """Nhóm unified token stream mà không làm mất lời gốc hoặc bản dịch."""
        blocks: list[TranscriptBlock] = []
        current_speaker: str | None = None
        for token in self.final_tokens + self.non_final_tokens:
            text = str(token.get("text") or "")
            if not text:
                continue
            speaker_value = token.get("speaker")
            if speaker_value is not None:
                current_speaker = str(speaker_value)
            kind = (
                "translation"
                if token.get("translation_status") == "translation"
                else "speech"
            )
            language_value = token.get("language") or token.get("source_language")
            language = str(language_value) if language_value else None
            is_final = bool(token.get("is_final"))
            if (
                blocks
                and blocks[-1].kind == kind
                and blocks[-1].language == language
                and blocks[-1].speaker == current_speaker
            ):
                previous = blocks[-1]
                blocks[-1] = TranscriptBlock(
                    kind=kind,
                    text=previous.text + text,
                    language=language,
                    speaker=current_speaker,
                    is_final=previous.is_final and is_final,
                )
            else:
                blocks.append(
                    TranscriptBlock(
                        kind=kind,
                        text=text.lstrip(),
                        language=language,
                        speaker=current_speaker,
                        is_final=is_final,
                    )
                )
        return tuple(block for block in blocks if block.text.strip())

    def render(self) -> str:
        """Hiển thị transcript và bản dịch, phân khối theo speaker/language."""
        parts: list[str] = []
        current_speaker: str | None = None
        current_mode: str | None = None
        current_language: str | None = None
        at_line_start = True

        for token in self.final_tokens + self.non_final_tokens:
            text = str(token.get("text", ""))
            speaker = token.get("speaker")
            if speaker is not None:
                speaker = str(speaker)
            elif current_speaker is not None:
                speaker = current_speaker
            mode = (
                "translation"
                if token.get("translation_status") == "translation"
                else "speech"
            )
            language = token.get("language") or token.get("source_language")
            language = str(language) if language else None

            if speaker is not None and speaker != current_speaker:
                if parts:
                    parts.append("\n\n")
                parts.append(f"NGƯỜI NÓI {speaker}")
                current_speaker = speaker
                current_mode = None
                current_language = None
                at_line_start = False

            if mode != current_mode or language != current_language:
                if parts and not at_line_start:
                    parts.append("\n")
                label = "BẢN DỊCH" if mode == "translation" else "LỜI NÓI"
                suffix = f" [{language}]" if language else ""
                parts.append(f"{label}{suffix}: ")
                current_mode = mode
                current_language = language
                text = text.lstrip()
                at_line_start = False

            parts.append(text)
            at_line_start = text.endswith("\n")

        if self.non_final_tokens and parts:
            parts.append(" ▌")
        return "".join(parts).strip()


def build_session_config(
    api_key: str,
    audio_format: QAudioFormat,
    *,
    translation_mode: str,
    target_language: str,
    language_a: str,
    language_b: str,
    speaker_diarization: bool,
) -> dict[str, Any]:
    """Tạo start request đúng hợp đồng WebSocket Soniox cho raw PCM từ Qt."""
    key = api_key.strip()
    if not key:
        raise ValueError("Chưa nhập Soniox API key.")

    sample_formats = {
        QAudioFormat.SampleFormat.UInt8: "pcm_u8",
        QAudioFormat.SampleFormat.Int16: "pcm_s16le",
        QAudioFormat.SampleFormat.Int32: "pcm_s32le",
        QAudioFormat.SampleFormat.Float: "pcm_f32le",
    }
    encoding = sample_formats.get(audio_format.sampleFormat())
    if encoding is None:
        raise ValueError("Định dạng microphone không được Soniox hỗ trợ.")

    config: dict[str, Any] = {
        "api_key": key,
        "model": SONIOX_MODEL,
        "audio_format": encoding,
        "sample_rate": audio_format.sampleRate(),
        "num_channels": audio_format.channelCount(),
        "enable_language_identification": True,
        "enable_speaker_diarization": bool(speaker_diarization),
        "enable_endpoint_detection": True,
        "max_endpoint_delay_ms": 1200,
    }
    if translation_mode == "one_way":
        config["translation"] = {
            "type": "one_way",
            "target_language": target_language,
        }
    elif translation_mode == "two_way":
        if language_a == language_b:
            raise ValueError("Hai ngôn ngữ dịch hai chiều phải khác nhau.")
        config["translation"] = {
            "type": "two_way",
            "language_a": language_a,
            "language_b": language_b,
        }
        config["language_hints"] = [language_a, language_b]
        config["language_hints_strict"] = True
    else:
        raise ValueError("Chế độ dịch Soniox không hợp lệ.")
    return config


def audio_input_options() -> list[tuple[str, str]]:
    """Danh sách microphone `(mô tả, device-id hex)` dùng trong Cài đặt."""
    options = [("Mặc định hệ thống", "")]
    seen: set[str] = set()
    for device in QMediaDevices.audioInputs():
        device_id = bytes(device.id()).hex()
        if not device_id or device_id in seen:
            continue
        seen.add(device_id)
        options.append((device.description() or "Microphone", device_id))
    return options


def system_audio_input_options() -> list[tuple[str, str]]:
    """Danh sách thiết bị phát có WASAPI loopback `(nhãn, tên thiết bị)`."""
    options = [("Mặc định Windows", "")]
    try:
        manager = pyaudio.PyAudio()
    except Exception:  # noqa: BLE001 - UI vẫn phải mở khi backend native lỗi.
        return [("WASAPI loopback không khả dụng", "")]
    try:
        seen: set[str] = set()
        for device in manager.get_loopback_device_info_generator():
            name = str(device.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            options.append((name.removesuffix(" [Loopback]"), name))
    except Exception:  # noqa: BLE001
        return [("WASAPI loopback không khả dụng", "")]
    finally:
        manager.terminate()
    return options


def _find_loopback_device(manager, device_name: str) -> dict[str, Any]:
    if not device_name:
        return dict(manager.get_default_wasapi_loopback())
    for device in manager.get_loopback_device_info_generator():
        if device.get("name") == device_name:
            return dict(device)
    raise ValueError("Thiết bị phát đã chọn không còn khả dụng.")


def _loopback_format(device: dict[str, Any]) -> QAudioFormat:
    input_channels = int(device.get("maxInputChannels") or 0)
    if input_channels <= 0:
        raise ValueError("Thiết bị phát không hỗ trợ WASAPI loopback.")
    channels = min(2, input_channels)
    sample_rate = int(device.get("defaultSampleRate") or 0)
    if sample_rate <= 0:
        raise ValueError("Thiết bị phát không cung cấp sample rate hợp lệ.")
    audio_format = QAudioFormat()
    audio_format.setSampleRate(sample_rate)
    audio_format.setChannelCount(channels)
    audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    return audio_format


def _resolve_audio_device(device_id: str) -> QAudioDevice:
    if device_id:
        for device in QMediaDevices.audioInputs():
            if bytes(device.id()).hex() == device_id:
                return device
    return QMediaDevices.defaultAudioInput()


def _capture_format(device: QAudioDevice) -> QAudioFormat:
    preferred = QAudioFormat()
    preferred.setSampleRate(16000)
    preferred.setChannelCount(1)
    preferred.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    if device.isFormatSupported(preferred):
        return preferred
    return device.preferredFormat()


class SonioxRealtimeSession(QObject):
    """Vòng đời WebSocket và một nguồn audio realtime (mic hoặc WASAPI loopback)."""

    state_changed = Signal(str)
    transcript_changed = Signal(str)
    failed = Signal(str)
    finished = Signal()
    audio_data_ready = Signal(bytes)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = "idle"
        self._source = "microphone"
        self._socket: QWebSocket | None = None
        self._audio: QAudioSource | None = None
        self._audio_io = None
        self._loopback_manager = None
        self._loopback_device: dict[str, Any] | None = None
        self._loopback_stream = None
        self._config_message = ""
        self._transcript = TranscriptBuffer()
        self._finishing = False
        self.audio_data_ready.connect(self._send_audio_data)
        self._stop_timer = QTimer(self)
        self._stop_timer.setSingleShot(True)
        self._stop_timer.timeout.connect(self._finish_normally)

    @property
    def state(self) -> str:
        return self._state

    @property
    def source(self) -> str:
        return self._source

    @property
    def is_active(self) -> bool:
        return self._state != "idle"

    @property
    def transcript(self) -> str:
        return self._transcript.render()

    @property
    def transcript_blocks(self) -> tuple[TranscriptBlock, ...]:
        return self._transcript.blocks()

    def start(
        self,
        *,
        api_key: str,
        audio_source: str,
        device_id: str,
        system_device: str,
        translation_mode: str,
        target_language: str,
        language_a: str,
        language_b: str,
        speaker_diarization: bool,
    ) -> bool:
        if self.is_active:
            return False
        if not api_key.strip():
            self.failed.emit("Chưa nhập Soniox API key.")
            return False
        if audio_source not in {"microphone", "system"}:
            self.failed.emit("Nguồn âm thanh Soniox không hợp lệ.")
            return False

        self._source = audio_source
        try:
            audio_format = self._prepare_capture(device_id, system_device)
            config = build_session_config(
                api_key,
                audio_format,
                translation_mode=translation_mode,
                target_language=target_language,
                language_a=language_a,
                language_b=language_b,
                speaker_diarization=speaker_diarization,
            )
        except (OSError, ValueError) as exc:
            self._release_capture()
            self.failed.emit(str(exc))
            return False

        self._transcript.clear()
        self._finishing = False
        self._config_message = json.dumps(config, ensure_ascii=False)
        self._socket = QWebSocket("", QWebSocketProtocol.Version.Version13, self)
        self._socket.connected.connect(self._on_connected)
        self._socket.textMessageReceived.connect(self._on_text_message)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.errorOccurred.connect(self._on_socket_error)
        self._socket.sslErrors.connect(self._on_ssl_errors)
        self._set_state("connecting")
        self._socket.open(QUrl(SONIOX_WEBSOCKET_URL))
        return True

    def _prepare_capture(self, device_id: str, system_device: str) -> QAudioFormat:
        if self._source == "microphone":
            device = _resolve_audio_device(device_id)
            if device.isNull():
                raise ValueError("Không tìm thấy microphone khả dụng.")
            audio_format = _capture_format(device)
            self._audio = QAudioSource(device, audio_format, self)
            self._audio.stateChanged.connect(self._on_audio_state_changed)
            return audio_format

        try:
            self._loopback_manager = pyaudio.PyAudio()
            self._loopback_device = _find_loopback_device(
                self._loopback_manager, system_device
            )
            return _loopback_format(self._loopback_device)
        except Exception as exc:  # noqa: BLE001 - backend native trả nhiều kiểu lỗi.
            self._release_capture()
            raise ValueError(f"Không mở được audio hệ thống: {exc}") from exc

    def stop(self) -> None:
        if not self.is_active or self._finishing:
            return
        self._set_state("stopping")
        self._stop_capture_stream()
        if self._socket is None or not self._socket.isValid():
            self._finish_normally()
            return
        self._socket.sendBinaryMessage(QByteArray())
        self._stop_timer.start(4000)

    def shutdown(self) -> None:
        """Dừng ngay khi ứng dụng thoát; không chờ server finalize."""
        if not self.is_active:
            return
        self._finishing = True
        self._stop_timer.stop()
        if self._socket is not None:
            self._socket.abort()
        self._cleanup()

    def _set_state(self, state: str) -> None:
        if self._state == state:
            return
        self._state = state
        self.state_changed.emit(state)

    def _on_connected(self) -> None:
        if self._socket is None:
            return
        self._socket.sendTextMessage(self._config_message)
        if not self._start_capture_stream():
            return
        self._set_state("listening")

    def _start_capture_stream(self) -> bool:
        if self._source == "microphone":
            if self._audio is None:
                self._fail("Không thể mở microphone.")
                return False
            self._audio_io = self._audio.start()
            if self._audio_io is None:
                self._fail("Không thể mở microphone.")
                return False
            self._audio_io.readyRead.connect(self._send_available_audio)
            return True

        if self._loopback_manager is None or self._loopback_device is None:
            self._fail("Không tìm thấy thiết bị audio hệ thống.")
            return False
        device = self._loopback_device
        rate = int(device["defaultSampleRate"])
        channels = min(2, max(1, int(device["maxInputChannels"])))
        frames_per_buffer = max(480, int(rate * 0.1))
        try:
            self._loopback_stream = self._loopback_manager.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=int(device["index"]),
                frames_per_buffer=frames_per_buffer,
                stream_callback=self._on_loopback_audio,
                start=False,
            )
            self._loopback_stream.start_stream()
        except Exception as exc:  # noqa: BLE001 - PortAudio native error.
            self._fail(f"Không thể thu audio hệ thống: {exc}")
            return False
        return True

    def _on_loopback_audio(
        self, in_data: bytes, _frame_count: int, _time_info, _status
    ):
        if in_data:
            self.audio_data_ready.emit(bytes(in_data))
        flag = (
            pyaudio.paContinue
            if self._state in {"connecting", "listening"}
            else pyaudio.paComplete
        )
        return (None, flag)

    def _send_available_audio(self) -> None:
        if self._audio_io is None or self._state != "listening":
            return
        data = self._audio_io.readAll()
        if not data.isEmpty():
            self._send_audio_data(bytes(data))

    def _send_audio_data(self, data: bytes) -> None:
        if not data or self._socket is None or self._state != "listening":
            return
        if self._socket.bytesToWrite() > _MAX_PENDING_AUDIO_BYTES:
            self._fail("Kết nối Soniox quá chậm để truyền âm thanh realtime.")
            return
        self._socket.sendBinaryMessage(QByteArray(data))

    def _on_text_message(self, message: str) -> None:
        try:
            response = json.loads(message)
        except json.JSONDecodeError:
            self._fail("Soniox trả về dữ liệu không hợp lệ.")
            return
        if not isinstance(response, dict):
            self._fail("Soniox trả về dữ liệu không hợp lệ.")
            return
        if response.get("error_code") is not None:
            detail = response.get("error_message") or response.get("error_type")
            self._fail(f"Soniox: {detail or 'lỗi không xác định'}")
            return
        tokens = response.get("tokens")
        if isinstance(tokens, list):
            self._transcript.ingest(tokens)
            self.transcript_changed.emit(self._transcript.render())
        if response.get("finished"):
            self._finish_normally()

    def _on_audio_state_changed(self, state: QAudio.State) -> None:
        if (
            state == QAudio.State.StoppedState
            and self._state == "listening"
            and self._audio is not None
            and self._audio.error() != QAudio.Error.NoError
        ):
            self._fail("Microphone đã dừng do lỗi thiết bị.")

    def _on_socket_error(self, _error) -> None:
        if self._finishing or self._state == "idle":
            return
        detail = self._socket.errorString() if self._socket is not None else ""
        self._fail(f"Không thể kết nối Soniox: {detail or 'lỗi WebSocket'}")

    def _on_ssl_errors(self, _errors) -> None:
        self._fail("Không thể xác minh kết nối bảo mật tới Soniox.")

    def _on_disconnected(self) -> None:
        if self._finishing or self._state == "idle":
            return
        if self._state == "stopping":
            self._finish_normally()
        else:
            self._fail("Kết nối Soniox đã đóng ngoài dự kiến.")

    def _stop_capture_stream(self) -> None:
        if self._audio is not None:
            self._audio.stop()
        if self._loopback_stream is not None:
            try:
                if self._loopback_stream.is_active():
                    self._loopback_stream.stop_stream()
            except Exception:  # noqa: BLE001 - cleanup không được che lỗi chính.
                pass

    def _release_capture(self) -> None:
        self._stop_capture_stream()
        if self._loopback_stream is not None:
            try:
                self._loopback_stream.close()
            except Exception:  # noqa: BLE001
                pass
        if self._loopback_manager is not None:
            try:
                self._loopback_manager.terminate()
            except Exception:  # noqa: BLE001
                pass
        if self._audio is not None:
            self._audio.deleteLater()
        self._audio = None
        self._audio_io = None
        self._loopback_stream = None
        self._loopback_manager = None
        self._loopback_device = None

    def _fail(self, message: str) -> None:
        if self._finishing:
            return
        self._finishing = True
        self._stop_timer.stop()
        if self._socket is not None:
            self._socket.abort()
        self._cleanup()
        self.failed.emit(message)

    def _finish_normally(self) -> None:
        if self._finishing:
            return
        self._finishing = True
        self._stop_timer.stop()
        if self._socket is not None:
            self._socket.close()
        self._cleanup()
        self.finished.emit()

    def _cleanup(self) -> None:
        self._release_capture()
        if self._socket is not None:
            self._socket.deleteLater()
        self._socket = None
        self._config_message = ""
        self._finishing = False
        self._set_state("idle")
