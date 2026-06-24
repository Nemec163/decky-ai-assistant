# stage-safe-action

Purpose: convert a proposed runtime fix into an approval-ready staged action handoff.

Use roles: `deck-safety-reviewer` for review and `stage_action`, then `deck-executor` only after Decky approval.

Steps:

1. Restate the user-visible goal and evidence that justifies a write.
2. List exact commands and file edits as structured argv/diffs, not shell prose.
3. Classify the highest risk using `deck-safe-action-review`.
4. Add backup paths or backup notes, plus rollback steps or rollback notes.
5. Produce a staging handoff with title, risk, commands, file edits, backups, rollback, expected effect, blocked condition, and allowed next role.
6. Call `stage_action` only from `deck-safety-reviewer` or another context explicitly allowed to use `action_staging`; otherwise stop with the staging handoff.
7. Show the returned `display_plan` in Decky approval UI and wait for user approval.
8. Hand off only the matching staged action ID, expected risk, and Decky approval token to `deck-executor`.

Do not run unstaged actions. Do not treat natural-language approval as an execution token or print approval tokens in summaries.
