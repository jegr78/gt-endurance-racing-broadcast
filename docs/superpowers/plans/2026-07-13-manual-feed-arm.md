# Two-stage Feed Arm/Disarm (#492) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in two-stage feed model — enter a stint URL early, then explicitly arm/disarm each feed's pull — by extending the proven POV `paused` gate to Feed A/B.

**Architecture:** A pure `manual_feed_arm_enabled(environ)` flag (default OFF). When on, `Relay.__init__` starts both A/B feeds `paused` (disarmed); `feed_activate`/`feed_deactivate` (mirroring `pov_reload`/`pov_stop`) arm/disarm a feed's pull, behind director-gated `GET /feed/<A|B>/{activate,deactivate}`. Auto mode is 100% unchanged; the two models never mix (arm/disarm are manual-mode-only). Desync detection (#494) is suppressed in manual mode.

**Tech Stack:** Python 3 stdlib only; plain HTML/JS front-end (`director-panel.html`). Tests are runnable scripts (no pytest) under `tests/`, loaded via `importlib` as `m`.

## Global Constraints

- **Edit only under `src/`** (`dist/`/`runtime/` generated). Tests under `tests/`.
- **English only** in code/comments/log lines/UI copy/docs.
- **Python stdlib only** — no new dependencies.
- **`RACECAST_MANUAL_FEED_ARM` default OFF** — enabled only on an explicit truthy token (`_FAILOVER_TRUTHY = {"1","true","yes","on"}`). Flag off ⇒ behaviour is **100% unchanged**.
- **Arm/disarm are manual-mode-only** — in auto mode they return `{"error": "manual feed arm disabled (set RACECAST_MANUAL_FEED_ARM=1)"}` and mutate nothing.
- **`live_feed()` and the auto pre-warm/handover logic are NOT modified.**
- After a relay change run `python3 tests/test_pov.py`; before finishing run `python3 tools/run-tests.py` + `python3 tools/lint.py`.
- No secrets/machine-paths/real-IPs in tests.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Spec: `docs/superpowers/specs/2026-07-13-manual-feed-arm-design.md`. Issue #492.

---

### Task 1: Opt-in flag + init disarm + `/status` fields

**Files:**
- Modify: `src/relay/racecast-feeds.py` — add `manual_feed_arm_enabled(environ)` next to `auto_failover_enabled` (~line 260); set `self.manual_feed_arm` + disarm A/B in `Relay.__init__` (~line 5288, after `self.feeds = {...}`); add `manual_feed_arm` + per-feed `armed` to `status()` (~line 5610).
- Test: `tests/test_pov.py`

**Interfaces:**
- Produces: `manual_feed_arm_enabled(environ) -> bool`; `Relay.manual_feed_arm` (bool); `status()["manual_feed_arm"]` (bool) and `status()["feeds"][A|B]["armed"]` (`not paused`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pov.py` (auto-discovered by the `__main__` runner — no registration):

```python
def t_manual_feed_arm_enabled():
    # OFF by default (opt-in) — absent or empty is off.
    assert m.manual_feed_arm_enabled({}) is False
    assert m.manual_feed_arm_enabled({"RACECAST_MANUAL_FEED_ARM": ""}) is False
    # Explicit truthy tokens enable it.
    for v in ("1", "true", "yes", "on", "ON", "True"):
        assert m.manual_feed_arm_enabled({"RACECAST_MANUAL_FEED_ARM": v}) is True, v
    # Anything else stays off.
    for v in ("0", "false", "no", "off", "banana"):
        assert m.manual_feed_arm_enabled({"RACECAST_MANUAL_FEED_ARM": v}) is False, v


def t_relay_manual_arm_starts_feeds_disarmed():
    rows = [("uA", "A", "S1", 1), ("uB", "B", "S2", 2)]
    # Default (flag absent): feeds armed (paused False), manual_feed_arm False.
    r = m.Relay(_StubSource(["uA", "uB"], rows), (53001, 53002), LOGDIR)
    assert r.manual_feed_arm is False
    assert r.A.paused is False and r.B.paused is False
    st = r.status()
    assert st["manual_feed_arm"] is False
    assert st["feeds"]["A"]["armed"] is True and st["feeds"]["B"]["armed"] is True
    # Flag on: both feeds start disarmed (paused), armed=False in /status.
    os.environ["RACECAST_MANUAL_FEED_ARM"] = "1"
    try:
        r2 = m.Relay(_StubSource(["uA", "uB"], rows), (53003, 53004), LOGDIR)
    finally:
        del os.environ["RACECAST_MANUAL_FEED_ARM"]
    assert r2.manual_feed_arm is True
    assert r2.A.paused is True and r2.B.paused is True
    st2 = r2.status()
    assert st2["manual_feed_arm"] is True
    assert st2["feeds"]["A"]["armed"] is False and st2["feeds"]["B"]["armed"] is False
```

(`os` and `time` are already imported at the top of `tests/test_pov.py`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_pov.py`
Expected: FAIL — `AttributeError: module 'irofeeds' has no attribute 'manual_feed_arm_enabled'`.

- [ ] **Step 3: Write minimal implementation**

In `src/relay/racecast-feeds.py`, add the pure helper right after `auto_failover_enabled` (it reuses the existing `_FAILOVER_TRUTHY` set, ~line 265):

```python
def manual_feed_arm_enabled(environ):
    """True only when RACECAST_MANUAL_FEED_ARM is an explicit truthy token. OFF by
    default (opt-in): the default is today's auto-pull + auto-pre-warm. When on,
    both A/B feeds start disarmed (paused) and the director arms/disarms each pull
    explicitly (#492). Pure so the switch is unit-testable."""
    return str(environ.get("RACECAST_MANUAL_FEED_ARM", "")).strip().lower() in _FAILOVER_TRUTHY
```

In `Relay.__init__`, right after `self.feeds = {"A": self.A, "B": self.B}` (~line 5288):

```python
        # Two-stage feed scheduling (#492): when RACECAST_MANUAL_FEED_ARM is set,
        # both A/B feeds start DISARMED (paused) — a URL at the index does not pull
        # until the director arms the feed. Default off = auto-pull unchanged.
        self.manual_feed_arm = manual_feed_arm_enabled(os.environ)
        if self.manual_feed_arm:
            self.A.paused = True
            self.B.paused = True
```

In `status()`, add `"armed": not f.paused` to the per-feed dict in the feeds loop (~line 5612, alongside `"state"`):

```python
                               "state": "stopped" if f.paused else f.phase,
                               "armed": not f.paused,
```

And add the top-level field — on the line immediately after `out["live"] = {...}` (~line 5633):

```python
        out["manual_feed_arm"] = self.manual_feed_arm
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_pov.py`
Expected: PASS (all `t_*`).

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): RACECAST_MANUAL_FEED_ARM flag — start feeds disarmed (#492)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Arm/disarm actions + endpoints + policy

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `Relay.feed_activate`/`feed_deactivate` (after `pov_stop`, ~line 6234); dispatch for `GET /feed/<A|B>/{activate,deactivate}` (after the `/pov/*` dispatch, ~line 7598).
- Modify: `src/scripts/console_policy.py` — map `["feed", A|B, activate|deactivate]` to `Requirement(DIRECTOR, False)` (~line 81, near the `pov` mapping).
- Test: `tests/test_pov.py` (actions), `tests/test_console.py` (policy).

**Interfaces:**
- Consumes: `self.manual_feed_arm` (Task 1); `self.feeds`; `Feed.paused`/`reload`/`current_channel`.
- Produces: `Relay.feed_activate(which) -> status|error`; `Relay.feed_deactivate(which) -> status|error`; routes `/feed/<A|B>/activate` + `/feed/<A|B>/deactivate`; policy `min_capability(["feed","A","activate"]) == Requirement(DIRECTOR, False)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pov.py`:

```python
def t_feed_activate_deactivate_manual_mode():
    rows = [("uA", "A", "S1", 1), ("uB", "B", "S2", 2)]
    r = m.Relay(_StubSource(["uA", "uB"], rows), (53001, 53002), LOGDIR)
    r._reflect = lambda live, cut: None
    # Force manual mode + disarmed, as Relay.__init__ would with the flag on.
    r.manual_feed_arm = True
    r.A.paused = True; r.B.paused = True
    # URL present at the index but paused -> NO pull (current_channel gates on paused).
    assert r.A.current_channel() == (None, 0)
    # Arm A: unpaused; the URL is now pullable.
    r.feed_activate("A")
    assert r.A.paused is False
    assert r.A.current_channel() == ("uA", 0)
    # A deactivated feed reports "stopped", never "down" (no health alarm).
    r.feed_deactivate("A")
    assert r.A.paused is True
    fa = r.status()["feeds"]["A"]
    assert fa["state"] == "stopped" and fa["down"] is False and fa["armed"] is False


def t_feed_arm_disabled_in_auto_mode():
    rows = [("uA", "A", "S1", 1), ("uB", "B", "S2", 2)]
    r = m.Relay(_StubSource(["uA", "uB"], rows), (53001, 53002), LOGDIR)
    assert r.manual_feed_arm is False
    before = r.A.paused
    res = r.feed_activate("A")
    assert "error" in res
    assert r.A.paused == before          # mutated nothing
    assert "error" in r.feed_deactivate("B")


def t_feed_arm_unknown_feed():
    rows = [("uA", "A", "S1", 1)]
    r = m.Relay(_StubSource(["uA"], rows), (53001, 53002), LOGDIR)
    r.manual_feed_arm = True
    assert "error" in r.feed_activate("Z")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_pov.py`
Expected: FAIL — `AttributeError: 'Relay' object has no attribute 'feed_activate'`.

- [ ] **Step 3: Write minimal implementation**

Add to `Relay`, right after `pov_stop` (~line 6234):

```python
    def feed_activate(self, which):
        """Arm Feed A/B: start pulling at its current index (two-stage scheduling,
        #492). Mirrors pov_reload. Manual-mode only — an error otherwise so the auto
        pre-warm/handover logic and manual arm never fight."""
        if not self.manual_feed_arm:
            return {"error": "manual feed arm disabled (set RACECAST_MANUAL_FEED_ARM=1)"}
        f = self.feeds.get(which.upper())
        if not f:
            return {"error": f"unknown feed {which!r}"}
        f.paused = False
        f.reload()
        LOG.info("feed %s armed (manual)", which.upper())
        return self.status()

    def feed_deactivate(self, which):
        """Disarm Feed A/B: stop its pull, kill the process, close the port (frees
        bandwidth) — mirrors pov_stop. Manual-mode only (#492)."""
        if not self.manual_feed_arm:
            return {"error": "manual feed arm disabled (set RACECAST_MANUAL_FEED_ARM=1)"}
        f = self.feeds.get(which.upper())
        if not f:
            return {"error": f"unknown feed {which!r}"}
        f.paused = True
        f.reload()
        LOG.info("feed %s disarmed (manual)", which.upper())
        return self.status()
```

Add the dispatch in `do_GET`, right after the `/pov/*` lines (~line 7598):

```python
                if len(p)==3 and p[0]=="feed" and p[2]=="activate":
                    return self._send(relay.feed_activate(p[1]))
                if len(p)==3 and p[0]=="feed" and p[2]=="deactivate":
                    return self._send(relay.feed_deactivate(p[1]))
```

In `src/scripts/console_policy.py`, add to the director block right after the `pov` mapping (~line 81):

```python
    if len(p) == 3 and p[0] == "feed" and p[2] in ("activate", "deactivate"):
        return Requirement(DIRECTOR, False)   # two-stage feed arm/disarm (#492)
```

- [ ] **Step 4: Add the policy test, then run both files**

Append to `tests/test_console.py` (it binds `cp = _load("console_policy", …)`):

```python
def t_feed_arm_is_director_no_stepup():
    for act in ("activate", "deactivate"):
        assert cp.min_capability(["feed", "A", act]) == cp.Requirement(cp.DIRECTOR, False), act
        assert cp.min_capability(["feed", "B", act]) == cp.Requirement(cp.DIRECTOR, False), act
```

Run: `python3 tests/test_pov.py`  → PASS
Run: `python3 tests/test_console.py`  → PASS

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py src/scripts/console_policy.py tests/test_pov.py tests/test_console.py
git commit -m "feat(relay): feed_activate/deactivate + /feed/<A|B> endpoints (#492)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Suppress desync detection in manual mode

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `Relay._compute_desync` (early return when `self.manual_feed_arm`).
- Test: `tests/test_pov.py`

**Interfaces:**
- Consumes: `self.manual_feed_arm` (Task 1); the existing `_compute_desync`/`_desync` state (#494).
- Produces: `_compute_desync` returns an inactive block (and `status()["desync"]["active"]` is False) whenever manual mode is on.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pov.py`:

```python
def t_desync_suppressed_in_manual_mode():
    rows = [("uA", "A", "S1", 1), ("uB", "B", "S2", 2),
            ("uC", "C", "S3", 3), ("uD", "D", "S4", 4)]
    r = m.Relay(_StubSource(["uA", "uB", "uC", "uD"], rows), (53001, 53002), LOGDIR)
    r._reflect = lambda live, cut: None
    # Construct a would-be desync: on-air feed A dropped, off-air feed B serving,
    # past the settle window — in AUTO mode this fires the desync flag.
    r.A.phase = "connecting"; r.A.dropped = True
    r.B.phase = "serving"; r.B.dropped = False
    r._desync_since = time.time() - 20
    assert r.status()["desync"]["active"] is True          # auto mode: fires
    # Manual mode: the same feed state must NOT raise a desync (intentional disarm).
    r.manual_feed_arm = True
    assert r.status()["desync"]["active"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_pov.py`
Expected: FAIL — the manual-mode assertion fails (`active` is still True).

- [ ] **Step 3: Write minimal implementation**

In `_compute_desync`, add an early return at the very top (before `live = self.live_feed()`):

```python
        if self.manual_feed_arm:
            # Manual mode intentionally disarms feeds; the index-derived desync
            # predicate would false-positive during arm-before-cut. Off here (#492).
            self._desync_active = False
            self._desync_since = None
            self._desync = {"active": False}
            return self._desync
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_pov.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): suppress ping-pong desync detection in manual feed-arm mode (#492)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Director Panel per-feed ARM / STOP-PULL toggle (manual-mode only)

**Files:**
- Modify: `src/director/director-panel.html` — a per-feed arm/disarm control shown only when `d.manual_feed_arm`, plus a `feedArm(which, on)` helper.
- Test: none (visual surface; verified by the task reviewer's diff read + the controller visual verification in Task 5).

**Interfaces:**
- Consumes: `d.manual_feed_arm` and `d.feeds[A|B].armed` from `/status` (Task 1); the `/feed/<A|B>/{activate,deactivate}` routes (Task 2); the existing `relayCall`, `$`, and the feed-status render (the `#stA`/`#stB` pills, ~line 1425 in the `/status` poll).

- [ ] **Step 1: Add a manual-arm control container to the markup**

Find the feed-status row that holds the `#stA`/`#stB` pills (search `id="stA"`). Immediately after that row's container, add an initially-hidden control block:

```html
  <div id="feedArm" class="setrow" style="display:none">
    <button class="armbtn" data-feed="A" data-on="1">ARM A</button>
    <button class="armbtn" data-feed="A" data-on="0">STOP A</button>
    <button class="armbtn" data-feed="B" data-on="1">ARM B</button>
    <button class="armbtn" data-feed="B" data-on="0">STOP B</button>
  </div>
```

Add a minimal button style next to the panel's other button CSS:

```css
  .armbtn{padding:4px 10px;border-radius:6px;border:1px solid var(--edge);
          background:transparent;color:var(--ink);font-weight:700;cursor:pointer;font-size:12px}
  .armbtn.armed{border-color:#3ce07f;color:#3ce07f}
```

- [ ] **Step 2: Add the `feedArm` handler + wire the buttons**

Near the other `relayCall` helpers, add:

```javascript
function feedArm(which, on){
  relayCall("feed/" + which + "/" + (on ? "activate" : "deactivate"));
}
document.querySelectorAll("#feedArm .armbtn").forEach(b =>
  b.addEventListener("click", () => feedArm(b.dataset.feed, b.dataset.on === "1")));
```

- [ ] **Step 3: Show the control only in manual mode + reflect armed state**

In the `/status` poll (where `d.feeds.A`/`d.feeds.B` are read, ~line 1425), after the feed pills are updated add:

```javascript
    const arm = $("#feedArm");
    if (d.manual_feed_arm) {
      arm.style.display = "";
      // Green-highlight the ARM button of a feed that is currently armed.
      arm.querySelectorAll(".armbtn").forEach(b => {
        const f = d.feeds[b.dataset.feed];
        const isArmOn = b.dataset.on === "1";
        b.classList.toggle("armed", !!(f && f.armed) && isArmOn);
      });
    } else {
      arm.style.display = "none";
    }
```

- [ ] **Step 4: Sanity-check the markup**

Run: `python3 -c "import pathlib; s=pathlib.Path('src/director/director-panel.html').read_text(); assert 'feed/' in s and 'feedArm' in s and 'manual_feed_arm' in s and 'armbtn' in s; print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/director/director-panel.html
git commit -m "feat(panel): per-feed ARM/STOP-PULL toggle in manual feed-arm mode (#492)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Full suite + lint + visual verify

**Files:** none (verification gate).

- [ ] **Step 1: Full suite + lint**

Run: `python3 tools/run-tests.py`
Expected: all test files pass (exit 0).
Run: `python3 tools/lint.py`
Expected: `All checks passed`.

- [ ] **Step 2: Visual verify the manual-mode panel control (CONTROLLER task)**

Performed by the controller, not a code subagent. Render `director-panel.html` (headless, `.venv-pw`, or the demo build) with a `/status` payload carrying `manual_feed_arm: true` and `feeds.A.armed`/`feeds.B.armed`, screenshot the `#feedArm` control, Read it, and confirm: theme-fit buttons (not white browser defaults), the armed feed's ARM button highlighted green, the control hidden when `manual_feed_arm` is false. Record the marker:
`python3 .claude/hooks/record_ui_verified.py src/director/director-panel.html`.

**Wiki image:** the toggle appears only in manual mode; the default (auto-mode) panel is unchanged, so `director-panel.png` is NOT regenerated (same judgment as #494's conditional banner) — record the deferral in the ledger.

---

## Self-Review

**Spec coverage:**
- §1 opt-in flag + init disarm → Task 1 (`manual_feed_arm_enabled`, `__init__` disarm, `/status` fields).
- §2 arm/disarm actions (manual-only, error in auto) → Task 2.
- §3 `/next` no special-casing → nothing to build (the existing `cut=serving` gate handles it); noted in Global Constraints ("auto pre-warm/handover NOT modified"). A test would exercise unchanged code — omitted per YAGNI.
- §4 desync suppression in manual mode → Task 3.
- §5 endpoints + policy → Task 2 (routes + `console_policy`).
- §6 `/status` `manual_feed_arm` + per-feed `armed` → Task 1; Director Panel toggle → Task 4; wiki judgment → Task 5.
- §7 tests → Tasks 1/2/3 (flag, actions incl. URL-present-but-paused, stopped-not-down, auto-mode error, desync suppression, policy).
- **Companion buttons (spec §6 / AC):** the `companionconfig` is a 5203-line hand-maintained JSON exported from the Companion UI (not a code artifact — `export companion` only copies it). Adding buttons is a Companion-UI → re-export → strip workflow, like the wiki screenshots. **Deferred to a maintainer follow-up**; the Director Panel + endpoints deliver the full capability over tailnet AND Funnel. Flagged to the product owner at plan handoff.

**Placeholder scan:** none — Task 4's markup anchor ("find the `#stA`/`#stB` row") is a locate-then-insert instruction against a named existing element, with the exact HTML/CSS/JS to add; not a logic placeholder.

**Type consistency:** `manual_feed_arm_enabled(environ) -> bool`; `Relay.manual_feed_arm` (bool); `feed_activate(which)`/`feed_deactivate(which)` return `status|{"error":...}`; `/status` keys `manual_feed_arm` (top-level) + `feeds[X].armed` used identically in the panel (`d.manual_feed_arm`, `d.feeds[X].armed`). Route segments `["feed", A|B, activate|deactivate]` match the policy mapping.
