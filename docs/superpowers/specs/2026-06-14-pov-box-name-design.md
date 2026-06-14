# POV box name

**Date:** 2026-06-14
**Status:** Approved — ready for implementation
**Issue:** #130 (OBS: POV Box: Add name)
**Area:** relay (`src/relay/racecast-feeds.py`), HUD page (`src/obs/hud.html`),
Director Panel (`src/director/director-panel.html`), Apps Script + wiki
(`src/docs/wiki/Sheet-Webhook.md`), tests (`tests/test_pov.py`,
`tests/test_setup.py`).
**Builds on:** #129 — reuses the grey-box / white-text splitscreen label look.

## Problem

The HUD already carries an (invisible-by-default) POV picture-in-picture frame
slot (`#pov`, issue #141) aligned to the OBS `Feed POV` scene item. When a driver
POV is on air there is no way to label *whose* POV it is. The producer wants a
**free-text name** in the top-right corner of the POV box, styled like the #129
splitscreen labels, entered via the Panel, stored in the Sheet, and restylable in
the visual overlay builder.

## The Sheet (corrected model)

There is **already** a `POV` tab with a header row (`url`, `name`) and **exactly
one data row** (row 2) used to maintain the POV stream. The name is written to and
read from the `name` column of that row. **No new tabs or cells** are needed and
**no other tab** (Setup / Overlay / Configuration) is touched. The relay already
reads this tab via `pov_source` (a `ScheduleSource` over the POV tab CSV); the
existing `/pov/set` → `pov` webhook action already writes the `url` cell. This
feature extends that one tab/action with the `name` column.

## Decisions (confirmed with the producer)

- **The whole POV box follows the POV feed.** When the POV feed is **not visible**
  (paused/stopped) the **entire** box — frame/background **and** the name — stays
  hidden. When the POV feed is live, the frame shows (as styled) and the name shows
  whenever a name is set. Visibility is driven by the relay's existing POV on/off
  state (`/pov/reload` → on, `/pov/stop` → off), not a new control.
- **The name is free text**, stored in the POV tab's `name` cell. It is **clamped
  to 20 characters** and **may be empty** (cleared). No Configuration-vocab check
  (driver names are not in the vocab).
- **Name and URL share the POV row's one SAVE.** The panel's existing POV row gains
  a name input next to the URL; one SAVE writes both via `/pov/set`.
- **Freshness is guaranteed by the workflow.** `pov_source` is **not** periodically
  polled — it is re-read on `/pov/reload`. Since the box only becomes visible on
  `/pov/reload` (which refreshes `pov_source`), the name is always fresh at the
  moment the box appears. A successful `/pov/set` additionally refreshes
  `pov_source` so a mid-POV rename applies without a reload (subject to the same
  "applies on POV RELOAD" caveat the POV URL already documents).
- **Editable in the visual overlay builder.** Unlike the splitscreen labels, the
  name slot carries a `data-edit` marker so it appears as a positionable/restylable
  slot in the Control Center overlay builder (the issue asks for this explicitly).
- **Look:** grey rounded box, white text, IBM Plex Mono — same family as the
  splitscreen labels. Not force-uppercased (a personal name keeps its casing); the
  producer can add uppercase via the builder / override CSS.

## Architecture

### Relay (`src/relay/racecast-feeds.py`)

**Read the `name` column.** The POV tab's column is literally `name`; the schedule
parser only recognizes `streamer` today:
```python
SCHEDULE_STREAMER_HEADERS = ("streamer", "name")
```
This is additive — header lookup returns the first match in order, so a Schedule /
Qualifying tab with a `streamer` header is unchanged; only a tab with `name` and no
`streamer` (the POV tab) now reads that column into the row's name field. A POV row
with a blank URL but a name is already kept (the parser's "planned stint" rule:
kept when it has a URL **or** a stint **or** a streamer/name).

**Two pure projections on `Relay`**, mirroring #129's `splitscreen_state()`:
```python
    def pov_active(self):
        """True when the POV picture-in-picture feed is live (started, not
        paused). Drives the HUD: the whole POV box — frame and name — shows
        only while the POV is on air."""
        return bool(self.pov and not self.pov.paused)

    def pov_name(self):
        """The POV name from the POV tab's one data row (the 'name' column),
        or '' when there is no POV source / row."""
        if not self.pov_source:
            return ""
        rows = self.pov_source.get_rows()
        return rows[0][1] if rows else ""
```

**Merge both into `/hud/data` at the route** (the handler closure already holds
`relay` and `hud_source`; `build_hud_data`/`HudSource` stay sheet-pure and
untouched). At the `["hud","data"]` branch:
```python
    data = hud_source.data()                  # already a shallow copy
    data["povActive"] = relay.pov_active()
    data["povName"] = relay.pov_name()
    return self._send(data)
```

**Expose the name in `/status`** for panel prefill — `out["pov"]` gains:
```python
    "name": self.pov_name(),
```

**Write the name through the existing POV action.** Give `SetupControl` a
`pov_source` reference and extend `pov_set`:
```python
    def pov_set(self, url, name=None):
        # ... existing push_url + url validation unchanged ...
        payload = {"action": "pov", "url": url}
        if name is not None:
            payload["name"] = (name or "")[:20]
        ok, err = self._push(payload, "pov")
        if ok and self.pov_source is not None:
            self.pov_source.refresh()    # name (and stored url) live immediately
        return {"ok": True} if ok else {"error": err}
```
`name=None` keeps the URL-only call backward-compatible (no `name` key in the
payload → the script leaves the cell untouched). Construct `SetupControl` with
`pov_source=pov_source` (it is already in scope where `SetupControl` is built).

**Route** — pass the name through:
```python
    if p == ["pov", "set"]:
        return self._send(setup_ctl.pov_set(body.get("url"), body.get("name")))
```

### Apps Script (`src/docs/wiki/Sheet-Webhook.md`)

The webhook script is embedded in this wiki page and is updated in the same change.
Make `writePov` header-aware and partial so it can write the `name` cell:
```javascript
   function writePov(ss, p) {
     const sheet = tab(ss, TABS.pov);
     const lastCol = Math.max(1, sheet.getLastColumn());
     const header = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
     const colOf = (name) => {
       for (let c = 0; c < header.length; c++)
         if (String(header[c]).trim().toLowerCase() === name) return c + 1;
       return 0;
     };
     if ('url' in p)  sheet.getRange(2, colOf('url')  || 1).setNumberFormat('@').setValue(p.url  || '');
     if ('name' in p) sheet.getRange(2, colOf('name') || 2).setNumberFormat('@').setValue(p.name || '');
   }
```
- Bump the response version `v: 4` → `v: 5` in `doPost`.
- Update the action table row for `pov` to note it now writes `url` and/or `name`.
- The relay's `check_webhook_response` checks only `ok` + the `action` echo, **not**
  the version number, so v5 is backward-safe with deployed relays.
- **No** change to `SETUP_FIELDS` / `writeSetup` (the name is not a setup field).

### HUD page (`src/obs/hud.html`)

- **New slot**, placed after the `#pov` div:
  ```html
  <div id="pov-name" class="el" data-edit="POV name"
       data-edit-props="left,top,width,height,fontSize,fontFamily,color,background,borderStyle,borderColor,borderWidth"></div>
  ```
  (Prop list aligned to the keys the overlay-build compiler supports — the same
  family `#pov` already uses, plus text props; verify against
  `src/scripts/overlay_build.py` during implementation.)
- **Default style** (a fixed box, builder-resizable like every other slot — the
  grey-pill look comes from the default fill, not a content-sized special case):
  ```css
  #pov-name { left: 1592px; top: 618px; width: 288px; height: 38px;
    justify-content: flex-end;           /* text flush to the box's right edge */
    background: rgba(38,44,52,.92); border: 1px solid #4a5560; border-radius: 7px;
    padding: 0 12px; color: #fff;
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-weight: 600; font-size: 22px; letter-spacing: .04em; }
  ```
  Default geometry sits the box at the POV frame's top-right (frame is
  left:1496 width:384 → right edge 1880; the label ends at 1880, overhanging
  above the frame's top at 644).
- **JS — `tick()`** gains POV handling (reusing the existing `.empty` hide
  mechanism):
  ```js
  const povOn = !!d.povActive;
  document.getElementById("pov").classList.toggle("empty", !povOn);
  setText("pov-name", povOn ? (d.povName || "") : "");
  ```
  `#pov` (frame) hides when the POV is off; `#pov-name` hides when the POV is off
  **or** no name is set (`setText` toggles `.empty` on an empty value).

### Director Panel (`src/director/director-panel.html`)

The POV row in the **URLs · Schedule + POV** section gains a name input; the
existing single SAVE writes both:
- Markup — add a name cell to the POV row:
  ```html
  <tr><td class="rn">POV</td>
      <td><input id="povName" maxlength="20" placeholder="name (max 20)"></td>
      <td><input id="povUrl" placeholder="youtube.com/watch?v=… · twitch.tv/<channel> · UC…"></td>
      <td class="act"><button class="save" id="povSave">SAVE</button></td></tr>
  ```
- `povSave` sends both fields:
  ```js
  body: JSON.stringify({url: $("#povUrl").value.trim(), name: $("#povName").value.trim()})
  ```
- Dirty tracking on `#povName` (same as `#povUrl`):
  ```js
  $("#povName").addEventListener("input", ()=>$("#povName").dataset.dirty = 1);
  ```
- Prefill from `/status` in `schedPoll` (guarded exactly like `#povUrl`, using the
  new `d.pov.name`):
  ```js
  const ninp = $("#povName");
  if (d.pov && !ninp.dataset.dirty && ninp !== document.activeElement &&
      Date.now() - Number(ninp.dataset.saved||0) > SAVE_GUARD_MS)
    ninp.value = d.pov.name || "";
  ```
  (Stamp `#povName.dataset.saved` in `povSave` on success, mirroring `#povUrl`.)

## Data flow

1. Producer types a POV name (≤20) next to the POV URL and clicks SAVE →
   `POST /pov/set {url,name}` → webhook writes the POV tab `name` cell → relay
   refreshes `pov_source` → `/hud/data` `povName` reflects it.
2. Producer brings the POV on air (`/pov/reload`) → `pov_active()` True and
   `pov_source` re-read → the POV frame appears and the name renders in it.
3. Producer stops the POV (`/pov/stop`) → `povActive:false` → the whole box
   (frame + name) hides. The name stays in the Sheet for next time.

## Testing (TDD — test first)

- **`tests/test_pov.py`**:
  - `pov_active()` is True when `relay.pov` exists and is not paused, False when
    paused, False when `relay.pov` is None (drive via the existing `_relay`/`Relay`
    harness; set `relay.pov.paused`).
  - `pov_name()` returns the POV row's name and `""` when there is no source/row.
  - `ScheduleSource._parse_rows` reads the `name` column from a POV-tab-style
    fixture (header `url,name`; one data row) into the row's name field, and a
    Schedule fixture with a `streamer` header still reads `streamer` (regression).
- **`tests/test_setup.py`**:
  - `pov_set(url, name)` pushes `{"action":"pov","url":…,"name":…}` with the name
    clamped to 20 chars; `pov_set(url)` omits the `name` key (back-compat); a
    successful push triggers `pov_source.refresh()` (assert via a stub source).
- **HUD page string checks** (`tests/test_pov.py` or `tests/test_overlay.py`,
  whichever already string-checks `hud.html`): the page contains the `#pov-name`
  slot with `data-edit="POV name"`, and `tick()` toggles `#pov` on `povActive`.

## Wiki screenshots (CLAUDE.md rule — same change)

- **`director-panel.png`** — the POV row gains the name input → **required**.
- **`cc-overlay-builder.png`** — a new `POV name` builder slot appears on the canvas
  → refresh if the new slot is visible in the captured frame (verify when
  recapturing).

## Out of scope / follow-ups

- No new visibility control: the box reuses the existing `/pov/reload` ·
  `/pov/stop` actions Companion already drives.
- No POV name in the splitscreen labels (those stay role-only, #129).
- No periodic POV-tab poll: the on-`/pov/reload` refresh (+ refresh after a
  successful save) is sufficient because the box is only visible after a reload.
- No content-sized "pill" auto-width: the slot is a normal builder box for
  consistency; the grey-pill look is the default fill.
