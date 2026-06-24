# Releasing

Decky AI Assistant ships on **two release channels**. This document is the source of truth for how versions, branches, tags, and the in-plugin self-update relate. Read it before cutting any release.

## Channels at a glance

| Channel | Branch | Version form | Git tag | GitHub release | Self-update default |
| --- | --- | --- | --- | --- | --- |
| **stable** | `stable` | `X.Y.Z` | `vX.Y.Z` | "Latest", `prerelease=false` | ✅ yes |
| **dev** | `main` | `X.Y.Z-dev.N` | `vX.Y.Z-dev.N` | "Pre-release", `prerelease=true` | opt-in |

- **`main` is the dev / integration branch.** Day-to-day work lands here; dev releases are cut from it.
- **`stable` is the release branch.** Only tested commits reach it, and stable releases are cut from it.
- The `0.1.0` baseline is the shared branch point: `main` and `stable` start equal at `0.1.0`. Dev then moves ahead with `-dev.N` pre-releases targeting the next version.

## The hard rule

> **Never publish a dev build to the stable channel, and never mark a `-dev` tag as `--latest`.**

This is what keeps stable clean. Enforcement is layered:

1. **CI** — [`.github/workflows/release.yml`](.github/workflows/release.yml) inspects the pushed tag. A tag containing `-` is published as a **pre-release** and is never marked latest; a clean `vX.Y.Z` tag is published as **latest**.
2. **Self-update** — the backend filters releases by the user's channel. A **stable** install ignores any release with `prerelease=true`; a **dev** install also sees pre-releases. Default channel is **stable**.
3. **Branch discipline** — stable tags are cut from the `stable` branch, dev tags from `main`.

## Version scheme

- **Stable:** plain semver `X.Y.Z` (e.g. `0.1.0`, `0.2.0`).
- **Dev:** `X.Y.Z-dev.N`, where `X.Y.Z` is the **next** stable target and `N` increments per dev build (e.g. after stable `0.1.0`, the first dev build is `0.1.1-dev.1` or `0.2.0-dev.1`). The `-dev.N` suffix sorts **ahead** of the last stable, so dev installs see it as newer; stable installs ignore it.
- `package.json` `version` is the single source of truth. The release workflow refuses to publish if the pushed tag does not match `package.json` (minus the leading `v`).

## Cutting a dev release (from `main`)

```bash
git switch main
# bump package.json "version" to e.g. 0.2.0-dev.1, commit
git commit -am "Decky AI Assistant 0.2.0-dev.1"
git push origin main
git tag v0.2.0-dev.1
git push origin v0.2.0-dev.1     # → release.yml builds + publishes a pre-release
```

## Cutting a stable release (promote `main` → `stable`)

```bash
# 1. Make sure main is green and the desired commit is the release point.
git switch stable
git merge --ff-only main          # or merge the tested commit range
# 2. Drop the -dev suffix: set package.json "version" to e.g. 0.2.0, commit
git commit -am "Decky AI Assistant 0.2.0"
git push origin stable
git tag v0.2.0
git push origin v0.2.0           # → release.yml builds + publishes as Latest
# 3. Bump main to the next dev line (e.g. 0.2.1-dev.1 or 0.3.0-dev.1).
```

If `--ff-only` is not possible because `stable` has diverged, merge the specific tested commits rather than fast-forwarding the whole of `main`; `stable` should only ever contain shippable history.

## How the self-update picks a release

The plugin backend ([`main.py`](main.py)) reads the persisted channel (`release-channel.json`, default `stable`) and fetches GitHub Releases:

- **stable** → considers only non-draft, non-prerelease releases; picks the highest semver.
- **dev** → considers non-draft releases including pre-releases; picks the highest semver (a newer stable still wins over an older dev).

Users switch channels in **Settings → Diagnostics → Plugin Update**. Switching to **dev** is the only way to receive `-dev.N` builds.

## The release artifact

`pnpm run package` (run by the workflow) produces `out/decky-ai-assistant-v<version>.zip` with a top-level `decky-ai-assistant/` directory containing the built `dist/index.js`, `main.py`, metadata, the bundled Python `packages/`, `agent-pack/`, docs, and host instruction files. This ZIP — not GitHub's `Source code (zip)` — is the installable asset.

## Releasing checklist

- [ ] On the right branch (`main` for dev, `stable` for stable).
- [ ] `package.json` version matches the tag you are about to push.
- [ ] Dev tag has a `-dev.N` suffix; stable tag does not.
- [ ] Tests green (`unittest` suites + `agent-pack` validator) and `pnpm run check` passes.
- [ ] Pushed the tag; confirmed the workflow published with the correct pre-release / latest flag.
