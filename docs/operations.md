# Operations

## Local Setup

| Step | Command / File | Notes |
| --- | --- | --- |
| Open repo | `cd /Users/nmc/Documents/WORK-NMC/GitHub/decky-ai-assistant` | Repository root. |
| Check state | `git status --short` | Shows pending changes. |
| Read canonical agent rules | [AGENTS.md](../AGENTS.md) | Required for AI-agent implementation work. |
| Read contributing workflow | [CONTRIBUTING.md](../CONTRIBUTING.md) | Required before changing workflow, review rules, or release rules. |
| Read roadmap | [ROADMAP.md](../ROADMAP.md) | Required before implementation. |
| Read agent pack registry | [agent-pack/manifest.json](../agent-pack/manifest.json) | Required before changing skills, roles, commands, adapters, or tool policy. |

## Environment

| Variable | Required | Purpose | Source |
| --- | --- | --- | --- |
| `PYTHONPATH` | Core and MCP tests only | Use `packages/core/src` for core tests and `packages/core/src:packages/mcp-server/src` for MCP tests when running without installing packages. | [packages/core/tests](../packages/core/tests), [packages/mcp-server/tests](../packages/mcp-server/tests) |

Future constraints:

- Do not require provider API keys for default mode.
- Do not store AI CLI tokens in project env files.
- Use `.env.example` only for non-secret local development placeholders.

## Verification

| Check | Command | Notes |
| --- | --- | --- |
| Repo docs validation | `python3 /Users/nmc/.codex/skills/repo-docs/scripts/validate_repo_docs.py /Users/nmc/Documents/WORK-NMC/GitHub/decky-ai-assistant` | Validates required docs shape. |
| Agent pack validation | `python3 agent-pack/scripts/validate_agent_pack.py` | Validates skills, roles, commands, adapter manifests, MCP templates, and tool policy. |
| Agent skill validation | `python3 /Users/nmc/.codex/skills/.system/skill-creator/scripts/quick_validate.py agent-pack/skills/<skill-name>` | Run for changed skills. |
| Core unit tests | `PYTHONPATH=packages/core/src python3 -m unittest discover -s packages/core/tests` | Validates PTY session lifecycle, PTY child env sanitization, custom profile injection, risk classification, CLI profile detection, knowledge contracts/source registry/inventory/local-folder manifest building, SQLite FTS5/BM25 persistence, and diagnostics report/reader contracts. |
| MCP unit tests | `PYTHONPATH=packages/core/src:packages/mcp-server/src python3 -m unittest discover -s packages/mcp-server/tests` | Validates MCP contract catalog, risk metadata, injected read-only dispatcher handlers/readers, in-process dispatcher shell behavior, and the JSON-RPC 2.0 stdio MCP server (`initialize`, `tools/list`, `tools/call`). |
| MCP server smoke | `printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \| PYTHONPATH=packages/core/src:packages/mcp-server/src python3 -m deck_assistant_mcp serve` | Confirms the stdio server starts and lists the Deck tool catalog. |
| Decky dependency install | `npm exec --yes pnpm@9 -- install` | Uses the `pnpm` v9 line recommended by the official Decky plugin template. |
| Decky typecheck | `npm exec --yes pnpm@9 -- run check` | Runs `tsc --noEmit` for the Decky frontend. |
| Decky build | `npm exec --yes pnpm@9 -- run build` | Produces local ignored `dist` bundle. |
| Decky package ZIP | `npm exec --yes pnpm@9 -- run package` | Runs typecheck/build and creates install-by-URL ZIP under ignored `out`. |
| Deck smoke deploy over SSH | `scripts/deploy_decky_smoke.sh deck@steamdeck.local` | Dev-only loop; requires an SSH-reachable Deck and a prior build. |

## Build And Release

Releases ship on two channels — **stable** (`stable` branch, tags `vX.Y.Z`, GitHub "Latest") and **dev** (`main` branch, tags `vX.Y.Z-dev.N`, GitHub "Pre-release"). The full policy, version scheme, and promotion flow live in [RELEASING.md](../RELEASING.md). Never publish a dev build to the stable channel or mark a `-dev` tag as latest.

| Task | Command / File | Notes |
| --- | --- | --- |
| Decky plugin build | `npm exec --yes pnpm@9 -- run build` | Follows the current official Decky plugin template root layout. |
| Decky package | `npm exec --yes pnpm@9 -- run package` | Creates `out/decky-ai-assistant-v<version>.zip` (`<version>` is read from `package.json`, so it tracks the current release automatically) with a top-level `decky-ai-assistant` directory containing the frontend bundle, metadata, license, Python backend, bundled Python source packages, `agent-pack`, docs, and host instruction files. |
| Cut a release | Push a tag matching `package.json` version | `.github/workflows/release.yml` triggers on `v*` tags: it type-checks, packages the ZIP, verifies the tag matches `package.json`, and publishes a GitHub Release via `gh` — `--prerelease` for tags containing `-` (dev), `--latest` for clean `vX.Y.Z` tags (stable). |
| Release channels | [RELEASING.md](../RELEASING.md) | dev on `main` (`vX.Y.Z-dev.N`), stable on the `stable` branch (`vX.Y.Z`); the in-plugin self-update filters releases by the channel chosen in Settings (default stable). |
| Knowledge pack build | Unknown | Planned GitHub Action/static artifact flow. |
| Agent pack release | Bundled in Decky package; public release artifacts planned | The Decky ZIP includes `agent-pack` so Settings can install user-local Codex and Claude native assistant assets after a user request. Public marketplace/release distribution remains separate work. |
| Plugin release artifact | GitHub Release asset `decky-ai-assistant-v<version>.zip` | Install by URL from the release asset; never use GitHub's `Source code (zip)` because it lacks the built frontend bundle. |

## Runtime / Deployment

- Runtime target is Steam Deck Gaming Mode through Decky Loader.
- Preferred install path is a Decky-compatible ZIP hosted at an HTTPS URL.
- SSH deployment copies built files to `~/homebrew/plugins/decky-ai-assistant` and is only a developer loop.
- Local development may need a Steam Deck or Decky-compatible dev setup.
- Terminal sessions may remain running in the backend when the plugin panel or terminal route is closed; users close sessions explicitly from the terminal page.
- Hosted infrastructure is not required for MVP.

## Smoke Testing

Current scope:

- Decky frontend loads in Quick Access.
- Python backend responds to `ping`.
- Shared core and MCP Python modules import on the Deck.
- CLI profile contracts render without launching any CLI.
- Built-in Terminal Mode profiles launch through the Python PTY manager when their executables can be resolved from `PATH`, Decky runtime path hints, or the managed npm bin directory.
- Built-in Codex and Claude setup actions can install/update the latest npm package into `~/.local/share/decky-ai-assistant/npm`, bootstrap user-local Node.js 22 when npm is absent, and open or resume the official auth flow in a transient terminal session after the user requests the action.
- Built-in Codex and Claude settings can show a `low_write` native assistant pack install plan and write the bundled adapter assets into user-local CLI extension directories after the user requests the action. Codex pack installation writes the user-local plugin, a `./`-relative marketplace entry, global runtime skills, plugin MCP metadata, and a stable `~/.local/share/decky-ai-assistant/workspaces/codex` launch directory whose managed `AGENTS.md` frames the session as the Steam Deck assistant and whose managed `.codex/config.toml` registers the local `deck-assistant` MCP server. Claude pack installation writes direct user-level runtime skills, user-level agents, user-level commands, a self-contained plugin bundle under `~/.claude/plugins/decky-ai-assistant`, and a stable `~/.local/share/decky-ai-assistant/workspaces/claude` launch directory whose managed `CLAUDE.md` frames the session as the Steam Deck assistant and whose managed `.mcp.json`/`settings.local.json` register and pre-enable the local `deck-assistant` MCP server so supported CLIs start as Deck assistants with diagnostics and planning tools wired in and project trust persisted outside the home directory.
- Every profile settings view shows a permission-bypass toggle. Built-in Codex and Claude profiles launch with their CLI-native no-approval flags when enabled; custom profiles are trusted as configured. The setting is disabled by default and reported as `danger`.
- The plugin panel shows launchable profiles only; missing built-in CLIs are configured from Settings instead of appearing as broken launch buttons.
- PTY child processes and read-only CLI probes strip Decky/Steam dynamic library overrides such as `LD_LIBRARY_PATH` before launching shells or CLIs.
- Custom profiles can be added to Decky settings as structured argv; launch risk is reported for display only.
- Terminal input goes through xterm directly. The visually hidden Decky TextField is only a Steam virtual-keyboard trigger and text bridge, not the command-entry surface.
- Terminal mode keeps the toolbar, auth-link, paste fallback, voice, and extra-key controls visible for touch while Decky controller focus stays on xterm; the top help button opens terminal shortcuts in a modal instead of using Steam's expanded action footer.
- HTTP(S) auth links printed by CLI login flows appear above the terminal with Open, Copy, and Hide actions. Only sign-in/auth links are surfaced: a link qualifies when the URL is auth-shaped (oauth/authorize/device/sso/openid, OAuth query params, or an `auth`/`login`/`accounts`/`sso`/`id` host) or when login wording (sign in, authenticate, verification/device code, "open this link in your browser", etc.) sits within ~320 characters of it; ordinary URLs (docs, repos) are ignored. The panel stays until the user presses Hide, the session restarts/stops, or auth-completion wording appears after the latest link. Browser codes are pasted through the terminal toolbar Paste button, the Y shortcut, or Ctrl+V / Shift+Insert (which the terminal intercepts so a raw Ctrl+V never reaches the CLI). Paste reads the clipboard through the backend, which reads the gamescope Xwayland selection directly via libX11 (`DISPLAY` :0/:1, `CLIPBOARD` then `PRIMARY`) — the focus-independent path that works in Gaming Mode, where there is no wl-paste/xclip/xsel and klipper is desktop only. Clipboard text is always delivered to the PTY as plain (bracketed) text; an empty clipboard surfaces a brief toast rather than an error. Copy writes the selection to the same Xwayland clipboard via `execCommand("copy")`. Links and bounded terminal replay text are kept in memory only. Stale helper links are suppressed after Hide, restart/stop, or recognized auth completion.
- PTY children and read-only CLI probes include both the managed npm `.bin` directory and any user-local bootstrapped Node.js `bin` directory in `PATH`; CLI `HOME` and XDG auth/config/cache directories are normalized to the user's home instead of a root-like Decky runtime home. Codex and Claude launch from their managed workspaces when those directories exist.
- Profile clicks in the plugin panel reuse a running profile session or start the selected CLI if none is alive, then navigate to a dedicated terminal route.
- Running terminal sessions appear in the plugin panel as resumable background terminals.
- Terminal settings persist font family, font size, DPad mode (`Arrow keys` or `Scroll`), extra keys, virtual-keyboard behavior, and auto-copy selection. Terminal capture is always enabled in terminal routes.
- Voice settings persist voice control visibility, external voice API URL/model/key status, and native-voice preference. Recognized dictation is always inserted automatically (without pressing Enter) and is not user-configurable.
- Terminal voice input is user-started from the terminal route with one microphone button (or the Deck voice shortcut) and uses the same one-button toggle for both modes: press once to start listening, press again to send/insert. External API transcription records a bounded audio clip only after the microphone button is pressed, sends it to the configured OpenAI-compatible endpoint over verified TLS for HTTPS URLs, and inserts recognized text without pressing Enter. Native CLI voice (Claude `Prefer Native Voice`) drives the CLI's own tap dictation: the first press lazily enables `/voice tap` once per session and sends the space keystroke that starts listening, and the next press sends the space keystroke that submits the dictation — no "mode enabled" toast and no re-sending `/voice tap` on every press. Restarting the session re-arms the one-time `/voice tap`.
- Storage path planning returns read-only planned paths without scanning files.

Build a URL-installable Decky package locally:

```bash
npm exec --yes pnpm@9 -- install
npm exec --yes pnpm@9 -- run package
```

The package script validates TypeScript, builds the Decky frontend, collects the Python backend, repo-local Python packages, `agent-pack`, docs, and host instruction files, creates a ZIP under `out`, and checks the archive.

Install by URL:

1. Upload `out/decky-ai-assistant-v<version>.zip` (the `<version>` matches `package.json`; the package script derives the file name) as a GitHub Release asset or another HTTPS file.
2. On the Steam Deck, use Decky's URL install flow with that ZIP URL.
3. Reload Decky if the plugin does not appear immediately.

Optional developer deploy to an SSH-reachable Deck:

```bash
scripts/deploy_decky_smoke.sh deck@steamdeck.local
```

The SSH helper copies the built Terminal Mode runtime into `~/homebrew/plugins/decky-ai-assistant`. It intentionally does not use `sudo`, `systemctl`, `rm`, or `rsync --delete`.

Manual Deck checklist:

1. Reload Decky on the Steam Deck.
2. Open Quick Access.
3. Open `Decky AI Assistant`.
4. In the plugin panel, press `Bash`.
5. Confirm a dedicated terminal page opens with a shell prompt or shell output.
6. Type `printf 'decky-ai-assistant\n'` directly into xterm using a physical keyboard or the keyboard button.
7. Confirm the printed line appears in the terminal.
8. In terminal mode with always-on terminal input capture, confirm DPad and face-button input stays on the terminal, toolbar buttons are not reachable by controller focus, and the top help button opens the shortcut list by touch.
9. Navigate back, open `Bash` again from the plugin panel, and confirm the same running Bash session is re-opened instead of creating a duplicate.
10. Open Settings, adjust a terminal setting such as `Extra Keys`, return to the terminal, and confirm the terminal route still works.
11. In Settings > Voice, confirm `Voice Input` and `Prefer Native Voice` persist after changing and reopening the page. Enable `External Voice API` and confirm the `Endpoint URL`, `Model`, and `API Key` fields appear as full-width stacked inputs and persist, and that they are hidden again when `External Voice API` is off. Confirm there is no `Auto-Insert Dictation` toggle, `Voice Language` field, or standalone `Voice API` status line (dictation always auto-inserts; transcription language is auto-detected).
12. In Settings > Voice, with `External Voice API` enabled, configure an OpenAI-compatible `/v1/audio/transcriptions` endpoint, set a transcription model, and paste the BYO API key when the endpoint requires one; confirm a `Clear key` button appears once a key is saved.
13. In a Bash, Codex, or Claude terminal with `Prefer Native Voice` disabled, press the microphone button, speak a short phrase, press the same microphone/stop button again, and confirm the transcribed text appears at the prompt without Enter being sent. If recording or transcription is unavailable, record the runtime message and continue.
14. In a Claude terminal, enable `Prefer Native Voice`, press the microphone button once and confirm Claude starts listening (no "voice mode enabled" toast and no repeated `/voice tap` lines), speak a short phrase, then press the microphone/stop button again and confirm the dictation is sent. Restart the session and confirm the next microphone press re-enables tap mode once before listening.
15. In Settings > Profiles, select a built-in profile such as `Codex CLI` or `Claude Code`, press `Check status`, and confirm it reports a friendly `Status` (`Ready`, `Needs sign-in`, `Installed`, or `Not installed`) without tracebacks. Confirm no raw `Type`, `Risk`, or `Path` rows are shown and that there is no `Add Profile` section.
16. For a managed built-in profile, confirm the `Setup` section shows an optional setup message plus `Install + sign in` and `Update` buttons, without raw npm-package, install-dir, bin-dir, or risk rows.
17. Confirm the `Assistant Pack` section shows a `Status` line and an `Install native pack` button, without raw install-dir, written-file-count, or risk rows.
18. Press `Install native pack` and confirm it completes without `sudo` or provider CLI execution, then automatically requests a Decky plugin reload.
19. After the reload, start or restart the target CLI and confirm it sees the Decky AI Assistant native plugin, skills, or extension metadata according to that CLI's normal extension loading behavior. For Codex, confirm the marketplace entry points at `~/.agents/plugins/decky-ai-assistant`, a new Codex terminal starts in `~/.local/share/decky-ai-assistant/workspaces/codex`, `AGENTS.md` sets the Steam Deck assistant identity, and `/mcp` or the in-session MCP status shows the `deck-assistant` server from `.codex/config.toml`. For Claude Code, confirm the user-level skills under `~/.claude/skills/`, subagents under `~/.claude/agents/`, and commands under `~/.claude/commands/` are visible; a new Claude terminal starts in `~/.local/share/decky-ai-assistant/workspaces/claude` after the pack install; and `claude mcp list` (or the in-session tool list) shows the `deck-assistant` server from the workspace `.mcp.json`.
20. Confirm the `Permissions` section shows the `Bypass permissions` toggle and a `danger` warning note describing the no-approval behavior.
21. Enable `Bypass permissions`, restart any existing session for that profile, launch the profile, and confirm the session argv includes the expected no-approval flags.
22. Press `Install + sign in`.
23. Confirm a dedicated terminal page opens and runs a user-local Node/npm setup under `~/.local/share/decky-ai-assistant/` without `sudo`.
24. If npm succeeds and the CLI prints an auth URL, confirm the terminal page shows an `Auth link` row.
25. Press the Open button and confirm Steam opens the external web auth page, or press Copy and confirm the URL is copied for manual browser use.
26. Follow the official CLI auth prompts in the browser, paste the returned browser code with the toolbar Paste button or Y shortcut, type it directly into xterm, or use the transient fallback input only if automatic paste fails, then press Enter in the terminal when needed.
27. Confirm the auth helper hides after successful auth, or press Hide and confirm it does not return when navigating away and back.
28. Return to the plugin panel and confirm the installed CLI now appears as a launchable profile.
29. On the Settings `Diagnostics` page, press `Run health check` and confirm it reports `Backend` `ready` and a `CLIs ready` count of the form `N / M` without tracebacks.
30. Press `Check for update` in the `Plugin Update` section and confirm it shows `Installed`, `Latest`, and `Status` without tracebacks.
31. If a newer release is available on a test Deck, press `Update plugin`, confirm Decky Loader opens its install/update prompt for the release ZIP, approve the prompt, and confirm the validated release ZIP installs and reloads through Decky Loader. If the Decky install API is unavailable and the backend fallback is used, confirm writable installs replace files and request reload, while root-owned or otherwise non-writable installs fail before partial replacement with a recovery message. If the plugin is already current, confirm the button reports `up_to_date` and does not write files.

Record the Decky Loader version, SteamOS version, and each failed step before changing implementation.

## Workflow

- Keep each change scoped to one coherent slice.
- Treat [AGENTS.md](../AGENTS.md) as canonical; host-specific instruction files must mirror it.
- Use [CONTRIBUTING.md](../CONTRIBUTING.md) for review rules and PR expectations.
- Use [.github/pull_request_template.md](../.github/pull_request_template.md) when opening pull requests.
- Use [agent-pack/manifest.json](../agent-pack/manifest.json) as the registry for AI agent skills, roles, commands, adapter templates, and conflict rules.
- Update docs in the same change when commands, contracts, directories, risk behavior, or workflow rules change.

## Debugging

- Start with logs from Decky backend and frontend console once implementation exists.
- Terminal issues should be isolated by profile: `bash` first, then provider CLI.
- Provider auth issues must be debugged through official CLI commands running in PTY setup/auth sessions, not token inspection.
- MCP issues should expose server startup, tool schema, timeout, and risk/action-state diagnostics.
- Agent pack issues should start with `python3 agent-pack/scripts/validate_agent_pack.py`, then inspect the referenced skill, role, command, adapter, or tool-policy file.

## Known Operational Risks

- Steam Deck CPU/RAM/battery constraints make local LLMs, Whisper, and heavy indexing poor defaults.
- External API and CLI-native speech recognition may be unavailable in some SteamOS, WebView, audio-device, account, organization, or network configurations; the terminal must still work through typed and pasted input.
- Decky terminal streaming may need a transport beyond simple request/response calls.
- User-added repositories can be too large for local indexing.
- CLI providers may change auth flows or config paths.
- CLI providers may change npm package names, Node.js requirements, release artifact URLs, or first-run auth prompts; managed setup should fail visibly in the terminal instead of falling back to system package managers.
- Dangerous commands must never be hidden behind vague natural-language text.
- Claude MCP config shape was verified on 2026-06-21; Codex MCP config and plugin MCP metadata paths were rechecked against official OpenAI Codex docs on 2026-06-23. Target-native release packaging must still be verified before publishing.
