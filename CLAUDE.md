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
- **Removing/renaming a CLI flag? Grep the whole repo — including `tools/` and
  `.github/`.** Those callers run only in the build/release pipeline, not in the
  test suite (a stale `--timer-url` in the binary smoke test broke every v1.0.0
  release build). CI's `binary-smoke` job now exercises the binary path on every
  PR, but grepping first is cheaper than a red pipeline.
- **Never invent domain rules or crew conventions.** Docs describe the
  *mechanism* (what a button/endpoint does); broadcast procedure (who goes on
  air when, with which feed) is defined by the team, not derived. State
  assumptions explicitly and ask when uncertain instead of asserting.
- **Tests must run on any machine and in CI** — no real IPs, no machine paths,
  no environment-specific values; use fixtures/parameters (Tailscale IPs are
  `100.64.0.0/10` test constants, never this machine's address). Prefer TDD:
  failing test first, then the fix.
- **Pipeline/permission problems (release-please, tokens, branch protection,
  Actions) are research-first:** map the complete lifecycle and requirement set
  (docs + known issues) before changing anything — one planned fix, not
  symptom-per-loop trial and error.

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
python3 tests/test_tailscale.py      # Tailscale detection/control helpers
python3 tests/test_obsws.py          # minimal obs-websocket client (feed release on stop, page refresh on start)
python3 tests/test_installer_common.py  # shared installer helpers (brew bootstrap)
python3 tests/test_install_tools.py     # install-tools decision helpers
python3 tests/test_install_apps.py      # install-apps decision helpers
python3 tests/test_init.py           # iro init wizard logic (plan/skip/gates)
python3 tests/test_timer.py          # relay race-timer unit checks
python3 tests/test_setup.py          # panel sheet-control (webhook payloads, SetupControl, endpoints)
python3 tests/test_ui_ops.py         # Control Center structured status providers + op registry
python3 tests/test_ui_jobs.py        # Control Center job manager (child spawn, line buffer)
python3 tests/test_ui_server.py      # Control Center HTTP server (routes, SSE, quit)
python3 tools/run-tests.py           # the whole suite (exactly what CI runs)
python3 tools/lint.py                # ruff lint (= the CI lint job); --fix auto-corrects.
                                     # Rules mirror the CodeQL alert classes — see ruff.toml.
                                     # Run it after changing any Python file.
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
python3 src/iro.py ui                # local Control Center web app (dashboard, service control, logs); port 8089 / IRO_UI_PORT
python3 src/iro.py event status      # event-day readiness report (apps + services + assets)
python3 src/iro.py event start       # bring everything up (Tailscale, Discord, relay, OBS, Companion); --stint N = mid-event takeover (stint N is on air; /set/stint/<n> corrects later)
python3 src/iro.py event stop        # stop iro services; GUI apps keep running
python3 src/iro.py tailscale up|down|status  # connect/disconnect/inspect Tailscale (event start connects automatically)
python3 src/iro.py obs refresh       # force-reload the relay-served OBS browser sources (HUD/timer)
python3 src/iro.py init              # guided first-time setup: .env gate, install-tools/-apps, cookies, graphics, media, setup, export companion, preflight — with skip-detection (--browser NAME, --skip-installs, --force)
python3 src/iro.py update            # self-update the binary from GitHub Releases (--tag TAG installs an exact release; UI previews use this)
python3 src/iro.py preflight         # hardware/tool check
python3 src/iro.py cookies firefox   # refresh YouTube cookies before an event (Firefox recommended; Windows Chrome/Edge exports are blocked by app-bound encryption)
python3 src/iro.py graphics          # download broadcast graphics -> runtime/graphics/
python3 src/iro.py media             # download Intro/Outro clips -> runtime/media/
python3 src/iro.py setup --out runtime/IRO_Endurance.import.json   # localize OBS collection
python3 src/iro.py install-tools     # install yt-dlp/streamlink/ffmpeg/deno (winget/brew/apt; bootstraps brew on macOS); --update also upgrades installed ones (pre-event)
python3 src/iro.py install-apps      # install OBS/Companion/Tailscale/Discord (winget/brew/apt+official installers); --update upgrades installed ones (Linux: prints per-app guide)
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
`IRO_SHEET_ID` (Google Sheet driving schedule + HUD) and `IRO_SHEET_PUSH_URL` (optional
Apps Script webhook that lets the relay write to the Sheet: race-timer state + the panel's HUD/Schedule/POV controls).
A small bounded `load_dotenv()` — duplicated in
`src/relay/iro-feeds.py`, `src/setup-assets.py`, `src/relay/get-media.py`, and
`src/relay/get-graphics.py` — reads a `.env` only from the script dir or the project
root (marker: `.git`/`.env.example`), never an unrelated parent; real environment
variables take precedence. `.env.example` is the template.
Keep the four `load_dotenv` copies in sync if you touch one.

### Two token round-trips (keep paths/secrets out of git)
- **OBS.** `src/obs/IRO_Endurance.json` stores tokens: `__IRO_GRAPHICS__` (broadcast
  still-graphics dir), `__IRO_SHEET__` (HUD sheet), `__IRO_MEDIA__` (Intro/Outro clip
  dir). The race timer is relay-served (`/timer`, fixed loopback URL in the collection —
  no token); state = Sheet tab `Timer` + `runtime/timer.json`, Director-controlled via
  `/timer/*` endpoints. **OBS browser sources cache JS aggressively:** after `hud.html`/`timer.html`
  change, OBS keeps the old page until refreshed. `iro relay start` and
  `iro event start` do that automatically — a hash gate over the *served* page
  bytes (`runtime/obs-pages.hash`) triggers obs-websocket `refreshnocache` on
  every browser source pointing at the relay; `iro obs refresh` forces it. The
  manual right-click → Refresh remains the fallback when obs-websocket is
  unreachable. Anything that must survive a reload therefore lives server-side
  (`runtime/timer.json`, the Sheet), never in page JS. When you edit scenes inside OBS, re-export and fold it back with
  `tools/tokenize-obs.py exported.json src/obs/IRO_Endurance.json`
  (regex-tokenizes sheet URLs + image-source basenames). `src/setup-assets.py` does
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
endpoints (`/next`, `/reload`, `/set/A/<n>`, `/pov/reload`, `/timer/*`, `/status`, `/panel`, …)
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

The panel's **sheet controls** write back through one Apps Script webhook
(`IRO_SHEET_PUSH_URL`, shared with the race timer — wiki: Sheet-Webhook):
Setup fields (Stint label/Streamer/Session/Race Control) are async-optimistic
(`HudSource` override now, sheet poll confirms, 30 s expiry), Schedule/POV URL
writes are synchronous; URL changes never auto-reload a feed. Setup "Stint" =
HUD display label, NOT the feed stint index. `SetupControl` + endpoints
`/setup/*`, `/schedule/*`, `/pov/set` (POST). Tests: `tests/test_setup.py`.

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
- **`src/scripts/obs_ws.py`** — minimal obs-websocket v5 client (stdlib only). After
  `relay stop`/`streams stop` kill the feeds, `_release_obs_feeds()` re-applies the
  feed media inputs' own settings via `SetInputSettings` — the one request that makes
  OBS rebuild the ffmpeg source and close its socket (media STOP/RESTART actions are
  ignored for inactive sources). Without it OBS pins the feed ports in FIN_WAIT_1
  until it restarts and preflight warns "port in use". Must run AFTER the kill (a
  rebuild against a live relay would just reconnect). Password auto-discovered from
  OBS's obs-websocket config.json (`IRO_OBS_WS_PASSWORD` in `.env` overrides). Fully
  best-effort: any failure prints one notice and the stop continues.

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

A separate **preview** channel (`.github/workflows/preview.yml`, helper
`tools/preview_meta.py`) publishes pre-release binaries for testing ahead of a
real release — triggered by the `preview` label on a PR or by `workflow_dispatch`
against a ref. Its tags are `preview-*` (never `v*`), so it never triggers
`release.yml` or release-please; `preview-cleanup.yml` deletes a PR's pre-release
on close.

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
(Tailscale detection/control lives in `src/scripts/tailscale.py`; its `detect_tailscale_ip` is duplicated in the standalone relay — keep those two in sync), and — only while Companion
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
