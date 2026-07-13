# Coordination

## Repo Development

- The active agent using the `deck-project-developer` skill owns one bounded repo slice at a time.
- Repo-local development starts with scope, files in scope, and verification plan before edits.
- Runtime roles are organizational labels for terminal-first runtime work.
- Use `deck-knowledge-curator` only for source, pack, or index-policy changes that need curation ownership.
- Do not mix unrelated files or multiple independent slices into one development session handoff or one commit.

## Development Handoff Record

Each repo-local handoff should include:

- `slice_goal`;
- `files_in_scope`;
- `files_changed`;
- `verification`;
- `risk_notes`;
- `commit_status`;
- `allowed_next_role`;
- `blocked_condition`.

`commit_status` should state whether the slice is `not_started`, `in_progress`, `ready_to_commit`, or `committed`. The slice owner creates one meaningful commit after relevant validation passes. If work stops before commit, hand off with `commit_status` set to `in_progress` or `ready_to_commit` and leave the next owner explicit.

## Runtime Coordination

## Ownership

- `deck-planner` owns user intent, plan shape, and next-role selection.
- `deck-diagnostician` owns evidence from logs, game context, storage, and knowledge tools.
- `deck-knowledge-curator` owns source and index proposals.

## Terminal Flow

1. Planning and diagnosis collect evidence with read-only MCP tools where useful.
2. `propose_fix` may turn evidence into a concise plan and risk label.
3. Requested fixes run through the active CLI's normal shell/tooling.
4. Decky keeps requested writes in the active CLI workflow.

## Handoff Record

Each handoff should include:

- user-visible goal;
- evidence gathered;
- risk level;
- exact commands and file diffs, when a write is proposed;
- backup path or backup note, when useful;
- rollback steps or rollback note, when useful;
- allowed next role;
- blocked condition, if any.

Risk is informational metadata for the active CLI workflow.

## Conflict Rules

- Runtime roles may continue into user-requested writes when the active CLI permits it.
- Target-native adapters cannot override `AGENTS.md` credential rules.
- Runtime tooling cannot read or export AI CLI credentials.
