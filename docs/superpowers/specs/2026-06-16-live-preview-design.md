# Live Preview in the Director Panel — Design

**Date:** 2026-06-16
**Status:** Approved (brainstorming) — ready for implementation plan
**Surface:** Director Panel (`/panel`) only

## Problem

A remote director drives the broadcast through the Director Panel over the
tailnet but **cannot see what the broadcast looks like** — they have no view of
the OBS program output, and no way to check an upcoming commentator feed before
cutting to it. They are flying blind on the one thing that matters most: the
picture going out.

## Goal

Give the director, inside the panel, an on-demand multiview:

- A **Program tile** — the live OBS program output (active scene incl. HUD and
  overlays), auto-refreshing ~1.5 s, i.e. exactly what viewers see.
- A **Feed tile per feed** — Feed A, Feed B, POV — a still grabbed **on click**,
  so the director can verify a feed (alive? correctly framed?) before a cut.

The section is **collapsible and hidden by default**; it does work (and uses
bandwidth) only while shown.

## Key constraints

- **Bandwidth.** The off-air feeds are *not* being downloaded until OBS cuts to
  them (streamlink only pulls when a consumer connects), so previewing an
  upcoming feed always costs a real upstream pull. Mitigated by: feed stills are
  **click-only**, the program poll runs **only while the section is visible**, and
  a hidden section does **zero** work.
- **Trust boundary.** No new exposure: the relay already serves `/panel` and
  already speaks obs-websocket. The tailnet stays the trust boundary, same as
  `/status` (which already reveals stream URLs).
- **Never disturb the live broadcast.** All preview work is read-only and
  best-effort; it must never mutate OBS/feed state, never hang a relay thread,
  and never crash the panel.

## Architecture

The relay is the single broker — it runs on the producer machine (local
obs-websocket access on `127.0.0.1:4455` and local feed ports
`53001/53002/53003`) and is the component reachable by the remote director over
the tailnet. The browser polls/clicks; the relay brokers each frame.

Per-tile source routing the relay applies:

| Tile | Source | Why |
|---|---|---|
| Program | OBS `GetSourceScreenshot` of the **current program scene** | only OBS can render the composite (feed + HUD + overlays) |
| On-air feed (A or B) | OBS `GetSourceScreenshot` of `Feed A` / `Feed B` | already decoding → free, instant; the on-air port is held by OBS so a port grab can't connect anyway |
| Off-air feed | ffmpeg one-frame grab from the feed's own loopback port `127.0.0.1:5300X` | reuses the already-resolved feed pipeline; identical for YouTube/Twitch; no `yt-dlp -g` re-resolution |
| POV | OBS `GetSourceScreenshot` of `Feed POV` if active, else placeholder | POV starts paused; when paused port 53003 isn't serving |

**Off-air grab mechanism — decision.** Grab from the feed's own loopback port
rather than re-resolving the upstream URL. The off-air streamlink server is
already up and idle; one transient HTTP consumer (`ffmpeg -i
http://127.0.0.1:53002 -frames:v 1`) yields a frame using the pipeline streamlink
already built — no platform-specific code, no expired-URL handling, no slow
`yt-dlp` + cookies + deno round-trip. Same upstream cost as any other approach
(~1 segment). The one risk — a grab colliding with OBS at the exact handover
instant — is bounded by a short timeout and the fact grabs fire only on a click;
a failed grab just shows "nicht verfügbar" and the director re-clicks.

*Rejected alternatives:* (1) grab from the upstream URL directly — adds
platform-specific code, URL expiry, and a slow re-resolve, with no upside;
(2) OBS-only, no off-air grab — cheapest but fails the core upcoming-feed
pre-cut check (OBS isn't decoding the off-air feed, so its screenshot is
black/stale). OBS-only remains the fallback if the port grab proves flaky in
testing.

## Components

### `src/scripts/obs_ws.py`
- `parse_screenshot_data_uri(data_uri)` — **pure**: decode a
  `data:image/jpg;base64,…` payload to raw bytes; return `None` on a malformed
  URI (no comma / bad base64). Unit-tested.
- `get_source_screenshot(source_name, width=640, fmt="jpg", quality=60,
  host="127.0.0.1", port=None, password=None, timeout=2.0)` — open a session,
  send `GetSourceScreenshot` (`imageFormat`, `imageWidth`,
  `imageCompressionQuality`), decode the data URI, return `(jpeg_bytes, "")` or
  `(None, note)`. Best-effort, never raises — same contract as the rest of the
  module.
- For the Program tile the relay resolves the active scene via
  `GetCurrentProgramScene`, then screenshots that scene name. (A helper
  `get_program_screenshot(...)` may wrap the two calls; tested via a mock
  `_Session`.)

### `src/relay/racecast-feeds.py`
- `preview_source(target, live, pov_active, feed_ports)` — **pure** router →
  `("obs", "Feed A")` / `("grab", 53002)` / `("placeholder", reason)`. The heart
  of the routing; unit-tested in isolation. Inputs come from existing relay
  state: `live_feed()` (lower-index feed = on-air), the feed ports, and the POV
  running flag (`self.pov` present and not `self.pov.paused`).
- `feed_grab_cmd(port, width)` — **pure** ffmpeg arg-list builder
  (`-frames:v 1`, scale filter, mjpeg to stdout), pinned byte-for-byte by test
  like `streamlink_serve_cmd`.
- `GET /preview/program` → `image/jpeg` of the current program scene (used by
  the auto-poll).
- `GET /preview/feed/<A|B|POV>` → `image/jpeg` (used on click). Routes via
  `preview_source`, then either `obs_ws.get_source_screenshot(...)` or an ffmpeg
  grab (hard ~8 s timeout, subprocess killed on timeout).
- Both responses carry `Cache-Control: no-store`. Error/placeholder paths return
  **503** with a short note (so the panel can render a labelled placeholder).

### `src/director/director-panel.html`
- A collapsible **"Live Preview"** section, **hidden by default**; the
  open/closed state persists in `localStorage` (matching existing panel prefs).
- When shown: a large **Program tile** (`<img>` whose `src` is reassigned with a
  cache-busting `?ts=` every ~1.5 s) above a row of **Feed A / Feed B / POV**
  tiles, each with a `↻` button. Clicking sets that tile's `img.src =
  /preview/feed/<X>?ts=…` and shows a spinner/disabled state until it loads.
- The on-air feed tile is highlighted; the panel derives the on-air feed from
  the `/status` `feeds` block it already polls (lower stint index = on air,
  mirroring the relay's `live_feed()`) — **no new data endpoint**.
- Hiding the section clears the program interval → no further requests.

No changes to the OBS scene collection, profiles, or config. `ffmpeg` is already
a hard runtime dependency.

## Data flow

**Program tile (auto, ~1.5 s, only while shown):**
```
panel <img src="/preview/program?ts=…">   (interval reassigns ts)
  → relay GET /preview/program
      → obs_ws.get_program_screenshot(width=640)
          → GetCurrentProgramScene → GetSourceScreenshot
      ← JPEG bytes → 200 image/jpeg (Cache-Control: no-store)
```
The browser drives the polling; the relay stays stateless. Section hidden →
interval cleared → **zero traffic**.

**Feed tile (on click only):**
```
director clicks ↻ on Feed B → panel sets img.src=/preview/feed/B?ts=…
  → relay GET /preview/feed/B
      → preview_source("B", live=live_feed(), pov_active, feed_ports)
          ├─ "obs"  (B on-air)  → get_source_screenshot("Feed B", width=480)
          ├─ "grab" (B off-air) → ffmpeg -i http://127.0.0.1:53002 -frames:v 1 (≤8 s)
          └─ "placeholder"      → 503 + note
      ← JPEG bytes → 200 image/jpeg
  → panel swaps the <img>, re-enables ↻
```
Each request is independent and short-lived; grabs fire only on a click or the
program poll, never in the background.

## Error handling

All best-effort; each failure yields a graceful tile, never an exception:

| Condition | Relay | Panel shows |
|---|---|---|
| OBS not running / wrong WS password | `get_source_screenshot` → `(None, note)` → **503** + note | "OBS nicht erreichbar" |
| Off-air grab times out / streamlink idle / feed off | ffmpeg non-zero or >8 s → killed → **503** + note | "Feed nicht verfügbar" |
| POV paused (default) | router → `("placeholder","pov off")` → **503** | "POV aus" |
| `ffmpeg` missing on PATH | caught → **503** + note | "ffmpeg fehlt" |
| Grab collides with OBS at handover | short timeout; one failed grab | momentary "nicht verfügbar", retry |

Guarantees:
- **No background work** — grabs only on click; program poll only while visible;
  hidden = no obs-websocket calls, no ffmpeg, no traffic.
- **No mutation** — `GetSourceScreenshot` is read-only; the port grab is a
  transient consumer that disconnects immediately; nothing touches scene state,
  the on-air cut, or feed config.
- **Hard timeout** on the grab subprocess (killed on timeout) so a stuck
  upstream can't hang a relay worker thread.
- **`Cache-Control: no-store`** on every preview response.

## Testing (TDD, stdlib only)

Pure logic first, then wiring — mirroring `streamlink_serve_cmd` /
`feed_state_intents` coverage.

- **`tests/test_obsws.py`** — `parse_screenshot_data_uri` (valid → bytes;
  garbage/missing comma → `None`); `get_source_screenshot` against a mock
  `_Session` (asserts the `GetSourceScreenshot` request shape and the data-URI
  decode; OBS unreachable → `(None, note)`).
- **`tests/test_pov.py`** (relay) — `preview_source(...)` routing table (on-air →
  `("obs", "Feed A/B")`; off-air → `("grab", port)`; POV active →
  `("obs","Feed POV")`; POV paused / feed off → `("placeholder", …)`); plus
  `feed_grab_cmd(port, width)` pinned byte-for-byte.
- **Relay endpoint tests** — `/preview/program` and `/preview/feed/<X>` via the
  existing relay test harness with a stubbed obs-websocket + stubbed grab:
  success → `image/jpeg`; each error path → `503` + note; confirm the router
  calls only the chosen mechanism (no obs call on a grab path and vice-versa).
- **Gates:** `python3 tools/run-tests.py`, `python3 tools/lint.py`,
  `python3 tools/build.py` (exit 0), and `python3 tests/test_pov.py`.
- **Wiki:** refresh `src/docs/wiki/images/director-panel.png` with the Live
  Preview section expanded, in the same change (hard rule), captured by driving a
  running panel with Playwright.

## Out of scope

- Control Center surface (panel-only by decision; the producer sits at OBS).
- Live video / virtual-camera streaming (obs-websocket offers no video stream;
  polled screenshots are the stdlib-only mechanism).
- Auto-refreshing feed tiles (click-only by decision, to bound upstream traffic).
- Audio monitoring.
