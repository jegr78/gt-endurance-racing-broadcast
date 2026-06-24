# Control Center `app.log` — persist action/console output to disk

**Date:** 2026-06-24
**Status:** Design (approved)
**Area:** Control Center (`src/racecast_ui.py`, `src/ui/`), logging (`src/scripts/logsetup.py`)

## Problem

When an operator triggers an action in the Control Center, the resulting output
appears in a short console view in the browser. That output lives **only in
memory**: each action spawns a child process (`JobManager` in
`src/ui/ui_jobs.py`); the reader thread decodes its combined stdout/stderr line by
line into a per-`Job` Python list (`Job.lines`, head-trimmed at `max_lines=5000`)
and streams it to the browser over SSE. Nothing is written to disk and nothing is
timestamped, so once the Control Center process exits — or the 5000-line buffer
trims — the record of what was run and what it produced is gone. There is no way
to review, after the fact, which actions ran and how they ended.

## Goal

Persist Control Center action output to a timestamped, rotating log file
(`app.log`) that slots into the existing logging infrastructure and shows up as a
normal log source in the Control Center's own log viewer — **without** changing
the in-memory buffer or the SSE/browser flow.

## Non-goals

- No change to the browser console view (it stays concise and timestamp-free; the
  timestamps live in the file).
- No new logging mechanism — reuse `logsetup`.
- No capture of non-job UI surfaces (e.g. the `.env` editor, profile switches).
  Only the spawned-action jobs are logged. (Could be added later; out of scope.)
- No per-job-id correlation beyond an `[op]` line prefix.

## Decisions (resolved during brainstorming)

- **Location: machine-wide `runtime/logs/app.log`** (a new top-level `runtime/logs/`
  directory), *not* per-profile. The Control Center is a single machine-local app;
  many of its actions are machine-wide (`install-tools`, `install-apps`,
  `preflight`, `speedtest`, `freeport`, `cookies`) and the active profile can
  change during a session. Filing those under a profile would be misleading and a
  profile switch would split the Control Center's own history across files.
- **Content: action output + lifecycle markers** — each output line (1:1 with the
  console view) plus a start marker (op name + resolved argv) and an end marker
  (exit code). This makes the file answer "what did I click and what happened".

## Approach

Reuse `logsetup.configure_logging` to create a dedicated `racecast.app` logger
that writes to `runtime/logs/app.log`, created once at Control Center startup and
passed into the `JobManager`. The `JobManager`'s existing reader thread — which
already iterates the child's output lines — emits each line to the logger, plus a
start and an end marker. A new `"app"` entry in the log-source registry surfaces
the file (and its rotated archives) in the Control Center log viewer.

**Rejected alternatives:**

- *Own file handler inside `JobManager`* — duplicates the rotation/format/retention
  logic and risks drifting from the relay's behavior.
- *Log at the `do_POST` route layer* — the route does not see the streamed output
  lines, only start/exit; line capture must happen where the reader thread runs.

## Design

### 1. Logger + file (`src/racecast.py`, `run_ui()`)

Create the logger once when the Control Center starts, mirroring the relay's setup:

```python
import logsetup
app_log_dir = os.path.join(_runtime_base_dir(), "logs")   # machine-wide
logsetup.prune_old_logs(app_log_dir)                       # 7-day window, like the daemons
app_logger = logsetup.configure_logging(
    "racecast.app",
    os.path.join(app_log_dir, "app.log"),
    to_stdout=False,                                       # file only — the UI has its own console
)
```

- `configure_logging(name, log_path, level=INFO, to_stdout=None)` already gives the
  shared format `%(asctime)s %(levelname)s %(message)s` (`YYYY-MM-DD HH:MM:SS`),
  the `_ResilientTimedRotatingFileHandler` (midnight rotation, `.YYYY-MM-DD`
  archive suffix, `backupCount=0`), and `delay=True` (the file is created on the
  **first** write, so an idle session leaves no empty `app.log`).
- `prune_old_logs(app_log_dir)` runs once at startup (default 7-day retention,
  overridable via `RACECAST_LOG_RETENTION_DAYS`), exactly as the relay/streams
  daemons prune their dirs on start.
- Exact runtime-dir helper to use is whatever `run_ui()` already resolves for the
  machine-wide runtime base (the same base under which `runtime/active-profile`
  and `runtime/<profile>/` live), so `app.log` is a sibling of the per-profile log
  trees.

### 2. JobManager logs lifecycle + lines (`src/ui/ui_jobs.py`)

`JobManager.__init__` gains an optional `logger=None` parameter (stored as
`self.logger`). When `None`, nothing is logged — so existing tests and any caller
that does not pass a logger are unaffected, and the SSE/in-memory paths are
untouched.

- **`start()`** — capture `argv = self.argv_for(op_args)` into a local, spawn with
  it, and once the `Job` is successfully created emit a start marker:
  `self.logger.info("[%s] action started — argv: %s", op, " ".join(argv))`. (Logged
  on the success path only — a "still running" rejection or a spawn failure logs no
  start marker.)
- **`_reader()`** — for each decoded `line`, emit
  `self.logger.info("[%s] %s", job.op, line)` alongside the existing
  `job.lines.append(line)`. After `job.proc.wait()`, emit an end marker at a level
  that reflects the exit code:
  `INFO "[op] action finished — exit 0"` / `WARNING "[op] action finished — exit <code>"`.
- **Thread-exhaustion path** (the `RuntimeError` branch in `start()` that sets
  `exit_code = -1`) also emits a `WARNING` end marker, so a job that never produced
  a reader still leaves a trace.
- All logger calls are guarded (`if self.logger:`) so the `logger=None` default is
  a true no-op.

The `[op]` prefix keeps concurrently-running actions distinguishable in the single
machine-wide file. A numeric job id is intentionally omitted (YAGNI).

Example file content:

```
2026-06-24 19:40:11 INFO [relay-start] action started — argv: …/racecast relay start
2026-06-24 19:40:12 INFO [relay-start] racecast relay running.  Schedule source: sheet tab "Schedule"
2026-06-24 19:40:12 INFO [relay-start]   Feed A -> http://127.0.0.1:53001   Feed B -> http://127.0.0.1:53002
2026-06-24 19:40:13 INFO [relay-start] action finished — exit 0
```

### 3. Wire the logger into the manager (`src/racecast.py`, `run_ui()`)

Pass `logger=app_logger` where the `JobManager` is instantiated for the Control
Center.

### 4. Surface `app.log` in the log viewer (`src/racecast.py`, `_log_sources()`)

Add an `"app"` source to the log-source registry, pointing at the machine-wide
`runtime/logs` directory and the `app.log` basename, following the same shape as
the existing racecast-owned sources (`relay`, `streams`, `tailscale`). This makes
`app.log` and its dated archives selectable in the Control Center log viewer and
via the archive-listing path (`--list` / `--archive <date>`), for free, with no
front-end change. The file is listed only when it exists (an idle install with no
actions yet shows no empty source).

## Security

`app.log` contains exactly what the browser console view already shows — the
spawned child's stdout/stderr. No new secret is exposed: the `.env` editor and
other non-job UI surfaces are not jobs and write nothing here. Action argv is
logged, which for Control Center ops is the same `racecast <subcommand>` form the
console already surfaces (no secret arguments).

## Testing (TDD — failing test first)

- **`tests/test_ui_jobs.py`** — drive a `JobManager` with a fake `logger` and a
  fake `spawn` whose child emits known lines; assert the logger received: one start
  marker (with op + argv), one call per output line (prefixed `[op]`), and an end
  marker carrying the exit code (INFO on 0, WARNING on non-zero). Assert that with
  `logger=None` no logging occurs and existing behavior is unchanged (regression
  guard for the default path). No disk IO — the logger is a stub.
- **`tests/test_ui_server.py` / `tests/test_racecast.py`** — assert the
  `"app"` source is present in `_log_sources()` and resolves to
  `runtime/logs/app.log` (machine-wide, not under a profile).

## Files touched

- `src/ui/ui_jobs.py` — `JobManager` gains `logger` param + start/line/exit logging.
- `src/racecast.py` — `run_ui()` creates the `racecast.app` logger + prunes
  `runtime/logs`, passes it to `JobManager`; `_log_sources()` gains the `"app"`
  source.
- `tests/test_ui_jobs.py`, `tests/test_ui_server.py` (and/or `tests/test_racecast.py`)
  — coverage per above.
- No change to `src/scripts/logsetup.py` (reused as-is).
