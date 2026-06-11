#!/usr/bin/env python3
"""Stdlib unit checks for the relay's auto dual-bind (localhost + Tailscale IP).
Run: python3 tests/test_bind.py"""
import importlib.util, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


# --- _in_cgnat: Tailscale uses the 100.64.0.0/10 CGNAT range -----------------
def t_cgnat_typical_tailscale_ip():
    assert m._in_cgnat("100.64.10.20") is True


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


# --- parse_tailscale_status: CGNAT IPv4 from `tailscale status --json`, -------
# --- but ONLY while the backend is actually Running (a stopped node still -----
# --- has its assigned IP, so `tailscale ip -4` alone reports false positives) -
def _status_json(state, ips):
    return json.dumps({"BackendState": state, "Self": {"TailscaleIPs": ips}})


def t_status_running_returns_ip():
    out = _status_json("Running", ["100.64.10.20", "fd7a:115c:a1e0::1"])
    assert m.parse_tailscale_status(out) == "100.64.10.20"


def t_status_running_skips_ipv6_before_ipv4():
    out = _status_json("Running", ["fd7a:115c:a1e0::1", "100.64.10.20"])
    assert m.parse_tailscale_status(out) == "100.64.10.20"


def t_status_stopped_is_none_even_with_ip():
    # The regression: a disconnected node keeps its assigned tailnet IP.
    out = _status_json("Stopped", ["100.64.10.20"])
    assert m.parse_tailscale_status(out) is None


def t_status_needslogin_is_none():
    assert m.parse_tailscale_status(_status_json("NeedsLogin", [])) is None


def t_status_running_without_cgnat_ip_is_none():
    assert m.parse_tailscale_status(_status_json("Running", [])) is None
    assert m.parse_tailscale_status('{"BackendState": "Running"}') is None


def t_status_garbage_is_none():
    assert m.parse_tailscale_status("") is None
    assert m.parse_tailscale_status("not json") is None
    assert m.parse_tailscale_status("[1, 2]") is None


# --- resolve_bind_addresses: bind arg + detected ip -> ordered address list ---
def t_auto_with_tailscale_ip():
    assert m.resolve_bind_addresses("auto", "100.64.10.20") == ["127.0.0.1", "100.64.10.20"]


def t_auto_without_tailscale_falls_back_to_localhost():
    assert m.resolve_bind_addresses("auto", None) == ["127.0.0.1"]


def t_explicit_localhost_ignores_tailscale():
    assert m.resolve_bind_addresses("127.0.0.1", "100.64.10.20") == ["127.0.0.1"]
    assert m.resolve_bind_addresses("localhost", "100.64.10.20") == ["127.0.0.1"]


def t_explicit_address_wins_over_auto_detection():
    assert m.resolve_bind_addresses("0.0.0.0", "100.64.10.20") == ["0.0.0.0"]
    assert m.resolve_bind_addresses("0.0.0.0", None) == ["0.0.0.0"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
