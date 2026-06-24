# Coordination

## Repo Development

- The active agent using the `deck-project-developer` skill owns one bounded repo slice at a time.
- Repo-local development starts with scope, files in scope, and verification plan before edits.
- Runtime roles are handoff boundaries for review or staging, not the default owners of repository implementation work.
- Use `deck-knowledge-curator` only for source, pack, or index-policy changes that need curation ownership.
- Use `deck-safety-reviewer` before finalizing any change to risk ceilings, approval-token boundaries, staged-action semantics, or execution permissions.
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
- `deck-diagnostician` owns read-only evidence from logs, game context, storage, and knowledge tools.
- `deck-safety-reviewer` owns risk classification, exact approval wording, backup requirements, rollback requirements, and non-executing runtime action staging.
- `deck-executor` owns approved execution only through `run_approved_action`.
- `deck-knowledge-curator` owns source and index proposals; it may stage source/index updates but must not execute them.

## Staged Action Lifecycle

1. Planning and diagnosis collect read-only evidence.
2. Safety review converts a proposed write into an approval-ready action shape.
3. `deck-safety-reviewer` may call `stage_action` to create a staged action record and `display_plan`; it must not execute commands or file edits.
4. Decky approval flow shows the exact staged action and releases the approval token only after user approval.
5. `deck-executor` calls `run_approved_action` with the staged action ID, approval token, and expected risk.
6. Execution returns sanitized status, audit ID, and rollback status.

## Handoff Record

Each handoff should include:

- user-visible goal;
- evidence gathered;
- risk level;
- exact commands and file diffs, when a write is proposed;
- backup path or backup note;
- rollback steps or rollback note;
- staged action ID, if any;
- allowed next role;
- blocked condition, if any.

Do not include an approval token in a handoff record before Decky approval. After approval, pass the token only to `deck-executor` for the matching `run_approved_action` call.

## Approval Token Boundary

- Approval tokens are bearer execution capabilities, not conversational approval text.
- Agents must not invent, echo, persist, or summarize approval tokens.
- Agents must not receive approval tokens before Decky approval.
- A token is valid only for its staged action ID and expected risk.
- Natural-language approval does not replace the token for `run_approved_action`.
- Staging output may include `staged_action_id`, `risk`, `requires_approval`, and `display_plan`; it must not expose execution credentials.

## Conflict Rules

- Only one role may own a staged action ID at a time.
- Diagnosis roles cannot execute writes.
- Executor cannot change the staged command list.
- Executor must reject a missing token, risk mismatch, action ID mismatch, or changed command/file-edit list.
- Target-native adapters cannot override `AGENTS.md` safety rules.
- Runtime tooling cannot read or export AI CLI credentials.
