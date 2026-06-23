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
