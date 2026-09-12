from __future__ import annotations

import sys
import unittest
from unittest import mock
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from PySide6.QtMultimedia import QAudioFormat  # noqa: E402

from soniox_realtime import (  # noqa: E402
    SonioxRealtimeSession,
    TranscriptBuffer,
    build_session_config,
    _find_loopback_device,
    _loopback_format,
    system_audio_input_options,
)


def _pcm_format() -> QAudioFormat:
    audio_format = QAudioFormat()
    audio_format.setSampleRate(16000)
    audio_format.setChannelCount(1)
    audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    return audio_format


class SonioxContractTests(unittest.TestCase):
    def test_one_way_config_matches_websocket_contract(self) -> None:
        payload = build_session_config(
            "soniox-key",
            _pcm_format(),
            translation_mode="one_way",
            target_language="vi",
            language_a="en",
            language_b="vi",
            speaker_diarization=True,
        )

        self.assertEqual(payload["model"], "stt-rt-v5")
        self.assertEqual(payload["audio_format"], "pcm_s16le")
        self.assertEqual(payload["sample_rate"], 16000)
        self.assertEqual(payload["num_channels"], 1)
        self.assertTrue(payload["enable_speaker_diarization"])
        self.assertTrue(payload["enable_language_identification"])
        self.assertEqual(
            payload["translation"],
            {"type": "one_way", "target_language": "vi"},
        )

    def test_two_way_config_restricts_session_to_language_pair(self) -> None:
        payload = build_session_config(
            "soniox-key",
            _pcm_format(),
            translation_mode="two_way",
            target_language="vi",
            language_a="en",
            language_b="ja",
            speaker_diarization=False,
        )

        self.assertEqual(
            payload["translation"],
            {"type": "two_way", "language_a": "en", "language_b": "ja"},
        )
        self.assertEqual(payload["language_hints"], ["en", "ja"])
        self.assertTrue(payload["language_hints_strict"])
        self.assertFalse(payload["enable_speaker_diarization"])

    def test_invalid_session_configuration_is_rejected_before_network_io(self) -> None:
        with self.assertRaisesRegex(ValueError, "API key"):
            build_session_config(
                " ",
                _pcm_format(),
                translation_mode="one_way",
                target_language="vi",
                language_a="en",
                language_b="vi",
                speaker_diarization=True,
            )
        with self.assertRaisesRegex(ValueError, "phải khác nhau"):
            build_session_config(
                "key",
                _pcm_format(),
                translation_mode="two_way",
                target_language="vi",
                language_a="en",
                language_b="en",
                speaker_diarization=True,
            )

    def test_missing_key_fails_before_audio_device_lookup(self) -> None:
        session = SonioxRealtimeSession()
        errors: list[str] = []
        session.failed.connect(errors.append)

        started = session.start(
            api_key=" ",
            audio_source="system",
            device_id="missing-device",
            system_device="Missing output",
            translation_mode="one_way",
            target_language="vi",
            language_a="en",
            language_b="vi",
            speaker_diarization=True,
        )

        self.assertFalse(started)
        self.assertEqual(errors, ["Chưa nhập Soniox API key."])
        self.assertEqual(session.state, "idle")

    def test_loopback_device_selection_and_pcm_format(self) -> None:
        devices = [
            {
                "index": 4,
                "name": "Speakers [Loopback]",
                "maxInputChannels": 2,
                "defaultSampleRate": 48000.0,
            },
            {
                "index": 8,
                "name": "Headphones [Loopback]",
                "maxInputChannels": 2,
                "defaultSampleRate": 44100.0,
            },
        ]
        manager = mock.Mock()
        manager.get_loopback_device_info_generator.return_value = iter(devices)
        manager.get_default_wasapi_loopback.return_value = devices[0]

        selected = _find_loopback_device(manager, "Headphones [Loopback]")
        audio_format = _loopback_format(selected)

        self.assertEqual(selected["index"], 8)
        self.assertEqual(audio_format.sampleRate(), 44100)
        self.assertEqual(audio_format.channelCount(), 2)
        self.assertEqual(audio_format.sampleFormat(), QAudioFormat.SampleFormat.Int16)

    def test_system_audio_options_use_loopback_outputs_and_release_backend(
        self,
    ) -> None:
        manager = mock.Mock()
        manager.get_loopback_device_info_generator.return_value = iter(
            [
                {"name": "Speakers [Loopback]"},
                {"name": "Headphones [Loopback]"},
            ]
        )
        with mock.patch("soniox_realtime.pyaudio.PyAudio", return_value=manager):
            options = system_audio_input_options()

        self.assertEqual(
            options,
            [
                ("Mặc định Windows", ""),
                ("Speakers", "Speakers [Loopback]"),
                ("Headphones", "Headphones [Loopback]"),
            ],
        )
        manager.terminate.assert_called_once_with()

    def test_transcript_replaces_non_final_tokens_and_groups_speakers(self) -> None:
        transcript = TranscriptBuffer()
        transcript.ingest(
            [
                {
                    "text": "Hello ",
                    "is_final": True,
                    "speaker": "1",
                    "language": "en",
                    "translation_status": "original",
                },
                {
                    "text": "world",
                    "is_final": False,
                    "speaker": "1",
                    "language": "en",
                    "translation_status": "original",
                },
            ]
        )
        self.assertEqual(
            [
                (block.kind, block.speaker, block.language, block.text, block.is_final)
                for block in transcript.blocks()
            ],
            [("speech", "1", "en", "Hello world", False)],
        )

        transcript.ingest(
            [
                {
                    "text": "world",
                    "is_final": True,
                    "speaker": "1",
                    "language": "en",
                    "translation_status": "original",
                },
                {
                    "text": "Xin chào thế giới.",
                    "is_final": True,
                    "language": "vi",
                    "translation_status": "translation",
                },
                {
                    "text": "Good morning.",
                    "is_final": True,
                    "speaker": "2",
                    "language": "en",
                    "translation_status": "original",
                },
            ]
        )

        self.assertEqual(
            [
                (block.kind, block.speaker, block.language, block.text)
                for block in transcript.blocks()
            ],
            [
                ("speech", "1", "en", "Hello world"),
                ("translation", "1", "vi", "Xin chào thế giới."),
                ("speech", "2", "en", "Good morning."),
            ],
        )

        transcript.ingest(
            [
                {
                    "text": "Chào buổi sáng.",
                    "is_final": True,
                    "speaker": "2",
                    "language": "vi",
                    "translation_status": "translation",
                },
                {
                    "text": "<end>",
                    "is_final": True,
                    "translation_status": "none",
                },
                {
                    "text": "次の文です。",
                    "is_final": False,
                    "speaker": "2",
                    "language": "ja",
                    "translation_status": "original",
                },
            ]
        )
        pending = transcript.blocks()[-1]
        self.assertEqual((pending.kind, pending.language), ("speech", "ja"))
        self.assertEqual(pending.text, "次の文です。")
        self.assertFalse(pending.is_final)
        self.assertNotIn("<end>", "".join(block.text for block in transcript.blocks()))

        transcript.ingest(
            [
                {
                    "text": "次の文です。",
                    "is_final": True,
                    "speaker": "2",
                    "language": "ja",
                    "translation_status": "original",
                },
                {
                    "text": "Đây là câu tiếp theo.",
                    "is_final": True,
                    "speaker": "2",
                    "language": "vi",
                    "translation_status": "translation",
                },
                {
                    "text": "<end>",
                    "is_final": True,
                    "translation_status": "none",
                },
            ]
        )

        blocks = transcript.blocks()
        self.assertEqual(
            [(block.kind, block.language) for block in blocks[-2:]],
            [("speech", "ja"), ("translation", "vi")],
        )
        self.assertEqual(blocks[-2].text, "次の文です。")
        self.assertEqual(blocks[-1].text, "Đây là câu tiếp theo.")
        self.assertTrue(all(block.is_final for block in blocks))


    def test_blocks_cache_matches_full_recomputation(self) -> None:
        """Ảnh chụp incremental phải trùng khớp với dựng lại từ đầu."""
        transcript = TranscriptBuffer()
        batches = [
            [
                {
                    "text": "Hello ",
                    "is_final": True,
                    "speaker": "1",
                    "language": "en",
                    "translation_status": "original",
                },
                {
                    "text": "there",
                    "is_final": False,
                    "speaker": "1",
                    "language": "en",
                    "translation_status": "original",
                },
            ],
            [
                {
                    "text": "there",
                    "is_final": True,
                    "speaker": "1",
                    "language": "en",
                    "translation_status": "original",
                },
                {
                    "text": "Xin chào",
                    "is_final": True,
                    "language": "vi",
                    "translation_status": "translation",
                },
            ],
            [
                {
                    "text": "Bye",
                    "is_final": False,
                    "speaker": "2",
                    "language": "en",
                    "translation_status": "original",
                }
            ],
        ]
        for batch in batches:
            transcript.ingest(batch)
            cached = transcript.blocks()
            reference = TranscriptBuffer()
            reference.final_tokens = list(transcript.final_tokens)
            reference.non_final_tokens = list(transcript.non_final_tokens)
            self.assertEqual(cached, reference.blocks())

        # Bắt đầu phiên mới: ảnh chụp phải được xoá sạch.
        transcript.clear()
        self.assertEqual(transcript.blocks(), ())


if __name__ == "__main__":
    unittest.main()
