#!/usr/bin/env python3
"""Stdlib unit checks for the Crew roster + role resolution (#216 phase 1).
Run: python3 tests/test_roles.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_crew_truthy_allowlist():
    for yes in ("x", "X", " yes ", "TRUE", "1", "y", "✓"):
        assert m._crew_truthy(yes), yes
    for no in ("", " ", "0", "no", "false", "-", "maybe"):
        assert not m._crew_truthy(no), no


def t_parse_header_mode_locates_columns_by_name():
    text = "Name,Director,Producer\nAlice,X,X\nBob,x,\nCarol,,\n"
    rows = m.CrewSource._parse_rows(text)
    assert rows == [("Alice", True, True),
                    ("Bob", True, False),
                    ("Carol", False, False)], rows


def t_parse_header_mode_columns_may_move_and_extras_ignored():
    # Producer left of Director, plus an unrelated Contact column.
    text = "Name,Contact,Producer,Director\nAlice,@a,X,\n"
    rows = m.CrewSource._parse_rows(text)
    assert rows == [("Alice", False, True)], rows


def t_parse_skips_blank_name_rows():
    text = "Name,Director,Producer\n,X,\nBob,X,\n"
    rows = m.CrewSource._parse_rows(text)
    assert rows == [("Bob", True, False)], rows


def t_parse_positional_fallback_no_header():
    # No recognized name header -> col0=name, col1=director, col2=producer.
    text = "Alice,X,X\nBob,x,\n"
    rows = m.CrewSource._parse_rows(text)
    assert rows == [("Alice", True, True), ("Bob", True, False)], rows


def t_parse_positional_fallback_skips_headerlike_first_row():
    # A header-like first row (col1/col2 are header words) is dropped even when
    # the name header itself is unrecognized.
    text = "Person?,Director,Producer\nAlice,X,\n"
    rows = m.CrewSource._parse_rows(text)
    assert rows == [("Alice", True, False)], rows


def t_parse_empty_returns_none():
    assert m.CrewSource._parse_rows("") is None
    assert m.CrewSource._parse_rows("\n") is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
