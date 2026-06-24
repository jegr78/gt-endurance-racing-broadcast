# Relay start-ordering fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fail fast and clearly when the relay's mandatory loopback control port (8088) is already taken — before any network work and before the misleading `relay starting` / `Schedule loaded` logs — and show the actual profile/league name in the start line.

**Architecture:** Add a pure-ish probe helper `control_port_available(host, port)` to `src/relay/racecast-feeds.py`, call it early in `main()` (right after the `relay starting` log, before the first network refresh), and source the start line's `profile=` from the injected `args.league_name`. The real bind later in `main()` is unchanged and remains the authoritative guard.

**Tech Stack:** Python 3 stdlib only (`socket`). Tests are stdlib runnable scripts (no pytest).

## Global Constraints

- **Edit only under `src/` and `tests/`** (plus the already-committed `docs/` spec). (CLAUDE.md)
- **English only** in all code, comments, log strings. (CLAUDE.md)
- **Stdlib only — no new dependency.** `socket` is already imported by the relay.
- **Do not touch the real bind** at `main()` ~line 5736 or the issue-#84 loopback-mandatory abort — they stay as the final guard.
- **CI-safe tests:** no hardcoded ports / IPs — use `127.0.0.1` + an OS-assigned ephemeral port (`bind(("127.0.0.1", 0))`).
- **Keep the abort message verbatim** identical to the existing late-guard `sys.exit` text, so the operator sees one consistent message.
- **Run after Python changes:** `python3 tools/lint.py`. **Before shipping:** `python3 tools/run-tests.py` and `python3 tools/build.py`.

---

### Task 1: `control_port_available` + early probe + `profile=` fix

**Files:**
- Modify: `src/relay/racecast-feeds.py` — add `control_port_available()` near the other bind helpers (just after `resolve_bind_addresses`, ~line 385); call it early in `main()` (after the `relay starting` log, ~line 5467); fix the `profile=` field in that same log line (~line 5465-5467).
- Test: `tests/test_bind.py`

**Interfaces:**
- Consumes: stdlib `socket` (already imported); `args.http_port`, `args.league_name` (existing argparse fields).
- Produces: `control_port_available(host, port) -> bool` — True if the port can be bound now, False on a bind error (port in use). Always closes its probe socket.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_bind.py` (after the existing `resolve_bind_addresses` tests):

```python
def t_control_port_available_true_when_free_false_when_taken():
    import socket
    # A port we bind and hold -> reported unavailable.
    held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    port = held.getsockname()[1]
    try:
        assert m.control_port_available("127.0.0.1", port) is False
    finally:
        held.close()
    # Once freed, the same port is available again.
    assert m.control_port_available("127.0.0.1", port) is True


def t_main_probes_control_port_before_refresh_and_logs_league():
    import inspect
    src = inspect.getsource(m.main)
    assert "control_port_available(" in src                       # the early probe exists
    assert src.index("control_port_available(") < src.index("pov_source")  # before the first refresh
    assert '(args.league_name or "?")' in src                    # start line uses the injected name
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_bind.py`
Expected: FAIL — `AttributeError: module 'irofeeds' has no attribute 'control_port_available'`.

- [ ] **Step 3: Add the helper**

In `src/relay/racecast-feeds.py`, immediately after the `resolve_bind_addresses` function (~line 385), add:

```python
def control_port_available(host, port):
    """True if the mandatory loopback control port can be bound right now (no other
    relay holds it). A throwaway probe using the same SO_REUSEADDR semantics as the
    real control server, so its verdict matches what the real bind would see. Returns
    False only on a bind error (port in use / unbindable); the socket is always closed."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()
```

- [ ] **Step 4: Fix the `profile=` field**

In `src/relay/racecast-feeds.py`, change the `relay starting` log (currently lines ~5465-5467) from:

```python
    LOG.info("relay starting — profile=%s bind=%s ports=%s mode=%s schedule=%s",
             os.environ.get("RACECAST_PROFILE", "?"), args.bind, args.ports,
             ("qualifying" if args.qualifying else "race"), csv_url)
```

to:

```python
    LOG.info("relay starting — profile=%s bind=%s ports=%s mode=%s schedule=%s",
             (args.league_name or "?"), args.bind, args.ports,
             ("qualifying" if args.qualifying else "race"), csv_url)
```

- [ ] **Step 5: Add the early probe**

In `src/relay/racecast-feeds.py`, immediately AFTER that `relay starting` log line and BEFORE the POV source block (`pov_source = None`, ~line 5471), insert:

```python
    # Fail fast: the loopback control port is mandatory (OBS always reaches the relay
    # on 127.0.0.1). If another relay already holds it, abort BEFORE the network
    # refreshes below — otherwise the log reads like a successful start
    # ("Schedule loaded …") right before the bind fails. The real bind later is the
    # authoritative guard; this just turns a slow, misleading failure into a fast,
    # clear one.
    if not control_port_available("127.0.0.1", args.http_port):
        LOG.error("control port 127.0.0.1:%s already in use — another relay is "
                  "probably running; aborting before any startup work.", args.http_port)
        sys.exit(f"Could not bind the control server on 127.0.0.1 port {args.http_port} "
                 f"— another relay is probably already running. Stop it first "
                 f"('racecast relay stop'), then check 'racecast status' / 'racecast preflight' "
                 f"to see what holds the port.")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 tests/test_bind.py`
Expected: `ALL PASS` (existing bind tests plus the two new ones).

- [ ] **Step 7: Lint**

Run: `python3 tools/lint.py`
Expected: no findings for `src/relay/racecast-feeds.py`.

- [ ] **Step 8: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_bind.py
git commit -m "fix(relay): probe the control port before startup work; show league in start log"
```

---

### Task 2: Full-suite + build verification gate

**Files:** none (verification only).

- [ ] **Step 1: Run the whole test suite (exactly what CI runs)**

Run: `python3 tools/run-tests.py`
Expected: all test scripts pass — in particular `test_bind.py` and `test_pov.py` (relay units).

- [ ] **Step 2: Lint the whole tree**

Run: `python3 tools/lint.py`
Expected: no findings.

- [ ] **Step 3: Build verify**

Run: `python3 tools/build.py`
Expected: build completes and the verify step passes. (Missing media/graphics `[warn]` lines are expected — gitignored runtime assets.)

- [ ] **Step 4: Manual smoke (optional)**

Start a relay (or any process) holding 127.0.0.1:8088, then `python3 src/racecast.py relay run` and confirm the console log shows `relay starting — profile=<name> …` immediately followed by the `control port … already in use` abort — with **no** `Schedule loaded` line in between.

---

## Self-Review

**Spec coverage:**
- `control_port_available` probe helper (SO_REUSEADDR, always closes, False on bind error) → Task 1 Step 3. ✓
- Early probe right after `relay starting`, before the first refresh, with the verbatim abort message → Task 1 Step 5. ✓
- `profile=` sourced from `args.league_name` → Task 1 Step 4. ✓
- Real bind untouched → not modified (only an early guard added). ✓
- CI-safe unit test (ephemeral port) → Task 1 Step 1 (`t_control_port_available_…`). ✓
- Ordering + league-name regression guard → Task 1 Step 1 (`t_main_probes_control_port_before_refresh_and_logs_league`, inspect-based, mirrors the repo's existing `t_relay_start_spawns_to_boot_log_not_console` pattern). ✓
- Stdlib only, English only → honored. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command has an expected result.

**Type consistency:** `control_port_available(host, port) -> bool` defined in Step 3 and called in Step 5 and the Step 1 tests with the same `(host, port)` signature; the abort `sys.exit` string matches the existing late-guard message verbatim; the inspect test's anchors (`control_port_available(`, `pov_source`, `(args.league_name or "?")`) match the exact strings introduced in Steps 3-5.
