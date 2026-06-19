# Companion buttons over Funnel (`/console/buttons`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a remote director reach the Bitfocus Companion web-button UI over the public Tailscale Funnel by reverse-proxying Companion through the relay under a director-gated `/console/buttons` sub-path.

**Architecture:** A pure helper module computes the proxy plumbing (path strip, header injection/filtering, version + bind-address resolution). The stdlib relay (`racecast-feeds.py`) gains a `_proxy_companion` method — **HTTP for html/js/css/assets AND a raw-WebSocket passthrough for the tRPC `/trpc` channel** — plus a `_buttons_health` probe, wired into the existing `_console_gate` behind the **director** capability. Funnel still mounts only `/console`; `/console/buttons` is a sub-path of that same mount, proxied internally to the resolved Companion bind address, injecting `Companion-custom-prefix: console/buttons` so a stock Companion ≥ v4.1.0 emits correctly-prefixed URLs.

**Tech Stack:** Python 3 stdlib only (`http.server`, `urllib.request`, `urllib.parse`, `socket`, `select`). No new runtime deps. Tests are runnable scripts (no pytest).

## Phase 0 — Validation (DONE 2026-06-19, against a live local Companion v4.3.4)

A throwaway stdlib proxy + a real browser (Playwright) confirmed the design and **corrected three assumptions**. Verdict: **GO**. Findings, now load-bearing:

1. **Companion v4.3.4** (≥ v4.1.0); the `Companion-custom-prefix` mechanism is present and rewrites every served asset URL.
2. **The header value must have NO leading slash:** `console/buttons`. `/console/buttons` makes Companion emit broken `//console/buttons/…` (protocol-relative) URLs. Keep two strings: path prefix `/console/buttons`, header value `console/buttons`.
3. **The realtime channel is a raw WebSocket at `/trpc`** (tRPC). There is **no** HTTP polling fallback — a polling-only proxy renders a permanent loading spinner. **The WebSocket passthrough is mandatory.** Upside: a raw WS to a single upstream is simpler than socket.io — transparent byte pump, no Engine.IO/`sid`/polling.
4. **WS passthrough works:** with the byte pump the full live button page renders (0 console errors, live button colours, presses actuate).
5. **Companion binds to the Tailscale IP, not loopback** (`racecast companion start` → `--admin-address=<tailscale-ip>:8000`). The relay must **resolve** the bind address.

(No production code was shipped in Phase 0; the throwaway proxy + screenshots were deleted.)

## Global Constraints

- **Edit only under `src/`** for shipped code; `tests/` and `docs/` are editable; never touch `dist/`/`runtime/`.
- **English only** in all code and docs.
- **Relay stays stdlib-only** — no new third-party imports in `racecast-feeds.py`.
- **Only `/console` is ever Funnel-mounted.** Do NOT add a second mount. `tests/test_tailscale.py` pins this — it must stay green.
- **OBS-WebSocket is never funnelled** (unchanged by this work).
- **Prefix has two forms:** path prefix `MOUNT_PREFIX = "/console/buttons"` (strip/route); header value `PREFIX_HEADER_VALUE = "console/buttons"` (NO leading slash — Phase 0 fact #2).
- **The WebSocket passthrough is mandatory** (Companion's tRPC `/trpc` has no polling fallback).
- **Companion address is resolved, never hardcoded loopback:** config.json `bind_ip` → Tailscale IP → `127.0.0.1`.
- **Prerequisite: Companion ≥ v4.1.0** (the `Companion-custom-prefix` runtime header landed in v4.1.0 via bitfocus/companion#3503).
- **No real IPs / machine paths / secrets in tests** — upstream stubs bind `127.0.0.1` on a free port (`("127.0.0.1", 0)`); Tailscale test IPs are `100.64.0.0/10`.
- **Security posture is Option C (deliberate):** transparent passthrough behind the director token gate, fully automatic (no opt-in, no step-up). See the spec's "Security posture".
- Each commit message ends with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Run `python3 tools/lint.py` after changing any Python file; run `python3 tools/run-tests.py` + `python3 tools/build.py` before the PR.

---

### Task 1: Pure proxy helpers

**Files:**
- Create: `src/scripts/console_proxy.py`
- Test: `tests/test_console_proxy.py`

**Interfaces:**
- Produces: `MOUNT_PREFIX="/console/buttons"`, `PREFIX_HEADER_VALUE="console/buttons"`, `COMPANION_PREFIX_HEADER="Companion-custom-prefix"`, `HOP_BY_HOP` (set); `upstream_path(request_path)->str`; `forward_request_headers(headers, prefix=PREFIX_HEADER_VALUE, host="127.0.0.1:8000")->dict`; `filter_response_headers(items)->list`; `is_websocket_upgrade(headers)->bool`; `version_ge(ver_str, floor)->bool`; `resolve_companion_base(bind_ip, tailscale_ip, port=8000)->str`.

- [ ] **Step 1: Write the failing test** — create `tests/test_console_proxy.py`:

```python
#!/usr/bin/env python3
"""Pure unit checks for the /console/buttons proxy helpers (#236).
Run: python3 tests/test_console_proxy.py"""
import importlib.util, os
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "console_proxy", os.path.join(ROOT, "src", "scripts", "console_proxy.py"))
cp = importlib.util.module_from_spec(spec); spec.loader.exec_module(cp)


def t_upstream_path_strips_prefix_and_keeps_query():
    assert cp.upstream_path("/console/buttons") == "/"
    assert cp.upstream_path("/console/buttons/") == "/"
    assert cp.upstream_path("/console/buttons/tablet") == "/tablet"
    assert cp.upstream_path("/console/buttons/assets/index-abc.js") == "/assets/index-abc.js"
    assert cp.upstream_path("/console/buttons/trpc?x=1&y=2") == "/trpc?x=1&y=2"


def t_forward_headers_inject_no_leading_slash_prefix():
    out = cp.forward_request_headers({"Host": "x.ts.net", "Accept": "text/html",
                                      "Connection": "keep-alive", "Accept-Encoding": "gzip"})
    assert out["Companion-custom-prefix"] == "console/buttons"   # NO leading slash (Phase 0)
    assert out["Host"] == "127.0.0.1:8000"
    assert out["Accept"] == "text/html"
    assert "Connection" not in out and "Accept-Encoding" not in out


def t_filter_response_headers_drops_framing_and_hop_by_hop():
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
    assert cp.version_ge("4.1.0", (4, 1, 0)) and cp.version_ge("4.3.4", (4, 1, 0))
    assert not cp.version_ge("4.0.9", (4, 1, 0))
    assert not cp.version_ge(None, (4, 1, 0)) and not cp.version_ge("garbage", (4, 1, 0))


def t_resolve_companion_base():
    # A specific bind_ip is authoritative (Companion bound to the Tailscale IP, not loopback).
    assert cp.resolve_companion_base("100.81.0.4", None) == "http://100.81.0.4:8000"
    # 0.0.0.0 (all interfaces) -> loopback works.
    assert cp.resolve_companion_base("0.0.0.0", "100.81.0.4") == "http://127.0.0.1:8000"
    # missing bind_ip -> Tailscale IP if known, else loopback.
    assert cp.resolve_companion_base("", "100.81.0.4") == "http://100.81.0.4:8000"
    assert cp.resolve_companion_base(None, None) == "http://127.0.0.1:8000"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run it to verify it fails** — `python3 tests/test_console_proxy.py` → FAIL (module missing).

- [ ] **Step 3: Write the implementation** — create `src/scripts/console_proxy.py`:

```python
#!/usr/bin/env python3
"""Pure plumbing for the /console/buttons reverse proxy to Bitfocus Companion (#236).

No I/O, no sockets — header/path transforms + address/version decisions the relay's
_proxy_companion uses. Companion >= v4.1.0 serves its UI under a sub-path when the proxy
injects the `Companion-custom-prefix` header WITHOUT a leading slash (bitfocus/companion
#3503; validated on v4.3.4). Knowing nothing about tRPC/WebSocket framing, these helpers are
unaffected by Companion upgrades. Tests: tests/test_console_proxy.py."""
from urllib.parse import urlsplit, urlunsplit

MOUNT_PREFIX = "/console/buttons"          # the relay path prefix (strip / route)
PREFIX_HEADER_VALUE = "console/buttons"    # the Companion-custom-prefix value (NO leading slash)
COMPANION_PREFIX_HEADER = "Companion-custom-prefix"

# RFC 7230 hop-by-hop headers (lowercase) — never forwarded on the HTTP path.
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
              "te", "trailer", "trailers", "transfer-encoding", "upgrade"}


def upstream_path(request_path):
    """Map a full '/console/buttons[/...]' request path (optional ?query) to the Companion
    upstream path. The bare prefix and '<prefix>/' both map to '/'."""
    parts = urlsplit(request_path); path, pre = parts.path, MOUNT_PREFIX
    if path in (pre, pre + "/"):
        up = "/"
    elif path.startswith(pre + "/"):
        up = path[len(pre):]
    else:
        up = path
    return urlunsplit(("", "", up, parts.query, ""))


def forward_request_headers(headers, prefix=PREFIX_HEADER_VALUE, host="127.0.0.1:8000"):
    """Client headers to send upstream on the HTTP path: drop hop-by-hop, the original Host,
    and Accept-Encoding (Companion then replies uncompressed — the proxy does not re-encode);
    set Host and inject the no-leading-slash sub-path prefix header. `headers` exposes
    .items() (a dict or http.server's email.message.Message)."""
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
    """Upstream response headers to relay back: drop hop-by-hop and the framing headers the
    proxy recomputes (Content-Length/Type) or forced off (Content-Encoding)."""
    out = []
    for k, v in items:
        lk = k.lower()
        if lk in HOP_BY_HOP or lk in ("content-length", "content-type", "content-encoding"):
            continue
        out.append((k, v))
    return out


def is_websocket_upgrade(headers):
    """True for a WebSocket upgrade request (Companion's tRPC /trpc channel)."""
    return (headers.get("Upgrade", "").lower() == "websocket"
            and "upgrade" in headers.get("Connection", "").lower())


def version_ge(ver_str, floor):
    """True if dotted ver_str (e.g. '4.1.0') >= floor tuple; False on None/unparseable."""
    try:
        parts = tuple(int(x) for x in ver_str.split(".")[:3])
    except (AttributeError, ValueError):
        return False
    return parts >= floor


def resolve_companion_base(bind_ip, tailscale_ip, port=8000):
    """Pick the local Companion admin base URL. A specific bind_ip (Companion bound to one
    interface, e.g. the Tailscale IP) is authoritative; 0.0.0.0/empty -> loopback; a missing
    bind_ip -> the Tailscale IP if known, else loopback."""
    host = (bind_ip or "").strip()
    if host and host != "0.0.0.0":
        pass
    elif host == "0.0.0.0":
        host = "127.0.0.1"
    else:
        host = (tailscale_ip or "").strip() or "127.0.0.1"
    return "http://%s:%d" % (host, port)
```

- [ ] **Step 4: Run the test to verify it passes** — `python3 tests/test_console_proxy.py` → `ALL PASS`.

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
- Modify: `src/scripts/console_policy.py` (one rule in `min_capability`, ~line 84, in the director block)
- Test: `tests/test_console.py` (alias `cp`, uses `cp.min_capability`/`cp.Requirement`/`cp.DIRECTOR`)

**Interfaces:** `min_capability(["buttons", ...])` → `Requirement(DIRECTOR, False)`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_console.py`:

```python
def t_buttons_requires_director_no_stepup():
    assert cp.min_capability(["buttons"]) == cp.Requirement(cp.DIRECTOR, False)
    assert cp.min_capability(["buttons", "tablet"]) == cp.Requirement(cp.DIRECTOR, False)
    assert cp.min_capability(["buttons", "trpc"]) == cp.Requirement(cp.DIRECTOR, False)
    assert cp.min_capability(["buttons", "health"]) == cp.Requirement(cp.DIRECTOR, False)


def t_buttons_commentator_forbidden_director_allowed():
    assert cp.decide({cp.COMMENTATOR}, ["buttons", "tablet"]) == cp.FORBIDDEN
    assert cp.decide({cp.DIRECTOR}, ["buttons", "tablet"]) == cp.ALLOW
```

- [ ] **Step 2: Run it to verify it fails** — `python3 tests/test_console.py` → FAIL (`min_capability(["buttons"])` is `None`).

- [ ] **Step 3: Write the implementation** — in `src/scripts/console_policy.py`, in the director block (after the `obs` rule ~line 74):

```python
    if p and p[0] == "buttons":                 # /console/buttons/* -> Companion proxy (#236)
        return Requirement(DIRECTOR, False)
```

- [ ] **Step 4: Run the test to verify it passes** — `python3 tests/test_console.py` → `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/console_policy.py tests/test_console.py
git commit -m "feat(console): route /console/buttons to the director capability (#236)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Relay HTTP proxy + Companion-address resolver + health + gate wiring

**Files:**
- Modify: `src/relay/racecast-feeds.py`
  - imports near `import console_policy` (~line 91): `import console_proxy`, `import install_apps`, `import companion_common`, `import tailscale`
  - `make_handler(...)` signature (~line 2861): add `companion_url=None`
  - add `_companion_base`, `_proxy_companion` (HTTP only here), `_buttons_health` methods in class `H`
  - `_console_gate` (~line 3031, after `whoami`): add the `buttons` branch
- Test: `tests/test_console_gate.py` (thread `companion_url` through `_serve`; add an HTTP stub upstream + tests)

**Interfaces:**
- Consumes: `console_proxy.*`, `install_apps.companion_http_version`, `companion_common.companion_config_path`, `tailscale.detect_tailscale_ip`, `console_policy.decide`.
- Produces: `_companion_base(self)->str`, `_proxy_companion(self, method)` (HTTP path), `_buttons_health(self)`; `make_handler` kwarg `companion_url`.

- [ ] **Step 1: Write the failing test** — in `tests/test_console_gate.py`, thread `companion_url` through `_serve` (add `companion_url=None` param and pass `companion_url=companion_url` into `m.make_handler(...)`), then add:

```python
from http.server import BaseHTTPRequestHandler


class _StubCompanion(BaseHTTPRequestHandler):
    last = {}
    def do_GET(self):
        _StubCompanion.last = {"path": self.path,
                               "prefix": self.headers.get("Companion-custom-prefix")}
        body = b"<html>companion web buttons</html>"
        self.send_response(200); self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass


def _stub_companion():
    srv = m.ThreadingHTTPServer(("127.0.0.1", 0), _StubCompanion)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def t_buttons_http_proxies_for_director():
    up = _stub_companion(); upurl = f"http://127.0.0.1:{up.server_address[1]}"
    srv = _serve(companion_url=upurl); port = srv.server_address[1]
    try:
        code, body = _get(port, "/console/buttons/tablet", _tok("bob"))   # director
        assert code == 200, (code, body)
        assert "companion web buttons" in body, body
        assert _StubCompanion.last["prefix"] == "console/buttons", _StubCompanion.last  # no slash
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

- [ ] **Step 2: Run it to verify it fails** — `python3 tests/test_console_gate.py` → FAIL (`make_handler() got an unexpected keyword argument 'companion_url'`).

- [ ] **Step 3: Write the implementation**

(a) Imports near `import console_policy`:

```python
import console_proxy      # pure /console/buttons proxy plumbing (#236)
import install_apps       # companion_http_version for the buttons health probe (#236)
import companion_common   # companion config.json path for bind-address resolution (#236)
import tailscale          # detect_tailscale_ip fallback for bind-address resolution (#236)
```

(b) `make_handler` signature — extend the last param line (~line 2861):

```python
                 console_page_path=None, companion_url=None):
```

(c) Methods in class `H` (after `_send_page`, ~line 2905):

```python
        def _companion_base(self):
            """Resolved Companion admin base URL. The make_handler `companion_url` override
            wins (tests / non-standard installs); otherwise resolve from Companion's own
            config.json bind_ip, then the Tailscale IP, then loopback (#236)."""
            if companion_url:
                return companion_url
            bind_ip = None
            try:
                import sys, json
                with open(companion_common.companion_config_path(sys.platform)) as fh:
                    bind_ip = (json.load(fh).get("bind_ip") or "").strip() or None
            except Exception:
                bind_ip = None
            return console_proxy.resolve_companion_base(bind_ip, tailscale.detect_tailscale_ip())

        def _proxy_companion(self, method):
            """Reverse-proxy a /console/buttons/* request to the local Companion (Option C,
            #236), director-gated by the caller. HTTP here; the WebSocket (tRPC /trpc) branch
            is added in the next task. Best-effort: never raises; unreachable Companion -> 502."""
            import urllib.request, urllib.error
            from urllib.parse import urlsplit
            base = self._companion_base()
            host = urlsplit(base).hostname or "127.0.0.1"
            url = base.rstrip("/") + console_proxy.upstream_path(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(length) if length else None
            hdrs = console_proxy.forward_request_headers(
                self.headers, host="%s:%d" % (host, urlsplit(base).port or 8000))
            req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    body, status = resp.read(), resp.status
                    out_headers = console_proxy.filter_response_headers(resp.headers.items())
                    ctype = resp.headers.get("Content-Type", "application/octet-stream")
            except urllib.error.HTTPError as e:
                body, status = e.read(), e.code
                out_headers = console_proxy.filter_response_headers(e.headers.items())
                ctype = e.headers.get("Content-Type", "application/octet-stream")
            except Exception as e:
                LOG.warning("Companion proxy failed: %s: %s", type(e).__name__, e)
                return self._send({"error": "Companion not reachable"}, 502)
            self.send_response(status)
            for k, v in out_headers:
                self.send_header(k, v)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)
            return None

        def _buttons_health(self):
            """Director-gated availability probe for the launcher: is Companion up and new
            enough (>= 4.1.0) to serve under the /console/buttons sub-path? (#236)"""
            import urllib.request
            base = self._companion_base()
            ver = install_apps.companion_http_version(base)
            reachable = ver is not None
            if not reachable:
                try:
                    urllib.request.urlopen(base.rstrip("/") + "/", timeout=2); reachable = True
                except Exception:
                    reachable = False
            ok = reachable and console_proxy.version_ge(ver, (4, 1, 0))
            return self._send({"reachable": reachable, "version": ver, "ok": ok})
```

(d) `_console_gate` — insert after the `whoami` block (after ~line 3031, before the page block):

```python
            # /console/buttons/* -> reverse-proxy to the local Companion (#236), director only.
            # 'buttons/health' is served by the relay (launcher availability probe) and shadows
            # that one upstream path (Companion's UI does not use /health).
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

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 tests/test_console_gate.py     # ALL PASS
python3 tests/test_tailscale.py        # boundary unchanged — still ALL PASS
```

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/relay/racecast-feeds.py tests/test_console_gate.py
git commit -m "feat(console): HTTP-proxy /console/buttons to a resolved Companion, director-gated (#236)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: WebSocket passthrough (mandatory — Companion tRPC `/trpc`)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`_proxy_companion`: handle the WS upgrade first)
- Test: `tests/test_console_gate.py` (a raw-socket upstream stub + a raw-socket client)

**Interfaces:**
- Consumes: `console_proxy.is_websocket_upgrade`, `console_proxy.upstream_path`, `console_proxy.forward_request_headers`, `self.connection` (the raw client socket).
- Produces: a transparent bidirectional byte relay for the `/trpc` WebSocket; any failure closes the upgrade.

- [ ] **Step 1: Write the failing test** — add to `tests/test_console_gate.py`:

```python
import socket as _socket


def _ws_echo_stub():
    """Raw-socket upstream: completes a 101 handshake, then echoes bytes."""
    srv = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    srv.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0)); srv.listen(1)
    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\n"
                         b"Upgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
            try:
                while True:
                    b = conn.recv(4096)
                    if not b:
                        break
                    conn.sendall(b)
            except OSError:
                pass
            conn.close()
    threading.Thread(target=serve, daemon=True).start()
    return srv


def t_buttons_ws_passthrough_for_director():
    up = _ws_echo_stub(); upurl = f"http://127.0.0.1:{up.getsockname()[1]}"
    srv = _serve(companion_url=upurl); port = srv.server_address[1]
    try:
        c = _socket.create_connection(("127.0.0.1", port), timeout=5)
        req = ("GET /console/buttons/trpc?t=%s HTTP/1.1\r\n"
               "Host: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n") % _tok("bob")
        c.sendall(req.encode())
        resp = c.recv(4096)
        assert resp.split(b"\r\n")[0].endswith(b"101 Switching Protocols"), resp
        c.sendall(b"hello-trpc")
        assert c.recv(4096) == b"hello-trpc"
        c.close()
    finally:
        srv.shutdown(); up.close()
```

- [ ] **Step 2: Run it to verify it fails** — `python3 tests/test_console_gate.py` → FAIL (the WS upgrade is currently treated as a normal HTTP GET; no `101` comes back, or the assert on the echo fails).

- [ ] **Step 3: Write the implementation** — at the **top** of `_proxy_companion`, before the urllib path, add the WS branch:

```python
            from urllib.parse import urlsplit as _urlsplit
            if console_proxy.is_websocket_upgrade(self.headers):
                import socket, select
                base = self._companion_base(); u = _urlsplit(base)
                host, cport = u.hostname or "127.0.0.1", u.port or 8000
                try:
                    up = socket.create_connection((host, cport), timeout=5)
                except OSError as e:
                    LOG.warning("Companion WS connect failed: %s", e)
                    return self._send({"error": "Companion not reachable"}, 502)
                # Replay the upgrade: rewritten path + the upgrade headers forwarded RAW
                # (Upgrade/Connection/Sec-WebSocket-* must survive) + injected prefix.
                hdrs = {k: v for k, v in self.headers.items()
                        if k.lower() not in ("host", "accept-encoding")}
                hdrs["Host"] = "%s:%d" % (host, cport)
                hdrs[console_proxy.COMPANION_PREFIX_HEADER] = console_proxy.PREFIX_HEADER_VALUE
                raw = ("GET %s HTTP/1.1\r\n" % console_proxy.upstream_path(self.path)
                       + "".join("%s: %s\r\n" % kv for kv in hdrs.items()) + "\r\n")
                up.sendall(raw.encode("latin-1"))
                client = self.connection
                try:
                    while True:
                        r, _, _ = select.select([client, up], [], [], 120)
                        if not r:
                            break
                        for s in r:
                            chunk = s.recv(65536)
                            if not chunk:
                                raise ConnectionError
                            (up if s is client else client).sendall(chunk)
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
git commit -m "feat(console): raw-WebSocket passthrough for the Companion tRPC channel (#236)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Launcher entry for directors

**Files:**
- Modify: `src/console/console.html` (the `<script>` block, lines 47–61)
- Test: `tests/test_console_gate.py` (assert the launcher carries the buttons wiring for directors)

**Interfaces:** Consumes `card()`, `RC_API()`, `/console/whoami` roles, and `GET /console/buttons/health`. Produces a director-only "Companion Buttons" card opening `/console/buttons/` in a new tab when `health.ok`, or a disabled "needs Companion ≥ 4.1" note when reachable-but-old.

- [ ] **Step 1: Write the failing test** — add to `tests/test_console_gate.py`:

```python
def t_console_launcher_has_buttons_wiring_for_director():
    srv = _serve(companion_url="http://127.0.0.1:1"); port = srv.server_address[1]
    try:
        code, body = _get(port, "/console", _tok("bob"))   # director
        assert code == 200, (code, body)
        assert "/buttons/health" in body, body
        assert "RC_API('/buttons/')" in body, body
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run it to verify it fails** — `python3 tests/test_console_gate.py` → FAIL on the new test (strings absent).

- [ ] **Step 3: Write the implementation** — in `src/console/console.html`, replace lines 53–57:

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

- [ ] **Step 4: Run the test to verify it passes** — `python3 tests/test_console_gate.py` → `ALL PASS`.

- [ ] **Step 5: Commit** (HTML only — no lint; no Control Center / Director Panel surface changed, so no wiki screenshot refresh)

```bash
git add src/console/console.html tests/test_console_gate.py
git commit -m "feat(console): launcher 'Companion Buttons' card for directors (#236)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Documentation — correct the security boundary honestly

**Files:** Modify `src/docs/wiki/Remote-access.md`, `src/docs/wiki/Architecture.md`, `src/docs/wiki/Companion.md`, `CLAUDE.md`. Test: none (verified by `tools/build.py` + a read).

- [ ] **Step 1: `Remote-access.md`** — change the "Companion stays on the tailnet / never exposed" claim. Add a "Companion web buttons over the Funnel (`/console/buttons`)" subsection:

```markdown
### Companion web buttons over the Funnel (`/console/buttons`)

A director can open their physical Companion button page in the browser over the Funnel at
`/console/buttons` (a card on the `/console` launcher, shown when Companion ≥ v4.1.0 is
running). The relay reverse-proxies it — HTTP for the page and assets, plus a transparent
WebSocket passthrough for Companion's realtime control channel — behind the **director token
gate**. The page needs no Tailscale account.

> **Security note (deliberate).** Companion has no real auth boundary by vendor design — its
> admin password "only stops casual browsers", and its realtime channel can export the full
> configuration without authentication (bitfocus/companion#3814, closed *won't-fix*). So an
> authenticated **director** reaching `/console/buttons` effectively has full control of that
> Companion, including a config export that may contain stored credentials. This is an
> accepted trade-off (we trust the director roster; a director on the tailnet already has the
> same access). Recommendations: do not store reusable secrets in a funnelled Companion
> (rotate the OBS-WebSocket password if it must live there); `racecast cockpit token revoke`
> rotates a leaked link at once. Only `/console` is Funnel-mounted — `/console/buttons` is a
> sub-path of that single mount, proxied internally; there is no second mount, and
> OBS-WebSocket is still never funnelled.
```

- [ ] **Step 2: `Architecture.md`** — in the control-flow/boundary section + diagram, add `/console/buttons → Companion` through the relay (director-gated; HTTP + WS). One line + a diagram edge `RELAY -. "director-gated buttons proxy (HTTP+WS)" .-> COMP`.

- [ ] **Step 3: `Companion.md`** — alongside the existing Tailscale remote-access path, add an "Over the Funnel" note pointing to `/console/buttons` and [Remote access](Remote-access), with the Companion ≥ v4.1.0 requirement.

- [ ] **Step 4: `CLAUDE.md`** — in the relay/cockpit section, reconcile "only `/console` is funnel-mounted" with the new sub-path proxy: `/console/buttons` reverse-proxies (HTTP + a raw-WebSocket passthrough for Companion's tRPC `/trpc`) to the resolved local Companion bind address, director-gated (#236); it is a sub-path of the single `/console` mount (no second mount); OBS-WebSocket remains never funnelled.

- [ ] **Step 5: Commit**

```bash
git add src/docs/wiki/Remote-access.md src/docs/wiki/Architecture.md src/docs/wiki/Companion.md CLAUDE.md
git commit -m "docs(wiki): document Companion buttons over Funnel + the boundary change (#236)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification (after the last task)

- [ ] `python3 tools/run-tests.py` → whole suite green.
- [ ] `python3 tools/lint.py` → clean.
- [ ] `python3 tools/build.py` → exits 0 (verify step ≈ CI).
- [ ] Manual: with a real Companion ≥ v4.1.0 + `racecast funnel on`, open `https://<host>/console` as a director → "Companion Buttons" card → opens the live web-buttons page (button colours live, a press actuates Companion). Confirm `https://<host>/status` and `/panel` (root) are NOT publicly reachable (boundary intact).
