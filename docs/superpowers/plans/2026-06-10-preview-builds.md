# Preview Builds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `preview` channel that publishes real, downloadable binaries as a GitHub pre-release — from a labeled PR or a `workflow_dispatch` against `main` — without ever touching the real `v*` release flow.

**Architecture:** A small unit-tested Python helper (`tools/preview_meta.py`) computes the pre-release identity (tag/version/title) from the triggering event. A new workflow `.github/workflows/preview.yml` runs that helper, the full test gate, the PyInstaller build (same 3-OS matrix as `release.yml`), and publishes a `preview-*` pre-release with public download URLs, then comments the links on the PR. A second workflow `.github/workflows/preview-cleanup.yml` deletes a PR's pre-release + tag when the PR closes.

**Tech Stack:** GitHub Actions (YAML), `gh` CLI, Python 3 stdlib (helper + tests), PyInstaller (existing build).

---

## File Structure

- **Create `tools/preview_meta.py`** — pure `compute_preview_meta()` (tag/version/title from event data) + a thin `main()` that emits `key=value` lines for `$GITHUB_OUTPUT`. CI-only, maintainer tooling, not shipped (lives in `tools/`, which `build.py` never copies).
- **Create `tests/test_preview.py`** — stdlib unit checks for the helper. Auto-discovered by `tools/run-tests.py` (globs `tests/test_*.py`), so it runs in CI and in the preview's own test gate.
- **Create `.github/workflows/preview.yml`** — the preview build+publish pipeline (jobs: `meta` → `release` → `build` → `comment`).
- **Create `.github/workflows/preview-cleanup.yml`** — deletes `preview-pr-<N>` on PR close.
- **Modify `src/docs/wiki/Build-and-maintenance.md`** — add a "Preview builds" subsection.
- **Modify `CLAUDE.md`** — one sentence in the Standalone-binary section.

> **Note on workflow testing:** GitHub Actions YAML cannot be unit-tested with the repo's stdlib-only suite (no PyYAML). The testable logic is therefore extracted into `tools/preview_meta.py` and covered by `tests/test_preview.py`. The workflow wiring itself is verified by the integration acceptance run in Task 7.

---

## Task 1: Preview identity helper — pure function (TDD)

**Files:**
- Create: `tools/preview_meta.py`
- Test: `tests/test_preview.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_preview.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the preview-build identity helper.
Run: python3 tests/test_preview.py"""
import contextlib, importlib.util, io, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "preview_meta", os.path.join(ROOT, "tools", "preview_meta.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


# --- compute_preview_meta: PR builds keyed by PR number ----------------------
def t_pr_meta():
    out = m.compute_preview_meta("pull_request", pr_number=42,
                                 sha="0123abcdef9999")
    assert out == {
        "tag": "preview-pr-42",
        "version": "preview-pr42-0123abc",
        "title": "Preview: PR #42 (0123abc)",
    }, out


def t_pr_meta_accepts_string_number():
    out = m.compute_preview_meta("pull_request", pr_number="7",
                                 sha="abcdef1234567")
    assert out["tag"] == "preview-pr-7"
    assert out["version"] == "preview-pr7-abcdef1"


# --- compute_preview_meta: dispatch builds keyed by sanitized ref ------------
def t_dispatch_main():
    out = m.compute_preview_meta("workflow_dispatch", ref="main",
                                 sha="deadbeef0001")
    assert out == {
        "tag": "preview-main",
        "version": "preview-main-deadbee",
        "title": "Preview: main (deadbee)",
    }, out


def t_dispatch_sanitizes_slash():
    out = m.compute_preview_meta("workflow_dispatch", ref="feat/preview-builds",
                                 sha="cafebabe1234")
    assert out["tag"] == "preview-feat-preview-builds"
    assert out["version"] == "preview-feat-preview-builds-cafebab"


def t_dispatch_strips_refs_heads():
    out = m.compute_preview_meta("workflow_dispatch", ref="refs/heads/main",
                                 sha="cafebabe1234")
    assert out["tag"] == "preview-main"


def t_dispatch_empty_ref_defaults_main():
    out = m.compute_preview_meta("workflow_dispatch", ref="",
                                 sha="0000000aaaa")
    assert out["tag"] == "preview-main"


# --- guards ------------------------------------------------------------------
def t_pr_requires_number():
    try:
        m.compute_preview_meta("pull_request", pr_number=None, sha="abc1234")
    except ValueError:
        return
    assert False, "expected ValueError for PR event with no number"


def t_unknown_event_raises():
    try:
        m.compute_preview_meta("push", sha="abc1234")
    except ValueError:
        return
    assert False, "expected ValueError for unsupported event"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_preview.py`
Expected: FAIL — `FileNotFoundError`/`ModuleNotFoundError` for `tools/preview_meta.py` (the module does not exist yet).

- [ ] **Step 3: Write minimal implementation**

Create `tools/preview_meta.py`:

```python
#!/usr/bin/env python3
"""Compute the identity (tag / version / title) of a preview build from the
triggering GitHub event. CI-only helper for .github/workflows/preview.yml; not
shipped (tools/ is never copied into the distributable). The pure
compute_preview_meta() is unit-tested in tests/test_preview.py; main() emits
`key=value` lines for $GITHUB_OUTPUT.

Usage (from the workflow):
  python tools/preview_meta.py --event pull_request --pr 42 \
      --sha "$SHA" >> "$GITHUB_OUTPUT"
  python tools/preview_meta.py --event workflow_dispatch --ref main \
      --sha "$SHA" >> "$GITHUB_OUTPUT"
"""
import argparse


def _sanitize_ref(ref):
    """A git ref made safe for a tag suffix: drop a refs/heads/ or refs/tags/
    prefix and replace every '/' with '-' (feat/x -> feat-x). Empty -> 'main'."""
    ref = (ref or "").strip()
    for prefix in ("refs/heads/", "refs/tags/"):
        if ref.startswith(prefix):
            ref = ref[len(prefix):]
    ref = ref.replace("/", "-")
    return ref or "main"


def compute_preview_meta(event_name, pr_number=None, ref=None, sha=None):
    """Return {'tag', 'version', 'title'} for a preview build.

    PR builds are keyed by PR number (one rolling pre-release per open PR);
    dispatch builds are keyed by the sanitized ref (one per branch, e.g.
    preview-main). The version embeds the 7-char short SHA so `iro --version`
    pinpoints the exact commit a tester is running.
    """
    short = (sha or "")[:7]
    if event_name == "pull_request":
        if not pr_number:
            raise ValueError("pull_request event requires a PR number")
        n = int(pr_number)
        return {
            "tag": f"preview-pr-{n}",
            "version": f"preview-pr{n}-{short}",
            "title": f"Preview: PR #{n} ({short})",
        }
    if event_name == "workflow_dispatch":
        r = _sanitize_ref(ref)
        return {
            "tag": f"preview-{r}",
            "version": f"preview-{r}-{short}",
            "title": f"Preview: {r} ({short})",
        }
    raise ValueError(f"unsupported event: {event_name!r}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", required=True)
    ap.add_argument("--pr")
    ap.add_argument("--ref")
    ap.add_argument("--sha", required=True)
    a = ap.parse_args(argv)
    meta = compute_preview_meta(a.event, a.pr, a.ref, a.sha)
    for key, value in meta.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_preview.py`
Expected: a line `ok t_...` per test, then `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add tools/preview_meta.py tests/test_preview.py
git commit -m "feat(ci): preview-build identity helper (tag/version/title)"
```

---

## Task 2: Helper CLI emits `$GITHUB_OUTPUT` lines (TDD)

This verifies `main()` prints the `key=value` lines the workflow appends to `$GITHUB_OUTPUT`.

**Files:**
- Test: `tests/test_preview.py` (add one test)
- (Implementation already written in Task 1 — `main()` exists; this task locks its contract with a test.)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_preview.py`, before the `if __name__` block:

```python
# --- main(): emits GITHUB_OUTPUT key=value lines -----------------------------
def t_main_pr_emits_output_lines():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.main(["--event", "pull_request", "--pr", "5", "--sha",
                "1234567abcdef"])
    lines = buf.getvalue().strip().splitlines()
    assert "tag=preview-pr-5" in lines, lines
    assert "version=preview-pr5-1234567" in lines, lines
    assert "title=Preview: PR #5 (1234567)" in lines, lines


def t_main_dispatch_ignores_empty_pr():
    # The workflow always passes --pr (empty on dispatch) and --ref (empty on
    # PR). main() must route on --event, not on which optional arg is empty.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.main(["--event", "workflow_dispatch", "--pr", "", "--ref", "main",
                "--sha", "deadbeef0001"])
    lines = buf.getvalue().strip().splitlines()
    assert "tag=preview-main" in lines, lines
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `python3 tests/test_preview.py`
Expected: PASS (the new tests too) — `main()` already routes on `--event` and ignores the empty optional. If `t_main_dispatch_ignores_empty_pr` fails, it means `compute_preview_meta` is branching on `pr_number` truthiness instead of `event_name`; fix the routing in `compute_preview_meta` to branch only on `event_name` (as written in Task 1) and re-run.

- [ ] **Step 3: Run the whole suite + lint**

Run: `python3 tools/run-tests.py`
Expected: `== test_preview.py` appears in the output and the run ends with `ALL TEST FILES PASS`.

Run: `python3 tools/lint.py`
Expected: ruff reports no errors for `tools/preview_meta.py` / `tests/test_preview.py`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_preview.py
git commit -m "test(ci): lock preview_meta main() GITHUB_OUTPUT contract"
```

---

## Task 3: Preview workflow — `meta` + `release` jobs

Create the workflow with the first two jobs: compute identity, then (re)create the rolling pre-release once (no matrix race).

**Files:**
- Create: `.github/workflows/preview.yml`

- [ ] **Step 1: Create the workflow with `meta` and `release` jobs**

Create `.github/workflows/preview.yml`:

```yaml
name: Preview
# Build a downloadable PRE-RELEASE binary for testing BEFORE a real release.
# Triggered by the 'preview' label on a PR (builds the PR branch) or by
# workflow_dispatch (builds a chosen ref, default main). Publishes a
# `preview-*` pre-release with public download URLs. preview-* tags never match
# v*, so release.yml and release-please are never triggered by a preview.
on:
  pull_request:
    types: [labeled, synchronize]
  workflow_dispatch:
    inputs:
      ref:
        description: "Branch/ref to build a preview from"
        default: main

permissions:
  contents: write          # create/upload the pre-release
  pull-requests: write     # the download-links PR comment

# Per preview target (PR number, or the dispatched ref). The group must use
# parse-time expressions only -- it cannot reference the meta job's computed tag.
concurrency:
  group: preview-${{ github.event.pull_request.number || inputs.ref }}
  cancel-in-progress: true

defaults:
  run:
    shell: bash

jobs:
  meta:
    # Only build for PRs that actually carry the 'preview' label: the labeled
    # event also fires for OTHER labels, and synchronize fires on every push.
    # workflow_dispatch is always allowed.
    if: >-
      github.event_name == 'workflow_dispatch' ||
      contains(github.event.pull_request.labels.*.name, 'preview')
    runs-on: ubuntu-latest
    outputs:
      tag: ${{ steps.id.outputs.tag }}
      version: ${{ steps.id.outputs.version }}
      title: ${{ steps.id.outputs.title }}
      sha: ${{ steps.id.outputs.sha }}
    steps:
      - uses: actions/checkout@v6
        with:
          # PR: build the PR head commit. Dispatch: build the chosen ref.
          ref: ${{ github.event_name == 'workflow_dispatch' && inputs.ref || github.event.pull_request.head.sha }}
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - name: Compute preview identity (tag/version/title/sha)
        id: id
        run: |
          SHA="$(git rev-parse HEAD)"
          python tools/preview_meta.py \
            --event "${{ github.event_name }}" \
            --pr "${{ github.event.pull_request.number }}" \
            --ref "${{ inputs.ref }}" \
            --sha "$SHA" >> "$GITHUB_OUTPUT"
          echo "sha=$SHA" >> "$GITHUB_OUTPUT"

  release:
    needs: meta
    runs-on: ubuntu-latest
    steps:
      - name: (Re)create the rolling pre-release for this preview tag
        env:
          GH_TOKEN: ${{ github.token }}
          GH_REPO: ${{ github.repository }}
        run: |
          # Rolling: drop any prior pre-release for this tag so target commit,
          # title and assets all reflect the NEW build, then recreate it empty.
          gh release delete "${{ needs.meta.outputs.tag }}" --cleanup-tag --yes || true
          gh release create "${{ needs.meta.outputs.tag }}" \
            --prerelease \
            --target "${{ needs.meta.outputs.sha }}" \
            --title "${{ needs.meta.outputs.title }}" \
            --notes "Automated preview build — not a release. Built from commit ${{ needs.meta.outputs.sha }}. Unsigned: expect a one-time SmartScreen/Gatekeeper warning on first run."
```

- [ ] **Step 2: Lint the YAML offline (best-effort sanity)**

Run:
```bash
python3 -c "import json,re,sys; t=open('.github/workflows/preview.yml').read(); print('non-empty:', bool(t.strip())); print('has meta job:', 'meta:' in t); print('has release job:', 'release:' in t)"
```
Expected: all three `True`. (Stdlib has no YAML parser; full validation happens when the workflow runs in Task 7.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/preview.yml
git commit -m "feat(ci): preview workflow — meta + rolling pre-release jobs"
```

---

## Task 4: Preview workflow — `build` matrix (test gate + publish assets)

Add the 3-OS build job, mirroring `release.yml` exactly, gated on the full test suite, uploading to the pre-release created in Task 3.

**Files:**
- Modify: `.github/workflows/preview.yml` (append the `build` job)

- [ ] **Step 1: Append the `build` job**

Add to `.github/workflows/preview.yml`, after the `release:` job (same indentation level, under `jobs:`):

```yaml
  build:
    needs: [meta, release]
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: windows-latest
            asset: iro-windows.zip
            built: dist/bin/iro.exe
            binary: iro.exe
            built_ui: dist/bin/iro-ui.exe
            binary_ui: iro-ui.exe
          - os: macos-latest
            asset: iro-macos.tar.gz
            built: dist/bin/iro
            binary: iro
            built_ui: dist/bin/iro-ui.app
            binary_ui: iro-ui.app
          - os: ubuntu-latest
            asset: iro-linux.tar.gz
            built: dist/bin/iro
            binary: iro
            built_ui: dist/bin/iro-ui
            binary_ui: iro-ui
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v6
        with:
          ref: ${{ needs.meta.outputs.sha }}
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - name: Run test suite (full gate — preview is green-built)
        run: python tools/run-tests.py
      - name: Install PyInstaller
        run: python -m pip install pyinstaller
      - name: Build + smoke-test the binary
        run: python tools/build-binary.py --version "${{ needs.meta.outputs.version }}"
      - name: Package the preview asset (binaries + .env.example)
        run: |
          mkdir staging
          cp -R "${{ matrix.built }}" "staging/${{ matrix.binary }}"
          cp -R "${{ matrix.built_ui }}" "staging/${{ matrix.binary_ui }}"
          cp .env.example staging/
          cd staging
          case "${{ matrix.asset }}" in
            *.zip)    python -m zipfile -c "../${{ matrix.asset }}" "${{ matrix.binary }}" "${{ matrix.binary_ui }}" .env.example ;;
            *.tar.gz) tar czf "../${{ matrix.asset }}" "${{ matrix.binary }}" "${{ matrix.binary_ui }}" .env.example ;;
            *)        echo "Unknown asset format: ${{ matrix.asset }}"; exit 1 ;;
          esac
      - name: Upload the asset to the pre-release
        env:
          GH_TOKEN: ${{ github.token }}
        run: gh release upload "${{ needs.meta.outputs.tag }}" "${{ matrix.asset }}" --clobber
```

- [ ] **Step 2: Sanity-check the file offline**

Run:
```bash
python3 -c "t=open('.github/workflows/preview.yml').read(); print('build job:', 'build:' in t); print('test gate:', 'tools/run-tests.py' in t); print('three assets:', all(a in t for a in ('iro-windows.zip','iro-macos.tar.gz','iro-linux.tar.gz')))"
```
Expected: all `True`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/preview.yml
git commit -m "feat(ci): preview build matrix — test gate + 3-OS pre-release assets"
```

---

## Task 5: Preview workflow — PR comment with download links

Add a job that posts/refreshes a single PR comment listing the three download URLs. PR trigger only.

**Files:**
- Modify: `.github/workflows/preview.yml` (append the `comment` job)

- [ ] **Step 1: Append the `comment` job**

Add to `.github/workflows/preview.yml`, after the `build:` job:

```yaml
  comment:
    needs: [meta, build]
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - name: Post/refresh the download-links comment
        env:
          GH_TOKEN: ${{ github.token }}
          GH_REPO: ${{ github.repository }}
          PR: ${{ github.event.pull_request.number }}
          TAG: ${{ needs.meta.outputs.tag }}
          REPO: ${{ github.repository }}
          VERSION: ${{ needs.meta.outputs.version }}
        run: |
          BASE="https://github.com/$REPO/releases/download/$TAG"
          BODY="$(cat <<EOF
          <!-- preview-build -->
          ### 🔬 Preview build \`$VERSION\`

          Download (unsigned — one-time SmartScreen/Gatekeeper warning on first run):

          - **Windows:** $BASE/iro-windows.zip
          - **macOS:** $BASE/iro-macos.tar.gz
          - **Linux:** $BASE/iro-linux.tar.gz

          Rebuilt automatically on every push to this PR. \`iro --version\` prints \`$VERSION\`.
          EOF
          )"
          # --edit-last reuses the bot's previous preview comment; --create-if-none
          # posts the first one (gh >= 2.61, present on GitHub-hosted runners).
          gh pr comment "$PR" --body "$BODY" --edit-last --create-if-none
```

- [ ] **Step 2: Sanity-check the file offline**

Run:
```bash
python3 -c "t=open('.github/workflows/preview.yml').read(); print('comment job:', 'comment:' in t); print('edit-last:', '--edit-last' in t and '--create-if-none' in t)"
```
Expected: both `True`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/preview.yml
git commit -m "feat(ci): preview workflow — PR comment with download links"
```

---

## Task 6: Cleanup workflow — delete a PR's preview on close

**Files:**
- Create: `.github/workflows/preview-cleanup.yml`

- [ ] **Step 1: Create the cleanup workflow**

Create `.github/workflows/preview-cleanup.yml`:

```yaml
name: Preview cleanup
# When a PR closes (merged or not), delete its preview pre-release + tag so the
# Releases page and the tag namespace stay tidy. Dispatch previews (preview-<ref>)
# are rolling and overwritten on the next dispatch, so they need no per-PR hook.
on:
  pull_request:
    types: [closed]

permissions:
  contents: write

jobs:
  delete-preview:
    runs-on: ubuntu-latest
    steps:
      - name: Delete the PR's preview pre-release and tag
        env:
          GH_TOKEN: ${{ github.token }}
          GH_REPO: ${{ github.repository }}
          TAG: preview-pr-${{ github.event.pull_request.number }}
        run: |
          # No-op (|| true) when the PR never had a preview.
          gh release delete "$TAG" --cleanup-tag --yes || true
```

- [ ] **Step 2: Sanity-check the file offline**

Run:
```bash
python3 -c "t=open('.github/workflows/preview-cleanup.yml').read(); print('closed trigger:', 'closed' in t); print('cleanup-tag:', '--cleanup-tag' in t)"
```
Expected: both `True`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/preview-cleanup.yml
git commit -m "feat(ci): delete a PR's preview pre-release on close"
```

---

## Task 7: Docs + the one-time `preview` label, then integration verification

**Files:**
- Modify: `src/docs/wiki/Build-and-maintenance.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the wiki subsection**

In `src/docs/wiki/Build-and-maintenance.md`, immediately after the paragraph that ends "...stamped into `iro --version` at build time.)" (the `CHANGELOG.md`/`version.txt` paragraph, around line 48) and before "## Round-trips that keep secrets/paths out of git", insert:

```markdown
## Preview builds (test before releasing)

Sometimes a build must be tested *before* a real release — a single PR, or
`main` after several PRs merged with no release yet. The **Preview** workflow
publishes real, downloadable binaries as a GitHub **pre-release** (public
download URLs, but never the "Latest" slot), built green (full test gate runs
first).

- **From a PR:** add the **`preview`** label to the PR. Every push to the
  labeled PR (re)builds a `preview-pr-<N>` pre-release for all three OSes, and a
  PR comment lists the download links. Closing the PR deletes the pre-release.
- **From `main` (or any branch):** Actions → **Preview** → *Run workflow* →
  pick the ref (default `main`). Publishes a rolling `preview-<ref>` pre-release.

Preview tags are `preview-*`, never `v*`, so they never trigger `release.yml` or
disturb the release-please Release PR. `iro --version` of a preview binary prints
e.g. `preview-pr42-0123abc` so a tester knows the exact commit. Preview binaries
are unsigned, same one-time SmartScreen/Gatekeeper warning as releases.

> One-time setup: the `preview` label must exist in the repo —
> `gh label create preview --color FFA500 --description "Build a downloadable preview binary"`.
>
> Fork PRs cannot publish previews (GitHub gives fork-PR workflows a read-only
> token); the team's same-repo branch workflow is unaffected.
```

- [ ] **Step 2: Add the CLAUDE.md sentence**

In `CLAUDE.md`, in the "Standalone binary (PyInstaller)" subsection, at the end (after the sentence "Unsigned binaries: SmartScreen/Gatekeeper show a one-time 'run anyway' warning."), append:

```markdown
A separate **preview** channel (`.github/workflows/preview.yml`, helper
`tools/preview_meta.py`) publishes pre-release binaries for testing ahead of a
real release — triggered by the `preview` label on a PR or by `workflow_dispatch`
against a ref. Its tags are `preview-*` (never `v*`), so it never triggers
`release.yml` or release-please; `preview-cleanup.yml` deletes a PR's pre-release
on close.
```

- [ ] **Step 3: Run the full suite + lint one more time**

Run: `python3 tools/run-tests.py`
Expected: ends with `ALL TEST FILES PASS` (including `test_preview.py`).

Run: `python3 tools/lint.py`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/docs/wiki/Build-and-maintenance.md CLAUDE.md
git commit -m "docs: document the preview-build channel"
```

- [ ] **Step 5: Create the `preview` label (one-time, before first use)**

Run:
```bash
gh label create preview --color FFA500 --description "Build a downloadable preview binary" || true
```
Expected: label created (or "already exists" — harmless).

- [ ] **Step 6: Push the branch and open a PR**

```bash
git push -u origin feat/preview-builds
gh pr create --fill --base main
```

- [ ] **Step 7: Integration verification — PR preview**

On the PR you just opened, add the `preview` label:
```bash
gh pr edit --add-label preview
```
Then verify (Acceptance #1–#3):
- `gh run list --workflow=Preview` shows a run that goes green.
- `gh release view preview-pr-<N>` exists, is marked **Pre-release**, and lists `iro-windows.zip`, `iro-macos.tar.gz`, `iro-linux.tar.gz`.
- The PR has a comment with the three download links.
- Download the macOS asset, extract, run `./iro --version` → prints `preview-pr<N>-<shortsha>` matching `git rev-parse --short HEAD`.
- Push an empty commit (`git commit --allow-empty -m "chore: bump preview" && git push`) → the **same** `preview-pr-<N>` release updates in place (no second pre-release appears in `gh release list`).

- [ ] **Step 8: Integration verification — dispatch + separation + cleanup**

- Dispatch (Acceptance #5): `gh workflow run Preview -f ref=main` → after it finishes, `gh release view preview-main` exists as a pre-release with the three archives.
- Negative gate (Acceptance #4): on a throwaway unlabeled PR, push a commit → confirm **no** Preview run starts; add a non-`preview` label → still no run.
- Separation (Acceptance #7): `gh release list` shows no new `v*` release; `gh pr list --search "release-please"` shows the Release PR unchanged by any preview run.
- Cleanup (Acceptance #6): close the test PR (`gh pr close <N>`) → `gh release view preview-pr-<N>` returns "release not found" and `git ls-remote --tags origin "preview-pr-<N>"` is empty.

---

## Self-Review

**Spec coverage:**
- Pre-release mechanism, public URLs → Task 3 (`release` job, `--prerelease`), Task 4 (upload). ✓
- PR-label trigger + dispatch trigger → Task 3 (`on:` + `meta.if`). ✓
- `preview-*` ≠ `v*` separation → Task 3 naming (helper from Task 1) + verified in Task 7 Step 8. ✓
- Rolling tag / no accumulation → Task 3 (`release delete`+`create`), Task 4 (`upload --clobber`), verified Task 7 Step 7. ✓
- Unambiguous `iro --version` → Task 1 (`version` embeds short SHA), verified Task 7 Step 7. ✓
- Full test gate before publish → Task 4 (`run-tests.py` before build). ✓
- PR comment with links → Task 5. ✓
- Cleanup on PR close → Task 6, verified Task 7 Step 8. ✓
- Fork-PR caveat, label one-time setup → Task 7 docs + Step 5. ✓
- All 3 OS archives incl. `.env.example` → Task 4 matrix (mirrors `release.yml`). ✓

**Placeholder scan:** No "TBD"/"handle edge cases"/"similar to" — every code/YAML block is complete and self-contained. ✓

**Type/name consistency:** `compute_preview_meta(event_name, pr_number, ref, sha)` and its keys `tag`/`version`/`title` are used identically in Tasks 1, 2, and consumed as `steps.id.outputs.{tag,version,title}` / `needs.meta.outputs.{tag,version,title,sha}` in Tasks 3–6. The four `--event/--pr/--ref/--sha` CLI flags match between `main()` (Task 1) and the workflow call (Task 3). ✓
```
