#!/usr/bin/env python3
"""Keep ONE streamlink server alive for one public YouTube channel (static mode).
Usage: python3 loopstream.py <CHANNEL_ID> <PORT>
Serves http://127.0.0.1:<PORT> for an OBS media source. Prefers 1080p, >=720p.
NOTE: PUBLIC channels only. The real (unlisted) flow is the relay (`racecast relay start`).
"""
import os, subprocess, sys, time


def no_window_kwargs(os_name=None):
    """Popen/call kwargs that stop streamlink from flashing a terminal window on
    Windows. A static feed runs DETACHED (no console — start-streams' spawn_kwargs),
    so the streamlink child otherwise gets a fresh, PERSISTENT console window for
    the whole stint (same class as the relay's per-feed spawn, issue #30). The
    feed's stdout is redirected to a log file by start-streams, so CREATE_NO_WINDOW
    suppresses the window without losing logged output. No-op (empty) off Windows.
    Mirrors services.no_window_kwargs — duplicated so this standalone feed imports
    nothing from its siblings."""
    os_name = os.name if os_name is None else os_name
    if os_name == "nt":
        CREATE_NO_WINDOW = 0x08000000
        return {"creationflags": CREATE_NO_WINDOW}
    return {}


def streamlink_argv(url, port):
    """streamlink serve argv for one public channel. Prefers 1080p, falls to 720p."""
    return ["streamlink", url, "1080p60,1080p,720p60,720p",
            "--player-external-http", "--player-external-http-port", port,
            "--ringbuffer-size", "64M", "--hls-live-edge", "4",
            "--retry-streams", "15", "--retry-open", "5"]


def serve_once(url, port, call=subprocess.call):
    """Serve `url` on `port` until streamlink exits; returns its exit code.
    `call` is an injectable seam for the unit test."""
    return call(streamlink_argv(url, port), **no_window_kwargs())


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: loopstream.py <CHANNEL_ID> <PORT>")
    ch, port = sys.argv[1], sys.argv[2]
    url = f"https://www.youtube.com/channel/{ch}/live"
    while True:
        print(f">> [{port}] Connecting to {url}", flush=True)
        try:
            serve_once(url, port)
        except FileNotFoundError:
            sys.exit("ERROR: streamlink not found (brew install streamlink / pip install -U streamlink).")
        print(f">> [{port}] Stream ended or not live. Retrying in 10s...", flush=True)
        time.sleep(10)


if __name__ == "__main__":
    main()
