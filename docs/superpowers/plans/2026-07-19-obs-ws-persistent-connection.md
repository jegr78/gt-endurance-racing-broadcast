# Persistent obs-websocket connection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the relay's connect-per-poll obs-websocket churn (~45k closes in one event) with two reused, lock-guarded persistent connections (screenshots vs control), transparently reconnecting on a dead socket, default-on with a kill-switch.

**Architecture:** `_Session` self-reports socket death via an `alive` flag; each OBS-network function gains an optional `session=None` (default path byte-identical to today); a lock-guarded `_ObsConn` holder reuses one session and reconnect-retries once; a `_ObsFacade` routes the relay's `_obs_ws.X` calls through the right holder; a `_PassthroughConn` restores connect-per-call when the kill-switch is off.

**Tech Stack:** Python 3 stdlib. Tests are stdlib runnable scripts (`t_*` auto-run). `tests/test_obsws.py` loads `src/scripts/obs_ws.py` as `m`.

## Global Constraints

- Edit only under `src/` (+ `tests/`, `.env.example`). Never `dist/`/`runtime/`.
- stdlib only; English only. Every obs_ws public function keeps its **best-effort contract: never raises**; the persistent path preserves it.
- The default (`session=None`, kill-switch off = passthrough) path must be **byte-identical to today** — the existing `tests/test_obsws.py` stays green untouched.
- `_obs_ws` (the imported module in `racecast-feeds.py`) stays the None-sentinel: build `relay._obs` iff `_obs_ws is not None`, so the 24 existing `if _obs_ws is None:` guards remain valid and are **not edited**.
- Kill-switch `RACECAST_OBS_WS_PERSIST` default on; falsey tokens `{"0","false","no","off"}` (reuse `_FANOUT_FALSEY`) → passthrough.
- `python3 tools/run-tests.py` + `python3 tools/lint.py` + `python3 tools/build.py` green at the end.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: `_Session.alive` — socket-death self-report

**Files:**
- Modify: `src/scripts/obs_ws.py` — `_Session` (class at line 334; `__init__` 337, `next_json` 342, `send_json` 360)
- Test: `tests/test_obsws.py`

**Interfaces:**
- Produces: `_Session` instances carry `self.alive` (bool, starts True); set False the moment a `sendall`/`recv` raises `OSError`, or the connection is seen closed (empty recv / opcode 0x8). A request-level `ValueError` (from `request()`) does NOT touch `alive`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_obsws.py`; it loads obs_ws as `m`). Use a minimal fake socket.

```python
class _FakeSock:
    def __init__(self, recv_chunks=None, send_raises=False):
        self._recv = list(recv_chunks or [])
        self._send_raises = send_raises
        self.sent = []
    def sendall(self, b):
        if self._send_raises:
            raise OSError("broken pipe")
        self.sent.append(b)
    def recv(self, n):
        if self._recv:
            return self._recv.pop(0)
        return b""                       # EOF
    def settimeout(self, t): pass
    def close(self): pass


def t_session_alive_starts_true():
    s = m._Session(_FakeSock(), b"")
    assert s.alive is True


def t_session_send_marks_dead_on_oserror():
    s = m._Session(_FakeSock(send_raises=True), b"")
    try:
        s.send_json({"x": 1})
    except OSError:
        pass
    assert s.alive is False, "send failure must flag the session dead"


def t_session_next_json_marks_dead_on_eof():
    s = m._Session(_FakeSock(recv_chunks=[]), b"")   # recv -> b"" -> EOF
    try:
        s.next_json()
    except ConnectionError:
        pass
    assert s.alive is False
```

- [ ] **Step 2: Run — confirm RED**

Run: `python3 tests/test_obsws.py`
Expected: FAIL — `_Session` has no `alive`.

- [ ] **Step 3: Implement** (in `src/scripts/obs_ws.py`)

- `_Session.__init__`: add `self.alive = True` after `self.counter = 0`.
- `send_json`: wrap the send so a failure flags death, then re-raises:
```python
    def send_json(self, obj):
        try:
            self.sock.sendall(encode_frame(json.dumps(obj).encode()))
        except OSError:
            self.alive = False
            raise
```
- `next_json`: flag death on the two close paths and on a `recv` `OSError`:
```python
    def next_json(self):
        while True:
            frame = decode_frame(self.buf)
            if frame is None:
                try:
                    chunk = self.sock.recv(65536)
                except OSError:
                    self.alive = False
                    raise
                if not chunk:
                    self.alive = False
                    raise ConnectionError("OBS closed the connection")
                self.buf += chunk
                continue
            opcode, payload, self.buf = frame
            if opcode == 0x9:
                self.sock.sendall(encode_frame(payload, opcode=0xA))
            elif opcode == 0x8:
                self.alive = False
                raise ConnectionError("OBS closed the connection")
            elif opcode == 0x1:
                return json.loads(payload)
```

- [ ] **Step 4: Run — confirm GREEN + commit**

Run: `python3 tests/test_obsws.py`
Expected: PASS (new + all existing).
```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs-ws): _Session.alive flag — self-report socket death (#537)"
```

---

### Task 2: Optional `session=None` on the OBS-network functions

**Files:**
- Modify: `src/scripts/obs_ws.py` — the 18 OBS-network functions listed below
- Test: `tests/test_obsws.py`

**Interfaces:**
- Consumes: `_Session` (Task 1).
- Produces: each listed function gains a trailing `session=None` kwarg. When a session is passed, the function uses it and does **not** call `_connect` or `session.close()`; when omitted, behavior is unchanged. Return shapes unchanged.

Functions (grep each; all currently open via `session, note = _connect(...)` or `_open_session`, then `session.close()`):
`get_program_screenshot` (704), `get_source_screenshot` (682), `read_obs_state` (913), `get_health_stats` (539), `get_current_program_scene` (730), `set_current_program_scene` (776), `switch_to_scene_if_idle` (808), `set_scene_item_enabled` (1022), `set_scene_item_transform` (1045), `set_input_volume` (832), `set_input_mute` (848), `set_stream` (864), `set_stream_service` (886), `reflect_feed_state` (963), `refresh_browser_inputs` (650), `release_feed_inputs` (569), `get_scene_collection` (1070), `set_scene_collection` (1092).

**Transformation rule** (apply to each; preserve every function's existing request logic exactly — change ONLY the connect/close bracketing):

- Add `session=None` as the last parameter.
- Replace the open line `session, note = _connect(host, port, password, timeout)` with:
```python
    own = session is None
    if own:
        session, note = _connect(host, port, password, timeout)
    if session is None:
        return <the function's existing early-return value>, note
```
  (Keep the exact early-return tuple the function already uses — e.g. `None, note`, `(False, note)`, `(None, None, note)` for `get_health_stats`, `[], note`, etc. Do not change it.)
- Guard the close: change `session.close()` to run only when we opened it. If the function already uses `try/finally`, make it `finally: if own: session.close()`. If it closes without a finally, wrap the body in `try: ... finally: if own: session.close()` — OR if the function's structure makes a minimal change cleaner, replace the trailing `session.close()` with `if own: session.close()` provided every return path still reaches it (prefer `try/finally` when unsure).
- `get_health_stats` (539) uses `_open_session` directly (not `_connect`); apply the same `own`/guard logic to its session acquisition and its `session.close()`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_obsws.py`). A fake session that records requests and never closes, proving the passed-session path skips connect/close.

```python
class _FakeSession:
    def __init__(self, responses):
        self.responses = dict(responses)   # request_type -> responseData
        self.alive = True
        self.closed = False
        self.requests = []
    def request(self, rt, rd):
        self.requests.append((rt, rd))
        return self.responses.get(rt, {})
    def close(self):
        self.closed = True


def t_set_input_mute_uses_passed_session_no_connect_no_close(monkey=None):
    fs = _FakeSession({"SetInputMute": {}})
    called = {"connect": 0}
    orig = m._connect
    m._connect = lambda *a, **k: (called.__setitem__("connect", called["connect"] + 1), (None, "x"))[1]
    try:
        ok, note = m.set_input_mute("Feed A", True, session=fs)
    finally:
        m._connect = orig
    assert ok is True and note == "" , (ok, note)
    assert called["connect"] == 0, "must NOT open its own connection"
    assert fs.closed is False, "must NOT close a session it did not open"
    assert fs.requests and fs.requests[0][0] == "SetInputMute"


def t_omitting_session_still_connects_and_closes():
    # Default path: a stub _connect returns a fake session; the function must close it.
    fs = _FakeSession({"SetInputMute": {}})
    orig = m._connect
    m._connect = lambda *a, **k: (fs, "")
    try:
        ok, note = m.set_input_mute("Feed A", True)
    finally:
        m._connect = orig
    assert ok is True and fs.closed is True, "own-session path must close"
```
(If `set_input_mute`'s success return is not `(True, "")`, adjust the assert to its real shape — read the function first. Pick a second function of a different shape, e.g. `get_current_program_scene`, and add the same passed-session/no-close assertion.)

- [ ] **Step 2: Run — confirm RED** → `python3 tests/test_obsws.py` (TypeError: unexpected kwarg `session`).

- [ ] **Step 3: Implement** — apply the transformation rule to all 18 functions.

- [ ] **Step 4: Run — confirm GREEN + commit**

Run: `python3 tests/test_obsws.py`
Expected: PASS (new + all existing untouched).
```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs-ws): optional session= reuse on the OBS-network functions (#537)"
```

---

### Task 3: `_ObsConn` holder + `_PassthroughConn`

**Files:**
- Modify: `src/scripts/obs_ws.py` — add the two classes near `_connect` (after line 452) and ensure `import threading` is present (add if missing)
- Test: `tests/test_obsws.py`

**Interfaces:**
- Consumes: `_connect`, `_Session.alive` (Tasks 1-2).
- Produces:
  - `_ObsConn(host="127.0.0.1", port=None, password=None, timeout=2.0)` with `.run(func, *args, **kwargs)` and `.close()`.
  - `_PassthroughConn()` with `.run(func, *args, **kwargs)` = `func(*args, **kwargs)` and a no-op `.close()`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_obsws.py`)

```python
def _script_conn(sessions):
    """An _ObsConn whose _connect yields the given fake sessions in order (then None)."""
    c = m._ObsConn()
    seq = list(sessions)
    def fake_connect(*a, **k):
        return (seq.pop(0), "") if seq else (None, "OBS down")
    c._connect_fn = fake_connect      # test seam (see implement note)
    return c


def t_obsconn_reuses_one_session():
    fs = _FakeSession({"GetVersion": {}})
    c = _script_conn([fs])
    calls = {"n": 0}
    def fn(session=None):
        calls["n"] += 1
        session.request("GetVersion", {})
        return "ok", ""
    assert c.run(fn) == ("ok", "")
    assert c.run(fn) == ("ok", "")
    assert calls["n"] == 2 and len(fs.requests) == 2   # reused: one session, two calls


def t_obsconn_reconnects_and_retries_once_on_death():
    dead = _FakeSession({}); dead.alive = True
    good = _FakeSession({"GetVersion": {}})
    c = _script_conn([dead, good])
    def fn(session=None):
        if session is dead:
            session.alive = False          # simulate socket dying mid-call
            return None, "died"
        session.request("GetVersion", {})
        return "ok", ""
    assert c.run(fn) == ("ok", "")         # retried on the fresh (good) session
    assert dead.closed is True             # dead one was dropped/closed


def t_obsconn_no_retry_on_request_level_failure():
    fs = _FakeSession({}); fs.alive = True
    c = _script_conn([fs])
    calls = {"n": 0}
    def fn(session=None):
        calls["n"] += 1
        return None, "scene not found"     # request-level failure; session stays alive
    assert c.run(fn) == (None, "scene not found")
    assert calls["n"] == 1                 # NOT retried
    assert fs.closed is False


def t_obsconn_obs_down_falls_back_to_no_session():
    c = _script_conn([])                   # _connect always returns (None, ...)
    seen = {"session": "unset"}
    def fn(session=None):
        seen["session"] = session
        return None, "obs unavailable"
    assert c.run(fn) == (None, "obs unavailable")
    assert seen["session"] is None         # called WITHOUT a session (per-call fallback)


def t_passthrough_calls_without_session():
    c = m._PassthroughConn()
    seen = {"kw": "unset"}
    def fn(x, session="MISSING"):
        seen["kw"] = session
        return x
    assert c.run(fn, 7) == 7
    assert seen["kw"] == "MISSING"         # no session kwarg injected
    c.close()                              # no-op, must not raise
```

- [ ] **Step 2: Run — confirm RED** → `python3 tests/test_obsws.py` (no `_ObsConn`).

- [ ] **Step 3: Implement** (in `src/scripts/obs_ws.py`; add `import threading` at the top if absent)

```python
class _ObsConn:
    """One persistent, lock-guarded obs-websocket session, reused across calls with
    transparent reconnect-and-retry-once (#537). Best-effort: never raises."""

    def __init__(self, host="127.0.0.1", port=None, password=None, timeout=2.0):
        self.host, self.port, self.password, self.timeout = host, port, password, timeout
        self._lock = threading.Lock()
        self._session = None
        self._connect_fn = _connect        # test seam

    def _drop(self):
        s, self._session = self._session, None
        if s is not None:
            s.close()

    def _ensure(self):
        if self._session is not None and not self._session.alive:
            self._drop()
        if self._session is None:
            self._session, _ = self._connect_fn(self.host, self.port, self.password, self.timeout)
        return self._session

    def run(self, func, *args, **kwargs):
        with self._lock:
            result = None
            for attempt in (0, 1):
                sess = self._ensure()
                if sess is None:
                    return func(*args, **kwargs)      # OBS down -> per-call path -> clean note
                result = func(*args, session=sess, **kwargs)
                if sess.alive:
                    return result                     # success OR request-level failure
                self._drop()                          # socket died during the call
                if attempt == 1:
                    return result                     # already retried once
            return result

    def close(self):
        with self._lock:
            self._drop()


class _PassthroughConn:
    """Kill-switch OFF: connect-per-call, no session reuse (#537)."""
    def run(self, func, *args, **kwargs):
        return func(*args, **kwargs)
    def close(self):
        pass
```

- [ ] **Step 4: Run — confirm GREEN + commit**

Run: `python3 tests/test_obsws.py`
Expected: PASS.
```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs-ws): _ObsConn persistent holder + _PassthroughConn (#537)"
```

---

### Task 4: `_ObsFacade` — route calls to the two holders

**Files:**
- Modify: `src/scripts/obs_ws.py` — add `_SHOT_FNS`, `_ROUTED_FNS`, `_ObsFacade` after `_PassthroughConn`
- Test: `tests/test_obsws.py`

**Interfaces:**
- Consumes: `_ObsConn`/`_PassthroughConn` (Task 3), the module functions.
- Produces:
  - `_SHOT_FNS = frozenset({"get_program_screenshot", "get_source_screenshot"})`
  - `_ROUTED_FNS = _SHOT_FNS | frozenset({<the 16 control/read names from Task 2>})`
  - `_ObsFacade(shot, ctrl, module)` — `__getattr__(name)`: if `name in _ROUTED_FNS` returns `lambda *a, **k: (shot if name in _SHOT_FNS else ctrl).run(getattr(module, name), *a, **k)`; else `getattr(module, name)` (constants + pure helpers pass through). `.close()` closes both holders.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_obsws.py`)

```python
class _RecordConn:
    def __init__(self, tag): self.tag, self.calls = tag, []
    def run(self, func, *a, **k):
        self.calls.append((getattr(func, "__name__", func), a, k)); return self.tag
    def close(self): self.calls.append(("closed", (), {}))


def t_facade_routes_screenshot_vs_control():
    shot, ctrl = _RecordConn("shot"), _RecordConn("ctrl")
    fac = m._ObsFacade(shot, ctrl, m)
    assert fac.get_program_screenshot(width=640) == "shot"
    assert fac.set_input_mute("Feed A", True) == "ctrl"
    assert shot.calls[0][0] == "get_program_screenshot"
    assert ctrl.calls[0][0] == "set_input_mute"


def t_facade_passes_through_non_routed_attrs():
    shot, ctrl = _RecordConn("shot"), _RecordConn("ctrl")
    fac = m._ObsFacade(shot, ctrl, m)
    assert fac.STINT_SCENE is m.STINT_SCENE              # constant pass-through
    assert fac.stream_kbps is m.stream_kbps             # pure helper pass-through (not routed)
    assert not shot.calls and not ctrl.calls


def t_facade_close_closes_both():
    shot, ctrl = _RecordConn("shot"), _RecordConn("ctrl")
    m._ObsFacade(shot, ctrl, m).close()
    assert shot.calls[-1][0] == "closed" and ctrl.calls[-1][0] == "closed"
```

- [ ] **Step 2: Run — confirm RED** → `python3 tests/test_obsws.py` (no `_ObsFacade`).

- [ ] **Step 3: Implement**

```python
_SHOT_FNS = frozenset({"get_program_screenshot", "get_source_screenshot"})
_ROUTED_FNS = _SHOT_FNS | frozenset({
    "read_obs_state", "get_health_stats", "get_current_program_scene",
    "set_current_program_scene", "switch_to_scene_if_idle", "set_scene_item_enabled",
    "set_scene_item_transform", "set_input_volume", "set_input_mute", "set_stream",
    "set_stream_service", "reflect_feed_state", "refresh_browser_inputs",
    "release_feed_inputs", "feed_media_cursors", "get_scene_collection",
    "set_scene_collection",
})


class _ObsFacade:
    """Routes the relay's obs_ws.* calls through two persistent holders (#537):
    screenshots on one connection, control/read on the other. Non-routed attributes
    (constants, pure helpers) pass straight through to the module."""

    def __init__(self, shot, ctrl, module):
        self._shot, self._ctrl, self._m = shot, ctrl, module

    def __getattr__(self, name):
        if name in _ROUTED_FNS:
            conn = self._shot if name in _SHOT_FNS else self._ctrl
            fn = getattr(self._m, name)
            return lambda *a, **k: conn.run(fn, *a, **k)
        return getattr(self._m, name)

    def close(self):
        self._shot.close()
        self._ctrl.close()
```
Note: `feed_media_cursors` is in `_ROUTED_FNS` and must therefore have gained `session=` in Task 2 — if Task 2 omitted it, add `session=None` to it now (grep to confirm it is in the Task 2 list; it is).

- [ ] **Step 4: Run — confirm GREEN + commit**

Run: `python3 tests/test_obsws.py`
Expected: PASS.
```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs-ws): _ObsFacade routes screenshots vs control to two holders (#537)"
```

---

### Task 5: Relay wiring — build `relay._obs`, route the call sites, teardown

**Files:**
- Modify: `src/relay/racecast-feeds.py` — config helper + `Relay.__init__` + the routable call sites + teardown + `apply_split_audio` caller
- Test: `tests/test_racecast.py` (a small routing/construction check if feasible) — otherwise the obs_ws unit tests + the full suite/build gate cover it

**Interfaces:**
- Consumes: `_ObsFacade`, `_ObsConn`, `_PassthroughConn` (Tasks 3-4).
- Produces: `Relay._obs` — an `_ObsFacade` when `_obs_ws is not None`, else `None`. `obs_ws_persist_enabled(environ) -> bool`.

- [ ] **Step 1: Add the config helper + build the facade**

- Near the other `*_enabled` helpers (e.g. after `fanout_enabled`, ~line 350), add:
```python
def obs_ws_persist_enabled(environ):
    """Reuse two persistent obs-websocket connections instead of connect-per-call
    (#537). Default ON; a falsey RACECAST_OBS_WS_PERSIST restores connect-per-call. Pure."""
    return str(environ.get("RACECAST_OBS_WS_PERSIST", "")).strip().lower() not in _FANOUT_FALSEY
```
- In `Relay.__init__` (near the other transport config, after `self.fanout = ...` ~line 6041), build the facade:
```python
        if _obs_ws is None:
            self._obs = None
        elif obs_ws_persist_enabled(os.environ):
            self._obs = _obs_ws._ObsFacade(_obs_ws._ObsConn(), _obs_ws._ObsConn(), _obs_ws)
        else:
            self._obs = _obs_ws._ObsFacade(_obs_ws._PassthroughConn(),
                                           _obs_ws._PassthroughConn(), _obs_ws)
```
(The two `_ObsConn()` use the obs_ws default host/port/password resolution — same as today's calls, which pass no host/port. Good.)

- [ ] **Step 2: Route the call sites** — replace `_obs_ws.<fn>(...)` with the facade for the routable network calls. Leave the 24 `if _obs_ws is None:` guards and constant access (`_obs_ws.STINT_SCENE`, `_obs_ws.POV_SOURCE`, `_obs_ws.stream_kbps`) **unchanged**.

  **In Relay methods → `self._obs.<fn>`:**
  - 6444 `_obs_ws.feed_media_cursors(ports=[f.port])` → `self._obs.feed_media_cursors(...)`
  - 6491 `_obs_ws.get_current_program_scene()` → `self._obs.get_current_program_scene()`
  - 6505 `_obs_ws.set_current_program_scene(intermission)` → `self._obs.set_current_program_scene(...)`
  - 6547 `_obs_ws.read_obs_state(...)` → `self._obs.read_obs_state(...)`
  - 6558, 6567, 6747 `_obs_ws.set_scene_item_enabled(...)` → `self._obs.set_scene_item_enabled(...)`
  - 6765 `_obs_ws.reflect_feed_state(live, cut)` → `self._obs.reflect_feed_state(...)`
  - 6801 `_obs_ws.get_health_stats()` → `self._obs.get_health_stats()`

  **In handler methods → `relay._obs.<fn>`** (the handler holds a `relay` local; confirm by context):
  - 8288, 8497 the screenshot lambdas `lambda: _obs_ws.get_program_screenshot(width=640)` → `lambda: relay._obs.get_program_screenshot(width=640)`
  - 8413, 8972, 9028 `_obs_ws.read_obs_state(...)` → `relay._obs.read_obs_state(...)`
  - 8929 `set_current_program_scene`, 8938 `set_scene_item_enabled`, 8947 `set_input_mute`, 8949 `set_input_volume`, 8963/9042/9070 `set_stream`, 8986 `refresh_browser_inputs`, 9003 `release_feed_inputs`, 9039 `set_stream_service` → `relay._obs.<fn>(...)`

  **Nested closure 9553** `_flag_graphic_apply` — `return _obs_ws.set_scene_item_enabled(...)` → use the enclosing scope's facade ref: `self._obs` if the enclosing method has `self`, else `relay._obs` (grep the enclosing `def` at ~9548 to see which name is in scope).

  **Leave on the module (documented, negligible churn):** 5739 `Feed._obs_reconnect_now` — the Feed holds no facade ref; a drop-recovery reconnect is rare, so keep `_obs_ws.release_feed_inputs(...)` as-is. Add a one-line comment noting why.

- [ ] **Step 3: `apply_split_audio` callers pass the facade.** Two call sites — **8390** and **8955** — both read `apply_split_audio(relay, _obs_ws)`. Change each `_obs_ws` argument to `relay._obs`, so its `obs_ws.set_input_mute(...)` route through the control conn. (`apply_split_audio`'s body at 3371 is unchanged — it already calls `obs_ws.set_input_mute`, which the facade routes.)

- [ ] **Step 4: Teardown** in `Relay.shutdown` (line 7330). Append a best-effort close of the facade:
```python
    def shutdown(self):
        for f in self.feeds.values(): f.shutdown()
        if self.pov: self.pov.shutdown()
        for srv in self._fanout_servers: srv.stop()
        if getattr(self, "_obs", None) is not None:
            try:
                self._obs.close()          # #537: clean 1000 on the persistent sessions
            except Exception:  # noqa: BLE001 — best-effort
                pass
```

- [ ] **Step 5: (Optional) construction test** — if `tests/test_racecast.py` can build a `Relay` cheaply, add a check that `obs_ws_persist_enabled({})` is True, `obs_ws_persist_enabled({"RACECAST_OBS_WS_PERSIST": "0"})` is False. If building a Relay is heavy, just add these two pure-helper assertions:
```python
def t_obs_ws_persist_default_on():
    import importlib.util, os
    # load the relay module the same way the file's other tests do (reuse its loader)
    assert relaymod.obs_ws_persist_enabled({}) is True
    assert relaymod.obs_ws_persist_enabled({"RACECAST_OBS_WS_PERSIST": "0"}) is False
```
(Use the module alias `tests/test_racecast.py` already binds; if none, add one mirroring another test file's `spec_from_file_location("irofeeds", ...src/relay/racecast-feeds.py...)`.)

- [ ] **Step 6: Run + commit**

Run: `python3 tests/test_racecast.py` then `python3 tests/test_pov.py` then `python3 tests/test_obsws.py`
Expected: all PASS.
```bash
git add src/relay/racecast-feeds.py tests/test_racecast.py .env.example
git commit -m "feat(relay): route OBS calls through persistent connections (#537)"
```
(Also add to `.env.example`, near the other `RACECAST_*` OBS knobs: `# RACECAST_OBS_WS_PERSIST=0   # #537: disable persistent obs-websocket reuse (connect-per-call)`.)

---

### Task 6: Full-suite + lint + build gate

- [ ] `python3 tools/run-tests.py` → ALL PASS. `python3 tools/lint.py` → clean. `python3 tools/build.py` → verify passes. Commit any fixups only if needed.

## Self-Review

- Spec §1 `_Session.alive` → Task 1. ✅
- Spec §2 `session=None` on the OBS-network fns → Task 2 (18 fns, transformation rule, default byte-identical). ✅
- Spec §3 `_ObsConn` (reconnect-retry-once, request-level no-retry, OBS-down fallback) + `_PassthroughConn` → Task 3. ✅
- Spec §4 `_ObsFacade` routing + pass-through + relay wiring (facade None when module None, 24 guards untouched, screenshot lambdas, apply_split_audio, teardown) → Task 4 + Task 5. ✅
- Spec §Config `RACECAST_OBS_WS_PERSIST` default-on → Task 5 (`obs_ws_persist_enabled`, `.env.example`). ✅
- Spec §Testing — holder fake-session matrix (a-e), facade routing/pass-through/passthrough-no-session, `_Session.alive`, session=-passthrough per shape → Tasks 1-4 tests. ✅
- Best-effort/never-raises preserved (holder returns func results; passthrough; OBS-down fallback). ✅
- Type consistency: `_ObsConn(host,port,password,timeout).run(func,*a,**k)/close()`; `_PassthroughConn.run/close`; `_ObsFacade(shot,ctrl,module).__getattr__/close`; `_SHOT_FNS ⊂ _ROUTED_FNS`; `_Session.alive`; `obs_ws_persist_enabled(environ)`; `Relay._obs` — consistent across tasks.
- No placeholders; each code step shows code, each run step shows command + expected.
