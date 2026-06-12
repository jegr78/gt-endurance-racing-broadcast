# Profile Export / Import — design

**Date:** 2026-06-12
**Status:** approved (brainstorming)
**Goal:** Let a producer export a whole league profile as a single `.zip` and let
another producer import it — so onboarding a new producer no longer means
hand-creating `profiles/<name>/` and re-entering every league setting.

## Motivation

A profile is the league: `profiles/<name>/profile.env` (NAME, SHEET_ID,
**SHEET_PUSH_URL**, INTRO/OUTRO_URL, LOGO, OBS_COLLECTION), the per-league
`overlay/` (hud.css, timer.css, fonts/), an optional logo image at the profile
root, and the downloaded assets under `runtime/<name>/graphics|media`. Real
profiles are gitignored (`profiles/*`, only `example/` ships), so today a new
producer must recreate all of this by hand. A profile export/import path turns
that into "send a zip, click Import, click Use".

This **supersedes** the originally-requested look-backup import button: the
look-backup feature (`racecast backup …` + the Looks card) stays untouched as the
profile-internal snapshot/restore use case; the separate asset-import button is
dropped because profile import covers the onboarding need.

## Decisions (from brainstorming)

- **Scope:** Profile export/import replaces the asset-import button. Look-backup
  /restore is unchanged.
- **Bundle contents:** the whole `profiles/<name>/` tree (so the LOGO file and
  fonts travel automatically) + the runtime `graphics/` and `media/` assets, with
  assets deselectable via an "Include assets" checkbox (default on). A config-only
  bundle is small; the receiver can re-fetch assets with `racecast graphics`/`media`
  (public Sheet downloads, no cookies needed).
- **SHEET_PUSH_URL:** always included, no warning and no opt-out. Sheet access is
  shared anyway, the values must reach the producer's machine somehow, and once
  there they are inspectable. No special handling.
- **CLI parity:** add `racecast profile export` / `racecast profile import`
  alongside the UI buttons (symmetry + testable core logic).

## Bundle format

A `.zip` with a typed manifest. The whole profile dir ships under `profile/`;
runtime assets ship at top level under `graphics/` and `media/`:

```
manifest.json   {kind:"profile-export", schema:1, name, display, created,
                 includes_assets, counts}
profile/...     the complete profiles/<name>/ tree (profile.env, overlay/,
                logo image, fonts, …)
graphics/...    runtime/<name>/graphics/   (only when assets included)
media/...       runtime/<name>/media/      (only when assets included)
```

`name` is the directory slug; `display` is the league NAME for messages.

## Architecture

### New module: `src/scripts/profile_io.py` (pure logic, stdlib only)

Mirrors `backup_admin.py`'s discipline (validate before writing, atomic, fail-safe)
and reuses its `SECTIONS = ("graphics","media")`-style constants for the asset
subtrees. No argv parsing, no network.

- `export_profile(name, sources, include_assets, dest) -> path`
  - `sources` is a dir map `{profile_dir, graphics, media}`.
  - Always adds the `profile/` tree; adds `graphics/`/`media/` only when
    `include_assets`. Writes the typed manifest. Atomic temp-file → `os.replace`,
    exactly like `create_backup`.
- `import_profile(src_zip, roots, force=False) -> {name, display, includes_assets}`
  - **Validates before touching any live dir:**
    - `manifest.kind == "profile-export"`,
    - `profile/profile.env` is present,
    - every member is under `{manifest.json, profile/, graphics/, media/}` with no
      absolute path and no `..` segment (a `_safe_members`-equivalent guard),
  - target slug = `slugify(manifest.name)` (also traversal defense); if
    `profiles/<slug>/` exists and `not force` → `FileExistsError`,
  - writes `profiles/<slug>/` from `profile/`, and `runtime/<slug>/graphics|media`
    from the asset subtrees when present, each via an atomic `.old`-swap (live-only
    files dropped per section), and **does not switch** the active profile.

### Endpoints (`src/ui/ui_server.py`)

- `GET /api/profile/export?name=<slug>&assets=1` — calls `ctx["profile_export"]`
  (builds the zip into a temp file), then streams it back as a download:
  `Content-Disposition: attachment; filename="<slug>-profile.zip"`, and deletes the
  temp file afterward. Not JSON — a real file download.
- `POST /api/profile/import?force=0` — raw zip body (no multipart: `cgi` was
  removed in Python 3.13+). New helper `_body_to_tempfile(max_bytes)` streams
  `Content-Length` in chunks into a temp file and rejects bodies over
  `MAX_IMPORT_BYTES` (default 2 GiB, to allow media videos). Then
  `ctx["profile_import"](tmp_path, force)` → `{ok, name, display, includes_assets}`
  or `{ok:false, error}`. Temp file removed in a `finally`.

### Providers (`src/racecast.py`)

`profile_export_data(name, include_assets)` and `profile_import_data(tmp_path,
force)`, wired into the `ctx` dict next to the `backup_*` providers. Both build the
`sources`/`roots` maps from `_env_base()` (profiles root) and `_runtime_dir()`
(asset roots). Error paths return `{ok:false, error}` (no profile, malformed zip,
slug taken).

### Control Center UI (`src/ui/control-center.html`, Profile view)

- **Export profile** button per profile row (or on the active profile) with an
  **Include assets** checkbox (default on) → opens the export download URL.
- **Import profile** button at the top of the Profiles card → hidden
  `<input type="file" accept=".zip">` → POSTs the file as the raw body → on success
  shows "Profile 'X' imported" and offers to switch to it (`/api/profile/use`). On a
  name collision the inline error shows, plus a "Replace existing profile 'X'?"
  confirm that re-uploads with `force=1`.
- Errors render inline, following the existing `profile-err`/`overlay-err` pattern.

### CLI (`src/racecast.py` + `src/scripts/profile_admin.py`)

- `racecast profile export <name> [--no-assets] [--out PATH]` — writes the bundle
  (default `./<slug>-profile.zip`), prints the path.
- `racecast profile import <file> [--force]` — creates the profile, prints the slug
  and a `racecast profile use <slug>` hint.
- `PROFILE_VERBS` + `parse_profile_args` extended for the export/import verbs (their
  arg shape is `<name>`/`<file>` + flags, unlike the existing list/show/use/new).

## Error handling

- Import validation runs entirely **before** any live write; a malformed or unsafe
  archive fails with a clear message and leaves the filesystem untouched.
- Slug derivation via `slugify` doubles as path-traversal defense.
- Existing profile + no force → explicit `FileExistsError`-backed message; force
  does an atomic `.old`-swap so a failure mid-write does not leave a half profile.
- Upload size cap returns a clear 413-style JSON error rather than buffering an
  unbounded body.
- Export/import providers never raise to the HTTP layer — they return
  `{ok:false, error}` and the route maps it to the right status code.

## Testing

- `tests/test_profile_io.py` (new, stdlib-runnable): export builds a zip with the
  typed `kind`/`profile/`/`manifest`; assets present only when `include_assets`;
  **round-trip** export→import into fresh roots reproduces `profile.env` + overlay
  (+ logo) (+ assets); import rejects missing `profile.env`, missing manifest, wrong
  `kind`, `..` traversal, a foreign top-level entry; `FileExistsError` without force
  and overwrite with force; slug sanitization / traversal defense.
- `tests/test_ui_server.py` extended: `GET /api/profile/export` streams a file with
  `Content-Disposition`; `POST /api/profile/import` accepts a raw body and the size
  cap rejects an over-limit body.
- Provider tests for `profile_export_data` / `profile_import_data` (error paths: no
  active/named profile, corrupt zip).
- Final gates: `python3 tools/lint.py` and `python3 tools/build.py` (its verify step
  is the closest local mirror of CI).

## Docs

- **CLAUDE.md** — Profiles + config section and the Commands list (new
  `profile export|import`).
- **README.md** — operator quickstart line for export/import.
- **Wiki** (`src/docs/wiki/`, published via `tools/sync-wiki.py`, never hand-edited
  on GitHub) — a new onboarding section: "Onboard a new producer: export → send the
  zip → import → use".
- **Wiki screenshots** — the Control Center Profile view changes (Export/Import
  buttons, Include-assets checkbox, the import flow), so the wiki's Control Center
  screenshots must be regenerated after the UI lands. Capture fresh shots and embed
  them on the relevant wiki page(s).

## Out of scope

- The standalone look-backup *import* button (dropped — profile import covers it).
- Any change to look-backup create/list/restore/delete.
- Auto-switching the active profile on import (offered as a follow-up action, not
  automatic).
- Re-downloading assets during import (the receiver runs `racecast graphics`/`media`
  if they chose a config-only bundle).
