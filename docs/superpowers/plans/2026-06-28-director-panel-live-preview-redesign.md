# Director Panel live-preview redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Director Panel feed tiles show auto-updating per-second stills of every feed plus an audio-level meter on the off-air feed, sourced from OBS for active feeds and from one decoupled low-res pull for the off-air feed, so a remote director can verify the upcoming feed before a Splitscreen swap — without the broken loopback grab and without threatening the broadcast.

**Architecture:** A new relay-side `PreviewManager` owns (a) a short-TTL cache of OBS source screenshots for the on-air feed / active POV, and (b) one reference-counted, idle-stopped low-res (360p) pull for the off-air feed that produces both a ~1 fps still and a continuous ebur128 audio level. All directors poll the relay's per-tile cache, so delivery cost is flat in the number of viewers. The live feed↔OBS transport is untouched (deeper fan-out work is deferred to issue #358).

**Tech Stack:** Python 3 stdlib only (no framework, no pytest); existing external tools `ffmpeg`, `streamlink`, `yt-dlp`; the relay's `BaseHTTPRequestHandler` server; `src/scripts/obs_ws.py` (obs-websocket v5). Tests are runnable stdlib scripts.

Spec: `docs/superpowers/specs/2026-06-28-director-panel-live-preview-redesign-design.md`

## Global Constraints

- **Edit only under `src/` (and `tests/`, `docs/`).** `dist/`/`runtime/` are generated — never hand-edit.
- **All scripts and docs are English only.**
- **No hardcoded secrets or machine paths.** Tests use no real IPs/paths (Tailscale test range `100.64.0.0/10` only).
- **Python-only tooling.** No `.sh`/`.bat`.
- **Tests are stdlib runnable scripts** (`python3 tests/test_X.py`), functions named `t_*`, plain `assert`, auto-run by the file's `__main__` loop. No pytest.
- **The relay must stay dependency-light and best-effort:** every new preview path must never raise into the server and must never affect the live feed workers (same contract as `get_program_screenshot`).
- **Cross-platform** (CI matrix includes Windows): reuse `external_tool_env()` and `_no_window_kwargs()` for every subprocess; never assemble fixed-OS paths with `os.path.join`.
- **Changed a UI surface → refresh its wiki screenshot in the same change.** The Director Panel maps to `src/docs/wiki/images/director-panel.png` (regenerate via the `wiki-screenshots` skill).
- **Run `python3 tools/lint.py` after changing any Python file**, and `python3 tools/run-tests.py` before finishing.

## File Structure

- `src/relay/racecast-feeds.py` (modify) — extend `preview_source`; add pure argv builders, MJPEG splitter, ebur128 parser, `lufs_to_meter`; add `_PreviewPullWorker` + `PreviewManager`; rework the `/preview/feed/*` endpoint, add `/preview/levels`; add `preview_manager` param to `make_handler`; instantiate + wire in `main`; add the `/console/preview/*` any-auth rewrite in `_console_gate`; remove dead `feed_grab_cmd`/`grab_feed_frame`.
- `tests/test_preview.py` (create) — pure builders, splitter, parser, worker (fake spawn), manager (fake obs + fake worker), endpoint round-trip.
- `tests/test_pov.py` (modify) — update the `t_preview_source_*` tests to the new `("pull", …)` shape; remove `t_feed_grab_cmd_pinned`.
- `src/director/director-panel.html` (modify) — auto-polling still tiles, audio bar on the off-air tile, per-tile play/pause.
- `src/docs/wiki/images/director-panel.png` (regenerate).

## Interfaces locked in this plan (names later tasks rely on)

- `preview_source(target, live, pov_active, feed_keys) -> ("obs", source_name) | ("pull", feed_key) | ("placeholder", reason)`
- `PREVIEW_FMT_YT = "b[height<=360]/w"`, `PREVIEW_QUALITY_YT = "best"`, `PREVIEW_QUALITY_TW = "360p,480p,worst"`, `PREVIEW_STILL_WIDTH = 480`
- `preview_pull_streamlink_cmd(target, platform, quality, cookies=None, user_agent=STREAMLINK_YT_UA) -> list[str]`
- `preview_ffmpeg_cmd(width=PREVIEW_STILL_WIDTH) -> list[str]`
- `split_mjpeg_frames(buf: bytes) -> (list[bytes], bytes)`  # complete JPEGs, remainder
- `parse_ebur128_momentary(line: str) -> float | None`  # momentary LUFS
- `lufs_to_meter(lufs: float | None) -> float`  # 0.0..1.0
- `_PreviewPullWorker(target, channel, platform, cookies, log, spawn=None)` with `.start()`, `.stop()`, `.latest_frame() -> bytes|None`, `.latest_level() -> float`, `.target`, `.ok`
- `PreviewManager(relay, obs_ws_get, log, obs_ttl=1.0, idle_timeout=8.0)` with `.still(target) -> (bytes|None, note)`, `.levels() -> dict`, `.run()` (idle reaper loop), `.shutdown()`
- `make_handler(..., preview_manager=None)`

---

### Task 1: Re-point `preview_source` from loopback-grab to off-air pull

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`preview_source`, ~2152-2172)
- Test: `tests/test_pov.py` (update `t_preview_source_*`, ~69-92)

**Interfaces:**
- Produces: `preview_source(target, live, pov_active, feed_keys) -> ("obs", name) | ("pull", key) | ("placeholder", reason)`. `feed_keys` is the set of configured feed keys (e.g. `{"A","B"}`, plus `"POV"` when a POV feed exists).

- [ ] **Step 1: Update the failing tests** in `tests/test_pov.py` — replace the off-air `("grab", port)` expectations and adapt the 4th arg to a set of feed keys:

```python
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
```

- [ ] **Step 2: Run the tests, verify they FAIL**

Run: `python3 tests/test_pov.py`
Expected: AssertionError in `t_preview_source_offair_uses_pull` (current code returns `("grab", …)`).

- [ ] **Step 3: Rewrite `preview_source`**

```python
def preview_source(target, live, pov_active, feed_keys):
    """Pure: how to source a feed preview tile.

    target      'A' | 'B' | 'POV'
    live        the on-air feed ('A' | 'B') from Relay.live_feed()
    pov_active  Relay.pov_active()
    feed_keys   the configured feed keys, e.g. {'A','B'} (+'POV' when a POV feed exists)

    Returns ('obs', source_name) | ('pull', feed_key) | ('placeholder', reason).
    The on-air feed and the active POV are decoding in OBS, so screenshot the
    source directly. The off-air feed is NOT decoded by OBS and its loopback port
    is held single-consumer by OBS, so it needs a decoupled low-res pull (handled
    by PreviewManager). A paused POV / unconfigured feed has nothing to show."""
    if target == "POV":
        return ("obs", "Feed POV") if pov_active else ("placeholder", "pov off")
    if target in ("A", "B"):
        if target not in feed_keys:
            return ("placeholder", "feed off")
        if target == live:
            return ("obs", "Feed " + target)
        return ("pull", target)
    return ("placeholder", "unknown feed")
```

- [ ] **Step 4: Run the tests, verify they PASS**

Run: `python3 tests/test_pov.py`
Expected: `ALL PASS` (note: `t_feed_grab_cmd_pinned` still references the old helper — it is removed in Task 8; until then keep `feed_grab_cmd` defined so this file still imports. It does, so the suite passes here.)

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(preview): off-air tiles use a decoupled pull, not the loopback grab

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Pure argv builders for the off-air low-res pull

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add constants + builders near `streamlink_serve_cmd`, ~2124-2146)
- Test: `tests/test_preview.py` (create)

**Interfaces:**
- Consumes: `STREAMLINK_YT_UA` (existing browser UA constant used by `streamlink_serve_cmd`).
- Produces: `PREVIEW_FMT_YT`, `PREVIEW_QUALITY_YT`, `PREVIEW_QUALITY_TW`, `PREVIEW_STILL_WIDTH`, `preview_pull_streamlink_cmd(...)`, `preview_ffmpeg_cmd(width)`.

- [ ] **Step 1: Write the failing tests** in a new `tests/test_preview.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the Director Panel live preview. Run: python3 tests/test_preview.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_preview_pull_streamlink_cmd_twitch():
    cmd = m.preview_pull_streamlink_cmd("https://twitch.tv/foo", "twitch",
                                        m.PREVIEW_QUALITY_TW)
    assert cmd == ["streamlink", "--stdout", "--",
                   "https://twitch.tv/foo", m.PREVIEW_QUALITY_TW]


def t_preview_pull_streamlink_cmd_youtube_has_ua_and_cookies():
    cmd = m.preview_pull_streamlink_cmd("https://hls.example/360.m3u8", "youtube",
                                        m.PREVIEW_QUALITY_YT,
                                        cookies="/tmp/yt.txt", user_agent="UA/1")
    assert "--http-header" in cmd and "User-Agent=UA/1" in cmd
    assert "--http-cookies-file" in cmd and "/tmp/yt.txt" in cmd
    assert cmd[-2:] == ["https://hls.example/360.m3u8", m.PREVIEW_QUALITY_YT]
    assert cmd[0] == "streamlink" and "--stdout" in cmd


def t_preview_ffmpeg_cmd_pinned():
    assert m.preview_ffmpeg_cmd(480) == [
        "ffmpeg", "-nostdin", "-loglevel", "info", "-i", "pipe:0",
        "-map", "0:v:0", "-vf", "fps=1,scale=480:-2", "-f", "mjpeg", "pipe:1",
        "-map", "0:a:0?", "-af", "ebur128", "-f", "null", "-"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run, verify FAIL**

Run: `python3 tests/test_preview.py`
Expected: AttributeError (`preview_pull_streamlink_cmd` not defined).

- [ ] **Step 3: Add constants + builders** in `src/relay/racecast-feeds.py` immediately after `streamlink_serve_cmd` (after ~line 2146):

```python
# --- Director Panel off-air preview pull (decoupled from OBS / the loopback port) ---
PREVIEW_FMT_YT = "b[height<=360]/w"     # yt-dlp: pick YouTube's 360p rendition (worst fallback)
PREVIEW_QUALITY_YT = "best"             # the resolved YT URL is already the 360p rendition
PREVIEW_QUALITY_TW = "360p,480p,worst"  # Twitch named qualities (low first)
PREVIEW_STILL_WIDTH = 480               # JPEG width of a preview still


def preview_pull_streamlink_cmd(target, platform, quality,
                                cookies=None, user_agent=STREAMLINK_YT_UA):
    """Argv: stream a LOW-res copy of a feed to stdout for the preview ffmpeg.
    Decoupled from the feed's loopback port (single-consumer, held by OBS). For
    YouTube `target` is a pre-resolved 360p HLS URL and needs the same browser
    UA + cookies context as the real feed (#345); Twitch gets the twitch.tv URL
    and its plugin picks the named quality. `--` guards the positional URL."""
    cmd = ["streamlink", "--stdout"]
    if platform != "twitch":
        if user_agent:
            cmd += ["--http-header", "User-Agent=" + user_agent]
        if cookies:
            cmd += ["--http-cookies-file", cookies]
    return cmd + ["--", target, quality]


def preview_ffmpeg_cmd(width=PREVIEW_STILL_WIDTH):
    """Argv: read the streamlink pipe on stdin, emit a 1 fps scaled MJPEG on
    stdout (latest-frame source) AND run ebur128 on the audio (its per-second
    measurements print to stderr at loglevel info -> parsed for the level bar).
    Audio is optional (`0:a:0?`) so a video-only feed still yields stills."""
    return ["ffmpeg", "-nostdin", "-loglevel", "info", "-i", "pipe:0",
            "-map", "0:v:0", "-vf", "fps=1,scale=%d:-2" % width,
            "-f", "mjpeg", "pipe:1",
            "-map", "0:a:0?", "-af", "ebur128", "-f", "null", "-"]
```

- [ ] **Step 4: Run, verify PASS**

Run: `python3 tests/test_preview.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_preview.py
git commit -m "feat(preview): pinned argv builders for the off-air low-res pull

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Pure MJPEG frame splitter + ebur128 level parser

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add the three pure functions near the builders)
- Test: `tests/test_preview.py`

**Interfaces:**
- Produces: `split_mjpeg_frames(buf) -> (frames, remainder)`, `parse_ebur128_momentary(line) -> float|None`, `lufs_to_meter(lufs) -> float`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_preview.py`, before the `__main__` block):

```python
def t_split_mjpeg_frames_extracts_complete_jpegs():
    soi, eoi = b"\xff\xd8", b"\xff\xd9"
    a = soi + b"AAAA" + eoi
    b = soi + b"BBBB" + eoi
    frames, rem = m.split_mjpeg_frames(b"\x00\x00" + a + b + soi + b"CC")
    assert frames == [a, b]
    assert rem == soi + b"CC"          # incomplete trailing frame is kept


def t_split_mjpeg_frames_no_complete_frame():
    frames, rem = m.split_mjpeg_frames(b"\xff\xd8partial")
    assert frames == []
    assert rem == b"\xff\xd8partial"


def t_parse_ebur128_momentary():
    line = "[Parsed_ebur128_1 @ 0x55] t: 3   TARGET:-23 LUFS    M: -20.1 S: -22.0 ..."
    assert abs(m.parse_ebur128_momentary(line) - (-20.1)) < 1e-6
    assert m.parse_ebur128_momentary("frame= 10 fps=1.0") is None
    assert m.parse_ebur128_momentary("[Parsed_ebur128_1] M: -inf S: -inf") is None


def t_lufs_to_meter_maps_range():
    assert m.lufs_to_meter(None) == 0.0
    assert m.lufs_to_meter(-60.0) == 0.0          # at/below floor
    assert m.lufs_to_meter(-10.0) == 1.0          # at/above ceiling
    mid = m.lufs_to_meter(-35.0)                   # halfway (-60..-10)
    assert 0.49 < mid < 0.51
```

- [ ] **Step 2: Run, verify FAIL**

Run: `python3 tests/test_preview.py`
Expected: AttributeError (`split_mjpeg_frames` not defined).

- [ ] **Step 3: Implement the three functions** (in `src/relay/racecast-feeds.py`, after `preview_ffmpeg_cmd`):

```python
import re as _re  # if `re` is not already imported at module top, use the module's existing import instead

_JPEG_SOI = b"\xff\xd8"
_JPEG_EOI = b"\xff\xd9"
_EBUR128_M = _re.compile(r"\bM:\s*(-?\d+(?:\.\d+)?)")
PREVIEW_LUFS_FLOOR = -60.0
PREVIEW_LUFS_CEIL = -10.0


def split_mjpeg_frames(buf):
    """Pure: pull every COMPLETE JPEG (SOI..EOI) out of an MJPEG byte buffer.
    Returns (frames, remainder); remainder is the trailing incomplete bytes to
    prepend to the next read. Leading junk before the first SOI is discarded."""
    frames = []
    while True:
        start = buf.find(_JPEG_SOI)
        if start < 0:
            return frames, b""
        end = buf.find(_JPEG_EOI, start + 2)
        if end < 0:
            return frames, buf[start:]
        frames.append(buf[start:end + 2])
        buf = buf[end + 2:]


def parse_ebur128_momentary(line):
    """Pure: the momentary loudness (LUFS) from one ffmpeg ebur128 log line, or
    None when the line carries no finite `M:` value (e.g. '-inf' on silence)."""
    mt = _EBUR128_M.search(line)
    if not mt:
        return None
    try:
        return float(mt.group(1))
    except ValueError:
        return None


def lufs_to_meter(lufs):
    """Pure: map momentary LUFS to a 0.0..1.0 bar over [floor, ceil]. None -> 0."""
    if lufs is None:
        return 0.0
    frac = (lufs - PREVIEW_LUFS_FLOOR) / (PREVIEW_LUFS_CEIL - PREVIEW_LUFS_FLOOR)
    return max(0.0, min(1.0, frac))
```

Note: check the top of `racecast-feeds.py` — if `re` is already imported, drop the `import re as _re` line and use `re.compile`. Verify with `grep -n "^import re" src/relay/racecast-feeds.py`.

- [ ] **Step 4: Run, verify PASS**

Run: `python3 tests/test_preview.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_preview.py
git commit -m "feat(preview): pure MJPEG splitter + ebur128 level parser

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `_PreviewPullWorker` (injectable spawn, best-effort)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add the worker class after the pure helpers)
- Test: `tests/test_preview.py`

**Interfaces:**
- Consumes: `preview_pull_streamlink_cmd`, `preview_ffmpeg_cmd`, `split_mjpeg_frames`, `parse_ebur128_momentary`, `lufs_to_meter`, `resolve_hls`, `channel_url`, `platform_of`, `PREVIEW_FMT_YT`, `external_tool_env`, `_no_window_kwargs`.
- Produces: `_PreviewPullWorker(target, channel, cookies, log, spawn=None)` with `.start()`, `.stop()`, `.latest_frame()`, `.latest_level()`, `.target`, `.ok`. `spawn(self) -> (proc_or_None, video_stream, stderr_iter)` is an injectable seam; default uses real subprocesses.

The worker resolves the source, launches `streamlink … | ffmpeg`, runs two daemon threads (one draining ffmpeg stdout → `split_mjpeg_frames` → newest JPEG; one iterating ffmpeg stderr → `parse_ebur128_momentary` → level), and is fully best-effort.

- [ ] **Step 1: Write the failing test** using a fake spawn (no real processes):

```python
import threading, time


class _FakeProc:
    def __init__(self): self._alive = True
    def poll(self): return None if self._alive else 0
    def kill(self): self._alive = False
    def wait(self, timeout=None): self._alive = False


def t_preview_pull_worker_collects_frame_and_level():
    soi, eoi = b"\xff\xd8", b"\xff\xd9"
    frame = soi + b"IMG" + eoi
    proc = _FakeProc()

    def fake_spawn(worker):
        # video: one complete JPEG then EOF; stderr: one ebur128 line then EOF
        video = [frame, b""]
        def vread(n=65536):
            return video.pop(0) if video else b""
        class _V:  # minimal read() interface
            read = staticmethod(vread)
        stderr = iter(["[Parsed_ebur128_1] M: -20.0 S: -22.0\n"])
        return proc, _V(), stderr

    w = m._PreviewPullWorker("B", "https://twitch.tv/x", None,
                             _quiet_log(), spawn=fake_spawn)
    w.start()
    _wait(lambda: w.latest_frame() == frame, 2.0)
    assert w.latest_frame() == frame
    _wait(lambda: w.latest_level() > 0.0, 2.0)
    assert 0.0 < w.latest_level() <= 1.0
    w.stop()


def _quiet_log():
    import logging
    lg = logging.getLogger("test.preview"); lg.addHandler(logging.NullHandler()); return lg


def _wait(pred, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred(): return
        time.sleep(0.02)
```

- [ ] **Step 2: Run, verify FAIL**

Run: `python3 tests/test_preview.py`
Expected: AttributeError (`_PreviewPullWorker` not defined).

- [ ] **Step 3: Implement the worker** (in `src/relay/racecast-feeds.py`):

```python
class _PreviewPullWorker:
    """One decoupled low-res pull of a single (off-air) feed. Produces the latest
    JPEG still + a 0..1 audio level. Best effort: a resolve/spawn failure leaves
    .ok False and the manager shows the tile 'unavailable'; nothing here can
    affect the live feed workers. `spawn` is injectable for tests."""

    def __init__(self, target, channel, cookies, log, spawn=None):
        self.target = target
        self.channel = channel
        self.cookies = cookies
        self.log = log
        self._spawn = spawn or self._spawn_real
        self._proc = None
        self._frame = None
        self._level = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.ok = True

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def latest_frame(self):
        with self._lock:
            return self._frame

    def latest_level(self):
        with self._lock:
            return self._level

    def _spawn_real(self, _worker):
        url = channel_url(self.channel)
        plat = platform_of(url)
        if plat == "twitch":
            target, quality = url, PREVIEW_QUALITY_TW
        else:
            hls, err = resolve_hls(url, self.cookies, self.log, PREVIEW_FMT_YT)
            if not hls:
                self.log.info("preview resolve failed for %s: %s", self.target, err)
                return None, None, iter(())
            target, quality = hls, PREVIEW_QUALITY_YT
        sl_cmd = preview_pull_streamlink_cmd(target, plat, quality, cookies=self.cookies)
        ff_cmd = preview_ffmpeg_cmd()
        sl = subprocess.Popen(sl_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              env=external_tool_env(), **_no_window_kwargs())
        ff = subprocess.Popen(ff_cmd, stdin=sl.stdout, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=False,
                              env=external_tool_env(), **_no_window_kwargs())
        if sl.stdout:
            sl.stdout.close()   # ffmpeg owns the pipe now
        self._sl = sl
        stderr_iter = iter(ff.stderr.readline, b"")
        return ff, ff.stdout, _decode_lines(stderr_iter)

    def _run(self):
        try:
            proc, video, stderr_iter = self._spawn(self)
        except Exception as e:                       # noqa: BLE001 best-effort
            self.ok = False
            self.log.info("preview pull %s spawn error: %s", self.target, e)
            return
        if proc is None or video is None:
            self.ok = False
            return
        self._proc = proc
        threading.Thread(target=self._pump_levels, args=(stderr_iter,), daemon=True).start()
        buf = b""
        while not self._stop.is_set():
            chunk = video.read(65536)
            if not chunk:
                break
            frames, buf = split_mjpeg_frames(buf + chunk)
            if frames:
                with self._lock:
                    self._frame = frames[-1]
        self._kill()

    def _pump_levels(self, stderr_iter):
        for line in stderr_iter:
            if self._stop.is_set():
                break
            lufs = parse_ebur128_momentary(line)
            if lufs is not None:
                with self._lock:
                    self._level = lufs_to_meter(lufs)

    def _kill(self):
        for p in (getattr(self, "_proc", None), getattr(self, "_sl", None)):
            try:
                if p and p.poll() is None:
                    p.kill()
            except Exception:                        # noqa: BLE001
                pass

    def stop(self):
        self._stop.set()
        self._kill()


def _decode_lines(byte_iter):
    """Yield ffmpeg stderr lines as str (best effort), from a bytes line iterator."""
    for raw in byte_iter:
        yield raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else raw
```

Note: the fake `_V().read` in the test ignores its arg via `staticmethod(vread)` where `vread` accepts `n`; ensure the real loop calls `video.read(65536)` (it does).

- [ ] **Step 4: Run, verify PASS**

Run: `python3 tests/test_preview.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_preview.py
git commit -m "feat(preview): _PreviewPullWorker (latest still + audio level, best-effort)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `PreviewManager` (OBS still cache + off-air pull lifecycle + idle reaper)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add `PreviewManager` after `_PreviewPullWorker`)
- Test: `tests/test_preview.py`

**Interfaces:**
- Consumes: `preview_source`, `_PreviewPullWorker`, a relay exposing `.live_feed()`, `.pov_active()`, `.feeds` (dict), `.pov`, and `relay.feeds[key].current_channel()`/`.cookies`; an `obs_ws_get` callable returning the obs_ws module (or None).
- Produces: `PreviewManager(relay, obs_ws_get, log, obs_ttl=1.0, idle_timeout=8.0)` with `.still(target) -> (bytes|None, note)`, `.levels() -> dict`, `.run()`, `.shutdown()`.

- [ ] **Step 1: Write the failing tests** with a fake relay + fake obs + a worker-factory seam:

```python
class _FakeFeed:
    def __init__(self, ch): self._ch = ch; self.cookies = None
    def current_channel(self): return (self._ch, 0)


class _FakeRelay:
    def __init__(self, live="A", pov=None):
        self.feeds = {"A": _FakeFeed("https://twitch.tv/a"),
                      "B": _FakeFeed("https://twitch.tv/b")}
        self._live = live; self.pov = pov
    def live_feed(self): return self._live
    def pov_active(self): return bool(self.pov)


class _FakeObs:
    def get_source_screenshot(self, name, width=480):
        return (b"\xff\xd8OBS" + name.encode() + b"\xff\xd9", "")


def t_manager_onair_returns_obs_screenshot():
    mgr = m.PreviewManager(_FakeRelay(live="A"), lambda: _FakeObs(), _quiet_log())
    data, note = mgr.still("A")
    assert data == b"\xff\xd8OBSFeed A\xff\xd9" and note == ""


def t_manager_obs_cache_reuses_within_ttl():
    calls = {"n": 0}
    class _CountObs:
        def get_source_screenshot(self, name, width=480):
            calls["n"] += 1; return (b"\xff\xd8x\xff\xd9", "")
    mgr = m.PreviewManager(_FakeRelay(live="A"), lambda: _CountObs(), _quiet_log(), obs_ttl=60.0)
    mgr.still("A"); mgr.still("A")
    assert calls["n"] == 1          # second call served from cache


def t_manager_offair_starts_pull_and_levels():
    started = {}
    def fake_factory(target, channel, cookies, log):
        class _W:
            def __init__(s): s.target = target; s.ok = True
            def start(s): started["t"] = target; return s
            def stop(s): started["stopped"] = True
            def latest_frame(s): return b"\xff\xd8P\xff\xd9"
            def latest_level(s): return 0.7
        return _W().start()
    mgr = m.PreviewManager(_FakeRelay(live="A"), lambda: _FakeObs(), _quiet_log(),
                           worker_factory=fake_factory)
    data, note = mgr.still("B")     # B is off-air
    assert data == b"\xff\xd8P\xff\xd9"
    assert started["t"] == "B"
    assert mgr.levels() == {"B": 0.7}


def t_manager_placeholder_when_pov_off():
    mgr = m.PreviewManager(_FakeRelay(live="A", pov=None), lambda: _FakeObs(), _quiet_log())
    data, note = mgr.still("POV")
    assert data is None and note == "pov off"
```

- [ ] **Step 2: Run, verify FAIL**

Run: `python3 tests/test_preview.py`
Expected: AttributeError (`PreviewManager` not defined).

- [ ] **Step 3: Implement `PreviewManager`**:

```python
class PreviewManager:
    """Director Panel preview source-of-truth. Active tiles (on-air feed / active
    POV) are served from a short-TTL OBS-screenshot cache; the single off-air feed
    is served from one reference-counted _PreviewPullWorker. All directors poll
    this shared state, so cost is flat in viewer count. Best effort throughout."""

    def __init__(self, relay, obs_ws_get, log, obs_ttl=1.0, idle_timeout=8.0,
                 worker_factory=None):
        self.relay = relay
        self._obs_get = obs_ws_get
        self.log = log
        self.obs_ttl = obs_ttl
        self.idle_timeout = idle_timeout
        self._factory = worker_factory or (
            lambda target, channel, cookies, log: _PreviewPullWorker(
                target, channel, cookies, log).start())
        self._obs_cache = {}              # source_name -> (monotonic_ts, jpeg)
        self._pull = None                 # current _PreviewPullWorker or None
        self._last_touch = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def _feed_keys(self):
        keys = set(self.relay.feeds)
        if self.relay.pov:
            keys.add("POV")
        return keys

    def still(self, target):
        target = target.upper()
        kind, ref = preview_source(target, self.relay.live_feed(),
                                   self.relay.pov_active(), self._feed_keys())
        if kind == "placeholder":
            return None, ref
        if kind == "obs":
            return self._obs_still(ref)
        return self._pull_still(target)    # kind == "pull"

    def _obs_still(self, source_name):
        now = time.monotonic()
        hit = self._obs_cache.get(source_name)
        if hit and now - hit[0] < self.obs_ttl:
            return hit[1], ""
        obs = self._obs_get()
        if obs is None:
            return None, "obs unavailable"
        data, note = obs.get_source_screenshot(source_name, width=PREVIEW_STILL_WIDTH)
        if data is None:
            return None, note
        self._obs_cache[source_name] = (now, data)
        return data, ""

    def _pull_still(self, target):
        with self._lock:
            self._last_touch = time.monotonic()
            if self._pull is None or self._pull.target != target:
                if self._pull is not None:
                    self._pull.stop()
                ch, _ = self.relay.feeds[target].current_channel()
                if not ch:
                    self._pull = None
                    return None, "feed off"
                self._pull = self._factory(
                    target, ch, self.relay.feeds[target].cookies, self.log)
            worker = self._pull
        frame = worker.latest_frame()
        if frame is None:
            return None, ("unavailable" if not worker.ok else "starting")
        return frame, ""

    def levels(self):
        with self._lock:
            w = self._pull
        if w is None:
            return {}
        return {w.target: w.latest_level()}

    def run(self):
        """Idle reaper: stop the off-air pull when no one has polled it recently."""
        while not self._stop.wait(2.0):
            with self._lock:
                if (self._pull is not None
                        and time.monotonic() - self._last_touch > self.idle_timeout):
                    self._pull.stop()
                    self._pull = None

    def shutdown(self):
        self._stop.set()
        with self._lock:
            if self._pull is not None:
                self._pull.stop()
                self._pull = None
```

- [ ] **Step 4: Run, verify PASS**

Run: `python3 tests/test_preview.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_preview.py
git commit -m "feat(preview): PreviewManager — OBS still cache + off-air pull lifecycle + idle reaper

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Wire endpoints (`/preview/feed/*` rework + `/preview/levels`) and the manager into the relay

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `make_handler` signature (~4114), the `/preview/feed` block (~4992-5016), add `/preview/levels`, and `main` wiring (~5928-5946).
- Test: `tests/test_preview.py` (endpoint round-trip via `m.make_handler` + a temp HTTP server).

**Interfaces:**
- Consumes: `PreviewManager`, the module global `_obs_ws`.
- Produces: `make_handler(..., preview_manager=None)`; endpoints `GET /preview/feed/{A|B|POV}` (JPEG or 503) and `GET /preview/levels` (JSON).

- [ ] **Step 1: Write the failing endpoint test** in `tests/test_preview.py`:

```python
import json, urllib.request, urllib.error


def _serve_with_manager(mgr):
    relay = mgr.relay
    srv = m.ThreadingHTTPServer(("127.0.0.1", 0),
                                m.make_handler(relay, preview_manager=mgr))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def t_endpoint_preview_levels_json():
    # off-air pull via fake factory returns level 0.5
    def fake_factory(target, channel, cookies, log):
        class _W:
            target = "B"; ok = True
            def latest_frame(self): return b"\xff\xd8P\xff\xd9"
            def latest_level(self): return 0.5
        return _W()
    relay = _make_min_relay_for_preview()        # see note below
    mgr = m.PreviewManager(relay, lambda: None, _quiet_log(), worker_factory=fake_factory)
    mgr.still("B")                                # start the off-air pull
    srv = _serve_with_manager(mgr)
    port = srv.server_address[1]
    body = urllib.request.urlopen("http://127.0.0.1:%d/preview/levels" % port, timeout=3).read()
    assert json.loads(body) == {"B": 0.5}
    srv.shutdown()
```

`_make_min_relay_for_preview()` should build a real `m.Relay` the same way `tests/test_pov.py::_make_min_relay` does (reuse that helper's construction — import-load `test_pov` or copy its minimal builder). Keep it minimal: two feeds A/B from `_URLS8`, live = "A". If reuse is awkward, the `_FakeRelay` from Task 5 plus `make_handler` works too, because the endpoint only calls `preview_manager.levels()`/`.still()` — confirm `make_handler` does not dereference other relay methods on this path.

- [ ] **Step 2: Run, verify FAIL**

Run: `python3 tests/test_preview.py`
Expected: FAIL — `make_handler` has no `preview_manager` param / `/preview/levels` 404s.

- [ ] **Step 3a: Add the param** to `make_handler` (line ~4114): add `preview_manager=None` to the signature.

- [ ] **Step 3b: Replace the `/preview/feed` block** (~4992-5016) with:

```python
                if len(p) == 3 and p[:2] == ["preview", "feed"]:
                    target = p[2].upper()
                    if target not in PREVIEW_FEEDS:
                        return self._send({"error": "unknown feed", "feed": p[2]}, 404)
                    if preview_manager is None:
                        return self._send({"error": "preview disabled"}, 404)
                    data, note = preview_manager.still(target)
                    if data is None:
                        return self._send({"error": "preview unavailable",
                                           "note": note}, 503)
                    return self._send_jpeg(data)
                if p == ["preview", "levels"]:
                    if preview_manager is None:
                        return self._send({"error": "preview disabled"}, 404)
                    return self._send(preview_manager.levels())
```

- [ ] **Step 3c: Wire the manager in `main`** — near the BroadcastChatSupervisor start (~5928) add:

```python
    preview_manager = PreviewManager(relay, lambda: _obs_ws, relay_logger)
    threading.Thread(target=preview_manager.run, daemon=True).start()
```

Use the same logger the surrounding relay code uses (grep nearby for the logger variable name, e.g. `logger`/`relay_logger`). Then pass it into the `make_handler(...)` call (~5946): add `preview_manager=preview_manager`.

- [ ] **Step 4: Run, verify PASS**

Run: `python3 tests/test_preview.py` then `python3 tests/test_pov.py`
Expected: `ALL PASS` for both.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_preview.py
git commit -m "feat(preview): relay endpoints for cached stills + audio levels, manager wired in

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Expose `/console/preview/*` over Funnel (any authenticated subject)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`_console_gate`, near the broadcast-chat any-auth block ~4648)
- Test: `tests/test_cockpit.py` (the file that already exercises `/console` auth) — add an any-auth GET check; if its harness is heavy, add the check to `tests/test_preview.py` against a relay started with a console secret.

**Interfaces:**
- Consumes: `_console_gate`'s `sub` (segments after `console`), `subject` (already authenticated above this point).
- Produces: `/console/preview/feed/{X}` and `/console/preview/levels` fall through to the root `/preview/*` handlers for any authenticated subject.

- [ ] **Step 1: Write the failing test.** Mirror an existing `/console` any-auth test in `tests/test_cockpit.py` (search it for `broadcast-chat` or `whoami`), minting a token via the same helper used there, then asserting `GET /console/preview/levels` returns 200 JSON (not 401/404) and that an unauthenticated request is denied. Reuse that file's token-mint + relay-start fixtures verbatim.

- [ ] **Step 2: Run, verify FAIL**

Run: `python3 tests/test_cockpit.py`
Expected: the new assertion FAILS (route falls through to a 404/forbidden).

- [ ] **Step 3: Add the rewrite** in `_console_gate`, immediately after the broadcast-chat block (~4657), before the role-gated `buttons`/`logo` blocks:

```python
            # Read-only Director-Panel preview mirror: any authenticated /console
            # subject may poll the cached stills + audio levels. Funnelled under the
            # existing /console mount — no new public surface; the data is a low-res
            # still of already-public platform video, never persisted.
            if method == "GET" and (sub == ["preview", "levels"]
                    or (len(sub) == 3 and sub[:2] == ["preview", "feed"])):
                return sub      # -> root /preview/... handler in do_GET
```

- [ ] **Step 4: Run, verify PASS**

Run: `python3 tests/test_cockpit.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_cockpit.py
git commit -m "feat(preview): expose /console/preview/* (any-auth) over Funnel

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Remove the dead loopback grab

**Files:**
- Modify: `src/relay/racecast-feeds.py` (delete `feed_grab_cmd` ~2175-2182 and `grab_feed_frame`)
- Modify: `tests/test_pov.py` (delete `t_feed_grab_cmd_pinned`, ~95-101)

**Interfaces:** none produced; removes `feed_grab_cmd` / `grab_feed_frame`.

- [ ] **Step 1: Confirm no remaining callers**

Run: `grep -rnE "feed_grab_cmd|grab_feed_frame" src/ tests/`
Expected: only the definitions + `t_feed_grab_cmd_pinned` (the endpoint caller was replaced in Task 6).

- [ ] **Step 2: Delete** `feed_grab_cmd` and `grab_feed_frame` from `src/relay/racecast-feeds.py`, and `t_feed_grab_cmd_pinned` from `tests/test_pov.py`.

- [ ] **Step 3: Run the suites**

Run: `python3 tests/test_pov.py && python3 tests/test_preview.py`
Expected: `ALL PASS` for both (no `NameError`).

- [ ] **Step 4: Lint**

Run: `python3 tools/lint.py`
Expected: clean (no unused-import/name warnings from the removal).

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "refactor(preview): drop the dead single-consumer loopback grab

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Frontend — auto-polling still tiles + audio bar + per-tile play/pause

**Files:**
- Modify: `src/director/director-panel.html` (preview section markup ~412-439, CSS ~358-371, JS ~1794-1840)

**Interfaces:**
- Consumes: `RC_API("/preview/feed/<X>")`, `RC_API("/preview/levels")`, the existing `pvMarkOnAir(feed)` knowledge of the on-air feed.

- [ ] **Step 1: Markup** — give each `.pvtile` an audio bar element and a play/pause control; keep the program tile as-is:

```html
<!-- inside each feed .pvtile, after the .pvframe -->
<div class="pvbar"><span class="pvbarfill"></span></div>
<button class="k pvtoggle" data-feed="A">PAUSE</button>
```

(Repeat for B and POV; the ↻ refresh button is removed — tiles auto-poll.)

- [ ] **Step 2: CSS** — add to the `<style>` block:

```css
.pvbar{height:6px;background:#1a1f27;border-radius:3px;margin-top:4px;overflow:hidden}
.pvbarfill{display:block;height:100%;width:0;background:#4ade80;transition:width .2s}
.pvtile.paused .pvframe{opacity:.4}
.pvtile.onair .pvbar{display:none}   /* on-air is audible in program: no meter */
```

- [ ] **Step 3: JS** — replace the click-grab logic (~1818-1833) with per-tile polling and a shared levels poll:

```javascript
const PV_FEED_MS = 1000;
const pvFeedTimers = {};   // feed -> interval id
let pvLevelTimer = null;

function pvPollFeed(tile){
  const feed = tile.dataset.feed, frame = tile.querySelector(".pvframe"),
        img = frame.querySelector("img"), ph = frame.querySelector(".pvph"),
        txt = ph.querySelector(".pvphtxt");
  const probe = new Image();
  probe.onload = () => { img.src = probe.src; frame.classList.add("loaded");
                         ph.classList.remove("err"); };
  probe.onerror = () => { frame.classList.remove("loaded");
                          ph.classList.add("err"); txt.textContent = "Unavailable"; };
  probe.src = RC_API("/preview/feed/" + feed) + "?ts=" + Date.now();
}

function pvStartFeed(tile){
  const feed = tile.dataset.feed;
  if(pvFeedTimers[feed]) return;
  tile.classList.remove("paused");
  pvPollFeed(tile);
  pvFeedTimers[feed] = setInterval(() => pvPollFeed(tile), PV_FEED_MS);
}
function pvStopFeed(tile){
  const feed = tile.dataset.feed;
  if(pvFeedTimers[feed]){ clearInterval(pvFeedTimers[feed]); delete pvFeedTimers[feed]; }
  tile.classList.add("paused");
}
function pvPollLevels(){
  fetch(RC_API("/preview/levels")).then(r => r.ok ? r.json() : {}).then(map => {
    document.querySelectorAll(".pvtile").forEach(t => {
      const fill = t.querySelector(".pvbarfill");
      if(fill) fill.style.width = Math.round(100 * (map[t.dataset.feed] || 0)) + "%";
    });
  }).catch(() => {});
}

document.querySelectorAll(".pvtile .pvtoggle").forEach(btn => {
  btn.onclick = () => {
    const tile = btn.closest(".pvtile");
    if(pvFeedTimers[tile.dataset.feed]){ pvStopFeed(tile); btn.textContent = "PLAY"; }
    else { pvStartFeed(tile); btn.textContent = "PAUSE"; }
  };
});
```

Then, in `pvStart()` (the SHOW handler ~1805) also start each feed tile + the levels poll, and in `pvStop()` clear them:

```javascript
// in pvStart(), after the program poll is set up:
document.querySelectorAll(".pvtile").forEach(pvStartFeed);
pvLevelTimer = setInterval(pvPollLevels, PV_FEED_MS); pvPollLevels();
// in pvStop(): clear all feed timers + the level timer
document.querySelectorAll(".pvtile").forEach(pvStopFeed);
if(pvLevelTimer){ clearInterval(pvLevelTimer); pvLevelTimer = null; }
```

- [ ] **Step 4: Manual smoke test** with a running dev build (the `racecast-local-uat` skill): open `/panel`, SHOW the preview, confirm the off-air tile auto-updates and its green audio bar moves when the upcoming commentator speaks, the on-air tile shows no bar, and PAUSE/PLAY toggles a tile without collapsing the section.

- [ ] **Step 5: Commit**

```bash
git add src/director/director-panel.html
git commit -m "feat(preview): auto-polling still tiles with audio meter + per-tile play/pause

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Refresh the Director Panel wiki screenshot + run the full suite

**Files:**
- Regenerate: `src/docs/wiki/images/director-panel.png`
- Verify: full test suite + lint.

- [ ] **Step 1: Regenerate the screenshot** via the `wiki-screenshots` skill (demo profile + `tools/obs-sim.py` OBS stand-in), capturing the Director Panel with the preview section open so the new still tiles + audio bars are visible. Save to `src/docs/wiki/images/director-panel.png`.

- [ ] **Step 2: Run the full suite + lint**

Run: `python3 tools/lint.py && python3 tools/run-tests.py`
Expected: lint clean; `ALL PASS` across the suite.

- [ ] **Step 3: Build self-verify** (the closest thing to CI)

Run: `python3 tools/build.py`
Expected: build + verify succeed (no shell scripts, no secrets, preflight present).

- [ ] **Step 4: Commit**

```bash
git add src/docs/wiki/images/director-panel.png
git commit -m "docs(preview): refresh Director Panel wiki screenshot for the live-preview redesign

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Off-air "Unavailable" root cause → Task 1 (selector → pull) + Task 4/5 (decoupled pull). ✓
- Per-second auto stills → Task 9 (polling) + Task 5 (cache). ✓
- Audio meter on off-air feed → Task 3 (parser) + Task 4 (level) + Task 6 (`/preview/levels`) + Task 9 (bar). ✓
- On-air/POV from OBS, no pull → Task 1 + Task 5 (`_obs_still` cache). ✓
- 360p source, never 1080p; Twitch no bot-check, YouTube one isolated resolve → Task 2 + Task 4 (`_spawn_real`). ✓
- Multi-director-safe (shared pull + cache, flat egress) → Task 5 (single `_pull`, TTL cache) + Task 6. ✓
- Funnel under `/console`, any-auth, no new surface → Task 7. ✓
- Best-effort, never affects live feed → Task 4/5 try/except + injectable seams. ✓
- Per-tile play/pause; remove confusing ↻ → Task 9. ✓
- Remove dead loopback grab → Task 8. ✓
- Wiki screenshot in the same change → Task 10. ✓
- Fan-out / stale glitch deferred → issue #358 (not in this plan). ✓

**Placeholder scan:** every code step carries real code; no TBD/TODO. The two seams that say "reuse the existing helper" (Task 6 logger name, Task 7 token-mint fixture) point at concrete existing code the implementer greps for — acceptable, not placeholders.

**Type consistency:** `still() -> (bytes|None, note)`, `levels() -> {feed: float}`, `_PreviewPullWorker.target/.ok/.latest_frame()/.latest_level()`, `preview_source(...) -> (kind, ref)` are used identically across Tasks 4–9. `make_handler(..., preview_manager=None)` matches the call site in Task 6. `PREVIEW_*` constant names match between Task 2 and Task 4.
