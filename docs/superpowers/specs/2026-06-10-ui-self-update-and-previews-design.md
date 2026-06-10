# UI self-update + preview installs — design

**Issue:** #34 — "UI: Update Version — No update, just link to GitHub Releases"
**Date:** 2026-06-10
**Status:** Design (approved in chat, pending written-spec review)

## Problem

The CLI binary self-updates: `iro update` (`src/scripts/update.py`) downloads the
platform archive from GitHub Releases, swaps the running binary in place, and
reinstalls the `iro-ui` launcher alongside it. The Control Center UI does **not**
— its `/api/update` endpoint is deliberately *check-only* (`update_check_data`,
a thin wrapper over the same `classify()`), and the amber Home banner / sidebar
version-note merely link to the Releases page. There is no UI path that triggers
an actual update.

The maintainer's expectation: a one-click update from the UI, while still being
able to **see what's included** (release notes) before installing. Additionally,
offer the **preview builds** (CI pre-releases per PR / per branch), not only the
latest stable release, so they can be tested from the UI without manual download.

## Constraints the design must respect

- **`/releases/latest` excludes pre-releases by GitHub design** — preview builds
  never appear there. Listing previews requires `/releases` (the list endpoint),
  filtered to `prerelease: true`.
- **Previews are not semver-comparable.** Their tags are `preview-pr-<n>` /
  `preview-<ref>` and versions `preview-pr<n>-<sha>` / `preview-<ref>-<sha>`
  (`tools/preview_meta.py`). `parse_version()` returns `None` for them, so the
  existing "is a newer release out?" semver compare cannot rank them. There can
  be **several at once** (one rolling pre-release per open PR, one per branch).
  → "install a preview" is *install exactly this tag*, never a version compare.
- **All shipped scripts/docs are English only** (project hard rule).
- **Edit only under `src/`** (plus this spec); `dist/`/`runtime/` are generated.
- **Tests must run on any machine and in CI** — pure logic, injected fetchers,
  no network. Mirror the existing `tests/test_update.py` style (pure functions,
  `opener=`/`fetch=` injection).
- The binary swap of a *running* process is safe until restart on all three OSes
  (macOS/Linux keep the old inode through `os.replace`; Windows uses the existing
  rename-trick: a running `.exe` can be renamed but not overwritten). The UI
  therefore never needs to stop itself to update — it finishes the job and asks
  the operator to restart the Control Center.

## Chosen approach: thin UI over an extended CLI updater

The UI's universal pattern is: an op maps to an `iro <subcommand>` argv, spawned
as a **job** with a streamed live log (`src/ui/ui_ops.py` `OPS`/`PARAMS` +
`src/ui/ui_jobs.py`). `iro update` is already a registered ONESHOT. So the
install actions reuse that machinery wholesale; `update.py` gains the missing
pieces (a `--tag` install path + a pure prerelease-list function) and `iro.py`
exposes the listing + notes to the UI.

Rejected alternatives:
- **UI-native updater** (the server downloads + swaps in-process): the very
  process serving the page swaps its own binary, loses the live-log UX, diverges
  from every other op, and is harder to test. Rejected.
- **Minimal** (UI just runs `iro update --yes`, no notes, no previews): does not
  meet the chosen flow (notes + button) and drops previews entirely. Rejected.

## Components

### 1. CLI updater — `src/scripts/update.py`

**New `--tag <tag>` install path.** When `--tag` is given, the updater installs
*exactly* that release rather than computing the latest-stable update:
- Fetch the single release via `GET /releases/tags/<tag>` (a new
  `fetch_release_by_tag(tag, opener=)` mirroring `fetch_latest`).
- A pure `classify_tag(release, platform)` → one of:
  - `("install", tag, url)` — platform asset present, install it.
  - `("building", tag, None)` — release exists but this platform's asset is not
    uploaded yet.
  - `("error", message, None)` — malformed release data.
  No semver compare (previews are incomparable, and re-installing the same or an
  "older" stable tag via an explicit `--tag` is a legitimate downgrade/pin).
- On `("install", …)` reuse the existing `download → extract_binary →
  swap_plan/perform → install_ui` plumbing unchanged.
- A bogus tag → `/releases/tags/<tag>` 404 → friendly "no such release" exit.

**New pure listing for the UI.** `classify_prereleases(releases, platform)`
takes the parsed `GET /releases` list and returns, for each `prerelease: true`
entry, a dict:
```
{tag, version, title, commit, published_at, asset_url|None, notes}
```
where `asset_url is None` means "still building" (no platform asset yet),
`version`/`title` come from the tag/name, `commit` is the release's
`target_commitish` (falling back to the short SHA embedded in the version
string, e.g. the `abc1234` in `preview-pr42-abc1234`), and `notes` is the
release body markdown. Stable releases are filtered out (the regular update path covers
those). Paired with `fetch_releases(per_page=N, opener=)` (GET `/releases`).

All new functions are pure (data in → data out) except the two thin
`fetch_*` HTTP helpers, exactly like the current file.

### 2. Backend wiring — `src/iro.py`

- Extend `update_check_data(...)` to include `notes` (the latest release's body
  markdown) so the regular-update dialog can render it. Single source of truth
  stays `scripts/update.py`.
- Add a `preview_list_data(fetch=None)` wrapper over `classify_prereleases`,
  exposed as a new context provider `previews`, with a server-side cached
  wrapper analogous to `update_check_cached` (served on demand, never from the
  status poll).
- `--tag`/`--yes` already flow through the ONESHOT path (argparse in
  `update.py`; `iro` injects `--current`). No dispatch change needed beyond
  confirming `update` stays in `ONESHOTS`.

### 3. UI server + op registry — `src/ui/ui_server.py`, `src/ui/ui_ops.py`

- New GET endpoint `/api/previews` → `ctx["previews"](force)` (on-demand,
  server-cached like `/api/update`); returns the prerelease list. The endpoint
  is always available; the UI gates its *visibility* behind the opt-in.
- New ops in `ui_ops.OPS`:
  - `"update"` → `["update", "--yes"]`
  - `"update-preview"` → `["update", "--yes"]` with a `tag` param appended as
    `["--tag", <tag>]` via `PARAMS`.
- New `PARAMS["update-preview"] = {"tag": _tag_arg}` where `_tag_arg` validates
  against `^(v\d|preview-)[\w.-]+$` (defence against argv junk; the UI only ever
  sends a tag it received from `/api/previews`).

### 4. UI — `src/ui/control-center.html`

**Regular update (Home banner / sidebar note).** Clicking opens a **dialog**:
- Rendered release notes (reuse `src/ui/mdrender.py`) for the latest tag.
- An **"Update now"** button → starts the `update` job, shows its live log.
- "View on GitHub ↗" kept as a secondary link.
- **Service warning (non-blocking):** if the status poll shows relay / OBS /
  Companion running, the dialog shows a notice — "Updating swaps the binary and
  needs a restart — don't do this during a live show." The button stays enabled.

**Preview section (Help/About view, behind opt-in).** In the existing
Help/Guides view (next to version + issue link):
- An opt-in toggle "Show preview / testing builds", persisted in `localStorage`
  (default **off**), keeping the server stateless.
- When on: fetch `/api/previews`, list each pre-release (title, commit, date,
  platform availability). Each row has **"Install"**, which opens the same
  notes-dialog (showing that preview's notes + the same service warning) and on
  confirm runs the `update-preview` job for its `tag`.
- "Still building" entries show disabled with a hint.

**Restart UX (chosen: notice only, no auto-relaunch).** When an update/preview
job finishes, a prominent message: "Update installed → please quit and reopen
the Control Center." No automatic restart.

## Data flow

```
Regular update:
  Home banner click
    → GET /api/update (cached)  → {current, latest, notes, releases_url, …}
    → dialog renders notes (+ service warning from last status poll)
    → "Update now" → POST start job op=update
    → ui_jobs spawns `iro update --yes` → live log via SSE
    → job ends → "restart Control Center" notice

Preview install:
  Help view, opt-in on
    → GET /api/previews (cached) → [ {tag, title, commit, date, asset_url, notes}, … ]
    → row "Install" → dialog renders that preview's notes (+ service warning)
    → confirm → POST start job op=update-preview tag=<tag>
    → ui_jobs spawns `iro update --yes --tag <tag>` → live log
    → job ends → "restart Control Center" notice
```

## Error handling

- **Offline / GitHub unreachable:** `/api/update` and `/api/previews` already
  return `{ok:false,error}` on exception; the dialog/list shows the error, no
  job starts.
- **Tag still building:** `classify_tag` → `("building", …)`; `iro update --tag`
  exits with the existing "binaries still building — retry" message, surfaced in
  the job log. The preview list marks such rows non-installable up front.
- **Bogus tag:** 404 → "no such release"; the validator also rejects malformed
  tags before a job is spawned.
- **Swap failure:** unchanged — `update.py` already exits with a restore hint;
  the job log carries it.
- **`iro-ui` reinstall hiccup:** unchanged — best-effort, never undoes the `iro`
  swap (`install_ui` is already wrapped).

## Testing

- `tests/test_update.py` (pure, injected fetchers):
  - `classify_tag`: install / building / error / unknown-platform-asset.
  - `classify_prereleases`: filters stable out, marks "building" when no platform
    asset, extracts commit/title/notes, empty list → `[]`.
  - `--tag` argument plumbing (parsed, drives `fetch_release_by_tag`).
- `tests/test_ui_ops.py`: `build_argv("update")`, `build_argv("update-preview",
  {"tag": …})` valid + invalid tag (raises `ValueError`).
- `tests/test_ui_server.py`: `/api/previews` route returns the provider payload;
  error path returns `{ok:false}`.
- Extend the existing `/api/update` / `update_check_data` tests for the added
  `notes` field.
- Run `python3 tools/run-tests.py` + `python3 tools/lint.py`; then
  `python3 tools/build.py` (verify step) since UI files ship.

## Out of scope

- Auto-relaunch of the Control Center after update (operator restarts manually).
- Stopping services automatically before an update (warn-only, per decision).
- Background/automatic updating (the check stays on-demand; install stays a
  deliberate click).
- A CLI affordance for *listing* previews (the UI is the consumer; `iro update
  --tag` is the only new CLI surface, and it is independently useful).

## Review follow-ups (PR #35, high-effort code review)

A post-implementation review surfaced issues that were fixed in the same PR;
these supersede the original design where they differ:

- **Single `update` op (was `update` + `update-preview`).** Two distinct op
  names let the job manager run both concurrently — two binary swaps racing. A
  preview install is now the SAME `update` op with an optional `tag` param, so
  one op name serialises them (`ui_jobs` refuses a second concurrent run).
- **UI tag allowlist is preview-only.** `_tag_arg`'s regex is now
  `^preview-[\w.-]+\Z`. A regular update sends no tag (→ latest); the UI never
  needs to install a specific *stable* tag, so rejecting `vX.Y.Z` closes a
  crafted-`/api/op/update {tag:"v1.0.0"}` downgrade vector. (`iro update --tag
  <vX.Y.Z>` on the CLI is still unrestricted — that boundary is the shell.)
- **Release notes ARE rendered (hardened mdrender), not plaintext.** The
  original design deferred to plaintext for safety. Instead `mdrender`'s link
  rule was hardened (href HTML-escaped + scheme allowlist; `javascript:`/`data:`
  dropped), making it safe for PR-authored notes. The server returns a rendered,
  sanitised `notes_html`; the dialog uses it via `innerHTML` with a plaintext
  (`textContent`) fallback when rendering is unavailable. This also hardens the
  existing docs-rendering path.
- **Restart prompt gated on a real swap.** The "Update installed — restart"
  alert now fires only when the job log contains the updater's `updated to <tag>`
  marker, not merely on exit 0 (an "already up to date" run also exits 0).
- **Preview list loads lazily.** Fetched when the Help view is opened (if opted
  in), not eagerly at startup, with an in-flight guard against overlapping loads.
- **Robustness:** `--tag` honours `--check` (dry-run); a non-writable binary dir
  fails with a clear message instead of a traceback; `_commit_of` only trusts
  `target_commitish` when it parses as a hex SHA (GitHub stores a branch name
  there for branch-targeted releases). Shared `_get_json` / `_find_asset_url`
  helpers de-duplicate the fetch and asset-scan boilerplate.
