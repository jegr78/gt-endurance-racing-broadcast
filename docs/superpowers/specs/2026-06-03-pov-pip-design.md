# Driver-POV Picture-in-Picture — Design

**Date:** 2026-06-03
**Status:** Approved (design), ready for implementation planning
**Scope:** Add an ad-hoc driver-POV stream as a small picture-in-picture (PiP) in the
Stint scene, maintainable remotely by the Director.

---

## 1. Goal

Give the broadcast an optional **driver-POV PiP** in the bottom-right of the **Stint**
scene, layered over the active feed. The POV stream is ad-hoc (changes per driver/
moment), maintained remotely by the Director, and is source-agnostic (YouTube,
Twitch, …). It must never overlap the HUD and must not disturb the existing A/B
relay, schedule, or combo behaviour.

## 2. Decisions (locked during brainstorming)

| Topic | Decision |
|---|---|
| POV source | **Source-agnostic** (YouTube / Twitch / other) — handled by yt-dlp resolve |
| URL control surface | **Google-Sheet cell** — new tab `POV`, cell `A2` (A1 = header `url`) |
| Audio | **Muted by default, switchable** (Director can raise POV audio briefly) |
| Scene scope | **Stint only** |
| Size | **384×216** (1/5, 16:9) |
| Position | x=**1496**, y=**644** → box x[1496–1880], y[644–860] |
| Label | **None** (pure video) |
| Pull architecture | **Approach A** — 3rd independent relay feed on port **53003** |

## 3. Architecture (Approach A)

Reuse the proven, bot-check-safe pull pipeline (yt-dlp resolves the live manifest →
streamlink serves the direct URL; cookies + deno). The POV is a **third, independent
feed** — NOT part of the A/B ping-pong index, so schedule advancing is untouched.

```
 Sheet tab "POV" A2 (URL)
        │  (gviz CSV poll / on RELOAD)
        ▼
 iro-feeds.py ── PovSource ──► PovFeed (own thread)
        │                         │ yt-dlp resolve (720p cap, cookies)
        │                         ▼
        │                    streamlink ──► http://127.0.0.1:53003
        ▼                                          │
 /status {pov:{state,url,port}}                    ▼
 /pov/reload   /pov/stop                  OBS "Feed POV" (ffmpeg_source)
        ▲                                  Stint, 384×216 bottom-right,
        │ Companion HTTP GET               hidden + muted by default
        │                                          │
 Director (Companion Page 2):  RELOAD → SHOW/HIDE → AUDIO → STOP
                                  └─ visibility/mute via OBS-WebSocket ─┘
```

Two cleanly separated paths: **URL/pull** (Sheet → relay → port) and
**visibility/audio** (Companion → OBS). The relay only serves the image to the port;
what goes on-air is the Director's decision alone.

## 4. Component changes

### 4.1 Relay (`iro-feeds.py`)

- **`PovSource`** — small schedule-source analogue that reads the `POV` tab via gviz
  CSV (same mechanism as `ScheduleSource`), polled at the existing interval. Empty
  cell = POV off.
- **POV `Feed`** — reuse the existing `Feed` class on a dedicated port **53003**, with
  its own format cap `YTDLP_FORMAT_POV = "b[height<=720]/b"` (small PiP → 720p saves
  bandwidth/CPU/decode). Same cookies, same yt-dlp→streamlink chain. Runs in its own
  thread; resolve retries never block the A/B feeds.
- **Behaviour:** URL present → resolve + serve on 53003. URL empty or resolve fails →
  port stays closed, `/status` reports `pov:{state:"error"|"idle", …}`. A/B operation
  is never disturbed.
- **New HTTP endpoints:**
  - `GET /pov/reload` — re-read the POV cell and (re)connect the POV feed.
  - `GET /pov/stop` — tear down the POV pull, close the port (free bandwidth).
  - `GET /status` — add a `pov` block: `{url, state, error, port}` where
    `state ∈ idle | resolving | serving | error`.
- Endpoints bind on the existing control server (`--http-port`, default 8088), so the
  `--bind 0.0.0.0` option already covers remote reach.

### 4.2 OBS (scene collection)

- New source **`Feed POV`** — `ffmpeg_source`, input `http://127.0.0.1:53003`,
  added **only to the Stint scene**, **front-most**, **hidden by default**.
- **Transform:** position x=1496, y=644; size 384×216 (bounds "scale to inner"/fit so a
  non-16:9 POV letterboxes instead of cropping). Right edge x=1880 aligns with the HUD
  data block; bottom edge y=860 sits ~20 px above the HUD lower-third band (starts
  ~y880) → no HUD overlap (verified against Overlay.png frame zones).
- **Source settings:** "close file when inactive" ON (no decode while hidden),
  "restart playback when source becomes active" ON (picks up the port on SHOW),
  reconnect delay ON (survives brief drops).
- **Audio:** track active, **Mute = ON** by default (switchable from Companion).

### 4.3 Companion (`iro-buttons.companionconfig`)

Page 1 has no free row (4-row grid full). POV buttons go on **Page 2 ("COMBO"), row 2**,
columns 1–4 (a gap below the combo row), aligned under the combos. Uses the existing
OBS connection and the existing "Generic HTTP Requests" connection — no new connection.

| Pos | Button | Action | Feedback |
|---|---|---|---|
| (2,1) | **POV RELOAD ⟳** | HTTP GET `http://127.0.0.1:8088/pov/reload` | — |
| (2,2) | **POV SHOW/HIDE** | `Set Source Visibility` (Stint / Feed POV), toggle | `Source Visible` → green |
| (2,3) | **POV AUDIO** | `Toggle Source Mute` (Feed POV) | `Source Muted` → red |
| (2,4) | **POV STOP ■** | HTTP GET `http://127.0.0.1:8088/pov/stop` | — |

**Combo buttons: no change required.** `Feed POV` lives only in Stint, so switching to
Splitscreen/Interview/Standby auto-hides the PiP and auto-silences its audio (OBS only
outputs the program scene's audio). No POV audio bleeds into interviews.

### 4.4 Docs

- README: short "Driver-POV PiP" subsection (Sheet `POV` tab, the four Companion
  buttons, the two operating rules).
- Cheat sheet (Director card): one line — "POV PiP: enter URL in Sheet `POV` → RELOAD →
  SHOW; HIDE + STOP when done."

## 5. Director workflow

1. Enter the POV URL in Sheet tab `POV`, cell A2.
2. **POV RELOAD** → relay pulls the stream onto port 53003 (still hidden).
3. **POV SHOW** → PiP appears bottom-right in Stint.
4. (optional) **POV AUDIO** → raise POV sound briefly, then mute again.
5. **POV HIDE** when done → **POV STOP** frees the pull.

Two operating rules: **"RELOAD before SHOW"** and **"HIDE + STOP when done"**.

## 6. Pitfalls & error handling

1. **POV not live / wrong URL** → resolve fails; port stays closed, `/status` shows the
   error, PiP stays hidden. No black frame on-air (RELOAD before SHOW).
2. **Third parallel pull = load** → 720p cap, POV STOP releases it, source closes when
   hidden. Fine on the M3.
3. **Latency desync** POV↔main feed → independent streams, different delay; not
   frame-synced. Accepted for a goodie; no sync attempted.
4. **Bot-check / cookies** → YouTube POV uses the same `cookies.txt`; Twitch usually
   needs none. Same `get-cookies` workflow covers it.
5. **Black image on first SHOW** → "restart playback when active" + reconnect delay
   pick up the stream once the relay serves. Rule: RELOAD → wait briefly → SHOW.
6. **Director forgets STOP** → pull keeps running (hidden, harmless on-air) but wastes
   bandwidth and may show the stale driver next time. Rule: new POV = edit cell +
   RELOAD; done = HIDE + STOP.
7. **Sheet-edit race** → editing the cell takes effect only on RELOAD (running POV
   stays stable) — same safe behaviour as the schedule.
8. **Non-16:9 POV** → bounds "fit" letterboxes instead of cropping.
9. **A/B untouched** → POV is a separate feed object with its own thread; resolve
   retries don't block the ping-pong. Port 53003 must be free.

## 7. Out of scope (YAGNI)

- No label / driver name in the PiP.
- No A/V synchronisation POV↔main feed.
- No POV in Splitscreen (Stint only).
- No multiple simultaneous POVs (one slot/port; switch = cell + RELOAD).
- No Companion per-driver presets (Sheet cell stays the flexible source).
- No auto show/hide tied to handover (manual Director control).

## 8. Implementation surface (summary)

- `iro-feeds.py`: add `PovSource`, a POV `Feed`, `YTDLP_FORMAT_POV`, endpoints
  `/pov/reload` + `/pov/stop`, and the `pov` block in `/status`. Keep both the working
  copy and the package copy in sync.
- OBS collection (`IRO_Endurance.json` + packaged template): add `Feed POV` to the
  Stint scene with the transform/settings above.
- Companion config: add the four Page-2 buttons + feedbacks; keep password stripped in
  the package copy.
- Sheet: create tab `POV` (A1 `url`, A2 the URL).
- Docs: README subsection + Director cheat-sheet line.
- Rebuild `IRO_Broadcast_Package.zip`.

All changes are additive; no existing A/B / schedule / combo behaviour is modified.
