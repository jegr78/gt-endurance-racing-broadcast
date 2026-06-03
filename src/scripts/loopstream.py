#!/usr/bin/env python3
"""Keep ONE streamlink server alive for one public YouTube channel (static mode).
Usage: python3 loopstream.py <CHANNEL_ID> <PORT>
Serves http://127.0.0.1:<PORT> for an OBS media source. Prefers 1080p, >=720p.
NOTE: PUBLIC channels only. The real (unlisted) flow is the relay (tools/run-relay.py).
"""
import subprocess, sys, time


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: loopstream.py <CHANNEL_ID> <PORT>")
    ch, port = sys.argv[1], sys.argv[2]
    url = f"https://www.youtube.com/channel/{ch}/live"
    while True:
        print(f">> [{port}] Connecting to {url}", flush=True)
        try:
            subprocess.call(["streamlink", url, "1080p60,1080p,720p60,720p",
                             "--player-external-http", "--player-external-http-port", port,
                             "--ringbuffer-size", "64M", "--hls-live-edge", "4",
                             "--retry-streams", "15", "--retry-open", "5"])
        except FileNotFoundError:
            sys.exit("ERROR: streamlink not found (brew install streamlink / pip install -U streamlink).")
        print(f">> [{port}] Stream ended or not live. Retrying in 10s...", flush=True)
        time.sleep(10)


if __name__ == "__main__":
    main()
