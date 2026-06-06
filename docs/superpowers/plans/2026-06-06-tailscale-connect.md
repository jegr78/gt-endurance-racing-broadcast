# Tailscale Connect/Disconnect Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `iro tailscale up|down|status` controls Tailscale's connection, and `iro event start` connects a stopped Tailscale automatically instead of only launching the app.

**Architecture:** All Tailscale logic moves from `src/scripts/companion_common.py` into a new `src/scripts/tailscale.py` (binary discovery, BackendState-aware parsing, argument-less `up`/`down` control). `src/iro.py` gains the `tailscale` command and a shared connect flow used by `event start`. The relay (`src/relay/iro-feeds.py`) keeps its own documented copy of the detection — it stays a standalone single file.

**Tech Stack:** Pure Python stdlib (project convention: no pytest, each test file is a runnable script; ruff via `tools/lint.py`).

**Spec:** `docs/superpowers/specs/2026-06-06-tailscale-connect-design.md`

**Branch:** continue on `fix/tailscale-connected-check` (builds on the BackendState detection fix).

**Conventions for every task:** run `python3 tools/lint.py` after changing any Python file; all code/comments in English.

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `src/scripts/tailscale.py` | create | All Tailscale logic: bins, CGNAT check, `parse_tailscale_backend`, `detect_tailscale_ip`, `tailscale_backend`, `tailscale_up/down`, `plan_tailscale_up` |
| `tests/test_tailscale.py` | create | Pure-function tests for the new module |
| `src/scripts/companion_common.py` | modify | Loses all Tailscale code (keeps Companion bind/control only) |
| `tests/test_companion.py` | modify | Tailscale smoke tests move out |
| `src/iro.py` | modify | `tailscale` routing + CLI verbs, `_tailscale_connect()` flow, `event_start` step 1, `_tailscale_ip()` + `companion_start` import switch, USAGE |
| `tests/test_iro.py` | modify | Routing tests for the new command |
| `tools/build-binary.py` | modify | `--hidden-import tailscale` |
| `tests/test_bind.py`, `src/relay/iro-feeds.py` | untouched | Relay keeps its copy |
| `CLAUDE.md`, `README.md`, `src/docs/wiki/Run-an-event.md`, `src/docs/wiki/If-something-goes-wrong.md` | modify | Docs |

---

### Task 1: New module `src/scripts/tailscale.py` (move + new pure logic)

**Files:**
- Create: `tests/test_tailscale.py`
- Create: `src/scripts/tailscale.py`
- Modify: `src/scripts/companion_common.py` (delete moved code, docstring, imports)
- Modify: `tests/test_companion.py` (drop the moved smoke test)
- Modify: `src/iro.py:279-284` (`_tailscale_ip`) and `src/iro.py:431` (`companion_start`)

- [ ] **Step 1: Write the failing tests** — create `tests/test_tailscale.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the Tailscale detection/control helpers.
Run: python3 tests/test_tailscale.py"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import tailscale as ts


def _status_json(state, ips):
    return json.dumps({"BackendState": state, "Self": {"TailscaleIPs": ips}})


# --- _in_cgnat: Tailscale uses the 100.64.0.0/10 CGNAT range -----------------
def t_cgnat_range():
    assert ts._in_cgnat("100.64.10.20") is True
    assert ts._in_cgnat("100.63.255.255") is False
    assert ts._in_cgnat("192.168.1.5") is False
    assert ts._in_cgnat("not-an-ip") is False


# --- parse_tailscale_backend: (BackendState, ip) from `status --json` ---------
def t_backend_running_returns_state_and_ip():
    out = _status_json("Running", ["fd7a:115c:a1e0::1", "100.64.10.20"])
    assert ts.parse_tailscale_backend(out) == ("Running", "100.64.10.20")


def t_backend_stopped_keeps_state_but_no_ip():
    # A disconnected node keeps its assigned tailnet IP — never report it.
    out = _status_json("Stopped", ["100.64.10.20"])
    assert ts.parse_tailscale_backend(out) == ("Stopped", None)


def t_backend_needslogin():
    assert ts.parse_tailscale_backend(_status_json("NeedsLogin", [])) == \
        ("NeedsLogin", None)


def t_backend_running_without_cgnat_ip():
    assert ts.parse_tailscale_backend(_status_json("Running", [])) == ("Running", None)


def t_backend_garbage_is_none_none():
    assert ts.parse_tailscale_backend("") == (None, None)
    assert ts.parse_tailscale_backend("not json") == (None, None)
    assert ts.parse_tailscale_backend("[1, 2]") == (None, None)
    assert ts.parse_tailscale_backend('{"Self": {}}') == (None, None)


# --- parse_tailscale_status: Running IP only (detection compat wrapper) -------
def t_status_wrapper_running_vs_stopped():
    assert ts.parse_tailscale_status(_status_json("Running", ["100.64.10.20"])) == \
        "100.64.10.20"
    assert ts.parse_tailscale_status(_status_json("Stopped", ["100.64.10.20"])) is None


# --- plan_tailscale_up: decision for an `up` request given a BackendState -----
def t_plan_running_is_connected():
    assert ts.plan_tailscale_up("Running") == "connected"


def t_plan_stopped_and_starting_run_up():
    assert ts.plan_tailscale_up("Stopped") == "run-up"
    assert ts.plan_tailscale_up("Starting") == "run-up"
    assert ts.plan_tailscale_up("NoState") == "run-up"


def t_plan_login_states_never_run_up():
    # `up` in these states would trigger the interactive browser login.
    assert ts.plan_tailscale_up("NeedsLogin") == "needs-login"
    assert ts.plan_tailscale_up("NeedsMachineAuth") == "needs-login"


def t_plan_no_backend_launches_app():
    assert ts.plan_tailscale_up(None) == "launch-app"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 tests/test_tailscale.py`
Expected: `ModuleNotFoundError: No module named 'tailscale'`

- [ ] **Step 3: Create `src/scripts/tailscale.py`**

```python
"""Tailscale detection and connect/disconnect control for the iro CLI.

One home for everything Tailscale: CLI-binary discovery, BackendState-aware
detection, and the argument-less `up`/`down` control behind `iro tailscale ...`
and `iro event start`. A stopped/disconnected node keeps its assigned tailnet
IP, so `tailscale ip -4` alone reports false positives — only BackendState
"Running" counts as connected.

detect_tailscale_ip() is duplicated in src/relay/iro-feeds.py (the relay is a
standalone single file by design) — the project's bounded-duplication
convention (cf. load_dotenv). Keep the two in sync.

Spec: docs/superpowers/specs/2026-06-06-tailscale-connect-design.md.
Tests: tests/test_tailscale.py."""
import ipaddress, json, subprocess

_CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")  # Tailscale's IPv4 range
# Candidate Tailscale CLI locations (PATH first, then the platform installers).
_TAILSCALE_BINS = [
    "tailscale",
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",  # macOS GUI app
    "/usr/bin/tailscale", "/usr/local/bin/tailscale", "/opt/homebrew/bin/tailscale",
    r"C:\Program Files\Tailscale\tailscale.exe",
]


def _in_cgnat(ip):
    """True iff ip is a valid IPv4 address inside Tailscale's 100.64.0.0/10 range."""
    try:
        return ipaddress.ip_address(ip) in _CGNAT_NET
    except ValueError:
        return False


def parse_tailscale_backend(output):
    """(BackendState, ip) parsed from `tailscale status --json` output.

    The IP is Self's first CGNAT IPv4 and is only reported while Running.
    (None, None) on unparseable output or a missing BackendState."""
    try:
        data = json.loads(output)
    except ValueError:
        return None, None
    if not isinstance(data, dict):
        return None, None
    state = data.get("BackendState")
    if not isinstance(state, str) or not state:
        return None, None
    if state != "Running":
        return state, None
    for ip in (data.get("Self") or {}).get("TailscaleIPs") or []:
        if _in_cgnat(str(ip)):
            return state, str(ip)
    return state, None


def parse_tailscale_status(output):
    """Self's first CGNAT IPv4 from `tailscale status --json`, or None unless
    the backend is actually Running."""
    return parse_tailscale_backend(output)[1]


def tailscale_backend(timeout=3):
    """(binary, BackendState, ip) via the first CLI whose backend answers
    `status --json`; (None, None, None) when none does (CLI missing, or the
    backend is not running — on macOS it only lives while the app runs)."""
    for binary in _TAILSCALE_BINS:
        try:
            out = subprocess.run([binary, "status", "--json"], capture_output=True,
                                 text=True, errors="replace", timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            continue
        state, ip = parse_tailscale_backend(out.stdout)
        if state:
            return binary, state, ip
    return None, None, None


def detect_tailscale_ip():
    """This machine's connected Tailscale IPv4 via the CLI, or None if the
    Tailscale backend is unavailable, stopped, or logged out."""
    return tailscale_backend()[2]


def plan_tailscale_up(state):
    """Decision for an `up` request given a BackendState:
    connected   : Running — nothing to do.
    needs-login : `up` would trigger the interactive browser login; hint only.
    launch-app  : no backend answered — start the Tailscale app first.
    run-up      : any other state (Stopped, Starting, ...) — run `up`."""
    if state == "Running":
        return "connected"
    if state in ("NeedsLogin", "NeedsMachineAuth"):
        return "needs-login"
    if state is None:
        return "launch-app"
    return "run-up"


def _run_verb(binary, verb, timeout):
    """Run an argument-less `tailscale up|down`; returns (ok, detail). The
    timeout is a backstop in case `up` unexpectedly enters the interactive
    login flow — callers never invoke it in the NeedsLogin state."""
    try:
        out = subprocess.run([binary, verb], capture_output=True, text=True,
                             errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if out.returncode:
        detail = (out.stderr or out.stdout or "").strip()
        return False, detail or f"exit code {out.returncode}"
    return True, ""


def tailscale_up(binary, timeout=15):
    """Argument-less `tailscale up`: brings the network online WITHOUT changing
    any settings (per the CLI's own help — the opposite of `tailscale down`)."""
    return _run_verb(binary, "up", timeout)


def tailscale_down(binary, timeout=15):
    """Argument-less `tailscale down`: disconnect, keep login + settings."""
    return _run_verb(binary, "down", timeout)
```

- [ ] **Step 4: Run the new tests**

Run: `python3 tests/test_tailscale.py`
Expected: `ALL PASS`

- [ ] **Step 5: Remove the moved code from `companion_common.py`**

Delete from `src/scripts/companion_common.py`: `_CGNAT_NET`, `_TAILSCALE_BINS`, `_in_cgnat()`, `parse_tailscale_status()`, `detect_tailscale_ip()` (lines 21-68). Change the import line `import ipaddress, json, os, subprocess` to drop `ipaddress` (keep the others — `json`/`os`/`subprocess` are used by the Companion control helpers below; `tools/lint.py` flags any leftover unused import). Replace the docstring paragraph

```
The Tailscale-IP detection below is duplicated from src/relay/iro-feeds.py — the
project's bounded-duplication convention (cf. load_dotenv). Keep the two in sync.
```

with

```
Tailscale detection lives in scripts/tailscale.py; iro.py passes the detected
IP into desired_bind_ip() — this module holds Companion logic only.
```

- [ ] **Step 6: Drop the moved smoke test from `tests/test_companion.py`**

Delete this block (it is covered by `tests/test_tailscale.py` now):

```python
# --- Tailscale detect parsing (duplicated from relay; smoke only) -------------
def t_parse_tailscale_status_smoke():
    running = '{"BackendState": "Running", "Self": {"TailscaleIPs": ["100.64.10.20"]}}'
    stopped = '{"BackendState": "Stopped", "Self": {"TailscaleIPs": ["100.64.10.20"]}}'
    assert cc.parse_tailscale_status(running) == "100.64.10.20"
    assert cc.parse_tailscale_status(stopped) is None
```

- [ ] **Step 7: Switch the two `iro.py` call sites to the new module**

`src/iro.py:279-284` — replace:

```python
def _tailscale_ip():
    try:
        import companion_common as cc
        return cc.detect_tailscale_ip()
    except Exception:
        return None
```

with:

```python
def _tailscale_ip():
    try:
        import tailscale
        return tailscale.detect_tailscale_ip()
    except Exception:
        return None
```

`src/iro.py:431` (inside `companion_start`) — replace `ts = cc.detect_tailscale_ip()` with `ts = _tailscale_ip()` (same behaviour; the helper already wraps the import).

- [ ] **Step 8: Run the whole suite + lint**

Run: `python3 tools/run-tests.py && python3 tools/lint.py`
Expected: `ALL TEST FILES PASS` and `All checks passed!`

- [ ] **Step 9: Commit**

```bash
git add src/scripts/tailscale.py tests/test_tailscale.py src/scripts/companion_common.py tests/test_companion.py src/iro.py
git commit -m "refactor(tailscale): move Tailscale logic into scripts/tailscale.py"
```

---

### Task 2: `iro tailscale up|down|status` routing

**Files:**
- Modify: `src/iro.py` (`TAILSCALE_VERBS`, `route()`, USAGE docstring)
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing routing tests** — append to `tests/test_iro.py` (next to the other routing tests, before the `t_http_url` block):

```python
def t_tailscale_verbs():
    for verb in ("up", "down", "status"):
        assert m.route(["tailscale", verb]) == \
            {"kind": "service", "command": "tailscale", "verb": verb, "rest": []}


def t_tailscale_bad_verb_raises():
    _raises(lambda: m.route(["tailscale"]))
    _raises(lambda: m.route(["tailscale", "restart"]))
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_iro.py`
Expected: FAIL in `t_tailscale_verbs` (`ValueError: unknown command: tailscale` → assertion/raise)

- [ ] **Step 3: Add the routing**

In `src/iro.py`, after `EVENT_VERBS = ("status", "start", "stop")` add:

```python
TAILSCALE_VERBS = ("up", "down", "status")
```

In `route()`, after the `if cmd == "event":` block add:

```python
    if cmd == "tailscale":
        verb = rest[0] if rest else None
        if verb not in TAILSCALE_VERBS:
            raise ValueError(f"usage: iro tailscale {{{'|'.join(TAILSCALE_VERBS)}}}")
        return {"kind": "service", "command": "tailscale", "verb": verb, "rest": rest[1:]}
```

In the module docstring (USAGE), after the `iro event start --stint N` line add:

```
  iro tailscale up|down|status          # connect / disconnect / inspect Tailscale
```

- [ ] **Step 4: Run tests**

Run: `python3 tests/test_iro.py`
Expected: `ALL PASS` (the new routes resolve; DISPATCH wiring comes in Task 3 — `main()` would print "not implemented yet", which routing tests don't hit)

- [ ] **Step 5: Commit**

```bash
git add src/iro.py tests/test_iro.py
git commit -m "feat(iro): route the tailscale up|down|status command"
```

---

### Task 3: Connect flow + CLI verbs + `event start` integration

**Files:**
- Modify: `src/iro.py` (new functions near `event_start`, DISPATCH, `event_start` step 1)

- [ ] **Step 1: Add the shared connect flow** — in `src/iro.py`, directly above `event_start` (after `_event_launch`):

```python
def _tailscale_connect(ev=None):
    """Best-effort connect: argument-less `tailscale up` keeps all settings
    ("the opposite of tailscale down"). Launches the app first when no backend
    answers (macOS: the backend only lives while the app runs); never runs `up`
    in NeedsLogin — that would trigger the interactive browser login. Shared by
    `iro tailscale up` and `iro event start`; returns the tailnet IP or None."""
    import tailscale as ts
    binary, state, ip = ts.tailscale_backend()
    if ts.plan_tailscale_up(state) == "launch-app":
        ev = ev or _event_modules()[0]
        _event_launch(ev, "tailscale")
        for _ in range(20):  # ~10 s for the backend to come up
            time.sleep(0.5)
            binary, state, ip = ts.tailscale_backend()
            if state:
                break
    action = ts.plan_tailscale_up(state)
    if action == "connected":
        print(f"tailscale: already connected ({ip}).")
        return ip
    if action == "needs-login":
        print("tailscale: logged out — open the Tailscale app and sign in.")
        return None
    if action == "launch-app":  # the backend never came up
        print("tailscale: not running — start the Tailscale app manually.")
        return None
    ok, detail = ts.tailscale_up(binary)
    if not ok:
        hint = " (try `sudo tailscale up`)" if sys.platform.startswith("linux") else ""
        print(f"tailscale: `up` failed: {detail}{hint}")
        return None
    for _ in range(20):  # ~10 s for the tailnet to come up
        ip = ts.detect_tailscale_ip()
        if ip:
            break
        time.sleep(0.5)
    print(f"tailscale: connected ({ip})." if ip
          else "tailscale: `up` succeeded but no tailnet IP yet.")
    return ip
```

- [ ] **Step 2: Add the CLI verb functions** — directly below `_tailscale_connect`:

```python
def tailscale_up_cmd(_rest):
    raise SystemExit(0 if _tailscale_connect() else 1)


def tailscale_down_cmd(_rest):
    import tailscale as ts
    binary, state, _ip = ts.tailscale_backend()
    if state != "Running":
        print("tailscale: not connected.")
        return
    ok, detail = ts.tailscale_down(binary)
    if not ok:
        hint = " (try `sudo tailscale down`)" if sys.platform.startswith("linux") else ""
        sys.exit(f"tailscale: `down` failed: {detail}{hint}")
    print("tailscale: disconnected.")


def tailscale_status_cmd(_rest):
    import tailscale as ts
    _binary, state, ip = ts.tailscale_backend()
    if state is None:
        print("Tailscale: backend not running — `iro tailscale up` starts and connects it.")
    elif state == "Running":
        print(f"Tailscale: connected ({ip}).")
    elif state in ("NeedsLogin", "NeedsMachineAuth"):
        print(f"Tailscale: {state} — open the Tailscale app and sign in.")
    else:
        print(f"Tailscale: {state} — run `iro tailscale up` to connect.")
```

- [ ] **Step 3: Wire DISPATCH** — in the `DISPATCH` dict, after the `("event", ...)` entries add:

```python
    ("tailscale", "up"): tailscale_up_cmd, ("tailscale", "down"): tailscale_down_cmd,
    ("tailscale", "status"): tailscale_status_cmd,
```

- [ ] **Step 4: Replace `event_start` step 1** — replace the block

```python
    # 1. Tailscale
    if _tailscale_ip():
        print("tailscale: already connected.")
    else:
        _event_launch(ev, "tailscale")
        ip = None
        for _ in range(20):  # ~10 s for the tailnet to come up
            ip = _tailscale_ip()
            if ip:
                break
            time.sleep(0.5)
        if ip:
            print("tailscale: connected.")
        else:
            print("tailscale: no tailnet IP yet — sign in to Tailscale; "
                  "continuing local-only (OBS keeps working).")
```

with:

```python
    # 1. Tailscale — connect a stopped backend; launch the app when needed.
    if _tailscale_connect(ev) is None:
        print("tailscale: continuing local-only (OBS keeps working).")
```

- [ ] **Step 5: Suite + lint**

Run: `python3 tools/run-tests.py && python3 tools/lint.py`
Expected: `ALL TEST FILES PASS`, `All checks passed!`

- [ ] **Step 6: Manual verification on this machine** (Tailscale is deliberately disconnected — ideal):

```bash
python3 src/iro.py tailscale status   # expect: "Tailscale: Stopped — run `iro tailscale up` to connect."
python3 src/iro.py tailscale up       # expect: "tailscale: connected (100.x.y.z)."
python3 src/iro.py tailscale status   # expect: "Tailscale: connected (100.x.y.z)."
python3 src/iro.py tailscale down     # expect: "tailscale: disconnected."
python3 src/iro.py tailscale down     # expect: "tailscale: not connected."
```

Ask the user whether Tailscale should be left connected or disconnected afterwards.

- [ ] **Step 7: Commit**

```bash
git add src/iro.py
git commit -m "feat(iro): tailscale up/down/status + auto-connect in event start"
```

---

### Task 4: Frozen binary support

**Files:**
- Modify: `tools/build-binary.py:65-67` (hidden imports)

- [ ] **Step 1: Add the hidden import** — in the PyInstaller argv (around line 65), extend:

```python
           "--hidden-import", "services", "--hidden-import", "companion_common",
           "--hidden-import", "event", "--hidden-import", "preflight",
           "--hidden-import", "install_apps", "--hidden-import", "obs_ws",
```

to also include:

```python
           "--hidden-import", "tailscale",
```

(keep the surrounding comment's module list in sync — it names the frozen modules).

- [ ] **Step 2: Verify the frozen build** (maintainer machine, takes ~1-2 min):

Run: `python3 tools/build-binary.py`
Expected: build + smoke test pass; then `dist/bin/iro tailscale status` prints a Tailscale state line (proves the module froze in).

- [ ] **Step 3: Commit**

```bash
git add tools/build-binary.py
git commit -m "build(binary): freeze the tailscale module"
```

---

### Task 5: Docs

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `src/docs/wiki/Run-an-event.md`, `src/docs/wiki/If-something-goes-wrong.md`

- [ ] **Step 1: CLAUDE.md** —
  1. Commands block: after the `event stop` line add
     `python3 src/iro.py tailscale up|down|status  # connect/disconnect/inspect Tailscale (event start connects automatically)`.
  2. Tests block: after the `test_event.py` line add
     `python3 tests/test_tailscale.py    # Tailscale detection/control helpers`.
  3. Architecture, Companion-helpers section: replace `(duplicated detect_tailscale_ip, keep in sync with the relay)` with `(Tailscale detection/control lives in src/scripts/tailscale.py; its detect_tailscale_ip is duplicated in the standalone relay — keep those two in sync)`.

- [ ] **Step 2: README.md** — in the command list after `iro event stop` (line ~63) add:

```
iro tailscale up          # connect Tailscale (event start does this automatically)
iro tailscale down        # disconnect Tailscale after the event
```

- [ ] **Step 3: Wiki** —
  1. `src/docs/wiki/Run-an-event.md` step 8: extend the sentence "`iro event start` brings up Tailscale, Discord, …" to note that a disconnected Tailscale is connected automatically (no GUI click needed).
  2. `src/docs/wiki/If-something-goes-wrong.md`: in the Tailscale/remote-access trouble entry, add `iro tailscale status` (shows the real backend state) and `iro tailscale up` as the first fix.

- [ ] **Step 4: Build verify + commit**

Run: `python3 tools/build.py` (its verify step checks the shipped docs/package invariants)
Expected: build + verify pass, ZIP written.

```bash
git add CLAUDE.md README.md src/docs/wiki/Run-an-event.md src/docs/wiki/If-something-goes-wrong.md
git commit -m "docs: document iro tailscale up/down/status"
```

(Wiki publishing via `python3 tools/sync-wiki.py` happens after merge, not in this plan.)

---

### Final verification

- [ ] `python3 tools/run-tests.py` → `ALL TEST FILES PASS`
- [ ] `python3 tools/lint.py` → `All checks passed!`
- [ ] `python3 tools/build.py` → verify passes
- [ ] Manual: Task 3 Step 6 transcript shows connect/disconnect round-trip
