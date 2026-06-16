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


def t_status_live_and_league_block():
    # Takeover reads the on-air feed/stint + league key from /status so producer B
    # never has to guess.
    with tempfile.TemporaryDirectory() as td:
        r = _mk_relay(td, ["a", "b", "c", "d"])   # A idx0/stint1, B idx1/stint2
        r.sheet_id = "SHEET123"
        st = r.status()
        assert st["live"] == {"feed": "A", "stint": 1, "mode": "race"}
        assert st["league"] == {"sheet_id": "SHEET123"}
        r.A.idx = 2                               # after a handover B is on air
        assert r.status()["live"] == {"feed": "B", "stint": 2, "mode": "race"}


def t_status_league_sheet_id_none_when_unset():
    with tempfile.TemporaryDirectory() as td:
        r = _mk_relay(td, ["a", "b"])
        assert r.status()["league"] == {"sheet_id": None}


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


# --------------------------------------------------------------------------
# Aggregate health (live heartbeat) — pure evaluation, transition, payload
# --------------------------------------------------------------------------
def _facts(**kw):
    base = {"feeds_down": [], "feeds_connecting_long": [], "cookies_stale": False,
            "obs_reachable": True, "tailscale_present": True}
    base.update(kw)
    return base


def t_aggregate_health_green_when_all_ok():
    h = m.aggregate_health(_facts())
    assert h["level"] == "green" and h["reasons"] == []


def t_aggregate_health_red_on_feed_down():
    h = m.aggregate_health(_facts(feeds_down=["A"]))
    assert h["level"] == "red"
    assert any("Feed A" in r and "down" in r.lower() for r in h["reasons"])


def t_aggregate_health_yellow_causes():
    # each non-feed-down problem is yellow on its own
    assert m.aggregate_health(_facts(obs_reachable=False))["level"] == "yellow"
    assert m.aggregate_health(_facts(cookies_stale=True))["level"] == "yellow"
    assert m.aggregate_health(_facts(tailscale_present=False))["level"] == "yellow"
    assert m.aggregate_health(_facts(feeds_connecting_long=["B"]))["level"] == "yellow"


def t_aggregate_health_obs_unknown_is_not_yellow():
    # obs_reachable None = not probed yet -> must not raise a false alarm
    assert m.aggregate_health(_facts(obs_reachable=None))["level"] == "green"


def t_aggregate_health_red_lists_underlying_yellows():
    h = m.aggregate_health(_facts(feeds_down=["A"], cookies_stale=True))
    assert h["level"] == "red"
    assert any("Feed A" in r for r in h["reasons"])
    assert any("cookie" in r.lower() for r in h["reasons"])


def t_health_should_notify_transitions_only():
    # first tick: announce only a non-green baseline
    assert m.health_should_notify(None, "green") is False
    assert m.health_should_notify(None, "red") is True
    # no change -> silent (anti-spam over a multi-hour race)
    assert m.health_should_notify("red", "red") is False
    assert m.health_should_notify("green", "green") is False
    # any change -> notify (degrade AND recover)
    assert m.health_should_notify("green", "yellow") is True
    assert m.health_should_notify("red", "green") is True
    assert m.health_should_notify("yellow", "red") is True


def t_discord_health_payload_shape_and_color():
    red = m.discord_health_payload("red", ["Feed A down"], prev_level="green")
    emb = red["embeds"][0]
    assert emb["color"] == m.HEALTH_COLORS["red"]
    assert "Feed A down" in emb["description"]
    # recovery wording when returning to green
    ok = m.discord_health_payload("green", [], prev_level="red")
    assert ok["embeds"][0]["color"] == m.HEALTH_COLORS["green"]
    assert "recover" in (ok["embeds"][0]["title"] + ok["embeds"][0]["description"]).lower()


def t_status_includes_health():
    orig = m.detect_tailscale_ip
    m.detect_tailscale_ip = lambda: "100.64.0.9"     # present -> no false yellow in CI
    try:
        with tempfile.TemporaryDirectory() as td:
            r = _mk_relay(td, ["https://youtu.be/a", "https://youtu.be/b"])
            # status() kicks off a throttled async OBS probe; on a loaded CI runner
            # it can finish and overwrite obs_reachable=False before status() reads
            # the health facts, flipping green->yellow. Disable it so the assertion
            # reflects the value we set, not a probe race (flaky macos-3.12, #189 CI).
            r._maybe_probe_obs = lambda now: None
            r.obs_reachable = True
            h = r.status()["health"]
            assert h["level"] == "green" and h["reasons"] == [] and "since_s" in h
            r.A.dropped = True                        # lost a live feed -> red
            assert r.status()["health"]["level"] == "red"
    finally:
        m.detect_tailscale_ip = orig


def t_status_refresh_does_not_consume_notification_baseline():
    # /status refreshes the DISPLAYED level every 2 s but must never advance the
    # webhook baseline — else the 30 s heartbeat would miss the transition.
    orig = m.detect_tailscale_ip
    m.detect_tailscale_ip = lambda: "100.64.0.9"
    try:
        with tempfile.TemporaryDirectory() as td:
            r = _mk_relay(td, ["https://youtu.be/a", "https://youtu.be/b"])
            r.obs_reachable = True
            r.A.dropped = True
            r.status(); r.status()
            assert r.health_level == "red"            # display followed the drop
            assert r._notified_level is None          # baseline untouched by /status
            assert m.health_should_notify(r._notified_level, r.health_level) is True
    finally:
        m.detect_tailscale_ip = orig


def t_send_health_webhook_noop_without_url():
    # No URL configured -> push disabled, never raises (health display still works).
    with tempfile.TemporaryDirectory() as td:
        r = _mk_relay(td, ["https://youtu.be/a"])
        assert r.discord_webhook_url is None
        r._send_health_webhook("red", ["Feed A down"], None)   # must not raise


def t_send_health_webhook_sets_user_agent():
    # Discord sits behind Cloudflare, which 403s the default "Python-urllib/x.y"
    # User-Agent -> the POST silently never arrives. The request MUST carry an
    # explicit User-Agent (the rest of the relay already does). Regression guard.
    with tempfile.TemporaryDirectory() as td:
        r = _mk_relay(td, ["https://youtu.be/a"])
        r.discord_webhook_url = "https://discord.test/api/webhooks/1/abc"
        captured = {}

        class _Resp:
            def read(self): return b""

        def fake_urlopen(req, timeout=None):
            captured["req"] = req
            return _Resp()

        orig = m.urlopen
        m.urlopen = fake_urlopen
        try:
            r._send_health_webhook("red", ["Feed A down"], None)
        finally:
            m.urlopen = orig
        ua = captured["req"].get_header("User-agent")
        assert ua and "racecast" in ua.lower(), ua


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
