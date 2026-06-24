---
name: deck-knowledge-curator
description: Add, update, audit, disable, or remove Decky AI Assistant knowledge sources with license, revision, hash, citation, include/exclude filter, and Steam Deck resource-limit discipline. Use for development or runtime source-curation procedures; do not use to implement the indexer or bypass staged write approval.
---

# Deck Knowledge Curator

## Workflow

1. Intake the source request before touching local state.
2. Classify the highest-risk action: source listing and metadata inspection are `read_only`; adding, updating, disabling, removing, fetching, or indexing sources is at least `low_write`; deleting local files, changing permissions, or using privileged commands escalates to `danger`.
3. Verify source identity with stable fields: source type, canonical URL or local path, owner/publisher, intended scope, license, revision, content hash strategy, enabled state, and citation label.
4. Reject credential-store reads, token export, hosted proxy requirements, background scans, and unbounded repository crawls.
5. Apply include/exclude filters before proposing any fetch or indexing work.
6. Enforce size and time limits suitable for Steam Deck Gaming Mode.
7. Require citations for every indexed chunk or runtime answer that uses the source.
8. Stage writes as an approval-ready plan; do not execute fetch, index, enable, disable, remove, or cleanup actions from this skill.
9. Report disabled, skipped, failed, or removed sources separately from enabled sources.

## Intake Checklist

Capture these fields in the staged plan or audit note:

| Field | Requirement |
| --- | --- |
| Source ID | Stable lowercase identifier, unique within the local source registry. |
| Source type | `github_repo`, `git_url`, `docs_url`, `local_folder`, or `pack_registry`. |
| Location | Canonical URL, registry entry, or local path; redact private home-path details unless needed. |
| Purpose | The Deck question or workflow the source should support. |
| License | SPDX ID or exact upstream license label; `unknown` keeps the source disabled. |
| Revision | Git commit/tag, release version, ETag/Last-Modified, document version, or retrieval timestamp when no stronger revision exists. |
| Hash | SHA-256 for pack artifacts, fetched documents, or file manifest after filters. |
| Citation format | Source title plus URL/path, revision, heading or file path, and chunk location when available. |
| Resource budget | Max bytes, max files, max fetch/index time, and whether work is manual-request only. |

## Filters

Prefer useful documentation over exhaustive capture.

- Include text documentation formats: Markdown, plaintext, reStructuredText, AsciiDoc, HTML documentation pages, JSON/YAML metadata only when it explains the source.
- Exclude binaries, images, archives, vendored dependencies, generated build outputs, caches, lockfiles, minified assets, node_modules, package stores, logs, secrets, credential files, and large unrelated code trees.
- Exclude files without a clear citation path or license coverage.
- Stop and ask for a narrower scope when filters still exceed the declared resource budget.

## License And Citation Gates

- Enable only sources with known license metadata and a recorded revision/hash.
- Mark `unknown`, missing, incompatible, or unclear license sources as disabled with a concise reason and next review step.
- Prefer upstream license files, package metadata, release metadata, or official site terms over copied license summaries.
- Keep citation payloads small: source ID, title, URL/path, license, revision, file or heading, and chunk locator.
- Do not quote large source passages when a citation and concise summary are enough.

## Resource Limits

- Default to manual, user-requested indexing only; do not schedule background refreshes.
- Bound each staged source update with byte, file-count, and elapsed-time limits.
- Prefer static pack artifacts or narrowed documentation paths for large repositories.
- Stop cleanly when limits are hit and report what was included, skipped, and still available for a narrower follow-up.
- Keep outputs short enough for Steam Deck UI and avoid dumping full manifests unless requested.

## Staged Output

When proposing a source change, return an approval-ready plan with:

- Action title and risk level.
- Source metadata from the intake checklist.
- Include/exclude filters.
- Resource limits and stop conditions.
- Expected writes, such as registry metadata, local cache/index files, enabled-state changes, or cleanup.
- Backup or rollback note for any local metadata or cache mutation.
- Disabled, removed, skipped, or failed source report with reasons.
- Exact command or file-diff placeholder when another tool or role will stage the concrete action.

Hand off execution only through the repo/runtime staged-action flow and Decky-side approval token. Keep this skill focused on curation decisions and approval-ready source plans, not indexer implementation.
