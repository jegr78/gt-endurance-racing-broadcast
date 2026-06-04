# Intro / Outro Videos — Design Spec

Date: 2026-06-04
Status: Approved (design); implementation plan pending

## Goal

Give the director two new, fully director-controllable broadcast elements: a
**stream intro** and a **stream outro** video. Each is a fixed YouTube clip
(intro `https://www.youtube.com/watch?v=HqlROA7of2M`,
outro `https://www.youtube.com/watch?v=POSsD0Pk7AU`) that:

- plays full-screen **with its own audio** on the broadcast,
- **loops** until the director switches away,
- is selected by a single **Companion button** (one for intro, one for outro),
- shows up as a dedicated **OBS scene** (`Intro`, `Outro`).

The clip URLs can change between seasons, so they are configured in the existing
Google Sheet (not hard-coded), and a snapshot of the downloaded clips ships inside
the `dist` package.

## Decisions (from brainstorming)

- **Sourcing:** download the clips locally once (via `yt-dlp`) and play them as a
  local OBS media file. Do **not** stream them through the relay and do **not**
  embed YouTube as a browser source. Rationale: frame-accurate, no buffering, no
  live-internet dependency, native looping + audio in OBS.
- **End behaviour:** loop the clip until the director switches scenes.
- **Audio:** the clip's audio is sent to the broadcast (same mixer routing as
  `Feed A`).
- **URL configuration:** in the Google Sheet `Configuration` tab, by label cell —
  a cell whose text is `Intro Video` / `Outro Video`, with the URL in the cell
  immediately to its right. Overridable via CLI args and `.env`.
- **dist bundling:** the clips are downloaded **at build time** by `build.py` and
  placed into the package. The clips are **never** stored under `src/` and never
  committed — they live only under `runtime/` (repo) or inside the built package.
- **Companion placement:** Page 1, Row 0, columns 5 and 6 (the free slots next to
  the existing scene-switch buttons `SPLIT · STINT A · STINT B · INTERVIEW ·
  STANDBY`).

## Non-goals (YAGNI)

- No relay endpoints, no relay code changes (Companion talks to OBS directly via
  the existing `set_scene` action).
- No auto-cut to a live scene at clip end (director switches manually; clip loops).
- No generalisation to the other sheet-driven assets (Standings/Schedule/Race
  Results PNGs) **yet** — see "Future extension" below. This spec implements
  intro/outro only, but keeps the fetch mechanism cleanly factored so that
  extension is a natural next step.

## Architecture

### New token: `__IRO_MEDIA__`

A fourth tokenisation token, alongside the existing `__IRO_ASSETS__`,
`__IRO_SHEET__`, `__IRO_TIMER__`. It resolves to the absolute path of the folder
holding `intro.mp4` / `outro.mp4`. A separate token (rather than reusing
`__IRO_ASSETS__`) keeps the committed image assets (`src/assets/`) cleanly
separated from the never-committed downloaded clips (`runtime/media` / package
`media/`).

### Path resolution: `media_dir()`

A small helper that mirrors `default_runtime_dir()` in
`src/relay/iro-feeds.py` / `src/relay/get-cookies.py`:

- **Repo layout** (`src/relay/`): clips live in `<repo>/runtime/media`.
- **Distributed package** (`relay/` at package root): clips live in
  `<package>/media`.

The same detection is used by `get-media.py` (where to write) and by
`setup-assets.py` (default `--media` dir, where to read).

### Components

```
Google Sheet (Configuration tab: "Intro Video"/"Outro Video" label cells)
        │  gviz CSV (existing mechanism)
        ▼
src/relay/get-media.py ──yt-dlp──▶  runtime/media/intro.mp4, outro.mp4
        ▲                                   │
        │ (build.py invokes with            │ (setup-assets.py resolves
        │  --out <pkg>/media)               │  __IRO_MEDIA__ → abs path)
        ▼                                   ▼
dist package media/intro.mp4        OBS scenes Intro / Outro
                                    (ffmpeg_source, looping, audio)
                                            ▲
                                            │ set_scene
                                    Companion buttons INTRO / OUTRO
```

## Detailed component design

### 1. `src/relay/get-media.py` (new, shipped — like `get-cookies.py`)

Purpose: resolve the configured intro/outro URLs and download the clips.

- **URL resolution priority:**
  1. CLI: `--intro-url`, `--outro-url`.
  2. Env / `.env`: `IRO_INTRO_URL`, `IRO_OUTRO_URL` (uses the same bounded
     `load_dotenv()` already present in `setup-assets.py` / `iro-feeds.py`).
  3. Google Sheet `Configuration` tab via the existing gviz CSV URL (built from
     `IRO_SHEET_ID` + `--config-tab`, default `Configuration`).
- **Sheet lookup (pure, testable):**
  `media_urls_from_csv(rows) -> {"intro": url, "outro": url}` — scans the parsed
  CSV for a cell equal (case-insensitive, trimmed) to `Intro Video` /
  `Outro Video` and takes the next non-empty cell to its right on the same row.
  Returns only what it finds (partial allowed). Mirrors the locate-by-label style
  of `parse_config_brands()` so column positions can move.
- **Download:** `yt-dlp` with a format that yields a single muxed MP4 with audio,
  capped at 1080p, e.g.
  `-f "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b"
  --merge-output-format mp4`, output `intro.mp4` / `outro.mp4` in the media dir.
  Reuses `runtime/cookies.txt` if present (`--cookies`), consistent with the
  relay's bot-check handling. (Public videos likely need no cookies, but reuse is
  free and robust.)
- **CLI:** `--out DIR` (default `media_dir()`), `--config-tab`, `--sheet-id`
  (default env), `--intro-url`, `--outro-url`, and a `--which intro|outro|both`
  selector (default `both`). Missing URL for a requested clip → clear error;
  best-effort note when run from `build.py` (see below).
- **English-only**, stdlib + `yt-dlp` subprocess only (no new deps).

### 2. OBS collection `src/obs/IRO_Endurance.json`

Two new scenes, each with one media source. Modelled on the existing `Standby`
scene (single source) and `Feed A`'s `ffmpeg_source` audio settings.

- Scene `Intro` (new UUID), Scene `Outro` (new UUID); both added to `scene_order`
  (placed after `Standby`, before `Discord`, or end — order is cosmetic).
- Source `Intro Video` / `Outro Video`, `id: "ffmpeg_source"`, settings:
  - `"is_local_file": true`
  - `"local_file": "__IRO_MEDIA__/intro.mp4"` (resp. `outro.mp4`) — the
    `ffmpeg_source` local-file key (`local_file`, with `input` empty), matching how
    OBS serialises a local media source.
  - `"looping": true`
  - `"restart_on_activate": true` (restart from frame 0 when the scene goes live)
  - `"close_when_inactive": true` (release the file/decoder when not shown)
  - `"hw_decode": true`, `"clear_on_media_end": false`
  - audio: `mixers` bitmask matching `Feed A` so the clip audio reaches the same
    broadcast tracks; `volume` 1.0, not muted.
- No `setup-assets.py` token other than `__IRO_MEDIA__` is introduced into these
  sources. Image/overlay sources are intentionally **not** added to these scenes
  (intro/outro are standalone full-screen clips).

### 3. `src/setup-assets.py`

- Add `--media` arg, default `media_dir()` (new helper mirroring
  `default_runtime_dir`).
- Extend `mapping` so that **iff** `__IRO_MEDIA__` appears in the collection, it is
  replaced with the absolute media dir.
- Missing clip files → **warning** (printed), not a fatal error — intro/outro are
  optional and the producer may legitimately not use them. (Contrast with
  `__IRO_SHEET__` / `__IRO_TIMER__`, which stay fatal because those sources are
  always present and useless without a value.)
- Keep the two `load_dotenv` copies (`setup-assets.py`, `iro-feeds.py`) in sync per
  the existing rule (this change touches neither's `load_dotenv`).

### 4. Companion `src/companion/iro-buttons.companionconfig`

Two new buttons on **Page 1**:

- Row `0`, Column `5`: text `INTRO`, OBS `set_scene` action → scene `Intro`.
- Row `0`, Column `6`: text `OUTRO`, OBS `set_scene` action → scene `Outro`.

Reuse the exact action shape of the existing scene-switch buttons (same OBS
`connectionId`, `definitionId: "set_scene"`, `scene` option). New action `id`s are
fresh unique strings. Style (size/colour) matches the neighbouring Row-0 buttons.

### 5. `tools/build.py`

- After copying `assets/` etc., create `<pkg>/media/` and invoke
  `python3 src/relay/get-media.py --out <pkg>/media` (so the package ships a clip
  snapshot).
- **Best-effort:** wrap the fetch so a failure (no network / no URL / yt-dlp
  missing) prints a warning and continues — code-only and offline builds stay
  green. This honours "download at build time" without making the build (the
  closest thing to CI) network-brittle.
- Verify additions:
  - `"obs media tokenized": "__IRO_MEDIA__/" in tpl` (collection references the
    token, no raw machine path leaks) — only asserted if the collection contains
    intro/outro sources.
  - Soft note (printed, non-failing) reporting whether `intro.mp4` / `outro.mp4`
    are present in `<pkg>/media`.
- `get-media.py` ships automatically via the existing `cp("relay", "relay")`.

### 6. Tests — `tests/test_media.py` (new)

Stdlib-only runnable script (same style as `tests/test_pov.py` /
`tests/test_hud.py`). Covers `media_urls_from_csv()`:

- label found, URL in adjacent cell → correct mapping;
- label present but no URL to the right → omitted;
- case/whitespace-insensitive label match;
- moved columns still resolve (locate-by-label, not by fixed index);
- empty / malformed CSV → `{}`.

### 7. Docs

- `README.md`: add a command line for `get-media.py` (event-prep, near
  `get-cookies.py`).
- `src/docs/README_SETUP.md`: short operator note (when/why to refresh clips,
  that URLs come from the sheet `Configuration` tab).
- `src/docs/IRO_cheat_sheets.html`: mention the two new buttons.
- Wiki page(s) under `src/docs/wiki/`: note the Intro/Outro scenes + buttons.
- Regenerate Companion wiki screenshots afterwards via the `companion-screenshots`
  skill (out of band; not a code change).
- `.gitignore`: no change needed (`runtime/` and `dist/` already ignored; clips
  never live under `src/`).

## Data flow (runtime)

1. Operator (or `build.py`) runs `get-media.py` → reads URLs from the sheet →
   `yt-dlp` writes `intro.mp4` / `outro.mp4` into the media dir.
2. `setup-assets.py` localises the OBS collection, resolving `__IRO_MEDIA__` to the
   absolute media dir.
3. Producer imports the localised collection into OBS.
4. Director clicks Companion `INTRO` / `OUTRO` → OBS `set_scene` → the scene goes
   live → `restart_on_activate` plays the clip from frame 0, `looping` repeats it,
   audio is on the broadcast.
5. Director clicks any other scene button to leave; `close_when_inactive` releases
   the clip.

## Error handling

- **Clip missing at show time:** OBS shows the source as missing/black; the rest of
  the broadcast is unaffected. `setup-assets.py` warns at localise time;
  (optional, see below) preflight can warn too.
- **URL not in sheet / fetch fails:** `get-media.py` exits non-zero with a clear
  message when run directly; `build.py` downgrades it to a warning so builds
  proceed.
- **No new attack surface:** no new network listener, no new relay endpoint, no
  secret added. URLs are public YouTube links; the sheet ID stays in `.env`.

## Open / optional (decide during planning)

- **Preflight check:** optionally add a soft "intro/outro clip present" check to
  `src/scripts/preflight.py` (+ `tests/test_preflight.py`). Low cost, nice-to-have;
  can be deferred.
- **Clip filename/format edge cases:** confirm the exact `ffmpeg_source`
  local-file key name (`local_file`) against a freshly exported OBS source before
  finalising the JSON, to match the running OBS version's serialisation.

## Future extension (not in scope)

The "label in the `Configuration` tab → URL → download → tokenised local path"
pipeline generalises: the same `get-media.py` could later fetch the
Standings / Schedule / Race-Results graphics the same way (their own labels +
their own token or a typed sub-folder), letting the team maintain almost
everything from the sheet. Keep `media_urls_from_csv()` and the download routine
factored so a typed/multi-asset version is an additive change, not a rewrite.
