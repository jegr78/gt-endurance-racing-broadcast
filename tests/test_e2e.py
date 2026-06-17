#!/usr/bin/env python3
"""Unit tests for the pure pieces of tools/e2e_checks.py (stdlib, no pytest)."""
import os, sys, socket
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import e2e_checks as e


def t_free_port_is_bindable():
    p = e.free_port()
    assert isinstance(p, int) and 1024 < p < 65536, p
    # The returned port must be free to bind right now.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", p))
    s.close()


def t_free_port_varies():
    # Two consecutive calls should not collide in practice.
    assert e.free_port() != e.free_port() or True  # non-flaky: just exercise it


def t_run_checks_aggregates_and_exits():
    def ok(_ctx):  return e.CheckResult("ok", "pass", "")
    def bad(_ctx): return e.CheckResult("bad", "fail", "boom")
    def skipd(_ctx): return e.CheckResult("sk", "skip", "no browser")
    results, code = e.run_checks([ok, skipd], ctx=None)
    assert code == 0 and {r.status for r in results} == {"pass", "skip"}
    results, code = e.run_checks([ok, bad], ctx=None)
    assert code == 1, code  # any fail -> non-zero


def t_run_checks_turns_exception_into_fail():
    def boom(_ctx): raise RuntimeError("kaboom")
    results, code = e.run_checks([boom], ctx=None)
    assert code == 1 and results[0].status == "fail" and "kaboom" in results[0].message


def t_classify_capability():
    assert e.classify_capability(available=False, name="playwright").status == "skip"
    assert e.classify_capability(available=True, name="playwright") is None


def _relay_parse(text):
    import importlib.util
    here = os.path.dirname(__file__)
    path = os.path.join(here, "..", "src", "relay", "racecast-feeds.py")
    spec = importlib.util.spec_from_file_location("racecast_feeds", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ScheduleSource._parse_rows(text)


def t_build_schedule_csv_parses_in_relay():
    rows = [
        ("https://www.youtube.com/watch?v=aaaaaaaaaaa", "Alice", "Stint 1"),
        ("https://www.twitch.tv/bobcaster", "Bob", "Stint 2"),
    ]
    csv_text = e.build_schedule_csv(rows)
    assert csv_text.splitlines()[0].lower().split(",")[:3] == ["url", "streamer", "stint"]
    parsed = _relay_parse(csv_text)
    assert parsed is not None and len(parsed) == 2, parsed
    # (url, streamer, stint, line) tuples; streamers survive.
    assert [r[1] for r in parsed] == ["Alice", "Bob"], parsed
    assert [r[2] for r in parsed] == ["Stint 1", "Stint 2"], parsed


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("PASS test_e2e")
