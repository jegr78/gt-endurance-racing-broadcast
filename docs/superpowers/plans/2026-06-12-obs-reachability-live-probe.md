# Live OBS-reachability probe for `/status`

**Goal:** The director panel's "OBS NOT REACHABLE — NEXT can't auto-cut" banner must
reflect OBS's *current* reachability, not a value cached from the last feed reflection,
so the common "relay started before OBS" case self-heals without a relay restart.

**Architecture:** Today `Relay.obs_note` is written **only** by `_reflect()` — which runs
at startup and on `/next` / `/set/stint`. If OBS isn't listening when the relay boots
(e.g. `event start` brings the relay up first), the startup probe records
"not reachable" and nothing re-checks until the next handover, so `/status` reports a
stale `obs.reachable: false` forever. Fix: add a side-effect-free obs-websocket
reachability probe (`obs_ws.probe()`) and have `Relay.status()` kick it off
**throttled, off-thread**. A new `Relay.obs_reachable` field — owned by the probe —
drives the banner; `obs_note` stays for diagnostics.

**Tech stack:** Pure Python 3 stdlib. Tests are runnable scripts (`tests/test_*.py`).

---

### Task 1: `obs_ws.probe()` — a side-effect-free reachability check

**Files:**
- Modify: `src/scripts/obs_ws.py` (new function after `_connect`)
- Test: `tests/test_obsws.py`

- [ ] **Test first** (reuses the existing fake-OBS harness + free-port pattern):

```python
def t_probe_unreachable_is_quiet():
    sock = socket.socket(); sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]; sock.close()
    reachable, note = m.probe(port=free_port, password="x", timeout=0.5)
    assert reachable is False
    assert note                                    # human-readable reason

def t_probe_end_to_end_against_fake_server():
    state = {"released": []}
    port, srv = _start_fake_obs(state)
    reachable, note = m.probe(port=port, password="supersecret", timeout=5)
    assert reachable is True
    assert note == "", note
    srv.close()
```

- [ ] **Implement:**

```python
def probe(host="127.0.0.1", port=None, password=None, timeout=2.0):
    """Lightweight OBS reachability check used by the relay's /status: open an
    obs-websocket session (handshake + auth) and close it at once, touching
    nothing in OBS. Returns (reachable: bool, note: str) — (False, reason) when
    OBS is closed/locked/mis-keyed, (True, "") on a full identify. Never raises
    (same best-effort contract as the other entry points)."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    session.close()
    return True, ""
```

- [ ] Run `python3 tests/test_obsws.py` → ALL PASS. Commit.

---

### Task 2: throttle decision — pure `should_probe_obs()`

**Files:**
- Modify: `src/relay/racecast-feeds.py` (module-level helper + constant)
- Test: `tests/test_health.py` (already imports the relay module)

- [ ] **Test first:**

```python
def t_should_probe_obs_throttles_and_respects_inflight():
    # first call (last_ts=0, not running) -> probe
    assert m.should_probe_obs(0.0, False, 1000.0, 5.0) is True
    # within the interval -> skip
    assert m.should_probe_obs(998.0, False, 1000.0, 5.0) is False
    # interval elapsed -> probe again
    assert m.should_probe_obs(994.0, False, 1000.0, 5.0) is True
    # a probe already in flight -> never launch a second
    assert m.should_probe_obs(0.0, True, 1000.0, 5.0) is False
```

- [ ] **Implement** (near the other module-level helpers):

```python
OBS_PROBE_INTERVAL_S = 5.0   # min seconds between background OBS reachability probes

def should_probe_obs(last_ts, running, now, interval):
    """True when status() should kick off a fresh OBS reachability probe: none
    already in flight, and the previous probe is older than `interval`. Pure so
    the throttle is unit-testable without a live relay."""
    return not running and (now - last_ts) >= interval
```

- [ ] Run `python3 tests/test_health.py` → ALL PASS. Commit.

---

### Task 3: wire the probe into `Relay.status()`

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`Relay.__init__`, new `_maybe_probe_obs`, `status`)

- [ ] **`__init__`** — add next to `self.obs_note` (line ~1516):

```python
self.obs_note = None          # last OBS note (None/"" = ok); read by status()
self.obs_reachable = None     # last LIVE reachability probe; None until first /status
self._obs_probe_ts = 0.0      # time.time() of the last reachability probe
self._obs_probe_running = False
self._obs_lock = threading.Lock()
```

- [ ] **New method** (after `_reflect`):

```python
def _maybe_probe_obs(self, now):
    """Kick off a throttled, side-effect-free OBS reachability probe off-thread so
    /status reflects OBS's CURRENT state, not a value cached from the last
    handover. Makes the common 'relay started before OBS' case self-heal: the
    banner clears within one probe interval once OBS is up — no restart, no
    handover needed."""
    if _obs_ws is None:
        return
    with self._obs_lock:
        if not should_probe_obs(self._obs_probe_ts, self._obs_probe_running,
                                now, OBS_PROBE_INTERVAL_S):
            return
        self._obs_probe_running = True

    def run():
        reachable, note = _obs_ws.probe()
        with self._obs_lock:
            self.obs_reachable = reachable
            self.obs_note = note or None
            self._obs_probe_ts = time.time()
            self._obs_probe_running = False
    threading.Thread(target=run, daemon=True).start()
```

- [ ] **`status()`** — trigger the probe and report the probed field:

```python
def status(self):
    now = time.time()
    self._maybe_probe_obs(now)
    ...
    out["obs"] = {"reachable": self.obs_reachable, "note": self.obs_note}
    return out
```

`_reflect()` is left unchanged — it still records `obs_note` for immediate
post-handover diagnostics; the probe owns `obs_reachable` (and refreshes the note
within one interval). The panel banner keys on `obs.reachable === false`, so an
unknown (`null`) state before the first probe shows no banner — no false alarm.

- [ ] Run the full relay suite (`test_pov`, `test_health`, `test_timer`, `test_hud`) → green. Commit.

---

### Task 4: regression sweep + ship

- [ ] `python3 tools/run-tests.py` (the whole suite, what CI runs) → ALL PASS.
- [ ] `python3 tools/lint.py` → clean.
- [ ] `python3 tools/build.py` verify step → passes (no secrets, tokenization, no shell scripts).
- [ ] Commit, push, open PR.
