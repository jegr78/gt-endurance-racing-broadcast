# On-Air Program-Audio Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a toggleable, on-demand audible monitor of the on-air feed's audio next to the (unchanged) silent program still on the Director Panel, Commentator Cockpit, and Race Control desk.

**Architecture:** The relay encodes the on-air feed's audio to an endless MP3 stream via one on-demand ffmpeg (fed from the existing fan-out `FeedRing`), re-served from an output `FeedRing` to many HTTP listeners; the encoder follows the on-air feed across handovers by restarting on the new feed's ring while keeping the same output ring (MP3 frames splice seamlessly). The browser plays it with a bare `<audio>` element behind a speaker toggle (default muted; a user gesture starts it, which also satisfies the autoplay policy).

**Tech Stack:** Python 3 stdlib only (relay `src/relay/racecast-feeds.py`), `ffmpeg` (already a runtime dep), plain HTML/JS front-end, stdlib-only runnable test scripts (no pytest).

## Global Constraints

- **Edit only under `src/`, `tests/`, `tools/`, `docs/`.** `dist/`/`runtime/` are generated — never hand-edit (`dist/.../console_policy.py` is a build copy; ignore it).
- **English only** in all code, comments, docs.
- **No new runtime dependency.** ffmpeg is already required; MP3 via `libmp3lame`.
- **Best-effort contract:** no relay path added here may raise into the request/response or crash the relay — mirror `get_program_screenshot` / `_PreviewRingTap` (any spawn/read failure → silent/unavailable, never an exception up the stack).
- **Tests are stdlib runnable scripts:** each `tests/test_*.py` ends with the `if __name__ == "__main__":` runner that calls every `t_*` function; relay module loaded via `importlib.util.spec_from_file_location("irofeeds", ROOT/"src/relay/racecast-feeds.py")`.
- **Codec is parameterized:** MP3 default via module constants; an AAC switch must be a one-constant edit.
- **Feature default-ON, kill-switch `RACECAST_PROGRAM_AUDIO=0`.** Audio default-muted is a front-end/gesture property, not a relay flag.
- **Fan-out is the precondition:** the tap only runs when `relay.fanout` is true (the default). Fan-out off → endpoints 404, front-end card self-hides. No second re-pull fallback (YAGNI).
- **Run `python3 tools/lint.py` after changing any Python file** (mirrors the CI lint job).

## File Structure

- **Modify `src/relay/racecast-feeds.py`** — pure helpers (`program_audio_enabled`, `program_audio_ffmpeg_cmd`, `should_retarget`) + constants; the `ProgramAudioService` class; `self.program_audio` read in `Relay.__init__`; service construction in `main`; `make_handler` new kwarg + closure; `_stream_ring` handler helper; two routes.
- **Modify `src/scripts/console_policy.py`** — add `["cockpit","program-audio"]` to the ANY cockpit allowlist.
- **Modify `src/director/director-panel.html`, `src/cockpit/cockpit.html`, `src/racecontrol/race-control.html`** — the shared audio control (hidden `<audio>` + toggle + volume + 404 self-hide).
- **Create `tests/test_program_audio.py`** — pure helpers + `ProgramAudioService` lifecycle (fakes, thread-free).
- **Modify `tests/test_console.py`** — assert `["cockpit","program-audio"]` resolves to `Requirement(ANY, False)` and `["preview","program-audio"]` too.
- **Modify `tools/e2e_checks.py` + `tests/test_e2e.py`** — a synthetic check for the audio endpoint headers / 404-when-disabled.
- **Modify `.env.example`, `CLAUDE.md`** — document the flag + feature.
- **Wiki/screenshots** — regenerate `director-panel.png`, cockpit, race-control images; `ui-visual-verification`; wiki prose.

---

### Task 1: `program_audio_enabled` flag helper (pure) + `Relay.program_audio`

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add near the `auto_failover_enabled` block, ~L214; and one line in `Relay.__init__`)
- Test: `tests/test_program_audio.py` (new)

**Interfaces:**
- Produces: `program_audio_enabled(environ) -> bool` (default True; False only on explicit falsey token). `Relay.program_audio: bool`.

- [ ] **Step 1: Write the failing test** — create `tests/test_program_audio.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the on-air program-audio monitor (relay tap).
Run: python3 tests/test_program_audio.py"""
import importlib.util, os

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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_program_audio.py`
Expected: FAIL — `AttributeError: module 'irofeeds' has no attribute 'program_audio_enabled'`

- [ ] **Step 3: Write minimal implementation** — in `src/relay/racecast-feeds.py`, directly after the `auto_failover_enabled` function (~L221):

```python
# ---------- On-air program-audio monitor (#program-audio) ------------------
_PROGRAM_AUDIO_FALSEY = {"0", "false", "no", "off"}


def program_audio_enabled(environ):
    """True unless RACECAST_PROGRAM_AUDIO is an explicit falsey token. Default ON:
    the feature is offered (endpoints + toggle live) whenever fan-out runs; the
    encoder is on-demand so it costs nothing until someone listens. Set
    RACECAST_PROGRAM_AUDIO=0 to disable entirely. Pure so the switch is
    unit-testable. Audio being default-muted is a front-end/gesture property, not
    this flag."""
    return str(environ.get("RACECAST_PROGRAM_AUDIO", "")).strip().lower() not in _PROGRAM_AUDIO_FALSEY
```

Then in `Relay.__init__` (right after `self.fanout = fanout_enabled(os.environ)`, ~L4427) add:

```python
        self.program_audio = program_audio_enabled(os.environ)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_program_audio.py`
Expected: `ok t_program_audio_default_on` / `ok t_program_audio_killswitch` / `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/test_program_audio.py src/relay/racecast-feeds.py
git commit -m "feat(relay): program-audio kill-switch flag (default on)"
```

---

### Task 2: `program_audio_ffmpeg_cmd` + codec constants (pure)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add near `preview_ffmpeg_cmd`, ~L2412)
- Test: `tests/test_program_audio.py`

**Interfaces:**
- Produces: constants `PROGRAM_AUDIO_CODEC`, `PROGRAM_AUDIO_BITRATE`, `PROGRAM_AUDIO_FORMAT`, `PROGRAM_AUDIO_CONTENT_TYPE`, `PROGRAM_AUDIO_SAMPLE_RATE`, `PROGRAM_AUDIO_CHANNELS`, `PROGRAM_AUDIO_RING_BYTES`; `program_audio_ffmpeg_cmd() -> list[str]`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_program_audio.py` (before the runner):

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_program_audio.py`
Expected: FAIL — `AttributeError: ... 'program_audio_ffmpeg_cmd'`

- [ ] **Step 3: Write minimal implementation** — in `src/relay/racecast-feeds.py`, directly after `preview_ffmpeg_cmd` (~L2412) and the `_JPEG_SOI` line:

```python
# --- On-air program-audio monitor: encode the on-air feed's audio to MP3 -----
# Codec/params live in constants so switching to AAC-ADTS (audio/aac, "-c:a aac
# -f adts") is a one-line edit. MP3 is the default for universal <audio>
# decodability (Firefox on Linux may lack system AAC codecs). Fixed sample-rate
# + channel count guarantee frame compatibility across a handover ffmpeg restart
# (both feeds encode to identical params -> the client MP3 stream splices).
PROGRAM_AUDIO_CODEC = "libmp3lame"
PROGRAM_AUDIO_BITRATE = "96k"
PROGRAM_AUDIO_FORMAT = "mp3"
PROGRAM_AUDIO_CONTENT_TYPE = "audio/mpeg"
PROGRAM_AUDIO_SAMPLE_RATE = "44100"
PROGRAM_AUDIO_CHANNELS = "1"
PROGRAM_AUDIO_RING_BYTES = 512 * 1024   # encoded MP3 is low-bitrate; a small ring is ample


def program_audio_ffmpeg_cmd():
    """Argv: read the on-air feed's MPEG-TS on stdin, drop video, encode the
    (optional) audio stream to a fixed-param MP3 on stdout for endless HTTP
    streaming. `0:a:0?` makes audio optional so a video-only feed just yields
    silence rather than an ffmpeg error."""
    return ["ffmpeg", "-nostdin", "-loglevel", "warning", "-i", "pipe:0",
            "-vn", "-map", "0:a:0?",
            "-ar", PROGRAM_AUDIO_SAMPLE_RATE, "-ac", PROGRAM_AUDIO_CHANNELS,
            "-c:a", PROGRAM_AUDIO_CODEC, "-b:a", PROGRAM_AUDIO_BITRATE,
            "-f", PROGRAM_AUDIO_FORMAT, "pipe:1"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_program_audio.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/test_program_audio.py src/relay/racecast-feeds.py
git commit -m "feat(relay): program-audio ffmpeg command + codec constants (MP3)"
```

---

### Task 3: `should_retarget` handover decision (pure)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add right after `program_audio_ffmpeg_cmd`)
- Test: `tests/test_program_audio.py`

**Interfaces:**
- Produces: `should_retarget(prev_live, cur_live, serving) -> bool`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_program_audio.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_program_audio.py`
Expected: FAIL — `AttributeError: ... 'should_retarget'`

- [ ] **Step 3: Write minimal implementation** — after `program_audio_ffmpeg_cmd`:

```python
def should_retarget(prev_live, cur_live, serving):
    """The program-audio encoder should re-point (restart ffmpeg on the new
    feed's ring) only when the on-air feed changed AND the new feed is actually
    serving bytes. Guards against tapping a not-yet-serving / absent feed at a
    handover (mirrors the cut=True guard in Relay.next_auto)."""
    return bool(serving) and cur_live is not None and cur_live != prev_live
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_program_audio.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/test_program_audio.py src/relay/racecast-feeds.py
git commit -m "feat(relay): program-audio handover re-point decision (pure)"
```

---

### Task 4: `ProgramAudioService` (encoder lifecycle + refcount + handover)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add after the `PreviewManager` class, ~L2926)
- Test: `tests/test_program_audio.py`

**Interfaces:**
- Consumes: `FeedRing` (Task's file, existing), `program_audio_ffmpeg_cmd`, `should_retarget`, `external_tool_env()`, `_no_window_kwargs()` (all existing/earlier).
- Produces:
  - `ProgramAudioService(relay, log, idle_timeout=8.0, spawn=None, ring_factory=None)`
  - `.acquire() -> FeedRing | None` — register a listener; `None` if fan-out is off.
  - `.release() -> None` — deregister a listener.
  - `._encoder_tick(prev_live) -> str | None` — one supervisor step (spawn/re-point); returns the feed name now encoding (test seam).
  - `.shutdown() -> None`.
  - Attributes for tests: `._listeners: int`, `._out: FeedRing | None`, `._enc_target: str | None`, `._proc`.
- `spawn()` contract (injectable): returns `(proc, stdin_writable, stdout_readable)`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_program_audio.py`. This uses fakes so it is thread-free and deterministic:

```python
import io, threading  # add to the imports at the top of the file if not present


class _FakeRing:
    def __init__(self):
        self.closed = False
    def live_offset(self):
        return 0
    def read(self, cursor, timeout):
        return b"", cursor          # never yields in tests; we don't run pumps


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_program_audio.py`
Expected: FAIL — `AttributeError: ... 'ProgramAudioService'`

- [ ] **Step 3: Write minimal implementation** — add after `PreviewManager` (~L2926):

```python
class ProgramAudioService:
    """On-demand MP3 encoder of the ON-AIR feed's audio, re-served to many HTTP
    listeners from one output FeedRing. Reference-counted: the encoder starts on
    the first listener (acquire) and a supervisor thread idle-reaps it when the
    last one leaves (release). It follows the on-air feed across handovers by
    restarting ffmpeg on the new feed's ring while keeping the SAME output ring
    (MP3 frames are self-contained -> the client stream splices, only a brief
    silence gap). Requires fan-out (the in-process feed bytes only exist then);
    acquire() returns None otherwise. Best effort throughout: a spawn/read failure
    leaves the output silent and never raises. `spawn`/`ring_factory` injectable
    for tests."""

    def __init__(self, relay, log, idle_timeout=8.0, spawn=None, ring_factory=None):
        self.relay = relay
        self.log = log
        self.idle_timeout = idle_timeout
        self._spawn = spawn or self._spawn_real
        self._ring_factory = ring_factory or (lambda: FeedRing(PROGRAM_AUDIO_RING_BYTES))
        self._out = None            # output FeedRing (encoded MP3), shared by all listeners
        self._proc = None           # current ffmpeg subprocess
        self._enc_target = None     # feed name the encoder is currently pointed at
        self._listeners = 0
        self._last_touch = 0.0
        self._running = False
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # ---- listener lifecycle (called by the HTTP streaming handler) ----
    def acquire(self):
        """Register a listener and return the shared output ring to stream from,
        or None if the feature can't run (fan-out off)."""
        with self._lock:
            if not getattr(self.relay, "fanout", False):
                return None
            self._listeners += 1
            self._last_touch = time.monotonic()
            if not self._running:
                self._out = self._ring_factory()
                self._running = True
                self._stop.clear()
                threading.Thread(target=self._supervise, daemon=True).start()
            return self._out

    def release(self):
        with self._lock:
            if self._listeners > 0:
                self._listeners -= 1
            self._last_touch = time.monotonic()

    def touch(self):
        with self._lock:
            self._last_touch = time.monotonic()

    # ---- encoder supervisor ----
    def _supervise(self):
        prev = None
        while not self._stop.is_set():
            with self._lock:
                idle = (self._listeners == 0
                        and time.monotonic() - self._last_touch > self.idle_timeout)
            if idle:
                break
            prev = self._encoder_tick(prev)
            self._stop.wait(1.0)
        self._teardown()

    def _encoder_tick(self, prev_live):
        """One supervisor step: (re)spawn the encoder for the current on-air feed
        when needed. Returns the feed name now encoding (or prev_live unchanged).
        The test seam — pure of threads/sleeps."""
        live = self.relay.live_feed()
        feed = self.relay.feeds.get(live) if live else None
        ring = getattr(feed, "ring", None)
        serving = ring is not None
        if self._proc is None or should_retarget(self._enc_target, live, serving):
            if serving:
                self._restart_encoder(live, ring)
                return live
        return prev_live if self._enc_target is None else self._enc_target

    def _restart_encoder(self, live, ring):
        self._kill_proc()
        try:
            proc, stdin, stdout = self._spawn()
        except Exception as e:                     # noqa: BLE001 best-effort
            self.log.info("program-audio spawn error: %s", e)
            self._proc = None
            self._enc_target = None
            return
        self._proc = proc
        self._enc_target = live
        threading.Thread(target=self._feed_stdin, args=(stdin, ring), daemon=True).start()
        threading.Thread(target=self._pump_stdout, args=(stdout,), daemon=True).start()

    def _spawn_real(self):
        ff = subprocess.Popen(program_audio_ffmpeg_cmd(), stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=False, env=external_tool_env(), **_no_window_kwargs())
        threading.Thread(target=self._pump_stderr, args=(ff.stderr,), daemon=True).start()
        return ff, ff.stdin, ff.stdout

    def _feed_stdin(self, stdin, ring):
        """Pump on-air ring bytes into this encoder's ffmpeg stdin; join at the
        ring's current live edge (only recent data, no rewind)."""
        cursor = ring.live_offset() if hasattr(ring, "live_offset") else 0
        try:
            while not self._stop.is_set() and not getattr(ring, "closed", False):
                data, cursor = ring.read(cursor, 1.0)
                if data:
                    stdin.write(data); stdin.flush()
                if self._proc is None or self._proc.poll() is not None:
                    break                          # encoder gone (killed on handover)
        except OSError:
            pass                                   # ffmpeg stdin closed
        finally:
            try:
                stdin.close()
            except OSError:
                pass

    def _pump_stdout(self, stdout):
        """Pump encoded MP3 bytes from ffmpeg stdout into the shared output ring."""
        out = self._out
        try:
            while not self._stop.is_set():
                chunk = stdout.read(65536)
                if not chunk:
                    break                          # encoder EOF (killed / died)
                if out is not None:
                    out.write(chunk)
        except OSError:
            pass

    def _pump_stderr(self, stderr):
        for line in _decode_lines(iter(stderr.readline, b"")):
            if self._stop.is_set():
                break
            line = line.strip()
            if line:
                self.log.info("[program-audio ffmpeg] %s", line)

    def _kill_proc(self):
        p = self._proc
        try:
            if p and p.poll() is None:
                p.kill()
        except Exception:                          # noqa: BLE001
            pass

    def _teardown(self):
        self._kill_proc()
        self._proc = None
        self._enc_target = None
        with self._lock:
            self._running = False
            if self._out is not None:
                try:
                    self._out.close()
                except Exception:                  # noqa: BLE001
                    pass
                self._out = None

    def shutdown(self):
        self._stop.set()
        self._teardown()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_program_audio.py`
Expected: `ALL PASS` (all `t_*` including the four `ProgramAudioService` cases)

- [ ] **Step 5: Commit**

```bash
git add tests/test_program_audio.py src/relay/racecast-feeds.py
git commit -m "feat(relay): ProgramAudioService — on-demand on-air MP3 encoder"
```

---

### Task 5: console_policy — allow `/console/cockpit/program-audio` (ANY)

**Files:**
- Modify: `src/scripts/console_policy.py` (the ANY cockpit allowlist tuple, ~L145)
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: `console_policy.min_capability`, `Requirement`, `ANY` (existing).
- Produces: `min_capability(["cockpit","program-audio"]) == Requirement(ANY, False)`.

Note: `["preview","program-audio"]` already resolves to `Requirement(ANY, False)` via the existing `p[0] in ("hud","preview","splitscreen")` rule — the test below asserts both, but only the cockpit tuple needs a code change.

- [ ] **Step 1: Write the failing test** — add to `tests/test_console.py` (follow the file's existing import of `console_policy` as e.g. `cp`; match the local alias used there). Add near the other `min_capability` ANY assertions:

```python
def t_program_audio_endpoints_are_any():
    # Cockpit + Race Control desk stream (funnelled under /console/cockpit/...)
    assert cp.min_capability(["cockpit", "program-audio"]) == cp.Requirement(cp.ANY, False)
    # Director Panel stream (tailnet /preview/... and /console/preview/... via gate)
    assert cp.min_capability(["preview", "program-audio"]) == cp.Requirement(cp.ANY, False)
```

(If `tests/test_console.py` imports the module under a different alias than `cp`, use that alias.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_console.py`
Expected: FAIL on the `["cockpit","program-audio"]` assertion (`min_capability` returns `None` → not equal).

- [ ] **Step 3: Write minimal implementation** — in `src/scripts/console_policy.py`, extend the ANY cockpit allowlist tuple (the `if p in ([...])` block ~L145). Add `["cockpit", "program-audio"]` as a new element:

```python
    if p in (["cockpit"], ["cockpit", "data"], ["cockpit", "program"],
             ["cockpit", "program-audio"],   # on-air program-audio MP3 stream (ANY, read-only)
             ["cockpit", "timer"], ["cockpit", "chat", "data"],
             ["cockpit", "chat", "send"],
             ["cockpit", "cues"], ["cockpit", "cues", "ack"],
             ["cockpit", "rc-notes"],      # RC->commentator notes read (#376)
             ["cockpit", "cue-back"]):     # commentator->director cue-back send (#377)
        return Requirement(ANY, False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_console.py`
Expected: PASS (and `python3 tests/test_console_gate.py` still passes).

- [ ] **Step 5: Commit**

```bash
git add tests/test_console.py src/scripts/console_policy.py
git commit -m "feat(console): allow /console/cockpit/program-audio (ANY, read-only)"
```

---

### Task 6: `_stream_ring` handler helper + the two routes + service wiring

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `make_handler` signature (add `program_audio_service=None` kwarg, alongside `preview_manager=...`); add `_stream_ring` to class `H` (next to `_send_jpeg`, ~L5178); add two routes in `do_GET` (the director route next to `["preview","program"]` ~L5959; the cockpit route next to `["cockpit","program"]` ~L6123); construct the service in `main` (next to `preview_manager = PreviewManager(...)`, ~L7047) and pass it into `make_handler` (~L7075).
- Test: `tests/test_program_audio.py` (unit test `_stream_ring`'s header contract via a fake handler); manual smoke described below.

**Interfaces:**
- Consumes: `ProgramAudioService.acquire/release/touch`, `PROGRAM_AUDIO_CONTENT_TYPE`, existing `self._send`, `self._console_auth`.
- Produces: routes `GET /preview/program-audio` (director; tailnet ungated / `/console/...` ANY via gate) and `GET /cockpit/program-audio` (cockpit + race-control; inner `_console_auth`); handler method `_stream_ring(self, ring, content_type, service)`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_program_audio.py`. It exercises the header contract + the streaming loop against a fake `wfile`/ring without a real socket:

```python
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
```

Note: the shipped `_stream_ring` lives as a method on `H`; to unit-test it thread-free we also expose a module-level `_program_audio_stream_ring(handler, ring, content_type, service)` and have the method delegate to it. Both are added in Step 3.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_program_audio.py`
Expected: FAIL — `AttributeError: ... '_program_audio_stream_ring'`

- [ ] **Step 3: Write minimal implementation**

(a) Module-level streaming core (add near the other module helpers, e.g. right after `should_retarget`):

```python
def _program_audio_stream_ring(handler, ring, content_type, service):
    """Write an endless byte stream from a FeedRing to an HTTP client. Shared core
    of the H._stream_ring method (module-level so it is unit-testable without a
    socket). No Content-Length: the client reads until it disconnects, which makes
    handler.wfile.write raise (caught) -> the caller's finally releases the
    listener."""
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.end_headers()
    cursor = ring.live_offset() if hasattr(ring, "live_offset") else 0
    try:
        while not getattr(ring, "closed", False):
            data, cursor = ring.read(cursor, 1.0)
            if data:
                handler.wfile.write(data)
            service.touch()
    except (OSError, ValueError):
        pass                       # client disconnected mid-write
    return None
```

(b) The `H` method (next to `_send_jpeg`, ~L5178):

```python
        def _stream_ring(self, ring, content_type, service):
            return _program_audio_stream_ring(self, ring, content_type, service)
```

(c) `make_handler` signature — add the kwarg (next to `preview_manager=None`):

```python
                     preview_manager=None, program_audio_service=None,
```

(d) Director route in `do_GET`, immediately after the `["preview","program"]` block (~L5966):

```python
                if p == ["preview", "program-audio"]:
                    if program_audio_service is None:
                        return self._send({"error": "program audio disabled"}, 404)
                    ring = program_audio_service.acquire()
                    if ring is None:               # fan-out off -> no in-process feed bytes
                        return self._send({"error": "program audio unavailable"}, 404)
                    try:
                        return self._stream_ring(ring, PROGRAM_AUDIO_CONTENT_TYPE,
                                                 program_audio_service)
                    finally:
                        program_audio_service.release()
```

(e) Cockpit/Race-Control route, immediately after the `["cockpit","program"]` block (~L6131):

```python
                    if p == ["cockpit", "program-audio"]:
                        if self._console_auth() is None:
                            return None
                        if program_audio_service is None:
                            return self._send({"error": "program audio disabled"}, 404)
                        ring = program_audio_service.acquire()
                        if ring is None:
                            return self._send({"error": "program audio unavailable"}, 404)
                        try:
                            return self._stream_ring(ring, PROGRAM_AUDIO_CONTENT_TYPE,
                                                     program_audio_service)
                        finally:
                            program_audio_service.release()
```

(f) Construction in `main` (right after `preview_manager = PreviewManager(relay, lambda: _obs_ws, LOG)`, ~L7047):

```python
    program_audio_service = (ProgramAudioService(relay, LOG)
                             if relay.program_audio else None)
```

(g) Pass into `make_handler` (add to the kwargs list next to `preview_manager=preview_manager`, ~L7075):

```python
                           program_audio_service=program_audio_service,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_program_audio.py`
Expected: `ALL PASS` (incl. `t_stream_ring_headers_and_body`).

Then a live smoke check (manual, needs a running relay with fan-out + a live feed; skip if none handy — the e2e task covers the headless case):

Run: `python3 src/racecast.py relay run` in one shell, then in another:
`curl -sN http://127.0.0.1:8088/preview/program-audio | head -c 4 | xxd`
Expected: bytes flow (MP3 frame sync `ff fb`/`ff f3`/`ff f2` or an ID3 tag); when `RACECAST_PROGRAM_AUDIO=0`, `curl -s -o /dev/null -w '%{http_code}'` returns `404`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_program_audio.py src/relay/racecast-feeds.py
git commit -m "feat(relay): stream on-air program audio (/preview + /cockpit routes)"
```

---

### Task 7: Front-end audio control across the three console pages

**Files:**
- Modify: `src/director/director-panel.html` (near the `#pvProgram` `<img>` / `#pvProgramFrame`, ~L491; JS near `pvSetProgram`, ~L2052)
- Modify: `src/cockpit/cockpit.html` (near `<img id="program">`, ~L286; JS near `pollProgram`, ~L525)
- Modify: `src/racecontrol/race-control.html` (near `<img id="program">`, ~L177; JS near `pollProgram`, ~L371)

**Interfaces:**
- Consumes: the `RC_API(path)` shim (present in all three pages; resolves tailnet vs `/console` base) and existing page styling.
- Produces: a hidden `<audio id="pgmAudio">` + a `<button id="pgmAudioBtn">` speaker toggle + `<input id="pgmAudioVol" type="range">` next to the program monitor, wired to the correct endpoint per page. Card self-hides on a probe 404.

Endpoint per page:
- Director Panel → `RC_API("/preview/program-audio")`
- Cockpit → `RC_API("/cockpit/program-audio")`
- Race Control → `RC_API("/cockpit/program-audio")` (reuses the cockpit stream)

- [ ] **Step 1: Add the markup** — in each page, directly after the program monitor `<img>`/frame, insert (adjust class names to match the page's existing button styling; keep IDs exactly as below):

```html
<div id="pgmAudioBar" style="display:none; align-items:center; gap:8px; margin-top:6px;">
  <button id="pgmAudioBtn" type="button" aria-pressed="false" title="Listen to on-air audio">🔇 Audio</button>
  <input id="pgmAudioVol" type="range" min="0" max="1" step="0.05" value="0.8"
         aria-label="Program audio volume" style="width:110px;">
  <audio id="pgmAudio" preload="none" style="display:none;"></audio>
</div>
```

- [ ] **Step 2: Add the JS** — in each page, add this block and call `pgmAudioInit(ENDPOINT)` once on load (`ENDPOINT` per the table above). Uses only the page's existing `RC_API`:

```javascript
function pgmAudioInit(endpoint) {
  var bar = document.getElementById('pgmAudioBar');
  var btn = document.getElementById('pgmAudioBtn');
  var vol = document.getElementById('pgmAudioVol');
  var au  = document.getElementById('pgmAudio');
  if (!bar || !btn || !au) return;
  var url = RC_API(endpoint);
  // Probe: show the control only if the endpoint exists (feature on + fan-out on).
  fetch(url, { method: 'HEAD' }).then(function (r) {
    if (r.status === 404) return;            // disabled -> stay hidden
    bar.style.display = 'flex';
  }).catch(function () { /* leave hidden */ });
  au.volume = parseFloat(vol.value);
  vol.addEventListener('input', function () { au.volume = parseFloat(vol.value); });
  var on = false;
  btn.addEventListener('click', function () {
    on = !on;
    if (on) {
      au.src = url + (url.indexOf('?') < 0 ? '?' : '&') + 'ts=' + Date.now();
      au.play().catch(function () { on = false; setBtn(); });  // gesture satisfies autoplay
    } else {
      au.pause(); au.removeAttribute('src'); au.load();        // drop the connection -> relay reaps encoder
    }
    setBtn();
  });
  function setBtn() {
    btn.textContent = (on ? '🔊' : '🔇') + ' Audio';
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
  }
}
```

Wire-up per page (add where the page kicks off its other pollers):
- `src/director/director-panel.html` (near where `pvSetProgram()` is first started, ~L2063): `pgmAudioInit("/preview/program-audio");`
- `src/cockpit/cockpit.html` (near where `pollProgram()` is kicked off, ~L915): `pgmAudioInit("/cockpit/program-audio");`
- `src/racecontrol/race-control.html` (near where `pollProgram()` is kicked off, ~L576): `pgmAudioInit("/cockpit/program-audio");`

- [ ] **Step 3: Verify each page still parses / no console errors** — start the relay + open each page, confirm no JS console errors and the bar appears only when the feature is available:

Run: `python3 src/racecast.py relay run` (fan-out default on), open `http://127.0.0.1:8088/panel`; confirm the "🔇 Audio" control shows. Then restart with `RACECAST_PROGRAM_AUDIO=0 python3 src/racecast.py relay run` and confirm the control stays hidden on all three pages.

(No unit test — HTML/JS; the e2e task and the visual-verification gate cover behavior.)

- [ ] **Step 4: Commit**

```bash
git add src/director/director-panel.html src/cockpit/cockpit.html src/racecontrol/race-control.html
git commit -m "feat(console): on-air audio toggle on Director Panel, Cockpit, Race Control"
```

---

### Task 8: e2e synthetic check — audio endpoint headers / 404-when-disabled

**Files:**
- Modify: `tools/e2e_checks.py` (add a `check_program_audio_*` to the pure check registry; follow the existing `check_*` signature and `SYNTHETIC_CHECKS` list)
- Modify: `tests/test_e2e.py` (register/exercise the new check in the pure-piece tests, matching how existing checks are unit-tested there)

**Interfaces:**
- Consumes: the existing `http_request` helper + `CheckResult` in `tools/e2e_checks.py`.
- Produces: a synthetic check asserting the enabled relay serves `/preview/program-audio` with `Content-Type: audio/mpeg` (read a few bytes then close), and the cockpit-disabled relay 404s it.

- [ ] **Step 1: Write the failing test** — in `tests/test_e2e.py`, add a unit test that the new check function exists and is in `SYNTHETIC_CHECKS`, mirroring the existing check-registry tests:

```python
def t_program_audio_check_registered():
    names = [c.__name__ for c in e2e.SYNTHETIC_CHECKS]
    assert "check_program_audio_stream" in names
```

(Use the same module alias `e2e`/`e2e_checks` that `tests/test_e2e.py` already imports.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_e2e.py`
Expected: FAIL — `check_program_audio_stream` not found.

- [ ] **Step 3: Write minimal implementation** — in `tools/e2e_checks.py`, add (matching the file's `CheckResult` + `http_request` conventions):

```python
def check_program_audio_stream(ctx):
    """The enabled relay streams on-air program audio as audio/mpeg. We only read
    the response headers (a few bytes may or may not flow under the no-op
    streamlink stubs); the assertion is the content type + 200, and that the
    cockpit-DISABLED relay 404s the cockpit variant."""
    r = http_request(ctx.base_url + "/preview/program-audio", method="GET",
                     timeout=5, read_bytes=64)
    if r.status != 200:
        return CheckResult("program_audio_stream", False,
                           "expected 200, got %s" % r.status)
    ctype = r.headers.get("Content-Type", "")
    if "audio/mpeg" not in ctype:
        return CheckResult("program_audio_stream", False,
                           "expected audio/mpeg, got %r" % ctype)
    return CheckResult("program_audio_stream", True, "audio/mpeg stream served")
```

Add `check_program_audio_stream` to the `SYNTHETIC_CHECKS` list. If `http_request` lacks a `read_bytes` bounded-read arg, add one (read at most N bytes then close the connection) so the check never blocks on the endless stream — this is the one behavioral change the endless response forces on the harness; document it in the helper's docstring.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_e2e.py`
Expected: PASS.
Then the full harness locally: `python3 tools/e2e.py` — expected: the new check appears and passes (enabled relay serves `audio/mpeg`).

- [ ] **Step 5: Commit**

```bash
git add tools/e2e_checks.py tests/test_e2e.py
git commit -m "test(e2e): program-audio endpoint content-type check (synthetic)"
```

---

### Task 9: Docs — `.env.example` + `CLAUDE.md`

**Files:**
- Modify: `.env.example` (add the flag with a comment)
- Modify: `CLAUDE.md` (a short paragraph in the relay section)

**Interfaces:** none (documentation).

- [ ] **Step 1: Add the flag to `.env.example`** — near the other `RACECAST_*` machine knobs:

```bash
# On-air program-audio monitor (Director Panel / Cockpit / Race Control): the
# relay encodes the on-air feed's audio to an MP3 stream the console pages can
# toggle on. Default ON, audio is muted until a listener clicks; the encoder is
# on-demand (zero cost when nobody listens) and requires the feed fan-out. Set to
# 0 to disable the feature entirely.
RACECAST_PROGRAM_AUDIO=1
```

- [ ] **Step 2: Document in `CLAUDE.md`** — in the relay section (after the broadcast-chat / cue paragraphs), add a concise paragraph:

```markdown
The relay also serves an optional **on-air program-audio monitor**: the on-air
feed's audio, encoded to an endless MP3 stream and offered as a toggle next to the
silent program still on the Director Panel, Commentator Cockpit, and Race Control
desk. Endpoints `GET /preview/program-audio` (director; ANY) and
`GET /console/cockpit/program-audio` (cockpit + race-control; ANY, funnelled under
the existing `/console` mount — no new public surface). One on-demand ffmpeg
(`libmp3lame`, codec parameterized via `PROGRAM_AUDIO_*` constants) taps the feed
fan-out ring and is re-served to many listeners from one output `FeedRing`
(`ProgramAudioService`, reference-counted + idle-reaped — zero cost when nobody
listens); it follows the on-air feed across handovers by restarting on the new
feed's ring (MP3 frames splice, brief silence gap). Requires fan-out (endpoints
404 otherwise; the front-end card self-hides). Default ON; kill-switch
`RACECAST_PROGRAM_AUDIO=0`. NOT the full OBS program mix — feed-audio only (see
`docs/superpowers/specs/2026-07-02-program-audio-monitor-design.md`). Tests:
`tests/test_program_audio.py`.
```

- [ ] **Step 3: Verify build self-check + lint**

Run: `python3 tools/lint.py`
Expected: no findings.

- [ ] **Step 4: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs: document the on-air program-audio monitor + RACECAST_PROGRAM_AUDIO"
```

---

### Task 10: Full suite + wiki screenshots + visual verification

**Files:**
- Modify: `src/docs/wiki/images/director-panel.png` and the cockpit + race-control images under `src/docs/wiki/images/` (and their `src/docs/slides/assets/img/` twins if present) — regenerated, not hand-edited.
- Modify: relevant wiki prose pages under `src/docs/wiki/` (a short "enable audio" note on the Director Panel / Cockpit / Race Control pages).

**Interfaces:** none (assets + prose).

- [ ] **Step 1: Run the whole test suite + lint**

Run: `python3 tools/run-tests.py && python3 tools/lint.py`
Expected: all green (this is exactly what CI runs).

- [ ] **Step 2: Build self-verify**

Run: `python3 tools/build.py`
Expected: the verify step passes (tokenization, no secrets, no shell scripts, preflight present).

- [ ] **Step 3: Visual verification (blocking gate)** — invoke the **`ui-visual-verification`** skill and render each changed surface (Director Panel, Cockpit, Race Control) from a local dev build; eyeball the "🔇 Audio" toggle + volume slider placement and that toggling starts/stops audio. This satisfies the Stop-hook marker.

- [ ] **Step 4: Regenerate wiki screenshots** — invoke the **`wiki-screenshots`** skill (demo profile + `tools/obs-sim.py` stand-in) and recapture `director-panel.png`, the cockpit, and the race-control images as element screenshots matching the existing framing. Add the short "enable on-air audio" note to the matching wiki prose pages.

- [ ] **Step 5: Commit**

```bash
git add src/docs/wiki src/docs/slides
git commit -m "docs(wiki): refresh Director Panel / Cockpit / Race Control shots for audio toggle"
```

- [ ] **Step 6: Push + open the PR** (per the repo's one-PR-per-feature flow):

```bash
git push -u origin feat/program-audio-monitor
gh pr create --fill
```

---

## Self-Review

**Spec coverage:**
- On-air feed audio, follows handover → Tasks 3, 4 (`should_retarget`, `_encoder_tick`). ✓
- Available by default / audio default-muted / on-demand / kill-switch → Tasks 1 (flag), 4 (refcount + idle reaper), 7 (gesture-muted toggle). ✓
- Progressive HTTP MP3, parameterized codec → Tasks 2, 6. ✓
- Endpoints + ANY auth, no new public surface → Tasks 5, 6. ✓
- Front-end on all three pages, 404 self-hide → Task 7. ✓
- Fan-out precondition / 404 otherwise → Tasks 4 (`acquire` returns None), 6 (routes). ✓
- Edge cases (no audio track, handover gap, dead socket, POV, qualifying) → covered by `0:a:0?` (Task 2), MP3 splice + `_restart_encoder` (Task 4), `_stream_ring` try/except (Task 6), on-air-only via `live_feed()` (Task 4). ✓
- Testing (pure pieces, lifecycle, auth, e2e) → Tasks 1–5, 8. ✓
- Docs + screenshots → Tasks 9, 10. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The one deliberately open detail — matching the local module alias in `tests/test_console.py` / `tests/test_e2e.py` and the page button class names — is called out explicitly with instructions, not left vague.

**Type consistency:** `ProgramAudioService.acquire()` returns the ring or `None` (Task 4) and callers branch on `None` (Task 6). `_program_audio_stream_ring(handler, ring, content_type, service)` signature matches the `H._stream_ring` delegate and the test (Task 6). `should_retarget(prev_live, cur_live, serving)` signature matches its test (Task 3) and caller `_encoder_tick` (Task 4). `program_audio_ffmpeg_cmd()` / constants names match across Tasks 2, 4, 6, 9.

**Scope:** Single feature, one PR; task boundaries are independently reviewable/committable.
