#!/usr/bin/env python3
"""Stdlib checks for the Control Center's structured status providers in iro.py.
Run: python3 tests/test_ui_ops.py"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
import iro


# ---------- relay ----------

def t_relay_status_data_running():
    d = iro.relay_status_data(read_pid=lambda p: 4242,
                              alive=lambda pid: True,
                              http_ok=lambda: True)
    assert d == {"pid": 4242, "alive": True, "port": 8088, "http_ok": True}


def t_relay_status_data_stopped_skips_http_probe():
    probed = []
    d = iro.relay_status_data(read_pid=lambda p: None,
                              alive=lambda pid: False,
                              http_ok=lambda: probed.append(1) or True)
    assert d == {"pid": None, "alive": False, "port": 8088, "http_ok": False}
    assert probed == []   # never probe HTTP for a dead relay


def t_relay_extra_text_ok_with_tailscale():
    d = {"pid": 1, "alive": True, "port": 8088, "http_ok": True}
    text = iro._relay_extra_text(d, "100.64.0.7")
    assert "control http://127.0.0.1:8088/status OK" in text
    assert "tablet/panel http://100.64.0.7:8088/panel" in text


def t_relay_extra_text_port_down_no_tailscale():
    d = {"pid": 1, "alive": True, "port": 8088, "http_ok": False}
    text = iro._relay_extra_text(d, None)
    assert text == "(port 8088 not responding)"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")
