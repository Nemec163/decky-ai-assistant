from __future__ import annotations

import io
import json
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


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


def _release(
    tag_name: str,
    *,
    draft: bool = False,
    prerelease: bool = False,
    asset_name: str | None = None,
) -> dict:
    version = tag_name.removeprefix("v")
    return {
        "tag_name": tag_name,
        "draft": draft,
        "prerelease": prerelease,
        "html_url": f"https://github.com/Nemec163/decky-ai-assistant/releases/tag/{tag_name}",
        "assets": [
            {
                "name": asset_name or f"decky-ai-assistant-v{version}.zip",
                "browser_download_url": (
                    "https://github.com/Nemec163/decky-ai-assistant/releases/download/"
                    f"{tag_name}/decky-ai-assistant-v{version}.zip"
                ),
                "digest": "sha256:abc123",
            }
        ],
    }


def _plugin_archive_bytes(version: str = "0.1.2-pre.27") -> bytes:
    buffer = io.BytesIO()
    package_payload = {
        "name": "decky-ai-assistant",
        "version": version,
    }
    files = {
        "dist/index.js": "console.log('decky-ai-assistant');\n",
        "main.py": "print('updated')\n",
        "package.json": json.dumps(package_payload) + "\n",
        "plugin.json": json.dumps({"name": "Decky AI Assistant"}) + "\n",
        "LICENSE": "MIT\n",
        "README.md": "# Decky AI Assistant\n",
        "AGENTS.md": "# Agent Instructions\n",
        "CLAUDE.md": "# Claude Instructions\n",
        "CONTRIBUTING.md": "# Contributing\n",
        "ROADMAP.md": "# Roadmap\n",
        "agent-pack/manifest.json": "{}\n",
        "docs/architecture.md": "# Architecture\n",
        "packages/core/src/deck_assistant_core/__init__.py": "",
        "packages/mcp-server/src/deck_assistant_mcp/__init__.py": "",
    }
    with zipfile.ZipFile(buffer, "w") as archive:
        for relative_path, content in files.items():
            archive.writestr(f"decky-ai-assistant/{relative_path}", content)
    return buffer.getvalue()


class PluginUpdatePlanTests(unittest.TestCase):
    def test_plan_selects_latest_prerelease_zip(self) -> None:
        plan = main._plugin_update_plan_from_releases(
            [
                _release("v0.1.2-pre.26"),
                _release("v0.1.2-pre.27"),
            ],
            current_version="0.1.2-pre.26",
        )

        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["latest_version"], "0.1.2-pre.27")
        self.assertEqual(plan["tag_name"], "v0.1.2-pre.27")
        self.assertTrue(plan["reload_required"])

    def test_plan_marks_current_release_up_to_date(self) -> None:
        plan = main._plugin_update_plan_from_releases(
            [_release("v0.1.2-pre.27")],
            current_version="0.1.2-pre.27",
        )

        self.assertEqual(plan["status"], "up_to_date")
        self.assertFalse(plan["reload_required"])

    def test_plan_ignores_draft_releases(self) -> None:
        plan = main._plugin_update_plan_from_releases(
            [
                _release("v0.1.2-pre.28", draft=True),
                _release("v0.1.2-pre.27"),
            ],
            current_version="0.1.2-pre.26",
        )

        self.assertEqual(plan["latest_version"], "0.1.2-pre.27")

    def test_stable_channel_ignores_prerelease(self) -> None:
        plan = main._plugin_update_plan_from_releases(
            [
                _release("v0.2.0-dev.1", prerelease=True),
                _release("v0.1.0"),
            ],
            current_version="0.1.0",
            channel="stable",
        )

        self.assertEqual(plan["status"], "up_to_date")
        self.assertEqual(plan["latest_version"], "0.1.0")

    def test_dev_channel_includes_prerelease(self) -> None:
        plan = main._plugin_update_plan_from_releases(
            [
                _release("v0.2.0-dev.1", prerelease=True),
                _release("v0.1.0"),
            ],
            current_version="0.1.0",
            channel="dev",
        )

        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["latest_version"], "0.2.0-dev.1")

    def test_plan_includes_requested_channel(self) -> None:
        plan = main._plugin_update_plan_from_releases(
            [_release("v0.1.0")],
            current_version="0.1.0",
            channel="dev",
        )

        self.assertEqual(plan["channel"], "dev")


class PluginUpdateArchiveTests(unittest.TestCase):
    def test_archive_rejects_path_traversal(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("decky-ai-assistant/../evil.txt", "bad")

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                main._extract_plugin_update_archive(buffer.getvalue(), Path(temp_dir))

    def test_install_replaces_plugin_bundle_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugin_root = Path(temp_dir)
            (plugin_root / "docs").mkdir()
            (plugin_root / "docs/old.md").write_text("old\n", encoding="utf-8")
            (plugin_root / "main.py").write_text("print('old')\n", encoding="utf-8")

            result = main._install_plugin_update_archive(
                _plugin_archive_bytes(),
                plugin_root=plugin_root,
            )

            package_payload = json.loads((plugin_root / "package.json").read_text(encoding="utf-8"))
            self.assertEqual(package_payload["version"], "0.1.2-pre.27")
            self.assertEqual((plugin_root / "main.py").read_text(encoding="utf-8"), "print('updated')\n")
            self.assertTrue((plugin_root / "dist/index.js").is_file())
            self.assertTrue((plugin_root / "packages/core/src/deck_assistant_core/__init__.py").is_file())
            self.assertFalse((plugin_root / "docs/old.md").exists())
            self.assertGreaterEqual(result["files_written"], 14)
            self.assertGreaterEqual(result["directories_written"], 6)

    def test_install_refuses_unwritable_plugin_root_before_replacing_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugin_root = Path(temp_dir)
            (plugin_root / "main.py").write_text("print('old')\n", encoding="utf-8")

            with patch("main.os.access", return_value=False):
                with self.assertRaises(PermissionError) as caught:
                    main._install_plugin_update_archive(
                        _plugin_archive_bytes(),
                        plugin_root=plugin_root,
                    )

            self.assertIn("not writable by the Decky plugin process", str(caught.exception))
            self.assertEqual((plugin_root / "main.py").read_text(encoding="utf-8"), "print('old')\n")
            self.assertFalse((plugin_root / "package.json").exists())


if __name__ == "__main__":
    unittest.main()
