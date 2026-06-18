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


def t_prune_removes_only_old_files(tmp):
    d = os.path.join(tmp, "prune"); os.makedirs(d)
    now = 1_000_000_000
    fresh = os.path.join(d, "relay.console.log")
    old = os.path.join(d, "relay.console.log.2020-01-01")
    for p in (fresh, old):
        open(p, "w").close()
    os.utime(fresh, (now - 1 * 86400, now - 1 * 86400))    # 1 day old -> keep
    os.utime(old, (now - 30 * 86400, now - 30 * 86400))    # 30 days old -> delete
    removed = lg.prune_old_logs(d, keep_days=7, now_ts=now)
    assert removed == [old], removed
    assert os.path.exists(fresh) and not os.path.exists(old)


def t_prune_missing_dir_is_noop():
    assert lg.prune_old_logs("/no/such/dir/xyz", keep_days=7, now_ts=1) == []


def t_classify_subproc_line_levels():
    assert lg.classify_subproc_line("HTTP 403 Forbidden") == logging.ERROR
    assert lg.classify_subproc_line("Traceback (most recent call last)") == logging.ERROR
    assert lg.classify_subproc_line("Waiting for streams, retrying in 5s") == logging.WARNING
    assert lg.classify_subproc_line("Opening stream: 1080p (hls)") == logging.INFO


def t_tag_line_prefixes_and_strips_eol():
    assert lg.tag_line("feed_A", "serving stint 3\n") == "[feed_A] serving stint 3"
    assert lg.tag_line("relay", "x\r\n") == "[relay] x"


def t_pump_subprocess_logs_each_line(tmp):
    import io
    path = os.path.join(tmp, "logs", "feed_A.log")
    log = lg.configure_logging("test.pump", path, to_stdout=False)
    stream = io.StringIO("Opening stream\nHTTP 403 Forbidden\n")
    lg.pump_subprocess(stream, log, "streamlink")
    for h in log.handlers:
        h.flush()
    with open(path, encoding="utf-8") as fh:
        body = fh.read()
    assert "INFO [streamlink] Opening stream" in body, body
    assert "ERROR [streamlink] HTTP 403 Forbidden" in body, body


def t_obs_log_dir_per_platform():
    assert lg.obs_log_dir("darwin", home="/Users/x") == \
        "/Users/x/Library/Application Support/obs-studio/logs"
    assert lg.obs_log_dir("linux", home="/home/x") == "/home/x/.config/obs-studio/logs"
    assert lg.obs_log_dir("win32", home="/h", env={"APPDATA": "C:/Users/x/AppData/Roaming"}) \
        == "C:/Users/x/AppData/Roaming/obs-studio/logs"


def t_list_and_newest_log_order(tmp):
    d = os.path.join(tmp, "ll"); os.makedirs(d)
    a = os.path.join(d, "a.log"); b = os.path.join(d, "b.log")
    open(a, "w").close(); open(b, "w").close()
    os.utime(a, (100, 100)); os.utime(b, (200, 200))
    assert lg.list_logs(d) == [b, a]          # newest first
    assert lg.newest_log(d) == b
    assert lg.newest_log(os.path.join(tmp, "empty")) is None


def t_archive_dates_lists_rotated(tmp):
    d = os.path.join(tmp, "ad"); os.makedirs(d)
    for n in ("relay.console.log", "relay.console.log.2026-06-17",
              "relay.console.log.2026-06-16", "feed_A.log.2026-06-17", "junk.txt"):
        open(os.path.join(d, n), "w").close()
    assert lg.archive_dates(d, ["relay.console.log", "feed_A.log"]) == \
        ["2026-06-17", "2026-06-16"]


def t_resolve_archive_ok_and_guards(tmp):
    d = os.path.join(tmp, "ra"); os.makedirs(d)
    good = os.path.join(d, "relay.console.log.2026-06-17")
    open(good, "w").close()
    assert lg.resolve_archive(d, "relay.console.log", "2026-06-17") == os.path.realpath(good)
    assert lg.resolve_archive(d, "relay.console.log", "2026-06-18") is None   # no file
    assert lg.resolve_archive(d, "relay.console.log", "../../etc/passwd") is None
    assert lg.resolve_archive(d, "../relay.console.log", "2026-06-17") is None
    assert lg.resolve_archive(d, "relay.console.log", "2026-13-99x") is None   # bad date shape


def t_close_logging_releases_handlers(tmp):
    path = os.path.join(tmp, "logs", "close.log")
    log = lg.configure_logging("test.close", path, to_stdout=False)
    log.info("x")
    assert any(getattr(h, "_racecast", False) for h in log.handlers)
    lg.close_logging("test.close")
    assert not any(getattr(h, "_racecast", False) for h in log.handlers)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in sorted(globals().items()):
            if name.startswith("t_") and callable(fn):
                import inspect
                fn(tmp) if inspect.signature(fn).parameters else fn()
                print("ok", name)
        # Windows can't delete a file with an open handle — release every rotating
        # handler this run attached before the temp dir is removed.
        for _ln in list(logging.Logger.manager.loggerDict):
            lg.close_logging(_ln)
