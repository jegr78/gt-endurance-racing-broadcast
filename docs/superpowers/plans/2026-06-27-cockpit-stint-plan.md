# Cockpit Stint Plan (read-only) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a compact, read-only stint plan (stint label + streamer name) to the Commentator Cockpit's right column, directly below the Race Timer, highlighting the on-air stint and this commentator's own stints.

**Architecture:** A new pure helper `cockpit_schedule(rows, live_idx, me_key)` in the relay produces a redacted (no stream URL) per-row list with `on_air`/`mine` flags; it is added to the existing `/cockpit/data` payload (which already resolves `rows`/`live_idx`/`me`). The cockpit page renders it in a new scrollable card wired into the existing `pollTally()` loop.

**Tech Stack:** Python 3 stdlib (relay, `racecast-feeds.py`), plain HTML/CSS/JS (`cockpit.html`), stdlib unit tests (`tests/test_cockpit.py`, run as a plain script).

## Global Constraints

- Edit only under `src/` (plus `tests/` and `docs/`). Never touch `dist/`/`runtime/`.
- All scripts and docs English only.
- The cockpit is reachable over the public Funnel → the stint plan MUST carry **no stream URL** (same redaction boundary as `/console/takeover/status`).
- Front-end renders untrusted text via `textContent` only (XSS-safe), like the rest of the cockpit.
- Tests are stdlib-only, runnable as `python3 tests/test_cockpit.py`; test functions are named `t_*` and auto-run by the file's `__main__` footer.
- After a cockpit UI change, the cockpit wiki screenshot is stale and must be regenerated in the same change (CLAUDE.md hard rule) — see Task 4.

---

### Task 1: Pure `cockpit_schedule` helper + tests

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add function next to `race_control_schedule`, after line 2271)
- Test: `tests/test_cockpit.py` (add `t_*` functions after `t_race_control_schedule_empty`, line 223)

**Interfaces:**
- Consumes: `asset_key(name)` (already in `racecast-feeds.py`).
- Produces: `cockpit_schedule(rows, live_idx, me_key) -> list[dict]` where each dict is `{"stint": str, "streamer": str, "on_air": bool, "mine": bool}`, in schedule order, NO url key. Consumed by Task 2 (the `/cockpit/data` handler) and Task 3 (the front-end render).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cockpit.py` after line 223 (the `_rows()` helper at line 164 is reused):

```python
def t_cockpit_schedule_flags_on_air_and_mine():
    # me = "alpha-racing"; on-air feed is row 1 (Beta). Alpha's rows (0, 2) are
    # "mine"; only row 1 is on_air.
    sched = m.cockpit_schedule(_rows(), 1, "alpha-racing")
    assert sched == [
        {"stint": "S1", "streamer": "Alpha Racing", "on_air": False, "mine": True},
        {"stint": "S2", "streamer": "Beta", "on_air": True, "mine": False},
        {"stint": "S3", "streamer": "Alpha Racing", "on_air": False, "mine": True},
        {"stint": "S4", "streamer": "Gamma", "on_air": False, "mine": False}], sched


def t_cockpit_schedule_redacts_url():
    # Reachable over the Funnel -> never a stream URL (the takeover redaction line).
    sched = m.cockpit_schedule(_rows(), 0, "beta")
    for row in sched:
        assert "url" not in row, row
    assert "u0" not in json.dumps(sched) and "http" not in json.dumps(sched).lower()


def t_cockpit_schedule_live_idx_none():
    # No feed on air yet -> no row is on_air; mine flags still resolve.
    sched = m.cockpit_schedule(_rows(), None, "alpha-racing")
    assert all(r["on_air"] is False for r in sched)
    assert [r["mine"] for r in sched] == [True, False, True, False]


def t_cockpit_schedule_empty():
    assert m.cockpit_schedule([], 0, "anyone") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL with `AttributeError: module 'irofeeds' has no attribute 'cockpit_schedule'`.

- [ ] **Step 3: Write the minimal implementation**

In `src/relay/racecast-feeds.py`, insert after `race_control_schedule` (after line 2271, before `cockpit_display_name`):

```python
def cockpit_schedule(rows, live_idx, me_key):
    """Redacted stint plan for the cockpit's read-only stint-plan card (right
    column, below the timer). Per row: stint + streamer, plus an on_air flag
    (row == live_idx) and a mine flag (asset_key match for the token's streamer).
    NO stream URL — the cockpit is reachable over the public Funnel, so this stays
    inside the /console/takeover/status redaction boundary. rows are
    ScheduleSource 4-tuples (url, streamer, stint, line). Pure."""
    return [{"stint": st, "streamer": n,
             "on_air": i == live_idx,
             "mine": asset_key(n) == me_key}
            for i, (_u, n, st, _l) in enumerate(rows)]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_cockpit.py`
Expected: `ok t_cockpit_schedule_*` lines and `ALL PASS`.

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: no new findings.

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_cockpit.py
git commit -m "feat(cockpit): pure cockpit_schedule helper (redacted stint plan)"
```

---

### Task 2: Add `schedule` to the `/cockpit/data` payload

**Files:**
- Modify: `src/relay/racecast-feeds.py` (the `/cockpit/data` handler, the `tally.update({...})` call around lines 5093-5101)

**Interfaces:**
- Consumes: `cockpit_schedule` (Task 1); `rows`, `live_idx`, `me` already resolved in the handler (lines 5083-5085).
- Produces: `/cockpit/data` JSON now carries `"schedule": [...]` (the Task-1 shape). Consumed by Task 3.

- [ ] **Step 1: Add the field**

In `src/relay/racecast-feeds.py`, inside the `tally.update({...})` block at line 5093, add a `schedule` entry (place it next to `my_stints`):

```python
                        tally.update({"me": me, "mode": relay.mode,
                                      "program_available": _obs_ws is not None,
                                      # read-only event title for the talent header (#207)
                                      "event_title": event_store.get() if event_store else "",
                                      # own stints for the link-submission picker
                                      # (#193); empty -> the cockpit hides the form.
                                      "submit_enabled": submission_store is not None,
                                      "my_stints": cockpit_own_stints(rows, me),
                                      # read-only redacted stint plan for the
                                      # right-column card (no stream URLs).
                                      "schedule": cockpit_schedule(rows, live_idx, me),
                                      "my_pending": my_pending})
```

- [ ] **Step 2: Verify the existing suite still passes**

Run: `python3 tests/test_cockpit.py`
Expected: `ALL PASS` (no payload assertion exists for this field; this step guards against a typo/regression).

- [ ] **Step 3: Commit**

```bash
git add src/relay/racecast-feeds.py
git commit -m "feat(cockpit): expose redacted stint plan on /cockpit/data"
```

---

### Task 3: Cockpit front-end — stint-plan card + render

**Files:**
- Modify: `src/cockpit/cockpit.html` (CSS block ~line 58; right-column markup line 242-250; `pollTally` line 319-323; a new render function)

**Interfaces:**
- Consumes: `d.schedule` from `/cockpit/data` (Task 2): a list of `{stint, streamer, on_air, mine}`.
- Produces: no JS exports; a DOM card `#stintPlan`.

- [ ] **Step 1: Add the CSS**

In `src/cockpit/cockpit.html`, after the `#timer .t { ... }` rule (line 59), add:

```css
  /* Read-only stint plan (right column, below the timer). max-height shows
     ~3 stints; the rest scrolls. */
  #stintPlan { max-height: 110px; overflow-y: auto; }
  #stintPlan .row { display: flex; align-items: center; gap: 8px; padding: 6px 12px;
                    border-bottom: 1px solid #1c2027; font-size: 13px; }
  #stintPlan .row:last-child { border-bottom: 0; }
  #stintPlan .row.mine { border-left: 3px solid #8ab4f8; padding-left: 9px; }
  #stintPlan .row.onair { background: #2a0d10; }
  #stintPlan .st { font-weight: 700; opacity: .85; min-width: 0; }
  #stintPlan .nm { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  #stintPlan .live { font-weight: 700; font-size: 10px; padding: 1px 6px; border-radius: 999px;
                     background: #c1121f; color: #fff; letter-spacing: .04em; }
  #stintPlan .empty { padding: 10px 12px; opacity: .6; font-size: 13px; }
```

- [ ] **Step 2: Add the card markup**

In `src/cockpit/cockpit.html`, between the Race-timer card (line 243) and the Graphics card (line 244), insert:

```html
    <div class="card" style="margin-top:12px;"><h2>Stint plan</h2>
      <div id="stintPlan"><div class="empty">Loading…</div></div></div>
```

- [ ] **Step 3: Add the render function**

In `src/cockpit/cockpit.html`, after the `pollTally` function (after line 323), add:

```javascript
// --- Read-only stint plan (right column) ---
function renderStintPlan(d) {
  const box = $('stintPlan');
  const rows = d.schedule || [];
  box.textContent = '';
  if (!rows.length) {
    const e = document.createElement('div');
    e.className = 'empty'; e.textContent = 'No stints scheduled yet.';
    box.appendChild(e); return;
  }
  let onAirEl = null;
  for (const s of rows) {
    const row = document.createElement('div');
    row.className = 'row' + (s.on_air ? ' onair' : '') + (s.mine ? ' mine' : '');
    const st = document.createElement('span');
    st.className = 'st'; st.textContent = s.stint || '';      // XSS-safe
    const nm = document.createElement('span');
    nm.className = 'nm'; nm.textContent = s.streamer || '';   // XSS-safe
    row.appendChild(st); row.appendChild(nm);
    if (s.on_air) {
      const tag = document.createElement('span');
      tag.className = 'live'; tag.textContent = 'ON AIR';
      row.appendChild(tag);
      onAirEl = row;
    }
    box.appendChild(row);
  }
  if (onAirEl) onAirEl.scrollIntoView({ block: 'nearest' });
}
```

- [ ] **Step 4: Wire it into the poll loop**

In `src/cockpit/cockpit.html`, change the `pollTally` body (line 320) to also call `renderStintPlan`:

```javascript
async function pollTally() {
  try { const d = await j('/cockpit/data'); renderTally(d); renderSubmit(d); renderStintPlan(d); }
  catch (e) { /* transient */ }
  setTimeout(pollTally, 2000);
}
```

- [ ] **Step 5: Verify the page-token-strip test still passes**

Run: `python3 tests/test_cockpit.py`
Expected: `ALL PASS` (the page still contains `history.replaceState` / `location.pathname`).

- [ ] **Step 6: Manual smoke via the local UAT build**

Use the `racecast-local-uat` skill to stand up a real-league dev build, open `/console/cockpit?t=<token>` for a scheduled streamer, and confirm: the stint-plan card shows under the timer, ~3 rows visible then scrolls, the on-air row shows the `ON AIR` pill and is auto-scrolled into view, and the streamer's own rows carry the blue left accent. (If a live build is impractical in this session, note it and rely on the e2e/Playwright check in Task 4.)

- [ ] **Step 7: Commit**

```bash
git add src/cockpit/cockpit.html
git commit -m "feat(cockpit): read-only stint-plan card below the race timer"
```

---

### Task 4: Docs + wiki screenshot

**Files:**
- Modify: `CLAUDE.md` (the cockpit paragraph describing `/cockpit/*`)
- Modify (regenerate): `src/docs/wiki/images/<cockpit screenshot>.png` (+ any slide mirror under `src/docs/slides/assets/img/`) via the `wiki-screenshots` skill

**Interfaces:**
- Consumes: the shipped behavior from Tasks 1-3.
- Produces: updated operator docs + a current cockpit screenshot.

- [ ] **Step 1: Update CLAUDE.md**

In the cockpit paragraph (the "talent-facing Commentator Cockpit (issue #191)" section), add a sentence noting the new surface, e.g. after the tally description:

```
A read-only **stint plan** (right column, below the timer) lists the full running
order (stint label + streamer name) from a redacted `schedule` field on
`/cockpit/data` — no stream URLs (the same Funnel redaction boundary as
`/console/takeover/status`); the on-air stint and the viewer's own stints are
highlighted (pure `cockpit_schedule`).
```

- [ ] **Step 2: Regenerate the cockpit wiki screenshot**

Invoke the `wiki-screenshots` skill and follow its reproducible recipe (demo profile + `tools/obs-sim.py`) to recapture the cockpit page image under `src/docs/wiki/images/` (and the slide mirror if one exists). Confirm the demo profile's committed `profile.env` is reverted afterward (the demo relay mutates `CONSOLE_SECRET` — see the memory note).

- [ ] **Step 3: Run the full suite + lint**

Run: `python3 tools/run-tests.py && python3 tools/lint.py`
Expected: all tests pass, no lint findings.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md src/docs/wiki/images src/docs/slides/assets/img
git commit -m "docs(cockpit): document + screenshot the read-only stint plan"
```

---

## Self-Review

**Spec coverage:**
- Pure redacted helper, no URLs → Task 1. ✓
- `/cockpit/data` field → Task 2. ✓
- Right-column card below timer, ~3 stints / scroll, on-air + mine highlight, auto-scroll, empty state → Task 3. ✓
- Tests (on_air/mine flags, no URL, empty, live_idx None covers a qualifying-style/no-air case) → Task 1. ✓
- CLAUDE.md + wiki screenshot → Task 4. ✓

**Placeholder scan:** No TBD/TODO; all code shown in full. Task 3 Step 6 is a real manual smoke with a fallback note, not a placeholder.

**Type consistency:** `cockpit_schedule(rows, live_idx, me_key)` returns `{stint, streamer, on_air, mine}` consistently across Tasks 1-3; the front-end reads exactly those keys. Test module handle is `m` (= `_load("irofeeds", ...)`), `json` already imported in `test_cockpit.py`.
