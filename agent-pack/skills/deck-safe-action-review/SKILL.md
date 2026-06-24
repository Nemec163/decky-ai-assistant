---
name: deck-safe-action-review
description: Review proposed local Steam Deck actions before execution. Use before any write, sudo, destructive command, config edit, Flatpak permission change, package manager action, plugin setting mutation, or staged MCP action.
---

# Deck Safe Action Review

## Workflow

1. Identify every command, file edit, permission change, backup, rollback, and runtime side effect.
2. Classify the highest risk across the full action, not each command in isolation.
3. Require exact commands or diffs for write, high-write, and danger actions.
4. Require backup or rollback notes for high-write and danger actions where possible.
5. Return an approval-ready staging handoff and the minimum safe execution scope.
6. Treat `stage_action` output as pending approval; only the Decky approval flow can release the execution token.
7. Reject execution if the action lacks required approval, uses vague natural-language permission, or hides destructive behavior.
8. For repo-local development, require this review before finalizing changes to risk ceilings, approval-token boundaries, staged-action semantics, or execution permissions.

## Risk Levels

| Risk | Allowed without approval | Requires |
| --- | --- | --- |
| read_only | User-requested inspection only | No mutation, bounded output. |
| low_write | Nothing | Plan and approval. |
| high_write | Nothing | Exact diff/commands, backup where possible, approval. |
| danger | Nothing | Separate explicit approval and rollback/restore path where possible. |

## Hard Stops

- Do not approve reading or exporting provider credentials.
- Do not approve write execution through read-only roles.
- Do not approve unstaged actions.
- Do not approve commands that differ from the displayed command list.
- Do not invent, print, log, or summarize Decky approval tokens.
- Do not expand into routine docs-only or implementation-only review when the slice does not change safety or execution boundaries.

## Staging Handoff

Return these fields when a write may be acceptable:

- `title`
- `risk`
- `commands` as structured argv
- `file_edits` as exact diffs when required
- `backups` or `backup_note`
- `rollback` or `rollback_note`
- `expected_effect`
- `blocked_condition`
- `allowed_next_role`

After `stage_action`, carry only `staged_action_id`, `risk`, and `display_plan` forward for Decky approval. After Decky approval, pass the approval token only to `deck-executor` for `run_approved_action`.

## References

- Read `references/risk-model.md` when classifying action schemas or command plans.
