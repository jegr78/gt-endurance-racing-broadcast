#!/usr/bin/env python3
"""Stdlib checks for get-cookies helpers. Run: python3 tests/test_cookies.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "get_cookies", os.path.join(ROOT, "src", "relay", "get-cookies.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_hint_locked_db_says_close_browser():
    # Chromium browsers lock their cookie DB while running (yt-dlp #7271).
    err = "ERROR: Could not copy Chrome cookie database. See ... for more info"
    hint = m.failure_hint(err, "chrome")
    assert "close" in hint.lower() and "chrome" in hint.lower()


def t_hint_no_profile_says_installed():
    err = 'ERROR: could not find chrome cookies database in "..."'
    assert "installed" in m.failure_hint(err, "chrome").lower()


def t_hint_decrypt_suggests_firefox():
    err = "ERROR: Failed to decrypt with DPAPI"
    hint = m.failure_hint(err, "chrome")
    assert "firefox" in hint.lower()


def t_hint_default_is_generic():
    for err in ("", None, "ERROR: something else entirely"):
        hint = m.failure_hint(err, "brave")
        assert "brave" in hint.lower() and "logged in" in hint.lower()


def t_relay_cookie_hint_delegates_to_get_cookies():
    # The relay's export_cookies() reuses failure_hint from the sibling
    # get-cookies.py — same hints in both flows, one source of truth.
    rspec = importlib.util.spec_from_file_location(
        "iro_feeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
    relay = importlib.util.module_from_spec(rspec); rspec.loader.exec_module(relay)
    err = "ERROR: Could not copy Chrome cookie database."
    assert relay._cookie_hint(err, "chrome") == m.failure_hint(err, "chrome")


def t_default_runtime_dir_repo_and_dist():
    repo = os.path.join("x", "repo", "src", "relay")
    assert m.default_runtime_dir(repo) == os.path.join("x", "repo", "runtime")
    dist = os.path.join("x", "pkg", "relay")
    assert m.default_runtime_dir(dist) == dist


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
