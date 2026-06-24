from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from deck_assistant_core import (
    NativeAgentPackError,
    NativeAgentPackStatus,
    install_native_agent_pack,
    plan_native_agent_pack_install,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


class NativeAgentPackInstallTests(unittest.TestCase):
    def test_plan_reports_user_local_codex_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = plan_native_agent_pack_install(
                "codex",
                plugin_root=str(REPO_ROOT),
                home=temp_dir,
            )

        self.assertEqual(plan.status, NativeAgentPackStatus.READY)
        self.assertEqual(plan.target, "codex")
        self.assertEqual(plan.risk.value, "low_write")
        self.assertIn("/.agents/plugins/decky-ai-assistant", plan.install_dir or "")
        self.assertTrue(any(path.endswith("/.agents/plugins/marketplace.json") for path in plan.write_paths))
        self.assertTrue(plan.approval_requirement.requires_plan)

    def test_install_codex_pack_writes_plugin_marketplace_skills_and_workspace_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = plan_native_agent_pack_install(
                "codex",
                plugin_root=str(REPO_ROOT),
                home=temp_dir,
            )
            result = install_native_agent_pack(
                "codex",
                plugin_root=str(REPO_ROOT),
                home=temp_dir,
            )
            home = Path(temp_dir)

            plugin_manifest = json.loads(
                (home / ".agents/plugins/decky-ai-assistant/.codex-plugin/plugin.json").read_text(
                    encoding="utf-8"
                )
            )
            plugin_mcp = json.loads(
                (home / ".agents/plugins/decky-ai-assistant/.mcp.json").read_text(
                    encoding="utf-8"
                )
            )
            marketplace = json.loads(
                (home / ".agents/plugins/marketplace.json").read_text(encoding="utf-8")
            )
            workspace = home / ".local/share/decky-ai-assistant/workspaces/codex"

            self.assertTrue(result.installed)
            self.assertEqual(plugin_manifest["name"], "decky-ai-assistant")
            self.assertEqual(plugin_manifest["skills"], "./skills/")
            self.assertEqual(plugin_manifest["mcpServers"], "./.mcp.json")
            self.assertEqual(plugin_manifest["interface"]["displayName"], "Decky AI Assistant")
            self.assertIn("deck-assistant", plugin_mcp)
            self.assertEqual(marketplace["plugins"][0]["name"], "decky-ai-assistant")
            self.assertEqual(
                marketplace["plugins"][0]["source"]["path"],
                "./decky-ai-assistant",
            )
            self.assertTrue(
                (home / ".agents/skills/deck-runtime-support/SKILL.md").is_file()
            )
            self.assertIn(str(workspace), plan.write_paths)
            self.assertIn(str(workspace / "AGENTS.md"), plan.write_paths)
            self.assertIn(str(workspace / ".codex/config.toml"), plan.write_paths)
            self.assertTrue((workspace / ".decky-ai-assistant-managed.json").is_file())
            self.assertIn(
                "Steam Deck", (workspace / "AGENTS.md").read_text(encoding="utf-8")
            )
            codex_config = (workspace / ".codex/config.toml").read_text(encoding="utf-8")
            self.assertIn('[mcp_servers."deck-assistant"]', codex_config)
            self.assertIn("deck_assistant_mcp", codex_config)

    def test_install_claude_pack_writes_user_assets_and_workspace_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = plan_native_agent_pack_install(
                "claude",
                plugin_root=str(REPO_ROOT),
                home=temp_dir,
            )
            result = install_native_agent_pack(
                "claude",
                plugin_root=str(REPO_ROOT),
                home=temp_dir,
            )
            home = Path(temp_dir)

            plugin_root = home / ".claude/plugins/decky-ai-assistant"
            plugin_manifest = json.loads(
                (plugin_root / ".claude-plugin/plugin.json").read_text(encoding="utf-8")
            )
            workspace = home / ".local/share/decky-ai-assistant/workspaces/claude"
            mcp_config = json.loads(
                (workspace / ".mcp.json").read_text(encoding="utf-8")
            )

            self.assertTrue(result.installed)
            self.assertIn(
                str(home / ".claude/skills/deck-runtime-support"),
                plan.write_paths,
            )
            self.assertIn(
                str(home / ".claude/agents/deck-planner.md"),
                plan.write_paths,
            )
            self.assertIn(
                str(home / ".claude/commands/diagnose-runtime.md"),
                plan.write_paths,
            )
            self.assertIn(str(workspace), plan.write_paths)
            self.assertIn(str(workspace / ".mcp.json"), plan.write_paths)
            self.assertEqual(plugin_manifest["name"], "decky-ai-assistant")
            self.assertEqual(plugin_manifest["skills"], "./skills/")
            self.assertEqual(plugin_manifest["agents"], "./agents/")
            self.assertTrue((plugin_root / "skills/deck-runtime-support/SKILL.md").is_file())
            self.assertTrue((plugin_root / "CLAUDE.md").is_file())
            self.assertFalse(
                (home / ".claude/skills/decky-ai-assistant").exists()
            )
            self.assertTrue(
                (home / ".claude/skills/deck-runtime-support/SKILL.md").is_file()
            )
            self.assertTrue((home / ".claude/agents/deck-planner.md").is_file())
            self.assertTrue((home / ".claude/commands/diagnose-runtime.md").is_file())
            self.assertTrue((home / ".claude/commands/stage-safe-action.md").is_file())
            self.assertTrue((workspace / ".decky-ai-assistant-managed.json").is_file())
            self.assertTrue((workspace / "CLAUDE.md").is_file())
            self.assertIn(
                "Steam Deck", (workspace / "CLAUDE.md").read_text(encoding="utf-8")
            )
            self.assertIn("deck-assistant", mcp_config["mcpServers"])
            server = mcp_config["mcpServers"]["deck-assistant"]
            self.assertEqual(server["command"], "python3")
            self.assertEqual(server["args"], ["-m", "deck_assistant_mcp", "serve"])
            settings = json.loads(
                (workspace / ".claude/settings.local.json").read_text(encoding="utf-8")
            )
            self.assertEqual(settings["enabledMcpjsonServers"], ["deck-assistant"])

    def test_install_claude_pack_uses_runtime_xdg_workspace(self) -> None:
        original_home_override = os.environ.get("DECKY_AI_ASSISTANT_CLI_HOME")
        original_xdg_data_home = os.environ.get("XDG_DATA_HOME")

        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as data_home:
            os.environ["DECKY_AI_ASSISTANT_CLI_HOME"] = home_dir
            os.environ["XDG_DATA_HOME"] = data_home
            workspace = Path(data_home) / "decky-ai-assistant/workspaces/claude"

            try:
                result = install_native_agent_pack(
                    "claude",
                    plugin_root=str(REPO_ROOT),
                )
            finally:
                _restore_env("DECKY_AI_ASSISTANT_CLI_HOME", original_home_override)
                _restore_env("XDG_DATA_HOME", original_xdg_data_home)

            self.assertIn(str(workspace), result.plan.write_paths)
            self.assertTrue((workspace / ".decky-ai-assistant-managed.json").is_file())
            self.assertTrue(
                (Path(home_dir) / ".claude/skills/deck-runtime-support/SKILL.md").is_file()
            )

    def test_install_claude_pack_refuses_unmanaged_user_level_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            unmanaged = Path(temp_dir) / ".claude/skills/deck-runtime-support"
            unmanaged.mkdir(parents=True)
            (unmanaged / "SKILL.md").write_text("user skill", encoding="utf-8")

            with self.assertRaisesRegex(NativeAgentPackError, "unmanaged directory"):
                install_native_agent_pack(
                    "claude",
                    plugin_root=str(REPO_ROOT),
                    home=temp_dir,
                )

    def test_unknown_pack_install_target_is_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = plan_native_agent_pack_install(
                "unsupported-ai",
                plugin_root=str(REPO_ROOT),
                home=temp_dir,
            )

            self.assertEqual(plan.status, NativeAgentPackStatus.UNSUPPORTED)
            self.assertEqual(plan.risk.value, "read_only")
            self.assertIn("Codex and Claude", plan.message)

            with self.assertRaisesRegex(NativeAgentPackError, "Codex and Claude"):
                install_native_agent_pack(
                    "unsupported-ai",
                    plugin_root=str(REPO_ROOT),
                    home=temp_dir,
                )

    def test_install_refuses_to_overwrite_unmanaged_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            unmanaged = Path(temp_dir) / ".agents/plugins/decky-ai-assistant"
            unmanaged.mkdir(parents=True)
            (unmanaged / "user-file.txt").write_text("do not overwrite", encoding="utf-8")

            with self.assertRaisesRegex(NativeAgentPackError, "unmanaged directory"):
                install_native_agent_pack(
                    "codex",
                    plugin_root=str(REPO_ROOT),
                    home=temp_dir,
                )

def _restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
