# Agent Instructions

## Mission

Build an open-source Decky plugin and companion extension pack that exposes existing AI CLI agents on Steam Deck without taking over the user's credentials, billing, or system shell.

## Instruction Order

Use this file as the canonical repo instruction set. Native host files such as [CLAUDE.md](CLAUDE.md) and [.github/copilot-instructions.md](.github/copilot-instructions.md) must stay consistent with it.

When instructions conflict, follow this order:

1. System and developer instructions from the active agent runtime.
2. The user's current request.
3. This file.
4. Host-specific instruction files.
5. General preferences inferred from existing code and docs.

## Read First

Before implementation work:

1. Read [ROADMAP.md](ROADMAP.md).
2. Read [docs/architecture.md](docs/architecture.md) before changing component boundaries.
3. Read [docs/interfaces.md](docs/interfaces.md) before adding CLI adapter, MCP, Decky, skill, plugin, or workflow contracts.
4. Read [docs/operations.md](docs/operations.md) before adding build, test, packaging, or release commands.
5. Read [CONTRIBUTING.md](CONTRIBUTING.md) before changing repo workflow, review gates, or release rules.

## Working Standard

- Keep work scoped to one coherent slice; finish implementation, docs, and verification for that slice before widening scope.
- Prefer simple, explicit modules with clear ownership over framework-heavy scaffolding.
- Prefer structured parsers, typed contracts, and subprocess/PTY APIs over shell string scraping.
- Keep Decky frontend thin; put session, tool, source, action, and safety logic in backend/core packages.
- Add tests around contracts, risk classification, source indexing, and command rendering before UI polish.
- Update docs when contracts, commands, directories, risk boundaries, or workflow rules change.
- Leave unrelated dirty worktree changes untouched.

## Non-Negotiable Constraints

- Do not read, export, copy, log, or upload AI CLI auth tokens.
- Do not build a hosted model proxy into the default path.
- Do not run background scans unless the user explicitly enables them.
- Do not auto-execute write, sudo, destructive, or system-level commands in the default path.
- Explicit owner-enabled per-profile CLI permission bypass may launch supported CLIs with their documented no-approval mode, but it must be disabled by default, visible in Settings, persisted per profile, and shown as `danger` risk.
- Do not run the Decky plugin as root by default.
- Do not add telemetry by default.
- Keep local resource use low enough for Steam Deck Gaming Mode.

## Release Channels

- `main` is the dev channel: dev builds are pre-release tags `vX.Y.Z-dev.N` (GitHub `prerelease=true`).
- The `stable` branch is the stable channel: stable builds are tags `vX.Y.Z` (GitHub "Latest", `prerelease=false`).
- Never publish a dev build to the stable channel and never mark a `-dev` tag as latest. Only tested commits are promoted from `main` to `stable`.
- The in-plugin self-update filters releases by the channel chosen in Settings (default stable). See [RELEASING.md](RELEASING.md) for the full policy and promotion flow.

## Extension Strategy

- Use Agent Skills for reusable procedures and knowledge workflows.
- Use MCP for live tools, source search, local Deck diagnostics, and action execution.
- Use CLI-specific adapters for process/session behavior only.
- Use custom agents for role separation: planner, diagnostics, safety reviewer, executor, knowledge curator.
- Package reusable skills and MCP config as plugins/extensions where each target CLI supports that natively.

## Agent Pack

- Treat [agent-pack/manifest.json](agent-pack/manifest.json) as the registry for repo-local skills, roles, commands, adapter templates, and conflict rules.
- Keep shared behavior in portable skills under `agent-pack/skills/`.
- Keep role boundaries in `agent-pack/agents/` and tool permissions in [agent-pack/tool-policy.json](agent-pack/tool-policy.json).
- Keep target-specific Codex and Claude packaging under `agent-pack/adapters/`; adapters must wrap shared assets instead of redefining safety rules.
- Run `python3 agent-pack/scripts/validate_agent_pack.py` after changing `agent-pack/`.

## Safety Model

Every local action must classify risk before execution:

| Risk | Examples | Required behavior |
| --- | --- | --- |
| read_only | list logs, inspect versions, query storage | Allowed after user request. |
| low_write | create backup, write plugin config, update local index | Show plan and get approval. |
| high_write | edit game config, launch option changes, flatpak permissions | Show exact diff/commands, backup, approval. |
| danger | sudo, rm, pacman, systemctl, chmod, readonly partition changes | Separate explicit approval and rollback/restore path where possible. |

Risk handling rules:

- Natural-language approval is not enough for dangerous commands; show the exact command or diff.
- Write actions need a staged plan before execution.
- High-write and danger actions need a backup or rollback note where possible.
- MCP tools must not bypass Decky-side approval for write actions unless the user has explicitly enabled per-profile owner bypass for the active CLI session; default behavior must keep staged approvals.

## Verification

For documentation-only changes, run the repo docs validator listed in [docs/operations.md](docs/operations.md).

For implementation changes, run the narrowest reliable checks first, then the broader package checks once they exist. If a check cannot run locally, document the reason in the final handoff.
