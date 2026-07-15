# Auto-stop the freed feed on `/next` handover — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On a `/next` handover that actually cuts to the incoming feed, automatically stop (disarm) the outgoing feed, and make manual-arm the default so the arm-before-handover workflow is out-of-box.

**Architecture:** A gated one-block addition to `Relay.next_auto`'s real-handover branch (stop the freed feed only when `cut` happened and manual-arm is active), plus flipping `manual_feed_arm_enabled` to default-ON. No new pull machinery — reuses the existing per-feed `paused` gate + `reload()` (the POV/`feed_deactivate` stop primitive).

**Tech Stack:** Pure Python 3 stdlib. Tests are runnable scripts under `tests/` (no pytest); the full suite is `python3 tools/run-tests.py`.

## Global Constraints

- Edit only under `src/` (+ `tests/`, `docs/`, `.env.example`). Never touch `dist/`/`runtime/`.
- The auto-stop MUST be gated on `cut == True` — pressing `/next` before the incoming feed is armed/serving must cut nothing and stop nothing (never black out the live program).
- The auto-stop is gated on `self.manual_feed_arm` so the explicit legacy opt-out (`RACECAST_MANUAL_FEED_ARM=0`) keeps its seamless whole-stint pre-roll intact (a coherent, backward-compatible opt-out — not a broken mode).
- `manual_feed_arm_enabled` default flips OFF→ON, mirroring the existing `program_audio_enabled` FALSEY-set pattern (`{"0","false","no","off"}`); empty/absent ⇒ ON.
- Stop the outgoing feed with the internal primitive (`feed.paused = True; feed.reload()`), NOT the HTTP helper `feed_deactivate()` (which is manual-mode-gated and returns a status/error dict).
- Design doc: `docs/superpowers/specs/2026-07-15-freed-feed-autostop-on-handover-design.md`.

---

### Task 1: Flip `manual_feed_arm_enabled` to default-ON (+ `.env.example` + test compat)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`manual_feed_arm_enabled`, ~line 410-415; add a FALSEY set near the existing `_PROGRAM_AUDIO_FALSEY` at line 419)
- Modify: `.env.example` (add the opt-out knob)
- Test: `tests/test_pov.py` (module-level env guard; rewrite `t_manual_feed_arm_enabled` @1397 and `t_relay_manual_arm_starts_feeds_disarmed` @1409)

**Interfaces:**
- Produces: `manual_feed_arm_enabled(environ) -> bool` now returns `True` unless the value is an explicit falsey token. `Relay.__init__` already calls it and starts A/B `paused=True` when it is truthy — unchanged wiring, flipped default.

- [ ] **Step 1: Update the default-value unit test to the new semantics (write the failing test first)**

In `tests/test_pov.py`, replace the body of `t_manual_feed_arm_enabled` (line ~1397):

```python
def t_manual_feed_arm_enabled():
    # Default-ON now: absent/empty ⇒ manual arm on.
    assert m.manual_feed_arm_enabled({}) is True
    assert m.manual_feed_arm_enabled({"RACECAST_MANUAL_FEED_ARM": ""}) is True
    for v in ("1", "true", "yes", "on", "TRUE", "On"):
        assert m.manual_feed_arm_enabled({"RACECAST_MANUAL_FEED_ARM": v}) is True, v
    for v in ("0", "false", "no", "off", "OFF", "No"):
        assert m.manual_feed_arm_enabled({"RACECAST_MANUAL_FEED_ARM": v}) is False, v
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_manual_feed_arm_enabled()"`
Expected: `AssertionError` (current impl returns False for `{}`).

- [ ] **Step 3: Flip the default in the source**

In `src/relay/racecast-feeds.py`, near line 419 (beside `_PROGRAM_AUDIO_FALSEY`) add:

```python
_MANUAL_FEED_ARM_FALSEY = {"0", "false", "no", "off"}
```

Replace `manual_feed_arm_enabled` (line ~410-415) with:

```python
def manual_feed_arm_enabled(environ):
    """True unless RACECAST_MANUAL_FEED_ARM is an explicit falsey token. Default ON:
    feed URLs are entered into the schedule but do NOT pull until the director arms
    the feed, and `/next` auto-stops the outgoing feed after a handover cut — the
    durable single-puller workflow (#489/#505). Set RACECAST_MANUAL_FEED_ARM=0 to
    restore the legacy auto-pull + seamless whole-stint pre-roll. Pure so the switch
    is unit-testable."""
    return str(environ.get("RACECAST_MANUAL_FEED_ARM", "")).strip().lower() not in _MANUAL_FEED_ARM_FALSEY
```

- [ ] **Step 4: Run the unit test to confirm it passes**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_manual_feed_arm_enabled()"`
Expected: no output (pass).

- [ ] **Step 5: Add a module-level test guard so legacy auto-pull tests stay green**

Many `tests/test_pov.py` tests assert auto-pull via `current_channel()` (e.g. `t_cold_start_one_link_then_add_second`, the qualifying tests, the #491 dedup tests). With the default flipped, a bare `m.Relay(...)` would now start feeds `paused`, breaking them. Pin the file to the legacy path by default; individual tests opt into manual mode explicitly.

At the top of `tests/test_pov.py`, immediately after the existing `import os` (and before the first `m.Relay` use), add:

```python
# Default flipped to manual-arm ON (#492 follow-up). These relay tests exercise the
# legacy auto-pull machinery (index/dedup/qualifying); pin them to the opt-out path so
# they stay focused. Tests that need manual mode set r.manual_feed_arm/paused explicitly.
os.environ.setdefault("RACECAST_MANUAL_FEED_ARM", "0")
```

- [ ] **Step 6: Rewrite `t_relay_manual_arm_starts_feeds_disarmed` for the new default (write, then run)**

Replace `t_relay_manual_arm_starts_feeds_disarmed` (line ~1409) with a version that controls the env explicitly (the module guard sets "0", so the "absent" case must pop it):

```python
def t_relay_manual_arm_starts_feeds_disarmed():
    rows = [("uA", "A", "S1", 1), ("uB", "B", "S2", 2)]
    # Opt-out (flag "0"): legacy auto-pull, feeds armed.
    os.environ["RACECAST_MANUAL_FEED_ARM"] = "0"
    try:
        r0 = m.Relay(_StubSource(["uA", "uB"], rows), (53001, 53002), LOGDIR)
    finally:
        del os.environ["RACECAST_MANUAL_FEED_ARM"]
    assert r0.manual_feed_arm is False
    assert r0.A.paused is False and r0.B.paused is False
    assert r0.status()["feeds"]["A"]["armed"] is True
    # New DEFAULT (flag absent): manual arm on, feeds disarmed.
    saved = os.environ.pop("RACECAST_MANUAL_FEED_ARM", None)
    try:
        rd = m.Relay(_StubSource(["uA", "uB"], rows), (53005, 53006), LOGDIR)
    finally:
        if saved is not None:
            os.environ["RACECAST_MANUAL_FEED_ARM"] = saved
    assert rd.manual_feed_arm is True
    assert rd.A.paused is True and rd.B.paused is True
    assert rd.status()["manual_feed_arm"] is True
    assert rd.status()["feeds"]["A"]["armed"] is False
    # Explicit "1": same as default (disarmed).
    os.environ["RACECAST_MANUAL_FEED_ARM"] = "1"
    try:
        r2 = m.Relay(_StubSource(["uA", "uB"], rows), (53003, 53004), LOGDIR)
    finally:
        del os.environ["RACECAST_MANUAL_FEED_ARM"]
    assert r2.manual_feed_arm is True and r2.A.paused is True
```

- [ ] **Step 7: Add the opt-out to `.env.example`**

Append to `.env.example` (near other `RACECAST_*` machine knobs):

```
# Two-stage feed arming (#492). Default ON: a stint URL in the schedule does NOT pull
# until the feed is armed in the Director Panel, and /next auto-stops the outgoing feed
# after a handover. Set to 0 to restore the legacy auto-pull + seamless whole-stint
# pre-roll (only advisable on a residential IP, where concurrent-pull throttling is a non-issue).
RACECAST_MANUAL_FEED_ARM=1
```

- [ ] **Step 8: Run the whole relay test file (regression guard for the default flip)**

Run: `python3 tests/test_pov.py`
Expected: exits 0. If any auto-pull test regresses, it is a missed spot needing the legacy pin — do NOT weaken an assertion; ensure the guard (Step 5) is placed before the first relay construction.

- [ ] **Step 9: Commit**

```bash
git add src/relay/racecast-feeds.py .env.example tests/test_pov.py
git commit -m "feat(relay): default manual feed arm ON (#492 follow-up)"
```

---

### Task 2: Auto-stop the freed feed in `next_auto` on a real handover cut

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`Relay.next_auto`, real-handover branch, lines ~6531-6549)
- Test: `tests/test_pov.py` (4 new tests near the existing next_auto tests ~line 242-275)

**Interfaces:**
- Consumes: `self.manual_feed_arm` (bool), `self.feeds[freed]` (a `Feed` with `.paused`, `.reload()`, `.idx`, `.phase`), the local `cut`/`freed`/`slots`/`nxt` already computed in the branch.
- Produces: after a handover with `cut=True` in manual mode, `self.feeds[freed].paused == True` and its pull process is killed (port freed). Return dict of `next_auto` is unchanged.

- [ ] **Step 1: Write the failing tests (add after `t_next_reflects_only_when_incoming_serving`, ~line 276)**

```python
def t_next_auto_stops_freed_feed_on_cut():
    r = _relay(["s1", "s2", "s3", "s4"])
    r.manual_feed_arm = True
    r.feeds["A"].phase = "serving"      # outgoing serving
    r.feeds["B"].phase = "serving"      # incoming armed + serving -> cut
    r.A.paused = False; r.B.paused = False
    out = r.next_auto()                 # live_after_next=B, freed=A
    assert out["obs_cut"] is True
    assert r.A.paused is True           # freed feed auto-stopped
    assert r.B.paused is False          # incoming stays live/armed


def t_next_auto_keeps_freed_when_no_cut():
    r = _relay(["s1", "s2", "s3", "s4"])
    r.manual_feed_arm = True
    r.feeds["A"].phase = "serving"      # outgoing serving (still on air)
    r.feeds["B"].phase = "idle"         # incoming NOT serving -> no cut
    r.A.paused = False; r.B.paused = False
    out = r.next_auto()
    assert out["obs_cut"] is False
    assert r.A.paused is False          # freed NOT stopped -> live picture preserved


def t_next_auto_freed_disarmed_at_next_slot():
    r = _relay(["s1", "s2", "s3", "s4"])
    r.manual_feed_arm = True
    r.feeds["A"].phase = "serving"; r.feeds["B"].phase = "serving"
    r.A.paused = False; r.B.paused = False
    r.next_auto()                       # cut to B; freed A re-indexed to stint3 (idx2) + stopped
    assert r.A.idx == 2 and r.A.paused is True


def t_next_auto_legacy_no_autostop():
    r = _relay(["s1", "s2", "s3", "s4"])
    r.manual_feed_arm = False           # legacy auto pre-roll opt-out
    r.feeds["A"].phase = "serving"; r.feeds["B"].phase = "serving"
    r.A.paused = False; r.B.paused = False
    r.next_auto()
    assert r.A.paused is False          # legacy: freed keeps pre-rolling, no auto-stop
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_next_auto_stops_freed_feed_on_cut()"`
Expected: `AssertionError` on `r.A.paused is True` (no auto-stop yet).
(Confirm `t_next_auto_keeps_freed_when_no_cut` and `t_next_auto_legacy_no_autostop` already pass — they assert the un-changed no-stop behaviour — and `t_next_auto_freed_disarmed_at_next_slot` fails on `paused`.)

- [ ] **Step 3: Add the gated auto-stop to `next_auto`**

In `src/relay/racecast-feeds.py`, real-handover branch, right after the freed feed is re-indexed (`self.feeds[freed].set_index(next_slot_first_row(slots, nxt))`, ~line 6542) and before `self.on_air_row = nxt`:

```python
        self.feeds[freed].set_index(next_slot_first_row(slots, nxt))
        # #489/#505: on a real handover cut, stop the outgoing pull so only ONE feed
        # ever pulls googlevideo between handovers (the durable single-puller fix). Gated
        # on cut (never stop a feed we did not cut away from -> never blacks the program)
        # and on manual arm (the legacy opt-out keeps its whole-stint pre-warm).
        if cut and self.manual_feed_arm:
            self.feeds[freed].paused = True
            self.feeds[freed].reload()          # wake + kill proc -> loopback port closes
            LOG.info("handover -> freed feed %s auto-stopped after cut", freed)
        self.on_air_row = nxt
```

- [ ] **Step 4: Run the four new tests to confirm they pass**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; [getattr(t,n)() for n in ('t_next_auto_stops_freed_feed_on_cut','t_next_auto_keeps_freed_when_no_cut','t_next_auto_freed_disarmed_at_next_slot','t_next_auto_legacy_no_autostop')]"
```
Expected: no output (all pass).

- [ ] **Step 5: Run the full relay test file (no regression in handover/index logic)**

Run: `python3 tests/test_pov.py`
Expected: exits 0.

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): /next auto-stops the freed feed after a handover cut (#489)"
```

---

### Task 3: Director Panel hint + visual verification + wiki screenshot

**Files:**
- Modify: `src/director/director-panel.html` (near the ARM/STOP buttons, lines ~512-515)
- Regenerate: `src/docs/wiki/images/director-panel.png`

**Interfaces:** none (front-end copy only).

- [ ] **Step 1: Add the auto-stop hint next to the arm controls**

In `src/director/director-panel.html`, after the arm-button row (the block containing `ARM A`/`STOP A`/`ARM B`/`STOP B`, ~line 512-515), add a small hint line styled with an existing muted/hint class (match a sibling `.hint`/muted style already in the file — do not invent a new color):

```html
<div class="hint">Arm the incoming feed before the handover. <code>/next</code> stops the outgoing feed automatically.</div>
```

Use whatever muted-hint class the panel already defines for such notes; if none exists, reuse the CSS variable palette (`--mut`/`--edge`) consistent with the surrounding controls — no new hard-coded colors.

- [ ] **Step 2: Visually verify the change (REQUIRED — ui-visual-verification skill)**

Invoke the **ui-visual-verification** skill: boot the demo relay + obs-sim, open `/panel`, take an **element** screenshot of the arm-controls row, `Read` it back, and confirm the hint reads correctly, uses the panel theme (no default/unstyled text), and is aligned with the buttons. Fix and re-shoot if off. Then record the marker:

```bash
python3 .claude/hooks/record_ui_verified.py src/director/director-panel.html
```

- [ ] **Step 3: Refresh the committed wiki screenshot (REQUIRED — wiki-screenshots skill)**

The arm/stop controls now render by default (manual-arm default-on), so `director-panel.png` is stale. Invoke the **wiki-screenshots** skill (demo profile + obs-sim, dev build) to recapture `src/docs/wiki/images/director-panel.png` at the same framing as the existing image.

- [ ] **Step 4: Clean up the demo build**

`racecast relay stop`; `pkill -f obs-sim.py`; remove the stub `runtime/yt-cookies.txt`; `git checkout -- profiles/demo/profile.env` (the auto-provisioned `CONSOLE_SECRET`). Delete any scratch PNGs from the repo root.

- [ ] **Step 5: Commit**

```bash
git add src/director/director-panel.html src/docs/wiki/images/director-panel.png
git commit -m "docs(panel): note /next auto-stops the outgoing feed; refresh panel screenshot"
```

---

## Final verification

- [ ] Run the whole suite exactly as CI does: `python3 tools/run-tests.py`
- [ ] Lint: `python3 tools/lint.py`
- [ ] Build self-verify (closest to CI ship gate): `python3 tools/build.py`

## Self-review notes

- Spec coverage: default flip (Task 1) ✓, auto-stop gated on cut + manual arm (Task 2) ✓, panel hint + screenshot (Task 3) ✓, `.env.example`/opt-out docs (Task 1 Step 7) ✓, safety gate `cut=True` (Task 2 test `t_next_auto_keeps_freed_when_no_cut`) ✓, legacy opt-out unbroken (Task 2 test `t_next_auto_legacy_no_autostop`) ✓.
- No placeholders: every code/test block is complete.
- Type consistency: `manual_feed_arm_enabled` bool; `Feed.paused`/`.reload()`/`.idx`/`.phase` used exactly as the existing POV/`feed_deactivate` code and the `_relay`/phase test conventions use them.
