# Runtime Contract

## Tools

1. `search_knowledge`
2. `list_sources`
3. `inspect_current_game`
4. `read_proton_logs`
5. `get_storage_report`
6. `propose_fix`

Use tools 1-5 for evidence and tool 6 for concise planning. Requested writes run through the active CLI's normal shell/tooling.

## Redaction

- Redact tokens, session IDs, API keys, OAuth artifacts, cookies, and full auth paths.
- Preserve enough path context for the user to recognize game, launcher, and storage locations.

## Fix Plans

- A handoff should include goal, evidence, risk, exact write scope when relevant, next role when useful, and blocked condition.
- Planning output should include `title`, `risk`, `steps`, `commands`, and `file_edits`.
- Applied fixes are handled by the active CLI and should keep exact command context visible.
