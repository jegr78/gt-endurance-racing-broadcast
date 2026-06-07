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


def t_relay_extra_text_ok_no_tailscale():
    d = {"pid": 1, "alive": True, "port": 8088, "http_ok": True}
    assert iro._relay_extra_text(d, None) == "control http://127.0.0.1:8088/status OK"


# ---------- companion ----------

def t_companion_payload_running_with_config():
    d = iro.companion_status_payload(True, True,
                                     {"bind_ip": "100.64.0.7", "http_port": 8000})
    assert d == {"supported": True, "running": True,
                 "url": "http://100.64.0.7:8000/tablet", "why": ""}


def t_companion_payload_running_no_config():
    d = iro.companion_status_payload(True, True, None)
    assert d["running"] is True and d["url"] is None


def t_companion_payload_unsupported():
    d = iro.companion_status_payload(False, False, None, "(manual on linux)")
    assert d == {"supported": False, "running": False, "url": None,
                 "why": "(manual on linux)"}


# ---------- streams ----------

def t_streams_status_data_labels(tmp):
    p1 = os.path.join(tmp, "feed_53001.pid")
    with open(p1, "w") as fh:
        fh.write(str(os.getpid()))          # a live PID -> alive True
    p2 = os.path.join(tmp, "feed_53002.pid")
    with open(p2, "w") as fh:
        fh.write("garbage")                 # unreadable -> pid None, alive False
    feeds = iro.streams_status_data(pidfiles=[p1, p2])
    assert feeds == [
        {"label": "53001", "pid": os.getpid(), "alive": True},
        {"label": "53002", "pid": None, "alive": False}]


def t_streams_status_data_empty():
    assert iro.streams_status_data(pidfiles=[]) == []


# ---------- aggregate payload ----------

def t_ui_status_payload_shape():
    payload = iro.ui_status_payload(
        relay=lambda: {"alive": False}, companion=lambda: {"running": False},
        streams=lambda: [], tailscale=lambda: None)
    assert payload == {"version": iro.version(), "relay": {"alive": False},
                       "companion": {"running": False}, "streams": [],
                       "tailscale_ip": None}


if __name__ == "__main__":
    import inspect, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in sorted(globals().items()):
            if name.startswith("t_") and callable(fn):
                fn(tmp) if inspect.signature(fn).parameters else fn()
                print("ok", name)
    print("ALL PASS")
