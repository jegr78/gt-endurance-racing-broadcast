#!/usr/bin/env python3
"""Stop every streamlink server started by start-streams.py (Mac/Linux + Windows)."""
import argparse, glob, os, signal, subprocess


def looks_like_feed(probe_output, windows=False):
    """True iff a ps/tasklist probe line describes one of our feed processes:
    loopstream/streamlink children (or their python.exe image on Windows), or
    the frozen iro binary running the hidden `streams run-feed` verb. Guards
    against stale/recycled PID files naming an unrelated process.

    On POSIX the full command line is available, so we require either "run-feed"
    (frozen iro child) or a loopstream/streamlink token — bare "python" alone is
    intentionally NOT accepted (too broad; any python process would match).
    On Windows the probe returns only the image name (no argv), so we accept
    "python", "streamlink", and "iro.exe"."""
    text = probe_output.lower()
    if "run-feed" in text or "iro.exe" in text:   # frozen children (both platforms)
        return True
    tokens = ("python", "streamlink") if windows else ("loopstream", "streamlink")
    return any(tok in text for tok in tokens)


def pid_is_feed(pid):
    """True only if `pid` is actually one of our feed processes. Guards against a
    stale/forged PID file naming a recycled PID — without this we could SIGTERM an
    unrelated process. POSIX: match the command line against our launchers."""
    if os.name == "nt":
        try:
            # errors="replace": tasklist writes OEM-codepage console output
            # (localized umlauts) that the ANSI codepage cannot decode; the
            # matched feed tokens are pure ASCII.
            out = subprocess.check_output(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
                                          stderr=subprocess.DEVNULL, text=True,
                                          errors="replace")
        except (subprocess.SubprocessError, OSError):
            return False
        return looks_like_feed(out, windows=True)
    try:
        cmd = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="],
                                      stderr=subprocess.DEVNULL, text=True,
                                      errors="replace")
    except (subprocess.SubprocessError, OSError):
        return False
    return looks_like_feed(cmd)


def kill_tree(pid):
    if os.name == "nt":
        subprocess.call(["taskkill", "/PID", str(pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.call(["pkill", "-P", str(pid)], stderr=subprocess.DEVNULL)  # children first
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass  # already gone or not ours — pid_is_feed() vetted it before


def state_dir(here):
    """Must match start-streams.py: repo -> <repo>/runtime/static ; dist -> next to script."""
    if os.path.basename(here) == "scripts" and os.path.basename(os.path.dirname(here)) == "src":
        return os.path.join(os.path.dirname(os.path.dirname(here)), "runtime", "static")
    return here


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default=state_dir(here))
    a = ap.parse_args()
    pidfiles = glob.glob(os.path.join(a.state_dir, "feed_*.pid"))
    for pf in pidfiles:
        try:
            with open(pf) as fh:
                pid = int(fh.read().strip())
        except ValueError:
            os.remove(pf); continue
        if not pid_is_feed(pid):
            print(f"Skipped {os.path.basename(pf)[:-4]} (PID {pid} is not a feed — stale file)")
            os.remove(pf); continue
        kill_tree(pid)
        print(f"Stopped {os.path.basename(pf)[:-4]} (PID {pid})")
        os.remove(pf)
    # NOTE: no broad `pkill -f player-external-http` here — the relay (iro-feeds.py)
    # also serves with --player-external-http, so a catch-all would kill live relay
    # feeds. Only the tracked PID files are stopped.
    if not pidfiles:
        print("No running feeds found.")
    print("Done.")


if __name__ == "__main__":
    main()
