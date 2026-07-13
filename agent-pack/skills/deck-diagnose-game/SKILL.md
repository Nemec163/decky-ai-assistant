---
name: deck-diagnose-game
description: Diagnose and, when requested, fix Steam Deck game launch, crash, Proton, compatibility, and performance issues through Decky AI Assistant MCP tools and cited knowledge.
---

# Deck Diagnose Game

## Workflow

1. Define the scope: current game, named title, Steam app ID, non-Steam shortcut, launcher entry, symptom, and approximate time of failure.
2. Use MCP evidence first. Start with `inspect_current_game`; use `read_proton_logs` for launch, crash, Proton, or compatibility symptoms; use `get_storage_report` when storage, shadercache, or compatdata size may affect the issue.
3. Use `search_knowledge` for cited Steam Deck, Proton, Decky, launcher, and game-compatibility guidance.
4. Separate evidence from hypotheses. If an MCP tool is unavailable, state the missing capability and continue with the best CLI-owned path when the user asked for a fix.
5. Rank likely causes by evidence strength, user impact, reversibility, and whether the issue is game-specific, Proton-specific, launcher-specific, or system-wide.
6. If a fix is requested, classify risk, show the action, and execute through the active CLI's normal shell/tooling.

## Evidence Rules

- Redact tokens, account identifiers, shell history, unrelated home-directory details, and credential-like strings.
- Keep output short enough for Steam Deck Gaming Mode.
- Avoid unbounded scans and background work unless the user explicitly requested them.

## Diagnostic Domains

| Domain | Guidance |
| --- | --- |
| Launch failure | Check app identity, Proton log status, missing runtime hints, launcher handoff failures, and recent user-reported config changes. |
| Crash or freeze | Focus on the latest bounded log window, Proton/runtime errors, known compatibility notes, and reproducibility. |
| Proton compatibility | Compare requested Proton version, game context, and cited compatibility guidance. |
| Performance | Look for storage pressure, shadercache context, game-specific notes, display mode hints, and recent update timing. |
| Controller or display | Prefer cited Steam Input/display guidance and current game context. |
| Launcher or non-Steam game | Identify whether Heroic, Lutris, Bottles, Flatpak, or a shortcut wrapper is involved. |

## Boundaries

- Never read, export, log, or summarize AI CLI auth tokens or provider credential stores.
- Risk labels are informational metadata; command approval belongs to the active CLI.

## Output Shape

Return a concise report with:

- `goal` and `scope`
- `evidence_gathered`
- `findings`
- `likely_causes`
- `proposed_fix_risk`, when planning output is available
- `actions_taken`, when a fix was requested and executed
- `handoff`, when a handoff is useful
