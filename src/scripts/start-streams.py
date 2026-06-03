#!/usr/bin/env python3
"""Launch one streamlink server per channel (static/public mode), backgrounded,
each with a log + PID file so stop-streams.py can shut them down.
EDIT the FEEDS list: (CHANNEL_ID, PORT). Ports must match the OBS media sources.
NOTE: PUBLIC channels only. The real unlisted flow is the relay (tools/run-relay.py).
"""
import os, shutil, subprocess, sys


def state_dir(here):
    """Where PID/log files live: repo (src/scripts/) -> <repo>/runtime/static (gitignored);
    distributed package (scripts/) -> next to the script."""
    if os.path.basename(here) == "scripts" and os.path.basename(os.path.dirname(here)) == "src":
        return os.path.join(os.path.dirname(os.path.dirname(here)), "runtime", "static")
    return here

# ---- channels ----  (CHANNEL_ID, PORT)
FEEDS = [
    ("UCNye-wNBqNL5ZzHSJj3l8Bg", "53001"),   # Feed A - TEST: Al Jazeera English (24/7)
    ("UCknLrEdhRCp1aegoMqRaCZg", "53002"),   # Feed B - TEST: DW News (24/7)
    # Replace TEST IDs with the real streamer channel IDs before the event.
]
# ------------------


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    sdir = state_dir(here)
    logdir = os.path.join(sdir, "logs")
    os.makedirs(logdir, exist_ok=True)
    if not shutil.which("streamlink"):
        sys.exit("streamlink not found (brew install streamlink / pip install -U streamlink).")
    loop = os.path.join(here, "loopstream.py")
    for i, (ch, port) in enumerate(FEEDS, 1):
        log = open(os.path.join(logdir, f"feed_{port}.log"), "ab")
        p = subprocess.Popen([sys.executable, loop, ch, port], stdout=log, stderr=subprocess.STDOUT)
        open(os.path.join(sdir, f"feed_{port}.pid"), "w").write(str(p.pid))
        print(f"Started Feed {i} -> channel {ch} on http://127.0.0.1:{port} (log: {logdir}/feed_{port}.log)")
    print("\nAll feeds launched. Point each OBS media source at its http://127.0.0.1:PORT.")
    print("Stop everything with:  python3 stop-streams.py")


if __name__ == "__main__":
    main()
