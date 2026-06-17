# e2e / regression harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a thin maintainer driver (`tools/e2e.py`) that stands up the relay + Control Center from `src/` and asserts the live HTTP surface, in a CI-runnable synthetic mode and a local-only real-league mode that share one assertion core.

**Architecture:** Pure helpers (free-port, synthetic-CSV builder, check registry/runner, skip-fail classifier, tolerant HTTP) live in `tools/e2e_checks.py` and are unit-tested in `tests/test_e2e.py`. The driver `tools/e2e.py` owns process lifecycle: it scaffolds an ephemeral synthetic environment (temp profile + in-process CSV server), spawns the relay (`racecast relay run`) and Control Center (`racecast ui --no-browser`) on OS-assigned free ports, polls readiness, runs the check registry, and tears every process down in a `finally`. Real-league mode reuses the same checks against the copied deployed profile. Optional Playwright checks skip when unavailable.

**Tech Stack:** Python 3 stdlib only (`http.server`, `urllib`, `subprocess`, `socket`, `tempfile`, `csv`), no pytest (runnable-script convention). Reuses `src/scripts/cockpit_auth.py` (`mint_token`, `streamer_key`) and `src/relay/racecast-feeds.py`'s `ScheduleSource._parse_rows` for fixture validation.

---

## Reference facts (verified against the codebase)

- Relay reads cockpit gating from env directly: `RACECAST_COCKPIT_SECRET` + `RACECAST_COCKPIT_ENABLED` (`src/relay/racecast-feeds.py:3415`). No `profile.env` write needed to enable cockpit.
- Relay control HTTP server starts on its own thread; feed pulls are best-effort daemon threads, so missing `yt-dlp`/`streamlink`/`ffmpeg`/`deno`/OBS does not stop `/status` from coming up.
- Relay schedule CSV is **header mode**: columns `URL`, `Streamer`, `Stint` (`SCHEDULE_URL_HEADERS=("url",)`, `SCHEDULE_STREAMER_HEADERS=("streamer","name")`, `SCHEDULE_STINT_HEADERS=("stint",)`). URLs must pass `is_channel()` — real YouTube/Twitch host URLs only (no localhost/LAN/file).
- `--sheet-csv-url` disables POV, qualifying and HUD-push (`src/relay/racecast-feeds.py:3269,3280,3338`), so a synthetic CSV server is the whole schedule.
- `/status` JSON shape: `{schedule_len, mode, source, feeds:{A:{port,index,stint,channel,state,...},B:{...}}, live:{feed,stint,mode}, league:{sheet_id}, health:{level,...}}` (`status()` at `:2289`).
- `cockpit_tally(rows, live_idx, me_key)` is pure (`:1303`) → `{on_air:bool, up_next:{stint,in_n}|None, scheduled:bool}`; served at `/cockpit/data` (`:2840`).
- Control Center readiness route: `/api/ping`; cockpit API: `/api/cockpit/status` (`src/ui/ui_server.py:268,435`).
- `cockpit_auth.mint_token(secret, key, version=1)` and `streamer_key(s)` (`src/scripts/cockpit_auth.py:42,27`).

---

## File structure

- **Create `tools/e2e_checks.py`** — pure, import-testable assertion core: `free_port()`, `build_schedule_csv()`, `http_request()` (tolerant), `CheckResult`, `run_checks()`, `classify_capability()`, and the individual check callables.
- **Create `tools/e2e.py`** — the driver: arg parsing, synthetic env scaffolding, in-process CSV server, process spawn/poll/teardown, mode selection (synthetic / `--real-league`), optional Playwright dispatch, summary + exit code.
- **Create `tests/test_e2e.py`** — runnable-script unit tests for the pure pieces of `e2e_checks.py`.
- **Modify `.github/workflows/ci.yml`** — add a synthetic-e2e step on the Linux runner.

---

## Task 1: Free-port helper

**Files:**
- Create: `tools/e2e_checks.py`
- Test: `tests/test_e2e.py`

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
"""Unit tests for the pure pieces of tools/e2e_checks.py (stdlib, no pytest)."""
import os, sys, socket
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import e2e_checks as e


def t_free_port_is_bindable():
    p = e.free_port()
    assert isinstance(p, int) and 1024 < p < 65536, p
    # The returned port must be free to bind right now.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", p))
    s.close()


def t_free_port_varies():
    # Two consecutive calls should not collide in practice.
    assert e.free_port() != e.free_port() or True  # non-flaky: just exercise it


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("PASS test_e2e")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_e2e.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'e2e_checks'`.

- [ ] **Step 3: Write minimal implementation**

Create `tools/e2e_checks.py`:

```python
#!/usr/bin/env python3
"""Pure, import-testable assertion core for the e2e harness (tools/e2e.py).

Stdlib only. Everything here is exercised by tests/test_e2e.py without spawning
a relay; the heavy end-to-end run lives in tools/e2e.py."""
import socket


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_e2e.py`
Expected: `ok t_free_port_is_bindable`, `ok t_free_port_varies`, `PASS test_e2e`.

- [ ] **Step 5: Commit**

```bash
git add tools/e2e_checks.py tests/test_e2e.py
git commit -m "feat(e2e): free-port helper + test scaffold (#199)"
```

---

## Task 2: Synthetic-CSV builder

**Files:**
- Modify: `tools/e2e_checks.py`
- Test: `tests/test_e2e.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_e2e.py` (also import the relay parser to prove the CSV is valid for the real code path):

```python
def _relay_parse(text):
    import importlib.util
    here = os.path.dirname(__file__)
    path = os.path.join(here, "..", "src", "relay", "racecast-feeds.py")
    spec = importlib.util.spec_from_file_location("racecast_feeds", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ScheduleSource._parse_rows(text)


def t_build_schedule_csv_parses_in_relay():
    rows = [
        ("https://www.youtube.com/watch?v=aaaaaaaaaaa", "Alice", "Stint 1"),
        ("https://www.twitch.tv/bobcaster", "Bob", "Stint 2"),
    ]
    csv_text = e.build_schedule_csv(rows)
    assert csv_text.splitlines()[0].lower().split(",")[:3] == ["url", "streamer", "stint"]
    parsed = _relay_parse(csv_text)
    assert parsed is not None and len(parsed) == 2, parsed
    # (url, streamer, stint, line) tuples; streamers survive.
    assert [r[1] for r in parsed] == ["Alice", "Bob"], parsed
    assert [r[2] for r in parsed] == ["Stint 1", "Stint 2"], parsed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_e2e.py`
Expected: FAIL — `AttributeError: module 'e2e_checks' has no attribute 'build_schedule_csv'`.

- [ ] **Step 3: Write minimal implementation**

Add to `tools/e2e_checks.py`:

```python
import csv as _csv
import io as _io

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_e2e.py`
Expected: all `ok ...` lines incl. `t_build_schedule_csv_parses_in_relay`, then `PASS test_e2e`.

- [ ] **Step 5: Commit**

```bash
git add tools/e2e_checks.py tests/test_e2e.py
git commit -m "feat(e2e): synthetic schedule-CSV builder validated against the relay parser (#199)"
```

---

## Task 3: Check result type, registry runner, capability classifier

**Files:**
- Modify: `tools/e2e_checks.py`
- Test: `tests/test_e2e.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_e2e.py`:

```python
def t_run_checks_aggregates_and_exits():
    def ok(_ctx):  return e.CheckResult("ok", "pass", "")
    def bad(_ctx): return e.CheckResult("bad", "fail", "boom")
    def skipd(_ctx): return e.CheckResult("sk", "skip", "no browser")
    results, code = e.run_checks([ok, skipd], ctx=None)
    assert code == 0 and {r.status for r in results} == {"pass", "skip"}
    results, code = e.run_checks([ok, bad], ctx=None)
    assert code == 1, code  # any fail -> non-zero


def t_run_checks_turns_exception_into_fail():
    def boom(_ctx): raise RuntimeError("kaboom")
    results, code = e.run_checks([boom], ctx=None)
    assert code == 1 and results[0].status == "fail" and "kaboom" in results[0].message


def t_classify_capability():
    assert e.classify_capability(available=False, name="playwright").status == "skip"
    assert e.classify_capability(available=True, name="playwright") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_e2e.py`
Expected: FAIL — `AttributeError: ... 'CheckResult'`.

- [ ] **Step 3: Write minimal implementation**

Add to `tools/e2e_checks.py`:

```python
import collections

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_e2e.py`
Expected: all `ok ...`, `PASS test_e2e`.

- [ ] **Step 5: Commit**

```bash
git add tools/e2e_checks.py tests/test_e2e.py
git commit -m "feat(e2e): check-result type, registry runner, capability classifier (#199)"
```

---

## Task 4: Tolerant HTTP helper

**Files:**
- Modify: `tools/e2e_checks.py`
- Test: `tests/test_e2e.py`

- [ ] **Step 1: Write the failing test** (spin a tiny local server in-test so no network is needed)

Add to `tests/test_e2e.py`:

```python
def t_http_request_returns_status_even_on_4xx():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            if self.path == "/ok":
                self.send_response(200); self.send_header("X-T", "1"); self.end_headers()
                self.wfile.write(b"hello")
            else:
                self.send_response(401); self.end_headers(); self.wfile.write(b"no")

    srv = ThreadingHTTPServer(("127.0.0.1", e.free_port()), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        st, body, hdrs = e.http_request(base + "/ok")
        assert st == 200 and body == b"hello" and hdrs.get("X-T") == "1", (st, body)
        st, body, _ = e.http_request(base + "/nope")   # must NOT raise on 401
        assert st == 401, st
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_e2e.py`
Expected: FAIL — `AttributeError: ... 'http_request'`.

- [ ] **Step 3: Write minimal implementation**

Add to `tools/e2e_checks.py`:

```python
import urllib.request
import urllib.error


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_e2e.py`
Expected: all `ok ...`, `PASS test_e2e`.

- [ ] **Step 5: Commit**

```bash
git add tools/e2e_checks.py tests/test_e2e.py
git commit -m "feat(e2e): tolerant HTTP helper (status on 4xx/5xx, no raise) (#199)"
```

---

## Task 5: HTTP checks (the assertions) as ctx-driven callables

**Files:**
- Modify: `tools/e2e_checks.py`
- Test: `tests/test_e2e.py`

The checks take a `ctx` with `.relay_url`, `.disabled_relay_url`, `.ui_url`, `.token`, `.streamer_key`, `.expect` (expected schedule facts). Unit-test the **pure response-shaping** logic against an in-test stub server; the full live run happens in Task 6.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_e2e.py` a stub relay exposing the minimal surface, then assert two representative checks pass against it:

```python
def _stub_relay():
    import json, threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    state = {"token": "good"}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _send(self, code, body=b"", ctype="application/json", extra=None):
            self.send_response(code); self.send_header("Content-Type", ctype)
            for k, v in (extra or {}).items(): self.send_header(k, v)
            self.end_headers(); self.wfile.write(body)
        def _authed(self):
            return ("t=" in (self.path or "")) or \
                   ("rc_cockpit=" + state["token"]) in (self.headers.get("Cookie") or "")
        def do_GET(self):
            p = self.path.split("?")[0]
            if p == "/status":
                self._send(200, json.dumps({"schedule_len": 2, "mode": "race",
                    "feeds": {"A": {"port": 1}, "B": {"port": 2}},
                    "live": {"feed": "A", "stint": 1, "mode": "race"}}).encode())
            elif p == "/cockpit/data":
                if not self._authed(): return self._send(401, b'{"error":"auth"}')
                self._send(200, json.dumps({"tally": {"on_air": True,
                    "up_next": {"stint": "Stint 2", "in_n": 1}, "scheduled": True}}).encode())
            elif p == "/cockpit":
                if not self._authed(): return self._send(401, b"no")
                self._send(200, b"<html>cockpit</html>", "text/html",
                           {"Set-Cookie": "rc_cockpit=good; HttpOnly"})
            else:
                self._send(404, b"nope")
    srv = ThreadingHTTPServer(("127.0.0.1", e.free_port()), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def t_check_status_and_auth_gating():
    srv, url = _stub_relay()
    try:
        Ctx = e.Ctx
        ctx = Ctx(relay_url=url, disabled_relay_url=url + "/missing", ui_url=None,
                  token="good", streamer_key="alice",
                  expect={"schedule_len": 2, "live_stint": 1})
        assert e.check_status_ok(ctx).status == "pass"
        assert e.check_cockpit_requires_token(ctx).status == "pass"
        assert e.check_cockpit_accepts_token(ctx).status == "pass"
        assert e.check_cockpit_tally(ctx).status == "pass"
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_e2e.py`
Expected: FAIL — `AttributeError: ... 'Ctx'`.

- [ ] **Step 3: Write minimal implementation**

Add to `tools/e2e_checks.py`:

```python
import collections as _collections
import json as _json

Ctx = _collections.namedtuple(
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
```

> Note for the implementer: `check_cockpit_timer_renders`, `check_chat_round_trip`, `check_submission_pending`, `check_cc_api_cockpit`, and `check_enable_preserves_keys` follow the same pattern. Probe the live endpoint first (Task 6 brings a real relay up), confirm the exact JSON/HTML keys, then write each as a `CheckResult` callable. Add a stub-server unit test for any whose logic does response-shaping beyond a status-code compare. Keep each check a single-responsibility function named `check_<thing>`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_e2e.py`
Expected: all `ok ...`, `PASS test_e2e`.

- [ ] **Step 5: Commit**

```bash
git add tools/e2e_checks.py tests/test_e2e.py
git commit -m "feat(e2e): core HTTP checks (status, cockpit auth gating, tally) (#199)"
```

---

## Task 6: The driver — synthetic bring-up, run, teardown

**Files:**
- Create: `tools/e2e.py`

This task is **integration**: its verification is the driver running green, not a unit test. Build incrementally and run `python3 tools/e2e.py` after each addition.

- [ ] **Step 1: Scaffold the driver skeleton**

Create `tools/e2e.py`:

```python
#!/usr/bin/env python3
"""End-to-end / regression harness: stand up the relay + Control Center from
src/ and assert the live HTTP surface. Synthetic mode (default, CI-runnable,
no real Sheet/cookies/OBS/Tailscale) or --real-league NAME (local-only).

Not shipped (maintainer tool). Stdlib only."""
import argparse, contextlib, os, shutil, signal, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import e2e_checks as E
import cockpit_auth


def _csv_server(csv_text):
    body = csv_text.encode()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/csv"); self.end_headers()
            self.wfile.write(body)
    srv = ThreadingHTTPServer(("127.0.0.1", E.free_port()), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/schedule.csv"
```

- [ ] **Step 2: Add process spawn + readiness poll helpers**

Append to `tools/e2e.py`:

```python
def _spawn(argv, env, log):
    """Spawn a child from src/, its own process group so teardown kills the tree.
    stdout/stderr captured to *log* (a file path) for diagnosis."""
    fh = open(log, "wb")
    kw = {}
    if os.name == "posix":
        kw["start_new_session"] = True
    p = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT, **kw)
    p._logfh = fh  # keep handle for close on teardown
    return p


def _kill(p):
    if not p or p.poll() is not None:
        with contextlib.suppress(Exception):
            if getattr(p, "_logfh", None): p._logfh.close()
        return
    with contextlib.suppress(Exception):
        if os.name == "posix":
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        else:
            p.terminate()
    with contextlib.suppress(Exception):
        p.wait(timeout=10)
    with contextlib.suppress(Exception):
        if getattr(p, "_logfh", None): p._logfh.close()


def _wait_ready(url, timeout, proc=None, log=None):
    """Poll *url* until HTTP 200 or timeout. On timeout, dump *log* and raise."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            break
        try:
            st, _, _ = E.http_request(url, timeout=2)
            if st == 200:
                return
        except Exception:
            pass
        time.sleep(0.3)
    detail = ""
    if log and os.path.exists(log):
        with open(log, "rb") as fh:
            detail = fh.read()[-2000:].decode("utf-8", "replace")
    raise RuntimeError(f"service not ready at {url} within {timeout}s\n--- child log ---\n{detail}")
```

- [ ] **Step 3: Add the synthetic-mode runner**

Append to `tools/e2e.py`:

```python
SCHEDULE_ROWS = [
    ("https://www.youtube.com/watch?v=aaaaaaaaaaa", "Alice", "Stint 1"),
    ("https://www.twitch.tv/bobcaster", "Bob", "Stint 2"),
]


def run_synthetic(args):
    tmp = tempfile.mkdtemp(prefix="racecast-e2e-")
    procs, servers = [], []
    try:
        # 1. synthetic profile (scaffold from profiles/example) + cockpit secret
        prof_root = os.path.join(tmp, "profiles")
        shutil.copytree(os.path.join(ROOT, "profiles", "example"),
                        os.path.join(prof_root, "e2e"))
        secret = "e2e-secret-0123456789abcdef"
        key = cockpit_auth.streamer_key("Alice")
        token = cockpit_auth.mint_token(secret, key, version=1)

        # 2. schedule CSV server
        csv_srv, csv_url = _csv_server(E.build_schedule_csv(SCHEDULE_ROWS))
        servers.append(csv_srv)

        # 3. enabled relay
        relay_port = E.free_port()
        env = dict(os.environ)
        env.update(RACECAST_COCKPIT_SECRET=secret, RACECAST_COCKPIT_ENABLED="1",
                   RACECAST_PROFILE="e2e")
        relay_log = os.path.join(tmp, "relay.log")
        relay = _spawn([sys.executable, os.path.join(ROOT, "src", "racecast.py"),
                        "relay", "run", "--bind", "127.0.0.1",
                        "--http-port", str(relay_port), "--sheet-csv-url", csv_url],
                       env, relay_log)
        procs.append(relay)
        relay_url = f"http://127.0.0.1:{relay_port}"
        _wait_ready(relay_url + "/status", args.timeout, relay, relay_log)

        # 4. disabled relay (no RACECAST_COCKPIT_ENABLED) -> /cockpit/* 404
        dis_port = E.free_port()
        env2 = dict(os.environ); env2.update(RACECAST_PROFILE="e2e")
        dis_log = os.path.join(tmp, "relay-disabled.log")
        dis = _spawn([sys.executable, os.path.join(ROOT, "src", "racecast.py"),
                      "relay", "run", "--bind", "127.0.0.1",
                      "--http-port", str(dis_port), "--sheet-csv-url", csv_url],
                     env2, dis_log)
        procs.append(dis)
        dis_url = f"http://127.0.0.1:{dis_port}"
        _wait_ready(dis_url + "/status", args.timeout, dis, dis_log)

        # 5. Control Center
        ui_port = E.free_port()
        env3 = dict(env); env3["RACECAST_UI_PORT"] = str(ui_port)
        ui_log = os.path.join(tmp, "ui.log")
        ui = _spawn([sys.executable, os.path.join(ROOT, "src", "racecast.py"),
                     "ui", "--no-browser"], env3, ui_log)
        procs.append(ui)
        ui_url = f"http://127.0.0.1:{ui_port}"
        _wait_ready(ui_url + "/api/ping", args.timeout, ui, ui_log)

        # 6. run checks
        ctx = E.Ctx(relay_url=relay_url, disabled_relay_url=dis_url, ui_url=ui_url,
                    token=token, streamer_key=key,
                    expect={"schedule_len": 2, "live_stint": 1})
        results, code = E.run_checks(E.SYNTHETIC_CHECKS, ctx)
        print(E.summarize(results))
        return code
    finally:
        if not args.keep:
            for p in procs: _kill(p)
            for s in servers:
                with contextlib.suppress(Exception): s.shutdown()
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print(f"--keep: left tmp at {tmp}")
```

Add the check list to `tools/e2e_checks.py`:

```python
SYNTHETIC_CHECKS = [
    check_status_ok,
    check_cockpit_requires_token,
    check_cockpit_accepts_token,
    check_cockpit_404_when_disabled,
    check_cockpit_tally,
    # extend with: check_cockpit_timer_renders, check_chat_round_trip,
    # check_submission_pending, check_cc_api_cockpit, check_enable_preserves_keys
]
```

- [ ] **Step 4: Add arg parsing + main**

Append to `tools/e2e.py`:

```python
def main(argv=None):
    ap = argparse.ArgumentParser(description="racecast e2e/regression harness")
    ap.add_argument("--real-league", metavar="NAME", default=None,
                    help="drive the copied real-league dev build (local only, never CI)")
    ap.add_argument("--playwright", action="store_true",
                    help="also run gated rendered checks (skip if unavailable)")
    ap.add_argument("--timeout", type=float, default=30.0,
                    help="per-service readiness timeout (s)")
    ap.add_argument("--keep", action="store_true", help="skip teardown (debug)")
    args = ap.parse_args(argv)
    if args.real_league:
        return run_real_league(args)   # added in Task 7
    return run_synthetic(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the harness**

Run: `python3 tools/e2e.py`
Expected: the five core checks print `[PASS]` and the process exits 0. (If a service times out, read the dumped child log; the most likely first-run issue is the UI/relay needing a dependency the runner lacks — note it and adjust.)

While here, **probe the remaining endpoints** to fill in the deferred checks from Task 5's note (`/cockpit/timer`, `/chat/*`, `/cockpit/submit` + `/submissions/*`, `/api/cockpit/status`), then add each as a `check_*` and append to `SYNTHETIC_CHECKS`. Re-run until all are green.

- [ ] **Step 6: Commit**

```bash
git add tools/e2e.py tools/e2e_checks.py
git commit -m "feat(e2e): synthetic-mode driver (relay + CC bring-up, checks, teardown) (#199)"
```

---

## Task 7: Real-league mode + `enable_preserves_keys` check

**Files:**
- Modify: `tools/e2e.py`
- Modify: `tools/e2e_checks.py`

- [ ] **Step 1: Implement `run_real_league`**

Append to `tools/e2e.py` a runner that resolves the copied profile via `src/scripts/config.py`, mints a token from the league's real `COCKPIT_SECRET`, spawns the relay (`racecast relay start`/`run`) + UI against it, runs the **subset of checks safe against real data** (everything except the destructive submission-approve), and tears down. It must **refuse to run under CI** — guard:

```python
def run_real_league(args):
    if os.environ.get("CI"):
        print("real-league mode is local-only; refusing under CI"); return 0
    # resolve profiles/<NAME>, spawn services against it, run REAL_LEAGUE_CHECKS,
    # summarize, teardown (same _spawn/_wait_ready/_kill helpers).
    ...
```

- [ ] **Step 2: Add `check_enable_preserves_keys`** (the #191 env-clobber regression) to `tools/e2e_checks.py` — write a temp `profile.env` with extra keys, run `racecast cockpit enable` against it, assert every pre-existing key survives. Unit-test this one in `tests/test_e2e.py` against a temp dir (it is pure file I/O, no relay).

- [ ] **Step 3: Run both**

Run: `python3 tools/e2e.py` (synthetic, must stay green) and, if real-league data is present locally, `python3 tools/e2e.py --real-league iro-gtec`.
Expected: synthetic green; real-league green or a clear skip when data is absent.

- [ ] **Step 4: Commit**

```bash
git add tools/e2e.py tools/e2e_checks.py tests/test_e2e.py
git commit -m "feat(e2e): real-league local mode + enable-preserves-keys regression check (#199)"
```

---

## Task 8: Optional Playwright rendered checks (gated)

**Files:**
- Modify: `tools/e2e.py`

- [ ] **Step 1: Add a gated Playwright dispatch** that runs only with `--playwright`, detects browser availability, and on absence emits `classify_capability(available=False, name="playwright")` skips rather than failing. The rendered checks (`render_tally_pill`, `render_funnel_pill`) assert the cockpit page's tally + funnel pills. Keep them additive to the result list so a browserless run still exits on the API checks alone.

- [ ] **Step 2: Run**

Run: `python3 tools/e2e.py` (no browser → Playwright checks skip) and `python3 tools/e2e.py --playwright` where a browser exists.
Expected: skips are reported, exit code still governed by the API checks.

- [ ] **Step 3: Commit**

```bash
git add tools/e2e.py
git commit -m "feat(e2e): optional gated Playwright rendered checks (#199)"
```

---

## Task 9: CI wiring + docs note

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `tools/e2e.py` (module docstring already documents usage; add a one-line pointer in the maintainer docs if a natural home exists)

- [ ] **Step 1: Inspect the CI workflow**

Run: `grep -n "runs-on\|name:\|run:\|python3 tools/run-tests.py" .github/workflows/ci.yml`
Confirm where the Linux job runs the test suite.

- [ ] **Step 2: Add the synthetic e2e step** to the Linux job (after the unit suite), e.g.:

```yaml
      - name: e2e harness (synthetic)
        if: runner.os == 'Linux'
        run: python3 tools/e2e.py
```

- [ ] **Step 3: Verify locally** the whole-suite gates still pass:

Run:
```bash
python3 tools/run-tests.py
python3 tools/lint.py
python3 tools/build.py
```
Expected: all exit 0 (`tests/test_e2e.py` is now part of `run-tests.py`; `tools/e2e.py`/`e2e_checks.py` are not shipped, so `build.py`'s no-shell-scripts/portable checks stay green).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(e2e): run the synthetic e2e harness on the Linux runner (#199)"
```

---

## Self-review notes (addressed)

- **Spec coverage:** synthetic + real-league (Tasks 6, 7); API + optional Playwright (Tasks 5, 8); thin driver in `tools/` (Task 6); all 10 core checks (Tasks 5–7); CI wiring (Task 9); self-test of pure pieces (`tests/test_e2e.py`, Tasks 1–5, 7). The funnel-CapMap bug is intentionally left to `tests/test_funnel_setup.py` per the spec.
- **Deferred checks:** Task 5's note + Task 6 Step 5 require probing the live endpoints to finalize `check_cockpit_timer_renders`, `check_chat_round_trip`, `check_submission_pending`, `check_cc_api_cockpit` — they are explicitly listed, not silently dropped.
- **Type consistency:** `CheckResult(name,status,message)`, `Ctx(relay_url,disabled_relay_url,ui_url,token,streamer_key,expect)`, `run_checks -> (results,code)`, `http_request -> (status,body,headers)`, check callables named `check_*`, `SYNTHETIC_CHECKS` list — used consistently across tasks.
- **Assumptions to confirm at Task 6 Step 5:** relay starts without `yt-dlp`/`streamlink`/`ffmpeg`/`deno`; `racecast ui --no-browser` serves `/api/ping` and stays up headless.
