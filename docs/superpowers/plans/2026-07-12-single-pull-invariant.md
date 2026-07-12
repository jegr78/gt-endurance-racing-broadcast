# Single-Pull Invariant (#491) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee that no two relay feeds ever pull the identical non-empty URL at once, closing the same-URL back-to-back double-pull (`429`) seen live at N24 stints 7→8.

**Architecture:** One pure helper `dedupe_pull_index(target_idx, other_idx, rows)` computes a collision-free pull index (advancing a colliding feed to the next distinct slot, mirroring the slot-awareness `next_auto`/`set_stint` already have). It is wired into the three **raw** Relay-level activation paths — `set_index`, `reload`, `advance` — leaving the already-slot-aware `next_auto`/`set_stint` and the low-level `Feed.set_index` untouched.

**Tech Stack:** Python 3 stdlib only. Tests are runnable scripts (no pytest) under `tests/`, loaded via `importlib` — see `tests/test_pov.py`.

## Global Constraints

- **Edit only under `src/`** (`dist/`/`runtime/` are generated). Tests go under `tests/`.
- **English only** in all code, comments, log lines, docs.
- **Python stdlib only** — no new dependencies; the relay stays dependency-light.
- **After any relay change run** `python3 tests/test_pov.py`; **before finishing run** `python3 tools/run-tests.py` (full suite) and `python3 tools/lint.py` (ruff, the CI lint job).
- **No secrets, no machine paths, no real IPs** in tests (CI + Windows matrix).
- Spec: `docs/superpowers/specs/2026-07-12-single-pull-invariant-design.md`. Issue #491.

---

### Task 1: Pure helper `dedupe_pull_index`

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add the function next to `next_slot_first_row`, ~line 3707)
- Test: `tests/test_pov.py` (append a test function + register it in the runner list)

**Interfaces:**
- Consumes: existing pure helpers `pull_slots(rows)` and `next_slot_first_row(slots, row)` in the same module.
- Produces: `dedupe_pull_index(target_idx, other_idx, rows) -> (int, bool)` — the collision-free pull index for a feed wanting `target_idx` while the other feed is at `other_idx`, and whether a redirect happened. `rows` are `ScheduleSource` 4-tuples `(url, streamer, stint, line)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pov.py`:

```python
def t_dedupe_pull_index():
    rows = [("uA", "A", "S1", 1), ("uB", "B", "S2", 2),
            ("uB", "B", "S3", 3), ("uD", "D", "S4", 4)]
    # No collision: different URLs -> unchanged.
    assert m.dedupe_pull_index(1, 0, rows) == (1, False)
    # Collision (contiguous same-URL slot): target row2 uB vs other row1 uB
    # -> next distinct slot (row3 uD).
    assert m.dedupe_pull_index(2, 1, rows) == (3, True)
    # Collision at the slot head: target row1 uB vs other row2 uB -> row3.
    assert m.dedupe_pull_index(1, 2, rows) == (3, True)
    # Idle/blank target (idx == len) never collides.
    assert m.dedupe_pull_index(4, 0, rows) == (4, False)
    # Other feed idle -> no collision.
    assert m.dedupe_pull_index(1, 4, rows) == (1, False)
    # Non-contiguous repeated URL: loop past it.
    rows2 = [("uA", "A", "S1", 1), ("uB", "B", "S2", 2),
             ("uC", "C", "S3", 3), ("uB", "B", "S4", 4)]
    # target row3 uB vs other row1 uB -> no safe later slot -> idle sentinel (4).
    assert m.dedupe_pull_index(3, 1, rows2) == (4, True)
    # target row1 uB vs other row3 uB -> next distinct slot row2 (uC).
    assert m.dedupe_pull_index(1, 3, rows2) == (2, True)
```

No runner registration needed — `tests/test_pov.py`'s `__main__` block auto-discovers every top-level `t_*` function via `globals()`; defining the function is enough.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_pov.py`
Expected: FAIL — `AttributeError: module 'irofeeds' has no attribute 'dedupe_pull_index'`.

- [ ] **Step 3: Write minimal implementation**

Insert into `src/relay/racecast-feeds.py` immediately after `is_continuation` (~line 3714), before `slot_start_indices`:

```python
def dedupe_pull_index(target_idx, other_idx, rows):
    """Collision-free pull index for a feed that wants to sit at 0-based
    *target_idx* while the OTHER feed sits at *other_idx*. Enforces the
    single-pull invariant (#491): a feed must never pull the identical non-empty
    URL the other feed already holds.

    - Empty/idle target (idx past the end or a blank URL), or a target URL that
      differs from the other feed's URL -> (target_idx unchanged, False).
    - Same non-empty URL -> advance to next_slot_first_row, the first row of the
      next DISTINCT slot; loop-until-safe so a non-contiguous later slot repeating
      the other feed's URL is skipped too, ending at the idle sentinel
      (idx == len(rows)) when nothing collision-free remains. Returns
      (idx, True). Pure."""
    n = len(rows)
    ti = max(0, min(int(target_idx), n))   # n == the idle sentinel (one past end)

    def url(i):
        return (rows[i][0] or "").strip() if 0 <= i < n else ""

    other_url = url(other_idx)
    if ti >= n or not url(ti) or url(ti) != other_url:
        return ti, False
    slots = pull_slots(rows)
    idx = ti
    while idx < n and url(idx) and url(idx) == other_url:
        idx = next_slot_first_row(slots, idx)   # strictly increases -> terminates
    return idx, True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_pov.py`
Expected: PASS (all `t_*` including `t_dedupe_pull_index`).

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): pure dedupe_pull_index single-pull helper (#491)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Guard the direct-set path (`Relay.set_index`)

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `Relay.set_index(self, which, idx)` (~line 5882)
- Test: `tests/test_pov.py`

**Interfaces:**
- Consumes: `dedupe_pull_index` (Task 1); `self.source.get_rows()`, `self.feeds` (`{"A":…, "B":…}`), `self.on_air_row`, `self.status()`.
- Produces: `Relay.set_index` returns `{**status(), "redirected": bool}`; on a redirect it advances `self.on_air_row` to the requested row so a later `/next` still resolves.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pov.py` (auto-discovered by the `__main__` runner — no registration):

```python
def t_set_index_guards_same_url_double_pull():
    rows = [("uA", "A", "S1", 1), ("uB", "B", "S2", 2),
            ("uB", "B", "S3", 3), ("uD", "D", "S4", 4)]
    r = m.Relay(_StubSource(["uA", "uB", "uB", "uD"], rows), (53001, 53002), LOGDIR)
    r._reflect = lambda live, cut: None
    for f in r.feeds.values():
        f.phase = "serving"
    r.next_auto()                                  # stint 2: B(uB) on air, A freed -> uD
    assert r.live_feed() == "B" and r.B.current_channel()[0] == "uB"
    # Operator directly activates stint 3 (row2, the SAME uB) on feed A.
    out = r.set_index("A", 2)
    assert out["redirected"] is True
    urls = {k: f.current_channel()[0] for k, f in r.feeds.items()}
    assert list(urls.values()).count("uB") == 1    # single uB pull, no duplicate
    assert urls == {"A": "uD", "B": "uB"}          # A stayed on the next distinct slot
    assert r.on_air_row_idx() == 2                  # display advanced to stint 3
    assert r.live_feed() == "B"                     # B (lower idx) stays on air
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_pov.py`
Expected: FAIL — `KeyError: 'redirected'` (the current `set_index` returns bare `status()`).

- [ ] **Step 3: Write minimal implementation**

Replace `Relay.set_index` (currently two lines) with:

```python
    def set_index(self, which, idx):
        f = self.feeds.get(which.upper())
        if not f:
            return None
        other_key = "B" if which.upper() == "A" else "A"
        other = self.feeds.get(other_key)
        redirected = False
        if other is not None:
            rows = self.source.get_rows()
            new_idx, redirected = dedupe_pull_index(idx, other.idx, rows)
            if redirected:
                # The other feed already pulls this URL -> the requested row is a
                # same-URL continuation: advance the DISPLAY to it and send this
                # feed to the next distinct slot, never a duplicate pull (#491).
                self.on_air_row = max(0, min(idx, max(0, len(rows) - 1)))
                LOG.info("set %s -> row %d would duplicate feed %s's stream; "
                         "auto-advanced to row %d (next distinct slot)",
                         which.upper(), idx + 1, other_key, new_idx + 1)
                idx = new_idx
        f.set_index(idx)
        return {**self.status(), "redirected": redirected}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_pov.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "fix(relay): guard direct set_index against same-URL double-pull (#491)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Guard the reload path (`Relay.reload`)

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `Relay.reload(self, which=None)` (~line 5926)
- Test: `tests/test_pov.py`

**Interfaces:**
- Consumes: `dedupe_pull_index` (Task 1); `self.live_feed()`, `self.feeds`, `self.source.get_rows()`. Existing behaviour (substitution detection via `is_substitution`/`_record_substitution`, the `targets` reload loop) is preserved.
- Produces: after a `reload`, the off-air feed is re-pointed off any URL the on-air feed holds, before the pull reconnects.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pov.py` (auto-discovered by the `__main__` runner — no registration):

```python
def t_reload_guards_same_url_double_pull():
    rows = [("uA", "A", "S1", 1), ("uB", "B", "S2", 2),
            ("uX", "X", "S3", 3), ("uD", "D", "S4", 4)]
    src = _StubSource(["uA", "uB", "uX", "uD"], rows)
    r = m.Relay(src, (53001, 53002), LOGDIR)
    r._reflect = lambda live, cut: None
    for f in r.feeds.values():
        f.phase = "serving"
    # Start: A row0 uA on air, B preloaded row1 uB. The operator edits the sheet
    # so row1's URL becomes uA (== the on-air feed's stream) and reloads.
    src._items[1] = "uA"
    src._rows[1] = ("uA", "A", "S2", 2)
    r.reload()
    urls = {k: f.current_channel()[0] for k, f in r.feeds.items()}
    assert list(urls.values()).count("uA") == 1    # on-air uA not duplicated
    assert r.live_feed() == "A"                     # on-air feed unchanged (no cut)
    assert r.A.current_channel()[0] == "uA"
    assert r.B.current_channel()[0] != "uA"         # off-air B re-pointed off the dup
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_pov.py`
Expected: FAIL — both feeds resolve to `uA` (assert `count("uA") == 1` fails).

- [ ] **Step 3: Write minimal implementation**

In `Relay.reload`, insert the invariant check after the `self.source.refresh(...)` + substitution block and **before** the `targets = …` line:

```python
        # Single-pull invariant (#491): a schedule edit may have made the off-air
        # feed's parked row share the on-air feed's URL. Re-point the OFF-AIR feed
        # to the next distinct slot before it reconnects, so two feeds never pull
        # the identical stream. Moving a parked feed never cuts the live picture;
        # done regardless of `which` (a reload("A") can still leave B on a dup).
        off = "B" if live == "A" else "A"
        ded_rows = self.source.get_rows()
        ded_idx, ded_redir = dedupe_pull_index(
            self.feeds[off].idx, self.feeds[live].idx, ded_rows)
        if ded_redir:
            LOG.info("reload: feed %s parked on feed %s's stream; auto-advanced "
                     "to row %d (next distinct slot)", off, live, ded_idx + 1)
            self.feeds[off].set_index(ded_idx)
```

(`live` is already bound earlier in the method as `live = self.live_feed()`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_pov.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "fix(relay): reload cannot leave two feeds on one URL (#491)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Guard the nudge path (`Relay.advance`) + full verification

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `Relay.advance(self, which, delta)` (~line 5873)
- Test: `tests/test_pov.py`

**Interfaces:**
- Consumes: `dedupe_pull_index` (Task 1); `self.feeds`, `self.source.get_rows()`, `self.status()`.
- Produces: `Relay.advance` returns `{**status(), "changed": bool, "feed": str, "redirected": bool}` (adds the `redirected` key; `changed`/`feed` unchanged).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pov.py` (auto-discovered by the `__main__` runner — no registration):

```python
def t_advance_guards_same_url_double_pull():
    rows = [("uA", "A", "S1", 1), ("uB", "B", "S2", 2),
            ("uB", "B", "S3", 3), ("uD", "D", "S4", 4)]
    r = m.Relay(_StubSource(["uA", "uB", "uB", "uD"], rows), (53001, 53002), LOGDIR)
    r._reflect = lambda live, cut: None
    for f in r.feeds.values():
        f.phase = "serving"
    # A row0 uA on air, B row1 uB. Nudge A by +2 -> row2 (uB) would duplicate B.
    out = r.advance("A", +2)
    assert out["redirected"] is True
    urls = {k: f.current_channel()[0] for k, f in r.feeds.items()}
    assert list(urls.values()).count("uB") == 1     # no duplicate uB
    assert r.A.current_channel()[0] == "uD"          # A bumped to next distinct slot
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_pov.py`
Expected: FAIL — `KeyError: 'redirected'` (current `advance` has no such key; A would also land on `uB`).

- [ ] **Step 3: Write minimal implementation**

Replace `Relay.advance` with:

```python
    def advance(self, which, delta):
        f = self.feeds.get(which.upper())
        if not f:
            return None
        other_key = "B" if which.upper() == "A" else "A"
        other = self.feeds.get(other_key)
        target = f.idx + delta
        redirected = False
        if other is not None:
            rows = self.source.get_rows()
            target, redirected = dedupe_pull_index(target, other.idx, rows)
            if redirected:
                LOG.info("advance %s would duplicate feed %s's stream; "
                         "auto-advanced to row %d (next distinct slot)",
                         which.upper(), other_key, target + 1)
        changed = f.set_index(target)
        # Spread **self.status() FIRST, explicit keys last, so a future status()
        # field can never silently shadow these (matches next_auto's ordering).
        return {**self.status(), "changed": changed, "feed": which.upper(),
                "redirected": redirected}
```

- [ ] **Step 4: Run the relay test + full suite + lint**

Run: `python3 tests/test_pov.py`
Expected: PASS (all `t_*`).

Run: `python3 tools/run-tests.py`
Expected: PASS (whole suite — confirms no regression in `test_racecast`, `test_streams`, etc.).

Run: `python3 tools/lint.py`
Expected: no findings (`All checks passed`).

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "fix(relay): guard prev/next nudge against same-URL double-pull (#491)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Invariant "no two feeds pull identical non-empty URL" → `dedupe_pull_index` (Task 1).
- Pure helper, loop-until-safe, idle sentinel → Task 1 impl + tests.
- Wiring on `set_index`/`reload`/`advance`, low-level `Feed.set_index` untouched → Tasks 2/3/4.
- `on_air_row` follows on a set collision (later `/next` resolves) → Task 2 impl + assertion.
- `reload` pair-check regardless of `which`, off-air feed yields (no cut) → Task 3.
- `redirected` note + log line → all three wiring tasks.
- Acceptance regression: stints 7→8 same URL via set-path AND reload-path → Tasks 2 + 3.
- Out of scope (defensive `live_feed`, desync banner, Resync button) → left for #494; not in this plan. ✓

**Placeholder scan:** none — every step has concrete code/commands and expected output.

**Type consistency:** `dedupe_pull_index(target_idx, other_idx, rows) -> (int, bool)` used identically in Tasks 2/3/4. `rows` are `ScheduleSource` 4-tuples everywhere. `self.feeds` keyed `"A"`/`"B"`. Return dicts add only the `redirected` key (plus the pre-existing `changed`/`feed` on `advance`).
