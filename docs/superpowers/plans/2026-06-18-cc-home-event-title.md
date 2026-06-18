# Control Center Home — Editable Event Title Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the producer view and edit the live free-text event title (#207) directly from the Control Center Home view, whether the relay is running or stopped.

**Architecture:** Two new provider functions in `src/racecast.py` (`event_title_read_data`, `event_title_write_data`) bridge the Control Center (port 8089) to the relay's event-title state — reading the relay's `/status` when it's up and `runtime/<profile>/event.json` (or the profile `EVENT_TITLE` default) when it's down, and writing via `POST /event/title` when up or a direct `event.json` write when down. Two routes in `src/ui/ui_server.py` (`GET`/`POST /api/event-title`) expose them; a new Home-view section in `src/ui/control-center.html` provides display + inline edit, mirroring the Director Panel.

**Tech Stack:** Pure Python stdlib (no framework), vanilla HTML/JS, stdlib `unittest`-free runnable-script tests (each `tests/test_*.py` is a script).

**Spec:** `docs/superpowers/specs/2026-06-18-control-center-home-event-title-design.md`

---

## File Structure

- **`src/racecast.py`** (modify) — add `_relay_post_json` (POST sibling of `_relay_fetch_json`), `_event_title_sanitizer` (cached load of the relay's single sanitize rule), `event_title_read_data`, `event_title_write_data`; register both in the `run_ui` `ctx` dict.
- **`src/ui/ui_server.py`** (modify) — add `GET /api/event-title` and `POST /api/event-title` routes.
- **`src/ui/control-center.html`** (modify) — add the Home "Event title" section + its load/edit/save JS; wire its refresh into `showView('home')` and the status poll.
- **`tests/test_racecast.py`** (modify) — unit-test the two providers (relay-up/down read precedence, relay-up/down write paths, real-sanitizer wiring, never-raises).
- **`tests/test_ui_server.py`** (modify) — route tests (GET returns payload, POST calls writer + echoes, validation→400) and the two new `_ctx` default keys.
- **`src/docs/wiki/images/cc-home.png`** (replace) — refreshed Home screenshot from a local dev build (CLAUDE.md hard rule).

---

## Task 1: Backend providers in `src/racecast.py`

**Files:**
- Modify: `src/racecast.py` (add helpers near `_relay_fetch_json` ~line 1226 and the provider block ~line 2593 next to `relay_live_data`)
- Test: `tests/test_racecast.py`

### Step 1.1 — Write the failing tests

- [ ] Add these tests to `tests/test_racecast.py` (the file imports `racecast` as `m`; it already uses `importlib`, `os`). Add `import json, os, tempfile` at the top **only if not already present** (check the existing imports first — `import importlib.util, os` is there; add `json` and `tempfile`).

```python
# ---- event title providers (Control Center Home; #207 follow-up) ----

def t_event_title_read_from_relay_when_alive():
    d = m.event_title_read_data(alive=lambda: True,
                                fetch=lambda u: {"event_title": "Round 4"})
    assert d == {"ok": True, "title": "Round 4",
                 "source": "relay", "relay_alive": True}, d


def t_event_title_read_relay_unreachable_falls_back_to_file():
    # alive() True but the GET blows up -> read the persisted file instead.
    with tempfile.TemporaryDirectory() as dd:
        p = os.path.join(dd, "event.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"title": "From File"}, fh)
        def boom(_u):
            raise OSError("relay starting up")
        d = m.event_title_read_data(alive=lambda: True, fetch=boom,
                                    path=p, default="Default Cup")
        assert d["title"] == "From File" and d["source"] == "file", d


def t_event_title_read_file_then_default_when_relay_down():
    with tempfile.TemporaryDirectory() as dd:
        p = os.path.join(dd, "event.json")
        # no file -> profile default
        d = m.event_title_read_data(alive=lambda: False, path=p, default="Default Cup")
        assert d == {"ok": True, "title": "Default Cup",
                     "source": "default", "relay_alive": False}, d
        # file present -> file wins
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"title": "From File"}, fh)
        d = m.event_title_read_data(alive=lambda: False, path=p, default="Default Cup")
        assert d["title"] == "From File" and d["source"] == "file", d


def t_event_title_write_posts_to_relay_when_alive():
    sent = {}
    def post(url, payload):
        sent["url"] = url; sent["payload"] = payload
        return {"ok": True, "title": payload["title"]}
    d = m.event_title_write_data("  Round 5  ", alive=lambda: True, post=post,
                                 sanitize=lambda s: s.strip())
    assert d == {"ok": True, "title": "Round 5", "applied": "relay"}, d
    assert sent["url"].endswith("/event/title"), sent
    assert sent["payload"] == {"title": "Round 5"}, sent


def t_event_title_write_writes_file_when_relay_down():
    with tempfile.TemporaryDirectory() as dd:
        p = os.path.join(dd, "sub", "event.json")     # dir created on demand
        d = m.event_title_write_data("Round 6", alive=lambda: False, path=p,
                                     sanitize=lambda s: s.strip())
        assert d == {"ok": True, "title": "Round 6", "applied": "file"}, d
        with open(p, encoding="utf-8") as fh:
            assert json.load(fh) == {"title": "Round 6"}


def t_event_title_write_applies_the_real_relay_sanitizer():
    # No sanitize seam -> exercises _event_title_sanitizer loading the relay rule.
    with tempfile.TemporaryDirectory() as dd:
        p = os.path.join(dd, "event.json")
        d = m.event_title_write_data("Round\n7\tCup", alive=lambda: False, path=p)
        assert d["ok"] and d["title"] == "Round7Cup", d   # control chars stripped


def t_event_title_write_relay_error_returns_not_ok():
    def boom(_u, _p):
        raise OSError("connection refused")
    d = m.event_title_write_data("x", alive=lambda: True, post=boom,
                                 sanitize=lambda s: s)
    assert d["ok"] is False and "connection refused" in d["error"], d
```

### Step 1.2 — Run the tests to verify they fail

- [ ] Run: `python3 tests/test_racecast.py`
- [ ] Expected: FAIL with `AttributeError: module 'racecast' has no attribute 'event_title_read_data'` (or `event_title_write_data`).

### Step 1.3 — Add the POST helper and cached sanitizer

- [ ] In `src/racecast.py`, directly **after** `_relay_fetch_json` (ends ~line 1230), add:

```python
def _relay_post_json(url, payload, timeout=3):
    """POST a JSON body to a relay control-server endpoint and parse its JSON
    reply (the write sibling of _relay_fetch_json)."""
    import urllib.request
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


_EVENT_TITLE_SANITIZER = None


def _event_title_sanitizer():
    """The relay's single sanitize_event_title rule (#207), loaded once and cached.
    One source of truth for EVENT_TITLE_MAX/normalization — the Control Center must
    not duplicate it (CLAUDE.md: keep the rule un-forked)."""
    global _EVENT_TITLE_SANITIZER
    if _EVENT_TITLE_SANITIZER is None:
        _EVENT_TITLE_SANITIZER = \
            _load_relay_module("relay/racecast-feeds.py").sanitize_event_title
    return _EVENT_TITLE_SANITIZER
```

### Step 1.4 — Add the read provider

- [ ] In `src/racecast.py`, directly **after** `relay_live_data` (ends ~line 2627), add:

```python
def event_title_read_data(alive=None, fetch=None, path=None, default=None):
    """Current free-text event title (#207) for the Control Center Home. Relay up
    -> the authoritative live value from /status. Relay down (or unreachable) ->
    runtime/<profile>/event.json, falling back to the active profile's EVENT_TITLE
    default. Never raises. alive/fetch/path/default are test seams."""
    alive = alive or _relay_is_alive
    fetch = fetch or _relay_fetch_json
    path = path or _event_title_path()
    is_alive = bool(alive())
    if is_alive:
        try:
            st = fetch(f"http://127.0.0.1:{RELAY_PORT}/status")
            if isinstance(st, dict) and isinstance(st.get("event_title"), str):
                return {"ok": True, "title": st["event_title"],
                        "source": "relay", "relay_alive": True}
        except Exception:  # noqa: BLE001 — relay reachable check is best-effort
            pass           # fall through to the persisted file / default
    try:
        with open(path, encoding="utf-8") as fh:
            saved = json.load(fh)
        if isinstance(saved, dict) and isinstance(saved.get("title"), str):
            return {"ok": True, "title": saved["title"],
                    "source": "file", "relay_alive": is_alive}
    except (OSError, ValueError):
        pass               # no/corrupt file -> the profile default
    dflt = _profile_event_default() if default is None else default
    return {"ok": True, "title": dflt or "", "source": "default",
            "relay_alive": is_alive}


def _profile_event_default():
    """The active profile's EVENT_TITLE default ("" when unset/unresolvable).
    Best-effort — the Home field degrades to empty, never errors."""
    try:
        root = _env_base(IS_FROZEN, _real_executable(), HERE)
        rc = pcfg.resolve_config(root, runtime_root=_runtime_base_dir())
        return rc.event_title or ""
    except Exception:  # noqa: BLE001 — best effort
        return ""
```

### Step 1.5 — Add the write provider

- [ ] Directly **after** `event_title_read_data`/`_profile_event_default`, add:

```python
def event_title_write_data(value, alive=None, post=None, path=None, sanitize=None):
    """Set the live event title (#207) from the Control Center Home. Relay up ->
    POST /event/title (updates the live store AND persists event.json in one place).
    Relay down -> write event.json directly (the next `event start` adopts it via
    EventTitleStore precedence; mirrors takeover()). Sanitized with the relay's one
    rule. Returns {"ok", "title", "applied"} or {"ok": False, "error"}; never raises.
    alive/post/path/sanitize are test seams."""
    alive = alive or _relay_is_alive
    path = path or _event_title_path()
    sanitize = sanitize or _event_title_sanitizer()
    title = sanitize(value)
    if alive():
        post = post or _relay_post_json
        try:
            res = post(f"http://127.0.0.1:{RELAY_PORT}/event/title", {"title": title})
            stored = res.get("title", title) if isinstance(res, dict) else title
            return {"ok": True, "title": stored, "applied": "relay"}
        except Exception as exc:  # noqa: BLE001 — surface as a clean error to the UI
            return {"ok": False, "error": f"relay rejected the title: {exc}"}
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"title": title}, fh)
        return {"ok": True, "title": title, "applied": "file"}
    except OSError as exc:
        return {"ok": False, "error": f"could not write event.json: {exc}"}
```

### Step 1.6 — Run the tests to verify they pass

- [ ] Run: `python3 tests/test_racecast.py`
- [ ] Expected: prints `ok t_event_title_*` for all seven new tests and `ALL PASS`.

### Step 1.7 — Commit

```bash
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(ui): event-title read/write providers bridging Control Center to the relay (#207)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Wire providers into `ctx` + add UI-server routes

**Files:**
- Modify: `src/racecast.py` (`run_ui` `ctx` dict ~line 4381)
- Modify: `src/ui/ui_server.py` (`do_GET` ~after line 343; `do_POST` ~after line 574)
- Test: `tests/test_ui_server.py`

### Step 2.1 — Write the failing route tests

- [ ] In `tests/test_ui_server.py`, add the two keys to the `_ctx()` default dict (so the shared stub is complete) — insert alongside the other lambdas, e.g. right after the `"speedtest"` entry at the end of the dict (before the closing `}`):

```python
            "event_title_read": lambda: {"ok": True, "title": "",
                                         "source": "default", "relay_alive": False},
            "event_title_write": lambda value: {"ok": True, "title": value or "",
                                                "applied": "file"},
```

- [ ] Then add these tests (the file already has `_get`, `_post_json`, `_serve`, `_ctx`):

```python
def t_event_title_get_route():
    ctx = _ctx()
    ctx["event_title_read"] = lambda: {"ok": True, "title": "Round 4",
                                       "source": "relay", "relay_alive": True}
    httpd, port = _serve(ctx)
    try:
        code, body = _get(port, "/api/event-title")
        d = json.loads(body)
        assert code == 200 and d["title"] == "Round 4" and d["source"] == "relay"
    finally:
        httpd.shutdown()


def t_event_title_get_route_error_is_500():
    ctx = _ctx()
    def boom():
        raise RuntimeError("relay gone")
    ctx["event_title_read"] = boom
    httpd, port = _serve(ctx)
    try:
        code, body = _get(port, "/api/event-title")
        assert code == 500 and "relay gone" in json.loads(body)["error"]
    finally:
        httpd.shutdown()


def t_event_title_post_route_saves():
    seen = []
    ctx = _ctx()
    ctx["event_title_write"] = lambda value: seen.append(value) or {
        "ok": True, "title": (value or "").strip(), "applied": "file"}
    httpd, port = _serve(ctx)
    try:
        code, body = _post_json(port, "/api/event-title", {"title": " Round 5 "})
        d = json.loads(body)
        assert code == 200 and d["ok"] and d["title"] == "Round 5"
        assert seen == [" Round 5 "]
    finally:
        httpd.shutdown()


def t_event_title_post_validation_error_is_400():
    ctx = _ctx()
    ctx["event_title_write"] = lambda value: {"ok": False, "error": "relay rejected"}
    httpd, port = _serve(ctx)
    try:
        code, body = _post_json(port, "/api/event-title", {"title": "x"})
        assert code == 400 and "relay rejected" in json.loads(body)["error"]
    finally:
        httpd.shutdown()
```

### Step 2.2 — Run the tests to verify they fail

- [ ] Run: `python3 tests/test_ui_server.py`
- [ ] Expected: the GET test fails (route returns 404 → `_get` returns `(404, …)` so `code == 200` assertion fails); the POST tests fail similarly.

### Step 2.3 — Register the providers in `ctx`

- [ ] In `src/racecast.py`, inside the `run_ui` `ctx = { … }` dict (after `"relay_live": relay_live_data,` at ~line 4386), add:

```python
        "event_title_read": event_title_read_data,
        "event_title_write": event_title_write_data,
```

### Step 2.4 — Add the GET route

- [ ] In `src/ui/ui_server.py` `do_GET`, directly **after** the `/api/relay-live` block (ends ~line 343), add:

```python
            if path == "/api/event-title":
                try:
                    return self._json(ctx["event_title_read"]())
                except Exception as exc:
                    return self._json({"ok": False,
                                       "error": f"event title read failed: {exc}"},
                                      code=500)
```

### Step 2.5 — Add the POST route

- [ ] In `src/ui/ui_server.py` `do_POST`, directly **after** the `/api/env` block (ends ~line 574), add:

```python
            if path == "/api/event-title":
                body = self._body_json()
                if body is None:
                    return self._json({"ok": False, "error": "malformed JSON body"},
                                      code=400)
                try:
                    result = ctx["event_title_write"](body.get("title"))
                except Exception as exc:
                    return self._json({"ok": False,
                                       "error": f"could not set event title: {exc}"},
                                      code=500)
                return self._json(result, code=200 if result.get("ok") else 400)
```

### Step 2.6 — Run the tests to verify they pass

- [ ] Run: `python3 tests/test_ui_server.py`
- [ ] Expected: all event-title route tests print `ok` and the file ends `ALL PASS`.

### Step 2.7 — Commit

```bash
git add src/racecast.py src/ui/ui_server.py tests/test_ui_server.py
git commit -m "feat(ui): GET/POST /api/event-title routes wired to the event-title providers (#207)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Home view — display + inline editor

**Files:**
- Modify: `src/ui/control-center.html` (Home markup ~line 514; JS near `fetchRelayLive` ~line 1121, `showView` ~line 1015, status poll ~line 1406)

This task is UI wiring with no unit test (the route layer is covered in Task 2; the e2e harness exercises the live server separately). Verify by driving a local dev build in Task 4.

### Step 3.1 — Add the Home "Event title" section

- [ ] In `src/ui/control-center.html`, insert a new section immediately **after** the Home `viewhead` closing `</div>` (the `</div>` at the end of the takeover button block, ~line 514) and **before** the first services `<section>` (~line 515):

```html
        <section id="home-event">
          <div class="row"><span class="name">Event title</span>
            <span class="dim grow" id="evt-title-text">—</span>
            <input id="evt-title-input" maxlength="120" hidden
                   placeholder="Event title (e.g. GTEC - 2026 - Round 4 - Nürburgring 24h)"
                   aria-label="Event title">
            <button class="linkbtn" id="evt-title-edit"
                    title="Set the event title shown on the HUD, Cockpit and Discord">Edit</button>
            <span class="err" id="evt-title-err" hidden></span></div>
        </section>
```

### Step 3.2 — Add the event-title JS (load / edit / save)

- [ ] In `src/ui/control-center.html`, directly **after** the `fetchRelayLive` function (ends ~line 1150, just before the `// Status payload shape` comment at line 1252 region — place it right after `fetchRelayLive`'s closing brace), add:

```javascript
// ----- event title (Home; #207 follow-up) -----
let evtTitle = '', evtEditing = false;
function renderEventTitle(title) {
  evtTitle = (title || '').trim();
  if (evtEditing) return;                  // don't yank an editor the user has open
  const el = $('evt-title-text');
  el.textContent = evtTitle || 'not set';
  el.classList.toggle('dim', !evtTitle);
}
async function fetchEventTitle() {
  let d;
  try { d = await (await fetch('/api/event-title', {cache: 'no-store'})).json(); }
  catch (e) { return; }                    // server gone — keep last state
  if (d && d.ok) renderEventTitle(d.title);
}
function startEditEventTitle() {
  evtEditing = true;
  $('evt-title-err').hidden = true;
  const inp = $('evt-title-input');
  inp.value = evtTitle;
  $('evt-title-text').hidden = true; $('evt-title-edit').hidden = true;
  inp.hidden = false; inp.focus(); inp.select();
}
function stopEditEventTitle() {            // restore display (Esc / blur / post-save)
  evtEditing = false;
  $('evt-title-input').hidden = true;
  $('evt-title-text').hidden = false; $('evt-title-edit').hidden = false;
  renderEventTitle(evtTitle);
}
async function saveEventTitle(value) {
  let d;
  try {
    d = await (await fetch('/api/event-title', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title: value})})).json();
  } catch (e) {
    $('evt-title-err').textContent = 'Control Center not reachable.';
    $('evt-title-err').hidden = false; return;
  }
  if (!d.ok) {
    $('evt-title-err').textContent = d.error || 'could not set the event title';
    $('evt-title-err').hidden = false; return;
  }
  renderEventTitle(d.title);               // textContent path -> XSS-safe
}
$('evt-title-edit').addEventListener('click', startEditEventTitle);
$('evt-title-input').addEventListener('keydown', async (e) => {
  if (e.key === 'Enter') { e.preventDefault(); await saveEventTitle(e.target.value); stopEditEventTitle(); }
  else if (e.key === 'Escape') { stopEditEventTitle(); }
});
$('evt-title-input').addEventListener('blur', () => { if (evtEditing) stopEditEventTitle(); });
```

### Step 3.3 — Refresh on entering Home and on the status poll

- [ ] In `showView` (~line 1015), inside the `if (name === 'home')` area, add a call so the title loads on entry. Change the existing block:

```javascript
  // entering Home: refresh the takeover device dropdown from the tailnet
  if (name === 'home') loadTakeoverPeers();
```

to:

```javascript
  // entering Home: refresh the takeover device dropdown from the tailnet
  if (name === 'home') loadTakeoverPeers();
  // entering Home: load the current event title (works relay up or down)
  if (name === 'home') fetchEventTitle();
```

- [ ] In the status poll (`onStatus`, ~line 1406), directly **after** the `if (currentView === 'home' && relayUp && s.relay.http_ok) fetchRelayLive();` line, add (note: NO relay-up guard — the title is readable from event.json/default when the relay is down):

```javascript
  if (currentView === 'home') fetchEventTitle();
```

### Step 3.4 — Sanity-check the markup/JS load

- [ ] Run a syntax sanity check on the file (the page must still parse). Open it in a quick headless check:

Run: `python3 -c "import re,sys; html=open('src/ui/control-center.html').read(); assert html.count('id=\"evt-title-text\"')==1 and html.count('function fetchEventTitle')==1; print('markup+js present')"`
Expected: `markup+js present`

### Step 3.5 — Commit

```bash
git add src/ui/control-center.html
git commit -m "feat(ui): editable event-title field on the Control Center Home view (#207)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Manual verification + refresh the wiki screenshot

**Files:**
- Replace: `src/docs/wiki/images/cc-home.png`

CLAUDE.md hard rule: a visible Control Center change requires regenerating the matching `cc-*.png` **from a local dev build** (no `VERSION` stamped, so the badge shows "dev build") in the same change.

### Step 4.1 — Run the Control Center from source

- [ ] Start a local dev build (no VERSION file → "dev build" badge):

Run: `python3 src/racecast.py ui --no-browser` (leave it running in a background shell; note the port, default 8089)

### Step 4.2 — Exercise the new field end-to-end (relay down)

- [ ] With the relay stopped, open `http://127.0.0.1:8089`, click **Edit** on the Event title row, type `GTEC - 2026 - Round 4 - Nürburgring 24h`, press Enter.
- [ ] Confirm the row now shows that title.
- [ ] Confirm it persisted to the active profile's `event.json`:

Run: `python3 -c "import json,glob; print([open(p).read() for p in glob.glob('runtime/*/event.json')])"`
Expected: the JSON contains `"title": "GTEC - 2026 - Round 4 - Nürburgring 24h"`.

### Step 4.3 — Capture the Home screenshot

- [ ] Drive the running dev build with the Playwright MCP, navigate to Home, and take an **element** screenshot framed like the existing `cc-home.png` (the Home view container), saving over `src/docs/wiki/images/cc-home.png`. Set the event title field to a representative value first (e.g. the round label above) so the new row is shown populated.
- [ ] Verify the new image shows the Event title row and the "dev build" version badge.

### Step 4.4 — Stop the dev build

- [ ] Stop the background `racecast ui` process.

### Step 4.5 — Commit

```bash
git add src/docs/wiki/images/cc-home.png
git commit -m "docs(wiki): refresh cc-home.png with the event-title field (#207)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Full suite, lint, and build verify

**Files:** none (verification only)

### Step 5.1 — Run the full test suite

- [ ] Run: `python3 tools/run-tests.py`
- [ ] Expected: every test file reports `ALL PASS` and the runner exits 0.

### Step 5.2 — Lint

- [ ] Run: `python3 tools/lint.py`
- [ ] Expected: no findings (clean exit). If the new `except Exception` lines trip a rule, confirm the `# noqa: BLE001` markers match the surrounding style (they mirror `profile_logo`/`relay_live_data`).

### Step 5.3 — Build self-verify

- [ ] Run: `python3 tools/build.py`
- [ ] Expected: build completes and the verify step passes (tokenization, blanked password, no secrets, no shell scripts).

### Step 5.4 — Final commit (only if build produced tracked changes; normally none)

```bash
git status   # expect clean working tree (dist/ is gitignored)
```

---

## Self-Review notes (already reconciled)

- **Spec coverage:** read-precedence (relay>file>default) → Task 1.4 + tests 1.1; two write paths → Task 1.5 + tests; single sanitize rule (no fork) → `_event_title_sanitizer` + test `t_event_title_write_applies_the_real_relay_sanitizer`; routes + CSRF gate (inherited from `do_POST`'s `_allowed`/`request_csrf_ok`) → Task 2; Home display + inline edit mirroring the Panel → Task 3; live-title-not-profile-default separation → Home reads/writes `event.json`/relay only, never `profile.env`; wiki screenshot → Task 4.
- **Type consistency:** provider return shapes `{"ok","title","source","relay_alive"}` (read) and `{"ok","title","applied"}` / `{"ok":False,"error"}` (write) are used identically in racecast tests, the `_ctx` stubs, and the ui_server route tests. Element ids `evt-title-text` / `evt-title-input` / `evt-title-edit` / `evt-title-err` are consistent across markup (3.1) and JS (3.2/3.3).
- **No placeholders:** every code step contains the full code; every run step has an exact command + expected output.
