# Sheet-Driven Graphics + Weather Overlays — Design Spec

> Follows the **Intro / Outro Videos** spec (`2026-06-04-intro-outro-videos-design.md`).
> Same pattern, extended from two video clips to all broadcast still-graphics.

## Goal

Drive **every broadcast graphic** (Standings, Schedule, Race/Quali Results, Overlay,
Post Race Interviews, Standby cover, and three new weather graphics) from the Google
Sheet **Assets** tab — downloaded fresh into `runtime/` before each event, never
committed — exactly like the Intro/Outro clips. Add the three weather graphics as new
OBS sources, each switchable by its own Companion button.

## Decisions (from brainstorming)

1. **Pure runtime, like Intro/Outro.** The committed top-level PNGs in `src/assets/`
   are removed; all graphics are downloaded from the Sheet into `runtime/graphics/`.
   No committed fallback. Accepted trade-off (identical to Intro/Outro): if the fetch
   has not run / the producer is offline, those sources show black. The event prep
   checklist gains a "fetch graphics" step.
2. **All graphic rows** of the Assets tab are sheet-driven (not just the per-event ones).
3. **Label = filename. No mapping table.** The download filename is the **exact Assets
   label** + `.png` (lightly sanitised). OBS sources point at
   `__IRO_GRAPHICS__/<Label>.png`. There is deliberately **no** `{label: filename}`
   dict in code — the Sheet is the single source of truth for names. A new graphic
   added to the Sheet is fetched automatically (it still needs an OBS source + button
   to appear on air, but the fetch code is untouched).
4. **Weather = Stint overlays, one toggle each.** The three weather graphics are hidden
   full-screen `image_source`s inside the **Stint** scene, each with one Companion
   toggle button and a lit-while-visible feedback — mirroring the existing
   Standings/Schedule/Results buttons exactly (independent toggles, not radio).
5. **Dedicated token + dir** `__IRO_GRAPHICS__` → `runtime/graphics/`, parallel to
   `__IRO_MEDIA__` → `runtime/media/`. Not reused from `__IRO_MEDIA__`: "media" is
   video; a self-documenting `graphics/` dir keeps the two concerns separate and is the
   foundation for pulling further still-assets from the Sheet later.

## Prerequisite already satisfied

The Assets-tab labels are filesystem-clean (the `Race Waether 1` typo was corrected in
the Sheet to `Race Weather 1`). Because labels are used verbatim as filenames, Sheet
labels **must** stay clean — there is no code-side alias.

The current graphic labels (the canonical filenames, each `<Label>.png`):
`Overlay`, `Standings`, `Schedule`, `Race Results`, `Quali Results`,
`Race Weather 1`, `Race Weather 2`, `Quali Weather`, `Post Race Interviews`, `Standby`.

## Non-goals (YAGNI)

- No relay involvement: graphics are local files in OBS, not relay-served (unlike the HUD).
- No auto-creation of OBS sources/buttons from new Sheet rows (fetch is generic; OBS
  wiring stays explicit).
- No change to the HUD overlay, flags, or brand logos. `src/assets/flags/` and
  `src/assets/brands/` stay committed and bundled (the relay serves them) and are
  untouched by this work.
- No mutually-exclusive ("radio") graphics behaviour — independent toggles, as today.
- No per-graphic env/CLI URL overrides (the Sheet is the source; Intro/Outro keep theirs).

## Architecture

### New token: `__IRO_GRAPHICS__`

Mirrors `__IRO_MEDIA__`. The OBS collection stores `__IRO_GRAPHICS__/<Label>.png` for
every still-graphic source; `setup-assets.py` replaces it with the absolute path to the
local graphics dir. Resolves to:
- **Repo:** `<repo>/runtime/graphics/`
- **Package:** `<package>/graphics/`

`__IRO_ASSETS__` is **retired from the shipped collection** (no source references it
after this change). Its resolver stays in `setup-assets.py` for backward compatibility
(harmless no-op when the token is absent); the `--assets` dir is still validated because
`flags/`/`brands/` live there.

### Path resolution: `graphics_dir()`

A `graphics_dir(here)` helper in `get-graphics.py` and a `graphics_dir(base)` in
`setup-assets.py`, each a one-line sibling of the existing `media_dir()`:
- `get-graphics.py` sits at `src/relay/` (repo) or `<pkg>/relay/` (package):
  repo → `<repo>/runtime/graphics`; package → `<pkg>/graphics`.
- `setup-assets.py` sits at `src/` (repo) or `<pkg>/` (package):
  repo (basename `src`) → `<repo>/runtime/graphics`; package → `<base>/graphics`.

### Google Drive download

Assets graphic rows are Drive **share** links
(`https://drive.google.com/file/d/<ID>/view?usp=sharing`). Convert to the direct
download endpoint `https://drive.google.com/uc?export=download&id=<ID>` and GET with
stdlib `urllib` (no `yt-dlp` — these are images). The ID is extracted by regex from
either the `/file/d/<ID>/` or `?id=<ID>` form. A small **confirm-token fallback**
handles Drive's interstitial for large files (if the first response is `text/html`
containing a `confirm=` token, re-request with it) — defensive; the current images are
small enough to download directly (verified: HTTP 200, `image/png`).

### Components

| File | Change |
|------|--------|
| `src/relay/get-graphics.py` | **New.** Fetch Assets tab → download every Drive-link row as `<Label>.png` into the graphics dir. |
| `src/obs/IRO_Endurance.json` | Retokenise the 8 `__IRO_ASSETS__/*.png` graphic refs → `__IRO_GRAPHICS__/<Label>.png`; rename source `Season Schedule`→`Schedule`; add 3 weather `image_source`s + 3 hidden Stint items. |
| `src/assets/*.png` (top-level) | **Delete** the 7 committed graphics (pure runtime). `flags/`+`brands/` stay. |
| `src/setup-assets.py` | Add `__IRO_GRAPHICS__` resolution + missing-file warning (mirrors `__IRO_MEDIA__`). |
| `src/companion/iro-buttons.companionconfig` | 3 weather toggle buttons (Page 1, col 7, rows 1–3); retarget `Schedule Toggle` source ref to `Schedule`. |
| `tools/build.py` | Best-effort `get-graphics.py --out <pkg>/graphics`; verify switches to `__IRO_GRAPHICS__/` + no Drive-path leakage. |
| `tools/tokenize-obs.py` | Asset-basename tokenisation retargets to `__IRO_GRAPHICS__`. |
| `tools/add_standby_cover.py` | Standby Cover source path → `__IRO_GRAPHICS__/Standby.png`. |
| `tests/test_graphics.py` | **New.** Drive-id extraction, download-URL builder, label→filename sanitiser, `graphics_dir()` repo/package. |
| Docs | CLAUDE.md, README.md, README_SETUP.md, wiki (OBS-Setup, Run-an-event, Director, Configuration), cheat-sheet HTML. |
| `companion-page1-show-control.png` | Regenerate (companion-screenshots skill). |

## Detailed component design

### 1. `src/relay/get-graphics.py` (new, shipped — sibling of `get-media.py`)

```
load_dotenv(start)                  # 4th verbatim copy (CLAUDE.md note: 3 -> 4)
GRAPHICS_VIDEO_LABELS = {...}       # labels handled by get-media (Intro Video / Outro Video) -> skipped
drive_id(url)        -> str|None    # regex /file/d/<id>/ or ?id=<id>
to_download_url(id)  -> str         # uc?export=download&id=<id>
safe_filename(label) -> str         # trim; reject path separators/control chars; '<label>.png'
graphics_from_csv(rows) -> {label: url}   # every row whose URL is a Drive link (skip YouTube)
graphics_dir(here)   -> str         # repo runtime/graphics vs package graphics
fetch_assets_csv(sheet_id, tab)     # gviz CSV (same shape as get-media)
download(url, out_path)             # urllib GET + confirm-token fallback; write bytes
main()                              # --out, --sheet-id, --assets-tab (default 'Assets'),
                                    #   --only "<Label>[,<Label>...]" (optional filter)
```

- **Filename = sanitised label.** `safe_filename("Race Results")` → `Race Results.png`.
  Spaces are allowed (OBS already used `Season Schedule.png`). Reject `/`, `\\`, NUL and
  leading/trailing dots; otherwise verbatim. A label that sanitises to empty is skipped
  with a warning.
- **Row classification** is by URL, not by a label list: YouTube → skip (that's
  `get-media.py`); Google Drive → download. Unknown hosts → warn + skip.
- **Cookies** are not needed (public Drive links); no `cookies.txt` dependency.
- Exit non-zero listing any graphic that could not be downloaded (so the build's
  best-effort wrapper can note it), but never delete a previously-downloaded file on a
  failed refresh.

### 2. OBS collection `src/obs/IRO_Endurance.json`

- **Retokenise** every `__IRO_ASSETS__/<X>.png` → `__IRO_GRAPHICS__/<X>.png`, where
  `<X>` is the Assets label: `Overlay`, `Standings`, `Race Results`, `Quali Results`,
  `Post Race Interviews`, plus `Schedule` (was `Season Schedule.png`) and `Standby`
  (was `YT-IRO-Race.png`, used by both `Standby Cover` and `Thumbnail`).
- **Rename** source `Season Schedule` → `Schedule` so source name = file = label.
  (Source display names `Standby Cover`/`Thumbnail` keep their functional names; only
  their `file` changes to `__IRO_GRAPHICS__/Standby.png`.)
- **Add** 3 `image_source`s — `Race Weather 1`, `Race Weather 2`, `Quali Weather` —
  each `file: __IRO_GRAPHICS__/<Name>.png`, with fresh deterministic UUIDs.
- **Add** 3 scene items to the **Stint** scene, copying an existing graphic item's
  transform exactly: `visible:false`, `pos (0,0)`, `bounds_type:2`,
  `bounds (1920,1080)`. Placed above the feeds, like Standings/Results.

### 3. `src/setup-assets.py`

- Add `GRAPHICS_TOKEN = "__IRO_GRAPHICS__"` and `graphics_dir(base)` (sibling of
  `media_dir`). Add `--graphics` arg (default `graphics_dir(base)`).
- In `main()`, mirror the `__IRO_MEDIA__` block: if `GRAPHICS_TOKEN in raw`, map it to
  the graphics dir and **warn (not fail)** for any `<Label>.png` missing in that dir,
  listing them and pointing at `get-graphics.py`. Add a confirmation print line.
- Keep `ASSETS_TOKEN` handling (no-op when absent).

### 4. Companion `src/companion/iro-buttons.companionconfig`

- 3 new toggle buttons on **Page 1, column 7, rows 1–3** (the free right edge) — a
  "Weather" column. Labels kept short and readable, e.g. `Race Wx 1`, `Race Wx 2`,
  `Quali Wx` (final wording fixed during planning).
- Each button, copied from `Standings Toggle`:
  - step `down`: `toggle_scene_item` on scene `Stint`, source `<Weather source>`,
    `visible: toggle`.
  - feedback: `scene_item_active` on `Stint`/`<source>`, lit bgcolor `13421568`.
  - All new actions/feedbacks carry `upgradeIndex: 8`.
- Retarget the existing `Schedule Toggle` button's action+feedback `source` from
  `Season Schedule` to `Schedule` (the renamed source).

### 5. `tools/build.py`

- After the media download, add a best-effort `get-graphics.py --out <pkg>/graphics`
  (own try/except; build continues on failure, like media).
- **Verify** changes:
  - Replace `"obs tokenized": "__IRO_ASSETS__/" in tpl` with
    `"obs graphics tokenized": "__IRO_GRAPHICS__/" in tpl` (and keep the
    `"GoogleDrive"/drive.google.com not in tpl` leak check).
  - Soft, non-gating note per expected `<Label>.png` present in `<pkg>/graphics`
    (mirrors the media note).

### 6. `tools/tokenize-obs.py` and `tools/add_standby_cover.py`

- `tokenize-obs.py`: the regex that rewrites localised asset basenames back to a token
  targets `__IRO_GRAPHICS__` instead of `__IRO_ASSETS__`.
- `add_standby_cover.py`: the re-added `Standby Cover` source's `file` →
  `__IRO_GRAPHICS__/Standby.png`.

### 7. Tests — `tests/test_graphics.py` (new, stdlib, runnable script)

Load the hyphenated module via `importlib.util.spec_from_file_location` (as
`test_media.py` does). Cover:
- `drive_id` on both URL forms + a non-Drive URL (→ `None`).
- `to_download_url` shape.
- `safe_filename`: label → `<Label>.png`; rejects `/`, `\\`, control chars; trims.
- `graphics_from_csv`: picks Drive rows, skips YouTube rows, keys by label.
- `graphics_dir`: repo (`src/relay`) → `runtime/graphics`; package (`relay`) → `graphics`.

### 8. Docs

- **CLAUDE.md:** `load_dotenv` now **four** copies (add `get-graphics.py`); document
  `__IRO_GRAPHICS__`/`runtime/graphics`, `get-graphics.py`, and that broadcast graphics
  are pure-runtime (sheet-driven, not committed); `flags/`/`brands/` remain committed.
- **README.md:** `get-graphics.py` command line.
- **src/docs/README_SETUP.md:** prep step to fetch graphics.
- **Wiki:**
  - `OBS-Setup.md` — graphics now runtime-downloaded; add weather sources to the scene
    list; mention black-on-missing.
  - `Run-an-event.md` — prep step `get-graphics.py`; weather usage during the race.
  - `Director.md` — weather buttons in the Page-1 board + a beat on using them.
  - `Configuration.md` — `__IRO_GRAPHICS__` token alongside the others.
- **src/docs/IRO_cheat_sheets.html:** weather buttons in the Director card.

## Data flow (prep + runtime)

```
Producer (prep):
  python3 src/relay/get-graphics.py
    -> read .env (IRO_SHEET_ID) -> fetch Assets tab CSV
    -> for each Drive-link row: GET uc?export=download&id=<id>
       -> runtime/graphics/<Label>.png
  python3 src/setup-assets.py --out runtime/IRO_Endurance.import.json
    -> __IRO_GRAPHICS__ -> <repo>/runtime/graphics (warn on any missing <Label>.png)
  OBS: Import collection -> image_sources load runtime/graphics/<Label>.png

On air:
  Director presses a graphic/weather button (Companion)
    -> toggle_scene_item Stint/<source> visible -> overlay shows/hides
```

## Error handling

- **Missing graphic file:** OBS shows black for that source; `setup-assets.py` warns at
  localise time; `build.py` notes it (non-gating). Never fatal — same policy as media.
- **Sheet unreachable / row missing:** `get-graphics.py` warns per label, exits non-zero
  listing failures, leaves any prior file intact.
- **Bad/renamed label in Sheet:** the matching `<Label>.png` is simply not produced →
  OBS source black. Surfaced by the `setup-assets.py` missing-file warning. (This is the
  cost of label-as-filename; acceptable and explicit.)
- **Drive interstitial:** confirm-token fallback; if still HTML, treat as failure for
  that label (warn, continue).

## Security / constraints

- Pure stdlib; no new runtime deps (Drive download is `urllib`). English-only.
- Graphics live **only** in `runtime/graphics/` — never under `src/`, never committed
  (gitignored, like `runtime/media/`).
- No secrets/paths added to git; the Sheet ID still comes from the gitignored `.env`.
- No `.sh`/`.bat`.

## Open / optional (decide during planning)

- Exact Companion button captions for the three weather buttons.
- Whether `get-graphics.py` also accepts Intro/Outro-style per-asset CLI overrides
  (default: no — Sheet only).
- Whether to drop `ASSETS_TOKEN` entirely once the collection no longer uses it
  (default: keep the no-op resolver for backward compatibility).
