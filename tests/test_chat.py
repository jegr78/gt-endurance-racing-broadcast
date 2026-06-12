#!/usr/bin/env python3
"""Stdlib unit checks for the crew chat. Run: python3 tests/test_chat.py"""
import importlib.util
import json
import os
import tempfile

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


def t_sanitize_message_folds_unicode_line_separators():
    # Chat lines are single-row: NEL/LS/PS must collapse to a space, not break.
    msg = ca.sanitize_message({"ts": 1.0, "user": "a",
                               "text": "one two three\x85four"})
    assert msg["text"] == "one two three four"


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


def t_validate_payload_ok():
    payload = {"messages": [{"ts": 2.0, "user": "B", "text": "two"},
                            {"ts": 1.0, "user": "A", "text": "one"}]}
    msgs = ca.validate_payload(payload)
    assert [x["ts"] for x in msgs] == [1.0, 2.0]          # sorted by ts
    assert all(set(x) == {"ts", "user", "text"} for x in msgs)


def t_validate_payload_empty_is_valid():
    assert ca.validate_payload({"messages": []}) == []


def t_validate_payload_drops_bad_entries_keeps_good():
    payload = {"messages": [{"ts": 1.0, "user": "A", "text": "ok"},
                            {"user": "A", "text": "no ts"},
                            "garbage"]}
    msgs = ca.validate_payload(payload)
    assert len(msgs) == 1 and msgs[0]["text"] == "ok"


def t_validate_payload_caps_to_max_messages():
    payload = {"messages": [{"ts": float(i), "user": "A", "text": str(i)}
                            for i in range(ca.MAX_MESSAGES + 50)]}
    msgs = ca.validate_payload(payload)
    assert len(msgs) == ca.MAX_MESSAGES
    assert msgs[-1]["text"] == str(ca.MAX_MESSAGES + 49)   # newest kept


def t_validate_payload_rejects_malformed_shape():
    for bad in (None, [], 5, "x", {"messages": 5}, {"messages": {"a": 1}}, {}):
        try:
            ca.validate_payload(bad)
            raise AssertionError(bad)
        except ValueError:
            pass


def t_write_then_load_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "chat.json")
        msgs = [{"ts": 1.0, "user": "A", "text": "one"}]
        ca.write_messages(path, msgs)
        assert ca.load_messages(path) == msgs


def t_load_missing_or_corrupt_returns_empty():
    with tempfile.TemporaryDirectory() as d:
        assert ca.load_messages(os.path.join(d, "nope.json")) == []
        bad = os.path.join(d, "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        assert ca.load_messages(bad) == []


def t_load_sanitizes_hand_edited_file():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "chat.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"messages": [{"ts": 1.0, "user": "A", "text": "hi"},
                                    {"user": "no ts", "text": "drop"}]}, fh)
        assert ca.load_messages(path) == [{"ts": 1.0, "user": "A", "text": "hi"}]


def t_write_is_atomic_no_partial_temp_left():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "chat.json")
        ca.write_messages(path, [{"ts": 1.0, "user": "A", "text": "x"}])
        assert set(os.listdir(d)) == {"chat.json"}   # no leftover *.tmp


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
