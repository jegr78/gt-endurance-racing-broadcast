# Single-pull invariant on all feed-activation paths (#491)

**Date:** 2026-07-12
**Issue:** [#491](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/491)
**Scope:** `src/relay/racecast-feeds.py` only (relay). #491 is shipped first, as its own
PR; the desync detection/recovery layer (#494) is a separate follow-up.

## Problem

When two consecutive stints share the **same feed URL** (a commentator staying on one
stream back-to-back), a feed can be landed on a URL the *other* feed is already pulling.
Two feeds then pull the **identical YouTube stream from the same IP simultaneously**,
which trips an immediate `429` on both. Observed live during the N24 24h race
(stints 7→8, 2026-07-12, v1.5.5):

```
01:51:15  feed_A  stint 7 -> Q5Er_7PIeB4     # A on air, pulling the stream
04:02:33  feed_B  stint 8 -> Q5Er_7PIeB4     # B lands on the SAME url -> 2nd puller
04:02:38  relay   continuation -> stint 8 stays on feed A (no cut)
04:04:47  feed_A  429 Too Many Requests -> fan-out stall -> killed
04:04:52  feed_B  429 Too Many Requests -> fan-out stall -> killed
```

The `/next` path (`next_auto`) and the takeover path (`set_stint`) are already
slot-aware and never duplicate a pull. The gap: the invariant is **not enforced on the
raw activation paths** — the Relay-level `set_index` (`/set/A|B/<n>`, API/Companion) and
`reload` (the likely incident path: the off-air feed was pre-warmed onto a row whose URL
was then edited to equal the on-air feed's, and a reload reconnected it onto the
duplicate). There is no guard against "two feeds, identical URL".

## Invariant

> **No two feeds may pull the identical non-empty URL at the same time.**

The blank/empty URL is exempt (an idle feed pulls nothing; two idle feeds never collide).

## Design

### 1. Pure helper (unit-testable, beside `pull_slots`)

```python
def dedupe_pull_index(target_idx, other_idx, rows):
    """The collision-free pull index for a feed that wants to sit at 0-based
    *target_idx* while the OTHER feed sits at *other_idx*. Enforces the single-pull
    invariant: a feed never pulls the identical non-empty URL the other feed holds.

    - Empty target URL, or a target URL != the other feed's URL -> target_idx
      unchanged (no collision).
    - Same non-empty URL -> advance to next_slot_first_row(slots, target_idx), the
      first row of the next DISTINCT slot. Loop-until-safe: if a non-contiguous later
      slot repeats the other feed's URL, keep advancing until the URL differs or the
      feed idles past the end (idx == len(rows)).

    Returns (idx, redirected: bool). Pure."""
```

`next_slot_first_row` already skips a same-URL continuation run, so one hop clears the
common (contiguous) case. The loop only matters for a pathological schedule that repeats
a URL in a *non-adjacent* slot; without the loop the redirect could re-collide. The idle
sentinel (`idx == len(rows)`, "one past the last stint") is the terminal fallback — a
feed with nowhere collision-free to go idles rather than duplicating.

### 2. Wiring — Relay level only

`next_auto`/`set_stint` compute already-correct slot indices and call the **low-level
`Feed.set_index`** directly. Those stay untouched — double-guarding could fight their
deliberate placements. The guard sits on the three **raw** activation paths:

- **`Relay.set_index(which, idx)`** (`:5882`, serves `/set/A|B/<n>`): dedupe the moving
  feed's target against the other feed's current index. On a redirect (the other feed is
  already live on that URL = a continuation), advance the moving feed to the next
  distinct slot **and** set `on_air_row = idx` (clamped) so the display label follows the
  continuation. `live_feed()` stays correct because the moved feed goes to a *higher*
  index (off-air), and a later `/next` resolves without manual sheet surgery. With no
  collision, behaviour is unchanged (`on_air_row` untouched, as today).

- **`Relay.reload(which=None)`** (`:5926`): after the schedule refresh, compare the two
  feeds' indices **regardless of `which`** (a `reload("A")` can still leave the parked
  off-air feed on a now-duplicate URL). If they share a non-empty URL, re-point the
  **off-air feed** (the one NOT `live_feed()`) forward via the helper — moving a
  parked/pre-warm feed is free and never cuts the live picture — even when the off-air
  feed was not in the reload target set. Apply the re-point **before** the pull
  reconnects, so the corrected index is what streamlink resolves. The on-air feed keeps
  its URL (no cut).

- **`Relay.advance(which, ±2)`** (`:5873`, Prev/Next nudge): run the same dedupe on the
  nudged feed against the other. Minimal added cost, closes the last raw path.

### 3. Visibility

On any redirect, include a `redirected` note in the return/status object and emit a log
line, e.g. `feed B auto-advanced to stint 9 — would have duplicated feed A's stream`, so
the panel/log explain why an activation "stayed on Feed A".

## Testing (TDD, failing-first)

**Pure helper (`dedupe_pull_index`):**
- empty target URL → unchanged
- target URL != other → unchanged
- contiguous same URL → next distinct slot
- non-contiguous repeated URL → loops past it
- no safe slot before the end → idle sentinel (`len(rows)`)

**Relay regression (the #491 acceptance test):** stints 7→8 same URL, driven through
`Relay.set_index` **and** through `Relay.reload`:
- the two feeds never hold the identical non-empty URL afterwards
- `on_air_row` / `live_feed()` stay consistent (a subsequent `/next` resolves to the
  right feed without sheet surgery)

Tests live with the existing slot/pull helper tests (`tests/test_pov.py`) plus a
relay-level case; run `python3 tests/test_pov.py` and `python3 tools/run-tests.py`.

## Explicitly out of scope (→ #494)

Defensive `live_feed()` against a *dropped* on-air feed, the heartbeat desync-detection
banner, and the "Resync to stint N" panel action. #491 **prevents** the double-pull that
caused the N24 desync; #494 is the **recovery** layer for a desync from any cause.

## Acceptance criteria (from #491)

- [ ] Activating the 2nd stint of a same-URL back-to-back never results in both feeds
      pulling that URL — it stays a single pull regardless of which control is used.
- [ ] Direct `/set/A|B/<n>` onto a URL the other feed is pulling is guarded (redirect to
      the next distinct slot), not a duplicate pull.
- [ ] `reload` cannot leave two feeds on the identical URL.
- [ ] Regression test covers stints 7→8 same-URL activation via the direct-set path
      **and** the reload path.
