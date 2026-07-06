# Director-Panel Unified Mode-Aware Schedule Block — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the Director Panel's two schedule sections (`#urlsBox` race schedule + `#qualBox` qualifying) into one mode-aware "Schedule" block with a single visible mode chip, a single race↔qualifying switch, and a POV editor reachable in both modes.

**Architecture:** Front-end only (`src/director/director-panel.html`). One `<details id="urlsBox">` holds a race-only region (`#raceSched`), a qualifying-only region (`#qualSched`), and a shared POV row. `relayPoll` (already polling `/status`.`mode`) calls a new `applyMode(qualifying)` that toggles the two regions, the mode chip, and the switch label. A single `#modeSwitch` button calls the existing `/mode/race` | `/mode/qualifying` endpoints. No relay change — all endpoints already exist.

**Tech Stack:** Vanilla HTML/CSS/JS (no framework). Tests are stdlib string-assertion checks over the static HTML in `tests/test_director_panel.py` (run as a plain script). Visual verification via the `ui-visual-verification` and `wiki-screenshots` skills (demo profile + `tools/obs-sim.py`).

## Global Constraints

- Edit only under `src/` (and `tests/`). Never touch `dist/`/`runtime/`. (CLAUDE.md)
- English only in all code/docs/UI copy. (CLAUDE.md)
- Backward-compat matters — racecast is released (v1.1.0+). This change keeps both qualifying entry paths (`event start --qualifying` and the live in-panel switch) and all existing relay endpoints. (memory: no-prod-use-prefer-clean-breaks)
- POV is a separate, mode-independent feed (`/pov/*`) and MUST be editable in both race and qualifying mode. (spec; user note)
- Tests run on any machine / CI — no real IPs or machine paths. (CLAUDE.md)
- After any UI-surface change: render + eyeball in BOTH modes (`ui-visual-verification`), and regenerate the committed wiki image `director-panel.png` (`wiki-screenshots`) in the SAME change. (CLAUDE.md hard rule)
- Run `python3 tools/lint.py` after changing any Python file (only `tests/*.py` here).

**Reference spec:** `docs/superpowers/specs/2026-07-06-director-panel-unified-schedule-mode-design.md`

**Starting state:** the working tree already carries the interim CSS-cascade bugfix (`details.urls[hidden]{display:none}` at `src/director/director-panel.html:220-223` + test `t_urls_section_honors_hidden_rule`). This plan builds on it and keeps that CSS rule.

---

### Task 1: Merge into one mode-aware schedule block (markup + CSS + JS)

**Files:**
- Modify: `src/director/director-panel.html` (markup ~644-689; CSS ~229; JS: `relayPoll` ~1414-1420, `schedPoll`/toggle ~1987-2020, Qualifying JS ~2022-2092)
- Test: `tests/test_director_panel.py`

**Interfaces:**
- Consumes (existing, unchanged): `$(sel)` helper; `relayCall(path)`; `schedRow`, `rowBusy`, `fillSchedSelect`, `schedOptions`, `SAVE_GUARD_MS`; endpoints `/status`, `/schedule/data`, `/qualifying/data`, `/mode/race`, `/mode/qualifying`, `/pov/set`.
- Produces: `applyMode(qualifying: boolean)` (toggles `#raceSched`/`#qualSched`/`#modeChip`/`#modeSwitch`, sets module-level `relayMode`); DOM ids `#raceSched`, `#qualSched`, `#modeChip`, `#modeSwitch`. Removes ids `#qualBox`, `#qualOn`, `#qualOff`, `#qualModeBadge`.

- [ ] **Step 1: Create the feature branch**

We are on `main`; branch first (carries the uncommitted interim fix along). Run from the repo root.

```bash
git checkout -b fix/director-panel-unified-schedule-mode
```

- [ ] **Step 2: Write/replace the failing tests**

In `tests/test_director_panel.py`: (a) **replace** `t_mode_drives_section_visibility`, (b) **update** `t_setup_tab_order` to drop `id="qualBox"`, (c) **add** four new tests. Keep `t_urls_section_honors_hidden_rule` untouched.

Replace the existing `t_setup_tab_order` body's `_order(...)` call (currently lists `'id="urlsBox"', 'id="qualBox"',`) with:

```python
def t_setup_tab_order():
    # Scn.Vis -> Gfx -> Flag Gfx -> Timer -> Audio -> Transition -> Schedule
    # (merged: urlsBox) -> Pending -> Substitution, all after the SETUP panel.
    h = _html()
    _order(h, 'id="tabSetup"',
           'id="scnBus"', 'id="gfxBus"', 'id="flagGfxBus"', 'id="timerBus"',
           'id="audio"', 'id="txBar"', 'id="urlsBox"',
           'id="subsBox"', 'id="subSec"')
```

Replace the whole `t_mode_drives_section_visibility` function with:

```python
def t_mode_drives_section_visibility():
    # relayPoll delegates to applyMode(); applyMode toggles the two mode regions
    # and flips the single switch label. The two mode regions are mutually exclusive.
    h = _html()
    assert "applyMode(" in h, "relayPoll must delegate mode handling to applyMode"
    assert '$("#raceSched").hidden = qualifying' in h
    assert '$("#qualSched").hidden = !qualifying' in h
    assert "switch → QUALIFYING" in h   # race-mode target
    assert "switch → RACE" in h          # qualifying-mode target


def t_single_merged_schedule_section():
    # The old standalone Qualifying <details> is gone — one merged block.
    h = _html()
    assert 'id="qualBox"' not in h, "qualBox must be merged into the single #urlsBox block"
    assert h.count('id="urlsBox"') == 1


def t_mode_regions_and_switch_present():
    h = _html()
    assert 'id="raceSched"' in h    # race-only region
    assert 'id="qualSched"' in h    # qualifying-only region
    assert 'id="modeSwitch"' in h   # the single mode switch
    assert 'id="modeChip"' in h     # always-visible mode indicator


def t_pov_editor_shared_across_modes():
    # POV must work in BOTH modes → its editor sits AFTER both mode regions
    # (shared), never nested inside the race-only or qualifying-only region.
    h = _html()
    assert h.index('id="povUrl"') > h.index('id="schedBody"')   # after race region content
    assert h.index('id="povUrl"') > h.index('id="qualRow"')     # after qualifying region content


def t_old_mode_buttons_removed():
    h = _html()
    assert 'id="qualOn"' not in h
    assert 'id="qualOff"' not in h
    assert 'id="qualModeBadge"' not in h
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
python3 tests/test_director_panel.py
```
Expected: FAIL — first failing assertion in `t_single_merged_schedule_section` (`'id="qualBox"' not in h`) or `t_mode_regions_and_switch_present` (missing `id="raceSched"`), because the markup still has the old two-section structure.

- [ ] **Step 4: Add the mode-chip + switch CSS**

In `src/director/director-panel.html`, immediately after the line `details.urls[open] summary::after{content:"▾"}` (currently line 229), insert:

```css
  .urls .modechip{margin-left:6px;padding:2px 8px;border-radius:6px;font-size:10px;
    font-weight:700;letter-spacing:.14em;color:var(--amber);border:1px solid var(--amber)}
  .urls .modechip.qual{color:var(--blue);border-color:var(--blue)}
  .urls .modeswitch{padding:7px 12px;font-size:11px;letter-spacing:.12em;border-radius:8px;
    border:1px solid var(--edge);background:#141921;color:var(--muted);cursor:pointer}
  .urls .modeswitch:hover{border-color:var(--blue);color:var(--ink)}
```

- [ ] **Step 5: Replace the two `<details>` blocks with the single merged block**

Replace the entire markup span from `<details class="bus urls" id="urlsBox">` through the closing `</details>` of `#qualBox` (currently lines 644-689 — the two `<details>` blocks) with:

```html
  <details class="bus urls" id="urlsBox">
    <summary>Schedule <span class="modechip" id="modeChip">RACE</span></summary>
    <div class="body">
      <div style="margin-bottom:10px">
        <button class="modeswitch" id="modeSwitch" hidden>switch → QUALIFYING</button>
      </div>

      <!-- Race schedule (shown in race mode) -->
      <div id="raceSched">
        <table><tbody id="schedBody"></tbody></table>
        <button class="add" id="schedAdd">+ ADD ROW</button>
        <div class="hint">YouTube or Twitch — enter a full watch URL
          (<code>youtube.com/watch?v=…</code> or <code>twitch.tv/&lt;channel&gt;</code>).
          Saves write the Google Sheet only — a feed picks the new URL up
          on RELOAD A/B / NEXT (rows marked <b>A</b>/<b>B</b> are live now). Each row's
          <b>Streamer</b> and <b>Stint</b> label (Configuration vocab) become the HUD's
          STREAMER/STINT when that row goes on air. <b>CLEAR URL</b> removes only the
          stream link and keeps the Streamer + Stint slot. Streamer/Stint/URL can still
          be edited in the Sheet directly.</div>
      </div>

      <!-- Qualifying schedule (shown in qualifying mode) -->
      <div id="qualSched" hidden>
        <table><tbody>
          <tr id="qualRow">
            <td class="rn">Q<span class="livebadge" id="qualLive"></span></td>
            <td style="width:22%"><select class="nm" id="qualNm" title="Streamer (Configuration vocab)"></select></td>
            <td style="width:18%"><select class="st" id="qualSt" title="Stint label (Configuration vocab)"></select></td>
            <td><input class="u" id="qualUrl" placeholder="youtube.com/watch?v=… · twitch.tv/<channel> · UC…"></td>
            <td class="act"><button class="save" id="qualSave">SAVE</button><button class="clear" id="qualClear">CLEAR</button></td>
          </tr>
        </tbody></table>
        <div class="hint" id="qualInfo">Qualifying: one stream, served on <b>Feed A</b>.
          Edits write the <b>Qualifying</b> tab in the Sheet — the feed picks it up on
          RELOAD A / NEXT (or on the mode switch). On switch the HUD STREAMER/STINT follow
          this row.</div>
      </div>

      <!-- POV (shown in BOTH modes — POV is a separate, mode-independent feed) -->
      <table><tbody>
        <tr><td class="rn">POV</td>
            <td><input id="povName" maxlength="20" placeholder="name (max 20)"></td>
            <td><input id="povUrl" placeholder="youtube.com/watch?v=… · twitch.tv/<channel> · UC…"></td>
            <td class="act"><button class="save" id="povSave">SAVE</button></td></tr>
      </tbody></table>
      <div class="hint">POV — a full watch URL (<code>youtube.com/watch?v=…</code> or
        <code>twitch.tv/&lt;channel&gt;</code>). The POV URL applies on <b>POV RELOAD</b>.
        Available in both race and qualifying.</div>
    </div>
  </details>
```

- [ ] **Step 6: Update `relayPoll` to delegate to `applyMode`**

In `relayPoll` (currently lines 1416-1420), replace:

```js
    const qualifying = d.mode === "qualifying";
    // Show the schedule editor matching the active mode. The mode toggle,
    // submissions, and Parts control stay visible in both modes.
    if ($("#urlsBox")) $("#urlsBox").hidden = qualifying;
    if ($("#qualRow")) $("#qualRow").hidden = !qualifying;
```

with:

```js
    // One mode-aware schedule block: applyMode toggles the race/qualifying
    // regions + the mode chip + the switch label. POV stays visible in both.
    applyMode(d.mode === "qualifying");
```

- [ ] **Step 7: Rewrite the Qualifying JS section (applyMode + switch + qualPoll)**

Replace the block from `/* ---------- Qualifying (issue #124)... */` and `let qualAvailable = false;` (line 2022-2023) — specifically the `qualOn`/`qualOff` handlers (2059-2066), the `qualPoll` function (2067-2091), and the `$("#qualBox")` toggle listener (2092) — as follows.

First, add `applyMode` + the module-level `relayMode` right after `let qualAvailable = false;`:

```js
/* ---------- Mode (race / qualifying): one block, one switch ---------------
   relay.mode has one value with two setters (event start --qualifying, or the
   live switch here). applyMode() renders that single value; the switch calls
   /mode/*. POV is a separate feed and stays visible in both modes. */
let qualAvailable = false;
let relayMode = "race";
function applyMode(qualifying){
  relayMode = qualifying ? "qualifying" : "race";
  $("#raceSched").hidden = qualifying;
  $("#qualSched").hidden = !qualifying;
  $("#modeChip").textContent = qualifying ? "QUALIFYING" : "RACE";
  $("#modeChip").classList.toggle("qual", qualifying);
  $("#modeSwitch").textContent = qualifying ? "switch → RACE" : "switch → QUALIFYING";
}
```

Replace the `qualOn`/`qualOff` click handlers with the single switch handler:

```js
$("#modeSwitch").addEventListener("click", async ()=>{
  if (relayMode === "qualifying"){
    if (!confirm("Switch the relay back to RACE MODE? Feeds re-point to the race schedule (interrupts a running pull).")) return;
    await relayCall("mode/race");
  } else {
    if (!confirm("Switch the relay to QUALIFYING MODE? Feed A serves the Qualifying tab — this interrupts a running race pull (use between sessions).")) return;
    await relayCall("mode/qualifying");
  }
  qualPoll();
});
```

Replace `qualPoll` with (guard now keys on `#urlsBox`; sets `#modeSwitch` availability instead of the removed on/off buttons + badge):

```js
async function qualPoll(){
  if (!$("#urlsBox").open) return;   // closed section -> no traffic
  try{
    const r = await fetch("/qualifying/data", {cache:"no-store"});
    const d = await r.json();
    if (d.error) return;
    qualAvailable = !!d.available;
    $("#modeSwitch").hidden = !qualAvailable;   // race-only install: no switch
    ["qualNm","qualSt","qualUrl","qualSave","qualClear"].forEach(id=>$("#"+id).disabled = !qualAvailable);
    if (!qualAvailable){
      $("#qualInfo").textContent = "Qualifying tab not available (no 'Qualifying' tab in the sheet, or --no-qualifying / custom CSV URL).";
      return;
    }
    const row = (d.rows && d.rows[0]) || null;
    $("#qualLive").textContent = row && row.live ? row.live : "";
    const busy = qualRowBusy();
    fillSchedSelect($("#qualNm"), schedOptions.streamer, busy ? null : (row ? (row.name||"") : ""));
    fillSchedSelect($("#qualSt"), schedOptions.stint, busy ? null : (row ? (row.stint||"") : ""));
    if (row) $("#qualRow").dataset.sheetRow = row.sheetRow;
    if (!busy && row) $("#qualUrl").value = row.url || "";
  }catch(e){}
}
```

Delete the old `$("#qualBox").addEventListener("toggle", ()=>qualPoll());` line (it referenced the removed section).

- [ ] **Step 8: Make the section toggle poll both pollers**

Replace the schedPoll toggle listener (currently line 2020) `$("#urlsBox").addEventListener("toggle", ()=>schedPoll());` with:

```js
$("#urlsBox").addEventListener("toggle", ()=>{ schedPoll(); qualPoll(); });
```

Leave `schedPoll` otherwise unchanged — it keeps polling in both modes because its second half also refreshes the always-visible POV inputs (`#povUrl`/`#povName`); mode-gating it would freeze POV in qualifying.

- [ ] **Step 9: Verify no dangling references to removed ids**

```bash
grep -nE 'qualBox|qualOn|qualOff|qualModeBadge' src/director/director-panel.html
```
Expected: no output (all removed). If any line prints, fix it before continuing.

- [ ] **Step 10: Run the panel tests to verify they pass**

```bash
python3 tests/test_director_panel.py
```
Expected: `ALL PASS` (including the new tests and the retained `t_urls_section_honors_hidden_rule`).

- [ ] **Step 11: Lint the changed test file + run the full suite**

```bash
python3 tools/lint.py
python3 tools/run-tests.py
```
Expected: lint `All checks passed!`; suite passes (no other test references the removed ids — `t_setup_tab_order` was updated in Step 2).

- [ ] **Step 12: Commit**

```bash
git add src/director/director-panel.html tests/test_director_panel.py \
        docs/superpowers/specs/2026-07-06-director-panel-unified-schedule-mode-design.md \
        docs/superpowers/plans/2026-07-06-director-panel-unified-schedule-mode.md
git commit -m "$(cat <<'EOF'
feat(panel): unify race/qualifying into one mode-aware schedule block

Merge the standalone Qualifying section into the schedule block: one visible
mode chip + one race<->qualifying switch, race rows shown in race mode, the
single Q row in qualifying mode, and the POV editor shown in BOTH modes
(POV is a separate, mode-independent feed). Removes the duplicate schedule
editor that showed in race mode and makes the current mode obvious. Front-end
only — reuses /mode/*, /schedule/*, /qualifying/*, /pov/* unchanged.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Visual verification (both modes) + wiki screenshot

**Files:**
- Modify: `src/docs/wiki/images/director-panel.png` (regenerate)
- (Also updates the mirrored slide image if `wiki-screenshots` covers it — commit whatever it regenerates.)

**Interfaces:** none (verification + committed image only).

- [ ] **Step 1: Serve the demo build and look at BOTH modes**

Follow `ui-visual-verification`. Boot the demo relay + `tools/obs-sim.py` (demo profile, stub cookies) as in the `wiki-screenshots` skill Part B. Open `/panel`, go to the SETUP tab, and screenshot the merged Schedule block in **race mode** and in **qualifying mode** (switch via the panel button or `curl .../mode/qualifying`). Read each PNG back and check, deliberately:
  - Race mode: race rows + `+ ADD ROW` + POV row visible; chip reads `● RACE` (amber); switch reads `switch → QUALIFYING`; NO qualifying Q row.
  - Qualifying mode: the single Q row + POV row visible; chip reads `● QUALIFYING` (blue); switch reads `switch → RACE`; NO race rows / `+ ADD ROW`.
  - POV row present in BOTH.
  - Theme fit (uses `--edge`/`--ink`/`--blue`/`--amber`; no default white controls), alignment, spacing consistent with sibling sections.
Fix and re-shoot if anything is off.

- [ ] **Step 2: Record the UI-verification marker**

```bash
python3 .claude/hooks/record_ui_verified.py src/director/director-panel.html
```

- [ ] **Step 3: Regenerate the committed wiki screenshot**

Use the `wiki-screenshots` skill to regenerate `director-panel.png` (race-mode framing, matching the existing image). The race-mode appearance changed (standalone Qualifying box gone; header gained the mode chip + switch), so the committed image is stale.

- [ ] **Step 4: Tear down the demo build**

`relay stop`; `pkill -f obs-sim.py`; remove the stub `runtime/yt-cookies.txt`; `git checkout -- profiles/demo/profile.env` (reverts the auto-provisioned `CONSOLE_SECRET`). Delete any scratch PNGs from the repo root.

- [ ] **Step 5: Commit the regenerated image**

```bash
git add src/docs/wiki/images/director-panel.png
# plus any mirrored slide image wiki-screenshots regenerated
git commit -m "$(cat <<'EOF'
docs(wiki): refresh director-panel.png for the unified schedule block

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**1. Spec coverage:**
- One mode-aware block merging `#urlsBox`+`#qualBox` → Task 1 Step 5. ✓
- One mode chip + one switch (label flips, keeps confirm + `/mode/*`) → Steps 4, 5, 7. ✓
- Race region / qualifying region / POV shared in both modes → Step 5; tests Step 2. ✓
- POV pulled out of the mode-gated region (reachable in qualifying) → Step 5 markup + Step 8 note (schedPoll not mode-gated so POV keeps refreshing). ✓
- Availability: switch hidden when qualifying unavailable → Step 7 (`#modeSwitch.hidden = !qualAvailable`). ✓
- Retain `details.urls[hidden]{display:none}` CSS guard → untouched (Global Constraints / starting state). ✓
- Tests: replace `t_mode_drives_section_visibility`, update `t_setup_tab_order`, add POV-shared + single-section + buttons-removed, keep hidden-rule test → Step 2. ✓
- No relay change → confirmed (only `.html`/test edits). ✓
- Wiki screenshot regen + visual verify both modes → Task 2. ✓

**2. Placeholder scan:** No TBD/TODO/"handle edge cases" — every step has exact code/commands. ✓

**3. Type/name consistency:** `applyMode(qualifying)`, `relayMode`, ids `#raceSched`/`#qualSched`/`#modeChip`/`#modeSwitch` used identically in markup (Step 5), JS (Steps 6-8), and tests (Step 2). Removed ids `#qualBox`/`#qualOn`/`#qualOff`/`#qualModeBadge` asserted absent (Step 2, Step 9). Test strings (`'$("#raceSched").hidden = qualifying'`, `"switch → QUALIFYING"`) match the JS/markup verbatim. ✓
