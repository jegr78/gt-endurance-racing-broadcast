#!/usr/bin/env python3
"""Live-server integration checks for the /console auth gate (#216 phase 3a).
Run: python3 tests/test_console_gate.py"""
import importlib.util, os, tempfile, threading, json
import urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOGDIR = tempfile.mkdtemp(prefix="racecast-test-logs-")
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

SECRET = "s3cret-league"
_URLS8 = [f"https://www.youtube.com/watch?v=stint{i}" for i in range(1, 9)]


class _FakeSource:
    """A schedule source exposing .get() (URL list) and get_rows()/.rows (the
    (url,name,stint,line) tuples the gate reads for schedule_keys and the cockpit
    chat handler reads for the speaker name)."""
    def __init__(self, urls, rows):
        self.items = list(urls)
        self.rows = list(rows)
    def get(self): return self.items
    def get_rows(self): return self.rows
    def refresh(self, timeout=None): pass
    def health(self): return {"ok": True}


class _Crew:
    def __init__(self, rows): self._rows = list(rows)
    def get(self): return list(self._rows)


def _serve(companion_url=None):
    rows = [("https://youtu.be/a", "Alice", "1", 2)]           # alice -> commentator
    src = _FakeSource(_URLS8, rows)
    relay = m.Relay(src, [53001, 53002], LOGDIR)
    crew = _Crew([("Bob", True, False), ("Carol", False, True)])  # bob=director, carol=producer
    SRC = os.path.join(ROOT, "src")
    handler = m.make_handler(
        relay, console_secret=SECRET, cockpit_versions_path=None,
        chat_store=m.ChatStore(os.path.join(LOGDIR, "chat.json")),
        crew_source=crew,
        panel_path=os.path.join(SRC, "director", "director-panel.html"),
        cockpit_page_path=os.path.join(SRC, "cockpit", "cockpit.html"),
        console_page_path=os.path.join(SRC, "console", "console.html"),
        companion_url=companion_url)
    srv = m.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _tok(key):
    return m.cockpit_auth.mint_token(SECRET, key)


def _get(port, path, token=None, secret=None, secret_header="X-Console-Secret"):
    url = f"http://127.0.0.1:{port}{path}"
    if token:
        url += ("&" if "?" in path else "?") + "t=" + token
    req = urllib.request.Request(url)
    if secret:
        req.add_header(secret_header, secret)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _post(port, path, token=None, secret=None, body=None, secret_header="X-Console-Secret"):
    url = f"http://127.0.0.1:{port}{path}"
    if token:
        url += ("&" if "?" in path else "?") + "t=" + token
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    if secret:
        req.add_header(secret_header, secret)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def t_no_token_is_401():
    srv = _serve(); port = srv.server_address[1]
    try:
        assert _get(port, "/console/status")[0] == 401
    finally:
        srv.shutdown()


def t_any_authenticated_read_allowed():
    srv = _serve(); port = srv.server_address[1]
    try:
        code, body = _get(port, "/console/status", _tok("alice"))   # commentator -> any read ok
        assert code == 200, (code, body)
    finally:
        srv.shutdown()


def t_commentator_forbidden_from_director_op():
    srv = _serve(); port = srv.server_address[1]
    try:
        assert _get(port, "/console/next", _tok("alice"))[0] == 403
    finally:
        srv.shutdown()


def t_director_allowed_director_op():
    srv = _serve(); port = srv.server_address[1]
    try:
        assert _get(port, "/console/reload", _tok("bob"))[0] == 200
    finally:
        srv.shutdown()


def t_producer_stepup_required_without_secret():
    srv = _serve(); port = srv.server_address[1]
    try:
        assert _get(port, "/console/set/stint/2", _tok("carol"))[0] == 403
    finally:
        srv.shutdown()


def t_producer_stepup_allowed_with_secret():
    srv = _serve(); port = srv.server_address[1]
    try:
        assert _get(port, "/console/set/stint/2", _tok("carol"), secret=SECRET)[0] == 200
    finally:
        srv.shutdown()


def t_role_gate_precedes_stepup():
    # A director (not producer) with the correct secret is still FORBIDDEN.
    srv = _serve(); port = srv.server_address[1]
    try:
        assert _get(port, "/console/set/stint/2", _tok("bob"), secret=SECRET)[0] == 403
    finally:
        srv.shutdown()


def t_unknown_console_route_is_404():
    srv = _serve(); port = srv.server_address[1]
    try:
        assert _get(port, "/console/bogus", _tok("bob"))[0] == 404
    finally:
        srv.shutdown()


def t_chat_send_forces_token_identity():
    srv = _serve(); port = srv.server_address[1]
    try:
        url = f"http://127.0.0.1:{port}/console/chat/send?t=" + _tok("alice")
        body = json.dumps({"text": "hello from the console"}).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200
        code, data = _get(port, "/console/chat/data", _tok("alice"))
        assert code == 200, (code, data)
        msgs = json.loads(data).get("messages", [])
        # ChatStore messages are {"ts","user","text"}; the speaker is "user" and is
        # server-forced to the token's streamer (display name), never client-declared.
        assert any(msg.get("text") == "hello from the console"
                   and m.asset_key(msg.get("user", "")) == "alice" for msg in msgs), data
    finally:
        srv.shutdown()


def t_chat_send_ignores_client_supplied_user():
    # A client-supplied "user" field in the POST body must be overridden by the
    # token identity — the stored speaker must be the token's key, never "bob".
    srv = _serve(); port = srv.server_address[1]
    try:
        url = f"http://127.0.0.1:{port}/console/chat/send?t=" + _tok("alice")
        body = json.dumps({"user": "bob", "text": "spoof attempt"}).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200
        code, data = _get(port, "/console/chat/data", _tok("alice"))
        msgs = json.loads(data).get("messages", [])
        spoof = [msg for msg in msgs if msg.get("text") == "spoof attempt"]
        assert spoof, data
        # The stored speaker must be the TOKEN identity (alice), never the client's "bob".
        for msg in spoof:
            assert m.asset_key(msg.get("user", "")) == "alice", msg
    finally:
        srv.shutdown()


def t_wrong_method_console_route_is_404():
    # /status is GET-only; POSTing it through /console authorizes (ANY) then 404s
    # at the root dispatch. Pins the GET/POST asymmetry.
    srv = _serve(); port = srv.server_address[1]
    try:
        url = f"http://127.0.0.1:{port}/console/status?t=" + _tok("alice")
        req = urllib.request.Request(url, data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        assert code == 404, code
    finally:
        srv.shutdown()


def t_root_cockpit_page_has_empty_base():
    srv = _serve(); port = srv.server_address[1]
    try:
        code, body = _get(port, "/cockpit", _tok("alice"))
        assert code == 200, (code, body)
        assert 'window.RC_API_BASE = ""' in body, body[:400]
    finally:
        srv.shutdown()


def t_console_whoami_returns_roles():
    srv = _serve(); port = srv.server_address[1]
    try:
        code, data = _get(port, "/console/whoami", _tok("bob"))   # bob = director
        assert code == 200, (code, data)
        body = json.loads(data)
        assert body["subject"] == "bob"
        assert "director" in body["roles"]
    finally:
        srv.shutdown()


def t_console_launcher_served_any_auth():
    srv = _serve(); port = srv.server_address[1]
    try:
        code, body = _get(port, "/console", _tok("alice"))   # commentator
        assert code == 200, (code, body)
        assert 'window.RC_API_BASE = "/console"' in body, body[:400]
    finally:
        srv.shutdown()


def t_console_cockpit_page_any_auth_with_console_base_and_cookie():
    srv = _serve(); port = srv.server_address[1]
    try:
        url = f"http://127.0.0.1:{port}/console/cockpit?t=" + _tok("alice")
        with urllib.request.urlopen(url, timeout=5) as r:
            body = r.read().decode()
            setc = r.headers.get("Set-Cookie", "")
        assert 'window.RC_API_BASE = "/console"' in body, body[:400]
        assert "Path=/console" in setc, setc
    finally:
        srv.shutdown()


def t_console_panel_requires_director():
    srv = _serve(); port = srv.server_address[1]
    try:
        assert _get(port, "/console/panel", _tok("alice"))[0] == 403   # commentator -> no
        assert _get(port, "/console/panel", _tok("bob"))[0] == 200      # director -> yes
    finally:
        srv.shutdown()


def t_console_launcher_links_are_mount_absolute():
    # Card hrefs must be built through RC_API so they resolve under /console
    # (a bare relative 'cockpit' against /console would navigate to /cockpit).
    srv = _serve(); port = srv.server_address[1]
    try:
        code, body = _get(port, "/console", _tok("bob"))   # bob = director: both cards render
        assert code == 200, (code, body)
        assert "RC_API('/cockpit')" in body, body
        assert "RC_API('/panel')" in body, body
        # The old bare-relative forms must be gone.
        assert "card('cockpit'" not in body and "card('panel'" not in body, body
    finally:
        srv.shutdown()


def t_takeover_status_needs_producer_and_step_up():
    # No token -> 401; producer token WITHOUT the secret -> 403 step-up; producer
    # token WITH the secret -> 200 and a REDACTED body (no feed stream URLs).
    srv = _serve(); port = srv.server_address[1]
    try:
        code, _ = _get(port, "/console/takeover/status")                          # no auth
        assert code == 401, code
        code, _ = _get(port, "/console/takeover/status", _tok("carol"))           # no secret
        assert code == 403, code
        code, body = _get(port, "/console/takeover/status", _tok("carol"), SECRET)
        assert code == 200, (code, body)
        blob = json.loads(body)
        assert "live" in blob and "league" in blob, blob
        # Redaction: the public takeover status must NOT carry the feed map or stream URLs.
        assert "feeds" not in blob and "pov" not in blob, blob
        serialised = json.dumps(blob)
        assert "youtube" not in serialised.lower() and "http" not in serialised.lower(), serialised
    finally:
        srv.shutdown()


def t_legacy_cockpit_secret_header_still_accepted():
    # Back-compat: the step-up header was renamed X-Cockpit-Secret -> X-Console-Secret.
    # The relay accepts the legacy name for one release so a mixed-version takeover
    # (old client sending X-Cockpit-Secret, new relay) still authorizes.
    srv = _serve(); port = srv.server_address[1]
    try:
        code, _ = _get(port, "/console/takeover/status", _tok("carol"), SECRET,
                       secret_header="X-Cockpit-Secret")
        assert code == 200, code
    finally:
        srv.shutdown()


def t_takeover_director_without_producer_is_forbidden():
    # A director (no producer role) is rejected even with the step-up secret.
    srv = _serve(); port = srv.server_address[1]
    try:
        code, _ = _get(port, "/console/takeover/status", _tok("bob"), SECRET)
        assert code == 403, code
    finally:
        srv.shutdown()


def t_console_obs_scene_requires_director():
    srv = _serve(); port = srv.server_address[1]
    try:
        assert _post(port, "/console/obs/scene", body={"scene": "Stint"})[0] == 401   # no token
        assert _post(port, "/console/obs/scene", _tok("carol"),                        # producer, not director
                     body={"scene": "Stint"})[0] == 403
        code, _ = _post(port, "/console/obs/scene", _tok("bob"), body={"scene": "Stint"})
        assert code in (200, 503), code   # director allowed (200 ok, or 503 when no OBS in the test)
    finally:
        srv.shutdown()


def t_takeover_chat_and_versions_gated_and_routed():
    srv = _serve(); port = srv.server_address[1]
    try:
        code, body = _get(port, "/console/takeover/chat", _tok("carol"), SECRET)
        assert code == 200, (code, body)
        assert "messages" in json.loads(body), body
        code, body = _get(port, "/console/takeover/versions", _tok("carol"), SECRET)
        assert code == 200, (code, body)
        assert "versions" in json.loads(body), body
        # Without the step-up secret both are 403.
        assert _get(port, "/console/takeover/chat", _tok("carol"))[0] == 403
        assert _get(port, "/console/takeover/versions", _tok("carol"))[0] == 403
    finally:
        srv.shutdown()


from http.server import BaseHTTPRequestHandler


class _StubCompanion(BaseHTTPRequestHandler):
    last = {}
    def do_GET(self):
        _StubCompanion.last = {"path": self.path,
                               "prefix": self.headers.get("Companion-custom-prefix")}
        body = b"<html>companion web buttons</html>"
        self.send_response(200); self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass


def _stub_companion():
    srv = m.ThreadingHTTPServer(("127.0.0.1", 0), _StubCompanion)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def t_buttons_http_proxies_for_director():
    up = _stub_companion(); upurl = f"http://127.0.0.1:{up.server_address[1]}"
    srv = _serve(companion_url=upurl); port = srv.server_address[1]
    try:
        code, body = _get(port, "/console/buttons/tablet", _tok("bob"))   # director
        assert code == 200, (code, body)
        assert "companion web buttons" in body, body
        assert _StubCompanion.last["prefix"] == "console/buttons", _StubCompanion.last  # no slash
        assert _StubCompanion.last["path"] == "/tablet", _StubCompanion.last
    finally:
        srv.shutdown(); up.shutdown()


def t_buttons_forbidden_for_commentator():
    up = _stub_companion(); upurl = f"http://127.0.0.1:{up.server_address[1]}"
    srv = _serve(companion_url=upurl); port = srv.server_address[1]
    try:
        assert _get(port, "/console/buttons/tablet", _tok("alice"))[0] == 403
    finally:
        srv.shutdown(); up.shutdown()


def t_buttons_502_when_companion_down():
    srv = _serve(companion_url="http://127.0.0.1:1"); port = srv.server_address[1]
    try:
        assert _get(port, "/console/buttons/tablet", _tok("bob"))[0] == 502
    finally:
        srv.shutdown()


def t_buttons_health_shape_and_director_gated():
    srv = _serve(companion_url="http://127.0.0.1:1"); port = srv.server_address[1]
    try:
        assert _get(port, "/console/buttons/health", _tok("alice"))[0] == 403   # commentator
        code, body = _get(port, "/console/buttons/health", _tok("bob"))         # director
        assert code == 200, (code, body)
        blob = json.loads(body)
        assert set(blob) == {"reachable", "version", "ok"}, blob
        assert blob["reachable"] is False and blob["ok"] is False               # nothing on port 1
    finally:
        srv.shutdown()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
