#!/usr/bin/env python3
"""Stdlib checks for the logging helper. Run: python3 tests/test_logs.py"""
import logging, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import logsetup as lg


def t_configure_logging_writes_timestamped_line(tmp):
    path = os.path.join(tmp, "logs", "relay.console.log")
    log = lg.configure_logging("test.relay.a", path, to_stdout=False)
    log.info("hello world")
    for h in log.handlers:
        h.flush()
    with open(path, encoding="utf-8") as fh:
        line = fh.read().strip()
    # "2026-06-18 12:00:00 INFO hello world"
    assert line.endswith("INFO hello world"), line
    assert line[:4].isdigit() and line[4] == "-", line   # leading ISO date


def t_configure_logging_no_stdout_handler_when_not_tty(tmp):
    path = os.path.join(tmp, "logs", "b.log")
    log = lg.configure_logging("test.relay.b", path, to_stdout=False)
    assert all(not isinstance(h, logging.StreamHandler)
               or isinstance(h, logging.FileHandler)
               for h in log.handlers)


def t_configure_logging_idempotent(tmp):
    path = os.path.join(tmp, "logs", "c.log")
    a = lg.configure_logging("test.relay.c", path, to_stdout=False)
    n = len(a.handlers)
    b = lg.configure_logging("test.relay.c", path, to_stdout=False)
    assert a is b and len(b.handlers) == n   # no duplicate handlers


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in sorted(globals().items()):
            if name.startswith("t_") and callable(fn):
                import inspect
                fn(tmp) if inspect.signature(fn).parameters else fn()
                print("ok", name)
