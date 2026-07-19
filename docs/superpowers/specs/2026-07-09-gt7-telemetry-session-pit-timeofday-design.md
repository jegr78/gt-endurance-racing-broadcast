# GT7 telemetry: session-start reset, pit-lap exclusion, on-track time-of-day

Epic: #300 (Solo mode). Extends the shipped GT7 telemetry POV HUD
(`docs/superpowers/specs/2026-07-08-gt7-telemetry-pov-hud-design.md`, issue
**#324**). All three units are **additive and POV/solo-only** — the endurance
path stays byte-identical.

## Context

The #324 telemetry engine derives a **reference lap** (the fastest clean
completed lap) and from it delta / predicted lap. Live use surfaced three gaps:

1. **A stale reference survives a session change.** When the driver leaves one
   session and starts another (practice → qualifying → race in a lobby, or a
   time-trial restart), the old reference lap — from a different session, and
   potentially a different track or car — persists, permanently poisoning
   delta/predicted until a relay restart. GT7 sends no explicit "session
   changed" event, so we must derive it.
2. **A pit lap corrupts the derived metrics.** An in/out lap (pit stop) is not a
   representative lap: its time is inflated by the pit-lane transit and the
   stationary service, and a refuel makes its fuel delta negative. If it becomes
   the reference or feeds the lap-time / fuel-burn averages, delta/predicted/fuel
   all skew. GT7 sends no pit flag, so we must derive it.
3. **A broadcast-relevant value is missing.** The POV HUD deliberately omits
   speed / gear / RPM / lap-number (GT7's own in-game HUD already shows those).
   One value that is **not** on the in-game HUD but **is** in the UDP stream is
   the **time of day on track** (as shown by EzioDash Pro) — genuinely useful in
   a day/night endurance broadcast.

## Research findings (why the approaches below)

- **No session field.** The community-standard signal for a session boundary is
  the **lap counter resetting** and/or the **best-lap time clearing to −1** (GT7
  wipes the best on every session change). Confirmed against gt7dashboard
  (`if curlap == 0` resets its session timer) and MacManley/gt7-udp. Both signals
  are already parsed by our engine.
- **No pit field — anywhere.** Even Victory Dash states its pit algorithm is
  "still being tuned." The one signal that catches **every** stop type,
  including tyre-only stops that add no fuel, is the **car coming to a sustained
  standstill while on track**: GT7 forces the car to a complete stop in the box
  for any service, and a car is never stopped for seconds during a real racing
  lap. Fuel-rise is a second, unambiguous confirmation for refuel stops.
- **No timed-race countdown in UDP.** The comprehensive parsers
  (carlos-menezes/gran-turismo-query exposes 60+ fields, MacManley, Nenkai/
  PDTools) carry **no** race-time-remaining / race-duration / timed-race
  countdown. The only time field is `dayProgression` (int32, ms) — documented as
  "current time of day on track in ms", i.e. the in-game day/night clock, **not**
  an elapsed-race or countdown value. Therefore automatic timed-race lap
  prediction is impossible, and raw "Lap X / N" (available via `lapsInRace`)
  only duplicates GT7's own HUD. Both are dropped (see Non-goals); the
  broadcast-valuable, non-duplicative field `dayProgression` is added instead.

Sources: snipem/gt7dashboard, MacManley/gt7-udp, Nenkai/PDTools,
carlos-menezes/gran-turismo-query, granturismosport.se/eziodashpro,
GTPlanet "Overview of GT7 Telemetry Software" thread.

## Decisions (agreed with the user)

- **Session reset trigger** = lap counter goes backwards **OR** best-lap clears
  to −1. A normal forward increment (e.g. 0 → 1) never triggers it.
- **Pit detection basis** = sustained standstill (primary) **or** fuel rose
  during the lap (confirmation). No tyre-temp-collapse signal (noisier, not
  needed for correctness).
- **Pit action = correctness only.** A pit lap is excluded from the reference and
  from the lap-time / fuel-burn averages. **No** HUD badge and **no** stop-type
  label.
- **Time-of-day** rendered as `HH:MM:SS` from ms-since-midnight; unit-independent
  (ignores metric/imperial). Its **HUD position is deferred** to a short visual
  discussion with the user before the feature is closed (default: a new
  positionable slot inside the telemetry panel; exact placement TBD in the
  builder).
- **Delivery = one PR** into `epic/300-solo-mode`, TDD, `run-tests.py` stays
  green with nothing disabled; endurance byte-identical.

## Architecture

Pure logic stays in the stdlib-only, unit-testable modules; the relay socket/
thread glue is unchanged. The three units touch:

- `src/scripts/gt7_telemetry.py` — parser + engine (units A, B, C).
- `src/scripts/gt7_crypto.py` — unchanged (min packet length already covers
  `0x80`).
- `src/obs/hud.html` — one new element (unit C only).
- Visual Overlay Builder slot source + compiler (unit C only).

### A. Session-start auto-reset (`gt7_telemetry.py`, engine)

`TelemetryEngine.update(pkt, now)` gains a session-boundary check evaluated
**before** the normal lap-edge handling. A boundary is detected when either:

- `self._lap_num is not None and pkt.lap < self._lap_num` — the lap counter went
  backwards (restart / new session / time-trial reset); **or**
- `self._last is not None and self._last.best_ms > 0 and pkt.best_ms == -1` — the
  best lap was cleared (GT7 wipes it on a session change).

On a boundary the engine performs a **full session reset**:

- `self._ref = None`
- `self._lap_times = []`
- `self._lap_fuel = []`
- `self._top_speed = 0.0`
- open a fresh `_LapAccumulator(now, started_at_boundary=True)` and set
  `self._lap_num = pkt.lap`

The just-reset packet is still processed normally afterwards (trace/tyre history
continue). The mid-lap-connect guard (`started_at_boundary`) and the existing
lap-length guards are unchanged; the fresh accumulator will only become a
reference once it has run a full clean lap.

Interaction with the normal lap-edge branch: the boundary check consumes the
event (it already advanced `_lap_num` and opened the accumulator), so the
existing `elif pkt.lap != self._lap_num` branch does not also fire on the same
packet.

**`TelemetryStore` file cleanup.** `TelemetryStore.update()` already saves when a
new reference appears (`self._eng._ref is not had`). Add the symmetric case: when
`had is not None and self._eng._ref is None` (a session reset dropped the
reference), delete the persisted `telemetry.json` so a later relay restart cannot
reload the stale reference. Best-effort (`os.remove` in a `try/except OSError`),
never raises.

### B. Pit-lap exclusion (`gt7_telemetry.py`, engine)

`_LapAccumulator` gains:

- a `pit` boolean (`__slots__`), default `False`;
- a `stopped_s` float accumulator (`__slots__`), default `0.0`.

New module constants:

- `STOPPED_SPEED_MPS = 0.5` — at/below this the car counts as stationary.
- `PIT_STOP_MIN_S = 2.0` — cumulative stationary time that marks a pit lap.

In `_LapAccumulator.add(pkt, now)`, within the existing "counts as clean driving"
path (not paused/loading, on track, `0 < dt <= 2.0`):

- if `pkt.speed_mps < STOPPED_SPEED_MPS`: `self.stopped_s += dt`; when
  `self.stopped_s >= PIT_STOP_MIN_S`, set `self.pit = True`.
- fuel confirmation stays where fuel is already tracked: after updating
  `fuel_start` / `fuel_end`, if `fuel_end > fuel_start + 0.05` (litres, ε against
  float noise), set `self.pit = True`.

In `TelemetryEngine._finalise_lap()`, extend the existing guard: a lap that is
`acc.pit` is **not** finalised — it never becomes the reference and is **not**
appended to `self._lap_times` or `self._lap_fuel`. (This sits alongside the
current `not acc.started_at_boundary` / `MIN_LAP_S` / `MIN_LAP_DIST` rejections;
the `if burn > 0` fuel guard is retained but a pit lap now returns before it.)

Documented edge case: a standing-start stop whose stationary time bleeds past the
lap 0 → 1 boundary can flag lap 1 as `pit`. Harmless — an out-lap should not seed
the reference or the fuel/time averages anyway.

### C. On-track time-of-day (`gt7_telemetry.py` + `hud.html`)

**Parse.** Add `OFF_DAY_PROGRESSION = 0x80` and a `day_ms` field to `GT7Packet`
(`struct.unpack_from("<i", plain, OFF_DAY_PROGRESSION)`). The offset sits inside
the range the parser already reads (throttle/brake at `0x91`/`0x92`), so no
change to `gt7_crypto.MIN_PACKET_LEN`. Pinned by the round-trip test; confirmed
live via the probe tool.

**Engine.** `snapshot()` gains `time_of_day_ms` = the latest packet's `day_ms`, or
`None` when no packet has arrived yet (mirrors how `best_s`/`delta_s` stay `None`
until available, so the HUD hides the clock rather than showing `00:00:00`). No
history, no averaging — a direct passthrough.

**Format.** `format_snapshot()` gains `time_of_day` = `HH:MM:SS` derived from
`time_of_day_ms` (ms-since-midnight, wrapped to 24 h): `total = (ms // 1000) %
86400; f"{total//3600:02d}:{total%3600//60:02d}:{total%60:02d}"`. Unit-
independent — unaffected by `units`. A pure helper `_fmt_clock(ms)` returns `None`
when `ms` is `None` (so `time_of_day` is `None` until the first packet),
unit-tested.

**HUD.** `hud.html` gains one element `#tele-clock`
(`data-edit="Time of day" data-edit-kind="text"`) plus its label
`#tele-clock-lbl` (`data-edit="Time of day label"`), rendered from
`data.time_of_day`, self-hiding via the existing `/telemetry/data` 404 probe like
the other telemetry elements. Implementation lands the slot at its default
position (inside the telemetry panel, near the fuel/top-speed block); the final
placement is a builder adjustment made after a short visual review with the user,
so it does not block the plan.

**Builder + wiki (CLAUDE.md).** The new slot is added to the builder's slot
source and the overlay compiler (same as the existing `#tele-*` slots), and the
telemetry-block wiki screenshot is regenerated and committed in the same change
(captured from a local dev build with the synthetic-telemetry feeder, per the
wiki-screenshots skill).

## Data flow (unchanged transport)

```
GT7 console --UDP:33740--> relay listener thread
  decrypt_packet -> parse_packet (now incl. day_ms)
  -> TelemetryEngine.update(pkt, now)
       session-boundary check -> full reset (ref/times/fuel/top + drop telemetry.json)
       per-lap accumulation   -> pit flag (standstill | fuel-rise)
       finalise                -> pit/short/mid-connect laps rejected
  -> TelemetryStore (snapshot incl. time_of_day_ms; -> telemetry.json)
OBS Browser Source (hud.html)
  poll GET /telemetry/data -> tyres/trace/delta/predicted/fuel/top + time_of_day
```

No new endpoints, no payload keys removed (all additions are new keys), no
transport change.

## Testing (no hardware in CI)

`tests/test_gt7_telemetry.py` (extended; timestamps injected, deterministic):

- **Session reset on lap-backwards:** feed a clean reference lap, then a packet
  whose `lap` is lower → `has_reference` returns False, `top_speed` is 0, and a
  subsequent clean lap re-establishes a fresh reference.
- **Session reset on best→−1:** an established reference plus a packet whose
  `best_ms` transitions from a real value to −1 → reference dropped.
- **No reset on normal increment:** `lap` 0 → 1 with `best_ms` unchanged keeps the
  reference and history intact.
- **Store drops the file on reset:** with a `path`, a session reset removes
  `telemetry.json` (write a ref first, assert the file exists, trigger a reset,
  assert it is gone).
- **Pit via standstill:** a lap with ≥ `PIT_STOP_MIN_S` of `speed≈0` while on
  track is excluded from the reference and from `lap_times` / `lap_fuel`.
- **Pit via fuel-rise:** a lap whose `fuel_end > fuel_start` is excluded (and does
  not appear as a negative burn either).
- **Non-pit lap unaffected:** a normal clean lap still becomes the reference and
  feeds the averages (guards against false positives).
- **Time-of-day formatting:** `_fmt_clock` maps known ms values to `HH:MM:SS`,
  wraps past 24 h, and returns `None` for `None`; `format_snapshot` surfaces
  `time_of_day`.

`tests/test_gt7_crypto.py` — unchanged (offset `0x80` is within the existing
minimum length).

Endpoint-shape tests (relay style) — `/telemetry/data` still returns the
documented shape plus the new `time_of_day` key; endurance still 404s.

`run-tests.py` stays green; **no existing test disabled**; endurance
byte-identical.

**Live validation (user, real PS5 + GT7):** the offset `0x80` for `dayProgression`
is confirmed with `tools/gt7-telemetry-probe.py` (field dump); a session change
(restart / practice→race) clears delta/predicted and they re-derive on the next
clean lap; a pit stop (with and without refuel) does not corrupt delta/predicted/
fuel; the time-of-day clock ticks and matches the in-game clock.

## Non-goals (documented, not built)

- **Timed-race lap prediction** — no race duration / countdown exists in the UDP
  stream, and an operator-entered duration was rejected (manual, easily
  forgotten). Timed races keep the existing fuel-based `laps_remaining` /
  `time_remaining`.
- **Raw "Lap X / N"** — `lapsInRace` is available but duplicates GT7's own
  in-game lap counter; no broadcast value over it.
- **Pit HUD badge / stop-type label** — correctness-only; the pit signal is used
  purely to exclude bad laps from the derived metrics.
- **Tyre-temp-collapse pit signal** — not needed once standstill + fuel-rise
  cover every stop type; would only add noise.

## Risks & caveats

- **Undocumented API / offset drift:** `dayProgression` at `0x80` is from the
  community layout; pinned by the round-trip test and confirmed by the live
  probe, consistent with the existing validated offsets (`last_ms` at `0x7C`).
- **Standstill false positives:** an on-track crash/spin that stops the car for
  ≥2 s is flagged as a pit lap and excluded from the reference/averages — which is
  the correct outcome for a non-representative lap, so the false positive is
  benign.
- **Session-reset sensitivity:** keyed on lap-backwards or best→−1; both are
  strong, low-noise signals (the lap counter never decreases mid-session and the
  best only clears on a session change), so spurious resets are not expected.

## Success criteria

`racecast --profile <solo-pov> relay run` with `RACECAST_GT7_PS_IP` set: after a
session change the reference lap and delta/predicted/top-speed reset and
re-derive on the next clean lap; a pit stop (with or without refuel) leaves
delta/predicted/fuel uncorrupted; the telemetry HUD shows a live `HH:MM:SS`
time-of-day; the full test suite stays green with nothing disabled and the
endurance path is byte-identical.
