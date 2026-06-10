#!/usr/bin/env python3
"""Stdlib unit checks for the profile-aware config resolver.
Run: python3 tests/test_config.py"""
import importlib.util, os, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "racecast_config", os.path.join(ROOT, "src", "scripts", "config.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def _mkroot(td):
    """A fake project root: a dir holding a .env.example marker."""
    root = os.path.join(td, "proj")
    os.makedirs(root)
    open(os.path.join(root, ".env.example"), "w").close()
    return root


def t_find_project_root_finds_marker_above_start():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        start = os.path.join(root, "src", "scripts")
        os.makedirs(start)
        assert m.find_project_root(start) == root


def t_find_project_root_returns_none_when_no_marker_within_bound():
    with tempfile.TemporaryDirectory() as td:
        deep = os.path.join(td, "a", "b", "c", "d", "e")
        os.makedirs(deep)
        # no marker anywhere -> None (bounded walk, never an unrelated parent)
        assert m.find_project_root(deep, max_levels=4) is None


def t_parse_env_text_ignores_blanks_comments_and_strips_quotes():
    text = '\n'.join([
        "# a comment",
        "",
        "SHEET_ID=abc123",
        '  NAME = "IRO Endurance" ',
        "URL='https://x/y?key=z'",   # '=' inside the value is kept
        "noequals",
    ])
    got = m.parse_env_text(text)
    assert got == {
        "SHEET_ID": "abc123",
        "NAME": "IRO Endurance",
        "URL": "https://x/y?key=z",
    }


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
