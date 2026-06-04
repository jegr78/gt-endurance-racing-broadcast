# Configuration

Two things are machine- and event-specific and are **never** hardcoded or committed:
the **Google Sheet ID** (schedule + HUD data) and the **stagetimer output URL**. Both
come from a gitignored `.env` file. Then `setup-assets.py` localizes the OBS collection
for this machine.

## The `.env` file

At the repository (or package) root there is a tracked template, `.env.example`. Copy
it and fill in your values:

```bash
cp .env.example .env
```

```ini
# .env  (gitignored — never commit this)
IRO_SHEET_ID=your_google_sheet_id_here
IRO_TIMER_URL=https://stagetimer.io/output/XXXXXXXX/?v=2&signature=...
```

- **`IRO_SHEET_ID`** — the long ID from your HUD/schedule sheet URL:
  `https://docs.google.com/spreadsheets/d/`**`<THIS>`**`/edit`. Drives the relay:
  the schedule, the POV tab, and the HUD overlay (Overlay + Configuration tabs, served
  at `/hud`).
- **`IRO_TIMER_URL`** — the full signed stagetimer.io output URL injected into the timer
  browser source.

Real environment variables take precedence over `.env`. The loader only reads a `.env`
from the script directory or the project root (marked by `.git` / `.env.example`),
never an unrelated parent directory.

> **Security:** `.env` is gitignored and must stay that way. The signed stagetimer URL
> is a secret — if it ever leaks, regenerate the output link in stagetimer and update
> `IRO_TIMER_URL`.

## Localize the OBS collection (`setup-assets.py`)

The OBS scene collection in git is deliberately **path- and secret-free**: it stores
tokens (`__IRO_ASSETS__`, `__IRO_TIMER__`) instead of real paths and URLs. (The HUD
overlay is served by the relay, so the collection no longer embeds the sheet — there is
no `__IRO_SHEET__` token in it.) `setup-assets.py` injects the real values from `.env`
and writes an importable collection:

```bash
python3 src/setup-assets.py --out runtime/IRO_Endurance.import.json
# in the distributed package:  python3 setup-assets.py
```

This:
- rewrites the image paths to **this** machine's `assets/` folder (Overlay + graphics +
  thumbnail + the flag/brand HUD logos), and
- injects `IRO_TIMER_URL` into the timer browser source. (The HUD overlay needs no
  injection — it is served by the relay; `IRO_SHEET_ID` is read by the relay, not the
  collection.)

You can override per-run without `.env`: `--sheet-id <ID>` / `--timer-url <URL>`.

> **Import the `.import.json`, not the `.template.json`.** And **do not move the folder
> after importing into OBS** — OBS stores absolute image paths. If you move it, re-run
> `setup-assets.py` and re-import.

## Refresh graphics from the production source (optional)

If your overlay graphics live in a shared folder (Google Drive / Dropbox / network
share), set it once and sync:

```bash
echo /path/to/your/graphics/folder > runtime/assets-source.txt   # one-off (gitignored)
python3 tools/sync-assets.py
# or per-run:  python3 tools/sync-assets.py --source /path/to/folder
```

Next: [OBS Setup](OBS-Setup).
