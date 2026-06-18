# Logging improvements — design

Date: 2026-06-18
Status: approved (brainstorming) → ready for implementation plan

## Problem

The logs feature (CLI + Control Center) is thin and lossy:

- **No timestamps.** The relay (`src/relay/racecast-feeds.py`) and static streams
  (`src/scripts/loopstream.py`) emit via raw `print()`; `services.start_detached`
  appends the child's stdout/stderr to one file through a raw fd (`"ab"`).
  Operators cannot correlate a log line with wall-clock time.
- **Existing per-feed files are unsurfaced.** The relay already writes each feed to
  its own file — `feed_A.log` / `feed_B.log` / `feed_POV.log` under
  `runtime/<profile>/logs/` (`racecast-feeds.py:2101`) — and pipes the **streamlink
  subprocess stdout straight into that file via a raw fd** (`stdout=log`,
  `racecast-feeds.py:2194`), alongside `resolve_hls`/`ssai_warning` diagnostics. So
  the streamlink/yt-dlp errors operators most want live in `feed_*.log`, **which the
  Control Center never surfaces today** (its "relay" source shows only
  `relay.console.log`). These files also carry no timestamps and never rotate.
- **Missing information.** Operators specifically miss: (1) **start context**
  (which profile, bind address, ports, schedule source, race/qualifying mode),
  (2) **handover/stint events** (`/next`, `/reload`, Feed A/B swap, `set_stint`,
  mode switch), (3) **yt-dlp/streamlink errors** (today merged raw into the relay
  console, not delimited or classified), (4) **schedule/sheet problems** (sheet
  unreachable, empty/garbled rows, unresolved streamer names).
- **No rotation, archival, size cap, or cleanup anywhere.** Files grow unbounded;
  history beyond the live file is not browsable.
- **Limited surface.** The Control Center logs view offers exactly three live
  sources (relay/companion/streams) via SSE tail of the last 40 lines, with no
  file selection and no historical browsing. OBS and Tailscale are not surfaced
  at all.

## Goals

1. Timestamped, leveled log lines for relay + streams, carrying the four missing
   information classes above.
2. Daily (midnight) rotation with a date-suffixed archive, and a 7-day auto-cleanup.
3. Browse/select archived logs from both CLI and Control Center.
4. Surface additional logs: **OBS** (read-only tail of the platform log dir),
   **Companion** (extend today's newest-file read with archive selection), and a
   **Tailscale status snapshot** log (Tailscale has no tailable log file).
5. An **aggregated live log** ("All (live)") as the **default** Control Center
   view, merging **all** live sources — relay + all stream feeds + the external
   logs (OBS, Companion, Tailscale snapshot). In normal operation usually only the
   relay runs, so a relay+streams-only aggregate would add little over the relay
   view; including the external logs is what makes the aggregate worthwhile
   (accepting the noise and the non-uniform line formats).

## Non-goals

- No third-party logging framework or external `logrotate` (stdlib only,
  cross-platform incl. Windows — per repo hard rules).
- No timestamp re-formatting of external app logs (OBS/Companion lines keep their
  native format).
- No aggregation of *history* (archives are browsed per-source); no CLI aggregate
  command in this iteration (aggregate is UI-only).
- No timestamp normalization in the aggregate: external (OBS/Companion) lines are
  merged as-is, source-prefixed, in arrival order — not reformatted or re-sorted to
  our timestamp format.

## Chosen approach

**Daemon-owned rotating logging + a reusable stdlib helper module.** Each
long-lived daemon (relay, each `loopstream`) configures its own
`logging.TimedRotatingFileHandler`; child subprocess output is pumped through that
logger by a reader thread. A single pure prune function is the only deletion
authority. Rejected alternatives: rotate-on-start without `logging` (cannot cleanly
timestamp the daemon's own lines, no midnight split — weaker); external logrotate
(not cross-platform, violates stdlib/Windows rules).

## Architecture

### New module: `src/scripts/logsetup.py`

stdlib-only, **must not import `config.py`** (keeps the relay dependency-light, like
the other self-contained scripts). Contains the reusable, mostly-pure pieces:

- `configure_logging(log_path, level=logging.INFO) -> logging.Logger`
  - `TimedRotatingFileHandler(log_path, when="midnight", backupCount=0,
    encoding="utf-8")` → rolls at local midnight, archive named
    `relay.console.log.2026-06-18`. `backupCount=0` means the handler never deletes
    (prune is the sole deletion authority).
  - `Formatter("%(asctime)s %(levelname)s %(message)s")` with an explicit
    `datefmt` that includes the date.
  - Adds a `StreamHandler(sys.stdout)` **only when `sys.stdout.isatty()`** — so
    foreground `relay run` shows live logs in the terminal, while the daemon (whose
    stdout is redirected to a boot file, not a TTY) does not double-write.
- `prune_old_logs(log_dir, keep_days=7, now_ts=None) -> list[str]`
  - The **only** deletion path. Deletes files in `log_dir` older than `keep_days`
    **by mtime** (robust across all log types: rotated logs, per-port feed logs,
    `*.boot.log`, the Tailscale snapshot, any local OBS copies). `now_ts` is
    injectable for deterministic tests. Returns the list of removed paths.
- `classify_subproc_line(line) -> int`
  - Heuristic log level for a pumped subprocess line (e.g. `error`/`403`/
    `forbidden` → WARNING/ERROR, else INFO). Pure.
- External-log discovery (pure where possible):
  - `obs_log_dir(platform, home=None, env=None) -> str | None` — per-platform OBS
    log directory (macOS `~/Library/Application Support/obs-studio/logs`, Windows
    `%APPDATA%/obs-studio/logs`, Linux `~/.config/obs-studio/logs`). These are
    **current-machine** paths, so `os.path.join` is correct here (the cross-platform
    rule only forbids `os.path.join` on a *foreign*-OS fixed path).
  - `list_logs(dir) -> list[str]` (newest-first) and `newest_log(dir) -> str | None`
    — generic; Companion's existing newest-file logic is refactored onto these.
  - `resolve_archive(log_dir, basename, date) -> str | None` — maps a source +
    date to a concrete archive path **with a path-traversal guard** (only files
    inside `log_dir` whose name matches the source basename pattern; reject `..`,
    separators, absolute paths).

### Daemon changes

- **Relay (`src/relay/racecast-feeds.py`)**: replace `print()` with
  `log.info/warning/error` via `configure_logging`. Emit the four information
  classes:
  - **Start context** — one header line at startup: active profile, `--bind`
    result, feed ports, schedule source URL/tab, mode (race/qualifying).
  - **Handover/stint** — `/next`, `/reload`, Feed A/B advance, `set_stint`,
    `set_mode`: which feed now serves which streamer/stint.
  - **Schedule/sheet** — sheet unreachable, empty/short schedule, streamer names
    that did not resolve via `asset_key`.
  - **yt-dlp errors** — the short-lived `yt-dlp -g` resolve calls are captured;
    failures are logged explicitly at WARNING/ERROR (no pump needed for these).
- **Per-feed loggers + subprocess pump** — each relay feed (A/B/POV) already owns a
  `feed_<name>.log`; convert that file from a raw `stdout=log` fd redirect to its own
  `configure_logging` logger. The **long-lived streamlink server** is spawned with
  `stdout=PIPE, stderr=STDOUT`; a daemon reader thread reads line-by-line and logs
  each with a source tag (`[streamlink]`) at the level from `classify_subproc_line`.
  The `resolve_hls`/`ssai_warning` diagnostic writes (which today `open(self.logfile,
  "a")`) move onto the same feed logger. The thread is a daemon thread (never blocks
  shutdown); a pipe read error ends only the thread, never the relay.
- **Streams (`src/scripts/loopstream.py`)**: same pattern — its own rotating logger
  + a pump for its streamlink child. Each feed port owns an independent logger on
  its own `feed_<port>.log` (independent processes).
- **`src/scripts/services.py`**: `start_detached` redirects the child's raw
  stdout/stderr to a **separate small `*.boot.log`** (catches crashes/tracebacks
  *before* logging is configured) — never the same file the handler owns (two
  writers would corrupt rotation). `prune_old_logs` is invoked on each service
  start over the active profile's logs dir.

### Rotation, cleanup, configuration

- Daily rotation at local midnight (handler), correct even mid-event.
- `prune_old_logs` deletes every log type older than `keep_days` (default **7**),
  overridable via `.env` `RACECAST_LOG_RETENTION_DAYS`. Runs on each service start.

### CLI surface

- Existing `relay|streams|companion logs` gain:
  - `--list` — list available archives (date + size).
  - `--archive TOKEN` — read a specific archive (no follow; static). The token is a
    rotation date (`YYYY-MM-DD`) for racecast sources; for external apps
    (obs/companion) it is an older filename from `--list` (they do not follow our
    `name.YYYY-MM-DD` rotation naming).
  - `-f`/`--follow` unchanged (live file).
- New, consistent with the existing `obs`/`tailscale` command groups:
  - `racecast obs logs [-f|--list|--archive FILE]` — read-only tail of the
    platform OBS log dir's newest file (or a selected older one).
  - `racecast tailscale logs [--list|--archive YYYY-MM-DD]` — read the snapshot log.
- `racecast tailscale status` additionally appends a timestamped snapshot to
  `runtime/<profile>/logs/tailscale.snapshot.log`; a snapshot is also written on
  each service start.

### Control Center

- Source `<select id="logsel">` (`control-center.html:896`) gains **`obs`** and
  **`tailscale`**, plus a new **`aggregate`** option labeled "All (live)" set as
  the **default** selection (replaces today's "— select a log —" placeholder).
- A new **archive selector** (date dropdown) beside the source select. Default
  "live" = SSE tail (existing behavior). Selecting a date → static read (no SSE).
- New server routes in `src/ui/ui_server.py`:
  - `/api/logs/<name>/archives` — JSON list of archives for a source.
  - `/api/logs/<name>/file?token=…` — static archive content (token = date for
    racecast sources, filename for external; **path-traversal guarded** server-side).
  - `/api/logs/aggregate/stream` — SSE merge-tail (below).
- **Merged-source model.** A logical source maps to a **set** of live files, not
  one file (`racecast.py` builds the mapping in `ctx`):
  - `relay` → `relay.console.log` + `feed_A.log` + `feed_B.log` + `feed_POV.log`
  - `streams` → every `static/logs/feed_<port>.log`
  - `obs` / `companion` → the newest file in the app's log dir
  - `tailscale` → the snapshot log
  - `aggregate` ("All (live)") → the union of all of the above
  The **same merge-tail mechanism** serves single-file and multi-file sources (a
  one-file source is just a one-element set), so `relay`, `streams`, and `aggregate`
  share one code path. Each emitted line is source-prefixed (`[relay]`,
  `[feed_A]`, `[streams:53001]`, `[obs]`, …).
- `ctx` replaces the flat `log_paths` (`racecast.py:4541`) with a source registry:
  each source name → `{files: () -> list[path], dir, archives: () -> list[token],
  read: (token) -> text}` (token = rotation date for racecast sources, older
  filename for external apps). External/newest-log and snapshot resolvers are wired
  in here.

### Aggregated live log

- `/api/logs/aggregate/stream` tails **all** live files — the relay console, the
  relay per-feed logs (`feed_A/B/POV.log`), every static `feed_<port>.log`, the
  newest external log per app (OBS, Companion), and the Tailscale snapshot — each in
  its own daemon reader thread. Every line is prefixed with a source tag (`[relay]`,
  `[feed_A]`, `[streams:53001]`, `[obs]`, `[companion]`, `[tailscale]`) and pushed
  to a thread-safe queue that the SSE handler drains.
  **Arrival order** — racecast lines carry their own timestamp; external lines are
  passed through verbatim. Honest `tail -f file1 file2…`; no live re-sorting and no
  reformatting of external lines.
- Sources discovered/refreshed periodically: re-globbing the streams logs dir picks
  up feeds that start *after* the client connects, and the newest-file resolution
  for OBS/Companion is re-evaluated so a new app session's log is followed.
- Best-effort: an absent source (OBS not installed/running, no Companion log) is
  simply skipped and attached if/when it appears.
- Aggregate is **live-only**; archive history is browsed per-source.

## Error handling & edge cases

- Pump threads are daemon threads; a pipe error ends only the thread.
- External logs are read-only / best-effort: no OBS installed or no log → the same
  friendly empty message as Companion today.
- Frozen mode: the handler + threads run unchanged in the re-invoked daemon process
  (`racecast relay run`); log paths resolve under `runtime/<profile>/` next to the
  binary.
- Path traversal: archive reads only ever serve files inside the known log dir
  matching the source basename pattern.

## Testing

- New `tests/test_logs.py`: `prune_old_logs` (age boundary, mixed types, injected
  clock), `classify_subproc_line`, `obs_log_dir` per platform, `list_logs`/
  `newest_log` ordering, `resolve_archive` traversal-guard rejection, formatter
  output shape.
- `tests/test_ui_server.py`: new routes (`/archives`, `/file`, aggregate stream
  seam) + traversal reject.
- `tests/test_racecast.py`: CLI routing for `--list`/`--archive`, `obs logs`,
  `tailscale logs`.
- `tests/test_services.py`: boot-file redirect + prune-on-start.

## Docs & artifacts

- **Wiki screenshot**: the Logs view changes visibly → `src/docs/wiki/images/
  cc-logs.png` regenerated from a **local dev build** and committed in the same
  change (repo hard rule).
- Update CLAUDE.md (commands list + test list), README operator commands, and the
  wiki Logs page if present.

## Files touched (anticipated)

- New: `src/scripts/logsetup.py`, `tests/test_logs.py`.
- `src/scripts/services.py` — boot-file redirect, prune-on-start.
- `src/relay/racecast-feeds.py` — adopt logger, event logging, streamlink pump.
- `src/scripts/loopstream.py` (+ `start-streams.py` redirect) — logger + pump.
- `src/racecast.py` — obs/tailscale log resolvers, archive resolvers, ctx wiring,
  CLI subcommands (`--list`/`--archive`, `obs logs`, `tailscale logs`), tailscale
  snapshot append, `.env` retention knob.
- `src/ui/ui_server.py` — archive routes, static read, aggregate SSE, traversal guard.
- `src/ui/control-center.html` — source options (obs/tailscale/aggregate-default),
  archive date selector, static-read JS.
- `src/docs/wiki/images/cc-logs.png`, CLAUDE.md, README.
