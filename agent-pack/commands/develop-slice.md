# develop-slice

Purpose: implement one repo-local development slice with docs and verification.

Use skill: `deck-project-developer`

Steps:

1. Read `AGENTS.md`, `ROADMAP.md`, and the relevant docs.
2. Check `git status --short`.
3. Define the slice goal, files in scope, and verification plan before editing.
4. Use runtime roles only as explicit handoff boundaries. Do not treat them as the default repo editors.
5. Keep risk metadata visible for user-facing CLI workflows.
6. Hand off to `deck-knowledge-curator` when the slice changes source, pack, or index-policy behavior and needs curation ownership.
7. Edit only the files in scope for that slice.
8. Run relevant checks from `docs/operations.md`.
9. Leave a development handoff with `slice_goal`, `files_in_scope`, `files_changed`, `verification`, `risk_notes`, `commit_status`, `allowed_next_role`, and `blocked_condition`.
10. Create one meaningful commit when the slice is complete and validated.

Do not use for runtime Steam Deck repair actions.
