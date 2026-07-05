# Qualifying in the Event Start/Stop lifecycle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make qualifying a first-class broadcast session in the event start/stop loop — a `Q` row in the Producer tab becomes the active broadcast part in qualifying mode, reusing the last-part auto-stop → report → teardown 1:1, with mode-correct submissions and a mode-aware Director Panel.

**Architecture:** The relay already exposes a mode-aware `relay.source` property, so cockpit / race-control / `/schedule/data` / submission *target* resolution follow the mode for free. This plan adds (1) a pure `Q`-vs-race part classifier and mode-gates the Producer parts, (2) a label-based confirm phrase (`START PART Q`), (3) a `— Qualifying` report-title marker, (4) a Control Center qualifying toggle, (5) submission approve routing to the Qualifying tab, and (6) mode-aware Director-Panel section display.

**Tech Stack:** Pure Python 3 stdlib (no framework, no package manager). Tests are standalone runnable scripts (`python3 tests/test_X.py`), not pytest. Relay = `src/relay/racecast-feeds.py` (hyphenated → loaded by path in tests). Pure logic in `src/scripts/`. UI in `src/ui/` (Control Center) and `src/director/` (panel).

## Global Constraints

- **Edit only under `src/`, `tests/`, `docs/`.** `dist/`/`runtime/` are generated — never hand-edit.
- **English only** in all code and docs.
- **Python stdlib only** — no new runtime dependencies.
- **No secrets / machine paths** in code, tests, or docs. Tests run on any machine + CI (no real IPs/paths).
- **Outbound HTTP for `racecast.py` goes through the existing `http_util`-backed helpers** (reuse `_relay_fetch_json`; never add a bare `urllib`/`urlopen`). The loopback `127.0.0.1:8088` relay is fine.
- **Best-effort contract:** relay OBS/network helpers never raise — a failure logs/notes and flow continues.
- **Backward compatibility:** the product is released (v1.1.0). No CLI flag is removed or renamed. Old `part.json` / `cockpit-pending.json` files keep working. A Producer tab without a `Q` row behaves exactly as today.
- **Any visible Control Center or Director Panel change requires refreshing its wiki screenshot in the same change** (`cc-*.png`, `director-panel.png`) — see Task 8.
- Run `python3 tools/lint.py` after changing any Python file; `python3 tools/run-tests.py` is the full suite CI runs.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/scripts/producer.py` | Pure Producer-tab parser | + `part_kind`, `active_producer_rows` |
| `src/scripts/parts.py` | Pure Part view-model + validators | label-based confirm token; new `validate_*` signatures |
| `src/relay/racecast-feeds.py` | Relay (I/O) | mode-gate `/parts/*`; `PartStore.reset`; `/mode` part reset; submission mode capture + approve routing |
| `src/racecast.py` | Operator CLI | `_relay_mode`, `_qualifying_title`; apply to report title/filename/Discord |
| `src/scripts/cockpit_submissions.py` | Pure submission store | + `mode` field |
| `src/ui/ui_ops.py` | Control Center op → argv | + `_qualifying_flag` in `event-start` params |
| `src/ui/control-center.html` | Control Center UI | qualifying checkbox at Start Event |
| `src/director/director-panel.html` | Director Panel | mode-aware section display + QUALI submission tag |
| `tests/test_parts.py` | parts + producer + relay parts unit checks | new cases |
| `tests/test_racecast.py` | CLI unit checks | report-title marker |
| `tests/test_ui_ops.py` | Control Center op argv | qualifying flag |
| `tests/test_submissions.py` | submission store + endpoints | mode field + approve routing |
| `tests/test_director_panel.py` | panel markup anchors | mode-visibility + QUALI tag |

---

### Task 1: Producer part classifier (pure)

**Files:**
- Modify: `src/scripts/producer.py` (append two functions after `parse_producer_rows`)
- Test: `tests/test_parts.py`

**Interfaces:**
- Produces: `producer.part_kind(label) -> "qualifying" | "race"`; `producer.active_producer_rows(rows, mode) -> list[dict]` (subset of parsed Producer rows whose `part_kind` matches `mode`; order preserved).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_parts.py`. First add the import near the top (after the existing `import parts as m`):

```python
import producer as pm  # pure Producer-tab classifier (same sys.path as parts)
```

Then add the test functions:

```python
def t_part_kind_classifies_q_vs_numeric():
    assert pm.part_kind("Q") == "qualifying"
    assert pm.part_kind("q") == "qualifying"
    assert pm.part_kind(" Qualifying ") == "qualifying"
    assert pm.part_kind("Q1") == "qualifying"
    assert pm.part_kind("Part 1") == "race"
    assert pm.part_kind("1") == "race"
    assert pm.part_kind("") == "race"
    assert pm.part_kind(None) == "race"


def t_active_producer_rows_filters_by_mode():
    rows = [{"part": "Part 1"}, {"part": "Q"}, {"part": "Part 2"}]
    race = pm.active_producer_rows(rows, "race")
    assert [r["part"] for r in race] == ["Part 1", "Part 2"]
    qual = pm.active_producer_rows(rows, "qualifying")
    assert [r["part"] for r in qual] == ["Q"]
    # unknown mode -> race subset; empty/None -> []
    assert [r["part"] for r in pm.active_producer_rows(rows, "x")] == ["Part 1", "Part 2"]
    assert pm.active_producer_rows([], "race") == []
    assert pm.active_producer_rows(None, "qualifying") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_parts.py`
Expected: FAIL — `AttributeError: module 'producer' has no attribute 'part_kind'` (or an ImportError until the import line resolves; the functions do not exist yet).

- [ ] **Step 3: Write minimal implementation**

Append to `src/scripts/producer.py`:

```python
def part_kind(label):
    """Classify a Producer part by its label: 'qualifying' when the trimmed,
    uppercased label starts with 'Q' (Q, Q1, Qualifying, …), else 'race'
    (numeric / 'Part N'). The qualifying broadcast is modelled as a 'Q' row in
    the same Producer tab, so the Parts control can show the race parts in race
    mode and the single Q part in qualifying mode."""
    return "qualifying" if str(label or "").strip().upper().startswith("Q") else "race"


def active_producer_rows(rows, mode):
    """The subset of parsed Producer rows whose part_kind matches the relay mode:
    'qualifying' -> the Q rows, anything else -> the race/numeric rows. Order is
    preserved. Empty/None rows -> []."""
    want = "qualifying" if mode == "qualifying" else "race"
    return [r for r in (rows or []) if part_kind(r.get("part")) == want]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_parts.py`
Expected: PASS — ends with `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/producer.py tests/test_parts.py
git commit -m "feat(parts): classify Producer parts as qualifying (Q) vs race"
```

---

### Task 2: Label-based confirm phrase (pure)

**Files:**
- Modify: `src/scripts/parts.py` (`parts_intent_phrase`, `parts_view_model`, `validate_start`, `validate_end`; add `part_confirm_token`)
- Test: `tests/test_parts.py`

**Interfaces:**
- Produces: `parts.part_confirm_token(label) -> str` (`"Part 1"`→`"1"`, `"Q"`→`"Q"`, `"Part Q"`→`"Q"`); `parts.parts_intent_phrase(action, token) -> str`; `parts.validate_start(body, rows, state)` and `parts.validate_end(body, rows, state)` — **note the new `rows` parameter** (a list of Producer-row dicts, already mode-gated by the caller). Return contract unchanged: `(True, index)` or `(False, (error, http_status))`.
- Consumes (Task 3 relies on): `validate_start(body, rows, state)`, `validate_end(body, rows, state)`, and `parts_view_model(rows, state, stream_active)` now emitting label-based `confirm_phrase`.

- [ ] **Step 1: Write the failing test**

Update the existing `t_parts_intent_phrase` in `tests/test_parts.py` and add token/phrase cases:

```python
def t_parts_intent_phrase():
    assert m.parts_intent_phrase("start", "1") == "START PART 1"
    assert m.parts_intent_phrase("end", "3") == "END PART 3"
    assert m.parts_intent_phrase("start", "Q") == "START PART Q"


def t_part_confirm_token():
    assert m.part_confirm_token("Part 1") == "1"
    assert m.part_confirm_token("part 2") == "2"
    assert m.part_confirm_token("Q") == "Q"
    assert m.part_confirm_token("Part Q") == "Q"
    assert m.part_confirm_token("  Part   3 ") == "3"


def t_view_model_qualifying_confirm_phrase():
    # A single Q row, ready to start -> confirm phrase reads START PART Q.
    q = [{"part": "Q", "producer": "A"}]
    vm = m.parts_view_model(q, {"index": 1, "live": False}, stream_active=False)
    assert vm["action"] == "start" and vm["confirm_phrase"] == "START PART Q"
    vm2 = m.parts_view_model(q, {"index": 1, "live": False}, stream_active=True)
    assert vm2["action"] == "end" and vm2["confirm_phrase"] == "END PART Q"
```

Replace the four existing `validate_*` tests to pass `rows` (the ROWS3 fixture) instead of a bare count, and add a Q case:

```python
def t_validate_start_ok():
    ok, res = m.validate_start({"index": 1, "intent": "START PART 1"},
                               ROWS3, {"index": 1, "live": False})
    assert ok and res == 1


def t_validate_start_bad_phrase():
    ok, res = m.validate_start({"index": 1, "intent": "go"},
                               ROWS3, {"index": 1, "live": False})
    assert not ok and res[1] == 403


def t_validate_start_wrong_index():
    ok, res = m.validate_start({"index": 2, "intent": "START PART 2"},
                               ROWS3, {"index": 1, "live": False})
    assert not ok and res[1] == 409


def t_validate_start_bad_index_type():
    ok, res = m.validate_start({"index": "x", "intent": "START PART x"},
                               ROWS3, {"index": 1, "live": False})
    assert not ok and res[1] == 400


def t_validate_start_qualifying_token():
    q = [{"part": "Q"}]
    ok, res = m.validate_start({"index": 1, "intent": "START PART Q"},
                               q, {"index": 1, "live": False})
    assert ok and res == 1
    bad, r2 = m.validate_start({"index": 1, "intent": "START PART 1"},
                               q, {"index": 1, "live": False})
    assert not bad and r2[1] == 403          # numeric phrase rejected for a Q part


def t_validate_end_ok():
    ok, res = m.validate_end({"intent": "END PART 2"}, ROWS3, {"index": 2, "live": True})
    assert ok and res == 2


def t_validate_end_bad_phrase():
    ok, res = m.validate_end({"intent": "nope"}, ROWS3, {"index": 2, "live": True})
    assert not ok and res[1] == 403


def t_validate_end_qualifying_token():
    q = [{"part": "Q"}]
    ok, res = m.validate_end({"intent": "END PART Q"}, q, {"index": 1, "live": True})
    assert ok and res == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_parts.py`
Expected: FAIL — `AttributeError: module 'parts' has no attribute 'part_confirm_token'`, and the `validate_*` calls raise `TypeError` (old 3-arg signature took a count, not rows) once the attribute exists.

- [ ] **Step 3: Write minimal implementation**

In `src/scripts/parts.py`, replace `parts_intent_phrase` and add `part_confirm_token` above it:

```python
def part_confirm_token(label):
    """The token shown in a Part's confirmation phrase. A leading 'Part'
    (case-insensitive) plus whitespace is stripped, so a numeric race label
    'Part 1' -> '1' (today's 'START PART 1' is unchanged) and a qualifying label
    'Q' -> 'Q' (or 'Part Q' -> 'Q'). Falls back to the trimmed label."""
    s = " ".join(str(label or "").split())
    if s.upper().startswith("PART"):
        rest = s[4:].strip()
        return rest or s
    return s


def parts_intent_phrase(action, token):
    """The exact confirmation phrase for an action on a Part, keyed by the Part's
    confirm token (see part_confirm_token): ('start', '2') -> 'START PART 2',
    ('end', 'Q') -> 'END PART Q'. The panel shows it and the relay re-validates
    the typed value against it."""
    return "{} PART {}".format(str(action).upper(), token)
```

In `parts_view_model`, replace the two `confirm_phrase` assignments so they use the acting row's label token:

```python
    if live:
        li = index if 1 <= index <= count else count
        vm["index"] = li
        vm["current_label"] = parts[li - 1]["label"]
        vm["producer"] = parts[li - 1]["producer"]
        vm["action"] = "end"
        vm["confirm_phrase"] = parts_intent_phrase(
            "end", part_confirm_token(parts[li - 1]["label"]))
    elif index > count:
        vm["complete"] = True
    else:
        vm["current_label"] = parts[index - 1]["label"]
        vm["producer"] = parts[index - 1]["producer"]
        vm["action"] = "start"
        vm["confirm_phrase"] = parts_intent_phrase(
            "start", part_confirm_token(parts[index - 1]["label"]))
        vm["next_index"] = index + 1 if index + 1 <= count else None
    return vm
```

Replace `validate_start` and `validate_end` with the rows-aware versions (the token is derived from the row label; an out-of-range index falls back to a numeric token so the pre-existing behavior is preserved):

```python
def _row_token(rows, idx):
    """Confirm token for the 1-based Part idx from its row label, or the numeric
    fallback 'idx' when idx is out of range (preserves the pre-label behavior)."""
    count = len(rows)
    label = rows[idx - 1].get("part") if 1 <= idx <= count else None
    return part_confirm_token(label or "Part {}".format(idx))


def validate_start(body, rows, state):
    """Validate a /parts/start request against the mode-gated Producer rows. Pure.
    Returns (True, index) or (False, (error, http_status)). The typed intent phrase
    is the anti-accident gate; the index must equal the expected next Part."""
    count = len(rows)
    try:
        idx = int(body.get("index"))
    except (TypeError, ValueError):
        return False, ("index must be a number", 400)
    if normalize_intent(body.get("intent")) != parts_intent_phrase("start", _row_token(rows, idx)):
        return False, ("confirmation phrase mismatch", 403)
    if idx != int(state.get("index", 1)) or not (1 <= idx <= count):
        return False, ("Part {} is not the next Part to start".format(idx), 409)
    return True, idx


def validate_end(body, rows, state):
    """Validate a /parts/end request against the currently-focused Part. Pure."""
    idx = int(state.get("index", 1))
    if normalize_intent(body.get("intent")) != parts_intent_phrase("end", _row_token(rows, idx)):
        return False, ("confirmation phrase mismatch", 403)
    return True, idx
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_parts.py`
Expected: PASS — `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/parts.py tests/test_parts.py
git commit -m "feat(parts): label-based confirm phrase (START PART Q)"
```

---

### Task 3: Relay — mode-gate the Parts control + reset on mode switch

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `PartStore.reset` (after `PartStore.end`, ~line 1507); `/parts/data` (~6880); `/parts/start` (~7429); `/parts/end` (~7465-7476); `/mode` endpoint (~7125)
- Test: `tests/test_parts.py` (uses the `R` relay module already loaded there)

**Interfaces:**
- Consumes: `producer_mod.active_producer_rows` (Task 1), `parts_mod.validate_start(body, rows, state)` / `validate_end(body, rows, state)` (Task 2).
- Produces: `R.PartStore.reset() -> {"index": 1, "live": False}`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_parts.py`:

```python
def t_partstore_reset():
    import tempfile, os
    d = tempfile.mkdtemp()
    ps = R.PartStore(os.path.join(d, "part.json"))
    ps.mark_live(3)
    assert ps.get() == {"index": 3, "live": True}
    assert ps.reset() == {"index": 1, "live": False}
    # persisted -> a fresh store reloads the reset pointer
    assert R.PartStore(os.path.join(d, "part.json")).get() == {"index": 1, "live": False}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_parts.py`
Expected: FAIL — `AttributeError: 'PartStore' object has no attribute 'reset'`.

- [ ] **Step 3: Write minimal implementation**

In `src/relay/racecast-feeds.py`, add `reset` to `PartStore` (right after the `end` method):

```python
    def reset(self):
        """Reset the pointer to the first part, not-live — used by `event start`
        (via the file) and on a live `/mode` switch so the mode-gated Parts
        control never carries a stale index into the other mode's subset."""
        with self.lock:
            self.state = default_part_state()
            self._save_file()
            return dict(self.state)
```

Mode-gate `/parts/data` — replace `rows = producer_source.get()` (in the `["parts", "data"]` branch) with:

```python
                        rows = producer_mod.active_producer_rows(
                            producer_source.get(), relay.mode)
```

Mode-gate `/parts/start` — replace `rows = producer_source.get()` and the validate call:

```python
                    rows = producer_mod.active_producer_rows(
                        producer_source.get(), relay.mode)
                    ok, res = parts_mod.validate_start(body, rows, part_store.get())
```

Mode-gate `/parts/end` — move the rows fetch above `validate_end`, mode-gate it, and pass it to both `validate_end` and `parts_view_model`:

```python
                if p == ["parts", "end"]:
                    if part_store is None or _obs_ws is None:
                        return self._send({"ok": False, "error": "parts unavailable"}, 503)
                    rows = (producer_mod.active_producer_rows(producer_source.get(), relay.mode)
                            if producer_source is not None else [])
                    ok, res = parts_mod.validate_end(body, rows, part_store.get())
                    if not ok:
                        return self._send({"ok": False, "error": res[0]}, res[1])
                    ok2, note = _obs_ws.set_stream(False)
                    if not ok2:
                        return self._send({"ok": False, "error": note}, 503)
                    pre_vm = parts_mod.parts_view_model(rows, part_store.get(),
                                                        stream_active=True)
```

(Leave the rest of `/parts/end` — `is_last`, `part_store.end()`, health event, `_spawn_event_stop` — unchanged. Delete the now-duplicate `rows = producer_source.get() …` line that sat below `set_stream(False)`.)

Add the part-pointer reset to the `/mode` endpoint. Find the handler at ~line 7125 (`res = relay.set_mode(p[1].lower())`) and add the reset after a successful switch, before returning:

```python
                    res = relay.set_mode(p[1].lower())
                    if not res.get("error"):
                        _push_live_schedule(relay, setup_ctl)
                        # Re-point the broadcast-part pointer to the new mode's first
                        # part, unless a part is currently live (never disturb an
                        # on-air broadcast). Keeps the mode-gated Parts control
                        # coherent across a live race<->qualifying switch.
                        if part_store is not None and not part_store.get().get("live"):
                            part_store.reset()
                    return self._send(res)
```

(If the existing handler already calls `_push_live_schedule` on success, fold the reset into that same success branch rather than duplicating it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_parts.py`
Expected: PASS — `ALL PASS`.

- [ ] **Step 5: Grep for any other stale caller of the changed signatures**

Run: `grep -rn "validate_start\|validate_end\|parts_intent_phrase" src tools`
Expected: only `src/scripts/parts.py` (definitions) and `src/relay/racecast-feeds.py` (`parts_mod.validate_start(body, rows, …)`, `parts_mod.validate_end(body, rows, …)`). No other caller passes the old signature. If any other caller appears, update it to the rows-aware signature.

- [ ] **Step 6: Sanity-check the relay still imports**

Run: `python3 -c "import importlib.util,os; s=importlib.util.spec_from_file_location('r','src/relay/racecast-feeds.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print('import ok')"`
Expected: `import ok`.

- [ ] **Step 7: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_parts.py
git commit -m "feat(relay): mode-gate the Parts control (Q part in qualifying mode)"
```

---

### Task 4: Report title — `— Qualifying` marker

**Files:**
- Modify: `src/racecast.py` — add `_relay_mode` + `_qualifying_title` after `_report_event_title` (~1327); apply in `_build_report_file` (~1365) and `_send_report_core` (~1397)
- Test: `tests/test_racecast.py` (module var `m`)

**Interfaces:**
- Consumes: existing `_relay_fetch_json(url)` and `RELAY_PORT`.
- Produces: `racecast._relay_mode() -> "race" | "qualifying" | None`; `racecast._qualifying_title(base) -> str`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_racecast.py` (module is imported as `m`):

```python
def t_qualifying_title_marks_when_qualifying():
    orig = m._relay_mode
    try:
        m._relay_mode = lambda: "qualifying"
        assert m._qualifying_title("Le Mans 24h") == "Le Mans 24h — Qualifying"
        assert m._qualifying_title("") == "Qualifying"
        m._relay_mode = lambda: "race"
        assert m._qualifying_title("Le Mans 24h") == "Le Mans 24h"
        m._relay_mode = lambda: None
        assert m._qualifying_title("Le Mans 24h") == "Le Mans 24h"
    finally:
        m._relay_mode = orig
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `AttributeError: module 'racecast' has no attribute '_relay_mode'`.

- [ ] **Step 3: Write minimal implementation**

In `src/racecast.py`, add after `_report_event_title` (~line 1327):

```python
def _relay_mode():
    """The live relay's schedule mode ('race'/'qualifying') from /status, or None
    when the relay is unreachable. Best-effort — the report title marker degrades
    gracefully. Reuses the loopback JSON helper (no bare urllib)."""
    try:
        data = _relay_fetch_json(f"http://127.0.0.1:{RELAY_PORT}/status")
        mode = data.get("mode")
        return mode if mode in ("race", "qualifying") else None
    except Exception:  # noqa: BLE001 — best-effort
        return None


def _qualifying_title(base):
    """Append ' — Qualifying' to a report/event title when the live relay is in
    qualifying mode; an empty base becomes just 'Qualifying'. Unchanged otherwise."""
    if _relay_mode() == "qualifying":
        return f"{base} — Qualifying" if base else "Qualifying"
    return base
```

In `_build_report_file`, wrap the title (line ~1365):

```python
    title = _qualifying_title(_report_event_title())
```

In `_send_report_core`, wrap the title (line ~1397):

```python
    title = _qualifying_title(_report_event_title() or league or "Event")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_racecast.py`
Expected: PASS — the file prints its `ok …` lines and `ALL PASS` (or equivalent success footer).

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(report): mark the post-event report title with — Qualifying in qualifying mode"
```

---

### Task 5: Control Center — qualifying toggle at Start Event

**Files:**
- Modify: `src/ui/ui_ops.py` — add `_qualifying_flag`; extend `PARAMS["event-start"]`
- Modify: `src/ui/control-center.html` — a checkbox next to `#stint` (~line 570); include it in `opEventStart` (~line 1850)
- Test: `tests/test_ui_ops.py`

**Interfaces:**
- Consumes: existing `build_argv(name, params)` and the `["event", "start"]` base op.
- Produces: `event-start` accepts a `qualifying` param → appends `--qualifying`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui_ops.py`:

```python
def t_event_start_qualifying_flag():
    assert ui_ops.build_argv("event-start", {"qualifying": True}) == ["event", "start", "--qualifying"]
    # composes with stint; falsy/absent omits the flag
    argv = ui_ops.build_argv("event-start", {"stint": "3", "qualifying": True})
    assert "--stint" in argv and "3" in argv and "--qualifying" in argv
    assert ui_ops.build_argv("event-start", {"qualifying": False}) == ["event", "start"]
    assert ui_ops.build_argv("event-start", {}) == ["event", "start"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_ui_ops.py`
Expected: FAIL — `ValueError: unknown parameter 'qualifying' for event-start` (the param is not registered yet).

- [ ] **Step 3: Write minimal implementation**

In `src/ui/ui_ops.py`, add a flag builder next to `_update_flag` (~line 82):

```python
def _qualifying_flag(value):
    """`--qualifying` starts the event in qualifying mode (Feed A serves the
    Qualifying tab; the Parts control operates on the Q broadcast part)."""
    return ["--qualifying"] if value else []
```

Extend the `event-start` entry in `PARAMS` (~line 126):

```python
    "event-start": {"stint": _stint_arg, "qualifying": _qualifying_flag},
```

In `src/ui/control-center.html`, add a checkbox right after the `#stint` input (line 570), before the Start-event button:

```html
          <label class="chk" title="Start the event in qualifying mode (Feed A serves the Qualifying tab)">
            <input id="event-qualifying" type="checkbox"> Qualifying</label>
```

Update `opEventStart()` (~line 1850) to include the flag:

```javascript
function opEventStart() {
  const v = $('stint').value.trim();
  const params = {};
  if (v) params.stint = v;
  if ($('event-qualifying').checked) params.qualifying = true;
  op('event-start', true, params);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_ui_ops.py`
Expected: PASS.

- [ ] **Step 5: Verify the panel markup anchors (no JS runtime)**

Run: `grep -n 'id="event-qualifying"' src/ui/control-center.html`
Expected: one match (the checkbox). The screenshot is regenerated in Task 8.

- [ ] **Step 6: Commit**

```bash
git add src/ui/ui_ops.py src/ui/control-center.html tests/test_ui_ops.py
git commit -m "feat(ui): qualifying toggle at Control Center Start Event"
```

---

### Task 6: Submissions — record mode, approve into the right tab

**Files:**
- Modify: `src/scripts/cockpit_submissions.py` — `_validate_entry` (tolerant of + defaulting `mode`), `add_pending` (accept `mode`)
- Modify: `src/relay/racecast-feeds.py` — `/cockpit/submit` (~7230, pass `relay.mode`); `/submissions/approve` (~7338, branch writer)
- Test: `tests/test_submissions.py`

**Interfaces:**
- Consumes: existing `SetupControl.schedule_set(row, url, name, stint)` and `SetupControl.qualifying_set(row, url, name, stint)` (both already in the relay).
- Produces: submission entries carry `mode: "race" | "qualifying"` (default `"race"` for old files); `add_pending(..., mode="race")`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_submissions.py` (it uses `_load(name, rel)` to import modules — load `cockpit_submissions` the same way the file already does; reuse the existing loaded handle if present):

```python
def t_add_pending_records_mode():
    cs = _load("cockpit_submissions", ["src", "scripts", "cockpit_submissions.py"])
    d = tempfile.mkdtemp()
    path = os.path.join(d, "pending.json")
    e = cs.add_pending(path, streamer_key="alice", streamer_name="Alice",
                       target_line=5, target_stint="Q", proposed_url="https://youtu.be/x",
                       prev_url="", now=1.0, mode="qualifying")
    assert e["mode"] == "qualifying"
    # default when omitted
    e2 = cs.add_pending(path, streamer_key="bob", streamer_name="Bob",
                        target_line=6, target_stint="2", proposed_url="https://youtu.be/y",
                        prev_url="", now=2.0)
    assert e2["mode"] == "race"


def t_validate_entry_defaults_missing_mode_to_race():
    cs = _load("cockpit_submissions", ["src", "scripts", "cockpit_submissions.py"])
    legacy = {"id": 1, "streamer_key": "alice", "streamer_name": "Alice",
              "target_line": 5, "target_stint": "Q", "proposed_url": "https://youtu.be/x",
              "prev_url": "", "ts": 1.0}          # no mode field (pre-upgrade entry)
    seq, entries = cs.validate_pending({"seq": 1, "pending": [legacy]})
    assert entries[0]["mode"] == "race"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_submissions.py`
Expected: FAIL — `KeyError: 'mode'` (add_pending does not store it; `_validate_entry` does not emit it).

- [ ] **Step 3: Write minimal implementation**

In `src/scripts/cockpit_submissions.py`, update the entry docstring line (12-14) to include `mode`, then update `_validate_entry` to validate + default it (add before the `return`):

```python
    mode = e.get("mode", "race")
    if mode not in ("race", "qualifying"):
        raise ValueError(f"bad mode: {mode!r}")
    return {"id": e["id"], "streamer_key": key, "streamer_name": e["streamer_name"],
            "target_line": line, "target_stint": e["target_stint"],
            "proposed_url": e["proposed_url"], "prev_url": e["prev_url"],
            "ts": e["ts"], "mode": mode}
```

Update `add_pending` to accept and store `mode` (default `"race"`):

```python
def add_pending(path, *, streamer_key, streamer_name, target_line, target_stint,
                proposed_url, prev_url, now, mode="race", max_pending=MAX_PENDING):
    """Append a new pending entry with a fresh monotonic id, cap the list to
    *max_pending* (dropping the oldest), persist, and return the stored entry.
    `mode` ('race'/'qualifying') records which schedule tab the entry targets so
    approve writes back to the correct tab."""
    seq, entries = _load(path)
    seq += 1
    entry = {"id": seq, "streamer_key": streamer_key, "streamer_name": streamer_name,
             "target_line": int(target_line), "target_stint": target_stint,
             "proposed_url": proposed_url, "prev_url": prev_url, "ts": now, "mode": mode}
    entries.append(_validate_entry(entry))
    if len(entries) > max_pending:
        entries = entries[-max_pending:]
    _write(path, seq, entries)
    return entry
```

In `src/relay/racecast-feeds.py` `/cockpit/submit` (~7230), pass the current mode when creating the entry:

```python
                        entry = submission_store.add(
                            streamer_key=me,
                            streamer_name=res["streamer_name"] or me,
                            target_line=res["target_line"],
                            target_stint=res["target_stint"],
                            proposed_url=url, prev_url=res["prev_url"],
                            now=time.time(), mode=relay.mode)
```

In `/submissions/approve` (~7338), branch the writer on the entry's recorded mode (the entry's tab, not the relay's current mode):

```python
                        writer = (setup_ctl.qualifying_set
                                  if entry.get("mode") == "qualifying"
                                  else setup_ctl.schedule_set)
                        res = writer(
                            entry["target_line"], url=entry["proposed_url"],
                            name=entry["streamer_name"], stint=entry["target_stint"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_submissions.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/cockpit_submissions.py src/relay/racecast-feeds.py tests/test_submissions.py
git commit -m "feat(submissions): record mode and approve qualifying links into the Qualifying tab"
```

---

### Task 7: Director Panel — mode-aware section display + QUALI tag

**Files:**
- Modify: `src/director/director-panel.html` — `relayPoll` (~line 1416, add section visibility); `subRow` (~2095, QUALI tag)
- Test: `tests/test_director_panel.py`

**Interfaces:**
- Consumes: the always-on `relayPoll()` `/status` read (already has `d.mode === "qualifying"` at ~1414). Element ids: `#urlsBox` (race schedule editor), `#qualRow` (qualifying editor row), always-visible: `#qualOn`/`#qualOff` (mode toggle), `#subsBox`, `#partControl`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_director_panel.py`:

```python
def t_mode_drives_section_visibility():
    h = _html()
    # relayPoll toggles the race schedule editor and the qualifying editor row by mode
    assert '$("#urlsBox").hidden = qualifying' in h
    assert '$("#qualRow").hidden = !qualifying' in h


def t_qualifying_submission_tag_present():
    h = _html()
    # subRow renders a QUALI tag when the pending entry is a qualifying submission
    assert 'QUALI' in h
    assert 'e.mode === "qualifying"' in h
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_director_panel.py`
Expected: FAIL — `AssertionError: missing …` (the anchors don't exist yet).

- [ ] **Step 3: Write minimal implementation**

In `src/director/director-panel.html` `relayPoll`, right after the qualifying warn-line block (after line 1415, before `$("#feedHealth").innerHTML = …`), add the section toggle:

```javascript
    const qualifying = d.mode === "qualifying";
    // Show the schedule editor matching the active mode. The mode toggle,
    // submissions, and Parts control stay visible in both modes.
    if ($("#urlsBox")) $("#urlsBox").hidden = qualifying;
    if ($("#qualRow")) $("#qualRow").hidden = !qualifying;
```

In `subRow(e)` (~line 2095), prepend a QUALI tag to the streamer cell for qualifying entries. Replace the `tr.innerHTML = …` assignment with:

```javascript
  const qtag = e.mode === "qualifying"
    ? '<span class="tag" style="background:#7c3aed;color:#fff;border-radius:3px;padding:0 4px;font-size:10px;margin-right:4px">QUALI</span>'
    : '';
  tr.innerHTML = `<td class="rn">${escapeHtml(e.target_stint||"?")}</td>
    <td>${qtag}<b>${escapeHtml(e.streamer_name||e.streamer_key||"?")}</b><br>
        <span class="hint" style="word-break:break-all">${prev} → <b>${escapeHtml(e.proposed_url||"")}</b></span></td>
    <td class="act"><button class="clear prev">PREVIEW</button><button class="save app">APPROVE</button><button class="clear rej">REJECT</button></td>`;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_director_panel.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/director/director-panel.html tests/test_director_panel.py
git commit -m "feat(panel): show the schedule editor matching the active mode; tag qualifying submissions"
```

---

### Task 8: Docs, screenshots, full-suite verification

**Files:**
- Modify: `CLAUDE.md` (the `event start` CLI line — add the Control Center qualifying toggle + Q-part note), `src/docs/wiki/Sheet-Webhook.md` (document the `Q` Producer row + `get_stream_key` `Q` ref), and the Producer-tab doc wherever it lives (grep below)
- Regenerate: `src/docs/wiki/images/director-panel.png`, `src/docs/wiki/images/cc-<view>.png` (the Home view hosting Start Event) + their `src/docs/slides/assets/img/` copies
- Verify: whole test suite + lint + build

- [ ] **Step 1: Locate the Producer-tab + Start-Event docs to update**

Run: `grep -rln "Producer" src/docs/wiki; grep -rln "Start event\|--qualifying\|Qualifying" src/docs/wiki`
Update the matching pages: document that a `Q` row in the Producer tab (own Stream Key ref) is the qualifying broadcast part, that `event start --qualifying` (or the Control Center **Qualifying** toggle) drives it, and that ending the single `Q` part auto-stops the event with a `— Qualifying` report. Keep it mechanism-only (no invented crew procedure — CLAUDE.md rule).

- [ ] **Step 2: Regenerate the Director Panel + Control Center screenshots**

Use the **`wiki-screenshots`** skill (demo profile + `tools/obs-sim.py` OBS stand-in, local dev build so the version badge stays uniform). Capture:
- `director-panel.png` — the default (race-mode) panel now shows the race schedule editor without the permanent qualifying editor row.
- `cc-<view>.png` for the Control Center Home view — now with the **Qualifying** checkbox at Start Event.
Follow the [[demo-relay-writes-console-secret]] caveat: running the demo relay mutates `profiles/demo/profile.env` — revert that file before committing.

- [ ] **Step 3: Run the whole suite + lint**

Run: `python3 tools/run-tests.py && python3 tools/lint.py`
Expected: all tests pass; lint clean (exit 0).

- [ ] **Step 4: Build verify (closest thing to CI)**

Run: `python3 tools/build.py`
Expected: `dist/` assembles and self-verifies (tokenization, blanked password, no secrets, no shell scripts) with no error.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md src/docs/
git commit -m "docs(qualifying): document the Q broadcast part + refresh panel/CC screenshots"
```

---

## Self-Review

**Spec coverage:**
- A. `Q` part data model → Task 1 (classifier) + Task 8 (docs of the Sheet row). ✓
- B. Mode-gated parts control → Task 3. ✓
- C. Reuse last-part auto-stop → unchanged (Task 3 leaves `is_last`/`_spawn_event_stop` intact; the single Q part is last). ✓
- D. `event start --qualifying` unchanged → confirmed (no CLI task needed; Task 5 adds the UI toggle only). ✓
- Confirm phrase `START PART Q` → Task 2. ✓
- E. Report title `— Qualifying` → Task 4. ✓
- F. Control Center toggle → Task 5. ✓
- G1. Director Panel mode-aware display → Task 7. ✓
- G2. Submission mode field + approve routing → Task 6. ✓
- Cockpit/Race-Control already mode-aware → verify-only; no code task (correct — they read `relay.source`). Covered by the existing suite in Task 8.
- `set_mode` part-pointer reset → Task 3. ✓
- Screenshots (`director-panel.png`, `cc-*.png`) → Task 8. ✓

**Placeholder scan:** no TBD/TODO; every code step shows complete code; every test step shows real assertions. ✓

**Type consistency:** `validate_start(body, rows, state)` / `validate_end(body, rows, state)` defined in Task 2 and called with exactly that shape in Task 3. `part_confirm_token`/`parts_intent_phrase(action, token)` consistent across Tasks 2–3. `add_pending(..., mode="race")` (Task 6) matches the `submission_store.add(..., mode=relay.mode)` call (Task 6). `_relay_mode`/`_qualifying_title` (Task 4) consistent. Element ids `#urlsBox`/`#qualRow` (Task 7) match the panel markup. ✓
