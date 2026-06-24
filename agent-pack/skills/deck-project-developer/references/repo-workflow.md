# Repo Workflow Reference

## Required Checks

- Start with `git status --short`.
- Read `AGENTS.md`, `ROADMAP.md`, and the relevant docs before implementation.
- For package, command, adapter, or runtime contract changes, update `docs/index.md`, `docs/repo-map.md`, `docs/operations.md`, `docs/interfaces.md`, or `docs/architecture.md` as appropriate.
- Run `python3 /Users/nmc/.codex/skills/repo-docs/scripts/validate_repo_docs.py /Users/nmc/Documents/WORK-NMC/GitHub/decky-ai-assistant` for documentation changes.
- Run `python3 agent-pack/scripts/validate_agent_pack.py` after changing `agent-pack/`.

## Slice Discipline

- A slice should have one owner: docs/workflow, core contract, CLI adapter, MCP tool, Decky UI, knowledge indexing, or action runner.
- Do not mix UI polish with safety-critical backend changes unless the UI is required to verify the safety behavior.
- Add target-native packaging only after portable skills and MCP contracts exist.
- Start each slice with `slice_goal`, `files_in_scope`, and a verification plan.
- End each slice with `files_changed`, `verification`, `risk_notes`, `commit_status`, `allowed_next_role`, and `blocked_condition`.
- Prefer one meaningful commit per completed slice. If validation is incomplete, hand off without committing.

## Agent Pack Changes

- Add shared behavior to portable skills first.
- Add role-specific behavior to `agent-pack/agents/*.md`.
- Add deterministic shortcuts to `agent-pack/commands/*.md`.
- Add target-specific references under `agent-pack/adapters/<target>/`.
- Keep adapter files as templates until their target-native schema is verified against official docs.
- Hand off to `deck-safety-reviewer` before finalizing any change to risk ceilings, approval-token boundaries, staged-action semantics, or execution permissions.
- Hand off to `deck-knowledge-curator` when source, pack, or index-policy ownership is the main slice concern.
