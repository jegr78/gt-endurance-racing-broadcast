#!/usr/bin/env python3
"""Launch one streamlink server per channel (static/public mode), backgrounded,
each with a log + PID file so stop-streams.py can shut them down.
Feeds come from <state-dir>/streams.json (managed by the Control Center) when
present, else the built-in FEEDS default below — (CHANNEL_ID, PORT). Ports must
match the OBS media sources.
NOTE: PUBLIC channels only. The real unlisted flow is the relay (`iro relay start`).
"""
import argparse, json, os, shutil, subprocess, sys


def state_dir(here):
    """Where PID/log files live: repo (src/scripts/) -> <repo>/runtime/static (gitignored);
    distributed package (scripts/) -> next to the script."""
    if os.path.basename(here) == "scripts" and os.path.basename(os.path.dirname(here)) == "src":
        return os.path.join(os.path.dirname(os.path.dirname(here)), "runtime", "static")
    return here

def feed_argv(frozen, executable, loop_path, channel, port):
    """Child argv for one feed. Frozen iro binary: re-invoke ourselves with the
    hidden `streams run-feed` verb (no python3 on producer machines); otherwise
    run loopstream.py with the current interpreter."""
    if frozen:
        return [executable, "streams", "run-feed", channel, port]
    return [executable, loop_path, channel, port]


def feed_env(frozen, base_env):
    """Env for frozen feed children. They re-run the iro --onefile binary, and
    PYINSTALLER_RESET_ENVIRONMENT=1 makes each an independent instance (own
    _MEIPASS) that outlives this parent — same fix as iro.py's
    _frozen_child_env(); keep the two in sync. Repo mode: None (inherit)."""
    if not frozen:
        return None
    env = dict(base_env)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def _spawn_kwargs():
    """services.py lives next to this script (repo + bundle); import lazily so
    loading this file from elsewhere (tests) needs no path setup."""
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("services", os.path.join(here, "services.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.spawn_kwargs(os.name)


# ---- channels ----  (CHANNEL_ID, PORT)
FEEDS = [
    ("UCNye-wNBqNL5ZzHSJj3l8Bg", "53001"),   # Feed A - TEST: Al Jazeera English (24/7)
    ("UCknLrEdhRCp1aegoMqRaCZg", "53002"),   # Feed B - TEST: DW News (24/7)
    # Replace TEST IDs with the real streamer channel IDs before the event.
]
# ------------------

STREAMS_CONFIG = "streams.json"


def load_feeds(state_dir):
    """Feeds to serve: <state_dir>/streams.json (Control Center-managed) when it
    exists and parses, else the built-in FEEDS default. Returns a list of
    (channel, port) string pairs; entries missing a channel or port are skipped,
    and a malformed/empty file falls back to FEEDS so a bad edit never serves
    nothing."""
    path = os.path.join(state_dir, STREAMS_CONFIG)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        feeds = []
        for e in data:
            ch, port = str(e.get("channel", "")).strip(), str(e.get("port", "")).strip()
            if ch and port:
                feeds.append((ch, port))
        return feeds or FEEDS
    except (OSError, ValueError, AttributeError, TypeError):
        return FEEDS


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default=state_dir(here),
                    help="PID/log dir (iro passes <runtime>/static explicitly).")
    a = ap.parse_args()
    sdir = a.state_dir
    logdir = os.path.join(sdir, "logs")
    os.makedirs(logdir, exist_ok=True)
    if not shutil.which("streamlink"):
        sys.exit("streamlink not found (brew install streamlink / pip install -U streamlink).")
    loop = os.path.join(here, "loopstream.py")
    frozen = bool(getattr(sys, "frozen", False))
    for i, (ch, port) in enumerate(load_feeds(sdir), 1):
        # Close the parent's log fd after the spawn — the child holds its own
        # duplicate (same pattern as services.start_detached).
        with open(os.path.join(logdir, f"feed_{port}.log"), "ab") as log:
            p = subprocess.Popen(feed_argv(frozen, sys.executable, loop, ch, port),
                                 stdout=log, stderr=subprocess.STDOUT,
                                 env=feed_env(frozen, os.environ),
                                 **_spawn_kwargs())
        with open(os.path.join(sdir, f"feed_{port}.pid"), "w") as fh:
            fh.write(str(p.pid))
        print(f"Started Feed {i} -> channel {ch} on http://127.0.0.1:{port} (log: {logdir}/feed_{port}.log)")
    print("\nAll feeds launched. Point each OBS media source at its http://127.0.0.1:PORT.")
    print("Stop everything with:  iro streams stop")


if __name__ == "__main__":
    main()
