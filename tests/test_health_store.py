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


def _snap(ts=100.0, level="green", a="serving", b="idle", timer_push="ok"):
    return {"ts": ts, "health_level": level, "health_reasons": [],
            "feed_a_state": a, "feed_a_down": 0, "feed_a_stint": 1,
            "feed_b_state": b, "feed_b_down": 0, "feed_b_stint": 2,
            "pov_state": None, "obs_reachable": 1,
            "source_last_ok_age_s": 2.0, "source_count": 5,
            "cookies_present": 1, "cookies_age_h": 3.0, "cookies_stale": 0,
            "timer_mode": "running", "timer_push": timer_push,
            "mode": "race", "live_feed": "A", "live_stint": 1}


def t_open_migrate_sets_version_and_wal():
    with tempfile.TemporaryDirectory() as d:
        conn = hs.open_db(os.path.join(d, "h.db"))
        try:
            hs.migrate(conn)
            assert conn.execute("PRAGMA user_version").fetchone()[0] == hs.SCHEMA_VERSION
            assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        finally:
            conn.close()


def t_migrate_is_idempotent():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "h.db")
        first = hs.open_db(path)
        hs.migrate(first)
        first.close()
        conn = hs.open_db(path)
        try:
            hs.migrate(conn)            # second run must not raise
            assert conn.execute("PRAGMA user_version").fetchone()[0] == hs.SCHEMA_VERSION
        finally:
            conn.close()


def t_record_then_query_roundtrip_parses_reasons():
    with tempfile.TemporaryDirectory() as d:
        conn = hs.open_db(os.path.join(d, "h.db")); hs.migrate(conn)
        try:
            hs.record(conn, _snap(ts=100.0, level="yellow") | {"health_reasons": ["cookies stale"]}, "event")
            rows = hs.query_range(conn, 0, 1e12)
            assert len(rows) == 1
            assert rows[0]["ts"] == 100.0 and rows[0]["kind"] == "event"
            assert rows[0]["health_level"] == "yellow"
            assert rows[0]["health_reasons"] == ["cookies stale"]   # parsed back to a list
            assert rows[0]["pov_state"] is None
        finally:
            conn.close()


def t_query_range_filters_and_orders():
    with tempfile.TemporaryDirectory() as d:
        conn = hs.open_db(os.path.join(d, "h.db")); hs.migrate(conn)
        try:
            for ts in (300.0, 100.0, 200.0):
                hs.record(conn, _snap(ts=ts), "periodic")
            rows = hs.query_range(conn, 150.0, 250.0)
            assert [r["ts"] for r in rows] == [200.0]
            allrows = hs.query_range(conn, 0, 1e12)
            assert [r["ts"] for r in allrows] == [100.0, 200.0, 300.0]   # ascending
        finally:
            conn.close()


def t_schema_has_no_url_columns():
    # Redaction by construction: a stream URL / sheet_id must never be storable.
    cols = " ".join(hs.COLUMNS).lower()
    for forbidden in ("url", "channel", "sheet", "http"):
        assert forbidden not in cols, forbidden


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


def t_timer_push_is_a_band_field_and_transitions():
    assert "timer_push" in hs.BAND_FIELDS
    samples = [_snap(ts=0.0, timer_push="ok"), _snap(ts=30.0, timer_push="failed")]
    bands = hs.derive_bands(samples)["timer_push"]
    assert [b["state"] for b in bands] == ["ok", "failed"]


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
    assert set(hs.NUMERIC_FIELDS) == {"source_last_ok_age_s", "cookies_age_h"}
    assert series["cookies_age_h"] == {"t": [30.0], "v": [4.0]}   # None dropped
    assert series["source_last_ok_age_s"]["t"] == [0.0, 30.0]


def t_prune_deletes_older_than_retention():
    with tempfile.TemporaryDirectory() as d:
        conn = hs.open_db(os.path.join(d, "h.db")); hs.migrate(conn)
        try:
            now = 10_000_000.0
            old = now - 40 * 86400        # 40 days old
            recent = now - 1 * 86400      # 1 day old
            hs.record(conn, _snap(ts=old), "periodic")
            hs.record(conn, _snap(ts=recent), "periodic")
            deleted = hs.prune(conn, retention_days=30, now=now)
            assert deleted == 1
            rows = hs.query_range(conn, 0, 1e12)
            assert [r["ts"] for r in rows] == [recent]
        finally:
            conn.close()


def t_export_then_import_into_fresh_db_roundtrips():
    with tempfile.TemporaryDirectory() as d:
        a = hs.open_db(os.path.join(d, "a.db")); hs.migrate(a)
        b = hs.open_db(os.path.join(d, "b.db")); hs.migrate(b)
        try:
            hs.record(a, _snap(ts=100.0, level="green"), "periodic")
            hs.record(a, _snap(ts=130.0, level="red"), "event")
            lines = hs.export_jsonl(a)
            assert len(lines) == 2 and lines[0].startswith("{")

            n = hs.import_jsonl(b, lines)
            assert n == 2
            rows = hs.query_range(b, 0, 1e12)
            assert [r["ts"] for r in rows] == [100.0, 130.0]
            assert rows[1]["kind"] == "event"
        finally:
            a.close(); b.close()


def t_import_is_idempotent_dedup_by_ts_kind():
    with tempfile.TemporaryDirectory() as d:
        a = hs.open_db(os.path.join(d, "a.db")); hs.migrate(a)
        try:
            hs.record(a, _snap(ts=100.0), "periodic")
            lines = hs.export_jsonl(a)
            assert hs.import_jsonl(a, lines) == 0       # re-importing changes nothing
            assert len(hs.query_range(a, 0, 1e12)) == 1
        finally:
            a.close()


def t_import_skips_malformed_lines():
    with tempfile.TemporaryDirectory() as d:
        b = hs.open_db(os.path.join(d, "b.db")); hs.migrate(b)
        try:
            good = hs.export_jsonl_line({"ts": 5.0, "kind": "periodic", "health_level": "green",
                                         "health_reasons": []})
            n = hs.import_jsonl(b, [good, "{not json", "", "null", "[]"])
            assert n == 1
        finally:
            b.close()


m = _load("irofeeds", ("src", "relay", "racecast-feeds.py"))

LOGDIR = tempfile.mkdtemp(prefix="racecast-test-health-")
_URLS = [f"https://www.youtube.com/watch?v=stint{i}" for i in range(1, 3)]


class _FakeSrc:
    """Minimal schedule source for _make_relay — two stints, no live pulls."""
    def __init__(self, items): self.items = list(items)
    def get(self): return self.items
    def refresh(self, timeout=None): pass
    def health(self): return {"last_ok_age_s": 1.0, "count": len(self.items)}


def _make_relay(mod):
    """Build a minimal Relay with two stints and a temp log dir."""
    src = _FakeSrc(_URLS)
    return mod.Relay(src, [53001, 53002], LOGDIR)


def t_healthstore_record_tick_marks_changes_as_events():
    with tempfile.TemporaryDirectory() as d:
        store = m.HealthStore(os.path.join(d, "h.db"))
        try:
            r1 = store.record_tick(_snap(ts=0.0, level="green"), now=0.0)
            r2 = store.record_tick(_snap(ts=30.0, level="green"), now=30.0)
            r3 = store.record_tick(_snap(ts=60.0, level="red"), now=60.0)
            assert r1["kind"] == "event"        # first row is always an event (baseline)
            assert r2["kind"] == "periodic"     # unchanged state
            assert r3["kind"] == "event"        # health_level changed
            assert len(store.query(0, 1e12)) == 3
        finally:
            store.close()


def t_healthstore_bands_incidents_series_smoke():
    with tempfile.TemporaryDirectory() as d:
        store = m.HealthStore(os.path.join(d, "h.db"))
        try:
            store.record_tick(_snap(ts=0.0, level="green"), now=0.0)
            store.record_tick(_snap(ts=30.0, level="red") | {"health_reasons": ["Feed B down"]}, now=30.0)
            assert store.bands(0, 1e12)["health_level"][-1]["state"] == "red"
            assert store.incidents(0, 1e12)[0]["severity"] == "red"
            assert "source_last_ok_age_s" in store.series(0, 1e12, 2000)
        finally:
            store.close()


def t_relay_health_snapshot_has_no_urls_and_all_columns():
    relay = _make_relay(m)
    snap = relay._health_snapshot(now=123.0)
    for col in hs.COLUMNS:
        if col in ("ts", "kind"):
            continue
        assert col in snap, col
    assert "timer_push" in snap
    assert "timer_remaining_s" not in snap   # clean break: replaced by timer_push
    blob = repr(snap).lower()
    assert "http" not in blob and "youtu" not in blob   # redaction


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
