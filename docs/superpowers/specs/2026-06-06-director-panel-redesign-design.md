# Director Panel Redesign — Design

**Date:** 2026-06-06
**File touched:** `src/director/director-panel.html` (served by the relay at `/panel`)

## Problem

The director panel combines OBS control and the race timer, but its OBS actions
drifted out of sync with reality:

- The scene list misses **Intro** and **Outro**; the Companion macro buttons
  (scene + feed visibility + mutes in one press) have no panel equivalent, so the
  panel and the Stream Deck behave differently for the same job.
- The panel has **no relay feed control at all** (`/next`, `/reload`, per-feed
  reload, POV reload/stop) even though that is half of what Companion does.
- Graphics toggles miss **Standby Cover** and **Post Race Interviews**; audio
  misses the **Feed POV** input; the volume slider uses a 0–100 multiplier while
  Companion thinks in dB.
- The ad-hoc guest-URL loader and the Split L/R feed toggles are unused legacy.

## Goal

One page where a remote director finds every action the Stream Deck has, in the
same relative position, plus a live status strip — without OBS or relay ever
being a hard dependency for the other half of the page.

## Layout: "vision-mixer busses" (chosen over a left-rail variant)

Full-width horizontal rows, each labeled at the left edge like a mixer bus.
Order mirrors the Companion pages so deck and tablet share one muscle memory:

| Bus | Content |
|---|---|
| **PGM** (sticky) | STINT A · STINT B · SPLIT · INTERVIEW · STANDBY · INTRO · OUTRO |
| **FEEDS** | NEXT · RELOAD ALL · RELOAD A · RELOAD B · POV RELOAD · POV STOP · SET STINT… |
| **SCN·VIS** | Stint · Splitscreen · Interview · Standby (raw scene switch) · Feed A/B/POV visibility toggles |
| **GFX** | HUD (Stint) · HUD (Split) · Standings · Schedule · Race Results · Quali Results · Race Wx 1/2 · Quali Wx · Standby Cover · Post-Race Interviews |
| **TIMER** | START · PAUSE · RESET · SHOW · HIDE · +1m · −1m · +10s · −10s · SET DURATION… |
| **AUDIO** | one row per input: dB slider + dB readout + 0 dB reset + mute |

- The **PGM row is sticky** below the header (the one idea kept from the
  rejected left-rail layout): "what's on air" decisions never scroll away.
- Rows wrap on narrow screens; uniform key sizing keeps the grid rhythm.
- Header keeps the existing connection fields (IP / port / password,
  localStorage-persisted) and gains a **live status strip**.

## Status strip (header)

| Item | Source | Notes |
|---|---|---|
| ON AIR scene + feed | OBS (`GetCurrentProgramScene` + scene-item visibility) | red, the eye-catcher |
| Stint counter per feed (A: 3, B: 4, of N) | relay `GET /status` (`feeds.{A,B}.stint`, `schedule_len`) | works without OBS |
| POV state | relay `/status` (`pov.state`) | stopped/connecting/serving/idle |
| Timer | existing `/timer/data` poll | unchanged |
| OBS LED / Relay LED | websocket state / `/status` fetch success | two separate dots |

Polling: keep the existing 2 s cadence; one combined relay poll (`/status` +
`/timer/data`) and the existing OBS refresh.

## Action semantics

### PGM macros — exact Companion page-1 row-0 behavior

Each macro = `SetCurrentProgramScene` + `SetSceneItemEnabled` + `SetInputMute`
batch, mirroring the Companion config:

| Macro | Scene | Visibility (in Stint/Split) | Unmuted | Muted |
|---|---|---|---|---|
| STINT A | Stint | Feed A on, Feed B off | Feed A | Feed B, Discord |
| STINT B | Stint | Feed B on, Feed A off | Feed B | Feed A, Discord |
| SPLIT | Splitscreen | Feed A on, Feed B on | Feed A | Feed B, Discord |
| INTERVIEW | Interview | — | Discord | Feed A, Feed B |
| STANDBY | Standby | — | — | Feed A, Feed B, Discord |
| INTRO | Intro | — | — | Feed A, Feed B, Discord |
| OUTRO | Outro | — | — | Feed A, Feed B, Discord |

ON AIR feedback = same logic as Companion (program scene matches, and for
STINT A/B/SPLIT the feed item is visible). These macros are OBS-only; POV mute
is intentionally not part of them (matches Companion).

### FEEDS — relay HTTP (no OBS needed)

`GET /next`, `/reload`, `/reload/A`, `/reload/B`, `/pov/reload`, `/pov/stop`,
and `/set/stint/<n>` via a `prompt()` (same dependency-free pattern as the
timer's SET DURATION). Responses logged to the existing log box; buttons are
always enabled (relay reachability shows in the LED, errors land in the log).

### SCN·VIS, GFX — OBS scene-item toggles

Same `GetSceneItemId`/`SetSceneItemEnabled` toggle mechanism as today, with the
list synced to the collection:

- Visibility toggles: Feed A, Feed B, Feed POV (all in scene `Stint`).
- Graphics (scene `Stint`): `HUD` (the OBS *group*, valid as a scene item),
  Standings, Schedule, Race Results, Quali Results, Race Weather 1, Race
  Weather 2, Quali Weather, Standby Cover.
- Graphics (scene `Splitscreen`): `HUD` (the group exists in both scenes; both
  toggles stay, as today).
- Graphics (scene `Interview`): Post Race Interviews.

### TIMER — unchanged

Existing endpoints and stopwatch semantics; panel remains the superset of the
Companion timer page (±10 s and SET DURATION exist only here).

### AUDIO — dB semantics

Inputs: Feed A, Feed B, **Feed POV** (new), Discord Audio Capture.
Per row: slider −60…0 dB (writes `SetInputVolume {inputVolumeDb}`), live dB
readout, `0 dB` reset button (Companion's "VOL RESET"), mute toggle with state
polling (`GetInputMute`/`ToggleInputMute`, as today). Slider position syncs
from `GetInputVolume` on refresh so deck and panel don't fight.

### Removed

- Ad-hoc guest-feed URL loader (panel-only legacy, decided out).
- `Split L`/`Split R` toggles.
- The plain 0–100 volume multiplier model.

## Visual direction

Keep and refine the existing industrial broadcast-switcher look: dark, Saira
Condensed display + IBM Plex Mono body, amber section markers, red ON-AIR glow,
green active states. New: bus labels in the amber cap style at the left edge of
each row; uniform key sizing across busses. No new external dependencies —
still a single self-contained HTML file using the pinned obs-websocket-js CDN
build and Google Fonts (existing behavior).

## Error handling

- OBS not connected: OBS-backed keys disabled (as today); FEEDS + TIMER busses
  stay fully usable. Relay unreachable: FEEDS/TIMER actions log an error, relay
  LED goes red, OBS half keeps working.
- All OBS calls stay wrapped in the existing `safe()`/log pattern; macro
  batches log the first failing step but continue the remaining steps (a half
  high-pressure switch is better than none — same per-action independence as
  Companion's action list).
- `/set/stint` and SET DURATION validate via the relay's own 400 responses and
  surface `{"error": …}` in the log box.

## Testing

No JS test harness exists for the panel (static file, stdlib-only repo) —
manual verification stays the model:

1. `python3 src/iro.py relay start` → open `http://127.0.0.1:8088/panel`.
2. Without OBS: FEEDS + TIMER busses work, status strip shows relay/timer data,
   OBS LED red.
3. With OBS (collection imported): each PGM macro matches the corresponding
   Companion button's end state (scene, visibility, mutes); toggles and audio
   rows track state changes made from OBS/Companion within one 2 s poll.
4. `python3 tests/test_pov.py` + `python3 tools/build.py` (panel ships in the
   package; build verify must stay green).

Relay code is untouched; no new endpoints are added.
