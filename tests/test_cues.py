#!/usr/bin/env python3
"""Stdlib unit checks for the director text-cue channel. Run: python3 tests/test_cues.py"""
import importlib.util
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


cu = _load("cue_admin", ("src", "scripts", "cue_admin.py"))


def t_sanitize_cue_basic():
    c = cu.sanitize_cue({"id": 1, "ts": 100.0, "target": "max", "level": "info",
                         "text": "wrap up", "from": "Director", "ack": None})
    assert c == {"id": 1, "ts": 100.0, "target": "max", "level": "info",
                 "text": "wrap up", "from": "Director", "ack": None}


def t_sanitize_cue_caps_and_strips():
    c = cu.sanitize_cue({"id": 2, "ts": 1.0, "target": "all", "level": "critical",
                         "text": "x" * 500, "from": "y" * 80})
    assert len(c["text"]) == cu.MAX_CUE_TEXT
    assert len(c["from"]) == cu.MAX_NAME


def t_sanitize_cue_folds_control_chars():
    c = cu.sanitize_cue({"id": 3, "ts": 1.0, "target": "max", "level": "info",
                         "text": "go\x07 now\nplease"})
    assert c["text"] == "go now please"
    assert c["from"] == "Director"          # blank -> default label


def t_sanitize_cue_rejects_bad():
    for bad in ({"id": 1, "ts": 1.0, "target": "max", "level": "loud", "text": "x"},
                {"id": 1, "ts": 1.0, "target": "", "level": "info", "text": "x"},
                {"id": 1, "ts": 1.0, "target": "max", "level": "info", "text": "   "},
                {"id": 0, "ts": 1.0, "target": "max", "level": "info", "text": "x"},
                {"id": True, "ts": 1.0, "target": "max", "level": "info", "text": "x"},
                {"id": 1, "ts": "x", "target": "max", "level": "info", "text": "x"}):
        assert cu.sanitize_cue(bad) is None, bad


def t_sanitize_cue_ack_shape():
    c = cu.sanitize_cue({"id": 1, "ts": 1.0, "target": "max", "level": "critical",
                         "text": "hot", "ack": {"ts": 9.0, "junk": 1}})
    assert c["ack"] == {"ts": 9.0}
    c2 = cu.sanitize_cue({"id": 1, "ts": 1.0, "target": "max", "level": "critical",
                          "text": "hot", "ack": {"nope": 1}})
    assert c2["ack"] is None


def t_resolve_target_all_and_key():
    norm = lambda s: s.strip().lower().replace(" ", "-")
    assert cu.resolve_target("all", None, norm) == "all"
    assert cu.resolve_target("Max Power", None, norm) == "max-power"
    assert cu.resolve_target("  ", None, norm) is None


def t_resolve_target_on_air():
    norm = lambda s: s.strip().lower()
    assert cu.resolve_target("on-air", "jegr", norm) == "jegr"
    assert cu.resolve_target("on-air", None, norm) is None   # nobody on air


def t_active_cues_info_ttl():
    cues = [{"id": 1, "ts": 100.0, "target": "max", "level": "info",
             "text": "hi", "from": "Director", "ack": None}]
    assert cu.active_cues_for(cues, "max", 120.0, info_ttl=30) == cues   # within TTL
    assert cu.active_cues_for(cues, "max", 130.0, info_ttl=30) == []     # at boundary: expired
    assert cu.active_cues_for(cues, "max", 131.0, info_ttl=30) == []     # expired


def t_active_cues_critical_sticky_until_ack():
    base = {"id": 1, "ts": 1.0, "target": "max", "level": "critical",
            "text": "hot", "from": "Director", "ack": None}
    assert cu.active_cues_for([base], "max", 1e9) == [base]              # sticky forever
    acked = dict(base, ack={"ts": 5.0})
    assert cu.active_cues_for([acked], "max", 1e9) == []                 # acked -> gone


def t_active_cues_target_scope():
    cues = [{"id": 1, "ts": 1.0, "target": "max", "level": "critical", "text": "a",
             "from": "Director", "ack": None},
            {"id": 2, "ts": 1.0, "target": "all", "level": "critical", "text": "b",
             "from": "Director", "ack": None}]
    got = cu.active_cues_for(cues, "ann", 1e9)
    assert [c["id"] for c in got] == [2]          # ann sees only the "all" cue, not max's


def t_prune_drops_stale_keeps_active():
    cues = [{"id": 1, "ts": 1.0, "target": "max", "level": "info", "text": "old",
             "from": "Director", "ack": None},                      # expired info
            {"id": 2, "ts": 1.0, "target": "max", "level": "critical", "text": "ack'd",
             "from": "Director", "ack": {"ts": 2.0}},                # acked critical
            {"id": 3, "ts": 1.0, "target": "max", "level": "critical", "text": "live",
             "from": "Director", "ack": None}]                      # still active
    kept = cu.prune(cues, now=1000.0, info_ttl=30)
    assert [c["id"] for c in kept] == [3]


def t_validate_payload_sorts_and_caps():
    payload = {"cues": [
        {"id": 2, "ts": 2.0, "target": "max", "level": "info", "text": "b"},
        {"id": 1, "ts": 1.0, "target": "max", "level": "info", "text": "a"},
        {"id": 3, "ts": 3.0, "target": "max", "level": "bogus", "text": "drop me"}]}
    clean = cu.validate_payload(payload)
    assert [c["id"] for c in clean] == [1, 2]        # sorted by id, bad entry dropped


def t_validate_payload_rejects_shape():
    for bad in ({}, {"cues": "nope"}, []):
        try:
            cu.validate_payload(bad); raise AssertionError(bad)
        except ValueError:
            pass


def t_write_load_round_trip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "sub", "cues.json")
        cu.write_cues(path, [{"id": 1, "ts": 1.0, "target": "max", "level": "info",
                              "text": "hi", "from": "Director", "ack": None}])
        assert cu.load_cues(path) == [{"id": 1, "ts": 1.0, "target": "max",
                                       "level": "info", "text": "hi",
                                       "from": "Director", "ack": None}]


def t_load_missing_is_empty():
    with tempfile.TemporaryDirectory() as d:
        assert cu.load_cues(os.path.join(d, "nope.json")) == []


def t_apply_pulled_prunes_and_writes():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "cues.json")
        payload = {"cues": [
            {"id": 1, "ts": 1.0, "target": "max", "level": "info", "text": "stale"},
            {"id": 2, "ts": 1.0, "target": "max", "level": "critical", "text": "live"}]}
        n = cu.apply_pulled(path, payload, now=1000.0, info_ttl=30)
        assert n == 1                                  # the expired info pruned out
        assert [c["id"] for c in cu.load_cues(path)] == [2]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
