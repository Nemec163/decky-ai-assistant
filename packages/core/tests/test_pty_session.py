from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest

from deck_assistant_core import CliProfile, PtySessionError, PtySessionManager
from deck_assistant_core.cli import managed_cli_profile_workspace_dir
from deck_assistant_core.pty_session import build_terminal_child_env


def _requires_posix_bash() -> bool:
    return os.name != "posix" or shutil.which("bash") is None


@unittest.skipIf(_requires_posix_bash(), "PTY smoke tests require POSIX bash")
class PtySessionManagerTests(unittest.TestCase):
    def test_start_write_read_and_stop_bash_session(self) -> None:
        manager = PtySessionManager()
        marker = b"__DECKY_PTY_READY__"

        try:
            session = manager.start_session("bash", cols=100, rows=30)

            self.assertEqual(session.profile_name, "bash")
            self.assertEqual(session.cols, 100)
            self.assertEqual(session.rows, 30)
            self.assertTrue(session.running)

            written = manager.write_session(
                session.id,
                "printf '__DECKY_PTY_READY__\\n'; exit\n",
            )
            output = self._read_until(manager, session.id, marker)

            self.assertGreater(written, 0)
            self.assertIn(marker, output)
        finally:
            manager.stop_all_sessions()

        self.assertEqual(manager.list_sessions(), ())

    def test_child_environment_removes_decky_loader_library_overrides(self) -> None:
        original_ld_library_path = os.environ.get("LD_LIBRARY_PATH")
        os.environ["LD_LIBRARY_PATH"] = "/tmp/decky-runtime-libs"
        manager = PtySessionManager()
        marker = b"__LD_LIBRARY_PATH__<>"

        try:
            session = manager.start_session("bash")
            manager.write_session(
                session.id,
                "printf '__LD_LIBRARY_PATH__<%s>\\n' \"$LD_LIBRARY_PATH\"; exit\n",
            )
            output = self._read_until(manager, session.id, marker)

            self.assertIn(marker, output)
        finally:
            if original_ld_library_path is None:
                os.environ.pop("LD_LIBRARY_PATH", None)
            else:
                os.environ["LD_LIBRARY_PATH"] = original_ld_library_path
            manager.stop_all_sessions()

    def test_custom_profiles_are_available_to_pty_manager(self) -> None:
        custom_profile = CliProfile.from_custom_command(
            name="custom-bash",
            display_name="Custom Bash",
            argv=["bash"],
        )
        manager = PtySessionManager(profiles=(custom_profile,))
        marker = b"__CUSTOM_PROFILE__"

        try:
            session = manager.start_session("custom-bash")

            self.assertEqual(session.profile_name, "custom-bash")
            self.assertEqual(session.display_name, "Custom Bash")

            manager.write_session(
                session.id,
                "printf '__CUSTOM_PROFILE__\\n'; exit\n",
            )
            output = self._read_until(manager, session.id, marker)

            self.assertIn(marker, output)
        finally:
            manager.stop_all_sessions()

    def test_claude_profile_uses_stable_workspace_when_available(self) -> None:
        original_home = os.environ.get("HOME")
        original_xdg_data_home = os.environ.get("XDG_DATA_HOME")
        claude_profile = CliProfile(
            name="claude",
            display_name="Claude Code",
            executable="bash",
            version_args=None,
        )
        manager = PtySessionManager(profiles=(claude_profile,))

        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["HOME"] = temp_dir
            os.environ.pop("XDG_DATA_HOME", None)
            workspace = managed_cli_profile_workspace_dir("claude")
            os.makedirs(workspace, exist_ok=True)
            marker = f"__CLAUDE_CWD__<{workspace}>".encode("utf-8")

            try:
                session = manager.start_session("claude")
                manager.write_session(
                    session.id,
                    "printf '__CLAUDE_CWD__<%s>\\n' \"$PWD\"; exit\n",
                )
                output = self._read_until(manager, session.id, marker)

                self.assertEqual(session.cwd, workspace)
                self.assertIn(marker, output)
            finally:
                _restore_env("HOME", original_home)
                _restore_env("XDG_DATA_HOME", original_xdg_data_home)
                manager.stop_all_sessions()

    def test_codex_profile_uses_stable_workspace_when_available(self) -> None:
        original_home = os.environ.get("HOME")
        original_xdg_data_home = os.environ.get("XDG_DATA_HOME")
        codex_profile = CliProfile(
            name="codex",
            display_name="Codex CLI",
            executable="bash",
            version_args=None,
        )
        manager = PtySessionManager(profiles=(codex_profile,))

        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["HOME"] = temp_dir
            os.environ.pop("XDG_DATA_HOME", None)
            workspace = managed_cli_profile_workspace_dir("codex")
            os.makedirs(workspace, exist_ok=True)
            marker = f"__CODEX_CWD__<{workspace}>".encode("utf-8")

            try:
                session = manager.start_session("codex")
                manager.write_session(
                    session.id,
                    "printf '__CODEX_CWD__<%s>\\n' \"$PWD\"; exit\n",
                )
                output = self._read_until(manager, session.id, marker)

                self.assertEqual(session.cwd, workspace)
                self.assertIn(marker, output)
            finally:
                _restore_env("HOME", original_home)
                _restore_env("XDG_DATA_HOME", original_xdg_data_home)
                manager.stop_all_sessions()

    def test_terminal_child_env_keeps_path_hints_and_terminal_metadata(self) -> None:
        original_xdg_data_home = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = "/tmp/decky-ai-data"
        try:
            env = build_terminal_child_env(
                executable_path="/usr/bin/bash",
                cols=101,
                rows=31,
                cwd="/home/deck",
                shell_path="/usr/bin/bash",
            )
        finally:
            if original_xdg_data_home is None:
                os.environ.pop("XDG_DATA_HOME", None)
            else:
                os.environ["XDG_DATA_HOME"] = original_xdg_data_home

        self.assertNotIn("LD_LIBRARY_PATH", env)
        self.assertEqual(env["TERM"], "xterm-256color")
        self.assertEqual(env["COLORTERM"], "truecolor")
        self.assertEqual(env["COLUMNS"], "101")
        self.assertEqual(env["LINES"], "31")
        self.assertEqual(env["PWD"], "/home/deck")
        self.assertEqual(env["SHELL"], "/usr/bin/bash")
        self.assertEqual(env["XDG_DATA_HOME"], "/tmp/decky-ai-data")
        self.assertIn(
            "/tmp/decky-ai-data/decky-ai-assistant/npm/node_modules/.bin",
            env["PATH"].split(os.pathsep),
        )
        self.assertIn("/usr/bin", env["PATH"].split(os.pathsep))

    def test_resize_updates_session_snapshot(self) -> None:
        manager = PtySessionManager()

        try:
            session = manager.start_session("bash")
            resized = manager.resize_session(session.id, cols=120, rows=40)

            self.assertEqual(resized.id, session.id)
            self.assertEqual(resized.cols, 120)
            self.assertEqual(resized.rows, 40)
            self.assertEqual(manager.get_session(session.id).cols, 120)
            self.assertEqual(manager.get_session(session.id).rows, 40)
        finally:
            manager.stop_all_sessions()

    def test_restart_keeps_session_id_with_new_process(self) -> None:
        manager = PtySessionManager()
        marker = b"__DECKY_PTY_RESTARTED__"

        try:
            session = manager.start_session("bash", cols=90, rows=25)
            restarted = manager.restart_session(session.id)

            self.assertEqual(restarted.id, session.id)
            self.assertEqual(restarted.profile_name, "bash")
            self.assertEqual(restarted.cols, 90)
            self.assertEqual(restarted.rows, 25)
            self.assertNotEqual(restarted.pid, session.pid)
            self.assertTrue(restarted.running)

            manager.write_session(
                restarted.id,
                "printf '__DECKY_PTY_RESTARTED__\\n'; exit\n",
            )
            output = self._read_until(manager, restarted.id, marker)

            self.assertIn(marker, output)
        finally:
            manager.stop_all_sessions()

    def test_open_profile_session_reuses_running_profile_session(self) -> None:
        manager = PtySessionManager()

        try:
            first = manager.open_profile_session("bash", cols=90, rows=25)
            second = manager.open_profile_session("bash", cols=100, rows=30)

            self.assertEqual(second.id, first.id)
            self.assertEqual(second.pid, first.pid)
            self.assertEqual(second.cols, 100)
            self.assertEqual(second.rows, 30)
            self.assertEqual(len(manager.list_sessions()), 1)
        finally:
            manager.stop_all_sessions()

    def test_open_transient_session_reuses_running_profile_session(self) -> None:
        manager = PtySessionManager()
        setup_profile = CliProfile.from_custom_command(
            name="setup-claude-auth",
            display_name="Claude Code setup",
            argv=["bash"],
        )

        try:
            first = manager.open_transient_session(setup_profile, cols=90, rows=25)
            second = manager.open_transient_session(setup_profile, cols=100, rows=30)

            self.assertEqual(second.id, first.id)
            self.assertEqual(second.pid, first.pid)
            self.assertEqual(second.profile_name, "setup-claude-auth")
            self.assertEqual(second.cols, 100)
            self.assertEqual(second.rows, 30)
            self.assertEqual(len(manager.list_sessions()), 1)
        finally:
            manager.stop_all_sessions()

    def test_open_transient_session_reuses_mixed_case_profile(self) -> None:
        manager = PtySessionManager()
        profile = CliProfile.from_custom_command(
            name="Setup-Claude-Auth",
            display_name="Claude Code setup",
            argv=["bash"],
        )

        try:
            first = manager.open_transient_session(profile, cols=90, rows=25)
            second = manager.open_transient_session(profile, cols=90, rows=25)

            self.assertEqual(second.id, first.id)
            self.assertEqual(second.pid, first.pid)
            self.assertEqual(len(manager.list_sessions()), 1)
        finally:
            manager.stop_all_sessions()

    def test_missing_executable_fails_without_creating_session(self) -> None:
        manager = PtySessionManager(which=lambda executable: None)

        with self.assertRaises(PtySessionError):
            manager.start_session("bash")

        self.assertEqual(manager.list_sessions(), ())

    def test_max_sessions_limit_is_enforced(self) -> None:
        manager = PtySessionManager(max_sessions=1)

        try:
            manager.start_session("bash")

            with self.assertRaises(PtySessionError):
                manager.start_session("bash")
        finally:
            manager.stop_all_sessions()

    def test_invalid_dimensions_are_rejected(self) -> None:
        manager = PtySessionManager()

        with self.assertRaises(ValueError):
            manager.start_session("bash", cols=0, rows=24)

        with self.assertRaises(ValueError):
            manager.start_session("bash", cols=80, rows=0)

    def _read_until(
        self,
        manager: PtySessionManager,
        session_id: str,
        marker: bytes,
        *,
        timeout_seconds: float = 5.0,
    ) -> bytes:
        deadline = time.monotonic() + timeout_seconds
        output = b""
        while time.monotonic() < deadline:
            output += manager.read_session(session_id, timeout_seconds=0.05)
            if marker in output:
                return output
        self.fail(f"timed out waiting for PTY marker {marker!r}; output={output!r}")


def _restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
