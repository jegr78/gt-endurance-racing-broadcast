# If something goes wrong

Problem → fix. When in doubt, run `racecast preflight` first — it catches
most setup problems (tools, ports, cookies) before they bite you live.

## A feed won't show

| Problem | Fix |
|---------|-----|
| Feed says *"Sign in to confirm you're not a bot"* | Refresh cookies (`racecast cookies firefox`) and make sure **deno** is installed — the feeds need both. |
| Cookie export from Chrome/Edge/Brave says FAILED | On **Windows** these browsers cannot be exported at all — their cookies are app-bound encrypted (Chrome 127+). Log into YouTube in **Firefox** and run `racecast cookies firefox` (works even while Firefox is running). On macOS/Linux: close the browser completely first — it locks its cookie database while running — then re-run. |
| A feed just won't appear | Is the commentator actually live right now? Update the tools (`racecast install-tools --update`) and try again. |
| Nothing happens when you open a feed's address in a browser | That's normal — each feed serves only OBS, not browsers. Not a fault. |
| The handover didn't switch feeds | Press **Feeds Next** once **after** cutting to the new feed; the off-air feed only advances on Feeds Next, never mid-stint. |
| POV PiP is black after **POV Toggle** | Shown too early — the pull wasn't ready yet. Open `http://<producer-tailscale-ip>:8088/status`: the `pov` block must say `serving` (`connecting` = still resolving, or the driver isn't live yet — the relay retries every 15 s on its own). Hide the PiP, wait for `serving`, toggle again. Full timing: [Director guide](Director#showing-a-driver-pov-plan-ahead). |
| `racecast update` says binaries are still building | The release was just cut and CI is still uploading — retry in a few minutes. |

## The HUD / overlay is blank or stale

| Problem | Fix |
|---------|-----|
| HUD is blank in OBS | The relay draws the HUD — make sure it's running (`racecast relay start`). |
| HUD text isn't updating | It updates within a few seconds. Check you're editing the **Overlay** tab of the sheet and that the sheet is still shared. |
| A flag or team logo is missing | The image file's name must match the text in the sheet (lowercase, spaces become `-`). Run `python3 tools/fetch-flags.py` to fetch any missing flags. Full detail: [OBS & scenes](OBS-Setup). |

## The director can't connect

| Problem | Fix |
|---------|-----|
| First triage | Director-side checks (Tailscale app, right URL, panel password) are on [Director setup → If you cannot connect](Director-Setup#if-you-cannot-connect) — have the director run through those while you check below. |
| Director can't reach the buttons | Run `racecast tailscale status` — the process icon alone says nothing about being connected; the backend must be `Running`. If it shows `Stopped`, run `racecast tailscale up` first. Then check: Tailscale connected on both machines? Companion running with **GUI Interface = All Interfaces**? Using the **Tailscale** address (`100.x.y.z`), not a local one? |
| Buttons load but OBS shows disconnected | OBS open with the WebSocket server on (port `4455`) and the **same password** entered in Companion? |

## No Discord audio (interviews)

| Problem | Fix |
|---------|-----|
| No interview audio | Discord must run **windowed** (not fullscreen), and the producer must have **joined the voice channel locally**. |
| Discord source dead after switching machine/OS | `racecast setup` localizes the capture source per OS (macOS *App Audio Capture* · Windows *Application Audio Capture* on `Discord.exe` · Linux [PipeWire Audio Capture plugin](https://obsproject.com/forum/resources/pipewire-audio-capture.1458/), untested) — re-run `racecast setup` and re-import. |
| Interview audio doubled / echo | Capture Discord only through that audio-capture source — not *also* via desktop audio. |

## Everything is laggy

| Problem | Fix |
|---------|-----|
| General lag / stutter | Memory is the usual limit (16 GB) — **reboot before the event**, close other apps, run preflight. Make sure OBS uses your GPU to encode. |

---

Deeper diagnostics for developers: [Architecture](Architecture),
[Relay — how the feeds work](Relay-Mode).
