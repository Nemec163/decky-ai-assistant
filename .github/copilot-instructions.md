# GitHub Copilot Instructions

Follow the canonical project rules in [AGENTS.md](../AGENTS.md).

Core constraints:

- Never read, export, copy, log, or upload AI CLI auth tokens.
- Do not add hosted model proxy behavior to the default path.
- Do not auto-execute commands on the plugin's own initiative; terminal actions are user-initiated through the UI or active CLI.
- Per-profile CLI permission bypass may launch supported CLIs with their documented no-approval mode; keep it visible in Settings, persisted per profile, and shown as `danger` risk.
- Keep Decky frontend code thin; put session, source, and risk metadata in backend/core packages.
- Prefer small, explicit modules with tests around contracts and risk classification.
- Update docs when directories, commands, public contracts, or risk behavior change.
- Use `agent-pack/manifest.json` for repo-local agent workflows and run `python3 agent-pack/scripts/validate_agent_pack.py` after changing `agent-pack/`.
