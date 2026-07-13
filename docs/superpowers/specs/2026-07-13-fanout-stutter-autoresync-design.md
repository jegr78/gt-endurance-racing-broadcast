# Fan-out stutter: detection-driven auto-resync + graduated stall handling (#488)

**Date:** 2026-07-13
**Issue:** [#488](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/488)
**Scope:** `src/relay/racecast-feeds.py` (the fan-out `FeedRing` / `FeedFanoutServer` /
byte-stall watchdog / `Feed` serve loop), a new pure `tests/test_fanout.py`, and a new
maintainer soak tool under `tools/`. Machine-level `.env` flags. Single PR into `main`.

## Problem

During long broadcasts the program develops a visible **stutter/lag** that a Director-Panel
**"OBS Feed Reset"** clears every time. Reproduced across N24 event days (AWS cloud box,
v1.5.5). The post-event report proved the stutter is **100% ingest/source-side** — OBS
output was flawless (0% dropped, 60 fps, 0 congestion) — so the mispacing is in the
**source → relay ring → OBS-ffmpeg** path, never the encode/output.

Two distinct triggers, same fix family:

- **Trigger A — OBS-consumption drift.** The fan-out `FeedRing` has **no consumer
  backpressure**: the live reader (streamlink → ring) always appends and overflows the
  oldest bytes. Over a long session OBS's ffmpeg media-source consumption clock drifts
  against the live-edge, its socket backs up, and the ring eventually overflows past OBS's
  cursor → the cursor is snapped forward → OBS loses bytes → ffmpeg discontinuity = the
  visible glitch. **Interval is variable/unpredictable** (recurred within ~10 min once,
  ~90 min another) → no time-based trigger. A media-source rebuild resets OBS's demuxer at
  the live edge and clears it — reliably, every time, on both feeds.

- **Trigger B — the 8 s byte-stall watchdog amplifies a flaky source.** A commentator
  producing from a **PlayStation over WiFi** (a normal, recurring condition — jittery
  wireless + console encoder) periodically stalls the live edge. The relay's watchdog
  treats any > 8 s byte gap as a dead reader and forces a **full yt-dlp re-resolve**,
  whose teardown makes the visible gap *larger* than the underlying micro-stall; repeated
  cycles read as continuous stutter. streamlink already retries HLS segments internally, so
  the re-resolve is often premature.

## What already exists (so we don't rebuild it)

- **The proven reset primitive:** `Feed._obs_reconnect()` → `obs_ws.release_feed_inputs([port])`
  re-applies the feed input's own settings (`SetInputSettings`), a forced source rebuild
  that drops OBS's socket so it re-joins the fan-out at the live edge with a clean demuxer.
  This is exactly what the manual "OBS Feed Reset" button and the drop-recovery
  `on_first_byte` hook already call. Best-effort, threaded, never crashes the serve.
- **The ring already tracks absolute offsets:** `FeedRing.live_offset()` = `_base + len(_buf)`;
  each consumer carries its own `cursor`. The cursor-snap (`if cursor < self._base`) is the
  exact data-loss event.
- **The byte-stall watchdog** (`_serve_fanout` inner `_watchdog`, `feed_stalled`,
  `FANOUT_STALL_S = 8.0`) already detects a stall; today it kills unconditionally at 8 s.
- **The reader stamps `last_byte_ts`** on every block — a rolling bitrate (B/s) is free from it.

## Design

### Component 1 — Detection-driven auto-resync (Trigger A)

**Signal — OBS's byte-lag behind the live edge.** For the OBS socket consumer,
`lag_bytes = live_offset() − obs_cursor`. Because `FeedFanoutServer._serve` does a
**blocking `sendall`**, `obs_cursor` only advances when OBS's TCP socket accepts bytes:
- OBS keeping up → cursor tracks live, `lag` stays small/constant.
- OBS drifting (ffmpeg plays slower than ingest → its demux buffer fills → it stops reading
  the socket → `sendall` blocks) → `live_offset` races ahead, `obs_cursor` stalls → `lag`
  grows monotonically. **This growing lag is the drift.**
- Extreme → `lag` > ring capacity → cursor snapped forward → the glitch (definitive backstop).

**Two sub-signals from one measurement** (a light per-feed sampler folded into the existing
watchdog thread, 1 Hz):
1. **Drift** — `lag_s` exceeds `lag_threshold` for a sustained debounce window.
2. **Stuck** — `obs_cursor` has not advanced for > `stall_threshold` while `live_offset` grew
   (OBS hung in `sendall`).

`lag_s = lag_bytes / rolling_B_per_s`. `FeedFanoutServer` publishes, per connection, a
lock-protected `(cursor, last_advance_ts)`; the sampler reads the OBS consumer's state
(the preview ring-tap reads the ring directly, not via the socket server, so it is never
counted). Only samples while the feed is **serving with an OBS consumer attached** (off-air
→ `close_when_inactive=True` → OBS disconnected → no consumer → no trigger, naturally gated).

**Pure decision function** (`tests/test_fanout.py`):
```python
def autoresync_decision(lag_s, stall_s, since_last_reset_s, *,
                        lag_threshold, stall_threshold, cooldown_s):
    """True when the OBS consumer has drifted (lag_s > lag_threshold) OR is stuck
    (stall_s > stall_threshold), AND the cooldown since the last auto-reset has
    elapsed (since_last_reset_s >= cooldown_s). Pure — unit-tested with synthetic
    values. None/zero lag_s or stall_s never trips it."""
```

**Action.** On a True decision the feed calls the existing `Feed._obs_reconnect()` (rebuild
the feed's OBS input → OBS re-joins clean at the live edge), records the reset time (for the
cooldown), and logs it. The cooldown prevents reset loops; a stuck/dead OBS socket is dropped
by the rebuild and OBS reconnects on its own.

**Default ON with a kill-switch** (`RACECAST_FEED_AUTORESYNC`, default on;
`=0` disables). It automates a proven-safe action and offloads the director; the brief
(1–2 s) black at each (rare) auto-reset is acceptable. Thresholds are conservative and
**calibrated in the local soak before it is relied on live**. Transport is a machine
concern, so the flags live in machine `.env`, consistent with `RACECAST_FEED_FANOUT`.

**Tuning knobs** (env overrides; the defaults are soak-tuned *starting points*, not final):
- `RACECAST_FEED_AUTORESYNC_LAG_S` — drift threshold, start **8.0 s**.
- `RACECAST_FEED_AUTORESYNC_COOLDOWN_S` — min seconds between auto-resets, start **60.0 s**.
- The stuck `stall_threshold` reuses `RACECAST_FEED_STALL_S` (Component 2).
- Debounce = the lag must exceed the threshold across N consecutive 1 Hz samples (start N=3).

### Component 2 — Graduated stall handling (Trigger B)

Make the byte-stall hard-kill grace **configurable and higher**: `RACECAST_FEED_STALL_S`
(start **20.0 s**, up from the hardcoded `FANOUT_STALL_S = 8.0`). A byte-stall while
streamlink is **alive** is often a recoverable uplink micro-stall that streamlink's own HLS
segment retry bridges without a teardown; the longer grace lets that recovery happen instead
of forcing a full yt-dlp re-resolve that enlarges the gap. `feed_stalled(last_byte_ts, now,
stall_s=…)` stays a pure, tested function — only the threshold becomes configurable (read
once at feed start). **Trade-off:** a genuinely dead source is re-resolved a bit later; the
30 s red health grace is separate and unchanged, so alarming is not delayed materially.

### Component 3 — Local soak harness (`tools/`, maintainer, not CI)

A multi-hour, real-OBS validation the unit suite cannot do (the drift is an ffmpeg-playout /
source-clock phenomenon). **Fully local — no cloud box, no real stream, no cookies.**

- Drives the **real** `FeedRing` + `FeedFanoutServer` classes (imported from
  `src/relay/racecast-feeds.py`), fed by **`ffmpeg -re`** (native-rate = ~1× live pacing;
  a test pattern or looped clip). `-re` avoids the VOD-race that no-backpressure otherwise
  causes. The operator points **local OBS** at the feed port.
- **Injectable stalls** (Trigger B): the harness can withhold bytes for a few seconds
  periodically to simulate the WiFi/console uplink stall.
- **Instrumentation:** logs `lag_s`, snap count, and auto-reset firings over time so the
  drift is *visible* and the auto-reset's detect-and-clear is verifiable. Records the
  **fan-out on/off comparison** (the AC).
- **Safe deterministic core** (in the unit suite, no OBS): the mechanism is validated by
  feeding the pure `autoresync_decision` and the sampler synthetic lag/stall values and
  asserting the reset fires and clears — this does **not** need the natural drift to occur.
  The natural-drift reproduction is **best-effort** and can be accelerated with injected
  pacing perturbations.

### Deferred (follow-up)

**True consumer-paced backpressure on the ring** — the speculative "durable root fix" for
Trigger A. It is fundamentally in tension with live streaming (a live source cannot be
throttled) and cannot be validated without a multi-hour real-OBS soak; the detection-driven
auto-resync is the *proven* mitigation. Revisit only if the soak shows the auto-resync is
insufficient. The manual "OBS Feed Reset" button is unchanged throughout.

## Config flags (machine `.env`)

| Flag | Default | Meaning |
|---|---|---|
| `RACECAST_FEED_AUTORESYNC` | **on** | Detection-driven auto-resync; `=0` disables. |
| `RACECAST_FEED_AUTORESYNC_LAG_S` | 8.0 | Drift threshold (OBS lag behind live), soak-tuned. |
| `RACECAST_FEED_AUTORESYNC_COOLDOWN_S` | 60.0 | Min seconds between auto-resets. |
| `RACECAST_FEED_STALL_S` | 20.0 | Byte-stall hard-kill grace (was hardcoded 8 s). |

## Testing & validation

**Pure units (`tests/test_fanout.py`, stdlib runnable script, CI):**
- `autoresync_decision`: drift-only, stuck-only, both, cooldown-blocked, None/zero inputs,
  boundary values.
- The sampler's lag/stuck computation from a `FeedRing` + a fake consumer registry
  (synthetic offsets/timestamps — no real stream): a slow/blocked consumer produces growing
  `lag_s`; a keeping-up consumer stays ~0; the cursor-snap still fires as the backstop.
- Rolling B/s → `lag_s` conversion.
- `RACECAST_FEED_AUTORESYNC*` / `RACECAST_FEED_STALL_S` parsing (default-on token logic like
  `feed_fanout_enabled`).

**Graduated watchdog:** `feed_stalled` with the configurable threshold (new input cases in
`tests/test_pov.py`, where the fan-out health functions already live).

**Local soak (maintainer, blocking before any live reliance):** run the `tools/` harness
against local OBS — **harness built first** so a baseline run (fan-out on, no fix) can start
early and soak for hours in the background while the fixes are built; then a second run with
the fixes to confirm the auto-reset detects and clears the drift, and that the graduated
watchdog bridges an injected stall without a re-resolve. Fan-out on/off comparison recorded.

## Acceptance criteria

- [ ] A single feed can run a multi-hour session; when OBS-consumption drift sets in, the
      relay **detects** it (OBS lag behind live) and **auto-rebuilds** the feed's OBS input
      (the proven reset), clearing the stutter without the director watching. Default on,
      `RACECAST_FEED_AUTORESYNC=0` disables; manual Feed Reset unchanged.
- [ ] A recoverable multi-second source micro-stall (WiFi/console) no longer forces an
      immediate full re-resolve — the graduated `RACECAST_FEED_STALL_S` grace lets
      streamlink's internal retry bridge it.
- [ ] Pure unit coverage for `autoresync_decision`, the lag/stuck sampler, and the
      configurable stall threshold.
- [ ] A local `tools/` soak harness (ffmpeg `-re` + the real ring/server + local OBS,
      injectable stalls, lag/snap/reset logging) exists and is documented; the fan-out
      on/off behaviour is recorded from it. No cloud box required.
