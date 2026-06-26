# Overlay Builder — Editable Preview Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Control Center overlay builder a session-only "Preview data" panel so an operator can type their own per-slot text, switch flag/POV states, and see every slot rendered faithfully on the canvas before checking in OBS.

**Architecture:** `SAMPLE["hud"]` in `overlay_build.py` stays the single source of *default* preview values (extended to cover every text slot) and gains a `FLAG_PRESETS` list; `/api/overlay/slots` ships `flagPresets` to the builder. The builder holds an editable copy (`ovState.preview`), mirrored to `localStorage` (never to profile files), and `ovFillSample()` renders the canvas from it — adding three runtime-fidelity mirrors that are missing today (flag colour via `data-state`, POV show/hide, team-name auto-fit).

**Tech Stack:** Python stdlib (no deps), vanilla JS in `control-center.html` (no JS libs), stdlib test scripts (no pytest).

## Global Constraints

- **Edit only under `src/`** (plus `tests/` and `docs/`). Never hand-edit `dist/`/`runtime/`.
- **English only** in all code, comments, UI strings, and docs.
- **No new runtime dependency.** Pure Python stdlib + vanilla JS.
- **Tests are stdlib scripts**, each runnable as `python3 tests/test_X.py`; functions are named `t_*` and auto-run by the file's `__main__` loop.
- **After any Python change run** `python3 tools/lint.py` (the CI lint job).
- **Scope:** `hud` page only — no `splitscreen`, no profile persistence, no `/hud/preview` change, no editable image/box keys.
- **Mandatory follow-up (CLAUDE.md hard rule):** the Control Center builder UI changes, so `src/docs/wiki/images/cc-overlay-builder.png` MUST be regenerated in this same change (Task 4) via the `wiki-screenshots` skill, captured from a local dev build.

---

### Task 1: Extend `SAMPLE["hud"]` + add `FLAG_PRESETS`

**Files:**
- Modify: `src/scripts/overlay_build.py:78-93` (the `SAMPLE` dict) and add a new constant after it.
- Test: `tests/test_overlay.py`

**Interfaces:**
- Produces: `overlay_build.FLAG_PRESETS` — a tuple of `{"state": str, "label": str}` dicts. `overlay_build.SAMPLE["hud"]` gains `"pov-name"` and `"flag-status"` string entries.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing tests**

Add these two functions to `tests/test_overlay.py` (anywhere among the other `t_*` functions; they use the existing `_read` helper and the `ob` import already at the top of the file):

```python
def t_ob_sample_covers_every_text_slot():
    """Every text-kind HUD slot has a non-empty SAMPLE entry so the builder
    canvas renders something for it. Box slots (images, the POV frame) are
    exempt — they carry an asset sample or are a frame with no text."""
    html = _read(ROOT, "src", "obs", "hud.html")
    slots = ob.extract_slots(html)
    sample = ob.SAMPLE["hud"]
    # A text slot is one whose prop set includes the text-only "fontSize"
    # (KIND_TEXT adds it; KIND_BOX does not).
    text_ids = [s["id"] for s in slots if "fontSize" in s["props"]]
    missing = [sid for sid in text_ids if not sample.get(sid)]
    assert not missing, "text slots missing a SAMPLE entry: %r" % missing


def t_ob_flag_presets_match_hud_states():
    """Every FLAG_PRESETS state is a real #flag-status[data-state="..."] hook
    in hud.html, so the builder's flag picker can colour the canvas. Guards
    drift if a state is renamed or removed from the page CSS."""
    html = _read(ROOT, "src", "obs", "hud.html")
    assert ob.FLAG_PRESETS, "FLAG_PRESETS must not be empty"
    for p in ob.FLAG_PRESETS:
        assert p.get("label"), "flag preset missing label: %r" % (p,)
        needle = 'data-state="%s"' % p["state"]
        assert needle in html, "flag state not a data-state hook in hud.html: %s" % p["state"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_overlay.py`
Expected: FAIL — `t_ob_flag_presets_match_hud_states` raises `AttributeError: module 'overlay_build' has no attribute 'FLAG_PRESETS'` (and `t_ob_sample_covers_every_text_slot` fails on the missing `pov-name`/`flag-status` entries).

- [ ] **Step 3: Extend `SAMPLE["hud"]`**

In `src/scripts/overlay_build.py`, add two entries to the `SAMPLE["hud"]` dict (after the `"race-control"` / `"clock"` lines, before the image-key entries). Result:

```python
        "race-control": "FCY — Full Course Yellow",
        "clock": "1:23:45",
        "pov-name": "John Doe",
        "flag-status": "Safety Car",
        "round-flag": {"flag": "belgium"},
```

(Leave the `team*-logo` image entries unchanged below it.)

- [ ] **Step 4: Add the `FLAG_PRESETS` constant**

Immediately after the closing `}` of the `SAMPLE` dict (currently line ~93), add:

```python
# Flag states offered in the builder's session-only preview picker. Each entry
# is {state, label}: `state` is the #flag-status[data-state="..."] CSS hook in
# src/obs/hud.html (the canvas sets it to preview the colour), `label` is the
# banner text shown. Every `state` MUST exist as a data-state rule in hud.html
# — tests/test_overlay.py::t_ob_flag_presets_match_hud_states guards drift.
FLAG_PRESETS = (
    {"state": "green-flag", "label": "Green Flag"},
    {"state": "yellow-flag", "label": "Yellow Flag"},
    {"state": "double-yellow", "label": "Double Yellow"},
    {"state": "safety-car", "label": "Safety Car"},
    {"state": "virtual-safety-car", "label": "Virtual Safety Car"},
    {"state": "full-course-yellow", "label": "Full Course Yellow"},
    {"state": "code-60", "label": "Code 60"},
    {"state": "red-flag", "label": "Red Flag"},
    {"state": "checkered-flag", "label": "Checkered Flag"},
)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 tests/test_overlay.py`
Expected: `ALL PASS` (including both new `ok t_ob_...` lines).

- [ ] **Step 6: Lint**

Run: `python3 tools/lint.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/scripts/overlay_build.py tests/test_overlay.py
git commit -m "feat(overlay): complete HUD sample data + add FLAG_PRESETS"
```

---

### Task 2: Ship `flagPresets` from `/api/overlay/slots`

**Files:**
- Modify: `src/racecast.py:4213-4215` (the `overlay_slots_data` return dict).
- Test: `tests/test_racecast.py` (new function near the existing `t_overlay_slots_data_from_real_hud` at line 1346), `tests/test_ui_server.py:166` (keep the route stub representative).

**Interfaces:**
- Consumes: `overlay_build.FLAG_PRESETS` (Task 1).
- Produces: `overlay_slots_data("hud")` returns a dict that now includes `"flagPresets": [ {state,label}, ... ]`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_racecast.py` (the module is imported as `m` there, as used by `t_overlay_slots_data_from_real_hud`):

```python
def t_overlay_slots_data_includes_flag_presets():
    r = m.overlay_slots_data("hud")
    assert r["ok"], r
    fp = r["flagPresets"]
    assert isinstance(fp, list) and fp, "flagPresets must be a non-empty list"
    assert all(isinstance(p, dict) and "state" in p and "label" in p for p in fp)
    assert "safety-car" in [p["state"] for p in fp]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `KeyError: 'flagPresets'`.

- [ ] **Step 3: Add `flagPresets` to the return dict**

In `src/racecast.py`, change the success return of `overlay_slots_data` (lines 4213-4215) to:

```python
        return {"ok": True, "page": page, "slots": ob.extract_slots(html),
                "css": ob.base_style(html), "body": ob.base_body(html),
                "sample": ob.SAMPLE.get(page, {}),
                "flagPresets": [dict(p) for p in ob.FLAG_PRESETS]}
```

- [ ] **Step 4: Keep the UI-server route stub representative**

In `tests/test_ui_server.py` at line 166, the stub return for the overlay-slots route currently ends with `"sample": {"stint": "STINT 3"}}`. Add a `flagPresets` key so the stub mirrors the real shape:

```python
                                           "sample": {"stint": "STINT 3"},
                                           "flagPresets": [{"state": "safety-car", "label": "Safety Car"}]},
```

(Match the surrounding indentation/braces exactly; this is the dict the fake `overlay_slots_data` returns in that test.)

- [ ] **Step 5: Run both tests to verify they pass**

Run: `python3 tests/test_racecast.py && python3 tests/test_ui_server.py`
Expected: both print `ALL PASS`.

- [ ] **Step 6: Lint**

Run: `python3 tools/lint.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/racecast.py tests/test_racecast.py tests/test_ui_server.py
git commit -m "feat(overlay): expose flagPresets via /api/overlay/slots"
```

---

### Task 3: Builder "Preview data" panel + faithful canvas render

**Files:**
- Modify: `src/ui/control-center.html` — CSS (near line 283), HTML panel (inside `#ov-panel`, after line 743), help text (line 765), and JS (`ovState` near line 2819, `loadOverlay` near 2854-2891, `ovBuildCanvas` near 2959-2965, `ovFillSample` at 2970-2986, plus new functions).
- Test: `tests/test_overlay.py` (a markup-presence test, since this file's JS has no unit harness — the repo tests HTML surfaces by string assertion, e.g. `t_splitscreen_page_wires_data_and_override`).

**Interfaces:**
- Consumes: `slotsR.flagPresets` (Task 2), `ovState.sample`, `ovState.slots` (each `{id,label,props}`), `ovState.shadow` (the canvas Shadow root), the existing `$()` id helper, and the base hud.html `.empty` class (which hides a slot — the same hook `setText`/`setFlag` toggle at runtime).
- Produces: `ovState.preview = {values, flagState, povActive}`; functions `ovPreviewInit`, `ovPreviewDefaults`, `ovPreviewKey`, `ovPreviewSave`, `ovPreviewReset`, `ovRenderPreviewPanel`, `ovPreviewText`, `ovPreviewFlag`, `ovPreviewPov`, `ovFitName`; rewritten `ovFillSample`.

- [ ] **Step 1: Write the failing markup test**

Add to `tests/test_overlay.py`:

```python
def t_control_center_has_preview_data_panel():
    """The overlay builder ships the session-only Preview-data panel + the
    editable preview model the canvas renders from."""
    html = _read(ROOT, "src", "ui", "control-center.html")
    for needle in ('id="ov-preview-states"', 'id="ov-preview-fields"',
                   'ovState.preview', 'function ovFillSample',
                   'function ovPreviewReset', 'function ovFitName',
                   'flagPresets', "'overlay-preview:'"):
        assert needle in html, "control-center.html missing: %s" % needle
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_overlay.py`
Expected: FAIL — `control-center.html missing: id="ov-preview-states"`.

- [ ] **Step 3: Verify the `.empty` hide hook exists (read-only sanity)**

Run: `grep -n '\.empty' src/obs/hud.html`
Expected: at least one rule that hides an `.empty` slot (e.g. `display:none` / `visibility:hidden`). This confirms toggling the `empty` class on the canvas faithfully shows/hides `flag-status`, `pov`, `pov-name`, and `race-control`. (If, unexpectedly, no `.empty` hide rule exists, add `'.el.empty{display:none}'` to `OV_SHADOW_CSS` near line 2840 so the canvas hides the same slots runtime does — then note it in the commit.)

- [ ] **Step 4: Add panel CSS**

In `src/ui/control-center.html`, near the `.ov-slotpick` rule (line 283), add:

```css
  .ovprev { margin:.4em 0; border:1px solid #2A3550; border-radius:6px; padding:.2em .5em; }
  .ovprev > summary { cursor:pointer; font-weight:600; }
  .ovprev-row { display:flex; align-items:center; gap:.4em; margin:.25em 0; font-size:.85em; }
  .ovprev-row input[type="text"], .ovprev-row select { flex:1; min-width:0; background:#232C42;
    color:var(--txt); border:1px solid #2A3550; border-radius:4px; padding:.15em .3em; }
```

- [ ] **Step 5: Add the panel HTML**

In `#ov-panel`, immediately after the `<p class="envhint" id="ov-pick" ...>` line (line 743), insert:

```html
              <details class="ovprev" id="ov-preview">
                <summary>Preview data</summary>
                <p class="envhint" style="margin:.3em 0">Session-only — try how your own content looks. Not saved to the profile; verify live in OBS with Preview.</p>
                <div id="ov-preview-states"></div>
                <div id="ov-preview-fields"></div>
                <button type="button" class="ov-gpreset" onclick="ovPreviewReset()">Reset preview data</button>
              </details>
```

- [ ] **Step 6: Update the builder help text**

At line 765, replace the trailing sentence so it points at the panel. Change:

```
live via Apply in OBS. The canvas shows sample data over your <b>Overlay.png</b> frame — verify live with Preview.</p>
```

to:

```
live via Apply in OBS. The canvas shows your editable <b>Preview data</b> over your <b>Overlay.png</b> frame — verify live in OBS with Preview.</p>
```

- [ ] **Step 7: Add `preview` + `flagPresets` to `ovState`**

In the `ovState` object literal (lines 2819-2823), add two fields (e.g. after `sample: {},`):

```javascript
const ovState = {page: 'hud', slots: [], sample: {}, flagPresets: [], preview: null,
                 baseCss: '', body: '',
                 layout: null, fonts: [], library: [], scale: 1, sel: null,
                 shadow: null, selBox: null, fields: {}, undo: [], redo: [],
                 grid: {show: false, size: 10, snap: false}, gridEl: null,
                 zoom: 'fit'};
```

- [ ] **Step 8: Wire preview load in `loadOverlay`**

In `loadOverlay`, after `ovState.sample = slotsR.sample || {};` (line 2868) add:

```javascript
    ovState.flagPresets = slotsR.flagPresets || [];
    ovState.active = layoutR.active || '';
    ovPreviewInit();
```

And after `ovRenderPanel();` (line 2886) add:

```javascript
  ovRenderPreviewPanel();
```

(`ovPreviewInit` runs before `ovBuildCanvas()` at line 2885 so the first canvas fill already reads the preview model.)

- [ ] **Step 9: Fill the canvas after styling (move one call)**

In `ovBuildCanvas`, the `ovFillSample();` call at line 2959 runs *before* slot overrides are applied, so team-name auto-fit would measure the un-styled width. Move it to *after* the styling loop. Delete the `ovFillSample();` at line 2959, and add it right after the `ovState.slots.forEach(... ovStyleSlot(s.id); });` loop (after line 2965, before `ovApplyZoom();`):

```javascript
  ovState.slots.forEach(s => {
    const el = sh.getElementById(s.id);
    if (!el) return;
    el.addEventListener('pointerdown', ovStartDrag);
    ovStyleSlot(s.id);
  });
  ovFillSample();
  ovApplyZoom();
  ovPositionSel();
```

- [ ] **Step 10: Replace `ovFillSample` and add the helper functions**

Replace the whole `ovFillSample` function (lines 2970-2986) with the version below, and add the preview-model + panel functions immediately after it:

```javascript
function ovFillSample() {
  const pv = ovState.preview || ovPreviewDefaults();
  const vals = pv.values || {};
  ovState.slots.forEach(s => {
    const el = ovState.shadow.getElementById(s.id);
    if (!el) return;
    const img = el.querySelector('img');
    // Flag status: colour from the picked state (data-state), text from its label.
    if (s.id === 'flag-status') {
      const preset = (ovState.flagPresets || []).find(p => p.state === pv.flagState);
      el.textContent = preset ? preset.label : '';
      if (preset) el.dataset.state = preset.state; else el.removeAttribute('data-state');
      el.classList.toggle('empty', !preset);
      return;
    }
    // POV frame + name follow the POV-active toggle (mirrors runtime povActive).
    if (s.id === 'pov') { el.classList.toggle('empty', !pv.povActive); return; }
    if (s.id === 'pov-name') {
      const nm = vals['pov-name'] || '';
      el.textContent = pv.povActive ? nm : '';
      el.classList.toggle('empty', !pv.povActive || !nm);
      return;
    }
    const v = vals[s.id];
    if (img && v && typeof v === 'object') {       // image slot: {flag|brand: key}
      const sub = v.flag ? 'flags' : (v.brand ? 'brands' : null);
      const key = v.flag || v.brand;
      if (sub && key) img.src = '/api/overlay/asset/' + sub + '/' + encodeURIComponent(key);
      el.classList.remove('empty');
    } else if (typeof v === 'string' && !img) {    // text slot
      el.textContent = v;
      el.classList.toggle('empty', !v);
      if (/^team\d-name$/.test(s.id)) ovFitName(el);   // mirror hud.html auto-fit
    } else {
      el.classList.remove('empty');
    }
  });
}

// Mirror of hud.html::fitName — shrink a team name from --team-name-max toward
// --team-name-min until it fits, so the canvas previews a long name the way the
// live overlay renders it (not as raw overflow).
function ovFitName(el) {
  const cs = getComputedStyle(el);
  const max = parseFloat(cs.getPropertyValue('--team-name-max')) || 30;
  const min = parseFloat(cs.getPropertyValue('--team-name-min')) || 16;
  let size = max;
  el.style.fontSize = size + 'px';
  while (size > min && el.scrollWidth > el.clientWidth) { size -= 1; el.style.fontSize = size + 'px'; }
}

// Session-only preview model: an editable copy of the server SAMPLE defaults,
// mirrored to localStorage per profile+page. NEVER written to profile files —
// it only changes what content the offline canvas shows.
function ovPreviewKey() { return 'overlay-preview:' + (ovState.active || '') + ':' + ovState.page; }

function ovPreviewDefaults() {
  const values = {};
  Object.keys(ovState.sample || {}).forEach(k => {
    const v = ovState.sample[k];
    values[k] = (v && typeof v === 'object') ? Object.assign({}, v) : v;
  });
  const flag0 = (ovState.flagPresets[0] && ovState.flagPresets[0].state) || '';
  return { values: values, flagState: flag0, povActive: true };
}

function ovPreviewInit() {
  ovState.preview = ovPreviewDefaults();
  try {
    const saved = JSON.parse(localStorage.getItem(ovPreviewKey()) || 'null');
    if (saved && typeof saved === 'object') {
      if (saved.values && typeof saved.values === 'object')
        Object.assign(ovState.preview.values, saved.values);
      if (typeof saved.flagState === 'string') ovState.preview.flagState = saved.flagState;
      if (typeof saved.povActive === 'boolean') ovState.preview.povActive = saved.povActive;
    }
  } catch (e) { /* malformed/old -> seeded defaults */ }
}

function ovPreviewSave() {
  try { localStorage.setItem(ovPreviewKey(), JSON.stringify(ovState.preview)); } catch (e) {}
}

function ovPreviewReset() {
  try { localStorage.removeItem(ovPreviewKey()); } catch (e) {}
  ovState.preview = ovPreviewDefaults();
  ovRenderPreviewPanel();
  ovFillSample();
}

function ovRenderPreviewPanel() {
  const pv = ovState.preview || ovPreviewDefaults();
  const sc = $('ov-preview-states'); if (!sc) return;
  sc.textContent = '';
  if ((ovState.flagPresets || []).length) {
    const row = document.createElement('label'); row.className = 'ovprev-row';
    row.appendChild(document.createTextNode('Flag'));
    const sel = document.createElement('select');
    const off = document.createElement('option'); off.value = ''; off.textContent = 'Off';
    sel.appendChild(off);
    ovState.flagPresets.forEach(p => {
      const o = document.createElement('option'); o.value = p.state; o.textContent = p.label;
      if (p.state === pv.flagState) o.selected = true;
      sel.appendChild(o);
    });
    sel.onchange = () => ovPreviewFlag(sel.value);
    row.appendChild(sel); sc.appendChild(row);
  }
  const povRow = document.createElement('label'); povRow.className = 'ovprev-row';
  const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = !!pv.povActive;
  cb.onchange = () => ovPreviewPov(cb.checked);
  povRow.appendChild(cb); povRow.appendChild(document.createTextNode('POV active'));
  sc.appendChild(povRow);

  const ff = $('ov-preview-fields'); ff.textContent = '';
  // One text field per text slot (those with the text-only fontSize prop), except
  // flag-status (driven by the picker above) and clock (the live race timer).
  ovState.slots.filter(s => s.props.indexOf('fontSize') !== -1
      && s.id !== 'flag-status' && s.id !== 'clock').forEach(s => {
    const row = document.createElement('label'); row.className = 'ovprev-row';
    row.appendChild(document.createTextNode(s.label));
    const inp = document.createElement('input'); inp.type = 'text';
    const v = pv.values[s.id];
    inp.value = (typeof v === 'string') ? v : '';
    inp.oninput = () => ovPreviewText(s.id, inp.value);
    row.appendChild(inp); ff.appendChild(row);
  });
}

function ovPreviewText(id, value) { ovState.preview.values[id] = value; ovPreviewSave(); ovFillSample(); }
function ovPreviewFlag(state) { ovState.preview.flagState = state; ovPreviewSave(); ovFillSample(); }
function ovPreviewPov(on) { ovState.preview.povActive = !!on; ovPreviewSave(); ovFillSample(); }
```

- [ ] **Step 11: Run the markup test to verify it passes**

Run: `python3 tests/test_overlay.py`
Expected: `ALL PASS` (incl. `ok t_control_center_has_preview_data_panel`).

- [ ] **Step 12: Manual smoke check in a local dev build**

Run the Control Center from source (no `VERSION` stamp) and open the overlay builder:

```bash
python3 src/racecast.py ui
```

Verify in the Profile view → overlay builder: a "Preview data" disclosure appears in the right-hand panel; expanding it shows a Flag dropdown (Off + the 9 states), a "POV active" checkbox, and a text field per text slot. Changing a team name re-fits it on the canvas; picking a flag colours `#flag-status`; unchecking POV hides the POV frame + name; clearing Race control hides its banner. Reload the page → your edits persist (localStorage). Click "Reset preview data" → defaults return. (No relay required — the builder canvas is offline.)

- [ ] **Step 13: Commit**

```bash
git add src/ui/control-center.html tests/test_overlay.py
git commit -m "feat(overlay): editable session-only Preview-data panel in the builder"
```

---

### Task 4: Refresh the wiki screenshot + final verification

**Files:**
- Modify: `src/docs/wiki/images/cc-overlay-builder.png` (regenerated, committed).

**Interfaces:**
- Consumes: the finished builder UI from Task 3.

- [ ] **Step 1: Regenerate the builder screenshot**

Invoke the `wiki-screenshots` skill and follow it to recapture the overlay-builder image. Capture from a **local dev build** (run `racecast ui` straight from `src/`, no `VERSION` stamp, so the version badge matches the other `cc-*.png`). Use the demo profile per the skill's reproducible recipe, open the overlay builder, **expand the new "Preview data" panel** so the change is visible, and take the element screenshot of the builder card (the framing the skill specifies) to `src/docs/wiki/images/cc-overlay-builder.png`.

- [ ] **Step 2: Run the full test suite**

Run: `python3 tools/run-tests.py`
Expected: the whole suite passes (this is what CI runs).

- [ ] **Step 3: Lint**

Run: `python3 tools/lint.py`
Expected: no errors.

- [ ] **Step 4: Build verify**

Run: `python3 tools/build.py`
Expected: build + self-verify succeed (tokenization, blanked password, no secrets, no shell scripts).

- [ ] **Step 5: Commit**

```bash
git add src/docs/wiki/images/cc-overlay-builder.png
git commit -m "docs(wiki): refresh overlay-builder screenshot for Preview-data panel"
```

---

## Self-Review

**Spec coverage:**
- Editable per-slot text → Task 3 (panel text fields + `ovPreviewText`). ✅
- Switch dynamic states (flag colour, POV on/off, race-control on/off) → Task 3 (flag picker + POV checkbox + empty-text-hides race control), backed by Task 1 `FLAG_PRESETS` + Task 2 `flagPresets`. ✅
- Every slot renders something → Task 1 (`SAMPLE` completeness + test) + Task 3 (`pov`/`pov-name` handling). ✅
- Session-only, no profile persistence → Task 3 (localStorage, reset button); no profile-file writes. ✅
- `/hud/preview` unchanged, no splitscreen, no image-key editing → respected (not touched). ✅
- Three runtime-fidelity gaps (flag colour, POV visibility, team auto-fit) → Task 3 (`ovFillSample` + `ovFitName`). ✅
- Mandatory wiki screenshot → Task 4. ✅
- Tests (completeness, drift guard, endpoint shape, markup) → Tasks 1-3. ✅

**Placeholder scan:** No TBD/TODO/"add error handling"/"similar to". All code blocks are complete and concrete. ✅

**Type consistency:** `ovState.preview` shape `{values, flagState, povActive}` is identical across `ovPreviewDefaults`, `ovPreviewInit`, `ovFillSample`, `ovRenderPreviewPanel`, and the three setters. `FLAG_PRESETS` items are `{state,label}` in Python (Task 1), serialized verbatim by Task 2, and read as `p.state`/`p.label` in Task 3. `flagPresets` key name matches end to end. ✅
