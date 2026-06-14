# Visual Builder timer-merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold the race timer into the main HUD overlay so the visual builder is a true 1:1 WYSIWYG (one page, one CSS, one OBS source), give the POV box live background/border controls aligned to the real OBS box, and pre-fill the property panel from the template.

**Architecture:** The timer stops being its own page/CSS/OBS source; the clock becomes one more absolutely-positioned slot inside `hud.html` at its true on-air geometry, polling the unchanged `/timer/data` state. The overlay builder collapses to a single `hud` page; properties pre-fill from the rendered canvas's computed style and Save writes a full per-slot snapshot. The OBS collection drops the `HUD Race Timer` source and reorders `HUD Overlay` above `Feed POV`.

**Tech Stack:** Pure Python stdlib (no framework), stdlib-only runnable test scripts (`tests/test_*.py`), vanilla-JS Control Center (`src/ui/control-center.html`), OBS scene-collection JSON.

---

## File Structure

- `src/scripts/overlay_build.py` — pure compiler; gains border props, drops the `timer` page from `SAMPLE`.
- `src/obs/hud.html` — gains the `#clock` slot (markup + base CSS + a `/timer/data` poll loop); `#pov` default position fixed + border/background props.
- `src/obs/timer.html` — **deleted** (merged into hud).
- `src/relay/racecast-feeds.py` — drop the `/timer` page route + `/timer/override.css`; keep all timer *state* endpoints; stop loading `timer.html`; narrow `read_overlay_css` to `hud`.
- `src/racecast.py` — `OBS_PAGE_PATHS` drops the timer entries; overlay data-layer funcs narrow to the single `hud` page + fold a legacy `timer.css` into `customCss` once.
- `src/ui/ui_server.py` — overlay routes always operate on `hud`.
- `src/ui/control-center.html` — remove HUD/Timer tabs; prefill from `getComputedStyle`; Save-all; POV panel fields; border keys in the JS CSS map.
- `src/obs/GT_Endurance.json` — remove the `HUD Race Timer` source + scene items; reorder `HUD Overlay` above `Feed POV`.
- `tools/build.py` — stop shipping `timer.html`; update verify checks.
- `tests/test_overlay.py`, `tests/test_racecast.py`, `tests/test_timer.py`, `tests/test_hud.py` — updated/added.

**Commit cadence:** one commit per task (after its tests pass). Branch `feat/builder-timer-merge` is already checked out.

---

### Task 1: Compiler — POV border properties

**Files:**
- Modify: `src/scripts/overlay_build.py` (the `_PX_PROPS`, `_TEXT_PROPS`, `PROP_ORDER` tables + `_declaration`)
- Test: `tests/test_overlay.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_overlay.py` (before the `if __name__` runner). `POVSLOTS` mirrors the `#pov` allowed props:

```python
POVSLOTS = [{"id": "pov", "label": "POV box",
             "props": ["left", "top", "width", "height",
                       "background", "borderStyle", "borderColor", "borderWidth"]}]

def t_ob_compile_pov_border_and_background():
    css = ob.compile_overlay_css(
        {"slots": {"pov": {"background": "#0b0f1a", "borderStyle": "solid",
                           "borderColor": "#ff2a2a", "borderWidth": 4}}}, POVSLOTS)
    assert "#pov {" in css
    assert "background: #0b0f1a" in css
    assert "border-style: solid" in css
    assert "border-color: #ff2a2a" in css
    assert "border-width: 4px" in css

def t_ob_compile_border_width_is_px_gated():
    # borderWidth is numeric-only (px), like the other geometry props
    css = ob.compile_overlay_css({"slots": {"pov": {"borderWidth": "4; }#x{a:b"}}}, POVSLOTS)
    assert "border-width" not in css

def t_ob_compile_border_props_respect_allowed():
    # a text slot that does NOT allow border props must not emit them
    slots = [{"id": "stint", "label": "S", "props": list(ob.DEFAULT_PROPS)}]
    css = ob.compile_overlay_css({"slots": {"stint": {"borderStyle": "solid"}}}, slots)
    assert "border-style" not in css
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_overlay.py`
Expected: FAIL (e.g. `border-style` not found in css / `#pov {` missing).

- [ ] **Step 3: Implement** — in `src/scripts/overlay_build.py`:

Add `borderWidth` to the px map:
```python
_PX_PROPS = {
    "left": "left", "top": "top", "width": "width", "height": "height",
    "fontSize": "font-size", "borderWidth": "border-width",
    "teamNameMax": "--team-name-max", "teamNameMin": "--team-name-min",
}
```
Add the two color-ish border props to the text map:
```python
_TEXT_PROPS = {"color": "color", "background": "background",
               "borderColor": "border-color", "borderStyle": "border-style"}
```
Add the new keys to the stable emit order (insert after `background`):
```python
PROP_ORDER = ("left", "top", "width", "height", "fontSize", "borderWidth",
              "teamNameMax", "teamNameMin", "fontFamily", "color",
              "background", "borderColor", "borderStyle", "align")
```
`borderStyle` is a bare keyword (`solid`/`dashed`/…). `_declaration` already routes `_TEXT_PROPS` through `_safe_value` (which rejects `;{}<>`), so `border-style: solid` is safe and `solid; }#x` is rejected. No change to `_declaration` needed.

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_overlay.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/overlay_build.py tests/test_overlay.py
git commit -m "feat(overlay): compiler supports POV background + border props

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Compiler — move the clock sample into the HUD page

**Files:**
- Modify: `src/scripts/overlay_build.py` (`SAMPLE`)
- Test: `tests/test_overlay.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_overlay.py`:

```python
def t_ob_sample_has_clock_in_hud_only():
    assert ob.SAMPLE["hud"].get("clock") == "1:23:45"
    assert "timer" not in ob.SAMPLE      # timer page is merged into hud
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_overlay.py`
Expected: FAIL (`KeyError`/assert — `SAMPLE["hud"]` has no `clock`, and `timer` key still present).

- [ ] **Step 3: Implement** — in `SAMPLE`, add `"clock": "1:23:45"` to the `hud` dict and delete the whole `"timer": {...}` entry:

```python
SAMPLE = {
    "hud": {
        "stint": "STINT 3", "session": "Race",
        "streamer": "twitch.tv/commentary",
        "round-top": "Round 4", "round-country": "Belgium",
        "team1-num": "7", "team1-name": "Team Redline",
        "team2-num": "23", "team2-name": "Apex Racing",
        "team3-num": "99", "team3-name": "Night Shift Motorsport",
        "race-control": "FCY — Full Course Yellow",
        "clock": "1:23:45",
    },
}
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_overlay.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/overlay_build.py tests/test_overlay.py
git commit -m "feat(overlay): clock sample moves into the merged HUD page

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: HUD page — add the clock slot, fix the POV box

**Files:**
- Modify: `src/obs/hud.html` (base `<style>`, body markup, the poll script)
- Test: `tests/test_overlay.py` (replace the two timer-page tests with hud-page equivalents)

- [ ] **Step 1: Replace the failing timer-page tests** — in `tests/test_overlay.py`, **delete** `t_ob_extract_slots_from_real_timer` and `t_timer_clock_base_is_finite_positionable` (they read the now-removed `timer.html`) and **add** these hud-based tests:

```python
def t_ob_hud_has_clock_slot():
    with open(os.path.join(ROOT, "src", "obs", "hud.html"), encoding="utf-8") as f:
        slots = ob.extract_slots(f.read())
    ids = [s["id"] for s in slots]
    assert "clock" in ids
    clock = next(s for s in slots if s["id"] == "clock")
    assert clock["label"] == "Clock"
    assert "left" in clock["props"] and "fontSize" in clock["props"]

def t_ob_hud_clock_base_is_finite_positionable():
    # Regression for #135 carried into the merged page: the clock hugs its digits,
    # it is not a full-canvas centered box (dragging that moves nothing visibly).
    with open(os.path.join(ROOT, "src", "obs", "hud.html"), encoding="utf-8") as f:
        style = ob.base_style(f.read())
    clock_rule = re.search(r"#clock\s*\{[^}]*\}", style).group(0)
    assert "1920px" not in clock_rule, "clock must not span the full canvas width"

def t_ob_hud_pov_has_border_props_and_obs_position():
    with open(os.path.join(ROOT, "src", "obs", "hud.html"), encoding="utf-8") as f:
        html = f.read()
    pov = next(s for s in ob.extract_slots(html) if s["id"] == "pov")
    for p in ("background", "borderStyle", "borderColor", "borderWidth"):
        assert p in pov["props"], p
    pov_rule = re.search(r"#pov\s*\{[^}]*\}", ob.base_style(html)).group(0)
    # aligned to the OBS Feed POV box (pos 1496,644 bounds 384x216)
    assert "1496px" in pov_rule and "644px" in pov_rule
    assert "384px" in pov_rule and "216px" in pov_rule
```

Also update `t_read_overlay_css_timer_present` (it asserts the relay serves a `timer` override) and `t_read_overlay_css_rejects_unknown_page` — see Task 4 (they depend on the relay change). For now leave them; Task 4 fixes them.

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_overlay.py`
Expected: FAIL (`#clock` not in slots; `#pov` lacks border props / wrong position).

- [ ] **Step 3: Implement `src/obs/hud.html`**

(a) In `<style>`, replace the POV rule and add a clock rule. Replace:
```css
  #pov { left: 40px; top: 560px; width: 480px; height: 270px; }
```
with:
```css
  /* POV picture-in-picture frame (issue #141): aligned to the OBS "Feed POV"
     scene item (pos 1496,644, bounds 384x216). Transparent by default — set a
     background/border in the overlay builder to frame the PiP on air. */
  #pov { left: 1496px; top: 644px; width: 384px; height: 216px; }

  /* Race-timer clock, merged in from the old separate timer source. Sits at the
     "Feed POV"-free top band at the clock's true on-air size/position (was OBS
     crop y[217..895] + scale 0.0854 + pos 880,98). Tune live via the builder. */
  #clock { left: 889px; top: 98px; height: 58px;
    display: flex; align-items: center; white-space: nowrap;
    font-family: "SF Mono", "Cascadia Mono", "Consolas", "Menlo", monospace;
    font-weight: 700; font-size: 36px; color: #ffffff;
    text-shadow: 0 2px 6px rgba(0,0,0,.6); font-variant-numeric: tabular-nums; }
```

(b) In `<body>`, add the clock slot next to `#pov` (give the POV box its new props):
```html
  <div id="race-control" class="el white" data-edit="Race control"></div>
  <div id="pov" class="el" data-edit="POV box" data-edit-props="left,top,width,height,background,borderStyle,borderColor,borderWidth"></div>
  <div id="clock" class="el white" data-edit="Clock"></div>
```
(`#clock` keeps the default text-slot prop set — no `data-edit-props` attribute.)

(c) In `<script>`, add a second poll loop for the clock. Add the constants and ticker near the top of the script (after `const POLL_MS = 2500;`):
```javascript
  const TIMER_POLL_MS = 2000, TIMER_TICK_MS = 250;
  let timerState = null, clockOffset = 0;   // serverNow - clientNow at last poll

  function fmtClock(s) {
    s = Math.max(0, Math.ceil(s));
    const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
    return `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}`;
  }
  function renderClock() {
    const el = document.getElementById("clock");
    if (!timerState || !timerState.visible) { el.textContent = ""; el.classList.add("empty"); return; }
    let text;
    if (timerState.end === null) {
      const s = (timerState.remaining_s ?? null) !== null ? timerState.remaining_s : timerState.duration_s;
      text = fmtClock(s);
    } else {
      const remaining = timerState.end - (Date.now() / 1000 + clockOffset);
      text = remaining > 0 ? fmtClock(remaining) : "";
    }
    el.textContent = text;
    el.classList.toggle("empty", !text);
  }
  async function pollClock() {
    try {
      const r = await fetch("/timer/data", { cache: "no-store" });
      const d = await r.json();
      if (!d.error) { timerState = d; clockOffset = d.server_now - Date.now() / 1000; }
    } catch (e) { /* keep last good state on transient errors */ }
  }
```
And start them next to the existing `tick()` calls at the bottom of the script:
```javascript
  tick();
  setInterval(tick, POLL_MS);
  pollClock();
  setInterval(pollClock, TIMER_POLL_MS);
  setInterval(renderClock, TIMER_TICK_MS);
```
(These mirror the deleted `timer.html` logic verbatim, so the clock behaves identically — local tick against the end anchor, re-sync on poll, blank when not visible.)

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_overlay.py`
Expected: `ALL PASS` for the new hud tests (the two `t_read_overlay_css_*timer*` tests may still fail — fixed in Task 4).

- [ ] **Step 5: Commit**

```bash
git add src/obs/hud.html tests/test_overlay.py
git commit -m "feat(hud): merge race-timer clock into the HUD page; fix POV box

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Relay — drop the timer page, keep timer state

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`do_GET` routing, `read_overlay_css`, the `timer_path` block, `--no-timer` help, startup prints, `make_handler` signature)
- Delete: `src/obs/timer.html`
- Test: `tests/test_overlay.py` (the two `read_overlay_css` timer tests)

- [ ] **Step 1: Update the failing relay tests** — in `tests/test_overlay.py`:

Replace `t_read_overlay_css_timer_present` with a test that `timer` is now rejected, and extend the unknown-page test:
```python
def t_read_overlay_css_timer_is_now_unknown():
    # the timer page is merged into the HUD — "timer" is no longer an overlay page
    with tempfile.TemporaryDirectory() as tmp:
        od = _mkoverlay(tmp, hud_css="#stint{left:10px}")
        assert feeds.read_overlay_css(od, "timer") == b""
```
Leave `t_read_overlay_css_rejects_unknown_page` as-is (it already expects `b""` for an unknown page).

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_overlay.py`
Expected: FAIL — `read_overlay_css(od, "timer")` currently returns the timer override bytes / accepts `timer`.

- [ ] **Step 3: Implement `src/relay/racecast-feeds.py`**

(a) `read_overlay_css` (~line 294): narrow the accepted page set to `hud` only. Whatever the current allow-list is (e.g. `if page not in ("hud", "timer")`), change it to `if page != "hud": return b""`.

(b) In `do_GET`, **delete** the timer override route:
```python
                if p == ["timer", "override.css"]:
                    return self._send_css(read_overlay_css(overlay_dir, "timer"))
```
and **delete** the timer *page* branch inside the `["timer"]` block (keep everything else):
```python
                    if p == ["timer"]:
                        if not timer_path: return self._send({"error": "timer disabled"}, 404)
                        return self._send_file(timer_path, "text/html; charset=utf-8")
```
The `["timer", "data"]`, `start`, `stop`, `reset`, `show`, `hide`, `set`, `adjust` branches stay unchanged.

(c) Remove `timer_path` from `make_handler`'s signature (line ~2093) and from the `make_handler(...)` call (line ~2642). Remove the `timer_path = None` / `for cand in (... "timer.html" ...)` discovery block (lines ~2590–2605) — keep `timer_store` and its poller thread. `--no-timer` now only gates `timer_store`.

(d) Update the `--no-timer` help text (line ~2453):
```python
    ap.add_argument("--no-timer", action="store_true",
                    help="Do not run the race timer (the HUD clock stays blank; "
                         "/timer/data and the /timer controls are disabled).")
```

(e) Update the startup print (lines ~2711) — drop the standalone `/timer` page line; the timer is part of `/hud`:
```python
        print(f"  HUD overlay incl. race timer (OBS source): "
              f"http://127.0.0.1:{args.http_port}/hud")
        print(f"  Timer controls: /timer/start | /timer/stop | /timer/reset "
              f"(tab '{args.timer_tab}', {push})")
```
(Adjust to the surrounding f-string style; keep the `push`/`args.timer_tab` references already in scope.)

(f) Update the module docstring lines ~60: drop `GET /timer -> race-timer browser-source page`; keep the `/timer/data` + control lines.

(g) Delete the file:
```bash
git rm src/obs/timer.html
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_overlay.py && python3 tests/test_pov.py && python3 tests/test_timer.py`
Expected: `ALL PASS` (timer *state* tests still green; overlay timer page rejected).

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_overlay.py
git rm src/obs/timer.html
git commit -m "feat(relay): drop the standalone /timer page; clock lives in /hud

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: racecast.py — OBS_PAGE_PATHS + single overlay page

**Files:**
- Modify: `src/racecast.py` (`OBS_PAGE_PATHS`, `_active_profile_overlay_path`, `_overlay_base_html`, the obs-refresh skip message)
- Test: `tests/test_racecast.py`

- [ ] **Step 1: Update the failing tests** — in `tests/test_racecast.py`:

Line ~1262 — new tuple:
```python
    assert m.OBS_PAGE_PATHS == ("/hud", "/hud/override.css")
```
`t_served_pages_hash_concatenates_in_order` (~608) — drop `/timer` from the fixture so it matches the new `OBS_PAGE_PATHS`:
```python
    pages = {"/hud": b"HUD", "/hud/override.css": b"CSS"}
    expected = hashlib.sha256(b"HUD" + b"CSS").hexdigest()
    assert m.served_pages_hash(fetch=lambda p: pages[p]) == expected
```
(Check the test's existing hash construction and mirror it; the point is the fixture keys must equal `OBS_PAGE_PATHS`.)

`t_overlay_timer_write_then_read_roundtrip` (~993) — **delete** it (timer is no longer an overlay page). `t_overlay_rejects_unknown_page` should now also cover `timer`:
```python
            assert m.overlay_write_data("timer", "x")["ok"] is False
            assert m.overlay_write_data("panel", "x")["ok"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_racecast.py`
Expected: FAIL (`OBS_PAGE_PATHS` mismatch; `timer` still accepted).

- [ ] **Step 3: Implement `src/racecast.py`**

Line ~573:
```python
OBS_PAGE_PATHS = ("/hud", "/hud/override.css")
```
`_active_profile_overlay_path` (~2430) and `_overlay_base_html` (~2490): change `if page not in ("hud", "timer")` → `if page != "hud"` in both.
Line ~586 docstring and ~1062 skip message: replace `/hud + /timer` with `/hud`. The ~1062 line:
```python
        print("obs: page refresh skipped — could not read /hud from the relay.")
```
Line ~14 CLI banner comment `# force-reload the relay-served OBS browser sources (HUD/timer)` → `(HUD incl. timer)`.

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_racecast.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(obs-refresh): timer folded into /hud; OBS_PAGE_PATHS drops /timer

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Control Center data layer — single page + legacy timer.css fold

**Files:**
- Modify: `src/racecast.py` (`overlay_layout_read` — fold a legacy `timer.css`)
- Test: `tests/test_racecast.py`

Goal: when the builder loads the `hud` layout for a profile that still has a non-trivial hand-written `timer.css` (rules, not just the comment template), append it once into the hud layout's `customCss` so no styling is silently lost.

- [ ] **Step 1: Write the failing test** — add to `tests/test_racecast.py` near the other overlay tests (mirror their tmp-profile setup; reuse the existing helper that sets `RACECAST_PROFILE` + a `profiles/demo/overlay` dir):

```python
def t_overlay_layout_folds_legacy_timer_css():
    with _tmp_active_profile("demo") as (m, td):   # use the existing fixture helper
        od = os.path.join(td, "profiles", "demo", "overlay")
        os.makedirs(od, exist_ok=True)
        with open(os.path.join(od, "timer.css"), "w", encoding="utf-8") as f:
            f.write("#clock { color: #f4f4f4; }")     # a real rule, not a comment
        d = m.overlay_layout_read("hud")
        assert d["ok"] is True
        assert "#clock { color: #f4f4f4; }" in (d["layout"].get("customCss") or "")

def t_overlay_layout_ignores_comment_only_timer_css():
    with _tmp_active_profile("demo") as (m, td):
        od = os.path.join(td, "profiles", "demo", "overlay")
        os.makedirs(od, exist_ok=True)
        with open(os.path.join(od, "timer.css"), "w", encoding="utf-8") as f:
            f.write("/* just the template, no rules */\n")
        d = m.overlay_layout_read("hud")
        assert "just the template" not in (d["layout"].get("customCss") or "")
```
(If `_tmp_active_profile` does not exist under that name, copy the setup pattern from `t_overlay_write_then_read_roundtrip` which already builds a tmp profile and imports the module — name the helper to match what that test uses.)

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_racecast.py`
Expected: FAIL (legacy timer.css not folded).

- [ ] **Step 3: Implement** — add a tiny comment-stripping helper and the fold in `src/racecast.py`. Near the overlay layout helpers:

```python
def _css_has_rules(text):
    """True if `text` has real CSS once comments + whitespace are stripped."""
    return bool(re.sub(r"/\*.*?\*/", "", text or "", flags=re.S).strip())
```
In `overlay_layout_read(page)` (the function that returns `{ok, page, layout, migrated}`), after the layout dict is resolved and before returning, when `page == "hud"`, fold a legacy timer.css that carries real rules and isn't already present:
```python
        if page == "hud":
            active, css_path = _active_profile_overlay_path("hud")
            if active:
                timer_css = os.path.join(os.path.dirname(css_path), "timer.css")
                if os.path.exists(timer_css):
                    with open(timer_css, encoding="utf-8") as fh:
                        legacy = fh.read()
                    cur = layout.get("customCss") or ""
                    if _css_has_rules(legacy) and legacy.strip() not in cur:
                        layout["customCss"] = (cur + ("\n" if cur else "")
                                               + "/* merged from legacy timer.css */\n"
                                               + legacy)
                        result["migrated"] = True
```
(Adapt variable names — `layout`, `result` — to the function's actual locals; ensure `re` is imported at module top, which it already is.)

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_racecast.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(overlay): fold a legacy timer.css into the merged HUD layout

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: OBS collection — remove the timer source, reorder POV

**Files:**
- Modify: `src/obs/GT_Endurance.json`
- Test: `tests/test_overlay.py` (structural assertions on the shipped collection)

- [ ] **Step 1: Write the failing structural test** — append to `tests/test_overlay.py`:

```python
import json as _json
def t_obs_collection_has_no_timer_source():
    with open(os.path.join(ROOT, "src", "obs", "GT_Endurance.json"), encoding="utf-8") as f:
        col = _json.load(f)
    blob = _json.dumps(col)
    assert "HUD Race Timer" not in blob, "the separate timer source must be removed"
    assert "8088/timer" not in blob, "no scene item should point at the /timer page"
    # the HUD page source is still there
    assert "8088/hud" in blob

def t_obs_hud_overlay_above_feed_pov():
    # In every scene that has both, HUD Overlay must render in FRONT of Feed POV
    # so the HUD's #pov frame draws over the video. OBS renders index 0 = front.
    with open(os.path.join(ROOT, "src", "obs", "GT_Endurance.json"), encoding="utf-8") as f:
        col = _json.load(f)
    def items_of(src):
        return (src.get("settings") or {}).get("items") or []
    for src in col.get("sources", []):
        if src.get("id") not in ("scene", "group"):
            continue
        names = [it.get("name") for it in items_of(src)]
        if "HUD Overlay" in names and "Feed POV" in names:
            assert names.index("HUD Overlay") < names.index("Feed POV"), src.get("name")
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_overlay.py`
Expected: FAIL (`HUD Race Timer` present; `Feed POV` currently precedes `HUD Overlay`).

- [ ] **Step 3: Implement the JSON edit deterministically** — run this one-off transform (it preserves OBS's 4-space indent), then delete the script:

```bash
python3 - <<'PY'
import json
P = "src/obs/GT_Endurance.json"
col = json.load(open(P, encoding="utf-8"))

def items_of(src):
    s = src.get("settings")
    return s.get("items") if isinstance(s, dict) else None

for src in col.get("sources", []):
    items = items_of(src)
    if not items:
        continue
    # 1) remove every scene/group item named "HUD Race Timer"
    items[:] = [it for it in items if it.get("name") != "HUD Race Timer"]
    # 2) reorder: move "HUD Overlay" in FRONT of (before) "Feed POV"
    names = [it.get("name") for it in items]
    if "HUD Overlay" in names and "Feed POV" in names:
        oi, pi = names.index("HUD Overlay"), names.index("Feed POV")
        if oi > pi:
            it = items.pop(oi)
            items.insert(pi, it)

# 3) remove the top-level "HUD Race Timer" SOURCE definition
col["sources"] = [s for s in col.get("sources", []) if s.get("name") != "HUD Race Timer"]

json.dump(col, open(P, "w", encoding="utf-8"), indent=4, ensure_ascii=True)
open(P, "a").write("\n")
print("done")
PY
```
Then sanity-check tokenization still holds:
```bash
python3 tools/tokenize-obs.py --check src/obs/GT_Endurance.json 2>/dev/null || true
```
(If `tokenize-obs.py` has no `--check`, skip — the build verify in Task 10 is the gate.)

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_overlay.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/obs/GT_Endurance.json tests/test_overlay.py
git commit -m "feat(obs): drop the HUD Race Timer source; HUD Overlay above Feed POV

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: build.py — stop shipping timer.html, fix verify checks

**Files:**
- Modify: `tools/build.py`
- Test: `python3 tools/build.py` (its own verify step)

- [ ] **Step 1: Locate the timer references**

Run: `grep -n "timer" tools/build.py`
Expected: the `cp("obs/timer.html", "timer.html")` line (~61) and the two verify checks (~159, ~161, ~166).

- [ ] **Step 2: Implement** — in `tools/build.py`:

Delete the copy line:
```python
    cp("obs/timer.html", "timer.html")
```
In the verify `checks` dict, delete the timer-page checks and assert the clock is now in the HUD page instead:
```python
        "obs timer is relay-served": "http://127.0.0.1:8088/timer" in tpl
```
→ remove. Keep `"relay timer endpoint": "/timer/data" in relay` (the state endpoint still exists — verify the string is still in the relay source). Remove:
```python
        "timer html shipped": os.path.isfile(os.path.join(PKG, "timer.html")),
```
Add a check that the clock merged into the hud page (read `hud.html`, not `tpl`):
```python
        "hud serves the clock": '<div id="clock"' in open(
            os.path.join(PKG, "hud.html"), encoding="utf-8").read(),
```

- [ ] **Step 3: Run the build**

Run: `python3 tools/build.py`
Expected: build completes; verify prints all checks `ok` (no `timer.html` missing, clock present).

- [ ] **Step 4: Commit**

```bash
git add tools/build.py
git commit -m "build: stop shipping timer.html; verify the clock merged into hud

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Builder frontend — one page, prefill, save-all, POV fields

**Files:**
- Modify: `src/ui/control-center.html` (the overlay-builder section + JS)

No stdlib unit test covers this inline JS; it is verified live in Task 10. Keep edits surgical.

- [ ] **Step 1: Remove the HUD/Timer tabs.** In the markup (~line 608) delete the two tab buttons:
```html
              <button id="overlay-tab-hud" class="on" onclick="setOverlayPage('hud')">HUD</button>
              <button id="overlay-tab-timer" onclick="setOverlayPage('timer')">Timer</button>
```
In JS, replace `setOverlayPage` usage: set `let overlayPage = 'hud';` permanently and delete `setOverlayPage` (and the `$('overlay-tab-*')` lines inside it). `loadOverlay` already fetches `?page=' + overlayPage` → always `hud`.

- [ ] **Step 2: Add the border keys to the JS CSS maps** (~line 2284) so the canvas previews them and Save-all serializes them:
```javascript
const OV_CSSNAME = {left: 'left', top: 'top', width: 'width', height: 'height',
  fontSize: 'font-size', borderWidth: 'border-width', teamNameMax: '--team-name-max',
  teamNameMin: '--team-name-min', color: 'color', background: 'background',
  borderColor: 'border-color', borderStyle: 'border-style',
  fontFamily: 'font-family', align: 'justify-content'};
const OV_PX = new Set(['left', 'top', 'width', 'height', 'fontSize', 'borderWidth',
                       'teamNameMax', 'teamNameMin']);
```

- [ ] **Step 3: Add the POV panel fields.** In `ovRenderPanel` (~line 2683, after the `background` field block) add border controls, gated by `has(...)`:
```javascript
  if (has('borderWidth')) panel.appendChild(ovNumField('borderWidth', 'Border width (px)', ov));
  if (has('borderStyle')) {
    panel.appendChild(ovSelectField('borderStyle', 'Border style',
      [{v: '', t: '— none —'}, {v: 'solid', t: 'Solid'},
       {v: 'dashed', t: 'Dashed'}, {v: 'dotted', t: 'Dotted'}], ov));
  }
  if (has('borderColor')) panel.appendChild(ovColorField('borderColor', 'Border color', ov));
```

- [ ] **Step 4: Prefill from computed style.** Add a helper and call it when a slot is selected so empty fields show the template's effective values. Add near the other `ov*` helpers:
```javascript
// Effective base values for a slot, read from the rendered canvas element (the
// cascade ground-truth from base hud.html). Numbers for geometry/size, hex for
// colors. Used to PRE-FILL the panel so the operator always sees real values.
function ovRgbToHex(v) {
  const m = /^rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(v || '');
  if (!m) return (v && v[0] === '#') ? v : '';
  return '#' + [1, 2, 3].map(i => (+m[i]).toString(16).padStart(2, '0')).join('');
}
function ovBaseValues(id) {
  const el = ovState.shadow && ovState.shadow.getElementById(id);
  if (!el) return {};
  const cs = getComputedStyle(el);
  const px = n => Math.round(parseFloat(n) || 0);
  return {
    left: px(cs.left), top: px(cs.top), width: px(cs.width), height: px(cs.height),
    fontSize: px(cs.fontSize), borderWidth: px(cs.borderWidth),
    color: ovRgbToHex(cs.color), background: ovRgbToHex(cs.backgroundColor),
    borderColor: ovRgbToHex(cs.borderColor),
  };
}
```
In `ovRenderPanel`, compute the effective view once and pass it where today it passes `ov`:
```javascript
  const ov = (ovState.layout.slots && ovState.layout.slots[id]) || {};
  const base = ovBaseValues(id);
  const view = Object.assign({}, base, ov);   // override wins; base fills the rest
```
Then change the field constructors to read from `view` instead of `ov` for the prefilled props — i.e. `ovNumField('left', 'Left (px)', view)`, `ovNumField('top', …, view)`, `width`, `height`, `fontSize`, `borderWidth`, `ovColorField('color', …, view)`, `ovColorField('background', …, view)`, `ovColorField('borderColor', …, view)`. Leave `fontFamily`/`align`/`teamName*` reading from `ov` (they stay override-on-change; prefilling the font stack is noise).

- [ ] **Step 5: Save-all — write the full snapshot.** In `saveOverlay` (~line 2748), before building the POST body, materialize every editable slot's full effective value set into the layout:
```javascript
  // Save-all: persist each slot's full effective values (base + edits), so the
  // generated CSS fully pins the look (the producer chose this over diff-only).
  const fullSlots = {};
  (ovState.slots || []).forEach(s => {
    const base = ovBaseValues(s.id);
    const ov = (ovState.layout.slots && ovState.layout.slots[s.id]) || {};
    const allowed = new Set(s.props || []);
    const merged = {};
    (s.props || []).forEach(p => {
      const v = (ov[p] !== undefined) ? ov[p] : base[p];
      if (v !== undefined && v !== '' && allowed.has(p)) merged[p] = v;
    });
    if (Object.keys(merged).length) fullSlots[s.id] = merged;
  });
  const layout = Object.assign({}, ovState.layout, {
    version: 1, page: 'hud', slots: fullSlots, fonts: ovState.fonts.slice(),
    customCss: $('overlayCss').value});
```
(Replace the existing `const layout = Object.assign(...)` line with the block above; keep the rest of `saveOverlay` — the POST and the "Saved ✓" affordance — unchanged. `ovBaseValues` only returns geometry/size/colors, so text/align/teamName props still come from `ov`, preserving their override-only behavior.)

- [ ] **Step 6: Verify the page parses** (no unit test): reload the Control Center and watch the console.

Run: navigate to `http://127.0.0.1:8089`, open the browser console.
Expected: no JS errors; the overlay builder renders without HUD/Timer tabs.

- [ ] **Step 7: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(ui): single-page overlay builder with template prefill + POV frame

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Full suite, build, and live verification

**Files:** none (verification only)

- [ ] **Step 1: Full test suite**

Run: `python3 tools/run-tests.py`
Expected: every test file `ALL PASS` (this is exactly what CI runs).

- [ ] **Step 2: Lint**

Run: `python3 tools/lint.py`
Expected: no findings (CodeQL-mirrored ruff rules).

- [ ] **Step 3: Build + verify**

Run: `python3 tools/build.py`
Expected: assembles `dist/GT_Racecast_Package/`; verify prints all checks `ok` (no timer.html, clock in hud, no secrets, no shell scripts).

- [ ] **Step 4: Live — restart the relay so the merged page + OBS source change take effect**

Run (in the producer's install): `python3 src/racecast.py relay restart` (or `racecast obs refresh` if the relay is already on the new code).
Then in OBS, re-import / reload so the `HUD Race Timer` source is gone and `HUD Overlay` (now incl. the clock) is above `Feed POV`.

- [ ] **Step 5: Live — verify in the running Control Center (Playwright)**

- Open `http://127.0.0.1:8089` → Profile → overlay builder. Confirm: one canvas, no HUD/Timer tabs; the clock appears at the top band at on-air scale (small, ~36px), NOT a giant clock.
- Select the Clock slot → its Left/Top/Font size fields are pre-filled with real numbers.
- Select the POV box → Background / Border style / Border color / Border width fields exist; set a solid red 4px border; the box frames the PiP area on the canvas.
- Save → "Saved ✓"; open `/hud/preview` (Preview button) and confirm the clock sits correctly over the broadcast and the POV frame renders.

- [ ] **Step 6: Live — confirm the exact clock geometry against the old on-air look**

If the clock's size/position is off versus the pre-merge timer, tune `#clock` `left/top/font-size` in `src/obs/hud.html`, `relay restart`, re-check. Commit any tuning:
```bash
git add src/obs/hud.html
git commit -m "fix(hud): tune merged clock geometry to match on-air"
```

- [ ] **Step 7: Push + open the PR**

```bash
git push -u origin feat/builder-timer-merge
gh pr create --title "feat(overlay): merge timer into HUD, POV frame, property prefill" \
  --body "$(cat <<'EOF'
Merges the race timer into the main HUD overlay (one page/CSS/OBS source), fixes the
POV box (OBS-aligned position + live background/border frame), and pre-fills the
builder's property panel from the template (save-all snapshot).

Spec: docs/superpowers/specs/2026-06-14-visual-builder-timer-merge-design.md
Plan: docs/superpowers/plans/2026-06-14-visual-builder-timer-merge.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review notes

- **Spec coverage:** timer merge (Tasks 3,4,5,7,8) · POV position (Task 3) · POV live border/bg (Tasks 1,3,9) · prefill (Task 9) · save-all (Task 9) · legacy timer.css migration (Task 6) · OBS reorder for the frame (Task 7) · verification incl. live (Task 10). All spec sections map to a task.
- **Verify-live, not asserted:** exact `#clock` pixels (Task 10 Step 6) and `HUD Overlay`-above-`Feed POV` frame behavior (Task 7 test + Task 10 Step 5) — per the spec, confirmed in the running app, not asserted blind.
- **Flag rule (CLAUDE.md):** the only relay flag touched is `--no-timer` (kept, re-scoped to the state only); no flag is removed. `grep -rn "no-timer\|timer.html\|/timer\b" tools/ .github/` before finishing Task 8 to confirm no pipeline caller breaks.
- **Cross-platform:** no new fixed-OS path joins introduced.
