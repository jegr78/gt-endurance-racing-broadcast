#!/usr/bin/env python3
"""Stdlib unit checks for broadcast Part control (src/scripts/parts.py + relay
PartStore/ProducerSource/apply). Run: python3 tests/test_parts.py"""
import importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import parts as m  # pure module

# relay module (hyphenated filename -> load by path); used from Task 2 on.
_rspec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
R = importlib.util.module_from_spec(_rspec); _rspec.loader.exec_module(R)

ROWS3 = [{"part": "Part 1", "producer": "A", "magicdns": "a", "stream_key": "key1"},
         {"part": "Part 2", "producer": "B", "magicdns": "b", "stream_key": "key2"},
         {"part": "Part 3", "producer": "C", "magicdns": "c", "stream_key": "key3"}]


def t_parts_intent_phrase():
    assert m.parts_intent_phrase("start", 1) == "START PART 1"
    assert m.parts_intent_phrase("end", 3) == "END PART 3"


def t_normalize_intent():
    assert m.normalize_intent("  end   part 2 ") == "END PART 2"
    assert m.normalize_intent("Start Part 1") == "START PART 1"
    assert m.normalize_intent(None) == ""


def t_view_model_ready_offers_start():
    vm = m.parts_view_model(ROWS3, {"index": 1, "live": False}, stream_active=False)
    assert vm["enabled"] and vm["count"] == 3
    assert vm["action"] == "start" and vm["index"] == 1
    assert vm["confirm_phrase"] == "START PART 1" and vm["complete"] is False
    assert len(vm["parts"]) == 3 and vm["parts"][1]["label"] == "Part 2"


def t_view_model_live_offers_end_from_obs():
    # file says not live, OBS says active -> OBS wins (authoritative)
    vm = m.parts_view_model(ROWS3, {"index": 1, "live": False}, stream_active=True)
    assert vm["live"] is True and vm["action"] == "end"
    assert vm["confirm_phrase"] == "END PART 1"


def t_view_model_after_end_offers_next():
    vm = m.parts_view_model(ROWS3, {"index": 2, "live": False}, stream_active=False)
    assert vm["action"] == "start" and vm["index"] == 2
    assert vm["confirm_phrase"] == "START PART 2" and vm["next_index"] == 3


def t_view_model_last_part_complete():
    vm = m.parts_view_model(ROWS3, {"index": 4, "live": False}, stream_active=False)
    assert vm["complete"] is True and vm["action"] is None


def t_view_model_no_parts_disabled():
    vm = m.parts_view_model([], {"index": 1, "live": False}, stream_active=False)
    assert vm["enabled"] is False and vm["action"] is None


def t_view_model_falls_back_to_file_live():
    vm = m.parts_view_model(ROWS3, {"index": 2, "live": True}, stream_active=None)
    assert vm["live"] is True and vm["action"] == "end" and vm["index"] == 2


def t_validate_start_ok():
    ok, res = m.validate_start({"index": 1, "intent": "START PART 1"},
                               {"index": 1, "live": False}, 3)
    assert ok and res == 1


def t_validate_start_bad_phrase():
    ok, res = m.validate_start({"index": 1, "intent": "go"},
                               {"index": 1, "live": False}, 3)
    assert not ok and res[1] == 403


def t_validate_start_wrong_index():
    ok, res = m.validate_start({"index": 2, "intent": "START PART 2"},
                               {"index": 1, "live": False}, 3)
    assert not ok and res[1] == 409


def t_validate_start_bad_index_type():
    ok, res = m.validate_start({"index": "x", "intent": "START PART x"},
                               {"index": 1, "live": False}, 3)
    assert not ok and res[1] == 400


def t_validate_end_ok():
    ok, res = m.validate_end({"intent": "END PART 2"}, {"index": 2, "live": True})
    assert ok and res == 2


def t_validate_end_bad_phrase():
    ok, res = m.validate_end({"intent": "nope"}, {"index": 2, "live": True})
    assert not ok and res[1] == 403


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
