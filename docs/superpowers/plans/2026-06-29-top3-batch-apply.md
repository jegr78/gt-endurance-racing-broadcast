# Top-3 Teams Batch Apply — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Director Panel's Top-3 team controls staged-by-default — set P1/P2/P3, then one "Apply Top 3" commits all three atomically (one relay request) and writes them back to the Sheet — with a per-row Batch toggle (default ON) that can be switched OFF to restore today's live per-dropdown behavior.

**Architecture:** A new relay endpoint `POST /setup/teams` sets all three `HudSource` team-overrides under a single lock acquisition (so `/hud/data` never renders a partial/duplicated standing), then writes each slot back to the Sheet via the existing single-slot `teams` webhook action (no Apps Script change). The Director Panel stages dropdown changes locally in batch mode and submits them through the new endpoint; the existing `GET /setup/team/<slot>/<value>` live path is unchanged.

**Tech Stack:** Pure Python stdlib relay (`src/relay/racecast-feeds.py`), stdlib HTTP test harness (`tests/test_setup.py`, runnable script — no pytest), vanilla JS/HTML panel (`src/director/director-panel.html`).

## Global Constraints

- **Edit only under `src/`** (and `tests/`, `docs/`). Never hand-edit `dist/`/`runtime/`.
- **English only** in all scripts and docs.
- **Never hardcode secrets or machine paths.** No real IPs/paths in tests.
- The relay is deliberately dependency-light and is **exempt** from the `http_util` UA guard — it keeps using its own `post_webhook`. Do not import shared modules into it.
- **racecast is released (v1.1.0+): keep the live single-slot path (`GET /setup/team/...`) backward compatible.** The batch path is additive.
- **No Apps Script / webhook protocol change** — reuse the existing single-slot `teams` action.
- After relay changes run `python3 tests/test_setup.py`; before finishing run `python3 tools/run-tests.py` and `python3 tools/lint.py`.
- **Director Panel is a UI surface: regenerate `src/docs/wiki/images/director-panel.png` in the SAME change** via the `wiki-screenshots` skill.

---

### Task 1: Relay backend — atomic batch team apply

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add `HudSource.set_teams_override`; add `SetupControl.set_teams` + `SetupControl._push_teams`; add `POST /setup/teams` routing in `do_POST`)
- Test: `tests/test_setup.py` (new `t_*` functions; reuses the existing `_team_ctl` and `_client` helpers)

**Interfaces:**
- Consumes (existing, unchanged): `HudSource.resolve_team(label) -> dict`, `HudSource.full_team_name(name) -> str`, `HudSource.roster_names() -> list[str]`, `HudSource.team_pending(now=None) -> set[int]`, `HudSource.refresh()`, `SetupControl._push(payload, expected_action) -> (ok, err)`, module-level `TEAM_SLOTS = {"p1":1,"p2":2,"p3":3}`, `OVERRIDE_TTL`, `post_webhook`.
- Produces:
  - `HudSource.set_teams_override(self, entries, now=None)` — `entries: dict[int, dict]` (0-based slot → resolved team entry); sets all under one lock.
  - `SetupControl.set_teams(self, teams, now=None) -> dict` — `teams: dict[str,str]` (`{"p1":name,...}`); returns `{"ok":True,"slots":[...],"pending":True}` or `{"error":...}`.
  - `SetupControl._push_teams(self, writes)` — `writes: list[tuple[int,str]]` (1-based slot, roster name); the background thread body.
  - Route `POST /setup/teams` with JSON body `{"teams": {"p1":..,"p2":..,"p3":..}}`.

- [ ] **Step 1: Write the failing tests**

Add these four functions to `tests/test_setup.py` (anywhere among the other `t_*` functions; they reuse the existing `_team_ctl`/`_client` helpers and `TEAM_CONFIG_CSV` roster of `OVO eSports`/`Feel Good`):

```python
def t_set_teams_override_atomic_present():
    # All given slot overrides are visible after a single batch call.
    _ctl_unused, hs, orig = _team_ctl([])
    try:
        hs.set_teams_override({0: hs.resolve_team("OVO eSports"),
                               2: hs.resolve_team("Feel Good")}, now=1000.0)
        assert hs.team_pending(now=1001.0) == {0, 2}
        d = hs.data(now=1001.0)
        assert d["teams"][0]["name"] == "OVO eSports"
        assert d["teams"][2]["name"] == "Feel Good"
    finally:
        m.post_webhook = orig


def t_set_teams_validates_all_or_nothing():
    pushes = []
    ctl, hs, orig = _team_ctl(pushes)
    try:
        # one bad value in the batch -> nothing applied, nothing written
        r = ctl.set_teams({"p1": "OVO eSports", "p2": "Not A Team"}, now=1000.0)
        assert "error" in r
        assert hs.team_pending(now=1001.0) == set()
        assert pushes == []
        assert "error" in ctl.set_teams({"p9": "OVO eSports"})   # bad slot key
        assert "error" in ctl.set_teams(None)                    # not a dict
    finally:
        m.post_webhook = orig


def t_set_teams_atomic_echo_and_pushes():
    pushes = []
    ctl, hs, orig = _team_ctl(pushes)
    try:
        r = ctl.set_teams({"p1": "OVO eSports", "p2": "Feel Good",
                           "p3": "OVO eSports"}, now=1000.0)
        assert r.get("ok") and r.get("pending"), r
        assert hs.team_pending(now=1001.0) == {0, 1, 2}          # all three atomic
        d = hs.data(now=1001.0)
        assert [t["name"] for t in d["teams"][:3]] == \
            ["OVO eSports", "Feel Good", "OVO eSports"]
        ctl._push_teams([(1, "OVO eSports"), (2, "Feel Good"),
                         (3, "OVO eSports")])                    # thread body, run sync
        assert {"action": "teams", "slot": 1, "name": "OVO eSports"} in pushes
        assert {"action": "teams", "slot": 2, "name": "Feel Good"} in pushes
        assert {"action": "teams", "slot": 3, "name": "OVO eSports"} in pushes
        assert ctl.push_status == "ok"
    finally:
        m.post_webhook = orig


def t_endpoints_setup_teams_post():
    pushes = []
    ctl, hs, orig = _team_ctl(pushes)
    srv, get, post = _client(ctl)
    try:
        r = post("/setup/teams", {"teams": {"p1": "OVO eSports",
                                            "p2": "Feel Good", "p3": "OVO eSports"}})
        assert r.get("ok") and r.get("pending"), r
        assert hs.team_pending() == {0, 1, 2}
        assert "error" in post("/setup/teams", {"teams": {"p1": "Not A Team"}})
    finally:
        srv.shutdown(); m.post_webhook = orig
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_setup.py`
Expected: FAIL — `AttributeError: 'HudSource' object has no attribute 'set_teams_override'` (and `'SetupControl' object has no attribute 'set_teams'`).

- [ ] **Step 3: Add `HudSource.set_teams_override`**

In `src/relay/racecast-feeds.py`, immediately after the existing `set_team_override` method (around line 3594), add:

```python
    def set_teams_override(self, entries, now=None):
        """Optimistic echo for a BATCH panel team write: set multiple podium-slot
        overrides (0-based slot -> entry) under a SINGLE lock acquisition, so the
        /hud/data reader (same lock) never observes a partial top-3. The per-call
        set_team_override would let a poll interleave between slots — the exact
        duplication this batch path removes."""
        now = time.time() if now is None else now
        exp = now + OVERRIDE_TTL
        with self.lock:
            for slot, entry in entries.items():
                self.team_overrides[slot] = (entry, exp)
```

- [ ] **Step 4: Add `SetupControl.set_teams` and `_push_teams`**

In `src/relay/racecast-feeds.py`, immediately after the existing `_push_team` method (around line 3708, right before the `# -- URL writes (synchronous)` comment), add:

```python
    # -- batch team apply (Director Panel "Apply Top 3"): all slots atomic ----
    def set_teams(self, teams, now=None):
        """Set all given podium slots ATOMICALLY (one HudSource lock -> the
        broadcast HUD never shows a partial/duplicated standing), then write each
        slot back to the Sheet via the existing single-slot `teams` webhook action
        (no Apps Script change). Validation is all-or-nothing: any bad slot key or
        non-roster value applies nothing and writes nothing."""
        if not isinstance(teams, dict):
            return {"error": "teams must be an object like {\"p1\":\"…\"}"}
        if not self.push_url:
            return {"error": "webhook not configured — set RACECAST_SHEET_PUSH_URL "
                             "in the active profile or .env (wiki: Sheet-Webhook)"}
        roster = self.hud.roster_names()
        resolved = {}                       # 0-based slot index -> (slot_key, name)
        for slot_key, name in teams.items():
            if slot_key not in TEAM_SLOTS:
                return {"error": f"unknown team slot: {slot_key!r} "
                                 f"(one of {', '.join(sorted(TEAM_SLOTS))})"}
            name = (name or "").strip()
            if name not in roster:
                return {"error": f"not in the team roster: {name!r} "
                                 "(add it to the Configuration tab first)"}
            resolved[TEAM_SLOTS[slot_key] - 1] = (slot_key, name)
        if not resolved:
            return {"error": "no team slots given"}
        entries = {idx: self.hud.resolve_team(name)
                   for idx, (_k, name) in resolved.items()}
        self.hud.set_teams_override(entries, now)
        writes = [(idx + 1, name) for idx, (_k, name) in sorted(resolved.items())]
        threading.Thread(target=self._push_teams, args=(writes,),
                         daemon=True).start()
        return {"ok": True,
                "slots": [k for _i, (k, _n) in sorted(resolved.items())],
                "pending": True}

    def _push_teams(self, writes):
        """Sheet write-back for a batch apply: one webhook call per slot (the
        single-slot `teams` action, reused), then a single hud.refresh() once all
        slots are written. `writes` is a list of (1-based slot, roster name)."""
        ok_all = True
        for slot, name in writes:
            full = self.hud.full_team_name(name)
            ok, _err = self._push({"action": "teams", "slot": slot, "name": full},
                                  "teams")
            ok_all = ok_all and ok
        if ok_all:
            self.hud.refresh()
```

- [ ] **Step 5: Add the `POST /setup/teams` route**

In `src/relay/racecast-feeds.py` `do_POST`, after the `if not setup_ctl:` guard and next to the other setup routes (right after the `if p == ["pov", "set"]:` block, around line 6203), add:

```python
                if p == ["setup", "teams"]:
                    return self._send(setup_ctl.set_teams(body.get("teams")))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 tests/test_setup.py`
Expected: PASS — ends with `ALL PASS`.

- [ ] **Step 7: Run the full suite and lint**

Run: `python3 tools/run-tests.py && python3 tools/lint.py`
Expected: the whole suite passes; lint reports no findings.

- [ ] **Step 8: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_setup.py
git commit -m "feat(panel): atomic batch Top-3 team apply (POST /setup/teams)"
```

---

### Task 2: Director Panel — staged Top-3 with Batch toggle (default ON)

**Files:**
- Modify: `src/director/director-panel.html` (CSS `.staged` style; the `TEAM_FIELDS.forEach` block; new `teamChange`/`top3Apply`/`top3SyncControls`; the `setupPoll` team loop)
- Artifact: `src/docs/wiki/images/director-panel.png` (regenerate via the `wiki-screenshots` skill)

**Interfaces:**
- Consumes: `POST /setup/teams` with `{"teams":{"p1":..,"p2":..,"p3":..}}` (Task 1); the existing `teamSet(slot, value)` live path; `$`, `log`, `toast`, `setupPoll`, `TEAM_FIELDS`, `escapeHtml` (existing in the file).
- Produces: client-only state `top3Batch` (persisted `localStorage["racecast.top3.batch"]`, default ON), `top3Staged` map, helpers `teamChange`, `top3Apply`, `top3SyncControls`, and a `lastSetupRO` flag mirrored from the poll.

- [ ] **Step 1: Add the staged-select CSS**

In `src/director/director-panel.html`, right after the `.fld select.pending` rule (line 175), add:

```css
  .fld select.staged{border-color:var(--blue);box-shadow:0 0 0 3px rgba(58,160,255,.18)}
```

- [ ] **Step 2: Replace the team-row wiring and `teamSet`-only behavior**

Replace the existing `TEAM_FIELDS.forEach(...)` block (lines 1415–1420):

```javascript
TEAM_FIELDS.forEach(([key,label])=>{
  const w = document.createElement("div"); w.className = "fld";
  w.innerHTML = `<label>${label}</label><select data-team="${key}" disabled></select>`;
  w.querySelector("select").addEventListener("change", e=>teamSet(key, e.target.value));
  $("#teamRow").appendChild(w);
});
```

with this (dropdowns route through `teamChange`; a Batch toggle + Apply button are appended to the row):

```javascript
/* ---------- Top-3 teams: batch (default) vs live single-slot ----------
   Batch ON (default): a dropdown change only STAGES locally; "Apply Top 3"
   commits all three atomically via POST /setup/teams (one relay request -> the
   HUD never shows a transient duplicate). Batch OFF: each dropdown pushes live
   through teamSet (the pre-existing behavior). */
const TOP3_BATCH_KEY = "racecast.top3.batch";
let top3Batch = (localStorage.getItem(TOP3_BATCH_KEY) ?? "1") !== "0";   // default ON
let lastSetupRO = false;                  // read-only state from the last setup poll
const top3Staged = {};                    // slot key -> staged (unapplied) value

TEAM_FIELDS.forEach(([key,label])=>{
  const w = document.createElement("div"); w.className = "fld";
  w.innerHTML = `<label>${label}</label><select data-team="${key}" disabled></select>`;
  w.querySelector("select").addEventListener("change", e=>teamChange(key, e.target.value));
  $("#teamRow").appendChild(w);
});
{ const w = document.createElement("div"); w.className = "fld";
  w.innerHTML = `<label><input type="checkbox" id="top3BatchTgl"> Batch</label>` +
                `<button class="pill go" id="top3Apply" disabled>Apply Top 3</button>`;
  $("#teamRow").appendChild(w); }
$("#top3BatchTgl").checked = top3Batch;
$("#top3BatchTgl").addEventListener("change", e=>{
  top3Batch = e.target.checked;
  try{ localStorage.setItem(TOP3_BATCH_KEY, top3Batch ? "1" : "0"); }catch(_){}
  for (const k in top3Staged) delete top3Staged[k];   // discard unapplied staging
  top3SyncControls();
  setupPoll();                                         // re-sync selects from the sheet
});
$("#top3Apply").addEventListener("click", top3Apply);

function top3SyncControls(){
  const dirty = Object.keys(top3Staged).length > 0;
  $("#top3Apply").hidden = !top3Batch;
  $("#top3Apply").disabled = lastSetupRO || !dirty;
  for (const [key] of TEAM_FIELDS){
    const sel = document.querySelector(`select[data-team="${key}"]`);
    if (!sel) continue;
    const staged = key in top3Staged;
    sel.classList.toggle("staged", staged);
    if (staged) sel.classList.remove("pending");
  }
}

// A dropdown change stages locally in batch mode, pushes live otherwise.
function teamChange(slot, value){
  if (top3Batch){
    if (!value) return;
    top3Staged[slot] = value;
    top3SyncControls();
    return;
  }
  teamSet(slot, value);
}

async function top3Apply(){
  if (!Object.keys(top3Staged).length) return;
  // Submit the complete top-3: staged where changed, current selection otherwise.
  const teams = {};
  for (const [key] of TEAM_FIELDS){
    const sel = document.querySelector(`select[data-team="${key}"]`);
    const v = (key in top3Staged) ? top3Staged[key] : (sel ? sel.value : "");
    if (v) teams[key] = v;
  }
  try{
    const r = await fetch("/setup/teams", {method:"POST", cache:"no-store",
      headers:{"Content-Type":"application/json"}, body: JSON.stringify({teams})});
    const d = await r.json();
    if (d.error){ log("Top-3: " + d.error, "err"); toast("Top-3: " + d.error); return; }
    log("Top-3 applied → " + Object.values(teams).join(" / "));
    for (const k in top3Staged) delete top3Staged[k];
    top3SyncControls();
    setupPoll();
  }catch(e){ log("Top-3 apply failed (relay reachable?): " + e, "err"); toast("Top-3 apply failed — relay unreachable"); }
}
```

Note: `teamSet` (the live single-slot function defined just below at lines 1422–1431) stays exactly as-is.

- [ ] **Step 3: Guard staged selects in the poll**

Replace the team loop in `setupPoll` (lines 1468–1481):

```javascript
  for (const [key] of TEAM_FIELDS){
    const sel = document.querySelector(`select[data-team="${key}"]`);
    if (!sel || sel === document.activeElement) continue;
    const opts = d.options[key] || [];
    const sig = JSON.stringify(opts);
    if (sel.dataset.sig !== sig){
      sel.innerHTML = opts.map(o=>`<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join("");
      sel.dataset.sig = sig;
    }
    const cur = d.fields[key] || "";
    if ([...sel.options].some(o=>o.value===cur)) sel.value = cur;
    sel.classList.toggle("pending", d.pending.includes(key));
    sel.disabled = ro;
  }
```

with (refresh options + disabled always, but never yank a staged-but-unapplied pick):

```javascript
  for (const [key] of TEAM_FIELDS){
    const sel = document.querySelector(`select[data-team="${key}"]`);
    if (!sel || sel === document.activeElement) continue;
    const opts = d.options[key] || [];
    const sig = JSON.stringify(opts);
    if (sel.dataset.sig !== sig){
      sel.innerHTML = opts.map(o=>`<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join("");
      sel.dataset.sig = sig;
    }
    sel.disabled = ro;
    if (key in top3Staged) continue;          // staged-but-unapplied: leave the pick
    const cur = d.fields[key] || "";
    if ([...sel.options].some(o=>o.value===cur)) sel.value = cur;
    sel.classList.toggle("pending", d.pending.includes(key));
  }
  lastSetupRO = ro;
  top3SyncControls();
```

- [ ] **Step 4: Manually verify the panel behavior**

Stand up a local dev build per the `racecast-local-uat` skill (relay + panel from `src/`), open `/panel`, and confirm:
- The HUD section's Top-3 row shows three dropdowns + a `Batch` checkbox (checked by default) + an `Apply Top 3` button (disabled until a change).
- Batch ON: changing P1 then P2 tints them blue (staged) and does NOT change the broadcast HUD; clicking `Apply Top 3` flips all selected slots at once (no duplicate frame) and writes the Sheet; the row returns to amber `pending` then settles.
- Toggling Batch OFF discards unapplied staging and restores the live behavior (a dropdown change pushes immediately).

Expected: as described; the log lines `Top-3 applied → …` appear on apply.

- [ ] **Step 5: Regenerate the Director Panel wiki screenshot**

Invoke the `wiki-screenshots` skill and recapture the Director Panel image (the demo profile + `tools/obs-sim.py` recipe the skill documents), overwriting `src/docs/wiki/images/director-panel.png`.

Expected: the committed image shows the new Top-3 row (Batch toggle + Apply Top 3 button).

- [ ] **Step 6: Run the full suite and lint** (HTML is not unit-tested, but guard against regressions)

Run: `python3 tools/run-tests.py && python3 tools/lint.py`
Expected: pass / no findings.

- [ ] **Step 7: Commit**

```bash
git add src/director/director-panel.html src/docs/wiki/images/director-panel.png
git commit -m "feat(panel): stage Top-3 teams and apply in one action (Batch default)"
```

---

## Self-review notes

- **Spec coverage:** atomic relay override (Task 1 Step 3), all-or-nothing validation (Task 1 Step 4 + test), reuse single-slot webhook / no Apps Script change (Task 1 `_push_teams`), `POST /setup/teams` (Task 1 Step 5), Batch toggle default-on + staging + Apply + poll guard + read-only disable (Task 2), live path unchanged (`teamSet` untouched), director-panel.png refresh (Task 2 Step 5). All spec sections map to a task.
- **Type consistency:** `set_teams_override(entries: dict[int,dict])`, `set_teams(teams: dict[str,str]) -> dict`, `_push_teams(writes: list[tuple[int,str]])`, route body key `teams` — used consistently across backend, tests, and the panel `fetch`.
