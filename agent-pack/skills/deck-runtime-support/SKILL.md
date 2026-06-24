---
name: deck-runtime-support
description: Operate and troubleshoot a deployed Decky AI Assistant runtime through local read-only diagnostics, knowledge search, staged actions, and explicit approval. Use for Steam Deck runtime support, current game diagnosis, storage diagnosis, source search, and agent handoffs.
---

# Deck Runtime Support

## Workflow

1. Identify the user-visible issue and current context.
2. Use read-only MCP tools first: knowledge search, source listing, current game inspection, logs, and storage reports.
3. Keep findings cited and small enough for Gaming Mode UI.
4. If a fix is needed, ask `deck-safe-action-review` to classify risk and prepare the approval text.
5. Produce a staged-action handoff with exact commands/diffs, backups, rollback, expected effect, and allowed next role.
6. Use `stage_action` only from an `action_staging` context; do not execute from diagnosis or review roles.
7. Hand off approved execution only to `deck-executor` with the matching staged action ID, expected risk, and Decky approval token.
8. Record sanitized audit details without tokens, secrets, or full private paths unless necessary for the user.

## Boundaries

- Never read, print, upload, or summarize AI CLI auth tokens.
- Never run `sudo`, `rm`, package manager, permission, systemd, or readonly partition commands without danger-level handling.
- Never mutate game configs, Flatpak permissions, launch options, or plugin settings directly from diagnosis.
- Never start background scans or indexing unless the user explicitly requested that run.

## Conflict Avoidance

- One role owns one action at a time.
- Diagnosis roles can collect evidence but cannot execute writes.
- Safety review can approve wording and risk classification but cannot issue approval tokens or execute writes.
- Staging creates a pending approval record; it is not user approval.
- Executor can run only a previously staged action approved by Decky UI.

## References

- Read `references/runtime-contract.md` when wiring MCP tools, runtime roles, approvals, or audit events.
