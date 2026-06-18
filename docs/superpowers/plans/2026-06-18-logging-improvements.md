# Logging Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the relay + static streams timestamped, leveled, daily-rotated logs with 7-day cleanup; surface OBS / Companion / Tailscale logs and archive history in the CLI and Control Center; and add an aggregated "All (live)" view as the Control Center default.

**Architecture:** A new stdlib-only helper `src/scripts/logsetup.py` holds the reusable, mostly-pure pieces (rotating-logger setup, prune, subprocess classification/pump, external-log discovery, archive resolution with a traversal guard). Each long-lived daemon (relay, each `loopstream`) configures its own `TimedRotatingFileHandler` and pumps its streamlink child's output through that logger. A logical log "source" maps to a *set* of files; one merge-tail mechanism serves single-file and multi-file sources alike (`relay`, `streams`, `aggregate`).

**Tech Stack:** Python 3 stdlib only (`logging`, `logging.handlers.TimedRotatingFileHandler`, `threading`, `queue`, `http.server` SSE). No third-party deps. Tests are stdlib runnable scripts (`tests/test_*.py`, `t_*` functions), matching the existing harness.

**Spec:** `docs/superpowers/specs/2026-06-18-logging-improvements-design.md`

---

## Conventions for this plan

- **Test harness:** each `tests/test_*.py` defines `t_*()` functions (optionally taking a `tmp` dir) and a bottom runner (copy from `tests/test_services.py:180-186`). Run a whole file with `python3 tests/test_logs.py`; the suite with `python3 tools/run-tests.py`; lint with `python3 tools/lint.py` after any Python change.
- **Commit cadence:** commit after each task's tests pass. Commit messages use Conventional Commits and end with the repo's `Co-Authored-By` trailer.
- **Edit only under `src/`** (+ `tests/`, `docs/`); never `dist/`/`runtime/`.

## File structure

- **Create** `src/scripts/logsetup.py` — rotating-logger setup, `prune_old_logs`, `classify_subproc_line`, `tag_line`, `pump_subprocess`, `obs_log_dir`, `list_logs`, `newest_log`, `resolve_archive`, `archive_dates`. stdlib-only; **must not import `config.py`** (keeps the relay dependency-light).
- **Create** `tests/test_logs.py` — unit tests for every pure helper above.
- **Modify** `src/scripts/services.py` — `start_detached` boot-file separation; no behavior change to existing callers that pass a real log path.
- **Modify** `src/relay/racecast-feeds.py` — console logger + event lines; per-feed loggers + streamlink pump.
- **Modify** `src/scripts/loopstream.py` + `src/scripts/start-streams.py` — per-feed logger + pump; boot-file redirect.
- **Modify** `src/scripts/tailscale.py` — `status_snapshot_text()` helper (pure formatting).
- **Modify** `src/racecast.py` — source registry, OBS/Tailscale resolvers, prune-on-start, snapshot append, CLI `--list`/`--archive`, `obs logs`, `tailscale logs`, `ctx` wiring.
- **Modify** `src/ui/ui_server.py` — `/api/logs/<name>/archives`, `/api/logs/<name>/file`, merge-tail refactor of `_stream_log`, `/api/logs/aggregate/stream`.
- **Modify** `src/ui/control-center.html` — source dropdown (aggregate default + obs/tailscale), archive date selector, static-read JS.
- **Modify** `tools/run-tests.py` (register `test_logs.py` if it uses an explicit list), `CLAUDE.md`, `README.md`, `src/docs/wiki/images/cc-logs.png`.

---

## Task 1: `logsetup.configure_logging` — rotating timestamped logger

**Files:**
- Create: `src/scripts/logsetup.py`
- Test: `tests/test_logs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_logs.py`:

```python
#!/usr/bin/env python3
"""Stdlib checks for the logging helper. Run: python3 tests/test_logs.py"""
import logging, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import logsetup as lg


def t_configure_logging_writes_timestamped_line(tmp):
    path = os.path.join(tmp, "logs", "relay.console.log")
    log = lg.configure_logging("test.relay.a", path, to_stdout=False)
    log.info("hello world")
    for h in log.handlers:
        h.flush()
    with open(path, encoding="utf-8") as fh:
        line = fh.read().strip()
    # "2026-06-18 12:00:00 INFO hello world"
    assert line.endswith("INFO hello world"), line
    assert line[:4].isdigit() and line[4] == "-", line   # leading ISO date


def t_configure_logging_no_stdout_handler_when_not_tty(tmp):
    path = os.path.join(tmp, "logs", "b.log")
    log = lg.configure_logging("test.relay.b", path, to_stdout=False)
    assert all(not isinstance(h, logging.StreamHandler)
               or isinstance(h, logging.FileHandler)
               for h in log.handlers)


def t_configure_logging_idempotent(tmp):
    path = os.path.join(tmp, "logs", "c.log")
    a = lg.configure_logging("test.relay.c", path, to_stdout=False)
    n = len(a.handlers)
    b = lg.configure_logging("test.relay.c", path, to_stdout=False)
    assert a is b and len(b.handlers) == n   # no duplicate handlers


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in sorted(globals().items()):
            if name.startswith("t_") and callable(fn):
                import inspect
                fn(tmp) if inspect.signature(fn).parameters else fn()
                print("ok", name)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 tests/test_logs.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'logsetup'`.

- [ ] **Step 3: Implement `configure_logging`**

Create `src/scripts/logsetup.py`:

```python
"""Reusable, mostly-pure logging helpers for the racecast daemons and log surface.
stdlib-only by design — DO NOT import config.py here (the relay stays
dependency-light, like the other self-contained scripts). Covers: rotating
timestamped loggers, the single log-prune authority, subprocess line
classification + a pump, external-app log discovery, and archive resolution."""
import logging, os, re, sys, time
from logging.handlers import TimedRotatingFileHandler

DEFAULT_RETENTION_DAYS = 7
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def configure_logging(name, log_path, level=logging.INFO, to_stdout=None):
    """A logging.Logger writing timestamped, leveled lines to log_path with daily
    midnight rotation (archive suffix `.YYYY-MM-DD`). backupCount=0 -> the handler
    never deletes; prune_old_logs is the sole deletion authority. A stdout
    StreamHandler is added only on a TTY (foreground run) — a daemon whose stdout is
    a redirected file must not double-write. Idempotent per `name`."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    if any(getattr(h, "_racecast", False) for h in logger.handlers):
        return logger
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    fh = TimedRotatingFileHandler(log_path, when="midnight", backupCount=0,
                                  encoding="utf-8")
    fh.setFormatter(fmt)
    fh._racecast = True
    logger.addHandler(fh)
    on_tty = sys.stdout.isatty() if to_stdout is None else to_stdout
    if on_tty:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        sh._racecast = True
        logger.addHandler(sh)
    return logger
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 tests/test_logs.py`
Expected: PASS — `ok t_configure_logging_*`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/logsetup.py tests/test_logs.py
git commit -m "feat(logs): rotating timestamped logger helper (configure_logging)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `logsetup.prune_old_logs` — the single 7-day cleanup authority

**Files:**
- Modify: `src/scripts/logsetup.py`
- Test: `tests/test_logs.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_logs.py`)

```python
def t_prune_removes_only_old_files(tmp):
    d = os.path.join(tmp, "prune"); os.makedirs(d)
    now = 1_000_000_000
    fresh = os.path.join(d, "relay.console.log")
    old = os.path.join(d, "relay.console.log.2020-01-01")
    for p in (fresh, old):
        open(p, "w").close()
    os.utime(fresh, (now - 1 * 86400, now - 1 * 86400))    # 1 day old -> keep
    os.utime(old, (now - 30 * 86400, now - 30 * 86400))    # 30 days old -> delete
    removed = lg.prune_old_logs(d, keep_days=7, now_ts=now)
    assert removed == [old], removed
    assert os.path.exists(fresh) and not os.path.exists(old)


def t_prune_missing_dir_is_noop():
    assert lg.prune_old_logs("/no/such/dir/xyz", keep_days=7, now_ts=1) == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 tests/test_logs.py`
Expected: FAIL — `AttributeError: module 'logsetup' has no attribute 'prune_old_logs'`.

- [ ] **Step 3: Implement** (append to `src/scripts/logsetup.py`)

```python
def prune_old_logs(log_dir, keep_days=DEFAULT_RETENTION_DAYS, now_ts=None):
    """Delete files in log_dir whose mtime is older than keep_days; return the
    removed paths. The ONLY log-deletion path — covers every log type (rotated
    console/feed logs, *.boot.log, the Tailscale snapshot, any local OBS copies).
    `now_ts` is injectable for deterministic tests. Best-effort: unreadable dir or
    a vanishing file is skipped, never raised."""
    now_ts = time.time() if now_ts is None else now_ts
    cutoff = now_ts - keep_days * 86400
    removed = []
    try:
        names = os.listdir(log_dir)
    except OSError:
        return removed
    for name in names:
        p = os.path.join(log_dir, name)
        try:
            if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                os.remove(p)
                removed.append(p)
        except OSError:
            pass
    return sorted(removed)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 tests/test_logs.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/logsetup.py tests/test_logs.py
git commit -m "feat(logs): prune_old_logs — single 7-day cleanup authority

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: subprocess classification + tag + pump

**Files:**
- Modify: `src/scripts/logsetup.py`
- Test: `tests/test_logs.py`

- [ ] **Step 1: Write the failing test** (append)

```python
def t_classify_subproc_line_levels():
    assert lg.classify_subproc_line("HTTP 403 Forbidden") == logging.ERROR
    assert lg.classify_subproc_line("Traceback (most recent call last)") == logging.ERROR
    assert lg.classify_subproc_line("Waiting for streams, retrying in 5s") == logging.WARNING
    assert lg.classify_subproc_line("Opening stream: 1080p (hls)") == logging.INFO


def t_tag_line_prefixes_and_strips_eol():
    assert lg.tag_line("feed_A", "serving stint 3\n") == "[feed_A] serving stint 3"
    assert lg.tag_line("relay", "x\r\n") == "[relay] x"


def t_pump_subprocess_logs_each_line(tmp):
    import io
    path = os.path.join(tmp, "logs", "feed_A.log")
    log = lg.configure_logging("test.pump", path, to_stdout=False)
    stream = io.StringIO("Opening stream\nHTTP 403 Forbidden\n")
    lg.pump_subprocess(stream, log, "streamlink")
    for h in log.handlers:
        h.flush()
    body = open(path, encoding="utf-8").read()
    assert "INFO [streamlink] Opening stream" in body, body
    assert "ERROR [streamlink] HTTP 403 Forbidden" in body, body
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 tests/test_logs.py`
Expected: FAIL — `classify_subproc_line` missing.

- [ ] **Step 3: Implement** (append)

```python
_ERROR_HINTS = ("error", "fatal", "forbidden", "403", "401", "traceback",
                "exception", "failed", "denied", "could not", "no such")
_WARN_HINTS = ("warn", "retry", "retrying", "unable", "timeout", "timed out",
               "waiting for")


def classify_subproc_line(line):
    """Heuristic logging level for one pumped subprocess line."""
    low = line.lower()
    if any(h in low for h in _ERROR_HINTS):
        return logging.ERROR
    if any(h in low for h in _WARN_HINTS):
        return logging.WARNING
    return logging.INFO


def tag_line(source, line):
    """Prefix a single log line with its source tag for the merged view, stripping
    the trailing newline/carriage-return."""
    return f"[{source}] {line.rstrip(chr(10)).rstrip(chr(13))}"


def pump_subprocess(stream, logger, tag):
    """Read text lines from a subprocess pipe (stream) and log each at a classified
    level, prefixed `[tag]`. Runs to EOF; swallows read errors. Designed to run in a
    daemon thread so it never blocks daemon shutdown."""
    try:
        for raw in iter(stream.readline, ""):
            if raw == "":
                break
            line = raw.rstrip("\n").rstrip("\r")
            logger.log(classify_subproc_line(line), "[%s] %s", tag, line)
    except (ValueError, OSError):
        pass   # pipe closed mid-read — end the thread, never the daemon
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 tests/test_logs.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/logsetup.py tests/test_logs.py
git commit -m "feat(logs): subprocess line classification, tagging, and pump

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: external-log discovery (OBS dir + generic list/newest)

**Files:**
- Modify: `src/scripts/logsetup.py`
- Test: `tests/test_logs.py`

> Cross-platform note (CLAUDE.md): `obs_log_dir` builds a *fixed-OS* path from the
> passed `platform`, so it uses string concatenation with explicit `/`, NOT
> `os.path.join` (which injects `\` on the Windows runner and would break the pinned
> POSIX fixtures below).

- [ ] **Step 1: Write the failing test** (append)

```python
def t_obs_log_dir_per_platform():
    assert lg.obs_log_dir("darwin", home="/Users/x") == \
        "/Users/x/Library/Application Support/obs-studio/logs"
    assert lg.obs_log_dir("linux", home="/home/x") == "/home/x/.config/obs-studio/logs"
    assert lg.obs_log_dir("win32", home="/h", env={"APPDATA": "C:/Users/x/AppData/Roaming"}) \
        == "C:/Users/x/AppData/Roaming/obs-studio/logs"


def t_list_and_newest_log_order(tmp):
    d = os.path.join(tmp, "ll"); os.makedirs(d)
    a = os.path.join(d, "a.log"); b = os.path.join(d, "b.log")
    open(a, "w").close(); open(b, "w").close()
    os.utime(a, (100, 100)); os.utime(b, (200, 200))
    assert lg.list_logs(d) == [b, a]          # newest first
    assert lg.newest_log(d) == b
    assert lg.newest_log(os.path.join(tmp, "empty")) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 tests/test_logs.py`
Expected: FAIL — `obs_log_dir` missing.

- [ ] **Step 3: Implement** (append)

```python
def obs_log_dir(platform, home=None, env=None):
    """OBS Studio's log directory for a platform. Fixed-OS path -> string concat
    with '/', never os.path.join (see plan note). Returns the dir (may not exist)."""
    home = os.path.expanduser("~") if home is None else home
    env = os.environ if env is None else env
    if platform == "darwin":
        return home + "/Library/Application Support/obs-studio/logs"
    if platform.startswith("win") or platform == "nt":
        base = (env.get("APPDATA") or (home + "/AppData/Roaming")).replace("\\", "/")
        return base + "/obs-studio/logs"
    return home + "/.config/obs-studio/logs"


def list_logs(log_dir):
    """Regular files in log_dir, newest-first by mtime; [] if dir is absent."""
    try:
        files = [os.path.join(log_dir, f) for f in os.listdir(log_dir)]
    except OSError:
        return []
    files = [f for f in files if os.path.isfile(f)]
    files.sort(key=os.path.getmtime, reverse=True)
    return files


def newest_log(log_dir):
    """Newest file in log_dir, or None."""
    files = list_logs(log_dir)
    return files[0] if files else None
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 tests/test_logs.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/logsetup.py tests/test_logs.py
git commit -m "feat(logs): external-log discovery (obs_log_dir, list_logs, newest_log)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: archive resolution with a path-traversal guard

**Files:**
- Modify: `src/scripts/logsetup.py`
- Test: `tests/test_logs.py`

- [ ] **Step 1: Write the failing test** (append)

```python
def t_archive_dates_lists_rotated(tmp):
    d = os.path.join(tmp, "ad"); os.makedirs(d)
    for n in ("relay.console.log", "relay.console.log.2026-06-17",
              "relay.console.log.2026-06-16", "feed_A.log.2026-06-17", "junk.txt"):
        open(os.path.join(d, n), "w").close()
    assert lg.archive_dates(d, ["relay.console.log", "feed_A.log"]) == \
        ["2026-06-17", "2026-06-16"]


def t_resolve_archive_ok_and_guards(tmp):
    d = os.path.join(tmp, "ra"); os.makedirs(d)
    good = os.path.join(d, "relay.console.log.2026-06-17")
    open(good, "w").close()
    assert lg.resolve_archive(d, "relay.console.log", "2026-06-17") == os.path.realpath(good)
    assert lg.resolve_archive(d, "relay.console.log", "2026-06-18") is None   # no file
    assert lg.resolve_archive(d, "relay.console.log", "../../etc/passwd") is None
    assert lg.resolve_archive(d, "../relay.console.log", "2026-06-17") is None
    assert lg.resolve_archive(d, "relay.console.log", "2026-13-99x") is None   # bad date shape
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 tests/test_logs.py`
Expected: FAIL — `archive_dates` missing.

- [ ] **Step 3: Implement** (append)

```python
def archive_dates(log_dir, basenames):
    """Sorted-descending list of YYYY-MM-DD dates for which any of `basenames` has a
    rotated archive (`<basename>.<date>`) in log_dir."""
    dates = set()
    for path in list_logs(log_dir):
        name = os.path.basename(path)
        for base in basenames:
            m = re.fullmatch(re.escape(base) + r"\.(\d{4}-\d{2}-\d{2})", name)
            if m:
                dates.add(m.group(1))
    return sorted(dates, reverse=True)


def resolve_archive(log_dir, basename, date):
    """Realpath of the archive `<basename>.<date>` inside log_dir, or None. Guards
    traversal: `date` must be exactly YYYY-MM-DD, `basename` must carry no path
    separators, and the resolved path must stay inside log_dir."""
    if not date or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return None
    if not basename or "/" in basename or "\\" in basename or os.sep in basename:
        return None
    root = os.path.realpath(log_dir)
    full = os.path.realpath(os.path.join(log_dir, f"{basename}.{date}"))
    try:
        inside = os.path.commonpath([root, full]) == root
    except ValueError:
        return None   # different drives on Windows
    if not inside or not os.path.isfile(full):
        return None
    return full
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 tests/test_logs.py`
Expected: PASS.

- [ ] **Step 5: Register the test file + commit**

If `tools/run-tests.py` keeps an explicit list of test modules, add `test_logs` to it (grep: `grep -n "test_services\|test_ui_jobs" tools/run-tests.py`). If it auto-discovers `tests/test_*.py`, no change is needed — confirm by running the suite.

```bash
python3 tools/run-tests.py
git add src/scripts/logsetup.py tests/test_logs.py tools/run-tests.py
git commit -m "feat(logs): archive_dates + resolve_archive (traversal-guarded)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `services.start_detached` boot-file separation

The relay/streams daemons will own their own rotating log file via `configure_logging`. `start_detached` must therefore stop owning that same file (two writers would corrupt rotation). We give it an explicit boot-log path for catching pre-logging crashes, defaulting to today's behavior so other callers are unaffected.

**Files:**
- Modify: `src/scripts/services.py:158-172`
- Test: `tests/test_services.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_services.py`, before the runner)

```python
def t_start_detached_uses_boot_log_when_given(tmp):
    boot = os.path.join(tmp, "logs", "relay.boot.log")
    pidf = os.path.join(tmp, "relay.pid")
    argv = [sys.executable, "-c", "import sys; sys.stderr.write('boom\\n')"]
    pid = sv.start_detached(argv, boot, pidf)
    sv.stop_pid(pid, pidf, timeout=5)
    assert os.path.exists(boot)             # crash/stderr captured to the boot file
    assert "boom" in open(boot, encoding="utf-8").read()
```

(Existing `t_start_detached_then_stop` still passes — the signature is unchanged.)

- [ ] **Step 2: Run it to verify it passes already / behavior baseline**

Run: `python3 tests/test_services.py`
Expected: PASS (this test documents the boot-file role; `start_detached` already appends stdout/stderr to its `log_path`). No code change to `start_detached` itself is required — the "boot file" is simply *which path the caller passes*. Keep this test as the regression guard for that contract.

- [ ] **Step 3: Commit**

```bash
git add tests/test_services.py
git commit -m "test(services): document start_detached boot-file capture contract

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

> Implementation note for later tasks: callers (relay/streams) pass a `*.boot.log`
> path to `start_detached`; the daemon configures its own `configure_logging` to the
> real `*.console.log`/`feed_*.log`.

---

## Task 7: relay console logger + the four event classes

Replace the relay's `print()` with a module logger writing to `relay.console.log`, and add the start-context / handover / schedule event lines the operator is missing.

**Files:**
- Modify: `src/relay/racecast-feeds.py` (main setup near `:3359-3365`; `print()` sites throughout; argparse for `--logdir`)
- Test: manual + suite (the relay is a script; its pure helpers stay tested via `test_pov.py` etc.)

- [ ] **Step 1: Add the logger in `main()`**

After the `logdir` is computed (`racecast-feeds.py:3364-3365`), add — note the relay already adds `src/scripts` to `sys.path`, so `logsetup` imports directly:

```python
    import logsetup
    LOG = logsetup.configure_logging(
        "racecast.relay", os.path.join(logdir, "relay.console.log"))
    _keep = int(os.environ.get("RACECAST_LOG_RETENTION_DAYS") or logsetup.DEFAULT_RETENTION_DAYS)
    logsetup.prune_old_logs(logdir, keep_days=_keep)   # cleanup on every start
```

Make `LOG` reachable where the relay currently prints. If the relay prints from module-level functions (not just `main`), store it on the relay/server object the same way `logdir`/`cookies` are threaded, OR expose a module-global set once in `main`:

```python
# near the top of racecast-feeds.py, module level:
LOG = logging.getLogger("racecast.relay")   # configured in main(); safe to use early
```

(`logging.getLogger` returns the same instance `configure_logging` later attaches handlers to, so module-level call sites work without threading a parameter.)

- [ ] **Step 2: Emit the start-context header** (right after the logger is configured in `main`, where `csv_url`, `ports`, bind, mode are known — `racecast-feeds.py:3368+`)

```python
    LOG.info("relay starting — profile=%s bind=%s ports=%s mode=%s schedule=%s",
             os.environ.get("RACECAST_PROFILE", "?"), args.bind, args.ports,
             ("qualifying" if args.qualifying else "race"), csv_url)
```

- [ ] **Step 3: Convert existing `print()` sites to leveled logs**

Find them: `grep -n "print(" src/relay/racecast-feeds.py`. Apply this mapping (mechanical):
- `print("WARN: …")` / `print(f"WARN…")` → `LOG.warning("…")` (drop the `WARN:` prefix; the level shows it).
- `print("ERROR…")` → `LOG.error("…")`.
- `print("INFO: …")` and all other informational prints → `LOG.info("…")`.
- Keep `print` only where it writes to a **captured pipe the CLI parses** (e.g. a `yt-dlp -g` resolve in a child process context) — none in the relay server loop; convert all server-side prints.

Representative conversions (already present lines):
```python
# racecast-feeds.py:1651
LOG.info("Schedule loaded from Google Sheet: %d stints.", len(self.items))
# racecast-feeds.py:1663
LOG.warning("sheet unreachable (%s). Serving cached/last schedule.", self.last_error)
# racecast-feeds.py:3585 (startup confirmation)
LOG.info("racecast relay running. Schedule source: %s", source_desc)
# racecast-feeds.py:3577 (shutdown)
LOG.info("Stopping feeds…")
```

- [ ] **Step 4: Add handover/stint + schedule-resolution event lines**

In the handover/reload/set_stint/set_mode paths (search `def handover`, `def reload`, `set_stint`, `set_mode`), add one INFO per transition, e.g.:
```python
LOG.info("handover -> feed %s now serving stint %d (%s)", feed.name, idx + 1, streamer)
LOG.info("reload: schedule re-read (%d stints)", len(self.source.items))
LOG.info("mode -> %s", self.mode)
```
Where a streamer name fails to resolve to a flag/brand via `asset_key`, add:
```python
LOG.warning("unresolved streamer name '%s' (no flag/brand match)", raw_name)
```
(Place this where `asset_key` is applied to schedule rows — search `asset_key(`.)

- [ ] **Step 5: Verify the relay still boots + writes a timestamped console log**

Run (from repo root, with the synthetic stubs or real tools on PATH):
```bash
python3 src/racecast.py relay run --help    # argparse intact
```
Then a smoke boot is exercised by the e2e harness in a later check. Confirm no `print(` remain in server paths:
```bash
grep -n "print(" src/relay/racecast-feeds.py
```
Expected: only `print` inside `if __name__`/CLI-usage/`sys.exit` message contexts, if any.

- [ ] **Step 6: Lint + commit**

```bash
python3 tools/lint.py
python3 tests/test_pov.py
git add src/relay/racecast-feeds.py
git commit -m "feat(relay): timestamped console logger + start/handover/schedule events

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: relay per-feed logger + streamlink pump

Convert each feed's `feed_<name>.log` from a raw `stdout=log` fd to a `configure_logging` logger, and pump the streamlink child's output through it (timestamps + classified levels + `[streamlink]` tag). Move the `resolve_hls`/`ssai_warning` diagnostic writes onto the same logger.

**Files:**
- Modify: `src/relay/racecast-feeds.py:2101` (feed init), `:2172-2207` (serve loop), `:1160-1180`/`:1313-1340` (resolve/ssai writes)

- [ ] **Step 1: Give the feed its own logger** — at `racecast-feeds.py:2101`, replace:

```python
        self.logfile = os.path.join(logdir, f"feed_{name}.log")
```
with:
```python
        self.logfile = os.path.join(logdir, f"feed_{name}.log")
        import logsetup
        self.log = logsetup.configure_logging(
            f"racecast.feed.{name}", self.logfile, to_stdout=False)
```

- [ ] **Step 2: Pump streamlink instead of redirecting its fd** — replace the serve block `racecast-feeds.py:2190-2207`:

```python
            with open(self.logfile, "a", encoding="utf-8") as log:
                log.write(f">> [{self.name}:{self.port}] serving stint {i+1} ({serve_platform})\n"); log.flush()
                cmd = streamlink_serve_cmd(target, self.port, serve_platform, token)
                try:
                    self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                                 env=external_tool_env(), **_no_window_kwargs())
                    if serve_platform != "youtube":   # YouTube keeps ssai_warning() result as last_error
                        self.last_error = None
                    self._set_phase("serving")
                    self.dropped = False          # live picture -> any prior alarm clears
                    serve_started = time.monotonic()
                    self.proc.wait()
                    serve_elapsed = time.monotonic() - serve_started
                    serve_rc = self.proc.returncode
                except FileNotFoundError:
                    log.write(f">> [{self.name}] streamlink not found on PATH — retrying\n"); log.flush()
                    self.proc = None
                    time.sleep(RETRY_SLEEP); continue
```
with:
```python
            import logsetup
            self.log.info("serving stint %d (%s)", i + 1, serve_platform)
            cmd = streamlink_serve_cmd(target, self.port, serve_platform, token)
            try:
                self.proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    env=external_tool_env(), **_no_window_kwargs())
                pump = threading.Thread(
                    target=logsetup.pump_subprocess,
                    args=(self.proc.stdout, self.log, "streamlink"), daemon=True)
                pump.start()
                if serve_platform != "youtube":
                    self.last_error = None
                self._set_phase("serving")
                self.dropped = False
                serve_started = time.monotonic()
                self.proc.wait()
                serve_elapsed = time.monotonic() - serve_started
                serve_rc = self.proc.returncode
            except FileNotFoundError:
                self.log.warning("streamlink not found on PATH — retrying")
                self.proc = None
                time.sleep(RETRY_SLEEP); continue
```

- [ ] **Step 3: Route the resolve/ssai diagnostic writes through the logger**

These helpers take a `logfile` path and `open(...,"a")` it (`racecast-feeds.py:1160-1180`, `:1313-1340`, `:2172`). Change their signature to accept the feed logger instead of a path and call `logger.info/warning(...)`. At each call site pass `self.log`:
- `resolve_hls(url, self.cookies, self.log, self.fmt)` (was `self.logfile`)
- `ssai_warning(hls, self.log)` (was `self.logfile`)
- the pre-serve `open(self.logfile,"a")` block at `:2172` → `self.log.info(...)`.

Inside those helpers, replace each `with open(logfile,"a") as log: log.write(f"…")` with `logger.warning("…")` / `logger.info("…")` (drop the leading `>>`/`WARN` decorations; the timestamp + level replace them).

- [ ] **Step 4: Confirm `threading` is imported** at the top of `racecast-feeds.py` (it already is — `threading.Event` is used at `:2100`). No new import needed beyond `logsetup`.

- [ ] **Step 5: Smoke + lint + commit**

```bash
python3 tools/lint.py
python3 tests/test_pov.py
grep -n "stdout=log\|open(self.logfile" src/relay/racecast-feeds.py   # expect: none
git add src/relay/racecast-feeds.py
git commit -m "feat(relay): per-feed rotating logger + streamlink pump (timestamps/levels)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: static streams — per-feed logger + pump + boot file

**Files:**
- Modify: `src/scripts/loopstream.py:87-129` (add `--log`, configure logger, pump)
- Modify: `src/scripts/start-streams.py:21-27` (feed_argv `--log`), `:137-147` (boot-file redirect)

- [ ] **Step 1: `loopstream` accepts `--log`, configures a logger, pumps streamlink**

Replace `loopstream.py:105-129` (`serve_once` + `main`) with:

```python
def serve_once(url, port, platform="youtube", twitch_token=None, logger=None):
    """Serve `url` on `port` until streamlink exits; returns its exit code. When a
    logger is given, streamlink's output is pumped through it (timestamps + levels +
    [streamlink] tag); otherwise it inherits stdout (legacy/standalone use)."""
    import logsetup
    if logger is None:
        return subprocess.call(streamlink_argv(url, port, platform, twitch_token),
                               env=external_tool_env(), **no_window_kwargs())
    proc = subprocess.Popen(streamlink_argv(url, port, platform, twitch_token),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            env=external_tool_env(), **no_window_kwargs())
    import threading
    threading.Thread(target=logsetup.pump_subprocess,
                     args=(proc.stdout, logger, "streamlink"), daemon=True).start()
    return proc.wait()


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("channel")
    ap.add_argument("port")
    ap.add_argument("--log", help="rotating log file this feed owns")
    a = ap.parse_args()
    ch, port = a.channel, a.port
    url = channel_url(ch)
    plat = platform_of(url)
    logger = None
    if a.log:
        import logsetup
        logger = logsetup.configure_logging(
            f"racecast.staticfeed.{port}", a.log, to_stdout=False)
        logsetup.prune_old_logs(
            os.path.dirname(a.log),
            keep_days=int(os.environ.get("RACECAST_LOG_RETENTION_DAYS") or logsetup.DEFAULT_RETENTION_DAYS))
    token = None
    if plat == "twitch":
        token = twitch_oauth_from_cookies(
            os.path.join(runtime_dir(os.path.dirname(os.path.abspath(__file__))), "twitch-cookies.txt"))
    while True:
        msg = f"connecting to {url} ({plat})"
        logger.info(msg) if logger else print(f">> [{port}] {msg}", flush=True)
        try:
            serve_once(url, port, plat, token, logger=logger)
        except FileNotFoundError:
            sys.exit("ERROR: streamlink not found (brew install streamlink / pip install -U streamlink).")
        end = "stream ended or not live — retrying in 10s"
        logger.warning(end) if logger else print(f">> [{port}] {end}", flush=True)
        time.sleep(10)
```

> `loopstream.py` already imports from `services` (a `src/scripts` sibling); add no
> path setup — `import logsetup` resolves the same way.

- [ ] **Step 2: `start-streams` passes `--log` and redirects the boot fd**

Replace `start-streams.py:21-27` (`feed_argv`):
```python
def feed_argv(frozen, executable, loop_path, channel, port, log_path):
    """Child argv for one feed. The feed OWNS log_path via its own rotating logger;
    start_detached captures only the boot/crash fd to a separate *.boot.log."""
    if frozen:
        return [executable, "streams", "run-feed", channel, port, "--log", log_path]
    return [executable, loop_path, channel, port, "--log", log_path]
```

Replace `start-streams.py:137-147` loop body:
```python
    for i, (ch, port) in enumerate(load_feeds(sdir), 1):
        feed_log = os.path.join(logdir, f"feed_{port}.log")
        boot_log = os.path.join(logdir, f"feed_{port}.boot.log")
        with open(boot_log, "ab") as boot:
            p = subprocess.Popen(
                feed_argv(frozen, sys.executable, loop, ch, port, feed_log),
                stdout=boot, stderr=subprocess.STDOUT,
                env=feed_env(frozen, os.environ), **_spawn_kwargs())
        with open(os.path.join(sdir, f"feed_{port}.pid"), "w") as fh:
            fh.write(str(p.pid))
        print(f"Started Feed {i} -> channel {ch} on http://127.0.0.1:{port} (log: {feed_log})")
```

- [ ] **Step 3: Update `test_streams.py` for the new `feed_argv` arity**

`grep -n "feed_argv" tests/test_streams.py` and update each call to pass a `log_path` arg, asserting `--log` + the path appear in the returned argv. Example:
```python
def t_feed_argv_repo_includes_log():
    argv = ss.feed_argv(False, "/py", "/loop.py", "UC123", "53001", "/r/logs/feed_53001.log")
    assert argv == ["/py", "/loop.py", "UC123", "53001", "--log", "/r/logs/feed_53001.log"]
def t_feed_argv_frozen_includes_log():
    argv = ss.feed_argv(True, "/bin/racecast", "/loop.py", "UC123", "53001", "/r/logs/feed_53001.log")
    assert argv == ["/bin/racecast", "streams", "run-feed", "UC123", "53001", "--log", "/r/logs/feed_53001.log"]
```

- [ ] **Step 4: Run + lint + commit**

```bash
python3 tests/test_streams.py
python3 tools/lint.py
git add src/scripts/loopstream.py src/scripts/start-streams.py tests/test_streams.py
git commit -m "feat(streams): per-feed rotating logger + streamlink pump + boot file

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Tailscale status snapshot log

Tailscale has no tailable log; append a timestamped `tailscale status` snapshot to `runtime/<profile>/logs/tailscale.snapshot.log` on each service start and on `racecast tailscale status`.

**Files:**
- Modify: `src/scripts/tailscale.py` (add a pure `status_snapshot_text(output, ts)` formatter)
- Modify: `src/racecast.py` (call it; append on `tailscale_status` + relay/streams start)
- Test: `tests/test_tailscale.py`

- [ ] **Step 1: Failing test** (append to `tests/test_tailscale.py`)

```python
def t_status_snapshot_text_shape():
    out = ts.status_snapshot_text("100.64.0.1  myhost  active", ts="2026-06-18 12:00:00")
    assert out.startswith("==== 2026-06-18 12:00:00 ====\n")
    assert out.rstrip().endswith("100.64.0.1  myhost  active")
    assert out.endswith("\n")
```

(`import tailscale as ts` is already at the top of that test file — confirm; add if missing.)

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 tests/test_tailscale.py`
Expected: FAIL — `status_snapshot_text` missing.

- [ ] **Step 3: Implement in `src/scripts/tailscale.py`**

```python
def status_snapshot_text(output, ts):
    """One timestamped snapshot block for the tailscale.snapshot.log. Pure: caller
    supplies the wall-clock `ts` string and the `tailscale status` text."""
    return f"==== {ts} ====\n{output.rstrip()}\n"
```

- [ ] **Step 4: Wire it in `src/racecast.py`**

Add a helper near the other log-path helpers (`racecast.py:551`):
```python
def _tailscale_snapshot_path():
    return os.path.join(_runtime_dir(), "logs", "tailscale.snapshot.log")

def _append_tailscale_snapshot():
    """Best-effort: append a timestamped `tailscale status` block to the snapshot log."""
    try:
        text = ts_mod.status_text()  # existing human-readable status, or build from status()
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        path = _tailscale_snapshot_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(ts_mod.status_snapshot_text(text, ts))
    except Exception:
        pass
```
> Use whichever existing tailscale accessor returns human-readable status text; if
> only `status()` (structured) exists, format a one-line summary from it. `ts_mod`
> is the module alias `src/racecast.py` already imports tailscale under — grep
> `import.*tailscale` to confirm the alias.

Call `_append_tailscale_snapshot()` from:
- `tailscale_status` command (after printing status),
- `relay_start` (right after the spawn, `racecast.py:1324`) and `streams_start`.

- [ ] **Step 5: Run + lint + commit**

```bash
python3 tests/test_tailscale.py
python3 tools/lint.py
git add src/scripts/tailscale.py src/racecast.py tests/test_tailscale.py
git commit -m "feat(tailscale): timestamped status snapshot log

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: source registry in `racecast.py` (files + archives + read)

Replace the flat `ctx["log_paths"]` with a registry describing each logical source as a set of live files plus archive listing/reading. This is the single source of truth the CLI and the UI both consume.

**Files:**
- Modify: `src/racecast.py` (new resolvers + `_log_sources()`; `ctx` at `:4541`)
- Test: `tests/test_racecast.py`

- [ ] **Step 1: Failing test** (append to `tests/test_racecast.py`)

```python
def t_log_sources_registry_shape():
    src = rc._log_sources()
    assert set(["relay", "streams", "obs", "companion", "tailscale", "aggregate"]) <= set(src)
    for name, spec in src.items():
        assert callable(spec["files"])         # () -> list[path]
        assert callable(spec["archives"])       # () -> list[token]
        assert callable(spec["read"])           # (token) -> text
    # aggregate's file set is the union of the individual sources
    agg = set(src["aggregate"]["files"]())
    parts = set()
    for n in ("relay", "streams", "obs", "companion", "tailscale"):
        parts |= set(src[n]["files"]())
    assert agg == parts
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `_log_sources` missing.

- [ ] **Step 3: Implement `_log_sources()` in `src/racecast.py`**

Add resolvers + the registry (near the existing log-path helpers):

```python
def _relay_feed_logs():
    """The relay's per-feed logs (feed_A/B/POV.log) under the profile logs dir."""
    d = os.path.join(_runtime_dir(), "logs")
    return sorted(glob.glob(os.path.join(d, "feed_*.log")))

def _relay_files():
    files = [_relay_log_path()] + _relay_feed_logs()
    return [f for f in files if os.path.exists(f)]

def _streams_files():
    d = os.path.join(_streams_static_dir(), "logs")
    return sorted(glob.glob(os.path.join(d, "feed_*.log")))

def _obs_files():
    import logsetup
    d = logsetup.obs_log_dir(sys.platform)
    newest = logsetup.newest_log(d)
    return [newest] if newest else []

def _companion_files():
    p = _companion_log_path()
    return [p] if p else []

def _tailscale_files():
    p = _tailscale_snapshot_path()
    return [p] if os.path.exists(p) else []

def _read_dated(dirpath, files, date):
    """Concatenate the rotated archives for `date` across a racecast source's files,
    each line source-prefixed. Empty string if none / bad date (guarded by
    resolve_archive)."""
    import logsetup
    chunks = []
    for f in files:
        arch = logsetup.resolve_archive(dirpath, os.path.basename(f), date)
        if arch:
            with open(arch, encoding="utf-8", errors="replace") as fh:
                label = os.path.basename(f).split(".log")[0]
                chunks += [f"[{label}] {ln.rstrip(chr(10))}" for ln in fh]
    return "\n".join(chunks)

def _read_named(dirpath, token):
    """Read one external log file by basename, guarded to dirpath. None if invalid."""
    if not token or "/" in token or "\\" in token or os.sep in token or ".." in token:
        return None
    root = os.path.realpath(dirpath)
    full = os.path.realpath(os.path.join(dirpath, token))
    try:
        if os.path.commonpath([root, full]) != root or not os.path.isfile(full):
            return None
    except ValueError:
        return None
    with open(full, encoding="utf-8", errors="replace") as fh:
        return fh.read()

def _log_sources():
    """Registry: source name -> {files, dir, archives, read}. Archives are opaque
    TOKENS: racecast sources use rotation dates (YYYY-MM-DD); external apps
    (obs/companion) use the older filenames in their dir (they do not follow our
    rotation naming). `read(token)` resolves a token to text per source. The UI and
    CLI both consume this registry."""
    relay_dir = os.path.join(_runtime_dir(), "logs")
    streams_dir = os.path.join(_streams_static_dir(), "logs")
    import logsetup
    def rc_src(files_fn, dirpath):
        return {"files": files_fn, "dir": dirpath,
                "archives": (lambda: logsetup.archive_dates(
                    dirpath, [os.path.basename(f) for f in files_fn()])),
                "read": (lambda tok: _read_dated(dirpath, files_fn(), tok))}
    def ext_src(files_fn, dirpath):
        def archives():
            cur = set(os.path.basename(f) for f in files_fn())   # exclude the live/newest
            return [os.path.basename(f) for f in logsetup.list_logs(dirpath)
                    if os.path.basename(f) not in cur]
        return {"files": files_fn, "dir": dirpath, "archives": archives,
                "read": (lambda tok: _read_named(dirpath, tok))}
    reg = {
        "relay": rc_src(_relay_files, relay_dir),
        "streams": rc_src(_streams_files, streams_dir),
        "tailscale": rc_src(_tailscale_files, relay_dir),
        "obs": ext_src(_obs_files, logsetup.obs_log_dir(sys.platform)),
        "companion": ext_src(_companion_files,
                             os.path.dirname(_companion_log_path() or "") or "."),
    }
    def _agg_files():
        out = []
        for n in ("relay", "streams", "obs", "companion", "tailscale"):
            out += reg[n]["files"]()
        return out
    reg["aggregate"] = {"files": _agg_files, "dir": relay_dir,
                        "archives": (lambda: []),       # aggregate is live-only
                        "read": (lambda tok: "")}
    return reg
```

- [ ] **Step 4: Wire `ctx`** — replace `racecast.py:4541-4543`:
```python
        "log_paths": {"relay": _relay_log_path,
                      "companion": _companion_log_path,
                      "streams": _latest_stream_log},
```
with:
```python
        "log_sources": _log_sources(),
```

- [ ] **Step 5: Run + lint + commit**

```bash
python3 tests/test_racecast.py
python3 tools/lint.py
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(logs): source registry (relay/streams/obs/companion/tailscale/aggregate)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: CLI — `--list` / `--archive`, `obs logs`, `tailscale logs`

Give the existing `logs` subcommands archive listing/reading, and add `obs`/`tailscale` log commands. Add a small shared helper that tails the **merged** live files for a source (so `relay logs` shows console + feed logs).

**Files:**
- Modify: `src/racecast.py` (`relay_logs`/`streams_logs`/`companion_logs`; new `obs_logs`/`tailscale_logs`; DISPATCH `:2442+`; CLI usage/help)
- Modify: `src/scripts/services.py` (a `tail_merged(paths, follow)` helper)
- Test: `tests/test_services.py`, `tests/test_racecast.py`

- [ ] **Step 1: Failing test for `tail_merged`** (append to `tests/test_services.py`)

```python
def t_tail_merged_prefixes_sources(tmp, capsys=None):
    import io, contextlib
    a = os.path.join(tmp, "feed_A.log"); b = os.path.join(tmp, "feed_B.log")
    open(a, "w").write("a-line\n"); open(b, "w").write("b-line\n")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sv.tail_merged([a, b], follow=False, lines=10)
    out = buf.getvalue()
    assert "[feed_A] a-line" in out and "[feed_B] b-line" in out
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 tests/test_services.py`
Expected: FAIL — `tail_merged` missing.

- [ ] **Step 3: Implement `tail_merged` in `src/scripts/services.py`** (below `tail`)

```python
def tail_merged(paths, follow=False, lines=40, label_of=None):
    """Tail several files into one stream, each line prefixed with its source
    (`[basename] line`). Non-follow: print the last `lines` of each file, source
    order. Follow: poll all files and emit new lines as they arrive (arrival order).
    `label_of(path) -> str` overrides the source label (default: basename w/o .log)."""
    import os as _os
    paths = [p for p in paths if p and _os.path.exists(p)]
    if not paths:
        print("(no log yet)")
        return
    def lbl(p):
        return label_of(p) if label_of else _os.path.basename(p).split(".log")[0]
    handles = []
    for p in paths:
        fh = open(p, encoding="utf-8", errors="replace")
        for line in fh.readlines()[-lines:]:
            sys.stdout.write(f"[{lbl(p)}] {line.rstrip(chr(10))}\n")
        handles.append((fh, p))
    if not follow:
        for fh, _ in handles:
            fh.close()
        return
    try:
        while True:
            quiet = True
            for fh, p in handles:
                line = fh.readline()
                if line:
                    sys.stdout.write(f"[{lbl(p)}] {line.rstrip(chr(10))}\n")
                    sys.stdout.flush()
                    quiet = False
            if quiet:
                time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        for fh, _ in handles:
            fh.close()
```

- [ ] **Step 4: Rewrite the CLI `logs` handlers in `src/racecast.py`**

Add a shared dispatcher and replace `relay_logs`/`companion_logs`/`streams_logs` (`:1521`, `:1738`, `:1798`):

```python
def _logs_cmd(source_name, rest):
    src = _log_sources().get(source_name)
    if src is None:
        print(f"(unknown log source: {source_name})"); return
    if "--list" in rest:
        toks = src["archives"]()
        print("\n".join(toks) if toks else "(no archives)")
        return
    if "--archive" in rest:
        tok = rest[rest.index("--archive") + 1]
        text = src["read"](tok)
        print(text if text else f"(no archive '{tok}')")
        return
    sv.tail_merged(src["files"](), follow=("-f" in rest or "--follow" in rest))

def relay_logs(rest):      _logs_cmd("relay", rest)
def streams_logs(rest):    _logs_cmd("streams", rest)
def companion_logs(rest):  _logs_cmd("companion", rest)
def obs_logs(rest):        _logs_cmd("obs", rest)
def tailscale_logs(rest):  _logs_cmd("tailscale", rest)
```

- [ ] **Step 5: Register new DISPATCH entries** (`racecast.py:2442+`)

Add:
```python
    ("obs", "logs"): obs_logs,
    ("tailscale", "logs"): tailscale_logs,
```
(Keep the existing `("relay","logs")` etc. — they now point at the rewritten handlers.)

- [ ] **Step 6: Update CLI usage/help text** — add `obs logs` and `tailscale logs`, and the `--list`/`--archive` flags, to the `docstring` command list at the top of `src/racecast.py` (the same block CLAUDE.md mirrors).

- [ ] **Step 7: Failing/passing test for routing** (append to `tests/test_racecast.py`)

```python
def t_dispatch_has_obs_and_tailscale_logs():
    assert ("obs", "logs") in rc.DISPATCH
    assert ("tailscale", "logs") in rc.DISPATCH
```

- [ ] **Step 8: Run + lint + commit**

```bash
python3 tests/test_services.py tests/test_racecast.py
python3 tools/lint.py
git add src/racecast.py src/scripts/services.py tests/test_services.py tests/test_racecast.py
git commit -m "feat(logs): CLI --list/--archive + obs/tailscale logs + merged tail

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Control Center server — archives, file read, merge-tail, aggregate

Refactor `_stream_log` onto the source registry (multi-file merge-tail) and add archive routes + the aggregate stream.

**Files:**
- Modify: `src/ui/ui_server.py` (`:552-554` routing; `:863-891` `_stream_log`; add `_log_archives`, `_log_file`, `_stream_aggregate`)
- Test: `tests/test_ui_server.py`

- [ ] **Step 1: Failing tests** (append to `tests/test_ui_server.py`, mirroring existing `_get` helpers; build `ctx["log_sources"]` with a temp dir)

```python
def t_log_archives_lists_dates(tmp):
    d = os.path.join(tmp, "logs"); os.makedirs(d)
    for n in ("relay.console.log", "relay.console.log.2026-06-17"):
        open(os.path.join(d, n), "w").close()
    ctx = _ctx_with_sources(tmp)        # helper: builds log_sources over tmp (see below)
    port = _serve(ctx)
    code, body = _get(port, "/api/logs/relay/archives")
    assert code == 200 and "2026-06-17" in body


def t_log_file_rejects_traversal(tmp):
    ctx = _ctx_with_sources(tmp)
    port = _serve(ctx)
    code, _ = _get(port, "/api/logs/relay/file?token=../../etc/passwd")
    assert code == 400
```

Add a small `_ctx_with_sources(tmp)` builder in the test that mimics `racecast._log_sources()` shape over `tmp` (so the server test stays independent of `racecast.py`).

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 tests/test_ui_server.py`
Expected: FAIL — routes 404 / helper missing.

- [ ] **Step 3: Routing** — replace `ui_server.py:552-554`:

```python
            if path.startswith("/api/logs/") and path.endswith("/stream"):
                name = path.split("/")[3]
                if name == "aggregate":
                    return self._stream_aggregate()
                return self._stream_log(name) if name else self._not_found("unknown log")
            if path.startswith("/api/logs/") and path.endswith("/archives"):
                name = path.split("/")[3]
                return self._log_archives(name)
            if path.startswith("/api/logs/") and "/file" in path:
                name = path.split("/")[3]
                return self._log_file(name, qs.get("token", [""])[0])
```
(`qs` = the parsed query string the handler already computes for other routes; reuse it. If not present in scope, parse via `urllib.parse.urlparse`/`parse_qs` as the file does elsewhere.)

- [ ] **Step 4: Implement the handlers** (replace `_stream_log` at `:863`, add the rest)

```python
        def _src(self, name):
            return ctx.get("log_sources", {}).get(name)

        def _log_archives(self, name):
            src = self._src(name)
            if src is None:
                return self._not_found(f"unknown log: {name}")
            return self._json({"ok": True, "tokens": src["archives"]()})

        def _log_file(self, name, token):
            src = self._src(name)
            if src is None:
                return self._not_found(f"unknown log: {name}")
            # Structural guard up front (defense-in-depth; the source read() guards too).
            if not token or "/" in token or "\\" in token or ".." in token:
                return self._json({"ok": False, "error": "bad token"}, code=400)
            text = src["read"](token)
            return self._json({"ok": True, "text": text or ""})

        def _tail_files(self, files, label_of):
            """Yield (label, line) for the last TAIL_LINES of each file then new
            lines as they arrive (arrival order). Used by single-source + aggregate."""
            import threading, queue
            q = queue.Queue()
            stop = {"v": False}
            def follow(path):
                try:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        for ln in fh.readlines()[-TAIL_LINES:]:
                            q.put((label_of(path), ln.rstrip("\r\n")))
                        while not stop["v"]:
                            ln = fh.readline()
                            if ln:
                                q.put((label_of(path), ln.rstrip("\r\n")))
                            else:
                                time.sleep(0.4)
                except OSError:
                    pass
            for p in files:
                threading.Thread(target=follow, args=(p,), daemon=True).start()
            return q, stop

        def _stream_source(self, files, label_of):
            self._sse_headers()
            if not files:
                self.wfile.write(sse_frame("(no log yet — waiting)")); self.wfile.flush()
            q, stop = self._tail_files(files, label_of)
            try:
                while True:
                    try:
                        label, line = q.get(timeout=0.5)
                        self.wfile.write(sse_frame(f"[{label}] {line}"))
                        self.wfile.flush()
                    except Exception:
                        self.wfile.write(b": ping\n\n"); self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                stop["v"] = True
                return None

        def _stream_log(self, name):
            src = self._src(name)
            if src is None:
                return self._not_found(f"unknown log: {name}")
            files = src["files"]()
            return self._stream_source(
                files, lambda p: os.path.basename(p).split(".log")[0])

        def _stream_aggregate(self):
            src = self._src("aggregate")
            if src is None:
                return self._not_found("aggregate unavailable")
            return self._stream_source(
                src["files"](), lambda p: os.path.basename(p).split(".log")[0])
```

> The aggregate's file set is captured at connect; feeds that appear later are out
> of scope for this iteration's server (documented in the spec under "discovered/
> refreshed periodically" — a follow-up may re-glob). For now, reconnecting picks up
> new feeds. If periodic refresh is wanted now, add a thread that re-globs
> `src["files"]()` every few seconds and starts a `follow()` for unseen paths.

- [ ] **Step 5: Run + lint + commit**

```bash
python3 tests/test_ui_server.py
python3 tools/lint.py
git add src/ui/ui_server.py tests/test_ui_server.py
git commit -m "feat(ui): log archives + file read + multi-file merge-tail + aggregate stream

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Control Center frontend — dropdown, archive picker, static read

**Files:**
- Modify: `src/ui/control-center.html:893-903` (logs view), `:3458-3467` (`watchLog`)

- [ ] **Step 1: Update the logs view markup** — replace `:896-901`:

```html
          <select id="logsel" onchange="onLogSourceChange()" aria-label="Log source">
            <option value="aggregate">All (live)</option>
            <option value="relay">relay</option>
            <option value="streams">streams</option>
            <option value="obs">obs</option>
            <option value="companion">companion</option>
            <option value="tailscale">tailscale</option>
          </select>
          <select id="logarch" onchange="onLogArchiveChange()" aria-label="Archive (day)">
            <option value="">live</option>
          </select></div>
```

- [ ] **Step 2: Replace `watchLog` (`:3458-3467`) with the source/archive logic**

```javascript
function onLogSourceChange() {
  const name = $('logsel').value;
  populateArchives(name);
  $('logarch').value = '';
  watchLog(name);
}

async function populateArchives(name) {
  const sel = $('logarch');
  sel.innerHTML = '<option value="">live</option>';
  if (name === 'aggregate') { sel.disabled = true; return; }
  sel.disabled = false;
  try {
    const r = await fetch('/api/logs/' + name + '/archives');
    const j = await r.json();
    (j.tokens || []).forEach(t => {
      const o = document.createElement('option');
      o.value = t; o.textContent = t; sel.appendChild(o);
    });
  } catch (e) {}
}

function onLogArchiveChange() {
  const name = $('logsel').value, token = $('logarch').value;
  if (!token) { watchLog(name); return; }
  if (logES) { logES.close(); logES = null; }
  loadArchive(name, token);
}

async function loadArchive(name, token) {
  $('svclog').textContent = '(loading…)';
  try {
    const r = await fetch('/api/logs/' + name + '/file?token=' + encodeURIComponent(token));
    const j = await r.json();
    $('svclog').textContent = j.ok ? (j.text || '(empty)') : ('(' + (j.error || 'error') + ')');
  } catch (e) { $('svclog').textContent = '(failed to load archive)'; }
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
```

- [ ] **Step 3: Default the logs view to aggregate on open** — find where the logs view is shown/activated (search `data-view="logs"` activation or a `showView('logs')`); ensure `onLogSourceChange()` runs once when the view first becomes visible so "All (live)" starts streaming. If the view simply unhides, add a one-time call in the view-switch handler: when target view is `logs` and `!logES`, call `onLogSourceChange()`.

- [ ] **Step 4: Manual verification (local dev build)**

```bash
python3 src/racecast.py ui    # open http://127.0.0.1:8089 -> Logs view
```
Confirm: "All (live)" is selected by default and streams; switching to `relay` shows console + `[feed_A]`/`[feed_B]` lines; the archive dropdown lists past days (after a rotation/with a seeded `*.2026-06-17` file) and renders static content; `obs`/`tailscale` show their logs or a friendly empty message.

- [ ] **Step 5: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(ui): aggregate-default log view + source/archive selectors

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Docs + wiki screenshot

**Files:**
- Modify: `CLAUDE.md` (commands list + test list), `README.md`
- Modify: `src/docs/wiki/images/cc-logs.png` (regenerate), and `src/docs/wiki/` Logs page if one exists

- [ ] **Step 1: Update CLAUDE.md** — add `python3 tests/test_logs.py` to the test list with a one-line description; add the new CLI forms (`relay logs --list/--archive`, `obs logs`, `tailscale logs`) to the commands block; add a short note under the relay/Architecture section that logs are timestamped, daily-rotated (7-day cleanup via `RACECAST_LOG_RETENTION_DAYS`), and that "relay"/"streams"/"aggregate" are merged-file sources.

- [ ] **Step 2: Update README.md** — mirror the new `logs` flags + `obs`/`tailscale logs` in the operator command list.

- [ ] **Step 3: Regenerate `cc-logs.png` from a LOCAL DEV BUILD** (CLAUDE.md hard rule + memory `wiki-screenshots-use-local-dev-build`):
  - Run `racecast ui` straight from `src/` (no `VERSION` file stamped) so the version badge reads "dev build".
  - Open the **Logs** view, leave "All (live)" selected, drive it with the Playwright MCP, and take an **element** screenshot of the logs view card (match the framing of the existing image — not a full-window grab).
  - Overwrite `src/docs/wiki/images/cc-logs.png`.

- [ ] **Step 4: Full suite + build verify + lint**

```bash
python3 tools/run-tests.py
python3 tools/lint.py
python3 tools/build.py        # verify step: tokenization, no secrets, no shell scripts
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md README.md src/docs/wiki/images/cc-logs.png src/docs/wiki/
git commit -m "docs(logs): document logging feature + refresh cc-logs screenshot

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification

- [ ] `python3 tools/run-tests.py` — whole suite green (incl. new `test_logs.py`).
- [ ] `python3 tools/lint.py` — clean.
- [ ] `python3 tools/build.py` — verify step passes.
- [ ] `python3 tools/e2e.py` — synthetic harness still green (relay boots with the new logger; no `print`-path regressions). Optionally `--shots DIR` to eyeball the logs view.
- [ ] Manual: relay + streams logs carry `YYYY-MM-DD HH:MM:SS LEVEL …` timestamps; `feed_*.log` carries `[streamlink]` lines; Control Center "All (live)" is the default and merges relay+streams+external; archive day-picker reads past logs; files older than 7 days are pruned on the next service start.

## Notes on tricky bits

- **Two writers, one file:** never let `start_detached` redirect a daemon's stdout to the same file the daemon's `configure_logging` owns — always a separate `*.boot.log`. (Tasks 7-9.)
- **Frozen mode:** `configure_logging` + pump threads run in the re-invoked daemon process (`racecast relay run`, `streams run-feed`); paths resolve under `runtime/<profile>/` next to the binary. No frozen-specific code needed, but smoke the binary path via the e2e `binary` job before release.
- **Cross-platform paths:** `obs_log_dir` builds fixed-OS paths with `/` concatenation, never `os.path.join` (Task 4 note) — the Windows CI runner would otherwise inject `\` and fail the pinned POSIX fixtures.
- **Aggregate liveness:** the aggregate captures its file set at connect; document that newly-started feeds need a reconnect (or add the optional periodic re-glob in Task 13 Step 4).
