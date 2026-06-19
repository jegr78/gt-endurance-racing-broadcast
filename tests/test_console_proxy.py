#!/usr/bin/env python3
"""Pure unit checks for the /console/buttons proxy helpers (#236).
Run: python3 tests/test_console_proxy.py"""
import importlib.util, os
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "console_proxy", os.path.join(ROOT, "src", "scripts", "console_proxy.py"))
cp = importlib.util.module_from_spec(spec); spec.loader.exec_module(cp)


def t_upstream_path_strips_prefix_and_keeps_query():
    assert cp.upstream_path("/console/buttons") == "/"
    assert cp.upstream_path("/console/buttons/") == "/"
    assert cp.upstream_path("/console/buttons/tablet") == "/tablet"
    assert cp.upstream_path("/console/buttons/assets/index-abc.js") == "/assets/index-abc.js"
    assert cp.upstream_path("/console/buttons/trpc?x=1&y=2") == "/trpc?x=1&y=2"


def t_forward_headers_inject_no_leading_slash_prefix():
    out = cp.forward_request_headers({"Host": "x.ts.net", "Accept": "text/html",
                                      "Connection": "keep-alive", "Accept-Encoding": "gzip"})
    assert out["Companion-custom-prefix"] == "console/buttons"   # NO leading slash (Phase 0)
    assert out["Host"] == "127.0.0.1:8000"
    assert out["Accept"] == "text/html"
    assert "Connection" not in out and "Accept-Encoding" not in out


def t_filter_response_headers_drops_framing_and_hop_by_hop():
    kept = dict(cp.filter_response_headers(
        [("Content-Length", "10"), ("Content-Type", "text/html"),
         ("Set-Cookie", "a=b"), ("Transfer-Encoding", "chunked"), ("X-Foo", "bar")]))
    assert "Content-Length" not in kept and "Content-Type" not in kept
    assert "Transfer-Encoding" not in kept
    assert kept["Set-Cookie"] == "a=b" and kept["X-Foo"] == "bar"


def t_is_websocket_upgrade():
    assert cp.is_websocket_upgrade({"Upgrade": "websocket", "Connection": "Upgrade"})
    assert not cp.is_websocket_upgrade({"Connection": "keep-alive"})


def t_version_ge():
    assert cp.version_ge("4.1.0", (4, 1, 0)) and cp.version_ge("4.3.4", (4, 1, 0))
    assert not cp.version_ge("4.0.9", (4, 1, 0))
    assert not cp.version_ge(None, (4, 1, 0)) and not cp.version_ge("garbage", (4, 1, 0))


def t_resolve_companion_base():
    # A specific bind_ip is authoritative (Companion bound to the Tailscale IP, not loopback).
    assert cp.resolve_companion_base("100.81.0.4", None) == "http://100.81.0.4:8000"
    # 0.0.0.0 (all interfaces) -> loopback works.
    assert cp.resolve_companion_base("0.0.0.0", "100.81.0.4") == "http://127.0.0.1:8000"
    # missing bind_ip -> Tailscale IP if known, else loopback.
    assert cp.resolve_companion_base("", "100.81.0.4") == "http://100.81.0.4:8000"
    assert cp.resolve_companion_base(None, None) == "http://127.0.0.1:8000"


def t_strip_relay_token_removes_only_t():
    assert cp.strip_relay_token("/console/buttons/tablet?t=abc") == "/console/buttons/tablet"
    assert cp.strip_relay_token("/console/buttons/x?a=1&t=abc&b=2") == "/console/buttons/x?a=1&b=2"
    assert cp.strip_relay_token("/console/buttons/x") == "/console/buttons/x"
    assert cp.strip_relay_token("/console/buttons/x?a=1") == "/console/buttons/x?a=1"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
