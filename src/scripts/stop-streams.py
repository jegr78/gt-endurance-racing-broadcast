#!/usr/bin/env python3
"""Stop every streamlink server started by start-streams.py (Mac/Linux + Windows)."""
import glob, os, signal, subprocess, sys


def pid_is_feed(pid):
    """True only if `pid` is actually one of our feed processes. Guards against a
    stale/forged PID file naming a recycled PID — without this we could SIGTERM an
    unrelated process. POSIX: match the command line against our launchers."""
    if os.name == "nt":
        try:
            out = subprocess.check_output(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
                                          stderr=subprocess.DEVNULL, text=True)
        except (subprocess.SubprocessError, OSError):
            return False
        return "python" in out.lower() or "streamlink" in out.lower()
    try:
        cmd = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="],
                                      stderr=subprocess.DEVNULL, text=True)
    except (subprocess.SubprocessError, OSError):
        return False
    return "loopstream" in cmd or "streamlink" in cmd


def kill_tree(pid):
    if os.name == "nt":
        subprocess.call(["taskkill", "/PID", str(pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.call(["pkill", "-P", str(pid)], stderr=subprocess.DEVNULL)  # children first
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


def state_dir(here):
    """Must match start-streams.py: repo -> <repo>/runtime/static ; dist -> next to script."""
    if os.path.basename(here) == "scripts" and os.path.basename(os.path.dirname(here)) == "src":
        return os.path.join(os.path.dirname(os.path.dirname(here)), "runtime", "static")
    return here


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    pidfiles = glob.glob(os.path.join(state_dir(here), "feed_*.pid"))
    for pf in pidfiles:
        try:
            pid = int(open(pf).read().strip())
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
