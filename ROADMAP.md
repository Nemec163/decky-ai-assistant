# Implementation Roadmap

This roadmap is written for AI agents and human maintainers. Work phase-by-phase. Do not skip safety, source attribution, or resource-budget gates to ship UI faster.

## 0. Product Definition

### Goal

Create a Decky plugin that gives Steam Deck users a local AI cockpit:

- terminal access to existing AI CLIs in Gaming Mode;
- assistant workflows specialized for Steam Deck troubleshooting and setup;
- manageable knowledge packs from official docs, community repositories, and user-added sources;
- explicit approval before local actions.

### Open-Source Distribution

- Default path: public, free, open source, BYO official CLI account.
- Infrastructure: GitHub repository, GitHub Actions, GitHub Releases, static registry.
- Do not proxy, resell, or abstract away Codex, Claude, or other model access.

### Primary Users

| User | Need |
| --- | --- |
| Steam Deck power user | Run AI CLIs and terminal commands without leaving Gaming Mode. |
| Non-Linux Deck user | Ask natural-language questions and approve safe fixes. |
| Open-source contributor | Add skills, knowledge packs, CLI adapters, or workflows. |
| Advanced tinkerer | Connect custom agents, MCP servers, and private documentation. |

## 1. Current Best-Practice Baseline

Use these facts as design constraints unless later verified sources supersede them.

### Decky

- Decky plugins are React/TypeScript frontend plus Python backend.
- Decky supports Python functions called from TypeScript and two-way plugin communication.
- Decky plugin metadata can request `root`, but root should only be used when actually required.
- The plugin template and Deckbrew docs are the first source for structure and packaging.

### Terminal Layer

- Use `xterm.js` for terminal rendering.
- Use a real PTY for interactive CLIs; plain `subprocess.run()` is insufficient for TUI, login prompts, resize, Ctrl+C, and streaming.
- Keep the terminal transport isolated behind a session API so the frontend does not know provider-specific details.

### AI CLI Layer

| CLI | Default auth posture | Native extension posture |
| --- | --- | --- |
| Codex CLI | ChatGPT account, API key, or access token; device auth supported. | Skills, plugins, custom agents, MCP, hooks, subagents. |
| Claude Code | Claude.ai Pro/Max/Team/Enterprise or API/cloud providers. | Skills, plugins, subagents, hooks, MCP, marketplaces. |
| Hermes Agent | Provider routing, memory, skills, MCP, messaging gateways. | Useful reference for learning loop and channel architecture. |
| OpenClaw | Local personal assistant with gateway/control-plane framing. | Useful reference for multi-channel assistant UX and onboarding. |

Reference projects:

| Project | Why it matters |
| --- | --- |
| OpenCode | Reference for terminal-first agent UX, primary-agent/subagent separation, custom commands, MCP, LSP diagnostics, and privacy posture. It is not an MVP provider target. |
| OpenClaw | Reference for local personal assistant UX, onboarding, and gateway/control-plane framing. |
| Hermes Agent | Reference for skills, memory, MCP, voice, provider routing, and deploy-anywhere patterns. |

### Extension Decision Rule

| Need | Use |
| --- | --- |
| Reusable procedural workflow | Agent Skill |
| Live tools, local diagnostics, source search, Deck actions | MCP server |
| Distribution bundle | Plugin/extension for each supported CLI |
| Isolated role with different permissions/model/context | Custom agent/subagent |
| Repeatable deterministic shortcut | Slash command/custom command |
| Always-on guard around actions | Hook, but only where the target CLI supports it safely |
| Repo-specific durable instruction | `AGENTS.md`, `CLAUDE.md`, or target-native equivalent |

## 2. Target Architecture

```text
Decky Plugin
  frontend/
    React + @decky/ui
    Terminal view using xterm.js
    Assistant, Knowledge, Actions, Settings panels

  backend/
    Python Decky backend
    PTY/session manager
    CLI adapter supervisor
    Local action runner
    Settings and audit log

deck-assistant-core
  CLI adapter contracts
  Risk classifier
  Knowledge source manager
  Knowledge pack index reader/writer
  Source citation model

deck-assistant-mcp
  search_knowledge
  list_sources
  inspect_current_game
  read_proton_logs
  get_storage_report
  propose_fix
  run_approved_action

agent-pack/
  skills/
  agents/
  commands/
  workflows/
  plugin manifests for Codex and Claude where supported

pack-registry/
  static registry JSON
  public knowledge pack metadata
  signed/hash-checked release artifacts
```

## 3. Implementation Phases

### Phase 1: Repository And Research Foundation

Deliverables:

- Project docs and roadmap.
- Source matrix for Decky, Codex, Claude, plus reference notes for OpenCode, OpenClaw, and Hermes.
- Initial threat model and resource budget.
- Chosen license and contribution rules.

Agent tasks:

1. Verify Decky template structure and current store/backend packaging rules.
2. Verify current CLI auth commands and non-interactive flags for `codex` and `claude`.
3. Verify MCP config paths and plugin/extension packaging for each target CLI.
4. Document known gaps as `Needs verification`, not assumptions.

Acceptance criteria:

- Docs explain why default mode uses existing CLI auth instead of API keys.
- Docs define what runs on Deck and what may run outside Deck.
- Docs define risk levels before any action runner code exists.

### Phase 2: Decky Terminal MVP

Deliverables:

- Decky plugin scaffold.
- xterm.js terminal panel.
- Python PTY backend.
- Session lifecycle: start, write, resize, stop, restart.
- CLI profiles: `bash`, `codex`, `claude`, `custom`.

Agent tasks:

1. Scaffold from official Decky plugin template.
2. Add frontend terminal component with fixed dimensions and Steam Deck-friendly controls.
3. Implement backend PTY session manager with per-session IDs.
4. Add command allowlist for known profiles and explicit custom-command warning.
5. Add smoke tests for PTY lifecycle where possible outside Deck.

Acceptance criteria:

- User can open plugin in Gaming Mode and run `bash`.
- User can launch installed AI CLI without the plugin reading credentials.
- Ctrl+C, resize, stop, and restart work.
- Plugin is idle when closed and does not poll aggressively.

Do not add:

- Local LLM.
- Hosted proxy.
- Voice.
- Auto-fixes.

### Phase 3: CLI Auth And Adapter Layer

Deliverables:

- CLI detection and health checks.
- Login guidance UI.
- Adapter contracts for command launch, status, login, and prompt injection.
- Device-code/link display where the CLI supports it.

Agent tasks:

1. Implement `detect_cli(name)` with path/version/status.
2. Implement `auth_status` using official commands only, such as `codex login status` where available.
3. Add login wizard that launches the official CLI login flow inside PTY.
4. Document provider-specific caveats without storing provider credentials.

Acceptance criteria:

- Missing CLI shows install guidance, not a failure trace.
- Logged-out CLI offers official login flow.
- Logged-in CLI can be launched without re-auth.
- API key mode is optional and never the default.

### Phase 3.5: Terminal Input Ergonomics

Deliverables:

- User-started voice controls on terminal pages.
- Generic external transcription through a user-configured OpenAI-compatible API endpoint.
- Explicit opt-in CLI-native voice dispatch where documented and available.
- Settings for voice control visibility, external API URL/model/key, native preference, auto-insert behavior, and dictation language.

Agent tasks:

1. Keep voice as a terminal input path that writes to the existing PTY session API.
2. Keep external transcription opt-in and BYO-key; do not read CLI auth stores, proxy hosted model access, or enable a hosted default path.
3. Send only the user-recorded audio clip after a push-to-talk action, with a bounded size limit and configured language hint.
4. For generic dictation, insert recognized text without sending Enter so accidental transcripts do not execute shell commands.
5. Degrade to typed, pasted, and virtual-keyboard input when recording or transcription is unavailable.

Acceptance criteria:

- Bash, Codex, Claude, and custom profiles still work without speech support.
- Claude profiles can trigger native `/voice tap` from the terminal page when native voice is preferred.
- Non-Claude profiles can use the configured external transcription endpoint.
- Microphone capture starts only after a user action.
- No hosted transcription proxy, local Whisper dependency, background recording, CLI token access, or default provider API key is added.

### Phase 4: Core Knowledge Pack

Deliverables:

- Local `Core Deck Pack`.
- Knowledge pack schema.
- SQLite FTS5/BM25 indexer. Initial core persistence contract exists; source-update wiring and UI are still planned.
- Source attribution model.
- License metadata display.

Agent tasks:

1. Define `knowledge-pack.json` schema with source URL, license, revision, hash, created time, and file manifest.
2. Build chunking for Markdown/text docs with heading-aware citations.
3. Index initial core docs: Steam Deck basics, Decky, Proton, Flatpak, Heroic/Lutris/Bottles/EmuDeck paths.
4. Keep the embedded pack small; target fast lookup over exhaustive storage.

Acceptance criteria:

- `search_knowledge("shader cache")` returns cited chunks.
- UI shows source, license, revision, and enabled state.
- Pack update can be disabled.
- No model API is needed for local search.

### Phase 5: Knowledge Source Manager

Deliverables:

- Add source by GitHub repo or docs URL.
- Fetch, filter, chunk, index, enable/disable, remove.
- Local-only default for user-added sources.
- Static pack registry support.

Agent tasks:

1. Add source types: `github_repo`, `git_url`, `docs_url`, `local_folder`, `pack_registry`.
2. Implement file filters: include docs formats, exclude binaries, vendored code, giant files, lockfiles.
3. Add source size and time limits for Deck safety.
4. Add public pack download path from GitHub Releases/static registry.

Acceptance criteria:

- User can add `https://github.com/mikeroyal/Steam-Deck-Guide`.
- Indexing runs only on request and shows progress.
- Large repos stop with a useful explanation and recommended hosted/off-device path.
- Search results include source citations and license metadata.

### Phase 6: Local MCP Server

Deliverables:

- `deck-assistant-mcp` server.
- Tools for knowledge, diagnostics, and approved actions.
- MCP instructions with first 512 characters self-contained.
- Config snippets for Codex and Claude.

Initial tools:

| Tool | Risk | Purpose |
| --- | --- | --- |
| `search_knowledge` | read_only | Search enabled packs. |
| `list_sources` | read_only | Show enabled/disabled sources and licenses. |
| `inspect_current_game` | read_only | Detect current/selected Steam app context where available. |
| `read_proton_logs` | read_only | Locate and summarize Proton logs. |
| `get_storage_report` | read_only | Show shader cache, compatdata, logs, screenshots/videos. |
| `propose_fix` | read_only | Convert diagnosis into a plan and risk classification. |
| `stage_action` | low_write | Prepare action for UI approval, no execution. |
| `run_approved_action` | variable | Execute only actions approved in Decky UI. |

Acceptance criteria:

- Codex and Claude can connect to the MCP server using target-native config.
- Tools expose stable JSON contracts.
- Write tools cannot run without a Decky-side approval token.
- Tool results are small, structured, and citation-aware.

### Phase 7: Assistant Mode

Deliverables:

- Ask panel.
- Current game context panel.
- Diagnosis workflows.
- Plan and approval UI.

Core workflows:

1. Current Game Doctor.
2. Storage Doctor.
3. Decky Doctor.
4. Flatpak/Launcher Doctor.
5. System Report.

Agent tasks:

1. Implement read-only diagnostics first.
2. Add workflow prompts as Agent Skills, not hardcoded giant prompts.
3. Route live data through MCP tools.
4. Require approval for any local write.

Acceptance criteria:

- User can ask "why does this game not launch?" and receive cited local findings.
- User can produce a system report without exposing tokens.
- User sees exact commands/diffs before applying a fix.

### Phase 8: Agent Pack

Deliverables:

- Portable Agent Skills.
- Target-native packaging for Codex and Claude where practical.
- Custom agents/subagents for role separation.
- Workflow commands.

Skills to create:

| Skill | Trigger | Purpose |
| --- | --- | --- |
| `deck-diagnose-game` | Game launch/performance issues | Inspect app context, Proton logs, compatibility notes. |
| `deck-storage-doctor` | Low storage/cache cleanup | Find safe cleanup candidates. |
| `deck-flatpak-doctor` | Heroic/Lutris/Bottles/permissions | Diagnose launcher/runtime issues. |
| `deck-knowledge-curator` | Add/update sources | Validate licenses, chunking, citations. |
| `deck-safe-action-review` | Before local writes | Review risk, rollback, approval text. |
| `deck-report-builder` | Share diagnostics | Build sanitized support bundle. |

Custom agents:

| Agent | Default tools | Purpose |
| --- | --- | --- |
| `deck-planner` | read-only MCP, knowledge | Turn user request into a plan. |
| `deck-diagnostician` | read-only local tools | Inspect logs, storage, versions, configs. |
| `deck-safety-reviewer` | no write tools | Classify risk and require rollback plan. |
| `deck-executor` | approved action tool only | Execute approved local action. |
| `deck-knowledge-curator` | source manager tools | Add, update, and audit knowledge packs. |

Acceptance criteria:

- Skills are usable in at least Codex and Claude without rewriting.
- MCP config examples exist for Codex and Claude.
- CLI-specific packaging is additive; core skill instructions stay portable.

### Phase 9: Safe Action Runner

Deliverables:

- Declarative action schema.
- Dry-run renderer.
- Backup and rollback support.
- Approval token flow.
- Audit log.

Action schema fields:

```json
{
  "id": "uuid",
  "title": "Human-readable action",
  "risk": "read_only|low_write|high_write|danger",
  "commands": [],
  "file_edits": [],
  "backups": [],
  "rollback": [],
  "requires_sudo": false,
  "approved_by_user_at": null
}
```

Acceptance criteria:

- MCP cannot execute unstaged actions.
- Decky UI approval is required for every write.
- File edits create backups before mutation.
- Dangerous actions require separate confirmation and are disabled by default.

### Phase 10: Public Pack Registry

Deliverables:

- Static registry file.
- GitHub Action to rebuild public packs.
- Release artifact hash verification.
- Pack signing plan or at minimum SHA-256 pinning.

Initial public packs:

- Core Deck Pack.
- Steam-Deck-Guide community pack.
- Decky docs pack.
- Proton docs pack.
- Heroic/Lutris/Bottles/EmuDeck docs pack.

Acceptance criteria:

- Deck downloads prebuilt packs without cloning large repos.
- Registry update is static and cheap to host.
- Pack metadata includes source license and revision.
- User can disable all remote registry checks.

### Phase 11: Voice Input Optional Layer

Deliverables:

- Push-to-talk UI.
- Provider strategy.
- Local/off-device tradeoff setting.

Default:

- Do not ship local Whisper as default because it can load CPU, RAM, and battery.
- Prefer user-selected external transcription or existing OS/mobile input.
- Keep any external transcription endpoint disabled until the user supplies configuration.

Acceptance criteria:

- Voice is optional.
- Text input remains complete.
- No always-listening behavior.

### Phase 12: Optional Off-Deck Indexing Experiments

Only after the local open-source path is stable.

Possible features:

- Self-hostable large-repo indexing.
- User-controlled private source sync.
- Cross-device knowledge pack sync.
- Team policy packs.
- Self-hostable remote MCP endpoint.

Hard requirements:

- Explicit consent before uploading private sources.
- Clear resource limits and data retention controls.
- Local-only mode remains first-class.
- No hosted command execution on user Deck.

## 4. Testing Strategy

| Layer | Checks |
| --- | --- |
| PTY | start/write/read/resize/interrupt/stop; TUI smoke tests. |
| CLI adapters | installed/missing/logged-in/logged-out/custom command. |
| Knowledge | chunking, dedupe, FTS results, citations, license metadata. |
| MCP | schema validation, tool timeouts, approval enforcement. |
| Action runner | dry-run, backup, rollback, risk classification, audit log. |
| Decky UI | Steam Deck viewport, controller navigation, no text overflow. |
| Resource | idle CPU, memory, disk growth, indexing limits. |

## 5. Security And Privacy Gates

Before public alpha:

- Threat model checked into docs.
- No token paths logged.
- Audit log redacts secrets.
- User-added sources are local-only by default.
- No telemetry unless opt-in.
- No cloud sync enabled by default.
- Write actions impossible through MCP without Decky approval token.

Before plugin store submission:

- Decky root flag absent unless a specific feature requires it.
- Store/package rules verified against current Decky docs.
- Dependencies and bundled binaries reviewed.
- Large binary downloads avoided or hash-pinned.

## 6. Open Questions

- Best current Decky transport for high-volume streaming: direct backend calls, websocket, or local loopback service.
- Whether Codex and Claude can consume one shared Agent Skills location cleanly on SteamOS.
- Which Steam client APIs or files can reliably expose current game context in Gaming Mode.
- Whether pack signing should use Sigstore, minisign, or SHA-256-only for MVP.
- Which reference practices from OpenCode, OpenClaw, and Hermes are worth adopting without turning them into provider targets.

## 7. Source Notes

Validated source families used for this roadmap:

- Decky: Deckbrew plugin docs, Decky Loader, Decky plugin template.
- Terminal: xterm.js and Python PTY documentation.
- Codex: current Codex manual, Codex CLI auth, skills, plugins, MCP, subagents.
- Claude Code: official skills, plugins, plugin marketplaces, MCP, and feature overview docs.
- OpenCode: official docs and GitHub README used as reference material for agents, MCP, commands, LSP, and privacy posture.
- OpenClaw: official site/GitHub for local assistant, onboarding, gateway framing.
- Hermes Agent: official docs for provider routing, skills, memory, MCP, voice, and deployment patterns.
