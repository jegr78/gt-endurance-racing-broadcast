#!/usr/bin/env python3
"""Stdlib unit checks for the Commentator Cockpit. Run: python3 tests/test_cockpit.py"""
import importlib.util
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ca = _load("cockpit_auth", ("src", "scripts", "cockpit_auth.py"))
m = _load("irofeeds", ("src", "relay", "racecast-feeds.py"))
cad = _load("cockpit_admin", ("src", "scripts", "cockpit_admin.py"))

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


def t_versions_default_and_bump():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cockpit-versions.json")
        assert cad.load_versions(p) == {}                 # missing -> {}
        assert cad.current_version({}, "alpha") == 1      # default 1
        assert cad.bump_version(p, "alpha") == 2          # 1 -> 2, persisted
        assert cad.load_versions(p) == {"alpha": 2}
        assert cad.bump_version(p, "alpha") == 3


def t_revoked_token_rejected_after_bump():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cockpit-versions.json")
        tok_v1 = ca.mint_token(SECRET, "alpha", version=1)
        assert ca.verify_token(SECRET, tok_v1, cad.load_versions(p)) == "alpha"
        cad.bump_version(p, "alpha")                       # now current = 2
        assert ca.verify_token(SECRET, tok_v1, cad.load_versions(p)) is None
        tok_v2 = ca.mint_token(SECRET, "alpha", version=2)
        assert ca.verify_token(SECRET, tok_v2, cad.load_versions(p)) == "alpha"


def t_apply_pulled_validates():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cockpit-versions.json")
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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
