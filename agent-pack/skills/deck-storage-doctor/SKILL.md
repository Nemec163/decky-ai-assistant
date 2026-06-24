---
name: deck-storage-doctor
description: Diagnose Steam Deck low-storage and cleanup questions through Decky AI Assistant read-only MCP storage reports, cited knowledge search, and approval-only staged planning. Use for shadercache, compatdata, logs, screenshots, videos, per-game storage, reclaimable-space triage, and "what can I safely clean" workflows; do not use to execute cleanup.
---

# Deck Storage Doctor

## Workflow

1. Clarify the scope: whole Deck, current game, a named Steam app ID, shadercache, compatdata, logs, screenshots, or videos.
2. Use read-only MCP evidence first. Start with `get_storage_report`, then use `search_knowledge` for cited Steam Deck, Steam, Proton, Decky, or launcher guidance relevant to the reported categories.
3. Use `propose_fix` only after evidence is collected. Treat its output as a read-only plan and risk classification, not approval and not execution.
4. Rank findings by reclaimable size, confidence, and data-loss risk. Prefer small, high-confidence recommendations over broad cleanup.
5. If cleanup is requested, hand off to `deck-safe-action-review` for staged action planning. Do not execute, auto-clean, or call `run_approved_action` from this skill.
6. End every cleanup proposal with an explicit `no_action_taken` note unless a separate staged action record has been created by an allowed staging role.

## Evidence Rules

- `get_storage_report` should cover shadercache, compatdata, logs, screenshots, and videos for the requested scope.
- `search_knowledge` should cite source IDs, revisions, and concise passages or summaries for claims about safe cleanup behavior.
- `propose_fix` should receive the gathered evidence and return a plan with risk, expected effect, approval requirements, and blocked conditions.
- Keep results small enough for Gaming Mode. Avoid unbounded scans, background work, and full private path dumps.
- Redact tokens, auth paths, shell history, unrelated home-directory details, and any credential-like strings.
- If the storage report is unavailable, stop with a blocked condition instead of falling back to ad hoc shell commands.

## Storage Domains

| Domain | Guidance |
| --- | --- |
| Shadercache | Treat as rebuildable cache, but warn about redownloads, shader compilation stutter, and active-game/download timing. Recommend app-specific review before any cleanup. |
| Compatdata | Treat as high-risk user/application state. It can contain Proton prefixes, saves, configs, launchers, and account data. Do not call it orphaned from size alone; require an app identity or explicit user target. |
| Logs | Preserve recent logs when diagnosing a current problem. Cleanup is usually low value unless logs are unusually large. |
| Screenshots/videos | Treat as user-created media. Prefer review, export, or user-selected deletion; never bulk-delete by default. |

## Cleanup Boundaries

- Never use `sudo`, `rm`, package managers, permission changes, readonly partition changes, or system-level commands.
- Never run cleanup automatically, even for cache-like directories.
- Never mutate Steam, Proton, game, launcher, Decky, Flatpak, or plugin state directly from this skill.
- Deleting files is destructive and must go through the staged action and Decky approval flow with exact scope, backup or rollback notes, and user-visible risk.
- If runtime execution is not implemented or staging is unavailable, provide a read-only report and a blocked cleanup handoff instead of inventing commands.

## Output Shape

Return a concise report with:

- `goal` and `scope`
- `evidence_gathered` with tool names and citations
- `storage_summary` by shadercache, compatdata, logs, screenshots, and videos
- `cleanup_candidates` with size, confidence, reason, data-loss risk, and whether user review is required
- `recommended_next_step`
- `proposed_fix_risk` from `propose_fix`
- `no_action_taken`
- `handoff`, when cleanup is requested, including allowed next role, exact candidate scope, backup or rollback note, and blocked condition

When the user only asks what is using space, stop after the read-only report. When the user asks to clean space, produce a staged-action handoff and wait for Decky approval flow; do not proceed to execution.
