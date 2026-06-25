# HUD Brand-Name element + per-slot visibility toggle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-team Brand-Name **text** element to the HUD (sourced from a new "Brand Name Override" Configuration column with fallback to the existing brand text), and add a real per-slot hide/show toggle to the visual overlay builder.

**Architecture:** The relay's `parse_config_roster` gains a `brandName` field (override-or-verbatim) on each roster entry; it flows through the existing team-dict builders into `/hud/data`, where three new `data-edit` text slots render it. The pure overlay compiler gains a `visible` boolean property that emits `display:none`; the builder front-end gets an eye toggle plus a dimmed (not hidden) canvas treatment so a hidden slot stays selectable.

**Tech Stack:** Pure Python 3 stdlib (relay + compiler), vanilla JS + Shadow DOM (builder), stdlib runnable test scripts (no pytest).

## Global Constraints

- **Edit only under `src/`** (plus `tests/` and `docs/`). Never hand-edit `dist/`/`runtime/`.
- **English only** in all code, comments, and docs.
- **No new dependencies** — Python stdlib + vanilla JS only.
- Tests are runnable scripts: `python3 tests/test_<name>.py` (each `t_*` function runs from `__main__`). The full suite is `python3 tools/run-tests.py`; lint is `python3 tools/lint.py` (run after any Python change).
- **The brand→logo mapping (`brandKey`) must never change** — the override affects displayed text only.
- A visible Control-Center change requires refreshing `src/docs/wiki/images/cc-overlay-builder.png` in the same change (Task 5).
- After shipping changes, `python3 tools/build.py` must still pass its verify step.

---

### Task 1: Relay — `brandName` in roster + payload (data layer)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`BRAND_TEXT_HEADERS` block ~815; `parse_config_roster` ~848-873; `team_entry` ~954-962; `HudSource.resolve_team` ~2890-2898; the two empty-team placeholders ~2777 and ~2871)
- Test: `tests/test_hud.py`

**Interfaces:**
- Produces: roster entries are now `{"number": str, "brandKey": str, "brandName": str}`; every `/hud/data` team object is `{"name", "number", "brandKey", "brandName"}`. `brandName = override.strip() or verbatim_brand_text.strip()` (override = the "Brand Name Override" column; verbatim = the matched `BRAND_TEXT_HEADERS` column). Consumed by Task 2 (hud.html `setTeam`).

- [ ] **Step 1: Write the failing tests** — update every exact team/roster dict assertion to include `brandName`, and add an override-precedence test.

In `tests/test_hud.py`, add the new fixture + test (place after `t_parse_config_roster_accepts_brand_name_header`, ~line 97):

```python
# New "Brand Name Override" column: when present it wins for the DISPLAY name,
# but never changes the logo mapping (brandKey stays the asset_key of Brand).
CONFIG_CSV_BRAND_OVERRIDE = (
    "Teams,Brand Name,Brand Name Override,Race Control\n"
    "OVO eSports #111,Porsche,Porsche 963,Formation Lap\n"   # override wins for text
    "Elite Racing Squad #73,BMW,,Final Lap\n"                 # blank override -> verbatim
)


def t_parse_config_roster_brand_name_override():
    r = m.parse_config_roster(CONFIG_CSV_BRAND_OVERRIDE)
    # override wins for the display name; brandKey still maps from Brand ("porsche")
    assert r["OVO eSports"] == {
        "number": "111", "brandKey": "porsche", "brandName": "Porsche 963"}, r
    # empty override falls back to the verbatim brand text
    assert r["Elite Racing Squad"] == {
        "number": "73", "brandKey": "bmw", "brandName": "BMW"}, r
```

Then update these existing assertions (add the `brandName` key; value = the verbatim brand cell, or `""` where `brandKey` is `""`):

```python
# t_parse_config_roster (~73-75) — Brand Key col = Porsche/Porsche/Ferrari
    assert r["OVO eSports"] == {"number": "111", "brandKey": "porsche", "brandName": "Porsche"}, r
    assert r["Feel Good Racing"] == {"number": "303", "brandKey": "porsche", "brandName": "Porsche"}, r
    assert r["NWR Motorsport"] == {"number": "224", "brandKey": "ferrari", "brandName": "Ferrari"}, r

# t_parse_config_roster_accepts_brand_name_header (~94-96) — Brand Name col
    assert r["OVO eSports"] == {"number": "111", "brandKey": "porsche", "brandName": "Porsche"}, r
    assert r["Elite Racing Squad"] == {"number": "73", "brandKey": "bmw", "brandName": "BMW"}, r
    assert r["Alien Motorsports"] == {"number": "999", "brandKey": "amg", "brandName": "AMG"}, r

# t_parse_config_roster_ignores_image_columns (~101-102) — no brand text col -> ""
    assert m.parse_config_roster("Teams,Brand Logo,Brands\nX #1,,\n") == {
        "X": {"number": "1", "brandKey": "", "brandName": ""}}

# t_build_hud_data (~115-116)
    assert d["teams"][0] == {"name": "OVO eSports", "number": "111", "brandKey": "porsche", "brandName": "Porsche"}
    assert d["teams"][2] == {"name": "NWR Motorsport", "number": "224", "brandKey": "ferrari", "brandName": "Ferrari"}

# t_build_hud_data_unknown_brand_blank (~123)
    assert d["teams"][0] == {"name": "Mystery Team", "number": "0", "brandKey": "", "brandName": ""}

# t_roster_number_column (~295-296) — Brand Name = Porsche/BMW
    assert r == {"OVO eSports": {"number": "111", "brandKey": "porsche", "brandName": "Porsche"},
                 "Feel Good": {"number": "303", "brandKey": "bmw", "brandName": "BMW"}}, r

# t_roster_embedded_fallback (~300-301) — Brand Name = Porsche/Audi
    assert r["OVO eSports"] == {"number": "111", "brandKey": "porsche", "brandName": "Porsche"}
    assert r["Apex Racing"] == {"number": "7", "brandKey": "audi", "brandName": "Audi"}

# t_roster_column_wins_over_embedded (~305)
    assert r == {"OVO eSports": {"number": "111", "brandKey": "porsche", "brandName": "Porsche"}}, r

# t_build_hud_data_team_number_and_strip (~327, 330-332)
    roster = {"OVO eSports": {"number": "111", "brandKey": "porsche", "brandName": "Porsche"}}
    ...
    assert d["teams"][0] == {"name": "OVO eSports", "number": "111", "brandKey": "porsche", "brandName": "Porsche"}
    assert d["teams"][1] == {"name": "Unknown", "number": "5", "brandKey": "", "brandName": ""}
    assert d["teams"][2] == {"name": "", "number": "", "brandKey": "", "brandName": ""}

# t_parse_config_roster_team_name_header (~337) — Brand = Porsche
    assert r == {"OVO eSports": {"number": "111", "brandKey": "porsche", "brandName": "Porsche"}}, r

# t_hud_roster_names_and_resolve (~367-369) — config Brand Name = Porsche
    assert hs.resolve_team("OVO eSports") == {"name": "OVO eSports", "number": "111", "brandKey": "porsche", "brandName": "Porsche"}
    assert hs.resolve_team("Ghost #9") == {"name": "Ghost", "number": "9", "brandKey": "", "brandName": ""}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_hud.py`
Expected: FAIL — assertions report missing/extra `brandName` key (e.g. `AssertionError` on `t_parse_config_roster`).

- [ ] **Step 3: Implement the relay changes**

In `src/relay/racecast-feeds.py`, after `BRAND_TEXT_HEADERS` (~815) add:

```python
# Optional DISPLAY-name override column. When present and non-empty it overrides
# the brand TEXT shown in the HUD; it NEVER affects the brand logo (brandKey is
# always asset_key(Brand)). Exact whole-cell match -> no collision with
# BRAND_TEXT_HEADERS' "brand name".
BRAND_NAME_OVERRIDE_HEADERS = ("brand name override",)
```

In `parse_config_roster`, locate the override column and build `brandName`. Replace the brand line + the `out[name] = ...` line (~861-872):

```python
    bi = next((header.index(h) for h in BRAND_TEXT_HEADERS if h in header), None)
    oi = next((header.index(h) for h in BRAND_NAME_OVERRIDE_HEADERS if h in header), None)
    ni = next((header.index(h) for h in NUMBER_HEADERS if h in header), None)
    out = {}
    for row in rows[1:]:
        if len(row) <= ti:
            continue
        name, embedded = split_team_label(row[ti])
        if not name:
            continue
        col_num = (row[ni].strip() if ni is not None and len(row) > ni else "")
        brand_raw = (row[bi].strip() if bi is not None and len(row) > bi else "")
        override = (row[oi].strip() if oi is not None and len(row) > oi else "")
        out[name] = {"number": col_num or embedded,
                     "brandKey": asset_key(brand_raw),
                     "brandName": override or brand_raw}
    return out
```

In `team_entry` (~959-962), add `brandName`:

```python
    return {"name": name,
            "number": info.get("number") or embedded,
            "brandKey": info.get("brandKey", ""),
            "brandName": info.get("brandName", "")}
```

In `HudSource.resolve_team` (~2895-2898), add `brandName`:

```python
        return {"name": name,
                "number": info.get("number") or embedded,
                "brandKey": info.get("brandKey", ""),
                "brandName": info.get("brandName", "")}
```

In the `EMPTY` placeholder (~2777) update the team template:

```python
             "teams": [{"name": "", "number": "", "brandKey": "", "brandName": ""} for _ in range(3)],
```

In the padding loop (~2871):

```python
                    teams.append({"name": "", "number": "", "brandKey": "", "brandName": ""})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_hud.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/relay/racecast-feeds.py tests/test_hud.py
git commit -m "feat(hud): brandName (override-or-verbatim) in roster + team payload"
```

---

### Task 2: HUD page — three Brand-Name text slots + builder sample

**Files:**
- Modify: `src/obs/hud.html` (base CSS team block ~43-58; slot markup ~102-110; `setTeam` ~170-185)
- Modify: `src/scripts/overlay_build.py` (`SAMPLE["hud"]` ~74-88)
- Test: `tests/test_overlay.py` (`t_ob_extract_slots_from_real_hud` ~220; `t_ob_sample_has_flag_and_brand_images` ~478)

**Interfaces:**
- Consumes: `team.brandName` from Task 1.
- Produces: three new editable text slots `team1-brand`, `team2-brand`, `team3-brand` (picked up automatically by `extract_slots`); `SAMPLE["hud"]` carries brand text for each.

- [ ] **Step 1: Write the failing tests** — extend the extraction-order and sample assertions.

In `tests/test_overlay.py`, update `t_ob_extract_slots_from_real_hud` (the `ids ==` list ~225-231) to include the three brand slots after each team-name:

```python
    assert ids == ["stint", "session", "streamer", "round-top", "round-flag",
                   "round-country",
                   "team1-logo", "team1-num", "team1-name", "team1-brand",
                   "team2-logo", "team2-num", "team2-name", "team2-brand",
                   "team3-logo", "team3-num", "team3-name", "team3-brand",
                   "race-control", "pov", "pov-name", "clock"]
```

Add a sample assertion (append inside `t_ob_sample_has_flag_and_brand_images`, after the existing brand loop):

```python
    # brand-name text slots preview with text (issue: brand name element)
    for tid in ("team1-brand", "team2-brand", "team3-brand"):
        assert isinstance(h.get(tid), str) and h[tid], tid
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_overlay.py`
Expected: FAIL — `t_ob_extract_slots_from_real_hud` (ids mismatch) and the sample assertion (`team1-brand` missing).

- [ ] **Step 3: Add the slots, CSS, sample, and setTeam population**

In `src/obs/hud.html`, add a default-position CSS rule per brand slot. After the `#team3-name` rule (~58) add:

```css
  .team-brand { height: 22px; width: 250px; font-size: 16px; color: #cfd6df;
    overflow: hidden; white-space: nowrap; }
  #team1-brand { left: 453px; top: 1064px; }
  #team2-brand { left: 896px; top: 1064px; }
  #team3-brand { left: 1340px; top: 1064px; }
```

Add the three `data-edit` text slots — one directly after each team-name slot (after lines 104 / 107 / 110):

```html
  <div id="team1-brand" class="el team-brand white" data-edit="Team 1 brand name" data-edit-kind="text"></div>
```
```html
  <div id="team2-brand" class="el team-brand white" data-edit="Team 2 brand name" data-edit-kind="text"></div>
```
```html
  <div id="team3-brand" class="el team-brand white" data-edit="Team 3 brand name" data-edit-kind="text"></div>
```

In `setTeam` (~177-184), after the `nameEl` block and before the `logoEl` block, populate the brand text:

```javascript
    const brandEl = document.getElementById("team" + n + "-brand");
    const brandName = (team && team.brandName) || "";
    brandEl.textContent = brandName;
    brandEl.classList.toggle("empty", !brandName);
```

In `src/scripts/overlay_build.py`, extend `SAMPLE["hud"]` (~79-81) with brand text next to each team's existing sample:

```python
        "team1-num": "7", "team1-name": "Team Redline", "team1-brand": "BMW",
        "team2-num": "23", "team2-name": "Apex Racing", "team2-brand": "Porsche",
        "team3-num": "99", "team3-name": "Night Shift Motorsport", "team3-brand": "Ferrari",
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_overlay.py`
Expected: `ALL PASS` (note: `t_shipped_demo_overlay_css_matches_its_layout` stays green — the demo layout is untouched and the new slots use base CSS only).

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/obs/hud.html src/scripts/overlay_build.py tests/test_overlay.py
git commit -m "feat(hud): per-team Brand Name text slots + builder sample"
```

---

### Task 3: Compiler — `visible` property → `display:none`

**Files:**
- Modify: `src/scripts/overlay_build.py` (`PROP_ORDER` ~42-48; `KIND_BOX` ~56-58; `_declaration` ~227-267)
- Test: `tests/test_overlay.py`

**Interfaces:**
- Produces: `visible` is an allowed prop on every slot (in `KIND_BOX`, inherited by `KIND_TEXT`). `visible: false` compiles to `display: none`; `visible: true` or absent emits no rule; a non-boolean value is dropped. Consumed by Task 4 (builder toggle).

- [ ] **Step 1: Write the failing tests**

In `tests/test_overlay.py`, add after `t_ob_compile_rotation` (~the SK/`_css_x` helpers already exist near line 525):

```python
def t_ob_compile_visible():
    # false -> display:none; true/absent -> no display rule; non-bool dropped
    assert "display: none" in _css_x({"visible": False})
    assert "display" not in _css_x({"visible": True})
    assert "display" not in _css_x({})
    assert "display" not in _css_x({"visible": "no"})
    assert "display" not in _css_x({"visible": 0})


def t_ob_visible_is_a_box_prop():
    # every slot (box + text) accepts visible
    assert "visible" in ob.KIND_BOX
    assert "visible" in ob.KIND_TEXT
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_overlay.py`
Expected: FAIL — `t_ob_compile_visible` (`display: none` not found; `visible` not emitted) and `t_ob_visible_is_a_box_prop`.

- [ ] **Step 3: Implement the `visible` property**

In `src/scripts/overlay_build.py`:

Add `"visible"` to the end of `PROP_ORDER` (~48):

```python
PROP_ORDER = ("left", "top", "width", "height", "padding",
              "fontSize", "lineHeight", "letterSpacing",
              "borderWidth", "borderRadius",
              "teamNameMax", "teamNameMin", "fontFamily", "color",
              "background", "borderColor", "borderStyle",
              "align", "valign", "textTransform", "opacity",
              "rotation", "textShadow", "visible")
```

Add `"visible"` to `KIND_BOX` (~56-58):

```python
KIND_BOX = ("left", "top", "width", "height", "padding",
            "background", "borderWidth", "borderStyle", "borderColor",
            "borderRadius", "opacity", "rotation", "visible")
```

In `_declaration`, handle `visible` BEFORE the `_safe_value` coercion (because `bool` is an `int` subclass and would otherwise fall through to `None`). Insert right after the `textShadow` branch (~230):

```python
    if prop == "textShadow":
        return _text_shadow_decl(value)
    if prop == "visible":
        # Only an explicit False hides the slot; True/anything-else = default shown.
        return "display: none" if value is False else None
    value = _safe_value(value)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_overlay.py`
Expected: `ALL PASS` (`t_shipped_demo_overlay_css_matches_its_layout` still green — no demo slot sets `visible`).

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/overlay_build.py tests/test_overlay.py
git commit -m "feat(overlay): per-slot visible property compiling to display:none"
```

---

### Task 4: Builder front-end — eye toggle + dimmed canvas treatment

**Files:**
- Modify: `src/ui/control-center.html` (`OV_SHADOW_CSS` ~2789-2794; `ovApplyProp` ~2923-2955; `ovStyleSlot` ~2957-2963; `ovRenderPanel` ~3209-3310)
- Test: manual (browser builder); no JS unit harness in this repo — covered by full suite + lint, and the Task 5 screenshot exercises the surface.

**Interfaces:**
- Consumes: the `visible` prop from Task 3 (slots already advertise it via `meta.props`).
- Produces: an eye/checkbox toggle in the property panel that writes `visible:false` (hidden) / clears it (shown); hidden slots render dimmed + dashed + badged on the canvas (never `display:none`, so they stay selectable).

- [ ] **Step 1: Add the canvas "hidden" styling**

In `src/ui/control-center.html`, extend `OV_SHADOW_CSS` (append to the string block ~2789-2794, before the existing closing of the concatenation):

```javascript
  '.ov-hidden{opacity:.32!important;outline:2px dashed #f59e0b!important;outline-offset:-1px}' +
  '.ov-hidden::after{content:"hidden";position:absolute;top:0;left:0;z-index:60;' +
  'font:700 9px/1.4 system-ui,sans-serif;background:#f59e0b;color:#111;padding:0 3px;border-radius:2px}' +
```

(Insert these two lines as additional `+ '...'` terms in the same concatenated `OV_SHADOW_CSS` literal; keep the trailing `+` consistent with the surrounding lines.)

- [ ] **Step 2: Handle `visible` in `ovApplyProp`**

In `ovApplyProp` (~2930), add a `visible` branch right after the `textShadow` branch (before the generic `value === ''` unset path, since `visible` is not in `OV_CSSNAME`):

```javascript
  if (prop === 'visible') {
    el.classList.toggle('ov-hidden', value === false);   // canvas: dim, don't remove
    return;
  }
```

- [ ] **Step 3: Apply `visible` in `ovStyleSlot`**

In `ovStyleSlot` (~2961-2962), after the `textShadow` apply line, add:

```javascript
  ovApplyProp(el, 'textShadow', ov.textShadow);
  ovApplyProp(el, 'visible', ov.visible);
```

- [ ] **Step 4: Add the toggle to the panel**

In `ovRenderPanel`, right after the `h4` label is appended (~3227, after `panel.appendChild(h);`), add the visibility toggle (all slots carry `visible`):

```javascript
  if (has('visible')) {
    const wrap = document.createElement('div'); wrap.className = 'ovinline';
    const cb = document.createElement('input'); cb.type = 'checkbox';
    cb.checked = ov.visible !== false;                 // shown unless explicitly hidden
    const lab = document.createElement('label'); lab.textContent = 'Visible';
    lab.style.margin = '0 0 0 6px';
    cb.onchange = () => ovSetProp(id, 'visible', cb.checked ? '' : false);
    wrap.append(cb, lab); panel.appendChild(wrap);
  }
```

Note: `ovSetProp(id, 'visible', false)` stores `false` (not deleted, since `false` is not in its `'' / undefined / null` delete set); `ovSetProp(id, 'visible', '')` deletes the key → back to default shown. `ovState.fields['visible']` is intentionally unset (the checkbox is rebuilt on every panel render).

- [ ] **Step 5: Verify the builder loads and behaves (manual)**

Run a local dev Control Center and exercise the toggle:

```bash
RACECAST_UI_PORT=8090 python3 src/racecast.py ui
```
Expected: in Profile → overlay builder, selecting any slot shows a **Visible** checkbox; unchecking dims the slot with a dashed outline + "hidden" badge (still selectable); re-checking restores it. (If a running instance owns 8089, the env var keeps this on a free port.) Stop with Ctrl-C.

- [ ] **Step 6: Run the full suite + lint, then commit**

```bash
python3 tools/run-tests.py
python3 tools/lint.py
git add src/ui/control-center.html
git commit -m "feat(builder): per-slot hide/show toggle with dimmed canvas treatment"
```
Expected: suite `ALL PASS` (in particular `tests/test_ui_server.py` and `tests/test_overlay.py`), lint clean.

---

### Task 5: Docs — wiki screenshot + Configuration column note

**Files:**
- Modify (regenerate): `src/docs/wiki/images/cc-overlay-builder.png`
- Modify: the Sheet-related wiki page under `src/docs/wiki/` documenting the Configuration tab columns (locate with the grep below)
- Test: `python3 tests/test_wiki.py`

- [ ] **Step 1: Find the Sheet/Configuration wiki page**

Run:
```bash
grep -rln "Brand Name\|Configuration tab\|Brand Key" src/docs/wiki/
```
Expected: the page(s) that list the Configuration columns (e.g. the Sheet-Webhook / Google-Sheet onboarding page).

- [ ] **Step 2: Document the new optional column**

Add one row/line to that page describing the **optional** `Brand Name Override` Configuration column — mechanism only: *"Optional. When set, this text is shown as the team's Brand Name HUD element instead of the `Brand`/`Brand Name` value; it does not change which brand **logo** is used. Leave blank to show the brand text verbatim."* Do not invent league procedure.

- [ ] **Step 3: Regenerate the overlay-builder screenshot**

Use the **`wiki-screenshots`** skill (drives a local dev build with the `demo` profile + `tools/obs-sim.py`, captures the `#ov-modal .ovmodal-card` / overlay-builder element). Capture from a **local dev build** (run `racecast ui` from `src/`, no `VERSION` stamped) so the version badge matches the other `cc-*.png`. Overwrite `src/docs/wiki/images/cc-overlay-builder.png`.

Note: running the demo-profile relay mutates `profiles/demo/profile.env` (writes `CONSOLE_SECRET`) — revert that file before committing (see the `demo-relay-writes-console-secret` memory).

- [ ] **Step 4: Validate wiki links/anchors**

Run: `python3 tests/test_wiki.py`
Expected: `ALL PASS` (no broken links/anchors from the edit).

- [ ] **Step 5: Commit**

```bash
git checkout -- profiles/demo/profile.env   # drop the CONSOLE_SECRET the demo relay wrote
git add src/docs/wiki/images/cc-overlay-builder.png src/docs/wiki/
git commit -m "docs(wiki): Brand Name Override column + refreshed overlay-builder screenshot"
```

---

### Task 6: Final verification

- [ ] **Step 1: Full suite**

Run: `python3 tools/run-tests.py`
Expected: `ALL PASS`.

- [ ] **Step 2: Lint**

Run: `python3 tools/lint.py`
Expected: no findings.

- [ ] **Step 3: Build verify (closest thing to CI)**

Run: `python3 tools/build.py`
Expected: assembles `dist/` and passes the verify step (tokenization, blanked password, no secrets, preflight present, no shell scripts).

- [ ] **Step 4: Confirm clean tree + branch ready for PR**

Run: `git status` and `git log --oneline main..HEAD`
Expected: working tree clean; the six feature/docs commits present on `feat/hud-brand-name-visibility`.

---

## Self-Review notes

- **Spec coverage:** Feature A data layer (Task 1) + HUD slots (Task 2); Feature B compiler (Task 3) + builder UI (Task 4); tests folded into each task; docs/screenshot (Task 5); verification (Task 6). All spec "Files touched" are covered.
- **Type consistency:** `brandName` key name is identical across `parse_config_roster`, `team_entry`, `resolve_team`, placeholders, `setTeam` (`team.brandName`), and `SAMPLE`. Slot ids `team{1,2,3}-brand` consistent across hud.html, the extraction test, and SAMPLE. `visible` prop name consistent across `KIND_BOX`/`PROP_ORDER`/`_declaration`/`ovApplyProp`/`ovStyleSlot`/`ovRenderPanel`.
- **No placeholders:** every code step shows the exact edit.
- **Edge cases:** missing override → verbatim fallback (tested); no brand column → `""` (tested); non-bool `visible` dropped (tested); demo sync test stays green (demo layout untouched).
