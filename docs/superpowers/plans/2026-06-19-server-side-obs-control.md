# Server-side OBS control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the Director Panel's OBS control (scene switch, source visibility, audio)
from the browser's direct obs-websocket connection to relay HTTP endpoints, so the panel
works fully over the public Funnel with no OBS credentials at the client.

**Architecture:** The relay already speaks obs-websocket to its **local** OBS
(`src/scripts/obs_ws.py`: `set_scene_item_enabled`, `get_program_screenshot`, `probe`,
`_connect` with the OBS password auto-discovered locally). Add a few same-style helpers,
expose **named intent** endpoints `/obs/{scene,source,audio,state}` (root paths; reached
over Funnel only via the director-gated `_console_gate` fall-through), and rewire the
panel's `obs.call(...)` to `fetch("/obs/...")`. The program monitor already uses the
relay's `/preview/program` — unchanged. Spec:
`docs/superpowers/specs/2026-06-19-server-side-obs-control-design.md`.

**Tech Stack:** Pure Python stdlib (relay + obs-websocket v5 client), vanilla HTML/JS
(panel), runnable-script tests (no pytest).

## Global Constraints

- **Edit only under `src/`** (+ `tests/`, `docs/`). `dist/`/`runtime/` are generated.
- **All scripts and docs English only.**
- **Relay + obs_ws stay stdlib-only.** New obs_ws helpers mirror the existing best-effort
  contract **exactly**: `session, note = _connect(...)`; on `session is None` return the
  failure tuple; do the `session.request(...)`; `except Exception: return <fail>, str(exc)
  or exc.__class__.__name__`; `finally: session.close()`. **Never raise.**
- **Named intent endpoints only** — `/obs/scene`, `/obs/source`, `/obs/audio`,
  `/obs/state`. **No** generic OBS-request passthrough. A compromised director token can
  trigger only these broadcast ops.
- **Director-gated, no step-up:** `console_policy` maps `obs → Requirement(DIRECTOR, False)`.
- **Remove the browser→OBS-WebSocket path entirely** (both `/panel` and `/console/panel`):
  drop the `obs-websocket-js` CDN script, the OBS IP/Port/Password card, `new
  OBSWebSocket()`, `obs.connect`. The relay talks to its **local** OBS (127.0.0.1:4455,
  password auto-discovered) — the panel never sends an OBS IP/port/password.
- **The program monitor is already server-side** (`/preview/program` via `RC_API`) — do
  NOT change it; there is **no** `/obs/program` endpoint.
- **No machine paths / real IPs / secrets** in committed files (Tailscale test IPs
  `100.64.0.0/10`). The panel must not embed an OBS password.
- **Wiki screenshot:** the panel loses the OBS connect card → `director-panel.png` MUST be
  refreshed in the same change (dev build, Playwright; controller step).
- Local gate green before each PR: `python3 tools/run-tests.py`, `python3 tools/lint.py`,
  `python3 tools/build.py` (exit 0). Relay change ⇒ also `python3 tests/test_pov.py`.

---

### Task 1: `obs_ws.py` control helpers + state reader

**Files:**
- Modify: `src/scripts/obs_ws.py` — add `set_current_program_scene`, `set_input_volume`,
  `set_input_mute`, `read_obs_state` (next to `get_program_screenshot`, ~line 495).
- Test: `tests/test_obsws.py`.

**Interfaces:**
- Consumes: `_connect(host, port, password, timeout)` → `(session, note)`; the
  `OBSSession.request(request_type, request_data)` method; existing `DEFAULT_PORT`.
- Produces: `set_current_program_scene(scene, …) → (ok, note)`;
  `set_input_volume(input_name, volume_db, …) → (ok, note)`;
  `set_input_mute(input_name, muted, …) → (ok, note)`;
  `read_obs_state(sources, inputs, …) → (state|None, note)` where `sources` =
  `[(scene, source), …]`, `inputs` = `[name, …]`, and `state` =
  `{"scene", "sources":[{"scene","source","enabled"}], "audio":[{"input","muted","volumeDb"}]}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_obsws.py` (append; module alias
  is the one the file already uses — match it). Add a minimal fake session and monkeypatch
  `_connect`, mirroring how the file tests session-driven helpers if it already does;
  otherwise add this `_FakeSession`:

```python
class _FakeSession:
    def __init__(self, responses=None):
        self.sent = []
        self._responses = responses or {}
    def request(self, request_type, request_data=None):
        self.sent.append((request_type, request_data or {}))
        return self._responses.get(request_type, {})
    def close(self):
        self.sent.append(("close", {}))


def _patch_connect(monkeypatch_target, session, note=""):
    # returns a callable suitable for replacing m._connect
    return lambda host, port, password, timeout: (session, note)


def t_set_current_program_scene_sends_request():
    sess = _FakeSession()
    orig, m._connect = m._connect, lambda *a, **k: (sess, "")
    try:
        ok, note = m.set_current_program_scene("Stint")
    finally:
        m._connect = orig
    assert ok is True and note == ""
    assert ("SetCurrentProgramScene", {"sceneName": "Stint"}) in sess.sent


def t_set_input_volume_and_mute():
    sess = _FakeSession()
    orig, m._connect = m._connect, lambda *a, **k: (sess, "")
    try:
        assert m.set_input_volume("Mic", -6.0)[0] is True
        assert m.set_input_mute("Mic", True)[0] is True
    finally:
        m._connect = orig
    assert ("SetInputVolume", {"inputName": "Mic", "inputVolumeDb": -6.0}) in sess.sent
    assert ("SetInputMute", {"inputName": "Mic", "inputMuted": True}) in sess.sent


def t_read_obs_state_batches_one_session():
    sess = _FakeSession({
        "GetCurrentProgramScene": {"currentProgramSceneName": "Stint"},
        "GetSceneItemId": {"sceneItemId": 7},
        "GetSceneItemEnabled": {"sceneItemEnabled": True},
        "GetInputMute": {"inputMuted": False},
        "GetInputVolume": {"inputVolumeDb": -3.0},
    })
    orig, m._connect = m._connect, lambda *a, **k: (sess, "")
    try:
        state, note = m.read_obs_state([("Stint", "HUD")], ["Mic"])
    finally:
        m._connect = orig
    assert note == "" and state["scene"] == "Stint"
    assert state["sources"] == [{"scene": "Stint", "source": "HUD", "enabled": True}]
    assert state["audio"] == [{"input": "Mic", "muted": False, "volumeDb": -3.0}]


def t_obs_helpers_unreachable_return_failure_not_raise():
    orig, m._connect = m._connect, lambda *a, **k: (None, "OBS not running")
    try:
        assert m.set_current_program_scene("Stint") == (False, "OBS not running")
        assert m.read_obs_state([], []) == (None, "OBS not running")
    finally:
        m._connect = orig
```

- [ ] **Step 2: Run — verify they fail**

Run: `python3 tests/test_obsws.py`
Expected: FAIL — `AttributeError: module has no attribute 'set_current_program_scene'`.

- [ ] **Step 3: Implement the helpers** in `src/scripts/obs_ws.py` (mirror
  `get_program_screenshot`'s structure exactly):

```python
def set_current_program_scene(scene, host="127.0.0.1", port=None,
                              password=None, timeout=2.0):
    """Switch the OBS program scene (best effort). (ok, note); never raises."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    try:
        session.request("SetCurrentProgramScene", {"sceneName": scene})
        return True, ""
    except Exception as exc:                          # noqa: BLE001 — best-effort contract
        return False, str(exc) or exc.__class__.__name__
    finally:
        session.close()


def set_input_volume(input_name, volume_db, host="127.0.0.1", port=None,
                     password=None, timeout=2.0):
    """Set an OBS audio input volume in dB (best effort). (ok, note)."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    try:
        session.request("SetInputVolume",
                        {"inputName": input_name, "inputVolumeDb": float(volume_db)})
        return True, ""
    except Exception as exc:                          # noqa: BLE001 — best-effort contract
        return False, str(exc) or exc.__class__.__name__
    finally:
        session.close()


def set_input_mute(input_name, muted, host="127.0.0.1", port=None,
                   password=None, timeout=2.0):
    """Set an OBS audio input mute state (best effort). (ok, note)."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    try:
        session.request("SetInputMute",
                        {"inputName": input_name, "inputMuted": bool(muted)})
        return True, ""
    except Exception as exc:                          # noqa: BLE001 — best-effort contract
        return False, str(exc) or exc.__class__.__name__
    finally:
        session.close()


def read_obs_state(sources, inputs, host="127.0.0.1", port=None,
                   password=None, timeout=2.0):
    """One-session panel-refresh snapshot: current program scene + the enabled state
    of each (scene, source) + the mute/volume of each audio input. `sources` =
    [(scene, source), …]; `inputs` = [name, …]. Returns (state, "") or (None, note);
    a per-item OBS error leaves that item's fields None rather than failing the whole
    read. Best effort — never raises."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return None, note
    try:
        cur = session.request("GetCurrentProgramScene", {})
        scene = cur.get("currentProgramSceneName") or cur.get("sceneName")
        src_out = []
        for sc, src in sources:
            try:
                sid = session.request(
                    "GetSceneItemId",
                    {"sceneName": sc, "sourceName": src}).get("sceneItemId")
                enabled = session.request(
                    "GetSceneItemEnabled",
                    {"sceneName": sc, "sceneItemId": sid}).get("sceneItemEnabled")
            except Exception:                         # noqa: BLE001 — per-item best effort
                enabled = None
            src_out.append({"scene": sc, "source": src, "enabled": enabled})
        aud_out = []
        for name in inputs:
            try:
                muted = session.request(
                    "GetInputMute", {"inputName": name}).get("inputMuted")
                vol = session.request(
                    "GetInputVolume", {"inputName": name}).get("inputVolumeDb")
            except Exception:                         # noqa: BLE001 — per-item best effort
                muted, vol = None, None
            aud_out.append({"input": name, "muted": muted, "volumeDb": vol})
        return {"scene": scene, "sources": src_out, "audio": aud_out}, ""
    except Exception as exc:                          # noqa: BLE001 — best-effort contract
        return None, str(exc) or exc.__class__.__name__
    finally:
        session.close()
```

- [ ] **Step 4: Run — verify they pass**

Run: `python3 tests/test_obsws.py` → PASS (`ALL PASS`).

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py` → clean.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): obs_ws scene/audio control + batched state-read helpers"
```

---

### Task 2: Relay `/obs/*` endpoints + console policy

**Files:**
- Modify: `src/relay/racecast-feeds.py` — add `["obs", …]` POST routes in `do_POST`,
  placed BEFORE the `if not setup_ctl:` 404 guard (OBS routes don't need `setup_ctl`).
- Modify: `src/scripts/console_policy.py` — add the `obs → Requirement(DIRECTOR, False)`
  row in the director block.
- Test: `tests/test_console_gate.py` (director-gated `/console/obs/*`), `tests/test_console.py`
  (the policy row), `tests/test_pov.py` (relay regression).

**Interfaces:**
- Consumes: `_obs_ws` (the relay's `import obs_ws as _obs_ws`, may be `None`), the Task 1
  helpers, the parsed `body` dict in `do_POST`, `_console_gate` (already authorizes
  `["obs", …]` once the policy row exists).
- Produces: `POST /obs/scene {scene}`, `POST /obs/source {scene,source,on}`,
  `POST /obs/audio {input, db|mute}`, `POST /obs/state {sources:[{scene,source}], inputs:[name]}`.

- [ ] **Step 1: Add the policy row test** in `tests/test_console.py` (match the file's
  existing `min_capability`/`decide` test idiom):

```python
def t_obs_routes_require_director():
    from console_policy import min_capability, Requirement, DIRECTOR
    for seg in (["obs", "scene"], ["obs", "source"], ["obs", "audio"], ["obs", "state"]):
        assert min_capability(seg) == Requirement(DIRECTOR, False), seg
```

- [ ] **Step 2: Add the gate tests** in `tests/test_console_gate.py` (reuse `_serve`,
  `_tok`, `_get` and add a POST helper if the file lacks one — match the existing style;
  `carol`=producer→also implies… use a DIRECTOR token: `bob`=director). Note `_get`/POST
  needs to send a JSON body for these POST routes — mirror how other POST gate tests do it,
  or add a `_post(port, path, token, secret, body)` helper:

```python
def t_console_obs_scene_requires_director():
    srv = _serve(); port = srv.server_address[1]
    try:
        assert _post(port, "/console/obs/scene", body={"scene": "Stint"})[0] == 401   # no token
        assert _post(port, "/console/obs/scene", _tok("carol"),                       # producer, not director
                     body={"scene": "Stint"})[0] == 403
        code, _ = _post(port, "/console/obs/scene", _tok("bob"), body={"scene": "Stint"})
        assert code in (200, 503), code   # director allowed (200 ok, or 503 when no OBS in the test)
    finally:
        srv.shutdown()
```

> `bob` is the director fixture, `carol` the producer (`_Crew([("Bob",True,False),("Carol",False,True)])`).
> With no OBS running in the test harness, the relay returns 503 (obs unavailable) — the
> point is the **gate** (401/403/allowed), not a live OBS. Assert `in (200, 503)` for the
> allowed case.

- [ ] **Step 3: Run — verify they fail**

Run: `python3 tests/test_console.py` and `python3 tests/test_console_gate.py`
Expected: FAIL — policy returns `None` for `obs`; gate 404s `/console/obs/*`.

- [ ] **Step 4: Add the policy row** in `src/scripts/console_policy.py` (in the director
  block, e.g. after the `pov` row):

```python
    if p and p[0] == "obs":                     # relay-mediated OBS control (scene/source/audio/state)
        return Requirement(DIRECTOR, False)
```

- [ ] **Step 5: Add the relay routes** in `do_POST`, BEFORE the `if not setup_ctl:` guard
  (~line 3520). Mirror the `/preview/program` 503-when-`_obs_ws is None` pattern:

```python
                if p == ["obs", "scene"]:
                    if _obs_ws is None:
                        return self._send({"error": "obs unavailable"}, 503)
                    ok, note = _obs_ws.set_current_program_scene(body.get("scene"))
                    return self._send({"ok": True} if ok
                                      else {"ok": False, "error": note}, 200 if ok else 503)
                if p == ["obs", "source"]:
                    if _obs_ws is None:
                        return self._send({"error": "obs unavailable"}, 503)
                    ok, note = _obs_ws.set_scene_item_enabled(
                        body.get("scene"), body.get("source"), bool(body.get("on")))
                    return self._send({"ok": True} if ok
                                      else {"ok": False, "error": note}, 200 if ok else 503)
                if p == ["obs", "audio"]:
                    if _obs_ws is None:
                        return self._send({"error": "obs unavailable"}, 503)
                    inp = body.get("input")
                    if "mute" in body:
                        ok, note = _obs_ws.set_input_mute(inp, bool(body.get("mute")))
                    elif "db" in body:
                        ok, note = _obs_ws.set_input_volume(inp, body.get("db"))
                    else:
                        return self._send({"ok": False, "error": "audio needs db or mute"}, 400)
                    return self._send({"ok": True} if ok
                                      else {"ok": False, "error": note}, 200 if ok else 503)
                if p == ["obs", "state"]:
                    if _obs_ws is None:
                        return self._send({"error": "obs unavailable"}, 503)
                    sources = [(s.get("scene"), s.get("source"))
                               for s in (body.get("sources") or [])]
                    state, note = _obs_ws.read_obs_state(sources, body.get("inputs") or [])
                    if state is None:
                        return self._send({"ok": False, "error": note}, 503)
                    return self._send({"ok": True, **state})
```

- [ ] **Step 6: Run — verify they pass**

Run: `python3 tests/test_console.py`, `python3 tests/test_console_gate.py`,
`python3 tests/test_pov.py` → all `ALL PASS`.

- [ ] **Step 7: Lint**

Run: `python3 tools/lint.py` → clean.

- [ ] **Step 8: Commit**

```bash
git add src/relay/racecast-feeds.py src/scripts/console_policy.py \
        tests/test_console.py tests/test_console_gate.py
git commit -m "feat(relay): /obs/{scene,source,audio,state} director-gated OBS control"
```

---

### Task 3: Director Panel rewire + screenshot

**Files:**
- Modify: `src/director/director-panel.html` — remove the browser→OBS-WS path; route OBS
  control through the new relay endpoints.
- Refresh: `src/docs/wiki/images/director-panel.png` (controller step — Step 5).

**Interfaces:**
- Consumes: `/obs/{scene,source,audio,state}` (Task 2); the existing `RC_API()` base shim
  and the panel's `fetch`/`relayPoll` helpers.
- Produces: no API; the rewired panel + the refreshed screenshot.

- [ ] **Step 1: Remove the browser→OBS-WS surface.** Delete: the `<script
  src="…obs-websocket-js…">` tag (~line 29); the OBS **IP / Port / Password** card (the
  `#ip`/`#port`/`#pw` `<div class="fld …">` block, ~lines 312–314) and its surrounding
  connect controls; `const obs = new OBSWebSocket()` (~line 542); the `obs.connect(...)`
  call + Connect handler (~line 969). Update the "Ready…" log hint (~line 436) to drop
  "enter the Producer's Tailscale IP + OBS WebSocket password and Connect" — OBS control
  now needs nothing from the operator.

- [ ] **Step 2: Add fetch-based OBS helpers** (near the panel's other `fetch` helpers).
  All use `RC_API(...)` so they resolve under `/console` and at root:

```javascript
async function obsPost(path, body){
  const r = await fetch(RC_API("/obs/" + path), {method:"POST", cache:"no-store",
    headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
  const d = await r.json().catch(()=>({ok:false,error:"bad response"}));
  obsLed(r.ok && d.ok ? "ok" : "err");
  return d;
}
const obsScene  = (scene)            => obsPost("scene",  {scene});
const obsSource = (scene,source,on)  => obsPost("source", {scene, source, on});
const obsVol    = (input,db)         => obsPost("audio",  {input, db});
const obsMute   = (input,muted)      => obsPost("audio",  {input, mute:muted});
```

- [ ] **Step 3: Rewire every `obs.call(...)` site** (~lines 607–786, 694–695, 704–708,
  722–724) to the helpers:
  - `SetCurrentProgramScene{sceneName}` → `obsScene(name)`.
  - `GetSceneItemId`+`SetSceneItemEnabled` → `obsSource(scene, source, on)` (send explicit
    `on`; for a **toggle** button, send `on = !<last-known-enabled>` from the latest
    `/obs/state` snapshot the panel holds — do not round-trip a read first).
  - `SetInputVolume{inputVolumeDb}` → `obsVol(input, db)`; `SetInputMute`/`ToggleInputMute`
    → `obsMute(input, muted)` (toggle sends `!<last-known-muted>`).

- [ ] **Step 4: Rewire the state poll.** Replace `refresh()` (~line 743, the `obs.call`
  reads of current scene / item-enabled / mute / volume) with a single
  `obsPost("state", {sources:[…], inputs:[…]})` built from the panel's button config
  (the `BTN`/scenes/vis/graphics/audio maps already list every `{scene, source}` and audio
  input). Render the active-scene highlight, the source-enabled LEDs, and the mute/volume
  rows from the returned snapshot. Drive the OBS **LED** from the call success
  (`obsLed("ok"/"err")`), replacing the old WS-connection LED. Keep the 2 s poll
  (`setInterval`). Leave the program monitor (`/preview/program`, ~lines 1499–1531)
  **unchanged**.

- [ ] **Step 5: Local smoke + gate.**

Run: `python3 tools/run-tests.py` (ALL TEST FILES PASS), `python3 tools/lint.py` (clean),
`python3 tools/build.py` (exit 0). Optionally open the panel from a dev relay
(`python3 src/racecast.py relay run` then `/panel`) to confirm no JS console errors and the
OBS card is gone.

- [ ] **Step 6: Refresh `director-panel.png` (CONTROLLER step).** Capture from a **local
  dev build** (no `VERSION`), driving the panel with the Playwright MCP. The panel needs
  relay data — either run a dev relay and open `/panel`, or open the page and route-mock
  the relay polls with **synthetic** data (no real IPs/streamer names/OBS host). Take a
  screenshot framed like the existing `director-panel.png` (inspect it first). Verify the
  OBS IP/Port/Password card is gone and there are no real IPs/secrets. Save over
  `src/docs/wiki/images/director-panel.png`.

- [ ] **Step 7: Commit**

```bash
git add src/director/director-panel.html src/docs/wiki/images/director-panel.png
git commit -m "feat(panel): relay-mediated OBS control (drop browser obs-websocket) + director-panel.png"
```

---

### Task 4: Docs + spec + final gate

**Files:**
- Modify: `CLAUDE.md` — the Director Panel description: OBS control is now relay-mediated
  (`/obs/{scene,source,audio,state}`, director-gated), the panel needs no OBS
  IP/port/password, and it therefore works fully over Funnel (`/console/panel`).
- Modify: the relevant wiki page(s) describing the panel / Funnel access (e.g.
  `Commentator-Cockpit.md` console section and/or the Director-Panel page) — note the
  credential-free, Funnel-complete panel; OBS-WebSocket never leaves the producer machine.
- Create/commit: this plan doc **and** the spec
  `docs/superpowers/specs/2026-06-19-server-side-obs-control-design.md` (currently
  untracked) — `git add` both.

**Interfaces:** none (docs only).

- [ ] **Step 1: Update `CLAUDE.md`** — concise, matching the file's prose: the panel's OBS
  control moved server-side; routes `/obs/scene|source|audio|state` (director); no OBS
  credentials at the client; OBS-WebSocket stays local; the panel is now fully usable over
  Funnel. Note `/preview/program` already served the monitor.

- [ ] **Step 2: Update the wiki** — a short note on the credential-free, Funnel-complete
  Director Panel and the security posture (OBS-WS never exposed/funnelled; named
  director-gated OBS endpoints). English; no real hosts/secrets.

- [ ] **Step 3: Full local gate**

Run: `python3 tools/run-tests.py` (ALL TEST FILES PASS), `python3 tools/lint.py` (clean),
`python3 tools/build.py` (exit 0), `python3 tests/test_pov.py` (ALL PASS).

- [ ] **Step 4: Commit (docs + spec + plan)**

```bash
git add docs/superpowers/specs/2026-06-19-server-side-obs-control-design.md \
        docs/superpowers/plans/2026-06-19-server-side-obs-control.md \
        CLAUDE.md src/docs/wiki/*.md
git commit -m "docs(obs): relay-mediated OBS control + server-side OBS design/spec"
```

---

## Self-Review

- **Spec coverage:** relay-mediated OBS control ✓ (Task 2); named intent endpoints
  scene/source/audio/state ✓; director-gated, no step-up ✓ (Task 2 policy row);
  browser→OBS-WS fully removed incl. IP/port/pw card + CDN ✓ (Task 3); program monitor
  unchanged (`/preview/program`) ✓; `director-panel.png` refreshed ✓ (Task 3 Step 6);
  docs + spec committed ✓ (Task 4).
- **Security:** OBS password never leaves the producer machine; OBS-WS never funnelled;
  bounded surface (4 named ops, director-gated); only `/console` mounted (root `/obs/*`
  tailnet-only, reached publicly only via the director gate).
- **No new `/obs/program`** — the monitor already uses `/preview/program` (any-auth,
  console-allowed); confirmed in Task 3 Step 4 (left unchanged).
- **Type consistency:** obs_ws helpers all return `(ok, note)` except `read_obs_state` →
  `(state|None, note)`; the relay routes map those to `{ok, …}`/`{ok:false, error}` with
  200/503/400; the panel's `obsPost` reads `d.ok`. `read_obs_state(sources, inputs)`
  signature matches the relay's `[(scene,source)]` / `[name]` construction.
- **Best-effort contract preserved** — every obs_ws helper mirrors `get_program_screenshot`
  (never raises; `_connect` None → failure tuple).
```
