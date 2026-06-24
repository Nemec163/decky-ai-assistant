# Risk Model Reference

## Classification

| Risk | Examples | Required behavior |
| --- | --- | --- |
| read_only | List logs, inspect versions, query storage, search local knowledge | Allowed after user request. |
| low_write | Create backup, write plugin config, update local index | Show plan and get approval. |
| high_write | Edit game config, launch option changes, Flatpak permissions | Show exact diff/commands, backup where possible, approval. |
| danger | `sudo`, `rm`, `pacman`, `systemctl`, `chmod`, readonly partition changes | Separate explicit approval and rollback/restore path where possible. |

## Escalation Rules

- Any command requiring elevated permissions is danger unless proven read-only and explicitly bounded.
- Any deletion command is danger unless it only removes a temporary file created by the current action.
- Any game config, launch option, Flatpak permission, or system integration edit is high_write or higher.
- Any background indexing, source fetch, or local cache update is low_write at minimum.
- Any credential-store access is rejected, not risk-classified for execution.
- Any repo-local change to risk ceilings, approval-token boundaries, staged-action semantics, or execution permissions requires safety-review handoff before commit.

## Approval Text Must Include

- Action title.
- Risk level.
- Exact commands or file diffs.
- Backup path or reason backup is not possible.
- Rollback or restore path where possible.
- Expected user-visible effect.

## Approval Token Boundary

- Natural-language approval authorizes the UI workflow only; it is not an execution token.
- `stage_action` prepares the display plan and staged action ID but does not execute.
- Decky approval flow releases the opaque approval token after the user approves the exact staged action.
- Only `run_approved_action` should receive the token, staged action ID, and expected risk together.
- Agents must not print tokens in handoff records, audit summaries, or chat output.
