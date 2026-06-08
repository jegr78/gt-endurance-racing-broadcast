#!/usr/bin/env python3
"""Stdlib unit checks for the POV additions. Run: python3 tests/test_pov.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "iro-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_parse_one_url():
    items = m.ScheduleSource._parse_csv("url\nhttps://www.youtube.com/watch?v=abc123\n")
    assert items == ["https://www.youtube.com/watch?v=abc123"], items


def t_parse_empty_is_none():
    assert m.ScheduleSource._parse_csv("url\n\n") is None


def t_pov_format_constant():
    assert m.YTDLP_FORMAT_POV == "b[height<=720]/b"


def t_feed_paused_returns_none():
    f = m.Feed("POV", 53003, 0, lambda: ["https://youtu.be/x"], HERE)
    f.paused = True
    assert f.current_channel() == (None, 0)
    f.paused = False
    ch, i = f.current_channel()
    assert ch == "https://youtu.be/x" and i == 0


def t_feed_has_fmt_attr():
    f = m.Feed("POV", 53003, 0, lambda: [], HERE, fmt="b[height<=720]/b")
    assert f.fmt == "b[height<=720]/b"


def t_current_channel_idles_past_end():
    # idx beyond the schedule -> idle (None), NOT a clamp onto the last stint
    f = m.Feed("B", 53002, 1, lambda: ["https://youtu.be/only"], HERE)
    assert f.current_channel() == (None, 1)        # one link, B on slot 2 -> idle
    f2 = m.Feed("B", 53002, 0, lambda: ["https://youtu.be/only"], HERE)
    assert f2.current_channel() == ("https://youtu.be/only", 0)


def t_set_index_allows_one_past_end_for_idle():
    f = m.Feed("A", 53001, 0, lambda: ["a", "b"], HERE)
    assert f.set_index(2) is True                  # len 2 -> idle slot 2 is reachable
    assert f.idx == 2
    assert f.current_channel() == (None, 2)        # idles
    f2 = m.Feed("A", 53001, 0, lambda: ["a", "b"], HERE)
    assert f2.set_index(99) is True                # clamps to len (idle sentinel) from idx 0
    assert f2.idx == 2
    assert f2.set_index(99) is False               # already at the sentinel -> no-op


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
