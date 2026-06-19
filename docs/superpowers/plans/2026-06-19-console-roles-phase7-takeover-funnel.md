# Phase 7 — Producer takeover over Funnel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let producer B take over producer A's live state when A is reachable only
over the public Tailscale **Funnel** (B has no Tailscale account / different network),
by exposing the takeover **pull** state under a producer + step-up gated
`/console/takeover/*` namespace and teaching `racecast event takeover … --funnel` to
read it.

**Architecture:** Reuse the already-merged machinery. The `/console` auth gate + the
capability matrix already reserve `["takeover", …] → producer + step-up`
(`console_policy.py`), so Phase 7 adds (1) three **consolidated** read endpoints under
`/console/takeover/` — `status` (a redacted allowlist: `live`/`league`/`event_title`/
`timer`/`mode`, **never** the feed stream URLs that the tailnet `/status` exposes),
`chat`, `versions` — wired through the existing gate; and (2) a `--funnel` path in
`event_takeover` that fetches those over `https://<magicdns>/console/takeover/*` with
the league `COCKPIT_SECRET` as the `X-Cockpit-Secret` step-up header, then runs the
unchanged `takeover_plan`/`league_guard`/`chat`/`versions`/`event start` flow.

**Tech Stack:** Pure Python stdlib (relay + CLI), runnable-script tests (no pytest),
Tailscale Funnel (HTTPS, MagicDNS).

## Global Constraints

- **Edit only under `src/`** (+ `tests/`, `docs/`). `dist/`/`runtime/` are generated.
- **All scripts and docs English only.**
- **Security boundary (the epic invariant):** only `/console` is Funnel-mounted. The
  new takeover endpoints live **under `/console/takeover/`** and are reached ONLY through
  `_console_gate` (producer + step-up). The redacted `/console/takeover/status` MUST be
  built by an **allowlist** (`live`, `league`, `event_title`, `timer`, `mode`) so it can
  never leak feed `channel`/`pov.url` stream URLs over the public internet. Root
  `/status`, `/chat/data`, `/cockpit/versions` stay tailnet/loopback as today.
- **Step-up over Funnel = the shared per-league `COCKPIT_SECRET`** (same league = same
  secret, travels with `profile export`). It rides as the `X-Cockpit-Secret` header,
  validated by the existing `cockpit_auth.secret_matches` (constant-time). Never log it.
- **The tailnet takeover path is unchanged.** `event takeover <100.x-ip>` (no `--funnel`)
  keeps using `http://<ip>:<port>/status` + `chat pull` + `cockpit pull-versions` exactly
  as today. `--funnel` is a parallel path; do not refactor the tailnet path's behavior.
- **Reuse, don't duplicate:** chat apply is `ca.apply_pulled`, versions apply is
  `cpadm.apply_pulled` — the funnel path reuses both (only the fetch differs).
- **No new deps; relay stays stdlib-only.** No machine paths / real IPs in committed
  files (Tailscale test IPs are `100.64.0.0/10`; MagicDNS test hosts are fake, e.g.
  `producer-a.example.ts.net`). No secrets in tests.
- **No Control Center / UI change in this phase** (funnel takeover is CLI; bring-up stays
  local `event start`). So **no wiki screenshot** is due — do not touch `cc-*.png`.
- Local gate green before each PR: `python3 tools/run-tests.py`, `python3 tools/lint.py`,
  `python3 tools/build.py` (exit 0). Relay change ⇒ also `python3 tests/test_pov.py`.

---

### Task 1: Relay `/console/takeover/{status,chat,versions}` endpoints

**Files:**
- Modify: `src/relay/racecast-feeds.py`
  - In `_console_gate` (the `outcome == console_policy.ALLOW` block, after the existing
    `chat/send`, `chat/data`, `submit` rewrites): rewrite the two reuse cases.
  - In `do_GET`, add the redacted `["takeover", "status"]` handler (near the existing
    `["status"]` handler at ~line 3103).
- Test: `tests/test_console_gate.py` (producer + step-up gating for `/console/takeover/*`
  + the redaction assertion). Relay regression: `tests/test_pov.py`.

**Interfaces:**
- Consumes: `relay.status()` (carries `live`, `league`, `mode`), `event_store`,
  `timer_store`, `console_policy` (already maps `["takeover", …] → PRODUCER, step_up`),
  `_console_gate`.
- Produces: `GET /console/takeover/status` → `{live, league, event_title, timer, mode}`
  (no stream URLs); `GET /console/takeover/chat` → `{messages:[…]}` (via `/chat/data`);
  `GET /console/takeover/versions` → `{versions:{…}}` (via `/cockpit/versions`).

- [ ] **Step 1: Write the failing gate + redaction tests** in `tests/test_console_gate.py`
  (mirror the existing harness — the file already drives `/console/...` requests with a
  minted token and an optional `X-Cockpit-Secret` header; reuse its client/fixtures):

```python
def t_takeover_status_needs_producer_and_step_up():
    # No token -> 401; producer token WITHOUT the secret -> 403 step-up; producer
    # token WITH the secret -> 200 and a REDACTED body (no feed stream URLs).
    code, _ = _console_get("/console/takeover/status")                  # no auth
    assert code == 401
    code, _ = _console_get("/console/takeover/status", token=PRODUCER)  # no secret
    assert code == 403
    code, body = _console_get("/console/takeover/status",
                              token=PRODUCER, secret=SECRET)
    assert code == 200, body
    assert "live" in body and "league" in body
    # Redaction: the public takeover status must NOT carry the feed map / URLs.
    assert "feeds" not in body and "pov" not in body
    blob = json.dumps(body)
    assert "youtube" not in blob.lower() and "http" not in blob.lower()


def t_takeover_director_without_producer_is_forbidden():
    # A director (no producer role) is rejected even with the secret.
    code, _ = _console_get("/console/takeover/status",
                           token=DIRECTOR_ONLY, secret=SECRET)
    assert code == 403


def t_takeover_chat_and_versions_gated_and_routed():
    code, body = _console_get("/console/takeover/chat",
                              token=PRODUCER, secret=SECRET)
    assert code == 200 and "messages" in body
    code, body = _console_get("/console/takeover/versions",
                              token=PRODUCER, secret=SECRET)
    assert code == 200 and "versions" in body
    # Without the step-up secret both are 403.
    assert _console_get("/console/takeover/chat", token=PRODUCER)[0] == 403
    assert _console_get("/console/takeover/versions", token=PRODUCER)[0] == 403
```

> Token/secret fixtures (`PRODUCER`, `DIRECTOR_ONLY`, `SECRET`, the `_console_get`
> helper) already exist in `test_console_gate.py` for the `set/stint` + `mode`
> producer+step-up tests — reuse them; do not invent a new harness. If a producer
> token fixture is not present, mint one the same way the existing step-up tests do
> (a streamer tagged producer in the test Crew roster).

- [ ] **Step 2: Run — verify they fail**

Run: `python3 tests/test_console_gate.py`
Expected: FAIL — `/console/takeover/*` currently 404s (ALLOW falls through to no handler).

- [ ] **Step 3: Add the two reuse rewrites in `_console_gate`** (in the
  `if outcome == console_policy.ALLOW:` block, beside the existing rewrites):

```python
                if sub == ["takeover", "chat"]:
                    return ["chat", "data"]          # full history, gated producer+step-up
                if sub == ["takeover", "versions"]:
                    return ["cockpit", "versions"]   # secret already step-up-verified above
```

- [ ] **Step 4: Add the redacted `["takeover", "status"]` handler in `do_GET`** (right
  after the `if not p or p == ["status"]:` block at ~line 3103). Build it by **allowlist**
  so feed stream URLs can never leak:

```python
                if p == ["takeover", "status"]:
                    # Funnel-exposed (producer + step-up via _console_gate). Redacted:
                    # ONLY the fields a takeover needs — NEVER the feeds/pov stream URLs
                    # that the tailnet /status carries (this leaves the tailnet).
                    full = relay.status()
                    return self._send({
                        "live": full.get("live"),
                        "league": full.get("league"),
                        "mode": full.get("mode"),
                        "event_title": event_store.get() if event_store else "",
                        "timer": timer_store.summary() if timer_store else None,
                    })
```

- [ ] **Step 5: Run the gate tests — verify they pass**

Run: `python3 tests/test_console_gate.py`
Expected: PASS (`ALL PASS`).

- [ ] **Step 6: Relay regression + lint**

Run: `python3 tests/test_pov.py` (Expected: `ALL PASS`) and `python3 tools/lint.py`
(Expected: clean).

- [ ] **Step 7: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_console_gate.py
git commit -m "feat(relay): /console/takeover/{status,chat,versions} for Funnel takeover (producer+step-up)"
```

---

### Task 2: CLI `event takeover … --funnel`

**Files:**
- Modify: `src/racecast.py`
  - Add helpers `_active_cockpit_secret()`, `_funnel_takeover_base(host)`,
    `_takeover_get(url, secret=None, timeout=5)` (near `_relay_fetch_json`, ~line 1414).
  - Extend `event_takeover(rest)` (~line 2488): parse `--funnel`; when set, build the
    funnel base + secret, fetch the redacted status, pull chat + versions over funnel
    (reusing `ca.apply_pulled` / `cpadm.apply_pulled`), and distinguish auth-rejected
    (401/403 → abort with a clear secret error) from unreachable (network → fall back to
    `--stint`, like today). The tailnet branch is unchanged.
  - Update the `event takeover` usage string + the `racecast.py` top-of-file help comment
    (the `# racecast event takeover …` line) to mention `--funnel`.
- Test: `tests/test_racecast.py` (parse + funnel URL build + secret-missing + auth-reject
  + success-calls-event_start; stub `_takeover_get`, `event_start`, the apply funcs).

**Interfaces:**
- Consumes: `takeover_plan`, `league_guard`, `_takeover_event_title`, `event_start`,
  `ca.apply_pulled`, `cpadm.apply_pulled`, the chat-store path helper used by `chat_cmd`,
  `_cockpit_versions_path()`, `_apply_active_profile_env()`.
- Produces: `racecast event takeover <host> --funnel [--stint N] [--qualifying] [--force]`.

- [ ] **Step 1: Write the failing CLI tests** in `tests/test_racecast.py` (append; module
  alias is `m`; stub the network + bring-up like the existing `event takeover` tests at
  ~line 1528):

```python
def t_funnel_takeover_base_builds_console_url():
    assert m._funnel_takeover_base("producer-a.example.ts.net") == \
        "https://producer-a.example.ts.net/console/takeover"
    assert m._funnel_takeover_base("https://producer-a.example.ts.net/console") == \
        "https://producer-a.example.ts.net/console/takeover"
    assert m._funnel_takeover_base("http://producer-a.example.ts.net/") == \
        "https://producer-a.example.ts.net/console/takeover"


def t_event_takeover_funnel_requires_secret(monkey_env):
    # --funnel with no COCKPIT_SECRET in the active profile -> clear abort.
    _set_env(monkey_env, RACECAST_COCKPIT_SECRET="", RACECAST_SHEET_ID="L1")
    try:
        m.event_takeover(["producer-a.example.ts.net", "--funnel", "--stint", "3"])
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert "secret" in str(e).lower() or "cockpit_secret" in str(e).lower()


def t_event_takeover_funnel_auth_rejected_aborts():
    # A 403/401 from the funnel endpoint means a bad/missing secret — abort, do NOT
    # silently fall back (unlike a network failure).
    import urllib.error
    def fake_get(url, secret=None, timeout=5):
        raise urllib.error.HTTPError(url, 403, "forbidden", {}, None)
    orig_get, m._takeover_get = m._takeover_get, fake_get
    orig_es, m.event_start = m.event_start, lambda a: (_ for _ in ()).throw(
        AssertionError("event_start must not run on auth-reject"))
    _set_secret("S")
    try:
        m.event_takeover(["producer-a.example.ts.net", "--funnel", "--stint", "3"])
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert "secret" in str(e).lower() or "rejected" in str(e).lower()
    finally:
        m._takeover_get, m.event_start = orig_get, orig_es


def t_event_takeover_funnel_success_calls_event_start():
    seen = {}
    def fake_get(url, secret=None, timeout=5):
        seen.setdefault("urls", []).append(url)
        seen["secret"] = secret
        if url.endswith("/status"):
            return {"live": {"feed": "A", "stint": 3, "mode": "race"},
                    "league": {"sheet_id": "L1"}, "event_title": "", "timer": None}
        if url.endswith("/chat"):
            return {"messages": []}
        if url.endswith("/versions"):
            return {"versions": {}}
        return {}
    orig_get, m._takeover_get = m._takeover_get, fake_get
    es = {}
    orig_es, m.event_start = m.event_start, lambda a: es.update(args=a)
    _set_secret("S"); _set_sheet("L1")
    try:
        m.event_takeover(["producer-a.example.ts.net", "--funnel"])
    finally:
        m._takeover_get, m.event_start = orig_get, orig_es
    assert es.get("args") == ["--stint", "3"], es           # derived from A's live.stint
    assert all(u.startswith("https://producer-a.example.ts.net/console/takeover")
               for u in seen["urls"])
    assert seen["secret"] == "S"                            # step-up header sent
```

> Adapt the env/secret/sheet stub helpers (`_set_secret`, `_set_sheet`, `_set_env`) to
> whatever the existing `event takeover` / cockpit tests in `test_racecast.py` already
> use to set `RACECAST_COCKPIT_SECRET` / `RACECAST_SHEET_ID` / `RACECAST_SHEET_PUSH_URL`
> in the process env. Do not invent a new fixture style; match the file.

- [ ] **Step 2: Run — verify they fail**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `_funnel_takeover_base` / `_takeover_get` not defined; `--funnel` unhandled.

- [ ] **Step 3: Add the funnel helpers** in `src/racecast.py` (near `_relay_fetch_json`):

```python
def _active_cockpit_secret():
    """The active league's COCKPIT_SECRET from the resolved profile env ('' if unset).
    Same league = same secret (it travels with `profile export`), so producer B already
    holds A's secret — no typing needed for a same-league takeover."""
    _apply_active_profile_env()
    return (os.environ.get("RACECAST_COCKPIT_SECRET") or "").strip()


def _funnel_takeover_base(host):
    """`https://<magicdns-host>/console/takeover` from a MagicDNS host or a pasted URL.
    Strips any scheme and trailing path (e.g. '.../console') the operator pasted."""
    host = (host or "").strip()
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].rstrip("/")
    return "https://%s/console/takeover" % host


def _takeover_get(url, secret=None, timeout=5):
    """GET a (funnel) takeover endpoint with the step-up secret header. Raises
    urllib HTTPError on 401/403 (bad secret) so the caller can distinguish auth
    rejection from a network failure."""
    import urllib.request
    headers = {"X-Cockpit-Secret": secret} if secret else {}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))
```

- [ ] **Step 4: Branch `event_takeover` on `--funnel`.** Add `funnel = "--funnel" in args`
  after the existing flag parsing, then split the status fetch and the chat/versions pulls.
  Keep the tailnet branch byte-for-byte as today; add the funnel branch:

```python
    funnel = "--funnel" in args
    secret = _active_cockpit_secret() if funnel else None
    if funnel and not secret:
        sys.exit("racecast: --funnel takeover needs the league COCKPIT_SECRET in your "
                 "active profile (same league as A). Set it, or use the tailnet IP.")
    base = _funnel_takeover_base(host) if funnel else None

    status = None
    if funnel:
        try:
            fetched = _takeover_get(base + "/status", secret)
            status = fetched if isinstance(fetched, dict) else None
        except Exception as exc:
            code = getattr(exc, "code", None)
            if code in (401, 403):
                sys.exit("racecast: producer A rejected the step-up secret (HTTP "
                         f"{code}) — check the league COCKPIT_SECRET matches A's.")
            status = None                 # network/unreachable -> fall back to --stint
    else:
        try:
            fetched = _relay_fetch_json(f"http://{host}:{port}/status")
            status = fetched if isinstance(fetched, dict) else None
        except Exception:
            status = None
```

  Then for the chat + versions pulls, replace the two `chat_cmd`/`cockpit_cmd` calls with
  a funnel-aware version (tailnet path unchanged):

```python
    try:                                    # best-effort: a chat failure must not abort
        if funnel:
            payload = _takeover_get(base + "/chat", secret)
            n = ca.apply_pulled(_chat_path(), payload)
            _chat_reload_if_running()
            print(f"Pulled {n} messages from A (funnel).")
        else:
            chat_cmd(["pull", host, "--port", str(port)])
    except SystemExit:
        print("note: chat pull failed — continuing takeover.")
    except Exception as exc:
        print(f"note: chat pull failed ({type(exc).__name__}) — continuing takeover.")

    try:                                    # best-effort: cockpit pull must not abort
        if funnel:
            payload = _takeover_get(base + "/versions", secret)
            count = cpadm.apply_pulled(_cockpit_versions_path(), payload)
            print(f"pulled {count} cockpit version record(s) from A (funnel).")
        else:
            cockpit_cmd(["pull-versions", host, "--port", str(port)])
    except SystemExit:
        print("note: cockpit-versions pull failed — continuing takeover.")
    except Exception as exc:
        print(f"note: cockpit-versions pull failed ({type(exc).__name__}) — continuing.")
```

  > Use the SAME chat-store path + reload helper that `chat_cmd`'s `pull` branch uses
  > (find it — it computes `path` and calls `ca.apply_pulled(path, …)` + a reload). Name
  > the helper here `_chat_path()` if one exists; otherwise extract the path
  > expression `chat_cmd` uses into a tiny shared helper and call it from both. Do NOT
  > duplicate the apply logic — only the fetch differs.

- [ ] **Step 5: Update the usage string + help comment.** In `event_takeover`'s `sys.exit`
  usage line add `[--funnel]`, and update the top-of-file `# racecast event takeover …`
  comment to note `--funnel <magicdns-host>` (takeover over the public Funnel using the
  league secret). Grep the repo for the old usage text to catch any duplicate.

- [ ] **Step 6: Run — verify they pass**

Run: `python3 tests/test_racecast.py`
Expected: PASS (`ALL PASS`).

- [ ] **Step 7: Lint**

Run: `python3 tools/lint.py` → clean.

- [ ] **Step 8: Commit**

```bash
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(event): event takeover --funnel (pull A's state over the public Funnel)"
```

---

### Task 3: Docs + final gate

**Files:**
- Modify: `CLAUDE.md` — the `event takeover` line + the cockpit/console architecture
  section: document `--funnel`, the `/console/takeover/{status,chat,versions}` producer +
  step-up endpoints, the redacted status (no stream URLs), and the secret-as-step-up.
- Modify: `README.md` — the `event takeover` quickstart line gains `--funnel <host>`.
- Modify: the relevant wiki page — `src/docs/wiki/Commentator-Cockpit.md` (the
  console/Funnel security narrative) and/or a takeover/Funnel section: add how a remote
  producer takes over over Funnel (needs `racecast funnel on` on A, the league secret in
  B's profile), and the boundary note (only `/console` mounted; takeover status redacted).
- Create/commit: this plan doc.

**Interfaces:** none (docs only).

- [ ] **Step 1: Update `CLAUDE.md`** — concise, matching the file's prose: the
  `event takeover` bullet gets `--funnel <magicdns-host>`; the cockpit section notes the
  new producer+step-up `/console/takeover/*` pull endpoints and that only `/console` is
  funnel-mounted (the boundary is preserved — takeover status is redacted of stream URLs).

- [ ] **Step 2: Update `README.md`** — the takeover quickstart line: add the `--funnel`
  form with a one-line note (remote producer, no Tailscale account; needs the league
  secret + `funnel on` on A).

- [ ] **Step 3: Update the wiki** — add a short "Takeover over Funnel" subsection to the
  cockpit/console wiki page: prerequisites (A runs `racecast funnel on`; B's profile has
  the league `COCKPIT_SECRET`), the command, and the security boundary (producer + step-up,
  redacted status, only `/console` public). English; no real hosts/secrets.

- [ ] **Step 4: Full local gate**

Run: `python3 tools/run-tests.py` (ALL TEST FILES PASS), `python3 tools/lint.py` (clean),
`python3 tools/build.py` (exit 0), `python3 tests/test_pov.py` (ALL PASS).

- [ ] **Step 5: Commit (docs + plan)**

```bash
git add docs/superpowers/plans/2026-06-19-console-roles-phase7-takeover-funnel.md \
        CLAUDE.md README.md src/docs/wiki/Commentator-Cockpit.md
git commit -m "docs(takeover): event takeover --funnel + /console/takeover security boundary"
```

---

## Self-Review

- **Spec coverage (§H):** takeover pull endpoints under `/console`, producer + step-up ✓
  (Task 1; matrix already enforces it); `event_takeover` accepts a Funnel MagicDNS host +
  the producer secret ✓ (Task 2); bring-up stays local `event start --stint N` ✓ (the
  funnel path still ends in `event_start`).
- **Decision honored:** 3 consolidated endpoints (`status`/`chat`/`versions`, status
  carries live/league/event_title/timer); `--funnel` flag (explicit, not auto-detect).
- **Security:** redacted status by allowlist (no stream URLs leave the tailnet); step-up
  is the shared per-league secret; auth-reject (401/403) aborts loudly, network-fail falls
  back to `--stint`; only `/console` funnel-mounted (unchanged); secret never logged.
- **No duplication:** chat/versions reuse `ca.apply_pulled`/`cpadm.apply_pulled`; the
  relay reuses `/chat/data` + `/cockpit/versions` via gate rewrites; only `/console/takeover/
  status` is new (and minimal).
- **Type consistency:** `_takeover_get(url, secret, timeout)` raises HTTPError on 401/403
  (the funnel branch checks `getattr(exc,"code",None)`); `_funnel_takeover_base` returns the
  `…/console/takeover` base both branches append `/status|/chat|/versions` to.
- **No UI change → no screenshot due** (CLAUDE.md rule N/A this phase).
- **Tailnet path untouched** — `event takeover <100.x-ip>` behaves exactly as before.
```
