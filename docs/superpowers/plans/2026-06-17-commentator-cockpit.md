# Commentator Cockpit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a talent-facing `/cockpit/*` page on the relay — authenticated per-commentator (HMAC token), served publicly via Tailscale Funnel — giving each commentator a live program monitor, an "ON AIR / UP NEXT" tally, embedded crew chat, and the race timer (GitHub issue #191).

**Architecture:** A new auth-gated `/cockpit/*` namespace on the existing relay `ThreadingHTTPServer`. Tailscale Funnel maps **only** the `/cockpit` path prefix to `127.0.0.1:8088`; the rest of the relay stays tailnet/loopback-only and is never funnelled. Auth is 100% server-side (Funnel passes no Tailscale identity): a per-league secret `COCKPIT_SECRET` signs a self-describing per-commentator token `<streamer_key>.<version>.<sig>`; a machine-local `cockpit-versions.json` enables revocation by bumping a streamer's version. Tally is derived from the on-air feed (`/status` `live` block) joined to the live schedule via `asset_key`-normalised streamer names. ~80% of the surface reuses already-shipped pieces (`get_program_screenshot` from #190, `ChatStore`, `TimerStore`, `live_schedule_row`).

**Tech Stack:** Pure Python 3 + stdlib (`hmac`, `hashlib`, `secrets`, `http.cookies`, `http.server`); no framework, no third-party deps. Tests are stdlib runnable scripts (no pytest). Tailscale Funnel via the `tailscale` CLI.

---

## Decisions & assumptions (read first)

These resolve the issue's open questions from the **approved design comment**
(<https://github.com/jegr78/gt-endurance-racing-broadcast/issues/191#issuecomment-4721314093>).
Where the issue body and the approved comment differ, **the approved comment wins**.

1. **Two-knob gating.** `COCKPIT_SECRET` is a **per-league** value in
   `profiles/<name>/profile.env` (travels with `profile export`/import). `COCKPIT_ENABLED`
   is a **machine-local** `true/false` flag in `.env`. `/cockpit/*` is live **only** when
   **both** are present/true; otherwise every `/cockpit/*` path returns **404** (identical
   to chat/timer when disabled). Funnel exposure (`cockpit funnel on`) is a *separate*
   public-ingress switch layered on top.
2. **Token format (verbatim from the spec):**
   `token = "<streamer_key>.<version>.<sig>"` where
   `streamer_key = asset_key(streamer_name)` (URL-safe `[a-z0-9-]`),
   `version` is an integer (default 1), and
   `sig = HMAC_SHA256(COCKPIT_SECRET, "<streamer_key>:<version>")` hex, **truncated to
   128 bits (32 hex chars)**.
3. **No token→name map stored.** A valid signature *is* proof of identity. Revocation state
   is the only token state: `runtime/<profile>/cockpit-versions.json` =
   `{streamer_key: current_version}` (default 1 when absent). A token whose `version` is
   below the streamer's current version is rejected.
4. **Transport:** link is `…/cockpit?t=<token>`. The page response sets an
   `HttpOnly; Secure; SameSite=Lax` cookie `rc_cockpit=<token>`; all sub-requests
   authenticate via that cookie. Tokens are never logged.
5. **`asset_key` duplication.** `cockpit_auth.streamer_key()` duplicates the relay's
   `asset_key()` byte-for-byte and is pinned equal by a cross-check test (the same idiom as
   `STREAMLINK_TWITCH` in `tests/test_streams.py`). This keeps `src/scripts/cockpit_auth.py`
   free of any import of the hyphenated relay module.
6. **Curated data only.** `/cockpit/data` returns
   `{me, on_air, up_next, scheduled, program_available, mode}` — never stream URLs, never
   raw `/status`.
7. **English only, edit only under `src/`, no secrets/paths in git, tests run anywhere with
   no real IPs** (Tailscale fixtures use the `100.64.0.0/10` range) — per CLAUDE.md.

---

## File structure

**New files**
- `src/scripts/cockpit_auth.py` — pure auth core: `streamer_key`, `mint_token`,
  `verify_token`, version-store load/current/bump, `parse_cookie_token`, `RateLimiter`.
- `src/scripts/cockpit_admin.py` — version-store persistence + takeover pull
  (`validate_versions`, `write_versions`, `apply_pulled`), mirroring `chat_admin.py`.
- `src/cockpit/cockpit.html` — the talent page (program monitor + tally + chat + timer).
- `tests/test_cockpit.py` — auth + tally + endpoint + admin unit checks.

**Modified files**
- `src/relay/racecast-feeds.py` — `cockpit_tally` + `cockpit_display_name` pure helpers;
  `make_handler` gains cockpit kwargs and the `/cockpit/*` routes; `main()` resolves the
  page path + secret/enabled/versions path and passes them in.
- `src/scripts/config.py` — `ResolvedConfig.cockpit_secret`; parse `COCKPIT_SECRET`.
- `src/racecast.py` — `_profile_env_vars` injects `RACECAST_COCKPIT_SECRET`; new
  `cockpit_cmd` group; takeover pulls versions; Control Center `ctx` data functions.
- `src/scripts/tailscale.py` — `tailscale_funnel_on` / `tailscale_funnel_off` wrappers.
- `src/ui/ui_server.py` + `src/ui/control-center.html` — Cockpit section (routes + UI).
- `profiles/example/profile.env` — documented `COCKPIT_SECRET=` line.
- `.env.example` — documented `RACECAST_COCKPIT_ENABLED=` line.
- `src/docs/wiki/images/cc-cockpit.png` (+ a wiki page) — Control Center screenshot.
- `README.md` / `CLAUDE.md` command list — `racecast cockpit …`.

---

## Milestones

- **M1 — Relay core (Tasks 1–9):** auth core, tally, `/cockpit/*` endpoints, the talent
  page, config + relay wiring. Produces a working, **tailnet-reachable** authenticated
  cockpit. Fully TDD'd.
- **M2 — CLI & Funnel & takeover (Tasks 10–14):** `racecast cockpit` command group,
  the `tailscale funnel` wrapper (public ingress), version revocation, takeover pull.
- **M3 — Control Center & docs (Tasks 15–18):** Cockpit settings section, wiki screenshot,
  docs.

Each milestone ends green (`python3 tools/run-tests.py` + `python3 tools/lint.py`).

---

# Milestone 1 — Relay core

### Task 1: Auth core — `streamer_key` + `mint_token` + `verify_token`

**Files:**
- Create: `src/scripts/cockpit_auth.py`
- Test: `tests/test_cockpit.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cockpit.py` with the standard bootstrap and the first cases:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the Commentator Cockpit. Run: python3 tests/test_cockpit.py"""
import importlib.util
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ca = _load("cockpit_auth", ("src", "scripts", "cockpit_auth.py"))

SECRET = "test-secret-do-not-ship"


def t_streamer_key_normalizes():
    assert ca.streamer_key("Alpha Racing") == "alpha-racing"
    assert ca.streamer_key("  Beta!#1  ") == "beta1"
    assert ca.streamer_key("") == ""
    assert ca.streamer_key(None) == ""


def t_mint_token_shape():
    tok = ca.mint_token(SECRET, "alpha-racing", version=1)
    key, ver, sig = tok.split(".")
    assert key == "alpha-racing"
    assert ver == "1"
    assert len(sig) == 32 and all(c in "0123456789abcdef" for c in sig)


def t_verify_round_trip():
    tok = ca.mint_token(SECRET, "alpha-racing")
    assert ca.verify_token(SECRET, tok) == "alpha-racing"


def t_verify_rejects_tampered_sig():
    tok = ca.mint_token(SECRET, "alpha-racing")
    bad = tok[:-1] + ("0" if tok[-1] != "0" else "1")
    assert ca.verify_token(SECRET, bad) is None


def t_verify_rejects_wrong_secret():
    tok = ca.mint_token(SECRET, "alpha-racing")
    assert ca.verify_token("other-secret", tok) is None


def t_verify_rejects_malformed():
    for bad in ("", "a.b", "a.b.c.d", "alpha.notint.deadbeef" + "0" * 24,
                "BADKEY.1." + "0" * 32, "a." * 0 + "alpha-racing.1.short"):
        assert ca.verify_token(SECRET, bad) is None, bad


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 tests/test_cockpit.py`
Expected: `ModuleNotFoundError`/`AttributeError` (file/functions missing).

- [ ] **Step 3: Write the minimal implementation**

Create `src/scripts/cockpit_auth.py`:

```python
"""Commentator-cockpit auth core (issue #191) — pure, stdlib-only, importable by
both the relay (src/relay/racecast-feeds.py) and the CLI (src/racecast.py) WITHOUT
importing the hyphenated relay module.

Token model (per the approved design):
    token = "<streamer_key>.<version>.<sig>"
    streamer_key = streamer_key(name)                 # URL-safe [a-z0-9-]
    sig = HMAC_SHA256(secret, "<streamer_key>:<version>") hex, truncated to 128 bits.
A valid signature IS proof the request is that streamer — no token->name map is stored.
Revocation is a per-streamer integer version (see cockpit_admin.py): a token whose
version is below the streamer's current version is rejected.
"""
import hashlib
import hmac
import re
import time
from http.cookies import SimpleCookie

COOKIE_NAME = "rc_cockpit"
_KEY_RE = re.compile(r"[a-z0-9-]+")


def streamer_key(s):
    """Normalize a streamer name to a URL-safe key. DUPLICATE of
    racecast-feeds.asset_key() — pinned byte-identical by a cross-check test in
    tests/test_cockpit.py (same idiom as STREAMLINK_TWITCH). Keep them in sync."""
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    return re.sub(r"[^a-z0-9-]", "", s)


def _sign(secret, key, version):
    msg = f"{key}:{version}".encode("utf-8")
    full = hmac.new((secret or "").encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return full[:32]                       # 128-bit truncation -> shorter link


def mint_token(secret, key, version=1):
    """Build a signed token for an already-normalized streamer_key."""
    return f"{key}.{int(version)}.{_sign(secret, key, int(version))}"


def verify_token(secret, token, versions=None):
    """Return the streamer_key iff the token's signature is valid (constant-time)
    AND, when *versions* is given, its version is current. None on any failure.
    *versions* is the {streamer_key: current_version} dict (default 1 when absent)."""
    if not token or not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    key, ver_s, sig = parts
    if not key or not _KEY_RE.fullmatch(key):
        return None
    try:
        version = int(ver_s)
    except ValueError:
        return None
    expected = _sign(secret, key, version)
    if not hmac.compare_digest(sig, expected):
        return None
    if versions is not None and version < int(versions.get(key, 1)):
        return None
    return key


def parse_cookie_token(cookie_header):
    """Extract the rc_cockpit token from a raw Cookie header, or None. Pure."""
    if not cookie_header:
        return None
    try:
        jar = SimpleCookie()
        jar.load(cookie_header)
    except Exception:
        return None
    morsel = jar.get(COOKIE_NAME)
    return morsel.value if morsel else None


class RateLimiter:
    """Fixed-window per-key counter (auth failures, chat sends). Time-injectable
    so tests are deterministic. Best-effort, in-process only."""

    def __init__(self, limit, window_s):
        self.limit = limit
        self.window_s = window_s
        self._hits = {}                    # key -> [window_start, count]

    def allow(self, key, now=None):
        now = time.time() if now is None else now
        start, count = self._hits.get(key, (now, 0))
        if now - start >= self.window_s:
            start, count = now, 0
        count += 1
        self._hits[key] = (start, count)
        return count <= self.limit
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `python3 tests/test_cockpit.py`
Expected: `ok t_mint_token_shape` … `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/cockpit_auth.py tests/test_cockpit.py
git commit -m "feat(cockpit): token auth core (mint/verify, cookie parse, rate limiter)"
```

---

### Task 2: Version store + revocation + `streamer_key` parity

**Files:**
- Create: `src/scripts/cockpit_admin.py`
- Modify: `tests/test_cockpit.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_cockpit.py`, above the `__main__` block)

```python
cad = _load("cockpit_admin", ("src", "scripts", "cockpit_admin.py"))
m = _load("irofeeds", ("src", "relay", "racecast-feeds.py"))


def t_streamer_key_matches_asset_key():
    """cockpit_auth.streamer_key is a verbatim duplicate of asset_key — pin them."""
    for s in ("Alpha Racing", "  Beta!#1 ", "Ümlaut x", "a-b_c d", "", "  "):
        assert ca.streamer_key(s) == m.asset_key(s), s


def t_versions_default_and_bump():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cockpit-versions.json")
        assert cad.load_versions(p) == {}                 # missing -> {}
        assert cad.current_version({}, "alpha") == 1      # default 1
        assert cad.bump_version(p, "alpha") == 2          # 1 -> 2, persisted
        assert cad.load_versions(p) == {"alpha": 2}
        assert cad.bump_version(p, "alpha") == 3


def t_revoked_token_rejected_after_bump():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cockpit-versions.json")
        tok_v1 = ca.mint_token(SECRET, "alpha", version=1)
        assert ca.verify_token(SECRET, tok_v1, cad.load_versions(p)) == "alpha"
        cad.bump_version(p, "alpha")                       # now current = 2
        assert ca.verify_token(SECRET, tok_v1, cad.load_versions(p)) is None
        tok_v2 = ca.mint_token(SECRET, "alpha", version=2)
        assert ca.verify_token(SECRET, tok_v2, cad.load_versions(p)) == "alpha"


def t_apply_pulled_validates():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cockpit-versions.json")
        assert cad.apply_pulled(p, {"versions": {"alpha": 3, "beta": 2}}) == 2
        assert cad.load_versions(p) == {"alpha": 3, "beta": 2}
        for bad in ({"versions": {"alpha": 0}}, {"versions": {"BAD KEY": 2}},
                    {"versions": {"alpha": "x"}}, {"nope": {}}, []):
            try:
                cad.apply_pulled(p, bad); assert False, bad
            except ValueError:
                pass
```

- [ ] **Step 2: Run and confirm failure**

Run: `python3 tests/test_cockpit.py`
Expected: fails loading `cockpit_admin` / on the new assertions.

- [ ] **Step 3: Implement** — create `src/scripts/cockpit_admin.py`:

```python
"""Commentator-cockpit revocation store (issue #191), mirroring chat_admin.py:
pure validation + atomic JSON writes, no side effects until validation passes.

State file: runtime/<profile>/cockpit-versions.json == {"versions": {key: int}}.
This is the ONLY token state; everything else is derived from COCKPIT_SECRET.
Pulled on producer takeover (apply_pulled), exactly like chat_admin.apply_pulled."""
import json
import os
import re

_KEY_RE = re.compile(r"[a-z0-9-]+")


def validate_versions(payload):
    """{"versions": {streamer_key: int>=1}} -> the cleaned dict. Raises ValueError
    on any malformed shape (mirrors chat_admin.validate_payload)."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    versions = payload.get("versions")
    if not isinstance(versions, dict):
        raise ValueError("missing 'versions' object")
    out = {}
    for key, val in versions.items():
        if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
            raise ValueError(f"bad streamer key: {key!r}")
        if isinstance(val, bool) or not isinstance(val, int) or val < 1:
            raise ValueError(f"bad version for {key!r}: {val!r}")
        out[key] = val
    return out


def load_versions(path):
    """{key: version} from disk, or {} when missing/corrupt (best-effort, like
    chat_admin.load_messages — a bad file must never lock everyone out)."""
    try:
        with open(path, encoding="utf-8") as fh:
            return validate_versions(json.load(fh))
    except (OSError, ValueError):
        return {}


def current_version(versions, key):
    """Current version for a streamer_key, defaulting to 1 when absent."""
    try:
        return int(versions.get(key, 1))
    except (TypeError, ValueError):
        return 1


def write_versions(path, versions):
    """Atomically persist {key: version} as {"versions": {...}} (temp + replace)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"versions": versions}, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def bump_version(path, key):
    """Increment a streamer's version (revocation), persist, return the new value."""
    versions = load_versions(path)
    versions[key] = current_version(versions, key) + 1
    write_versions(path, versions)
    return versions[key]


def apply_pulled(path, payload):
    """Validate a pulled {"versions": {...}} then overwrite *path*; return the
    count. Raises ValueError before touching disk (takeover safety)."""
    versions = validate_versions(payload)
    write_versions(path, versions)
    return len(versions)
```

- [ ] **Step 4: Run and confirm pass**

Run: `python3 tests/test_cockpit.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/cockpit_admin.py tests/test_cockpit.py
git commit -m "feat(cockpit): revocation version store + takeover pull validation"
```

---

### Task 3: Tally derivation helpers (`cockpit_tally`, `cockpit_display_name`)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add after `live_schedule_row`, ~line 1298)
- Modify: `tests/test_cockpit.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_cockpit.py`)

```python
def _rows():
    # ScheduleSource 4-tuples: (url, streamer, stint, line)
    return [("u0", "Alpha Racing", "S1", 2),
            ("u1", "Beta", "S2", 3),
            ("u2", "Alpha Racing", "S3", 4),
            ("u3", "Gamma", "S4", 5)]


def t_tally_on_air():
    t = m.cockpit_tally(_rows(), 0, "alpha-racing")
    assert t["on_air"] is True
    assert t["up_next"] == {"stint": "S3", "in_n": 2}
    assert t["scheduled"] is True


def t_tally_up_next_only():
    t = m.cockpit_tally(_rows(), 0, "beta")
    assert t["on_air"] is False
    assert t["up_next"] == {"stint": "S2", "in_n": 1}


def t_tally_not_upcoming():
    t = m.cockpit_tally(_rows(), 2, "beta")     # Beta already passed
    assert t["on_air"] is False and t["up_next"] is None and t["scheduled"] is True


def t_tally_not_scheduled():
    t = m.cockpit_tally(_rows(), 0, "nobody")
    assert t == {"on_air": False, "up_next": None, "scheduled": False}


def t_display_name_maps_key_to_name():
    assert m.cockpit_display_name(_rows(), "alpha-racing") == "Alpha Racing"
    assert m.cockpit_display_name(_rows(), "nobody") == "nobody"
```

- [ ] **Step 2: Run and confirm failure**

Run: `python3 tests/test_cockpit.py`
Expected: `AttributeError: module 'irofeeds' has no attribute 'cockpit_tally'`.

- [ ] **Step 3: Implement** — in `src/relay/racecast-feeds.py`, directly **after** the
`live_schedule_row` function (ends ~line 1298), add:

```python
def cockpit_tally(rows, live_idx, me_key):
    """Talent tally for a commentator identified by *me_key* (a streamer_key).
    Pure — unit-testable without a running relay. *rows* are ScheduleSource
    4-tuples (url, streamer, stint, line); *live_idx* is the on-air feed's index.
      on_air   = the on-air row's streamer normalizes to me_key
      up_next  = the nearest FUTURE row that is me ->
                 {"stint": <stint label>, "in_n": <handovers away>}, else None
      scheduled= me appears anywhere in the schedule"""
    cur = live_schedule_row(rows, live_idx)
    on_air = bool(cur and asset_key(cur["streamer"]) == me_key)
    up_next = None
    if live_idx is not None:
        for j in range(live_idx + 1, len(rows)):
            _url, streamer, stint, _line = rows[j]
            if asset_key(streamer) == me_key:
                up_next = {"stint": stint, "in_n": j - live_idx}
                break
    scheduled = any(asset_key(r[1]) == me_key for r in rows)
    return {"on_air": on_air, "up_next": up_next, "scheduled": scheduled}


def cockpit_display_name(rows, me_key):
    """The display streamer name whose asset_key == me_key (first match), so chat
    messages are attributed to a human-readable name. Falls back to me_key."""
    for _url, streamer, _stint, _line in rows:
        if asset_key(streamer) == me_key:
            return streamer
    return me_key
```

- [ ] **Step 4: Run and confirm pass**

Run: `python3 tests/test_cockpit.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_cockpit.py
git commit -m "feat(cockpit): pure tally + display-name derivation helpers"
```

---

### Task 4: `make_handler` gains cockpit params + the auth gate helpers

**Files:**
- Modify: `src/relay/racecast-feeds.py` — imports (~top), `make_handler` signature
  (line 2374), and add private auth helpers inside `H`.

This task only adds the plumbing (no routes yet) so the next tasks stay small.

- [ ] **Step 1: Add the import.** Find the relay's import block near the top of
`src/relay/racecast-feeds.py`. The relay is dependency-light and self-contained, but it
already imports sibling scripts (e.g. `chat_admin`). Locate that import and add `cockpit_auth`
and `cockpit_admin` next to it.

Run to find it: `grep -n "import chat_admin\|chat_admin" src/relay/racecast-feeds.py | head -3`

Add alongside the existing `chat_admin` import (match the exact import style used there — a
`sys.path` insert + `import chat_admin` or `from ... import`):

```python
import cockpit_auth
import cockpit_admin
```

- [ ] **Step 2: Extend `make_handler`'s signature.** Change (line 2374):

```python
def make_handler(relay, panel_path=None, hud_source=None, hud_path=None, assets_dir=None,
                 timer_store=None, setup_ctl=None, overlay_dir=None,
                 chat_store=None, preview_path=None, graphics_dir=None,
                 splitscreen_path=None):
```

to add four cockpit kwargs at the end:

```python
def make_handler(relay, panel_path=None, hud_source=None, hud_path=None, assets_dir=None,
                 timer_store=None, setup_ctl=None, overlay_dir=None,
                 chat_store=None, preview_path=None, graphics_dir=None,
                 splitscreen_path=None, cockpit_page_path=None, cockpit_secret=None,
                 cockpit_enabled=False, cockpit_versions_path=None):
```

- [ ] **Step 3: Add per-handler rate limiters + auth helpers.** Immediately after the
`class H(BaseHTTPRequestHandler):` line (2378), before `_send` (so they are class
attributes / methods), add the rate limiters as **closure-level** state (shared across
requests) just *above* `class H`:

```python
    _cockpit_authfail_rl = cockpit_auth.RateLimiter(limit=20, window_s=60)
    _cockpit_chat_rl = cockpit_auth.RateLimiter(limit=10, window_s=60)
```

(Place these two lines between the `def make_handler(...)` signature and `class H`, indented
once — they live in the closure so every `H` instance shares one limiter.)

Then add these methods inside `class H` (e.g. right after `log_message`, ~line 2434):

```python
        def _cockpit_active(self):
            """True iff the cockpit is enabled AND a secret is configured."""
            return bool(cockpit_enabled and cockpit_secret)

        def _cockpit_token(self):
            """The presented token: query ?t= first (link load), else the cookie."""
            qs = parse_qs(urlparse(self.path).query)
            if qs.get("t"):
                return qs["t"][0]
            return cockpit_auth.parse_cookie_token(self.headers.get("Cookie"))

        def _cockpit_auth(self):
            """Return the authed streamer_key, or None after sending 401. Applies
            a per-client failure rate limit. Caller must `return` on None."""
            versions = cockpit_admin.load_versions(cockpit_versions_path) \
                if cockpit_versions_path else {}
            me = cockpit_auth.verify_token(cockpit_secret, self._cockpit_token(), versions)
            if me is None:
                client = self.client_address[0] if self.client_address else "?"
                if not _cockpit_authfail_rl.allow(client):
                    self._send({"error": "rate limited"}, 429)
                else:
                    self._send({"error": "unauthorized"}, 401)
                return None
            return me
```

Confirm `parse_qs` and `urlparse` are imported (they are — the file already uses
`urlparse`; check `grep -n "from urllib.parse import" src/relay/racecast-feeds.py` and add
`parse_qs` to that import line if absent).

- [ ] **Step 4: Smoke-check it still imports & all tests pass.**

Run: `python3 -c "import sys; sys.path.insert(0,'src/scripts'); import importlib.util,os; \
spec=importlib.util.spec_from_file_location('m','src/relay/racecast-feeds.py'); \
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); print('import ok')"`
Expected: `import ok`
Run: `python3 tests/test_cockpit.py && python3 tests/test_pov.py`
Expected: both `ALL PASS` / ok.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py
git commit -m "feat(cockpit): wire cockpit params + server-side auth gate into make_handler"
```

---

### Task 5: `GET /cockpit/data` (tally JSON) — first authed endpoint

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `do_GET` (add a `/cockpit` block, ~line 2558,
  after the existing `chat` block)
- Modify: `tests/test_cockpit.py` — the in-process endpoint fixture + tests

- [ ] **Step 1: Write the failing test** (append to `tests/test_cockpit.py`). This adds the
endpoint fixture used by all remaining endpoint tests:

```python
def _cockpit_client(secret="sek", enabled=True, rows=None, live_idx=0,
                    versions_path=None, chat_store=None, timer_store=None,
                    page_path=None):
    import threading as _t
    import urllib.error
    from urllib.request import Request, urlopen

    class _Feed:
        def __init__(self, idx): self.idx = idx

    class _Source:
        def __init__(self, rws): self._rows = rws
        def get_rows(self): return list(self._rows)
        def health(self): return {"count": len(self._rows)}

    class _Relay:
        def __init__(self):
            self.source = _Source(rows if rows is not None else _rows())
            self.mode = "race"
            a, b = (live_idx, live_idx + 1) if live_idx == 0 else (live_idx, live_idx - 1)
            self.feeds = {"A": _Feed(live_idx), "B": _Feed(live_idx + 1)}
        def live_feed(self): return "A"
        def status(self): return {"schedule_len": len(self.source.get_rows())}

    handler = m.make_handler(_Relay(), chat_store=chat_store, timer_store=timer_store,
                             cockpit_page_path=page_path, cockpit_secret=secret,
                             cockpit_enabled=enabled, cockpit_versions_path=versions_path)
    srv = m.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    _t.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def _read(req):
        try:
            with urlopen(req, timeout=5) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def get(path, cookie=None):
        h = {"Cookie": cookie} if cookie else {}
        return _read(Request(base + path, headers=h))

    def post(path, body, cookie=None):
        h = {"Content-Type": "application/json"}
        if cookie:
            h["Cookie"] = cookie
        return _read(Request(base + path, data=json.dumps(body).encode(),
                             headers=h, method="POST"))
    return srv, get, post


def t_data_requires_auth():
    srv, get, _ = _cockpit_client()
    try:
        code, _h, _b = get("/cockpit/data")
        assert code == 401, code
    finally:
        srv.shutdown()


def t_data_disabled_is_404():
    srv, get, _ = _cockpit_client(enabled=False)
    try:
        tok = ca.mint_token("sek", "alpha-racing")
        code, _h, _b = get("/cockpit/data?t=" + tok)
        assert code == 404, code
    finally:
        srv.shutdown()


def t_data_authed_tally():
    srv, get, _ = _cockpit_client()
    try:
        tok = ca.mint_token("sek", "alpha-racing")
        code, _h, body = get("/cockpit/data?t=" + tok)
        assert code == 200, code
        d = json.loads(body)
        assert d["me"] == "alpha-racing" and d["on_air"] is True
        assert d["up_next"] == {"stint": "S3", "in_n": 2}
        assert d["mode"] == "race"
        # curated: never leak schedule URLs / raw status
        assert "url" not in body.decode() and "schedule_len" not in body.decode()
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run and confirm failure**

Run: `python3 tests/test_cockpit.py`
Expected: `t_data_*` fail (404 for everything — route not present yet).

- [ ] **Step 3: Implement the route.** In `do_GET`, **after** the `chat` block (the one
ending at line 2558 with its `return self._send({"error": "unknown" ...}, 404)`), add:

```python
                if p[:1] == ["cockpit"]:
                    if not self._cockpit_active():
                        return self._send({"error": "cockpit disabled"}, 404)
                    if p == ["cockpit", "data"]:
                        me = self._cockpit_auth()
                        if me is None:
                            return None
                        rows = relay.source.get_rows()
                        live_idx = relay.feeds[relay.live_feed()].idx
                        tally = cockpit_tally(rows, live_idx, me)
                        tally.update({"me": me, "mode": relay.mode,
                                      "program_available": _obs_ws is not None})
                        return self._send(tally)
                    return self._send({"error": "unknown", "path": self.path}, 404)
```

- [ ] **Step 4: Run and confirm pass**

Run: `python3 tests/test_cockpit.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_cockpit.py
git commit -m "feat(cockpit): GET /cockpit/data tally endpoint (auth-gated, curated)"
```

---

### Task 6: `GET /cockpit` (page + cookie), `/cockpit/program`, `/cockpit/timer`

**Files:**
- Modify: `src/relay/racecast-feeds.py` — extend the `/cockpit` block
- Modify: `tests/test_cockpit.py`

- [ ] **Step 1: Write the failing test** (append):

```python
def t_page_sets_cookie_and_serves_html():
    with tempfile.TemporaryDirectory() as d:
        page = os.path.join(d, "cockpit.html")
        with open(page, "w") as fh:
            fh.write("<!doctype html><title>cockpit</title>")
        srv, get, _ = _cockpit_client(page_path=page)
        try:
            tok = ca.mint_token("sek", "alpha-racing")
            code, headers, body = get("/cockpit?t=" + tok)
            assert code == 200, code
            assert b"<!doctype html>" in body.lower() if False else b"cockpit" in body
            setc = headers.get("Set-Cookie", "")
            assert "rc_cockpit=" in setc and "HttpOnly" in setc and "SameSite=Lax" in setc
        finally:
            srv.shutdown()


def t_page_bad_token_401_no_cookie():
    with tempfile.TemporaryDirectory() as d:
        page = os.path.join(d, "cockpit.html")
        open(page, "w").close()
        srv, get, _ = _cockpit_client(page_path=page)
        try:
            code, headers, _b = get("/cockpit?t=bogus")
            assert code == 401, code
            assert "rc_cockpit=" not in (headers.get("Set-Cookie") or "")
        finally:
            srv.shutdown()


def t_timer_authed():
    class _Timer:
        def data(self): return {"running": False, "remaining": "1:00:00"}
    srv, get, _ = _cockpit_client(timer_store=_Timer())
    try:
        tok = ca.mint_token("sek", "alpha-racing")
        code, _h, body = get("/cockpit/timer", cookie="rc_cockpit=" + tok)
        assert code == 200, code
        assert json.loads(body)["remaining"] == "1:00:00"
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run and confirm failure**

Run: `python3 tests/test_cockpit.py`
Expected: the three new tests fail.

- [ ] **Step 3: Implement.** Add a cookie-setting file sender and extend the `/cockpit`
block. First add a helper inside `class H` (next to `_send_file`, ~line 2397):

```python
        def _send_html_with_cookie(self, path, token):
            """Serve the cockpit HTML and set the rc_cockpit auth cookie so all
            sub-requests authenticate without the token in the URL."""
            try:
                with open(path, "rb") as fh:
                    body = fh.read()
            except OSError:
                return self._send({"error": "cockpit page not found"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Set-Cookie",
                             f"{cockpit_auth.COOKIE_NAME}={token}; Path=/cockpit; "
                             "HttpOnly; Secure; SameSite=Lax")
            self.end_headers()
            self.wfile.write(body)
            return None
```

Then, inside the `if p[:1] == ["cockpit"]:` block (after the `cockpit/data` clause, before
the final unknown-404), add:

```python
                    if p == ["cockpit"]:
                        me = self._cockpit_auth()
                        if me is None:
                            return None
                        if not cockpit_page_path:
                            return self._send({"error": "cockpit page not found"}, 404)
                        return self._send_html_with_cookie(cockpit_page_path,
                                                           self._cockpit_token())
                    if p == ["cockpit", "program"]:
                        if self._cockpit_auth() is None:
                            return None
                        if _obs_ws is None:
                            return self._send({"error": "obs unavailable"}, 503)
                        data, note = _obs_ws.get_program_screenshot(width=640)
                        if data is None:
                            return self._send({"error": "preview unavailable",
                                               "note": note}, 503)
                        return self._send_jpeg(data)
                    if p == ["cockpit", "timer"]:
                        if self._cockpit_auth() is None:
                            return None
                        if not timer_store:
                            return self._send({"error": "timer disabled"}, 404)
                        return self._send(timer_store.data())
```

- [ ] **Step 4: Run and confirm pass**

Run: `python3 tests/test_cockpit.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_cockpit.py
git commit -m "feat(cockpit): serve talent page (cookie), program JPEG, read-only timer"
```

---

### Task 7: Cockpit chat — `GET /cockpit/chat/data` + `POST /cockpit/chat/send` (forced name)

**Files:**
- Modify: `src/relay/racecast-feeds.py` — extend the `/cockpit` GET block + add a `/cockpit`
  POST block in `do_POST`
- Modify: `tests/test_cockpit.py`

- [ ] **Step 1: Write the failing test** (append):

```python
def t_cockpit_chat_send_forces_identity():
    with tempfile.TemporaryDirectory() as d:
        cs = m.ChatStore(os.path.join(d, "chat.json"))
        srv, get, post = _cockpit_client(chat_store=cs)
        try:
            tok = ca.mint_token("sek", "alpha-racing")
            # client tries to spoof "user" -> must be ignored, forced to display name
            code, _h, body = post("/cockpit/chat/send",
                                  {"user": "Impostor", "text": "hi"},
                                  cookie="rc_cockpit=" + tok)
            assert code == 200, (code, body)
            assert json.loads(body)["message"]["user"] == "Alpha Racing"
            code, _h, body = get("/cockpit/chat/data", cookie="rc_cockpit=" + tok)
            msgs = json.loads(body)["messages"]
            assert msgs[-1]["user"] == "Alpha Racing" and msgs[-1]["text"] == "hi"
        finally:
            srv.shutdown()


def t_cockpit_chat_requires_auth():
    with tempfile.TemporaryDirectory() as d:
        cs = m.ChatStore(os.path.join(d, "chat.json"))
        srv, get, post = _cockpit_client(chat_store=cs)
        try:
            assert get("/cockpit/chat/data")[0] == 401
            assert post("/cockpit/chat/send", {"text": "x"})[0] == 401
        finally:
            srv.shutdown()
```

- [ ] **Step 2: Run and confirm failure**

Run: `python3 tests/test_cockpit.py`
Expected: the two new tests fail.

- [ ] **Step 3: Implement.** Add to the `/cockpit` GET block (after the `cockpit/timer`
clause):

```python
                    if p == ["cockpit", "chat", "data"]:
                        if self._cockpit_auth() is None:
                            return None
                        if not chat_store:
                            return self._send({"error": "chat disabled"}, 404)
                        return self._send(chat_store.data())
```

Then in `do_POST`, **before** the `if p == ["chat", "send"]:` line (~2641), add a cockpit
POST block (cockpit auth is checked first; the body was already parsed above):

```python
                if p[:1] == ["cockpit"]:
                    if not self._cockpit_active():
                        return self._send({"error": "cockpit disabled"}, 404)
                    if p == ["cockpit", "chat", "send"]:
                        me = self._cockpit_auth()
                        if me is None:
                            return None
                        if not chat_store:
                            return self._send({"error": "chat disabled"}, 404)
                        client = self.client_address[0] if self.client_address else "?"
                        if not _cockpit_chat_rl.allow(client):
                            return self._send({"error": "rate limited"}, 429)
                        name = cockpit_display_name(relay.source.get_rows(), me)
                        return self._send(chat_store.add(user=name,
                                                         text=body.get("text")))
                    return self._send({"error": "unknown", "path": self.path}, 404)
```

Note: in `do_POST` the JSON body parse + size guard already ran at the top of the method
(lines 2632-2640), so `body` is available here.

- [ ] **Step 4: Run and confirm pass**

Run: `python3 tests/test_cockpit.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_cockpit.py
git commit -m "feat(cockpit): crew chat embedded with token-forced identity"
```

---

### Task 8: The talent page `src/cockpit/cockpit.html`

**Files:**
- Create: `src/cockpit/cockpit.html`

This is a self-contained page (no build step), same idiom as `director-panel.html`. All
fetches are same-origin under `/cockpit`, so the `rc_cockpit` cookie authenticates them.

- [ ] **Step 1: Create the page.** Write `src/cockpit/cockpit.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Commentator Cockpit</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 15px/1.4 system-ui, sans-serif; background: #0b0d10; color: #e8eaed; }
  header { display: flex; align-items: center; gap: 12px; padding: 10px 14px; background: #14171c; }
  header h1 { font-size: 15px; margin: 0; font-weight: 600; letter-spacing: .02em; }
  #who { opacity: .7; font-size: 13px; }
  .wrap { display: grid; grid-template-columns: 2fr 1fr; gap: 12px; padding: 12px; }
  @media (max-width: 820px) { .wrap { grid-template-columns: 1fr; } }
  .card { background: #14171c; border: 1px solid #232830; border-radius: 10px; overflow: hidden; }
  .tally { padding: 18px; text-align: center; font-weight: 800; font-size: 26px;
           letter-spacing: .04em; border-radius: 10px; transition: background .2s; }
  .tally.onair { background: #c1121f; color: #fff; box-shadow: 0 0 0 3px #ff4d5e inset; }
  .tally.next  { background: #1d4ed8; color: #fff; }
  .tally.idle  { background: #1b1f25; color: #9aa0a6; font-size: 18px; }
  .sub { font-size: 13px; font-weight: 500; opacity: .9; margin-top: 4px; }
  #program { width: 100%; display: block; background: #000; aspect-ratio: 16/9; object-fit: contain; }
  .progwrap { position: relative; }
  .progwrap .badge { position: absolute; top: 8px; left: 8px; background: rgba(0,0,0,.6);
                     padding: 2px 8px; border-radius: 6px; font-size: 12px; }
  #timer { padding: 14px; text-align: center; }
  #timer .t { font-size: 30px; font-weight: 700; font-variant-numeric: tabular-nums; }
  #chat { display: flex; flex-direction: column; height: 340px; }
  #chatlog { flex: 1; overflow-y: auto; padding: 8px 10px; }
  #chatlog .msg { margin-bottom: 6px; }
  #chatlog .u { font-weight: 600; color: #8ab4f8; }
  .chatbar { display: flex; gap: 6px; padding: 8px; border-top: 1px solid #232830; }
  .chatbar input { flex: 1; padding: 8px; background: #0b0d10; color: #e8eaed;
                   border: 1px solid #2a3038; border-radius: 6px; }
  .chatbar button { padding: 8px 12px; background: #1d4ed8; color: #fff; border: 0;
                    border-radius: 6px; cursor: pointer; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .06em; opacity: .7;
       margin: 0; padding: 10px 12px; border-bottom: 1px solid #232830; }
</style>
</head>
<body>
<header>
  <h1>Commentator Cockpit</h1>
  <span id="who"></span>
</header>

<div id="tally" class="tally idle">…</div>

<div class="wrap">
  <div>
    <div class="card progwrap">
      <span class="badge">PROGRAM</span>
      <img id="program" alt="program monitor">
    </div>
  </div>
  <div>
    <div class="card"><h2>Race timer</h2><div id="timer"><div class="t">—</div></div></div>
    <div class="card" style="margin-top:12px;">
      <h2>Crew chat</h2>
      <div id="chat">
        <div id="chatlog"></div>
        <div class="chatbar">
          <input id="chatin" placeholder="Message the crew…" maxlength="500">
          <button id="chatsend">Send</button>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
const $ = (id) => document.getElementById(id);

async function j(path) {
  const r = await fetch(path, { cache: 'no-store' });
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

// --- Tally ---
function renderTally(d) {
  $('who').textContent = d.me ? '· ' + d.me + (d.mode === 'qualifying' ? ' · QUALI' : '') : '';
  const el = $('tally');
  if (d.on_air) {
    el.className = 'tally onair';
    el.innerHTML = 'YOU ARE ON AIR';
  } else if (d.up_next) {
    el.className = 'tally next';
    const inN = d.up_next.in_n;
    el.innerHTML = 'UP NEXT · stint ' + d.up_next.stint +
      '<div class="sub">in ' + inN + ' handover' + (inN === 1 ? '' : 's') + '</div>';
  } else if (d.scheduled) {
    el.className = 'tally idle';
    el.textContent = 'Standby — not upcoming';
  } else {
    el.className = 'tally idle';
    el.textContent = 'Standby — not scheduled';
  }
}
async function pollTally() {
  try { renderTally(await j('/cockpit/data')); } catch (e) { /* transient */ }
  setTimeout(pollTally, 2000);
}

// --- Program monitor (JPEG stills, cache-busted) ---
function pollProgram() {
  const img = $('program');
  const next = new Image();
  next.onload = () => { img.src = next.src; setTimeout(pollProgram, 1500); };
  next.onerror = () => setTimeout(pollProgram, 3000);
  next.src = '/cockpit/program?_=' + Date.now();
}

// --- Timer ---
async function pollTimer() {
  try {
    const d = await j('/cockpit/timer');
    $('timer').querySelector('.t').textContent =
      d.remaining || d.display || d.clock || '—';
  } catch (e) { /* transient */ }
  setTimeout(pollTimer, 1000);
}

// --- Chat ---
let lastTs = 0;
async function pollChat() {
  try {
    const d = await j('/cockpit/chat/data');
    const log = $('chatlog');
    log.textContent = '';
    (d.messages || []).forEach(msg => {
      const row = document.createElement('div');
      row.className = 'msg';
      const u = document.createElement('span');
      u.className = 'u'; u.textContent = (msg.user || 'Crew') + ': ';
      row.appendChild(u);
      row.appendChild(document.createTextNode(msg.text || ''));  // XSS-safe
      log.appendChild(row);
    });
    log.scrollTop = log.scrollHeight;
  } catch (e) { /* transient */ }
  setTimeout(pollChat, 3000);
}
async function sendChat() {
  const inp = $('chatin');
  const text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  try {
    await fetch('/cockpit/chat/send', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text })           // user is forced server-side
    });
    pollChat();
  } catch (e) { /* transient */ }
}
$('chatsend').addEventListener('click', sendChat);
$('chatin').addEventListener('keydown', (e) => { if (e.key === 'Enter') sendChat(); });

pollTally(); pollProgram(); pollTimer(); pollChat();
</script>
</body>
</html>
```

- [ ] **Step 2: Smoke test the page is served** with a real token. Run an ad-hoc check:

Run:
```bash
python3 - <<'PY'
import importlib.util, os, threading, urllib.request, urllib.error
ROOT="."
def load(n,rel):
    s=importlib.util.spec_from_file_location(n,os.path.join(ROOT,*rel))
    mod=importlib.util.module_from_spec(s); s.loader.exec_module(mod); return mod
import sys; sys.path.insert(0,"src/scripts")
ca=load("cockpit_auth",("src","scripts","cockpit_auth.py"))
m=load("m",("src","relay","racecast-feeds.py"))
class F:
    def __init__(s,i): s.idx=i
class S:
    def get_rows(s): return [("u","Alpha","S1",2)]
    def health(s): return {}
class R:
    source=S(); mode="race"; feeds={"A":F(0),"B":F(1)}
    def live_feed(s): return "A"
    def status(s): return {}
page=os.path.abspath("src/cockpit/cockpit.html")
h=m.make_handler(R(),cockpit_page_path=page,cockpit_secret="sek",cockpit_enabled=True)
srv=m.ThreadingHTTPServer(("127.0.0.1",0),h)
threading.Thread(target=srv.serve_forever,daemon=True).start()
port=srv.server_address[1]
tok=ca.mint_token("sek","alpha")
r=urllib.request.urlopen(f"http://127.0.0.1:{port}/cockpit?t={tok}")
print("status", r.status, "cookie", "rc_cockpit" in r.headers.get("Set-Cookie",""))
print("has-img", b"id=\"program\"" in r.read())
srv.shutdown()
PY
```
Expected: `status 200 cookie True` and `has-img True`.

- [ ] **Step 3: Commit**

```bash
git add src/cockpit/cockpit.html
git commit -m "feat(cockpit): talent page (program monitor + tally + chat + timer)"
```

---

### Task 9: Relay `main()` + `config.py` wiring (page path, secret, enabled, versions)

**Files:**
- Modify: `src/scripts/config.py` — `ResolvedConfig` + `resolve_config`
- Modify: `src/racecast.py` — `_profile_env_vars`
- Modify: `src/relay/racecast-feeds.py` — `main()` resolve + `make_handler` call
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing config test.** Append to `tests/test_config.py` a case
that a profile.env `COCKPIT_SECRET` surfaces on `ResolvedConfig`. Find the existing helper
in that file that writes a profile.env + calls `resolve_config` (grep for `resolve_config(`)
and mirror it:

```python
def t_cockpit_secret_resolved():
    import tempfile, os
    with tempfile.TemporaryDirectory() as root:
        _scaffold_profile(root, "lg", "NAME=LG\nSHEET_ID=x\nCOCKPIT_SECRET=abc123\n")
        rc = cfg.resolve_config(root, override="lg", runtime_root=os.path.join(root, "runtime"))
        assert rc.cockpit_secret == "abc123"
```

(Use whatever the file's existing profile-scaffolding helper is named; if there is none,
write `profiles/lg/profile.env` directly with `os.makedirs` + `open`.)

- [ ] **Step 2: Run and confirm failure**

Run: `python3 tests/test_config.py`
Expected: `AttributeError: 'ResolvedConfig' object has no attribute 'cockpit_secret'`.

- [ ] **Step 3: Implement config.** In `src/scripts/config.py`, add the field to
`ResolvedConfig` (after `obs_collection`, line 158):

```python
    cockpit_secret: str = ""     # per-league HMAC secret for the talent cockpit (#191)
```

And parse it in `resolve_config`'s return (after the `obs_collection=` line, ~210):

```python
        cockpit_secret=prof.get("COCKPIT_SECRET", ""),
```

- [ ] **Step 4: Inject it in `racecast.py`.** In `_profile_env_vars` (line ~188), add to the
`pairs` tuple:

```python
             ("RACECAST_COCKPIT_SECRET", rc.cockpit_secret),
```

- [ ] **Step 5: Resolve everything in the relay `main()`.** In
`src/relay/racecast-feeds.py`, near the other page-path resolution (the splitscreen block,
~line 2896), add cockpit page resolution:

```python
    cockpit_page_path = None
    for cand in (os.path.join(here, "cockpit.html"),
                 os.path.join(here, "..", "cockpit.html"),
                 os.path.join(here, "..", "cockpit", "cockpit.html")):
        if os.path.exists(cand):
            cockpit_page_path = os.path.abspath(cand); break
```

Then just before the `handler = make_handler(...)` call (line 2979), add:

```python
    cockpit_secret = os.environ.get("RACECAST_COCKPIT_SECRET") or None
    cockpit_enabled = (os.environ.get("RACECAST_COCKPIT_ENABLED", "").strip().lower()
                       in ("1", "true", "yes", "on"))
    cockpit_versions_path = os.path.join(runtime, "cockpit-versions.json")
```

And extend the `make_handler(...)` call (lines 2979-2983) to pass them:

```python
    handler = make_handler(relay, panel_path, hud_source, hud_path, assets_dir,
                           timer_store, setup_ctl,
                           overlay_dir=args.overlay_dir, chat_store=chat_store,
                           preview_path=preview_path, graphics_dir=graphics_dir,
                           splitscreen_path=splitscreen_path,
                           cockpit_page_path=cockpit_page_path,
                           cockpit_secret=cockpit_secret,
                           cockpit_enabled=cockpit_enabled,
                           cockpit_versions_path=cockpit_versions_path)
```

Add a startup banner line near the panel banner (~line 3034), only when active:

```python
    if cockpit_secret and cockpit_enabled:
        print(f"  Commentator cockpit: /cockpit (auth) — links via 'racecast cockpit links'")
```

- [ ] **Step 6: Run the suites**

Run: `python3 tests/test_config.py && python3 tests/test_cockpit.py && python3 tests/test_pov.py`
Expected: all pass.
Run: `python3 tools/lint.py`
Expected: clean.

- [ ] **Step 7: Document the knobs.** In `profiles/example/profile.env` add (after the
`OBS_COLLECTION` block):

```bash
# OPTIONAL: per-league secret for the Commentator Cockpit (issue #191). Auto-
# generated by `racecast cockpit enable`; travels with `profile export`. Leave
# blank unless you use the talent cockpit. Treat it like a password.
COCKPIT_SECRET=
```

In `.env.example` add:

```bash
# Commentator Cockpit master switch for THIS machine (issue #191). true => the
# relay serves /cockpit (still requires a per-league COCKPIT_SECRET in the active
# profile). Default off. Set by `racecast cockpit enable`.
RACECAST_COCKPIT_ENABLED=false
```

- [ ] **Step 8: Commit**

```bash
git add src/scripts/config.py src/racecast.py src/relay/racecast-feeds.py \
        tests/test_config.py profiles/example/profile.env .env.example
git commit -m "feat(cockpit): wire secret/enabled/page into relay + profile config"
```

**End of M1.** Run `python3 tools/run-tests.py` — expect all green. A relay started with
`RACECAST_COCKPIT_ENABLED=true` and a `COCKPIT_SECRET` now serves an authenticated cockpit
over the tailnet at `http://<tailscale-ip>:8088/cockpit?t=<token>`.

---

# Milestone 2 — CLI, Funnel & takeover

### Task 10: Tailscale Funnel wrappers

**Files:**
- Modify: `src/scripts/tailscale.py`
- Modify: `tests/test_tailscale.py`

> **Research-first (CLAUDE.md rule for external tooling):** before writing the exact
> command, run `tailscale funnel --help` and `tailscale serve --help` on a machine with
> Tailscale installed and confirm the path-scoping flag name. As of current Tailscale the
> command is `tailscale funnel --bg --set-path=/cockpit <target>` and reset is
> `tailscale funnel --set-path=/cockpit off`. If the installed version differs, adjust the
> `args` list below to match — the wrapper shape (subprocess + `_run_funnel`) stays the same.

- [ ] **Step 1: Write the failing test.** Append to `tests/test_tailscale.py` a test of the
**pure arg builder** (so we don't shell out in CI):

```python
def t_funnel_args():
    on = ts.funnel_args(path="/cockpit", target_port=8088, enable=True)
    assert on == ["funnel", "--bg", "--set-path=/cockpit", "http://127.0.0.1:8088/cockpit"]
    off = ts.funnel_args(path="/cockpit", target_port=8088, enable=False)
    assert off == ["funnel", "--set-path=/cockpit", "off"]
```

(Use the module alias the file already uses — grep the top of `tests/test_tailscale.py` for
how it loads `tailscale.py`, e.g. `ts = _load(...)`.)

- [ ] **Step 2: Run and confirm failure**

Run: `python3 tests/test_tailscale.py`
Expected: `AttributeError: ... has no attribute 'funnel_args'`.

- [ ] **Step 3: Implement** in `src/scripts/tailscale.py` (add after `tailscale_up`):

```python
def funnel_args(path, target_port, enable):
    """Pure: the `tailscale funnel` argv to expose ONLY *path* (e.g. /cockpit) on
    public 443, reverse-proxied to the local relay, or to tear it down. Unit-
    tested without shelling out. The target keeps the same path so /cockpit/* maps
    1:1 onto the relay's /cockpit/*."""
    flag = f"--set-path={path}"
    if enable:
        return ["funnel", "--bg", flag, f"http://127.0.0.1:{target_port}{path}"]
    return ["funnel", flag, "off"]


def funnel(binary, path, target_port, enable, timeout=20):
    """Run the funnel on/off command. Returns (ok, detail). Best-effort, mirrors
    _run_verb. NOTE: enabling requires MagicDNS + HTTPS + the 'funnel' nodeAttr in
    the tailnet policy (a one-time admin step) — surface failures verbatim."""
    args = funnel_args(path, target_port, enable)
    try:
        out = subprocess.run([binary, *args], capture_output=True, text=True,
                             errors="replace", timeout=timeout,
                             env=services.external_tool_env(),
                             **services.no_window_kwargs())
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if out.returncode:
        detail = (out.stderr or out.stdout or "").strip()
        return False, detail or f"exit code {out.returncode}"
    return True, (out.stdout or "").strip()
```

- [ ] **Step 4: Run and confirm pass**

Run: `python3 tests/test_tailscale.py`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/tailscale.py tests/test_tailscale.py
git commit -m "feat(cockpit): tailscale funnel wrapper (path-scoped to /cockpit)"
```

---

### Task 11: `racecast cockpit` command group — `enable` / `disable` / `links`

**Files:**
- Modify: `src/racecast.py` — `route()` + a new `cockpit_cmd`
- Modify: `tests/test_racecast.py`

> **Confirm anchors first:** run
> `grep -n "def _write_env_file\|def _active_profile_env_strict\|def parse_env_text\|def _env_file\|def _runtime_base_dir\|def _active_profile_name" src/racecast.py`
> and use the real names where this task references them (the names below match the Explore
> findings: `_env_file()`, `parse_env_text`, `_write_env_file`, `_active_profile_env_strict`,
> `_active_profile_name`). `_cockpit_versions_path()` is a small new helper this task adds.

- [ ] **Step 1: Write the failing routing test.** Append to `tests/test_racecast.py`
(mirror its existing `route()` tests — grep for `route(` in that file):

```python
def t_route_cockpit():
    assert rc.route(["cockpit", "links"]) == {"kind": "cockpit", "rest": ["links"]}
    assert rc.route(["cockpit", "enable"]) == {"kind": "cockpit", "rest": ["enable"]}
    try:
        rc.route(["cockpit"])         # missing verb
        assert False
    except ValueError:
        pass
```

- [ ] **Step 2: Run and confirm failure**

Run: `python3 tests/test_racecast.py`
Expected: the new test fails.

- [ ] **Step 3: Implement routing + command.** In `route()` (add a block next to the `chat`
block, ~line 800), add:

```python
    if cmd == "cockpit":
        if not rest or rest[0] not in COCKPIT_VERBS:
            raise ValueError(f"usage: racecast cockpit {{{'|'.join(COCKPIT_VERBS)}}}")
        return {"kind": "cockpit", "rest": rest}
```

Near the other verb tuples (e.g. `CHAT_VERBS`), add:

```python
COCKPIT_VERBS = ("enable", "disable", "funnel", "links", "token", "pull-versions")
```

In `main()` where the action dict `kind` is dispatched (grep for `kind == "chat"`), add:

```python
    if action["kind"] == "cockpit":
        return cockpit_cmd(action["rest"])
```

Add the helpers + command (place near `chat_cmd`, ~line 790). This step implements
`enable`/`disable`/`links`; `funnel`/`token`/`pull-versions` come in Tasks 12–14 (add them as
explicit `sys.exit("not yet")` stubs now so the verb list stays valid, then fill in):

```python
import secrets as _secrets

import cockpit_auth as cpa          # add near the other src/scripts imports at top
import cockpit_admin as cpadm


def _cockpit_versions_path():
    """runtime/<active-profile>/cockpit-versions.json."""
    return os.path.join(_runtime_base_dir(), _active_profile_name() or "default",
                        "cockpit-versions.json")


def _cockpit_roster():
    """Distinct streamer names from the active schedule, in first-seen order.
    Reads the live /status-independent schedule via the relay's CSV the same way
    other CLI helpers do — but the simplest robust source is the running relay's
    /schedule/data. Fall back to an error if the relay is not reachable."""
    data = _relay_fetch_json(f"http://127.0.0.1:8088/schedule/data")
    seen, roster = set(), []
    for row in (data or {}).get("rows", []):
        name = (row.get("name") or "").strip()
        key = cpa.streamer_key(name)
        if key and key not in seen:
            seen.add(key); roster.append(name)
    return roster


def cockpit_cmd(rest):
    """`racecast cockpit enable|disable|funnel|links|token|pull-versions`."""
    verb, args = rest[0], rest[1:]

    if verb == "enable":
        # 1) ensure a per-league COCKPIT_SECRET exists in the active profile.env
        active, ppath = _active_profile_env_strict()
        if not active:
            sys.exit("racecast: no active profile — create or select one first.")
        entries = parse_env_text(open(ppath).read()) if os.path.exists(ppath) else {}
        if not entries.get("COCKPIT_SECRET"):
            entries["COCKPIT_SECRET"] = _secrets.token_hex(32)
            _write_env_file(ppath, [{"key": k, "value": v} for k, v in entries.items()])
            print(f"generated COCKPIT_SECRET in {ppath}")
        # 2) set the machine-local master switch
        epath = _env_file()
        menv = parse_env_text(open(epath).read()) if os.path.exists(epath) else {}
        menv["RACECAST_COCKPIT_ENABLED"] = "true"
        _write_env_file(epath, [{"key": k, "value": v} for k, v in menv.items()])
        print("cockpit enabled — restart the relay, then 'racecast cockpit links'.")
        return

    if verb == "disable":
        epath = _env_file()
        menv = parse_env_text(open(epath).read()) if os.path.exists(epath) else {}
        menv["RACECAST_COCKPIT_ENABLED"] = "false"
        _write_env_file(epath, [{"key": k, "value": v} for k, v in menv.items()])
        print("cockpit disabled — restart the relay to stop serving /cockpit.")
        return

    if verb == "links":
        _apply_active_profile_env()
        secret = os.environ.get("RACECAST_COCKPIT_SECRET")
        if not secret:
            sys.exit("racecast: no COCKPIT_SECRET — run 'racecast cockpit enable' first.")
        host = detect_tailscale_ip() or "<tailscale-ip>"
        versions = cpadm.load_versions(_cockpit_versions_path())
        roster = _cockpit_roster()
        if not roster:
            sys.exit("racecast: no streamers in the schedule (is the relay running?).")
        post = "--post" in args
        lines = []
        for name in roster:
            key = cpa.streamer_key(name)
            tok = cpa.mint_token(secret, key, cpadm.current_version(versions, key))
            url = f"https://<your-magicdns-host>/cockpit?t={tok}"  # Funnel host
            lan = f"http://{host}:8088/cockpit?t={tok}"            # tailnet fallback
            print(f"{name}:\n  funnel: {url}\n  tailnet: {lan}")
            lines.append(f"{name}: {url}")
        if post:
            _post_chat_message("Cockpit links:\n" + "\n".join(lines))
            print("posted links into crew chat.")
        return

    if verb == "funnel":
        return _cockpit_funnel(args)        # Task 12
    if verb == "token":
        return _cockpit_token(args)         # Task 13
    if verb == "pull-versions":
        return _cockpit_pull_versions(args)  # Task 14
```

If `_post_chat_message` does not already exist, implement a tiny POST to
`/chat/send` (grep `def _post_chat_message\|/chat/send` first; if absent add a 5-line helper
using `urllib.request` mirroring `_relay_fetch_json`).

- [ ] **Step 4: Stub the three later verbs** so the module imports and routes pass. Add
temporary stubs (replaced in Tasks 12-14):

```python
def _cockpit_funnel(args): sys.exit("cockpit funnel: implemented in a later task")
def _cockpit_token(args): sys.exit("cockpit token: implemented in a later task")
def _cockpit_pull_versions(args): sys.exit("cockpit pull-versions: implemented later")
```

- [ ] **Step 5: Run and confirm pass**

Run: `python3 tests/test_racecast.py`
Expected: pass.
Run: `python3 tools/lint.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(cockpit): racecast cockpit enable/disable/links commands"
```

---

### Task 12: `racecast cockpit funnel on|off`

**Files:**
- Modify: `src/racecast.py` — replace the `_cockpit_funnel` stub

- [ ] **Step 1: Implement.** Replace the stub:

```python
def _cockpit_funnel(args):
    """`racecast cockpit funnel on|off` — public ingress for ONLY /cockpit via
    Tailscale Funnel. Requires MagicDNS + HTTPS + the 'funnel' nodeAttr (one-time
    tailnet-admin step); funnel() surfaces the verbatim error if missing."""
    if not args or args[0] not in ("on", "off"):
        sys.exit("usage: racecast cockpit funnel {on|off}")
    enable = args[0] == "on"
    binary, _state, _ip = tsmod.tailscale_backend()
    if not binary:
        sys.exit("racecast: Tailscale CLI not found / backend not running.")
    ok, detail = tsmod.funnel(binary, path="/cockpit", target_port=8088, enable=enable)
    if not ok:
        sys.exit(f"racecast: funnel {'on' if enable else 'off'} failed: {detail}\n"
                 "Hint: enable MagicDNS + HTTPS and add the 'funnel' nodeAttr in the "
                 "tailnet policy (one-time admin step).")
    print(f"cockpit funnel {'enabled' if enable else 'disabled'}. {detail}".strip())
```

Confirm the module alias for `tailscale.py` (grep `import tailscale` in `src/racecast.py`;
use the real alias — referenced here as `tsmod`).

- [ ] **Step 2: Verify it routes** (no real funnel call in CI):

Run: `python3 -c "import sys; sys.argv=['racecast','cockpit','funnel']; \
import importlib.util; s=importlib.util.spec_from_file_location('rc','src/racecast.py'); \
print('module loads ok')"`
Expected: `module loads ok` (lint will catch real issues).
Run: `python3 tools/lint.py`
Expected: clean.

- [ ] **Step 3: Manual verification (operator, not CI).** On a Tailscale machine with the
relay running and cockpit enabled: `racecast cockpit funnel on`, then from a phone on
mobile data open the printed `https://<magicdns-host>/cockpit?t=<token>` and confirm the
page loads AND that `https://<magicdns-host>/status` and `/panel` are **not** reachable
(404/connection refused) — proving only `/cockpit` is funnelled.

- [ ] **Step 4: Commit**

```bash
git add src/racecast.py
git commit -m "feat(cockpit): racecast cockpit funnel on|off (path-scoped public ingress)"
```

---

### Task 13: `racecast cockpit token revoke <streamer>`

**Files:**
- Modify: `src/racecast.py` — replace `_cockpit_token`
- Modify: `tests/test_cockpit.py` (revocation already covered at the store level; add a thin
  CLI-path assertion only if a seam exists — otherwise rely on Task 2's store tests)

- [ ] **Step 1: Implement.** Replace the stub:

```python
def _cockpit_token(args):
    """`racecast cockpit token revoke <streamer>` — bump that streamer's version
    so their current link stops validating; re-issue with 'racecast cockpit links'."""
    if len(args) < 2 or args[0] != "revoke":
        sys.exit("usage: racecast cockpit token revoke <streamer-name>")
    key = cpa.streamer_key(args[1])
    if not key:
        sys.exit("racecast: empty streamer name.")
    new_ver = cpadm.bump_version(_cockpit_versions_path(), key)
    # Best-effort: nudge a running relay to drop cached versions (it reads the file
    # per request, so no reload endpoint is needed — this is purely informational).
    print(f"revoked '{args[1]}' (key {key}) -> version {new_ver}. "
          f"Re-issue with 'racecast cockpit links'.")
```

Note: the relay reads `cockpit-versions.json` per request (`load_versions` in
`_cockpit_auth`), so no relay reload is required — the bump takes effect immediately.

- [ ] **Step 2: Verify** the store-level revocation tests still pass (they exercise the same
`bump_version`):

Run: `python3 tests/test_cockpit.py`
Expected: `ALL PASS`.
Run: `python3 tools/lint.py`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add src/racecast.py
git commit -m "feat(cockpit): racecast cockpit token revoke <streamer>"
```

---

### Task 14: Takeover pulls `cockpit-versions.json`

**Files:**
- Modify: `src/racecast.py` — `_cockpit_pull_versions` + a call in `event_takeover`
- Modify: `tests/test_cockpit.py` (admin `apply_pulled` already covered; add CLI smoke if a
  seam exists)

- [ ] **Step 1: Implement the pull command.** Replace the stub:

```python
def _cockpit_pull_versions(args):
    """`racecast cockpit pull-versions <ip> [--port N]` — fetch producer A's
    cockpit-versions over the tailnet and adopt them locally (takeover). Mirrors
    `chat pull`: tailnet trust, best-effort. Hidden helper called by takeover."""
    if not args or args[0].startswith("-"):
        sys.exit("usage: racecast cockpit pull-versions <A-tailscale-ip> [--port N]")
    host = args[0]
    port = _takeover_port(args[1:])     # reuse the existing port parser
    payload = _relay_fetch_json(f"http://{host}:{port}/cockpit/versions")
    if not isinstance(payload, dict):
        sys.exit(f"racecast: could not fetch cockpit versions from {host}:{port}")
    try:
        count = cpadm.apply_pulled(_cockpit_versions_path(), payload)
    except ValueError as exc:
        sys.exit(f"racecast: bad cockpit versions payload: {exc}")
    print(f"pulled {count} cockpit version record(s) from {host}.")
```

- [ ] **Step 2: Expose `/cockpit/versions` on the relay** (read-only, producer-only over the
tailnet — like the rest of the relay; NOT funnelled). In `do_GET`'s `/cockpit` block, add
**before** the unknown-404 (note: this path is tailnet-reachable but is *not* under the
Funnel mount, so it needs no token — it carries no secret, only opaque version integers,
consistent with `chat pull`):

```python
                    if p == ["cockpit", "versions"]:
                        if not cockpit_versions_path:
                            return self._send({"versions": {}})
                        return self._send({"versions":
                            cockpit_admin.load_versions(cockpit_versions_path)})
```

Add a test (append to `tests/test_cockpit.py`):

```python
def t_versions_endpoint_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        vp = os.path.join(d, "cockpit-versions.json")
        cad.write_versions(vp, {"alpha": 3})
        srv, get, _ = _cockpit_client(versions_path=vp)
        try:
            code, _h, body = get("/cockpit/versions")
            assert code == 200 and json.loads(body)["versions"] == {"alpha": 3}
        finally:
            srv.shutdown()
```

- [ ] **Step 3: Wire into `event_takeover`.** In `event_takeover` (line ~2045), right after
the existing chat-pull try/except, add:

```python
    try:                                    # best-effort: cockpit pull must not abort
        cockpit_cmd(["pull-versions", host, "--port", str(port)])
    except SystemExit:
        print("note: cockpit-versions pull failed — continuing takeover.")
```

- [ ] **Step 4: Run and confirm pass**

Run: `python3 tests/test_cockpit.py && python3 tools/lint.py`
Expected: `ALL PASS` + clean.

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py src/relay/racecast-feeds.py tests/test_cockpit.py
git commit -m "feat(cockpit): takeover pulls A's revocation versions (tailnet, best-effort)"
```

**End of M2.** Run `python3 tools/run-tests.py` — expect all green.

---

# Milestone 3 — Control Center & docs

### Task 15: Control Center backend — cockpit data functions + routes

**Files:**
- Modify: `src/racecast.py` — `cockpit_status_data`, `cockpit_set_enabled_data`,
  `cockpit_funnel_data`, `cockpit_links_data`, `cockpit_revoke_data`; register in the UI ctx
- Modify: `src/ui/ui_server.py` — `/api/cockpit/*` routes
- Modify: `tests/test_ui_server.py`

> **Confirm anchors first:** `grep -n "profile_env_read\|make_handler(ctx)\|def do_GET\|def do_POST\|_json(" src/ui/ui_server.py`
> and `grep -n "\"profile_env_read\"\|ctx = {" src/racecast.py` — register the new ctx keys
> exactly where `profile_env_read/write` are registered (Explore: racecast.py ~3938).

- [ ] **Step 1: Write the failing UI test.** Append to `tests/test_ui_server.py`, mirroring
its existing route tests (grep `/api/profile/env` there for the fixture):

```python
def t_api_cockpit_status():
    ctx = _base_ctx()        # whatever helper the file uses to build a ctx
    ctx["cockpit_status"] = lambda: {"ok": True, "enabled": True, "has_secret": True,
                                     "funnel": False, "links": []}
    srv, get, _post = _ui_client(ctx)
    try:
        code, body = get("/api/cockpit/status")
        assert code == 200 and json.loads(body)["enabled"] is True
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run and confirm failure**

Run: `python3 tests/test_ui_server.py`
Expected: 404 / missing-route failure.

- [ ] **Step 3: Implement the backend data functions** in `src/racecast.py` (near
`profile_env_entries_data`, ~2687):

```python
def cockpit_status_data():
    """Cockpit state for the Control Center: enabled flag, secret presence, funnel
    state (best-effort), and the per-commentator links. {ok, ...} never raises."""
    try:
        _apply_active_profile_env()
        secret = os.environ.get("RACECAST_COCKPIT_SECRET") or ""
        enabled = (os.environ.get("RACECAST_COCKPIT_ENABLED", "").strip().lower()
                   in ("1", "true", "yes", "on"))
        links = []
        if secret:
            host = detect_tailscale_ip() or ""
            versions = cpadm.load_versions(_cockpit_versions_path())
            for name in _cockpit_roster_safe():
                key = cpa.streamer_key(name)
                tok = cpa.mint_token(secret, key, cpadm.current_version(versions, key))
                links.append({"name": name,
                              "tailnet": f"http://{host}:8088/cockpit?t={tok}" if host else "",
                              "funnel": f"https://<magicdns-host>/cockpit?t={tok}"})
        return {"ok": True, "enabled": enabled, "has_secret": bool(secret), "links": links}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _cockpit_roster_safe():
    try:
        return _cockpit_roster()
    except SystemExit:
        return []


def cockpit_set_enabled_data(enabled):
    """Toggle the machine-local master switch (+ generate a secret on first enable)."""
    try:
        cockpit_cmd(["enable" if enabled else "disable"])
        return {"ok": True}
    except SystemExit as exc:
        return {"ok": False, "error": str(exc)}


def cockpit_funnel_data(on):
    try:
        _cockpit_funnel(["on" if on else "off"])
        return {"ok": True}
    except SystemExit as exc:
        return {"ok": False, "error": str(exc)}


def cockpit_revoke_data(streamer):
    try:
        _cockpit_token(["revoke", streamer])
        return {"ok": True}
    except SystemExit as exc:
        return {"ok": False, "error": str(exc)}
```

Register in the UI ctx dict (where `profile_env_read` is registered, ~3938):

```python
        "cockpit_status": cockpit_status_data,
        "cockpit_set_enabled": cockpit_set_enabled_data,
        "cockpit_funnel": cockpit_funnel_data,
        "cockpit_revoke": cockpit_revoke_data,
```

- [ ] **Step 4: Add the routes** in `src/ui/ui_server.py`. In `do_GET` (next to
`/api/profile/env`):

```python
        if path == "/api/cockpit/status":
            return self._json(ctx["cockpit_status"]())
```

In `do_POST` (next to the profile env write):

```python
        if path == "/api/cockpit/enabled":
            return self._json(ctx["cockpit_set_enabled"](bool(payload.get("enabled"))))
        if path == "/api/cockpit/funnel":
            return self._json(ctx["cockpit_funnel"](bool(payload.get("on"))))
        if path == "/api/cockpit/revoke":
            return self._json(ctx["cockpit_revoke"](payload.get("streamer", "")))
```

(Match how `do_POST` reads the JSON body in this file — grep for `payload =` / `json.loads`
in `do_POST` and reuse the same variable.)

- [ ] **Step 5: Run and confirm pass**

Run: `python3 tests/test_ui_server.py && python3 tools/lint.py`
Expected: pass + clean.

- [ ] **Step 6: Commit**

```bash
git add src/racecast.py src/ui/ui_server.py tests/test_ui_server.py
git commit -m "feat(cockpit): Control Center backend (status/enable/funnel/revoke)"
```

---

### Task 16: Control Center frontend — the Cockpit section

**Files:**
- Modify: `src/ui/control-center.html`

> **Confirm the nav pattern first:** open `src/ui/control-center.html` and find how a view is
> declared (`data-view="..."`), how it is added to the left nav, and the `$()`/`fetch`
> helpers. Mirror the Profile view exactly (Explore: lines 595-611 HTML, 2345-2396 JS).

- [ ] **Step 1: Add the nav entry + view.** Add a sidebar nav item "Cockpit" (mirror the
existing nav items) and a view block:

```html
<div class="view" data-view="cockpit" hidden>
  <section>
    <div class="viewhead"><h3>Commentator Cockpit</h3>
      <span class="sub">talent monitor + tally · issue #191</span><span class="spacer"></span>
      <button onclick="loadCockpit()">Reload</button></div>
    <div class="enverr" id="cp-err" hidden></div>
    <div class="row">
      <label><input type="checkbox" id="cp-enabled" onchange="toggleCockpit()">
        Enable cockpit on this machine</label>
    </div>
    <div class="row">
      <button id="cp-funnel-on" onclick="cockpitFunnel(true)">Funnel ON (public)</button>
      <button id="cp-funnel-off" onclick="cockpitFunnel(false)">Funnel OFF</button>
      <span class="sub">Exposes only /cockpit publicly. Needs MagicDNS + HTTPS + funnel nodeAttr.</span>
    </div>
    <h4>Commentator links</h4>
    <div id="cp-links"></div>
  </section>
</div>
```

- [ ] **Step 2: Add the JS** (near the profile JS):

```javascript
async function loadCockpit() {
  let d;
  try { d = await (await fetch('/api/cockpit/status', {cache: 'no-store'})).json(); }
  catch (e) { showProfileErr('cp-err', 'Control Center not reachable.'); return; }
  if (!d.ok) { showProfileErr('cp-err', d.error || 'cockpit status failed'); return; }
  $('cp-err').hidden = true;
  $('cp-enabled').checked = !!d.enabled;
  const c = $('cp-links');
  c.textContent = '';
  if (!d.has_secret) {
    c.textContent = 'Enable the cockpit to generate a league secret and links.';
    return;
  }
  (d.links || []).forEach(l => {
    const row = document.createElement('div');
    row.className = 'cprow';
    const nm = document.createElement('b'); nm.textContent = l.name + ' ';
    const copy = document.createElement('button');
    copy.textContent = 'Copy funnel link';
    copy.onclick = () => navigator.clipboard.writeText(l.funnel);
    const rev = document.createElement('button');
    rev.textContent = 'Revoke';
    rev.onclick = () => revokeCockpit(l.name);
    row.append(nm, copy, document.createTextNode(' '), rev);
    c.appendChild(row);
  });
}
async function toggleCockpit() {
  await fetch('/api/cockpit/enabled', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({enabled: $('cp-enabled').checked})});
  loadCockpit();
}
async function cockpitFunnel(on) {
  const r = await (await fetch('/api/cockpit/funnel', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({on})})).json();
  if (!r.ok) showProfileErr('cp-err', r.error || 'funnel failed');
}
async function revokeCockpit(streamer) {
  if (!confirm('Revoke ' + streamer + "'s current link?")) return;
  await fetch('/api/cockpit/revoke', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({streamer})});
  loadCockpit();
}
```

Hook `loadCockpit()` into the view-switch dispatcher (find where `loadProfileEnv()` is
called on nav-select and add the cockpit case).

- [ ] **Step 3: Manual smoke test.** Run the Control Center from source (per CLAUDE.md, dev
build, no VERSION):

Run: `python3 src/racecast.py ui --no-browser` then open `http://127.0.0.1:8089`, click the
Cockpit nav item, toggle enable, confirm links render.

- [ ] **Step 4: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(cockpit): Control Center Cockpit section (enable, funnel, links, revoke)"
```

---

### Task 17: Refresh the Control Center wiki screenshot (CLAUDE.md hard rule)

**Files:**
- Create: `src/docs/wiki/images/cc-cockpit.png`

- [ ] **Step 1: Capture from a local dev build** (no `VERSION` file, so the version badge
matches the other `cc-*.png`). With `python3 src/racecast.py ui` running, drive it with the
Playwright MCP, navigate to the Cockpit view, and take an **element** screenshot of the
card/section (mirror the framing of the existing `cc-*.png`, e.g. the `<section>` element),
saving to `src/docs/wiki/images/cc-cockpit.png`.

- [ ] **Step 2: (If a wiki page references it)** add the image to the relevant wiki page
under `src/docs/wiki/` (e.g. a new `Commentator-Cockpit.md` or a section in the Control
Center page). Wiki publish (`tools/sync-wiki.py`) stays a separate maintainer step; only the
committed image is required here.

- [ ] **Step 3: Commit**

```bash
git add src/docs/wiki/images/cc-cockpit.png src/docs/wiki/*.md
git commit -m "docs(cockpit): Control Center cockpit screenshot + wiki page"
```

---

### Task 18: Docs + command-list + build verify

**Files:**
- Modify: `README.md`, `CLAUDE.md` (the `## Commands` block), `src/docs/` operator material

- [ ] **Step 1: Add the commands** to the `CLAUDE.md` command list and `README.md`:

```bash
python3 src/racecast.py cockpit enable            # generate league secret + turn on (this machine)
python3 src/racecast.py cockpit links             # print per-commentator cockpit links
python3 src/racecast.py cockpit funnel on|off     # public ingress for ONLY /cockpit (Tailscale Funnel)
python3 src/racecast.py cockpit token revoke NAME # rotate one commentator's link
```

Add a short architecture paragraph to `CLAUDE.md` under the relay section describing the
`/cockpit/*` namespace, the two-knob gating, the token model, and that **only** `/cockpit`
is ever funnelled (the security boundary).

- [ ] **Step 2: Run the full suite + lint + build verify.**

Run: `python3 tools/run-tests.py`
Expected: every test file `ALL PASS`.
Run: `python3 tools/lint.py`
Expected: clean.
Run: `python3 tools/build.py`
Expected: build + verify step succeeds (tokenization, blanked password, no secrets, no shell
scripts, page present). Confirm `src/cockpit/cockpit.html` is copied into the dist package.

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md src/docs
git commit -m "docs(cockpit): operator commands + architecture notes"
```

**End of M3.** The feature is complete: an authenticated, Funnel-exposed talent cockpit with
program monitor, tally, chat, and timer; CLI + Control Center management; takeover-safe.

---

## Self-review checklist (done while writing)

- **Spec coverage:** §1 boundary → T4-T6, T9; §2 token → T1; revocation → T2/T13; §3 tally →
  T3/T5; §4 endpoints → T5-T7, T14 (`/cockpit/versions`); §5 Funnel/CLI → T10-T13;
  §6 takeover → T14; §7 security (path-scope, constant-time, curated, cookie, rate-limit) →
  T1/T4-T7/T12; §8 testing → every task is TDD. ✅
- **Placeholders:** the only intentional runtime-confirm steps are the exact Tailscale
  `funnel` CLI syntax (T10, flagged research-first per CLAUDE.md) and the `<magicdns-host>`
  in printed links (inherent to free-tier Funnel; the host is the producer's, surfaced at
  runtime). No code placeholders. ✅
- **Type/name consistency:** `streamer_key`, `mint_token`, `verify_token`,
  `load_versions/current_version/bump_version/apply_pulled`, `cockpit_tally`,
  `cockpit_display_name`, `_cockpit_auth`, `cockpit_cmd`/`COCKPIT_VERBS`,
  `RACECAST_COCKPIT_SECRET`/`RACECAST_COCKPIT_ENABLED`, `cockpit-versions.json` — used
  consistently across tasks. ✅
- **Open items to confirm during execution (grep-first, noted inline):** exact names
  `_write_env_file`, `_active_profile_env_strict`, `_runtime_base_dir`, `_relay_fetch_json`,
  `_takeover_port`, `_post_chat_message`, the `tailscale.py`/`tailscale_backend` alias, the
  `chat_admin` import style in the relay, and the `ui_server.py` ctx-registration line. Each
  task that uses one starts with the grep to pin it.
