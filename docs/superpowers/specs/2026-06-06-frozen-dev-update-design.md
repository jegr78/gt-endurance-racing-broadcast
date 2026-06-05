# `iro update` for frozen dev binaries

**Date:** 2026-06-06
**Status:** approved design
**Extends:** `2026-06-05-self-update-design.md`

## Problem

The self-update dev guard refuses whenever `parse_version(current)` is `None`,
with the message "running from source — update with `git pull` instead." That
guard was designed for the repo checkout (`python3 src/iro.py update`), but
`tools/build-binary.py` stamps `dev` when run without `--version`, so a
**locally built frozen binary** hits the same guard — and the `git pull` hint
is wrong there (no repo sits next to the binary, and the binary cannot be
rebuilt by pulling).

## Decision

A frozen binary reporting `dev` offers an update to the **latest GitHub
release** (`update: dev -> vX.Y.Z`, normal confirmation prompt). The dev
version is incomparable, so no semver compare happens — a dev binary always
gets the newest release offered; running `iro update` is the way back onto
the release track. Only the true repo mode (not frozen) keeps the
`git pull` message.

Frozen detection is `getattr(sys, "frozen", False)` inside `update.py`
itself: frozen one-shots run **in-process** in the binary (importlib), repo
mode runs under a normal `python3` — no new injected argument from `iro.py`
needed, the module stays self-contained.

## Changes

### 1. `src/scripts/update.py`

- `classify(release, platform, current, frozen=False)` — new parameter.
  When `cur is None`:
  - `frozen=False` → `('dev', None, None)` (unchanged).
  - `frozen=True` → parse the release tag (malformed → `('error', ...)`),
    look up the platform asset → `('update', tag, url)` or
    `('building', tag, None)`. Never `('up-to-date', ...)` for dev.
- `main()` dev guard becomes
  `if parse_version(a.current) is None and not getattr(sys, "frozen", False)`;
  the message stays the `git pull` line (correct in repo mode).
- `main()` passes the frozen flag into `classify()`.
- Update the decision table in the `classify()` docstring.

### 2. Tests (`tests/test_update.py`)

Three new pure-function cases:

- frozen dev + release with platform asset → `('update', tag, url)`.
- frozen dev + release without the platform asset → `('building', tag, None)`.
- non-frozen dev → `('dev', None, None)` (regression for the repo guard).

### 3. Docs

None. Operator behavior for release binaries is unchanged (their version is
always `vX.Y.Z`; the new path is never taken there). Wiki text already says
"update with `iro update`", which now also holds for dev binaries.

## Explicit decisions

- **No `git describe` stamping** in `tools/build-binary.py` — locally built
  binaries stay `dev` on purpose; `iro update` is the way back to releases
  (user decision 2026-06-06).
- **No `--frozen` CLI flag injected by `iro.py`** — `sys.frozen` is visible
  in-process; a flag would add coupling for nothing.
- A dev binary re-offers the same latest release on every run (no
  "up to date" state) — accepted; harmless and explicit.

## Acceptance

1. Frozen binary built with `--version dev` → `iro update --check` reports
   `update available: dev -> vX.Y.Z`; `iro update` prompts and swaps.
2. `python3 src/iro.py update` (repo mode) → still refuses with the
   `git pull` hint.
3. Release binaries (`vX.Y.Z`) behave exactly as before.
