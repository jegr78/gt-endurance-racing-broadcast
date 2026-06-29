# Relay Mode

> Technical reference. The operator version is [Run an event](Run-an-event).

The recommended flow for endurance racing: **one commentator per stint**, streams
**unlisted**, two fixed feeds that "walk" along the schedule. See
[Architecture §2](Architecture#2-relay-ping-pong-the-endurance-flow) for the diagram.

## How it pulls (important)

The relay supports **YouTube and Twitch** feeds (YouTube via yt-dlp, Twitch direct via Streamlink).

**YouTube feeds:** the relay uses **yt-dlp to resolve** each live HLS URL — this is what
passes YouTube's bot-check, via `yt-cookies.txt` + deno JS-challenge solving — and
**streamlink to serve** that direct URL to OBS. So `yt-cookies.txt` and `deno` are both
required for reliable YouTube pulls. Streamlink alone, even with cookies, is blocked by
the bot-check.

**Twitch feeds:** the relay routes those directly through Streamlink's native Twitch
plugin (no yt-dlp hop). Low-latency mode is enabled automatically; ad filtering is
handled by Streamlink's current built-in behavior. Public Twitch channels need no
cookies; gated (subscriber/follower-only) channels need `twitch-cookies.txt`
(see [§2 below](#2-producer-accounts-and-cookies-before-each-event)).

A running feed is **never** torn off mid-stint. Sheet edits apply on the next `/next`
(handover) or `/reload`. Curling a feed port returns nothing — each port serves a single
consumer (OBS); that is not a failure.

## 1. The schedule (Google Sheet tab `Schedule`)

- One column holds the entries **in stint order**; other columns (stint number / name)
  are ignored. Editable remotely by anyone with sheet access.
- **Enter full watch URLs** for each stint:
  - YouTube: `https://www.youtube.com/watch?v=VIDEOID` — **unlisted streams must use
    this form**; the channel `/live` URL only works for public streams. A bare
    `UC…` channel ID is also accepted as a shorthand for YouTube streams.
  - Twitch: `https://www.twitch.tv/<channel>` — there is no bare-ID short form for Twitch.
- The streamer/director enters their watch URL shortly before their stint.
- Default sheet = the shared HUD sheet (the active profile's `SHEET_ID`). Override with
  `--sheet-id …` / `--sheet-tab …`.

## 2. Producer accounts and cookies (before each event)

### YouTube login (required)

Against YouTube's *"Sign in to confirm you're not a bot"*. Easiest — auto-export from
your **logged-in** browser:

```bash
racecast cookies firefox
# browsers: firefox | chrome | safari | edge | brave   (Firefox recommended)
```

- You must be **logged into YouTube** in that browser.
- **Firefox is the recommended source on every OS** — no prompts, and it works even
  while Firefox is running.
- **Windows**: Chrome/Edge/Brave **cannot** be exported — their cookies are app-bound
  encrypted (Chrome 127+); use Firefox.
- macOS **Chrome/Edge**: approve the Keychain prompt. **Safari**: grant your terminal
  **Full Disk Access**. (Firefox needs neither.)
- Writes `runtime/yt-cookies.txt` (chmod 600), auto-detected and passed to yt-dlp.
  `/status` then shows `"cookies": true`. **Re-run before each event** — cookies rotate.
- Alternative: let the relay export on start with `--cookies-from-browser firefox`, or
  drop any Netscape `yt-cookies.txt` next to the relay (a legacy `cookies.txt` is
  migrated automatically on first use).

### Twitch login (optional)

Only needed for **gated** (subscriber/follower-only) Twitch streams. Public Twitch
channels work without any cookies. If any stint uses a gated Twitch feed, export the
producer's Twitch session before the event:

```bash
racecast cookies twitch firefox
# browsers: firefox | chrome | safari | edge | brave   (Firefox recommended)
```

- You must be **logged into Twitch** in that browser (not YouTube — a separate session).
- Writes `runtime/twitch-cookies.txt` (chmod 600), auto-detected by the relay for
  Twitch feeds. The `/status` `cookies` field shows whether the YouTube cookie jar is loaded.
- **Re-run before each event** alongside the YouTube refresh.

### Summary: which accounts the producer needs

| Account | When needed | Cookie file |
|---|---|---|
| **YouTube** (logged in) | Always — needed for the bot-check on any YouTube feed | `yt-cookies.txt` |
| **Twitch** (logged in) | Only if any stint uses a gated (sub/follower-only) Twitch feed | `twitch-cookies.txt` |

The cookies are shared across all leagues on the machine and live at the top-level
`runtime/` directory (not per-profile).

### Known limits

- **YouTube server-side ads (DAI/SSAI):** if the streamer's channel serves server-side
  inserted ads, the relay detects the ad marker in the stream and reports it in
  `/status` (surfaced as the feed's `last_error` in `/status`, and shown on the director panel).
  The relay cannot remove them — there is no reliable skip mechanism. The clean solution
  is an ad-free source: league-owned, unlisted, unmonetized stint streams have no server-side ads.
- **Twitch ad filtering:** handled automatically by Streamlink's current built-in
  behavior. Coverage depends on Streamlink's version and Twitch's current serving
  method.
- **Twitch URL form:** always use the full `twitch.tv/<channel>` URL in the schedule.
  There is no bare-ID short form for Twitch (unlike YouTube's bare `UC…` channel ID).

## 3. Start the relay

```bash
racecast relay start        # background
racecast relay run          # foreground/debug mode
```

Stop with `racecast relay stop` (or Ctrl+C in foreground mode). For remote
directors, bind the control server to the producer's **Tailscale IP** (not `0.0.0.0`) —
see [Director](Director) and the security note below.
(Developers running from the repo: python3 src/racecast.py works the same everywhere.)

**Taking over mid-event (multi-part broadcasts):** start the relay at the stint
that is on air right now —

```bash
racecast relay start --stint 4   # stint 4 is live: Feed A serves it, Feed B preloads stint 5
```

`--stint` puts that stint on Feed A and preloads the next one on Feed B — there
is no need to continue the previous producer's A/B order; `/next` works as
usual from there. Full checklist:
[Run an event → Producer handover](Run-an-event#producer-handover-12h24h-multi-part-events).

## 4. Control it (Companion → relay)

Companion connection **"Generic HTTP Requests"**, action **GET**:

| Button | Endpoint | When |
|--------|----------|------|
| **Feeds Next** | `http://127.0.0.1:8088/next` | once per handover, right after cutting to the new feed |
| **Feeds Reload** | `http://127.0.0.1:8088/reload` | edited a cell in the sheet → reload the current feed now |
| **Feeds Status** | `http://127.0.0.1:8088/status` | inspect feed state, cookies, URLs |
| **Feed A Reload** | `http://127.0.0.1:8088/reload/A` | reconnect only Feed A (one feed glitched mid-stint) |
| **Feed B Reload** | `http://127.0.0.1:8088/reload/B` | reconnect only Feed B |

**Feeds Next (`/next`)** now also drives OBS over obs-websocket: it makes the new
commentator visible in the **Stint** scene, switches the feed audio, and cuts the
program to **Stint** (only once the incoming feed is actually serving — never to a
black/buffering feed). No Feed A/B choice and no special case for starting with one
link. Requires obs-websocket reachable (see Pre-flight); otherwise the manual
panel/Companion FEED + scene buttons remain the fallback.

Works for remote directors too — Companion makes the request locally on the producer
station.

One more endpoint for the browser (not a Companion button — it needs a number):
`http://127.0.0.1:8088/set/stint/<n>` positions BOTH feeds for a producer
takeover (1-based: stint n on Feed A, n+1 preloaded on Feed B). It tears
running feeds — use it before going live, never mid-program.

---

## The HUD overlay (served by the relay)

The relay also serves the lower-third HUD, so it must be running for the HUD to render.
It reads the **Overlay** tab (live values) and the **Configuration** tab (team →
manufacturer via a `Brand Name` column) and exposes:

- `GET /hud` — the overlay page; point one OBS Browser Source at
  `http://127.0.0.1:8088/hud` (1920×1080, transparent).
- `GET /hud/data` — the live values as JSON; the page polls it every ~2.5 s, so editing
  the sheet updates the overlay with **no manual reload**.
- `GET /intermission` — a read-only broadcast-chat panel for the **Intermission** OBS
  scene: always-visible, auto-scrolling, mirrors the same public YouTube/Twitch broadcast
  chat as the crew console's broadcast-chat card. Point the Intermission scene's chat
  Browser Source at `http://127.0.0.1:8088/intermission`. The relay must be running for
  it to render; if broadcast-chat is disabled the page shows an empty panel. The per-league
  override CSS is at `/intermission/override.css` (from
  `profiles/<name>/overlay/intermission.css`).

Flags and brand logos are bundled assets resolved from text: the Country text →
`flags/<country>.svg`, a team's `Brand Name` → `brands/<key>.png`. Add a new round's
flag with `python3 tools/fetch-flags.py` (fetches only what is missing). Flags:
`--no-hud` (disable), `--overlay-tab` / `--config-tab` (tab names), `--hud-poll`
(refresh seconds, default 5). See [OBS Setup](OBS-Setup) for the source itself.

---

## Driver-POV PiP (optional)

A third relay feed on port **53003** (capped at 720p), independent of the A/B ping-pong,
serves an ad-hoc driver POV as a small picture-in-picture (bottom-right) over the active
feed in the **Stint** scene. The driver's live **watch URL** comes from the Google Sheet
tab **`POV`** (row 2; columns `url` and `name`, where `name` is an optional on-screen
label ≤20 chars — empty `url` = POV off), set there directly or from the panel's POV row.

The relay resolves and serves it on **POV Reload** (`/pov/reload`); `/status` reports the
`pov` block (`state: connecting` while resolving or waiting for the driver, `serving`
once ready). **POV Toggle** (`/pov/toggle`) is a **relay action**: it flips the relay's
`pov_shown` state, shows/hides the `Feed POV` PiP in OBS (best-effort), and the HUD POV
box (frame + name) follows it. The PiP lives only in the Stint scene, so switching to
Splitscreen/Interview/Standby auto-hides and auto-silences it; audio is muted by default.

**Lead time:** the PiP is not instant — plan roughly **5 minutes** from "driver starts
streaming" to "PiP on air" (resolve ~10–30 s, plus the 15 s retry loop while the driver
isn't live yet, plus OBS connecting on first show). The operator walkthrough — including
the order of the button presses — is in the
[Director guide](Director#showing-a-driver-pov-plan-ahead).

---

## Security note

The relay's control server (`:8088`) is **unauthenticated**. By default it binds to
`127.0.0.1` (local only). For remote directors use `--bind <tailscale-ip>` — **prefer the
Tailscale IP over `0.0.0.0`**, because the endpoints have no auth and `/status` reveals
stream URLs. `--no-panel` disables the served director panel.

## Quickstart

```bash
# 1. Fill the sheet tab 'Schedule' with watch URLs (YouTube or Twitch), in stint order.
racecast cookies firefox         # 2a. refresh YouTube cookies (required)
racecast cookies twitch firefox  # 2b. refresh Twitch cookies (only if any gated Twitch feed)
racecast relay start             # 3. start the relay (background)
# 4. Companion buttons:  Feeds Next -> /next   ·   Feeds Reload -> /reload
```

See also: [Static Mode](Static-Mode) (the simpler fallback), [Run an event](Run-an-event).
