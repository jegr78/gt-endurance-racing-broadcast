# If something goes wrong

Problem → fix. When in doubt, run `iro preflight` first — it catches
most setup problems (tools, ports, cookies) before they bite you live.

## A feed won't show

| Problem | Fix |
|---------|-----|
| Feed says *"Sign in to confirm you're not a bot"* | Refresh cookies (`iro cookies chrome`) and make sure **deno** is installed — the feeds need both. |
| `iro cookies chrome` says FAILED (*"Could not copy … cookie database"*) | Close Chrome **completely** first (all windows, plus its tray/background mode) — Chrome locks its cookie database while it runs — then re-run. If Chrome's cookie **encryption** still blocks the export, log into YouTube in Firefox and use `iro cookies firefox`. |
| A feed just won't appear | Is the commentator actually live right now? Update the tools (macOS/Linux `brew upgrade streamlink yt-dlp` · Windows `pip install -U streamlink yt-dlp`) and try again. |
| Nothing happens when you open a feed's address in a browser | That's normal — each feed serves only OBS, not browsers. Not a fault. |
| The handover didn't switch feeds | Press **Feeds Next** once **after** cutting to the new feed; the off-air feed only advances on Feeds Next, never mid-stint. |

## The HUD / overlay is blank or stale

| Problem | Fix |
|---------|-----|
| HUD is blank in OBS | The relay draws the HUD — make sure it's running (`iro relay start`). |
| HUD text isn't updating | It updates within a few seconds. Check you're editing the **Overlay** tab of the sheet and that the sheet is still shared. |
| A flag or team logo is missing | The image file's name must match the text in the sheet (lowercase, spaces become `-`). Run `python3 tools/fetch-flags.py` to fetch any missing flags. Full detail: [OBS & scenes](OBS-Setup). |

## The director can't connect

| Problem | Fix |
|---------|-----|
| Director can't reach the buttons | Tailscale "Connected" on both machines? Companion running with **GUI Interface = All Interfaces**? Using the **Tailscale** address (`100.x.y.z`), not a local one? |
| Buttons load but OBS shows disconnected | OBS open with the WebSocket server on (port `4455`) and the **same password** entered in Companion? |

## No Discord audio (interviews)

| Problem | Fix |
|---------|-----|
| No interview audio | Discord must run **windowed** (not fullscreen), and the producer must have **joined the voice channel locally**. The OBS source is *App Audio Capture* (macOS) / *Application Audio Capture* (Windows; Linux via PipeWire — *should work, not yet tested on Linux*). |
| Interview audio doubled / echo | Capture Discord only through that audio-capture source — not *also* via desktop audio. |

## Everything is laggy

| Problem | Fix |
|---------|-----|
| General lag / stutter | Memory is the usual limit (16 GB) — **reboot before the event**, close other apps, run preflight. Make sure OBS uses your GPU to encode. |

---

Deeper diagnostics for developers: [Architecture](Architecture),
[Relay — how the feeds work](Relay-Mode).
