# Auto-switch OBS to the Standby scene at `event start` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After `racecast event start` brings the stack up (scene-collection check → forced OBS refresh), park OBS on the **Standby** scene so the producer is ready to Start Streaming — default-on, kill-switchable, and never cutting a live program.

**Architecture:** One new best-effort helper in `obs_ws.py` (`switch_to_scene_if_idle`) does a guarded scene switch in a single obs-websocket session (read `GetStreamStatus`; skip when live; otherwise `SetCurrentProgramScene`). `racecast.py` gains a thin `_switch_to_standby()` wrapper + an opt-out env flag, called once at the end of `event_start` (inherited by `event_takeover`). Docs record the new step and flag.

**Tech Stack:** Python stdlib only. obs-websocket v5 via the existing `src/scripts/obs_ws.py` client. Tests are runnable scripts (no pytest), auto-discovered by the `t_*` convention.

## Global Constraints

- **Edit only under `src/`** for shipped code; `docs/` and `.env.example` are the other allowed touch points here. No edits to `dist/` or `runtime/`.
- **English only** in all code and docs.
- **No hardcoded secrets or machine paths.** The OBS-WebSocket password is auto-discovered by `obs_ws` / overridden via `.env`; the helper never takes a literal password.
- **Best-effort OBS contract:** every `obs_ws` helper returns a value and **never raises**; an unreachable OBS is a note, not a crash. `_switch_to_standby` never blocks or aborts bring-up.
- **Never cut a live program:** the switch must send **no** `SetCurrentProgramScene` when OBS output is active. This is the safety-critical invariant and has a dedicated test.
- **Tests run on any machine / CI:** use `127.0.0.1` + ephemeral ports (bind `("127.0.0.1", 0)`), the existing fake-OBS harness. No real IPs, no machine paths.
- **Mirror existing patterns:** `_standby_on_start_enabled()` mirrors `_collection_switch_enabled()` (`src/racecast.py:4251`) verbatim in shape; the fake-server test mirrors the `set_stream` / `set_scene_collection` tests.

---

### Task 1: `obs_ws.switch_to_scene_if_idle()` + unit coverage

**Files:**
- Modify: `src/scripts/obs_ws.py` (add one function after `set_current_program_scene`, which ends at `src/scripts/obs_ws.py:754`)
- Test: `tests/test_obsws.py` (add three `t_*` functions; the `__main__` runner auto-discovers them — no registration)

**Interfaces:**
- Consumes: existing module internals `_connect(host, port, password, timeout)` (returns `(session, note)`; `session is None` on failure) and `parse_stream_status(payload)` (returns a dict with key `"stream_active"`, a flattened `outputActive`).
- Produces: `switch_to_scene_if_idle(scene, host="127.0.0.1", port=None, password=None, timeout=2.0) -> (action, note)` where `action` is one of `"switched"`, `"live"`, `"error"`; `note` is `""` on the clean switch and a human-readable string otherwise. Consumed by Task 2's `_switch_to_standby()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_obsws.py`, directly after `t_set_scene_collection_unreachable_is_quiet` (ends at `tests/test_obsws.py:722`, near the other scene tests). These reuse the shared `_start_fake_obs(state)` helper (`tests/test_obsws.py:636`, returns `(port, srv)`) — the fake server already answers `GetStreamStatus` from `state["stream_active"]` and records a `SetCurrentProgramScene` into `state["set_scene"]` (`tests/test_obsws.py:417-428, 379-382`).

```python
# --------------------------------------------------------------------------
# switch_to_scene_if_idle — park OBS on Standby at `event start` (never cut live)
# --------------------------------------------------------------------------
def t_switch_to_scene_if_idle_switches_when_offline():
    state = {"stream_active": False, "program_scene": "Stint"}
    port, srv = _start_fake_obs(state)
    action, note = m.switch_to_scene_if_idle("Standby", port=port,
                                             password="supersecret", timeout=5)
    assert action == "switched", (action, note)
    assert note == "", note
    assert state["set_scene"] == "Standby"       # SetCurrentProgramScene was sent
    srv.close()


def t_switch_to_scene_if_idle_skips_when_live():
    state = {"stream_active": True, "program_scene": "Stint"}
    port, srv = _start_fake_obs(state)
    action, note = m.switch_to_scene_if_idle("Standby", port=port,
                                             password="supersecret", timeout=5)
    assert action == "live", (action, note)
    assert note                                  # explains why it was skipped
    assert "set_scene" not in state              # SAFETY: no scene switch sent while live
    assert state["program_scene"] == "Stint"     # program untouched
    srv.close()


def t_switch_to_scene_if_idle_unreachable_is_note_not_crash():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]
    sock.close()
    action, note = m.switch_to_scene_if_idle("Standby", port=free_port,
                                             password="x", timeout=0.5)
    assert action == "error", (action, note)
    assert note                                  # human-readable reason, did not raise
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_obsws.py`
Expected: FAIL — `AttributeError: module 'obs_ws' has no attribute 'switch_to_scene_if_idle'` (the runner stops at the first new `t_switch_*`).

- [ ] **Step 3: Implement `switch_to_scene_if_idle`**

Add to `src/scripts/obs_ws.py` immediately after `set_current_program_scene` (after line 754):

```python
def switch_to_scene_if_idle(scene, host="127.0.0.1", port=None,
                            password=None, timeout=2.0):
    """Switch OBS to `scene` ONLY when no stream output is active — never cut a
    live program. Reads GetStreamStatus first; if the stream is live, leaves the
    program scene untouched. Best effort — never raises (same contract as
    get_program_screenshot). Returns (action, note) where action is one of:
      "switched" — OBS was idle; SetCurrentProgramScene sent
      "live"     — OBS is streaming; NO switch sent (note explains)
      "error"    — could not reach OBS / a request failed (note has the reason)."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return "error", note
    try:
        status = parse_stream_status(session.request("GetStreamStatus", {}))
        if status.get("stream_active"):
            return "live", "OBS is streaming — left the program scene untouched"
        session.request("SetCurrentProgramScene", {"sceneName": scene})
        return "switched", ""
    except Exception as exc:                          # noqa: BLE001 — best-effort contract
        return "error", str(exc) or exc.__class__.__name__
    finally:
        session.close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_obsws.py`
Expected: PASS — ends with `ALL PASS`; the three new `ok t_switch_to_scene_if_idle_*` lines appear.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): switch_to_scene_if_idle — guarded scene switch that never cuts a live program"
```

---

### Task 2: Wire `_switch_to_standby()` into `event_start`

**Files:**
- Modify: `src/racecast.py` — add the `STANDBY_SCENE` constant, `_standby_on_start_enabled()`, `_switch_to_standby()`; add one call in `event_start`.

**Interfaces:**
- Consumes: Task 1's `obs_ws.switch_to_scene_if_idle(scene)`; existing `_machine_env_value(name)` (used by `_collection_switch_enabled`, `src/racecast.py:4256`).
- Produces: `_switch_to_standby()` — called once at the end of `event_start`, after `_refresh_obs_pages(force=True)`.

- [ ] **Step 1: Add the constant + env-flag helper**

In `src/racecast.py`, add `_standby_on_start_enabled()` directly after `_collection_switch_enabled()` (which ends at `src/racecast.py:4257`):

```python
def _standby_on_start_enabled():
    """Opt-OUT: `event start` parks OBS on the Standby scene by default. Setting the
    machine flag RACECAST_OBS_STANDBY_ON_START to a falsey value (0/false/no/off)
    disables it; absent/empty means enabled. Mirrors _collection_switch_enabled."""
    return _machine_env_value("RACECAST_OBS_STANDBY_ON_START").strip().lower() \
        not in {"0", "false", "no", "off"}
```

Add the `STANDBY_SCENE` module constant next to `EXPECTED_SCENE_COLLECTION` (grep for `EXPECTED_SCENE_COLLECTION =` in `src/racecast.py` and place it immediately below that line):

```python
STANDBY_SCENE = "Standby"   # canonical scene name in src/obs/GT_Endurance.json
```

- [ ] **Step 2: Add `_switch_to_standby()`**

In `src/racecast.py`, add directly after `_check_scene_collection()` (which ends at `src/racecast.py:3149`):

```python
def _switch_to_standby():
    """After bring-up, park OBS on the Standby scene (Director Guide: start on
    Standby, then Start Streaming). Default-on; RACECAST_OBS_STANDBY_ON_START=0
    disables. Best-effort: never blocks bring-up, and NEVER cuts a live program
    (switch_to_scene_if_idle skips when OBS output is active)."""
    if not _standby_on_start_enabled():
        return
    try:
        import obs_ws
    except Exception as exc:                          # noqa: BLE001 — best effort
        print(f"obs: standby switch skipped ({exc}).")
        return
    action, note = obs_ws.switch_to_scene_if_idle(STANDBY_SCENE)
    if action == "switched":
        print(f"obs: switched to the '{STANDBY_SCENE}' scene — ready to Start Streaming.")
    elif action == "live":
        print(f"obs: '{STANDBY_SCENE}' switch skipped — {note}.")
    else:  # error
        print(f"obs: '{STANDBY_SCENE}' switch skipped — {note}. "
              f"Switch to Standby manually before going live.")
```

- [ ] **Step 3: Add the call site in `event_start`**

In `src/racecast.py`, in `event_start`, immediately after the forced refresh (`src/racecast.py:3237`, `_refresh_obs_pages(force=True)`), add:

```python
    _check_scene_collection()
    _refresh_obs_pages(force=True)
    _switch_to_standby()          # park OBS on Standby, ready to Start Streaming
```

(Only the third line is new; the first two already exist.)

- [ ] **Step 4: Verify import + basic wiring**

There is no unit test for the `event_start` call site (bring-up spawns real processes; consistent with `_check_scene_collection` having none). Instead verify the module imports cleanly and the new symbols resolve:

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'src'); sys.path.insert(0,'src/scripts'); import importlib.util, os; spec=importlib.util.spec_from_file_location('racecast','src/racecast.py'); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); print(mod.STANDBY_SCENE); print(callable(mod._switch_to_standby), callable(mod._standby_on_start_enabled))"
```
Expected: prints `Standby` then `True True` with no traceback.

- [ ] **Step 5: Run the obs_ws + racecast test suites**

Run: `python3 tests/test_obsws.py && python3 tests/test_racecast.py`
Expected: both end in `ALL PASS`.

- [ ] **Step 6: Commit**

```bash
git add src/racecast.py
git commit -m "feat(obs): park OBS on Standby at event start (default-on, RACECAST_OBS_STANDBY_ON_START=0 opts out)"
```

---

### Task 3: Document the new step + kill-switch

**Files:**
- Modify: `.env.example` (add the commented flag next to the collection-switch flag at `.env.example:25`)
- Modify: `CLAUDE.md` (extend the obs_ws scene-collection paragraph at `CLAUDE.md:676`)

**Interfaces:** none (docs only).

- [ ] **Step 1: `.env.example`**

Insert a commented block directly **after** the existing `# RACECAST_OBS_COLLECTION_SWITCH=0` line (`.env.example:25`), matching the file's comment style:

```dotenv
# OBS Standby scene on `event start` (DEFAULT ON). After bring-up, park OBS on the
# Standby scene so the producer is ready to Start Streaming (Director Guide: start on
# Standby). Best-effort; never cuts a live program (skipped when OBS is already
# streaming). Set to 0 to leave OBS on whatever scene it was on.
# RACECAST_OBS_STANDBY_ON_START=0
```

- [ ] **Step 2: `CLAUDE.md`**

Extend the obs_ws paragraph at `CLAUDE.md:676` (the one describing the scene-collection check/switch during `event start`). Append one sentence after the collection-switch description, before "The canonical product name is …":

```
`racecast event start` also parks OBS on the **Standby** scene after the collection check and the forced page-refresh (Director Guide: start on Standby, then Start Streaming), default-on (`RACECAST_OBS_STANDBY_ON_START=0` opts out); it is best-effort and **never cuts a live program** — the switch is skipped when OBS output is already active (`obs_ws.switch_to_scene_if_idle`), which also makes a mid-event `event takeover` onto a streaming OBS a no-op.
```

- [ ] **Step 3: Verify the build's doc/secret gate still passes**

Run: `python3 tools/build.py`
Expected: exits 0 (`build.py`'s verify step checks no secrets / no shell scripts / tokenization — a doc + `.env.example` change must not break it).

- [ ] **Step 4: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs: document Standby-on-event-start step + RACECAST_OBS_STANDBY_ON_START"
```

---

## Final gates (after all tasks)

- [ ] `python3 tools/run-tests.py` — the whole suite, exactly what CI runs. Expected: `ALL TEST FILES PASS`.
- [ ] `python3 tools/lint.py` — ruff lint (the CI lint job). Expected: no findings.
- [ ] `python3 tools/build.py` — assemble + verify `dist/`. Expected: exit 0.

## Notes for the executor

- **No UI surface changes.** This plan touches no `*.html` / `src/ui/` file, so there is **no** wiki-screenshot obligation and **no** `ui-visual-verification` gate. Do not regenerate `director-panel.png`. (Stated explicitly so a reviewer does not flag their absence.)
- **`event takeover` needs no separate change** — it calls `event_start(...)` (`src/racecast.py:3429`), so it inherits `_switch_to_standby()`. The not-live guard makes a takeover onto an already-streaming OBS a no-op.
- **Scene name is a constant, not configurable** (YAGNI, per the spec). A league that renamed the scene uses the kill-switch.
