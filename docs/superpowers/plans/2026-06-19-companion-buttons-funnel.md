# Companion buttons over Funnel (`/console/buttons`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a remote director reach the Bitfocus Companion web-button UI over the public Tailscale Funnel by reverse-proxying Companion through the relay under a director-gated `/console/buttons` sub-path.

**Architecture:** A pure helper module computes the proxy plumbing (path strip, header injection/filtering, version compare). The stdlib relay (`racecast-feeds.py`) gains a `_proxy_companion` method and a `_buttons_health` probe, wired into the existing `_console_gate` behind the **director** capability. Funnel still mounts only `/console`; `/console/buttons` is a sub-path of that same mount, proxied internally to `http://127.0.0.1:8000`, injecting `Companion-custom-prefix: /console/buttons` so a stock Companion ≥ v4.1.0 emits correctly-prefixed URLs. Phase 1 proxies HTTP (incl. Engine.IO long-polling); WebSocket passthrough is an optional Phase 2.

**Tech Stack:** Python 3 stdlib only (`http.server`, `urllib.request`, `urllib.parse`). No new runtime deps. Tests are runnable scripts (no pytest).

## Global Constraints

- **Edit only under `src/`** for shipped code; `tests/` and `docs/` are editable; never touch `dist/`/`runtime/`.
- **English only** in all code and docs.
- **Relay stays stdlib-only** — no new third-party imports in `racecast-feeds.py`.
- **Only `/console` is ever Funnel-mounted.** Do NOT add a second mount. `tests/test_tailscale.py` pins this — it must stay green.
- **OBS-WebSocket is never funnelled** (unchanged by this work).
- **The injected prefix value is exactly `/console/buttons`** (constant `console_proxy.COMPANION_PREFIX`).
- **Prerequisite: Companion ≥ v4.1.0** (the `Companion-custom-prefix` runtime header landed in v4.1.0 via bitfocus/companion#3503).
- **No real IPs / machine paths / secrets in tests** — upstream stubs bind `127.0.0.1` on a free port (`("127.0.0.1", 0)`).
- **Security posture is Option C (deliberate):** transparent passthrough behind the director token gate, fully automatic (no opt-in, no step-up). See the spec's "Security posture" section.
- Each commit message ends with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Run `python3 tools/lint.py` after changing any Python file; run `python3 tools/run-tests.py` + `python3 tools/build.py` before the PR.

## Phase 0 — Manual validation gate (run locally BEFORE Task 1; ships no code)

**This is not a subagent task.** Before implementing, the maintainer validates the load-bearing assumption — that Companion's web buttons work through a plain HTTP reverse proxy on the **polling** transport — against a real local Companion ≥ v4.1.0. If this fails, stop and revisit the design (Phase 2 WS may become mandatory, changing scope).

1. Start a local Companion (`racecast companion start` or the app), confirm it serves `http://127.0.0.1:8000/`.
2. Confirm version ≥ 4.1.0: `python3 -c "import sys; sys.path.insert(0,'src/scripts'); import install_apps as a; print(a.companion_http_version('http://127.0.0.1:8000'))"`.
3. Run a throwaway one-file reverse proxy (stdlib) on a spare port that forwards `/*` → `http://127.0.0.1:8000/*` with `Companion-custom-prefix: /console/buttons` injected and the path served under `/console/buttons/` (mimicking the relay). Open `http://127.0.0.1:<port>/console/buttons/` in a browser.
4. **Go/No-Go:** the web-buttons page renders, assets load (no 404s to `/`), and pressing a button actuates Companion. Note whether it works on polling alone (it should; socket.io falls back to polling when WS isn't proxied).
5. Record one line of findings (works / doesn't, transport observed) in this plan's PR description or append to the spike doc. Delete the throwaway script — **do not commit it**.

Proceed to Task 1 only on **Go**.

---

### Task 1: Pure proxy helpers

**Files:**
- Create: `src/scripts/console_proxy.py`
- Test: `tests/test_console_proxy.py`

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces:
  - `COMPANION_PREFIX = "/console/buttons"` (str), `COMPANION_PREFIX_HEADER = "Companion-custom-prefix"` (str), `HOP_BY_HOP` (set of lowercase header names).
  - `upstream_path(request_path: str) -> str` — strip the prefix, preserve query.
  - `forward_request_headers(headers, prefix=COMPANION_PREFIX, host="127.0.0.1:8000") -> dict` — copy client headers minus hop-by-hop/Host/Accept-Encoding, set Host, inject the prefix header. `headers` is any iterable of `.items()` (dict or `email.message.Message`).
  - `filter_response_headers(items) -> list[tuple[str,str]]` — drop hop-by-hop + Content-Length/Type/Encoding.
  - `is_websocket_upgrade(headers) -> bool`.
  - `version_ge(ver_str: str, floor: tuple) -> bool`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_console_proxy.py`:

```python
#!/usr/bin/env python3
"""Pure unit checks for the /console/buttons proxy helpers (#236).
Run: python3 tests/test_console_proxy.py"""
import importlib.util, os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "console_proxy", os.path.join(ROOT, "src", "scripts", "console_proxy.py"))
cp = importlib.util.module_from_spec(spec); spec.loader.exec_module(cp)


def t_upstream_path_strips_prefix():
    assert cp.upstream_path("/console/buttons") == "/"
    assert cp.upstream_path("/console/buttons/") == "/"
    assert cp.upstream_path("/console/buttons/tablet") == "/tablet"
    assert cp.upstream_path("/console/buttons/assets/index-abc.js") == "/assets/index-abc.js"


def t_upstream_path_preserves_query():
    assert cp.upstream_path("/console/buttons/socket.io/?EIO=4&transport=polling") \
        == "/socket.io/?EIO=4&transport=polling"


def t_forward_request_headers_injects_prefix_and_host():
    out = cp.forward_request_headers({"Host": "x.ts.net", "Accept": "text/html",
                                      "Connection": "keep-alive", "Accept-Encoding": "gzip"})
    assert out["Companion-custom-prefix"] == "/console/buttons"
    assert out["Host"] == "127.0.0.1:8000"
    assert out["Accept"] == "text/html"
    assert "Connection" not in out and "Accept-Encoding" not in out   # hop-by-hop + compression dropped


def t_filter_response_headers_drops_length_and_hop_by_hop():
    kept = dict(cp.filter_response_headers(
        [("Content-Length", "10"), ("Content-Type", "text/html"),
         ("Set-Cookie", "a=b"), ("Transfer-Encoding", "chunked"), ("X-Foo", "bar")]))
    assert "Content-Length" not in kept and "Content-Type" not in kept
    assert "Transfer-Encoding" not in kept
    assert kept["Set-Cookie"] == "a=b" and kept["X-Foo"] == "bar"


def t_is_websocket_upgrade():
    assert cp.is_websocket_upgrade({"Upgrade": "websocket", "Connection": "Upgrade"})
    assert not cp.is_websocket_upgrade({"Connection": "keep-alive"})


def t_version_ge():
    assert cp.version_ge("4.1.0", (4, 1, 0))
    assert cp.version_ge("4.2.5", (4, 1, 0))
    assert not cp.version_ge("4.0.9", (4, 1, 0))
    assert not cp.version_ge(None, (4, 1, 0))
    assert not cp.version_ge("garbage", (4, 1, 0))


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 tests/test_console_proxy.py`
Expected: FAIL — `No module named ...` / `AttributeError` (file does not exist yet).

- [ ] **Step 3: Write the implementation**

Create `src/scripts/console_proxy.py`:

```python
#!/usr/bin/env python3
"""Pure plumbing for the /console/buttons reverse proxy to Bitfocus Companion (#236).

No I/O, no sockets — just header/path transforms the relay's _proxy_companion uses.
Companion >= v4.1.0 serves its UI under a sub-path when the proxy injects the
`Companion-custom-prefix` header (bitfocus/companion#3503); these helpers build that
request and clean the response. Knowing nothing about socket.io, they are unaffected by
Companion upgrades. Tests: tests/test_console_proxy.py."""
from urllib.parse import urlsplit, urlunsplit

COMPANION_PREFIX = "/console/buttons"
COMPANION_PREFIX_HEADER = "Companion-custom-prefix"

# RFC 7230 hop-by-hop headers (lowercase) — never forwarded by a proxy.
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
              "te", "trailer", "trailers", "transfer-encoding", "upgrade"}


def upstream_path(request_path):
    """Map a full '/console/buttons[/...]' request path (optional ?query) to the
    Companion upstream path. The bare prefix and '<prefix>/' both map to '/'."""
    parts = urlsplit(request_path)
    path, pre = parts.path, COMPANION_PREFIX
    if path in (pre, pre + "/"):
        up = "/"
    elif path.startswith(pre + "/"):
        up = path[len(pre):]              # keep the leading slash of the remainder
    else:
        up = path                          # defensive: not under the prefix
    return urlunsplit(("", "", up, parts.query, ""))


def forward_request_headers(headers, prefix=COMPANION_PREFIX, host="127.0.0.1:8000"):
    """Client headers to send upstream: drop hop-by-hop, the original Host, and
    Accept-Encoding (so Companion replies uncompressed — the proxy does not re-encode);
    set Host to the local Companion and inject the sub-path prefix header. `headers` is
    any object exposing .items() (a dict or http.server's email.message.Message)."""
    out = {}
    for k, v in headers.items():
        lk = k.lower()
        if lk in HOP_BY_HOP or lk in ("host", "accept-encoding"):
            continue
        out[k] = v
    out["Host"] = host
    out[COMPANION_PREFIX_HEADER] = prefix
    return out


def filter_response_headers(items):
    """Upstream response headers to relay back: drop hop-by-hop and the framing headers
    the proxy recomputes (Content-Length/Type) or forced off (Content-Encoding). `items`
    is an iterable of (name, value) pairs."""
    out = []
    for k, v in items:
        lk = k.lower()
        if lk in HOP_BY_HOP or lk in ("content-length", "content-type", "content-encoding"):
            continue
        out.append((k, v))
    return out


def is_websocket_upgrade(headers):
    """True for a WebSocket upgrade request (Phase 2 passthrough only)."""
    return (headers.get("Upgrade", "").lower() == "websocket"
            and "upgrade" in headers.get("Connection", "").lower())


def version_ge(ver_str, floor):
    """True if dotted ver_str (e.g. '4.1.0') >= floor tuple (e.g. (4,1,0)); False on
    None / unparseable input."""
    try:
        parts = tuple(int(x) for x in ver_str.split(".")[:3])
    except (AttributeError, ValueError):
        return False
    return parts >= floor
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_console_proxy.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/console_proxy.py tests/test_console_proxy.py
git commit -m "feat(console): pure /console/buttons proxy helpers (#236)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `buttons` → director capability in the policy matrix

**Files:**
- Modify: `src/scripts/console_policy.py` (add one rule in `min_capability`, ~line 84, in the director block)
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: `console_policy.min_capability`, `console_policy.Requirement`, `console_policy.DIRECTOR`.
- Produces: `min_capability(["buttons", ...])` returns `Requirement(DIRECTOR, False)` for any path under `buttons` (incl. `["buttons"]`, `["buttons","health"]`, `["buttons","socket.io"]`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_console.py` (follow the file's existing `t_*` + `min_capability`/`Requirement` usage; check the top of the file for how it imports `console_policy` as e.g. `cp`):

```python
def t_buttons_requires_director_no_stepup():
    assert cp.min_capability(["buttons"]) == cp.Requirement(cp.DIRECTOR, False)
    assert cp.min_capability(["buttons", "tablet"]) == cp.Requirement(cp.DIRECTOR, False)
    assert cp.min_capability(["buttons", "socket.io"]) == cp.Requirement(cp.DIRECTOR, False)
    assert cp.min_capability(["buttons", "health"]) == cp.Requirement(cp.DIRECTOR, False)


def t_buttons_commentator_forbidden_director_allowed():
    assert cp.decide({cp.COMMENTATOR}, ["buttons", "tablet"]) == cp.FORBIDDEN
    assert cp.decide({cp.DIRECTOR}, ["buttons", "tablet"]) == cp.ALLOW
```

(Match the import alias actually used in `tests/test_console.py` — read its first ~20 lines first; the snippet above assumes `cp`.)

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 tests/test_console.py`
Expected: FAIL — `min_capability(["buttons"])` returns `None` (route unknown) so the equality assert fails.

- [ ] **Step 3: Write the implementation**

In `src/scripts/console_policy.py`, inside `min_capability`, in the director block (after the `obs` rule near line 74, alongside the other `p[0] == ...` director rules), add:

```python
    if p and p[0] == "buttons":                 # /console/buttons/* -> Companion proxy (#236)
        return Requirement(DIRECTOR, False)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_console.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/console_policy.py tests/test_console.py
git commit -m "feat(console): route /console/buttons to the director capability (#236)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Relay proxy + health endpoint + gate wiring

**Files:**
- Modify: `src/relay/racecast-feeds.py`
  - imports near the top (`import console_proxy`, `import install_apps`) — next to the existing `import console_policy` (~line 91)
  - `make_handler(...)` signature (~line 2858–2861): add `companion_url="http://127.0.0.1:8000"`
  - add `_proxy_companion` + `_buttons_health` methods inside class `H` (near `_send`, ~line 2880)
  - `_console_gate` (~line 3028, after the `whoami` block, before the page block): add the `buttons` branch
- Test: `tests/test_console_gate.py` (extend `_serve` to thread `companion_url`; add a stub upstream + tests)

**Interfaces:**
- Consumes: `console_proxy.upstream_path/forward_request_headers/filter_response_headers/version_ge`, `install_apps.companion_http_version`, `console_policy.decide`.
- Produces: handler methods `_proxy_companion(self, method)` and `_buttons_health(self)`; a new `make_handler` kwarg `companion_url`.

- [ ] **Step 1: Write the failing test**

In `tests/test_console_gate.py`, add a stub Companion and thread `companion_url` through `_serve`. First change `_serve` to accept and pass it:

```python
def _serve(companion_url="http://127.0.0.1:8000"):
    rows = [("https://youtu.be/a", "Alice", "1", 2)]
    src = _FakeSource(_URLS8, rows)
    relay = m.Relay(src, [53001, 53002], LOGDIR)
    crew = _Crew([("Bob", True, False), ("Carol", False, True)])
    SRC = os.path.join(ROOT, "src")
    handler = m.make_handler(
        relay, console_secret=SECRET, cockpit_versions_path=None,
        chat_store=m.ChatStore(os.path.join(LOGDIR, "chat.json")),
        crew_source=crew,
        panel_path=os.path.join(SRC, "director", "director-panel.html"),
        cockpit_page_path=os.path.join(SRC, "cockpit", "cockpit.html"),
        console_page_path=os.path.join(SRC, "console", "console.html"),
        companion_url=companion_url)
    srv = m.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
```

Then add the stub + tests:

```python
from http.server import BaseHTTPRequestHandler


class _StubCompanion(BaseHTTPRequestHandler):
    last = {}
    def do_GET(self):
        _StubCompanion.last = {"path": self.path,
                               "prefix": self.headers.get("Companion-custom-prefix")}
        body = b"<html>companion web buttons</html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass


def _stub_companion():
    srv = m.ThreadingHTTPServer(("127.0.0.1", 0), _StubCompanion)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def t_buttons_proxies_to_companion_for_director():
    up = _stub_companion(); upurl = f"http://127.0.0.1:{up.server_address[1]}"
    srv = _serve(companion_url=upurl); port = srv.server_address[1]
    try:
        code, body = _get(port, "/console/buttons/tablet", _tok("bob"))   # director
        assert code == 200, (code, body)
        assert "companion web buttons" in body, body
        assert _StubCompanion.last["prefix"] == "/console/buttons", _StubCompanion.last
        assert _StubCompanion.last["path"] == "/tablet", _StubCompanion.last
    finally:
        srv.shutdown(); up.shutdown()


def t_buttons_forbidden_for_commentator():
    up = _stub_companion(); upurl = f"http://127.0.0.1:{up.server_address[1]}"
    srv = _serve(companion_url=upurl); port = srv.server_address[1]
    try:
        assert _get(port, "/console/buttons/tablet", _tok("alice"))[0] == 403
    finally:
        srv.shutdown(); up.shutdown()


def t_buttons_502_when_companion_down():
    # Point at a closed port (no stub) -> proxy returns 502.
    srv = _serve(companion_url="http://127.0.0.1:1"); port = srv.server_address[1]
    try:
        assert _get(port, "/console/buttons/tablet", _tok("bob"))[0] == 502
    finally:
        srv.shutdown()


def t_buttons_health_shape_and_director_gated():
    srv = _serve(companion_url="http://127.0.0.1:1"); port = srv.server_address[1]
    try:
        assert _get(port, "/console/buttons/health", _tok("alice"))[0] == 403   # commentator
        code, body = _get(port, "/console/buttons/health", _tok("bob"))         # director
        assert code == 200, (code, body)
        blob = json.loads(body)
        assert set(blob) == {"reachable", "version", "ok"}, blob
        assert blob["reachable"] is False and blob["ok"] is False               # nothing on port 1
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 tests/test_console_gate.py`
Expected: FAIL — `make_handler() got an unexpected keyword argument 'companion_url'` (param not added yet).

- [ ] **Step 3: Write the implementation**

(a) Imports — next to `import console_policy` (~line 91):

```python
import console_proxy   # pure /console/buttons proxy plumbing (#236)
import install_apps    # companion_http_version for the buttons health probe (#236)
```

(b) `make_handler` signature — extend the last line of the param list (~line 2861):

```python
                 console_page_path=None, companion_url="http://127.0.0.1:8000"):
```

(c) Methods inside class `H` (place after `_send_page`, ~line 2905):

```python
        def _proxy_companion(self, method):
            """Reverse-proxy a /console/buttons/* request to the local Companion
            (Option C, #236). Director-gated by the caller. Best-effort: never raises;
            an unreachable Companion -> 502. Phase 1 handles HTTP incl. Engine.IO
            long-polling; WebSocket upgrade is a future Phase 2 (falls back to polling)."""
            import urllib.request, urllib.error
            up = console_proxy.upstream_path(self.path)
            url = companion_url.rstrip("/") + up
            length = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(length) if length else None
            hdrs = console_proxy.forward_request_headers(self.headers)
            req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    body, status = resp.read(), resp.status
                    out_headers = console_proxy.filter_response_headers(resp.headers.items())
                    ctype = resp.headers.get("Content-Type", "application/octet-stream")
            except urllib.error.HTTPError as e:        # relay Companion's own 4xx/5xx verbatim
                body, status = e.read(), e.code
                out_headers = console_proxy.filter_response_headers(e.headers.items())
                ctype = e.headers.get("Content-Type", "application/octet-stream")
            except Exception as e:                      # connection refused / timeout
                LOG.warning("Companion proxy failed: %s: %s", type(e).__name__, e)
                return self._send({"error": "Companion not reachable on 127.0.0.1:8000"}, 502)
            self.send_response(status)
            for k, v in out_headers:
                self.send_header(k, v)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)
            return None

        def _buttons_health(self):
            """Director-gated availability probe for the launcher: is Companion up, and
            is it new enough (>= 4.1.0) to serve under the /console/buttons sub-path?"""
            import urllib.request
            ver = install_apps.companion_http_version(companion_url)
            reachable = ver is not None
            if not reachable:                           # reachable but version-less (e.g. old build)
                try:
                    urllib.request.urlopen(companion_url.rstrip("/") + "/", timeout=2)
                    reachable = True
                except Exception:
                    reachable = False
            ok = reachable and console_proxy.version_ge(ver, (4, 1, 0))
            return self._send({"reachable": reachable, "version": ver, "ok": ok})
```

(d) `_console_gate` — insert the buttons branch right after the `whoami` block (after line ~3031, before the page block at ~3036):

```python
            # /console/buttons/* -> reverse-proxy to the local Companion (#236), director
            # only. 'buttons/health' is served by the relay (launcher availability probe)
            # and shadows that one upstream path (Companion's UI does not use /health).
            if sub and sub[0] == "buttons":
                if console_policy.decide(roles, sub, method, has_step_up) != console_policy.ALLOW:
                    self._send({"error": "forbidden"}, 403)
                    return None
                if sub == ["buttons", "health"]:
                    self._buttons_health()
                    return None
                self._proxy_companion(method)
                return None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_console_gate.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Confirm the boundary test still passes + lint + commit**

```bash
python3 tests/test_tailscale.py      # only /console funnelled — must still pass
python3 tools/lint.py
git add src/relay/racecast-feeds.py tests/test_console_gate.py
git commit -m "feat(console): relay-proxy /console/buttons to Companion, director-gated (#236)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Launcher entry for directors

**Files:**
- Modify: `src/console/console.html` (the `<script>` block, lines 47–61)
- Test: `tests/test_console_gate.py` (assert the served launcher carries the buttons wiring for directors)

**Interfaces:**
- Consumes: the existing `card()` helper, `RC_API()`, `/console/whoami` roles, and the new `GET /console/buttons/health`.
- Produces: a director-only "Companion Buttons" card that opens `/console/buttons/` in a new tab when `health.ok`, or a disabled "needs Companion ≥ 4.1" note when reachable-but-old.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_console_gate.py`:

```python
def t_console_launcher_has_buttons_wiring_for_director():
    srv = _serve(companion_url="http://127.0.0.1:1"); port = srv.server_address[1]
    try:
        code, body = _get(port, "/console", _tok("bob"))   # director
        assert code == 200, (code, body)
        # The launcher JS must probe buttons health and build a mount-absolute buttons link.
        assert "/buttons/health" in body, body
        assert "RC_API('/buttons/')" in body, body
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 tests/test_console_gate.py`
Expected: FAIL on `t_console_launcher_has_buttons_wiring_for_director` — strings absent.

- [ ] **Step 3: Write the implementation**

In `src/console/console.html`, replace the director-card line and menu render (lines 53–57) so the buttons card is appended after a health probe. Replace:

```javascript
    if (roles.indexOf('director') !== -1)
      out.push(card(RC_API('/panel'), 'Director Panel', 'Feed, schedule, timer, HUD & submissions control'));
    var menu = document.getElementById('menu');
    menu.innerHTML = out.join('') ||
      '<div class="empty">No surfaces are available for your role.</div>';
```

with:

```javascript
    if (roles.indexOf('director') !== -1)
      out.push(card(RC_API('/panel'), 'Director Panel', 'Feed, schedule, timer, HUD & submissions control'));
    var menu = document.getElementById('menu');
    function render() {
      menu.innerHTML = out.join('') ||
        '<div class="empty">No surfaces are available for your role.</div>';
    }
    render();
    if (roles.indexOf('director') !== -1) {
      // Companion buttons over Funnel (#236): only when a new-enough Companion is up.
      fetch(RC_API('/buttons/health')).then(function (r) { return r.json(); }).then(function (h) {
        if (h.ok) {
          out.push('<a class="card" target="_blank" rel="noopener" href="' +
            RC_API('/buttons/') + '"><div class="t">Companion Buttons</div>' +
            '<div class="d">Your physical Companion button page, in the browser</div></a>');
        } else if (h.reachable) {
          out.push('<div class="card" style="opacity:.5"><div class="t">Companion Buttons</div>' +
            '<div class="d">Unavailable — needs Companion ≥ 4.1</div></div>');
        }
        render();
      }).catch(function () { /* leave the menu as rendered */ });
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_console_gate.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

(No lint — HTML only. No Control Center / Director Panel surface changed, so no wiki screenshot refresh.)

```bash
git add src/console/console.html tests/test_console_gate.py
git commit -m "feat(console): launcher 'Companion Buttons' card for directors (#236)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Documentation — correct the security boundary honestly

**Files:**
- Modify: `src/docs/wiki/Remote-access.md`, `src/docs/wiki/Architecture.md`, `src/docs/wiki/Companion.md`, `CLAUDE.md`
- Test: none (docs); verified by `tools/build.py` and a manual read.

**Interfaces:** none.

- [ ] **Step 1: `Remote-access.md`** — In "The security boundary" / "Companion stays on the tailnet" sections, change the claim that Companion is never exposed. Add, in the boundary list and the Companion section, that Companion's web buttons ARE reachable over Funnel at `/console/buttons`, **behind the director gate**, and add a clearly-marked risk note:

```markdown
### Companion web buttons over the Funnel (`/console/buttons`)

A director can open their physical Companion button page in the browser over the Funnel at
`/console/buttons` (a card on the `/console` launcher, shown when Companion ≥ v4.1.0 is
running). The relay reverse-proxies it to the local Companion, behind the **director token
gate** — the page needs no Tailscale account.

> **Security note (deliberate).** Companion has no real auth boundary by vendor design — its
> admin password "only stops casual browsers", and its realtime channel can export the full
> configuration without authentication (bitfocus/companion#3814, closed *won't-fix*). So an
> authenticated **director** reaching `/console/buttons` effectively has full control of that
> Companion, including a config export that may contain stored credentials. This is an
> accepted trade-off (we trust the director roster, and a director on the tailnet already has
> the same access). Recommendations: do not store reusable secrets in a funnelled Companion
> (rotate the OBS-WebSocket password if it must live there); `racecast cockpit token revoke`
> rotates a leaked link at once. OBS-WebSocket itself is still never funnelled.
```

Keep "only `/console` is Funnel-mounted" accurate: `/console/buttons` is a sub-path of that single mount, proxied internally — there is **no** second mount.

- [ ] **Step 2: `Architecture.md`** — In the control-flow / boundary section and its diagram, add `/console/buttons → Companion` through the relay (director-gated). One line + the diagram edge `RELAY -. "director-gated buttons proxy" .-> COMP`.

- [ ] **Step 3: `Companion.md`** — Alongside the existing Tailscale remote-access path, add a short "Over the Funnel" note pointing to `/console/buttons` and [Remote access](Remote-access), with the Companion ≥ v4.1.0 requirement.

- [ ] **Step 4: `CLAUDE.md`** — In the relay/cockpit section, reconcile the "only `/console` is funnel-mounted" statement with the new sub-path proxy: note `/console/buttons` reverse-proxies to the local Companion (director-gated, #236), that it is a sub-path of the single `/console` mount (no second mount), and that OBS-WebSocket remains never funnelled.

- [ ] **Step 5: Commit**

```bash
git add src/docs/wiki/Remote-access.md src/docs/wiki/Architecture.md src/docs/wiki/Companion.md CLAUDE.md
git commit -m "docs(wiki): document Companion buttons over Funnel + the boundary change (#236)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6 (OPTIONAL — Phase 2): WebSocket passthrough

> **Skip unless Phase 0 / real use shows polling latency is inadequate for button feel.** Phase 1 already works on polling (socket.io's default fallback). This task only lowers latency; it is not required for a shippable feature. If skipped, note it in the PR.

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`_proxy_companion`: handle `console_proxy.is_websocket_upgrade`)
- Test: `tests/test_console_gate.py` (a stub upstream that completes a `101` upgrade and echoes one frame)

**Interfaces:**
- Consumes: `console_proxy.is_websocket_upgrade`, `console_proxy.upstream_path`, `self.connection` (the raw client socket).
- Produces: transparent bidirectional byte relay for `/console/buttons/socket.io/` WebSocket; any failure closes the upgrade so the client reverts to polling.

- [ ] **Step 1: Write the failing test** — a stub that accepts the upgrade, returns `101 Switching Protocols` with a computed `Sec-WebSocket-Accept`, then echoes bytes; assert the relay relays the `101` and a single echoed frame. (Use a raw `socket` stub, not `BaseHTTPRequestHandler`, since this hijacks the connection.)

- [ ] **Step 2: Run it to verify it fails** — `python3 tests/test_console_gate.py` fails (WS not handled; upgrade returns a normal proxied response or errors).

- [ ] **Step 3: Implement** — at the top of `_proxy_companion`, before the urllib path:

```python
            if console_proxy.is_websocket_upgrade(self.headers):
                import socket, select
                try:
                    up = socket.create_connection(("127.0.0.1", 8000), timeout=5)
                except OSError as e:
                    LOG.warning("Companion WS connect failed: %s", e)
                    return self._send({"error": "Companion not reachable"}, 502)
                # Replay the upgrade request line + headers (rewritten path + injected prefix).
                req_line = "GET %s HTTP/1.1\r\n" % console_proxy.upstream_path(self.path)
                hdrs = console_proxy.forward_request_headers(self.headers)
                raw = req_line + "".join("%s: %s\r\n" % kv for kv in hdrs.items()) + "\r\n"
                up.sendall(raw.encode("latin-1"))
                client = self.connection
                # Pump both directions until either side closes (transparent — no framing).
                socks = [client, up]
                try:
                    while True:
                        r, _, _ = select.select(socks, [], [], 60)
                        if not r:
                            break
                        for s in r:
                            data = s.recv(65536)
                            if not data:
                                raise ConnectionError
                            (up if s is client else client).sendall(data)
                except Exception:
                    pass
                finally:
                    up.close()
                self.close_connection = True
                return None
```

- [ ] **Step 4: Run the test to verify it passes** — `python3 tests/test_console_gate.py` → `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/relay/racecast-feeds.py tests/test_console_gate.py
git commit -m "feat(console): optional WebSocket passthrough for /console/buttons (#236)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification (after the last task)

- [ ] `python3 tools/run-tests.py` → whole suite green.
- [ ] `python3 tools/lint.py` → clean.
- [ ] `python3 tools/build.py` → exits 0 (verify step ≈ CI).
- [ ] Manual: with a real Companion ≥ v4.1.0 + `racecast funnel on`, open `https://<host>/console` as a director → "Companion Buttons" card appears → opens the web-buttons page → a press actuates Companion. Confirm `https://<host>/status` and `/panel` (root) are NOT reachable publicly (boundary intact).
