---
name: deck-flatpak-doctor
description: Diagnose and, when requested, fix Steam Deck Heroic, Lutris, Bottles, Flatpak permission, portal, filesystem, launcher handoff, Wine/Proton runtime, and sandbox access issues through Decky AI Assistant tools and cited knowledge.
---

# Deck Flatpak Doctor

## Workflow

1. Define the scope: launcher name, install source, game/store entry, non-Steam shortcut, symptom, target path, storage location, and approximate time of failure.
2. Use MCP evidence first. Use `inspect_current_game` for Steam shortcut or active game context, `read_proton_logs` for Proton/Wine launch symptoms, and `get_storage_report` when storage/path pressure may be relevant.
3. Use `search_knowledge` for cited Steam Deck, Flatpak, Heroic, Lutris, Bottles, Wine, Proton, Decky, and launcher guidance.
4. Separate launcher evidence, sandbox evidence, runtime evidence, and user-reported facts.
5. Rank likely causes by evidence strength, reversibility, blast radius, and ownership.
6. If a permission, runtime, package, prefix, shortcut, or config change is requested, classify risk, show exact commands or edits, and execute through the active CLI's normal shell/tooling.

## Evidence Rules

- Redact tokens, account identifiers, license keys, shell history, unrelated home-directory details, full private path dumps, and credential-like strings.
- Keep output small enough for Steam Deck Gaming Mode.
- Avoid broad home-directory enumeration unless explicitly requested.

## Diagnostic Domains

| Domain | Guidance |
| --- | --- |
| Launcher identity | Determine whether Heroic, Lutris, Bottles, Steam, or a non-Steam shortcut owns the failing launch path. |
| Flatpak sandbox | Look for evidence of missing filesystem, device, portal, network, or environment access. |
| Filesystem paths | Check whether the game, prefix, or library is on internal storage, SD card, removable media, or a hidden path. |
| Runtime and libraries | Distinguish missing Flatpak runtimes, Wine/Proton runner issues, Vulkan/GPU hints, and launcher update mismatch. |
| Prefix and saves | Treat Wine prefixes, Bottles bottles, Heroic prefixes, Lutris prefixes, saves, and account state as user data. |
| Steam handoff | Inspect shortcut/app context and Proton logs before blaming the launcher. |

## Boundaries

- Never read, export, log, or summarize AI CLI auth tokens, launcher account tokens, store credentials, or provider credential stores.
- Risk labels are informational metadata; command approval belongs to the active CLI.

## Output Shape

Return a concise report with:

- `goal` and `scope`
- `evidence_gathered`
- `launcher_context`
- `sandbox_and_permissions`
- `runtime_and_prefix_context`
- `findings`
- `likely_causes`
- `proposed_fix_risk`
- `actions_taken`, when a fix was requested and executed
- `handoff`, when a handoff is useful
