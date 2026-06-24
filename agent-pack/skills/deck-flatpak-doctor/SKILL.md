---
name: deck-flatpak-doctor
description: Diagnose Steam Deck Heroic, Lutris, Bottles, Flatpak permission, portal, filesystem, launcher handoff, Wine/Proton runtime, and sandbox access issues through Decky AI Assistant read-only MCP tools and cited knowledge. Use for Flatpak launcher doctor workflows, non-Steam game launch failures, missing library/runtime symptoms, SD card access problems, and "Heroic/Lutris/Bottles cannot see or launch my game" questions; do not use to change permissions or execute fixes.
---

# Deck Flatpak Doctor

## Workflow

1. Define the scope: launcher name, install source, game/store entry, non-Steam shortcut, symptom, target path, storage location, and approximate time of failure.
2. Use read-only MCP evidence first. Use `inspect_current_game` when a Steam shortcut or active game context is involved; use `read_proton_logs` when the symptom reaches Proton/Wine launch; use `get_storage_report` when SD card, compatdata, shadercache, logs, or path pressure may be relevant.
3. Use `search_knowledge` for cited Steam Deck, Flatpak, Heroic, Lutris, Bottles, Wine, Proton, Decky, and launcher guidance. Include source IDs, revisions, headings, or local log labels.
4. Separate launcher evidence, sandbox evidence, runtime evidence, and user-reported facts. If MCP lacks a needed Flatpak-specific inspector, return a blocked condition instead of falling back to ad hoc shell commands.
5. Rank likely causes by evidence strength, reversibility, blast radius, and whether the issue is app-specific, launcher-specific, sandbox-specific, runtime-specific, or storage/path-specific.
6. Use `propose_fix` only after evidence is collected and only when the active role/tool policy allows planning tools. Treat its result as a read-only plan and risk classification, not approval.
7. If a permission, runtime, package, prefix, shortcut, or config change is needed, hand off to `deck-safe-action-review`; this skill never calls `stage_action` or `run_approved_action`.
8. End with `no_action_taken` unless a separate allowed staging role creates a pending action.

## Evidence Rules

- Prefer bounded MCP output over shell inspection. Do not invent `flatpak`, `find`, `stat`, `chmod`, or package-manager probes when the runtime tool does not expose them.
- `inspect_current_game` should identify whether Steam is launching a native title, non-Steam shortcut, launcher wrapper, or current app context.
- `read_proton_logs` should summarize recent bounded Proton/Wine launch windows when the launcher hands off to a game or prefix.
- `get_storage_report` should support claims about SD card paths, compatdata, shadercache, logs, screenshots, videos, or storage pressure; do not turn launcher diagnosis into broad cleanup.
- `search_knowledge` should cite stable source metadata for Flatpak sandbox behavior, launcher configuration, runtime packages, filesystem access, and safe troubleshooting.
- Redact tokens, account identifiers, license keys, shell history, unrelated home-directory details, full private path dumps, and credential-like strings.
- Keep output small enough for Steam Deck Gaming Mode. Avoid unbounded scans, background work, and broad home-directory enumeration.

## Diagnostic Domains

| Domain | Guidance |
| --- | --- |
| Launcher identity | Determine whether Heroic, Lutris, Bottles, Steam, or a non-Steam shortcut owns the failing launch path. Avoid mixing launcher-specific fixes until ownership is clear. |
| Flatpak sandbox | Look for evidence of missing filesystem, device, portal, network, or environment access. Permission changes are high-write candidates and must be reviewed, not applied. |
| Filesystem paths | Check whether the game, prefix, or library is on internal storage, SD card, removable media, or a path the launcher cannot see. Treat path remapping as a configuration change. |
| Runtime and libraries | Distinguish missing Flatpak runtimes, Wine/Proton runner issues, Vulkan/GPU hints, and launcher update mismatch. Do not run installs, repairs, or updates from this skill. |
| Prefix and saves | Treat Wine prefixes, Bottles bottles, Heroic prefixes, Lutris prefixes, saves, and account state as user data. Do not delete, reset, or rewrite them from diagnosis. |
| Steam handoff | When Steam launches the entry, inspect shortcut/app context and Proton logs before blaming the launcher. Do not edit launch options directly. |

## Action Boundaries

- Never change Flatpak permissions, overrides, portals, launch options, shortcuts, prefixes, saves, game configs, Decky settings, or launcher settings directly.
- Never run `flatpak override`, `flatpak repair`, `flatpak update`, package managers, `sudo`, `rm`, `chmod`, `chown`, `systemctl`, readonly partition changes, or system-level commands from this skill.
- Treat Flatpak permission changes and launcher config edits as high-write unless a stricter risk applies. They require exact diffs or commands, backup or rollback notes where possible, and Decky approval through the staged-action flow.
- Treat package installs, repairs, system service changes, destructive deletion, ownership changes, and readonly partition changes as danger-level candidates requiring separate explicit approval.
- Never read, export, log, or summarize AI CLI auth tokens, launcher account tokens, store credentials, or provider credential stores.
- If runtime MCP tools are missing, return a blocked read-only report and the exact missing capability instead of inventing local command sequences.

## Output Shape

Return a concise report with:

- `goal` and `scope`
- `evidence_gathered` with tool names, citations, and local log labels
- `launcher_context`
- `sandbox_and_permissions`
- `runtime_and_prefix_context`
- `findings` separated from `hypotheses`
- `likely_causes` with confidence, impact, reversibility, and supporting evidence
- `safe_next_steps` limited to read-only checks or user-visible manual choices
- `proposed_fix_risk`, when planning output is available
- `no_action_taken`
- `handoff`, when a write may be needed, including allowed next role, exact candidate outcome, backup or rollback note if known, and blocked condition

When the user only asks what is wrong, stop after the read-only report. When the user asks to fix it, produce an evidence handoff for safety review and wait for the staged approval flow; do not proceed to execution.
