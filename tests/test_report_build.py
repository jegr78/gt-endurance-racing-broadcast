#!/usr/bin/env python3
"""Unit checks for the pure post-event report builder (stdlib only)."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# report_build imports health_store by module name, so put src/scripts on sys.path.
import sys
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
rb = _load("report_build", ("src", "scripts", "report_build.py"))


def _sample(ts, **kw):
    row = {"ts": ts, "kind": "periodic", "health_level": "green",
           "health_reasons": [], "feed_a_down": 0, "feed_b_down": 0,
           "live_stint": None, "live_feed": None}
    row.update(kw)
    return row


def t_select_session_single_run():
    ts = [100.0, 130.0, 160.0, 190.0]
    assert rb.select_session(ts, gap_s=1800) == (100.0, 190.0)


def t_select_session_splits_on_big_gap():
    # two runs separated by a 2000s gap (> SESSION_GAP_S) -> only the last run
    ts = [100.0, 130.0, 5000.0, 5030.0, 5060.0]
    assert rb.select_session(ts, gap_s=1800) == (5000.0, 5060.0)


def t_select_session_handover_gap_stays_one_session():
    # a 4-min handover gap (< 1800s) does NOT split the event
    ts = [100.0, 130.0, 400.0, 430.0]
    assert rb.select_session(ts, gap_s=1800) == (100.0, 430.0)


def t_select_session_empty():
    assert rb.select_session([], gap_s=1800) == (None, None)


def t_bucket_samples_collapses_concurrent():
    # two machines sampling ~same 30s window -> one row per 30s bucket (last wins)
    samples = [_sample(0.0, health_level="green"), _sample(10.0, health_level="yellow"),
               _sample(30.0, health_level="green"), _sample(40.0, health_level="red")]
    out = rb.bucket_samples(samples, bucket_s=30)
    assert [s["ts"] for s in out] == [10.0, 40.0], out


def t_build_report_uptime_and_feeds():
    samples = [_sample(0.0), _sample(30.0, health_level="yellow", feed_a_down=1),
               _sample(60.0, health_level="green"), _sample(90.0)]
    rep = rb.build_report(samples, [], {}, "Test Event", (0.0, 90.0), now=1000.0)
    assert rep["header"]["duration_s"] == 90.0
    # green for [0-30] and [60-90] = 60s of 90s -> 66.7%
    assert rep["header"]["uptime_pct"] == 66.7, rep["header"]
    feed_a = next(f for f in rep["feeds"] if f["feed"] == "A")
    assert feed_a["drops"] == 1, rep["feeds"]


def t_build_report_on_air_names_and_fallback():
    samples = [_sample(0.0, live_stint=1), _sample(30.0, live_stint=1),
               _sample(60.0, live_stint=2)]
    rep = rb.build_report(samples, [], {1: "Alice", 2: "Bob"},
                          "E", (0.0, 60.0), now=1000.0)
    names = {c["name"]: c["seconds"] for c in rep["on_air"]["commentators"]}
    assert names.get("Alice") == 60.0, rep["on_air"]
    assert "Bob" in names, rep["on_air"]
    assert rep["on_air"]["resolved"] is True
    # empty map -> "Stint N" fallback + resolved False
    rep2 = rb.build_report(samples, [], {}, "E", (0.0, 60.0), now=1000.0)
    assert any(c["name"] == "Stint 1" for c in rep2["on_air"]["commentators"]), rep2
    assert rep2["on_air"]["resolved"] is False


def t_build_report_producer_handover_from_events():
    samples = [_sample(0.0), _sample(30.0)]
    events = [{"ts": 15.0, "type": "takeover", "producer": "B",
               "metadata": {"from": "A", "stint": 2}}]
    rep = rb.build_report(samples, events, {}, "E", (0.0, 30.0), now=1000.0)
    assert rep["overlap_approximate"] is True
    assert rep["producer_handovers"] == [{"ts": 15.0, "from": "A", "to": "B", "stint": 2}]


def t_build_report_quality_none_when_empty():
    samples = [_sample(0.0), _sample(30.0)]  # no v3 quality columns set
    rep = rb.build_report(samples, [], {}, "E", (0.0, 30.0), now=1000.0)
    assert rep["quality"] is None
    samples2 = [_sample(0.0, stream_kbps=6000.0), _sample(30.0, stream_kbps=4000.0)]
    rep2 = rb.build_report(samples2, [], {}, "E", (0.0, 30.0), now=1000.0)
    assert rep2["quality"]["stream_kbps_peak"] == 6000.0, rep2["quality"]


def t_render_html_is_self_contained():
    samples = [_sample(0.0, live_stint=1), _sample(30.0, live_stint=1, feed_a_down=1),
               _sample(60.0, health_level="red")]
    rep = rb.build_report(samples, [], {1: "Alice"}, "Grand Prix", (0.0, 60.0), now=1000.0)
    html = rb.render_html(rep)
    assert html.startswith("<!doctype html>")
    assert "Grand Prix" in html
    assert "Alice" in html
    # self-contained: no external references (dotless marker avoids the CodeQL
    # incomplete-url-substring rule that has bitten test asserts before)
    assert "http" + "://" not in html, "external URL leaked into report"
    assert "https" + "://" not in html
    assert "Feed reliability" in html
    assert "Incident" in html


def t_render_summary_text():
    samples = [_sample(0.0), _sample(30.0)]
    rep = rb.build_report(samples, [], {}, "My Event", (0.0, 30.0), now=1000.0)
    txt = rb.render_summary_text(rep)
    assert "My Event" in txt
    assert "uptime" in txt.lower()


def t_report_filename():
    assert rb.report_filename("Grand Prix #3", "2026-07-01") == "2026-07-01-grand-prix-3.html"
    assert rb.report_filename("", "2026-07-01") == "2026-07-01-report.html"


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")


if __name__ == "__main__":
    run()
