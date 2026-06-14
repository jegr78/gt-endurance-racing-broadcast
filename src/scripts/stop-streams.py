#!/usr/bin/env python3
"""Stop every streamlink server started by start-streams.py (Mac/Linux + Windows)."""
import argparse, glob, os, signal, subprocess, time


def looks_like_feed(probe_output, windows=False):
    """True iff a ps/tasklist probe line describes one of our feed processes:
    loopstream/streamlink children (or their python.exe image on Windows), or
    the frozen racecast binary running the hidden `streams run-feed` verb. Guards
    against stale/recycled PID files naming an unrelated process.

    On POSIX the full command line is available, so we require either "run-feed"
    (frozen racecast child) or a loopstream/streamlink token — bare "python" alone is
    intentionally NOT accepted (too broad; any python process would match).
    On Windows the probe returns only the image name (no argv), so we accept
    "python", "streamlink", and "racecast.exe"."""
    text = probe_output.lower()
    if "run-feed" in text or "racecast.exe" in text:   # frozen children (both platforms)
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


def _proc_alive(pid):
    """True if `pid` still exists (POSIX). signal 0 is an existence probe — it
    sends nothing. PermissionError means the PID is live but not ours, so alive."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def kill_tree(pid):
    """Terminate a feed process AND every descendant.

    Static feeds are spawned as session leaders (services.spawn_kwargs ->
    start_new_session=True), so the whole tree shares ONE process group whose id
    is `pid`. Signalling the GROUP reaps grandchildren too — essential for the
    frozen binary, where the tree is bootloader(pid) -> app-child -> streamlink:
    a direct-children-only kill (`pkill -P pid`) orphaned streamlink, which kept
    its port bound and blocked the relay's Feed A (#133). Best-effort throughout;
    pid_is_feed() vetted `pid` before we get here."""
    if os.name == "nt":
        # taskkill /T already walks and kills the whole tree.
        subprocess.call(["taskkill", "/PID", str(pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, PermissionError):
        return  # already gone
    if pgid != pid:
        # Not the session leader we expect (feeds always are). Fall back to the
        # narrower kill rather than risk signalling an unrelated process group.
        subprocess.call(["pkill", "-P", str(pid)], stderr=subprocess.DEVNULL)
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass  # leader already gone / not ours — nothing left to signal
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    # Escalate to SIGKILL on the group if the leader is still up after a grace
    # period (a wedged streamlink that ignores SIGTERM would otherwise hold its port).
    for _ in range(25):                  # ~2.5 s grace
        if not _proc_alive(pid):
            break
        time.sleep(0.1)
    if _proc_alive(pid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass  # group already reaped between the grace poll and the kill


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
    # NOTE: no broad `pkill -f player-external-http` here — the relay (racecast-feeds.py)
    # also serves with --player-external-http, so a catch-all would kill live relay
    # feeds. Only the tracked PID files are stopped.
    if not pidfiles:
        print("No running feeds found.")
    print("Done.")


if __name__ == "__main__":
    main()
