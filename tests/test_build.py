#!/usr/bin/env python3
"""Stdlib checks for build.py's secret-pattern verify. Run: python3 tests/test_build.py

Importing build.py only runs its module-level defs (the __main__ guard does not
fire), so this never triggers an actual build."""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "build", os.path.join(ROOT, "tools", "build.py"))
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)


def t_has_appscript_secret_flags_exec_endpoint():
    # the SHEET_PUSH_URL secret class most likely to leak into the OBS json
    assert b.has_appscript_secret("https://script.google.com/macros/s/ABC123def/exec")
    assert b.has_appscript_secret(
        '{"url": "https://script.googleusercontent.com/macros/echo?key=secret"}')
    assert b.has_appscript_secret("anything .../exec trailing")


def t_has_appscript_secret_flags_key_query():
    assert b.has_appscript_secret("https://api.example.com/data?key=AIzaSyXXXX")
    assert b.has_appscript_secret("https://x/y?a=1&key=zzz")


def t_has_appscript_secret_clean_text_passes():
    assert not b.has_appscript_secret("http://127.0.0.1:8088/hud")
    assert not b.has_appscript_secret("__RACECAST_GRAPHICS__/Overlay.png")
    assert not b.has_appscript_secret("http://127.0.0.1:8088/timer/data")
    assert not b.has_appscript_secret("")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
