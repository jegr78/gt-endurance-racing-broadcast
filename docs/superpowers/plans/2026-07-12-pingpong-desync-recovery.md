# Ping-pong Desync Detection + Recovery (#494) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect a ping-pong/cockpit desync (the index-designated on-air feed is not delivering while the other feed is), surface it as a Director-Panel banner + a panel-local `/status` field, degrade the cockpit to "syncing…", and recover with a feed-agnostic `resync_to_stint(N)` that preserves whichever feed actually serves N.

**Architecture:** Two pure helpers (`ping_pong_desynced`, `desync_settled`) drive a debounced desync flag the heartbeat/`_refresh_health` recomputes but never acts on. A new feed-agnostic `resync_to_stint` reconciles onto the serving feed (no cut), exposed at `GET /resync/stint/<n>` (director-tier). The Director Panel renders a red banner with a one-click Resync button; the cockpit short-circuits to "syncing…" on a top-level `syncing` flag.

**Tech Stack:** Python 3 stdlib only. Front-end is plain HTML/JS in `src/director/director-panel.html` and `src/cockpit/cockpit.html`. Tests are runnable scripts (no pytest) under `tests/`, loaded via `importlib`.

## Global Constraints

- **Edit only under `src/`** (`dist/`/`runtime/` are generated). Tests go under `tests/`.
- **English only** in all code, comments, log lines, UI copy, docs.
- **Python stdlib only** — no new dependencies; the relay stays dependency-light.
- **After any relay change run** `python3 tests/test_pov.py`; **before finishing run** `python3 tools/run-tests.py` (full suite) and `python3 tools/lint.py` (ruff).
- **No secrets/machine-paths/real-IPs in tests** (CI + Windows matrix).
- **`live_feed()` stays unchanged** — it is the pure index invariant driving handover; the desync flag is a separate, display-only signal.
- **The heartbeat never mutates feeds/OBS** — detection only (banner + log). Recovery is the operator-triggered `resync_to_stint`.
- **Debounce constant is the existing `HEALTH_CONNECTING_SETTLE_S` (= 15).**
- **UI surfaces changed → refresh wiki screenshots in this change:** `src/docs/wiki/images/director-panel.png` (banner) + the cockpit image ("syncing…"). Capture from a local dev build.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Spec: `docs/superpowers/specs/2026-07-12-pingpong-desync-recovery-design.md`. Issue #494.

---

### Task 1: Desync detection — pure helpers + Relay state + `/status` field

**Files:**
- Modify: `src/relay/racecast-feeds.py` — add two pure helpers near the slot helpers (~line 3820); add desync state to `Relay.__init__` (~line 5298, near `self.health_level`), a `_feed_serving` helper + `_compute_desync(now)` method, call it from `_refresh_health` (~line 5387), and add `out["desync"]` to `status()` (~line 5604).
- Test: `tests/test_pov.py`

**Interfaces:**
- Produces:
  - `ping_pong_desynced(live_serving, off_serving) -> bool`
  - `desync_settled(raw, since_ts, now, settle_s) -> (active: bool, since_ts: float|None)`
  - `Relay._compute_desync(now)` sets `self._desync` = `{"active", "since_s", "serving_feed", "suggested_stint"}` (the `/status` `desync` block); `status()["desync"]` exposes it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pov.py` (auto-discovered by the `__main__` runner — no registration):

```python
def t_ping_pong_desynced_pure():
    # On-air feed not delivering while the off-air feed is -> desynced.
    assert m.ping_pong_desynced(live_serving=False, off_serving=True) is True
    # On-air fine -> never desynced.
    assert m.ping_pong_desynced(live_serving=True, off_serving=True) is False
    assert m.ping_pong_desynced(live_serving=True, off_serving=False) is False
    # On-air down but nothing better to show (off not serving) -> a plain drop,
    # a health condition, NOT a desync.
    assert m.ping_pong_desynced(live_serving=False, off_serving=False) is False


def t_desync_settled_debounce():
    # Not raw -> inactive, timer cleared.
    assert m.desync_settled(False, 100.0, 200.0, 15) == (False, None)
    # Raw first seen -> timer starts, not yet active (0 < settle).
    assert m.desync_settled(True, None, 100.0, 15) == (False, 100.0)
    # Raw, still within the settle window -> not active, timer preserved.
    assert m.desync_settled(True, 100.0, 110.0, 15) == (False, 100.0)
    # Raw, past the settle window -> active, timer preserved.
    assert m.desync_settled(True, 100.0, 116.0, 15) == (True, 100.0)


def t_relay_status_exposes_desync_block():
    rows = [("uA", "A", "S1", 1), ("uB", "B", "S2", 2),
            ("uC", "C", "S3", 3), ("uD", "D", "S4", 4)]
    r = m.Relay(_StubSource(["uA", "uB", "uC", "uD"], rows), (53001, 53002), LOGDIR)
    r._reflect = lambda live, cut: None
    # Simulate: on-air feed A (idx0) dropped, off-air feed B (idx1) serving.
    r.A.phase = "connecting"; r.A.dropped = True
    r.B.phase = "serving"; r.B.dropped = False
    # Force the settle to have already elapsed.
    r._desync_since = time.time() - 20
    d = r.status()["desync"]
    assert d["active"] is True
    assert d["serving_feed"] == "B"
    assert d["suggested_stint"] == 2          # B is on row1 -> stint 2
    # Healthy: both serving -> inactive block.
    r.A.dropped = False; r.A.phase = "serving"
    assert r.status()["desync"]["active"] is False
```

(`import time` is already at the top of `tests/test_pov.py`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_pov.py`
Expected: FAIL — `AttributeError: module 'irofeeds' has no attribute 'ping_pong_desynced'`.

- [ ] **Step 3: Write minimal implementation**

In `src/relay/racecast-feeds.py`, add the two pure helpers after `cockpit_schedule` (~line 3820):

```python
def ping_pong_desynced(live_serving, off_serving):
    """True when the index-designated on-air feed is NOT delivering a stable
    picture while the OFF-air feed IS — the feed on screen and the feed derived as
    on-air disagree. Pure; the caller supplies each feed's 'serving a stable
    picture' boolean and applies the settle debounce. False whenever the on-air
    feed is fine, or the off-air feed is not itself delivering (a plain on-air
    drop with nothing better to show is a health condition, not a desync)."""
    return (not live_serving) and off_serving


def desync_settled(raw, since_ts, now, settle_s):
    """Debounce the raw desync condition: it becomes ACTIVE only after it has held
    for *settle_s* seconds (so a quick reconnect blip never raises it). Returns
    (active, since_ts): the running start-timestamp is preserved across ticks while
    raw holds and cleared to None as soon as it ends. Pure."""
    if not raw:
        return False, None
    if since_ts is None:
        since_ts = now
    return (now - since_ts) >= settle_s, since_ts
```

In `Relay.__init__` (near `self.health_level = None`, ~line 5298) add:

```python
        self._desync_since = None   # monotonic-ish start ts of the raw desync condition
        self._desync = {"active": False}   # the /status desync block (recomputed each tick)
        self._desync_active = False        # last active state, for the log-on-transition
```

Add these two methods to `Relay` (place them right after `live_after_next`, ~line 5641):

```python
    def _feed_serving(self, f):
        """A feed is 'delivering a stable picture' when its process is up and it is
        neither dropped nor paused. Used only for desync detection."""
        return f.is_serving() and not f.dropped and not f.paused

    def _compute_desync(self, now):
        """Recompute the panel-local desync flag (never mutates feeds/OBS). The
        index-designated on-air feed (live_feed) not delivering while the other is
        = a ping-pong desync; debounced by HEALTH_CONNECTING_SETTLE_S. Stores the
        /status block in self._desync and logs on the active transition."""
        live = self.live_feed()
        off = "B" if live == "A" else "A"
        raw = ping_pong_desynced(self._feed_serving(self.feeds[live]),
                                 self._feed_serving(self.feeds[off]))
        active, self._desync_since = desync_settled(
            raw, self._desync_since, now, HEALTH_CONNECTING_SETTLE_S)
        block = {"active": active}
        if active:
            block["since_s"] = round(now - self._desync_since, 1)
            block["serving_feed"] = off
            block["suggested_stint"] = self.feeds[off].idx + 1
        if active and not self._desync_active:
            LOG.warning("ping-pong desync: on-air feed %s not delivering while %s "
                        "serves stint %d — resync suggested", live, off,
                        self.feeds[off].idx + 1)
        elif not active and self._desync_active:
            LOG.info("ping-pong desync cleared")
        self._desync_active = active
        self._desync = block
        return block
```

In `_refresh_health(self, now)` (~line 5387), add a call so both the heartbeat and the `/status` 2 s refresh keep it fresh — insert right before `return h`:

```python
        self._compute_desync(now)
```

In `status()`, add `out["desync"] = self._desync` on the line immediately **after** the existing `out["health"] = {...}` assignment (which follows the `self._refresh_health(now)` call at ~line 5607, so `self._desync` is freshly recomputed before it is read):

```python
        out["desync"] = self._desync
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_pov.py`
Expected: PASS (all `t_*`).

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): debounced ping-pong desync detection + /status field (#494)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Recovery — feed-agnostic `resync_to_stint` + `/resync/stint/<n>` endpoint + policy

**Files:**
- Modify: `src/relay/racecast-feeds.py` — add `Relay.resync_to_stint(self, stint)` (after `set_stint`, ~line 5960); add the `GET /resync/stint/<n>` dispatch (next to the `set/stint` dispatch, ~line 7494).
- Modify: `src/scripts/console_policy.py` — map `["resync","stint",n]` to `Requirement(DIRECTOR, False)` (~line 60, in the director block).
- Test: `tests/test_pov.py` (the method), `tests/test_console.py` (the policy mapping).

**Interfaces:**
- Consumes: `pull_slots`, `next_slot_first_row`, `dedupe_pull_index` (existing); `set_stint` (fallback).
- Produces: `Relay.resync_to_stint(stint) -> status_dict`; route `GET /resync/stint/<n>`; policy `min_capability(["resync","stint",n]) == Requirement(DIRECTOR, False)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pov.py`:

```python
def t_resync_to_stint_keeps_serving_feed_no_cut():
    # Slot-parity desync: stint 3 legitimately runs on Feed B (idx2), Feed A is the
    # dropped ex-on-air feed stuck at a low idx (idx0). set_stint(3) would be
    # A-centric and cut B; resync must keep B on air and move A.
    rows = [("uA", "A", "S1", 1), ("uB", "B", "S2", 2),
            ("uC", "C", "S3", 3), ("uD", "D", "S4", 4)]
    r = m.Relay(_StubSource(["uA", "uB", "uC", "uD"], rows), (53001, 53002), LOGDIR)
    r._reflect = lambda live, cut: None
    r.A.set_index(0); r.B.set_index(2)             # A idx0 (dropped), B idx2 serving uC
    for f in r.feeds.values(): f.phase = "serving"
    r.A.dropped = True
    b_idx_before = r.B.idx
    b_proc_before = r.B.proc                        # anchor's process must be untouched
    res = r.resync_to_stint(3)
    assert r.B.idx == b_idx_before                  # anchor (B) NOT moved -> no cut
    assert r.B.proc is b_proc_before
    assert r.on_air_row_idx() == 2                  # display stint 3
    assert r.live_feed() == "B"                     # B is now the lower-or-equal? -> serving anchor
    assert r.A.idx > r.B.idx                        # A moved forward off the low idx
    assert r.A.current_channel()[0] != "uC"         # A not duplicating B's stream

def t_resync_to_stint_falls_back_when_no_feed_serves():
    # No feed serves stint 4's URL -> deliberate re-point via set_stint.
    rows = [("uA", "A", "S1", 1), ("uB", "B", "S2", 2),
            ("uC", "C", "S3", 3), ("uD", "D", "S4", 4)]
    r = m.Relay(_StubSource(["uA", "uB", "uC", "uD"], rows), (53001, 53002), LOGDIR)
    r._reflect = lambda live, cut: None
    r.A.set_index(0); r.B.set_index(1)
    for f in r.feeds.values(): f.phase = "idle"     # nothing serving uD
    r.resync_to_stint(4)
    # set_stint fallback: A on slot head of stint 4 (row3), display stint 4.
    assert r.on_air_row_idx() == 3
    assert r.A.idx == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_pov.py`
Expected: FAIL — `AttributeError: 'Relay' object has no attribute 'resync_to_stint'`.

- [ ] **Step 3: Write minimal implementation**

Add to `Relay`, immediately after `set_stint` (~line 5960):

```python
    def resync_to_stint(self, stint):
        """Feed-agnostic desync recovery: reconcile 'stint <N> is on air NOW' onto
        whichever feed is ACTUALLY serving it, preserving the live picture. Finds
        the feed whose current URL == stint N's row URL and keeps it on air (A OR
        B), sets on_air_row, and moves the OTHER feed to the next distinct slot
        (#491-safe). Non-destructive: the anchor feed is never re-indexed, and
        Feed.set_index no-ops (no kill) when a feed is already at its target. Falls
        back to set_stint (a deliberate re-point + cut) only when NO feed serves N."""
        self.source.refresh(timeout=6)
        rows = self.source.get_rows()
        n = len(rows)
        target = min(max(1, int(stint)) - 1, max(0, n - 1)) if n else 0
        target_url = (rows[target][0] or "").strip() if n else ""
        anchor = None
        if target_url:
            for k in ("A", "B"):
                ch, _ = self.feeds[k].current_channel()
                if (ch or "").strip() == target_url and self.feeds[k].is_serving():
                    anchor = k
                    break
        if anchor is None:
            LOG.info("resync_to_stint -> stint %d not served by any feed; "
                     "falling back to set_stint (re-point)", target + 1)
            return self.set_stint(stint)
        other = "B" if anchor == "A" else "A"
        slots = pull_slots(rows)
        off_idx, _redir = dedupe_pull_index(
            next_slot_first_row(slots, target), self.feeds[anchor].idx, rows)
        self.feeds[other].set_index(off_idx)   # no kill if already there
        self.on_air_row = target
        LOG.info("resync_to_stint -> stint %d anchored on serving feed %s (no cut); "
                 "feed %s -> slot %d", target + 1, anchor, other, off_idx + 1)
        self._reflect(anchor, cut=False)
        return self.status()
```

Add the endpoint dispatch in `do_GET`, right before the `if len(p)==3 and p[:2]==["set","stint"]:` block (~line 7494):

```python
                if len(p)==3 and p[:2]==["resync","stint"]:
                    res = relay.resync_to_stint(int(p[2]))
                    # Puts a stint on air -> same HUD auto-write as /set/stint.
                    if setup_ctl:
                        _push_live_schedule(relay, setup_ctl)
                    return self._send(res)
```

In `src/scripts/console_policy.py`, add to the director block (after the `set` A|B line, ~line 76):

```python
    if len(p) == 3 and p[:2] == ["resync", "stint"]:   # in-session director recovery
        return Requirement(DIRECTOR, False)
```

- [ ] **Step 4: Add the policy test, then run both test files**

Append to `tests/test_console.py` a check mirroring the existing `min_capability` tests (find how the file imports the module — it loads `console_policy`; match the local style):

```python
def t_resync_stint_is_director_no_stepup():
    req = cp.min_capability(["resync", "stint", "4"], "GET")
    assert req == cp.Requirement(cp.DIRECTOR, False)
```

(Use whatever alias `tests/test_console.py` already binds `console_policy` to — check the top of the file; it may be `cp` or `console_policy`. Match it.)

Run: `python3 tests/test_pov.py`
Expected: PASS.
Run: `python3 tests/test_console.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py src/scripts/console_policy.py tests/test_pov.py tests/test_console.py
git commit -m "feat(relay): feed-agnostic resync_to_stint + /resync/stint endpoint (#494)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Director Panel — desync banner with a one-click Resync button

**Files:**
- Modify: `src/director/director-panel.html` — extend the banner model/renderer to carry an optional action (~lines 876-887); add a `desync` banner block in the `/status` poll after the `feeddown` block (~line 1453); add a `resyncTo(n)` helper near the other `relayCall` uses.
- Test: none (UI); verified by the task reviewer reading the diff + the controller visual verify in Task 5.

**Interfaces:**
- Consumes: `d.desync` from `/status` (Task 1): `{active, since_s, serving_feed, suggested_stint}`; the `/resync/stint/<n>` route (Task 2); existing `setBanner`/`clearBanner`/`renderBanners`, `relayCall`, `escapeHtml`.

- [ ] **Step 1: Extend the banner model + renderer for an optional action**

Replace the banner block (`src/director/director-panel.html` ~lines 876-887) with:

```javascript
const banners = {};   // id -> {level: "red"|"amber", msg, action?: {label, fn}}
function setBanner(id, level, msg, action){
  const prev = banners[id];
  if (prev && prev.msg === msg && prev.level === level && !!prev.action === !!action) return;
  banners[id] = {level, msg, action}; renderBanners();
}
function clearBanner(id){
  if (banners[id]){ delete banners[id]; renderBanners(); }
}
const _bannerActions = {};   // id -> fn, bound at render so onclick can find it
function renderBanners(){
  const el = $("#banners");
  el.innerHTML = Object.entries(banners).map(([id, b]) => {
    const btn = b.action
      ? ` <button class="bannerbtn" onclick="_runBannerAction('${id}')">${escapeHtml(b.action.label)}</button>`
      : "";
    return `<div class="banner ${b.level}">⚠ ${escapeHtml(b.msg)}${btn}</div>`;
  }).join("");
  for (const [id, b] of Object.entries(banners)) _bannerActions[id] = b.action ? b.action.fn : null;
}
function _runBannerAction(id){ const fn = _bannerActions[id]; if (fn) fn(); }
```

Add a minimal button style next to the `.banner` CSS (~line 268):

```css
  .bannerbtn{margin-left:10px;padding:3px 10px;border-radius:6px;border:1px solid currentColor;
             background:transparent;color:inherit;font-weight:700;cursor:pointer;font-size:12px}
```

- [ ] **Step 2: Add the desync banner + resyncTo in the `/status` poll**

Right after the `feeddown` banner block (`else clearBanner("feeddown");`, ~line 1453) insert:

```javascript
    if (d.desync && d.desync.active) {
      const n = d.desync.suggested_stint;
      setBanner("desync", "red",
        "PING-PONG DESYNC — the on-air feed is not delivering while Feed " +
        d.desync.serving_feed + " serves stint " + n + " · Resync to fix the panel/cockpit",
        {label: "Resync to stint " + n, fn: () => resyncTo(n)});
    }
    else clearBanner("desync");
```

Add a `resyncTo` helper near the existing takeover control (the `set/stint` prompt, ~line 947):

```javascript
async function resyncTo(n){
  if (!confirm("Resync: make stint " + n + " on air on the feed actually serving it? " +
               "(No cut if that feed is already on air.)")) return;
  await relayCall("resync/stint/" + n);
}
```

- [ ] **Step 3: Sanity-check the markup**

Run: `python3 -c "import pathlib; s=pathlib.Path('src/director/director-panel.html').read_text(); assert 'resync/stint/' in s and 'PING-PONG DESYNC' in s and '_runBannerAction' in s; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add src/director/director-panel.html
git commit -m "feat(panel): ping-pong desync banner with one-click Resync (#494)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Cockpit — graceful "syncing…" during a desync

**Files:**
- Modify: `src/relay/racecast-feeds.py` — add a pure `cockpit_syncing(desync)` helper near `cockpit_schedule` (~line 3820) and use it to add a top-level `"syncing"` key to the `/cockpit/data` payload (~line 7282, the `tally.update({...})` block).
- Modify: `src/cockpit/cockpit.html` — short-circuit the tally render to "syncing…" when `d.syncing` (~lines 394-421).
- Test: `tests/test_cockpit.py` (the pure `cockpit_syncing` helper).

**Interfaces:**
- Consumes: `self._desync` (Task 1) inside the `/cockpit/data` handler.
- Produces: `cockpit_syncing(desync) -> bool`; `/cockpit/data` payload gains `"syncing": bool`; the cockpit renders "syncing…" when true.

Note: `/cockpit/data` is auth-gated (404s without a console secret + token), so an HTTP round-trip test is disproportionate for a one-line flag. The decision is extracted to the pure `cockpit_syncing` helper (matching the repo's pure-helper pattern for `cockpit_tally`/`cockpit_schedule`) and unit-tested directly; `relay._desync["active"]` itself is already covered by Task 1's status test.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cockpit.py` (it loads the relay module as `m` and unit-tests pure helpers like `m.cockpit_tally` directly — same style here):

```python
def t_cockpit_syncing_pure():
    assert m.cockpit_syncing({"active": True, "serving_feed": "B"}) is True
    assert m.cockpit_syncing({"active": False}) is False
    assert m.cockpit_syncing({}) is False       # missing key -> not syncing
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL — `AttributeError: module '...' has no attribute 'cockpit_syncing'`.

- [ ] **Step 3: Add the pure helper + wire it into `/cockpit/data`**

In `src/relay/racecast-feeds.py`, add after `cockpit_schedule` (~line 3820):

```python
def cockpit_syncing(desync):
    """True when the relay's desync block is active — the cockpit should show
    'syncing…' instead of the (index-derived, possibly wrong) ON-AIR tally. Pure."""
    return bool(desync.get("active"))
```

Then in the `p == ["cockpit", "data"]` handler's `tally.update({...})` (~line 7282), add one key:

```python
                                      "syncing": cockpit_syncing(relay._desync),
```

- [ ] **Step 4: Degrade the cockpit tally render**

In `src/cockpit/cockpit.html`, at the top of the tally render (right after `const el = $('tally');`, ~line 394), insert a short-circuit before the `if (d.on_air)`:

```javascript
  if (d.syncing) {
    el.className = 'tally idle';
    el.textContent = 'syncing…';
  } else if (d.on_air) {
```

(Change the existing `if (d.on_air) {` on the next line to `} else if (d.on_air) {`? No — instead make the inserted block the leading branch and leave the existing chain intact by converting the first `if` to `else if`.) Concretely, replace:

```javascript
  const el = $('tally');
  if (d.on_air) {
```

with:

```javascript
  const el = $('tally');
  if (d.syncing) {
    el.className = 'tally idle';
    el.textContent = 'syncing…';
  } else if (d.on_air) {
```

- [ ] **Step 5: Run the test + a markup sanity check**

Run: `python3 tests/test_cockpit.py`
Expected: PASS.
Run: `python3 -c "import pathlib; s=pathlib.Path('src/cockpit/cockpit.html').read_text(); assert 'syncing…' in s and 'd.syncing' in s; print('ok')"`
Expected: `ok`.

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py src/cockpit/cockpit.html tests/test_cockpit.py
git commit -m "feat(cockpit): degrade to 'syncing...' during a ping-pong desync (#494)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Full suite + lint + visual verify + wiki screenshots

**Files:**
- Modify: `src/docs/wiki/images/director-panel.png` (banner visible), the cockpit wiki image ("syncing…").
- No code changes (verification + docs images).

**Interfaces:** none (final gate).

- [ ] **Step 1: Full suite + lint**

Run: `python3 tools/run-tests.py`
Expected: all test files pass (exit 0).
Run: `python3 tools/lint.py`
Expected: `All checks passed`.

- [ ] **Step 2: Visual verify + capture the two wiki screenshots (CONTROLLER task)**

This step is performed by the controller, not a code subagent. Use the **`wiki-screenshots`** skill against a local dev build (run `racecast ui` / the relay from `src/`, no `VERSION` stamped), with the `demo` profile + `tools/obs-sim.py` recipe. Force a desync state so the surfaces show the new UI:
- **Director Panel:** drive `/status` to a desync (e.g. a stubbed `desync.active` state, or the obs-sim recipe with the on-air feed dropped while the other serves) → capture the red **PING-PONG DESYNC** banner with the Resync button → save `src/docs/wiki/images/director-panel.png`.
- **Cockpit:** with `syncing:true` on `/cockpit/data` → capture the **"syncing…"** tally → save the cockpit image.
Follow the `ui-visual-verification` gate (render + eyeball) before declaring done. Present the renders to Jens for design approval (Artifact) — this is a visual surface, do not self-approve.

- [ ] **Step 3: Commit the images**

```bash
git add src/docs/wiki/images/director-panel.png src/docs/wiki/images/*cockpit*.png
git commit -m "docs(wiki): refresh panel + cockpit shots for the desync banner/syncing state (#494)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Pure detection predicate → Task 1 (`ping_pong_desynced`).
- Debounced heartbeat flag, no mutation, `/status` field (not health_level, no Discord) → Task 1 (`desync_settled`, `_compute_desync`, `out["desync"]`).
- `live_feed()` unchanged → enforced (Task 1 adds a separate path; Global Constraints).
- Graceful cockpit "syncing…" → Task 4. **Deviation from spec §3:** the spec suggested threading a `desynced` param through `cockpit_tally`/`cockpit_schedule`; the plan instead adds a top-level `syncing` flag to `/cockpit/data` and short-circuits the front-end. This keeps the two pure helpers pure and is a cleaner realization of the same AC ("degrades to syncing… instead of wrong data"). Behaviour is identical to the user-facing requirement.
- Director Panel banner + one-click Resync → Task 3.
- Feed-agnostic non-destructive `resync_to_stint` + `/resync/stint` + policy (director-tier) → Task 2.
- Tests for predicate + resync + policy + cockpit field → Tasks 1/2/4.
- Wiki screenshots refreshed → Task 5.

**Placeholder scan:** none. Task 2 Step 4 references `tests/test_console.py`'s existing `cp` alias (confirmed: `cp = _load("console_policy", …)`); Task 4 uses `m` (confirmed: `m = _load("irofeeds", …)`). All test/impl code is concrete.

**Type consistency:** `ping_pong_desynced(live_serving, off_serving) -> bool` and `desync_settled(raw, since_ts, now, settle_s) -> (bool, float|None)` are used consistently. `self._desync` is a dict with `active`/`since_s`/`serving_feed`/`suggested_stint`, read the same way in `status()`, `/cockpit/data`, and the panel (`d.desync.*`). `resync_to_stint(stint) -> status_dict`. Endpoint `resync/stint/<n>` matches the policy segments `["resync","stint",n]`.
