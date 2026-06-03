# OBS Setup

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

## 5. Discord audio (interviews)

The source **Discord Audio Capture** comes with the collection.

- **macOS:** it's an `sck_audio_capture` source bound to the Discord app. Grant OBS
  **Screen &amp; System Audio Recording** permission once (System Settings → Privacy &amp;
  Security). **Keep Discord in windowed mode, NOT fullscreen** — otherwise it is not
  captured.
- **Windows:** re-create the source as **Application Audio Capture (BETA)** → pick
  **Discord**. Don't *also* capture Discord via desktop audio, or you'll double it.

## 6. Stream key

Enter the **IRO YouTube channel** stream key in OBS only at event time
(**Settings → Stream**).

Next: [Companion](Companion), then [Relay Mode](Relay-Mode).
