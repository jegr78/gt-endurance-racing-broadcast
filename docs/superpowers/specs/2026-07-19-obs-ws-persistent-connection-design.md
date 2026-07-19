# Persistent obs-websocket connection — design

**Issue:** #537. Source: Suzuka 8h (2026-07-18) — the OBS log for the 8.5 h event held
**~45,000** `WebSocketServer::onClose … code 1000` lines: the relay opens a **new
obs-websocket connection per poll** (program screenshot, state read, health, control)
and closes it immediately. Functionally harmless (clean 1000 closes) but heavy
connect/handshake/identify churn and log noise.

**Status:** design approved (brainstorming), pending spec review.

## Problem

Every public function in `src/scripts/obs_ws.py` is stateless: `_connect` (TCP + WS
upgrade + obs-websocket identify) → one or more `session.request(...)` → `session.close()`.
The dominant caller is `get_program_screenshot` — each Director-Panel / cockpit /
race-control viewer polls the program image every ~1–2 s, and every poll is a full
connect+identify+close. State reads (`read_obs_state`), the heartbeat
(`get_health_stats`), and the control/write calls add the rest. At ~1.5 closes/s over
8.5 h that is the 45k.

## Decisions (from brainstorming)

- **Two persistent connections.** A dedicated **screenshot** connection carries the
  frequent, slightly-slow `get_program_screenshot`/`get_source_screenshot`; a **control**
  connection carries state reads + health + every control/write call. Separate locks mean
  a screenshot in flight can never delay a scene switch or mute.
- **Default ON with a kill-switch.** `RACECAST_OBS_WS_PERSIST` defaults on; `=0` falls back
  to today's connect-per-call path instantly (matches the fan-out / prebuffer rollout
  pattern). The proven per-call path stays the fallback.

## Architecture

### 1. `_Session.alive` (obs_ws.py)

`_Session` gains `self.alive = True`, set to `False` the moment a socket op fails:
- `send_json`: wrap `sock.sendall` — on `OSError` set `alive=False`, re-raise.
- `next_json`: on the empty-`recv` / opcode-0x8 close paths (already `raise
  ConnectionError`) and on any `recv` `OSError`, set `alive=False` first.

This lets the holder learn a socket died even though the public function swallows the
exception into its best-effort note. A request-level failure (`ValueError` "scene not
found", raised by `request()` on a non-`result` response) leaves `alive=True` — it is not
a dead socket.

### 2. Optional `session=None` on the OBS-network functions (obs_ws.py)

Each OBS-network function gains a trailing `session=None` kwarg. Pattern (shown for
`get_program_screenshot`; identical shape for the rest):

```python
def get_program_screenshot(..., session=None):
    own = session is None
    if own:
        session, note = _connect(host, port, password, timeout)
        if session is None:
            return None, note
    try:
        ... existing session.request(...) work ...
        return value, ""
    except Exception as exc:            # noqa: BLE001 — best-effort
        return None, str(exc) or exc.__class__.__name__
    finally:
        if own:
            session.close()
```

When `session` is passed the function uses it and **never** calls `_connect`/`close`.
When omitted, behavior is **byte-identical to today** — so the CLI (`racecast obs
collection`, `probe`, …) and every existing test are untouched (no test churn beyond the
new ones).

Functions to gain the kwarg (the ones the relay routes; the OBS-network set):
- **Screenshot:** `get_program_screenshot`, `get_source_screenshot`.
- **Control/read:** `read_obs_state`, `get_health_stats`, `get_current_program_scene`,
  `set_current_program_scene`, `switch_to_scene_if_idle`, `set_scene_item_enabled`,
  `set_scene_item_transform`, `set_input_mute`, `set_input_volume`, `set_stream`,
  `set_stream_service`, `reflect_feed_state`, `refresh_browser_inputs`,
  `release_feed_inputs`, `feed_media_cursors`, `get_scene_collection`,
  `set_scene_collection`.

Pure helpers (`stream_kbps`, `parse_*`, constants) get nothing — they never touch a
socket.

### 3. `_ObsConn` holder (obs_ws.py)

```python
class _ObsConn:
    """One persistent, lock-guarded obs-websocket session, reused across calls with
    transparent reconnect-and-retry-once. Best-effort: never raises."""
    def __init__(self, host="127.0.0.1", port=None, password=None, timeout=2.0):
        ...; self._lock = threading.Lock(); self._session = None

    def _ensure(self):
        if self._session is not None and not self._session.alive:
            self._drop()
        if self._session is None:
            self._session, _ = _connect(self.host, self.port, self.password, self.timeout)
        return self._session          # may stay None (OBS down)

    def _drop(self):
        s, self._session = self._session, None
        if s is not None:
            s.close()                 # best-effort clean 1000

    def run(self, func, *args, **kwargs):
        with self._lock:
            for attempt in (0, 1):
                sess = self._ensure()
                if sess is None:
                    return func(*args, **kwargs)        # OBS down → per-call path → clean note
                result = func(*args, session=sess, **kwargs)
                if sess.alive:
                    return result                       # success OR request-level failure
                self._drop()                            # socket died during the call
                if attempt == 1:
                    return result                       # already retried once
            return result

    def close(self):
        with self._lock:
            self._drop()
```

**Why retry-once heals the idle case:** if OBS silently closed the idle socket, the cached
session is still `alive=True` until we use it; the first `func(session=sess)` then fails
(`recv`→EOF→`alive=False`), the holder drops and retries on a fresh session within the
**same** `run()` — so no call is lost to an idle close. A genuine OBS outage makes
`_ensure` return `None` and we fall back to the per-call path (same clean 503/note as
today). Request-level failures keep `alive=True` and are never retried (so an idempotent
double-write is avoided).

### 4. `_ObsFacade` (obs_ws.py) + relay wiring

The relay currently calls `_obs_ws.<fn>(...)` everywhere (`_obs_ws` is the imported
module, or `None` if obs-websocket support is absent). A facade centralizes routing:

```python
_SHOT_FNS = frozenset({"get_program_screenshot", "get_source_screenshot"})
_ROUTED_FNS = _SHOT_FNS | frozenset({...the control/read set above...})

class _ObsFacade:
    def __init__(self, shot, ctrl, module):
        self._shot, self._ctrl, self._m = shot, ctrl, module
    def __getattr__(self, name):
        if name in _ROUTED_FNS:
            conn = self._shot if name in _SHOT_FNS else self._ctrl
            fn = getattr(self._m, name)
            return lambda *a, **k: conn.run(fn, *a, **k)
        return getattr(self._m, name)      # constants + pure helpers pass straight through
    def close(self):
        self._shot.close(); self._ctrl.close()
```

- Call sites swap `_obs_ws.X(...)` → `relay._obs.X(...)` uniformly — routed names go
  through the holders, non-routed names (`STINT_SCENE`, `POV_SOURCE`, `stream_kbps`, …)
  pass through unchanged.
- `relay._obs` is a `_ObsFacade` when `_obs_ws is not None`, else `None`. The existing
  `if _obs_ws is None:` guards become `if relay._obs is None:` (support-absent → 503,
  unchanged).
- The program-screenshot cache wrapper `_program_shot_cache.fetch(lambda:
  _obs_ws.get_program_screenshot(width=640))` becomes `… fetch(lambda:
  relay._obs.get_program_screenshot(width=640))` — routed through the shot conn.
- `apply_split_audio(relay, obs_ws)` is called with `relay._obs` instead of the module, so
  its `obs_ws.set_input_mute(...)` calls route through the control conn.

**Kill-switch off** (`RACECAST_OBS_WS_PERSIST=0`): `relay._obs` is still a `_ObsFacade`,
but built over **passthrough** holders whose `run(func, *a, **k)` just returns
`func(*a, **k)` (no `session=`, connect-per-call). Same call sites, proven path. A
`_PassthroughConn` with a no-op `close()` gives this uniformly.

### 5. Lifecycle & threading

- Both holders are created in `Relay.__init__` (from `RACECAST_OBS_WS_PERSIST`), connect
  lazily on first `run`. No idle reaping (two authed idle sockets are cheap; OBS keeps
  them; retry-once handles a silent close).
- Each holder has its **own** lock; calls within a holder serialize over its one socket
  (required — obs-ws responses on one socket must not interleave); the two holders are
  independent, so screenshots never block control calls.
- Closed on relay teardown (the same place the heartbeat thread is stopped), best-effort.

## Config

- `RACECAST_OBS_WS_PERSIST` — default **on**; falsey (`0/false/no/off`, reusing
  `_FANOUT_FALSEY`) → passthrough (connect-per-call).

## Interactions

- **Best-effort / 503 contract:** unchanged. A routed call on a down OBS returns the same
  `(None, note)` today's per-call path returns; the five control endpoints still map that
  to 503, `/obs/refresh` still to `count:0`.
- **Clean 1000 closes:** preserved — `_drop()`/`close()` use `_Session.close()`. The churn
  drops from ~1.5/s to a handful (one open per connection + reconnects on OBS restart).
- **obs-websocket support absent** (`_obs_ws is None`): `relay._obs is None`; every guard
  short-circuits to 503 exactly as today.
- **Feed release on stop** (`release_feed_inputs`) and **POV transform sync**
  (`set_scene_item_transform`) route through the control conn like any other call.

## Testing

- `_ObsConn` with a **fake session** scripted `alive→dead`: (a) N successful `run`s → **one**
  `_connect`; (b) a call that flips `alive=False` → drop + **one** reconnect + retry, result
  from the retry; (c) a request-level failure (returns a note, `alive=True`) → **no** retry,
  **no** reconnect; (d) `_ensure` returns None (OBS down) → `run` calls `func` with **no**
  `session` (per-call fallback) and never raises; (e) `close()` drops the session.
- `_ObsFacade`: (a) a `_SHOT_FN` routes through the shot holder, a control fn through the
  ctrl holder; (b) a non-routed attribute (`stream_kbps`, `STINT_SCENE`) passes through to
  the module untouched; (c) passthrough holders (kill-switch off) call the function with
  **no** `session` kwarg.
- `_Session.alive`: `send_json`/`next_json` set `alive=False` on a simulated socket error;
  a normal request leaves it True. (Fake socket, no real OBS — same pattern as the existing
  obs_ws unit tests.)
- One `session=`-passthrough test per representative function shape (a
  screenshot-style two-request fn and a single-request control fn): passing a live fake
  session skips `_connect`/`close` and returns the parsed value; omitting it is unchanged.
- Regression: the existing `tests/test_obsws.py` suite stays green untouched (default
  `session=None` path is byte-identical).

## Out of scope

- No connection **pool** beyond the two fixed roles (screenshots vs control) — YAGNI; the
  two-connection split already isolates the one latency risk.
- No obs-websocket **event subscriptions** / push model — the request/response model is
  unchanged; only the transport is reused.
- No change to the CLI or standalone `obs_ws` entry points (they keep connect-per-call).
- The other Suzuka items (#538 pre-event docs).
