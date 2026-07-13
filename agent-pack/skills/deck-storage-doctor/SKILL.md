---
name: deck-storage-doctor
description: Diagnose and, when requested, clean Steam Deck low-storage issues through Decky AI Assistant storage reports, cited knowledge search, concise fix plans, and CLI-owned execution.
---

# Deck Storage Doctor

## Workflow

1. Clarify the scope: whole Deck, current game, Steam app ID, shadercache, compatdata, logs, screenshots, or videos.
2. Use `get_storage_report`, then `search_knowledge` for cited Steam Deck, Steam, Proton, Decky, or launcher guidance.
3. Use `propose_fix` after evidence is collected when a plan helps.
4. Rank findings by reclaimable size, confidence, and data-loss risk.
5. If cleanup is requested, classify risk, show exact scope, and execute through the active CLI's normal shell/tooling.

## Evidence Rules

- Redact tokens, auth paths, shell history, unrelated home-directory details, and credential-like strings.
- Avoid unbounded scans, background work, and full private path dumps unless explicitly requested.

## Storage Domains

| Domain | Guidance |
| --- | --- |
| Shadercache | Rebuildable cache, but warn about redownloads, shader compilation stutter, and active-game/download timing. |
| Compatdata | Can contain Proton prefixes, saves, configs, launchers, and account data; require an app identity or explicit user target. |
| Logs | Preserve recent logs when diagnosing a current problem. |
| Screenshots/videos | Treat as user-created media; prefer user-selected deletion. |

## Boundaries

- Never read, export, log, or summarize AI CLI auth tokens or provider credential stores.
- Risk labels are informational metadata; command approval belongs to the active CLI.

## Output Shape

Return a concise report with:

- `goal` and `scope`
- `evidence_gathered`
- `storage_summary`
- `cleanup_candidates`
- `recommended_next_step`
- `proposed_fix_risk`
- `actions_taken`, when cleanup was requested and executed
- `handoff`, when a handoff is useful
