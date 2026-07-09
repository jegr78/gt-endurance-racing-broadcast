# Solo Device Enumeration — Standalone (temp-input OBS probe) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enumerate the machine's OBS video-capture and microphone devices without any solo scene collection imported, by probing OBS with a throwaway scene + temporary disabled input, replacing the #304 "import the solo collection first" mechanism.

**Architecture:** A new pure `pick_input_kind` selects the platform capture kind from OBS's live `GetInputKindList`; a new best-effort `probe_device_options` opens one obs-websocket session, creates a throwaway scene and a disabled temp input of that kind, reads the device dropdown via `GetInputPropertiesListPropertyItems`, and always removes both in a `finally`. Both existing callers (the Control Center `/api/devices` route and the `racecast device-scan` CLI) switch to it; the old named-input reader `enumerate_device_options` (and its only helper `input_not_found`) are removed. UX copy that told operators to import the collection first is dropped.

**Tech Stack:** Python 3 stdlib only. Tests are stdlib runnable scripts (NOT pytest): each `tests/test_*.py` defines `t_*()` functions and a `__main__` runner. Run one function with `python3 -c "import sys; sys.path.insert(0,'tests'); import test_X as t; t.t_NAME()"`. The existing `tests/test_obsws.py` `_fake_obs_server` / `_start_fake_obs` harness is a real in-process websocket OBS stand-in — extend it, do not mock.

## Global Constraints

- **Edit only under `src/` (plus `tests/` and `docs/`).** `dist/`/`runtime/` are generated — never hand-edit.
- **English only** in all code, comments, docs, and copy.
- **obs_ws helpers are best-effort and NEVER raise** — any failure (OBS unreachable, missing kind, protocol surprise) returns empty data + a human-readable `note`; the contract mirrors `release_feed_inputs` / `probe`. Blind `except Exception` carries `# noqa: BLE001 — best-effort contract`.
- **`obs_ws` must stay importable without pulling `setup-assets`** (the `STREAMLINK_TWITCH`/`DEVICE_VARIANTS` duplication precedent: agreement pinned by a cross-check test, not a shared import).
- **The temp probe must never switch the OBS program scene** and must always remove its throwaway scene + input, including on a mid-probe error.
- **`.env` write path is unchanged** — `env_upsert_data` (upsert; preserves unrelated `RACECAST_*` keys). This plan does not touch it.
- **A change to `src/ui/control-center.html` triggers the `ui-visual-verify-gate` Stop hook** — the final task must render, look, and record the marker via `.claude/hooks/record_ui_verified.py`.
- Run `python3 tools/lint.py` after changing any Python file; run `python3 tools/run-tests.py` before the final handoff.

---

## File Structure

- `src/scripts/obs_ws.py` — **add** `pick_input_kind`, the two matcher-tuple constants, the three probe-name constants, and `probe_device_options`; **remove** `enumerate_device_options` + `input_not_found`. Keep `parse_property_items` and `device_property_name` (both reused).
- `src/racecast.py` — repoint `device_scan_cmd` (line ~2632) and `devices_enumerate_data` (line ~4626) to `probe_device_options`; remove the now-unused `DEVICE_SCAN_INPUT_NAME` / `DEVICE_SCAN_MIC_INPUT_NAME` constants; update the CLI's no-devices exit copy.
- `src/ui/control-center.html` — drop the "import the solo collection first" fallback string in the `#dev-hint` JS (line ~2566).
- `tests/test_obsws.py` — add `pick_input_kind` unit tests; extend `_fake_obs_server` to serve `GetInputKindList` / `CreateScene` / `CreateInput` / `GetInputPropertiesListPropertyItems` / `RemoveInput` / `RemoveScene` and record calls; add `probe_device_options` end-to-end tests (happy path, unreachable, cleanup-on-error, no-kind); remove `t_input_not_found`.
- `tests/test_racecast.py` — repoint any patch target from `enumerate_device_options` to `probe_device_options`; assert `devices_enumerate_data` maps a probe result to the `{ok,devices,note,mic,mic_note}` shape.
- `tests/test_ui_server.py` — `GET /api/devices` shape via the injected enumerator (contract unchanged; verify still green).

---

## Task 1: `pick_input_kind` + capture-kind matcher constants (obs_ws)

**Files:**
- Modify: `src/scripts/obs_ws.py` (add after `device_property_name`, near line 583)
- Test: `tests/test_obsws.py`

**Interfaces:**
- Produces: `pick_input_kind(kind_list, matchers) -> str | None`; module constants `VIDEO_INPUT_KIND_MATCHERS`, `AUDIO_INPUT_KIND_MATCHERS`, `PROBE_SCENE_NAME`, `PROBE_VIDEO_INPUT`, `PROBE_MIC_INPUT`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_obsws.py` (before the `__main__` block):

```python
def t_pick_input_kind_finds_macos_v2_via_substring():
    # macOS reports av_capture_input_v2; the matcher is the av_capture_input substring.
    kinds = ["image_source", "av_capture_input_v2", "coreaudio_input_capture"]
    assert m.pick_input_kind(kinds, m.VIDEO_INPUT_KIND_MATCHERS) == "av_capture_input_v2"
    assert m.pick_input_kind(kinds, m.AUDIO_INPUT_KIND_MATCHERS) == "coreaudio_input_capture"


def t_pick_input_kind_honors_matcher_priority_over_list_order():
    # dshow appears BEFORE v4l2 in the list, but the matcher order is
    # (av_capture, dshow, v4l2); dshow's matcher outranks v4l2's regardless of
    # list position — assert the preferred matcher wins.
    kinds = ["v4l2_input", "dshow_input"]
    assert m.pick_input_kind(kinds, m.VIDEO_INPUT_KIND_MATCHERS) == "dshow_input"


def t_pick_input_kind_none_when_no_match_or_bad_input():
    assert m.pick_input_kind(["image_source", "color_source"], m.VIDEO_INPUT_KIND_MATCHERS) is None
    assert m.pick_input_kind([], m.VIDEO_INPUT_KIND_MATCHERS) is None
    assert m.pick_input_kind(None, m.VIDEO_INPUT_KIND_MATCHERS) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_obsws as t; t.t_pick_input_kind_finds_macos_v2_via_substring()"`
Expected: FAIL with `AttributeError: module 'obs_ws' has no attribute 'pick_input_kind'`.

- [ ] **Step 3: Add the constants and `pick_input_kind`**

In `src/scripts/obs_ws.py`, immediately after the `device_property_name` function (after line 583), add:

```python
# Platform capture-input kinds, as OBS reports them in GetInputKindList. Matched by
# substring (macOS reports av_capture_input_v2, so an exact-string match would miss it)
# and tried in this order — a preferred matcher wins over a later one regardless of the
# order OBS lists the kinds in. macOS is live-validated; Windows/Linux go through the
# same mechanism (documented cross-platform assumption, see the design spec).
VIDEO_INPUT_KIND_MATCHERS = ("av_capture_input", "dshow_input", "v4l2_input")
AUDIO_INPUT_KIND_MATCHERS = ("coreaudio_input_capture", "wasapi_input_capture",
                             "pulse_input_capture")

# Throwaway names for the device-enumeration probe (temp scene + disabled temp inputs;
# never appear in program output; always removed after the probe).
PROBE_SCENE_NAME = "__racecast_device_probe__"
PROBE_VIDEO_INPUT = "__racecast_probe_video__"
PROBE_MIC_INPUT = "__racecast_probe_mic__"


def pick_input_kind(kind_list, matchers):
    """First kind in `kind_list` whose lowercased value contains a `matchers`
    substring. Honors matcher order first (a preferred matcher wins even if a
    less-preferred kind appears earlier in `kind_list`), then list order. Returns
    None if nothing matches or `kind_list` is not a list/tuple. Case-insensitive."""
    if not isinstance(kind_list, (list, tuple)):
        return None
    lowered = [(k, str(k).lower()) for k in kind_list]
    for sub in matchers:
        needle = sub.lower()
        for original, low in lowered:
            if needle in low:
                return original
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_obsws.py`
Expected: prints `ok t_pick_input_kind_...` lines and `ALL PASS`.

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: no new findings.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(solo): pick_input_kind + capture-kind matchers for device probe

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `probe_device_options` + fake-server support + cleanup guarantee (obs_ws)

**Files:**
- Modify: `src/scripts/obs_ws.py` (add `probe_device_options`; leave `enumerate_device_options`/`input_not_found` in place — Task 3 removes them)
- Test: `tests/test_obsws.py` (extend `_fake_obs_server`; add probe tests)

**Interfaces:**
- Consumes: `pick_input_kind`, the matcher + probe-name constants (Task 1), `parse_property_items`, `device_property_name`, `_connect` (existing).
- Produces: `probe_device_options(host="127.0.0.1", port=None, password=None, timeout=2.0) -> {"devices": list, "note": str, "mic": list, "mic_note": str}` where each list is `[{"name": str, "value": str}]` (from `parse_property_items`, which also carries `"enabled"`).

- [ ] **Step 1: Extend the fake OBS server to serve the probe request types**

In `tests/test_obsws.py`, inside `_fake_obs_server`'s request dispatch (the `if rtype == ...` chain starting at line 358), add these branches **before** the final `else: resp = {}` (line 433). They record calls into `state` so tests can assert lifecycle + cleanup:

```python
        elif rtype == "GetInputKindList":
            resp = {"inputKinds": state.get("input_kinds",
                    ["image_source", "av_capture_input_v2", "coreaudio_input_capture"])}
        elif rtype == "CreateScene":
            state.setdefault("created_scenes", []).append(rdata["sceneName"])
            resp = {}
        elif rtype == "RemoveScene":
            state.setdefault("removed_scenes", []).append(rdata["sceneName"])
            resp = {}
        elif rtype == "CreateInput":
            state.setdefault("created_inputs", []).append(
                (rdata["sceneName"], rdata["inputName"], rdata["inputKind"],
                 rdata.get("sceneItemEnabled")))
            resp = {}
        elif rtype == "RemoveInput":
            state.setdefault("removed_inputs", []).append(rdata["inputName"])
            resp = {}
        elif rtype == "GetInputPropertiesListPropertyItems":
            state.setdefault("prop_reads", []).append(
                (rdata["inputName"], rdata["propertyName"]))
            if state.get("prop_raises"):
                _srv_send_json(conn, {"op": 7, "d": {
                    "requestType": rtype, "requestId": rid,
                    "requestStatus": {"result": False, "code": 604},
                    "responseData": {}}})
                continue
            table = state.get("prop_items", {})
            resp = {"propertyItems": table.get(rdata["propertyName"], [])}
```

- [ ] **Step 2: Write the failing probe tests**

Add to `tests/test_obsws.py` (before `__main__`). These reuse the existing `_start_fake_obs(state)` helper (password `"supersecret"`):

```python
_VIDEO_ITEMS = [{"itemName": "FaceTime HD Camera", "itemValue": "0x1", "itemEnabled": True},
                {"itemName": "Elgato Cam Link", "itemValue": "0x2", "itemEnabled": True}]
_MIC_ITEMS = [{"itemName": "MacBook Air Microphone", "itemValue": "mic-uid", "itemEnabled": True}]


def t_probe_device_options_lists_video_and_mic_and_cleans_up():
    # darwin properties: video "device", audio "device_id".
    state = {"prop_items": {"device": _VIDEO_ITEMS, "device_id": _MIC_ITEMS}}
    port, srv = _start_fake_obs(state)
    try:
        out = m.probe_device_options(port=port, password="supersecret", timeout=5)
    finally:
        srv.close()
    # NOTE: value-carrying assertions rely on the probe running on macOS (device props).
    # The lifecycle assertions below are platform-independent.
    assert isinstance(out["devices"], list) and isinstance(out["mic"], list)
    # A throwaway scene was created and then removed (cleanup guarantee).
    assert m.PROBE_SCENE_NAME in state.get("created_scenes", [])
    assert m.PROBE_SCENE_NAME in state.get("removed_scenes", [])
    # Every temp input created was also removed.
    created = [n for (_s, n, _k, _e) in state.get("created_inputs", [])]
    assert created, "expected at least one temp input"
    assert sorted(created) == sorted(state.get("removed_inputs", []))
    # Temp inputs were created DISABLED (never enter program output).
    assert all(enabled is False for (_s, _n, _k, enabled) in state["created_inputs"])


def t_probe_device_options_cleans_up_even_when_read_raises():
    # The property read fails mid-probe; the temp scene + input must STILL be removed.
    state = {"prop_raises": True,
             "prop_items": {"device": _VIDEO_ITEMS, "device_id": _MIC_ITEMS}}
    port, srv = _start_fake_obs(state)
    try:
        out = m.probe_device_options(port=port, password="supersecret", timeout=5)
    finally:
        srv.close()
    assert out["devices"] == [] and out["note"]      # degraded, note explains
    assert m.PROBE_SCENE_NAME in state.get("removed_scenes", [])
    created = [n for (_s, n, _k, _e) in state.get("created_inputs", [])]
    assert sorted(created) == sorted(state.get("removed_inputs", []))


def t_probe_device_options_no_capture_kind_is_note_not_crash():
    # OBS reports no capture kinds at all -> empty lists + explanatory notes, no crash,
    # scene still created and removed.
    state = {"input_kinds": ["image_source", "color_source"], "prop_items": {}}
    port, srv = _start_fake_obs(state)
    try:
        out = m.probe_device_options(port=port, password="supersecret", timeout=5)
    finally:
        srv.close()
    assert out["devices"] == [] and out["note"]
    assert out["mic"] == [] and out["mic_note"]
    assert state.get("created_inputs", []) == []     # nothing to create
    assert m.PROBE_SCENE_NAME in state.get("removed_scenes", [])


def t_probe_device_options_unreachable_is_quiet():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]
    sock.close()
    out = m.probe_device_options(port=free_port, password="x", timeout=0.5)
    assert out["devices"] == [] and out["mic"] == []
    assert out["note"] and out["mic_note"]           # both carry the connect reason
```

- [ ] **Step 3: Run the probe tests to verify they fail**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_obsws as t; t.t_probe_device_options_unreachable_is_quiet()"`
Expected: FAIL with `AttributeError: module 'obs_ws' has no attribute 'probe_device_options'`.

- [ ] **Step 4: Implement `probe_device_options`**

In `src/scripts/obs_ws.py`, add after `enumerate_device_options` (after line 634):

```python
def probe_device_options(host="127.0.0.1", port=None, password=None, timeout=2.0):
    """Enumerate the local video-capture and microphone devices OBS offers, WITHOUT
    any solo collection imported — exactly what OBS shows when you add a capture
    source by hand. Opens one session, creates a throwaway scene plus a disabled
    temp input of the platform capture kind, reads its device dropdown, then removes
    both. Returns {"devices": [...], "note": str, "mic": [...], "mic_note": str}
    (each list is [{name, value, enabled}] from parse_property_items).

    Best-effort like release_feed_inputs: OBS unreachable / no capture kind /
    protocol surprise -> empty list(s) + a human-readable note, NEVER raises. The
    throwaway scene + inputs are ALWAYS removed (finally), including mid-probe, and
    the current program scene is never switched (the temp input is created disabled)."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return {"devices": [], "note": note, "mic": [], "mic_note": note}
    out = {"devices": [], "note": "", "mic": [], "mic_note": ""}
    created = []
    scene_made = False

    def read_options(input_name, kind, prop):
        try:
            session.request("CreateInput", {"sceneName": PROBE_SCENE_NAME,
                                            "inputName": input_name, "inputKind": kind,
                                            "sceneItemEnabled": False})
            created.append(input_name)
            payload = session.request("GetInputPropertiesListPropertyItems",
                                      {"inputName": input_name, "propertyName": prop})
            return parse_property_items(payload), ""
        except Exception as exc:                     # noqa: BLE001 — best-effort contract
            return [], (str(exc) or exc.__class__.__name__)

    try:
        kinds = session.request("GetInputKindList").get("inputKinds", [])
        vid_kind = pick_input_kind(kinds, VIDEO_INPUT_KIND_MATCHERS)
        aud_kind = pick_input_kind(kinds, AUDIO_INPUT_KIND_MATCHERS)
        try:                                         # clear a stale scene from a crash
            session.request("RemoveScene", {"sceneName": PROBE_SCENE_NAME})
        except Exception:                            # noqa: BLE001 — best-effort contract
            pass
        session.request("CreateScene", {"sceneName": PROBE_SCENE_NAME})
        scene_made = True
        if vid_kind:
            out["devices"], out["note"] = read_options(
                PROBE_VIDEO_INPUT, vid_kind, device_property_name(sys.platform))
        else:
            out["note"] = "no video capture input kind in this OBS"
        if aud_kind:
            out["mic"], out["mic_note"] = read_options(
                PROBE_MIC_INPUT, aud_kind,
                device_property_name(sys.platform, kind="audio"))
        else:
            out["mic_note"] = "no audio capture input kind in this OBS"
    except Exception as exc:                         # noqa: BLE001 — best-effort contract
        reason = str(exc) or exc.__class__.__name__
        out["note"] = out["note"] or reason
        out["mic_note"] = out["mic_note"] or reason
    finally:
        for name in created:
            try:
                session.request("RemoveInput", {"inputName": name})
            except Exception:                        # noqa: BLE001 — best-effort contract
                pass
        if scene_made:
            try:
                session.request("RemoveScene", {"sceneName": PROBE_SCENE_NAME})
            except Exception:                        # noqa: BLE001 — best-effort contract
                pass
        session.close()
    return out
```

- [ ] **Step 5: Run the probe tests to verify they pass**

Run: `python3 tests/test_obsws.py`
Expected: all `t_probe_device_options_*` print `ok` and the file ends `ALL PASS`.

- [ ] **Step 6: Lint**

Run: `python3 tools/lint.py`
Expected: no new findings.

- [ ] **Step 7: Commit**

```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(solo): probe_device_options — collection-free OBS device enumeration

Creates a throwaway scene + disabled temp input of the platform capture kind,
reads the device dropdown, always removes both (finally). Best-effort; never
raises. Fake-server tests prove the cleanup guarantee incl. mid-probe failure.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Migrate both callers; remove the old reader (racecast)

**Files:**
- Modify: `src/racecast.py` — `device_scan_cmd` (~2614-2688), `devices_enumerate_data` (~4616-4634); remove `DEVICE_SCAN_INPUT_NAME`/`DEVICE_SCAN_MIC_INPUT_NAME` (2580-2581)
- Modify: `src/scripts/obs_ws.py` — remove `enumerate_device_options` (615-634) and `input_not_found` (606-612)
- Test: `tests/test_obsws.py` (remove `t_input_not_found`), `tests/test_racecast.py`, `tests/test_ui_server.py`

**Interfaces:**
- Consumes: `probe_device_options` (Task 2). `devices_write_data` / `resolve_device_selection` / `env_upsert_data` / `_parse_device_scan_args` are unchanged.
- Produces: `devices_enumerate_data() -> {"ok": bool, "devices": [{name,value}], "note": str, "mic": [{name,value}], "mic_note": str}` (shape unchanged; new source).

- [ ] **Step 1: Add the `devices_enumerate_data` mapping test**

`tests/test_racecast.py` has NO existing `devices_enumerate_data` test — add these two beside the other `device`/`env` tests. The module under test is aliased `m` (`m = importlib.util.module_from_spec(...)` at line 8), and `racecast.py` lazily `import obs_ws` inside the function, so patching `obs_ws.probe_device_options` on the shared module object takes effect:

```python
def t_devices_enumerate_data_maps_probe_result():
    import obs_ws
    saved = obs_ws.probe_device_options
    obs_ws.probe_device_options = lambda *a, **k: {
        "devices": [{"name": "Cam", "value": "0x1", "enabled": True}],
        "note": "",
        "mic": [{"name": "Mic", "value": "uid", "enabled": True}],
        "mic_note": "audio note"}
    try:
        out = m.devices_enumerate_data()
    finally:
        obs_ws.probe_device_options = saved
    assert out["ok"] is True                       # ok reflects the video note only
    assert out["devices"] == [{"name": "Cam", "value": "0x1"}]
    assert out["note"] == ""
    assert out["mic"] == [{"name": "Mic", "value": "uid"}]
    assert out["mic_note"] == "audio note"


def t_devices_enumerate_data_note_sets_ok_false():
    import obs_ws
    saved = obs_ws.probe_device_options
    obs_ws.probe_device_options = lambda *a, **k: {
        "devices": [], "note": "OBS unreachable", "mic": [], "mic_note": "OBS unreachable"}
    try:
        out = m.devices_enumerate_data()
    finally:
        obs_ws.probe_device_options = saved
    assert out["ok"] is False
    assert out["note"] == "OBS unreachable"
```

- [ ] **Step 2: Run the mapping test to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_racecast as t; t.t_devices_enumerate_data_maps_probe_result()"`
Expected: FAIL — `devices_enumerate_data` still calls `enumerate_device_options` (which now ignores the patched `probe_device_options`), so `ok`/values won't match (or it errors once Step 4 removes the old function). Either way: not PASS.

- [ ] **Step 3: Repoint `devices_enumerate_data`**

In `src/racecast.py`, replace the body of `devices_enumerate_data` (lines 4625-4634, the `import obs_ws` through the `return`) with:

```python
    import obs_ws
    res = obs_ws.probe_device_options()
    return {"ok": not res["note"],
            "devices": [{"name": d["name"], "value": d["value"]} for d in res["devices"]],
            "note": res["note"],
            "mic": [{"name": d["name"], "value": d["value"]} for d in res["mic"]],
            "mic_note": res["mic_note"]}
```

Also update the function's docstring (lines 4617-4624): replace the "offered to the 'Solo Capture Device' input" / "Commentary Mic Device" wording with "enumerated by a throwaway-scene OBS probe (no collection needs importing)" and change the trailing `obs_ws.enumerate_device_options is best-effort` to `obs_ws.probe_device_options is best-effort`.

- [ ] **Step 4: Repoint `device_scan_cmd` and remove the dead constants/helpers**

In `src/racecast.py` `device_scan_cmd`, replace lines 2632-2638 (the two `enumerate_device_options` calls and the no-devices guard) with:

```python
    res = obs_ws.probe_device_options()
    devices, note = res["devices"], res["note"]
    mics, mic_note = res["mic"], res["mic_note"]
    if not devices and not mics:
        sys.exit(f"device-scan: {note or mic_note or 'no devices found'} — "
                 "start OBS with obs-websocket enabled, then retry.")
```

Delete the two constants at lines 2580-2581 (`DEVICE_SCAN_INPUT_NAME`, `DEVICE_SCAN_MIC_INPUT_NAME`).

In `src/scripts/obs_ws.py`, delete `input_not_found` (lines 606-612) and `enumerate_device_options` (lines 615-634). Keep `parse_property_items` (used by the probe).

In `tests/test_obsws.py`, delete `t_input_not_found` (lines ~1504-1512) — the helper it tests is gone.

- [ ] **Step 5: Run the affected suites to verify green**

Run: `python3 tests/test_racecast.py && python3 tests/test_obsws.py && python3 tests/test_ui_server.py`
Expected: each ends `ALL PASS`. (`test_ui_server`'s `/api/devices` test injects the enumerator, so its contract is unchanged.)

- [ ] **Step 6: Grep to confirm nothing still references the removed names**

Run: `grep -rn "enumerate_device_options\|input_not_found\|DEVICE_SCAN_INPUT_NAME\|DEVICE_SCAN_MIC_INPUT_NAME" src/ tests/ tools/`
Expected: **no output** (empty). If anything prints, fix that caller before committing.

- [ ] **Step 7: Lint**

Run: `python3 tools/lint.py`
Expected: no new findings (no unused-import/name warnings from the removals).

- [ ] **Step 8: Commit**

```bash
git add src/racecast.py src/scripts/obs_ws.py tests/test_racecast.py tests/test_obsws.py
git commit -m "refactor(solo): route device-scan + /api/devices through probe_device_options

Both callers now enumerate via the collection-free temp-input probe; remove the
old named-input reader enumerate_device_options + input_not_found and the
DEVICE_SCAN_* input-name constants.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Control Center hint copy + visual verification

**Files:**
- Modify: `src/ui/control-center.html` (~2544, ~2566)
- Verify: render + look; record `runtime/ui-visual-verified.json` marker

**Interfaces:** none (front-end copy only; `/api/devices` shape unchanged).

- [ ] **Step 1: Update the degraded-state copy**

In `src/ui/control-center.html`, the `#dev-hint` fallback (around line 2566) currently reads:

```javascript
    : ((d && d.note) || 'Start OBS with the solo collection imported to list devices, or set '
```

Replace the literal string (keep the `(d && d.note) ||` precedence so a server note still wins) so the collection wording is gone. The new fallback:

```javascript
    : ((d && d.note) || 'Start OBS with obs-websocket enabled to list devices, or set '
```

Leave the trailing `RACECAST_CAPTURE/WEBCAM in the .env editor above.` continuation as-is (only the "solo collection imported" clause changes to "obs-websocket enabled"). Do not touch the `'Control Center not reachable.'` branch at line 2544.

- [ ] **Step 2: Serve the Control Center from the dev build on a free port**

Per `ui-visual-verification`: from `src/`, start the Control Center on a free port (scan 8090+, NEVER 8089 — that is the operator's real instance):

Run: `RACECAST_UI_PORT=8090 python3 src/racecast.py ui --no-browser` (background it; if 8090 is busy try 8091, 8092, …)
Expected: the server logs `serving on http://127.0.0.1:8090`.

- [ ] **Step 3: Screenshot the changed component and look**

Use the Playwright MCP. Navigate to `http://127.0.0.1:8090`, open **General Settings**, scroll to the **Solo devices** section (`#dev-head` / `#dev-hint`), and take an **element** screenshot of that section at a realistic viewport width. `Read` the PNG back and verify deliberately:
- the hint no longer says "solo collection imported" — it now reads "obs-websocket enabled" (OBS will be unreachable in the dev build, so the fallback branch is what renders);
- it uses the surface's theme (`.envhint` styling on the dark panel — no default browser look);
- it is not clipped and sits correctly under the two dropdowns.

If anything is off, fix `control-center.html` and re-shoot.

- [ ] **Step 4: Refresh the committed wiki screenshot**

The General Settings view is a Control Center surface (CLAUDE.md hard rule). Regenerate `src/docs/wiki/images/cc-settings.png` via the `wiki-screenshots` skill (local dev build, no `VERSION` stamped, so the version badge stays uniform). Commit the refreshed PNG alongside the code.

- [ ] **Step 5: Tear down the dev build**

Stop the Control Center process. Remove any scratch PNGs from the repo root (only `src/docs/...` images are committed).

- [ ] **Step 6: Record the visual-verification marker**

Run: `python3 .claude/hooks/record_ui_verified.py src/ui/control-center.html`
Expected: it records the current content hash (this satisfies the `ui-visual-verify-gate` Stop hook). Run it AFTER the final edit to `control-center.html`.

- [ ] **Step 7: Commit**

```bash
git add src/ui/control-center.html src/docs/wiki/images/cc-settings.png
git commit -m "docs(solo): drop 'import collection first' device hint; refresh cc-settings

The device probe no longer needs a collection imported, so the General Settings
device hint points at obs-websocket instead. Wiki screenshot regenerated.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final: whole-branch review + suite

- [ ] Run the full suite: `python3 tools/run-tests.py` — expected all green.
- [ ] Run lint: `python3 tools/lint.py` — expected clean.
- [ ] Dispatch the whole-branch code review (superpowers:requesting-code-review).
- [ ] Do NOT open a PR / merge / release — that is the user's explicit call.

---

## Self-Review (plan vs. spec)

**Spec coverage:**
- `pick_input_kind` + matcher constants → Task 1. ✓
- `probe_device_options` (one connect, temp scene, disabled temp inputs, always-cleanup, best-effort) → Task 2. ✓
- Remove `enumerate_device_options` (+ its sole helper `input_not_found`) → Task 3. ✓
- Both callers repointed (CC route via `devices_enumerate_data`, CLI `device_scan_cmd`) → Task 3. ✓
- `device_property_name` reused unchanged (video + audio) → confirmed, no task edits it. ✓
- UX copy drop of "import the solo collection first" (CC `#dev-hint` + CLI exit) → Task 4 (CC) + Task 3 Step 4 (CLI). ✓
- Fake-session cleanup-guarantee test incl. mid-probe raise → Task 2 Steps 1-2. ✓
- macOS live-validated / Windows-Linux documented risk → in the code comment (Task 1) and spec; no separate task. ✓
- `.env` write path unchanged → not touched by any task. ✓
- `cc-settings.png` refresh + visual verification → Task 4. ✓

**Placeholder scan:** none — every code step carries the literal code; every command has an expected result.

**Type consistency:** `probe_device_options` returns `{"devices","note","mic","mic_note"}` in Task 2 and is consumed with exactly those keys in Task 3. `pick_input_kind(kind_list, matchers)` signature is identical in definition (Task 1) and call sites (Task 2). Constants `PROBE_SCENE_NAME`/`PROBE_VIDEO_INPUT`/`PROBE_MIC_INPUT` defined in Task 1, used in Task 2 and asserted in Task 2 tests.
