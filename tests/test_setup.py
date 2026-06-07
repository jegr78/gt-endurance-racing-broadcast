#!/usr/bin/env python3
"""Stdlib unit checks for the panel sheet-control additions.
Run: python3 tests/test_setup.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "iro-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


# ---------- webhook response check (v2 action echo) ----------

def t_webhook_ok_plain():
    ok, err = m.check_webhook_response(b'{"ok": true}')
    assert ok and err is None


def t_webhook_ok_with_echo():
    ok, err = m.check_webhook_response(b'{"ok": true, "action": "setup", "v": 2}',
                                       expected_action="setup")
    assert ok and err is None


def t_webhook_v1_script_is_outdated_for_actions():
    # a v1 timer-only script answers ok WITHOUT the action echo -> not a success
    ok, err = m.check_webhook_response(b'{"ok": true}', expected_action="setup")
    assert not ok and "outdated" in err


def t_webhook_error_body():
    ok, err = m.check_webhook_response(b'{"error": "bad key"}')
    assert not ok and "bad key" in err


def t_webhook_garbage_body():
    ok, err = m.check_webhook_response(b"<html>Apps Script error page</html>")
    assert not ok and "did not confirm" in err
    ok, err = m.check_webhook_response(b"")
    assert not ok


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
