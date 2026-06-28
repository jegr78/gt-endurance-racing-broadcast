# Relay-side Feed Fan-out Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the relay the single persistent consumer of each feed's
streamlink and re-serve the stream to multiple consumers (OBS + preview), behind
a default-off machine flag, fixing the ~2 s stale-on-activation glitch and making
the preview tap free.

**Architecture:** Per feed, a live-reader thread pumps `streamlink --stdout` into
a bounded byte ring; a tiny HTTP server binds the feed's loopback port and streams
the ring to each connecting consumer with a "live reader never blocks, slow
consumer is snapped to the live edge" policy. Health moves from "serve process
exited" to "bytes stopped flowing". OBS is told to disconnect off-air
(`close_when_inactive=True`) live via obs-websocket. Everything is gated by
`RACECAST_FEED_FANOUT`; with the flag off the existing direct-serve path runs
unchanged.

**Tech Stack:** Pure Python 3 stdlib (`socket`, `threading`, `http`,
`subprocess`); `streamlink`/`ffmpeg` as external tools. No new dependencies.

## Global Constraints

- **Edit only under `src/`** (and `tests/`, `docs/`). Never hand-edit `dist/`/`runtime/`.
- **All code/docs English only.**
- **No new runtime dependency** — stdlib + the existing `streamlink`/`ffmpeg`/`yt-dlp`/`deno`.
- **The relay stays self-contained:** new pure functions and classes live **inside**
  `src/relay/racecast-feeds.py`, alongside the existing `PreviewManager` /
  `_PreviewPullWorker` / `preview_source`. Do NOT add a new importable sibling module
  the relay imports (the relay deliberately imports no shared project modules).
- **Tests are stdlib runnable scripts** — a `tests/test_*.py` with `t_*()` functions and a
  `__main__` block that runs them all. Load the relay via
  `importlib.util.spec_from_file_location(..., "src/relay/racecast-feeds.py")`
  exactly as `tests/test_feed_preview.py` does (module alias `m`).
- **Best-effort relay:** nothing in this work may raise into the HTTP server or affect a
  live feed. A fan-out failure must degrade (placeholder / fall back), never crash.
- **The live reader must never block on a slow/absent consumer** — this is the load-bearing
  invariant; it is tested deterministically (Task 3).
- **Feed ports stay `127.0.0.1`-only.** Never bind a feed port to the Tailscale IP.
- **Coexistence: `RACECAST_FEED_FANOUT` default OFF.** With the flag off, the direct-serve
  path (`streamlink_serve_cmd` + `Feed.run`'s `proc.wait()` body) must be byte-for-byte the
  behaviour shipped today.
- **Run `python3 tools/lint.py` after changing any Python file**; run the named test file
  for the task, and `python3 tools/run-tests.py` before the final review.
- **Do NOT run any of this against a machine that is producing a live event.** Execution is
  local-only and must not overlap a broadcast.

**Spec:** `docs/superpowers/specs/2026-06-28-relay-feed-fanout-design.md` — read it first.

---

### Task 1: Fan-out flag + stall/health pure helpers

The smallest isolated pieces first: the flag reader and the new pure health
predicate, both trivially testable, both consumed by later integration tasks.

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add two pure functions + two constants near the
  other module-level relay constants, e.g. just after `HEALTH_DROP_GRACE_S` ~line 180)
- Create: `tests/test_fanout.py`

**Interfaces:**
- Produces:
  - `FANOUT_STALL_S = 8.0` — seconds without a byte before a live reader is declared stalled.
  - `fanout_enabled(environ) -> bool` — True iff `environ.get("RACECAST_FEED_FANOUT")` is a
    truthy token (`"1"`, `"true"`, `"yes"`, `"on"`, case-insensitive); everything else False.
  - `feed_stalled(last_byte_ts, now, stall_s=FANOUT_STALL_S) -> bool` — True iff
    `last_byte_ts is not None and (now - last_byte_ts) > stall_s`. A `None` timestamp
    (no byte ever) is NOT a stall — startup is handled by the existing `dead_serves` path.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fanout.py`:

```python
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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("all fanout tests passed")
```

- [ ] **Step 2: Run, verify it fails**

Run: `python3 tests/test_fanout.py`
Expected: FAIL with `AttributeError: module 'irofeeds' has no attribute 'fanout_enabled'`.

- [ ] **Step 3: Implement the helpers** in `src/relay/racecast-feeds.py`

```python
FANOUT_STALL_S = 8.0   # seconds without a byte from streamlink before a fan-out reader is "stalled"
_FANOUT_TRUTHY = {"1", "true", "yes", "on"}


def fanout_enabled(environ):
    """True iff RACECAST_FEED_FANOUT is a truthy token. Default off → today's
    direct-serve path. Pure so the switch is unit-testable."""
    return str(environ.get("RACECAST_FEED_FANOUT", "")).strip().lower() in _FANOUT_TRUTHY


def feed_stalled(last_byte_ts, now, stall_s=FANOUT_STALL_S):
    """True iff a fan-out live reader has produced bytes before but none for
    `stall_s`. A None timestamp (never produced) is NOT a stall — that startup
    case is handled by the existing dead_serves path, not the watchdog."""
    return last_byte_ts is not None and (now - last_byte_ts) > stall_s
```

- [ ] **Step 4: Run, verify pass**

Run: `python3 tests/test_fanout.py` → all pass. Then `python3 tools/lint.py`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_fanout.py src/relay/racecast-feeds.py
git commit -m "feat(relay): fan-out flag + stall-health pure helpers (#358)"
```

---

### Task 2: The bounded byte ring (`FeedRing`)

The buffer at the heart of R1. Greenfield, fully unit-testable with no real
stream. The load-bearing invariant — a slow reader is snapped to the live edge,
never throttling the writer — is enforced and tested here.

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add the `FeedRing` class near the other fan-out
  code, e.g. just before `PreviewManager`)
- Test: `tests/test_fanout.py` (append tests)

**Interfaces:**
- Produces a class `FeedRing(capacity)`:
  - `write(data: bytes) -> None` — append bytes; advance the absolute write offset; when total
    bytes exceed `capacity`, the logical start advances (oldest bytes drop). Never blocks.
    Wakes readers.
  - `live_offset() -> int` — the current absolute write offset (the live edge).
  - `start_offset() -> int` — the oldest absolute offset still retained
    (`max(0, live_offset - capacity)`).
  - `read(cursor: int, timeout: float) -> (bytes, int)` — return bytes available after
    `cursor` and the new cursor. If `cursor < start_offset()` (reader fell behind the retained
    window) the cursor is **snapped** to `start_offset()` before reading (bytes lost, reader
    stays live). If no new bytes within `timeout`, returns `(b"", cursor)`.
  - `close() -> None` — wake all waiting readers (used on shutdown so `read` returns promptly).
  - `closed: bool` attribute.
- Internals: a single `bytearray` window holding the last `capacity` bytes, plus an integer
  `_base` = absolute offset of `window[0]`; a `threading.Condition` for wakeups.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_fanout.py`:

```python
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
```

- [ ] **Step 2: Run, verify it fails**

Run: `python3 tests/test_fanout.py` → FAIL (`no attribute 'FeedRing'`).

- [ ] **Step 3: Implement `FeedRing`**

```python
class FeedRing:
    """A bounded byte ring for one feed: a single live writer (the streamlink
    reader) and many readers (OBS, preview), each tracking its own absolute
    offset. The writer NEVER blocks — when the window overflows the oldest bytes
    drop and a lagging reader is snapped forward to the live edge. Pure stdlib;
    unit-testable with no real stream."""

    def __init__(self, capacity):
        self.capacity = capacity
        self._buf = bytearray()
        self._base = 0                 # absolute offset of self._buf[0]
        self._cond = threading.Condition()
        self.closed = False

    def write(self, data):
        if not data:
            return
        with self._cond:
            self._buf += data
            overflow = len(self._buf) - self.capacity
            if overflow > 0:
                del self._buf[:overflow]
                self._base += overflow
            self._cond.notify_all()

    def live_offset(self):
        with self._cond:
            return self._base + len(self._buf)

    def start_offset(self):
        with self._cond:
            return self._base

    def read(self, cursor, timeout):
        with self._cond:
            live = self._base + len(self._buf)
            if cursor >= live and not self.closed:
                self._cond.wait(timeout)
                live = self._base + len(self._buf)
            if cursor < self._base:        # fell behind the window → snap to live edge
                cursor = self._base
            if cursor >= live:
                return b"", cursor
            data = bytes(self._buf[cursor - self._base:])
            return data, live

    def close(self):
        with self._cond:
            self.closed = True
            self._cond.notify_all()
```

- [ ] **Step 4: Run, verify pass** — `python3 tests/test_fanout.py` all pass; `python3 tools/lint.py`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_fanout.py src/relay/racecast-feeds.py
git commit -m "feat(relay): FeedRing bounded byte ring with live-edge snap (#358)"
```

---

### Task 3: The fan-out TS server (`FeedFanoutServer`)

Binds the feed's loopback port and streams a `FeedRing` to every connecting
consumer, each on its own thread, dropping a stuck socket without ever touching
the ring writer.

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add `FeedFanoutServer` after `FeedRing`)
- Test: `tests/test_fanout.py`

**Interfaces:**
- Consumes: `FeedRing` (Task 2).
- Produces a class `FeedFanoutServer(host, port, ring, log)`:
  - `start() -> self` — bind `(host, port)` (TCP), spawn an accept loop daemon thread.
  - `port` attribute (the bound port; useful when `port=0` for tests).
  - `stop() -> None` — close the listening socket and ring; in-flight handlers exit on the
    next ring read.
  - On each accepted connection: read+discard the HTTP request line/headers, write a minimal
    `HTTP/1.0 200 OK\r\nContent-Type: video/mp2t\r\nConnection: close\r\n\r\n` header, then loop
    `ring.read(cursor, timeout=1.0)` → `sock.sendall(data)`. On any socket error, or
    `ring.closed`, close the socket and return. A blocked/slow `sendall` stalls only this
    handler thread; the ring writer is untouched.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_fanout.py`:

```python
def _http_get_body(port, nbytes, deadline=2.0):
    s = socket.create_connection(("127.0.0.1", port), timeout=deadline)
    s.sendall(b"GET / HTTP/1.0\r\n\r\n")
    buf = b""
    s.settimeout(deadline)
    while len(buf) < nbytes:
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
```

- [ ] **Step 2: Run, verify it fails** — `python3 tests/test_fanout.py` → FAIL (`no attribute 'FeedFanoutServer'`).

> Note: `m.logging` must resolve — `racecast-feeds.py` already imports `logging` at module
> top, so `m.logging` works. If not, use `import logging` in the test.

- [ ] **Step 3: Implement `FeedFanoutServer`**

```python
class FeedFanoutServer:
    """Serve one FeedRing to many HTTP consumers (OBS + preview) on a loopback
    port. One accept loop + one handler thread per consumer. A slow/stuck socket
    stalls only its own handler; the ring writer is never touched. Best effort:
    a handler error closes that socket and returns."""

    def __init__(self, host, port, ring, log):
        self.host = host
        self.port = port
        self.ring = ring
        self.log = log
        self._sock = None
        self._stop = False

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self.port = self._sock.getsockname()[1]
        self._sock.listen(8)
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return self

    def _accept_loop(self):
        while not self._stop:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return                          # socket closed by stop()
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        try:
            conn.recv(65536)                    # consume the request line/headers
            conn.sendall(b"HTTP/1.0 200 OK\r\n"
                         b"Content-Type: video/mp2t\r\n"
                         b"Connection: close\r\n\r\n")
            cursor = self.ring.live_offset()    # join at the live edge
            while not self._stop and not self.ring.closed:
                data, cursor = self.ring.read(cursor, timeout=1.0)
                if data:
                    conn.sendall(data)
        except OSError:
            pass                                # consumer went away / slow send aborted
        finally:
            try: conn.close()
            except OSError: pass

    def stop(self):
        self._stop = True
        self.ring.close()
        if self._sock is not None:
            try: self._sock.close()
            except OSError: pass
```

- [ ] **Step 4: Run, verify pass** — `python3 tests/test_fanout.py` all pass; `python3 tools/lint.py`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_fanout.py src/relay/racecast-feeds.py
git commit -m "feat(relay): FeedFanoutServer multi-consumer TS server (#358)"
```

---

### Task 4: streamlink-stdout command + Feed fan-out reader body

Give `Feed.run` a fan-out branch: spawn `streamlink --stdout`, pump bytes into
the feed's `FeedRing`, track `last_byte_ts`, and detect EOF/stall — reusing the
existing classification. The direct-serve branch is untouched when the flag is
off.

**Files:**
- Modify: `src/relay/racecast-feeds.py` — add `streamlink_fanout_cmd(...)` next to
  `streamlink_serve_cmd` (~line 2124); add a `Feed`-level `ring` attribute + a fan-out
  serve body in `Feed.run` (~line 3649). Read the whole current `Feed.run` before editing.
- Test: `tests/test_fanout.py` (command builder) + `tests/test_pov.py` (new health inputs in Task 5)

**Interfaces:**
- Consumes: `FeedRing` (Task 2), `feed_stalled` (Task 1), the existing `resolve_hls`,
  `channel_url`, `platform_of`, `STREAMLINK_TWITCH`, `STREAMLINK_SERVE`, `STREAMLINK_YT_UA`.
- Produces:
  - `streamlink_fanout_cmd(target, platform, twitch_token=None, cookies=None,
    user_agent=STREAMLINK_YT_UA) -> list[str]` — identical resolution rules to
    `streamlink_serve_cmd` but the sink is `--stdout` instead of
    `--player-external-http --player-external-http-port`. YouTube carries UA(+cookies);
    Twitch gets the twitch.tv URL + plugin flags (+ optional `--twitch-api-header`).
  - `Feed.ring` — a `FeedRing` set by the relay wiring (Task 6) when fan-out is on, else None.
  - `Feed.last_byte_ts` — monotonic timestamp of the last byte pumped (None until first byte).
  - A method `Feed._serve_fanout(target, serve_platform, token)` invoked from `Feed.run`'s
    serve section when `self.ring is not None`; it returns the same `(serve_elapsed, serve_rc)`
    contract the direct-serve `proc.wait()` produces, so the classification tail of `Feed.run`
    is shared.

- [ ] **Step 1: Write the failing test for the command builder** — append to `tests/test_fanout.py`:

```python
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
```

- [ ] **Step 2: Run, verify it fails** — `python3 tests/test_fanout.py` → FAIL (`no attribute 'streamlink_fanout_cmd'`).

- [ ] **Step 3: Implement the command builder**

```python
def streamlink_fanout_cmd(target, platform="youtube", twitch_token=None,
                          cookies=None, user_agent=STREAMLINK_YT_UA):
    """Argv for the fan-out live reader: same resolution rules as
    streamlink_serve_cmd, but the sink is --stdout (the relay reads it and
    re-serves to many consumers) instead of --player-external-http. `--` guards
    the positional URL/stream."""
    base = ["streamlink", "--stdout"]
    if platform == "twitch":
        base += STREAMLINK_TWITCH
        if twitch_token:
            base += ["--twitch-api-header", f"Authorization=OAuth {twitch_token}"]
    else:
        base += STREAMLINK_SERVE
        if user_agent:
            base += ["--http-header", f"User-Agent={user_agent}"]
        if cookies:
            base += ["--http-cookies-file", cookies]
    return base + ["--", target, "best"]
```

- [ ] **Step 4: Run, verify the builder test passes** — `python3 tests/test_fanout.py`.

- [ ] **Step 5: Add `ring`/`last_byte_ts` to `Feed.__init__`**

In `Feed.__init__` (~line 3585, after `self.quality = None`) add:

```python
        self.ring = None              # set by the relay when fan-out is enabled (#358); None → direct-serve
        self.last_byte_ts = None      # monotonic ts of the last byte pumped into the ring (fan-out health)
```

- [ ] **Step 6: Add `Feed._serve_fanout`** (method on `Feed`, near `run`)

```python
    def _serve_fanout(self, target, serve_platform, token):
        """Fan-out serve: stream `streamlink --stdout` into self.ring, tracking
        last_byte_ts so the watchdog (feed_stalled) and EOF both surface. Returns
        (serve_elapsed, serve_rc) like the direct-serve proc.wait() so Feed.run's
        classification tail is shared. Kills streamlink on stop/advance/stall."""
        cmd = streamlink_fanout_cmd(target, serve_platform, token, cookies=self.cookies)
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=external_tool_env(), **_no_window_kwargs())
        self._set_phase("serving")
        self._clear_drop_health()
        self.last_byte_ts = None
        serve_started = time.monotonic()
        stdout = self.proc.stdout
        try:
            while True:
                if self.stop or self.advance.is_set():
                    break
                if feed_stalled(self.last_byte_ts, time.monotonic()):
                    self.log.warning("fan-out stall on %s — restarting reader", self.name)
                    break
                chunk = stdout.read(65536)
                if not chunk:
                    break                       # streamlink EOF (ended / 403 / expired)
                self.ring.write(chunk)
                self.last_byte_ts = time.monotonic()
        finally:
            self._kill_proc()
        return time.monotonic() - serve_started, (self.proc.returncode or 0)
```

> Implementation note for the executor: `stdout.read(65536)` blocks until bytes or EOF, so the
> stop/advance/stall checks run between chunks. A live feed delivers bytes continuously, so the
> loop is responsive; a fully stalled streamlink yields no chunk and is caught by the
> `feed_stalled` check on the next iteration only if a prior byte set `last_byte_ts`. For the
> never-produced-a-byte case, rely on the existing `dead_serves` fast-exit path (the reader
> returns a near-zero `serve_elapsed` on immediate EOF). If a robust stall-kill while
> `read()` is blocked is needed, the reviewer may request a watchdog thread that calls
> `self._kill_proc()` when `feed_stalled` trips — keep that minimal and test it.

- [ ] **Step 7: Branch `Feed.run`'s serve section** — in `Feed.run`, replace the direct-serve
  block (the `cmd = streamlink_serve_cmd(...)` + `Popen` + `self.proc.wait()` region, ~lines
  3675-3696) so it chooses the path:

```python
            self.log.info("serving stint %d (%s)", i + 1, serve_platform)
            if self.ring is not None:
                try:
                    serve_elapsed, serve_rc = self._serve_fanout(target, serve_platform, token)
                except FileNotFoundError:
                    self.log.warning("streamlink not found on PATH — retrying")
                    self.proc = None
                    time.sleep(RETRY_SLEEP); continue
            else:
                cmd = streamlink_serve_cmd(target, self.port, serve_platform, token,
                                           cookies=self.cookies)
                try:
                    self.proc = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace",
                        env=external_tool_env(), **_no_window_kwargs())
                    pump = threading.Thread(
                        target=logsetup.pump_subprocess,
                        args=(self.proc.stdout, self.log, "streamlink"),
                        kwargs={"on_line": self._observe_streamlink_line},
                        daemon=True)
                    pump.start()
                    if serve_platform != "youtube":
                        self.last_error = None
                    self._set_phase("serving")
                    self._clear_drop_health()
                    serve_started = time.monotonic()
                    self.proc.wait()
                    serve_elapsed = time.monotonic() - serve_started
                    serve_rc = self.proc.returncode
                except FileNotFoundError:
                    self.log.warning("streamlink not found on PATH — retrying")
                    self.proc = None
                    time.sleep(RETRY_SLEEP); continue
            self._set_phase("connecting")
            # ... existing classification tail unchanged (served_ok / dropped / dead_serves) ...
```

> The classification tail after `self._set_phase("connecting")` is shared and unchanged.
> Read the current `Feed.run` in full and preserve every line of that tail.

- [ ] **Step 8: Run tests** — `python3 tests/test_fanout.py`, `python3 tests/test_pov.py`
  (must still pass — direct-serve path unchanged), `python3 tools/lint.py`.

- [ ] **Step 9: Commit**

```bash
git add tests/test_fanout.py src/relay/racecast-feeds.py
git commit -m "feat(relay): Feed fan-out reader body + streamlink_fanout_cmd (#358)"
```

---

### Task 5: Health re-expression — new inputs to the existing pure predicates

Confirm and lock the health semantics under fan-out: EOF maps to the existing
drop/dead-serve classification, and the byte-stall watchdog is covered. The pure
functions do not change; we add input cases that pin their fan-out behaviour.

**Files:**
- Test: `tests/test_pov.py` (append `t_*` cases) and `tests/test_fanout.py`
- Modify (only if a test reveals a gap): `src/relay/racecast-feeds.py`

**Interfaces:**
- Consumes: `serve_exit_is_drop`, `should_idle_dead_serves`, `dead_serve_backoff`,
  `feed_fast_exit_error`, `feed_stalled` — all already defined.

- [ ] **Step 1: Write the pinning tests** — append to `tests/test_fanout.py`:

```python
def t_fanout_eof_is_drop_when_not_stopped_or_advancing():
    # streamlink EOF mid-serve, not a stop/handover → a real DROP (same rule as direct-serve).
    assert m.serve_exit_is_drop(False, False) is True
    assert m.serve_exit_is_drop(True, False) is False     # stop → not a drop
    assert m.serve_exit_is_drop(False, True) is False     # advance/handover → not a drop


def t_fanout_fast_eof_counts_as_dead_serve():
    # A reader that returns near-instantly (403/expired manifest) is a fast exit.
    err = m.feed_fast_exit_error(0.2, 1)
    assert err                                            # non-empty error string
    assert m.should_idle_dead_serves(m.DEAD_SERVE_IDLE_AFTER) is True
```

> `DEAD_SERVE_IDLE_AFTER` (= 5) and `feed_fast_exit_error(elapsed_s, returncode)` are the real
> names/signatures (verified). This task is a *characterization* of existing behaviour — adapt
> the asserts if a signature has since changed; do not change production code unless a test
> exposes a genuine fan-out gap.

- [ ] **Step 2: Run, verify** — `python3 tests/test_fanout.py`. Fix the asserts to the real
  signatures until green. If a genuine gap appears (e.g. a fan-out EOF path that bypasses
  `dead_serves`), write a failing test first, then the minimal fix in `Feed.run`.

- [ ] **Step 3: Add the stall-watchdog integration note test** (only if Step 6/Task 4 added a
  watchdog thread): assert the watchdog calls `_kill_proc` when `feed_stalled` trips, using a
  fake feed with a stubbed `_kill_proc`. Skip if Task 4 used the in-loop check only.

- [ ] **Step 4: Run the full relay health suite** — `python3 tests/test_pov.py` (all green),
  `python3 tools/lint.py`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_fanout.py src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "test(relay): pin fan-out health classification (EOF/stall) (#358)"
```

---

### Task 6: Relay wiring — rings + fan-out servers when the flag is on

Make the relay create a `FeedRing` per feed and start a `FeedFanoutServer` on
each feed port when `fanout_enabled` is true; otherwise leave today's path exactly
as is.

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `Relay.__init__`/`Relay.start` (~lines 3758-3845)
  and the `main()` server bring-up (~line 6180). Read both regions first.
- Test: `tests/test_fanout.py`

**Interfaces:**
- Consumes: `fanout_enabled`, `FeedRing`, `FeedFanoutServer`, `Feed.ring`, `Feed.port`.
- Produces:
  - `Relay.fanout: bool` — computed once at construction from the environment via
    `fanout_enabled(os.environ)`.
  - `Relay._fanout_servers: list[FeedFanoutServer]` — started in `Relay.start()` when
    `self.fanout`, one per feed (A, B, and POV if present), each with a `FeedRing` assigned to
    the feed's `.ring`. Stopped in the relay's shutdown path.
  - Ring capacity constant `FANOUT_RING_BYTES = 8 * 1024 * 1024` (≈ a few seconds of a feed at
    typical bitrate; bounded).

- [ ] **Step 1: Write the failing test** (constructor wiring, no real sockets) — append to
  `tests/test_fanout.py`:

```python
def t_relay_fanout_flag_from_env(monkeypatch=None):
    # fanout_enabled drives Relay.fanout; verified via the pure helper to avoid
    # constructing a full Relay (which needs sources). This guards the wiring contract.
    assert m.fanout_enabled({"RACECAST_FEED_FANOUT": "1"}) is True
    assert m.FANOUT_RING_BYTES >= 1 << 20      # bounded, at least 1 MB
```

> A full `Relay` construction needs schedule sources and ports; the integration is better
> proven by the e2e check in Task 9 (real port binding). This unit test pins the constant and
> the flag contract. The executor wires `Relay.fanout`/`_fanout_servers` per the Interfaces
> block and relies on Task 9 for the live binding assertion.

- [ ] **Step 2: Run, verify it fails** — `python3 tests/test_fanout.py` → FAIL
  (`no attribute 'FANOUT_RING_BYTES'`).

- [ ] **Step 3: Implement the wiring**

Add the constant near the other fan-out constants:

```python
FANOUT_RING_BYTES = 8 * 1024 * 1024   # per-feed ring window (bounded; ≈ a few seconds at typical feed bitrate)
```

In `Relay.__init__`, after the feeds dict is built (~line 3782), add:

```python
        self.fanout = fanout_enabled(os.environ)
        self._fanout_servers = []
```

In `Relay.start` (~line 3836), BEFORE spawning the `f.run` threads, add:

```python
        if self.fanout:
            live = list(self.feeds.items()) + ([("POV", self.pov)] if self.pov else [])
            for _name, f in live:
                f.ring = FeedRing(FANOUT_RING_BYTES)
                srv = FeedFanoutServer("127.0.0.1", f.port, f.ring,
                                       logging.getLogger("racecast.fanout." + f.name))
                srv.start()
                self._fanout_servers.append(srv)
```

In the relay's shutdown (find where feeds are shut down — `Feed.shutdown` is called on stop;
locate the relay-level stop path) add, before/after feed shutdown:

```python
        for srv in self._fanout_servers:
            srv.stop()
```

> The executor must locate the actual relay shutdown site (grep `shutdown(` on `Relay` /
> the `main()` teardown) and place the `srv.stop()` loop there. With the flag off,
> `_fanout_servers` stays empty and every line above is a no-op — direct-serve unchanged.

- [ ] **Step 4: Run tests** — `python3 tests/test_fanout.py`, `python3 tests/test_pov.py`,
  `python3 tools/lint.py`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_fanout.py src/relay/racecast-feeds.py
git commit -m "feat(relay): wire FeedRing + FeedFanoutServer per feed when flag on (#358)"
```

---

### Task 7: OBS `close_when_inactive` live-set via obs-websocket

When fan-out is on, tell OBS to disconnect off-air so no backlog forms. Done live
at relay start via obs-websocket, best-effort, mirroring the existing
`_sync_pov_transform` / `_release_obs_feeds` hooks.

**Files:**
- Modify: `src/scripts/obs_ws.py` — add a helper to set `close_when_inactive` on the feed
  media inputs. Read the existing `set_input_settings` / `set_scene_item_transform` /
  `_release_obs_feeds` first.
- Modify: `src/racecast.py` — the relay-start hook that already calls obs refresh /
  `_sync_pov_transform`; add the close-when-inactive call gated on `fanout_enabled`.
- Test: `tests/test_obsws.py`

**Interfaces:**
- Produces: `obs_ws.set_feed_close_when_inactive(inputs, value=True) -> note:str` (or extend
  the existing client) that issues `SetInputSettings` with
  `{"close_when_inactive": value}` (merge, do not overwrite) for each feed input name. Returns
  a best-effort note; never raises. The feed input names are the existing media source names
  (e.g. the `Feed A`/`Feed B`/`Feed POV` media inputs — confirm the exact OBS input names from
  `_release_obs_feeds`, which already enumerates them).

- [ ] **Step 1: Write the failing test** — in `tests/test_obsws.py`, add a request-builder test
  mirroring the existing obs_ws tests (use the file's fake-socket / request-capture harness):

```python
def t_set_feed_close_when_inactive_builds_setinputsettings():
    # Capture the SetInputSettings requests for each feed input; assert overlayMerge True.
    reqs = capture_requests(lambda c: c.set_feed_close_when_inactive(["Feed A", "Feed B"], True))
    kinds = [r["requestType"] for r in reqs]
    assert kinds.count("SetInputSettings") == 2
    for r in reqs:
        d = r["requestData"]
        assert d["inputSettings"]["close_when_inactive"] is True
        assert d.get("overlay", True) is True       # merge, not replace
```

> Adapt `capture_requests` to the harness `tests/test_obsws.py` already uses (read it first;
> it has a fake socket that records sent frames). Match the real method/style.

- [ ] **Step 2: Run, verify it fails** — `python3 tests/test_obsws.py`.

- [ ] **Step 3: Implement `set_feed_close_when_inactive`** in `src/scripts/obs_ws.py`,
  following the existing `SetInputSettings` call shape (use `overlay=True` to merge so only
  `close_when_inactive` changes). Best-effort: catch and return a note on failure.

- [ ] **Step 4: Wire it at relay start** in `src/racecast.py` — where the start path already
  syncs POV/refreshes OBS, add (gated):

```python
    if fanout_enabled(os.environ):
        note = obs_ws.set_feed_close_when_inactive(FEED_INPUT_NAMES, True)
        if note:
            print("obs: " + note)
```

> Use the same `fanout_enabled` semantics as the relay (import or re-read the env). Reuse the
> feed input name list the existing `_release_obs_feeds` uses — do not invent names.

- [ ] **Step 5: Run** — `python3 tests/test_obsws.py`, `python3 tools/lint.py`.

- [ ] **Step 6: Commit**

```bash
git add tests/test_obsws.py src/scripts/obs_ws.py src/racecast.py
git commit -m "feat(obs): set feed close_when_inactive live when fan-out on (#358)"
```

---

### Task 8: PreviewManager taps the hub when fan-out is on

When fan-out is on, the off-air preview tile reads from the feed's `FeedRing`
(an internal consumer) instead of spawning the #359 second pull — the "free
preview" win. The `still(target)` / `levels()` contract is unchanged.

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `PreviewManager` (~line 2359) and `preview_source`
  (~line 2335).
- Test: `tests/test_feed_preview.py`

**Interfaces:**
- Consumes: `Feed.ring` (Task 4/6), `preview_ffmpeg_cmd` / `split_mjpeg_frames` /
  `parse_ebur128_momentary` / `lufs_to_meter` (existing), `FeedRing.read`.
- Produces:
  - `preview_source(...)` gains a fourth kind for the off-air feed when a ring exists: returns
    `("ring", feed_key)` instead of `("pull", feed_key)`. Signature gains a `fanout` bool
    (default False so existing callers/tests are unaffected):
    `preview_source(target, live, pov_active, feed_keys, fanout=False)`.
  - A `_PreviewRingTap(ring, log)` worker mirroring `_PreviewPullWorker`'s
    `latest_frame()/latest_level()` API but sourcing bytes from the ring (feed them to one
    `preview_ffmpeg_cmd` via a pipe) — so `PreviewManager._pull_still` / `levels` treat both
    identically.
  - `PreviewManager` learns the active feed's ring from `self.relay.feeds[target].ring`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_feed_preview.py`:

```python
def t_preview_source_ring_when_fanout_and_offair():
    # off-air feed, fan-out on → ('ring', key) not ('pull', key)
    kind, ref = m.preview_source("B", "A", False, {"A", "B"}, fanout=True)
    assert (kind, ref) == ("ring", "B")


def t_preview_source_pull_when_fanout_off():
    kind, ref = m.preview_source("B", "A", False, {"A", "B"}, fanout=False)
    assert (kind, ref) == ("pull", "B")


def t_preview_source_onair_still_obs_with_fanout():
    # on-air feed is always OBS regardless of fan-out
    assert m.preview_source("A", "A", False, {"A", "B"}, fanout=True) == ("obs", "Feed A")
```

- [ ] **Step 2: Run, verify it fails** — `python3 tests/test_feed_preview.py` → FAIL
  (signature has no `fanout`).

- [ ] **Step 3: Extend `preview_source`**

```python
def preview_source(target, live, pov_active, feed_keys, fanout=False):
    """... (existing docstring) ... When `fanout` is True the off-air feed is read
    from the relay's FeedRing ('ring') instead of a decoupled second pull ('pull')."""
    if target == "POV":
        return ("obs", "Feed POV") if pov_active else ("placeholder", "pov off")
    if target in ("A", "B"):
        if target not in feed_keys:
            return ("placeholder", "feed off")
        if target == live:
            return ("obs", "Feed " + target)
        return ("ring", target) if fanout else ("pull", target)
    return ("placeholder", "unknown feed")
```

- [ ] **Step 4: Implement `_PreviewRingTap` + route it in `PreviewManager`**

Add `_PreviewRingTap` (mirrors `_PreviewPullWorker` but reads from `ring` instead of spawning
streamlink): a thread reads `ring.read(cursor, 1.0)`, writes bytes to a single
`preview_ffmpeg_cmd` subprocess stdin, and reuses the existing MJPEG/ebur128 parsing to expose
`latest_frame()` / `latest_level()`. Then in `PreviewManager.still`, pass
`self.relay.fanout` into `preview_source`, and add a `kind == "ring"` branch that lazily
creates a `_PreviewRingTap(self.relay.feeds[target].ring, self.log)` (reusing the same
`_pull`/idle-reaper slot and lifecycle as the pull worker, so only one tap runs and it is
reaped on idle).

> Keep the worker lifecycle identical to `_pull_still` (one active worker, reset on target
> change, idle-reaped). The only change is the worker *source*. The reviewer should confirm a
> failed ring tap leaves the tile "unavailable" (best-effort), never crashes.

- [ ] **Step 5: Run** — `python3 tests/test_feed_preview.py`, `python3 tests/test_fanout.py`,
  `python3 tools/lint.py`.

- [ ] **Step 6: Commit**

```bash
git add tests/test_feed_preview.py src/relay/racecast-feeds.py
git commit -m "feat(preview): tap the fan-out ring instead of a second pull when flag on (#358)"
```

---

### Task 9: e2e synthetic — feed ports bound by the relay in fan-out mode

Prove in CI that with the flag on, the relay itself binds the feed ports and the
HTTP surface stands. (Real TS throughput stays the live-UAT's job.)

**Files:**
- Modify: `tools/e2e.py` (spawn one relay variant with `RACECAST_FEED_FANOUT=1`) and
  `tools/e2e_checks.py` (add `check_fanout_feed_port_bound`); register in `SYNTHETIC_CHECKS`.
- Test: `tests/test_e2e.py` (unit-cover the new check's pure parts if any)

**Interfaces:**
- Consumes: the existing e2e free-port + spawn + `http_request` helpers.
- Produces: `check_fanout_feed_port_bound(ctx) -> CheckResult` — asserts a TCP connect to the
  fan-out relay's feed-A port succeeds and an HTTP GET returns a `200` with
  `Content-Type: video/mp2t` (the no-op streamlink stub means no body, but the server header
  proves the relay — not streamlink — owns the port).

- [ ] **Step 1: Read `tools/e2e.py` + `tools/e2e_checks.py`** to learn the spawn/check
  registry shape and the synthetic stub-tool setup (the no-op `streamlink` stub).

- [ ] **Step 2: Write the check** in `tools/e2e_checks.py` following the existing
  `check_*` style; connect to the feed port, send `GET / HTTP/1.0`, assert the
  `video/mp2t` header line is present.

- [ ] **Step 3: Spawn a fan-out relay** in `tools/e2e.py` (env `RACECAST_FEED_FANOUT=1`, on a
  free feed port) and run the new check against it; tear it down in the guaranteed `finally`.

- [ ] **Step 4: Run** — `python3 tools/e2e.py` (synthetic) and `python3 tests/test_e2e.py`;
  `python3 tools/lint.py`.

- [ ] **Step 5: Commit**

```bash
git add tools/e2e.py tools/e2e_checks.py tests/test_e2e.py
git commit -m "test(e2e): assert relay binds feed ports in fan-out mode (#358)"
```

---

### Task 10: Docs — `.env.example`, CLAUDE.md architecture note

Document the flag and the new transport so the next maintainer (and the operator)
understands the switch and its coupling to `close_when_inactive`.

**Files:**
- Modify: `.env.example` (add the flag, commented, default off, with a one-line explanation)
- Modify: `CLAUDE.md` (the relay architecture section — describe the fan-out mode + flag +
  coexistence + that `close_when_inactive` is set live when on)

- [ ] **Step 1: Add to `.env.example`**

```bash
# Relay feed fan-out (experimental, default off). When 1, the relay becomes the single
# streamlink consumer and re-serves each feed to OBS + the preview, fixing the ~2s
# stale-on-activation glitch and freeing the preview tap. Falls back to the proven
# direct-serve path when unset. See docs/superpowers/specs/2026-06-28-relay-feed-fanout-design.md
# RACECAST_FEED_FANOUT=1
```

- [ ] **Step 2: Add a paragraph to CLAUDE.md** under "The relay" describing: the fan-out hub
  (streamlink --stdout → FeedRing → FeedFanoutServer on the loopback feed port, multi-consumer),
  the `RACECAST_FEED_FANOUT` machine flag (default off, coexistence), health moving from
  serve-exit to byte-flow/stall, and `close_when_inactive=True` set live via obs-ws when on.
  Reference the spec path. Keep it to the section's existing density.

- [ ] **Step 3: Validate docs** — `python3 tools/lint.py` (and `python3 tests/test_wiki.py`
  only if a wiki page was touched; this task does not touch `src/docs/wiki/`).

- [ ] **Step 4: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs: document RACECAST_FEED_FANOUT relay fan-out mode (#358)"
```

---

## Final verification (before the whole-branch review)

- [ ] `python3 tools/run-tests.py` — the entire suite green.
- [ ] `python3 tools/lint.py` — clean.
- [ ] `python3 tools/e2e.py` — synthetic e2e green (includes the new fan-out check).
- [ ] Re-read the spec's acceptance criteria; the CI-checkable ones (flag default off,
      feed-port binding, preview routing, health classification) are covered. The
      live-only ones (R1/R2/R3 — OBS shows live within <1 s, both platforms, no on-air
      regression) are explicitly deferred to the **live-UAT gate** and must NOT be marked
      done from CI.

## Live-UAT gate (separate, NOT part of this branch's CI — run before shipping)

Per the spec, before flipping the default or relying on fan-out in production, run
`racecast-local-uat` / `racecast-e2e` against **real YouTube AND Twitch** streams with
`RACECAST_FEED_FANOUT=1` and verify: (1) OBS shows live not stale < 1 s on activation;
(2) off-air feed stays warm, no false DROP; (3) preview reads with no second pull;
(4) a full swap with no on-air regression; (5) a slow consumer does not stall the live path.
This is operator-run on a non-production machine, never overlapping a live event.
