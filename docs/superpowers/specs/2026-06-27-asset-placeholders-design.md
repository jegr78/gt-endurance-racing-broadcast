# Neutral placeholders for missing broadcast assets

**Status:** Design approved (brainstorming) — pending implementation plan.
**Date:** 2026-06-27

## Problem

Not every league fills every asset in its Sheet *Assets* tab. Weather overlays are
the canonical example: a league that never reports weather simply omits those rows.
But the OBS scene collection still references those image sources
(`__RACECAST_GRAPHICS__/Weather Sunny.png`, …), so on import OBS rightly flags them as
missing and shows a broken/black source. Today `setup-assets.py` only prints a
`WARNING`; the producer is left with broken sources for assets they intentionally do
not use. The same applies to the Intro/Outro clips (`intro.mp4`/`outro.mp4`).

## Goal

Ship neutral, byte-small placeholder assets inside the binary and drop them — under
the expected filenames — into a profile's `graphics/`/`media/` dir whenever a
referenced asset is missing, so OBS shows a neutral source instead of a broken one.
A transparent 1920×1080 PNG for graphics; a black, silent 5 s 1080p clip for media.

## Key insight: the authoritative "expected" set is the OBS collection, not the Sheet

`get-graphics.py` only iterates over what the *Assets* tab defines, so a graphic that
is **never in the Sheet** (the weather case) is never seen there. The authoritative
list of expected graphic filenames is the set of `__RACECAST_GRAPHICS__/<name>.png`
references in the tokenized OBS collection — which `setup-assets.py` already extracts
by regex. Both the download step and the localize step must derive the expected set
from that collection so the never-in-Sheet case is covered.

## Decisions (from brainstorming)

1. **Trigger point: both** — a shared helper invoked from `get-graphics.py` /
   `get-media.py` (download) **and** `setup-assets.py` (localize). Localize is the
   authoritative, collection-driven net right before OBS import; the download step
   fills proactively so the folder is complete after `racecast graphics`/`media`.
2. **Status honesty: silent** — a placeholder counts as a present file. No changes to
   `event.py` / `event status` / preflight. The only signal is a write-time NOTE in
   the command output. (Accepted risk: a failed download of a *Sheet-defined* graphic
   is masked by a transparent placeholder; the write-time NOTE is the mitigation.)
3. **Placeholder MP4 is committed** (not generated per binary build) — avoids an
   ffmpeg dependency in the release CI, consistent with `tools/fetch-flags.py`.
4. **Clip is black + silent** as the neutral form.

## Bundling mechanics (verified against `tools/build-binary.py`)

There is **no "whole src/ tree"** bundle — `build-binary.py` has an explicit
`DATA` list. It works because:
- `assets` is in `DATA`, and PyInstaller `--add-data` of a *directory* mirrors the
  tree **recursively**. `src/assets/flags/`, `src/assets/brands/`, and
  `src/assets/vendor/uplot/` already ship this way, so a new
  **`src/assets/placeholders/`** subdir ships with **no `DATA` change**.
- `obs` is in `DATA` → the OBS template ships; `get-graphics.py` reads it under
  `_MEIPASS/src/obs/` (repo name `GT_Endurance.json`; ZIP-package name
  `GT_Endurance.template.json` — the helper tries both, like `setup-assets.py`).
- `scripts` is in `DATA` → `src/scripts/placeholders.py` ships, **but** it is imported
  by importlib-loaded scripts that PyInstaller's static scan cannot see, so
  `build-binary.py` gains one line: **`--hidden-import placeholders`** (exactly as
  `overlay_build`/`discord_web` are already listed).

## Components

### a) Bundled placeholder files — `src/assets/placeholders/`
- `transparent-1080p.png` — fully transparent 1920×1080 RGBA PNG (~1–3 KB).
- `neutral-5s-1080p.mp4` — black, silent, 5 s, 1080p, H.264 `yuv420p` (~50–150 KB).

Committed (product assets, like the flag/brand logos). Regenerated reproducibly by a
maintainer tool.

### b) Maintainer regenerator — `tools/make-placeholders.py`
Writes both files into `src/assets/placeholders/` (PNG via stdlib `zlib`/`struct`;
MP4 via `ffmpeg -f lavfi -i color=c=black:s=1920x1080:d=5:r=30 -c:v libx264
-pix_fmt yuv420p -an …`). Mirrors the `fetch-flags.py` model: maintainer runs it,
commits the output. Not shipped.

### c) Shared helper — `src/scripts/placeholders.py` (pure stdlib, **no `config.py`**)
Consistent with the established "import a small pure helper, never the heavy
resolver" pattern (`overlay_build`, `discord_web`, `services` are imported the same
way by these scripts).

- `GRAPHIC_PLACEHOLDER = "transparent-1080p.png"`,
  `MEDIA_PLACEHOLDER = "neutral-5s-1080p.mp4"`.
- `graphic_placeholder_path()` / `media_placeholder_path()` — resolve
  `src/assets/placeholders/<file>` relative to **this module** (`dirname(__file__)/
  ../assets/placeholders`), so it works in the repo and under `_MEIPASS` without the
  caller passing an anchor. Returns the path, or `None` when the bundled file is
  absent (best-effort).
- `expected_graphics_from_template(text)` → sorted unique `<name>.png` from
  `re.findall(r"__RACECAST_GRAPHICS__/([^\"\\]+\.png)", text)` (the regex moved out of
  `setup-assets.py`; `setup-assets.py` then calls this helper — single source).
- `find_obs_template(obs_dir)` → first existing of
  `("GT_Endurance.template.json", "GT_Endurance.json")` in `obs_dir`, else `None`.
- `fill_missing(expected_names, directory, src_path)` → for each name not already in
  `directory`, atomically copy `src_path` → `directory/name` (`.part` + `os.replace`);
  `os.makedirs(directory, exist_ok=True)` first. Returns the sorted list of names it
  filled. Best-effort: a falsy `src_path`, an unreadable source, or a per-file copy
  error is skipped (logged by the caller), never raised. Idempotent.

### d) Wiring
- **`setup-assets.py`** (authoritative): after computing the missing graphics and
  missing intro/outro (the existing blocks at the `MEDIA_TOKEN`/`GRAPHICS_TOKEN`
  branches), call `fill_missing(...)` for each, then print
  `NOTE: wrote neutral placeholder for: <names>` instead of the old `WARNING`.
  Expected graphics come from `expected_graphics_from_template(raw)`; media is the
  fixed `intro.mp4`/`outro.mp4` pair already computed there.
- **`get-graphics.py`**: after the download loop, locate the bundled OBS template via
  `find_obs_template`, derive the expected set with
  `expected_graphics_from_template`, and `fill_missing` into `--out`. Best-effort: a
  missing/unreadable template skips the fill, leaving today's behavior. This covers
  the never-in-Sheet (weather) case at download time.
- **`get-media.py`**: after the download loop, `fill_missing(["intro.mp4",
  "outro.mp4"], --out, media_placeholder_path())`.

### e) Status / readiness
Unchanged. `event status`/preflight stay Sheet-driven; placeholders count as present.

## Error handling
Every fill is best-effort and never aborts a download/localize: a missing bundled
placeholder, a missing OBS template, or a per-file copy error is skipped, and the
command proceeds exactly as it does today (warnings/black sources) for anything that
could not be filled. No new failure mode is introduced.

## Testing
- **`tests/test_placeholders.py`** (the pure core):
  - `expected_graphics_from_template` extracts the right basenames, de-duplicates,
    sorts, ignores non-graphic tokens.
  - `find_obs_template` prefers `.template.json`, falls back to `.json`, returns
    `None` when neither exists.
  - `fill_missing` writes only the missing names, byte-identical to the source,
    atomically (no `.part` left behind), returns the filled list, is idempotent on a
    second run, creates the target dir, and tolerates a `None`/absent source.
  - Placeholder-path resolution returns an existing file in the repo layout.
- Extend `tests/test_setup.py` only if `setup-assets.py`'s localize path is unit-
  testable there; otherwise rely on the helper tests plus the binary smoke
  (`smoke()` already runs `setup --sheet-id smoke`, which exercises the fill path
  in-process and will surface a bundling/`--hidden-import` regression).

## Out of scope (YAGNI)
- Placeholder-aware reporting in `event status` (explicitly declined — silent).
- Per-asset bespoke placeholders (one transparent PNG / one black clip suffices).
- Generating the MP4 at binary-build time (committed instead).
