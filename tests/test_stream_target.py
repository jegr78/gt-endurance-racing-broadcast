#!/usr/bin/env python3
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
import stream_target as st


def t_resolve_part_ref_matches_case_insensitively():
    rows = [{"part": "1", "stream_key": "key1"}, {"part": "Q", "stream_key": "keyq"}]
    assert st.resolve_part_ref(rows, "1") == "key1"
    assert st.resolve_part_ref(rows, " q ") == "keyq"


def t_resolve_part_ref_missing_or_blank_is_empty():
    rows = [{"part": "1", "stream_key": ""}, {"part": "2", "stream_key": "key2"}]
    assert st.resolve_part_ref(rows, "1") == ""      # matched row, no ref
    assert st.resolve_part_ref(rows, "9") == ""      # no such part
    assert st.resolve_part_ref([], "1") == ""


def t_event_platform_first_non_empty():
    assert st.event_platform([("youtube", "chan")]) == "youtube"
    assert st.event_platform([("", "chan"), ("Twitch", "c2")]) == "twitch"
    assert st.event_platform([]) == ""


def t_parse_stream_key_response_ok():
    body = b'{"ok": true, "action": "get_stream_key", "key": "live_x"}'
    assert st.parse_stream_key_response(body) == ("live_x", "")


def t_parse_stream_key_response_error_when_not_ok():
    body = b'{"ok": false, "action": "get_stream_key", "error": "no key for ref \'key1\'"}'
    key, err = st.parse_stream_key_response(body)
    assert key == "" and "no key" in err


def t_parse_stream_key_response_outdated_script_no_action_echo():
    body = b'{"ok": true, "key": "x"}'          # no action echo -> outdated
    key, err = st.parse_stream_key_response(body)
    assert key == "" and "outdated" in err


def t_parse_stream_key_response_missing_key():
    body = b'{"ok": true, "action": "get_stream_key"}'
    key, err = st.parse_stream_key_response(body)
    assert key == "" and "no key" in err


def t_parse_stream_key_response_malformed_json_is_error_not_crash():
    key, err = st.parse_stream_key_response(b"<html>500</html>")
    assert key == "" and err


def t_parse_stream_key_response_non_dict_json_is_error():
    key, err = st.parse_stream_key_response(b"123")   # valid JSON, not a dict
    assert key == "" and err


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
