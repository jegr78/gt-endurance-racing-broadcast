# GT7 Telemetry HUD: Fuel-per-lap + Delta direction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two strategy-layer readouts to the GT7 POV telemetry HUD — precise fuel consumption per lap, and a coloured trend arrow showing whether the delta-to-best gap is currently growing or shrinking.

**Architecture:** Both values are derived in the deterministic, unit-tested engine (`gt7_telemetry.py`), surfaced through `format_snapshot`, and only *rendered* by `hud.html`. Fuel-per-lap already exists in the raw snapshot; the delta trend is a new short time-windowed history in the engine. No new packet fields are decoded; the locked HUD layout is untouched except `#tele-fuel`'s font-size.

**Tech Stack:** Python 3 stdlib only (no pytest — each test file is a runnable script with `t_`-prefixed functions), vanilla HTML/CSS/JS in a single relay-served page.

## Global Constraints

- **Edit only under `src/`, `tests/`, `docs/`.** `dist/`/`runtime/` are generated — never touch.
- **HUD text is English only** (no German in `hud.html`).
- **Tests: stdlib only, no pytest.** Functions are named `t_*` and auto-run by the file's `__main__` loop. Run the file with `python3 tests/test_gt7_telemetry.py`. Helpers start with `_` so they are not auto-run.
- **Run `python3 tools/lint.py` after any Python change** (the CI lint job).
- **Delta trend constants** (verbatim): `DELTA_TREND_WINDOW_S = 1.5`, `DELTA_TREND_DEADBAND = 0.02`.
- **Colours** (verbatim): gaining/ahead green `#3ce07f`, losing/behind red `#ff5d5d`.
- **Arrow glyphs** (verbatim): up `▲` = losing time now, down `▼` = gaining now.
- **Fuel line segment order** (verbatim): `level · per_lap · laps · time`; per-lap label `/lap`.
- No secrets, no machine paths, no real IPs anywhere.
- The HUD overlay is NOT a wiki-screenshot surface (that rule covers Control Center / Director Panel / Companion only) — no wiki image to refresh. A real HUD render for Jens's visual approval IS required before done.

---

### Task 1: Engine — delta trend history + `delta_dir` in snapshot

**Files:**
- Modify: `src/scripts/gt7_telemetry.py` (constants ~line 42; `TelemetryEngine.__init__` ~line 161; `_reset_session` ~line 185; `update` ~line 195; `snapshot` ~line 287)
- Modify: `tests/test_gt7_telemetry.py` (add helper + tests)
- Also commit: `docs/superpowers/specs/2026-07-10-gt7-telemetry-fuel-per-lap-delta-direction-design.md` (the approved spec, committed with the first code)

**Interfaces:**
- Consumes: existing `TelemetryEngine._ref`, `_ref_time_at(distance)`, `_acc` (`.elapsed`, `.distance`), `snapshot()`.
- Produces: `snapshot()` returns a new key `"delta_dir"` with value `"up" | "down" | "flat" | None`. Module constants `DELTA_TREND_WINDOW_S`, `DELTA_TREND_DEADBAND`.

- [ ] **Step 1: Write the failing tests**

Add this helper and five tests to `tests/test_gt7_telemetry.py` (anywhere among the other `t_*` functions, e.g. after `t_engine_delta_negative_when_faster`):

```python
def _ref_then_partial(speed2, secs=3.0):
    """Set a 50 m/s reference lap, then drive `secs` of lap 2 at speed2 m/s.
    Returns (engine, next_free_timestamp)."""
    eng = tm.TelemetryEngine()
    eng.update(tm.parse_packet(_packet(lap=0)), 99.0)          # mid-connect partial (discarded)
    _feed_lap(eng, 100.0, 1, duration=10.0, speed=50.0)         # reference ~10 s / 500 m
    t = 120.0
    for _ in range(int(secs / 0.1)):
        eng.update(tm.parse_packet(_packet(speed_mps=speed2, lap=2)), t); t += 0.1
    return eng, t


def t_engine_delta_dir_down_when_gaining():
    eng, _ = _ref_then_partial(100.0)      # faster than the 50 m/s reference -> gap shrinking
    assert eng.snapshot()["delta_dir"] == "down"


def t_engine_delta_dir_up_when_losing():
    eng, _ = _ref_then_partial(40.0)       # slower than reference -> gap growing
    assert eng.snapshot()["delta_dir"] == "up"


def t_engine_delta_dir_flat_when_matching():
    eng, _ = _ref_then_partial(50.0)       # matching reference pace -> within deadband
    assert eng.snapshot()["delta_dir"] == "flat"


def t_engine_delta_dir_none_without_reference():
    eng = tm.TelemetryEngine()
    eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=1)), 100.0)
    assert eng.snapshot()["delta_dir"] is None


def t_engine_delta_dir_cleared_on_lap_edge():
    """The trend history must not carry across the start/finish line: right after a
    lap-change edge there are <2 samples, so delta_dir is None (no phantom trend)."""
    eng, t = _ref_then_partial(40.0)       # building an "up" trend on lap 2
    assert eng.snapshot()["delta_dir"] == "up"
    eng.update(tm.parse_packet(_packet(speed_mps=40.0, lap=3)), t)   # lap edge -> history cleared
    assert eng.snapshot()["delta_dir"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'tests'); import test_gt7_telemetry as t; t.t_engine_delta_dir_down_when_gaining()"
```
Expected: FAIL with `KeyError: 'delta_dir'` (the key does not exist yet).

- [ ] **Step 3: Add the module constants**

In `src/scripts/gt7_telemetry.py`, directly after the tyre-average window block (the `TYRE_AVG_WINDOW_S = 30.0` lines, ~line 42), add:

```python
# --- Delta trend (which way the gap to best is moving) ---
DELTA_TREND_WINDOW_S = 1.5    # compare current delta vs this-many-seconds-ago
DELTA_TREND_DEADBAND = 0.02   # s; |change| below this reads as "flat" (anti-jitter)
```

- [ ] **Step 4: Add the history deque to `__init__`**

In `TelemetryEngine.__init__`, after the `self._top_speed = 0.0` line, add:

```python
        self._delta_hist = deque()    # (t, delta) over DELTA_TREND_WINDOW_S; cleared per lap
```

- [ ] **Step 5: Clear the history when a new lap/session opens**

In `_reset_session`, after `self._top_speed = 0.0`, add:

```python
        self._delta_hist.clear()
```

In `update`, inside the lap-change-edge branch (`elif pkt.lap != self._lap_num:`), after the `self._acc = _LapAccumulator(now, started_at_boundary=True)` line, add:

```python
            self._delta_hist.clear()
```

- [ ] **Step 6: Sample the delta at the end of `update`**

In `update`, immediately after the tyre-history trim loop (the `while self._tyre_hist and self._tyre_hist[0][0] < tcut:` / `self._tyre_hist.popleft()` block at the end of the method), add:

```python
        if self._ref is not None and self._acc is not None and self._acc.elapsed > 0:
            d = self._acc.elapsed - self._ref_time_at(self._acc.distance)
            self._delta_hist.append((now, d))
            dcut = now - DELTA_TREND_WINDOW_S
            while self._delta_hist and self._delta_hist[0][0] < dcut:
                self._delta_hist.popleft()
```

- [ ] **Step 7: Derive `delta_dir` in `snapshot`**

In `snapshot`, after the `if has_ref:` block that sets `delta`/`predicted`/`best` (right before the `return {` statement), add:

```python
        delta_dir = None
        if has_ref and len(self._delta_hist) >= 2:
            diff = self._delta_hist[-1][1] - self._delta_hist[0][1]
            if diff > DELTA_TREND_DEADBAND:
                delta_dir = "up"        # gap growing -> losing time now
            elif diff < -DELTA_TREND_DEADBAND:
                delta_dir = "down"      # gap shrinking -> gaining now
            else:
                delta_dir = "flat"
```

Then add this line to the dict returned by `snapshot` (e.g. right after `"delta_s": delta,`):

```python
            "delta_dir": delta_dir,
```

- [ ] **Step 8: Run the tests to verify they pass**

Run:
```bash
python3 tests/test_gt7_telemetry.py
```
Expected: `ALL PASS` (the five new `t_engine_delta_dir_*` tests print `ok ...`, and every pre-existing test still passes).

- [ ] **Step 9: Lint**

Run:
```bash
python3 tools/lint.py
```
Expected: no errors.

- [ ] **Step 10: Commit**

```bash
git add src/scripts/gt7_telemetry.py tests/test_gt7_telemetry.py docs/superpowers/specs/2026-07-10-gt7-telemetry-fuel-per-lap-delta-direction-design.md
git commit -m "feat(gt7): delta trend direction (up/down/flat) in telemetry engine"
```

---

### Task 2: `format_snapshot` — surface `fuel.per_lap` + `delta_dir`

**Files:**
- Modify: `src/scripts/gt7_telemetry.py` (`format_snapshot`, ~line 344-377)
- Modify: `tests/test_gt7_telemetry.py` (add two tests)

**Interfaces:**
- Consumes: the raw snapshot dict — `snap["fuel"]["per_lap"]` (litres/lap or `None`) and `snap.get("delta_dir")` from Task 1.
- Produces: `format_snapshot(...)` output gains `out["fuel"]["per_lap"]` (unit-converted, rounded to 1 dp, or `None`) and top-level `out["delta_dir"]` (`"up"|"down"|"flat"|None`).

- [ ] **Step 1: Write the failing tests**

Add these two tests to `tests/test_gt7_telemetry.py`:

```python
def t_format_surfaces_fuel_per_lap_and_delta_dir():
    snap = {"speed_mps": 0.0, "tyre_temp": (70.0, 70.0, 70.0, 70.0),
            "tyre_temp_avg": (70.0, 70.0, 70.0, 70.0), "top_speed_mps": 0.0,
            "lap": 1, "current_lap_s": 0.0, "best_s": 90.0,
            "delta_s": 0.5, "predicted_s": 90.5, "has_reference": True,
            "time_of_day_ms": None, "delta_dir": "up",
            "fuel": {"level": 40.0, "per_lap": 2.5, "laps_remaining": 16.0,
                     "time_remaining_s": 1600.0}}
    out = tm.format_snapshot(snap, "metric", (70, 85, 95))
    assert out["fuel"]["per_lap"] == 2.5
    assert out["delta_dir"] == "up"
    imp = tm.format_snapshot(snap, "imperial", (70, 85, 95))
    assert imp["fuel"]["per_lap"] == 0.7        # 2.5 L -> 0.66 gal -> 0.7
    assert imp["delta_dir"] == "up"


def t_format_delta_dir_and_per_lap_default_none():
    """format_snapshot tolerates a snapshot with no delta_dir and null per_lap."""
    snap = {"speed_mps": 0.0, "tyre_temp": (70.0, 70.0, 70.0, 70.0),
            "tyre_temp_avg": (70.0, 70.0, 70.0, 70.0), "top_speed_mps": 0.0,
            "lap": 1, "current_lap_s": 0.0, "best_s": None,
            "delta_s": None, "predicted_s": None, "has_reference": False,
            "time_of_day_ms": None,
            "fuel": {"level": 10.0, "per_lap": None, "laps_remaining": None,
                     "time_remaining_s": None}}
    out = tm.format_snapshot(snap, "metric", (70, 85, 95))
    assert out["delta_dir"] is None
    assert out["fuel"]["per_lap"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'tests'); import test_gt7_telemetry as t; t.t_format_surfaces_fuel_per_lap_and_delta_dir()"
```
Expected: FAIL with `KeyError: 'per_lap'` (the formatted fuel dict has no `per_lap` yet).

- [ ] **Step 3: Add `per_lap` to the formatted fuel dict and `delta_dir` top-level**

In `format_snapshot`, replace the `"fuel": { ... }` sub-dict with (adds the `per_lap` line — same gal conversion as `level`):

```python
        "fuel": {
            "level": round(lvl, 1),
            "per_lap": (None if fuel["per_lap"] is None
                        else round(fuel["per_lap"] * (0.2641720 if imperial else 1.0), 1)),
            "laps_remaining": (None if fuel["laps_remaining"] is None
                               else round(fuel["laps_remaining"], 1)),
            "time_remaining": _fmt_time(fuel["time_remaining_s"]),
        },
```

And add this line to the returned dict, immediately after the `"delta": ...` line:

```python
        "delta_dir": snap.get("delta_dir"),
```

(`snap.get` — not `snap[...]` — so callers that build a snapshot without the key never `KeyError`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
python3 tests/test_gt7_telemetry.py
```
Expected: `ALL PASS`.

- [ ] **Step 5: Run the wider telemetry suites (additive shape check)**

Run:
```bash
python3 tests/test_telemetry_endpoints.py && python3 tests/test_telemetry_flag.py
```
Expected: both print their pass banner. Adding keys is additive; if either asserts an exact key set and fails, update that assertion to include `per_lap` / `delta_dir` and re-run.

- [ ] **Step 6: Lint**

Run:
```bash
python3 tools/lint.py
```
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/scripts/gt7_telemetry.py tests/test_gt7_telemetry.py
git commit -m "feat(gt7): surface fuel per-lap + delta_dir in format_snapshot payload"
```

---

### Task 3: HUD — FUEL line per-lap segment + delta trend arrow

**Files:**
- Modify: `src/obs/hud.html` (`#tele-delta` markup ~line 285; `#tele-fuel` CSS ~line 122; the tele render JS ~line 414-428)

**Interfaces:**
- Consumes: the telemetry payload `d` (already polled by the tele block) — new fields `d.delta_dir` and `d.fuel.per_lap` from Task 2.
- Produces: no code interface; a rendered HUD.

- [ ] **Step 1: Split `#tele-delta` into arrow + value spans**

Replace the `#tele-delta` element (currently `<div id="tele-delta" ... style="display:none">--</div>`) with:

```html
    <div id="tele-delta" class="el white" data-edit="Delta to best" data-edit-kind="text" style="display:none"><span id="tele-delta-arrow"></span><span id="tele-delta-val">--</span></div>
```

- [ ] **Step 2: Reduce the FUEL value font-size for the 4th segment**

In the CSS, change the `#tele-fuel` rule from `font-size:23px` to `font-size:18px`:

```css
  #tele-fuel{left:1522px;top:809px;font-size:18px}
```

(Starting value; Step 6 verifies the longest realistic line does not overflow the panel and adjusts if needed.)

- [ ] **Step 3: Render the delta arrow + coloured value**

In the tele render JS, replace the current delta block:

```javascript
        const delta = document.getElementById("tele-delta");
        const pred = document.getElementById("tele-pred");
        if (d.has_reference && d.delta !== null) {
          delta.style.display = ""; pred.style.display = "";
          delta.textContent = (d.delta >= 0 ? "+" : "") + d.delta.toFixed(2) + "s";
          delta.style.color = d.delta < 0 ? "#3ce07f" : "#ff5d5d";
          pred.textContent = d.predicted || "--";
        } else {
          delta.style.display = "none"; pred.style.display = "none";
        }
```

with:

```javascript
        const delta = document.getElementById("tele-delta");
        const dArrow = document.getElementById("tele-delta-arrow");
        const dVal = document.getElementById("tele-delta-val");
        const pred = document.getElementById("tele-pred");
        if (d.has_reference && d.delta !== null) {
          delta.style.display = ""; pred.style.display = "";
          dVal.textContent = (d.delta >= 0 ? "+" : "") + d.delta.toFixed(2) + "s";
          dVal.style.color = d.delta < 0 ? "#3ce07f" : "#ff5d5d";   // sign = ahead/behind
          if (d.delta_dir === "up") {
            dArrow.textContent = "▲ ";        // gap growing -> losing now
            dArrow.style.color = "#ff5d5d";
          } else if (d.delta_dir === "down") {
            dArrow.textContent = "▼ ";        // gap shrinking -> gaining now
            dArrow.style.color = "#3ce07f";
          } else {
            dArrow.textContent = "";               // flat / unknown: no arrow
          }
          pred.textContent = d.predicted || "--";
        } else {
          delta.style.display = "none"; pred.style.display = "none";
        }
```

- [ ] **Step 4: Add the fuel per-lap segment**

In the same render function, replace the fuel block:

```javascript
        const f = d.fuel;
        document.getElementById("tele-fuel").textContent =
          f.level + d.units.fuel +
          (f.laps_remaining !== null ? " · " + f.laps_remaining + " laps" : "") +
          (f.time_remaining ? " · " + f.time_remaining : "");
```

with (per-lap is the 2nd segment, after level):

```javascript
        const f = d.fuel;
        document.getElementById("tele-fuel").textContent =
          f.level + d.units.fuel +
          (f.per_lap !== null && f.per_lap !== undefined ? " · " + f.per_lap + "/lap" : "") +
          (f.laps_remaining !== null ? " · " + f.laps_remaining + " laps" : "") +
          (f.time_remaining ? " · " + f.time_remaining : "");
```

- [ ] **Step 5: Sanity-check the page loads (no JS syntax error)**

Run a quick static check that the file still parses as HTML and the two new element ids are present:

```bash
python3 -c "d=open('src/obs/hud.html').read(); assert 'tele-delta-arrow' in d and 'tele-delta-val' in d and '/lap' in d; print('markup ok')"
```
Expected: `markup ok`.

- [ ] **Step 6: Render the HUD and verify no overflow (visual)**

Bring up a local dev build serving `/hud` with telemetry fake content (per the `wiki-screenshots` skill recipe: `demo` profile + `tools/obs-sim.py`, or the telemetry probe fixture) and confirm on a real 1920×1080 render:
- FUEL line shows `level · X.X/lap · N laps · M:SS` with **no clipping / overflow** past the panel; if it clips, drop `#tele-fuel` font-size by 1px and re-render until it fits.
- Delta shows a red `▲` when losing / green `▼` when gaining, to the left of the sign-coloured number; no arrow when flat.

- [ ] **Step 7: Commit**

```bash
git add src/obs/hud.html
git commit -m "feat(gt7): HUD fuel-per-lap segment + delta trend arrow"
```

---

### Task 4: Full suite, lint, and visual approval gate

**Files:** none (verification only).

- [ ] **Step 1: Run the whole test suite (exactly what CI runs)**

Run:
```bash
python3 tools/run-tests.py
```
Expected: all tests pass. If a telemetry-shape assertion elsewhere fails, fix it to accept the additive `per_lap` / `delta_dir` keys and re-run.

- [ ] **Step 2: Lint the whole tree**

Run:
```bash
python3 tools/lint.py
```
Expected: no errors.

- [ ] **Step 3: Produce a render for Jens's visual approval**

Following the memory `ui-visual-verify-gate-and-skill` + `hud-design-needs-visual-dialog`: capture the telemetry HUD render (fuel line with per-lap + a losing `▲` and a gaining `▼` delta example) and present it to Jens as an Artifact for approval. Do NOT mark the feature done until he approves. Fold any layout feedback (font-size, arrow spacing) back into `src/obs/hud.html` and re-render.

- [ ] **Step 4: (On approval) confirm the branch is clean**

Run:
```bash
git status
```
Expected: clean working tree; the three feature commits (+ spec) present on the branch.

---

## Self-Review

- **Spec coverage:** Feature 1 fuel-per-lap → Task 2 (payload) + Task 3 (HUD). Feature 2 delta direction: engine trend → Task 1, payload → Task 2, HUD arrow → Task 3. Tests → Tasks 1-2 (engine/format) + Task 4 (full suite). Visual gate → Task 4. Non-goals (no new slots, no new packet fields, no pit special-casing) respected — no task adds any.
- **Placeholder scan:** none — every code step shows the exact code; the only "adjust" is the font-size render loop, which has a concrete start value (18px) and a concrete adjust rule (−1px until it fits).
- **Type consistency:** `delta_dir` is `"up"|"down"|"flat"|None` in engine (Task 1), passed through with `snap.get("delta_dir")` (Task 2), read as `d.delta_dir` in JS (Task 3). `fuel.per_lap` is litres/lap `float|None` in the raw snapshot, converted+rounded in Task 2, read as `d.fuel.per_lap` in Task 3. Glyphs/colours match the Global Constraints verbatim.
