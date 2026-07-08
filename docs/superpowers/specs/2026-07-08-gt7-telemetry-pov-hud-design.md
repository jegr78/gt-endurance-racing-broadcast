# GT7 UDP telemetry-driven POV HUD (solo mode)

Epic: #300 (Solo mode). Primary issue: **#324** (block 9/9). Builds on the
solo relay foundation (#302, see
`docs/superpowers/specs/2026-07-06-solo-relay-mode-design.md`).

## Context

In solo **POV** mode a single driver streams their own run. Unlike the
commentary use case — where the commentator spectates the online lobby and has
**no** telemetry — the POV driver's own PS4/PS5 broadcasts telemetry over GT7's
undocumented "Simulator Interface" UDP API. This feature consumes that stream on
the driver's machine and renders a live data overlay through the existing OBS
Browser Source pipeline.

Scope is deliberately **POV-only**: GT7 UDP exposes only the local car's own
telemetry (the console that answers the heartbeat). It carries **no data about
other cars or the field** — no opponent positions, no gap/delta-to-rivals. It is
**not** a replacement for the endurance multi-feed / sheet architecture.

## The data source (how it works)

- Send a heartbeat byte (`b'A'`) to `PS_IP:33739`; receive telemetry on local UDP
  port `33740`.
- The console expects a fresh heartbeat roughly every 1000 packets (~16 s); we
  send every ~10 s.
- Packets are **Salsa20-encrypted**. Key = first 32 bytes of the ASCII string
  `"Simulator Interface Packet GT7 ver 0.0"`. The nonce is derived from 4 bytes at
  offset `0x40` of the ciphertext, XORed with a per-packet-version constant
  (`0xDEADBEAF` for packet type `A`).
- After decryption the first 4 bytes are the magic `G7S0` (`0x30 0x53 0x37 0x47`);
  the rest is fixed-offset `struct` data. Update rate ~60 Hz.
- **Undocumented API** — stable historically (largely unchanged since GT6) but
  unofficial; Polyphony could change/close it in a patch. Tracked as a known
  dependency risk (see Risks).

Field offsets come from the community documentation (MacManley/gt7-udp — the
spec source); we parse only the subset the HUD needs and pin the offsets with a
round-trip test.

## Decisions (agreed with the user)

- **Transport = polling, trace batched (KISS).** The relay pushes nothing today —
  HUD/timer/chat all poll. The telemetry HUD keeps that model: `/telemetry/data`
  polled ~10 Hz for numbers, `/telemetry/trace` returns the last N ring-buffer
  samples per poll and the browser draws the throttle/brake curve smoothly from the
  batch. Raw 60 Hz is decimated to the ring buffer in the relay. No new transport,
  no long-lived connections, no new relay failure mode.
- **Crypto = pure-Python, vendored.** A ~80-LOC Salsa20 core in
  `src/scripts/gt7_crypto.py`; **no pip dependency** (the repo has none — the model
  is stdlib + external binaries, all frozen into the PyInstaller binary). Covered by
  Salsa20 test vectors + a round-trip test.
- **Delivery = one PR** into `epic/300-solo-mode`, TDD, `run-tests.py` stays green
  with nothing disabled.
- **HUD = integrated into `hud.html`, kind-gated** via a 404 self-probe (the
  telemetry endpoints exist only in solo, so the block hides itself in endurance —
  no `kind` threaded into the page).
- **Delta/predicted hidden until a valid reference lap exists.** Tyres / trace /
  fuel run immediately.
- **Units configurable per profile.** `RACECAST_TELEMETRY_UNITS=metric` (default:
  km/h, °C, L) or `imperial` (mph, °F, gal). Applies to **all** values incl. tyre
  temperature.
- **Tyre-temp thresholds** (from the issue comment; GT7 reports no optimal window):
  cold `<70 °C`, optimal `70–85 °C`, hot `>85 °C` (critical `>95 °C`). Held
  internally in **°C** (GT7-native); the band comparison is always in °C and only
  the *display* converts to °F under `imperial`, so thresholds are never maintained
  twice. `.env`-overridable (in °C).
- **`SoloHudStore` note:** issue #324 was written as "extends the planned
  `SoloHudStore`", but that store was collapsed by the sheet-always reframe (#302).
  Live 60 Hz telemetry never goes through a Google Sheet anyway, so this feature
  ships its **own** telemetry store + endpoints, independent of the sheet-driven
  `HudSource`.

## Architecture

All units are **additive and POV/solo-only**; the endurance path stays
byte-identical. Pure logic lives in stdlib-only, unit-testable modules; sockets
and threads are thin glue in the relay.

### A. `src/scripts/gt7_crypto.py` — decryption (pure, no I/O)

- `salsa20_...` core (~80 LOC, stdlib only).
- `decrypt_packet(data: bytes) -> bytes | None`: builds the key from the fixed
  ASCII string, derives the nonce from bytes at `0x40` XOR `0xDEADBEAF`, decrypts,
  validates the `G7S0` magic; returns `None` on a magic mismatch (bad/foreign
  packet) — never raises.
- Tests: published Salsa20 test vectors + an encrypt→decrypt round-trip of a known
  plaintext (so no captured packet is required to prove correctness; a real capture
  can be added opportunistically).

### B. `src/scripts/gt7_telemetry.py` — parser + engine (pure, no sockets)

- `parse_packet(decrypted: bytes) -> GT7Packet`: fixed-offset `struct` parse of the
  field subset — speed (m/s), `fuelLevel`, `fuelCapacity`, `tyreTemp[4]`
  (FL/FR/RL/RR, °C), `throttle`/`brake` (0–255), `lapCount`, `bestLapTimeMs`,
  `lastLapTimeMs`, and the `flags` bitfield (on-track / paused / loading-or-replay).
- `TelemetryEngine`: consumes parsed packets with an **injected timestamp**
  (`update(pkt, now)`, deterministic — matches the `health_store.record(now=...)`
  pattern) and maintains:
  - **Lap detection** from `lapCount` plus the on-track/paused/replay flags; menu /
    replay / paused activity never advances a lap. On a real lap change the current
    lap is finalised and accumulators reset.
  - **Distance integration** within the lap: `s += speed * Δt`.
  - **Reference lap**: the fastest *clean* completed lap, stored as a
    time-vs-distance sample array.
  - **Delta to best**: `delta = current_lap_time − reference_time(current_distance)`
    (negative = faster). Current lap time is accumulated from `Δt` (the packet has
    no current-lap-elapsed field), not read from the packet.
  - **Predicted lap**: `predicted = best_lap_time + current_delta`.
  - **Fuel**: per-lap consumption = `fuel@lap_start − fuel@lap_end`, smoothed over
    the last 2–3 laps → `laps_remaining = fuelLevel / consumption`,
    `time_remaining = laps_remaining * recent_avg_lap_time`.
  - **Input trace**: throttle/brake ring buffer (~15 s), 60 Hz decimated to ~30 Hz.
  - `has_reference` flag (false until a clean reference lap exists → the HUD hides
    delta/predicted).
- Produces `snapshot()` (numbers dict) and `trace_batch(n)` (last N samples).

### C. UDP listener thread in the relay (`src/relay/racecast-feeds.py`)

- **Solo-only**, started from `main()` when `args.solo` and telemetry is enabled.
- Binds `0.0.0.0:33740` (distinct from control 8088 and feed ports 53001–53003; the
  relay is a machine singleton so no collision). Sends the heartbeat to
  `PS_IP:33739` every ~10 s. `PS_IP` from `.env` (`RACECAST_GT7_PS_IP`); when empty,
  optional broadcast discovery (heartbeat to the subnet broadcast, learn the
  responder's address).
- Per received datagram: `decrypt_packet` → `parse_packet` → `engine.update(pkt,
  now)` → publish into the telemetry store.
- **Best-effort**, like the feed/OBS paths: any error logs to a dedicated telemetry
  logger and the thread keeps running; no console answering → the thread idles, the
  store stays empty, the relay never crashes.

### D. Telemetry store (thread-safe)

- Thin wrapper holding the latest snapshot + trace buffer + reference lap,
  persisted to `runtime/<profile>/telemetry.json` (same pattern as `timer.json`),
  so the **reference lap survives a Browser Source reload**. It resets on a relay
  restart (a fresh session).

### E. Relay endpoints (solo-gated; loopback/tailnet; NOT funnelled)

- `GET /telemetry/data` → `{tyres:{fl,fr,rl,rr}, delta, predicted, fuel:{litres,
  laps_remaining, time_remaining}, speed, current_lap, best_lap, has_reference,
  units, thresholds}`.
- `GET /telemetry/trace` → the last ~150 `{t, throttle, brake}` samples.
- Both exist **only in solo** (endurance → 404, so the HUD block self-hides —
  mirrors the broadcast-chat card contract). POV is local to the driver; there is no
  crew/console exposure, so these are never Funnel-mounted.

### F. HUD integration (`src/obs/hud.html`)

- A telemetry block that **probes `/telemetry/data`** on load: present → render the
  block; 404 → stay hidden. This *is* the kind gate (no `kind` variable in the
  page).
- Polls `/telemetry/data` (~100 ms) and `/telemetry/trace`; renders:
  1. **Tyre temps** — 4 values with colour bands (cold/optimal/hot/critical from the
     °C thresholds; display unit follows `units`).
  2. **Throttle/brake trace** — rolling `<canvas>` fed from the trace batch.
  3. **Delta to best** — hidden until `has_reference`.
  4. **Predicted lap** — hidden until `has_reference`.
  5. **Fuel** — remaining litres/gallons + laps + time.
- Elements carry `data-edit` slot markers so they are positionable in the **Visual
  Overlay Builder** like the existing HUD slots (issue sub-task 9). New slot entries
  are added to the builder's slot source + compiler.

### G. Configuration (`.env`, machine-local)

- `RACECAST_GT7_PS_IP` — PS4/PS5 IP; empty → broadcast discovery.
- `RACECAST_GT7_TELEMETRY` — master kill-switch (default on in solo; `0` disables
  the thread and the endpoints 404 → HUD block hidden).
- `RACECAST_TELEMETRY_UNITS` — `metric` (default) | `imperial`.
- `RACECAST_TELEMETRY_TYRE_COLD` / `_OPTIMAL_HI` / `_HOT_HI` — °C band edges
  (defaults 70 / 85 / 95).

## Data flow

```
GT7 console --UDP:33740--> relay listener thread
  decrypt_packet -> parse_packet -> TelemetryEngine.update(pkt, now)
  -> TelemetryStore (snapshot + trace + reference; -> telemetry.json)
OBS Browser Source (hud.html)
  poll GET /telemetry/data  (~10 Hz)  -> numbers
  poll GET /telemetry/trace (~10 Hz)  -> last N throttle/brake samples -> canvas
relay heartbeat thread --UDP:33739--> GT7 console (every ~10 s)
```

## Testing (no hardware in CI)

- `tests/test_gt7_crypto.py` — Salsa20 test vectors + encrypt→decrypt round-trip;
  magic-mismatch returns `None`.
- `tests/test_gt7_telemetry.py` — the pure engine against a **scripted packet
  sequence** (a synthetic lap: distance ramp, lap-counter increment, fuel decrement,
  flag transitions): asserts lap detection, delta vs a set reference, predicted lap,
  fuel estimate + smoothing, trace decimation, `has_reference` gating, and that
  replay/paused flags create **no** phantom laps. Timestamps are injected, so it is
  deterministic.
- Endpoint-shape tests (relay test style): a solo relay returns the documented
  `/telemetry/data` + `/telemetry/trace` shapes; endurance returns 404.
- `run-tests.py` stays green; **no existing test disabled** (endurance byte-identical).

**Live path (maintainer / user):**

- `tools/gt7-telemetry-probe.py` (standalone, not shipped — mirrors
  `tools/broadcast-chat-probe.py`): heartbeat + decrypt + parsed-field dump against a
  **real** console, no relay/sheet/UI. This is how the real path is validated.
- End-to-end verification (issue #324) is performed by the user on a real PS5 + GT7:
  drive laps, watch tyres/trace update, set a reference lap → delta/predicted appear,
  fuel populates after ≥2 laps, lap reset is correct, menu/replay makes no phantom
  laps, HUD survives a Browser Source reload.

## Wiki screenshots (CLAUDE.md)

`hud.html` gains a solo-only telemetry surface. It only renders in solo with live
data, so the shot is captured by feeding the HUD **synthetic telemetry** (a small
fake-telemetry feeder analogous to `tools/obs-sim.py`) and taking an element
screenshot of the telemetry block. The endurance `hud.html` wiki shot is unchanged
(the block stays hidden). Captured from a local dev build per the wiki-screenshots
skill.

## Risks & caveats (documented, not mitigated in code)

- **No field data:** own car only; no opponent positions, no gap-to-rivals. POV-only
  by design.
- **Fuel map not reported:** GT7 does not expose the selected fuel map; a mid-run map
  change makes consumption jump and the estimate needs ~1 lap to re-converge.
  Reliable while the map is stable.
- **Undocumented API:** historically stable but unofficial; a game patch could break
  it. Known dependency risk.
- **GPL boundary:** snipem/gt7dashboard is GPL-3.0 — concept/architecture reference
  only, **no code copied**. Crypto/struct reference from Nenkai/PDTools (MIT) and
  MacManley/gt7-udp (field docs).

## Sub-task mapping (issue #324, all in the one PR)

1. UDP listener + heartbeat → §C.
2. Salsa20 + `struct` parser → §A + §B.
3. Lap detection + per-lap finalisation → §B.
4. Distance / delta / predicted → §B.
5. Fuel consumption / remaining laps & time → §B.
6. Input-trace ring buffer → §B.
7. Telemetry store (raw + derived, reload-persistent) → §D.
8. Transport to Browser Source → §E (polling + batched trace; the agreed
   replacement for the issue's WebSocket/SSE proposal).
9. HUD layout for the five elements → §F.
10. Config (`PS_IP`, discovery, tyre thresholds, units) → §G.

## Addendum (2026-07-08): EZIO-Dash-informed additions

After reviewing the established GT7 driver dashboard **EZIO Dash**
(`granturismosport.se/eziodash`), two low-cost, broadcast-relevant values are
added to the HUD *before* merge (the packet already carries them). Speed / gear /
RPM / last-lap were deliberately **excluded** — GT7's own in-game HUD already
shows those to the driver, and a POV broadcast overlay should not duplicate them.

- **Session top speed** — the maximum `speed` seen while genuinely on track
  (`on_track and not paused`), held for the session. `snapshot()` →
  `top_speed_mps`; `data()` → `top_speed` (display unit). A `#tele-top` HUD element.
- **Tyre 30 s rolling average** per wheel, shown *alongside* the current temp
  (EZIO's "Both" default). Engine keeps a 30 s ring of tyre temps
  (`TYRE_AVG_WINDOW_S = 30.0`); `snapshot()` → `tyre_temp_avg`; each
  `data().tyres[i]` gains an `avg` (display unit). The colour **band stays driven
  by the current °C**, not the average. Rendered as a small dimmed `ø<avg>` next
  to the current value inside each existing tyre slot (no new tyre slot).

Both are additive to the payload (existing keys unchanged) and stay POV/solo-only.
Our differentiators over EZIO remain: delta-to-best + predicted lap (EZIO has
neither) and full Visual-Overlay-Builder positionability (EZIO is non-customisable).

## Success criteria

`racecast --profile <solo-pov> relay run` with `RACECAST_GT7_PS_IP` set: the
heartbeat is sent, telemetry is received and decrypted on `33740`; `/telemetry/data`
and `/telemetry/trace` respond; the `hud.html` telemetry block renders tyres + trace
live, shows delta/predicted after a reference lap, and fuel after ≥2 laps; no feed
ports are bound; the relay singleton (8088) is unaffected; the full test suite stays
green with nothing disabled.
