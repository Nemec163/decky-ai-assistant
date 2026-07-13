# Repository Map

## Directory Map

| Path | Purpose | Notes |
| --- | --- | --- |
| `/` | Project root, Decky plugin entry files, public docs, license, agent instructions, workflow rules | Root-level plugin files follow the official Decky template layout. |
| `docs/` | Lean repository documentation | Maintained for AI agents and humans. |
| `.github/` | GitHub-facing instructions and PR workflow | Contains Copilot instructions and PR template; CI not created yet. |
| `agent-pack/` | Repo-local AI agent workflows, roles, commands, adapters, and validation | Created; bundled into the Decky ZIP for user-local native assistant pack installs. Public release packaging remains separate work. |
| `src/` | Decky plugin frontend | Terminal Mode MVP with xterm.js, launchable-only profile launcher panel, route-based terminal page, route-based Settings navigation, managed CLI setup/auth controls, native assistant pack controls, per-profile permission-bypass toggles, profile settings, separate terminal input/display and voice settings pages, PTY controls, direct xterm input, and backend/core contract checks. |
| `main.py` | Decky Python backend entrypoint | Backend for ping, CLI profile listing/health, managed setup plan/action calls, native assistant pack plan/install calls, per-profile permission-bypass plan/update calls, custom profile settings, terminal display/input/voice config, profile open-or-reattach, storage path planning, and user-requested PTY session lifecycle for up to eight concurrent sessions; no credential reads, background scans, or automatic command execution in default mode. |
| `plugin.json`, `package.json`, `rollup.config.js`, `tsconfig.json` | Decky plugin metadata/build config | Based on the official Decky plugin template root layout. |
| `scripts/` | Local project helper scripts | Includes ZIP packaging and smoke deploy helpers for Deck testing. |
| `packages/core/` | Shared domain logic | Initial Python contracts for PTY sessions, managed CLI setup plans with user-local Node/npm bootstrap, user-local native assistant pack installs, per-profile permission-bypass planning, risk classification, CLI profile detection, knowledge packs/search including local-folder pack manifest builds, source registry state, persisted SQLite FTS5/BM25 indexes, and read-only diagnostics reports. |
| `packages/mcp-server/` | Local MCP contract package | Created as stdlib-only tool contracts plus an injectable in-process dispatcher shell with read-only knowledge index, diagnostics, and proposal hooks; transport/server implementation exists for the current catalog. |
| `agent-pack/skills/` | Portable Agent Skills for development, runtime support, game/storage/Flatpak diagnostics, and knowledge curation | Created. |
| `agent-pack/agents/` | Custom agent role profiles and handoff boundaries | Created. |
| `agent-pack/commands/` | Deterministic workflow command templates | Created. |
| `agent-pack/adapters/` | Codex and Claude adapter manifests plus source notes | MCP config shape verified; release packaging still template status. |
| `agent-pack/mcp/` | Target MCP config examples | MCP config shape verified against official docs on 2026-06-21. |
| `pack-registry/` | Planned static registry and pack build metadata | Not created yet. |
| `.github/workflows/` | Planned CI and pack rebuild jobs | Not created yet. |

## Key Modules

| Module | Owns | Main files |
| --- | --- | --- |
| Decky plugin | Gaming Mode Terminal Mode MVP with launchable-only profile launcher, terminal toolbar controls, Settings route with separate terminal and voice pages, managed setup/auth controls, native assistant pack controls, per-profile permission-bypass toggles, terminal voice input, and background sessions now; broader assistant and knowledge UI planned | [src/index.tsx](../src/index.tsx), [main.py](../main.py), [docs/operations.md](operations.md) |
| PTY/session manager | Interactive terminal sessions for AI CLIs, setup/auth flows, and shell with sanitized child env, managed npm bin path injection, Claude managed-workspace cwd selection, and injected custom profiles | Initial contract in [packages/core/src/deck_assistant_core/pty_session.py](../packages/core/src/deck_assistant_core/pty_session.py); Decky backend transport planned. |
| CLI adapters | Detect, launch, health-check provider CLIs, plan managed latest npm installs/auth flows with user-local Node.js bootstrap, resolve executables and sanitize probe environments in minimal Decky `PATH` runtimes, summarize profile health, render profile workspace paths, render CLI-native permission-bypass args, and represent custom structured-argv terminal profiles | Initial contracts in [packages/core/src/deck_assistant_core/cli.py](../packages/core/src/deck_assistant_core/cli.py). |
| Native agent pack installer | Install bundled Codex and Claude assistant assets into user-local extension directories with managed marker checks; Claude install also syncs direct user-level skills/agents and prepares the managed Claude workspace | [packages/core/src/deck_assistant_core/agent_pack.py](../packages/core/src/deck_assistant_core/agent_pack.py). |
| Knowledge manager | Sources, source registry state, packs, deterministic source filtering and inventory, local-folder manifest building, in-memory and persisted SQLite FTS5/BM25 indexing, citations, licensing | Initial contracts in [packages/core/src/deck_assistant_core/knowledge/](../packages/core/src/deck_assistant_core/knowledge/); source fetching and persistence wiring planned. |
| Diagnostics reports | Typed read-only path planning, bounded filesystem readers, and report contracts for storage sections, bounded Proton log excerpts, warnings, limits, and status inference | Initial contracts and readers in [packages/core/src/deck_assistant_core/diagnostics.py](../packages/core/src/deck_assistant_core/diagnostics.py). |
| MCP server | Static tool contract catalog and injectable in-process dispatcher shell for AI CLIs | Contract catalog in [packages/mcp-server/src/deck_assistant_mcp/contracts.py](../packages/mcp-server/src/deck_assistant_mcp/contracts.py), dispatcher shell in [packages/mcp-server/src/deck_assistant_mcp/dispatcher.py](../packages/mcp-server/src/deck_assistant_mcp/dispatcher.py), including read-only knowledge search/source listing from an injected knowledge index, diagnostics, and fix planning; transport/server implementation exists for the current catalog. |
| Agent pack | Portable skills including game/storage/Flatpak diagnostics, custom agents, workflow commands, adapter manifests, MCP templates, conflict rules, and bundled native install source files | [agent-pack/manifest.json](../agent-pack/manifest.json) |

## Generated / External / Ignore Zones

| Path | Reason |
| --- | --- |
| Dependency directories | Dependency output; ignored. |
| Build output directories | Generated artifacts; ignored. |
| `.cache/`, `tmp/` | Local transient data; ignored. |
| `*.sqlite`, `*.sqlite3`, `*.db` | Local knowledge indexes; ignored until fixtures are explicitly needed. |
| `.env`, `.env.*` | Secrets; ignored except `.env.example`. |

## Tests

| Path | Test type | Notes |
| --- | --- | --- |
| [packages/core/tests](../packages/core/tests) | Unit tests | Stdlib `unittest` coverage for PTY session lifecycle, transient setup sessions, managed CLI setup plans, native assistant pack installation, permission-bypass planning, risk classification, CLI profile detection/custom profile contracts, knowledge source filtering/source registry/search/local-folder manifest building, SQLite FTS5/BM25 persistence, and diagnostics report contracts. |
| [packages/mcp-server/tests](../packages/mcp-server/tests) | Unit tests | Stdlib `unittest` coverage for MCP tool contract order, risk mapping, detached catalog exports, injected read-only knowledge/diagnostics dispatcher handlers/readers, invariant validation, and contract-only exports. |
| [agent-pack/scripts/validate_agent_pack.py](../agent-pack/scripts/validate_agent_pack.py) | Agent pack consistency check | Stdlib Python; validates manifest files plus MCP tool policy coverage and role/tool-group consistency. |

## Config And Tooling

| Path | Purpose |
| --- | --- |
| [.gitignore](../.gitignore) | Ignore local, generated, dependency, and secret files. |
| [AGENTS.md](../AGENTS.md) | Instructions for AI agents working in the repo. |
| [CLAUDE.md](../CLAUDE.md) | Claude Code native instruction mirror. |
| [.github/copilot-instructions.md](../.github/copilot-instructions.md) | GitHub Copilot instruction mirror. |
| [.github/pull_request_template.md](../.github/pull_request_template.md) | PR checklist for verification, safety, and docs. |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Contributor workflow and safety review rules. |
| [.editorconfig](../.editorconfig) | Shared editor whitespace and newline defaults. |
| [.gitattributes](../.gitattributes) | Text normalization and binary file hints. |
| [LICENSE](../LICENSE) | MIT license. |
| [ROADMAP.md](../ROADMAP.md) | Implementation plan and acceptance checks. |
| [agent-pack/manifest.json](../agent-pack/manifest.json) | Agent pack registry. |
| [agent-pack/tool-policy.json](../agent-pack/tool-policy.json) | MCP tool groups and role permissions. |
| [package.json](../package.json) | Decky frontend build scripts and dependencies. |
| [plugin.json](../plugin.json) | Decky plugin metadata. |
| [scripts/package_decky_plugin.sh](../scripts/package_decky_plugin.sh) | Builds a Decky-compatible ZIP under ignored `out`. |
