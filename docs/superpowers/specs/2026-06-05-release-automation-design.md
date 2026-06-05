# Automated release management via release-please

**Date:** 2026-06-05
**Status:** approved design
**Branch:** `feat/release-automation` (built in its own worktree; the main
checkout stays free for parallel work)

## Problem

Versions are git tags and nothing reminds the maintainer to push one. `main`
accumulates `feat:`/`fix:` commits, no tag follows, and operators downloading
`releases/latest` get stale binaries. The decision *when* to release must stay
human (event-driven timing), but the *remembering*, *version arithmetic* and
*changelog* should be automated.

## Solution

[release-please](https://github.com/googleapis/release-please-action) in
PR-gated mode:

- A new workflow runs on every push to `main` and maintains a single standing
  **Release PR** that accumulates all Conventional Commits since the last
  release, with the computed next version (`fix:` → patch, `feat:` → minor)
  and a changelog preview. The open PR **is** the reminder.
- **Merging the Release PR** creates the tag `vX.Y.Z` and the GitHub release
  with generated notes. Nothing releases without that human merge.
- Commits of type `docs:`/`ci:`/`chore:`/`test:` alone never open a Release
  PR — quiet periods stay quiet.

## Components

### 1. `.github/workflows/release-please.yml` (new)

- Trigger: `push` to `main`.
- `googleapis/release-please-action@v4`, `release-type: simple`.
- Permissions: `contents: write`, `pull-requests: write`, **`actions: write`**
  (the last one is required for the dispatch step below — without it
  `gh workflow run` fails with 403).
- **Dispatch chain** (the critical part): tags created with the default
  `GITHUB_TOKEN` do **not** trigger `on: push: tags` workflows. Therefore,
  when the action reports `releases_created == 'true'`, a follow-up step runs
  `gh workflow run release.yml --ref <tag>` (`workflow_dispatch` is exempt
  from the GITHUB_TOKEN trigger restriction). Without this, merging the
  Release PR would produce a tag + release **with no binaries**.

### 2. `.github/workflows/release.yml` (one-line change)

- Add `workflow_dispatch:` alongside the existing tag trigger. When
  dispatched with `--ref <tag>`, `github.ref_name` is the tag name, so the
  existing `build-binary.py --version "${{ github.ref_name }}"` stamping is
  unchanged. The `gh release create … || true` step is already idempotent
  (release-please created the release first); asset upload already uses
  `--clobber`. **No other change** to release.yml.

### 3. Repo artifacts (new files, maintained by the bot)

- `release-please-config.json` — release-type simple, package name `iro`.
- `.release-please-manifest.json` — seeded with the current version `0.1.0`.
- `CHANGELOG.md` — bot-maintained from commit messages.
- `version.txt` — bumped by the bot; **informational only**. The authoritative
  version remains the git tag: the binary stamps `github.ref_name` at build
  time. No code reads version.txt.

### 4. Docs

- Wiki `Build-and-maintenance.md` → "Releases" section: primary flow becomes
  "merge the Release PR when an event approaches"; pushing a manual `v*` tag
  stays documented as the unchanged escape hatch (it still triggers
  release.yml directly via tag push).
- `CLAUDE.md`: one sentence in the Standalone-binary section pointing at the
  release-please flow.

## Constraints / facts verified against the current repo (2026-06-05)

- `release.yml` is untouched by the recent Windows-test commits — premises
  hold exactly.
- The repo's ruleset ("changes must be made through a pull request") is
  *satisfied*, not fought, by this design: the Release PR passes the 5
  required status checks like any PR (it only touches CHANGELOG/manifest/
  version.txt; CI is unaffected by those).
- Commit discipline is already Conventional throughout recent history.

## Expected first run

`main` already carries multiple `feat:`/`fix:` commits since `v0.1.0`
(Discord audio localization, Companion first-launch fix, cookie fixes, …), so
the **first Release PR will immediately propose `v0.2.0`** with all of them in
the changelog. That is correct behavior, not a bug.

## Acceptance

1. Merge a `fix:`-typed commit to `main` → Release PR appears/updates with a
   patch bump.
2. Merge the Release PR → tag + GitHub release exist, **and** release.yml ran
   via dispatch and uploaded the three archives (`iro-windows.zip`,
   `iro-macos.tar.gz`, `iro-linux.tar.gz`).
3. `iro --version` of a downloaded binary prints the new tag.
4. A manual `git tag vX.Y.Z && git push origin vX.Y.Z` still produces a full
   release (escape hatch intact).

## Out of scope

- Auto-merge of the Release PR (the human gate is the point).
- Checksums/signing of assets (tracked as future work in the self-update
  spec).
- Major-version (`vN.0.0`) policy — bump manually via release-please's
  `Release-As:` commit footer when ever needed.
