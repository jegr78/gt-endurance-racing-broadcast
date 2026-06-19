# Console roles — Phase 3a: the `/console` auth gate + API mirror — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `CrewSource` into the live relay and add the funnelled-namespace **auth gate**: a `/console/*` request verifies its identity token, resolves roles (`resolve_roles`), decides via `console_policy.decide`, and on ALLOW **falls through to the existing endpoint handler** (rewriting identity-bound routes to their `/cockpit` equivalents). On deny it returns 401/403/404. This is the security-critical core; the role-adaptive HTML pages are Phase 3b.

**Architecture:** A thin gate at the top of `do_GET`/`do_POST`. Both already compute `p = [segments]`; when `p[0] == "console"` the gate authorizes the stripped sub-path and either reassigns `p = sub` (fall through to the identical root dispatch — zero duplication, the capability matrix is the allowlist) or sends a denial and returns. Identity-bound endpoints (`chat/send`, `chat/data`, `submit`) are rewritten to the already-identity-forced `/cockpit/*` handlers so the server, never the client, sets the speaker.

**Tech Stack:** Pure Python 3 stdlib. Reuses Phase 1 (`CrewSource`, `resolve_roles`), Phase 2 (`console_policy`), and the existing `cockpit_auth`/`_cockpit_auth` identity path.

## Global Constraints

- Edit only under `src/`, `tests/`, `docs/`, `CLAUDE.md`; never `dist/` or `runtime/`.
- English only; no secrets, machine paths, or real IPs in committed files (Tailscale test IPs are `100.64.0.0/10`).
- The relay stays stdlib-only. `console_policy` is imported by bare name like the existing `import cockpit_auth` / `import cockpit_admin` (src/scripts is already on `sys.path`).
- Identity ≠ authorization (locked #3): the token is verified for identity only; roles come from the live roster; the matrix decides. No token-format change.
- **Boundary invariant unchanged:** root endpoints + `/cockpit/*` stay reachable exactly as today (tailnet/loopback, unauthenticated). The gate only ADDS the `/console` path; it must not alter any existing route's behavior. Funnel still mounts nothing new in this phase (Phase 4).
- A missing per-league `cockpit_secret` → every `/console/*` path 404s (same rule as `/cockpit/*`).
- Step-up = the shared producer secret via the `X-Cockpit-Secret` header, checked with `cockpit_auth.secret_matches` (constant-time). Never log the token or the secret.
- Tests run on any machine incl. `windows-latest`; no network (inject `CrewSource.rows` / fake schedule rows directly).
- Reference spec: `docs/superpowers/specs/2026-06-19-role-based-funnel-access-design.md` §C/§D, and `docs/superpowers/plans/2026-06-19-console-roles-phase3a-gate.md` (this file).

## File Structure

- **Modify** `src/relay/racecast-feeds.py`:
  - `import console_policy` alongside the other `src/scripts` imports (~line 87).
  - Module-level pure helper `schedule_keys(rows)` next to `resolve_roles` (~line 528).
  - `--crew-tab` argparse option (next to `--qualifying-tab`, ~line 3415) + `crew_source` construction/refresh/poller in `__main__` (mirroring `qual_source`).
  - `make_handler(... crew_source=None)` and pass it from `__main__`.
  - Handler methods `_console_roles(subject)` + `_console_gate(p, method)`; two-line hooks at the top of `do_GET` and `do_POST`.
- **Modify** `tests/test_roles.py` — unit-test the pure `schedule_keys` helper.
- **Create** `tests/test_console_gate.py` — live-server integration tests for the gate (a `ThreadingHTTPServer` over `make_handler`, modeled on `tests/test_pov.py`).
- **Modify** `CLAUDE.md` — document the new test file.

Relay-module loader for tests (verbatim from `tests/test_pov.py`):
```python
import importlib.util, os, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOGDIR = tempfile.mkdtemp(prefix="racecast-test-logs-")
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
```

---

### Task 1: `schedule_keys` helper + `CrewSource` live wiring

**Files:**
- Modify: `src/relay/racecast-feeds.py`
- Test: `tests/test_roles.py` (extend)

**Interfaces:**
- Consumes: `asset_key`, `resolve_roles`, `CrewSource` (all existing); the `__main__` source-wiring pattern of `qual_source`.
- Produces:
  - Module-level `schedule_keys(rows) -> set[str]` — `{asset_key(name) for (url,name,stint,line) in rows if name.strip()}`.
  - `import console_policy` available in the module.
  - `make_handler(..., crew_source=None)` accepting the live `CrewSource`.
  - In `__main__`: a `crew_source` built from `--crew-tab` (disabled, like POV/qualifying, when `--sheet-csv-url` is set), refreshed once, polled, and passed to `make_handler`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_roles.py` (before the `__main__` runner):
```python
def t_schedule_keys_normalizes_and_skips_blank():
    rows = [("https://youtu.be/a", "Alice", "1", 2),
            ("", "Bob O'Brien", "2", 3),
            ("https://youtu.be/c", "", "3", 4)]   # blank streamer -> skipped
    assert m.schedule_keys(rows) == {"alice", m.asset_key("Bob O'Brien")}


def t_schedule_keys_empty():
    assert m.schedule_keys([]) == set()
```
(`m` is the loaded relay module — `tests/test_roles.py` already loads it as `m`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_roles.py`
Expected: FAIL — `AttributeError: module 'irofeeds' has no attribute 'schedule_keys'`.

- [ ] **Step 3: Write the implementation**

3a. Add the import beside the other sibling-script imports (after `import cockpit_submissions`, ~line 90):
```python
import console_policy  # /console authorization matrix + decision (#216)
```

3b. Add the helper right after `resolve_roles` (after its `return roles`, ~line 552):
```python
def schedule_keys(rows):
    """Set of asset_key-normalized streamer names present in a schedule's rows
    ([(url, name, stint, line)]). This is the implicit commentator roster that
    resolve_roles unions with the Crew tab (#216)."""
    return {asset_key(n) for (_u, n, _s, _l) in rows if (n or "").strip()}
```

3c. Add the `--crew-tab` argument right after the `--qualifying-tab` block (~line 3417):
```python
    ap.add_argument("--crew-tab", default="Crew",
                    help="Sheet tab naming Director/Producer crew for /console roles "
                         "(#216); disabled with a custom --sheet-csv-url.")
```

3d. Build the `crew_source` in `__main__`, right after the `qual_source` block (after its `qual_source.refresh()`, ~line 3543):
```python
    # Crew roster (#216): Name | Director | Producer tab giving the director/
    # producer capabilities for /console. Like POV/qualifying it is derivable
    # only from sheet-id/tab, so a custom --sheet-csv-url disables it. Missing or
    # empty tab is non-fatal -- roles just fall back to schedule-only commentator.
    crew_source = None
    if not args.sheet_csv_url:
        crew_csv_url = (f"https://docs.google.com/spreadsheets/d/{args.sheet_id}"
                        f"/gviz/tq?tqx=out:csv&sheet={quote(args.crew_tab)}")
        crew_cache = os.path.join(runtime, "crew.cache.txt")
        crew_source = CrewSource(crew_csv_url, crew_cache)
        crew_source.refresh()   # non-fatal: empty/unreachable = no director/producer rows
```

3e. Add the poller for `crew_source` next to the qualifying poller (after the `qual_source` poller thread, ~line 3667):
```python
    if crew_source:
        threading.Thread(target=poller, args=(crew_source, args.poll, stop_evt),
                         daemon=True).start()
```

3f. Add the `crew_source` parameter to `make_handler` (signature ~line 2772, end of the kwargs):
```python
                 submission_store=None, event_store=None, crew_source=None):
```
and pass it at the `make_handler(...)` call (~line 3690), after `event_store=event_store`:
```python
                           event_store=event_store,
                           crew_source=crew_source)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_roles.py`
Expected: `ALL PASS`.
Run: `python3 tests/test_pov.py` (smoke — confirms the relay module still imports and `make_handler` still builds with the new kwarg)
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

Run: `python3 tools/lint.py`
```bash
git add src/relay/racecast-feeds.py tests/test_roles.py
git commit -m "$(cat <<'MSG'
feat(relay): wire CrewSource into the relay + schedule_keys helper (#216 phase 3a)

Constructs the live Crew roster (--crew-tab, disabled under --sheet-csv-url like
POV/qualifying), polls it, and threads it into make_handler. Adds the pure
schedule_keys() roster helper and imports console_policy. Nothing gates on it
yet -- the /console gate is the next task.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

### Task 2: the `/console` auth gate (`_console_roles`, `_console_gate`, do_GET/do_POST hooks)

**Files:**
- Modify: `src/relay/racecast-feeds.py`
- Test: `tests/test_console_gate.py` (create)

**Interfaces:**
- Consumes: `crew_source`, `cockpit_secret`, `cockpit_versions_path` (closure vars), `self._cockpit_auth()` (existing identity verify + 401/429 + rate limit), `self._console_roles`, `console_policy`, `schedule_keys`, `resolve_roles`, `relay.source.rows`.
- Produces:
  - `_console_roles(self, subject) -> set` — resolves the subject's capability set from the live schedule + crew roster.
  - `_console_gate(self, p, method) -> list | None` — returns the (possibly rewritten) segment list to fall through to when ALLOWED, or `None` after sending a response (denied / no identity / disabled).
  - Hooks at the top of `do_GET`/`do_POST`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_console_gate.py`:
```python
#!/usr/bin/env python3
"""Live-server integration checks for the /console auth gate (#216 phase 3a).
Run: python3 tests/test_console_gate.py"""
import importlib.util, os, tempfile, threading, json
import urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOGDIR = tempfile.mkdtemp(prefix="racecast-test-logs-")
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

SECRET = "s3cret-league"
_URLS8 = [f"https://www.youtube.com/watch?v=stint{i}" for i in range(1, 9)]


class _FakeSource:
    """A schedule source exposing .get() (URL list) and get_rows()/.rows (the
    (url,name,stint,line) tuples the gate reads for schedule_keys and the cockpit
    chat handler reads for the speaker name)."""
    def __init__(self, urls, rows):
        self.items = list(urls)
        self.rows = list(rows)
    def get(self): return self.items
    def get_rows(self): return self.rows
    def refresh(self, timeout=None): pass
    def health(self): return {"ok": True}


class _Crew:
    def __init__(self, rows): self._rows = list(rows)
    def get(self): return list(self._rows)


def _serve():
    rows = [("https://youtu.be/a", "Alice", "1", 2)]           # alice -> commentator
    src = _FakeSource(_URLS8, rows)
    relay = m.Relay(src, [53001, 53002], LOGDIR)
    crew = _Crew([("Bob", True, False), ("Carol", False, True)])  # bob=director, carol=producer
    handler = m.make_handler(relay, cockpit_secret=SECRET, cockpit_versions_path=None,
                             chat_store=m.ChatStore(os.path.join(LOGDIR, "chat.json")),
                             crew_source=crew)
    srv = m.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _tok(key):
    return m.cockpit_auth.mint_token(SECRET, key)


def _get(port, path, token=None, secret=None):
    url = f"http://127.0.0.1:{port}{path}"
    if token:
        url += ("&" if "?" in path else "?") + "t=" + token
    req = urllib.request.Request(url)
    if secret:
        req.add_header("X-Cockpit-Secret", secret)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def t_no_token_is_401():
    srv = _serve(); port = srv.server_address[1]
    try:
        assert _get(port, "/console/status")[0] == 401
    finally:
        srv.shutdown()


def t_any_authenticated_read_allowed():
    srv = _serve(); port = srv.server_address[1]
    try:
        code, body = _get(port, "/console/status", _tok("alice"))   # commentator -> any read ok
        assert code == 200, (code, body)
    finally:
        srv.shutdown()


def t_commentator_forbidden_from_director_op():
    srv = _serve(); port = srv.server_address[1]
    try:
        assert _get(port, "/console/next", _tok("alice"))[0] == 403
    finally:
        srv.shutdown()


def t_director_allowed_director_op():
    srv = _serve(); port = srv.server_address[1]
    try:
        assert _get(port, "/console/reload", _tok("bob"))[0] == 200
    finally:
        srv.shutdown()


def t_producer_stepup_required_without_secret():
    srv = _serve(); port = srv.server_address[1]
    try:
        assert _get(port, "/console/set/stint/2", _tok("carol"))[0] == 403
    finally:
        srv.shutdown()


def t_producer_stepup_allowed_with_secret():
    srv = _serve(); port = srv.server_address[1]
    try:
        assert _get(port, "/console/set/stint/2", _tok("carol"), secret=SECRET)[0] == 200
    finally:
        srv.shutdown()


def t_role_gate_precedes_stepup():
    # A director (not producer) with the correct secret is still FORBIDDEN.
    srv = _serve(); port = srv.server_address[1]
    try:
        assert _get(port, "/console/set/stint/2", _tok("bob"), secret=SECRET)[0] == 403
    finally:
        srv.shutdown()


def t_unknown_console_route_is_404():
    srv = _serve(); port = srv.server_address[1]
    try:
        assert _get(port, "/console/bogus", _tok("bob"))[0] == 404
    finally:
        srv.shutdown()


def t_chat_send_forces_token_identity():
    srv = _serve(); port = srv.server_address[1]
    try:
        url = f"http://127.0.0.1:{port}/console/chat/send?t=" + _tok("alice")
        body = json.dumps({"text": "hello from the console"}).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200
        code, data = _get(port, "/console/chat/data", _tok("alice"))
        assert code == 200, (code, data)
        msgs = json.loads(data).get("messages", [])
        # ChatStore messages are {"ts","user","text"}; the speaker is "user" and is
        # server-forced to the token's streamer (display name), never client-declared.
        assert any(msg.get("text") == "hello from the console"
                   and m.asset_key(msg.get("user", "")) == "alice" for msg in msgs), data
    finally:
        srv.shutdown()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

> Confirmed against `racecast-feeds.py`: `ChatStore.data()` returns `{"messages": [...]}` and each message is `{"ts","user","text"}` (speaker = `user`). The cockpit chat-send handler forces `user = cockpit_display_name(relay.source.get_rows(), me)`, so the fake source must expose `get_rows()` (it does). Do not change the gate to fit the test.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_console_gate.py`
Expected: FAIL — the `/console/*` requests currently fall through to the normal dispatch (no `console` route), so `/console/status` returns 404/empty, not 401/200. (Confirms the gate is absent.)

- [ ] **Step 3: Write the implementation**

3a. Add the two handler methods next to `_cockpit_auth` (after it, ~line 2900). `_console_roles` reads the live schedule + crew; `_console_gate` is the authorize-and-fall-through core:
```python
        def _console_roles(self, subject):
            """Resolve a verified subject to its capability set from the live
            schedule (commentator) + Crew roster (director/producer)."""
            src = getattr(relay, "source", None)
            if src is not None and hasattr(src, "get_rows"):
                rows = src.get_rows()
            else:
                rows = getattr(src, "rows", []) or []
            crew = crew_source.get() if crew_source else []
            return resolve_roles(crew, schedule_keys(rows), subject)

        def _console_gate(self, p, method):
            """Authorize a /console/* request and return the segment list to fall
            through to (ALLOW), or None after sending a response. p includes the
            leading 'console'. Identity-bound routes are rewritten to their
            identity-forced /cockpit equivalents so the server sets the speaker.
            Boundary: when no league cockpit secret is configured, /console 404s
            exactly like /cockpit."""
            if not cockpit_secret:
                self._send({"error": "not found"}, 404)
                return None
            sub = p[1:]
            subject = self._cockpit_auth()        # identity only; sends 401/429 on failure
            if subject is None:
                return None
            roles = self._console_roles(subject)
            presented = self.headers.get("X-Cockpit-Secret")
            has_step_up = bool(presented) and cockpit_auth.secret_matches(presented, cockpit_secret)
            outcome = console_policy.decide(roles, sub, method, has_step_up)
            if outcome == console_policy.ALLOW:
                if sub == ["chat", "send"]:
                    return ["cockpit", "chat", "send"]
                if sub == ["chat", "data"]:
                    return ["cockpit", "chat", "data"]
                if sub == ["submit"]:
                    return ["cockpit", "submit"]
                return sub
            if outcome == console_policy.STEP_UP_REQUIRED:
                self._send({"error": "step-up required"}, 403)
                return None
            if outcome == console_policy.FORBIDDEN:
                self._send({"error": "forbidden"}, 403)
                return None
            self._send({"error": "not found"}, 404)   # NOT_FOUND
            return None
```

3b. Hook the gate at the top of `do_GET` — replace:
```python
        def do_GET(self):
            p = [x for x in urlparse(self.path).path.split("/") if x]
            try:
                if not p or p == ["status"]:
```
with (insert the 4 lines after `try:`):
```python
        def do_GET(self):
            p = [x for x in urlparse(self.path).path.split("/") if x]
            try:
                if p and p[0] == "console":
                    p = self._console_gate(p, "GET")
                    if p is None:
                        return
                if not p or p == ["status"]:
```

3c. Hook the gate at the top of `do_POST` — replace:
```python
        def do_POST(self):
            p = [x for x in urlparse(self.path).path.split("/") if x]
            try:
                length = int(self.headers.get("Content-Length") or 0)
```
with:
```python
        def do_POST(self):
            p = [x for x in urlparse(self.path).path.split("/") if x]
            try:
                if p and p[0] == "console":
                    p = self._console_gate(p, "POST")
                    if p is None:
                        return
                length = int(self.headers.get("Content-Length") or 0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_console_gate.py`
Expected: `ok t_any_authenticated_read_allowed` … `ALL PASS`.
Run: `python3 tests/test_pov.py` and `python3 tests/test_cockpit.py`
Expected: `ALL PASS` (the existing root + cockpit routes are unchanged).

- [ ] **Step 5: Lint + commit**

Run: `python3 tools/lint.py`
```bash
git add src/relay/racecast-feeds.py tests/test_console_gate.py
git commit -m "$(cat <<'MSG'
feat(relay): /console auth gate with role-gated fall-through (#216 phase 3a)

Top-of-dispatch gate: verify token identity (reusing _cockpit_auth), resolve
roles from the live schedule + Crew roster, decide via console_policy, and on
ALLOW fall through to the identical root handler. Identity-bound routes
(chat/send, chat/data, submit) are rewritten to their identity-forced /cockpit
equivalents. Deny -> 401/403/404. Root and /cockpit routes unchanged; nothing
is funnelled yet (Phase 4).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

### Task 3: Documentation + full local gate

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: everything above.
- Produces: green full suite + build, documented test entry.

- [ ] **Step 1: Add the test to the documented list**

In `CLAUDE.md`, in the `## Commands` test block, add a line after the `tests/test_console.py` entry (match the column alignment):
```
python3 tests/test_console_gate.py   # /console auth gate: token->roles->decide fall-through (#216)
```

- [ ] **Step 2: Run the whole suite**

Run: `python3 tools/run-tests.py`
Expected: ends with `ALL TEST FILES PASS` (includes `== test_console_gate.py`).

- [ ] **Step 3: Lint**

Run: `python3 tools/lint.py`
Expected: no errors.

- [ ] **Step 4: Build self-verify**

Run: `python3 tools/build.py`
Expected: exits 0. Do NOT `git add` the gitignored `dist/` artifacts; `git status` before committing must show only `CLAUDE.md`.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'MSG'
docs: list test_console_gate.py in the CLAUDE.md test index (#216 phase 3a)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

## Self-Review

**Spec coverage (Phase 3a scope only):**
- Spec §B "wire `CrewSource` into the relay's live refresh loop" → Task 1. ✓
- Spec §C/§D + "`_console_auth()` … dispatches to the same handler logic after a per-endpoint role check; no business logic duplicated" → Task 2 gate with fall-through + the matrix as allowlist. ✓
- Spec §C "chat/send (identity server-forced)" → Task 2 rewrites `chat/send`/`chat/data`/`submit` to the `/cockpit` identity-forced handlers. ✓
- Spec §D step-up via shared producer secret → `X-Cockpit-Secret` + `secret_matches`, role-gate-before-step-up (enforced by `decide`, asserted by `t_role_gate_precedes_stepup`). ✓
- Boundary invariant (root/`/cockpit` unchanged; nothing funnelled) → no existing route touched; `test_pov.py`/`test_cockpit.py` re-run green. ✓
- Deliberately out of Phase 3a (Phase 3b+): the `/console` launcher + cockpit/panel/prod **pages**, the `rc_cockpit` cookie at `Path=/console`, the `window.RC_API_BASE` base-path switch, the Funnel mount (Phase 4), the link CLI (Phase 5), and the e2e gating check (added when pages land / Phase 3b).

**Placeholder scan:** none — complete code and exact commands throughout. The one conditional note (chat `from` key) instructs verifying the real key against `racecast-feeds.py` before writing, and is a test-only adjustment, not a logic placeholder.

**Type consistency:** `schedule_keys(rows) -> set` and `resolve_roles(crew_rows, schedule_keys, subject)` compose (Task 1's set feeds Phase 1's resolver); `_console_gate` returns `list | None` consumed by `p = self._console_gate(...)` / `if p is None: return`; `console_policy.ALLOW/FORBIDDEN/STEP_UP_REQUIRED/NOT_FOUND` and `decide(roles, segments, method, has_step_up)` match the Phase 2 module exactly; `cockpit_auth.secret_matches(presented, secret)` argument order matches the existing signature.

**Security note:** the gate reuses `_cockpit_auth` (token verify + per-source-IP failure rate limit) for identity, then enforces roles via the audited matrix BEFORE any fall-through, so a lower-privileged token can never reach a higher-capability handler. `secret_matches` is constant-time; `presented` is only read from a request header and never logged. The fall-through executes the identical, already-trusted root handler — no new write path is introduced.
