#!/usr/bin/env python3
"""Stdlib unit checks for the POV additions. Run: python3 tests/test_pov.py"""
import importlib.util, json, os, tempfile
import threading, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# Feed opens a per-feed log at construction (configure_logging). Point every
# Feed/Relay logdir at a throwaway temp dir so the suite never writes feed_*.log
# into the repo tree.
LOGDIR = tempfile.mkdtemp(prefix="racecast-test-logs-")
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class _FakeSource:
    def __init__(self, items): self.items = list(items)
    def get(self): return self.items
    def get_rows(self): return [(u, "", "", i + 1) for i, u in enumerate(self.items)]
    def refresh(self, timeout=None): pass
    def health(self): return {"ok": True}


_URLS8 = [f"https://www.youtube.com/watch?v=stint{i}" for i in range(1, 9)]


def _serve(relay):
    srv = m.ThreadingHTTPServer(("127.0.0.1", 0), m.make_handler(relay))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def t_benign_client_disconnect_classifies_aborts():
    # A browser source / panel tab that closes mid-response trips one of these;
    # they are the client's doing, never a relay fault, so they must be swallowed
    # (ConnectionAbortedError == WinError 10053 from issue #25).
    assert m._benign_client_disconnect(ConnectionAbortedError())
    assert m._benign_client_disconnect(ConnectionResetError())
    assert m._benign_client_disconnect(BrokenPipeError())
    # real faults must still surface (a generic OSError is NOT a ConnectionError).
    assert not m._benign_client_disconnect(ValueError("real bug"))
    assert not m._benign_client_disconnect(OSError("disk full"))
    assert not m._benign_client_disconnect(None)


def t_no_window_kwargs_per_os():
    # The relay daemon runs DETACHED (no console), so its yt-dlp/streamlink/
    # tailscale children would each pop a terminal window on Windows (issue #30).
    # CREATE_NO_WINDOW only on Windows; a no-op (empty kwargs) everywhere else so
    # the same spawn site stays cross-platform.
    assert m._no_window_kwargs("nt") == {"creationflags": 0x08000000}
    assert m._no_window_kwargs("posix") == {}
    assert m._no_window_kwargs("java") == {}


def t_parse_one_url():
    items = m.ScheduleSource._parse_csv("url\nhttps://www.youtube.com/watch?v=abc123\n")
    assert items == ["https://www.youtube.com/watch?v=abc123"], items


def t_parse_empty_is_none():
    assert m.ScheduleSource._parse_csv("url\n\n") is None


def t_pov_format_constant():
    assert m.YTDLP_FORMAT_POV == "b[height<=720]/b"


def t_preview_source_onair_uses_obs():
    keys = {"A", "B"}
    assert m.preview_source("A", "A", False, keys) == ("obs", "Feed A")
    assert m.preview_source("B", "B", False, keys) == ("obs", "Feed B")


def t_preview_source_offair_uses_pull():
    keys = {"A", "B"}
    assert m.preview_source("B", "A", False, keys) == ("pull", "B")
    assert m.preview_source("A", "B", False, keys) == ("pull", "A")


def t_preview_source_pov_active_vs_paused():
    keys = {"A", "B", "POV"}
    assert m.preview_source("POV", "A", True, keys) == ("obs", "Feed POV")
    assert m.preview_source("POV", "A", False, keys) == ("placeholder", "pov off")


def t_preview_source_unconfigured_feed_is_placeholder():
    assert m.preview_source("B", "A", False, {"A"}) == ("placeholder", "feed off")


def t_preview_source_unknown_target_is_placeholder():
    assert m.preview_source("X", "A", False, {"A", "B"}) == ("placeholder", "unknown feed")


def t_feed_paused_returns_none():
    f = m.Feed("POV", 53003, 0, lambda: ["https://youtu.be/x"], LOGDIR)
    f.paused = True
    assert f.current_channel() == (None, 0)
    f.paused = False
    ch, i = f.current_channel()
    assert ch == "https://youtu.be/x" and i == 0


def t_feed_has_fmt_attr():
    f = m.Feed("POV", 53003, 0, lambda: [], LOGDIR, fmt="b[height<=720]/b")
    assert f.fmt == "b[height<=720]/b"


def t_feed_fast_exit_error_flags_immediate_bind_failure():
    # #143: streamlink that dies almost instantly with a non-zero code = a failed
    # --player-external-http bind (orphan holds the port). Surface it as last_error.
    msg = m.feed_fast_exit_error(0.2, 1)
    assert msg and "port in use" in msg


def t_feed_fast_exit_error_ignores_clean_and_long_exits():
    # The normal serving path must NEVER set a spurious error.
    assert m.feed_fast_exit_error(0.2, 0) is None       # clean exit (stream ended)
    assert m.feed_fast_exit_error(0.2, None) is None    # never finished / unknown rc
    assert m.feed_fast_exit_error(120.0, 1) is None     # served a while, then died
    assert m.feed_fast_exit_error(None, 1) is None      # no timing available


def t_status_surfaces_feed_last_error():
    # Once Feed.last_error is set, /status (per-feed payload) shows it so the panel
    # stops displaying a silent 'connecting' (the #133 mystery).
    r = _relay(["a", "b"])
    r.A.last_error = m.feed_fast_exit_error(0.2, 1)
    assert r.status()["feeds"]["A"]["last_error"] == "feed exited immediately — port in use? see feed log"


def t_serve_exit_is_drop():
    # A serving feed's process exited. It's an unexpected DROP (lost live picture)
    # only when the exit was NOT intentional — not a relay stop, not a handover/
    # reload (advance). This keeps the panel alert off during normal handovers.
    assert m.serve_exit_is_drop(stopped=False, advancing=False) is True
    assert m.serve_exit_is_drop(stopped=True, advancing=False) is False   # relay stopping
    assert m.serve_exit_is_drop(stopped=False, advancing=True) is False   # handover/reload
    assert m.serve_exit_is_drop(stopped=True, advancing=True) is False


def t_dead_serve_backoff_escalates_and_caps():
    # base, 2x, 4x, 8x with the default base (RETRY_SLEEP = 10)
    assert m.dead_serve_backoff(1) == 10
    assert m.dead_serve_backoff(2) == 20
    assert m.dead_serve_backoff(3) == 40
    assert m.dead_serve_backoff(4) == 80
    # capped at DEAD_SERVE_BACKOFF_CAP (300)
    assert m.dead_serve_backoff(6) == 300
    assert m.dead_serve_backoff(100) == 300
    # count below 1 falls back to the base (defensive)
    assert m.dead_serve_backoff(0) == 10
    # explicit base/cap honoured
    assert m.dead_serve_backoff(3, base=5, cap=15) == 15   # 5*4=20 -> capped to 15


def t_should_idle_dead_serves_at_limit():
    assert m.should_idle_dead_serves(4) is False
    assert m.should_idle_dead_serves(5) is True            # DEAD_SERVE_IDLE_AFTER == 5
    assert m.should_idle_dead_serves(6) is True
    assert m.should_idle_dead_serves(2, limit=2) is True   # custom limit
    assert m.should_idle_dead_serves(1, limit=2) is False


def t_feed_starts_not_dropped():
    f = m.Feed("A", 53001, 0, lambda: ["a"], LOGDIR)
    assert f.dropped is False


def t_status_surfaces_feed_down():
    # Once a feed is marked dropped, /status flags it down so the panel can raise
    # a distinct alarm; a paused/stopped feed is never 'down' (intentional).
    r = _relay(["a", "b"])
    assert r.status()["feeds"]["A"]["down"] is False
    r.A.dropped = True
    assert r.status()["feeds"]["A"]["down"] is True
    assert r.status()["feeds"]["B"]["down"] is False
    r.A.paused = True                          # paused beats dropped -> not an alarm
    assert r.status()["feeds"]["A"]["down"] is False


def t_reload_and_set_index_clear_dropped():
    # Director intervention (reload / reposition) acknowledges the drop: the alarm
    # clears, and re-fires only if the feed drops again.
    f = m.Feed("A", 53001, 0, lambda: ["a", "b"], LOGDIR)
    f.dropped = True
    f.reload()
    assert f.dropped is False
    f.dropped = True
    f.set_index(1)
    assert f.dropped is False


def t_current_channel_idles_past_end():
    # idx beyond the schedule -> idle (None), NOT a clamp onto the last stint
    f = m.Feed("B", 53002, 1, lambda: ["https://youtu.be/only"], LOGDIR)
    assert f.current_channel() == (None, 1)        # one link, B on slot 2 -> idle
    f2 = m.Feed("B", 53002, 0, lambda: ["https://youtu.be/only"], LOGDIR)
    assert f2.current_channel() == ("https://youtu.be/only", 0)


def t_set_index_allows_one_past_end_for_idle():
    f = m.Feed("A", 53001, 0, lambda: ["a", "b"], LOGDIR)
    assert f.set_index(2) is True                  # len 2 -> idle slot 2 is reachable
    assert f.idx == 2
    assert f.current_channel() == (None, 2)        # idles
    f2 = m.Feed("A", 53001, 0, lambda: ["a", "b"], LOGDIR)
    assert f2.set_index(99) is True                # clamps to len (idle sentinel) from idx 0
    assert f2.idx == 2
    assert f2.set_index(99) is False               # already at the sentinel -> no-op


class _StubSource:
    def __init__(self, items, rows=None):
        self._items = list(items)
        # rows parallel to items: (url, streamer, stint, line). Default: bare.
        self._rows = list(rows) if rows is not None else [
            (u, "", "", i + 1) for i, u in enumerate(items)]
    def get(self): return list(self._items)
    def get_rows(self): return list(self._rows)
    def refresh(self, timeout=6): return True
    def health(self): return {"count": len(self._items), "last_ok_age_s": 0, "last_error": None}
    def add(self, url): self._items.append(url)


def _relay(items):
    r = m.Relay(_StubSource(items), (53001, 53002), LOGDIR)
    r._reflect = lambda live, cut: None        # isolate index logic from OBS I/O
    r._reflect_pov = lambda shown: None        # isolate POV toggle from OBS I/O
    return r


def t_next_new_live_is_the_non_advanced_feed():
    r = _relay(["s1", "s2", "s3", "s4"])
    assert (r.A.idx, r.B.idx) == (0, 1)
    assert r.live_after_next() == "B"          # B (stint2) is pre-warmed -> next live
    r.next_auto()
    assert (r.A.idx, r.B.idx) == (2, 1)        # A advanced to stint3; B now live
    assert r.live_feed() == "B"
    r.next_auto()
    assert (r.A.idx, r.B.idx) == (2, 3)        # B advanced to stint4; A now live
    assert r.live_feed() == "A"


def t_cold_start_one_link_then_add_second():
    r = _relay(["s1"])                         # start with ONE link
    assert (r.A.idx, r.B.idx) == (0, 1)
    assert r.B.current_channel() == (None, 1)  # B idles (black) on the empty slot 2
    r.source.add("s2")                         # link entered mid-event
    assert r.live_after_next() == "B"
    r.next_auto()
    assert r.live_feed() == "B" and r.B.current_channel() == ("s2", 1)


def t_next_reflects_only_when_incoming_serving():
    r = _relay(["s1", "s2", "s3", "s4"])
    calls = []
    r._reflect = lambda live, cut: calls.append((live, cut))
    r.feeds["B"].phase = "idle"                 # incoming feed not yet serving
    out = r.next_auto()
    assert out["obs_cut"] is False
    assert calls == []                          # no visibility/audio flip onto a non-serving feed
    r.feeds["A"].phase = "serving"              # next incoming feed is live
    out2 = r.next_auto()
    assert out2["obs_cut"] is True
    assert calls == [("A", True)]


def t_set_stint_reflects_live_feed_without_cut():
    r = _relay(["s1", "s2", "s3", "s4"])
    calls = []
    r._reflect = lambda live, cut: calls.append((live, cut))
    r.set_stint(3)                              # stint 3 on air -> A=2, B=3, live=A
    assert (r.A.idx, r.B.idx) == (2, 3)
    assert calls == [("A", False)]


def t_live_schedule_row_pure():
    rows = [("https://youtu.be/a", "JeGr", "Stint 1", 1),
            ("https://youtu.be/b", "GT45", "Stint 2", 2)]
    assert m.live_schedule_row(rows, 0) == {"streamer": "JeGr", "stint": "Stint 1"}
    assert m.live_schedule_row(rows, 1) == {"streamer": "GT45", "stint": "Stint 2"}
    assert m.live_schedule_row(rows, 2) is None        # idles past the end
    assert m.live_schedule_row(rows, -1) is None       # never wraps to the last row
    assert m.live_schedule_row([], 0) is None
    assert m.live_schedule_row(rows, None) is None


def t_relay_live_schedule_row_tracks_on_air_feed():
    rows = [("s1", "JeGr", "Stint 1", 1), ("s2", "GT45", "Stint 2", 2),
            ("s3", "Ann", "Stint 3", 3), ("s4", "Ben", "Stint 4", 4)]
    r = m.Relay(_StubSource(["s1", "s2", "s3", "s4"], rows), (53001, 53002), LOGDIR)
    r._reflect = lambda live, cut: None
    assert r.live_feed() == "A"                        # A on stint 1
    assert r.live_schedule_row() == {"streamer": "JeGr", "stint": "Stint 1"}
    r.next_auto()                                      # B (stint 2) now on air
    assert r.live_feed() == "B"
    assert r.live_schedule_row() == {"streamer": "GT45", "stint": "Stint 2"}


def t_on_air_row_tracks_feed_in_normal_operation():
    r = _relay(["s1", "s2", "s3", "s4"])
    assert r.on_air_row_idx() == 0                       # stint 1
    assert r.live_row_map() == {0: "A", 1: "B"}          # on-air A row0, off-air B row1
    r.next_auto()                                        # B (stint 2) on air
    assert r.on_air_row_idx() == 1
    assert r.live_feed() == "B"
    assert r.live_row_map() == {1: "B", 2: "A"}          # on-air B row1, off-air A row2
    # the HUD row follows the displayed on-air row
    rows = r.source.get_rows()
    assert m.live_schedule_row(rows, r.on_air_row_idx())["stint"] == r.live_schedule_row()["stint"]


def _relay_q(items, qual_items, qual_rows=None, mode="race"):
    race = _StubSource(items)
    qual = _StubSource(qual_items, qual_rows)
    r = m.Relay(race, (53001, 53002), LOGDIR, qual_source=qual, mode=mode)
    r._reflect = lambda live, cut: None
    return r


def t_default_mode_is_race():
    r = _relay_q(["s1", "s2"], ["q1"])
    assert r.mode == "race"
    assert r.source is r.race_source
    assert r.A.current_channel() == ("s1", 0)


def t_start_in_qualifying_mode():
    r = _relay_q(["s1", "s2"], ["q1"], mode="qualifying")
    assert r.mode == "qualifying"
    assert r.source is r.qual_source
    assert r.A.current_channel() == ("q1", 0)       # single qualifying stream on Feed A
    assert r.B.current_channel() == (None, 1)       # Feed B idles (one stream only)


def t_set_mode_switches_active_source_and_feeds():
    qrows = [("q1", "GT45", "Qualifying", 2)]
    r = _relay_q(["s1", "s2", "s3"], ["q1"], qual_rows=qrows)
    assert r.A.current_channel() == ("s1", 0)
    out = r.set_mode("qualifying")
    assert out["mode"] == "qualifying"
    assert r.source is r.qual_source
    assert (r.A.idx, r.B.idx) == (0, 1)             # stint 1: A serves q1, B idles
    assert r.A.current_channel() == ("q1", 0)
    assert r.live_schedule_row() == {"streamer": "GT45", "stint": "Qualifying"}
    r.set_mode("race")                              # back to the race schedule
    assert r.mode == "race" and r.source is r.race_source
    assert (r.A.idx, r.B.idx) == (0, 1)
    assert r.A.current_channel() == ("s1", 0)


def t_set_mode_qualifying_unavailable_without_source():
    r = _relay(["s1", "s2"])                        # no qual_source
    assert r.qual_source is None
    out = r.set_mode("qualifying")
    assert "error" in out and r.mode == "race"      # stays race


def t_set_mode_rejects_unknown():
    r = _relay_q(["s1"], ["q1"])
    assert "error" in r.set_mode("warmup")
    assert r.mode == "race"


def t_status_reports_mode_and_qualifying():
    r = _relay_q(["s1", "s2"], ["q1"])
    st = r.status()
    assert st["mode"] == "race"
    assert st["qualifying"]["active"] is False
    r.set_mode("qualifying")
    assert r.status()["qualifying"]["active"] is True


def t_next_past_end_is_idle_no_cut():
    r = _relay(["s1", "s2"])
    r.feeds["B"].phase = "serving"
    r.next_auto()                               # the one real handover: B (s2) on air
    assert r.live_feed() == "B"
    out = r.next_auto()                         # over-press past the last stint
    assert out["obs_cut"] is False              # incoming feed idle -> no cut, no crash


def t_splitscreen_state_maps_live_feed_to_current():
    r = _relay(["s1", "s2", "s3", "s4"])
    assert r.splitscreen_state() == {"current": "A", "next_active": True, "mode": "race"}
    r.next_auto()                                  # B becomes the on-air feed
    assert r.splitscreen_state()["current"] == "B"


def t_splitscreen_state_hides_next_in_qualifying():
    r = _relay_q(["s1", "s2"], ["q1"], mode="qualifying")
    st = r.splitscreen_state()
    assert st == {"current": "A", "next_active": False, "mode": "qualifying"}


def t_pov_active_tracks_pov_shown():
    r = _relay(["s1", "s2"])
    assert r.pov_active() is False               # pov_shown defaults False
    assert r.set_pov_shown(True) == {"shown": True}
    assert r.pov_active() is True
    assert r.pov_toggle() == {"shown": False}    # flips back
    assert r.pov_active() is False
    assert r.pov_toggle() == {"shown": True}     # and forward again
    assert r.pov_active() is True


def t_pov_name_reads_pov_source_row():
    r = _relay(["s1", "s2"])
    assert r.pov_name() == ""                        # no pov_source
    r.pov_source = _StubSource(["https://youtu.be/p"],
                               rows=[("https://youtu.be/p", "JeGr", "", 2)])
    assert r.pov_name() == "JeGr"
    r.pov_source = _StubSource([], rows=[])          # source but no row
    assert r.pov_name() == ""


def t_hud_page_has_pov_name_slot_and_gating():
    import os as _os
    path = _os.path.join(ROOT, "src", "obs", "hud.html")
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    # The name slot exists and is a builder slot (data-edit marker).
    assert 'id="pov-name"' in html
    assert 'data-edit="POV name"' in html
    # tick() hides the whole POV box (frame) when the POV feed is off.
    assert "povActive" in html
    assert 'getElementById("pov").classList.toggle("empty"' in html


def t_preview_program_endpoint_serves_jpeg():
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], LOGDIR)

    class FakeObs:
        def get_program_screenshot(self, **kw): return (b"\xff\xd8PGM\xff\xd9", "")
        def get_source_screenshot(self, *a, **kw): return (None, "n/a")

    old = m._obs_ws; m._obs_ws = FakeObs(); srv = _serve(r)
    try:
        port = srv.server_address[1]
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/preview/program", timeout=5)
        body = resp.read()
        assert resp.headers["Content-Type"] == "image/jpeg"
        assert resp.headers["Cache-Control"] == "no-store"
        assert body == b"\xff\xd8PGM\xff\xd9"
    finally:
        srv.shutdown(); m._obs_ws = old


def t_preview_program_503_when_obs_down():
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], LOGDIR)
    old = m._obs_ws; m._obs_ws = None; srv = _serve(r)
    try:
        port = srv.server_address[1]
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/preview/program", timeout=5)
            raise AssertionError("expected HTTP 503")
        except urllib.error.HTTPError as e:
            assert e.code == 503
    finally:
        srv.shutdown(); m._obs_ws = old


def t_obs_stream_endpoint_starts_and_validates():
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], LOGDIR)

    class FakeObs:
        def __init__(self): self.calls = []
        def set_stream(self, active, **kw):
            self.calls.append(active); return (True, "")

    fo = FakeObs(); old = m._obs_ws; m._obs_ws = fo; srv = _serve(r)
    try:
        port = srv.server_address[1]
        url = f"http://127.0.0.1:{port}/obs/stream"
        req = urllib.request.Request(
            url, data=b'{"on": true}',
            headers={"Content-Type": "application/json"}, method="POST")
        body = urllib.request.urlopen(req, timeout=5).read()
        assert json.loads(body)["ok"] is True
        assert fo.calls == [True]
        # Missing "on" -> 400
        req = urllib.request.Request(
            url, data=b'{}', headers={"Content-Type": "application/json"},
            method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("expected HTTP 400")
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        srv.shutdown(); m._obs_ws = old


def t_director_panel_has_stream_button():
    path = os.path.join(ROOT, "src", "director", "director-panel.html")
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    assert 'id="obsStreamBtn"' in html
    assert 'obsPost("stream"' in html
    assert "End the live broadcast" in html          # Stop is confirm-guarded


def t_director_panel_chat_rail_fixed_height():
    # The desktop right-rail stacks the crew chat over the read-only broadcast chat.
    # Both logs must have a *fixed* height (so the crew box never grows with messages
    # and pushes into the broadcast box), and the two boxes must not flex-shrink
    # (shrinking made the crew box spill its content over the broadcast box). Two
    # 38vh logs + chrome also overflowed the rail and produced a second scrollbar.
    path = os.path.join(ROOT, "src", "director", "director-panel.html")
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    # The unbounded grow-to-38vh cap is gone (it was the only 38vh in the file).
    assert "38vh" not in html
    # Logs get a stable, viewport-aware fixed height (clamped), not max-height growth.
    assert "details.chat#chatBox .chatlog,details.chat#bchatBox .chatlog{height:clamp(" in html
    # Boxes do not shrink below their content (flex:0 0 auto, not 0 1 auto).
    assert "details.chat#chatBox,details.chat#bchatBox{margin-bottom:0;min-height:0;flex:0 0 auto;" in html
    assert "flex:0 1 auto" not in html


def t_obs_stream_503_when_obs_down():
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], LOGDIR)
    old = m._obs_ws; m._obs_ws = None; srv = _serve(r)
    try:
        port = srv.server_address[1]
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/obs/stream", data=b'{"on": true}',
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("expected HTTP 503")
        except urllib.error.HTTPError as e:
            assert e.code == 503
    finally:
        srv.shutdown(); m._obs_ws = old


def _serve_mgr(relay, mgr):
    """Serve relay + preview_manager; return the running server."""
    srv = m.ThreadingHTTPServer(("127.0.0.1", 0),
                                m.make_handler(relay, preview_manager=mgr))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def t_preview_feed_onair_uses_obs_not_grab():
    # On-air feed: PreviewManager uses OBS screenshot (obs path, not pull).
    import logging
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], LOGDIR)   # A on air (idx 0)

    class FakeObs:
        def __init__(self): self.name = None
        def get_source_screenshot(self, name, **kw):
            self.name = name; return (b"\xff\xd8ONAIR\xff\xd9", "")

    fo = FakeObs()
    lg = logging.getLogger("test.pov.onair"); lg.addHandler(logging.NullHandler())
    mgr = m.PreviewManager(r, lambda: fo, lg)
    srv = _serve_mgr(r, mgr)
    try:
        port = srv.server_address[1]
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/preview/feed/A", timeout=5).read()
        assert body == b"\xff\xd8ONAIR\xff\xd9" and fo.name == "Feed A"
    finally:
        srv.shutdown()


def t_preview_feed_offair_uses_grab_not_obs():
    # Off-air feed, DIRECT-SERVE mode (fan-out off): PreviewManager uses the pull
    # worker (not OBS); worker returns a frame. (Fan-out on routes to the ring tap —
    # preview_source routing is covered in test_feed_preview.py.)
    import logging
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], LOGDIR)   # B off air (idx 1)
    r.fanout = False                                           # pin the direct-serve pull path
    calls = {}

    def fake_factory(target, channel, cookies, log):
        class _W:
            ok = True
            def __init__(self): self.target = target
            def stop(self): pass
            def latest_frame(self): calls["target"] = target; return b"\xff\xd8GRB\xff\xd9"
            def latest_level(self): return 0.5
        return _W()

    lg = logging.getLogger("test.pov.offair"); lg.addHandler(logging.NullHandler())
    mgr = m.PreviewManager(r, lambda: None, lg, worker_factory=fake_factory)
    srv = _serve_mgr(r, mgr)
    try:
        port = srv.server_address[1]
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/preview/feed/B", timeout=5).read()
        assert body == b"\xff\xd8GRB\xff\xd9"
        assert calls.get("target") == "B"
    finally:
        srv.shutdown()


def t_preview_feed_pov_paused_is_503():
    # No POV configured: preview_source returns placeholder → still() → (None, "pov off") → 503.
    import logging
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], LOGDIR)   # no POV configured
    lg = logging.getLogger("test.pov.pov"); lg.addHandler(logging.NullHandler())
    mgr = m.PreviewManager(r, lambda: None, lg)
    srv = _serve_mgr(r, mgr)
    try:
        port = srv.server_address[1]
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/preview/feed/POV", timeout=5)
            raise AssertionError("expected HTTP 503")
        except urllib.error.HTTPError as e:
            assert e.code == 503
    finally:
        srv.shutdown()


def t_preview_feed_unknown_is_404():
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], LOGDIR)
    srv = _serve(r)
    try:
        port = srv.server_address[1]
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/preview/feed/Z", timeout=5)
            raise AssertionError("expected HTTP 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()


def t_preview_feed_grab_failure_is_503():
    # still() returning None yields 503; preview_manager=None (disabled) yields 404.
    import logging
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], LOGDIR)   # B off air
    lg = logging.getLogger("test.pov.preview"); lg.addHandler(logging.NullHandler())

    class _StillNoneManager:
        relay = r
        def still(self, target): return (None, "unavailable")
        def levels(self): return {}

    srv_mgr = m.ThreadingHTTPServer(("127.0.0.1", 0),
                                    m.make_handler(r, preview_manager=_StillNoneManager()))
    threading.Thread(target=srv_mgr.serve_forever, daemon=True).start()
    try:
        port = srv_mgr.server_address[1]
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/preview/feed/B", timeout=5)
            raise AssertionError("expected HTTP 503")
        except urllib.error.HTTPError as e:
            assert e.code == 503
        # preview_manager=None -> 404 "preview disabled"
        srv_off = m.ThreadingHTTPServer(("127.0.0.1", 0), m.make_handler(r))
        threading.Thread(target=srv_off.serve_forever, daemon=True).start()
        try:
            port2 = srv_off.server_address[1]
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port2}/preview/feed/B", timeout=5)
                raise AssertionError("expected HTTP 404")
            except urllib.error.HTTPError as e:
                assert e.code == 404
        finally:
            srv_off.shutdown()
    finally:
        srv_mgr.shutdown()


def t_aggregate_stream_not_active_is_red():
    # Off-air only escalates once OBS has streamed at least once (stream_expected
    # latch) — a live broadcast that drops off air pages.
    h = m.aggregate_health({"obs_reachable": True, "stream_active": False,
                            "stream_expected": True})
    assert h["level"] == "red"
    assert any("not streaming" in r.lower() or "off air" in r.lower() for r in h["reasons"])


def t_aggregate_stream_not_active_pre_show_is_green():
    # OBS reachable, not streaming, but never streamed this session (no latch) ->
    # NO alarm, so a pre-show relay start never fires a CRITICAL ping.
    assert m.aggregate_health({"obs_reachable": True, "stream_active": False})["level"] == "green"
    assert m.aggregate_health({"obs_reachable": True, "stream_active": False,
                               "stream_expected": False})["level"] == "green"


def t_aggregate_stream_active_unknown_is_green():
    # OBS reachable but stream_active not sampled (None) -> no alarm.
    assert m.aggregate_health({"obs_reachable": True})["level"] == "green"
    assert m.aggregate_health({"obs_reachable": True, "stream_active": None})["level"] == "green"
    # OBS not reachable -> existing yellow path, stream_active ignored.
    assert m.aggregate_health({"obs_reachable": False, "stream_active": False,
                               "stream_expected": True})["level"] == "yellow"


def t_aggregate_yellow_signals():
    for key in ("stream_reconnecting", "funnel_down", "sheet_push_failing"):
        h = m.aggregate_health({"obs_reachable": True, "stream_active": True, key: True})
        assert h["level"] == "yellow", (key, h)
    # observational signals never escalate
    assert m.aggregate_health({"obs_reachable": True, "stream_active": True,
                               "tailscale_up": False, "companion_ok": False})["level"] == "green"


def t_parse_stream_quality():
    assert m.parse_stream_quality("[cli][info] Opening stream: 720p (hls)") == "720p"
    assert m.parse_stream_quality("[cli][info] Opening stream: source (hls)") == "source"
    assert m.parse_stream_quality("[cli][info] Opening stream: 1080p60 (muxed-stream)") == "1080p60"
    assert m.parse_stream_quality("[download] Written 5 MB") is None
    assert m.parse_stream_quality("") is None


def t_sample_connectivity_sets_state_and_expected():
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], LOGDIR)
    # Monkeypatch the module-level references that _sample_connectivity uses.
    orig_funnel = m.tailscale.funnel_on
    orig_backend = m.tailscale.tailscale_backend
    orig_reachable = m.companion_common.companion_reachable
    try:
        # Never-expected case: funnel down before ever seen up -> neutral (None).
        r2 = m.Relay(_FakeSource(_URLS8), [53001, 53002], LOGDIR)
        m.tailscale.funnel_on = lambda *a, **k: False
        m.tailscale.tailscale_backend = lambda *a, **k: ("ts", "Running", "100.64.0.1")
        m.companion_common.companion_reachable = lambda *a, **k: True
        r2._sample_connectivity()
        assert r2.conn_state["funnel_ok"] is None    # neutral, not red
        assert r2.funnel_expected is False

        m.tailscale.funnel_on = lambda *a, **k: True
        m.tailscale.tailscale_backend = lambda *a, **k: ("ts", "Running", "100.64.0.1")
        m.companion_common.companion_reachable = lambda *a, **k: False
        r._sample_connectivity()
        assert r.conn_state["funnel_ok"] is True
        assert r.conn_state["tailscale_up"] is True
        assert r.conn_state["companion_ok"] is False
        assert r.funnel_expected is True           # latched once seen up
        # Funnel later down, but expected stays latched -> funnel_down derivable.
        m.tailscale.funnel_on = lambda *a, **k: False
        r._sample_connectivity()
        assert r.conn_state["funnel_ok"] is False  # real regression: was expected
        assert r.funnel_expected is True
    finally:
        m.tailscale.funnel_on = orig_funnel
        m.tailscale.tailscale_backend = orig_backend
        m.companion_common.companion_reachable = orig_reachable


def _make_min_relay():
    """Minimal Relay for snapshot/facts tests — two stints, temp log dir."""
    return m.Relay(_FakeSource(_URLS8), [53001, 53002], LOGDIR)


def t_health_snapshot_carries_new_fields():
    relay = _make_min_relay()
    relay.obs_stats = {"obs_cpu_pct": 10.0, "obs_fps": 60.0, "stream_active": True,
                       "stream_reconnecting": False, "stream_congestion": 0.1,
                       "stream_dropped_pct": 0.0, "stream_kbps": 6000.0,
                       "obs_mem_mb": 900.0, "obs_disk_free_mb": 5000.0,
                       "obs_render_skipped_pct": 0.0}
    relay.conn_state = {"funnel_ok": True, "tailscale_up": True, "companion_ok": False}
    relay.funnel_expected = True
    relay.feeds["A"].quality = "720p"
    snap = relay._health_snapshot(123.0)
    assert snap["obs_cpu_pct"] == 10.0 and snap["stream_active"] == 1
    assert snap["funnel_ok"] == 1 and snap["companion_ok"] == 0
    assert snap["feed_a_quality"] == "720p"
    # All COLUMNS keys present (record() tolerates missing, but emit them explicitly).
    hs = m.health_store
    for col in hs.COLUMNS:
        if col not in ("kind",):
            assert col in snap, col


def t_health_facts_gate_funnel_and_push():
    relay = _make_min_relay()
    relay.obs_reachable = True
    relay.obs_stats = {"stream_active": True, "stream_reconnecting": True}
    relay.conn_state = {"funnel_ok": False, "tailscale_up": True, "companion_ok": True}
    relay.funnel_expected = True                  # funnel was up, now down -> funnel_down
    facts = relay._health_facts(1.0)
    assert facts["stream_reconnecting"] is True
    assert facts["funnel_down"] is True
    # funnel never seen up -> not a fault
    relay.funnel_expected = False
    assert relay._health_facts(1.0)["funnel_down"] is False


def t_health_facts_stream_expected_gates_off_air():
    # _health_facts must propagate the stream_expected latch (off until OBS has
    # streamed, then on). The aggregate LEVEL mapping is covered by the
    # t_aggregate_stream_not_active_* tests with EXPLICIT facts — we don't assert it
    # via _health_facts here, because _health_facts also samples ambient signals
    # (tailscale_present etc.) that would make a level assertion env-dependent.
    relay = _make_min_relay()
    relay.obs_reachable = True
    relay.obs_stats = {"stream_active": False}     # OBS reachable but not streaming
    relay.stream_expected = False
    facts = relay._health_facts(1.0)
    assert facts["stream_expected"] is False
    assert facts["stream_active"] is False
    # once OBS has streamed, the latch flips the gate fact on
    relay.stream_expected = True
    assert relay._health_facts(1.0)["stream_expected"] is True


def t_pull_slots_basic():
    def rows(urls): return [(u, "", "", i + 1) for i, u in enumerate(urls)]
    assert m.pull_slots(rows(["a", "b", "b", "d"])) == [0, 1, 1, 2]   # back-to-back b
    assert m.pull_slots(rows(["a", "b", "a"])) == [0, 1, 2]           # non-consecutive != run
    assert m.pull_slots(rows(["b", "b", "b"])) == [0, 0, 0]           # three in a row
    assert m.pull_slots(rows(["", ""])) == [0, 1]                     # blanks never merge
    assert m.pull_slots(rows(["a", "", "a"])) == [0, 1, 2]            # blank breaks the run
    assert m.pull_slots([]) == []


def t_slot_row_helpers():
    slots = [0, 1, 1, 2]
    assert m.slot_first_row(slots, 1) == 1
    assert m.slot_first_row(slots, 2) == 3
    assert m.slot_first_row(slots, 9) is None
    # off-air preload / freed-feed target skips the same-URL run:
    assert m.next_slot_first_row(slots, 0) == 1      # after slot0 -> row1 (b)
    assert m.next_slot_first_row(slots, 1) == 3      # after slot1 (b,b) -> row3 (d), NOT row2
    assert m.next_slot_first_row(slots, 3) == 4      # after last slot -> idle sentinel (len)
    assert m.next_slot_first_row([], 0) == 0
    # continuation detection:
    assert m.is_continuation(slots, 2) is True       # row2 continues row1 (same b)
    assert m.is_continuation(slots, 1) is False      # row1 is a new slot
    assert m.is_continuation(slots, 0) is False      # no row -1
    assert m.is_continuation(slots, 4) is False      # past the end


def t_slot_start_indices():
    def rows(urls): return [(u, "", "", i + 1) for i, u in enumerate(urls)]
    # normal schedule: identical to stint_start_indices (every row its own slot)
    assert m.slot_start_indices(3, rows(["a", "b", "c", "d"])) == (2, 3)
    # takeover onto the SECOND row of a back-to-back (stint 3 = second b):
    # Feed A parks on the slot HEAD (row1), Feed B preloads the next slot (row3)
    assert m.slot_start_indices(3, rows(["a", "b", "b", "d"])) == (1, 3)
    # takeover onto the FIRST b (stint 2): A row1, B skips the duplicate -> row3
    assert m.slot_start_indices(2, rows(["a", "b", "b", "d"])) == (1, 3)
    # empty schedule falls back
    assert m.slot_start_indices(1, []) == (0, 1)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
