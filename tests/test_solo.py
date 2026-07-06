#!/usr/bin/env python3
"""Stdlib unit checks for solo relay mode (#302). Run: python3 tests/test_solo.py"""
import importlib.util, os, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOGDIR = tempfile.mkdtemp(prefix="racecast-test-solo-")
spec = importlib.util.spec_from_file_location(
    "irofeeds_solo", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def _solo_relay():
    return m.Relay(None, [], LOGDIR, solo=True, sheet_id="abc", league_name="Solo")


def t_solo_relay_has_no_feeds():
    r = _solo_relay()
    assert r.solo is True
    assert r.feeds == {}
    assert r.race_source is None and r.qual_source is None
    assert r.pov is None                      # no pov_source passed


def t_endurance_relay_still_has_ab_and_solo_false():
    class _Src:
        def get(self): return ["u1", "u2"]
        def get_rows(self): return [("u1", "", "", 1), ("u2", "", "", 2)]
        def refresh(self, timeout=None): pass
        def health(self): return {"ok": True}
    r = m.Relay(_Src(), [53001, 53002], LOGDIR)
    assert r.solo is False
    assert set(r.feeds) == {"A", "B"}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
