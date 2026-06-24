# Relay Dead-Stint Backoff & Idle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the relay from hammering a stint whose stream has ended (the 632 MB / 220 k-line 403 storm) by adding escalating backoff and an idle-after-N give-up to the "was-live-then-died" path, while leaving the "not-yet-live" pre-roll path untouched.

**Architecture:** Two pure, unit-tested helpers (`dead_serve_backoff`, `should_idle_dead_serves`) carry the schedule/decision; a thin change to `Feed.run`'s post-`proc.wait()` tail counts consecutive fast-dying serves, backs off escalating-then-idle, and resets the counter on a real serve or operator action.

**Tech Stack:** Pure Python 3 + stdlib only. Tests are runnable scripts (`t_*` functions, no pytest). Relay module is `src/relay/racecast-feeds.py`, loaded in tests via importlib as `m`.

## Global Constraints

- Edit only under `src/` and `tests/`. Never touch `dist/`/`runtime/`.
- Python + stdlib only; no new dependencies; the relay stays dependency-light (do NOT import `config.py` or other shared modules into `racecast-feeds.py`).
- All code and comments in English.
- Tests must run on any machine and in CI — no real IPs, no machine paths, no network, no sleeps that depend on wall-clock; the new helpers are pure and tested without spawning threads or processes.
- Run `python3 tools/lint.py` after changing any Python file (ruff; mirrors CI).
- After changing the relay, run `python3 tests/test_pov.py`.
- Exact new constants: `DEAD_SERVE_BACKOFF_CAP = 300`, `DEAD_SERVE_IDLE_AFTER = 5`. `RETRY_SLEEP` (10) is the backoff base; `RESOLVE_RETRY` (15) and the not-yet-live path are unchanged.
- "Dead serve" threshold is the existing `HEALTH_SERVED_OK_S` (10 s): a serve that ends with `serve_elapsed < HEALTH_SERVED_OK_S` is a dead serve.
- **Critical:** the dead-serve counter (`self.dead_serves`) must NOT be reset inside `_clear_drop_health()` — that helper is called at every serve-start (line ~3310 of `run`), which would zero the counter each iteration so it never accumulates. Reset it only in: the `served_ok` branch, the operator-`advance` branch of `run`, and explicitly inside `set_index()` and `reload()`.

---

### Task 1: Pure helpers + constants

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add two constants near the existing timing constants at lines 123-126; add two pure functions near `feed_fast_exit_error`/`serve_exit_is_drop`, lines ~129-160)
- Test: `tests/test_pov.py` (add `t_*` functions, helper-style like `t_feed_fast_exit_error_*`)

**Interfaces:**
- Consumes: nothing (leaf helpers).
- Produces:
  - `DEAD_SERVE_BACKOFF_CAP = 300` (int, seconds)
  - `DEAD_SERVE_IDLE_AFTER = 5` (int)
  - `dead_serve_backoff(count, base=RETRY_SLEEP, cap=DEAD_SERVE_BACKOFF_CAP) -> int|float` — escalating sleep `base * 2**(count-1)` capped at `cap`; `count < 1` returns `base`.
  - `should_idle_dead_serves(count, limit=DEAD_SERVE_IDLE_AFTER) -> bool` — `count >= limit`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pov.py` (anywhere among the other `t_*` helper tests, e.g. right after `t_serve_exit_is_drop`). The module under test is already loaded as `m`:

```python
def t_dead_serve_backoff_escalates_and_caps():
    # base, 2x, 4x, 8x with the default base (RETRY_SLEEP = 10)
    assert m.dead_serve_backoff(1) == 10
    assert m.dead_serve_backoff(2) == 20
    assert m.dead_serve_backoff(3) == 40
    assert m.dead_serve_backoff(4) == 80
    # capped at DEAD_SERVE_BACKOFF_CAP (300)
    assert m.dead_serve_backoff(6) == 300
    assert m.dead_serve_backoff(100) == 300
    # count below 1 falls back to the base (defensive)
    assert m.dead_serve_backoff(0) == 10
    # explicit base/cap honoured
    assert m.dead_serve_backoff(3, base=5, cap=15) == 15   # 5*4=20 -> capped to 15


def t_should_idle_dead_serves_at_limit():
    assert m.should_idle_dead_serves(4) is False
    assert m.should_idle_dead_serves(5) is True            # DEAD_SERVE_IDLE_AFTER == 5
    assert m.should_idle_dead_serves(6) is True
    assert m.should_idle_dead_serves(2, limit=2) is True   # custom limit
    assert m.should_idle_dead_serves(1, limit=2) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_pov.py`
Expected: FAIL with `AttributeError: module 'irofeeds' has no attribute 'dead_serve_backoff'`.

- [ ] **Step 3: Add the constants**

In `src/relay/racecast-feeds.py`, find the existing block (lines ~123-126):

```python
RESOLVE_RETRY = 15  # seconds between yt-dlp resolve attempts while a stint isn't live
# ...
RETRY_SLEEP = 10    # seconds after a stream ends / manifest expires before re-resolving
FEED_FAST_EXIT_S = 3.0  # a serve proc dying faster than this (non-zero) = a bind/launch failure, not a stint
```

Add immediately after `FEED_FAST_EXIT_S`:

```python
DEAD_SERVE_BACKOFF_CAP = 300   # s — max delay between re-attempts of a fast-dying ("was live, now dead") serve
DEAD_SERVE_IDLE_AFTER = 5      # consecutive dead serves -> go idle until the operator advances/reloads
```

- [ ] **Step 4: Add the pure helpers**

In the same file, near `feed_fast_exit_error` / `serve_exit_is_drop` (lines ~129-160), add:

```python
def dead_serve_backoff(count, base=RETRY_SLEEP, cap=DEAD_SERVE_BACKOFF_CAP):
    """Escalating sleep (seconds) before re-attempting a stint whose serve keeps
    dying fast (the 403/expired-manifest 'was live, now dead' case): base, 2x base,
    4x base ... capped at `cap`. `count` is the number of consecutive dead serves so
    far (>= 1); a count below 1 returns `base`. Pure so the schedule is unit-tested
    without sleeping."""
    return min(base * (2 ** max(count - 1, 0)), cap)


def should_idle_dead_serves(count, limit=DEAD_SERVE_IDLE_AFTER):
    """True once consecutive dead serves reach `limit` -> the feed stops re-spawning
    and idles until the operator advances (/next) or reloads (/reload)."""
    return count >= limit
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 tests/test_pov.py`
Expected: PASS — prints `ok t_dead_serve_backoff_escalates_and_caps` and `ok t_should_idle_dead_serves_at_limit` among the others.

- [ ] **Step 6: Lint**

Run: `python3 tools/lint.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): pure dead-serve backoff/idle helpers + constants"
```

---

### Task 2: Wire backoff + idle into Feed.run

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `Feed.__init__` (add state, ~line 3188), `set_index`/`reload` (reset, lines ~3240/3246), `Feed.run` tail (lines ~3319-3342)

**Interfaces:**
- Consumes from Task 1: `dead_serve_backoff(count)`, `should_idle_dead_serves(count)`, `HEALTH_SERVED_OK_S`, `RETRY_SLEEP`.
- Produces: new per-feed attribute `self.dead_serves` (int). No new public methods.

**Note on testing:** `Feed.run` is a thread loop that spawns subprocesses; the project does not unit-test it directly (consistent with the existing relay test strategy — the pure helpers from Task 1 carry the logic). This task's verification is: the full `test_pov.py` suite still passes (no regression), lint is clean, and a careful read confirms the integration matches the spec. Do NOT add a test that spawns streamlink or sleeps for real backoff durations.

- [ ] **Step 1: Add the counter to `Feed.__init__`**

In `Feed.__init__`, right after `self.served_ok = False` (line ~3187) and before `self.quality = None`:

```python
        self.served_ok = False
        # Consecutive "was live, now dead" serves (resolved OK but died faster than
        # HEALTH_SERVED_OK_S — the 403/expired-manifest case). Drives escalating
        # backoff and the idle-after-N give-up in run(). Reset on a real serve, on
        # operator advance, and in set_index()/reload(). NOT reset in
        # _clear_drop_health() (that runs every serve-start, which would zero it).
        self.dead_serves = 0
        self.quality = None               # last streamlink-selected quality (e.g. "720p")
```

- [ ] **Step 2: Reset the counter in `set_index` and `reload`**

In `set_index` (line ~3240), after `self._clear_drop_health()`:

```python
        self._clear_drop_health()         # director repositioned -> alarm acknowledged, new source not yet served
        self.dead_serves = 0              # new source -> fresh dead-serve count
        self.advance.set(); self._kill_proc()
```

In `reload` (line ~3246), after `self._clear_drop_health()`:

```python
        self._clear_drop_health()         # director intervened -> alarm acknowledged, reconnecting source
        self.dead_serves = 0              # operator reload -> fresh dead-serve count
        self.advance.set(); self._kill_proc()
```

- [ ] **Step 3: Update the `run` tail — served_ok reset, advance reset, dead-serve branch**

In `Feed.run`, the current tail (lines ~3323-3342) is:

```python
            if serve_elapsed >= HEALTH_SERVED_OK_S:
                self.served_ok = True
            # ... dropped/dropped_since bookkeeping (unchanged) ...
            was_dropped = self.dropped
            self.dropped = serve_exit_is_drop(self.stop, self.advance.is_set())
            if self.dropped and not was_dropped:
                self.dropped_since = time.time()
            if self.stop: break
            if self.advance.is_set():
                self.advance.clear(); continue
            # #143: ... fast-exit bind-failure surface ...
            err = feed_fast_exit_error(serve_elapsed, serve_rc)
            if err:
                self.last_error = err
            time.sleep(RETRY_SLEEP)
```

Change three things. First, the served_ok line resets the counter:

```python
            if serve_elapsed >= HEALTH_SERVED_OK_S:
                self.served_ok = True
                self.dead_serves = 0               # stable live picture -> reset
```

Second, the operator-advance branch resets the counter:

```python
            if self.advance.is_set():
                self.advance.clear()
                self.dead_serves = 0               # operator moved/reloaded -> fresh source
                continue
```

Third, replace the final `time.sleep(RETRY_SLEEP)` (and keep the `feed_fast_exit_error`
lines just above it) with the dead-serve branch:

```python
            err = feed_fast_exit_error(serve_elapsed, serve_rc)
            if err:
                self.last_error = err
            if serve_elapsed < HEALTH_SERVED_OK_S:
                # Resolved OK but the serve died fast (403/expired manifest / VOD).
                self.dead_serves += 1
                if should_idle_dead_serves(self.dead_serves):
                    self._set_phase("idle")
                    self.last_error = ("stint source unavailable — paused after "
                                       f"{self.dead_serves} attempts; /next or /reload to retry")
                    # Stop hammering: wait for operator /next or /reload (which set
                    # advance) or shutdown (self.stop). advance wakes us instantly;
                    # the 1 s timeout bounds the stop-check latency.
                    while not self.stop and not self.advance.is_set():
                        self.advance.wait(1.0)
                    continue                       # top of loop re-evaluates; advance/stop handled there
                time.sleep(dead_serve_backoff(self.dead_serves))
                continue
            time.sleep(RETRY_SLEEP)                 # served_ok serve that simply ended normally
```

- [ ] **Step 4: Run the full relay suite to verify no regression**

Run: `python3 tests/test_pov.py`
Expected: PASS — all `t_*` print `ok`, including Task 1's two new tests.

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: no errors.

- [ ] **Step 6: Run the broader suite that touches the relay**

Run: `python3 tests/test_bind.py && python3 tests/test_racecast.py`
Expected: both PASS (they import/exercise the relay module; this confirms the edits did not break module load or unrelated relay paths).

- [ ] **Step 7: Commit**

```bash
git add src/relay/racecast-feeds.py
git commit -m "fix(relay): escalating backoff + idle-after-N for dead stint serves"
```

---

## Self-Review

**Spec coverage:**
- Two failure paths distinguished → Task 2 Step 3 (only the `serve_elapsed < HEALTH_SERVED_OK_S` path changes; the not-yet-live `resolve` path at line ~3290 is untouched). ✅
- New constants `DEAD_SERVE_BACKOFF_CAP`/`DEAD_SERVE_IDLE_AFTER` → Task 1 Step 3. ✅
- Pure helpers `dead_serve_backoff`/`should_idle_dead_serves` → Task 1 Steps 3-4. ✅
- `self.dead_serves` state + reset on real serve / advance / set_index / reload → Task 2 Steps 1-3. ✅
- Idle waits on `self.advance`, woken by operator; bounded stop-check → Task 2 Step 3. ✅
- Streamlink flags / Path A / health model untouched → no task changes them (explicit in Global Constraints + Task 2 note). ✅
- Tests in `tests/test_pov.py` (escalation, cap, count<1; idle limit) → Task 1 Step 1. ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✅

**Type/name consistency:** `dead_serve_backoff`, `should_idle_dead_serves`, `self.dead_serves`, `DEAD_SERVE_BACKOFF_CAP`, `DEAD_SERVE_IDLE_AFTER`, `HEALTH_SERVED_OK_S`, `RETRY_SLEEP` used identically across both tasks. ✅
