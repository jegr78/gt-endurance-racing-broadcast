# Back-to-back stint continuity (same commentator, same feed URL)

**Status:** Design — approved direction, pre-implementation.
**Date:** 2026-07-03
**Area:** relay (`src/relay/racecast-feeds.py`), plus the pure schedule helpers it exports.

## Problem

The schedule assumes one commentator stream per stint and the relay ping-pongs two
feeds along it (Feed A odd stints, Feed B even). Occasionally one commentator has to
cover **back-to-back stints** and keeps their single stream running across both — e.g.
`Stint 1 = A`, `Stint 2 = B`, `Stint 3 = B` (same URL), `Stint 4 = C`.

Maintaining the same feed URL on two consecutive schedule rows breaks the current
mechanism in two ways:

1. **Duplicate continuous pull.** After the 1→2 handover the now-off-air Feed A is
   advanced by `+2` onto Stint 3 (`URL_B`). So for the *entire* Stint 2, Feed B (on air)
   **and** Feed A both pull the identical `URL_B` — not just during the handover overlap.
   Besides being wasteful, pulling the same unlisted YouTube stream twice with the same
   cookies risks concurrent-stream / rate-limit rejection.
2. **Unnecessary cut mid-commentator.** At the 2→3 handover OBS cuts from Feed B to Feed A
   even though both show the identical stream — an avoidable video/audio glitch in the
   middle of one continuous commentator segment.

Dropping the Stint 3 row instead would fix the pull but make the running order / stint-plan
display wrong (it must show Stint 2 and Stint 3 as distinct stints).

## Requirements (decided)

- **Two separate schedule rows are kept** — the running order shows Stint 2 and Stint 3
  distinctly. No new Sheet convention (no merged `"2-3"` label, no count column).
- **The relay recognizes continuity from the data** and, for a same-URL continuation,
  performs **no re-pull and no OBS cut**.
- **Boundary behavior:** the producer presses **Next** at every stint boundary, as today.
  On a continuation Next, the video keeps running untouched, but the **logical stint
  pointer advances**: the HUD stint label moves (`Stint 2` → `Stint 3`) and the ON-AIR
  marker moves down one row in the stint plan / cockpit / Race Control desk.
- Detection is on **the URL only, consecutive rows only** (see Non-goals).

## Approach: pull-slots + a logical on-air row pointer

The insight is that two things are conflated today: the **feed's pull position** and the
**displayed on-air stint**. During a normal race they are the same row; during a
continuation they must diverge. We split them.

### 1. Pull-slots (pure function)

A new pure helper collapses **maximal runs of consecutive rows with the same non-empty
URL** into *slots*:

```
pull_slots(rows) -> list[int]        # slot id per row index, parallel to rows
# rows are ScheduleSource 4-tuples (url, streamer, stint, line)
# [A, B, B, D]         -> [0, 1, 1, 2]
# [A, B, A]            -> [0, 1, 2]   (non-consecutive same URL != continuation)
# [B, B, B]            -> [0, 0, 0]
# blank/empty URL rows -> never merged (each is its own slot; you cannot "continue"
#                         a stream that has no link yet)
```

The two feeds ping-pong over **slots**, not raw rows: a single `URL_B` pull serves both
Stint 2 and Stint 3. Deduplication and the no-cut behavior therefore fall out of the data
structure instead of being special-cased in three code paths.

Helpers derived from `pull_slots` (also pure, unit-tested):

- `slot_first_row(slot_of, slot_id)` — the first row index of a slot (the row a feed
  actually pulls for that slot).
- `next_slot_first_row(slot_of, row)` — first row of the slot **after** the slot
  containing `row`, or `len(rows)` (idle) when none. Used to preload the off-air feed and
  to advance a freed feed — this is what skips a continuation run instead of landing a
  second feed on it.
- `is_continuation(slot_of, row)` — `True` when `row` and `row-1` share a slot (the Next
  onto `row` is label-only).

### 2. Logical on-air row pointer

Add `Relay.on_air_row` — the **0-based schedule row currently on screen for display**.
Add an accessor `Relay.on_air_row_idx()` returning it (clamped to the schedule).

- On a **real handover** it advances with the feed (they stay in lock-step).
- On a **continuation Next** it advances **alone**: the on-air feed's physical `idx` stays
  parked on the slot's first row (the live pull is untouched), while `on_air_row` moves to
  the next display row.

Invariant preserved: `live_feed()` still returns the feed on the lower physical `idx`
(the on-air feed pulls the slot's first row; the off-air feed preloads a strictly later
slot). No change to `live_feed()`.

### 3. `next_auto()` — the state machine

After `self.source.refresh(...)` (fresh Sheet data at handover, unchanged) and recomputing
`slot_of = pull_slots(rows)`:

```
next_row = on_air_row + 1
if next_row >= len(rows):        # past the last stint -> idle advance (today's behavior)
    ...
elif slot_of[next_row] == slot_of[on_air_row]:
    # ---- CONTINUATION: label-only ----
    on_air_row = next_row
    # on-air feed idx stays on the slot's first row: NO set_index, NO re-pull, NO cut.
    # off-air feed is already preloaded on the next different slot: nothing to advance.
    return {..., "obs_cut": False, "continuation": True}
else:
    # ---- REAL HANDOVER ----
    # 1. Reconcile the off-air feed's preload against fresh slots (handles a Sheet edit
    #    that turned a former continuation into a real handover): ensure it sits on
    #    next_slot_first_row(slot_of, on_air_row); set_index if not (re-pulls).
    # 2. Cut to the (previously off-air) feed if it is serving (today's `cut` gate).
    # 3. Advance the freed feed to next_slot_first_row(slot_of, <new on-air row>).
    # 4. on_air_row = next_row
    return {..., "obs_cut": cut, "continuation": False}
```

Preload avoidance is structural: a freed feed always jumps to the **next different slot**,
so it can never sit on the URL the on-air feed is already serving — problem (1) is gone.
The continuation branch never cuts — problem (2) is gone.

### 4. Display consumers re-point to `on_air_row`

Every consumer that today reads `relay.feeds[relay.live_feed()].idx` as the on-air stint
switches to `relay.on_air_row_idx()`:

- `live_schedule_row(rows, live_idx)` → HUD stint/streamer (`/hud/data`, `/status`).
- `cockpit_tally(rows, live_idx, me)` → cockpit ON AIR / UP NEXT.
- `cockpit_schedule(rows, live_idx, me)` → cockpit stint-plan `on_air` highlight.
- `race_control_schedule(rows, live_map)` and the qualifying `live` map → the `live` map's
  on-air entry is built from `on_air_row_idx()` (not the on-air feed's physical idx), so
  the desk highlights the displayed stint (Stint 3) during a continuation. The off-air
  feed's preload marker still comes from its physical idx.

`current_channel()` (the actual pull) keeps using the feed's physical `idx` — during a
continuation that is the slot's first row, whose URL is exactly the continuing stream.

### 5. Takeover / startup become slot-aware

`stint_start_indices(stint, n)` (used by `set_stint` and the `--stint N` startup path)
today returns `(stint-1, stint)`. A takeover at a stint that is the *second* half of a
back-to-back (e.g. Stint 3) must not start a fresh mid-slot pull offset from the slot
head. Replace/wrap it with a slot-aware helper:

- On-air feed A → `slot_first_row(slot_of, slot_of[stint-1])` (pull the slot head once).
- Off-air feed B → `next_slot_first_row(slot_of, stint-1)`.
- `on_air_row = stint - 1` (display shows the taken-over stint).

`set_stint()` and `set_mode()` set `on_air_row` accordingly; qualifying (single row) yields
one slot and `on_air_row = 0` — a no-op for continuity.

## Data flow (worked example `[A, B, B, D]`, slots `[0,1,1,2]`)

| Event            | Feed A idx / URL | Feed B idx / URL | on_air_row | HUD    | OBS cut | Pulls (distinct)   |
|------------------|------------------|------------------|-----------|--------|---------|--------------------|
| start (stint 1)  | 0 / A **(air)**  | 1 / B (preload)  | 0         | Stint 1| —       | A, B               |
| Next → 2 (real)  | 3 / D (preload)  | 1 / B **(air)**  | 1         | Stint 2| yes     | B, D  ← no dup B    |
| Next → 3 (cont.) | 3 / D (preload)  | 1 / B **(air)**  | 2         | Stint 3| **no**  | B, D  ← same pull   |
| Next → 4 (real)  | 3 / D **(air)**  | idle             | 3         | Stint 4| yes     | D                  |

Old behavior for contrast: at "Next → 2" Feed A landed on `idx 2 = URL_B` (duplicate B for
all of Stint 2), and "Next → 3" cut B→A between two identical streams.

## Edge cases

- **3+ in a row** (`B,B,B`): one slot; two consecutive label-only advances, then a real
  handover. Works by construction.
- **Same URL, non-consecutive** (`A,B,A`): separate slots; normal ping-pong with a re-pull
  on the return — unchanged from today.
- **Blank/planned rows**: empty-URL rows are never merged, so a planned-but-linkless stint
  never counts as a continuation; the feed idles on it as today.
- **Live Sheet edit that changes a boundary**: slots are recomputed on the `refresh()` at
  each `/next`/`/reload`; the real-handover branch reconciles the off-air feed's preload
  before cutting, so an edit that turns a former continuation into a real handover re-pulls
  the correct URL instead of cutting to a stale preload. Consistent with the existing
  "sheet edits apply on the next /next" rule; a running feed is never torn mid-stint.
- **POV feed**: independent driver PiP — untouched.
- **Qualifying mode**: single row → single slot → continuity is inert.

## Testing (TDD, stdlib-only, in `tests/test_pov.py`'s style)

Pure functions first (new `tests/` cases or extend `test_pov.py`):

- `pull_slots`: the four canonical shapes above + empty-URL non-merge + empty schedule.
- `slot_first_row` / `next_slot_first_row` / `is_continuation`: including past-the-end idle.
- Slot-aware takeover indices: takeover onto a continuation's second row parks the feed on
  the slot head, not mid-slot; off-air feed preloads the next slot.

State-machine level (extend the existing `Relay`-driving tests):

- A full `[A,B,B,D]` walk asserting per-step `(A.idx, B.idx, on_air_row, obs_cut,
  continuation)` matches the table; assert **no feed ever pulls a URL the on-air feed is
  serving** (duplicate-pull guard) and **the continuation Next reports `obs_cut == False`**.
- Display consumers return the logical stint during a continuation:
  `live_schedule_row` / `cockpit_tally` / `cockpit_schedule` / `race_control_schedule`
  reflect `on_air_row`, not the on-air feed's physical idx.

## Non-goals

- **URL normalization.** Continuity is exact-string equality after `.strip()`. Two
  different-but-equivalent URLs (e.g. `watch?v=` vs `youtu.be/`) are treated as a real
  handover (a re-pull). Producers keep one identical link across back-to-back rows; this is
  the conservative, surprise-free choice.
- **Automatic label advance.** The producer still presses Next at each boundary; there is
  no timer/telemetry coupling to auto-advance the label mid-slot (GT7 has no timing API —
  see the domain constraints).
- **Merging by commentator name.** Detection is URL-based; a name column that happens to
  repeat with a *different* URL is a genuine new pull, not a continuation.
- No Sheet schema change, no Companion button change (the same `/next` press drives both
  branches; the relay decides).

## Files touched

- `src/relay/racecast-feeds.py` — new pure helpers (`pull_slots`, `slot_first_row`,
  `next_slot_first_row`, `is_continuation`, slot-aware takeover indices); `Relay.on_air_row`
  + `on_air_row_idx()`; `next_auto()`, `set_stint()`, `set_mode()`, and the `--stint N`
  startup path; the ~5 display call sites that read `feeds[live_feed()].idx`.
- `tests/test_pov.py` (+ any dedicated `tests/` file that already drives the `Relay`
  state machine) — the cases above.
- No changes to HTML/overlay/Companion/Sheet.
