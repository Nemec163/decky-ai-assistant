# Runtime Contract Reference

## Tool Order

1. `search_knowledge`
2. `list_sources`
3. `inspect_current_game`
4. `read_proton_logs`
5. `get_storage_report`
6. `propose_fix`
7. `stage_action`
8. `run_approved_action`

Use tools 1-6 from diagnosis and planning roles. Use `stage_action` only after risk review and only from a context allowed to use `action_staging`. Use `run_approved_action` only from `deck-executor` with a Decky approval token.

## Evidence Rules

- Keep tool results structured and short.
- Prefer source IDs, citations, revisions, and license metadata over copied source text.
- Redact tokens, session IDs, API keys, OAuth artifacts, cookies, and full auth paths.
- Include enough local path context for the user to act, but do not expose unrelated private data.

## Runtime Locking

- A staged action has one owner role and one action ID.
- A role handoff must include goal, evidence, risk, exact write scope when relevant, staged action ID if any, next allowed role, and blocked condition.
- Staging output should include `staged_action_id`, `risk`, `requires_approval`, and `display_plan`, not the approval token.
- Decky approval flow controls approval-token release.
- Executor must compare the approved action ID, expected risk, and command/file-edit list before running.
- Failed actions return sanitized stderr/stdout summaries and rollback status.
