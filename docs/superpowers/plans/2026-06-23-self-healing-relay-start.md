# Self-healing `relay start` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `racecast relay start` (the Control Center "Start relay" button) always converge to exactly one current-binary relay on port 8088 under the active profile, healing orphan / split-brain / wrong-profile / dead-PID holders automatically while never disturbing a healthy active-profile relay.

**Architecture:** A new pure classifier `relay_start_plan` (decision table over already-available signals) returns one of `running` / `start` / `heal` plus the PIDs to kill and a reason. The existing `relay_start` becomes a thin impure wrapper that gathers signals, calls the classifier, and on `heal` hard-kills every holder of 8088 + the feed ports before the normal fresh-start path. The old refuse-on-foreign-holder function `relay_start_port_note` is removed. The Control Center "kill stale relay" op is re-pointed to a forceful `freeport`.

**Tech Stack:** Pure Python + stdlib. Tests are runnable scripts (no pytest), one `t_*` function per case, picked up by each test file's existing `__main__` runner. Cross-platform port/kill helpers already exist in `src/scripts/ports.py` (`pids_on_port`, `kill_pid`, `FEED_PORTS`).

**Spec:** `docs/superpowers/specs/2026-06-23-self-healing-relay-start-design.md`

---

## Reference: current code

- `src/racecast.py`
  - `RELAY_PORT = 8088` (line ~778)
  - `relay_start_port_note(our_relay_alive, control_pids)` — lines ~1691-1700 (TO BE REMOVED)
  - `relay_start(rest)` — lines ~1702-1739 (TO BE REWIRED)
  - helpers reused: `pt.pids_on_port`, `pt.FEED_PORTS`, `pt.kill_pid`, `sv.read_pid`,
    `sv.pid_alive`, `sv.start_detached`, `_relay_pid_path`, `_running_relay_profile`,
    `_active_profile_name`, `_relay_http_ok`, `_clear_relay_profile_stamp`,
    `_ensure_active_console_secret`, `_write_relay_profile_stamp`, `_relay_daemon_argv`,
    `_relay_boot_log_path`, `_frozen_child_env`, `_append_tailscale_snapshot`,
    `_refresh_obs_pages`, `_stint_args`, `wait_for`
- `src/ui/ui_ops.py` — `OPS["kill-relay"] = ["freeport", "8088"]` (line ~32)
- `tests/test_racecast.py` — loads the module as `m` via importlib; `t_relay_start_port_note()` lines ~2591-2597 (TO BE REPLACED)
- `tests/test_ui_ops.py` — imports `ui_ops`; registry/route tests at lines ~118-145

---

## Task 1: Pure classifier `relay_start_plan`

**Files:**
- Modify: `src/racecast.py` (add `relay_start_plan` just above `relay_start`, ~line 1702)
- Test: `tests/test_racecast.py` (add new `t_*` functions; do NOT touch `t_relay_start_port_note` yet)

- [ ] **Step 1: Write the failing tests**

Add these functions anywhere among the other `t_*` functions in `tests/test_racecast.py` (e.g. directly after `t_relay_start_port_note`):

```python
def t_relay_start_plan_port_free_starts():
    action, kill, reason = m.relay_start_plan(
        port_pids=[], feed_pids=[], pidfile_pid=None, pidfile_alive=False,
        running_profile="", active_profile="testing", http_ok=False)
    assert action == "start" and kill == [] and reason == ""


def t_relay_start_plan_healthy_active_is_noop():
    action, kill, reason = m.relay_start_plan(
        port_pids=[100], feed_pids=[200], pidfile_pid=100, pidfile_alive=True,
        running_profile="testing", active_profile="testing", http_ok=True)
    assert action == "running" and kill == []


def t_relay_start_plan_dead_pidfile_but_port_held_heals():
    action, kill, reason = m.relay_start_plan(
        port_pids=[100], feed_pids=[], pidfile_pid=None, pidfile_alive=False,
        running_profile="", active_profile="testing", http_ok=False)
    assert action == "heal" and kill == [100] and "100" in reason


def t_relay_start_plan_split_brain_heals_and_unions_pids():
    action, kill, reason = m.relay_start_plan(
        port_pids=[100, 101], feed_pids=[200], pidfile_pid=100, pidfile_alive=True,
        running_profile="testing", active_profile="testing", http_ok=True)
    assert action == "heal" and kill == [100, 101, 200] and "split-brain" in reason


def t_relay_start_plan_not_responding_heals():
    action, kill, reason = m.relay_start_plan(
        port_pids=[100], feed_pids=[], pidfile_pid=100, pidfile_alive=True,
        running_profile="testing", active_profile="testing", http_ok=False)
    assert action == "heal" and kill == [100] and "responding" in reason


def t_relay_start_plan_foreign_holder_heals():
    action, kill, reason = m.relay_start_plan(
        port_pids=[999], feed_pids=[], pidfile_pid=100, pidfile_alive=True,
        running_profile="testing", active_profile="testing", http_ok=True)
    assert action == "heal" and kill == [999] and "foreign" in reason


def t_relay_start_plan_wrong_profile_heals_and_names_both():
    action, kill, reason = m.relay_start_plan(
        port_pids=[100], feed_pids=[], pidfile_pid=100, pidfile_alive=True,
        running_profile="iro-gtec", active_profile="testing", http_ok=True)
    assert action == "heal" and kill == [100]
    assert "iro-gtec" in reason and "testing" in reason


def t_relay_start_plan_empty_stamp_is_mismatch_heals():
    # A current-binary relay always stamps its profile; an absent stamp means an
    # old/pre-stamp daemon -> heal (never a "running" no-op on an empty stamp).
    action, kill, reason = m.relay_start_plan(
        port_pids=[100], feed_pids=[], pidfile_pid=100, pidfile_alive=True,
        running_profile="", active_profile="testing", http_ok=True)
    assert action == "heal" and kill == [100]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -c "import sys; sys.path.insert(0,'tests'); import test_racecast as t; t.t_relay_start_plan_port_free_starts()"`
Expected: FAIL with `AttributeError: module 'racecast' has no attribute 'relay_start_plan'`

- [ ] **Step 3: Implement `relay_start_plan`**

Insert directly **above** `def relay_start(rest):` in `src/racecast.py`:

```python
def relay_start_plan(*, port_pids, feed_pids, pidfile_pid, pidfile_alive,
                     running_profile, active_profile, http_ok):
    """Pure: decide what `relay start` must do, from the gathered signals.

    Returns (action, kill_pids, reason):
      action  "start"   control port free -> just start
              "running" exactly one healthy active-profile relay we own -> no-op
              "heal"    a defect (orphan / split-brain / wrong-profile / dead-PID /
                        not-responding) -> kill kill_pids, then start fresh
      kill_pids  sorted union of the 8088 + feed-port holders (heal only, else [])
      reason     short plain-language defect string (heal only, else "")

    An EMPTY/unknown running_profile counts as a mismatch (heal): a current-binary
    relay always writes its stamp, so a stampless holder is a pre-stamp/old daemon.
    """
    port_set = set(port_pids)
    if not port_set:
        return ("start", [], "")
    single = len(port_set) == 1
    ours = single and pidfile_alive and (pidfile_pid in port_set)
    if ours and http_ok and running_profile and running_profile == active_profile:
        return ("running", [], "")
    kill = sorted(port_set | set(feed_pids))
    if len(port_set) > 1:
        reason = "split-brain: %d listeners on port %d" % (len(port_set), RELAY_PORT)
    elif not ours:
        reason = "foreign holder PID %s" % ", ".join(str(p) for p in sorted(port_set))
    elif not http_ok:
        reason = "relay not responding on port %d" % RELAY_PORT
    else:
        reason = "serving profile %r, active is %r" % (
            running_profile or "(none)", active_profile)
    return ("heal", kill, reason)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run each new test (or just run the whole file): `python tests/test_racecast.py`
Expected: PASS (prints the file's normal "all tests passed" footer, exit 0)

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(relay): pure relay_start_plan classifier for self-healing start"
```

---

## Task 2: Rewire `relay_start` to heal; remove `relay_start_port_note`

**Files:**
- Modify: `src/racecast.py` — replace `relay_start` body; delete `relay_start_port_note`
- Test: `tests/test_racecast.py` — delete `t_relay_start_port_note`

- [ ] **Step 1: Delete the obsolete test**

Remove the whole function `t_relay_start_port_note()` (lines ~2591-2597) from `tests/test_racecast.py`:

```python
def t_relay_start_port_note():
    # Our own relay is caught by the earlier PID check; this only fires for a
    # FOREIGN holder of 8088 (and never when the port is free).
    assert m.relay_start_port_note(True, [123]) is None
    assert m.relay_start_port_note(False, []) is None
    note = m.relay_start_port_note(False, [999])
    assert note and "999" in note and str(m.RELAY_PORT) in note and "freeport" in note
```

- [ ] **Step 2: Delete `relay_start_port_note` from `src/racecast.py`**

Remove the whole function (lines ~1691-1700):

```python
def relay_start_port_note(our_relay_alive, control_pids):
    """Message when the control port (8088) is held by something that is NOT our
    relay (our own relay is caught earlier by the singleton PID check). None when
    the port is free or our relay holds it. Such a holder makes the new relay's
    control-port bind fail (#273) — refuse with a pointer to the recovery action."""
    if our_relay_alive or not control_pids:
        return None
    return (f"port {RELAY_PORT} is held by PID {', '.join(map(str, control_pids))} "
            f"(not a racecast relay) — the relay's control port would fail to bind. "
            f"Free it first: racecast freeport {RELAY_PORT}")
```

- [ ] **Step 3: Replace the `relay_start` body**

Replace the entire current `relay_start` function with:

```python
def relay_start(rest):
    stint = _stint_args(rest)   # validate early: fail fast BEFORE spawning the daemon
    # Gather the signals for the pure plan. The PID file is the un-scoped singleton
    # (_relay_pid_path), so it finds the one tracked relay even across a profile
    # switch; pids_on_port finds EVERY listener (incl. an untracked orphan / a
    # Windows dual-bind split-brain) the PID file cannot see.
    port_pids = pt.pids_on_port(RELAY_PORT)
    feed_pids = sorted({p for fp in pt.FEED_PORTS for p in pt.pids_on_port(fp)})
    pid = sv.read_pid(_relay_pid_path())
    action, kill_pids, reason = relay_start_plan(
        port_pids=port_pids, feed_pids=feed_pids,
        pidfile_pid=pid, pidfile_alive=sv.pid_alive(pid),
        running_profile=_running_relay_profile(),
        active_profile=_active_profile_name() or "",
        http_ok=_relay_http_ok() if port_pids else False)
    if action == "running":
        print(f"relay already running (pid {pid}).")
        if stint:
            print(f"  --stint ignored (relay keeps its position) — to reposition the "
                  f"running relay open http://127.0.0.1:{RELAY_PORT}/set/stint/{stint[1]}")
        relay_status([])
        return None
    if action == "heal":
        # Self-heal a defect (orphan / split-brain / wrong-profile / dead-PID /
        # unresponsive). Kill BY PORT — not via the PID file or `freeport` (which
        # refuses while "a relay is alive") — so a cross-profile/old-binary orphan
        # is actually cleared instead of deadlocking the start (#273 follow-up).
        print(f"relay: clearing stale holder(s) of port {RELAY_PORT} "
              f"({reason}) — killing PID {', '.join(map(str, kill_pids))}, then restarting.")
        for kpid in kill_pids:
            pt.kill_pid(kpid)
        left = sorted({p for p in pt.pids_on_port(RELAY_PORT)})
        if left:
            print(f"  WARNING: port {RELAY_PORT} STILL held by PID "
                  f"{', '.join(map(str, left))} after kill — start may fail.")
        if os.path.exists(_relay_pid_path()):
            os.remove(_relay_pid_path())
        _clear_relay_profile_stamp()
    # action in {"start", "heal"} -> fresh start.
    # A feed port may still LISTEN even with 8088 free (a leaked static-streams
    # streamlink) -> warn rather than letting Feed A loop silently in "connecting".
    busy = [p for p in pt.FEED_PORTS if pt.pids_on_port(p)]
    if busy:
        print(f"WARNING: feed port(s) {', '.join(map(str, busy))} already in use — "
              f"that feed may fail to bind. Free them first: racecast freeport")
    _ensure_active_console_secret()   # zero-config console: provision + inject the secret
    _write_relay_profile_stamp()      # record the running profile before spawn (#273)
    argv = _relay_daemon_argv(rest, IS_FROZEN)
    newpid = sv.start_detached(argv, _relay_boot_log_path(), _relay_pid_path(),
                               env=_frozen_child_env())
    print(f"relay started (pid {newpid}). Watch it: racecast relay logs -f")
    _append_tailscale_snapshot()
    _refresh_obs_pages(wait=10)   # waits for the control port, then refreshes OBS pages
    # Post-start verification: exactly one process should now hold 8088. More than
    # one means a residual dual-bind split-brain survived -> surface it, don't hide it.
    holders = sorted({p for p in pt.pids_on_port(RELAY_PORT)})
    if len(holders) > 1:
        print(f"  WARNING: {len(holders)} processes listen on port {RELAY_PORT} "
              f"(PID {', '.join(map(str, holders))}) — possible split-brain; "
              f"re-run 'racecast relay start' to reconcile.")
    return None
```

- [ ] **Step 4: Verify no remaining references to the deleted function**

Run: `grep -rn "relay_start_port_note" src tests tools .github`
Expected: no output (function and its only test are gone).

- [ ] **Step 5: Run the full racecast test file**

Run: `python tests/test_racecast.py`
Expected: PASS, exit 0 (the deleted test is gone; the Task 1 classifier tests pass).

- [ ] **Step 6: Commit**

```bash
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(relay): self-healing relay start; drop refuse-on-foreign-holder path"
```

---

## Task 3: Re-point the Control Center "kill stale relay" op to forceful freeport

**Files:**
- Modify: `src/ui/ui_ops.py` — `OPS["kill-relay"]`
- Test: `tests/test_ui_ops.py` — assert the new argv

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui_ops.py` (e.g. after `t_ops_registry_shape`):

```python
def t_kill_relay_op_is_forceful_and_covers_feed_ports():
    # The manual emergency brake must actually KILL the holder(s): without --force
    # freeport refuses while a relay's PID file reports "alive", so it never reached
    # a cross-profile orphan. Cover the control port AND the feed ports.
    assert ui_ops.OPS["kill-relay"] == [
        "freeport", "--force", "8088", "53001", "53002", "53003"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -c "import sys; sys.path.insert(0,'tests'); import test_ui_ops as t; t.t_kill_relay_op_is_forceful_and_covers_feed_ports()"`
Expected: FAIL with `AssertionError` (current value is `["freeport", "8088"]`).

- [ ] **Step 3: Update the op**

In `src/ui/ui_ops.py`, change the `kill-relay` entry:

```python
    "kill-relay": ["freeport", "--force", "8088", "53001", "53002", "53003"],   # force-free the relay control + feed ports: recover a stale/orphaned relay the Stop button can't reach
```

- [ ] **Step 4: Run the ui_ops test file**

Run: `python tests/test_ui_ops.py`
Expected: PASS, exit 0 (incl. `t_ops_registry_routes_in_rc`, since `freeport --force 8088 …` still routes to `kind == "freeport"`).

- [ ] **Step 5: Commit**

```bash
git add src/ui/ui_ops.py tests/test_ui_ops.py
git commit -m "fix(ui): make 'kill stale relay' force-free the control + feed ports"
```

---

## Task 4: Full gates (lint, suite, build verify)

**Files:** none (verification only)

- [ ] **Step 1: Lint**

Run: `python tools/lint.py`
Expected: no findings (exit 0). If any, fix inline and re-run.

- [ ] **Step 2: Full test suite (exactly what CI runs)**

Run: `python tools/run-tests.py`
Expected: every test file passes, exit 0.

- [ ] **Step 3: Build self-verify**

Run: `python tools/build.py`
Expected: assembles `dist/` and its verify step passes (tokenization, blanked password, no secrets, preflight present, no shell scripts), exit 0.

- [ ] **Step 4: Manual smoke (local, this machine)**

This validates the impure wrapper end-to-end against a real port (the unit tests only cover the pure classifier).

1. Ensure a relay is running, then run `racecast relay start` again → expect `relay already running (pid …)`, no kill.
2. Start a second leftover relay process holding 8088 (or simulate an orphan), then `racecast relay start` → expect a `relay: clearing stale holder(s) …` line naming the reason + PIDs, then a fresh start, then exactly one listener on 8088.

Document the observed output in the PR description.

- [ ] **Step 5: Commit (only if Step 1/3 required fixes)**

```bash
git add -A
git commit -m "chore(relay): lint/build fixups for self-healing start"
```

---

## Self-review notes (author)

- **Spec coverage:** Section 1 table → `relay_start_plan` (Task 1) + wrapper dispatch (Task 2). Heal clears 8088 + feed ports → `kill` union (Task 1) + kill loop (Task 2). No-op on healthy active relay → `running` branch. Empty-stamp = mismatch → dedicated test. Post-start single-holder verify → Task 2 Step 3 tail. Remove `relay_start_port_note` → Task 2. kill-stale button → Task 3. Tests on all OS / no new OS code → reuse `pids_on_port`/`kill_pid` (cross-platform). No UI screenshot change → Task 4 has no `cc-*.png` step (button unchanged visually).
- **Type consistency:** `relay_start_plan` returns `(action, kill_pids, reason)` everywhere; `action` strings `"start"|"running"|"heal"` used identically in Task 1 and Task 2.
- **No placeholders:** every code/step is concrete.
