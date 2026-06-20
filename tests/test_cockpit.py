#!/usr/bin/env python3
"""Stdlib unit checks for the Commentator Cockpit. Run: python3 tests/test_cockpit.py"""
import importlib.util
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ca = _load("console_auth", ("src", "scripts", "console_auth.py"))
m = _load("irofeeds", ("src", "relay", "racecast-feeds.py"))
cad = _load("console_admin", ("src", "scripts", "console_admin.py"))

SECRET = "test-secret-do-not-ship"


def t_streamer_key_normalizes():
    assert ca.streamer_key("Alpha Racing") == "alpha-racing"
    assert ca.streamer_key("  Beta!#1  ") == "beta1"
    assert ca.streamer_key("") == ""
    assert ca.streamer_key(None) == ""


def t_mint_token_shape():
    tok = ca.mint_token(SECRET, "alpha-racing", version=1)
    key, ver, sig = tok.split(".")
    assert key == "alpha-racing"
    assert ver == "1"
    assert len(sig) == 32 and all(c in "0123456789abcdef" for c in sig)


def t_verify_round_trip():
    tok = ca.mint_token(SECRET, "alpha-racing")
    assert ca.verify_token(SECRET, tok) == "alpha-racing"


def t_verify_rejects_tampered_sig():
    tok = ca.mint_token(SECRET, "alpha-racing")
    bad = tok[:-1] + ("0" if tok[-1] != "0" else "1")
    assert ca.verify_token(SECRET, bad) is None


def t_verify_rejects_wrong_secret():
    tok = ca.mint_token(SECRET, "alpha-racing")
    assert ca.verify_token("other-secret", tok) is None


def t_secret_matches():
    assert ca.secret_matches("abc", "abc") is True
    assert ca.secret_matches("abc", "abcd") is False
    assert ca.secret_matches("", "abc") is False
    assert ca.secret_matches(None, "abc") is False
    assert ca.secret_matches(None, None) is True   # both empty -> trivially equal


def t_verify_rejects_malformed():
    for bad in ("", "a.b", "a.b.c.d", "alpha.notint.deadbeef" + "0" * 24,
                "BADKEY.1." + "0" * 32, "alpha-racing.1.short"):
        assert ca.verify_token(SECRET, bad) is None, bad


def t_streamer_key_matches_asset_key():
    """console_auth.streamer_key must behave identically to relay asset_key()."""
    for s in ("Alpha Racing", "  Beta!#1 ", "Ümlaut x", "a-b_c d", "", "  "):
        assert ca.streamer_key(s) == m.asset_key(s), s


def t_verify_token_version_check():
    tok_v1 = ca.mint_token(SECRET, "alpha", version=1)
    assert ca.verify_token(SECRET, tok_v1, {"alpha": 1}) == "alpha"
    assert ca.verify_token(SECRET, tok_v1, {"alpha": 2}) is None   # stale version
    assert ca.verify_token(SECRET, tok_v1, {}) == "alpha"          # default 1
    tok_v2 = ca.mint_token(SECRET, "alpha", version=2)
    assert ca.verify_token(SECRET, tok_v2, {"alpha": 2}) == "alpha"


def t_safe_cookie_token_allowlist():
    # A real minted token passes through unchanged.
    tok = ca.mint_token(SECRET, "alpha-racing", version=2)
    assert ca.safe_cookie_token(tok) == tok
    # CR/LF (response splitting), ';' (cookie attribute injection), spaces and the
    # empty/None inputs all collapse to "" so nothing unsafe reaches Set-Cookie.
    assert ca.safe_cookie_token("a.1.deadbeef\r\nSet-Cookie: evil=1") == ""
    assert ca.safe_cookie_token("a.1.x; HttpOnly=no") == ""
    assert ca.safe_cookie_token("a b") == ""
    assert ca.safe_cookie_token("") == ""
    assert ca.safe_cookie_token(None) == ""


def t_rate_limiter_fixed_window():
    rl = ca.RateLimiter(limit=2, window_s=60)
    assert rl.allow("ip", now=0) is True
    assert rl.allow("ip", now=1) is True
    assert rl.allow("ip", now=2) is False      # 3rd hit in window -> blocked
    assert rl.allow("other", now=2) is True    # counter is per-key
    assert rl.allow("ip", now=61) is True       # window reset


def t_versions_default_and_bump():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "console-versions.json")
        assert cad.load_versions(p) == {}                 # missing -> {}
        assert cad.current_version({}, "alpha") == 1      # default 1
        assert cad.bump_version(p, "alpha") == 2          # 1 -> 2, persisted
        assert cad.load_versions(p) == {"alpha": 2}
        assert cad.bump_version(p, "alpha") == 3


def t_revoked_token_rejected_after_bump():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "console-versions.json")
        tok_v1 = ca.mint_token(SECRET, "alpha", version=1)
        assert ca.verify_token(SECRET, tok_v1, cad.load_versions(p)) == "alpha"
        cad.bump_version(p, "alpha")                       # now current = 2
        assert ca.verify_token(SECRET, tok_v1, cad.load_versions(p)) is None
        tok_v2 = ca.mint_token(SECRET, "alpha", version=2)
        assert ca.verify_token(SECRET, tok_v2, cad.load_versions(p)) == "alpha"


def t_apply_pulled_validates():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "console-versions.json")
        assert cad.apply_pulled(p, {"versions": {"alpha": 3, "beta": 2}}) == 2
        assert cad.load_versions(p) == {"alpha": 3, "beta": 2}
        for bad in ({"versions": {"alpha": 0}}, {"versions": {"BAD KEY": 2}},
                    {"versions": {"alpha": "x"}}, {"nope": {}}, []):
            try:
                cad.apply_pulled(p, bad)
                raise AssertionError(f"expected ValueError for {bad!r}")
            except ValueError:
                pass  # expected: bad payload rejected before any write


def _rows():
    # ScheduleSource 4-tuples: (url, streamer, stint, line)
    return [("u0", "Alpha Racing", "S1", 2),
            ("u1", "Beta", "S2", 3),
            ("u2", "Alpha Racing", "S3", 4),
            ("u3", "Gamma", "S4", 5)]


def t_tally_on_air():
    t = m.cockpit_tally(_rows(), 0, "alpha-racing")
    assert t["on_air"] is True
    assert t["up_next"] == {"stint": "S3", "in_n": 2}
    assert t["scheduled"] is True


def t_tally_up_next_only():
    t = m.cockpit_tally(_rows(), 0, "beta")
    assert t["on_air"] is False
    assert t["up_next"] == {"stint": "S2", "in_n": 1}
    assert t["scheduled"] is True


def t_tally_live_idx_none():
    # No feed on air yet: no on_air, the loop is skipped, but me is scheduled.
    t = m.cockpit_tally(_rows(), None, "alpha-racing")
    assert t == {"on_air": False, "up_next": None, "scheduled": True}


def t_tally_not_upcoming():
    t = m.cockpit_tally(_rows(), 2, "beta")     # Beta already passed
    assert t["on_air"] is False and t["up_next"] is None and t["scheduled"] is True


def t_tally_not_scheduled():
    t = m.cockpit_tally(_rows(), 0, "nobody")
    assert t == {"on_air": False, "up_next": None, "scheduled": False}


def t_display_name_maps_key_to_name():
    assert m.cockpit_display_name(_rows(), "alpha-racing") == "Alpha Racing"
    assert m.cockpit_display_name(_rows(), "nobody") == "nobody"


def _cockpit_client(secret="sek", rows=None, live_idx=0,
                    versions_path=None, chat_store=None, timer_store=None,
                    page_path=None):
    """Stand up make_handler over a real ThreadingHTTPServer on an ephemeral port.
    Returns (server, get, post); caller must srv.shutdown() in a finally block."""
    import threading as _t
    import urllib.error
    from urllib.request import Request, urlopen

    class _Feed:
        def __init__(self, idx):
            self.idx = idx

    class _Source:
        def __init__(self, rws):
            self._rows = rws

        def get_rows(self):
            return list(self._rows)

        def health(self):
            return {"count": len(self._rows)}

    class _Relay:
        def __init__(self):
            self.source = _Source(rows if rows is not None else _rows())
            self.mode = "race"
            self.feeds = {"A": _Feed(live_idx), "B": _Feed(live_idx + 1)}

        def live_feed(self):
            return "A"

        def status(self):
            return {"schedule_len": len(self.source.get_rows())}

    handler = m.make_handler(_Relay(), chat_store=chat_store, timer_store=timer_store,
                             cockpit_page_path=page_path, console_secret=secret,
                             console_versions_path=versions_path)
    srv = m.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    _t.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def _read(req):
        try:
            with urlopen(req, timeout=5) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def get(path, cookie=None, headers=None):
        h = dict(headers or {})
        if cookie:
            h["Cookie"] = cookie
        return _read(Request(base + path, headers=h))

    def post(path, body, cookie=None, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        if cookie:
            h["Cookie"] = cookie
        return _read(Request(base + path, data=json.dumps(body).encode(),
                             headers=h, method="POST"))

    return srv, get, post


def t_data_requires_auth():
    srv, get, _post = _cockpit_client()
    try:
        code, _h, _b = get("/cockpit/data")
        assert code == 401, code
    finally:
        srv.shutdown()


def t_data_without_secret_is_404():
    # No CONSOLE_SECRET configured -> cockpit not served (every /cockpit/* 404s).
    srv, get, _post = _cockpit_client(secret=None)
    try:
        tok = ca.mint_token("sek", "alpha-racing")
        code, _h, _b = get("/cockpit/data?t=" + tok)
        assert code == 404, code
    finally:
        srv.shutdown()


def t_data_authed_tally():
    srv, get, _post = _cockpit_client()
    try:
        tok = ca.mint_token("sek", "alpha-racing")
        code, _h, body = get("/cockpit/data?t=" + tok)
        assert code == 200, code
        d = json.loads(body)
        assert d["me"] == "alpha-racing" and d["on_air"] is True
        assert d["up_next"] == {"stint": "S3", "in_n": 2}
        assert d["mode"] == "race"
        # my_stints surfaces the commentator's OWN urls (u0, u2) so the cockpit
        # can pre-fill them, but never a foreign row's url (u1 Beta, u3 Gamma)
        # or raw relay status.
        assert "u1" not in body.decode() and "u3" not in body.decode()
        assert "schedule_len" not in body.decode()
    finally:
        srv.shutdown()


def t_page_sets_cookie_and_serves_html():
    with tempfile.TemporaryDirectory() as d:
        page = os.path.join(d, "cockpit.html")
        with open(page, "w") as fh:
            fh.write("<!doctype html><title>cockpit</title>")
        srv, get, _post = _cockpit_client(page_path=page)
        try:
            tok = ca.mint_token("sek", "alpha-racing")
            code, headers, body = get("/cockpit?t=" + tok)
            assert code == 200, code
            assert b"cockpit" in body
            setc = headers.get("Set-Cookie", "")
            assert "rc_console=" in setc and "HttpOnly" in setc and "SameSite=Lax" in setc
            # plain-http (tailnet) request -> NO Secure, else the browser drops it
            assert "Secure" not in setc
        finally:
            srv.shutdown()


def t_page_cookie_secure_behind_funnel():
    with tempfile.TemporaryDirectory() as d:
        page = os.path.join(d, "cockpit.html")
        with open(page, "w") as fh:
            fh.write("<!doctype html><title>cockpit</title>")
        srv, get, _post = _cockpit_client(page_path=page)
        try:
            tok = ca.mint_token("sek", "alpha-racing")
            code, headers, _body = get("/cockpit?t=" + tok,
                                       headers={"X-Forwarded-Proto": "https"})
            assert code == 200, code
            assert "Secure" in headers.get("Set-Cookie", "")   # Funnel HTTPS -> Secure
        finally:
            srv.shutdown()


def t_page_bad_token_401_no_cookie():
    with tempfile.TemporaryDirectory() as d:
        page = os.path.join(d, "cockpit.html")
        open(page, "w").close()
        srv, get, _post = _cockpit_client(page_path=page)
        try:
            code, headers, _b = get("/cockpit?t=bogus")
            assert code == 401, code
            assert "rc_console=" not in (headers.get("Set-Cookie") or "")
        finally:
            srv.shutdown()


def t_timer_authed():
    class _Timer:
        def data(self):
            return {"running": False, "remaining": "1:00:00"}
    srv, get, _post = _cockpit_client(timer_store=_Timer())
    try:
        tok = ca.mint_token("sek", "alpha-racing")
        code, _h, body = get("/cockpit/timer", cookie="rc_console=" + tok)
        assert code == 200, code
        assert json.loads(body)["remaining"] == "1:00:00"
    finally:
        srv.shutdown()


def t_cockpit_chat_send_forces_identity():
    with tempfile.TemporaryDirectory() as d:
        cs = m.ChatStore(os.path.join(d, "chat.json"))
        srv, get, post = _cockpit_client(chat_store=cs)
        try:
            tok = ca.mint_token("sek", "alpha-racing")
            # client tries to spoof "user" -> must be ignored, forced to display name
            code, _h, body = post("/cockpit/chat/send",
                                  {"user": "Impostor", "text": "hi"},
                                  cookie="rc_console=" + tok)
            assert code == 200, (code, body)
            assert json.loads(body)["message"]["user"] == "Alpha Racing"
            code, _h, body = get("/cockpit/chat/data", cookie="rc_console=" + tok)
            msgs = json.loads(body)["messages"]
            assert msgs[-1]["user"] == "Alpha Racing" and msgs[-1]["text"] == "hi"
        finally:
            srv.shutdown()


def t_cockpit_chat_requires_auth():
    with tempfile.TemporaryDirectory() as d:
        cs = m.ChatStore(os.path.join(d, "chat.json"))
        srv, get, post = _cockpit_client(chat_store=cs)
        try:
            assert get("/cockpit/chat/data")[0] == 401
            assert post("/cockpit/chat/send", {"text": "x"})[0] == 401
        finally:
            srv.shutdown()


def t_versions_endpoint_requires_secret():
    with tempfile.TemporaryDirectory() as d:
        vp = os.path.join(d, "console-versions.json")
        cad.write_versions(vp, {"alpha": 3})
        srv, get, _post = _cockpit_client(secret="sek", versions_path=vp)
        try:
            # /cockpit/versions sits under the funnelled /cockpit prefix -> must auth
            assert get("/cockpit/versions")[0] == 401                       # no header
            assert get("/cockpit/versions",
                       headers={"X-Console-Secret": "wrong"})[0] == 401     # bad secret
            code, _h, body = get("/cockpit/versions",
                                 headers={"X-Console-Secret": "sek"})       # right secret
            assert code == 200 and json.loads(body)["versions"] == {"alpha": 3}
        finally:
            srv.shutdown()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
