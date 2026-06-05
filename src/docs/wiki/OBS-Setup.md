# OBS Setup

> Technical reference. The quick version is in [Set up the broadcast PC](Set-up-the-broadcast-PC).

Import the scene collection, confirm the graphics, and wire up Discord audio. Do
[Configuration](Configuration) first so `setup-assets.py` has produced the importable
collection.

## 1. Import the scene collection

1. OBS → **Scene Collection → Import** → select `runtime/IRO_Endurance.import.json`
   (in the package: `obs/IRO_Endurance.import.json`).
2. Switch to the **IRO Endurance** collection.
3. **Images there?** Overlay / Standings / … should be visible. If not, `setup-assets.py`
   didn't run for this machine — re-run it and re-import (see [Configuration](Configuration)).

> Import the `.import.json`, **not** the `.template.json`. Never move the folder after
> import — OBS stores absolute image paths.

## 2. The scenes

- **Stint** — the active feed full-screen + HUD overlay (POV PiP lives only here). It also
  holds a hidden **Standby Cover** (the dedicated `Standby Cover.png` graphic — a neutral
  cover, distinct from the Standby scene's `Standby.png` thumbnail) **below the HUD group**,
  so showing it hides the feeds and the POV PiP while the Race Control banner and timer stay
  on top. The director toggles it with the Companion **Standby Toggle** button (a
  *Set Source Visibility* toggle on `Stint / Standby Cover`, with a *Source Visible*
  feedback so it lights while active). Re-add the source after a rebuild with
  `python3 tools/add_standby_cover.py src/obs/IRO_Endurance.json`.
- **Splitscreen** — two feeds side by side, for the ~10-minute handover.
- **Interview** — interview graphic + Discord audio.
- **Standby / BRB** — for breaks.
- **Intro** / **Outro** — full-screen stream-open and stream-close clips that **loop with
  audio**, played from local files (`runtime/media/intro.mp4` / `outro.mp4`). The director
  switches to them with the Companion **INTRO** / **OUTRO** buttons. The file paths are
  tokenised as `__IRO_MEDIA__` in the collection and resolved by `setup-assets.py`; download
  or refresh the clips from the Sheet **Assets** tab with `iro media`
  (see [Configuration](Configuration)). If the clips are missing the scene shows black.

> **Broadcast graphics are local files.** The still-graphics image sources — Overlay,
> Standings, Schedule, Race Results, Quali Results, Standby, Standby Cover, and the three
> **weather** overlays (**Race Weather 1**, **Race Weather 2**, **Quali Weather**) — read from
> `runtime/graphics/<Label>.png`. They are tokenised `__IRO_GRAPHICS__` in the collection
> and resolved by `setup-assets.py`. Download them from the Sheet **Assets** tab with
> `iro graphics` (one PNG per Assets row, the Sheet label is the
> filename); a source whose file is missing shows black until you fetch it. The three
> weather graphics are **hidden full-screen overlays in the Stint scene**, each switchable
> by its own Companion toggle (`Weather Race (1) Toggle` / `Weather Race (2) Toggle` / `Weather Quali Toggle` — see
> [Director guide](Director)), exactly like the Standings/Results toggles.

## 3. Media Sources (the feeds)

Each feed is a **Media Source** pointed at a fixed local port — these come with the
collection and never change URL:

| Source | Input |
|--------|-------|
| Feed A | `http://127.0.0.1:53001` |
| Feed B | `http://127.0.0.1:53002` |
| POV    | `http://127.0.0.1:53003` |

If you ever recreate one: uncheck **Local File**, set the input URL, tick **Use hardware
decoding**, set **Network Buffering** to `8`–`16` MB (stacks on top of Streamlink's
buffer) and **Reconnect Delay** to `10` s.

The ports are served by the [Relay](Relay-Mode) (recommended) or by
[Static Mode](Static-Mode).

## 4. HUD &amp; graphics (Browser Sources)

The HUD and info-graphics are **Browser Sources** driven live by the shared Google Sheet
and stagetimer.io. They are left in the scene and toggled by the director via Companion —
no screen-share, no extra latency. Their URLs were injected from `.env` by
`setup-assets.py`.

> The HUD and graphics pull from **shared** production resources (the sheet and
> stagetimer) — changes affect everyone. The sheet must stay shared.

### The lower-third HUD: one relay-served overlay

The lower-third HUD (streamer, session, round, flag, top-3 teams, race control) is a
**single** Browser Source named **HUD Overlay** pointing at the relay:
`http://127.0.0.1:8088/hud`. It replaces the old set of ~13 per-cell Browser Sources
(each of which loaded the full Google Sheets editor and was cropped with a chroma key) —
that approach was the main cause of producer-machine lag.

- **The relay must be running** for the HUD to render (it serves `/hud`). See
  [Relay Mode](Relay-Mode).
- **Content is still edited centrally in the sheet** — no manual reloads: the page polls
  the relay every ~2.5 s, and the relay refreshes the sheet every `--hud-poll` seconds
  (default 5). Live values come from the **Overlay** tab; the **Configuration** tab maps
  each team to its manufacturer via a **`Brand Name`** text column (header may also be
  `Brand Key` or `Brand`; the image columns `Brand Logo`/`Brands` are ignored).
- **Flags and brand logos** are bundled assets in `src/assets/flags/` and
  `src/assets/brands/`, resolved by text: the Country text → `flags/<country>.svg`, and a
  team's `Brand Name` → `brands/<key>.png|svg` (lowercase, spaces → `-`). Add a flag/logo by
  dropping a matching `.svg` in those folders.
- Relay flags: `--no-hud` disables it; `--overlay-tab` / `--config-tab` override tab names;
  `--hud-poll` sets the refresh interval.

The stagetimer countdown stays its own Browser Source (it is a real-time page, not sheet
data).

## 5. Discord audio (interviews)

The source **Discord Audio Capture** comes with the collection. `iro setup` realizes it
for the importing OS — no manual source-switching needed.

- **macOS:** `App Audio Capture` (ScreenCaptureKit), bound to the Discord app. Grant OBS
  **Screen &amp; System Audio Recording** permission once (System Settings → Privacy &amp;
  Security). **Keep Discord in windowed mode, NOT fullscreen** — otherwise it is not
  captured.
- **Windows:** `Application Audio Capture`, bound to `Discord.exe`. Any Discord window
  title works — channel names don't matter. Don't *also* capture Discord via desktop
  audio, or you'll double it.
- **Linux:** requires the
  [PipeWire Audio Capture plugin](https://obsproject.com/forum/resources/pipewire-audio-capture.1458/)
  (untested). Install the plugin before importing the collection.
- **Switched production machine or OS?** Re-run `iro setup` and re-import the collection.

## 6. Stream key

Enter the **IRO YouTube channel** stream key in OBS only at event time
(**Settings → Stream**).

Next: [Companion](Companion), then [Relay Mode](Relay-Mode).
