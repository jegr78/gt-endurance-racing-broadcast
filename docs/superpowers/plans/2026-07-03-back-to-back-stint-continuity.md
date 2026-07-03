# Back-to-back Stint Continuity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let one commentator cover back-to-back stints on a single continuous stream (same feed URL on consecutive schedule rows) without a duplicate pull or an OBS cut mid-commentator, while the HUD/stint-plan still shows every stint distinctly.

**Architecture:** A pure `pull_slots(rows)` helper collapses consecutive same-URL rows into "slots"; the two feeds ping-pong over slots instead of raw rows (so a same-URL run is served by one pull and never re-cut). A new `Relay.on_air_row` pointer decouples the *displayed* stint from the *feed pull position* — on a same-URL continuation Next it advances alone (label moves, video untouched); otherwise it advances with a real handover.

**Tech Stack:** Python 3 stdlib only. Relay lives in `src/relay/racecast-feeds.py`; tests are plain runnable scripts in `tests/` (no pytest).

## Global Constraints

- **Edit only under `src/`** (and `tests/`). Never touch `dist/`/`runtime/`.
- **stdlib only** — no new dependencies; the relay stays dependency-light.
- **All code/comments/docs English only.**
- **The relay is the self-contained script** `src/relay/racecast-feeds.py` — it must not import shared `src/scripts/` modules for this work; keep the new helpers local to the file, next to `stint_start_indices`.
- **Tests run on any machine / CI** — no real IPs, URLs, or machine paths; use the existing `_StubSource` / `_relay` fixtures.
- Run `python3 tests/test_pov.py` after every task; run `python3 tools/lint.py` on the changed file; the final task runs `python3 tools/run-tests.py` and `python3 tools/build.py`.
- Spec: `docs/superpowers/specs/2026-07-03-back-to-back-stint-continuity-design.md`.

### Reference: how to run one test function

```bash
python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_pull_slots_basic()"
```

`python3 tests/test_pov.py` runs the whole file (its `__main__` block invokes every `t_*`).

---

### Task 1: Pure slot helpers

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add functions immediately after `stint_start_indices`, ~line 3296)
- Test: `tests/test_pov.py` (add functions; they auto-run via the `__main__` block)

**Interfaces:**
- Consumes: nothing (pure, stdlib only).
- Produces:
  - `pull_slots(rows) -> list[int]` — slot id per row (parallel to `rows`); `rows` are ScheduleSource 4-tuples `(url, streamer, stint, line)`.
  - `slot_first_row(slots, sid) -> int | None` — first row index of slot `sid`.
  - `next_slot_first_row(slots, row) -> int` — first row of the slot after `row`'s slot, or `len(slots)` (idle sentinel) if none.
  - `is_continuation(slots, row) -> bool` — `True` when `row` shares a slot with `row-1`.
  - `slot_start_indices(stint, rows) -> (a_idx, b_idx)` — slot-aware takeover placement.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pov.py` (anywhere among the `t_*` functions):

```python
def t_pull_slots_basic():
    def rows(urls): return [(u, "", "", i + 1) for i, u in enumerate(urls)]
    assert m.pull_slots(rows(["a", "b", "b", "d"])) == [0, 1, 1, 2]   # back-to-back b
    assert m.pull_slots(rows(["a", "b", "a"])) == [0, 1, 2]           # non-consecutive != run
    assert m.pull_slots(rows(["b", "b", "b"])) == [0, 0, 0]           # three in a row
    assert m.pull_slots(rows(["", ""])) == [0, 1]                     # blanks never merge
    assert m.pull_slots(rows(["a", "", "a"])) == [0, 1, 2]            # blank breaks the run
    assert m.pull_slots([]) == []


def t_slot_row_helpers():
    slots = [0, 1, 1, 2]
    assert m.slot_first_row(slots, 1) == 1
    assert m.slot_first_row(slots, 2) == 3
    assert m.slot_first_row(slots, 9) is None
    # off-air preload / freed-feed target skips the same-URL run:
    assert m.next_slot_first_row(slots, 0) == 1      # after slot0 -> row1 (b)
    assert m.next_slot_first_row(slots, 1) == 3      # after slot1 (b,b) -> row3 (d), NOT row2
    assert m.next_slot_first_row(slots, 3) == 4      # after last slot -> idle sentinel (len)
    assert m.next_slot_first_row([], 0) == 0
    # continuation detection:
    assert m.is_continuation(slots, 2) is True       # row2 continues row1 (same b)
    assert m.is_continuation(slots, 1) is False      # row1 is a new slot
    assert m.is_continuation(slots, 0) is False      # no row -1
    assert m.is_continuation(slots, 4) is False      # past the end


def t_slot_start_indices():
    def rows(urls): return [(u, "", "", i + 1) for i, u in enumerate(urls)]
    # normal schedule: identical to stint_start_indices (every row its own slot)
    assert m.slot_start_indices(3, rows(["a", "b", "c", "d"])) == (2, 3)
    # takeover onto the SECOND row of a back-to-back (stint 3 = second b):
    # Feed A parks on the slot HEAD (row1), Feed B preloads the next slot (row3)
    assert m.slot_start_indices(3, rows(["a", "b", "b", "d"])) == (1, 3)
    # takeover onto the FIRST b (stint 2): A row1, B skips the duplicate -> row3
    assert m.slot_start_indices(2, rows(["a", "b", "b", "d"])) == (1, 3)
    # empty schedule falls back
    assert m.slot_start_indices(1, []) == (0, 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_pov.py`
Expected: FAIL with `AttributeError: module ... has no attribute 'pull_slots'`.

- [ ] **Step 3: Write the implementation**

Insert into `src/relay/racecast-feeds.py` right after `stint_start_indices` (after line ~3296, before `live_schedule_row`):

```python
def pull_slots(rows):
    """Slot id per row: maximal runs of CONSECUTIVE rows with the same non-empty
    URL share one slot, so a single feed pull serves the whole run — a commentator
    keeping one stream across back-to-back stints. A blank/empty URL never merges
    (you cannot 'continue' a stream that has no link), so each blank row is its own
    slot and a blank breaks a run. *rows* are ScheduleSource 4-tuples
    (url, streamer, stint, line); returns a list parallel to rows. Pure."""
    slots = []
    prev_url = None
    sid = -1
    for r in rows:
        url = (r[0] or "").strip()
        if url and url == prev_url:
            slots.append(sid)                 # continuation of the current run
        else:
            sid += 1
            slots.append(sid)
        prev_url = url or None                 # a blank breaks the run
    return slots


def slot_first_row(slots, sid):
    """First row index belonging to slot *sid*, or None when absent. Pure."""
    for i, s in enumerate(slots):
        if s == sid:
            return i
    return None


def next_slot_first_row(slots, row):
    """First row of the slot AFTER the slot containing *row*, or len(slots) (the
    idle sentinel, one past the last row) when there is none. This is where the
    off-air feed preloads and a freed feed advances, so it always skips a same-URL
    continuation run instead of landing a second feed on it. Pure."""
    if not slots:
        return 0
    row = max(0, min(row, len(slots) - 1))
    cur = slots[row]
    for i in range(row + 1, len(slots)):
        if slots[i] != cur:
            return i
    return len(slots)                          # no later slot -> idle past the end


def is_continuation(slots, row):
    """True when the Next onto 0-based *row* stays within the same slot as row-1
    (a same-URL back-to-back) -> a label-only advance: no re-pull, no OBS cut.
    Pure."""
    return 1 <= row < len(slots) and slots[row] == slots[row - 1]


def slot_start_indices(stint, rows):
    """Slot-aware producer-takeover placement. 1-based *stint* is on air NOW: Feed
    A pulls the HEAD of that stint's slot (so a takeover onto the second row of a
    back-to-back pulls the single stream once, not a mid-slot offset), Feed B
    preloads the head of the NEXT slot. Returns (a_idx, b_idx). For a normal
    schedule (each row its own slot) this equals stint_start_indices. *rows* are
    ScheduleSource 4-tuples. Pure; falls back to stint_start_indices on an empty
    schedule."""
    n = len(rows)
    if n == 0:
        return stint_start_indices(stint, 0)
    stint = max(1, int(stint))
    row = min(stint - 1, n - 1)
    slots = pull_slots(rows)
    a = slot_first_row(slots, slots[row])
    b = next_slot_first_row(slots, row)
    return a, b
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_pov.py`
Expected: PASS (all `t_*`, including the three new ones).

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: no new findings on `racecast-feeds.py`.

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): pure pull-slot helpers for same-URL stint continuity"
```

---

### Task 2: `on_air_row` pointer + display re-point (behavior-neutral)

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `Relay.__init__` (~4732), add `on_air_row_idx()` / `live_row_map()` methods, rewire `live_schedule_row()` method (~5137), keep `on_air_row` synced in `next_auto`/`set_stint`/`set_mode`, and repoint the four handler call sites.
- Test: `tests/test_pov.py`

**Interfaces:**
- Consumes: `pull_slots`, `slot_start_indices` (Task 1).
- Produces:
  - `Relay.on_air_row` (int attribute) — 0-based displayed on-air row.
  - `Relay.on_air_row_idx() -> int` — clamped displayed row.
  - `Relay.live_row_map() -> dict[int, str]` — `{row_index: feed_key}` for schedule highlights (on-air feed keyed by displayed row, off-air by physical idx).

**Note:** This task is behavior-neutral — `on_air_row` is kept equal to the on-air feed's pull index everywhere, so the displayed stint does not yet diverge. Task 3 introduces the divergence; because the display consumers are repointed here first, they light up automatically then.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pov.py`:

```python
def t_on_air_row_tracks_feed_in_normal_operation():
    r = _relay(["s1", "s2", "s3", "s4"])
    assert r.on_air_row_idx() == 0                       # stint 1
    assert r.live_row_map() == {0: "A", 1: "B"}          # on-air A row0, off-air B row1
    r.next_auto()                                        # B (stint 2) on air
    assert r.on_air_row_idx() == 1
    assert r.live_feed() == "B"
    assert r.live_row_map() == {1: "B", 2: "A"}          # on-air B row1, off-air A row2
    # the HUD row follows the displayed on-air row
    rows = r.source.get_rows()
    assert m.live_schedule_row(rows, r.on_air_row_idx())["stint"] == r.live_schedule_row()["stint"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_on_air_row_tracks_feed_in_normal_operation()"`
Expected: FAIL with `AttributeError: 'Relay' object has no attribute 'on_air_row_idx'`.

- [ ] **Step 3a: Initialize `on_air_row` in `__init__`**

In `Relay.__init__`, replace the current placement line (~4732):

```python
        a_idx, b_idx = stint_start_indices(start_stint, len(self.active_source().get()))
```

with:

```python
        a_idx, b_idx = slot_start_indices(start_stint, self.active_source().get_rows())
        # 0-based DISPLAY row currently on air (drives the HUD stint label + the
        # ON-AIR marker). Equals the on-air feed's pull index in normal operation;
        # diverges one row ahead only during a same-URL back-to-back continuation.
        self.on_air_row = a_idx
```

- [ ] **Step 3b: Add the two accessor methods**

Add these methods to `Relay` (place next to `live_feed`, ~5083):

```python
    def on_air_row_idx(self):
        """0-based schedule row currently ON SCREEN — drives the HUD stint label
        and the ON-AIR marker on the cockpit / stint-plan / Race Control views.
        Equals the on-air feed's pull index in normal operation; during a same-URL
        back-to-back continuation it sits one row ahead of the still-parked pull.
        Clamped to the active schedule."""
        n = len(self.source.get())
        if not n:
            return 0
        return max(0, min(self.on_air_row, n))

    def live_row_map(self):
        """{row_index: feed_key} for the schedule-highlight consumers: the on-air
        feed is keyed by the DISPLAY row (on_air_row_idx), the off-air feed by its
        physical pull index. Equals {f.idx: key} in normal operation; during a
        continuation the on-air marker follows the displayed stint. The on-air
        entry is written last so it wins any (degenerate) index collision."""
        live = self.live_feed()
        off = "B" if live == "A" else "A"
        row_map = {self.feeds[off].idx: off}
        row_map[self.on_air_row_idx()] = live
        return row_map
```

- [ ] **Step 3c: Rewire the `live_schedule_row()` method**

Change the method body (~5141) from `self.feeds[self.live_feed()].idx` to the display row:

```python
    def live_schedule_row(self):
        """{"streamer", "stint"} for the stint currently ON SCREEN, or None when it
        idles past the schedule end. Drives the handover HUD auto-write (issue
        #112) and follows a same-URL continuation label."""
        return live_schedule_row(self.source.get_rows(), self.on_air_row_idx())
```

- [ ] **Step 3d: Keep `on_air_row` synced (behavior-neutral) in the mutators**

In `next_auto` (~5264), after the handover computes `new_live`, add a sync line so `on_air_row` follows the on-air feed. Change the tail of `next_auto`:

```python
        nf = self.feeds[new_live]
        self.on_air_row = nf.idx                      # keep display row == on-air pull (Task 3 makes it diverge)
        LOG.info("handover -> feed %s now on air (stint index %d)", nf.name, nf.idx + 1)
        return {**result, "obs_cut": cut}
```

In `set_stint` (~5292), after `self.A.set_index(a_idx)` / `self.B.set_index(b_idx)`:

```python
        self.on_air_row = a_idx
```

In `set_mode` (~5313), after `self.A.set_index(a_idx)` / `self.B.set_index(b_idx)`:

```python
        self.on_air_row = a_idx
```

- [ ] **Step 3e: Repoint the four display call sites to the new accessors**

These four handler sites currently derive the on-air row from the feed index; repoint them so Task 3's divergence flows through. Each is a mechanical swap (no behavior change while `on_air_row == feed.idx`).

Race Control data (~6011-6012):

```python
                    rows = relay.source.get_rows()
                    live = relay.live_row_map()
                    live_idx = relay.on_air_row_idx()
```

Cockpit data (~6454):

```python
                        live_idx = relay.on_air_row_idx()
                        tally = cockpit_tally(rows, live_idx, me)
```

(the `cockpit_schedule(rows, live_idx, me)` call at ~6473 already reads that local `live_idx` — no further change.)

The two `live_schedule_row(rows, live_idx)` handler sites (~6779-6780 and ~6798-6799):

```python
                    live_idx = relay.on_air_row_idx()
                    cur = live_schedule_row(rows, live_idx)
```

Leave the qualifying `live = {f.idx: k ...}` map at ~6614 as-is for now (qualifying is single-row; Task 4 covers mode paths) — but if it is the schedule/panel highlight map, replace it with `relay.live_row_map()` too. Verify by reading the surrounding handler: if it feeds `race_control_schedule`/`cockpit_schedule`, use `live_row_map()`; if it is qualifying-only cosmetic, leave it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_pov.py`
Expected: PASS (new test + all existing, incl. `t_relay_live_schedule_row_tracks_on_air_feed`, `t_set_mode_*`).

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): on_air_row display pointer + repoint schedule consumers"
```

---

### Task 3: Continuation branch in `next_auto` (the divergence)

**Files:**
- Modify: `src/relay/racecast-feeds.py` — rewrite `next_auto` (~5264).
- Modify: `tests/test_pov.py` — make `_StubSource.add` also append a parallel row (so `get_rows()` stays consistent with `get()`, mirroring production).
- Test: `tests/test_pov.py`

**Interfaces:**
- Consumes: `pull_slots`, `next_slot_first_row`, `is_continuation` (Task 1); `on_air_row`, `on_air_row_idx`, `live_feed`, `live_after_next` (Task 2).
- Produces: `next_auto()` returns now include `"continuation": bool`; `obs_cut` is `False` on a continuation.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pov.py`:

```python
def t_back_to_back_no_dup_pull_no_cut():
    rows = [("uA", "A", "Stint 1", 1), ("uB", "B", "Stint 2", 2),
            ("uB", "B", "Stint 3", 3), ("uD", "D", "Stint 4", 4)]
    r = m.Relay(_StubSource(["uA", "uB", "uB", "uD"], rows), (53001, 53002), LOGDIR)
    r._reflect = lambda live, cut: None
    # make both feeds report "serving" so cut/continuation is exercised
    for f in r.feeds.values(): f.phase = "serving"

    def pulled():
        return {k: f.current_channel()[0] for k, f in r.feeds.items()}

    # start: A=uA on air (row0), B preloads uB (row1)
    assert r.on_air_row_idx() == 0 and r.live_feed() == "A"
    assert pulled() == {"A": "uA", "B": "uB"}

    # Next -> stint 2 (real handover): B(uB) on air; freed A must skip the
    # duplicate uB run and preload uD -> NO second uB pull anywhere.
    out1 = r.next_auto()
    assert out1["continuation"] is False and out1["obs_cut"] is True
    assert r.on_air_row_idx() == 1 and r.live_feed() == "B"
    assert pulled() == {"A": "uD", "B": "uB"}
    assert list(pulled().values()).count("uB") == 1        # no duplicate uB

    # Next -> stint 3 (continuation): same feed, same pull, NO cut, label advances
    out2 = r.next_auto()
    assert out2["continuation"] is True and out2["obs_cut"] is False
    assert r.on_air_row_idx() == 2 and r.live_feed() == "B"
    assert pulled() == {"A": "uD", "B": "uB"}               # untouched
    assert r.live_schedule_row() == {"streamer": "B", "stint": "Stint 3"}

    # Next -> stint 4 (real handover): cut to A(uD)
    out3 = r.next_auto()
    assert out3["continuation"] is False and out3["obs_cut"] is True
    assert r.on_air_row_idx() == 3 and r.live_feed() == "A"
    assert r.live_schedule_row() == {"streamer": "D", "stint": "Stint 4"}
```

- [ ] **Step 2: Make the stub consistent, then run the test to verify it fails**

First update `_StubSource.add` (~223) so a mid-event link also appears in `get_rows()`:

```python
    def add(self, url):
        self._items.append(url)
        self._rows.append((url, "", "", len(self._items)))
```

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_back_to_back_no_dup_pull_no_cut()"`
Expected: FAIL — current `next_auto` advances by +2 (Feed A lands on the duplicate `uB`) and has no `"continuation"` key.

- [ ] **Step 3: Rewrite `next_auto`**

Replace the whole `next_auto` method (~5264-5274) with:

```python
    def next_auto(self):
        self.source.refresh(timeout=6)               # fresh sheet data at handover (bounded wait)
        rows = self.source.get_rows()
        slots = pull_slots(rows)
        cur = self.on_air_row_idx()
        nxt = cur + 1

        # Same-URL back-to-back: keep the on-air pull, advance the LABEL only.
        if is_continuation(slots, nxt):
            self.on_air_row = nxt
            LOG.info("continuation -> stint %d stays on feed %s (no cut)",
                     nxt + 1, self.live_feed())
            return {"changed": False, "feed": self.live_feed(),
                    "continuation": True, "obs_cut": False, **self.status()}

        # Past the last stint: idle over-press (unchanged behavior).
        if nxt >= len(rows):
            new_live = self.live_after_next()
            target = "A" if new_live == "B" else "B"
            result = self.advance(target, +2)
            cut = self.feeds[new_live].phase == "serving"
            if cut:
                self._reflect(new_live, cut=True)
            self.on_air_row = self.feeds[new_live].idx
            return {**result, "continuation": False, "obs_cut": cut}

        # Real handover to the pre-warmed off-air feed, walking SLOTS (not +2) so a
        # freed feed skips a continuation run instead of duplicating the on-air pull.
        new_live = self.live_after_next()
        freed = "A" if new_live == "B" else "B"
        # Reconcile the incoming feed's preload against fresh slots (a Sheet edit may
        # have moved the boundary): it must sit on the next slot after the current row.
        self.feeds[new_live].set_index(next_slot_first_row(slots, cur))
        cut = self.feeds[new_live].phase == "serving"
        if cut:
            self._reflect(new_live, cut=True)         # only flip onto a feed that is actually live
        # Advance the freed feed to the slot AFTER the new on-air row.
        self.feeds[freed].set_index(next_slot_first_row(slots, nxt))
        self.on_air_row = nxt
        nf = self.feeds[new_live]
        LOG.info("handover -> feed %s now on air (stint %d)", nf.name, nxt + 1)
        return {"changed": True, "feed": new_live,
                "continuation": False, "obs_cut": cut, **self.status()}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_pov.py`
Expected: PASS — the new back-to-back test plus every existing feed test (`t_next_new_live_is_the_non_advanced_feed`, `t_next_reflects_only_when_incoming_serving`, `t_cold_start_one_link_then_add_second`, `t_next_past_end_is_idle_no_cut`, `t_splitscreen_state_maps_live_feed_to_current`).

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): same-URL continuation skips re-pull + OBS cut on Next"
```

---

### Task 4: Slot-aware takeover / mode + display during continuation

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `set_stint` (~5287), `set_mode` (~5299).
- Test: `tests/test_pov.py`

**Interfaces:**
- Consumes: `slot_start_indices`, `pull_slots` (Task 1); `on_air_row`, `live_row_map` (Task 2).
- Produces: `set_stint` / `set_mode` place feeds on slot heads and set `on_air_row` to the taken-over/first display row.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pov.py`:

```python
def t_set_stint_slot_aware_on_back_to_back():
    rows = [("uA", "A", "Stint 1", 1), ("uB", "B", "Stint 2", 2),
            ("uB", "B", "Stint 3", 3), ("uD", "D", "Stint 4", 4)]
    r = m.Relay(_StubSource(["uA", "uB", "uB", "uD"], rows), (53001, 53002), LOGDIR)
    r._reflect = lambda live, cut: None
    # Takeover: stint 3 (second half of B's back-to-back) is on air NOW.
    r.set_stint(3)
    # Feed A parks on the slot head (row1 = the single uB pull), B preloads uD (row3).
    assert (r.A.idx, r.B.idx) == (1, 3)
    assert r.A.current_channel()[0] == "uB" and r.B.current_channel()[0] == "uD"
    # ...but the DISPLAY shows stint 3.
    assert r.on_air_row_idx() == 2
    assert r.live_schedule_row() == {"streamer": "B", "stint": "Stint 3"}


def t_race_control_map_follows_displayed_stint_on_continuation():
    rows = [("uA", "A", "Stint 1", 1), ("uB", "B", "Stint 2", 2),
            ("uB", "B", "Stint 3", 3), ("uD", "D", "Stint 4", 4)]
    r = m.Relay(_StubSource(["uA", "uB", "uB", "uD"], rows), (53001, 53002), LOGDIR)
    r._reflect = lambda live, cut: None
    for f in r.feeds.values(): f.phase = "serving"
    r.next_auto()                       # stint 2 (B on air, uB pull on B row1)
    r.next_auto()                       # stint 3 continuation: label at row2, pull at row1
    assert r.on_air_row_idx() == 2
    live = r.live_row_map()
    # the RC/stint-plan highlight is on the DISPLAYED stint (row2), not the pull row (1)
    sched = m.race_control_schedule(rows, live)
    assert sched[2]["live"] == "B"      # stint 3 marked live
    assert sched[1]["live"] is None     # stint 2 no longer highlighted
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_set_stint_slot_aware_on_back_to_back()"`
Expected: FAIL — current `set_stint` uses `stint_start_indices` → `(2, 3)` (mid-slot A pull of `uB` at row2, a duplicate placement) and does not set `on_air_row` to the display stint.

- [ ] **Step 3: Make `set_stint` slot-aware**

Replace the body of `set_stint` (~5291-5297):

```python
    def set_stint(self, stint):
        """Producer-takeover correction: 1-based stint <stint> is on air NOW ->
        Feed A serves the HEAD of that stint's slot (a takeover onto a back-to-back's
        second row still pulls the single stream once), Feed B preloads the next
        slot. The DISPLAY row is set to <stint>. Tears a running feed off its stream
        (like /set) — use BEFORE going live, not mid-program."""
        self.source.refresh(timeout=6)      # clamp against fresh sheet data
        rows = self.source.get_rows()
        a_idx, b_idx = slot_start_indices(stint, rows)
        self.A.set_index(a_idx)
        self.B.set_index(b_idx)
        self.on_air_row = min(max(1, int(stint)) - 1, max(0, len(rows) - 1))
        LOG.info("set_stint -> Feed A slot-head %d, Feed B %d, display stint %d",
                 a_idx + 1, b_idx + 1, self.on_air_row + 1)
        self._reflect(self.live_feed(), cut=False)   # set visibility/audio; director picks the scene
        return self.status()
```

- [ ] **Step 4: Make `set_mode` set `on_air_row` from slot placement**

In `set_mode` (~5313), replace the `stint_start_indices` line and add the display-row sync:

```python
        rows = self.active_source().get_rows()
        a_idx, b_idx = slot_start_indices(1, rows)
        self.A.set_index(a_idx)
        self.B.set_index(b_idx)
        self.on_air_row = a_idx
```

(This supersedes the `self.on_air_row = a_idx` line added in Task 2 Step 3d for `set_mode`; keep a single assignment.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 tests/test_pov.py`
Expected: PASS (new takeover + RC-map tests, and existing `t_set_stint_reflects_live_feed_without_cut`, `t_set_mode_switches_active_source_and_feeds` still green — normal schedules give the same indices).

- [ ] **Step 6: Lint**

Run: `python3 tools/lint.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): slot-aware takeover + display row on continuation"
```

---

### Task 5: Full regression, lint, build verify

**Files:** none (verification only).

- [ ] **Step 1: Run the whole test suite**

Run: `python3 tools/run-tests.py`
Expected: all tests pass (this is what CI runs). Pay attention to `tests/test_pov.py`, `tests/test_racecast.py`, `tests/test_cockpit.py`, `tests/test_roles.py` — the cockpit/RC consumers repointed in Task 2.

- [ ] **Step 2: Lint the whole tree**

Run: `python3 tools/lint.py`
Expected: no findings.

- [ ] **Step 3: Build self-verify**

Run: `python3 tools/build.py`
Expected: build + verify pass (tokenization, blanked password, no secrets, no shell scripts).

- [ ] **Step 4: Manual sanity note (no code)**

Confirm by reading `next_auto` once more that: (a) a continuation returns `obs_cut=False` and does not call `set_index` on any feed; (b) the real-handover branch's freed feed uses `next_slot_first_row(slots, nxt)`; (c) `on_air_row` is written in every branch. These are the three invariants the spec's worked-example table depends on.

- [ ] **Step 5: Commit (if run-tests produced any fixture/lint touch-ups)**

```bash
git add -A
git commit -m "test(relay): regression pass for stint continuity" || echo "nothing to commit"
```

---

## Self-Review

**Spec coverage:**
- Pull-slots (spec §1) → Task 1 (`pull_slots`, `slot_first_row`, `next_slot_first_row`, `is_continuation`).
- Logical on-air pointer (spec §2) → Task 2 (`on_air_row`, `on_air_row_idx`).
- `next_auto` state machine incl. preload reconcile (spec §3) → Task 3.
- Display consumers re-point (spec §4) → Task 2 Step 3e (+ `live_row_map` for the RC/stint-plan highlight).
- Slot-aware takeover/startup (spec §5) → Task 1 (`slot_start_indices`, used by `__init__` in Task 2) + Task 4 (`set_stint`/`set_mode`).
- Worked example `[A,B,B,D]` → Task 3 test `t_back_to_back_no_dup_pull_no_cut` asserts the table row-by-row (no dup pull, continuation `obs_cut=False`).
- Edge cases: 3-in-a-row & blanks → Task 1 `t_pull_slots_basic`; non-consecutive same URL → same; live Sheet edit reconcile → Task 3 `next_auto` incoming `set_index(next_slot_first_row(...))`; qualifying inert → single row → one slot (covered by existing `t_set_mode_*` staying green).
- Non-goals (exact-URL match, no auto-advance, no name-merge, no Sheet/Companion change) → honored; no HTML/Sheet/Companion edits in any task.

**Placeholder scan:** none — every code step shows full code; every run step gives the command + expected result.

**Type consistency:** `pull_slots`→`list[int]`; `slot_first_row`→`int|None`; `next_slot_first_row`→`int`; `is_continuation`→`bool`; `slot_start_indices`→`(int,int)`; `on_air_row_idx`→`int`; `live_row_map`→`dict[int,str]`. `next_auto` returns consistently include `"continuation"` and `"obs_cut"` keys across all three branches. `__init__` uses `slot_start_indices(start_stint, rows)` (rows, not len) — matched to Task 1's signature.
