# GT7 telemetry: session reset, pit-lap exclusion, on-track time-of-day — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the GT7 POV telemetry engine reset its derived metrics on a session change, exclude pit (in/out) laps from the reference and averages, and add an on-track time-of-day readout to the POV HUD.

**Architecture:** Three additive, POV/solo-only changes. Two are pure-engine correctness fixes in `src/scripts/gt7_telemetry.py` (session-boundary detection + full reset; pit-lap flag via standstill/refuel that blocks a lap from becoming the reference or feeding the time/fuel averages). The third parses one more packet field (`dayProgression` at `0x80`) and surfaces it as a self-gating HUD element. The endurance path stays byte-identical; the telemetry endpoints already 404 in endurance so every HUD addition self-hides.

**Tech Stack:** Pure Python 3 stdlib (no framework, no pip deps). Tests are runnable stdlib scripts (no pytest). HTML/JS in `src/obs/hud.html`. Overlay builder slot extraction in `src/scripts/overlay_build.py`.

## Global Constraints

- **Edit only under `src/`, `tests/`, `docs/`.** `dist/`/`runtime/` are generated — never hand-edit.
- **English only** in all code, comments, docs.
- **Endurance path stays byte-identical.** Every change is POV/solo-only and self-gating; do not alter endurance behaviour. No payload key is renamed or removed — `time_of_day` is a **new** key (additive).
- **Session-reset trigger = lap counter goes backwards OR best-lap clears to −1.** A normal forward increment (e.g. `0 → 1`) must never trigger it.
- **Pit detection basis = sustained standstill (primary) OR fuel rose during the lap (confirmation).** No tyre-temp signal. Pit action is **correctness-only** (exclude from reference + time/fuel averages) — no HUD badge, no stop-type label.
- **Time-of-day** renders as `HH:MM:SS` from ms-since-midnight, wrapped to 24 h, **unit-independent**; it is `None` until the first packet (so the HUD hides it, mirroring `best_s`/`delta_s`).
- **Named constants** for all thresholds: `STOPPED_SPEED_MPS`, `PIT_STOP_MIN_S`, `FUEL_RISE_L`, `OFF_DAY_PROGRESSION`.
- **Tests are stdlib-only and CI-safe** — no real IPs, no machine paths; use `tempfile` for on-disk tests. Cross-platform matrix includes Windows: use `os.path.join` only for current-machine paths.
- **After any Python change** run `python3 tools/lint.py` (the CI lint job). **The full suite** `python3 tools/run-tests.py` must stay green with nothing disabled.
- **`src/obs/hud.html` is a rendered surface:** the `ui-visual-verification` Stop hook blocks completion until you render the HUD element, look at it, and record the marker (`python3 .claude/hooks/record_ui_verified.py src/obs/hud.html`). The overlay-builder slot set changes, so re-capture `src/docs/wiki/images/cc-overlay-builder.png` via the `wiki-screenshots` skill in the same task.

---

### Task 1: Session-start auto-reset

**Files:**
- Modify: `src/scripts/gt7_telemetry.py` — `TelemetryEngine.update`, new `_is_session_boundary` / `_reset_session`; `TelemetryStore.update`, new `_remove_file`.
- Test: `tests/test_gt7_telemetry.py`

**Interfaces:**
- Consumes: existing engine internals — `self._lap_num`, `self._last` (a `GT7Packet` with `.lap`, `.best_ms`), `self._ref`, `self._lap_times`, `self._lap_fuel`, `self._top_speed`, `self._acc`, `_LapAccumulator(now, started_at_boundary=…)`; `TelemetryStore._save`, `self._path`, `self._eng`.
- Produces: `TelemetryEngine._is_session_boundary(pkt) -> bool`, `TelemetryEngine._reset_session(now, pkt) -> None`, `TelemetryStore._remove_file() -> None`. Behaviour: after a session boundary, `snapshot()["has_reference"]` is `False` and `["top_speed_mps"]` is `0.0`; the persisted `telemetry.json` is deleted.

- [ ] **Step 1: Write the failing tests**

Add these four tests to `tests/test_gt7_telemetry.py` (they use the existing `_packet` / `_feed_lap` helpers already in the file):

```python
def t_engine_session_reset_on_lap_backwards():
    eng = tm.TelemetryEngine()
    eng.update(tm.parse_packet(_packet(lap=0)), 99.0)         # mid-connect partial
    _feed_lap(eng, 100.0, 1, duration=10.0, speed=50.0)       # sets a reference; now on lap 2
    assert eng.snapshot()["has_reference"] is True
    assert eng.snapshot()["top_speed_mps"] > 0.0
    # a packet whose lap counter dropped => session boundary => full reset
    eng.update(tm.parse_packet(_packet(lap=0, speed_mps=0.0)), 130.0)
    s = eng.snapshot()
    assert s["has_reference"] is False
    assert s["top_speed_mps"] == 0.0
    # a fresh clean lap re-establishes a reference
    _feed_lap(eng, 131.0, 1, duration=10.0, speed=40.0)
    assert eng.snapshot()["has_reference"] is True


def t_engine_session_reset_on_best_cleared():
    eng = tm.TelemetryEngine()
    eng.update(tm.parse_packet(_packet(lap=0)), 99.0)
    _feed_lap(eng, 100.0, 1, duration=10.0, speed=50.0)
    assert eng.snapshot()["has_reference"] is True
    # best carries a real value, then clears to -1 (GT7 wipes it on a session change)
    eng.update(tm.parse_packet(_packet(lap=2, best_ms=95000)), 130.0)
    eng.update(tm.parse_packet(_packet(lap=2, best_ms=-1)), 130.1)
    assert eng.snapshot()["has_reference"] is False


def t_engine_no_reset_on_normal_lap_increment():
    eng = tm.TelemetryEngine()
    eng.update(tm.parse_packet(_packet(lap=0)), 99.0)
    _feed_lap(eng, 100.0, 1, duration=10.0, speed=50.0)       # ref from lap 1, now on lap 2
    assert eng.snapshot()["has_reference"] is True
    _feed_lap(eng, 120.0, 2, duration=10.0, speed=50.0)       # forward 2 -> 3: NO reset
    assert eng.snapshot()["has_reference"] is True


def t_store_removes_file_on_session_reset():
    import tempfile
    d = tempfile.mkdtemp()
    path = os.path.join(d, "telemetry.json")
    st = tm.TelemetryStore(path, units="metric", reset=True)
    st.update(tm.parse_packet(_packet(lap=0)), 99.0)
    t = 100.0
    for _ in range(100):
        st.update(tm.parse_packet(_packet(speed_mps=50.0, lap=1)), t); t += 0.1
    st.update(tm.parse_packet(_packet(speed_mps=50.0, lap=2)), t)   # lap edge -> ref saved
    assert os.path.exists(path)
    st.update(tm.parse_packet(_packet(lap=0, speed_mps=0.0)), t + 1)  # session boundary
    assert not os.path.exists(path)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'tests'); import test_gt7_telemetry as t; t.t_engine_session_reset_on_lap_backwards()"
```
Expected: FAIL — `AssertionError` on `has_reference is False` (no reset logic yet; the dropped-lap packet is treated as a normal lap edge and the reference survives).

- [ ] **Step 3: Add the session-boundary detection + reset to the engine**

In `src/scripts/gt7_telemetry.py`, add two methods to `TelemetryEngine` (place them just above `update`):

```python
    def _is_session_boundary(self, pkt):
        """A new session (practice->quali->race, or a restart) is signalled by the
        lap counter going backwards or the best lap clearing to -1. GT7 sends no
        explicit session-change event, so we derive it from these two signals."""
        if self._lap_num is None:
            return False
        if pkt.lap < self._lap_num:                       # lap counter went backwards
            return True
        if self._last is not None and self._last.best_ms > 0 and pkt.best_ms == -1:
            return True                                    # best lap was wiped
        return False

    def _reset_session(self, now, pkt):
        """Drop everything derived from the previous session (possibly a different
        track/car) and re-open a fresh lap at the boundary."""
        self._ref = None
        self._lap_times = []
        self._lap_fuel = []
        self._top_speed = 0.0
        self._lap_num = pkt.lap
        self._acc = _LapAccumulator(now, started_at_boundary=True)
```

Then change the head of `update` from:

```python
    def update(self, pkt, now):
        if self._lap_num is None:         # first packet: open a lap MID-lap (not a boundary)
            self._lap_num = pkt.lap
            self._acc = _LapAccumulator(now)                       # started_at_boundary=False
        elif pkt.lap != self._lap_num:    # lap-change edge: this new lap starts at the line
```

to:

```python
    def update(self, pkt, now):
        if self._lap_num is None:         # first packet: open a lap MID-lap (not a boundary)
            self._lap_num = pkt.lap
            self._acc = _LapAccumulator(now)                       # started_at_boundary=False
        elif self._is_session_boundary(pkt):   # session change: wipe stale derived state
            self._reset_session(now, pkt)
        elif pkt.lap != self._lap_num:    # lap-change edge: this new lap starts at the line
```

(The rest of `update` — the `if self._acc is not None: self._acc.add(...)`, trace, tyre, top-speed handling — is unchanged. The boundary branch consumes the event, so the `elif pkt.lap != self._lap_num` edge branch does not also fire on the same packet.)

- [ ] **Step 4: Add the store file-cleanup**

In `TelemetryStore`, change `update` from:

```python
    def update(self, pkt, now):
        with self._lock:
            had = self._eng._ref
            self._eng.update(pkt, now)
            if self._eng._ref is not had:      # a new reference lap was set
                self._save()
```

to:

```python
    def update(self, pkt, now):
        with self._lock:
            had = self._eng._ref
            self._eng.update(pkt, now)
            if self._eng._ref is not had:
                if self._eng._ref is None:     # session reset dropped the reference
                    self._remove_file()
                else:                          # a new reference lap was set
                    self._save()
```

and add `_remove_file` next to `_save`:

```python
    def _remove_file(self):
        if not self._path:
            return
        try:
            os.remove(self._path)
        except OSError:
            pass                               # best-effort, never crash the relay
```

- [ ] **Step 5: Run the four tests to verify they pass**

Run:
```bash
for n in t_engine_session_reset_on_lap_backwards t_engine_session_reset_on_best_cleared t_engine_no_reset_on_normal_lap_increment t_store_removes_file_on_session_reset; do python3 -c "import sys; sys.path.insert(0,'tests'); import test_gt7_telemetry as t; getattr(t,'$n')(); print('ok $n')"; done
```
Expected: `ok` printed for all four.

- [ ] **Step 6: Run the whole telemetry test file + lint**

Run:
```bash
python3 tests/test_gt7_telemetry.py && python3 tools/lint.py
```
Expected: `ALL PASS` from the test file; lint prints no errors.

- [ ] **Step 7: Commit**

```bash
git add src/scripts/gt7_telemetry.py tests/test_gt7_telemetry.py
git commit -m "feat(telemetry): reset derived metrics on session start (#324 follow-up)

Session boundary = lap counter backwards OR best lap cleared to -1; drops
reference/lap-time/fuel/top-speed and the persisted telemetry.json.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Pit-lap exclusion

**Files:**
- Modify: `src/scripts/gt7_telemetry.py` — new constants; `_LapAccumulator.__slots__`/`__init__`/`add`; `TelemetryEngine._finalise_lap`.
- Test: `tests/test_gt7_telemetry.py`

**Interfaces:**
- Consumes: `_LapAccumulator.add(pkt, now)` clean-driving path (post paused/loading/on-track guard), `self.fuel_start`/`self.fuel_end`, `self.elapsed`/`self.distance`; `GT7Packet.speed_mps`/`.fuel_level`. `_finalise_lap`'s existing guard chain.
- Produces: `_LapAccumulator.pit` (bool). A lap with `pit is True` is never installed as the reference and never appended to `self._lap_times` / `self._lap_fuel`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_gt7_telemetry.py`:

```python
def t_engine_pit_lap_via_standstill_excluded():
    eng = tm.TelemetryEngine()
    eng.update(tm.parse_packet(_packet(lap=0)), 99.0)
    t = 100.0
    for _ in range(80):                                   # ~8 s driving
        eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=1)), t); t += 0.1
    for _ in range(30):                                   # ~3 s stationary (pit box)
        eng.update(tm.parse_packet(_packet(speed_mps=0.0, lap=1)), t); t += 0.1
    eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=2)), t)   # lap edge
    assert eng.snapshot()["has_reference"] is False       # pit lap never became reference


def t_engine_pit_lap_via_fuel_rise_excluded():
    eng = tm.TelemetryEngine()
    eng.update(tm.parse_packet(_packet(lap=0, fuel_level=20.0)), 99.0)
    t = 100.0
    for i in range(100):                                  # fuel jumps up mid-lap = refuel
        fuel = 20.0 + (10.0 if i > 50 else 0.0)
        eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=1, fuel_level=fuel)), t); t += 0.1
    eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=2, fuel_level=30.0)), t)
    assert eng.snapshot()["has_reference"] is False


def t_engine_brief_slowdown_not_pit():
    """False-positive guard: a short (<PIT_STOP_MIN_S) slow section is not a pit lap."""
    eng = tm.TelemetryEngine()
    eng.update(tm.parse_packet(_packet(lap=0)), 99.0)
    t = 100.0
    for _ in range(80):
        eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=1)), t); t += 0.1
    for _ in range(10):                                   # ~1 s slow (hairpin), below threshold
        eng.update(tm.parse_packet(_packet(speed_mps=0.0, lap=1)), t); t += 0.1
    eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=2)), t)
    assert eng.snapshot()["has_reference"] is True        # brief stop still a valid lap
```

- [ ] **Step 2: Run to verify they fail**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'tests'); import test_gt7_telemetry as t; t.t_engine_pit_lap_via_standstill_excluded()"
```
Expected: FAIL — `has_reference` is `True` (no pit logic yet; the stopped lap still becomes the reference).

- [ ] **Step 3: Add the constants**

In `src/scripts/gt7_telemetry.py`, next to the existing `MIN_LAP_S` / `SAMPLE_MIN_DIST` block, add:

```python
# --- Pit-lap guards ---
# A pit (in/out) lap is not representative: its time is inflated by the pit-lane
# transit and the stationary service, and a refuel makes its fuel delta negative.
# GT7 sends no pit flag, so we derive one: a sustained standstill (the car must
# stop in the box for ANY service, incl. tyre-only) OR fuel rising during the lap
# (a refuel). Such a lap is excluded from the reference and the time/fuel averages.
STOPPED_SPEED_MPS = 0.5   # at/below this the car counts as stationary
PIT_STOP_MIN_S = 2.0      # cumulative standstill (s) that marks a pit lap
FUEL_RISE_L = 0.05        # litres; fuel_end above fuel_start by this = a refuel
```

- [ ] **Step 4: Extend `_LapAccumulator`**

Add `"pit"` and `"stopped_s"` to `__slots__`:

```python
    __slots__ = ("t0", "elapsed", "distance", "samples", "clean", "last_t",
                 "fuel_start", "fuel_end", "started_at_boundary", "pit", "stopped_s")
```

In `__init__`, after `self.started_at_boundary = started_at_boundary`, add:

```python
        self.pit = False
        self.stopped_s = 0.0
```

In `add`, extend the clean-driving path. It currently reads:

```python
        self.elapsed += dt
        self.distance += max(0.0, pkt.speed_mps) * dt
        if self.distance >= self.samples[-1][0] + SAMPLE_MIN_DIST:
            if len(self.samples) >= MAX_SAMPLES:
                self.clean = False        # bogus/flooded lap: cap memory, drop the lap
                return
            self.samples.append((self.distance, self.elapsed))
        if self.fuel_start is None:
            self.fuel_start = pkt.fuel_level
        self.fuel_end = pkt.fuel_level
```

Change it to:

```python
        self.elapsed += dt
        self.distance += max(0.0, pkt.speed_mps) * dt
        if pkt.speed_mps < STOPPED_SPEED_MPS:             # standstill in the pit box
            self.stopped_s += dt
            if self.stopped_s >= PIT_STOP_MIN_S:
                self.pit = True
        if self.distance >= self.samples[-1][0] + SAMPLE_MIN_DIST:
            if len(self.samples) >= MAX_SAMPLES:
                self.clean = False        # bogus/flooded lap: cap memory, drop the lap
                return
            self.samples.append((self.distance, self.elapsed))
        if self.fuel_start is None:
            self.fuel_start = pkt.fuel_level
        self.fuel_end = pkt.fuel_level
        if self.fuel_end > self.fuel_start + FUEL_RISE_L:  # refuel = pit lap
            self.pit = True
```

- [ ] **Step 5: Reject pit laps in `_finalise_lap`**

`_finalise_lap` currently starts:

```python
    def _finalise_lap(self):
        acc = self._acc
        if acc is None or not acc.clean or len(acc.samples) < 2:
            return
        # Only a lap that opened at a real lap-change edge and ran a plausible
        # minimum length counts — rejects the mid-lap-connect partial and menu/
        # out-lap blips that would otherwise poison the reference + fuel/time avgs.
        if not acc.started_at_boundary or acc.elapsed < MIN_LAP_S or acc.distance < MIN_LAP_DIST:
            return
```

Insert the pit check between the two guards:

```python
    def _finalise_lap(self):
        acc = self._acc
        if acc is None or not acc.clean or len(acc.samples) < 2:
            return
        if acc.pit:                       # in/out lap (standstill or refuel): never a
            return                        # reference, and out of the time/fuel averages
        # Only a lap that opened at a real lap-change edge and ran a plausible
        # minimum length counts — rejects the mid-lap-connect partial and menu/
        # out-lap blips that would otherwise poison the reference + fuel/time avgs.
        if not acc.started_at_boundary or acc.elapsed < MIN_LAP_S or acc.distance < MIN_LAP_DIST:
            return
```

- [ ] **Step 6: Run the three tests to verify they pass**

Run:
```bash
for n in t_engine_pit_lap_via_standstill_excluded t_engine_pit_lap_via_fuel_rise_excluded t_engine_brief_slowdown_not_pit; do python3 -c "import sys; sys.path.insert(0,'tests'); import test_gt7_telemetry as t; getattr(t,'$n')(); print('ok $n')"; done
```
Expected: `ok` for all three.

- [ ] **Step 7: Run the whole telemetry file + lint**

Run:
```bash
python3 tests/test_gt7_telemetry.py && python3 tools/lint.py
```
Expected: `ALL PASS`; lint clean. (Confirms the existing clean-lap/fuel tests still pass — no false positives.)

- [ ] **Step 8: Commit**

```bash
git add src/scripts/gt7_telemetry.py tests/test_gt7_telemetry.py
git commit -m "feat(telemetry): exclude pit laps from reference + averages (#324 follow-up)

Pit lap derived from a sustained standstill in the box (any service) or fuel
rising during the lap (refuel); such laps never seed delta/predicted/fuel.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: On-track time-of-day — parse + format (pure engine)

**Files:**
- Modify: `src/scripts/gt7_telemetry.py` — `OFF_DAY_PROGRESSION`, `GT7Packet.day_ms`, `parse_packet`, `snapshot`, new `_fmt_clock`, `format_snapshot`.
- Test: `tests/test_gt7_telemetry.py` — extend `_packet`, add tests.

**Interfaces:**
- Consumes: the decrypted packet buffer (`int32` LE at `0x80`); `snapshot()` dict; `format_snapshot(snap, units, thresholds)`.
- Produces: `GT7Packet.day_ms` (int), `snapshot()["time_of_day_ms"]` (int|None), `_fmt_clock(ms) -> str|None` (`HH:MM:SS`), `format_snapshot(...)["time_of_day"]` (str|None). Unit-independent.

- [ ] **Step 1: Extend the `_packet` test helper**

In `tests/test_gt7_telemetry.py`, inside `_packet`, after the `OFF_LAST_MS` pack line, add:

```python
    struct.pack_into("<i", b, tm.OFF_DAY_PROGRESSION, kw.get("day_ms", 0))
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_gt7_telemetry.py`:

```python
def t_parse_day_ms():
    p = tm.parse_packet(_packet(day_ms=65438716))
    assert p.day_ms == 65438716


def t_fmt_clock():
    assert tm._fmt_clock(None) is None
    assert tm._fmt_clock(0) == "00:00:00"
    assert tm._fmt_clock(65438716) == "18:10:38"                  # 65438.716 s
    assert tm._fmt_clock(90061000) == "01:01:01"                  # wraps past 24 h


def t_format_snapshot_time_of_day():
    eng = tm.TelemetryEngine()
    eng.update(tm.parse_packet(_packet(day_ms=45000000, speed_mps=10.0, lap=1)), 100.0)
    out = tm.format_snapshot(eng.snapshot(), "metric", (70, 85, 95))
    assert out["time_of_day"] == "12:30:00"                       # 45000 s


def t_format_snapshot_time_of_day_none_before_packet():
    eng = tm.TelemetryEngine()
    out = tm.format_snapshot(eng.snapshot(), "metric", (70, 85, 95))
    assert out["time_of_day"] is None
```

- [ ] **Step 3: Run to verify they fail**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'tests'); import test_gt7_telemetry as t; t.t_parse_day_ms()"
```
Expected: FAIL — `AttributeError: 'GT7Packet' object has no attribute 'day_ms'`.

- [ ] **Step 4: Add the offset + packet field + parse**

In `src/scripts/gt7_telemetry.py`, add the offset in the offsets block (after `OFF_LAST_MS`):

```python
OFF_DAY_PROGRESSION = 0x80  # time of day on track, ms since midnight (int32)
```

Add `"day_ms"` to the `GT7Packet` namedtuple field list (after `"last_ms"`):

```python
    "throttle", "brake", "lap", "best_ms", "last_ms", "day_ms",
```

In `parse_packet`, add the field in the `GT7Packet(...)` construction (after the `last_ms=` line):

```python
        day_ms=struct.unpack_from("<i", plain, OFF_DAY_PROGRESSION)[0],
```

- [ ] **Step 5: Add `_fmt_clock` and the snapshot/format fields**

Add the helper next to `_fmt_time`:

```python
def _fmt_clock(ms):
    """Format ms-since-midnight as HH:MM:SS (wrapped to 24 h). None -> None."""
    if ms is None:
        return None
    total = (int(ms) // 1000) % 86400
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"
```

In `TelemetryEngine.snapshot`, add to the returned dict (e.g. after `"top_speed_mps": self._top_speed,`):

```python
            "time_of_day_ms": pkt.day_ms if pkt else None,
```

In `format_snapshot`, add to the returned dict (e.g. after the `"has_reference"` line):

```python
        "time_of_day": _fmt_clock(snap["time_of_day_ms"]),
```

- [ ] **Step 6: Run the four tests to verify they pass**

Run:
```bash
for n in t_parse_day_ms t_fmt_clock t_format_snapshot_time_of_day t_format_snapshot_time_of_day_none_before_packet; do python3 -c "import sys; sys.path.insert(0,'tests'); import test_gt7_telemetry as t; getattr(t,'$n')(); print('ok $n')"; done
```
Expected: `ok` for all four.

- [ ] **Step 7: Run the whole telemetry file + lint**

Run:
```bash
python3 tests/test_gt7_telemetry.py && python3 tools/lint.py
```
Expected: `ALL PASS`; lint clean. (`t_parse_fields` and the format tests still pass — the new field is additive.)

- [ ] **Step 8: Commit**

```bash
git add src/scripts/gt7_telemetry.py tests/test_gt7_telemetry.py
git commit -m "feat(telemetry): parse on-track time-of-day (dayProgression @0x80) (#324 follow-up)

Adds GT7Packet.day_ms, snapshot time_of_day_ms, _fmt_clock, and the HH:MM:SS
time_of_day formatted field (unit-independent, None until first packet).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: On-track time-of-day — HUD element, builder slot, visual verify

**Files:**
- Modify: `src/obs/hud.html` — two `#tele-clock*` elements + render JS.
- Modify: `src/scripts/overlay_build.py` — `SAMPLE_CONTENT` entries.
- Modify: `tests/test_overlay.py` — update the exact slot-id list in `t_ob_extract_slots_from_real_hud`.
- Regenerate: `src/docs/wiki/images/cc-overlay-builder.png` (overlay-builder slot set changed).

**Interfaces:**
- Consumes: `format_snapshot(...)["time_of_day"]` (from Task 3), served via `GET /telemetry/data`; `extract_slots` reading `data-edit` markers from `hud.html`; `SAMPLE_CONTENT` for builder-canvas preview text.
- Produces: HUD slots `tele-clock-lbl` + `tele-clock` (both `data-edit-kind="text"`), self-hiding until `time_of_day` is non-null.

- [ ] **Step 1: Write the failing slot test**

In `tests/test_overlay.py`, update `t_ob_extract_slots_from_real_hud`: in the asserted `ids == [...]` list, insert the two new ids immediately after `"tele-top-lbl", "tele-top",` and before the `"tyres-capture", "clock"` tail. The telemetry tail becomes:

```python
                   "tele-panel", "webcam",
                   "tele-tyres", "tele-trace", "tele-delta",
                   "tele-pred-lbl", "tele-pred",
                   "tele-fuel-lbl", "tele-fuel",
                   "tele-top-lbl", "tele-top",
                   "tele-clock-lbl", "tele-clock",
                   # "tyres-capture" is a TOP-LEVEL slot (outside #tele) so it stays
                   # builder-editable in a Commentary profile that has no telemetry;
                   # it drives the "Solo Tyres/Fuel Capture" OBS device transform
                   # (Task 4, epic #300).
                   "tyres-capture", "clock"]
```

- [ ] **Step 2: Run to verify it fails**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'tests'); import test_overlay as t; t.t_ob_extract_slots_from_real_hud()"
```
Expected: FAIL — the extracted `ids` do not yet contain `tele-clock-lbl`/`tele-clock` (the assert lists them but `hud.html` has no such elements).

- [ ] **Step 3: Add the HUD elements**

In `src/obs/hud.html`, inside the telemetry `#tele` block, immediately after the `#tele-top` line (`<div id="tele-top" ...>--</div>`), add:

```html
    <div id="tele-clock-lbl" class="el" data-edit="Time of day label" data-edit-kind="text" style="display:none">TIME</div>
    <div id="tele-clock" class="el white" data-edit="Time of day" data-edit-kind="text" style="display:none">--</div>
```

- [ ] **Step 4: Add the render JS**

In `src/obs/hud.html`, in the `/telemetry/data` render function, after the `tele-top` line
(`document.getElementById("tele-top").textContent = d.top_speed + " " + d.units.speed;`), add:

```javascript
        const clock = document.getElementById("tele-clock");
        const clockLbl = document.getElementById("tele-clock-lbl");
        if (d.time_of_day) {
          clock.style.display = ""; clockLbl.style.display = "";
          clock.textContent = d.time_of_day;
        } else {
          clock.style.display = "none"; clockLbl.style.display = "none";
        }
```

- [ ] **Step 5: Add builder sample content**

In `src/scripts/overlay_build.py`, in the `SAMPLE_CONTENT` dict, after the `"tele-top": "291 km/h",` line, add:

```python
        "tele-clock-lbl": "TIME",
        "tele-clock": "18:10:38",
```

- [ ] **Step 6: Run the slot test + full overlay file + lint**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'tests'); import test_overlay as t; t.t_ob_extract_slots_from_real_hud()" \
  && python3 tests/test_overlay.py && python3 tools/lint.py
```
Expected: the single test prints nothing (passes); `test_overlay.py` prints its `ALL PASS`; lint clean.

- [ ] **Step 7: Visual-verify the HUD element (ui-visual-verification skill)**

Follow the `ui-visual-verification` skill: boot the demo relay + `tools/obs-sim.py`, feed the telemetry HUD synthetic telemetry (the feeder recipe from the #324 wiki-screenshots step), open `/hud`, and take an **element** screenshot of the telemetry block (`#tele`). `Read` the PNG and confirm the new `TIME 18:10:38` reads correctly: theme-consistent with the sibling `#tele-top`/`#tele-fuel` labels (same font/colour/size), aligned in the panel, not clipped. Fix and re-shoot if off. Then record the marker:

```bash
python3 .claude/hooks/record_ui_verified.py src/obs/hud.html
```

- [ ] **Step 8: Refresh the overlay-builder wiki image (wiki-screenshots skill)**

The builder's slot set changed, so re-capture `src/docs/wiki/images/cc-overlay-builder.png` per the `wiki-screenshots` skill (local dev build, no `VERSION`, element screenshot of the overlay-builder card matching the existing framing). Commit the regenerated PNG in this task.

- [ ] **Step 9: Full suite + build verify**

Run:
```bash
python3 tools/run-tests.py && python3 tools/build.py
```
Expected: the full suite passes with nothing disabled; `build.py` completes its verify step (tokenization, no secrets, no shell scripts, preflight present).

- [ ] **Step 10: Commit**

```bash
git add src/obs/hud.html src/scripts/overlay_build.py tests/test_overlay.py src/docs/wiki/images/cc-overlay-builder.png
git commit -m "feat(telemetry): on-track time-of-day HUD element + builder slot (#324 follow-up)

Self-gating TIME HH:MM:SS element in the POV telemetry block; builder slot +
sample content; refreshed overlay-builder wiki image.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- §A Session-start reset (lap-backwards OR best→−1; drop ref/times/fuel/top; store deletes `telemetry.json`) → **Task 1**.
- §B Pit-lap exclusion (standstill primary + fuel-rise confirmation; excluded from reference + averages; correctness-only) → **Task 2**.
- §C On-track time-of-day (`dayProgression` @0x80; `day_ms`; `time_of_day_ms`; `_fmt_clock`; `time_of_day` HH:MM:SS, unit-independent, None before first packet) → **Task 3** (parse/format) + **Task 4** (HUD element, builder slot, self-gating).
- Testing section (session reset both triggers + no-reset-on-increment + store file drop; pit via standstill + via fuel-rise + non-pit guard; time-of-day formatting + None) → covered across Tasks 1–3. Endpoint additive-key note: no test enumerates the `/telemetry/data` key set (verified), so `time_of_day` is safely additive.
- Non-goals (no timed-race prediction, no Lap X/N, no pit badge, no tyre-collapse signal) → nothing in the plan builds them.
- Deferred item (final time-of-day slot position) → Task 4 lands the default position; final placement is a post-merge builder adjustment, does not block the plan.

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N". Every code step shows complete code; every run step gives an exact command and expected output.

**Type consistency:** `_is_session_boundary(pkt)`/`_reset_session(now, pkt)`/`_remove_file()` (Task 1); `_LapAccumulator.pit`/`stopped_s` and constants `STOPPED_SPEED_MPS`/`PIT_STOP_MIN_S`/`FUEL_RISE_L` (Task 2); `OFF_DAY_PROGRESSION`/`day_ms`/`time_of_day_ms`/`_fmt_clock`/`time_of_day` (Task 3) are used consistently in Task 4's JS (`d.time_of_day`) and tests. Slot ids `tele-clock-lbl`/`tele-clock` match between `hud.html`, `SAMPLE_CONTENT`, and the `test_overlay.py` assertion.
