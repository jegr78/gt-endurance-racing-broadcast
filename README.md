# IRO Endurance Broadcast — Repository

Single-source repo for the IRO Endurance broadcast producer station.
**Edit only under `src/`.** `dist/` and `runtime/` are generated and gitignored.

📖 **Operator docs & onboarding:** see the [project wiki](https://github.com/jegr78/IRO_Broadcast_Setup/wiki)
(architecture diagrams, setup, runbook, troubleshooting). Its source lives in
`src/docs/wiki/` and is published with `python3 tools/sync-wiki.py`.

## Layout
- `src/` — source of truth: `relay/`, `obs/`, `companion/`, `director/`, `assets/`, `scripts/`, `docs/`, `setup-assets.py`
- `.env` — machine-local secrets/config (gitignored; copy from `.env.example`)
- `tools/` — maintainer scripts (build, tokenize, sync, helpers) — not shipped
- `tests/` — `test_pov.py`
- `runtime/` — cookies/logs/caches (gitignored)
- `dist/` — built distributable + ZIP (gitignored)
- `docs/superpowers/` — specs & plans

## Configure the Google Sheet (once)
The HUD + relay schedule live in a Google Sheet. Its ID is **not** hardcoded —
it comes from `IRO_SHEET_ID` (env var or a gitignored `.env` at the repo root):
```bash
cp .env.example .env      # then put your Sheet ID into IRO_SHEET_ID
```
Used by the relay (schedule/POV tabs) and by `setup-assets.py` (HUD browser source).

## Get started — the Control Center

Download the latest release for your platform from
[**GitHub Releases**](https://github.com/jegr78/IRO_Broadcast_Setup/releases/latest)
(`iro-windows.zip` / `iro-macos.tar.gz` / `iro-linux.tar.gz`) and extract it into
**its own folder**. The archive holds two binaries side by side: **`iro`** (the
CLI) and **`iro-ui`** (the Control Center).

**Double-click `iro-ui`** (`iro-ui.exe` / `iro-ui.app`; Linux: `./iro-ui`) to open
the **Control Center** at `http://127.0.0.1:8089/` — a local web dashboard that
runs the whole station (setup wizard, service control, logs) from your browser.
The first launch creates a `.env` next to the binaries for your Sheet ID and
secrets. Full step-by-step:
[Set up the broadcast PC (wiki)](https://github.com/jegr78/IRO_Broadcast_Setup/wiki/Set-up-the-broadcast-PC)
· [The Control Center (wiki)](https://github.com/jegr78/IRO_Broadcast_Setup/wiki/Control-Center).

> **First start:** Windows SmartScreen / macOS Gatekeeper show a one-time warning for
> unsigned binaries — choose "Run anyway" / right-click → Open.

## The CLI (alternative)

Everything the Control Center does is also an `iro …` command — the terminal stays
a first-class option (and the only one on headless Linux). Run `iro` once to create
the `.env`, then update later with `iro update`.

### One-time machine setup
```
iro init              # guided setup: installs tools+apps, cookies, graphics,
                      # media, OBS collection, Companion config, preflight —
                      # skips what is already done; re-run any time
```

Or run the steps individually:
```
iro install-tools     # installs yt-dlp/streamlink/ffmpeg/deno (offers Homebrew setup on a fresh Mac)
iro install-apps      # optional: installs OBS, Companion, Tailscale
iro preflight         # verify the machine is ready
iro export companion  # write the Companion button config -> runtime/iro-buttons.companionconfig
```

### One-time / pre-event setup
```
iro cookies firefox      # refresh YouTube cookies before each event (log into YouTube in Firefox first)
iro media                # download Intro/Outro clips -> runtime/media/
iro graphics             # download broadcast graphics -> runtime/graphics/
iro setup --out runtime/IRO_Endurance.import.json   # localize OBS assets + inject Sheet ID
# OBS -> Scene Collection -> Import -> runtime/IRO_Endurance.import.json
```

## Run it

```
iro event start          # bring everything up: Tailscale, Discord, relay, OBS, Companion
iro event start --stint 4 # take over mid-event (12h/24h): stint 4 is on air now
iro event status         # event-day readiness report (apps, services, cookies, graphics, media, config)
iro event stop           # stop relay/Companion/streams — OBS & friends keep running
iro tailscale up         # connect Tailscale (event start does this automatically)
iro tailscale down       # disconnect Tailscale after the event
iro preflight            # check tools/hardware
iro relay start          # start the relay (background)
iro relay logs -f        # watch it live
iro relay status         # health + tailnet URL
iro companion start      # bind Companion to Tailscale, start it
iro status               # all services at a glance
iro relay stop           # stop the relay
iro obs refresh          # force-reload the relay-served OBS browser sources (HUD/timer)
iro obs collection       # check the active OBS scene collection
iro obs collection set   # switch OBS to the IRO Endurance collection
```

For live debugging, run the relay in the foreground: `iro relay run`.

## Build the distributable (maintainer)
```bash
python3 tools/build.py     # -> dist/IRO_Broadcast_Package/ + dist/IRO_Broadcast_Package.zip
```

## After editing the OBS collection in OBS
Re-export from OBS, then fold the change back into the tokenized source:
```bash
python3 tools/tokenize-obs.py /path/to/exported.json src/obs/IRO_Endurance.json
```
