# Relay-Hosted Race Timer — Design

**Date:** 2026-06-06
**Status:** Approved (design), ready for implementation planning
**Scope:** Replace the stagetimer.io browser source with a relay-hosted race
countdown that the Director controls remotely (start, stop, show/hide, set
duration, correct) and that survives both relay/OBS restarts and a mid-race
producer-machine handover. Zero running cost.

---

## 1. Goal

The broadcast shows the remaining race time as the `HUD Race Timer` browser
source. Today that source points at a signed stagetimer.io output URL
(`__IRO_TIMER__` / `IRO_TIMER_URL`), and only someone with stagetimer access
can start the timer or toggle its visibility. stagetimer's HTTP API requires a
paid license ("The API is accessible with any paid license" —
stagetimer.io/docs/api-v1/), so Director control via stagetimer is ruled out
on the free tier.

Replace it with a timer hosted by the relay itself:

- Director controls it from the existing surfaces — the `/panel` page (tablet
  over the tailnet) and new Companion buttons (Generic-HTTP, port 8088).
- The countdown state survives a relay restart on the same machine **and** a
  takeover by a different producer machine mid-race.
- stagetimer, the signed URL secret, and the free-tier device limit all go
  away. No new runtime dependency (stdlib + a one-time Google Apps Script
  deployment).

## 2. Decisions (locked during brainstorming)

| Topic | Decision |
|---|---|
| stagetimer | **Fully replaced** — no stagetimer account needed at all |
| Central state | **Sheet tab + Apps Script webhook** — read via gviz CSV (like Schedule/Overlay), written via a Google Apps Script web app |
| Local persistence | `runtime/timer.json` — restarts on the same machine never need the Sheet |
| Conflict rule | **Newest write wins** — both Sheet and local state carry an `Updated (UTC)` stamp |
| Ticking | **Client-side only** — the browser source computes `end − now` locally; the Sheet stores only the anchor, never a ticking value |
| Pre-start display | Static full configured duration (e.g. `6:00:00`) |
| At zero | Display goes **blank** (matches today's behaviour) — no `0:00:00` left standing |
| Visibility | Server-side flag — `/timer` renders blank when hidden, so hide/show acts on every producer machine at once |
| Look | Match the current stagetimer overlay: large monospace digits, transparent background, same on-canvas position/size |
| Control surfaces | **Both** `/panel` (new Timer section) and Companion (new buttons in `iro export companion`) |
| Director ops | start, stop, show, hide, set duration, adjust (± seconds) |
| Cost | 0 — Apps Script free quotas are far above one-event usage |

## 3. State model

The entire timer is three values plus a write stamp, stored in a new
key/value Sheet tab **`Timer`** (column A = key, column B = value):

| Key | Example | Meaning |
|---|---|---|
| `Race End (UTC)` | `2026-06-13T20:00:00Z` | Absolute anchor. Empty = not started. |
| `Duration` | `6:00:00` | Configured race length. Shown statically pre-start; basis for `end = now + duration` on start. |
| `Visible` | `TRUE` / `FALSE` | Director's manual show/hide. |
| `Updated (UTC)` | `2026-06-13T13:59:58Z` | Written by Apps Script on every write; drives the newest-wins merge. |

Derived display states (pure function, unit-tested):

| Condition | Display |
|---|---|
| `Visible = FALSE` | blank |
| No anchor (not started) | static `Duration` |
| Anchor in the future | ticking countdown `end − now` |
| Anchor reached/past | blank |

Clock assumption: producer machines are NTP-synced (macOS/Windows default).
Two machines rendering against the same absolute anchor show the same time.

### Read path
The relay polls the `Timer` tab as CSV
(`…/gviz/tq?tqx=out:csv&sheet=Timer`) with a short TTL cache (~5 s), same
pattern as the Schedule/Overlay/POV tabs. Polling latency only affects how
fast show/hide and corrections propagate — the tick itself is local and
smooth.

### Write path
A Google Apps Script **web app** bound to the Sheet exposes `doPost`: it
validates a shared secret, writes the posted keys into the `Timer` tab, and
stamps `Updated (UTC)`. Deployed once by the sheet owner ("execute as me",
"anyone with the link"); the copy-paste script and deployment steps ship in
the docs/wiki.

- `.env`: one new **optional** variable `IRO_TIMER_PUSH_URL` — the Apps
  Script `/exec` URL including its `key=<shared secret>` query parameter
  (single-var pattern, like the old `IRO_TIMER_URL`).
- Every Director action applies **immediately** to local state
  (`runtime/timer.json`, with its own `Updated` stamp) and is then pushed to
  the webhook in the background.
- Push failure (or unset `IRO_TIMER_PUSH_URL`) degrades, never breaks: the
  timer keeps working machine-locally and `/timer/data` + `/panel` surface a
  `sheet sync: failed/disabled` notice so the Director knows handover safety
  is not guaranteed right now.

### Merge rule
On every poll the relay compares `Updated (UTC)` stamps and adopts whichever
state — Sheet or local — is newer. This makes a takeover trivial (the new
machine's relay adopts the Sheet anchor on first poll) without letting a
stale Sheet revert a fresh local action whose push failed.

## 4. Display page (`/timer`)

New relay-served page (same pattern as `/hud`): static HTML + JS, served by
the existing control server, polling `/timer/data` (~2 s) and ticking
locally between polls.

- Large monospace digits, `H:MM:SS`, transparent background — matches the
  current stagetimer look in the broadcast.
- Implements the display-state table above; blank means fully transparent.
- The OBS `HUD Race Timer` browser source URL changes to the **fixed**
  `http://127.0.0.1:8088/timer` — loopback, no token, no secret. The
  `__IRO_TIMER__` token and `IRO_TIMER_URL` are removed everywhere
  (collection, `setup-assets.py`, `.env.example`, init wizard, docs).
- Scene items in `src/obs/IRO_Endurance.json` are updated (crop/scale) so the
  on-canvas position and size of the digits stay exactly as today.

## 5. Control endpoints

Added to the existing unauthenticated control server (port 8088, GET-only,
Companion Generic-HTTP compatible — same trust boundary as `/next` etc.: the
tailnet):

| Endpoint | Action |
|---|---|
| `/timer/start` | `end = now + duration`. Does **not** touch visibility — start and show/hide are orthogonal controls. |
| `/timer/stop` | Clears the anchor → back to "not started" (static duration). |
| `/timer/show` / `/timer/hide` | Sets `Visible`. |
| `/timer/set/<H:MM:SS>` | Sets `Duration`. Never re-anchors a running timer — mid-race it only changes the stored duration for the *next* start; corrections use `adjust`. |
| `/timer/adjust/<±seconds>` | Shifts a running anchor by ± seconds (e.g. `/timer/adjust/-60`). No-op with an error note when not running. |
| `/timer/data` | JSON: state, anchor, duration, visible, server time, sheet-sync status. Consumed by the page and the panel. |

`relay.status()` (`/status`, `iro status`) gains a compact timer summary.

## 6. Control surfaces

- **`/panel`** (`src/director/director-panel.html`): new Timer section —
  remaining-time readout, Start/Stop, Show/Hide, duration input, ±1 min /
  ±10 s correction buttons, sheet-sync indicator.
- **Companion** (`iro export companion`): new buttons calling the endpoints —
  Start, Stop, Show/Hide toggle, +1 min, −1 min. Wiki screenshots regenerated
  (companion-screenshots skill) during implementation.

## 7. Error handling

| Failure | Behaviour |
|---|---|
| Webhook down / `IRO_TIMER_PUSH_URL` unset | Local-only mode; visible sync notice on panel + `/timer/data`; everything else keeps working. |
| Sheet unreachable (read) | Relay keeps last known/local state; notice in `/timer/data`. |
| Malformed tab values | Treated as absent (not started / visible TRUE default); parse never throws. |
| Bad endpoint args (`/timer/set/abc`) | 4xx JSON error, state untouched. |
| Clock skew between machines | Out of scope to fix; documented assumption (NTP on). Anchor math keeps both machines self-consistent. |

## 8. Testing

`tests/test_timer.py` (stdlib, runnable script, like the others) covering the
pure logic: tab CSV parsing, display-state derivation (pre-start / running /
zero / hidden), duration parsing (`H:MM:SS`), anchor math incl. `adjust`,
newest-wins merge, endpoint routing (mirroring `test_pov.py` style). The
webhook push is isolated behind a small function and tested with a stub.
Manual verification: OBS browser source against a running relay; panel and
Companion buttons over the tailnet; simulated handover (second relay instance
reading the same Sheet).

## 9. Out of scope

- Pause/red-flag handling (stop+restart or `adjust` cover rare cases).
- Authenticating the control endpoints (unchanged trust model: the tailnet).
- Count-up / lap timing / multiple timers.
- Replacing stagetimer for any non-broadcast use the team may have.

## 10. Cleanup checklist (ships with the change)

- Remove `IRO_TIMER_URL` from `.env.example`, `setup-assets.py` injection,
  `iro init` gate (replaced by optional `IRO_TIMER_PUSH_URL`).
- Remove `__IRO_TIMER__` from the OBS collection + `tools/tokenize-obs.py`.
- Update `tools/build.py` verify step (tokenization check no longer expects
  `__IRO_TIMER__`).
- Docs/wiki: Director timer how-to + Apps Script setup page; purge stagetimer
  references from operator docs and cheat sheets.
