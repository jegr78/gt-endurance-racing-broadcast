# Bundled overlay fonts (replace curated download picker)

**Date:** 2026-06-14
**Status:** Approved — ready for implementation plan

## Problem

The machine-wide overlay font library (`runtime/fonts/`) starts empty on every new
install. The operator has to populate it from **General Settings** — a curated
quick-pick of ~22 Google families plus a free-text typeahead — before the Overlay
Builder's font pickers offer anything useful. The goal is for a baseline set of
broadcast-friendly fonts to be **always available on every local installation**, with
no manual download step, so the Overlay Builder works out of the box.

## Goal

- A curated baseline font set ships with every OS build and is present in
  `runtime/fonts/` after the first app start (CLI **or** Control Center UI).
- The set survives `racecast update` (which swaps only the binary).
- Remove the now-redundant **curated quick-pick** from General Settings. Keep the
  free-text Google-font typeahead/download, the installed-fonts overview (with delete),
  and the existing "Open Google Fonts" link button.
- Update the wiki, including a fresh General Settings screenshot.

## Non-goals

- No change to the per-league `overlay/fonts/` uploader in the Overlay Builder.
- No change to `_materialize_overlay_fonts` (the on-save copy of a used font into the
  active profile) — it keeps working; the library it draws from is now pre-populated.
- No change to the relay's font serving or the override-CSS pipeline.

## Design

### Font source = single manifest

`overlay_build.GOOGLE_FONTS` (the existing curated 22 families) stays as the **single
source of truth** for "which fonts belong to the bundled set" AND as the typeahead
fallback list in `google_font_catalog_data`. Only its presentation as a clickable
quick-pick is removed.

### Build pipeline

1. **`tools/fetch-fonts.py`** (new maintainer tool, modeled on `tools/fetch-flags.py`):
   - Downloads each family in `GOOGLE_FONTS` from Google Fonts, reusing
     `overlay_build.google_font_css_url` / `google_font_filename` and the same woff2
     extraction logic as `machine_font_download_data` (fixed googleapis css host →
     gstatic woff2; bold weight first, default face fallback). Fetchers are injectable
     for tests.
   - Writes **`fonts.zip`** containing the `.woff2` files plus a `manifest.json`
     `{version, fonts: [filenames...], stamp}` where `stamp = sha256` of the sorted
     filename list. Output path: repo root `fonts.zip` (gitignored).
   - Runnable standalone by a dev to populate the dev environment.
2. **`tools/build-binary.py`**: ensures `fonts.zip` exists (invokes `fetch-fonts` if
   missing), then bundles it via `--add-data` into both frozen binaries (same mechanism
   as `profiles/example`). The zip travels **inside** the binary — so `racecast update`
   refreshes the font set.
3. **CI** (`.github/workflows/release.yml`, `preview.yml`): no packaging change needed —
   the zip is inside the binary, not a separate archive member. The build step gains a
   network fetch of the fonts (or a cached `fonts.zip`); document the network dependency.

### Extraction at app start

- New `ensure_bundled_fonts(home)` in `src/racecast.py`, called from **`_bootstrap()`**
  right after `ensure_example_profile()` — covers CLI and UI (both route through
  `_bootstrap`).
- `_bundled_fonts_zip()` locator: frozen → `os.path.join(_MEIPASS, "fonts.zip")`;
  dev/repo → repo-root `fonts.zip`. Returns `None` when absent (no-op, e.g. a dev who
  never ran `fetch-fonts`).
- Target: `runtime/fonts/` (= `_machine_fonts_dir()`).
- **Stamp-gated:** marker `runtime/fonts/.bundled.json` records the last applied stamp.
  Equal stamp → no-op (cheap, runs every start). Missing/different stamp → extract.
- **Per-file only-if-absent:** never overwrite an existing same-named file (respects
  operator-added or same-named fonts). Then write the marker.
  - Consequence: an operator who deletes a bundled font keeps it gone *within a
    version*; a later release with a changed set (new stamp) re-seeds the baseline
    (re-adding any deleted bundled fonts). This is intended — "always available"
    baseline.
- **Zip-slip safe:** validate every entry name with `_font_name_ok` + realpath
  containment (the same hardening as `_write_font`); never blind `extractall`.
- Fully best-effort: any failure prints one notice and startup continues (the library
  just stays whatever it already was).

### UI change (General Settings → font library)

- **Remove:** the curated `<select id="font-catalog">`, its **Download** button, the
  `downloadLibFont()` handler, the `pending`/catalog render path, and the `catalog`
  field returned by `machine_fonts_list_data`.
- **Keep:** the "Open Google Fonts" link button (already present), the free-text
  **"Other font"** typeahead (`#font-custom` → `/api/fonts/download`), the installed
  fonts overview (`#font-lib-list`) including delete, and the routes `/api/fonts`,
  `/api/fonts/catalog`, `/api/fonts/download`, `/api/fonts/delete`.
- Update the section hint text: `runtime/fonts/` is pre-seeded with the bundled set;
  add further families by name via the typeahead.

### Tests

- **`tests/test_fonts.py`** (new):
  - `fetch-fonts` zip assembly with injected css/bin fetchers → asserts the zip
    contains the expected woff2 names + a manifest with a deterministic stamp.
  - `ensure_bundled_fonts` / extraction: stamp-gating (no-op on equal stamp, extract on
    diff), per-file only-if-absent (does not overwrite a pre-existing file), zip-slip
    rejection (a `../evil` entry is refused), marker is written.
- **`tests/test_ui_server.py` / `tests/test_racecast.py`**: drop assertions on the
  removed `catalog` field; keep the typeahead (`/api/fonts/catalog`) and download/delete
  coverage.

### Docs

- **`CLAUDE.md`**: Control Center section + the font-library description — the library is
  now pre-seeded from the build; the curated quick-pick is gone; the typeahead/upload
  paths remain. Note `tools/fetch-fonts.py` + the in-binary `fonts.zip`.
- **`src/ui/control-center.html`**: section hint text.
- **`src/docs/wiki/HUD-Overlays.md`**: the font-library paragraph.
- **`src/docs/wiki/Control-Center.md`**: General Settings prose if it mentions fonts.
- **Wiki screenshot:** regenerate `src/docs/wiki/images/cc-settings.png` from the
  running Control Center (General Settings view, new font section) via the Playwright
  MCP, then publish with `tools/sync-wiki.py`.

## Open questions

None.
