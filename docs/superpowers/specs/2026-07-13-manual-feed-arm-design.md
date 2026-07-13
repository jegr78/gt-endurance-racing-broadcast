# Two-stage feed scheduling — manual feed arm/disarm (#492)

**Date:** 2026-07-13
**Issue:** [#492](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/492)
**Scope:** `src/relay/racecast-feeds.py` (flag + arm/disarm + desync suppression + `/status`),
`src/scripts/console_policy.py` (endpoint gating), `src/director/director-panel.html`
(per-feed toggle), `src/companion/…` (buttons via `racecast export companion`). Single PR
into `main`.

## Problem

Today a stint URL entered in the schedule (sheet or Director Panel) pulls **immediately**
— streamlink connects and hits the platform. There is no way to enter a URL early without
pulling, and stopping a feed's pull after a handover requires the manual workaround of
deleting the previous stint's URL from the schedule. This wants a first-class two-stage
control: enter URLs any time, but **arm** a feed before its pull runs, and **disarm** a
feed to stop its pull promptly (freeing the port/bandwidth). It is a structural mitigation
for the same-URL double-pull (#491) and the 2-feed 429 (#489): with manual arm, a second
feed never pulls unless explicitly activated, and the operator bounds the overlap window.

## The mechanism already exists (POV)

The pull is gated on a per-feed `paused` flag, proven by the POV feed:
- `Feed.current_channel()` returns `(None, idx)` when `self.paused` → the run loop idles,
  **no pull**, even with a URL at the feed's index.
- `Relay.pov_reload()` sets `paused=False` + `reload()` = **activate**.
- `Relay.pov_stop()` sets `paused=True` + `reload()` (wake + kill proc → port closes) =
  **deactivate**.
- Health already maps `paused → "stopped"` (distinct from `dropped → "down"`), so a
  disarmed feed raises no alarm.

So there is **no new pull machinery** — this extends the POV pause pattern to Feed A/B.

## Design

### 1. Opt-in flag `RACECAST_MANUAL_FEED_ARM` (default OFF — today unchanged)

A pure `manual_feed_arm_enabled(environ)` reading `RACECAST_MANUAL_FEED_ARM`, mirroring the
`fanout_enabled` convention **inverted**: default OFF; enabled only on an explicit truthy
token (`1/true/yes/on`). When enabled, `Relay.__init__` starts **both Feed A and Feed B
`paused=True`** (disarmed). The `paused` gate in `current_channel()` then suppresses every
pull, including the ping-pong pre-warm: even though `next_auto` still advances a feed's
index, a paused feed does not pull. With the flag off, behaviour is **100% unchanged**
(auto-pull, auto-pre-warm, seamless `/next`).

### 2. Arm/disarm actions (mirror POV 1:1)

```python
Relay.feed_activate(which)    # feeds[which].paused = False; feeds[which].reload() -> pulls at current idx
Relay.feed_deactivate(which)  # feeds[which].paused = True;  feeds[which].reload() -> kill proc, close port
```

Both are **manual-mode-only**. In auto mode they return
`{"error": "manual feed arm disabled (set RACECAST_MANUAL_FEED_ARM=1)"}` and mutate
nothing — a clean separation so the auto pre-warm/handover logic and manual arm never
fight. `which` is validated (`A`/`B`); the POV feed keeps its own `/pov/*` controls.

### 3. `/next` + OBS cut in manual mode — no special-casing needed

`next_auto`/`set_stint` already gate the OBS cut on `cut = (feed.phase == "serving")`, so
`/next` **never cuts onto a disarmed (non-serving) feed** — it shows the current feed until
the incoming one is armed. `/next` still does its index/label/on-air-designation
bookkeeping; whether video appears is governed by arm state. The intended operator
workflow: **arm the incoming feed (warm it) → cut (`/next` or OBS) → disarm the outgoing
feed** — a short, controlled overlap instead of an open-ended double pull.

**Cold-start trade-off (documented):** a disarmed feed is not pre-warmed, so arming incurs
a cold start (yt-dlp resolve + streamlink connect, a few seconds). Mitigation is the whole
point: arm a short time before the handover.

### 4. Interaction with #494 desync detection

In manual mode an intentionally-disarmed on-air-index feed while the other serves is a
**normal** transitional state (arm-before-cut), but it would false-positive
`ping_pong_desynced`. So **`_compute_desync` returns inactive whenever manual mode is on**
— the desync banner is an auto-ping-pong tool; manual mode is operator-driven and shows
per-feed arm state directly. (`live_feed()` and the recovery `resync_to_stint` are
unaffected and remain available.)

### 5. Endpoints + policy

GET `/feed/<A|B>/activate` and `/feed/<A|B>/deactivate` (GET, matching `/pov/reload`,
`/pov/stop` — Companion's Generic-HTTP module uses GET). `console_policy.min_capability`
maps `["feed", "A"|"B", "activate"|"deactivate"]` → `Requirement(DIRECTOR, False)`, so the
controls work over Funnel under `/console` like the other feed/panel controls. No new
public surface (only `/console` is funnelled).

### 6. `/status` surface + Director Panel + Companion

`/status` gains a top-level `manual_feed_arm: bool` and a per-feed `armed: bool`
(`not paused`) inside each `feeds[A|B]` block. The Director Panel shows a per-feed **ARM /
STOP PULL** toggle with a clear armed/idle indicator, rendered **only when
`manual_feed_arm` is true** — so the default (auto-mode) panel is visually unchanged.
Companion gains arm/disarm buttons in the exported config.

**Wiki-screenshot judgment:** the toggle appears only in manual mode; the panel's DEFAULT
(auto-mode) documented appearance is unchanged, so `director-panel.png` is not stale
(same judgment as #494's conditional banner). The manual-mode surface is verified
per-surface (headless render + eyeball, recorded in `runtime/ui-visual-verified.json`).

### 7. Tests

- Pure `manual_feed_arm_enabled(environ)`: default off, truthy tokens on, falsey/absent off.
- `feed_activate`/`feed_deactivate` (mirror the POV pause tests): a URL present at the
  index but `paused` → no pull (`current_channel()` returns `(None, idx)`); activate →
  unpaused + reload; deactivate → paused + reload; a deactivated feed reports `stopped`,
  not `down` (no health alarm).
- Manual mode init: both feeds start `paused=True`; auto mode: both start `paused=False`.
- Auto-mode `feed_activate`/`feed_deactivate` return the disabled error and mutate nothing.
- `_compute_desync` returns inactive in manual mode.
- `console_policy` maps the two feed routes to `Requirement(DIRECTOR, False)`.

## Explicitly out of scope

- The optional per-stint **"Active" column** in the Schedule sheet (a declarative per-row
  arm flag) — more sheet + Apps Script coordination; a follow-up if per-feed control proves
  insufficient.
- Any change to auto mode's pre-warm/handover — auto mode is untouched by default.
- The POV feed's own controls (already `/pov/*`).

## Acceptance criteria (from #492)

- [ ] A stint URL can be entered with **no pull** until the feed is activated (manual mode).
- [ ] Activate starts the pull; deactivate stops it promptly and frees the port (like
      `/pov/stop`).
- [ ] A deactivated feed reports `stopped` (not `down`) and raises no health alarm.
- [ ] Panel + Companion expose per-feed arm/disarm with clear state; endpoints
      director-gated and Funnel-safe.
- [ ] Behaviour is opt-in — existing auto-pull deployments are unchanged with the flag off.
- [ ] Unit tests for activate/deactivate incl. the "URL present but paused → no pull" path.
