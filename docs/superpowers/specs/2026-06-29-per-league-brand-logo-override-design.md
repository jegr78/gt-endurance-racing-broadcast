# Per-League Brand-Logo Override via Sheet — Design

**Date:** 2026-06-29
**Status:** Approved (design)
**Topic:** Let a league owner override (or extend) the pre-built HUD brand logos per
league, configured in the Google Sheet and delivered with `profile export`.

## Problem

The HUD brand logos are a fixed, committed set of 24 PNGs under `src/assets/brands/`
(`bmw.png`, `audi.png`, `ferrari.png`, …). For each team the HUD resolves
`brandKey = asset_key(<Brand text from the Configuration tab>)` (e.g. `"BMW" → bmw`)
and requests `/hud/assets/brands/<brandKey>`; the relay serves it from a hard-wired
`src/assets` directory (`racecast-feeds.py:6473`). A league whose manufacturer is not
in the committed set — or who wants a league-custom version of an existing logo — has
no way to add or override one; the HUD slot stays empty.

A league owner asked for the ability to **override the pre-built brand logos per
league, configured in the Sheet**, and to have those assets **travel with the profile
export**.

## Decisions (from brainstorming)

1. **Keying:** per **brand** (`brandKey`), matching today's model. Overriding an
   existing key (`bmw`) and adding a new one (`cupra`) are the same operation. No
   per-team logos.
2. **Sheet source:** a dedicated new **`Brands`** tab (not the Assets tab, not a
   Configuration column).
3. **Storage / serving:** a **runtime section** — download into
   `runtime/<profile>/brands/`, relay resolves **override-first** (profile dir, then
   the committed base set), exported as a new asset section. Mirrors `graphics`/`media`.
4. **Trigger:** a dedicated **`racecast brands`** command (own `get-brands.py`
   downloader) **plus** a download card in the Control Center Profile view, analogous
   to the existing graphics/media download actions.

## Architecture

### 1. Sheet contract — the `Brands` tab

A new Sheet tab, header-located like every other tab. Two logical columns:

| Brand | Logo |
|-------|------|
| BMW   | `https://drive.google.com/…` (Drive share link) |
| Cupra | `https://drive.google.com/…` |

- **Invariant — the key lines up with the Configuration tab.** The key cell is
  normalized with the **same `asset_key()`** used for the Configuration-tab `brandKey`
  (`"BMW" → bmw`, `"Aston Martin" → aston-martin`). So the downloaded filename stem is
  *guaranteed* to equal the `brandKey` the HUD resolves for that team. The owner types
  the same brand text they already use — no separate "key" knowledge required.
- Accepted key headers (first match wins): `Brand Key | Brand | Brand Name`.
  Accepted logo headers: `Logo | Logo URL | Image`.
- Only rows whose logo cell is a **Google-Drive** link are downloaded (others skipped),
  matching `get-graphics.py`'s `is_drive_url()` rule.
- "Replace" and "add" are the same row: if `bmw` already exists in the base set it is
  overridden; a `cupra` that does not exist is added.

### 2. Downloader — `src/relay/get-brands.py` + `racecast brands`

- New self-contained script `src/relay/get-brands.py`, closely modeled on
  `get-graphics.py`: gviz CSV fetch of the `Brands` tab
  (`…/gviz/tq?tqx=out:csv&sheet=Brands`, no API key), Drive-link extraction, Drive
  large-file interstitial handling, **PNG signature verification**
  (`b"\x89PNG\r\n\x1a\n"`), atomic write (tempfile → rename).
- Target: `runtime/<profile>/brands/<asset_key>.png`.
- Pure pieces (test-importable, mirroring `get-graphics.py`):
  - `brands_from_csv(rows) -> {asset_key: drive_url}` — header-located, normalizes the
    key cell via `asset_key`, keeps only Drive-link rows.
  - `safe_filename(key) -> "<key>.png"` reusing the strict key shape.
- **`asset_key()` is duplicated into `get-brands.py`** (the four self-contained relay
  scripts deliberately do not import shared modules — same rule as the duplicated
  `load_dotenv` and the `STREAMLINK_TWITCH` constant). The copy is pinned **byte- /
  behavior-identical** to the relay's `asset_key` by a `getsource` cross-check test
  (the precedent is `tests/test_streams.py` pinning `STREAMLINK_TWITCH`).
- CLI: a new ONESHOT `brands` in `src/racecast.py` (`ONESHOTS` tuple), with a
  profile-scoped `--out runtime/<active>/brands` injected via `_oneshot_extra_args`
  (the same mechanism graphics/media use). Flags: `--sheet-id` (default
  `RACECAST_SHEET_ID`), `--brands-tab` (default `Brands`).
- Image format is **PNG only** (transparency; the committed base set is PNG). No
  SVG/JPG download path — YAGNI.

### 3. Relay serving — override-first, zero front-end change

- The relay derives `brands_dir = os.path.join(runtime, "brands")` next to the existing
  `graphics_dir` (`racecast-feeds.py:6472`); `runtime` is already the profile-scoped
  `--runtime-dir`, so this is `runtime/<profile>/brands` with **no new CLI flag**. It is
  passed into `make_handler` (new `brands_dir=` param, defaulting `None`).
- New pure function `resolve_brand_override(brands_dir, key)` that mirrors
  `resolve_asset`'s safety contract — strict `ASSET_KEY_RE`, the `ASSET_EXTS` extension
  order, and realpath-containment against `brands_dir` — but treats `brands_dir`
  **directly** as the base (the runtime layout is `runtime/<profile>/brands/<key>.png`,
  with no extra `brands/` sub-level, unlike `src/assets` + `"brands"`). Returns
  `(path, content_type)` or `None`.
- In `_send_asset`: for `sub == "brands"`, try `resolve_brand_override(brands_dir, key)`
  first; on a miss fall back to `resolve_asset(assets_dir, "brands", key)`. `flags`
  resolution is unchanged (base set only).
- **The HUD/splitscreen front-end is untouched** — same `/hud/assets/brands/<key>`
  URL, only the server-side resolution becomes override-first.
- New downloads apply **live after an OBS browser-source refresh** (`racecast obs
  refresh` / the `relay start` hash gate re-fetches the page; the browser re-requests
  the brand images). **No relay restart needed** — unlike the `--overlay-dir`
  launch-gate, because `brands_dir` is always derived, not gated on existence at launch.

### 4. Profile export / import — new asset section

- `ASSET_SECTIONS = ("graphics", "media", "brands")` in `src/scripts/profile_io.py`.
  Everything else follows automatically: `export_profile` zips
  `runtime/<profile>/brands/` under a `brands/` top-level prefix, records its file
  count in the manifest `counts`, `_safe_members`' `allowed_top` (derived from
  `ASSET_SECTIONS`) accepts it, and `import_profile` atomically swaps
  `runtime/<slug>/brands/` (only when the bundle carries it — a config-only bundle
  leaves an existing brands dir untouched).
- The export `sources` dict in `src/racecast.py` gains
  `"brands": os.path.join(runtime_dir, "brands")`.

#### Compatibility note (released v1.1.0)

Adding a section is **additive**. Old bundles (no `brands/`) import into the new binary
unchanged. The one forward-incompatibility: a bundle produced by the **new** binary
that *contains* a `brands/` section is **rejected by an older binary** on import,
because `_safe_members` only allows the top-level dirs it knows. This is acceptable
(newer-produces-newer) and is called out here explicitly per the project rule that
backward compatibility matters for the released product; the export manifest `schema`
is **not** bumped (the structure is unchanged, only the section enum grew). Operators
handing a brand-override profile to another producer must be on a matching-or-newer
build — the same expectation as any new feature's assets.

### 5. Control Center — download card

- A **"Brands"** download row/card in the Profile view, reusing the existing
  structured-status providers + op-registry + job-manager mechanics that drive the
  graphics/media download actions (`src/ui/`). Triggers the same code path as
  `racecast brands`.
- **Wiki screenshot obligation (CLAUDE.md hard rule):** the changed Control Center
  Profile view means its `cc-*.png` under `src/docs/wiki/images/` is now stale and MUST
  be regenerated in the **same change** via the `wiki-screenshots` skill, captured from
  a **local dev build** (no `VERSION` stamp) so the version badge stays uniform.

## Testing

- `brands_from_csv`: header-location across the accepted header variants, key
  normalization via `asset_key`, Drive-link-only filtering, blank/garbage rows ignored.
- `resolve_brand_override`: override-first hit, extension order, missing dir → `None`,
  path-traversal / unsafe key rejected, realpath containment enforced.
- `_send_asset` endpoint behavior: a runtime override wins over the base set for the
  same key; a key present only in the base set still resolves; an unknown key 404s;
  `flags` unaffected.
- `profile_io` round-trip: export → import with a `brands/` section restores the files;
  a no-`brands` (old-shape) bundle imports cleanly; a config-only re-import leaves an
  existing brands dir untouched.
- `getsource` cross-check pinning `asset_key` in `get-brands.py` to the relay's
  definition (drift guard; mirrors the `STREAMLINK_TWITCH` pin in `tests/test_streams.py`).
- Run `python3 tools/lint.py` and `python3 tools/run-tests.py`; `python3 tools/build.py`
  for the ship verification.

## Docs

- New `Brands` tab added to the Sheet-tab reference (wiki) and the League-Owner setup
  page (`src/docs/wiki/League-Owner-Setup.md`).
- `src/docs/wiki/Profiles.md`: note that `profile export` now also carries the
  per-league brand logos.
- `README.md` command list and the `CLAUDE.md` Commands + Architecture sections: add
  `racecast brands` and describe the override resolution.
- Run `python3 tests/test_wiki.py` after wiki edits (link/anchor validation).

## Out of scope (YAGNI)

- Per-team logos / a Configuration-tab logo column (we key per brand).
- Live CSV polling of the images (they are binary assets → downloaded per event, like
  graphics/media).
- SVG/JPG/WebP download paths (PNG with transparency is sufficient; the base set is PNG).
- Mirroring the runtime brands into the profile tree on export (single source of truth
  is `runtime/<profile>/brands/`).
