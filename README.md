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

## Run it

```bash
python3 src/iro.py preflight            # check tools/hardware
python3 src/iro.py relay start          # start the relay (background)
python3 src/iro.py relay logs -f        # watch it live
python3 src/iro.py relay status         # health + tailnet URL
python3 src/iro.py companion start      # bind Companion to Tailscale, start it
python3 src/iro.py status               # all services at a glance
python3 src/iro.py relay stop           # stop the relay
```

(In the distributed package the same commands are `python3 iro.py …`.)
For live debugging you can still run the relay in the foreground: `python3 src/iro.py relay run`.

### One-time / pre-event setup
```bash
python3 src/iro.py setup --out runtime/IRO_Endurance.import.json   # localize OBS assets + inject Sheet ID
# OBS -> Scene Collection -> Import -> runtime/IRO_Endurance.import.json
python3 src/iro.py cookies chrome       # refresh YouTube cookies before each event
python3 src/iro.py media                # download Intro/Outro clips -> runtime/media/
python3 src/iro.py graphics             # download broadcast graphics -> runtime/graphics/
```

## Build the distributable
```bash
python3 tools/build.py     # -> dist/IRO_Broadcast_Package/ + dist/IRO_Broadcast_Package.zip
```

## Standalone binary (no Python needed)

Download your platform's binary from the GitHub **Releases** page
(`iro-windows.exe`, `iro-macos`, `iro-linux`), put it in **its own folder**
(it creates `runtime/` and reads `.env` next to itself), then:

    iro install-tools     # one-time: installs yt-dlp/streamlink/ffmpeg/deno (offers Homebrew setup on a fresh Mac)
    iro install-apps      # optional: installs OBS, Companion, Tailscale (Linux: confirms before running vendor installers)
    iro preflight         # verify the machine is ready
    iro export companion  # write the Companion button config for import

First start: Windows SmartScreen / macOS Gatekeeper show a one-time warning for
unsigned binaries — choose "Run anyway" / right-click → Open.

## After editing the OBS collection in OBS
Re-export from OBS, then fold the change back into the tokenized source:
```bash
python3 tools/tokenize-obs.py /path/to/exported.json src/obs/IRO_Endurance.json
```
