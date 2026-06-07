# Live Failure Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make live failures visible where the operator looks — feed health and cookie staleness in `/status` and on the director panel (banner/toasts), guards on risky feed actions, a preflight Google-Sheet check, and three plain-language message fixes.

**Architecture:** The `Feed.run()` loop maintains `phase`/`phase_since`/`last_error` attributes (approach 1 from the spec); `Relay.status()` exposes them plus an on-demand `cookies_health` computed from the cookies.txt mtime. The panel renders only (state banner + toasts + health line) from its existing 2 s polls — no new endpoints. Preflight gains a pure `classify_sheet()` fed by an isolated CSV fetch.

**Tech Stack:** Pure Python stdlib (repo rule: no packages, no pytest; tests are runnable scripts with `t_*` functions). Panel is a single static HTML file with vanilla JS (no test suite by convention — keep client logic render-only).

**Spec:** `docs/superpowers/specs/2026-06-07-live-failure-visibility-design.md`

**Conventions that apply to every task:**
- Run `python3 tools/lint.py` after changing any Python file; `--fix` auto-corrects. Match the file's existing `# noqa: BLE001` style if ruff flags a broad `except Exception` that a best-effort contract requires.
- Tests run with `python3 tests/test_<name>.py` — expected final line: `ALL PASS`.
- All code/comments/docs in English.
- The relay (`src/relay/iro-feeds.py`) stays import-free/standalone — duplicated constants carry a "keep in sync" comment (existing convention: `detect_tailscale_ip`).

---

### Task 1: `cookie_health()` — pure cookie-staleness helper in the relay

**Files:**
- Create: `tests/test_health.py`
- Modify: `src/relay/iro-feeds.py` (constant near the top ~line 60 area with the other constants; helper next to `_cookie_hint`, ~line 1406)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_health.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for live-failure-visibility: cookie_health, resolve_hls
error propagation, Feed phases, Relay.status() contract.
Run: python3 tests/test_health.py"""
import importlib.util, os, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "iro-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_cookie_health_no_path():
    # Running cookie-less (public streams) is legitimate: never stale.
    assert m.cookie_health(None) == {"present": False, "age_h": None, "stale": False}


def t_cookie_health_missing_file():
    h = m.cookie_health(os.path.join(HERE, "no-such-cookies.txt"))
    assert h == {"present": False, "age_h": None, "stale": False}


def t_cookie_health_fresh_and_stale():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "cookies.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# Netscape HTTP Cookie File\n")
        mtime = os.path.getmtime(path)
        fresh = m.cookie_health(path, now=mtime + 3600)
        assert fresh == {"present": True, "age_h": 1.0, "stale": False}, fresh
        stale = m.cookie_health(path, now=mtime + 14 * 3600)
        assert stale["present"] is True and stale["stale"] is True
        assert round(stale["age_h"]) == 14


def t_cookie_max_age_matches_preflight():
    # One source of truth: 12 h, same as preflight.cookies_status default.
    assert m.COOKIE_MAX_AGE_H == 12


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_health.py`
Expected: `AttributeError: module 'irofeeds' has no attribute 'cookie_health'`

- [ ] **Step 3: Implement `cookie_health()`**

In `src/relay/iro-feeds.py`, add the constant next to the other module constants (near `YTDLP_FORMAT` / `RESOLVE_RETRY` at the top):

```python
COOKIE_MAX_AGE_H = 12   # keep in sync with preflight.py cookies_status(max_age_hours)
```

Add the helper directly above `def _cookie_hint(` (~line 1406):

```python
def cookie_health(path, now=None, max_age_hours=COOKIE_MAX_AGE_H):
    """Cookie staleness for /status, computed on demand from the file mtime —
    during a 24 h event the cookies age while the relay runs, so this must be
    live, not a startup snapshot. Running cookie-less (path None / file gone)
    is a legitimate configuration (public streams): present=False, stale=False
    — the panel raises its cookie banner only on stale=True."""
    if not path or not os.path.isfile(path):
        return {"present": False, "age_h": None, "stale": False}
    now = time.time() if now is None else now
    age_h = round((now - os.path.getmtime(path)) / 3600, 1)
    return {"present": True, "age_h": age_h, "stale": age_h > max_age_hours}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_health.py`
Expected: `ALL PASS`

- [ ] **Step 5: Lint and commit**

```bash
python3 tools/lint.py
git add tests/test_health.py src/relay/iro-feeds.py
git commit -m "feat(relay): cookie_health() — on-demand cookie staleness (12 h, mirrors preflight)"
```

---

### Task 2: `resolve_hls()` returns `(url, error)` — carry the yt-dlp error text

**Files:**
- Modify: `src/relay/iro-feeds.py:701-729` (`resolve_hls`), `src/relay/iro-feeds.py:1144-1150` (the only call site, in `Feed.run`)
- Test: `tests/test_health.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_health.py` (above the `__main__` block):

```python
class _FakeRun:
    def __init__(self, stdout="", stderr=""):
        self.stdout, self.stderr = stdout, stderr


def t_resolve_hls_success_returns_url_and_no_error():
    orig = m.subprocess.run
    m.subprocess.run = lambda *a, **k: _FakeRun(stdout="https://hls.example/x.m3u8\n")
    try:
        url, err = m.resolve_hls("https://yt.example/x", None, os.devnull)
    finally:
        m.subprocess.run = orig
    assert url == "https://hls.example/x.m3u8" and err is None


def t_resolve_hls_failure_returns_last_stderr_line():
    orig = m.subprocess.run
    m.subprocess.run = lambda *a, **k: _FakeRun(
        stderr="WARNING: noise\nERROR: This live event will begin in 2 hours\n")
    try:
        url, err = m.resolve_hls("https://yt.example/x", None, os.devnull)
    finally:
        m.subprocess.run = orig
    assert url is None
    assert "live event will begin" in err


def t_resolve_hls_failure_without_stderr_says_not_live():
    orig = m.subprocess.run
    m.subprocess.run = lambda *a, **k: _FakeRun()
    try:
        url, err = m.resolve_hls("https://yt.example/x", None, os.devnull)
    finally:
        m.subprocess.run = orig
    assert url is None and err == "not live?"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_health.py`
Expected: FAIL — `cannot unpack non-sequence` / `TypeError` (current `resolve_hls` returns a single value).

- [ ] **Step 3: Change `resolve_hls` to return `(url, error)`**

Replace the body of `resolve_hls` (lines 701-729) with:

```python
def resolve_hls(url, cookies, logfile, fmt=YTDLP_FORMAT):
    """Resolve a YouTube live URL to a direct HLS manifest URL via yt-dlp
    (handles cookies + the bot-check). Returns (url, None) on success or
    (None, error_line) — the error line feeds /status so the panel can show
    WHY a feed is stuck connecting (today it only lands in feed_X.log)."""
    cmd = ["yt-dlp", "-g", "-f", fmt, "--no-warnings", "--no-playlist", url]
    if cookies:
        cmd += ["--cookies", cookies]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=90)
    except FileNotFoundError:
        # Startup checks for yt-dlp; reaching here means it vanished mid-run.
        try:
            with open(logfile, "a", encoding="utf-8") as log:
                log.write("   yt-dlp not found on PATH\n")
        except Exception:
            pass  # logging is best-effort; never let it break the resolve loop
        return None, "yt-dlp not found on PATH"
    except subprocess.TimeoutExpired:
        return None, "yt-dlp timed out (90 s)"
    out = [l for l in (r.stdout or "").splitlines() if l.startswith("http")]
    if out:
        return out[0], None
    err = (r.stderr or "").strip().splitlines()
    last = err[-1] if err else "not live?"
    try:
        with open(logfile, "a", encoding="utf-8") as log:
            log.write(f"   yt-dlp could not resolve {url} ({last})\n")
    except Exception:
        pass  # logging is best-effort; never let it break the resolve loop
    return None, last
```

Update the call site in `Feed.run` (line 1144): replace

```python
            hls = resolve_hls(url, self.cookies, self.logfile, self.fmt)
```

with

```python
            hls, err = resolve_hls(url, self.cookies, self.logfile, self.fmt)
```

and replace the failure branch (lines 1148-1150)

```python
            if not hls:
                time.sleep(RESOLVE_RETRY)   # not live yet / could not resolve -> poll again
                continue
```

with

```python
            if not hls:
                self.last_error = err       # surfaced via /status (panel health line)
                time.sleep(RESOLVE_RETRY)   # not live yet / could not resolve -> poll again
                continue
```

(`self.last_error` does not exist yet — Task 3 adds it to `Feed.__init__` in the same PR; the suite is only expected green again at the end of Task 3. If you must commit Task 2 standalone, run only the `resolve_hls` tests.)

- [ ] **Step 4: Run the resolve tests**

Run: `python3 tests/test_health.py`
Expected: the three `t_resolve_hls_*` checks print `ok`; `python3 tests/test_pov.py` still prints `ALL PASS` (it never calls `resolve_hls`).

- [ ] **Step 5: Lint (commit together with Task 3)**

```bash
python3 tools/lint.py
```

---

### Task 3: Feed phase attributes (`phase`, `phase_since`, `last_error`)

**Files:**
- Modify: `src/relay/iro-feeds.py:1080-1172` (class `Feed`)
- Test: `tests/test_health.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_health.py`:

```python
def t_feed_initial_phase_is_idle():
    f = m.Feed("A", 53001, 0, lambda: [], HERE)
    assert f.phase == "idle"
    assert f.last_error is None
    assert isinstance(f.phase_since, float)


def t_set_phase_updates_since_only_on_change():
    f = m.Feed("A", 53001, 0, lambda: [], HERE)
    f._set_phase("connecting")
    assert f.phase == "connecting"
    since = f.phase_since
    f._set_phase("connecting")          # same phase -> timestamp untouched
    assert f.phase_since == since       # duration accumulates across retries
    f._set_phase("serving")
    assert f.phase == "serving" and f.phase_since >= since
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_health.py`
Expected: `AttributeError: 'Feed' object has no attribute 'phase'`

- [ ] **Step 3: Implement the phase machine**

In `Feed.__init__` (after `self.logfile = ...`, line 1093) add:

```python
        # Health for /status: phase ("idle" | "connecting" | "serving"),
        # since-when, and the last yt-dlp error line. Written by the run()
        # thread, read by Relay.status() — attribute reads/writes are atomic
        # enough (same convention as self.proc).
        self.phase = "idle"
        self.phase_since = time.time()
        self.last_error = None
```

Add the helper method after `is_serving` (line 1107):

```python
    def _set_phase(self, phase):
        """Phase + timestamp, updated only on change — so state_age_s keeps
        accumulating across resolve retries within one 'connecting' stretch."""
        if phase != self.phase:
            self.phase = phase
            self.phase_since = time.time()
```

Update `run()` (lines 1135-1168) — the full method after the change:

```python
    def run(self):
        while not self.stop:
            ch, i = self.current_channel()
            if not ch:
                self._set_phase("idle")
                time.sleep(3); continue
            self._set_phase("connecting")
            url = channel_url(ch)
            with open(self.logfile, "a", encoding="utf-8") as log:
                log.write(f"\n>> [{self.name}:{self.port}] stint {i+1} -> resolving {url}\n"); log.flush()
            # 1) resolve the live HLS URL via yt-dlp (cookies + bot-check handling)
            hls, err = resolve_hls(url, self.cookies, self.logfile, self.fmt)
            if self.stop: break
            if self.advance.is_set():
                self.advance.clear(); continue
            if not hls:
                self.last_error = err       # surfaced via /status (panel health line)
                time.sleep(RESOLVE_RETRY)   # not live yet / could not resolve -> poll again
                continue
            # 2) serve the direct HLS URL via streamlink (no YouTube plugin -> no bot-check)
            with open(self.logfile, "a", encoding="utf-8") as log:
                log.write(f">> [{self.name}:{self.port}] serving stint {i+1}\n"); log.flush()
                cmd = ["streamlink", hls, "best", "--player-external-http",
                       "--player-external-http-port", str(self.port)] + STREAMLINK_SERVE
                try:
                    self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
                    self.last_error = None
                    self._set_phase("serving")
                    self.proc.wait()
                except FileNotFoundError:
                    # Startup checks for streamlink; reaching here means it vanished mid-run.
                    log.write(f">> [{self.name}] streamlink not found on PATH — retrying\n"); log.flush()
                    self.proc = None
                    time.sleep(RETRY_SLEEP); continue
            self._set_phase("connecting")   # child gone -> we are reconnecting
            if self.stop:
                break
            if self.advance.is_set():
                self.advance.clear(); continue
            time.sleep(RETRY_SLEEP)   # stream ended / manifest expired -> re-resolve
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_health.py` → `ALL PASS`
Run: `python3 tests/test_pov.py` → `ALL PASS`

- [ ] **Step 5: Lint and commit (Tasks 2+3 together)**

```bash
python3 tools/lint.py
git add tests/test_health.py src/relay/iro-feeds.py
git commit -m "feat(relay): feed phase machine + yt-dlp error propagation (resolve_hls returns (url, error))"
```

---

### Task 4: `Relay.status()` — feed state, `state_age_s`, `last_error`, `cookies_health`

**Files:**
- Modify: `src/relay/iro-feeds.py:1198-1213` (`Relay.status`)
- Test: `tests/test_health.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_health.py`:

```python
def _mk_relay(td, items, cookies=None, pov_items=None):
    src = m.ScheduleSource(None, os.path.join(td, "cache.txt"), None)
    src.items = list(items)
    src.rows = [(u, "", i + 1) for i, u in enumerate(items)]
    pov_src = None
    if pov_items is not None:
        pov_src = m.ScheduleSource(None, os.path.join(td, "pov-cache.txt"), None)
        pov_src.items = list(pov_items)
        pov_src.rows = [(u, "", i + 1) for i, u in enumerate(pov_items)]
    return m.Relay(src, [53001, 53002], td, cookies,
                   pov_source=pov_src, pov_port=53003 if pov_src else None)


def t_status_reports_feed_state_age_and_error():
    with tempfile.TemporaryDirectory() as td:
        r = _mk_relay(td, ["https://youtu.be/a", "https://youtu.be/b"])
        r.A._set_phase("serving")
        r.B._set_phase("connecting")
        r.B.last_error = "ERROR: This live event will begin in 2 hours"
        st = r.status()
        assert st["feeds"]["A"]["state"] == "serving"
        assert st["feeds"]["B"]["state"] == "connecting"
        assert st["feeds"]["B"]["last_error"].startswith("ERROR:")
        assert st["feeds"]["A"]["last_error"] is None
        assert st["feeds"]["A"]["state_age_s"] >= 0
        # existing keys unchanged
        assert st["feeds"]["A"]["stint"] == 1 and st["feeds"]["A"]["port"] == 53001
        assert st["cookies"] is False


def t_status_cookies_health_no_cookies():
    with tempfile.TemporaryDirectory() as td:
        r = _mk_relay(td, ["https://youtu.be/a"])
        st = r.status()
        assert st["cookies_health"] == {"present": False, "age_h": None, "stale": False}


def t_status_cookies_health_stale_file():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "cookies.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("x\n")
        old = os.path.getmtime(path) - 14 * 3600
        os.utime(path, (old, old))
        r = _mk_relay(td, ["https://youtu.be/a"], cookies=path)
        st = r.status()
        assert st["cookies_health"]["present"] is True
        assert st["cookies_health"]["stale"] is True


def t_status_pov_stopped_when_paused_with_age():
    with tempfile.TemporaryDirectory() as td:
        r = _mk_relay(td, ["https://youtu.be/a"], pov_items=["https://youtu.be/p"])
        st = r.status()                      # POV starts paused
        assert st["pov"]["state"] == "stopped"
        assert st["pov"]["state_age_s"] >= 0
        assert st["pov"]["url"] == "https://youtu.be/p"   # existing key kept
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_health.py`
Expected: `KeyError: 'state'` (feeds A/B carry no state yet).

- [ ] **Step 3: Implement the status enrichment**

Replace `Relay.status()` (lines 1198-1213) with:

```python
    def status(self):
        now = time.time()
        sched = self.source.get()
        out = {"schedule_len": len(sched), "cookies": bool(self.cookies),
               "cookies_health": cookie_health(self.cookies, now=now),
               "source": self.source.health(), "feeds": {}}
        for k, f in self.feeds.items():
            ch, i = f.current_channel()
            out["feeds"][k] = {"port": f.port, "index": i, "stint": i + 1,
                               "channel": ch,
                               "state": "stopped" if f.paused else f.phase,
                               "state_age_s": round(now - f.phase_since, 1),
                               "last_error": f.last_error}
        if self.pov:
            raw = (self.pov_source.get()[:1] or [None])[0] if self.pov_source else None
            out["pov"] = {"port": self.pov.port, "url": raw,
                          "state": "stopped" if self.pov.paused else self.pov.phase,
                          "state_age_s": round(now - self.pov.phase_since, 1),
                          "source": self.pov_source.health() if self.pov_source else None}
        return out
```

(The old POV derivation — `paused`/`is_serving()`/`raw` — is replaced by the phase machine: identical observable states, but `connecting` vs `idle` now comes from what the loop actually does.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_health.py` → `ALL PASS`
Run: `python3 tests/test_pov.py && python3 tests/test_hud.py && python3 tests/test_timer.py && python3 tests/test_setup.py` → all `ALL PASS` (the relay module is shared).

- [ ] **Step 5: Lint and commit**

```bash
python3 tools/lint.py
git add tests/test_health.py src/relay/iro-feeds.py
git commit -m "feat(relay): /status carries feed state + state_age_s + last_error and cookies_health"
```

---

### Task 5: Relay startup cookie WARN + clearer bind error

**Files:**
- Modify: `src/relay/iro-feeds.py` (~line 1556 after the cookies chmod; ~line 1645 bind error)

- [ ] **Step 1: Add the startup WARN**

In `main()`, directly after the existing cookies hardening block

```python
    if cookies:
        try: os.chmod(cookies, 0o600)   # contains a live YouTube session — owner-only
        except OSError: pass            # best-effort hardening; never block startup
```

append:

```python
    if cookies:
        _ch = cookie_health(cookies)
        if _ch["stale"]:
            print(f"WARN: cookies.txt is {_ch['age_h']:.0f} h old — cookies rotate; "
                  "run 'iro cookies firefox' before the event.")
```

- [ ] **Step 2: Sharpen the bind error**

Replace (line ~1645)

```python
        sys.exit(f"Could not bind the control server on {bind_addrs} port {args.http_port}.")
```

with

```python
        sys.exit(f"Could not bind the control server on {bind_addrs} port {args.http_port} "
                 f"— port may already be in use: run 'iro preflight' or 'iro status' "
                 f"to see what holds it.")
```

- [ ] **Step 3: Smoke-check the module still parses and the suite is green**

Run: `python3 src/relay/iro-feeds.py --help`
Expected: usage text, exit 0.
Run: `python3 tests/test_health.py && python3 tests/test_pov.py` → `ALL PASS`.

- [ ] **Step 4: Lint and commit**

```bash
python3 tools/lint.py
git add src/relay/iro-feeds.py
git commit -m "feat(relay): startup WARN on stale cookies + actionable bind-failure message"
```

---

### Task 6: Panel — banner + toast plumbing, sync/relay/cookie banners, toast hookups

**Files:**
- Modify: `src/director/director-panel.html`

No automated tests (project convention: panel JS untested — all decisions are server-computed; this task is rendering only).

- [ ] **Step 1: Add the CSS**

After the `#log` rule (line ~162) insert:

```css
  /* ---------- state banners (persistent) + toasts (one-off) ---------- */
  #banners{display:flex;flex-direction:column;gap:8px;margin-bottom:12px}
  #banners:empty{display:none}
  .banner{border-radius:10px;padding:10px 14px;font-size:13px;font-weight:600;
    letter-spacing:.04em;display:flex;gap:10px;align-items:center}
  .banner.amber{background:#2e2305;border:1px solid var(--amber);color:#ffd361}
  .banner.red{background:#330f0f;border:1px solid var(--air);color:#ff9d9d}
  #toasts{position:fixed;top:14px;right:14px;z-index:100;display:flex;
    flex-direction:column;gap:8px;max-width:340px}
  .toast{background:#330f0f;border:1px solid var(--air);color:#ff9d9d;border-radius:10px;
    padding:10px 14px;font-size:12px;font-weight:600;box-shadow:0 8px 24px rgba(0,0,0,.6)}
```

- [ ] **Step 2: Add the containers**

Directly after `</header>` (line ~190) insert:

```html
  <div id="banners"></div>
```

Directly before the closing `</div>` of `.wrap` (after the `#log` div, line ~241) insert:

```html
<div id="toasts"></div>
```

- [ ] **Step 3: Add the JS plumbing**

After the `relayLed` function (line ~333) insert:

```js
/* ---------- state banners (persistent conditions) + toasts (one-off) ----
   Banners reflect ONGOING conditions; they appear while the condition holds
   and clear themselves when it resolves — not dismissible by design. Toasts
   announce one-off action failures (~6 s); the log keeps the history. */
const banners = {};   // id -> {level: "red"|"amber", msg}
function setBanner(id, level, msg){
  if (banners[id] && banners[id].msg === msg) return;
  banners[id] = {level, msg}; renderBanners();
}
function clearBanner(id){
  if (banners[id]){ delete banners[id]; renderBanners(); }
}
function renderBanners(){
  $("#banners").innerHTML = Object.values(banners)
    .map(b=>`<div class="banner ${b.level}">⚠ ${escapeHtml(b.msg)}</div>`).join("");
}
function toast(msg){
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = "✕ " + msg;
  $("#toasts").appendChild(t);
  setTimeout(()=>t.remove(), 6000);
}
```

(`escapeHtml` is a hoisted function declaration further down the file — safe to reference.)

- [ ] **Step 4: Hook up toasts on every action failure**

In `relayCall` (lines 475-485): change the two failure lines to also toast —

```js
    if (d.error) { log("Relay /" + path + ": " + d.error, "err"); toast("Relay /" + path + ": " + d.error); return; }
```

and

```js
  }catch(e){ log("Relay /" + path + " failed (relay reachable?): " + e, "err"); toast("Relay /" + path + " failed — relay unreachable"); }
```

In `timerCall` (lines 620-628), same pattern:

```js
    if (d.error) { log("Timer: " + d.error, "err"); toast("Timer: " + d.error); return; }
```

```js
  }catch(e){ log("Timer action failed (relay reachable?): " + e, "err"); toast("Timer action failed — relay unreachable"); }
```

In `setupSet` (lines 685-695):

```js
    if (d.error){ log("HUD " + field + ": " + d.error, "err"); toast("HUD " + field + ": " + d.error); setupPoll(); return; }
```

```js
  }catch(e){ log("HUD " + field + " failed (relay reachable?): " + e, "err"); toast("HUD " + field + " failed — relay unreachable"); }
```

In `schedSave` (lines 756-779):

```js
    if (d.error){ log("Schedule row " + row + ": " + d.error, "err"); toast("Schedule row " + row + ": " + d.error); btn.textContent = "RETRY"; return; }
```

```js
  }catch(e){ log("Schedule save failed: " + e, "err"); toast("Schedule row " + row + " save failed"); btn.textContent = "RETRY"; }
```

In the `#povSave` handler (lines 793-810):

```js
    if (d.error){ log("POV URL: " + d.error, "err"); toast("POV URL: " + d.error); btn.textContent = "RETRY"; return; }
```

```js
  }catch(e){ log("POV save failed: " + e, "err"); toast("POV URL save failed"); btn.textContent = "RETRY"; }
```

- [ ] **Step 5: Raise/clear the state banners from the existing polls**

In `setupPoll` (lines 697-725), after the line `$("#clearRc").disabled = ro;` add:

```js
  if (d.push === "failed")
    setBanner("sync", "red", "SHEET SYNC FAILED — panel HUD/URL changes are not reaching the sheet");
  else clearBanner("sync");
```

In `timerRender` (lines 633-650), after the `const sync = ...` chain add:

```js
  if (d.sync.push === "failed")
    setBanner("timersync", "red", "TIMER SHEET SYNC FAILED — producer handover not safe");
  else clearBanner("timersync");
```

The relay-unreachable and cookie banners land in `relayPoll` in Task 7 (it is rewritten there anyway).

- [ ] **Step 6: Manual sanity + commit**

Open the file locally (`open src/director/director-panel.html` or any browser) — with no relay the page must render, show no banner crash, and log "relay not reachable" lines as before (banners need the poll rewrite of Task 7 to appear).

```bash
git add src/director/director-panel.html
git commit -m "feat(panel): state-banner + toast plumbing; toasts on action failures; sync banners"
```

---

### Task 7: Panel — feed health (strip pills + FEEDS health line) and relay/cookie banners

**Files:**
- Modify: `src/director/director-panel.html`

- [ ] **Step 1: CSS for the state pills**

After the `.st.air b{...}` rule (line ~52) insert:

```css
  .st.ok{border-color:var(--live);color:#8fe6b0}
  .st.ok b{color:#baf5d0}
  .st.warn{border-color:var(--amber);color:#ffd361}
  .st.warn b{color:#ffe49a}
```

And after the `.hint` rule (line ~123):

```css
  #feedHealth{min-height:0}
  #feedHealth .warnline{color:#ffd361}
```

- [ ] **Step 2: Give the FEEDS bus a body + health line**

Replace (line ~202)

```html
  <section class="bus"><div class="cap">Feeds</div><div class="keys" id="feedsBus"></div></section>
```

with

```html
  <section class="bus"><div class="cap">Feeds</div>
    <div class="body">
      <div class="keys" id="feedsBus"></div>
      <div class="hint" id="feedHealth"></div>
    </div>
  </section>
```

- [ ] **Step 3: Rewrite `relayPoll` with state rendering + banners**

Replace the whole `relayPoll` function (lines 568-582) with:

```js
/* state -> [pill suffix, pill css class]; durations/staleness come from the
   relay (state_age_s, cookies_health) — this file only renders. */
const FEED_STATE = {serving:["LIVE","ok"], connecting:["CONN","warn"],
                    idle:["IDLE",""], stopped:["STOPPED",""]};
function fmtDur(s){
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s/3600), mi = Math.floor(s%3600/60), sec = s%60;
  return (h ? h + ":" + String(mi).padStart(2,"0") : String(mi)) + ":" + String(sec).padStart(2,"0");
}
function healthLine(name, f){
  const what = f.stint ? "stint " + f.stint : "the POV stream";
  if (f.state === "serving")
    return `${name} · serving ${what} (since ${fmtDur(f.state_age_s)})`;
  if (f.state === "connecting"){
    let s = `${name} · connecting to ${what} for ${fmtDur(f.state_age_s)}`;
    if (f.state_age_s > 30){
      s += " — stream may not be live yet";
      if (f.last_error) s += " (" + escapeHtml(f.last_error) + ")";
      return `<span class="warnline">${s}</span>`;
    }
    return s;
  }
  return "";
}
function statePill(el, label, stint, n, state){
  const [txt, cls] = FEED_STATE[state] || ["", ""];
  el.className = "st" + (cls ? " " + cls : "");
  el.innerHTML = label + " <b>" + stint + "</b>" + (n ? "/" + n : "") + (txt ? " · " + txt : "");
}
async function relayPoll(){
  try{
    const r = await fetch("/status", {cache:"no-store"});
    const d = await r.json();
    relayLed(true); clearBanner("relay");
    const n = d.schedule_len;
    statePill($("#stA"), "A", "S" + d.feeds.A.stint, n, d.feeds.A.state);
    statePill($("#stB"), "B", "S" + d.feeds.B.stint, n, d.feeds.B.state);
    if (d.pov) statePill($("#stPov"), "POV",
        (FEED_STATE[d.pov.state] ? "" : d.pov.state.toUpperCase()) || "·", 0, d.pov.state);
    else $("#stPov").innerHTML = "POV <b>—</b>";
    const lines = [healthLine("A", d.feeds.A), healthLine("B", d.feeds.B)];
    if (d.pov && d.pov.state !== "stopped") lines.push(healthLine("POV", d.pov));
    $("#feedHealth").innerHTML = lines.filter(Boolean).join("<br>");
    const ck = d.cookies_health;
    if (ck && ck.stale)
      setBanner("cookies", "amber",
        `COOKIES ${Math.round(ck.age_h)} H OLD — next handover may fail · ` +
        `run 'iro cookies firefox' on the producer machine`);
    else clearBanner("cookies");
  }catch(e){
    relayLed(false);
    setBanner("relay", "red", "RELAY UNREACHABLE — feed & timer buttons will not work");
    for (const [sel, label] of [["#stA","A"],["#stB","B"],["#stPov","POV"]]){
      $(sel).className = "st"; $(sel).innerHTML = label + " <b>—</b>";
    }
    $("#feedHealth").innerHTML = "";
  }
}
```

Note the POV pill: for the known states the suffix (`LIVE`/`CONN`/`STOPPED`/`IDLE`) is the content — `POV <b>·</b> · CONN` would be noise, so the bold slot shows `·` unless the state is unknown. Check the rendering in Step 5 and simplify to taste — target look: `POV STOPPED`, `POV · CONN`, `POV · LIVE`.

- [ ] **Step 4: Drop the now-dead duplicate**

The old `relayPoll` body set `#stA/#stB/#stPov` directly — ensure no second definition remains (one `async function relayPoll` in the file).

- [ ] **Step 5: Manual verification against a live relay**

```bash
python3 src/iro.py relay run
# in a browser: http://127.0.0.1:8088/panel
```

Expected: pills show `A S1 · CONN` (amber) until a stream serves; FEEDS section shows the health line incl. duration; after >30 s connecting the amber warning + yt-dlp error appears; stopping the relay (Ctrl+C) flips the red RELAY UNREACHABLE banner within ~2 s. To see the cookie banner: `touch -t` an old timestamp onto `runtime/cookies.txt` and restart the relay.

- [ ] **Step 6: Commit**

```bash
git add src/director/director-panel.html
git commit -m "feat(panel): feed health pills + FEEDS health line; relay/cookie state banners"
```

---

### Task 8: Panel — guards (RELOAD confirm, NEXT debounce) + stint terminology

**Files:**
- Modify: `src/director/director-panel.html`

- [ ] **Step 1: Guard the feed actions**

Replace (lines 377-379)

```js
FEED_ACTIONS.forEach(([label, path, tag])=>{
  $("#feedsBus").appendChild(mkKey(label, tag, ()=>relayCall(path), false));
});
```

with

```js
FEED_ACTIONS.forEach(([label, path, tag])=>{
  const b = mkKey(label, tag, ()=>{
    // RELOAD tears the running pull -> brief dead air if that feed is on air.
    if (label.startsWith("RELOAD") &&
        !confirm(label + ": reconnect the feed — brief interruption if it is on air. Continue?"))
      return;
    if (label === "NEXT"){            // double-press guard: two presses = two handovers
      b.disabled = true;
      setTimeout(()=>{ b.disabled = false; }, 3000);
    }
    relayCall(path);
  }, false);
  $("#feedsBus").appendChild(b);
});
```

(`"POV RELOAD"` does not start with `"RELOAD"` — POV stays unguarded by design.)

- [ ] **Step 2: Rename the SET STINT button + prompt**

Replace (lines 380-386)

```js
$("#feedsBus").appendChild(mkKey("SET STINT…", "correct", ()=>{
  const v = prompt("Stint number now ON AIR (1-based):");
```

with

```js
$("#feedsBus").appendChild(mkKey("FEEDS → STINT…", "correction", ()=>{
  const v = prompt("Which stint is ON AIR right now? (e.g. 3)");
```

(the rest of that handler — digit check, confirm, `relayCall("set/stint/...")` — is unchanged).

- [ ] **Step 3: Rename the HUD dropdown label**

Replace (line 667-670)

```js
const SETUP_FIELDS = [
  ["stint","STINT (HUD LABEL)"], ["streamer","STREAMER"],
```

with

```js
const SETUP_FIELDS = [
  ["stint","STINT LABEL"], ["streamer","STREAMER"],
```

- [ ] **Step 4: Manual verification**

With the relay from Task 7 still running: RELOAD ALL asks for confirmation; Cancel does nothing; NEXT greys out for 3 s after a press; the FEEDS button reads `FEEDS → STINT…` with tag `correction`; the HUD dropdown label reads `STINT LABEL`.

- [ ] **Step 5: Commit**

```bash
git add src/director/director-panel.html
git commit -m "feat(panel): confirm on RELOAD, NEXT double-press guard, FEEDS → STINT… rename"
```

---

### Task 9: Preflight — Google Sheet section (+ port-message tweak, + `.env` for the oneshot)

**Files:**
- Modify: `src/scripts/preflight.py` (new fetch + classifier + `gather()` section; port message ~line 323)
- Modify: `src/iro.py` (`_oneshot_code`, ~line 1036)
- Test: `tests/test_preflight.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_preflight.py` loads the module via `importlib` at the top (existing pattern — reuse its `m`). Append above the `__main__` block:

```python
def t_classify_sheet_no_id_warns():
    r = m.classify_sheet(None)
    assert r.level == "WARN"
    assert "IRO_SHEET_ID" in r.detail


def t_classify_sheet_fetch_error_fails_with_sharing_hint():
    r = m.classify_sheet("SHEET_ID", "error", "URLError: timed out")
    assert r.level == "FAIL"
    assert "Anyone with the link" in r.detail


def t_classify_sheet_html_body_is_signin_page():
    r = m.classify_sheet("SHEET_ID", "ok", "<HTML><HEAD><TITLE>Sign in</TITLE>")
    assert r.level == "FAIL"
    assert "sign-in" in r.detail


def t_classify_sheet_csv_passes_with_row_count():
    r = m.classify_sheet("SHEET_ID", "ok", '"url","name"\n"https://x","Max"\n')
    assert r.level == "PASS"
    assert "2 row" in r.detail


def t_classify_sheet_empty_csv_fails():
    r = m.classify_sheet("SHEET_ID", "ok", "\n , \n")
    assert r.level == "FAIL"
    assert "empty" in r.detail
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_preflight.py`
Expected: `AttributeError: module ... has no attribute 'classify_sheet'`

- [ ] **Step 3: Implement fetch + classifier + section**

In `src/scripts/preflight.py`, extend the imports (top of file):

```python
import csv
import io
from urllib.parse import quote
from urllib.request import Request, urlopen
```

Add after the cookies block (after `cookies_status`, ~line 230):

```python
# --------------------------------------------------------------------------
# Google Sheet (the schedule/HUD source — a shared production resource)
# --------------------------------------------------------------------------
SHEET_TAB = "Schedule"   # keep in sync with the relay's DEFAULT_SHEET_TAB


def fetch_sheet_csv(sheet_id, tab=SHEET_TAB, timeout=10):
    """Network probe, kept apart from the pure classifier:
    ("ok", body_text) or ("error", message)."""
    url = (f"https://docs.google.com/spreadsheets/d/{sheet_id}"
           f"/gviz/tq?tqx=out:csv&sheet={quote(tab)}")
    try:
        req = Request(url, headers={"User-Agent": "iro-preflight/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return "ok", resp.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 — any network failure is the same FAIL
        return "error", f"{type(exc).__name__}: {exc}"


def classify_sheet(sheet_id, outcome=None, payload=""):
    """Pure classifier over the fetch outcome. An HTML body is Google's
    sign-in page — the classic 'sheet not shared' case."""
    if not sheet_id:
        return Result(WARN, "Google Sheet",
                      "IRO_SHEET_ID not set — fill it in .env (run via `iro preflight`)")
    if outcome == "error":
        return Result(FAIL, "Google Sheet",
                      f"not readable ({payload}) — check sharing: Share -> "
                      f"'Anyone with the link: Viewer' (or no network)")
    head = (payload or "").lstrip()[:200].lower()
    if head.startswith("<!doctype") or head.startswith("<html"):
        return Result(FAIL, "Google Sheet",
                      "not readable (got a sign-in page) — check sharing: "
                      "Share -> 'Anyone with the link: Viewer'")
    rows = [r for r in csv.reader(io.StringIO(payload)) if any(c.strip() for c in r)]
    if not rows:
        return Result(FAIL, "Google Sheet",
                      f"reachable but tab '{SHEET_TAB}' is empty — correct tab name?")
    return Result(PASS, "Google Sheet",
                  f"reachable ({len(rows)} row(s) in '{SHEET_TAB}')")
```

In `gather()` (line ~329), after the `cookies = [...]` line add:

```python
    sheet_id = os.environ.get("IRO_SHEET_ID")
    if sheet_id:
        outcome, payload = fetch_sheet_csv(sheet_id)
        sheet = [classify_sheet(sheet_id, outcome, payload)]
    else:
        sheet = [classify_sheet(None)]
```

and add the section to the returned list, after `("YouTube cookies", cookies),`:

```python
        ("Google Sheet", sheet),
```

- [ ] **Step 4: Tweak the port-in-use message**

Replace (line ~323)

```python
                                 "in use — relay already running or a port conflict"))
```

with

```python
                                 "in use — relay already running or a port conflict; "
                                 "`iro status` shows whether that is the relay"))
```

- [ ] **Step 5: Load `.env` for the preflight oneshot**

In `src/iro.py`, replace the whole `_oneshot_code` function (line ~1036) with:

```python
def _oneshot_code(command, rest):
    """Run a one-shot and return its exit code (the seam `iro init` uses to
    chain steps — oneshot() below keeps the exit-the-CLI behavior)."""
    if command == "preflight":
        # The sheet check reads IRO_SHEET_ID from the environment. Frozen mode
        # already loads .env (_load_env_frozen); in repo/package mode preflight
        # runs as a subprocess, which inherits os.environ — merge the .env file
        # in (real environment wins, same semantics as the scripts' load_dotenv).
        for key, val in _read_env_file().items():
            os.environ.setdefault(key, val)
    extra = _oneshot_extra(command, rest, IS_FROZEN, _runtime_dir())
    if command == "update" and "--current" not in rest:
        extra += ["--current", version()]
    return _run_script(ONESHOT_MAP[command], list(rest) + extra)
```

(`_read_env_file` is defined later in the module, line ~1081 — fine, it is
resolved at call time.)

- [ ] **Step 6: Run the tests**

Run: `python3 tests/test_preflight.py` → `ALL PASS`
Run: `python3 tests/test_iro.py && python3 tests/test_init.py` → `ALL PASS` (oneshot routing untouched).
Manual: `python3 src/iro.py preflight` on this machine shows the new "Google Sheet" section (PASS with the real `.env`, WARN without).

- [ ] **Step 7: Lint and commit**

```bash
python3 tools/lint.py
git add tests/test_preflight.py src/scripts/preflight.py src/iro.py
git commit -m "feat(preflight): Google Sheet readability check + clearer port-in-use hint"
```

---

### Task 10: `event status` Tailscale wording (jargon out)

**Files:**
- Modify: `src/scripts/event.py:183-186` (`classify_tailscale`)
- Test: `tests/test_event.py:144-147`

- [ ] **Step 1: Update the test to pin the new wording**

In `tests/test_event.py`, replace `t_classify_tailscale` (lines 144-147) with:

```python
def t_classify_tailscale():
    assert m.classify_tailscale("100.64.1.2").level == "PASS"
    assert "100.64.1.2" in m.classify_tailscale("100.64.1.2").detail
    miss = m.classify_tailscale(None)
    assert miss.level == "WARN"
    assert "Tailscale not connected" in miss.detail   # no 'tailnet' jargon
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 tests/test_event.py`
Expected: `AssertionError` on the new wording assertion.

- [ ] **Step 3: Fix the message**

In `src/scripts/event.py`, replace (lines 184-186)

```python
    return Result(WARN, "Tailscale",
                  "no tailnet IP — remote panel/tablet unreachable; sign in to Tailscale")
```

with

```python
    return Result(WARN, "Tailscale",
                  "Tailscale not connected — directors cannot reach the panel/tablet "
                  "remotely; sign in to Tailscale")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_event.py` → `ALL PASS`

- [ ] **Step 5: Lint and commit**

```bash
python3 tools/lint.py
git add src/scripts/event.py tests/test_event.py
git commit -m "fix(event): plain-language Tailscale warning (drop 'tailnet IP' jargon)"
```

---

### Task 11: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Whole suite + lint**

```bash
python3 tools/run-tests.py
python3 tools/lint.py
```

Expected: `ALL TEST FILES PASS` (the new `tests/test_health.py` is auto-discovered by the glob) and a clean lint.

- [ ] **Step 2: Build + self-verify**

```bash
python3 tools/build.py
```

Expected: build succeeds; its verify step (tokenization, blanked password, no shell scripts, preflight present) passes — the panel and relay ship from `src/`, nothing new to whitelist.

- [ ] **Step 3: End-to-end panel smoke (manual, ~3 min)**

```bash
python3 src/iro.py relay start
# browser: http://127.0.0.1:8088/panel
```

Checklist: pills show feed states; FEEDS health line updates; RELOAD asks, NEXT debounces; `FEEDS → STINT…` prompt reads correctly; stop the relay (`python3 src/iro.py relay stop`) → red banner within 2 s. Then restart and stop cleanly.

- [ ] **Step 4: Commit any stragglers, then done**

```bash
git status   # should be clean
```

---

## Spec-coverage map (self-review)

| Spec section | Tasks |
|---|---|
| §1 Feed health in `Feed` | 2, 3 |
| §2 Cookie health + `/status` contract | 1, 4, 5 (startup WARN) |
| §3 Panel banner/toasts/health/guards/rename | 6, 7, 8 |
| §4 Preflight Google Sheet section | 9 |
| §5 Message fixes (bind / tailnet / port-in-use) | 5, 10, 9 |
| Testing strategy | 1-4, 9, 10 (TDD), 11 (suite/build/manual) |
