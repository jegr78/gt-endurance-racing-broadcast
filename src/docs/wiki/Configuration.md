# Configuration

> Technical reference. The setup steps are in [Set up the broadcast PC](Set-up-the-broadcast-PC).

Two things are machine- and event-specific and are **never** hardcoded or committed:
the **Google Sheet ID** (schedule + HUD data) and, optionally, the **race-timer webhook
URL**. Both come from a gitignored `.env` file. Then `setup-assets.py` localizes the OBS
collection for this machine.

## The `.env` file

At the repository (or package) root there is a tracked template, `.env.example`. Copy
it and fill in your values:

```bash
cp .env.example .env
```

```ini
# .env  (gitignored — never commit this)
IRO_SHEET_ID=your_google_sheet_id_here
IRO_TIMER_PUSH_URL=https://script.google.com/macros/s/…/exec?key=your_secret
```

- **`IRO_SHEET_ID`** — the long ID from your HUD/schedule sheet URL:
  `https://docs.google.com/spreadsheets/d/`**`<THIS>`**`/edit`. Drives the relay:
  the schedule, the POV tab, and the HUD overlay (Overlay + Configuration tabs, served
  at `/hud`).
- **`IRO_TIMER_PUSH_URL`** *(optional)* — the Apps Script write webhook for the relay-hosted
  race timer. Lets Director actions (start/stop/show/hide/correct) sync to the Sheet's
  `Timer` tab so a second producer machine takes over with the same countdown. Unset =
  timer works on this machine only. See [Race-Timer](Race-Timer) for setup.
- **`IRO_INTRO_URL` / `IRO_OUTRO_URL`** *(optional)* — override the Intro/Outro clip
  URLs that normally come from the Sheet **Assets** tab (used by `iro media`).
- **`IRO_COMPANION_EXE`** *(optional, Windows)* — full path to `Companion.exe` for
  `iro companion start/stop`. Only needed when Companion sits in a non-standard
  location; the standard install paths are found automatically, e.g. the
  winget / `iro install-apps` default:
  `IRO_COMPANION_EXE=C:\Program Files\Companion\Companion.exe`

Real environment variables take precedence over `.env`. The loader only reads a `.env`
from the script directory or the project root (marked by `.git` / `.env.example`),
never an unrelated parent directory.

> **Security:** `.env` is gitignored and must stay that way. The `IRO_TIMER_PUSH_URL`
> contains a shared secret — if it ever leaks, redeploy the Apps Script with a new key
> and update the URL in `.env` on every producer machine.

## Localize the OBS collection (`setup-assets.py`)

The OBS scene collection in git is deliberately **path- and secret-free**: it stores
tokens instead of real paths and URLs. `setup-assets.py` injects the real values from
`.env` and writes an importable collection:

```bash
iro setup --out runtime/IRO_Endurance.import.json
```

The tokens in the collection:

| Token | Resolves to |
|-------|-------------|
| `__IRO_GRAPHICS__` | `runtime/graphics/` (package: `graphics/`) — the Sheet-driven broadcast graphics, `__IRO_GRAPHICS__/<Label>.png` |
| `__IRO_MEDIA__` | `runtime/media/` — the Intro/Outro clips |

(The HUD overlay and the race timer are both served by the relay at fixed loopback URLs —
the collection embeds neither the sheet ID nor any external service URL; no token is
needed for them.)

So `setup-assets.py`:
- rewrites the broadcast-graphic image paths (`__IRO_GRAPHICS__`) to **this** machine's
  `runtime/graphics/` folder. Those PNGs are **not** committed — download them first with
  `iro graphics` (see [Sheet-driven graphics](#sheet-driven-graphics)
  below); a graphic still missing prints a warning and OBS shows that source black.

(The HUD overlay and race timer need no injection — both are served by the relay;
`IRO_SHEET_ID` is read by the relay, not the collection.)

> `__IRO_ASSETS__` is retired from the OBS collection. `src/assets/` now holds **only**
> the bundled HUD `flags/` + `brands/` logos — these stay committed and are served by the
> relay HUD, not by the OBS collection.

You can override the graphics path per-run without `.env`: `--sheet-id <ID>`.

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
iro graphics            # -> runtime/graphics/<Label>.png
```

Run it before `setup-assets.py` (and again before an event when the sheet graphics
changed). `setup-assets.py` then resolves `__IRO_GRAPHICS__` to this folder; a graphic
that is still missing only prints a warning (it never fails) and OBS shows that source
black until you fetch it.

Next: [OBS Setup](OBS-Setup).
