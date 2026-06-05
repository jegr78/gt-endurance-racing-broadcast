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
python3 tests/test_bind.py           # relay auto dual-bind (localhost + Tailscale IP)
python3 tests/test_companion.py      # Companion start/stop bind helpers
python3 tests/test_preflight.py      # preflight classifier unit checks
python3 tests/test_services.py       # daemon helper (PID/spawn/stop)
python3 tests/test_iro.py            # iro CLI routing
python3 tests/test_streams.py       # static-streams helpers (frozen feed spawn)
python3 tests/test_event.py          # event readiness helpers (probes/launch/assets)
python3 tests/test_installer_common.py  # shared installer helpers (brew bootstrap)
python3 tests/test_install_tools.py     # install-tools decision helpers
python3 tests/test_install_apps.py      # install-apps decision helpers
python3 tools/run-tests.py           # the whole suite (exactly what CI runs)
# Run ONE test function:
python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_pov_format_constant()"

# Build the distributable (assembles + self-verifies dist/)
python3 tools/build.py               # -> dist/IRO_Broadcast_Package/ + .zip
# Standalone binary (maintainer; CI builds all three OSes on tags v*)
python3 tools/build-binary.py        # -> dist/bin/iro (+ smoke test)

# Unified operator CLI (the producer's main entrypoint)
python3 src/iro.py relay start       # start the relay in the background
python3 src/iro.py relay stop        # stop it
python3 src/iro.py relay logs -f     # tail the relay log
python3 src/iro.py relay run         # foreground/debug mode
python3 src/iro.py companion start   # bind Companion to Tailscale IP and start it
python3 src/iro.py companion stop
python3 src/iro.py streams start     # static/public-stream mode
python3 src/iro.py streams stop
python3 src/iro.py status            # aggregate health of all services
python3 src/iro.py event status      # event-day readiness report (apps + services + assets)
python3 src/iro.py event start       # bring everything up (Tailscale, Discord, relay, OBS, Companion)
python3 src/iro.py event stop        # stop iro services; GUI apps keep running
python3 src/iro.py preflight         # hardware/tool check
python3 src/iro.py cookies firefox   # refresh YouTube cookies before an event (Firefox recommended; Windows Chrome/Edge exports are blocked by app-bound encryption)
python3 src/iro.py graphics          # download broadcast graphics -> runtime/graphics/
python3 src/iro.py media             # download Intro/Outro clips -> runtime/media/
python3 src/iro.py setup --out runtime/IRO_Endurance.import.json   # localize OBS collection
python3 src/iro.py install-tools     # install yt-dlp/streamlink/ffmpeg/deno (winget/brew/apt; bootstraps brew on macOS)
python3 src/iro.py install-apps      # install OBS/Companion/Tailscale/Discord (winget/brew/apt+official installers)
python3 src/iro.py export companion  # write the Companion button config for import
python3 src/iro.py --version

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
`src/relay/iro-feeds.py`, `src/setup-assets.py`, `src/relay/get-media.py`, and
`src/relay/get-graphics.py` — reads a `.env` only from the script dir or the project
root (marker: `.git`/`.env.example`), never an unrelated parent; real environment
variables take precedence. `.env.example` is the template.
Keep the four `load_dotenv` copies in sync if you touch one.

### Two token round-trips (keep paths/secrets out of git)
- **OBS.** `src/obs/IRO_Endurance.json` stores tokens: `__IRO_GRAPHICS__` (broadcast
  still-graphics dir), `__IRO_SHEET__` (HUD sheet), `__IRO_TIMER__` (stagetimer URL),
  `__IRO_MEDIA__` (Intro/Outro clip dir). When you edit scenes inside OBS, re-export
  and fold it back with `tools/tokenize-obs.py exported.json src/obs/IRO_Endurance.json`
  (regex-tokenizes sheet/timer URLs + image-source basenames). `src/setup-assets.py` does
  the reverse, injecting real values from `.env` into an importable collection. OBS
  stores **absolute** paths, so the localized collection must not be moved after
  import. `src/relay/get-media.py` downloads the Intro/Outro clips (sheet-driven via
  the Assets tab `Intro Video`/`Outro Video` labels, or `IRO_INTRO_URL`/
  `IRO_OUTRO_URL` env overrides) into `runtime/media/`; the `Intro`/`Outro` OBS
  scenes play them looping with audio.
- **Broadcast graphics are pure-runtime** (same model as the Intro/Outro clips): the
  still-graphics (Overlay, Standings, Schedule, Race/Quali Results, the three weather
  overlays, Standby, …) are **never committed**. `python3 src/relay/get-graphics.py`
  downloads each one from the Sheet **Assets** tab into `runtime/graphics/<Label>.png`
  (the Sheet label *is* the filename — no mapping table; YouTube Intro/Outro rows are
  skipped). They are tokenised `__IRO_GRAPHICS__/<Label>.png` in the collection and
  resolved by `setup-assets.py` (which warns, never fails, on a missing file → OBS shows
  black until you run `get-graphics.py`). `src/assets/` therefore now holds **only** the
  HUD `flags/` + `brands/` logos (still committed, relay-served).
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

Control is an **unauthenticated** `ThreadingHTTPServer` on port `8088` exposing GET
endpoints (`/next`, `/reload`, `/set/A/<n>`, `/pov/reload`, `/status`, `/panel`, …)
driven by Companion's Generic-HTTP module. `--bind` defaults to **`auto`** (plug &
play): it binds `127.0.0.1` (OBS always reaches the HUD/feeds on the fixed loopback
address — the OBS collection never needs editing) **and** this machine's Tailscale IP
(auto-detected via `detect_tailscale_ip()`, the `100.64.0.0/10` CGNAT range) when
present, so remote directors/tablets reach `/panel` + `/hud` over the tailnet — *without*
exposing the unauthenticated server on the local LAN the way `0.0.0.0` would. If
Tailscale is down, `auto` falls back to localhost-only (OBS keeps working). Pass an
explicit value (`127.0.0.1` for local-only, or `0.0.0.0`) to override. The endpoints
have no auth and `/status` reveals stream URLs, so the tailnet is the trust boundary —
keep it to invited members. Bind logic is pure + unit-tested: `tests/test_bind.py`.

The same server also hosts the **lower-third HUD** as one relay-served page,
replacing ~13 cropped Google-Sheets-editor browser sources (the old producer-lag
culprit): `/hud` serves `src/obs/hud.html`, `/hud/data` returns the overlay JSON
(`HudSource` reads the **Overlay** tab for live values + the **Configuration** tab's
brand-text column — header `Brand Name`/`Brand Key`/`Brand`, see `BRAND_TEXT_HEADERS` —
for team→manufacturer), and `/hud/assets/{flags,brands}/<name>`
serves bundled logos from `src/assets/`. The page polls `/hud/data` (no manual
reloads); flags/brands resolve from text via `asset_key()`. Flags: `--no-hud`,
`--overlay-tab`, `--config-tab`, `--hud-poll`. Tests: `tests/test_hud.py`.

### Unified `iro` CLI (`src/iro.py`)
`src/iro.py` is the single shipped entrypoint for operators. It dispatches to:
- **`src/scripts/services.py`** — daemon helper for the relay and static-streams: spawns
  subprocesses, writes PID + log files under `runtime/`, and provides start/stop/restart/
  status/logs for both. `iro relay run` is the foreground/debug mode (no daemon).
- **Companion adapter** (over `src/scripts/companion_common.py`) — `iro companion
  start/stop/restart/status/logs` wraps the Companion bind logic (Windows + macOS
  automated; Linux manual by design).
- **One-shot wrappers** — `iro preflight`, `iro cookies`, `iro graphics`, `iro media`,
  `iro setup` delegate to the corresponding `src/` modules without needing to remember
  individual script paths.
- **`iro status`** — aggregate health of relay + companion + streams at a glance.

`tools/` is maintainer-only (build, tokenize, sync) and is not shipped to producers.

### Standalone binary (PyInstaller)
`tools/build-binary.py` freezes `src/iro.py` into one executable per OS; the whole
`src/` tree ships as bundled data under `sys._MEIPASS/src/`, so here-relative path
resolution keeps working. In frozen mode (`sys.frozen`), `iro` runs bundled scripts
**in-process** (importlib + patched argv, string `sys.exit` payloads go to stderr)
and daemons re-invoke the binary itself (`iro relay run`, hidden `iro streams
run-feed`) with `PYINSTALLER_RESET_ENVIRONMENT=1` so each child extracts its own
bundle and outlives the parent. `runtime/` and `.env` live next to the binary —
keep it in its own folder. `services.py`/`companion_common.py` carry the per-OS
process control (Windows: ctypes PID probe — `os.kill(pid, 0)` would TERMINATE the
target there — taskkill/tasklist, Companion.exe discovery + `IRO_COMPANION_EXE`
override in `.env`; Linux Companion control is manual by design — in WSL/Docker
setups Companion runs on the host). Releases: merge the standing
**release-please** Release PR (or push a `v*` tag manually — both work) —
`.github/workflows/release.yml` tests, builds, smoke-tests and uploads
`iro-windows.zip` / `iro-macos.tar.gz` / `iro-linux.tar.gz` (each contains the
`iro` binary + `.env.example`; on first run the frozen binary copies it to `.env` —
see `ensure_env_file`). release-please tags via GITHUB_TOKEN, which cannot
trigger on-tag workflows, so `release-please.yml` dispatches `release.yml`
explicitly. `ci.yml` runs the suite on all
three OSes for every PR. Unsigned binaries: SmartScreen/Gatekeeper show a
one-time "run anyway" warning.

### Static mode (`src/scripts/`) — the simpler alternative
`loopstream.py` keeps one streamlink server alive for one public channel; `start-streams.py`
/ `stop-streams.py` manage a set of them with PID/log files under `runtime/static/`. This
is the fallback for public streams; the real unlisted-stream flow is the relay. Invoke via
`iro streams start/stop` — `start-streams.py`/`stop-streams.py` are logic modules, not
the operator entrypoint. `stop-streams.py` validates a PID actually belongs to a feed
process before killing.

### Companion remote-access helpers (`src/scripts/`)
`companion_common.py` (tests `tests/test_companion.py`) contains the pure logic that binds
**Bitfocus Companion**'s admin/web-buttons server to this machine's Tailscale IP so a tablet
can open `http://<tailscale-ip>:<port>/tablet` over the tailnet — same plug-&-play model as
the relay's `--bind auto`, and likewise **not** the LAN. It auto-detects the Tailscale IP
(duplicated `detect_tailscale_ip`, keep in sync with the relay), and — only while Companion
is stopped, with a `.iro-bak` backup — sets `bind_ip` in Companion's `config.json`
(`~/Library/Application Support/companion/config.json` on macOS; the GUI launcher reads
it as `--admin-address`). Windows + macOS automated (Windows: Companion.exe discovery +
`IRO_COMPANION_EXE` override in `.env`); Linux manual by design — in WSL/Docker setups
Companion runs on the host. Invoke via `iro companion start/stop`. **Important:**
binding only controls *where* Companion listens — Companion serves `/tablet` and the admin
GUI on one port + one shared socket API (its admin password is a casual deterrent, not a
boundary), so isolating the admin from directors is a **Tailscale-ACL** job (restrict who
reaches the port), not something these scripts can do. Editing `config.json` is
unsupported-but-stable; re-check after Companion upgrades.

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
