#!/usr/bin/env python3
"""Validate the repo-local agent pack without external dependencies."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:  # PyYAML is optional; the validator must run on the stdlib alone.
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - exercised only without PyYAML
    yaml = None

try:  # tomllib ships in the stdlib on Python 3.11+.
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - exercised only on <3.11
    tomllib = None


ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "agent-pack"
MANIFEST = PACK / "manifest.json"
MCP_TEMPLATES_DIR = PACK / "mcp"
VALID_RISKS = ["read_only", "low_write", "high_write", "danger"]
REPO_HANDOFF_FIELDS = [
    "slice_goal",
    "files_in_scope",
    "files_changed",
    "verification",
    "risk_notes",
    "commit_status",
    "allowed_next_role",
    "blocked_condition",
]
MCP_TOOL_RISKS = {
    "search_knowledge": "read_only",
    "list_sources": "read_only",
    "inspect_current_game": "read_only",
    "read_proton_logs": "read_only",
    "get_storage_report": "read_only",
    "propose_fix": "read_only",
}


def fail(message: str) -> None:
    print(f"agent-pack validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        fail(f"missing file: {path.relative_to(ROOT)}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path.relative_to(ROOT)}: {exc}")


def require_path(repo_path: str) -> Path:
    path = ROOT / repo_path
    if not path.exists():
        fail(f"manifest path does not exist: {repo_path}")
    return path


def require_unique(items: list[dict], label: str) -> list[str]:
    ids = [item.get("id") for item in items]
    if any(not item_id for item_id in ids):
        fail(f"{label} entries must all have ids")
    duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
    if duplicates:
        fail(f"duplicate {label} ids: {', '.join(duplicates)}")
    return ids


def validate_tool_policy(policy: dict, role_ids: list[str]) -> None:
    if policy.get("schema_version") != 1:
        fail("tool-policy schema_version must be 1")
    if policy.get("risk_levels") != VALID_RISKS:
        fail("tool-policy risk_levels must match canonical order")

    tool_groups = policy.get("mcp_tool_groups", {})
    if not isinstance(tool_groups, dict) or not tool_groups:
        fail("tool-policy mcp_tool_groups must be a non-empty object")

    tool_to_group: dict[str, str] = {}
    for group, tools in tool_groups.items():
        if not isinstance(tools, list) or not tools:
            fail(f"mcp_tool_group must list at least one tool: {group}")
        for tool in tools:
            if not isinstance(tool, str) or not tool:
                fail(f"mcp_tool_group contains invalid tool id: {group}")
            if tool not in MCP_TOOL_RISKS:
                fail(f"mcp_tool_group contains unknown tool: {tool}")
            if tool in tool_to_group:
                fail(
                    "MCP tool assigned to multiple groups: "
                    f"{tool} in {tool_to_group[tool]}, {group}"
                )
            tool_to_group[tool] = group

    missing_tools = set(MCP_TOOL_RISKS) - set(tool_to_group)
    if missing_tools:
        fail(f"mcp_tool_groups missing tools: {', '.join(sorted(missing_tools))}")

    role_policy = policy.get("role_tool_policy", {})
    if not isinstance(role_policy, dict):
        fail("role_tool_policy must be an object")
    unknown_policy_roles = set(role_policy) - set(role_ids)
    if unknown_policy_roles:
        unknown = ", ".join(sorted(unknown_policy_roles))
        fail(f"role_tool_policy contains unknown roles: {unknown}")
    missing_policy_roles = set(role_ids) - set(role_policy)
    if missing_policy_roles:
        missing = ", ".join(sorted(missing_policy_roles))
        fail(f"role_tool_policy missing roles: {missing}")

    for role_id, rule in role_policy.items():
        allowed_groups = rule.get("allowed_groups", [])
        if not isinstance(allowed_groups, list):
            fail(f"allowed_groups must be a list for {role_id}")

        for group in allowed_groups:
            if not isinstance(group, str) or not group:
                fail(f"role {role_id} contains invalid tool group id")
            if group not in tool_groups:
                fail(f"role {role_id} allows unknown tool group: {group}")


def validate_handoff_policy(policy: dict, role_ids: list[str]) -> None:
    handoff = policy.get("handoff_policy", {})
    if not isinstance(handoff, dict):
        fail("handoff_policy must be an object")

    repo_handoff_fields = handoff.get("repo_development_handoff_fields")
    if repo_handoff_fields != REPO_HANDOFF_FIELDS:
        fail("handoff_policy repo_development_handoff_fields must match canonical order")

    if handoff.get("single_owner_per_repo_slice") is not True:
        fail("handoff_policy single_owner_per_repo_slice must be true")
    if handoff.get("single_commit_per_repo_slice") is not True:
        fail("handoff_policy single_commit_per_repo_slice must be true")


def validate_openai_yaml(path: Path, skill_id: str) -> None:
    """Parse the OpenAI adapter YAML (PyYAML when available, stdlib fallback)."""

    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        try:
            loaded = yaml.safe_load(text)
        except yaml.YAMLError as exc:  # type: ignore[union-attr]
            fail(f"invalid YAML in agents/openai.yaml for {skill_id}: {exc}")
        if not isinstance(loaded, dict):
            fail(f"agents/openai.yaml for {skill_id} must be a mapping")
        interface = loaded.get("interface")
        if not isinstance(interface, dict):
            fail(f"agents/openai.yaml for {skill_id} missing interface mapping")
        for field in ("display_name", "short_description", "default_prompt"):
            value = interface.get(field)
            if not isinstance(value, str) or not value.strip():
                fail(
                    f"agents/openai.yaml for {skill_id} missing interface.{field}"
                )
        return

    # Stdlib-only fallback: minimal structural sanity check without a parser.
    if "interface:" not in text:
        fail(f"agents/openai.yaml for {skill_id} missing interface block")
    for field in ("display_name", "short_description", "default_prompt"):
        if not re.search(rf"^\s+{field}\s*:", text, re.MULTILINE):
            fail(f"agents/openai.yaml for {skill_id} missing interface.{field}")


def validate_skills(skills: list[dict]) -> None:
    for skill in skills:
        path = require_path(skill["path"])
        skill_md = path / "SKILL.md"
        openai_yaml = path / "agents" / "openai.yaml"
        if not skill_md.exists():
            fail(f"missing SKILL.md for skill {skill['id']}")
        text = skill_md.read_text(encoding="utf-8")
        if "TODO" in text:
            fail(f"skill contains TODO markers: {skill['id']}")
        expected = f"name: {skill['id']}"
        if expected not in text:
            fail(f"skill frontmatter name mismatch for {skill['id']}")
        if not openai_yaml.exists():
            fail(f"missing agents/openai.yaml for skill {skill['id']}")
        validate_openai_yaml(openai_yaml, skill["id"])


def validate_mcp_templates() -> None:
    """Validate the bundled MCP example templates parse cleanly."""

    claude_example = MCP_TEMPLATES_DIR / "claude.example.json"
    codex_example = MCP_TEMPLATES_DIR / "codex.example.toml"

    if not claude_example.exists():
        fail(f"missing MCP template: {claude_example.relative_to(ROOT)}")
    try:
        with claude_example.open("r", encoding="utf-8") as handle:
            claude_config = json.load(handle)
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {claude_example.relative_to(ROOT)}: {exc}")
    if not isinstance(claude_config.get("mcpServers"), dict):
        fail(f"{claude_example.relative_to(ROOT)} must define mcpServers object")

    if not codex_example.exists():
        fail(f"missing MCP template: {codex_example.relative_to(ROOT)}")
    if tomllib is not None:
        try:
            with codex_example.open("rb") as handle:
                tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:  # type: ignore[union-attr]
            fail(f"invalid TOML in {codex_example.relative_to(ROOT)}: {exc}")


def parse_agent_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        fail(f"missing frontmatter in {path.relative_to(ROOT)}")
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def validate_agents(role_entries: list[dict], policy: dict) -> None:
    role_policy = policy.get("role_tool_policy", {})
    for role in role_entries:
        path = require_path(role["path"])
        fields = parse_agent_frontmatter(path)
        role_id = role["id"]
        if fields.get("id") != role_id:
            fail(f"agent frontmatter id mismatch for {role_id}")
        if role_id not in role_policy:
            fail(f"missing role_tool_policy for {role_id}")
        declared_groups = {
            group.strip()
            for group in fields.get("tool_groups", "").split(",")
            if group.strip()
        }
        policy_groups = set(role_policy[role_id].get("allowed_groups", []))
        if declared_groups != policy_groups:
            fail(f"tool group mismatch for {role_id}")


def validate_adapters(targets: list[dict]) -> None:
    for target in targets:
        adapter = load_json(require_path(target["adapter_manifest"]))
        if adapter.get("id") != target["id"]:
            fail(f"adapter id mismatch for {target['id']}")
        for template in adapter.get("mcp_templates", []):
            require_path(template)
        if adapter.get("status") != "template":
            fail(f"adapter status must remain template until verified: {target['id']}")


def validate_commands(commands: list[dict]) -> None:
    for command in commands:
        path = require_path(command["path"])
        text = path.read_text(encoding="utf-8")
        if command["id"] not in text.splitlines()[0]:
            fail(f"command title should include id: {command['id']}")
        if command["id"] == "develop-slice":
            if "Use skill: `deck-project-developer`" not in text:
                fail("develop-slice must use the deck-project-developer skill")
            for field in REPO_HANDOFF_FIELDS:
                if f"`{field}`" not in text:
                    fail(f"develop-slice missing repo handoff field: {field}")


def validate_coordination(manifest: dict) -> None:
    coordination_path = require_path(manifest["runtime"]["coordination"])
    text = coordination_path.read_text(encoding="utf-8")
    for heading in ("## Repo Development", "## Development Handoff Record", "## Runtime Coordination"):
        if heading not in text:
            fail(f"coordination file missing heading: {heading}")
    for field in REPO_HANDOFF_FIELDS:
        if f"`{field}`" not in text:
            fail(f"coordination file missing repo handoff field: {field}")
    required_phrases = (
        "one meaningful commit",
        "terminal-first runtime",
        "active CLI",
    )
    for phrase in required_phrases:
        if phrase not in text:
            fail(f"coordination file missing phrase: {phrase}")


def validate_development_skill(skills: list[dict]) -> None:
    for skill in skills:
        if skill["id"] != "deck-project-developer":
            continue
        text = (require_path(skill["path"]) / "SKILL.md").read_text(encoding="utf-8")
        required_phrases = (
            "`slice_goal`",
            "`files_in_scope`",
            "`commit_status`",
            "one meaningful commit",
        )
        for phrase in required_phrases:
            if phrase not in text:
                fail(f"deck-project-developer skill missing phrase: {phrase}")


def main() -> None:
    manifest = load_json(MANIFEST)
    if manifest.get("schema_version") != 1:
        fail("manifest schema_version must be 1")
    if manifest.get("canonical_instruction") != "AGENTS.md":
        fail("AGENTS.md must remain canonical")
    if not (ROOT / "AGENTS.md").exists():
        fail("missing AGENTS.md")
    if manifest.get("adapter_sources"):
        require_path(manifest["adapter_sources"])

    targets = manifest.get("targets", [])
    skills = manifest.get("skills", [])
    roles = manifest.get("roles", [])
    commands = manifest.get("commands", [])

    require_unique(targets, "target")
    require_unique(skills, "skill")
    role_ids = require_unique(roles, "role")
    require_unique(commands, "command")

    policy = load_json(require_path(manifest["tool_policy"]))
    validate_tool_policy(policy, role_ids)
    validate_handoff_policy(policy, role_ids)

    validate_skills(skills)
    validate_development_skill(skills)
    validate_agents(roles, policy)
    validate_adapters(targets)
    validate_commands(commands)
    validate_coordination(manifest)
    validate_mcp_templates()

    print("agent-pack validation passed")


if __name__ == "__main__":
    main()
