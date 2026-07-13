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
        pass  # Ctrl-C → fall through to cleanup
    finally:
        stop.set()
        try:
            proc.terminate()
        except OSError:
            pass  # process already gone
        srv.stop()
        print(f"[soak] done — total resets: {resets[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
