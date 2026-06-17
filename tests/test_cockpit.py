#!/usr/bin/env python3
"""Stdlib unit checks for the Commentator Cockpit. Run: python3 tests/test_cockpit.py"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ca = _load("cockpit_auth", ("src", "scripts", "cockpit_auth.py"))
m = _load("irofeeds", ("src", "relay", "racecast-feeds.py"))

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


def t_verify_rejects_malformed():
    for bad in ("", "a.b", "a.b.c.d", "alpha.notint.deadbeef" + "0" * 24,
                "BADKEY.1." + "0" * 32, "alpha-racing.1.short"):
        assert ca.verify_token(SECRET, bad) is None, bad


def t_streamer_key_matches_asset_key():
    """cockpit_auth.streamer_key must behave identically to relay asset_key()."""
    for s in ("Alpha Racing", "  Beta!#1 ", "Ümlaut x", "a-b_c d", "", "  "):
        assert ca.streamer_key(s) == m.asset_key(s), s


def t_verify_token_version_check():
    tok_v1 = ca.mint_token(SECRET, "alpha", version=1)
    assert ca.verify_token(SECRET, tok_v1, {"alpha": 1}) == "alpha"
    assert ca.verify_token(SECRET, tok_v1, {"alpha": 2}) is None   # stale version
    assert ca.verify_token(SECRET, tok_v1, {}) == "alpha"          # default 1
    tok_v2 = ca.mint_token(SECRET, "alpha", version=2)
    assert ca.verify_token(SECRET, tok_v2, {"alpha": 2}) == "alpha"


def t_rate_limiter_fixed_window():
    rl = ca.RateLimiter(limit=2, window_s=60)
    assert rl.allow("ip", now=0) is True
    assert rl.allow("ip", now=1) is True
    assert rl.allow("ip", now=2) is False      # 3rd hit in window -> blocked
    assert rl.allow("other", now=2) is True    # counter is per-key
    assert rl.allow("ip", now=61) is True       # window reset


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
