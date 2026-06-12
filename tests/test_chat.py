#!/usr/bin/env python3
"""Stdlib unit checks for the crew chat. Run: python3 tests/test_chat.py"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


ca = _load("chat_admin", ("src", "scripts", "chat_admin.py"))


def t_sanitize_message_basic():
    msg = ca.sanitize_message({"ts": 100.0, "user": "Jens", "text": "hello"})
    assert msg == {"ts": 100.0, "user": "Jens", "text": "hello"}


def t_sanitize_message_trims_and_caps():
    msg = ca.sanitize_message({"ts": 1.0, "user": "x" * 80, "text": "y" * 900})
    assert len(msg["user"]) == ca.MAX_NAME
    assert len(msg["text"]) == ca.MAX_TEXT


def t_sanitize_message_strips_control_chars_keeps_space():
    msg = ca.sanitize_message({"ts": 1.0, "user": "a\x00b", "text": "li\x07ne one"})
    assert msg["user"] == "ab"
    assert msg["text"] == "line one"


def t_sanitize_message_default_name():
    msg = ca.sanitize_message({"ts": 1.0, "user": "   ", "text": "hi"})
    assert msg["user"] == ca.DEFAULT_NAME


def t_sanitize_message_rejects_empty_text():
    for bad in ({"ts": 1.0, "user": "a", "text": "   "},
                {"ts": 1.0, "user": "a"},
                {"ts": 1.0, "user": "a", "text": 5}):
        assert ca.sanitize_message(bad) is None, bad


def t_sanitize_message_rejects_bad_ts():
    for bad in ({"user": "a", "text": "hi"},
                {"ts": "soon", "user": "a", "text": "hi"},
                {"ts": True, "user": "a", "text": "hi"}):
        assert ca.sanitize_message(bad) is None, bad


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
