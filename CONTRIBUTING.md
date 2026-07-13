# Contributing

## Workflow

1. Read [AGENTS.md](AGENTS.md), [ROADMAP.md](ROADMAP.md), and the relevant docs in [docs/](docs/).
2. Check the worktree with `git status --short`.
3. Pick one coherent slice of work and keep changes scoped to it.
4. Update tests and docs in the same change when behavior, commands, contracts, directories, or risk boundaries change.
5. Run the relevant verification commands from [docs/operations.md](docs/operations.md).

## Scope Rules

- Prefer complete, narrow changes over broad partial scaffolding.
- Keep product, risk, and interface decisions documented before building UI on top of them.
- Use official CLI auth flows; never inspect provider credential stores.
- Keep default behavior local and opt-in. No telemetry, hosted proxy, or background scans by default.
- When changing agent workflows, update [agent-pack/manifest.json](agent-pack/manifest.json), [agent-pack/tool-policy.json](agent-pack/tool-policy.json), and the affected skills/roles/commands together.

## Risk Review

Every local action should be classified for display before it runs. Risk is metadata; requested writes stay in the active CLI workflow.

| Risk | Display behavior |
| --- | --- |
| read_only | User-requested action is enough. |
| low_write | Show the plan or command when available. |
| high_write | Show exact diff or commands when available. |
| danger | Show exact dangerous commands plainly; the active CLI owns approval. |

Do not hide dangerous commands behind summaries. Show exact commands for `sudo`, `rm`, `pacman`, `systemctl`, permission changes, readonly partition changes, and similar operations.

## Release Channels

Work lands on `main` (the dev channel). Dev builds are pre-release tags `vX.Y.Z-dev.N`; stable builds are tags `vX.Y.Z` cut from the `stable` branch and marked "Latest". Only tested commits are promoted from `main` to `stable`, and a `-dev` tag is never marked latest. See [RELEASING.md](RELEASING.md) for the full policy and the release/promotion commands.

## Pull Request Checklist

- Scope is limited to one coherent change.
- Docs are updated or the change does not alter stable docs.
- Tests/checks were run, or the reason is documented.
- Risk boundaries are unchanged or explicitly documented.
- No AI CLI credentials, local tokens, logs with secrets, or generated indexes are committed.
- `python3 agent-pack/scripts/validate_agent_pack.py` passes when `agent-pack/` changes.
