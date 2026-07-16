# Stint-scene full-page graphics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 12 new independently-toggleable full-page graphics to the on-air **Stint** scene (Weekend Info, Race Info, Next Event, Starting Grid, Grid Row 1–8), maintained via the Sheet Assets tab and shown/hidden from the Director Panel + Companion — mirroring the existing graphics (Standings, Weather) exactly.

**Architecture:** Three hardcoded surfaces must agree on the exact `scene`/`source` strings: the OBS collection (`src/obs/GT_Endurance.json` — image-source + invisible full-frame Stint scene-item per graphic), the Director Panel (`CONFIG.graphics*` arrays → `POST /obs/source`), and Companion (per-graphic `toggle_scene_item` OBS-module button). The download side (`get-graphics.py`) and the relay `/obs/source` endpoint are already generic — no change. A new structural test (`tests/test_stint_graphics.py`) guards all three surfaces against name-drift.

**Tech Stack:** Python 3 stdlib (tests are runnable scripts, no pytest), OBS scene-collection JSON, plain HTML/JS Director Panel, Bitfocus Companion `.companionconfig` JSON. Repo skills: `companion-buttons`, `companion-screenshots`, `wiki-screenshots`, `ui-visual-verification`.

## Global Constraints

- **Edit only under `src/`** (+ `tests/`, `docs/`). Never touch `dist/`/`runtime/`.
- **English only** in all code/docs/comments.
- **No secrets, no machine paths, no real IPs** anywhere (tests must run in CI).
- The **12 canonical labels** are byte-identical everywhere (OBS source name = OBS scene-item name = panel `source` = Companion `source` = Sheet Assets label): `Weekend Info`, `Race Info`, `Next Event`, `Starting Grid`, `Grid Row 1`, `Grid Row 2`, `Grid Row 3`, `Grid Row 4`, `Grid Row 5`, `Grid Row 6`, `Grid Row 7`, `Grid Row 8`. A single-character mismatch fails silently (panel 503 "scene item not found"; Companion no-op).
- All 12 graphics go **only** into the **Stint** scene, `"visible": false`, full-frame (`bounds 1920×1080`), independent on/off toggles (no exclusive/reveal logic).
- **Full test suite is `python3 tools/run-tests.py`**; lint is `python3 tools/lint.py`; ship-verify is `python3 tools/build.py`.
- **Wiki hard rule:** a change to the Director Panel or Companion buttons MUST refresh the matching `src/docs/wiki/images/*.png` in the same change.
- Fixed UUID / scene-item-id assignments (unique, non-colliding with existing `dddddd*`/`cccc*`/`bbbb*`/`f792*` and max existing item id 37):

  | Label | image-source `uuid` | scene-item `id` |
  |-------|---------------------|-----------------|
  | Weekend Info  | `eeeeee01-0000-4000-8000-000000000001` | 38 |
  | Race Info     | `eeeeee02-0000-4000-8000-000000000002` | 39 |
  | Next Event    | `eeeeee03-0000-4000-8000-000000000003` | 40 |
  | Starting Grid | `eeeeee04-0000-4000-8000-000000000004` | 41 |
  | Grid Row 1    | `eeeeee11-0000-4000-8000-000000000011` | 42 |
  | Grid Row 2    | `eeeeee12-0000-4000-8000-000000000012` | 43 |
  | Grid Row 3    | `eeeeee13-0000-4000-8000-000000000013` | 44 |
  | Grid Row 4    | `eeeeee14-0000-4000-8000-000000000014` | 45 |
  | Grid Row 5    | `eeeeee15-0000-4000-8000-000000000015` | 46 |
  | Grid Row 6    | `eeeeee16-0000-4000-8000-000000000016` | 47 |
  | Grid Row 7    | `eeeeee17-0000-4000-8000-000000000017` | 48 |
  | Grid Row 8    | `eeeeee18-0000-4000-8000-000000000018` | 49 |

---

### Task 1: OBS collection — 12 image-sources + 12 Stint scene-items

**Files:**
- Create: `tests/test_stint_graphics.py`
- Modify: `src/obs/GT_Endurance.json` (append 12 `image_source` defs to `"sources"`; insert 12 scene-items into the **Stint** scene's `settings.items`)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: the 12 canonical labels as OBS sources+scene-items. Later tasks (panel, Companion) reference the same label strings and `scene:"Stint"`. `tests/test_stint_graphics.py` grows a panel check in Task 2 and a Companion check in Task 3.

- [ ] **Step 1: Write the failing test** — `tests/test_stint_graphics.py`

```python
#!/usr/bin/env python3
"""Structural guard for the 12 added Stint full-page graphics (info + grid).
Run: python3 tests/test_stint_graphics.py

Asserts the three hardcoded surfaces agree on the exact scene/source strings:
OBS collection (this task), Director Panel (Task 2), Companion (Task 3). A
name-drift between them fails silently in production, so it is pinned here."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OBS = os.path.join(ROOT, "src", "obs", "GT_Endurance.json")
PANEL = os.path.join(ROOT, "src", "director", "director-panel.html")
COMPANION = os.path.join(ROOT, "src", "companion",
                         "racecast-buttons.companionconfig")

NEW_GRAPHICS = [
    "Weekend Info", "Race Info", "Next Event", "Starting Grid",
    "Grid Row 1", "Grid Row 2", "Grid Row 3", "Grid Row 4",
    "Grid Row 5", "Grid Row 6", "Grid Row 7", "Grid Row 8",
]


def _obs():
    with open(OBS, encoding="utf-8") as fh:
        return json.load(fh)


def t_obs_image_sources_present():
    d = _obs()
    by_name = {s["name"]: s for s in d["sources"] if s.get("id") == "image_source"}
    for label in NEW_GRAPHICS:
        assert label in by_name, f"missing image_source: {label}"
        s = by_name[label]
        assert s["settings"]["file"] == f"__RACECAST_GRAPHICS__/{label}.png", label
        assert s["settings"].get("linear_alpha") is True, label


def t_obs_stint_scene_items_present():
    d = _obs()
    stint = next(s for s in d["sources"] if s.get("name") == "Stint"
                 and s.get("id") == "scene")
    items = {i["name"]: i for i in stint["settings"]["items"]}
    src_uuid = {s["name"]: s["uuid"] for s in d["sources"]
                if s.get("id") == "image_source"}
    ids = [i["id"] for i in stint["settings"]["items"]]
    assert len(ids) == len(set(ids)), "duplicate scene-item id in Stint"
    for label in NEW_GRAPHICS:
        assert label in items, f"missing Stint scene-item: {label}"
        it = items[label]
        assert it["visible"] is False, label
        assert it["source_uuid"] == src_uuid[label], label
        assert it["bounds"] == {"x": 1920.0, "y": 1080.0}, label
        assert it["show_transition"]["name"] == f"{label} Show Transition", label
        assert it["hide_transition"]["name"] == f"{label} Hide Transition", label


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_stint_graphics.py`
Expected: FAIL — `AssertionError: missing image_source: Weekend Info`

- [ ] **Step 3: Mutate the OBS collection programmatically** — run this one-shot (NOT committed; it edits the tracked JSON in place with a minimal, byte-clean diff)

```python
python3 - <<'PY'
import json
p = "src/obs/GT_Endurance.json"
raw = open(p, encoding="utf-8").read()
d = json.loads(raw)

NEW = [
    ("Weekend Info",  "eeeeee01-0000-4000-8000-000000000001", 38),
    ("Race Info",     "eeeeee02-0000-4000-8000-000000000002", 39),
    ("Next Event",    "eeeeee03-0000-4000-8000-000000000003", 40),
    ("Starting Grid", "eeeeee04-0000-4000-8000-000000000004", 41),
    ("Grid Row 1",    "eeeeee11-0000-4000-8000-000000000011", 42),
    ("Grid Row 2",    "eeeeee12-0000-4000-8000-000000000012", 43),
    ("Grid Row 3",    "eeeeee13-0000-4000-8000-000000000013", 44),
    ("Grid Row 4",    "eeeeee14-0000-4000-8000-000000000014", 45),
    ("Grid Row 5",    "eeeeee15-0000-4000-8000-000000000015", 46),
    ("Grid Row 6",    "eeeeee16-0000-4000-8000-000000000016", 47),
    ("Grid Row 7",    "eeeeee17-0000-4000-8000-000000000017", 48),
    ("Grid Row 8",    "eeeeee18-0000-4000-8000-000000000018", 49),
]

def image_source(label, uuid):
    return {
        "prev_ver": 536936450, "name": label, "uuid": uuid,
        "id": "image_source", "versioned_id": "image_source",
        "settings": {"file": f"__RACECAST_GRAPHICS__/{label}.png",
                     "unload": False, "linear_alpha": True},
        "mixers": 0, "sync": 0, "flags": 0, "volume": 1.0, "balance": 0.5,
        "enabled": True, "muted": False, "push-to-mute": False,
        "push-to-mute-delay": 0, "push-to-talk": False, "push-to-talk-delay": 0,
        "hotkeys": {}, "deinterlace_mode": 0, "deinterlace_field_order": 0,
        "monitoring_type": 0, "private_settings": {},
    }

def scene_item(label, uuid, iid):
    return {
        "name": label, "source_uuid": uuid, "visible": False, "locked": True,
        "rot": 0.0, "align": 5, "bounds_type": 2, "bounds_align": 0,
        "bounds_crop": False, "crop_left": 0, "crop_top": 0, "crop_right": 0,
        "crop_bottom": 0, "id": iid, "group_item_backup": False,
        "pos": {"x": 0.0, "y": 0.0}, "scale": {"x": 1.0, "y": 1.0},
        "bounds": {"x": 1920.0, "y": 1080.0}, "scale_filter": "disable",
        "blend_method": "default", "blend_type": "normal",
        "show_transition": {"id": "fade_transition",
                            "versioned_id": "fade_transition",
                            "name": f"{label} Show Transition",
                            "transition": {}, "duration": 300},
        "hide_transition": {"id": "fade_transition",
                            "versioned_id": "fade_transition",
                            "name": f"{label} Hide Transition",
                            "transition": {}, "duration": 300},
        "private_settings": {},
    }

existing = {s["name"] for s in d["sources"]}
for label, uuid, _ in NEW:
    assert label not in existing, f"source already present: {label}"
    d["sources"].append(image_source(label, uuid))

stint = next(s for s in d["sources"]
             if s.get("name") == "Stint" and s.get("id") == "scene")
items = stint["settings"]["items"]
qw = next(i for i, it in enumerate(items) if it["name"] == "Quali Weather")
block = [scene_item(l, u, n) for (l, u, n) in NEW]
stint["settings"]["items"] = items[:qw + 1] + block + items[qw + 1:]

out = json.dumps(d, indent=4, ensure_ascii=False)   # NO trailing newline: the
open(p, "w", encoding="utf-8").write(out)            # source file has none
print("added", len(NEW), "sources + scene-items")
PY
```

Note on z-order: the 12 items are appended as a contiguous block right after `Quali Weather`. Exact stacking among them is immaterial — each is a full-frame image that paints only its own content (transparent elsewhere), so independent toggles never overlap destructively. Reorder the `items` array later only if a future artwork needs specific layering.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_stint_graphics.py`
Expected: `ok t_obs_image_sources_present` / `ok t_obs_stint_scene_items_present` / `ALL PASS`

- [ ] **Step 5: Verify no unrelated churn + placeholder logic still derives the set**

Run: `git diff --stat src/obs/GT_Endurance.json` (expect only additions), then `python3 tests/test_placeholders.py` and `python3 tests/test_build.py`
Expected: both PASS (the placeholder/seed + build-verify derive the expected graphics from the collection generically — the 12 new tokens are picked up automatically).

- [ ] **Step 6: Commit**

```bash
git add tests/test_stint_graphics.py src/obs/GT_Endurance.json
git commit -m "feat(obs): 12 new full-page graphics in the Stint scene (info + grid)

Add Weekend Info, Race Info, Next Event, Starting Grid, Grid Row 1-8 as
invisible full-frame image-sources + Stint scene-items, mirroring the
existing Standings/Weather graphics. Independent on/off toggles."
```

---

### Task 2: Director Panel — grouped Pre-Race + Grid toggle blocks

**Files:**
- Modify: `src/director/director-panel.html` (add two `<section class="bus">` blocks near the existing Gfx bus at `:673`; add `CONFIG.graphicsPreRace` + `CONFIG.graphicsGrid` near `:874`; render them near `:1042`)
- Modify: `tests/test_stint_graphics.py` (add the panel check)

**Interfaces:**
- Consumes: the 12 canonical labels + `scene:"Stint"` from Task 1.
- Produces: panel toggle buttons that POST `/obs/source {scene:"Stint", source:<label>, on}` via the existing `toggleSource` handler; each button is registered in `toggleKeys` so it gets the on-air highlight from `/obs/state`.

- [ ] **Step 1: Add the panel check to the test (failing)** — append to `tests/test_stint_graphics.py` before the `__main__` block

```python
def t_panel_lists_new_graphics():
    with open(PANEL, encoding="utf-8") as fh:
        html = fh.read()
    # Two new config arrays + two new bus containers exist.
    assert "graphicsPreRace" in html, "missing CONFIG.graphicsPreRace"
    assert "graphicsGrid" in html, "missing CONFIG.graphicsGrid"
    assert 'id="gfxPreRaceBus"' in html
    assert 'id="gfxGridBus"' in html
    # Every new source is wired with scene:"Stint" in a CONFIG entry.
    for label in NEW_GRAPHICS:
        assert f'source:"{label}"' in html, f"panel missing source: {label}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_stint_graphics.py`
Expected: FAIL — `AssertionError: missing CONFIG.graphicsPreRace`

- [ ] **Step 3: Add the two bus containers** — in `src/director/director-panel.html`, immediately after the existing Gfx bus line (`<section class="bus"><div class="cap">Gfx</div><div class="keys" id="gfxBus"></div></section>` at `:673`), insert:

```html
  <section class="bus"><div class="cap">Pre-Race</div><div class="keys" id="gfxPreRaceBus"></div></section>
  <section class="bus"><div class="cap">Grid</div>
    <div class="setrow"><div class="keys" id="gfxGridTopBus"></div></div>
    <div class="setrow"><div class="keys" id="gfxGridBus"></div></div>
  </section>
```

(`Starting Grid` renders in `#gfxGridTopBus` on its own row; the 8 rows wrap in `#gfxGridBus` below it — the semantic-row pattern used by the HUD bus.)

- [ ] **Step 4: Add the config arrays** — in `src/director/director-panel.html`, immediately after the closing `],` of `CONFIG.graphics` (`:886`), add:

```js
  graphicsPreRace: [
    {label:"WEEKEND",    scene:"Stint", source:"Weekend Info"},
    {label:"RACE INFO",  scene:"Stint", source:"Race Info"},
    {label:"NEXT EVENT", scene:"Stint", source:"Next Event"},
  ],
  graphicsGrid: [
    {label:"STARTING GRID", scene:"Stint", source:"Starting Grid", top:true},
    {label:"GRID R1", scene:"Stint", source:"Grid Row 1"},
    {label:"GRID R2", scene:"Stint", source:"Grid Row 2"},
    {label:"GRID R3", scene:"Stint", source:"Grid Row 3"},
    {label:"GRID R4", scene:"Stint", source:"Grid Row 4"},
    {label:"GRID R5", scene:"Stint", source:"Grid Row 5"},
    {label:"GRID R6", scene:"Stint", source:"Grid Row 6"},
    {label:"GRID R7", scene:"Stint", source:"Grid Row 7"},
    {label:"GRID R8", scene:"Stint", source:"Grid Row 8"},
  ],
```

- [ ] **Step 5: Render the new buses** — in `src/director/director-panel.html`, immediately after the existing `CONFIG.graphics.forEach(...)` block (`:1042-1045`), add:

```js
CONFIG.graphicsPreRace.forEach(item=>{
  const b = mkKey(item.label, item.scene, ()=>toggleSource(item, b));
  b._item = item; toggleKeys.push(b); $("#gfxPreRaceBus").appendChild(b);
});

CONFIG.graphicsGrid.forEach(item=>{
  const b = mkKey(item.label, item.scene, ()=>toggleSource(item, b));
  b._item = item; toggleKeys.push(b);
  $(item.top ? "#gfxGridTopBus" : "#gfxGridBus").appendChild(b);
});
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `python3 tests/test_stint_graphics.py`
Expected: `ok t_panel_lists_new_graphics` + prior tests + `ALL PASS`

- [ ] **Step 7: Visually verify the panel** — invoke the `ui-visual-verification` skill: render the Director Panel (SETUP tab), confirm the new **Pre-Race** (3 buttons) and **Grid** (Starting Grid on its own row + R1–R8 below) blocks appear, are readable, and toggle without layout breakage. This is required by the repo's blocking Stop-hook gate for panel changes.

- [ ] **Step 8: Commit**

```bash
git add src/director/director-panel.html tests/test_stint_graphics.py
git commit -m "feat(panel): Pre-Race + Grid graphic toggle blocks

Add grouped Director Panel toggles for the 12 new Stint graphics
(Weekend/Race Info/Next Event + Starting Grid + Grid Row 1-8), wired to
POST /obs/source with on-air highlight via toggleKeys."
```

---

### Task 3: Companion — Page 1 row 4 (info) + new GRID page (grid)

**Files:**
- Modify: `src/companion/racecast-buttons.companionconfig` (bump `pages.1.gridSize.maxRow` 3→4; add 3 info buttons on page 1 row 4; add a new page 5 "GRID" with 9 buttons)
- Modify: `tests/test_stint_graphics.py` (add the Companion check)

**Interfaces:**
- Consumes: the 12 canonical labels + `scene:"Stint"` from Task 1.
- Produces: one Companion `toggle_scene_item` OBS-module button per graphic (+ `scene_item_active` feedback), matching the existing graphics-button pattern (page 1 row 3).

- [ ] **Step 1: Add the Companion check to the test (failing)** — append to `tests/test_stint_graphics.py` before the `__main__` block

```python
def t_companion_toggles_new_graphics():
    with open(COMPANION, encoding="utf-8") as fh:
        cfg = json.load(fh)
    toggled = set()
    def walk(o):
        if isinstance(o, dict):
            if o.get("definitionId") == "toggle_scene_item":
                opt = o.get("options", {})
                scene = (opt.get("scene") or {}).get("value")
                source = (opt.get("source") or {}).get("value")
                if scene == "Stint" and source:
                    toggled.add(source)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(cfg)
    for label in NEW_GRAPHICS:
        assert label in toggled, f"companion missing toggle for: {label}"
    # Page 1 was extended to a 4th row for the info toggles.
    assert cfg["pages"]["1"]["gridSize"]["maxRow"] >= 4
    # A dedicated GRID page exists.
    names = [p.get("name") for p in cfg["pages"].values()]
    assert "GRID" in names, f"no GRID page (pages: {names})"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_stint_graphics.py`
Expected: FAIL — `AssertionError: companion missing toggle for: Weekend Info`

- [ ] **Step 3: Author + import the buttons via the `companion-buttons` skill**

Invoke the **`companion-buttons`** skill and author these buttons following the existing graphics-button pattern (page 1 row 3, e.g. `pages.1.controls.3.0` "Standings Toggle"): each button is `type:"button"` with a `feedbacks[0]` `scene_item_active` (bgcolor `13421568`) on the OBS connection `dv_e1zuVb_6XgPv0eRibl`, and a `steps.0.action_sets.down[0]` `toggle_scene_item` on the same connection with options `{scene:"Stint", all:false, source:<label>, visible:"toggle"}`. Generate fresh nanoid ids for `feedbacks[].id` and `action_sets.down[].id` (the skill handles this). The `style.text` is the label with `\n` line-wraps to fit the key (see below).

Layout:

- **Page 1 — extend to a 4th row.** Set `pages.1.gridSize.maxRow = 4`. Add `pages.1.controls.4.0/1/2`:

  | Cell | text | scene → source |
  |------|------|----------------|
  | `4.0` | `Weekend\nInfo\nToggle` | Stint → `Weekend Info` |
  | `4.1` | `Race Info\nToggle` | Stint → `Race Info` |
  | `4.2` | `Next Event\nToggle` | Stint → `Next Event` |

- **New Page 5 "GRID"** — add `pages.5` with a fresh nanoid `id`, `"name":"GRID"`, `gridSize {minColumn:0,maxColumn:7,minRow:0,maxRow:3}`, and `controls`:

  | Cell | text | scene → source |
  |------|------|----------------|
  | `0.0` | `Starting\nGrid\nToggle` | Stint → `Starting Grid` |
  | `1.0` | `Grid R1` | Stint → `Grid Row 1` |
  | `1.1` | `Grid R2` | Stint → `Grid Row 2` |
  | `1.2` | `Grid R3` | Stint → `Grid Row 3` |
  | `1.3` | `Grid R4` | Stint → `Grid Row 4` |
  | `1.4` | `Grid R5` | Stint → `Grid Row 5` |
  | `1.5` | `Grid R6` | Stint → `Grid Row 6` |
  | `1.6` | `Grid R7` | Stint → `Grid Row 7` |
  | `1.7` | `Grid R8` | Stint → `Grid Row 8` |

  Give page 5 a `PAGEUP`/`PAGEDOWN`-style nav only if the other pages have them (match the existing pattern; skip if they don't). Per the skill: export from a running Companion, then import with **"Import Preserving Unselected"** so the other pages/connections are untouched.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_stint_graphics.py`
Expected: `ok t_companion_toggles_new_graphics` + all prior + `ALL PASS`

- [ ] **Step 5: Click-test live** — per the `companion-buttons` skill, with a running Companion bound to the Tailscale IP + a running relay/OBS (or the obs-sim stand-in), click each new button and confirm the corresponding Stint source visibility flips and the `scene_item_active` feedback highlights.

- [ ] **Step 6: Commit**

```bash
git add src/companion/racecast-buttons.companionconfig tests/test_stint_graphics.py
git commit -m "feat(companion): buttons for 12 new Stint graphics

Page 1 gains a 4th row (Weekend/Race Info/Next Event toggles); new GRID
page adds Starting Grid + Grid Row 1-8 toggle_scene_item buttons."
```

---

### Task 4: Refresh wiki screenshots (hard rule)

**Files:**
- Modify: `src/docs/wiki/images/director-panel.png`
- Modify/Create: `src/docs/wiki/images/companion-page*.png` (extended Page 1 + new GRID page)

**Interfaces:**
- Consumes: the rendered Director Panel (Task 2) and Companion board (Task 3).
- Produces: committed, up-to-date wiki images.

- [ ] **Step 1: Regenerate the Director Panel image** — invoke the **`wiki-screenshots`** skill (demo profile + `tools/obs-sim.py` stand-in, local dev build) and recapture `director-panel.png` so it shows the new Pre-Race + Grid blocks.

- [ ] **Step 2: Regenerate the Companion board images** — invoke the **`companion-screenshots`** skill and recapture the affected `companion-page*.png` (the extended Page 1 and the new GRID page).

- [ ] **Step 3: Verify the images changed and are non-empty**

Run: `git status --porcelain src/docs/wiki/images/ && python3 tools/run-tests.py 2>&1 | tail -5`
Expected: the PNGs show as modified/added; the suite (incl. `test_wiki.py` link/anchor checks) PASSES.

- [ ] **Step 4: Commit**

```bash
git add src/docs/wiki/images/
git commit -m "docs(wiki): refresh Director Panel + Companion shots for new graphics"
```

---

### Task 5: Full-suite gate, lint, build-verify, and operator doc

**Files:**
- Modify: `README.md` and/or `src/docs/wiki/Sheet-Webhook.md` (or the relevant Assets/graphics operator page) — document the 12 new Assets-tab labels as an operator step (league supplies the PNGs).

**Interfaces:**
- Consumes: everything above.
- Produces: green CI-equivalent gates + operator documentation of the new sheet rows.

- [ ] **Step 1: Document the Assets rows** — add a short note to the operator docs listing the 12 canonical labels the league adds to the **Assets** tab (`Label | <Google-Drive PNG link>`), stressing the labels must byte-match, and that graphics not meant for the commentator console can tick the **Internal** checkbox. Find the existing Assets/graphics doc first:

Run: `grep -rln "Assets tab\|get-graphics\|Overlay.png\|Standings" src/docs README.md`

- [ ] **Step 2: Run the full suite**

Run: `python3 tools/run-tests.py`
Expected: PASS (includes `test_stint_graphics.py`, `test_director_panel.py`, `test_placeholders.py`, `test_build.py`, `test_wiki.py`).

- [ ] **Step 3: Lint**

Run: `python3 tools/lint.py`
Expected: no findings (add `--fix` only if it flags something auto-correctable).

- [ ] **Step 4: Build-verify**

Run: `python3 tools/build.py`
Expected: build + verify PASS (tokenization intact, no secrets, no shell scripts, the new `__RACECAST_GRAPHICS__/…` tokens resolve).

- [ ] **Step 5: Commit + open the PR**

```bash
git add README.md src/docs
git commit -m "docs: operator note for the 12 new Assets-tab graphics"
git push -u origin feat/stint-full-page-graphics
gh pr create --fill
```

Follow the repo's one-PR-per-change + squash-merge workflow (`ship-feature` skill) for CI + review.

---

## Self-Review

**Spec coverage:** OBS image-sources+scene-items → Task 1. Sheet-driven download (no code) → covered by Task 1 Step 5 (placeholder logic derives from collection) + Task 5 Step 1 (operator doc). Director Panel grouped blocks → Task 2. Companion Page-1-row-4 + GRID page → Task 3. Wiki screenshots → Task 4. Verification (tests/lint/build/visual) → Tasks 1–5. Name-drift guard → `tests/test_stint_graphics.py` across all three surfaces. No relay/setup/get-graphics change (spec "no edit needed") → honored. All spec sections map to a task.

**Placeholder scan:** No TBD/TODO. Every code step shows the exact content (test bodies, the JSON-mutation script, the HTML/JS insertions, the button spec table). Companion nanoid generation is explicitly delegated to the `companion-buttons` skill (which owns that mechanism) rather than left vague.

**Type/name consistency:** The 12 canonical labels are identical in the Global Constraints table, the OBS mutation script, `NEW_GRAPHICS` in the test, the panel `CONFIG.graphicsPreRace`/`graphicsGrid` `source:` strings, and the Companion table. UUIDs/ids match between the constraints table and the Task 1 script. Panel container ids (`gfxPreRaceBus`, `gfxGridTopBus`, `gfxGridBus`) match between the HTML insertion (Step 3) and the render loop (Step 5) and the test (Step 1). `toggleSource`, `mkKey`, `toggleKeys`, `_item` match the existing panel code verified at `director-panel.html:1042`.
