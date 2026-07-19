# GT7 telemetry: session average lap time + session distance — design

**Status:** approved (Jens, 2026-07-10)
**Branch:** feat/gt7-session-metrics (off epic/300-solo-mode)
**Builds on:** the derived-metrics engine in `src/scripts/gt7_telemetry.py`
(POV/telemetry HUD; last shipped #463 fuel-per-lap + delta direction).

## Goal

Add two session-cumulative telemetry values to the GT7 POV HUD — the overlay's
niche (the temporal/strategy layer the in-game HUD does not show):

1. **Session average lap time** — the mean of every clean, completed, non-pit lap
   of the current session.
2. **Session distance** — the total on-track distance actually driven this session.

And, per Jens's decision, **unify the averaging model**: drop the existing 3-lap
rolling window used for fuel; both fuel-per-lap **and** the new average lap time
are now computed over the **whole session** (all admitted laps). One averaging
model for everything.

## Non-goals / hard constraints

- **Ambient / track / air temperature is NOT added** — it is not present in the
  GT7 UDP packet (only water/oil — both constant sim values — and tyre surface
  temp). Confirmed against the reverse-engineered packet-format reference
  (MacManley/gt7-udp). We do not synthesise environment data.
- No new packet fields are decoded. Both metrics are **derived** from data the
  engine already integrates (per-lap distance via `speed·Δt`; lap admission via
  `_finalise_lap`).
- These are session metrics: they are **not persisted**. `TelemetryStore`
  persists only the reference lap, so both reset on relay restart (a new relay
  session = a new session) — correct and intended.
- HUD placement in the locked POV/telemetry layout is **not decided in this
  spec**. A rendered proposal goes to Jens for visual approval during
  implementation (per `hud-design-needs-visual-dialog`,
  `pov-telemetry-hud-layout-locked`, `dont-decide-editability-scope-silently`).

## Behaviour

### Averaging model change (fuel unification)

Today `_finalise_lap` appends to `self._lap_times` and `self._lap_fuel`, each
capped to the last 3 (`[-3:]`), and `_fuel()` averages those capped lists.

**New model:** replace the two capped lists with four running accumulators on the
engine:

- `self._lap_time_sum` (float, seconds) + `self._lap_time_n` (int)
- `self._lap_fuel_sum` (float, litres) + `self._lap_fuel_n` (int)

`_finalise_lap` adds an admitted lap's `elapsed` to the time accumulator, and its
positive fuel burn to the fuel accumulator (same admission gate as today: clean,
started-at-boundary, ≥ `MIN_LAP_S` / `MIN_LAP_DIST`, non-pit, positive burn).
`_reset_session` zeroes all four. No cap.

`avg_lap_s = _lap_time_sum / _lap_time_n` when `_lap_time_n > 0`, else `None`.
`per_lap = _lap_fuel_sum / _lap_fuel_n` when `_lap_fuel_n > 0`, else `None`.
`laps_remaining` / `time_remaining_s` are unchanged in formula but now consume the
session `per_lap` and session `avg_lap_s` (DRY: `time_remaining_s = laps_remaining
· avg_lap_s`). This is a **behaviour change** to the (unreleased, epic-branch)
`per_lap` / `laps_remaining` / `time_remaining` values: rolling-3 → session mean.

### Session distance

A single running accumulator `self._session_dist_m` (float, metres), zeroed in
`__init__` and `_reset_session`.

- When a lap closes at a **lap-change edge** (the `pkt.lap != self._lap_num`
  branch of `update`), add the closing accumulator's `.distance` to
  `_session_dist_m` **before** opening the new accumulator — unconditionally
  (pit laps and the mid-lap-connect first lap count: their distance was really
  driven; the accumulator already skips paused/loading/off-track, so no menu
  fake distance is added).
- On a **session boundary**, `_reset_session` resets `_session_dist_m = 0.0` (the
  closing lap belonged to the previous session — discarded).
- `snapshot()` returns `session_dist_m = self._session_dist_m + (acc.distance if
  acc else 0.0)` — the closed laps plus the live in-progress lap.

### Snapshot / format additions

`snapshot()` gains two keys:
- `avg_lap_s`: float seconds or `None`.
- `session_dist_m`: float metres (always present; 0.0 before any driving).

`format_snapshot()` gains two keys:
- `avg_lap`: `_fmt_time(avg_lap_s)` (`M:SS.mmm`, or `None` → HUD hides it).
- `session_distance`: rounded to 1 dp, in **km** (metric) or **miles**
  (imperial: `m · 0.000621371`; metric: `m / 1000`). Unit label added to the
  existing `units` block as `"distance": "mi" | "km"`.

### HUD (`src/obs/hud.html`)

Two new read-only elements (`textContent` only), fed from `/telemetry/data`.
Placement + styling delivered as a Playwright render for Jens's visual approval
before the feature is marked done. `avg_lap === null` hides its element;
`session_distance` shows from 0.0.

## Testing

Pure engine + format functions, stdlib `t_*` tests in
`tests/test_gt7_telemetry.py`:

- Session average over >3 laps ≠ last-3 (proves the window is gone): feed laps of
  different durations and assert the mean is the all-lap mean.
- Session average excludes pit / partial / unclean laps (same gate as reference).
- Fuel `per_lap` now session-mean over >3 laps (update the model, not a new gate).
- Update `t_engine_pit_lap_via_standstill_excluded` (line ~488): it asserts the
  internal `_lap_times == [] and _lap_fuel == []`; switch to the new accumulators
  (`_lap_time_n == 0 and _lap_fuel_n == 0`) or assert `snapshot()["avg_lap_s"] is
  None`.
- Session distance accumulates across laps incl. a pit lap; resets to 0 on session
  boundary; `snapshot` includes the live current-lap distance.
- `format_snapshot` surfaces `avg_lap` (metric M:SS.mmm; `None` → `None`) and
  `session_distance` (metric km, imperial miles, 1 dp) + the `distance` unit label.

`tools/run-tests.py` green; `tools/lint.py` clean. HUD is not a wiki-screenshot
surface → no wiki image, but the visual-verify marker is recorded after the render.

## Files

- `src/scripts/gt7_telemetry.py` — engine accumulators + snapshot/format keys.
- `tests/test_gt7_telemetry.py` — new + updated tests.
- `src/obs/hud.html` — two HUD elements (placement per Jens visual approval).
- `docs/superpowers/specs|plans/2026-07-10-gt7-telemetry-session-avg-distance*` —
  this spec + the plan.
