# Kill stale relay button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Kill stale relay" button to the Control Center Relay card that frees the relay control port 8088 (recovering an orphaned/untracked relay) by reusing `racecast freeport 8088`.

**Architecture:** A new Control Center op `kill-relay` maps to `["freeport", "8088"]` and flows through the existing `freeport` routing in `racecast.py` — no new racecast verb, no new HTTP handler. The frontend adds one row to the Relay `<section>` in `control-center.html` plus a confirm-modal entry. No `--force`, so a healthy tracked relay is refused (steered to Stop Relay) while an orphan with an unknown PID is killed.

**Tech Stack:** Pure Python stdlib; the Control Center web UI (`src/ui/ui_ops.py`, `src/ui/ui_server.py`, `src/ui/control-center.html`); stdlib-script tests (`tests/test_ui_ops.py`, run directly with `python3`).

## Global Constraints

- **Edit only under `src/`** (plus `tests/` and `docs/`). `dist/`/`runtime/` are generated — never hand-edit.
- **English only** in all scripts and docs (UI copy included).
- **Tests are stdlib runnable scripts, not pytest.** Each file runs as `python3 tests/<file>.py`; test functions are named `t_*`; a `__main__` block runs them all and prints `ALL PASS`.
- **Run `python3 tools/lint.py` after changing any Python file** (the CI lint job).
- **The relay control port is the fixed `8088`** (`RELAY_PORT` in `racecast.py`); the op uses the literal string `"8088"`, mirroring the documented CLI `racecast freeport 8088`.
- **No `--force` from the UI** — `freeport`'s owner-check must remain the safety gate.
- **Changed a UI surface → refresh its wiki screenshot in the SAME change.** The Relay card lives in `src/docs/wiki/images/cc-relay.png`; regenerate it from a **local dev build** (run `racecast ui` from `src/`, no `VERSION` stamped).

---

### Task 1: Add the `kill-relay` op + registry tests

**Files:**
- Modify: `src/ui/ui_ops.py` (the `OPS` dict, near the existing `"free-ports": ["freeport"]` entry around line 31)
- Test: `tests/test_ui_ops.py` (add a test next to the existing `# ---------- ui_ops registry ----------` / free-ports-adjacent tests)

**Interfaces:**
- Consumes: `ui_ops.OPS` (dict: op name → base racecast argv), `ui_ops.build_argv(name, params=None)` (raises `ValueError` on unknown op / unexpected params), `rc.route(argv)` (returns `{"kind": ...}`; `freeport` argv routes to kind `"freeport"`).
- Produces: a new op key `"kill-relay"` → `["freeport", "8088"]` that later tasks (the frontend button) call via `op('kill-relay', true)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui_ops.py` (e.g. just after `t_chat_clear_op_builds_argv`):

```python
def t_kill_relay_op_builds_argv():
    # The "Kill stale relay" button frees the relay control port 8088 by reusing
    # `racecast freeport 8088` (no --force: a healthy tracked relay is refused).
    assert ui_ops.OPS["kill-relay"] == ["freeport", "8088"]
    assert ui_ops.build_argv("kill-relay") == ["freeport", "8088"]


def t_kill_relay_op_routes_to_freeport():
    assert rc.route(list(ui_ops.OPS["kill-relay"]))["kind"] == "freeport"


def t_kill_relay_op_rejects_params():
    try:
        ui_ops.build_argv("kill-relay", {"port": "53001"})
        raise AssertionError("expected ValueError for an unexpected param")
    except ValueError:
        pass
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_ui_ops.py`
Expected: FAIL — a `KeyError: 'kill-relay'` (the op is not yet in `OPS`), raised inside `t_kill_relay_op_builds_argv`.

- [ ] **Step 3: Add the op to the registry**

In `src/ui/ui_ops.py`, in the `OPS` dict, add the entry directly below `"free-ports"`:

```python
    "free-ports": ["freeport"],   # kill orphaned holders of the feed ports (53001-53003)
    "kill-relay": ["freeport", "8088"],   # free the relay control port: recover a stale/orphaned relay the Stop button can't reach
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_ui_ops.py`
Expected: PASS — ends with `ALL PASS` (the new `t_kill_relay_*` print `ok`, and the generic `t_ops_registry_routes_in_rc` still passes since `freeport` is an allowed kind).

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/ui/ui_ops.py tests/test_ui_ops.py
git commit -m "feat(ui): add kill-relay op (freeport 8088) for stale relay recovery"
```

---

### Task 2: Relay-card button + confirm text in the Control Center

**Files:**
- Modify: `src/ui/control-center.html` — the Relay `<section>` (around lines 460–474) and the `CONFIRM_TEXT` object (around lines 1682–1687)

**Interfaces:**
- Consumes: the existing `op(name, confirmFirst, params)` JS helper (POSTs `/api/op/<name>`, shows `CONFIRM_TEXT[name]` when `confirmFirst` is truthy, then streams the job via `watchJob`); the `kill-relay` op from Task 1.
- Produces: no JS API surface — a visible button + confirm string only.

- [ ] **Step 1: Add the Relay-card row**

In `src/ui/control-center.html`, insert a new row in the Relay `<section>` immediately **after** the relay lifecycle row (the `<div class="row">` that ends with the `Open panel ↗` link, line ~470) and **before** the `Feed ports` row (line ~471). This mirrors the existing Feed ports row exactly:

```html
          <div class="row"><span class="name">Stale relay</span>
            <span class="dim grow">control port 8088 — force-free a stale/orphaned relay the Stop button can't reach (unknown PID); a healthy relay is left untouched</span>
            <button class="danger" onclick="op('kill-relay', true)">
              <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><line x1="9" y1="9" x2="15" y2="15"/><line x1="15" y1="9" x2="9" y2="15"/></svg>Kill stale relay</button></div>
```

- [ ] **Step 2: Add the confirm text**

In the `CONFIRM_TEXT` object, add an entry alongside `'free-ports'` (after the `'free-ports': '…'` line around line 1687 — remember to add a comma to the preceding entry if it is currently the last one):

```javascript
  'free-ports': 'Free the feed ports (53001–53003)? Kills any orphaned process holding them. A running relay or static stream is left untouched.',
  'kill-relay': 'Kill a stale relay? Frees the relay control port 8088 by killing the process holding it — use this when the relay is orphaned (unknown PID) and the Stop button can\'t reach it. A healthy, running relay is left untouched (use Stop Relay instead).'
```

- [ ] **Step 3: Verify the page loads and the button behaves (manual smoke)**

Run the Control Center from source and click the button with no relay running:

```bash
python3 src/racecast.py ui
```

Open the printed URL, go to the Relay card, click **Kill stale relay**, confirm the modal. With nothing on 8088 the job console should show `port 8088: already free`. (No automated test — the op logic is covered by Task 1 and `tests/test_ports.py`; this is a visual/behaviour check.) Stop the UI with Ctrl-C when done.

- [ ] **Step 4: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(ui): Kill stale relay button in the Control Center Relay card"
```

---

### Task 3: Refresh the wiki screenshot + full verification

**Files:**
- Modify: `src/docs/wiki/images/cc-relay.png` (regenerated)

**Interfaces:**
- Consumes: a running local **dev build** Control Center (so the version badge reads "dev build").
- Produces: the updated screenshot committed in the same change as the code (CLAUDE.md requirement).

- [ ] **Step 1: Run a local dev-build Control Center**

Run it straight from `src/` (no `VERSION` file stamped) on a free port so it doesn't clash with a real instance on 8089:

```bash
RACECAST_UI_PORT=8095 python3 src/racecast.py ui
```

- [ ] **Step 2: Capture the Relay card**

Drive the running instance with the Playwright MCP and take an **element** screenshot of the Relay `<section>` (the card containing the new row), framed to match the existing `cc-relay.png` — not a full-window grab. Save it over `src/docs/wiki/images/cc-relay.png`. Stop the UI (Ctrl-C) when done.

- [ ] **Step 3: Confirm the new row is visible and the badge says "dev build"**

Open the regenerated `src/docs/wiki/images/cc-relay.png` and verify the **Kill stale relay** row is present under the relay lifecycle row and the version badge reads "dev build" (matching the other `cc-*.png`).

- [ ] **Step 4: Run the full test suite**

Run: `python3 tools/run-tests.py`
Expected: the whole suite passes (this is exactly what CI runs).

- [ ] **Step 5: Run the build self-verify**

Run: `python3 tools/build.py`
Expected: build + verify succeeds (tokenization, blanked password, no secrets, no shell scripts).

- [ ] **Step 6: Commit**

```bash
git add src/docs/wiki/images/cc-relay.png
git commit -m "docs(wiki): refresh cc-relay.png with the Kill stale relay button"
```

---

## Self-Review

**Spec coverage:**
- Op `kill-relay` → `["freeport", "8088"]`, routes through existing `freeport` path → Task 1. ✅
- No `--force`; three outcomes via `freeport`'s gate → covered by reusing `freeport` (Task 1 op) + verified manually (Task 2 Step 3); underlying gate already tested in `tests/test_ports.py`. ✅
- Frontend: dedicated Relay-card row under the lifecycle row, label "Kill stale relay", dim explainer, `CONFIRM_TEXT` entry → Task 2. ✅
- No new status plumbing, no pid-file cleanup → nothing added (correct by omission). ✅
- Tests: `kill-relay` in `OPS`, `build_argv` == `["freeport","8088"]`, routes to `"freeport"` → Task 1. ✅
- Wiki `cc-relay.png` refreshed from a dev build in the same change → Task 3. ✅

**Placeholder scan:** No TBD/TODO/"handle edge cases"; all code shown literally. ✅

**Type consistency:** Op name `"kill-relay"` and argv `["freeport", "8088"]` are identical across the test (Task 1), the registry entry (Task 1), and the button `onclick="op('kill-relay', true)"` (Task 2). ✅
