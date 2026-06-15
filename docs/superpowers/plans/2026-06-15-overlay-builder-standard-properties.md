# Overlay-Builder Standard Properties — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every HUD overlay-builder slot the full set of standard CSS properties, driven by a single slot-kind table instead of hand-curated per-element whitelists.

**Architecture:** A `KIND_PROPS` table in the pure compiler (`overlay_build.py`) maps two slot kinds (`text`, `box`) to their property sets; `extract_slots` derives each slot's `props` from `data-edit-kind` in the markup. The compiler gains the new property declarations (padding, border-radius, vertical-align, text-transform, letter-spacing, opacity, line-height, rotation, text-shadow); the Control Center builder renders + applies them. The relay render/data path is untouched.

**Tech Stack:** Python 3 stdlib (compiler + stdlib unit tests, no pytest — each test file is a runnable script), vanilla JS in `src/ui/control-center.html`, Playwright MCP for live UI verification.

**Spec:** `docs/superpowers/specs/2026-06-15-overlay-builder-standard-properties-design.md`

**Conventions (CLAUDE.md):** edit only under `src/`; English only; run `python3 tools/lint.py` after any Python edit; run `python3 tools/run-tests.py` + `python3 tools/build.py` before a PR. Run one test file with `python3 tests/test_overlay.py`.

---

## File structure

- **Modify** `src/scripts/overlay_build.py` — add `KIND_BOX`/`KIND_TEXT`/`KIND_PROPS`, the new value mappings, `PROP_ORDER`, `_declaration`/`_text_shadow_decl`, and kind-aware `extract_slots`.
- **Modify** `src/obs/hud.html` — add `data-edit-kind` to every slot; drop redundant `data-edit-props` (keep team-name auto-fit extras). Base `<style>` unchanged.
- **Modify** `src/ui/control-center.html` — extend `OV_CSSNAME`/`OV_PX`, add `OV_VALIGN`/`OV_TEXTTRANSFORM`, extend `ovApplyProp`/`ovStyleSlot`, render the new fields in `ovRenderPanel` (grouped sections + a text-shadow sub-group).
- **Modify** `tests/test_overlay.py` — kind-derivation tests, per-property compile tests, text-shadow tests, and update the pinned `t_ob_extract_slots_from_real_hud` assertions.
- **Regenerate** `src/docs/wiki/images/cc-overlay-builder.png` — the builder UI changed (CLAUDE.md hard rule).

---

## Task 1: Compiler — slot-kind table + kind-aware `extract_slots`

**Files:**
- Modify: `src/scripts/overlay_build.py`
- Test: `tests/test_overlay.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_overlay.py` (after `t_ob_extract_slots_from_real_hud`):

```python
def t_ob_kind_props_constants():
    # Two kinds; text is a strict superset of box.
    assert set(ob.KIND_PROPS) == {"text", "box"}
    assert set(ob.KIND_BOX).issubset(set(ob.KIND_TEXT))
    # box has no text-only props
    for p in ("fontSize", "color", "align", "valign", "textTransform",
              "lineHeight", "letterSpacing", "textShadow", "fontFamily"):
        assert p not in ob.KIND_BOX
    # both kinds carry the shared box props
    for p in ("left", "top", "width", "height", "padding", "background",
              "borderRadius", "opacity", "rotation"):
        assert p in ob.KIND_BOX

def t_ob_extract_slots_kind_derives_props():
    html = ('<div id="a" data-edit="A" data-edit-kind="text"></div>'
            '<div id="b" data-edit="B" data-edit-kind="box"></div>'
            '<div id="c" data-edit="C" data-edit-kind="text" '
            'data-edit-props="teamNameMax,teamNameMin"></div>'
            '<div id="d" data-edit="D" data-edit-props="left,top"></div>')
    by = {s["id"]: s for s in ob.extract_slots(html)}
    assert by["a"]["props"] == list(ob.KIND_TEXT)
    assert by["b"]["props"] == list(ob.KIND_BOX)
    # extras are appended after the kind set, de-duplicated
    assert by["c"]["props"] == list(ob.KIND_TEXT) + ["teamNameMax", "teamNameMin"]
    # no kind + explicit props -> the explicit list (back-compat fallback)
    assert by["d"]["props"] == ["left", "top"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_overlay as t; t.t_ob_kind_props_constants()"`
Expected: FAIL with `AttributeError: module 'overlay_build' has no attribute 'KIND_PROPS'`.

- [ ] **Step 3: Add the kind constants**

In `src/scripts/overlay_build.py`, immediately after the `PROP_ORDER = (...)` block, add:

```python
# Slot kinds (issue: standard properties for all slots). The single source for
# which properties a slot offers — extract_slots derives slot["props"] from the
# element's data-edit-kind, replacing hand-curated per-element whitelists. text
# is a strict superset of box (box = container/image: position, size, fill,
# border, opacity, rotation; text adds the type properties).
KIND_BOX = ("left", "top", "width", "height", "padding",
            "background", "borderWidth", "borderStyle", "borderColor",
            "borderRadius", "opacity", "rotation")
KIND_TEXT = KIND_BOX + ("fontSize", "lineHeight", "letterSpacing",
                        "fontFamily", "color", "align", "valign",
                        "textTransform", "textShadow")
KIND_PROPS = {"text": KIND_TEXT, "box": KIND_BOX}
```

- [ ] **Step 4: Make `extract_slots` kind-aware**

Replace the body of `extract_slots` (the `if mp: ... else: props = list(DEFAULT_PROPS)` block) so it reads `data-edit-kind` and merges extras:

```python
        label = re.search(r"\bdata-edit=\"([^\"]*)\"", text).group(1)
        mk = re.search(r"\bdata-edit-kind=\"([^\"]*)\"", text)
        mp = re.search(r"\bdata-edit-props=\"([^\"]*)\"", text)
        extras = [p.strip() for p in mp.group(1).split(",") if p.strip()] if mp else []
        if mk and mk.group(1) in KIND_PROPS:
            props = list(KIND_PROPS[mk.group(1)])
            props += [p for p in extras if p not in props]   # extras appended, de-duped
        elif extras:
            props = extras                                   # back-compat: explicit list
        else:
            props = list(DEFAULT_PROPS)
        slots.append({"id": mid.group(1), "label": label, "props": props})
```

- [ ] **Step 5: Run the two tests to verify they pass**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_overlay as t; t.t_ob_kind_props_constants(); t.t_ob_extract_slots_kind_derives_props()"`
Expected: no output, exit 0 (both pass).

- [ ] **Step 6: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/overlay_build.py tests/test_overlay.py
git commit -m "feat(overlay): slot-kind table drives builder props"
```

---

## Task 2: Compiler — scalar properties (padding, border-radius, letter-spacing, opacity, line-height, rotation, valign, text-transform)

**Files:**
- Modify: `src/scripts/overlay_build.py`
- Test: `tests/test_overlay.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_overlay.py`:

```python
SK = [{"id": "x", "label": "X", "props": list(ob.KIND_TEXT)}]

def _css_x(over):
    return ob.compile_overlay_css({"slots": {"x": over}}, SK)

def t_ob_compile_px_extras():
    css = _css_x({"padding": 6, "borderRadius": 4, "letterSpacing": 2})
    assert "padding: 6px" in css
    assert "border-radius: 4px" in css
    assert "letter-spacing: 2px" in css

def t_ob_compile_opacity_and_line_height():
    css = _css_x({"opacity": 0.5, "lineHeight": 1.2})
    assert "opacity: 0.5" in css and "line-height: 1.2" in css
    # out-of-range / non-number dropped
    assert "opacity" not in _css_x({"opacity": 2})
    assert "opacity" not in _css_x({"opacity": "x"})
    assert "line-height" not in _css_x({"lineHeight": 0})

def t_ob_compile_rotation():
    assert "transform: rotate(15deg)" in _css_x({"rotation": 15})
    assert "transform: rotate(-8deg)" in _css_x({"rotation": -8})
    assert "transform" not in _css_x({"rotation": 999})
    assert "transform" not in _css_x({"rotation": "x"})

def t_ob_compile_valign_and_text_transform():
    assert "align-items: center" in _css_x({"valign": "middle"})
    assert "align-items: flex-end" in _css_x({"valign": "bottom"})
    assert "text-transform: uppercase" in _css_x({"textTransform": "uppercase"})
    # unknown enum values dropped (no injection)
    assert "align-items" not in _css_x({"valign": "sideways"})
    assert "text-transform" not in _css_x({"textTransform": "evil; }"})
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_overlay as t; t.t_ob_compile_px_extras()"`
Expected: FAIL (`padding: 6px` not in output — prop unsupported, dropped).

- [ ] **Step 3: Extend the value maps + PROP_ORDER**

In `src/scripts/overlay_build.py`, add the three px props to `_PX_PROPS` (inside the existing dict):

```python
    "padding": "padding", "borderRadius": "border-radius",
    "letterSpacing": "letter-spacing",
```

Add two enum maps right after `_ALIGN = {...}`:

```python
_VALIGN = {"top": "flex-start", "middle": "center", "bottom": "flex-end"}
_TEXT_TRANSFORM = {"none": "none", "uppercase": "uppercase",
                   "lowercase": "lowercase", "capitalize": "capitalize"}
```

Replace `PROP_ORDER` with the extended, deterministic order:

```python
PROP_ORDER = ("left", "top", "width", "height", "padding",
              "fontSize", "lineHeight", "letterSpacing",
              "borderWidth", "borderRadius",
              "teamNameMax", "teamNameMin", "fontFamily", "color",
              "background", "borderColor", "borderStyle",
              "align", "valign", "textTransform", "opacity",
              "rotation", "textShadow")
```

- [ ] **Step 4: Extend `_declaration`**

In `_declaration`, before the final `return None`, add the new branches:

```python
    if prop == "valign":
        mapped = _VALIGN.get(value) if isinstance(value, str) else None
        return f"align-items: {mapped}" if mapped else None
    if prop == "textTransform":
        mapped = _TEXT_TRANSFORM.get(value) if isinstance(value, str) else None
        return f"text-transform: {mapped}" if mapped else None
    if prop == "opacity":
        if not isinstance(value, (int, float)) or not 0 <= value <= 1:
            return None
        num = int(value) if float(value).is_integer() else value
        return f"opacity: {num}"
    if prop == "lineHeight":
        if not isinstance(value, (int, float)) or not 0 < value <= 5:
            return None
        num = int(value) if float(value).is_integer() else value
        return f"line-height: {num}"
    if prop == "rotation":
        if not isinstance(value, (int, float)) or not -360 <= value <= 360:
            return None
        num = int(value) if float(value).is_integer() else value
        return f"transform: rotate({num}deg)"
```

(`_safe_value` already rejects bool — an int subclass — so `opacity: True` cannot slip through.)

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `python3 tests/test_overlay.py`
Expected: ends with `ALL PASS` (all `t_` functions, old + new).

- [ ] **Step 6: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/overlay_build.py tests/test_overlay.py
git commit -m "feat(overlay): padding/radius/spacing/opacity/line-height/rotation/valign/transform props"
```

---

## Task 3: Compiler — text-shadow (compound, safe)

**Files:**
- Modify: `src/scripts/overlay_build.py`
- Test: `tests/test_overlay.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_overlay.py`:

```python
def t_ob_compile_text_shadow():
    css = _css_x({"textShadow": {"x": 0, "y": 2, "blur": 4, "color": "#000000"}})
    assert "text-shadow: 0px 2px 4px #000000" in css
    # all-zero offsets/blur -> invisible -> omitted
    assert "text-shadow" not in _css_x(
        {"textShadow": {"x": 0, "y": 0, "blur": 0, "color": "#000000"}})
    # missing/!str color dropped; non-dict dropped
    assert "text-shadow" not in _css_x({"textShadow": {"x": 1, "y": 1, "blur": 1}})
    assert "text-shadow" not in _css_x({"textShadow": "0 2px 4px red"})
    # color cannot inject (the _UNSAFE_VALUE gate via _safe_value)
    assert "text-shadow" not in _css_x(
        {"textShadow": {"x": 1, "y": 1, "blur": 1, "color": "red; } body{x:1"}})
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_overlay as t; t.t_ob_compile_text_shadow()"`
Expected: FAIL (`text-shadow: ...` not in output).

- [ ] **Step 3: Add `_text_shadow_decl` and wire it into `_declaration`**

In `src/scripts/overlay_build.py`, add this helper just above `_declaration`:

```python
def _text_shadow_decl(value):
    """One 'text-shadow: Xpx Ypx Bpx COLOR' from a {x,y,blur,color} dict, or None.
    Each part is validated individually (offsets/blur numbers, color via the
    _safe_value gate) so no value can inject CSS. Omitted when fully invisible."""
    if not isinstance(value, dict):
        return None
    nums = []
    for k in ("x", "y", "blur"):
        n = value.get(k, 0)
        if isinstance(n, bool) or not isinstance(n, (int, float)):
            return None
        nums.append(int(n) if float(n).is_integer() else n)
    color = _safe_value(value.get("color"))
    if not isinstance(color, str) or nums == [0, 0, 0]:
        return None
    return f"text-shadow: {nums[0]}px {nums[1]}px {nums[2]}px {color}"
```

Make `_declaration` handle the dict-valued prop FIRST (before `_safe_value`, which rejects dicts). Change the top of `_declaration` from:

```python
def _declaration(prop, value):
    """CSS 'name: value' for one (prop, value), or None when unsupported/unsafe."""
    value = _safe_value(value)
```

to:

```python
def _declaration(prop, value):
    """CSS 'name: value' for one (prop, value), or None when unsupported/unsafe."""
    if prop == "textShadow":
        return _text_shadow_decl(value)
    value = _safe_value(value)
```

(`textShadow` is already in `PROP_ORDER` and `KIND_TEXT` from earlier tasks, so `_slot_rule` will reach it.)

- [ ] **Step 4: Run the full overlay suite**

Run: `python3 tests/test_overlay.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/overlay_build.py tests/test_overlay.py
git commit -m "feat(overlay): compound text-shadow property (safe assembly)"
```

---

## Task 4: Markup — `data-edit-kind` on every HUD slot + update pinned slot test

**Files:**
- Modify: `src/obs/hud.html` (the slot `<div>`s, lines ~97-115)
- Test: `tests/test_overlay.py` (`t_ob_extract_slots_from_real_hud`)

- [ ] **Step 1: Update the pinned assertions first (failing test)**

In `tests/test_overlay.py`, inside `t_ob_extract_slots_from_real_hud`, replace the four per-slot prop assertions (`team1-name`, `team1-num`, `team1-logo`, `round-flag`) and the `pov` props assertion with kind-derived expectations:

```python
    # team name slot: the text kind + the auto-fit extras (issue #136)
    assert by_id["team1-name"]["props"] == list(ob.KIND_TEXT) + [
        "teamNameMax", "teamNameMin"]
    # team number slot: the full text kind (issue: standard props for all slots)
    assert by_id["team1-num"]["props"] == list(ob.KIND_TEXT)
    # image slots (logo, flag) are the box kind: no text properties
    assert by_id["team1-logo"]["props"] == list(ob.KIND_BOX)
    assert by_id["round-flag"]["props"] == list(ob.KIND_BOX)
    # POV box: the box kind (still carries background/border via the kind)
    assert by_id["pov"]["props"] == list(ob.KIND_BOX)
    for p in ("background", "borderStyle", "borderColor", "borderWidth"):
        assert p in by_id["pov"]["props"], p
    assert by_id["pov"]["label"] == "POV box"
```

Also relax the line that asserts the `stint` default set still excludes the team key (it does via the kind):

```python
    assert "fontSize" in by_id["stint"]["props"]
    assert "teamNameMax" not in by_id["stint"]["props"]
```

(leave those two lines as-is — they still hold for the `text` kind).

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_overlay as t; t.t_ob_extract_slots_from_real_hud()"`
Expected: FAIL — the real `hud.html` slots have no `data-edit-kind` yet, so `team1-num` still resolves the old explicit list.

- [ ] **Step 2: Add `data-edit-kind` to each slot in `src/obs/hud.html`**

Edit the slot block (lines ~97-115). Set each slot's kind and drop the now-redundant `data-edit-props` (keep it ONLY on the two team-name lines, for the auto-fit extras). Result:

```html
  <div id="stint" class="el white" data-edit="Stint banner" data-edit-kind="text"></div>
  <div id="session" class="el black" data-edit="Session" data-edit-kind="text"></div>
  <div id="streamer" class="el black" data-edit="Streamer" data-edit-kind="text"></div>
  <div id="round-top" class="el white" data-edit="Round title" data-edit-kind="text"></div>
  <div id="round-flag" class="el" data-edit="Round flag" data-edit-kind="box"><img alt=""></div>
  <div id="round-country" class="el white" data-edit="Round country" data-edit-kind="text"></div>
  <div id="team1-logo" class="el team-logo" data-edit="Team 1 logo" data-edit-kind="box"><img alt=""></div>
  <div id="team1-num" class="el team-num white" data-edit="Team 1 number" data-edit-kind="text"></div>
  <div id="team1-name" class="el team-name white" data-edit="Team 1 name" data-edit-kind="text" data-edit-props="teamNameMax,teamNameMin"></div>
  <div id="team2-logo" class="el team-logo" data-edit="Team 2 logo" data-edit-kind="box"><img alt=""></div>
  <div id="team2-num" class="el team-num white" data-edit="Team 2 number" data-edit-kind="text"></div>
  <div id="team2-name" class="el team-name white" data-edit="Team 2 name" data-edit-kind="text" data-edit-props="teamNameMax,teamNameMin"></div>
  <div id="team3-logo" class="el team-logo" data-edit="Team 3 logo" data-edit-kind="box"><img alt=""></div>
  <div id="team3-num" class="el team-num white" data-edit="Team 3 number" data-edit-kind="text"></div>
  <div id="team3-name" class="el team-name white" data-edit="Team 3 name" data-edit-kind="text" data-edit-props="teamNameMax,teamNameMin"></div>
  <div id="race-control" class="el white" data-edit="Race control" data-edit-kind="text"></div>
  <div id="pov" class="el" data-edit="POV box" data-edit-kind="box"></div>
  <div id="pov-name" class="el" data-edit="POV name" data-edit-kind="text"></div>
  <div id="clock" class="el white" data-edit="Clock" data-edit-kind="text"></div>
```

Update the explanatory comment above the block (the `data-edit-props` description) to mention `data-edit-kind`:

```html
  <!-- data-edit="<label>" marks a builder slot; data-edit-kind="text|box" sets
       its property set (KIND_PROPS in overlay_build.py — the single source).
       data-edit-props adds slot-specific extras (e.g. team-name auto-fit). -->
```

- [ ] **Step 3: Run the real-HUD slot test + full overlay suite**

Run: `python3 tests/test_overlay.py`
Expected: `ALL PASS`.

- [ ] **Step 4: Run the whole suite (other files read hud.html / slots)**

Run: `python3 tools/run-tests.py`
Expected: all test files report pass (watch `test_ui_server.py`, `test_racecast.py`, `test_hud.py`).

- [ ] **Step 5: Commit**

```bash
git add src/obs/hud.html tests/test_overlay.py
git commit -m "feat(overlay): tag HUD slots with data-edit-kind (text/box)"
```

---

## Task 5: UI — extend the prop maps + `ovApplyProp`/`ovStyleSlot`

**Files:**
- Modify: `src/ui/control-center.html` (constants ~2344-2351; `ovApplyProp` ~2486; `ovStyleSlot` ~2507)

This file has no JS unit tests (the repo tests the server, not the client) — verify in Task 7 via the running builder.

- [ ] **Step 1: Extend `OV_CSSNAME`**

Replace the `OV_CSSNAME` object (lines ~2344-2348) with the extended map:

```javascript
const OV_CSSNAME = {left: 'left', top: 'top', width: 'width', height: 'height',
  padding: 'padding', fontSize: 'font-size', lineHeight: 'line-height',
  letterSpacing: 'letter-spacing', borderWidth: 'border-width',
  borderRadius: 'border-radius', teamNameMax: '--team-name-max',
  teamNameMin: '--team-name-min', color: 'color', background: 'background',
  borderColor: 'border-color', borderStyle: 'border-style',
  fontFamily: 'font-family', align: 'justify-content', valign: 'align-items',
  textTransform: 'text-transform', opacity: 'opacity',
  rotation: 'transform'};
```

- [ ] **Step 2: Extend `OV_PX` and add the enum maps**

Replace the `OV_PX` set + `OV_ALIGN` line (lines ~2349-2351) with:

```javascript
const OV_PX = new Set(['left', 'top', 'width', 'height', 'padding', 'fontSize',
                       'letterSpacing', 'borderWidth', 'borderRadius',
                       'teamNameMax', 'teamNameMin']);
const OV_ALIGN = {left: 'flex-start', center: 'center', right: 'flex-end'};
const OV_VALIGN = {top: 'flex-start', middle: 'center', bottom: 'flex-end'};
```

- [ ] **Step 3: Handle the special props in `ovApplyProp`**

In `ovApplyProp` (the `else if` chain ~2498-2504), add `valign`, `rotation`, and `textShadow` cases. Replace:

```javascript
  } else if (prop === 'align') {
    el.style.justifyContent = OV_ALIGN[value] || '';
  } else {
    el.style.setProperty(name, value);
  }
```

with:

```javascript
  } else if (prop === 'align') {
    el.style.justifyContent = OV_ALIGN[value] || '';
  } else if (prop === 'valign') {
    el.style.alignItems = OV_VALIGN[value] || '';
  } else if (prop === 'rotation') {
    el.style.transform = (value === '' ? '' : 'rotate(' + value + 'deg)');
  } else if (prop === 'textShadow') {
    const s = value;
    el.style.textShadow = (s && s.color)
      ? ((s.x || 0) + 'px ' + (s.y || 0) + 'px ' + (s.blur || 0) + 'px ' + s.color)
      : '';
  } else {
    el.style.setProperty(name, value);
  }
```

Also handle the empty/unset case for `textShadow` (which is an object, so the existing `value === ''` early-return at the top of `ovApplyProp` won't catch a cleared object) — add, right after the existing early-return block (~2494):

```javascript
  if (prop === 'textShadow' && (!value || !value.color)) {
    el.style.textShadow = ''; return;
  }
```

- [ ] **Step 4: Apply `textShadow` in `ovStyleSlot`**

`ovStyleSlot` iterates `OV_CSSNAME` keys; `textShadow` is not in that map, so add one explicit line. Change `ovStyleSlot` (~2507-2512) to:

```javascript
function ovStyleSlot(id) {
  const el = ovState.shadow.getElementById(id);
  if (!el) return;
  const ov = (ovState.layout.slots && ovState.layout.slots[id]) || {};
  Object.keys(OV_CSSNAME).forEach(p => ovApplyProp(el, p, ov[p]));
  ovApplyProp(el, 'textShadow', ov.textShadow);
}
```

- [ ] **Step 5: Syntax-check the page loads**

Start the Control Center (`python3 src/racecast.py ui`), open `http://127.0.0.1:8089`, open the browser console, confirm **no JS errors** on load. Stop it after the check. (Full UI verification is Task 7.)

- [ ] **Step 6: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(overlay-ui): apply new slot properties live in the canvas"
```

---

## Task 6: UI — render the new fields in the property panel

**Files:**
- Modify: `src/ui/control-center.html` (`ovRenderPanel`, the field-rendering body ~2737-2795; add a text-shadow helper + an `ovSetShadow` near the other field helpers ~2689)

- [ ] **Step 1: Add a shadow setter + a text-shadow field helper**

After `ovSelectField` (~2689), add:

```javascript
function ovSetShadow(id, key, raw) {
  if (!ovState.layout.slots) ovState.layout.slots = {};
  const slot = ovState.layout.slots[id] || (ovState.layout.slots[id] = {});
  const s = Object.assign({x: 0, y: 0, blur: 0, color: ''}, slot.textShadow || {});
  s[key] = (key === 'color') ? raw : (raw === '' ? 0 : Number(raw));
  if (!s.color && !s.x && !s.y && !s.blur) delete slot.textShadow;
  else slot.textShadow = s;
  ovApplyProp(ovState.shadow.getElementById(id), 'textShadow', slot.textShadow);
  ovPositionSel();
}

function ovShadowField(ov) {
  const s = ov.textShadow || {};
  const wrap = document.createElement('div');
  const l = document.createElement('label'); l.textContent = 'Text shadow';
  wrap.appendChild(l);
  const row = document.createElement('div'); row.className = 'ovgrid2';
  const numIn = (key, ph, val) => {
    const i = document.createElement('input'); i.type = 'number';
    i.placeholder = ph; i.value = (val !== undefined ? val : '');
    i.oninput = () => ovSetShadow(ovState.sel, key, i.value);
    return i;
  };
  row.append(numIn('x', 'Offset X', s.x), numIn('y', 'Offset Y', s.y),
             numIn('blur', 'Blur', s.blur));
  const c = document.createElement('input'); c.type = 'color';
  if (/^#[0-9a-fA-F]{6}$/.test(s.color || '')) c.value = s.color;
  c.oninput = () => ovSetShadow(ovState.sel, 'color', c.value);
  row.appendChild(c);
  wrap.appendChild(row);
  return wrap;
}
```

- [ ] **Step 2: Render the new scalar fields (grouped) in `ovRenderPanel`**

In the field-rendering body, the existing blocks render Position (left/top), Size (width/height), fontSize, autofit, fontFamily, then color/background/border/align. Insert the new fields so each appears next to its group. Add **padding** to the Size group — change the size block (~2748-2754) to:

```javascript
  if (has('width') || has('height') || has('padding')) {
    const g = grid();
    if (has('width')) g.appendChild(ovNumField('width', 'Width (px)', view));
    if (has('height')) g.appendChild(ovNumField('height', 'Height (px)', view));
    if (has('padding')) g.appendChild(ovNumField('padding', 'Padding (px)', view));
    panel.appendChild(g);
  }
```

After the `fontSize` line (~2755), add line-height + letter-spacing:

```javascript
  if (has('lineHeight') || has('letterSpacing')) {
    const g = grid();
    if (has('lineHeight')) g.appendChild(ovNumField('lineHeight', 'Line height', view));
    if (has('letterSpacing')) g.appendChild(ovNumField('letterSpacing', 'Letter spacing (px)', view));
    panel.appendChild(g);
  }
```

After the `borderWidth` line (~2778), add border-radius:

```javascript
  if (has('borderRadius')) panel.appendChild(ovNumField('borderRadius', 'Corner radius (px)', view));
```

After the existing `align` select block (~2784-2789), add vertical-align, text-transform, opacity, rotation, and the text-shadow group:

```javascript
  if (has('valign')) {
    panel.appendChild(ovSelectField('valign', 'Vertical align',
      [{v: '', t: '— default —'}, {v: 'top', t: 'Top'},
       {v: 'middle', t: 'Middle'}, {v: 'bottom', t: 'Bottom'}], ov));
  }
  if (has('textTransform')) {
    panel.appendChild(ovSelectField('textTransform', 'Text transform',
      [{v: '', t: '— none —'}, {v: 'uppercase', t: 'UPPERCASE'},
       {v: 'lowercase', t: 'lowercase'}, {v: 'capitalize', t: 'Capitalize'}], ov));
  }
  if (has('opacity')) panel.appendChild(ovNumField('opacity', 'Opacity (0–1)', view));
  if (has('rotation')) panel.appendChild(ovNumField('rotation', 'Rotation (°)', view));
  if (has('textShadow')) panel.appendChild(ovShadowField(ov));
```

Note: `ovNumField` reads `view[prop]` (base+override). Since `ovBaseValues` does NOT return the new optional props, `view[prop]` is the override value only — i.e. these fields start blank until set, and stay override-only on save (spec's lean-output rule, achieved without touching `ovBaseValues`).

- [ ] **Step 3: Verify the panel renders all fields**

Restart the Control Center, open the overlay builder (Profile view), select the **Team 1 number** slot, and confirm the panel now shows Width/Height/Padding, Line height/Letter spacing, Corner radius, Vertical align, Text transform, Opacity, Rotation, and the Text-shadow row — with no console errors. Select **Team 1 logo** and confirm NO text fields appear (box kind).

- [ ] **Step 4: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(overlay-ui): property panel fields for the new standard props"
```

---

## Task 7: Live verification + regenerate the wiki screenshot

**Files:**
- Modify: `src/docs/wiki/images/cc-overlay-builder.png`

- [ ] **Step 1: Drive the builder end-to-end (Playwright MCP)**

With the Control Center running (`python3 src/racecast.py ui`, active profile `example`), open the overlay builder, select **Team 1 number**, set Width=54, Height=48, Vertical align=Middle, Corner radius=4, and a Text shadow (Y=2, Blur=4, color #000000). Confirm in the canvas that the badge changes live (width/height/rounding/shadow visible). Click **Save**.

- [ ] **Step 2: Confirm the generated CSS**

Run: `python3 -c "import json,sys; sys.path.insert(0,'src/scripts'); import overlay_build as ob; print(open('profiles/example/overlay/hud.css').read())" | grep -E "team1-num|text-shadow|align-items|border-radius"`
Expected: `#team1-num { ...; width: 54px; height: 48px; border-radius: 4px; align-items: center; text-shadow: 0px 2px 4px #000000; }` (order per `PROP_ORDER`).

- [ ] **Step 3: Reset the example profile (keep the repo template clean)**

The `example` profile must stay a clean template (no pinned layout). Revert the test edit:

```bash
git checkout -- profiles/example/overlay/hud.css
git status --porcelain profiles/example/   # expect: no changes
```

(If a `profiles/example/overlay/layout-hud.json` was created, `rm` it — it is not part of the template.)

- [ ] **Step 4: Recapture `cc-overlay-builder.png`**

Per CLAUDE.md: drive the running builder with the Playwright MCP and take an **element** screenshot of the overlay-builder card/modal (match the framing of the existing image — the card element, not a full-window grab). Save over `src/docs/wiki/images/cc-overlay-builder.png`. Use a slot selected so the expanded property panel (the new fields) is visible.

- [ ] **Step 5: Commit**

```bash
git add src/docs/wiki/images/cc-overlay-builder.png
git commit -m "docs(wiki): refresh overlay-builder screenshot for new properties"
```

---

## Task 8: Full gates, issue, PR (ship-feature)

**Files:** none (verification + release flow)

- [ ] **Step 1: Run the full local gates**

```bash
python3 tools/run-tests.py
python3 tools/lint.py
python3 tools/build.py
```
Expected: suite all-pass; lint clean; build exits 0 (verify step). Fix anything red before continuing.

- [ ] **Step 2: Open the GitHub issue**

```bash
gh issue create --title "Overlay builder: standard properties for all slots" \
  --label enhancement \
  --body "Make every HUD overlay-builder slot offer the full set of standard CSS properties via slot kinds (text/box) instead of hand-curated per-element whitelists. Adds padding, border-radius, vertical align, text-transform, letter-spacing, opacity, line-height, rotation and text-shadow. Spec: docs/superpowers/specs/2026-06-15-overlay-builder-standard-properties-design.md. Supersedes the per-league customCss width workaround (#172)."
```
Record the issue number `N`.

- [ ] **Step 3: Push + open the PR (after user OK)**

```bash
git push -u origin feat/overlay-builder-standard-props
gh pr create --base main \
  --title "feat(overlay): standard properties for all builder slots" \
  --body "Closes #N

Slot-kind table (text/box) in overlay_build.py drives builder props; adds padding, border-radius, vertical align, text-transform, letter-spacing, opacity, line-height, rotation, text-shadow. HUD page only. Spec + plan under docs/superpowers/. Wiki builder screenshot refreshed.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 4: Green CI, then merge (after user OK)**

Poll `gh pr checks <PR>` until the full matrix (macOS + Windows + Linux × Py 3.11–3.13, lint, CodeQL, gitleaks, binary-smoke) is green. Do not merge on red. Then: `gh pr merge <PR> --squash --delete-branch`.

- [ ] **Step 5: Wrap up + IRO GTEC migration (separate, profile-specific)**

```bash
git checkout main && git pull
```
Then, in the IRO GTEC profile (the user's install): set the number-badge width/height/valign in the builder, delete the `.team-num` `customCss` workaround, save, `racecast obs refresh`, and re-export the profile. (Not part of this repo PR.)

---

## Self-review notes

- **Spec coverage:** kinds + KIND_PROPS (Task 1); padding/border-radius/letter-spacing/opacity/line-height/rotation/valign/text-transform (Task 2); text-shadow compound (Task 3); markup data-edit-kind + back-compat (Task 4); UI maps/apply (Task 5); UI panel fields + lean override-only save (Task 6); live verify + wiki image (Task 7); gates + issue/PR + #172 migration (Task 8). Scope (HUD only, splitscreen excluded) honored — no splitscreen edits.
- **Override-only save:** achieved by NOT adding the new props to `ovBaseValues`; `merged[p] = ov[p] ?? base[p]` then yields the override value only. No code change needed there — documented in Task 6 Step 2.
- **Names consistent across tasks:** `KIND_BOX`/`KIND_TEXT`/`KIND_PROPS`, `_VALIGN`/`_TEXT_TRANSFORM`, `_text_shadow_decl`, `OV_VALIGN`, `ovSetShadow`/`ovShadowField` used identically where referenced.
- **Rotation caveat** (approximate resize handles while rotated) is a known, accepted limitation — no task attempts to fix the axis-aligned selection math.
