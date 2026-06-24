# Director Panel — OBS Stream Start/Stop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a relay-mediated Start/Stop broadcast control to the Director Panel, driven through OBS-WebSocket, reflecting the real stream state.

**Architecture:** Same three-layer relay-mediated model as the existing OBS controls. `src/scripts/obs_ws.py` gains a `set_stream()` helper and surfaces stream state in `read_obs_state()`. The relay exposes `POST /obs/stream {on}` (auto director-gated by `console_policy`, which already maps every `/obs/*` path to DIRECTOR). The Director Panel renders a button driven by the existing 2-second `/obs/state` poll.

**Tech Stack:** Pure Python + stdlib (relay, obs_ws), vanilla HTML/JS (director panel). Tests are runnable stdlib scripts (no pytest).

## Global Constraints

- **Edit only under `src/`** (plus `tests/` and `src/docs/wiki/`). Never touch `dist/`/`runtime/`. (verbatim from CLAUDE.md)
- **English only** in all code, comments, docs, UI copy.
- **Pure Python + stdlib** — no new dependencies; no `.sh`/`.bat` files.
- `obs_ws.py` talks to OBS on loopback only — no `http_util`/User-Agent concern.
- **Idempotent, best-effort OBS helpers:** every `obs_ws` entry point returns `(ok, note)` / data, NEVER raises (matches the existing helpers).
- **Changed a UI surface → refresh its wiki screenshot in the SAME change:** the Director Panel changes, so `src/docs/wiki/images/director-panel.png` MUST be regenerated and committed in this work (Task 5), captured from a LOCAL dev build.
- Run `python3 tools/lint.py` and `python3 tools/run-tests.py` before finishing.

---

### Task 1: `obs_ws.set_stream()` — idempotent stream start/stop

**Files:**
- Modify: `src/scripts/obs_ws.py` (add `set_stream`, next to `set_input_mute` ~line 642)
- Test: `tests/test_obsws.py` (extend `_fake_obs_server` ~line 405; add tests near the `release_feed_inputs` end-to-end tests ~line 421)

**Interfaces:**
- Consumes: existing `_connect(host, port, password, timeout)`, `parse_stream_status(payload)`, `_Session.request(request_type, request_data)`.
- Produces: `set_stream(active, host="127.0.0.1", port=None, password=None, timeout=2.0) -> (ok: bool, note: str)`. `active=True` → ensure streaming; `active=False` → ensure stopped. Idempotent (no-op success when already in the requested state).

- [ ] **Step 1: Extend the fake OBS server with stream request handlers**

In `tests/test_obsws.py`, inside `_fake_obs_server`, add these `elif` branches just before the final `else: resp = {}` (around line 413):

```python
        elif rtype == "GetStreamStatus":
            resp = {"outputActive": state.get("stream_active", False),
                    "outputReconnecting": state.get("stream_reconnecting", False),
                    "outputTimecode": state.get("stream_timecode", "00:00:00.000"),
                    "outputBytes": state.get("output_bytes", 0)}
        elif rtype == "StartStream":
            state.setdefault("stream_calls", []).append("start")
            state["stream_active"] = True
            resp = {}
        elif rtype == "StopStream":
            state.setdefault("stream_calls", []).append("stop")
            state["stream_active"] = False
            resp = {}
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_obsws.py` (after `t_release_feed_inputs_wrong_password_is_note_not_crash`, ~line 450). This reuses the existing fake-server harness pattern:

```python
def _start_fake_obs(state):
    server_sock = socket.socket()
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]
    threading.Thread(target=_fake_obs_server,
                     args=(server_sock, "supersecret", state), daemon=True).start()
    return server_sock, port


def t_set_stream_starts_when_offline():
    state = {"stream_active": False}
    sock, port = _start_fake_obs(state)
    ok, note = m.set_stream(True, port=port, password="supersecret", timeout=5)
    assert ok and note == "", note
    assert state["stream_calls"] == ["start"]
    assert state["stream_active"] is True
    sock.close()


def t_set_stream_stops_when_live():
    state = {"stream_active": True}
    sock, port = _start_fake_obs(state)
    ok, note = m.set_stream(False, port=port, password="supersecret", timeout=5)
    assert ok and note == "", note
    assert state["stream_calls"] == ["stop"]
    assert state["stream_active"] is False
    sock.close()


def t_set_stream_is_idempotent_noop_when_already_live():
    state = {"stream_active": True}
    sock, port = _start_fake_obs(state)
    ok, note = m.set_stream(True, port=port, password="supersecret", timeout=5)
    assert ok and note == "", note
    assert "stream_calls" not in state          # no StartStream sent
    sock.close()


def t_set_stream_unreachable_is_note_not_crash():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]
    sock.close()
    ok, note = m.set_stream(True, port=free_port, password="x", timeout=0.5)
    assert ok is False
    assert note                                 # human-readable reason
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 tests/test_obsws.py`
Expected: FAIL — `AttributeError: module 'obs_ws' has no attribute 'set_stream'` (the runner aborts on the first missing attribute).

- [ ] **Step 4: Implement `set_stream`**

In `src/scripts/obs_ws.py`, add after `set_input_mute` (~line 642):

```python
def set_stream(active, host="127.0.0.1", port=None,
               password=None, timeout=2.0):
    """Start or stop the OBS stream output (best effort). `active` True ->
    StartStream, False -> StopStream. Idempotent: if OBS is ALREADY in the
    requested state, returns (True, "") without sending a start/stop, so a
    double-click or retry never surfaces OBS's "output already active" error.
    (ok, note); never raises."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    try:
        status = parse_stream_status(session.request("GetStreamStatus", {}))
        if status.get("stream_active") == bool(active):
            return True, ""                       # already in the desired state
        session.request("StartStream" if active else "StopStream", {})
        return True, ""
    except Exception as exc:                       # noqa: BLE001 — best-effort contract
        return False, str(exc) or exc.__class__.__name__
    finally:
        session.close()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 tests/test_obsws.py`
Expected: PASS (all functions, including the four new ones).

- [ ] **Step 6: Commit**

```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): idempotent set_stream() helper for OBS stream start/stop (#295)"
```

---

### Task 2: Surface stream state in `read_obs_state` + `parse_stream_status` timecode

**Files:**
- Modify: `src/scripts/obs_ws.py` (`parse_stream_status` ~line 436; `read_obs_state` ~line 644)
- Test: `tests/test_obsws.py`

**Interfaces:**
- Consumes: the fake-server `GetStreamStatus` handler added in Task 1.
- Produces: `parse_stream_status` now includes `"stream_timecode"`. `read_obs_state(...)` returns an extra key `"stream": {"active": bool|None, "reconnecting": bool|None, "timecode": str|None}` (or `None` if the `GetStreamStatus` request fails), without failing the rest of the read.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_obsws.py` (after the Task 1 tests):

```python
def t_parse_stream_status_includes_timecode():
    out = m.parse_stream_status({"outputActive": True,
                                 "outputReconnecting": False,
                                 "outputTimecode": "00:12:34.567"})
    assert out["stream_timecode"] == "00:12:34.567"
    assert out["stream_active"] is True


def t_read_obs_state_includes_stream():
    state = {"released": [], "stream_active": True,
             "stream_timecode": "01:02:03.000"}
    sock, port = _start_fake_obs(state)
    out, note = m.read_obs_state([("Stint", "Feed A")], ["Feed A"],
                                 port=port, password="supersecret", timeout=5)
    assert note == "", note
    assert out["stream"] == {"active": True, "reconnecting": False,
                             "timecode": "01:02:03.000"}
    sock.close()
```

(`_start_fake_obs` is defined in Task 1.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_obsws.py`
Expected: FAIL — `KeyError: 'stream_timecode'` / `KeyError: 'stream'`.

- [ ] **Step 3: Add `stream_timecode` to `parse_stream_status`**

In `src/scripts/obs_ws.py`, in `parse_stream_status` (~line 442), add the timecode key to the returned dict (place it after `stream_reconnecting`):

```python
        "stream_reconnecting": None if recon is None else bool(recon),
        "stream_timecode": p.get("outputTimecode"),
```

- [ ] **Step 4: Add the `stream` block to `read_obs_state`**

In `src/scripts/obs_ws.py`, in `read_obs_state`, replace the final `return` (~line 679):

```python
        return {"scene": scene, "sources": src_out, "audio": aud_out}, ""
```

with:

```python
        try:
            st = parse_stream_status(session.request("GetStreamStatus", {}))
            stream = {"active": st.get("stream_active"),
                      "reconnecting": st.get("stream_reconnecting"),
                      "timecode": st.get("stream_timecode")}
        except Exception:                         # noqa: BLE001 — per-item best effort
            stream = None
        return {"scene": scene, "sources": src_out,
                "audio": aud_out, "stream": stream}, ""
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 tests/test_obsws.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): expose live stream state (active/reconnecting/timecode) in read_obs_state (#295)"
```

---

### Task 3: Relay `POST /obs/stream` endpoint + director-gating assertion

**Files:**
- Modify: `src/relay/racecast-feeds.py` (OBS POST block, after the `/obs/audio` handler ~line 4755)
- Test: `tests/test_pov.py` (relay route test, near the `/preview` route tests ~line 403); `tests/test_console.py` (`t_obs_routes_require_director` ~line 157)

**Interfaces:**
- Consumes: `_obs_ws.set_stream(active)` from Task 1; the existing `make_handler(relay)` / `_serve(relay)` harness; the existing `body` JSON parse in the POST dispatch.
- Produces: `POST /obs/stream` with body `{"on": true|false}` → `{"ok": true}` (200), `{"ok": false, "error": "stream needs on"}` (400) when `on` is missing, `{"error": "obs unavailable"}` (503) when OBS is down. Reachable on the tailnet directly and over Funnel via `/console/obs/stream` (the console gate falls through to this root handler once `console_policy` ALLOWs the director).

- [ ] **Step 1: Add `["obs", "stream"]` to the director-gating test**

In `tests/test_console.py`, extend the tuple in `t_obs_routes_require_director` (line 157):

```python
def t_obs_routes_require_director():
    for seg in (["obs", "scene"], ["obs", "source"], ["obs", "audio"],
                ["obs", "state"], ["obs", "stream"]):
        assert cp.min_capability(seg) == cp.Requirement(cp.DIRECTOR, False), seg
```

- [ ] **Step 2: Write the failing relay route test**

In `tests/test_pov.py`, add `import json` to the imports (line 3 becomes
`import importlib.util, json, os, tempfile`), then add near the `/preview` tests (~line 433):

```python
def t_obs_stream_endpoint_starts_and_validates():
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], LOGDIR)

    class FakeObs:
        def __init__(self): self.calls = []
        def set_stream(self, active, **kw):
            self.calls.append(active); return (True, "")

    fo = FakeObs(); old = m._obs_ws; m._obs_ws = fo; srv = _serve(r)
    try:
        port = srv.server_address[1]
        url = f"http://127.0.0.1:{port}/obs/stream"
        req = urllib.request.Request(
            url, data=b'{"on": true}',
            headers={"Content-Type": "application/json"}, method="POST")
        body = urllib.request.urlopen(req, timeout=5).read()
        assert json.loads(body)["ok"] is True
        assert fo.calls == [True]
        # Missing "on" -> 400
        req = urllib.request.Request(
            url, data=b'{}', headers={"Content-Type": "application/json"},
            method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("expected HTTP 400")
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        srv.shutdown(); m._obs_ws = old


def t_obs_stream_503_when_obs_down():
    r = m.Relay(_FakeSource(_URLS8), [53001, 53002], LOGDIR)
    old = m._obs_ws; m._obs_ws = None; srv = _serve(r)
    try:
        port = srv.server_address[1]
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/obs/stream", data=b'{"on": true}',
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("expected HTTP 503")
        except urllib.error.HTTPError as e:
            assert e.code == 503
    finally:
        srv.shutdown(); m._obs_ws = old
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 tests/test_pov.py` and `python3 tests/test_console.py`
Expected: `test_pov.py` FAILs (the POST returns 404 — handler not added yet), so `json.loads(body)["ok"]` raises / the 400 path 404s. `test_console.py` FAILs on the new `["obs","stream"]` element only if the policy didn't match — it WILL pass already (the `p[0]=="obs"` rule covers it), confirming no policy change is needed.

- [ ] **Step 4: Add the `/obs/stream` handler**

In `src/relay/racecast-feeds.py`, insert this block immediately after the `/obs/audio` handler ends (after line ~4755, before `if p == ["obs", "state"]:`):

```python
                if p == ["obs", "stream"]:
                    if _obs_ws is None:
                        return self._send({"error": "obs unavailable"}, 503)
                    if "on" not in body:
                        return self._send({"ok": False,
                                           "error": "stream needs on"}, 400)
                    ok, note = _obs_ws.set_stream(bool(body.get("on")))
                    return self._send({"ok": True} if ok
                                      else {"ok": False, "error": note},
                                      200 if ok else 503)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 tests/test_pov.py` and `python3 tests/test_console.py`
Expected: PASS for both.

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py tests/test_console.py
git commit -m "feat(relay): POST /obs/stream director-gated start/stop endpoint (#295)"
```

---

### Task 4: Director Panel — Start/Stop button in Live Preview

**Files:**
- Modify: `src/director/director-panel.html` (Live Preview cap ~line 379; CSS in the `<style>` block; OBS helpers ~line 777; `obsStatePoll` ~line 840; wire-up near the bottom ~line 1749)
- Test: `tests/test_pov.py` (HTML-string assertion, mirroring the existing `hud.html` string tests)

**Interfaces:**
- Consumes: the existing `obsPost(path, body)` helper, `$()` selector, `log(msg, level)`, the `obsStatePoll()` poll loop, and the new `d.stream` field from Task 2/3.
- Produces: a `#obsStreamBtn` button reflecting `{active, reconnecting, timecode}`; an `obsStream(on)` helper; a confirm-guarded Stop.

- [ ] **Step 1: Write the failing HTML-string test**

In `tests/test_pov.py`, add:

```python
def t_director_panel_has_stream_button():
    path = os.path.join(ROOT, "src", "director", "director-panel.html")
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    assert 'id="obsStreamBtn"' in html
    assert 'obsPost("stream"' in html
    assert "End the live broadcast" in html          # Stop is confirm-guarded
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_pov.py`
Expected: FAIL — `assert 'id="obsStreamBtn"' in html`.

- [ ] **Step 3: Add the button markup**

In `src/director/director-panel.html`, change the Live Preview cap line (~line 379) from:

```html
    <div class="cap">Live Preview <button class="k" id="pvToggle">SHOW</button></div>
```

to:

```html
    <div class="cap">Live Preview
      <button class="k" id="pvToggle">SHOW</button>
      <button class="k stream" id="obsStreamBtn" hidden>OFFLINE</button></div>
```

- [ ] **Step 4: Add the button CSS**

In the `<style>` block (anywhere among the button rules), add:

```css
#obsStreamBtn.live  { background:#c0392b; color:#fff; border-color:#c0392b; }
#obsStreamBtn.recon { background:#d68910; color:#fff; border-color:#d68910; }
```

- [ ] **Step 5: Add the `obsStream` helper and renderer**

In `src/director/director-panel.html`, after the `obsMute` definition (~line 780), add:

```javascript
const obsStream = (on) => obsPost("stream", {on});

/* Reflect the real OBS stream state on the button. `s` is d.stream from
   /obs/state ({active,reconnecting,timecode}) or null when OBS is unreachable. */
function renderStreamBtn(s){
  const b = $("#obsStreamBtn");
  b.hidden = false;
  if (!s){ b.textContent = "STREAM ?"; b.className = "k stream"; b.dataset.live = ""; return; }
  if (s.reconnecting){
    b.textContent = "RECONNECTING…"; b.className = "k stream recon"; b.dataset.live = "1";
  } else if (s.active){
    const tc = s.timecode ? " " + s.timecode.split(".")[0] : "";
    b.textContent = "● LIVE" + tc; b.className = "k stream live"; b.dataset.live = "1";
  } else {
    b.textContent = "OFFLINE — GO LIVE"; b.className = "k stream"; b.dataset.live = "";
  }
}
```

- [ ] **Step 6: Render on each poll + handle OBS-down**

In `obsStatePoll()`, in the early-return branch when `/obs/state` fails (~line 841), change:

```javascript
    if (!d.ok){ obsLed("err"); return; }
```

to:

```javascript
    if (!d.ok){ obsLed("err"); renderStreamBtn(null); return; }
```

Then, just after `programScene = obsState.scene;` (~line 848), add:

```javascript
    renderStreamBtn(d.stream);
```

- [ ] **Step 7: Wire the click handler**

Near the bottom of the script, just before the `obsStatePoll(); setInterval(obsStatePoll, 2000);` line (~line 1749), add:

```javascript
$("#obsStreamBtn").addEventListener("click", async ()=>{
  const live = $("#obsStreamBtn").dataset.live === "1";
  if (live && !confirm("End the live broadcast?")) return;
  const d = await obsStream(!live);
  if (!d.ok) log("OBS stream: " + (d.error || "failed"), "err");
  obsStatePoll();
});
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `python3 tests/test_pov.py`
Expected: PASS.

- [ ] **Step 9: Manual UAT (local dev build)**

Use the `racecast-local-uat` skill to stand up the real-league dev build (relay + director panel) on a free port, open `/panel` (or `/console/panel`), and verify: button shows OFFLINE; clicking goes LIVE with a running timecode; clicking again prompts the confirm and stops; killing OBS shows `STREAM ?`. (No commit from this step.)

- [ ] **Step 10: Commit**

```bash
git add src/director/director-panel.html tests/test_pov.py
git commit -m "feat(panel): Start/Stop OBS stream button in the Director Panel Live Preview (#295)"
```

---

### Task 5: Refresh the Director Panel wiki screenshot + docs

**Files:**
- Replace: `src/docs/wiki/images/director-panel.png`
- Modify: the Director-Panel wiki page under `src/docs/wiki/` (the page that documents the panel's OBS controls)

**Interfaces:** none (docs/assets only).

- [ ] **Step 1: Locate the wiki page that documents the panel**

Run: `grep -rl "director-panel.png\|Director Panel" src/docs/wiki/`
Expected: the Markdown page that embeds `images/director-panel.png`.

- [ ] **Step 2: Add a sentence describing the Start/Stop control**

In that page, near the OBS-control description, add one English sentence, e.g.:
"The **Live Preview** header carries a broadcast button: it shows **OFFLINE** when the stream is down and **● LIVE HH:MM:SS** while on air; starting is one click, stopping asks for confirmation. It drives OBS over the same relay-mediated OBS-WebSocket path as the scene/source/audio controls (no OBS IP/port/password needed)."

- [ ] **Step 3: Recapture the screenshot from a LOCAL dev build**

Run `racecast ui`/the relay straight from `src/` (no `VERSION` file) per the screenshot rule, open the Director Panel with the new button visible (stream OFFLINE state), and take an **element** screenshot of the panel via the Playwright MCP. Save it over `src/docs/wiki/images/director-panel.png` (same framing as the existing image).

- [ ] **Step 4: Verify the image updated**

Run: `git status --short src/docs/wiki/images/director-panel.png`
Expected: the file shows as modified.

- [ ] **Step 5: Commit**

```bash
git add src/docs/wiki/images/director-panel.png src/docs/wiki/
git commit -m "docs(wiki): document + screenshot the Director Panel stream Start/Stop button (#295)"
```

---

### Final verification

- [ ] **Run the full suite and lint**

Run: `python3 tools/lint.py && python3 tools/run-tests.py`
Expected: lint clean; all tests PASS.

- [ ] **Build verify (closest thing to CI)**

Run: `python3 tools/build.py`
Expected: the verify step passes (tokenization, no secrets, no shell scripts, preflight present).
