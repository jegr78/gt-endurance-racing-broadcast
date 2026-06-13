#!/usr/bin/env python3
"""Stdlib unit checks for live-failure-visibility: cookie_health, resolve_hls
error propagation, Feed phases, Relay.status() contract.
Run: python3 tests/test_health.py"""
import importlib.util, os, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_cookie_health_no_path():
    # Running cookie-less (public streams) is legitimate: never stale.
    assert m.cookie_health(None) == {"present": False, "age_h": None, "stale": False}


def t_cookie_health_missing_file():
    h = m.cookie_health(os.path.join(HERE, "no-such-cookies.txt"))
    assert h == {"present": False, "age_h": None, "stale": False}


def t_cookie_health_fresh_and_stale():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "cookies.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# Netscape HTTP Cookie File\n")
        mtime = os.path.getmtime(path)
        fresh = m.cookie_health(path, now=mtime + 3600)
        assert fresh == {"present": True, "age_h": 1.0, "stale": False}, fresh
        stale = m.cookie_health(path, now=mtime + 14 * 3600)
        assert stale["present"] is True and stale["stale"] is True
        assert round(stale["age_h"]) == 14


def t_cookie_max_age_matches_preflight():
    # One source of truth: 12 h, same as preflight.cookies_status default.
    assert m.COOKIE_MAX_AGE_H == 12


class _FakeRun:
    def __init__(self, stdout="", stderr=""):
        self.stdout, self.stderr = stdout, stderr


def t_resolve_hls_success_returns_url_and_no_error():
    orig = m.subprocess.run
    m.subprocess.run = lambda *a, **k: _FakeRun(stdout="https://hls.example/x.m3u8\n")
    try:
        url, err = m.resolve_hls("https://yt.example/x", None, os.devnull)
    finally:
        m.subprocess.run = orig
    assert url == "https://hls.example/x.m3u8" and err is None


def t_resolve_hls_failure_returns_last_stderr_line():
    orig = m.subprocess.run
    m.subprocess.run = lambda *a, **k: _FakeRun(
        stderr="WARNING: noise\nERROR: This live event will begin in 2 hours\n")
    try:
        url, err = m.resolve_hls("https://yt.example/x", None, os.devnull)
    finally:
        m.subprocess.run = orig
    assert url is None
    assert "live event will begin" in err


def t_resolve_hls_failure_without_stderr_says_not_live():
    orig = m.subprocess.run
    m.subprocess.run = lambda *a, **k: _FakeRun()
    try:
        url, err = m.resolve_hls("https://yt.example/x", None, os.devnull)
    finally:
        m.subprocess.run = orig
    assert url is None and err == "not live?"


def t_feed_initial_phase_is_idle():
    f = m.Feed("A", 53001, 0, lambda: [], HERE)
    assert f.phase == "idle"
    assert f.last_error is None
    assert isinstance(f.phase_since, float)


def t_set_phase_updates_since_only_on_change():
    f = m.Feed("A", 53001, 0, lambda: [], HERE)
    f._set_phase("connecting")
    assert f.phase == "connecting"
    since = f.phase_since
    f._set_phase("connecting")          # same phase -> timestamp untouched
    assert f.phase_since == since       # duration accumulates across retries
    f._set_phase("serving")
    assert f.phase == "serving" and f.phase_since >= since


def _mk_relay(td, items, cookies=None, pov_items=None):
    src = m.ScheduleSource(None, os.path.join(td, "cache.txt"), None)
    src.items = list(items)
    src.rows = [(u, "", "", i + 1) for i, u in enumerate(items)]
    pov_src = None
    if pov_items is not None:
        pov_src = m.ScheduleSource(None, os.path.join(td, "pov-cache.txt"), None)
        pov_src.items = list(pov_items)
        pov_src.rows = [(u, "", "", i + 1) for i, u in enumerate(pov_items)]
    return m.Relay(src, [53001, 53002], td, cookies,
                   pov_source=pov_src, pov_port=53003 if pov_src else None)


def t_status_reports_feed_state_age_and_error():
    with tempfile.TemporaryDirectory() as td:
        r = _mk_relay(td, ["https://youtu.be/a", "https://youtu.be/b"])
        r.A._set_phase("serving")
        r.B._set_phase("connecting")
        r.B.last_error = "ERROR: This live event will begin in 2 hours"
        st = r.status()
        assert st["feeds"]["A"]["state"] == "serving"
        assert st["feeds"]["B"]["state"] == "connecting"
        assert st["feeds"]["B"]["last_error"].startswith("ERROR:")
        assert st["feeds"]["A"]["last_error"] is None
        assert st["feeds"]["A"]["state_age_s"] >= 0
        # existing keys unchanged
        assert st["feeds"]["A"]["stint"] == 1 and st["feeds"]["A"]["port"] == 53001
        assert st["cookies"] is False


def t_status_cookies_health_no_cookies():
    with tempfile.TemporaryDirectory() as td:
        r = _mk_relay(td, ["https://youtu.be/a"])
        st = r.status()
        assert st["cookies_health"] == {"present": False, "age_h": None, "stale": False}


def t_status_cookies_health_stale_file():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "cookies.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("x\n")
        old = os.path.getmtime(path) - 14 * 3600
        os.utime(path, (old, old))
        r = _mk_relay(td, ["https://youtu.be/a"], cookies=path)
        st = r.status()
        assert st["cookies_health"]["present"] is True
        assert st["cookies_health"]["stale"] is True


def t_status_pov_stopped_when_paused_with_age():
    with tempfile.TemporaryDirectory() as td:
        r = _mk_relay(td, ["https://youtu.be/a"], pov_items=["https://youtu.be/p"])
        st = r.status()                      # POV starts paused
        assert st["pov"]["state"] == "stopped"
        assert st["pov"]["state_age_s"] >= 0
        assert st["pov"]["url"] == "https://youtu.be/p"   # existing key kept


def t_cookie_health_vanished_file_treated_as_absent():
    # The cookies file can be swapped/deleted mid-poll (racecast cookies refresh
    # while the relay runs) — must degrade to absent, never raise.
    with tempfile.TemporaryDirectory() as td:
        gone = os.path.join(td, "soon-gone.txt")
        with open(gone, "w", encoding="utf-8") as fh:
            fh.write("x\n")
        os.remove(gone)
        assert m.cookie_health(gone) == {"present": False, "age_h": None, "stale": False}


# --------------------------------------------------------------------------
# Live OBS-reachability probe behind /status's obs.reachable
# --------------------------------------------------------------------------
def t_should_probe_obs_throttles_and_respects_inflight():
    # first call (last_ts=0, idle) -> probe
    assert m.should_probe_obs(0.0, False, 1000.0, 5.0) is True
    # within the interval -> skip
    assert m.should_probe_obs(998.0, False, 1000.0, 5.0) is False
    # interval elapsed -> probe again (>= boundary counts)
    assert m.should_probe_obs(995.0, False, 1000.0, 5.0) is True
    # a probe already in flight -> never launch a second
    assert m.should_probe_obs(0.0, True, 1000.0, 5.0) is False


class _FakeObs:
    """Stand-in for the obs_ws module: probe() returns a canned (reachable, note)."""
    def __init__(self, reachable, note):
        self._result = (reachable, note)
        self.calls = 0

    def probe(self):
        self.calls += 1
        return self._result


def t_status_obs_field_reports_probed_reachability():
    # status() surfaces self.obs_reachable verbatim (the probe owns it), and the
    # default before any probe is None ("unknown" -> panel shows no banner).
    orig = m._obs_ws
    m._obs_ws = None                       # disable the live probe for determinism
    try:
        with tempfile.TemporaryDirectory() as td:
            r = _mk_relay(td, ["https://youtu.be/a", "https://youtu.be/b"])
            assert r.status()["obs"] == {"reachable": None, "note": None}
            r.obs_reachable = False
            r.obs_note = "OBS WebSocket not reachable on 127.0.0.1:4455 (OBS not running?)"
            st = r.status()
            assert st["obs"]["reachable"] is False
            assert "not reachable" in st["obs"]["note"]
            r.obs_reachable = True
            r.obs_note = None
            assert r.status()["obs"] == {"reachable": True, "note": None}
    finally:
        m._obs_ws = orig


def t_run_obs_probe_records_live_result_and_clears_inflight():
    orig = m._obs_ws
    try:
        with tempfile.TemporaryDirectory() as td:
            r = _mk_relay(td, ["https://youtu.be/a", "https://youtu.be/b"])
            r._obs_probe_running = True               # as set by _maybe_probe_obs
            m._obs_ws = _FakeObs(True, "")
            r._run_obs_probe()
            assert r.obs_reachable is True
            assert r.obs_note is None                 # "" normalizes to None
            assert r._obs_probe_running is False
            # an unreachable result records the reason and stays False
            r._obs_probe_running = True
            m._obs_ws = _FakeObs(False, "OBS not running?")
            r._run_obs_probe()
            assert r.obs_reachable is False
            assert r.obs_note == "OBS not running?"
            assert r._obs_probe_running is False
    finally:
        m._obs_ws = orig


def t_maybe_probe_obs_is_noop_without_client():
    orig = m._obs_ws
    m._obs_ws = None
    try:
        with tempfile.TemporaryDirectory() as td:
            r = _mk_relay(td, ["https://youtu.be/a", "https://youtu.be/b"])
            r._maybe_probe_obs(1000.0)
            assert r.obs_reachable is None
            assert r._obs_probe_running is False
    finally:
        m._obs_ws = orig


def t_maybe_probe_obs_throttles_repeat_calls():
    orig = m._obs_ws
    try:
        with tempfile.TemporaryDirectory() as td:
            r = _mk_relay(td, ["https://youtu.be/a", "https://youtu.be/b"])
            fake = _FakeObs(True, "")
            m._obs_ws = fake
            t = r._maybe_probe_obs(1000.0)
            assert t is not None; t.join(timeout=2)
            assert fake.calls == 1
            # immediate second call within the interval must not re-probe
            assert r._maybe_probe_obs(1001.0) is None
            assert fake.calls == 1
            # past the interval -> a fresh probe runs
            t = r._maybe_probe_obs(1000.0 + m.OBS_PROBE_INTERVAL_S + 0.1)
            assert t is not None; t.join(timeout=2)
            assert fake.calls == 2
    finally:
        m._obs_ws = orig


def t_maybe_probe_obs_disabled_returns_none_without_client():
    orig = m._obs_ws
    m._obs_ws = None
    try:
        with tempfile.TemporaryDirectory() as td:
            r = _mk_relay(td, ["https://youtu.be/a", "https://youtu.be/b"])
            assert r._maybe_probe_obs(1000.0) is None
    finally:
        m._obs_ws = orig


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
