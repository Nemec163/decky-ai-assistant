# Interfaces

## HTTP / RPC APIs

| Interface | Contract | Source anchors |
| --- | --- | --- |
| Decky frontend to backend | Typed calls for profile settings, managed CLI setup/auth, native assistant pack install planning, per-profile permission-bypass planning/settings, in-memory terminal auth links, terminal display/input settings, voice settings, external transcription settings/calls, background PTY session lifecycle, plugin update checks, and diagnostics. Sources and broader assistant UI are planned. | [main.py](../main.py), [src/index.tsx](../src/index.tsx), [ROADMAP.md](../ROADMAP.md) |
| Decky Terminal Mode frontend to backend | `ping`, profile health/setup calls, `open_cli_setup_action`, `install_agent_pack`, plugin update calls, permission-bypass settings, terminal config, voice capture/transcription, session list/open/start/read/write/resize/interrupt/restart/stop calls, and `get_storage_plan`. Setup, agent-pack install, and update actions are direct user-requested low-write workflows. Terminal Mode launches built-in and custom profiles from structured argv and reports risk for display only. | [main.py](../main.py), [src/index.tsx](../src/index.tsx), [docs/operations.md](operations.md) |
| Optional local streaming transport | Planned terminal stream transport if Decky method calls are insufficient for PTY throughput. | [ROADMAP.md](../ROADMAP.md) |
| Optional hosted pack registry | Static JSON registry with pack metadata and artifact URLs. | [ROADMAP.md](../ROADMAP.md) |

## CLI / Commands

| Command | Purpose | Source anchors |
| --- | --- | --- |
| `codex` | Launch Codex CLI in user-requested Terminal Mode. | [packages/core/src/deck_assistant_core/cli.py](../packages/core/src/deck_assistant_core/cli.py), [ROADMAP.md](../ROADMAP.md) |
| `codex --version` | Read-only Codex CLI availability probe. | [packages/core/src/deck_assistant_core/cli.py](../packages/core/src/deck_assistant_core/cli.py) |
| `codex login status` | Read-only Codex auth status check where available. | [packages/core/src/deck_assistant_core/cli.py](../packages/core/src/deck_assistant_core/cli.py), [ROADMAP.md](../ROADMAP.md) |
| `npm install --prefix ~/.local/share/decky-ai-assistant/npm @openai/codex@latest` | User-requested managed latest-version Codex CLI install/update flow, launched in PTY without `sudo`; bootstraps user-local Node.js 22 first if npm is unavailable. | [packages/core/src/deck_assistant_core/cli.py](../packages/core/src/deck_assistant_core/cli.py) |
| `codex login` | Official Codex auth flow launched in PTY; plugin does not read auth stores. | [packages/core/src/deck_assistant_core/cli.py](../packages/core/src/deck_assistant_core/cli.py) |
| `claude` | Launch Claude Code in user-requested Terminal Mode. | [packages/core/src/deck_assistant_core/cli.py](../packages/core/src/deck_assistant_core/cli.py), [ROADMAP.md](../ROADMAP.md) |
| `claude --version` | Read-only Claude Code availability probe. | [packages/core/src/deck_assistant_core/cli.py](../packages/core/src/deck_assistant_core/cli.py) |
| `npm install --prefix ~/.local/share/decky-ai-assistant/npm @anthropic-ai/claude-code@latest` | User-requested managed latest-version Claude Code install/update flow, launched in PTY without `sudo`; bootstraps user-local Node.js 22 first if npm is unavailable. | [packages/core/src/deck_assistant_core/cli.py](../packages/core/src/deck_assistant_core/cli.py) |
| `claude` setup auth | Official Claude Code first-run/login flow launched in PTY; plugin does not read auth stores. | [packages/core/src/deck_assistant_core/cli.py](../packages/core/src/deck_assistant_core/cli.py) |
| `/voice tap` | User-triggered Claude Code native voice command sent into an active Claude PTY when native voice is explicitly enabled; Claude owns microphone capture, transcription, auth/account checks, and provider-side audio handling. | [src/pages/TerminalPage.tsx](../src/pages/TerminalPage.tsx) |
| `bash` | Baseline user-requested Terminal Mode profile. | [packages/core/src/deck_assistant_core/cli.py](../packages/core/src/deck_assistant_core/cli.py), [ROADMAP.md](../ROADMAP.md) |
| `bash --version` | Read-only baseline shell availability probe. | [packages/core/src/deck_assistant_core/cli.py](../packages/core/src/deck_assistant_core/cli.py) |
| custom command | User-defined terminal profile created from structured `argv` only; no shell-string storage, no default version/auth probes, and launch risk is classified for display only. | [packages/core/src/deck_assistant_core/cli.py](../packages/core/src/deck_assistant_core/cli.py), [ROADMAP.md](../ROADMAP.md) |
| `python -m deck_assistant_mcp serve` | Stdio MCP server exposing the Deck tool catalog over newline-delimited JSON-RPC 2.0. It provides diagnostics, cited knowledge surfaces, and concise fix plans. Requested writes stay in the active CLI terminal workflow. | [packages/mcp-server/src/deck_assistant_mcp/server.py](../packages/mcp-server/src/deck_assistant_mcp/server.py) |

## MCP Tools

| Tool | Contract | Risk | Source anchors |
| --- | --- | --- | --- |
| `search_knowledge` | Query enabled knowledge packs and return at most 20 non-empty cited chunks with known source types, source/document/path metadata, and internally consistent chunk and line citations. | read_only | [packages/core/src/deck_assistant_core/knowledge/](../packages/core/src/deck_assistant_core/knowledge/), [ROADMAP.md](../ROADMAP.md) |
| `list_sources` | Return non-empty source status, license, revision, URL, known source type, and enabled state. | read_only | [packages/core/src/deck_assistant_core/knowledge/](../packages/core/src/deck_assistant_core/knowledge/), [ROADMAP.md](../ROADMAP.md) |
| `inspect_current_game` | Return selected/current Steam app context where available. | read_only | [ROADMAP.md](../ROADMAP.md) |
| `read_proton_logs` | Locate and read relevant Proton logs using bounded local readers and return the core Proton log report contract shape. | read_only | [packages/core/src/deck_assistant_core/diagnostics.py](../packages/core/src/deck_assistant_core/diagnostics.py), [ROADMAP.md](../ROADMAP.md) |
| `get_storage_report` | Summarize shader cache, compatdata, logs, screenshots/videos using bounded local readers and return the core storage report contract shape. | read_only | [packages/core/src/deck_assistant_core/diagnostics.py](../packages/core/src/deck_assistant_core/diagnostics.py), [ROADMAP.md](../ROADMAP.md) |
| `propose_fix` | Convert evidence into a concise plan and risk classification. | read_only | [ROADMAP.md](../ROADMAP.md) |

## Agent Pack Contracts

| Contract | Purpose | Source anchors |
| --- | --- | --- |
| `agent-pack/manifest.json` | Registry for skills, roles, commands, adapter manifests, tool policy, and conflict rules. | [agent-pack/manifest.json](../agent-pack/manifest.json) |
| `agent-pack/tool-policy.json` | MCP tool groups and role permissions. | [agent-pack/tool-policy.json](../agent-pack/tool-policy.json) |
| Adapter manifests | Codex and Claude packaging metadata with MCP examples and release-template status. | [agent-pack/adapters/codex/manifest.json](../agent-pack/adapters/codex/manifest.json), [agent-pack/adapters/claude/manifest.json](../agent-pack/adapters/claude/manifest.json) |
| Adapter source notes | Verified official MCP config references and remaining packaging caveats. | [agent-pack/adapters/sources.md](../agent-pack/adapters/sources.md) |
| Runtime coordination | Role ownership, handoff records, and terminal-first workflow ownership. | [agent-pack/runtime/coordination.md](../agent-pack/runtime/coordination.md) |
| Tool policy validation | Validator checks MCP tool coverage, duplicate group assignment, and role/tool-group consistency. | [agent-pack/scripts/validate_agent_pack.py](../agent-pack/scripts/validate_agent_pack.py), [agent-pack/tool-policy.json](../agent-pack/tool-policy.json) |
| Native assistant pack install | User-local Codex plugin with `./`-relative marketplace source, plugin `.mcp.json`, global Codex runtime skills, and a managed Codex workspace whose `AGENTS.md` sets the Steam Deck assistant identity and whose `.codex/config.toml` registers the local `deck-assistant` MCP server; self-contained Claude plugin bundle under `~/.claude/plugins`, plus direct user-level Claude skills/agents/commands and a managed Claude workspace whose `CLAUDE.md` sets the Steam Deck assistant identity and whose `.mcp.json`/`settings.local.json` register and pre-enable the local `deck-assistant` MCP server, all generated from the bundled `agent-pack`; managed marker files prevent overwriting unrelated directories or files. | [packages/core/src/deck_assistant_core/agent_pack.py](../packages/core/src/deck_assistant_core/agent_pack.py) |

## Jobs / Events / Webhooks

| Interface | Trigger | Side effects | Source anchors |
| --- | --- | --- | --- |
| Knowledge indexing job | User adds or updates source. | Fetches and writes local index files. | [ROADMAP.md](../ROADMAP.md) |
| Public pack build job | Scheduled GitHub Action or manual release. | Builds static pack artifacts. | [ROADMAP.md](../ROADMAP.md) |

## Package / Module Exports

| Export | Consumers | Source anchors |
| --- | --- | --- |
| PTY session manager | Decky backend, tests | Initial bounded POSIX PTY lifecycle contract for start, transient setup start/open-or-reattach, write, read, resize, interrupt, stop, restart, custom profile injection, child env sanitization, managed npm bin path injection, Codex/Claude managed-workspace cwd selection, and list operations implemented in [packages/core/src/deck_assistant_core/pty_session.py](../packages/core/src/deck_assistant_core/pty_session.py). |
| Decky Terminal Mode plugin | On-Deck development testing | Root-level Decky template shell implemented in [src/index.tsx](../src/index.tsx) and [main.py](../main.py). It exposes backend ping, CLI profile contract listing/health, managed setup plan/action calls, in-memory auth-link capture, terminal display/input and voice settings, opt-in external transcription settings/calls, launchable-only profile launcher panel, route-based xterm terminal pages, consolidated Diagnostics health check and plugin-update panel, background session listing, and user-requested PTY session lifecycle calls. |
| CLI adapter contract | Decky backend, tests | Built-in profile, custom structured-argv profile, managed npm setup plan, Decky-friendly executable resolution, managed Node.js runtime discovery, stable user-home/XDG environment normalization, profile workspace path rendering, sanitized probe environments for minimal `PATH` runtimes, launch planning, detection, version probe, auth-status, aggregate health summary, and risk metadata implemented in [packages/core/src/deck_assistant_core/cli.py](../packages/core/src/deck_assistant_core/cli.py). |
| Native agent pack installer | Decky backend, tests | Target support listing, install-plan rendering, Codex/Claude user-local extension tree population, Codex marketplace merge with `./`-relative local paths, Codex global runtime skill sync, Codex plugin-bundled MCP metadata, managed Codex workspace identity (`AGENTS.md`) and `deck-assistant` MCP registration (`.codex/config.toml`), Claude plugin-bundle install plus direct user-level skill/agent/command sync, managed Claude workspace identity (`CLAUDE.md`) and `deck-assistant` MCP registration (`.mcp.json`, `settings.local.json`), managed-directory/file marker validation, missing-source reporting, and deduplicated install result counts implemented in [packages/core/src/deck_assistant_core/agent_pack.py](../packages/core/src/deck_assistant_core/agent_pack.py). |
| Permission-bypass planner | Decky backend, tests | Explicit per-profile permission-bypass plans, CLI-native bypass arg rendering, custom-profile trust handling, and `danger` risk reporting are implemented in [packages/core/src/deck_assistant_core/cli.py](../packages/core/src/deck_assistant_core/cli.py); backend settings decide whether launch argv is rewritten. |
| Knowledge pack schema/search | Indexer, registry, UI, MCP server | Source, license, revision, hash, manifest, document, chunk, citation, deterministic manifest building from supplied document contents, deterministic local-folder manifest building from filtered UTF-8 files, deterministic chunking, pre-index source file filtering, local-folder source inventory, in-memory source registry state, in-memory search result/index contracts, and persisted SQLite FTS5/BM25 index files implemented in [packages/core/src/deck_assistant_core/knowledge/](../packages/core/src/deck_assistant_core/knowledge/). The MCP dispatcher can read an injected knowledge index for `search_knowledge` and `list_sources`. |
| Diagnostics report contracts | Decky backend, MCP diagnostics tools, tests | Implemented in [packages/core/src/deck_assistant_core/diagnostics.py](../packages/core/src/deck_assistant_core/diagnostics.py). Storage path planning, storage reports, Proton log reports, bounded filesystem storage readers, and bounded Proton log readers model read-only results with warnings, limits, status inference, and JSON round-trips. |
| Risk classifier | Assistant workflows, MCP server | Implemented in [packages/core/src/deck_assistant_core/risk.py](../packages/core/src/deck_assistant_core/risk.py). |
| MCP contract catalog and dispatcher | Agent pack adapters, MCP transport, tests | Static catalog version 5 tool contracts, precise knowledge citation fields, typed diagnostics/proposal schemas, detached catalog export, duplicate-name validation, risk invariants, optional injected knowledge index or read-only handlers/readers, and fix-planning handling implemented in [packages/mcp-server/src/deck_assistant_mcp/contracts.py](../packages/mcp-server/src/deck_assistant_mcp/contracts.py) and [packages/mcp-server/src/deck_assistant_mcp/dispatcher.py](../packages/mcp-server/src/deck_assistant_mcp/dispatcher.py); a newline-delimited JSON-RPC 2.0 stdio MCP transport wraps the dispatcher with real bounded diagnostics readers. |
| Agent pack validator | Maintainers and CI | [agent-pack/scripts/validate_agent_pack.py](../agent-pack/scripts/validate_agent_pack.py) |

## Agent Extension Surfaces

| Surface | Contract | Consumers |
| --- | --- | --- |
| Agent Skills | Portable `SKILL.md` workflows with focused descriptions and supporting files. | Codex, Claude, and Copilot-compatible hosts where supported |
| Custom agents/subagents | Narrow roles with clear risk posture. | Codex and Claude where supported |
| CLI plugin/extension packaging | Target-native distribution manifests and user-local installed adapter trees. | Codex and Claude plugins |
| Workflow commands | User-invoked shortcuts for common Deck diagnostics. | Supported CLI command systems |
| Repo instruction files | Durable repo rules with `AGENTS.md` as canonical and host-specific mirrors. | Codex, Claude, GitHub Copilot |
| Adapter templates | Target-native wrapper manifests and MCP examples. | Codex and Claude |

Portable runtime skills currently include `deck-diagnose-game`, `deck-storage-doctor`, `deck-flatpak-doctor`, and `deck-knowledge-curator`.

## Compatibility Notes

- Codex and Claude are the supported target-native assistant pack hosts.
- OpenCode should be treated as reference material for primary-agent/subagent separation, not as an MVP provider target.
- Hermes and OpenClaw are reference architectures, not MVP dependencies.
- Every target CLI adapter must degrade to plain Terminal Mode if native plugin/skill integration is unavailable.
- Terminal voice controls must degrade to plain typed/pasted Terminal Mode when external API recording/transcription or an explicitly selected CLI-native voice path is unavailable.
- Claude Code native voice support was checked against official docs on 2026-06-23: `/voice` is available in Claude Code v2.1.69 or later, with `/voice tap` requiring v2.1.116 or later; transcription is owned by Claude Code, not this plugin, and remains opt-in. Codex CLI has no documented stable native voice command in the official Codex CLI docs checked the same day, so Codex uses the configured external transcription path when available.
- MCP config shapes for Claude Code were verified against official docs on 2026-06-21; Codex MCP and plugin metadata paths were rechecked against official OpenAI Codex docs on 2026-06-23. Bundled native adapter installation is implemented as user-local file installation, while public marketplace/release distribution remains separate release work.
