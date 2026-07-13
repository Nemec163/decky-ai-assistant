from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import patch

from deck_assistant_core import (
    CliProfileHealth,
    CliProfileHealthStatus,
    CliPermissionBypassStatus,
    CliLaunchPlan,
    CliLaunchStatus,
    CliSetupAction,
    CliSetupStatus,
    apply_cli_permission_bypass,
    plan_cli_launch,
    plan_cli_permission_bypass,
    plan_cli_setup_action,
    summarize_cli_profile_health,
)
from deck_assistant_core.cli import (
    CliProfile,
    CliProfileError,
    CliAuthState,
    CliProbeStatus,
    ProbeResult,
    RiskLevel,
    build_cli_probe_env,
    check_cli_auth,
    detect_cli,
    get_cli_profile,
    list_cli_profiles,
    managed_cli_data_dir,
    managed_cli_profile_workspace_dir,
    managed_cli_node_bin_dirs,
    managed_cli_npm_bin_dir,
    managed_cli_npm_prefix,
    managed_cli_user_home,
    resolve_executable,
    _run_probe,
)


def _restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


class CliContractTests(unittest.TestCase):
    def test_known_profiles_have_stable_launch_commands(self) -> None:
        profiles = {profile.name: profile for profile in list_cli_profiles()}

        self.assertEqual(set(profiles), {"bash", "codex", "claude"})
        self.assertEqual(profiles["bash"].launch_argv(), ("bash",))
        self.assertEqual(profiles["codex"].launch_argv(), ("codex",))
        self.assertEqual(profiles["claude"].launch_argv(), ("claude",))

    @unittest.skipUnless(
        os.path.exists("/bin/bash") or os.path.exists("/usr/bin/bash"),
        "system bash is not available",
    )
    def test_resolve_executable_uses_decky_path_hints_when_path_is_empty(self) -> None:
        original_path = os.environ.get("PATH")
        os.environ["PATH"] = ""
        try:
            resolved = resolve_executable("bash")
        finally:
            if original_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = original_path

        self.assertIn(resolved, {"/bin/bash", "/usr/bin/bash"})

    def test_cli_probe_environment_removes_decky_loader_library_overrides(self) -> None:
        original_ld_library_path = os.environ.get("LD_LIBRARY_PATH")
        os.environ["LD_LIBRARY_PATH"] = "/tmp/decky-runtime-libs"

        try:
            env = build_cli_probe_env("/usr/bin/bash")
        finally:
            if original_ld_library_path is None:
                os.environ.pop("LD_LIBRARY_PATH", None)
            else:
                os.environ["LD_LIBRARY_PATH"] = original_ld_library_path

        self.assertNotIn("LD_LIBRARY_PATH", env)
        self.assertIn("/usr/bin", env["PATH"].split(os.pathsep))
        self.assertEqual(env["TERM"], "xterm-256color")

    def test_managed_cli_paths_use_user_local_data_home(self) -> None:
        original_xdg_data_home = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = "/tmp/decky-ai-data"

        try:
            self.assertEqual(
                managed_cli_npm_prefix(),
                "/tmp/decky-ai-data/decky-ai-assistant/npm",
            )
            self.assertEqual(
                managed_cli_npm_bin_dir(),
                "/tmp/decky-ai-data/decky-ai-assistant/npm/node_modules/.bin",
            )
        finally:
            if original_xdg_data_home is None:
                os.environ.pop("XDG_DATA_HOME", None)
            else:
                os.environ["XDG_DATA_HOME"] = original_xdg_data_home

    def test_managed_cli_profile_workspace_uses_stable_user_local_path(self) -> None:
        self.assertEqual(
            managed_cli_profile_workspace_dir("claude", home="/home/deck"),
            "/home/deck/.local/share/decky-ai-assistant/workspaces/claude",
        )

        with self.assertRaisesRegex(CliProfileError, "invalid CLI profile workspace"):
            managed_cli_profile_workspace_dir("../claude", home="/home/deck")

    def test_managed_cli_runtime_prefers_deck_home_over_root_home(self) -> None:
        original_home = os.environ.get("HOME")
        original_xdg_data_home = os.environ.get("XDG_DATA_HOME")
        original_xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
        original_xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
        original_isdir = os.path.isdir

        os.environ["HOME"] = "/root"
        os.environ["XDG_DATA_HOME"] = "/root/.local/share"
        os.environ["XDG_CONFIG_HOME"] = "/root/.config"
        os.environ["XDG_CACHE_HOME"] = "/root/.cache"

        def fake_isdir(path: str) -> bool:
            if path == "/home/deck":
                return True
            return original_isdir(path)

        try:
            with patch("deck_assistant_core.cli.os.path.isdir", side_effect=fake_isdir):
                env = build_cli_probe_env("/usr/bin/codex")

                self.assertEqual(managed_cli_user_home(), "/home/deck")
                self.assertEqual(
                    managed_cli_data_dir(),
                    "/home/deck/.local/share/decky-ai-assistant",
                )
                self.assertEqual(env["HOME"], "/home/deck")
                self.assertEqual(env["USER"], "deck")
                self.assertEqual(env["LOGNAME"], "deck")
                self.assertEqual(env["XDG_DATA_HOME"], "/home/deck/.local/share")
                self.assertEqual(env["XDG_CONFIG_HOME"], "/home/deck/.config")
                self.assertEqual(env["XDG_CACHE_HOME"], "/home/deck/.cache")
        finally:
            _restore_env("HOME", original_home)
            _restore_env("XDG_DATA_HOME", original_xdg_data_home)
            _restore_env("XDG_CONFIG_HOME", original_xdg_config_home)
            _restore_env("XDG_CACHE_HOME", original_xdg_cache_home)

    def test_managed_cli_node_bins_are_discovered_for_future_launches(self) -> None:
        original_xdg_data_home = os.environ.get("XDG_DATA_HOME")

        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["XDG_DATA_HOME"] = temp_dir
            node_root = Path(temp_dir) / "decky-ai-assistant" / "node"
            older_node = node_root / "node-v22.9.0-linux-x64" / "bin" / "node"
            newer_node = node_root / "node-v22.18.0-linux-x64" / "bin" / "node"
            for node_path in (older_node, newer_node):
                node_path.parent.mkdir(parents=True, exist_ok=True)
                node_path.write_text("#!/bin/sh\n", encoding="utf-8")
                node_path.chmod(0o755)

            try:
                node_bins = managed_cli_node_bin_dirs()
                env = build_cli_probe_env("/usr/bin/codex")
            finally:
                _restore_env("XDG_DATA_HOME", original_xdg_data_home)

        self.assertEqual(
            node_bins,
            (
                str(newer_node.parent),
                str(older_node.parent),
            ),
        )
        self.assertIn(str(newer_node.parent), env["PATH"].split(os.pathsep))

    def test_run_probe_uses_sanitized_environment(self) -> None:
        original_ld_library_path = os.environ.get("LD_LIBRARY_PATH")
        os.environ["LD_LIBRARY_PATH"] = "/tmp/decky-runtime-libs"

        try:
            result = _run_probe(
                [
                    sys.executable,
                    "-c",
                    "import os; print(os.environ.get('LD_LIBRARY_PATH', '<missing>'))",
                ],
                2.0,
            )
        finally:
            if original_ld_library_path is None:
                os.environ.pop("LD_LIBRARY_PATH", None)
            else:
                os.environ["LD_LIBRARY_PATH"] = original_ld_library_path

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "<missing>")

    def test_launch_plan_for_builtin_profile_uses_resolved_executable_path(self) -> None:
        plan = plan_cli_launch(
            "codex",
            which=lambda executable: f"/home/deck/.local/bin/{executable}",
        )

        self.assertIsInstance(plan, CliLaunchPlan)
        self.assertEqual(plan.status, CliLaunchStatus.READY)
        self.assertEqual(plan.path, "/home/deck/.local/bin/codex")
        self.assertEqual(plan.argv, ("/home/deck/.local/bin/codex",))
        self.assertEqual(plan.risk, RiskLevel.READ_ONLY)

    def test_launch_plan_for_custom_profile_preserves_structured_argv(self) -> None:
        profile = CliProfile.from_custom_command(
            name="custom-find",
            display_name="Custom Find",
            argv=["find", "/tmp", "-maxdepth", "1"],
        )

        plan = plan_cli_launch(
            profile,
            which=lambda executable: f"/usr/bin/{executable}",
        )

        self.assertEqual(plan.status, CliLaunchStatus.READY)
        self.assertEqual(plan.profile_type, "custom")
        self.assertEqual(plan.argv, ("/usr/bin/find", "/tmp", "-maxdepth", "1"))
        self.assertEqual(plan.risk, RiskLevel.READ_ONLY)

    def test_launch_plan_reports_missing_executable_without_probe_or_launch(self) -> None:
        seen: list[str] = []

        def missing(executable: str) -> None:
            seen.append(executable)
            return None

        plan = plan_cli_launch("codex", which=missing)

        self.assertEqual(seen, ["codex"])
        self.assertEqual(plan.status, CliLaunchStatus.MISSING_EXECUTABLE)
        self.assertIsNone(plan.path)
        self.assertEqual(plan.argv, ("codex",))
        self.assertEqual(plan.risk, RiskLevel.READ_ONLY)
        self.assertEqual(plan.error, "codex was not found on PATH.")

    def test_cli_setup_plan_installs_latest_package_into_user_local_prefix(self) -> None:
        original_xdg_data_home = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = "/tmp/decky-ai-data"

        try:
            plan = plan_cli_setup_action("codex", CliSetupAction.INSTALL_AUTH)
        finally:
            if original_xdg_data_home is None:
                os.environ.pop("XDG_DATA_HOME", None)
            else:
                os.environ["XDG_DATA_HOME"] = original_xdg_data_home

        self.assertEqual(plan.status, CliSetupStatus.READY)
        self.assertEqual(plan.risk, RiskLevel.LOW_WRITE)
        self.assertEqual(plan.npm_package, "@openai/codex")
        self.assertEqual(plan.install_prefix, "/tmp/decky-ai-data/decky-ai-assistant/npm")
        self.assertEqual(plan.bin_dir, "/tmp/decky-ai-data/decky-ai-assistant/npm/node_modules/.bin")
        self.assertEqual(plan.argv[:2], ("bash", "-lc"))
        self.assertIn("@openai/codex@latest", plan.argv[2])
        self.assertIn('exec "$managed_executable"', plan.argv[2])
        self.assertIn("official Codex login flow", plan.argv[2])
        self.assertIn("prepend_existing_managed_node_bins", plan.argv[2])
        self.assertIn("latest-v${node_line}.x/SHASUMS256.txt", plan.argv[2])
        self.assertLess(
            plan.argv[2].index("executable=codex"),
            plan.argv[2].index('managed_executable="$bin_dir/$executable"'),
        )

    def test_cli_setup_auth_plan_launches_existing_cli_auth_flow(self) -> None:
        plan = plan_cli_setup_action(
            "codex",
            "auth",
            which=lambda executable: f"/managed/bin/{executable}",
        )

        self.assertEqual(plan.status, CliSetupStatus.READY)
        self.assertEqual(plan.action, CliSetupAction.AUTH)
        self.assertEqual(plan.argv, ("/managed/bin/codex", "login"))
        self.assertEqual(plan.auth_argv, ("/managed/bin/codex", "login"))
        self.assertEqual(plan.risk, RiskLevel.LOW_WRITE)

    def test_cli_setup_auth_plan_reports_missing_cli(self) -> None:
        plan = plan_cli_setup_action("claude", "auth", which=lambda executable: None)

        self.assertEqual(plan.status, CliSetupStatus.MISSING_EXECUTABLE)
        self.assertEqual(plan.argv, ("claude",))
        self.assertEqual(plan.error, "claude was not found on PATH.")

    def test_cli_setup_plan_rejects_unsupported_profiles(self) -> None:
        plan = plan_cli_setup_action("bash", "install")

        self.assertEqual(plan.status, CliSetupStatus.UNSUPPORTED)
        self.assertEqual(plan.error, "Bash does not support managed setup.")

    def test_launch_plan_classifies_dangerous_custom_shell_executor(self) -> None:
        profile = CliProfile.from_custom_command(
            name="custom-shell",
            display_name="Custom Shell",
            argv=["bash", "-lc", "pwd"],
        )

        plan = plan_cli_launch(
            profile,
            which=lambda executable: f"/bin/{executable}",
        )

        self.assertEqual(plan.status, CliLaunchStatus.READY)
        self.assertEqual(plan.argv, ("/bin/bash", "-lc", "pwd"))
        self.assertEqual(plan.risk, RiskLevel.DANGER)

    def test_detect_missing_cli_does_not_run_probe(self) -> None:
        calls: list[tuple[str, ...]] = []

        result = detect_cli(
            "codex",
            which=lambda executable: None,
            run_probe=lambda argv, timeout: calls.append(tuple(argv)) or ProbeResult(0),
        )

        self.assertEqual(result.status, CliProbeStatus.MISSING)
        self.assertIsNone(result.path)
        self.assertEqual(calls, [])

    def test_detect_available_cli_returns_first_version_line(self) -> None:
        seen: list[tuple[tuple[str, ...], float]] = []

        def run_probe(argv: Sequence[str], timeout: float) -> ProbeResult:
            seen.append((tuple(argv), timeout))
            return ProbeResult(returncode=0, stdout="codex 1.2.3\nextra\n")

        result = detect_cli(
            "codex",
            timeout_seconds=3.5,
            which=lambda executable: f"/usr/bin/{executable}",
            run_probe=run_probe,
        )

        self.assertEqual(result.status, CliProbeStatus.READY)
        self.assertEqual(result.path, "/usr/bin/codex")
        self.assertEqual(result.version, "codex 1.2.3")
        self.assertEqual(seen, [(("/usr/bin/codex", "--version"), 3.5)])

    def test_detect_probe_failure_keeps_cli_path(self) -> None:
        result = detect_cli(
            "claude",
            which=lambda executable: f"/usr/bin/{executable}",
            run_probe=lambda argv, timeout: ProbeResult(returncode=2, stderr="failed"),
        )

        self.assertEqual(result.status, CliProbeStatus.PROBE_FAILED)
        self.assertEqual(result.path, "/usr/bin/claude")
        self.assertIsNone(result.version)

    def test_codex_auth_status_uses_official_read_only_probe(self) -> None:
        seen: list[tuple[str, ...]] = []

        def run_probe(argv: Sequence[str], timeout: float) -> ProbeResult:
            seen.append(tuple(argv))
            return ProbeResult(returncode=0, stdout="Logged in\n")

        result = check_cli_auth(
            "codex",
            which=lambda executable: f"/usr/bin/{executable}",
            run_probe=run_probe,
        )

        self.assertEqual(result.state, CliAuthState.LOGGED_IN)
        self.assertEqual(seen, [("/usr/bin/codex", "login", "status")])

    def test_codex_auth_status_reports_logged_out_marker(self) -> None:
        result = check_cli_auth(
            "codex",
            which=lambda executable: f"/usr/bin/{executable}",
            run_probe=lambda argv, timeout: ProbeResult(returncode=1, stderr="not logged in"),
        )

        self.assertEqual(result.state, CliAuthState.LOGGED_OUT)

    def test_cli_health_summary_aggregates_detection_auth_and_launch(self) -> None:
        seen: list[tuple[str, ...]] = []

        def run_probe(argv: Sequence[str], timeout: float) -> ProbeResult:
            seen.append(tuple(argv))
            if tuple(argv[1:]) == ("--version",):
                return ProbeResult(returncode=0, stdout="codex 1.2.3\n")
            if tuple(argv[1:]) == ("login", "status"):
                return ProbeResult(returncode=0, stdout="Logged in\n")
            return ProbeResult(returncode=2, stderr="unexpected probe")

        health = summarize_cli_profile_health(
            "codex",
            timeout_seconds=4.0,
            which=lambda executable: f"/usr/bin/{executable}",
            run_probe=run_probe,
        )

        self.assertIsInstance(health, CliProfileHealth)
        self.assertEqual(health.status, CliProfileHealthStatus.READY)
        self.assertTrue(health.can_launch)
        self.assertFalse(health.needs_login)
        self.assertEqual(health.detection.version, "codex 1.2.3")
        self.assertEqual(health.auth.state, CliAuthState.LOGGED_IN)
        self.assertEqual(health.launch_plan.argv, ("/usr/bin/codex",))
        self.assertEqual(
            seen,
            [
                ("/usr/bin/codex", "--version"),
                ("/usr/bin/codex", "login", "status"),
            ],
        )

        data = health.to_dict()
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["argv"], ["/usr/bin/codex"])
        self.assertEqual(data["detection"]["probe_argv"], ["/usr/bin/codex", "--version"])
        self.assertEqual(data["auth"]["probe_argv"], ["/usr/bin/codex", "login", "status"])

    def test_cli_health_summary_reports_login_required_without_blocking_launch(self) -> None:
        def run_probe(argv: Sequence[str], timeout: float) -> ProbeResult:
            if tuple(argv[1:]) == ("--version",):
                return ProbeResult(returncode=0, stdout="codex 1.2.3\n")
            return ProbeResult(returncode=1, stderr="not logged in")

        health = summarize_cli_profile_health(
            "codex",
            which=lambda executable: f"/usr/bin/{executable}",
            run_probe=run_probe,
        )

        self.assertEqual(health.status, CliProfileHealthStatus.LOGIN_REQUIRED)
        self.assertTrue(health.can_launch)
        self.assertTrue(health.needs_login)
        self.assertEqual(health.auth.state, CliAuthState.LOGGED_OUT)
        self.assertIn("CLI reports that login is required.", health.messages)

    def test_cli_health_summary_reports_auth_unknown_for_builtin_without_probe(self) -> None:
        health = summarize_cli_profile_health(
            "claude",
            which=lambda executable: f"/usr/bin/{executable}",
            run_probe=lambda argv, timeout: ProbeResult(returncode=0, stdout="claude 1.2.3\n"),
        )

        self.assertEqual(health.status, CliProfileHealthStatus.AUTH_UNKNOWN)
        self.assertTrue(health.can_launch)
        self.assertFalse(health.needs_login)
        self.assertEqual(health.auth.state, CliAuthState.UNKNOWN)
        self.assertIn("No read-only auth status probe is defined for this profile.", health.messages)

    def test_cli_health_summary_reports_missing_cli_without_running_probes(self) -> None:
        seen: list[tuple[str, ...]] = []

        health = summarize_cli_profile_health(
            "codex",
            which=lambda executable: None,
            run_probe=lambda argv, timeout: seen.append(tuple(argv)) or ProbeResult(returncode=0),
        )

        self.assertEqual(health.status, CliProfileHealthStatus.MISSING)
        self.assertFalse(health.can_launch)
        self.assertFalse(health.needs_login)
        self.assertEqual(health.detection.status, CliProbeStatus.MISSING)
        self.assertEqual(health.auth.state, CliAuthState.CLI_MISSING)
        self.assertEqual(health.launch_plan.status, CliLaunchStatus.MISSING_EXECUTABLE)
        self.assertEqual(seen, [])

    def test_permission_bypass_plan_reports_native_bypass_args(self) -> None:
        plan = plan_cli_permission_bypass("codex", enabled=True)

        self.assertEqual(plan.status, CliPermissionBypassStatus.ENABLED)
        self.assertEqual(plan.risk, RiskLevel.DANGER)
        self.assertTrue(plan.enabled)
        self.assertEqual(plan.bypass_args, ("--dangerously-bypass-approvals-and-sandbox",))
        self.assertIn("native no-approval", plan.message)

    def test_apply_permission_bypass_adds_known_cli_args(self) -> None:
        self.assertEqual(
            apply_cli_permission_bypass("codex").launch_argv(),
            ("codex", "--dangerously-bypass-approvals-and-sandbox"),
        )
        self.assertEqual(
            apply_cli_permission_bypass("claude").launch_argv(),
            ("claude", "--permission-mode", "bypassPermissions"),
        )
        self.assertEqual(apply_cli_permission_bypass("codex").risk, RiskLevel.DANGER)

    def test_custom_profile_health_uses_structured_argv_without_probes(self) -> None:
        seen: list[tuple[str, ...]] = []
        profile = CliProfile.from_custom_command(
            name="custom-find",
            display_name="Custom Find",
            argv=["find", "/tmp", "-maxdepth", "1"],
        )

        health = summarize_cli_profile_health(
            profile,
            which=lambda executable: f"/usr/bin/{executable}",
            run_probe=lambda argv, timeout: seen.append(tuple(argv)) or ProbeResult(returncode=0),
        )

        self.assertEqual(health.status, CliProfileHealthStatus.READY)
        self.assertEqual(health.profile_type, "custom")
        self.assertTrue(health.can_launch)
        self.assertFalse(health.needs_login)
        self.assertEqual(health.detection.status, CliProbeStatus.READY)
        self.assertEqual(health.detection.probe_argv, ())
        self.assertEqual(health.auth.state, CliAuthState.NOT_APPLICABLE)
        self.assertEqual(health.auth.probe_argv, ())
        self.assertEqual(health.launch_plan.argv, ("/usr/bin/find", "/tmp", "-maxdepth", "1"))
        self.assertEqual(seen, [])

        data = health.to_dict()
        self.assertEqual(data["argv"], ["/usr/bin/find", "/tmp", "-maxdepth", "1"])
        self.assertNotIsInstance(data["argv"], str)

    def test_auth_status_without_known_probe_is_unknown_or_not_applicable(self) -> None:
        bash = check_cli_auth("bash", which=lambda executable: f"/usr/bin/{executable}")
        claude = check_cli_auth("claude", which=lambda executable: f"/usr/bin/{executable}")

        self.assertEqual(bash.state, CliAuthState.NOT_APPLICABLE)
        self.assertEqual(claude.state, CliAuthState.UNKNOWN)

    def test_from_dict_restores_canonical_builtin_auth_state_when_missing(self) -> None:
        # Serialized payload omits auth_state_without_probe (older settings).
        bash = CliProfile.from_dict(
            {
                "name": "bash",
                "display_name": "Bash",
                "executable": "bash",
                "profile_type": "built_in",
            }
        )
        codex = CliProfile.from_dict(
            {
                "name": "codex",
                "display_name": "Codex CLI",
                "executable": "codex",
                "profile_type": "built_in",
                "auth_status_args": ["login", "status"],
            }
        )

        # Built-in bash is NOT_APPLICABLE, not the blanket UNKNOWN default.
        self.assertEqual(bash.auth_state_without_probe, CliAuthState.NOT_APPLICABLE)
        self.assertEqual(codex.auth_state_without_probe, CliAuthState.UNKNOWN)

    def test_from_dict_honors_explicit_auth_state_for_unknown_builtin(self) -> None:
        profile = CliProfile.from_dict(
            {
                "name": "unknown-builtin",
                "display_name": "Unknown",
                "executable": "unknown",
                "profile_type": "built_in",
                "auth_state_without_probe": "logged_out",
            }
        )
        self.assertEqual(profile.auth_state_without_probe, CliAuthState.LOGGED_OUT)

    def test_managed_user_identity_never_leaks_root_for_custom_home(self) -> None:
        original_home = os.environ.get("HOME")
        original_user = os.environ.get("USER")
        original_logname = os.environ.get("LOGNAME")
        original_override = os.environ.get("DECKY_AI_ASSISTANT_CLI_HOME")

        with tempfile.TemporaryDirectory() as temp_dir:
            custom_home = os.path.join(temp_dir, "steamdeck")
            os.makedirs(custom_home, exist_ok=True)
            os.environ["HOME"] = "/root"
            os.environ["USER"] = "root"
            os.environ["LOGNAME"] = "root"
            os.environ["DECKY_AI_ASSISTANT_CLI_HOME"] = custom_home

            try:
                env = build_cli_probe_env("/usr/bin/codex")
            finally:
                _restore_env("HOME", original_home)
                _restore_env("USER", original_user)
                _restore_env("LOGNAME", original_logname)
                _restore_env("DECKY_AI_ASSISTANT_CLI_HOME", original_override)

        self.assertEqual(env["HOME"], custom_home)
        self.assertEqual(env["USER"], "steamdeck")
        self.assertEqual(env["LOGNAME"], "steamdeck")

    def test_profile_lookup_normalizes_name(self) -> None:
        self.assertEqual(get_cli_profile(" Codex ").name, "codex")

    def test_custom_profile_uses_structured_argv(self) -> None:
        profile = CliProfile.from_custom_command(
            name="custom-htop",
            display_name="Custom Htop",
            argv=["/usr/bin/env", "TERM=xterm-256color", "htop"],
        )

        self.assertEqual(profile.profile_type, "custom")
        self.assertEqual(profile.executable, "/usr/bin/env")
        self.assertEqual(profile.launch_args, ("TERM=xterm-256color", "htop"))
        self.assertEqual(
            profile.launch_argv(),
            ("/usr/bin/env", "TERM=xterm-256color", "htop"),
        )

    def test_custom_profile_rejects_empty_argv_and_shell_string(self) -> None:
        with self.assertRaisesRegex(CliProfileError, "must not be empty"):
            CliProfile.from_custom_command(
                name="empty",
                display_name="Empty",
                argv=[],
            )

        with self.assertRaisesRegex(CliProfileError, "structured argv"):
            CliProfile.from_custom_command(
                name="shell-string",
                display_name="Shell String",
                argv="bash -lc pwd",
            )

    def test_custom_profile_exposes_risk(self) -> None:
        profile = CliProfile.from_custom_command(
            name="custom-touch",
            display_name="Custom Touch",
            argv=["touch", "/tmp/decky-ai-assistant-test"],
        )

        self.assertEqual(profile.risk, RiskLevel.LOW_WRITE)

    def test_custom_profile_round_trips_through_dict(self) -> None:
        profile = CliProfile.from_custom_command(
            name="custom-find",
            display_name="Custom Find",
            argv=["find", "/tmp", "-maxdepth", "1"],
        )

        data = profile.to_dict()
        restored = CliProfile.from_dict(json.loads(json.dumps(data)))

        self.assertEqual(restored.to_dict(), data)
        self.assertEqual(restored.launch_argv(), ("find", "/tmp", "-maxdepth", "1"))
        self.assertEqual(restored.auth_state_without_probe, CliAuthState.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
