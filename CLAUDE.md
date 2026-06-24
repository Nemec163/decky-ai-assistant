# Claude Code Instructions

## Canonical Source

Follow [AGENTS.md](AGENTS.md) as the canonical repo instruction set. This file exists so Claude Code loads the same operating rules natively.

## Required Reading

Before implementation work, read:

1. [ROADMAP.md](ROADMAP.md)
2. [docs/architecture.md](docs/architecture.md) before changing component boundaries
3. [docs/interfaces.md](docs/interfaces.md) before changing public contracts
4. [docs/operations.md](docs/operations.md) before changing build, test, package, or release commands
5. [CONTRIBUTING.md](CONTRIBUTING.md) before changing workflow rules
6. [RELEASING.md](RELEASING.md) before tagging, releasing, or changing version/branch behavior

## Hard Constraints

- Do not read, export, copy, log, or upload AI CLI auth tokens.
- Do not add a hosted model proxy to the default path.
- Do not run background scans unless explicitly enabled by the user.
- Do not auto-execute write, sudo, destructive, or system-level commands in the default path.
- Explicit owner-enabled per-profile CLI permission bypass may launch supported CLIs with their documented no-approval mode, but it must be disabled by default, visible in Settings, persisted per profile, and shown as `danger` risk.
- Do not run the Decky plugin as root by default.
- Do not add telemetry by default.
- Release channels: `main` is dev (pre-release tags `vX.Y.Z-dev.N`); the `stable` branch is stable (`vX.Y.Z`, GitHub latest). Never publish a dev build to stable or mark a `-dev` tag as latest. See [RELEASING.md](RELEASING.md).

## Work Style

- Keep each change scoped to one coherent slice.
- Prefer small, typed, testable modules.
- Keep Decky UI thin; put safety, session, tool, and source management in backend/core packages.
- Add or update tests before UI polish when contracts or risk boundaries change.
- Update docs whenever directories, commands, contracts, or risk behavior change.
- Use [agent-pack/manifest.json](agent-pack/manifest.json) for repo-local skills, roles, commands, adapter templates, and conflict rules.
- Run `python3 agent-pack/scripts/validate_agent_pack.py` after changing `agent-pack/`.
