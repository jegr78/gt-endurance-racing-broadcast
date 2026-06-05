# Relay Mode

> Technical reference. The operator version is [Run an event](Run-an-event).

The recommended flow for endurance racing: **one commentator per stint**, streams
**unlisted**, two fixed feeds that "walk" along the schedule. See
[Architecture §2](Architecture#2-relay-ping-pong-the-endurance-flow) for the diagram.

## How it pulls (important)

The relay uses **yt-dlp to resolve** each live HLS URL — this is what passes YouTube's
bot-check, via `cookies.txt` + deno JS-challenge solving — and **streamlink to serve**
that direct URL to OBS. So `cookies.txt` and `deno` are both required for reliable pulls.
Streamlink alone, even with cookies, is blocked by the bot-check.

A running feed is **never** torn off mid-stint. Sheet edits apply on the next `/next`
(handover) or `/reload`. Curling a feed port returns nothing — each port serves a single
consumer (OBS); that is not a failure.

## 1. The schedule (Google Sheet tab `Schedule`)

- One column holds the entries **in stint order**; other columns (stint number / name)
  are ignored. Editable remotely by anyone with sheet access.
- **Unlisted streams → use the watch URL** `https://www.youtube.com/watch?v=VIDEOID`.
  The channel `/live` URL only works for **public** streams. The streamer/director enters
  their watch URL shortly before their stint.
- Default sheet = the shared HUD sheet (from `IRO_SHEET_ID`). Override with
  `--sheet-id …` / `--sheet-tab …`.

## 2. Get YouTube cookies (before each event)

Against YouTube's *"Sign in to confirm you're not a bot"*. Easiest — auto-export from
your **logged-in** browser:

```bash
iro cookies chrome
# browsers: chrome | firefox | safari | edge | brave
```

- You must be **logged into YouTube** in that browser.
- macOS **Chrome/Edge**: approve the Keychain prompt. **Safari**: grant your terminal
  **Full Disk Access**. (Firefox needs neither.)
- Windows / Linux: the browser export usually runs without a prompt (Firefox needs none
  on any OS).
- Writes `runtime/cookies.txt` (chmod 600), auto-detected and passed to Streamlink.
  `/status` then shows `"cookies": true`. **Re-run before each event** — cookies rotate.
- Alternative: let the relay export on start with `--cookies-from-browser chrome`, or
  drop any Netscape `cookies.txt` next to the relay.

## 3. Start the relay

```bash
iro relay start        # background
iro relay run          # foreground/debug mode
```

Stop with `iro relay stop` (or Ctrl+C in foreground mode). For remote
directors, bind the control server to the producer's **Tailscale IP** (not `0.0.0.0`) —
see [Director](Director) and the security note below.
(Developers running from the repo: python3 src/iro.py works the same everywhere.)

## 4. Control it (Companion → relay)

Companion connection **"Generic HTTP Requests"**, action **GET**:

| Button | Endpoint | When |
|--------|----------|------|
| **Feeds Next** | `http://127.0.0.1:8088/next` | once per handover, right after cutting to the new feed |
| **Feeds Reload** | `http://127.0.0.1:8088/reload` | edited a cell in the sheet → reload the current feed now |
| **Feeds Status** | `http://127.0.0.1:8088/status` | inspect feed state, cookies, URLs |
| **Feed A Reload** | `http://127.0.0.1:8088/reload/A` | reconnect only Feed A (one feed glitched mid-stint) |
| **Feed B Reload** | `http://127.0.0.1:8088/reload/B` | reconnect only Feed B |

Works for remote directors too — Companion makes the request locally on the producer
station.

---

## The HUD overlay (served by the relay)

The relay also serves the lower-third HUD, so it must be running for the HUD to render.
It reads the **Overlay** tab (live values) and the **Configuration** tab (team →
manufacturer via a `Brand Name` column) and exposes:

- `GET /hud` — the overlay page; point one OBS Browser Source at
  `http://127.0.0.1:8088/hud` (1920×1080, transparent).
- `GET /hud/data` — the live values as JSON; the page polls it every ~2.5 s, so editing
  the sheet updates the overlay with **no manual reload**.

Flags and brand logos are bundled assets resolved from text: the Country text →
`flags/<country>.svg`, a team's `Brand Name` → `brands/<key>.png`. Add a new round's
flag with `python3 tools/fetch-flags.py` (fetches only what is missing). Flags:
`--no-hud` (disable), `--overlay-tab` / `--config-tab` (tab names), `--hud-poll`
(refresh seconds, default 5). See [OBS Setup](OBS-Setup) for the source itself.

---

## Driver-POV PiP (optional)

Show an ad-hoc driver POV as a small picture-in-picture (bottom-right) over the active
feed in the **Stint** scene. Pulled by a third relay feed on port **53003** (capped at
720p), independent of the A/B ping-pong.

1. **Schedule it:** put the driver's live **watch URL** into the Google Sheet tab
   **`POV`**, cell **A2** (A1 = header `url`). Empty cell = POV off.
2. **Pull it:** press **POV Reload** → the relay resolves + serves it on 53003 (still
   hidden). `/status` shows the `pov` block (`state: serving`).
3. **Show it:** press **POV Toggle** → the PiP appears bottom-right in Stint.
4. **Audio:** muted by default; **MUTE POV** toggles mute, **VOL POV UP / VOL POV DOWN** adjust
   volume (use briefly).
5. **Done:** **POV Toggle** to hide, then **POV Stop** (frees the pull / bandwidth).

Two rules: **Reload before Toggle (show)**, and **hide + POV Stop when done**. The PiP
lives only in the Stint scene, so switching to Splitscreen/Interview/Standby auto-hides
and auto-silences it.

---

## Security note

The relay's control server (`:8088`) is **unauthenticated**. By default it binds to
`127.0.0.1` (local only). For remote directors use `--bind <tailscale-ip>` — **prefer the
Tailscale IP over `0.0.0.0`**, because the endpoints have no auth and `/status` reveals
stream URLs. `--no-panel` disables the served director panel.

## Quickstart

```bash
# 1. Fill the sheet tab 'Schedule' with watch URLs (unlisted), in stint order.
iro cookies chrome   # 2. refresh YouTube cookies
iro relay start      # 3. start the relay (background)
# 4. Companion buttons:  Feeds Next -> /next   ·   Feeds Reload -> /reload
```

See also: [Static Mode](Static-Mode) (the simpler fallback), [Run an event](Run-an-event).
