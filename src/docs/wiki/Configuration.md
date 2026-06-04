# Configuration

> Technical reference. The setup steps are in [Set up the broadcast PC](Set-up-the-broadcast-PC).

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
tokens instead of real paths and URLs. `setup-assets.py` injects the real values from
`.env` and writes an importable collection:

```bash
python3 src/iro.py setup --out runtime/IRO_Endurance.import.json
# in the distributed package:  python3 setup-assets.py
```

The tokens in the collection:

| Token | Resolves to |
|-------|-------------|
| `__IRO_GRAPHICS__` | `runtime/graphics/` (package: `graphics/`) — the Sheet-driven broadcast graphics, `__IRO_GRAPHICS__/<Label>.png` |
| `__IRO_MEDIA__` | `runtime/media/` — the Intro/Outro clips |
| `__IRO_TIMER__` | the signed `IRO_TIMER_URL` (stagetimer output) |

(The HUD overlay is served by the relay, so the collection no longer embeds the sheet —
there is no `__IRO_SHEET__` token in it.)

So `setup-assets.py`:
- rewrites the broadcast-graphic image paths (`__IRO_GRAPHICS__`) to **this** machine's
  `runtime/graphics/` folder. Those PNGs are **not** committed — download them first with
  `python3 src/iro.py graphics` (see [Sheet-driven graphics](#sheet-driven-graphics)
  below); a graphic still missing prints a warning and OBS shows that source black, and
- injects `IRO_TIMER_URL` into the timer browser source. (The HUD overlay needs no
  injection — it is served by the relay; `IRO_SHEET_ID` is read by the relay, not the
  collection.)

> `__IRO_ASSETS__` is retired from the OBS collection. `src/assets/` now holds **only**
> the bundled HUD `flags/` + `brands/` logos — these stay committed and are served by the
> relay HUD, not by the OBS collection.

You can override per-run without `.env`: `--sheet-id <ID>` / `--timer-url <URL>`.

> **Import the `.import.json`, not the `.template.json`.** And **do not move the folder
> after importing into OBS** — OBS stores absolute image paths. If you move it, re-run
> `setup-assets.py` and re-import.

## Sheet-driven graphics

The broadcast still-graphics (Overlay, Standings, Schedule, Race/Quali Results, the three
weather overlays, Standby, …) are **pure-runtime**: they are driven from the Google Sheet
**Assets** tab and **never committed**, the same model as the Intro/Outro clips. Each
Assets row that points at a graphic is downloaded as `runtime/graphics/<Label>.png` — the
Sheet label *is* the filename (no mapping table; the Intro/Outro YouTube rows are skipped):

```bash
python3 src/iro.py graphics            # -> runtime/graphics/<Label>.png
# in the distributed package the graphics ship under  graphics/  and can be refreshed on site
```

Run it before `setup-assets.py` (and again before an event when the sheet graphics
changed). `setup-assets.py` then resolves `__IRO_GRAPHICS__` to this folder; a graphic
that is still missing only prints a warning (it never fails) and OBS shows that source
black until you fetch it.

Next: [OBS Setup](OBS-Setup).
