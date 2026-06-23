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
