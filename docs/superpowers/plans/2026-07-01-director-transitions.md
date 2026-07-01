# Director Per-Take Transitions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the director pick Cut / Fade / Stinger per take on the Director Panel; the chosen transition is applied to director-initiated scene switches via OBS-WebSocket.

**Architecture:** Extend `obs_ws.set_current_program_scene` to optionally set the scene transition + duration (resolved from `GetSceneTransitionList` by transition *kind*) before switching; thread an optional `{transition, duration}` through the director-gated relay `/obs/scene` endpoint; add a sticky Cut/Fade/Stinger + duration bar to the Director Panel that sends the active choice with every scene switch (scene bus + macro scene step). Automated feed-handover/auto-failover switches stay hard cuts.

**Tech Stack:** Python 3 stdlib (`obs_ws` single-shot OBS-WebSocket session); the relay `ThreadingHTTPServer`; the Director Panel HTML/JS (`obsPost` fetch shim).

## Global Constraints

- **Edit only under `src/` and `tests/`** (plus `docs/`). English only; stdlib only.
- **No secrets / machine paths / real IPs** in committed files (Tailscale test IPs are `100.64.0.0/10`).
- **Never raises:** `obs_ws` keeps its best-effort `(ok, note)` contract — any failure returns `(False, note)` / carries a note; the relay keeps its 200/503 contract. No new exception surface.
- **Automated cuts stay hard cuts:** only director-manual scene switches (`/obs/scene`) carry a transition. `reflect_feed_state` (feed A/B handover) and auto-failover pass NO transition and are unchanged.
- **Backward compatible:** `set_current_program_scene(scene)` with no transition and `POST /obs/scene {scene}` with no `transition` behave exactly as today.
- **Policy unchanged:** every `/obs/*` path already resolves to `console_policy.Requirement(DIRECTOR, False)`; the transition param inherits it — do NOT touch `console_policy.py`.
- **Resolve by kind:** map `cut→cut_transition`, `fade→fade_transition`, `stinger→stinger_transition` (name fallback "Cut"/"Fade" for cut/fade). Stinger with none configured → degrade to Cut + a note ("no Stinger configured in OBS; used Cut"); never block the switch.
- **Default active transition = Fade, default duration = 300 ms.** Cut is instant (duration forced 0). Duration clamped 0–10000 ms.
- Test files end with a bare `run()` under `if __name__ == "__main__":` — never `sys.exit(run())`.
- Director Panel changed ⇒ `src/docs/wiki/images/director-panel.png` refreshed in the same PR (hard rule).

## File Structure

- **Modify `src/scripts/obs_ws.py`** — pure `resolve_transition`; extend `set_current_program_scene` with `transition`/`duration_ms`.
- **Modify `src/relay/racecast-feeds.py`** — `/obs/scene` reads optional `{transition, duration}`, clamps, forwards, returns the note.
- **Modify `src/director/director-panel.html`** — transition bar (Cut/Fade/Stinger + duration), sticky state, `obsScene` includes it, note surfaced.
- **Modify `tests/test_obsws.py`** — `resolve_transition` + transition-aware `set_current_program_scene`.
- **Modify `tests/test_console_gate.py`** — `/obs/scene` with a transition still director-gated + forwarded.
- **Modify `src/docs/wiki/`** — Director-Panel/console page: the transition bar + Stinger-needs-OBS-setup note.
- **Add `src/docs/wiki/images/director-panel.png`** — refreshed screenshot (Task 3b).

---

### Task 1: obs_ws — transition resolution + transition-aware scene switch

**Files:**
- Modify: `src/scripts/obs_ws.py`
- Test: `tests/test_obsws.py`

**Interfaces produced (used by Task 2):**
- `resolve_transition(choice, transitions) -> (name: str|None, note: str)` — pure.
- `set_current_program_scene(scene, host="127.0.0.1", port=None, password=None, timeout=2.0, transition=None, duration_ms=None) -> (ok, note)` — `transition ∈ {None,"cut","fade","stinger"}`.

- [ ] **Step 1: Write the failing test** — add to `tests/test_obsws.py` (keep its bare-`run()` footer):

```python
def t_resolve_transition_by_kind_and_fallback():
    tlist = [{"transitionName": "Cut", "transitionKind": "cut_transition"},
             {"transitionName": "Fade", "transitionKind": "fade_transition"},
             {"transitionName": "My Wipe", "transitionKind": "stinger_transition"}]
    assert m.resolve_transition("cut", tlist) == ("Cut", "")
    assert m.resolve_transition("fade", tlist) == ("Fade", "")
    # stinger resolves by KIND regardless of the name
    assert m.resolve_transition("stinger", tlist) == ("My Wipe", "")
    # name fallback when kind missing (older OBS payloads without kinds)
    nokind = [{"transitionName": "Fade", "transitionKind": ""}]
    assert m.resolve_transition("fade", nokind) == ("Fade", "")
    # stinger absent -> None + note
    name, note = m.resolve_transition("stinger", [{"transitionName": "Cut",
                                                   "transitionKind": "cut_transition"}])
    assert name is None and "Stinger" in note


def t_set_scene_with_fade_sets_transition_then_switches():
    sess = _FakeSession(responses={"GetSceneTransitionList": {"transitions": [
        {"transitionName": "Fade", "transitionKind": "fade_transition"},
        {"transitionName": "Cut", "transitionKind": "cut_transition"}]}})
    orig, m._connect = m._connect, lambda *a, **k: (sess, "")
    try:
        ok, note = m.set_current_program_scene("Stint", transition="fade", duration_ms=500)
    finally:
        m._connect = orig
    assert ok is True and note == ""
    types = [t for t, _ in sess.sent]
    # order: list transitions, set transition, set duration, then switch
    assert types.index("SetCurrentSceneTransition") < types.index("SetCurrentProgramScene")
    assert ("SetCurrentSceneTransition", {"transitionName": "Fade"}) in sess.sent
    assert ("SetCurrentSceneTransitionDuration", {"transitionDuration": 500}) in sess.sent
    assert ("SetCurrentProgramScene", {"sceneName": "Stint"}) in sess.sent


def t_set_scene_cut_sets_cut_no_duration():
    sess = _FakeSession(responses={"GetSceneTransitionList": {"transitions": [
        {"transitionName": "Cut", "transitionKind": "cut_transition"}]}})
    orig, m._connect = m._connect, lambda *a, **k: (sess, "")
    try:
        m.set_current_program_scene("Stint", transition="cut", duration_ms=500)
    finally:
        m._connect = orig
    assert ("SetCurrentSceneTransition", {"transitionName": "Cut"}) in sess.sent
    # cut is instant — no duration call
    assert all(t != "SetCurrentSceneTransitionDuration" for t, _ in sess.sent)


def t_set_scene_stinger_absent_degrades_to_cut_with_note():
    sess = _FakeSession(responses={"GetSceneTransitionList": {"transitions": [
        {"transitionName": "Cut", "transitionKind": "cut_transition"},
        {"transitionName": "Fade", "transitionKind": "fade_transition"}]}})
    orig, m._connect = m._connect, lambda *a, **k: (sess, "")
    try:
        ok, note = m.set_current_program_scene("Stint", transition="stinger", duration_ms=300)
    finally:
        m._connect = orig
    assert ok is True and "Stinger" in note
    assert ("SetCurrentSceneTransition", {"transitionName": "Cut"}) in sess.sent   # fell back
    assert ("SetCurrentProgramScene", {"sceneName": "Stint"}) in sess.sent


def t_set_scene_no_transition_is_plain_switch():
    sess = _FakeSession()
    orig, m._connect = m._connect, lambda *a, **k: (sess, "")
    try:
        m.set_current_program_scene("Stint")
    finally:
        m._connect = orig
    types = [t for t, _ in sess.sent]
    assert "GetSceneTransitionList" not in types and "SetCurrentSceneTransition" not in types
    assert ("SetCurrentProgramScene", {"sceneName": "Stint"}) in sess.sent
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_obsws.py`
Expected: FAIL — `resolve_transition` missing / `set_current_program_scene` has no `transition` kwarg.

- [ ] **Step 3: Implement** — in `src/scripts/obs_ws.py`:

3a. Add the pure resolver near the top-level helpers (e.g. above `set_current_program_scene`):
```python
_TRANSITION_KIND = {"cut": "cut_transition", "fade": "fade_transition",
                    "stinger": "stinger_transition"}
_TRANSITION_NAME_FALLBACK = {"cut": "cut", "fade": "fade"}


def resolve_transition(choice, transitions):
    """Resolve a director choice ('cut'|'fade'|'stinger') to a concrete OBS
    transition NAME, matched by kind against a GetSceneTransitionList payload
    (list of {transitionName, transitionKind}); falls back to a case-insensitive
    name match for cut/fade. Returns (name|None, note). Stinger with none
    configured -> (None, note). Pure; never raises."""
    kind = _TRANSITION_KIND.get(choice)
    for t in transitions or []:
        if kind and t.get("transitionKind") == kind:
            return (t.get("transitionName"), "")
    fb = _TRANSITION_NAME_FALLBACK.get(choice)
    if fb:
        for t in transitions or []:
            if (t.get("transitionName") or "").lower() == fb:
                return (t.get("transitionName"), "")
    if choice == "stinger":
        return (None, "no Stinger configured in OBS; used Cut")
    return (None, "")
```

3b. Extend `set_current_program_scene` (add the two kwargs + the set-transition-then-switch body). Replace the existing function with:
```python
def set_current_program_scene(scene, host="127.0.0.1", port=None,
                              password=None, timeout=2.0,
                              transition=None, duration_ms=None):
    """Switch the OBS program scene (best effort). When `transition`
    ('cut'|'fade'|'stinger') is given, set that transition (resolved by kind via
    GetSceneTransitionList) + duration first, then switch — so a director take
    uses the chosen transition. Stinger with none configured degrades to Cut and
    returns a note. (ok, note); never raises."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    out_note = ""
    try:
        if transition:
            tlist = session.request("GetSceneTransitionList", {}).get("transitions", [])
            name, resolve_note = resolve_transition(transition, tlist)
            if name is None and transition == "stinger":
                name, _ = resolve_transition("cut", tlist)     # degrade to a cut
                out_note = resolve_note
            if name:
                session.request("SetCurrentSceneTransition", {"transitionName": name})
                if transition != "cut" and duration_ms is not None:
                    session.request("SetCurrentSceneTransitionDuration",
                                    {"transitionDuration": int(duration_ms)})
        session.request("SetCurrentProgramScene", {"sceneName": scene})
        return True, out_note
    except Exception as exc:                          # noqa: BLE001 — best-effort contract
        return False, str(exc) or exc.__class__.__name__
    finally:
        session.close()
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_obsws.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint** — `python3 tools/lint.py` → exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): per-take transition on the scene switch (resolve by kind)"
```

---

### Task 2: Relay `/obs/scene` transition passthrough

**Files:**
- Modify: `src/relay/racecast-feeds.py` (the `/obs/scene` branch in `do_POST`)
- Test: `tests/test_console_gate.py`

**Interfaces:**
- Consumes: `_obs_ws.set_current_program_scene(scene, transition=..., duration_ms=...)` (Task 1).

- [ ] **Step 1: Write the failing test** — add to `tests/test_console_gate.py` (match its real relay-handler harness — read the file first; it already POSTs `/console/obs/scene` and has a director token. The key assertion: a `transition`+`duration` body reaches `_obs_ws` with the clamped duration). Concretely, monkeypatch the relay module's `_obs_ws` with a capturing fake:

```python
def t_obs_scene_forwards_transition_and_clamps_duration():
    # m is the loaded relay module (as elsewhere in this file); build the same
    # director-authed handler used by t_console_obs_scene_requires_director.
    calls = {}

    class _FakeObs:
        def set_current_program_scene(self, scene, transition=None, duration_ms=None):
            calls["args"] = (scene, transition, duration_ms)
            return True, ""
    orig, m._obs_ws = m._obs_ws, _FakeObs()
    try:
        # POST /console/obs/scene as the director with an over-range duration
        code, body = _post_console(m, "/console/obs/scene",
                                   {"scene": "Stint", "transition": "fade",
                                    "duration": 999999},
                                   token=_director_token(m))
        assert code == 200, (code, body)
        assert calls["args"][0] == "Stint" and calls["args"][1] == "fade"
        assert calls["args"][2] == 10000        # clamped to the 0..10000 ceiling
    finally:
        m._obs_ws = orig
```
Adapt `_post_console` / `_director_token` to the real helpers in `tests/test_console_gate.py` (it already mints a director token `bob` and POSTs to `/console/obs/scene` in `t_console_obs_scene_requires_director`). The assertion that matters: the endpoint forwards `transition` and a clamped `duration_ms`.

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_console_gate.py`
Expected: FAIL — the endpoint ignores `transition`/`duration`.

- [ ] **Step 3: Implement** — in `src/relay/racecast-feeds.py`, replace the `/obs/scene` branch body with:
```python
                if p == ["obs", "scene"]:
                    if _obs_ws is None:
                        return self._send({"error": "obs unavailable"}, 503)
                    transition = body.get("transition")
                    duration = body.get("duration")
                    if duration is not None:
                        try:
                            duration = max(0, min(10000, int(duration)))
                        except (TypeError, ValueError):
                            duration = None
                    ok, note = _obs_ws.set_current_program_scene(
                        body.get("scene"), transition=transition, duration_ms=duration)
                    if not ok:
                        return self._send({"ok": False, "error": note}, 503)
                    return self._send({"ok": True, "note": note} if note
                                      else {"ok": True})
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_console_gate.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Regression + lint**

Run: `python3 tests/test_console.py && python3 tests/test_pov.py && python3 tools/lint.py`
Expected: pass / exit 0 (policy + relay import intact).

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_console_gate.py
git commit -m "feat(relay): /obs/scene accepts a per-take transition + duration"
```

---

### Task 3: Director Panel transition bar

**Files:**
- Modify: `src/director/director-panel.html`

**Interfaces:**
- Consumes: `POST /obs/scene {scene, transition, duration}` (Task 2).

- [ ] **Step 1: Add the transition bar markup.** In `src/director/director-panel.html`, add a transition bar immediately before the scene bus (`#scnBus`). Read the file first to match the surrounding bus/section markup and classes; the bar has three toggle buttons + a duration input:
```html
      <div class="bus" id="txBar" title="Transition applied to the next scene switch">
        <span class="buslabel">Transition</span>
        <button class="k tx" data-tx="cut">CUT</button>
        <button class="k tx" data-tx="fade">FADE</button>
        <button class="k tx" data-tx="stinger">STINGER</button>
        <label class="txdur">dur <input id="txDur" type="number" min="0" max="10000"
               step="50" value="300"> ms</label>
      </div>
```
(Use the file's existing bus/label/button class names if they differ — match `#scnBus`'s section.)

- [ ] **Step 2: Sticky state + wiring.** In the panel script, add the sticky state + a renderer, default **fade / 300**, and make `obsScene` include the active transition. Replace the `obsScene` arrow with a function and add the bar wiring:
```javascript
let activeTransition = "fade";
let activeDuration = 300;

function renderTxBar(){
  document.querySelectorAll('#txBar .tx').forEach(b =>
    b.classList.toggle('active', b.dataset.tx === activeTransition));
  const dur = $("#txDur");
  if (dur) dur.disabled = (activeTransition === "cut");
}
document.querySelectorAll('#txBar .tx').forEach(b =>
  b.addEventListener('click', () => { activeTransition = b.dataset.tx; renderTxBar(); }));
{ const d = $("#txDur"); if (d) d.addEventListener('change', () => {
    const v = parseInt(d.value, 10);
    activeDuration = isNaN(v) ? 300 : Math.max(0, Math.min(10000, v)); d.value = activeDuration; }); }
renderTxBar();

async function obsScene(scene){
  const d = await obsPost("scene", {scene, transition: activeTransition,
    duration: activeTransition === "cut" ? 0 : activeDuration});
  if (d && d.note) log(d.note, "warn");     // e.g. stinger not configured -> used cut
  return d;
}
```
(Delete the old `const obsScene = (scene) => obsPost("scene", {scene});` line. `runMacro`'s scene step already calls `obsScene(m.scene)`, so macros pick up the active transition automatically; source/audio steps are unchanged.)

- [ ] **Step 3: Style the active state + duration field.** Add CSS near the other `.k`/`.bus` rules (match the file's existing active-button styling — grep for `.active`):
```css
    #txBar .tx.active { outline: 2px solid #4fa3ff; }
    #txBar .txdur { margin-left: 8px; font-size: 12px; opacity: .85; }
    #txBar .txdur input { width: 64px; }
```
(If the panel already has an `.active` convention for `.k` buttons, reuse it instead of `outline` so it looks native.)

- [ ] **Step 4: Verify the panel loads + relay routing intact.**

Run: `python3 tests/test_racecast.py`
Expected: `ALL PASS` (no server-side change here; sanity that nothing broke).

Manually confirm the HTML parses (no server restart needed — the panel is read per request): open `/panel` in the demo dev build (Task 3b captures it).

- [ ] **Step 5: Lint** — `python3 tools/lint.py` → exit 0 (HTML isn't linted, but run to be safe if any .py touched; here none).

- [ ] **Step 6: Commit (code only — screenshot is Task 3b)**

```bash
git add src/director/director-panel.html
git commit -m "feat(panel): Cut/Fade/Stinger per-take transition bar (default Fade)"
```

---

### Task 3b: Refresh `director-panel.png` (screenshot — blocking hard rule)

**Files:** Replace `src/docs/wiki/images/director-panel.png`

- [ ] **Step 1:** Use the `wiki-screenshots` skill. Boot a demo relay against `tools/obs-sim.py` (per the skill's Part B recipe) so `/panel` renders with content, on the demo profile + dev build. Mint a director token if the panel is reached via `/console/panel`, or open the tailnet `/panel` directly.
- [ ] **Step 2:** Drive the Playwright MCP to the Director Panel; confirm the new **Transition** bar (CUT · FADE · STINGER + duration, FADE active by default) is visible near the scene bus. Take the screenshot matching the existing `director-panel.png` framing (element or full-page as the existing image uses). Save to `src/docs/wiki/images/director-panel.png`.
- [ ] **Step 3:** Clean up per the skill: `relay stop`; `git checkout -- profiles/demo/profile.env` (the demo relay writes `CONSOLE_SECRET` — revert it); remove the stub cookies + any scratch PNG in the repo root; stop obs-sim.
- [ ] **Step 4:** Commit:
```bash
git add src/docs/wiki/images/director-panel.png
git commit -m "docs: refresh Director Panel screenshot with the transition bar"
```

---

### Task 4: Docs

**Files:** `src/docs/wiki/` (the Director-Panel / console page)

- [ ] **Step 1:** Find the wiki page documenting the Director Panel (grep `src/docs/wiki/` for "Director" / "director-panel.png"). Add a short **Transition** subsection: the bar picks Cut / Fade / Stinger for the next scene switch (sticky; default Fade; duration in ms; Cut is instant). State that it applies to scene switches (scene bus + macros), not source toggles, and that **Stinger requires the producer to configure a Stinger transition in OBS** — Cut and Fade always work; if no Stinger is configured the take falls back to a cut.
- [ ] **Step 2:** Validate wiki links: `python3 tests/test_wiki.py` → `ALL PASS`.
- [ ] **Step 3:** Commit:
```bash
git add src/docs/wiki
git commit -m "docs(obs): document the Director Panel transition bar"
```

---

## Final verification (before the PR)

- [ ] `python3 tools/run-tests.py` — whole suite green (`test_obsws.py`, `test_console_gate.py`, `test_console.py`, `test_pov.py`, `test_wiki.py`).
- [ ] `python3 tools/lint.py` — exit 0.
- [ ] `python3 tools/build.py` — exit 0.
- [ ] `director-panel.png` committed; `profiles/demo/profile.env` secret-free; no scratch files.

## Self-Review (author checklist — completed)

1. **Spec coverage:** resolve-by-kind + set-then-switch → Task 1; stinger degradation → Task 1 (`resolve_transition` + fallback in `set_current_program_scene`); relay passthrough + clamp + note → Task 2; policy unchanged (no `console_policy.py` edit) → constraints; sticky Cut/Fade/Stinger bar, default Fade/300, applies to scene bus + macros → Task 3; automated cuts unchanged (no edit to `reflect_feed_state`/auto-failover) → constraints; backward compat (no-transition path) → Task 1/Task 2; screenshot → Task 3b; docs incl. Stinger-needs-OBS-setup → Task 4.
2. **Placeholder scan:** none; every code step carries complete code. The Task-2 test + Task-3 markup/CSS explicitly instruct matching the real `tests/test_console_gate.py` helpers and the panel's existing bus/active classes (must be read from those files); the asserted behavior is concrete.
3. **Type consistency:** `set_current_program_scene(scene, ..., transition, duration_ms)` signature matches its relay call (`transition=`, `duration_ms=`) and the tests; `resolve_transition(choice, transitions) -> (name|None, note)` matches its use inside `set_current_program_scene`; `/obs/scene` body keys `transition`/`duration` match the panel's `obsPost("scene", {scene, transition, duration})`.
