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


def t_fanout_enabled_default_off():
    assert m.fanout_enabled({}) is False
    for v in ("0", "false", "no", "", "off"):
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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("all fanout tests passed")
