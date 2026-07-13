from __future__ import annotations

import asyncio
import base64
import ctypes
import ctypes.util
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import wave
import zipfile
from urllib.parse import urlsplit
from pathlib import Path, PurePosixPath
from typing import Any

import decky


PLUGIN_ROOT = Path(__file__).resolve().parent
CORE_SRC = PLUGIN_ROOT / "packages" / "core" / "src"
MCP_SRC = PLUGIN_ROOT / "packages" / "mcp-server" / "src"
CUSTOM_PROFILES_FILENAME = "custom-profiles.json"
PROFILE_PERMISSIONS_FILENAME = "profile-permissions.json"
TERMINAL_CONFIG_FILENAME = "terminal-config.json"
RELEASE_CHANNEL_FILENAME = "release-channel.json"
VOICE_TRANSCRIPTION_CONFIG_FILENAME = "voice-transcription.json"
MAX_CUSTOM_PROFILES = 16
TERMINAL_URL_PATTERN = re.compile(r"https?://[^\s<>'\"`\x00-\x1f\x7f\\]+")
ANSI_ESCAPE_PATTERN = re.compile(
    r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))"
)
URL_CONTINUATION_START_PATTERN = re.compile(r"[A-Za-z0-9%._~:/?#\[\]@!$&'()*+,;=-]")
URL_QUERY_PART_PATTERN = re.compile(r"[A-Za-z0-9_.%~-]+=|[&?=]")
AUTH_COMPLETION_PATTERN = re.compile(
    r"\b(?:"
    r"successfully (?:logged in|authenticated)"
    r"|(?:login|log in|authentication|authorization|auth) "
    r"(?:successful|succeeded|complete|completed)"
    r"|logged in successfully"
    r"|you are now logged in"
    r"|oauth callback received"
    r")\b",
    re.IGNORECASE,
)
# A link is only surfaced when it looks like a sign-in/auth link: either the URL
# itself is auth-shaped, or login wording sits next to it in the output. Ordinary
# URLs printed by a CLI (docs, repos, etc.) are intentionally ignored.
AUTH_LINK_URL_HINT_PATTERN = re.compile(
    r"oauth"
    r"|/authorize|/authenticate"
    r"|/device(?:[/?#]|$)|/login/device"
    r"|/sso(?:[/?#]|$)|/connect/|openid"
    r"|response_type=|client_id=|code_challenge=|redirect_uri=",
    re.IGNORECASE,
)
AUTH_LINK_HOST_LABELS = frozenset(
    {"auth", "login", "accounts", "oauth", "signin", "sso", "id", "secure"}
)
AUTH_LINK_CONTEXT_PATTERN = re.compile(
    r"sign[ -]?in|log[ -]?in|logging[ -]?in"
    r"|authenticat|authoriz|credentials"
    r"|verification code|verify your|user code|device code|one[ -]?time code"
    r"|security code|confirmation code"
    r"|enter (?:the |this )?code|paste (?:the |this )?code|copy (?:the |this )?code"
    r"|open (?:the )?(?:following |this )?(?:url|link|page)"
    r"|in (?:your |a )?browser|browser to (?:continue|sign|log|authenticat)"
    r"|to (?:continue|authenticate|authorize|finish)"
    r"|complete (?:your )?(?:sign[ -]?in|login|authentication)",
    re.IGNORECASE,
)
AUTH_LINK_CONTEXT_WINDOW_CHARS = 320
TERMINAL_LINK_TAIL_CHARS = 8192
TERMINAL_OUTPUT_TAIL_CHARS = 32768
CLIPBOARD_MAX_CHARS = 65536
CLIPBOARD_TIMEOUT_SECONDS = 1.0
VOICE_TRANSCRIPTION_TIMEOUT_SECONDS = 45.0
VOICE_TRANSCRIPTION_MAX_BYTES = 8 * 1024 * 1024
VOICE_CAPTURE_MAX_SECONDS = 120.0
VOICE_CAPTURE_MIN_BYTES = 48
VOICE_CAPTURE_RATE = 16000
VOICE_CAPTURE_TOOLS = ("pw-record", "parecord", "arecord")
PLUGIN_UPDATE_REPO = "Nemec163/decky-ai-assistant"
PLUGIN_UPDATE_RELEASES_URL = (
    f"https://api.github.com/repos/{PLUGIN_UPDATE_REPO}/releases?per_page=20"
)
PLUGIN_UPDATE_TIMEOUT_SECONDS = 20.0
PLUGIN_UPDATE_MAX_BYTES = 64 * 1024 * 1024
PLUGIN_PACKAGE_NAME = "decky-ai-assistant"
PLUGIN_UPDATE_REQUIRED_FILES = (
    "dist/index.js",
    "main.py",
    "package.json",
    "plugin.json",
    "LICENSE",
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "ROADMAP.md",
)
PLUGIN_UPDATE_REQUIRED_DIRS = (
    "agent-pack",
    "docs",
    "packages/core/src",
    "packages/mcp-server/src",
)
VOICE_CA_BUNDLE_ENV_KEYS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
VOICE_CA_BUNDLE_PATHS = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/ca-certificates/extracted/tls-ca-bundle.pem",
    "/etc/ssl/cert.pem",
    "/etc/ssl/certs/ca-bundle.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
)
TRAILING_URL_PUNCTUATION = ".,;:)]}>"
RELEASE_CHANNELS = ("stable", "dev")
DEFAULT_RELEASE_CHANNEL = "stable"
DEFAULT_TERMINAL_CONFIG: dict[str, Any] = {
    "font_family": "Menlo, Consolas, monospace",
    "font_size": 12,
    "use_dpad": True,
    "dpad_mode": "arrows",
    "terminal_capture_input": True,
    "disable_virtual_keyboard": False,
    "extra_keys": True,
    "auto_copy_selection": True,
    "voice_input": True,
    "voice_prefer_native_cli": False,
}
DEFAULT_VOICE_TRANSCRIPTION_CONFIG: dict[str, Any] = {
    "enabled": False,
    "base_url": "https://api.openai.com/v1/audio/transcriptions",
    "model": "gpt-4o-mini-transcribe",
    "api_key": "",
}

for source_path in (CORE_SRC, MCP_SRC):
    source_text = str(source_path)
    if source_path.exists() and source_text not in sys.path:
        sys.path.insert(0, source_text)

from deck_assistant_core.profile_permissions import (  # noqa: E402  (sys.path set above)
    is_bypass_enabled,
    normalize_profile_name,
    parse_profile_permissions,
    serialize_profile_permissions,
)


def _module_status(module_name: str) -> dict[str, Any]:
    try:
        __import__(module_name)
    except Exception as error:  # Decky should return diagnostics, not a traceback.
        return {"name": module_name, "available": False, "error": str(error)}
    return {"name": module_name, "available": True, "error": None}


class Plugin:
    def __init__(self) -> None:
        self._init_state()

    def _init_state(self) -> None:
        """Initialize all in-memory state so every method can assume the
        fields exist, even when the plugin is constructed without ``_main``
        (as the unit tests do)."""

        self.terminal_links: dict[str, list[str]] = {}
        self.terminal_link_buffers: dict[str, str] = {}
        self.terminal_output_tails: dict[str, str] = {}
        self.terminal_link_suppressed: set[str] = set()
        self.custom_profiles: tuple[Any, ...] = ()
        self.profile_permissions: dict[str, dict[str, Any]] | None = None
        self.terminal_config: dict[str, Any] | None = None
        self.release_channel: str | None = None
        self.voice_transcription_config: dict[str, Any] | None = None
        self._voice_capture: dict[str, Any] | None = None

    async def _main(self) -> None:
        self.loop = asyncio.get_event_loop()
        from deck_assistant_core import PtySessionManager

        self._init_state()
        self.custom_profiles = self._load_custom_profiles()
        self.profile_permissions = self._load_profile_permissions()
        self.terminal_config = self._load_terminal_config()
        self.release_channel = self._load_release_channel()
        self.voice_transcription_config = self._load_voice_transcription_config()
        self.pty_sessions = PtySessionManager(
            max_sessions=8,
            profiles=self._terminal_profiles_for_manager(),
        )
        decky.logger.info("Decky AI Assistant plugin loaded")

    async def _unload(self) -> None:
        capture = self._voice_capture
        self._voice_capture = None
        if capture is not None:
            try:
                self._discard_voice_capture(capture)
            except Exception as exc:  # Best-effort cleanup during Decky unload.
                decky.logger.warning("Could not clean up voice capture on unload: %s", exc)
        manager = getattr(self, "pty_sessions", None)
        if manager is not None:
            manager.stop_all_sessions()
        decky.logger.info("Decky AI Assistant plugin unloaded")

    async def ping(self) -> dict[str, Any]:
        return {
            "plugin": "Decky AI Assistant",
            "mode": "terminal_mvp",
            "root": str(PLUGIN_ROOT),
            "modules": [
                _module_status("deck_assistant_core"),
                _module_status("deck_assistant_mcp"),
            ],
        }

    async def get_cli_profiles(self) -> dict[str, Any]:
        profiles = self._all_cli_profiles()
        return {
            "profiles": [self._profile_payload(profile) for profile in profiles],
        }

    async def get_cli_profile_health(self) -> dict[str, Any]:
        from deck_assistant_core import summarize_cli_profile_health

        return {
            "profiles": [
                summarize_cli_profile_health(profile, timeout_seconds=1.0).to_dict()
                for profile in self._all_cli_profiles()
            ]
        }

    async def get_cli_setup_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        from deck_assistant_core import plan_cli_setup_action

        payload = request or {}
        profile = self._get_cli_profile(str(payload.get("profile_name", "")))
        action = str(payload.get("action", "install_auth"))
        return {"plan": plan_cli_setup_action(profile, action).to_dict()}

    async def open_cli_setup_action(self, request: dict[str, Any]) -> dict[str, Any]:
        from deck_assistant_core import plan_cli_setup_action
        from deck_assistant_core.cli import CliSetupStatus

        manager = self._terminal_manager()
        payload = request or {}
        profile = self._get_cli_profile(str(payload.get("profile_name", "")))
        action = str(payload.get("action", "install_auth"))
        cols = _int_payload(payload, "cols", 80)
        rows = _int_payload(payload, "rows", 24)

        plan = plan_cli_setup_action(profile, action)
        if plan.status is not CliSetupStatus.READY:
            raise ValueError(plan.error or plan.message or "CLI setup action is not ready")

        session = manager.open_transient_session(plan.to_profile(), cols=cols, rows=rows)
        return {"session": session.to_dict(), "plan": plan.to_dict()}

    async def get_agent_pack_install_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        from deck_assistant_core import plan_native_agent_pack_install

        payload = request or {}
        profile = self._get_cli_profile(str(payload.get("profile_name", "")))
        return {
            "plan": plan_native_agent_pack_install(
                profile.name,
                plugin_root=str(PLUGIN_ROOT),
            ).to_dict()
        }

    async def install_agent_pack(self, request: dict[str, Any]) -> dict[str, Any]:
        from deck_assistant_core import install_native_agent_pack

        payload = request or {}
        profile = self._get_cli_profile(str(payload.get("profile_name", "")))

        result = install_native_agent_pack(profile.name, plugin_root=str(PLUGIN_ROOT))
        return result.to_dict()

    async def get_plugin_update_plan(self) -> dict[str, Any]:
        channel = self._release_channel()
        return await asyncio.to_thread(_fetch_plugin_update_plan, channel)

    async def update_plugin_to_latest(self, request: dict[str, Any]) -> dict[str, Any]:
        channel = self._release_channel()
        plan = await asyncio.to_thread(_fetch_plugin_update_plan, channel)
        if plan["status"] == "up_to_date":
            decky.logger.info(
                "Plugin update skipped: current version %s is up to date",
                plan.get("current_version"),
            )
            return {
                "plan": plan,
                "installed": False,
                "files_written": 0,
                "directories_written": 0,
                "bytes_downloaded": 0,
                "sha256": "",
                "reload_required": False,
            }
        if plan["status"] != "ready":
            raise ValueError(plan.get("message") or "plugin update is not available")

        decky.logger.info(
            "Plugin update requested: %s -> %s (%s)",
            plan.get("current_version"),
            plan.get("latest_version"),
            plan.get("tag_name"),
        )
        try:
            await asyncio.to_thread(_validate_plugin_update_install_target, PLUGIN_ROOT)
            archive_bytes, sha256 = await asyncio.to_thread(
                _download_plugin_update_asset,
                str(plan["asset_url"]),
                str(plan.get("asset_digest") or ""),
            )
            install_result = await asyncio.to_thread(
                _install_plugin_update_archive,
                archive_bytes,
                plugin_root=PLUGIN_ROOT,
            )
        except Exception as exc:
            decky.logger.warning("Plugin update failed: %s", exc)
            raise
        result_plan = dict(plan)
        result_plan["status"] = "installed"
        result_plan["message"] = (
            f"Installed {result_plan['latest_version']}. Reloading Decky plugin is required."
        )
        decky.logger.info(
            "Plugin update installed: %s (%s bytes, sha256 %s)",
            result_plan["latest_version"],
            len(archive_bytes),
            sha256,
        )
        return {
            "plan": result_plan,
            "installed": True,
            "files_written": install_result["files_written"],
            "directories_written": install_result["directories_written"],
            "bytes_downloaded": len(archive_bytes),
            "sha256": sha256,
            "reload_required": True,
        }

    async def get_release_channel(self) -> dict[str, Any]:
        return {"channel": self._release_channel()}

    async def set_release_channel(self, request: dict[str, Any]) -> dict[str, Any]:
        channel = _normalize_release_channel((request or {}).get("channel"))
        self._save_release_channel(channel)
        self.release_channel = channel
        return {"channel": channel}

    async def get_permission_bypass_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        from deck_assistant_core import plan_cli_permission_bypass

        payload = request or {}
        profile = self._get_cli_profile(str(payload.get("profile_name", "")))
        return {
            "plan": plan_cli_permission_bypass(
                profile,
                enabled=self._profile_permission_bypass_enabled(profile.name),
            ).to_dict()
        }

    async def update_permission_bypass(self, request: dict[str, Any]) -> dict[str, Any]:
        from deck_assistant_core import plan_cli_permission_bypass

        payload = request or {}
        profile = self._get_base_cli_profile(str(payload.get("profile_name", "")))
        enabled = bool(payload.get("enabled", False))
        plan = plan_cli_permission_bypass(profile, enabled=enabled)
        if enabled and plan.status.value == "unsupported":
            raise ValueError(f"permission bypass is not supported for profile: {profile.name}")

        permissions = dict(self._profile_permissions())
        if enabled:
            permissions[profile.name] = {"bypass_permissions": True}
        else:
            permissions.pop(profile.name, None)
        self._save_profile_permissions(permissions)
        self.profile_permissions = permissions
        self._sync_terminal_profiles()

        launch_profile = self._get_cli_profile(profile.name)
        return {
            "plan": plan_cli_permission_bypass(launch_profile, enabled=enabled).to_dict(),
            "profiles": [self._profile_payload(item) for item in self._all_cli_profiles()],
        }

    async def add_cli_profile(self, request: dict[str, Any]) -> dict[str, Any]:
        from deck_assistant_core import CliProfile, get_cli_profile
        from deck_assistant_core.cli import CliProfileError

        argv = _argv_payload(request)
        display_name = str(request.get("display_name") or request.get("name") or "").strip()
        if not display_name:
            display_name = argv[0]
        name_source = str(request.get("name") or "").strip() or display_name or argv[0]
        name = normalize_profile_name(name_source)

        try:
            get_cli_profile(name)
        except CliProfileError:
            pass
        else:
            raise ValueError(f"built-in profile already exists: {name}")

        profile = CliProfile.from_custom_command(
            name=name,
            display_name=display_name,
            argv=argv,
        )
        current_profiles = {item.name: item for item in self._load_custom_profiles()}
        current_profiles[profile.name] = profile
        profiles = tuple(current_profiles[key] for key in sorted(current_profiles))
        if len(profiles) > MAX_CUSTOM_PROFILES:
            raise ValueError(f"custom profile limit reached: {MAX_CUSTOM_PROFILES}")

        self._save_custom_profiles(profiles)
        self._set_custom_profiles(profiles)
        return {
            "profile": self._profile_payload(profile),
            "profiles": [self._profile_payload(item) for item in self._all_cli_profiles()],
        }

    async def remove_cli_profile(self, request: dict[str, Any]) -> dict[str, Any]:
        from deck_assistant_core import get_cli_profile
        from deck_assistant_core.cli import CliProfileError

        name = normalize_profile_name(str(request.get("name", "")))
        try:
            get_cli_profile(name)
        except CliProfileError:
            pass
        else:
            raise ValueError(f"built-in profile cannot be removed: {name}")

        profiles = tuple(profile for profile in self._load_custom_profiles() if profile.name != name)
        self._save_custom_profiles(profiles)
        self._set_custom_profiles(profiles)
        return {
            "removed": name,
            "profiles": [self._profile_payload(item) for item in self._all_cli_profiles()],
        }

    async def get_terminal_config(self) -> dict[str, Any]:
        return dict(self._terminal_config())

    async def update_terminal_config(self, request: dict[str, Any]) -> dict[str, Any]:
        config = dict(self._terminal_config())
        config.update(_terminal_config_payload(request or {}))
        self._save_terminal_config(config)
        self.terminal_config = config
        return dict(config)

    async def get_voice_transcription_config(self) -> dict[str, Any]:
        return _voice_transcription_public_payload(self._voice_transcription_config())

    async def update_voice_transcription_config(self, request: dict[str, Any]) -> dict[str, Any]:
        config = dict(self._voice_transcription_config())
        config.update(_voice_transcription_config_payload(request or {}, existing=config))
        self._save_voice_transcription_config(config)
        self.voice_transcription_config = config
        return _voice_transcription_public_payload(config)

    async def transcribe_voice_audio(self, request: dict[str, Any]) -> dict[str, Any]:
        payload = request or {}
        config = self._voice_transcription_config()
        if not bool(config.get("enabled")):
            raise ValueError("external voice transcription is disabled")

        audio_base64 = str(payload.get("audio_base64") or "")
        if not audio_base64:
            raise ValueError("audio_base64 is required")
        try:
            audio_bytes = base64.b64decode(audio_base64, validate=True)
        except ValueError as exc:
            raise ValueError("audio_base64 is invalid") from exc
        if not audio_bytes:
            raise ValueError("audio is empty")
        if len(audio_bytes) > VOICE_TRANSCRIPTION_MAX_BYTES:
            raise ValueError(
                f"audio is too large: {len(audio_bytes)} bytes "
                f"(max {VOICE_TRANSCRIPTION_MAX_BYTES})"
            )

        content_type = _voice_audio_content_type(str(payload.get("content_type") or "audio/webm"))
        filename = _voice_audio_filename(str(payload.get("filename") or "voice-input.webm"))

        result = await asyncio.to_thread(
            _transcribe_with_external_api,
            config,
            audio_bytes,
            content_type,
            filename,
        )
        return result

    async def start_voice_capture(self) -> dict[str, Any]:
        try:
            config = self._voice_transcription_config()
            if not bool(config.get("enabled")):
                raise ValueError("external voice transcription is disabled")
            base_url = _validated_transcription_url(
                str(config.get("base_url") or DEFAULT_VOICE_TRANSCRIPTION_CONFIG["base_url"])
            )
            api_key = str(config.get("api_key") or "").strip()
            if _voice_transcription_api_key_required(base_url) and not api_key:
                raise ValueError("voice transcription API key is required for external endpoints")

            stale_capture = self._voice_capture
            self._voice_capture = None
            if stale_capture is not None:
                await asyncio.to_thread(self._discard_voice_capture, stale_capture)

            selected = _select_voice_capture_tool()
            if selected is None:
                raise ValueError(
                    "no microphone capture tool found; install pipewire (pw-record) "
                    "or alsa-utils (arecord)"
                )
            tool, executable = selected

            fd, path = tempfile.mkstemp(prefix="decky-voice-", suffix=".wav")
            os.close(fd)
            argv = _voice_capture_command(tool, path)
            argv[0] = executable

            try:
                process = subprocess.Popen(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    env=_voice_capture_env(),
                )
            except OSError as exc:
                Path(path).unlink(missing_ok=True)
                raise ValueError(f"could not start microphone capture: {exc}") from exc

            await asyncio.sleep(0.15)
            if process.poll() is not None:
                stderr = b""
                if process.stderr is not None:
                    stderr = process.stderr.read(4096)
                    process.stderr.close()
                Path(path).unlink(missing_ok=True)
                detail = stderr.decode("utf-8", errors="replace").strip()[:200]
                if not detail:
                    detail = f"exit code {process.returncode}"
                raise ValueError(f"microphone capture exited immediately: {detail}")

            token = uuid.uuid4().hex
            self._voice_capture = {
                "process": process,
                "path": path,
                "tool": tool,
                "token": token,
                "started_at": time.monotonic(),
            }
            asyncio.create_task(self._expire_voice_capture(token))
            return {"recording": True, "tool": tool, "error": None}
        except Exception as exc:
            message = _voice_error_message(exc, fallback="Voice input failed.")
            decky.logger.warning("Voice capture start failed: %s", message)
            return {"recording": False, "tool": "", "error": message}

    async def _expire_voice_capture(self, token: str) -> None:
        await asyncio.sleep(VOICE_CAPTURE_MAX_SECONDS)
        capture = self._voice_capture
        if capture is not None and capture.get("token") == token:
            self._voice_capture = None
            decky.logger.info("Voice capture auto-stopped after %.0f seconds", VOICE_CAPTURE_MAX_SECONDS)
            await asyncio.to_thread(self._discard_voice_capture, capture)

    async def stop_voice_capture(self) -> dict[str, Any]:
        try:
            capture = self._voice_capture
            if capture is None:
                raise ValueError("no voice capture in progress")
            self._voice_capture = None

            audio_bytes = await asyncio.to_thread(self._finalize_voice_capture, capture)
            audio_info = _captured_wav_info(audio_bytes)
            if len(audio_bytes) > VOICE_TRANSCRIPTION_MAX_BYTES:
                raise ValueError(
                    f"audio is too large: {len(audio_bytes)} bytes "
                    f"(max {VOICE_TRANSCRIPTION_MAX_BYTES})"
                )

            content_type = "audio/wav"
            filename = "voice-input.wav"
            config = self._voice_transcription_config()
            if not bool(config.get("enabled")):
                raise ValueError("external voice transcription is disabled")

            result = await asyncio.to_thread(
                _transcribe_with_external_api,
                config,
                audio_bytes,
                content_type,
                filename,
            )
            return {**result, **audio_info, "error": None}
        except Exception as exc:
            message = _voice_error_message(exc, fallback="Voice transcription failed.")
            decky.logger.warning("Voice transcription failed: %s", message)
            return {"text": "", "error": message}

    async def cancel_voice_capture(self) -> dict[str, Any]:
        capture = self._voice_capture
        self._voice_capture = None
        if capture is not None:
            await asyncio.to_thread(self._discard_voice_capture, capture)
        return {"cancelled": True}

    async def list_terminal_sessions(self) -> dict[str, Any]:
        manager = self._terminal_manager()
        return {"sessions": [session.to_dict() for session in manager.list_sessions()]}

    async def start_terminal_session(self, request: dict[str, Any] | None = None) -> dict[str, Any]:
        manager = self._terminal_manager()
        payload = request or {}
        profile_name = str(payload.get("profile_name", "bash"))
        cols = _int_payload(payload, "cols", 80)
        rows = _int_payload(payload, "rows", 24)

        self._sync_terminal_profiles()
        # Validate the profile exists. Risk classification is display metadata;
        # command safety is delegated to the underlying CLI (Claude/Codex) and
        # the user's explicit terminal input. The optional per-profile
        # permission-bypass toggle still controls native no-approval launch args.
        self._get_cli_profile(profile_name)

        session = manager.start_session(profile_name, cols=cols, rows=rows)
        return {"session": session.to_dict()}

    async def open_terminal_profile(self, request: dict[str, Any] | None = None) -> dict[str, Any]:
        manager = self._terminal_manager()
        payload = request or {}
        profile_name = str(payload.get("profile_name", "bash"))
        cols = _int_payload(payload, "cols", 80)
        rows = _int_payload(payload, "rows", 24)

        self._sync_terminal_profiles()
        # Validate the profile exists; risk classification is display metadata
        # (see start_terminal_session).
        self._get_cli_profile(profile_name)

        session = manager.open_profile_session(profile_name, cols=cols, rows=rows)
        return {"session": session.to_dict()}

    async def read_terminal_session(self, request: dict[str, Any]) -> dict[str, Any]:
        manager = self._terminal_manager()
        session_id = _session_id_payload(request)
        max_bytes = min(_int_payload(request, "max_bytes", 65536), 131072)
        timeout_seconds = min(_float_payload(request, "timeout_seconds", 0.0), 0.25)

        data = manager.read_session(
            session_id,
            max_bytes=max_bytes,
            timeout_seconds=timeout_seconds,
        )
        decoded = data.decode("utf-8", errors="replace")
        self._record_terminal_output(session_id, decoded)
        links = self._record_terminal_links(session_id, decoded)
        if not links:
            links = self._rescan_terminal_output_tail(session_id)
        session = manager.get_session(session_id)
        return {
            "data": decoded,
            "session": session.to_dict(),
            "links": links,
        }

    async def get_terminal_session_links(self, request: dict[str, Any]) -> dict[str, Any]:
        session_id = _session_id_payload(request)
        links = self._terminal_session_links(session_id)
        if not links:
            links = self._rescan_terminal_output_tail(session_id)
        return {"links": links, "output_tail": self._terminal_output_tail(session_id)}

    async def clear_terminal_session_links(self, request: dict[str, Any]) -> dict[str, Any]:
        session_id = _session_id_payload(request)
        self._suppress_terminal_links(session_id)
        return {"links": []}

    async def read_clipboard_text(self) -> dict[str, Any]:
        return await asyncio.to_thread(_read_system_clipboard_text)

    async def write_terminal_session(self, request: dict[str, Any]) -> dict[str, Any]:
        manager = self._terminal_manager()
        session_id = _session_id_payload(request)
        data = str(request.get("data", ""))
        return {"bytes_written": manager.write_session(session_id, data)}

    async def resize_terminal_session(self, request: dict[str, Any]) -> dict[str, Any]:
        manager = self._terminal_manager()
        session_id = _session_id_payload(request)
        cols = _int_payload(request, "cols", 80)
        rows = _int_payload(request, "rows", 24)

        session = manager.resize_session(session_id, cols=cols, rows=rows)
        return {"session": session.to_dict()}

    async def interrupt_terminal_session(self, request: dict[str, Any]) -> dict[str, Any]:
        manager = self._terminal_manager()
        session_id = _session_id_payload(request)
        return {"bytes_written": manager.send_interrupt(session_id)}

    async def restart_terminal_session(self, request: dict[str, Any]) -> dict[str, Any]:
        manager = self._terminal_manager()
        session_id = _session_id_payload(request)
        self._clear_terminal_links(session_id)
        session = manager.restart_session(session_id)
        return {"session": session.to_dict()}

    async def stop_terminal_session(self, request: dict[str, Any]) -> dict[str, Any]:
        manager = self._terminal_manager()
        session_id = _session_id_payload(request)
        manager.stop_session(session_id)
        self._clear_terminal_links(session_id)
        return {"stopped": True, "session_id": session_id}

    async def stop_all_terminal_sessions(self) -> dict[str, Any]:
        manager = self._terminal_manager()
        stopped_ids = [session.id for session in manager.list_sessions()]
        manager.stop_all_sessions()
        self.terminal_links = {}
        self.terminal_link_buffers = {}
        self.terminal_output_tails = {}
        self.terminal_link_suppressed = set()
        return {"stopped": stopped_ids}

    async def get_storage_plan(self) -> dict[str, Any]:
        from deck_assistant_core import StorageSectionName, plan_storage_report_paths

        plan = plan_storage_report_paths(
            sections=(StorageSectionName.LOGS, StorageSectionName.SCREENSHOTS_VIDEOS),
        )
        return {
            "entries": [entry.to_dict() for entry in plan],
        }

    def _terminal_manager(self) -> Any:
        manager = getattr(self, "pty_sessions", None)
        if manager is None:
            raise RuntimeError("PTY session manager is not initialized.")
        return manager

    def _all_cli_profiles(self) -> tuple[Any, ...]:
        from deck_assistant_core import list_cli_profiles

        return tuple(
            self._apply_profile_permission_mode(profile)
            for profile in (*list_cli_profiles(), *self._sync_terminal_profiles())
        )

    def _get_cli_profile(self, name: str) -> Any:
        profile = self._get_base_cli_profile(name)
        return self._apply_profile_permission_mode(profile)

    def _get_base_cli_profile(self, name: str) -> Any:
        from deck_assistant_core import get_cli_profile
        from deck_assistant_core.cli import CliProfileError

        try:
            return get_cli_profile(name)
        except CliProfileError as not_found:
            try:
                normalized = normalize_profile_name(name)
            except ValueError:
                raise not_found from None
            for profile in self._sync_terminal_profiles():
                if normalize_profile_name(profile.name) == normalized:
                    return profile
            raise

    def _sync_terminal_profiles(self) -> tuple[Any, ...]:
        profiles = self._load_custom_profiles()
        self._set_custom_profiles(profiles)
        return profiles

    def _set_custom_profiles(self, profiles: tuple[Any, ...]) -> None:
        self.custom_profiles = profiles
        manager = getattr(self, "pty_sessions", None)
        if manager is not None:
            manager.set_profiles(self._terminal_profiles_for_manager())

    def _terminal_profiles_for_manager(self) -> tuple[Any, ...]:
        return tuple(
            self._apply_profile_permission_mode(profile)
            for profile in self._load_custom_profiles()
        ) + tuple(
            self._apply_profile_permission_mode(profile)
            for profile in _built_in_profiles_for_overrides()
            if self._profile_permission_bypass_enabled(profile.name)
        )

    def _apply_profile_permission_mode(self, profile: Any) -> Any:
        if not self._profile_permission_bypass_enabled(profile.name):
            return profile
        from deck_assistant_core import apply_cli_permission_bypass

        return apply_cli_permission_bypass(profile)

    def _profile_permission_bypass_enabled(self, name: str) -> bool:
        return is_bypass_enabled(self._profile_permissions(), name)

    def _profile_permissions(self) -> dict[str, dict[str, Any]]:
        permissions = self.profile_permissions
        if permissions is None:
            permissions = self._load_profile_permissions()
            self.profile_permissions = permissions
        return permissions

    def _profile_payload(self, profile: Any) -> dict[str, Any]:
        return _profile_payload(
            profile,
            bypass_enabled=self._profile_permission_bypass_enabled(profile.name),
        )

    def _terminal_config(self) -> dict[str, Any]:
        config = self.terminal_config
        if config is None:
            config = self._load_terminal_config()
            self.terminal_config = config
        return config

    def _release_channel(self) -> str:
        channel = self.release_channel
        if channel is None:
            channel = self._load_release_channel()
            self.release_channel = channel
        return channel

    def _voice_transcription_config(self) -> dict[str, Any]:
        config = self.voice_transcription_config
        if config is None:
            config = self._load_voice_transcription_config()
            self.voice_transcription_config = config
        return config

    def _finalize_voice_capture(self, capture: dict[str, Any]) -> bytes:
        path = str(capture.get("path") or "")
        try:
            _terminate_capture_process(capture["process"])
            if not path:
                return b""
            try:
                return Path(path).read_bytes()
            except OSError:
                return b""
        finally:
            if path:
                Path(path).unlink(missing_ok=True)
            process = capture.get("process")
            stderr = getattr(process, "stderr", None)
            if stderr is not None:
                stderr.close()

    def _discard_voice_capture(self, capture: dict[str, Any]) -> None:
        process = capture.get("process")
        try:
            if process is not None:
                _terminate_capture_process(process)
        except Exception:
            pass
        try:
            path = str(capture.get("path") or "")
            if path:
                Path(path).unlink(missing_ok=True)
        except OSError:
            pass
        try:
            stderr = getattr(process, "stderr", None)
            if stderr is not None:
                stderr.close()
        except Exception:
            pass

    def _terminal_session_links(self, session_id: str) -> list[str]:
        if self._terminal_links_are_suppressed(session_id):
            return []
        return list(self.terminal_links.get(session_id, ()))

    def _terminal_output_tail(self, session_id: str) -> str:
        return str(self.terminal_output_tails.get(session_id, ""))

    def _record_terminal_output(self, session_id: str, output: str) -> None:
        if not output:
            return
        tails = self.terminal_output_tails
        tails[session_id] = f"{tails.get(session_id, '')}{output}"[-TERMINAL_OUTPUT_TAIL_CHARS:]
        if _terminal_auth_completed_after_latest_link(tails[session_id]):
            self._suppress_terminal_links(session_id)

    def _record_terminal_links(self, session_id: str, output: str) -> list[str]:
        if not output:
            return self._terminal_session_links(session_id)
        buffers = self.terminal_link_buffers
        scan_text = f"{buffers.get(session_id, '')}{output}"
        buffers[session_id] = scan_text[-TERMINAL_LINK_TAIL_CHARS:]
        if _terminal_auth_completed_after_latest_link(scan_text):
            self._suppress_terminal_links(session_id)
            return []
        next_links = _extract_terminal_links(scan_text)
        if not next_links:
            return self._terminal_session_links(session_id)

        self.terminal_link_suppressed.discard(session_id)
        return self._store_terminal_links(session_id, next_links)

    def _rescan_terminal_output_tail(self, session_id: str) -> list[str]:
        if self._terminal_links_are_suppressed(session_id):
            return []
        output = self.terminal_output_tails.get(session_id, "")
        if not output:
            return self._terminal_session_links(session_id)
        if _terminal_auth_completed_after_latest_link(output):
            self._suppress_terminal_links(session_id)
            return []
        next_links = _extract_terminal_links(output)
        if not next_links:
            return self._terminal_session_links(session_id)
        return self._store_terminal_links(session_id, next_links)

    def _store_terminal_links(self, session_id: str, next_links: list[str]) -> list[str]:
        links = self.terminal_links
        current = list(links.get(session_id, ()))
        for link in next_links:
            current = [
                existing
                for existing in current
                if existing != link and not _is_shorter_prefix(existing, link)
            ]
            current.insert(0, link)
        links[session_id] = current[:5]
        return list(links[session_id])

    def _clear_terminal_links(self, session_id: str) -> None:
        self.terminal_links.pop(session_id, None)
        self.terminal_link_buffers.pop(session_id, None)
        self.terminal_output_tails.pop(session_id, None)
        self.terminal_link_suppressed.discard(session_id)

    def _suppress_terminal_links(self, session_id: str) -> None:
        self.terminal_links.pop(session_id, None)
        self.terminal_link_buffers.pop(session_id, None)
        self.terminal_link_suppressed.add(session_id)

    def _terminal_links_are_suppressed(self, session_id: str) -> bool:
        return session_id in self.terminal_link_suppressed

    def _load_custom_profiles(self) -> tuple[Any, ...]:
        from deck_assistant_core import CliProfile
        from deck_assistant_core.cli import CliProfileError

        path = _custom_profiles_path()
        if not path.exists():
            return ()

        try:
            raw_profiles = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            decky.logger.warning("Could not read custom CLI profiles: %s", exc)
            return ()

        if not isinstance(raw_profiles, list):
            decky.logger.warning("Custom CLI profile settings must contain a list.")
            return ()

        profiles = []
        for raw_profile in raw_profiles:
            try:
                profile = CliProfile.from_dict(raw_profile)
            except (KeyError, TypeError, ValueError, CliProfileError) as exc:
                decky.logger.warning("Ignoring invalid custom CLI profile: %s", exc)
                continue
            if profile.profile_type == "custom":
                profiles.append(profile)
        return tuple(profiles[:MAX_CUSTOM_PROFILES])

    def _save_custom_profiles(self, profiles: tuple[Any, ...]) -> None:
        path = _custom_profiles_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = [profile.to_dict() for profile in profiles]
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)

    def _load_profile_permissions(self) -> dict[str, dict[str, Any]]:
        path = _profile_permissions_path()
        if not path.exists():
            return {}

        try:
            raw_permissions = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            decky.logger.warning("Could not read profile permissions: %s", exc)
            return {}

        return parse_profile_permissions(raw_permissions)

    def _save_profile_permissions(self, permissions: dict[str, dict[str, Any]]) -> None:
        path = _profile_permissions_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = serialize_profile_permissions(permissions)
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)

    def _load_terminal_config(self) -> dict[str, Any]:
        path = _terminal_config_path()
        if not path.exists():
            return dict(DEFAULT_TERMINAL_CONFIG)

        try:
            raw_config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            decky.logger.warning("Could not read terminal config: %s", exc)
            return dict(DEFAULT_TERMINAL_CONFIG)

        if not isinstance(raw_config, dict):
            decky.logger.warning("Terminal config settings must contain an object.")
            return dict(DEFAULT_TERMINAL_CONFIG)

        config = dict(DEFAULT_TERMINAL_CONFIG)
        config.update(_terminal_config_payload(raw_config))
        return config

    def _save_terminal_config(self, config: dict[str, Any]) -> None:
        path = _terminal_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(DEFAULT_TERMINAL_CONFIG)
        payload.update(_terminal_config_payload(config))
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)

    def _load_release_channel(self) -> str:
        path = _release_channel_path()
        if not path.exists():
            return DEFAULT_RELEASE_CHANNEL

        try:
            raw_config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            decky.logger.warning("Could not read release channel: %s", exc)
            return DEFAULT_RELEASE_CHANNEL

        if not isinstance(raw_config, dict):
            decky.logger.warning("Release channel settings must contain an object.")
            return DEFAULT_RELEASE_CHANNEL

        return _normalize_release_channel(raw_config.get("channel"))

    def _save_release_channel(self, channel: Any) -> None:
        path = _release_channel_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"channel": _normalize_release_channel(channel)}
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)

    def _load_voice_transcription_config(self) -> dict[str, Any]:
        path = _voice_transcription_config_path()
        if not path.exists():
            return dict(DEFAULT_VOICE_TRANSCRIPTION_CONFIG)

        try:
            raw_config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            decky.logger.warning("Could not read voice transcription config: %s", exc)
            return dict(DEFAULT_VOICE_TRANSCRIPTION_CONFIG)

        if not isinstance(raw_config, dict):
            decky.logger.warning("Voice transcription settings must contain an object.")
            return dict(DEFAULT_VOICE_TRANSCRIPTION_CONFIG)

        config = dict(DEFAULT_VOICE_TRANSCRIPTION_CONFIG)
        config.update(_voice_transcription_config_payload(raw_config, existing=config))
        return config

    def _save_voice_transcription_config(self, config: dict[str, Any]) -> None:
        path = _voice_transcription_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(DEFAULT_VOICE_TRANSCRIPTION_CONFIG)
        payload.update(_voice_transcription_config_payload(config, existing=payload))
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)


def _decky_settings_dir() -> Path:
    env_value = os.environ.get("DECKY_PLUGIN_SETTINGS_DIR")
    if env_value:
        return Path(env_value)

    decky_value = str(getattr(decky, "DECKY_PLUGIN_SETTINGS_DIR", "") or "")
    if decky_value:
        return Path(decky_value)

    try:
        from decky_plugin import DECKY_PLUGIN_SETTINGS_DIR
    except Exception:
        return PLUGIN_ROOT / ".decky-settings"
    return Path(DECKY_PLUGIN_SETTINGS_DIR)


def _custom_profiles_path() -> Path:
    return _decky_settings_dir() / CUSTOM_PROFILES_FILENAME


def _profile_permissions_path() -> Path:
    return _decky_settings_dir() / PROFILE_PERMISSIONS_FILENAME


def _terminal_config_path() -> Path:
    return _decky_settings_dir() / TERMINAL_CONFIG_FILENAME


def _release_channel_path() -> Path:
    return _decky_settings_dir() / RELEASE_CHANNEL_FILENAME


def _voice_transcription_config_path() -> Path:
    return _decky_settings_dir() / VOICE_TRANSCRIPTION_CONFIG_FILENAME


def _plugin_current_version(plugin_root: Path = PLUGIN_ROOT) -> str:
    package_path = plugin_root / "package.json"
    try:
        package_payload = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        decky.logger.warning("Could not read plugin package version: %s", exc)
        return "unknown"
    version = str(package_payload.get("version") or "").strip()
    return version or "unknown"


def _fetch_plugin_update_plan(channel: str = DEFAULT_RELEASE_CHANNEL) -> dict[str, Any]:
    channel = _normalize_release_channel(channel)
    current_version = _plugin_current_version()
    try:
        releases = _read_json_url(PLUGIN_UPDATE_RELEASES_URL)
    except Exception as exc:
        decky.logger.warning("Could not fetch plugin update releases: %s", exc)
        return _plugin_update_unavailable_plan(
            current_version=current_version,
            message=f"Could not check GitHub releases: {exc}",
            channel=channel,
        )

    return _plugin_update_plan_from_releases(
        releases,
        current_version=current_version,
        channel=channel,
    )


def _read_json_url(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{PLUGIN_PACKAGE_NAME}/plugin-update",
        },
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 - fixed GitHub Releases URL.
            request,
            timeout=PLUGIN_UPDATE_TIMEOUT_SECONDS,
            context=_plugin_update_ssl_context(url),
        ) as response:
            body = response.read(1024 * 1024)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"GitHub returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"GitHub request failed: {exc.reason}") from exc

    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("GitHub returned invalid JSON") from exc


def _plugin_update_plan_from_releases(
    releases: Any,
    *,
    current_version: str,
    channel: str = DEFAULT_RELEASE_CHANNEL,
) -> dict[str, Any]:
    channel = _normalize_release_channel(channel)
    if not isinstance(releases, list):
        decky.logger.warning("Plugin update release payload was not a list.")
        return _plugin_update_unavailable_plan(
            current_version=current_version,
            message="GitHub release payload was not usable.",
            channel=channel,
        )

    release, asset = _latest_plugin_update_release(releases, channel=channel)
    if release is None or asset is None:
        return _plugin_update_unavailable_plan(
            current_version=current_version,
            message="No compatible Decky AI Assistant release ZIP was found.",
            channel=channel,
        )

    latest_version = _release_version(release)
    tag_name = str(release.get("tag_name") or "")
    if latest_version == "unknown":
        latest_version = tag_name.lstrip("v") or "unknown"

    browser_download_url = str(asset.get("browser_download_url") or "").strip()
    if not browser_download_url:
        return _plugin_update_unavailable_plan(
            current_version=current_version,
            latest_version=latest_version,
            tag_name=tag_name,
            message="Latest release asset is missing a download URL.",
            channel=channel,
        )

    status = "ready"
    message = f"Update {current_version} to {latest_version}."
    if not _version_is_newer(latest_version, current_version):
        status = "up_to_date"
        message = f"Installed version {current_version} is up to date."

    return {
        "status": status,
        "risk": "low_write",
        "channel": channel,
        "current_version": current_version,
        "latest_version": latest_version,
        "tag_name": tag_name,
        "asset_name": str(asset.get("name") or ""),
        "asset_url": browser_download_url,
        "asset_digest": str(asset.get("digest") or ""),
        "html_url": str(release.get("html_url") or ""),
        "message": message,
        "reload_required": status == "ready",
    }


def _plugin_update_unavailable_plan(
    *,
    current_version: str,
    latest_version: str = "",
    tag_name: str = "",
    message: str,
    channel: str = DEFAULT_RELEASE_CHANNEL,
) -> dict[str, Any]:
    channel = _normalize_release_channel(channel)
    return {
        "status": "unavailable",
        "risk": "low_write",
        "channel": channel,
        "current_version": current_version,
        "latest_version": latest_version,
        "tag_name": tag_name,
        "asset_name": "",
        "asset_url": "",
        "asset_digest": "",
        "html_url": "",
        "message": message,
        "reload_required": False,
    }


def _latest_plugin_update_release(
    releases: list[Any],
    *,
    channel: str = DEFAULT_RELEASE_CHANNEL,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    channel = _normalize_release_channel(channel)
    candidates: list[tuple[tuple[Any, ...], dict[str, Any], dict[str, Any]]] = []
    for release in releases:
        if not isinstance(release, dict) or bool(release.get("draft")):
            continue
        if channel == "stable" and bool(release.get("prerelease")):
            continue
        asset = _plugin_update_asset(release)
        if asset is None:
            continue
        version = _release_version(release)
        candidates.append((_version_sort_key(version), release, asset))

    if not candidates:
        return None, None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1], candidates[0][2]


def _plugin_update_asset(release: dict[str, Any]) -> dict[str, Any] | None:
    assets = release.get("assets")
    if not isinstance(assets, list):
        return None
    tag_name = str(release.get("tag_name") or "")
    version = _release_version(release)
    preferred_names = {
        f"{PLUGIN_PACKAGE_NAME}-v{version}.zip",
        f"{PLUGIN_PACKAGE_NAME}-{tag_name}.zip",
        f"{PLUGIN_PACKAGE_NAME}.zip",
    }
    fallback: dict[str, Any] | None = None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        if name in preferred_names:
            return asset
        if fallback is None and name.startswith(f"{PLUGIN_PACKAGE_NAME}-") and name.endswith(".zip"):
            fallback = asset
    return fallback


def _release_version(release: dict[str, Any]) -> str:
    tag_name = str(release.get("tag_name") or "").strip()
    if tag_name.startswith("v"):
        return tag_name[1:]
    return tag_name or "unknown"


def _version_is_newer(candidate: str, current: str) -> bool:
    if candidate == current:
        return False
    candidate_key = _version_sort_key(candidate)
    current_key = _version_sort_key(current)
    if candidate_key[0] == (0, 0, 0) and current_key[0] == (0, 0, 0):
        return candidate != current
    return candidate_key > current_key


def _version_sort_key(version: str) -> tuple[Any, ...]:
    normalized = version.strip().lstrip("v")
    normalized = normalized.split("+", maxsplit=1)[0]
    base, _, prerelease = normalized.partition("-")
    parts: list[int] = []
    for part in base.split("."):
        if part.isdigit():
            parts.append(int(part))
        else:
            match = re.match(r"(\d+)", part)
            parts.append(int(match.group(1)) if match else 0)
    while len(parts) < 3:
        parts.append(0)
    prerelease_rank = 1 if not prerelease else 0
    prerelease_parts: list[tuple[int, int | str]] = []
    for part in re.split(r"[._-]", prerelease):
        if not part:
            continue
        if part.isdigit():
            prerelease_parts.append((1, int(part)))
        else:
            prerelease_parts.append((0, part.lower()))
    return (tuple(parts[:3]), prerelease_rank, tuple(prerelease_parts))


def _download_plugin_update_asset(asset_url: str, expected_digest: str = "") -> tuple[bytes, str]:
    parsed = urlsplit(asset_url)
    if parsed.scheme != "https" or parsed.netloc not in {
        "github.com",
        "objects.githubusercontent.com",
        "github-releases.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }:
        raise ValueError("plugin update asset URL must be a GitHub HTTPS URL")

    request = urllib.request.Request(
        asset_url,
        headers={"User-Agent": f"{PLUGIN_PACKAGE_NAME}/plugin-update"},
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 - validated GitHub HTTPS asset URL.
            request,
            timeout=PLUGIN_UPDATE_TIMEOUT_SECONDS,
            context=_plugin_update_ssl_context(asset_url),
        ) as response:
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > PLUGIN_UPDATE_MAX_BYTES:
                    raise ValueError(
                        f"plugin update archive is too large: {total} bytes "
                        f"(max {PLUGIN_UPDATE_MAX_BYTES})"
                    )
                chunks.append(chunk)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"release asset download returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"release asset download failed: {exc.reason}") from exc

    archive_bytes = b"".join(chunks)
    sha256 = hashlib.sha256(archive_bytes).hexdigest()
    digest = expected_digest.strip().lower()
    if digest.startswith("sha256:") and digest.removeprefix("sha256:") != sha256:
        raise ValueError("release asset sha256 digest did not match GitHub metadata")
    return archive_bytes, sha256


def _plugin_update_ssl_context(url: str) -> ssl.SSLContext | None:
    if urlsplit(url).scheme != "https":
        return None
    ca_bundle = _voice_ca_bundle_path()
    if ca_bundle is not None:
        return ssl.create_default_context(cafile=str(ca_bundle))
    try:
        import certifi  # type: ignore[import-not-found]
    except Exception:
        return ssl.create_default_context()
    certifi_path = Path(str(certifi.where()))
    if certifi_path.is_file():
        return ssl.create_default_context(cafile=str(certifi_path))
    return ssl.create_default_context()


def _install_plugin_update_archive(
    archive_bytes: bytes,
    *,
    plugin_root: Path = PLUGIN_ROOT,
) -> dict[str, int]:
    with tempfile.TemporaryDirectory(prefix=f"{PLUGIN_PACKAGE_NAME}-update-") as temp_dir:
        temp_root = Path(temp_dir)
        bundle_dir = _extract_plugin_update_archive(archive_bytes, temp_root)
        _validate_plugin_update_install_target(
            plugin_root,
            entry_names=[item.name for item in bundle_dir.iterdir()],
        )
        return _replace_plugin_bundle_entries(bundle_dir, plugin_root=plugin_root)


def _validate_plugin_update_install_target(
    plugin_root: Path,
    *,
    entry_names: list[str] | None = None,
) -> None:
    message = _plugin_update_install_target_issue(plugin_root, entry_names=entry_names)
    if message:
        raise PermissionError(message)


def _plugin_update_install_target_issue(
    plugin_root: Path,
    *,
    entry_names: list[str] | None = None,
) -> str:
    plugin_root = plugin_root.resolve()
    if not plugin_root.exists():
        parent = plugin_root.parent
        if _directory_is_writable(parent):
            return ""
        return _plugin_update_permission_message([str(parent)])
    if not plugin_root.is_dir():
        return f"Plugin update target is not a directory: {plugin_root}"

    blocked_dirs: list[str] = []
    if not _directory_is_writable(plugin_root):
        blocked_dirs.append(str(plugin_root))

    for name in entry_names or []:
        target = plugin_root / name
        if not target.exists() or target.is_symlink():
            continue
        if target.is_dir():
            for directory in (target, *[item for item in target.rglob("*") if item.is_dir()]):
                if not _directory_is_writable(directory):
                    blocked_dirs.append(str(directory))
                    if len(blocked_dirs) >= 5:
                        break
        if len(blocked_dirs) >= 5:
            break

    if not blocked_dirs:
        return ""
    return _plugin_update_permission_message(blocked_dirs)


def _directory_is_writable(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.W_OK | os.X_OK)


def _plugin_update_permission_message(blocked_dirs: list[str]) -> str:
    paths = ", ".join(blocked_dirs[:5])
    suffix = "" if len(blocked_dirs) <= 5 else ", ..."
    return (
        "Plugin update cannot replace the installed files because the plugin "
        f"directory is not writable by the Decky plugin process: {paths}{suffix}. "
        "Reinstall from the GitHub Release ZIP or fix the plugin directory "
        "ownership outside Decky, then try again."
    )


def _extract_plugin_update_archive(archive_bytes: bytes, temp_root: Path) -> Path:
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            _validate_plugin_update_archive(archive)
            archive.extractall(temp_root)
    except zipfile.BadZipFile as exc:
        raise ValueError("plugin update archive is not a valid ZIP file") from exc

    bundle_dir = temp_root / PLUGIN_PACKAGE_NAME
    _validate_extracted_plugin_bundle(bundle_dir)
    return bundle_dir


def _validate_plugin_update_archive(archive: zipfile.ZipFile) -> None:
    names = archive.namelist()
    if not names:
        raise ValueError("plugin update archive is empty")

    for member in archive.infolist():
        member_path = _zip_member_path(member.filename)
        if member_path is None:
            continue
        parts = member_path.parts
        if not parts or parts[0] != PLUGIN_PACKAGE_NAME:
            raise ValueError("plugin update archive must contain a decky-ai-assistant top directory")
        if _zip_member_is_symlink(member):
            raise ValueError(f"plugin update archive contains unsupported symlink: {member.filename}")


def _zip_member_path(name: str) -> PurePosixPath | None:
    normalized = name.replace("\\", "/").strip()
    if not normalized:
        return None
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"plugin update archive contains unsafe path: {name}")
    if path.parts and ":" in path.parts[0]:
        raise ValueError(f"plugin update archive contains unsafe path: {name}")
    return path


def _zip_member_is_symlink(member: zipfile.ZipInfo) -> bool:
    return ((member.external_attr >> 16) & 0o170000) == 0o120000


def _validate_extracted_plugin_bundle(bundle_dir: Path) -> None:
    if not bundle_dir.is_dir():
        raise ValueError("plugin update archive did not extract a plugin bundle")

    for relative_path in PLUGIN_UPDATE_REQUIRED_FILES:
        if not (bundle_dir / relative_path).is_file():
            raise ValueError(f"plugin update archive is missing {relative_path}")
    for relative_path in PLUGIN_UPDATE_REQUIRED_DIRS:
        if not (bundle_dir / relative_path).is_dir():
            raise ValueError(f"plugin update archive is missing {relative_path}/")

    try:
        package_payload = json.loads((bundle_dir / "package.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("plugin update package.json is invalid") from exc
    if package_payload.get("name") != PLUGIN_PACKAGE_NAME:
        raise ValueError("plugin update package.json has an unexpected package name")


def _replace_plugin_bundle_entries(bundle_dir: Path, *, plugin_root: Path) -> dict[str, int]:
    plugin_root = plugin_root.resolve()
    bundle_entries = sorted(bundle_dir.iterdir(), key=lambda item: item.name)
    files_written = 0
    directories_written = 0

    with tempfile.TemporaryDirectory(prefix=f"{PLUGIN_PACKAGE_NAME}-backup-") as backup_temp:
        backup_root = Path(backup_temp)
        backups: list[tuple[Path, Path]] = []
        try:
            for source in bundle_entries:
                target = plugin_root / source.name
                backup = backup_root / source.name
                if target.exists() or target.is_symlink():
                    if target.is_dir() and not target.is_symlink():
                        shutil.copytree(target, backup, symlinks=True)
                    else:
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, backup, follow_symlinks=False)
                    backups.append((target, backup))

                _remove_path(target)
                if source.is_dir():
                    shutil.copytree(source, target)
                    directories_written += _count_dirs(source)
                    files_written += _count_files(source)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    files_written += 1
        except Exception as exc:
            decky.logger.warning(
                "Plugin update failed during file replacement; restoring backup: %s",
                exc,
            )
            for target, backup in reversed(backups):
                _remove_path(target)
                if backup.is_dir() and not backup.is_symlink():
                    shutil.copytree(backup, target, symlinks=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, target, follow_symlinks=False)
            raise

    return {"files_written": files_written, "directories_written": directories_written}


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _count_files(path: Path) -> int:
    if path.is_file():
        return 1
    return sum(1 for item in path.rglob("*") if item.is_file())


def _count_dirs(path: Path) -> int:
    if path.is_dir():
        return 1 + sum(1 for item in path.rglob("*") if item.is_dir())
    return 0


def _voice_capture_command(tool: str, path: str) -> list[str]:
    if tool == "pw-record":
        return [
            "pw-record",
            "--media-category",
            "Capture",
            "--rate",
            str(VOICE_CAPTURE_RATE),
            "--channels",
            "1",
            "--format",
            "s16",
            "--container",
            "wav",
            path,
        ]
    if tool == "parecord":
        return [
            "parecord",
            "--file-format=wav",
            f"--rate={VOICE_CAPTURE_RATE}",
            "--channels=1",
            path,
        ]
    if tool == "arecord":
        return [
            "arecord",
            "-q",
            "-f",
            "S16_LE",
            "-r",
            str(VOICE_CAPTURE_RATE),
            "-c",
            "1",
            "-t",
            "wav",
            path,
        ]
    raise ValueError(f"unsupported voice capture tool: {tool}")


def _select_voice_capture_tool() -> tuple[str, str] | None:
    for tool in VOICE_CAPTURE_TOOLS:
        executable = shutil.which(tool)
        if executable is not None:
            return tool, executable
    return None


def _built_in_profiles_for_overrides() -> tuple[Any, ...]:
    from deck_assistant_core import list_cli_profiles

    return list_cli_profiles()


def _profile_payload(profile: Any, *, bypass_enabled: bool = False) -> dict[str, Any]:
    return {
        "name": profile.name,
        "display_name": profile.display_name,
        "executable": profile.executable,
        "argv": list(profile.launch_argv()),
        "risk": profile.risk.value,
        "profile_type": profile.profile_type,
        "permission_bypass_enabled": bypass_enabled,
    }


def _argv_payload(payload: dict[str, Any]) -> tuple[str, ...]:
    command = str(payload.get("command", "")).strip()
    if command:
        try:
            argv = tuple(shlex.split(command))
        except ValueError as exc:
            raise ValueError(f"command argv is invalid: {exc}") from exc
    else:
        raw_argv = payload.get("argv")
        if not isinstance(raw_argv, list):
            raise ValueError("command argv must not be empty")
        argv = tuple(str(part) for part in raw_argv)

    if not argv:
        raise ValueError("command argv must not be empty")
    return argv


def _normalize_release_channel(value: Any) -> str:
    channel = str(value or "").strip().lower()
    if channel in RELEASE_CHANNELS:
        return channel
    return DEFAULT_RELEASE_CHANNEL


def _terminal_config_payload(payload: dict[str, Any]) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if "font_family" in payload:
        font_family = str(payload.get("font_family") or "").strip()
        config["font_family"] = font_family or DEFAULT_TERMINAL_CONFIG["font_family"]
    if "font_size" in payload:
        font_size = _bounded_int(payload.get("font_size"), "font_size", 8, 28)
        config["font_size"] = font_size
    if "dpad_mode" in payload:
        dpad_mode = str(payload.get("dpad_mode") or "").strip()
        if dpad_mode == "navigation":
            dpad_mode = "arrows"
        if dpad_mode not in {"arrows", "scroll"}:
            raise ValueError("dpad_mode must be arrows or scroll")
        config["dpad_mode"] = dpad_mode
    for key in (
        "use_dpad",
        "disable_virtual_keyboard",
        "extra_keys",
        "auto_copy_selection",
        "voice_input",
        "voice_prefer_native_cli",
    ):
        if key in payload:
            config[key] = bool(payload.get(key))
    return config


def _voice_transcription_config_payload(
    payload: dict[str, Any],
    *,
    existing: dict[str, Any],
) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if "enabled" in payload:
        config["enabled"] = bool(payload.get("enabled"))
    if "base_url" in payload:
        base_url = str(payload.get("base_url") or "").strip()
        if not base_url:
            base_url = DEFAULT_VOICE_TRANSCRIPTION_CONFIG["base_url"]
        config["base_url"] = _validated_transcription_url(base_url)
    if "model" in payload:
        model = str(payload.get("model") or "").strip()
        if not model:
            model = DEFAULT_VOICE_TRANSCRIPTION_CONFIG["model"]
        if not re.fullmatch(r"[A-Za-z0-9._:/+-]{1,96}", model):
            raise ValueError("voice transcription model contains unsupported characters")
        config["model"] = model
    if "api_key" in payload:
        api_key = str(payload.get("api_key") or "")
        if api_key:
            config["api_key"] = api_key.strip()
    if bool(payload.get("clear_api_key")):
        config["api_key"] = ""
    elif "api_key" not in config:
        config["api_key"] = str(existing.get("api_key") or "")
    return config


def _voice_transcription_public_payload(config: dict[str, Any]) -> dict[str, Any]:
    base_url = str(config.get("base_url") or DEFAULT_VOICE_TRANSCRIPTION_CONFIG["base_url"])
    return {
        "enabled": bool(config.get("enabled")),
        "base_url": base_url,
        "model": str(config.get("model") or DEFAULT_VOICE_TRANSCRIPTION_CONFIG["model"]),
        "api_key_required": _voice_transcription_api_key_required(base_url),
        "api_key_configured": bool(str(config.get("api_key") or "").strip()),
    }


def _validated_transcription_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError("voice transcription base_url must be an HTTP(S) URL")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("voice transcription base_url must use HTTPS outside localhost")
    return value


def _voice_transcription_api_key_required(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.hostname not in {"localhost", "127.0.0.1", "::1"}


def _voice_audio_content_type(value: str) -> str:
    content_type = value.split(";", maxsplit=1)[0].strip().lower()
    if not content_type.startswith("audio/"):
        raise ValueError("voice audio content_type must start with audio/")
    return content_type[:96]


def _voice_audio_filename(value: str) -> str:
    filename = Path(value).name or "voice-input.webm"
    filename = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    return filename[:96] or "voice-input.webm"


def _transcribe_with_external_api(
    config: dict[str, Any],
    audio_bytes: bytes,
    content_type: str,
    filename: str,
) -> dict[str, Any]:
    base_url = _validated_transcription_url(
        str(config.get("base_url") or DEFAULT_VOICE_TRANSCRIPTION_CONFIG["base_url"])
    )
    model = str(config.get("model") or DEFAULT_VOICE_TRANSCRIPTION_CONFIG["model"])
    api_key = str(config.get("api_key") or "").strip()
    parsed = urlsplit(base_url)
    is_local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if not api_key and not is_local:
        raise ValueError("voice transcription API key is required for external endpoints")

    fields = {
        "model": model,
        "response_format": "json",
    }
    body, multipart_content_type = _build_multipart_form_data(
        fields=fields,
        file_field="file",
        filename=filename,
        content_type=content_type,
        file_bytes=audio_bytes,
    )
    headers = {
        "Content-Type": multipart_content_type,
        "User-Agent": "decky-ai-assistant/voice-transcription",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(base_url, data=body, headers=headers, method="POST")
    open_kwargs: dict[str, Any] = {"timeout": VOICE_TRANSCRIPTION_TIMEOUT_SECONDS}
    ssl_context = _voice_transcription_ssl_context(base_url)
    if ssl_context is not None:
        open_kwargs["context"] = ssl_context
    try:
        with urllib.request.urlopen(  # noqa: S310 - user-configured HTTPS endpoint.
            request,
            **open_kwargs,
        ) as response:
            raw_body = response.read(256 * 1024)
            response_content_type = response.headers.get("content-type", "")
    except urllib.error.HTTPError as exc:
        error_body = exc.read(4096).decode("utf-8", errors="replace")
        detail = _voice_api_error_detail(error_body)
        raise ValueError(f"voice transcription API returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"voice transcription API request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ValueError("voice transcription API request timed out") from exc

    decoded = raw_body.decode("utf-8", errors="replace")
    if "application/json" in response_content_type.lower():
        try:
            payload = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise ValueError("voice transcription API returned invalid JSON") from exc
        text = str(payload.get("text") or "").strip() if isinstance(payload, dict) else ""
    else:
        text = decoded.strip()
    if not text:
        raise ValueError("voice transcription API returned no text")
    return {"text": text}


def _voice_transcription_ssl_context(base_url: str) -> ssl.SSLContext | None:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https":
        return None
    ca_bundle = _voice_ca_bundle_path()
    if ca_bundle is None:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=str(ca_bundle))


def _voice_ca_bundle_path() -> Path | None:
    for key in VOICE_CA_BUNDLE_ENV_KEYS:
        value = str(os.environ.get(key) or "").strip()
        if not value:
            continue
        path = Path(value)
        if path.is_file():
            return path
    for value in VOICE_CA_BUNDLE_PATHS:
        path = Path(value)
        if path.is_file():
            return path
    return None


def _captured_wav_info(audio_bytes: bytes) -> dict[str, Any]:
    if len(audio_bytes) < VOICE_CAPTURE_MIN_BYTES:
        raise ValueError("no audio was captured")

    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            frame_count = wav_file.getnframes()
            frame_rate = wav_file.getframerate()
            channel_count = wav_file.getnchannels()
    except (EOFError, wave.Error) as exc:
        raise ValueError("captured audio is not a valid WAV file") from exc

    if frame_rate <= 0 or frame_count <= 0:
        raise ValueError("no audio frames were captured")

    duration_seconds = frame_count / frame_rate
    return {
        "audio_bytes": len(audio_bytes),
        "duration_seconds": round(duration_seconds, 3),
        "sample_rate": frame_rate,
        "channels": channel_count,
    }


def _voice_api_error_detail(error_body: str) -> str:
    text = _sanitize_voice_error_text(error_body)
    try:
        payload = json.loads(error_body)
    except json.JSONDecodeError:
        return text or "request failed"
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            error_type = error.get("type")
            if isinstance(message, str) and message.strip():
                detail = message.strip()
                if isinstance(error_type, str) and error_type.strip():
                    detail = f"{detail} ({error_type.strip()})"
                return _sanitize_voice_error_text(detail)
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return _sanitize_voice_error_text(message)
    return text or "request failed"


def _voice_error_message(error: Exception, *, fallback: str) -> str:
    text = _sanitize_voice_error_text(str(error))
    return text or fallback


def _sanitize_voice_error_text(value: str) -> str:
    text = value.replace("\x00", "").strip()
    text = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted>", text)
    text = re.sub(
        r"(?i)(api[_ -]?key[\"':= ]+)[A-Za-z0-9._~+/=-]{12,}",
        r"\1<redacted>",
        text,
    )
    return text[:500]


def _build_multipart_form_data(
    *,
    fields: dict[str, str],
    file_field: str,
    filename: str,
    content_type: str,
    file_bytes: bytes,
) -> tuple[bytes, str]:
    boundary = f"decky-ai-assistant-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("ascii"),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{filename}"\r\n'
            ).encode("ascii"),
            f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


_X11_SELECTION_NOTIFY = 31
_CLIPBOARD_DISPLAYS: tuple[str, ...] = (":0", ":1")
_CLIPBOARD_SELECTIONS: tuple[bytes, ...] = (b"CLIPBOARD", b"PRIMARY")
_x11_lib: "ctypes.CDLL | None" = None
_x11_load_failed = False


class _XSelectionEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("requestor", ctypes.c_ulong),
        ("selection", ctypes.c_ulong),
        ("target", ctypes.c_ulong),
        ("property", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
    ]


class _XEvent(ctypes.Union):
    _fields_ = [
        ("type", ctypes.c_int),
        ("xselection", _XSelectionEvent),
        ("pad", ctypes.c_long * 24),
    ]


def _load_libx11() -> "ctypes.CDLL | None":
    """Load libX11 once and bind the symbols used for selection reads.

    Steam Deck Gaming Mode has no wl-paste/xclip/xsel and klipper is desktop
    only, but the gamescope Xwayland selections (DISPLAY :0/:1) hold the same
    clipboard that the Steam UI and the plugin write to. Reading them directly
    through libX11 is the one focus-independent path that works in Gaming Mode.
    """

    global _x11_lib, _x11_load_failed
    if _x11_lib is not None or _x11_load_failed:
        return _x11_lib
    library_name = ctypes.util.find_library("X11") or "libX11.so.6"
    try:
        lib = ctypes.CDLL(library_name)
    except OSError:
        _x11_load_failed = True
        return None

    atom = ctypes.c_ulong
    display_p = ctypes.c_void_p
    window = ctypes.c_ulong
    lib.XOpenDisplay.restype = display_p
    lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    lib.XInternAtom.restype = atom
    lib.XInternAtom.argtypes = [display_p, ctypes.c_char_p, ctypes.c_int]
    lib.XDefaultRootWindow.restype = window
    lib.XDefaultRootWindow.argtypes = [display_p]
    lib.XCreateSimpleWindow.restype = window
    lib.XCreateSimpleWindow.argtypes = [
        display_p, window, ctypes.c_int, ctypes.c_int,
        ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_ulong,
    ]
    lib.XGetSelectionOwner.restype = window
    lib.XGetSelectionOwner.argtypes = [display_p, atom]
    lib.XConvertSelection.argtypes = [display_p, atom, atom, atom, window, ctypes.c_ulong]
    lib.XPending.restype = ctypes.c_int
    lib.XPending.argtypes = [display_p]
    lib.XNextEvent.argtypes = [display_p, ctypes.c_void_p]
    lib.XGetWindowProperty.restype = ctypes.c_int
    lib.XGetWindowProperty.argtypes = [
        display_p, window, atom, ctypes.c_long, ctypes.c_long, ctypes.c_int, atom,
        ctypes.POINTER(atom), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
    ]
    lib.XDestroyWindow.argtypes = [display_p, window]
    lib.XFree.argtypes = [ctypes.c_void_p]
    lib.XFlush.argtypes = [display_p]
    lib.XCloseDisplay.argtypes = [display_p]
    _x11_lib = lib
    return lib


def _read_x11_selection(
    lib: "ctypes.CDLL", display_name: bytes, selection_name: bytes, timeout: float
) -> "str | None":
    """Return the selection text, "" if empty/unowned, or None if unreachable."""

    dpy = lib.XOpenDisplay(display_name)
    if not dpy:
        return None
    try:
        selection = lib.XInternAtom(dpy, selection_name, False)
        utf8 = lib.XInternAtom(dpy, b"UTF8_STRING", False)
        prop = lib.XInternAtom(dpy, b"DECKY_AI_CLIP", False)
        if lib.XGetSelectionOwner(dpy, selection) == 0:
            return ""
        root = lib.XDefaultRootWindow(dpy)
        win = lib.XCreateSimpleWindow(dpy, root, 0, 0, 1, 1, 0, 0, 0)
        try:
            lib.XConvertSelection(dpy, selection, utf8, prop, win, 0)
            lib.XFlush(dpy)
            deadline = time.monotonic() + timeout
            event = _XEvent()
            while time.monotonic() < deadline:
                while lib.XPending(dpy):
                    lib.XNextEvent(dpy, ctypes.byref(event))
                    if event.type != _X11_SELECTION_NOTIFY:
                        continue
                    if event.xselection.property == 0:
                        return ""
                    actual_type = ctypes.c_ulong()
                    actual_format = ctypes.c_int()
                    nitems = ctypes.c_ulong()
                    bytes_after = ctypes.c_ulong()
                    data = ctypes.POINTER(ctypes.c_ubyte)()
                    status = lib.XGetWindowProperty(
                        dpy, win, prop, 0, CLIPBOARD_MAX_CHARS, False, 0,
                        ctypes.byref(actual_type), ctypes.byref(actual_format),
                        ctypes.byref(nitems), ctypes.byref(bytes_after), ctypes.byref(data),
                    )
                    if status != 0 or not data:
                        return ""
                    try:
                        raw = ctypes.string_at(data, nitems.value)
                    finally:
                        lib.XFree(data)
                    return raw.decode("utf-8", "replace")
                time.sleep(0.005)
            return ""
        finally:
            lib.XDestroyWindow(dpy, win)
    finally:
        lib.XCloseDisplay(dpy)


def _read_x11_clipboard_text() -> "dict[str, Any] | None":
    lib = _load_libx11()
    if lib is None:
        return None

    displays: list[bytes] = []
    env_display = os.environ.get("DISPLAY")
    candidates = ((env_display,) if env_display else ()) + _CLIPBOARD_DISPLAYS
    for name in candidates:
        encoded = name.encode()
        if encoded and encoded not in displays:
            displays.append(encoded)

    last_error: str | None = None
    for display_name in displays:
        for selection_name in _CLIPBOARD_SELECTIONS:
            try:
                text = _read_x11_selection(
                    lib, display_name, selection_name, CLIPBOARD_TIMEOUT_SECONDS
                )
            except Exception as exc:  # defensive: ctypes/X11 failures stay non-fatal
                last_error = (
                    f"x11 {display_name.decode(errors='replace')} "
                    f"{selection_name.decode()}: {exc}"
                )
                continue
            if text is None:
                continue
            text = _clipboard_process_text(text)
            if text:
                source = f"x11:{display_name.decode(errors='replace')}:{selection_name.decode()}"
                return {"text": text, "source": source, "error": None}
    if last_error is not None:
        return {"text": "", "source": None, "error": last_error}
    return None


def _read_system_clipboard_text() -> dict[str, Any]:
    x11_result = _read_x11_clipboard_text()
    if x11_result is not None:
        return x11_result
    return {
        "text": "",
        "source": None,
        "error": "no X11 clipboard reader available",
    }


def _voice_capture_env() -> dict[str, str]:
    env = dict(os.environ)
    runtime_dir = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if Path(runtime_dir).exists():
        env["XDG_RUNTIME_DIR"] = runtime_dir
        session_bus = Path(runtime_dir) / "bus"
        if session_bus.exists():
            env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={session_bus}")
    return env


def _terminate_capture_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    try:
        process.send_signal(signal.SIGINT)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        if process.poll() is not None:
            return
        try:
            process.kill()
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def _clipboard_process_text(value: str) -> str:
    text = value.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    if text.endswith("\n"):
        text = text[:-1]
    return text[:CLIPBOARD_MAX_CHARS]


def _terminal_link_url_is_auth(link: str) -> bool:
    try:
        host = (urlsplit(link).hostname or "").lower()
    except ValueError:
        host = ""
    if host and host.split(".", 1)[0] in AUTH_LINK_HOST_LABELS:
        return True
    return bool(AUTH_LINK_URL_HINT_PATTERN.search(link))


def _terminal_link_is_auth(link: str, scan_text: str, start: int, end: int) -> bool:
    if _terminal_link_url_is_auth(link):
        return True
    window_start = max(0, start - AUTH_LINK_CONTEXT_WINDOW_CHARS)
    window_end = min(len(scan_text), end + AUTH_LINK_CONTEXT_WINDOW_CHARS)
    context = _normalize_terminal_text(scan_text[window_start:window_end])
    return bool(AUTH_LINK_CONTEXT_PATTERN.search(context))


def _extract_terminal_links(output: str) -> list[str]:
    links: list[str] = []
    for scan_text in (output, _unwrap_terminal_urls(output)):
        for match in TERMINAL_URL_PATTERN.finditer(scan_text):
            link = match.group(0).rstrip(TRAILING_URL_PUNCTUATION)
            if not link or _looks_like_incomplete_terminal_url(link) or _is_loopback_terminal_url(link):
                continue
            if not _terminal_link_is_auth(link, scan_text, match.start(), match.end()):
                continue
            if any(existing == link or _is_shorter_prefix(link, existing) for existing in links):
                continue
            links = [existing for existing in links if not _is_shorter_prefix(existing, link)]
            links.append(link)
    return links


def _unwrap_terminal_urls(output: str) -> str:
    text = _normalize_terminal_text(output)
    lines = text.split("\n")
    if len(lines) <= 1:
        return text

    unwrapped: list[str] = []
    current = lines[0]
    line_index = 1
    while line_index < len(lines):
        line = lines[line_index]
        if _line_continues_terminal_url(current, line):
            current = current.rstrip() + line.lstrip()
            line_index += 1
        elif not line.strip():
            next_index = _next_non_empty_line_index(lines, line_index + 1)
            if next_index is not None and _line_continues_terminal_url(current, lines[next_index]):
                current = current.rstrip() + lines[next_index].lstrip()
                line_index = next_index + 1
            else:
                unwrapped.append(current)
                current = line
                line_index += 1
        else:
            unwrapped.append(current)
            current = line
            line_index += 1
    unwrapped.append(current)
    return "\n".join(unwrapped)


def _next_non_empty_line_index(lines: list[str], start: int) -> int | None:
    for index in range(start, len(lines)):
        if lines[index].strip():
            return index
    return None


def _normalize_terminal_text(output: str) -> str:
    text = ANSI_ESCAPE_PATTERN.sub("", output)
    # Some CLIs running in a PTY emit CRCRLF. Treat the whole run as one line
    # break so wrapped URLs are not split by artificial blank lines.
    text = re.sub(r"\r+\n", "\n", text)
    return text.replace("\r", "\n")


def _line_continues_terminal_url(previous_line: str, next_line: str) -> bool:
    previous = previous_line.rstrip()
    next_part = next_line.lstrip()
    if (
        not previous
        or not next_part
        or not URL_CONTINUATION_START_PATTERN.match(next_part)
        or not _looks_like_url_continuation_fragment(next_part)
    ):
        return False

    matches = list(TERMINAL_URL_PATTERN.finditer(previous))
    if not matches:
        return False
    match = matches[-1]
    if match.end() != len(previous):
        return False

    link = match.group(0).rstrip(TRAILING_URL_PUNCTUATION)
    if not link:
        return False
    if _looks_like_oauth_url(link):
        return True
    if _looks_like_incomplete_terminal_url(link):
        return True
    return len(link) >= 80 and bool(URL_QUERY_PART_PATTERN.search(next_part[:24]))


def _looks_like_url_continuation_fragment(next_part: str) -> bool:
    token = next_part.split(maxsplit=1)[0].rstrip(TRAILING_URL_PUNCTUATION)
    if not token or not re.fullmatch(r"[A-Za-z0-9%._~:/?#\[\]@!$&'()*+,;=-]+", token):
        return False
    if any(character in token for character in "%&=/?#:+_.-"):
        return True
    return (
        len(token) >= 24
        and bool(re.search(r"[A-Z]", token))
        and bool(re.search(r"[a-z]", token))
        and bool(re.search(r"[0-9]", token))
    )


def _looks_like_oauth_url(link: str) -> bool:
    lowered = link.lower()
    return "/oauth/" in lowered or "oauth2" in lowered or "/authorize" in lowered


def _looks_like_incomplete_terminal_url(link: str) -> bool:
    try:
        parsed = urlsplit(link)
    except ValueError:
        return True
    if not parsed.scheme or not parsed.netloc:
        return True

    if re.search(r"%(?:[0-9A-Fa-f])?$", link):
        return True

    if parsed.query:
        last_part = re.split(r"[&;]", parsed.query)[-1]
        if ("&" in parsed.query or ";" in parsed.query) and "=" not in last_part:
            return True
        if _looks_like_oauth_url(link) and last_part.endswith("="):
            return True
    return False


def _is_loopback_terminal_url(link: str) -> bool:
    try:
        parsed = urlsplit(link)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if host == "localhost" or host == "::1":
        return True
    if host.startswith("127."):
        return True
    return host == "0.0.0.0"


def _terminal_auth_completed_after_latest_link(output: str) -> bool:
    text = _unwrap_terminal_urls(output)
    latest_link_end = -1
    for match in TERMINAL_URL_PATTERN.finditer(text):
        link = match.group(0).rstrip(TRAILING_URL_PUNCTUATION)
        if (
            link
            and not _looks_like_incomplete_terminal_url(link)
            and not _is_loopback_terminal_url(link)
        ):
            latest_link_end = match.end()

    if latest_link_end < 0:
        return False

    return any(match.start() >= latest_link_end for match in AUTH_COMPLETION_PATTERN.finditer(text))


def _is_shorter_prefix(existing: str, candidate: str) -> bool:
    return len(existing) >= 32 and len(existing) < len(candidate) and candidate.startswith(existing)


def _bounded_int(value: Any, key: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return parsed


def _session_id_payload(payload: dict[str, Any]) -> str:
    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        raise ValueError("session_id must not be empty")
    return session_id


def _int_payload(payload: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(payload.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc


def _float_payload(payload: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(payload.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc
