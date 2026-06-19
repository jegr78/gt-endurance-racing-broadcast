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


def _serve():
    rows = [("https://youtu.be/a", "Alice", "1", 2)]           # alice -> commentator
    src = _FakeSource(_URLS8, rows)
    relay = m.Relay(src, [53001, 53002], LOGDIR)
    crew = _Crew([("Bob", True, False), ("Carol", False, True)])  # bob=director, carol=producer
    handler = m.make_handler(relay, cockpit_secret=SECRET, cockpit_versions_path=None,
                             chat_store=m.ChatStore(os.path.join(LOGDIR, "chat.json")),
                             crew_source=crew)
    srv = m.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _tok(key):
    return m.cockpit_auth.mint_token(SECRET, key)


def _get(port, path, token=None, secret=None):
    url = f"http://127.0.0.1:{port}{path}"
    if token:
        url += ("&" if "?" in path else "?") + "t=" + token
    req = urllib.request.Request(url)
    if secret:
        req.add_header("X-Cockpit-Secret", secret)
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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
