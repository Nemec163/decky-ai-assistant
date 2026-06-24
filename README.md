# Decky AI Assistant

Run your existing AI coding CLIs — and a safety-first Steam Deck support assistant — directly from Steam Deck Gaming Mode, through a [Decky Loader](https://decky.xyz) plugin.

Decky AI Assistant brings **Codex CLI**, **Claude Code**, `bash`, and your own custom commands into a controller-friendly terminal on the Deck, then layers a portable agent pack (skills, roles, and a local MCP tool server) on top so those CLIs can diagnose Steam Deck problems with **read-only tools and explicit, staged approval** for anything that writes.

It is **bring-your-own-account**: the plugin launches the CLIs you already log into. It never proxies model access, never reads your provider credentials, adds no telemetry, and does not run as root by default.

> **Status:** Terminal Mode is a working MVP you can use today. The agent layer ships a complete, unit-tested safety model (risk classification, staged actions, role separation) and a local MCP server with read-only Deck diagnostics. Live knowledge-pack search and the approval-gated action runner are in active development — see [Project status](#project-status).

---

## Why

Steam Deck is a full Linux machine, but Gaming Mode gives you no comfortable terminal and no easy way to ask "why won't this game launch?" without dropping to Desktop Mode. Meanwhile, capable AI CLIs already exist and you already pay for them. Decky AI Assistant connects the two — without taking over your accounts, your shell, or your data.

## Features

- **Terminal Mode** — `xterm.js` frontend over a real Python PTY. Controller-friendly: D-pad navigation, on-screen-keyboard, extra-keys row, and a Gaming-Mode clipboard paste path that reads the gamescope Xwayland selection directly via libX11. Sessions survive closing the panel until you stop them.
- **Built-in & custom profiles** — `codex`, `claude`, `bash`, and user-defined profiles built from structured `argv` (never opaque shell strings).
- **Managed CLI setup & auth** — install or update the latest Codex CLI / Claude Code into a user-local npm prefix (`~/.local/share/decky-ai-assistant/npm`), bootstrapping a user-local Node.js runtime if needed, then open the official login flow inside the terminal. Auth links printed by the CLI get Open / Copy / Hide buttons. The plugin never reads or stores provider tokens.
- **Native agent pack install** — one-click install of the bundled Deck assistant pack into Codex and Claude user-local extension paths: portable skills, role subagents, slash commands, a managed workspace that frames the session as the Steam Deck assistant, and `deck-assistant` MCP server wiring.
- **Local MCP server (`deck-assistant`)** — a dependency-free JSON-RPC stdio server (`python -m deck_assistant_mcp serve`) exposing read-only Deck diagnostics (`read_proton_logs`, `get_storage_report`, …), cited knowledge search, and a non-executing `stage_action` tool. It refuses approval-gated execution by default.
- **Safety model** — every local action is risk-classified (`read_only` / `low_write` / `high_write` / `danger`). Writes are staged as reviewable plans; destructive commands require exact diffs, backups, and separate confirmation. Credential paths are rejected outright.
- **Voice input (optional)** — push-to-talk that records a bounded clip for a user-configured OpenAI-compatible transcription endpoint, or Claude Code's native `/voice tap`. Disabled until you configure it; mic capture only starts on a user action.
- **Per-profile permission bypass** — an explicit, `danger`-classified, off-by-default toggle that launches Codex/Claude in their documented no-approval mode for users who want it.
- **In-plugin self-update with dev/stable channels** — update from GitHub Releases without leaving the Deck; pick the **stable** or **dev** channel in Settings (see [Release channels](#release-channels)).

## Install

Decky AI Assistant installs as a Decky Loader plugin from a release ZIP.

1. Install [Decky Loader](https://decky.xyz) on your Steam Deck.
2. In Decky, use **Install from URL** (developer setting) and point it at the release asset named `decky-ai-assistant-v<version>.zip` from [Releases](https://github.com/Nemec163/decky-ai-assistant/releases).
3. Open the plugin in Gaming Mode, pick a profile, and (for `codex`/`claude`) install/log in from **Settings** if the CLI isn't present yet.

> Do **not** install GitHub's automatic `Source code (zip)` archive — it lacks the built `dist/index.js` frontend bundle and will not load in SteamUI. Always use the `decky-ai-assistant-v<version>.zip` asset.

### Release channels

Releases are published on two channels; choose one in **Settings → Diagnostics → Plugin Update**:

| Channel | Who it's for | Versions | GitHub release |
| --- | --- | --- | --- |
| **stable** (default) | Everyday use | `vX.Y.Z` | marked "Latest" |
| **dev** | Testing newest changes | `vX.Y.Z-dev.N` | marked "Pre-release" |

A stable install only ever sees stable releases; a dev install also receives pre-releases. Full policy and the maintainer workflow live in [RELEASING.md](RELEASING.md).

## Privacy & safety principles

- Use your existing official CLI login. **No hosted model proxy** is ever added to the default path.
- **Never** read, export, copy, log, or upload AI CLI auth tokens or credential stores.
- **No telemetry**, no background scans, and no cloud sync by default.
- **Not root by default.** The plugin uses a user-local Node/npm prefix and never `sudo`/`pacman`/system-shell edits for setup.
- **Read-only is the default.** Writes are staged and require explicit Decky approval; dangerous actions require separate confirmation and a rollback note.

## Project status

| Area | State |
| --- | --- |
| Terminal Mode (PTY, xterm, controller, clipboard, OSK) | ✅ Working MVP |
| Managed Codex/Claude setup + official auth flow | ✅ Working |
| Native agent pack install (Codex & Claude) | ✅ Working |
| Safety contracts: risk model, staged actions, roles, tool policy | ✅ Complete & unit-tested |
| MCP server: stdio transport + read-only diagnostics (Proton logs, storage) | ✅ Working |
| MCP: live knowledge-pack search / `inspect_current_game` / `propose_fix` | 🚧 Stubbed — wiring in progress |
| Runtime approval bridge (`stage_action` → Decky approval → `run_approved_action`) | 🚧 Designed & tested in isolation; cross-process bridge in progress |
| Assistant / Knowledge / Approvals UI | 🗺️ Planned |

See [ROADMAP.md](ROADMAP.md) for the phased implementation plan.

## Architecture

```
Decky plugin (Gaming Mode)
  frontend/  React + @decky/ui, xterm.js terminal, settings routes      → src/
  backend/   Python PTY sessions, managed CLI setup, self-update         → main.py

deck-assistant-core   risk classifier · staged actions · diagnostics
                      · knowledge · CLI adapters · agent-pack installer   → packages/core/
deck-assistant-mcp    static tool catalog · dispatcher · stdio server     → packages/mcp-server/
agent-pack            portable skills · role subagents · commands
                      · tool policy · Codex/Claude adapter templates      → agent-pack/
```

The Deck runs everything: PTY sessions, local diagnostics, knowledge indexes, and action approvals. Model access stays inside the user's official CLIs. MCP is the shared tool bridge the CLIs connect to.

More detail:

- [Architecture](docs/architecture.md)
- [Interfaces & contracts](docs/interfaces.md)
- [Operations (build, test, release)](docs/operations.md)
- [Repository guide](docs/index.md) · [Repository map](docs/repo-map.md)
- [Agent instructions (canonical)](AGENTS.md)

## Build from source

Requires Node.js 20+ and `pnpm` 9.

```bash
# Frontend type-check and build
npm exec --yes pnpm@9 -- install
npm exec --yes pnpm@9 -- run check
npm exec --yes pnpm@9 -- run build

# Build the installable Decky ZIP (out/decky-ai-assistant-v<version>.zip)
npm exec --yes pnpm@9 -- run package
```

Python test suites (no third-party deps required):

```bash
PYTHONPATH=packages/core/src python3 -m unittest discover -s packages/core/tests
PYTHONPATH=packages/core/src:packages/mcp-server/src python3 -m unittest discover -s packages/mcp-server/tests
python3 -m unittest discover -s tests
python3 agent-pack/scripts/validate_agent_pack.py
```

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) and the canonical [AGENTS.md](AGENTS.md) before starting. In short: keep each change to one coherent slice, keep the Decky frontend thin and safety logic in the core/MCP packages, add tests around contracts and risk boundaries, and update docs when contracts, commands, or risk behavior change. Releases follow the dev/stable policy in [RELEASING.md](RELEASING.md).

## License

[MIT](LICENSE) © nmc
