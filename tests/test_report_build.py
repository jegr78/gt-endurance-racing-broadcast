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


def t_feed_stats_interval_weighted_downtime():
    # ts 0, 30, 60 with feed_a_down=0,1,0 → down band [30,60] → downtime 30s
    samples = [_sample(0.0, feed_a_down=0), _sample(30.0, feed_a_down=1),
               _sample(60.0, feed_a_down=0)]
    rep = rb.build_report(samples, [], {}, "E", (0.0, 60.0), now=1000.0)
    feed_a = next(f for f in rep["feeds"] if f["feed"] == "A")
    assert feed_a["drops"] == 1, feed_a
    assert feed_a["downtime_s"] == 30.0, feed_a
    assert feed_a["longest_outage_s"] == 30.0, feed_a


def t_fill_gaps_does_not_bridge_relay_down_gap():
    # Contiguous green [0,30], then a ~11-min relay-down hole, then green [700,730],
    # all within one session. The hole must NOT count as green -> uptime well below 100%.
    samples = [_sample(0.0), _sample(30.0),
               _sample(700.0), _sample(730.0)]
    rep = rb.build_report(samples, [], {}, "E", (0.0, 730.0), now=1000.0)
    assert rep["header"]["uptime_pct"] < 100.0, rep["header"]
    # green wall-clock is the two contiguous 30s intervals (~60s of 730s), NOT the whole span
    assert rep["header"]["uptime_pct"] <= 20.0, rep["header"]


def t_report_collects_and_renders_substitutions():
    samples = [_sample(100.0), _sample(160.0)]
    events = [
        {"ts": 130.0, "type": "feed_substitution",
         "metadata": {"feed": "A", "stint": 2, "reason": "A dropped"}},
        {"ts": 150.0, "type": "feed_substitution", "metadata": {"feed": "B", "stint": 3}},
        {"ts": 140.0, "type": "takeover", "producer": "B", "metadata": {"from": "A", "stint": 2}},
    ]
    names = {2: "Ann", 3: "Bob"}   # name_for_stint is a DICT, keyed 1-based
    rep = rb.build_report(samples, events, names, "6h Spa", (100.0, 160.0), now=200.0)
    subs = rep["substitutions"]
    assert [s["feed"] for s in subs] == ["A", "B"]
    assert subs[0] == {"ts": 130.0, "feed": "A", "stint": 2, "streamer": "Ann", "reason": "A dropped"}
    assert subs[1]["streamer"] == "Bob" and subs[1]["reason"] == ""
    html = rb.render_html(rep)
    assert "Stream substitutions" in html and "Ann" in html and "A dropped" in html
    # empty case renders no section
    rep0 = rb.build_report(samples, [], {}, "", (100.0, 160.0), now=200.0)
    assert rep0["substitutions"] == []
    assert "Stream substitutions" not in rb.render_html(rep0)


def t_build_report_no_mutation_on_repeated_call():
    # build_report must not mutate shared state: two calls on the same samples must
    # yield identical health_bands (no accumulating dict mutation).
    samples = [_sample(0.0), _sample(30.0, health_level="yellow"),
               _sample(60.0, health_level="green"), _sample(90.0)]
    rep1 = rb.build_report(samples, [], {}, "E", (0.0, 90.0), now=1000.0)
    snapshot = [dict(b) for b in rep1["health_bands"]]
    rep2 = rb.build_report(samples, [], {}, "E", (0.0, 90.0), now=1000.0)
    assert rep1["health_bands"] == rep2["health_bands"], (
        "second call produced different health_bands", rep1["health_bands"], rep2["health_bands"])
    assert rep1["health_bands"] == snapshot, "first call's health_bands were mutated by second call"


def t_fmt_seconds():
    import time as _t
    # _fmt_dur keeps seconds even at hour scale
    assert rb._fmt_dur(3725) == "1h 2m 5s"
    assert rb._fmt_dur(125) == "2m 5s"
    assert rb._fmt_dur(5) == "5s"
    # _fmt_clock shows HH:MM:SS
    ts = _t.mktime((2026, 7, 5, 15, 17, 9, 0, 0, -1))
    assert rb._fmt_clock(ts) == "15:17:09"
    assert rb._fmt_clock(None) == "—"


def t_on_air_windows_and_exclusion():
    # part events define the on-air window; obs_stream is the fallback
    ev = [{"ts": 100, "type": "part_start", "metadata": {"index": 1}},
          {"ts": 400, "type": "part_end", "metadata": {"index": 1}}]
    assert rb.on_air_windows(ev, 500) == [(100, 400)]
    assert rb.windows_total_s([(100, 400)]) == 300
    ev2 = [{"ts": 100, "type": "obs_stream_start"}, {"ts": 300, "type": "obs_stream_stop"}]
    assert rb.on_air_windows(ev2, 500) == [(100, 300)]
    assert rb.on_air_windows([], 500) is None
    # unclosed part_start closes at session_end
    assert rb.on_air_windows([{"ts": 100, "type": "part_start"}], 500) == [(100, 500)]


def t_build_report_excludes_off_air():
    def s(ts, lvl):
        return {"ts": ts, "health_level": lvl, "health_reasons": [],
                "live_stint": 1, "feed_a_down": 0, "feed_b_down": 0}
    # off-air red BEFORE the part window must not count; in-window green = 100% uptime
    samples = [s(50, "red"), s(100, "green"), s(130, "green"), s(160, "green")]
    events = [{"ts": 100, "type": "part_start", "metadata": {"index": 1}},
              {"ts": 160, "type": "part_end", "metadata": {"index": 1}}]
    rep = rb.build_report(samples, events, {}, "T", (50, 160), 200)
    assert rep["header"]["uptime_pct"] == 100.0
    assert rep["header"]["on_air_s"] == 60
    assert rep["incidents"] == []          # the pre-window red is excluded
    # timeline lists the part boundaries
    tl = rep["broadcast_timeline"]
    assert [(r["ts"], r["label"]) for r in tl] == [(100, "Part 1 started"), (160, "Part 1 ended")]
    html = rb.render_html(rep)
    assert "Broadcast timeline" in html and "Part 1 started" in html
    assert ">On air<" in html


def t_build_report_legacy_no_windows():
    # no part/obs_stream events -> whole-session behaviour (off-air counts)
    def s(ts, lvl):
        return {"ts": ts, "health_level": lvl, "health_reasons": ["off air"],
                "live_stint": 1, "feed_a_down": 0, "feed_b_down": 0}
    samples = [s(0, "green"), s(30, "red"), s(60, "green")]
    rep = rb.build_report(samples, [], {}, "T", (0, 60), 100)
    assert rep["header"]["on_air_s"] == 60          # falls back to full duration
    assert len(rep["incidents"]) == 1               # off-air still counted


def t_report_discord_fields():
    rep = {"header": {"uptime_pct": 98.0, "on_air_s": 3600, "duration_s": 7200,
                      "start": 0, "end": 7200}, "incidents": [1, 2]}
    f = dict(rb.report_discord_fields(rep))
    assert f["Uptime"] == "98.0%"
    assert f["On air"] == "1h 0m 0s"
    assert f["Incidents"] == "2"
    assert f["Session length"] == "2h 0m 0s"
    assert "Window" in f


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")


if __name__ == "__main__":
    run()
