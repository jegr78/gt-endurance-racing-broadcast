# Bandwidth speed test (opt-in) + preflight indicator

**Date:** 2026-06-14
**Status:** Approved — ready for implementation
**Issue:** #131 (UI & CLI: Bandwidth speed test option)
**Area:** new module (`src/scripts/speedtest.py`), preflight
(`src/scripts/preflight.py`), CLI (`src/racecast.py`), install-tools
(`src/scripts/install_tools.py`), Control Center (`src/ui/control-center.html`,
`src/ui/ui_ops.py`, `src/ui/ui_server.py`), `.env.example`, docs/wiki, tests,
wiki screenshot (`src/docs/wiki/images/cc-preflight.png`).

## Problem

A producer's internet line carries a lot of weight: OBS pushes one clean program
*out* to YouTube while the relay pulls up to three live feeds *in*. If the line
cannot sustain that, the broadcast degrades. Today `racecast preflight` only
shows a **static advisory** in its `Network` section ("use a wired connection
with upload headroom above your OBS bitrate") — there is no actual measurement,
so the producer cannot make a defensible statement about whether the current
hardware + bandwidth are sufficient.

Issue #131 asks for an option to **run a real download/upload speed test**, show
the results, and let preflight **check them against the documented
minimum/recommended thresholds** and present an indicator.

## Documented thresholds (already in the wiki)

`src/docs/wiki/Set-up-the-broadcast-PC.md` already defines the numbers this
feature thresholds against:

| | Minimum | Recommended |
|---|---|---|
| **Download** | 25 Mbps | 50 Mbps |
| **Upload** | 10 Mbps | 20 Mbps |

These are the single source of truth; the feature hard-codes them as constants
that mirror that table (see "Out of scope" for why they are not configurable).

## Decisions (confirmed with the producer)

1. **Measurement tool: Ookla Speedtest CLI** (`speedtest`). Chosen over a
   stdlib/Cloudflare approach and over LibreSpeed because the goal is a
   *defensible, externally comparable* number, and Ookla has the largest server
   network and fits the existing winget/brew/apt install flow. Accepted
   trade-offs, documented honestly: closed source, one-time EULA/GDPR
   acceptance, and **every run sends its result to Ookla** (same data egress as
   running speedtest.net in a browser).
2. **Opt-in only.** The speed test is **never** part of the automatic
   `racecast preflight` run (which is fast, run often, and exercised in CI). It
   is its own action in **both** the CLI and the Control Center. Preflight only
   *reads* the last stored result.
3. **Results are logged locally.** Each run appends a record to a machine-level
   history; preflight reads the latest and warns when the minimum thresholds are
   not met.
4. **Below-minimum = WARN, never FAIL.** Below `min` → a prominent WARN; between
   `min` and `recommended` → a mild WARN; at/above `recommended` → PASS. It never
   hard-blocks readiness (no FAIL, no exit-1), to avoid a measurement outlier
   marking the whole machine "NOT READY". The worse of the download/upload sides
   governs the level.
5. **Staleness = WARN, window configurable.** A result older than
   `RACECAST_SPEEDTEST_MAX_AGE_DAYS` (default **7**) → WARN ("stale — re-measure
   before the event"), regardless of the measured value. The age is always shown.
6. **History pruning: keep the last 10 runs** (ring buffer by count, constant
   `HISTORY_LIMIT = 10`). Preflight needs only the latest; the history exists so
   the producer can see whether the line varies across recent checks.

## Architecture

### 1. New module `src/scripts/speedtest.py` — pure logic + thin runner

Mirrors the style of `preflight.py` / `config.py`: pure, unit-testable helpers
with the one I/O boundary (the subprocess call, the file read/write) injectable.

**Constants**

```
SPEEDTEST_BIN   = "speedtest"
MIN_DOWN_MBPS   = 25.0   # mirrors Set-up-the-broadcast-PC.md
MIN_UP_MBPS     = 10.0
REC_DOWN_MBPS   = 50.0
REC_UP_MBPS     = 20.0
DEFAULT_MAX_AGE_DAYS = 7
HISTORY_LIMIT   = 10
```

**argv builder**

```
run_argv() -> ["speedtest", "--format=json", "--accept-license", "--accept-gdpr"]
```

`--accept-license --accept-gdpr` are passed on **every** invocation so the
first-run interactive license prompt never blocks us.

**Parsing** — `parse_result(json_text, now=...) -> dict`

Ookla `--format=json` returns (relevant fields):

```
{ "ping":     {"latency": <ms>, "jitter": <ms>},
  "download": {"bandwidth": <bytes/sec>, ...},
  "upload":   {"bandwidth": <bytes/sec>, ...},
  "packetLoss": <percent | absent>,
  "server":   {"name": "...", "location": "...", "id": <int>},
  "isp":      "...",
  "result":   {"url": "https://www.speedtest.net/result/c/..."} }
```

`bandwidth` is **bytes per second** → Mbps = `bandwidth * 8 / 1_000_000`. The
record we persist:

```
{ "ts": <unix seconds>,            # stamped by the caller (now), not by the tool
  "download_mbps": <float>,
  "upload_mbps":   <float>,
  "ping_ms":       <float | null>,
  "jitter_ms":     <float | null>,
  "packet_loss":   <float | null>, # percent; null when the tool omits it
  "server":        <str>,          # "name — location"
  "isp":           <str>,
  "result_url":    <str | null> }
```

`packetLoss` and `result.url` are tolerated as absent (older CLI / no result
submission) → `null`. Malformed/empty JSON raises a `ValueError` the runner turns
into a friendly message.

**Classification** — `classify(record, now, max_age_days=...) -> preflight.Result`

Returns a `preflight.Result` (reuse the existing `Result`/level constants —
`speedtest.py` imports them from `preflight.py`; preflight does **not** import
speedtest at module top to avoid a cycle, see §4):

- `record is None` → `INFO "bandwidth — not measured yet; run `racecast speedtest`"`.
- age `> max_age_days` → `WARN "... measured Nd ago — stale, re-measure before the event"`.
- else level = **worse of** the download and upload sides:
  - either side `< min` → `WARN` ("below the 25/10 Mbps minimum").
  - either side `< recommended` (but ≥ min) → `WARN` (mild; "meets minimum, below the 50/20 recommended").
  - both sides `≥ recommended` → `PASS`.
- The detail string always shows `↓X.X ↑Y.Y Mbps · measured <age> · <server> / <isp>`.

`classify` is pure (takes `now`), so every branch is unit-tested without a clock.

**History store** (machine-level, not per-profile — bandwidth is a property of
the machine/line, identical across leagues):

- `history_path(state_dir=...) -> runtime/speedtest-history.jsonl`
  (top-level `runtime/`, alongside the cookies jar and `active-profile`, via the
  same `state_dir()` helper the other scripts use).
- `append_record(record, path=...)`: read existing lines, append, **trim to the
  last `HISTORY_LIMIT`**, rewrite. One JSON object per line (JSONL). Tolerates a
  missing/empty/partly-corrupt file (skips unparseable lines).
- `load_latest(path=...) -> dict | None`: the last valid record.
- `load_history(path=..., limit=HISTORY_LIMIT) -> list[dict]`: newest-first, for
  the UI table.

**Runner** — `run(now, runner=subprocess.run, which=shutil.which, state_dir=...) -> dict`

1. If `which(SPEEDTEST_BIN)` is `None` → raise a typed error whose message points
   at `racecast install-tools`.
2. Invoke `run_argv()`, capture stdout. Non-zero exit / empty output → friendly
   error (e.g. "no internet connection?").
3. `parse_result(stdout, now)`, `append_record(...)`, return the record.

### 2. CLI: `racecast speedtest`

Add a `speedtest` subcommand to `src/racecast.py` (alongside `preflight`,
`status`). It runs **in the foreground** (the test takes ~20–30 s):

- Calls `speedtest.run(now=time.time())`, then prints a human summary:
  ```
  Bandwidth speed test (Ookla)
    Download  48.3 Mbps   (min 25 / rec 50)
    Upload    22.1 Mbps   (min 10 / rec 20)
    Ping      11 ms · jitter 2 ms · loss 0%
    Server    Deutsche Telekom — Berlin   ISP: …
    Result    https://www.speedtest.net/result/c/…
    => OK (meets the recommended 50/20)         # PASS/WARN line from classify()
  ```
- `--json` prints the persisted record as JSON instead (for automation), still
  appending to history.
- Binary missing → one-line message "Ookla speedtest CLI not found — run
  `racecast install-tools` (or install it manually)." and a non-zero exit.

Frozen-binary note: the subcommand runs the bundled `speedtest.py` in-process
like the other one-shot wrappers (no daemon, no child `racecast` re-invocation).

### 3. `install-tools` learns Ookla

`speedtest` is provisioned by `racecast install-tools`, but kept **out of the
readiness `TOOLS` tuple** so its absence never turns the preflight *tool chain*
into a FAIL (it is an optional, opt-in capability). Per OS:

- **Windows:** winget `Ookla.Speedtest.CLI` (clean, automated).
- **macOS:** `brew tap teamookla/speedtest` then `brew install speedtest` (the
  Ookla CLI is a tapped formula, not core — the tap step is new vs. the existing
  plain `brew install` tools).
- **Linux:** Ookla needs its own apt repo (not a stock package) → **manual guide
  pointer** in `manual_guide()`, mirroring how `deno` is handled today.

Implementation shape: introduce a small `EXTRA_TOOLS`/speedtest-specific branch
rather than overloading the uniform `WINGET_IDS`/`APT_PACKAGES` dicts (those
assume one package-manager id per tool; Ookla's mac tap + Linux repo break that
uniformity). `--update` upgrades it where the manager supports it (winget
upgrade, brew upgrade). The existing `installer_common.install_exit_ok`
whitelist (winget "no applicable update") is reused.

### 4. Preflight integration (`src/scripts/preflight.py`)

The `Network` section's static advisory is **augmented** (not removed):

- `gather()` calls `speedtest.load_latest()` + `speedtest.classify(record, now,
  max_age_days=<env>)` and puts that `Result` first in the `network` list.
- The existing wired-connection advisory stays as a trailing `INFO` sub-note.
- If the `speedtest` binary is absent **and** there is no stored record, the
  line reads `INFO "bandwidth — speed-test CLI not installed; run
  `racecast install-tools`, then `racecast speedtest`"`.

To avoid an import cycle (`preflight` ← `speedtest` which imports `Result` from
`preflight`), `preflight.gather()` imports `speedtest` **lazily inside the
function**, and `speedtest.py` imports the `Result`/level names from
`preflight` at module top. `gather()` already takes injectable seams; the
speedtest read is wrapped best-effort (any failure → the plain advisory INFO, so
preflight never crashes because of this feature).

`RACECAST_SPEEDTEST_MAX_AGE_DAYS` is read in `gather()` (default 7, bad/blank →
default).

### 5. Control Center — Preflight view

The Control Center surfaces this in the **Preflight view** (not Help & Docs:
the result feeds preflight, so it belongs next to it).

- **HTML (`control-center.html`):** a new "Speed test" card in the
  `data-view="preflight"` block, above or beside the existing checklist:
  - a **"Run speed test"** button → `op('speedtest', …)` (streams the Ookla
    output into the docked console job, like other ops),
  - the **latest result** (download/upload + PASS/WARN pill + age + server/ISP),
  - a compact **recent-history table** (up to 10 rows: time, ↓, ↑, ping),
  - a one-line note about Ookla (closed source; each run is sent to Ookla).
- **`ui_ops.py`:** register `"speedtest": ["speedtest"]` in `OPS`.
- **`ui_server.py`:** add `GET /api/speedtest` → `{latest, history}` from
  `speedtest.load_latest()` / `load_history()` (read-only; the *run* goes through
  the existing op/jobs child-process path, so the server stays non-blocking).
- The preflight checklist's `Network` line reflects the stored result the next
  time **Run** (preflight) is pressed.
- **Screenshot:** regenerate **`src/docs/wiki/images/cc-preflight.png`** in the
  same change (CLAUDE.md hard rule) by driving a running instance with the
  Playwright MCP and taking an element screenshot of the Preflight view.

### 6. Config & docs

- **`.env.example`:** add `RACECAST_SPEEDTEST_MAX_AGE_DAYS=7` with a short
  comment. Machine-level (it is a per-machine policy knob, like the other
  `RACECAST_*` vars).
- **`src/docs/wiki/Set-up-the-broadcast-PC.md`:** in the bandwidth section,
  document `racecast speedtest` + the Control Center button, how preflight uses
  the stored result (WARN below 25/10, WARN when stale), and the honest Ookla
  note (closed source; each run's result is sent to Ookla — equivalent to a
  browser speedtest.net run). Note the test measures the line **idle** — it is a
  *capability* check; the true under-load picture is OBS's live stats during a
  broadcast.
- **`CLAUDE.md`** command list + **`README.md`:** add the `racecast speedtest`
  line and a one-line `install-tools` mention of Ookla.

### 7. Tests (`tests/test_speedtest.py` + additions) — stdlib only, no real network

- `parse_result`: a captured Ookla `--format=json` fixture → expected record;
  bytes/sec→Mbps math; tolerated-absent `packetLoss`/`result.url`; malformed
  JSON → `ValueError`.
- `classify`: every branch with a pinned `now` — `None` record (INFO), stale
  (WARN), below-min (WARN), between min/rec (WARN), at/above rec (PASS), and the
  "worse side governs" cases (good down / bad up and vice-versa).
- History: `append_record` trims to `HISTORY_LIMIT`; round-trips
  `load_latest`/`load_history`; tolerates missing/empty/corrupt lines.
- `run_argv` exact tokens (the `--accept-*` flags must be present — a regression
  guard, since dropping them reintroduces the blocking prompt).
- `run`: binary-missing path (injected `which` → None) raises the typed error;
  happy path with an injected `runner` returning fixture stdout appends one
  record.
- install-tools: the speedtest command builders per manager (winget id, brew
  tap+install, Linux manual-guide pointer) — added to `tests/test_install_tools.py`.
- UI: `GET /api/speedtest` shape in `tests/test_ui_server.py`; `"speedtest"` op
  routing in `tests/test_racecast.py`.
- Run the **whole** suite (`python3 tools/run-tests.py`) + `python3 tools/lint.py`
  — cross-file enumerations (the OPS map, preflight sections) break silently
  otherwise.

## Out of scope (YAGNI)

- **Configurable thresholds.** The 25/10/50/20 values stay hard-coded constants
  mirroring the wiki table; the producer chose "below-min = WARN", not the
  configurable-thresholds variant. Only the *staleness window* is configurable.
- **Latency/jitter/packet-loss thresholds.** The docs give no numbers; inventing
  pass/fail bands would be inventing an ops rule. These are stored and displayed
  for information only.
- **Age-based history pruning.** Count-based (last 10) only; the staleness WARN
  already covers "too old to trust".
- **A second/fallback tool (LibreSpeed).** One tool (Ookla); revisit only if it
  proves unavailable in practice.
- **Wiring the speed test into `racecast event status`** — preflight is its home.
