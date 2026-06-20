# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A self-contained broadcast-production toolkit (**GT Endurance Racing Broadcast**) for
sim-racing endurance leagues, run on a producer's machine (Windows, macOS, or Linux).
The core is a **relay** that pulls one commentator YouTube or Twitch stream per race stint
and serves it to OBS; around it sit an OBS scene collection, a Stream Deck (Companion)
button config, and operator docs. It is **multi-profile**: one install hosts several
leagues, each as a `profiles/<name>/` directory (league config + optional per-league
overlay CSS); the active profile is switchable. Pure Python + stdlib (no framework,
no package manager); external runtime deps are `yt-dlp`, `streamlink`, `ffmpeg`,
`deno` (installed via brew, not vendored).

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
- **Cross-platform paths: the test matrix includes Windows.** A helper that
  assembles a *fixed-OS* absolute path — e.g. a macOS `/Applications/<App>.app`
  bundle — must build it with explicit forward slashes (`bundle +
  "/Contents/Info.plist"`), NOT `os.path.join`. `os.path.join` injects
  backslashes on the Windows runner, so a unit test that exercises that helper
  (with a POSIX path pinned in the fixture) passes on macOS/Linux but fails on
  `windows-latest` — even though production only ever runs the helper on its own
  OS. Use `os.path.join` only for paths on the *current* machine; never run it on
  a path you already know belongs to a different OS. (Broke #97's Windows CI.)
- **Pipeline/permission problems (release-please, tokens, branch protection,
  Actions) are research-first:** map the complete lifecycle and requirement set
  (docs + known issues) before changing anything — one planned fix, not
  symptom-per-loop trial and error.
- **Changed a UI surface? Refresh its wiki screenshot in the SAME change.** This
  is the step that keeps getting forgotten. Any visible change to the **Control
  Center** (`src/ui/`), the **Director Panel** (`/panel`), or the **Companion /
  Web Buttons** means the matching image under `src/docs/wiki/images/` is now
  stale and MUST be regenerated and committed alongside the code — never as a
  "later" follow-up. Surface → image: Control Center views → `cc-<view>.png`
  (e.g. the overlay builder → `cc-overlay-builder.png`); Director Panel →
  `director-panel.png`; Companion pages → `companion-page<N>-*.png`. How to
  recapture: Companion buttons via the **`companion-screenshots`** skill;
  Control Center / Director Panel by driving a running instance with the
  Playwright MCP and taking an **element** screenshot of the relevant card/modal
  (e.g. `#ov-modal .ovmodal-card`) so the framing matches the existing images —
  not a full-window grab. **Always capture Control Center screenshots from a local
  dev build** (run `racecast ui` straight from `src/`, no `VERSION` file stamped) so
  every `cc-*.png` shows the same "dev build" version badge. A real version baked into
  one shot goes stale at the next release and breaks uniformity — the dev-build state
  is the only fully reproducible one. If you refresh a single `cc-*.png`, still use the
  dev build so it matches the rest. Publishing the wiki itself stays a separate
  `tools/sync-wiki.py` step, but the image must already be committed in the repo.

## Commands

```bash
# Tests (stdlib only — each file is a runnable script, no pytest)
python3 tests/test_pov.py            # relay POV/schedule unit checks
python3 tests/test_bind.py           # relay auto dual-bind (localhost + Tailscale IP)
python3 tests/test_companion.py      # Companion start/stop bind helpers
python3 tests/test_preflight.py      # preflight classifier unit checks
python3 tests/test_services.py       # daemon helper (PID/spawn/stop)
python3 tests/test_racecast.py            # racecast CLI routing
python3 tests/test_config.py         # profile/config resolver (machine .env + profile.env, active pointer)
python3 tests/test_profile.py        # profile admin (list/show/use/new --from)
python3 tests/test_overlay.py        # per-league overlay overrides (hud/timer CSS + fonts serving)
python3 tests/test_streams.py       # static-streams helpers (frozen feed spawn)
python3 tests/test_roles.py          # crew roster (CrewSource) + role resolution (#216)
python3 tests/test_console.py        # /console authorization policy: capability matrix + decision (#216)
python3 tests/test_console_gate.py   # /console auth gate: token->roles->decide fall-through (#216)
python3 tests/test_event.py          # event readiness helpers (probes/launch/assets)
python3 tests/test_tailscale.py      # Tailscale detection/control helpers
python3 tests/test_obsws.py          # minimal obs-websocket client (feed release on stop, page refresh on start)
python3 tests/test_discord_web.py    # Discord-web/browser capture decision (native-vs-web, browser target)
python3 tests/test_discord_oauth.py  # pure Discord OAuth helpers (state HMAC, handle match, token mint)
python3 tests/test_installer_common.py  # shared installer helpers (brew bootstrap)
python3 tests/test_install_tools.py     # install-tools decision helpers
python3 tests/test_install_apps.py      # install-apps decision helpers
python3 tests/test_init.py           # racecast init wizard logic (plan/skip/gates)
python3 tests/test_timer.py          # relay race-timer unit checks
python3 tests/test_chat.py           # crew chat (ChatStore + chat_admin + endpoints)
python3 tests/test_submissions.py    # cockpit stream-link submissions (pending store + own-row resolver + endpoints)
python3 tests/test_event_title.py    # free-text event title (#207): sanitizer + EventTitleStore + /event/title + /status + /cockpit/data
python3 tests/test_backup.py         # profile look backups (zip snapshot create/list/restore/delete)
python3 tests/test_setup.py          # panel sheet-control (webhook payloads, SetupControl, endpoints)
python3 tests/test_ui_ops.py         # Control Center structured status providers + op registry
python3 tests/test_ui_jobs.py        # Control Center job manager (child spawn, line buffer)
python3 tests/test_ui_server.py      # Control Center HTTP server (routes, SSE, quit)
python3 tests/test_e2e.py            # e2e-harness pure pieces (free-port, CSV builder, check registry, gates)
python3 tests/test_logs.py           # rotating logger, prune, subprocess pump, OBS dir, archive resolution
python3 tools/run-tests.py           # the whole suite (exactly what CI runs)
python3 tools/lint.py                # ruff lint (= the CI lint job); --fix auto-corrects.
                                     # Rules mirror the CodeQL alert classes — see ruff.toml.
                                     # Run it after changing any Python file.
# Run ONE test function:
python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_pov_format_constant()"

# Build the distributable (assembles + self-verifies dist/)
python3 tools/build.py               # -> dist/GT_Racecast_Package/ + .zip
# Standalone binary (maintainer; CI builds all three OSes on tags v*)
python3 tools/build-binary.py        # -> dist/bin/racecast + dist/bin/racecast-ui (+ smoke test)

# End-to-end / regression harness (maintainer; stands up relay + Control Center, asserts the live HTTP surface)
python3 tools/e2e.py                  # synthetic mode: self-contained, no real Sheet/cookies/OBS — the CI `e2e` job runs this
python3 tools/e2e.py --real-league NAME   # local-only: drive the copied real-league dev build (refuses under CI)
python3 tools/e2e.py --playwright [--headed] [--shots DIR]  # optional rendered checks / visible browser / MCP-free screenshot tour

# Unified operator CLI (the producer's main entrypoint)
python3 src/racecast.py relay start       # start the relay in the background
python3 src/racecast.py relay stop        # stop it
python3 src/racecast.py relay logs -f     # tail the relay log (console + feed_A/B/POV, merged)
python3 src/racecast.py relay logs --list                  # list available archive dates
python3 src/racecast.py relay logs --archive 2026-06-17   # read a past day's rotated log
python3 src/racecast.py relay run         # foreground/debug mode
python3 src/racecast.py companion enable-control  # Linux only: one-time setup (systemd drop-in + root helper + sudoers rule)
python3 src/racecast.py companion start   # bind Companion to Tailscale IP and start it
python3 src/racecast.py companion stop
python3 src/racecast.py streams start     # static/public-stream mode
python3 src/racecast.py streams stop
python3 src/racecast.py status            # aggregate health of all services
python3 src/racecast.py ui                # local Control Center web app (dashboard, service control, logs, profiles, settings); port 8089 / RACECAST_UI_PORT
python3 src/racecast.py profile list      # list league profiles (profiles/<name>/profile.env)
python3 src/racecast.py profile show      # show the active profile's resolved league config (add <name> for another)
python3 src/racecast.py profile use NAME  # switch the active profile (writes runtime/active-profile)
python3 src/racecast.py profile new NAME  # scaffold a new league profile (--from SRC copies an existing one)
python3 src/racecast.py profile export NAME      # export a league profile to a portable zip (--no-assets, --out PATH)
python3 src/racecast.py profile import FILE       # import a profile bundle (--force to replace an existing one)
python3 src/racecast.py --profile NAME <command>  # run ONE command against a non-active profile
python3 src/racecast.py event status      # event-day readiness report (apps + services + assets)
python3 src/racecast.py event start       # bring everything up (Tailscale, Discord, relay, OBS, Companion); --stint N = mid-event takeover (stint N is on air; /set/stint/<n> corrects later); --qualifying = qualifying mode (Feed A serves the Qualifying tab; switch live via /mode/race|/mode/qualifying or the panel); --title "…" = free-text event title shown in Panel/Cockpit/Discord (#207; also editable live in the panel, persisted to runtime/<profile>/event.json, pulled from producer A at takeover)
python3 src/racecast.py event takeover <A-ip> [--stint N]  # take over from A over the tailnet: read on-air stint+league from /status, pull chat+cockpit-versions, bring up at that stint
python3 src/racecast.py event takeover <A-magicdns-host> --funnel [--stint N]  # same but over the public Funnel — no Tailscale account needed on B; authenticated with the shared league CONSOLE_SECRET (step-up via X-Console-Secret header); calls /console/takeover/{status,chat,versions}; status is redacted (live/league/event_title/timer/mode only — feed stream URLs never leave the tailnet)
python3 src/racecast.py event stop        # stop racecast services; GUI apps keep running
python3 src/racecast.py tailscale up|down|status  # connect/disconnect/inspect Tailscale (event start connects automatically)
python3 src/racecast.py obs refresh       # force-reload the relay-served OBS browser sources (HUD/timer)
python3 src/racecast.py obs collection    # check the active OBS scene collection (add `set` to switch to the active profile's collection)
python3 src/racecast.py obs logs          # tail the newest OBS Studio log (read-only, not rotated by racecast)
python3 src/racecast.py tailscale logs    # tail the tailscale.snapshot.log (timestamped `tailscale status` blocks, appended on start + racecast tailscale status)
python3 src/racecast.py sheet open        # open the active league's Google Sheet in the browser (built from its SHEET_ID); `sheet url` prints the link. Also an "Open Sheet ↗" button in the Control Center Profile view.
python3 src/racecast.py init              # guided first-time setup: .env gate, profile select, install-tools/-apps, cookies, graphics, media, setup, export companion, preflight — with skip-detection (--browser NAME, --skip-installs, --force)
python3 src/racecast.py update            # self-update the binary from GitHub Releases (--tag TAG installs an exact release; UI previews use this)
python3 src/racecast.py freeport          # free a stuck feed port (default 53001-53003); kills an orphaned holder so a feed can bind. Refuses a running relay/streams (would cut a live feed) unless --force. Cross-platform port→PID (lsof/ss/fuser/netstat) in src/scripts/ports.py; per-process kill (not the session-group kill of #133's stop path). Also a Control Center action (free-ports op) + a `relay start` warning when a feed port is already bound.
python3 src/racecast.py preflight         # hardware/tool check
python3 src/racecast.py speedtest          # opt-in Ookla bandwidth test; logs locally, preflight warns vs 25/10 Mbps
python3 src/racecast.py cookies firefox          # refresh YouTube cookies before an event (Firefox recommended; Windows Chrome/Edge exports are blocked by app-bound encryption)
python3 src/racecast.py cookies twitch firefox   # refresh Twitch cookies (only needed for gated sub/follower-only Twitch feeds)
python3 src/racecast.py graphics          # download broadcast graphics -> runtime/<profile>/graphics/
python3 src/racecast.py media             # download Intro/Outro clips -> runtime/<profile>/media/
python3 src/racecast.py setup --out runtime/<profile>/GT_Endurance.import.json   # localize OBS collection
python3 src/racecast.py install-tools     # install yt-dlp/streamlink/ffmpeg/deno (winget/brew/apt — Linux apt runs via sudo; deno has no apt pkg so it's a pinned, SHA-256-verified GitHub-release download into runtime/bin, which racecast adds to PATH; bootstraps brew on macOS); --update also upgrades installed ones (pre-event)
python3 src/racecast.py install-apps      # install OBS/Companion/Tailscale/Discord (winget/brew/apt+official installers); --update upgrades installed ones (Linux: prints per-app guide)
python3 src/racecast.py obs-browser       # Linux only: build & install OBS's Browser Source plugin (obs-browser + CEF) from source — the distro/PPA ships none on aarch64, and the relay HUD/timer need a Browser Source. Pins CEF per OBS version (see obs_browser_linux.py); --yes skips the prompt. On no-GPU/VM hosts also disable OBS Browser Source Hardware Acceleration.
python3 src/racecast.py export companion  # write the Companion button config for import
python3 src/racecast.py chat clear        # wipe the crew-chat history on the active relay
python3 src/racecast.py chat pull <ip>    # take over another producer's chat history at handover (relay may be running)
python3 src/racecast.py chat import <file> # load a previously exported JSON file into the relay
python3 src/racecast.py chat export       # write the current chat history to chat-export.json (or --out PATH)
python3 src/racecast.py backup create|list|restore|delete <label>  # named look snapshots (overlay+graphics+media) per profile
python3 src/racecast.py cockpit enable     # talent Commentator Cockpit: generate a per-league secret + turn it on for this machine (#191)
python3 src/racecast.py cockpit disable    # stop serving /cockpit on this machine
python3 src/racecast.py links              # print per-person /console launcher links (Crew tab ∪ live Schedule); --post drops them into crew chat
python3 src/racecast.py funnel on|off  # public ingress for ONLY /console (the role-adaptive crew launcher) via Tailscale Funnel (needs MagicDNS+HTTPS+funnel nodeAttr)
python3 src/racecast.py cockpit setup-funnel    # automate the one-time tailnet prereqs (MagicDNS + funnel nodeAttr) via a Tailscale API access token; --apply to perform (dry-run default)
python3 src/racecast.py cockpit token revoke <streamer>  # rotate one commentator's link (bumps their version)
python3 src/racecast.py --version

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
`dist/GT_Racecast_Package/` (the artifact handed to other producers), stripping
the Companion password and renaming the tokenized OBS collection to
`GT_Endurance.template.json`. `runtime/` holds machine-local state (cookies, logs,
caches, the localized OBS import) and is gitignored. Helpers detect whether they run
from the repo (`src/...`) or the distributed package and pick paths accordingly —
see `default_runtime_dir()` (relay/get-cookies) and `state_dir()` (scripts).

### Profiles + config (`src/scripts/config.py`) — the multi-profile model
Config comes from **two layers** and one resolver:
- **Machine `.env`** (gitignored, repo root or next to the binary; template
  `.env.example`) holds ONLY machine-local knobs — never league secrets:
  `RACECAST_OBS_WS_PASSWORD`, `RACECAST_COMPANION_EXE`, `RACECAST_UI_PORT`,
  `RACECAST_UI_PASSWORD` (reserved/unused), and `RACECAST_PROFILE` (default active
  profile when no `--profile` is given).
- **`profiles/<name>/profile.env`** is the **league** — un-prefixed keys `NAME`,
  `SHEET_ID` (Google Sheet driving schedule + HUD), `SHEET_PUSH_URL` (optional Apps
  Script webhook that lets the relay write to the Sheet: race-timer state + the
  panel's HUD/Schedule/POV controls), `INTRO_URL`, `OUTRO_URL`, `LOGO`,
  `OBS_COLLECTION`, `CONSOLE_SECRET` (signs per-person console tokens; auto-provisioned
  on first relay start), and optionally `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET`
  (per-league Discord OAuth app — when present, `/console/login` + `/console/oauth/callback`
  are activated; when absent, OAuth is off and signed links remain the only entry path).
  The shipped `profiles/example/` is a template, excluded from the usable-league list.
  One install hosts several leagues this way.

`src/scripts/config.py` is the resolver: it parses the machine `.env` + the selected
`profiles/<name>/profile.env`, picks the active profile (precedence: `--profile` >
`RACECAST_PROFILE` env > `runtime/active-profile` pointer file > the sole profile when
exactly one exists), and returns a `ResolvedConfig`. The CLI then **injects** the
active league's values into child processes as **prefixed** env vars
(`RACECAST_SHEET_ID`, `RACECAST_SHEET_PUSH_URL`, `RACECAST_INTRO_URL`,
`RACECAST_OUTRO_URL`, `RACECAST_OBS_COLLECTION` — see `_profile_env_vars` /
`_apply_active_profile_env` in `src/racecast.py`), so the relay and the asset
downloaders read a flat environment and stay profile-agnostic. `racecast profile
list|show|use|new|export|import [--from/--no-assets/--out/--force]` manages profiles;
global `--profile NAME` runs one command against a non-active profile. `racecast
profile export NAME` packages the entire `profiles/<name>/` tree (including
`SHEET_PUSH_URL` in `profile.env`) plus the optional runtime `graphics/` and `media/`
into a single zip that can be imported on another machine with `racecast profile
import FILE` — this is the onboarding path for handing a league to a new producer.
This is distinct from `racecast backup …` (`backup_admin.py`), which is a
profile-internal named snapshot of the overlay CSS + graphics + media only and never
crosses machines.

A small bounded `load_dotenv()` is **duplicated** in the four self-contained scripts
that can run standalone — `src/relay/racecast-feeds.py`, `src/setup-assets.py`,
`src/relay/get-media.py`, and `src/relay/get-graphics.py` — reading a `.env` only from
the script dir or the project root (marker: `.git`/`.env.example`), never an unrelated
parent; real environment variables take precedence. These deliberately do NOT import
`config.py` (the relay stays dependency-light), but the canonical loader for everything
else is `src/scripts/config.py`. Keep the four `load_dotenv` copies in sync if you
touch one.

### Profile-scoped runtime
Per-league machine state lives under **`runtime/<profile>/`**: the localized OBS
import (`GT_Endurance.import.json`), downloaded `graphics/` and `media/`, etc. Shared
machine state (cookies jar, the active-profile pointer) stays at `runtime/` top level.
So `racecast graphics` / `media` / `setup` always write into the active profile's
runtime dir; switching profiles points the CLI at a different one.

### Two token round-trips (keep paths/secrets out of git)
- **OBS.** `src/obs/GT_Endurance.json` stores tokens: `__RACECAST_GRAPHICS__` (broadcast
  still-graphics dir) and `__RACECAST_MEDIA__` (Intro/Outro clip dir). The HUD and the
  race timer are relay-served on the fixed loopback (`127.0.0.1:8088`, no token) — the
  Sheet URL is no longer embedded in the collection (the relay reads `SHEET_ID` from the
  active profile). Timer state = Sheet tab `Timer` + `runtime/timer.json`,
  Director-controlled via `/timer/*` endpoints. **OBS browser sources cache JS
  aggressively:** after `hud.html`/`timer.html` (or a per-profile overlay CSS) change,
  OBS keeps the old page until refreshed. `racecast relay start` and
  `racecast event start` do that automatically — a hash gate over the *served* page
  bytes (`runtime/obs-pages.hash`, covering `OBS_PAGE_PATHS` = `/hud`, `/timer`,
  `/hud/override.css`, `/timer/override.css`) triggers obs-websocket `refreshnocache`
  on every browser source pointing at the relay; `racecast obs refresh` forces it. The
  manual right-click → Refresh remains the fallback when obs-websocket is unreachable.
  Anything that must survive a reload therefore lives server-side (`runtime/timer.json`,
  the Sheet), never in page JS. When you edit scenes inside OBS, re-export and fold it
  back with `tools/tokenize-obs.py exported.json src/obs/GT_Endurance.json`
  (regex-tokenizes the graphics image-source basenames + any Google-Sheet URLs).
  `src/setup-assets.py`
  does the reverse, injecting real values (the active profile's runtime dirs) into an
  importable collection at `runtime/<profile>/GT_Endurance.import.json`, naming it the
  league's `OBS_COLLECTION` (default `GT Endurance Racing — <league>`). OBS stores
  **absolute** paths, so the localized collection must not be moved after import.
  `src/relay/get-media.py` downloads the Intro/Outro clips (sheet-driven via the Assets
  tab `Intro Video`/`Outro Video` labels, or `RACECAST_INTRO_URL`/`RACECAST_OUTRO_URL`
  env overrides) into `runtime/<profile>/media/`; the `Intro`/`Outro` OBS scenes play
  them looping with audio.
- **Broadcast graphics are pure-runtime** (same model as the Intro/Outro clips): the
  still-graphics (Overlay, Standings, Schedule, Race/Quali Results, the three weather
  overlays, Standby, …) are **never committed**. `python3 src/relay/get-graphics.py`
  downloads each one from the Sheet **Assets** tab into
  `runtime/<profile>/graphics/<Label>.png` (the Sheet label *is* the filename — no
  mapping table; YouTube Intro/Outro rows are skipped). They are tokenised
  `__RACECAST_GRAPHICS__/<Label>.png` in the collection and resolved by
  `setup-assets.py` (which warns, never fails, on a missing file → OBS shows black until
  you run `get-graphics.py`). `src/assets/` therefore holds **only** the HUD `flags/` +
  `brands/` logos (still committed, relay-served).
- **Companion.** Export the config into the gitignored `incoming/` folder, then
  `tools/strip_companion_pass.py` blanks the WebSocket password and writes
  `src/companion/racecast-buttons.companionconfig`. `build.py` re-strips defensively.
- **Per-league overlay (optional).** `profiles/<name>/overlay/{hud,timer}.css` +
  `overlay/fonts/` restyle the relay-served HUD/timer per league via cascade-wins
  override CSS — the base `hud.html`/`timer.html` carry a `<link>` to the override last
  in `<head>`, so a league can recolor/reposition the overlay without forking the page.
  The relay serves `/hud/override.css`, `/timer/override.css`, and
  `/overlay/fonts/<file>` (each read per request from the `--overlay-dir`; empty body
  when the file is absent). The CLI passes `--overlay-dir profiles/<active>/overlay`
  whenever that dir exists (`_overlay_relay_args` in `src/racecast.py`). The two
  override.css are part of `OBS_PAGE_PATHS`, so editing them advances the refresh hash
  and OBS reloads automatically. Editable in the Control Center — a **visual overlay
  builder** (issue #114): the slots' `data-edit` markers in `hud.html`/`timer.html`
  are the single slot source, a pure compiler (`src/scripts/overlay_build.py`,
  `compile_overlay_css`) turns a `layout-<page>.json` the builder owns into the
  generated `<page>.css`, and a hand-written `<page>.css` is migrated verbatim into the
  layout's `customCss` (the pro escape hatch, appended last) on first use — so the
  relay serves the generated file unchanged. Spec:
  `docs/superpowers/specs/2026-06-13-visual-overlay-builder-design.md`. The **first**
  override on a profile whose `overlay/` did not exist when the relay started needs one
  `racecast relay restart` (the `--overlay-dir` flag is decided at launch), but later
  edits apply live. Tests: `tests/test_overlay.py` (compiler + slot extraction +
  migration), `tests/test_ui_server.py` + `tests/test_racecast.py` (routes + data layer).

### The relay (`src/relay/racecast-feeds.py`) — the heart
A 2-feed "ping-pong": **Feed A** (port 53001) serves odd stints, **Feed B** (53002)
even stints; at each handover the off-air feed advances to the next stint's
commentator stream, so OBS media sources never change URL. A 3rd **POV** feed
(53003) is an optional driver picture-in-picture, paused at start. The schedule is a
Google-Sheet tab read as CSV (no API key); a running feed is never torn off
mid-stint — sheet edits apply on the next `/next` (handover) or `/reload`.
**Qualifying mode** (issue #124): a second `ScheduleSource` reads a separate
`Qualifying` tab (same URL/Streamer/Stint structure); `Relay.mode` ∈
{race, qualifying} and `self.source` is a property returning the active one, so
every path (status/next/reload/set_stint/handover) is mode-aware. Qualifying is a
single stream → it lands on Feed A (B idles). Switch at launch (`--qualifying` /
`racecast event start --qualifying`) or live via `/mode/race`|`/mode/qualifying`
(`set_mode`, re-points feeds like a takeover); the panel has a Qualifying section
(mode toggle + a one-row editor writing the Qualifying tab via the `schedule`
webhook action with `tab:"Qualifying"`). On switch the HUD Streamer/Stint follow
the qualifying row (the issue #112 path).

Pull pipeline per feed: **YouTube** — `yt-dlp -g` resolves the live HLS URL (passing
YouTube's bot-check via `yt-cookies.txt` + deno JS challenge) → `streamlink
--player-external-http` serves that URL to one OBS client. **Twitch** — routed directly
through Streamlink's Twitch plugin (no yt-dlp hop); gated feeds optionally use
`twitch-cookies.txt`. (`curl`-ing a feed port returns nothing — it serves a single
consumer; that is not a failure.)

Control is an **unauthenticated** `ThreadingHTTPServer` on port `8088` exposing GET
endpoints (`/next`, `/reload`, `/set/A/<n>`, `/pov/reload`, `/timer/*`, `/status`,
`/panel`, plus the served pages `/hud`, `/timer` and the per-league overlay assets
`/hud/override.css`, `/timer/override.css`, `/overlay/fonts/<file>`, …)
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

**Logging.** The relay and each static-stream feed write timestamped, leveled lines
(`YYYY-MM-DD HH:MM:SS LEVEL …`) to per-service log files under `runtime/<profile>/logs/`
via `src/scripts/logsetup.py` (`TimedRotatingFileHandler`, daily midnight rotation,
archive suffix `.YYYY-MM-DD`). Old archives are pruned on each service start: the
retention window defaults to 7 days and is overridable with
`RACECAST_LOG_RETENTION_DAYS`. Each relay feed has its own `feed_A/B/POV.log`; the
streamlink child's output is pumped through the feed logger with a `[streamlink]` tag
and classified levels (ERROR for 4xx/fatal, WARNING for retries). The `relay` and
`streams` CLI log sources are **merged-file views** (console + all feed logs in one
stream); `aggregate` is the default Control Center source and merges all live sources
(relay, streams, OBS, Companion, Tailscale). OBS Studio and Companion logs are
read-only from their native app directories; the Tailscale source appends a
timestamped `tailscale status` snapshot on each service start and on
`racecast tailscale status`. Archive history is accessible with
`relay|streams logs --list` / `--archive <date>` (racecast sources) or by filename
token (OBS/Companion).

The same server also hosts the **lower-third HUD** as one relay-served page,
replacing ~13 cropped Google-Sheets-editor browser sources (the old producer-lag
culprit): `/hud` serves `src/obs/hud.html`, `/hud/data` returns the overlay JSON
(`HudSource` reads the **Overlay** tab for live values + the **Configuration** tab's
brand-text column — header `Brand Name`/`Brand Key`/`Brand`, see `BRAND_TEXT_HEADERS` —
for team→manufacturer), and `/hud/assets/{flags,brands}/<name>`
serves bundled logos from `src/assets/`. The page polls `/hud/data` (no manual
reloads); flags/brands resolve from text via `asset_key()`. Flags: `--no-hud`,
`--overlay-tab`, `--config-tab`, `--hud-poll`, `--overlay-dir` (per-league override
CSS/fonts, passed by the CLI when `profiles/<active>/overlay` exists). Tests:
`tests/test_hud.py`.

The panel's **sheet controls** write back through one Apps Script webhook
(`RACECAST_SHEET_PUSH_URL`, injected by the CLI from the active profile's
`SHEET_PUSH_URL`, shared with the race timer — wiki: Sheet-Webhook):
Setup fields (Stint label/Streamer/Session/Race Control) are async-optimistic
(`HudSource` override now, sheet poll confirms, 30 s expiry), Schedule/POV URL
writes are synchronous; URL changes never auto-reload a feed. Setup "Stint" =
HUD display label, NOT the feed stint index. `SetupControl` + endpoints
`/setup/*`, `/schedule/*`, `/pov/set` (POST). Tests: `tests/test_setup.py`.

The relay also hosts a **crew chat** (`GET /chat/data`, `POST /chat/send`,
`GET /chat/reload`) — an in-memory ring buffer (200 messages) persisted to
`runtime/<profile>/chat.json`. The panel polls `/chat/data`; messages render via
`textContent` (XSS-safe); the unread badge is keyed on server `ts` (handover-safe).
There is **no destructive HTTP endpoint** — clear/import/pull are producer-only CLI
actions (`racecast chat clear|pull|import|export`, logic in
`src/scripts/chat_admin.py`) that write the file and trigger `/chat/reload`. The
tailnet is the trust boundary (unauthenticated, like the rest of the relay).
Tests: `tests/test_chat.py`.

The relay also serves a **talent-facing Commentator Cockpit** (issue #191) under an
auth-gated `/cockpit/*` namespace: a live program monitor (reusing
`get_program_screenshot`), an "ON AIR / UP NEXT" tally (`cockpit_tally`, derived from the
on-air feed + the live schedule via `asset_key`-normalised streamer names), the embedded
crew chat (identity forced to the token's streamer), and a read-only timer. It is exposed
**publicly via Tailscale Funnel**, which maps **only** the `/console` path prefix to
`127.0.0.1:8088` — the rest of the relay stays tailnet/loopback-only and is **never**
funnelled (the security boundary). `/console/buttons` reverse-proxies (HTTP + a raw-WebSocket
passthrough for Companion's tRPC `/trpc`) to the resolved local Companion bind address,
director-gated (#236); it is a sub-path of the single `/console` mount (no second mount);
OBS-WebSocket remains never funnelled. Funnel passes no Tailscale identity, so auth is 100%
server-side: a per-person token `<streamer_key>.<version>.<sig>` signed with the
**per-league** `CONSOLE_SECRET` (`profiles/<name>/profile.env`, travels with `profile
export`); revocation bumps a streamer's version in
`runtime/<profile>/console-versions.json`.
The cockpit is **zero-config**: the secret is **auto-provisioned** by the CLI on first relay
start (`_ensure_active_cockpit_secret` in `src/racecast.py`, idempotent, never the shipped
`example` profile), so `/cockpit/*` is live **whenever a secret exists** — there is no
separate enable flag. When the secret is absent every `/cockpit/*` path 404s (like chat/timer
when disabled). PUBLIC exposure is the **independent Funnel switch** (`racecast funnel on`),
which mounts **only** `/console` — the only way `/console` leaves the tailnet. The token
rides in the `…/console?t=` link once, then an `HttpOnly; Secure; SameSite=Lax`
`rc_console` cookie. **Discord OAuth second front door:** when `DISCORD_CLIENT_ID` +
`DISCORD_CLIENT_SECRET` are set in `profile.env`, the relay also serves
`/console/login` + `/console/oauth/callback` (scope `identify`); a session-bound
`rc_oauth_state` cookie guards CSRF; on a Crew-tab Discord-handle match the relay mints
the same `rc_console` token. The Crew tab gained `Commentator` and `Discord` columns;
`resolve_roles` is an A1 union (Schedule OR Crew Commentator flag). Auth core:
`src/scripts/console_auth.py`; revocation store: `src/scripts/console_admin.py`;
talent page: `src/cockpit/cockpit.html`; CLI: `racecast cockpit …`; takeover pulls A's
versions over the tailnet (like `chat pull`). Tests: `tests/test_cockpit.py`. The crew
roster (Crew tab ∪ live Schedule) is exposed via a tailnet-only `GET /crew/data` endpoint
(root path, **never** funnelled — only `/console` is mounted); `racecast links` unions Crew
∪ Schedule to produce role-adaptive `/console` links for every person. The Control Center
cockpit view is now called **"Crew Console"**.

**Producer takeover over Funnel (`/console/takeover/*`, issue #216 Phase 7).** When
producer B is not on the tailnet, `racecast event takeover <A-magicdns-host> --funnel`
pulls the handover state over A's public Funnel. Three read-only endpoints live under
`/console/takeover/` (all reachable via Funnel, **never** adding to the public surface
beyond the existing `/console` mount):
- `GET /console/takeover/status` — **redacted** status: only `live`, `league`,
  `event_title`, `timer`, and `mode`. Feed stream URLs are stripped — they never leave
  the tailnet. This is an allowlist, not a blocklist.
- `GET /console/takeover/chat` — the full chat history (same payload as `/chat/data`).
- `GET /console/takeover/versions` — the console-versions revocation map (same payload
  as `/cockpit/versions`).

All three require the **step-up** `X-Console-Secret` header (legacy name `X-Cockpit-Secret`
still accepted for one release) carrying the shared per-league `CONSOLE_SECRET` (producer-level
auth — the same secret that signs commentator tokens). A
wrong secret returns HTTP 403; the client aborts loudly. A network failure falls back to the
local `--stint N` bringup. On success, B's relay is brought up via the normal `event start`
path with the adopted stint/league/title/mode, and chat + versions are applied locally
(`ca.apply_pulled` / `cpadm.apply_pulled`, same as the tailnet pull path). The tailnet path
(`racecast event takeover <100.x-ip>`) is unchanged and does not use the step-up header.
The security boundary is preserved: only `/console` is Funnel-mounted (with `/console/buttons`
as a director-gated relay-proxy sub-path — no second mount); no takeover endpoint is reachable
without the step-up secret; feed URLs stay tailnet-only; OBS-WebSocket is never funnelled. CLI helper:
`_funnel_takeover_base(host)` + `_takeover_get(url, secret, timeout)`; plan:
`docs/superpowers/plans/2026-06-19-console-roles-phase7-takeover-funnel.md`.

**Commentator stream-link submission (issue #193).** A write-scoped add-on: a commentator
submits a YouTube/Twitch URL for one of *their own* stints from the cockpit
(`POST /cockpit/submit`, the only write reachable over Funnel) — token-auth + per-identity
rate limit + `is_channel()` SSRF guard + server-side **own-rows-only** check
(`own_submission_target`, `asset_key(streamer) == token's streamer_key`). It is stored
**pending** (never auto-published) in `runtime/<profile>/cockpit-pending.json` and pings
Discord (`cockpit_submission_payload`, no-op without a webhook). The director's
**list/approve/reject** live under a separate `/submissions/*` namespace that is **NOT**
funnelled (tailnet-only, reached from `/panel`); approve calls the existing
`SetupControl.schedule_set` (writes the Sheet; applies on the next `/reload`). Pure store +
audit log: `src/scripts/cockpit_submissions.py` (mirrors `cockpit_admin.py`); thin
thread-safe wrapper `SubmissionStore` + endpoints in the relay; panel section + cockpit
form in the two HTML files. Tests: `tests/test_submissions.py`.

**Role-adaptive /console pages (issue #216).** The relay also serves a `/console` launcher plus `/console/cockpit` and `/console/panel` pages, all role-gated behind the Phase 3a `/console` auth gate; page API calls resolve under the mount via an injected `window.RC_API_BASE` shim. Launcher, cockpit, and panel are in `src/console/console.html`, served with the authenticated subject's role-conditional links; `/console/whoami` returns the authenticated subject. Authorization is per-role (any authenticated subject reaches `/console` + `/console/cockpit`; directors reach `/console/panel`). Tests: `tests/test_console.py` + `tests/test_console_gate.py`.

**Relay-mediated OBS control (Director Panel).** The Director Panel's scene switches, visibility toggles, and audio controls go through the relay — not a direct browser→OBS-WebSocket connection. Four director-gated endpoints (all checked via `console_policy` before dispatch): `POST /obs/scene` (switch scene), `POST /obs/source` (show/hide a source), `POST /obs/audio` (set input volume/mute), `POST /obs/state` (batch read of current scene + source visibility + audio levels). The relay calls `src/scripts/obs_ws.py` on the producer's machine, where the OBS-WebSocket password is auto-discovered from OBS's own config (overridable via `RACECAST_OBS_WS_PASSWORD` in `.env`); the password never crosses the network and OBS-WebSocket is **never** funnelled. The Director Panel therefore needs **no OBS IP, port, or password** from the director — the panel works fully over Funnel (`/console/panel`) using only the per-person token. The program monitor was already relay-mediated (`GET /preview/program`, any-auth, console-allowed) and is unchanged. All four OBS helpers follow the same best-effort contract as `get_program_screenshot` — they never raise; `obs_ws._connect()` returning `None` maps to a `503` from the endpoint with a descriptive note. Tests: `tests/test_obsws.py`.

### Unified `racecast` CLI (`src/racecast.py`)
`src/racecast.py` is the single shipped entrypoint for operators. It resolves the
active profile (via `src/scripts/config.py`) and injects its league values into the
environment before dispatching to:
- **`src/scripts/services.py`** — daemon helper for the relay and static-streams: spawns
  subprocesses, writes PID + log files under `runtime/`, and provides start/stop/restart/
  status/logs for both. `racecast relay run` is the foreground/debug mode (no daemon).
- **Companion adapter** (over `src/scripts/companion_common.py`) — `racecast companion
  start/stop/restart/status/logs` wraps the Companion bind logic (Windows + macOS
  automated; native Linux companion-pi systemd service controlled; other Linux setups
  — WSL/Docker/manual AppImage — are manual).
- **One-shot wrappers** — `racecast preflight`, `racecast cookies`, `racecast graphics`,
  `racecast media`, `racecast setup` delegate to the corresponding `src/` modules
  without needing to remember individual script paths.
- **`racecast profile list|show|use|new [--from]`** + global `--profile NAME` — manage
  league profiles (logic in `src/scripts/profile_admin.py` + `config.py`); `use` writes
  the `runtime/active-profile` pointer.
- **`racecast status`** — aggregate health of relay + companion + streams at a glance.
- **`src/scripts/obs_ws.py`** — minimal obs-websocket v5 client (stdlib only). After
  `relay stop`/`streams stop` kill the feeds, `_release_obs_feeds()` re-applies the
  feed media inputs' own settings via `SetInputSettings` — the one request that makes
  OBS rebuild the ffmpeg source and close its socket (media STOP/RESTART actions are
  ignored for inactive sources). Without it OBS pins the feed ports in FIN_WAIT_1
  until it restarts and preflight warns "port in use". Must run AFTER the kill (a
  rebuild against a live relay would just reconnect). Password auto-discovered from
  OBS's obs-websocket config.json (`RACECAST_OBS_WS_PASSWORD` in `.env` overrides). Fully
  best-effort: any failure prints one notice and the stop continues.
  It also exposes a scene-collection check/switch (`GetSceneCollectionList` / `SetCurrentSceneCollection`): `racecast obs collection [set]`, a warning during `racecast event start`, a line in `racecast event status`, and the Control Center's OBS row. Switching is always an explicit producer action — it rebuilds every source — never automatic. The canonical product name is `EXPECTED_SCENE_COLLECTION` (`GT Endurance Racing`), which mirrors the `name` field of `src/obs/GT_Endurance.json`; a localized per-league collection defaults to `GT Endurance Racing — <league>` (`PRODUCT_COLLECTION_PREFIX` + the profile name, unless the profile sets `OBS_COLLECTION`), so several leagues keep separate collections in one OBS. `racecast obs collection set` switches to the active profile's expected name.

### Control Center (`src/racecast_ui.py` + `src/ui/`)
`racecast ui` serves a local web app (`src/ui/ui_server.py`, port 8089 /
`RACECAST_UI_PORT`) for dashboard, service control and logs. Two settings surfaces:
- **Profile view** — switch the active profile, create a new one (new-profile dialog,
  optionally `--from` an existing one), edit the active league's `profile.env`, style the
  per-league overlays in the **visual overlay builder** (drag/resize the HUD/Timer slots
  on a same-origin Shadow-DOM canvas over `Overlay.png`, with a fonts uploader and an
  advanced-CSS escape hatch), download profile-scoped graphics/media, and manage the
  **crew roster** in the **crew editor** (reads the league Sheet's `Crew` tab via the
  relay's `/crew/data`; writes per-row director/producer flags back via the `crew`
  webhook action — routes `/api/crew`, `/api/crew/delete`). The Crew tab
  (`Name | Commentator | Director | Producer | Discord` header in row 1) and the `crew`
  Apps Script action are a league Sheet-side coordination item (see `Sheet-Webhook` wiki
  page); without them roles degrade gracefully and the editor surfaces an
  outdated-script banner. Routes:
  `/api/profiles`, `/api/profile/{use,new,env}`, `/api/overlay`,
  `/api/overlay/{slots,layout,fonts,bg,font/<name>}`, `/api/crew`, `/api/crew/delete`.
- **General Settings** — machine-wide knobs: the `.env` editor (`RACECAST_*` vars),
  cookie refresh, and the **overlay font library** (`runtime/fonts/`, shared across
  leagues). A curated baseline set (`overlay_build.GOOGLE_FONTS`) is downloaded at build
  time into `fonts.zip`, bundled INTO each binary, and extracted into `runtime/fonts/` on
  first start by `ensure_bundled_fonts()` (stamp-gated, only-if-absent, zip-slip-safe — so
  every install has fonts without a manual download, and `racecast update` refreshes the
  set). Operators add further families by name via the Settings typeahead (routes
  `/api/fonts`, `/api/fonts/{catalog,download,delete}`); `tools/fetch-fonts.py` is the
  maintainer tool that builds the zip. A font a league's design uses is copied into that
  profile's `overlay/fonts/` on save (`_materialize_overlay_fonts`), so `profile export`
  stays self-contained; the relay/canvas serve it locally (no broadcast-time CDN).

`tools/` is maintainer-only (build, tokenize, sync) and is not shipped to producers.

### Standalone binary (PyInstaller)
`tools/build-binary.py` freezes `src/racecast.py` into the `racecast` executable and
`src/racecast_ui.py` into the windowed `racecast-ui` (Control Center launcher) — one
pair per OS; the whole `src/` tree ships as bundled data under `sys._MEIPASS/src/`, so
here-relative path resolution keeps working. In frozen mode (`sys.frozen`), `racecast`
runs bundled scripts **in-process** (importlib + patched argv, string `sys.exit`
payloads go to stderr) and daemons re-invoke the binary itself (`racecast relay run`,
hidden `racecast streams run-feed`) with `PYINSTALLER_RESET_ENVIRONMENT=1` so each
child extracts its own bundle and outlives the parent. `runtime/`, `profiles/` and
`.env` live next to the binary — keep it in its own folder.
`services.py`/`companion_common.py` carry the per-OS process control (Windows: ctypes
PID probe — `os.kill(pid, 0)` would TERMINATE the target there — taskkill/tasklist,
Companion.exe discovery + `RACECAST_COMPANION_EXE` override in `.env`; native Linux:
companion-pi systemd service via `companion_linux.py`; other Linux setups — WSL/Docker/
manual AppImage — remain manual, matching the pre-existing guidance).
Releases: merge the standing **release-please** Release PR (or push a `v*` tag manually
— both work) — `.github/workflows/release.yml` tests, builds, smoke-tests and uploads
`racecast-windows.zip` / `racecast-macos.tar.gz` / `racecast-linux.tar.gz` /
`racecast-linux-arm64.tar.gz` (each contains the `racecast` binary + `.env.example`;
on first run the frozen binary copies it to `.env` — see `ensure_env_file`). The two
Linux archives are built natively on the `ubuntu-latest` (x86-64) and
`ubuntu-24.04-arm` (ARM64) matrix runners; `update.asset_name()` picks the right one
per `platform.machine()` so a self-updating ARM64 binary never fetches the x86-64
archive. release-please tags via GITHUB_TOKEN, which cannot
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

### End-to-end / regression harness (`tools/e2e.py` + `tools/e2e_checks.py`)
The integration **outer loop** (issue #199): it stands up the relay + Control Center
from `src/` as owned subprocesses and asserts the **live HTTP surface** — the class of
bug the unit suite (pure functions) can't catch. Maintainer-only (`tools/`, not shipped).
`tools/e2e_checks.py` is the pure, import-testable assertion core (free-port,
synthetic-CSV builder, tolerant `http_request`, the `CheckResult`/`run_checks` registry,
the `check_*` callables, `SYNTHETIC_CHECKS`/`REAL_LEAGUE_CHECKS`), unit-tested in
`tests/test_e2e.py`; `tools/e2e.py` owns process lifecycle (spawn, readiness-poll,
guaranteed `finally` teardown — no leaked relays/UI even on failure). Two modes:
- **Synthetic** (`tools/e2e.py`, the default, **CI-runnable**): an ephemeral temp profile +
  an in-process CSV schedule server via `--sheet-csv-url`; spawns an enabled relay + a
  cockpit-disabled relay + the Control Center on free `127.0.0.1` ports; runs 10 checks.
  No real Sheet/cookies/OBS/Tailscale. Because the relay **hard-exits at startup without
  `yt-dlp`/`streamlink` on PATH** (`racecast-feeds.py`), synthetic mode writes **no-op
  stubs** for `yt-dlp`/`streamlink`/`ffmpeg`/`deno` into the temp dir and prepends them
  to the relay's PATH (the fake schedule URLs are never pulled). The dedicated **`e2e`
  CI job** (`.github/workflows/ci.yml`, ubuntu) runs exactly this; the matrix `test` job
  already runs `tests/test_e2e.py` via `run-tests.py`.
- **Real-league** (`--real-league NAME`, **local only — refuses under CI**): drives the
  copied real-league dev build (real Sheet/cookies/`CONSOLE_SECRET`), minting a token for
  a real streamer pulled live from `/schedule/data`. Runs a **non-mutating** subset
  (`REAL_LEAGUE_CHECKS`): it **excludes** `check_submission_pending` (a `POST
  /cockpit/submit` could ping the league's real Discord webhook) and
  `check_cockpit_404_when_disabled` (needs a second relay); `check_chat_round_trip` is
  included (the crew chat is relay-local).

The checks regression-guard the four #191 cockpit bugs (env-clobber via the real
`racecast._set_env_key`, timer `—`, double-"stint" tally, flat `/cockpit/data` shape)
and the #193 own-row submission. Optional **rendered checks** (`--playwright`) use the
Playwright **Python library** (not the MCP) and SKIP when unavailable (CI omits the
flag). Visual helpers, all local-only: `--headed`/`--slowmo` (visible browser),
`--keep` (leave the services up + print the live URLs incl. the cockpit token), and
`--shots DIR` (write a screenshot of each surface — a reproducible, MCP-free tour;
the Control Center shot shows the machine's Tailscale IP, so it is a **local artifact,
never committed**). The local real-league run (copy the deployed instance's
profile/runtime/cookies in, enable cockpit on the copy, set up a Playwright venv, run,
tear down) is captured in the **`racecast-e2e`** skill, which builds on the
**`racecast-local-uat`** skill's data copy-in. Spec/plan:
`docs/superpowers/{specs,plans}/2026-06-17-e2e-regression-harness*.md`.

### Static mode (`src/scripts/`) — the simpler alternative
`loopstream.py` keeps one streamlink server alive for one public channel (YouTube or
Twitch); `start-streams.py` / `stop-streams.py` manage a set of them with PID/log files
under `runtime/static/`. This is the fallback for **public** channels only — no yt-dlp
bot-check, no unlisted streams; the real unlisted-stream flow is the relay. YouTube is
served via Streamlink's direct HLS path; Twitch is served via Streamlink's Twitch plugin
(low-latency, same flags as the relay — `STREAMLINK_TWITCH` is **duplicated from
`racecast-feeds.py` and pinned byte-identical by a `getsource` cross-check in
`tests/test_streams.py`** to prevent drift). Gated Twitch feeds use the same machine-level
`twitch-cookies.txt` as the relay. Each feed entry may be a YouTube channel ID (UC…) or
a full `youtube.com`/`twitch.tv` URL; invalid channels are rejected at load time by
`is_channel()` (SSRF guard). Invoke via `racecast streams start/stop` —
`start-streams.py`/`stop-streams.py` are logic modules, not the operator entrypoint.
`stop-streams.py` validates a PID actually belongs to a feed process before killing.

### Companion remote-access helpers (`src/scripts/`)
`companion_common.py` (tests `tests/test_companion.py`) contains the pure logic that binds
**Bitfocus Companion**'s admin/web-buttons server to this machine's Tailscale IP so a tablet
can open `http://<tailscale-ip>:<port>/tablet` over the tailnet — same plug-&-play model as
the relay's `--bind auto`, and likewise **not** the LAN. It auto-detects the Tailscale IP
(Tailscale detection/control lives in `src/scripts/tailscale.py`; its `detect_tailscale_ip` is duplicated in the standalone relay — keep those two in sync), and — only while Companion
is stopped, with a `.racecast-bak` backup — sets `bind_ip` in Companion's `config.json`
(`~/Library/Application Support/companion/config.json` on macOS; the GUI launcher reads
it as `--admin-address`). Windows + macOS automated (Windows: Companion.exe discovery +
`RACECAST_COMPANION_EXE` override in `.env`); native Linux: companion-pi **systemd
service**, controlled by `companion_linux.py` — `racecast companion start/stop` invoke
`systemctl` via a root bind helper that pins `--admin-address` to the Tailscale IP, or
`127.0.0.1` when the tailnet is down (never `0.0.0.0`, matching the relay's `--bind
auto` rule). This requires a one-time `racecast companion enable-control` (installs a
systemd `ExecStart` drop-in, the `/usr/local/sbin/racecast-companion-bind` root helper,
and a visudo-validated NOPASSWD sudoers rule); `install-apps` runs it automatically
after a Linux Companion install. Re-run `enable-control` after a structural
`sudo companion-update` that changes the node launch line. Other Linux setups
(WSL/Docker on the host, manual AppImage) keep the manual path. Tests:
`tests/test_companion_linux.py`. Invoke via `racecast companion start/stop`. **Important:**
binding only controls *where* Companion listens — Companion serves `/tablet` and the admin
GUI on one port + one shared socket API (its admin password is a casual deterrent, not a
boundary), so isolating the admin from directors is a **Tailscale-ACL** job (restrict who
reaches the port), not something these scripts can do. Editing `config.json` is
unsupported-but-stable; re-check after Companion upgrades.

## Docs

- `README.md` — operator quickstart (the commands above).
- `src/docs/` — shipped operator material (`README_SETUP.md`,
  `Broadcast_Setup_Guide.md`, printable `cheat_sheets.html`).
- `src/docs/wiki/` — canonical source for the **GitHub wiki** (split-up onboarding
  pages + Mermaid architecture diagrams). The wiki is generated, never hand-edited on
  GitHub: edit these pages, then `python3 tools/sync-wiki.py` mirrors them to the
  `<origin>.wiki.git` repo (clones into `runtime/wiki/`, commits, pushes). First push
  per repo needs a one-time bootstrap — create+save any page via the GitHub Wiki UI so
  GitHub creates the wiki repo. See `src/docs/wiki/Maintaining-this-Wiki.md`.
- `docs/superpowers/{specs,plans}/` — design specs and implementation plans for
  features (POV PiP, repo structure, preflight). Read the matching spec before
  extending one of those features.
