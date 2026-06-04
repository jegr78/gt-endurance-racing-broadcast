# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A self-contained broadcast-production toolkit for the "IRO Endurance" sim-racing
championship, run on a producer's machine (Windows, macOS, or Linux). The core is a **relay** that pulls one
commentator YouTube stream per race stint and serves it to OBS; around it sit an
OBS scene collection, a Stream Deck (Companion) button config, and operator docs.
Pure Python + stdlib (no framework, no package manager); external runtime deps are
`yt-dlp`, `streamlink`, `ffmpeg`, `deno` (installed via brew, not vendored).

## Hard rules

- **Edit only under `src/`.** `dist/` and `runtime/` are generated and gitignored —
  never hand-edit them. `tools/` are maintainer scripts (not shipped).
- **All scripts and docs must be English only.** (Chat with the user is German; the
  code/docs are read by an international team.)
- **Never hardcode secrets or machine paths.** Secrets come from `.env` (see below).
  The OBS collection and scripts are deliberately path/secret-free in git.
- Tooling is Python-only by design — do not reintroduce `.sh`/`.bat` (the build
  fails if any are shipped).

## Commands

```bash
# Tests (stdlib only — each file is a runnable script, no pytest)
python3 tests/test_pov.py            # relay POV/schedule unit checks
python3 tests/test_preflight.py      # preflight classifier unit checks
# Run ONE test function:
python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_pov_format_constant()"

# Build the distributable (assembles + self-verifies dist/)
python3 tools/build.py               # -> dist/IRO_Broadcast_Package/ + .zip

# Run the relay (the producer's main tool)
python3 tools/run-relay.py [extra relay args]   # wraps src/relay/iro-feeds.py --runtime-dir runtime

# Localize the OBS collection for this machine (tokens -> real paths/secrets)
python3 src/setup-assets.py --out runtime/IRO_Endurance.import.json

# Refresh YouTube cookies before an event (bot-check bypass)
python3 src/relay/get-cookies.py chrome --runtime-dir runtime

# Pre-flight hardware/tool check
python3 src/scripts/preflight.py

# Fetch any missing HUD country flags from the sheet's Configuration tab
python3 tools/fetch-flags.py            # adds missing -> src/assets/flags/ (keeps old)

# Publish the GitHub wiki from src/docs/wiki/ (maintainer; --dry-run to preview)
python3 tools/sync-wiki.py
```

After changing the relay, run `python3 tests/test_pov.py`; after any change that
ships, run `python3 tools/build.py` — its verify step is the closest thing to CI
(checks tokenization, blanked password, no secrets, preflight present, no shell
scripts).

## Architecture

### Single-source + build
`src/` is the only source of truth. `tools/build.py` copies it into
`dist/IRO_Broadcast_Package/` (the artifact handed to other producers), stripping
the Companion password and renaming the tokenized OBS collection to
`IRO_Endurance.template.json`. `runtime/` holds machine-local state (cookies, logs,
caches, the localized OBS import) and is gitignored. Helpers detect whether they run
from the repo (`src/...`) or the distributed package and pick paths accordingly —
see `default_runtime_dir()` (relay/get-cookies) and `state_dir()` (scripts).

### Secrets via `.env` (gitignored, repo root)
`IRO_SHEET_ID` (Google Sheet driving schedule + HUD) and `IRO_TIMER_URL` (signed
stagetimer output URL). A small bounded `load_dotenv()` — duplicated in
`src/relay/iro-feeds.py` and `src/setup-assets.py` — reads a `.env` only from the
script dir or the project root (marker: `.git`/`.env.example`), never an unrelated
parent; real environment variables take precedence. `.env.example` is the template.
Keep the two `load_dotenv` copies in sync if you touch one.

### Two token round-trips (keep paths/secrets out of git)
- **OBS.** `src/obs/IRO_Endurance.json` stores tokens: `__IRO_ASSETS__` (image
  paths), `__IRO_SHEET__` (HUD sheet), `__IRO_TIMER__` (stagetimer URL). When you
  edit scenes inside OBS, re-export and fold it back with
  `tools/tokenize-obs.py exported.json src/obs/IRO_Endurance.json` (regex-tokenizes
  sheet/timer URLs + asset basenames). `src/setup-assets.py` does the reverse,
  injecting real values from `.env` into an importable collection. OBS stores
  **absolute** asset paths, so the localized collection must not be moved after import.
- **Companion.** Export the config into the gitignored `incoming/` folder, then
  `tools/strip_companion_pass.py` blanks the WebSocket password and writes
  `src/companion/iro-buttons.companionconfig`. `build.py` re-strips defensively.

### The relay (`src/relay/iro-feeds.py`) — the heart
A 2-feed "ping-pong": **Feed A** (port 53001) serves odd stints, **Feed B** (53002)
even stints; at each handover the off-air feed advances to the next stint's
commentator stream, so OBS media sources never change URL. A 3rd **POV** feed
(53003) is an optional driver picture-in-picture, paused at start. The schedule is a
Google-Sheet tab read as CSV (no API key); a running feed is never torn off
mid-stint — sheet edits apply on the next `/next` (handover) or `/reload`.

Pull pipeline per feed: `yt-dlp -g` resolves the live HLS URL (passing YouTube's
bot-check via `cookies.txt` + deno JS challenge) → `streamlink --player-external-http`
serves that URL to one OBS client. (`curl`-ing the port returns nothing — it serves a
single consumer; that is not a failure.)

Control is an **unauthenticated** `ThreadingHTTPServer` (default `127.0.0.1:8088`)
exposing GET endpoints (`/next`, `/reload`, `/set/A/<n>`, `/pov/reload`, `/status`,
`/panel`, …) driven by Companion's Generic-HTTP module. `--bind 0.0.0.0` exposes it
for remote directors — prefer binding to the Tailscale IP, not all interfaces (the
endpoints have no auth and `/status` reveals stream URLs).

The same server also hosts the **lower-third HUD** as one relay-served page,
replacing ~13 cropped Google-Sheets-editor browser sources (the old producer-lag
culprit): `/hud` serves `src/obs/hud.html`, `/hud/data` returns the overlay JSON
(`HudSource` reads the **Overlay** tab for live values + the **Configuration** tab's
brand-text column — header `Brand Name`/`Brand Key`/`Brand`, see `BRAND_TEXT_HEADERS` —
for team→manufacturer), and `/hud/assets/{flags,brands}/<name>`
serves bundled logos from `src/assets/`. The page polls `/hud/data` (no manual
reloads); flags/brands resolve from text via `asset_key()`. Flags: `--no-hud`,
`--overlay-tab`, `--config-tab`, `--hud-poll`. Tests: `tests/test_hud.py`.

### Static mode (`src/scripts/`) — the simpler alternative
`start-streams.py` / `stop-streams.py` / `loopstream.py` launch one streamlink server
per **public** channel with PID/log files under `runtime/static/`. This is the
fallback for public streams; the real unlisted-stream flow is the relay.
`stop-streams.py` validates a PID actually belongs to a feed process before killing.

## Docs

- `README.md` — operator quickstart (the commands above).
- `src/docs/` — shipped operator material (`README_SETUP.md`,
  `IRO_Broadcast_Setup_Guide.md`, printable `IRO_cheat_sheets.html`).
- `src/docs/wiki/` — canonical source for the **GitHub wiki** (split-up onboarding
  pages + Mermaid architecture diagrams). The wiki is generated, never hand-edited on
  GitHub: edit these pages, then `python3 tools/sync-wiki.py` mirrors them to the
  `<origin>.wiki.git` repo (clones into `runtime/wiki/`, commits, pushes). First push
  per repo needs a one-time bootstrap — create+save any page via the GitHub Wiki UI so
  GitHub creates the wiki repo. See `src/docs/wiki/Maintaining-this-Wiki.md`.
- `docs/superpowers/{specs,plans}/` — design specs and implementation plans for
  features (POV PiP, repo structure, preflight). Read the matching spec before
  extending one of those features.
