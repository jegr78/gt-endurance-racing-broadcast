# Health Monitor Extensions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Health Monitor with richer OBS statistics, relay feed stream quality, and connectivity checks (Funnel/Tailscale/Companion/Sheet-push), with broadcast-critical signals driving the existing rollup + Discord alerts and everything else observational.

**Architecture:** Approach A — extend the existing pipeline. One wide `samples` table gains 17 columns (schema v3, lossless `ALTER TABLE ADD COLUMN`); the 30 s relay heartbeat gains an OBS-stats call (`GetStats` + `GetStreamStatus` in one `obs_ws` session) plus connectivity probes (reusing the tested `tailscale.funnel_on`/`tailscale_backend` helpers and a new TCP reachability check); `aggregate_health` gains gated critical signals; the relay-served page gains grouped bands/charts and per-feed quality badges. Export/import and producer-handover carry the new columns for free.

**Tech Stack:** Pure Python stdlib (`sqlite3`, `socket`, `subprocess`), the existing `src/scripts/obs_ws.py` v5 client, `src/scripts/tailscale.py`, uPlot (already vendored), no new runtime dependencies.

## Global Constraints

- **Pure Python stdlib only** — no new runtime dependencies. OBS data via `src/scripts/obs_ws.py`; Tailscale/Funnel via the existing `tailscale` CLI helpers; Companion via a stdlib TCP connect.
- **Redaction by construction** — every new field is a boolean, number, or short quality label. NO stream URLs, NO `sheet_id`, NO Funnel hostname is ever stored or returned. `_health_snapshot` stays an explicit allowlist. `/console/takeover/status` (live/league/event_title/timer/mode) is UNCHANGED.
- **Best-effort sampling** — every new sampler block is wrapped in its own `try/except`; a failure sets only its fields to `None` and the heartbeat continues. The `obs_ws` helpers and the `tailscale` helpers never raise.
- **Tests run on any machine and in CI (incl. windows-latest)** — no real IPs (Tailscale IPs are `100.64.0.0/10` test constants), no machine paths, close every SQLite connection (`try/finally`), localhost-only sockets in tests.
- **English-only** code and docs. Edit only under `src/` (+ `tests/`, `docs/`). Run `python3 tools/lint.py` after any Python change.
- **Exact new field names (17):** bands — `stream_active`, `stream_reconnecting`, `funnel_ok`, `sheet_push_ok`, `tailscale_up`, `companion_ok`; numeric — `stream_kbps`, `stream_dropped_pct`, `stream_congestion`, `obs_cpu_pct`, `obs_mem_mb`, `obs_fps`, `obs_render_skipped_pct`, `obs_disk_free_mb`; text — `feed_a_quality`, `feed_b_quality`, `pov_quality`.
- **`SCHEMA_VERSION` = 3.**
- **Severity (confirmed):** `stream_active=false` (OBS reachable) → **red**, NO live-gate (red even pre-show); `stream_reconnecting`, Funnel-down (expected-on), Sheet-push-failing → **yellow**. Observational signals (`tailscale_up`, `companion_ok`, all numerics) NEVER touch the rollup.

---

### Task 1: Schema v3 — migration + constants (`health_store.py`)

**Files:**
- Modify: `src/scripts/health_store.py`
- Test: `tests/test_health_store.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `SCHEMA_VERSION == 3`; `COLUMNS`, `BAND_FIELDS`, `NUMERIC_FIELDS`, `STATE_KEY_FIELDS` extended with the 17 new fields; `migrate(conn)` performs a lossless v2→v3 `ALTER TABLE ADD COLUMN` upgrade and is idempotent.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_health_store.py` (follow the file's existing `t_*` + runner pattern; **close every connection**):

```python
def t_migrate_v2_to_v3_is_lossless():
    import tempfile, os, sqlite3
    d = tempfile.mkdtemp()
    path = os.path.join(d, "h.db")
    # Build a v2 table by hand (old column set + user_version=2), insert one row.
    c = sqlite3.connect(path)
    try:
        c.executescript(
            "CREATE TABLE samples (ts REAL NOT NULL, kind TEXT NOT NULL, "
            "health_level TEXT, health_reasons TEXT, feed_a_state TEXT, "
            "feed_a_down INTEGER, feed_a_stint INTEGER, feed_b_state TEXT, "
            "feed_b_down INTEGER, feed_b_stint INTEGER, pov_state TEXT, "
            "obs_reachable INTEGER, source_last_ok_age_s REAL, source_count INTEGER, "
            "cookies_present INTEGER, cookies_age_h REAL, cookies_stale INTEGER, "
            "timer_mode TEXT, timer_push TEXT, mode TEXT, live_feed TEXT, "
            "live_stint INTEGER);")
        c.execute("PRAGMA user_version=2")
        c.execute("INSERT INTO samples (ts, kind, health_level) VALUES (?,?,?)",
                  (1000.0, "tick", "green"))
        c.commit()
    finally:
        c.close()
    # Migrate via the real loader and assert the upgrade is lossless.
    conn = hs.open_db(path)
    try:
        hs.migrate(conn)
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        assert ver == 3, ver
        cols = {r[1] for r in conn.execute("PRAGMA table_info(samples)").fetchall()}
        for f in ("stream_active", "funnel_ok", "stream_kbps", "obs_cpu_pct",
                  "feed_a_quality", "pov_quality"):
            assert f in cols, f
        rows = conn.execute("SELECT ts, health_level, stream_active FROM samples").fetchall()
        assert rows[0][0] == 1000.0 and rows[0][1] == "green" and rows[0][2] is None
    finally:
        conn.close()


def t_new_fields_round_trip():
    import tempfile, os
    d = tempfile.mkdtemp()
    conn = hs.open_db(os.path.join(d, "h.db"))
    try:
        hs.migrate(conn)
        snap = {"ts": 5.0, "health_level": "green", "stream_active": 1,
                "stream_reconnecting": 0, "funnel_ok": 1, "sheet_push_ok": 0,
                "tailscale_up": 1, "companion_ok": 0, "stream_kbps": 6200.0,
                "stream_dropped_pct": 0.5, "stream_congestion": 0.1,
                "obs_cpu_pct": 12.3, "obs_mem_mb": 900.0, "obs_fps": 60.0,
                "obs_render_skipped_pct": 0.0, "obs_disk_free_mb": 50000.0,
                "feed_a_quality": "720p", "feed_b_quality": "1080p",
                "pov_quality": "source"}
        hs.record(conn, snap, "tick")
        got = hs.query_range(conn, 0, 10)[0]
        assert got["stream_active"] == 1 and got["feed_a_quality"] == "720p"
        assert got["stream_kbps"] == 6200.0 and got["sheet_push_ok"] == 0
        bands = hs.derive_bands([got])
        assert "funnel_ok" in bands and "companion_ok" in bands
        series = hs.numeric_series([got])
        assert "stream_kbps" in series and "obs_cpu_pct" in series
    finally:
        conn.close()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_health_store as t; t.t_migrate_v2_to_v3_is_lossless()"`
Expected: FAIL (`user_version == 2`, new columns absent).

- [ ] **Step 3: Implement the schema changes**

In `src/scripts/health_store.py`:

Bump the version:
```python
SCHEMA_VERSION = 3
```

Extend the four constants (append, preserving existing order):
```python
COLUMNS = (
    "ts", "kind",
    "health_level", "health_reasons",
    "feed_a_state", "feed_a_down", "feed_a_stint",
    "feed_b_state", "feed_b_down", "feed_b_stint",
    "pov_state", "obs_reachable",
    "source_last_ok_age_s", "source_count",
    "cookies_present", "cookies_age_h", "cookies_stale",
    "timer_mode", "timer_push",
    "mode", "live_feed", "live_stint",
    # v3: OBS stats + connectivity + feed quality (redaction-safe: no URLs)
    "stream_active", "stream_reconnecting", "funnel_ok", "sheet_push_ok",
    "tailscale_up", "companion_ok",
    "stream_kbps", "stream_dropped_pct", "stream_congestion",
    "obs_cpu_pct", "obs_mem_mb", "obs_fps", "obs_render_skipped_pct",
    "obs_disk_free_mb",
    "feed_a_quality", "feed_b_quality", "pov_quality",
)

BAND_FIELDS = ("health_level", "feed_a_state", "feed_b_state",
               "pov_state", "obs_reachable", "cookies_stale", "timer_push",
               "stream_active", "stream_reconnecting", "funnel_ok",
               "sheet_push_ok", "tailscale_up", "companion_ok")
NUMERIC_FIELDS = ("source_last_ok_age_s", "cookies_age_h",
                  "stream_kbps", "stream_dropped_pct", "stream_congestion",
                  "obs_cpu_pct", "obs_mem_mb", "obs_fps",
                  "obs_render_skipped_pct", "obs_disk_free_mb")
STATE_KEY_FIELDS = ("health_level", "feed_a_state", "feed_a_down",
                    "feed_b_state", "feed_b_down", "pov_state", "obs_reachable",
                    "timer_push",
                    "stream_active", "stream_reconnecting", "funnel_ok",
                    "sheet_push_ok", "tailscale_up", "companion_ok")
```

Add the v3 column declarations BOTH to `_CREATE` (for fresh DBs) and as a migration list. Extend the `_CREATE` table body — add these lines before the closing `);`:
```python
    timer_mode TEXT, timer_push TEXT,
    mode TEXT, live_feed TEXT, live_stint INTEGER,
    stream_active INTEGER, stream_reconnecting INTEGER,
    funnel_ok INTEGER, sheet_push_ok INTEGER,
    tailscale_up INTEGER, companion_ok INTEGER,
    stream_kbps REAL, stream_dropped_pct REAL, stream_congestion REAL,
    obs_cpu_pct REAL, obs_mem_mb REAL, obs_fps REAL,
    obs_render_skipped_pct REAL, obs_disk_free_mb REAL,
    feed_a_quality TEXT, feed_b_quality TEXT, pov_quality TEXT
);
```
(Replace the existing `live_stint INTEGER\n);` tail with the block above — note the comma after `live_stint INTEGER`.)

Add the migration column list and rewrite `migrate()` directly below the `_CREATE` string:
```python
# v3 columns, added via ALTER TABLE to pre-v3 DBs (fresh DBs get them from _CREATE).
_V3_COLUMNS = (
    ("stream_active", "INTEGER"), ("stream_reconnecting", "INTEGER"),
    ("funnel_ok", "INTEGER"), ("sheet_push_ok", "INTEGER"),
    ("tailscale_up", "INTEGER"), ("companion_ok", "INTEGER"),
    ("stream_kbps", "REAL"), ("stream_dropped_pct", "REAL"),
    ("stream_congestion", "REAL"), ("obs_cpu_pct", "REAL"),
    ("obs_mem_mb", "REAL"), ("obs_fps", "REAL"),
    ("obs_render_skipped_pct", "REAL"), ("obs_disk_free_mb", "REAL"),
    ("feed_a_quality", "TEXT"), ("feed_b_quality", "TEXT"),
    ("pov_quality", "TEXT"),
)


def migrate(conn):
    """Create the schema, add any missing v3 columns (lossless upgrade from v2),
    and stamp user_version. Idempotent and version-agnostic."""
    conn.executescript(_CREATE)
    have = {r["name"] for r in conn.execute("PRAGMA table_info(samples)").fetchall()}
    for name, decl in _V3_COLUMNS:
        if name not in have:
            conn.execute(f"ALTER TABLE samples ADD COLUMN {name} {decl}")
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    conn.commit()
```

- [ ] **Step 4: Run both new tests + the whole file**

Run: `python3 tests/test_health_store.py`
Expected: PASS (all, including the two new functions — add them to the file's runner list).

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/health_store.py tests/test_health_store.py
git commit -m "feat(health): schema v3 — OBS stats, connectivity, feed-quality columns"
```

---

### Task 2: OBS stats parsers + `get_health_stats()` (`obs_ws.py`)

**Files:**
- Modify: `src/scripts/obs_ws.py`
- Test: `tests/test_obsws.py`

**Interfaces:**
- Consumes: the existing `_connect(host, port, password, timeout)` and `_Session.request`.
- Produces:
  - `parse_obs_stats(payload: dict) -> dict` with keys `obs_cpu_pct, obs_mem_mb, obs_fps, obs_render_skipped_pct, obs_disk_free_mb` (each `None` if its source field is absent).
  - `parse_stream_status(payload: dict) -> dict` with keys `stream_active (bool|None), stream_reconnecting (bool|None), stream_congestion (float|None), stream_dropped_pct (float|None), output_bytes (int|None)`.
  - `get_health_stats(host="127.0.0.1", port=None, password=None, timeout=2.0) -> (reachable: bool, stats: dict, note: str)` — opens ONE session, calls `GetStats` + `GetStreamStatus`, merges the two parsed dicts; best-effort (never raises).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_obsws.py`:

```python
def t_parse_obs_stats():
    p = {"cpuUsage": 12.5, "memoryUsage": 910.0, "availableDiskSpace": 51200.0,
         "activeFps": 60.0, "renderSkippedFrames": 3, "renderTotalFrames": 1000}
    out = obs_ws.parse_obs_stats(p)
    assert out["obs_cpu_pct"] == 12.5
    assert out["obs_mem_mb"] == 910.0
    assert out["obs_disk_free_mb"] == 51200.0
    assert out["obs_fps"] == 60.0
    assert out["obs_render_skipped_pct"] == 0.3
    # Missing fields -> None, never KeyError; zero total -> None (no div by zero).
    out2 = obs_ws.parse_obs_stats({"renderSkippedFrames": 0, "renderTotalFrames": 0})
    assert out2["obs_cpu_pct"] is None and out2["obs_render_skipped_pct"] is None


def t_parse_stream_status():
    p = {"outputActive": True, "outputReconnecting": False, "outputCongestion": 0.2,
         "outputSkippedFrames": 5, "outputTotalFrames": 500, "outputBytes": 1234567}
    out = obs_ws.parse_stream_status(p)
    assert out["stream_active"] is True
    assert out["stream_reconnecting"] is False
    assert out["stream_congestion"] == 0.2
    assert out["stream_dropped_pct"] == 1.0
    assert out["output_bytes"] == 1234567
    out2 = obs_ws.parse_stream_status({})
    assert out2["stream_active"] is None and out2["stream_dropped_pct"] is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_obsws as t; t.t_parse_obs_stats()"`
Expected: FAIL (`parse_obs_stats` not defined).

- [ ] **Step 3: Implement the parsers + the session call**

Add near the other module-level helpers in `src/scripts/obs_ws.py` (e.g. just above `probe`):

```python
def _pct(part, total):
    """skipped/total as a rounded percentage, or None when either is missing or
    total is zero (avoid a div-by-zero and a meaningless 0/0)."""
    if part is None or not total:
        return None
    return round(part / total * 100.0, 2)


def parse_obs_stats(payload):
    """Flatten a GetStats response into the health field names. Missing keys -> None."""
    p = payload or {}
    return {
        "obs_cpu_pct": p.get("cpuUsage"),
        "obs_mem_mb": p.get("memoryUsage"),
        "obs_disk_free_mb": p.get("availableDiskSpace"),
        "obs_fps": p.get("activeFps"),
        "obs_render_skipped_pct": _pct(p.get("renderSkippedFrames"),
                                       p.get("renderTotalFrames")),
    }


def parse_stream_status(payload):
    """Flatten a GetStreamStatus response. outputBytes is returned raw (the caller
    derives kbps from successive samples); missing keys -> None."""
    p = payload or {}
    active = p.get("outputActive")
    recon = p.get("outputReconnecting")
    return {
        "stream_active": None if active is None else bool(active),
        "stream_reconnecting": None if recon is None else bool(recon),
        "stream_congestion": p.get("outputCongestion"),
        "stream_dropped_pct": _pct(p.get("outputSkippedFrames"),
                                   p.get("outputTotalFrames")),
        "output_bytes": p.get("outputBytes"),
    }
```

Add the session entry point, mirroring `probe()`'s best-effort contract:
```python
def get_health_stats(host="127.0.0.1", port=None, password=None, timeout=2.0):
    """One obs-websocket session -> (reachable, stats, note). `stats` is the merged
    parse_obs_stats + parse_stream_status dict (empty {} when the requests fail but
    the session opened). Best-effort: never raises (same contract as probe())."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, {}, note
    try:
        stats = parse_obs_stats(session.request("GetStats", {}))
        stats.update(parse_stream_status(session.request("GetStreamStatus", {})))
        return True, stats, ""
    except Exception as exc:                         # noqa: BLE001 — best-effort contract
        return True, {}, str(exc) or exc.__class__.__name__
    finally:
        session.close()
```

- [ ] **Step 4: Run the file**

Run: `python3 tests/test_obsws.py`
Expected: PASS (add the two new functions to the runner list).

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): parse GetStats/GetStreamStatus + get_health_stats helper"
```

---

### Task 3: `stream_kbps` pure derivation (`obs_ws.py`)

**Files:**
- Modify: `src/scripts/obs_ws.py`
- Test: `tests/test_obsws.py`

**Interfaces:**
- Produces: `stream_kbps(prev_bytes, prev_ts, bytes_, ts, active) -> float|None`. kbps from the byte delta over the time delta; `None` (reset) when not active, on first sample, on a non-positive `dt`, or on a byte-counter regression (stream stop/restart).

- [ ] **Step 1: Write the failing test**

```python
def t_stream_kbps():
    # 125000 bytes over 1 s = 1000 kbps.
    assert obs_ws.stream_kbps(0, 100.0, 125000, 101.0, True) == 1000.0
    assert obs_ws.stream_kbps(None, None, 125000, 101.0, True) is None   # first sample
    assert obs_ws.stream_kbps(0, 100.0, 125000, 101.0, False) is None    # not streaming
    assert obs_ws.stream_kbps(200000, 100.0, 1000, 101.0, True) is None  # counter reset
    assert obs_ws.stream_kbps(0, 101.0, 125000, 101.0, True) is None     # dt == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_obsws as t; t.t_stream_kbps()"`
Expected: FAIL (`stream_kbps` not defined).

- [ ] **Step 3: Implement**

```python
def stream_kbps(prev_bytes, prev_ts, bytes_, ts, active):
    """Upstream kbps from successive outputBytes samples. None resets the line on
    stream stop/restart so no ghost spike appears."""
    if not active or bytes_ is None or prev_bytes is None or prev_ts is None:
        return None
    dt = ts - prev_ts
    if dt <= 0 or bytes_ < prev_bytes:
        return None
    return round((bytes_ - prev_bytes) * 8 / 1000.0 / dt, 1)
```

- [ ] **Step 4: Run + commit**

Run: `python3 tests/test_obsws.py` → PASS.
```bash
python3 tools/lint.py
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): stream_kbps derivation from successive outputBytes"
```

---

### Task 4: Critical-signal gates in `aggregate_health` (`racecast-feeds.py`)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (the `aggregate_health` function, ~line 184)
- Test: `tests/test_pov.py`

**Interfaces:**
- Consumes: extra `facts` keys (all optional, default absent) — `stream_active (bool|None)`, `stream_reconnecting (bool|None)`, `funnel_down (bool)`, `sheet_push_failing (bool)`. `obs_reachable` already exists.
- Produces: unchanged return shape `{"level", "reasons"}`. New behavior: `stream_active is False` while `obs_reachable` is truthy → red; `stream_reconnecting`, `funnel_down`, `sheet_push_failing` → yellow. Absent facts ⇒ identical to today.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pov.py`:

```python
def t_aggregate_stream_not_active_is_red():
    h = aggregate_health({"obs_reachable": True, "stream_active": False})
    assert h["level"] == "red"
    assert any("not streaming" in r.lower() or "off air" in r.lower() for r in h["reasons"])


def t_aggregate_stream_active_unknown_is_green():
    # OBS reachable but stream_active not sampled (None) -> no alarm.
    assert aggregate_health({"obs_reachable": True})["level"] == "green"
    assert aggregate_health({"obs_reachable": True, "stream_active": None})["level"] == "green"
    # OBS not reachable -> existing yellow path, stream_active ignored.
    assert aggregate_health({"obs_reachable": False, "stream_active": False})["level"] == "yellow"


def t_aggregate_yellow_signals():
    for key in ("stream_reconnecting", "funnel_down", "sheet_push_failing"):
        h = aggregate_health({"obs_reachable": True, "stream_active": True, key: True})
        assert h["level"] == "yellow", (key, h)
    # observational signals never escalate
    assert aggregate_health({"obs_reachable": True, "stream_active": True,
                             "tailscale_up": False, "companion_ok": False})["level"] == "green"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_aggregate_stream_not_active_is_red()"`
Expected: FAIL (level == "green").

- [ ] **Step 3: Implement**

Replace the body of `aggregate_health` (keep the docstring, extend it) with:
```python
    reasons, red, yellow = [], [], []
    for name in facts.get("feeds_down") or []:
        red.append(f"Feed {name} down — lost the live stream")
    # OBS reachable but not streaming = off air (no live-gate: red even pre-show).
    if facts.get("obs_reachable") and facts.get("stream_active") is False:
        red.append("OBS is not streaming — broadcast is off air")
    if facts.get("obs_reachable") is False:
        yellow.append("OBS WebSocket unreachable — no auto-cut")
    if facts.get("obs_reachable") and facts.get("stream_reconnecting"):
        yellow.append("OBS stream reconnecting — upstream unstable")
    if facts.get("funnel_down"):
        yellow.append("Funnel down — talent cannot reach the cockpit")
    if facts.get("sheet_push_failing"):
        yellow.append("Sheet webhook failing — panel writes are not saved")
    if facts.get("cookies_stale"):
        yellow.append("YouTube cookies stale — handovers may fail")
    if not facts.get("tailscale_present", True):
        yellow.append("Tailscale not connected — directors cannot reach the panel")
    for name in facts.get("feeds_connecting_long") or []:
        yellow.append(f"Feed {name} stuck connecting")
    reasons.extend(red)
    reasons.extend(yellow)
    level = "red" if red else ("yellow" if yellow else "green")
    return {"level": level, "reasons": reasons}
```

- [ ] **Step 4: Run the new tests + the full pov suite (no regressions)**

Run: `python3 tests/test_pov.py`
Expected: PASS (new functions added to the runner; all pre-existing `aggregate_health` tests still pass — absent facts give identical output).

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(health): critical-signal gates in aggregate_health (stream/funnel/push)"
```

---

### Task 5: Companion TCP reachability helper (`companion_common.py`)

**Files:**
- Modify: `src/scripts/companion_common.py`
- Test: `tests/test_companion.py`

**Interfaces:**
- Produces: `companion_reachable(host="127.0.0.1", port=8000, timeout=1.0) -> bool` — a stdlib TCP connect; best-effort (any `OSError` → `False`). `COMPANION_DEFAULT_ADMIN_PORT = 8000`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_companion.py` (localhost only — CI-safe):

```python
def t_companion_reachable():
    import socket
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert companion_common.companion_reachable("127.0.0.1", port, 1.0) is True
    finally:
        srv.close()
    # Closed port -> False (no exception).
    assert companion_common.companion_reachable("127.0.0.1", port, 0.5) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_companion as t; t.t_companion_reachable()"`
Expected: FAIL (`companion_reachable` not defined).

- [ ] **Step 3: Implement**

Add to `src/scripts/companion_common.py` (it already `import socket`? if not, add the import at top):
```python
import socket

COMPANION_DEFAULT_ADMIN_PORT = 8000


def companion_reachable(host="127.0.0.1", port=COMPANION_DEFAULT_ADMIN_PORT, timeout=1.0):
    """True iff a TCP connection to the Companion admin port succeeds. Best-effort:
    any socket error -> False (Companion not running / wrong port)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
```

- [ ] **Step 4: Run + commit**

Run: `python3 tests/test_companion.py` → PASS.
```bash
python3 tools/lint.py
git add src/scripts/companion_common.py tests/test_companion.py
git commit -m "feat(companion): companion_reachable TCP health probe"
```

---

### Task 6: Feed stream-quality parser + pump hook (`logsetup.py` + `racecast-feeds.py`)

**Files:**
- Modify: `src/scripts/logsetup.py` (`pump_subprocess` gains an optional `on_line` callback)
- Modify: `src/relay/racecast-feeds.py` (pure `parse_stream_quality`; `Feed.quality` + line observer; pass `on_line` at pump start)
- Test: `tests/test_logs.py` (pump hook), `tests/test_pov.py` (parser)

**Interfaces:**
- Produces:
  - `logsetup.pump_subprocess(stream, logger, tag, on_line=None)` — calls `on_line(line)` per line when provided (best-effort: an `on_line` exception is swallowed).
  - `racecast-feeds.parse_stream_quality(line) -> str|None` — extracts the quality token from a streamlink `Opening stream: <quality> (...)` line; `None` otherwise.
  - `Feed.quality` (str|None), updated by `Feed._observe_streamlink_line(line)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pov.py`:
```python
def t_parse_stream_quality():
    assert parse_stream_quality("[cli][info] Opening stream: 720p (hls)") == "720p"
    assert parse_stream_quality("[cli][info] Opening stream: source (hls)") == "source"
    assert parse_stream_quality("[cli][info] Opening stream: 1080p60 (muxed-stream)") == "1080p60"
    assert parse_stream_quality("[download] Written 5 MB") is None
    assert parse_stream_quality("") is None
```

Add to `tests/test_logs.py`:
```python
def t_pump_subprocess_on_line_hook():
    import io, logging
    seen = []
    stream = io.StringIO("a\nb\n")
    logger = logging.getLogger("t.pump.hook"); logger.addHandler(logging.NullHandler())
    logsetup.pump_subprocess(stream, logger, "streamlink", on_line=seen.append)
    assert seen == ["a", "b"]
    # A failing callback never breaks the pump.
    stream2 = io.StringIO("x\n")
    def boom(_): raise ValueError("nope")
    logsetup.pump_subprocess(stream2, logger, "streamlink", on_line=boom)  # no raise
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_parse_stream_quality()"`
Expected: FAIL (`parse_stream_quality` not defined).

- [ ] **Step 3: Implement the pump hook**

In `src/scripts/logsetup.py`, replace `pump_subprocess`:
```python
def pump_subprocess(stream, logger, tag, on_line=None):
    """Read text lines from a subprocess pipe (stream) and log each at a classified
    level, prefixed `[tag]`. When on_line is given, call it per (stripped) line for
    side-channel parsing (e.g. feed quality) — a failing callback never breaks the
    pump. Runs to EOF; swallows read errors. Designed for a daemon thread."""
    try:
        for raw in iter(stream.readline, ""):   # sentinel "" stops at EOF
            line = raw.rstrip("\n").rstrip("\r")
            logger.log(classify_subproc_line(line), "[%s] %s", tag, line)
            if on_line is not None:
                try:
                    on_line(line)
                except Exception:                # noqa: BLE001 — observer is best-effort
                    pass
    except (ValueError, OSError):
        pass  # pipe closed mid-read — end the thread, never the daemon
```

- [ ] **Step 4: Implement the parser + Feed wiring**

In `src/relay/racecast-feeds.py`, add the pure parser near the other module helpers (e.g. above the `Feed` class):
```python
import re

_STREAM_QUALITY_RE = re.compile(r"Opening stream:\s+(\S+)")


def parse_stream_quality(line):
    """The quality token from a streamlink 'Opening stream: <quality> (...)' line,
    else None. Pure → unit-tested."""
    if not line:
        return None
    m = _STREAM_QUALITY_RE.search(line)
    return m.group(1) if m else None
```
(If `re` is already imported at the top of the file, do not add a second import — put `_STREAM_QUALITY_RE` next to the function.)

In `Feed.__init__`, add after `self.served_ok = False`:
```python
        self.quality = None               # last streamlink-selected quality (e.g. "720p")
```

Add the observer method to `Feed`:
```python
    def _observe_streamlink_line(self, line):
        q = parse_stream_quality(line)
        if q:
            self.quality = q
```

At the pump start (the `threading.Thread(target=logsetup.pump_subprocess, args=(self.proc.stdout, self.log, "streamlink"), ...)` call ~line 2816), pass the observer. Since `pump_subprocess` now takes `on_line` as a keyword, change `args=(...)` to include it via `kwargs`:
```python
                pump = threading.Thread(
                    target=logsetup.pump_subprocess,
                    args=(self.proc.stdout, self.log, "streamlink"),
                    kwargs={"on_line": self._observe_streamlink_line},
                    daemon=True)
```
(Preserve whatever local variable name / `.start()` the existing code uses.)

- [ ] **Step 5: Run the tests**

Run: `python3 tests/test_pov.py && python3 tests/test_logs.py`
Expected: PASS (add the new functions to each runner).

- [ ] **Step 6: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/logsetup.py src/relay/racecast-feeds.py tests/test_pov.py tests/test_logs.py
git commit -m "feat(relay): parse streamlink feed quality via pump on_line hook"
```

---

### Task 7: Relay collect layer — sample OBS stats + connectivity into relay state (`racecast-feeds.py`)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`Relay.__init__`, `_run_obs_probe`, a new `_sample_connectivity`, the heartbeat)
- Test: `tests/test_pov.py`

**Interfaces:**
- Consumes: `obs_ws.get_health_stats`, `obs_ws.stream_kbps`, `tailscale.funnel_on`, `tailscale.tailscale_backend`, `companion_common.companion_reachable`, `Feed.quality`, the timer store `summary()["push"]`.
- Produces relay attributes (read by Task 8): `self.obs_stats` (dict, redacted — NO `output_bytes`), `self.conn_state` (dict: `funnel_ok`, `tailscale_up`, `companion_ok`, `funnel_expected`). Internal: `self._obs_last_bytes`, `self._obs_last_bytes_ts`, `self.funnel_expected`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pov.py` (drives the pure pieces; the network helpers are monkeypatched):

```python
def t_sample_connectivity_sets_state_and_expected(monkeypatch):
    relay = _make_min_relay()  # existing helper in test_pov that builds a Relay; if absent,
                               # build the smallest Relay the other tests use.
    import racecast_feeds as rf
    monkeypatch.setattr(rf.tailscale, "funnel_on", lambda *a, **k: True)
    monkeypatch.setattr(rf.tailscale, "tailscale_backend", lambda *a, **k: ("ts", "Running", "100.64.0.1"))
    monkeypatch.setattr(rf.companion_common, "companion_reachable", lambda *a, **k: False)
    relay._sample_connectivity()
    assert relay.conn_state["funnel_ok"] is True
    assert relay.conn_state["tailscale_up"] is True
    assert relay.conn_state["companion_ok"] is False
    assert relay.funnel_expected is True           # latched once seen up
    # Funnel later down, but expected stays latched -> funnel_down derivable.
    monkeypatch.setattr(rf.tailscale, "funnel_on", lambda *a, **k: False)
    relay._sample_connectivity()
    assert relay.conn_state["funnel_ok"] is False
    assert relay.funnel_expected is True
```

> Implementer note: `tests/test_pov.py` imports the relay module as `racecast_feeds` (the hyphenated filename is loaded via the existing test shim — reuse whatever import alias the file already uses). If no `_make_min_relay` helper exists, add a tiny module-level factory in the test that constructs the relay with stub feeds, mirroring the existing relay-construction tests.

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_pov.py` (the new function errors: `_sample_connectivity` / `conn_state` missing).
Expected: FAIL.

- [ ] **Step 3: Implement relay state + samplers**

In `Relay.__init__`, alongside the existing health fields (near `self.obs_reachable = None`), add:
```python
        self.obs_stats = {}               # last redacted OBS GetStats/GetStreamStatus
        self._obs_last_bytes = None       # for stream_kbps derivation
        self._obs_last_bytes_ts = None
        self.conn_state = {"funnel_ok": None, "tailscale_up": None,
                           "companion_ok": None}
        self.funnel_expected = False      # latched True once the Funnel is seen up
```

Replace `_run_obs_probe` so it fetches stats and derives kbps in the same session:
```python
    def _run_obs_probe(self):
        """Body of the OBS probe (own method so it is testable synchronously).
        Fetches reachability + GetStats/GetStreamStatus in one session, derives the
        upstream kbps, and stores a REDACTED stats dict (never output_bytes)."""
        now = time.time()
        reachable, stats, note = _obs_ws.get_health_stats()
        kbps = _obs_ws.stream_kbps(self._obs_last_bytes, self._obs_last_bytes_ts,
                                   stats.get("output_bytes"), now,
                                   stats.get("stream_active"))
        with self._obs_lock:
            self.obs_reachable = reachable
            self.obs_note = note or None
            self._obs_probe_running = False
            self._obs_last_bytes = stats.get("output_bytes")
            self._obs_last_bytes_ts = now
            redacted = {k: v for k, v in stats.items() if k != "output_bytes"}
            redacted["stream_kbps"] = kbps
            self.obs_stats = redacted
```

Add the connectivity sampler as a `Relay` method:
```python
    def _sample_connectivity(self):
        """Sample Funnel/Tailscale/Companion reachability into self.conn_state and
        latch funnel_expected. Best-effort: each probe defaults to None on failure."""
        try:
            funnel = tailscale.funnel_on("/console")
        except Exception:                                # noqa: BLE001 — best-effort
            funnel = None
        try:
            ts_state = tailscale.tailscale_backend()[1]
            ts_up = (ts_state == "Running") if ts_state is not None else None
        except Exception:                                # noqa: BLE001
            ts_up = None
        try:
            comp_port = int(os.environ.get("RACECAST_COMPANION_PORT")
                            or companion_common.COMPANION_DEFAULT_ADMIN_PORT)
            comp = companion_common.companion_reachable("127.0.0.1", comp_port)
        except Exception:                                # noqa: BLE001
            comp = None
        if funnel:
            self.funnel_expected = True
        self.conn_state = {"funnel_ok": funnel, "tailscale_up": ts_up,
                           "companion_ok": comp}
```

Ensure the imports exist at the top of `racecast-feeds.py`: `from scripts import tailscale, companion_common` (match the file's existing import style for sibling scripts; the relay already imports `obs_ws` as `_obs_ws`). If the relay is dependency-light and does NOT currently import these, import them lazily inside `_sample_connectivity` instead (a top-of-function `import` is acceptable here because the heartbeat is not hot-path and the relay already shells to tailscale elsewhere). Pick whichever matches the file; do not add an unused import.

Call `_sample_connectivity()` from `_heartbeat_loop`, right after `self._maybe_probe_obs(now)`:
```python
            self._maybe_probe_obs(now)
            self._sample_connectivity()
```

- [ ] **Step 4: Run the test**

Run: `python3 tests/test_pov.py` → PASS.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): sample OBS stats + connectivity in the heartbeat"
```

---

### Task 8: Relay emit layer — snapshot, facts, current payload (`racecast-feeds.py`)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`_health_snapshot`, `_health_facts`, the handler's `_health_current`)
- Test: `tests/test_pov.py` (snapshot + facts shape), `tests/test_racecast.py` (current payload, if a relay fixture exists there)

**Interfaces:**
- Consumes: `self.obs_stats`, `self.conn_state`, `self.funnel_expected`, `Feed.quality`, timer push status.
- Produces: `_health_snapshot` returns all 17 new fields; `_health_facts` returns the new gated critical keys (`stream_active`, `stream_reconnecting`, `funnel_down`, `sheet_push_failing`); `_health_current` adds per-feed `quality`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pov.py`:

```python
def t_health_snapshot_carries_new_fields():
    relay = _make_min_relay()
    relay.obs_stats = {"obs_cpu_pct": 10.0, "obs_fps": 60.0, "stream_active": True,
                       "stream_reconnecting": False, "stream_congestion": 0.1,
                       "stream_dropped_pct": 0.0, "stream_kbps": 6000.0,
                       "obs_mem_mb": 900.0, "obs_disk_free_mb": 5000.0,
                       "obs_render_skipped_pct": 0.0}
    relay.conn_state = {"funnel_ok": True, "tailscale_up": True, "companion_ok": False}
    relay.funnel_expected = True
    relay.feeds["A"].quality = "720p"
    snap = relay._health_snapshot(123.0)
    assert snap["obs_cpu_pct"] == 10.0 and snap["stream_active"] == 1
    assert snap["funnel_ok"] == 1 and snap["companion_ok"] == 0
    assert snap["feed_a_quality"] == "720p"
    # All COLUMNS keys present (record() tolerates missing, but emit them explicitly).
    import health_store as hs
    for col in hs.COLUMNS:
        if col not in ("kind",):
            assert col in snap, col


def t_health_facts_gate_funnel_and_push():
    relay = _make_min_relay()
    relay.obs_reachable = True
    relay.obs_stats = {"stream_active": True, "stream_reconnecting": True}
    relay.conn_state = {"funnel_ok": False, "tailscale_up": True, "companion_ok": True}
    relay.funnel_expected = True                  # funnel was up, now down -> funnel_down
    facts = relay._health_facts(1.0)
    assert facts["stream_reconnecting"] is True
    assert facts["funnel_down"] is True
    # funnel never seen up -> not a fault
    relay.funnel_expected = False
    assert relay._health_facts(1.0)["funnel_down"] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_pov.py`
Expected: FAIL (snapshot lacks `obs_cpu_pct` / facts lacks `funnel_down`).

- [ ] **Step 3: Implement**

Extend `_health_snapshot`'s returned dict. Just before the final `return {...}`, add helpers and merge the new fields. Replace the `return {...}` so it includes:
```python
        st = self.obs_stats or {}
        cs = self.conn_state or {}

        def _b(v):
            return None if v is None else (1 if v else 0)

        def _q(f):
            return getattr(f, "quality", None)

        return {"ts": now,
                "health_level": self.health_level, "health_reasons": self.health_reasons,
                "feed_a_state": a_state, "feed_a_down": a_down, "feed_a_stint": a_stint,
                "feed_b_state": b_state, "feed_b_down": b_down, "feed_b_stint": b_stint,
                "pov_state": (None if not self.pov else
                              ("stopped" if self.pov.paused else self.pov.phase)),
                "obs_reachable": (None if self.obs_reachable is None
                                  else (1 if self.obs_reachable else 0)),
                "source_last_ok_age_s": self.source.health().get("last_ok_age_s"),
                "source_count": self.source.health().get("count"),
                "cookies_present": 1 if self.cookies else 0,
                "cookies_age_h": ch.get("age_h"),
                "cookies_stale": 1 if ch.get("stale") else 0,
                "timer_mode": tmode, "timer_push": tpush,
                "mode": self.mode,
                "live_feed": live, "live_stint": self.feeds[live].idx + 1,
                # v3 OBS stats (already redacted: obs_stats never carries output_bytes)
                "stream_active": _b(st.get("stream_active")),
                "stream_reconnecting": _b(st.get("stream_reconnecting")),
                "stream_kbps": st.get("stream_kbps"),
                "stream_dropped_pct": st.get("stream_dropped_pct"),
                "stream_congestion": st.get("stream_congestion"),
                "obs_cpu_pct": st.get("obs_cpu_pct"),
                "obs_mem_mb": st.get("obs_mem_mb"),
                "obs_fps": st.get("obs_fps"),
                "obs_render_skipped_pct": st.get("obs_render_skipped_pct"),
                "obs_disk_free_mb": st.get("obs_disk_free_mb"),
                # v3 connectivity (sheet_push_ok derived from the timer push status)
                "funnel_ok": _b(cs.get("funnel_ok")),
                "tailscale_up": _b(cs.get("tailscale_up")),
                "companion_ok": _b(cs.get("companion_ok")),
                "sheet_push_ok": (None if tpush in (None, "never", "disabled")
                                  else (1 if tpush == "ok" else 0)),
                # v3 feed quality
                "feed_a_quality": _q(self.feeds["A"]),
                "feed_b_quality": _q(self.feeds["B"]),
                "pov_quality": _q(self.pov) if self.pov else None}
```

Extend `_health_facts`'s return dict. Compute the gated facts before the `return`:
```python
        st = self.obs_stats or {}
        cs = self.conn_state or {}
        funnel_down = bool(self.funnel_expected) and (cs.get("funnel_ok") is False)
        tpush = None
        ts = getattr(self, "timer_store", None)
        if ts is not None:
            try:
                tpush = ts.summary().get("push")
            except Exception:                            # noqa: BLE001 — best-effort
                tpush = None
        return {"feeds_down": feeds_down, "feeds_connecting_long": connecting_long,
                "cookies_stale": cookie_health(self.cookies, now=now)["stale"],
                "obs_reachable": self.obs_reachable, "tailscale_present": ts_present,
                "stream_active": st.get("stream_active"),
                "stream_reconnecting": st.get("stream_reconnecting"),
                "funnel_down": funnel_down,
                "sheet_push_failing": (tpush == "failed")}
```

Extend `_health_current` (the nested handler method) so each feed carries its quality. Change the `feeds` comprehension to read from `relay.feeds` for quality (status() does not expose it):
```python
            feeds = {}
            for k, v in (full.get("feeds") or {}).items():
                q = getattr(relay.feeds.get(k), "quality", None) if relay.feeds.get(k) else None
                feeds[k] = {"state": v.get("state"), "down": v.get("down"),
                            "stint": v.get("stint"), "state_age_s": v.get("state_age_s"),
                            "quality": q}
            pov = full.get("pov")
            pov_red = None if not pov else {"state": pov.get("state"),
                                            "down": pov.get("down"), "shown": pov.get("shown"),
                                            "quality": getattr(relay.pov, "quality", None)}
```
(Leave the rest of `_health_current` unchanged.)

- [ ] **Step 4: Run the tests**

Run: `python3 tests/test_pov.py`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): emit OBS stats + connectivity + feed quality in health samples"
```

---

### Task 9: Dashboard UI — grouped bands, new charts, feed badges (`health-monitor.html`)

**Files:**
- Modify: `src/console/health-monitor.html`
- Test: manual (driven in Task 10's e2e + screenshot); JS has no unit harness in this repo.

**Interfaces:**
- Consumes: the `/health-monitor/data` payload's `bands`, `series`, `current.feeds[X].quality`.
- Produces: grouped band sections (Critical / Feeds / Connectivity), the 8 new charts, per-feed quality badges, and `segClass` mappings for the new boolean bands.

- [ ] **Step 1: Extend the band field list with groups**

Replace the JS `BAND_FIELDS` array (~line 350) with grouped entries `[field, label, group]`:
```js
const BAND_FIELDS = [
  ["health_level", "Health", "critical"],
  ["stream_active", "Stream active", "critical"],
  ["stream_reconnecting", "Reconnecting", "critical"],
  ["funnel_ok", "Funnel", "critical"],
  ["sheet_push_ok", "Sheet push", "critical"],
  ["feed_a_state", "Feed A", "feeds"],
  ["feed_b_state", "Feed B", "feeds"],
  ["pov_state", "POV", "feeds"],
  ["obs_reachable", "OBS", "connectivity"],
  ["tailscale_up", "Tailscale", "connectivity"],
  ["companion_ok", "Companion", "connectivity"],
  ["cookies_stale", "Cookies", "connectivity"],
  ["timer_push", "Timer sync", "connectivity"],
];
const BAND_GROUPS = [["critical", "Critical"], ["feeds", "Feeds"],
                     ["connectivity", "Connectivity"]];
```

- [ ] **Step 2: Render group subheaders + feed badges in `renderBands`**

Update `renderBands(bands, current)` to take the current snapshot (for feed quality) and emit a subheader per group, then the rows of that group. Replace the `BAND_FIELDS.forEach(...)` loop with:
```js
function renderBands(bands, current) {
  const host = $("hm-bands");
  host.innerHTML = "";
  const quality = {
    feed_a_state: current && current.feeds && current.feeds.A && current.feeds.A.quality,
    feed_b_state: current && current.feeds && current.feeds.B && current.feeds.B.quality,
    pov_state: current && current.pov && current.pov.quality,
  };
  BAND_GROUPS.forEach(([gkey, gtitle]) => {
    const rows = BAND_FIELDS.filter(([, , g]) => g === gkey);
    const hdr = document.createElement("div");
    hdr.className = "band-group"; hdr.textContent = gtitle;
    host.appendChild(hdr);
    rows.forEach(([field, label]) => {
      const segs = (bands && bands[field]) || [];
      if (field === "pov_state" && segs.every((b) => b.state === null || b.state === undefined)) return;
      const row = document.createElement("div"); row.className = "bandrow";
      const lab = document.createElement("div"); lab.className = "bandlabel";
      lab.textContent = label;
      const q = quality[field];
      if (q) { const tag = document.createElement("span"); tag.className = "qbadge";
               tag.textContent = q; lab.appendChild(tag); }
      const track = document.createElement("div"); track.className = "bandtrack";
      // ... keep the EXISTING per-seg rendering loop here (positions + segClass) ...
      row.appendChild(lab); row.appendChild(track); host.appendChild(row);
    });
  });
}
```
(Preserve the existing segment-positioning math and the `track`/`row` element structure the current code uses — only the grouping wrapper + badge are new. Match the existing class names for label/track if they differ.)

Update the caller (~line 556): `renderBands(blob.bands || {}, blob.current || {});`

- [ ] **Step 3: Extend `segClass` for the new boolean bands**

In `segClass(field, state)` add cases BEFORE the free-form-state fallback:
```js
  // Critical booleans: 1 = ok (green), 0 = fault (red); stream_reconnecting is inverted.
  if (field === "stream_active" || field === "funnel_ok" || field === "sheet_push_ok") {
    if (state === null || state === undefined) return "unknown";
    return state ? "on" : "off";
  }
  if (field === "stream_reconnecting") {
    if (state === null || state === undefined) return "unknown";
    return state ? "off" : "on";          // reconnecting=true is the fault
  }
  // Observational booleans: down is neutral (not an alarm).
  if (field === "tailscale_up" || field === "companion_ok") {
    if (state === null || state === undefined) return "unknown";
    return state ? "on" : "neutral";
  }
```
And the label helper `stateLabel(field, state)` (~line 345) — add:
```js
  if (field === "stream_active") return state ? "streaming" : "not streaming";
  if (field === "stream_reconnecting") return state ? "reconnecting" : "stable";
  if (field === "funnel_ok") return state ? "up" : "down";
  if (field === "sheet_push_ok") return state ? "ok" : "failing";
  if (field === "tailscale_up") return state ? "up" : "down";
  if (field === "companion_ok") return state ? "up" : "down";
```

- [ ] **Step 4: Add the 8 new charts (grouped)**

Replace the numeric chart field list (~line 402) with grouped entries:
```js
const NUMERIC_FIELDS = [
  ["stream_kbps", "Upstream kbps", "OBS Output"],
  ["stream_dropped_pct", "Dropped frames %", "OBS Output"],
  ["stream_congestion", "Congestion", "OBS Output"],
  ["obs_cpu_pct", "OBS CPU %", "OBS Resources"],
  ["obs_mem_mb", "OBS memory (MB)", "OBS Resources"],
  ["obs_fps", "OBS FPS", "OBS Resources"],
  ["obs_render_skipped_pct", "Render skipped %", "OBS Resources"],
  ["obs_disk_free_mb", "Disk free (MB)", "OBS Resources"],
  ["source_last_ok_age_s", "Source last-OK age (s)", "Relay / Schedule"],
  ["cookies_age_h", "Cookies age (h)", "Relay / Schedule"],
];
```
In the chart-building function, iterate groups: emit a `<div class="chart-group">Title</div>` subheader before each group's charts (the existing per-field uPlot creation loop is unchanged — just key off the 3-tuple's `[0]` field and `[1]` title, and insert the group header when the group changes). A field whose series is empty/all-None still creates an (empty) chart — keep current behavior.

- [ ] **Step 5: Add CSS for the new elements**

In the `<style>` block, near the bands styles:
```css
  .band-group, .chart-group { font-size: 12px; font-weight: 600; color: var(--muted);
    text-transform: uppercase; letter-spacing: .04em; margin: 10px 0 4px; }
  .qbadge { margin-left: 8px; font-size: 11px; font-weight: 500; color: var(--muted);
    background: rgba(255,255,255,.06); border-radius: 4px; padding: 1px 6px; }
```

- [ ] **Step 6: Manual smoke**

Run a dev relay with the synthetic e2e (Task 10) OR `racecast relay start` from `src/`, open `/health-monitor`, confirm: grouped band sections render, new boolean bands show the right colors (unknown=grey when OBS down), feed badges appear when a quality is known, the 8 new charts render under their group headers without console errors.

- [ ] **Step 7: Commit**

```bash
python3 tools/lint.py     # html is not linted, but keep the habit for any touched .py
git add src/console/health-monitor.html
git commit -m "feat(ui): grouped Health Monitor bands/charts + feed-quality badges"
```

---

### Task 10: e2e coverage, build, wiki screenshot + docs

**Files:**
- Modify: `tools/e2e_checks.py` (extend the health-monitor check), `tools/build.py` (only if it asserts on health-monitor.html contents — verify, adjust if needed)
- Modify: `src/docs/wiki/Health-Monitor.md`
- Replace: `src/docs/wiki/images/health-monitor.png`
- Test: `python3 tests/test_e2e.py`, `python3 tools/e2e.py`, `python3 tools/build.py`

**Interfaces:**
- Consumes: the extended `/health-monitor/data` payload.
- Produces: an e2e assertion that the new fields appear (as `None` in synthetic mode) and the page renders the new groups; a refreshed wiki screenshot + doc text.

- [ ] **Step 1: Extend the synthetic e2e check**

In `tools/e2e_checks.py`, find the existing health-monitor check (it asserts `/health-monitor/data` shape). Extend it to assert the new keys exist in the payload's band/series maps (values are `None`/empty in synthetic mode — OBS/Tailscale absent — which is the correct synthetic result):
```python
    # v3 fields present in the band + series maps (None/empty without OBS/Tailscale)
    bands = blob.get("bands") or {}
    for f in ("stream_active", "funnel_ok", "tailscale_up", "companion_ok"):
        if f not in bands:
            return CheckResult("health_monitor_v3_fields", False, f"missing band {f}")
    series = blob.get("series") or {}
    for f in ("stream_kbps", "obs_cpu_pct"):
        if f not in series:
            return CheckResult("health_monitor_v3_fields", False, f"missing series {f}")
```
(Adapt to the file's actual `CheckResult` signature + how the existing check fetches `blob`. If the check is registered in `SYNTHETIC_CHECKS`, the new assertions ride along — no new registration needed.)

- [ ] **Step 2: Run the e2e unit tests + the synthetic harness**

Run: `python3 tests/test_e2e.py`
Expected: PASS.
Run: `python3 tools/e2e.py`
Expected: all checks pass (the synthetic relay now reports the v3 fields as None/empty).

- [ ] **Step 3: Verify the build still self-checks**

Run: `python3 tools/build.py`
Expected: PASS (the verify step ships `health-monitor.html`; no secret/shell-script regressions). If `tools/build.py` or `tests/test_build.py` asserts on specific health-monitor.html content, update that assertion to match the new markup.

- [ ] **Step 4: Refresh the wiki screenshot (dev build)**

Capture from a LOCAL dev build (run from `src/`, no `VERSION` stamped) so the version badge stays "dev" — per CLAUDE.md and the `wiki-screenshots-use-local-dev-build` memory. Drive a running instance, open `/health-monitor`, and take an **element** screenshot of the monitor card (matching the framing of the existing image). Save over `src/docs/wiki/images/health-monitor.png`.

- [ ] **Step 5: Update the wiki page text**

In `src/docs/wiki/Health-Monitor.md`, document the new sections (OBS stats: stream-active/reconnecting, dropped %, congestion, upstream kbps, CPU/MEM/FPS/render-skip/disk; connectivity: Funnel/Tailscale/Companion; feed quality; Sheet-push) and state the critical-vs-observational split and the "no live-gate ⇒ red even pre-show" consequence. Run `python3 tests/test_wiki.py` if present (validates links/anchors).

- [ ] **Step 6: Commit**

```bash
python3 tools/lint.py
git add tools/e2e_checks.py tools/build.py src/docs/wiki/Health-Monitor.md src/docs/wiki/images/health-monitor.png
git commit -m "test(e2e)+docs(wiki): cover Health Monitor v3 fields + refresh screenshot"
```

---

## Self-Review

**Spec coverage:**
- §1 fields (17) → Tasks 1 (schema), 7/8 (sampling+emit), 9 (display). ✓
- §2 sampler mechanics (heartbeat OBS session, kbps reset, connectivity local, sheet-push passive, feed-quality parse) → Tasks 2/3/5/6/7/8. ✓
- §3 critical logic (no live-gate red; reconnect/funnel/push yellow; funnel_expected; sheet-push configured) → Tasks 4 (gates) + 7/8 (gating facts). ✓
- §4 migration v2→v3 / redaction / handover → Task 1 (migration; export/import carry COLUMNS for free — no new task needed, verified by Task 1's round-trip + existing health pull tests). ✓
- §5 UI grouped layout/badges/incident timeline → Task 9 (timeline already derives from health_level, so the new criticals appear via health_reasons — no change needed). ✓
- §6 testing → each task is TDD; Task 10 adds e2e + wiki. ✓

**Placeholder scan:** no TBD/TODO; every code step shows complete code. The two "preserve the existing loop" notes in Task 9 are intentional (the surrounding segment-math is large and unchanged) and name exactly what to keep.

**Type consistency:** `obs_stats` keys (`stream_active`, `obs_cpu_pct`, …) match `parse_obs_stats`/`parse_stream_status` outputs and the `COLUMNS` names; `conn_state` keys (`funnel_ok`/`tailscale_up`/`companion_ok`) match `_sample_connectivity`, `_health_snapshot`, and the band fields; `stream_kbps` is derived in Task 3 and stored under that exact name; `sheet_push_ok` is derived from the timer push status (no separate sampler), consistent with §2's "passive". `_health_facts` emits `funnel_down`/`sheet_push_failing`/`stream_active`/`stream_reconnecting` exactly as `aggregate_health` (Task 4) consumes them.

**Known soft spots flagged for the implementer:** the relay module import alias in tests (`racecast_feeds`) and the `_make_min_relay` helper (reuse or add); the Companion default port (8000, `RACECAST_COMPANION_PORT` override); whether `re`/`socket` are already imported in the target files (don't double-import — the lint hook rejects unused/duplicate imports).
