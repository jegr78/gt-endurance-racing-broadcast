# Health Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a relay-served Health Monitor dashboard that records the relay's own health as a SQLite time-series and renders it (status bands + uPlot line charts + an incident timeline) with time-range filtering, reachable locally and over Funnel under `/console` for any authenticated subject.

**Architecture:** A new pure-logic SQLite store (`src/scripts/health_store.py`) holds time-series samples and derives bands/incidents/numeric-series. The relay wraps it thread-safely (`HealthStore`), samples itself in the existing 30 s heartbeat, and serves `/health-monitor` (page) + `/health-monitor/data` (combined payload) at the tailnet root and under the existing `/console` gate (`Requirement(ANY, False)`). Producer takeover pulls the history (`/console/takeover/health` step-up, tailnet `/health/raw`); a `racecast health export|import|pull` CLI and a Control Center card cover cross-event persistence.

**Tech Stack:** Python 3 stdlib only (`sqlite3`, `http.server`, `json`, `urllib`), vanilla JS, uPlot (vendored ~50 KB MIT). No pytest — each `tests/test_*.py` is a runnable stdlib script.

## Global Constraints

- **Edit only under `src/`.** `dist/`/`runtime/` are generated; `tools/` are maintainer scripts (touch only for build/wiki tasks).
- **English only** in all code and docs.
- **No hardcoded secrets or machine paths.** No real IPs in tests (Tailscale test constants are `100.64.0.0/10`).
- **Tooling is Python-only** — no `.sh`/`.bat`.
- **Outbound HTTP from the covered side goes through `src/scripts/http_util.py`** (CLI `health pull`). The relay stays dependency-light and must NOT import `config.py`/shared CLI modules into the hyphenated relay file beyond what it already imports.
- **Pure-store house style:** atomic writes, sanitize-on-load, return `{"ok": ...}`/`{"error": ...}`, mirror `chat_admin.py`/`cue_admin.py`.
- **Redaction by construction:** the sample schema has NO stream-URL / `sheet_id` columns; the `current` block in `/health-monitor/data` is built from an allowlist, never the raw `relay.status()`.
- **Access policy:** `["health-monitor"]` and `["health-monitor","data"]` → `Requirement(ANY, False)`. Do NOT introduce a new role/capability. `["console","takeover","health"]` is already covered by the generic `takeover/*` → `Requirement(PRODUCER, True)` rule.
- **Tests run on any machine + CI** via `python3 tools/run-tests.py`; lint via `python3 tools/lint.py`.
- **A changed UI surface requires its wiki screenshot refreshed in the same change** (Task 16): the new monitor page + the Control Center card → `cc-*.png` (local dev build, no `VERSION` stamp).
- **Constants** (define in `health_store.py`, import where needed): `SAMPLE_INTERVAL_S = 30`, `LIVE_WINDOW_S = 900`, `GAP_S = 95` (≈3× tick → a gap = relay was down), `DEFAULT_MAX_POINTS = 2000`, `DEFAULT_RETENTION_DAYS = 30`, `BAND_FIELDS = ("health_level","feed_a_state","feed_b_state","pov_state","obs_reachable","cookies_stale")`, `NUMERIC_FIELDS = ("source_last_ok_age_s","cookies_age_h","timer_remaining_s")`, `STATE_KEY_FIELDS = ("health_level","feed_a_state","feed_a_down","feed_b_state","feed_b_down","pov_state","obs_reachable")`.

---

## File Structure

**Create:**
- `src/scripts/health_store.py` — pure SQLite store + derivations (Tasks 1–6).
- `src/console/health-monitor.html` — the dashboard page (Task 11).
- `src/assets/vendor/uplot/uPlot.iife.min.js`, `uPlot.min.css`, `LICENSE` — vendored chart lib (Task 10).
- `tests/test_health_store.py` — pure-store + `HealthStore` wrapper tests (Tasks 1–7).

**Modify:**
- `src/relay/racecast-feeds.py` — `HealthStore` wrapper, `Relay._health_snapshot`, heartbeat sampling, `make_handler(health_store=…, health_monitor_page_path=…, uplot_dir=…)`, root + console routes, payload builders, gate branch, bootstrap wiring (Tasks 7, 9, 10, 13).
- `src/scripts/console_policy.py` — two policy entries (Task 8).
- `src/racecast.py` — `health` subcommand (export/import/pull), takeover health pull, `_health_db_path()` (Tasks 12, 13).
- `src/ui/ui_server.py` + `src/ui/control-center.html` + `src/racecast_ui.py` — Health Monitor card + export/import ops (Task 14).
- `tests/test_console.py`, `tests/test_console_gate.py`, `tests/test_racecast.py`, `tests/test_ui_server.py` — gate/route/CLI/UI tests (Tasks 8, 9, 12, 14).
- `README.md`, `CLAUDE.md`, `src/docs/wiki/` (+ images) — docs + screenshots (Task 16).

---

## Task 1: health_store.py — schema, open/migrate, record, query_range

**Files:**
- Create: `src/scripts/health_store.py`
- Create: `tests/test_health_store.py`

**Interfaces:**
- Produces: `open_db(path) -> sqlite3.Connection`, `migrate(conn)`, `SCHEMA_VERSION` (int), the constants from Global Constraints, `COLUMNS` (tuple of column names in order, excluding rowid), `record(conn, snapshot, kind, now=None) -> dict` (the inserted row), `query_range(conn, frm, to) -> list[dict]` (ordered by ts asc; `health_reasons` parsed to a list).

- [ ] **Step 1: Write the failing test**

Create `tests/test_health_store.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the health-history store. Run: python3 tests/test_health_store.py"""
import importlib.util
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


hs = _load("health_store", ("src", "scripts", "health_store.py"))


def _snap(ts=100.0, level="green", a="serving", b="idle"):
    return {"ts": ts, "health_level": level, "health_reasons": [],
            "feed_a_state": a, "feed_a_down": 0, "feed_a_stint": 1,
            "feed_b_state": b, "feed_b_down": 0, "feed_b_stint": 2,
            "pov_state": None, "obs_reachable": 1,
            "source_last_ok_age_s": 2.0, "source_count": 5,
            "cookies_present": 1, "cookies_age_h": 3.0, "cookies_stale": 0,
            "timer_mode": "running", "timer_remaining_s": 1200,
            "mode": "race", "live_feed": "A", "live_stint": 1}


def t_open_migrate_sets_version_and_wal():
    with tempfile.TemporaryDirectory() as d:
        conn = hs.open_db(os.path.join(d, "h.db"))
        hs.migrate(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == hs.SCHEMA_VERSION
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def t_migrate_is_idempotent():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "h.db")
        hs.migrate(hs.open_db(path))
        conn = hs.open_db(path)
        hs.migrate(conn)            # second run must not raise
        assert conn.execute("PRAGMA user_version").fetchone()[0] == hs.SCHEMA_VERSION


def t_record_then_query_roundtrip_parses_reasons():
    with tempfile.TemporaryDirectory() as d:
        conn = hs.open_db(os.path.join(d, "h.db")); hs.migrate(conn)
        hs.record(conn, _snap(ts=100.0, level="yellow") | {"health_reasons": ["cookies stale"]}, "event")
        rows = hs.query_range(conn, 0, 1e12)
        assert len(rows) == 1
        assert rows[0]["ts"] == 100.0 and rows[0]["kind"] == "event"
        assert rows[0]["health_level"] == "yellow"
        assert rows[0]["health_reasons"] == ["cookies stale"]   # parsed back to a list
        assert rows[0]["pov_state"] is None


def t_query_range_filters_and_orders():
    with tempfile.TemporaryDirectory() as d:
        conn = hs.open_db(os.path.join(d, "h.db")); hs.migrate(conn)
        for ts in (300.0, 100.0, 200.0):
            hs.record(conn, _snap(ts=ts), "periodic")
        rows = hs.query_range(conn, 150.0, 250.0)
        assert [r["ts"] for r in rows] == [200.0]
        allrows = hs.query_range(conn, 0, 1e12)
        assert [r["ts"] for r in allrows] == [100.0, 200.0, 300.0]   # ascending


def t_schema_has_no_url_columns():
    # Redaction by construction: a stream URL / sheet_id must never be storable.
    cols = " ".join(hs.COLUMNS).lower()
    for forbidden in ("url", "channel", "sheet", "http"):
        assert forbidden not in cols, forbidden


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_health_store.py`
Expected: FAIL — `ModuleNotFoundError`/`AttributeError` (no `health_store.py`).

- [ ] **Step 3: Write minimal implementation**

Create `src/scripts/health_store.py`:

```python
#!/usr/bin/env python3
"""Pure logic for the relay health-history time-series (runtime/<profile>/health-history.db).

SQLite-backed (stdlib `sqlite3`) — the only non-JSON store in the repo. No network,
no argv parsing: schema/migrations, sample insert, range query, the band/incident/
numeric-series derivations, retention pruning, and JSON-Lines export/import-merge.
Imported by the relay (HealthStore wrapper) and the `racecast health` CLI so both
agree on the on-disk shape. Redaction by construction: there is NO stream-URL or
sheet_id column, so the DB is safe to expose, export, and pull over Funnel.
"""
import json
import sqlite3

SCHEMA_VERSION = 1

SAMPLE_INTERVAL_S = 30          # heartbeat tick = sample cadence
LIVE_WINDOW_S = 900            # default range when no from/to given (15 min)
GAP_S = 95                     # inter-sample gap > this = relay was down (no band spans it)
DEFAULT_MAX_POINTS = 2000      # numeric-series downsample cap per metric
DEFAULT_RETENTION_DAYS = 30

# Column order is the insert order. NO url/channel/sheet columns (redaction).
COLUMNS = (
    "ts", "kind",
    "health_level", "health_reasons",
    "feed_a_state", "feed_a_down", "feed_a_stint",
    "feed_b_state", "feed_b_down", "feed_b_stint",
    "pov_state", "obs_reachable",
    "source_last_ok_age_s", "source_count",
    "cookies_present", "cookies_age_h", "cookies_stale",
    "timer_mode", "timer_remaining_s",
    "mode", "live_feed", "live_stint",
)

BAND_FIELDS = ("health_level", "feed_a_state", "feed_b_state",
               "pov_state", "obs_reachable", "cookies_stale")
NUMERIC_FIELDS = ("source_last_ok_age_s", "cookies_age_h", "timer_remaining_s")
STATE_KEY_FIELDS = ("health_level", "feed_a_state", "feed_a_down",
                    "feed_b_state", "feed_b_down", "pov_state", "obs_reachable")

_CREATE = """
CREATE TABLE IF NOT EXISTS samples (
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    health_level TEXT, health_reasons TEXT,
    feed_a_state TEXT, feed_a_down INTEGER, feed_a_stint INTEGER,
    feed_b_state TEXT, feed_b_down INTEGER, feed_b_stint INTEGER,
    pov_state TEXT, obs_reachable INTEGER,
    source_last_ok_age_s REAL, source_count INTEGER,
    cookies_present INTEGER, cookies_age_h REAL, cookies_stale INTEGER,
    timer_mode TEXT, timer_remaining_s INTEGER,
    mode TEXT, live_feed TEXT, live_stint INTEGER
);
CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples (ts);
"""


def open_db(path):
    """Open (creating the file/dirs as needed) with WAL + a busy timeout so the
    heartbeat writer and request-thread readers don't trip over each other."""
    conn = sqlite3.connect(path, check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def migrate(conn):
    """Create the schema and stamp user_version. Idempotent."""
    conn.executescript(_CREATE)
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    conn.commit()


def _row_to_dict(row):
    d = dict(row)
    raw = d.get("health_reasons")
    try:
        d["health_reasons"] = json.loads(raw) if raw else []
    except (ValueError, TypeError):
        d["health_reasons"] = []
    return d


def record(conn, snapshot, kind, now=None):
    """Insert one sample row from a snapshot dict. Missing keys store NULL;
    health_reasons (a list) is JSON-encoded. Returns the stored row as a dict."""
    s = dict(snapshot)
    if now is not None and s.get("ts") is None:
        s["ts"] = now
    s["kind"] = kind
    s["health_reasons"] = json.dumps(s.get("health_reasons") or [])
    values = [s.get(col) for col in COLUMNS]
    placeholders = ",".join("?" for _ in COLUMNS)
    conn.execute(f"INSERT INTO samples ({','.join(COLUMNS)}) VALUES ({placeholders})", values)
    conn.commit()
    stored = {c: s.get(c) for c in COLUMNS}
    stored["health_reasons"] = snapshot.get("health_reasons") or []
    return stored


def query_range(conn, frm, to):
    """Samples with frm <= ts <= to, ascending. health_reasons parsed to a list."""
    cur = conn.execute("SELECT * FROM samples WHERE ts>=? AND ts<=? ORDER BY ts ASC",
                       (frm, to))
    return [_row_to_dict(r) for r in cur.fetchall()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_health_store.py`
Expected: `ok t_open_migrate_…` … `ALL PASS`.

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: no findings for the new file.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/health_store.py tests/test_health_store.py
git commit -m "feat(health): SQLite health-history store — schema, record, query"
```

---

## Task 2: derive_bands — collapse equal states, break on gaps

**Files:**
- Modify: `src/scripts/health_store.py`
- Test: `tests/test_health_store.py`

**Interfaces:**
- Consumes: `query_range` row dicts, `BAND_FIELDS`, `GAP_S`.
- Produces: `collapse_bands(points, gap_s=GAP_S) -> list[{from,to,state}]` (points = list of `(ts, value)`), `derive_bands(samples, gap_s=GAP_S) -> dict[field -> list[band]]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_health_store.py` (above the `__main__` block):

```python
def t_collapse_bands_merges_equal_and_splits_on_change():
    pts = [(0.0, "green"), (30.0, "green"), (60.0, "red"), (90.0, "red")]
    bands = hs.collapse_bands(pts, gap_s=95)
    assert bands == [{"from": 0.0, "to": 30.0, "state": "green"},
                     {"from": 60.0, "to": 90.0, "state": "red"}]


def t_collapse_bands_breaks_on_gap_even_if_equal():
    # A long gap (relay down) must end the band, not bridge it.
    pts = [(0.0, "green"), (30.0, "green"), (1000.0, "green")]
    bands = hs.collapse_bands(pts, gap_s=95)
    assert len(bands) == 2
    assert bands[0] == {"from": 0.0, "to": 30.0, "state": "green"}
    assert bands[1] == {"from": 1000.0, "to": 1000.0, "state": "green"}


def t_derive_bands_covers_all_band_fields():
    samples = [_snap(ts=0.0, level="green", a="serving"),
               _snap(ts=30.0, level="red", a="idle")]
    bands = hs.derive_bands(samples)
    assert set(bands) == set(hs.BAND_FIELDS)
    assert bands["health_level"] == [{"from": 0.0, "to": 0.0, "state": "green"},
                                     {"from": 30.0, "to": 30.0, "state": "red"}]
    assert bands["feed_a_state"][0]["state"] == "serving"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_health_store.py`
Expected: FAIL — `AttributeError: module ... has no attribute 'collapse_bands'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/scripts/health_store.py`:

```python
def collapse_bands(points, gap_s=GAP_S):
    """Collapse [(ts, value), ...] (ascending) into contiguous bands
    {from,to,state}. A new band starts when the value changes OR the gap to the
    previous sample exceeds gap_s (the relay was down — never bridge it)."""
    bands = []
    for ts, val in points:
        if bands and bands[-1]["state"] == val and (ts - bands[-1]["to"]) <= gap_s:
            bands[-1]["to"] = ts
        else:
            bands.append({"from": ts, "to": ts, "state": val})
    return bands


def derive_bands(samples, gap_s=GAP_S):
    """One band list per BAND_FIELD, from ordered samples."""
    return {field: collapse_bands([(s["ts"], s.get(field)) for s in samples], gap_s)
            for field in BAND_FIELDS}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_health_store.py` → `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/health_store.py tests/test_health_store.py
git commit -m "feat(health): derive status bands (collapse equal states, break on gaps)"
```

---

## Task 3: derive_incidents — non-green health spans with labels

**Files:**
- Modify: `src/scripts/health_store.py`
- Test: `tests/test_health_store.py`

**Interfaces:**
- Consumes: `collapse_bands`, sample dicts (`health_level`, `health_reasons`).
- Produces: `derive_incidents(samples, gap_s=GAP_S) -> list[{ts,end,duration_s,severity,label}]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_health_store.py`:

```python
def t_derive_incidents_from_non_green_health_bands():
    samples = [
        _snap(ts=0.0, level="green"),
        _snap(ts=30.0, level="yellow") | {"health_reasons": ["cookies stale"]},
        _snap(ts=60.0, level="yellow") | {"health_reasons": ["cookies stale"]},
        _snap(ts=90.0, level="green"),
        _snap(ts=120.0, level="red") | {"health_reasons": ["Feed B down — lost the live stream"]},
    ]
    inc = hs.derive_incidents(samples)
    assert len(inc) == 2
    assert inc[0]["severity"] == "yellow"
    assert inc[0]["ts"] == 30.0 and inc[0]["end"] == 60.0 and inc[0]["duration_s"] == 30.0
    assert inc[0]["label"] == "cookies stale"
    assert inc[1]["severity"] == "red"
    assert inc[1]["label"].startswith("Feed B down")


def t_derive_incidents_empty_when_all_green():
    assert hs.derive_incidents([_snap(ts=0.0), _snap(ts=30.0)]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_health_store.py`
Expected: FAIL — no `derive_incidents`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/scripts/health_store.py`:

```python
def _incident_label(level, reasons):
    if reasons:
        return reasons[0]
    return {"red": "CRITICAL", "yellow": "DEGRADED"}.get(level, level or "")


def derive_incidents(samples, gap_s=GAP_S):
    """Every non-green aggregate-health band becomes an incident with the reasons
    recorded at the band's start as its label."""
    reasons_at = {s["ts"]: s.get("health_reasons") or [] for s in samples}
    out = []
    for b in collapse_bands([(s["ts"], s.get("health_level")) for s in samples], gap_s):
        if b["state"] == "green" or b["state"] is None:
            continue
        out.append({"ts": b["from"], "end": b["to"],
                    "duration_s": b["to"] - b["from"], "severity": b["state"],
                    "label": _incident_label(b["state"], reasons_at.get(b["from"]))})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_health_store.py` → `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/health_store.py tests/test_health_store.py
git commit -m "feat(health): derive incident timeline from non-green health bands"
```

---

## Task 4: numeric_series + downsample

**Files:**
- Modify: `src/scripts/health_store.py`
- Test: `tests/test_health_store.py`

**Interfaces:**
- Consumes: sample dicts, `NUMERIC_FIELDS`, `DEFAULT_MAX_POINTS`.
- Produces: `downsample(pairs, max_points) -> list[(ts,val)]` (last value per time-bucket), `numeric_series(samples, max_points=DEFAULT_MAX_POINTS) -> dict[field -> {t:[...], v:[...]}]` (None values dropped per metric).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_health_store.py`:

```python
def t_downsample_passthrough_when_small():
    pairs = [(0.0, 1.0), (1.0, 2.0)]
    assert hs.downsample(pairs, 10) == pairs


def t_downsample_buckets_to_max_keeping_last_per_bucket():
    pairs = [(float(i), float(i)) for i in range(10)]
    out = hs.downsample(pairs, 5)
    assert len(out) <= 5
    assert out[-1] == (9.0, 9.0)             # newest point always kept


def t_numeric_series_drops_none_and_splits_t_v():
    samples = [_snap(ts=0.0) | {"cookies_age_h": None},
               _snap(ts=30.0) | {"cookies_age_h": 4.0}]
    series = hs.numeric_series(samples)
    assert set(series) == set(hs.NUMERIC_FIELDS)
    assert series["cookies_age_h"] == {"t": [30.0], "v": [4.0]}   # None dropped
    assert series["source_last_ok_age_s"]["t"] == [0.0, 30.0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_health_store.py`
Expected: FAIL — no `downsample`/`numeric_series`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/scripts/health_store.py`:

```python
import math


def downsample(pairs, max_points):
    """Bucket [(ts,val), ...] to <= max_points, taking the last point in each
    time-bucket (cheap, monotonic-x safe). The newest point is always retained."""
    n = len(pairs)
    if max_points <= 0 or n <= max_points:
        return list(pairs)
    bucket = math.ceil(n / max_points)
    out = []
    for i in range(0, n, bucket):
        out.append(pairs[min(i + bucket - 1, n - 1)])
    return out


def numeric_series(samples, max_points=DEFAULT_MAX_POINTS):
    """Per numeric field: drop None, downsample, split into parallel t/v arrays."""
    out = {}
    for field in NUMERIC_FIELDS:
        pairs = [(s["ts"], s.get(field)) for s in samples if s.get(field) is not None]
        pairs = downsample(pairs, max_points)
        out[field] = {"t": [p[0] for p in pairs], "v": [p[1] for p in pairs]}
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_health_store.py` → `ALL PASS`. (Move `import math` to the top of the file with the other imports; rerun.)

- [ ] **Step 5: Commit**

```bash
git add src/scripts/health_store.py tests/test_health_store.py
git commit -m "feat(health): numeric series + bucket downsampling"
```

---

## Task 5: prune — retention window

**Files:**
- Modify: `src/scripts/health_store.py`
- Test: `tests/test_health_store.py`

**Interfaces:**
- Produces: `prune(conn, retention_days=DEFAULT_RETENTION_DAYS, now=None) -> int` (rows deleted).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_health_store.py`:

```python
def t_prune_deletes_older_than_retention():
    with tempfile.TemporaryDirectory() as d:
        conn = hs.open_db(os.path.join(d, "h.db")); hs.migrate(conn)
        now = 10_000_000.0
        old = now - 40 * 86400        # 40 days old
        recent = now - 1 * 86400      # 1 day old
        hs.record(conn, _snap(ts=old), "periodic")
        hs.record(conn, _snap(ts=recent), "periodic")
        deleted = hs.prune(conn, retention_days=30, now=now)
        assert deleted == 1
        rows = hs.query_range(conn, 0, 1e12)
        assert [r["ts"] for r in rows] == [recent]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_health_store.py`
Expected: FAIL — no `prune`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/scripts/health_store.py` (add `import time` at the top with the other imports):

```python
def prune(conn, retention_days=DEFAULT_RETENTION_DAYS, now=None):
    """Delete samples older than retention_days. Returns the deleted row count."""
    now = time.time() if now is None else now
    cutoff = now - retention_days * 86400
    cur = conn.execute("DELETE FROM samples WHERE ts < ?", (cutoff,))
    conn.commit()
    return cur.rowcount
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_health_store.py` → `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/health_store.py tests/test_health_store.py
git commit -m "feat(health): retention pruning by age"
```

---

## Task 6: export_jsonl + import_jsonl (merge, dedup by ts)

**Files:**
- Modify: `src/scripts/health_store.py`
- Test: `tests/test_health_store.py`

**Interfaces:**
- Produces: `export_jsonl(conn, frm=0) -> list[str]` (one JSON object per line, ascending), `import_jsonl(conn, lines) -> int` (rows newly inserted; idempotent — duplicate `(ts, kind)` ignored).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_health_store.py`:

```python
def t_export_then_import_into_fresh_db_roundtrips():
    with tempfile.TemporaryDirectory() as d:
        a = hs.open_db(os.path.join(d, "a.db")); hs.migrate(a)
        hs.record(a, _snap(ts=100.0, level="green"), "periodic")
        hs.record(a, _snap(ts=130.0, level="red"), "event")
        lines = hs.export_jsonl(a)
        assert len(lines) == 2 and lines[0].startswith("{")

        b = hs.open_db(os.path.join(d, "b.db")); hs.migrate(b)
        n = hs.import_jsonl(b, lines)
        assert n == 2
        rows = hs.query_range(b, 0, 1e12)
        assert [r["ts"] for r in rows] == [100.0, 130.0]
        assert rows[1]["kind"] == "event"


def t_import_is_idempotent_dedup_by_ts_kind():
    with tempfile.TemporaryDirectory() as d:
        a = hs.open_db(os.path.join(d, "a.db")); hs.migrate(a)
        hs.record(a, _snap(ts=100.0), "periodic")
        lines = hs.export_jsonl(a)
        assert hs.import_jsonl(a, lines) == 0       # re-importing changes nothing
        assert len(hs.query_range(a, 0, 1e12)) == 1


def t_import_skips_malformed_lines():
    with tempfile.TemporaryDirectory() as d:
        b = hs.open_db(os.path.join(d, "b.db")); hs.migrate(b)
        good = hs.export_jsonl_line({"ts": 5.0, "kind": "periodic", "health_level": "green",
                                     "health_reasons": []})
        n = hs.import_jsonl(b, [good, "{not json", "", "null", "[]"])
        assert n == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_health_store.py`
Expected: FAIL — no `export_jsonl`/`import_jsonl`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/scripts/health_store.py`:

```python
def export_jsonl_line(row):
    """Serialize one sample dict (health_reasons may be a list) to a JSON line."""
    r = {c: row.get(c) for c in COLUMNS}
    r["kind"] = row.get("kind")
    reasons = row.get("health_reasons")
    r["health_reasons"] = reasons if isinstance(reasons, list) else []
    return json.dumps(r, ensure_ascii=False)


def export_jsonl(conn, frm=0):
    """All samples with ts >= frm as JSON lines, ascending."""
    cur = conn.execute("SELECT * FROM samples WHERE ts>=? ORDER BY ts ASC", (frm,))
    out = []
    for row in cur.fetchall():
        out.append(export_jsonl_line(_row_to_dict(row)))
    return out


def import_jsonl(conn, lines):
    """Merge JSON-Lines samples into the DB, deduplicated by (ts, kind). Malformed
    lines are skipped (never fatal). Returns the number of rows newly inserted."""
    inserted = 0
    placeholders = ",".join("?" for _ in COLUMNS)
    for line in lines:
        line = (line or "").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict) or obj.get("ts") is None or obj.get("kind") is None:
            continue
        dup = conn.execute("SELECT 1 FROM samples WHERE ts=? AND kind=? LIMIT 1",
                           (obj["ts"], obj["kind"])).fetchone()
        if dup:
            continue
        s = dict(obj)
        s["health_reasons"] = json.dumps(s.get("health_reasons") or [])
        values = [s.get(col) for col in COLUMNS]
        conn.execute(f"INSERT INTO samples ({','.join(COLUMNS)}) VALUES ({placeholders})",
                     values)
        inserted += 1
    conn.commit()
    return inserted
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_health_store.py` → `ALL PASS`. Then `python3 tools/lint.py`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/health_store.py tests/test_health_store.py
git commit -m "feat(health): JSON-Lines export + dedup merge import"
```

---

## Task 7: HealthStore wrapper + Relay snapshot + heartbeat sampling

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add `HealthStore` near `ChatStore` ~line 1273; add `Relay._health_snapshot`; hook `_heartbeat_loop` ~2914)
- Test: `tests/test_health_store.py`

**Interfaces:**
- Consumes: everything from `health_store.py`; relay `Feed`/`Relay` internals (`self.feeds`, `self.pov`, `feed_health_state`, `cookie_health`, `self.health_level`, `self.health_reasons`, `self.mode`, `self.live_feed()`).
- Produces: `class HealthStore` with `record_tick(snapshot, now) -> dict` (kind = `'event'` when STATE_KEY_FIELDS changed vs the last recorded row, else `'periodic'`), `query(frm, to)`, `bands(frm, to)`, `incidents(frm, to)`, `series(frm, to, max_points)`, `prune()`, `export_lines(frm=0)`, `import_lines(lines)`; `Relay._health_snapshot(now) -> dict` (a sample dict matching `health_store.COLUMNS`, minus ts/kind).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_health_store.py` (load the relay module the same way `tests/test_chat.py` does — `m = _load("irofeeds", ("src", "relay", "racecast-feeds.py"))`):

```python
m = _load("irofeeds", ("src", "relay", "racecast-feeds.py"))


def t_healthstore_record_tick_marks_changes_as_events():
    with tempfile.TemporaryDirectory() as d:
        store = m.HealthStore(os.path.join(d, "h.db"))
        r1 = store.record_tick(_snap(ts=0.0, level="green"), now=0.0)
        r2 = store.record_tick(_snap(ts=30.0, level="green"), now=30.0)
        r3 = store.record_tick(_snap(ts=60.0, level="red"), now=60.0)
        assert r1["kind"] == "event"        # first row is always an event (baseline)
        assert r2["kind"] == "periodic"     # unchanged state
        assert r3["kind"] == "event"        # health_level changed
        assert len(store.query(0, 1e12)) == 3


def t_healthstore_bands_incidents_series_smoke():
    with tempfile.TemporaryDirectory() as d:
        store = m.HealthStore(os.path.join(d, "h.db"))
        store.record_tick(_snap(ts=0.0, level="green"), now=0.0)
        store.record_tick(_snap(ts=30.0, level="red") | {"health_reasons": ["Feed B down"]}, now=30.0)
        assert store.bands(0, 1e12)["health_level"][-1]["state"] == "red"
        assert store.incidents(0, 1e12)[0]["severity"] == "red"
        assert "source_last_ok_age_s" in store.series(0, 1e12, 2000)


def t_relay_health_snapshot_has_no_urls_and_all_columns():
    src = m._FakeSource(["u1", "u2", "u3"], [("https://youtu.be/a", "Alice", "1", 2)]) \
        if hasattr(m, "_FakeSource") else None
    # Build a Relay with the test's existing helper if present; else skip gracefully.
    # (Implementer: reuse the Relay construction helper already used by other relay tests.)
    relay = _make_relay(m)
    snap = relay._health_snapshot(now=123.0)
    for col in hs.COLUMNS:
        if col in ("ts", "kind"):
            continue
        assert col in snap, col
    blob = repr(snap).lower()
    assert "http" not in blob and "youtu" not in blob   # redaction
```

Add a small `_make_relay(m)` helper at the top of the test file mirroring the Relay construction used in `tests/test_pov.py`/`tests/test_console_gate.py` (a `FakeSource` of schedule rows + two feed ports + a temp log dir). Keep it minimal — two stints, no live pulls.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_health_store.py`
Expected: FAIL — no `HealthStore` / `_health_snapshot`.

- [ ] **Step 3: Write minimal implementation**

In `src/relay/racecast-feeds.py`, import the store near the other `src/scripts` imports the relay already does (the relay imports sibling scripts via the bundled-path mechanism — match exactly how `chat_admin`/`cue_admin` are imported in this file). Then add `HealthStore` right after the `ChatStore` class (~line 1321):

```python
class HealthStore:
    """Thread-safe wrapper around the SQLite health-history store. One connection
    guarded by a lock (the heartbeat thread writes; request threads read). Marks a
    tick as an 'event' when the categorical state changed since the last row."""

    def __init__(self, path, retention_days=health_store.DEFAULT_RETENTION_DAYS):
        self.path = path
        self.retention_days = retention_days
        self.lock = threading.Lock()
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        except OSError:
            pass
        self.conn = health_store.open_db(self.path)
        health_store.migrate(self.conn)
        self._last_key = None

    @staticmethod
    def _state_key(snapshot):
        return tuple(snapshot.get(f) for f in health_store.STATE_KEY_FIELDS)

    def record_tick(self, snapshot, now=None):
        key = self._state_key(snapshot)
        with self.lock:
            kind = "event" if key != self._last_key else "periodic"
            self._last_key = key
            return health_store.record(self.conn, snapshot, kind, now=now)

    def query(self, frm, to):
        with self.lock:
            return health_store.query_range(self.conn, frm, to)

    def bands(self, frm, to):
        return health_store.derive_bands(self.query(frm, to))

    def incidents(self, frm, to):
        return health_store.derive_incidents(self.query(frm, to))

    def series(self, frm, to, max_points):
        return health_store.numeric_series(self.query(frm, to), max_points)

    def prune(self):
        with self.lock:
            return health_store.prune(self.conn, self.retention_days)

    def export_lines(self, frm=0):
        with self.lock:
            return health_store.export_jsonl(self.conn, frm)

    def import_lines(self, lines):
        with self.lock:
            return health_store.import_jsonl(self.conn, lines)
```

Add `Relay._health_snapshot` (place it next to `_health_facts`, ~line 2880). It mirrors what `status()` already computes but stores NO URLs:

```python
    def _health_snapshot(self, now):
        """A redacted, flat health sample (matches health_store.COLUMNS minus
        ts/kind). No stream URLs / sheet_id — safe to persist and pull."""
        def feed_fields(f):
            return ("stopped" if f.paused else f.phase,
                    1 if (f.dropped and not f.paused) else 0, f.idx + 1)
        a_state, a_down, a_stint = feed_fields(self.feeds["A"])
        b_state, b_down, b_stint = feed_fields(self.feeds["B"])
        ch = cookie_health(self.cookies, now=now)
        live = self.live_feed()
        snap = {"ts": now,
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
                "timer_mode": None, "timer_remaining_s": None,
                "mode": self.mode,
                "live_feed": live, "live_stint": self.feeds[live].idx + 1}
        return snap
```

(Timer fields stay `None` here — the relay's `TimerStore` lives in the handler closure, not on `Relay`; Task 9 fills `timer_mode`/`timer_remaining_s` into the served payload from `timer_store` directly. Sampling timer history is out of scope for v1; the numeric `timer_remaining` chart is fed from the live payload only. If you later move the store onto `Relay`, populate these here.)

Hook `_heartbeat_loop` (~line 2914) — add sampling after the health refresh:

```python
    def _heartbeat_loop(self):
        while not self._hb_stop.is_set():
            now = time.time()
            self._maybe_probe_obs(now)
            level = self._refresh_health(now)["level"]
            if self.health_store is not None:                      # ADDED
                try:                                               # ADDED
                    self.health_store.record_tick(self._health_snapshot(now), now)  # ADDED
                except Exception:                                  # ADDED noqa: BLE001 — sampling is best-effort
                    pass                                           # ADDED
            if health_should_notify(self._notified_level, level):
                self._send_health_webhook(level, self.health_reasons, self._notified_level)
                self._notified_level = level
            self._hb_stop.wait(HEARTBEAT_INTERVAL_S)
```

Initialize `self.health_store = None` in `Relay.__init__` (next to the other optional attributes like the chat/timer wiring) so the attribute always exists; the bootstrap (Task 13) assigns the real store.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_health_store.py` → `ALL PASS`.

- [ ] **Step 5: Run the relay's own suite (no regressions)**

Run: `python3 tests/test_pov.py` and `python3 tests/test_chat.py`
Expected: both `ALL PASS` (heartbeat change is additive + guarded).

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_health_store.py
git commit -m "feat(health): thread-safe HealthStore + relay snapshot + heartbeat sampling"
```

---

## Task 8: console_policy entries (ANY for the page + data)

**Files:**
- Modify: `src/scripts/console_policy.py` (add two entries in `min_capability`, in the race-control region ~line 102)
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: existing `Requirement`, `ANY`, `decide`.
- Produces: `min_capability(["health-monitor"])` and `min_capability(["health-monitor","data"])` both return `Requirement(ANY, False)`. (Takeover is already covered by the generic `takeover/*` rule → `Requirement(PRODUCER, True)`.)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_console.py` (near the race-control policy tests ~line 192). The module is imported there as `cp`:

```python
def t_health_monitor_page_and_data_are_any_authenticated():
    assert cp.min_capability(["health-monitor"]) == cp.Requirement(cp.ANY, False)
    assert cp.min_capability(["health-monitor", "data"]) == cp.Requirement(cp.ANY, False)


def t_decide_health_monitor_allows_any_role():
    for role in (cp.COMMENTATOR, cp.DIRECTOR, cp.PRODUCER, cp.RACE_CONTROL):
        assert cp.decide({role}, ["health-monitor"]) == cp.ALLOW
        assert cp.decide({role}, ["health-monitor", "data"]) == cp.ALLOW
    # An authenticated subject with no resolved role still reaches an ANY route.
    assert cp.decide(set(), ["health-monitor"]) == cp.ALLOW


def t_takeover_health_is_producer_step_up():
    assert cp.min_capability(["takeover", "health"]) == cp.Requirement(cp.PRODUCER, True)
    assert cp.decide({cp.PRODUCER}, ["takeover", "health"], has_step_up=False) == cp.STEP_UP_REQUIRED
    assert cp.decide({cp.PRODUCER}, ["takeover", "health"], has_step_up=True) == cp.ALLOW
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_console.py`
Expected: FAIL — `min_capability(["health-monitor"])` returns `None`.

- [ ] **Step 3: Write minimal implementation**

In `src/scripts/console_policy.py`, add directly below the race-control block (after the `if p == ["race-control"] ...` entry, ~line 102):

```python
    # --- health monitor: read-only dashboard, any authenticated subject (#health) ---
    # Page + its combined data endpoint. Redacted by construction (no stream URLs),
    # so any authenticated console subject may view it — same tier as the cockpit
    # monitors. Takeover/health is the producer+step-up pull, already matched by the
    # generic takeover/* rule above.
    if p == ["health-monitor"] or p == ["health-monitor", "data"]:
        return Requirement(ANY, False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_console.py` → `ALL PASS`. Then `python3 tests/test_console_gate.py` (no regressions yet — gate wiring comes in Task 9).

- [ ] **Step 5: Commit**

```bash
git add src/scripts/console_policy.py tests/test_console.py
git commit -m "feat(health): policy — /health-monitor is any-authenticated"
```

---

## Task 9: Relay routes — page, data, raw, gate branch, takeover rewrite

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`make_handler` signature + closure; `_health_monitor_payload`, `_health_current`, `_health_raw_payload`; `do_GET` root branches; `_console_gate` branch + takeover rewrite)
- Test: `tests/test_console_gate.py`, `tests/test_health_store.py`

**Interfaces:**
- Consumes: `relay.health_store`, `timer_store`, `event_store`, `health_store` constants, `_send`, `_send_page`, `console_policy`.
- Produces (handler methods): `_health_monitor_payload()`, `_health_current()`, `_health_raw_payload()`; `make_handler(..., health_store=None, health_monitor_page_path=None, uplot_dir=None)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_console_gate.py` (it already has `_serve`, `_get`, `_tok`). First extend `_serve` to pass the new params — add to the `make_handler(...)` call in `_serve`:

```python
        health_store=m.HealthStore(os.path.join(LOGDIR, "health.db")),
        health_monitor_page_path=os.path.join(SRC, "console", "health-monitor.html"),
        uplot_dir=os.path.join(SRC, "assets", "vendor", "uplot"),
```

Then add tests:

```python
def t_console_health_monitor_page_any_authenticated():
    srv = _serve(); port = srv.server_address[1]
    try:
        # alice=commentator, bob=director, dave=race_control — all may view.
        for who in ("alice", "bob", "dave"):
            code, body = _get(port, "/console/health-monitor", _tok(who))
            assert code == 200, (who, code)
            assert 'window.RC_API_BASE = "/console"' in body or '__RC_API_BASE__' not in body
        # No token -> 401.
        assert _get(port, "/console/health-monitor", None)[0] in (401, 404)
    finally:
        srv.shutdown()


def t_console_health_monitor_data_shape_and_redaction():
    srv = _serve(); port = srv.server_address[1]
    try:
        code, body = _get(port, "/console/health-monitor/data", _tok("alice"))
        assert code == 200, (code, body)
        blob = json.loads(body)
        for key in ("now", "current", "bands", "incidents", "series"):
            assert key in blob, key
        serialised = json.dumps(blob)
        assert "youtu" not in serialised and "watch?v=" not in serialised   # redaction
    finally:
        srv.shutdown()


def t_takeover_health_requires_step_up_secret():
    srv = _serve(); port = srv.server_address[1]
    try:
        # carol=producer; without the secret header -> step-up (403/401).
        assert _get(port, "/console/takeover/health", _tok("carol"))[0] in (401, 403)
        code, body = _get(port, "/console/takeover/health", _tok("carol"),
                          headers={"X-Console-Secret": SECRET})
        assert code == 200, (code, body)
        # JSON-Lines body (possibly empty) — every non-empty line parses.
        for line in body.splitlines():
            if line.strip():
                json.loads(line)
    finally:
        srv.shutdown()
```

If `_get` does not yet accept a `headers=` kwarg, extend it minimally to merge extra headers (mirror how `tests/test_cockpit.py` passes the `X-Cockpit-Secret`/`X-Console-Secret` header).

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_console_gate.py`
Expected: FAIL — unknown `make_handler` kwargs / 404 on `/console/health-monitor`.

- [ ] **Step 3: Write minimal implementation**

In `make_handler`, add the three params (default `None`) to the signature and capture them in the closure (same place `chat_store`, `race_control_page_path` are captured).

Add the payload helpers inside the handler class (near `_status_payload`, ~line 3790):

```python
        def _health_query_window(self):
            qs = parse_qs(urlparse(self.path).query)
            def _f(name):
                try:
                    return float(qs[name][0])
                except (KeyError, ValueError, IndexError):
                    return None
            frm, to = _f("from"), _f("to")
            try:
                maxn = int(qs["max"][0])
            except (KeyError, ValueError, IndexError):
                maxn = health_store.DEFAULT_MAX_POINTS
            now = time.time()
            if frm is None or to is None:
                to, frm = now, now - health_store.LIVE_WINDOW_S
            return frm, to, maxn, now

        def _health_current(self):
            """Allowlist of the live health fields — NEVER the feed/pov stream URLs
            that relay.status() carries (redaction boundary)."""
            full = relay.status()
            feeds = {k: {"state": v.get("state"), "down": v.get("down"),
                         "stint": v.get("stint"), "state_age_s": v.get("state_age_s")}
                     for k, v in (full.get("feeds") or {}).items()}
            pov = full.get("pov")
            pov_red = None if not pov else {"state": pov.get("state"),
                                            "down": pov.get("down"), "shown": pov.get("shown")}
            return {"health": full.get("health"), "feeds": feeds, "pov": pov_red,
                    "obs": full.get("obs"), "source": full.get("source"),
                    "cookies_health": full.get("cookies_health"),
                    "mode": full.get("mode"), "live": full.get("live"),
                    "timer": timer_store.summary() if timer_store else None,
                    "event_title": event_store.get() if event_store else ""}

        def _health_monitor_payload(self):
            if relay.health_store is None:
                return {"error": "health monitor disabled"}
            frm, to, maxn, now = self._health_query_window()
            store = relay.health_store
            return {"now": now, "from": frm, "to": to,
                    "current": self._health_current(),
                    "bands": store.bands(frm, to),
                    "incidents": store.incidents(frm, to),
                    "series": store.series(frm, to, maxn)}

        def _health_raw_payload(self):
            """JSON-Lines body of raw samples (for takeover/export). Returns a str."""
            if relay.health_store is None:
                return ""
            qs = parse_qs(urlparse(self.path).query)
            try:
                frm = float(qs["from"][0])
            except (KeyError, ValueError, IndexError):
                frm = 0
            return "\n".join(relay.health_store.export_lines(frm))
```

Add a tiny raw-text sender if the handler lacks one (mirror `_send` but `text/plain`):

```python
        def _send_text(self, text, code=200):
            body = (text or "").encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
```

Add the **root** routes in `do_GET` (after the existing root `/status` block, ~line 3840), so the page works on the tailnet unauthenticated like `/panel`:

```python
                if p == ["health-monitor"]:
                    if not health_monitor_page_path:
                        return self._send({"error": "page not found"}, 404)
                    return self._send_page(health_monitor_page_path, "")
                if p == ["health-monitor", "data"]:
                    return self._send(self._health_monitor_payload())
                if p == ["health", "raw"]:
                    return self._send_text(self._health_raw_payload())
```

Add the **console gate** branch in `_console_gate` (mirror the race-control branch, ~line 3691). Place BEFORE the generic decide flow:

```python
            if sub and sub[0] == "health-monitor":
                if console_policy.decide(roles, sub, method, has_step_up) != console_policy.ALLOW:
                    self._send({"error": "forbidden"}, 403)
                    return None
                if sub == ["health-monitor"] and method == "GET":
                    if not health_monitor_page_path:
                        return self._send({"error": "page not found"}, 404)
                    self._send_page(health_monitor_page_path, "/console",
                                    cookie_token=self._cockpit_token(), cookie_path="/console")
                    return None
                if sub == ["health-monitor", "data"] and method == "GET":
                    self._send(self._health_monitor_payload())
                    return None
                return self._send({"error": "not found"}, 404)
```

Add the **takeover rewrite** in the gate's ALLOW region where the other `takeover/*` rewrites live (~line 3746), so `/console/takeover/health` falls through to the root raw handler:

```python
                if sub == ["takeover", "health"]:
                    return ["health", "raw"]         # producer+step-up already verified
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_console_gate.py`
Expected: `ALL PASS`. (The page test will pass once `health-monitor.html` exists; if you run this before Task 11, point `health_monitor_page_path` at an existing page or create a stub `health-monitor.html` containing `window.RC_API_BASE = "__RC_API_BASE__"` first, then build the real page in Task 11.)

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_console_gate.py
git commit -m "feat(health): relay routes — page, /health-monitor/data, /health/raw, takeover"
```

---

## Task 10: Vendor uPlot + asset route

**Files:**
- Create: `src/assets/vendor/uplot/uPlot.iife.min.js`, `src/assets/vendor/uplot/uPlot.min.css`, `src/assets/vendor/uplot/LICENSE`
- Modify: `src/relay/racecast-feeds.py` (asset route under both root and `/console`)
- Test: `tests/test_console_gate.py`

**Interfaces:**
- Produces: `GET /health-monitor/assets/<file>` (and `/console/health-monitor/assets/<file>`) serving the two uPlot files with correct MIME, 404 otherwise.

- [ ] **Step 1: Fetch the vendored files**

Download the pinned release (uPlot 1.6.x, MIT) into `src/assets/vendor/uplot/`:

```bash
mkdir -p src/assets/vendor/uplot
curl -fsSL https://cdn.jsdelivr.net/npm/uplot@1.6.31/dist/uPlot.iife.min.js -o src/assets/vendor/uplot/uPlot.iife.min.js
curl -fsSL https://cdn.jsdelivr.net/npm/uplot@1.6.31/dist/uPlot.min.css   -o src/assets/vendor/uplot/uPlot.min.css
curl -fsSL https://raw.githubusercontent.com/leeoniya/uPlot/1.6.31/LICENSE -o src/assets/vendor/uplot/LICENSE
```

Verify both assets are non-empty and the JS defines `uPlot`:

```bash
test -s src/assets/vendor/uplot/uPlot.iife.min.js && grep -q uPlot src/assets/vendor/uplot/uPlot.iife.min.js && echo OK
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_console_gate.py`:

```python
def t_health_monitor_assets_served():
    srv = _serve(); port = srv.server_address[1]
    try:
        code, body = _get(port, "/health-monitor/assets/uPlot.min.css", None)
        assert code == 200 and body.strip(), code
        # Path traversal is refused.
        assert _get(port, "/health-monitor/assets/../../racecast.py", None)[0] in (400, 404)
    finally:
        srv.shutdown()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 tests/test_console_gate.py`
Expected: FAIL — 404 on the asset.

- [ ] **Step 4: Write minimal implementation**

Add a root route in `do_GET` (next to the health routes) and allow it through the gate as an ANY asset. Reuse the relay's existing static-file/MIME helper if one exists (the relay already serves `/hud/assets/...` and `/overlay/fonts/...` — match that idiom). Minimal standalone version:

```python
                if len(p) == 3 and p[:2] == ["health-monitor", "assets"]:
                    name = p[2]
                    if not uplot_dir or not re.fullmatch(r"[A-Za-z0-9._-]+", name):
                        return self._send({"error": "not found"}, 404)
                    full = os.path.join(uplot_dir, name)
                    try:
                        with open(full, "rb") as fh:
                            data = fh.read()
                    except OSError:
                        return self._send({"error": "not found"}, 404)
                    ctype = "text/css" if name.endswith(".css") else \
                            ("application/javascript" if name.endswith(".js") else "application/octet-stream")
                    self.send_response(200)
                    self.send_header("Content-Type", ctype + "; charset=utf-8")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "max-age=86400")
                    self.end_headers(); self.wfile.write(data)
                    return None
```

For the `/console` path, add `health-monitor/assets` to the ANY-allowed assets: in `console_policy.min_capability`, extend the health-monitor entry:

```python
    if p == ["health-monitor"] or p == ["health-monitor", "data"] or \
       (len(p) == 3 and p[:2] == ["health-monitor", "assets"]):
        return Requirement(ANY, False)
```

and in the gate's `health-monitor` branch, fall through assets to the root handler:

```python
                if len(sub) == 3 and sub[:2] == ["health-monitor", "assets"]:
                    return sub        # served by the root asset route
```

(The filename regex already blocks traversal; the policy regex test in Task 8 should be extended with an assets case — add `assert cp.min_capability(["health-monitor","assets","uPlot.min.css"]) == cp.Requirement(cp.ANY, False)` to `t_health_monitor_page_and_data_are_any_authenticated`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 tests/test_console_gate.py` and `python3 tests/test_console.py`
Expected: both `ALL PASS`.

- [ ] **Step 6: Commit**

```bash
git add src/assets/vendor/uplot src/relay/racecast-feeds.py src/scripts/console_policy.py tests/test_console_gate.py tests/test_console.py
git commit -m "feat(health): vendor uPlot (MIT) + serve /health-monitor/assets"
```

---

## Task 11: The health-monitor.html page

**Files:**
- Create: `src/console/health-monitor.html`
- (Manual visual check; no new automated test beyond the page-serves test from Task 9.)

**Interfaces:**
- Consumes: `GET __RC_API_BASE__ + "/health-monitor/data"`, the uPlot assets, the `__RC_API_BASE__`/`__RC_OAUTH__` shim.

- [ ] **Step 1: Create the page**

Create `src/console/health-monitor.html` modeled on `src/console/console.html` (same `__RC_API_BASE__` shim at the top of `<head>`). Structure:

- `<head>`: `<link rel="stylesheet" href="__RC_API_BASE__/health-monitor/assets/uPlot.min.css">`, then `<script src="__RC_API_BASE__/health-monitor/assets/uPlot.iife.min.js"></script>`. A `<script>window.RC_API_BASE = "__RC_API_BASE__";</script>` shim (same idiom as the other console pages — the gate substitutes `/console`, the root serves `""`).
- Dark dashboard theme (self-contained `<style>`; neutral colors, NOT per-league overlay CSS): green `#2ECC71`, yellow `#F1C40F`, red `#E74C3C` for the band/badge states; gap = transparent.
- **Status header:** a big health badge (`#hm-badge`) + reasons list (`#hm-reasons`), `#hm-title`, `#hm-mode`, `#hm-live`, `#hm-since`.
- **Time-range bar:** buttons `Live · 1h · 6h · 24h · 7d` (each sets `window.range`), a from/to `<input type="datetime-local">` pair + an Apply button. Live mode sets a 5 s `setInterval` refresh; any fixed range clears it and fetches once.
- **Status bands:** for each of `health_level, feed_a_state, feed_b_state, pov_state, obs_reachable, cookies_stale`, render a labelled row of absolutely-positioned `<div>` segments computed from `bands[field]` (left/width = `(from-rangeStart)/(rangeEnd-rangeStart)`), colored by state, with a `title` tooltip `state — HH:MM:SS–HH:MM:SS`. Skip the `pov_state` row when all bands are null.
- **Numeric charts:** one uPlot per `series` key (`source_last_ok_age_s`, `cookies_age_h`, `timer_remaining_s`), built from `{t, v}`. Guard: if uPlot is undefined (asset failed), show a text fallback "charts unavailable".
- **Incident timeline:** a table from `incidents` — local time, severity pill, label, duration (humanized `Nm Ns`). Empty → "No incidents in this range. 🎉".
- Fetch helper: `const API = window.RC_API_BASE || "";` then `fetch(API + "/health-monitor/data?from=..&to=..")`. All text via `textContent` (XSS-safe), like the chat panel.

Keep it one file, vanilla JS, no build step.

- [ ] **Step 2: Verify it serves and renders structure**

Run: `python3 tests/test_console_gate.py`
Expected: `t_console_health_monitor_page_any_authenticated` + `t_console_health_monitor_data_shape_and_redaction` PASS.

- [ ] **Step 3: Manual smoke (optional, local)**

Start a dev relay from `src/` and open `http://127.0.0.1:8088/health-monitor`; confirm the page loads, bands render, charts draw (uses the live window; will be sparse until samples accrue). Note: leave the screenshot capture for Task 16.

- [ ] **Step 4: Commit**

```bash
git add src/console/health-monitor.html
git commit -m "feat(health): health-monitor dashboard page (bands + uPlot + incidents)"
```

---

## Task 12: CLI — `racecast health export|import|pull`

**Files:**
- Modify: `src/racecast.py` (route dispatch ~line 914; `_health_db_path()`; `health_cmd(rest)`; reuse `http_util`)
- Test: `tests/test_racecast.py`

**Interfaces:**
- Consumes: `health_store` (imported as `hsmod`), `http_util`, `_runtime_dir()`.
- Produces: `route()` returns `{"kind":"health","rest":rest}` for `cmd=="health"`; `health_cmd(rest)` handling `export [--from TS] [--out PATH]`, `import <file>`, `pull <ip> [--port N] [--from TS]`; `_health_db_path() -> str`; `HEALTH_VERBS = ("export","import","pull")`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_racecast.py` (it already imports the CLI module; mirror how `chat` routing is tested there):

```python
def t_route_health_subcommand():
    assert rc.route(["health", "export"]) == {"kind": "health", "rest": ["export"]}
    assert rc.route(["health", "pull", "100.64.0.1"]) == {"kind": "health", "rest": ["pull", "100.64.0.1"]}


def t_health_export_import_roundtrip(tmp_path=None):
    import tempfile, os
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "health-history.db")
        conn = rc.hsmod.open_db(db); rc.hsmod.migrate(conn)
        rc.hsmod.record(conn, {"ts": 1.0, "health_level": "green", "health_reasons": []}, "periodic")
        conn.close()
        out = os.path.join(d, "dump.jsonl")
        # Point the CLI at our temp DB via monkeypatching the path resolver.
        rc._health_db_path = lambda: db
        rc.health_cmd(["export", "--out", out])
        assert os.path.exists(out) and os.path.getsize(out) > 0
        # Import into a second DB.
        db2 = os.path.join(d, "h2.db"); rc.hsmod.migrate(rc.hsmod.open_db(db2))
        rc._health_db_path = lambda: db2
        rc.health_cmd(["import", out])
        conn2 = rc.hsmod.open_db(db2)
        assert len(rc.hsmod.query_range(conn2, 0, 1e12)) == 1
```

(If `tests/test_racecast.py` uses a different invocation harness for subcommands, follow that file's existing pattern; the assertions above define the required behavior either way.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — no `health` route / `health_cmd` / `hsmod`.

- [ ] **Step 3: Write minimal implementation**

In `src/racecast.py`: import the store the same way other `src/scripts` modules are imported in this file (e.g. `import health_store as hsmod` via the established import shim). Add to `route()` next to the `chat` case (~line 914):

```python
    if cmd == "health":
        return {"kind": "health", "rest": rest}
```

Add the path helper next to `_chat_path` (~line 1022):

```python
def _health_db_path():
    return os.path.join(_runtime_dir(), "health-history.db")
```

Add the handler modeled on `chat_cmd` (~line 1050):

```python
HEALTH_VERBS = ("export", "import", "pull")


def health_cmd(rest):
    """`racecast health export|import|pull` — move health history across events/machines."""
    verb = rest[0] if rest else None
    if verb not in HEALTH_VERBS:
        sys.exit(f"usage: racecast health {{{'|'.join(HEALTH_VERBS)}}}")
    args = rest[1:]
    db = _health_db_path()

    if verb == "export":
        out, frm = "health-export.jsonl", 0
        if "--out" in args:
            i = args.index("--out")
            if i + 1 >= len(args):
                sys.exit("usage: racecast health export [--from TS] [--out PATH]")
            out = args[i + 1]
        if "--from" in args:
            i = args.index("--from")
            try:
                frm = float(args[i + 1])
            except (IndexError, ValueError):
                sys.exit("racecast: --from requires a numeric epoch value")
        conn = hsmod.open_db(db); hsmod.migrate(conn)
        lines = hsmod.export_jsonl(conn, frm)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + ("\n" if lines else ""))
        print(f"Exported {len(lines)} samples -> {out}")
        return None

    if verb == "import":
        if not args:
            sys.exit("usage: racecast health import <file.jsonl>")
        try:
            with open(args[0], encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except OSError as e:
            sys.exit(f"racecast: could not read {args[0]}: {e}")
        conn = hsmod.open_db(db); hsmod.migrate(conn)
        n = hsmod.import_jsonl(conn, lines)
        print(f"Imported {n} new samples into {db}")
        return None

    if verb == "pull":
        if not args:
            sys.exit("usage: racecast health pull <tailscale-ip> [--port N] [--from TS]")
        host = args[0]
        port = RELAY_PORT
        if "--port" in args[1:]:
            i = args.index("--port", 1)
            try:
                port = int(args[i + 1])
            except (IndexError, ValueError):
                sys.exit("racecast: --port must be an integer")
        frm = 0
        if "--from" in args[1:]:
            i = args.index("--from", 1)
            try:
                frm = float(args[i + 1])
            except (IndexError, ValueError):
                sys.exit("racecast: --from requires a numeric epoch value")
        url = f"http://{host}:{port}/health/raw?from={frm}"
        try:
            with http_util.open_url(url, timeout=5) as resp:
                if resp.status != 200:
                    sys.exit(f"racecast: pull failed — HTTP {resp.status} from {host}")
                body = resp.read().decode("utf-8")
        except Exception as e:
            sys.exit(f"racecast: pull failed — {type(e).__name__}: {e} (local history unchanged)")
        conn = hsmod.open_db(db); hsmod.migrate(conn)
        n = hsmod.import_jsonl(conn, body.splitlines())
        print(f"Pulled {n} new samples from {host}.")
        return None
```

Wire the dispatch where `route()` results are handled (where `kind=="chat"` calls `chat_cmd`): add `if r["kind"] == "health": return health_cmd(r["rest"])`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_racecast.py` → `ALL PASS`. Then `python3 tools/lint.py`.

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(health): racecast health export|import|pull CLI"
```

---

## Task 13: Bootstrap wiring + takeover health pull

**Files:**
- Modify: `src/relay/racecast-feeds.py` (relay `main()`/startup: create `HealthStore`, assign `relay.health_store`, `prune()` on start, pass page/uplot paths + store into `make_handler`)
- Modify: `src/racecast.py` (`event_takeover`: pull `/health/raw` (tailnet) / `/console/takeover/health` (funnel) and merge — mirror the chat/cues pulls)
- Test: covered by Task 7/9 + a takeover smoke assertion in `tests/test_racecast.py` if that file already exercises `event_takeover` helpers; otherwise rely on the gate test from Task 9.

**Interfaces:**
- Consumes: `HealthStore`, `_health_db_path`, `_funnel_takeover_base`, `_takeover_get`, `http_util`, `hsmod`.

- [ ] **Step 1: Relay bootstrap**

In the relay's startup (where `ChatStore`, `TimerStore`, page paths are constructed and passed to `make_handler` — search for the existing `chat_store=` / `race_control_page_path=` wiring):

```python
    health_store_obj = HealthStore(
        os.path.join(state_dir(), "health-history.db"),
        retention_days=int(os.environ.get("RACECAST_HEALTH_RETENTION_DAYS",
                                          health_store.DEFAULT_RETENTION_DAYS)))
    relay.health_store = health_store_obj
    try:
        health_store_obj.prune()        # drop stale rows on start
    except Exception:                   # noqa: BLE001 — best-effort
        pass
```

Resolve the page/uplot paths the same way the other pages are resolved (here-relative or `sys._MEIPASS/src/...`):

```python
    health_monitor_page = _here_path("console", "health-monitor.html")
    uplot_dir = _here_path("assets", "vendor", "uplot")
```

(Use whatever helper the relay already uses to build `cockpit.html` / `race-control.html` paths — match it exactly.) Pass all three into `make_handler(..., health_store=relay.health_store, health_monitor_page_path=health_monitor_page, uplot_dir=uplot_dir)`.

A daily prune: the heartbeat already ticks every 30 s; gate a prune to roughly once a day by tracking `self._last_prune` on the relay and calling `relay.health_store.prune()` when `now - self._last_prune > 86400`. Add inside `_heartbeat_loop` after the sample write:

```python
            if self.health_store is not None and (now - self._last_prune) > 86400:
                try:
                    self.health_store.prune(); self._last_prune = now
                except Exception:        # noqa: BLE001
                    pass
```

Initialize `self._last_prune = 0` in `Relay.__init__`.

- [ ] **Step 2: Takeover pull**

In `src/racecast.py` `event_takeover`, after the cues pull block (mirror it exactly — best-effort, never aborts):

```python
    # Adopt A's health history (#health), like the chat pull — best-effort.
    try:
        if funnel:
            body = _takeover_get_text(base + "/health", secret)
        else:
            with http_util.open_url("http://%s:%d/health/raw" % (host, port), timeout=5) as r:
                body = r.read().decode("utf-8")
        conn = hsmod.open_db(_health_db_path()); hsmod.migrate(conn)
        n = hsmod.import_jsonl(conn, body.splitlines())
        print(f"Pulled {n} health samples from A.")
    except Exception as exc:
        print(f"note: health pull failed ({type(exc).__name__}) — continuing takeover.")
```

`_takeover_get` returns parsed JSON; the health endpoint returns NDJSON text, so add a sibling helper next to `_takeover_get` (~line 1529):

```python
def _takeover_get_text(url, secret=None, timeout=5):
    """GET a (funnel) takeover endpoint that returns text (NDJSON), with step-up."""
    headers = {"X-Console-Secret": secret} if secret else None
    with http_util.open_url(url, headers=headers, timeout=timeout) as r:
        return r.read().decode("utf-8")
```

- [ ] **Step 3: Run the suites**

Run: `python3 tools/run-tests.py`
Expected: full suite `ALL PASS` (this is the CI suite; fixes any wiring regressions now).

- [ ] **Step 4: Commit**

```bash
git add src/relay/racecast-feeds.py src/racecast.py
git commit -m "feat(health): bootstrap store + daily prune + takeover health pull"
```

---

## Task 14: Control Center — card + export/import ops

**Files:**
- Modify: `src/ui/control-center.html` (a "Health Monitor" card: link + export/import controls)
- Modify: `src/ui/ui_server.py` (register `health-export` / `health-import` ops, or POST routes)
- Modify: `src/racecast_ui.py` (op argv builders, if ops are declared there)
- Test: `tests/test_ui_server.py`

**Interfaces:**
- Consumes: the ops/jobs registry (`ctx["ops"]`, `ctx["build_argv"]`, `ctx["jobs"]`) used by `/api/op/<name>`.
- Produces: ops `health-export` → `racecast health export --out <runtime>/health-export.jsonl` and `health-import` → `racecast health import <path>`; a card in the Profile/Home view linking to the relay's `/health-monitor`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ui_server.py` (mirror its existing op/route tests):

```python
def t_health_ops_registered():
    ctx = _make_ctx()           # use the file's existing context/fixture builder
    assert "health-export" in ctx["ops"]
    assert "health-import" in ctx["ops"]
    argv = ctx["build_argv"]("health-export", None)
    assert argv[:2] == ["health", "export"] or "export" in argv


def t_health_import_argv_requires_path():
    ctx = _make_ctx()
    try:
        ctx["build_argv"]("health-import", {})      # missing 'file'
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    argv = ctx["build_argv"]("health-import", {"file": "/tmp/x.jsonl"})
    assert argv[-1] == "/tmp/x.jsonl"
```

(Adapt `_make_ctx()` to the actual fixture name in `tests/test_ui_server.py`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_ui_server.py`
Expected: FAIL — ops not registered.

- [ ] **Step 3: Write minimal implementation**

Register the two ops where the op registry + `build_argv` live (follow the existing op declarations — e.g. how `cookies`/`graphics` ops are declared). `health-export` takes no params; `health-import` requires a `file` param (raise `ValueError` if absent, matching the `build_argv` contract that returns 400 on `ValueError`).

In `src/ui/control-center.html`, add a card (mirror the Relay/Companion rows from `control-center.html:545-567`) in the Profile/Home view:

```html
        <section id="home-health-monitor">
          <div class="row"><span class="name">Health Monitor</span>
            <a class="linkbtn" id="hm-open" target="_blank" rel="noopener">Open monitor ↗</a>
            <span class="dim grow">relay must be running</span>
            <button onclick="runOp('health-export')">Export history</button>
            <button onclick="importHealth()">Import history…</button></div>
        </section>
```

Wire `hm-open`'s href to the relay base + `/health-monitor` (reuse however the existing "Open panel ↗" link is built from the relay address/port). `importHealth()` prompts for a path and calls `runOp('health-import', {file: path})` (reuse the page's existing `runOp` helper that POSTs `/api/op/<name>`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_ui_server.py` → `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/ui/control-center.html src/ui/ui_server.py src/racecast_ui.py tests/test_ui_server.py
git commit -m "feat(health): Control Center card + export/import ops"
```

---

## Task 15: Full suite + lint + build verify

**Files:** none (verification only)

- [ ] **Step 1: Run the whole test suite**

Run: `python3 tools/run-tests.py`
Expected: every test file prints `ALL PASS` / its success line; the runner exits 0.

- [ ] **Step 2: Lint**

Run: `python3 tools/lint.py`
Expected: no findings (fix any with `python3 tools/lint.py --fix` then re-run).

- [ ] **Step 3: Build verify**

Run: `python3 tools/build.py`
Expected: build succeeds; the verify step passes (no secrets, no shell scripts, tokenization intact). Confirm `src/assets/vendor/uplot/` is present in `dist/GT_Racecast_Package/`.

- [ ] **Step 4: Commit (only if any fixups were needed)**

```bash
git add -A
git commit -m "test(health): green suite, lint, build verify"
```

---

## Task 16: Docs + wiki + screenshots

**Files:**
- Modify: `README.md`, `CLAUDE.md` (command list)
- Create/modify: `src/docs/wiki/` page for the Health Monitor + `src/docs/wiki/images/` capture
- Recapture: the Control Center `cc-*.png` that now shows the Health Monitor card

- [ ] **Step 1: Command-list docs**

Add to the `racecast` command list in both `README.md` and `CLAUDE.md`:

```
python3 src/racecast.py health export [--from TS] [--out PATH]   # dump health history to JSON Lines
python3 src/racecast.py health import <file.jsonl>               # merge a health-history dump (dedup by ts)
python3 src/racecast.py health pull <ip> [--port N] [--from TS]  # pull another producer's health history (takeover helper)
```

Add a one-line note in CLAUDE.md's relay section that the relay serves `/health-monitor` (tailnet) + `/console/health-monitor` (Funnel, any-authenticated), backed by `runtime/<profile>/health-history.db`, and that uPlot is vendored under `src/assets/vendor/uplot/` (the deliberate first vendored JS — see the spec).

- [ ] **Step 2: Wiki page**

Add a `src/docs/wiki/Health-Monitor.md` page (mechanism only, per the "never invent crew procedure" rule): what the dashboard shows (bands/charts/incidents), the time-range controls, who can see it (any authenticated `/console` subject), how it persists (SQLite + export/import + takeover pull). Link it from the wiki sidebar/home page where the other operator pages are listed. Run `python3 tests/test_wiki.py` to validate links/anchors.

- [ ] **Step 3: Screenshots (local dev build, no VERSION stamp)**

Capture from a local `src/` dev build (so the version badge stays uniform — see memory):
- The Health Monitor page → `src/docs/wiki/images/health-monitor.png` (element screenshot of the dashboard, framed like the other page images). Seed some samples first so bands/charts/incidents are non-empty (run a dev relay briefly, or import a small synthetic JSONL via `racecast health import`).
- The Control Center view now showing the Health Monitor card → refresh the matching `cc-*.png` (the Profile/Home view image).

Use the Playwright MCP for the element shots, matching the existing image framing.

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md src/docs/wiki/Health-Monitor.md src/docs/wiki/images/health-monitor.png src/docs/wiki/images/cc-*.png
git commit -m "docs(health): command list, wiki page, monitor + Control Center screenshots"
```

- [ ] **Step 5: (Maintainer) publish wiki**

Wiki publishing stays a separate step (`python3 tools/sync-wiki.py`) — do NOT run it as part of this change; the committed images + page are the deliverable.

---

## Self-Review

**Spec coverage:**
- Pure SQLite store (schema, record, query, bands, incidents, series, prune, export/import) → Tasks 1–6. ✓
- Heartbeat sampler (periodic + event-on-change), no new thread → Task 7. ✓
- Combined `/health-monitor/data` (current + bands + incidents + series), root + `/console`, ANY gate → Tasks 8, 9. ✓
- `/health/raw` + `/console/takeover/health` (step-up) → Tasks 9 (route + generic takeover policy) + 13 (pull). ✓
- Redaction (no URL columns; allowlisted `current`) → Tasks 1 (`t_schema_has_no_url_columns`), 7 (`_health_snapshot`), 9 (`_health_current`, redaction tests). ✓
- uPlot vendored + status bands + incident timeline + time-range presets/custom → Tasks 10, 11. ✓
- CLI export/import/pull → Task 12. ✓
- Producer handover carry-over (tailnet + funnel) → Task 13. ✓
- Control Center card + export/import → Task 14. ✓
- Retention default 30 / `RACECAST_HEALTH_RETENTION_DAYS` → Tasks 5, 13. ✓
- Docs + wiki + screenshots (CLAUDE.md requirement) → Task 16. ✓

**Known spec deviations (intentional, called out):**
- Sampling granularity = heartbeat tick (≤30 s); event rows are marked, not second-accurate (spec updated to match).
- Numeric series are per-metric `{t,v}` (own x-axis, Nones dropped) rather than one shared `t` column — cleaner with sparse metrics; payload documents both `bands`, `incidents`, `series`.
- `source` is rendered as a numeric chart (`source_last_ok_age_s`), not a status band; bands cover `health/feed_a/feed_b/pov/obs/cookies`. (Spec listed `source` under bands; a numeric chart is the honest representation — no invented stale threshold.)
- Timer history is not sampled in v1 (`timer_*` columns stay NULL from the heartbeat); the live `timer` shows in `current` and the `timer_remaining_s` chart is sparse until/unless the store is moved onto `Relay`. Noted in Task 7.

**Placeholder scan:** No TBD/TODO; every code step has concrete code. The `_make_relay`/`_make_ctx`/`_get(headers=)` test helpers reference existing fixtures in their target files (the implementer adapts to the real fixture names) — these are the only "match the existing pattern" notes and are unavoidable without copying each whole test file.

**Type consistency:** `record_tick`/`record` return a row dict with `health_reasons` as a list; `query_range`/`query` parse `health_reasons` back to a list; `export_jsonl_line` emits it as a list; `import_jsonl` re-encodes. `COLUMNS` order is the single source for insert/select/export. `derive_bands` returns `{field: [bands]}`; `HealthStore.bands` forwards it. The payload keys (`now/from/to/current/bands/incidents/series`) are identical across Task 9's builder, the page (Task 11), and the gate tests (Task 9).
