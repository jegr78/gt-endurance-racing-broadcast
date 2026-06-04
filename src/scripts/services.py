"""Manage spawned background services (relay, streams) via a PID file + log file.
Pure decision logic (read_pid, pid_alive, status_line) is separated from process
side effects (start_detached, stop_pid, tail) so it unit-tests without spawning."""
import os, signal, subprocess, sys, time


def read_pid(pid_path):
    """Int PID stored in pid_path, or None if missing/empty/garbage."""
    try:
        with open(pid_path) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def spawn_kwargs(os_name):
    """Popen kwargs that detach the child from our session/console per OS."""
    if os_name == "posix":
        return {"start_new_session": True}
    if os_name == "nt":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        return {"creationflags": DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP}
    return {}


def stop_commands(os_name, pid, force):
    """argv to stop a PID on Windows (taskkill), or None where POSIX signals apply.
    /T kills the child tree — the relay's streamlink/yt-dlp children must not be
    orphaned. The non-force form asks first (WM_CLOSE); console children usually
    ignore it, so stop_pid() falls through to the force form after the timeout."""
    if os_name != "nt":
        return None
    if force:
        return ["taskkill", "/F", "/T", "/PID", str(pid)]
    return ["taskkill", "/PID", str(pid)]


def pid_alive(pid):
    """True iff a process with this PID currently exists."""
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _pid_alive_windows(pid):
    """ctypes probe — os.kill(pid, 0) is NOT safe on Windows: any signal other
    than CTRL_C/CTRL_BREAK unconditionally TerminateProcess()es the target."""
    import ctypes
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    ERROR_ACCESS_DENIED = 5
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED  # exists, no access
    try:
        code = ctypes.c_ulong()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


def status_line(name, pid, alive, extra=""):
    """One formatted line: 'relay          RUNNING (pid 1234)  <extra>'.
    Pad width 14 keeps the longest name (e.g. 'streams:53002') aligned."""
    state = f"RUNNING (pid {pid})" if alive else "stopped"
    return f"{name:<14} {state}  {extra}".rstrip()


def start_detached(argv, log_path, pid_path, env=None):
    """Spawn argv detached, stdout/stderr -> log_path, write pid_path. Returns PID.
    Caller must verify it is not already running first.
    env: optional full environment dict for the child (defaults to inherited)."""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    os.makedirs(os.path.dirname(pid_path), exist_ok=True)
    kwargs = spawn_kwargs(os.name)
    # Open the log in a `with` so the parent's fd is closed after Popen dups it
    # into the child — avoids a parent-side fd leak that would also pin the file.
    with open(log_path, "ab") as log:
        proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env, **kwargs)
    with open(pid_path, "w") as fh:
        fh.write(str(proc.pid))
    return proc.pid


def _reap_zombie(pid):
    """Attempt waitpid(WNOHANG) to reap a zombie child; silently ignore if not our child."""
    if os.name != "posix":
        return
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass  # not our child — nothing to reap
    except OSError:
        pass


def _signal_stop(pid, force):
    cmd = stop_commands(os.name, pid, force)
    if cmd is not None:
        subprocess.run(cmd, capture_output=True)
        return
    try:
        os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
    except OSError:
        pass


def stop_pid(pid, pid_path=None, timeout=10):
    """Graceful stop, wait up to timeout, then force; remove pid_path. True if gone."""
    if pid_alive(pid):
        _signal_stop(pid, force=False)
        for _ in range(timeout * 2):
            _reap_zombie(pid)
            if not pid_alive(pid):
                break
            time.sleep(0.5)
        if pid_alive(pid):
            _signal_stop(pid, force=True)
            time.sleep(0.5)
            _reap_zombie(pid)
    if pid_path and os.path.exists(pid_path):
        os.remove(pid_path)
    return not pid_alive(pid)


def tail(log_path, follow=False, lines=40):
    """Print the last `lines` of log_path; if follow, stream new output until Ctrl+C.
    Pure-Python (cross-platform — no system `tail`)."""
    if not os.path.exists(log_path):
        print(f"(no log yet at {log_path})")
        return
    with open(log_path, encoding="utf-8", errors="replace") as fh:
        for line in fh.readlines()[-lines:]:
            sys.stdout.write(line)
        if not follow:
            return
        try:
            while True:
                line = fh.readline()
                if line:
                    sys.stdout.write(line); sys.stdout.flush()
                else:
                    time.sleep(0.3)
        except KeyboardInterrupt:
            pass
