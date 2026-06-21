# Centralized outbound-HTTP helper + User-Agent guard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every covered module's outbound HTTP through one helper that always sends a racecast `User-Agent`, and add a guard test that makes a bare `urllib` request impossible on the covered side.

**Architecture:** A new stdlib-only `src/scripts/http_util.py` exposes `open_url`/`get_bytes`/`get_json`/`post_json` (UA always injected, caller headers win) and re-exports `HTTPError`. The CLI/scripts callers migrate to it; a guard test scans the covered files for `urlopen`/`urllib.request` and fails if found. The relay, the self-contained `get-*`/`setup-assets` scripts, and `update.py` are excluded (documented).

**Tech Stack:** Python 3 stdlib only (`urllib`). Tests are runnable stdlib scripts (no pytest), discovered by `tools/run-tests.py`.

## Global Constraints

- Edit only under `src/` and `tests/` (plus `docs/` and `CLAUDE.md`). English only. stdlib only — no new deps.
- Canonical UA: `RACECAST_UA = "racecast/1.0"`. A caller-supplied `User-Agent` header MUST override it (the Google-Fonts fetch deliberately sends a browser UA).
- Behavior preserved per call: keep each site's original `timeout` (pass it explicitly), original extra headers, and `HTTPError` still raised.
- Covered files (guard-enforced): `src/racecast.py`, `src/ui/ui_server.py`, `src/scripts/installer_common.py`, `src/scripts/install_tools.py`, `src/scripts/install_apps.py`, `src/scripts/funnel_setup.py`, `src/scripts/obs_browser_linux.py`, `src/scripts/preflight.py`.
- Excluded (NOT migrated): the relay (`src/relay/racecast-feeds.py`), `src/relay/get-graphics.py`, `src/relay/get-media.py`, `src/setup-assets.py` (self-contained, dependency-light, already UA-compliant), and `src/scripts/update.py` (custom HTTPS-only redirect opener + test seam; already sets a UA).
- `urllib.parse` and `urllib.error` are allowed in covered files; only `urlopen` and `urllib.request` are banned.
- After every Python change run `python3 tools/lint.py` (must pass).

---

### Task 1: The `http_util` helper

**Files:**
- Create: `src/scripts/http_util.py`
- Create: `tests/test_http_util.py`

**Interfaces:**
- Produces:
  - `RACECAST_UA: str` (= `"racecast/1.0"`)
  - `HTTPError` (re-export of `urllib.error.HTTPError`)
  - `open_url(url, *, data=None, headers=None, method=None, timeout=10)` → urllib response (context manager); UA always set, caller headers override; raises `HTTPError`.
  - `get_bytes(url, *, headers=None, timeout=10) -> bytes`
  - `get_json(url, *, headers=None, timeout=10)` → parsed JSON
  - `post_json(url, obj, *, headers=None, timeout=10) -> bytes` (sets `Content-Type: application/json`, JSON-encodes `obj`)
  - Module-level `urlopen`/`Request` (imported from `urllib.request`) so tests can patch `http_util.urlopen`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_http_util.py`:

```python
#!/usr/bin/env python3
"""Stdlib checks for the shared outbound-HTTP helper. Run: python3 tests/test_http_util.py"""
import importlib.util, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
spec = importlib.util.spec_from_file_location(
    "http_util", os.path.join(ROOT, "src", "scripts", "http_util.py"))
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)


class _Resp:
    def __init__(self, body=b""): self._b = body
    def read(self, n=None): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _capture(body=b""):
    """Patch http_util.urlopen; return (calls, restore). calls[i] = (Request, timeout)."""
    calls = []
    def fake(req, timeout=None):
        calls.append((req, timeout))
        return _Resp(body)
    orig = h.urlopen
    h.urlopen = fake
    return calls, (lambda: setattr(h, "urlopen", orig))


def t_ua_constant_is_not_default_urllib():
    assert h.RACECAST_UA and "urllib" not in h.RACECAST_UA.lower()


def t_open_url_always_sets_user_agent():
    calls, restore = _capture()
    try:
        with h.open_url("https://x/y", timeout=4):
            pass
    finally:
        restore()
    req, timeout = calls[0]
    assert req.get_header("User-agent") == h.RACECAST_UA
    assert timeout == 4


def t_caller_user_agent_overrides_default():
    calls, restore = _capture()
    try:
        h.get_bytes("https://x/y", headers={"User-Agent": "Mozilla/5.0 ua"})
    finally:
        restore()
    assert calls[0][0].get_header("User-agent") == "Mozilla/5.0 ua"


def t_extra_headers_merge_keep_ua():
    calls, restore = _capture()
    try:
        h.get_bytes("https://x/y", headers={"Range": "bytes=0-9"})
    finally:
        restore()
    req = calls[0][0]
    assert req.get_header("User-agent") == h.RACECAST_UA
    assert req.get_header("Range") == "bytes=0-9"


def t_get_json_parses():
    calls, restore = _capture(body=b'{"a": 1}')
    try:
        assert h.get_json("https://x/y") == {"a": 1}
    finally:
        restore()


def t_post_json_sets_content_type_and_body():
    calls, restore = _capture()
    try:
        h.post_json("https://x/y", {"k": "v"})
    finally:
        restore()
    req = calls[0][0]
    assert req.get_header("Content-type") == "application/json"
    assert json.loads(req.data.decode("utf-8")) == {"k": "v"}
    assert req.get_method() == "POST"
    assert req.get_header("User-agent") == h.RACECAST_UA


def t_httperror_is_reexported_and_propagates():
    assert h.HTTPError is __import__("urllib.error", fromlist=["HTTPError"]).HTTPError
    def boom(req, timeout=None):
        raise h.HTTPError("https://x", 403, "Forbidden", {}, None)
    orig = h.urlopen; h.urlopen = boom
    try:
        h.get_bytes("https://x")
        raise AssertionError("expected HTTPError")
    except h.HTTPError as e:
        assert e.code == 403
    finally:
        h.urlopen = orig


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_http_util.py`
Expected: FAIL — `FileNotFoundError`/import error (no `src/scripts/http_util.py` yet).

- [ ] **Step 3: Create the helper**

Create `src/scripts/http_util.py`:

```python
#!/usr/bin/env python3
"""The one place racecast's CLI/scripts side issues outbound HTTP.

Every request carries an explicit User-Agent: Cloudflare-fronted hosts (Discord,
Google Fonts, some vendor endpoints) reject the default `Python-urllib/x.y` UA with
HTTP 403, so a bare urllib call silently fails. Routing all covered-module HTTP
through here makes "forgetting the UA" structurally impossible (enforced by
tests/test_http_util.py). The relay and the self-contained get-*/setup-assets
scripts keep their own UA — they are intentionally dependency-light and excluded."""
import json
import urllib.error
from urllib.request import Request, urlopen   # module-level so tests can patch http_util.urlopen

RACECAST_UA = "racecast/1.0"
DEFAULT_TIMEOUT = 10
HTTPError = urllib.error.HTTPError            # re-export: callers never import urllib to catch


def open_url(url, *, data=None, headers=None, method=None, timeout=DEFAULT_TIMEOUT):
    """Return the urllib response (use in a `with`). RACECAST_UA is always set; a
    caller-supplied User-Agent in `headers` overrides it. Raises HTTPError on
    4xx/5xx exactly like urllib. `timeout=None` means no timeout."""
    merged = {"User-Agent": RACECAST_UA}
    if headers:
        merged.update(headers)
    req = Request(url, data=data, headers=merged, method=method)
    return urlopen(req, timeout=timeout)        # noqa: S310 — UA-stamped; covered-module HTTP funnels here


def get_bytes(url, *, headers=None, timeout=DEFAULT_TIMEOUT):
    with open_url(url, headers=headers, timeout=timeout) as r:
        return r.read()


def get_json(url, *, headers=None, timeout=DEFAULT_TIMEOUT):
    return json.loads(get_bytes(url, headers=headers, timeout=timeout).decode("utf-8"))


def post_json(url, obj, *, headers=None, timeout=DEFAULT_TIMEOUT):
    merged = {"Content-Type": "application/json"}
    if headers:
        merged.update(headers)
    with open_url(url, data=json.dumps(obj).encode("utf-8"), headers=merged,
                  method="POST", timeout=timeout) as r:
        return r.read()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_http_util.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/http_util.py tests/test_http_util.py
git commit -m "feat(http): central outbound-HTTP helper with a guaranteed User-Agent"
```

---

### Task 2: Migrate the `src/scripts/*` callers

**Files:**
- Modify: `src/scripts/installer_common.py`, `src/scripts/install_tools.py`, `src/scripts/install_apps.py`, `src/scripts/funnel_setup.py`, `src/scripts/obs_browser_linux.py`, `src/scripts/preflight.py`
- Modify (test repoint): `tests/test_installer_common.py`, `tests/test_preflight.py`

**Interfaces:**
- Consumes: `http_util.open_url`, `http_util.get_bytes` (Task 1). Each file gains `import http_util` (sibling import; `src/scripts` is on `sys.path` in production, the frozen binary, and the test loaders).

- [ ] **Step 1: Migrate `installer_common.py`**

Replace the `INSTALLER_UA` constant + `_fetch` (lines ~16-25). Remove `import urllib.request` from `_fetch`; add `import http_util` to the module's top imports (the `import os, shutil, subprocess` line region). New `_fetch`:

```python
def _fetch(url, timeout):
    """GET `url` over cert-verified HTTPS with a real User-Agent, returning the body."""
    return http_util.get_bytes(url, timeout=timeout)
```

Delete the now-unused `INSTALLER_UA = "racecast-installer/1.0"` line and its comment (it is referenced nowhere else — verified by grep). Add near the existing imports:

```python
import http_util
```

- [ ] **Step 2: Migrate `install_tools.py`**

There are two default-opener closures (the speedtest download ~line 101 and the deno download ~line 170). Each looks like:

```python
    if opener is None:
        import urllib.request
        def opener(url):
            with urllib.request.urlopen(url, timeout=60) as resp:  # nosec ...
                return resp.read()
```

Replace each with (keep the original per-site timeout — 60 for speedtest, 120 for deno):

```python
    if opener is None:
        def opener(url):
            return http_util.get_bytes(url, timeout=60)   # deno site: timeout=120
```

Add `import http_util` to the module's top imports. (The `opener=` test seam is untouched — tests pass their own `opener`, so they never reach `http_util`.)

- [ ] **Step 3: Migrate `install_apps.py`**

Replace `_http_fetch` (lines ~289-294). Remove `import urllib.request`; add `import http_util` to the top imports. New body:

```python
def _http_fetch(url, range_bytes):
    """GET `url` (optionally only its first `range_bytes`) and return the decoded
    body. Short timeout; raises on any failure (callers treat that as 'unknown')."""
    headers = {"Range": f"bytes=0-{range_bytes - 1}"} if range_bytes else None
    with http_util.open_url(url, headers=headers, timeout=4) as resp:
        body = resp.read(range_bytes) if range_bytes else resp.read()
    return body.decode("utf-8", "replace")
```

- [ ] **Step 4: Migrate `funnel_setup.py`**

Remove `import urllib.request` (line 16); keep `import urllib.error` and `import urllib.parse`. Add `import http_util`. In `_req` (lines ~75-77) replace:

```python
    with http_util.open_url(API + path, data=data, headers=headers,
                            method=method, timeout=timeout) as r:
        return r.status, dict(r.headers), r.read()
```

(The `Request` line is removed; `open_url` builds it.)

- [ ] **Step 5: Migrate `obs_browser_linux.py`**

In the top import line `import hashlib, os, shutil, subprocess, sys, tempfile, urllib.request`, remove `urllib.request` and add a separate `import http_util`. Replace `_download` (line ~209) — preserve the original NO-timeout behavior with `timeout=None` (the CEF download is large):

```python
def _download(url, dest):
    print(f"  downloading {url}")
    with http_util.open_url(url, timeout=None) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
```

- [ ] **Step 6: Migrate `preflight.py`**

Remove `from urllib.request import Request, urlopen` (line 25); keep `from urllib.error import HTTPError, URLError` (line 23) and `from urllib.parse import quote` (line 24). Add `import http_util` to the imports. Replace the request (lines ~288-289):

```python
        with http_util.open_url(url, timeout=timeout) as resp:
            return "ok", resp.read().decode("utf-8", "replace")
```

(The `Request(... User-Agent: racecast-preflight/1.0)` line is removed; the helper sets the UA. The `except HTTPError` / `except URLError` handlers are unchanged — `http_util.open_url` raises the same `urllib.error` classes.)

- [ ] **Step 7: Repoint the two coupled tests**

In `tests/test_installer_common.py`, `_capture_request` (lines ~105-121) patches `urllib.request.urlopen`; repoint it to patch `http_util.urlopen`. At the top loader (after the `sys.path.insert(... "src","scripts")` line) add:

```python
import http_util
```

Then in `_capture_request` replace the patch target — change `urllib.request.urlopen = fake_urlopen` / the `orig_open, ... = urllib.request.urlopen, ...` save+restore to use `http_util`:

```python
    orig_open, orig_call = http_util.urlopen, m.subprocess.call
    http_util.urlopen = fake_urlopen
    # ... run ...
    finally:
        http_util.urlopen, m.subprocess.call = orig_open, orig_call
```

In `tests/test_preflight.py`, two tests patch `m.urlopen` (lines ~285-286 and ~300-301). Add `import http_util` at the loader top (after the `sys.path.insert` for `src/scripts`, if present; otherwise add `sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))` then `import http_util`). Repoint both:

```python
    orig = http_util.urlopen
    http_util.urlopen = boom
    # ...
    finally:
        http_util.urlopen = orig
```

(The `boom` that raises `urllib.error.HTTPError(... 403 ...)` still flows through `open_url` to preflight's `except HTTPError`, so the "forbidden" assertion holds.)

- [ ] **Step 8: Run the affected tests + lint**

Run each and expect `ALL PASS`:

```bash
python3 tests/test_installer_common.py
python3 tests/test_install_tools.py
python3 tests/test_install_apps.py
python3 tests/test_preflight.py
python3 tools/lint.py
```

- [ ] **Step 9: Commit**

```bash
git add src/scripts/installer_common.py src/scripts/install_tools.py \
        src/scripts/install_apps.py src/scripts/funnel_setup.py \
        src/scripts/obs_browser_linux.py src/scripts/preflight.py \
        tests/test_installer_common.py tests/test_preflight.py
git commit -m "refactor(http): route src/scripts HTTP callers through http_util"
```

---

### Task 3: Migrate `racecast.py` + `ui_server.py`

**Files:**
- Modify: `src/racecast.py` (9 sites), `src/ui/ui_server.py` (1 site)

**Interfaces:**
- Consumes: `http_util.open_url`, `get_bytes`, `get_json`, `post_json` (Task 1).
- No test changes: `tests/test_racecast.py` patches whole functions (`m._relay_fetch_json`, `m._takeover_get`, `m._post_discord_webhook`); `tests/test_ui_server.py` patches its own `_urlopen`. Neither touches the migrated internals.

- [ ] **Step 1: Add the import to `racecast.py`**

After `import config as pcfg` (line ~45), add:

```python
import http_util
```

- [ ] **Step 2: Migrate the nine `racecast.py` sites**

`_fetch_relay_page` (~740):

```python
def _fetch_relay_page(path):
    return http_util.get_bytes(f"http://127.0.0.1:{RELAY_PORT}{path}", timeout=3)
```

`chat_cmd` (~981, ~1046): remove `import urllib.request as _u`; change the pull block:

```python
        try:
            with http_util.open_url(url, timeout=5) as resp:
                if resp.status != 200:
                    sys.exit(f"racecast: pull failed — HTTP {resp.status} from {host}")
                payload = json.loads(resp.read())
```

`_post_chat_message` (~1145):

```python
def _post_chat_message(text):
    """Best-effort POST of one crew-chat message to the local relay."""
    http_util.post_json(f"http://127.0.0.1:{RELAY_PORT}/chat/send",
                        {"user": "Producer", "text": text}, timeout=3)
```

The cockpit/versions pull (~1256-1260) — inside its existing `try`:

```python
    secret = os.environ.get("RACECAST_CONSOLE_SECRET") or ""
    try:
        payload = http_util.get_json(f"http://{host}:{port}/cockpit/versions",
                                     headers={"X-Console-Secret": secret}, timeout=5)
    except Exception as exc:
```

The `/status` ping (~1431-1433):

```python
    try:
        # .read() drains the socket; we only care whether the request succeeds
        http_util.get_bytes(f"http://127.0.0.1:{RELAY_PORT}/status", timeout=3)
        return True
    except Exception:
        return False
```

`_relay_fetch_json` (~1441):

```python
def _relay_fetch_json(url, timeout=3):
    """GET a relay control-server endpoint and parse its JSON body."""
    return http_util.get_json(url, timeout=timeout)
```

`_takeover_get` (~1468):

```python
def _takeover_get(url, secret=None, timeout=5):
    """GET a (funnel) takeover endpoint with the step-up secret header. Raises
    HTTPError on 401/403 (bad secret) so the caller can distinguish auth
    rejection from a network failure."""
    headers = {"X-Console-Secret": secret} if secret else None
    return http_util.get_json(url, headers=headers, timeout=timeout)
```

`_relay_post_json` (~1478):

```python
def _relay_post_json(url, payload, timeout=3):
    """POST a JSON body to a relay control-server endpoint and parse its JSON
    reply (the write sibling of _relay_fetch_json)."""
    return json.loads(http_util.post_json(url, payload, timeout=timeout).decode("utf-8"))
```

`_http_get` (~4045): remove `import urllib.request` and the `# noqa: S310`; a caller-supplied `User-Agent` (the `_GOOGLE_FONT_UA` browser string) overrides the default via the helper merge:

```python
def _http_get(url, headers=None, binary=False, timeout=15):
    data = http_util.get_bytes(url, headers=headers or None, timeout=timeout)
    return data if binary else data.decode("utf-8", "replace")
```

Leave `_ts_api_err`'s `import urllib.error` (~3413) as-is — `urllib.error` is allowed by the guard.

- [ ] **Step 3: Migrate `ui_server.py`**

After `import logsetup` (line 11) add `import http_util`. Replace `_fetch_ping` (~50-51):

```python
def _fetch_ping(host, port):
    return http_util.get_bytes(f"http://{host}:{port}/api/ping", timeout=2)
```

- [ ] **Step 4: Run the affected tests + lint**

```bash
python3 tests/test_racecast.py
python3 tests/test_ui_server.py
python3 tools/lint.py
```
Expected: `ALL PASS` for both, lint clean.

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py src/ui/ui_server.py
git commit -m "refactor(http): route racecast + Control Center HTTP through http_util"
```

---

### Task 4: Enforcement guard + docs

**Files:**
- Modify: `tests/test_http_util.py` (add the scan)
- Modify: `CLAUDE.md` (update the hard rule + Commands list)

**Interfaces:** none (guard + docs).

- [ ] **Step 1: Add the enforcement scan test**

Append to `tests/test_http_util.py` (before the `__main__` block):

```python
# The covered modules must not issue a bare urllib request — everything goes
# through http_util so the User-Agent can never be forgotten. urllib.parse /
# urllib.error stay allowed; only `urlopen` and `urllib.request` are banned.
_COVERED = [
    ("src", "racecast.py"),
    ("src", "ui", "ui_server.py"),
    ("src", "scripts", "installer_common.py"),
    ("src", "scripts", "install_tools.py"),
    ("src", "scripts", "install_apps.py"),
    ("src", "scripts", "funnel_setup.py"),
    ("src", "scripts", "obs_browser_linux.py"),
    ("src", "scripts", "preflight.py"),
]


def t_covered_files_have_no_bare_urllib():
    for parts in _COVERED:
        text = open(os.path.join(ROOT, *parts), encoding="utf-8").read()
        for banned in ("urlopen", "urllib.request"):
            assert banned not in text, f"{'/'.join(parts)} still uses {banned!r}"
```

- [ ] **Step 2: Run it to verify it passes**

Run: `python3 tests/test_http_util.py`
Expected: `ALL PASS` (Tasks 2-3 already removed every `urlopen`/`urllib.request` from the covered files). If it fails, the named file still has a bare call — migrate it.

- [ ] **Step 3: Update CLAUDE.md**

Replace the User-Agent hard-rule bullet (the one starting "**Outbound HTTP to an external service MUST send an explicit `User-Agent`.**") with a version that points at the helper and the guard:

```markdown
- **Outbound HTTP goes through `src/scripts/http_util.py`** (the covered side:
  `racecast.py`, `ui_server.py`, `src/scripts/*`). It always sends a racecast
  `User-Agent`; Discord and other Cloudflare-fronted hosts (Google Fonts, some
  vendor endpoints) 403 the default `Python-urllib/x.y` UA, so a bare `urllib`
  call silently fails. `tests/test_http_util.py` enforces this — it fails if a
  covered file uses `urlopen`/`urllib.request` directly. Exceptions, each
  already setting its own UA: the self-contained relay/`get-*`/`setup-assets`
  scripts (deliberately dependency-light, must not import shared modules) and
  `src/scripts/update.py` (needs its own HTTPS-only redirect opener + test seam).
```

Add to the Commands test list (near `tests/test_installer_common.py`):

```markdown
python3 tests/test_http_util.py     # shared outbound-HTTP helper + User-Agent guard
```

- [ ] **Step 4: Full suite + lint**

```bash
python3 tools/run-tests.py
python3 tools/lint.py
```
Expected: `ALL TEST FILES PASS` and lint clean.

- [ ] **Step 5: Commit**

```bash
git add tests/test_http_util.py CLAUDE.md
git commit -m "test(http): guard covered modules against bare urllib; document the helper"
```

---

### Final verification

- [ ] **Build self-verify (closest thing to CI for shipped artifacts):**

```bash
python3 tools/build.py
```
Expected: build + verify succeed (no shell scripts, tokenization, etc.). Pre-existing "graphic … MISSING" warnings are expected (runtime-downloaded) and do not fail the build.

## Self-Review notes

- **Spec coverage:** helper module → Task 1; migration of covered files → Tasks 2-3; `update.py`/relay exclusions → honored (not in `_COVERED`, documented in Task 4 CLAUDE.md); guard test → Task 4; caller-UA-override (Google Fonts) → helper merge + `t_caller_user_agent_overrides_default` + `_http_get` migration; docs/Commands → Task 4. All covered.
- **Type/name consistency:** `open_url`/`get_bytes`/`get_json`/`post_json`/`RACECAST_UA`/`HTTPError`/module-level `urlopen` are defined in Task 1 and used identically in Tasks 2-4; the guard's `_COVERED` list matches the Global Constraints covered set exactly.
- **No-network tests:** the helper tests patch `http_util.urlopen`; the repointed `test_installer_common`/`test_preflight` patch the same symbol; no test hits the network.
- **Behavior preserved:** every migrated site keeps its original timeout (3/5/2/4/60/120/None) and headers; `obs_browser_linux` uses `timeout=None` to preserve its original no-timeout download.
