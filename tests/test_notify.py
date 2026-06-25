#!/usr/bin/env python3
"""Stdlib unit checks for the pure Discord payload builders (notify.py).
Run: python3 tests/test_notify.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import notify as n


def _embed(payload):
    assert payload["username"] == "GT Racecast"
    assert payload["embeds"] and len(payload["embeds"]) == 1
    return payload["embeds"][0]


def t_takeover_pings_here_and_names_both_producers():
    p = n.takeover_discord_payload("Bob", "Alice", 7, "Feed A", event_title="GTEC R4")
    assert p["content"] == "@here"
    assert p["allowed_mentions"] == {"parse": ["everyone"]}
    e = _embed(p)
    assert "Bob" in e["description"]            # who took over
    assert "Alice" in e["description"]          # from whom
    assert "7" in e["description"]              # the on-air stint
    assert e["footer"]["text"] == "GTEC R4 · Bob"   # event title · producer


def t_takeover_without_from_producer_or_title():
    p = n.takeover_discord_payload("Bob", "", 3, "Feed B")
    e = _embed(p)
    assert "Bob" in e["description"]
    assert e["footer"]["text"] == "Bob"        # producer only
    # no "from" clause when the outgoing producer is unknown
    assert "from " not in e["description"].lower()


def t_obs_stream_started_is_info_no_ping():
    p = n.obs_stream_discord_payload(True, "Bob", event_title="GTEC R4")
    assert "content" not in p or not p.get("content")   # info, NOT an @here ping
    e = _embed(p)
    assert "start" in e["title"].lower()
    assert e["footer"]["text"] == "GTEC R4 · Bob"
    assert e["color"] == n.COLOR_STREAM_START


def t_obs_stream_stopped_pings_here_off_air():
    p = n.obs_stream_discord_payload(False, "Bob")
    assert p["content"] == "@here"
    assert p["allowed_mentions"] == {"parse": ["everyone"]}
    e = _embed(p)
    assert "stop" in e["title"].lower()
    assert "off air" in e["description"].lower()
    assert e["footer"]["text"] == "Bob"
    assert e["color"] == n.COLOR_STREAM_STOP


def t_no_footer_when_neither_title_nor_producer():
    p = n.obs_stream_discord_payload(True, "")
    e = _embed(p)
    assert "footer" not in e


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("all notify tests passed")
