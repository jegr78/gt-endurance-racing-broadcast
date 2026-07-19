# On-air-aware SPLIT audio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the SPLIT audio follow whichever feed is on air (unmute on-air, mute off-air + Discord), resolved server-side from `Relay.live_feed()`, so the stint-2→3-class "muted the live commentator" bug can't recur — for both the Director Panel and the Companion button.

**Architecture:** A pure `split_audio_targets(live_feed)` resolver + an `apply_split_audio(relay, obs_ws)` handler in the relay, exposed as `POST /obs/split-audio` (director-gated via the `/console` mount) and `GET /obs/split-audio` (tailnet, for Companion). The panel SPLIT macro and the Companion "Split Scene" button call it instead of hardcoding mutes.

**Tech Stack:** Python 3 stdlib only. Tests are stdlib runnable scripts (`t_*` auto-run). Director Panel is plain HTML/JS. Companion config is JSON edited via the `companion-buttons` skill.

## Global Constraints

- Edit only under `src/` (plus `tests/`, `docs/`, and the committed wiki images under `src/docs/wiki/images/`). Never `dist/`/`runtime/`.
- Python + stdlib only; no new deps. English only.
- `/obs/*` is already director-gated (`console_policy.min_capability` maps `p[0]=="obs"` → `Requirement(DIRECTOR, False)`), so no `console_policy` change is needed.
- OBS control is best-effort: `_obs_ws is None` or a falsey `set_input_mute` → HTTP 503 with a note; never raise (mirror the existing `/obs/audio` handler).
- Feed input names are `"Feed A"`, `"Feed B"`, `"Discord Audio Capture"` (match the panel `CONFIG` macro strings).
- A visible Director Panel change MUST refresh `src/docs/wiki/images/director-panel.png` in the same change (CLAUDE.md); a Companion button change MUST refresh the `companion-page*` board images.
- `python3 tools/run-tests.py` + `python3 tools/lint.py` green at the end.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: Relay `/obs/split-audio` endpoint (pure resolver + apply + dispatch)

**Files:**
- Modify: `src/relay/racecast-feeds.py` — add `SPLIT_DISCORD_INPUT`, `split_audio_targets`, `apply_split_audio` (place near the other `_obs_*`/OBS helpers); add `["obs","split-audio"]` dispatch in `do_POST` (next to `["obs","audio"]`, ~line 8835) and in `do_GET` (next to `["obs","flag",...]`, ~line 8278)
- Test: `tests/test_obsws.py` (pure resolver + apply with stubs) and `tests/test_cockpit.py` OR `tests/test_console_gate.py` (endpoint dispatch over the ephemeral-server harness)

**Interfaces:**
- Produces:
  - `split_audio_targets(live_feed) -> (unmute:str, mute:list[str])` — pure. `"A"` → `("Feed A", ["Feed B", "Discord Audio Capture"])`; anything else (`"B"`) → `("Feed B", ["Feed A", "Discord Audio Capture"])`.
  - `apply_split_audio(relay, obs_ws) -> (payload:dict, status:int)` — `obs_ws is None` → `({"error":"obs unavailable"}, 503)`; else resolves `relay.live_feed()`, applies mutes via `obs_ws.set_input_mute`, returns `({"ok":bool,"live":str,"unmute":str,"mute":list,[ "note":str]}, 200|503)`.

- [ ] **Step 1: Write the failing pure + apply tests** (append to `tests/test_obsws.py`)

```python
def t_split_audio_targets_A_on_air():
    assert m.split_audio_targets("A") == ("Feed A", ["Feed B", "Discord Audio Capture"])


def t_split_audio_targets_B_on_air():
    # the Suzuka bug: B on air must unmute B and mute A (not the reverse)
    assert m.split_audio_targets("B") == ("Feed B", ["Feed A", "Discord Audio Capture"])


def t_apply_split_audio_mutes_offair_unmutes_onair():
    calls = []

    class _Obs:
        def set_input_mute(self, name, muted):
            calls.append((name, muted)); return True, ""

    class _Relay:
        def live_feed(self):
            return "B"

    payload, status = m.apply_split_audio(_Relay(), _Obs())
    assert status == 200 and payload["ok"] is True and payload["live"] == "B"
    assert ("Feed B", False) in calls          # on-air unmuted
    assert ("Feed A", True) in calls           # off-air muted
    assert ("Discord Audio Capture", True) in calls


def t_apply_split_audio_no_obs_is_503():
    class _Relay:
        def live_feed(self):
            return "A"

    payload, status = m.apply_split_audio(_Relay(), None)
    assert status == 503 and payload.get("ok") is not True
```

- [ ] **Step 2: Run — confirm RED**

Run: `python3 tests/test_obsws.py`
Expected: FAIL — `AttributeError: module 'iroobs'/'irofeeds' has no attribute 'split_audio_targets'`.

- [ ] **Step 3: Implement the resolver + apply**

In `src/relay/racecast-feeds.py`, near the other OBS helpers:

```python
SPLIT_DISCORD_INPUT = "Discord Audio Capture"   # #534: interview/Discord bus muted during a SPLIT


def split_audio_targets(live_feed):
    """(unmute, mute) OBS inputs for a SPLIT given the on-air feed (#534): unmute the
    on-air feed, mute the off-air feed + the Discord/interview bus. Pure — the fix for
    the hardcoded 'unmute A / mute B' that muted the live commentator on B-on-air handovers."""
    on = "Feed A" if live_feed == "A" else "Feed B"
    off = "Feed B" if live_feed == "A" else "Feed A"
    return on, [off, SPLIT_DISCORD_INPUT]


def apply_split_audio(relay, obs_ws):
    """Resolve the on-air feed and apply the SPLIT audio via obs-websocket (#534).
    Best-effort, mirrors /obs/audio: obs unreachable -> ({"error":...}, 503); never raises."""
    if obs_ws is None:
        return {"error": "obs unavailable"}, 503
    live = relay.live_feed()
    unmute, mute = split_audio_targets(live)
    ok_all = True
    notes = []
    ok, note = obs_ws.set_input_mute(unmute, False)
    ok_all = ok_all and ok
    if note:
        notes.append(note)
    for name in mute:
        ok, note = obs_ws.set_input_mute(name, True)
        ok_all = ok_all and ok
        if note:
            notes.append(note)
    payload = {"ok": bool(ok_all), "live": live, "unmute": unmute, "mute": mute}
    if notes:
        payload["note"] = "; ".join(str(n) for n in notes)
    return payload, (200 if ok_all else 503)
```

- [ ] **Step 4: Run — confirm GREEN**

Run: `python3 tests/test_obsws.py`
Expected: PASS.

- [ ] **Step 5: Add the route dispatch**

In `do_POST`, next to `if p == ["obs", "audio"]:` (~line 8835):
```python
                if p == ["obs", "split-audio"]:
                    payload, status = apply_split_audio(relay, _obs_ws)
                    return self._send(payload, status)
```
In `do_GET`, next to the `["obs", "flag", ...]` block (~line 8278):
```python
                if p == ["obs", "split-audio"]:
                    payload, status = apply_split_audio(relay, _obs_ws)
                    return self._send(payload, status)
```

- [ ] **Step 6: Write the endpoint dispatch test**

Append to `tests/test_console_gate.py` (it already stands up `make_handler` and stubs `m._obs_ws` with a `_FakeObs`; follow its `orig, m._obs_ws = m._obs_ws, _FakeObs()` … `finally: m._obs_ws = orig` pattern and its server/get/post harness). The test must:
1. stub a relay whose `live_feed()` returns `"B"`,
2. `POST /obs/split-audio` (director-authenticated, as the file's other `/obs` tests do),
3. assert HTTP 200, `body["live"] == "B"`, and that the `_FakeObs` recorded `set_input_mute("Feed B", False)`, `("Feed A", True)`, `("Discord Audio Capture", True)`.

Write it consistent with that file's existing helpers (do not invent a new harness). If the file's `_FakeObs` lacks `set_input_mute`, add a recording `set_input_mute(self, name, muted)` returning `(True, "")`.

- [ ] **Step 7: Run — confirm GREEN + commit**

Run: `python3 tests/test_obsws.py` and `python3 tests/test_console_gate.py`
Expected: both PASS.
```bash
git add src/relay/racecast-feeds.py tests/test_obsws.py tests/test_console_gate.py
git commit -m "feat(relay): on-air-aware /obs/split-audio endpoint (#534)"
```

---

### Task 2: Director Panel — SPLIT calls the endpoint (dynamic audio)

**Files:**
- Modify: `src/director/director-panel.html` — the `SPLIT` macro (`~line 874`) and `runMacro` (`~line 1326`)
- Refresh: `src/docs/wiki/images/director-panel.png` (+ the slides copy) — via the `wiki-screenshots` skill
- (No new unit test — behavior is server-side, covered by Task 1; verified visually.)

**Interfaces:**
- Consumes: `POST /obs/split-audio` (Task 1); `obsPost(path, body)` (existing, `~line 1164`).

- [ ] **Step 1: Make the SPLIT macro server-resolved**

Replace the SPLIT macro (~line 874):
```javascript
    {label:"SPLIT", scene:"Splitscreen",
     show:[["Splitscreen","Feed A"],["Splitscreen","Feed B"]], hide:[],
     airAudio:true, rc:"Driver Swaps"},
```
(removed the hardcoded `unmute:["Feed A"], mute:["Feed B","Discord Audio Capture"]`; added `airAudio:true`.)

- [ ] **Step 2: Route `airAudio` through `runMacro`**

In `runMacro` (the audio-steps lines ~1328–1329), replace the two `m.unmute`/`m.mute` spreads with a conditional that keeps the static behaviour for every other macro and calls the endpoint for an `airAudio` macro:
```javascript
    ...(m.airAudio
        ? [[`split audio (on-air)`, ()=>obsPost("split-audio", {})]]
        : [...(m.unmute||[]).map(i=>[`unmute ${i}`, ()=>obsMute(i,false)]),
           ...(m.mute||[]).map(i=>[`mute ${i}`,     ()=>obsMute(i,true)])]),
```
(The `||[]` guards let the SPLIT macro omit `unmute`/`mute` entirely.)

- [ ] **Step 3: Verify the change renders and works** — REQUIRED SUB-SKILL: `ui-visual-verification`. Drive the Director Panel (demo profile + `tools/obs-sim.py` stand-in), press SPLIT, confirm exactly one `POST /obs/split-audio` fires (no per-input `/obs/audio` mute calls) and the button/log behave; record the marker.

- [ ] **Step 4: Refresh the wiki screenshot** — REQUIRED SUB-SKILL: `wiki-screenshots`. Regenerate `director-panel.png` (Control-Center/`/console` recipe) and commit it alongside the HTML.

- [ ] **Step 5: Commit**

```bash
git add src/director/director-panel.html src/docs/wiki/images/director-panel.png
git commit -m "feat(panel): SPLIT resolves on-air audio via /obs/split-audio (#534)"
```

---

### Task 3: Companion "Split Scene" button — call the endpoint

**Files:**
- Modify: `src/companion/racecast-buttons.companionconfig` — the "Split Scene" button (via the `companion-buttons` skill)
- Refresh: the relevant `src/docs/wiki/images/companion-page*-*.png` (via `companion-screenshots`)

- [ ] **Step 1: Add the endpoint call to the button** — REQUIRED SUB-SKILL: `companion-buttons`. Keep the button's scene switch; add a Generic-HTTP **GET** action to `http://<relay>:8088/obs/split-audio` (loopback/tailnet), and remove any static per-input mute actions on that button. Import into a running Companion and click-test that the on-air feed stays audible.

- [ ] **Step 2: Refresh the Companion board screenshot** — REQUIRED SUB-SKILL: `companion-screenshots`. Regenerate the page image containing the Split button and commit it.

- [ ] **Step 3: Commit**

```bash
git add src/companion/racecast-buttons.companionconfig src/docs/wiki/images/companion-page*.png
git commit -m "feat(companion): Split Scene button resolves on-air audio via /obs/split-audio (#534)"
```

---

### Task 4: Full-suite + lint gate

- [ ] **Step 1:** `python3 tools/run-tests.py` → ALL PASS (incl. `test_obsws.py`, `test_console_gate.py`).
- [ ] **Step 2:** `python3 tools/lint.py` → clean.
- [ ] **Step 3:** `python3 tools/build.py` → verify passes.
- [ ] **Step 4:** commit any fixups only if 1–3 required them.

## Self-Review

- Spec §1 pure targets → Task 1 Steps 1–4 (both directions, B-case = the bug). ✅
- Spec §2 apply handler (503 contract) → Task 1 Steps 3, 6. ✅
- Spec §3 two routes, one handler, `/obs/*` auto-gated → Task 1 Step 5 (POST + GET), Global Constraints note. ✅
- Spec §4 panel SPLIT server-resolved, STINT A/B unchanged → Task 2 (the `airAudio` conditional leaves all other macros' `unmute`/`mute` intact). ✅
- Spec §5 Companion button → Task 3. ✅
- Visual/screenshot obligations (CLAUDE.md) → Task 2 Steps 3–4, Task 3 Steps 1–2. ✅
- No placeholders; every code step shows full code; every run step shows command + expected output.
- Type consistency: `split_audio_targets(live_feed) -> (str, list)`, `apply_split_audio(relay, obs_ws) -> (dict, int)`, `obsPost("split-audio", {})`, `airAudio` flag — consistent across tasks.
