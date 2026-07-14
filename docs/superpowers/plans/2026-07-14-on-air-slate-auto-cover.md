# On-Air Slate — Auto-Cover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-raise the existing #378 **Standby Cover** over the on-air picture when the on-air feed's classified `source_state` (#502) says the source is offline/ended, and lower it on confirmed-live recovery — keeping the HUD — so the broadcast shows an intentional slate instead of black.

**Architecture:** A pure decision function (`auto_cover_action`) plus a lightweight relay daemon tick (`_auto_cover_loop` → `_maybe_auto_cover`, ~5 s) that reads the on-air feed's `source_state`/`offline_since`, and — only when a raise or lower could be pending — reads OBS (program scene + cover visibility) and toggles the `Standby Cover` source in the `Stint` scene via the same best-effort obs-ws path the manual RED FLAG button uses. Fire-once-per-outage + ownership flags mean it never fights the director. It is the gentler rung below the existing opt-in Intermission auto-failover.

**Tech Stack:** Python 3 stdlib only. Existing relay (`src/relay/racecast-feeds.py`), `src/scripts/obs_ws.py` (`read_obs_state`, `set_scene_item_enabled`, `STINT_SCENE`), the Director Panel HTML, `tests/test_pov.py`.

## Global Constraints

- **Edit only under `src/`** (+ `tests/`, `docs/`, `.env.example`). `dist/`/`runtime/` are generated. **English only. Python stdlib only.**
- **Backward compatible.** New flag `RACECAST_OBS_AUTO_COVER` is **default-ON, opt-out** (a falsey token `0/false/no/off` disables **only the automatic** raise/lower; the manual RED FLAG / Companion toggle is unaffected). Mirror the `fanout_enabled` / `program_audio_enabled` opt-out idiom (`... not in _AUTO_COVER_FALSEY`).
- **Reuse, do not duplicate.** Cover source is the existing `Standby Cover` in the `Stint` scene (#378). Toggle via `_obs_ws.set_scene_item_enabled(scene, source, enabled)`; read state via `_obs_ws.read_obs_state([(scene, source)], [])`. Scene name via `getattr(_obs_ws, "STINT_SCENE", "Stint")` (as `_maybe_auto_failover` does).
- **Trigger:** on-air feed `source_state ∈ {"not_live_yet", "ended"}`, persisted `≥ AUTO_COVER_SETTLE_S = 12` s (`AUTO_COVER_POLL_S = 5`). Constant source name `STANDBY_COVER_SOURCE = "Standby Cover"`.
- **State machine:** fire **once per outage** (`_cover_fired`); auto **lowers only a cover it owns** (`_cover_auto_owned`); **re-arm on recovery** (`source_state is None` → `_cover_fired = False`); **manual override always wins** (never auto-lower a manually-raised cover; no re-raise after a manual lower within one outage). Auto is **visibility-only** — it does **NOT** write a "Red Flag" HUD banner.
- **Best-effort OBS**, like `get_program_screenshot` / `_maybe_auto_failover`: `_obs_ws is None` or an unreachable OBS → set `self.obs_note`, return; **never raise into the loop**. A failed raise/lower is **not latched** (retries next tick) — flags advance only after a call that succeeded.
- **Non-goals (YAGNI):** generic drops with no classified `source_state` (incl. the #489 429 blackout — that's failover/#489 territory); a Splitscreen cover; audio muting; a new graphic; a configurable fallback *source* path.
- **UI change → same-change wiki image.** The one Director-Panel warnline means `src/docs/wiki/images/director-panel.png` (+ the slides copy if present) must be regenerated (wiki-screenshots skill) and the `ui-visual-verification` pre-flight look done, in Task 4.
- **After relay change:** `python3 tests/test_pov.py`. **Before finish:** `python3 tools/run-tests.py` (capture the REAL exit code — do **not** pipe through `tail`, which masks it), `python3 tools/lint.py`, `python3 tools/build.py`.
- **Commit trailer:** `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

**Test runner:** each `tests/*.py` is a runnable script (`python3 tests/test_pov.py`). Run ONE function: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_name()"`. In `tests/test_pov.py` the module under test is imported as **`m`**; a Relay is built with `_relay(items)` → `m.Relay(_StubSource(items), (53001, 53002), LOGDIR)`; a Feed with `m.Feed("A", 53001, 0, lambda: ["a"], LOGDIR)`.

---

### Task 1: Pure decision function + opt-out flag + constants

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add near the #378 auto-failover block, ~line 399–442)
- Test: `tests/test_pov.py`

**Interfaces:**
- Produces:
  - `AUTO_COVER_POLL_S = 5`, `AUTO_COVER_SETTLE_S = 12`, `STANDBY_COVER_SOURCE = "Standby Cover"`, `_AUTO_COVER_FALSEY = {"0", "false", "no", "off"}` (module constants).
  - `auto_cover_enabled(environ) -> bool` — default True; False only for a falsey token.
  - `auto_cover_action(enabled, source_state, offline_since, now, settle_s, cover_shown, auto_owned, cover_fired, program_scene, on_air_scene="Stint") -> "raise" | "lower" | None`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_pov.py`:

```python
def t_auto_cover_enabled_default_on_optout():
    assert m.auto_cover_enabled({}) is True
    assert m.auto_cover_enabled({"RACECAST_OBS_AUTO_COVER": "1"}) is True
    assert m.auto_cover_enabled({"RACECAST_OBS_AUTO_COVER": "0"}) is False
    assert m.auto_cover_enabled({"RACECAST_OBS_AUTO_COVER": "off"}) is False

def t_auto_cover_action_raises_on_offline_past_settle():
    # ended source, offline 20s (> settle 12), cover hidden, not fired, on Stint -> raise
    assert m.auto_cover_action(True, "ended", 100.0, 120.0, 12,
                               False, False, False, "Stint") == "raise"
    # not_live_yet raises identically
    assert m.auto_cover_action(True, "not_live_yet", 100.0, 120.0, 12,
                               False, False, False, "Stint") == "raise"

def t_auto_cover_action_waits_for_settle():
    # offline only 5s (< settle 12) -> no raise yet
    assert m.auto_cover_action(True, "ended", 100.0, 105.0, 12,
                               False, False, False, "Stint") is None

def t_auto_cover_action_fires_once_per_outage():
    # already fired this outage -> no re-raise (even though still offline & hidden)
    assert m.auto_cover_action(True, "ended", 100.0, 200.0, 12,
                               False, False, True, "Stint") is None

def t_auto_cover_action_skips_when_cover_already_shown():
    # a cover is already up (manual) -> pure fn does not raise
    assert m.auto_cover_action(True, "ended", 100.0, 200.0, 12,
                               True, False, False, "Stint") is None

def t_auto_cover_action_scene_guard():
    # OBS is on Intermission (not the on-air scene) -> never raise
    assert m.auto_cover_action(True, "ended", 100.0, 200.0, 12,
                               False, False, False, "Intermission") is None

def t_auto_cover_action_disabled_never_raises():
    assert m.auto_cover_action(False, "ended", 100.0, 200.0, 12,
                               False, False, False, "Stint") is None

def t_auto_cover_action_lowers_owned_cover_on_recovery():
    # source recovered (None), cover shown, auto owns it -> lower
    assert m.auto_cover_action(True, None, None, 300.0, 12,
                               True, True, True, "Stint") == "lower"

def t_auto_cover_action_lowers_even_when_disabled():
    # cleanup: flag flipped off mid-outage must not strand an auto-owned cover
    assert m.auto_cover_action(False, None, None, 300.0, 12,
                               True, True, True, "Stint") == "lower"

def t_auto_cover_action_never_lowers_manual_cover():
    # cover shown but auto does NOT own it (director raised it) -> no lower
    assert m.auto_cover_action(True, None, None, 300.0, 12,
                               True, False, False, "Stint") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_auto_cover_enabled_default_on_optout()"`
Expected: FAIL — `AttributeError: module ... has no attribute 'auto_cover_enabled'`.

- [ ] **Step 3: Implement** — in `src/relay/racecast-feeds.py`, directly after the `should_failover(...)` function (ends ~line 442), add:

```python
# ---------- Auto-cover: raise the Standby Cover on an offline on-air source (#495) ----
AUTO_COVER_POLL_S = 5            # how often the auto-cover tick evaluates the on-air feed
AUTO_COVER_SETTLE_S = 12        # source_state must persist this long before the cover raises
STANDBY_COVER_SOURCE = "Standby Cover"   # the #378 cover source in the Stint scene
_AUTO_COVER_FALSEY = {"0", "false", "no", "off"}


def auto_cover_enabled(environ):
    """True unless RACECAST_OBS_AUTO_COVER is an explicit falsey token. Default ON
    (opt-out): the automatic raise/lower is on; setting the flag falsey disables ONLY
    the automation (the manual RED FLAG / Companion toggle still works). Pure so the
    switch is unit-testable."""
    return str(environ.get("RACECAST_OBS_AUTO_COVER", "")).strip().lower() not in _AUTO_COVER_FALSEY


def auto_cover_action(enabled, source_state, offline_since, now, settle_s,
                      cover_shown, auto_owned, cover_fired,
                      program_scene, on_air_scene="Stint"):
    """Return "raise", "lower", or None for the auto-cover tick. Pure → unit-tested.
    - "lower": auto lowers ONLY a cover it owns, and only once the source recovered
      (source_state is None). Runs even when disabled so flipping the flag off
      mid-outage never strands an auto-raised cover.
    - "raise": once per outage, on-air source offline/ended past the settle, cover not
      already shown, and OBS still on the on-air scene.
    - None: everything else (manual covers are never auto-lowered; the manual button
      always works)."""
    if cover_shown and auto_owned and source_state is None:
        return "lower"
    if not enabled:
        return None
    if source_state in ("not_live_yet", "ended") and offline_since is not None \
            and (now - offline_since) >= settle_s \
            and not cover_shown and not cover_fired \
            and program_scene == on_air_scene:
        return "raise"
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_pov.py`
Expected: PASS (all `t_auto_cover_*` green, no regressions).

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): pure auto_cover_action + RACECAST_OBS_AUTO_COVER flag + constants (#495)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `Feed.offline_since` — stamp/clear beside `source_state`

**Files:**
- Modify: `src/relay/racecast-feeds.py` (Feed `__init__` ~5290; the four `self.source_state = …` assignment sites at ~5329, ~5337, ~5499, ~5559)
- Test: `tests/test_pov.py`

**Interfaces:**
- Consumes: `classify_source_state` (existing), `time.time()`.
- Produces:
  - `Feed.offline_since` attribute (float epoch when the source first became classified-offline in the current episode, or `None`).
  - `Feed._set_source_state(self, st)` — sets `self.source_state = st` AND maintains `offline_since`: stamp on the first `None → classified` transition (keep the original stamp across `not_live_yet → ended`), clear on `→ None`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_pov.py`:

```python
def t_feed_offline_since_stamps_and_clears():
    f = m.Feed("A", 53001, 0, lambda: ["a"], LOGDIR)
    assert f.offline_since is None
    f._set_source_state("not_live_yet")
    t0 = f.offline_since
    assert t0 is not None and f.source_state == "not_live_yet"
    f._set_source_state("ended")          # same outage -> keep the original stamp
    assert f.offline_since == t0 and f.source_state == "ended"
    f._set_source_state(None)             # recovered -> cleared
    assert f.offline_since is None and f.source_state is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_feed_offline_since_stamps_and_clears()"`
Expected: FAIL — `AttributeError: 'Feed' object has no attribute 'offline_since'`.

- [ ] **Step 3: Implement**

3a. In `Feed.__init__`, at the existing line (~5290):
```python
        self.source_state = None      # #495: "not_live_yet"/"ended"/None (why the feed isn't serving)
```
add immediately below it:
```python
        self.offline_since = None     # #495: epoch the source first became classified-offline (else None)
```

3b. Add the helper method on `Feed` (place it right after `__init__`, before the run loop):
```python
    def _set_source_state(self, st):
        """Set source_state and maintain offline_since (#495): stamp the epoch on the
        first None->classified transition of an outage (kept across not_live_yet->ended),
        and clear it when the source is no longer classified-offline."""
        if st:
            if self.offline_since is None:
                self.offline_since = time.time()
        else:
            self.offline_since = None
        self.source_state = st
```

3c. Replace the four direct assignments with the helper:
- ~5329 `self.source_state = None      # a fresh serve/reposition: the drop's cause no longer applies`
  → `self._set_source_state(None)     # a fresh serve/reposition: the drop's cause no longer applies`
- ~5337 (inside `if st:`) `self.source_state = st` → `self._set_source_state(st)`
- ~5499 `self.source_state = classify_source_state(err)` → `self._set_source_state(classify_source_state(err))`
- ~5559 `self.source_state = None   # confirmed live serve: the drop's cause no longer applies (#495)`
  → `self._set_source_state(None)   # confirmed live serve: the drop's cause no longer applies (#495)`

(Use `grep -n "self.source_state" src/relay/racecast-feeds.py` to confirm the exact four sites before editing; the `__init__` line stays a direct assignment plus the new `offline_since` line.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_pov.py`
Expected: PASS (new test green; `t_status_exposes_feed_source_state` and all others still green — the helper is a drop-in).

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): track Feed.offline_since beside source_state for the auto-cover settle (#495)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Relay auto-cover tick + flags + `/status` field

**Files:**
- Modify: `src/relay/racecast-feeds.py` (Relay `__init__` ~5695; `start()` ~5752; new `_auto_cover_loop`/`_maybe_auto_cover` near `_maybe_auto_failover` ~6002; `status()` ~6046)
- Test: `tests/test_pov.py`

**Interfaces:**
- Consumes: `auto_cover_enabled`, `auto_cover_action`, `AUTO_COVER_POLL_S`, `AUTO_COVER_SETTLE_S`, `STANDBY_COVER_SOURCE` (Task 1); `Feed.source_state`/`offline_since` (Task 2); `self.live_feed()`, `self.feeds`, `self._hb_stop`, `_obs_ws.read_obs_state`, `_obs_ws.set_scene_item_enabled`, `getattr(_obs_ws, "STINT_SCENE", "Stint")`.
- Produces:
  - Relay attrs `self.auto_cover` (bool), `self._cover_fired` (bool), `self._cover_auto_owned` (bool).
  - `Relay._auto_cover_loop(self)` (daemon, waits `AUTO_COVER_POLL_S` on `self._hb_stop`) and `Relay._maybe_auto_cover(self, now)`.
  - `status()["auto_cover_active"] = bool(self._cover_auto_owned)` (consumed by the Task 4 panel warnline).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_pov.py`:

```python
def t_status_exposes_auto_cover_active():
    r = _relay(["a", "b"])
    assert r.status()["auto_cover_active"] is False
    r._cover_auto_owned = True
    assert r.status()["auto_cover_active"] is True

def t_maybe_auto_cover_no_obs_is_noop():
    # Best-effort: with no obs-ws bound the tick must return without raising and
    # must not falsely latch the outage flags.
    saved = m._obs_ws
    m._obs_ws = None
    try:
        r = _relay(["a", "b"])
        r.A._set_source_state("ended")
        r.A.offline_since = 100.0
        r._maybe_auto_cover(200.0)          # 100s offline, but no OBS -> no-op
        assert r._cover_fired is False
        assert r._cover_auto_owned is False
    finally:
        m._obs_ws = saved
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_status_exposes_auto_cover_active()"`
Expected: FAIL — `KeyError: 'auto_cover_active'`.

- [ ] **Step 3: Implement**

3a. In `Relay.__init__`, after the auto-failover flags (~5696, after `self._failed_over = False`), add:
```python
        # #495 auto-cover: raise the #378 Standby Cover over an offline on-air source
        # (keeps the HUD). Default-on (RACECAST_OBS_AUTO_COVER); fires once per outage,
        # re-arms on recovery; never fights the manual RED FLAG (owns only what it raised).
        self.auto_cover = auto_cover_enabled(os.environ)
        self._cover_fired = False       # already raised the cover for the current outage
        self._cover_auto_owned = False  # auto raised the cover that is currently shown
```

3b. In `Relay.start()`, after the heartbeat thread line (~5752), add:
```python
        threading.Thread(target=self._auto_cover_loop, daemon=True).start()
```

3c. Add the two methods next to `_maybe_auto_failover` (after it, ~line 6044):
```python
    def _auto_cover_loop(self):
        """Fast tick (AUTO_COVER_POLL_S) that auto-raises/lowers the Standby Cover on an
        offline on-air source (#495). Separate from the 30 s health heartbeat because
        covering black is time-sensitive. Daemon; stops with the process."""
        while not self._hb_stop.is_set():
            try:
                self._maybe_auto_cover(time.time())
            except Exception:  # noqa: BLE001 — best-effort; never break the tick loop
                pass
            self._hb_stop.wait(AUTO_COVER_POLL_S)

    def _maybe_auto_cover(self, now):
        """Auto-raise the #378 Standby Cover over the ON-AIR picture when that feed's
        classified source_state (#502) is offline/ended, and lower it on confirmed-live
        recovery — keeping the HUD. Default-on; fires once per outage, re-arms on
        recovery, never fights the manual RED FLAG. Best-effort: never raises."""
        if _obs_ws is None:
            return
        f = self.feeds[self.live_feed()]
        ss, off_since = f.source_state, f.offline_since
        if ss is None:
            self._cover_fired = False        # re-arm for the next outage (memory-only)
        # Cheap gate: touch OBS only when a raise or a lower could actually be pending.
        maybe_raise = (self.auto_cover and ss in ("not_live_yet", "ended")
                       and off_since is not None and (now - off_since) >= AUTO_COVER_SETTLE_S
                       and not self._cover_fired)
        maybe_lower = (self._cover_auto_owned and ss is None)
        if not maybe_raise and not maybe_lower:
            return
        on_air_scene = getattr(_obs_ws, "STINT_SCENE", "Stint")
        state, note = _obs_ws.read_obs_state([(on_air_scene, STANDBY_COVER_SOURCE)], [])
        if state is None:                    # OBS unreachable — one note, retry next tick
            self.obs_note = note or self.obs_note
            return
        scene = state.get("scene")
        src0 = (state.get("sources") or [{}])[0] or {}
        cover_shown = bool(src0.get("enabled"))
        action = auto_cover_action(self.auto_cover, ss, off_since, now, AUTO_COVER_SETTLE_S,
                                   cover_shown, self._cover_auto_owned, self._cover_fired,
                                   scene, on_air_scene=on_air_scene)
        if action == "raise":
            ok, note = _obs_ws.set_scene_item_enabled(on_air_scene, STANDBY_COVER_SOURCE, True)
            if not ok:                       # not latched -> retry next tick
                self.obs_note = note or self.obs_note
                return
            self._cover_fired = True
            self._cover_auto_owned = True
            LOG.warning("Auto-cover: on-air feed %s source %s -> raised Standby Cover (#495)",
                        f.name, ss)
        elif action == "lower":
            ok, note = _obs_ws.set_scene_item_enabled(on_air_scene, STANDBY_COVER_SOURCE, False)
            if not ok:
                self.obs_note = note or self.obs_note
                return
            self._cover_auto_owned = False
            LOG.info("Auto-cover: on-air source recovered -> lowered Standby Cover (#495)")
        elif maybe_raise and cover_shown:
            # A cover is already up (the director raised it) during this outage. Adopt the
            # outage as handled so we neither double-raise nor re-poll OBS every tick — but
            # do NOT take ownership (auto never lowers a manually-raised cover).
            self._cover_fired = True
        # Recovery reconciliation: once the source is live again we own no cover, even if
        # it was already hidden manually (prevents a stale-owned OBS re-poll loop).
        if ss is None:
            self._cover_auto_owned = False
```

3d. In `status()` (the top-level dict it returns, ~6046 onward — find the outer `return {…}` that already contains `"mode"`/`"desync"`; add a sibling key), add:
```python
            "auto_cover_active": bool(self._cover_auto_owned),
```
(Place it beside the other top-level status keys such as `"mode"`; keep trailing-comma style consistent with the surrounding dict.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_pov.py`
Expected: PASS (both new tests green; no regressions).

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): auto-cover tick — raise/lower the Standby Cover on offline on-air source (#495)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Director-Panel warnline + `.env.example` + wiki docs/screenshot

**Files:**
- Modify: `src/director/director-panel.html` (the `relayPoll` warnline block, ~line 1568–1573)
- Modify: `.env.example`
- Modify: `src/docs/wiki/Director.md` (a line on the auto-cover behavior)
- Regenerate: `src/docs/wiki/images/director-panel.png` (+ any slides copy)
- Test: none new (front-end + config + docs); the Task 3 `status()["auto_cover_active"]` field is the data contract.

**Interfaces:**
- Consumes: `d.auto_cover_active` from `/status` (Task 3).

- [ ] **Step 1: Add the warnline** — in `src/director/director-panel.html`, immediately after the #493 auto-step-down `["A","B"].forEach(...)` block (the one pushing the "auto-dropped to ROBUST" warnline, ~line 1573), add:

```javascript
    // #495: auto-cover alert — the relay auto-raised the Standby Cover over an offline
    // on-air source. The RED FLAG light already shows the cover is up; this line says WHY.
    if (d.auto_cover_active)
      lines.push('<span class="warnline">⚠ On-air source offline — Standby Cover auto-raised (RED FLAG to override)</span>');
```

- [ ] **Step 2: Document the flag** — in `.env.example`, add a block alongside the other `RACECAST_OBS_*` / feature flags:

```bash
# On-air auto-cover (#495): when an ON-AIR feed's source goes offline / not-live-yet /
# live-ended, the relay auto-raises the #378 "Standby Cover" over the picture (keeping the
# HUD) after a short settle, and lowers it again when the source is live. Default ON; set to
# a falsey value (0/false/no/off) to disable ONLY the automation — the manual RED FLAG /
# Companion toggle still works.
# RACECAST_OBS_AUTO_COVER=1
```

- [ ] **Step 3: Document in the wiki page** — in `src/docs/wiki/Director.md`, near the RED FLAG / Standby Cover description, add a short paragraph:

```markdown
The **Standby Cover** also raises **automatically** when the on-air feed's source goes
offline, is not live yet, or has ended (after a ~12 s settle), so the broadcast shows the
standby slate instead of black — the HUD (Race Control banner + timer) stays on top. It
lowers again on its own when the source is live. A `⚠ On-air source offline — Standby Cover
auto-raised` note appears in the panel's feed-health area; press **RED FLAG** to override.
Disable the automation with `RACECAST_OBS_AUTO_COVER=0` (the manual button is unaffected).
```

- [ ] **Step 4: Visual pre-flight look (`ui-visual-verification` skill)**

Serve the demo relay + obs-sim (wiki-screenshots Part B recipe), open `/panel`, and drive the panel so `auto_cover_active` is true (simplest: with the demo relay running, a source is offline → the warnline renders; or temporarily assert the render by confirming the warnline element appears when `d.auto_cover_active` is true). Take an **element** screenshot of `#feedHealth`, `Read` it back, and confirm the warnline uses the `.warnline` style (amber, matches the sibling ROBUST line), is not clipped, and reads correctly. Fix and re-shoot if off. Then record the marker:
```bash
python3 .claude/hooks/record_ui_verified.py src/director/director-panel.html
```

- [ ] **Step 5: Regenerate the committed wiki screenshot**

Use the **wiki-screenshots** skill to regenerate `src/docs/wiki/images/director-panel.png` from the local dev build (per the CLAUDE.md hard rule + the dev-build version-badge rule), and update any slides copy of it. Commit the PNG alongside the code.

- [ ] **Step 6: Run the full suite + lint + build**

```bash
python3 tools/run-tests.py > /tmp/rc-tests.txt 2>&1; echo "EXIT=$?"   # read the file; do NOT pipe to tail
python3 tools/lint.py
python3 tools/build.py
```
Expected: `EXIT=0`; lint clean; build verify passes.

- [ ] **Step 7: Commit**

```bash
git add src/director/director-panel.html .env.example src/docs/wiki/Director.md src/docs/wiki/images/director-panel.png
git commit -m "feat(panel): auto-cover warnline + RACECAST_OBS_AUTO_COVER docs + screenshot (#495)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final whole-branch review

After Task 4, dispatch the final code reviewer (superpowers:requesting-code-review) on the full branch diff (`git merge-base main HEAD`..HEAD). Focus lenses: the fire-once/ownership/re-arm state machine in `_maybe_auto_cover` (no re-raise after a manual lower; never auto-lower a manually-raised cover; no stale-owned OBS re-poll loop after recovery); best-effort OBS contract (unreachable OBS never latches a flag / never raises); the cheap pre-gate really prevents per-tick OBS polling on a healthy on-air source and during a steady raised outage; auto is visibility-only (no HUD "Red Flag" banner write); default-on opt-out parsing; and the escalation-ladder coexistence with `_maybe_auto_failover` (auto-cover only manages the cover while OBS is on `Stint`).

## Self-Review (author)

**1. Spec coverage:**
- Auto-raise/lower on on-air `source_state` offline/ended, keep HUD → Task 3 (`_maybe_auto_cover` + `set_scene_item_enabled` on the Stint-scene `Standby Cover`). ✓
- ~5 s tick / ~12 s settle via `offline_since` timestamp → Task 1 constants + Task 2 `offline_since` + Task 3 loop. ✓
- Fire-once-per-outage, re-arm on recovery, ownership, never fight manual, visibility-only → Task 1 pure fn + Task 3 flags/adopt/reconcile. ✓
- Default-on opt-out `RACECAST_OBS_AUTO_COVER` → Task 1 `auto_cover_enabled`, Task 3 wiring, Task 4 `.env.example`. ✓
- Escalation-ladder coexistence with #378 failover (only act on `Stint`) → Task 1 scene guard + Task 3 `on_air_scene`. ✓
- Panel warnline as the only UI change; RED FLAG light already reflects real state → Task 4 + Task 3 `auto_cover_active`. ✓
- Best-effort OBS, never raise, no false latch on failure → Task 3 (`_obs_ws is None` guard, `state is None` guard, un-latched retry on `not ok`, loop try/except). ✓
- Tests: pure truth table + `offline_since` transitions + status field + no-obs no-op → Tasks 1–3. ✓
- Non-goals unchanged (generic drops / 429 / splitscreen / audio / new graphic / fallback source). ✓

**2. Placeholder scan:** none — every code/step is concrete.

**3. Type consistency:** `auto_cover_action` signature identical across Task 1 (def) and Task 3 (call, keyword `on_air_scene=`); `STANDBY_COVER_SOURCE`, `AUTO_COVER_SETTLE_S`, `AUTO_COVER_POLL_S`, `auto_cover_enabled`, `_set_source_state`, `offline_since`, `auto_cover_active`, `_cover_fired`, `_cover_auto_owned` used consistently between tasks.
