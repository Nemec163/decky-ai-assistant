# GitHub Copilot Instructions

Follow the canonical project rules in [AGENTS.md](../AGENTS.md).

Core constraints:

- Never read, export, copy, log, or upload AI CLI auth tokens.
- Do not add hosted model proxy behavior to the default path.
- Do not auto-execute write, sudo, destructive, or system-level commands in the default path.
- Explicit owner-enabled per-profile CLI permission bypass may launch supported CLIs with their documented no-approval mode, but it must stay disabled by default, visible in Settings, persisted per profile, and shown as `danger` risk.
- Keep Decky frontend code thin; put session, action, source, and safety logic in backend/core packages.
- Prefer small, explicit modules with tests around contracts and risk classification.
- Update docs when directories, commands, public contracts, or risk behavior change.
- Use `agent-pack/manifest.json` for repo-local agent workflows and run `python3 agent-pack/scripts/validate_agent_pack.py` after changing `agent-pack/`.
