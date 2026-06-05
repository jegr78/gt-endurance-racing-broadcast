# Release Automation (release-please) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standing release-please Release PR replaces "remember to tag" — merging it creates the tag, the GitHub release, and (via a workflow_dispatch chain) the binary build.

**Architecture:** New `release-please.yml` workflow (push→main) maintains the Release PR from Conventional Commits; on merge it creates tag+release and dispatches the existing `release.yml` (tags created with GITHUB_TOKEN don't trigger on-tag workflows). `release.yml` only gains a `workflow_dispatch:` trigger. Version source of truth stays the git tag.

**Tech Stack:** GitHub Actions, `googleapis/release-please-action@v4` (release-type `simple`), `gh` CLI.

**Spec:** `docs/superpowers/specs/2026-06-05-release-automation-design.md`

**Workspace:** ALL work happens in a dedicated worktree on branch `feat/release-automation` — the main checkout at `/Users/jegr/Downloads/IRO_Broadcast_Setup` is in parallel use and must not be touched.

---

### Task 1: Worktree + branch

- [ ] **Step 1: Create the worktree**

```bash
git -C /Users/jegr/Downloads/IRO_Broadcast_Setup worktree add -b feat/release-automation /Users/jegr/Downloads/IRO-wt-release-automation main
cd /Users/jegr/Downloads/IRO-wt-release-automation && git status
```

Expected: new worktree on fresh branch `feat/release-automation`, clean tree. All later tasks run from `/Users/jegr/Downloads/IRO-wt-release-automation`.

---

### Task 2: release-please config + manifest

**Files:**
- Create: `release-please-config.json`
- Create: `.release-please-manifest.json`

- [ ] **Step 1: Write `release-please-config.json`**

```json
{
  "$schema": "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json",
  "release-type": "simple",
  "include-component-in-tag": false,
  "packages": {
    ".": {}
  }
}
```

(`include-component-in-tag: false` keeps tags as plain `vX.Y.Z` — the existing `release.yml`/operator docs depend on that shape. `simple` maintains `version.txt` + `CHANGELOG.md`; both are informational, the tag stays authoritative.)

- [ ] **Step 2: Write `.release-please-manifest.json`** (seed = the existing release)

```json
{
  ".": "0.1.0"
}
```

- [ ] **Step 3: Validate both parse**

Run: `python3 -c "import json; json.load(open('release-please-config.json')); json.load(open('.release-please-manifest.json')); print('json ok')"`
Expected: `json ok`

- [ ] **Step 4: Commit**

```bash
git add release-please-config.json .release-please-manifest.json
git commit -m "feat(ci): release-please config seeded at v0.1.0"
```

---

### Task 3: The release-please workflow

**Files:**
- Create: `.github/workflows/release-please.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: release-please
on:
  push:
    branches: [main]
permissions:
  contents: write
  pull-requests: write
  actions: write          # gh workflow run (the dispatch step) needs this
jobs:
  release-please:
    runs-on: ubuntu-latest
    steps:
      - uses: googleapis/release-please-action@v4
        id: release
      # Tags created with the default GITHUB_TOKEN do NOT trigger on-tag
      # workflows -- without this dispatch, merging the Release PR would
      # produce a tag + release with no binaries.
      - name: Build the binaries for the new tag
        if: ${{ steps.release.outputs.release_created }}
        env:
          GH_TOKEN: ${{ github.token }}
        run: >
          gh workflow run release.yml
          --ref "${{ steps.release.outputs.tag_name }}"
          --repo "${{ github.repository }}"
```

(No checkout step needed — `gh workflow run --repo …` works without a local clone. The action reads `release-please-config.json` + `.release-please-manifest.json` from the repo by default.)

- [ ] **Step 2: Sanity-check YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release-please.yml')); print('yaml ok')" 2>/dev/null || echo "pyyaml missing — visual indent review"`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release-please.yml
git commit -m "feat(ci): release-please workflow with dispatch chain to the binary build"
```

---

### Task 4: `workflow_dispatch` trigger on release.yml

**Files:**
- Modify: `.github/workflows/release.yml` (lines 1–4)

- [ ] **Step 1: Add the trigger**

The file currently starts:

```yaml
name: Release
on:
  push:
    tags: ["v*"]
```

Change the `on:` block to:

```yaml
name: Release
on:
  push:
    tags: ["v*"]
  workflow_dispatch:        # dispatched by release-please.yml with --ref <tag>
```

Nothing else changes — when dispatched with `--ref vX.Y.Z`, `github.ref_name` is the tag, so `build-binary.py --version "${{ github.ref_name }}"` stamping works unchanged; `gh release create … || true` is already idempotent (release-please created the release first) and the upload uses `--clobber`.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "feat(ci): release.yml accepts workflow_dispatch from release-please"
```

---

### Task 5: Docs (wiki + CLAUDE.md)

**Files:**
- Modify: `src/docs/wiki/Build-and-maintenance.md` (the "## Releases (standalone binaries)" section)
- Modify: `CLAUDE.md` (the Releases sentence in the Standalone-binary section)

- [ ] **Step 1: Rework the wiki Releases section**

Read the section first. Replace its body (keep the heading) with:

````markdown
Operators download `iro` from GitHub Releases and never need Python.

**Primary flow — merge the Release PR:** a release-please bot maintains a
standing PR that collects every `feat:`/`fix:` commit since the last release,
with the computed next version and changelog. When an event approaches and
`main` is in a good state, **merge that PR** — this creates the `vX.Y.Z` tag,
the GitHub release with notes, and kicks off the binary build that uploads
`iro-windows.zip` / `iro-macos.tar.gz` / `iro-linux.tar.gz` (each contains the
`iro` binary plus `.env.example`; on first run the binary copies it to `.env`).
No Release PR open = nothing release-worthy happened (`docs:`/`ci:` commits
don't count). The binaries are unsigned — operators see a one-time
SmartScreen/Gatekeeper warning (documented on the setup page).

**Escape hatch — manual tag:** pushing a semver tag still works exactly as
before and skips the bot:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

`CHANGELOG.md` and `version.txt` in the repo root are maintained by the bot;
the authoritative version is always the git tag (stamped into `iro --version`
at build time).
````

- [ ] **Step 2: Update CLAUDE.md**

In the Standalone-binary section, replace the sentence beginning `Releases: push a` so it reads:

> Releases: merge the standing **release-please** Release PR (or push a `v*`
> tag manually — both work) — `.github/workflows/release.yml` tests, builds,
> smoke-tests and uploads `iro-windows.zip` / `iro-macos.tar.gz` /
> `iro-linux.tar.gz` (each contains the `iro` binary + `.env.example`; on
> first run the frozen binary copies it to `.env` — see `ensure_env_file`).
> release-please tags via GITHUB_TOKEN, which cannot trigger on-tag workflows,
> so `release-please.yml` dispatches `release.yml` explicitly.

- [ ] **Step 3: Commit**

```bash
git add src/docs/wiki/Build-and-maintenance.md CLAUDE.md
git commit -m "docs: release flow is merge-the-release-PR; manual tag stays the escape hatch"
```

---

### Task 6: Verify, push, PR, merge

- [ ] **Step 1: Full suite + build verify** (nothing should be affected — CI/doc change only)

Run: `python3 tools/run-tests.py && python3 tools/build.py`
Expected: `ALL TEST FILES PASS`, build self-verify OK.

- [ ] **Step 2: Push the branch and open the PR**

```bash
git push -u origin feat/release-automation
gh pr create --title "feat(ci): automated release management via release-please" \
  --body "$(cat <<'EOF'
Implements docs/superpowers/specs/2026-06-05-release-automation-design.md:
standing Release PR via release-please (simple type, tag stays authoritative),
workflow_dispatch chain so the tag actually builds binaries, docs updated.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Wait for CI green on the PR**

Run: `gh pr checks --watch`
Expected: all 5 required checks pass.

- [ ] **Step 4: Squash-merge with a conventional title** (the squash title lands on main and feeds release-please)

```bash
gh pr merge --squash --subject "feat(ci): automated release management via release-please"
```

---

### Task 7: Post-merge verification (acceptance 1)

- [ ] **Step 1: The merge push triggers release-please.yml — watch it**

```bash
gh run list --workflow release-please.yml --limit 1     # grab id
gh run watch <id> --exit-status
```

Expected: success.

- [ ] **Step 2: The first Release PR exists and proposes v0.2.0**

```bash
gh pr list --search "release-please" --json number,title,headRefName
```

Expected: one open PR titled like `chore(main): release 0.2.0` (branch `release-please--branches--main`). Its diff touches only `CHANGELOG.md`, `version.txt`, `.release-please-manifest.json`; the changelog lists the Windows-test `feat:`/`fix:` commits plus this feature. **This is expected to be v0.2.0 and large — per spec.**

- [ ] **Step 3: STOP — do not merge the Release PR**

Merging it cuts the real `v0.2.0` release. That is the user's call (event timing). Report the PR number/contents and hand over. (Full-chain acceptance — tag, dispatched build, three assets — happens whenever the user merges it; if the user wants it validated immediately, merging now is safe: main is green and v0.2.0 content is exactly the Windows-test improvements.)

- [ ] **Step 4: Clean up the worktree**

```bash
git -C /Users/jegr/Downloads/IRO_Broadcast_Setup worktree remove /Users/jegr/Downloads/IRO-wt-release-automation
git -C /Users/jegr/Downloads/IRO_Broadcast_Setup branch -d feat/release-automation 2>/dev/null || true
```

(Branch delete may fail if GitHub auto-deleted it on merge — fine.)

---

## Self-review notes (spec coverage)

- Workflow + permissions (incl. `actions: write`) → Task 3. Dispatch chain → Task 3.
- release.yml one-line trigger change, nothing else → Task 4.
- Config/manifest/`version.txt`-is-informational → Task 2 (+ wiki text Task 5).
- Docs (wiki primary-flow rework, manual tag escape hatch, CLAUDE.md) → Task 5.
- Expected-first-run note (immediate v0.2.0 PR) → Task 7 step 2.
- Acceptance 1 → Task 7; acceptance 2–4 occur on the user-gated Release-PR merge (documented in Task 7 step 3).
