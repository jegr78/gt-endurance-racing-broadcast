# Feed fan-out trailing-cursor prebuffer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the source-jitter feed stutters by joining OBS (and the program-audio monitor) `N` seconds behind the fan-out ring's live edge instead of at it, so a bursty low-bitrate source's short gaps are absorbed by an in-ring reserve.

**Architecture:** `FeedRing` gains a throttled `(offset, monotonic_ts)` time index and two pure readers (`offset_at_age`, `trailing_offset`). A module-level pure `fanout_join_offset(ring, prebuffer_s, now)` picks the join cursor. The OBS HTTP consumer (`FeedFanoutServer._serve`) and the program-audio encoder input (`ProgramAudioService._feed_stdin`) call it; the Director-Panel preview tap and the MP3-output serve stay at the live edge (unchanged). Depth is `RACECAST_FEED_PREBUFFER_S` (default 3.0 s; `0` = today's live-edge join).

**Tech Stack:** Python 3 stdlib only (no new deps). Tests are stdlib runnable scripts under `tests/` (each `t_*` function auto-runs from the `__main__` harness).

## Global Constraints

- Edit only under `src/` (plus `tests/`, `.env.example`, `docs/`, `CLAUDE.md`). Never touch `dist/`/`runtime/`.
- Python + stdlib only. No new runtime dependencies. The relay stays dependency-light.
- All code/docs English only.
- Tests must run on any machine and in CI — no real IPs, machine paths, or environment-specific values; inject `now` and use in-memory `FeedRing`s, never real sockets/streams for the new unit tests.
- Pure logic is unit-tested; prefer TDD (failing test first).
- `python3 tools/run-tests.py` and `python3 tools/lint.py` must pass at the end.
- The single source of truth is `src/relay/racecast-feeds.py`; keep `FeedRing`'s "writer never blocks" invariant intact.

---

### Task 1: `FeedRing` time index — `offset_at_age` / `trailing_offset`

**Files:**
- Modify: `src/relay/racecast-feeds.py` (import line ~69; constants near line 343; `FeedRing` class 3582–3629)
- Test: `tests/test_fanout.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `FeedRing.write(self, data, now=None)` — unchanged behaviour; optionally records a time mark (`now` defaults to `time.monotonic()`; tests inject a float).
  - `FeedRing.offset_at_age(self, age_s, now) -> int` — the absolute offset that was the live edge ~`age_s` ago, clamped to `[start_offset, live_offset]`.
  - `FeedRing.trailing_offset(self, prebuffer_s, now) -> int` — `live_offset()` when `prebuffer_s <= 0`, else `offset_at_age(prebuffer_s, now)`.
  - Module constants `MARK_MIN_INTERVAL_S = 0.1`, `DEFAULT_FEED_PREBUFFER_S = 3.0`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fanout.py` (above the `if __name__ == "__main__":` block):

```python
def t_ring_trailing_offset_holds_reserve():
    r = m.FeedRing(1_000_000)
    for i in range(10):                     # write 100 bytes/s; live edge = (i+1)*100
        r.write(b"x" * 100, now=float(i))
    # 3 s behind now=9 -> newest mark with ts<=6 is (700, 6)
    assert r.trailing_offset(3.0, now=9.0) == 700


def t_ring_offset_at_age_clamps_to_start_when_young():
    r = m.FeedRing(1_000_000)
    r.write(b"x" * 100, now=0.0)
    r.write(b"x" * 100, now=0.5)            # only 0.5 s of history
    assert r.offset_at_age(3.0, now=0.5) == r.start_offset() == 0


def t_ring_trailing_offset_zero_is_live_edge():
    r = m.FeedRing(1_000_000)
    r.write(b"x" * 500, now=1.0)
    assert r.trailing_offset(0.0, now=5.0) == r.live_offset() == 500


def t_ring_marks_throttled():
    r = m.FeedRing(10_000)
    for i in range(20):                     # 20 writes 10 ms apart = 0.19 s span
        r.write(b"x" * 10, now=i * 0.01)
    assert len(r._marks) <= 3               # MARK_MIN_INTERVAL_S=0.1 -> ~2-3 marks


def t_ring_marks_pruned_on_overflow():
    r = m.FeedRing(250)
    for i in range(10):                     # 1 s apart -> each its own mark
        r.write(b"x" * 100, now=float(i))
    assert r.start_offset() == 750          # 1000 written, cap 250
    assert all(off > 750 for off, _ in r._marks)   # scrolled-out marks pruned


def t_ring_write_still_works_without_now():
    r = m.FeedRing(1024)                     # production writer passes no `now`
    r.write(b"abc")
    data, cur = r.read(0, timeout=0.1)
    assert data == b"abc" and cur == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_fanout.py`
Expected: FAIL — `AttributeError: 'FeedRing' object has no attribute 'trailing_offset'` (or `_marks`).

- [ ] **Step 3: Implement the time index**

In `src/relay/racecast-feeds.py`:

(a) Add `collections` to the stdlib import line (~line 69), keeping it alphabetical:
```python
import argparse, collections, csv, datetime, hmac, html, io, ipaddress, json, logging, os, random, re, secrets, shutil, signal, socket, ssl, subprocess, sys, threading, time
```

(b) Near `FANOUT_RING_BYTES` (~line 343) add the constants:
```python
MARK_MIN_INTERVAL_S = 0.1        # #533: throttle the FeedRing time index to ~1 mark/100 ms
DEFAULT_FEED_PREBUFFER_S = 3.0   # #533: seconds a broadcast consumer joins behind the fan-out live edge
```

(c) In `FeedRing.__init__`, add the marks deque (after `self._base = 0`):
```python
        self._marks = collections.deque()   # #533: (live_offset, monotonic_ts) samples, throttled+pruned
```

(d) Replace `FeedRing.write` (3596–3606) with the mark-recording version:
```python
    def write(self, data, now=None):
        if not data:
            return
        with self._cond:
            self._buf += data
            overflow = len(self._buf) - self.capacity
            if overflow > 0:
                del self._buf[:overflow]
                self._base += overflow
            live = self._base + len(self._buf)
            self._record_mark(live, now)     # #533: time index for trailing joins
            self._cond.notify_all()

    def _record_mark(self, live, now):
        # Caller holds self._cond. Sample the live edge at most once per
        # MARK_MIN_INTERVAL_S, then drop marks that have scrolled out of the
        # retained window (offset <= base). Pure aside from the default clock.
        if now is None:
            now = time.monotonic()
        if not self._marks or (now - self._marks[-1][1]) >= MARK_MIN_INTERVAL_S:
            self._marks.append((live, now))
        while self._marks and self._marks[0][0] <= self._base:
            self._marks.popleft()
```

(e) Add the two readers after `start_offset` (before `read`):
```python
    def offset_at_age(self, age_s, now):
        """The absolute offset that was the live edge ~age_s ago (the newest mark
        with ts <= now-age_s), clamped to the retained window. When the ring holds
        less than age_s of history it returns start_offset (serve the oldest
        retained byte). Pure — now is injected."""
        with self._cond:
            live = self._base + len(self._buf)
            target = now - age_s
            chosen = self._base
            for off, ts in self._marks:
                if ts <= target:
                    chosen = off
                else:
                    break
            return min(max(self._base, chosen), live)

    def trailing_offset(self, prebuffer_s, now):
        """The join offset prebuffer_s seconds behind the live edge (#533);
        the live edge itself when prebuffer_s <= 0 (today's behaviour)."""
        if prebuffer_s <= 0:
            return self.live_offset()
        return self.offset_at_age(prebuffer_s, now)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_fanout.py`
Expected: PASS — ends with `all fanout tests passed`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_fanout.py
git commit -m "feat(relay): FeedRing time index for trailing joins (#533)"
```

---

### Task 2: `feed_prebuffer_s` config helper + `.env.example`

**Files:**
- Modify: `src/relay/racecast-feeds.py` (near `feed_autoresync_enabled`, ~line 355–366)
- Modify: `.env.example` (feed knobs block, after line 27)
- Test: `tests/test_fanout.py`

**Interfaces:**
- Consumes: `DEFAULT_FEED_PREBUFFER_S` (Task 1).
- Produces: `feed_prebuffer_s(environ, default=DEFAULT_FEED_PREBUFFER_S) -> float` — absent/empty/non-numeric → `default`; a valid number (including `0`) is honoured; negatives clamp to `0.0` (disabled = live-edge join).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fanout.py`:

```python
def t_feed_prebuffer_s_default_and_overrides():
    assert m.feed_prebuffer_s({}) == 3.0                                   # absent -> default
    assert m.feed_prebuffer_s({"RACECAST_FEED_PREBUFFER_S": ""}) == 3.0    # empty -> default
    assert m.feed_prebuffer_s({"RACECAST_FEED_PREBUFFER_S": "3.5"}) == 3.5
    assert m.feed_prebuffer_s({"RACECAST_FEED_PREBUFFER_S": "0"}) == 0.0   # explicit disable
    assert m.feed_prebuffer_s({"RACECAST_FEED_PREBUFFER_S": "-1"}) == 0.0  # negative clamps to 0
    assert m.feed_prebuffer_s({"RACECAST_FEED_PREBUFFER_S": "abc"}) == 3.0 # invalid -> default
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_fanout.py`
Expected: FAIL — `AttributeError: module 'irofeeds' has no attribute 'feed_prebuffer_s'`.

- [ ] **Step 3: Implement the helper**

In `src/relay/racecast-feeds.py`, after `feed_autoresync_enabled` (~line 366):

```python
def feed_prebuffer_s(environ, default=DEFAULT_FEED_PREBUFFER_S):
    """Seconds OBS and the program-audio monitor join behind the fan-out live edge
    (#533). Absent/empty/non-numeric -> default; a valid number (incl. 0) is used
    as-is; negatives clamp to 0.0 (disabled = today's live-edge join). Pure so the
    knob is unit-testable."""
    raw = str(environ.get("RACECAST_FEED_PREBUFFER_S", "")).strip()
    if raw == "":
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default
```

In `.env.example`, after line 27 (`# RACECAST_FEED_STALL_S=20 ...`):

```bash
# RACECAST_FEED_PREBUFFER_S=3.0          # #533: seconds OBS/program-audio join behind the fan-out
#                                        # live edge so bursty source gaps don't stutter (0 = live edge)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_fanout.py`
Expected: PASS — `all fanout tests passed`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py .env.example tests/test_fanout.py
git commit -m "feat(relay): RACECAST_FEED_PREBUFFER_S config knob (#533)"
```

---

### Task 3: `fanout_join_offset` + OBS trailing join (`FeedFanoutServer`, `Relay`)

**Files:**
- Modify: `src/relay/racecast-feeds.py` — new `fanout_join_offset` (place just above `class FeedFanoutServer`, ~line 3633); `FeedFanoutServer.__init__` (3639–3648) + `_serve` join (3674); `Relay.__init__` (~5864) + `Relay.start` `FeedFanoutServer(...)` (5936)
- Modify: `CLAUDE.md` (fan-out paragraph)
- Test: `tests/test_fanout.py`

**Interfaces:**
- Consumes: `FeedRing.trailing_offset` (Task 1), `feed_prebuffer_s` (Task 2).
- Produces:
  - `fanout_join_offset(ring, prebuffer_s, now) -> int` — `ring.trailing_offset(prebuffer_s, now)` when available; else `ring.live_offset()` when available; else `0`.
  - `FeedFanoutServer(host, port, ring, log, prebuffer_s=0.0)` with attribute `self.prebuffer_s` and method `_join_offset(self, now) -> int`.
  - `Relay.feed_prebuffer_s: float` (set in `__init__`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fanout.py` (add `import logging` to the file's import line if not present, or reference `m.logging`):

```python
def t_fanout_join_offset_trailing_when_indexed():
    r = m.FeedRing(1_000_000)
    for i in range(10):
        r.write(b"x" * 100, now=float(i))
    assert m.fanout_join_offset(r, 3.0, now=9.0) == 700


def t_fanout_join_offset_zero_prebuffer_is_live():
    r = m.FeedRing(1_000_000)
    r.write(b"x" * 500, now=1.0)
    assert m.fanout_join_offset(r, 0.0, now=5.0) == 500


def t_fanout_join_offset_falls_back_without_index():
    class BareLive:
        def live_offset(self):
            return 42
    assert m.fanout_join_offset(BareLive(), 3.0, now=9.0) == 42

    class Bare:
        pass
    assert m.fanout_join_offset(Bare(), 3.0, now=9.0) == 0


def t_fanout_server_join_uses_prebuffer():
    r = m.FeedRing(1_000_000)
    for i in range(10):
        r.write(b"x" * 100, now=float(i))
    srv = m.FeedFanoutServer("127.0.0.1", 0, r, m.logging.getLogger("t533"),
                             prebuffer_s=3.0)
    assert srv.prebuffer_s == 3.0
    assert srv._join_offset(now=9.0) == 700
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_fanout.py`
Expected: FAIL — `AttributeError: module 'irofeeds' has no attribute 'fanout_join_offset'`.

- [ ] **Step 3: Implement the helper and wire OBS**

(a) Add the pure helper just above `class FeedFanoutServer:` (~line 3633):
```python
def fanout_join_offset(ring, prebuffer_s, now):
    """Absolute cursor a BROADCAST consumer (OBS, program-audio) joins at: prebuffer_s
    seconds behind the ring's live edge (#533), or the live edge when prebuffer_s <= 0
    or the ring has no time index (direct-serve / test doubles). Pure — now injected."""
    if hasattr(ring, "trailing_offset"):
        return ring.trailing_offset(prebuffer_s, now)
    if hasattr(ring, "live_offset"):
        return ring.live_offset()
    return 0
```

(b) `FeedFanoutServer.__init__` — accept and store `prebuffer_s`:
```python
    def __init__(self, host, port, ring, log, prebuffer_s=0.0):
        self.host = host
        self.port = port
        self.ring = ring
        self.log = log
        self.prebuffer_s = prebuffer_s        # #533: join OBS this far behind the live edge
        self._sock = None
        self._stop = False
        self._consumers = {}            # id -> {"cycle_ts": float, "snaps": int}
        self._consumers_lock = threading.Lock()
```

(c) Add a testable join method and use it in `_serve`. Add after `__init__` (before `start`):
```python
    def _join_offset(self, now):
        return fanout_join_offset(self.ring, self.prebuffer_s, now)
```
In `_serve`, replace line 3674:
```python
            cursor = self.ring.live_offset()    # join at the live edge
```
with:
```python
            cursor = self._join_offset(time.monotonic())   # #533: join prebuffer_s behind the live edge
```

(d) `Relay.__init__` — after `self.fanout = fanout_enabled(os.environ)` (~line 5864), add:
```python
        self.feed_prebuffer_s = feed_prebuffer_s(os.environ)   # #533: OBS/program-audio trailing depth
```

(e) `Relay.start` — pass it into the constructor (line 5936):
```python
                srv = FeedFanoutServer("127.0.0.1", f.port, f.ring,
                                       logging.getLogger("racecast.fanout." + f.name),
                                       prebuffer_s=self.feed_prebuffer_s)
```

(f) `CLAUDE.md` — in the fan-out paragraph (the `RACECAST_FEED_FANOUT` section), append one sentence:
```
By default OBS and the program-audio monitor join the ring **`RACECAST_FEED_PREBUFFER_S` seconds behind the live edge** (default 3 s, #533) so a bursty low-bitrate source's short gaps are absorbed by the in-ring reserve instead of stalling OBS (`=0` restores the live-edge join); the Director-Panel preview still taps the live edge.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_fanout.py`
Expected: PASS — `all fanout tests passed`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py CLAUDE.md tests/test_fanout.py
git commit -m "feat(relay): join OBS behind the fan-out live edge (trailing prebuffer) (#533)"
```

---

### Task 4: Program-audio monitor joins trailing

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `ProgramAudioService` (add `_join_offset`; change `_feed_stdin` join at 3955)
- Test: `tests/test_program_audio.py`

**Interfaces:**
- Consumes: `fanout_join_offset` (Task 3), `Relay.feed_prebuffer_s` (Task 3).
- Produces: `ProgramAudioService._join_offset(self, ring, now) -> int` — `fanout_join_offset(ring, getattr(self.relay, "feed_prebuffer_s", 0.0), now)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_program_audio.py` (match its existing module-load: it exposes the module as `m`; add `import logging` if the file doesn't already):

```python
def t_program_audio_join_offset_uses_relay_prebuffer():
    r = m.FeedRing(1_000_000)
    for i in range(10):
        r.write(b"x" * 100, now=float(i))

    class FakeRelay:
        feed_prebuffer_s = 3.0
    svc = m.ProgramAudioService(FakeRelay(), logging.getLogger("t533pa"))
    assert svc._join_offset(r, now=9.0) == 700


def t_program_audio_join_offset_defaults_when_relay_lacks_attr():
    r = m.FeedRing(1_000_000)
    r.write(b"x" * 500, now=1.0)

    class FakeRelay:
        pass
    svc = m.ProgramAudioService(FakeRelay(), logging.getLogger("t533pa"))
    assert svc._join_offset(r, now=5.0) == 500   # getattr default 0.0 -> live edge
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_program_audio.py`
Expected: FAIL — `AttributeError: 'ProgramAudioService' object has no attribute '_join_offset'`.

- [ ] **Step 3: Implement**

In `ProgramAudioService`, add the method (near `_feed_stdin`):
```python
    def _join_offset(self, ring, now):
        return fanout_join_offset(ring, getattr(self.relay, "feed_prebuffer_s", 0.0), now)
```
In `_feed_stdin` (line 3955), replace:
```python
        cursor = ring.live_offset() if hasattr(ring, "live_offset") else 0
```
with:
```python
        cursor = self._join_offset(ring, time.monotonic())   # #533: match OBS's trailing join
```
Update the `_feed_stdin` docstring line "join at the ring's current live edge (only recent data, no rewind)" to "join `feed_prebuffer_s` behind the live edge to match the broadcast (#533)".

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_program_audio.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_program_audio.py
git commit -m "feat(relay): program-audio monitor joins the trailing offset (#533)"
```

---

### Task 5: Full-suite + lint verification gate

**Files:** none (verification only).

- [ ] **Step 1: Run the full test suite**

Run: `python3 tools/run-tests.py`
Expected: all tests pass (includes `test_fanout.py`, `test_program_audio.py`, `test_feed_preview.py`, `test_pov.py`). If `test_feed_preview.py` or any consumer test fails because it asserted a live-edge join, confirm the failure is only in the two *changed* consumers (OBS, program-audio) and that the preview/POV still join at the live edge (they must — they were not changed); fix any real regression, otherwise the suite is green.

- [ ] **Step 2: Run lint**

Run: `python3 tools/lint.py`
Expected: no findings. Fix any (e.g. unused import) inline.

- [ ] **Step 3: Build self-verify (ships-safe check)**

Run: `python3 tools/build.py`
Expected: build + verify step passes (tokenization, no secrets, no shell scripts).

- [ ] **Step 4: Commit any fixups (only if Steps 1–3 required changes)**

```bash
git add -A
git commit -m "chore(relay): lint/test fixups for trailing prebuffer (#533)"
```

---

## Self-Review

**Spec coverage:**
- Component 1 (FeedRing time index, `offset_at_age`/`trailing_offset`, throttled marks, 16 MB unchanged) → Task 1. ✅
- Component 2 (`FeedFanoutServer` OBS join → trailing) → Task 3. ✅
- Component 3 (config `RACECAST_FEED_PREBUFFER_S`, default 3.0, `0` disables, `.env.example`) → Task 2. ✅
- Per-consumer policy (OBS trailing, program-audio trailing, preview live-edge) → Task 3 (OBS) + Task 4 (program-audio); preview/MP3-output left unchanged by design (verified in Task 5 Step 1). ✅
- Interactions (#488 reconnect rejoins trailing, watchdog unaffected, direct-serve fallback has no ring) → no code change needed; `fanout_join_offset` degrades to live-edge/0 without a ring index (tested in Task 3). ✅
- Fallback B (paced de-jitter) → out of scope unless live validation fails; not in this plan by design. ✅
- Validation: unit tests (Tasks 1–4) cover the ring math + join wiring; the local ffmpeg back-pressure test + live smoke are maintainer steps in the spec, not code — noted, not a plan task. ✅

**Placeholder scan:** No TBD/TODO; every code step shows full code; every run step shows the command + expected output.

**Type consistency:** `trailing_offset(prebuffer_s, now)`, `offset_at_age(age_s, now)`, `fanout_join_offset(ring, prebuffer_s, now)`, `FeedFanoutServer(..., prebuffer_s=0.0)`, `_join_offset(now)` (server) vs `_join_offset(ring, now)` (program-audio — different receiver, intentionally different arity), `Relay.feed_prebuffer_s`, `feed_prebuffer_s(environ, default=...)` — consistent across tasks.

**Note on the two `_join_offset` methods:** `FeedFanoutServer._join_offset(now)` reads its own `self.prebuffer_s`; `ProgramAudioService._join_offset(ring, now)` reads `self.relay.feed_prebuffer_s` and takes the ring explicitly (the on-air feed ring changes across handovers). Both delegate to the single pure `fanout_join_offset`.
