#!/usr/bin/env python3
"""Stdlib unit checks for relay feed fan-out. Run: python3 tests/test_fanout.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_fanout_enabled_truthy_tokens():
    for v in ("1", "true", "TRUE", "Yes", "on"):
        assert m.fanout_enabled({"RACECAST_FEED_FANOUT": v}) is True, v


def t_fanout_enabled_default_off():
    assert m.fanout_enabled({}) is False
    for v in ("0", "false", "no", "", "off"):
        assert m.fanout_enabled({"RACECAST_FEED_FANOUT": v}) is False, v


def t_feed_stalled_window():
    assert m.feed_stalled(100.0, 100.0 + m.FANOUT_STALL_S + 0.1) is True
    assert m.feed_stalled(100.0, 100.0 + m.FANOUT_STALL_S - 0.1) is False


def t_feed_stalled_none_is_not_stall():
    assert m.feed_stalled(None, 1_000_000.0) is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("all fanout tests passed")
