#!/usr/bin/env python3
"""Stdlib checks for the shared outbound-HTTP helper. Run: python3 tests/test_http_util.py"""
import importlib.util, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
spec = importlib.util.spec_from_file_location(
    "http_util", os.path.join(ROOT, "src", "scripts", "http_util.py"))
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)


class _Resp:
    def __init__(self, body=b""): self._b = body
    def read(self, n=None): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _capture(body=b""):
    """Patch http_util.urlopen; return (calls, restore). calls[i] = (Request, timeout)."""
    calls = []
    def fake(req, timeout=None):
        calls.append((req, timeout))
        return _Resp(body)
    orig = h.urlopen
    h.urlopen = fake
    return calls, (lambda: setattr(h, "urlopen", orig))


def t_ua_constant_is_not_default_urllib():
    assert h.RACECAST_UA and "urllib" not in h.RACECAST_UA.lower()


def t_open_url_always_sets_user_agent():
    calls, restore = _capture()
    try:
        with h.open_url("https://x/y", timeout=4):
            pass
    finally:
        restore()
    req, timeout = calls[0]
    assert req.get_header("User-agent") == h.RACECAST_UA
    assert timeout == 4


def t_caller_user_agent_overrides_default():
    calls, restore = _capture()
    try:
        h.get_bytes("https://x/y", headers={"User-Agent": "Mozilla/5.0 ua"})
    finally:
        restore()
    assert calls[0][0].get_header("User-agent") == "Mozilla/5.0 ua"


def t_extra_headers_merge_keep_ua():
    calls, restore = _capture()
    try:
        h.get_bytes("https://x/y", headers={"Range": "bytes=0-9"})
    finally:
        restore()
    req = calls[0][0]
    assert req.get_header("User-agent") == h.RACECAST_UA
    assert req.get_header("Range") == "bytes=0-9"


def t_get_json_parses():
    calls, restore = _capture(body=b'{"a": 1}')
    try:
        assert h.get_json("https://x/y") == {"a": 1}
    finally:
        restore()


def t_post_json_sets_content_type_and_body():
    calls, restore = _capture()
    try:
        h.post_json("https://x/y", {"k": "v"})
    finally:
        restore()
    req = calls[0][0]
    assert req.get_header("Content-type") == "application/json"
    assert json.loads(req.data.decode("utf-8")) == {"k": "v"}
    assert req.get_method() == "POST"
    assert req.get_header("User-agent") == h.RACECAST_UA


def t_httperror_is_reexported_and_propagates():
    assert h.HTTPError is __import__("urllib.error", fromlist=["HTTPError"]).HTTPError
    def boom(req, timeout=None):
        raise h.HTTPError("https://x", 403, "Forbidden", {}, None)
    orig = h.urlopen; h.urlopen = boom
    try:
        h.get_bytes("https://x")
        raise AssertionError("expected HTTPError")
    except h.HTTPError as e:
        assert e.code == 403
    finally:
        h.urlopen = orig


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
