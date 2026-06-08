# IRO Control Center — Phase 2 (Jobs & Actions) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every one-shot `iro` action becomes a Control Center button (installs, graphics, media, cookies, setup export, preflight, export companion, event start/stop) with validated parameters, jobs become cancellable, and a new "Setup & Assets" section surfaces readiness state (cookies freshness, graphics/media completeness vs the sheet).

**Architecture:** Extends Phase 1 in place. `ui_ops.py` gains a parameter-validating `build_argv(name, params)` (the HTTP surface still can never pass free-form args). `ui_jobs.py` gains `cancel()`. `ui_server.py` parses an optional JSON POST body, adds `/api/jobs/<id>/cancel` and the on-demand `GET /api/assets` (sheet fetch — too slow for the 3 s status poll, which instead gains only the cheap local `cookies` check). `src/iro.py` gains `cookies_status_data()` / `assets_status_data()` reusing the existing event/preflight classifiers.

**Tech Stack:** Python stdlib only, vanilla HTML/JS. Spec: `docs/superpowers/specs/2026-06-07-control-center-design.md` (Phasing §2).

**Established context (verified against the code):**
- `get-cookies.py` takes the browser as an optional positional (default `firefox`).
- `install_tools.py` / `install_apps.py` accept `--yes` and `--update`.
- `preflight.Result` is a dataclass `level/name/detail`; levels are the strings `PASS/WARN/FAIL/INFO`.
- `event.classify_assets(label, missing, count, severity, fix)` → `Result`; `iro._asset_state(ev)` → `(g_dir, m_dir, missing_g, missing_m)` and may raise (callers classify).
- `iro.route(argv)` raises `ValueError` on bad usage — the new registry test uses it.
- Jobs run the full `iro` CLI as a child, so frozen-mode injections (`_oneshot_extra`: `--runtime-dir`, `--out` redirects) apply automatically.
- Conventions: stdlib-only runnable tests, `python3 tools/lint.py` clean, English only, no fixed ports in tests.

---

### Task 1: `ui_ops.py` — extended registry + `build_argv` with validated params

**Files:**
- Modify: `src/ui/ui_ops.py`
- Test: `tests/test_ui_ops.py`

- [ ] **Step 1: Write the failing tests.** In `tests/test_ui_ops.py`, REPLACE the existing `t_ops_registry_resolves_to_dispatch` (the registry now contains one-shots, which are not `DISPATCH` keys) with the route-based version, and append the `build_argv` tests — all above the `__main__` block:

```python
def t_ops_registry_routes_in_iro():
    # every registry entry must be a valid iro invocation (service verb,
    # oneshot, or export) — route() raises ValueError on anything unknown
    for name, argv in ui_ops.OPS.items():
        action = iro.route(list(argv))
        assert action["kind"] in ("service", "oneshot", "export"), name


def t_build_argv_plain_and_unknown():
    assert ui_ops.build_argv("relay-start") == ["relay", "start"]
    try:
        ui_ops.build_argv("not-an-op")
        raise AssertionError("unknown op accepted")
    except ValueError:
        pass


def t_build_argv_cookies_browser():
    assert ui_ops.build_argv("cookies", {"browser": "firefox"}) == ["cookies", "firefox"]
    assert ui_ops.build_argv("cookies") == ["cookies"]        # browser optional
    try:
        ui_ops.build_argv("cookies", {"browser": "lynx; rm -rf /"})
        raise AssertionError("invalid browser accepted")
    except ValueError:
        pass


def t_build_argv_event_stint():
    assert ui_ops.build_argv("event-start", {"stint": "4"}) == \
        ["event", "start", "--stint", "4"]
    assert ui_ops.build_argv("event-start", {"stint": ""}) == ["event", "start"]
    for bad in ("0", "-1", "abc", "1.5"):
        try:
            ui_ops.build_argv("event-start", {"stint": bad})
            raise AssertionError(f"invalid stint accepted: {bad}")
        except ValueError:
            pass


def t_build_argv_update_flag():
    assert ui_ops.build_argv("install-tools", {"update": True}) == \
        ["install-tools", "--yes", "--update"]
    assert ui_ops.build_argv("install-tools", {"update": False}) == \
        ["install-tools", "--yes"]
    assert ui_ops.build_argv("install-apps", {"update": True}) == \
        ["install-apps", "--yes", "--update"]


def t_build_argv_rejects_unknown_params():
    try:
        ui_ops.build_argv("relay-start", {"stint": "4"})
        raise AssertionError("param on paramless op accepted")
    except ValueError:
        pass
```

- [ ] **Step 2:** Run `python3 tests/test_ui_ops.py` → FAIL (`AttributeError: ... 'build_argv'` — and the old dispatch test removed).

- [ ] **Step 3: Implement.** Replace the whole content of `src/ui/ui_ops.py` with:

```python
"""Control Center operation registry: which `iro` invocations the web UI may
trigger, and how to build the child argv. Pure data + pure helpers (no I/O) —
the UI server routes /api/op/<name> through this table and build_argv() only,
so the HTTP surface can never run arbitrary commands or pass free-form args."""

# name -> base iro argv. Installs always run with --yes: jobs have no stdin
# (DEVNULL), so an interactive prompt would silently read EOF and decline.
OPS = {
    "relay-start": ["relay", "start"],
    "relay-stop": ["relay", "stop"],
    "relay-restart": ["relay", "restart"],
    "companion-start": ["companion", "start"],
    "companion-stop": ["companion", "stop"],
    "companion-restart": ["companion", "restart"],
    "streams-start": ["streams", "start"],
    "streams-stop": ["streams", "stop"],
    "tailscale-up": ["tailscale", "up"],
    "tailscale-down": ["tailscale", "down"],
    "obs-refresh": ["obs", "refresh"],
    "event-start": ["event", "start"],
    "event-stop": ["event", "stop"],
    "cookies": ["cookies"],
    "graphics": ["graphics"],
    "media": ["media"],
    "setup": ["setup"],
    "preflight": ["preflight"],
    "export-companion": ["export", "companion"],
    "install-tools": ["install-tools", "--yes"],
    "install-apps": ["install-apps", "--yes"],
}

# Browsers get-cookies can export from (yt-dlp --cookies-from-browser names).
BROWSERS = ("firefox", "chrome", "edge", "brave", "safari")


def _browser_arg(value):
    if value not in BROWSERS:
        raise ValueError(f"browser must be one of: {', '.join(BROWSERS)}")
    return [value]


def _stint_arg(value):
    s = str(value)
    if not s.isdigit() or int(s) < 1:
        raise ValueError("stint must be a 1-based stint number")
    return ["--stint", s]


def _update_flag(value):
    return ["--update"] if value else []


# op name -> {param name: validator(value) -> argv fragment}. Ops absent here
# accept no parameters at all.
PARAMS = {
    "cookies": {"browser": _browser_arg},
    "event-start": {"stint": _stint_arg},
    "install-tools": {"update": _update_flag},
    "install-apps": {"update": _update_flag},
}


def build_argv(name, params=None):
    """Base argv + validated optional params. Raises ValueError on an unknown
    op, an unknown param, or an invalid value. Empty-string/None values are
    treated as 'not provided' (the UI sends blank inputs as empty strings)."""
    if name not in OPS:
        raise ValueError(f"unknown operation: {name}")
    argv = list(OPS[name])
    spec = PARAMS.get(name, {})
    params = params or {}
    unknown = set(params) - set(spec)
    if unknown:
        raise ValueError(f"unexpected parameter(s): {', '.join(sorted(unknown))}")
    for key, validate in spec.items():
        if key in params and params[key] not in (None, ""):
            argv += validate(params[key])
    return argv


def job_argv(op_args, frozen, executable, iro_script):
    """argv to run `iro <op_args...>` as a child process: the frozen binary
    re-invokes itself (same mechanism as the daemon spawns); repo/package mode
    runs iro.py with this interpreter."""
    if frozen:
        return [executable] + list(op_args)
    return [executable, iro_script] + list(op_args)
```

- [ ] **Step 4:** Run `python3 tests/test_ui_ops.py` → `ALL PASS`; `python3 tools/lint.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add src/ui/ui_ops.py tests/test_ui_ops.py
git commit -m "feat(ui): one-shot ops + validated params in the registry (build_argv)"
```

---

### Task 2: `src/iro.py` — cookies + assets readiness data

**Files:**
- Modify: `src/iro.py` (insert below `ui_status_payload`, ~line 1160; modify `ui_status_payload` itself)
- Test: `tests/test_ui_ops.py`

- [ ] **Step 1: Write the failing tests** (append above `__main__`):

```python
# ---------- readiness data ----------

def t_cookies_status_data_shape():
    class R:
        level, detail = "PASS", "fresh (1 h old)"
    d = iro.cookies_status_data(status=lambda: R)
    assert d == {"level": "PASS", "detail": "fresh (1 h old)"}


def t_assets_status_data_complete(tmp):
    d = iro.assets_status_data(state=lambda ev: (tmp, tmp, [], []))
    assert d["ok"] is True
    assert d["graphics"]["level"] == "PASS" and d["media"]["level"] == "PASS"


def t_assets_status_data_missing_and_unverified(tmp):
    # graphics: sheet readable, one file missing -> FAIL with the filename;
    # media: sheet unreadable (None) + empty local dir -> its severity (WARN)
    d = iro.assets_status_data(state=lambda ev: (tmp, tmp, ["Overlay.png"], None))
    assert d["graphics"]["level"] == "FAIL"
    assert "Overlay.png" in d["graphics"]["detail"]
    assert d["media"]["level"] == "WARN"


def t_assets_status_data_error():
    def boom(ev):
        raise RuntimeError("no sheet")
    d = iro.assets_status_data(state=boom)
    assert d["ok"] is False and "no sheet" in d["error"]
```

Also UPDATE the existing `t_ui_status_payload_shape` test — the payload gains a `cookies` key:

```python
def t_ui_status_payload_shape():
    payload = iro.ui_status_payload(
        relay=lambda: {"alive": False}, companion=lambda: {"running": False},
        streams=lambda: [], tailscale=lambda: None,
        cookies=lambda: {"level": "WARN", "detail": "x"})
    assert payload == {"version": iro.version(), "relay": {"alive": False},
                       "companion": {"running": False}, "streams": [],
                       "tailscale_ip": None,
                       "cookies": {"level": "WARN", "detail": "x"}}
```

- [ ] **Step 2:** Run `python3 tests/test_ui_ops.py` → FAIL (`'cookies_status_data'`).

- [ ] **Step 3: Implement in `src/iro.py`.** Replace `ui_status_payload` and add the two new functions directly below it:

```python
def ui_status_payload(relay=None, companion=None, streams=None, tailscale=None,
                      cookies=None):
    """Aggregate health for the Control Center dashboard (/api/status).
    Each parameter is an optional zero-arg callable override (None = real
    probe). Cheap, local-only probes — the sheet-fetching asset check lives
    in assets_status_data() behind the on-demand /api/assets."""
    return {"version": version(),
            "relay": (relay or relay_status_data)(),
            "companion": (companion or companion_status_data)(),
            "streams": (streams or streams_status_data)(),
            "tailscale_ip": (tailscale or _tailscale_ip)(),
            "cookies": (cookies or cookies_status_data)()}


def cookies_status_data(status=None):
    """Local cookie-jar freshness (no network — safe for the 3 s poll)."""
    if status is None:
        pf = _event_modules()[1]
        path = os.path.join(_runtime_dir(), "cookies.txt")
        status = lambda: pf.cookies_status(path)
    res = status()
    return {"level": res.level, "detail": res.detail}


def assets_status_data(state=None):
    """Sheet-driven graphics/media readiness (network: sheet fetch, takes
    seconds — served on demand via /api/assets, never from the status poll)."""
    ev = _event_modules()[0]
    try:
        g_dir, m_dir, missing_g, missing_m = (state or _asset_state)(ev)
    except Exception as exc:
        return {"ok": False, "error": f"asset check failed: {exc}"}
    g = ev.classify_assets("Graphics", missing_g, ev.local_count(g_dir), ev.FAIL,
                           "run `iro graphics`")
    m = ev.classify_assets("Media", missing_m, ev.local_count(m_dir), ev.WARN,
                           "run `iro media`")
    return {"ok": True,
            "graphics": {"level": g.level, "detail": g.detail},
            "media": {"level": m.level, "detail": m.detail}}
```

(`E731` lambda-assignment is not in the lint rule set — `lambda:` assignments appear elsewhere in the file; if the linter complains, use a nested `def`.)

- [ ] **Step 4:** Run `python3 tests/test_ui_ops.py` → `ALL PASS`; `python3 tests/test_ui_server.py` → `ALL PASS` (its ctx stubs `status` entirely); `python3 tools/lint.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add src/iro.py tests/test_ui_ops.py
git commit -m "feat(iro): cookies + sheet-asset readiness as structured data"
```

---

### Task 3: `ui_jobs.py` — cancel

**Files:**
- Modify: `src/ui/ui_jobs.py`
- Test: `tests/test_ui_jobs.py`

- [ ] **Step 1: Write the failing tests** (append above `__main__`):

```python
def t_cancel_running_job():
    code = "import time; print('started', flush=True); time.sleep(30)"
    jm = ui_jobs.JobManager(lambda a: [sys.executable, "-c", code])
    job_id, _ = jm.start("sleepy", [])
    deadline = time.time() + 10            # wait until the child is really up
    while time.time() < deadline:
        lines, _n, _c = jm.lines_since(job_id, 0)
        if lines:
            break
        time.sleep(0.05)
    assert jm.cancel(job_id) is True
    snap = _wait_done(jm, job_id, timeout=10)
    assert snap["exit_code"] is not None and snap["exit_code"] != 0
    assert snap["cancelled"] is True


def t_cancel_finished_and_unknown():
    jm = ui_jobs.JobManager(lambda a: ["ignored"], spawn=lambda argv: FakeProc())
    job_id, _ = jm.start("echo", [])
    _wait_done(jm, job_id)
    assert jm.cancel(job_id) is False      # already finished
    assert jm.cancel("nope") is None       # unknown id
    assert jm.snapshot(job_id)["cancelled"] is False
```

- [ ] **Step 2:** Run `python3 tests/test_ui_jobs.py` → FAIL (`'JobManager' object has no attribute 'cancel'`).

- [ ] **Step 3: Implement in `src/ui/ui_jobs.py`.**

In `Job.__init__`, add below `self.exit_code = None`:

```python
        self.cancelled = False   # cancel() was requested (exit code will be non-zero)
```

In `snapshot()`, extend the returned dict:

```python
            return {"id": job.id, "op": job.op,
                    "running": job.exit_code is None, "exit_code": job.exit_code,
                    "cancelled": job.cancelled}
```

Add the method after `snapshot()`:

```python
    def cancel(self, job_id):
        """Request termination of a running job. True = signalled, False =
        already finished, None = unknown id. Terminates only the direct child
        (a daemon the child already detached keeps running — by design: cancel
        means 'stop this action', not 'tear down services')."""
        job = self.jobs.get(job_id)        # GIL-atomic dict read
        if job is None:
            return None
        with job.lock:
            if job.exit_code is not None:
                return False
            job.cancelled = True
        try:
            job.proc.terminate()
        except OSError:
            pass                           # exited between the check and the signal
        return True
```

- [ ] **Step 4:** Run `python3 tests/test_ui_jobs.py` → `ALL PASS`; `python3 tools/lint.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add src/ui/ui_jobs.py tests/test_ui_jobs.py
git commit -m "feat(ui): job cancellation (terminate direct child, cancelled flag)"
```

---

### Task 4: `ui_server.py` — JSON params, cancel route, `/api/assets` + ctx wiring

**Files:**
- Modify: `src/ui/ui_server.py`, `src/iro.py` (`ui_cmd` ctx)
- Test: `tests/test_ui_server.py`

- [ ] **Step 1: Write the failing tests.** In `tests/test_ui_server.py`, FIRST extend `_ctx()` with the two new keys (full replacement of the function):

```python
def _ctx(jobs=None):
    page = os.path.join(ROOT, "src", "ui", "control-center.html")
    return {"version": "test",
            "page_path": page,
            "status": lambda: {"relay": {"alive": False}},
            "ops": {"echo": ["echo-args"]},
            "build_argv": lambda name, params=None: ["echo-args"],
            "assets": lambda: {"ok": True,
                               "graphics": {"level": "PASS", "detail": "g"},
                               "media": {"level": "PASS", "detail": "m"}},
            "jobs": jobs or ui_jobs.JobManager(
                lambda a: [sys.executable, "-c", "print('hi from job')"]),
            "log_paths": {}}
```

Then append the new tests (above `__main__`):

```python
def _post_json(port, path, obj):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", method="POST",
        data=json.dumps(obj).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def t_op_param_validation_is_400():
    ctx = _ctx()
    def boom(name, params=None):
        raise ValueError("browser must be one of: firefox")
    ctx["build_argv"] = boom
    httpd, port = _serve(ctx)
    try:
        code, body = _post_json(port, "/api/op/echo", {"params": {"browser": "x"}})
        assert code == 400 and "browser" in json.loads(body)["error"]
    finally:
        httpd.shutdown()


def t_op_malformed_body_is_400():
    httpd, port = _serve(_ctx())
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/op/echo", method="POST",
            data=b"{not json", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        assert code == 400
    finally:
        httpd.shutdown()


def t_op_with_params_passes_them_to_build_argv():
    seen = []
    ctx = _ctx()
    ctx["build_argv"] = lambda name, params=None: seen.append((name, params)) or ["echo-args"]
    httpd, port = _serve(ctx)
    try:
        code, _b = _post_json(port, "/api/op/echo", {"params": {"browser": "firefox"}})
        assert code == 200
        assert seen == [("echo", {"browser": "firefox"})]
    finally:
        httpd.shutdown()


def t_assets_route():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/assets")
        data = json.loads(body)
        assert code == 200 and data["ok"] is True
        assert data["graphics"]["level"] == "PASS"
    finally:
        httpd.shutdown()


def t_assets_route_provider_error_is_500():
    ctx = _ctx()
    def boom():
        raise RuntimeError("sheet down")
    ctx["assets"] = boom
    httpd, port = _serve(ctx)
    try:
        code, body = _get(port, "/api/assets")
        assert code == 500 and "sheet down" in json.loads(body)["error"]
    finally:
        httpd.shutdown()


def t_cancel_route():
    httpd, port = _serve(_ctx())
    try:
        _c, body = _post(port, "/api/op/echo")
        job_id = json.loads(body)["job_id"]
        code, body = _post(port, f"/api/jobs/{job_id}/cancel")
        assert code == 200 and json.loads(body)["ok"] is True
        code, _b = _post(port, "/api/jobs/nope/cancel")
        assert code == 404
    finally:
        httpd.shutdown()
```

- [ ] **Step 2:** Run `python3 tests/test_ui_server.py` → FAIL (params ignored / unknown routes 404).

- [ ] **Step 3: Implement in `src/ui/ui_server.py`.**

Add a body-reading helper to the Handler (below `_sse_headers`):

```python
        def _body_json(self):
            """Parsed JSON POST body; {} when absent/empty, None when malformed."""
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception:
                return None
```

In `do_GET`, add the assets route (below the `/api/status` block):

```python
            if path == "/api/assets":
                try:
                    return self._json(ctx["assets"]())
                except Exception as exc:    # sheet/probe failure must stay JSON
                    return self._json({"ok": False,
                                       "error": f"assets check failed: {exc}"},
                                      code=500)
```

In `do_POST`, replace the `/api/op/` block and add the cancel route above it:

```python
            if path.startswith("/api/jobs/") and path.endswith("/cancel"):
                job_id = path.split("/")[3]
                result = ctx["jobs"].cancel(job_id) if job_id else None
                if result is None:
                    return self._not_found("unknown job")
                return self._json({"ok": True, "cancelled": result})
            if path.startswith("/api/op/"):
                name = path[len("/api/op/"):]
                if name not in ctx["ops"]:
                    return self._not_found(f"unknown operation: {name}")
                body = self._body_json()
                if body is None:
                    return self._json({"ok": False, "error": "malformed JSON body"},
                                      code=400)
                try:
                    argv = ctx["build_argv"](name, body.get("params"))
                except ValueError as exc:
                    return self._json({"ok": False, "error": str(exc)}, code=400)
                job_id, err = ctx["jobs"].start(name, argv)
                if err:
                    return self._json({"ok": False, "error": err}, code=409)
                return self._json({"ok": True, "job_id": job_id})
```

Update the `make_handler` docstring's ctx line to include the new keys:

```python
    """ctx: version, page_path, status() -> dict, ops {name: argv},
    build_argv(name, params) -> argv (raises ValueError), assets() -> dict,
    jobs (ui_jobs.JobManager), log_paths {name: () -> path|None},
    shutdown() (installed by serve())."""
```

In `src/iro.py` `ui_cmd()`, extend the ctx dict (after the `"ops"` line):

```python
        "build_argv": ops_mod.build_argv,
        "assets": assets_status_data,
```

- [ ] **Step 4:** Run `python3 tests/test_ui_server.py` → `ALL PASS`; `python3 tests/test_ui_jobs.py`, `python3 tests/test_ui_ops.py`, `python3 tests/test_iro.py` → `ALL PASS`; `python3 tools/lint.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add src/ui/ui_server.py src/iro.py tests/test_ui_server.py
git commit -m "feat(ui): op params via JSON body, job cancel route, on-demand /api/assets"
```

---

### Task 5: `control-center.html` — Event row, Setup & Assets section, job cancel

**Files:**
- Modify: `src/ui/control-center.html`

The page test (`t_root_serves_the_page`) keeps passing; this task is verified visually in Task 6. Apply ALL of the following edits.

- [ ] **Step 1: CSS additions.** In the `<style>` block, below the `.badge.on .dot` rule, add:

```css
  .badge.warn { background:rgba(245,158,11,.12); color:#FCD34D;
                border-color:rgba(245,158,11,.35); }
  .badge.warn .dot { background:var(--warn); }
  .badge.fail { background:rgba(239,68,68,.12); color:#FCA5A5;
                border-color:rgba(239,68,68,.35); }
  .badge.fail .dot { background:var(--bad); }
```

Below the `select:focus-visible` rule, add:

```css
  input[type=number] { background:#232C42; color:var(--txt); width:78px;
           border:1px solid var(--line); border-radius:8px; padding:7px 10px;
           font:13px var(--mono); min-height:34px; }
  input[type=number]:focus-visible { outline:2px solid var(--accent);
           outline-offset:2px; }
```

- [ ] **Step 2: Event row.** In the Dashboard section, directly above the `OBS pages` row, insert:

```html
    <div class="row"><span class="name">Event</span>
      <span class="dim grow">Bring the stack up (Tailscale, Discord, relay, OBS, Companion) / stop iro services</span>
      <input id="stint" type="number" min="1" placeholder="stint">
      <button onclick="opEventStart()">
        <svg viewBox="0 0 24 24"><polygon points="6 3 20 12 6 21 6 3"/></svg>Start</button>
      <button class="danger" onclick="op('event-stop', true)">
        <svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>Stop</button></div>
```

- [ ] **Step 3: Job cancel button.** Replace the job section header with:

```html
    <h2>Job: <span id="jobtitle" style="color:var(--txt)"></span>
        <span class="spin" id="jobspin"></span>
        <span id="jobchip" hidden></span>
        <span class="spacer"></span>
        <button class="danger" id="jobcancel" hidden onclick="cancelJob()">
          <svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>Cancel</button></h2>
```

And add `.spacer { flex:1; }` usage note: the rule already exists globally from the header — no CSS change needed.

- [ ] **Step 4: Setup & Assets section.** Insert between the job section (`</section>` of `id="job"`) and the Service logs section:

```html
  <section>
    <h2>Setup &amp; Assets</h2>
    <div class="row"><span class="name">Cookies</span>
      <span class="badge" id="b-cookies"><span class="dot"></span><span>…</span></span>
      <span class="dim grow" id="d-cookies"></span>
      <select id="browser" aria-label="Browser to export YouTube cookies from">
        <option value="firefox" selected>firefox</option>
        <option value="chrome">chrome</option>
        <option value="edge">edge</option>
        <option value="brave">brave</option>
        <option value="safari">safari</option>
      </select>
      <button onclick="op('cookies', false, {browser: $('browser').value})">
        <svg viewBox="0 0 24 24"><path d="M23 4v6h-6"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>Refresh</button></div>
    <div class="row"><span class="name">Graphics</span>
      <span class="badge" id="b-graphics"><span class="dot"></span><span>unchecked</span></span>
      <span class="dim grow" id="d-graphics"></span>
      <button onclick="op('graphics')">
        <svg viewBox="0 0 24 24"><path d="M12 5v14"/><path d="m19 12-7 7-7-7"/></svg>Download</button></div>
    <div class="row"><span class="name">Media</span>
      <span class="badge" id="b-media"><span class="dot"></span><span>unchecked</span></span>
      <span class="dim grow" id="d-media"></span>
      <button onclick="op('media')">
        <svg viewBox="0 0 24 24"><path d="M12 5v14"/><path d="m19 12-7 7-7-7"/></svg>Download</button></div>
    <div class="row"><span class="name">Assets</span>
      <span class="dim grow">Verify graphics/media against the sheet's Assets tab (fetches the sheet)</span>
      <button onclick="checkAssets()">
        <svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>Check</button></div>
    <div class="row"><span class="name">OBS setup</span>
      <span class="dim grow">Write the localized OBS collection into runtime/ (import it in OBS afterwards)</span>
      <button onclick="op('setup')">Export</button></div>
    <div class="row"><span class="name">Companion</span>
      <span class="dim grow">Write the button config into runtime/ (import it in Companion afterwards)</span>
      <button onclick="op('export-companion')">Export</button></div>
    <div class="row"><span class="name">Tools</span>
      <span class="dim grow">yt-dlp / streamlink / ffmpeg / deno</span>
      <button onclick="op('install-tools', true)">Install</button>
      <button onclick="op('install-tools', true, {update: true})">Update</button></div>
    <div class="row"><span class="name">Apps</span>
      <span class="dim grow">OBS / Companion / Tailscale / Discord</span>
      <button onclick="op('install-apps', true)">Install</button>
      <button onclick="op('install-apps', true, {update: true})">Update</button></div>
    <div class="row"><span class="name">Preflight</span>
      <span class="dim grow">Hardware / tools / config check</span>
      <button onclick="op('preflight')">Run</button></div>
  </section>
```

- [ ] **Step 5: JS changes.** Replace `op()` and `watchJob()` with, and add the new functions:

```js
async function op(name, confirmFirst, params) {
  if (confirmFirst && !confirm('Run ' + name + '?')) return;
  let r;
  try {
    r = await (await fetch('/api/op/' + name, {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({params: params || {}})})).json();
  } catch (e) { alert('Control Center not reachable.'); return; }
  if (!r.ok) { alert(r.error); return; }
  watchJob(name, r.job_id);
}

function opEventStart() {
  const v = $('stint').value.trim();
  op('event-start', true, v ? {stint: v} : {});
}

let jobId = null, jobCancelled = false;

function watchJob(name, id) {
  if (jobES) jobES.close();
  jobId = id;
  jobCancelled = false;
  $('job').hidden = false;
  $('jobtitle').textContent = name;
  $('jobspin').hidden = false;
  $('jobchip').hidden = true;
  $('jobcancel').hidden = false;
  $('joblog').textContent = '';
  jobES = new EventSource('/api/jobs/' + id + '/stream');
  jobES.onmessage = e => {
    $('joblog').textContent += e.data + '\n';
    $('joblog').scrollTop = 1e9;
  };
  jobES.addEventListener('done', e => {
    const ok = e.data === '0';
    $('jobspin').hidden = true;
    $('jobcancel').hidden = true;
    const chip = $('jobchip');
    chip.hidden = false;
    chip.className = 'chip ' + (ok ? 'ok' : 'fail');
    chip.textContent = ok ? 'done'
                          : (jobCancelled ? 'cancelled'
                                          : 'failed (exit ' + e.data + ')');
    jobES.close();
    refresh();
    if (name === 'graphics' || name === 'media') checkAssets();
  });
}

async function cancelJob() {
  if (!jobId) return;
  jobCancelled = true;
  try { await fetch('/api/jobs/' + jobId + '/cancel', {method: 'POST'}); }
  catch (e) {}
}

function setLevelBadge(key, level, text, detail) {
  const b = $('b-' + key);
  b.classList.remove('on', 'warn', 'fail');
  if (level === 'PASS') b.classList.add('on');
  else if (level === 'WARN') b.classList.add('warn');
  else if (level === 'FAIL') b.classList.add('fail');
  b.lastElementChild.textContent = text;
  $('d-' + key).textContent = detail || '';
}

async function checkAssets() {
  setLevelBadge('graphics', '', 'checking…', '');
  setLevelBadge('media', '', 'checking…', '');
  let a;
  try {
    a = await (await fetch('/api/assets', {cache: 'no-store'})).json();
  } catch (e) { a = {ok: false, error: 'Control Center not reachable'}; }
  if (!a.ok) {
    setLevelBadge('graphics', 'WARN', 'ERROR', a.error || 'check failed');
    setLevelBadge('media', 'WARN', 'ERROR', '');
    return;
  }
  setLevelBadge('graphics', a.graphics.level,
                a.graphics.level === 'PASS' ? 'COMPLETE' : a.graphics.level,
                a.graphics.detail);
  setLevelBadge('media', a.media.level,
                a.media.level === 'PASS' ? 'COMPLETE' : a.media.level,
                a.media.detail);
}
```

And in `refresh()`, after the tailscale `setBadge` line, add:

```js
  if (s.cookies) setLevelBadge('cookies', s.cookies.level,
      s.cookies.level === 'PASS' ? 'FRESH' : s.cookies.level, s.cookies.detail);
```

- [ ] **Step 6:** Run `python3 tests/test_ui_server.py` → `ALL PASS` (page contract test).

- [ ] **Step 7: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(ui): event row, Setup & Assets section, job cancel button"
```

---

### Task 6: Full verification + visual check

**Files:** none new (verification only; fixes go where they belong)

- [ ] **Step 1:** `python3 tools/run-tests.py` → `ALL TEST FILES PASS`; `python3 tools/lint.py` → clean.

- [ ] **Step 2: Dev-mode smoke** (override port; repo mode):

```bash
IRO_UI_PORT=8189 python3 src/iro.py ui --no-browser &
sleep 2
curl -s http://127.0.0.1:8189/api/status | python3 -m json.tool | grep -A2 cookies
curl -s http://127.0.0.1:8189/api/assets | python3 -m json.tool
curl -s -X POST -H "Content-Type: application/json" -d '{"params":{"browser":"lynx"}}' \
     http://127.0.0.1:8189/api/op/cookies          # expect 400 browser error
curl -s -X POST http://127.0.0.1:8189/api/quit
```

Expected: status payload has `cookies.level`; `/api/assets` returns graphics/media levels (or ok:false when the sheet is unreachable — also a valid outcome); invalid browser → `{"ok": false, "error": "browser must be one of: ..."}`.

- [ ] **Step 3:** `python3 tools/build.py` → verify step passes. `python3 tools/build-binary.py` → `Smoke test OK (... ui).`

- [ ] **Step 4: Visual check** — start the dev server again, open the page (Playwright or manually), verify: Event row with stint input, Setup & Assets section with cookies badge populated from the poll, Check → graphics/media badges, a job with the Cancel button visible while running.

- [ ] **Step 5: Commit** any fixes that surfaced, message style `fix(ui): <what> (phase-2 verification)`.

---

## Out of scope for Phase 2 (do NOT build now)

- Init wizard (`/api/init/*`), the `iro-ui` double-click binary, packaging/release — Phase 3.
- Tailnet bind + password auth — v2.
- Update self-update (`iro update`) as a UI op — deliberately excluded: swapping the binary under a running job manager is its own problem; revisit in Phase 3 with the packaging work.
