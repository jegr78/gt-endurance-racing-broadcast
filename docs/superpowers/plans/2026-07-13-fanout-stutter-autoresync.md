# Fan-out stutter: auto-resync + graduated stall (#488) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the long-session fan-out stutter by auto-rebuilding a drifting feed's OBS input on reliable detection (the proven manual reset, automated), stop the 8 s watchdog from amplifying flaky sources, and provide a local soak harness whose evidence resolves the backpressure question inside this issue.

**Architecture:** The relay's fan-out `FeedFanoutServer` publishes per-OBS-consumer health (how long its `sendall` has been blocked = `stuck_s`, plus cursor-snap counts). A pure `autoresync_decision` turns that into a reset trigger; the `_serve_fanout` watchdog samples it at 1 Hz and calls the existing `Feed._obs_reconnect()` (rebuild the OBS input) with a cooldown. The byte-stall watchdog's kill grace becomes configurable and higher so streamlink's internal retry bridges recoverable stalls. A `tools/` soak harness drives the real ring/server from `ffmpeg -re` into local OBS to classify the drift curve.

**Tech Stack:** Python 3 stdlib only (`socket`/`threading`). Tests are stdlib runnable scripts (no pytest). External: `ffmpeg` (already a runtime dep) for the soak harness only.

## Global Constraints

- **Edit only under `src/`** (plus `tools/` for the maintainer harness, `tests/` for tests, `docs/` for the spec/plan). `dist/`/`runtime/` are generated.
- **English only**; **Python stdlib only** in shipped code.
- **Tests are stdlib runnable scripts:** whole file `python3 tests/test_fanout.py`; one function `python3 -c "import sys; sys.path.insert(0,'tests'); import test_fanout as t; t.t_name()"`. No pytest. Run `python3 tools/lint.py` after any Python change.
- **The relay is the live-critical heart.** The fan-out reader must **never block** (its "reader never blocks" invariant is load-bearing). The auto-resync only ever calls the existing best-effort `Feed._obs_reconnect()` (threaded, never raises); it must not touch the reader loop.
- **`FeedRing.read`'s signature is shared** with the program-audio consumer — do NOT change it. Snap detection is pure arithmetic in the consumer loop.
- **Detection signal is time/event based, not byte-lag:** `read()` re-pins the cursor to the live edge every call, so the backlog lives in the blocking `sendall` — measure `stuck_s = now − cycle_ts` and cursor-snaps, NOT `live_offset − cursor`.
- **Config flags live in machine `.env`** (transport is a machine concern), read via pure getters like the existing `fanout_enabled(os.environ)`.
- **Auto-resync is default ON** with kill-switch `RACECAST_FEED_AUTORESYNC=0`.
- **`tools/fanout-soak.py` is maintainer-only** — not shipped, not run in CI (hours-long, needs a GUI OBS). Its pure pieces are unit-tested; the run is an operator checkpoint.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## File structure

- `src/relay/racecast-feeds.py` — the constant bump, the pure getters, `snap_bytes`, `autoresync_decision`, the `FeedFanoutServer` consumer instrumentation (`consumer_health`/`reset_snaps`), and the `_serve_fanout` watchdog wiring (graduated stall + auto-resync sampler) + `Feed`/`Relay.start` wiring.
- `.env.example` — the four new commented knobs.
- `tests/test_fanout.py` — all new pure/instrumentation tests (the file already exists with the import shim `m`).
- `tools/fanout-soak.py` — new maintainer soak harness.

---

### Task 1: Config knobs + ring headroom

**Files:**
- Modify: `src/relay/racecast-feeds.py` (constant ~274; new getters after `fanout_enabled` ~285)
- Modify: `.env.example`
- Test: `tests/test_fanout.py`

**Interfaces:**
- Produces: `feed_autoresync_enabled(environ)->bool`, `feed_autoresync_stuck_s(environ)->float`, `feed_autoresync_cooldown_s(environ)->float`, `feed_stall_s(environ)->float`, `_env_float(environ,key,default)->float`; `FANOUT_RING_BYTES == 16*1024*1024`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_fanout.py`:
```python
def t_feed_autoresync_default_on_and_falsey_disables():
    assert m.feed_autoresync_enabled({}) is True
    assert m.feed_autoresync_enabled({"RACECAST_FEED_AUTORESYNC": ""}) is True
    for v in ("0", "false", "OFF", "no"):
        assert m.feed_autoresync_enabled({"RACECAST_FEED_AUTORESYNC": v}) is False, v
    for v in ("1", "true", "on"):
        assert m.feed_autoresync_enabled({"RACECAST_FEED_AUTORESYNC": v}) is True, v


def t_env_float_defaults_and_guards():
    assert m._env_float({}, "K", 5.0) == 5.0
    assert m._env_float({"K": ""}, "K", 5.0) == 5.0
    assert m._env_float({"K": "abc"}, "K", 5.0) == 5.0
    assert m._env_float({"K": "0"}, "K", 5.0) == 5.0        # <=0 -> default
    assert m._env_float({"K": "-3"}, "K", 5.0) == 5.0
    assert m._env_float({"K": "12.5"}, "K", 5.0) == 12.5


def t_feed_tuning_getter_defaults():
    assert m.feed_autoresync_stuck_s({}) == 5.0
    assert m.feed_autoresync_cooldown_s({}) == 60.0
    assert m.feed_stall_s({}) == 20.0
    assert m.feed_autoresync_stuck_s({"RACECAST_FEED_AUTORESYNC_STUCK_S": "8"}) == 8.0
    assert m.feed_stall_s({"RACECAST_FEED_STALL_S": "30"}) == 30.0


def t_ring_headroom_is_16mb():
    assert m.FANOUT_RING_BYTES == 16 * 1024 * 1024
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_fanout.py`
Expected: `AttributeError: module 'irofeeds' has no attribute 'feed_autoresync_enabled'` (or the ring assert fails).

- [ ] **Step 3: Bump the ring constant**

In `src/relay/racecast-feeds.py` replace:
```python
FANOUT_RING_BYTES = 8 * 1024 * 1024   # per-feed ring window (bounded; ≈ a few seconds at typical feed bitrate)
```
with:
```python
FANOUT_RING_BYTES = 16 * 1024 * 1024  # per-feed ring window (bounded; ≈12 s at 10 Mbps). #488: 8→16 MB headroom so the auto-resync fires an orderly rebuild below the hard cursor-snap.
```

- [ ] **Step 4: Add the getters**

Immediately after the `fanout_enabled` function (after its `return` line), add:
```python
def feed_autoresync_enabled(environ):
    """True unless RACECAST_FEED_AUTORESYNC is an explicit falsey token. Default ON
    (#488): the relay auto-rebuilds a feed's OBS input when it detects OBS drifting
    behind the live edge (the proven manual "OBS Feed Reset", automated). Set
    RACECAST_FEED_AUTORESYNC=0 to disable. Pure so the switch is unit-testable."""
    return str(environ.get("RACECAST_FEED_AUTORESYNC", "")).strip().lower() not in _FANOUT_FALSEY


def _env_float(environ, key, default):
    """Parse a positive float env override; fall back to `default` on absent/empty/
    non-numeric/<=0. Pure."""
    try:
        v = float(str(environ.get(key, "")).strip())
    except (TypeError, ValueError):
        return default
    return v if v > 0 else default


def feed_autoresync_stuck_s(environ):
    """OBS-handler send-block threshold (s) before an auto-resync. #488, soak-tuned."""
    return _env_float(environ, "RACECAST_FEED_AUTORESYNC_STUCK_S", 5.0)


def feed_autoresync_cooldown_s(environ):
    """Min seconds between auto-resyncs (anti-loop). #488."""
    return _env_float(environ, "RACECAST_FEED_AUTORESYNC_COOLDOWN_S", 60.0)


def feed_stall_s(environ):
    """Byte-stall hard-kill grace (s) for the fan-out watchdog. #488: raised from the
    hardcoded 8 s so streamlink's internal HLS retry can bridge a recoverable uplink
    micro-stall before a full re-resolve. Soak-tuned."""
    return _env_float(environ, "RACECAST_FEED_STALL_S", 20.0)
```

- [ ] **Step 5: Document the knobs in `.env.example`**

After the `# RACECAST_FEED_FANOUT=0` line, add:
```
# RACECAST_FEED_AUTORESYNC=0             # #488: disable auto-rebuild of a drifting OBS feed source (default on)
# RACECAST_FEED_AUTORESYNC_STUCK_S=5     # OBS send-block seconds before an auto-resync
# RACECAST_FEED_AUTORESYNC_COOLDOWN_S=60 # min seconds between auto-resyncs
# RACECAST_FEED_STALL_S=20               # byte-stall grace (s) before a fan-out re-resolve
```

- [ ] **Step 6: Run tests + lint**

Run: `python3 tests/test_fanout.py && python3 tools/lint.py`
Expected: all pass (`t_relay_fanout_flag_from_env`'s `FANOUT_RING_BYTES >= 1<<20` still holds), lint clean.

- [ ] **Step 7: Commit**
```bash
git add src/relay/racecast-feeds.py .env.example tests/test_fanout.py
git commit -m "feat(relay): #488 config knobs (auto-resync/stall) + 16MB ring headroom"
```

---

### Task 2: Pure detection primitives + FeedFanoutServer consumer instrumentation

**Files:**
- Modify: `src/relay/racecast-feeds.py` (module-level `snap_bytes`, `autoresync_decision` near `feed_stalled` ~380; `FeedFanoutServer.__init__` / `_serve` / new methods ~3346-3404)
- Test: `tests/test_fanout.py`

**Interfaces:**
- Produces: `snap_bytes(prev_cursor,new_cursor,data_len)->int`; `autoresync_decision(stuck_s,snaps,since_last_reset_s,*,stuck_threshold,snap_threshold,cooldown_s)->bool`; `FeedFanoutServer.consumer_health(now)->(max_stuck_s|None,total_snaps)`, `FeedFanoutServer.reset_snaps()`.
- Consumes: `FeedRing` (unchanged), `time.monotonic`.

- [ ] **Step 1: Write the failing pure-function tests**

Add to `tests/test_fanout.py`:
```python
def t_snap_bytes_zero_when_contiguous():
    # data spans [new_cursor-len, new_cursor); start == prev_cursor -> no skip.
    assert m.snap_bytes(100, 150, 50) == 0
    assert m.snap_bytes(100, 100, 0) == 0


def t_snap_bytes_counts_skipped_on_overflow():
    # consumer at 100, but read snapped it forward: served [180,200) -> skipped 80.
    assert m.snap_bytes(100, 200, 20) == 80


def t_autoresync_decision_stuck_and_snap_and_cooldown():
    kw = dict(stuck_threshold=5.0, snap_threshold=1, cooldown_s=60.0)
    # neither -> False
    assert m.autoresync_decision(1.0, 0, None, **kw) is False
    # stuck over threshold -> True
    assert m.autoresync_decision(6.0, 0, None, **kw) is True
    # a snap -> True
    assert m.autoresync_decision(0.0, 1, None, **kw) is True
    # within cooldown -> False even if stuck
    assert m.autoresync_decision(9.0, 3, 10.0, **kw) is False
    # cooldown elapsed -> True
    assert m.autoresync_decision(9.0, 0, 61.0, **kw) is True
    # None stuck_s never trips on its own
    assert m.autoresync_decision(None, 0, None, **kw) is False


def t_consumer_health_aggregates_registry():
    # consumer_health aggregates the per-connection registry deterministically
    # (max send-block age + total snaps). White-box: the socket-timing path is the
    # soak's job, not a flaky unit test — the honest boundary.
    ring = m.FeedRing(1 << 20)
    srv = m.FeedFanoutServer("127.0.0.1", 0, ring, m.logging.getLogger("t"))
    assert srv.consumer_health(1000.0) == (None, 0)          # no consumer attached
    with srv._consumers_lock:
        srv._consumers[1] = {"cycle_ts": 990.0, "snaps": 2}
        srv._consumers[2] = {"cycle_ts": 998.0, "snaps": 1}
    stuck, snaps = srv.consumer_health(1000.0)
    assert stuck == 10.0 and snaps == 3                       # max(10,2)=10 ; 2+1=3
    srv.reset_snaps()
    assert srv.consumer_health(1000.0) == (10.0, 0)          # snaps cleared, cycle_ts kept
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_fanout.py`
Expected: `AttributeError: ... 'snap_bytes'`.

- [ ] **Step 3: Add the pure functions**

After `feed_stalled` (near line 380), add:
```python
def snap_bytes(prev_cursor, new_cursor, data_len):
    """Bytes a fan-out consumer lost to a ring cursor-snap. FeedRing.read returns
    (data, new_cursor) with data == buf[cursor-base:], so the served bytes span
    [new_cursor-data_len, new_cursor). If that start ran past prev_cursor the ring had
    overflowed the consumer and read() snapped it forward, skipping the gap. Pure —
    returns the skipped byte count (0 when the consumer kept up)."""
    skipped = (new_cursor - data_len) - prev_cursor
    return skipped if skipped > 0 else 0


def autoresync_decision(stuck_s, snaps, since_last_reset_s, *,
                        stuck_threshold, snap_threshold, cooldown_s):
    """Whether to auto-rebuild OBS's feed input (#488). True when OBS's handler is stuck
    draining the socket (stuck_s > stuck_threshold) OR it has taken cursor-snaps
    (snaps >= snap_threshold), AND the cooldown since the last auto-reset has elapsed
    (since_last_reset_s is None or >= cooldown_s). Pure — unit-tested. A None stuck_s /
    zero snaps never trips it on its own."""
    if since_last_reset_s is not None and since_last_reset_s < cooldown_s:
        return False
    stuck = stuck_s is not None and stuck_s > stuck_threshold
    snapped = snaps >= snap_threshold
    return bool(stuck or snapped)
```

- [ ] **Step 4: Instrument `FeedFanoutServer`**

In `FeedFanoutServer.__init__`, after `self._stop = False`, add:
```python
        self._consumers = {}            # id -> {"cycle_ts": float, "snaps": int}
        self._consumers_lock = threading.Lock()
```

Replace the whole `_serve` method body with:
```python
    def _serve(self, conn):
        cid = None
        try:
            conn.recv(65536)                    # consume the request line/headers
            conn.sendall(b"HTTP/1.0 200 OK\r\n"
                         b"Content-Type: video/mp2t\r\n"
                         b"Connection: close\r\n\r\n")
            cursor = self.ring.live_offset()    # join at the live edge
            cid = id(threading.current_thread())
            with self._consumers_lock:
                self._consumers[cid] = {"cycle_ts": time.monotonic(), "snaps": 0}
            while not self._stop and not self.ring.closed:
                prev = cursor
                data, cursor = self.ring.read(cursor, timeout=1.0)
                skipped = snap_bytes(prev, cursor, len(data))
                with self._consumers_lock:
                    st = self._consumers.get(cid)
                    if st is not None:
                        st["cycle_ts"] = time.monotonic()   # read cycle completed
                        if skipped > 0:
                            st["snaps"] += 1
                if data:
                    conn.sendall(data)                       # may block if OBS is slow
                    with self._consumers_lock:
                        st = self._consumers.get(cid)
                        if st is not None:
                            st["cycle_ts"] = time.monotonic()  # send completed
        except OSError:
            pass                                # consumer went away / slow send aborted
        finally:
            if cid is not None:
                with self._consumers_lock:
                    self._consumers.pop(cid, None)
            try:
                conn.close()
            except OSError:
                pass  # already closed
```

After `_serve` (before `stop`), add:
```python
    def consumer_health(self, now):
        """Worst-case OBS-consumer health for the auto-resync sampler: the max send-block
        age (now - cycle_ts) and the total cursor-snaps across active consumers. Returns
        (max_stuck_s, total_snaps); (None, 0) when no consumer is attached. Thread-safe."""
        with self._consumers_lock:
            if not self._consumers:
                return None, 0
            max_stuck = max(now - st["cycle_ts"] for st in self._consumers.values())
            total_snaps = sum(st["snaps"] for st in self._consumers.values())
        return max_stuck, total_snaps

    def reset_snaps(self):
        """Clear snap counters after an auto-resync (the rebuild fixes the cause)."""
        with self._consumers_lock:
            for st in self._consumers.values():
                st["snaps"] = 0
```

- [ ] **Step 5: Run tests + lint**

Run: `python3 tests/test_fanout.py && python3 tools/lint.py`
Expected: all pass (incl. the existing `t_fanout_server_streams_ring_to_two_consumers` / `t_fanout_server_writer_unblocked_by_dead_consumer` — the `_serve` rewrite preserves their behaviour), lint clean.

- [ ] **Step 6: Commit**
```bash
git add src/relay/racecast-feeds.py tests/test_fanout.py
git commit -m "feat(relay): #488 snap_bytes + autoresync_decision + FeedFanoutServer consumer health"
```

---

### Task 3: Local soak harness (`tools/fanout-soak.py`)

**Files:**
- Create: `tools/fanout-soak.py`
- Test: `tests/test_fanout.py` (the one pure piece, `soak_stall_active`)

**Interfaces:**
- Consumes: `FeedRing`, `FeedFanoutServer`, `FANOUT_RING_BYTES`, `consumer_health`, `autoresync_decision`, `feed_autoresync_*` (Tasks 1-2); `obs_ws.release_feed_inputs` (existing).
- Produces: a runnable maintainer tool + pure `soak_stall_active(elapsed_s,*,period_s,duration_s)->bool`.

- [ ] **Step 1: Write the failing pure-piece test**

Add to `tests/test_fanout.py`:
```python
def t_soak_stall_active_schedule():
    import importlib.util as _il
    p = os.path.join(ROOT, "tools", "fanout-soak.py")
    s = _il.spec_from_file_location("fanout_soak", p)
    soak = _il.module_from_spec(s); s.loader.exec_module(soak)
    # last 3 s of every 30 s period are a stall
    assert soak.soak_stall_active(0.0, period_s=30, duration_s=3) is False
    assert soak.soak_stall_active(26.9, period_s=30, duration_s=3) is False
    assert soak.soak_stall_active(27.1, period_s=30, duration_s=3) is True
    assert soak.soak_stall_active(29.9, period_s=30, duration_s=3) is True
    assert soak.soak_stall_active(57.1, period_s=30, duration_s=3) is True   # wraps
    assert soak.soak_stall_active(5.0, period_s=0, duration_s=3) is False    # disabled
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_fanout as t; t.t_soak_stall_active_schedule()"`
Expected: `FileNotFoundError` / import error (the tool does not exist yet).

- [ ] **Step 3: Write the harness**

Create `tools/fanout-soak.py`:
```python
#!/usr/bin/env python3
"""Local fan-out soak harness (#488) — maintainer, NOT shipped, NOT run in CI.

Drives the REAL relay FeedRing + FeedFanoutServer from an ffmpeg -re real-time TS
into your LOCAL OBS, so the OBS-consumption drift (which only appears with real OBS on
a ~1x live-paced source) can be reproduced and CLASSIFIED (clock-bias vs jitter) — the
evidence that resolves the backpressure question inside #488. It also runs the SAME
detection (autoresync_decision) + action (obs_ws.release_feed_inputs) the relay will
use, so it validates detect-and-clear end-to-end against real OBS.

No cloud box, no real stream, no cookies.

Usage:
    # 1. Run the harness (prints the URL to point OBS at):
    python3 tools/fanout-soak.py --port 53001
    # 2. In OBS add a Media Source, uncheck "Local File", URL http://127.0.0.1:53001,
    #    and (to mirror the relay) enable obs-websocket so the reset can rebuild it.
    # 3. Watch the log: stuck_s / snaps / RESET lines. Let it run for hours.

    # Baseline (no auto-reset — capture the RAW drift curve to classify):
    python3 tools/fanout-soak.py --port 53001 --no-autoresync
    # Trigger-B check (inject a 3 s source stall every 30 s):
    python3 tools/fanout-soak.py --port 53001 --stall-period 30 --stall-duration 3

The relay wiring (Tasks 4-5) uses the same pure functions; this harness is the
faithful local proxy that tunes the thresholds and classifies the curve.
"""
import argparse
import importlib.util
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, *rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def soak_stall_active(elapsed_s, *, period_s, duration_s):
    """True during the injected-stall window (the last `duration_s` of every
    `period_s`). period_s<=0 or duration_s<=0 disables. Pure — unit-tested."""
    if period_s <= 0 or duration_s <= 0:
        return False
    return (elapsed_s % period_s) >= (period_s - duration_s)


FFMPEG_CMD = [
    "ffmpeg", "-hide_banner", "-loglevel", "error",
    "-re", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=60",
    "-f", "lavfi", "-i", "sine=frequency=1000",
    "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "8M", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-f", "mpegts", "-",
]


def main():
    ap = argparse.ArgumentParser(description="Fan-out soak harness (#488)")
    ap.add_argument("--port", type=int, default=53001)
    ap.add_argument("--stall-period", type=float, default=0.0, help="s between injected stalls (0=off)")
    ap.add_argument("--stall-duration", type=float, default=3.0, help="s each injected stall lasts")
    ap.add_argument("--log-interval", type=float, default=5.0)
    ap.add_argument("--no-autoresync", action="store_true", help="baseline: log only, never reset")
    args = ap.parse_args()

    fe = _load("irofeeds", "src", "relay", "racecast-feeds.py")
    obs_ws = _load("obs_ws", "src", "scripts", "obs_ws.py")

    ring = fe.FeedRing(fe.FANOUT_RING_BYTES)
    srv = fe.FeedFanoutServer("127.0.0.1", args.port, ring, fe.logging.getLogger("soak"))
    srv.start()
    stuck_thr = fe.feed_autoresync_stuck_s(os.environ)
    cooldown = fe.feed_autoresync_cooldown_s(os.environ)
    print(f"[soak] serving on http://127.0.0.1:{srv.port}  — point OBS Media Source at it")
    print(f"[soak] autoresync={'off' if args.no_autoresync else 'on'} "
          f"stuck_thr={stuck_thr}s cooldown={cooldown}s ring={fe.FANOUT_RING_BYTES}B")

    proc = subprocess.Popen(FFMPEG_CMD, stdout=subprocess.PIPE)
    stop = threading.Event()
    started = time.monotonic()
    resets = [0]
    last_reset = [None]

    def _monitor():
        while not stop.is_set():
            time.sleep(args.log_interval)
            now = time.monotonic()
            stuck_s, snaps = srv.consumer_health(now)
            print(f"[soak] t={now-started:7.1f}s stuck={('-' if stuck_s is None else f'{stuck_s:.1f}')}s "
                  f"snaps={snaps} resets={resets[0]}")
            if args.no_autoresync:
                continue
            since = None if last_reset[0] is None else now - last_reset[0]
            if fe.autoresync_decision(stuck_s, snaps, since, stuck_threshold=stuck_thr,
                                      snap_threshold=1, cooldown_s=cooldown):
                names, note = obs_ws.release_feed_inputs(ports=[srv.port])
                resets[0] += 1
                last_reset[0] = now
                srv.reset_snaps()
                print(f"[soak] RESET #{resets[0]} at t={now-started:.1f}s -> {names or note}")

    threading.Thread(target=_monitor, daemon=True).start()
    try:
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            if not soak_stall_active(time.monotonic() - started,
                                     period_s=args.stall_period, duration_s=args.stall_duration):
                ring.write(chunk)          # withhold during an injected stall
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        try:
            proc.terminate()
        except OSError:
            pass
        srv.stop()
        print(f"[soak] done — total resets: {resets[0]}")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the pure test + lint**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_fanout as t; t.t_soak_stall_active_schedule()" && python3 tools/lint.py`
Expected: pass, lint clean. (A real soak run is the operator checkpoint below, not this step.)

- [ ] **Step 5: Commit**
```bash
git add tools/fanout-soak.py tests/test_fanout.py
git commit -m "feat(tools): #488 local fan-out soak harness (ffmpeg -re + real ring/server + OBS)"
```

---

### CHECKPOINT A — operator soak (run by Jens, local OBS). Not an implementer task.

After Task 3, run the harness against local OBS to (1) classify the drift curve and
(2) validate detect-and-clear, before the relay wiring locks in thresholds:

1. **Baseline** (`--no-autoresync`, hours): capture `stuck_s`/`snaps` over time.
   - **Monotone/linear ramp → clock bias** → the auto-resync is the correct+sufficient
     fix; no backpressure (Task 6 branch A).
   - **Oscillating with spikes → jitter** → a bounded read-ahead would help
     (Task 6 branch B).
2. **Validation** (default, auto-resync on): confirm a RESET fires when the drift
   crosses threshold and the curve clears after each. Tune `stuck_s`/`cooldown` if the
   defaults are too eager/lazy.
3. **Trigger B** (`--stall-period 30 --stall-duration 3`): confirm an injected 3 s stall
   does not cascade (the harness serves the ring; the relay's graduated watchdog is
   Task 4 — record the stall's effect on the curve here as the baseline for it).

Record the results (curve classification + tuned thresholds) in the PR description.
This checkpoint gates **Task 6**.

---

### Task 4: Graduated stall watchdog

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`_serve_fanout` watchdog, ~5196-5212)
- Test: `tests/test_fanout.py`

**Interfaces:**
- Consumes: `feed_stall_s(os.environ)` (Task 1), `feed_stalled(last_byte_ts, now, stall_s=…)` (existing).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_fanout.py`:
```python
def t_feed_stalled_honours_configured_grace():
    # The graduated grace: at 20 s default, an 8 s gap is NOT a stall (streamlink's
    # retry gets time); a 21 s gap is.
    g = m.feed_stall_s({})                       # 20.0
    assert m.feed_stalled(100.0, 100.0 + 8.0, stall_s=g) is False
    assert m.feed_stalled(100.0, 100.0 + g + 0.1, stall_s=g) is True
```

- [ ] **Step 2: Run the test**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_fanout as t; t.t_feed_stalled_honours_configured_grace()"`
Expected: PASS — it locks the graduated-grace **contract** (`feed_stall_s` default 20 s + `feed_stalled` honouring it), which holds once Task 1 is in. Task 4's actual deliverable is the **watchdog wiring** in Step 3 (that the closure passes `stall_s=feed_stall_s(...)` instead of the hardcoded 8 s) — diff-verified + soak-validated, the honest boundary already documented in `t_fanout_watchdog_kill_condition_is_feed_stalled`.

- [ ] **Step 3: Wire the configured grace into the watchdog**

In `_serve_fanout`, just before `watchdog_stop = threading.Event()`, add:
```python
        stall_s = feed_stall_s(os.environ)
```
Then in the `_watchdog` closure replace the stall check:
```python
                if feed_stalled(self.last_byte_ts, time.monotonic()):
                    self.log.warning("fan-out stall on %s — killing reader", self.name)
```
with:
```python
                if feed_stalled(self.last_byte_ts, time.monotonic(), stall_s=stall_s):
                    self.log.warning("fan-out stall on %s (>%.0fs) — killing reader",
                                     self.name, stall_s)
```

- [ ] **Step 4: Run tests + lint**

Run: `python3 tests/test_fanout.py && python3 tests/test_pov.py && python3 tools/lint.py`
Expected: all pass, lint clean. (The watchdog-closure wiring is diff-verified + soak-validated — the honest boundary already documented in `t_fanout_watchdog_kill_condition_is_feed_stalled`.)

- [ ] **Step 5: Commit**
```bash
git add src/relay/racecast-feeds.py tests/test_fanout.py
git commit -m "feat(relay): #488 graduated fan-out stall grace (configurable, 8->20s default)"
```

---

### Task 5: Auto-resync wiring in the watchdog + Feed/Relay wiring

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`Feed.__init__` ~5068; `_serve_fanout` watchdog ~5196-5215; `Relay.start` fan-out loop ~5476)
- Test: `tests/test_fanout.py`

**Interfaces:**
- Consumes: `feed_autoresync_enabled/_stuck_s/_cooldown_s(os.environ)`, `autoresync_decision`, `FeedFanoutServer.consumer_health/reset_snaps` (Tasks 1-2); `Feed._obs_reconnect()` (existing, threaded/best-effort).
- Produces: `Feed.fanout_server` (set by `Relay.start`), `Feed._last_autoresync_ts`.

- [ ] **Step 1: Write the failing wiring test**

Add to `tests/test_fanout.py`:
```python
def t_feed_has_autoresync_attrs():
    import tempfile
    f = m.Feed("A", 53001, 0, (lambda: []), tempfile.mkdtemp())
    assert f.fanout_server is None
    assert f._last_autoresync_ts is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_fanout as t; t.t_feed_has_autoresync_attrs()"`
Expected: `AttributeError: 'Feed' object has no attribute 'fanout_server'`.

- [ ] **Step 3: Add the Feed attributes**

In `Feed.__init__`, after `self.source_state = None`, add:
```python
        self.fanout_server = None     # #488: set by Relay.start when fan-out is on (auto-resync sampler)
        self._last_autoresync_ts = None   # monotonic ts of the last auto-resync (cooldown)
```

- [ ] **Step 4: Sample + act in the watchdog**

In `_serve_fanout`, next to the `stall_s = feed_stall_s(os.environ)` line (Task 4), add:
```python
        autoresync_on = feed_autoresync_enabled(os.environ)
        ar_stuck = feed_autoresync_stuck_s(os.environ)
        ar_cooldown = feed_autoresync_cooldown_s(os.environ)
```
Then in the `_watchdog` closure, after the `feed_stalled(...)` block (after its `return`), add:
```python
                if autoresync_on and self.fanout_server is not None:
                    now = time.monotonic()
                    stuck_s, snaps = self.fanout_server.consumer_health(now)
                    since = (None if self._last_autoresync_ts is None
                             else now - self._last_autoresync_ts)
                    if autoresync_decision(stuck_s, snaps, since, stuck_threshold=ar_stuck,
                                           snap_threshold=1, cooldown_s=ar_cooldown):
                        self.log.warning("auto-resync %s — OBS drift (stuck=%.1fs snaps=%d) "
                                         "— rebuilding OBS input", self.name,
                                         stuck_s or 0.0, snaps)
                        self._obs_reconnect()          # threaded, best-effort
                        self._last_autoresync_ts = now
                        self.fanout_server.reset_snaps()
```

- [ ] **Step 5: Wire the server onto the feed in `Relay.start`**

In `Relay.start`, inside the fan-out loop, after `self._fanout_servers.append(srv)`, add:
```python
                f.fanout_server = srv
```

- [ ] **Step 6: Run tests + lint**

Run: `python3 tests/test_fanout.py && python3 tests/test_pov.py && python3 tools/lint.py`
Expected: all pass, lint clean. (The watchdog-closure sampler + `Relay.start` wiring are diff-verified + soak-validated — the honest boundary; the pure `autoresync_decision`/`consumer_health` and the Feed attrs are unit-tested.)

- [ ] **Step 7: Commit**
```bash
git add src/relay/racecast-feeds.py tests/test_fanout.py
git commit -m "feat(relay): #488 detection-driven auto-resync in the fan-out watchdog (default on)"
```

---

### Task 6 (conditional, in-issue): the backpressure decision from CHECKPOINT A

Decided from the operator soak's drift-curve classification — resolved **inside #488**,
not deferred:

- **Branch A — clock bias (monotone ramp):** the auto-resync is confirmed sufficient.
  Document the finding (the classified curve + tuned thresholds) in the spec's
  backpressure section and the PR; **no backpressure code**. #488 closes.
- **Branch B — jitter (oscillating spikes):** add a bounded read-ahead / backpressure
  in this same PR, its exact shape driven by the measured curve (e.g. a larger ring or
  a paced consumer), with new pure tests in `tests/test_fanout.py` and a re-run of the
  validation soak. Then #488 closes.

Which branch runs is set at CHECKPOINT A; this task's content is finalized then.

---

## Final verification (after all build tasks + the chosen Task 6 branch)

- [ ] `python3 tools/run-tests.py && python3 tools/lint.py` — all green, lint clean.
- [ ] `python3 tools/build.py` — dist self-verify passes (no shell scripts, no secrets,
      tokenization intact); confirms `tools/fanout-soak.py` is not shipped.
