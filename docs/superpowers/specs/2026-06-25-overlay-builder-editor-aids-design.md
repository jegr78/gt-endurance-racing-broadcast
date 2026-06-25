# Visual builder — editor aids: align toolbar, undo/redo, grid — design

Date: 2026-06-25

## Summary

Three front-end-only quality-of-life additions to the Control Center's visual
overlay builder (`src/ui/control-center.html`), all routed through the builder's
existing seams (`ovSetProp`, `ovState`, `ovBuildCanvas`):

- **A) Align-to-canvas toolbar** — per-slot buttons in the property editor that
  center a slot on the canvas (horizontally / vertically) or pin it to a canvas
  edge (left/right/top/bottom). Solves "place Flag status dead-center" without the
  operator computing `(1920 − width)/2` by hand.
- **B) Undo/Redo** — a snapshot history of the in-memory layout (visual/slot edits
  only), with toolbar buttons and `Ctrl/Cmd-Z` / `Ctrl/Cmd-Shift-Z` shortcuts.
- **C) Grid overlay + optional snap** — a toggleable reference grid on the canvas
  with a configurable spacing (free px + 5/10/20 presets), and an independent
  "snap to grid" toggle that rounds drag/resize to the grid.

No server, compiler, route, or Python-test change. The grid is an editor-only aid
and is **never** written to the layout / profile / `override.css`.

## Background (current state)

- The builder renders the base page's `<style>` + slot markup into a Shadow-DOM
  canvas (`#ov-stage`, fixed `1920×1080`, scaled via `transform`) over the league's
  `Overlay.png`; drag/resize edits an in-memory `ovState.layout` model that the
  server compiles into `override.css`. (`src/ui/control-center.html:2765` ff.)
- **Single mutation funnel:** every scalar property change goes through
  `ovSetProp(id, prop, value)` (`:2976`) — used by drag (`ovStartDrag` `:3021`),
  resize (`ovStartResize` `:3038`), number fields (`ovNumField` `:3114`), color
  fields (`ovColorField` `:3124`), and selects (`ovSelectField` `:3139`).
  Compound/edge cases have their own funnels: `ovSetShadow` (`:3153`),
  `ovSetBodyFont` (`:3369`), `ovResetSlot` (`:3342`), font picks (`ovPickFont`
  `:3109`).
- The property panel is rebuilt per selected slot by `ovRenderPanel` (`:3220`); the
  Left/Top number fields live in its first `grid()` block (`:3249-3254`).
- `ovBuildCanvas` (`:2881`) (re)builds the shadow canvas from `ovState.body` +
  `ovState.baseCss`, attaches drag handlers, styles each slot from
  `ovState.layout`, and appends the selection box (`z-index:50`). Re-callable.
- `loadOverlay` (`:2805`) loads slots/layout/fonts and resets selection — the
  natural place to (re)initialise per-session editor state on profile/page switch.
- The canvas width `1920` is currently a magic number in `ovFitCanvas`
  (`:2996`, `wrap.clientWidth / 1920`); height `1080` lives only in the
  `.ovcanvas` CSS (`:300`). There is **no** undo, grid, or align logic today.
- There is **no JS unit-test harness** in the repo (tests are stdlib Python and do
  not exercise `control-center.html`), so these features are verified manually
  against a local dev build.

## Design

### Shared

Introduce two module-level constants as the single source of canvas dimensions,
reused by both align and grid:

```javascript
const OV_CANVAS_W = 1920, OV_CANVAS_H = 1080;
```

Replace the `1920` literal in `ovFitCanvas` with `OV_CANVAS_W`.

### A) Align-to-canvas toolbar (property editor)

In `ovRenderPanel`, right after the Left/Top `grid()` block, append a compact
button group **"Align to canvas"**, gated per axis by the slot's allowed props
(`has('left')` for horizontal actions, `has('top')` for vertical):

- Horizontal: **⇤ Left** (`left=0`), **H Center**
  (`left = round((OV_CANVAS_W − w)/2)`), **⇥ Right** (`left = OV_CANVAS_W − w`).
- Vertical: **⤒ Top** (`top=0`), **V Center**
  (`top = round((OV_CANVAS_H − h)/2)`), **⤓ Bottom** (`top = OV_CANVAS_H − h`).

`w`/`h` are read from the **rendered** shadow element
(`el.offsetWidth`/`offsetHeight`) — the cascade ground-truth, correct whether or
not width/height are overridden. Each button calls
`ovSetProp(id, 'left'|'top', value)`, so the canvas, the selection box, and the
Left/Top number fields update through the existing path, and the change is captured
by Undo (B). For `flag-status` (w=360), **H Center → left = 780**.

**Approach:** purely additive in the panel, no new state. Rejected alternative: a
free "align relative to another slot" tool — out of scope (YAGNI); the ask is
canvas-relative only.

### B) Undo/Redo (visual edits only)

Two snapshot stacks on `ovState`: `undo` and `redo`, each holding deep JSON clones
of `ovState.layout` (the model is small — ~30 slots × a few props). Helpers:

```javascript
function ovSnap_() { return JSON.parse(JSON.stringify(ovState.layout)); }
function ovHistInit() { ovState.undo = [ovSnap_()]; ovState.redo = []; ovHistButtons(); }
function ovCommit() {                                   // after ONE logical edit
  ovState.undo.push(ovSnap_());
  if (ovState.undo.length > 50) ovState.undo.shift();
  ovState.redo = []; ovHistButtons();
}
function ovUndo() {
  if (ovState.undo.length < 2) return;
  ovState.redo.push(ovState.undo.pop());               // pop current
  ovState.layout = JSON.parse(JSON.stringify(ovState.undo[ovState.undo.length - 1]));
  ovReloadCanvasFromLayout();
}
function ovRedo() {
  if (!ovState.redo.length) return;
  const s = ovState.redo.pop();
  ovState.undo.push(s);
  ovState.layout = JSON.parse(JSON.stringify(s));
  ovReloadCanvasFromLayout();
}
```

**Invariant:** `ovState.undo`'s top always equals the last committed layout, so
`ovUndo` reverts to the new top and `ovRedo` reapplies — no per-prop inverse
operations needed.

`ovReloadCanvasFromLayout()` rebuilds from the restored layout while preserving
selection:

```javascript
function ovReloadCanvasFromLayout() {
  ovBuildCanvas();
  if (ovState.sel && !ovState.shadow.getElementById(ovState.sel)) ovState.sel = null;
  ovRenderPanel(); ovPositionSel(); ovHistButtons();
}
```

It deliberately does **not** touch the Advanced-CSS textarea (`#overlayCss`) — that
field keeps its native browser text-undo (out of scope). `ovState.layout.customCss`
is only reconciled from the textarea at `saveOverlay` time, as today.

**`ovCommit()` call sites (one coalesced entry per logical edit):**

- `ovStartDrag`/`ovStartResize`: call once in the `up()` handler, only if the value
  actually changed (compare start vs. final left/top or width/height).
- `ovNumField`: keep `oninput` for live preview; add `onchange` → `ovCommit()`
  (fires on blur/Enter → one entry per field edit, not per keystroke).
- `ovColorField`: `onchange` on both the color and text inputs (the native color
  picker fires `input` repeatedly while dragging, `change` once on close).
- `ovSelectField`, the Visible checkbox, `ovResetSlot`, the align buttons,
  `ovPickFont`/`ovSetBodyFont`, and `ovSetShadow` (its inputs' `change`): call
  `ovCommit()` after applying.

**UI:** **↶ Undo** / **↷ Redo** buttons in the builder toolbar (next to Save),
disabled by `ovHistButtons()` when their stack can't move. **Keyboard:** a
`keydown` listener handles `Ctrl/Cmd-Z` (undo) and `Ctrl/Cmd-Shift-Z` / `Ctrl-Y`
(redo) **only** when `ovState.shadow` exists and `e.target` is not an
`INPUT`/`TEXTAREA`/`SELECT` (so form fields and the Advanced-CSS textarea keep
their own undo). It reuses the existing builder lifetime; no new global state beyond
`ovState`.

`ovHistInit()` is called at the end of `loadOverlay`, so history resets on every
profile/page switch.

**Approach:** snapshot stack over a command pattern — simplest and robust for a
small model; no inverse op per prop type. Memory is trivial (50 small JSON clones).

### C) Grid overlay + optional snap

**Visual grid.** Add a non-interactive grid element inside the shadow root in
`ovBuildCanvas` (sibling of the slots, below them and the selection box):

```css
.ov-grid { position:absolute; inset:0; pointer-events:none; z-index:1; }
```

`ovUpdateGrid()` sets its `background-image` to two `repeating-linear-gradient`s
(vertical + horizontal) at `ovState.grid.size` px in 1920-space (so spacing scales
with the host `transform` and aligns to `Overlay.png`), and toggles visibility from
`ovState.grid.show`. Minor lines are faint (`rgba(120,170,255,.16)`); every 10th
line is slightly stronger for orientation (a second gradient pair at `size*10`).
`ovBuildCanvas` creates the element and calls `ovUpdateGrid()`; size/show changes
call only `ovUpdateGrid()` (no full rebuild).

**Toolbar controls:** a **Grid** checkbox, a spacing number input (free px, default
**10**, min 1) with **5 / 10 / 20** quick-pick buttons, and an **independent**
**Snap** checkbox.

**State + persistence:** `ovState.grid = {show:false, size:10, snap:false}`,
mirrored to `localStorage` (key e.g. `rc.ov.grid`) on change and restored on load.
It is an **editor preference** — never written to `ovState.layout`, the profile, or
`override.css` (it is not a slot prop; the compiler never sees it).

**Snap.** When `ovState.grid.snap` is true, drag and resize round to the grid via
`ovSnap(v) = Math.round(v / ovState.grid.size) * ovState.grid.size` (resize still
clamps to `Math.max(8, …)`). Applied **only** inside `ovStartDrag`/`ovStartResize`
`move()` — typed values and align buttons stay exact. Snap works whether or not the
grid is shown.

**Approach:** grid lives in the scaled shadow host (not a separate overlay div) so
the spacing needs no scale math and overlays `Overlay.png` exactly. Rejected:
baking the grid into the served HUD/`override.css` — it is a design aid, must not
reach OBS.

## Error / edge handling

- Align on a slot missing the relevant axis prop: the button isn't rendered (gated
  by `has(...)`).
- Undo with an empty / one-entry stack: no-op (guarded); buttons disabled.
- A slot that vanished between snapshots (none expected — slot set is fixed per
  page) is dropped from selection in `ovReloadCanvasFromLayout`.
- Grid size ≤ 0 or non-numeric: clamp to ≥ 1 before use; `localStorage` parse
  failure falls back to the defaults.
- No demo/example overlay files change → the
  `t_shipped_demo_overlay_css_matches_its_layout` sync guard stays green.

## Testing

No JS harness exists, so verification is **manual** against a local dev build
(`racecast ui` from `src/`, demo / `erf-nls` profile — `racecast-local-uat` data
copy-in):

- **Align:** select Flag status → **H Center** sets Left to **780**; edge buttons
  pin to 0 / `1920−w` / 0 / `1080−h`; the Left/Top fields and canvas update.
- **Undo/Redo:** drag a slot, edit a number field, change a color → each `Ctrl-Z`
  reverts exactly one logical edit; `Ctrl-Shift-Z` reapplies; buttons enable/disable
  correctly; typing in the Advanced-CSS textarea still uses native undo; switching
  profile/page resets history.
- **Grid:** toggle on/off, change spacing (free + presets), confirm lines align to
  `Overlay.png` and scale with the window; enable Snap → drag/resize round to the
  spacing while typed values stay exact; reload the page → grid prefs persist and
  the layout/`override.css` are unchanged (grid never serialised).

The existing Python suite (`tools/run-tests.py`) must stay green (unchanged — no
server/compiler edit).

## Documentation

- Refresh `src/docs/wiki/images/cc-overlay-builder.png` (+ the slides copy under
  `src/docs/slides/assets/img/`) in the **same change** — the builder toolbar and
  property panel gain visible controls (`wiki-screenshots` skill, local dev build,
  element screenshot of `#ov-modal .ovmodal-card` to match framing).

## Out of scope (YAGNI)

- No align-relative-to-another-slot, no distribute/space-evenly.
- Undo does not cover the Advanced-CSS textarea (native text-undo there).
- Grid is not persisted per profile and never compiled into the overlay.
- No snap-to-other-slots / smart guides.

## Decomposition

One spec, three independent parts (A / B / C). They share the toolbar and canvas
seams but have no functional dependency, so they can land as separate commits (and,
if desired, separate PRs). The wiki screenshot is refreshed once, after the last
visible part merges.

## Files touched

- `src/ui/control-center.html` — `OV_CANVAS_W`/`OV_CANVAS_H` constants; align button
  group in `ovRenderPanel`; undo/redo stacks + helpers + toolbar buttons + keyboard
  handler + `ovHistInit` in `loadOverlay` + `ovCommit` call sites; grid element +
  `ovUpdateGrid` + toolbar controls + `ovState.grid` (localStorage) + `ovSnap` in
  drag/resize; CSS for the new buttons and `.ov-grid`.
- `src/docs/wiki/images/cc-overlay-builder.png` (+ slides copy) — refreshed
  screenshot.
