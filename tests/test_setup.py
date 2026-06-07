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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
