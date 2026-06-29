#!/usr/bin/env python3
"""Content checks for the Intermission control surfaces. Run: python3 tests/test_intermission.py"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def t_panel_has_intermission_macro():
    html = _read(os.path.join("src", "director", "director-panel.html"))
    assert "INTERMISSION" in html
    assert "Intermission" in html            # scene name in the macro
    assert "Intermission Music" in html      # audio fader input


def t_companion_has_intermission_button():
    raw = _read(os.path.join("src", "companion", "racecast-buttons.companionconfig"))
    json.loads(raw)                           # must stay valid JSON
    assert "Intermission" in raw              # a button/action references the scene


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
