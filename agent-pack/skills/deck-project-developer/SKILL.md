---
name: deck-project-developer
description: Develop this repository safely and consistently. Use when implementing, reviewing, or refactoring Decky AI Assistant code, docs, tests, package boundaries, adapter contracts, MCP contracts, or repo workflow rules.
---

# Deck Project Developer

## Workflow

1. Read the required repo docs named in `AGENTS.md`.
2. Check `git status --short` and preserve unrelated user changes.
3. Pick one coherent implementation slice and state `slice_goal`, `files_in_scope`, and the verification plan before editing.
4. Prefer core/backend contracts before UI polish when runtime tools, sources, sessions, or CLI behavior are involved.
5. Use runtime roles only as explicit handoff boundaries. Do not treat them as the default owners of repository edits.
6. Route source, pack, or index-policy ownership questions to `deck-knowledge-curator`.
7. Update tests and docs in the same slice when stable behavior changes.
8. Run the narrowest relevant checks from `docs/operations.md`.
9. End with a development handoff that includes `slice_goal`, `files_in_scope`, `files_changed`, `verification`, `risk_notes`, `commit_status`, `allowed_next_role`, and `blocked_condition`.
10. Create one meaningful commit when the slice is complete; if blocked before commit, leave `commit_status` set to `in_progress` or `ready_to_commit`.

## Boundaries

- Do not inspect AI CLI credential stores, token files, shell history, or provider auth caches.
- Do not add default hosted model proxy behavior.
- Do not add background scans, telemetry, or automatic writes.
- Do not run destructive commands to manage the repo.
- Treat `AGENTS.md` as canonical when host-specific instruction files disagree.

## Development Priorities

- Put reusable logic in planned core/backend packages, not in Decky UI components.
- Keep CLI-specific adapters limited to process/session behavior, detection, and target-native packaging.
- Keep MCP tools small, JSON-shaped, timeout-aware, and risk-classified.
- Keep skills portable; target-specific packaging should wrap them without rewriting the core procedure.
- Keep runtime risk visible while leaving requested writes in the active CLI workflow.

## References

- Read `references/repo-workflow.md` when changing repo workflow, package layout, commands, or agent pack contents.
