# Unified `iro` Operator CLI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the split operator entrypoints (`tools/run-relay.py`, `start-/stop-companion.py`, `start-/stop-streams.py`) with one shipped command, `iro`, exposing a uniform `start | stop | restart | status | logs` verb set per service plus the one-shot actions.

**Architecture:** A thin dispatcher `src/iro.py` (parse + route, no logic) routes to per-service adapters. Relay and streams are spawned background daemons managed through a shared helper `src/scripts/services.py` (PID file + log file under `runtime/`); companion is its own adapter over the existing `companion_common.py` (a GUI app, not a PID-spawned daemon). One-shot actions (`preflight/cookies/graphics/media/setup`) are thin pass-throughs to existing modules.

**Tech Stack:** Pure Python 3 + stdlib only (no pytest — each test file is a runnable script, matching the project). External runtime tools unchanged (`yt-dlp`, `streamlink`, `ffmpeg`, `deno`, Tailscale CLI).

Reference spec: `docs/superpowers/specs/2026-06-04-iro-unified-cli-design.md`.

---

## File structure

| File | Responsibility |
|---|---|
| `src/scripts/services.py` (create) | Daemon helper: PID read/alive, detached spawn, graceful stop, tail, status line |
| `tests/test_services.py` (create) | Unit + real-process integration tests for `services.py` |
| `src/iro.py` (create) | Dispatcher: `route(argv)` + `main()` + service adapters + one-shot wrappers |
| `tests/test_iro.py` (create) | Unit tests for `route(argv)` |
| `src/scripts/companion_common.py` (keep) | Pure companion logic, imported by the companion adapter |
| `src/scripts/start-streams.py`, `stop-streams.py`, `loopstream.py` (keep) | Streams implementation, sub-processed by the streams adapter |
| `tools/build.py` (modify) | Verify `iro.py` ships + old entrypoints gone |
| `README.md`, `CLAUDE.md` (modify) | Rewrite operator commands around `iro` |
| `tools/run-relay.py`, `src/scripts/start-companion.py`, `src/scripts/stop-companion.py` (delete) | Replaced by `iro` |

**Path model (critical):** `src/iro.py` ships as `iro.py` at the package root. In both repo (`src/`) and package (root), `relay/` and `scripts/` are sibling subdirs of `iro.py`'s dir, so `os.path.join(HERE, "relay"|"scripts", …)` resolves in both. Runtime dir: repo → `<repo>/runtime` (parent of `src/`); package → `<pkgroot>/runtime`.

---

## Task 1: `services.py` daemon helper

**Files:**
- Create: `src/scripts/services.py`
- Test: `tests/test_services.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_services.py
#!/usr/bin/env python3
"""Stdlib checks for the spawned-service daemon helper. Run: python3 tests/test_services.py"""
import os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import services as sv


def t_read_pid_valid(tmp):
    p = os.path.join(tmp, "x.pid"); open(p, "w").write("4321\n")
    assert sv.read_pid(p) == 4321


def t_read_pid_missing_or_garbage(tmp):
    assert sv.read_pid(os.path.join(tmp, "nope.pid")) is None
    p = os.path.join(tmp, "g.pid"); open(p, "w").write("not-a-pid")
    assert sv.read_pid(p) is None


def t_pid_alive_self_and_dead():
    assert sv.pid_alive(os.getpid()) is True
    assert sv.pid_alive(0) is False
    assert sv.pid_alive(2_000_000_000) is False   # implausibly high → not alive


def t_status_line_running_and_stopped():
    assert sv.status_line("relay", 99, True).startswith("relay")
    assert "RUNNING (pid 99)" in sv.status_line("relay", 99, True)
    assert "stopped" in sv.status_line("relay", None, False)


def t_start_detached_then_stop(tmp):
    log = os.path.join(tmp, "logs", "svc.log")
    pidf = os.path.join(tmp, "svc.pid")
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    pid = sv.start_detached(argv, log, pidf)
    assert sv.pid_alive(pid) is True
    assert sv.read_pid(pidf) == pid
    assert sv.stop_pid(pid, pidf, timeout=5) is True
    assert sv.pid_alive(pid) is False
    assert not os.path.exists(pidf)   # pid file removed on stop


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in sorted(globals().items()):
            if name.startswith("t_") and callable(fn):
                import inspect
                fn(tmp) if inspect.signature(fn).parameters else fn()
                print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_services.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'services'`.

- [ ] **Step 3: Write `src/scripts/services.py`**

```python
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


def pid_alive(pid):
    """True iff a process with this PID currently exists (signal-0 probe)."""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def status_line(name, pid, alive, extra=""):
    """One formatted line: 'relay      RUNNING (pid 1234)  <extra>'."""
    state = f"RUNNING (pid {pid})" if alive else "stopped"
    return f"{name:<10} {state}  {extra}".rstrip()


def start_detached(argv, log_path, pid_path):
    """Spawn argv detached, stdout/stderr -> log_path, write pid_path. Returns PID.
    Caller must verify it is not already running first."""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    os.makedirs(os.path.dirname(pid_path), exist_ok=True)
    log = open(log_path, "ab")
    kwargs = {"start_new_session": True} if os.name == "posix" else {}
    proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, **kwargs)
    with open(pid_path, "w") as fh:
        fh.write(str(proc.pid))
    return proc.pid


def stop_pid(pid, pid_path=None, timeout=10):
    """SIGTERM, wait up to timeout, then SIGKILL; remove pid_path. True if gone."""
    if pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        for _ in range(timeout * 2):
            if not pid_alive(pid):
                break
            time.sleep(0.5)
        if pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            time.sleep(0.5)
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_services.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/services.py tests/test_services.py
git commit -m "feat(cli): spawned-service daemon helper (services.py)"
```

---

## Task 2: `iro.py` dispatcher core — `route(argv)`

**Files:**
- Create: `src/iro.py`
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_iro.py
#!/usr/bin/env python3
"""Stdlib checks for the iro dispatcher routing. Run: python3 tests/test_iro.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("iro", os.path.join(ROOT, "src", "iro.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_service_start():
    assert m.route(["relay", "start"]) == \
        {"kind": "service", "command": "relay", "verb": "start", "rest": []}


def t_relay_run_forwards_rest():
    r = m.route(["relay", "run", "--no-pov"])
    assert r["kind"] == "service" and r["verb"] == "run" and r["rest"] == ["--no-pov"]


def t_companion_and_streams_verbs():
    assert m.route(["companion", "logs"])["verb"] == "logs"
    assert m.route(["streams", "restart"])["verb"] == "restart"


def t_aggregate_status():
    assert m.route(["status"]) == {"kind": "aggregate"}


def t_oneshot_with_args():
    assert m.route(["cookies", "chrome"]) == \
        {"kind": "oneshot", "command": "cookies", "rest": ["chrome"]}
    assert m.route(["preflight"])["command"] == "preflight"


def t_help_when_empty():
    assert m.route([])["kind"] == "help"


def t_run_only_valid_for_relay():
    _raises(lambda: m.route(["companion", "run"]))


def t_bad_verb_and_unknown_command_raise():
    _raises(lambda: m.route(["relay", "bogus"]))
    _raises(lambda: m.route(["nonsense"]))


def _raises(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError("expected ValueError")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_iro.py`
Expected: FAIL — `AttributeError: module 'iro' has no attribute 'route'`.

- [ ] **Step 3: Write `src/iro.py` (core only — adapters added in later tasks)**

```python
#!/usr/bin/env python3
"""IRO operator CLI — one entrypoint for every service and setup action.

  python3 src/iro.py relay start        # repo
  python3 iro.py     relay start        # shipped package

  iro relay     start|stop|restart|status|logs|run
  iro companion start|stop|restart|status|logs
  iro streams   start|stop|restart|status|logs
  iro status                            # aggregate health of all services
  iro preflight | cookies [browser] | graphics | media | setup [--out PATH]
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "scripts"))

SERVICES = ("relay", "companion", "streams")
SERVICE_VERBS = ("start", "stop", "restart", "status", "logs")
RELAY_ONLY_VERBS = ("run",)
ONESHOTS = ("preflight", "cookies", "graphics", "media", "setup")

USAGE = __doc__


def route(argv):
    """Resolve argv into an action dict WITHOUT executing. Raises ValueError on bad
    usage. This is the unit-test seam; main() executes the result."""
    if not argv or argv[0] in ("-h", "--help", "help"):
        return {"kind": "help"}
    cmd, rest = argv[0], argv[1:]
    if cmd == "status" and not rest:
        return {"kind": "aggregate"}
    if cmd in SERVICES:
        verb = rest[0] if rest else None
        valid = SERVICE_VERBS + (RELAY_ONLY_VERBS if cmd == "relay" else ())
        if verb not in valid:
            raise ValueError(f"usage: iro {cmd} {{{'|'.join(valid)}}}")
        return {"kind": "service", "command": cmd, "verb": verb, "rest": rest[1:]}
    if cmd in ONESHOTS:
        return {"kind": "oneshot", "command": cmd, "rest": rest}
    raise ValueError(f"unknown command: {cmd}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        action = route(argv)
    except ValueError as e:
        sys.exit(f"iro: {e}")
    if action["kind"] == "help":
        print(USAGE); return
    # Dispatch tables are filled in by later tasks (DISPATCH below).
    raise SystemExit("iro: not yet implemented")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_iro.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/iro.py tests/test_iro.py
git commit -m "feat(cli): iro dispatcher core with route()"
```

---

## Task 3: Relay adapter

**Files:**
- Modify: `src/iro.py` (add path helpers, relay adapter, wire dispatch)

- [ ] **Step 1: Add path helpers + relay adapter to `src/iro.py`**

Insert after the `sys.path.insert(...)` line:

```python
import subprocess
import services as sv

def _runtime_dir():
    """Repo (src/) -> <repo>/runtime ; package (root) -> <pkgroot>/runtime."""
    if os.path.basename(HERE) == "src":
        return os.path.join(os.path.dirname(HERE), "runtime")
    return os.path.join(HERE, "runtime")

def _relay_script():
    return os.path.join(HERE, "relay", "iro-feeds.py")

RELAY_PID = lambda: os.path.join(_runtime_dir(), "relay.pid")
RELAY_LOG = lambda: os.path.join(_runtime_dir(), "logs", "relay.console.log")
RELAY_PORT = 8088
```

Add the adapter functions (anywhere below `route`):

```python
def _tailscale_ip():
    try:
        import companion_common as cc
        return cc.detect_tailscale_ip()
    except Exception:
        return None

def _relay_extra():
    parts = []
    try:
        import urllib.request
        urllib.request.urlopen(f"http://127.0.0.1:{RELAY_PORT}/status", timeout=3).read()
        parts.append(f"control http://127.0.0.1:{RELAY_PORT}/status OK")
    except Exception:
        parts.append(f"(port {RELAY_PORT} not responding)")
    ts = _tailscale_ip()
    if ts:
        parts.append(f"tablet/panel http://{ts}:{RELAY_PORT}/panel")
    return "  ".join(parts)

def relay_start(rest):
    pid = sv.read_pid(RELAY_PID())
    if sv.pid_alive(pid):
        print(f"relay already running (pid {pid}).")
        return relay_status([])
    argv = [sys.executable, _relay_script(), "--runtime-dir", _runtime_dir()] + rest
    newpid = sv.start_detached(argv, RELAY_LOG(), RELAY_PID())
    print(f"relay started (pid {newpid}). Watch it: iro relay logs -f")

def relay_stop(rest):
    pid = sv.read_pid(RELAY_PID())
    if not sv.pid_alive(pid):
        if os.path.exists(RELAY_PID()):
            os.remove(RELAY_PID())
        print("relay is not running.")
        return
    print("relay stopped." if sv.stop_pid(pid, RELAY_PID()) else "relay may still be running.")

def relay_restart(rest):
    relay_stop([]); relay_start(rest)

def relay_status(rest):
    pid = sv.read_pid(RELAY_PID()); alive = sv.pid_alive(pid)
    print(sv.status_line("relay", pid, alive, _relay_extra() if alive else ""))

def relay_logs(rest):
    sv.tail(RELAY_LOG(), follow=("-f" in rest or "--follow" in rest))

def relay_run(rest):
    argv = [sys.executable, _relay_script(), "--runtime-dir", _runtime_dir()] + rest
    raise SystemExit(subprocess.call(argv))
```

- [ ] **Step 2: Wire the dispatch in `main()`**

Replace the `raise SystemExit("iro: not yet implemented")` line with:

```python
    if action["kind"] == "service":
        fn = DISPATCH.get((action["command"], action["verb"]))
        if not fn:
            sys.exit(f"iro: {action['command']} {action['verb']} not implemented yet")
        return fn(action["rest"])
    sys.exit(f"iro: {action['kind']} not implemented yet")
```

And add the dispatch table just above `main()`:

```python
DISPATCH = {
    ("relay", "start"): relay_start, ("relay", "stop"): relay_stop,
    ("relay", "restart"): relay_restart, ("relay", "status"): relay_status,
    ("relay", "logs"): relay_logs, ("relay", "run"): relay_run,
}
```

- [ ] **Step 3: Verify routing unit tests still pass**

Run: `python3 tests/test_iro.py`
Expected: `ALL PASS` (route() unchanged).

- [ ] **Step 4: Integration-verify the relay lifecycle (manual)**

Run each and confirm the expected:
```bash
python3 src/iro.py relay start     # -> "relay started (pid N)"
sleep 6
python3 src/iro.py relay status    # -> "relay  RUNNING (pid N)  control ... OK  tablet/panel http://100.x:8088/panel"
python3 src/iro.py relay logs | head -5   # -> shows the relay banner lines
python3 src/iro.py relay stop      # -> "relay stopped."
python3 src/iro.py relay status    # -> "relay      stopped"
```
Confirm `runtime/relay.pid` is gone after stop and `runtime/logs/relay.console.log` exists.

- [ ] **Step 5: Commit**

```bash
git add src/iro.py
git commit -m "feat(cli): iro relay adapter (start/stop/restart/status/logs/run)"
```

---

## Task 4: Companion adapter (+ delete old companion entrypoints)

**Files:**
- Modify: `src/iro.py` (companion adapter, dispatch)
- Delete: `src/scripts/start-companion.py`, `src/scripts/stop-companion.py`

The orchestration currently in `start-companion.py` / `stop-companion.py` moves into
`iro.py`; the pure logic stays in `companion_common.py` (unchanged, still tested by
`tests/test_companion.py`).

- [ ] **Step 1: Add the companion adapter to `src/iro.py`**

```python
import glob, json, shutil, time

def _companion():
    import companion_common as cc
    return cc

def _companion_running(cc):
    cmds = cc.companion_control_commands(sys.platform)
    return cmds and subprocess.run(cmds["running"], capture_output=True).returncode == 0

def companion_start(rest):
    cc = _companion()
    cmds = cc.companion_control_commands(sys.platform)
    if cmds is None:
        sys.exit(f"companion: automated start is macOS-only (this is {sys.platform}). "
                 "Set Companion's Admin GUI interface to your Tailscale IP manually.")
    bind_arg = rest[0] if rest else "auto"
    cfg_path = cc.companion_config_path(sys.platform)
    if not os.path.exists(cfg_path):
        sys.exit(f"companion: config not found at {cfg_path}. Launch Companion once, then retry.")
    text = open(cfg_path, encoding="utf-8").read()
    cfg = json.loads(text)
    current, port = cfg.get("bind_ip", "127.0.0.1"), cfg.get("http_port", 8000)
    ts = cc.detect_tailscale_ip()
    desired = cc.desired_bind_ip(bind_arg, ts)
    if bind_arg == "auto" and not ts:
        print("  (warn) no Tailscale IP found — binding 127.0.0.1 (local only).")
    plan = cc.plan_companion_action(current, desired, _companion_running(cc))
    if plan["stop_first"]:
        print("Stopping Companion to change its bind address…")
        subprocess.run(cmds["quit"], capture_output=True)
        for _ in range(30):
            if not _companion_running(cc):
                break
            time.sleep(0.5)
        else:
            sys.exit("companion: did not stop in time; aborting (config untouched).")
    if plan["edit"]:
        shutil.copy2(cfg_path, cfg_path + ".iro-bak")
        tmp = cfg_path + ".tmp"
        open(tmp, "w", encoding="utf-8").write(cc.config_with_bind_ip(text, desired))
        os.replace(tmp, cfg_path)
        print(f"Set Companion bind_ip {current} -> {desired} (backup: {cfg_path}.iro-bak)")
    if plan["start"]:
        print("Starting Companion…")
        subprocess.run(cmds["start"], capture_output=True)
    else:
        print(f"Companion already bound to {desired} and running.")
    host = desired if desired != "0.0.0.0" else (ts or "<this-machine-ip>")
    print(f"Companion buttons (tablet): http://{host}:{port}/tablet")
    print("  Admin GUI shares this port — restrict who reaches it with a Tailscale ACL.")

def companion_stop(rest):
    cc = _companion()
    cmds = cc.companion_control_commands(sys.platform)
    if cmds is None:
        sys.exit(f"companion: automated stop is macOS-only (this is {sys.platform}).")
    if not _companion_running(cc):
        print("companion is not running."); return
    print("Stopping Companion…")
    subprocess.run(cmds["quit"], capture_output=True)
    for _ in range(30):
        if not _companion_running(cc):
            print("companion stopped."); return
        time.sleep(0.5)
    print("companion may still be running. Force-quit: pkill -f Companion")

def companion_restart(rest):
    companion_stop([]); companion_start(rest)

def companion_status(rest):
    cc = _companion()
    if cc.companion_control_commands(sys.platform) is None:
        print(sv.status_line("companion", None, False, f"(unsupported on {sys.platform})")); return
    running = _companion_running(cc)
    extra = ""
    if running:
        cfg_path = cc.companion_config_path(sys.platform)
        try:
            cfg = json.load(open(cfg_path, encoding="utf-8"))
            extra = f"http://{cfg.get('bind_ip')}:{cfg.get('http_port', 8000)}/tablet"
        except Exception:
            extra = ""
    print(sv.status_line("companion", "?" if running else None, running, extra))

def companion_logs(rest):
    cc = _companion()
    logdir = os.path.join(os.path.dirname(cc.companion_config_path(sys.platform)), "logs")
    logs = sorted(glob.glob(os.path.join(logdir, "*")), key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
    if not logs:
        print(f"(no Companion logs at {logdir})"); return
    sv.tail(logs[-1], follow=("-f" in rest or "--follow" in rest))
```

- [ ] **Step 2: Add companion entries to `DISPATCH`**

```python
    ("companion", "start"): companion_start, ("companion", "stop"): companion_stop,
    ("companion", "restart"): companion_restart, ("companion", "status"): companion_status,
    ("companion", "logs"): companion_logs,
```

- [ ] **Step 3: Delete the old entrypoints**

```bash
git rm src/scripts/start-companion.py src/scripts/stop-companion.py
```

- [ ] **Step 4: Verify companion_common tests still pass + integration-verify**

Run: `python3 tests/test_companion.py` → `ALL PASS`.
Then (macOS, Companion installed):
```bash
python3 src/iro.py companion start    # -> sets bind_ip to Tailscale IP, starts Companion, prints tablet URL
sleep 12
python3 src/iro.py companion status   # -> "companion  RUNNING (pid ?)  http://100.x:8000/tablet"
python3 src/iro.py companion stop     # -> "companion stopped."
```

- [ ] **Step 5: Commit**

```bash
git add src/iro.py
git commit -m "feat(cli): iro companion adapter; drop start-/stop-companion.py entrypoints"
```

---

## Task 5: Streams adapter

**Files:**
- Modify: `src/iro.py` (streams adapter, dispatch)

The streams implementation (`start-streams.py`, `stop-streams.py`, `loopstream.py`)
stays; the adapter sub-processes it and reads its PID/log files under
`runtime/static/`.

- [ ] **Step 1: Add the streams adapter to `src/iro.py`**

```python
def _streams_script(name):
    return os.path.join(HERE, "scripts", name)

def _streams_static_dir():
    return os.path.join(_runtime_dir(), "static")

def streams_start(rest):
    raise SystemExit(subprocess.call([sys.executable, _streams_script("start-streams.py")] + rest))

def streams_stop(rest):
    subprocess.call([sys.executable, _streams_script("stop-streams.py")] + rest)

def streams_restart(rest):
    streams_stop([]); streams_start(rest)

def streams_status(rest):
    pidfiles = sorted(glob.glob(os.path.join(_streams_static_dir(), "feed_*.pid")))
    if not pidfiles:
        print(sv.status_line("streams", None, False, "(no feeds started)")); return
    for pf in pidfiles:
        pid = sv.read_pid(pf)
        label = "streams:" + os.path.basename(pf)[len("feed_"):-len(".pid")]
        print(sv.status_line(label, pid, sv.pid_alive(pid)))

def streams_logs(rest):
    logs = sorted(glob.glob(os.path.join(_streams_static_dir(), "logs", "feed_*.log")),
                  key=lambda p: os.path.getmtime(p))
    if not logs:
        print(f"(no stream logs under {os.path.join(_streams_static_dir(), 'logs')})"); return
    sv.tail(logs[-1], follow=("-f" in rest or "--follow" in rest))
```

- [ ] **Step 2: Add streams entries to `DISPATCH`**

```python
    ("streams", "start"): streams_start, ("streams", "stop"): streams_stop,
    ("streams", "restart"): streams_restart, ("streams", "status"): streams_status,
    ("streams", "logs"): streams_logs,
```

- [ ] **Step 3: Verify routing + smoke**

Run: `python3 tests/test_iro.py` → `ALL PASS`.
Run: `python3 src/iro.py streams status` → `streams     stopped  (no feeds started)` (when none running).

- [ ] **Step 4: Commit**

```bash
git add src/iro.py
git commit -m "feat(cli): iro streams adapter over the existing static-mode scripts"
```

---

## Task 6: One-shot wrappers + aggregate `iro status`

**Files:**
- Modify: `src/iro.py`

- [ ] **Step 1: Add one-shot wrappers + aggregate status**

```python
def _run(script_relpath, rest):
    raise SystemExit(subprocess.call([sys.executable, os.path.join(HERE, script_relpath)] + rest))

ONESHOT_MAP = {
    "preflight": "scripts/preflight.py",
    "cookies":   "relay/get-cookies.py",
    "graphics":  "relay/get-graphics.py",
    "media":     "relay/get-media.py",
    "setup":     "setup-assets.py",
}

def oneshot(command, rest):
    rel = ONESHOT_MAP[command]
    # cookies/graphics/media run from src/relay and accept --runtime-dir
    extra = ["--runtime-dir", _runtime_dir()] if command in ("cookies", "graphics", "media") else []
    raise SystemExit(subprocess.call([sys.executable, os.path.join(HERE, rel)] + rest + extra))

def aggregate_status(_rest=None):
    relay_status([])
    companion_status([])
    streams_status([])
```

Note: confirm `get-graphics.py` / `get-media.py` accept `--runtime-dir`; if a script
does not, drop it from the `extra` set for that command. (`get-cookies.py` does, per
CLAUDE.md.) Verify in Step 3 and adjust the membership of the `extra` condition.

- [ ] **Step 2: Wire one-shot + aggregate dispatch in `main()`**

Replace the final `sys.exit(f"iro: {action['kind']} not implemented yet")` with:

```python
    if action["kind"] == "oneshot":
        return oneshot(action["command"], action["rest"])
    if action["kind"] == "aggregate":
        return aggregate_status()
    sys.exit(f"iro: {action['kind']} not implemented")
```

- [ ] **Step 3: Verify**

```bash
python3 tests/test_iro.py            # ALL PASS
python3 src/iro.py preflight          # runs the preflight check
python3 src/iro.py status             # three status lines: relay / companion / streams
python3 src/iro.py cookies --help 2>&1 | head -3   # confirms forwarding + --runtime-dir accepted
```
If `cookies`/`graphics`/`media` reject `--runtime-dir`, remove them from the `extra`
condition and re-verify.

- [ ] **Step 4: Commit**

```bash
git add src/iro.py
git commit -m "feat(cli): iro one-shot wrappers + aggregate status"
```

---

## Task 7: Migration — remove run-relay.py; update build verify

**Files:**
- Delete: `tools/run-relay.py`
- Modify: `tools/build.py` (verify block)

- [ ] **Step 1: Delete the obsolete wrapper**

```bash
git rm tools/run-relay.py
```

- [ ] **Step 2: Add build-verify checks**

In `tools/build.py`, find the verify section (the block printing `[OK] …` checks) and
add, alongside the existing checks (keep them all):

```python
    _check("iro cli shipped", os.path.exists(os.path.join(PKG, "iro.py")))
    _check("services helper shipped", os.path.exists(os.path.join(PKG, "scripts", "services.py")))
    for gone in ("scripts/start-companion.py", "scripts/stop-companion.py"):
        _check(f"old entrypoint removed: {gone}", not os.path.exists(os.path.join(PKG, gone)))
```

Use the file's existing check helper/idiom — match how the current `[OK]`/`[FAIL]`
lines are emitted (replace `_check` with the real helper name found in `build.py`).

- [ ] **Step 3: Verify the build passes**

Run: `python3 tools/build.py`
Expected: ends with the package built and all `[OK] …` lines including the new
`iro cli shipped`, `services helper shipped`, `old entrypoint removed: …`.

- [ ] **Step 4: Commit**

```bash
git add tools/build.py
git commit -m "build: ship iro.py + services.py, verify old entrypoints removed"
```

---

## Task 8: Docs — README + CLAUDE.md

**Files:**
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: Rewrite the operator commands in `README.md`**

Replace relay/companion run instructions with the `iro` surface:

```markdown
## Run it

    python3 src/iro.py preflight            # check tools/hardware
    python3 src/iro.py relay start          # start the relay (background)
    python3 src/iro.py relay logs -f        # watch it live
    python3 src/iro.py relay status         # health + tailnet URL
    python3 src/iro.py companion start      # bind Companion to Tailscale, start it
    python3 src/iro.py status               # all services at a glance
    python3 src/iro.py relay stop           # stop the relay

(In the distributed package the same commands are `python3 iro.py …`.)
For live debugging you can still run the relay in the foreground: `python3 src/iro.py relay run`.
```

- [ ] **Step 2: Update `CLAUDE.md`**

In the "Commands" block, replace the `tools/run-relay.py` line and the
`start-companion.py`/`stop-companion.py` lines with the `iro` commands above; add
`python3 tests/test_services.py` and `python3 tests/test_iro.py` to the tests list.
In the architecture section, replace the "Companion remote-access helpers" + "Static
mode" entrypoint descriptions with a short "Unified `iro` CLI" subsection: dispatcher
`src/iro.py` → `services.py` daemon helper (relay, streams) + companion adapter
(`companion_common.py`) + one-shot wrappers; note `tools/` is now maintainer-only.

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: operator commands move to the unified iro CLI"
```

---

## Task 9: Final verification

- [ ] **Step 1: Run the full test suite**

```bash
for t in tests/test_services.py tests/test_iro.py tests/test_bind.py \
         tests/test_companion.py tests/test_pov.py tests/test_preflight.py tests/test_hud.py; do
  python3 "$t" >/tmp/t.out 2>&1 && echo "PASS $t" || { echo "FAIL $t"; tail -8 /tmp/t.out; }
done
```
Expected: all `PASS`.

- [ ] **Step 2: Build + self-verify**

Run: `python3 tools/build.py`
Expected: package built, every `[OK]` check passes (incl. the new ones), no `[FAIL]`.

- [ ] **Step 3: End-to-end smoke**

```bash
python3 src/iro.py relay start && sleep 6 && python3 src/iro.py status
python3 src/iro.py relay stop
```
Expected: relay shows RUNNING with the tailnet URL, then stopped.

- [ ] **Step 4: Final commit (if any docs/cleanup remain)**

```bash
git add -A && git commit -m "chore: finalize unified iro CLI" || echo "nothing to finalize"
```

---

## Self-review notes (for the implementer)

- **Spec coverage:** command surface (Task 2–6), relay daemonization + `run` (Task 3),
  companion macOS adapter (Task 4), streams over existing scripts (Task 5), one-shots +
  aggregate (Task 6), migration + build verify (Task 7), docs (Task 8). All spec
  sections map to a task.
- **Known verification gates:** the `--runtime-dir` forwarding for `graphics`/`media`
  (Task 6 Step 3) and the real `build.py` check-helper name (Task 7 Step 2) must be
  confirmed against the code during execution — both are called out inline.
- **No behaviour change** to the relay pull pipeline, OBS collection, HUD, or the
  Tailscale dual-bind; `iro relay run` reproduces today's foreground behaviour.
```
