# GT7 telemetry: session average lap time + session distance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two session-cumulative GT7 telemetry values to the POV HUD — session average lap time and session distance — and unify all lap averaging onto the whole session (drop the 3-lap rolling window for fuel).

**Architecture:** Pure engine additions in `src/scripts/gt7_telemetry.py` (`TelemetryEngine` accumulators → `snapshot()` → `format_snapshot()`), surfaced by two read-only HUD elements in `src/obs/hud.html`. No new packet fields — both metrics are derived from data the engine already integrates.

**Tech Stack:** Python 3 stdlib only; no pytest (each `tests/test_*.py` is a runnable script, `t_*` funcs auto-run, `_`-helpers do not); HTML/CSS/vanilla JS for the HUD.

## Global Constraints

- Edit only under `src/`, `tests/`, `docs/`. Never `dist/` or `runtime/`.
- HUD text (`hud.html`) English only; render values via `textContent` (XSS-safe).
- After any `.py` change run `python3 tools/lint.py`; full suite `python3 tools/run-tests.py` green.
- One averaging model: **whole session, uncapped**, for BOTH fuel-per-lap and average lap time. No `[-3:]` window survives.
- Lap admission for the averages is unchanged: the existing `_finalise_lap` gate (clean, `started_at_boundary`, `elapsed ≥ MIN_LAP_S`, `distance ≥ MIN_LAP_DIST`, non-pit, positive fuel burn).
- Session distance counts **all** on-track distance driven, incl. pit and the mid-lap-connect first lap; resets to 0 on a session boundary.
- Units follow the existing toggle: distance in **km** (metric) / **miles** (imperial), 1 dp; lap time `M:SS.mmm` via `_fmt_time`.
- `None` average / `avg_lap` hides its HUD element; `session_distance` shows from 0.0.
- HUD placement in the locked layout is decided by a Playwright render for Jens's visual approval (Task 3) — not silently. Record the ui-visual-verify marker after.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: Engine — unify averaging + session average lap time

**Files:**
- Modify: `src/scripts/gt7_telemetry.py`
- Test: `tests/test_gt7_telemetry.py`

**Interfaces:**
- Consumes: existing `_finalise_lap` admission gate; `_LapAccumulator.elapsed/fuel_start/fuel_end`.
- Produces: `TelemetryEngine._lap_time_sum/_lap_time_n/_lap_fuel_sum/_lap_fuel_n` (running accumulators), `TelemetryEngine._avg_lap_s()` → `float|None`, `snapshot()["avg_lap_s"]` → `float|None`, `format_snapshot()["avg_lap"]` → `"M:SS.mmm"|None`. Fuel `per_lap`/`laps_remaining`/`time_remaining_s` now session-mean (same keys).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_gt7_telemetry.py` (uses the file's existing `_feed_lap(eng, t0, lap, duration, speed)` and `_packet`/`parse_packet` helpers):

```python
def t_engine_avg_lap_is_whole_session_not_last3():
    # Four clean laps of different durations: the average must be the mean of ALL
    # four, not just the last three (proves the rolling-3 window is gone).
    eng = tm.TelemetryEngine()
    eng.update(tm.parse_packet(_packet(lap=0)), 99.0)
    t = 100.0
    for lap, dur in ((1, 10.0), (2, 20.0), (3, 12.0), (4, 18.0)):
        _feed_lap(eng, t, lap, duration=dur, speed=50.0)
        t += dur
    # lap 5 edge already closed lap 4 inside _feed_lap's next call chain; read avg
    avg = eng.snapshot()["avg_lap_s"]
    assert avg is not None
    assert abs(avg - (10.0 + 20.0 + 12.0 + 18.0) / 4) < 0.5, avg   # ~15.0, not last-3 (~16.67)

def t_engine_avg_lap_none_without_laps():
    eng = tm.TelemetryEngine()
    eng.update(tm.parse_packet(_packet(lap=1, speed_mps=50.0)), 100.0)
    assert eng.snapshot()["avg_lap_s"] is None

def t_format_surfaces_avg_lap():
    snap = {"speed_mps": 0.0, "tyre_temp": (70, 70, 70, 70), "lap": 3,
            "current_lap_s": 5.0, "best_s": 90.0, "delta_s": None, "predicted_s": None,
            "has_reference": True, "tyre_temp_avg": (70.0, 70.0, 70.0, 70.0),
            "top_speed_mps": 0.0, "time_of_day_ms": None, "avg_lap_s": 92.5,
            "session_dist_m": 0.0,
            "fuel": {"level": 40.0, "per_lap": 2.5, "laps_remaining": 16.0,
                     "time_remaining_s": 1600.0}}
    out = tm.format_snapshot(snap, "metric", (70, 85, 95))
    assert out["avg_lap"] == "1:32.500"
    snap["avg_lap_s"] = None
    assert tm.format_snapshot(snap, "metric", (70, 85, 95))["avg_lap"] is None
```

Also **update** the existing pit-exclusion assertion (currently `tests/test_gt7_telemetry.py:488`):

```python
    # was: assert eng._lap_times == [] and eng._lap_fuel == []
    assert eng._lap_time_n == 0 and eng._lap_fuel_n == 0
    assert eng.snapshot()["avg_lap_s"] is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_gt7_telemetry.py`
Expected: FAIL — `avg_lap_s` KeyError / `_lap_time_n` AttributeError.

- [ ] **Step 3: Implement**

In `__init__`, replace:
```python
        self._lap_times = []      # last completed clean lap durations (s)
        self._lap_fuel = []       # last completed clean lap fuel burns (L)
```
with:
```python
        self._lap_time_sum = 0.0  # Σ admitted clean lap durations (s), whole session
        self._lap_time_n = 0
        self._lap_fuel_sum = 0.0  # Σ admitted clean lap fuel burns (L), whole session
        self._lap_fuel_n = 0
```

In `_reset_session`, replace:
```python
        self._lap_times = []
        self._lap_fuel = []
```
with:
```python
        self._lap_time_sum = 0.0
        self._lap_time_n = 0
        self._lap_fuel_sum = 0.0
        self._lap_fuel_n = 0
```

In `_finalise_lap`, replace:
```python
        self._lap_times.append(acc.elapsed)
        self._lap_times = self._lap_times[-3:]
        if acc.fuel_start is not None and acc.fuel_end is not None:
            burn = acc.fuel_start - acc.fuel_end
            if burn > 0:
                self._lap_fuel.append(burn)
                self._lap_fuel = self._lap_fuel[-3:]
```
with:
```python
        self._lap_time_sum += acc.elapsed
        self._lap_time_n += 1
        if acc.fuel_start is not None and acc.fuel_end is not None:
            burn = acc.fuel_start - acc.fuel_end
            if burn > 0:
                self._lap_fuel_sum += burn
                self._lap_fuel_n += 1
```

Add a helper (place it right above `_fuel`):
```python
    def _avg_lap_s(self):
        """Session mean of the admitted clean laps (s), or None before any lap."""
        return self._lap_time_sum / self._lap_time_n if self._lap_time_n else None
```

Replace `_fuel` body:
```python
    def _fuel(self):
        pkt = self._last
        level = pkt.fuel_level if pkt else 0.0
        per_lap = laps = time_rem = None
        if self._lap_fuel_n:
            per_lap = self._lap_fuel_sum / self._lap_fuel_n
            if per_lap > 0:
                laps = level / per_lap
                avg = self._avg_lap_s()
                if avg is not None:
                    time_rem = laps * avg
        return {"level": level, "per_lap": per_lap,
                "laps_remaining": laps, "time_remaining_s": time_rem}
```

In `snapshot()`'s returned dict, add after `"predicted_s": predicted,` line's block (any position in the dict is fine; keep near the lap fields):
```python
            "avg_lap_s": self._avg_lap_s(),
```

In `format_snapshot()`'s returned dict, add (near `"best_lap"`):
```python
        "avg_lap": _fmt_time(snap.get("avg_lap_s")),
```

- [ ] **Step 4: Run tests + lint**

Run: `python3 tests/test_gt7_telemetry.py && python3 tools/lint.py`
Expected: PASS; lint clean. (The pre-existing `t_engine_fuel_*` / `t_engine_fuel_continuous_decay` tests feed ≤3 laps, where session-mean == last-3, so they stay green.)

- [ ] **Step 5: Commit**

```bash
git add src/scripts/gt7_telemetry.py tests/test_gt7_telemetry.py
git commit -m "feat(gt7): session average lap time; unify fuel avg onto whole session"
```

---

### Task 2: Engine — session distance

**Files:**
- Modify: `src/scripts/gt7_telemetry.py`
- Test: `tests/test_gt7_telemetry.py`

**Interfaces:**
- Consumes: `_LapAccumulator.distance`; the `update()` lap-change / session-reset branches.
- Produces: `TelemetryEngine._session_dist_m` (float, metres), `snapshot()["session_dist_m"]` → float (closed laps + live lap), `format_snapshot()["session_distance"]` → float km/mi (1 dp), `format_snapshot()["units"]["distance"]` → `"km"|"mi"`.

- [ ] **Step 1: Write the failing tests**

```python
def t_engine_session_distance_accumulates_incl_pit():
    eng = tm.TelemetryEngine()
    eng.update(tm.parse_packet(_packet(lap=0)), 99.0)
    # lap 1: ~10 s @ 50 m/s ≈ 500 m
    _feed_lap(eng, 100.0, 1, duration=10.0, speed=50.0)
    d1 = eng.snapshot()["session_dist_m"]
    assert 400 < d1 < 600, d1
    # lap 2 also ~500 m -> ~1000 m total
    _feed_lap(eng, 110.0, 2, duration=10.0, speed=50.0)
    d2 = eng.snapshot()["session_dist_m"]
    assert 900 < d2 < 1100, d2
    assert d2 > d1

def t_engine_session_distance_resets_on_session_boundary():
    eng = tm.TelemetryEngine()
    eng.update(tm.parse_packet(_packet(lap=0)), 99.0)
    _feed_lap(eng, 100.0, 1, duration=10.0, speed=50.0)
    assert eng.snapshot()["session_dist_m"] > 100
    # lap counter backwards = new session
    eng.update(tm.parse_packet(_packet(lap=0, speed_mps=0.0)), 130.0)
    assert eng.snapshot()["session_dist_m"] == 0.0

def t_engine_session_distance_includes_live_lap():
    eng = tm.TelemetryEngine()
    t = 100.0
    for _ in range(100):    # ~10 s @ 50 m/s in the CURRENT (unfinished) lap
        eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=1)), t); t += 0.1
    assert eng.snapshot()["session_dist_m"] > 400   # live lap counted, no edge yet

def t_format_surfaces_session_distance():
    snap = {"speed_mps": 0.0, "tyre_temp": (70, 70, 70, 70), "lap": 2,
            "current_lap_s": 0.0, "best_s": None, "delta_s": None, "predicted_s": None,
            "has_reference": False, "tyre_temp_avg": (70.0, 70.0, 70.0, 70.0),
            "top_speed_mps": 0.0, "time_of_day_ms": None, "avg_lap_s": None,
            "session_dist_m": 2500.0,
            "fuel": {"level": 10.0, "per_lap": None, "laps_remaining": None,
                     "time_remaining_s": None}}
    out = tm.format_snapshot(snap, "metric", (70, 85, 95))
    assert out["session_distance"] == 2.5 and out["units"]["distance"] == "km"
    imp = tm.format_snapshot(snap, "imperial", (70, 85, 95))
    assert abs(imp["session_distance"] - 1.6) < 0.1 and imp["units"]["distance"] == "mi"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_gt7_telemetry.py`
Expected: FAIL — `session_dist_m` / `session_distance` KeyError.

- [ ] **Step 3: Implement**

In `__init__`, add (near the other counters):
```python
        self._session_dist_m = 0.0    # Σ on-track distance driven this session (m)
```

In `_reset_session`, add:
```python
        self._session_dist_m = 0.0
```

In `update()`, the lap-change-edge branch currently reads:
```python
        elif pkt.lap != self._lap_num:    # lap-change edge: this new lap starts at the line
            self._finalise_lap()
            self._lap_num = pkt.lap
            self._acc = _LapAccumulator(now, started_at_boundary=True)
            self._delta_hist.clear()
            if self._last is not None:    # seed the new lap's start-of-lap fuel reading
                self._acc.fuel_start = self._last.fuel_level
```
Insert the session-distance accrual right after `self._finalise_lap()` and before `self._lap_num = pkt.lap`:
```python
            self._finalise_lap()
            if self._acc is not None:     # bank the closing lap's driven distance
                self._session_dist_m += self._acc.distance
            self._lap_num = pkt.lap
```

In `snapshot()`, add to the returned dict:
```python
            "session_dist_m": self._session_dist_m + (acc.distance if acc else 0.0),
```

In `format_snapshot()`, compute before the return (near the `spd`/`lvl` locals):
```python
    dist = snap.get("session_dist_m", 0.0) * (0.000621371 if imperial else 0.001)
```
Add to the returned dict:
```python
        "session_distance": round(dist, 1),
```
And in the `"units"` sub-dict, add:
```python
            "distance": "mi" if imperial else "km",
```

- [ ] **Step 4: Run tests + lint**

Run: `python3 tests/test_gt7_telemetry.py && python3 tools/lint.py`
Expected: PASS; lint clean.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/gt7_telemetry.py tests/test_gt7_telemetry.py
git commit -m "feat(gt7): session distance metric (all on-track distance driven)"
```

---

### Task 3: HUD — average-lap + distance elements (render for Jens's visual approval)

**Files:**
- Modify: `src/obs/hud.html`

**Interfaces:**
- Consumes: `/telemetry/data` JSON `avg_lap` (string|null), `session_distance` (number), `units.distance` (string).
- Produces: two labeled HUD elements inside `#tele`, matching the existing `tele-*-lbl` / `tele-*` pattern (builder slots, `data-edit` markers).

- [ ] **Step 1: Add markup** inside the `#tele` block (`src/obs/hud.html`, after `#tele-clock`), mirroring the fuel/pred pattern:

```html
    <div id="tele-avg-lbl" class="el" data-edit="Avg lap label" data-edit-kind="text">AVG LAP</div>
    <div id="tele-avg" class="el white" data-edit="Avg lap" data-edit-kind="text" style="display:none">--</div>
    <div id="tele-dist-lbl" class="el" data-edit="Distance label" data-edit-kind="text">DISTANCE</div>
    <div id="tele-dist" class="el white" data-edit="Distance" data-edit-kind="text">--</div>
```

- [ ] **Step 2: Add CSS position rules** next to the existing `#tele-fuel{left:1522px;top:809px}` block (provisional coordinates — finalised in Step 5's render). Include the new labels in the shared `font`/`z-index` selector groups (the `#tele-pred-lbl,#tele-fuel-lbl,#tele-top-lbl` and the `z-index:1` lists) so they inherit the label font + layer:

```css
  #tele-avg-lbl{left:1522px;top:852px}
  #tele-avg{left:1522px;top:869px}
  #tele-dist-lbl{left:1522px;top:912px}
  #tele-dist{left:1522px;top:929px}
```

- [ ] **Step 3: Wire the JS** in `pollData()` (`src/obs/hud.html`), after the fuel block:

```javascript
        const avg = document.getElementById("tele-avg");
        if (d.avg_lap) {
          avg.style.display = ""; avg.textContent = d.avg_lap;
        } else {
          avg.style.display = "none";
        }
        document.getElementById("tele-dist").textContent =
          d.session_distance + " " + d.units.distance;
```

- [ ] **Step 4: Static sanity check** — serve `src/` and confirm no JS error and the elements exist:

Run: `python3 -m http.server 8099 --directory src` then open `/obs/hud.html` (values will be `--`/hidden with no relay; that is expected).

- [ ] **Step 5: Render for Jens's visual approval (ui-visual-verification)**

Boot the demo relay + obs-sim (or the Playwright render harness used for #463: mock `/telemetry/data` with representative values incl. `avg_lap`, `session_distance`, `units.distance`), screenshot the `#tele` panel at 1920×1080 1:1. Verify: both new lines fit the panel with no overflow at the longest realistic value; `AVG LAP` hides when `avg_lap` is null; `DISTANCE` shows from `0.0 km`; label font/colour match the sibling `FUEL`/`TOP SPEED` rows. **Present the render to Jens as an Artifact and get approval before marking done.** Adjust the Step-2 coordinates per his feedback and re-shoot. Then record the marker:

```bash
python3 .claude/hooks/record_ui_verified.py src/obs/hud.html
```

- [ ] **Step 6: Full suite + lint + commit**

Run: `python3 tools/run-tests.py && python3 tools/lint.py`
Expected: ALL TEST FILES PASS; lint clean.

```bash
git add src/obs/hud.html runtime/ui-visual-verified.json 2>/dev/null; git add src/obs/hud.html
git commit -m "feat(gt7): HUD session avg-lap + distance elements"
```

(The marker file under `runtime/` is gitignored; only `src/obs/hud.html` is committed.)

---

## Self-review

- **Spec coverage:** avg lap (Task 1), fuel unification (Task 1), session distance (Task 2), HUD surface (Task 3), no ambient temp (non-goal, not built). ✅
- **Type consistency:** `_avg_lap_s()` used by both `_fuel` and `snapshot`; `avg_lap_s`/`session_dist_m` keys flow snapshot→format via `snap.get` (backward-compatible with test-built snapshots). ✅
- **No placeholders:** every code step shows the exact before/after. Task 3 Step-2 coordinates are explicitly provisional, finalised by the required render. ✅
