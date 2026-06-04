#!/usr/bin/env python3
"""Stdlib unit checks for the relay's auto dual-bind (localhost + Tailscale IP).
Run: python3 tests/test_bind.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "iro-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


# --- _in_cgnat: Tailscale uses the 100.64.0.0/10 CGNAT range -----------------
def t_cgnat_typical_tailscale_ip():
    assert m._in_cgnat("100.81.234.4") is True


def t_cgnat_range_edges():
    assert m._in_cgnat("100.64.0.0") is True       # bottom of /10
    assert m._in_cgnat("100.127.255.255") is True  # top of /10
    assert m._in_cgnat("100.63.255.255") is False  # just below
    assert m._in_cgnat("100.128.0.0") is False     # just above


def t_cgnat_rejects_lan_and_garbage():
    assert m._in_cgnat("192.168.1.5") is False
    assert m._in_cgnat("10.0.0.1") is False
    assert m._in_cgnat("not-an-ip") is False
    assert m._in_cgnat("") is False


# --- parse_tailscale_ip: first CGNAT IPv4 line of `tailscale ip -4` -----------
def t_parse_single_line():
    assert m.parse_tailscale_ip("100.81.234.4\n") == "100.81.234.4"


def t_parse_skips_blank_and_non_cgnat():
    assert m.parse_tailscale_ip("\n  100.81.234.4  \nfe80::1\n") == "100.81.234.4"


def t_parse_none_when_empty():
    assert m.parse_tailscale_ip("") is None


def t_parse_none_when_no_cgnat():
    assert m.parse_tailscale_ip("192.168.1.5\n") is None


# --- resolve_bind_addresses: bind arg + detected ip -> ordered address list ---
def t_auto_with_tailscale_ip():
    assert m.resolve_bind_addresses("auto", "100.81.234.4") == ["127.0.0.1", "100.81.234.4"]


def t_auto_without_tailscale_falls_back_to_localhost():
    assert m.resolve_bind_addresses("auto", None) == ["127.0.0.1"]


def t_explicit_localhost_ignores_tailscale():
    assert m.resolve_bind_addresses("127.0.0.1", "100.81.234.4") == ["127.0.0.1"]
    assert m.resolve_bind_addresses("localhost", "100.81.234.4") == ["127.0.0.1"]


def t_explicit_address_wins_over_auto_detection():
    assert m.resolve_bind_addresses("0.0.0.0", "100.81.234.4") == ["0.0.0.0"]
    assert m.resolve_bind_addresses("0.0.0.0", None) == ["0.0.0.0"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
