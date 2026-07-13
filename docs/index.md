# Repository Guide

## Summary

- Planning repository for an open-source Steam Deck AI assistant built as a Decky plugin.
- Default model access uses the user's existing AI CLI login for Codex, Claude, or custom commands.
- The project combines Decky UI, PTY terminal sessions, local MCP tools, Agent Skills, knowledge packs, and risk metadata while keeping writes in the active CLI workflow.
- Repository workflow is standardized through root agent instructions, host-specific instruction files, and [CONTRIBUTING.md](../CONTRIBUTING.md).
- Repo-local agent workflows live in [agent-pack/manifest.json](../agent-pack/manifest.json) with portable skills for game, storage, Flatpak, and knowledge workflows, custom agent roles, commands, MCP templates, and adapter manifests.
- Initial shared core contracts exist for PTY sessions including Claude managed-workspace cwd selection, managed CLI setup plans with user-local Node/npm bootstrap, user-local native assistant pack installs including Claude direct user-level skills/agents, per-profile permission-bypass planning, risk classification, CLI profile detection, knowledge packs/search/local-folder manifest builds, source registry state, persisted SQLite FTS5/BM25 knowledge indexes, read-only diagnostics reports, and MCP knowledge dispatch backed by an injected knowledge index.
- A root-level Decky Terminal Mode MVP with a launchable-only profile launcher, route-based xterm terminal pages, Settings profile/setup/native-pack management, per-profile permission-bypass toggles, separate terminal input and voice settings pages, and background PTY sessions now exists for on-Deck testing: [src/index.tsx](../src/index.tsx), [main.py](../main.py), [plugin.json](../plugin.json), and the smoke checklist in [operations.md](operations.md).

## Stack

| Area | Technology | Source |
| --- | --- | --- |
| Decky plugin frontend | React, TypeScript, `@decky/ui`, `@xterm/xterm` | Terminal Mode shell in [src/index.tsx](../src/index.tsx). |
| Terminal rendering | `xterm.js` | Initial Terminal Mode MVP in [src/index.tsx](../src/index.tsx); broader workflow polish planned in [ROADMAP.md](../ROADMAP.md). |
| Backend | Python Decky backend, PTY process control | PTY Decky wiring in [main.py](../main.py); initial PTY session manager plus read-only diagnostics contracts/readers live under [packages/core/src/deck_assistant_core](../packages/core/src/deck_assistant_core). |
| Knowledge search | Source inventories, source registry state, filtered local-folder manifest builds, in-memory search, persisted SQLite FTS5/BM25 search now; embeddings optional later | Initial contracts live under [packages/core/src/deck_assistant_core](../packages/core/src/deck_assistant_core); source fetching, persistence wiring, and UI are planned in [ROADMAP.md](../ROADMAP.md) |
| Agent tools | MCP contracts and injectable in-process dispatcher shell now, including read-only knowledge search/source listing when given a knowledge index plus diagnostics and fix-planning tools; full MCP server transport exists for the current catalog | Initial package lives under [packages/mcp-server/src/deck_assistant_mcp](../packages/mcp-server/src/deck_assistant_mcp); roadmap in [ROADMAP.md](../ROADMAP.md) |
| Agent workflows | Repo-local skills, custom agents, commands, plugin/extension templates, and bundled native install assets | [agent-pack/manifest.json](../agent-pack/manifest.json) |
| Repo workflow | `AGENTS.md`, `CLAUDE.md`, Copilot instructions, PR template | Root config files |

## Start Here

| Task | Read | Source anchors |
| --- | --- | --- |
| Understand product direction | [ROADMAP.md](../ROADMAP.md) | Product Definition, Target Architecture |
| Understand boundaries | [architecture.md](architecture.md) | Components, Boundaries |
| Add or change public contracts | [interfaces.md](interfaces.md) | CLI, MCP, plugin, skill contracts |
| Add build, test, or release commands | [operations.md](operations.md) | Verification, Build And Release |
| Implement future code layout | [repo-map.md](repo-map.md) | Directory Map |
| Contribute or review changes | [../CONTRIBUTING.md](../CONTRIBUTING.md) | Workflow, runtime review, PR checklist |
| Change agent workflows or adapters | [../agent-pack/manifest.json](../agent-pack/manifest.json) | Agent pack registry and validator |

## Commands

| Task | Command | Notes |
| --- | --- | --- |
| Check git state | `git status --short` | Repository initialized. |
| Validate repo docs | `python3 /Users/nmc/.codex/skills/repo-docs/scripts/validate_repo_docs.py /Users/nmc/Documents/WORK-NMC/GitHub/decky-ai-assistant` | Uses local Codex repo-docs skill validator. |
| Validate agent pack | `python3 agent-pack/scripts/validate_agent_pack.py` | Checks skills, roles, commands, adapters, and tool policy consistency. |
| Test core contracts | `PYTHONPATH=packages/core/src python3 -m unittest discover -s packages/core/tests` | Runs stdlib unit tests for PTY session, risk, CLI profile, knowledge/source registry, and diagnostics contracts. |
| Install frontend deps | `npm exec --yes pnpm@9 -- install` | Uses Decky template's `pnpm` v9 expectation. |
| Typecheck plugin | `npm exec --yes pnpm@9 -- run check` | Runs `tsc --noEmit` for Decky frontend types. |
| Build plugin | `npm exec --yes pnpm@9 -- run build` | Emits ignored local bundle under `dist`. |
| Package plugin ZIP | `npm exec --yes pnpm@9 -- run package` | Creates install-by-URL ZIP under ignored `out`. |
| Deploy plugin over SSH | `scripts/deploy_decky_smoke.sh deck@steamdeck.local` | Dev-only loop; copies built Terminal Mode runtime to `~/homebrew/plugins/decky-ai-assistant`; see [operations.md](operations.md). |

## Main Entrypoints

| Entrypoint | Purpose |
| --- | --- |
| [README.md](../README.md) | Public overview. |
| [ROADMAP.md](../ROADMAP.md) | Step-by-step implementation roadmap. |
| [AGENTS.md](../AGENTS.md) | Durable instructions for AI agents working in the repo. |
| [CLAUDE.md](../CLAUDE.md) | Claude Code native instruction mirror. |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Contributor workflow and review rules. |
| [agent-pack/manifest.json](../agent-pack/manifest.json) | Repo-local agent workflow registry. |
| [docs/architecture.md](architecture.md) | Planned system model. |
| [docs/interfaces.md](interfaces.md) | Planned public contracts and integration surfaces. |

## High-Risk Notes

- The project runs local commands through user-started terminal sessions; write actions must be risk-labeled and left to the active CLI's approval/sandbox behavior.
- AI CLI credentials are owned by each CLI and must not be read or exported by this plugin.
- Steam Deck resource budget matters; avoid local LLMs, background indexing, and always-on agents by default.
- Hosted services are optional future work and must not become required for the open-source path.
