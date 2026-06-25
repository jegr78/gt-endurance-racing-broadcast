# Overlay Builder Editor Aids Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an align-to-canvas toolbar, undo/redo, and a toggleable snap grid to the Control Center's visual overlay builder.

**Architecture:** Three front-end-only enhancements in `src/ui/control-center.html`, all routed through the builder's existing seams (`ovSetProp`, `ovState`, `ovBuildCanvas`, `ovRenderPanel`). No server, compiler, route, or Python change. The grid is an editor preference (localStorage) and is never serialised into the layout/`override.css`.

**Tech Stack:** Vanilla JS + Shadow DOM in a single static HTML file (no build step, no JS libraries — the repo ships none). Tests are stdlib Python and do not exercise this file, so the new behaviour is verified manually against a local dev build.

## Global Constraints

- **Edit only under `src/`** — never `dist/`/`runtime/`. (Plus the plan/spec docs.)
- **English only** in all code, comments, UI strings, and docs.
- **No new JS dependency** — vanilla JS only.
- **Canvas is fixed `1920×1080`, origin top-left.**
- **The grid is editor-only** — never written to `ovState.layout`, the profile, or `override.css`.
- **Undo covers visual/slot edits only** — the Advanced-CSS textarea keeps native browser text-undo.
- **Wiki rule:** a visible Control Center change requires refreshing `src/docs/wiki/images/cc-overlay-builder.png` in the same change (final task).
- The existing Python suite (`python3 tools/run-tests.py`) and lint (`python3 tools/lint.py`) must stay green (they are unaffected, but are the regression guard).

## File Structure

- `src/ui/control-center.html` — the only code file. Changes are localised to: the
  builder toolbar markup (`#overlay-section` head, ~684-696), the builder CSS block
  (~293-348), and the overlay-builder JS module (~2765-3482).
- `src/docs/wiki/images/cc-overlay-builder.png` (+ any slides copy) — refreshed screenshot.

## Dev-build verification (used by every task)

Start a Control Center dev build on a free port (the user's real instance owns 8089 — never reuse it):

```bash
RACECAST_UI_PORT=8099 python3 src/racecast.py ui
```

Open `http://127.0.0.1:8099`, go to the **Profile** view, pick a profile that has an overlay (e.g. `demo` or `erf-nls`) so the **Overlay Builder** card populates its canvas. Use the **Pop out ↗** modal for room. After each task, hard-reload (Cmd/Ctrl-Shift-R) to bypass the browser cache before testing.

---

## Task 1: Shared canvas-dimension constants

**Files:**
- Modify: `src/ui/control-center.html` (overlay JS: `ovState` declaration ~2771; `ovFitCanvas` ~2996)

**Interfaces:**
- Produces: globals `OV_CANVAS_W = 1920`, `OV_CANVAS_H = 1080` (consumed by Tasks 3 and 4).

- [ ] **Step 1: Add the constants** above the `ovState` declaration.

Find (line ~2771):

```javascript
let overlayPage = 'hud';
const ovState = {page: 'hud', slots: [], sample: {}, baseCss: '', body: '',
```

Replace the first line with:

```javascript
let overlayPage = 'hud';
// Canvas is a fixed 1920x1080 design space (origin top-left); single source for
// the align toolbar and the snap grid.
const OV_CANVAS_W = 1920, OV_CANVAS_H = 1080;
const ovState = {page: 'hud', slots: [], sample: {}, baseCss: '', body: '',
```

- [ ] **Step 2: Use the constant in `ovFitCanvas`.**

Find (line ~2996):

```javascript
  const s = (wrap.clientWidth || 1) / 1920;
```

Replace with:

```javascript
  const s = (wrap.clientWidth || 1) / OV_CANVAS_W;
```

- [ ] **Step 3: Verify the builder still loads.**

Start the dev build (see above), open the Overlay Builder, confirm the canvas renders and scales as before, drag a slot to confirm no regression. Open the browser console (F12) — no errors.

- [ ] **Step 4: Commit.**

```bash
git add src/ui/control-center.html
git commit -m "refactor(builder): hoist canvas dimensions to OV_CANVAS_W/H constants"
```

---

## Task 2: Undo/Redo (visual edits)

**Files:**
- Modify: `src/ui/control-center.html` (toolbar markup ~691; CSS ~292; `ovState` ~2772; new history helpers near `ovSetProp` ~2984; commit calls in `ovStartDrag`/`ovStartResize`/`ovNumField`/`ovColorField`/`ovSelectField`/`ovRenderPanel`/`ovResetSlot`/`ovShadowField`/`ovPopulateFontSelect`; `loadOverlay` ~2838; keyboard listener ~3462)

**Interfaces:**
- Consumes: `ovState`, `ovBuildCanvas`, `ovRenderPanel`, `ovPositionSel`, `$`.
- Produces: `ovCommit()` (call after one logical edit — used by Task 3 align buttons), `ovHistInit()`, `ovUndo()`, `ovRedo()`, `ovReloadCanvasFromLayout()`, `ovHistButtons()`.

- [ ] **Step 1: Add `undo`/`redo` stacks to `ovState`.**

Find (lines ~2772-2774):

```javascript
const ovState = {page: 'hud', slots: [], sample: {}, baseCss: '', body: '',
                 layout: null, fonts: [], library: [], scale: 1, sel: null,
                 shadow: null, selBox: null, fields: {}};
```

Replace with:

```javascript
const ovState = {page: 'hud', slots: [], sample: {}, baseCss: '', body: '',
                 layout: null, fonts: [], library: [], scale: 1, sel: null,
                 shadow: null, selBox: null, fields: {}, undo: [], redo: []};
```

- [ ] **Step 2: Add the history helpers** immediately after `ovSetProp` (after its closing brace, line ~2984).

```javascript
// ----- Undo/redo (issue: builder editor aids) -----
// Snapshot stacks of the in-memory layout. VISUAL edits only — the Advanced-CSS
// textarea keeps its own native browser undo and is never tracked here. Invariant:
// ovState.undo's top always equals the last committed layout, so undo reverts to
// the new top and redo reapplies — no per-prop inverse operations.
function ovSnap_() { return JSON.parse(JSON.stringify(ovState.layout || {})); }

function ovHistInit() { ovState.undo = [ovSnap_()]; ovState.redo = []; ovHistButtons(); }

function ovCommit() {                       // call after ONE logical edit completes
  ovState.undo.push(ovSnap_());
  if (ovState.undo.length > 50) ovState.undo.shift();
  ovState.redo = [];
  ovHistButtons();
}

function ovUndo() {
  if (!ovState.undo || ovState.undo.length < 2) return;
  ovState.redo.push(ovState.undo.pop());
  ovState.layout = JSON.parse(JSON.stringify(ovState.undo[ovState.undo.length - 1]));
  ovReloadCanvasFromLayout();
}

function ovRedo() {
  if (!ovState.redo || !ovState.redo.length) return;
  const s = ovState.redo.pop();
  ovState.undo.push(s);
  ovState.layout = JSON.parse(JSON.stringify(s));
  ovReloadCanvasFromLayout();
}

function ovReloadCanvasFromLayout() {
  ovBuildCanvas();
  if (ovState.sel && !ovState.shadow.getElementById(ovState.sel)) ovState.sel = null;
  ovRenderPanel(); ovPositionSel(); ovHistButtons();
}

function ovHistButtons() {
  const u = $('overlay-undo'), r = $('overlay-redo');
  if (u) u.disabled = !ovState.undo || ovState.undo.length < 2;
  if (r) r.disabled = !ovState.redo || !ovState.redo.length;
}
```

- [ ] **Step 3: Add the toolbar buttons** before `#overlay-save`.

Find (line ~691):

```html
            <button id="overlay-save" onclick="saveOverlay()">
```

Insert immediately before it:

```html
            <button id="overlay-undo" onclick="ovUndo()" disabled title="Undo (Ctrl/Cmd-Z)">↶ Undo</button>
            <button id="overlay-redo" onclick="ovRedo()" disabled title="Redo (Ctrl/Cmd-Shift-Z)">↷ Redo</button>
```

- [ ] **Step 4: Add disabled-state CSS** after the `textarea.css-editor:disabled` rule (line ~292).

Find:

```css
  textarea.css-editor:disabled { opacity:.5; cursor:not-allowed; }
```

Insert after it:

```css
  #overlay-undo:disabled, #overlay-redo:disabled { opacity:.4; cursor:not-allowed; }
```

- [ ] **Step 5: Commit one entry per drag.** In `ovStartDrag`, find the `up()` handler (line ~3030):

```javascript
  function up() {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
  }
```

Replace with:

```javascript
  function up() {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    const e2 = ovState.shadow.getElementById(id);
    if (e2 && (e2.offsetLeft !== sl || e2.offsetTop !== st)) ovCommit();
  }
```

- [ ] **Step 6: Commit one entry per resize.** In `ovStartResize`, find the `up()` handler (line ~3051):

```javascript
  function up() {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
  }
```

Replace with:

```javascript
  function up() {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    if (el.offsetWidth !== sw || el.offsetHeight !== sh) ovCommit();
  }
```

- [ ] **Step 7: Commit on number-field change.** In `ovNumField`, find (line ~3119):

```javascript
  i.oninput = () => ovSetProp(ovState.sel, prop, i.value === '' ? '' : Number(i.value));
  ovState.fields[prop] = i; wrap.appendChild(i);
```

Replace with:

```javascript
  i.oninput = () => ovSetProp(ovState.sel, prop, i.value === '' ? '' : Number(i.value));
  i.onchange = () => ovCommit();
  ovState.fields[prop] = i; wrap.appendChild(i);
```

- [ ] **Step 8: Commit on color-field change.** In `ovColorField`, find (lines ~3132-3134):

```javascript
  c.oninput = () => { t.value = c.value; ovSetProp(ovState.sel, prop, c.value); };
  t.oninput = () => ovSetProp(ovState.sel, prop, t.value);
  ovState.fields[prop] = t;
```

Replace with:

```javascript
  c.oninput = () => { t.value = c.value; ovSetProp(ovState.sel, prop, c.value); };
  c.onchange = () => ovCommit();
  t.oninput = () => ovSetProp(ovState.sel, prop, t.value);
  t.onchange = () => ovCommit();
  ovState.fields[prop] = t;
```

- [ ] **Step 9: Commit on select change.** In `ovSelectField`, find (line ~3148):

```javascript
  s.onchange = () => ovSetProp(ovState.sel, prop, s.value);
```

Replace with:

```javascript
  s.onchange = () => { ovSetProp(ovState.sel, prop, s.value); ovCommit(); };
```

- [ ] **Step 10: Commit on the Visible toggle.** In `ovRenderPanel`, find (line ~3245):

```javascript
    cb.onchange = () => ovSetProp(id, 'visible', cb.checked ? '' : false);
```

Replace with:

```javascript
    cb.onchange = () => { ovSetProp(id, 'visible', cb.checked ? '' : false); ovCommit(); };
```

- [ ] **Step 11: Commit on Reset slot.** In `ovResetSlot`, find (lines ~3348-3349):

```javascript
  ovPositionSel();
  ovRenderPanel();
}
```

Replace with:

```javascript
  ovPositionSel();
  ovRenderPanel();
  ovCommit();
}
```

- [ ] **Step 12: Commit on shadow edits.** In `ovShadowField`, find the `numIn` helper and the color input (lines ~3174-3184):

```javascript
  const numIn = (key, ph, val) => {
    const i = document.createElement('input'); i.type = 'number';
    i.placeholder = ph; i.value = (val !== undefined ? val : '');
    i.oninput = () => ovSetShadow(ovState.sel, key, i.value);
    return i;
  };
```

Replace with:

```javascript
  const numIn = (key, ph, val) => {
    const i = document.createElement('input'); i.type = 'number';
    i.placeholder = ph; i.value = (val !== undefined ? val : '');
    i.oninput = () => ovSetShadow(ovState.sel, key, i.value);
    i.onchange = () => ovCommit();
    return i;
  };
```

Then find (line ~3184):

```javascript
  c.oninput = () => ovSetShadow(ovState.sel, 'color', c.value);
```

Replace with:

```javascript
  c.oninput = () => ovSetShadow(ovState.sel, 'color', c.value);
  c.onchange = () => ovCommit();
```

- [ ] **Step 13: Commit on font pick.** In `ovPopulateFontSelect`, find (line ~3105):

```javascript
  sel.onchange = () => onpick(sel.value, sel);
```

Replace with:

```javascript
  sel.onchange = () => { onpick(sel.value, sel); ovCommit(); };
```

- [ ] **Step 14: Initialise history on load.** In `loadOverlay`, find (line ~2838):

```javascript
  ovPopulateSlotPicker();
  ovRefreshFontUI();
}
```

Replace with:

```javascript
  ovPopulateSlotPicker();
  ovRefreshFontUI();
  ovHistInit();
}
```

- [ ] **Step 15: Add keyboard shortcuts.** After the Esc-closes-modal listener (line ~3462):

```javascript
// Esc closes the modal (only when it's open).
window.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !$('ov-modal').hidden) closeBuilderModal();
});
```

Insert after it:

```javascript
// Undo/redo shortcuts — only when the builder canvas exists and focus is NOT in a
// form field (so number/color inputs and the Advanced-CSS textarea keep native undo).
window.addEventListener('keydown', e => {
  if (!ovState.shadow) return;
  const tn = e.target && e.target.tagName;
  if (tn === 'INPUT' || tn === 'TEXTAREA' || tn === 'SELECT') return;
  if (!(e.ctrlKey || e.metaKey)) return;
  const k = e.key.toLowerCase();
  if (k === 'z' && !e.shiftKey) { e.preventDefault(); ovUndo(); }
  else if ((k === 'z' && e.shiftKey) || k === 'y') { e.preventDefault(); ovRedo(); }
});
```

- [ ] **Step 16: Verify in the dev build.**

Hard-reload the Overlay Builder. Confirm:
- Undo/Redo buttons start **disabled**.
- Drag a slot → Undo enables; click **Undo** → slot returns; **Redo** → slot moves back.
- Edit a Left value (type + Tab), change a Text color, change an enum select → each is one undo step.
- `Ctrl/Cmd-Z` / `Ctrl/Cmd-Shift-Z` work when not focused in a field; typing in the Advanced-CSS textarea still uses the browser's own undo (Ctrl-Z there does not trigger the builder undo).
- Switch profile → history resets (Undo disabled again).
- Console (F12): no errors.

- [ ] **Step 17: Python suite stays green.**

Run: `python3 tools/run-tests.py`
Expected: all pass (unchanged — no Python touched).

- [ ] **Step 18: Commit.**

```bash
git add src/ui/control-center.html
git commit -m "feat(builder): undo/redo for visual overlay edits (buttons + Ctrl/Cmd-Z)"
```

---

## Task 3: Align-to-canvas toolbar

**Files:**
- Modify: `src/ui/control-center.html` (CSS ~314; new `ovAlignBtn`/`ovAlignRow` helpers near `ovNumField` ~3113; `ovRenderPanel` Left/Top block ~3254)

**Interfaces:**
- Consumes: `OV_CANVAS_W`/`OV_CANVAS_H` (Task 1), `ovSetProp`, `ovCommit` (Task 2), `ovState.shadow`.
- Produces: `ovAlignRow(id, hasH, hasV)` (used by `ovRenderPanel`).

- [ ] **Step 1: Add the align helpers** immediately before `ovNumField` (line ~3114).

```javascript
// Align the selected slot to the canvas (center on an axis, or pin to an edge).
// Size is read from the rendered shadow element (cascade ground-truth, correct
// whether or not width/height are overridden). Each action goes through ovSetProp
// (so the canvas, selection box, and number fields sync) + ovCommit (one undo step).
function ovAlignBtn(label, title, fn) {
  const b = document.createElement('button');
  b.type = 'button'; b.className = 'ov-align-btn'; b.textContent = label;
  b.title = title; b.onclick = fn;
  return b;
}

function ovAlignRow(id, hasH, hasV) {
  const wrap = document.createElement('div');
  const l = document.createElement('label'); l.textContent = 'Align to canvas';
  wrap.appendChild(l);
  const row = document.createElement('div'); row.className = 'ov-alignrow';
  const el = () => ovState.shadow.getElementById(id);
  const set = (prop, val) => { ovSetProp(id, prop, val); ovCommit(); };
  if (hasH) row.append(
    ovAlignBtn('⇤', 'Align left edge', () => set('left', 0)),
    ovAlignBtn('H', 'Center horizontally',
      () => set('left', Math.round((OV_CANVAS_W - el().offsetWidth) / 2))),
    ovAlignBtn('⇥', 'Align right edge',
      () => set('left', OV_CANVAS_W - el().offsetWidth)));
  if (hasV) row.append(
    ovAlignBtn('⤒', 'Align top edge', () => set('top', 0)),
    ovAlignBtn('V', 'Center vertically',
      () => set('top', Math.round((OV_CANVAS_H - el().offsetHeight) / 2))),
    ovAlignBtn('⤓', 'Align bottom edge',
      () => set('top', OV_CANVAS_H - el().offsetHeight)));
  wrap.appendChild(row);
  return wrap;
}
```

- [ ] **Step 2: Render the align row** under the Left/Top fields. In `ovRenderPanel`, find (lines ~3249-3254):

```javascript
  if (has('left') || has('top')) {
    const g = grid();
    if (has('left')) g.appendChild(ovNumField('left', 'Left (px)', view));
    if (has('top')) g.appendChild(ovNumField('top', 'Top (px)', view));
    panel.appendChild(g);
  }
```

Replace with:

```javascript
  if (has('left') || has('top')) {
    const g = grid();
    if (has('left')) g.appendChild(ovNumField('left', 'Left (px)', view));
    if (has('top')) g.appendChild(ovNumField('top', 'Top (px)', view));
    panel.appendChild(g);
    panel.appendChild(ovAlignRow(id, has('left'), has('top')));
  }
```

- [ ] **Step 3: Add the button CSS** after the `.ovinline` rule (line ~314).

Find:

```css
  .ovinline { display:flex; gap:6px; align-items:center; }
```

Insert after it:

```css
  .ov-alignrow { display:flex; gap:4px; margin:6px 0 0; }
  .ov-align-btn { flex:1 1 0; min-width:0; background:#232C42; color:var(--txt);
             border:1px solid var(--line); border-radius:6px; padding:4px 0;
             font:12px var(--mono); cursor:pointer; }
  .ov-align-btn:hover { border-color:var(--accent); }
```

- [ ] **Step 4: Verify in the dev build.**

Hard-reload, select **Flag status**: an "Align to canvas" row of 6 buttons appears under Left/Top. Click **H** → Left becomes **780** (the number field updates, the slot recenters); **⇥** → Left = 1560; **V** → Top centers; each is one undo step (Undo reverts it). Select a text-only slot with only horizontal props → only the 3 horizontal buttons show. Console: no errors.

- [ ] **Step 5: Commit.**

```bash
git add src/ui/control-center.html
git commit -m "feat(builder): align-to-canvas toolbar (center H/V + edges) in property editor"
```

---

## Task 4: Grid overlay + optional snap

**Files:**
- Modify: `src/ui/control-center.html` (CSS ~314; grid bar markup ~696; `OV_SHADOW_CSS` ~2803; `ovState` ~2774; grid helpers near `loadOverlay`; `loadOverlay` ~2816 & ~2838; `ovBuildCanvas` ~2887; `ovStartDrag`/`ovStartResize` move handlers)

**Interfaces:**
- Consumes: `ovState`, `$`.
- Produces: `ovGridLoad()`, `ovUpdateGrid()`, `ovSnap(v)`, `ovGridToggle`/`ovGridSetSize`/`ovGridSnap`/`ovGridSyncControls`, `ovState.grid`, `ovState.gridEl`.

- [ ] **Step 1: Add grid state to `ovState`.**

Find (the `ovState` line from Task 2, now ending `… fields: {}, undo: [], redo: []};`):

```javascript
                 shadow: null, selBox: null, fields: {}, undo: [], redo: []};
```

Replace with:

```javascript
                 shadow: null, selBox: null, fields: {}, undo: [], redo: [],
                 grid: {show: false, size: 10, snap: false}, gridEl: null};
```

- [ ] **Step 2: Add the grid helpers** immediately after `ovHistButtons` (from Task 2).

```javascript
// ----- Reference grid (editor aid; NEVER serialised into the layout/override.css) -----
function ovGridLoad() {
  const g = {show: false, size: 10, snap: false};
  try { Object.assign(g, JSON.parse(localStorage.getItem('rc.ov.grid') || '{}')); }
  catch (e) { /* ignore corrupt prefs */ }
  g.size = Math.max(1, parseInt(g.size, 10) || 10);
  g.show = !!g.show; g.snap = !!g.snap;
  ovState.grid = g;
}
function ovGridSave() {
  try { localStorage.setItem('rc.ov.grid', JSON.stringify(ovState.grid)); } catch (e) {}
}
function ovUpdateGrid() {
  const g = ovState.gridEl;
  if (!g) return;
  if (!ovState.grid.show) { g.style.backgroundImage = 'none'; return; }
  const sz = Math.max(1, ovState.grid.size | 0);
  const minor = 'rgba(120,170,255,.16)', major = 'rgba(120,170,255,.34)';
  const lines = (c, s) =>
    'repeating-linear-gradient(0deg,' + c + ' 0 1px,transparent 1px ' + s + 'px),' +
    'repeating-linear-gradient(90deg,' + c + ' 0 1px,transparent 1px ' + s + 'px)';
  // major listed first => painted on top of the minor grid
  g.style.backgroundImage = lines(major, sz * 10) + ',' + lines(minor, sz);
}
function ovSnap(v) {
  if (!ovState.grid || !ovState.grid.snap) return v;
  const s = Math.max(1, ovState.grid.size | 0);
  return Math.round(v / s) * s;
}
function ovGridToggle(on) { ovState.grid.show = !!on; ovGridSave(); ovUpdateGrid(); }
function ovGridSetSize(v) {
  ovState.grid.size = Math.max(1, parseInt(v, 10) || 1);
  if ($('ov-grid-size')) $('ov-grid-size').value = ovState.grid.size;
  ovGridSave(); ovUpdateGrid();
}
function ovGridSnap(on) { ovState.grid.snap = !!on; ovGridSave(); }
function ovGridSyncControls() {
  if ($('ov-grid-show')) $('ov-grid-show').checked = ovState.grid.show;
  if ($('ov-grid-size')) $('ov-grid-size').value = ovState.grid.size;
  if ($('ov-grid-snap')) $('ov-grid-snap').checked = ovState.grid.snap;
}
```

- [ ] **Step 3: Create the grid element in `ovBuildCanvas`.** Find (lines ~2886-2888):

```javascript
  sh.innerHTML = '<style>' + ovState.baseCss + '\n' + OV_SHADOW_CSS + '\n' +
    ovFontFaceCss() + '</style>' + ovState.body;
  const sel = document.createElement('div');
```

Replace with:

```javascript
  sh.innerHTML = '<style>' + ovState.baseCss + '\n' + OV_SHADOW_CSS + '\n' +
    ovFontFaceCss() + '</style>' + ovState.body;
  // Reference grid: inserted right after <style> (before the slots) + pointer-events
  // none, so it paints UNDER the slots and over the Overlay.png backdrop.
  ovState.gridEl = document.createElement('div');
  ovState.gridEl.className = 'ov-grid';
  const st0 = sh.querySelector('style');
  sh.insertBefore(ovState.gridEl, st0 ? st0.nextSibling : sh.firstChild);
  ovUpdateGrid();
  const sel = document.createElement('div');
```

- [ ] **Step 4: Add the `.ov-grid` rule to `OV_SHADOW_CSS`.** Find (lines ~2801-2803):

```javascript
  '.ov-hidden{opacity:.32!important;outline:2px dashed #f59e0b!important;outline-offset:-1px}' +
  '.ov-hidden::after{content:"hidden";position:absolute;top:0;left:0;z-index:60;' +
  'font:700 9px/1.4 system-ui,sans-serif;background:#f59e0b;color:#111;padding:0 3px;border-radius:2px}';
```

Replace with:

```javascript
  '.ov-hidden{opacity:.32!important;outline:2px dashed #f59e0b!important;outline-offset:-1px}' +
  '.ov-hidden::after{content:"hidden";position:absolute;top:0;left:0;z-index:60;' +
  'font:700 9px/1.4 system-ui,sans-serif;background:#f59e0b;color:#111;padding:0 3px;border-radius:2px}' +
  '.ov-grid{position:absolute;inset:0;pointer-events:none}';
```

- [ ] **Step 5: Load prefs + sync controls in `loadOverlay`.** Find (line ~2816):

```javascript
  ovState.page = overlayPage;
```

Replace with:

```javascript
  ovGridLoad();
  ovState.page = overlayPage;
```

Then find (the block from Task 2, line ~2838):

```javascript
  ovPopulateSlotPicker();
  ovRefreshFontUI();
  ovHistInit();
}
```

Replace with:

```javascript
  ovPopulateSlotPicker();
  ovRefreshFontUI();
  ovHistInit();
  ovGridSyncControls();
}
```

- [ ] **Step 6: Add the grid toolbar row** after the builder head. Find (lines ~696-697):

```html
              <svg viewBox="0 0 24 24"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z"/><circle cx="12" cy="12" r="3"/></svg>Preview ↗</button></div>
          <div class="enverr" id="overlay-err" hidden></div>
```

Replace with:

```html
              <svg viewBox="0 0 24 24"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z"/><circle cx="12" cy="12" r="3"/></svg>Preview ↗</button></div>
          <div class="ovgridbar">
            <label><input type="checkbox" id="ov-grid-show" onchange="ovGridToggle(this.checked)"> Grid</label>
            <label>Size <input type="number" id="ov-grid-size" min="1" value="10" onchange="ovGridSetSize(this.value)"></label>
            <button type="button" class="ov-gpreset" onclick="ovGridSetSize(5)">5</button>
            <button type="button" class="ov-gpreset" onclick="ovGridSetSize(10)">10</button>
            <button type="button" class="ov-gpreset" onclick="ovGridSetSize(20)">20</button>
            <label><input type="checkbox" id="ov-grid-snap" onchange="ovGridSnap(this.checked)"> Snap to grid</label>
          </div>
          <div class="enverr" id="overlay-err" hidden></div>
```

- [ ] **Step 7: Add the grid-bar CSS** after the `.ov-align-btn:hover` rule (from Task 3, line ~314 area).

Find:

```css
  .ov-align-btn:hover { border-color:var(--accent); }
```

Insert after it:

```css
  .ovgridbar { display:flex; align-items:center; gap:10px; flex-wrap:wrap;
             margin:0 0 8px; font:12px var(--mono); color:var(--dim); }
  .ovgridbar label { display:inline-flex; align-items:center; gap:4px; margin:0; }
  .ovgridbar input[type=number] { width:64px; background:#232C42; color:var(--txt);
             border:1px solid var(--line); border-radius:6px; padding:4px 6px;
             font:12px var(--mono); }
  .ovgridbar .ov-gpreset { background:#232C42; color:var(--txt);
             border:1px solid var(--line); border-radius:6px; padding:3px 8px;
             font:12px var(--mono); cursor:pointer; }
  .ovgridbar .ov-gpreset:hover { border-color:var(--accent); }
```

- [ ] **Step 8: Snap drag to the grid.** In `ovStartDrag`, find (lines ~3026-3029):

```javascript
  function move(ev) {
    ovSetProp(id, 'left', sl + Math.round((ev.clientX - sx) / ovState.scale));
    ovSetProp(id, 'top', st + Math.round((ev.clientY - sy) / ovState.scale));
  }
```

Replace with:

```javascript
  function move(ev) {
    ovSetProp(id, 'left', ovSnap(sl + Math.round((ev.clientX - sx) / ovState.scale)));
    ovSetProp(id, 'top', ovSnap(st + Math.round((ev.clientY - sy) / ovState.scale)));
  }
```

- [ ] **Step 9: Snap resize to the grid.** In `ovStartResize`, find (lines ~3048-3049):

```javascript
    if (dir === 'se' || dir === 'e') ovSetProp(id, 'width', Math.max(8, sw + dx));
    if (dir === 'se' || dir === 's') ovSetProp(id, 'height', Math.max(8, sh + dy));
```

Replace with:

```javascript
    if (dir === 'se' || dir === 'e') ovSetProp(id, 'width', Math.max(8, ovSnap(sw + dx)));
    if (dir === 'se' || dir === 's') ovSetProp(id, 'height', Math.max(8, ovSnap(sh + dy)));
```

- [ ] **Step 10: Verify in the dev build.**

Hard-reload. Confirm:
- A grid bar (Grid checkbox, Size input, 5/10/20 presets, Snap checkbox) sits under the toolbar.
- Tick **Grid** → faint lines overlay the canvas, aligned to `Overlay.png`, with stronger lines every 10th; the grid scales when you resize the window / pop out the modal.
- Change Size (free + presets) → spacing updates live.
- Tick **Snap to grid**, drag/resize a slot → it rounds to the spacing; typed Left/Top values and the align buttons remain exact.
- Reload the page → Grid/Size/Snap prefs persist; **Save** the overlay, then inspect `profiles/<active>/overlay/layout-hud.json` and `hud.css` → **no** grid keys are present (grid never serialised).
- Console: no errors.

- [ ] **Step 11: Python suite stays green.**

Run: `python3 tools/run-tests.py`
Expected: all pass.

- [ ] **Step 12: Commit.**

```bash
git add src/ui/control-center.html
git commit -m "feat(builder): reference grid overlay with configurable spacing + optional snap"
```

---

## Task 5: Refresh the wiki screenshot

**Files:**
- Modify: `src/docs/wiki/images/cc-overlay-builder.png` (+ any slides copy under `src/docs/slides/assets/img/`)

- [ ] **Step 1: Confirm lint is clean** (guard before the visual step).

Run: `python3 tools/lint.py`
Expected: no findings (no Python changed; this is the CI lint job).

- [ ] **Step 2: Regenerate the screenshot** using the `wiki-screenshots` skill against a local dev build (no `VERSION` stamped, so the badge stays "dev build" — see the wiki rule). The skill drives a running dev-build instance and takes an **element** screenshot of `#ov-modal .ovmodal-card` so the framing matches the existing image. The builder now shows the grid bar, Undo/Redo buttons, and (with a slot selected) the align row.

- [ ] **Step 3: Confirm the image changed and is committed alongside the code.**

```bash
git status --porcelain src/docs/wiki/images/cc-overlay-builder.png
```

- [ ] **Step 4: Commit.**

```bash
git add src/docs/wiki/images/cc-overlay-builder.png src/docs/slides/assets/img/
git commit -m "docs(wiki): refresh overlay-builder screenshot (align/undo/grid controls)"
```

---

## Self-Review

**Spec coverage:**
- Shared constants → Task 1. ✓
- A) align toolbar (center H/V + edges, gated per axis, via ovSetProp+ovCommit) → Task 3. ✓
- B) undo/redo (snapshot stacks, coalesced commit sites, buttons + shortcuts, textarea excluded, reset on load) → Task 2. ✓
- C) grid (shadow element, configurable spacing + presets, localStorage, never serialised) + optional snap (drag/resize only) → Task 4. ✓
- Wiki screenshot → Task 5. ✓
- Verification (manual dev build, Python suite green, lint) → in each task. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every step shows the exact find/replace code.

**Type/name consistency:** `ovCommit`, `ovHistInit`, `ovUndo`, `ovRedo`, `ovReloadCanvasFromLayout`, `ovHistButtons` (Task 2) are used consistently by Task 3 (`ovCommit`) and Task 4 (helpers after `ovHistButtons`). `OV_CANVAS_W`/`OV_CANVAS_H` (Task 1) used in Tasks 3-4. `ovSnap`, `ovUpdateGrid`, `ovState.grid`/`ovState.gridEl` consistent within Task 4. The `ovState` literal is extended once per task (Task 2 adds `undo/redo`, Task 4 adds `grid/gridEl`) — Task 4's find string matches Task 2's output.

**Ordering dependency:** Task 3 (align) calls `ovCommit` → must follow Task 2. Task 4 snap relies on the drag/resize `ovCommit` from Task 2 but is otherwise independent. Tasks must be executed in numeric order.
