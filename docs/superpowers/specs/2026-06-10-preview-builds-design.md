# Preview builds — testable binaries before a real release

**Date:** 2026-06-10
**Status:** approved design

## Problem

Packaged binaries only exist when a real release is cut (`release.yml` on a
`v*` tag, driven by release-please). But sometimes a build needs to be tested
*ahead* of a release — either a single open PR, or `main` after several PRs have
merged with no release yet. Today the maintainer works around this by cutting
real (under-tested) versions and running the user/acceptance tests afterward.
That pollutes the real release history with provisional versions and inverts the
test order (publish first, validate later).

We want a **preview** channel: real packaged binaries (not a local dev build),
downloadable by **external testers without a GitHub account**, that are clearly
*not* the latest release, never interfere with the real release flow, and are
**green-built** (full test gate passes before publish).

## Solution

A new workflow `.github/workflows/preview.yml`, fully separate from
`release.yml`. It builds the same three OS archives as a real release and
publishes them as a **GitHub pre-release** (`gh release create --prerelease`),
which gives every asset a public, login-free download URL while keeping it off
the "Latest" slot on the Releases page.

Two triggers, one publish mechanism:

| Trigger | What it builds |
|---|---|
| `pull_request` (`labeled`, `synchronize`) | The PR branch — **only** when the PR carries the `preview` label. New commits on a labeled PR rebuild the preview. |
| `workflow_dispatch` (input `ref`, default `main`) | The chosen ref (default `main`) — for "several PRs merged, no release yet". |

**Hard separation from real releases:** preview tags are named `preview-*`,
**never `v*`**. `release.yml` triggers only on `v*`, and release-please only
tracks `v*` tags — so a preview can never trigger a real release nor perturb the
version arithmetic / Release PR.

## Components

### 1. `.github/workflows/preview.yml` (new)

**Triggers**

```yaml
on:
  pull_request:
    types: [labeled, synchronize]
  workflow_dispatch:
    inputs:
      ref:
        description: "Branch/ref to build (default: main)"
        default: main
```

**Permissions:** `contents: write` (create/upload the pre-release),
`pull-requests: write` (the PR comment).

**Concurrency:** `cancel-in-progress: true`, grouped per preview target so
rapid pushes to a labeled PR don't race two publishes onto the same tag. The
group must use expressions available at workflow-parse time (it cannot reference
the `meta` job's computed `tag` output), e.g.
`group: preview-${{ github.event.pull_request.number || inputs.ref }}`.

**Guard job (`meta`)** — runs first, computes the identity and decides whether
to proceed:

- For the PR trigger, **skip the whole run unless the PR has the `preview`
  label** (the `labeled` event also fires for *other* labels; `synchronize`
  fires on every push). Gate with
  `if: github.event_name == 'workflow_dispatch' || contains(github.event.pull_request.labels.*.name, 'preview')`.
- Compute, as job outputs:
  - `tag` — `preview-pr-<N>` for PRs, `preview-<sanitized-ref>` (e.g.
    `preview-main`) for dispatch. (`<sanitized-ref>` = ref with `/` → `-`.)
  - `version` — the string baked into the binary via `build-binary.py
    --version`, made unambiguous: `preview-pr<N>-<shortsha>` /
    `preview-<ref>-<shortsha>`. A tester running `iro --version` then sees
    exactly which commit they hold.
  - `sha` — the full commit SHA to build and to use as the release `--target`.
  - `title` — e.g. `Preview: PR #<N> (<shortsha>)` / `Preview: main
    (<shortsha>)`.

**Build job** — `needs: meta`, mirrors `release.yml`'s matrix and steps
(windows/macos/ubuntu; `iro` + `iro-ui` binaries; archives
`iro-windows.zip` / `iro-macos.tar.gz` / `iro-linux.tar.gz`, each including
`.env.example`). Per the user's decision, the **full test gate runs first**:

1. checkout `meta.outputs.sha`
2. `python tools/run-tests.py` (the same suite CI/release run)
3. install PyInstaller
4. `python tools/build-binary.py --version "<meta.version>"` (builds + smoke)
5. package the archive (identical packaging block to `release.yml`)
6. create the pre-release idempotently and upload:
   - `gh release create "<tag>" --prerelease --target "<sha>" --title "<title>"
     --notes "<auto>" || true` (first matrix OS wins the create; the rest are
     no-ops thanks to `|| true`)
   - `gh release upload "<tag>" "<asset>" --clobber` (rolling: re-pushing a PR
     overwrites the same tag's assets, so at most one pre-release per open PR /
     per ref)

A new commit on a labeled PR therefore *replaces* that PR's single pre-release
in place — no accumulation.

**PR comment job** (PR trigger only) — `needs: [meta, build]`, posts/updates a
single sticky comment on the PR with the three asset download URLs of the
`preview-pr-<N>` release, so testers grab links straight from the PR.

### 2. `.github/workflows/preview-cleanup.yml` (new, or a job in the same file)

- Trigger: `pull_request: types: [closed]`.
- If a release/tag `preview-pr-<N>` exists, delete both:
  `gh release delete "preview-pr-<N>" --cleanup-tag --yes || true`.
- Keeps the Releases page and the git tag namespace tidy once a PR is
  merged/closed. (Dispatch previews like `preview-main` are rolling and
  overwritten on the next dispatch; no per-PR cleanup hook applies — acceptable,
  there is at most one per ref.)

### 3. Docs

- Wiki `Build-and-maintenance.md` → a short "Preview builds" subsection: add the
  `preview` label to a PR, or run the Preview workflow against `main`; testers
  download from the pre-release; previews are deleted when the PR closes.
- `CLAUDE.md` → one sentence in the Standalone-binary section noting the preview
  channel and the `preview-*` / `v*` separation.

## Constraints / facts verified against the current repo (2026-06-10)

- `release.yml` triggers on `tags: ["v*"]` + `workflow_dispatch`; `preview-*`
  tags do not match, so the separation holds.
- `release-please` (config `release-type: simple`) tracks only `v*` releases —
  `preview-*` releases/tags are invisible to it.
- The preview build reuses `release.yml`'s exact matrix and packaging, so the
  preview archive is byte-for-structure identical to a real release archive
  (same binaries, same `.env.example`, same `ensure_env_file` first-run copy).
- Public repo → Actions minutes (incl. macOS runners) are free; a preview costs
  roughly one release build.

## Acceptance

1. Open a PR, add the `preview` label → the workflow runs the full test suite on
   all three OSes, then a **pre-release** `preview-pr-<N>` appears with the three
   archives, and a PR comment lists the download links.
2. `iro --version` of a downloaded preview binary prints
   `preview-pr<N>-<shortsha>` matching the PR's head commit.
3. Push a new commit to the labeled PR → the same `preview-pr-<N>` pre-release is
   updated in place (no second pre-release).
4. Adding a non-`preview` label, or pushing to an unlabeled PR, does **not**
   build a preview.
5. Run the Preview workflow via `workflow_dispatch` with `ref=main` → a
   `preview-main` pre-release appears with the three archives built from `main`.
6. Close/merge the PR → `preview-pr-<N>` release **and** tag are deleted.
7. Throughout, no `v*` tag, no real GitHub release, and no change to the
   release-please Release PR are produced by any preview run.
8. A failing test in the built ref blocks the pre-release (no assets published).

## Out of scope

- **Fork PRs.** GitHub gives fork-PR workflows a read-only token and no secrets,
  so a preview cannot publish from a fork. The team's same-repo branch workflow
  (collaborators push branches directly, ruleset enforces PR review) means this
  never applies in practice. Documented, not engineered around.
- Checksums/signing of preview assets (unsigned, same Gatekeeper/SmartScreen
  one-time warning as real releases; tracked in the self-update spec).
- Auto-promoting a preview to a real release (the human release gate stays).
- Auto-labeling PRs for preview (the `preview` label is applied by hand —
  opt-in is the point).
