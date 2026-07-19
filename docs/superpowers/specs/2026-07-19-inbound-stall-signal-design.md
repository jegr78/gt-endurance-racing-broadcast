# Inbound feed-stall signal — design

**Issue:** #535. Builds on the feed fan-out prebuffer (#533, merged).

**Status:** design approved (brainstorming), pending spec review.

**Source:** Suzuka 8h analysis (2026-07-18). The event had ~28+ visible feed
stutters and needed 3 manual "OBS Feed Reset" presses, yet the health monitor
rated **959 of 959 on-air samples green** and the report showed **0 incidents**.

## Problem

Every current detector is either OBS-side or drop-based, so **inbound source
jitter is invisible**:
- The `#488` cursor-progress **freeze detector** measures OBS's *playback* cursor;
  it fires (and auto-rebuilds) only when OBS runs dry.
- `feed_stalled` is the **8 s** byte-stall watchdog — far above the 0.1–2.2 s gaps.
- `feed_health_state` needs a served-then-lost drop; bursty bytes never qualify.
- `obs_render_skip_rate` is decoupled (peaked on Suzuka's *cleanest* stint).

With #533's prebuffer now absorbing sub-N inbound gaps, the meaningful signal is:
**did an inbound gap approach/exceed the reserve?** That is a *source-side*
inter-arrival measurement nothing currently records, so a stuttery (or
nearly-stuttery) event still reads all-green.

## Scope (decided in brainstorming)

- **Detection + visibility only.** Add the inbound-gap signal → a **soft yellow**
  health (visible in `/status`, the monitor, and counted in the report) that
  sends **no Discord `@here`**. Red/`@here` stays reserved for genuine feed loss.
- **No new auto-recovery.** The existing cursor-progress **freeze detector**
  already rebuilds the on-air feed's OBS input when the reserve is exhausted (OBS
  cursor stalls), and the #495 auto-cover raises Standby on a source-offline feed.
  Adding a second rebuild trigger keyed on the inbound gap would be redundant and
  can rebuild OBS onto a still-starved ring. This is documented, not re-built.

## Components

### 1. Per-feed inbound max-gap (relay)

The feed's ring-write loop already stamps `self.last_byte_ts` on every byte. Add a
per-feed `self._max_inbound_gap` (seconds). On each write, before updating
`last_byte_ts`, while the feed is **serving** (`phase == "serving"`, not paused):
`gap = now - last_byte_ts; self._max_inbound_gap = max(self._max_inbound_gap, gap)`
(guarded on `last_byte_ts is not None`). A method `take_max_inbound_gap()` returns
the value and **resets it to 0** — the heartbeat reads it once per interval, so a
transient 2 s stall that recovered between the 30 s heartbeats is still captured
as that interval's peak (a point-sample of the current gap would miss it).

### 2. Pure decision

`feed_inbound_degraded(max_gap_s, prebuffer_s, floor_s=FEED_STALL_FLOOR_S)` →
`bool`: `max_gap_s > max(prebuffer_s, floor_s)`. A gap must exceed **both** the
reserve (`prebuffer_s`, so a gap the prebuffer absorbed is not flagged) and a
small floor (`FEED_STALL_FLOOR_S`, default ~1.0 s, so `prebuffer=0` still needs a
real gap). Pure, unit-tested.

### 3. Soft (quiet) yellow — display vs notify split

`aggregate_health` gains a `feeds_jittery` fact (list of feed names whose interval
max-gap tripped `feed_inbound_degraded`) → a yellow reason
`"Feed X inbound stall (gap N.N s exceeded the N.N s reserve)"`. This is the
**display** health (pill, `/status`, report reasons).

To keep it quiet, the heartbeat computes the **notify** level from the same facts
**with `feeds_jittery` emptied**:
`notify_level = aggregate_health({**facts, "feeds_jittery": []}).level`, and pages
via the existing `health_should_notify(self._notified_level, notify_level)`. So an
inbound-jitter-only yellow never changes the notify level → **no `@here`**; a
jitter yellow that coincides with a real yellow (cookies, funnel, …) still pages
on the real reason; red is unaffected. `health_should_notify` and
`discord_health_payload` are unchanged.

### 4. Observability

- **DB:** add `feed_a_max_gap_s`, `feed_b_max_gap_s` REAL columns to
  `health_store` (`NUMERIC_FIELDS` + the schema + the additive-migration list —
  health_store already migrates by `ALTER TABLE ADD COLUMN`). Sampled each
  heartbeat from `take_max_inbound_gap()`.
- **Health monitor** (`src/console/health-monitor.html`): add the two series to
  the hardcoded metric list (like the `sys_*` charts), group "Feed stalls". A
  rendered surface → ui-visual-verification (+ refresh `health-monitor.png` if the
  chart grid visibly changes).
- **Report** (`report_build.py`): a **"Max inbound gap (s)"** peak row in the
  "Stream & OBS quality" section (peak = the worst gap; avg is meaningless for a
  max-per-interval series) — the row that makes a stuttery session no longer read
  clean.

### 5. Config

- `RACECAST_FEED_STALL_FLOOR_S` (default ~1.0) — the floor in `feed_inbound_degraded`.
- Kill-switch `RACECAST_FEED_STALL_SIGNAL` (default on) — when off, the gap is still
  sampled to the DB (free observability) but never contributes the yellow reason.
- Threshold otherwise tracks `feed_prebuffer_s` (#533) dynamically.

## Interactions

- **Freeze detector / #495 auto-cover:** unchanged; they remain the auto-recovery
  (§Scope). The new signal is orthogonal (source-side vs OBS-side).
- **`drop_connecting_notifiable` / existing yellows:** untouched; they still page
  as before via the notify level.
- **Prebuffer off (`RACECAST_FEED_PREBUFFER_S=0`):** the floor governs; a real gap
  still surfaces.

## Testing

- Pure `feed_inbound_degraded`: gap ≤ reserve → False; gap > reserve but ≤ floor →
  False; gap > both → True; `prebuffer=0` uses the floor.
- Max-gap accumulator: records the largest inter-arrival, resets on read, ignores
  non-serving intervals (a pure helper over (writes, now) so no real stream).
- Quiet yellow: `aggregate_health` with `feeds_jittery` → yellow + reason; the
  notify level with `feeds_jittery` emptied stays green → no page; jitter + a real
  yellow → notify yellow → pages.
- DB round-trip of the new columns (test_health_store); report peak row
  (test_report_build).

## Out of scope

Auto-resync on inbound stall (§Scope — existing freeze detector owns it); the
other Suzuka findings (#537 obs-ws churn, #538 pre-event docs).
