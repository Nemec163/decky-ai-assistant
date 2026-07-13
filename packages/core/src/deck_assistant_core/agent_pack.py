"""Native assistant pack installation contracts.

This module writes only user-local CLI extension assets. It does not run CLI
commands, read provider credentials, or grant elevated permissions.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from deck_assistant_core.cli import (
    managed_cli_profile_workspace_dir,
    managed_cli_user_home,
)
from deck_assistant_core.risk import RiskLevel


AGENT_PACK_PLUGIN_NAME = "decky-ai-assistant"
AGENT_PACK_DISPLAY_NAME = "Decky AI Assistant"
_MANAGED_MARKER = ".decky-ai-assistant-managed.json"
_RUNTIME_SKILL_NAMES = (
    "deck-runtime-support",
    "deck-diagnose-game",
    "deck-storage-doctor",
    "deck-flatpak-doctor",
    "deck-knowledge-curator",
)
_CLAUDE_GLOBAL_AGENT_NAMES = (
    "deck-planner.md",
    "deck-diagnostician.md",
    "deck-knowledge-curator.md",
)
_CLAUDE_GLOBAL_COMMAND_NAMES = ("diagnose-runtime.md",)
_MCP_SERVER_NAME = "deck-assistant"


class NativeAgentPackStatus(str, Enum):
    """Status of a target-native assistant pack install plan."""

    READY = "ready"
    UNSUPPORTED = "unsupported"
    MISSING_SOURCE = "missing_source"


class NativeAgentPackError(RuntimeError):
    """Raised when a native assistant pack cannot be installed safely."""


@dataclass(frozen=True)
class NativeAgentPackInstallPlan:
    """A low-write plan for installing target-native assistant pack assets."""

    target: str
    display_name: str
    status: NativeAgentPackStatus
    risk: RiskLevel
    source_dir: str | None
    install_dir: str | None
    write_paths: tuple[str, ...] = ()
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "display_name": self.display_name,
            "status": self.status.value,
            "risk": self.risk.value,
            "source_dir": self.source_dir,
            "install_dir": self.install_dir,
            "write_paths": list(self.write_paths),
            "message": self.message,
        }


@dataclass(frozen=True)
class NativeAgentPackInstallResult:
    """Result of installing user-local native assistant pack assets."""

    plan: NativeAgentPackInstallPlan
    installed: bool
    files_written: int
    directories_written: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "installed": self.installed,
            "files_written": self.files_written,
            "directories_written": self.directories_written,
        }


def list_native_agent_pack_targets() -> tuple[str, ...]:
    """Return supported target IDs in stable order."""

    return ("codex", "claude")


def plan_native_agent_pack_install(
    target: str,
    *,
    plugin_root: str,
    home: str | None = None,
) -> NativeAgentPackInstallPlan:
    """Prepare a low-write native assistant pack install plan."""

    normalized_target = str(target).strip().lower()
    display_name = _target_display_name(normalized_target)
    risk = RiskLevel.LOW_WRITE
    source_dir = _agent_pack_source_dir(plugin_root)
    user_home = _user_home(home)

    if normalized_target not in list_native_agent_pack_targets():
        return NativeAgentPackInstallPlan(
            target=normalized_target,
            display_name=display_name,
            status=NativeAgentPackStatus.UNSUPPORTED,
            risk=RiskLevel.READ_ONLY,
            source_dir=str(source_dir),
            install_dir=None,
            message="Native assistant pack install is available only for Codex and Claude.",
        )

    if not _source_is_available(source_dir):
        return NativeAgentPackInstallPlan(
            target=normalized_target,
            display_name=display_name,
            status=NativeAgentPackStatus.MISSING_SOURCE,
            risk=RiskLevel.READ_ONLY,
            source_dir=str(source_dir),
            install_dir=None,
            message="Bundled agent-pack assets are missing from this plugin install.",
        )

    install_dir = _target_install_dir(normalized_target, user_home)
    return NativeAgentPackInstallPlan(
        target=normalized_target,
        display_name=display_name,
        status=NativeAgentPackStatus.READY,
        risk=risk,
        source_dir=str(source_dir),
        install_dir=str(install_dir),
        write_paths=_target_write_paths(
            normalized_target,
            user_home,
            install_dir,
            explicit_home=home is not None,
        ),
        message=_target_install_message(normalized_target),
    )


def install_native_agent_pack(
    target: str,
    *,
    plugin_root: str,
    home: str | None = None,
) -> NativeAgentPackInstallResult:
    """Install target-native assistant pack files into user-local CLI directories."""

    plan = plan_native_agent_pack_install(target, plugin_root=plugin_root, home=home)
    if plan.status is not NativeAgentPackStatus.READY:
        raise NativeAgentPackError(plan.message or f"native assistant pack is not ready: {target}")

    source_dir = Path(plan.source_dir or "")
    install_dir = Path(plan.install_dir or "")
    target_id = plan.target
    user_home = _user_home(home)

    _replace_managed_directory(
        install_dir,
        lambda temp_dir: _populate_target_plugin_tree(
            temp_dir,
            source_dir=source_dir,
            plugin_root=Path(plugin_root),
            target=target_id,
        ),
    )

    if target_id == "codex":
        _install_codex_global_skills(source_dir, user_home)
        _write_codex_marketplace(user_home, install_dir)
        _install_codex_workspace_runtime(
            user_home,
            plugin_root=Path(plugin_root),
            explicit_home=home is not None,
        )
    elif target_id == "claude":
        _install_claude_user_assets(
            source_dir,
            user_home,
            plugin_root=Path(plugin_root),
            explicit_home=home is not None,
        )

    files_written, directories_written = _count_written_paths(
        Path(path) for path in plan.write_paths
    )
    return NativeAgentPackInstallResult(
        plan=plan,
        installed=True,
        files_written=files_written,
        directories_written=directories_written,
    )


def _populate_target_plugin_tree(
    destination: Path,
    *,
    source_dir: Path,
    plugin_root: Path,
    target: str,
) -> None:
    for child_name in ("skills", "agents", "commands", "runtime", "mcp"):
        source_child = source_dir / child_name
        if source_child.exists():
            shutil.copytree(source_child, destination / child_name)

    for file_name in ("manifest.json", "tool-policy.json", "adapters/sources.md"):
        source_file = source_dir / file_name
        if source_file.exists():
            target_file = destination / file_name
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)

    for file_name in (
        "AGENTS.md",
        "CLAUDE.md",
        "README.md",
        "ROADMAP.md",
        "CONTRIBUTING.md",
        "LICENSE",
    ):
        source_file = plugin_root / file_name
        if source_file.exists():
            shutil.copy2(source_file, destination / file_name)

    docs_dir = plugin_root / "docs"
    if docs_dir.exists():
        shutil.copytree(docs_dir, destination / "docs")

    if target == "codex":
        _write_json(destination / ".mcp.json", _mcp_server_json_config(plugin_root))
        _write_json(
            destination / ".codex-plugin" / "plugin.json",
            {
                "name": AGENT_PACK_PLUGIN_NAME,
                "version": _package_version(plugin_root),
                "description": "Steam Deck assistant workflows for Decky AI Assistant.",
                "skills": "./skills/",
                "mcpServers": "./.mcp.json",
                "interface": {
                    "displayName": AGENT_PACK_DISPLAY_NAME,
                    "shortDescription": "Steam Deck diagnostics for terminal-first AI CLIs.",
                    "category": "Productivity",
                    "capabilities": ["Read"],
                    "brandColor": "#10A37F",
                    "defaultPrompt": [
                        "Explain what Decky AI Assistant can do on this Steam Deck.",
                        "Diagnose this Steam Deck issue with read-only tools first.",
                    ],
                },
            },
        )
    elif target == "claude":
        _write_json(
            destination / ".claude-plugin" / "plugin.json",
            {
                "name": AGENT_PACK_PLUGIN_NAME,
                "displayName": AGENT_PACK_DISPLAY_NAME,
                "version": _package_version(plugin_root),
                "description": "Steam Deck assistant workflows for Decky AI Assistant.",
                "skills": "./skills/",
                "agents": "./agents/",
            },
        )
    else:
        raise NativeAgentPackError(f"unsupported native assistant pack target: {target}")

    _write_marker(destination, target)


def _install_global_skills(
    source_dir: Path,
    skills_root: Path,
    *,
    marker: str,
) -> None:
    """Install the runtime skill directories into a CLI-specific skills root."""

    source_skills_root = source_dir / "skills"
    for skill_name in _RUNTIME_SKILL_NAMES:
        source_skill = source_skills_root / skill_name
        if not source_skill.exists():
            continue
        target_skill = skills_root / skill_name
        _replace_managed_directory(
            target_skill,
            lambda temp_dir, source_skill=source_skill: shutil.copytree(
                source_skill,
                temp_dir,
                dirs_exist_ok=True,
            ),
        )
        _write_marker(target_skill, marker)


def _install_global_files(
    source_root: Path,
    destination_root: Path,
    names: tuple[str, ...],
    *,
    marker: str,
) -> None:
    """Install a fixed set of single-file assets into a CLI-specific root."""

    for name in names:
        source_file = source_root / name
        if not source_file.exists():
            continue
        _replace_managed_file(
            destination_root / name,
            source_file,
            target=marker,
        )


def _install_codex_global_skills(source_dir: Path, home: Path) -> None:
    _install_global_skills(
        source_dir,
        home / ".agents" / "skills",
        marker="codex-skill",
    )


def _install_codex_workspace_runtime(
    home: Path,
    *,
    plugin_root: Path,
    explicit_home: bool,
) -> None:
    """Write Codex project instructions and MCP wiring into the workspace.

    Codex reads repo-local AGENTS.md from its current working directory and can
    load project-scoped MCP configuration from `.codex/config.toml` in trusted
    projects. Starting managed Codex sessions from this workspace gives the Deck
    the same assistant identity and local tool bridge that Claude already gets.
    """

    workspace = _codex_workspace_path(home, explicit_home=explicit_home)
    _ensure_managed_workspace(workspace, "codex-workspace", "Codex")
    _replace_managed_text(
        workspace / "AGENTS.md",
        _codex_runtime_persona(),
        target="codex-runtime-instructions",
    )
    _replace_managed_text(
        workspace / ".codex" / "config.toml",
        _codex_workspace_mcp_config(plugin_root),
        target="codex-runtime-mcp",
    )


def _install_claude_user_assets(
    source_dir: Path,
    home: Path,
    *,
    plugin_root: Path,
    explicit_home: bool,
) -> None:
    _install_claude_global_skills(source_dir, home)
    _install_claude_global_agents(source_dir, home)
    _install_claude_global_commands(source_dir, home)
    _ensure_claude_workspace(home, explicit_home=explicit_home)
    _install_claude_workspace_runtime(
        home,
        plugin_root=plugin_root,
        explicit_home=explicit_home,
    )


def _install_claude_global_skills(source_dir: Path, home: Path) -> None:
    _install_global_skills(
        source_dir,
        home / ".claude" / "skills",
        marker="claude-skill",
    )


def _install_claude_global_agents(source_dir: Path, home: Path) -> None:
    _install_global_files(
        source_dir / "agents",
        home / ".claude" / "agents",
        _CLAUDE_GLOBAL_AGENT_NAMES,
        marker="claude-agent",
    )


def _install_claude_global_commands(source_dir: Path, home: Path) -> None:
    _install_global_files(
        source_dir / "commands",
        home / ".claude" / "commands",
        _CLAUDE_GLOBAL_COMMAND_NAMES,
        marker="claude-command",
    )


def _install_claude_workspace_runtime(
    home: Path,
    *,
    plugin_root: Path,
    explicit_home: bool,
) -> None:
    """Write the Steam Deck assistant identity and MCP wiring into the workspace.

    Claude Code launches from this workspace, so a project `CLAUDE.md` frames the
    session as the Deck assistant and a project `.mcp.json` registers the bundled
    `deck-assistant` MCP server. A project `settings.local.json` pre-enables that
    server so the launched CLI gains the Deck tool catalog immediately. All three
    are managed files and never overwrite user copies.
    """

    workspace = _claude_workspace_path(home, explicit_home=explicit_home)
    _replace_managed_text(
        workspace / "CLAUDE.md",
        _claude_runtime_persona(),
        target="claude-runtime-instructions",
    )
    _replace_managed_text(
        workspace / ".mcp.json",
        _claude_workspace_mcp_config(plugin_root),
        target="claude-runtime-mcp",
    )
    _replace_managed_text(
        workspace / ".claude" / "settings.local.json",
        _claude_workspace_settings(),
        target="claude-runtime-settings",
    )


def _ensure_claude_workspace(home: Path, *, explicit_home: bool) -> None:
    workspace = _claude_workspace_path(home, explicit_home=explicit_home)
    _ensure_managed_workspace(workspace, "claude-workspace", "Claude")


def _ensure_managed_workspace(workspace: Path, marker: str, label: str) -> None:
    if workspace.exists() and not workspace.is_dir():
        raise NativeAgentPackError(
            f"{label} workspace path is not a directory: {workspace}"
        )
    workspace.mkdir(parents=True, exist_ok=True)
    _write_marker(workspace, marker)


def _codex_workspace_path(home: Path, *, explicit_home: bool) -> Path:
    if explicit_home:
        return Path(managed_cli_profile_workspace_dir("codex", home=str(home)))
    return Path(managed_cli_profile_workspace_dir("codex"))


def _claude_workspace_path(home: Path, *, explicit_home: bool) -> Path:
    if explicit_home:
        return Path(managed_cli_profile_workspace_dir("claude", home=str(home)))
    return Path(managed_cli_profile_workspace_dir("claude"))


def _codex_runtime_persona() -> str:
    """Return the project AGENTS.md that frames Codex as the Deck assistant."""

    return (
        "# Steam Deck AI Assistant\n"
        "\n"
        "You are the Decky AI Assistant running inside Steam Deck Gaming Mode "
        "through the Decky plugin. Behave as a focused Steam Deck support assistant, "
        "not as a general coding agent unless the user explicitly asks for repo work. "
        "Keep answers short enough to read on the Deck.\n"
        "\n"
        "## Tools\n"
        "\n"
        f"A local MCP server named `{_MCP_SERVER_NAME}` is configured for this "
        "workspace. Prefer its read-only tools before shell commands:\n"
        "\n"
        "- `search_knowledge`, `list_sources` — cited answers from local knowledge packs.\n"
        "- `inspect_current_game` — selected/current Steam app context.\n"
        "- `read_proton_logs`, `get_storage_report` — bounded read-only Deck diagnostics.\n"
        "- `propose_fix` — turn evidence into a concise fix plan with a risk level.\n"
        "\n"
        "Use the installed `deck-*` skills for diagnosis, storage, Flatpak, and "
        "knowledge workflows. For requested fixes, use the active CLI's normal "
        "shell/tooling; Decky does not execute those fixes separately.\n"
        "\n"
        "## Risk model\n"
        "\n"
        "- Prefer diagnostics and citations first when they answer the Deck question.\n"
        "- Classify every local change: `read_only`, `low_write`, `high_write`, or `danger`.\n"
        "- Execute requested fixes when the active CLI allows it; Decky does not add extra prompts outside the CLI.\n"
        "- For dangerous commands (`sudo`, `rm`, `pacman`, `systemctl`, `chmod`, "
        "readonly-partition changes) show the exact command and a rollback note; "
        "never hide them behind vague natural-language text.\n"
        "- Never read, print, copy, or upload AI CLI auth tokens or credential stores.\n"
        "- Do not run background scans or indexing unless the user explicitly asks.\n"
        "\n"
        "This file is managed by Decky AI Assistant. Local edits may be replaced when "
        "the native pack is reinstalled.\n"
    )


def _mcp_server_json_config(plugin_root: Path) -> dict[str, Any]:
    core_src = plugin_root / "packages" / "core" / "src"
    mcp_src = plugin_root / "packages" / "mcp-server" / "src"
    python_path = ":".join((str(core_src), str(mcp_src)))
    return {
        _MCP_SERVER_NAME: {
            "command": "python3",
            "args": ["-m", "deck_assistant_mcp", "serve"],
            "env": {
                "PYTHONPATH": python_path,
                "DECK_ASSISTANT_MODE": "local",
            },
        }
    }


def _codex_workspace_mcp_config(plugin_root: Path) -> str:
    """Return project `.codex/config.toml` registering deck-assistant."""

    core_src = plugin_root / "packages" / "core" / "src"
    mcp_src = plugin_root / "packages" / "mcp-server" / "src"
    python_path = ":".join((str(core_src), str(mcp_src)))
    server_key = _toml_string(_MCP_SERVER_NAME)
    return (
        f"[mcp_servers.{server_key}]\n"
        'command = "python3"\n'
        'args = ["-m", "deck_assistant_mcp", "serve"]\n'
        "enabled = true\n"
        "tool_timeout_sec = 60\n"
        "\n"
        f"[mcp_servers.{server_key}.env]\n"
        f"PYTHONPATH = {_toml_string(python_path)}\n"
        'DECK_ASSISTANT_MODE = "local"\n'
    )


def _claude_runtime_persona() -> str:
    """Return the project CLAUDE.md that frames the session as the Deck assistant."""

    return (
        "# Steam Deck AI Assistant\n"
        "\n"
        "You are the **Decky AI Assistant** running inside Steam Deck Gaming Mode "
        "through the Decky plugin. Behave as a focused Steam Deck support assistant, "
        "not a general coding agent. Keep answers short enough to read on the Deck.\n"
        "\n"
        "## Tools\n"
        "\n"
        f"A local MCP server named `{_MCP_SERVER_NAME}` is registered for this "
        "workspace. Prefer its read-only tools before shell commands:\n"
        "\n"
        "- `search_knowledge`, `list_sources` — cited answers from local knowledge packs.\n"
        "- `inspect_current_game` — selected/current Steam app context.\n"
        "- `read_proton_logs`, `get_storage_report` — bounded read-only Deck diagnostics.\n"
        "- `propose_fix` — turn evidence into a concise fix plan with a risk level.\n"
        "\n"
        "Use the installed `deck-*` skills, subagents, and slash commands for "
        "diagnosis, storage, Flatpak, and knowledge workflows. For requested fixes, "
        "use the active CLI's normal shell/tooling; Decky does not execute those fixes separately.\n"
        "\n"
        "## Risk model\n"
        "\n"
        "- Prefer diagnostics and citations first when they answer the Deck question.\n"
        "- Classify every local change: `read_only`, `low_write`, `high_write`, or `danger`.\n"
        "- Execute requested fixes when the active CLI allows it; Decky does not add extra prompts outside the CLI.\n"
        "- For dangerous commands (`sudo`, `rm`, `pacman`, `systemctl`, `chmod`, "
        "readonly-partition changes) show the exact command and a rollback note; "
        "never hide them behind vague natural-language text.\n"
        "- Never read, print, copy, or upload AI CLI auth tokens or credential stores.\n"
        "- Do not run background scans or indexing unless the user explicitly asks.\n"
        "\n"
        "This file is managed by Decky AI Assistant. Local edits may be replaced when "
        "the native pack is reinstalled.\n"
    )


def _claude_workspace_mcp_config(plugin_root: Path) -> str:
    """Return the project `.mcp.json` registering the bundled deck-assistant server."""

    config = {
        "mcpServers": {
            _MCP_SERVER_NAME: {
                "type": "stdio",
                **_mcp_server_json_config(plugin_root)[_MCP_SERVER_NAME],
            }
        },
    }
    return json.dumps(config, indent=2, sort_keys=True) + "\n"


def _claude_workspace_settings() -> str:
    """Return project settings that pre-enable the bundled MCP server."""

    return (
        json.dumps(
            {"enabledMcpjsonServers": [_MCP_SERVER_NAME]},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _write_codex_marketplace(home: Path, install_dir: Path) -> None:
    marketplace_path = home / ".agents" / "plugins" / "marketplace.json"
    marketplace_path.parent.mkdir(parents=True, exist_ok=True)
    if marketplace_path.exists():
        try:
            marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise NativeAgentPackError(
                f"Codex marketplace JSON is invalid: {marketplace_path}"
            ) from exc
        if not isinstance(marketplace, dict):
            raise NativeAgentPackError(f"Codex marketplace must be a JSON object: {marketplace_path}")
    else:
        marketplace = {
            "name": "decky-ai-assistant-local",
            "interface": {"displayName": "Decky AI Assistant Local"},
            "plugins": [],
        }

    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list):
        raise NativeAgentPackError(f"Codex marketplace plugins must be an array: {marketplace_path}")

    next_entry = {
        "name": AGENT_PACK_PLUGIN_NAME,
        "source": {
            "source": "local",
            "path": _marketplace_relative_path(install_dir, marketplace_path.parent),
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Productivity",
    }
    marketplace["plugins"] = [
        item for item in plugins if not (isinstance(item, dict) and item.get("name") == AGENT_PACK_PLUGIN_NAME)
    ]
    marketplace["plugins"].append(next_entry)
    _write_json(marketplace_path, marketplace)


def _marketplace_relative_path(path: Path, root: Path) -> str:
    relative = os.path.relpath(path, root)
    if relative == ".":
        return "."
    if relative.startswith(("./", "../")):
        return relative
    return f"./{relative}"


def _toml_string(value: str) -> str:
    return json.dumps(str(value))


def _replace_managed_path(
    destination: Path,
    write_temp: Callable[[Path], None],
    *,
    target: str,
) -> None:
    """Atomically replace one managed file, refusing to clobber user copies.

    ``write_temp`` produces the new file contents at the given temporary path;
    the only difference between a file copy and a text write is this callback.
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not _is_managed_file(destination):
        raise NativeAgentPackError(f"refusing to overwrite unmanaged file: {destination}")

    temp_path = destination.parent / f".{destination.name}.tmp"
    if temp_path.exists():
        temp_path.unlink()
    try:
        write_temp(temp_path)
        temp_path.replace(destination)
        _write_file_marker(destination, target)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def _replace_managed_file(destination: Path, source: Path, *, target: str) -> None:
    _replace_managed_path(
        destination,
        lambda temp_path: shutil.copy2(source, temp_path),
        target=target,
    )


def _replace_managed_text(destination: Path, content: str, *, target: str) -> None:
    _replace_managed_path(
        destination,
        lambda temp_path: temp_path.write_text(content, encoding="utf-8"),
        target=target,
    )


def _replace_managed_directory(
    destination: Path,
    populate: Callable[[Path], None],
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not _is_managed_directory(destination):
        raise NativeAgentPackError(f"refusing to overwrite unmanaged directory: {destination}")

    temp_dir = destination.parent / f".{destination.name}.tmp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)
    try:
        populate(temp_dir)
        if destination.exists():
            shutil.rmtree(destination)
        temp_dir.replace(destination)
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise


def _is_managed_directory(path: Path) -> bool:
    marker_path = path / _MANAGED_MARKER
    return _marker_is_managed(marker_path)


def _is_managed_file(path: Path) -> bool:
    return _marker_is_managed(_managed_file_marker_path(path))


def _marker_is_managed(marker_path: Path) -> bool:
    if not marker_path.exists():
        return False
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return isinstance(marker, dict) and marker.get("managed_by") == AGENT_PACK_PLUGIN_NAME


def _write_marker(path: Path, target: str) -> None:
    _write_json(
        path / _MANAGED_MARKER,
        {
            "managed_by": AGENT_PACK_PLUGIN_NAME,
            "target": target,
            "schema_version": 1,
        },
    )


def _write_file_marker(path: Path, target: str) -> None:
    _write_json(
        _managed_file_marker_path(path),
        {
            "managed_by": AGENT_PACK_PLUGIN_NAME,
            "target": target,
            "schema_version": 1,
            "managed_file": path.name,
        },
    )


def _managed_file_marker_path(path: Path) -> Path:
    return path.with_name(f".{path.name}{_MANAGED_MARKER}")


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _target_display_name(target: str) -> str:
    return {
        "codex": "Codex CLI",
        "claude": "Claude Code",
    }.get(target, target or "unknown")


def _target_install_dir(target: str, home: Path) -> Path:
    if target == "codex":
        return home / ".agents" / "plugins" / AGENT_PACK_PLUGIN_NAME
    if target == "claude":
        return home / ".claude" / "plugins" / AGENT_PACK_PLUGIN_NAME
    raise NativeAgentPackError(f"unsupported native assistant pack target: {target}")


def _target_write_paths(
    target: str,
    home: Path,
    install_dir: Path,
    *,
    explicit_home: bool = False,
) -> tuple[str, ...]:
    paths = [str(install_dir)]
    if target == "codex":
        paths.append(str(home / ".agents" / "plugins" / "marketplace.json"))
        paths.extend(str(home / ".agents" / "skills" / name) for name in _RUNTIME_SKILL_NAMES)
        workspace = _codex_workspace_path(home, explicit_home=explicit_home)
        paths.append(str(workspace))
        paths.append(str(workspace / "AGENTS.md"))
        paths.append(str(workspace / ".codex" / "config.toml"))
    elif target == "claude":
        paths.extend(str(home / ".claude" / "skills" / name) for name in _RUNTIME_SKILL_NAMES)
        for name in _CLAUDE_GLOBAL_AGENT_NAMES:
            agent_path = home / ".claude" / "agents" / name
            paths.append(str(agent_path))
            paths.append(str(_managed_file_marker_path(agent_path)))
        for name in _CLAUDE_GLOBAL_COMMAND_NAMES:
            command_path = home / ".claude" / "commands" / name
            paths.append(str(command_path))
            paths.append(str(_managed_file_marker_path(command_path)))
        workspace = _claude_workspace_path(home, explicit_home=explicit_home)
        paths.append(str(workspace))
        paths.append(str(workspace / "CLAUDE.md"))
        paths.append(str(workspace / ".mcp.json"))
        paths.append(str(workspace / ".claude" / "settings.local.json"))
    return tuple(paths)


def _target_install_message(target: str) -> str:
    if target == "codex":
        return (
            "Installs a local Codex plugin marketplace entry, plugin MCP metadata, global "
            "runtime skills, and a stable Codex workspace whose AGENTS.md frames the session "
            "as the Steam Deck assistant and whose .codex/config.toml registers the local "
            "deck-assistant MCP server. Restart Codex to reload plugin and MCP metadata."
        )
    if target == "claude":
        return (
            "Installs user-level Deck skills, subagents, and commands under ~/.claude, plus "
            "a self-contained plugin bundle under ~/.claude/plugins. Prepares a stable Claude "
            "workspace whose CLAUDE.md frames the session as the Steam Deck assistant and whose "
            ".mcp.json registers the local deck-assistant tool server. Restart Claude Code to pick it up."
        )
    return "Unsupported native assistant pack target."


def _agent_pack_source_dir(plugin_root: str) -> Path:
    return Path(plugin_root).expanduser().resolve() / "agent-pack"


def _source_is_available(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "manifest.json").is_file()
        and (path / "skills").is_dir()
        and (path / "tool-policy.json").is_file()
    )


def _user_home(home: str | None) -> Path:
    if home is not None:
        normalized = Path(home).expanduser()
        if not normalized.is_absolute():
            raise NativeAgentPackError("home must be an absolute path")
        return normalized
    return Path(managed_cli_user_home())


def _package_version(plugin_root: Path) -> str:
    package_path = plugin_root / "package.json"
    if not package_path.exists():
        return "0.0.0"
    try:
        package_data = json.loads(package_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "0.0.0"
    version = package_data.get("version")
    return str(version) if version else "0.0.0"


def _count_written_paths(paths: Iterable[Path]) -> tuple[int, int]:
    """Count distinct managed files and directories under the written paths.

    Each top-level write path is resolved once; nested entries are deduped by
    their absolute walked path. These counts are reported in the install result
    for the UI only, so resolving symlinks per node (the previous behavior) is
    unnecessary work on a freshly written tree.
    """

    files: set[str] = set()
    directories: set[str] = set()
    for path in paths:
        if path.is_file():
            files.add(os.path.realpath(path))
            continue
        if path.is_dir():
            root = os.path.realpath(path)
            directories.add(root)
            for current_path, dir_names, file_names in os.walk(root):
                for dir_name in dir_names:
                    directories.add(os.path.join(current_path, dir_name))
                for file_name in file_names:
                    files.add(os.path.join(current_path, file_name))
    return len(files), len(directories)
