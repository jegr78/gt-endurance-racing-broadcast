#!/usr/bin/env python3
"""Stdlib unit checks for the Tailscale detection/control helpers.
Run: python3 tests/test_tailscale.py"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import tailscale as ts


def _status_json(state, ips):
    return json.dumps({"BackendState": state, "Self": {"TailscaleIPs": ips}})


# --- _in_cgnat: Tailscale uses the 100.64.0.0/10 CGNAT range -----------------
def t_cgnat_range():
    assert ts._in_cgnat("100.64.10.20") is True
    assert ts._in_cgnat("100.63.255.255") is False
    assert ts._in_cgnat("192.168.1.5") is False
    assert ts._in_cgnat("not-an-ip") is False


# --- parse_tailscale_backend: (BackendState, ip) from `status --json` ---------
def t_backend_running_returns_state_and_ip():
    out = _status_json("Running", ["fd7a:115c:a1e0::1", "100.64.10.20"])
    assert ts.parse_tailscale_backend(out) == ("Running", "100.64.10.20")


def t_backend_stopped_keeps_state_but_no_ip():
    # A disconnected node keeps its assigned tailnet IP — never report it.
    out = _status_json("Stopped", ["100.64.10.20"])
    assert ts.parse_tailscale_backend(out) == ("Stopped", None)


def t_backend_needslogin():
    assert ts.parse_tailscale_backend(_status_json("NeedsLogin", [])) == \
        ("NeedsLogin", None)


def t_backend_running_without_cgnat_ip():
    assert ts.parse_tailscale_backend(_status_json("Running", [])) == ("Running", None)


def t_backend_garbage_is_none_none():
    assert ts.parse_tailscale_backend("") == (None, None)
    assert ts.parse_tailscale_backend("not json") == (None, None)
    assert ts.parse_tailscale_backend("[1, 2]") == (None, None)
    assert ts.parse_tailscale_backend('{"Self": {}}') == (None, None)


# --- parse_tailscale_status: Running IP only (detection compat wrapper) -------
def t_status_wrapper_running_vs_stopped():
    assert ts.parse_tailscale_status(_status_json("Running", ["100.64.10.20"])) == \
        "100.64.10.20"
    assert ts.parse_tailscale_status(_status_json("Stopped", ["100.64.10.20"])) is None
    assert ts.parse_tailscale_status(_status_json("NeedsLogin", ["100.64.10.20"])) is None


# --- plan_tailscale_up: decision for an `up` request given a BackendState -----
def t_plan_running_is_connected():
    assert ts.plan_tailscale_up("Running") == "connected"


def t_plan_stopped_and_starting_run_up():
    assert ts.plan_tailscale_up("Stopped") == "run-up"
    assert ts.plan_tailscale_up("Starting") == "run-up"
    assert ts.plan_tailscale_up("NoState") == "run-up"


def t_plan_login_states_never_run_up():
    # `up` in these states would trigger the interactive browser login.
    assert ts.plan_tailscale_up("NeedsLogin") == "needs-login"
    assert ts.plan_tailscale_up("NeedsMachineAuth") == "needs-login"


def t_plan_no_backend_launches_app():
    assert ts.plan_tailscale_up(None) == "launch-app"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
