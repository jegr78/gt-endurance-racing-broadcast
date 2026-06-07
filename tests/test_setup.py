#!/usr/bin/env python3
"""Stdlib unit checks for the panel sheet-control additions.
Run: python3 tests/test_setup.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "iro-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


# ---------- webhook response check (v2 action echo) ----------

def t_webhook_ok_plain():
    ok, err = m.check_webhook_response(b'{"ok": true}')
    assert ok and err is None


def t_webhook_ok_with_echo():
    ok, err = m.check_webhook_response(b'{"ok": true, "action": "setup", "v": 2}',
                                       expected_action="setup")
    assert ok and err is None


def t_webhook_v1_script_is_outdated_for_actions():
    # a v1 timer-only script answers ok WITHOUT the action echo -> not a success
    ok, err = m.check_webhook_response(b'{"ok": true}', expected_action="setup")
    assert not ok and "outdated" in err


def t_webhook_error_body():
    ok, err = m.check_webhook_response(b'{"error": "bad key"}')
    assert not ok and "bad key" in err


def t_webhook_garbage_body():
    ok, err = m.check_webhook_response(b"<html>Apps Script error page</html>")
    assert not ok and "did not confirm" in err
    ok, err = m.check_webhook_response(b"")
    assert not ok


# ---------- schedule rows (url + name) ----------

SCHED_CSV = ('"https://www.youtube.com/watch?v=abc",Matt\n'
             '"UCLA_DiR1FfKNvjuUpBHmylQ",NASA\n'
             '"UCoMdktPbSTixAyNGwb-UYkQ"\n')


def t_parse_rows_url_and_name():
    rows = m.ScheduleSource._parse_rows(SCHED_CSV)
    assert rows == [("https://www.youtube.com/watch?v=abc", "Matt"),
                    ("UCLA_DiR1FfKNvjuUpBHmylQ", "NASA"),
                    ("UCoMdktPbSTixAyNGwb-UYkQ", "")], rows


def t_parse_rows_empty_is_none():
    assert m.ScheduleSource._parse_rows("url\n\n") is None


def t_parse_csv_still_returns_urls():
    items = m.ScheduleSource._parse_csv(SCHED_CSV)
    assert items[0] == "https://www.youtube.com/watch?v=abc"
    assert len(items) == 3


def t_schedule_source_get_rows():
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    s = m.ScheduleSource("http://sched", _os.path.join(d, "cache.txt"), None)
    s.fetch = lambda timeout=15: m.ScheduleSource._parse_rows(SCHED_CSV)
    assert s.refresh() is True
    assert s.get() == ["https://www.youtube.com/watch?v=abc",
                       "UCLA_DiR1FfKNvjuUpBHmylQ", "UCoMdktPbSTixAyNGwb-UYkQ"]
    assert s.get_rows()[1] == ("UCLA_DiR1FfKNvjuUpBHmylQ", "NASA")


def t_parse_rows_url_not_first_column():
    text = "Commentator,Channel\nMatt,UCaaaaaaaaaaaaaaaaaaaaaa\nNASA,UCbbbbbbbbbbbbbbbbbbbbbb\n"
    rows = m.ScheduleSource._parse_rows(text)
    assert rows == [("UCaaaaaaaaaaaaaaaaaaaaaa", ""),
                    ("UCbbbbbbbbbbbbbbbbbbbbbb", "")], rows


# ---------- SetupControl ----------

OVERLAY_CSV = (",Stint,Intro,,,,,,,\n,Streamer,JeGr,,,,,,,\n"
               ",Session,Warmup,,,,,,,\n,Race Control,,,,,,,,\n")
CONFIG_CSV = ("Stints,Streamers,Session,Race Control,Teams,Brand Name\n"
              "Stint 1,JeGr,Qualifier,Formation Lap,T #1,Porsche\n"
              "Stint 2,GT45,Race,Final Lap,T #2,BMW\n")


def _hs_stub():
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    hs = m.HudSource("http://overlay", "http://config",
                     _os.path.join(d, "hud.cache.json"))
    hs._fetch = lambda url, timeout=10: OVERLAY_CSV if url == "http://overlay" else CONFIG_CSV
    hs.refresh()
    return hs


def _ctl(pushes, response=b'{"ok": true, "action": "%s", "v": 2}'):
    hs = _hs_stub()
    ctl = m.SetupControl("http://push", hs)
    def fake_post(url, payload, timeout=10):
        pushes.append(payload)
        return response % payload["action"].encode() if b"%s" in response else response
    m.post_webhook, orig = fake_post, m.post_webhook
    return ctl, hs, orig


def t_set_field_unknown_field_and_value():
    ctl = m.SetupControl("http://push", _hs_stub())
    assert "error" in ctl.set_field("nope", "x")
    assert "error" in ctl.set_field("streamer", "Not In Vocab")
    assert "error" in ctl.set_field("streamer", "")   # only racecontrol clears


def t_set_field_requires_webhook():
    r = m.SetupControl(None, _hs_stub()).set_field("streamer", "GT45")
    assert "error" in r and "webhook" in r["error"]


def t_set_field_sets_override_and_pushes():
    pushes = []
    ctl, hs, orig = _ctl(pushes)
    try:
        r = ctl.set_field("streamer", "GT45", now=1000.0)
        assert r.get("ok") and r.get("pending")
        assert hs.data(now=1001.0)["streamer"] == "GT45"   # echo immediate
        ctl._push_setup("Streamer", "GT45")                # the thread body, run sync
        assert pushes[-1] == {"action": "setup", "fields": {"Streamer": "GT45"}}
        assert ctl.push_status == "ok"
    finally:
        m.post_webhook = orig


def t_clear_racecontrol_allowed():
    pushes = []
    ctl, hs, orig = _ctl(pushes)
    try:
        r = ctl.set_field("racecontrol", "", now=1000.0)
        assert r.get("ok")
        ctl._push_setup("Race Control", "")
        assert pushes[-1]["fields"] == {"Race Control": ""}
    finally:
        m.post_webhook = orig


def t_v1_script_reported_outdated():
    pushes = []
    ctl, hs, orig = _ctl(pushes, response=b'{"ok": true}')   # no action echo
    try:
        ctl._push_setup("Streamer", "GT45")
        assert ctl.push_status == "failed"
        assert "outdated" in ctl.last_error
    finally:
        m.post_webhook = orig


def t_schedule_set_validates_and_pushes():
    pushes = []
    ctl, hs, orig = _ctl(pushes)
    try:
        assert "error" in ctl.schedule_set("x", url="https://youtu.be/a")
        assert "error" in ctl.schedule_set(0, url="https://youtu.be/a")
        assert "error" in ctl.schedule_set(1, url="not a url")
        r = ctl.schedule_set(2, url="https://www.youtube.com/watch?v=x", name="Matt")
        assert r.get("ok"), r
        assert pushes[-1] == {"action": "schedule", "row": 2,
                              "url": "https://www.youtube.com/watch?v=x", "name": "Matt"}
    finally:
        m.post_webhook = orig


def t_pov_set_pushes():
    pushes = []
    ctl, hs, orig = _ctl(pushes)
    try:
        assert "error" in ctl.pov_set("nonsense")
        r = ctl.pov_set("https://www.youtube.com/watch?v=p")
        assert r.get("ok"), r
        assert pushes[-1] == {"action": "pov", "url": "https://www.youtube.com/watch?v=p"}
    finally:
        m.post_webhook = orig


def t_setup_data_shape():
    ctl = m.SetupControl(None, _hs_stub())
    d = ctl.data()
    assert d["fields"] == {"stint": "Intro", "streamer": "JeGr",
                           "session": "Warmup", "racecontrol": ""}
    assert d["options"]["racecontrol"] == ["Formation Lap", "Final Lap"]
    assert d["pending"] == [] and d["push"] == "disabled"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
