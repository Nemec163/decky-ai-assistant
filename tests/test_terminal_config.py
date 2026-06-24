from __future__ import annotations

import sys
import tempfile
import types
import unittest
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
    DEFAULT_TERMINAL_CONFIG,
    DEFAULT_VOICE_TRANSCRIPTION_CONFIG,
    _build_multipart_form_data,
    _terminal_config_payload,
    _transcribe_with_external_api,
    _validated_transcription_url,
    _voice_audio_content_type,
    _voice_audio_filename,
    _voice_transcription_ssl_context,
    _voice_transcription_config_payload,
    _voice_transcription_public_payload,
)


class TerminalConfigTests(unittest.TestCase):
    def test_defaults_contain_terminal_input_and_copy_fields(self) -> None:
        self.assertEqual(DEFAULT_TERMINAL_CONFIG["dpad_mode"], "arrows")
        self.assertIs(DEFAULT_TERMINAL_CONFIG["terminal_capture_input"], True)
        self.assertIs(DEFAULT_TERMINAL_CONFIG["auto_copy_selection"], True)
        self.assertIs(DEFAULT_TERMINAL_CONFIG["voice_input"], True)
        self.assertIs(DEFAULT_TERMINAL_CONFIG["voice_prefer_native_cli"], False)

    def test_defaults_do_not_expose_removed_voice_fields(self) -> None:
        self.assertNotIn("voice_auto_insert", DEFAULT_TERMINAL_CONFIG)
        self.assertNotIn("voice_language", DEFAULT_TERMINAL_CONFIG)
        self.assertEqual(
            _terminal_config_payload({"voice_auto_insert": False, "voice_language": "ru-RU"}),
            {},
        )

    def test_dpad_mode_payload(self) -> None:
        self.assertEqual(_terminal_config_payload({"dpad_mode": "scroll"}), {"dpad_mode": "scroll"})

    def test_legacy_dpad_navigation_mode_maps_to_arrows(self) -> None:
        self.assertEqual(_terminal_config_payload({"dpad_mode": "navigation"}), {"dpad_mode": "arrows"})

    def test_dpad_mode_must_be_known(self) -> None:
        with self.assertRaisesRegex(ValueError, "arrows or scroll"):
            _terminal_config_payload({"dpad_mode": "vim"})

    def test_bool_payload_coercion(self) -> None:
        self.assertEqual(
            _terminal_config_payload(
                {
                    "auto_copy_selection": 1,
                    "voice_input": 1,
                    "voice_prefer_native_cli": 0,
                }
            ),
            {
                "auto_copy_selection": True,
                "voice_input": True,
                "voice_prefer_native_cli": False,
            },
        )

    def test_removed_terminal_config_payload_fields_are_ignored(self) -> None:
        self.assertEqual(
            _terminal_config_payload(
                {
                    "terminal_capture_input": False,
                    "stick_scroll": False,
                    "scroll_speed": 1,
                    "show_scrollbar": False,
                }
            ),
            {},
        )


class VoiceTranscriptionConfigTests(unittest.TestCase):
    def test_voice_transcription_defaults_are_opt_in_and_redacted(self) -> None:
        public_payload = _voice_transcription_public_payload(DEFAULT_VOICE_TRANSCRIPTION_CONFIG)

        self.assertIs(public_payload["enabled"], False)
        self.assertEqual(
            public_payload["base_url"],
            "https://api.openai.com/v1/audio/transcriptions",
        )
        self.assertEqual(public_payload["model"], "gpt-4o-mini-transcribe")
        self.assertIs(public_payload["api_key_required"], True)
        self.assertIs(public_payload["api_key_configured"], False)
        self.assertNotIn("api_key", public_payload)

    def test_voice_transcription_payload_preserves_existing_key(self) -> None:
        existing = {
            **DEFAULT_VOICE_TRANSCRIPTION_CONFIG,
            "api_key": "secret-key",
        }

        payload = _voice_transcription_config_payload(
            {"enabled": True, "base_url": "https://example.com/v1/audio/transcriptions"},
            existing=existing,
        )

        self.assertIs(payload["enabled"], True)
        self.assertEqual(payload["api_key"], "secret-key")

    def test_voice_transcription_payload_can_clear_key(self) -> None:
        payload = _voice_transcription_config_payload(
            {"clear_api_key": True},
            existing={**DEFAULT_VOICE_TRANSCRIPTION_CONFIG, "api_key": "secret-key"},
        )

        self.assertEqual(payload["api_key"], "")

    def test_voice_transcription_url_requires_https_outside_localhost(self) -> None:
        self.assertEqual(
            _validated_transcription_url("https://example.com/v1/audio/transcriptions"),
            "https://example.com/v1/audio/transcriptions",
        )
        self.assertEqual(
            _validated_transcription_url("http://localhost:8080/v1/audio/transcriptions"),
            "http://localhost:8080/v1/audio/transcriptions",
        )
        with self.assertRaises(ValueError):
            _validated_transcription_url("http://example.com/v1/audio/transcriptions")

    def test_voice_audio_helpers(self) -> None:
        self.assertEqual(_voice_audio_content_type("audio/webm;codecs=opus"), "audio/webm")
        self.assertEqual(_voice_audio_filename("../voice input.webm"), "voice_input.webm")
        with self.assertRaises(ValueError):
            _voice_audio_content_type("text/plain")

    def test_voice_transcription_ssl_context_uses_ca_bundle_for_https(self) -> None:
        with tempfile.NamedTemporaryFile() as ca_bundle:
            ssl_context = object()
            with (
                mock.patch.dict(main.os.environ, {"SSL_CERT_FILE": ca_bundle.name}, clear=True),
                mock.patch("main.VOICE_CA_BUNDLE_PATHS", ()),
                mock.patch("main.ssl.create_default_context", return_value=ssl_context) as create_context,
            ):
                result = _voice_transcription_ssl_context("https://example.com/v1/audio/transcriptions")

        self.assertIs(result, ssl_context)
        create_context.assert_called_once_with(cafile=ca_bundle.name)

    def test_voice_transcription_ssl_context_ignores_missing_env_ca_bundle(self) -> None:
        with tempfile.NamedTemporaryFile() as ca_bundle:
            ssl_context = object()
            with (
                mock.patch.dict(main.os.environ, {"SSL_CERT_FILE": "/missing.pem"}, clear=True),
                mock.patch("main.VOICE_CA_BUNDLE_PATHS", (ca_bundle.name,)),
                mock.patch("main.ssl.create_default_context", return_value=ssl_context) as create_context,
            ):
                result = _voice_transcription_ssl_context("https://example.com/v1/audio/transcriptions")

        self.assertIs(result, ssl_context)
        create_context.assert_called_once_with(cafile=ca_bundle.name)

    def test_voice_transcription_ssl_context_skips_http_localhost(self) -> None:
        with mock.patch("main.ssl.create_default_context") as create_context:
            result = _voice_transcription_ssl_context("http://localhost:8080/v1/audio/transcriptions")

        self.assertIsNone(result)
        create_context.assert_not_called()

    def test_multipart_transcription_request(self) -> None:
        captured_requests = []
        ssl_context = object()

        class FakeResponse:
            headers = {"content-type": "application/json"}

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self, _limit: int) -> bytes:
                return b'{"text": " privet "}'

        def fake_urlopen(request: object, **kwargs: object) -> FakeResponse:
            captured_requests.append((request, kwargs))
            return FakeResponse()

        with (
            mock.patch("main.urllib.request.urlopen", fake_urlopen),
            mock.patch("main._voice_transcription_ssl_context", return_value=ssl_context),
        ):
            result = _transcribe_with_external_api(
                {
                    **DEFAULT_VOICE_TRANSCRIPTION_CONFIG,
                    "enabled": True,
                    "api_key": "test-key",
                },
                b"audio-bytes",
                "audio/webm",
                "voice-input.webm",
            )

        self.assertEqual(result, {"text": "privet"})
        self.assertEqual(len(captured_requests), 1)
        request, kwargs = captured_requests[0]
        self.assertEqual(kwargs["timeout"], main.VOICE_TRANSCRIPTION_TIMEOUT_SECONDS)
        self.assertIs(kwargs["context"], ssl_context)
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(request.get_method(), "POST")
        body = request.data
        self.assertIn(b'name="model"', body)
        self.assertIn(b"gpt-4o-mini-transcribe", body)
        self.assertNotIn(b'name="language"', body)
        self.assertIn(b"audio-bytes", body)

    def test_multipart_builder_includes_file_and_fields(self) -> None:
        body, content_type = _build_multipart_form_data(
            fields={"model": "whisper-1", "response_format": "json"},
            file_field="file",
            filename="voice-input.webm",
            content_type="audio/webm",
            file_bytes=b"abc",
        )

        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="model"', body)
        self.assertIn(b"whisper-1", body)
        self.assertIn(b'filename="voice-input.webm"', body)
        self.assertIn(b"Content-Type: audio/webm", body)
        self.assertIn(b"abc", body)


if __name__ == "__main__":
    unittest.main()
