# Console roles — Phase 3b: role-adaptive `/console` pages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve the role-adaptive HTML under `/console` — a launcher at `/console`, the existing cockpit at `/console/cockpit`, the director panel at `/console/panel` — each with the `rc_cockpit` cookie at `Path=/console` and a base-path shim so the pages' API calls resolve under `/console`. Plus a `/console/whoami` endpoint the launcher uses to render only the surfaces a token's roles permit.

**Architecture:** A server-side page server (`_send_page`) replaces a `__RC_API_BASE__` placeholder in the HTML with the active mount (`/console` publicly, `` at the tailnet root) and sets the cookie at the right path. A tiny injected shim patches `window.fetch` and exposes `RC_API()` so same-origin API requests get the base prefix — the existing pages keep calling `/cockpit/...`, `/timer/...`, etc., and they resolve under `/console` automatically. The Phase 3a gate gains page-serving + `/whoami` before its API fall-through. One capability-matrix gap is closed (`["cockpit","chat","send"]` → any).

**Tech Stack:** Pure Python 3 stdlib + vanilla HTML/JS (no framework, matching the repo).

## Global Constraints

- Edit only under `src/`, `tests/`, `docs/`, `CLAUDE.md`; never `dist/` or `runtime/`. English only; no secrets/machine paths/real IPs.
- Relay stays stdlib-only. Identity ≠ authorization; no token-format change.
- **Boundary invariant:** root + `/cockpit/*` behavior unchanged (tailnet/loopback). The root `/cockpit` page keeps its `Path=/cockpit` cookie; the root `/panel` keeps serving with no cookie. The ONLY new behavior is the added `/console/*` page routes. Nothing is funnelled in this phase (Phase 4).
- The base-path mechanism is the **fetch-interceptor shim** (chosen 2026-06-19): one injected script sets `window.RC_API_BASE` and patches `fetch`; the few `img.src` assignments use the `RC_API()` helper it defines. The shim is a no-op when `RC_API_BASE` is `""` (root serving), so root pages behave identically.
- Page authorization reuses the Phase 3a gate's `decide`: launcher + `/console/cockpit` = any authenticated; `/console/panel` = director. `/console/prod` is **deferred to Phase 7** (producer takeover UI); leaving it unserved → 404 (fail-closed), and the launcher simply doesn't link to it yet.
- A UI change note (CLAUDE.md): the director panel and cockpit are **visually unchanged** when served under `/console` (the shim is invisible), so `director-panel.png` does NOT go stale. The new launcher is a brand-new surface; its wiki image is a Phase 9 (docs) deliverable, not a stale existing image.
- Tests run on any machine incl. `windows-latest`; live-server assertions only, no network, no browser.
- Reference spec: `docs/superpowers/specs/2026-06-19-role-based-funnel-access-design.md` §D; builds on Phase 3a (`_console_gate`).

## File Structure

- **Modify** `src/scripts/console_policy.py` — add `["cockpit","chat","send"]` → `Requirement(ANY, False)` to the any-read block.
- **Modify** `tests/test_console.py` — assert the new matrix row.
- **Modify** `src/relay/racecast-feeds.py`:
  - generalize `_send_html_with_cookie` → `_send_page(path, api_base="", cookie_token=None, cookie_path=None)` (placeholder replace + optional cookie at a given path); keep a thin `_send_html_with_cookie` wrapper for the existing `/cockpit` call site.
  - route root `/panel` through `_send_page(panel_path, "")` (so its placeholder is replaced).
  - in `_console_gate`: handle `/console/whoami` and the page routes (`[]`→launcher, `["cockpit"]`, `["panel"]`) before the API fall-through.
  - `make_handler(..., console_page_path=None)` + resolve `console_page_path` in `__main__` (like `cockpit_page_path`) + pass it.
- **Modify** `src/cockpit/cockpit.html` and `src/director/director-panel.html` — add the shim+placeholder `<script>` at the very top of `<head>`; wrap the `img.src` assignments (cockpit:~234, panel:~1488 and ~1514) with `RC_API(...)`.
- **Create** `src/console/console.html` — the role-adaptive launcher.
- **Modify** `tests/test_console_gate.py` — page-serving + whoami integration tests.
- **Modify** `CLAUDE.md` — (no new test file; Task 3 just runs the gate. The test additions live in existing files.)

The shim `<script>` (identical in all three HTML pages, placed FIRST in `<head>` so it patches `fetch` before any page script runs):
```html
<script>
  // /console base-path shim (#216). The server replaces __RC_API_BASE__ with the
  // active mount ("/console" behind Funnel, "" at the tailnet/loopback root).
  // Patches fetch and exposes RC_API() so same-origin API calls resolve under the
  // mount; a no-op when the base is empty.
  window.RC_API_BASE = "__RC_API_BASE__";
  window.RC_API = function (p) {
    var b = window.RC_API_BASE || "";
    if (!b || typeof p !== "string" || p.charAt(0) !== "/") return p;
    if (p.indexOf(b + "/") === 0 || p === b) return p;   // already prefixed
    return b + p;
  };
  (function () {
    var _f = window.fetch;
    window.fetch = function (u, o) { return _f(window.RC_API(u), o); };
  })();
</script>
```

---

### Task 1: matrix gap + `_send_page` + shim into the existing pages

**Files:**
- Modify: `src/scripts/console_policy.py`, `tests/test_console.py`
- Modify: `src/relay/racecast-feeds.py`, `src/cockpit/cockpit.html`, `src/director/director-panel.html`
- Test: `tests/test_console_gate.py` (extend — root pages still serve correctly)

**Interfaces:**
- Produces: matrix allows `["cockpit","chat","send"]` (any); `_send_page(path, api_base="", cookie_token=None, cookie_path=None)`; both existing pages carry the shim + a placeholder, and serve **identically at the root** (base `""`).

- [ ] **Step 1: Write the failing tests**

In `tests/test_console.py`, add (before the `__main__` runner):
```python
def t_cockpit_chat_send_is_any_read():
    # cockpit.html POSTs /cockpit/chat/send; under /console it must be allowed
    # (any authenticated) -- identity is forced server-side by the cockpit handler.
    assert _cap(["cockpit", "chat", "send"], "POST") == ("any", False)
```
In `tests/test_console_gate.py`, add (before the runner) a check that the ROOT cockpit page still serves and now carries the shim with an EMPTY base (no `/console` prefix leaking into the tailnet page). The `_serve()` helper already builds a relay with `cockpit_secret`; root `/cockpit` needs `cockpit_page_path` — extend `_serve()` to pass it, OR add a focused server. Simplest: assert via the existing server that `GET /cockpit?t=<alice>` returns 200 and the body contains `window.RC_API_BASE = ""` (root base) — requires `_serve()` to pass `cockpit_page_path`:
```python
def t_root_cockpit_page_has_empty_base():
    srv = _serve(); port = srv.server_address[1]
    try:
        code, body = _get(port, "/cockpit", _tok("alice"))
        assert code == 200, (code, body)
        assert 'window.RC_API_BASE = ""' in body, body[:400]
    finally:
        srv.shutdown()
```
And update `_serve()` in `tests/test_console_gate.py` to pass the real cockpit page + panel + a launcher path so later tests can exercise them:
```python
    SRC = os.path.join(ROOT, "src")
    handler = m.make_handler(
        relay, cockpit_secret=SECRET, cockpit_versions_path=None,
        chat_store=m.ChatStore(os.path.join(LOGDIR, "chat.json")),
        crew_source=crew,
        panel_path=os.path.join(SRC, "director", "director-panel.html"),
        cockpit_page_path=os.path.join(SRC, "cockpit", "cockpit.html"),
        console_page_path=os.path.join(SRC, "console", "console.html"))
```
(`console_page_path` and the launcher file land in Task 2; for Task 1's test, the cockpit/panel paths are what matter. If `console.html` doesn't exist yet, `make_handler` just stores the path — it's only opened when `/console` is requested, which Task 1 doesn't test.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_console.py` → FAIL (`["cockpit","chat","send"]` returns `None`).
Run: `python3 tests/test_console_gate.py` → FAIL (`make_handler` has no `console_page_path` kwarg yet, and the page lacks the shim).

- [ ] **Step 3: Implement**

3a. `src/scripts/console_policy.py` — in the any-read cockpit tuple list, add the chat-send route:
```python
    if p in (["cockpit"], ["cockpit", "data"], ["cockpit", "program"],
             ["cockpit", "timer"], ["cockpit", "chat", "data"],
             ["cockpit", "chat", "send"]):
        return Requirement(ANY, False)
```

3b. `src/relay/racecast-feeds.py` — replace `_send_html_with_cookie` (lines ~2827-2851) with the generalized `_send_page` + a back-compat wrapper:
```python
        def _send_page(self, path, api_base="", cookie_token=None, cookie_path=None):
            """Serve an HTML page, substituting the __RC_API_BASE__ placeholder with
            api_base ("" at the tailnet/loopback root, "/console" behind Funnel) and
            optionally setting the rc_cockpit auth cookie scoped to cookie_path."""
            try:
                with open(path, "rb") as fh:
                    body = fh.read()
            except OSError:
                return self._send({"error": "page not found"}, 404)
            body = body.replace(b"__RC_API_BASE__", (api_base or "").encode())
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if cookie_token is not None and cookie_path:
                # `Secure` only behind the HTTPS Funnel (X-Forwarded-Proto); browsers
                # drop a Secure cookie over plain http, which would break the tailnet
                # fallback link (its sub-requests would never re-auth). The tailnet
                # hop is already WireGuard-encrypted.
                secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
                # Allowlist-sanitize: the value must never be raw request input
                # (CWE-113 response splitting / CWE-20 cookie injection).
                safe = cockpit_auth.safe_cookie_token(cookie_token)
                self.send_header("Set-Cookie",
                                 f"{cockpit_auth.COOKIE_NAME}={safe}; Path={cookie_path}; "
                                 f"HttpOnly{secure}; SameSite=Lax")
            self.end_headers()
            self.wfile.write(body)
            return None

        def _send_html_with_cookie(self, path, token):
            """Back-compat: the tailnet /cockpit page (cookie scoped to /cockpit,
            base empty)."""
            return self._send_page(path, "", cookie_token=token, cookie_path="/cockpit")
```

3c. `src/relay/racecast-feeds.py` — route root `/panel` through `_send_page` so its placeholder is replaced. Find the `if p == ["panel"]:` block (~line 3002) and change `return self._send_file(panel_path, "text/html; charset=utf-8")` to:
```python
                    return self._send_page(panel_path, "")
```

3d. `src/cockpit/cockpit.html` and `src/director/director-panel.html` — paste the shim `<script>` (from the File Structure section, verbatim) as the FIRST element inside `<head>` (before any other `<script>`/`<link>`). Then wrap the `img.src` assignments with `RC_API`:
- `src/cockpit/cockpit.html` ~line 234: `next.src = '/cockpit/program?_=' + Date.now();` → `next.src = RC_API('/cockpit/program') + '?_=' + Date.now();`
- `src/director/director-panel.html` ~line 1488: `img.src = "/preview/program?ts=" + Date.now();` → `img.src = RC_API("/preview/program") + "?ts=" + Date.now();`
- `src/director/director-panel.html` ~line 1514: `img.src = "/preview/feed/" + feed + "?ts=" + Date.now();` → `img.src = RC_API("/preview/feed/" + feed) + "?ts=" + Date.now();`
(Re-grep each `img.src`/`.src =` line to confirm the exact current text before editing.)

3e. `src/relay/racecast-feeds.py` — add `console_page_path=None` to the `make_handler` signature (next to `cockpit_page_path`).

- [ ] **Step 4: Run tests**

Run: `python3 tests/test_console.py` → `ALL PASS`.
Run: `python3 tests/test_console_gate.py` → `ALL PASS` (root cockpit page now has the empty base).
Run: `python3 tests/test_cockpit.py` and `python3 tests/test_pov.py` → `ALL PASS` (root /cockpit + /panel still serve; the cookie path for /cockpit is unchanged).

- [ ] **Step 5: Lint + commit**

Run: `python3 tools/lint.py`
```bash
git add src/scripts/console_policy.py tests/test_console.py src/relay/racecast-feeds.py \
        src/cockpit/cockpit.html src/director/director-panel.html tests/test_console_gate.py
git commit -m "$(cat <<'MSG'
feat(relay): base-path shim + _send_page for /console pages (#216 phase 3b)

Generalizes page serving to substitute the __RC_API_BASE__ placeholder and scope
the auth cookie per mount; injects a fetch-interceptor shim + RC_API() into the
cockpit and director pages so their API calls resolve under /console; closes the
matrix gap for /cockpit/chat/send (any). Root /cockpit + /panel serve identically
(empty base). No /console page routes yet -- that's the next task.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

### Task 2: `/console` page routes + launcher + `/whoami`

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`_console_gate` page handling + `console_page_path` wiring in `__main__`)
- Create: `src/console/console.html`
- Test: `tests/test_console_gate.py` (extend)

**Interfaces:**
- Consumes: `_send_page`, `_console_gate`/`_console_roles` (Phase 3a), `console_policy.decide`.
- Produces: `GET /console` → launcher (any auth); `GET /console/cockpit` → cockpit (any); `GET /console/panel` → director panel (director); `GET /console/whoami` → `{"subject","roles"}` (any).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_console_gate.py` (before the runner):
```python
def t_console_whoami_returns_roles():
    srv = _serve(); port = srv.server_address[1]
    try:
        code, data = _get(port, "/console/whoami", _tok("bob"))   # bob = director
        assert code == 200, (code, data)
        body = json.loads(data)
        assert body["subject"] == "bob"
        assert "director" in body["roles"]
    finally:
        srv.shutdown()


def t_console_launcher_served_any_auth():
    srv = _serve(); port = srv.server_address[1]
    try:
        code, body = _get(port, "/console", _tok("alice"))   # commentator
        assert code == 200, (code, body)
        assert 'window.RC_API_BASE = "/console"' in body, body[:400]
    finally:
        srv.shutdown()


def t_console_cockpit_page_any_auth_with_console_base_and_cookie():
    srv = _serve(); port = srv.server_address[1]
    try:
        url = f"http://127.0.0.1:{port}/console/cockpit?t=" + _tok("alice")
        with urllib.request.urlopen(url, timeout=5) as r:
            body = r.read().decode()
            setc = r.headers.get("Set-Cookie", "")
        assert 'window.RC_API_BASE = "/console"' in body, body[:400]
        assert "Path=/console" in setc, setc
    finally:
        srv.shutdown()


def t_console_panel_requires_director():
    srv = _serve(); port = srv.server_address[1]
    try:
        assert _get(port, "/console/panel", _tok("alice"))[0] == 403   # commentator -> no
        assert _get(port, "/console/panel", _tok("bob"))[0] == 200      # director -> yes
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_console_gate.py`
Expected: FAIL — `/console/whoami` 404s, `/console` falls through to status JSON (no `RC_API_BASE`), `/console/panel` falls through to the cookieless root panel.

- [ ] **Step 3: Implement**

3a. In `_console_gate` (added in Phase 3a), insert page + whoami handling AFTER `roles` is computed and BEFORE the `console_policy.decide(...)` call for APIs. The page routes still honor capability via `decide`:
```python
            # /console-only: identity introspection for the launcher (any auth).
            if sub == ["whoami"]:
                self._send({"subject": subject, "roles": sorted(roles)})
                return None
            # Role-adaptive pages: authorize via the same matrix, then serve HTML
            # with the /console base + a Path=/console cookie. Served BEFORE the API
            # fall-through so they don't reach the root page handlers (wrong cookie
            # path / no base).
            page = {(): console_page_path, ("cockpit",): cockpit_page_path,
                    ("panel",): panel_path}.get(tuple(sub))
            if page is not None or tuple(sub) in {(), ("cockpit",), ("panel",)}:
                if console_policy.decide(roles, sub, method, has_step_up) != console_policy.ALLOW:
                    self._send({"error": "forbidden"}, 403)
                    return None
                if not page:
                    return self._send({"error": "page not found"}, 404)
                token = self._cockpit_token()
                self._send_page(page, "/console", cookie_token=token, cookie_path="/console")
                return None
```
(Place this block right after `has_step_up = ...` and before `outcome = console_policy.decide(...)`. `tuple(sub)` of `[]` is `()` → launcher.)

3b. Wire `console_page_path` in `__main__`. Find the `cockpit_page_path = None` resolution block (~line 3671) and add an analogous one for the launcher; then pass it to `make_handler`:
```python
    console_page_path = None
    for cand in (os.path.join(here, "console", "console.html"),
                 os.path.join(here, "src", "console", "console.html")):
        if os.path.exists(cand):
            console_page_path = os.path.abspath(cand); break
```
(Match the exact candidate-path idiom used by the adjacent `cockpit_page_path` block — re-read it and mirror it, including its `here` base.) Then at the `make_handler(...)` call add:
```python
                           console_page_path=console_page_path,
```

3c. Create `src/console/console.html` — the role-adaptive launcher (dark theme consistent with `cockpit.html`; the shim FIRST in `<head>`):
```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Race Console</title>
<script>
  window.RC_API_BASE = "__RC_API_BASE__";
  window.RC_API = function (p) {
    var b = window.RC_API_BASE || "";
    if (!b || typeof p !== "string" || p.charAt(0) !== "/") return p;
    if (p.indexOf(b + "/") === 0 || p === b) return p;
    return b + p;
  };
  (function () { var _f = window.fetch; window.fetch = function (u, o) { return _f(window.RC_API(u), o); }; })();
</script>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; font: 16px/1.4 system-ui, sans-serif; background: #0e1116; color: #e6e6e6; }
  header { padding: 20px 24px; border-bottom: 1px solid #232a33; }
  h1 { margin: 0; font-size: 20px; }
  .who { color: #8b97a6; font-size: 13px; margin-top: 4px; }
  main { padding: 24px; display: grid; gap: 14px; max-width: 560px; }
  a.card { display: block; padding: 16px 18px; background: #161b22; border: 1px solid #232a33;
           border-radius: 10px; color: #e6e6e6; text-decoration: none; }
  a.card:hover { border-color: #3b82f6; }
  a.card .t { font-weight: 600; }
  a.card .d { color: #8b97a6; font-size: 13px; margin-top: 2px; }
  .empty { color: #8b97a6; }
</style>
</head>
<body>
<header><h1>Race Console</h1><div class="who" id="who">…</div></header>
<main id="menu"></main>
<script>
  function card(href, title, desc) {
    return '<a class="card" href="' + href + '"><div class="t">' + title +
           '</div><div class="d">' + desc + '</div></a>';
  }
  fetch('/whoami').then(function (r) { return r.json(); }).then(function (me) {
    var roles = me.roles || [];
    document.getElementById('who').textContent =
      me.subject + (roles.length ? ' — ' + roles.join(', ') : ' — viewer');
    var out = [];
    out.push(card('cockpit', 'Commentator Cockpit', 'Program monitor, tally, chat, stint links'));
    if (roles.indexOf('director') !== -1)
      out.push(card('panel', 'Director Panel', 'Feed, schedule, timer, HUD & submissions control'));
    var menu = document.getElementById('menu');
    menu.innerHTML = out.join('') ||
      '<div class="empty">No surfaces are available for your role.</div>';
  }).catch(function () {
    document.getElementById('menu').innerHTML =
      '<div class="empty">Could not load your access. Check your link.</div>';
  });
</script>
</body>
</html>
```
(Links are RELATIVE — `cockpit`/`panel` — so from `/console` they resolve to `/console/cockpit` and `/console/panel` without needing the shim.)

- [ ] **Step 4: Run tests**

Run: `python3 tests/test_console_gate.py` → `ALL PASS`.
Run: `python3 tests/test_pov.py` + `python3 tests/test_cockpit.py` → `ALL PASS` (unchanged).

- [ ] **Step 5: Lint + commit**

Run: `python3 tools/lint.py`
```bash
git add src/relay/racecast-feeds.py src/console/console.html tests/test_console_gate.py
git commit -m "$(cat <<'MSG'
feat(relay): role-adaptive /console pages + launcher + /whoami (#216 phase 3b)

Serves the launcher at /console, the cockpit at /console/cockpit (any auth), and
the director panel at /console/panel (director) -- each with a Path=/console
cookie and the /console base injected. /console/whoami returns the caller's
resolved roles so the launcher renders only the permitted surfaces. /console/prod
stays deferred to Phase 7 (fail-closed 404).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

### Task 3: Documentation + full local gate

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Note the new page in the architecture docs**

In `CLAUDE.md`, in the Control Center / relay docs area (near the cockpit description), add one concise sentence that the relay also serves a role-adaptive `/console` launcher + `/console/{cockpit,panel}` behind the Phase 3a auth gate (English, factual, no procedure invented). Keep it to one or two lines; do not restructure the section.

- [ ] **Step 2: Whole suite**

Run: `python3 tools/run-tests.py` → `ALL TEST FILES PASS`.

- [ ] **Step 3: Lint**

Run: `python3 tools/lint.py` → no errors.

- [ ] **Step 4: Build self-verify**

Run: `python3 tools/build.py` → exit 0. (`src/console/console.html` now ships under `src/`; confirm the build includes it and the verify step passes.) Do NOT `git add` `dist/`.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'MSG'
docs: note the role-adaptive /console pages in CLAUDE.md (#216 phase 3b)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

## Self-Review

**Spec coverage (Phase 3b scope only):**
- Spec §5/decision "separate gated pages under one mount" → launcher + `/console/cockpit` + `/console/panel`, each role-gated by the existing matrix. ✓
- Spec "base-path switch (`window.RC_API_BASE`)" → the fetch-interceptor shim + `RC_API()` (chosen mechanism), injected via the `__RC_API_BASE__` placeholder; root pages serve with `""` (no-op). ✓
- Spec "the `rc_cockpit` cookie at `Path=/console`" → `_send_page` cookie scoping. ✓
- Spec "the console shell renders the union of surfaces their roles permit" → `/console/whoami` + the launcher's role-conditional links. ✓
- Closes the `["cockpit","chat","send"]` matrix gap so cockpit.html works under `/console`. ✓
- Deferred (not gaps): `/console/prod` producer page (Phase 7), the Funnel mount (Phase 4), the link CLI (Phase 5), e2e/Playwright rendered checks + the launcher wiki image (Phase 9).

**Placeholder scan:** none — complete code throughout. (`__RC_API_BASE__` is a deliberate runtime placeholder the server substitutes, not a plan TODO.)

**Type/contract consistency:** `_send_page(path, api_base, cookie_token, cookie_path)` is used identically by the back-compat `/cockpit` wrapper, the root `/panel` route, and the three `/console` page routes; the shim's `window.RC_API_BASE`/`RC_API` names match between the injected snippet, the `img.src` call sites, and the launcher; `/console/whoami` returns `{"subject","roles"}` matching the launcher's `me.subject`/`me.roles`. Page authorization uses the same `console_policy.decide` outcomes as the API gate.

**Boundary/regression:** root `/cockpit` keeps `Path=/cockpit` + empty base; root `/panel` keeps no cookie + empty base; both now carry the inert shim. `test_cockpit`/`test_pov` re-run green confirms no regression. The new page routes are intercepted in the gate strictly under `p[0]=="console"`, so non-console traffic is untouched.
