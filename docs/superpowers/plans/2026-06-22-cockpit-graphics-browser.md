# Cockpit Graphics Browser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let commentators browse the league's broadcast graphics from the Commentator Cockpit and open a selected graphic in a new browser tab.

**Architecture:** Two new read-only, token-gated GET endpoints under the existing `/cockpit/*` namespace — `/cockpit/graphics` (JSON list of the profile's `*.png` graphics) and `/cockpit/graphics/<file>` (serves one PNG, path-traversal-safe). Both are added to the `console_policy` matrix as `ANY` (any authenticated subject) so they are reachable over Funnel via the `/console/cockpit/*` mount. The cockpit page gains a "Graphics" card that lists the names and opens each via a `RC_API(...)`-resolved `<a target="_blank">`.

**Tech Stack:** Pure Python 3 stdlib (relay `BaseHTTPRequestHandler`); plain HTML/CSS/JS in `src/cockpit/cockpit.html`; stdlib-only test scripts (no pytest).

## Global Constraints

- **Edit only under `src/`** (plus the matching `tests/`). `dist/`/`runtime/` are generated — never hand-edit.
- **English only** in all code, comments, and docs.
- **No secrets / machine paths** in code or tests; tests must run on any machine and in CI (incl. `windows-latest`).
- **Outbound HTTP** is irrelevant here (all new routes are inbound), so the `http_util` rule does not apply.
- **The relay stays dependency-light** — the new helpers are pure stdlib (`os`), no new imports beyond what `racecast-feeds.py` already has (`os`, `urllib.parse.unquote`).
- **Path safety mirrors the existing `resolve_asset` pattern**: reject path separators + `..`, then `realpath` containment inside the graphics dir; content-type is the constant `"image/png"`, never request-derived.
- **`graphics_dir` is already a `make_handler` parameter** (`src/relay/racecast-feeds.py:3095`) and already wired at relay startup (`src/relay/racecast-feeds.py:4511` → `:4652`). Do NOT add the parameter again — just consume it.
- **Changed a UI surface? Refresh its wiki screenshot in the SAME change.** The cockpit (Crew Console) is a documented surface — see Task 5.
- After any change run `python3 tools/lint.py` and `python3 tools/run-tests.py`; after a shipping change run `python3 tools/build.py`.

---

### Task 1: Pure graphics helpers (`list_graphics`, `resolve_graphic`)

Two module-level pure functions next to `resolve_asset`, fully unit-tested with no server. They are the testable core; the HTTP layer (Task 2) stays a thin wrapper.

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add two functions after `resolve_asset`, which ends at line 387)
- Test: `tests/test_cockpit.py` (add pure-helper tests; the module is imported there as `m`)

**Interfaces:**
- Consumes: nothing (pure `os` calls).
- Produces:
  - `list_graphics(graphics_dir) -> list[dict]` — sorted `[{"name": <label>, "file": <label>.png}, ...]` of the `*.png` files in `graphics_dir`; `[]` when the dir is unset/missing/unreadable.
  - `resolve_graphic(graphics_dir, name) -> tuple[str, str] | None` — `(absolute_path, "image/png")` for a safe, existing `*.png` filename inside `graphics_dir`, else `None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cockpit.py` (near the other module-level/helper tests, e.g. after `t_race_control_schedule_empty` around line 223). `m` is already the imported `racecast-feeds` module; `tempfile` and `os` are already imported at the top of the file (confirm and add if missing).

```python
def _seed_graphics(d):
    """Write a few dummy PNGs (+ one non-PNG) into dir d; return it."""
    for fn in ("Standings.png", "Schedule.png", "Race Results.png", "notes.txt"):
        with open(os.path.join(d, fn), "wb") as fh:
            fh.write(b"\x89PNG\r\n" + fn.encode())
    return d


def t_list_graphics_sorted_pngs_only():
    with tempfile.TemporaryDirectory() as d:
        _seed_graphics(d)
        got = m.list_graphics(d)
        assert got == [
            {"name": "Race Results", "file": "Race Results.png"},
            {"name": "Schedule", "file": "Schedule.png"},
            {"name": "Standings", "file": "Standings.png"},
        ], got


def t_list_graphics_missing_or_unset_dir_is_empty():
    assert m.list_graphics(None) == []
    assert m.list_graphics("/no/such/dir/xyz") == []


def t_resolve_graphic_happy_path():
    with tempfile.TemporaryDirectory() as d:
        _seed_graphics(d)
        hit = m.resolve_graphic(d, "Race Results.png")
        assert hit is not None
        path, ctype = hit
        assert ctype == "image/png"
        assert os.path.basename(path) == "Race Results.png"
        assert os.path.realpath(path).startswith(os.path.realpath(d) + os.sep)


def t_resolve_graphic_rejects_traversal_and_non_png():
    with tempfile.TemporaryDirectory() as d:
        _seed_graphics(d)
        for bad in ("../secret.png", "a/b.png", "a\\b.png", "..", ".",
                    "notes.txt", "Missing.png", "", "/etc/passwd"):
            assert m.resolve_graphic(d, bad) is None, bad
        assert m.resolve_graphic(None, "Standings.png") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_cockpit as t; t.t_list_graphics_sorted_pngs_only()"`
Expected: FAIL with `AttributeError: module ... has no attribute 'list_graphics'`.

- [ ] **Step 3: Implement the helpers**

In `src/relay/racecast-feeds.py`, immediately after `resolve_asset` (after line 387, before the overlay section comment at line 390), add:

```python
def list_graphics(graphics_dir):
    """Sorted list of the broadcast still-graphics (*.png) in graphics_dir as
    [{"name": <Sheet label>, "file": <label>.png}, ...] for the cockpit browser.
    Tolerant of an unset/missing/unreadable dir (returns []). Names are arbitrary
    Sheet labels (mixed case, spaces) so there is no key regex here — listing is
    a plain directory read; the SECURITY check lives in resolve_graphic."""
    if not graphics_dir:
        return []
    try:
        names = os.listdir(graphics_dir)
    except OSError:
        return []
    out = []
    for fn in names:
        if fn.lower().endswith(".png") and os.path.isfile(os.path.join(graphics_dir, fn)):
            out.append({"name": fn[:-4], "file": fn})
    out.sort(key=lambda e: e["name"].lower())
    return out


def resolve_graphic(graphics_dir, name):
    """Resolve a requested cockpit-graphics filename to (path, "image/png"), or
    None when unsafe or absent. Graphics filenames are arbitrary Sheet labels
    (uppercase/spaces allowed) so ASSET_KEY_RE does NOT apply; safety = reject any
    path separator / traversal component, then realpath containment inside
    graphics_dir (same guarantee as resolve_asset). Content-type is the constant
    "image/png", never request-derived."""
    if not graphics_dir or not name or name in (".", ".."):
        return None
    if "/" in name or "\\" in name:          # no directory components
        return None
    if not name.lower().endswith(".png"):
        return None
    base = os.path.realpath(graphics_dir)
    path = os.path.realpath(os.path.join(base, name))
    if not path.startswith(base + os.sep):   # belt-and-braces containment
        return None
    return (path, "image/png") if os.path.isfile(path) else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_cockpit.py`
Expected: all assertions pass, exit 0 (the file's `__main__` runner executes every `t_*`).

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/relay/racecast-feeds.py tests/test_cockpit.py
git commit -m "feat(cockpit): pure helpers to list/resolve broadcast graphics"
```

---

### Task 2: Relay endpoints `/cockpit/graphics` and `/cockpit/graphics/<file>`

Wire the helpers into the cockpit GET routing block. Both call `self._console_auth()` first (sends 401/429 and returns `None` on failure — the caller must `return None`). The graphics dir is the already-wired `graphics_dir` closure variable.

**Files:**
- Modify: `src/relay/racecast-feeds.py` — add two routes in `do_GET`'s `/cockpit/*` block (the block runs lines 3873–3951; insert before the final `return self._send({"error": "unknown", ...}, 404)` at line 3951)
- Modify: `tests/test_cockpit.py` — extend `_cockpit_client` (lines 226–288) with a `graphics_dir` param + endpoint tests

**Interfaces:**
- Consumes: `list_graphics`, `resolve_graphic` (Task 1); `self._console_auth()`, `self._send`, `self._send_file` (existing handler methods); `graphics_dir` (existing `make_handler` param/closure); `unquote` (already imported at line 71).
- Produces: HTTP routes `GET /cockpit/graphics` → `{"graphics": [...]}`; `GET /cockpit/graphics/<file>` → the PNG bytes with `Content-Type: image/png`, or 404 JSON.

- [ ] **Step 1: Write the failing endpoint tests**

First, update `_cockpit_client` in `tests/test_cockpit.py` to accept and forward a graphics dir. Change the signature (line 226-228) and the `make_handler` call (line 261-263):

```python
def _cockpit_client(secret="sek", rows=None, live_idx=0,
                    versions_path=None, chat_store=None, timer_store=None,
                    page_path=None, graphics_dir=None):
```

```python
    handler = m.make_handler(_Relay(), chat_store=chat_store, timer_store=timer_store,
                             cockpit_page_path=page_path, console_secret=secret,
                             console_versions_path=versions_path,
                             graphics_dir=graphics_dir)
```

Then add these tests (anywhere among the other `t_*` endpoint tests):

```python
def t_graphics_list_requires_auth():
    srv, get, _post = _cockpit_client()
    try:
        assert get("/cockpit/graphics")[0] == 401
    finally:
        srv.shutdown()


def t_graphics_list_authed_sorted():
    with tempfile.TemporaryDirectory() as d:
        _seed_graphics(d)
        srv, get, _post = _cockpit_client(graphics_dir=d)
        try:
            tok = ca.mint_token("sek", "alpha-racing")
            code, _h, body = get("/cockpit/graphics?t=" + tok)
            assert code == 200, code
            names = [e["name"] for e in json.loads(body)["graphics"]]
            assert names == ["Race Results", "Schedule", "Standings"], names
        finally:
            srv.shutdown()


def t_graphics_list_empty_without_dir():
    srv, get, _post = _cockpit_client()          # graphics_dir=None
    try:
        tok = ca.mint_token("sek", "alpha-racing")
        code, _h, body = get("/cockpit/graphics?t=" + tok)
        assert code == 200 and json.loads(body)["graphics"] == [], body
    finally:
        srv.shutdown()


def t_graphic_file_served_with_png_ctype():
    with tempfile.TemporaryDirectory() as d:
        _seed_graphics(d)
        srv, get, _post = _cockpit_client(graphics_dir=d)
        try:
            tok = ca.mint_token("sek", "alpha-racing")
            # %20 in the path exercises the unquote() of the filename segment.
            code, headers, body = get("/cockpit/graphics/Race%20Results.png?t=" + tok)
            assert code == 200, code
            assert headers["Content-Type"] == "image/png", headers["Content-Type"]
            with open(os.path.join(d, "Race Results.png"), "rb") as fh:
                assert body == fh.read()
        finally:
            srv.shutdown()


def t_graphic_file_requires_auth():
    with tempfile.TemporaryDirectory() as d:
        _seed_graphics(d)
        srv, get, _post = _cockpit_client(graphics_dir=d)
        try:
            assert get("/cockpit/graphics/Standings.png")[0] == 401
        finally:
            srv.shutdown()


def t_graphic_file_traversal_and_missing_are_404():
    with tempfile.TemporaryDirectory() as d:
        _seed_graphics(d)
        srv, get, _post = _cockpit_client(graphics_dir=d)
        try:
            tok = ca.mint_token("sek", "alpha-racing")
            assert get("/cockpit/graphics/Missing.png?t=" + tok)[0] == 404
            assert get("/cockpit/graphics/notes.txt?t=" + tok)[0] == 404
            # URL-encoded traversal: %2F is NOT split into segments, then unquoted
            # to a slash and rejected by resolve_graphic.
            assert get("/cockpit/graphics/..%2Fsecret.png?t=" + tok)[0] == 404
        finally:
            srv.shutdown()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_cockpit as t; t.t_graphics_list_authed_sorted()"`
Expected: FAIL — the list route does not exist yet, so the response is the cockpit block's `{"error": "unknown"}` 404 (assertion on `code == 200` fails).

- [ ] **Step 3: Add the two routes**

In `src/relay/racecast-feeds.py`, inside the `if p[:1] == ["cockpit"]:` block, immediately before the final `return self._send({"error": "unknown", "path": self.path}, 404)` (line 3951), add:

```python
                    if p == ["cockpit", "graphics"]:
                        if self._console_auth() is None:
                            return None
                        return self._send({"graphics": list_graphics(graphics_dir)})
                    if len(p) == 3 and p[:2] == ["cockpit", "graphics"]:
                        if self._console_auth() is None:
                            return None
                        hit = resolve_graphic(graphics_dir, unquote(p[2]))
                        if not hit:
                            return self._send({"error": "graphic not found"}, 404)
                        return self._send_file(hit[0], "image/png")
```

(`p` is `[x for x in urlparse(self.path).path.split("/") if x]` — segments are NOT url-decoded, so the filename segment is `unquote`-d here; `%2F` never produces an extra segment.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_cockpit.py`
Expected: all `t_*` pass, exit 0.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/relay/racecast-feeds.py tests/test_cockpit.py
git commit -m "feat(cockpit): serve broadcast graphics list + files (tailnet)"
```

---

### Task 3: Funnel reachability — `console_policy` ANY entries

Without a `console_policy` rule the new routes return `NOT_FOUND` (404) when reached as `/console/cockpit/graphics*` over Funnel. Add both as `Requirement(ANY, False)` so any authenticated subject (commentator/director/producer/race_control) may read them — the same tier as `/cockpit/program` and `/cockpit/timer`.

**Files:**
- Modify: `src/scripts/console_policy.py` — add two entries in `min_capability` next to the existing cockpit ANY block (lines 124–129)
- Test: `tests/test_console.py` (matrix unit test) and `tests/test_console_gate.py` (end-to-end gate fall-through)

**Interfaces:**
- Consumes: `console_policy.ANY`, `Requirement` (existing).
- Produces: `min_capability(["cockpit","graphics"])` and `min_capability(["cockpit","graphics",<file>])` both return `Requirement(ANY, False)`; `decide(...)` therefore `ALLOW`s them for any authenticated role set.

- [ ] **Step 1: Write the failing tests**

In `tests/test_console.py`, add the two segment lists to the existing `t_any_authenticated_reads` tuple (after `["cockpit", "chat", "data"]` on line 31):

```python
                 ["cockpit", "timer"], ["cockpit", "chat", "data"],
                 ["cockpit", "graphics"], ["cockpit", "graphics", "Standings.png"]):
```

In `tests/test_console_gate.py`, first let `_serve` accept a graphics dir so the gate test can exercise the real fall-through. Change `_serve` (line 40) and its `make_handler` call (line 47-57):

```python
def _serve(companion_url=None, logo_path=None, sheet_id=None, graphics_dir=None):
```

Add `graphics_dir=graphics_dir,` to the `make_handler(...)` keyword args (e.g. right after `logo_path=logo_path`). Then add these tests:

```python
def t_console_cockpit_graphics_list_any_auth():
    # A commentator token reaches the graphics list over the /console mount.
    srv = _serve(); port = srv.server_address[1]
    try:
        code, body = _get(port, "/console/cockpit/graphics", _tok("alice"))
        assert code == 200, (code, body)
        assert json.loads(body)["graphics"] == [], body   # no dir -> empty
    finally:
        srv.shutdown()


def t_console_cockpit_graphic_file_served_over_mount():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "Standings.png"), "wb") as fh:
            fh.write(b"\x89PNG\r\nX")
        srv = _serve(graphics_dir=d); port = srv.server_address[1]
        try:
            code, body = _get(port, "/console/cockpit/graphics/Standings.png", _tok("alice"))
            assert code == 200 and body == "\x89PNG\r\nX", (code, body)
        finally:
            srv.shutdown()
```

Confirm `tempfile` and `os` are imported at the top of `tests/test_console_gate.py`; add `import tempfile` if missing.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_console as t; t.t_any_authenticated_reads()"`
Expected: FAIL — `min_capability(["cockpit","graphics"])` is `None`, so `_cap` returns `None != ("any", False)`.

- [ ] **Step 3: Add the policy entries**

In `src/scripts/console_policy.py`, inside the final cockpit ANY block (the `if p in (["cockpit"], ...)` at lines 124–129), add two rules immediately after that block (before `return None` at line 131):

```python
    # Cockpit graphics browser: read-only list + file serve, any authenticated
    # subject (same tier as /cockpit/program). The file route is 3 segments
    # (["cockpit","graphics",<filename>]); the filename is validated server-side
    # by resolve_graphic, not here.
    if p == ["cockpit", "graphics"]:
        return Requirement(ANY, False)
    if len(p) == 3 and p[:2] == ["cockpit", "graphics"]:
        return Requirement(ANY, False)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_console.py && python3 tests/test_console_gate.py`
Expected: both exit 0.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/console_policy.py tests/test_console.py tests/test_console_gate.py
git commit -m "feat(console): allow cockpit graphics browser over Funnel (ANY)"
```

---

### Task 4: Cockpit UI — "Graphics" card

A new card in the right column listing the graphics as clickable links. Each link opens the graphic in a new tab via a `RC_API(...)`-resolved URL (the fetch shim only patches `window.fetch`, not `<a href>`, so the mount prefix must be applied by hand). Auth in the new tab rides the existing `rc_console` cookie (same-origin GET).

**Files:**
- Modify: `src/cockpit/cockpit.html` — add CSS, the card markup, and the fetch/render JS

**Interfaces:**
- Consumes: `GET /cockpit/graphics` (Task 2); `RC_API`, `$`, `j` helpers (existing in the page).
- Produces: a rendered, clickable graphics list; no new server contract.

- [ ] **Step 1: Add the card styles**

In the `<style>` block of `src/cockpit/cockpit.html`, after the `.submsg`/`#subPending` rules (around line 79, before the `/* --- Director cues --- */` comment), add:

```css
  /* --- Graphics browser --- */
  #gfxList { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; }
  #gfxList a { display: block; text-decoration: none; color: #e8eaed;
               background: #1b1f25; border: 1px solid #2a3038; border-radius: 6px;
               padding: 7px 10px; font-size: 14px; }
  #gfxList a:hover { border-color: #3b82f6; }
  #gfxList .empty { font-size: 13px; opacity: .6; padding: 2px 0; }
  #gfxHead { display: flex; align-items: center; justify-content: space-between; }
  #gfxRefresh { background: none; border: 0; color: #8ab4f8; cursor: pointer;
                font: inherit; font-size: 12px; padding: 0; }
```

- [ ] **Step 2: Add the card markup**

In `src/cockpit/cockpit.html`, inside the right-hand column `<div>` (the one containing the timer / submit / chat cards), add a new card after the "Crew chat" card's closing `</div>` (i.e. after line 177, still inside the column `<div>` that closes on line 178):

```html
    <div class="card" style="margin-top:12px;">
      <h2 id="gfxHead">Graphics
        <button id="gfxRefresh" type="button" title="Reload the graphics list">Refresh</button>
      </h2>
      <div id="gfxList"><div class="empty">Loading…</div></div>
    </div>
```

- [ ] **Step 3: Add the fetch + render JS**

In the main `<script>` of `src/cockpit/cockpit.html`, add a graphics section before the final bootstrap line `pollTally(); pollProgram(); ...` (line 431). The list is fetched once on load + on the Refresh button (the graphics set is effectively static during an event, so no polling):

```javascript
// --- Graphics browser ---
// List the broadcast still-graphics; clicking one opens it in a new tab. The
// file URL MUST go through RC_API() so it resolves under the /console mount over
// Funnel (the fetch shim only patches window.fetch, not <a href>). Auth in the
// new tab rides the rc_console cookie (same-origin GET) — no token in the URL.
async function loadGraphics() {
  const box = $('gfxList');
  try {
    const d = await j('/cockpit/graphics');
    const list = d.graphics || [];
    box.textContent = '';
    if (!list.length) {
      const e = document.createElement('div');
      e.className = 'empty';
      e.textContent = 'No graphics available.';
      box.appendChild(e);
      return;
    }
    list.forEach(g => {
      const a = document.createElement('a');
      a.href = RC_API('/cockpit/graphics/' + encodeURIComponent(g.file));
      a.target = '_blank';
      a.rel = 'noopener';
      a.textContent = g.name;                 // XSS-safe (Sheet label)
      box.appendChild(a);
    });
  } catch (e) {
    box.textContent = '';
    const er = document.createElement('div');
    er.className = 'empty';
    er.textContent = 'Could not load graphics.';
    box.appendChild(er);
  }
}
$('gfxRefresh').addEventListener('click', loadGraphics);
```

Then add `loadGraphics();` to the bootstrap line (line 431):

```javascript
pollTally(); pollProgram(); pollTimer(); pollChat(); pollCues(); loadGraphics();
```

- [ ] **Step 4: Verify the page loads and renders (manual smoke)**

There is no JS unit harness for this page; verify by serving a real relay with a seeded graphics dir using the local-UAT path. Minimal check without full UAT:

Run: `python3 -c "p=open('src/cockpit/cockpit.html').read(); assert 'loadGraphics' in p and \"RC_API('/cockpit/graphics/\" in p and 'gfxList' in p; print('cockpit graphics UI present')"`
Expected: prints `cockpit graphics UI present`.

(Full visual confirmation happens in Task 5 when capturing the screenshot from a local dev build.)

- [ ] **Step 5: Commit**

```bash
git add src/cockpit/cockpit.html
git commit -m "feat(cockpit): Graphics card — list + open a graphic in a new tab"
```

---

### Task 5: Wiki screenshot + full-suite/build verification

The cockpit (Crew Console) is a documented UI surface. Per the repo rule, a visible cockpit change must refresh its wiki screenshot in the same change. Then run the whole CI-equivalent gate.

**Files:**
- Modify: the cockpit image under `src/docs/wiki/images/` (identify the exact file in Step 1)
- (No code changes in this task.)

**Interfaces:**
- Consumes: the running local dev build (cockpit page from Task 4).
- Produces: an updated committed screenshot; green lint + full test suite + build verify.

- [ ] **Step 1: Identify the cockpit wiki image**

Run: `ls src/docs/wiki/images/ | grep -i -E "cockpit|console"`
Expected: the cockpit/Crew-Console screenshot filename (e.g. `cockpit.png` or `crew-console*.png`). Note the exact name for Step 3.

- [ ] **Step 2: Stand up a local dev cockpit with seeded graphics**

Use the **`racecast-local-uat`** skill to copy in a real-league profile/runtime and run the relay from `src/`, OR run a synthetic relay. Ensure the active profile's `runtime/<profile>/graphics/` has a few PNGs (run `python3 src/racecast.py graphics`, or drop a couple of `*.png` files in) so the card is populated. Open the cockpit with a freshly minted token:

```bash
python3 src/racecast.py links            # prints per-person /console + cockpit links
```

- [ ] **Step 3: Recapture the screenshot from the local dev build**

Per the repo rule, capture from a **local dev build** (run from `src/`, no `VERSION` stamped) so the version badge stays uniform. Drive the running cockpit with the Playwright MCP and take an **element** screenshot framed to match the existing image (the full cockpit page or the relevant card, matching the current image's framing). Save over the file identified in Step 1.

- [ ] **Step 4: Run the full CI-equivalent gate**

```bash
python3 tools/lint.py
python3 tools/run-tests.py
python3 tools/build.py
```
Expected: lint clean; the whole suite passes; build's verify step succeeds (tokenization, no secrets, no shell scripts, preflight present).

- [ ] **Step 5: Commit**

```bash
git add src/docs/wiki/images/
git commit -m "docs(wiki): refresh cockpit screenshot for graphics browser"
```

---

## Self-Review

**1. Spec coverage:**
- Two token-gated endpoints under `/cockpit/*` → Task 2. ✓
- Path-traversal-safe file serving (`resolve_asset` pattern) → Task 1 (`resolve_graphic`) + Task 2. ✓
- Pure helpers `list_graphics` / `resolve_graphic` + `graphics_dir` already on `make_handler` → Task 1 (param confirmed pre-existing, no re-add). ✓
- Funnel reachability via `/console/cockpit/*` → Task 3 (`console_policy` ANY) — **a step the spec implied via "reachable over Funnel" but did not call out; covered explicitly here**. ✓
- Cockpit UI "Graphics" card, clickable name list, opens in new tab via `RC_API`, empty state, refresh → Task 4. ✓
- Lists all PNGs (no exclusion list) → Task 1 `list_graphics`. ✓
- Tests in `test_cockpit.py` (+ `test_console.py`, `test_console_gate.py` for the Funnel path) → Tasks 1–3. ✓
- Wiki screenshot refresh → Task 5. ✓
- Scope excludes Race Control desk / media clips / thumbnails → not implemented, as intended. ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows complete code; commands have expected output. ✓

**3. Type consistency:** `list_graphics` returns `[{"name","file"}]` (Task 1) and is consumed in Task 2 (`{"graphics": [...]}`) and Task 4 (`g.name`, `g.file`). `resolve_graphic` returns `(path, "image/png")` and Task 2 uses `hit[0]` + the constant `"image/png"`. `_cockpit_client(..., graphics_dir=None)` and `_serve(..., graphics_dir=None)` signatures match their `make_handler(graphics_dir=...)` calls. Route shapes (`["cockpit","graphics"]`, `len==3 & p[:2]==["cockpit","graphics"]`) are identical in the relay (Task 2) and the policy (Task 3). ✓
