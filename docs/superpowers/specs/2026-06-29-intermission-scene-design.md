# Intermission Scene — design

Status: approved (2026-06-29)

## Goal

Provide a producer-controllable **Intermission** scene for the broadcast: a
full-screen league background graphic, continuously looping music, and a live
read-only broadcast-chat box overlaid in a fixed, always-visible panel. Operable
from the **Director Panel** and the **Companion / Web Buttons**, following the
exact patterns the toolkit already uses for the Intro/Outro/Standby scenes and
the Sheet-driven asset pipeline.

This is a convenience/production feature: it must degrade gracefully (no
broadcast chat configured → empty box, never an error) and add **no new public
surface** beyond what already exists.

## Background (how the existing pieces work)

- **Graphics** come from the Sheet `Assets` tab (label = filename) and are
  downloaded by `src/relay/get-graphics.py` into `runtime/<profile>/graphics/<Label>.png`.
  They are tokenized `__RACECAST_GRAPHICS__/<Label>.png` in the OBS collection and
  resolved by `src/setup-assets.py`. A missing graphic is seeded with a transparent
  placeholder (`src/scripts/placeholders.py`). `Standby Cover` is exactly this pattern,
  inserted into the collection by the idempotent maintainer tool `tools/add_standby_cover.py`.
- **Media** (Intro/Outro) are downloaded by `src/relay/get-media.py` via `yt-dlp`
  from the `Assets` tab labels `Intro Video` / `Outro Video` into
  `runtime/<profile>/media/intro.mp4` / `outro.mp4`, played by looping `ffmpeg_source`
  OBS sources with audio (`__RACECAST_MEDIA__/…`). Missing → neutral placeholder clip.
- **Drive direct download** (with the large-file confirm-token interstitial) lives in
  `src/relay/get-graphics.py` (`is_drive_url`, `drive_id`, `to_download_url`, `download`).
- **Overlay pages** are relay-served: `OVERLAY_PAGES = ("hud", "splitscreen")`. Each
  page `X` serves `GET /X` (HTML), `GET /X/override.css` (per-league override read per
  request from `--overlay-dir`), and a data endpoint. `OBS_PAGE_PATHS` lists the served
  byte paths whose hash gates the obs-websocket `refreshnocache` on relay/event start.
- **Broadcast chat** is already mirrored read-only by the relay at `GET /broadcast-chat/data`
  (tailnet/loopback) — `{messages:[{ts,user,text,source[,tokens]}], target}` — and rendered
  in the cockpit/director/race-control pages with `textContent` (+ emote `<img>`), XSS-safe.
- **Director Panel** OBS control is relay-mediated: `POST /obs/scene`, `/obs/source`,
  `/obs/audio`, `/obs/state` → `src/scripts/obs_ws.py`. The panel (`src/director/director-panel.html`)
  drives scene-switch **macros** (`CONFIG.macros`) and **audio faders** (`CONFIG.audio`).
- **Companion** (`src/companion/racecast-buttons.companionconfig`) switches scenes via the
  native OBS plugin (`set_scene`, `set_source_mute`) — the Intro/Outro/Standby buttons are
  the template.

## Architecture

A dedicated OBS **scene** (not a Standby-style cover toggle), composed of three
sources, fed by one new graphic asset, one new music asset, and one new relay
overlay page. The chat box reuses the existing broadcast-chat data; no new data
endpoint and no new public surface.

### 1. OBS scene `Intermission`

New scene **`Intermission`**, sources bottom → top:

1. **`Intermission`** — full-screen `image_source`, file `__RACECAST_GRAPHICS__/Intermission.png`
   (pos `{0,0}`, bounds `{1920,1080}`, `bounds_type:2` = fit), like `Standby Cover`.
2. **`Intermission Chat`** — `browser_source`, url `http://127.0.0.1:8088/intermission`,
   1920×1080, transparent background, on top of the graphic.
3. **`Intermission Music`** — `ffmpeg_source`, file `__RACECAST_MEDIA__/intermission.mp3`,
   `looping:true`, `restart_on_activate:true`, `close_when_inactive:true`, mixers `255`
   (audio on), like the Intro/Outro video sources.

Inserted by a new idempotent maintainer tool **`tools/add_intermission_scene.py`**
(mirrors `tools/add_standby_cover.py`). It deep-copies existing objects as schema
templates — the `Intro` scene skeleton, the HUD `browser_source`, the `Intro Video`
`ffmpeg_source`, and the `Thumbnail` `image_source` — overriding identity (name/uuid),
file/url, and item geometry; it also registers the new scene in the collection's scene
list/order so OBS shows it. Re-running once `Intermission` exists is a no-op. The
maintainer runs it against `src/obs/GT_Endurance.json` and commits the result.

UUIDs follow the existing convention (A/B/POV use `aaaaaaaN-`, cover `bbbbbbb1-`); the
Intermission objects get a fresh distinct prefix.

### 2. Relay overlay page `/intermission`

- `OVERLAY_PAGES += ("intermission",)`.
- New page `src/obs/intermission.html` (sibling of `hud.html`/`splitscreen.html`):
  - Links `<link rel="stylesheet" href="/intermission/override.css">` last in `<head>`.
  - **Polls the existing `GET /broadcast-chat/data`** every ~4 s with `cache:"no-store"`,
    renders `messages` into the box. (Reusing the endpoint — no `/intermission/data`.)
  - Renders each message XSS-safe via `textContent` (+ emote `<img>` with alt-text
    fallback, mirroring the cockpit `bchatBody`). Optional small timestamp + source badge
    on a handover overlap.
  - **Box behaviour:** a fixed-height container with `overflow:hidden`, always pinned to
    the bottom (`scrollTop = scrollHeight` after each render — NO "stick only if at bottom"
    check, unlike the cockpit), DOM trimmed to the last ~50 messages so older ones scroll up
    and out of the box. A semi-transparent panel sits behind the text so it stays readable
    over any background image. **No auto-hide**: the box/panel is always present even when the
    chat is idle or empty.
- Routes in `src/relay/racecast-feeds.py`:
  - `GET /intermission` → serve `intermission.html`.
  - `GET /intermission/override.css` → `read_overlay_css(overlay_dir, "intermission")`.
- `OBS_PAGE_PATHS += ("/intermission", "/intermission/override.css")` so an edit to the
  page or the override advances the refresh hash and OBS reloads automatically.
- Layout is a sensible fixed default, overridable per league via
  `profiles/<name>/overlay/intermission.css` (cascade-wins, same model as `hud.css`).
  Fonts are served by the existing `/overlay/fonts/<file>`.

### 3. Music asset (Drive **and** yt-dlp)

- New `Assets` tab label **`Intermission Music`** → `runtime/<profile>/media/intermission.mp3`.
- `src/relay/get-media.py` gains handling for this label:
  - Resolve the URL like Intro/Outro (CLI/env/Sheet; env `RACECAST_INTERMISSION_MUSIC_URL`).
  - If the value is a **Drive** link → direct download (Drive confirm-token handling); else
    (YouTube/other http(s) URL) → `yt-dlp -x --audio-format mp3` → `intermission.mp3`.
  - Same `--`-before-URL flag-injection guard and http(s)-only validation as the existing
    `download()`.
- **Decision — duplicate the Drive helpers into `get-media.py`** (small copies of
  `is_drive_url`/`drive_id`/`to_download_url` + a binary Drive `download` without the PNG
  signature check), each setting its own `User-Agent`. Rationale: keeps `get-media.py`
  self-contained, matches the existing "duplicated load_dotenv (×4)" / pinned-`STREAMLINK_TWITCH`
  philosophy for these dependency-light relay scripts, and avoids a shared
  `src/scripts/drive_dl.py` that would fall under the `tests/test_http_util.py` UA guard
  (which covers `src/scripts/*` and forbids direct `urlopen`). A cross-check test pins the
  duplicated Drive logic against `get-graphics.py` to prevent drift. *Alternative considered:*
  a shared `src/scripts/drive_dl.py` added to the http_util exemption list (DRY, dedups
  `get-graphics.py`) — rejected as touching the hard-rule UA-guard surface and refactoring a
  working download path for more blast radius than the feature warrants.
- **Default / fallback audio:** a seamless **ambient loop** synthesized with ffmpeg,
  committed as `src/assets/placeholders/neutral-ambient-loop.mp3` (royalty-free because
  synthetic), generated by extending `tools/make-placeholders.py`. It becomes the
  audio placeholder for a missing `intermission.mp3`, so a profile without a Sheet music
  entry (the demo) plays this loop automatically.
- `src/scripts/placeholders.py`: add `MUSIC_PLACEHOLDER = "neutral-ambient-loop.mp3"` +
  `music_placeholder_path()`, and a per-filename selector so `intermission.mp3` →
  music placeholder while `intro.mp4`/`outro.mp4` → the existing video placeholder.
  `get-media.py` `seed_missing_media` and `src/setup-assets.py`'s media fill both use the
  selector.

### 4. Demo background graphic

Generate `runtime/demo/graphics/Intermission.png` in the GT DEMO look (dark
background, the demo logo, an `INTERMISSION` / "We'll be right back" line, teal
accent borders — matching `Standby Cover.png`), rendered from an SVG/HTML template
via the repo's existing headless-render tooling, for local UAT and wiki screenshots.

**Handoff:** the canonical demo asset lives in the demo Google Sheet's Drive (which
the maintainer owns and the agent cannot edit). The deliverable is the generated PNG
plus the two `Assets` rows to add (`Intermission`, `Intermission Music`); the
maintainer uploads/links them in the demo Sheet.

### 5. Control surfaces

- **Director Panel** (`src/director/director-panel.html`):
  - New `CONFIG.macros` entry **`INTERMISSION`**: scene `Intermission`, mute `Feed A`,
    `Feed B`, `Discord Audio Capture` (parity with the `INTRO`/`OUTRO` macros).
  - New `CONFIG.audio` fader for input `Intermission Music` (volume + mute), so the producer
    can ride the music level.
  - State sync (`obsStatePoll`) lights the macro button when `Intermission` is the program scene.
- **Companion** (`src/companion/racecast-buttons.companionconfig`):
  - New **`Intermission`** button near the Intro/Outro buttons: OBS `set_scene` → `Intermission`
    + `set_source_mute` true on the feeds/Discord; feedback lights when the program scene is
    `Intermission`. Optionally a music volume button on the audio page.

### 6. Template, docs, tests

- `src/docs/sheet-template/Assets.csv`: add `Intermission` and `Intermission Music` rows.
- Wiki (`src/docs/wiki/`): document the Intermission scene + the two new Assets rows in
  `Sheet-Template`, `OBS-Setup`, `Configuration`, `Director`, `Companion`, `Relay-Mode`
  as relevant; keep `tests/test_wiki.py` green (link/anchor checks).
- **Wiki screenshots (hard rule — same change):** the Director Panel and Companion are
  visible surfaces that change, so regenerate `src/docs/wiki/images/director-panel.png`
  (via the `wiki-screenshots` skill) and the relevant `companion-pageN-*.png` (via the
  `companion-screenshots` skill), and commit them alongside the code.
- Tests:
  - `get-media.py` music routing: Drive-vs-yt-dlp decision, output filename `intermission.mp3`,
    URL resolution priority, the flag-injection/http(s) guard, and the Drive-helper drift
    cross-check.
  - `placeholders.py`: `intermission.mp3` → music placeholder; `intro.mp4`/`outro.mp4` →
    video placeholder.
  - `tools/add_intermission_scene.py`: idempotent; produces the three sources + the scene
    registered in the scene list; correct file/url tokens and geometry.
  - Relay routing / `tests/test_overlay.py` + `tests/test_racecast.py`: `intermission` in
    `OVERLAY_PAGES`, `/intermission` + `/intermission/override.css` served, both in
    `OBS_PAGE_PATHS`.
  - Optional `tools/e2e_checks.py`: `/intermission` serves HTTP 200.

## Explicitly out of scope (YAGNI)

- No overlay-builder slot for the chat box — `intermission.css` override is enough.
- No new data endpoint — reuse `GET /broadcast-chat/data`.
- No auto-hide / fade logic for the box.
- No write path for the chat (it stays read-only/ephemeral, like the existing broadcast chat).

## Security / boundaries

- The chat box mirrors data that is already public on YouTube/Twitch; read-only, ephemeral.
- No new endpoint and no new Funnel surface: the page polls the existing tailnet/loopback
  `GET /broadcast-chat/data`; OBS reaches it on the fixed loopback. The `/console/*` Funnel
  mount is untouched. OBS-WebSocket is never funnelled.
- Sheet-supplied music URLs are validated http(s)-only and passed after `--` to yt-dlp;
  Drive downloads are host-checked (`is_drive_url`).

## Likely delivery (sequencing left to the plan)

Probably 2–3 PRs: (a) relay `/intermission` page + chat box + per-league override.css;
(b) asset pipeline — music download (Drive+yt-dlp) + ambient-loop placeholder +
`Assets.csv`; (c) `add_intermission_scene.py` + OBS collection + Director Panel/Companion
control + refreshed wiki screenshots + docs.
