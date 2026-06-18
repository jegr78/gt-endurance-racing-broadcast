#!/usr/bin/env python3
"""Pure, import-testable assertion core for the e2e harness (tools/e2e.py).

Stdlib only. Everything here is exercised by tests/test_e2e.py without spawning
a relay; the heavy end-to-end run lives in tools/e2e.py."""
import collections
import csv as _csv
import io as _io
import json as _json
import os
import socket
import sys
import urllib.error
import urllib.request

CheckResult = collections.namedtuple("CheckResult", "name status message")
# status in {"pass", "fail", "skip"}


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
# Binary-mode launcher helpers (pure; tools/e2e.py --binary)
# ---------------------------------------------------------------------------
# Driving the FROZEN binary instead of `python src/racecast.py` is the
# regression guard for binary-ONLY bugs — a file/import missing from the
# PyInstaller bundle, or frozen path resolution — the class the src/ dev build
# hides (e.g. the cockpit.html bundle omission). The argv assembly is pure so it
# is unit-tested without building a binary.

def binary_name(osname=None):
    """The racecast executable's filename for *osname* (os.name): 'racecast.exe'
    on Windows ('nt'), else 'racecast'."""
    osname = os.name if osname is None else osname
    return "racecast.exe" if osname == "nt" else "racecast"


def default_binary_path(root, osname=None):
    """Where tools/build-binary.py drops the racecast executable:
    <root>/dist/bin/<binary_name>."""
    return os.path.join(root, "dist", "bin", binary_name(osname))


def service_launcher(binary, python=None, script=None):
    """Argv PREFIX that invokes the racecast CLI. With *binary* set -> the frozen
    binary ([binary]); otherwise the src/ dev path ([python, script]). Callers
    append the subcommand + args (e.g. + ["relay", "run", "--bind", ...]); the
    subcommand surface is identical either way, so the same checks run against
    both. *python* defaults to the current interpreter."""
    if binary:
        return [binary]
    return [python or sys.executable, script]


# ---------------------------------------------------------------------------
# Check context + individual HTTP check callables
# ---------------------------------------------------------------------------
Ctx = collections.namedtuple(
    "Ctx",
    "relay_url disabled_relay_url ui_url token streamer_key expect own_stint")
Ctx.__new__.__defaults__ = (None,)  # own_stint optional (stub-relay unit tests)


def _get_json(url, headers=None):
    st, body, _ = http_request(url, headers=headers)
    return st, (_json.loads(body or b"null"))


def first_roster_streamer(status, body_bytes):
    """Given a `/schedule/data` HTTP response — the SAME (status, body_bytes)
    shape http_request() returns (status int + raw body bytes) — return the
    first roster streamer name, or None when the status is not 200, the body is
    empty/unparseable, or no row carries a streamer name.

    The real relay serves /schedule/data as {"rows": [{"name": ...}, ...]}; this
    is the pure decode + extract step that the real-league run uses to pick a
    streamer to mint a cockpit token for, without hardcoding a name."""
    if status != 200:
        return None
    try:
        data = _json.loads(body_bytes or b"null")
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    for row in data.get("rows") or []:
        if not isinstance(row, dict):
            continue
        name = (row.get("name") or "").strip()
        if name:
            return name
    return None


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
    # /cockpit/data serves the cockpit_tally() fields FLAT at the top level
    # (on_air/up_next/scheduled), merged with me/mode/my_stints/… — not nested
    # under a "tally" key. Read whichever the server gives (real = flat).
    st, data = _get_json(f"{ctx.relay_url}/cockpit/data?t={ctx.token}")
    if st != 200:
        return CheckResult("cockpit_tally", "fail", f"HTTP {st}")
    tally = data.get("tally") if isinstance(data.get("tally"), dict) else data
    if "on_air" not in tally or "scheduled" not in tally:
        return CheckResult("cockpit_tally", "fail", f"tally shape: {tally}")
    up = tally.get("up_next") or {}
    # Regression guard for #191: the stint label must not double-print "stint".
    label = str(up.get("stint", "")) if isinstance(up, dict) else ""
    if label.lower().count("stint") > 1:
        return CheckResult("cockpit_tally", "fail", f"double stint: {label!r}")
    return CheckResult("cockpit_tally", "pass", "")


def check_cockpit_404_when_disabled(ctx):
    st, _, _ = http_request(ctx.disabled_relay_url + "/cockpit/data")
    if st != 404:
        return CheckResult("cockpit_404_when_disabled", "fail",
                           f"expected 404, got {st}")
    return CheckResult("cockpit_404_when_disabled", "pass", "")


def check_cockpit_timer_renders(ctx):
    """#191 regression: /cockpit/timer must serve real timer fields so the page
    renders a clock, not the literal '—' placeholder. The page falls back to '—'
    only when the JSON is absent / not visible / carries no duration, so assert a
    200 with visible=True and a numeric remaining_s OR duration_s OR end."""
    st, data = _get_json(f"{ctx.relay_url}/cockpit/timer?t={ctx.token}")
    if st != 200:
        return CheckResult("cockpit_timer_renders", "fail", f"HTTP {st}")
    if data.get("error"):
        return CheckResult("cockpit_timer_renders", "fail", f"error: {data['error']}")
    if not data.get("visible"):
        return CheckResult("cockpit_timer_renders", "fail",
                           f"not visible (page would show '—'): {data}")
    nums = [data.get("remaining_s"), data.get("duration_s"), data.get("end")]
    if not any(isinstance(v, (int, float)) for v in nums):
        return CheckResult("cockpit_timer_renders", "fail",
                           f"no renderable timer value: {data}")
    return CheckResult("cockpit_timer_renders", "pass", "")


def check_chat_round_trip(ctx):
    """POST /chat/send {user,text} then GET /chat/data must echo the message back
    (the relay's in-memory ring buffer)."""
    marker = "e2e-chat-ping"
    payload = _json.dumps({"user": "e2e", "text": marker}).encode()
    st, body, _ = http_request(ctx.relay_url + "/chat/send", method="POST",
                               headers={"Content-Type": "application/json"},
                               data=payload)
    if st != 200:
        return CheckResult("chat_round_trip", "fail", f"send HTTP {st}: {body[:120]!r}")
    sent = _json.loads(body or b"null") or {}
    if not sent.get("ok"):
        return CheckResult("chat_round_trip", "fail", f"send rejected: {sent}")
    st, data = _get_json(ctx.relay_url + "/chat/data")
    if st != 200:
        return CheckResult("chat_round_trip", "fail", f"data HTTP {st}")
    texts = [m.get("text") for m in (data.get("messages") or [])]
    if marker not in texts:
        return CheckResult("chat_round_trip", "fail",
                           f"sent message not in /chat/data ({len(texts)} msgs)")
    return CheckResult("chat_round_trip", "pass", "")


def check_submission_pending(ctx):
    """#193: an own-row POST /cockpit/submit (token-auth) lands as PENDING (never
    auto-published) and the director's tailnet-only /submissions lists it."""
    url = "https://www.youtube.com/watch?v=e2eee2eee2e"
    payload = _json.dumps({"url": url, "stint": ctx.own_stint}).encode()
    st, body, _ = http_request(
        f"{ctx.relay_url}/cockpit/submit?t={ctx.token}", method="POST",
        headers={"Content-Type": "application/json"}, data=payload)
    if st != 200:
        return CheckResult("submission_pending", "fail",
                           f"submit HTTP {st}: {body[:160]!r}")
    res = _json.loads(body or b"null") or {}
    if not res.get("ok") or not res.get("id"):
        return CheckResult("submission_pending", "fail", f"submit shape: {res}")
    sub_id = res["id"]
    st, data = _get_json(ctx.relay_url + "/submissions")
    if st != 200:
        return CheckResult("submission_pending", "fail", f"/submissions HTTP {st}")
    pending = data.get("pending") or []
    if not any(e.get("id") == sub_id for e in pending):
        return CheckResult("submission_pending", "fail",
                           f"submission {sub_id} not pending ({len(pending)} entries)")
    return CheckResult("submission_pending", "pass", "")


def check_event_title_round_trip(ctx):
    """#207: POST /event/title sets the free-text event title; it must then surface
    in BOTH /status (director panel) and /cockpit/data (talent). Relay-local state
    (event.json), no external push -> safe in synthetic AND real-league mode."""
    title = "E2E - Round 7 - Spa 24h"
    payload = _json.dumps({"title": title}).encode()
    st, body, _ = http_request(ctx.relay_url + "/event/title", method="POST",
                               headers={"Content-Type": "application/json"},
                               data=payload)
    if st != 200:
        return CheckResult("event_title_round_trip", "fail",
                           f"POST HTTP {st}: {body[:120]!r}")
    res = _json.loads(body or b"null") or {}
    if res.get("title") != title:
        return CheckResult("event_title_round_trip", "fail", f"echo: {res}")
    st, data = _get_json(ctx.relay_url + "/status")
    if st != 200 or data.get("event_title") != title:
        return CheckResult("event_title_round_trip", "fail",
                           f"/status event_title={data.get('event_title')!r}")
    st, cd = _get_json(f"{ctx.relay_url}/cockpit/data?t={ctx.token}")
    if st != 200 or cd.get("event_title") != title:
        return CheckResult("event_title_round_trip", "fail",
                           f"/cockpit/data event_title={cd.get('event_title')!r}")
    return CheckResult("event_title_round_trip", "pass", "")


def check_status_live(ctx):
    """Relaxed real-league /status health: 200 + a non-empty schedule + a live
    block, WITHOUT pinning exact counts (real schedule_len/live_stint are
    unknown without the live Sheet, so check_status_ok's fixed assertions don't
    apply). Structural health only."""
    st, data = _get_json(ctx.relay_url + "/status")
    if st != 200:
        return CheckResult("status_live", "fail", f"/status HTTP {st}")
    n = data.get("schedule_len")
    if not isinstance(n, int) or n <= 0:
        return CheckResult("status_live", "fail", f"schedule_len={n!r} (expected > 0)")
    live = data.get("live")
    if not isinstance(live, dict) or "feed" not in live:
        return CheckResult("status_live", "fail", f"no live block: {live!r}")
    return CheckResult("status_live", "pass", f"schedule_len={n}, live={live.get('feed')}")


def check_cc_api_cockpit(ctx):
    """Control Center /api/cockpit/status responds 200 with sane JSON
    (ok flag + a links list)."""
    if not ctx.ui_url:
        return CheckResult("cc_api_cockpit", "skip", "no ui_url")
    st, data = _get_json(ctx.ui_url + "/api/cockpit/status")
    if st != 200:
        return CheckResult("cc_api_cockpit", "fail", f"HTTP {st}")
    if "ok" not in data or not isinstance(data.get("links"), list):
        return CheckResult("cc_api_cockpit", "fail", f"shape: {data}")
    return CheckResult("cc_api_cockpit", "pass", "")


def _load_set_env_key():
    """Import the REAL `_set_env_key` from src/racecast.py — the single-key
    profile.env writer that the #191 fix lives in. racecast.py imports cleanly
    as a module (no hyphen, no import-time side effects)."""
    import importlib
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(here, "..", "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    return importlib.import_module("racecast")


def check_enable_preserves_keys(_ctx=None):
    """#191 regression: `racecast cockpit enable` must NOT wipe other profile.env
    keys when it writes COCKPIT_SECRET. The bug was a single-pair write through
    the full-set merge_env_text (any key not re-passed was dropped). We exercise
    the EXACT seam the CLI uses — `racecast._set_env_key(path, key, value)`
    (src/racecast.py:908) — against a temp profile.env carrying several keys, and
    assert every pre-existing key survives + COCKPIT_SECRET was added.

    Self-contained: its own tempfile fixture, no relay, no repo profiles/, no
    side effects — so it is safe to run anywhere (incl. SYNTHETIC_CHECKS)."""
    import tempfile
    rc = _load_set_env_key()
    tmp = tempfile.mkdtemp(prefix="racecast-e2e-enable-")
    try:
        ppath = os.path.join(tmp, "profile.env")
        pre = {
            "NAME": "Test League",
            "SHEET_ID": "1AbC_dEfGhIjKlMnOpQrStUvWxYz",
            "SHEET_PUSH_URL": "https://script.google.com/macros/s/AKfyc/exec",
            "CUSTOM_KEY": "keep-me-please",
        }
        with open(ppath, "w", encoding="utf-8") as fh:
            fh.write("# league config\n")
            for k, v in pre.items():
                fh.write(f"{k}={v}\n")
        res = rc._set_env_key(ppath, "COCKPIT_SECRET", "deadbeef" * 8)
        if not res.get("ok"):
            return CheckResult("enable_preserves_keys", "fail",
                               f"_set_env_key failed: {res.get('error')}")
        with open(ppath, encoding="utf-8") as fh:
            after = rc.parse_env_text(fh.read())
        for k, v in pre.items():
            if after.get(k) != v:
                return CheckResult("enable_preserves_keys", "fail",
                                   f"key {k!r} clobbered: was {v!r}, now {after.get(k)!r}")
        if not after.get("COCKPIT_SECRET"):
            return CheckResult("enable_preserves_keys", "fail",
                               "COCKPIT_SECRET was not added")
        return CheckResult("enable_preserves_keys", "pass",
                           f"{len(pre)} keys preserved + COCKPIT_SECRET added")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


SYNTHETIC_CHECKS = [
    check_status_ok,
    check_cockpit_requires_token,
    check_cockpit_accepts_token,
    check_cockpit_404_when_disabled,
    check_cockpit_tally,
    check_cockpit_timer_renders,
    check_chat_round_trip,
    check_submission_pending,
    check_event_title_round_trip,
    check_cc_api_cockpit,
    check_enable_preserves_keys,
]

# Real-league mode (local only): the safe subset for a copied profile. Read-only
# checks PLUS check_chat_round_trip and check_event_title_round_trip — both write
# only relay-local state (the crew chat ring buffer -> chat.json; the event title
# -> event.json), with no external push, so they are harmless against a throwaway
# copy.
# EXCLUDES check_submission_pending (POST /cockpit/submit could ping the league's
# REAL Discord webhook) and check_cockpit_404_when_disabled (needs a second
# disabled relay). Uses the relaxed check_status_live (real schedule_len/
# live_stint are unknown without the live Sheet).
REAL_LEAGUE_CHECKS = [
    check_status_live,
    check_cockpit_requires_token,
    check_cockpit_accepts_token,
    check_cockpit_tally,
    check_cockpit_timer_renders,
    check_chat_round_trip,
    check_event_title_round_trip,
    check_cc_api_cockpit,
    check_enable_preserves_keys,
]
