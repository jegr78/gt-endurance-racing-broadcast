# IRO Control Center — Phase 1 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local Control Center web app served by `iro ui` (stdlib HTTP server, port 8089 / `IRO_UI_PORT`) with a status dashboard, service start/stop as live-logged jobs, SSE log tails, and a quit button — plus the print→dict status refactor that gives CLI and UI one shared core.

**Architecture:** New `src/ui/` modules (`ui_ops.py` registry, `ui_jobs.py` job manager, `ui_server.py` HTTP server, `control-center.html` single static page in the director-panel style). `src/iro.py` gains structured `*_status_data()` functions (the CLI renders them as text, the UI serves them as JSON) and a `ui` subcommand. Long-running actions run as subprocesses of `iro` itself (`python3 src/iro.py …` in repo mode; the frozen binary re-invokes itself), with output streamed to the browser via Server-Sent Events.

**Tech Stack:** Python stdlib only (`http.server`, `threading`, `subprocess`, `json`), vanilla HTML/JS. No new dependencies. Spec: `docs/superpowers/specs/2026-06-07-control-center-design.md`.

**Conventions you must follow (from CLAUDE.md):**
- Tests are runnable scripts (no pytest): `python3 tests/test_X.py`. Each `t_*` function is run by the `__main__` loop; `tools/run-tests.py` globs `tests/test_*.py` automatically — no registration needed.
- After changing any Python file run `python3 tools/lint.py` (ruff; `--fix` auto-corrects).
- All code/docs/UI text English only. No real IPs or machine paths in tests.
- Edit only under `src/` (+ `tests/`, docs). Never touch `dist/` or `runtime/`.
- Module naming: the new modules are `ui_server.py` / `ui_jobs.py` / `ui_ops.py` (NOT `server.py`/`jobs.py`/`ops.py` as the spec sketches) — they are imported via `sys.path` insertion like `src/scripts/`, and bare names like `jobs` are too collision-prone there and in the frozen bundle.

---

### Task 1: Relay status refactor — `relay_status_data()`

The CLI's `relay_status()` prints; the UI needs the same facts as a dict. Split data from presentation. All injection-friendly (house style, cf. `pick_ca_bundle(exists=...)`).

**Files:**
- Create: `tests/test_ui_ops.py`
- Modify: `src/iro.py` (functions `_relay_extra` at ~392 and `relay_status` at ~527)

- [ ] **Step 1: Write the failing test**

Create `tests/test_ui_ops.py`:

```python
#!/usr/bin/env python3
"""Stdlib checks for the Control Center's structured status providers in iro.py.
Run: python3 tests/test_ui_ops.py"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
import iro


# ---------- relay ----------

def t_relay_status_data_running():
    d = iro.relay_status_data(read_pid=lambda p: 4242,
                              alive=lambda pid: True,
                              http_ok=lambda: True)
    assert d == {"pid": 4242, "alive": True, "port": 8088, "http_ok": True}


def t_relay_status_data_stopped_skips_http_probe():
    probed = []
    d = iro.relay_status_data(read_pid=lambda p: None,
                              alive=lambda pid: False,
                              http_ok=lambda: probed.append(1) or True)
    assert d == {"pid": None, "alive": False, "port": 8088, "http_ok": False}
    assert probed == []   # never probe HTTP for a dead relay


def t_relay_extra_text_ok_with_tailscale():
    d = {"pid": 1, "alive": True, "port": 8088, "http_ok": True}
    text = iro._relay_extra_text(d, "100.64.0.7")
    assert "control http://127.0.0.1:8088/status OK" in text
    assert "tablet/panel http://100.64.0.7:8088/panel" in text


def t_relay_extra_text_port_down_no_tailscale():
    d = {"pid": 1, "alive": True, "port": 8088, "http_ok": False}
    text = iro._relay_extra_text(d, None)
    assert text == "(port 8088 not responding)"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run it — must fail**

Run: `python3 tests/test_ui_ops.py`
Expected: `AttributeError: module 'iro' has no attribute 'relay_status_data'`

- [ ] **Step 3: Implement in `src/iro.py`**

Replace the existing `_relay_extra()` (the `def _relay_extra():` block directly under `_relay_http_ok`) with:

```python
def relay_status_data(read_pid=None, alive=None, http_ok=None):
    """Structured relay state — one source for `iro status` (text) and the
    Control Center's /api/status (JSON). Injection points are for tests."""
    read_pid = read_pid or sv.read_pid
    alive = alive or sv.pid_alive
    http_ok = http_ok or _relay_http_ok
    pid = read_pid(_relay_pid_path())
    is_alive = alive(pid)
    return {"pid": pid, "alive": is_alive, "port": RELAY_PORT,
            "http_ok": http_ok() if is_alive else False}


def _relay_extra_text(data, tailscale_ip):
    """The CLI's extra column for a live relay, from relay_status_data()."""
    parts = [f"control http://127.0.0.1:{data['port']}/status OK" if data["http_ok"]
             else f"(port {data['port']} not responding)"]
    if tailscale_ip:
        parts.append(f"tablet/panel http://{tailscale_ip}:{data['port']}/panel")
    return "  ".join(parts)
```

Replace the body of `relay_status()` (~line 527):

```python
def relay_status(rest):
    d = relay_status_data()
    extra = _relay_extra_text(d, _tailscale_ip()) if d["alive"] else ""
    print(sv.status_line("relay", d["pid"], d["alive"], extra))
```

- [ ] **Step 4: Grep for stale callers of the removed helper**

Run: `grep -rn "_relay_extra\b" src/ tests/ tools/ .github/ | grep -v _relay_extra_text`
Expected: no hits (only `relay_status` used it). If anything else shows up, update it.

- [ ] **Step 5: Run tests + lint**

Run: `python3 tests/test_ui_ops.py` → `ALL PASS`
Run: `python3 tests/test_iro.py` → `ALL PASS` (routing untouched, sanity)
Run: `python3 tools/lint.py` → clean

- [ ] **Step 6: Commit**

```bash
git add tests/test_ui_ops.py src/iro.py
git commit -m "refactor(iro): relay status as structured data (relay_status_data)"
```

---

### Task 2: Companion + streams status data, aggregate payload, log-path helpers

**Files:**
- Modify: `src/iro.py` (`companion_status` ~639, `companion_logs` ~659, `streams_status` ~693, `streams_logs` ~703, `aggregate_status` ~1096)
- Test: `tests/test_ui_ops.py` (extend)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_ui_ops.py`, above the `__main__` block)

```python
# ---------- companion ----------

def t_companion_payload_running_with_config():
    d = iro.companion_status_payload(True, True,
                                     {"bind_ip": "100.64.0.7", "http_port": 8000})
    assert d == {"supported": True, "running": True,
                 "url": "http://100.64.0.7:8000/tablet", "why": ""}


def t_companion_payload_running_no_config():
    d = iro.companion_status_payload(True, True, None)
    assert d["running"] is True and d["url"] is None


def t_companion_payload_unsupported():
    d = iro.companion_status_payload(False, False, None, "(manual on linux)")
    assert d == {"supported": False, "running": False, "url": None,
                 "why": "(manual on linux)"}


# ---------- streams ----------

def t_streams_status_data_labels(tmp):
    p1 = os.path.join(tmp, "feed_53001.pid")
    with open(p1, "w") as fh:
        fh.write(str(os.getpid()))          # a live PID -> alive True
    p2 = os.path.join(tmp, "feed_53002.pid")
    with open(p2, "w") as fh:
        fh.write("garbage")                 # unreadable -> pid None, alive False
    feeds = iro.streams_status_data(pidfiles=[p1, p2])
    assert feeds == [
        {"label": "53001", "pid": os.getpid(), "alive": True},
        {"label": "53002", "pid": None, "alive": False}]


def t_streams_status_data_empty():
    assert iro.streams_status_data(pidfiles=[]) == []


# ---------- aggregate payload ----------

def t_ui_status_payload_shape():
    payload = iro.ui_status_payload(
        relay=lambda: {"alive": False}, companion=lambda: {"running": False},
        streams=lambda: [], tailscale=lambda: None)
    assert payload == {"version": iro.version(), "relay": {"alive": False},
                       "companion": {"running": False}, "streams": [],
                       "tailscale_ip": None}
```

Change the `__main__` runner to pass a tempdir (same pattern as `tests/test_services.py`):

```python
if __name__ == "__main__":
    import inspect, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in sorted(globals().items()):
            if name.startswith("t_") and callable(fn):
                fn(tmp) if inspect.signature(fn).parameters else fn()
                print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run it — must fail**

Run: `python3 tests/test_ui_ops.py`
Expected: `AttributeError: ... 'companion_status_payload'`

- [ ] **Step 3: Implement in `src/iro.py`**

Insert above `companion_status` (~line 639):

```python
def companion_status_payload(supported, running, cfg, why=""):
    """Pure: shape the companion status dict from probed facts."""
    url = None
    if running and cfg:
        url = f"http://{cfg.get('bind_ip', '127.0.0.1')}:{cfg.get('http_port', 8000)}/tablet"
    return {"supported": supported, "running": running, "url": url, "why": why}


def companion_status_data():
    """Probe Companion and shape the result (best effort — a broken probe
    reports as unsupported, never raises)."""
    try:
        cc = _companion()
        cmds = _companion_cmds(cc)
    except Exception as exc:
        return companion_status_payload(False, False, None, f"check failed: {exc}")
    if cmds is None:
        why = ("(Companion.exe not found — set IRO_COMPANION_EXE in .env)"
               if sys.platform.startswith("win") else f"(manual on {sys.platform})")
        return companion_status_payload(False, False, None, why)
    running = _companion_running(cc)
    cfg = None
    if running:
        try:
            with open(cc.companion_config_path(sys.platform), encoding="utf-8") as fh:
                cfg = json.load(fh)
        except Exception:
            cfg = None
    return companion_status_payload(True, running, cfg)
```

Replace the body of `companion_status()` — the printed line must stay byte-identical to today's output in every case:

```python
def companion_status(rest):
    d = companion_status_data()
    print(sv.status_line("companion", "?" if d["running"] else None,
                         d["running"], d["url"] or d["why"]))
```

Insert above `streams_status()` (~line 693):

```python
def streams_status_data(pidfiles=None):
    """Structured per-feed state of the static-streams mode."""
    if pidfiles is None:
        pidfiles = sorted(glob.glob(os.path.join(_streams_static_dir(), "feed_*.pid")))
    feeds = []
    for pf in pidfiles:
        pid = sv.read_pid(pf)
        feeds.append({"label": os.path.basename(pf)[len("feed_"):-len(".pid")],
                      "pid": pid, "alive": sv.pid_alive(pid)})
    return feeds
```

Replace the body of `streams_status()`:

```python
def streams_status(rest):
    feeds = streams_status_data()
    if not feeds:
        print(sv.status_line("streams", None, False, "(no feeds started)"))
        return
    for f in feeds:
        print(sv.status_line("streams:" + f["label"], f["pid"], f["alive"]))
```

Extract the latest-log helpers (the Control Center's log tails need paths, not prints). In `companion_logs()` (~659) and `streams_logs()` (~703), replace the glob blocks:

```python
def _companion_log_path():
    """Newest Companion log file, or None (no logs / unsupported platform)."""
    try:
        cc = _companion()
        logdir = os.path.join(os.path.dirname(cc.companion_config_path(sys.platform)), "logs")
        logs = sorted(glob.glob(os.path.join(logdir, "*")), key=os.path.getmtime)
        return logs[-1] if logs else None
    except Exception:
        return None


def companion_logs(rest):
    path = _companion_log_path()
    if not path:
        print("(no Companion logs found)")
        return
    sv.tail(path, follow=("-f" in rest or "--follow" in rest))
```

```python
def _latest_stream_log():
    """Newest static-feed log file, or None."""
    logs = sorted(glob.glob(os.path.join(_streams_static_dir(), "logs", "feed_*.log")),
                  key=os.path.getmtime)
    return logs[-1] if logs else None


def streams_logs(rest):
    path = _latest_stream_log()
    if not path:
        print(f"(no stream logs under {os.path.join(_streams_static_dir(), 'logs')})")
        return
    sv.tail(path, follow=("-f" in rest or "--follow" in rest))
```

Insert below `aggregate_status()` (~1096):

```python
def ui_status_payload(relay=None, companion=None, streams=None, tailscale=None):
    """Aggregate health for the Control Center dashboard (/api/status)."""
    return {"version": version(),
            "relay": (relay or relay_status_data)(),
            "companion": (companion or companion_status_data)(),
            "streams": (streams or streams_status_data)(),
            "tailscale_ip": (tailscale or _tailscale_ip)()}
```

- [ ] **Step 4: Run tests + lint**

Run: `python3 tests/test_ui_ops.py` → `ALL PASS`
Run: `python3 tools/run-tests.py` → `ALL TEST FILES PASS` (the status refactor touches shared code paths)
Run: `python3 tools/lint.py` → clean

- [ ] **Step 5: Commit**

```bash
git add tests/test_ui_ops.py src/iro.py
git commit -m "refactor(iro): companion/streams status + aggregate payload as structured data"
```

---

### Task 3: `src/ui/ui_ops.py` — operation registry + job argv

**Files:**
- Create: `src/ui/ui_ops.py`
- Test: `tests/test_ui_ops.py` (extend)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_ui_ops.py`; add the import at the top of the file, below `import iro`)

```python
sys.path.insert(0, os.path.join(ROOT, "src", "ui"))
import ui_ops
```

```python
# ---------- ui_ops registry ----------

def t_ops_registry_shape():
    assert ui_ops.OPS["relay-start"] == ["relay", "start"]
    assert ui_ops.OPS["obs-refresh"] == ["obs", "refresh"]
    for name, argv in ui_ops.OPS.items():
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv), name


def t_job_argv_repo_mode():
    argv = ui_ops.job_argv(["relay", "start"], frozen=False,
                           executable="/usr/bin/python3", iro_script="/repo/src/iro.py")
    assert argv == ["/usr/bin/python3", "/repo/src/iro.py", "relay", "start"]


def t_job_argv_frozen_reinvokes_binary():
    argv = ui_ops.job_argv(["relay", "stop"], frozen=True,
                           executable="/opt/iro/iro", iro_script="/ignored")
    assert argv == ["/opt/iro/iro", "relay", "stop"]
```

- [ ] **Step 2: Run it — must fail**

Run: `python3 tests/test_ui_ops.py`
Expected: `ModuleNotFoundError: No module named 'ui_ops'`

- [ ] **Step 3: Create `src/ui/ui_ops.py`**

```python
"""Control Center operation registry: which `iro` invocations the web UI may
trigger, and how to build the child argv. Pure data + pure helpers (no I/O) —
the UI server routes /api/op/<name> through this table only, so the HTTP
surface can never run arbitrary commands."""

# name -> iro argv. Phase 1: service control + the OBS page refresh.
# Phase 2 adds the one-shots (installs, graphics, media, cookies, preflight, …).
OPS = {
    "relay-start": ["relay", "start"],
    "relay-stop": ["relay", "stop"],
    "relay-restart": ["relay", "restart"],
    "companion-start": ["companion", "start"],
    "companion-stop": ["companion", "stop"],
    "companion-restart": ["companion", "restart"],
    "streams-start": ["streams", "start"],
    "streams-stop": ["streams", "stop"],
    "obs-refresh": ["obs", "refresh"],
}


def job_argv(op_args, frozen, executable, iro_script):
    """argv to run `iro <op_args...>` as a child process: the frozen binary
    re-invokes itself (same mechanism as the daemon spawns); repo/package mode
    runs iro.py with this interpreter."""
    if frozen:
        return [executable] + list(op_args)
    return [executable, iro_script] + list(op_args)
```

- [ ] **Step 4: Run tests + lint**

Run: `python3 tests/test_ui_ops.py` → `ALL PASS`
Run: `python3 tools/lint.py` → clean

- [ ] **Step 5: Commit**

```bash
git add src/ui/ui_ops.py tests/test_ui_ops.py
git commit -m "feat(ui): operation registry + child argv helper (ui_ops)"
```

---

### Task 4: `src/ui/ui_jobs.py` — job manager

Runs one `iro` child per triggered operation, keeps its output lines in memory for polling/SSE, refuses a second concurrent run of the same op.

**Files:**
- Create: `src/ui/ui_jobs.py`
- Create: `tests/test_ui_jobs.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui_jobs.py`:

```python
#!/usr/bin/env python3
"""Stdlib checks for the Control Center job manager.
Run: python3 tests/test_ui_jobs.py"""
import io, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "ui"))
import ui_jobs


class FakeProc:
    """Minimal Popen stand-in: canned stdout, fixed exit code."""
    def __init__(self, out=b"line1\nline2\n", code=0):
        self.stdout = io.BytesIO(out)
        self._code = code
        self.returncode = None
    def wait(self):
        self.returncode = self._code
        return self._code


def _wait_done(jm, job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = jm.snapshot(job_id)
        if snap and snap["exit_code"] is not None:
            return snap
        time.sleep(0.05)
    raise AssertionError("job did not finish in time")


def t_start_collects_lines_and_exit():
    jm = ui_jobs.JobManager(lambda a: ["ignored"], spawn=lambda argv: FakeProc())
    job_id, err = jm.start("echo", ["x"])
    assert err is None and job_id
    snap = _wait_done(jm, job_id)
    assert snap["op"] == "echo" and snap["exit_code"] == 0
    lines, nxt, code = jm.lines_since(job_id, 0)
    assert lines == ["line1", "line2"] and nxt == 2 and code == 0


def t_lines_since_resumes_at_index():
    jm = ui_jobs.JobManager(lambda a: ["ignored"], spawn=lambda argv: FakeProc())
    job_id, _ = jm.start("echo", [])
    _wait_done(jm, job_id)
    lines, nxt, _ = jm.lines_since(job_id, 1)
    assert lines == ["line2"] and nxt == 2
    lines, nxt, _ = jm.lines_since(job_id, 2)
    assert lines == [] and nxt == 2


def t_duplicate_op_refused_while_running():
    class NeverEnds(FakeProc):
        def __init__(self):
            super().__init__()
            self.stdout = io.BufferedReader(io.BytesIO(b""))  # immediate EOF...
        def wait(self):
            time.sleep(0.3)                                    # ...but slow exit
            self.returncode = 0
            return 0
    jm = ui_jobs.JobManager(lambda a: ["ignored"], spawn=lambda argv: NeverEnds())
    job_id, err = jm.start("slow", [])
    assert err is None
    _id2, err2 = jm.start("slow", [])
    assert _id2 is None and "already running" in err2
    _wait_done(jm, job_id)
    job_id3, err3 = jm.start("slow", [])      # finished -> may run again
    assert err3 is None and job_id3 != job_id


def t_trim_keeps_since_semantics():
    out = b"".join(b"l%d\n" % i for i in range(10))
    jm = ui_jobs.JobManager(lambda a: ["ignored"],
                            spawn=lambda argv: FakeProc(out=out), max_lines=4)
    job_id, _ = jm.start("big", [])
    _wait_done(jm, job_id)
    lines, nxt, _ = jm.lines_since(job_id, 0)
    assert lines == ["l6", "l7", "l8", "l9"] and nxt == 10   # head trimmed, indices stable


def t_unknown_job_id():
    jm = ui_jobs.JobManager(lambda a: ["ignored"])
    assert jm.snapshot("nope") is None
    assert jm.lines_since("nope", 0) == (None, 0, None)


def t_real_subprocess_lifecycle():
    code = "print('hello'); import sys; sys.exit(3)"
    jm = ui_jobs.JobManager(lambda a: [sys.executable, "-c", code])
    job_id, err = jm.start("real", ["unused"])
    assert err is None
    snap = _wait_done(jm, job_id, timeout=15)
    assert snap["exit_code"] == 3
    lines, _, _ = jm.lines_since(job_id, 0)
    assert lines == ["hello"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run it — must fail**

Run: `python3 tests/test_ui_jobs.py`
Expected: `ModuleNotFoundError: No module named 'ui_jobs'`

- [ ] **Step 3: Create `src/ui/ui_jobs.py`**

```python
"""Control Center job manager: run one `iro <args>` child per triggered
operation, keep its combined stdout/stderr lines in memory for the web UI
(poll or SSE), and refuse a second concurrent run of the same operation.
Jobs are subprocesses (not threads) because sys.stdout is process-global —
parallel in-process ops would interleave output — and a child can be killed.
Spec: docs/superpowers/specs/2026-06-07-control-center-design.md."""
import subprocess, threading, uuid


class Job:
    def __init__(self, job_id, op, proc):
        self.id, self.op, self.proc = job_id, op, proc
        self.lines = []          # decoded output lines (head-trimmed, see dropped)
        self.dropped = 0         # lines trimmed off the head — keeps indices stable
        self.exit_code = None
        self.lock = threading.Lock()


class JobManager:
    def __init__(self, argv_for, env=None, spawn=None, max_lines=5000):
        """argv_for(op_args) -> child argv (see ui_ops.job_argv). env: full
        child environment or None (inherit). spawn: Popen-compatible test seam."""
        self.argv_for, self.env = argv_for, env
        self.spawn = spawn or self._spawn
        self.max_lines = max_lines
        self.jobs = {}           # job_id -> Job
        self.lock = threading.Lock()

    def _spawn(self, argv):
        return subprocess.Popen(argv, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=self.env)

    def start(self, op, op_args):
        """Start `op` unless one is still running. Returns (job_id, None) or
        (None, error-text)."""
        with self.lock:
            for job in self.jobs.values():
                if job.op == op and job.exit_code is None:
                    return None, f"{op} is already running"
            proc = self.spawn(self.argv_for(op_args))
            job = Job(uuid.uuid4().hex[:12], op, proc)
            self.jobs[job.id] = job
        threading.Thread(target=self._reader, args=(job,), daemon=True).start()
        return job.id, None

    def _reader(self, job):
        for raw in job.proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            with job.lock:
                job.lines.append(line)
                overflow = len(job.lines) - self.max_lines
                if overflow > 0:
                    del job.lines[:overflow]
                    job.dropped += overflow
        code = job.proc.wait()
        with job.lock:
            job.exit_code = code

    def snapshot(self, job_id):
        """{'id','op','running','exit_code'} or None for an unknown id."""
        job = self.jobs.get(job_id)
        if job is None:
            return None
        with job.lock:
            return {"id": job.id, "op": job.op,
                    "running": job.exit_code is None, "exit_code": job.exit_code}

    def lines_since(self, job_id, since):
        """(new lines from absolute index `since`, next index, exit_code).
        (None, since, None) for an unknown id. Head-trimmed lines are skipped —
        `since` stays an absolute position so SSE/poll clients never re-read."""
        job = self.jobs.get(job_id)
        if job is None:
            return None, since, None
        with job.lock:
            start = max(since - job.dropped, 0)
            chunk = list(job.lines[start:])
            return chunk, job.dropped + len(job.lines), job.exit_code
```

- [ ] **Step 4: Run tests + lint**

Run: `python3 tests/test_ui_jobs.py` → `ALL PASS`
Run: `python3 tools/lint.py` → clean

- [ ] **Step 5: Commit**

```bash
git add src/ui/ui_jobs.py tests/test_ui_jobs.py
git commit -m "feat(ui): job manager — iro child processes with line buffer (ui_jobs)"
```

---

### Task 5: `src/ui/ui_server.py` — HTTP server core (JSON routes)

**Files:**
- Create: `src/ui/ui_server.py`
- Create: `tests/test_ui_server.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui_server.py`:

```python
#!/usr/bin/env python3
"""Stdlib checks for the Control Center HTTP server (real server on an
ephemeral port — no fixed ports, CI-safe). Run: python3 tests/test_ui_server.py"""
import json, os, sys, threading, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "ui"))
import ui_jobs
import ui_server as us


# ---------- pure helpers ----------

def t_ui_port_default_and_override():
    assert us.ui_port({}) == 8089
    assert us.ui_port({"IRO_UI_PORT": "9100"}) == 9100
    assert us.ui_port({"IRO_UI_PORT": ""}) == 8089
    assert us.ui_port({"IRO_UI_PORT": "not-a-port"}) == 8089


def t_classify_ping():
    ours = json.dumps({"app": us.APP_ID, "version": "x"}).encode()
    assert us.classify_ping(ours) == "ours"
    assert us.classify_ping(b'{"app": "something-else"}') == "foreign"
    assert us.classify_ping(b"<html>hi</html>") == "foreign"


def t_sse_frames():
    assert us.sse_frame("hello") == b"data: hello\n\n"
    assert us.sse_done(3) == b"event: done\ndata: 3\n\n"


# ---------- live server ----------

def _ctx(jobs=None):
    page = os.path.join(ROOT, "src", "ui", "control-center.html")
    return {"version": "test",
            "page_path": page,
            "status": lambda: {"relay": {"alive": False}},
            "ops": {"echo": ["echo-args"]},
            "jobs": jobs or ui_jobs.JobManager(
                lambda a: [sys.executable, "-c", "print('hi from job')"]),
            "log_paths": {}}


def _serve(ctx):
    httpd = us.serve(ctx, "127.0.0.1", 0)        # port 0 -> ephemeral
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def _get(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _post(port, path):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 method="POST", data=b"")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def t_ping_identifies_app():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/ping")
        assert code == 200
        data = json.loads(body)
        assert data["app"] == us.APP_ID and data["version"] == "test"
    finally:
        httpd.shutdown()


def t_status_route_wraps_provider():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/status")
        data = json.loads(body)
        assert code == 200 and data["ok"] is True and data["relay"] == {"alive": False}
    finally:
        httpd.shutdown()


def t_unknown_routes_are_json_404():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/nope")
        assert code == 404 and json.loads(body)["ok"] is False
        code, body = _post(port, "/api/op/not-an-op")
        assert code == 404 and "unknown operation" in json.loads(body)["error"]
    finally:
        httpd.shutdown()


def t_op_starts_job_and_snapshot_completes():
    httpd, port = _serve(_ctx())
    try:
        code, body = _post(port, "/api/op/echo")
        assert code == 200
        job_id = json.loads(body)["job_id"]
        deadline = time.time() + 10
        while time.time() < deadline:
            _c, body = _get(port, f"/api/jobs/{job_id}")
            snap = json.loads(body)
            if snap["exit_code"] is not None:
                break
            time.sleep(0.1)
        assert snap["exit_code"] == 0 and snap["op"] == "echo"
        code, _b = _get(port, "/api/jobs/unknown-id")
        assert code == 404
    finally:
        httpd.shutdown()


def t_quit_shuts_the_server_down():
    httpd, port = _serve(_ctx())
    code, body = _post(port, "/api/quit")
    assert code == 200 and json.loads(body)["ok"] is True
    deadline = time.time() + 5
    while time.time() < deadline:           # serve_forever() must return
        try:
            _get(port, "/api/ping")
            time.sleep(0.1)
        except (urllib.error.URLError, ConnectionError, OSError):
            break
    httpd.server_close()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run it — must fail**

Run: `python3 tests/test_ui_server.py`
Expected: `ModuleNotFoundError: No module named 'ui_server'`

- [ ] **Step 3: Create `src/ui/ui_server.py`**

```python
"""Control Center HTTP server: serves the static page, the JSON status API,
job control, and SSE streams (job output + service log tails) on localhost.
Same construction as the relay's control server (ThreadingHTTPServer +
make_handler closure). v1 binds 127.0.0.1 only; the bind/auth seams for the
v2 Tailscale+password feature are this module's serve() and _allowed().
Spec: docs/superpowers/specs/2026-06-07-control-center-design.md."""
import json, os, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

APP_ID = "iro-control-center"
DEFAULT_PORT = 8089
TAIL_LINES = 40          # how much history a log stream starts with


def ui_port(env):
    """Port from IRO_UI_PORT (.env/environment), falling back to 8089."""
    try:
        return int(env.get("IRO_UI_PORT") or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def classify_ping(body):
    """'ours' when an IRO Control Center answered the ping, else 'foreign'."""
    try:
        return "ours" if json.loads(body.decode()).get("app") == APP_ID else "foreign"
    except Exception:
        return "foreign"


def probe_instance(host, port, fetch=None):
    """Is something on host:port? 'free' (nothing), 'ours' (a running Control
    Center), 'foreign' (another app)."""
    fetch = fetch or _fetch_ping
    try:
        body = fetch(host, port)
    except Exception:
        return "free"
    return classify_ping(body)


def _fetch_ping(host, port):
    import urllib.request
    with urllib.request.urlopen(f"http://{host}:{port}/api/ping", timeout=2) as r:
        return r.read()


def sse_frame(line):
    return f"data: {line}\n\n".encode("utf-8")


def sse_done(exit_code):
    return f"event: done\ndata: {exit_code}\n\n".encode("utf-8")


def _allowed(_handler):
    """Auth seam: always allowed in v1 (localhost-only bind is the boundary).
    v2 (Tailscale + IRO_UI_PASSWORD session cookie) changes only this."""
    return True


def make_handler(ctx):
    """ctx: version, page_path, status() -> dict, ops {name: argv},
    jobs (ui_jobs.JobManager), log_paths {name: () -> path|None},
    shutdown() (installed by serve())."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass                                  # quiet — one consumer, localhost

        def _json(self, obj, code=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _not_found(self, what="not found"):
            self._json({"ok": False, "error": what}, code=404)

        def _sse_headers(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

        def do_GET(self):
            if not _allowed(self):
                return self._json({"ok": False, "error": "unauthorized"}, code=401)
            path = urlparse(self.path).path
            if path == "/":
                return self._page()
            if path == "/api/ping":
                return self._json({"app": APP_ID, "version": ctx["version"]})
            if path == "/api/status":
                return self._json({"ok": True, **ctx["status"]()})
            if path.startswith("/api/jobs/") and path.endswith("/stream"):
                return self._stream_job(path.split("/")[3])
            if path.startswith("/api/jobs/"):
                snap = ctx["jobs"].snapshot(path.split("/")[3])
                return self._json({"ok": True, **snap}) if snap else self._not_found("unknown job")
            if path.startswith("/api/logs/") and path.endswith("/stream"):
                return self._stream_log(path.split("/")[3])
            return self._not_found()

        def do_POST(self):
            if not _allowed(self):
                return self._json({"ok": False, "error": "unauthorized"}, code=401)
            path = urlparse(self.path).path
            if path.startswith("/api/op/"):
                name = path[len("/api/op/"):]
                if name not in ctx["ops"]:
                    return self._not_found(f"unknown operation: {name}")
                job_id, err = ctx["jobs"].start(name, ctx["ops"][name])
                if err:
                    return self._json({"ok": False, "error": err}, code=409)
                return self._json({"ok": True, "job_id": job_id})
            if path == "/api/quit":
                self._json({"ok": True})
                # shutdown() blocks until serve_forever() returns — never call
                # it from a request thread directly.
                threading.Thread(target=ctx["shutdown"], daemon=True).start()
                return None
            return self._not_found()

        def _page(self):
            try:
                with open(ctx["page_path"], "rb") as fh:
                    body = fh.read()
            except OSError:
                return self._not_found("page not bundled")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _stream_job(self, job_id):
            if ctx["jobs"].snapshot(job_id) is None:
                return self._not_found("unknown job")
            self._sse_headers()
            since = 0
            try:
                while True:
                    chunk, since, code = ctx["jobs"].lines_since(job_id, since)
                    for line in chunk:
                        self.wfile.write(sse_frame(line))
                    if chunk:
                        self.wfile.flush()
                    if code is not None and not chunk:
                        self.wfile.write(sse_done(code))
                        self.wfile.flush()
                        return
                    if not chunk:
                        time.sleep(0.4)
            except (BrokenPipeError, ConnectionResetError):
                return                            # browser tab closed mid-stream

        def _stream_log(self, name):
            path_fn = ctx["log_paths"].get(name)
            if path_fn is None:
                return self._not_found(f"unknown log: {name}")
            self._sse_headers()
            try:
                path, notified = path_fn(), False
                while not path or not os.path.exists(path):
                    # one visible notice, then SSE comment pings (detect a
                    # closed tab without spamming the client)
                    self.wfile.write(sse_frame("(no log yet — waiting)")
                                     if not notified else b": ping\n\n")
                    self.wfile.flush()
                    notified = True
                    time.sleep(2.0)
                    path = path_fn()
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for line in fh.readlines()[-TAIL_LINES:]:
                        self.wfile.write(sse_frame(line.rstrip("\r\n")))
                    self.wfile.flush()
                    while True:
                        line = fh.readline()
                        if line:
                            self.wfile.write(sse_frame(line.rstrip("\r\n")))
                            self.wfile.flush()
                        else:
                            time.sleep(0.5)
            except (BrokenPipeError, ConnectionResetError):
                return

    return Handler


def serve(ctx, host, port):
    """Build the server (caller runs serve_forever) and install ctx['shutdown'].
    Raises OSError when the port is taken — callers turn that into the
    IRO_UI_PORT hint."""
    httpd = ThreadingHTTPServer((host, port), make_handler(ctx))
    httpd.daemon_threads = True                  # SSE threads die with the process
    ctx["shutdown"] = httpd.shutdown
    return httpd
```

- [ ] **Step 4: Run tests + lint**

Run: `python3 tests/test_ui_server.py` → `ALL PASS` (the `/` page test comes in Task 7; nothing here requests `/`)
Run: `python3 tools/lint.py` → clean

- [ ] **Step 5: Commit**

```bash
git add src/ui/ui_server.py tests/test_ui_server.py
git commit -m "feat(ui): Control Center HTTP server — status API, job control, quit (ui_server)"
```

---

### Task 6: SSE end-to-end — job stream test

The SSE code shipped in Task 5; this task proves the stream actually delivers job output + the done event over a real socket.

**Files:**
- Test: `tests/test_ui_server.py` (extend)

- [ ] **Step 1: Write the failing test** (append above the `__main__` block)

```python
def t_job_stream_delivers_lines_then_done():
    httpd, port = _serve(_ctx())
    try:
        _c, body = _post(port, "/api/op/echo")
        job_id = json.loads(body)["job_id"]
        req = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/jobs/{job_id}/stream", timeout=10)
        assert req.headers["Content-Type"] == "text/event-stream"
        raw = b""
        deadline = time.time() + 10
        while b"event: done" not in raw and time.time() < deadline:
            raw += req.read(1)                  # tiny reads — no buffering surprises
        req.close()
        assert b"data: hi from job\n\n" in raw
        assert b"event: done\ndata: 0\n\n" in raw
    finally:
        httpd.shutdown()


def t_job_stream_unknown_id_is_404():
    httpd, port = _serve(_ctx())
    try:
        code, _b = _get(port, "/api/jobs/nope/stream")
        assert code == 404
    finally:
        httpd.shutdown()
```

- [ ] **Step 2: Run it**

Run: `python3 tests/test_ui_server.py`
Expected: `ALL PASS` if Task 5's implementation is correct — if a stream test fails, fix `_stream_job` (NOT the test) until it passes.

- [ ] **Step 3: Commit**

```bash
git add tests/test_ui_server.py
git commit -m "test(ui): SSE job stream end-to-end coverage"
```

---

### Task 7: `control-center.html` — the page

One static file, inline CSS/JS, no framework — the `src/director/director-panel.html` model. English text only. Mechanism only — no broadcast-procedure advice in labels or hints (house rule).

**Files:**
- Create: `src/ui/control-center.html`
- Test: `tests/test_ui_server.py` (extend)

- [ ] **Step 1: Write the failing test** (append above the `__main__` block)

```python
def t_root_serves_the_page():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/")
        assert code == 200
        assert b"IRO Control Center" in body
        assert b"/api/status" in body          # the page talks to our API
    finally:
        httpd.shutdown()
```

- [ ] **Step 2: Run it — must fail**

Run: `python3 tests/test_ui_server.py`
Expected: FAIL — `/` returns 404 `page not bundled` (file does not exist yet).

- [ ] **Step 3: Create `src/ui/control-center.html`**

```html
<!DOCTYPE html>
<!-- IRO Control Center — producer web UI served by `iro ui` (ui_server.py).
     Single static file, inline CSS/JS, no framework, no build step (same
     model as director-panel.html). All state lives server-side; this page
     only polls /api/status and renders SSE streams. -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IRO Control Center</title>
<style>
  :root { --bg:#14161a; --card:#1d2127; --line:#2c323b; --txt:#e8eaed;
          --dim:#9aa3ad; --ok:#2e9e5b; --bad:#5a6472; --accent:#3b82f6;
          --danger:#c94f4f; }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.45 system-ui, sans-serif; background:var(--bg);
         color:var(--txt); }
  header { display:flex; align-items:center; gap:12px; padding:14px 20px;
           border-bottom:1px solid var(--line); }
  header h1 { font-size:17px; margin:0; }
  header .ver { color:var(--dim); font-size:12px; }
  header .spacer { flex:1; }
  main { max-width:1100px; margin:0 auto; padding:20px; display:grid; gap:16px; }
  section { background:var(--card); border:1px solid var(--line);
            border-radius:10px; padding:16px; }
  h2 { font-size:13px; text-transform:uppercase; letter-spacing:.08em;
       color:var(--dim); margin:0 0 12px; }
  .row { display:flex; align-items:center; gap:10px; padding:8px 0;
         border-top:1px solid var(--line); flex-wrap:wrap; }
  .row:first-of-type { border-top:0; }
  .name { width:110px; font-weight:600; }
  .badge { padding:2px 10px; border-radius:99px; font-size:12px;
           background:var(--bad); }
  .badge.on { background:var(--ok); }
  .dim { color:var(--dim); font-size:12px; }
  .grow { flex:1; min-width:120px; }
  button { background:#262c35; color:var(--txt); border:1px solid var(--line);
           border-radius:7px; padding:6px 12px; cursor:pointer; font-size:13px; }
  button:hover { border-color:var(--accent); }
  button.danger:hover { border-color:var(--danger); }
  a { color:var(--accent); }
  pre { background:#0d0f12; border:1px solid var(--line); border-radius:8px;
        padding:10px; height:280px; overflow:auto; white-space:pre-wrap;
        margin:8px 0 0; font-size:12px; }
  select { background:#262c35; color:var(--txt); border:1px solid var(--line);
           border-radius:7px; padding:6px; }
</style>
</head>
<body>
<header>
  <h1>IRO Control Center</h1><span class="ver" id="ver"></span>
  <span class="spacer"></span>
  <a id="panel-link" href="#" target="_blank" hidden>Director panel</a>
  <button class="danger" onclick="quitUi()">Quit</button>
</header>
<main>
  <section>
    <h2>Dashboard</h2>
    <div class="row"><span class="name">Relay</span>
      <span class="badge" id="b-relay">…</span>
      <span class="dim grow" id="d-relay"></span>
      <button onclick="op('relay-start')">Start</button>
      <button class="danger" onclick="op('relay-stop', true)">Stop</button>
      <button onclick="op('relay-restart', true)">Restart</button></div>
    <div class="row"><span class="name">Companion</span>
      <span class="badge" id="b-companion">…</span>
      <span class="dim grow" id="d-companion"></span>
      <button onclick="op('companion-start')">Start</button>
      <button class="danger" onclick="op('companion-stop', true)">Stop</button>
      <button onclick="op('companion-restart', true)">Restart</button></div>
    <div class="row"><span class="name">Streams</span>
      <span class="badge" id="b-streams">…</span>
      <span class="dim grow" id="d-streams"></span>
      <button onclick="op('streams-start')">Start</button>
      <button class="danger" onclick="op('streams-stop', true)">Stop</button></div>
    <div class="row"><span class="name">Tailscale</span>
      <span class="badge" id="b-ts">…</span>
      <span class="dim grow" id="d-ts"></span></div>
    <div class="row"><span class="name">OBS pages</span>
      <span class="dim grow">Reload the relay-served HUD/timer browser sources</span>
      <button onclick="op('obs-refresh')">Refresh</button></div>
  </section>
  <section id="job" hidden>
    <h2>Job: <span id="jobtitle"></span></h2>
    <pre id="joblog"></pre>
  </section>
  <section>
    <h2>Service logs</h2>
    <select id="logsel" onchange="watchLog(this.value)">
      <option value="">— select a log —</option>
      <option value="relay">relay</option>
      <option value="companion">companion</option>
      <option value="streams">streams</option>
    </select>
    <pre id="svclog"></pre>
  </section>
</main>
<script>
const $ = id => document.getElementById(id);
let jobES = null, logES = null;

function setBadge(key, on, onText, offText, detail) {
  const b = $('b-' + key);
  b.textContent = on ? onText : offText;
  b.classList.toggle('on', on);
  $('d-' + key).textContent = detail || '';
}

async function refresh() {
  let s;
  try {
    s = await (await fetch('/api/status', {cache: 'no-store'})).json();
  } catch (e) { return; }            // server gone (quit) — keep the last state
  $('ver').textContent = s.version;
  const relayUp = s.relay.alive;
  setBadge('relay', relayUp, 'RUNNING', 'stopped',
    relayUp ? (s.relay.http_ok ? 'control OK on port ' + s.relay.port
                               : 'port ' + s.relay.port + ' not responding') : '');
  $('panel-link').hidden = !(relayUp && s.relay.http_ok);
  $('panel-link').href = 'http://127.0.0.1:' + s.relay.port + '/panel';
  setBadge('companion', s.companion.running, 'RUNNING', 'stopped',
           s.companion.url || s.companion.why);
  const up = s.streams.filter(f => f.alive).length;
  setBadge('streams', up > 0, 'RUNNING', 'stopped',
           s.streams.length ? up + '/' + s.streams.length + ' feeds up'
                            : 'no feeds started');
  setBadge('ts', !!s.tailscale_ip, 'connected', 'down',
           s.tailscale_ip || 'not connected');
}

async function op(name, confirmFirst) {
  if (confirmFirst && !confirm('Run ' + name + '?')) return;
  let r;
  try {
    r = await (await fetch('/api/op/' + name, {method: 'POST'})).json();
  } catch (e) { alert('Control Center not reachable.'); return; }
  if (!r.ok) { alert(r.error); return; }
  watchJob(name, r.job_id);
}

function watchJob(name, id) {
  if (jobES) jobES.close();
  $('job').hidden = false;
  $('jobtitle').textContent = name;
  $('joblog').textContent = '';
  jobES = new EventSource('/api/jobs/' + id + '/stream');
  jobES.onmessage = e => {
    $('joblog').textContent += e.data + '\n';
    $('joblog').scrollTop = 1e9;
  };
  jobES.addEventListener('done', e => {
    $('joblog').textContent += '— finished (exit ' + e.data + ') —\n';
    $('jobtitle').textContent = name + ' (done)';
    jobES.close();
    refresh();
  });
}

function watchLog(name) {
  if (logES) { logES.close(); logES = null; }
  $('svclog').textContent = '';
  if (!name) return;
  logES = new EventSource('/api/logs/' + name + '/stream');
  logES.onmessage = e => {
    $('svclog').textContent += e.data + '\n';
    $('svclog').scrollTop = 1e9;
  };
}

async function quitUi() {
  if (!confirm('Quit the Control Center? Relay/Companion/streams keep running.')) return;
  try { await fetch('/api/quit', {method: 'POST'}); } catch (e) {}
  document.body.innerHTML =
    '<p style="padding:30px;font:14px system-ui">Control Center stopped — you can close this tab.</p>';
}

refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
```

- [ ] **Step 4: Run tests**

Run: `python3 tests/test_ui_server.py` → `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add src/ui/control-center.html tests/test_ui_server.py
git commit -m "feat(ui): Control Center page — dashboard, job log, service log tails"
```

---

### Task 8: `iro ui` subcommand, `.env.example`, docs, full verification

**Files:**
- Modify: `src/iro.py` (USAGE docstring ~line 7-19, `route()` ~332, `main()` ~1231, new `ui_cmd`)
- Modify: `.env.example`
- Modify: `CLAUDE.md` (commands section)
- Test: `tests/test_iro.py` (extend — follow its existing `t_*` style and import header exactly), `tests/test_ui_server.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_iro.py` (it already imports the `iro` module — match the surrounding test style):

```python
def t_route_ui():
    assert iro.route(["ui"]) == {"kind": "ui", "rest": []}
    assert iro.route(["ui", "--no-browser"]) == {"kind": "ui", "rest": ["--no-browser"]}
```

Append to `tests/test_ui_server.py` (probe_instance is pure with an injected fetch):

```python
def t_probe_instance_classifies():
    ours = json.dumps({"app": us.APP_ID}).encode()
    assert us.probe_instance("h", 1, fetch=lambda h, p: ours) == "ours"
    assert us.probe_instance("h", 1, fetch=lambda h, p: b"nope") == "foreign"
    def boom(h, p):
        raise OSError("connection refused")
    assert us.probe_instance("h", 1, fetch=boom) == "free"
```

- [ ] **Step 2: Run them — must fail**

Run: `python3 tests/test_iro.py` → FAIL (`unknown command: ui` ValueError)
Run: `python3 tests/test_ui_server.py` → PASS already (probe_instance shipped in Task 5) — if it fails, fix `probe_instance`.

- [ ] **Step 3: Implement in `src/iro.py`**

In `route()`, insert directly above the `if cmd == "init":` line:

```python
    if cmd == "ui":
        return {"kind": "ui", "rest": rest}
```

In `main()`, insert directly above the `if action["kind"] == "init":` line:

```python
    if action["kind"] == "ui":
        return ui_cmd(action["rest"])
```

Add `ui_cmd` + helpers above `main()` (below `init_cmd`):

```python
def _ui_modules():
    """src/ui modules — path-inserted like scripts/ (kept out of the module-level
    insert: only `iro ui` needs them)."""
    ui_dir = os.path.join(HERE, "ui") if not IS_FROZEN else os.path.join(
        _src_base(True, getattr(sys, "_MEIPASS", ""), HERE), "ui")
    if ui_dir not in sys.path:
        sys.path.insert(0, ui_dir)
    import ui_jobs, ui_ops, ui_server
    return ui_server, ui_jobs, ui_ops


def ui_cmd(rest):
    """Run the Control Center web server in the foreground (Ctrl+C stops it).
    Spec: docs/superpowers/specs/2026-06-07-control-center-design.md."""
    srv, jobs_mod, ops_mod = _ui_modules()
    for key, val in _read_env_file().items():
        os.environ.setdefault(key, val)        # IRO_UI_PORT from .env (env wins)
    port = srv.ui_port(os.environ)
    instance = srv.probe_instance("127.0.0.1", port)
    if instance == "ours":
        print(f"Control Center already running on port {port} — opening the browser.")
        _open_url(_http_url("127.0.0.1", port, "/"))
        return None
    if instance == "foreign":
        sys.exit(f"iro: port {port} is in use by another application — set "
                 "IRO_UI_PORT in .env to a free port and retry.")
    ctx = {
        "version": version(),
        "page_path": resource_path("ui/control-center.html"),
        "status": ui_status_payload,
        "ops": ops_mod.OPS,
        "jobs": jobs_mod.JobManager(
            lambda op_args: ops_mod.job_argv(op_args, IS_FROZEN, sys.executable,
                                             os.path.join(HERE, "iro.py")),
            env=_frozen_child_env()),
        "log_paths": {"relay": _relay_log_path,
                      "companion": _companion_log_path,
                      "streams": _latest_stream_log},
    }
    try:
        httpd = srv.serve(ctx, "127.0.0.1", port)
    except OSError as exc:
        sys.exit(f"iro: could not bind port {port} ({exc}) — set IRO_UI_PORT "
                 "in .env to a free port and retry.")
    url = _http_url("127.0.0.1", port, "/")
    print(f"Control Center: {url}  (Ctrl+C or the Quit button stops it)")
    if "--no-browser" not in rest:
        _open_url(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    print("Control Center stopped — relay/companion/streams keep running.")
    return None
```

Update the USAGE docstring: insert this line below the `iro status` line:

```
  iro ui [--no-browser]                 # local Control Center web app (port 8089 / IRO_UI_PORT)
```

- [ ] **Step 4: `.env.example`**

Append:

```
# OPTIONAL: port of the local Control Center web app (`iro ui`). Set this only
# when another application on this machine already occupies the default 8089.
IRO_UI_PORT=

# RESERVED for the future remote-support feature (Control Center over
# Tailscale): not read by any current version — leave commented out.
# IRO_UI_PASSWORD=
```

- [ ] **Step 5: CLAUDE.md**

In the Commands block, below the `python3 src/iro.py status` line, add:

```
python3 src/iro.py ui                # local Control Center web app (dashboard, service control, logs); port 8089 / IRO_UI_PORT
```

In the tests list, after the `test_setup.py` line, add:

```bash
python3 tests/test_ui_ops.py         # Control Center structured status providers + op registry
python3 tests/test_ui_jobs.py        # Control Center job manager (child spawn, line buffer)
python3 tests/test_ui_server.py      # Control Center HTTP server (routes, SSE, quit)
```

- [ ] **Step 6: Manual smoke (repo mode)**

```bash
python3 src/iro.py ui --no-browser &
sleep 1
curl -s http://127.0.0.1:8089/api/ping       # -> {"app": "iro-control-center", ...}
curl -s http://127.0.0.1:8089/api/status | python3 -m json.tool | head -15
curl -s -X POST http://127.0.0.1:8089/api/quit
wait
```

Expected: ping shows the app id; status shows relay/companion/streams/tailscale; quit ends the foreground process ("Control Center stopped …").
Then once WITH browser: `python3 src/iro.py ui` — eyeball the dashboard, press a Start/Stop button, watch the job log stream, select a service log, press Quit.

- [ ] **Step 7: Full verification**

Run: `python3 tools/run-tests.py` → `ALL TEST FILES PASS`
Run: `python3 tools/lint.py` → clean
Run: `python3 tools/build.py` → builds + self-verifies (the new `src/ui/` files must land in `dist/IRO_Broadcast_Package/`; the verify step confirms no shell scripts / no secrets).

- [ ] **Step 8: Commit**

```bash
git add src/iro.py .env.example CLAUDE.md tests/test_iro.py tests/test_ui_server.py
git commit -m "feat(iro): ui subcommand — local Control Center server (IRO_UI_PORT, single-instance probe)"
```

---

## Out of scope for Phase 1 (do NOT build these now)

- Job cancellation endpoint (`/api/jobs/<id>/cancel`) — Phase 2.
- One-shot ops (installs, graphics, media, cookies, setup, preflight, export companion, event start/stop) — Phase 2 extends `ui_ops.OPS` only.
- Init wizard (`/api/init/*`), the `iro-ui` double-click binary, per-OS packaging, release/CI integration — Phase 3.
- Tailnet bind + `IRO_UI_PASSWORD` auth — v2 (the `_allowed()` / `serve()` seams exist).
