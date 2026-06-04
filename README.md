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

## Run the relay (producer)
```bash
python3 src/setup-assets.py --out runtime/IRO_Endurance.import.json   # once: localize OBS assets + inject Sheet ID
# OBS -> Scene Collection -> Import -> runtime/IRO_Endurance.import.json
python3 src/relay/get-cookies.py chrome --runtime-dir runtime         # before each event
# Download the stream Intro/Outro clips (URLs from the Sheet's Configuration tab)
python3 src/relay/get-media.py            # -> runtime/media/intro.mp4, outro.mp4
python3 tools/run-relay.py                                            # start the relay
```

## Build the distributable
```bash
python3 tools/build.py     # -> dist/IRO_Broadcast_Package/ + dist/IRO_Broadcast_Package.zip
```

## After editing the OBS collection in OBS
Re-export from OBS, then fold the change back into the tokenized source:
```bash
python3 tools/tokenize-obs.py /path/to/exported.json src/obs/IRO_Endurance.json
```

## Refresh graphics from the production source
Set your graphics folder once (Google-Drive / Dropbox / network share), then sync:
```bash
echo /path/to/your/graphics/folder > runtime/assets-source.txt   # one-off (gitignored)
python3 tools/sync-assets.py
# or per-run:  python3 tools/sync-assets.py --source /path/to/folder
```
