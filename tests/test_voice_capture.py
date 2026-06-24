from __future__ import annotations

import io
import sys
import types
import unittest
import wave
from unittest import mock


sys.modules.setdefault(
    "decky",
    types.SimpleNamespace(
        logger=types.SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
        )
    ),
)

import main
from main import (
    _captured_wav_info,
    _select_voice_capture_tool,
    _voice_api_error_detail,
    _voice_capture_command,
    _voice_capture_env,
    _voice_error_message,
)


class VoiceCaptureHelperTests(unittest.TestCase):
    def test_voice_capture_command_for_pw_record(self) -> None:
        self.assertEqual(
            _voice_capture_command("pw-record", "/tmp/x.wav"),
            [
                "pw-record",
                "--media-category",
                "Capture",
                "--rate",
                "16000",
                "--channels",
                "1",
                "--format",
                "s16",
                "--container",
                "wav",
                "/tmp/x.wav",
            ],
        )

    def test_voice_capture_command_for_parecord(self) -> None:
        self.assertEqual(
            _voice_capture_command("parecord", "/tmp/x.wav"),
            [
                "parecord",
                "--file-format=wav",
                "--rate=16000",
                "--channels=1",
                "/tmp/x.wav",
            ],
        )

    def test_voice_capture_command_for_arecord(self) -> None:
        self.assertEqual(
            _voice_capture_command("arecord", "/tmp/x.wav"),
            [
                "arecord",
                "-q",
                "-f",
                "S16_LE",
                "-r",
                "16000",
                "-c",
                "1",
                "-t",
                "wav",
                "/tmp/x.wav",
            ],
        )

    def test_select_voice_capture_tool_returns_none_when_unavailable(self) -> None:
        with mock.patch("main.shutil.which", return_value=None):
            self.assertIsNone(_select_voice_capture_tool())

    def test_select_voice_capture_tool_returns_first_available_tool(self) -> None:
        def fake_which(tool: str) -> str | None:
            return "/usr/bin/arecord" if tool == "arecord" else None

        with mock.patch("main.shutil.which", side_effect=fake_which):
            self.assertEqual(_select_voice_capture_tool(), ("arecord", "/usr/bin/arecord"))

    def test_voice_capture_env_includes_xdg_runtime_dir(self) -> None:
        with mock.patch.dict(main.os.environ, {"XDG_RUNTIME_DIR": "/tmp"}, clear=True):
            env = _voice_capture_env()

        self.assertEqual(env["XDG_RUNTIME_DIR"], "/tmp")

    def test_captured_wav_info_returns_duration(self) -> None:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b"\x00\x00" * 16000)

        info = _captured_wav_info(buffer.getvalue())

        self.assertEqual(info["sample_rate"], 16000)
        self.assertEqual(info["channels"], 1)
        self.assertEqual(info["duration_seconds"], 1.0)
        self.assertGreater(info["audio_bytes"], 44)

    def test_captured_wav_info_rejects_empty_audio(self) -> None:
        with self.assertRaisesRegex(ValueError, "no audio was captured"):
            _captured_wav_info(b"")

    def test_voice_api_error_detail_extracts_openai_message(self) -> None:
        detail = _voice_api_error_detail(
            '{"error":{"message":"Invalid audio file.","type":"invalid_request_error"}}'
        )

        self.assertEqual(detail, "Invalid audio file. (invalid_request_error)")

    def test_voice_error_message_redacts_bearer_tokens(self) -> None:
        message = _voice_error_message(
            ValueError("failed with Bearer sk-testsecret1234567890"),
            fallback="fallback",
        )

        self.assertEqual(message, "failed with Bearer <redacted>")


class VoiceCaptureCallableTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_voice_capture_returns_structured_error_when_idle(self) -> None:
        plugin = main.Plugin()

        result = await plugin.stop_voice_capture()

        self.assertEqual(result["text"], "")
        self.assertEqual(result["error"], "no voice capture in progress")


if __name__ == "__main__":
    unittest.main()
