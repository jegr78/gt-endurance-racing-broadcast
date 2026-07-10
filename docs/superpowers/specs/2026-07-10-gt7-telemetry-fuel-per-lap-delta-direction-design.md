# GT7 Telemetry HUD: Fuel-per-lap + Delta direction

**Date:** 2026-07-10
**Status:** Approved (design)
**Extends:** `2026-07-08-gt7-telemetry-pov-hud-design.md`,
`2026-07-09-gt7-telemetry-session-pit-timeofday-design.md`

## Context & motivation

The GT7 UDP feed is single-car cockpit truth. The design principle for this overlay
(established with Jens, 2026-07-10) is: **do not duplicate GT7's own in-game HUD** —
its niche is the *temporal / strategy* layer that neither the in-game HUD (instantaneous)
nor the race director's standings (positions/gaps) show. Speed/gear/RPM/assists/mini-map
were all rejected as duplicative.

Two small, high-value additions were chosen, both derivable from data we already have:

1. **Precise fuel consumption per lap** — the in-game fuel readout is a coarse, laggy
   bar. We already compute a precise per-lap burn; surface it.
2. **Delta as a *direction*, not just a value** — the delta-to-best number already tells
   you whether you're cumulatively ahead/behind at this point in the lap; add whether that
   gap is *currently growing or shrinking*.

Both land in the existing bottom-right GT3-dash panel. The approved POV/telemetry HUD
layout (locked 2026-07-09) is otherwise untouched — no slots move; only `#tele-fuel`'s
font-size may shrink to fit.

## Feature 1 — Fuel per lap

### Engine / payload
`TelemetryEngine._fuel()` already returns `per_lap` (mean of the last ≤3 clean completed
laps' fuel burn — pit/out laps excluded, see the session-pit spec). Today `format_snapshot`
drops it. Change: surface it as `fuel.per_lap`, unit-converted like `level`
(L, or `× 0.2641720` → gal for imperial), rounded to 1 decimal. `None` when no clean lap
has completed yet.

```
fuel: { level, per_lap, laps_remaining, time_remaining }   # per_lap is new
```

### HUD (`src/obs/hud.html`)
Append per-lap as the **second** segment of the FUEL line, directly after the level:

```
FUEL
42.3L · 2.8/lap · 3 laps · 2:15
```

- English only (HUD hard rule). Segment omitted when `per_lap` is `null`, matching the
  existing optional `laps` / `time` segments.
- Order: `level · per_lap · laps · time`.
- `#tele-fuel` font-size is reduced enough that the longest realistic line (full tank,
  imperial units, all four segments present) fits the panel width with **no clipping /
  overflow**. Verified in a real render before done.

## Feature 2 — Delta direction

### Engine
On each `update(pkt, now)` where a reference lap exists and `acc.elapsed > 0`, compute the
instantaneous delta `acc.elapsed − _ref_time_at(acc.distance)` and append `(now, delta)`
to a new time-windowed deque `self._delta_hist` (window `DELTA_TREND_WINDOW_S = 1.5`,
trimmed by timestamp). The deque is **cleared** whenever a new accumulator opens
(first packet, lap-change edge, `_reset_session`) so no trend is computed across the
start/finish line or a session boundary.

`snapshot()` derives the direction:

```
diff = delta_hist[-1].delta − delta_hist[0].delta         # over the ~1.5 s window
if   diff >  DELTA_TREND_DEADBAND:  delta_dir = "up"      # gap growing → losing time now
elif diff < -DELTA_TREND_DEADBAND:  delta_dir = "down"    # gap shrinking → gaining now
else:                                delta_dir = "flat"
```

- `DELTA_TREND_DEADBAND = 0.02` (seconds) suppresses jitter.
- `delta_dir` is `None` when there is no reference or the history is too short
  (< 2 samples, i.e. the first ~1.5 s of a lap) → the HUD shows no arrow.
- Both constants are starting values, tunable live against a real stream.

### Payload
New top-level field `delta_dir ∈ {"up","down","flat"}` (or `null`) in `format_snapshot`
output, alongside the existing `delta`. `delta`'s own value/sign is unchanged.

### HUD (`src/obs/hud.html`)
`#tele-delta` (the box centred between GT7's two in-game timers) is restructured to hold
two spans: an **arrow** and the **number**.

- Arrow: `▲` (`dir == "up"`) coloured red `#ff5d5d` = losing time now; `▼` (`dir == "down"`)
  coloured green `#3ce07f` = gaining now; hidden/empty when `dir` is `"flat"` or `null`.
- Number: keeps its existing **sign** colouring — green (`#3ce07f`) when `delta < 0`
  (ahead of best), red (`#ff5d5d`) when `delta ≥ 0` (behind). **Unchanged.**
- Two independent colour channels: arrow = trend, number = standing. Examples:
  `▼ −0.12s` (ahead and extending), `▲ +0.34s` (behind and losing more),
  `▼ +0.34s` (behind but clawing back).

The whole delta widget remains hidden until a reference lap exists (unchanged).

## Testing (TDD — `tests/test_gt7_telemetry.py`)

- `format_snapshot` exposes `fuel.per_lap`; correct metric value and imperial (gal)
  conversion; `None` passes through.
- Delta direction: feed synthetic packets (injected timestamps) producing a rising delta →
  `"up"`, a falling delta → `"down"`, a change within the deadband → `"flat"`.
- `delta_hist` cleared on lap-change edge and on session boundary → no cross-boundary
  trend (first samples of the new lap yield `None`/`"flat"`).
- No reference / too-short history → `delta_dir is None`.

## Non-goals / out of scope

- No new builder slot; no slot repositioning; the locked layout is otherwise untouched.
- No new telemetry fields decoded from the packet — both features use already-derived data.
- Delta direction is not special-cased during pit/standstill laps (delta there is already
  meaningless and the widget is only interpreted on a flying lap); pre-existing behaviour.
- No change to `/telemetry/trace`, tyres, top speed, predicted, or time-of-day.

## Touched files

- `src/scripts/gt7_telemetry.py` — `_delta_hist` + constants, `update()` sampling,
  `snapshot()` `delta_dir`, `format_snapshot` `fuel.per_lap` + `delta_dir`.
- `src/obs/hud.html` — FUEL line (per-lap segment + `#tele-fuel` font-size), `#tele-delta`
  two-span arrow/number markup + render JS.
- `tests/test_gt7_telemetry.py` — the cases above.

Final step: a real HUD render for Jens's visual approval (visual-verify gate) before done.
