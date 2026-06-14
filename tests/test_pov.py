#!/usr/bin/env python3
"""Stdlib unit checks for the POV additions. Run: python3 tests/test_pov.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


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


def t_feed_paused_returns_none():
    f = m.Feed("POV", 53003, 0, lambda: ["https://youtu.be/x"], HERE)
    f.paused = True
    assert f.current_channel() == (None, 0)
    f.paused = False
    ch, i = f.current_channel()
    assert ch == "https://youtu.be/x" and i == 0


def t_feed_has_fmt_attr():
    f = m.Feed("POV", 53003, 0, lambda: [], HERE, fmt="b[height<=720]/b")
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


def t_current_channel_idles_past_end():
    # idx beyond the schedule -> idle (None), NOT a clamp onto the last stint
    f = m.Feed("B", 53002, 1, lambda: ["https://youtu.be/only"], HERE)
    assert f.current_channel() == (None, 1)        # one link, B on slot 2 -> idle
    f2 = m.Feed("B", 53002, 0, lambda: ["https://youtu.be/only"], HERE)
    assert f2.current_channel() == ("https://youtu.be/only", 0)


def t_set_index_allows_one_past_end_for_idle():
    f = m.Feed("A", 53001, 0, lambda: ["a", "b"], HERE)
    assert f.set_index(2) is True                  # len 2 -> idle slot 2 is reachable
    assert f.idx == 2
    assert f.current_channel() == (None, 2)        # idles
    f2 = m.Feed("A", 53001, 0, lambda: ["a", "b"], HERE)
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
    r = m.Relay(_StubSource(items), (53001, 53002), HERE)
    r._reflect = lambda live, cut: None        # isolate index logic from OBS I/O
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
    r = m.Relay(_StubSource(["s1", "s2", "s3", "s4"], rows), (53001, 53002), HERE)
    r._reflect = lambda live, cut: None
    assert r.live_feed() == "A"                        # A on stint 1
    assert r.live_schedule_row() == {"streamer": "JeGr", "stint": "Stint 1"}
    r.next_auto()                                      # B (stint 2) now on air
    assert r.live_feed() == "B"
    assert r.live_schedule_row() == {"streamer": "GT45", "stint": "Stint 2"}


def _relay_q(items, qual_items, qual_rows=None, mode="race"):
    race = _StubSource(items)
    qual = _StubSource(qual_items, qual_rows)
    r = m.Relay(race, (53001, 53002), HERE, qual_source=qual, mode=mode)
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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
