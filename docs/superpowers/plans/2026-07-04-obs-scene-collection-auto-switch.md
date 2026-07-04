# OBS Scene-Collection Auto-Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `racecast event start` auto-switch OBS to the active profile's scene collection (default-on, env kill-switch), so a prior league's collection can't linger on a shared multi-league box.

**Architecture:** A new pure decision function `scene_collection_action()` in `obs_ws.py` classifies an already-fetched collection status into an intent (`skip`/`ok`/`switch`/`warn_present`/`warn_absent`). `racecast.py`'s `_check_scene_collection()` becomes a thin executor that fetches status, calls the classifier, and either switches (via existing `set_scene_collection`) or prints the warning. A machine env flag `RACECAST_OBS_COLLECTION_SWITCH` gates the switch. The executor is reordered to run **before** `_refresh_obs_pages()` in `event_start`.

**Tech Stack:** Python 3 stdlib only. Tests are runnable scripts (no pytest), each `t_*` function auto-run under `if __name__ == "__main__"`.

## Global Constraints

- **Edit only under `src/`** (plus `docs/`, `tests/`, `.env.example`). Never touch `dist/`/`runtime/`.
- **Scripts and docs are English only.**
- **Best-effort contract:** every OBS interaction here must never raise and never block event bring-up — a failure prints one line and continues. Mirror `get_scene_collection`/`set_scene_collection`.
- **Env kill-switch parse:** falsey set is exactly `{"0", "false", "no", "off"}` (case-insensitive, stripped); absent/empty = enabled. Copied from `RACECAST_FEED_FANOUT` (`src/racecast.py:2198`).
- **Backward-compat:** racecast is released (v1.1.0). The `warn_present`/`warn_absent` output wording stays reachable and unchanged; only the default action on a mismatch changes.
- **Tests must run offline/hermetic** — no real OBS, no machine paths. Use the existing fake-OBS server and monkeypatch seams.
- After any Python change run `python3 tools/lint.py`.

---

### Task 1: Pure `scene_collection_action` classifier

**Files:**
- Modify: `src/scripts/obs_ws.py` (add function next to `scene_collection_status`, ~line 68)
- Test: `tests/test_obsws.py` (add `t_*` near the existing `scene_collection_status` tests, ~line 795+)

**Interfaces:**
- Consumes: the dict returned by `scene_collection_status(current, available, expected)` — keys `current`, `expected`, `available`, `match`, `expected_present`, `renamed_variant`.
- Produces: `scene_collection_action(status, note, switch_enabled) -> (action, detail)` where `action` ∈ `{"skip","ok","switch","warn_present","warn_absent"}`. `detail` is: the `note` string for `skip`; `status["current"]` for `ok`; `status["expected"]` for `switch`; the whole `status` dict for both `warn_*`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_obsws.py` (after the `t_scene_collection_status_*` block):

```python
# --------------------------------------------------------------------------
# Pure event-start decision — scene_collection_action
# --------------------------------------------------------------------------
def t_scene_collection_action_skip_when_no_status():
    assert m.scene_collection_action(None, "OBS closed", True) == ("skip", "OBS closed")


def t_scene_collection_action_ok_when_match():
    s = m.scene_collection_status("GT Endurance Racing", ["GT Endurance Racing"])
    assert m.scene_collection_action(s, "", True) == ("ok", "GT Endurance Racing")


def t_scene_collection_action_switch_when_mismatch_present_enabled():
    s = m.scene_collection_status("Other", ["GT Endurance Racing", "Other"])
    assert m.scene_collection_action(s, "", True) == ("switch", "GT Endurance Racing")


def t_scene_collection_action_warn_present_when_switch_disabled():
    s = m.scene_collection_status("Other", ["GT Endurance Racing", "Other"])
    action, detail = m.scene_collection_action(s, "", False)
    assert action == "warn_present" and detail is s        # dict passed through


def t_scene_collection_action_warn_absent_when_not_imported():
    s = m.scene_collection_status("Other", ["Other", "Foo"])
    action, detail = m.scene_collection_action(s, "", True)
    assert action == "warn_absent" and detail is s


def t_scene_collection_action_never_switches_to_renamed_variant():
    # expected exact name absent, only a "GT Endurance Racing 2" variant present
    s = m.scene_collection_status("GT Endurance Racing 2", ["GT Endurance Racing 2"])
    assert m.scene_collection_action(s, "", True)[0] == "warn_absent"
    assert s["renamed_variant"] == "GT Endurance Racing 2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_obsws.py`
Expected: FAIL — `AttributeError: module 'obs_ws' has no attribute 'scene_collection_action'`

- [ ] **Step 3: Implement the classifier**

In `src/scripts/obs_ws.py`, immediately after `scene_collection_status` (after its `return` at ~line 67), add:

```python
def scene_collection_action(status, note, switch_enabled):
    """Pure: decide what `event start` should do about the OBS scene collection.
    `status`/`note` are a get_scene_collection() result; `switch_enabled` is the
    RACECAST_OBS_COLLECTION_SWITCH gate. Returns (action, detail):
      ("skip", note)            OBS unreachable / no status — print note, do nothing
      ("ok", current)           already on the expected collection
      ("switch", expected)      mismatch, expected present, switch on -> switch to it
      ("warn_present", status)  mismatch, expected present, switch off -> warn
      ("warn_absent", status)   mismatch, expected not imported (incl. a renamed-only
                                variant — we never auto-switch to a renamed variant)
    The executor requests the switch with the exact expected name; set_scene_collection
    re-checks presence, so a renamed variant can never be selected."""
    if status is None:
        return ("skip", note)
    if status["match"]:
        return ("ok", status["current"])
    if not status["expected_present"]:
        return ("warn_absent", status)
    if not switch_enabled:
        return ("warn_present", status)
    return ("switch", status["expected"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_obsws.py`
Expected: `ALL PASS` (all `t_scene_collection_action_*` print `ok ...`)

- [ ] **Step 5: Commit**

```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): pure scene_collection_action classifier for event-start switch

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `_collection_switch_enabled` env gate

**Files:**
- Modify: `src/racecast.py` (add helper next to `_machine_env_value`, ~line 4234)
- Test: `tests/test_racecast.py` (add `t_*`, anywhere among the env tests)

**Interfaces:**
- Consumes: `_machine_env_value(name) -> str` (real env wins, then `.env` file, else `""`).
- Produces: `_collection_switch_enabled() -> bool`. True unless the flag is `0/false/no/off` (case-insensitive, stripped).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_racecast.py`:

```python
def t_collection_switch_enabled_default_on_and_optout():
    orig = m._machine_env_value
    try:
        m._machine_env_value = lambda name: ""                 # unset -> default on
        assert m._collection_switch_enabled() is True
        for off in ("0", "false", "no", "off", " OFF ", "False"):
            m._machine_env_value = lambda name, v=off: v
            assert m._collection_switch_enabled() is False, off
        for on in ("1", "true", "yes", "on", "anything"):
            m._machine_env_value = lambda name, v=on: v
            assert m._collection_switch_enabled() is True, on
    finally:
        m._machine_env_value = orig
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `AttributeError: module 'racecast' has no attribute '_collection_switch_enabled'`

- [ ] **Step 3: Implement the helper**

In `src/racecast.py`, immediately after `_machine_env_value` (after its `return ""` at ~line 4233), add:

```python
def _collection_switch_enabled():
    """Opt-OUT: `event start` auto-switches OBS to the active profile's scene
    collection by default. Setting the machine flag RACECAST_OBS_COLLECTION_SWITCH to a
    falsey value (0/false/no/off) restores the old warn-only behaviour; absent/empty
    means enabled. Mirrors the RACECAST_FEED_FANOUT parse convention."""
    return _machine_env_value("RACECAST_OBS_COLLECTION_SWITCH").strip().lower() \
        not in {"0", "false", "no", "off"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_racecast.py`
Expected: `t_collection_switch_enabled_default_on_and_optout` prints `ok`; suite ends `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(obs): RACECAST_OBS_COLLECTION_SWITCH env gate (default-on)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Executor rewrite + reorder in `event_start`

**Files:**
- Modify: `src/racecast.py` — rewrite `_check_scene_collection()` (~lines 3114-3137); reorder the call in `event_start` (~lines 3221-3222)
- Test: `tests/test_racecast.py` (two behavior tests)

**Interfaces:**
- Consumes: `obs_ws.get_scene_collection(expected=...)`, `obs_ws.scene_collection_action(...)` (Task 1), `obs_ws.set_scene_collection(name=...)`, `_active_obs_collection()`, `_collection_switch_enabled()` (Task 2).
- Produces: `_check_scene_collection()` — no return value; switches OBS or prints a status/warning line. Best-effort.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_racecast.py` (near the other event-start helpers). These monkeypatch the `obs_ws` module the executor imports, plus the two racecast seams:

```python
def _obsws_module():
    import sys as _sys
    SCRIPTS = os.path.join(ROOT, "src", "scripts")
    if SCRIPTS not in _sys.path:
        _sys.path.insert(0, SCRIPTS)
    import obs_ws
    return obs_ws


def t_check_scene_collection_switches_on_mismatch_when_enabled():
    import io, contextlib
    obs_ws = _obsws_module()
    expected = "GT Endurance Racing — demo"
    st = obs_ws.scene_collection_status(
        "Old League", ["Old League", expected], expected=expected)   # mismatch, present
    calls = {}
    saved = (obs_ws.get_scene_collection, obs_ws.set_scene_collection,
             m._active_obs_collection, m._collection_switch_enabled)
    try:
        obs_ws.get_scene_collection = lambda **kw: (st, "")
        def _fake_set(name, **kw):
            calls["name"] = name
            return (True, "")
        obs_ws.set_scene_collection = _fake_set
        m._active_obs_collection = lambda: expected
        m._collection_switch_enabled = lambda: True
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            m._check_scene_collection()
        assert calls.get("name") == expected, calls
        assert "switched to" in buf.getvalue(), buf.getvalue()
    finally:
        (obs_ws.get_scene_collection, obs_ws.set_scene_collection,
         m._active_obs_collection, m._collection_switch_enabled) = saved


def t_check_scene_collection_warns_not_switches_when_disabled():
    import io, contextlib
    obs_ws = _obsws_module()
    expected = "GT Endurance Racing — demo"
    st = obs_ws.scene_collection_status(
        "Old League", ["Old League", expected], expected=expected)
    calls = {}
    saved = (obs_ws.get_scene_collection, obs_ws.set_scene_collection,
             m._active_obs_collection, m._collection_switch_enabled)
    try:
        obs_ws.get_scene_collection = lambda **kw: (st, "")
        def _fake_set(name, **kw):
            calls["name"] = name
            return (True, "")
        obs_ws.set_scene_collection = _fake_set
        m._active_obs_collection = lambda: expected
        m._collection_switch_enabled = lambda: False              # kill-switch
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            m._check_scene_collection()
        assert "name" not in calls, "must not switch when disabled"
        out = buf.getvalue()
        assert "WARNING" in out and expected in out, out
    finally:
        (obs_ws.get_scene_collection, obs_ws.set_scene_collection,
         m._active_obs_collection, m._collection_switch_enabled) = saved
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — the enabled test fails its `"switched to"` assertion (today's `_check_scene_collection` only warns, never calls `set_scene_collection`), so `calls` is empty.

- [ ] **Step 3: Rewrite the executor**

In `src/racecast.py`, replace the whole `_check_scene_collection` function (currently ~lines 3114-3137) with:

```python
def _check_scene_collection():
    """At `event start`, align OBS's scene collection with the active profile.
    Default-on auto-switch (RACECAST_OBS_COLLECTION_SWITCH=0 -> warn-only, the old
    behaviour). Best-effort: never blocks bring-up. Safe to automate here because OBS
    refuses a collection switch while an output is active (set_scene_collection returns
    (False, ...)), and no output is active during bring-up. The manual fallback stays
    `racecast obs collection set` / the Control Center OBS row."""
    try:
        import obs_ws
        status, note = obs_ws.get_scene_collection(expected=_active_obs_collection())
    except Exception as exc:                         # noqa: BLE001 — best effort
        print(f"obs: scene collection check skipped ({exc}).")
        return
    action, detail = obs_ws.scene_collection_action(
        status, note, _collection_switch_enabled())
    if action == "skip":
        print(f"obs: scene collection check skipped — {detail}.")
    elif action == "ok":
        print(f"obs: scene collection '{detail}' active — correct.")
    elif action == "switch":
        ok, snote = obs_ws.set_scene_collection(name=detail)
        if ok:
            print(f"obs: scene collection switched to '{detail}' "
                  f"(was '{status['current']}').")
        else:
            print(f"obs: WARNING — could not switch to scene collection '{detail}' — "
                  f"{snote}. Switch with `racecast obs collection set` (or the OBS row "
                  f"in the Control Center) before going live.")
    elif action == "warn_present":
        print(f"obs: WARNING — scene collection '{detail['current']}' active, expected "
              f"'{detail['expected']}'. Switch with `racecast obs collection set` (or the "
              f"OBS row in the Control Center) before going live.")
    else:  # warn_absent
        print(f"obs: WARNING — scene collection '{detail['current']}' active, expected "
              f"'{detail['expected']}' not found in OBS — import it with `racecast setup` "
              f"before going live.")
```

- [ ] **Step 4: Reorder the call in `event_start`**

In `src/racecast.py` `event_start`, find (currently ~lines 3221-3222):

```python
    _refresh_obs_pages()
    _check_scene_collection()       # warn (never switch) if the wrong collection is up
```

Replace with (switch first so the source rebuild is followed by the refresh):

```python
    # Align OBS to the active profile's scene collection BEFORE refreshing pages — a
    # switch rebuilds every source, so a refresh must come after it (not be overwritten).
    _check_scene_collection()
    _refresh_obs_pages()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 tests/test_racecast.py`
Expected: both new tests print `ok`; suite ends `ALL PASS`.

- [ ] **Step 6: Lint**

Run: `python3 tools/lint.py`
Expected: no findings (exit 0).

- [ ] **Step 7: Commit**

```bash
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(obs): auto-switch OBS scene collection on event start

_check_scene_collection now switches (default) instead of warning, gated by
RACECAST_OBS_COLLECTION_SWITCH, and runs before the page-refresh hook so the
switch's source rebuild is followed by the refresh. event takeover inherits it.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Docs + full-suite gate

**Files:**
- Modify: `.env.example` (near the `RACECAST_FEED_FANOUT` block, ~line 19)
- Modify: `CLAUDE.md` (the `obs_ws.py` scene-collection sentence)
- Modify: `src/docs/wiki/Profiles.md:126-127`

- [ ] **Step 1: Document the env flag in `.env.example`**

After the `RACECAST_FEED_FANOUT` block (the `# RACECAST_FEED_FANOUT=0` line, ~line 19), insert a blank line then:

```
# OBS scene-collection auto-switch (DEFAULT ON). On `event start`, switch OBS to the
# active profile's scene collection when a different one is loaded, so a prior league's
# collection can't linger on a shared multi-league box. Safe: OBS refuses a switch while
# an output is active. Set to 0 for the old warn-only behaviour.
# RACECAST_OBS_COLLECTION_SWITCH=0
```

- [ ] **Step 2: Correct the CLAUDE.md sentence**

In `CLAUDE.md`, find:

```
It also exposes a scene-collection check/switch (`GetSceneCollectionList` / `SetCurrentSceneCollection`): `racecast obs collection [set]`, a warning during `racecast event start`, a line in `racecast event status`, and the Control Center's OBS row. Switching is always an explicit producer action — it rebuilds every source — never automatic.
```

Replace the final sentence ("Switching is always an explicit producer action — it rebuilds every source — never automatic.") with:

```
`racecast event start` auto-switches OBS to the active profile's collection by default (`RACECAST_OBS_COLLECTION_SWITCH=0` restores the old warn-only behaviour) — safe because OBS refuses a switch while an output is active and none is active during bring-up; `event takeover` inherits it. The switch runs before the page-refresh hook (it rebuilds every source). The manual `racecast obs collection set` and the Control Center OBS-row button remain the explicit fallback.
```

- [ ] **Step 3: Update the wiki Profiles page**

In `src/docs/wiki/Profiles.md`, replace lines 126-127:

```
Switching the OBS collection is always an explicit producer action (it rebuilds every
source) — it is never automatic. See [OBS & scenes](OBS-Setup).
```

with:

```
`racecast event start` auto-switches OBS to the active profile's collection by default,
so a prior league's collection can't linger on a shared box — it is safe because OBS
refuses a switch while an output is active. Set `RACECAST_OBS_COLLECTION_SWITCH=0` for
the old warn-only behaviour. The manual `racecast obs collection set` (above) and the
Control Center OBS-row button remain the explicit fallback; a switch rebuilds every
source. See [OBS & scenes](OBS-Setup).
```

- [ ] **Step 4: Validate wiki links/anchors**

Run: `python3 tests/test_wiki.py`
Expected: `ALL PASS` (body-only edit; no heading renamed, no anchor removed).

- [ ] **Step 5: Run the full suite + lint**

Run: `python3 tools/run-tests.py && python3 tools/lint.py`
Expected: whole suite passes; lint clean.

- [ ] **Step 6: Build verify (ships-safe check)**

Run: `python3 tools/build.py`
Expected: build + self-verify succeed (tokenization, no secrets, no shell scripts, preflight present).

- [ ] **Step 7: Commit**

```bash
git add .env.example CLAUDE.md src/docs/wiki/Profiles.md
git commit -m "docs(obs): document event-start scene-collection auto-switch + env flag

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Pure `scene_collection_action` (spec §1) → Task 1. ✓
- Executor rewrite + kill-switch (spec §2) → Task 2 (`_collection_switch_enabled`) + Task 3 (executor). ✓
- Ordering before `_refresh_obs_pages()` (spec §3) → Task 3 Step 4. ✓
- Takeover inherits (spec §4) → no code (calls `event_start`); noted in CLAUDE.md (Task 4). ✓
- Manual fallback unchanged (spec §5) → deliberately untouched; warn text routes to it. ✓
- Tests (spec) → Task 1 (5 branches), Task 2 (env parse), Task 3 (switch/no-switch behavior). ✓
- Docs (spec) → Task 4 (CLAUDE.md, .env.example, wiki). ✓
- No rendered UI change → no screenshot regen. ✓ (event-start output is CLI/CC job log.)

**Placeholder scan:** none — every code/test step shows full code.

**Type consistency:** `scene_collection_action(status, note, switch_enabled) -> (action, detail)` used identically in Task 1 (definition/tests) and Task 3 (executor). `_collection_switch_enabled() -> bool` defined in Task 2, called in Task 3. `set_scene_collection(name=...)` / `get_scene_collection(expected=...)` match existing signatures in `obs_ws.py`.
