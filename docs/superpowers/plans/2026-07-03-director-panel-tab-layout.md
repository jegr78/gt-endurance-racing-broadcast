# Director Panel Tab Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the Director Panel's single scroll column into a two-tab layout (PROGRAM / SETUP) so the live preview and most-used actions stay in view without scrolling.

**Architecture:** Front-end only. Wrap the existing left-column (`.mainpane`) `<section>`s into two `role="tabpanel"` wrappers under a sticky `role="tablist"` bar; reorder them by live-frequency. The right rail is untouched and shown on both tabs. Tab switching is CSS `hidden`-toggling only, so all DOM/polls/state survive a switch. Every existing element keeps its `id` and event bindings.

**Tech Stack:** Plain HTML/CSS/vanilla JS in `src/director/director-panel.html` (one file, one `<script>`). Structural guards in a new stdlib Python test `tests/test_director_panel.py` (string-index assertions over the served HTML, mirroring `tests/test_cockpit.py::t_all_console_pages_strip_token_from_url`).

## Global Constraints

- Edit only under `src/` (plus the new test under `tests/` and this plan's screenshots). `dist/`/`runtime/` are generated.
- All code and docs are English only.
- No relay/Python behavior change, no new endpoints, no auth/routing change. `/console/panel` (Funnel) serves the same file and inherits the layout.
- Preserve every existing element `id` and its inner structure — JS binds controls by `id`; only DOM position changes.
- The right rail (`.rail`: `#chatBox`, `#bchatBox`, `#gfxBrowseBox`) is unchanged and shown on both tabs.
- Tab names are exactly `PROGRAM` (default) and `SETUP`.
- Tab 1 (PROGRAM) order: Live Preview → PGM → Cues → Feeds → HUD.
- Tab 2 (SETUP) order: Scn·Vis → Gfx → Flag Gfx → Timer → Audio → Transition → URLs → Qualifying → Pending → Substitution.
- Reuse existing CSS tokens (`--bg`, `--panel`, `--panel-2`, `--edge`, `--ink`, `--muted`, `--amber`, `--amber-glow`, `--air`, `--blue`, `--mono`, `--head`). No new palette.
- Tab switch = toggling the `hidden` attribute only; never destroy/re-init a panel (preserves polls, timers, preview frames, in-progress input, scroll).
- `localStorage` key for the remembered tab is exactly `rc_panel_tab`.
- Run `python3 tools/lint.py` after any Python change and `python3 tools/run-tests.py` before finishing (run test commands in the FOREGROUND).
- A visible Director Panel change REQUIRES `ui-visual-verification` of both tabs AND a regenerated committed `src/docs/wiki/images/director-panel.png` (+ the `src/docs/slides/assets/img/director-panel.png` copy) in the same change (CLAUDE.md hard rule).

**Note on test scope:** there is no JS runtime in the Python test suite, so the structural tests assert **markup and presence-of-code anchors** over the HTML string (the established pattern for these pages). The actual runtime behavior (clicking tabs, keyboard, badge updating, chip reflecting the transition) is proven in Task 5's `ui-visual-verification` render pass — that is the behavioral gate, and the plan says so explicitly rather than pretending a string check proves behavior.

**Current section anchors (for reference — line numbers drift as you edit; locate by `id`):**
`<div class="mainpane">` (~463). Sections in current order: PGM `#pgmBus`, Cues `#cuesBus`, Live Preview `#previewSec`, Feeds `#feedsBus`, HUD `#setupRow`, Transition `#txBar`, Scn·Vis `#scnBus`, Gfx `#gfxBus`, Flag Gfx `#flagGfxBus`, Timer `#timerBus`, Audio `#audio`, URLs `#urlsBox`, Pending `#subsBox`, Qualifying `#qualBox`, Substitution `#subSec`, then `#log`, then `</div><!-- /.mainpane -->`.

---

### Task 1: Tab scaffolding — bar, panels, reorder, working switch, preview default-shown

**Files:**
- Modify: `src/director/director-panel.html` (`.mainpane` markup, `:root` + `.pgm` + new tab CSS, tab-switch JS, preview default)
- Create: `tests/test_director_panel.py`

**Interfaces:**
- Produces (JS, top-level in the single `<script>`): `function setTab(name)` — sets which panel is visible, updates `aria-selected`/roving `tabIndex`, and writes `localStorage["rc_panel_tab"]`. Consumed by Tasks 2 (keyboard), 3 (TX chip click), and re-used at boot. Constants `TAB_KEY="rc_panel_tab"`, `TAB_PANELS={program:"tabProgram",setup:"tabSetup"}`, `TAB_BTNS={program:"tabBtnProgram",setup:"tabBtnSetup"}`.
- Produces (DOM): `#tabProgram` / `#tabSetup` panels, `#tabBtnProgram` / `#tabBtnSetup` tabs, `#setupBadge` (empty placeholder, wired in Task 4).

- [ ] **Step 1: Write the failing structural test file**

Create `tests/test_director_panel.py`:

```python
#!/usr/bin/env python3
"""Stdlib structural checks for the Director Panel tab layout.
Run: python3 tests/test_director_panel.py

No JS runtime here — these assert markup + presence-of-code anchors over the
served HTML string (same pattern as tests/test_cockpit.py). Runtime behavior is
verified via the ui-visual-verification render pass, not here."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PANEL = os.path.join(ROOT, "src", "director", "director-panel.html")


def _html():
    with open(PANEL, encoding="utf-8") as fh:
        return fh.read()


def _order(html, *needles):
    """Assert each needle appears, in strictly increasing position."""
    last = -1
    for n in needles:
        i = html.find(n)
        assert i != -1, f"missing: {n}"
        assert i > last, f"out of order: {n} (at {i}) not after previous (at {last})"
        last = i


def t_tabbar_present():
    h = _html()
    assert 'role="tablist"' in h
    assert 'id="tabBtnProgram"' in h and 'data-tab="program"' in h
    assert 'id="tabBtnSetup"' in h and 'data-tab="setup"' in h
    assert '>PROGRAM<' in h and '>SETUP' in h


def t_two_tabpanels_present():
    h = _html()
    assert 'id="tabProgram"' in h and 'id="tabSetup"' in h
    assert 'role="tabpanel"' in h
    # SETUP panel ships hidden by default (PROGRAM is the default tab).
    seg = h[h.find('id="tabSetup"'):h.find('id="tabSetup"') + 120]
    assert "hidden" in seg, "SETUP panel must be hidden by default"


def t_program_tab_order():
    # Preview -> PGM -> Cues -> Feeds -> HUD, all inside the PROGRAM panel.
    h = _html()
    _order(h, 'id="tabProgram"',
           'id="previewSec"', 'id="pgmBus"', 'id="cuesBus"',
           'id="feedsBus"', 'id="setupRow"',
           'id="tabSetup"')  # everything above precedes the SETUP panel opening


def t_setup_tab_order():
    # Scn.Vis -> Gfx -> Flag Gfx -> Timer -> Audio -> Transition -> URLs
    # -> Qualifying -> Pending -> Substitution, all after the SETUP panel opening.
    h = _html()
    _order(h, 'id="tabSetup"',
           'id="scnBus"', 'id="gfxBus"', 'id="flagGfxBus"', 'id="timerBus"',
           'id="audio"', 'id="txBar"', 'id="urlsBox"', 'id="qualBox"',
           'id="subsBox"', 'id="subSec"')


def t_log_outside_panels():
    # The status log stays below both panels (visible on both tabs).
    h = _html()
    _order(h, 'id="subSec"', 'id="log"')


def t_settab_and_default():
    h = _html()
    assert "function setTab(" in h
    assert '"rc_panel_tab"' in h
    # boot initializes from the stored tab, defaulting to program
    assert 'localStorage.getItem(TAB_KEY) || "program"' in h


def t_preview_default_shown():
    # New/unset installs show the preview by default (respects an explicit "0").
    h = _html()
    assert 'localStorage.getItem(PV_KEY) || "1"' in h


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 tests/test_director_panel.py`
Expected: FAIL on `t_tabbar_present` (`assert 'role="tablist"' in h`) — none of the new markup exists yet.

- [ ] **Step 3: Add the `--tabbar-h` token and fix the `.pgm` sticky offset**

In `src/director/director-panel.html`, in the `:root{…}` block (currently ends with `--blue:#3aa0ff;`), add the tab-bar height token:

```css
    --blue:#3aa0ff;
    --tabbar-h:46px;
```

Then change the existing `.pgm` rule (currently `.pgm{position:sticky;top:8px;z-index:30}`) so PGM sticks BELOW the sticky tab bar instead of under it:

```css
  .pgm{position:sticky;top:calc(var(--tabbar-h) + 8px);z-index:30}
```

- [ ] **Step 4: Add the tab-bar + tab CSS**

Immediately AFTER the `.pgm{…}` rule from Step 3, add:

```css
  /* ---------- tab bar (PROGRAM / SETUP) ---------- */
  .tabbar{position:sticky;top:0;z-index:40;display:flex;gap:8px;
    min-height:var(--tabbar-h);align-items:flex-end;
    background:var(--bg);padding:8px 0 0;margin-bottom:12px;
    border-bottom:1px solid var(--edge)}
  .tab{appearance:none;cursor:pointer;font-family:var(--head);font-weight:700;
    letter-spacing:.12em;text-transform:uppercase;font-size:15px;
    padding:10px 20px;min-height:40px;border-radius:10px 10px 0 0;
    border:1px solid var(--edge);border-bottom:none;
    background:linear-gradient(180deg,var(--panel-2),var(--panel));
    color:var(--muted);position:relative;display:inline-flex;align-items:center;gap:8px}
  .tab[aria-selected="true"]{color:var(--ink)}
  .tab[aria-selected="true"]::after{content:"";position:absolute;left:0;right:0;bottom:-1px;
    height:2px;background:var(--amber);box-shadow:0 0 10px var(--amber-glow)}
  .tab:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
  .tabbadge{display:inline-flex;align-items:center;justify-content:center;
    min-width:18px;height:18px;padding:0 5px;border-radius:9px;
    background:var(--air);color:#fff;font-family:var(--mono);font-weight:700;
    font-size:11px;letter-spacing:0}
```

- [ ] **Step 5: Insert the tab bar and the two panel wrappers, and reorder the sections**

In the markup, immediately after `<div class="mainpane">` insert the tab bar and open the PROGRAM panel:

```html
  <div class="mainpane">

  <div class="tabbar" role="tablist" aria-label="Director panel sections">
    <button class="tab" id="tabBtnProgram" role="tab" data-tab="program"
            aria-selected="true" aria-controls="tabProgram" tabindex="0">PROGRAM</button>
    <button class="tab" id="tabBtnSetup" role="tab" data-tab="setup"
            aria-selected="false" aria-controls="tabSetup" tabindex="-1">SETUP<span
            class="tabbadge" id="setupBadge" hidden>0</span></button>
  </div>

  <div id="tabProgram" role="tabpanel" aria-labelledby="tabBtnProgram">
```

Then physically MOVE the existing `<section>` blocks so the PROGRAM panel contains, in this exact order:
1. `<section class="bus preview" id="previewSec">…</section>` (the Live Preview block)
2. `<section class="bus pgm"><div class="cap">PGM</div>…</section>`
3. `<section class="bus" id="cuesBus">…</section>`
4. `<section class="bus"><div class="cap">Feeds</div>…</section>`
5. `<section class="bus"><div class="cap">HUD</div>…</section>`

Close the PROGRAM panel and open the SETUP panel after the HUD section:

```html
  </div><!-- /#tabProgram -->

  <div id="tabSetup" role="tabpanel" aria-labelledby="tabBtnSetup" hidden>
```

Then MOVE the remaining sections into the SETUP panel in this exact order:
1. `<section class="bus"><div class="cap">Scn·Vis</div>…</section>`
2. `<section class="bus"><div class="cap">Gfx</div>…</section>`
3. `<section class="bus"><div class="cap">Flag Gfx</div>…</section>`
4. `<section class="bus"><div class="cap">Timer</div>…</section>`
5. `<section class="bus"><div class="cap">Audio</div>…</section>`
6. `<section class="bus" id="txBar" …>…</section>` (Transition)
7. `<details class="bus urls" id="urlsBox">…</details>`
8. `<details class="bus urls qualifying" id="qualBox">…</details>`
9. `<details class="bus urls" id="subsBox">…</details>` (Pending)
10. `<section class="bus" id="subSec" …>…</section>` (Substitution)

Close the SETUP panel, then leave `#log` (and the existing `</div><!-- /.mainpane -->`) after it:

```html
  </div><!-- /#tabSetup -->

  <div id="log">Ready. All controls work relay-only — no OBS connection needed.</div>

  </div><!-- /.mainpane -->
```

Do NOT touch anything from `<div class="rail">` onward.

- [ ] **Step 6: Make the preview default-shown**

Find the preview boot line (currently `if((localStorage.getItem(PV_KEY) || "0") === "1"){ pvStart(); }`) and change the default from hidden to shown (a stored explicit `"0"` from a user who hid it is still respected):

```javascript
if((localStorage.getItem(PV_KEY) || "1") === "1"){ pvStart(); }
```

- [ ] **Step 7: Add the tab-switch JS**

Immediately before the `/* ---------- boot ---------- */` comment near the end of the `<script>`, add:

```javascript
/* ---------- tab layout (PROGRAM / SETUP) ---------- */
const TAB_KEY = "rc_panel_tab";
const TAB_PANELS = { program: "tabProgram", setup: "tabSetup" };
const TAB_BTNS   = { program: "tabBtnProgram", setup: "tabBtnSetup" };
function setTab(name){
  if(!TAB_PANELS[name]) name = "program";
  for(const key in TAB_PANELS){
    const on = key === name;
    document.getElementById(TAB_PANELS[key]).hidden = !on;
    const btn = document.getElementById(TAB_BTNS[key]);
    btn.setAttribute("aria-selected", on ? "true" : "false");
    btn.tabIndex = on ? 0 : -1;
  }
  try{ localStorage.setItem(TAB_KEY, name); }catch(e){}
}
document.querySelectorAll(".tabbar .tab").forEach(b =>
  b.addEventListener("click", () => setTab(b.dataset.tab)));
setTab(localStorage.getItem(TAB_KEY) || "program");
```

- [ ] **Step 8: Run the structural tests — expect PASS**

Run: `python3 tests/test_director_panel.py`
Expected: `ALL PASS` (all seven `t_*` green).

- [ ] **Step 9: Run lint and the tests you touched**

Run: `python3 tools/lint.py`
Expected: no lint errors.
Run: `python3 tests/test_director_panel.py`
Expected: `ALL PASS`.

- [ ] **Step 10: Commit**

```bash
git add src/director/director-panel.html tests/test_director_panel.py
git commit -m "feat(panel): tab layout scaffolding (PROGRAM/SETUP) with reordered sections"
```

---

### Task 2: Keyboard & a11y — arrow-key tablist nav + global 1/2 shortcuts

**Files:**
- Modify: `src/director/director-panel.html` (extend the tab-layout JS block)
- Modify: `tests/test_director_panel.py` (append two tests)

**Interfaces:**
- Consumes: `setTab(name)`, `TAB_BTNS` from Task 1.
- Produces: a `.tabbar` `keydown` handler (Arrow Left/Right) and a document-level `keydown` handler for `1`/`2`, guarded against firing while typing.

- [ ] **Step 1: Append the failing tests**

Add to `tests/test_director_panel.py` (before the `__main__` block):

```python
def t_keyboard_shortcuts_present():
    h = _html()
    # global 1/2 switch tabs
    assert 'e.key === "1"' in h and 'e.key === "2"' in h
    # arrow-key nav on the tablist
    assert '"ArrowLeft"' in h and '"ArrowRight"' in h


def t_shortcut_guards_typing():
    # 1/2 must NOT fire while typing in a field.
    h = _html()
    assert "/^(INPUT|TEXTAREA|SELECT)$/.test" in h
    assert "isContentEditable" in h
```

- [ ] **Step 2: Run to confirm they fail**

Run: `python3 tests/test_director_panel.py`
Expected: FAIL on `t_keyboard_shortcuts_present` (`assert 'e.key === "1"'`).

- [ ] **Step 3: Add the keyboard handlers**

In the tab-layout JS block (Task 1), immediately after the `document.querySelectorAll(".tabbar .tab")…` click-wiring line and BEFORE the `setTab(localStorage…)` init line, insert:

```javascript
document.querySelector(".tabbar").addEventListener("keydown", e => {
  if(e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
  e.preventDefault();
  const next = e.target.dataset.tab === "program" ? "setup" : "program";
  setTab(next); document.getElementById(TAB_BTNS[next]).focus();
});
document.addEventListener("keydown", e => {
  if(e.metaKey || e.ctrlKey || e.altKey) return;
  const t = e.target;
  if(t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return;
  if(e.key === "1") setTab("program");
  else if(e.key === "2") setTab("setup");
});
```

- [ ] **Step 4: Run the tests — expect PASS**

Run: `python3 tests/test_director_panel.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/director/director-panel.html tests/test_director_panel.py
git commit -m "feat(panel): keyboard tab nav (arrows + 1/2 shortcuts, guarded)"
```

---

### Task 3: TX-armed chip on the PROGRAM tab

**Files:**
- Modify: `src/director/director-panel.html` (PGM section markup, chip CSS, `renderTxBar`, click wiring)
- Modify: `tests/test_director_panel.py` (append one test)

**Interfaces:**
- Consumes: `activeTransition` (existing JS var), `renderTxBar()` (existing), `setTab()` (Task 1).
- Produces: `#txArmed` chip in the PGM section that shows `TX: <TYPE>` and jumps to the SETUP tab on click.

- [ ] **Step 1: Append the failing test**

Add to `tests/test_director_panel.py` (before `__main__`):

```python
def t_tx_chip_present_and_wired():
    h = _html()
    # chip lives in the PGM section
    assert 'id="txArmed"' in h
    pgm = h.find('class="bus pgm"')
    assert pgm != -1 and h.find('id="txArmed"') > pgm
    assert h.find('id="txArmed"') < h.find('id="cuesBus"'), "chip must be inside PGM section"
    # renderTxBar updates the chip text
    assert 'chip.textContent = "TX: " + activeTransition.toUpperCase()' in h
    # clicking the chip switches to the SETUP tab
    assert 'chip.addEventListener("click", () => setTab("setup"))' in h
```

- [ ] **Step 2: Run to confirm it fails**

Run: `python3 tests/test_director_panel.py`
Expected: FAIL on `t_tx_chip_present_and_wired` (`assert 'id="txArmed"' in h`).

- [ ] **Step 3: Add the chip to the PGM section markup**

Change the PGM section (currently `<section class="bus pgm"><div class="cap">PGM</div><div class="keys" id="pgmBus"></div></section>`) to append the chip after the keys:

```html
  <section class="bus pgm"><div class="cap">PGM</div><div class="keys" id="pgmBus"></div><button
    class="txarmed" id="txArmed" type="button"
    title="Armed transition — click to change it on the SETUP tab">TX: FADE</button></section>
```

- [ ] **Step 4: Add the chip CSS**

After the `.tabbadge{…}` rule (Task 1, Step 4), add:

```css
  .txarmed{align-self:center;flex:0 0 auto;cursor:pointer;font-family:var(--mono);
    font-size:11px;letter-spacing:.08em;color:var(--ink);background:#0c0f13;
    border:1px solid var(--edge);border-radius:8px;padding:7px 10px;white-space:nowrap}
  .txarmed:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
```

- [ ] **Step 5: Update `renderTxBar()` to refresh the chip**

The existing `renderTxBar()` is:

```javascript
function renderTxBar(){
  document.querySelectorAll('#txBar .tx').forEach(b =>
    b.classList.toggle('on', b.dataset.tx === activeTransition));
  const dur = $("#txDur");
  if (dur) dur.disabled = (activeTransition === "cut");
}
```

Add the chip refresh as the last statement inside it:

```javascript
function renderTxBar(){
  document.querySelectorAll('#txBar .tx').forEach(b =>
    b.classList.toggle('on', b.dataset.tx === activeTransition));
  const dur = $("#txDur");
  if (dur) dur.disabled = (activeTransition === "cut");
  const chip = document.getElementById("txArmed");
  if (chip) chip.textContent = "TX: " + activeTransition.toUpperCase();
}
```

- [ ] **Step 6: Wire the chip click to switch to SETUP**

Immediately after the existing `renderTxBar();` call (the one right after the `#txBar .tx` click-wiring), add:

```javascript
{ const chip = document.getElementById("txArmed");
  if (chip) chip.addEventListener("click", () => setTab("setup")); }
```

- [ ] **Step 7: Run the tests — expect PASS**

Run: `python3 tests/test_director_panel.py`
Expected: `ALL PASS`.

- [ ] **Step 8: Commit**

```bash
git add src/director/director-panel.html tests/test_director_panel.py
git commit -m "feat(panel): TX-armed chip on PROGRAM tab (reflects transition, jumps to SETUP)"
```

---

### Task 4: SETUP tab badge — pending submissions + active substitution

**Files:**
- Modify: `src/director/director-panel.html` (`updateSetupBadge()`, hooks in `subsPoll` + `substitutionPoll`)
- Modify: `tests/test_director_panel.py` (append one test)

**Interfaces:**
- Consumes: `#subsCount` (existing, set by `subsPoll`), `#subSec` visibility (existing, set by `substitutionPoll`), `#setupBadge` (Task 1 markup).
- Produces: `function updateSetupBadge()` — shows the pending-submission count on `#setupBadge`, or a `•` dot when only a substitution is pending, else hidden. Called from both polls.

- [ ] **Step 1: Append the failing test**

Add to `tests/test_director_panel.py` (before `__main__`):

```python
def t_setup_badge_wired():
    h = _html()
    assert "function updateSetupBadge(" in h
    assert 'id="setupBadge"' in h
    # called from BOTH the submissions poll and the substitution poll
    assert h.count("updateSetupBadge()") >= 3  # 1 def-site call chain + >=2 call sites
    # reads the existing pending count and the substitution-visible state
    assert 'getElementById("subsCount")' in h
    assert 'getElementById("subSec")' in h
```

- [ ] **Step 2: Run to confirm it fails**

Run: `python3 tests/test_director_panel.py`
Expected: FAIL on `t_setup_badge_wired` (`assert "function updateSetupBadge("`).

- [ ] **Step 3: Add `updateSetupBadge()`**

In the tab-layout JS block (Task 1), append this function at the end of the block (after the keyboard handlers, before or after the `setTab(localStorage…)` init — placement is free, it is a hoisted declaration):

```javascript
function updateSetupBadge(){
  const badge = document.getElementById("setupBadge");
  if(!badge) return;
  const sc = document.getElementById("subsCount");
  const pending = (sc && !sc.hidden) ? (parseInt(sc.textContent, 10) || 0) : 0;
  const subActive = document.getElementById("subSec").style.display !== "none";
  if(pending > 0){ badge.textContent = String(pending); badge.hidden = false; }
  else if(subActive){ badge.textContent = "•"; badge.hidden = false; }
  else { badge.hidden = true; }
}
```

- [ ] **Step 4: Call it from `subsPoll()`**

In `subsPoll()`, the badge count is set just before the collapsed-early-return. The existing lines are:

```javascript
    const badge = $("#subsCount");
    badge.textContent = pend.length; badge.hidden = pend.length === 0;
    $("#subsEmpty").style.display = pend.length ? "none" : "";
    if (!$("#subsBox").open) return;     // collapsed -> keep the badge fresh only
```

Insert `updateSetupBadge();` right after the `$("#subsEmpty")…` line (so it runs even when `#subsBox` is collapsed):

```javascript
    const badge = $("#subsCount");
    badge.textContent = pend.length; badge.hidden = pend.length === 0;
    $("#subsEmpty").style.display = pend.length ? "none" : "";
    updateSetupBadge();
    if (!$("#subsBox").open) return;     // collapsed -> keep the badge fresh only
```

- [ ] **Step 5: Call it from `substitutionPoll()`**

The existing `substitutionPoll()` core is:

```javascript
    const sec = document.getElementById("subSec");
    if (!s){ sec.style.display = "none"; return; }
    sec.style.display = "";
```

Add an `updateSetupBadge();` in both branches (after each `display` assignment):

```javascript
    const sec = document.getElementById("subSec");
    if (!s){ sec.style.display = "none"; updateSetupBadge(); return; }
    sec.style.display = ""; updateSetupBadge();
```

- [ ] **Step 6: Run the tests — expect PASS**

Run: `python3 tests/test_director_panel.py`
Expected: `ALL PASS` (the `>= 3` count is met: the definition-body has no self-call, but the two poll call-sites plus the substitution null-branch call sum to 3 occurrences of `updateSetupBadge()`).

- [ ] **Step 7: Run lint + full-file test once more**

Run: `python3 tools/lint.py`
Expected: no errors.
Run: `python3 tests/test_director_panel.py`
Expected: `ALL PASS`.

- [ ] **Step 8: Commit**

```bash
git add src/director/director-panel.html tests/test_director_panel.py
git commit -m "feat(panel): SETUP tab badge for pending submissions + active substitution"
```

---

### Task 5: Visual verification + wiki screenshot (mandatory)

**Files:**
- Modify: `src/docs/wiki/images/director-panel.png`
- Modify: `src/docs/slides/assets/img/director-panel.png`
- (No code changes; this is the required look-and-render gate.)

**Interfaces:** none (verification + committed screenshot).

- [ ] **Step 1: Run the whole suite in the foreground**

Run: `python3 tools/run-tests.py`
Expected: `ALL TEST FILES PASS` (includes the new `tests/test_director_panel.py`).

- [ ] **Step 2: Boot the demo build and render `/panel`**

Follow the `wiki-screenshots` demo recipe (demo profile + stub `runtime/yt-cookies.txt` + `tools/obs-sim.py` on its port + `RACECAST_OBS_WS_*` → the sim), start the relay from `src/` (no `VERSION` stamp — dev-build badge), and open `/panel` in the Playwright MCP at a realistic director width (≥1280).

- [ ] **Step 3: Look at BOTH tabs (the actual behavioral gate)**

Per `ui-visual-verification`, take element screenshots and Read them back, checking deliberately:
- **PROGRAM tab:** the tab bar active-state (amber underline, `--ink` label), Preview **default-shown** with PROGRAM + Feed tiles, the `TX: FADE`/`TX: CUT` chip in the PGM row, and the row order Preview → PGM → Cues → Feeds → HUD. The right rail (Chat/Broadcast/Graphics) present.
- **SETUP tab:** click `SETUP` — order Scn·Vis → Gfx → Flag Gfx → Timer → Audio → Transition → URLs → Qualifying → Pending → Substitution; the rail still present and identical.
- **Badge:** with a seeded pending submission (or an active substitution), the `SETUP` tab shows the count/dot. If nothing is seedable in the demo, confirm the badge is hidden and note that the seeded case was reasoned, not rendered.
- **Interaction:** click PROGRAM/SETUP switches without losing the preview frame; `:focus-visible` ring on the tab buttons; a keyboard `2`/`1` switch works.
- Theme fit: no default browser controls; tab bar uses the panel tokens.
Fix and re-shoot anything off before proceeding.

- [ ] **Step 4: Regenerate the committed screenshot**

With the PROGRAM tab shown, capture the Director Panel image per the `wiki-screenshots` recipe and overwrite BOTH:
- `src/docs/wiki/images/director-panel.png`
- `src/docs/slides/assets/img/director-panel.png`
(Same image in both paths, matching the existing framing.)

- [ ] **Step 5: Record the visual-verification marker**

Run: `python3 .claude/hooks/record_ui_verified.py src/director/director-panel.html`
Expected: marker recorded (satisfies the Stop-hook gate).

- [ ] **Step 6: Tear down the demo build**

`racecast relay stop`; `pkill -f obs-sim.py`; remove the stub `runtime/yt-cookies.txt`; `git checkout -- profiles/demo/profile.env` (auto-provisioned `CONSOLE_SECRET`); delete any scratch PNGs from the repo root.

- [ ] **Step 7: Commit the screenshots**

```bash
git add src/docs/wiki/images/director-panel.png src/docs/slides/assets/img/director-panel.png
git commit -m "docs(panel): refresh director-panel screenshot for the tab layout"
```

---

## Self-Review

**1. Spec coverage.**
- Tab bar (PROGRAM default / SETUP), left-column only, rail on both tabs → Task 1 (markup + CSS).
- Tab 1 order + preview default-shown → Task 1 (Steps 5–6).
- Tab 2 order incl. Transition + Substitution → Task 1 (Step 5).
- Persistent `#log` on both tabs → Task 1 (Step 5) + `t_log_outside_panels`.
- Tab-bar visual/active state → Task 1 (Step 4).
- TX-armed chip → Task 3.
- Default tab + `rc_panel_tab` persistence → Task 1 (Step 7).
- SETUP badge (pending + substitution) → Task 4.
- Keyboard/a11y (roles/aria in markup, arrows, 1/2, guard) → Task 1 markup + Task 2.
- `display`-only switch preserves state → Task 1 `setTab` (toggles `hidden`, no teardown).
- Responsive (rail stacks <900px; tab bar stays) → inherited (no change to the `.panes` media queries; tab bar is inside `.mainpane`); verified in Task 5.
- `ui-visual-verification` + wiki screenshot → Task 5.
- `.pgm` sticky vs sticky tab bar reconciled → Task 1 (Step 3, `--tabbar-h`). ✅ no gaps.

**2. Placeholder scan.** No TBD/TODO/"handle edge cases"; every code step shows full code; every command has expected output. ✅

**3. Type/name consistency.** `setTab`, `TAB_KEY`/`"rc_panel_tab"`, `TAB_PANELS`/`TAB_BTNS`, `#tabProgram`/`#tabSetup`, `#tabBtnProgram`/`#tabBtnSetup`, `#setupBadge`, `#txArmed`, `updateSetupBadge`, `renderTxBar`, `PV_KEY` — used identically across tasks and tests. The `t_setup_badge_wired` `>= 3` count matches the three literal `updateSetupBadge()` call-sites added in Task 4 (two in `substitutionPoll` branches + one in `subsPoll`; the definition uses `function updateSetupBadge(` without parens-call). ✅
