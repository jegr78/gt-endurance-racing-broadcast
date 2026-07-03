# Graphics browser: Internal (OBS-only) filter + all-three-pages placement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let leagues mark Sheet assets "internal (OBS-only)" so they are hidden from the console Graphics browser, and surface that same browser on the Director Panel and Race Control desk (not just the cockpit) with one look and a fixed max height.

**Architecture:** The internal marker lives in the Sheet but the widget only sees the filesystem, so `get-graphics.py` writes a sidecar `graphics/manifest.json` recording the internal labels; the relay's `list_graphics()` reads it and omits those. The unchanged `/cockpit/graphics` endpoint (any authenticated console subject) is reused by all three pages — no new endpoint, no new public surface.

**Tech Stack:** Pure Python stdlib (no framework, no pytest — each `tests/*.py` is a runnable script); vanilla HTML/CSS/JS in the console pages.

## Global Constraints

- **Edit only under `src/`** (and `tests/`, `docs/`). Never hand-edit `dist/`/`runtime/`.
- **All scripts and docs English only.**
- **`get-graphics.py` is one of the five self-contained, dependency-light scripts** — it must NOT import `config.py` or other shared modules (only stdlib + the existing `placeholders` helper). Duplicate any small helper locally.
- **Backward compatible (racecast is released, v1.1.0):** no `Internal` column / no `manifest.json` → today's behaviour (all graphics listed). Additive only.
- **Truthy convention** mirrors `racecast-feeds.py` `CREW_TRUTHY`: `{"x", "yes", "true", "1", "y", "✓"}`, compared as `(v or "").strip().lower() in <set>`. A Sheets checkbox exports as `TRUE`/`FALSE` in gviz CSV.
- **Manifest filename `"manifest.json"` is a shared contract** between `get-graphics.py` (writer) and `racecast-feeds.py` (reader) — the two cannot share code (dependency-light rule), so keep the literal in sync.
- **Tests must run on any machine / CI** — no real IPs/paths; use `tempfile`.
- Run `python3 tools/lint.py` after changing any Python file; run the touched test file(s); `python3 tools/run-tests.py` is the whole CI suite.
- **Changed a UI surface → refresh its wiki screenshot in the SAME change** and pass the `ui-visual-verification` gate. Surfaces here: Commentator Cockpit → cockpit shots; Director Panel → `director-panel.png`; Race Control → its image under `src/docs/wiki/images/`.

---

### Task 1: `get-graphics.py` — parse the `Internal` column + write `manifest.json`

**Files:**
- Modify: `src/relay/get-graphics.py` (add `import json`; add `ASSET_*` constants + `_asset_truthy` + `internal_from_csv` + `write_manifest` after `MEDIA_LABELS` at line 123; call them in `main()`)
- Test: `tests/test_graphics.py`

**Interfaces:**
- Consumes: nothing new (reads the Assets CSV rows already parsed via `csv.reader`).
- Produces:
  - `internal_from_csv(rows: list[list[str]]) -> set[str]` — asset labels whose `Internal` box is ticked; empty set when no header / no `Internal` column.
  - `write_manifest(out_dir: str, internal_labels: set[str]) -> None` — writes `<out_dir>/manifest.json` = `{"internal": [<sorted labels>]}`; best-effort.
  - `MANIFEST_NAME = "manifest.json"`, `ASSET_NAME_HEADERS`, `ASSET_INTERNAL_HEADERS`, `ASSET_TRUTHY`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_graphics.py` (before the `if __name__` runner):

```python
def t_internal_from_csv_checkbox_true():
    rows = [["Name", "Link", "Internal"],
            ["Standings", "https://drive.google.com/file/d/S/view", "FALSE"],
            ["Standby", "https://drive.google.com/file/d/B/view", "TRUE"],
            ["Weather Rain", "", "TRUE"]]   # ticked, no link -> still internal
    assert m.internal_from_csv(rows) == {"Standby", "Weather Rain"}, m.internal_from_csv(rows)


def t_internal_from_csv_various_truthy_and_header_aliases():
    rows = [["Label", "Link", "OBS only"],
            ["A", "x", "x"], ["B", "x", "✓"], ["C", "x", "yes"],
            ["D", "x", ""], ["E", "x", "false"]]
    assert m.internal_from_csv(rows) == {"A", "B", "C"}, m.internal_from_csv(rows)


def t_internal_from_csv_no_header_or_no_column_is_empty():
    # header-less (today's sheets) -> no Internal column -> empty
    assert m.internal_from_csv([["Standings", "https://drive.google.com/file/d/S/view"]]) == set()
    # header present but no Internal column -> empty
    assert m.internal_from_csv([["Name", "Link"], ["Standings", "x"]]) == set()
    assert m.internal_from_csv([]) == set()


def t_write_manifest_shape():
    import json as _json, tempfile, os as _os
    with tempfile.TemporaryDirectory() as d:
        m.write_manifest(d, {"Standby", "Weather Rain"})
        with open(_os.path.join(d, "manifest.json"), encoding="utf-8") as fh:
            data = _json.load(fh)
        assert data == {"internal": ["Standby", "Weather Rain"]}, data  # sorted


def t_graphics_from_csv_ignores_header_row():
    # A header row must not become a bogus graphic: "Link" is not a Drive URL -> skipped.
    rows = [["Name", "Link", "Internal"],
            ["Standings", "https://drive.google.com/file/d/S/view", "FALSE"]]
    assert m.graphics_from_csv(rows) == {
        "Standings": "https://drive.google.com/file/d/S/view"}, m.graphics_from_csv(rows)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_graphics.py`
Expected: FAIL — `AttributeError: module 'getgraphics' has no attribute 'internal_from_csv'`.

- [ ] **Step 3: Add `json` to the imports**

In `src/relay/get-graphics.py` line 13, change:

```python
import argparse, csv, io, os, re, sys
```
to:
```python
import argparse, csv, io, json, os, re, sys
```

- [ ] **Step 4: Add the constants + helpers after `MEDIA_LABELS`**

Insert directly after the `MEDIA_LABELS = {...}` block (currently ends line 123):

```python
# Assets tab "Internal" checkbox (OBS-only assets hidden from the console Graphics
# browser). Located by header name — mirrors the Crew/Brand header lookup in
# racecast-feeds.py; truthy tokens mirror its CREW_TRUTHY. A Google-Sheets checkbox
# exports as TRUE/FALSE in the gviz CSV. Parsed independently of the download link so a
# ticked row without a link (e.g. a placeholder-seeded graphic) is still marked. With no
# header / no Internal column the set is empty and the browser shows everything.
ASSET_NAME_HEADERS = ("name", "label", "asset")
ASSET_INTERNAL_HEADERS = ("internal", "obs only", "obs-only")
ASSET_TRUTHY = frozenset({"x", "yes", "true", "1", "y", "✓"})

# Sidecar manifest the relay's list_graphics() reads to hide internal assets. The
# filename is a shared contract with racecast-feeds.py (which cannot import this
# dependency-light script) — keep the literal in sync.
MANIFEST_NAME = "manifest.json"


def _asset_truthy(v):
    return (v or "").strip().lower() in ASSET_TRUTHY


def internal_from_csv(rows):
    """Set of Assets-tab labels whose 'Internal' checkbox is ticked. Requires a header
    row with an ASSET_INTERNAL_HEADERS column; the label is read from the
    ASSET_NAME_HEADERS column (default col 0). Empty set when there is no header / no
    Internal column (backward compatible)."""
    if not rows:
        return set()
    header = [(h or "").strip().lower() for h in rows[0]]
    ii = next((header.index(h) for h in ASSET_INTERNAL_HEADERS if h in header), None)
    if ii is None:
        return set()
    ni = next((header.index(h) for h in ASSET_NAME_HEADERS if h in header), 0)
    out = set()
    for row in rows[1:]:
        if len(row) <= ii or not _asset_truthy(row[ii]):
            continue
        label = (row[ni] if ni < len(row) else "").strip()
        if label:
            out.add(label)
    return out


def write_manifest(out_dir, internal_labels):
    """Write <out_dir>/manifest.json = {"internal": [<sorted labels>]} recording the
    OBS-only assets the console Graphics browser must hide. Best-effort: an IO error is a
    warning, never fatal. Not a *.png, so list_graphics/resolve_graphic never touch it."""
    path = os.path.join(out_dir, MANIFEST_NAME)
    tmp = path + ".part"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"internal": sorted(internal_labels)}, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        print(f"WARNING: could not write {MANIFEST_NAME}: {e}")
```

- [ ] **Step 5: Wire it into `main()`**

In `main()`, capture the parsed rows and write the manifest. Change (currently line 264):

```python
    all_graphics = graphics_from_csv(list(csv.reader(io.StringIO(csv_text))))
```
to:
```python
    rows = list(csv.reader(io.StringIO(csv_text)))
    all_graphics = graphics_from_csv(rows)
```

Then, directly after `os.makedirs(a.out, exist_ok=True)` (currently line 273), add:

```python
    write_manifest(a.out, internal_from_csv(rows))
```

(Placed after the dir is created and before the download loop, so the manifest reflects **all** internal assets even under `--only` and even if a download later fails.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 tests/test_graphics.py`
Expected: `ALL PASS` (every `ok  t_…` line, including the new ones).

- [ ] **Step 7: Lint**

Run: `python3 tools/lint.py`
Expected: no findings (clean exit).

- [ ] **Step 8: Commit**

```bash
git add src/relay/get-graphics.py tests/test_graphics.py
git commit -m "feat(graphics): parse Assets 'Internal' column, write graphics manifest"
```

---

### Task 2: Relay `list_graphics()` — filter by the manifest

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`list_graphics` at line 628; add `_internal_graphic_labels` + `GRAPHICS_MANIFEST_NAME` just above it)
- Test: `tests/test_cockpit.py`

**Interfaces:**
- Consumes: `<graphics_dir>/manifest.json` written by Task 1 (`{"internal": [labels]}`).
- Produces: `list_graphics(graphics_dir)` unchanged signature/shape (`[{"name","file"}]`), now omitting internal-labelled PNGs. `_internal_graphic_labels(graphics_dir) -> set[str]` (lowercased).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cockpit.py` after `t_list_graphics_missing_or_unset_dir_is_empty` (line 277). `json`, `os`, `tempfile` are already imported (lines 4-6):

```python
def t_list_graphics_filters_internal_from_manifest():
    with tempfile.TemporaryDirectory() as d:
        _seed_graphics(d)  # Standings, Schedule, Race Results (+ notes.txt)
        with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump({"internal": ["Schedule"]}, fh)
        got = m.list_graphics(d)
        assert got == [
            {"name": "Race Results", "file": "Race Results.png"},
            {"name": "Standings", "file": "Standings.png"},
        ], got  # Schedule hidden; manifest.json itself never listed (not a .png)


def t_list_graphics_internal_match_is_case_insensitive():
    with tempfile.TemporaryDirectory() as d:
        _seed_graphics(d)
        with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump({"internal": ["  sTaNdInGs "]}, fh)  # padded + mixed case
        got = m.list_graphics(d)
        assert [e["name"] for e in got] == ["Race Results", "Schedule"], got


def t_list_graphics_absent_or_malformed_manifest_shows_all():
    with tempfile.TemporaryDirectory() as d:
        _seed_graphics(d)
        assert len(m.list_graphics(d)) == 3, "no manifest -> all listed"
        with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        assert len(m.list_graphics(d)) == 3, "malformed manifest -> all listed"
        with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump({"internal": "Schedule"}, fh)  # wrong type (str, not list)
        assert len(m.list_graphics(d)) == 3, "bad internal type -> all listed"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL — `t_list_graphics_filters_internal_from_manifest` returns all three (no filtering yet).

- [ ] **Step 3: Add the manifest reader + filter**

In `src/relay/racecast-feeds.py`, directly above `def list_graphics(graphics_dir):` (line 628), insert:

```python
# Shared contract with get-graphics.py's MANIFEST_NAME (it writes this file). The two
# cannot share code — the relay's downloaders are deliberately dependency-light — so keep
# the literal "manifest.json" in sync.
GRAPHICS_MANIFEST_NAME = "manifest.json"


def _internal_graphic_labels(graphics_dir):
    """Lowercased set of asset labels marked OBS-only (internal) in the graphics manifest
    get-graphics.py writes. Best-effort: missing/unreadable/malformed/wrong-shape ->
    empty set (the browser shows everything; backward compatible)."""
    if not graphics_dir:
        return set()
    try:
        with open(os.path.join(graphics_dir, GRAPHICS_MANIFEST_NAME), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return set()
    internal = data.get("internal") if isinstance(data, dict) else None
    if not isinstance(internal, list):
        return set()
    return {str(x).strip().lower() for x in internal}
```

Then edit `list_graphics` to consult it. Replace the loop body (lines 640-644):

```python
    out = []
    for fn in names:
        if fn.lower().endswith(".png") and os.path.isfile(os.path.join(graphics_dir, fn)):
            out.append({"name": fn[:-4], "file": fn})
    out.sort(key=lambda e: e["name"].lower())
    return out
```
with:
```python
    internal = _internal_graphic_labels(graphics_dir)
    out = []
    for fn in names:
        if fn.lower().endswith(".png") and os.path.isfile(os.path.join(graphics_dir, fn)):
            name = fn[:-4]
            if name.strip().lower() in internal:
                continue
            out.append({"name": name, "file": fn})
    out.sort(key=lambda e: e["name"].lower())
    return out
```

Also update the docstring's first sentence to note the filter (optional but preferred): append `" Assets flagged internal in the graphics manifest are omitted."` to the `list_graphics` docstring.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_cockpit.py`
Expected: all `ok  t_…` lines, `ALL PASS`.

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_cockpit.py
git commit -m "feat(relay): hide manifest-flagged internal assets from the graphics browser"
```

---

### Task 3: Cockpit — fixed max height on the existing Graphics list

**Files:**
- Modify: `src/cockpit/cockpit.html` (`#gfxList` CSS at line 151)

**Interfaces:** none (CSS only; the widget already exists here).

- [ ] **Step 1: Add the max-height + scroll**

In `src/cockpit/cockpit.html`, change line 151:

```css
  #gfxList { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; }
```
to:
```css
  #gfxList { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px;
             max-height: 260px; overflow-y: auto; }
```

- [ ] **Step 2: Render and eyeball it (ui-visual-verification gate)**

Invoke the `ui-visual-verification` skill. Stand up a local dev build (`racecast-local-uat` recipe, or `racecast ui` + a relay from `src/`) and open the cockpit; with >8 graphics the list must scroll inside the card at ~260px, header + Refresh unaffected. Capture the marker the Stop hook requires.

- [ ] **Step 3: Commit**

```bash
git add src/cockpit/cockpit.html
git commit -m "style(cockpit): cap the graphics browser height with scroll"
```

---

### Task 4: Race Control — Schedule + Graphics side by side (50/50), same widget

**Files:**
- Modify: `src/racecontrol/race-control.html` (markup at lines 185-192; add CSS; add JS near the other pollers)

**Interfaces:**
- Consumes: `GET /cockpit/graphics` (via `j`) + `RC_API('/cockpit/graphics/<file>')` for the `<a href>`. Both already available (`j` at line 236, `RC_API` at line 10).

- [ ] **Step 1: Wrap Schedule + a new Graphics card in a 50/50 row**

In `src/racecontrol/race-control.html`, replace the Schedule card block (lines 185-192):

```html
    <div class="card" style="margin-top:12px;">
      <h2>Schedule</h2>
      <div id="schedEmpty">Loading…</div>
      <table>
        <thead><tr><th style="width:90px">Stint</th><th>Streamer</th><th style="width:80px">On air</th></tr></thead>
        <tbody id="schedRows"></tbody>
      </table>
    </div>
```
with:
```html
    <div class="schedgfx">
      <div class="card">
        <h2>Schedule</h2>
        <div id="schedEmpty">Loading…</div>
        <table>
          <thead><tr><th style="width:90px">Stint</th><th>Streamer</th><th style="width:80px">On air</th></tr></thead>
          <tbody id="schedRows"></tbody>
        </table>
      </div>
      <div class="card">
        <h2 id="gfxHead">Graphics
          <button id="gfxRefresh" type="button" title="Reload the graphics list">Refresh</button>
        </h2>
        <div id="gfxList"><div class="empty">Loading…</div></div>
      </div>
    </div>
```

- [ ] **Step 2: Add the CSS**

In the `<style>` block (near the other card rules, e.g. after the `.wrap` rule around line 46), add:

```css
  .schedgfx { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
  @media (max-width: 640px) { .schedgfx { grid-template-columns: 1fr; } }
  #gfxHead { display: flex; align-items: center; justify-content: space-between; }
  #gfxRefresh { background: none; border: 0; color: #8ab4f8; cursor: pointer;
                font: inherit; font-size: 12px; padding: 0; }
  #gfxList { display: flex; flex-direction: column; gap: 4px;
             max-height: 260px; overflow-y: auto; }
  #gfxList a { display: block; text-decoration: none; color: #e8eaed;
               background: #1b1f25; border: 1px solid #2a3038; border-radius: 6px;
               padding: 7px 10px; font-size: 14px; }
  #gfxList a:hover { border-color: #3b82f6; }
  #gfxList .empty { font-size: 13px; opacity: .6; padding: 2px 0; }
```

- [ ] **Step 3: Add the loader + Refresh wiring + poller bootstrap**

In the `<script>`, add a `loadGraphics()` alongside the other loaders (mirror the cockpit's, using this page's `j`):

```javascript
async function loadGraphics() {
  const box = $('gfxList');
  try {
    const d = await j('/cockpit/graphics');
    const list = d.graphics || [];
    box.textContent = '';
    if (!list.length) {
      const e = document.createElement('div');
      e.className = 'empty'; e.textContent = 'No graphics available.';
      box.appendChild(e); return;
    }
    list.forEach(g => {
      const a = document.createElement('a');
      a.href = RC_API('/cockpit/graphics/' + encodeURIComponent(g.file));
      a.target = '_blank'; a.rel = 'noopener';
      a.textContent = g.name;                 // XSS-safe (Sheet label)
      box.appendChild(a);
    });
  } catch (e) {
    box.textContent = '';
    const er = document.createElement('div');
    er.className = 'empty'; er.textContent = 'Could not load graphics.';
    box.appendChild(er);
  }
}
$('gfxRefresh').addEventListener('click', loadGraphics);
```

Then add `loadGraphics();` to the page's initial bootstrap line (where the other `poll*()`/`load*()` calls fire on load — search for the existing `pollTimer()`/`pollChat()` bootstrap and append `loadGraphics();`).

- [ ] **Step 4: Render and eyeball it (ui-visual-verification gate)**

Invoke `ui-visual-verification`. Open Race Control on a dev build: Schedule and Graphics must sit in one row, 50/50, under the PROGRAM card; the Graphics list scrolls at ~260px; clicking a graphic opens the image in a new tab (auth via the `rc_console` cookie); at ≤640px they stack. Capture the marker.

- [ ] **Step 5: Commit**

```bash
git add src/racecontrol/race-control.html
git commit -m "feat(race-control): add the graphics browser beside the schedule (50/50)"
```

---

### Task 5: Director Panel — Graphics section under the Broadcast chat

**Files:**
- Modify: `src/director/director-panel.html` (markup after `#bchatBox`, line 653, inside `.rail`; add CSS; add JS)

**Interfaces:**
- Consumes: `GET /cockpit/graphics` (plain `fetch` — the page's global fetch patch prefixes `RC_API_BASE`, see the note at line 1939) + `RC_API('/cockpit/graphics/<file>')` for the `<a href>` (RC_API at line 10).

- [ ] **Step 1: Add the Graphics section inside the sidebar (`.rail`)**

In `src/director/director-panel.html`, immediately after the `#bchatBox` closing `</details>` (line 653) and before `</div><!-- /.rail -->` (line 654), insert:

```html
  <details class="bus chat" id="gfxBrowseBox" open>
    <summary>Graphics<button id="gfxRefresh" class="bcompose" title="Reload the graphics list">⟳ Refresh</button></summary>
    <div class="body">
      <div id="gfxList" class="chatlog"><div class="bempty">Loading…</div></div>
      <div class="hint">Read-only: the broadcast still-graphics (Sheet Assets tab).
        Click one to open it in a new tab. OBS-only assets are hidden.</div>
    </div>
  </details>
```

(Note: this is the image **browser**, distinct from the mainpane "Gfx" bus at line 552, which toggles OBS overlay sources.)

- [ ] **Step 2: Add the CSS**

In the `<style>` block (near the `#bchatLog` rules around line 308-311), add:

```css
  #gfxBrowseBox #gfxList { display: flex; flex-direction: column; gap: 4px;
                           max-height: 220px; overflow-y: auto; }
  #gfxBrowseBox #gfxList a { display: block; text-decoration: none; color: var(--fg, #e8eaed);
                             background: #14181d; border: 1px solid #2a3038;
                             border-radius: 6px; padding: 6px 9px; font-size: 13px; }
  #gfxBrowseBox #gfxList a:hover { border-color: #3b82f6; }
  #gfxBrowseBox #gfxList .bempty { color: var(--muted); font-size: 11px; }
```

- [ ] **Step 3: Add the loader + Refresh wiring + bootstrap**

In the `<script>`, add (plain `fetch` — the global patch prefixes the base; `<a href>` still needs `RC_API`):

```javascript
/* ---------- Graphics browser (read-only Sheet-assets list) ---------- */
async function loadGraphics() {
  const box = document.getElementById('gfxList');
  if (!box) return;
  try {
    const r = await fetch('/cockpit/graphics', { cache: 'no-store' });
    if (!r.ok) throw new Error(r.status);
    const d = await r.json();
    const list = d.graphics || [];
    box.textContent = '';
    if (!list.length) {
      const e = document.createElement('div');
      e.className = 'bempty'; e.textContent = 'No graphics available.';
      box.appendChild(e); return;
    }
    list.forEach(g => {
      const a = document.createElement('a');
      a.href = RC_API('/cockpit/graphics/' + encodeURIComponent(g.file));
      a.target = '_blank'; a.rel = 'noopener';
      a.textContent = g.name;                 // XSS-safe (Sheet label)
      box.appendChild(a);
    });
  } catch (e) {
    box.textContent = '';
    const er = document.createElement('div');
    er.className = 'bempty'; er.textContent = 'Could not load graphics.';
    box.appendChild(er);
  }
}
{ const gr = document.getElementById('gfxRefresh');
  if (gr) gr.addEventListener('click', loadGraphics); }
loadGraphics();
```

(Place `loadGraphics();` where the other on-load initializers run — near the broadcast-chat/`bchatPoll()` bootstrap. Guard the `#gfxRefresh` lookup because the id also exists on other pages' shared code paths; here it is scoped inside `#gfxBrowseBox`.)

- [ ] **Step 4: Render and eyeball it (ui-visual-verification gate)**

Invoke `ui-visual-verification`. Open the Director Panel on a dev build: a "Graphics" collapsible sits in the right rail directly under "Broadcast chat", matching the chat sections' look; the list scrolls at ~220px; Refresh reloads; clicking opens the image in a new tab; it is visually distinct from the mainpane "Gfx" toggle bus. Confirm no `#gfxRefresh`/`#gfxList` id clash breaks the crew/broadcast chat. Capture the marker.

- [ ] **Step 5: Commit**

```bash
git add src/director/director-panel.html
git commit -m "feat(director): add the read-only graphics browser under broadcast chat"
```

---

### Task 6: Docs + wiki screenshots

**Files:**
- Modify: `src/docs/wiki/Sheet-Template.md` (Assets tab section, ~line 289)
- Modify: screenshots under `src/docs/wiki/images/` (Director Panel, Race Control, Cockpit)

**Interfaces:** none.

- [ ] **Step 1: Document the `Internal` column**

In `src/docs/wiki/Sheet-Template.md`, in the Assets-tab section, document the header row `Name | Link | Internal` and that `Internal` is a **checkbox** (tickbox). State: ticking it keeps the asset in OBS (still downloaded) but hides it from the console **Graphics** browser (cockpit / Director Panel / Race Control); leave it empty/unticked for commentator-facing graphics; header-less tabs keep all graphics visible. Note a ticked row needs **no link** to mark a placeholder-seeded graphic (e.g. weather overlays) internal. English only; match the page's existing table style.

- [ ] **Step 2: Regenerate the changed screenshots**

Use the `wiki-screenshots` skill (demo profile + `tools/obs-sim.py`, local dev build so the version badge stays uniform) to recapture the Director Panel (`director-panel.png`), the Race Control image, and the cockpit shot(s) that show the Graphics widget. Commit the regenerated PNGs alongside.

- [ ] **Step 3: Validate wiki links/anchors**

Run: `python3 tests/test_wiki.py`
Expected: `ALL PASS` (no broken links/anchors from the edit).

- [ ] **Step 4: Commit**

```bash
git add src/docs/wiki/Sheet-Template.md src/docs/wiki/images/
git commit -m "docs(wiki): document Assets 'Internal' column + refresh console screenshots"
```

---

### Task 7: Full-suite gate + build verify

**Files:** none (verification only).

- [ ] **Step 1: Run the whole test suite**

Run: `python3 tools/run-tests.py`
Expected: all tests pass (this is exactly what CI runs).

- [ ] **Step 2: Lint the whole tree**

Run: `python3 tools/lint.py`
Expected: clean.

- [ ] **Step 3: Build verify (closest thing to CI's ship gate)**

Run: `python3 tools/build.py`
Expected: `dist/` assembles and self-verifies (no secrets, no shell scripts, tokenization OK). `get-graphics.py`'s new `manifest.json` write is runtime-only, so `dist/` is unaffected.

- [ ] **Step 4: Final commit (if the build changed any tracked artifact — usually none)**

```bash
git status   # expect clean; commit only if build.py legitimately updated a tracked file
```

---

## Self-Review

**Spec coverage:**
- Sheet `Name | Link | Internal` header + checkbox → Task 1 (parse) + Task 6 (doc). ✓
- Still download internal assets → Task 1 keeps the download loop untouched; manifest written after `makedirs`. ✓
- Sidecar manifest written by get-graphics → Task 1 (`write_manifest`). ✓
- Relay `list_graphics` filters via manifest → Task 2. ✓
- Endpoint reused, no new surface → Tasks 4/5 call the existing `/cockpit/graphics`. ✓
- Cockpit fixed max-height → Task 3. ✓
- RC Schedule+Graphics 50/50 row → Task 4. ✓
- Director section under broadcast chat → Task 5. ✓
- Backward compatibility (no header / no manifest) → Task 1 (`internal_from_csv` empty), Task 2 (`_internal_graphic_labels` empty); tested in both. ✓
- Tests (pure get-graphics + relay filter) → Tasks 1 & 2. ✓
- Wiki screenshots + `ui-visual-verification` → Tasks 3/4/5 (gate) + Task 6 (committed images). ✓

**Placeholder scan:** no TBD/TODO; every code step shows full code; every command has expected output.

**Type consistency:** `internal_from_csv`/`write_manifest`/`MANIFEST_NAME` (Task 1) vs `_internal_graphic_labels`/`GRAPHICS_MANIFEST_NAME` (Task 2) — the shared value is the string literal `"manifest.json"`, called out in both. `list_graphics` signature and `[{"name","file"}]` shape unchanged. Front-end `loadGraphics()` uses `j` (RC) vs plain `fetch` (director) per each page's shim, `RC_API` for the `<a href>` in both — matches the confirmed page conventions.
