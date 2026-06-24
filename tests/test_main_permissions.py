from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
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
from main import Plugin


class _StubManager:
    """Minimal PTY manager stand-in that records launch attempts.

    The real ``PtySessionManager`` spawns a subprocess; we only need to know
    whether ``start_terminal_session`` reached the manager (i.e. the launch
    gate let it through) without actually starting a process.
    """

    def __init__(self) -> None:
        self.started: list[str] = []
        self.profiles: tuple[object, ...] = ()

    def set_profiles(self, profiles: tuple[object, ...]) -> None:
        self.profiles = tuple(profiles)

    def start_session(self, profile_name: str, *, cols: int, rows: int) -> object:
        self.started.append(profile_name)
        return types.SimpleNamespace(to_dict=lambda: {"id": "stub", "profile_name": profile_name})


class _PluginPermissionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.settings_dir = Path(self._tmp.name)
        self._env_patch = mock.patch.dict(
            os.environ, {"DECKY_PLUGIN_SETTINGS_DIR": str(self.settings_dir)}
        )
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        self.addCleanup(self._tmp.cleanup)

    def _permissions_file(self) -> Path:
        return self.settings_dir / main.PROFILE_PERMISSIONS_FILENAME


class DefaultOffTests(_PluginPermissionTestCase):
    def test_bypass_disabled_by_default_with_no_file(self) -> None:
        plugin = Plugin()
        self.assertFalse(self._permissions_file().exists())
        self.assertFalse(plugin._profile_permission_bypass_enabled("claude"))

    def test_malformed_permissions_file_disables_bypass(self) -> None:
        # Not a JSON object -> parse_profile_permissions returns {} (disabled).
        self._permissions_file().write_text("[\"not\", \"an\", \"object\"]", encoding="utf-8")
        plugin = Plugin()
        self.assertEqual(plugin._load_profile_permissions(), {})
        self.assertFalse(plugin._profile_permission_bypass_enabled("claude"))

    def test_unparseable_permissions_file_disables_bypass(self) -> None:
        self._permissions_file().write_text("{ this is not json", encoding="utf-8")
        plugin = Plugin()
        self.assertEqual(plugin._load_profile_permissions(), {})
        self.assertFalse(plugin._profile_permission_bypass_enabled("claude"))


class LoadSaveRoundTripTests(_PluginPermissionTestCase):
    def test_enable_persists_and_reloads_as_enabled(self) -> None:
        writer = Plugin()
        writer._save_profile_permissions({"claude": {"bypass_permissions": True}})

        # Persisted to disk in the normalized, serialized shape.
        stored = json.loads(self._permissions_file().read_text(encoding="utf-8"))
        self.assertEqual(stored, {"claude": {"bypass_permissions": True}})

        # A fresh plugin reloads it as enabled.
        reader = Plugin()
        self.assertTrue(reader._profile_permission_bypass_enabled("claude"))
        # Normalized lookup: mixed case resolves to the same entry.
        self.assertTrue(reader._profile_permission_bypass_enabled("Claude"))
        # Other profiles stay disabled.
        self.assertFalse(reader._profile_permission_bypass_enabled("codex"))

    def test_disabling_removes_entry_and_persists_off(self) -> None:
        plugin = Plugin()
        plugin._save_profile_permissions({"claude": {"bypass_permissions": True}})
        plugin._save_profile_permissions({})

        self.assertEqual(json.loads(self._permissions_file().read_text(encoding="utf-8")), {})
        self.assertFalse(Plugin()._profile_permission_bypass_enabled("claude"))

    def test_non_truthy_bypass_entries_are_dropped_on_save(self) -> None:
        plugin = Plugin()
        plugin._save_profile_permissions({"claude": {"bypass_permissions": False}})
        self.assertEqual(json.loads(self._permissions_file().read_text(encoding="utf-8")), {})


class LaunchGatingTests(_PluginPermissionTestCase):
    def _make_plugin_with_stub_manager(self) -> tuple[Plugin, _StubManager]:
        plugin = Plugin()
        manager = _StubManager()
        plugin.pty_sessions = manager
        return plugin, manager

    def _patched_launch_plan(self):
        """plan_cli_launch returning a READY, non-read-only plan with a path set.

        This forces the launch gate's risk branch on (``path is not None`` and
        ``risk is not READ_ONLY``) so the test exercises the staged-approval
        gate itself rather than the missing-executable short-circuit.
        """

        from deck_assistant_core import RiskLevel

        def fake_plan_cli_launch(profile, *args, **kwargs):
            return types.SimpleNamespace(
                path="/usr/bin/claude",
                risk=RiskLevel.DANGER,
            )

        return mock.patch("deck_assistant_core.plan_cli_launch", side_effect=fake_plan_cli_launch)

    def test_gate_blocks_non_read_only_launch_when_bypass_disabled(self) -> None:
        plugin, manager = self._make_plugin_with_stub_manager()
        self.assertFalse(plugin._profile_permission_bypass_enabled("claude"))

        with self._patched_launch_plan():
            with self.assertRaises(ValueError) as ctx:
                asyncio.run(plugin.start_terminal_session({"profile_name": "claude"}))

        self.assertIn("requires staged approval", str(ctx.exception))
        # The gate fired before reaching the manager.
        self.assertEqual(manager.started, [])

    def test_gate_lifts_when_bypass_enabled(self) -> None:
        # Persist the bypass for the profile, then a fresh plugin loads it.
        Plugin()._save_profile_permissions({"claude": {"bypass_permissions": True}})

        plugin, manager = self._make_plugin_with_stub_manager()
        self.assertTrue(plugin._profile_permission_bypass_enabled("claude"))

        with self._patched_launch_plan():
            result = asyncio.run(plugin.start_terminal_session({"profile_name": "claude"}))

        # Gate lifted: the manager was reached and a session was returned.
        self.assertEqual(manager.started, ["claude"])
        self.assertEqual(result["session"]["profile_name"], "claude")


if __name__ == "__main__":
    unittest.main()
