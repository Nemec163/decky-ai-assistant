# diagnose-runtime

Purpose: diagnose a deployed Decky AI Assistant or Steam Deck issue without writes.

Use roles: `deck-planner`, `deck-diagnostician`

Steps:

1. Restate the user-visible symptom.
2. Use read-only knowledge and diagnostics tools.
3. Summarize evidence with citations or local source labels.
4. If a write is needed, stop and hand off to `stage-safe-action` with goal, evidence, proposed outcome, blocked condition, and allowed next role.

Do not execute cleanup, repair, install, permission, or config changes.
