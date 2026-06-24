# Control Center `app.log` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist Control Center action/console output to a timestamped, rotating `runtime/logs/app.log` that shows up as a normal log source in the Control Center's own log viewer.

**Architecture:** Reuse the existing `src/scripts/logsetup.py` (`configure_logging`) to create a `racecast.app` logger writing machine-wide to `runtime/logs/app.log`. The Control Center's `JobManager` (which already iterates each child action's output lines) emits a start marker (op + argv), one line per output line (prefixed `[op]`), and an end marker (exit code) to that logger. A new `"app"` entry in the `_log_sources()` registry plus one `<option>` in the logs `<select>` surface the file (and its dated archives) in the UI. The in-memory buffer and SSE/browser flow are untouched.

**Tech Stack:** Python 3 stdlib only (no new deps). `logging.handlers.TimedRotatingFileHandler` via `logsetup`. Tests are stdlib runnable scripts (no pytest).

## Global Constraints

- **Edit only under `src/`** (plus `tests/` and `docs/`). Never hand-edit `dist/`/`runtime/`. (CLAUDE.md)
- **English only** in all code, comments, docs, and log strings. (CLAUDE.md)
- **No new runtime dependency** — stdlib + the existing `logsetup` module only.
- **Reuse `logsetup`** for rotation/format/retention — do NOT write a second file handler. Format is fixed: `%(asctime)s %(levelname)s %(message)s`, datefmt `%Y-%m-%d %H:%M:%S`, midnight rotation, archive suffix `.YYYY-MM-DD`, `backupCount=0`, retention via `prune_old_logs` (default 7 days, `RACECAST_LOG_RETENTION_DAYS`).
- **Location is machine-wide:** `runtime/logs/app.log` (`os.path.join(_runtime_base_dir(), "logs")`), NOT per-profile.
- **`logger` is optional and defaults to `None`** in `JobManager` — when `None`, no logging happens and behavior is byte-for-byte unchanged (regression guard for every existing caller/test).
- **Tests must run on any machine and in CI** — no real IPs/paths; point loggers at a TempDir and call `logsetup.close_logging(name)` before the dir is removed (Windows holds open handles).
- **Run after Python changes:** `python3 tools/lint.py` (CI lint). **Before shipping:** `python3 tools/run-tests.py` (full suite) and `python3 tools/build.py` (verify step).
- **UI surface changed → refresh its wiki screenshot in the SAME change:** the logs view gains an `app` source → `src/docs/wiki/images/cc-logs.png` MUST be regenerated (Task 4).

---

### Task 1: `JobManager` logs lifecycle + each output line

**Files:**
- Modify: `src/ui/ui_jobs.py` (`JobManager.__init__`, `JobManager.start`, `JobManager._reader`)
- Test: `tests/test_ui_jobs.py`

**Interfaces:**
- Consumes: nothing new (uses the existing `op`, `op_args`, `argv` already in `start`).
- Produces: `JobManager(argv_for, env=None, spawn=None, max_lines=5000, logger=None)`. When `logger` is set, it receives, in order:
  - `logger.info("[%s] action started — argv: %s", op, " ".join(argv))`
  - `logger.info("[%s] %s", op, line)` per output line
  - `logger.info("[%s] action finished — exit %s", op, code)` when `code == 0`, else `logger.warning(...)` with the same message.
  - On reader-thread exhaustion: `logger.warning("[%s] action finished — exit -1 (%s)", op, exc)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui_jobs.py` (after the imports / `FakeProc`):

```python
class FakeLogger:
    """Captures (level, formatted-message) tuples — no disk IO."""
    def __init__(self):
        self.calls = []
    def _rec(self, level, msg, args):
        self.calls.append((level, msg % args if args else msg))
    def info(self, msg, *args):
        self._rec("INFO", msg, args)
    def warning(self, msg, *args):
        self._rec("WARNING", msg, args)


def t_logs_start_lines_and_exit():
    log = FakeLogger()
    jm = ui_jobs.JobManager(lambda a: ["racecast", "relay", "start"],
                            spawn=lambda argv: FakeProc(), logger=log)
    job_id, err = jm.start("relay-start", ["relay", "start"])
    assert err is None
    _wait_done(jm, job_id)
    msgs = [m for _lvl, m in log.calls]
    assert any(x.startswith("[relay-start] action started")
               and "racecast relay start" in x for x in msgs)
    assert "[relay-start] line1" in msgs
    assert "[relay-start] line2" in msgs
    assert ("INFO", "[relay-start] action finished — exit 0") in log.calls


def t_logs_nonzero_exit_is_warning():
    log = FakeLogger()
    jm = ui_jobs.JobManager(lambda a: ["x"],
                            spawn=lambda argv: FakeProc(code=3), logger=log)
    job_id, _ = jm.start("op", [])
    _wait_done(jm, job_id)
    assert ("WARNING", "[op] action finished — exit 3") in log.calls


def t_no_logger_is_silent():
    # Default logger=None must behave exactly as before — no crash, full output.
    jm = ui_jobs.JobManager(lambda a: ["x"], spawn=lambda argv: FakeProc())
    job_id, err = jm.start("op", [])
    assert err is None
    snap = _wait_done(jm, job_id)
    assert snap["exit_code"] == 0
    lines, _nxt, _code = jm.lines_since(job_id, 0)
    assert lines == ["line1", "line2"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_ui_jobs.py`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'logger'` (the `logger` kwarg doesn't exist yet).

- [ ] **Step 3: Add the `logger` parameter and the log calls**

In `src/ui/ui_jobs.py`, change `__init__` (currently line 29):

```python
    def __init__(self, argv_for, env=None, spawn=None, max_lines=5000, logger=None):
        """argv_for(op_args) -> child argv (see ui_ops.job_argv). env: full
        child environment or None (inherit). spawn: Popen-compatible test seam.
        logger: optional logging.Logger — when set, the action's start marker,
        each output line (prefixed `[op]`), and its exit code are logged (file
        persistence; the in-memory buffer + SSE are unchanged). None -> silent."""
        self.argv_for, self.env = argv_for, env
        self.spawn = spawn or self._spawn
        self.max_lines = max_lines
        self.logger = logger
        self.jobs = {}           # job_id -> Job (kept for the session — the op set is finite)
        self.lock = threading.Lock()
```

Replace `start` (currently lines 44-61) so it captures `argv` and logs the start marker on the success path:

```python
    def start(self, op, op_args):
        """Start `op` unless one is still running. Returns (job_id, None) or
        (None, error-text)."""
        with self.lock:
            for job in self.jobs.values():
                if job.op == op and job.exit_code is None:  # exit_code writes are atomic
                    return None, f"{op} is already running"
            argv = self.argv_for(op_args)
            proc = self.spawn(argv)
            job = Job(uuid.uuid4().hex[:12], op, proc)
            self.jobs[job.id] = job
        if self.logger:
            self.logger.info("[%s] action started — argv: %s", op, " ".join(argv))
        reader = threading.Thread(target=self._reader, args=(job,), daemon=True)
        try:
            reader.start()
        except RuntimeError as exc:      # OS thread exhaustion — unblock the op
            with job.lock:
                job.exit_code = -1
                job.lines.append(f"(could not start output reader: {exc})")
            if self.logger:
                self.logger.warning("[%s] action finished — exit -1 (%s)", op, exc)
        return job.id, None
```

Replace `_reader` (currently lines 63-75) to log each line and the exit marker (logging happens OUTSIDE `job.lock` so the file write never extends the critical section):

```python
    def _reader(self, job):
        for raw in job.proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if self.logger:
                self.logger.info("[%s] %s", job.op, line)
            with job.lock:
                job.lines.append(line)
                overflow = len(job.lines) - self.max_lines
                if overflow > 0:
                    del job.lines[:overflow]
                    job.dropped += overflow
        job.proc.stdout.close()          # release the pipe fd promptly
        code = job.proc.wait()
        with job.lock:
            job.exit_code = code
        if self.logger:
            log = self.logger.info if code == 0 else self.logger.warning
            log("[%s] action finished — exit %s", job.op, code)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_ui_jobs.py`
Expected: `ALL PASS` (every existing `t_*` plus the three new ones).

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: no findings for `src/ui/ui_jobs.py`.

- [ ] **Step 6: Commit**

```bash
git add src/ui/ui_jobs.py tests/test_ui_jobs.py
git commit -m "feat(ui): JobManager logs action start/lines/exit to an optional logger"
```

---

### Task 2: Create the `racecast.app` logger in `run_ui()` and wire it into `JobManager`

**Files:**
- Modify: `src/racecast.py` — add `_ui_app_log_dir()` / `_ui_app_log_path()` helpers (near the other runtime-path helpers, e.g. just after `_runtime_dir()` at line 188); create the logger in `run_ui()` (just before the `ctx = {` dict at line 5233); pass `logger=_app_logger` to the `JobManager` at line 5299.
- Test: `tests/test_racecast.py`

**Interfaces:**
- Consumes: `JobManager(..., logger=...)` from Task 1; `logsetup.configure_logging`, `logsetup.prune_old_logs`; `_runtime_base_dir()`.
- Produces: `_ui_app_log_path() -> <runtime base>/logs/app.log` and `_ui_app_log_dir() -> <runtime base>/logs` (consumed by Task 3).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_racecast.py` (near the other path-helper tests):

```python
def t_ui_app_log_path_is_machine_wide():
    # app.log lives at the un-scoped runtime base, NOT under a profile.
    assert m._ui_app_log_dir() == os.path.join(m._runtime_base_dir(), "logs")
    assert m._ui_app_log_path() == os.path.join(m._runtime_base_dir(), "logs", "app.log")


def t_run_ui_wires_app_logger():
    import inspect
    src = inspect.getsource(m.run_ui)
    assert 'configure_logging("racecast.app"' in src   # dedicated logger created
    assert "_ui_app_log_path()" in src
    assert "prune_old_logs" in src                      # retention applied at startup
    assert "logger=_app_logger" in src                  # passed into the JobManager
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `AttributeError: module 'racecast' has no attribute '_ui_app_log_dir'`.

- [ ] **Step 3: Add the path helpers**

In `src/racecast.py`, immediately after `_runtime_dir()` (line 188-189):

```python
def _ui_app_log_dir():
    """Control Center app.log lives machine-wide at runtime/logs (NOT per-profile):
    the UI's actions span profiles (install-tools, preflight, cookies, freeport…),
    and the active profile can change mid-session."""
    return os.path.join(_runtime_base_dir(), "logs")

def _ui_app_log_path():
    return os.path.join(_ui_app_log_dir(), "app.log")
```

- [ ] **Step 4: Create the logger in `run_ui()` and pass it to the JobManager**

In `src/racecast.py`, in `run_ui()`, insert just before `ctx = {` (line 5233):

```python
    # Control Center action output -> a timestamped, rotating machine-wide app.log
    # (same logsetup machinery as the relay). to_stdout=False: file only, never
    # double-write to the UI's own console. Prune on start, like the daemons.
    import logsetup
    _app_logger = logsetup.configure_logging("racecast.app", _ui_app_log_path(),
                                             to_stdout=False)
    logsetup.prune_old_logs(_ui_app_log_dir())
```

Then change the `JobManager` instantiation (lines 5299-5303) to pass the logger:

```python
        "jobs": jobs_mod.JobManager(
            lambda op_args: ops_mod.job_argv(op_args, IS_FROZEN,
                                             _rc_job_executable(),
                                             os.path.join(HERE, "racecast.py")),
            env=_frozen_child_env(), logger=_app_logger),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 tests/test_racecast.py`
Expected: `ALL PASS` (including the two new tests).

- [ ] **Step 6: Lint**

Run: `python3 tools/lint.py`
Expected: no findings for `src/racecast.py`.

- [ ] **Step 7: Commit**

```bash
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(ui): persist Control Center action output to runtime/logs/app.log"
```

---

### Task 3: Surface `app.log` as a log source in the registry and the UI

**Files:**
- Modify: `src/racecast.py` — add module-level `_app_files()` (near `_relay_files()` at line 653); add the `"app"` source to `_log_sources()` (lines 703-740).
- Modify: `src/ui/control-center.html` — add one `<option>` to the logs `<select>` (line 967).
- Test: `tests/test_racecast.py` (extend `t_log_sources_registry_shape` at line 2365).

**Interfaces:**
- Consumes: `_ui_app_log_path()` / `_ui_app_log_dir()` from Task 2; the existing `rc_src(files_fn, dirpath)` closure inside `_log_sources()`.
- Produces: `_log_sources()["app"]` — a racecast-style source (`{files, dir, archives, read}`) over `runtime/logs/app.log`, with dated-archive reads (`.YYYY-MM-DD`). The `"app"` source is standalone (intentionally NOT folded into the `aggregate` union — keeps the spec minimal; `aggregate` stays the five service sources).

- [ ] **Step 1: Write the failing test**

In `tests/test_racecast.py`, extend `t_log_sources_registry_shape` (line 2365) — change the required-set assertion and add an `app`-resolves assertion:

```python
def t_log_sources_registry_shape():
    src = m._log_sources()
    assert set(["relay", "streams", "obs", "companion", "tailscale",
                "aggregate", "app"]) <= set(src)
    for _name, spec in src.items():
        assert callable(spec["files"])          # () -> list[path]
        assert callable(spec["archives"])       # () -> list[token]
        assert callable(spec["read"])           # (token) -> text
    # the app source points at the machine-wide runtime/logs dir
    assert src["app"]["dir"] == m._ui_app_log_dir()
    # aggregate's file set is the union of the FIVE service sources (app is standalone)
    agg = set(src["aggregate"]["files"]())
    parts = set()
    for n in ("relay", "streams", "obs", "companion", "tailscale"):
        parts |= set(src[n]["files"]())
    assert agg == parts
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `KeyError: 'app'` (no `app` source in the registry yet).

- [ ] **Step 3: Add the `_app_files()` helper**

In `src/racecast.py`, immediately after `_relay_files()` (lines 653-655):

```python
def _app_files():
    p = _ui_app_log_path()
    return [p] if os.path.exists(p) else []
```

- [ ] **Step 4: Register the `app` source**

In `src/racecast.py`, in `_log_sources()`: add `app_dir` next to `relay_dir`/`streams_dir` (line 709-710):

```python
    relay_dir = os.path.join(_running_relay_dir(), "logs")   # follows the relay (#273)
    streams_dir = os.path.join(_streams_static_dir(), "logs")
    app_dir = _ui_app_log_dir()                              # machine-wide Control Center log
```

Then add the source to the `reg` dict (after the `companion` entry, line 729-730):

```python
        "companion": ext_src(_companion_files,
                             os.path.dirname(_companion_log_path() or "") or "."),
        "app": rc_src(_app_files, app_dir),
```

(Leave `_agg_files` and the `aggregate` entry unchanged — `app` is standalone.)

- [ ] **Step 5: Add the UI dropdown option**

In `src/ui/control-center.html`, in the `#logsel` `<select>` (lines 961-967), add the `app` option after `tailscale`:

```html
            <option value="tailscale">tailscale</option>
            <option value="app">app</option>
          </select>
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `python3 tests/test_racecast.py`
Expected: `ALL PASS`.

- [ ] **Step 7: Lint + ui_server route test (the registry feeds the SSE routes)**

Run: `python3 tools/lint.py && python3 tests/test_ui_server.py`
Expected: no lint findings; `tests/test_ui_server.py` prints `ALL PASS` (the new source flows through the existing generic `/api/logs/<name>/...` routes — no route change needed).

- [ ] **Step 8: Commit**

```bash
git add src/racecast.py src/ui/control-center.html tests/test_racecast.py
git commit -m "feat(ui): expose Control Center app.log as a selectable log source"
```

---

### Task 4: Refresh the `cc-logs.png` wiki screenshot

**Files:**
- Modify: `src/docs/wiki/images/cc-logs.png` (regenerated, not hand-edited)

**Why:** The logs view's source `<select>` gained an `app` option — a visible Control Center change. CLAUDE.md hard rule: a changed UI surface refreshes its wiki screenshot in the SAME change. Surface → image: Control Center logs view → `cc-logs.png`.

- [ ] **Step 1: Invoke the `wiki-screenshots` skill**

Use the **`wiki-screenshots`** skill (repo-anchored under `.claude/skills/`). Follow it exactly: start a local dev build (`racecast ui` from `src/`, no `VERSION` stamped, so the badge reads "dev build" like every other `cc-*.png`), populate believable content via the `demo` profile + `tools/obs-sim.py` per the skill's recipe, open the **Logs** view, select a source so the new `app` option is visible in the dropdown, and take the **element** screenshot framed to match the existing `cc-logs.png` (same card/region as the current image).

- [ ] **Step 2: Verify the image**

Confirm `src/docs/wiki/images/cc-logs.png` shows the logs view with the `app` entry present in the source dropdown, the "dev build" version badge, and framing consistent with the previous screenshot. (If the `demo` relay was run, revert any committed mutation to `profiles/demo/profile.env` per the demo-relay note before committing.)

- [ ] **Step 3: Commit**

```bash
git add src/docs/wiki/images/cc-logs.png
git commit -m "docs(wiki): refresh cc-logs.png for the app log source"
```

---

### Task 5: Full-suite + build verification gate

**Files:** none (verification only).

- [ ] **Step 1: Run the whole test suite (exactly what CI runs)**

Run: `python3 tools/run-tests.py`
Expected: all test scripts pass (the runner reports success for every `tests/test_*.py`).

- [ ] **Step 2: Lint the whole tree**

Run: `python3 tools/lint.py`
Expected: no findings.

- [ ] **Step 3: Build verify (closest thing to CI's ship check)**

Run: `python3 tools/build.py`
Expected: build completes and the verify step passes (tokenization, blanked password, no secrets, preflight present, no shell scripts).

- [ ] **Step 4: Manual smoke (optional but recommended)**

Run `python3 src/racecast.py ui`, trigger one action (e.g. `preflight`) from the Control Center, then confirm `runtime/logs/app.log` exists and contains timestamped `[preflight] …` lines (start marker, output, exit marker). Select `app` in the Logs view and confirm the lines render.

- [ ] **Step 5: Commit (only if Step 4 produced a tracked change — normally nothing to commit)**

No commit expected; `runtime/` is gitignored.

---

## Self-Review

**Spec coverage:**
- Machine-wide `runtime/logs/app.log` via `logsetup` → Task 2. ✓
- Lifecycle markers (start + argv, exit code) + each line `[op]`-prefixed → Task 1. ✓
- Daily rotation / 7-day prune reused from `logsetup`; prune at startup → Task 2. ✓
- `delay=True` (no empty file when idle) → inherited from `configure_logging` (Task 2). ✓
- `to_stdout=False` (file only) → Task 2. ✓
- New `"app"` log source in the registry + selectable in the viewer + dated archives → Task 3. ✓
- In-memory buffer + SSE/browser flow unchanged → Task 1 only adds logging around the existing buffer writes; `logger=None` default keeps every other caller identical. ✓
- Security: only child stdout/stderr is logged (same as the console view) → no code needed; noted. ✓
- Tests: `test_ui_jobs.py` (logger behavior + None no-op), `test_racecast.py` (path helper + registry), `test_ui_server.py` (routes still pass) → Tasks 1-3. ✓
- UI-surface screenshot refresh (`cc-logs.png`) → Task 4 (CLAUDE.md hard rule). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command has an expected result.

**Type consistency:** `JobManager(..., logger=None)` defined in Task 1 and consumed in Task 2; `_ui_app_log_path()`/`_ui_app_log_dir()` defined in Task 2 and consumed by `_app_files()` in Task 3; the `[op] action started/finished` message strings match exactly between the Task 1 implementation and the Task 1 test assertions (em-dash `—` used consistently).
