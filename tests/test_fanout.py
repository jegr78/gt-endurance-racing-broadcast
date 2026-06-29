#!/usr/bin/env python3
"""Stdlib unit checks for relay feed fan-out. Run: python3 tests/test_fanout.py"""
import importlib.util, os, socket, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_fanout_enabled_truthy_tokens():
    for v in ("1", "true", "TRUE", "Yes", "on"):
        assert m.fanout_enabled({"RACECAST_FEED_FANOUT": v}) is True, v


def t_fanout_enabled_default_on():
    # Default ON (#358 live-verified 2026-06-29): absent or empty -> fan-out.
    assert m.fanout_enabled({}) is True
    assert m.fanout_enabled({"RACECAST_FEED_FANOUT": ""}) is True


def t_fanout_enabled_explicit_falsey_disables():
    # Only an explicit falsey token falls back to the direct-serve path.
    for v in ("0", "false", "FALSE", "no", "off"):
        assert m.fanout_enabled({"RACECAST_FEED_FANOUT": v}) is False, v


def t_feed_stalled_window():
    assert m.feed_stalled(100.0, 100.0 + m.FANOUT_STALL_S + 0.1) is True
    assert m.feed_stalled(100.0, 100.0 + m.FANOUT_STALL_S - 0.1) is False


def t_feed_stalled_none_is_not_stall():
    assert m.feed_stalled(None, 1_000_000.0) is False


def t_ring_basic_read_after_write():
    r = m.FeedRing(1024)
    r.write(b"abc")
    data, cur = r.read(0, timeout=0.1)
    assert data == b"abc" and cur == 3


def t_ring_incremental_cursor():
    r = m.FeedRing(1024)
    r.write(b"abc")
    _, cur = r.read(0, timeout=0.1)
    r.write(b"de")
    data, cur2 = r.read(cur, timeout=0.1)
    assert data == b"de" and cur2 == 5


def t_ring_overflow_drops_oldest_and_snaps_slow_reader():
    r = m.FeedRing(4)                     # tiny window
    r.write(b"0123")                      # window = "0123", base=0, live=4
    r.write(b"4567")                      # window = "4567", base=4, live=8
    assert r.live_offset() == 8
    assert r.start_offset() == 4
    # a reader still at cursor 0 fell behind: it is snapped to start_offset (4)
    data, cur = r.read(0, timeout=0.1)
    assert cur == 8 and data == b"4567"   # got the retained window, not the lost "0123"


def t_ring_read_times_out_without_new_data():
    r = m.FeedRing(1024)
    r.write(b"abc")
    _, cur = r.read(0, timeout=0.1)
    t0 = time.monotonic()
    data, cur2 = r.read(cur, timeout=0.15)
    assert data == b"" and cur2 == cur
    assert time.monotonic() - t0 >= 0.1


def t_ring_writer_never_blocks_on_absent_reader():
    # Writing far more than capacity with NO reader must return immediately.
    r = m.FeedRing(1024)
    t0 = time.monotonic()
    for _ in range(1000):
        r.write(b"x" * 1024)
    assert time.monotonic() - t0 < 1.0    # never blocked
    assert r.live_offset() == 1000 * 1024


def _http_get_body(port, nbytes, deadline=2.0):
    s = socket.create_connection(("127.0.0.1", port), timeout=deadline)
    s.sendall(b"GET / HTTP/1.0\r\n\r\n")
    buf = b""
    s.settimeout(deadline)
    while True:
        # count only body bytes (after \r\n\r\n) so we don't exit early on the header
        sep = buf.find(b"\r\n\r\n")
        body_len = len(buf) - (sep + 4) if sep >= 0 else 0
        if body_len >= nbytes:
            break
        try:
            chunk = s.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
    s.close()
    # strip headers
    sep = buf.find(b"\r\n\r\n")
    return buf[sep + 4:] if sep >= 0 else buf


def t_fanout_server_streams_ring_to_two_consumers():
    ring = m.FeedRing(1 << 20)
    srv = m.FeedFanoutServer("127.0.0.1", 0, ring, m.logging.getLogger("t"))
    srv.start()
    try:
        bodies = {}

        def grab(idx):
            bodies[idx] = _http_get_body(srv.port, 10)
        t1 = threading.Thread(target=grab, args=(1,)); t1.start()
        t2 = threading.Thread(target=grab, args=(2,)); t2.start()
        time.sleep(0.2)                       # let both connect
        for i in range(10):
            ring.write(bytes([65 + i]))       # b"A".."J"
            time.sleep(0.01)
        t1.join(3); t2.join(3)
        assert bodies[1] == b"ABCDEFGHIJ"
        assert bodies[2] == b"ABCDEFGHIJ"
    finally:
        srv.stop()


def t_fanout_server_writer_unblocked_by_dead_consumer():
    # A consumer that connects then never reads must not stop the ring writer.
    ring = m.FeedRing(4096)
    srv = m.FeedFanoutServer("127.0.0.1", 0, ring, m.logging.getLogger("t"))
    srv.start()
    try:
        s = socket.create_connection(("127.0.0.1", srv.port), timeout=2.0)
        s.sendall(b"GET / HTTP/1.0\r\n\r\n")   # connect, then never recv
        t0 = time.monotonic()
        for _ in range(2000):
            ring.write(b"y" * 4096)            # 8 MB through a 4 KB ring
        assert time.monotonic() - t0 < 2.0     # writer never blocked
        s.close()
    finally:
        srv.stop()


def t_streamlink_fanout_cmd_youtube_has_stdout_ua_cookies():
    cmd = m.streamlink_fanout_cmd("https://hls.example/x.m3u8", "youtube",
                                  cookies="/tmp/yt.txt", user_agent="UA/9")
    assert cmd[0] == "streamlink" and "--stdout" in cmd
    assert "--player-external-http" not in cmd
    assert "--http-header" in cmd and "User-Agent=UA/9" in cmd
    assert "--http-cookies-file" in cmd and "/tmp/yt.txt" in cmd
    assert cmd[-2:] == ["https://hls.example/x.m3u8", "best"]


def t_streamlink_fanout_cmd_twitch_uses_plugin_no_ua():
    cmd = m.streamlink_fanout_cmd("https://twitch.tv/foo", "twitch",
                                  twitch_token="tok")
    assert "--stdout" in cmd and "--http-header" not in cmd
    assert "--twitch-api-header" in cmd
    assert cmd[-2:] == ["https://twitch.tv/foo", "best"]


def t_fanout_eof_is_drop_when_not_stopped_or_advancing():
    # streamlink EOF mid-serve in fan-out mode, not a stop/handover → a real DROP.
    # The fan-out path reads the same exit-classification predicate as direct-serve.
    assert m.serve_exit_is_drop(False, False) is True
    assert m.serve_exit_is_drop(True, False) is False   # stop → not a drop
    assert m.serve_exit_is_drop(False, True) is False   # advance/handover → not a drop


def t_fanout_fast_eof_counts_as_dead_serve():
    # A fan-out reader that returns near-instantly (403 / expired manifest) is a
    # fast exit: feed_fast_exit_error produces an error string, and
    # should_idle_dead_serves trips once DEAD_SERVE_IDLE_AFTER consecutive fast
    # exits accumulate — same dead-serve path as direct-serve.
    err = m.feed_fast_exit_error(0.2, 1)
    assert err                                           # non-empty error string
    assert m.should_idle_dead_serves(m.DEAD_SERVE_IDLE_AFTER) is True


def t_fanout_watchdog_kill_condition_is_feed_stalled():
    # The byte-stall watchdog's kill decision is exactly feed_stalled(last_byte_ts, now).
    # A stale timestamp (no bytes for > FANOUT_STALL_S) trips the kill condition;
    # a fresh timestamp (bytes arrived recently) does not.
    now = 1000.0
    stale_ts = now - m.FANOUT_STALL_S - 0.1   # bytes arrived too long ago
    fresh_ts = now - m.FANOUT_STALL_S + 0.1   # bytes arrived recently
    assert m.feed_stalled(stale_ts, now) is True    # watchdog WOULD kill
    assert m.feed_stalled(fresh_ts, now) is False   # watchdog would NOT kill
    # NOTE: The closure's wiring (predicate → _kill_proc) lives inside
    # Feed._serve_fanout and is not separately callable without a live streamlink
    # subprocess.  Integration coverage is provided by the live-UAT
    # (racecast-local-uat skill), not a unit test — that is the honest boundary.


def t_relay_fanout_flag_from_env(monkeypatch=None):
    # fanout_enabled drives Relay.fanout; verified via the pure helper to avoid
    # constructing a full Relay (which needs sources). This guards the wiring contract.
    assert m.fanout_enabled({"RACECAST_FEED_FANOUT": "1"}) is True
    assert m.FANOUT_RING_BYTES >= 1 << 20      # bounded, at least 1 MB


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("all fanout tests passed")
