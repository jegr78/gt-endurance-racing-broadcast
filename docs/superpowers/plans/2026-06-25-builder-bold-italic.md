# Visual Builder Bold / Italic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-slot **Bold** (`font-weight`) and **Italic** (`font-style`) controls to the visual overlay builder, as CSS-only enum properties.

**Architecture:** Two new enum text-properties (`fontWeight`, `fontStyle`) added to the pure overlay compiler exactly like `textTransform` (a CSS-name map + a validated `_declaration` branch + `KIND_TEXT`/`PROP_ORDER` membership), surfaced in the builder panel via two `ovSelectField` dropdowns and an `OV_CSSNAME` entry. No font-pipeline change — bold/italic render via CSS (synthetic where the self-hosted single-weight font lacks the face).

**Tech Stack:** Pure Python 3 stdlib (compiler), vanilla JS + Shadow DOM (builder), stdlib runnable test scripts (no pytest).

## Global Constraints

- **Edit only under `src/`** (plus `tests/` and `docs/`). Never hand-edit `dist/`/`runtime/`.
- **English only** in all code, comments, and docs.
- **No new dependencies**; CSS-only — no font downloads / multi-weight `@font-face`.
- **Scope is exactly two values each:** `fontWeight` ∈ {`normal`,`bold`}, `fontStyle` ∈ {`normal`,`italic`}. No numeric weights, no `oblique`. Unknown values must be dropped by the compiler (the injection gate), like every other enum.
- `fontWeight`/`fontStyle` are **text-only** — added to `KIND_TEXT`, NOT `KIND_BOX`.
- No demo/example overlay file changes (the `t_shipped_demo_overlay_css_matches_its_layout` sync guard must stay green).
- Tests are runnable scripts: `python3 tests/test_overlay.py` (prints `ALL PASS`). Full suite: `python3 tools/run-tests.py`; lint: `python3 tools/lint.py` (run after any Python change).
- A visible Control-Center change requires refreshing `src/docs/wiki/images/cc-overlay-builder.png` (+ the slides copy) in the same change.
- After shipping, `python3 tools/build.py` must still pass its verify step.

---

### Task 1: Compiler — `fontWeight` + `fontStyle` enum properties

**Files:**
- Modify: `src/scripts/overlay_build.py` (maps ~34; `PROP_ORDER` ~42-48; `KIND_TEXT` ~59-61; `_declaration` ~254-256)
- Test: `tests/test_overlay.py`

**Interfaces:**
- Produces: text slots accept `fontWeight` (→ `font-weight: normal|bold`) and `fontStyle` (→ `font-style: normal|italic`); unknown values drop. Both are in `KIND_TEXT` (and inherited nowhere else — not in `KIND_BOX`). Consumed by Task 2 (builder panel).

- [ ] **Step 1: Write the failing tests**

In `tests/test_overlay.py`, add after `t_ob_compile_valign_and_text_transform` (the `_css_x` / `SK` helpers already exist in that file):

```python
def t_ob_compile_font_weight_and_style():
    assert "font-weight: bold" in _css_x({"fontWeight": "bold"})
    assert "font-weight: normal" in _css_x({"fontWeight": "normal"})
    assert "font-style: italic" in _css_x({"fontStyle": "italic"})
    assert "font-style: normal" in _css_x({"fontStyle": "normal"})
    # out-of-scope / unknown values dropped (no injection, no numeric scale)
    assert "font-weight" not in _css_x({"fontWeight": "900"})
    assert "font-weight" not in _css_x({"fontWeight": "evil; }"})
    assert "font-style" not in _css_x({"fontStyle": "oblique"})


def t_ob_font_weight_style_are_text_only():
    assert "fontWeight" in ob.KIND_TEXT and "fontStyle" in ob.KIND_TEXT
    assert "fontWeight" not in ob.KIND_BOX and "fontStyle" not in ob.KIND_BOX
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_overlay.py`
Expected: FAIL — `t_ob_compile_font_weight_and_style` (`font-weight: bold` not found) and `t_ob_font_weight_style_are_text_only`.

- [ ] **Step 3: Implement the compiler changes**

In `src/scripts/overlay_build.py`, add the two maps right after `_TEXT_TRANSFORM` (~35):

```python
_FONT_WEIGHT = {"normal": "normal", "bold": "bold"}
_FONT_STYLE = {"normal": "normal", "italic": "italic"}
```

Add `"fontWeight", "fontStyle"` to `KIND_TEXT` (~59-61), after `fontFamily`:

```python
KIND_TEXT = KIND_BOX + ("fontSize", "lineHeight", "letterSpacing",
                        "fontFamily", "fontWeight", "fontStyle", "color",
                        "align", "valign", "textTransform", "textShadow")
```

Add them to `PROP_ORDER` (~42-48), right after `"fontFamily"`:

```python
PROP_ORDER = ("left", "top", "width", "height", "padding",
              "fontSize", "lineHeight", "letterSpacing",
              "borderWidth", "borderRadius",
              "teamNameMax", "teamNameMin", "fontFamily", "fontWeight",
              "fontStyle", "color", "background", "borderColor", "borderStyle",
              "align", "valign", "textTransform", "opacity",
              "rotation", "textShadow", "visible")
```

In `_declaration`, add two branches right after the `textTransform` branch (~256):

```python
    if prop == "fontWeight":
        mapped = _FONT_WEIGHT.get(value) if isinstance(value, str) else None
        return f"font-weight: {mapped}" if mapped else None
    if prop == "fontStyle":
        mapped = _FONT_STYLE.get(value) if isinstance(value, str) else None
        return f"font-style: {mapped}" if mapped else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_overlay.py`
Expected: `ALL PASS` (incl. `t_shipped_demo_overlay_css_matches_its_layout` — the demo layout sets neither prop, so its compiled CSS is unchanged).

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/overlay_build.py tests/test_overlay.py
git commit -m "feat(overlay): fontWeight/fontStyle (bold/italic) compiler properties"
```

---

### Task 2: Builder front-end — Bold / Italic dropdowns

**Files:**
- Modify: `src/ui/control-center.html` (`OV_CSSNAME` ~2775-2783; `ovRenderPanel` font-family block ~3255-3270)
- Test: manual (browser builder); no JS unit harness — covered by the full suite (data-layer routes) + the Task 3 screenshot.

**Interfaces:**
- Consumes: the `fontWeight`/`fontStyle` props from Task 1 (slots advertise them via `meta.props`).
- Produces: two select controls in the property panel; values round-trip through `ovSetProp` and apply live on the canvas through the existing generic `ovApplyProp` path.

- [ ] **Step 1: Add the CSS-name mappings**

In `src/ui/control-center.html`, extend `OV_CSSNAME` (~2782, alongside `fontFamily`):

```javascript
  fontFamily: 'font-family', fontWeight: 'font-weight', fontStyle: 'font-style',
  align: 'justify-content', valign: 'align-items',
```

(Add `fontWeight`/`fontStyle` to the existing literal; keep the other entries intact.)

- [ ] **Step 2: Add the two panel selects**

In `ovRenderPanel`, immediately after the `if (has('fontFamily')) { … }` block closes (~3270, before `if (has('color'))`), add:

```javascript
  if (has('fontWeight')) {
    panel.appendChild(ovSelectField('fontWeight', 'Font weight',
      [{v: '', t: '— default —'}, {v: 'normal', t: 'Normal'},
       {v: 'bold', t: 'Bold'}], ov));
  }
  if (has('fontStyle')) {
    panel.appendChild(ovSelectField('fontStyle', 'Font style',
      [{v: '', t: '— default —'}, {v: 'normal', t: 'Normal'},
       {v: 'italic', t: 'Italic'}], ov));
  }
```

No `ovApplyProp` change is needed: both props are in `OV_CSSNAME`, are non-px and non-special-cased, so the generic `el.style.setProperty('font-weight'|'font-style', value)` path applies them; `ovStyleSlot` already iterates `OV_CSSNAME`, so load/reset restore them.

- [ ] **Step 3: Verify the suite stays green + lint**

The JS is not exercised by an automated test; confirm nothing else broke:

```bash
python3 tools/run-tests.py
python3 tools/lint.py
```
Expected: suite `ALL TEST FILES PASS` (in particular `tests/test_ui_server.py`), lint clean.

- [ ] **Step 4: Manual builder smoke (optional but recommended)**

```bash
RACECAST_PROFILE=demo RACECAST_UI_PORT=8090 python3 src/racecast.py ui --no-browser
```
Open the Profile → overlay builder ("Pop out ↗"), select a text slot (e.g. "Stint banner"), confirm a **Font weight** and **Font style** dropdown appear; setting Bold/Italic restyles the slot live on the canvas; `— default —` reverts. Stop the UI afterward (`pkill -f "racecast.py ui"`). (The controller will also verify this in browser during review.)

- [ ] **Step 5: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(builder): Bold/Italic font-weight & font-style dropdowns"
```

---

### Task 3: Docs — refresh the overlay-builder screenshot

**Files:**
- Modify (regenerate): `src/docs/wiki/images/cc-overlay-builder.png` and `src/docs/slides/assets/img/cc-overlay-builder.png` (identical bytes — the slide deck `src/docs/slides/overlay-designer.html` reuses it)
- Test: `python3 tests/test_wiki.py`

- [ ] **Step 1: Regenerate the screenshot**

Use the **`wiki-screenshots`** skill recipe (Control Center view, UI server only — no relay needed). Start the dev build on the **demo** profile and a free port:

```bash
python3 src/racecast.py profile use demo
RACECAST_UI_PORT=8090 python3 src/racecast.py ui --no-browser
```

Drive it with the Playwright MCP: navigate `http://127.0.0.1:8090/` → Profile nav (`button[data-nav="profile"]`) → open the builder (`openBuilderModal()` / the "Pop out ↗" button) → select the same slot the existing shot uses (slot picker shows "Team 1 number", i.e. `ovSelect('team1-num')`) so the framing matches — the panel will now also show **Font weight** + **Font style**. Resize the viewport to ~1440×820 so the `#ov-modal .ovmodal-card` element is ~1388px wide (matching the existing image), then **element-screenshot** `#ov-modal .ovmodal-card`.

- [ ] **Step 2: Install the image to both paths and clean up**

```bash
cp <captured>.png src/docs/wiki/images/cc-overlay-builder.png
cp <captured>.png src/docs/slides/assets/img/cc-overlay-builder.png
pkill -f "racecast.py ui"
git checkout -- profiles/demo/profile.env   # only if the relay was started (UI alone does not write it)
```

(`racecast ui` alone does not provision `CONSOLE_SECRET`; only a relay start does. Still verify `git status --porcelain profiles/demo/profile.env` is clean before committing.)

- [ ] **Step 3: Validate wiki links/anchors**

Run: `python3 tests/test_wiki.py`
Expected: `ALL PASS`.

- [ ] **Step 4: Commit**

```bash
git add src/docs/wiki/images/cc-overlay-builder.png src/docs/slides/assets/img/cc-overlay-builder.png
git commit -m "docs(wiki): refresh overlay-builder screenshot for Bold/Italic controls"
```

---

### Task 4: Final verification

- [ ] **Step 1: Full suite** — Run: `python3 tools/run-tests.py` → Expected: `ALL TEST FILES PASS`.
- [ ] **Step 2: Lint** — Run: `python3 tools/lint.py` → Expected: no findings.
- [ ] **Step 3: Build verify** — Run: `python3 tools/build.py` → Expected: exit 0, verify step OK (companion password empty, OBS tokenized, demo profile secret-free).
- [ ] **Step 4: Clean tree** — Run: `git status` and `git log --oneline main..HEAD` → Expected: working tree clean; the feature/docs commits present on `feat/builder-bold-italic`.

---

## Self-Review notes

- **Spec coverage:** compiler maps/branches + `KIND_TEXT`/`PROP_ORDER` (Task 1); `OV_CSSNAME` + two selects (Task 2); screenshot (Task 3); verification (Task 4). All spec "Files touched" covered.
- **Type consistency:** prop names `fontWeight`/`fontStyle` and the value sets {normal,bold}/{normal,italic} are identical across the compiler maps, `KIND_TEXT`, `PROP_ORDER`, `_declaration`, `OV_CSSNAME`, and the panel selects.
- **No placeholders:** every code step shows the exact edit.
- **Edge cases:** unknown/numeric/`oblique` values dropped (tested); text-only membership (tested); demo sync guard untouched.
