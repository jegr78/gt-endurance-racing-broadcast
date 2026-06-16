# Live Preview in the Director Panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the remote director an on-demand multiview inside `/panel` — a live OBS program-output tile plus a click-to-grab still per feed (A / B / POV).

**Architecture:** The relay (already on the tailnet, already an obs-websocket client, already serving `/panel`) brokers every frame. Program + on-air feed come from obs-websocket `GetSourceScreenshot`; the off-air feed comes from a one-frame `ffmpeg` grab off the feed's own loopback port. Per-tile routing is a pure function. The panel section is collapsible, hidden by default, and does work only while shown.

**Tech Stack:** Pure Python 3 stdlib (relay + `obs_ws.py`), `ffmpeg` (already a runtime dep), vanilla JS/HTML in `director-panel.html`. Tests are stdlib runnable scripts (no pytest).

**Spec:** `docs/superpowers/specs/2026-06-16-live-preview-design.md`
**Branch:** `feat/live-preview` (spec already committed there)

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `src/scripts/obs_ws.py` | obs-websocket client | **Modify** — add `screenshot_request_data`, `parse_screenshot_data_uri`, `get_source_screenshot`, `get_program_screenshot` |
| `tests/test_obsws.py` | obs_ws unit checks | **Modify** — pure-helper tests + fake-OBS-server screenshot tests; extend `_fake_obs_server` |
| `src/relay/racecast-feeds.py` | the relay | **Modify** — `PREVIEW_FEEDS`, pure `preview_source`, `feed_grab_cmd`, `grab_feed_frame`, `_send_jpeg`, two `do_GET` routes |
| `tests/test_pov.py` | relay unit checks | **Modify** — router + cmd pinning + live-server endpoint tests |
| `src/director/director-panel.html` | director panel UI | **Modify** — collapsible Live Preview section + JS |
| `src/docs/wiki/images/director-panel.png` | wiki screenshot | **Replace** — recapture with the Live Preview section expanded |

All `obs_ws` additions keep the module's best-effort contract (never raise; return `(value, "")` or `(None, note)`). All relay additions are read-only and must never disturb feeds/OBS.

---

## Task 1: obs_ws pure helpers (request shape + data-URI decode)

**Files:**
- Modify: `src/scripts/obs_ws.py`
- Test: `tests/test_obsws.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_obsws.py` (after the existing pure-helper tests, before the fake-server section):

```python
# --------------------------------------------------------------------------
# Screenshot request shape + data-URI decode (pure)
# --------------------------------------------------------------------------
def t_screenshot_request_data_shape():
    d = m.screenshot_request_data("Feed A", width=480, fmt="jpg", quality=55)
    assert d == {"sourceName": "Feed A", "imageFormat": "jpg",
                 "imageWidth": 480, "imageCompressionQuality": 55}


def t_parse_screenshot_data_uri_valid():
    raw = b"\xff\xd8\xff\xd9"
    uri = "data:image/jpg;base64," + base64.b64encode(raw).decode()
    assert m.parse_screenshot_data_uri(uri) == raw


def t_parse_screenshot_data_uri_rejects_garbage():
    assert m.parse_screenshot_data_uri("not a data uri") is None
    assert m.parse_screenshot_data_uri("data:image/jpg;base64,@@@@") is None
    assert m.parse_screenshot_data_uri(None) is None
    assert m.parse_screenshot_data_uri(12345) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_obsws.py`
Expected: FAIL with `AttributeError: module 'obs_ws' has no attribute 'screenshot_request_data'`.

- [ ] **Step 3: Implement the helpers**

In `src/scripts/obs_ws.py`, add after the protocol helpers section (after `feed_input_names` / `browser_input_names`, before the password-discovery section):

```python
# --------------------------------------------------------------------------
# Source screenshots (GetSourceScreenshot) — pure helpers, unit-tested
# --------------------------------------------------------------------------
def screenshot_request_data(source_name, width=640, fmt="jpg", quality=60):
    """requestData for GetSourceScreenshot: a scaled still of a source/scene."""
    return {"sourceName": source_name, "imageFormat": fmt,
            "imageWidth": int(width), "imageCompressionQuality": int(quality)}


def parse_screenshot_data_uri(data_uri):
    """Decode a GetSourceScreenshot 'imageData' value
    (data:image/<fmt>;base64,<payload>) to raw bytes; None on a malformed URI."""
    if not isinstance(data_uri, str):
        return None
    head, sep, payload = data_uri.partition(",")
    if not sep or not head.startswith("data:") or "base64" not in head:
        return None
    try:
        return base64.b64decode(payload, validate=True)   # binascii.Error subclasses ValueError
    except ValueError:
        return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_obsws.py`
Expected: `ok t_screenshot_request_data_shape`, `ok t_parse_screenshot_data_uri_valid`, `ok t_parse_screenshot_data_uri_rejects_garbage`, … `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): screenshot request shape + data-URI decode helpers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: obs_ws screenshot fetchers (source + program scene)

**Files:**
- Modify: `src/scripts/obs_ws.py`
- Test: `tests/test_obsws.py` (extend `_fake_obs_server`, add fetcher tests)

- [ ] **Step 1: Extend the fake OBS server**

In `tests/test_obsws.py`, inside `_fake_obs_server`'s request loop, add these two branches alongside the existing `elif rtype == …` branches (e.g. right after the `GetInputList` branch):

```python
        elif rtype == "GetCurrentProgramScene":
            resp = {"currentProgramSceneName": state.get("program_scene", "Stint"),
                    "sceneName": state.get("program_scene", "Stint")}
        elif rtype == "GetSourceScreenshot":
            state.setdefault("shot_requests", []).append(rdata)
            raw = state.get("shot_bytes", b"\xff\xd8\xff\xd9")
            resp = {"imageData": "data:image/jpg;base64," + base64.b64encode(raw).decode()}
```

(These are additive — existing tests pass a `state` dict and never set these keys, so defaults apply.)

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_obsws.py` in the fake-server section (after `t_release_feed_inputs_*`):

```python
def t_get_source_screenshot_returns_bytes():
    state = {"shot_bytes": b"\xff\xd8hello\xff\xd9"}
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    port = srv.getsockname()[1]
    threading.Thread(target=_fake_obs_server, args=(srv, "pw", state), daemon=True).start()
    data, note = m.get_source_screenshot("Feed A", width=320, host="127.0.0.1",
                                         port=port, password="pw", timeout=5)
    srv.close()
    assert note == "" and data == b"\xff\xd8hello\xff\xd9"
    assert state["shot_requests"][0]["sourceName"] == "Feed A"
    assert state["shot_requests"][0]["imageWidth"] == 320


def t_get_program_screenshot_uses_current_scene():
    state = {"program_scene": "Stint", "shot_bytes": b"\xff\xd8PGM\xff\xd9"}
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    port = srv.getsockname()[1]
    threading.Thread(target=_fake_obs_server, args=(srv, "pw", state), daemon=True).start()
    data, note = m.get_program_screenshot(width=640, host="127.0.0.1",
                                          port=port, password="pw", timeout=5)
    srv.close()
    assert note == "" and data == b"\xff\xd8PGM\xff\xd9"
    assert state["shot_requests"][0]["sourceName"] == "Stint"


def t_get_source_screenshot_unreachable_is_quiet():
    sock = socket.socket(); sock.bind(("127.0.0.1", 0))
    free = sock.getsockname()[1]; sock.close()
    data, note = m.get_source_screenshot("Feed A", port=free, password="x", timeout=0.5)
    assert data is None and note
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 tests/test_obsws.py`
Expected: FAIL with `AttributeError: module 'obs_ws' has no attribute 'get_source_screenshot'`.

- [ ] **Step 4: Implement the fetchers**

In `src/scripts/obs_ws.py`, add to the request/response client section (after `refresh_browser_inputs`, before `reflect_feed_state`):

```python
def get_source_screenshot(source_name, width=640, fmt="jpg", quality=60,
                          host="127.0.0.1", port=None, password=None, timeout=2.0):
    """A scaled screenshot of an OBS source/scene as raw JPEG bytes.
    Returns (bytes, "") or (None, note). Best effort — never raises (same
    contract as release_feed_inputs/get_scene_collection)."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return None, note
    try:
        resp = session.request(
            "GetSourceScreenshot",
            screenshot_request_data(source_name, width, fmt, quality))
        data = parse_screenshot_data_uri(resp.get("imageData"))
        if data is None:
            return None, "OBS returned no image data"
        return data, ""
    except Exception as exc:                          # noqa: BLE001 — best-effort contract
        return None, str(exc) or exc.__class__.__name__
    finally:
        session.close()


def get_program_screenshot(width=640, fmt="jpg", quality=60,
                           host="127.0.0.1", port=None, password=None, timeout=2.0):
    """Screenshot the current OBS program scene (what viewers see) as raw JPEG
    bytes. Resolves the active scene name, then screenshots it on the same
    session. Returns (bytes, "") or (None, note). Best effort — never raises."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return None, note
    try:
        cur = session.request("GetCurrentProgramScene", {})
        scene = cur.get("currentProgramSceneName") or cur.get("sceneName")
        if not scene:
            return None, "OBS returned no program scene"
        resp = session.request(
            "GetSourceScreenshot",
            screenshot_request_data(scene, width, fmt, quality))
        data = parse_screenshot_data_uri(resp.get("imageData"))
        if data is None:
            return None, "OBS returned no image data"
        return data, ""
    except Exception as exc:                          # noqa: BLE001 — best-effort contract
        return None, str(exc) or exc.__class__.__name__
    finally:
        session.close()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 tests/test_obsws.py`
Expected: `ok t_get_source_screenshot_returns_bytes`, `ok t_get_program_screenshot_uses_current_scene`, `ok t_get_source_screenshot_unreachable_is_quiet`, … `ALL PASS`.

- [ ] **Step 6: Lint + commit**

Run: `python3 tools/lint.py` → Expected: no errors.

```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): GetSourceScreenshot fetchers for source + program scene

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: relay pure routing + ffmpeg grab command

**Files:**
- Modify: `src/relay/racecast-feeds.py`
- Test: `tests/test_pov.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pov.py` (after `t_pov_format_constant`):

```python
def t_preview_source_onair_uses_obs():
    ports = {"A": 53001, "B": 53002}
    assert m.preview_source("A", "A", False, ports) == ("obs", "Feed A")
    assert m.preview_source("B", "B", False, ports) == ("obs", "Feed B")


def t_preview_source_offair_grabs_port():
    ports = {"A": 53001, "B": 53002}
    assert m.preview_source("B", "A", False, ports) == ("grab", 53002)
    assert m.preview_source("A", "B", False, ports) == ("grab", 53001)


def t_preview_source_pov_active_vs_paused():
    ports = {"A": 53001, "B": 53002, "POV": 53003}
    assert m.preview_source("POV", "A", True, ports) == ("obs", "Feed POV")
    assert m.preview_source("POV", "A", False, ports) == ("placeholder", "pov off")


def t_preview_source_missing_port_is_placeholder():
    assert m.preview_source("B", "A", False, {"A": 53001}) == ("placeholder", "feed off")


def t_preview_source_unknown_target_is_placeholder():
    assert m.preview_source("X", "A", False, {"A": 53001}) == ("placeholder", "unknown feed")


def t_feed_grab_cmd_pinned():
    assert m.feed_grab_cmd(53002, 480) == [
        "ffmpeg", "-nostdin", "-loglevel", "error",
        "-i", "http://127.0.0.1:53002",
        "-frames:v", "1", "-vf", "scale=480:-2",
        "-f", "mjpeg", "pipe:1"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_pov.py`
Expected: FAIL with `AttributeError: module 'irofeeds' has no attribute 'preview_source'`.

- [ ] **Step 3: Implement the pure helpers**

In `src/relay/racecast-feeds.py`, add near the other pure relay helpers (e.g. just after `streamlink_serve_cmd`, which is around line 1171). The feed-source names mirror `obs_ws.FEED_SOURCES` / `obs_ws.POV_SOURCE` (kept literal so this stays pure and independent of whether `_obs_ws` imported):

```python
PREVIEW_FEEDS = ("A", "B", "POV")        # tiles the Director Panel can request


def preview_source(target, live, pov_active, feed_ports):
    """Pure: how to source a feed preview tile.

    target      'A' | 'B' | 'POV'
    live        the on-air feed ('A' | 'B') from Relay.live_feed()
    pov_active  Relay.pov_active()
    feed_ports  {'A': 53001, 'B': 53002, 'POV': 53003}

    Returns ('obs', source_name) | ('grab', port) | ('placeholder', reason).
    The on-air feed and the active POV are decoding in OBS, so screenshot the
    source directly; an off-air feed is not decoding (and its port is free of
    OBS), so grab one frame from its loopback port; a paused POV / absent port
    has nothing to show."""
    if target == "POV":
        return ("obs", "Feed POV") if pov_active else ("placeholder", "pov off")
    if target in ("A", "B"):
        if target == live:
            return ("obs", "Feed " + target)
        port = feed_ports.get(target)
        return ("grab", port) if port else ("placeholder", "feed off")
    return ("placeholder", "unknown feed")


def feed_grab_cmd(port, width=480):
    """ffmpeg: grab ONE frame from a feed's loopback HTTP server and emit a
    scaled JPEG on stdout. Pinned byte-for-byte by tests/test_pov.py."""
    return ["ffmpeg", "-nostdin", "-loglevel", "error",
            "-i", "http://127.0.0.1:%d" % port,
            "-frames:v", "1", "-vf", "scale=%d:-2" % width,
            "-f", "mjpeg", "pipe:1"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_pov.py`
Expected: the six new `ok t_preview_*` / `ok t_feed_grab_cmd_pinned` lines, then `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): pure preview routing + ffmpeg frame-grab command

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: relay grab runner + `/preview` endpoints

**Files:**
- Modify: `src/relay/racecast-feeds.py`
- Test: `tests/test_pov.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pov.py`. First add the imports + shared fixtures at the top of the test functions area (only if not already present — `t_set_stint_endpoint_http` shows the same pattern lives in `test_stint.py`, but `test_pov.py` needs its own copy):

```python
import json, threading, urllib.request, urllib.error


class _FakeSource:
    def __init__(self, items): self.items = list(items)
    def get(self): return self.items
    def refresh(self, timeout=None): pass
    def health(self): return {"ok": True}


_URLS8 = [f"https://www.youtube.com/watch?v=stint{i}" for i in range(1, 9)]


def _serve(relay):
    srv = m.ThreadingHTTPServer(("127.0.0.1", 0), m.make_handler(relay))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
```

Then the endpoint tests:

```python
def t_preview_program_endpoint_serves_jpeg():
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], HERE)

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
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], HERE)
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


def t_preview_feed_onair_uses_obs_not_grab():
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], HERE)   # A on air (idx 0)

    class FakeObs:
        def get_source_screenshot(self, name, **kw):
            self.name = name; return (b"\xff\xd8ONAIR\xff\xd9", "")

    fo = FakeObs(); old = m._obs_ws; m._obs_ws = fo
    old_grab = m.grab_feed_frame
    def _boom(*a, **k): raise AssertionError("grab used for on-air feed")
    m.grab_feed_frame = _boom; srv = _serve(r)
    try:
        port = srv.server_address[1]
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/preview/feed/A", timeout=5).read()
        assert body == b"\xff\xd8ONAIR\xff\xd9" and fo.name == "Feed A"
    finally:
        srv.shutdown(); m._obs_ws = old; m.grab_feed_frame = old_grab


def t_preview_feed_offair_uses_grab_not_obs():
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], HERE)   # B off air (idx 1)
    calls = {}
    def fake_grab(port, width=480, timeout=8.0):
        calls["port"] = port; calls["width"] = width; return b"\xff\xd8GRB\xff\xd9"

    class FakeObs:
        def get_source_screenshot(self, *a, **k): raise AssertionError("obs used for off-air grab")

    old = m._obs_ws; m._obs_ws = FakeObs()
    old_grab = m.grab_feed_frame; m.grab_feed_frame = fake_grab; srv = _serve(r)
    try:
        port = srv.server_address[1]
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/preview/feed/B", timeout=5).read()
        assert body == b"\xff\xd8GRB\xff\xd9"
        assert calls["port"] == 53002 and calls["width"] == 480
    finally:
        srv.shutdown(); m._obs_ws = old; m.grab_feed_frame = old_grab


def t_preview_feed_pov_paused_is_503():
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], HERE)   # no POV configured
    srv = _serve(r)
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
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], HERE)
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
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], HERE)   # B off air
    class FakeObs:
        def get_source_screenshot(self, *a, **k): return (None, "x")
    old = m._obs_ws; m._obs_ws = FakeObs()
    old_grab = m.grab_feed_frame; m.grab_feed_frame = lambda *a, **k: None; srv = _serve(r)
    try:
        port = srv.server_address[1]
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/preview/feed/B", timeout=5)
            raise AssertionError("expected HTTP 503")
        except urllib.error.HTTPError as e:
            assert e.code == 503
    finally:
        srv.shutdown(); m._obs_ws = old; m.grab_feed_frame = old_grab
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_pov.py`
Expected: FAIL — the `/preview/program` request returns the relay's 404 JSON (`{"error":"unknown",…}`), so `urlopen` raises `HTTPError 404` before any assert, or `grab_feed_frame` is missing (`AttributeError`).

- [ ] **Step 3: Implement the grab runner**

In `src/relay/racecast-feeds.py`, add right after `feed_grab_cmd` (from Task 3). It reuses `external_tool_env` (imported at module top, line ~88) and `_no_window_kwargs` (existing):

```python
def grab_feed_frame(port, width=480, timeout=8.0):
    """Run feed_grab_cmd and return the JPEG bytes, or None on any failure /
    timeout. Best effort — never raises; the grab subprocess is killed on
    timeout so a stuck upstream can't hang a relay worker thread."""
    try:
        proc = subprocess.run(
            feed_grab_cmd(port, width),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=timeout, env=external_tool_env(),
            **_no_window_kwargs(os.name))
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout
```

- [ ] **Step 4: Add the `_send_jpeg` handler method**

In `make_handler`'s `class H`, add after `_send_css` (around line 2336):

```python
        def _send_jpeg(self, body):
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)
            return None
```

- [ ] **Step 5: Wire the two routes into `do_GET`**

In `do_GET`, add these blocks just before the `splitscreen` block (after the `["hud","preview","frame"]` / `["hud","assets",…]` group, around line 2399):

```python
                if p == ["preview", "program"]:
                    if _obs_ws is None:
                        return self._send({"error": "obs unavailable"}, 503)
                    data, note = _obs_ws.get_program_screenshot(width=640)
                    if data is None:
                        return self._send({"error": "preview unavailable",
                                           "note": note}, 503)
                    return self._send_jpeg(data)
                if len(p) == 3 and p[:2] == ["preview", "feed"]:
                    target = p[2].upper()
                    if target not in PREVIEW_FEEDS:
                        return self._send({"error": "unknown feed", "feed": p[2]}, 404)
                    ports = {k: f.port for k, f in relay.feeds.items()}
                    if relay.pov:
                        ports["POV"] = relay.pov.port
                    kind, ref = preview_source(target, relay.live_feed(),
                                               relay.pov_active(), ports)
                    if kind == "placeholder":
                        return self._send({"error": "preview unavailable",
                                           "note": ref}, 503)
                    if kind == "obs":
                        if _obs_ws is None:
                            return self._send({"error": "obs unavailable"}, 503)
                        data, note = _obs_ws.get_source_screenshot(ref, width=480)
                        if data is None:
                            return self._send({"error": "preview unavailable",
                                               "note": note}, 503)
                        return self._send_jpeg(data)
                    data = grab_feed_frame(ref, width=480)   # kind == "grab"
                    if data is None:
                        return self._send({"error": "preview unavailable",
                                           "note": "grab failed"}, 503)
                    return self._send_jpeg(data)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 tests/test_pov.py`
Expected: all new `ok t_preview_*` lines, then `ALL PASS`.

- [ ] **Step 7: Lint + commit**

Run: `python3 tools/lint.py` → Expected: no errors.

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): /preview endpoints — program + per-feed stills over the panel

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Director Panel — Live Preview section

**Files:**
- Modify: `src/director/director-panel.html`

This is UI glue (no unit test framework for the panel HTML); verify by driving a running panel in Task 6. Keep edits minimal and match the file's existing `$("#id")` helper and `.bus` section style.

- [ ] **Step 1: Add the CSS**

In `src/director/director-panel.html`, just before `</style>` (line ~254):

```css
.preview .pvbody{margin-top:6px}
.pvprog img,.pvtile img{width:100%;display:block;background:#000;border-radius:6px;min-height:54px}
.pvfeeds{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-top:6px}
.pvlabel{font-size:11px;opacity:.85;margin-top:2px;display:flex;justify-content:space-between;align-items:center;gap:6px}
.pvtile.onair{outline:2px solid #4ade80;border-radius:6px}
.pvrefresh{padding:0 8px}
```

- [ ] **Step 2: Add the section markup**

In `src/director/director-panel.html`, insert immediately after the `PGM` bus section (the `<section class="bus pgm">…` line, ~286):

```html
  <section class="bus preview" id="previewSec">
    <div class="cap">Live Preview <button class="k" id="pvToggle">SHOW</button></div>
    <div class="pvbody" id="pvBody" hidden>
      <div class="pvprog">
        <img id="pvProgram" alt="Program output">
        <div class="pvlabel" id="pvProgramLabel"><span>PROGRAM</span></div>
      </div>
      <div class="pvfeeds">
        <div class="pvtile" data-feed="A"><img alt="Feed A">
          <div class="pvlabel"><span>FEED A</span><button class="k pvrefresh">↻</button></div></div>
        <div class="pvtile" data-feed="B"><img alt="Feed B">
          <div class="pvlabel"><span>FEED B</span><button class="k pvrefresh">↻</button></div></div>
        <div class="pvtile" data-feed="POV"><img alt="POV">
          <div class="pvlabel"><span>POV</span><button class="k pvrefresh">↻</button></div></div>
      </div>
    </div>
  </section>
```

- [ ] **Step 3: Add the JS**

In `src/director/director-panel.html`, add inside the main `<script>` block near the other top-level wiring (e.g. just before the `setInterval(relayPoll, 2000);` group, ~1322). Uses the file's `$` helper:

```javascript
// ---- Live Preview ---------------------------------------------------------
const PV_KEY = "rc_preview_open";
let pvTimer = null;
function pvSetProgram(){
  const img = $("#pvProgram");
  img.onerror = () => { img.removeAttribute("src"); img.alt = "OBS nicht erreichbar"; };
  img.src = "/preview/program?ts=" + Date.now();
}
function pvStart(){
  $("#pvBody").hidden = false; $("#pvToggle").textContent = "HIDE";
  pvSetProgram(); pvTimer = setInterval(pvSetProgram, 1500);
}
function pvStop(){
  $("#pvBody").hidden = true; $("#pvToggle").textContent = "SHOW";
  if(pvTimer){ clearInterval(pvTimer); pvTimer = null; }
}
$("#pvToggle").onclick = () => {
  const opening = $("#pvBody").hidden;
  if(opening){ pvStart(); } else { pvStop(); }
  try{ localStorage.setItem(PV_KEY, opening ? "1" : "0"); }catch(e){}
};
function pvGrabFeed(tile){
  const feed = tile.dataset.feed, img = tile.querySelector("img"),
        btn = tile.querySelector(".pvrefresh");
  btn.disabled = true; btn.textContent = "…";
  const done = () => { btn.disabled = false; btn.textContent = "↻"; };
  img.onload = done;
  img.onerror = () => { img.removeAttribute("src"); img.alt = feed + " nicht verfügbar"; done(); };
  img.src = "/preview/feed/" + feed + "?ts=" + Date.now();
}
document.querySelectorAll(".pvtile .pvrefresh").forEach(btn => {
  btn.onclick = () => pvGrabFeed(btn.closest(".pvtile"));
});
function pvMarkOnAir(feed){
  document.querySelectorAll(".pvtile").forEach(
    t => t.classList.toggle("onair", t.dataset.feed === feed));
  const lbl = $("#pvProgramLabel");
  if(lbl) lbl.firstElementChild.textContent = feed ? ("PROGRAM (Feed " + feed + " on air)") : "PROGRAM";
}
if((localStorage.getItem(PV_KEY) || "0") === "1"){ pvStart(); }
```

- [ ] **Step 4: Call `pvMarkOnAir` from the status poll**

The relay `/status` includes a `live` block (`{feed, stint, mode}`). In the existing `refresh()` success path (the one that sets `$("#stAir")`, around line 783–836), add one line after the `stAir` update:

```javascript
    pvMarkOnAir(d.live && d.live.feed);
```

- [ ] **Step 5: Syntax-check the JS**

Run (deno is a project tool; if present it catches JS syntax errors the build won't):
```bash
deno eval "import('node:fs').then(fs=>new Function(fs.readFileSync('src/director/director-panel.html','utf8').match(/<script>([\s\S]*)<\/script>/)[1]))" 2>/dev/null && echo "JS parses" || echo "check manually in build"
```
Expected: `JS parses` (or fall back to the build's verify in Task 6). Manual fallback: confirm the `<script>` block has balanced braces.

- [ ] **Step 6: Commit**

```bash
git add src/director/director-panel.html
git commit -m "feat(panel): collapsible Live Preview — program tile + click-to-grab feeds

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Wiki screenshot + full gates

**Files:**
- Replace: `src/docs/wiki/images/director-panel.png`

- [ ] **Step 1: Run the full suite + lint + build**

```bash
python3 tools/run-tests.py
python3 tools/lint.py
python3 tools/build.py
```
Expected: suite `ALL PASS` for every file, lint clean, `build.py` exits 0 (its verify step: tokenization, blanked password, no secrets, no shell scripts).

- [ ] **Step 2: Recapture the Director Panel screenshot**

The hard rule (CLAUDE.md): a visible Director Panel change must refresh `director-panel.png` in the same change. Drive a running panel and capture the full panel with the Live Preview section **expanded** (so the new tiles are visible):

1. Start a relay locally from `src/` so `/panel` is served (e.g. `python3 src/racecast.py relay run` against a test profile, or open `src/director/director-panel.html` through a relay instance). The Program/feed tiles will show "OBS nicht erreichbar" / "nicht verfügbar" placeholders if no OBS/feeds are up — acceptable for the screenshot, which documents the layout.
2. With Playwright MCP: `browser_navigate` to the panel URL, `browser_resize` to **1400** wide (match the existing image width), click `#pvToggle` to expand the section, then `browser_take_screenshot` of the full panel (`fullPage` framing consistent with the current 1400×2592 image).
3. Save/overwrite `src/docs/wiki/images/director-panel.png`.

- [ ] **Step 3: Verify the image landed**

Run: `python3 -c "import pathlib; p=pathlib.Path('src/docs/wiki/images/director-panel.png'); print(p.stat().st_size)"`
Expected: a non-trivial byte count (> 50000), newer than the previous capture.

- [ ] **Step 4: Commit**

```bash
git add src/docs/wiki/images/director-panel.png
git commit -m "docs(wiki): refresh director-panel screenshot with the Live Preview section

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Push + open the PR (after user OK)**

```bash
git push -u origin feat/live-preview
gh pr create --base main \
  --title "feat(panel): live preview multiview in the director panel" \
  --body "$(cat <<'EOF'
Adds an on-demand Live Preview multiview to the Director Panel:

- **Program tile** — live OBS program output via obs-websocket `GetSourceScreenshot`, auto-refresh ~1.5s, only while the section is shown.
- **Feed tiles (A/B/POV)** — click-to-grab stills: on-air feed + active POV via OBS; off-air feed via a one-frame `ffmpeg` grab from the feed's own loopback port. Bounded upstream traffic.
- Collapsible, hidden by default (state persisted in `localStorage`); panel-only; tailnet stays the trust boundary. All relay work is read-only and best-effort.

Spec: `docs/superpowers/specs/2026-06-16-live-preview-design.md`
Plan: `docs/superpowers/plans/2026-06-16-live-preview.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 6: Land it (per ship-feature)** — wait for green CI across the matrix (macOS + Windows + Linux × 3.11–3.13, lint, CodeQL, gitleaks, binary-smoke); then squash-merge + delete branch after user OK; `git checkout main && git pull`.

---

## Self-review

**Spec coverage:**
- Program tile via OBS screenshot → Tasks 2 (`get_program_screenshot`), 4 (`/preview/program`), 5 (tile + poll). ✓
- On-air feed via OBS, off-air via port grab, POV active/placeholder → Task 3 (`preview_source`), Task 4 (routing + grab). ✓
- Click-only feeds, ~1.5s program, hidden-by-default, localStorage toggle → Task 5. ✓
- Best-effort / 503 placeholders / no-store / hard timeout / no background work → Tasks 2, 4 (503 paths, `no-store`, `grab_feed_frame` timeout), 5 (interval cleared on hide). ✓
- Panel-only surface → no Control Center changes. ✓
- Tests: `parse_screenshot_data_uri`, `get_source_screenshot` vs mock OBS, `preview_source` table, `feed_grab_cmd` pinned, endpoint routing → Tasks 1–4. ✓
- Wiki `director-panel.png` refresh → Task 6. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command has expected output.

**Type consistency:** `screenshot_request_data` / `parse_screenshot_data_uri` / `get_source_screenshot` / `get_program_screenshot` (obs_ws) and `preview_source` / `feed_grab_cmd` / `grab_feed_frame` / `_send_jpeg` / `PREVIEW_FEEDS` (relay) are named identically across their defining task, the endpoint wiring (Task 4), and the tests. Return contracts match: `get_*_screenshot → (bytes|None, note)`; `grab_feed_frame → bytes|None`; `preview_source → (kind, ref)`.
