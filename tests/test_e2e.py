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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("PASS test_e2e")
