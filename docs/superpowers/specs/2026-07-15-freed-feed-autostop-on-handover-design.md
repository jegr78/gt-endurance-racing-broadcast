# Auto-stop the freed feed on `/next` handover (+ manual-arm as default)

**Date:** 2026-07-15
**Issues:** builds on [#492](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/492)
(two-stage manual feed arm, shipped) and [#489](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/489)
(2-feed 429 throttle); empirical basis in the #505 measurement.
**Scope:** `src/relay/racecast-feeds.py` (`next_auto` + the manual-arm default), tests, a
Director-Panel copy touch. Single PR.

## Motivation

The #505 measurement proved the durable fix for the datacenter-IP YouTube 429 is to **never
run two concurrent googlevideo pulls for longer than a brief, operator-controlled overlap**.
The whole-stint ping-pong pre-roll (the off-air feed pulling the *next* stint for the entire
current stint) is exactly the sustained 2-puller that trips the throttle.

#492 already shipped the primitives to avoid it — manual arm/disarm (`feed_activate` /
`feed_deactivate`, the per-feed `paused` gate, feeds starting disarmed under
`RACECAST_MANUAL_FEED_ARM`). What is still manual is **stopping the outgoing feed after a
handover**: today the operator must press a separate `STOP` (the successor to the N24
delete-the-URL workaround). This design folds that stop into `/next`.

## The one and only operator workflow (confirmed with the operator)

There is **no fully-automatic handover** in production. Feed URLs arrive ~10 min before each
handover, are **approved**, then entered into the Sheet schedule **without activating**.
The loop per handover:

1. **~10 min out:** incoming URL approved → entered in the schedule → feed stays **disarmed**
   (URL present, no pull — the `paused` gate).
2. **Just before the handover:** operator **activates** the incoming feed → warmup (yt-dlp
   resolve + streamlink connect).
3. **`/next`:** cut to the (now warm) incoming feed → **the freed feed stops automatically.**
4. The freed feed sits **disarmed** on its next slot → the loop repeats for the next handover.

All handovers go through `/next` (Director Panel handover button / Companion). OBS is never
cut directly, so the `/next` auto-stop is always on the handover path.

## Design

### 1. Auto-stop the freed feed inside `next_auto`, gated on an actual cut

In the real-handover branch of `Relay.next_auto` (`racecast-feeds.py:6531-6549`), after the
cut is applied, deactivate the freed (outgoing) feed:

```python
# after: cut = self.feeds[new_live].phase == "serving"; if cut: self._reflect(new_live, cut=True)
self.feeds[freed].set_index(next_slot_first_row(slots, nxt))   # unchanged: re-index to next slot
if cut and self.manual_feed_arm:                               # NEW: stop the outgoing pull
    self.feeds[freed].paused = True
    self.feeds[freed].reload()                                 # wake + kill proc -> port closes
    LOG.info("handover -> freed feed %s auto-stopped (manual arm)", freed)
```

- **Gated on `cut=True`.** If `/next` is pressed *before* the incoming feed is armed/warm,
  `cut` is `False` → **no stop happens** and the current picture holds. The auto-stop can
  therefore **never black out the live program** — it only ever stops a feed we have already
  cut *away* from. This is the critical safety property.
- The freed feed keeps its existing **re-index to the next slot** (`set_index`), so after the
  stop it sits **disarmed at the row where the next incoming URL will be entered** — exactly
  the state step 4 of the workflow expects.
- The stop uses the internal primitive directly (`paused = True` + `reload()`), not
  `feed_deactivate()` (which is a manual-mode-gated HTTP helper that returns a status dict /
  error). Same effect as `feed_deactivate` / `pov_stop`: kill the streamlink process, close
  the loopback port, free the bandwidth. Health already maps `paused → "stopped"` (not
  `down`), so no alarm fires.

The **continuation** branch (same-URL back-to-back) and the **past-last-stint** over-press
branch are unchanged: a continuation performs no cut and keeps the on-air pull (nothing to
free); the auto-stop lives only where a genuine handover cut to the other feed occurs.

### 2. `RACECAST_MANUAL_FEED_ARM` becomes default ON

The workflow requires "URL entered but inactive until activated" — i.e. the manual-arm
regime. To make it the out-of-box behaviour (operator does not have to set a flag every
start), `manual_feed_arm_enabled(environ)` **defaults ON**; the flag becomes an **opt-out**
(`RACECAST_MANUAL_FEED_ARM=0` restores the legacy auto-pull + seamless whole-stint pre-roll).

**Why the auto-stop stays tied to `manual_feed_arm` rather than truly unconditional.** In the
legacy auto path (flag explicitly `0`) the freed feed *is* the pre-roll engine for the next
handover; stopping it there, with no arm step to re-warm it, would break the following
handover (the just-stopped feed is next time's incoming and would be cold → `cut=False` →
no handover). Gating the auto-stop on `manual_feed_arm` keeps that opt-out **coherent and
100% backward-compatible** instead of shipping a knowingly-broken mode. Because manual-arm
is now the default, the auto-stop is observationally **"always on" in normal use** — the gate
only spares the deliberate legacy opt-out. (This is the one refinement from the earlier
"literally ungated" wording; behaviour for the real workflow is identical.)

**Breaking-change note (released software, [[no-prod-use-prefer-clean-breaks]]).** Flipping
the default changes behaviour for any existing deployment that relied on auto-pull: a URL in
the schedule no longer pulls until the feed is activated. The migration is one of:
(a) adopt the arm-before-handover workflow (intended), or (b) set `RACECAST_MANUAL_FEED_ARM=0`
to keep the old auto-pull. This is called out in the PR, the `.env.example`, and the release
notes. The operator has approved the default flip.

### 3. Director Panel / Companion

The per-feed **ARM / STOP** controls from #492 already render when `manual_feed_arm` is true
(now the default), so they become visible by default. The manual **STOP** button stays (an
operator can still stop a feed independently), but it is no longer *required* after a
handover — `/next` does it. A short Panel hint near the arm controls documents the new
auto-stop ("`/next` stops the outgoing feed automatically"). No layout change.

**Wiki screenshot:** the arm/stop controls now show in the default panel, so
`director-panel.png` is refreshed in the same PR (CLAUDE.md hard rule) via the
`wiki-screenshots` skill; the change is verified with `ui-visual-verification` first.

## Tests (`tests/` — pure/relay unit checks, stdlib)

- **Auto-stop on cut:** manual-arm on, incoming feed armed+serving → `next_auto` cut path →
  the freed feed ends `paused=True` and `reload()` was invoked (proc killed / port closed).
- **Safety gate (no cut → no stop):** manual-arm on, incoming feed *not* serving (disarmed) →
  `next_auto` returns `cut=False`, the freed feed is **untouched** (still armed/serving), the
  live picture is preserved.
- **Freed feed disarmed at the next slot:** after the auto-stop, the freed feed's index is the
  next slot and it is `paused` (ready for the next URL-entry + activate).
- **Legacy opt-out untouched:** `RACECAST_MANUAL_FEED_ARM=0` → `next_auto` does **not**
  auto-stop the freed feed (legacy pre-roll intact); a full two-handover sequence still works.
- **Default flip:** `manual_feed_arm_enabled({})` is `True`; `{"RACECAST_MANUAL_FEED_ARM":"0"}`
  is `False`; existing truthy-token tests still pass.
- **Continuation / past-last branches:** no auto-stop (no genuine handover cut).

## Explicitly out of scope

- Any warm-then-cut state machine / just-in-time auto-arm of the incoming feed. Not needed:
  the operator always activates the incoming feed before `/next` (workflow step 2).
- The POV feed (its own `/pov/*` controls, unchanged).
- The Schedule "Active" column idea (#492 out-of-scope, still deferred).

## Acceptance criteria

- [ ] After a `/next` handover that cuts to an armed incoming feed, the outgoing feed's pull
      stops automatically (process gone, port freed, reports `stopped` not `down`).
- [ ] `/next` pressed before the incoming feed is armed cuts nothing and stops nothing — the
      live picture is preserved.
- [ ] The freed feed ends disarmed on its next slot.
- [ ] Manual arm is the default; `RACECAST_MANUAL_FEED_ARM=0` restores the legacy auto path
      with no auto-stop and working seamless handovers.
- [ ] `.env.example` + release notes document the default flip and the opt-out.
- [ ] Director Panel arm/stop controls visible by default with the auto-stop hint;
      `director-panel.png` refreshed.
