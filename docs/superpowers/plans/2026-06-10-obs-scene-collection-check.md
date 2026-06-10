# OBS Scene Collection Check & Switch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect when OBS has the wrong scene collection active and let the producer switch to `IRO Endurance` with one explicit action — from the CLI (`iro obs collection [set]`), the event readiness report, and a Switch button in the Control Center.

**Architecture:** Add a pure classifier + two best-effort obs-websocket I/O calls to `src/scripts/obs_ws.py` (mirroring the existing `refresh_browser_inputs`/`release_feed_inputs` contract: never raise, return a note). `event start` and `event status` warn only; the switch is a discrete op so it works identically in CLI and the stdin-less Control Center jobs. The UI surfaces a live, on-demand check in the Apps-view OBS area.

**Tech Stack:** Pure Python 3 stdlib (no deps), the repo's runnable-script test files (no pytest), the existing obs-websocket v5 client and fake-server test harness, vanilla-JS Control Center.

**Spec:** `docs/superpowers/specs/2026-06-10-obs-scene-collection-check-design.md`

---

## File Structure

- `src/scripts/obs_ws.py` — **modify.** Add `EXPECTED_SCENE_COLLECTION`, pure `scene_collection_status()`, and best-effort `get_scene_collection()` / `set_scene_collection()`.
- `tests/test_obsws.py` — **modify.** Pure-logic tests + end-to-end tests against the fake OBS server (extended to answer the two new request types).
- `src/scripts/event.py` — **modify.** Add `classify_scene_collection()` (WARN-level Result).
- `tests/test_event.py` — **modify.** Tests for each classify branch.
- `src/iro.py` — **modify.** `OBS_VERBS`, `obs_collection_cmd()`, dispatch entry, `_check_scene_collection()` in `event_start`, collection line in `event_status`, `obs_collection_data()` UI provider + ctx entry.
- `src/ui/ui_ops.py` — **modify.** Register the `obs-collection-set` op.
- `tests/test_ui_ops.py` — **modify.** op-argv test + `obs_collection_data()` seam tests.
- `src/ui/ui_server.py` — **modify.** `GET /api/obs-collection` route + ctx docstring.
- `src/ui/control-center.html` — **modify.** Collection status line + Switch button + fetch hook + confirm text + post-job refresh.
- `CLAUDE.md`, `README.md` — **modify.** Document `iro obs collection [set]`.

---

## Task 1: Pure scene-collection classifier in obs_ws.py

**Files:**
- Modify: `src/scripts/obs_ws.py` (add near the other pure helpers, after `feed_state_intents`, around line 55)
- Test: `tests/test_obsws.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_obsws.py` (before the `_raises` helper near line 433):

```python
# --------------------------------------------------------------------------
# Pure scene-collection classifier — scene_collection_status
# --------------------------------------------------------------------------
def t_scene_collection_status_match():
    s = m.scene_collection_status("IRO Endurance", ["IRO Endurance", "Other"])
    assert s == {"current": "IRO Endurance", "expected": "IRO Endurance",
                 "available": ["IRO Endurance", "Other"], "match": True,
                 "expected_present": True, "renamed_variant": None}


def t_scene_collection_status_wrong_but_present():
    s = m.scene_collection_status("Other", ["IRO Endurance", "Other"])
    assert s["match"] is False
    assert s["expected_present"] is True
    assert s["renamed_variant"] is None


def t_scene_collection_status_renamed_variant():
    s = m.scene_collection_status("IRO Endurance 2", ["IRO Endurance 2", "Scene"])
    assert s["match"] is False
    assert s["expected_present"] is False
    assert s["renamed_variant"] == "IRO Endurance 2"


def t_scene_collection_status_expected_absent():
    s = m.scene_collection_status("Scene", ["Scene", "Foo"])
    assert s["match"] is False
    assert s["expected_present"] is False
    assert s["renamed_variant"] is None


def t_scene_collection_status_empty_current():
    s = m.scene_collection_status(None, [])
    assert s["match"] is False
    assert s["expected_present"] is False
    assert s["renamed_variant"] is None
    assert s["current"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_obsws.py`
Expected: `AttributeError: module 'obs_ws' has no attribute 'scene_collection_status'`

- [ ] **Step 3: Implement the constant + pure function**

In `src/scripts/obs_ws.py`, add the constant beside the other module constants (after `FEED_SOURCES`, line 40):

```python
# The scene collection the broadcast assumes. Mirrors the "name" field of
# src/obs/IRO_Endurance.json (the name OBS shows after importing the localized
# collection). Keep the two in sync. Not a secret, so the no-hardcoding rule
# does not apply; not parsed at runtime because the file is renamed + tokenized
# in the shipped package and bundled differently when frozen.
EXPECTED_SCENE_COLLECTION = "IRO Endurance"
```

Add the pure function after `feed_state_intents` (after line 54):

```python
def scene_collection_status(current, available, expected=EXPECTED_SCENE_COLLECTION):
    """Pure: classify the active OBS scene collection. `current` is OBS's
    currentSceneCollectionName; `available` is the full list it reported.
    Returns a dict (see keys below). The only "correct" state is match=True;
    renamed_variant flags a non-exact "IRO Endurance*" (e.g. an import-renamed
    'IRO Endurance 2'), which we never switch to automatically."""
    available = list(available)
    renamed = next((n for n in available
                    if n != expected and isinstance(n, str)
                    and n.startswith(expected)), None)
    return {"current": current, "expected": expected, "available": available,
            "match": current == expected,
            "expected_present": expected in available,
            "renamed_variant": renamed}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_obsws.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): pure scene-collection classifier (#36)"
```

---

## Task 2: Best-effort get/set scene collection (obs-websocket I/O)

**Files:**
- Modify: `src/scripts/obs_ws.py` (add after `reflect_feed_state`, end of file)
- Test: `tests/test_obsws.py` (extend the fake server + add end-to-end tests)

- [ ] **Step 1: Extend the fake OBS server to answer the two new request types**

In `tests/test_obsws.py`, inside `_fake_obs_server`'s request loop, add two `elif` branches alongside the existing ones (after the `GetInputList` branch, before `elif rtype == "PressInputPropertiesButton"`, around line 340):

```python
        if rtype == "GetSceneCollectionList":
            resp = {"currentSceneCollectionName": state.get("current_collection", ""),
                    "sceneCollections": state.get("collections", [])}
        elif rtype == "SetCurrentSceneCollection":
            if state.get("output_active"):     # OBS refuses while streaming/recording
                _srv_send_json(conn, {"op": 7, "d": {
                    "requestType": rtype, "requestId": rid,
                    "requestStatus": {"result": False, "code": 501,
                                      "comment": "output active"},
                    "responseData": {}}})
                continue
            state["set_collection"] = rdata["sceneCollectionName"]
            state["current_collection"] = rdata["sceneCollectionName"]
            resp = {}
        elif rtype == "GetInputList":
```

Note: the existing branch chain currently begins `if rtype == "GetInputList":`. Change that first `if` to the block above (which now starts the chain with `GetSceneCollectionList`) and demote the old `GetInputList` line to `elif rtype == "GetInputList":` as shown. All other branches stay unchanged. The new `state` keys default via `.get()`, so the existing release/refresh tests (which pass `state` without them) keep working.

- [ ] **Step 2: Write the failing end-to-end tests**

Add to `tests/test_obsws.py` after `t_refresh_browser_inputs_unreachable_is_quiet` (around line 430):

```python
# --------------------------------------------------------------------------
# get_scene_collection / set_scene_collection — best-effort, like the others
# --------------------------------------------------------------------------
def _start_fake_obs(state, password="supersecret"):
    """Spin up the loopback fake OBS server; return its port (daemon thread)."""
    server_sock = socket.socket()
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]
    thread = threading.Thread(target=_fake_obs_server,
                              args=(server_sock, password, state), daemon=True)
    thread.start()
    return port, server_sock


def t_get_scene_collection_reads_current_and_list():
    state = {"released": [], "current_collection": "IRO Endurance",
             "collections": ["IRO Endurance", "Other"]}
    port, srv = _start_fake_obs(state)
    status, note = m.get_scene_collection(port=port, password="supersecret", timeout=5)
    assert note == "", note
    assert status["current"] == "IRO Endurance"
    assert status["match"] is True
    assert status["available"] == ["IRO Endurance", "Other"]
    srv.close()


def t_get_scene_collection_unreachable_is_quiet():
    sock = socket.socket(); sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]; sock.close()
    status, note = m.get_scene_collection(port=free_port, password="x", timeout=0.5)
    assert status is None
    assert note


def t_set_scene_collection_switches_when_present_and_different():
    state = {"released": [], "current_collection": "Other",
             "collections": ["IRO Endurance", "Other"]}
    port, srv = _start_fake_obs(state)
    ok, note = m.set_scene_collection(port=port, password="supersecret", timeout=5)
    assert ok is True, note
    assert state["set_collection"] == "IRO Endurance"
    srv.close()


def t_set_scene_collection_noop_when_already_correct():
    state = {"released": [], "current_collection": "IRO Endurance",
             "collections": ["IRO Endurance"]}
    port, srv = _start_fake_obs(state)
    ok, note = m.set_scene_collection(port=port, password="supersecret", timeout=5)
    assert ok is True
    assert "already" in note
    assert "set_collection" not in state          # no switch request issued
    srv.close()


def t_set_scene_collection_refuses_when_absent():
    state = {"released": [], "current_collection": "Other",
             "collections": ["Other", "Spare"]}
    port, srv = _start_fake_obs(state)
    ok, note = m.set_scene_collection(port=port, password="supersecret", timeout=5)
    assert ok is False
    assert "not found" in note
    assert "set_collection" not in state
    srv.close()


def t_set_scene_collection_output_active_is_note_not_crash():
    state = {"released": [], "current_collection": "Other",
             "collections": ["IRO Endurance", "Other"], "output_active": True}
    port, srv = _start_fake_obs(state)
    ok, note = m.set_scene_collection(port=port, password="supersecret", timeout=5)
    assert ok is False
    assert note                                    # carries OBS's rejection
    srv.close()


def t_set_scene_collection_unreachable_is_quiet():
    sock = socket.socket(); sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]; sock.close()
    ok, note = m.set_scene_collection(port=free_port, password="x", timeout=0.5)
    assert ok is False
    assert note
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 tests/test_obsws.py`
Expected: `AttributeError: module 'obs_ws' has no attribute 'get_scene_collection'`

- [ ] **Step 4: Implement the two I/O functions**

In `src/scripts/obs_ws.py`, append after `reflect_feed_state` (end of file):

```python
def get_scene_collection(host="127.0.0.1", port=None, password=None, timeout=2.0):
    """Ask OBS which scene collection is active and classify it against
    EXPECTED_SCENE_COLLECTION. Returns (status_dict, note); (None, reason) on any
    failure — OBS closed, wrong password, protocol surprise — NEVER an exception
    (same best-effort contract as release_feed_inputs/refresh_browser_inputs)."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return None, note
    try:
        resp = session.request("GetSceneCollectionList", {})
        status = scene_collection_status(resp.get("currentSceneCollectionName"),
                                         resp.get("sceneCollections", []))
        return status, ""
    except Exception as exc:                         # noqa: BLE001 — best-effort contract
        return None, str(exc) or exc.__class__.__name__
    finally:
        session.close()


def set_scene_collection(name=EXPECTED_SCENE_COLLECTION, host="127.0.0.1",
                         port=None, password=None, timeout=2.0):
    """Switch OBS to scene collection `name`. Returns (ok, note). Best effort:
    - already on `name`            -> (True, "already on '<name>'"), no switch
    - `name` not in the live list  -> (False, "...not found...") — never creates
    - OBS rejects (output active)  -> (False, <obs error>) — _Session.request
      raises ValueError on a failed requestStatus; caught here, never re-raised
    - OBS unreachable              -> (False, reason)
    Heavyweight in OBS: the switch tears down and rebuilds ALL sources (incl. the
    relay feeds), so it is an explicit producer action, never automatic."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    try:
        resp = session.request("GetSceneCollectionList", {})
        current = resp.get("currentSceneCollectionName")
        available = resp.get("sceneCollections", [])
        if current == name:
            return True, f"already on '{name}'"
        if name not in available:
            return False, (f"scene collection '{name}' not found in OBS "
                           f"(import it with `iro setup`)")
        session.request("SetCurrentSceneCollection", {"sceneCollectionName": name})
        return True, ""
    except Exception as exc:                         # noqa: BLE001 — best-effort contract
        return False, str(exc) or exc.__class__.__name__
    finally:
        session.close()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 tests/test_obsws.py`
Expected: `ALL PASS`

- [ ] **Step 6: Commit**

```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): best-effort get/set scene collection over obs-websocket (#36)"
```

---

## Task 3: Readiness classifier in event.py

**Files:**
- Modify: `src/scripts/event.py` (add after `classify_companion`, around line 234)
- Test: `tests/test_event.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_event.py` (after the existing classify tests; place before the `if __name__` runner if present, else anywhere among the `t_` functions):

```python
# --------------------------------------------------------------------------
# OBS scene-collection readiness line
# --------------------------------------------------------------------------
def t_classify_scene_collection_skipped_when_status_none():
    r = m.classify_scene_collection(None, "OBS WebSocket not reachable")
    assert r.level == m.WARN
    assert "skipped" in r.detail
    assert "not reachable" in r.detail


def t_classify_scene_collection_match_is_pass():
    status = {"current": "IRO Endurance", "expected": "IRO Endurance",
              "available": ["IRO Endurance"], "match": True,
              "expected_present": True, "renamed_variant": None}
    r = m.classify_scene_collection(status, "")
    assert r.level == m.PASS
    assert "IRO Endurance" in r.detail


def t_classify_scene_collection_wrong_but_present_warns_with_fix():
    status = {"current": "Other", "expected": "IRO Endurance",
              "available": ["IRO Endurance", "Other"], "match": False,
              "expected_present": True, "renamed_variant": None}
    r = m.classify_scene_collection(status, "")
    assert r.level == m.WARN
    assert "iro obs collection set" in r.detail


def t_classify_scene_collection_renamed_variant_warns_manual():
    status = {"current": "IRO Endurance 2", "expected": "IRO Endurance",
              "available": ["IRO Endurance 2"], "match": False,
              "expected_present": False, "renamed_variant": "IRO Endurance 2"}
    r = m.classify_scene_collection(status, "")
    assert r.level == m.WARN
    assert "renamed" in r.detail


def t_classify_scene_collection_absent_warns_import():
    status = {"current": "Scene", "expected": "IRO Endurance",
              "available": ["Scene"], "match": False,
              "expected_present": False, "renamed_variant": None}
    r = m.classify_scene_collection(status, "")
    assert r.level == m.WARN
    assert "not found" in r.detail
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_event.py`
Expected: `AttributeError: module 'event' has no attribute 'classify_scene_collection'`

- [ ] **Step 3: Implement the classifier**

In `src/scripts/event.py`, add after `classify_companion` (after line 233):

```python
def classify_scene_collection(status, note):
    """OBS scene-collection readiness. WARN-level by design: a wrong collection
    is fixable in one click (`iro obs collection set` / the Control Center OBS
    row), and a flaky best-effort live probe must not turn the report red on its
    own. `status` is obs_ws.scene_collection_status(...) or None (probe failed)."""
    if status is None:
        return Result(WARN, "OBS scene collection", f"check skipped — {note}")
    if status["match"]:
        return Result(PASS, "OBS scene collection", f"{status['expected']} active")
    if status["renamed_variant"]:
        return Result(WARN, "OBS scene collection",
                      f"'{status['current']}' active — looks renamed; switch to "
                      f"{status['expected']} manually")
    if status["expected_present"]:
        return Result(WARN, "OBS scene collection",
                      f"'{status['current']}' active — switch with "
                      f"`iro obs collection set`")
    return Result(WARN, "OBS scene collection",
                  f"{status['expected']} collection not found — import it "
                  f"(`iro setup`)")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_event.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add src/scripts/event.py tests/test_event.py
git commit -m "feat(event): WARN-level OBS scene-collection readiness line (#36)"
```

---

## Task 4: CLI surface + event integration in iro.py

**Files:**
- Modify: `src/iro.py` — `OBS_VERBS` (line 438), parse usage (line 474 — auto-updates from `OBS_VERBS`), `obs_collection_cmd()` (add near `obs_refresh_cmd`, line 657), `DISPATCH` (line 1255), `_check_scene_collection()` + call in `event_start` (line 1214), collection line in `_event_sections` (line 1035).

This task has no new unit test of its own (the pure logic is covered in Tasks 1–3; the CLI wiring is exercised by the binary smoke test in CI). Verify by running the commands.

- [ ] **Step 1: Add the `collection` verb**

In `src/iro.py` line 438, change:

```python
OBS_VERBS = ("refresh",)
```
to:
```python
OBS_VERBS = ("refresh", "collection")
```

(The usage string at line 474 is built from `OBS_VERBS`, so it updates automatically.)

- [ ] **Step 2: Implement `obs_collection_cmd`**

In `src/iro.py`, add right after `obs_refresh_cmd` (after line 665):

```python
def obs_collection_cmd(rest):
    """`iro obs collection` reports the active OBS scene collection; add `set` to
    switch OBS to the IRO Endurance collection. Best effort — OBS must be running
    with obs-websocket reachable. A mismatch exits non-zero so scripts/CI notice;
    `set` exits non-zero on failure so the Control Center job shows red."""
    import obs_ws
    if rest[:1] == ["set"] and len(rest) == 1:
        ok, note = obs_ws.set_scene_collection()
        if not ok:
            sys.exit(f"obs: scene collection switch failed — {note}")
        print(f"obs: scene collection — {note or 'switched to ' + obs_ws.EXPECTED_SCENE_COLLECTION}.")
        return
    if rest:
        sys.exit("usage: iro obs collection [set]")
    status, note = obs_ws.get_scene_collection()
    if status is None:
        sys.exit(f"obs: scene collection check skipped — {note}")
    if status["match"]:
        print(f"obs: scene collection '{status['current']}' active — correct.")
        return
    if status["expected_present"]:
        sys.exit(f"obs: scene collection '{status['current']}' active — expected "
                 f"'{status['expected']}'. Run `iro obs collection set`.")
    if status["renamed_variant"]:
        sys.exit(f"obs: scene collection '{status['current']}' active — looks renamed "
                 f"from '{status['expected']}'; switch manually in OBS.")
    sys.exit(f"obs: '{status['expected']}' collection not found in OBS — import it "
             f"with `iro setup`.")
```

- [ ] **Step 3: Register the dispatch entry**

In `src/iro.py` `DISPATCH` (line 1255), change:

```python
    ("obs", "refresh"): obs_refresh_cmd,
```
to:
```python
    ("obs", "refresh"): obs_refresh_cmd, ("obs", "collection"): obs_collection_cmd,
```

- [ ] **Step 4: Add the event-start warning helper + call it**

In `src/iro.py`, add this helper near the other event helpers (e.g. right before `event_start`, line 1168):

```python
def _check_scene_collection():
    """Best-effort warning if OBS is on the wrong scene collection at event start.
    Never blocks bring-up: the producer switches with `iro obs collection set` or
    the Control Center OBS row (a switch rebuilds all sources, so it stays manual)."""
    try:
        import obs_ws
        status, note = obs_ws.get_scene_collection()
    except Exception as exc:                         # noqa: BLE001 — best effort
        print(f"obs: scene collection check skipped ({exc}).")
        return
    if status is None:
        print(f"obs: scene collection check skipped — {note}.")
        return
    if status["match"]:
        print(f"obs: scene collection '{status['current']}' active — correct.")
        return
    print(f"obs: WARNING — scene collection '{status['current']}' active, expected "
          f"'{status['expected']}'. Switch with `iro obs collection set` (or the OBS "
          f"row in the Control Center) before going live.")
```

In `event_start`, call it right after the page-refresh retry. Change (line 1214):

```python
    _refresh_obs_pages()
```
to:
```python
    _refresh_obs_pages()
    _check_scene_collection()       # warn (never switch) if the wrong collection is up
```

- [ ] **Step 5: Add the readiness line to `_event_sections`**

In `src/iro.py` `_event_sections` (lines 1035–1037), change:

```python
    apps = [ev.classify_app("obs", ev.app_running("obs")),
            ev.classify_app("discord", ev.app_running("discord")),
            ev.classify_tailscale(_tailscale_ip())]
```
to:
```python
    obs_running = ev.app_running("obs")
    apps = [ev.classify_app("obs", obs_running),
            ev.classify_app("discord", ev.app_running("discord")),
            ev.classify_tailscale(_tailscale_ip())]
    # Scene-collection line — only probe obs-websocket when OBS is actually up
    # (no point paying the connect timeout otherwise). Best effort: a broken
    # probe must never traceback the readiness report.
    if obs_running:
        try:
            import obs_ws
            status, note = obs_ws.get_scene_collection()
            apps.append(ev.classify_scene_collection(status, note))
        except Exception as exc:                     # noqa: BLE001 — best effort
            apps.append(ev.Result(ev.WARN, "OBS scene collection",
                                  f"check failed: {exc}"))
```

- [ ] **Step 6: Verify the CLI wiring**

Run (no OBS needed — must degrade gracefully, never traceback):

```bash
python3 src/iro.py obs collection
```
Expected: a single line like `obs: scene collection check skipped — OBS WebSocket not reachable on 127.0.0.1:4455 (OBS not running?)` and a non-zero exit (`echo $?` → 1). No traceback.

```bash
python3 src/iro.py obs collection set; echo "exit=$?"
```
Expected: `obs: scene collection switch failed — OBS WebSocket not reachable …` and `exit=1`. No traceback.

```bash
python3 src/iro.py obs bogus
```
Expected: `usage: iro obs {refresh|collection}` (the parse-level guard).

```bash
python3 tests/test_iro.py
```
Expected: `ALL PASS` (CLI routing unit checks still pass).

- [ ] **Step 7: Commit**

```bash
git add src/iro.py
git commit -m "feat(cli): iro obs collection [set] + event-start/status integration (#36)"
```

---

## Task 5: Control Center op, route, and provider

**Files:**
- Modify: `src/ui/ui_ops.py` (OPS table, line 9)
- Modify: `src/iro.py` (`obs_collection_data()` provider + ctx entry, line 2114)
- Modify: `src/ui/ui_server.py` (route after `/api/obs-ws`, line 215; ctx docstring line 67)
- Test: `tests/test_ui_ops.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui_ops.py` (anywhere among the `t_` functions):

```python
# ---------- obs scene collection ----------

def t_obs_collection_set_op_builds_argv():
    assert ui_ops.build_argv("obs-collection-set") == ["obs", "collection", "set"]


def t_obs_collection_set_op_rejects_params():
    try:
        ui_ops.build_argv("obs-collection-set", {"x": "1"})
    except ValueError:
        return
    raise AssertionError("expected ValueError for an unexpected param")


def t_obs_collection_data_ok_passes_status_through():
    status = {"current": "Other", "expected": "IRO Endurance",
              "available": ["IRO Endurance", "Other"], "match": False,
              "expected_present": True, "renamed_variant": None}
    d = iro.obs_collection_data(get=lambda: (status, ""))
    assert d["ok"] is True
    assert d["current"] == "Other"
    assert d["expected_present"] is True


def t_obs_collection_data_failure_is_not_ok():
    d = iro.obs_collection_data(get=lambda: (None, "OBS not reachable"))
    assert d == {"ok": False, "note": "OBS not reachable"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_ui_ops.py`
Expected: `ValueError: unknown operation: obs-collection-set` (first test), and `AttributeError: ... obs_collection_data`.

- [ ] **Step 3: Register the op**

In `src/ui/ui_ops.py`, add to `OPS` (after the `"obs-refresh"` entry, line 26):

```python
    "obs-collection-set": ["obs", "collection", "set"],
```

- [ ] **Step 4: Add the UI provider with a test seam**

In `src/iro.py`, add after `obs_ws_link_data` (after line 1471):

```python
def obs_collection_data(get=None):
    """Live OBS scene-collection check for the Control Center Apps view (on-demand
    /api/obs-collection). Best effort: {"ok": True, **status} when OBS answered,
    else {"ok": False, "note": reason}. Never raises (the route wraps it too).
    `get` is a test seam (defaults to obs_ws.get_scene_collection)."""
    if get is None:
        try:
            import obs_ws
            get = obs_ws.get_scene_collection
        except Exception as exc:                     # noqa: BLE001 — best effort
            return {"ok": False, "note": str(exc)}
    status, note = get()
    if status is None:
        return {"ok": False, "note": note}
    return {"ok": True, **status}
```

Add the ctx entry next to `"obs_ws"` (line 2114):

```python
        "obs_ws": obs_ws_link_data,
        "obs_collection": obs_collection_data,
```

- [ ] **Step 5: Add the HTTP route + ctx docstring note**

In `src/ui/ui_server.py`, add after the `/api/obs-ws` block (after line 215):

```python
            if path == "/api/obs-collection":
                try:
                    return self._json(ctx["obs_collection"]())
                except Exception as exc:
                    return self._json({"ok": False,
                                       "error": f"obs collection check failed: {exc}"},
                                      code=500)
```

In the `make_handler` docstring (line 67), append `obs_collection() -> dict,` to the listed ctx keys (keeps the contract doc accurate):

```python
    obs_ws() -> dict, obs_collection() -> dict, update_check(force) -> dict, streams_read() -> dict,
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 tests/test_ui_ops.py && python3 tests/test_ui_server.py`
Expected: `ALL PASS` for both.

- [ ] **Step 7: Commit**

```bash
git add src/ui/ui_ops.py src/ui/ui_server.py src/iro.py tests/test_ui_ops.py
git commit -m "feat(ui): obs-collection-set op + /api/obs-collection provider (#36)"
```

---

## Task 6: Control Center UI — status line + Switch button

**Files:**
- Modify: `src/ui/control-center.html` (Apps view markup line 496; CONFIRM_TEXT line 1247; view-open hook line 711; post-job refresh line 1298; new `fetchObsCollection()` near `fetchAssetFiles` line 1431)

HTML has no unit-test harness in this repo; verify by build + a manual Control Center check.

- [ ] **Step 1: Add the status-line markup**

In `src/ui/control-center.html`, in the Apps view, insert a collection line between the `applist` section close and the envhint. Change (lines 494–497):

```html
        <section><div id="applist">
          <div class="item miss"><span class="idot"></span><span class="dim grow">loading…</span></div>
        </div></section>
        <p class="envhint">The badge shows whether each app is running.
```
to:
```html
        <section><div id="applist">
          <div class="item miss"><span class="idot"></span><span class="dim grow">loading…</span></div>
        </div></section>
        <p class="envhint" id="obscoll">OBS scene collection: <span class="dim">checking…</span></p>
        <p class="envhint">The badge shows whether each app is running.
```

- [ ] **Step 2: Add the confirm text for the switch**

In `CONFIRM_TEXT` (line 1247), add an entry (the switch rebuilds sources, so it is gated like the other destructive ops):

```javascript
  'event-stop': 'Stop the event? (stops the iro services; OBS/Discord/Tailscale keep running)',
  'obs-collection-set': 'Switch OBS to the IRO Endurance scene collection? This rebuilds all sources (incl. the relay feeds).'
```

(Add a comma after the `event-stop` line and append the new line as shown.)

- [ ] **Step 3: Add `fetchObsCollection()`**

In `src/ui/control-center.html`, add this function right before `fetchAssetFiles` (line 1431):

```javascript
// OBS scene-collection check (on-demand, live obs-websocket connect) for the
// Apps view. Shows ✓ correct / ⚠ wrong, with a Switch button only when the
// IRO Endurance collection is present to switch to.
async function fetchObsCollection() {
  const el = $('obscoll');
  if (!el) return;
  let d;
  try { d = await (await fetch('/api/obs-collection', {cache: 'no-store'})).json(); }
  catch (e) { return; }                  // server gone — keep last state
  el.textContent = 'OBS scene collection: ';
  if (!d.ok) {
    const s = document.createElement('span');
    s.className = 'dim';
    s.textContent = 'check skipped — ' + (d.note || 'OBS not reachable');
    el.appendChild(s);
    return;
  }
  if (d.match) {
    const b = document.createElement('b');
    b.textContent = d.current;
    el.appendChild(b);
    el.appendChild(document.createTextNode(' active — correct.'));
    return;
  }
  const msg = document.createElement('span');
  if (d.expected_present) {
    msg.textContent = '⚠ “' + d.current + '” active — expected “'
                    + d.expected + '”. ';
    el.appendChild(msg);
    const b = document.createElement('button');
    b.textContent = 'Switch to ' + d.expected;
    b.onclick = () => op('obs-collection-set', true);
    el.appendChild(b);
  } else if (d.renamed_variant) {
    msg.textContent = '⚠ “' + d.current + '” active — looks renamed from “'
                    + d.expected + '”; switch manually in OBS.';
    el.appendChild(msg);
  } else {
    msg.textContent = '⚠ “' + d.expected + '” collection not found in OBS — '
                    + 'import it (Export collection / `iro setup`).';
    el.appendChild(msg);
  }
}
```

- [ ] **Step 4: Fetch on Apps-view open**

In the view-switch hook (after line 711, the `setupLoaded` block), add a refetch on every Apps visit (live OBS state changes, so do not one-shot guard it):

```javascript
  if (name === 'apps') fetchObsCollection();
```

- [ ] **Step 5: Refetch after the switch job finishes**

In the job `done` handler (line 1298), alongside the other post-job refreshes, add:

```javascript
    if (name === 'graphics' || name === 'media') fetchAssetFiles();
    if (name === 'obs-collection-set') fetchObsCollection();
```

- [ ] **Step 6: Verify in the running Control Center**

Run the UI and open the Apps view:

```bash
python3 src/iro.py ui
```
Then browse to `http://127.0.0.1:8089`, open **Apps**. Expected (with OBS not running): the line reads `OBS scene collection: check skipped — OBS WebSocket not reachable …`. No JS console errors (the page must not throw). Stop with Ctrl-C.

(If OBS is available with a non-IRO collection active, the line shows the ⚠ message and a **Switch to IRO Endurance** button that, when clicked, asks for confirmation, runs the job, and refreshes the line. This is the full manual check; the no-OBS check above is the minimum gate.)

- [ ] **Step 7: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(ui): OBS scene-collection status line + Switch button in Apps view (#36)"
```

---

## Task 7: Docs + full suite + build verify

**Files:**
- Modify: `CLAUDE.md` (command list near `iro obs refresh`; obs_ws description)
- Modify: `README.md` (command list)

- [ ] **Step 1: Document the command in CLAUDE.md**

In `CLAUDE.md`, in the Commands block, add a line after the `iro obs refresh` line:

```
python3 src/iro.py obs refresh       # force-reload the relay-served OBS browser sources (HUD/timer)
python3 src/iro.py obs collection    # check the active OBS scene collection (add `set` to switch to IRO Endurance)
```

In the `obs_ws.py` architecture paragraph (the `src/scripts/obs_ws.py` bullet under the unified CLI section), append one sentence:

```
It also exposes a scene-collection check/switch (`GetSceneCollectionList` /
`SetCurrentSceneCollection`): `iro obs collection [set]`, an `event start`
warning, an `event status` line, and the Control Center's OBS row. Switching
is always an explicit producer action — it rebuilds every source — never
automatic. The expected name is `EXPECTED_SCENE_COLLECTION`, which mirrors the
`name` field of `src/obs/IRO_Endurance.json`.
```

- [ ] **Step 2: Document the command in README.md**

In `README.md`, find the command list entry for `iro obs refresh` and add directly below it:

```
- `iro obs collection` — check the active OBS scene collection; `iro obs collection set` switches OBS to the `IRO Endurance` collection.
```

(If README has no `iro obs refresh` line, add the entry in the same group as the other `iro obs`/event commands.)

- [ ] **Step 3: Run the full test suite**

Run: `python3 tools/run-tests.py`
Expected: every test file reports `ALL PASS`; the runner ends with its success summary, exit 0.

- [ ] **Step 4: Run the linter**

Run: `python3 tools/lint.py`
Expected: no findings (exit 0). If it flags the broad `except Exception` lines, confirm they carry the `# noqa: BLE001` marker as in the surrounding code; fix any real findings.

- [ ] **Step 5: Build + self-verify the distributable**

Run: `python3 tools/build.py`
Expected: build completes and the verify step passes (no shell scripts, no secrets, tokenization intact, preflight present). Exit 0.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: iro obs collection [set] (#36)"
```

---

## Self-Review notes (verified against the spec)

- **Spec coverage:** constant + `scene_collection_status` (T1); `get`/`set` best-effort I/O (T2); WARN readiness classifier (T3); CLI `obs collection [set]`, `event start` warning, `event status` line (T4); UI op + route + provider (T5); Apps-view status line + Switch button + confirm + refresh (T6); docs (T7). Decision points all honored: exact-name match with prefix-only warning (T1/T3/T4), exact-only switch target (T2), Apps-view on-demand (T5/T6), `event status` gets a line (T4), warn-not-auto-switch everywhere.
- **Type consistency:** the `scene_collection_status` dict keys (`current`, `expected`, `available`, `match`, `expected_present`, `renamed_variant`) are used identically in T3 (classify), T4 (CLI/event), T5 (provider passthrough), and T6 (JS reads the same names). `get_scene_collection` → `(status|None, note)`; `set_scene_collection` → `(ok, note)`; `obs_collection_data` → `{ok, ...}` consistently.
- **No placeholders:** every code/edit step shows the exact code; every run step states the expected output.
- **Best-effort invariant:** all four OBS paths (CLI, event_start, event_status, UI provider) wrap failures and never traceback; tests assert the unreachable/wrong-password/output-active paths return notes, not exceptions.
```
