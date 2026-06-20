#!/usr/bin/env python3
"""Unit tests for the pure pieces of tools/e2e_checks.py (stdlib, no pytest)."""
import os, sys, socket
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import e2e_checks as e


def t_binary_name_per_os():
    assert e.binary_name("nt") == "racecast.exe"
    assert e.binary_name("posix") == "racecast"


def t_default_binary_path_layout():
    # build-binary.py drops the executable at <root>/dist/bin/<name>.
    p = e.default_binary_path("/repo", "posix")
    assert p == os.path.join("/repo", "dist", "bin", "racecast")
    pw = e.default_binary_path("/repo", "nt")
    assert pw.endswith(os.path.join("dist", "bin", "racecast.exe"))


def t_service_launcher_binary_vs_src():
    # Binary mode -> just the binary; src mode -> [python, script]. Either way the
    # caller appends the SAME subcommand, so the checks run unchanged against both.
    assert e.service_launcher("/tmp/app/racecast") == ["/tmp/app/racecast"]
    assert e.service_launcher(None, python="py3", script="src/racecast.py") == \
        ["py3", "src/racecast.py"]
    # empty string (flag given without a path) is falsy -> src path, not binary.
    assert e.service_launcher("", python="py3", script="s.py") == ["py3", "s.py"]


def t_free_port_is_bindable():
    p = e.free_port()
    assert isinstance(p, int) and 1024 < p < 65536, p
    # The returned port must be free to bind right now.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", p))
    s.close()


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
                   ("rc_console=" + state["token"]) in (self.headers.get("Cookie") or "")
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
                           {"Set-Cookie": "rc_console=good; HttpOnly"})
            else:
                self._send(404, b"nope")
            return None
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


def _stub_relay2():
    """A stub that mirrors the REAL relay's flat /cockpit/data shape (tally fields
    at the top level) plus /cockpit/timer, /chat/* round-trip and
    /cockpit/submit -> /submissions. Token-gated like the real relay."""
    import json, threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    chat = []          # mutable closure state — the round-trip target
    pending = []
    event = {"title": ""}   # /event/title round-trip target (#207)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _authed(self): return "t=" in (self.path or "")
        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            p = self.path.split("?")[0]
            if p == "/status":
                return self._send(200, {"schedule_len": 2, "event_title": event["title"]})
            if p == "/cockpit/data":
                if not self._authed(): return self._send(401, {"error": "auth"})
                # flat (real shape): tally fields merged at top level
                return self._send(200, {"on_air": True, "up_next": None,
                                        "scheduled": True, "me": "alice",
                                        "event_title": event["title"]})
            if p == "/cockpit/timer":
                if not self._authed(): return self._send(401, {"error": "auth"})
                return self._send(200, {"visible": True, "end": None,
                                        "duration_s": 21600, "remaining_s": None,
                                        "mode": "prestart"})
            if p == "/chat/data":
                return self._send(200, {"messages": list(chat)})
            if p == "/submissions":
                return self._send(200, {"pending": list(pending)})
            return self._send(404, {"error": "nope"})
        def do_POST(self):
            p = self.path.split("?")[0]
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if p == "/chat/send":
                msg = {"ts": 1.0, "user": body.get("user"), "text": body.get("text")}
                chat.append(msg)
                return self._send(200, {"ok": True, "message": msg})
            if p == "/cockpit/submit":
                if not self._authed(): return self._send(401, {"error": "auth"})
                entry = {"id": "sub-1", "target_stint": body.get("stint")}
                pending.append(entry)
                return self._send(200, {"ok": True, "id": "sub-1",
                                        "stint": body.get("stint")})
            if p == "/event/title":
                event["title"] = (body.get("title") or "").strip()
                return self._send(200, {"ok": True, "title": event["title"]})
            return self._send(404, {"error": "nope"})
    srv = ThreadingHTTPServer(("127.0.0.1", e.free_port()), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def t_check_cockpit_tally_reads_flat_shape():
    srv, url = _stub_relay2()
    try:
        ctx = e.Ctx(relay_url=url, disabled_relay_url=url, ui_url=None,
                    token="good", streamer_key="alice",
                    expect={"schedule_len": 2, "live_stint": 1})
        assert e.check_cockpit_tally(ctx).status == "pass"
    finally:
        srv.shutdown()


def t_check_cockpit_timer_renders():
    srv, url = _stub_relay2()
    try:
        ctx = e.Ctx(relay_url=url, disabled_relay_url=url, ui_url=None,
                    token="good", streamer_key="alice", expect={})
        assert e.check_cockpit_timer_renders(ctx).status == "pass"
    finally:
        srv.shutdown()


def t_check_chat_round_trip():
    srv, url = _stub_relay2()
    try:
        ctx = e.Ctx(relay_url=url, disabled_relay_url=url, ui_url=None,
                    token="good", streamer_key="alice", expect={})
        assert e.check_chat_round_trip(ctx).status == "pass"
    finally:
        srv.shutdown()


def t_check_submission_pending():
    srv, url = _stub_relay2()
    try:
        ctx = e.Ctx(relay_url=url, disabled_relay_url=url, ui_url=None,
                    token="good", streamer_key="alice", own_stint="Stint 1",
                    expect={})
        assert e.check_submission_pending(ctx).status == "pass"
    finally:
        srv.shutdown()


def t_check_event_title_round_trip():
    srv, url = _stub_relay2()
    try:
        ctx = e.Ctx(relay_url=url, disabled_relay_url=url, ui_url=None,
                    token="good", streamer_key="alice", expect={})
        assert e.check_event_title_round_trip(ctx).status == "pass"
    finally:
        srv.shutdown()


def t_check_cc_api_cockpit():
    import json, threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            if self.path == "/api/console/status":
                body = json.dumps({"ok": True, "enabled": False,
                                   "links": []}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers(); self.wfile.write(body)
            else:
                self.send_response(404); self.end_headers()
    srv = ThreadingHTTPServer(("127.0.0.1", e.free_port()), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        ui = f"http://127.0.0.1:{srv.server_address[1]}"
        ctx = e.Ctx(relay_url=None, disabled_relay_url=None, ui_url=ui,
                    token="good", streamer_key="alice", expect={})
        assert e.check_cc_api_cockpit(ctx).status == "pass"
        # No ui_url -> skip, never crash.
        ctx2 = ctx._replace(ui_url=None)
        assert e.check_cc_api_cockpit(ctx2).status == "skip"
    finally:
        srv.shutdown()


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


def t_first_roster_streamer_picks_first():
    # A well-formed /schedule/data body (the real relay's {"rows":[{"name":...}]}
    # shape) -> the first non-empty streamer name. The bytes-decoding here is the
    # SAME path the real-league run takes, so it covers the 3-tuple unpack +
    # JSON decode that the old 2-tuple unpack broke.
    import json
    body = json.dumps({"rows": [
        {"row": 1, "name": "Alice", "stint": "Stint 1"},
        {"row": 2, "name": "Bob", "stint": "Stint 2"},
    ]}).encode()
    assert e.first_roster_streamer(200, body) == "Alice"


def t_first_roster_streamer_empty_is_none():
    import json
    assert e.first_roster_streamer(200, json.dumps({"rows": []}).encode()) is None
    # blank names are skipped, too
    body = json.dumps({"rows": [{"name": "  "}, {"name": ""}]}).encode()
    assert e.first_roster_streamer(200, body) is None


def t_first_roster_streamer_non_200_is_none():
    import json
    body = json.dumps({"rows": [{"name": "Alice"}]}).encode()
    # Non-200 -> None even when the body would parse to a roster.
    assert e.first_roster_streamer(500, body) is None
    assert e.first_roster_streamer(404, b"") is None


def t_classify_capability():
    assert e.classify_capability(available=False, name="playwright").status == "skip"
    assert e.classify_capability(available=True, name="playwright") is None


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


def t_check_enable_preserves_keys_passes():
    # The self-contained check uses its own tempfile fixture + the REAL
    # racecast._set_env_key seam; it must pass with no relay and no side effects.
    assert e.check_enable_preserves_keys(None).status == "pass"


def t_set_env_key_preserves_other_keys():
    # Exercise the #191 seam directly against a temp profile.env: writing ONE key
    # must not drop the others (the bug was a full-set merge clobbering them).
    import tempfile, shutil, importlib
    src = os.path.join(os.path.dirname(__file__), "..", "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    rc = importlib.import_module("racecast")
    tmp = tempfile.mkdtemp(prefix="racecast-e2e-test-")
    try:
        ppath = os.path.join(tmp, "profile.env")
        with open(ppath, "w", encoding="utf-8") as fh:
            fh.write("# header\nNAME=Foo\nSHEET_ID=abc123\nSHEET_PUSH_URL=https://x/exec\n"
                     "CUSTOM=keep\n")
        res = rc._set_env_key(ppath, "CONSOLE_SECRET", "s" * 64)
        assert res.get("ok"), res
        with open(ppath, encoding="utf-8") as fh:
            after = rc.parse_env_text(fh.read())
        assert after["NAME"] == "Foo", after
        assert after["SHEET_ID"] == "abc123", after
        assert after["SHEET_PUSH_URL"] == "https://x/exec", after
        assert after["CUSTOM"] == "keep", after
        assert after["CONSOLE_SECRET"] == "s" * 64, after
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _import_e2e():
    import importlib
    if "e2e" in sys.modules:
        return sys.modules["e2e"]
    return importlib.import_module("e2e")


def t_rendered_checks_skip_without_browser():
    # GATE test, NOT a browser test: when Playwright is unavailable, the gated
    # dispatch must yield SKIP results (one per rendered check) and never try to
    # launch a browser. We force unavailability instead of probing the host.
    driver = _import_e2e()
    saved = driver._playwright_available
    driver._playwright_available = lambda: False
    try:
        ctx = e.Ctx(relay_url="http://127.0.0.1:1", disabled_relay_url=None,
                    ui_url=None, token="tok", streamer_key="alice", expect={})
        rendered = driver.run_rendered_checks(ctx)
        assert len(rendered) == len(driver.RENDERED_CHECKS), rendered
        assert all(r.status == "skip" for r in rendered), rendered
        names = {r.name for r in rendered}
        assert names == {"render_tally_pill", "render_funnel_pill"}, names
    finally:
        driver._playwright_available = saved


def t_capture_shots_skips_without_browser():
    # GATE test: --shots must no-op (return [], never launch a browser or create
    # the output dir) when Playwright is unavailable — same gate as the rendered
    # checks. We force unavailability instead of probing the host.
    driver = _import_e2e()
    saved = driver._playwright_available
    driver._playwright_available = lambda: False
    try:
        ctx = e.Ctx(relay_url="http://127.0.0.1:1", disabled_relay_url=None,
                    ui_url="http://127.0.0.1:2", token="tok", streamer_key="alice",
                    expect={})
        written = driver._capture_shots(ctx, os.path.join("nonexistent-e2e-shots-dir"))
        assert written == [], written
    finally:
        driver._playwright_available = saved


def t_rendered_skip_does_not_change_exit_code():
    # The overall exit code is governed by the API checks: appending SKIP
    # rendered results must keep a green run green (and a red run red).
    driver = _import_e2e()
    saved = driver._playwright_available
    driver._playwright_available = lambda: False
    try:
        ctx = e.Ctx(relay_url="http://127.0.0.1:1", disabled_relay_url=None,
                    ui_url=None, token="tok", streamer_key="alice", expect={})
        rendered = driver.run_rendered_checks(ctx)
        # API all pass -> combined stays 0 even with the SKIP rows appended.
        api_results, code = e.run_checks(
            [lambda _c: e.CheckResult("ok", "pass", "")], ctx)
        combined = api_results + rendered
        bumped = 1 if any(r.status == "fail" for r in rendered) else code
        assert bumped == 0, (code, rendered)
        assert {r.status for r in combined} == {"pass", "skip"}, combined
    finally:
        driver._playwright_available = saved


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("PASS test_e2e")
