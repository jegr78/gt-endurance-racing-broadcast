# Per-Profile Overlay Overrides (HUD + Timer) — Design

**Date:** 2026-06-11
**Status:** Design — pending implementation
**Milestone:** M5d of the multi-league rebrand (PR #43), executed **before** M6 (docs/wiki/README + the irreversible GitHub repo rename). M6 stays the last step.

## Context

The multi-league refactor (M1–M5c, landed on PR #43) already made the **OBS scene
collection** fully profile-scoped: one localized collection per profile
(`runtime/<profile>/GT_Endurance.import.json`), a per-profile collection **name**
(`OBS_COLLECTION` → falls back to the profile `NAME`), per-profile asset paths
(`runtime/<profile>/graphics|media`), all generated from a **single** committed base
template `src/obs/GT_Endurance.json` (no per-league variants in git). Several leagues
coexist in OBS and the producer switches with `racecast obs collection set`.

The one thing **not** yet profile-aware is the **relay-served HUD and race-timer pages**.
`src/obs/hud.html` and `src/obs/timer.html` are single, hard-coded files: every position
is a hard-coded pixel value in one inline `<style>` block, the font is fixed
(`"Arial Narrow"` / monospace stack), and the relay loads them from a fixed source path
(`src/relay/racecast-feeds.py`) — it never looks in `profiles/<name>/` or
`runtime/<profile>/`. Two different leagues serve byte-identical overlay pages today.

Different leagues will need different lower-third layout, positioning, arrangement, and
fonts. This design makes the overlay pages **per-profile overridable** while keeping a
single shared base template (so the OBS scenes, sources, panel, and Companion buttons
stay identical across leagues — only the page styling differs).

## Goals

1. Each profile can optionally ship its own overlay styling that overrides the shared
   base `hud.html` / `timer.html` — positioning, arrangement, colors, and **fonts** —
   without forking the base HTML.
2. Overrides are **committed with the profile** (`profiles/<name>/overlay/`), so a league
   carries its look; `profile new --from <src>` copies it automatically (existing
   `shutil.copytree`).
3. Profiles **without** an override keep today's exact behavior and bytes (no regression).
4. Edits apply live: after a save, an OBS browser-source refresh shows the new look
   without a relay restart (the relay reads override CSS per request).
5. The Control Center exposes a per-profile overlay-CSS **editor** (HUD + Timer).
6. Per-league OBS collection names follow a recognizable prefix convention so several
   toolkit collections group together in OBS.

## Non-Goals (v1)

- **Brand/flag logos stay global** in `src/assets/` (country flags + manufacturer logos
  are league-neutral). Not made profile-scoped here.
- **Binary font upload via the Control Center** is out of scope; fonts are a filesystem
  drop-in for v1 (`profiles/<name>/overlay/fonts/`). The CSS editor handles the two text
  files only.
- No new HUD/timer **data** fields; this is styling only. `/hud/data` and `/timer/data`
  contracts are unchanged.
- No CSS validation/linting in the editor; the producer owns the CSS (same trust model as
  the existing `profile.env` editor).

## Design

### 1. Profile overlay directory (committed, ships with the profile)

```
profiles/<name>/overlay/
  hud.css        # optional — override stylesheet for the HUD page
  timer.css      # optional — override stylesheet for the race-timer page
  fonts/         # optional — @font-face sources (woff2/woff/ttf/otf)
    <fontfiles>
```

All three are optional. The directory is copied verbatim by `profile new --from <src>`
(no code change — `create_profile` already `copytree`s the whole profile dir).

### 2. Override contract (cascade-wins overlay, base unchanged)

The base `src/obs/hud.html` and `src/obs/timer.html` keep their structure and inline
`<style>` block **unchanged**, and gain one override hook as the **last** element of
`<head>` (so the cascade order makes the override win):

```html
<link rel="stylesheet" href="/hud/override.css">     <!-- in hud.html -->
<link rel="stylesheet" href="/timer/override.css">   <!-- in timer.html -->
```

The override CSS is full CSS: it can reposition any element by id (`#stint`, `#session`,
`#streamer`, `#round-top`, `#round-flag`, `#round-country`, `#team0..2`, `#race-control`,
`#clock`), change colors/sizes, and declare `@font-face { src: url(/overlay/fonts/<file>) }`
to load a league font. When a profile has no override, the endpoint returns an **empty**
stylesheet → the `<link>` is a harmless no-op and the base look is byte-stable.

### 3. Relay changes (`src/relay/racecast-feeds.py`)

**New parameter:** `--overlay-dir DIR` (default `None`). The CLI passes the active
profile's `profiles/<name>/overlay` here when it exists. `None`/missing → override
endpoints serve empty CSS and the font endpoint 404s (today's behavior preserved).

**New endpoints** (added to `make_handler`'s `do_GET`, plumbed via a new `overlay_dir`
parameter on `make_handler`):

| Endpoint | Serves | Absent → |
| --- | --- | --- |
| `GET /hud/override.css` | `<overlay-dir>/hud.css` as `text/css; charset=utf-8`, `Cache-Control: no-store` | empty `text/css` body, `200` |
| `GET /timer/override.css` | `<overlay-dir>/timer.css` | empty `text/css` body, `200` |
| `GET /overlay/fonts/<name>` | `<overlay-dir>/fonts/<name>` with a font content-type by extension | `404` JSON |

- Override CSS is read **per request** from disk (not cached at relay start, unlike the
  base `hud_path`), so editor save → OBS refresh applies without a relay restart.
- **Always-200 empty** for the two `*.css` endpoints (even with no `--overlay-dir`) keeps
  the hash-gate fetch (below) succeeding and the base `<link>` harmless.
- **Font path safety** mirrors the existing `resolve_asset` (`src/relay/racecast-feeds.py:213`):
  a strict basename regex, an allow-list of extensions (`woff2`, `woff`, `ttf`, `otf`),
  `os.path.realpath` confinement under `<overlay-dir>/fonts`, content-type from a constant
  map (never request-derived). No `..`, no absolute paths, no traversal.

### 4. Hash-gate integration (`src/racecast.py`)

The OBS auto-refresh gate hashes the **bytes the relay actually serves** over HTTP
(`served_pages_hash`, `OBS_PAGE_PATHS = ("/hud", "/timer")`). Because override CSS loads
as a separate request, a CSS-only edit would not change the page HTML bytes. Fix by
extending the hashed set:

```python
OBS_PAGE_PATHS = ("/hud", "/timer", "/hud/override.css", "/timer/override.css")
```

Now any change to a profile's `hud.css`/`timer.css` flips the served hash → the existing
`refresh_decision` triggers `refreshnocache` on the relay-pointed browser sources. Fonts
are referenced *by* the CSS, so a font swap that matters is reflected through a CSS edit;
font bytes themselves are not separately hashed (YAGNI — a new font without a CSS change
has no visible effect). Profiles without overrides serve stable empty CSS → no spurious
refresh. `--no-hud`/`--no-timer` already make `/hud`/`/timer` 404 → `served_pages_hash`
returns `None` → "skip-no-pages", unchanged.

### 5. CLI wiring (`src/racecast.py`)

`ResolvedConfig.profile_dir` already exists (`src/scripts/config.py:196`). The relay-arg
builder (`_relay_runtime_args` / the daemon argv) appends
`--overlay-dir <profile_dir>/overlay` **only when that directory exists**, alongside the
existing `--runtime-dir` / `--cookies`. The relay stays profile-agnostic (it receives a
path, not a profile name). Frozen-mode `racecast relay run` re-invocation inherits the
same flag.

### 6. Control Center overlay-CSS editor

Mirrors the M4 `profile.env` editor exactly (same patterns, same safety model).

**Backend — pure data providers (`src/ui/ui_ops.py`):**
- `overlay_read_data(page)` → `{ "page": "hud"|"timer", "css": <text>, "exists": bool,
  "path": <abs> }`, reading `profiles/<active>/overlay/<page>.css`.
- `overlay_write_data(page, content)` → writes that file (creating `overlay/` if needed),
  returns `{ "ok": true, "path": <abs> }`.
- `page` is validated against the literal set `{"hud", "timer"}`; the file path is built
  by a **strict resolver** confined to the active profile's `overlay/` dir — it can never
  escape the profile dir or write the machine `.env` (same guarantee as the M4 profile-env
  resolver).

**Server routes (`src/ui/ui_server.py`):**
- `GET /api/overlay?page=hud|timer` → `overlay_read_data`.
- `POST /api/overlay` body `{page, content}` → `overlay_write_data`.

**Frontend (Profile view):** a new "Overlay CSS" card alongside the existing `profile.env`
editor and the scoped graphics/media — a page selector (HUD / Timer), a textarea
pre-filled from `GET /api/overlay`, and a Save button. After a successful save it shows a
hint and an **"Apply in OBS"** action that calls the existing OBS-refresh op (best-effort;
needs the relay up + obs-websocket, exactly like `racecast obs refresh`). The editor does
not auto-refresh OBS silently.

### 7. Example profile + docs

- `profiles/example/overlay/hud.css` and `timer.css`: **commented no-op** templates that
  list the overridable selectors/ids and a sample `@font-face` block, changing nothing by
  default — so a new league immediately sees what is overridable.
- A short `profiles/example/overlay/fonts/` note (e.g. a `.gitkeep` or one-line README)
  to keep the dir in git and document the drop-in convention.
- Operator docs/wiki coverage is folded into **M6** (the docs milestone), not here.

### 8. Collection-name prefix convention (small companion change)

`src/scripts/config.py` resolves `obs_collection`. Change the default (when
`OBS_COLLECTION` is unset) from the bare profile `NAME` to a product-prefixed name:

```python
PRODUCT_COLLECTION_PREFIX = "GT Endurance Racing"   # module constant
...
obs_collection = prof.get("OBS_COLLECTION") or f"{PRODUCT_COLLECTION_PREFIX} — {resolved_name}"
```

An explicit `OBS_COLLECTION` in `profile.env` still overrides everything. The **canonical
source name** in `tools/tokenize-obs.py` (the fold-back reset, currently
`"GT Endurance Racing"`) is **unchanged** — league names still never land in git. Several
leagues then show as `GT Endurance Racing — IRO Endurance`,
`GT Endurance Racing — ERF Endurance`, etc., grouped in OBS's collection list.

## Data flow

```
profiles/<name>/overlay/{hud,timer}.css, fonts/*
        │  (committed; copytree on `profile new --from`)
        ▼
CLI resolve_config → ResolvedConfig.profile_dir
        │  _relay_runtime_args appends --overlay-dir <profile_dir>/overlay (if exists)
        ▼
relay (racecast-feeds.py) serves:
   /hud  + <link href="/hud/override.css">      ← base html (cached) + per-request css
   /timer+ <link href="/timer/override.css">
   /overlay/fonts/<file>                         ← per-request, path-sanitized
        │
        ▼
OBS browser sources (HUD / Timer)  ── cascade: override wins
        ▲
        │  refresh triggered when served hash changes
racecast obs refresh / relay start  → served_pages_hash() now includes the two override.css
```

## Security

- Font endpoint: strict basename regex + extension allow-list + `realpath` confinement
  under `<overlay-dir>/fonts` + constant content-type map — reuses the proven
  `resolve_asset` pattern; no traversal, no header injection.
- Override-CSS filenames are fixed (`hud.css` / `timer.css`) — no request-controlled path
  on the relay.
- Control Center resolver: `page ∈ {hud, timer}` only; path is computed, confined to the
  active profile's `overlay/` dir, and structurally unable to reach the machine `.env`
  (same guarantee the M4 profile-env editor already enforces).
- Trust boundary is unchanged: the relay is tailnet-only; the Control Center is the local
  producer's app. Override CSS/fonts are producer-authored content, same trust level as
  `profile.env` and the OBS collection.

## Testing strategy (TDD, stdlib only)

- **Relay override serving** (`tests/test_hud.py` or a new `tests/test_overlay.py`):
  present `hud.css` → served as `text/css` with its bytes; missing/no `--overlay-dir` →
  empty `200` `text/css`; `timer.css` analogous.
- **Font serving + traversal:** valid `font.woff2` → served with `font/woff2`; `../x`,
  absolute paths, and disallowed extensions → `404`; content-type from the constant map.
- **Hash-gate:** `served_pages_hash` with a fake fetch returns a different digest when the
  override CSS bytes change and a stable digest when they don't; `OBS_PAGE_PATHS` includes
  the two override paths.
- **Argparse:** `--overlay-dir` parses and plumbs into `make_handler`.
- **CLI wiring:** `_relay_runtime_args` includes `--overlay-dir <…>/overlay` when the dir
  exists and omits it when absent (pure, fixture dirs).
- **Config default** (`tests/test_config.py`): `obs_collection` defaults to
  `"GT Endurance Racing — <NAME>"` when `OBS_COLLECTION` unset; explicit value still wins.
- **Control Center** (`tests/test_ui_ops.py`, `tests/test_ui_server.py`):
  `overlay_read_data`/`overlay_write_data` round-trip; `page` validation rejects anything
  outside `{hud, timer}`; the resolver cannot write outside the active profile's `overlay/`
  dir; `GET`/`POST /api/overlay` routes.

## Files touched (summary; exact lines in the plan)

- `src/obs/hud.html`, `src/obs/timer.html` — add the override `<link>` (last in `<head>`).
- `src/relay/racecast-feeds.py` — `--overlay-dir`; `/hud/override.css`,
  `/timer/override.css`, `/overlay/fonts/<name>` endpoints; per-request CSS read; font
  resolver; `make_handler` param.
- `src/racecast.py` — extend `OBS_PAGE_PATHS`; append `--overlay-dir` in the relay-arg
  builder.
- `src/scripts/config.py` — `PRODUCT_COLLECTION_PREFIX` + prefixed `obs_collection` default.
- `src/ui/ui_ops.py`, `src/ui/ui_server.py`, and the Profile-view frontend — overlay-CSS
  editor (providers + routes + UI).
- `profiles/example/overlay/{hud,timer}.css` (+ `fonts/` keep) — commented templates.
- Tests as above.

## Sequencing

Implemented as **M5d on PR #43**, before M6. Order within M5d: relay endpoints + base-HTML
hook (with tests) → hash-gate + CLI wiring → config collection-name default → Control
Center editor → example templates. Then the rolling PR #43 title/body and memory are
updated, CI watched to green. M6 (docs/wiki/README de-brand + repo rename) remains the
final, irreversible step and now also documents the overlay feature.

## Open questions

None blocking. Deferred by decision: binary font upload in the editor, per-league brand
logos, CSS validation — all post-v1 if a real need appears.
