# diagnose-runtime

Purpose: diagnose a deployed Decky AI Assistant or Steam Deck issue and continue to fixes when requested.

Use roles: `deck-planner`, `deck-diagnostician`

Steps:

1. Restate the user-visible symptom.
2. Use read-only knowledge and diagnostics tools.
3. Summarize evidence with citations or local source labels.
4. If a write is needed and requested, show the relevant risk metadata and continue through the active CLI's normal shell/tooling.

Do not read credential stores or hide destructive behavior.
