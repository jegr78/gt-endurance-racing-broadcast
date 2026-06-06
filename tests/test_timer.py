#!/usr/bin/env python3
"""Stdlib unit checks for the relay race timer. Run: python3 tests/test_timer.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "iro-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_parse_duration():
    assert m.parse_duration("6:00:00") == 21600
    assert m.parse_duration("06:00:00") == 21600
    assert m.parse_duration("0:00:30") == 30
    assert m.parse_duration("24:00:00") == 86400
    assert m.parse_duration(" 1:02:03 ") == 3723
    assert m.parse_duration("100:00:00") is None   # 3-digit hours rejected
    for bad in ("", None, "90", "1:2", "1:60:00", "1:00:60", "abc", "-1:00:00"):
        assert m.parse_duration(bad) is None, bad


def t_format_duration():
    assert m.format_duration(21600) == "6:00:00"
    assert m.format_duration(3723) == "1:02:03"
    assert m.format_duration(0) == "0:00:00"
    assert m.format_duration(86400) == "24:00:00"
    assert m.format_duration(3723.9) == "1:02:03"   # truncates float


def t_parse_utc_ts():
    # canonical ISO, Apps Script toISOString (fractional), gviz-reformatted
    assert m.parse_utc_ts("2026-06-13T20:00:00Z") == 1781380800.0
    assert m.parse_utc_ts("2026-06-13T20:00:00.000Z") == 1781380800.0
    assert m.parse_utc_ts("2026-06-13 20:00:00") == 1781380800.0
    for bad in ("", None, "tomorrow", "2026-06-13", "20:00:00"):
        assert m.parse_utc_ts(bad) is None, bad


def t_iso_utc_roundtrip():
    assert m.iso_utc(1781380800.0) == "2026-06-13T20:00:00Z"
    assert m.parse_utc_ts(m.iso_utc(1781380800.0)) == 1781380800.0


TIMER_CSV = (
    "Race End (UTC),2026-06-13T20:00:00Z\n"
    "Duration,6:00:00\n"
    "Visible,FALSE\n"
    "Updated (UTC),2026-06-13T13:59:58Z\n"
)


def t_parse_timer_tab():
    st = m.parse_timer_tab(TIMER_CSV)
    assert st["end"] == 1781380800.0
    assert st["duration"] == 21600
    assert st["visible"] is False
    assert st["updated"] == 1781359198.0


def t_parse_timer_tab_defaults_and_garbage():
    # empty/missing values fall back to the default state fields; never throws
    st = m.parse_timer_tab("Race End (UTC),\nDuration,\nVisible,\n")
    assert st["end"] is None and st["duration"] == 21600
    assert st["visible"] is True and st["updated"] == 0.0
    st = m.parse_timer_tab("")
    assert st["end"] is None
    st = m.parse_timer_tab("garbage,x\nmore,y\n")
    assert st["end"] is None and st["visible"] is True
    # label match is case-insensitive; gviz may reformat the ISO timestamp
    st = m.parse_timer_tab("race end (utc),2026-06-13 20:00:00\n")
    assert st["end"] == 1781380800.0


def t_timer_mode():
    base = {"end": 1000.0, "duration": 21600, "visible": True, "updated": 0.0}
    assert m.timer_mode(dict(base, visible=False), 500.0) == "hidden"
    assert m.timer_mode(dict(base, end=None), 500.0) == "prestart"
    assert m.timer_mode(base, 500.0) == "running"
    assert m.timer_mode(base, 1000.0) == "finished"
    assert m.timer_mode(base, 2000.0) == "finished"
    # hidden wins over everything
    assert m.timer_mode(dict(base, end=None, visible=False), 0.0) == "hidden"


def t_merge_timer_states_newest_wins():
    local = {"end": 1.0, "duration": 60, "visible": True, "updated": 100.0}
    sheet = {"end": 2.0, "duration": 90, "visible": False, "updated": 200.0}
    assert m.merge_timer_states(local, sheet) == sheet
    assert m.merge_timer_states(sheet, local) == sheet     # order-insensitive
    # tie -> first arg (local) wins; sheet None -> local
    tie = dict(sheet, updated=100.0)
    assert m.merge_timer_states(local, tie) == local
    assert m.merge_timer_states(local, None) == local


def _store(tmp=None, push_url=None, csv_url="http://sheet"):
    import tempfile, os as _os
    tmp = tmp or tempfile.mkdtemp()
    return m.TimerStore(csv_url, push_url, _os.path.join(tmp, "timer.json")), tmp


def t_timerstore_actions_update_state_and_stamp():
    ts, _ = _store()
    ts.set_duration(7200, now=900.0)
    assert ts.state["duration"] == 7200 and ts.state["updated"] == 900.0
    ts.start(now=1000.0)
    assert ts.state["end"] == 1000.0 + 7200
    assert ts.state["updated"] == 1000.0
    ts.adjust(-60)
    assert ts.state["end"] == 1000.0 + 7200 - 60
    ts.hide(); assert ts.state["visible"] is False
    ts.show(); assert ts.state["visible"] is True
    ts.stop(); assert ts.state["end"] is None


def t_timerstore_adjust_requires_running():
    ts, _ = _store()
    r = ts.adjust(60)
    assert "error" in r and ts.state["end"] is None


def t_timerstore_persists_and_reloads():
    import os as _os
    ts, tmp = _store()
    ts.set_duration(3600); ts.start(now=5000.0); ts.hide()
    ts2, _ = _store(tmp=tmp)
    assert ts2.state["end"] == 5000.0 + 3600
    assert ts2.state["duration"] == 3600
    assert ts2.state["visible"] is False
    assert _os.path.exists(_os.path.join(tmp, "timer.json"))


def t_timerstore_refresh_adopts_newer_sheet():
    ts, _ = _store()
    ts.set_duration(3600)                       # local write, updated = now
    newer = m.iso_utc(ts.state["updated"] + 100)
    ts._fetch = lambda url, timeout=10: (
        f"Race End (UTC),2026-06-13T20:00:00Z\nDuration,4:00:00\n"
        f"Visible,TRUE\nUpdated (UTC),{newer}\n")
    assert ts.refresh() is True
    assert ts.state["end"] == 1781380800.0 and ts.state["duration"] == 14400


def t_timerstore_refresh_keeps_newer_local():
    ts, _ = _store()
    ts._fetch = lambda url, timeout=10: (
        "Race End (UTC),2026-06-13T20:00:00Z\nDuration,4:00:00\n"
        "Visible,TRUE\nUpdated (UTC),2000-01-01T00:00:00Z\n")
    ts.refresh()
    ts.set_duration(3600)                       # local now newer than sheet
    ts.refresh()
    assert ts.state["duration"] == 3600         # stale sheet did not revert it


def t_timerstore_refresh_failure_keeps_state():
    ts, _ = _store()
    ts.set_duration(3600)
    def boom(url, timeout=10):
        raise RuntimeError("sheet down")
    ts._fetch = boom
    assert ts.refresh() is False
    assert ts.state["duration"] == 3600 and ts.last_error


def t_timerstore_push_payload_and_status():
    ts, _ = _store(push_url="http://push?key=k")
    sent = []
    ts._post = lambda url, body: sent.append((url, body))
    ts._spawn_push = ts._push                   # synchronous for the test
    ts.set_duration(7200); ts.start(now=1000.0)
    url, body = sent[-1]
    import json as _json
    p = _json.loads(body)
    assert url == "http://push?key=k"
    assert p == {"end": m.iso_utc(8200.0), "duration": "2:00:00", "visible": "TRUE"}
    assert ts.push_status == "ok"
    def fail(url, body):
        raise RuntimeError("403")
    ts._post = fail
    ts.hide()
    assert ts.push_status == "failed"


def t_timerstore_push_disabled_without_url():
    ts, _ = _store(push_url=None)
    ts.set_duration(7200)
    assert ts.push_status == "disabled"


def t_timerstore_data_contract():
    ts, _ = _store()
    d = ts.data(now=123.0)
    assert d["mode"] == "prestart" and d["visible"] is True
    assert d["end"] is None and d["duration_s"] == m.TIMER_DEFAULT_DURATION
    assert d["server_now"] == 123.0
    assert d["sync"]["push"] == "disabled"
    assert set(d["sync"]) == {"push", "sheet_last_ok_age_s", "last_error"}


def t_timerstore_summary():
    ts, _ = _store()
    assert ts.summary() == {"mode": "prestart", "visible": True,
                            "remaining_s": None, "push": "disabled"}
    ts.set_duration(60, now=10.0); ts.start(now=10.0)
    # anchor is long past against the real clock -> finished, clamped to 0
    s = ts.summary()
    assert s["mode"] == "finished" and s["remaining_s"] == 0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
