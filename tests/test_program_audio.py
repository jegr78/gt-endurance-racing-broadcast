#!/usr/bin/env python3
"""Stdlib unit checks for the on-air program-audio monitor (relay tap).
Run: python3 tests/test_program_audio.py"""
import importlib.util, io, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


# --- program_audio_enabled: default ON, explicit falsey token disables --------
def t_program_audio_default_on():
    assert m.program_audio_enabled({}) is True
    assert m.program_audio_enabled({"RACECAST_PROGRAM_AUDIO": ""}) is True
    assert m.program_audio_enabled({"RACECAST_PROGRAM_AUDIO": "1"}) is True
    assert m.program_audio_enabled({"RACECAST_PROGRAM_AUDIO": "on"}) is True


def t_program_audio_killswitch():
    for tok in ("0", "false", "no", "off", "OFF", " Off "):
        assert m.program_audio_enabled({"RACECAST_PROGRAM_AUDIO": tok}) is False


# --- program_audio_ffmpeg_cmd: audio-only MP3 to stdout, params from consts ---
def t_program_audio_ffmpeg_cmd_shape():
    cmd = m.program_audio_ffmpeg_cmd()
    assert cmd[0] == "ffmpeg"
    assert "-vn" in cmd                       # no video
    assert cmd[cmd.index("-map") + 1] == "0:a:0?"   # optional audio stream
    assert cmd[cmd.index("-ar") + 1] == m.PROGRAM_AUDIO_SAMPLE_RATE
    assert cmd[cmd.index("-ac") + 1] == m.PROGRAM_AUDIO_CHANNELS
    assert cmd[cmd.index("-c:a") + 1] == m.PROGRAM_AUDIO_CODEC
    assert cmd[cmd.index("-b:a") + 1] == m.PROGRAM_AUDIO_BITRATE
    assert cmd[cmd.index("-f") + 1] == m.PROGRAM_AUDIO_FORMAT
    assert cmd[-1] == "pipe:1"                 # emit to stdout


def t_program_audio_defaults_are_mp3():
    assert m.PROGRAM_AUDIO_CODEC == "libmp3lame"
    assert m.PROGRAM_AUDIO_FORMAT == "mp3"
    assert m.PROGRAM_AUDIO_CONTENT_TYPE == "audio/mpeg"


# --- should_retarget: re-point the encoder only on a real, serving handover ---
def t_should_retarget_on_handover():
    assert m.should_retarget("A", "B", True) is True
    assert m.should_retarget("B", "A", True) is True


def t_should_retarget_no_change():
    assert m.should_retarget("A", "A", True) is False


def t_should_retarget_guards():
    assert m.should_retarget("A", "B", False) is False   # new feed not serving yet
    assert m.should_retarget("A", None, True) is False    # no on-air feed
    assert m.should_retarget(None, "A", True) is True     # first target counts


# --- ProgramAudioService: refcount, idle reaper, handover restart (thread-free) --
class _FakeRing:
    def __init__(self):
        self.closed = False
    def live_offset(self):
        return 0
    def read(self, cursor, timeout):
        return b"", cursor          # never yields in tests; we don't run pumps
    def close(self):
        self.closed = True


class _FakeFeed:
    def __init__(self, ring):
        self.ring = ring


class _FakeRelay:
    def __init__(self, fanout=True, live="A"):
        self.fanout = fanout
        self._live = live
        self.feeds = {"A": _FakeFeed(_FakeRing()), "B": _FakeFeed(_FakeRing())}
    def live_feed(self):
        return self._live


class _FakeProc:
    def __init__(self):
        self.killed = False
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO()
    def poll(self):
        return 0 if self.killed else None
    def kill(self):
        self.killed = True


def _svc(relay, spawns):
    def spawn():
        p = _FakeProc(); spawns.append(p); return p, p.stdin, p.stdout
    return m.ProgramAudioService(relay, _Log(), idle_timeout=0.01,
                                 spawn=spawn, ring_factory=_FakeRing)


class _Log:
    def info(self, *a, **k):
        pass


def t_acquire_none_when_fanout_off():
    svc = _svc(_FakeRelay(fanout=False), [])
    assert svc.acquire() is None
    assert svc._listeners == 0


def t_acquire_returns_output_ring_and_counts():
    svc = _svc(_FakeRelay(), [])
    ring = svc.acquire()
    assert ring is not None and ring is svc._out
    assert svc._listeners == 1
    ring2 = svc.acquire()
    assert ring2 is svc._out            # same shared output ring
    assert svc._listeners == 2
    svc.release(); svc.release()
    assert svc._listeners == 0
    svc.shutdown()


def t_encoder_tick_spawns_for_on_air_feed():
    relay = _FakeRelay(live="A"); spawns = []
    svc = _svc(relay, spawns)
    svc.acquire()
    target = svc._encoder_tick(None)
    assert target == "A"
    assert len(spawns) == 1
    assert svc._enc_target == "A"
    svc.shutdown()


def t_encoder_tick_reencodes_on_handover():
    relay = _FakeRelay(live="A"); spawns = []
    svc = _svc(relay, spawns)
    svc.acquire()
    prev = svc._encoder_tick(None)      # spawns for A
    relay._live = "B"                    # handover
    prev = svc._encoder_tick(prev)      # should kill A's proc, spawn for B
    assert prev == "B"
    assert len(spawns) == 2
    assert spawns[0].killed is True      # old encoder killed
    assert svc._enc_target == "B"
    svc.shutdown()


def t_encoder_tick_noop_when_unchanged():
    relay = _FakeRelay(live="A"); spawns = []
    svc = _svc(relay, spawns)
    svc.acquire()
    prev = svc._encoder_tick(None)
    prev = svc._encoder_tick(prev)      # same feed -> no respawn
    assert len(spawns) == 1
    svc.shutdown()


# --- Fix wave: teardown re-arm race (Finding 1) + per-generation stdin (Finding 2) --
def t_teardown_rearms_when_listener_slips_in():
    # A listener slipped in during the idle-reap window: teardown must NOT close
    # the output ring and must re-arm a fresh supervisor. relay.live_feed()=None
    # so the re-armed supervisor has nothing to encode (stays thread-quiet).
    relay = _FakeRelay(); relay._live = None
    svc = _svc(relay, [])
    out = _FakeRing()
    svc._out = out
    svc._running = True
    svc._listeners = 1
    svc._teardown()
    assert svc._out is out               # ring kept — same object, not nulled
    assert out.closed is False           # and NOT closed
    assert svc._running is True          # re-armed, still running
    svc.shutdown()
    assert out.closed is True            # genuine shutdown finalizes


def t_teardown_finalizes_when_no_listeners():
    relay = _FakeRelay()
    svc = _svc(relay, [])
    out = _FakeRing()
    svc._out = out
    svc._running = True
    svc._listeners = 0
    svc._teardown()
    assert out.closed is True            # normal idle teardown closes the ring
    assert svc._out is None
    assert svc._running is False


def t_feed_stdin_exits_on_own_dead_proc_after_reassign():
    # The old generation's _feed_stdin must exit when ITS OWN proc dies, even
    # after a handover reassigned self._proc to a new live process. If it checked
    # the shared self._proc (alive), this call would loop forever and hang.
    svc = _svc(_FakeRelay(), [])
    mine = _FakeProc(); mine.kill()          # this thread's own proc is dead
    svc._proc = _FakeProc()                   # handover installed a NEW live proc
    svc._feed_stdin(io.BytesIO(), _FakeRing(), mine)   # must return (checks `mine`)
    assert svc._proc.poll() is None           # the reassigned proc is untouched/alive


# --- _program_audio_stream_ring: header contract + streaming loop (thread-free) --
class _CapturingWFile:
    def __init__(self):
        self.chunks = []
    def write(self, b):
        self.chunks.append(bytes(b))


class _ScriptRing:
    """Yields a fixed set of chunks then reports closed (ends the stream loop)."""
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.closed = False
    def live_offset(self):
        return 0
    def read(self, cursor, timeout):
        if self._chunks:
            return self._chunks.pop(0), cursor + 1
        self.closed = True
        return b"", cursor


class _FakeHandler:
    """Minimal stand-in exposing just what _stream_ring touches. We bind the real
    unbound method to it so we test the shipped code path."""
    def __init__(self):
        self.status = None
        self.headers_sent = {}
        self.ended = False
        self.wfile = _CapturingWFile()
    def send_response(self, code):
        self.status = code
    def send_header(self, k, v):
        self.headers_sent[k] = v
    def end_headers(self):
        self.ended = True


class _SvcStub:
    def touch(self):
        pass


def t_stream_ring_headers_and_body():
    h = _FakeHandler()
    ring = _ScriptRing([b"MP3a", b"MP3b"])
    # Bind the real _stream_ring implementation onto our fake handler.
    m._program_audio_stream_ring(h, ring, m.PROGRAM_AUDIO_CONTENT_TYPE, _SvcStub())
    assert h.status == 200
    assert h.headers_sent["Content-Type"] == "audio/mpeg"
    assert h.headers_sent["Cache-Control"] == "no-store"
    assert "Content-Length" not in h.headers_sent      # endless stream
    assert h.ended is True
    assert b"".join(h.wfile.chunks) == b"MP3aMP3b"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
