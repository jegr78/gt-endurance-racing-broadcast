# One-Button Handover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a driver-swap handover one button (`/next`) with no operator A/B awareness and no cold-start special case, by making the relay the single source of truth for feed state and reflecting that state into OBS over obs-websocket.

**Architecture:** Two coupled changes. (1) The off-air feed sits on its **own** next-stint slot and **idles** (black) when that slot has no link, instead of clamping onto the live stint — this removes the `A.idx == B.idx` tie/off-by-one and makes "new live = the feed `/next` did not advance" an invariant. (2) On every well-defined feed transition (startup, `/set/stint`, `/next`) the relay pushes the matching OBS state (Stint-scene source visibility + feed audio mute/unmute; on `/next` also cut program to Stint) via the existing `src/scripts/obs_ws.py` client — best effort, with the manual panel/Companion controls as the break-glass fallback. Plus an optional in-memory schedule inject so a panel-entered link is available before the next poll.

**Tech Stack:** Python 3 stdlib only (no pytest — each `tests/test_*.py` is a runnable script). obs-websocket v5 via the existing minimal client. Director panel is plain HTML/JS using obs-websocket-js.

**Spec:** `docs/superpowers/specs/2026-06-08-one-button-handover-design.md`

**Conventions:** TDD (failing test first). Run a single test file with `python3 tests/test_NAME.py` (prints `ok <fn>` per test, then `ALL PASS`). After relay changes run `python3 tests/test_pov.py`; before shipping run `python3 tools/lint.py` and `python3 tools/build.py`. Commit messages follow conventional commits (`feat:`/`fix:`/`refactor:`/`docs:`). Work on the existing branch `design/one-button-handover`.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/relay/iro-feeds.py` | Relay core: indices, feeds, handover, status, OBS reflection wiring | Modify |
| `src/scripts/obs_ws.py` | obs-websocket client; add pure intent planner + reflect apply | Modify |
| `src/director/director-panel.html` | Director panel; add OBS-unreachable banner | Modify |
| `src/scripts/preflight.py` | Pre-event check; tie the existing 4455 check to the handover dependency | Modify |
| `tests/test_stint.py` | `stint_start_indices` unit checks | Modify |
| `tests/test_pov.py` | Feed/`current_channel`/`set_index` + handover-invariant checks | Modify |
| `tests/test_obsws.py` | obs_ws pure-function checks; add intent-planner checks | Modify |
| `tests/test_setup.py` | SetupControl + schedule write; add inject checks | Modify |
| `src/docs/wiki/Director.md`, `src/docs/wiki/Relay-Mode.md` | Operator docs for the one-button flow | Modify |

---

## Phase 1 — Relay index invariant (Change 1)

### Task 1: `stint_start_indices` — off-air feed gets its own next slot

**Files:**
- Modify: `src/relay/iro-feeds.py:736-742`
- Test: `tests/test_stint.py:13-37`

- [ ] **Step 1: Update the failing tests to the new invariant**

In `tests/test_stint.py`, change the expected tuples so the off-air index is always `live_index + 1` (never clamped onto the live index):

```python
def t_start_from_one():
    assert m.stint_start_indices(1, 8) == (0, 1)
    assert m.stint_start_indices(1, 2) == (0, 1)
    assert m.stint_start_indices(1, 1) == (0, 1)   # was (0,0): B idles on the empty slot 2
    assert m.stint_start_indices(1, 0) == (0, 1)   # was (0,0): empty schedule, both idle


def t_takeover_midschedule():
    assert m.stint_start_indices(3, 8) == (2, 3)
    assert m.stint_start_indices(4, 8) == (3, 4)


def t_takeover_last_stint_b_idles():
    assert m.stint_start_indices(9, 8) == (7, 8)   # was (7,7): clamp A to last; B idles (no next)
    assert m.stint_start_indices(8, 8) == (7, 8)   # was (7,7): last stint live; B idles


def t_takeover_below_one_clamps_to_one():
    assert m.stint_start_indices(0, 8) == (0, 1)
    assert m.stint_start_indices(-5, 8) == (0, 1)
```

(Keep the existing function names if they differ — only the asserted tuples and the new `t_takeover_last_stint_b_idles` split change. If `t_takeover_clamps_to_last` exists, rename/replace it with `t_takeover_last_stint_b_idles`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_stint.py`
Expected: FAIL — `AssertionError` on `stint_start_indices(1, 1)` (currently returns `(0, 0)`).

- [ ] **Step 3: Rewrite `stint_start_indices`**

Replace `src/relay/iro-feeds.py:736-742` with:

```python
def stint_start_indices(stint, schedule_len):
    """0-based (A, B) start indices for a producer takeover: 1-based stint
    <stint> is on air NOW -> Feed A serves it, Feed B preloads the NEXT slot.
    A is clamped to a real stint; B is always A+1 and may point past the end
    (an empty/missing slot) — the off-air feed then idles (black) until that
    stint's link appears, instead of duplicating A's stream."""
    stint = max(1, int(stint))
    hi = max(0, schedule_len - 1)
    a = min(stint - 1, hi)
    return a, a + 1
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_stint.py`
Expected: PASS — ends with `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/iro-feeds.py tests/test_stint.py
git commit -m "refactor(relay): off-air feed gets its own next slot, not a clamp"
```

---

### Task 2: `current_channel` idles past the schedule; `set_index` allows the idle slot

**Files:**
- Modify: `src/relay/iro-feeds.py:1107-1115` (`current_channel`), `:1138-1147` (`set_index`), `:1670-1672` (WARN)
- Test: `tests/test_pov.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pov.py` (before the `if __name__` block):

```python
def t_current_channel_idles_past_end():
    # idx beyond the schedule -> idle (None), NOT a clamp onto the last stint
    f = m.Feed("B", 53002, 1, lambda: ["https://youtu.be/only"], HERE)
    assert f.current_channel() == (None, 1)        # one link, B on slot 2 -> idle
    f2 = m.Feed("B", 53002, 0, lambda: ["https://youtu.be/only"], HERE)
    assert f2.current_channel() == ("https://youtu.be/only", 0)


def t_set_index_allows_one_past_end_for_idle():
    f = m.Feed("A", 53001, 0, lambda: ["a", "b"], HERE)
    assert f.set_index(2) is True                  # len 2 -> idle slot 2 is reachable
    assert f.idx == 2
    assert f.current_channel() == (None, 2)        # idles
    assert f.set_index(99) is True                 # clamped to len (idle sentinel)
    assert f.idx == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_pov.py`
Expected: FAIL — `current_channel` currently clamps `min(idx, len-1)` and returns `("https://youtu.be/only", 0)` for the idle case.

- [ ] **Step 3: Implement idle-past-end**

In `src/relay/iro-feeds.py`, replace the body of `current_channel` (`:1107-1115`):

```python
    def current_channel(self):
        if self.paused:
            return None, self.idx
        sched = self.provider()
        with self.lock:
            if not sched or self.idx >= len(sched):
                return None, self.idx          # idle: empty schedule or own slot not filled yet
            return sched[self.idx], self.idx
```

Replace the clamp in `set_index` (`:1138-1147`) so the idle sentinel (`len`) stays reachable:

```python
    def set_index(self, new_idx):
        sched = self.provider()
        new_idx = max(0, min(new_idx, len(sched)))   # len == idle slot (one past the last stint)
        with self.lock:
            if new_idx == self.idx:
                return False
            self.idx = new_idx
        self.advance.set(); self._kill_proc()
        return True
```

- [ ] **Step 4: Update the cold-start WARN message**

Replace `src/relay/iro-feeds.py:1670-1672` with:

```python
    if len(source.get()) < 2:
        print("INFO: schedule has fewer than 2 stints — Feed B idles on the empty next "
              "slot (black) until that stint's link is added; Feed A keeps serving stint 1.")
```

- [ ] **Step 5: Run the tests + commit**

Run: `python3 tests/test_pov.py`
Expected: PASS — `ALL PASS`.

```bash
git add src/relay/iro-feeds.py tests/test_pov.py
git commit -m "feat(relay): off-air feed idles on an unfilled slot instead of duplicating"
```

---

## Phase 2 — OBS reflection (Change 2)

### Task 3: Pure intent planner in `obs_ws.py`

**Files:**
- Modify: `src/scripts/obs_ws.py` (add constants + `feed_state_intents` after the module constants near `:37`)
- Test: `tests/test_obsws.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_obsws.py` (before the run-loop at the bottom):

```python
def t_feed_state_intents_live_a_with_cut():
    assert m.feed_state_intents("A", True) == [
        ("show", "Feed A"), ("hide", "Feed B"),
        ("unmute", "Feed A"), ("mute", "Feed B"),
        ("cut", "Stint"),
    ]


def t_feed_state_intents_live_b_no_cut():
    assert m.feed_state_intents("B", False) == [
        ("show", "Feed B"), ("hide", "Feed A"),
        ("unmute", "Feed B"), ("mute", "Feed A"),
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_obsws.py`
Expected: FAIL — `AttributeError: module 'obs_ws' has no attribute 'feed_state_intents'`.

- [ ] **Step 3: Add constants + the pure planner**

In `src/scripts/obs_ws.py`, after `RELAY_PORTS = (53001, 53002, 53003)` (`:37`) add:

```python
STINT_SCENE = "Stint"                       # single-cam scene holding both feeds
FEED_SOURCES = {"A": "Feed A", "B": "Feed B"}   # scene-item name == audio input name


def feed_state_intents(live, do_cut, feeds=("A", "B"),
                       scene=STINT_SCENE, sources=None):
    """Pure: the OBS intent list that makes `live` (A/B) the on-air feed in the
    Stint scene. Visibility first, then audio, then (do_cut) the program cut.
    reflect_feed_state() turns each (verb, target) into obs-websocket requests."""
    sources = sources or FEED_SOURCES
    intents = [("show" if f == live else "hide", sources[f]) for f in feeds]
    intents += [("unmute" if f == live else "mute", sources[f]) for f in feeds]
    if do_cut:
        intents.append(("cut", scene))
    return intents
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_obsws.py`
Expected: PASS — `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): pure feed-state intent planner for the Stint scene"
```

---

### Task 4: `reflect_feed_state` apply in `obs_ws.py`

**Files:**
- Modify: `src/scripts/obs_ws.py` (add after `refresh_browser_inputs`, near `:393`)

- [ ] **Step 1: Add the best-effort apply**

This is network I/O against OBS; it has no unit test (same as `release_feed_inputs`/`refresh_browser_inputs`, which are I/O-only and tested via their pure helpers). Append to `src/scripts/obs_ws.py`:

```python
def reflect_feed_state(live, do_cut, scene=STINT_SCENE, sources=None,
                       host="127.0.0.1", port=None, password=None, timeout=2.0):
    """Reflect which feed (A/B) is on air into OBS: show/hide the Stint-scene
    sources, mute/unmute the feed audio inputs, and (do_cut) cut the program to
    Stint. Best effort by design: returns (applied_intents, note) and NEVER
    raises — a handover must go through even if OBS is closed/locked. On any
    failure the relay falls back to the manual panel/Companion controls."""
    intents = feed_state_intents(live, do_cut, scene=scene, sources=sources)
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return [], note
    applied = []
    try:
        for verb, target in intents:
            if verb in ("show", "hide"):
                sid = session.request("GetSceneItemId",
                                      {"sceneName": scene, "sourceName": target}).get("sceneItemId")
                session.request("SetSceneItemEnabled",
                                {"sceneName": scene, "sceneItemId": sid,
                                 "sceneItemEnabled": verb == "show"})
            elif verb in ("mute", "unmute"):
                session.request("SetInputMute",
                                {"inputName": target, "inputMuted": verb == "mute"})
            elif verb == "cut":
                session.request("SetCurrentProgramScene", {"sceneName": target})
            applied.append((verb, target))
        return applied, ""
    except Exception as exc:                         # noqa: BLE001 — best-effort contract
        return applied, str(exc) or exc.__class__.__name__
    finally:
        session.close()
```

- [ ] **Step 2: Smoke-check the import (no behavior change to existing tests)**

Run: `python3 tests/test_obsws.py`
Expected: PASS — `ALL PASS` (module still imports; new function present).

- [ ] **Step 3: Commit**

```bash
git add src/scripts/obs_ws.py
git commit -m "feat(obs): reflect_feed_state applies the intent plan to OBS (best effort)"
```

---

### Task 5: Wire the relay to reflect on startup, `/set/stint`, and `/next`

**Files:**
- Modify: `src/relay/iro-feeds.py` (module import block near `:1-40` imports; `Relay` class `:1199-1295`; `status` `:1223-1242`; `next_auto` `:1244-1247`; `set_stint` `:1260-1268`; `main` after `relay.start()` `:1677`)
- Test: `tests/test_pov.py`

- [ ] **Step 1: Write the failing handover-invariant test**

Append to `tests/test_pov.py`:

```python
class _StubSource:
    def __init__(self, items): self._items = list(items)
    def get(self): return list(self._items)
    def refresh(self, timeout=6): return True
    def health(self): return {"count": len(self._items), "last_ok_age_s": 0, "last_error": None}
    def add(self, url): self._items.append(url)


def _relay(items):
    r = m.Relay(_StubSource(items), (53001, 53002), HERE)
    r._reflect = lambda live, cut: None        # isolate index logic from OBS I/O
    return r


def t_next_new_live_is_the_non_advanced_feed():
    r = _relay(["s1", "s2", "s3", "s4"])
    assert (r.A.idx, r.B.idx) == (0, 1)
    assert r.live_after_next() == "B"          # B (stint2) is pre-warmed -> next live
    r.next_auto()
    assert (r.A.idx, r.B.idx) == (2, 1)        # A advanced to stint3; B now live
    assert r.live_feed() == "B"
    r.next_auto()
    assert (r.A.idx, r.B.idx) == (2, 3)        # B advanced to stint4; A now live
    assert r.live_feed() == "A"


def t_cold_start_one_link_then_add_second():
    r = _relay(["s1"])                         # start with ONE link
    assert (r.A.idx, r.B.idx) == (0, 1)
    assert r.B.current_channel() == (None, 1)  # B idles (black) on the empty slot 2
    r.source.add("s2")                         # link entered mid-event
    assert r.live_after_next() == "B"
    r.next_auto()
    assert r.live_feed() == "B" and r.B.current_channel() == ("s2", 1)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_pov.py`
Expected: FAIL — `AttributeError: 'Relay' object has no attribute 'live_after_next'`.

- [ ] **Step 3: Add the lazy obs_ws import**

In `src/relay/iro-feeds.py`, after the existing stdlib imports (around `:1-40`, after the last `import`), add:

```python
# OBS reflection (best effort). obs_ws lives in src/scripts (repo) or the
# bundled tree (frozen). A missing client just disables reflection — it must
# never break the relay.
_REL_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (os.path.join(_REL_HERE, "..", "scripts"),
              os.path.join(getattr(sys, "_MEIPASS", _REL_HERE), "src", "scripts")):
    if os.path.isdir(_cand) and _cand not in sys.path:
        sys.path.insert(0, _cand)
try:
    import obs_ws as _obs_ws
except Exception:                                # noqa: BLE001 — reflection is optional
    _obs_ws = None
```

(If `os` / `sys` are not already imported at the top, add them — they are used throughout, so they are.)

- [ ] **Step 4: Add live-feed helpers, `_reflect`, and reflection calls**

In the `Relay` class, add an `obs_note` attribute and helpers. After `self.feeds = {"A": self.A, "B": self.B}` (`:1207`) add:

```python
        self.obs_note = None          # last OBS-reflection note (None/"" = ok); read by status()
```

Add these methods to `Relay` (e.g. after `status`, before `next_auto`):

```python
    def live_feed(self):
        """The on-air feed = the one on the lower (earlier) stint index."""
        return "A" if self.A.idx <= self.B.idx else "B"

    def live_after_next(self):
        """Which feed will be on air after the next /next: the one NOT advanced."""
        return "B" if self.live_feed() == "A" else "A"

    def _reflect(self, live, cut):
        """Push the on-air feed (A/B) into OBS off-thread; never blocks the HTTP
        response, never raises. Records the note for /status."""
        if _obs_ws is None:
            return

        def run():
            _applied, note = _obs_ws.reflect_feed_state(live, cut)
            self.obs_note = note or None
        threading.Thread(target=run, daemon=True).start()
```

Rewrite `next_auto` (`:1244-1247`):

```python
    def next_auto(self):
        self.source.refresh(timeout=6)               # fresh sheet data at handover (bounded wait)
        new_live = self.live_after_next()
        target = "A" if new_live == "B" else "B"     # advance the OTHER (currently on-air) feed
        result = self.advance(target, +2)
        cut = self.feeds[new_live].phase == "serving"  # never auto-cut to a black/buffering feed
        self._reflect(new_live, cut)
        return {**result, "obs_cut": cut}
```

In `set_stint` (`:1260-1268`), after setting the indices and before `return`, add:

```python
        self._reflect(self.live_feed(), cut=False)   # set visibility/audio; director picks the scene
```

In `main`, right after `relay.start()` (`:1677`), add:

```python
    relay._reflect(relay.live_feed(), cut=False)     # pre-set Stint visibility/audio for the live feed
```

- [ ] **Step 5: Expose OBS health in `status`**

In `Relay.status` (`:1223-1242`), before `return out`, add:

```python
        out["obs"] = {"reachable": not self.obs_note, "note": self.obs_note}
```

- [ ] **Step 6: Run the tests + relay suite**

Run: `python3 tests/test_pov.py`
Expected: PASS — `ALL PASS`.
Run: `python3 tests/test_bind.py && python3 tests/test_stint.py`
Expected: PASS (no regressions in the other relay tests).

- [ ] **Step 7: Commit**

```bash
git add src/relay/iro-feeds.py tests/test_pov.py
git commit -m "feat(relay): reflect on-air feed into OBS on start/takeover/next"
```

---

## Phase 3 — Failure surfacing (break-glass)

### Task 6: Panel OBS-unreachable banner + preflight wording

**Files:**
- Modify: `src/director/director-panel.html:674-679` (inside `relayPoll`)
- Modify: `src/scripts/preflight.py` (the `SERVICE_PORTS` reachable message, `:322` + `:376-379`)

- [ ] **Step 1: Add the OBS banner to the panel poll**

In `src/director/director-panel.html`, inside `relayPoll()` after the cookies-banner block (after line `679 else clearBanner("cookies");`), add:

```javascript
    if (d.obs && d.obs.reachable === false)
      setBanner("obs", "amber",
        "OBS NOT REACHABLE — NEXT can't auto-cut · use the manual FEED/scene buttons; " +
        "Feed " + (d.feeds.A.state === "serving" ? "A" : "B") + " state shown above");
    else clearBanner("obs");
```

- [ ] **Step 2: Verify the panel still parses (served bytes unchanged otherwise)**

Run: `python3 -c "import pathlib,html.parser; html.parser.HTMLParser().feed(pathlib.Path('src/director/director-panel.html').read_text())" && echo OK`
Expected: `OK` (no parse error).

- [ ] **Step 3: Tie the preflight 4455 check to the handover dependency**

In `src/scripts/preflight.py`, the reachable branch for service ports (`:376-379`) currently reports `"{svc} reachable"`. Update the OBS-WebSocket case so the message names the dependency. Replace that reachable-append with:

```python
        if svc == "OBS WebSocket":
            ports.append(Result(PASS, f"port {port}", "OBS WebSocket reachable — one-button handover ready")
                         if port_reachable(host="127.0.0.1", port=port)
                         else Result(WARN, f"port {port}",
                                     "OBS WebSocket not reachable — NEXT can't auto-cut; "
                                     "enable obs-websocket in OBS (Tools -> WebSocket Server Settings)"))
        else:
            ports.append(Result(PASS, f"port {port}", f"{svc} reachable")
                         if port_reachable(host="127.0.0.1", port=port)
                         else Result(INFO, f"port {port}",
                                     f"{svc} not reachable (`iro status` confirms)"))
```

(Match the existing `Result`/level names — `PASS`/`WARN`/`INFO` — and the existing `port_reachable` signature; if the loop variable is `port`/`svc`, keep them. Preserve the existing free/in-use port block above it unchanged.)

- [ ] **Step 4: Run preflight tests**

Run: `python3 tests/test_preflight.py`
Expected: PASS — `ALL PASS` (the OBS port classification still returns a `Result`; adjust an assertion only if a test pinned the exact old "reachable" string).

- [ ] **Step 5: Commit**

```bash
git add src/director/director-panel.html src/scripts/preflight.py
git commit -m "feat(ui): surface OBS-unreachable as panel banner + preflight wording"
```

---

## Phase 4 — Optional: instant availability on panel schedule-write

### Task 7: `ScheduleSource.inject_row`

**Files:**
- Modify: `src/relay/iro-feeds.py` (add `inject_row` to `ScheduleSource`, after `get_rows` `:857-859`)
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_setup.py` (it already loads `iro-feeds.py` as `m` — reuse that loader; if it loads under a different module variable, match it):

```python
def t_inject_row_adds_link_before_poll():
    s = m.ScheduleSource(csv_url=None, cache_path=os.path.join(HERE, "_x.cache"),
                         local_fallback=None)
    s.items = ["s1"]; s.rows = [("s1", "Ann", 1)]
    assert s.inject_row(2, "https://www.youtube.com/watch?v=abc", "Ben") is True
    assert s.get() == ["s1", "https://www.youtube.com/watch?v=abc"]
    assert s.get_rows()[1] == ("https://www.youtube.com/watch?v=abc", "Ben", 2)


def t_inject_row_replaces_same_physical_row():
    s = m.ScheduleSource(csv_url=None, cache_path=os.path.join(HERE, "_x.cache"),
                         local_fallback=None)
    s.items = ["s1", "old"]; s.rows = [("s1", "Ann", 1), ("old", "X", 2)]
    s.inject_row(2, "UC1234567890123456789012", "New")
    assert s.get() == ["s1", "UC1234567890123456789012"]


def t_inject_row_rejects_empty_or_bad_url():
    s = m.ScheduleSource(csv_url=None, cache_path=os.path.join(HERE, "_x.cache"),
                         local_fallback=None)
    s.items = ["s1"]; s.rows = [("s1", "Ann", 1)]
    assert s.inject_row(2, "", "Ben") is False
    assert s.inject_row(2, "not-a-channel", "Ben") is False
    assert s.get() == ["s1"]
```

(Ensure `import os` and `HERE` exist in `tests/test_setup.py`; they do for its existing fixtures.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_setup.py`
Expected: FAIL — `AttributeError: 'ScheduleSource' object has no attribute 'inject_row'`.

- [ ] **Step 3: Implement `inject_row`**

After `ScheduleSource.get_rows` (`:857-859`) add:

```python
    def inject_row(self, physical_row, url, name=""):
        """Optimistically merge a panel schedule write into the in-memory
        schedule so an idling feed adopts it before the next poll. Keyed by
        physical sheet row (matches _parse_rows line numbers); the next poll
        reconciles against the sheet. No-op for an empty/invalid URL."""
        url = (url or "").strip()
        if not is_channel(url):
            return False
        with self.lock:
            rows = [r for r in self.rows if r[2] != physical_row]
            rows.append((url, (name or "").strip(), physical_row))
            rows.sort(key=lambda r: r[2])
            self.rows = rows
            self.items = [u for u, _n, _l in rows]
        return True
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_setup.py`
Expected: PASS — `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/iro-feeds.py tests/test_setup.py
git commit -m "feat(relay): in-memory schedule inject for instant panel writes"
```

---

### Task 8: `SetupControl` injects on a successful schedule write

**Files:**
- Modify: `src/relay/iro-feeds.py:985` (`SetupControl.__init__`), `:1031-1058` (`schedule_set`), `:1666-1668` (`main` wiring order)
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_setup.py`:

```python
def t_schedule_set_injects_on_success():
    src = m.ScheduleSource(csv_url=None, cache_path=os.path.join(HERE, "_y.cache"),
                           local_fallback=None)
    src.items = ["s1"]; src.rows = [("s1", "Ann", 1)]
    ctl = m.SetupControl(push_url="https://example.test/push", hud_source=None,
                         schedule_source=src)
    ctl._push = lambda payload, expected: (True, "")     # stub the webhook
    out = ctl.schedule_set(2, "https://www.youtube.com/watch?v=abc", "Ben")
    assert out.get("ok") is True
    assert src.get() == ["s1", "https://www.youtube.com/watch?v=abc"]   # available immediately


def t_schedule_set_no_inject_on_push_failure():
    src = m.ScheduleSource(csv_url=None, cache_path=os.path.join(HERE, "_z.cache"),
                           local_fallback=None)
    src.items = ["s1"]; src.rows = [("s1", "Ann", 1)]
    ctl = m.SetupControl(push_url="https://example.test/push", hud_source=None,
                         schedule_source=src)
    ctl._push = lambda payload, expected: (False, "boom")
    out = ctl.schedule_set(2, "https://www.youtube.com/watch?v=abc", "Ben")
    assert "error" in out
    assert src.get() == ["s1"]                            # nothing injected on failure
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_setup.py`
Expected: FAIL — `SetupControl.__init__` does not accept `schedule_source`.

- [ ] **Step 3: Add the dependency + inject on success**

In `SetupControl.__init__` (`:985`), add the parameter and store it:

```python
    def __init__(self, push_url, hud_source, schedule_source=None):
        self.push_url = push_url
        self.hud = hud_source
        self.schedule_source = schedule_source
        self.push_status = "disabled" if not push_url else "never"
```

(Keep any other existing attributes set in `__init__`.)

In `schedule_set`, change the final push/return (`:1057-1058`) to inject the URL locally on success:

```python
        ok, err = self._push(payload, "schedule")
        if ok and self.schedule_source is not None and url:
            self.schedule_source.inject_row(row, url, payload.get("name", ""))
        return {"ok": True, "row": row} if ok else {"error": err}
```

- [ ] **Step 4: Pass the source in `main`**

In `main`, `source` is created at `:1668` but `setup_ctl` at `:1666` (before it). Reorder so `source` exists first, then pass it. Replace `:1666-1668` region with:

```python
    source = ScheduleSource(csv_url, cache, local)
    source.load_initial(SCHEDULE_TEMPLATE)
    setup_ctl = SetupControl(push_url, hud_source, schedule_source=source) if hud_source else None
```

Delete the now-duplicate `source = ScheduleSource(...)` / `source.load_initial(...)` lines that previously sat at `:1668-1669` (they moved up). Keep the `if len(source.get()) < 2:` INFO block (now after this).

- [ ] **Step 5: Run the tests + commit**

Run: `python3 tests/test_setup.py && python3 tests/test_pov.py`
Expected: PASS — `ALL PASS` for both.

```bash
git add src/relay/iro-feeds.py tests/test_setup.py
git commit -m "feat(relay): panel schedule write is available immediately (local inject)"
```

---

## Phase 5 — Docs + full verification

### Task 9: Operator docs + lint + build + full suite

**Files:**
- Modify: `src/docs/wiki/Director.md` (driver-change section `:218-234`), `src/docs/wiki/Relay-Mode.md` (handover/controls)

- [ ] **Step 1: Update the Director driver-change steps**

In `src/docs/wiki/Director.md`, replace the multi-step "At a driver change" list with the one-button flow (describe the mechanism only, no invented crew procedure):

```markdown
**At a driver change**
1. Cut to **Splitscreen** with the **SPLIT** combo (covers the handover window).
2. Press **NEXT** once. The relay hands the feed over, shows the new commentator
   in the **Stint** scene, switches the audio, and cuts the program to **Stint** —
   you do not pick Feed A or Feed B.

You start a race with only the first stint's link in the **Schedule** sheet and add
each next link ~20–30 min before its swap (panel **Schedule** rows or the sheet
directly). Until a link is present the off-air feed shows a black tile in the split;
it goes live on its own once the link is in.

The relay also handles the audio (it mutes the off-air feed, unmutes the on-air one),
so **MUTE A / MUTE B** are no longer part of the normal flow. **STINT A / STINT B**,
**MUTE A / MUTE B** and **Feed A/B Toggle** stay on the panel and Stream Deck as a
**break-glass fallback** only: if the panel shows **OBS NOT REACHABLE**, NEXT can't
auto-cut — then use **STINT A / STINT B** (and, if needed, the manual FEED/MUTE
buttons) to cut by hand; `/status` shows which feed is live.
```

> **Operator-model note (decision: docs-only):** No Companion/panel buttons are
> added or relabeled. `Feeds Next` + `SPLIT` already exist and now suffice; the
> redundant A/B buttons keep working as fallback. This task only documents the new
> normal path — there is intentionally no Companion-config change and no wiki
> screenshot regeneration.

- [ ] **Step 2: Update Relay-Mode controls note**

In `src/docs/wiki/Relay-Mode.md`, near the **Feeds Next** control row, add a sentence:

```markdown
**Feeds Next (`/next`)** now also drives OBS over obs-websocket: it makes the new
commentator visible in the **Stint** scene, switches the feed audio, and cuts the
program to **Stint** (only once the incoming feed is actually serving — never to a
black/buffering feed). No Feed A/B choice and no special case for starting with one
link. Requires obs-websocket reachable (see Pre-flight); otherwise the manual
panel/Companion FEED + scene buttons remain the fallback.
```

- [ ] **Step 3: Lint**

Run: `python3 tools/lint.py`
Expected: no errors (ruff clean). If it reports issues in the touched files, fix and re-run.

- [ ] **Step 4: Run the full test suite (exactly what CI runs)**

Run: `python3 tools/run-tests.py`
Expected: all test files pass.

- [ ] **Step 5: Build + self-verify the distributable**

Run: `python3 tools/build.py`
Expected: builds `dist/IRO_Broadcast_Package/` and its verify step passes (tokenization, blanked password, no secrets, preflight present, no shell scripts).

- [ ] **Step 6: Verify the frozen relay can import obs_ws (binary path)**

Run: `python3 tools/build-binary.py`
Expected: builds `dist/bin/iro` and the smoke test passes. If `obs_ws` is missing from the frozen relay, add it to the hidden-imports / bundled data in `tools/build-binary.py` (the `src/` tree is bundled as data; the `_MEIPASS/src/scripts` path in Task 5 Step 3 resolves it), then rebuild.

- [ ] **Step 7: Commit**

```bash
git add src/docs/wiki/Director.md src/docs/wiki/Relay-Mode.md
git commit -m "docs(wiki): one-button handover flow for the director + relay mode"
```

---

## Self-Review notes (resolved during planning)

- **Spec coverage:** Change 1 → Tasks 1-2; Change 2 → Tasks 3-5; §5 failure handling → Task 6; §7 instant inject → Tasks 7-8; §8 testing folded into each task; docs → Task 9. All spec sections map to a task.
- **Type/name consistency:** `feed_state_intents` / `reflect_feed_state` (obs_ws), `live_feed` / `live_after_next` / `_reflect` / `obs_note` (Relay), `inject_row` (ScheduleSource), `schedule_source` (SetupControl) — used identically across tasks and tests.
- **Invariant check:** "new live = non-advanced feed" holds because Task 1 keeps `A.idx`/`B.idx` always distinct (B = A+1 at start; each `/next` advances exactly one by +2, preserving the offset), so `live_feed()`'s `A.idx <= B.idx` is unambiguous — this holds through the last real handover; past end-of-schedule both feeds reach the idle sentinel (a benign tie), and the serving-gated cut + reflection prevent any wrong-feed program cut or on-air visibility flip in that case.
- **Out of scope (unchanged):** POV feed, Discord audio, manual `/set/A|B` + `/prev` (fallback/expert ops, intentionally not auto-reflected), `/reload` (same stint → no identity change), HUD/timer/graphics, pull pipeline.
```
