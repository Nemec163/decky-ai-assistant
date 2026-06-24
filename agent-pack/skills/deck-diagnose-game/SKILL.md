---
name: deck-diagnose-game
description: Diagnose Steam Deck game launch, crash, Proton, compatibility, and performance issues through Decky AI Assistant read-only MCP tools and cited knowledge. Use for current game doctor, named Steam app ID, Proton logs, launch failures, crashes, controller/display/performance symptoms, and "why will this game not run" workflows; do not use to edit game configs or execute fixes.
---

# Deck Diagnose Game

## Workflow

1. Define the scope: current game, named title, Steam app ID, non-Steam shortcut, launcher entry, symptom, and approximate time of failure.
2. Use read-only MCP evidence first. Start with `inspect_current_game`; use `read_proton_logs` for launch, crash, Proton, or compatibility symptoms; use `get_storage_report` only when storage, shadercache, or compatdata size may affect the issue.
3. Use `search_knowledge` for cited Steam Deck, Proton, Decky, launcher, and game-compatibility guidance. Keep citations small and include source IDs, revisions, headings, or local log labels.
4. Separate evidence from hypotheses. If an MCP tool is unavailable, record a blocked condition instead of falling back to ad hoc shell commands.
5. Rank likely causes by evidence strength, user impact, reversibility, and whether the issue is game-specific, Proton-specific, launcher-specific, or system-wide.
6. If a fix is needed, use `propose_fix` only when the active role/tool policy allows planning tools. Otherwise hand off evidence to `deck-planner` or `deck-safety-reviewer`.
7. End with `no_action_taken` unless a separate allowed staging role creates a pending action. This skill never calls `stage_action` or `run_approved_action`.

## Evidence Rules

- `inspect_current_game` should identify the selected/current game, app ID when available, launch context, and relevant runtime hints without reading credentials.
- `read_proton_logs` should summarize bounded, relevant log sections. Prefer recent launch/crash windows over full logs.
- `get_storage_report` is supporting evidence for shadercache, compatdata, logs, screenshots, or videos; do not turn a game diagnosis into broad cleanup.
- `search_knowledge` should cite stable source metadata for compatibility guidance, Proton behavior, launcher behavior, or safe troubleshooting steps.
- Redact tokens, account identifiers, shell history, unrelated home-directory details, and credential-like strings.
- Keep output short enough for Steam Deck Gaming Mode. Avoid unbounded scans, background work, and full private path dumps.

## Diagnostic Domains

| Domain | Guidance |
| --- | --- |
| Launch failure | Check app identity, Proton log status, missing runtime hints, launcher handoff failures, and recent config changes reported by the user. |
| Crash or freeze | Focus on the latest bounded log window, Proton/runtime errors, known compatibility notes, and whether the failure is reproducible. |
| Proton compatibility | Compare requested Proton version, game context, and cited compatibility guidance. Do not change Proton version or launch options from this skill. |
| Performance | Look for storage pressure, shadercache context, known game-specific notes, display mode hints, and recent update timing before suggesting tweaks. |
| Controller or display | Prefer cited Steam Input/display guidance and current game context. Do not edit controller layouts, resolution files, or launch options directly. |
| Launcher or non-Steam game | Identify whether Heroic, Lutris, Bottles, Flatpak, or a shortcut wrapper is involved; hand off launcher-specific issues rather than changing permissions. |

## Action Boundaries

- Never edit launch options, Proton prefixes, game configs, saves, controller layouts, Flatpak permissions, Decky settings, or plugin state.
- Never run cleanup, repair, install, permission, package-manager, `sudo`, `rm`, readonly partition, or system-level commands.
- Never read, export, log, or summarize AI CLI auth tokens or provider credential stores.
- Never call `stage_action` from a diagnosis role. Writes must go through the `deck-safety-reviewer` role using the `$deck-safe-action-review` skill and Decky approval.
- If runtime MCP tools are missing, return a blocked read-only report and the exact missing capability instead of inventing shell commands.

## Output Shape

Return a concise report with:

- `goal` and `scope`
- `evidence_gathered` with tool names, source citations, and local log labels
- `findings` separated from `hypotheses`
- `likely_causes` with confidence and supporting evidence
- `safe_next_steps` limited to read-only checks or user-visible manual choices
- `proposed_fix_risk`, when planning output is available
- `no_action_taken`
- `handoff`, when a write may be needed, including allowed next role, evidence summary, exact candidate outcome, backup or rollback note if known, and blocked condition

When the user only asks what is wrong, stop after the read-only report. When the user asks to fix it, produce an evidence handoff for safety review and wait for the staged approval flow; do not proceed to execution.
