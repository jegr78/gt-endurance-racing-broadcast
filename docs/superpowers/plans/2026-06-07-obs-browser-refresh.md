# OBS Browser-Source Auto-Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically refresh the relay-served OBS browser sources (HUD + race timer) when their pages changed, so a stale page can never go on air after a package update — replacing the manual right-click → Refresh.

**Architecture:** A new `refresh_browser_inputs()` in the existing minimal obs-websocket client presses the `refreshnocache` properties button on every `browser_source` whose URL points at the relay (`127.0.0.1:8088`). A hash gate in `iro.py` compares the **served** page bytes (`GET /hud` + `/timer`) against `runtime/obs-pages.hash` and only refreshes on change; the hash is persisted only after a successful refresh. Hooks: `iro relay start` (after the control port answers), `iro event start` (after OBS is up), and a manual `iro obs refresh`.

**Tech Stack:** Pure Python stdlib (repo rule: no packages, no pytest). Tests are runnable scripts with `t_*` functions. obs-websocket v5 protocol over a hand-rolled RFC 6455 client (`src/scripts/obs_ws.py`).

**Spec:** `docs/superpowers/specs/2026-06-07-obs-browser-refresh-design.md`

**Spec deviation (settled with the user):** the staleness hash is computed over
the bytes the relay actually **serves** (`GET /hud` + `/timer`), not over the
files on disk. A still-running OLD relay after a binary update serves old
pages; a file hash would refresh OBS and persist the NEW hash while OBS never
saw the new pages. The served hash makes that impossible and doubles as the
"relay is up" probe. Task 1 amends the spec.

**Conventions that apply to every task:**
- Run `python3 tools/lint.py` after changing any Python file; `--fix` auto-corrects. Match the file's existing `# noqa: BLE001` style if ruff flags a broad `except Exception` that the best-effort contract requires.
- Tests run with `python3 tests/test_<name>.py` — expected final line: `ALL PASS`.
- All code/comments/docs in English.

---

### Task 1: Amend the spec (served-bytes hashing)

**Files:**
- Modify: `docs/superpowers/specs/2026-06-07-obs-browser-refresh-design.md`

- [ ] **Step 1: Update the hash row in the decisions table**

In the "Decisions" table, replace the "When to refresh" row's text with:

```markdown
| When to refresh | Hash-gated (option 1+3 from brainstorming): only when the page content actually changed since the last successful refresh. The hash is computed over the bytes the relay actually **serves** (`GET /hud` + `/timer`), not the files on disk — a still-running old relay can then never advance the gate past pages OBS has not seen, and the fetch doubles as the "relay is up" probe. A mid-event relay restart (`event start --stint N` takeover) must not flicker the on-air HUD. |
```

- [ ] **Step 2: Update section "2. Staleness gate"**

Replace the first two bullets of section "### 2. Staleness gate" with:

```markdown
- Hash: SHA-256 over the concatenated response bytes of `GET /hud` and
  `GET /timer` from the running relay (the two OBS-source pages; `/panel` is a
  tablet page, not an OBS source). Hashing what the relay *serves* (instead of
  the files on disk) closes an update race: after a binary update with the old
  relay still running, a file hash would refresh OBS against old served pages
  and wrongly persist the new hash. If any page cannot be fetched (relay down,
  `--no-hud`/`--no-timer`), the hook skips with a notice and keeps the hash.
- State file: `runtime/obs-pages.hash` (plain hex digest, one line).
```

- [ ] **Step 3: Update the architecture diagram's hash line**

In the ASCII diagram, replace the line
`├─ hash(hud.html + timer.html) == runtime/obs-pages.hash? → done (no flicker)`
with
`├─ hash(GET /hud + GET /timer) == runtime/obs-pages.hash? → done (no flicker)`

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-06-07-obs-browser-refresh-design.md
git commit -m "docs(spec): obs-refresh staleness hash uses served page bytes"
```

---

### Task 2: `browser_input_names()` — pure browser-source filter

**Files:**
- Modify: `src/scripts/obs_ws.py` (next to `feed_input_names`, ~line 169)
- Test: `tests/test_obsws.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_obsws.py` after the `feed_input_names` tests (~line 167):

```python
# --------------------------------------------------------------------------
# Which OBS browser sources show relay-served pages?
# --------------------------------------------------------------------------
def t_browser_input_names_picks_relay_pages():
    inputs = [{"inputName": "HUD Lower Third", "inputKind": "browser_source"},
              {"inputName": "HUD Race Timer", "inputKind": "browser_source"},
              {"inputName": "Docs Panel", "inputKind": "browser_source"},
              {"inputName": "Feed A", "inputKind": "ffmpeg_source"}]
    settings = {"HUD Lower Third": {"url": "http://127.0.0.1:8088/hud"},
                "HUD Race Timer": {"url": "http://127.0.0.1:8088/timer"},
                "Docs Panel": {"url": "https://example.com/docs"},
                "Feed A": {"input": "http://127.0.0.1:53001"}}
    names = m.browser_input_names(inputs, lambda n: settings.get(n, {}),
                                  needle="127.0.0.1:8088")
    assert names == ["HUD Lower Third", "HUD Race Timer"]


def t_browser_input_names_tolerates_settings_failure():
    inputs = [{"inputName": "A", "inputKind": "browser_source"}]
    def boom(name):
        raise RuntimeError("no settings")
    assert m.browser_input_names(inputs, boom) == []


def t_browser_input_names_ignores_local_file_pages():
    # A browser source rendering a local HTML file has no url to match.
    inputs = [{"inputName": "Local HTML", "inputKind": "browser_source"}]
    assert m.browser_input_names(
        inputs, lambda n: {"is_local_file": True, "local_file": "/x/p.html"}) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_obsws.py`
Expected: `AttributeError: module 'obs_ws' has no attribute 'browser_input_names'`

- [ ] **Step 3: Implement `browser_input_names()`**

Add to `src/scripts/obs_ws.py` directly below `feed_input_names()`:

```python
def browser_input_names(inputs, get_settings, needle="127.0.0.1:8088"):
    """Which browser sources show relay-served pages (HUD, race timer)?
    Matches by URL substring so any future relay page is covered without a
    name list; local-file pages and other URLs are left alone."""
    names = []
    for inp in inputs:
        if inp.get("inputKind") != "browser_source":
            continue
        name = inp.get("inputName")
        try:
            settings = get_settings(name) or {}
        except Exception:                            # one bad input must not stop the rest
            continue
        url = settings.get("url")
        if isinstance(url, str) and needle in url:
            names.append(name)
    return names
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_obsws.py`
Expected: `ALL PASS`

- [ ] **Step 5: Lint and commit**

```bash
python3 tools/lint.py
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): pure filter for relay-pointing browser sources"
```

---

### Task 3: Extract `_open_session()` + `_Session.close()` (behavior-preserving refactor)

The connect/upgrade/identify boilerplate currently lives inline in
`release_feed_inputs()`; `refresh_browser_inputs()` (Task 4) needs the same.
Extract it. The existing fake-server e2e tests are the safety net — no new
tests in this task.

**Files:**
- Modify: `src/scripts/obs_ws.py:215-317` (`_Session`, `release_feed_inputs`)

- [ ] **Step 1: Add `_Session.close()`**

Add this method to the `_Session` class (after `request()`):

```python
    def close(self):
        try:
            self.sock.sendall(encode_frame(b"", opcode=0x8))   # polite close
        except OSError:
            pass  # OBS may have dropped the socket first — close is courtesy only
        self.sock.close()
```

- [ ] **Step 2: Add `_open_session()` and `_connect()`**

Add between the `_Session` class and `release_feed_inputs()`:

```python
def _open_session(host, port, password, timeout):
    """Connect + WebSocket upgrade + obs-websocket identify. Returns an
    identified _Session; raises on any failure (callers translate that into
    their best-effort (names, note) contract)."""
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall(handshake_request(host, port, key))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError("OBS closed during the handshake")
            response += chunk
        session = _Session(sock, parse_handshake(response, key))
        hello = session.next_json()
        session.send_json(identify_payload(hello, password))
        identified = session.next_json()
        if identified.get("op") != 2:
            raise ValueError("OBS WebSocket identify failed")
        return session
    except Exception:
        sock.close()
        raise


def _connect(host, port, password, timeout):
    """(session, "") or (None, reason). Port + password fall back to OBS's own
    obs-websocket config / IRO_OBS_WS_PASSWORD; never raises."""
    cfg = read_ws_config(default_config_path())
    if port is None:
        port = (cfg or {}).get("port") or DEFAULT_PORT
    if password is None:
        password = find_password(os.environ, default_config_path())
    try:
        return _open_session(host, port, password, timeout), ""
    except OSError:
        return None, f"OBS WebSocket not reachable on {host}:{port} (OBS not running?)"
    except Exception as exc:                         # noqa: BLE001 — best-effort contract
        return None, str(exc) or exc.__class__.__name__
```

- [ ] **Step 3: Rewrite `release_feed_inputs()` on top of the helpers**

Replace the entire body of `release_feed_inputs()` (keep the signature and
docstring unchanged):

```python
def release_feed_inputs(ports=RELAY_PORTS, host="127.0.0.1", port=None,
                        password=None, timeout=2.0):
    """Make OBS drop its connections to the (just killed) relay feed ports by
    re-applying each feed input's own settings — a forced source rebuild that
    closes the socket without changing anything (see module docstring).

    Returns (released_input_names, note). Best effort by design: any failure —
    OBS not running, wrong password, protocol surprise — yields ([], reason)
    and NEVER an exception; stopping the relay must always go through.
    """
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return [], note
    try:
        inputs = session.request("GetInputList",
                                 {"inputKind": "ffmpeg_source"}).get("inputs", [])
        settings = {}                                # filled by the name filter

        def get_settings(name):
            settings[name] = session.request(
                "GetInputSettings", {"inputName": name}).get("inputSettings", {})
            return settings[name]

        names = feed_input_names(inputs, get_settings, ports)
        for name in names:
            session.request("SetInputSettings",      # unchanged -> rebuild only
                            {"inputName": name, "inputSettings": settings[name],
                             "overlay": True})
        return names, ""
    except Exception as exc:                         # noqa: BLE001 — see docstring
        return [], str(exc) or exc.__class__.__name__
    finally:
        session.close()
```

Note the deliberate note-format change: the `"could not release OBS feed
inputs: "` prefix is dropped — `iro.py` already prints notes as
`obs: feed release skipped — {note}`, so the prefix was redundant. The
existing tests only assert the note is non-empty.

- [ ] **Step 4: Run the existing tests to verify the refactor is invisible**

Run: `python3 tests/test_obsws.py`
Expected: `ALL PASS` (including `t_release_feed_inputs_end_to_end_against_fake_server` and the wrong-password test)

- [ ] **Step 5: Lint and commit**

```bash
python3 tools/lint.py
git add src/scripts/obs_ws.py
git commit -m "refactor(obs): extract session open/close from release_feed_inputs"
```

---

### Task 4: `refresh_browser_inputs()` — the refreshnocache entry point

**Files:**
- Modify: `src/scripts/obs_ws.py` (after `release_feed_inputs`)
- Test: `tests/test_obsws.py` (extend `_fake_obs_server`, new e2e tests)

- [ ] **Step 1: Extend the fake obs-websocket server**

In `tests/test_obsws.py`, inside `_fake_obs_server()`, replace the `inputs` and
`settings` fixtures with:

```python
    inputs = [{"inputName": "Feed A", "inputKind": "ffmpeg_source"},
              {"inputName": "Feed B", "inputKind": "ffmpeg_source"},
              {"inputName": "Intro Video", "inputKind": "ffmpeg_source"},
              {"inputName": "HUD Lower Third", "inputKind": "browser_source"},
              {"inputName": "HUD Race Timer", "inputKind": "browser_source"},
              {"inputName": "Docs Panel", "inputKind": "browser_source"}]
    settings = {"Feed A": {"input": "http://127.0.0.1:53001"},
                "Feed B": {"input": "http://127.0.0.1:53002"},
                "Intro Video": {"local_file": "/x/i.mp4", "is_local_file": True},
                "HUD Lower Third": {"url": "http://127.0.0.1:8088/hud"},
                "HUD Race Timer": {"url": "http://127.0.0.1:8088/timer"},
                "Docs Panel": {"url": "https://example.com/docs"}}
```

and replace the `if rtype == "GetInputList":` branch with one that honors the
`inputKind` filter, plus a new `PressInputPropertiesButton` branch:

```python
        if rtype == "GetInputList":
            kind = rdata.get("inputKind")
            resp = {"inputs": [i for i in inputs
                               if not kind or i["inputKind"] == kind]}
        elif rtype == "PressInputPropertiesButton":
            # The refresh presses OBS's own 'Refresh cache of current page'
            # button — never anything else.
            assert rdata["propertyName"] == "refreshnocache"
            state.setdefault("refreshed", []).append(rdata["inputName"])
            resp = {}
        elif rtype == "GetInputSettings":
```

(the existing `GetInputSettings` / `SetInputSettings` / fallback branches stay
unchanged).

- [ ] **Step 2: Write the failing e2e tests**

Add after `t_release_feed_inputs_wrong_password_is_note_not_crash()`:

```python
# --------------------------------------------------------------------------
# refresh_browser_inputs — the auto-refresh used by `iro relay|event start`
# --------------------------------------------------------------------------
def t_refresh_browser_inputs_end_to_end_against_fake_server():
    server_sock = socket.socket()
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]
    state = {"released": [], "refreshed": []}
    thread = threading.Thread(target=_fake_obs_server,
                              args=(server_sock, "supersecret", state), daemon=True)
    thread.start()
    names, note = m.refresh_browser_inputs(port=port, password="supersecret",
                                           timeout=5)
    assert note == "", note
    assert names == ["HUD Lower Third", "HUD Race Timer"]
    assert state["refreshed"] == ["HUD Lower Third", "HUD Race Timer"]
    assert state["released"] == []                 # refresh must not touch feeds
    server_sock.close()


def t_refresh_browser_inputs_unreachable_is_quiet():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]
    sock.close()
    names, note = m.refresh_browser_inputs(port=free_port, password="x",
                                           timeout=0.5)
    assert names == []
    assert note                                    # human-readable reason
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 tests/test_obsws.py`
Expected: `AttributeError: module 'obs_ws' has no attribute 'refresh_browser_inputs'`
(and all pre-existing tests still pass before that point).

- [ ] **Step 4: Implement `refresh_browser_inputs()`**

Add to `src/scripts/obs_ws.py` after `release_feed_inputs()`:

```python
def refresh_browser_inputs(needle="127.0.0.1:8088", host="127.0.0.1", port=None,
                           password=None, timeout=2.0):
    """Press 'Refresh cache of current page' (refreshnocache) on every browser
    source whose URL points at the relay — the programmatic right-click →
    Refresh, used after the shipped HUD/timer pages changed (OBS's CEF caches
    the page JS until then).

    Returns (refreshed_input_names, note). Best effort like
    release_feed_inputs(): any failure yields ([], reason), never an exception.
    """
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return [], note
    try:
        inputs = session.request("GetInputList",
                                 {"inputKind": "browser_source"}).get("inputs", [])

        def get_settings(name):
            return session.request("GetInputSettings",
                                   {"inputName": name}).get("inputSettings", {})

        names = browser_input_names(inputs, get_settings, needle)
        for name in names:
            session.request("PressInputPropertiesButton",
                            {"inputName": name, "propertyName": "refreshnocache"})
        return names, ""
    except Exception as exc:                         # noqa: BLE001 — see docstring
        return [], str(exc) or exc.__class__.__name__
    finally:
        session.close()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 tests/test_obsws.py`
Expected: `ALL PASS`

- [ ] **Step 6: Lint and commit**

```bash
python3 tools/lint.py
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): refresh_browser_inputs presses refreshnocache via obs-websocket"
```

---

### Task 5: Staleness-gate helpers in `iro.py` (pure, unit-tested)

**Files:**
- Modify: `src/iro.py` (new helpers near `RELAY_PORT`, ~line 247; add `hashlib` to the import line)
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_iro.py` (before the `_raises` helper at the bottom):

```python
def t_refresh_decision():
    assert m.refresh_decision(None, None) == "skip-no-pages"
    assert m.refresh_decision(None, "abc") == "skip-no-pages"
    assert m.refresh_decision("abc", "abc") == "skip-unchanged"
    assert m.refresh_decision("abc", "old") == "refresh"
    assert m.refresh_decision("abc", None) == "refresh"          # first run
    assert m.refresh_decision("abc", "abc", force=True) == "refresh"


def t_served_pages_hash_concatenates_in_order():
    import hashlib
    pages = {"/hud": b"HUD", "/timer": b"TIMER"}
    expected = hashlib.sha256(b"HUDTIMER").hexdigest()
    assert m.served_pages_hash(fetch=lambda p: pages[p]) == expected


def t_served_pages_hash_none_when_any_fetch_fails():
    def fetch(path):
        if path == "/timer":
            raise OSError("connection refused")
        return b"HUD"
    assert m.served_pages_hash(fetch=fetch) is None


def t_pages_hash_roundtrip_and_missing():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "state", "obs-pages.hash")
        assert m.read_pages_hash(path) is None                   # missing file
        m.write_pages_hash(path, "abc123")                       # creates the dir
        assert m.read_pages_hash(path) == "abc123"


def t_wait_for_polls_until_deadline():
    ticks = iter([0, 1, 2, 3, 4, 5])
    slept = []
    ok = m.wait_for(lambda: False, 2, clock=lambda: next(ticks),
                    sleep=slept.append)
    assert ok is False
    assert slept                                                 # polled, not busy-spun
    assert m.wait_for(lambda: True, 0, clock=lambda: 0,
                      sleep=lambda s: None) is True               # checks at least once
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_iro.py`
Expected: `AttributeError: module 'iro' has no attribute 'refresh_decision'`

- [ ] **Step 3: Implement the helpers**

In `src/iro.py`, change the import line (line 20) to include `hashlib`:

```python
import glob, hashlib, json, os, shutil, sys, time, webbrowser
```

Add below `RELAY_PORT = 8088` (~line 247):

```python
# The relay-served pages OBS renders as browser sources (panel is tablet-only).
OBS_PAGE_PATHS = ("/hud", "/timer")


def _fetch_relay_page(path):
    import urllib.request
    return urllib.request.urlopen(
        f"http://127.0.0.1:{RELAY_PORT}{path}", timeout=3).read()


def served_pages_hash(fetch=None, paths=OBS_PAGE_PATHS):
    """SHA-256 over the page bytes the relay actually serves to OBS. Hashing
    what OBS would load (not the files on disk) means a still-running OLD
    relay can never advance the staleness gate past pages OBS has not seen.
    None when any page cannot be fetched (relay down, --no-hud/--no-timer)."""
    fetch = fetch or _fetch_relay_page
    h = hashlib.sha256()
    for path in paths:
        try:
            h.update(fetch(path))
        except Exception:
            return None
    return h.hexdigest()


def refresh_decision(served, stored, force=False):
    """Should the OBS page-refresh hook act? Pure for tests: 'skip-no-pages'
    (relay down / pages disabled), 'skip-unchanged' (no on-air flicker), or
    'refresh'."""
    if served is None:
        return "skip-no-pages"
    if not force and served == stored:
        return "skip-unchanged"
    return "refresh"


def read_pages_hash(path):
    """Hash of the pages OBS last confirmed loading, or None (never refreshed)."""
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def write_pages_hash(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(value + "\n")


def wait_for(probe, wait, clock=time.monotonic, sleep=time.sleep):
    """Poll probe() until truthy or `wait` seconds elapsed; checks at least
    once, so wait=0 means 'probe now, no retries'."""
    deadline = clock() + wait
    while True:
        if probe():
            return True
        if clock() >= deadline:
            return False
        sleep(0.5)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_iro.py`
Expected: `ALL PASS`

- [ ] **Step 5: Lint and commit**

```bash
python3 tools/lint.py
git add src/iro.py tests/test_iro.py
git commit -m "feat(iro): staleness-gate helpers for the OBS page refresh"
```

---

### Task 6: `_refresh_obs_pages()` glue + the `relay start` hook

Glue mirrors `_release_obs_feeds()` (which is also untested glue over tested
parts): every branch prints one notice and never raises.

**Files:**
- Modify: `src/iro.py` (new glue next to `_release_obs_feeds`, hook in `relay_start`)

- [ ] **Step 1: Implement the glue**

Add to `src/iro.py` directly below `_release_obs_feeds()` (~line 377):

```python
def _obs_pages_hash_path():
    return os.path.join(_runtime_dir(), "obs-pages.hash")


def _refresh_obs_pages(force=False, wait=0):
    """Refresh the relay-served OBS browser sources (HUD + race timer) when
    the pages changed since the last successful refresh — replaces the manual
    right-click → 'Refresh cache of current page' (OBS's CEF caches the page
    JS until then; a producer updating the package must never go on air with
    a stale page). Best effort like _release_obs_feeds: one notice, never an
    exception. wait: seconds to allow a just-spawned relay to open its control
    port — never refresh against a closed port (the source would load a CEF
    error page that does not self-recover)."""
    if not wait_for(_relay_http_ok, wait):
        print(f"obs: page refresh skipped — relay not responding on port {RELAY_PORT}.")
        return
    served = served_pages_hash()
    decision = refresh_decision(served, read_pages_hash(_obs_pages_hash_path()), force)
    if decision == "skip-no-pages":
        print("obs: page refresh skipped — could not read /hud + /timer from the relay.")
        return
    if decision == "skip-unchanged":
        return                              # unchanged pages -> no on-air flicker
    try:
        import obs_ws
        names, note = obs_ws.refresh_browser_inputs(needle=f"127.0.0.1:{RELAY_PORT}")
    except Exception as exc:                # a start must never fail on this
        print(f"obs: page refresh skipped ({exc}).")
        return
    if note:
        print(f"obs: page refresh skipped — {note}")
        return                              # hash kept -> retried on the next start
    write_pages_hash(_obs_pages_hash_path(), served)   # only confirmed refreshes advance the gate
    print(f"obs: refreshed browser sources {', '.join(names)}." if names
          else "obs: no relay browser sources in OBS — nothing to refresh.")
```

(The empty-`names` success still advances the gate: OBS answered and has no
relay-pointing sources — e.g. collection not imported yet — so there is
nothing that can be stale.)

- [ ] **Step 2: Hook it into `relay_start()`**

In `relay_start()` (~line 357), after the started message and before `return None`:

```python
    print(f"relay started (pid {newpid}). Watch it: iro relay logs -f")
    _refresh_obs_pages(wait=10)   # pages may have changed since the last run
    return None
```

The already-running early-return path gets **no** hook: a running relay serves
the same pages it served before, so OBS cannot have gone stale.

- [ ] **Step 3: Run the full suite**

Run: `python3 tools/run-tests.py`
Expected: every file reports `ALL PASS` (no existing behavior asserted on `relay_start`'s stdout).

- [ ] **Step 4: Smoke-test by hand (relay only, no OBS)**

Run: `python3 src/iro.py relay restart`
Expected within ~12 s: `relay started (pid …)` followed by either
`obs: page refresh skipped — OBS WebSocket not reachable …` (OBS closed) or
`obs: refreshed browser sources …` / `obs: page refresh skipped — relay not
responding …` — but never a traceback. Then: `python3 src/iro.py relay stop`.

- [ ] **Step 5: Lint and commit**

```bash
python3 tools/lint.py
git add src/iro.py
git commit -m "feat(iro): auto-refresh OBS pages on relay start (hash-gated)"
```

---

### Task 7: `iro obs refresh` — manual command + routing

**Files:**
- Modify: `src/iro.py` (USAGE docstring, `route()`, `DISPATCH`, new `obs_refresh_cmd`)
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing routing tests**

Add to `tests/test_iro.py`:

```python
def t_obs_refresh_route():
    assert m.route(["obs", "refresh"]) == \
        {"kind": "service", "command": "obs", "verb": "refresh", "rest": []}


def t_obs_bad_verb_raises():
    _raises(lambda: m.route(["obs"]))
    _raises(lambda: m.route(["obs", "bogus"]))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_iro.py`
Expected: the run aborts in `t_obs_refresh_route` with
`ValueError: unknown command: obs`.

- [ ] **Step 3: Implement routing + command**

In `src/iro.py`:

(a) USAGE docstring — add after the `iro tailscale …` line:

```
  iro obs refresh                       # force-reload the relay-served OBS browser sources (HUD/timer)
```

(b) Next to `TAILSCALE_VERBS` (~line 260):

```python
OBS_VERBS = ("refresh",)
```

(c) In `route()`, after the `tailscale` branch:

```python
    if cmd == "obs":
        verb = rest[0] if rest else None
        if verb not in OBS_VERBS:
            raise ValueError(f"usage: iro obs {{{'|'.join(OBS_VERBS)}}}")
        return {"kind": "service", "command": "obs", "verb": verb, "rest": rest[1:]}
```

(d) The command, next to `_refresh_obs_pages()`:

```python
def obs_refresh_cmd(_rest):
    """Force-refresh every relay-served browser source — the scriptable
    right-click → Refresh (no staleness gate)."""
    if not _relay_http_ok():
        sys.exit(f"obs: relay not responding on port {RELAY_PORT} — start it first "
                 "(refreshing against a dead relay loads an error page in OBS).")
    _refresh_obs_pages(force=True)
```

(e) `DISPATCH` — add:

```python
    ("obs", "refresh"): obs_refresh_cmd,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_iro.py`
Expected: `ALL PASS`

- [ ] **Step 5: Lint and commit**

```bash
python3 tools/lint.py
git add src/iro.py tests/test_iro.py
git commit -m "feat(iro): obs refresh command — scriptable browser-source refresh"
```

---

### Task 8: The `event start` hook (post-OBS retry)

**Files:**
- Modify: `src/iro.py` (`event_start`, ~line 853)

- [ ] **Step 1: Add the hook**

In `event_start()`, between the `wait_until_up` loop and the readiness report:

```python
    for name, up in sorted(ev.wait_until_up(probes).items()):
        print(f"  {name}: {'up' if up else 'still not up — see the report below'}")
    # OBS may not have been running when relay_start's refresh hook fired
    # (event start launches OBS AFTER the relay) — retry now that both sides
    # are up. Hash-gated: a no-op when the first hook already delivered.
    _refresh_obs_pages()
    print("\nEvent readiness:")
```

- [ ] **Step 2: Run the full suite**

Run: `python3 tools/run-tests.py`
Expected: every file reports `ALL PASS`.

- [ ] **Step 3: Lint and commit**

```bash
python3 tools/lint.py
git add src/iro.py
git commit -m "feat(iro): retry the OBS page refresh after event start brings OBS up"
```

---

### Task 9: Docs — CLAUDE.md caveat, command list, wiki

**Files:**
- Modify: `CLAUDE.md` (the browser-source caveat in "Two token round-trips"; the Commands block)
- Modify: `src/docs/wiki/Run-an-event.md:28-31` (the "Before going LIVE" blockquote)

- [ ] **Step 1: Update the CLAUDE.md caveat**

Replace (in the OBS bullet of "Two token round-trips"):

```
**OBS browser sources cache JS aggressively:** after changing
`hud.html`/`timer.html`, the source needs a manual refresh in OBS (right-click →
Refresh) — auto-reload is not reliable.
```

with:

```
**OBS browser sources cache JS aggressively:** after `hud.html`/`timer.html`
change, OBS keeps the old page until refreshed. `iro relay start` and
`iro event start` do that automatically — a hash gate over the *served* page
bytes (`runtime/obs-pages.hash`) triggers obs-websocket `refreshnocache` on
every browser source pointing at the relay; `iro obs refresh` forces it. The
manual right-click → Refresh remains the fallback when obs-websocket is
unreachable.
```

(keep the following sentence about server-side state unchanged).

- [ ] **Step 2: Add the command to the CLAUDE.md Commands block**

After the `iro tailscale` line:

```bash
python3 src/iro.py obs refresh       # force-reload the relay-served OBS browser sources (HUD/timer)
```

- [ ] **Step 3: Update the wiki blockquote**

In `src/docs/wiki/Run-an-event.md`, replace:

```
> **Before going LIVE:** refresh the HUD overlay browser source in OBS once
> (right-click the source → Refresh) — its auto-refresh is not fully
> reliable.
```

with:

```
> **Page updates:** `iro event start` re-loads the HUD/timer browser sources
> automatically when an update changed them. If a page ever looks stale,
> `iro obs refresh` (or right-click the source → Refresh) forces it.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md src/docs/wiki/Run-an-event.md
git commit -m "docs: OBS pages now auto-refresh on relay/event start"
```

(Wiki publishing via `python3 tools/sync-wiki.py` is a maintainer step — leave
it to the user / the release flow.)

---

### Task 10: Full verification

- [ ] **Step 1: Whole suite**

Run: `python3 tools/run-tests.py`
Expected: every test file reports `ALL PASS`, exit code 0.

- [ ] **Step 2: Lint**

Run: `python3 tools/lint.py`
Expected: no findings.

- [ ] **Step 3: Build self-verify**

Run: `python3 tools/build.py`
Expected: ends with the verify step passing (tokenization, blanked password, no
secrets, preflight present, no shell scripts).

- [ ] **Step 4: End-to-end smoke (manual, OBS running)**

With OBS open and the collection imported:

```bash
python3 src/iro.py relay start        # expect: obs: refreshed browser sources … (first run, no stored hash)
python3 src/iro.py relay restart      # expect: NO refresh line (hash unchanged — gate works)
python3 src/iro.py obs refresh        # expect: obs: refreshed browser sources … (forced)
python3 src/iro.py relay stop
```

- [ ] **Step 5: Report**

No commit here unless fixes were needed; summarize results to the user.
