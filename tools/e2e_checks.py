#!/usr/bin/env python3
"""Pure, import-testable assertion core for the e2e harness (tools/e2e.py).

Stdlib only. Everything here is exercised by tests/test_e2e.py without spawning
a relay; the heavy end-to-end run lives in tools/e2e.py."""
import collections
import csv as _csv
import io as _io
import socket

CheckResult = collections.namedtuple("CheckResult", "name status message")
# status in {"pass", "fail", "skip"}


def classify_capability(available, name):
    """Optional capability gate: when *available* is False, return a skip
    CheckResult; when True, return None (run the real check)."""
    if available:
        return None
    return CheckResult(name, "skip", f"{name} unavailable")


def run_checks(checks, ctx):
    """Run each check(ctx) -> CheckResult. A raised exception becomes a fail.
    Returns (results, exit_code); exit_code is 1 iff any result failed."""
    results = []
    for fn in checks:
        try:
            r = fn(ctx)
            if not isinstance(r, CheckResult):
                r = CheckResult(getattr(fn, "__name__", "check"), "fail",
                                f"check returned {type(r).__name__}, not CheckResult")
        except Exception as exc:  # noqa: BLE001 — a crashing check is a failure
            r = CheckResult(getattr(fn, "__name__", "check"), "fail",
                            f"{type(exc).__name__}: {exc}")
        results.append(r)
    code = 1 if any(r.status == "fail" for r in results) else 0
    return results, code


def summarize(results):
    """One-line-per-check text summary + a totals line."""
    lines, n = [], {"pass": 0, "fail": 0, "skip": 0}
    for r in results:
        n[r.status] = n.get(r.status, 0) + 1
        mark = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}[r.status]
        lines.append(f"  [{mark}] {r.name}" + (f" — {r.message}" if r.message else ""))
    lines.append(f"  {n['pass']} passed, {n['fail']} failed, {n['skip']} skipped")
    return "\n".join(lines)

SCHEDULE_HEADER = ("URL", "Streamer", "Stint")


def build_schedule_csv(rows):
    """A header-mode schedule CSV (columns URL,Streamer,Stint) the relay's
    ScheduleSource parses 1:1. *rows* = iterable of (url, streamer, stint).
    URLs must be real YouTube/Twitch host URLs (is_channel() rejects
    localhost/LAN/file)."""
    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(SCHEDULE_HEADER)
    for url, streamer, stint in rows:
        w.writerow([url, streamer, stint])
    return buf.getvalue()


def free_port():
    """An OS-assigned free TCP port on the loopback. Bind :0, read it back,
    close — the caller hands it to a child immediately (small race window is
    acceptable for a local harness)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()
