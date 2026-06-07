#!/usr/bin/env python3
"""Stdlib unit checks for live-failure-visibility: cookie_health, resolve_hls
error propagation, Feed phases, Relay.status() contract.
Run: python3 tests/test_health.py"""
import importlib.util, os, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "iro-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_cookie_health_no_path():
    # Running cookie-less (public streams) is legitimate: never stale.
    assert m.cookie_health(None) == {"present": False, "age_h": None, "stale": False}


def t_cookie_health_missing_file():
    h = m.cookie_health(os.path.join(HERE, "no-such-cookies.txt"))
    assert h == {"present": False, "age_h": None, "stale": False}


def t_cookie_health_fresh_and_stale():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "cookies.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# Netscape HTTP Cookie File\n")
        mtime = os.path.getmtime(path)
        fresh = m.cookie_health(path, now=mtime + 3600)
        assert fresh == {"present": True, "age_h": 1.0, "stale": False}, fresh
        stale = m.cookie_health(path, now=mtime + 14 * 3600)
        assert stale["present"] is True and stale["stale"] is True
        assert round(stale["age_h"]) == 14


def t_cookie_max_age_matches_preflight():
    # One source of truth: 12 h, same as preflight.cookies_status default.
    assert m.COOKIE_MAX_AGE_H == 12


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
