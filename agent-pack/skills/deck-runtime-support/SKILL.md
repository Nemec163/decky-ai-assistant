---
name: deck-runtime-support
description: Operate and troubleshoot a deployed Decky AI Assistant runtime through local diagnostics, knowledge search, concise fix plans, and the active CLI terminal workflow. Use for Steam Deck runtime support, current game diagnosis, storage diagnosis, source search, and agent handoffs.
---

# Deck Runtime Support

## Workflow

1. Identify the user-visible issue and current context.
2. Use MCP tools for knowledge search, source listing, current game inspection, logs, and storage reports.
3. Keep findings cited and small enough for Gaming Mode UI.
4. If a fix is needed, classify risk and show exact commands or file edits when available.
5. Use `propose_fix` when evidence should be turned into a concise plan.
6. Execute requested fixes through the active CLI's normal shell/tooling.
7. Record sanitized audit details without secrets or unrelated private paths.

## Boundaries

- Never read, print, upload, or summarize AI CLI auth tokens.
- Never start background scans or indexing unless the user explicitly requested that run.
- Risk labels are informational metadata for user-requested CLI workflows.

## Conflict Avoidance

- One role owns one runtime handoff at a time when roles choose to hand off.
- Any runtime role may continue into user-requested fixes when the active CLI permits it.
- The active CLI owns command approval and sandbox behavior.

## References

- Read `references/runtime-contract.md` when wiring MCP tools, runtime roles, fix plans, or audit events.
