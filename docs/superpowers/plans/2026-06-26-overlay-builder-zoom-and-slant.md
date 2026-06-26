# Overlay Builder: Canvas Zoom + Slanted Edges — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a preset canvas zoom and two slant properties (`slant` = clip-path
parallelogram with upright text; `shear` = skewX) to the visual overlay builder.

**Architecture:** `slant`/`shear` are pure-compiler additions in
`src/scripts/overlay_build.py` (new slot properties → `clip-path` / a combined
`transform`), mirrored inline by the builder canvas in
`src/ui/control-center.html`. Zoom is builder-only (toolbar + a scale state + a
scrollable sizer + the Overlay.png backdrop moved onto the scaled stage). The relay,
served pages, and layout JSON schema are otherwise unchanged.

**Tech Stack:** Python 3 stdlib (compiler + stdlib test scripts), vanilla
HTML/CSS/JS (Control Center, no framework).

## Global Constraints

- **Edit only under `src/`** (plus `tests/` and `docs/`). Never hand-edit `dist/`/`runtime/`.
- **English only** in all code and docs.
- **No new dependencies** — stdlib Python + vanilla JS only.
- Tests are runnable stdlib scripts; every test function is named `t_*` and is
  auto-collected by the file's `__main__` loop. Run a file with
  `python3 tests/test_overlay.py`.
- The builder canvas MUST mirror the compiler: any property the compiler emits must
  render identically inline on the same-origin shadow canvas.
- **CLAUDE.md hard rule:** a change to the Overlay builder surface requires refreshing
  `src/docs/wiki/images/cc-overlay-builder.png` in the SAME PR (Task 5).
- Shipping: a single PR / issue.

---

### Task 1: Compiler — `slant` property (clip-path parallelogram)

**Files:**
- Modify: `src/scripts/overlay_build.py` (`KIND_BOX`, `PROP_ORDER`, new `_slant_decl`,
  a branch in `_declaration`)
- Test: `tests/test_overlay.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_slant_decl(value) -> str | None` (a `"clip-path: polygon(...)"`
  declaration). `slant` becomes an allowed prop on every `box`/`text` slot.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_overlay.py` (after `t_ob_compile_rotation`, near line 547). They
reuse the existing `_css_x` helper + `SK` slot (already `KIND_TEXT`):

```python
def t_ob_compile_slant_clip_path():
    # positive slant leans "/"; text is untouched (no transform)
    assert ("clip-path: polygon(40px 0, 100% 0, calc(100% - 40px) 100%, 0 100%)"
            in _css_x({"slant": 40}))
    # negative slant leans "\"
    assert ("clip-path: polygon(0 0, calc(100% - 30px) 0, 100% 100%, 30px 100%)"
            in _css_x({"slant": -30}))


def t_ob_compile_slant_rejects():
    assert "clip-path" not in _css_x({"slant": 0})       # zero = no clip
    assert "clip-path" not in _css_x({"slant": 401})     # over +400
    assert "clip-path" not in _css_x({"slant": -401})    # under -400
    assert "clip-path" not in _css_x({"slant": "x"})     # non-number
    assert "clip-path" not in _css_x({"slant": True})    # bool rejected
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_overlay.py`
Expected: FAIL — `t_ob_compile_slant_clip_path` (no `clip-path` emitted; `slant` is
not yet an allowed/handled prop).

- [ ] **Step 3: Add `slant` to the box property set + emit order**

In `src/scripts/overlay_build.py`, add `"slant"` to `KIND_BOX` (currently lines
58–60). Replace:

```python
KIND_BOX = ("left", "top", "width", "height", "padding",
            "background", "borderWidth", "borderStyle", "borderColor",
            "borderRadius", "opacity", "rotation", "visible")
```

with:

```python
KIND_BOX = ("left", "top", "width", "height", "padding",
            "background", "borderWidth", "borderStyle", "borderColor",
            "borderRadius", "slant", "opacity", "rotation", "visible")
```

In `PROP_ORDER` (lines 44–50), insert `"slant"` right after `"borderRadius"`. Replace
the `"borderWidth", "borderRadius",` line with:

```python
              "borderWidth", "borderRadius", "slant",
```

- [ ] **Step 4: Add the `_slant_decl` helper**

In `src/scripts/overlay_build.py`, add this function just above `_declaration`
(before line 259, `def _declaration`):

```python
def _slant_decl(value):
    """A 'clip-path: polygon(...)' parallelogram from a signed px slant, or None.
    Sign = lean direction (+ leans '/', - leans '\\'); |value| is the horizontal
    edge offset. Both vertical edges slant equally, so text content stays upright.
    0 / out-of-range (|value| > 400) / non-number / bool -> None (no clip)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value == 0 or not -400 <= value <= 400:
        return None
    a = abs(value)
    a = int(a) if float(a).is_integer() else a
    if value > 0:
        poly = f"polygon({a}px 0, 100% 0, calc(100% - {a}px) 100%, 0 100%)"
    else:
        poly = f"polygon(0 0, calc(100% - {a}px) 0, 100% 100%, {a}px 100%)"
    return f"clip-path: {poly}"
```

- [ ] **Step 5: Wire `slant` into `_declaration`**

In `_declaration` (line ~259), add a branch for `slant` BEFORE the generic
`value = _safe_value(value)` line — right after the `visible` block. Insert:

```python
    if prop == "slant":
        return _slant_decl(value)
```

(Place it immediately after the existing
`return "display: none" if value is False else None` line that closes the `visible`
block, and before `value = _safe_value(value)`.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 tests/test_overlay.py`
Expected: PASS — `ok t_ob_compile_slant_clip_path`, `ok t_ob_compile_slant_rejects`,
and `ALL PASS` (no regressions).

- [ ] **Step 7: Commit**

```bash
git add src/scripts/overlay_build.py tests/test_overlay.py
git commit -m "feat(overlay): slant property compiles to a clip-path parallelogram"
```

---

### Task 2: Compiler — `shear` property + combined transform

**Files:**
- Modify: `src/scripts/overlay_build.py` (`KIND_BOX`, `PROP_ORDER`, new `_num_in_range`
  + `_transform_decl`, remove the `rotation` branch from `_declaration`, update
  `_slot_rule`)
- Test: `tests/test_overlay.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_num_in_range(value, lo, hi) -> (int|float)|None`;
  `_transform_decl(overrides, allowed) -> str | None` (one combined
  `"transform: rotate(Rdeg) skewX(Kdeg)"`). `shear` becomes an allowed `box`/`text`
  prop. `rotation` is now emitted via `_transform_decl`, NOT `_declaration`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_overlay.py` (after the Task 1 tests):

```python
def t_ob_compile_shear_skewx():
    assert "transform: skewX(12deg)" in _css_x({"shear": 12})
    assert "transform: skewX(-20deg)" in _css_x({"shear": -20})
    assert "transform" not in _css_x({"shear": 90})      # 90 is degenerate
    assert "transform" not in _css_x({"shear": "x"})
    assert "transform" not in _css_x({"shear": True})


def t_ob_compile_rotation_and_shear_combine():
    css = _css_x({"rotation": 15, "shear": 10})
    # ONE combined transform, rotate before skewX
    assert "transform: rotate(15deg) skewX(10deg)" in css
    assert css.count("transform:") == 1


def t_ob_compile_slant_shear_gated_by_props():
    # a slot whose props lack slant/shear drops them (no injection)
    slots = [{"id": "x", "label": "X", "props": ["left", "top"]}]
    css = ob.compile_overlay_css(
        {"slots": {"x": {"slant": 40, "shear": 12, "rotation": 5}}}, slots)
    assert "clip-path" not in css and "transform" not in css
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_overlay.py`
Expected: FAIL — `t_ob_compile_shear_skewx` (no `skewX` emitted; `shear` unhandled).

- [ ] **Step 3: Add `shear` to the box property set + emit order**

In `src/scripts/overlay_build.py`, replace `KIND_BOX` (now, after Task 1):

```python
KIND_BOX = ("left", "top", "width", "height", "padding",
            "background", "borderWidth", "borderStyle", "borderColor",
            "borderRadius", "slant", "opacity", "rotation", "visible")
```

with (add `"shear"` after `"rotation"`):

```python
KIND_BOX = ("left", "top", "width", "height", "padding",
            "background", "borderWidth", "borderStyle", "borderColor",
            "borderRadius", "slant", "opacity", "rotation", "shear", "visible")
```

In `PROP_ORDER`, replace the `"rotation", "textShadow", "visible")` tail line:

```python
              "rotation", "textShadow", "visible")
```

with (add `"shear"` after `"rotation"`):

```python
              "rotation", "shear", "textShadow", "visible")
```

- [ ] **Step 4: Add `_num_in_range` + `_transform_decl`; remove the old rotation branch**

In `src/scripts/overlay_build.py`, add both helpers just above `_slot_rule`
(before line ~313, `def _slot_rule`):

```python
def _num_in_range(value, lo, hi):
    """A normalized number (int when integral) if `value` is a real number in
    [lo, hi], else None. bool is rejected (it is an int subclass)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not lo <= value <= hi:
        return None
    return int(value) if float(value).is_integer() else value


def _transform_decl(overrides, allowed):
    """One combined 'transform: rotate(Rdeg) skewX(Kdeg)' from a slot's rotation +
    shear overrides (each gated by `allowed` and its range), or None when neither
    applies. Merging both into a SINGLE declaration prevents one transform from
    silently overriding the other (two `transform:` lines -> the later wins)."""
    parts = []
    if "rotation" in allowed:
        r = _num_in_range(overrides.get("rotation"), -360, 360)
        if r is not None:
            parts.append(f"rotate({r}deg)")
    if "shear" in allowed:
        k = _num_in_range(overrides.get("shear"), -89, 89)
        if k is not None:
            parts.append(f"skewX({k}deg)")
    return f"transform: {' '.join(parts)}" if parts else None
```

Then REMOVE the now-obsolete `rotation` branch from `_declaration` (lines ~305–309):

```python
    if prop == "rotation":
        if not isinstance(value, (int, float)) or not -360 <= value <= 360:
            return None
        num = int(value) if float(value).is_integer() else value
        return f"transform: rotate({num}deg)"
```

(Delete those five lines. The function's trailing `return None` stays.)

- [ ] **Step 5: Emit the combined transform from `_slot_rule`**

Replace `_slot_rule` (lines ~313–324) with a version that skips `rotation`/`shear`
in the per-prop loop and appends the combined transform last:

```python
def _slot_rule(slot_id, overrides, allowed):
    """A '#id { ... }' rule for one slot's overrides, gated by its allowed props.
    rotation + shear are emitted together as one combined transform (see
    _transform_decl), so they are skipped in the per-prop loop."""
    decls = []
    for prop in PROP_ORDER:
        if prop in ("rotation", "shear"):
            continue
        if prop not in allowed or prop not in overrides:
            continue
        decl = _declaration(prop, overrides[prop])
        if decl:
            decls.append(decl)
    tdecl = _transform_decl(overrides, allowed)
    if tdecl:
        decls.append(tdecl)
    if not decls:
        return ""
    return f"#{slot_id} {{ {'; '.join(decls)}; }}\n"
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 tests/test_overlay.py`
Expected: PASS — new shear/combine/gating tests pass AND the pre-existing
`t_ob_compile_rotation` still passes (rotation now flows through `_transform_decl`:
`rotation: 15` → `transform: rotate(15deg)`; `rotation: 999` → dropped). `ALL PASS`.

- [ ] **Step 7: Commit**

```bash
git add src/scripts/overlay_build.py tests/test_overlay.py
git commit -m "feat(overlay): shear (skewX) + combined rotate/skew transform"
```

---

### Task 3: Builder canvas — live mirror + panel controls for `slant`/`shear`

**Files:**
- Modify: `src/ui/control-center.html` (`OV_CSSNAME`, `ovApplyProp`, new `ovSlantClip`
  + `ovApplyTransform`, `ovStyleSlot`, `ovRenderPanel`)

**Interfaces:**
- Consumes: the compiler's `slant`/`shear` semantics (must render identically inline).
- Produces: `ovSlantClip(value) -> string` (CSS polygon or `''`);
  `ovApplyTransform(el)` (sets `el.style.transform` from the slot's rotation+shear).

This task has no Python unit (the builder JS is verified manually + by the Task 5
screenshot, matching the existing builder split). Verification is a manual canvas
check described in Step 6.

- [ ] **Step 1: Drop `rotation` from `OV_CSSNAME`**

In `src/ui/control-center.html`, `OV_CSSNAME` ends (lines 2815–2816):

```javascript
  textTransform: 'text-transform', opacity: 'opacity',
  rotation: 'transform'};
```

Replace with (rotation now handled by the combined transform helper, not the generic
name map):

```javascript
  textTransform: 'text-transform', opacity: 'opacity'};
```

- [ ] **Step 2: Add the `ovSlantClip` + `ovApplyTransform` helpers**

Add these two functions immediately above `function ovApplyProp` (before line ~2970):

```javascript
// Mirror of overlay_build._slant_decl: a clip-path polygon for a signed px slant,
// or '' (no clip). + leans '/', - leans '\'; |v| is the edge offset; 0/out-of-range
// clears. Text content is untouched, so it stays upright (the ERF parallelogram look).
function ovSlantClip(value) {
  const v = parseFloat(value);
  if (!isFinite(v) || v === 0 || v < -400 || v > 400) return '';
  const a = Math.abs(v);
  return v > 0
    ? 'polygon(' + a + 'px 0, 100% 0, calc(100% - ' + a + 'px) 100%, 0 100%)'
    : 'polygon(0 0, calc(100% - ' + a + 'px) 0, 100% 100%, ' + a + 'px 100%)';
}

// Mirror of overlay_build._transform_decl: write ONE combined transform from the
// slot's rotation + shear overrides (rotate before skewX), so neither clobbers the
// other. el.id is the slot id; reads the live override map.
function ovApplyTransform(el) {
  const ov = (ovState.layout.slots && ovState.layout.slots[el.id]) || {};
  const parts = [];
  const r = parseFloat(ov.rotation);
  if (isFinite(r) && r >= -360 && r <= 360) parts.push('rotate(' + r + 'deg)');
  const k = parseFloat(ov.shear);
  if (isFinite(k) && k >= -89 && k <= 89) parts.push('skewX(' + k + 'deg)');
  el.style.transform = parts.join(' ');
}
```

- [ ] **Step 3: Special-case `slant`/`shear`/`rotation` in `ovApplyProp`**

In `ovApplyProp`, after the `visible` block (line ~2986, just before the
`if (value === undefined || value === null || value === '')` generic-unset block),
insert:

```javascript
  if (prop === 'slant') { el.style.clipPath = ovSlantClip(value); return; }
  if (prop === 'rotation' || prop === 'shear') { ovApplyTransform(el); return; }
```

Then REMOVE the now-dead generic rotation branch (lines ~3001–3002):

```javascript
  } else if (prop === 'rotation') {
    el.style.transform = 'rotate(' + value + 'deg)';
```

so the chain goes straight from the `valign` branch to the final `else`. (The
`} else {` that followed the rotation branch stays — just delete the two
rotation lines and their `} else if` opener, merging into the preceding chain.)
Concretely, replace:

```javascript
  } else if (prop === 'valign') {
    el.style.alignItems = OV_VALIGN[value] || '';
  } else if (prop === 'rotation') {
    el.style.transform = 'rotate(' + value + 'deg)';
  } else {
    el.style.setProperty(name, value);
  }
```

with:

```javascript
  } else if (prop === 'valign') {
    el.style.alignItems = OV_VALIGN[value] || '';
  } else {
    el.style.setProperty(name, value);
  }
```

- [ ] **Step 4: Apply `slant` + combined transform on full slot restyle**

In `ovStyleSlot` (lines ~3008–3015), after the `visible` apply, add the slant + the
combined transform (`ovApplyTransform` reads both rotation and shear, covering both).
Replace:

```javascript
function ovStyleSlot(id) {
  const el = ovState.shadow.getElementById(id);
  if (!el) return;
  const ov = (ovState.layout.slots && ovState.layout.slots[id]) || {};
  Object.keys(OV_CSSNAME).forEach(p => ovApplyProp(el, p, ov[p]));
  ovApplyProp(el, 'textShadow', ov.textShadow);
  ovApplyProp(el, 'visible', ov.visible);
}
```

with:

```javascript
function ovStyleSlot(id) {
  const el = ovState.shadow.getElementById(id);
  if (!el) return;
  const ov = (ovState.layout.slots && ovState.layout.slots[id]) || {};
  Object.keys(OV_CSSNAME).forEach(p => ovApplyProp(el, p, ov[p]));
  ovApplyProp(el, 'textShadow', ov.textShadow);
  ovApplyProp(el, 'visible', ov.visible);
  ovApplyProp(el, 'slant', ov.slant);
  ovApplyTransform(el);
}
```

- [ ] **Step 5: Add the Slant + Shear panel controls**

In `ovRenderPanel`, after the `rotation` field block (lines ~3501–3504), insert the
two new fields (same `ovNumField` + `ovState.fields.<prop>` pattern as rotation):

```javascript
  if (has('slant')) {
    panel.appendChild(ovNumField('slant', 'Slant (px, ±)', view));
    Object.assign(ovState.fields.slant, {min: -400, max: 400, step: 1});
  }
  if (has('shear')) {
    panel.appendChild(ovNumField('shear', 'Shear (°, ±)', view));
    Object.assign(ovState.fields.shear, {min: -89, max: 89, step: 1});
  }
```

- [ ] **Step 6: Verify in a live builder**

Run the Control Center from source on a free port and open the overlay builder:

Run:
```bash
RACECAST_UI_PORT=8090 python3 src/racecast.py ui
```
Then in the browser (Profile → overlay builder), select a box slot (e.g. `team1-num`),
set **Slant** to `40` → the box renders as a parallelogram with the number upright;
set it to `-40` → it leans the other way; clear it → the box returns to a rectangle.
Set **Shear** to `12` AND **Rotation** to `15` → the box is both rotated and sheared
(one combined transform, no jump from one clobbering the other). Confirm Undo/Redo and
the selection marquee still track the box. Stop the server (Ctrl-C).

Expected: slant clips the box (text upright), shear skews it, rotation+shear combine,
and Preview/Apply produce CSS matching the compiler.

- [ ] **Step 7: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(builder): slant + shear slot controls with live canvas mirror"
```

---

### Task 4: Builder canvas — preset zoom

**Files:**
- Modify: `src/ui/control-center.html` (CSS `.ovcanvas-wrap`/`.ovcanvas` + new zoom
  styles; toolbar HTML; sizer element; `ovState`; rename `ovFitCanvas`→`ovApplyZoom`;
  new `ovZoomSet`/`ovZoomStep`; move the backdrop onto the stage)

**Interfaces:**
- Consumes: `OV_CANVAS_W`/`OV_CANVAS_H`, `ovState.scale` (drag/resize math).
- Produces: `ovApplyZoom()` (replaces `ovFitCanvas()`); `ovZoomSet(z)` /
  `ovZoomStep(dir)`; `ovState.zoom` (`'fit'` | number).

Builder-only; verified manually (Step 8) + by the Task 5 screenshot.

- [ ] **Step 1: CSS — scrollable wrap, backdrop on the stage, zoom styles**

In `src/ui/control-center.html`, replace the `.ovcanvas-wrap` + `.ovcanvas` rules
(lines 297–302):

```css
  .ovcanvas-wrap { flex:1 1 520px; min-width:300px; background:#0b0f1a;
             border:1px solid var(--line); border-radius:10px; overflow:hidden;
             aspect-ratio:16/9; position:relative;
             background-size:cover; background-position:center; }
  .ovcanvas { position:absolute; top:0; left:0; width:1920px; height:1080px;
             transform-origin:top left; }
```

with (wrap scrolls; the Overlay.png backdrop moves onto the scaled stage; a sizer
defines the scroll area):

```css
  .ovcanvas-wrap { flex:1 1 520px; min-width:300px; background:#0b0f1a;
             border:1px solid var(--line); border-radius:10px; overflow:auto;
             aspect-ratio:16/9; position:relative; }
  .ov-sizer { position:absolute; top:0; left:0; width:100%; height:100%;
             pointer-events:none; }
  .ovcanvas { position:absolute; top:0; left:0; width:1920px; height:1080px;
             transform-origin:top left; background-size:100% 100%;
             background-repeat:no-repeat; }
  .ovgridbar .ov-zoomval { min-width:42px; text-align:center; color:var(--txt); }
  .ovgridbar .ov-zoomsep { width:1px; align-self:stretch; background:var(--line);
             margin:0 2px; }
```

- [ ] **Step 2: Toolbar HTML — zoom group**

In the `.ovgridbar` (after the `Snap to grid` label, line 721), add the zoom controls.
Insert immediately after:

```html
            <label><input type="checkbox" id="ov-grid-snap" onchange="ovGridSnap(this.checked)"> Snap to grid</label>
```

this block:

```html
            <span class="ov-zoomsep"></span>
            <label>Zoom</label>
            <button type="button" class="ov-gpreset" onclick="ovZoomStep(-1)">−</button>
            <span class="ov-zoomval" id="ov-zoomval">Fit</span>
            <button type="button" class="ov-gpreset" onclick="ovZoomStep(1)">+</button>
            <button type="button" class="ov-gpreset" onclick="ovZoomSet('fit')">Fit</button>
            <button type="button" class="ov-gpreset" onclick="ovZoomSet(0.5)">50%</button>
            <button type="button" class="ov-gpreset" onclick="ovZoomSet(1)">100%</button>
            <button type="button" class="ov-gpreset" onclick="ovZoomSet(1.5)">150%</button>
            <button type="button" class="ov-gpreset" onclick="ovZoomSet(2)">200%</button>
```

- [ ] **Step 3: HTML — add the sizer element to the canvas wrap**

The canvas wrap is (line 726):

```html
            <div class="ovcanvas-wrap"><div class="ovcanvas" id="ov-stage"></div></div>
```

Replace with (sizer first so it sits under the absolutely-positioned stage):

```html
            <div class="ovcanvas-wrap"><div class="ov-sizer" id="ov-sizer"></div><div class="ovcanvas" id="ov-stage"></div></div>
```

- [ ] **Step 4: State — zoom + zoom ladder constant**

Add the ladder constant next to `OV_CANVAS_W` (line 2800). Replace:

```javascript
const OV_CANVAS_W = 1920, OV_CANVAS_H = 1080;
```

with:

```javascript
const OV_CANVAS_W = 1920, OV_CANVAS_H = 1080;
const OV_ZOOM_LADDER = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];
```

Add `zoom: 'fit'` to `ovState` (lines 2801–2804). Replace the `grid:` line:

```javascript
                 grid: {show: false, size: 10, snap: false}, gridEl: null};
```

with:

```javascript
                 grid: {show: false, size: 10, snap: false}, gridEl: null,
                 zoom: 'fit'};
```

- [ ] **Step 5: Move the backdrop assignment onto the stage**

The backdrop is currently set on the wrap (line 2866):

```javascript
  $('ov-stage').parentElement.style.backgroundImage = "url('/api/overlay/bg?t=" + Date.now() + "')";
```

Replace with (set it on the scaled stage itself, so it scales + scrolls in lockstep):

```javascript
  $('ov-stage').style.backgroundImage = "url('/api/overlay/bg?t=" + Date.now() + "')";
```

- [ ] **Step 6: Rename `ovFitCanvas` → `ovApplyZoom` and honor the zoom**

Replace `ovFitCanvas` (lines 3114–3127):

```javascript
function ovFitCanvas() {
  const wrap = $('ov-stage').parentElement;
  // The Profile view starts display:none (clientWidth 0); a ResizeObserver
  // refits the instant it becomes visible, so the canvas is never stuck at ~0.
  if (!ovState.ro && 'ResizeObserver' in window) {
    ovState.ro = new ResizeObserver(() => {
      if (wrap.clientWidth) { ovFitCanvas(); ovPositionSel(); }
    });
    ovState.ro.observe(wrap);
  }
  const s = (wrap.clientWidth || 1) / OV_CANVAS_W;
  ovState.scale = s;
  $('ov-stage').style.transform = 'scale(' + s + ')';
}
```

with:

```javascript
function ovApplyZoom() {
  const wrap = $('ov-stage').parentElement;
  // The Profile view starts display:none (clientWidth 0); a ResizeObserver
  // refits the instant it becomes visible — but only while in Fit mode (a numeric
  // zoom is a fixed scale; a wrap resize there just changes what scrolls into view).
  if (!ovState.ro && 'ResizeObserver' in window) {
    ovState.ro = new ResizeObserver(() => {
      if (wrap.clientWidth && ovState.zoom === 'fit') { ovApplyZoom(); ovPositionSel(); }
    });
    ovState.ro.observe(wrap);
  }
  const s = ovState.zoom === 'fit'
    ? (wrap.clientWidth || 1) / OV_CANVAS_W
    : ovState.zoom;
  ovState.scale = s;
  $('ov-stage').style.transform = 'scale(' + s + ')';
  const sizer = $('ov-sizer');
  if (sizer) {
    sizer.style.width = (OV_CANVAS_W * s) + 'px';
    sizer.style.height = (OV_CANVAS_H * s) + 'px';
  }
  const vEl = $('ov-zoomval');
  if (vEl) vEl.textContent = ovState.zoom === 'fit' ? 'Fit' : Math.round(s * 100) + '%';
}

function ovZoomSet(z) {
  ovState.zoom = z;                     // 'fit' or a numeric factor
  ovApplyZoom();
  ovPositionSel();
}

function ovZoomStep(dir) {
  // From Fit, step onto the ladder nearest the current fit scale; otherwise step
  // one rung. dir = +1 (in) / -1 (out).
  const cur = ovState.scale || 1;
  let i = OV_ZOOM_LADDER.findIndex(z => z >= cur - 1e-3);
  if (i < 0) i = OV_ZOOM_LADDER.length - 1;
  if (ovState.zoom !== 'fit') {
    const j = OV_ZOOM_LADDER.indexOf(ovState.zoom);
    if (j >= 0) i = j;
  }
  i = Math.min(Math.max(i + dir, 0), OV_ZOOM_LADDER.length - 1);
  ovZoomSet(OV_ZOOM_LADDER[i]);
}
```

- [ ] **Step 7: Update the four `ovFitCanvas()` call sites**

`ovFitCanvas()` is called at lines ~2948 (`ovBuildCanvas`), ~3604, ~3620, ~3628
(modal open/resize). Rename each call to `ovApplyZoom()`. Run a grep to be sure none
remain:

Run: `grep -n "ovFitCanvas" src/ui/control-center.html`
Expected: no matches (all renamed to `ovApplyZoom`).

- [ ] **Step 8: Verify zoom in a live builder**

Run:
```bash
RACECAST_UI_PORT=8090 python3 src/racecast.py ui
```
Open the overlay builder. Confirm: **Fit** fills the panel as before (no scrollbars,
backdrop aligned). **100%** shows the canvas at 1:1 with scrollbars; the Overlay.png
backdrop scrolls in register with the slots. **50/150/200%** scale correctly; the
readout updates. `−`/`+` walk the ladder. Drag a slot at 200% — it tracks the cursor
1:1 (drag math uses the effective scale). Resize the window in Fit mode — it refits.
Stop the server (Ctrl-C).

- [ ] **Step 9: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(builder): preset canvas zoom with scroll + stage-anchored backdrop"
```

---

### Task 5: Refresh the builder screenshot + full gates

**Files:**
- Modify: `src/docs/wiki/images/cc-overlay-builder.png` (regenerated)

**Interfaces:** none.

- [ ] **Step 1: Run the full Python suite + lint**

Run:
```bash
python3 tools/run-tests.py && python3 tools/lint.py
```
Expected: all tests pass; lint clean. (Fix anything red before continuing.)

- [ ] **Step 2: Regenerate the builder screenshot**

Use the **`wiki-screenshots`** skill to recapture `cc-overlay-builder.png` from a
local dev build (run `racecast ui` straight from `src/`, no `VERSION` file, so the
"dev build" version badge stays uniform). Take the element screenshot of the overlay
builder card so the framing matches the existing image. The shot should show the new
zoom toolbar group; optionally apply a slant to one slot so the parallelogram look is
visible.

- [ ] **Step 3: Verify the image updated**

Run: `git status --short src/docs/wiki/images/cc-overlay-builder.png`
Expected: the file shows as modified.

- [ ] **Step 4: Commit**

```bash
git add src/docs/wiki/images/cc-overlay-builder.png
git commit -m "docs(wiki): refresh overlay builder screenshot (zoom + slant)"
```

---

## Self-Review notes

- **Spec coverage:** Part 1 (zoom) → Task 4. Part 2a `slant` → Task 1; 2b `shear` +
  2c combined transform → Task 2; 2d live mirror + 2e panel controls → Task 3. Part 3
  tests → Tasks 1–2 (compiler) + Task 5 (suite/lint); screenshot → Task 5. All
  covered.
- **Type/name consistency:** `_slant_decl`, `_num_in_range`, `_transform_decl`
  (Python) and `ovSlantClip`, `ovApplyTransform`, `ovApplyZoom`, `ovZoomSet`,
  `ovZoomStep` (JS) are each defined once and referenced under the same name.
  `ovFitCanvas` is fully renamed (Task 4 Step 7 greps to prove no caller is left
  behind — the repo's "grep the whole repo when renaming" rule).
- **Clamps match across compiler + canvas:** slant ±400 & ≠0; shear ±89; rotation
  ±360 — identical in `overlay_build.py` and the `ovSlantClip`/`ovApplyTransform`
  mirror.
