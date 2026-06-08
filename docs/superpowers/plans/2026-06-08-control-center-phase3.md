# IRO Control Center Phase 3 — Init Wizard + Packaging — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the Control Center by exposing the `iro init` first-time-setup wizard in the web UI and shipping a double-click `iro-ui` binary, wired into the existing release/CI pipeline.

**Architecture:** Three independent task groups. (A) Init wizard: a structured `/api/init/plan` endpoint reports each step's done/skip state by reusing the existing `_init_steps()` probes; heavy steps run through the *existing* job/op machinery (`/api/op/<name>` + SSE), and the two non-job steps (`.env` gate, `export-companion`) run through one new `/api/init/step/<key>` structured endpoint — no command logic is duplicated. (B) `src/iro_ui.py` is a second PyInstaller entrypoint that starts the same server via an extracted `run_ui(rest, fail, open_browser)` core, showing a native dialog instead of a console message on a fatal startup error; UI jobs always spawn the sibling `iro` binary. (C) `tools/build-binary.py` builds both binaries (`iro` console, `iro-ui` windowed) and smoke-tests both; `release.yml` ships both in every archive; CI already exercises the build step.

**Tech stack:** Pure Python stdlib (`http.server`, `subprocess`, `ctypes`/`osascript` for native dialogs), vanilla JS/inline-CSS single-page UI, PyInstaller, GitHub Actions. House test convention: stdlib runnable scripts, `t_*` functions, injected probes, no real IPs/machine paths.

**House rules in force:** Edit only under `src/` (and `tools/`, `.github/` for groups B/C). English-only. No `.sh`/`.bat`. Never hardcode secrets/paths. Tests run on any machine + CI. The UI server stays localhost-only. Describe mechanism only — invent no broadcast procedure. After any Python edit run `python3 tools/lint.py`; the PostToolUse hook blocks on ruff errors.

**Dev-mode caveat (documented, not a bug):** the wizard targets the shipped *frozen* binary. In `python3 src/iro.py ui` dev mode, the `setup` step's done-probe checks `runtime/IRO_Endurance.import.json` but a non-frozen `iro setup` job writes to `src/obs/…` (the `--out` injection in `oneshot()` is frozen-gated by design). The step still runs correctly; only its post-run "done" chip stays pending in dev. The frozen binary injects the matching `--out` (`iro.py:229-234`), so the producer flow is correct. Do **not** change the global `setup` default to fix a dev-only cosmetic.

---

## File Structure

**Group A — Init wizard**
- Modify `src/scripts/init_setup.py` — add `STEP_KINDS` (pure data: step key → kind/op/instruction).
- Modify `src/iro.py` — add `init_plan_data()`, `init_step_action_data()`, `_init_plan()` wrapper, ctx keys `init_plan`/`init_step`.
- Modify `src/ui/ui_server.py` — routes `GET /api/init/plan`, `POST /api/init/step/<key>`; ctx docstring.
- Modify `src/ui/control-center.html` — "Setup" nav item + wizard view + JS.
- Modify `tests/test_init.py` — `STEP_KINDS` coverage.
- Modify `tests/test_ui_ops.py` — `init_plan_data`/`init_step_action_data` shapes.
- Modify `tests/test_ui_server.py` — the two new routes.

**Group B — iro-ui binary**
- Create `src/scripts/native_dialog.py` — native fatal-error dialog (pure command builders + dispatcher).
- Modify `src/iro.py` — extract `run_ui(rest, fail, open_browser)` from `ui_cmd`; add `_iro_job_executable()`.
- Create `src/iro_ui.py` — the windowed second entrypoint.
- Create `tests/test_native_dialog.py` — command builders + dispatch.
- Modify `tests/test_ui_ops.py` — `_iro_job_executable()` selection.

**Group C — build / release / CI**
- Modify `tools/build-binary.py` — build both targets; `smoke_ui()`.
- Modify `.github/workflows/release.yml` — package both binaries per OS.
- Verify `.env.example` (IRO_UI_PORT/IRO_UI_PASSWORD already present) and `tools/build.py`.

---

## Group A — Init wizard

### Task A1: Step kind/op/instruction table

**Files:**
- Modify: `src/scripts/init_setup.py` (after `STEP_LABELS`, before `_USAGE`)
- Test: `tests/test_init.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_init.py`:

```python
def t_step_kinds_cover_every_step():
    # every ordered step has a kind descriptor; kinds are the three the UI knows
    assert set(ins.STEP_KINDS) == set(ins.STEP_ORDER)
    for key, meta in ins.STEP_KINDS.items():
        assert meta["kind"] in ("gate", "job", "action")
        assert set(meta) <= {"kind", "op", "instruction"}


def t_step_kinds_jobs_name_a_real_op():
    # job steps carry the op name the UI POSTs to /api/op/<op>
    jobs = {k: m for k, m in ins.STEP_KINDS.items() if m["kind"] == "job"}
    assert jobs["cookies"]["op"] == "cookies"
    assert jobs["preflight"]["op"] == "preflight"
    # gate/action steps have no op
    assert ins.STEP_KINDS["env"]["kind"] == "gate"
    assert ins.STEP_KINDS["env"].get("op") is None
    assert ins.STEP_KINDS["export-companion"]["kind"] == "action"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_init.py`
Expected: FAIL with `AttributeError: module 'init_setup' has no attribute 'STEP_KINDS'`

- [ ] **Step 3: Add the table**

Insert in `src/scripts/init_setup.py` after the `STEP_LABELS` dict (line ~26):

```python
# Per-step UI execution kind, consumed by the Control Center wizard
# (iro.init_plan_data). Three kinds:
#   "job"    -> the UI runs it through the existing job machine (/api/op/<op>),
#               streaming live output; "op" is the ui_ops.OPS name.
#   "gate"   -> a manual, probe-verified checkpoint the UI re-checks
#               (POST /api/init/step/<key>); no subprocess.
#   "action" -> a quick in-process action the UI runs structured
#               (POST /api/init/step/<key>).
# "instruction" (optional) is the operator-facing text shown before the step;
# "{browser}" is substituted by the wizard for the cookies step.
STEP_KINDS = {
    "env": {"kind": "gate", "op": None,
            "instruction": "Open Settings and set IRO_SHEET_ID in .env "
                           "(IRO_SHEET_PUSH_URL is optional). Then re-check."},
    "install-tools": {"kind": "job", "op": "install-tools"},
    "install-apps": {"kind": "job", "op": "install-apps"},
    "cookies": {"kind": "job", "op": "cookies",
                "instruction": "Log in to YouTube in {browser} first — the "
                               "cookie export reads that browser's session."},
    "graphics": {"kind": "job", "op": "graphics"},
    "media": {"kind": "job", "op": "media"},
    "setup": {"kind": "job", "op": "setup"},
    "export-companion": {"kind": "action", "op": None},
    "preflight": {"kind": "job", "op": "preflight"},
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_init.py`
Expected: `ALL PASS`

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/init_setup.py tests/test_init.py
git commit -m "feat(init): step kind/op table for the Control Center wizard"
```

---

### Task A2: Structured plan + action providers in iro.py

**Files:**
- Modify: `src/iro.py` (new functions near the other `init`/`ui` providers, after `_init_steps`, ~line 1810)
- Test: `tests/test_ui_ops.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui_ops.py` (it already imports `iro`):

```python
def t_init_plan_data_shape_and_safety():
    steps = [
        {"key": "env", "label": ".env", "done": lambda: "IRO_SHEET_ID set"},
        {"key": "cookies", "label": "cookies", "done": lambda: None},
        {"key": "preflight", "label": "preflight", "done": lambda: None},
    ]
    out = iro.init_plan_data(steps, iro.ins.STEP_KINDS, browser="chrome",
                             next_steps=["import the OBS collection"])
    assert out["ok"] is True
    by_key = {s["key"]: s for s in out["steps"]}
    assert by_key["env"]["done"] is True
    assert by_key["env"]["kind"] == "gate"
    assert by_key["cookies"]["done"] is False
    assert by_key["cookies"]["op"] == "cookies"
    # browser is interpolated into the instruction
    assert "chrome" in by_key["cookies"]["instruction"]
    assert out["next_steps"] == ["import the OBS collection"]


def t_init_plan_data_never_raises_on_probe_error():
    def boom():
        raise RuntimeError("sheet down")
    steps = [{"key": "graphics", "label": "graphics", "done": boom}]
    out = iro.init_plan_data(steps, iro.ins.STEP_KINDS, browser="firefox",
                             next_steps=[])
    # a broken probe reads as "not done", never a 500
    assert out["ok"] is True
    assert out["steps"][0]["done"] is False


def t_init_step_action_rejects_job_steps():
    # only env/export-companion are UI action steps; a job step is refused
    res = iro.init_step_action_data("cookies")
    assert res["ok"] is False
    assert "cookies" in res["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_ui_ops.py`
Expected: FAIL with `AttributeError: module 'iro' has no attribute 'init_plan_data'`

- [ ] **Step 3: Add the providers**

Insert in `src/iro.py` immediately after `_init_steps()` (before `_ui_modules`, ~line 1811):

```python
def init_plan_data(steps, kinds, browser="firefox", next_steps=None):
    """Wizard plan for the Control Center: each step's current done/skip state
    plus how the UI runs it (kind/op/instruction from ins.STEP_KINDS). Pure +
    never-raise — a broken done-probe reads as 'not done' (the step then runs
    and surfaces its own error), never a 500. `steps` is the _init_steps()-shaped
    list; `next_steps` is the closing manual checklist."""
    out = []
    for st in steps:
        meta = kinds.get(st["key"], {"kind": "action", "op": None})
        try:
            reason = st["done"]()
        except Exception:
            reason = None
        instr = meta.get("instruction")
        if instr:
            instr = instr.replace("{browser}", browser)
        out.append({"key": st["key"], "label": st["label"],
                    "kind": meta["kind"], "op": meta.get("op"),
                    "done": reason is not None, "skip_reason": reason,
                    "instruction": instr})
    return {"ok": True, "steps": out, "next_steps": list(next_steps or [])}


def init_step_action_data(key):
    """Run one non-job wizard step in-process and report its new state. Only the
    '.env' gate and 'export-companion' action are UI-driven here; job steps run
    through /api/op/<op>. Never raises — returns {ok: False, error} instead."""
    try:
        if key == "env":
            path = _env_file()
            example = os.path.join(os.path.dirname(path), ".env.example")
            if not os.path.exists(path) and os.path.exists(example):
                shutil.copyfile(example, path)
            reason = ins.env_done(_init_env_state())
            return {"ok": True, "key": key, "done": reason is not None,
                    "skip_reason": reason}
        if key == "export-companion":
            _init_export_run()
            reason = ins.export_done(os.path.exists(_init_companion_cfg()))
            return {"ok": True, "key": key, "done": reason is not None,
                    "skip_reason": reason}
        return {"ok": False, "error": f"step '{key}' is not a UI action step"}
    except Exception as exc:
        return {"ok": False, "error": f"init step '{key}' failed: {exc}"}


def _init_plan(browser="firefox"):
    """ctx['init_plan'] wrapper: build the full step list (no --skip-installs in
    the UI), then describe it. Closing checklist mirrors `iro init`'s output."""
    opts = {"browser": browser or "firefox", "skip_installs": False, "force": False}
    nxt = ins.manual_next_steps(_init_import_json(), _init_companion_cfg())
    return init_plan_data(_init_steps(opts), ins.STEP_KINDS,
                          browser=opts["browser"], next_steps=nxt)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_ui_ops.py`
Expected: `ALL PASS`

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/iro.py tests/test_ui_ops.py
git commit -m "feat(ui): structured init-wizard plan + action providers"
```

---

### Task A3: Server routes for the wizard

**Files:**
- Modify: `src/ui/ui_server.py` (`do_GET` block ~after `/api/env`, line ~253; `do_POST` block ~after `/api/streams`, line ~299; ctx docstring ~line 60-75)
- Test: `tests/test_ui_server.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui_server.py` (follow its existing fake-ctx + handler-call pattern; reuse its helper for building a handler and issuing a request — mirror an existing route test such as the `/api/streams` one):

```python
def t_init_plan_route_returns_plan():
    ctx = _ctx(init_plan=lambda browser="firefox": {
        "ok": True, "steps": [{"key": "env", "label": ".env", "kind": "gate",
                               "op": None, "done": False, "skip_reason": None,
                               "instruction": "set it"}],
        "next_steps": []})
    status, body = _get(ctx, "/api/init/plan")
    assert status == 200
    assert body["ok"] is True
    assert body["steps"][0]["key"] == "env"


def t_init_plan_route_passes_browser_query():
    seen = {}
    def plan(browser="firefox"):
        seen["browser"] = browser
        return {"ok": True, "steps": [], "next_steps": []}
    status, body = _get(_ctx(init_plan=plan), "/api/init/plan?browser=edge")
    assert status == 200
    assert seen["browser"] == "edge"


def t_init_step_route_runs_action():
    status, body = _post(
        _ctx(init_step=lambda key: {"ok": True, "key": key, "done": True,
                                    "skip_reason": "config already exported"}),
        "/api/init/step/export-companion", {})
    assert status == 200
    assert body["ok"] is True
    assert body["done"] is True


def t_init_step_route_reports_error_as_400():
    status, body = _post(
        _ctx(init_step=lambda key: {"ok": False, "error": "nope"}),
        "/api/init/step/cookies", {})
    assert status == 400
    assert body["ok"] is False
```

> If `tests/test_ui_server.py` has no `_ctx`/`_get`/`_post` helpers, reuse whatever request helper the existing route tests use (e.g. the handler-invocation harness used for `/api/streams` GET and POST) and add `init_plan`/`init_step` to the fake ctx the same way `streams_read`/`streams_write` are added.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_ui_server.py`
Expected: FAIL — the routes return 404 (`_not_found`) so the asserted 200/400 + body shape fail.

- [ ] **Step 3: Add the GET route**

In `src/ui/ui_server.py` `do_GET`, insert after the `/api/env` block (after line ~253, before the `/api/jobs/` blocks):

```python
            if path == "/api/init/plan":
                browser = parse_qs(urlparse(self.path).query or "").get(
                    "browser", ["firefox"])[0]
                try:
                    return self._json(ctx["init_plan"](browser))
                except Exception as exc:
                    return self._json({"ok": False,
                                       "error": f"init plan failed: {exc}"},
                                      code=500)
```

Ensure `parse_qs` is imported. Find the existing `from urllib.parse import` line and add `parse_qs` to it (alongside `urlparse`, `unquote`). If the file imports `urlparse`/`unquote` separately, add `parse_qs` in the same style.

- [ ] **Step 4: Add the POST route**

In `do_POST`, insert after the `/api/streams` block (after line ~299, before the `/api/op/` block):

```python
            if path.startswith("/api/init/step/"):
                key = unquote(path[len("/api/init/step/"):])
                try:
                    result = ctx["init_step"](key)
                except Exception as exc:
                    return self._json({"ok": False,
                                       "error": f"init step failed: {exc}"},
                                      code=500)
                return self._json(result, code=200 if result.get("ok") else 400)
```

- [ ] **Step 5: Update the ctx docstring**

In `make_handler`'s docstring (the `ctx` key list, ~line 60-80), add two lines alongside the existing entries (match the surrounding wording):

```
    init_plan(browser) -> dict (wizard plan: per-step done/kind/op/instruction),
    init_step(key) -> dict (run one non-job wizard step, {ok, done} | {ok: False, error}),
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python3 tests/test_ui_server.py`
Expected: `ALL PASS`

- [ ] **Step 7: Lint + commit**

```bash
python3 tools/lint.py
git add src/ui/ui_server.py tests/test_ui_server.py
git commit -m "feat(ui): /api/init/plan + /api/init/step routes"
```

---

### Task A4: Wire the wizard ctx keys

**Files:**
- Modify: `src/iro.py` (the ctx dict — currently in `ui_cmd`, lines ~1853-1882; after Task B2 this lives in `run_ui`. If doing Group A before Group B, edit the ctx in `ui_cmd`.)

- [ ] **Step 1: Add the ctx keys**

In the `ctx = { ... }` dict, add after the `"docs_content": docs_content,` line:

```python
        "init_plan": _init_plan,
        "init_step": init_step_action_data,
```

- [ ] **Step 2: Smoke the route end-to-end**

Run (dev server, no browser):

```bash
IRO_UI_PORT=8390 python3 src/iro.py ui --no-browser &
sleep 2
curl -s http://127.0.0.1:8390/api/init/plan | python3 -m json.tool | head -30
curl -s -X POST http://127.0.0.1:8390/api/quit
```

Expected: JSON with `"ok": true` and a `steps` array whose first element is `{"key": "env", "kind": "gate", ...}`, plus a `next_steps` array.

- [ ] **Step 3: Commit**

```bash
git add src/iro.py
git commit -m "feat(ui): expose init-wizard plan/step in the server ctx"
```

---

### Task A5: Wizard view + JS in the page

**Files:**
- Modify: `src/ui/control-center.html` (nav block ~316; a new view in the `<main>`; JS near the other view loaders + `op()`)

- [ ] **Step 1: Add the nav item**

In the `.nav` block, insert a "Setup" item immediately after the Home button (after line 317, before the Preflight button):

```html
      <button class="navitem" data-nav="wizard" onclick="showView('wizard')">
        <svg viewBox="0 0 24 24"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/><circle cx="12" cy="12" r="3"/></svg>Setup</button>
```

- [ ] **Step 2: Add the wizard view**

Insert a new view inside `<main>` (place it just before the `data-view="preflight"` view, ~line 513, to match nav order). Markup mirrors the existing card/item style:

```html
      <!-- ===== Setup wizard ===== -->
      <div class="view" data-view="wizard" hidden>
        <div class="viewhead"><h2>Setup</h2>
          <p class="sub">First-time setup, step by step. Already-completed
            steps are detected and skipped. The closing checklist lists the
            manual imports no script can do.</p></div>
        <div class="card">
          <div class="row" style="justify-content:flex-end;gap:10px">
            <label class="fl">YouTube browser
              <select id="wiz-browser" onchange="fetchWizard()">
                <option value="firefox">firefox</option>
                <option value="chrome">chrome</option>
                <option value="edge">edge</option>
                <option value="brave">brave</option>
                <option value="safari">safari</option>
              </select></label>
            <button class="btn" onclick="fetchWizard()">Re-check all</button>
          </div>
          <div id="wiz-steps" class="itemlist"></div>
        </div>
        <div class="card">
          <h3>Manual next steps</h3>
          <ol id="wiz-next" class="docs"></ol>
        </div>
      </div>
```

- [ ] **Step 3: Add the lazy-load hook**

In `showView()` (line ~624-631 area), add a loader flag and call. First extend the flag declaration at line 610-611:

```javascript
let setupLoaded = false, preflightRun = false, assetsLoaded = false,
    settingsLoaded = false, streamsLoaded = false, docsLoaded = false,
    wizardLoaded = false;
```

Then add inside `showView`, next to the other lazy first-loads:

```javascript
  if (name === 'wizard' && !wizardLoaded) { wizardLoaded = true; fetchWizard(); }
```

- [ ] **Step 4: Add the wizard JS**

Add near the other fetchers (e.g. after `fetchDocs`/before `op()`):

```javascript
async function fetchWizard() {
  const browser = ($('wiz-browser') || {}).value || 'firefox';
  let r;
  try {
    r = await (await fetch('/api/init/plan?browser=' + encodeURIComponent(browser))).json();
  } catch (e) { return; }
  if (!r.ok) return;
  renderWizard(r);
}

function renderWizard(plan) {
  const box = $('wiz-steps');
  box.innerHTML = '';
  plan.steps.forEach((s, i) => {
    const row = document.createElement('div');
    row.className = 'item';
    const chip = s.done ? '<span class="chip ok">done</span>'
                        : '<span class="chip">pending</span>';
    const detail = s.done && s.skip_reason
      ? '<span class="idim">' + esc(s.skip_reason) + '</span>' : '';
    const instr = (!s.done && s.instruction)
      ? '<div class="note-warn">' + esc(s.instruction) + '</div>' : '';
    let action = '';
    if (!s.done) {
      if (s.kind === 'job') {
        action = '<button class="btn" onclick="runWizardJob(\'' + s.op +
                 '\',\'' + s.key + '\')">Run</button>';
      } else if (s.key === 'env') {
        action = '<button class="btn" onclick="showView(\'settings\')">' +
                 'Open Settings</button>' +
                 '<button class="btn" onclick="runWizardAction(\'env\')">' +
                 'Re-check</button>';
      } else {
        action = '<button class="btn" onclick="runWizardAction(\'' + s.key +
                 '\')">Run</button>';
      }
    }
    row.innerHTML = '<div class="iname">' + (i + 1) + '. ' + esc(s.label) +
      ' ' + chip + ' ' + detail + instr + '</div>' +
      '<div class="iact">' + action + '</div>';
    box.appendChild(row);
  });
  const ol = $('wiz-next');
  ol.innerHTML = '';
  (plan.next_steps || []).forEach(t => {
    const li = document.createElement('li');
    li.textContent = t;
    ol.appendChild(li);
  });
}

function runWizardJob(opName, key) {
  const params = key === 'cookies'
    ? {browser: ($('wiz-browser') || {}).value || 'firefox'} : {};
  op(opName, false, params);     // streams in the docked console; re-check after
  // refresh the plan when the job finishes (watchJob calls refresh()/fetchers;
  // poll the plan shortly after so the chip flips without a manual re-check)
  setTimeout(fetchWizard, 1500);
}

async function runWizardAction(key) {
  let r;
  try {
    r = await (await fetch('/api/init/step/' + encodeURIComponent(key),
        {method: 'POST', headers: {'Content-Type': 'application/json'},
         body: '{}'})).json();
  } catch (e) { alert('Control Center not reachable.'); return; }
  if (!r.ok) { alert(r.error); return; }
  fetchWizard();
}
```

> `esc()` is the page's existing HTML-escape helper (used by the other render functions). If it is named differently in this file, use that name. `.chip`, `.item`, `.iname`, `.iact`, `.note-warn`, `.idim`, `.docs`, `.fl`, `.btn` are existing classes; reuse them (grep to confirm exact names, mirror the Apps/Tools item rows).

- [ ] **Step 5: Verify in the browser (Playwright)**

Rebuild not required for dev. Start the dev server and check the view renders:

```bash
IRO_UI_PORT=8390 python3 src/iro.py ui --no-browser &
sleep 2
```

Navigate to `http://127.0.0.1:8390/`, click **Setup**, confirm: the step list renders with done/pending chips, the `.env` step shows "Open Settings"/"Re-check", job steps show "Run", and the "Manual next steps" list is populated. Confirm no secrets are visible (the wizard shows no `.env` values — it only reports done/pending). Then:

```bash
curl -s -X POST http://127.0.0.1:8390/api/quit
```

- [ ] **Step 6: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(ui): Setup wizard view driving init steps"
```

---

## Group B — iro-ui binary

### Task B1: Native fatal-error dialog

**Files:**
- Create: `src/scripts/native_dialog.py`
- Test: `tests/test_native_dialog.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_native_dialog.py`:

```python
#!/usr/bin/env python3
"""native_dialog unit checks (pure command builders + dispatch). Run: python3 tests/test_native_dialog.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
import native_dialog as nd


def t_osascript_argv_quotes_and_titles():
    argv = nd.osascript_argv('port 8089 in use "now"')
    assert argv[0] == "osascript"
    joined = " ".join(argv)
    assert "IRO Control Center" in joined
    # double quotes are neutralised so the AppleScript string can't break out
    assert '"now"' not in joined


def t_notify_darwin_runs_osascript():
    calls = []
    nd.notify("boom", platform="darwin", run=lambda a: calls.append(a))
    assert calls and calls[0][0] == "osascript"


def t_notify_windows_calls_msgbox():
    calls = []
    nd.notify("boom", platform="win32", run=lambda a: None,
              msgbox=lambda m: calls.append(m))
    assert calls == ["boom"]


def t_notify_linux_falls_back_to_stderr(capsys=None):
    # no run/msgbox invoked on linux; message goes to stderr
    ran = []
    nd.notify("boom", platform="linux", run=lambda a: ran.append(a),
              msgbox=lambda m: ran.append(m))
    assert ran == []


def _run_all():
    fns = sorted(n for n in globals() if n.startswith("t_"))
    for n in fns:
        globals()[n]()
        print(f"  ok {n}")
    print(f"ALL PASS ({len(fns)})")


if __name__ == "__main__":
    _run_all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_native_dialog.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'native_dialog'`

- [ ] **Step 3: Create the module**

Create `src/scripts/native_dialog.py`:

```python
"""Show a fatal startup message to a user with no terminal — the windowed
`iro-ui` binary has no console to print to. Pure command builders plus a thin,
fully-injected dispatcher (tests pass fakes; nothing touches the system).
Used by src/iro_ui.py. Tests: tests/test_native_dialog.py."""
import subprocess
import sys

TITLE = "IRO Control Center"


def osascript_argv(message):
    """macOS: an `osascript -e 'display dialog ...'` argv. Double quotes in the
    message are neutralised so it cannot break out of the AppleScript string."""
    safe = message.replace('"', "'")
    return ["osascript", "-e",
            f'display dialog "{safe}" buttons {{"OK"}} default button "OK" '
            f'with icon stop with title "{TITLE}"']


def _win_msgbox(message):
    """Windows: a modal MessageBox via user32 (0x10 = MB_ICONERROR)."""
    import ctypes
    ctypes.windll.user32.MessageBoxW(0, message, TITLE, 0x10)


def notify(message, platform=sys.platform, run=subprocess.call, msgbox=None):
    """Surface `message` natively for the current OS. darwin -> osascript;
    win32 -> MessageBoxW; anything else -> stderr (the only safe fallback).
    `run`/`msgbox` are injected for tests."""
    if platform == "darwin":
        run(osascript_argv(message))
    elif platform.startswith("win"):
        (msgbox or _win_msgbox)(message)
    else:
        print(message, file=sys.stderr)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_native_dialog.py`
Expected: `ALL PASS`

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/native_dialog.py tests/test_native_dialog.py
git commit -m "feat(ui): native fatal-error dialog for the windowed launcher"
```

---

### Task B2: Extract run_ui + sibling-iro job executable

**Files:**
- Modify: `src/iro.py` (`ui_cmd` lines ~1822-1899; add `_iro_job_executable`)
- Test: `tests/test_ui_ops.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui_ops.py`:

```python
def t_iro_job_executable_frozen_uses_sibling():
    # frozen iro-ui must spawn the sibling `iro`, not itself
    posix = iro._iro_job_executable(frozen=True,
                                    executable="/opt/iro/iro-ui", win=False)
    assert posix == "/opt/iro/iro"
    win = iro._iro_job_executable(frozen=True,
                                  executable="C:\\iro\\iro-ui.exe", win=True)
    assert win.endswith("iro.exe")


def t_iro_job_executable_dev_uses_interpreter():
    # non-frozen: the running interpreter (paired with iro.py)
    assert iro._iro_job_executable(frozen=False, executable="/usr/bin/python3",
                                   win=False) == "/usr/bin/python3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_ui_ops.py`
Expected: FAIL with `AttributeError: module 'iro' has no attribute '_iro_job_executable'`

- [ ] **Step 3: Add the helper**

Insert in `src/iro.py` just before `ui_cmd` (~line 1821):

```python
def _iro_job_executable(frozen=IS_FROZEN, executable=None, win=None):
    """Path to the `iro` binary that runs Control Center jobs. When the server
    is launched by iro-ui (a sibling binary), jobs must still invoke `iro`, not
    iro-ui. Frozen: the sibling iro/iro.exe next to the running executable.
    Dev: the interpreter itself (paired with iro.py by job_argv)."""
    executable = sys.executable if executable is None else executable
    win = (os.name == "nt") if win is None else win
    if frozen:
        return os.path.join(os.path.dirname(executable),
                            "iro.exe" if win else "iro")
    return executable
```

- [ ] **Step 4: Extract run_ui from ui_cmd**

Refactor `ui_cmd` (lines ~1822-1899) into a thin wrapper over a new `run_ui`. Replace the whole `ui_cmd` body with:

```python
def ui_cmd(rest):
    """Run the Control Center web server in the foreground (Ctrl+C stops it).
    Spec: docs/superpowers/specs/2026-06-07-control-center-design.md."""
    return run_ui(rest, fail=sys.exit, open_browser="--no-browser" not in rest)


def run_ui(rest, fail=sys.exit, open_browser=True):
    """Shared Control Center server core for both entrypoints. `fail(msg)` is
    called on a fatal startup error (port taken / bind failure): the CLI passes
    sys.exit; iro_ui passes a native-dialog variant. Returns None when the
    server has stopped."""
    srv, jobs_mod, ops_mod = _ui_modules()
    for key, val in _read_env_file().items():
        os.environ.setdefault(key, val)        # IRO_UI_PORT from .env (env wins)
    port = srv.ui_port(os.environ)
    instance = srv.probe_instance("127.0.0.1", port)
    if instance == "ours":
        print(f"Control Center already running on port {port} — opening the browser.")
        if open_browser:
            _open_url(_http_url("127.0.0.1", port, "/"))
        return None
    if instance == "foreign":
        return fail(f"iro: port {port} is in use by another application — set "
                    "IRO_UI_PORT in .env to a free port and retry.")

    _upd = {"at": 0.0, "data": None}

    def update_check_cached(force=False):
        now = time.time()
        if not force and _upd["data"] is not None and now - _upd["at"] <= 3600:
            return _upd["data"]
        fresh = update_check_data()
        if fresh.get("ok"):
            _upd["data"], _upd["at"] = fresh, now
            return fresh
        return _upd["data"] or fresh

    ctx = {
        "version": version(),
        "page_path": resource_path("ui/control-center.html"),
        "status": ui_status_payload,
        "relay_live": relay_live_data,
        "obs_ws": obs_ws_link_data,
        "update_check": update_check_cached,
        "streams_read": streams_config_data,
        "streams_write": streams_config_write_data,
        "docs": docs_data,
        "docs_content": docs_content,
        "init_plan": _init_plan,
        "init_step": init_step_action_data,
        "ops": ops_mod.OPS,
        "build_argv": ops_mod.build_argv,
        "assets": assets_status_data,
        "asset_files": assets_files_data,
        "asset_roots": {"graphics": os.path.join(_runtime_dir(), "graphics"),
                        "media": os.path.join(_runtime_dir(), "media")},
        "tools": tools_status_data,
        "apps": apps_status_data,
        "preflight": preflight_data,
        "env_read": env_entries_data,
        "env_write": env_write_data,
        "jobs": jobs_mod.JobManager(
            lambda op_args: ops_mod.job_argv(op_args, IS_FROZEN,
                                             _iro_job_executable(),
                                             os.path.join(HERE, "iro.py")),
            env=_frozen_child_env()),
        "log_paths": {"relay": _relay_log_path,
                      "companion": _companion_log_path,
                      "streams": _latest_stream_log},
    }
    try:
        httpd = srv.serve(ctx, "127.0.0.1", port)
    except OSError as exc:
        return fail(f"iro: could not bind port {port} ({exc}) — set IRO_UI_PORT "
                    "in .env to a free port and retry.")
    url = _http_url("127.0.0.1", port, "/")
    print(f"Control Center: {url}  (Ctrl+C or the Quit button stops it)")
    if open_browser:
        _open_url(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    print("Control Center stopped — relay/companion/streams keep running.")
    return None
```

> This folds the Task A4 ctx keys (`init_plan`/`init_step`) into `run_ui`. If Group A already added them to `ui_cmd`'s ctx, they move here — confirm they appear exactly once.

- [ ] **Step 5: Run the full UI suite + lint**

Run:
```bash
python3 tests/test_ui_ops.py
python3 tests/test_ui_server.py
python3 tests/test_ui_jobs.py
python3 tools/lint.py
```
Expected: all `ALL PASS`, lint clean. (The extraction is behaviour-preserving for `iro ui`.)

- [ ] **Step 6: Smoke `iro ui` still works**

```bash
IRO_UI_PORT=8390 python3 src/iro.py ui --no-browser &
sleep 2
curl -s http://127.0.0.1:8390/api/ping
curl -s -X POST http://127.0.0.1:8390/api/quit
```
Expected: ping returns the `iro-control-center` signature; quit stops it.

- [ ] **Step 7: Commit**

```bash
git add src/iro.py tests/test_ui_ops.py
git commit -m "refactor(ui): extract run_ui core + sibling-iro job executable"
```

---

### Task B3: The iro_ui entrypoint

**Files:**
- Create: `src/iro_ui.py`

- [ ] **Step 1: Create the entrypoint**

Create `src/iro_ui.py`:

```python
#!/usr/bin/env python3
"""Second entrypoint: the windowed Control Center launcher (the `iro-ui`
binary). Producers double-click it — there is no terminal. It runs the same
server as `iro ui` via iro.run_ui(), but a fatal startup error (port taken /
bind failure) is shown in a NATIVE dialog instead of being written to a console
that does not exist. Jobs still spawn the sibling `iro` binary (see
iro._iro_job_executable). Spec: docs/superpowers/specs/2026-06-07-control-center-design.md."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)            # import the sibling iro module

import iro                              # noqa: E402 — after the path insert
import native_dialog                    # noqa: E402 — from scripts/ (iro added it to sys.path)


def _fatal(message):
    """Show the message natively, then exit non-zero (no console to print to)."""
    native_dialog.notify(message)
    raise SystemExit(1)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # Same bootstrap as iro.main(): make sure .env exists next to the binary,
    # retire any stale update binary, load the frozen env + SSL certs.
    iro.ensure_env_file(os.path.dirname(sys.executable))
    iro.cleanup_old_binary(os.path.dirname(sys.executable))
    iro._load_env_frozen()
    iro._ensure_ssl_certs()
    try:
        iro.run_ui(argv, fail=_fatal,
                   open_browser="--no-browser" not in argv)
    except SystemExit as exc:
        # belt-and-suspenders: a string exit code means a fatal message slipped
        # through as text — surface it natively too.
        if isinstance(exc.code, str):
            _fatal(exc.code)
        raise


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it runs in dev**

```bash
IRO_UI_PORT=8390 python3 src/iro_ui.py --no-browser &
sleep 2
curl -s http://127.0.0.1:8390/api/ping
curl -s -X POST http://127.0.0.1:8390/api/quit
```
Expected: ping returns the `iro-control-center` signature + version; quit stops it.

- [ ] **Step 3: Verify the native dialog path (port-taken)**

```bash
# occupy the port with a foreign listener, then launch iro-ui against it
python3 -c "import socket,time; s=socket.socket(); s.bind(('127.0.0.1',8391)); s.listen(); time.sleep(8)" &
sleep 1
IRO_UI_PORT=8391 python3 src/iro_ui.py --no-browser; echo "exit=$?"
```
Expected on macOS: a native dialog appears (dismiss it) and `exit=1`. On Linux: the message prints to stderr and `exit=1`. (This confirms `_fatal` fires via the foreign-port branch.)

- [ ] **Step 4: Lint + commit**

```bash
python3 tools/lint.py
git add src/iro_ui.py
git commit -m "feat(ui): iro-ui windowed launcher entrypoint"
```

---

## Group C — build / release / CI

### Task C1: Build + smoke both binaries

**Files:**
- Modify: `tools/build-binary.py`

- [ ] **Step 1: Parameterise the build into one target builder**

In `tools/build-binary.py`, refactor `main()` so the PyInstaller invocation is a reusable function. Replace the body of `main()` from the `cmd = launcher + [...]` assembly through the binary-existence check with a call to a new `build_target(...)`, and add that function. Keep `DATA`, `DOC_FILES`, `HIDDEN_STDLIB` shared. Concretely:

Add this function above `main()`:

```python
def build_target(launcher, workdir, version_file, sep, entry, name, windowed):
    """Run PyInstaller for one entrypoint. `windowed` builds a no-console app
    (Windows: no console window; macOS: an .app bundle; Linux: ignored). Returns
    the path to the built executable."""
    cmd = launcher + ["--onefile", "--name", name, "--clean", "--noconfirm",
           "--distpath", os.path.join(ROOT, "dist", "bin"),
           "--workpath", os.path.join(workdir, "build", name),
           "--specpath", workdir,
           "--paths", os.path.join(SRC, "scripts"),
           "--hidden-import", "services", "--hidden-import", "companion_common",
           "--hidden-import", "event", "--hidden-import", "preflight",
           "--hidden-import", "install_apps", "--hidden-import", "obs_ws",
           "--hidden-import", "tailscale", "--hidden-import", "init_setup",
           "--hidden-import", "native_dialog",
           "--add-data", f"{version_file}{sep}src"]
    if windowed:
        cmd += ["--windowed"]
    for mod in HIDDEN_STDLIB:
        cmd += ["--hidden-import", mod]
    for rel in DATA:
        path = os.path.join(SRC, rel)
        dest = f"src/{rel}" if os.path.isdir(path) else "src"
        cmd += ["--add-data", f"{path}{sep}{dest}"]
    for rel in DOC_FILES:
        cmd += ["--add-data", f"{os.path.join(SRC, rel)}{sep}src/docs"]
    cmd.append(os.path.join(SRC, entry))
    print("Running:", " ".join(cmd), flush=True)
    if subprocess.call(cmd) != 0:
        sys.exit(f"pyinstaller failed for {name}.")
    ext = ".exe" if os.name == "nt" else ""
    binary = os.path.join(ROOT, "dist", "bin", name + ext)
    if not os.path.isfile(binary):
        sys.exit(f"expected binary missing: {binary}")
    print(f"Built {binary} ({os.path.getsize(binary) // (1024 * 1024)} MB)")
    return binary
```

> Note: `native_dialog` is a real module imported by the frozen `iro_ui` at startup (before iro adds scripts/ to the path is irrelevant — iro_ui imports it directly), so it is listed as a `--hidden-import` for both targets. It is harmless in the `iro` target.

Then rewrite `main()`'s tail (after the `version_file` is written and `sep` is set) to build both targets and smoke them:

```python
    iro_bin = build_target(launcher, workdir, version_file, sep,
                           "iro.py", "iro", windowed=False)
    ui_bin = build_target(launcher, workdir, version_file, sep,
                          "iro_ui.py", "iro-ui", windowed=True)
    if not a.skip_smoke:
        smoke(iro_bin, a.version)
        smoke_ui(ui_bin)
```

(Remove the now-duplicated single-target `cmd`/build/verify lines that previously lived in `main()`.)

- [ ] **Step 2: Add the iro-ui smoke**

Add `smoke_ui()` next to `smoke()`:

```python
def smoke_ui(binary):
    """The windowed launcher must bind, answer the ping with the Control Center
    signature, run a job through the sibling `iro` binary, and quit. No --version
    check: a windowed Windows build has no stdout. The sibling `iro` lives next
    to this binary in dist/bin/, so the job spawn exercises _iro_job_executable."""
    import json
    import time
    import urllib.request
    env = os.environ.copy()
    env["IRO_UI_PORT"] = "8390"
    ui = subprocess.Popen([binary, "--no-browser"], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def _get(path):
        with urllib.request.urlopen(f"http://127.0.0.1:8390{path}", timeout=2) as r:
            return r.read()

    def _post(path):
        return urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:8390{path}", method="POST", data=b"{}"),
            timeout=5).read()

    try:
        body = b""
        for _ in range(20):                  # up to ~10 s to bind
            time.sleep(0.5)
            try:
                body = _get("/api/ping")
                break
            except OSError:
                if ui.poll() is not None:
                    break
        if b"iro-control-center" not in body:
            out = ui.stdout.read().decode("utf-8", "replace") if ui.poll() is not None else ""
            sys.exit(f"smoke iro-ui FAILED: no Control Center ping on :8390 "
                     f"(rc={ui.poll()}) out={out!r}")
        # Start a read-only job (preflight) and confirm it spawns + completes —
        # this proves iro-ui spawns the sibling `iro` binary, not itself.
        job = json.loads(_post("/api/op/preflight"))
        if not job.get("ok") or not job.get("job_id"):
            sys.exit(f"smoke iro-ui FAILED: could not start preflight job ({job!r})")
        jid, snap = job["job_id"], {}
        for _ in range(60):                  # up to ~30 s for preflight to finish
            time.sleep(0.5)
            snap = json.loads(_get(f"/api/jobs/{jid}"))
            if snap.get("done") or snap.get("exit_code") is not None:
                break
        if not (snap.get("done") or snap.get("exit_code") is not None):
            sys.exit(f"smoke iro-ui FAILED: preflight job never finished ({snap!r})")
        _post("/api/quit")
        ui.wait(timeout=10)
    finally:
        if ui.poll() is None:
            ui.kill()
    print("Smoke test OK (iro-ui: ping, sibling-iro job, quit).")
```

> Confirm the job-status JSON field names against `ui_jobs.JobManager.snapshot()` / the `/api/jobs/<id>` route (Task A3 referenced `snapshot`). Adjust `snap.get("done")`/`snap.get("exit_code")` to the actual keys the snapshot returns (grep `src/ui/ui_jobs.py` for the snapshot dict). The intent: poll until the job is no longer running.

- [ ] **Step 3: Build + smoke locally**

Run:
```bash
python3 tools/build-binary.py --version ci-smoke
```
Expected: builds `dist/bin/iro` and `dist/bin/iro-ui` (macOS also `dist/bin/iro-ui.app`), then prints both smoke "OK" lines. This is the exact step CI's `binary-smoke` runs, so a green local run = green CI.

- [ ] **Step 4: Commit**

```bash
git add tools/build-binary.py
git commit -m "build: build + smoke-test the iro-ui binary alongside iro"
```

---

### Task C2: Ship both binaries in releases

**Files:**
- Modify: `.github/workflows/release.yml`

- [ ] **Step 1: Add the iro-ui artifact to the matrix**

In `release.yml`, extend each `matrix.include` entry with the iro-ui built path and shipped name. Windows/Linux ship a single file; macOS ships the `.app` bundle directory:

```yaml
        include:
          - os: windows-latest
            asset: iro-windows.zip
            built: dist/bin/iro.exe
            binary: iro.exe
            built_ui: dist/bin/iro-ui.exe
            binary_ui: iro-ui.exe
          - os: macos-latest
            asset: iro-macos.tar.gz
            built: dist/bin/iro
            binary: iro
            built_ui: dist/bin/iro-ui.app
            binary_ui: iro-ui.app
          - os: ubuntu-latest
            asset: iro-linux.tar.gz
            built: dist/bin/iro
            binary: iro
            built_ui: dist/bin/iro-ui
            binary_ui: iro-ui
```

- [ ] **Step 2: Package both binaries**

Replace the "Package the release asset" step's script so it copies both into staging (`cp -R` handles the macOS `.app` directory as well as plain files), and add both to the archive:

```yaml
      - name: Package the release asset (binaries + .env.example)
        run: |
          mkdir staging
          cp -R "${{ matrix.built }}" "staging/${{ matrix.binary }}"
          cp -R "${{ matrix.built_ui }}" "staging/${{ matrix.binary_ui }}"
          cp .env.example staging/
          cd staging
          case "${{ matrix.asset }}" in
            *.zip)    python -m zipfile -c "../${{ matrix.asset }}" "${{ matrix.binary }}" "${{ matrix.binary_ui }}" .env.example ;;
            *.tar.gz) tar czf "../${{ matrix.asset }}" "${{ matrix.binary }}" "${{ matrix.binary_ui }}" .env.example ;;
            *)        echo "Unknown asset format: ${{ matrix.asset }}"; exit 1 ;;
          esac
```

> The Windows asset uses `python -m zipfile -c` with file arguments only — correct, because Windows ships `iro-ui.exe` (a file), never a `.app` directory. macOS/Linux use `tar`, which archives the `.app` bundle directory fine.

- [ ] **Step 3: Validate the workflow YAML**

Run (syntax + structure check; no network):
```bash
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/release.yml')); print('release.yml OK')" 2>/dev/null || \
  python3 -c "import sys; sys.exit('Install pyyaml or eyeball the YAML — CI will validate on push')"
```
Expected: `release.yml OK` (or the fallback note). Then manually confirm the matrix has `built_ui`/`binary_ui` on all three OSes and the package step references them.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "release: ship the iro-ui binary in every OS archive"
```

---

### Task C3: Final verification sweep

**Files:** none (verification + docs confirmation)

- [ ] **Step 1: Confirm .env.example already documents the UI keys**

Run:
```bash
grep -n "IRO_UI_PORT\|IRO_UI_PASSWORD" .env.example
```
Expected: `IRO_UI_PORT=` present and `# IRO_UI_PASSWORD=` reserved (commented). If a one-line comment above `IRO_UI_PORT` doesn't yet explain it, add: `# Control Center web UI port (iro ui / iro-ui). Default 8089.` — otherwise no change.

- [ ] **Step 2: Grep for stale single-binary assumptions**

Per the house rule (removing/renaming touches build + .github), confirm nothing else hardcodes "one binary":
```bash
grep -rn "dist/bin/iro\b" tools/ .github/ docs/ README.md src/docs/ 2>/dev/null
```
Review each hit: build/release should now handle both; docs that say "the binary" for the producer download should mention `iro-ui` is the double-click launcher (update operator-facing download docs minimally if they enumerate archive contents).

- [ ] **Step 3: Run the whole suite (exactly what CI runs)**

```bash
python3 tools/run-tests.py
python3 tools/lint.py
```
Expected: every test file `ALL PASS`; lint clean.

- [ ] **Step 4: Run the source-package self-verify**

```bash
python3 tools/build.py
```
Expected: builds `dist/IRO_Broadcast_Package/` and passes verify (tokenization, blanked password, no secrets, no shell scripts). `src/iro_ui.py` rides along automatically; verify rules are unchanged.

- [ ] **Step 5: Full binary build + dual smoke**

```bash
python3 tools/build-binary.py --version ci-smoke
```
Expected: both binaries build; both smoke tests print "OK".

- [ ] **Step 6: Commit any doc touch-ups**

```bash
git add -A
git commit -m "docs: note the iro-ui launcher in operator download docs"
```

(Skip if Steps 1-2 needed no edits.)

---

## Self-Review

**Spec coverage** (against `2026-06-07-control-center-design.md`, "Phasing" item 3 + "Build, release, CI"):
- Init step decomposition → Tasks A1-A2 (`STEP_KINDS`, `init_plan_data`, `init_step_action_data`). ✔
- Wizard UI (plan view: done/pending/skipped; gates as confirmations; long steps as jobs with live log) → Task A5. ✔
- `/api/init/plan` + `POST /api/init/step/<id>` → Task A3. ✔
- `iro-ui` per-OS targets (Windows `--noconsole`/`--windowed`, macOS `.app`, Linux plain) + native error dialog → Tasks B1-B3, C1. ✔
- Release archives contain `iro` + `iro-ui` → Task C2. ✔
- CI `binary-smoke` exercises both → automatic: it runs `build-binary.py`, which now builds + smokes both (Task C1); no `ci.yml` edit needed. ✔
- `.env.example` documents `IRO_UI_PORT` / reserves `IRO_UI_PASSWORD` → already present; confirmed in C3 Step 1. ✔
- `tools/build.py` verify unchanged, covers the new files → C3 Step 4. ✔

**Type consistency:**
- `init_plan_data(steps, kinds, browser, next_steps)` signature is identical across A2 (def), A2 tests, and the `_init_plan` caller. ✔
- Plan step dict keys (`key,label,kind,op,done,skip_reason,instruction`) are produced in A2 and consumed verbatim by the A5 renderer. ✔
- `init_step_action_data(key)` returns `{ok, key, done, skip_reason}` or `{ok: False, error}`; the A3 route maps `ok` → 200/400; A5 reads `r.ok`/`r.error`. ✔
- `run_ui(rest, fail, open_browser)` is defined once (B2) and called by both `ui_cmd` (B2) and `iro_ui.main` (B3) with matching args. ✔
- `_iro_job_executable(frozen, executable, win)` injectable signature matches its B2 tests and its in-`run_ui` no-arg call. ✔
- `build_target(launcher, workdir, version_file, sep, entry, name, windowed)` defined and called twice with matching args (C1). ✔

**Open verification points flagged inline (not placeholders — explicit "confirm X" with the expected answer):**
- A3: `tests/test_ui_server.py` request-helper names (reuse existing).
- A5: page HTML-escape helper name + existing CSS class names (reuse existing).
- C1: `/api/jobs/<id>` snapshot field names for the done/exit poll (grep `ui_jobs.py`).

**Scope:** one cohesive phase (the spec's Phase 3). Three independent groups, each independently testable; A and B can be built in either order (A4's ctx keys are folded into B2's `run_ui`, noted in both).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-08-control-center-phase3.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review (spec then quality) between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session with checkpoints for review.

Which approach?
