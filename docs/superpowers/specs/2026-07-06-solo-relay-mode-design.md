# Solo relay mode — feed-less, sheet-driven single-event broadcasts

Epic: #300 (Solo mode). Primary issue: #302. This spec is the shared foundation
for the relay-facing solo work and re-scopes several sub-issues (#301, #302,
#305, #306). It supersedes the "sheet-less" framing in the original epic body.

## Context

The endurance toolkit pulls one external commentator stream per stint and
"ping-pongs" two feeds (A/B on ports 53001/53002) into OBS, driven by a Google
Sheet. Solo mode reuses the same reusable core — Director Panel, relay-mediated
OBS control, timer, multi-profile, HUD — for a **single-event** broadcast where
the main program is a **local capture card + webcam in OBS**, not pulled external
feeds. Two starter templates: `commentary` (solo commentator of one race) and
`pov` (a driver's POV stream).

## The key reframe: schedule vs. sheet are orthogonal

The original epic conflated two independent things into "no feeds and no Sheet":

1. **No stint schedule / no A/B feed ping-pong** — this is the *essence* of solo.
   The main program is local OBS capture; there are no schedule-driven external
   stint feeds.
2. **No Google Sheet** — a *separate* decision about the config source.

Walking the sheet-derived sources shows only the `Schedule` (and `Qualifying`)
tab is endurance-exclusive — those drive the A/B feeds. Everything else is useful
in **both** modes: `HudSource` (Overlay/Configuration), `Channel` → broadcast
chat, `Crew` → console roles, `Producer` → parts, `Timer`, `Event Notes`,
`Assets`.

### Decision: sheet-always

Solo **always uses a Sheet** (the mechanism is proven and well-understood). For
solo we simply **strip the tabs we definitely do not need** — `Schedule` and
`Qualifying` — and keep everything else sheet-driven, unchanged. Therefore:

> **Solo = "endurance minus the A/B-feed schedule", plus an optional POV feed.**

`kind` gates only: whether the A/B-feed schedule exists, the OBS scene-collection
template (#303/#304), the Director-Panel/Control-Center UI (#307), and the
product name (#308). The relay divergence is small and additive; the endurance
path stays byte-identical.

## What solo does NOT change (maximum reuse, sheet-driven as today)

`HudSource` (Overlay/Configuration tabs → `/hud` + `/hud/data`), the panel
`Setup` controls (async-optimistic write-back via `RACECAST_SHEET_PUSH_URL`),
`Channel` → `BroadcastChatSupervisor`, `Crew` → `CrewSource` + console roles,
`Producer` → parts, `Timer` (`TimerStore`, sheet-synced), `Event Notes`,
`Assets` (`get-graphics`/`get-media`), `/panel`, `/obs/*`, `/preview/program`,
chat, cues, console/cockpit, submissions, health monitor. **The POV feed too** —
see below.

## What solo strips

- The `Schedule` (race) `ScheduleSource` and the A/B `Feed`s.
- The `Qualifying` `ScheduleSource` (no stint schedule to qualify).

That is the entire relay-level divergence.

## Design

### A. Solo detection & CLI wiring

- New relay flag `--solo` in `src/relay/racecast-feeds.py` (argparse), default
  off. `src/racecast.py` passes `--solo` to the relay child when the resolved
  `ResolvedConfig.kind == "solo"`.
- `SHEET_ID` is **present** in a solo profile (sheet-always), so the existing
  no-Sheet hard-exit is unchanged and simply passes.

### B. `Relay` solo construction (feed-less A/B, optional POV — unchanged)

A solo branch in `Relay.__init__`:

- `self.race_source = self.qual_source = None`; `self.feeds = {}` (no A/B, so no
  `slot_start_indices`); `self.solo = True`.
- **POV is unchanged.** It is already an independent third feed
  (`self.pov`, built from `pov_source` + `pov_port`, paused at start). Solo keeps
  it exactly as-is.
- `start()` needs no solo-specific change: `for f in self.feeds.values()` is a
  no-op over `{}`; the POV thread, its fan-out, and the heartbeat start normally.
  (`_health_facts`/`start` already compute `live = list(self.feeds.items()) +
  ([("POV", self.pov)] if self.pov else [])`, which degrades cleanly to just POV
  or nothing.)

Feed-touching methods get an explicit solo guard so they never assume `A`/`B`:

- `status()` returns a **solo-shaped** payload: `mode: "solo"`, POV state, timer,
  health, HUD — no A/B block. This is the one method the solo panel/console read.
- `live_feed()`, `_reflect()`, `handover`/`next`, `set_index`/`set_stint`,
  `reload(A/B)` return a defined "not applicable in solo" result instead of
  indexing `self.A`/`self.B`.

### C. `main()` startup branch (the small delta)

In solo (`args.solo`):

- **Skip** building `source = ScheduleSource(...)`, the `Qualifying` source, and
  the A/B `Feed`s; construct the `Relay` via the solo branch (no `source`, no
  `ports`).
- **Keep, sheet-driven exactly as endurance:** `HudSource`, `Channel` +
  `BroadcastChatSupervisor`, `CrewSource`, `ProducerSource`/parts, `TimerStore`,
  `EventNotesSource`, and the POV `pov_source` (from the Sheet `POV` tab).
- The **no-Sheet hard-exit stays** (solo has a Sheet).
- yt-dlp/streamlink: the startup **hard-exit is skipped in solo** (no A/B feeds).
  Tools are needed only by the optional POV feed; if absent, the POV feed logs
  and idles (the existing feed run-loop behavior — "streamlink not found on PATH
  — retrying"), non-fatal. Everything else runs.
- `_release_obs_feeds()` on stop is skipped in solo (no A/B feed media sources to
  rebuild; POV is handled as today).

### D. Solo POV (reuses the existing sheet-driven mechanism — no new store)

Because the Sheet is always present, solo POV reuses the **existing** POV path
unchanged: `pov_source` is built from `sheet_id` + the `POV` tab; the panel POV
control (`/pov/set`, POST) writes the URL back to the Sheet via the webhook
(ad-hoc, exactly the "set a POV per panel" use case); `/pov/reload` re-points the
POV feed. No `SoloPovStore`, no local POV file — one code path for both modes.

### E. Endpoint behavior

- **Kept, feed-independent (work in solo):** `/panel`, `/timer/*`, `/obs/*`,
  `/preview/program`, `/hud` + `/hud/data` (sheet-driven), `/pov/*`, `/setup/*`,
  chat/cues/console/crew/broadcast-chat, submissions, health monitor.
- **Guarded (never crash; return "not available in solo"):** `/next`, `/reload`,
  `/set/*`, `/schedule/*`, and the qualifying/mode endpoints.

### F. Testing (purely additive — nothing disabled)

Hard constraint: the endurance path stays byte-identical; **no existing test is
commented out or disabled**. `python3 tools/run-tests.py` must stay green with
zero deactivations.

New solo coverage:

- A relay-startup test: solo comes up **with** a Sheet but **without** a
  `Schedule` tab / A/B feeds and **without** yt-dlp/streamlink on PATH; `/status`
  reports `mode: "solo"`; `/panel`, `/obs/*`, `/timer/*`, and `/hud/data`
  respond; **no A/B feed ports are bound**; POV idles when its tab is empty.
- Unit tests for the solo guards on the feed-touching `Relay` methods
  (`status`/`live_feed`/`next`/`reload`/`set_stint`) — pure, no live relay.

The synthetic e2e harness (`tools/e2e.py`) gains a solo variant later if needed;
not required for #302.

### G. Sub-issue re-scope (consequence of sheet-always)

- **#301** (already merged) — the generated solo `profile.env` must **keep
  `SHEET_ID`** (and the relevant keys) rather than being sheet-less. Corrected as
  part of #302 (the solo relay needs the Sheet to be useful).
- **#302** — scope is exactly the relay delta above (strip Schedule/Qualifying +
  A/B; keep the rest sheet-driven; optional POV; conditional/soft tool check).
  Issue body updated.
- **#305** ("Panel-driven, sheet-less HUD / `SoloHudStore`") — **collapses.** The
  HUD is the existing `HudSource` + the panel `Setup` controls writing to the
  Sheet; solo only drops the schedule coupling (which falls away naturally). No
  new store. Issue closed as subsumed, or re-purposed to "panel Setup works
  without a schedule."
- **#306** ("asset management without a Sheet") — **trivial.** Solo uses the
  `Assets` tab like endurance (`get-graphics`/`get-media`). Reduced to docs/
  template if anything.
- **New:** a **solo Sheet layout** — the same Sheet template as endurance minus
  the `Schedule`/`Qualifying` tabs — documented in the wiki "Sheet-Template"
  page.

## Non-goals / boundaries (other sub-issues)

- OBS solo scene-collection templates (local capture + webcam) + device tokens —
  **#303**.
- Device enumeration (OBS-WS) → `.env` → token injection — **#304**.
- Kind-conditional UI (hide schedule/stint controls; show HUD-setup + POV in the
  Director Panel; Control Center kind affordances) — **#307**.
- Rebrand to "GT Racing Broadcast" — **#308**.
- GT7 UDP telemetry-driven POV HUD — **#324**.

## Success criteria (this spec / #302)

`racecast --profile <solo> relay run` starts on a machine with **no
yt-dlp/streamlink**, reading the solo profile's Sheet (no `Schedule` tab):
`/status` (mode solo), `/panel`, `/timer/data`, `/hud/data`, and `/obs/state`
respond; **no A/B feed ports are bound**; setting a POV via the panel and
reloading brings up the single POV feed; the full existing test suite stays green
with no test disabled.
