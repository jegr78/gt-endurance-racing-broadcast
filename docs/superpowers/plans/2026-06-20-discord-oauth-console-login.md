# Discord OAuth login for /console — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Discord OAuth2 login as an additive second front door to `/console`, so a producer distributes one generic broadcast-safe URL instead of per-person bearer links — and rename the console-wide auth layer from `cockpit` to `console`.

**Architecture:** The `/console` gate already derives roles/pages/policy from one `subject` (a `streamer_key`) read from a signed token (query `?t=` or cookie). Discord OAuth only adds a new way to *obtain that cookie*: `/console/login` → Discord `authorize` → `/console/oauth/callback` matches the Discord username against the Sheet Crew tab → mints the same token → sets the cookie. Everything downstream is unchanged. The existing signed-link flow stays as a fallback.

**Tech Stack:** Pure Python 3 + stdlib (no framework, no package manager). HTTP via `urllib`. HMAC via `hmac`/`hashlib`. Tests are runnable stdlib scripts (no pytest). The relay is `src/relay/racecast-feeds.py`; shared pure helpers live in `src/scripts/`.

## Global Constraints

- **Edit only under `src/`** (+ `tests/`, `docs/`). Never hand-edit `dist/`/`runtime/`.
- **English only** in all code, comments, docs.
- **Python-only tooling** — no `.sh`/`.bat`.
- **Never hardcode secrets or machine paths.** Secrets come from `profiles/<name>/profile.env`. Tests use no real IPs/paths/secrets — Tailscale IPs are `100.64.0.0/10` test constants.
- **No legacy/back-compat shims** — racecast has no production use yet. On rename, change the canonical definition + every caller + the tests; no dual-read.
- **Tests must run on any machine and in CI** — each `tests/test_*.py` is a runnable script. Run the whole suite with `python3 tools/run-tests.py`; lint with `python3 tools/lint.py`.
- **Cross-platform:** the test matrix includes Windows. Never `os.path.join` a path you know belongs to a different OS.
- **Removing/renaming a CLI flag or env key? Grep the whole repo** including `tools/` and `.github/`.
- **Changed a UI surface? Refresh its wiki screenshot in the SAME change** (Control Center → `cc-*.png`; `/console` launcher → its wiki image), captured from a local dev build.

## File Structure

**Phase 1 — rename (mechanical):**
- `src/scripts/cockpit_auth.py` → **rename to** `src/scripts/console_auth.py` (cookie `rc_cockpit`→`rc_console`).
- `src/scripts/cockpit_admin.py` → **rename to** `src/scripts/console_admin.py`; runtime file `cockpit-versions.json` → `console-versions.json`.
- Callers: `src/relay/racecast-feeds.py`, `src/racecast.py`, `src/scripts/console_proxy.py`, `src/scripts/config.py`.
- Tests: `tests/test_cockpit.py`, `tests/test_console_gate.py`, `tests/test_console.py`, `tests/test_console_proxy.py`, `tests/test_submissions.py`, `tests/test_racecast.py`.

**Phase 2 — OAuth feature:**
- Create `src/scripts/discord_oauth.py` — pure OAuth helpers (URL build, state HMAC, identity parse, subject match).
- Create `tests/test_discord_oauth.py`.
- Modify `src/relay/racecast-feeds.py` — Crew Discord/Commentator columns + `discord_map`/`commentator_keys`; A1 union in `resolve_roles`; `/console/login` + `/console/oauth/callback`; auth-optional launcher root; pass OAuth config into the handler.
- Modify `src/scripts/config.py` + `src/racecast.py` — `DISCORD_CLIENT_ID/SECRET` plumbing; `racecast links` extension.
- Modify `src/console/console.html` — "Login with Discord" button.
- Modify `profiles/example/profile.env` — documented keys.
- Docs: `src/docs/` league-owner section + `src/docs/wiki/League-Owner-Setup.md`; screenshots under `src/docs/wiki/images/`.

---

## Phase 1 — Rename cockpit → console (auth layer)

### Task 1: Rename the auth core module + cookie

**Files:**
- Rename: `src/scripts/cockpit_auth.py` → `src/scripts/console_auth.py`
- Modify: `src/relay/racecast-feeds.py` (imports + all `cockpit_auth.` refs), `src/racecast.py` (imports + `cpa`/`cockpit_auth` refs), `src/scripts/console_proxy.py:14`
- Test: `tests/test_cockpit.py`, `tests/test_console_gate.py`, `tests/test_console.py`, `tests/test_console_proxy.py`, `tests/test_submissions.py`

**Interfaces:**
- Produces: module `console_auth` with unchanged public API (`streamer_key`, `mint_token`, `verify_token`, `secret_matches`, `safe_cookie_token`, `parse_cookie_token`, `RateLimiter`) and `console_auth.COOKIE_NAME == "rc_console"`.

- [ ] **Step 1: Rename the file and the cookie constant**

```bash
git mv src/scripts/cockpit_auth.py src/scripts/console_auth.py
```

In `src/scripts/console_auth.py`:
- Change line 20 to `COOKIE_NAME = "rc_console"`.
- Update the module docstring line 1 from `"""Commentator-cockpit auth core (issue #191)` to `"""Console auth core (issue #216, formerly cockpit_auth #191)` and the `parse_cookie_token` docstring "Extract the rc_cockpit token" → "Extract the rc_console token". Leave the token model, `cockpit_admin.py` cross-reference comment (updated in Task 2 to `console_admin.py`), and all logic unchanged.

- [ ] **Step 2: Update `console_proxy.py`**

In `src/scripts/console_proxy.py` line 14:

```python
RELAY_COOKIE = "rc_console"               # the relay's auth cookie — must never reach Companion
```

Update the two nearby comments that say `rc_cockpit` (lines ~22) to `rc_console`.

- [ ] **Step 3: Update relay + CLI importers**

Find every importer and reference:

```bash
grep -rn "cockpit_auth\|import cockpit_auth\|cpa\b" src/relay/racecast-feeds.py src/racecast.py
```

In `src/relay/racecast-feeds.py` and `src/racecast.py`: replace `import cockpit_auth` with `import console_auth` and every `cockpit_auth.` with `console_auth.`. In `src/racecast.py` the import alias is `cpa` (`import cockpit_auth as cpa` or similar) — keep the alias name OR rename to `ca`; if you keep `cpa`, only the imported module changes: `import console_auth as cpa`. Grep confirms zero remaining `cockpit_auth` refs:

```bash
grep -rn "cockpit_auth" src/ ; echo "exit: $?"
```

Expected: no matches.

- [ ] **Step 4: Update the tests (rename references)**

In `tests/test_cockpit.py`, `tests/test_console_gate.py`, `tests/test_console.py`, `tests/test_console_proxy.py`, `tests/test_submissions.py`: replace every `import cockpit_auth` → `import console_auth`, `cockpit_auth.` → `console_auth.`, and every literal `"rc_cockpit="` → `"rc_console="` / `rc_cockpit` → `rc_console`. Verify:

```bash
grep -rn "cockpit_auth\|rc_cockpit" tests/ ; echo "exit: $?"
```

Expected: no matches.

- [ ] **Step 5: Run the affected tests + lint**

Run:
```bash
python3 tests/test_cockpit.py && python3 tests/test_console_gate.py && \
python3 tests/test_console.py && python3 tests/test_console_proxy.py && \
python3 tests/test_submissions.py && python3 tools/lint.py
```
Expected: all PASS, lint clean.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(auth): rename cockpit_auth -> console_auth, cookie rc_cockpit -> rc_console (no legacy)"
```

---

### Task 2: Rename the revocation store module + versions file

**Files:**
- Rename: `src/scripts/cockpit_admin.py` → `src/scripts/console_admin.py`
- Modify: `src/relay/racecast-feeds.py` (import + `cockpit_admin.`/`cockpit_versions_path`/`cockpit-versions.json`), `src/racecast.py` (import alias `cpadm`, `_cockpit_versions_path`), `src/scripts/console_auth.py` (cross-ref comment from Task 1)
- Test: `tests/test_cockpit.py`, `tests/test_console_gate.py`, `tests/test_submissions.py`, `tests/test_racecast.py`

**Interfaces:**
- Produces: module `console_admin` with unchanged public API (`load_versions`, `bump_version`, `current_version`, `apply_pulled`). The on-disk file is `runtime/<profile>/console-versions.json`.

- [ ] **Step 1: Rename the file**

```bash
git mv src/scripts/cockpit_admin.py src/scripts/console_admin.py
```

- [ ] **Step 2: Rename the versions filename**

```bash
grep -rn "cockpit-versions.json\|cockpit_versions_path\|_cockpit_versions_path" src/
```

Replace every `"cockpit-versions.json"` literal with `"console-versions.json"` (in `src/relay/racecast-feeds.py` and `src/racecast.py`). Rename the helper `_cockpit_versions_path` → `_console_versions_path` in `src/racecast.py` and the handler arg/local `cockpit_versions_path` → `console_versions_path` in `src/relay/racecast-feeds.py` (grep both files; update the `make_handler` signature + the `main()` wiring that passes it).

- [ ] **Step 3: Update importers**

In `src/relay/racecast-feeds.py` and `src/racecast.py`: `import cockpit_admin` → `import console_admin` (keep the `cpadm` alias if present: `import console_admin as cpadm`); every `cockpit_admin.` → `console_admin.`. Update the Task-1 cross-ref comment in `src/scripts/console_auth.py` (`see cockpit_admin.py` → `see console_admin.py`). Verify:

```bash
grep -rn "cockpit_admin\|cockpit-versions\|cockpit_versions_path" src/ ; echo "exit: $?"
```
Expected: no matches.

- [ ] **Step 4: Update tests**

In `tests/test_cockpit.py`, `tests/test_console_gate.py`, `tests/test_submissions.py`, `tests/test_racecast.py`: `cockpit_admin` → `console_admin`, `cockpit-versions.json` → `console-versions.json`, `_cockpit_versions_path` → `_console_versions_path`. Verify:

```bash
grep -rn "cockpit_admin\|cockpit-versions\|cockpit_versions_path" tests/ ; echo "exit: $?"
```
Expected: no matches.

- [ ] **Step 5: Drop the legacy COCKPIT_SECRET fallback in config.py**

In `src/scripts/config.py:213`, change:

```python
        console_secret=prof.get("CONSOLE_SECRET") or prof.get("COCKPIT_SECRET", ""),
```
to:
```python
        console_secret=prof.get("CONSOLE_SECRET", ""),
```

Grep for any other `COCKPIT_SECRET` reader (relay, racecast.py, takeover) and drop the legacy branch there too (per the no-legacy constraint):

```bash
grep -rn "COCKPIT_SECRET\|X-Cockpit-Secret" src/
```

For each hit, keep only the `CONSOLE_SECRET` / `X-Console-Secret` path. Update `tests/test_config.py` if it asserts the legacy fallback.

- [ ] **Step 6: Run the full suite + lint**

Run:
```bash
python3 tools/run-tests.py && python3 tools/lint.py
```
Expected: all PASS, lint clean. (This is the green checkpoint for the whole rename.)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(auth): rename cockpit_admin -> console_admin, cockpit-versions.json -> console-versions.json; drop legacy COCKPIT_SECRET"
```

---

## Phase 2 — Discord OAuth feature

### Task 3: Crew Discord + Commentator columns + A1 role union

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `CREW_*` header constants (~647), `CrewSource._parse_rows`/`__init__` (~1797), new `CrewSource.discord_map()` + `CrewSource.commentator_keys()`, `resolve_roles` (547), `_console_roles` (3127)
- Test: `tests/test_roles.py`

**Interfaces:**
- Consumes: `console_auth.streamer_key` / `asset_key` (existing).
- Produces:
  - `CrewSource.discord_map() -> dict[str, str]` mapping `discord_username.lower() -> crew_name`.
  - `CrewSource.commentator_keys() -> set[str]` of `asset_key`-normalized names whose Crew `Commentator` flag is truthy.
  - `resolve_roles(crew_rows, schedule_keys, subject, crew_commentator_keys=frozenset())` — commentator iff `subject in schedule_keys OR subject in crew_commentator_keys`.
  - `CrewSource.get()` still returns the existing `(name, is_dir, is_prod)` 3-tuples (unchanged — the Discord/Commentator data is exposed via the two new methods, so existing consumers are untouched).

- [ ] **Step 1: Write failing tests for the new crew parsing + role union**

Add to `tests/test_roles.py` (follow the file's existing harness — it imports the relay module under a stub name; reuse its import helper):

```python
def t_crew_discord_and_commentator_columns():
    import importlib
    rf = _load_relay()                      # existing helper in this test file
    csv = ("Name,Commentator,Director,Producer,Discord\n"
           "Alice,,x,,alice_d\n"
           "Bob,x,,,Bob.Handle\n"
           "Carol,,,,\n")
    rows = rf.CrewSource._parse_rows(csv)
    # get() shape is unchanged: (name, is_dir, is_prod)
    assert ("Alice", True, False) in rows
    assert ("Bob", False, False) in rows
    src = rf.CrewSource("")                  # no URL; inject rows directly
    src.rows = rows
    src._discord_rows = rf.CrewSource._parse_full(csv)   # see Step 3
    dm = src.discord_map()
    assert dm.get("alice_d") == "Alice"
    assert dm.get("bob.handle") == "Bob"     # lowercased key
    assert src.commentator_keys() == {rf.asset_key("Bob")}

def t_resolve_roles_a1_union_commentator_from_crew_flag():
    rf = _load_relay()
    crew = [("Alice", True, False)]
    # subject not in schedule, but IS in crew commentator set -> commentator
    roles = rf.resolve_roles(crew, set(), rf.asset_key("Bob"),
                             crew_commentator_keys={rf.asset_key("Bob")})
    assert roles == {"commentator"}
    # schedule still auto-grants (fallback intact)
    roles2 = rf.resolve_roles(crew, {rf.asset_key("Dan")}, rf.asset_key("Dan"))
    assert roles2 == {"commentator"}
    # director from crew flag, unioned with commentator from schedule
    roles3 = rf.resolve_roles(crew, {rf.asset_key("Alice")}, rf.asset_key("Alice"),
                              crew_commentator_keys=set())
    assert roles3 == {"commentator", "director"}
```

(If `tests/test_roles.py` has no `_load_relay`/`asset_key` helper, copy the relay-import shim from the top of `tests/test_console.py`, which already imports the hyphenated relay module.)

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_roles.py`
Expected: FAIL (`_parse_full` / `discord_map` / the `crew_commentator_keys` kwarg do not exist yet).

- [ ] **Step 3: Add the header constants + full-row parse**

In `src/relay/racecast-feeds.py` near line 650, add:

```python
CREW_COMMENTATOR_HEADERS = ("commentator",)
CREW_DISCORD_HEADERS = ("discord", "discord handle", "discord username")
```

In `CrewSource.__init__` (line ~1789) add a parallel store:

```python
        self.rows = []
        self.full_rows = []        # [(name, is_dir, is_prod, is_commentator, discord)]
```

Add a static `_parse_full(text)` that returns the 5-tuples (header mode only — the Discord/Commentator columns are header-located; positional fallback returns `[]` for the extra fields). Refactor `_parse_rows` to call `_parse_full` and project to 3-tuples so the two never drift:

```python
    @staticmethod
    def _parse_full(text):
        """CSV -> [(name, is_dir, is_prod, is_commentator, discord)]. Header mode
        only for the Commentator/Discord columns; positional fallback yields
        is_commentator=False, discord="" (those columns need a header to locate)."""
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            return []
        header = [(h or "").strip().lower() for h in rows[0]]
        name_i = next((header.index(h) for h in CREW_NAME_HEADERS if h in header), None)
        def col(headers):
            return next((header.index(h) for h in headers if h in header), None)
        if name_i is not None:
            dir_i, prod_i = col(CREW_DIRECTOR_HEADERS), col(CREW_PRODUCER_HEADERS)
            com_i, dis_i = col(CREW_COMMENTATOR_HEADERS), col(CREW_DISCORD_HEADERS)
            out = []
            for line, r in enumerate(rows, 1):
                if line == 1:
                    continue
                name = r[name_i].strip() if len(r) > name_i else ""
                if not name:
                    continue
                def cell(i): return r[i] if i is not None and len(r) > i else ""
                out.append((name, _crew_truthy(cell(dir_i)), _crew_truthy(cell(prod_i)),
                            _crew_truthy(cell(com_i)), (cell(dis_i) or "").strip()))
            return out
        # Positional fallback: name/dir/prod only; no commentator/discord columns.
        triples = CrewSource._parse_rows_positional(text)   # see Step 4
        return [(n, d, p, False, "") for (n, d, p) in triples]

    @staticmethod
    def _parse_rows(text):
        full = CrewSource._parse_full(text)
        return [(n, d, p) for (n, d, p, _c, _x) in full] or None
```

- [ ] **Step 4: Extract the positional fallback + store full rows on refresh**

Move the existing positional-fallback block (lines ~1825-1840) into a static `_parse_rows_positional(text) -> [(name, is_dir, is_prod)]` (returns `[]` not `None` when empty, so `_parse_full` can map it). In `refresh()` (line ~1863), also store the full rows:

```python
    def refresh(self, timeout=15):
        text = self._fetch_text(timeout)        # factor fetch's decode out, or inline
        rows = self._parse_rows(text) if text else None
        if rows:
            with self.lock:
                self.rows = rows
                self.full_rows = self._parse_full(text)
                self.last_ok = time.time()
                self.last_error = None
            return True
        ...
```

(Simplest: have `fetch()` return the decoded text and `refresh()` parse both shapes from it. Keep the existing error handling.)

- [ ] **Step 5: Add `discord_map()` + `commentator_keys()`**

```python
    def discord_map(self):
        """{discord_username_lower: crew_name} from the Crew tab's Discord column.
        Empty handles are skipped. Last write wins on a duplicate handle."""
        with self.lock:
            full = list(self.full_rows)
        out = {}
        for name, _d, _p, _c, discord in full:
            h = (discord or "").strip().lower()
            if h:
                out[h] = name
        return out

    def commentator_keys(self):
        """asset_key set of crew names whose Commentator flag is truthy (A1 union)."""
        with self.lock:
            full = list(self.full_rows)
        return {asset_key(n) for (n, _d, _p, c, _x) in full if c and (n or "").strip()}
```

- [ ] **Step 6: Wire the A1 union into `resolve_roles` + `_console_roles`**

In `resolve_roles` (line 547) add the parameter and the union:

```python
def resolve_roles(crew_rows, schedule_keys, subject, crew_commentator_keys=frozenset()):
    ...
    roles = set()
    if subject in schedule_keys or subject in crew_commentator_keys:
        roles.add("commentator")
    for name, is_dir, is_prod in crew_rows:
        ...
```

Update the docstring's commentator line to: `"commentator" iff subject is in the live Schedule OR carries the Crew Commentator flag (A1 union)`.

In `_console_roles` (line 3127), pass the new set:

```python
        crew = crew_source.get() if crew_source else []
        ckeys = crew_source.commentator_keys() if crew_source else frozenset()
        return resolve_roles(crew, schedule_keys(rows), subject, ckeys)
```

- [ ] **Step 7: Run the tests + lint**

Run: `python3 tests/test_roles.py && python3 tests/test_console.py && python3 tools/lint.py`
Expected: PASS, clean. (test_console covers `_console_roles`; ensure it still passes with the extra arg.)

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(crew): parse Crew Discord + Commentator columns; A1 commentator-role union"
```

---

### Task 4: `discord_oauth.py` — pure OAuth helpers

**Files:**
- Create: `src/scripts/discord_oauth.py`
- Test: `tests/test_discord_oauth.py`

**Interfaces:**
- Produces:
  - `authorize_url(client_id, redirect_uri, state) -> str`
  - `sign_state(secret, nonce, ts) -> str` (`"<ts>.<nonce>.<sig>"`)
  - `verify_state(secret, state, now, ttl=300) -> bool`
  - `parse_identity(user_json) -> str` (the lowercased `username`, or `""`)
  - `match_subject(username, discord_map) -> str | None` (returns the crew `name`, or `None`)
  - `TOKEN_ENDPOINT`, `USERINFO_ENDPOINT`, `AUTHORIZE_ENDPOINT` constants
  - `valid_redirect_host(host) -> bool` (host is a non-empty `*.ts.net` MagicDNS name, no scheme/port/path/CR-LF)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_discord_oauth.py`:

```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
import discord_oauth as do


def t_authorize_url_has_required_params():
    u = do.authorize_url("cid123", "https://host.ts.net/console/oauth/callback", "st.0.sig")
    assert u.startswith(do.AUTHORIZE_ENDPOINT + "?")
    assert "client_id=cid123" in u
    assert "scope=identify" in u
    assert "response_type=code" in u
    assert "redirect_uri=https%3A%2F%2Fhost.ts.net%2Fconsole%2Foauth%2Fcallback" in u
    assert "state=st.0.sig" in u


def t_state_roundtrip_valid():
    s = do.sign_state("secret", "abc123", 1000)
    assert do.verify_state("secret", s, now=1100, ttl=300) is True


def t_state_expired():
    s = do.sign_state("secret", "abc123", 1000)
    assert do.verify_state("secret", s, now=1400, ttl=300) is False   # 400s > 300


def t_state_tampered_or_wrong_secret():
    s = do.sign_state("secret", "abc123", 1000)
    assert do.verify_state("WRONG", s, now=1100, ttl=300) is False
    assert do.verify_state("secret", s + "x", now=1100, ttl=300) is False
    assert do.verify_state("secret", "not.a.state", now=1100, ttl=300) is False


def t_parse_identity():
    assert do.parse_identity({"id": "1", "username": "Jens_Gross"}) == "jens_gross"
    assert do.parse_identity({"id": "1"}) == ""
    assert do.parse_identity("garbage") == ""


def t_match_subject_case_insensitive():
    dm = {"jens_gross": "Jens Gross"}
    assert do.match_subject("Jens_Gross", dm) == "Jens Gross"
    assert do.match_subject("nobody", dm) is None
    assert do.match_subject("", dm) is None


def t_valid_redirect_host():
    assert do.valid_redirect_host("box.tail1234.ts.net") is True
    assert do.valid_redirect_host("evil.com") is False
    assert do.valid_redirect_host("box.ts.net\r\nX") is False
    assert do.valid_redirect_host("") is False


for _n, _f in sorted(globals().items()):
    if _n.startswith("t_") and callable(_f):
        _f(); print("ok", _n)
print("all discord_oauth tests passed")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_discord_oauth.py`
Expected: FAIL (`ModuleNotFoundError: discord_oauth`).

- [ ] **Step 3: Write `src/scripts/discord_oauth.py`**

```python
"""Discord OAuth2 (Authorization Code, scope=identify) helpers for /console login.

Pure + stdlib only. The relay (src/relay/racecast-feeds.py) calls these to build
the authorize redirect, sign/verify a stateless CSRF `state`, and resolve a Discord
username to a Crew member. The two network calls (code->token, /users/@me) are a
thin wrapper the relay owns; response PARSING stays here so tests run offline.

This is NOT a bot: scope is strictly `identify` (no email, guilds, or message
access). The app is registered per-league in the Discord Developer Portal; the
client_id/secret live in profiles/<name>/profile.env.
"""
import hashlib
import hmac
import re
from urllib.parse import urlencode

AUTHORIZE_ENDPOINT = "https://discord.com/oauth2/authorize"
TOKEN_ENDPOINT = "https://discord.com/api/oauth2/token"
USERINFO_ENDPOINT = "https://discord.com/api/users/@me"

# A MagicDNS host: dot-separated labels ending in .ts.net, no scheme/port/path/space.
_HOST_RE = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)*\.ts\.net\Z", re.IGNORECASE)
_NONCE_RE = re.compile(r"[A-Za-z0-9_-]+\Z")


def authorize_url(client_id, redirect_uri, state):
    """Build the Discord authorize URL (scope=identify, response_type=code)."""
    q = urlencode({
        "client_id": client_id or "",
        "redirect_uri": redirect_uri or "",
        "response_type": "code",
        "scope": "identify",
        "state": state or "",
        "prompt": "none",
    })
    return f"{AUTHORIZE_ENDPOINT}?{q}"


def _sign_state(secret, ts, nonce):
    msg = f"{int(ts)}.{nonce}".encode("utf-8")
    return hmac.new((secret or "").encode("utf-8"), msg, hashlib.sha256).hexdigest()[:32]


def sign_state(secret, nonce, ts):
    """A stateless CSRF token: "<ts>.<nonce>.<sig>". nonce is caller-supplied
    ([A-Za-z0-9_-]); no server storage. TTL is enforced in verify_state."""
    nonce = nonce if _NONCE_RE.fullmatch(nonce or "") else "x"
    return f"{int(ts)}.{nonce}.{_sign_state(secret, ts, nonce)}"


def verify_state(secret, state, now, ttl=300):
    """True iff `state` is a well-formed, in-TTL, correctly-signed token."""
    if not state or not isinstance(state, str):
        return False
    parts = state.split(".")
    if len(parts) != 3:
        return False
    ts_s, nonce, sig = parts
    try:
        ts = int(ts_s)
    except ValueError:
        return False
    if not _NONCE_RE.fullmatch(nonce or ""):
        return False
    if not hmac.compare_digest(sig, _sign_state(secret, ts, nonce)):
        return False
    return 0 <= (int(now) - ts) <= int(ttl)


def parse_identity(user_json):
    """Lowercased Discord `username` from a /users/@me dict, or "" on anything
    unexpected. Pure — the relay passes the already-parsed JSON."""
    if not isinstance(user_json, dict):
        return ""
    return (user_json.get("username") or "").strip().lower()


def match_subject(username, discord_map):
    """Crew name whose Discord handle == username (case-insensitive), or None.
    discord_map is {handle_lower: crew_name} from CrewSource.discord_map()."""
    key = (username or "").strip().lower()
    if not key:
        return None
    return (discord_map or {}).get(key)


def valid_redirect_host(host):
    """True iff host is a bare MagicDNS name safe to build a redirect_uri from
    (defense vs. a forged Host header injecting CR-LF or an off-tailnet redirect;
    Discord's exact registered-redirect match is the real guard)."""
    return bool(host) and bool(_HOST_RE.fullmatch(host))
```

- [ ] **Step 4: Run the tests + lint**

Run: `python3 tests/test_discord_oauth.py && python3 tools/lint.py`
Expected: `all discord_oauth tests passed`, lint clean.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/discord_oauth.py tests/test_discord_oauth.py
git commit -m "feat(oauth): pure Discord OAuth helpers (authorize url, state HMAC, identity/subject)"
```

---

### Task 5: Config plumbing for the per-league OAuth app

**Files:**
- Modify: `src/scripts/config.py` (ResolvedConfig + resolve_config), `src/racecast.py:188` (`_profile_env_vars`), `src/relay/racecast-feeds.py` (`main()` reads env + passes to `make_handler`)
- Modify: `profiles/example/profile.env` (document the keys)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `profiles/<name>/profile.env` keys `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`.
- Produces: `ResolvedConfig.discord_client_id` / `.discord_client_secret`; env `RACECAST_DISCORD_CLIENT_ID` / `RACECAST_DISCORD_CLIENT_SECRET`; relay handler args `discord_client_id` / `discord_client_secret`.

- [ ] **Step 1: Write the failing config test**

In `tests/test_config.py`, add a case (follow the file's fixture style for writing a temp `profiles/<n>/profile.env`):

```python
def t_resolve_config_reads_discord_oauth_keys():
    # ... build a temp root with a profile.env containing:
    #   DISCORD_CLIENT_ID=cid
    #   DISCORD_CLIENT_SECRET=csecret
    rc = config.resolve_config(root, override="demo")
    assert rc.discord_client_id == "cid"
    assert rc.discord_client_secret == "csecret"
```

Run: `python3 tests/test_config.py` → FAIL (`AttributeError: discord_client_id`).

- [ ] **Step 2: Add the fields to ResolvedConfig + resolve_config**

In `src/scripts/config.py`, add to the dataclass (after line 159):

```python
    discord_client_id: str = ""      # per-league Discord OAuth app (console login)
    discord_client_secret: str = ""  # never leaves the producer machine
```

In `resolve_config` (after line 213):

```python
        discord_client_id=prof.get("DISCORD_CLIENT_ID", ""),
        discord_client_secret=prof.get("DISCORD_CLIENT_SECRET", ""),
```

Run: `python3 tests/test_config.py` → PASS.

- [ ] **Step 3: Inject into the child env**

In `src/racecast.py` `_profile_env_vars` (line 192 `pairs`), add:

```python
             ("RACECAST_DISCORD_CLIENT_ID", rc.discord_client_id),
             ("RACECAST_DISCORD_CLIENT_SECRET", rc.discord_client_secret),
```

- [ ] **Step 4: Read them in the relay + pass to the handler**

In `src/relay/racecast-feeds.py` `main()` near the other `os.environ.get` reads (the area around `console_secret`, ~line 4083), add:

```python
    discord_client_id = os.environ.get("RACECAST_DISCORD_CLIENT_ID", "")
    discord_client_secret = os.environ.get("RACECAST_DISCORD_CLIENT_SECRET", "")
```

Add `discord_client_id=None, discord_client_secret=None` to the `make_handler(...)` signature (line ~2876-2879, alongside `console_secret`) and pass them in the `make_handler(...)` call in `main()` (line ~4127). They become closure variables the gate reads in Task 6.

- [ ] **Step 5: Document the keys in the example profile**

In `profiles/example/profile.env`, append (commented, since they're optional):

```bash
# Discord OAuth login for /console (optional; per-league app at discord.com/developers).
# Scope is identify only — NOT a bot. Register the redirect URI printed by
# `racecast links`:  https://<your-magicdns>/console/oauth/callback
# DISCORD_CLIENT_ID=
# DISCORD_CLIENT_SECRET=
```

- [ ] **Step 6: Run config tests + lint + commit**

Run: `python3 tests/test_config.py && python3 tools/lint.py`
Expected: PASS, clean.

```bash
git add -A
git commit -m "feat(config): per-league DISCORD_CLIENT_ID/SECRET plumbing (profile.env -> relay)"
```

---

### Task 6: Relay endpoints — `/console/login` + `/console/oauth/callback`

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `_console_gate` (intercept before auth, ~3148), new handler methods `_oauth_login`, `_oauth_callback`, `_oauth_exchange` (network wrapper), `_send_redirect`, `_send_html`; serve the launcher root auth-optional
- Test: `tests/test_console_gate.py`

**Interfaces:**
- Consumes: `discord_oauth.*` (Task 4), `console_auth.mint_token` + `console_admin` versions (Phase 1), `crew_source.discord_map()` (Task 3), the closure vars `discord_client_id`/`discord_client_secret` (Task 5).
- Produces: `GET /console/login` → 302 to Discord (or 404 if unconfigured); `GET /console/oauth/callback?code=&state=` → on match sets `rc_console` cookie `Path=/console` + 302 to the `/console` base, else a deny/error HTML page. The launcher root `/console` is served WITHOUT requiring auth so an unauthenticated visitor sees the login button.

- [ ] **Step 1: Write the failing endpoint tests**

In `tests/test_console_gate.py` (reuse its in-process server harness; it already mints tokens + drives the handler). Add:

```python
def t_console_login_redirects_when_oauth_configured():
    # make_handler(..., discord_client_id="cid", discord_client_secret="sec",
    #              console_secret="s"); request GET /console/login with Host header
    #              "box.tail1.ts.net" and X-Forwarded-Proto: https
    code, headers, _ = get("/console/login",
                           extra={"Host": "box.tail1.ts.net",
                                  "X-Forwarded-Proto": "https"})
    assert code == 302
    loc = headers["Location"]
    assert loc.startswith("https://discord.com/oauth2/authorize?")
    assert "redirect_uri=https%3A%2F%2Fbox.tail1.ts.net%2Fconsole%2Foauth%2Fcallback" in loc
    assert "client_id=cid" in loc

def t_console_login_404_when_oauth_unconfigured():
    # make_handler with discord_client_id="" (but console_secret set)
    code, _h, _b = get("/console/login")
    assert code == 404

def t_oauth_callback_sets_cookie_on_crew_match(monkeypatch_exchange):
    # Stub the network: patch the handler's _oauth_exchange to return the username
    # "alice_d" without hitting Discord. Crew tab (injected) maps alice_d -> "Alice".
    state = discord_oauth.sign_state("s", "n1", NOW)        # valid state
    code, headers, _ = get("/console/oauth/callback?code=abc&state=" + state,
                           extra={"Host": "box.tail1.ts.net",
                                  "X-Forwarded-Proto": "https"})
    assert code == 302
    assert headers["Location"].endswith("/console")
    setc = headers["Set-Cookie"]
    assert "rc_console=" in setc and "Path=/console" in setc and "HttpOnly" in setc

def t_oauth_callback_bad_state_400():
    code, _h, body = get("/console/oauth/callback?code=abc&state=not.valid.sig")
    assert code == 400

def t_oauth_callback_no_crew_match_denies(monkeypatch_exchange_unknown):
    # _oauth_exchange returns "ghost" (not in the Crew Discord map)
    state = discord_oauth.sign_state("s", "n1", NOW)
    code, _h, body = get("/console/oauth/callback?code=abc&state=" + state)
    assert code == 403
    assert b"not on the crew list" in body.lower() or b"crew" in body.lower()
```

(Match the harness's actual `get(...)` signature/headers helper; the test file already constructs a handler — extend its `make_handler` call with the two discord args and a stub for `_oauth_exchange`. If the harness can't inject a method stub, set a module-level `_TEST_EXCHANGE` hook the real `_oauth_exchange` consults when present — add that hook in Step 3.)

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_console_gate.py`
Expected: FAIL (routes don't exist).

- [ ] **Step 3: Add the OAuth handler methods**

In `src/relay/racecast-feeds.py`, add helpers near `_send_page` (after line ~2952):

```python
        def _send_redirect(self, location):
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None

        def _send_html(self, html, code=200):
            body = html.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)
            return None

        def _oauth_redirect_uri(self):
            """Build this host's callback URI from the request Host header, or None
            if it isn't a valid MagicDNS host (forged-Host / off-tailnet guard)."""
            host = (self.headers.get("Host") or "").split(":")[0].strip()
            if not discord_oauth.valid_redirect_host(host):
                return None
            return f"https://{host}/console/oauth/callback"

        def _oauth_exchange(self, code, redirect_uri):
            """Network: exchange the auth code for a token, then fetch the user's
            lowercased username. Returns "" on any failure. Best-effort (never raises).
            A module-level _TEST_EXCHANGE hook short-circuits this in unit tests."""
            hook = globals().get("_TEST_EXCHANGE")
            if hook is not None:
                return hook(code, redirect_uri)
            try:
                data = urlencode({
                    "client_id": discord_client_id,
                    "client_secret": discord_client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                }).encode("utf-8")
                req = Request(discord_oauth.TOKEN_ENDPOINT, data=data, method="POST",
                              headers={"Content-Type": "application/x-www-form-urlencoded",
                                       "User-Agent": "racecast-feeds/1.0"})
                with urlopen(req, timeout=10) as resp:
                    tok = json.loads(resp.read().decode("utf-8")).get("access_token")
                if not tok:
                    return ""
                ureq = Request(discord_oauth.USERINFO_ENDPOINT,
                               headers={"Authorization": f"Bearer {tok}",
                                        "User-Agent": "racecast-feeds/1.0"})
                with urlopen(ureq, timeout=10) as uresp:
                    return discord_oauth.parse_identity(
                        json.loads(uresp.read().decode("utf-8")))
            except Exception as e:
                LOG.warning("Discord OAuth exchange failed: %s: %s", type(e).__name__, e)
                return ""

        def _oauth_login(self):
            """GET /console/login -> 302 to Discord authorize (OAuth must be on)."""
            if not (discord_client_id and discord_client_secret):
                return self._send({"error": "not found"}, 404)
            redirect_uri = self._oauth_redirect_uri()
            if not redirect_uri:
                return self._send_html(
                    "<h1>Login unavailable</h1><p>This host can't run Discord login "
                    "(needs the public Funnel address).</p>", 400)
            import time as _t
            nonce = console_auth.safe_cookie_token(
                hmac.new(console_secret.encode(), str(self.client_address).encode(),
                         hashlib.sha256).hexdigest()[:16]) or "x"
            state = discord_oauth.sign_state(console_secret, nonce, int(_t.time()))
            return self._send_redirect(
                discord_oauth.authorize_url(discord_client_id, redirect_uri, state))

        def _oauth_callback(self):
            """GET /console/oauth/callback?code=&state= -> mint cookie or deny page."""
            if not (discord_client_id and discord_client_secret):
                return self._send({"error": "not found"}, 404)
            import time as _t
            qs = parse_qs(urlparse(self.path).query)
            if qs.get("error"):
                return self._send_html("<h1>Login cancelled</h1>"
                                       "<p><a href='/console/login'>Try again</a></p>", 200)
            state = (qs.get("state") or [""])[0]
            if not discord_oauth.verify_state(console_secret, state, int(_t.time())):
                return self._send_html("<h1>Login expired</h1>"
                                       "<p><a href='/console/login'>Try again</a></p>", 400)
            redirect_uri = self._oauth_redirect_uri()
            if not redirect_uri:
                return self._send_html("<h1>Login unavailable</h1>", 400)
            username = self._oauth_exchange((qs.get("code") or [""])[0], redirect_uri)
            if not username:
                return self._send_html("<h1>Login failed</h1>"
                                       "<p><a href='/console/login'>Try again</a></p>", 502)
            dm = crew_source.discord_map() if crew_source else {}
            name = discord_oauth.match_subject(username, dm)
            if not name:
                return self._send_html(
                    f"<h1>Not on the crew list</h1><p>Your Discord <b>@{username}</b> "
                    "isn't in this league's Crew list. Ask your league admin to add it.</p>",
                    403)
            key = console_auth.streamer_key(name)
            versions = (console_admin.load_versions(console_versions_path)
                        if console_versions_path else {})
            token = console_auth.mint_token(console_secret, key,
                                            console_admin.current_version(versions, key))
            # Set the Path=/console cookie, then 302 to the launcher base.
            secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
            safe = console_auth.safe_cookie_token(token)
            self.send_response(302)
            self.send_header("Location", "/console")
            self.send_header("Set-Cookie",
                             f"{console_auth.COOKIE_NAME}={safe}; Path=/console; "
                             f"HttpOnly{secure}; SameSite=Lax")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
```

Add `import hashlib, hmac` at the relay top if not already imported (grep first), and ensure `discord_oauth` is imported alongside the other `src/scripts` imports (`import discord_oauth`).

- [ ] **Step 4: Intercept the routes in `_console_gate` BEFORE auth**

In `_console_gate` (line 3145), right after the `if not console_secret: 404` guard and BEFORE `subject = self._cockpit_auth()` (line 3149), add:

```python
            sub = p[1:]
            # OAuth front door — these BOOTSTRAP identity, so they run before auth.
            if sub == ["login"]:
                self._oauth_login(); return None
            if sub == ["oauth", "callback"]:
                self._oauth_callback(); return None
            # The launcher root is auth-OPTIONAL when OAuth is on, so an
            # unauthenticated visitor can see the "Login with Discord" button.
            oauth_on = bool(discord_client_id and discord_client_secret)
            if sub == [] and oauth_on and self._cockpit_token() is None:
                self._send_page(console_page_path, "/console")   # no cookie; page shows login
                return None
            subject = self._cockpit_auth()        # identity only; sends 401/429 on failure
            ...
```

(Move the existing `sub = p[1:]` assignment up to this block — it's currently at line 3148; ensure it isn't duplicated.)

- [ ] **Step 5: Run the tests + lint**

Run: `python3 tests/test_console_gate.py && python3 tools/lint.py`
Expected: PASS, clean.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(oauth): /console/login + /console/oauth/callback (mint rc_console on Crew match)"
```

---

### Task 7: Launcher "Login with Discord" button + `racecast links` output

**Files:**
- Modify: `src/console/console.html` (inject `__RC_OAUTH__`; render login button on 401)
- Modify: `src/relay/racecast-feeds.py` `_send_page` — substitute `__RC_OAUTH__`
- Modify: `src/racecast.py` `links_cmd` (line 1170) — print share URL + redirect URI
- Test: `tests/test_racecast.py`

**Interfaces:**
- Consumes: the launcher is served at `/console` (Task 6) with `__RC_API_BASE__` already substituted; add a second placeholder `__RC_OAUTH__` set to `"1"` when OAuth is configured, else `""`.

- [ ] **Step 1: Inject the OAuth flag when serving the launcher page**

In `src/relay/racecast-feeds.py` `_send_page` (line 2933), after the `__RC_API_BASE__` replace, add:

```python
            body = body.replace(b"__RC_API_BASE__", (api_base or "").encode())
            oauth_flag = b"1" if (discord_client_id and discord_client_secret) else b""
            body = body.replace(b"__RC_OAUTH__", oauth_flag)
```

- [ ] **Step 2: Render the login button in console.html on missing auth**

In `src/console/console.html`, add near the top script (after line 9):

```javascript
  window.RC_OAUTH = "__RC_OAUTH__" === "1";
```

Replace the whoami `.catch` block (lines 88-91) so an unauthenticated visitor with OAuth enabled sees the login button instead of the error:

```javascript
  }).catch(function () {
    var menu = document.getElementById('menu');
    document.getElementById('who').textContent = 'not signed in';
    if (window.RC_OAUTH) {
      menu.innerHTML = '<a class="card" href="' + RC_API('/login') +
        '"><div class="t">Login with Discord</div><div class="d">' +
        'Sign in to reach your console</div></a>';
    } else {
      menu.innerHTML =
        '<div class="empty">Could not load your access. Check your link.</div>';
    }
  });
```

- [ ] **Step 3: Manually verify the page renders both states (local dev build)**

Per the `racecast-local-uat` skill, run the relay from `src/` against a profile with `CONSOLE_SECRET` set; visit `http://127.0.0.1:8088/console` (no token) → with `DISCORD_CLIENT_ID/SECRET` set you see the "Login with Discord" card; unset → the "check your link" message. (No automated browser test — this is the human gate before the screenshot in Task 8.)

- [ ] **Step 4: Extend `racecast links` to print the share URL + redirect URI**

In `src/racecast.py` `links_cmd` (line 1170), after the per-person loop (after line 1196) and before the `--post` block, add:

```python
    print()
    print("Share this ONE link with the whole crew (Discord login resolves their role):")
    print(f"  {('https://' + magic + '/console')}")
    print("Discord OAuth redirect URI to register in the league's Discord app:")
    print(f"  https://{magic}/console/oauth/callback")
```

- [ ] **Step 5: Add/extend the links test**

In `tests/test_racecast.py`, extend the existing `links_cmd` test (it stubs the roster + magicdns) to assert the new lines appear:

```python
    assert "/console/oauth/callback" in out
    assert "/console" in out          # the bare share URL
```

Run: `python3 tests/test_racecast.py` → PASS.

- [ ] **Step 6: Run tests + lint + commit**

Run: `python3 tests/test_racecast.py && python3 tools/lint.py`
Expected: PASS, clean.

```bash
git add -A
git commit -m "feat(console): Login-with-Discord launcher button; racecast links prints share URL + redirect URI"
```

---

### Task 8: Docs, Wiki page + screenshots

**Files:**
- Create: `src/docs/wiki/League-Owner-Setup.md`
- Modify: `src/docs/README_SETUP.md` (or `Broadcast_Setup_Guide.md`) — link the new section
- Modify: `CLAUDE.md` — note the Discord-OAuth env keys + the `console-versions.json` / `rc_console` / `console_auth`/`console_admin` renames where the cockpit names are described
- Capture: `src/docs/wiki/images/console-launcher.png` (or the existing console image name) + the Control Center Profile view `cc-*.png` if Discord fields were surfaced there
- Test: none (docs); run `python3 tools/build.py` verify

**Interfaces:** none (documentation).

- [ ] **Step 1: Write the League-Owner setup page**

Create `src/docs/wiki/League-Owner-Setup.md` covering, as numbered steps:
1. Create a Discord **Application** (not a bot) at discord.com/developers → OAuth2 → copy Client ID + Secret.
2. Paste into `profiles/<league>/profile.env` as `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET`.
3. Register each producer host's redirect URI `https://<magicdns>/console/oauth/callback` (printed by `racecast links`).
4. Maintain the **Crew tab**: `Name | Commentator | Director | Producer | Discord` — fill the Discord @handle for everyone who logs in; role from the flags.
5. Distribution: post the single `https://<magicdns>/console` URL in the crew channel. Signed `racecast links` remain a fallback.
6. Revocation: remove a **person** = blank their Crew Discord/role cell; kill a **leaked link** = `racecast cockpit token revoke <name>` (bumps the version in `console-versions.json`).

Keep it English, mechanism-only (no invented broadcast procedure), and cross-link the role-based-Funnel-access page.

- [ ] **Step 2: Capture the launcher screenshot from a local dev build**

Per the CLAUDE.md screenshot rule + the `racecast-local-uat` skill: run the relay from `src/` (no `VERSION` stamped), open `/console` unauthenticated with OAuth configured, and capture the launcher showing the "Login with Discord" card. Save it to the existing console wiki image path (grep `src/docs/wiki/` for the current console image name; reuse it). If the Control Center Profile view gained Discord fields, recapture that `cc-*.png` too (element screenshot, dev build).

- [ ] **Step 3: Update CLAUDE.md references**

In `CLAUDE.md`, update the cockpit→console naming notes: `rc_cockpit`→`rc_console`, `cockpit_auth.py`→`console_auth.py`, `cockpit_admin.py`→`console_admin.py`, `cockpit-versions.json`→`console-versions.json`, and add the Discord-OAuth env keys to the config section + the `tests/test_discord_oauth.py` line to the test list.

- [ ] **Step 4: Build-verify + commit**

Run: `python3 tools/build.py`
Expected: build + verify pass (no secrets, no shell scripts, tokenization OK).

```bash
git add -A
git commit -m "docs(wiki): League-Owner Discord-OAuth setup; refresh console launcher screenshot"
```

- [ ] **Step 5: Full suite + lint (final gate)**

Run: `python3 tools/run-tests.py && python3 tools/lint.py`
Expected: all PASS, clean.

---

## Self-Review

**Spec coverage:**
- OAuth second front door (login/callback) → Task 6. ✓
- One generic share URL → Task 7 (`racecast links`) + Task 8 (docs). ✓
- Match by Discord username, Crew tab `Discord` column, no approval → Task 3. ✓
- A1 union (commentator from Crew flag OR Schedule) → Task 3. ✓
- Per-league OAuth app in `profile.env`, travels with export → Task 5 (fields are read by `resolve_config`, which `profile export` packages). ✓
- Rename cookie/`cockpit_auth`/`cockpit_admin`/`cockpit-versions.json`, no legacy → Tasks 1-2 (incl. dropping the `COCKPIT_SECRET` fallback). ✓
- Keep talent Cockpit surface (`cockpit.html`, `/cockpit/*`, `cockpit_submissions.py`) → untouched by Tasks 1-2 (only `*_auth`/`*_admin` renamed). ✓
- `state` HMAC, `client_secret` server-side, `identify` scope, redirect-host validation, callback under `/console` → Task 4 (`valid_redirect_host`, `sign/verify_state`) + Task 6. ✓
- Two revocation mechanisms documented → Task 8. ✓
- Auth-optional launcher so the login button is reachable → Task 6 Step 4 + Task 7. ✓ (refinement found during planning, folded in)
- Tests for every unit; rename fallout in tests → each task's test step. ✓
- Docs/Wiki + screenshot same-change → Task 8. ✓

**Placeholder scan:** No "TBD"/"handle edge cases". The two test steps that say "match the harness's actual `get(...)` signature" reference a real, existing in-process server harness in `tests/test_console_gate.py`; the `_TEST_EXCHANGE` hook is fully specified in Task 6 Step 3.

**Type consistency:** `discord_map() -> {handle_lower: name}`, `match_subject(username, discord_map) -> name|None`, `mint_token(secret, key, version)`, `COOKIE_NAME == "rc_console"`, `resolve_roles(..., crew_commentator_keys=...)` — names/signatures consistent across Tasks 3/4/6. `console_versions_path` (renamed in Task 2) is the same name used in Task 6.

**Scope:** Two phases, one coherent deliverable; Phase 1 lands green independently. Right-sized: 8 tasks, each ends on a green test + commit.
