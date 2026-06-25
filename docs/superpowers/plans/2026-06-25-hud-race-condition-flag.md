# HUD Race-Condition Flag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated, color-coded race-condition **flag** element to the HUD (Green/Yellow/Safety Car/FCY/Red/…), hidden unless activated, controllable from the Google Sheet, the Director Panel, and Web/Companion buttons.

**Architecture:** A new Setup field `flag` mirrors the Race Control plumbing 1:1 (Overlay-tab row + Configuration-tab vocab column → `SETUP_FIELDS` → `/setup/set|clear/flag` → optimistic override + Sheet webhook → `/hud/data` `d.flag`). The HUD renders it in a separate `#flag-status` slot whose `data-state="<slug>"` attribute drives per-state default colors. It diverges from Race Control in exactly two ways: `flag` is clearable to empty, and it is NOT auto-cleared on stint handover.

**Tech Stack:** Pure Python 3 stdlib (relay), vanilla JS (HUD + panel), Companion config JSON, stdlib runnable test scripts (no pytest).

## Global Constraints

- **Edit only under `src/`** (plus `tests/` and `docs/`). Never hand-edit `dist/`/`runtime/`.
- **English only** in code, comments, docs.
- **No new dependencies.**
- **Naming:** url/vocab/overlay key + HUD data key = `flag`; Sheet header (Configuration column + Overlay row label) = `Flag`; HUD slot id = `flag-status` (NOT `flag` — avoids confusion with the country flag `#round-flag` / `d.round.flagKey`); color attribute = `data-state="<slug>"`.
- **flagSlug** = lowercase, non-alphanumeric runs → `-`, trimmed; then resolved through `FLAG_ALIASES = {sc:"safety-car", fcy:"full-course-yellow", vsc:"full-course-yellow"}`.
- **Canonical colored slugs:** `green-flag, yellow-flag, double-yellow, safety-car, full-course-yellow, code-60, red-flag, checkered-flag`. Unknown → neutral default.
- **Divergences from Race Control:** `flag` is empty-clearable; `flag` is NOT cleared on `/next` handover (it must persist).
- **No new public/Funnel surface** — the flag uses the existing tailnet `/setup/*` chain.
- Tests are runnable scripts: `python3 tests/test_<name>.py` (prints `ALL PASS`). Full suite: `python3 tools/run-tests.py`; lint: `python3 tools/lint.py` (run after any Python change).
- Visible Control-Center/Panel/Companion changes require refreshing the matching `src/docs/wiki/images/*.png` (+ slides copies) in the same change.
- After shipping, `python3 tools/build.py` must pass its verify step.

---

### Task 1: Relay — `flag` Setup field (data layer + endpoints)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`OVERLAY_LABELS` ~781; `VOCAB_COLUMNS` ~915; `build_hud_data` ~989; `HudSource.EMPTY` ~2788; `SETUP_FIELDS` ~2944; `set_field` empty-gate ~2996)
- Test: `tests/test_hud.py`, `tests/test_setup.py`

**Interfaces:**
- Produces: `/hud/data` carries `d.flag` (string, "" when unset). `/setup/set/flag/<value>` and `/setup/clear/flag` work; `/setup/data` exposes `fields.flag` + `options.flag`. Roster/overlay keys all use `flag`. Consumed by Task 2 (HUD), Task 3 (panel), Task 4 (companion).

- [ ] **Step 1: Write the failing tests**

In `tests/test_hud.py`, add (after the existing race-control overlay/vocab tests):

```python
FLAG_OVERLAY_CSV = (",Flag,Safety Car,,,,,,,\n")
def t_parse_overlay_flag():
    assert m.parse_overlay(FLAG_OVERLAY_CSV)["flag"] == "Safety Car"

def t_build_hud_data_flag():
    d = m.build_hud_data(m.parse_overlay(FLAG_OVERLAY_CSV), {})
    assert d["flag"] == "Safety Car"

def t_build_hud_data_flag_default_empty():
    d = m.build_hud_data(m.parse_overlay(",Stint,X,,,,,,,\n"), {})
    assert d["flag"] == ""

FLAG_CONFIG_CSV = ("Stints,Flag,Race Control\n"
                   "Stint 1,Yellow Flag,Formation Lap\n"
                   "Stint 2,Safety Car,Final Lap\n")
def t_parse_config_vocab_flag():
    assert m.parse_config_vocab(FLAG_CONFIG_CSV)["flag"] == ["Yellow Flag", "Safety Car"]

def t_hudsource_empty_has_flag():
    assert m.HudSource.EMPTY["flag"] == ""
```

In `tests/test_setup.py`, change the shared `CONFIG_CSV` (~63) to add a `Flag` column with values, and add flag tests. Replace the `CONFIG_CSV` block with:

```python
CONFIG_CSV = ("Stints,Streamers,Session,Race Control,Flag,Teams,Brand Name\n"
              "Stint 1,JeGr,Qualifier,Formation Lap,Yellow Flag,T #1,Porsche\n"
              "Stint 2,GT45,Race,Final Lap,Safety Car,T #2,BMW\n")
```

Add these tests (after `t_clear_racecontrol_allowed`):

```python
def t_clear_flag_allowed():
    pushes = []
    ctl, hs, orig = _ctl(pushes)
    try:
        r = ctl.set_field("flag", "", now=1000.0)
        assert r.get("ok")
        ctl._push_setup("Flag", "")
        assert pushes[-1]["fields"] == {"Flag": ""}
    finally:
        m.post_webhook = orig

def t_set_flag_validates_against_vocab():
    pushes = []
    ctl, hs, orig = _ctl(pushes)
    try:
        assert ctl.set_field("flag", "Safety Car", now=1000.0).get("ok")
        assert hs.data(now=1001.0)["flag"] == "Safety Car"      # optimistic echo
        assert "error" in ctl.set_field("flag", "Not A Flag")   # not in vocab
    finally:
        m.post_webhook = orig
```

Update `t_setup_data_shape` (~395) to assert the new field/options:

```python
    assert d["fields"]["flag"] == ""
    assert d["options"]["flag"] == ["Yellow Flag", "Safety Car"]
```

Add a flag-survives-handover test (after `t_next_handover_keeps_racecontrol_without_cut`, ~545):

```python
def t_next_handover_keeps_flag_on_cut():
    # A track condition (flag) outlives a commentator handover -> NOT cleared on cut.
    pushes = []
    ctl, hs, orig = _ctl(pushes)
    srv, get, post = _client(ctl, next_result={"obs_cut": True})
    try:
        assert get("/setup/set/flag/Safety%20Car").get("ok")
        assert hs.data()["flag"] == "Safety Car"
        get("/next")
        assert hs.data()["flag"] == "Safety Car"   # still set after the cut
    finally:
        srv.shutdown(); m.post_webhook = orig
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_hud.py` and `python3 tests/test_setup.py`
Expected: FAIL — `flag` missing from overlay/vocab/EMPTY/SETUP_FIELDS/options; `set_field("flag", …)` returns an unknown-field error.

- [ ] **Step 3: Implement the relay changes**

In `src/relay/racecast-feeds.py`:

`OVERLAY_LABELS` (~781) — add the `Flag` row mapping:
```python
OVERLAY_LABELS = {
    "stint": "stint", "streamer": "streamer", "session": "session",
    "round top": "round_top", "round bottom": "country",
    "race control": "race_control", "flag": "flag",
}
```

`VOCAB_COLUMNS` (~915) — add the `Flag` column:
```python
VOCAB_COLUMNS = {"stint": "stints", "streamer": "streamers",
                 "session": "session", "racecontrol": "race control",
                 "flag": "flag"}
```

`build_hud_data` (~989) — add `flag` after `raceControl`:
```python
        "raceControl": overlay.get("race_control", ""),
        "flag": overlay.get("flag", ""),
    }
```

`HudSource.EMPTY` (~2788) — add `flag`:
```python
             "raceControl": "", "flag": ""}
```

`SETUP_FIELDS` (~2944) — add the `flag` field:
```python
SETUP_FIELDS = {
    "stint": ("Stint", "stint"),
    "streamer": ("Streamer", "streamer"),
    "session": ("Session", "session"),
    "racecontrol": ("Race Control", "raceControl"),
    "flag": ("Flag", "flag"),
}
```

`set_field` empty-gate (~2996) — allow `flag` empty too:
```python
        if not value and key not in ("racecontrol", "flag"):
            return {"error": "empty value only allowed for racecontrol/flag"}
```

Do NOT touch the `/next` handover block — the flag intentionally stays out of the cut-clear path so it persists.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_hud.py` and `python3 tests/test_setup.py`
Expected: both `ALL PASS`.

- [ ] **Step 5: Update the now-stale comment + lint + commit**

In `tests/test_setup.py`, the `t_set_field_unknown_field_and_value` comment "only racecontrol clears" is now stale — change it to `# racecontrol/flag may clear; others can't`.

```bash
python3 tools/lint.py
git add src/relay/racecast-feeds.py tests/test_hud.py tests/test_setup.py
git commit -m "feat(hud): flag Setup field (Sheet/panel/webhook), persists across handover"
```

---

### Task 2: HUD — `#flag-status` element + color-coding

**Files:**
- Modify: `src/obs/hud.html` (CSS after `#race-control` ~93; slot after `#race-control` div ~119; `tick()` ~210 + a `setFlag`/`flagSlug` helper near `setText` ~156)
- Test: `tests/test_overlay.py` (`t_ob_extract_slots_from_real_hud`)

**Interfaces:**
- Consumes: `d.flag` from Task 1.
- Produces: a new builder slot `flag-status` (text kind), auto-extracted by `extract_slots`.

- [ ] **Step 1: Write the failing test**

In `tests/test_overlay.py`, update `t_ob_extract_slots_from_real_hud`'s `ids ==` list to include `"flag-status"` immediately after `"race-control"`:

```python
                   "race-control", "flag-status", "pov", "pov-name", "clock"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_overlay.py`
Expected: FAIL — `t_ob_extract_slots_from_real_hud` (ids mismatch: `flag-status` missing).

- [ ] **Step 3: Add the slot, CSS, and JS**

In `src/obs/hud.html`, add the slot markup immediately after the `#race-control` div (~119):

```html
  <div id="flag-status" class="el" data-edit="Flag status" data-edit-kind="text"></div>
```

Add CSS after the `#race-control { … }` rule (~93) — a neutral default badge plus per-state colors:

```css
  /* Race-condition flag (Yellow / Safety Car / FCY / …). Hidden when empty;
     color-coded per state via data-state. Builder-positionable. */
  #flag-status { left: 264px; top: 800px; width: 360px; height: 50px;
    font-size: 28px; font-weight: 700; background: #243039; padding: 10px;
    border-radius: 8px; color: #eef0f2; }
  #flag-status[data-state="green-flag"] { background: #1f8a3b; color: #fff; }
  #flag-status[data-state="yellow-flag"] { background: #f2c014; color: #111; }
  #flag-status[data-state="double-yellow"] { background: #f2c014; color: #111; }
  #flag-status[data-state="full-course-yellow"] { background: #e6a700; color: #111; }
  #flag-status[data-state="code-60"] { background: #e2761b; color: #111; }
  #flag-status[data-state="safety-car"] { background: #eef0f2; color: #111; }
  #flag-status[data-state="red-flag"] { background: #c62121; color: #fff; }
  #flag-status[data-state="checkered-flag"] { background: #111; color: #fff; }
```

Add the `flagSlug` helper + `FLAG_ALIASES` and a `setFlag` near `setText` (~156):

```javascript
  const FLAG_ALIASES = {
    "sc": "safety-car", "fcy": "full-course-yellow", "vsc": "full-course-yellow",
  };
  function flagSlug(value) {
    const s = (value || "").toLowerCase().replace(/[^a-z0-9]+/g, "-")
                .replace(/^-+|-+$/g, "");
    return FLAG_ALIASES[s] || s;
  }
  function setFlag(id, value) {
    const el = document.getElementById(id);
    el.textContent = value || "";
    el.classList.toggle("empty", !value);
    if (value) el.dataset.state = flagSlug(value);
    else el.removeAttribute("data-state");
  }
```

In `tick()`, after the `setText("race-control", d.raceControl);` line (~210), add:

```javascript
      setFlag("flag-status", d.flag);
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_overlay.py`
Expected: `ALL PASS` (the new slot has only base CSS; the demo layout is untouched, so `t_shipped_demo_overlay_css_matches_its_layout` stays green).

- [ ] **Step 5: Lint (no Python changed, but run the suite) + commit**

```bash
python3 tools/run-tests.py
git add src/obs/hud.html tests/test_overlay.py
git commit -m "feat(hud): color-coded #flag-status element (data-state slug + aliases)"
```
Expected: suite `ALL TEST FILES PASS`. (The `flagSlug`/color rendering is verified live by the controller during review.)

---

### Task 3: Director Panel — FLAG dropdown

**Files:**
- Modify: `src/director/director-panel.html` (`SETUP_FIELDS` array ~1154; `setupPoll` option builder ~1334)
- Test: manual (browser); no JS unit harness — covered by the full suite + the Task 5 screenshot.

**Interfaces:**
- Consumes: `/setup/data` `options.flag` + `fields.flag` from Task 1.

- [ ] **Step 1: Add the field to the panel array**

In `src/director/director-panel.html`, extend `SETUP_FIELDS` (~1154):

```javascript
const SETUP_FIELDS = [
  ["stint","STINT LABEL"], ["streamer","STREAMER"],
  ["session","SESSION"], ["racecontrol","RACE CONTROL"], ["flag","FLAG"],
];
```

- [ ] **Step 2: Include the empty (clear) option for flag**

In `setupPoll` (~1334), change the option builder so `flag` (like `racecontrol`) gets the leading empty option:

```javascript
    const opts = (["racecontrol","flag"].includes(key) ? [""] : []).concat(d.options[key] || []);
```

- [ ] **Step 3: Verify the suite + lint**

```bash
python3 tools/run-tests.py
python3 tools/lint.py
```
Expected: `ALL TEST FILES PASS`; lint clean. (No Python changed; this confirms nothing else broke.)

- [ ] **Step 4: Commit**

```bash
git add src/director/director-panel.html
git commit -m "feat(panel): FLAG dropdown (set + clear) in the Director Panel"
```

---

### Task 4: Companion / Web buttons — a FLAGS page

**Files:**
- Modify: `src/companion/racecast-buttons.companionconfig` (add a Page 3 with flag buttons)
- Test: validate the JSON parses + the board renders (`companion-screenshots` skill, Task 5)

**Interfaces:**
- Consumes: the `/setup/set/flag/<state>` + `/setup/clear/flag` endpoints from Task 1.
- The Generic-HTTP connection id in this config is **`BB0jmLMxj_0YwbhwslOiw`** (`definitionId: "get"`); the existing `setup/set/racecontrol` button (page 1, control `0/7` "RED FLAG") is the exact action template to mirror.

- [ ] **Step 1: Read the template and add a Page 3 of flag buttons**

The committed config has `pages: {"1": …, "2": …}`. Add a `"3"` page named `"FLAGS"` with one row (`"0"`) of buttons, each a `type:"button"` whose `steps."0".action_sets.down` is a single Generic-HTTP `get` action (mirror control `0/7` on page 1, but with `feedbacks: []` and no scene-toggle action — just the GET). Use the connection id `BB0jmLMxj_0YwbhwslOiw`. Give every action and feedback a fresh unique id string (21-char nanoid-style; any unique value works — must not collide with existing ids in the file).

Buttons (col → text → url):
- `0` → `FLAG\nGREEN` → `http://127.0.0.1:8088/setup/set/flag/Green%20Flag`
- `1` → `FLAG\nYELLOW` → `http://127.0.0.1:8088/setup/set/flag/Yellow%20Flag`
- `2` → `SAFETY\nCAR` → `http://127.0.0.1:8088/setup/set/flag/Safety%20Car`
- `3` → `FCY` → `http://127.0.0.1:8088/setup/set/flag/Full%20Course%20Yellow`
- `4` → `RED\nFLAG` → `http://127.0.0.1:8088/setup/set/flag/Red%20Flag`
- `5` → `CLEAR\nFLAG` → `http://127.0.0.1:8088/setup/clear/flag`

Each button object (fill `<UNIQUE_ID>` per button, distinct each time):
```json
{
  "type": "button",
  "style": {"text": "<TEXT>", "textExpression": false, "size": "14", "png64": null,
            "alignment": "center:center", "pngalignment": "center:center",
            "color": 16777215, "bgcolor": 0, "show_topbar": "default"},
  "options": {"stepProgression": "auto", "stepExpression": "", "rotaryActions": false},
  "feedbacks": [],
  "steps": {"0": {"action_sets": {"down": [
    {"id": "<UNIQUE_ID>", "definitionId": "get", "connectionId": "BB0jmLMxj_0YwbhwslOiw",
     "options": {"url": {"value": "<URL>", "isExpression": false},
                 "header": {"isExpression": false, "value": ""},
                 "jsonResultDataVariable": {"isExpression": false},
                 "result_stringify": {"isExpression": false, "value": true},
                 "statusCodeVariable": {"isExpression": false}},
     "upgradeIndex": 1, "type": "action"}], "up": []},
    "options": {"runWhileHeld": []}}}
}
```

The Page 3 skeleton (match the structure of pages "1"/"2" — read one to copy the page-level keys like `name`, `controls`, and any `gridSize`/meta the existing pages carry; reuse those values):
```json
"3": { "name": "FLAGS", "controls": { "0": { "0": <btn>, "1": <btn>, "2": <btn>, "3": <btn>, "4": <btn>, "5": <btn> } } }
```
Match whatever page-level fields pages "1"/"2" include (copy their non-`controls` keys verbatim into page "3" so the schema is identical).

- [ ] **Step 2: Validate the JSON parses and ids are unique**

Run:
```bash
python3 -c "import json; d=json.load(open('src/companion/racecast-buttons.companionconfig')); \
print('pages', list(d['pages'])); \
ids=__import__('re').findall(r'\"id\": \"([^\"]+)\"', open('src/companion/racecast-buttons.companionconfig').read()); \
print('flag urls', json.dumps(d).count('setup/set/flag'), '+clear', json.dumps(d).count('setup/clear/flag')); \
assert len(ids)==len(set(ids)), 'DUPLICATE ids'; print('ids unique:', len(ids))"
```
Expected: `pages ['1', '2', '3']`, `flag urls 5 +clear 1`, `ids unique: …` (no DUPLICATE assertion).

- [ ] **Step 3: Defensive password re-strip + commit**

```bash
python3 tools/strip_companion_pass.py src/companion/racecast-buttons.companionconfig || true
python3 tools/run-tests.py
git add src/companion/racecast-buttons.companionconfig
git commit -m "feat(companion): FLAGS button page (set Green/Yellow/SC/FCY/Red + clear)"
```
Expected: suite `ALL TEST FILES PASS` (incl. any companion-config test). If `strip_companion_pass.py` needs different args, check its `--help`; the goal is only to ensure no WebSocket password leaked in (the page added has none, so this is defensive).

---

### Task 5: Docs — Sheet column + refreshed screenshots

**Files:**
- Modify: a Sheet wiki page (`src/docs/wiki/Sheet-Template.md` — the Configuration-tab column table)
- Regenerate: `src/docs/wiki/images/director-panel.png`, the Companion board `companion-page3-*.png` (new) / existing `companion-page*.png`, and `src/docs/wiki/images/cc-overlay-builder.png` (new `flag-status` slot) — plus the slides copies where they exist.
- Test: `python3 tests/test_wiki.py`

- [ ] **Step 1: Document the Configuration `Flag` column**

In `src/docs/wiki/Sheet-Template.md`, add a row to the Configuration-tab column table (after the `Race Control` row):

```markdown
| `Flag` | optional | Dropdown options for the panel/Companion **race-condition flag** (Green/Yellow/Safety Car/Full Course Yellow/Red/…). Shown color-coded in the HUD; hidden when unset. Distinct from the country flag (which derives from `Round Bottom`/Country). |
```

Also add a one-line note that the canonical states (Green Flag, Yellow Flag, Double Yellow, Safety Car, Full Course Yellow, Code 60, Red Flag, Checkered Flag) ship default colors; `FCY`/`VSC`/`SC` abbreviations map to those; other values render neutral and can be styled per-league.

- [ ] **Step 2: Refresh the Director Panel screenshot**

Use the `wiki-screenshots` skill (demo profile + `tools/obs-sim.py` per its recipe) to recapture `/panel` (or `/console/panel`) showing the new **FLAG** dropdown → overwrite `src/docs/wiki/images/director-panel.png` (+ slides copy if present). Revert `profiles/demo/profile.env` after (the relay start writes `CONSOLE_SECRET`).

- [ ] **Step 3: Refresh the Companion board + overlay-builder screenshots**

- Companion: use the `companion-screenshots` skill to capture the new **FLAGS** page → `src/docs/wiki/images/companion-page3-*.png` (match the existing naming convention for page shots).
- Overlay builder: use `wiki-screenshots` (dev build, demo profile) to recapture `#ov-modal .ovmodal-card` (now lists a `Flag status` slot) → `src/docs/wiki/images/cc-overlay-builder.png` (+ slides copy).

- [ ] **Step 4: Validate wiki + commit**

```bash
python3 tests/test_wiki.py
git checkout -- profiles/demo/profile.env   # if a relay was started
git add src/docs/wiki/Sheet-Template.md src/docs/wiki/images/ src/docs/slides/assets/img/
git commit -m "docs(wiki): Flag Configuration column + refreshed panel/companion/builder screenshots"
```
Expected: `test_wiki.py` → `ALL PASS`; `git status --porcelain profiles/demo/profile.env` clean before commit.

---

### Task 6: Final verification

- [ ] **Step 1: Full suite** — `python3 tools/run-tests.py` → `ALL TEST FILES PASS`.
- [ ] **Step 2: Lint** — `python3 tools/lint.py` → no findings.
- [ ] **Step 3: Build verify** — `python3 tools/build.py` → exit 0, verify OK (companion password empty, OBS tokenized, demo profile secret-free).
- [ ] **Step 4: Clean tree** — `git status` clean; `git log --oneline main..HEAD` shows the feature/docs commits on `feat/hud-race-condition-flag`.

---

## Self-Review notes

- **Spec coverage:** relay field + endpoints + persist-on-handover (Task 1); HUD element + color-coding + aliases (Task 2); panel dropdown (Task 3); Companion/Web buttons (Task 4); Sheet doc + screenshots (Task 5); verification (Task 6). All spec "Files touched" covered.
- **Type/name consistency:** `flag` is the key across `OVERLAY_LABELS`, `VOCAB_COLUMNS`, `SETUP_FIELDS`, `build_hud_data`, `HudSource.EMPTY`, `/hud/data` `d.flag`, and the panel array; HUD slot id is `flag-status` everywhere (markup, extraction test, `setFlag` call); `data-state` slug + `FLAG_ALIASES` consistent between spec and Task 2.
- **No placeholders:** every code step shows the exact edit; the one templated artifact (Companion buttons) names the exact connection id, template control, field values, and a parse+unique-id validation gate.
- **Edge cases:** empty/clear allowed for flag (tested); not-in-vocab rejected (tested); flag persists across handover (tested, the divergence from Race Control); unknown slug → neutral default; demo sync guard untouched.
