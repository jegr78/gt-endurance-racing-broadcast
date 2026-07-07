# Kind-conditional UI (Director Panel + Control Center) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adapt the Director Panel and Control Center to the active profile's `kind` so a solo profile shows only the relevant controls and a solo relay never crashes the panel.

**Architecture:** Purely client-side gating in vanilla JS, matching the repo's existing patterns (`applyMode`, 404-self-hide, `os`-driven action hiding). The Director Panel reads the solo signal that already exists on `/status` (`d.solo === true`); the Control Center learns each profile's `kind` from a new field on `/api/profiles`. Every solo branch is additive and guarded — with the signal false/absent the DOM, CSS, and data flow are byte-identical to today.

**Tech Stack:** Python 3.11+ stdlib (no deps), vanilla HTML/CSS/JS, the repo's runnable-script test files (no pytest — each `tests/test_*.py` is a script; `tools/run-tests.py` runs all).

## Global Constraints

- **Edit only under `src/`** (and `tests/`). `dist/`/`runtime/` are generated.
- **All scripts and docs English only.**
- **Endurance path byte-identical; no existing test commented out/disabled.** Every solo branch is guarded on the solo signal; endurance behavior is unchanged.
- **No hardcoded secrets, machine paths, or real IPs in committed files.** Tests use fixtures only.
- **The solo signal is the EXISTING `/status` field** `d.solo === true` (equivalently `d.mode === "solo"`) — no new relay endpoint, no new `/status` field.
- **Kind values:** `endurance` (default) | `solo`. Solo templates: `commentary` | `pov` (`cfg.SOLO_TEMPLATES`, first entry is the default).
- **UI change → visual verification + committed wiki screenshot in the SAME change** (`director-panel.png`, affected `cc-*.png`), captured from a **local dev build** (no `VERSION`), per CLAUDE.md.
- Run after Python edits: `python3 tools/lint.py`. Run the whole suite with `python3 tools/run-tests.py`. Run one file with `python3 tests/test_ui_server.py`.

---

## File Structure

- `src/racecast.py` — `profiles_data()` gains a per-profile `kind`; `profile_new_data()` gains `kind`/`template` params forwarded to `pa.create_profile`.
- `src/ui/ui_server.py` — `/api/profile/new` forwards `kind`/`template` from the request body.
- `src/ui/control-center.html` — new-profile dialog kind/template selectors + JS; kind-gating of the Streams view, Home feeds row, and the (now solo-only) Solo-devices section.
- `src/director/director-panel.html` — `applySolo()`, `body.solo` CSS, solo-safe feed guards in `relayPoll()`, POV editor revealed as its own card in solo.
- `tests/test_racecast.py` — `profiles_data` kind field; `profile_new_data` forwards kind/template.
- `tests/test_ui_server.py` — `/api/profile/new` forwards kind/template; the `_ctx` fake accepts them.

---

### Task 1: Control Center backend — `kind` field + creation passthrough

Pure Python, unit-tested. Produces the interface Task 2's front-end consumes.

**Files:**
- Modify: `src/racecast.py` — `profiles_data()` (~4178-4200), `profile_new_data()` (~4217-4229)
- Modify: `src/ui/ui_server.py` — `/api/profile/new` route (~704-715)
- Test: `tests/test_racecast.py`, `tests/test_ui_server.py`

**Interfaces:**
- Consumes: `pcfg.resolve_config(...).kind` (str, default `"endurance"`), `pcfg.DEFAULT_KIND`, `pcfg.SOLO_TEMPLATES`, `pa.create_profile(root, name, source, kind=..., template=...)`.
- Produces:
  - `profiles_data()` → each `profiles[i]` dict now carries `"kind": str` (and the `ProfileError` fallback entry carries `"kind": pcfg.DEFAULT_KIND`).
  - `profile_new_data(name, source="example", create=None, kind=None, template=None)` — forwards `kind`/`template` to `create_profile`; `kind=None` ⇒ endurance default.
  - `POST /api/profile/new` accepts optional body keys `kind`, `template`.

- [ ] **Step 1: Write the failing test — `profiles_data` reports kind**

Add to `tests/test_racecast.py` (extend the existing fixture-style test; place right after `t_profiles_data_lists_active_and_available`):

```python
def t_profiles_data_reports_kind():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prof = os.path.join(td, "profiles")
        os.makedirs(os.path.join(prof, "demo"))
        os.makedirs(os.path.join(prof, "solo1"))
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(prof, "demo", "profile.env"), "w") as fh:
            fh.write("NAME=Demo League\nSHEET_ID=abc\n")
        with open(os.path.join(prof, "solo1", "profile.env"), "w") as fh:
            fh.write("NAME=Solo One\nKIND=solo\nTEMPLATE=commentary\n")
        os.makedirs(os.path.join(td, "runtime"))
        with open(os.path.join(td, "runtime", "active-profile"), "w") as fh:
            fh.write("demo\n")
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            d = m.profiles_data()
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        by = {p["name"]: p for p in d["profiles"]}
        assert by["demo"]["kind"] == "endurance", by["demo"]
        assert by["solo1"]["kind"] == "solo", by["solo1"]
```

Register it in the file's runner list (find where `t_profiles_data_lists_active_and_available` is called at the bottom `if __name__` block and add `t_profiles_data_reports_kind()` next to it).

- [ ] **Step 2: Run it — expect FAIL**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `KeyError: 'kind'` (profiles entries have no `kind` yet).

- [ ] **Step 3: Implement — add `kind` in `profiles_data`**

In `src/racecast.py`, in `profiles_data()`, change the success append and the `ProfileError` fallback:

```python
                out.append({"name": n, "display": rc.name,
                            "sheet_set": bool(rc.sheet_id),
                            "kind": rc.kind})
                if n == active:
                    logo = bool(servable_logo_path(rc.logo_path))
            except pcfg.ProfileError:
                out.append({"name": n, "display": n, "sheet_set": False,
                            "kind": pcfg.DEFAULT_KIND})
```

Also update the docstring line to mention `kind`:

```python
    {ok, active, logo, profiles:[{name, display, sheet_set, kind}]} or {ok:false, error}.
```

- [ ] **Step 4: Run it — expect PASS**

Run: `python3 tests/test_racecast.py`
Expected: PASS.

- [ ] **Step 5: Write the failing test — `profile_new_data` forwards kind/template**

Add to `tests/test_racecast.py` (near the other profile tests):

```python
def t_profile_new_data_forwards_kind_template():
    seen = {}
    def fake_create(root, name, source, kind=None, template=None):
        seen.update(root=root, name=name, source=source, kind=kind,
                    template=template)
        return os.path.join(root, "profiles", "solo1")
    orig = m._env_base
    m._env_base = lambda *a, **k: "/tmp/x"
    try:
        r = m.profile_new_data("Solo One", None, create=fake_create,
                               kind="solo", template="pov")
    finally:
        m._env_base = orig
    assert r["ok"] is True, r
    assert seen["kind"] == "solo" and seen["template"] == "pov", seen

def t_profile_new_data_defaults_endurance():
    seen = {}
    def fake_create(root, name, source, kind=None, template=None):
        seen.update(kind=kind, template=template)
        return os.path.join(root, "profiles", "gt3")
    orig = m._env_base
    m._env_base = lambda *a, **k: "/tmp/x"
    try:
        m.profile_new_data("GT3", "demo", create=fake_create)
    finally:
        m._env_base = orig
    assert seen["kind"] == m.pcfg.DEFAULT_KIND and seen["template"] is None, seen
```

Register both in the runner block.

- [ ] **Step 6: Run it — expect FAIL**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `profile_new_data` has no `kind`/`template` params (TypeError: unexpected keyword argument 'kind').

- [ ] **Step 7: Implement — `profile_new_data` params + passthrough**

In `src/racecast.py`, change `profile_new_data`:

```python
def profile_new_data(name, source="example", create=None, kind=None,
                     template=None):
    """Create a new profile by copying `source` (endurance) or generating a
    solo profile.env (kind="solo"). Does NOT switch to it.
    {ok, name, path} or {ok:false, error}. `create` seam."""
    try:
        root = _env_base(IS_FROZEN, _real_executable(), HERE)
        target = (create or pa.create_profile)(
            root, name, source or "example",
            kind=kind or pcfg.DEFAULT_KIND, template=template)
        return {"ok": True, "name": os.path.basename(target), "path": target}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": f"could not create profile: {exc}"}
```

(Keep the existing trailing comment about the slug in the docstring/body if you prefer; the `return` line is unchanged in spirit.)

- [ ] **Step 8: Run it — expect PASS**

Run: `python3 tests/test_racecast.py`
Expected: PASS.

- [ ] **Step 9: Write the failing test — route forwards kind/template**

In `tests/test_ui_server.py`, first update the default `_ctx` fake (line ~154) so it tolerates the new kwargs:

```python
            "profile_new": lambda name, source=None, kind=None, template=None: {
                "ok": True, "name": name, "from": source,
                "kind": kind, "template": template},
```

Then add a new test (near `t_profile_new_route_wraps_provider` / the existing `/api/profile/new` test at ~1240):

```python
def t_profile_new_route_forwards_kind_template():
    seen = []
    ctx = _ctx()
    ctx["profile_new"] = lambda name, source=None, kind=None, template=None: (
        seen.append((name, source, kind, template))
        or {"ok": True, "name": name, "from": source})
    httpd, port = _serve(ctx)
    try:
        code, body = _post_json(port, "/api/profile/new",
                                {"name": "solo1", "from": None,
                                 "kind": "solo", "template": "pov"})
        data = json.loads(body)
        assert code == 200 and data["ok"] is True, (code, body)
        assert seen == [("solo1", None, "solo", "pov")], seen
    finally:
        httpd.shutdown()
```

Register it in the file's runner block (bottom of `tests/test_ui_server.py`).

- [ ] **Step 10: Run it — expect FAIL**

Run: `python3 tests/test_ui_server.py`
Expected: FAIL — the route calls `ctx["profile_new"](name, from)` positionally, so `kind`/`template` never reach the fake (`seen` has `None, None`).

- [ ] **Step 11: Implement — route forwards kind/template**

In `src/ui/ui_server.py`, in the `/api/profile/new` handler, change the call:

```python
                try:
                    result = ctx["profile_new"](
                        body.get("name"), body.get("from"),
                        kind=body.get("kind"), template=body.get("template"))
```

- [ ] **Step 12: Run it — expect PASS + lint + full suite**

Run: `python3 tests/test_ui_server.py` → PASS
Run: `python3 tools/lint.py` → clean
Run: `python3 tools/run-tests.py` → all green (confirms no endurance test regressed)

- [ ] **Step 13: Commit**

```bash
git add src/racecast.py src/ui/ui_server.py tests/test_racecast.py tests/test_ui_server.py
git commit -m "feat(solo): Control Center learns profile kind + solo creation passthrough (#307)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Control Center front-end — creation dialog + kind gating

HTML/JS only. No unit tests (the repo does not unit-test CC front-end JS); covered by visual verification + the committed wiki screenshots. Consumes Task 1's `kind` field.

**Files:**
- Modify: `src/ui/control-center.html` — new-profile dialog markup (~691-700), `newProfile()` JS (~2882-2905), the Streams nav button (~475) + view (~539), the Home feeds row (~630-631), the Solo-devices section (~988-1007), and a `body.solo` CSS block.
- Wiki: `src/docs/wiki/images/cc-*.png` (affected views).

**Interfaces:**
- Consumes: `GET /api/profiles` → `{active, profiles:[{name, kind, ...}]}` (Task 1). The existing `loadProfiles()` already fetches this.
- Produces: a `document.body.classList` toggle `solo` reflecting the active profile's kind; the new-profile dialog POSTs `{name, from, kind, template}`.

- [ ] **Step 1: Add kind/template selectors to the new-profile dialog**

In `src/ui/control-center.html`, replace the `New profile` section body (~693-698) so it reads:

```html
          <div class="row"><span class="name">Name</span>
            <input id="newprofile-name" placeholder="e.g. erf" aria-label="New profile name">
            <span class="name">Kind</span>
            <select id="newprofile-kind" aria-label="Profile kind"
                    onchange="onKindChange()">
              <option value="endurance">Endurance (feeds + Sheet)</option>
              <option value="solo">Solo (local capture + webcam)</option>
            </select>
            <span class="name" id="newprofile-from-label">Copy from</span>
            <select id="newprofile-from" aria-label="Template to copy from"></select>
            <span class="name" id="newprofile-template-label" hidden>Template</span>
            <select id="newprofile-template" aria-label="Solo starter template" hidden>
              <option value="commentary">Commentary</option>
              <option value="pov">POV (driver)</option>
            </select>
            <button onclick="newProfile()">
              <svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>Create</button></div>
```

- [ ] **Step 2: Add the kind-change handler + update `newProfile()`**

In `src/ui/control-center.html`, add `onKindChange()` just above `async function newProfile()` (~2882), and update `newProfile()` to read kind/template and send them:

```javascript
function onKindChange() {
  const solo = $('newprofile-kind').value === 'solo';
  // Solo generates a fresh sheet-less profile — Copy-from is not applicable
  // (the CLI forbids --from with --kind solo).
  $('newprofile-template').hidden = !solo;
  $('newprofile-template-label').hidden = !solo;
  $('newprofile-from').hidden = solo;
  $('newprofile-from-label').hidden = solo;
}

async function newProfile() {
  const name = $('newprofile-name').value.trim();
  const kind = $('newprofile-kind').value;
  const solo = kind === 'solo';
  const from = solo ? null : $('newprofile-from').value;
  const template = solo ? $('newprofile-template').value : null;
  if (!name) { showProfileErr('newprofile-err', 'Enter a profile name.'); return; }
  let d;
  try {
    d = await (await fetch('/api/profile/new', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name, from, kind, template})})).json();
  } catch (e) { showProfileErr('newprofile-err', 'Control Center not reachable.'); return; }
  if (!d.ok) { showProfileErr('newprofile-err', d.error || 'could not create profile'); return; }
  $('newprofile-err').hidden = true;
  $('newprofile-name').value = '';
  loadProfiles();
  const hint = $('profile-hint');
  hint.hidden = false;
  hint.textContent = "created '" + name + "' — select it above to activate";
}
```

- [ ] **Step 3: Gate the active-profile kind into a `body.solo` class**

Find `loadProfiles()` in `src/ui/control-center.html` (it fetches `/api/profiles`). After it renders the list and knows `data.active` + `data.profiles`, add a call to a new `applyKindGating(data)`. Add this function near `loadProfiles`:

```javascript
function applyKindGating(data) {
  // Reflect the ACTIVE profile's kind onto <body> so kind-specific CSS can
  // hide feed surfaces / reveal solo controls. Endurance = no class.
  let kind = 'endurance';
  if (data && data.ok && Array.isArray(data.profiles)) {
    const a = data.profiles.find(p => p.name === data.active);
    if (a && a.kind) kind = a.kind;
  }
  document.body.classList.toggle('solo', kind === 'solo');
}
```

In `loadProfiles()`, at the end of the success path (where `data` is in scope), add:

```javascript
  applyKindGating(data);
```

(If `loadProfiles` names its parsed JSON differently, use that variable.)

- [ ] **Step 4: Give the gated containers stable ids**

In `src/ui/control-center.html`:
- The Home "Feeds" row (~630): wrap the row in an id:
  ```html
          <div class="row" id="home-feeds-row"><span class="name">Feeds</span>
            <span class="dim grow" id="hd-feeds">start the relay for live stats</span></div>
  ```
- The Solo-devices `<section>` (the one whose `.viewhead` h3 is "Solo devices", ~988): add `id="dev-section"` to that `<section>` open tag.
- The Streams nav button (~475) already has `data-nav="streams"`; the Streams view (~539) already has `data-view="streams"`. No markup change needed — the CSS selectors target those attributes.

- [ ] **Step 5: Add the `body.solo` CSS block**

Append to the `<style>` block in `src/ui/control-center.html` (end of the CSS):

```css
/* Kind-conditional UI (#307): a solo profile hides the feed/schedule surfaces
   and reveals the solo-only device pickers. Endurance = no `.solo` class. */
body.solo [data-nav="streams"],
body.solo [data-view="streams"],
body.solo #home-feeds-row { display: none !important; }
#dev-section { display: none; }            /* solo-only; hidden for endurance */
body.solo #dev-section { display: block; }
```

- [ ] **Step 6: Serve a local dev build + visually verify (ui-visual-verification skill)**

Boot the Control Center from source on a free port (never 8089):

```bash
# from the repo root
RACECAST_UI_PORT=8092 python3 src/racecast_ui.py --no-browser &   # or `racecast ui`
```

Using the Playwright MCP, at viewport 1440×900:
- Open the **Profile** view; screenshot the **New profile** dialog with Kind=Endurance (Copy-from shown) and again with Kind=Solo (Template shown, Copy-from hidden). Confirm the selects use the CC theme (no white browser control on the dark panel — the #397 smell).
- With a solo profile active (create one via the dialog, then select it), confirm the **Streams** nav item + view are gone, the **Home** Feeds row is gone, and **General Settings → Solo devices** is shown. Switch back to an endurance profile and confirm all of it returns (byte-identical).
- `Read` each PNG back and check theme fit, alignment, disabled/hidden states.

- [ ] **Step 7: Refresh the committed wiki screenshots**

Per CLAUDE.md, regenerate the affected `cc-*.png` from this dev build (dev-build badge, `demo`-style profile, no machine-path leaks) using the `wiki-screenshots` skill, and stage them. At minimum: the **Profile** view showing the new-profile dialog (`cc-profile.png` if that is the canonical name — otherwise the view's existing image). Verify no `.env` path / real Tailscale IP is visible in frame.

- [ ] **Step 8: Record the visual-verify marker + tear down**

```bash
python3 .claude/hooks/record_ui_verified.py src/ui/control-center.html
```
Tear down: stop the UI process; remove any scratch PNGs from the repo root; `git checkout -- profiles/demo/profile.env` if the demo profile's `CONSOLE_SECRET` got auto-written; delete any throwaway solo test profile you created under `profiles/`.

- [ ] **Step 9: Lint + full suite + commit**

```bash
python3 tools/lint.py
python3 tools/run-tests.py
git add src/ui/control-center.html src/docs/wiki/images/
git commit -m "feat(solo): kind-conditional Control Center (creation dialog + view gating) (#307)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Director Panel — solo signal + safe guards + POV card

HTML/JS only. Covered by visual verification (loading the panel against a solo relay: no console throw) + the committed `director-panel.png`. Makes the panel solo-safe and applies the cut.

**Files:**
- Modify: `src/director/director-panel.html` — `relayPoll()` feed reads (~1404-1454), a new `applySolo()` near `applyMode()` (~2037), a `body.solo` CSS block, and the POV reveal.
- Wiki: `src/docs/wiki/images/director-panel.png`.

**Interfaces:**
- Consumes: `/status` → in solo, `{mode:"solo", solo:true, feeds:{}, pov, obs, health, cookies_health, league, ...}` (racecast-feeds.py `_solo_status`). In endurance, `feeds.A`/`feeds.B` are present as today.
- Produces: `document.body.classList` toggle `solo`; no data shape change.

- [ ] **Step 1: Add `applySolo()` next to `applyMode()`**

In `src/director/director-panel.html`, right after the `applyMode(...)` function (~2044), add:

```javascript
// Kind-conditional cut (#307): a feed-less solo relay reports {solo:true}. Hide
// the A/B feed + schedule + submission affordances and reveal the POV editor as
// its own card. Endurance (solo=false) is byte-identical — no class is set.
function applySolo(isSolo){
  document.body.classList.toggle("solo", !!isSolo);
  const box = $("#urlsBox");
  if (box && isSolo) box.open = true;   // POV lives in the schedule <details>;
                                        // force it open so the POV card shows.
}
```

- [ ] **Step 2: Set the solo flag + guard feed reads in `relayPoll()`**

In `src/director/director-panel.html`, in `relayPoll()` after `relayLed(true); clearBanner("relay");` (~1402) add:

```javascript
    const solo = d.solo === true;         // feed-less solo relay (#302)
    applySolo(solo);
```

Then make every `d.feeds.A`/`d.feeds.B` dereference solo-safe:

(a) On-air marker (~1405):
```javascript
    pvMarkOnAir(!solo && d.feeds && d.feeds.A
      ? (d.feeds.A.index <= d.feeds.B.index ? "A" : "B") : null);
```

(b) The A/B state pills (~1414-1416) — wrap:
```javascript
    const n = d.schedule_len;
    if (!solo){
      statePill($("#stA"), "A", "S" + d.feeds.A.stint, n, d.feeds.A.state, d.feeds.A.down);
      statePill($("#stB"), "B", "S" + d.feeds.B.stint, n, d.feeds.B.state, d.feeds.B.down);
    }
```

(c) The feed-health lines + mode block (~1426-1432) — wrap the feed-specific part; keep the POV pill above it untouched:
```javascript
    if (!solo){
      const lines = [healthLine("A", d.feeds.A), healthLine("B", d.feeds.B)];
      if (d.pov && d.pov.state !== "stopped") lines.push(healthLine("POV", d.pov));
      if (d.mode === "qualifying")
        lines.unshift('<span class="warnline">QUALIFYING MODE — Feed A serves the Qualifying tab (race schedule paused)</span>');
      applyMode(d.mode === "qualifying");
      $("#feedHealth").innerHTML = lines.filter(Boolean).join("<br>");
    } else {
      $("#feedHealth").innerHTML = "";
    }
```

(d) The feed-down alarm (~1434-1443) — wrap in `if (!solo){ ... }` (it reads `d.feeds.A.down`/`d.feeds.B.down`). Keep the `d.pov && d.pov.down` case: in solo, evaluate only POV:
```javascript
    const downNames = [];
    if (!solo){
      if (d.feeds.A.down) downNames.push("A");
      if (d.feeds.B.down) downNames.push("B");
    }
    if (d.pov && d.pov.down) downNames.push("POV");
    if (downNames.length)
      setBanner("feeddown", "red",
        "FEED " + downNames.join(" + ") + " DOWN — lost the live stream · " +
        "RELOAD it or cut to the other feed/Standby");
    else clearBanner("feeddown");
```

(e) The OBS-unreachable banner (~1450-1454) reads `d.feeds.A.state` — make the feed-state hint solo-safe:
```javascript
    if (d.obs && d.obs.reachable === false)
      setBanner("obs", "amber",
        "OBS NOT REACHABLE — NEXT can't auto-cut · use the manual FEED/scene buttons"
        + (solo ? "" : " · Feed " + (d.feeds.A.state === "serving" ? "A" : "B") + " state shown above"));
    else clearBanner("obs");
```

The POV pill block (~1417-1424) and `povVisBtn` toggle (~1425) are shared and stay exactly as-is (solo has `d.pov`).

- [ ] **Step 3: Add the `body.solo` CSS block**

Append to the panel's `<style>` block in `src/director/director-panel.html`:

```css
/* Kind-conditional cut (#307): hide A/B feed + schedule + submission surfaces
   in solo; reveal the POV editor (which lives inside #urlsBox) as its own card.
   Endurance = no `.solo` class → byte-identical. */
body.solo #feedsBus,
body.solo #feedHealth,
body.solo #stA,
body.solo #stB,
body.solo .pvtile[data-feed="A"],
body.solo .pvtile[data-feed="B"],
body.solo #urlsBox > summary,
body.solo #raceSched,
body.solo #qualSched,
body.solo #modeSwitch,
body.solo #subsBox { display: none !important; }
/* The "Feeds" section wrapper is the <section> holding #feedsBus — hide it whole. */
body.solo #feedsBus { display: none !important; }
```

Note: `#feedsBus` and `#feedHealth` are the two children of the Feeds `<section>` (there is no id on the section). Hiding both empties the card; if the empty `<section>` frame is visually distracting in the verify step, add an id to that `<section>` (e.g. `id="feedsSec"`) and hide it instead. Decide during Step 5.

- [ ] **Step 4: Boot a solo relay dev build + verify no console throw**

The panel is served by the relay. Boot a **solo** relay from source (a solo profile + the demo obs-sim stand-in per the ui-visual-verification / wiki-screenshots skills). Minimal path:

```bash
cd src   # from the repo root
# create a throwaway solo profile if none exists:
python3 racecast.py profile new "Solo UAT" --kind solo --template commentary
python3 racecast.py --profile solo-uat relay start   # solo relay: no feeds
```

Open `http://127.0.0.1:8088/panel` in the Playwright MCP. **Confirm the browser console shows no error** (the pre-#307 panel throws on `d.feeds.A.stint`). If the relay won't start standalone, drive it via the demo obs-sim recipe in the wiki-screenshots skill.

- [ ] **Step 5: Visually verify the solo cut + POV card (ui-visual-verification)**

At a realistic viewport, element-screenshot the panel:
- **Solo** relay: Feeds card, A/B header pills, A/B preview tiles, schedule/qualifying editor, and Pending-submissions are gone; the **POV** editor is visible as its own card (the `#urlsBox` details is open with its "Schedule" summary hidden); Parts control, HUD/Setup inputs, Timer, Transition, OBS, program + POV preview tiles remain and are correctly themed.
- **Endurance** relay (start the demo endurance relay): the panel is byte-identical to today — POV back inside the collapsible "Schedule" box, all feed surfaces present.
- `Read` the PNGs back and check theme, alignment, no clipped/empty frames.

- [ ] **Step 6: Refresh `director-panel.png`**

Per CLAUDE.md, regenerate `src/docs/wiki/images/director-panel.png` from the dev build using the `wiki-screenshots` skill. The canonical panel image documents the **endurance** panel — recapture it (it must remain accurate; do not let #307 regress it). If a solo-variant image adds value, capture it as a companion under the same images dir; at minimum the endurance `director-panel.png` is refreshed and correct. No machine paths / real IPs in frame.

- [ ] **Step 7: Record the marker + tear down**

```bash
python3 .claude/hooks/record_ui_verified.py src/director/director-panel.html
```
Tear down: `python3 src/racecast.py relay stop`; `pkill -f obs-sim.py` if used; remove the stub `runtime/yt-cookies.txt`; `git checkout -- profiles/demo/profile.env` if touched; delete the throwaway `profiles/solo-uat/` you created; remove scratch PNGs from the repo root.

- [ ] **Step 8: Lint + full suite + commit**

```bash
python3 tools/lint.py           # no Python changed, but cheap
python3 tools/run-tests.py      # confirm nothing regressed
git add src/director/director-panel.html src/docs/wiki/images/
git commit -m "feat(solo): kind-conditional Director Panel (hide feeds/schedule, POV card, solo-safe status) (#307)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Signal mechanism (spec A) → Task 3 Step 2 (`d.solo` + `applySolo`), Task 2 Step 3 (`/api/profiles` kind → `body.solo`). ✅
- Director Panel cut (spec B: hide feeds/pills/tiles/schedule/qual/mode/submissions; keep Parts/HUD/timer/OBS/POV) → Task 3 Steps 2-3. ✅
- POV structural handling (spec B) → refined to be **endurance-safe**: POV stays in `#urlsBox`; solo forces the details open and hides the schedule bits + summary, so POV shows as its own card **without moving the DOM node** (moving it out would make POV always-visible in endurance too, violating byte-identical). Same user-visible outcome the design approved; mechanism honors the hard constraint. Flagged in the execution handoff. ✅
- Control Center creation dialog (spec C) → Task 1 (backend) + Task 2 Steps 1-2. ✅
- CC view gating + solo-only devices (spec C) → Task 2 Steps 3-5. ✅
- Testing (spec) → Task 1 unit tests; Tasks 2-3 visual verification + wiki screenshots (spec acknowledges the panel/CC JS is not unit-tested). ✅
- Visual verification + wiki screenshots (spec) → Task 2 Steps 6-8, Task 3 Steps 4-7. ✅

**Placeholder scan:** none — every code step shows the exact code; every command has an expected result.

**Type consistency:** `kind` is a plain str throughout; `profile_new_data(..., kind=None, template=None)` matches the route call in Task 1 Step 11 and the `_ctx` fake signature in Step 9; `applySolo`/`applyKindGating` names are used consistently; the gated ids (`#home-feeds-row`, `#dev-section`, `#urlsBox`, `#feedsBus`, `.pvtile[data-feed]`) match the markup steps.

**One deviation from the spec, by design:** the POV mechanism (see Spec coverage above) — reveal-in-place instead of DOM-move, to keep endurance byte-identical. No other divergence.
