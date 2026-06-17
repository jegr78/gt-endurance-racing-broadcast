#!/usr/bin/env python3
"""Pure, import-testable assertion core for the e2e harness (tools/e2e.py).

Stdlib only. Everything here is exercised by tests/test_e2e.py without spawning
a relay; the heavy end-to-end run lives in tools/e2e.py."""
import collections
import csv as _csv
import io as _io
import json as _json
import socket
import urllib.error
import urllib.request

CheckResult = collections.namedtuple("CheckResult", "name status message")


def http_request(url, method="GET", headers=None, data=None, timeout=10):
    """GET/POST returning (status, body_bytes, headers_dict) WITHOUT raising on
    4xx/5xx (urllib raises HTTPError there; we read it as a normal response so
    auth-gating checks can assert 401/404)."""
    req = urllib.request.Request(url, method=method, data=data,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 loopback
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers or {})
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


# ---------------------------------------------------------------------------
# Check context + individual HTTP check callables
# ---------------------------------------------------------------------------
Ctx = collections.namedtuple(
    "Ctx", "relay_url disabled_relay_url ui_url token streamer_key expect")


def _get_json(url, headers=None):
    st, body, _ = http_request(url, headers=headers)
    return st, (_json.loads(body or b"null"))


def check_status_ok(ctx):
    st, data = _get_json(ctx.relay_url + "/status")
    if st != 200:
        return CheckResult("status_ok", "fail", f"/status HTTP {st}")
    if data.get("schedule_len") != ctx.expect["schedule_len"]:
        return CheckResult("status_ok", "fail",
                           f"schedule_len={data.get('schedule_len')}")
    if data.get("live", {}).get("stint") != ctx.expect["live_stint"]:
        return CheckResult("status_ok", "fail", f"live={data.get('live')}")
    return CheckResult("status_ok", "pass", "")


def check_cockpit_requires_token(ctx):
    st, _, _ = http_request(ctx.relay_url + "/cockpit/data")
    if st != 401:
        return CheckResult("cockpit_requires_token", "fail",
                           f"expected 401, got {st}")
    return CheckResult("cockpit_requires_token", "pass", "")


def check_cockpit_accepts_token(ctx):
    url = f"{ctx.relay_url}/cockpit?t={ctx.token}"
    st, _, hdrs = http_request(url)
    if st != 200:
        return CheckResult("cockpit_accepts_token", "fail", f"HTTP {st}")
    if "rc_cockpit=" not in (hdrs.get("Set-Cookie") or ""):
        return CheckResult("cockpit_accepts_token", "fail", "no rc_cockpit cookie")
    return CheckResult("cockpit_accepts_token", "pass", "")


def check_cockpit_tally(ctx):
    st, data = _get_json(f"{ctx.relay_url}/cockpit/data?t={ctx.token}")
    if st != 200:
        return CheckResult("cockpit_tally", "fail", f"HTTP {st}")
    tally = data.get("tally") or {}
    up = tally.get("up_next") or {}
    # Regression guard for #191: the stint label must not double-print "stint".
    label = str(up.get("stint", ""))
    if label.lower().count("stint") > 1:
        return CheckResult("cockpit_tally", "fail", f"double stint: {label!r}")
    if "on_air" not in tally or "scheduled" not in tally:
        return CheckResult("cockpit_tally", "fail", f"tally shape: {tally}")
    return CheckResult("cockpit_tally", "pass", "")


def check_cockpit_404_when_disabled(ctx):
    st, _, _ = http_request(ctx.disabled_relay_url + "/cockpit/data")
    if st != 404:
        return CheckResult("cockpit_404_when_disabled", "fail",
                           f"expected 404, got {st}")
    return CheckResult("cockpit_404_when_disabled", "pass", "")
