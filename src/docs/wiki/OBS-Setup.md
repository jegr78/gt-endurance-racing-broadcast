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

- **Stint** — the active feed full-screen + HUD overlay (POV PiP lives only here).
- **Splitscreen** — two feeds side by side, for the ~10-minute handover.
- **Interview** — interview graphic + Discord audio.
- **Standby / BRB** — for breaks.

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

The source **Discord Audio Capture** comes with the collection.

- **macOS:** it's an `sck_audio_capture` source bound to the Discord app. Grant OBS
  **Screen &amp; System Audio Recording** permission once (System Settings → Privacy &amp;
  Security). **Keep Discord in windowed mode, NOT fullscreen** — otherwise it is not
  captured.
- **Windows:** re-create the source as **Application Audio Capture (BETA)** → pick
  **Discord**. Don't *also* capture Discord via desktop audio, or you'll double it.
- **Linux:** re-create the source as **Application Audio Capture** (PipeWire), or use an
  **Audio Output Capture** monitor source — *should work, not yet tested on Linux.*

## 6. Stream key

Enter the **IRO YouTube channel** stream key in OBS only at event time
(**Settings → Stream**).

Next: [Companion](Companion), then [Relay Mode](Relay-Mode).
