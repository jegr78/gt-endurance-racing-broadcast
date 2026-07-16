# Stint-scene full-page graphics — 12 new toggleable slots

**Date:** 2026-07-16
**Status:** Approved (design), ready for implementation plan

## Goal

Add **12 new full-page broadcast graphics** to the on-air **Stint** scene, each an
**independent on/off toggle** exactly like the existing full-page graphics (Standings,
Race Results, the weather overlays). Every new graphic is maintained the usual way — a
row in the league Google Sheet **Assets** tab — and is shown/hidden from the **Director
Panel** and **Companion** (Stream Deck) just like today's graphics.

### The 12 graphics

| Group | Labels (exact, = filename stem = OBS source name = Sheet Assets label) |
|-------|-----------------------------------------------------------------------|
| Info  | `Weekend Info`, `Race Info`, `Next Event` |
| Grid  | `Starting Grid`, `Grid Row 1`, `Grid Row 2`, `Grid Row 3`, `Grid Row 4`, `Grid Row 5`, `Grid Row 6`, `Grid Row 7`, `Grid Row 8` |

**Toggle model:** all 12 are **independent** on/off toggles. No exclusive/radio and no
progressive-reveal logic. The Grid Row PNGs are authored as full-frame images that paint
only their own row (transparent elsewhere), so a full-frame OBS source is correct and the
crew can reveal rows in any order by toggling them independently.

## How the existing pipeline works (reference)

The download side is **fully sheet-driven** (no hardcoded label list); the show/hide side
is **hardcoded in three surfaces** that must agree on the exact `scene`/`source` strings:

- **Sheet Assets tab → `src/relay/get-graphics.py`** — any Assets row with a Google-Drive
  link is downloaded to `runtime/<profile>/graphics/<Label>.png`. Label is the filename.
  No code change to add a graphic. Placeholder/seed + preflight logic derive the expected
  set from the OBS collection (`placeholders.expected_graphics_from_template`), so a new
  OBS source automatically gets transparent-placeholder + reset behavior.
- **OBS collection `src/obs/GT_Endurance.json`** — each graphic is (a) a top-level
  `image_source` carrying `__RACECAST_GRAPHICS__/<Label>.png` and (b) an invisible
  scene-item in the **Stint** scene with fade show/hide transitions. `src/setup-assets.py`
  substitutes the token generically (no edit needed).
- **Director Panel `src/director/director-panel.html`** — a hardcoded `CONFIG.graphics`
  array (`{label, scene, source}`) renders the `#gfxBus` toggle buttons; each calls the
  generic relay `POST /obs/source {scene, source, on}` (director-gated, arbitrary
  scene/source — **no relay change needed**).
- **Companion `src/companion/racecast-buttons.companionconfig`** — one button per graphic;
  graphics buttons drive OBS **directly via the Companion OBS module** (`toggle_scene_item`
  action + `scene_item_active` feedback), not the relay. Page 1's graphics row is full
  (8/8).

## Design

### 1. OBS collection (`src/obs/GT_Endurance.json`) — simple, full-frame

For each of the 12 labels, add:
- **(a)** a top-level `image_source` in `"sources"`: `"file":
  "__RACECAST_GRAPHICS__/<Label>.png"`, `"linear_alpha": true`, a fresh unique `uuid`.
- **(b)** an invisible scene-item in the **Stint** scene mirroring the `Standings` block:
  unique integer `id`, unique `source_uuid`, `"visible": false`, `bounds_type: 2` with
  `bounds {x:1920, y:1080}` (full-frame), and named `fade_transition` show/hide
  transitions (`"<Label> Show Transition"` / `"<Label> Hide Transition"`, 300 ms).

All 12 are full-frame and invisible by default — identical to the existing full-page
graphics. No new OBS scene, no repositioning session. (Positions/grouping the user raised
refer to the **Panel/Buttons**, not OBS.)

The graphics live only in the **Stint** scene (not Splitscreen/Interview/Standby).

### 2. Director Panel (`src/director/director-panel.html`) — new grouped blocks

Keep the existing `#gfxBus` (HUD/Standings/Schedule/Results/Weather/Standby/Post-Race)
unchanged. Add the 12 new toggles as **two new visually distinct bus sections**, so the
existing graphics bus stays readable:

- A **`Pre-Race`** section (`<section class="bus"><div class="cap">Pre-Race</div>…`) with
  the 3 info toggles: `WEEKEND`, `RACE INFO`, `NEXT EVENT`.
- A **`Grid`** section with `STARTING GRID` on its own semantic `.setrow`, then the 8 row
  toggles `GRID R1`…`GRID R8` on a second wrapped row.

Implementation approach: introduce dedicated config arrays (e.g. `CONFIG.graphicsPreRace`
and `CONFIG.graphicsGrid`) rendered into the two new `.keys` containers, reusing the same
button factory + `toggleSource` handler + `obsSource → POST /obs/source` path as
`CONFIG.graphics`. This follows the semantic-row pattern (cf. the HUD bus's three
`.setrow` rows) and avoids one 23-button flat list. `scene` is `"Stint"` for all 12;
`source` byte-matches the OBS scene-item names.

### 3. Companion (`racecast-buttons.companionconfig`)

Per the approved layout:
- **Extend Page 1** to a 4th row (bump `gridSize.maxRow` 3 → 4) and add the **3 info
  toggles** on the new row 4 (cols 0–2): `Weekend Info`, `Race Info`, `Next Event`.
- **New dedicated Page 5 "GRID"** for the 9 grid graphics: `Starting Grid` on row 0
  (col 0), `Grid Row 1`…`Grid Row 8` across rows 1–2 (cols 0–7).

Each button follows the existing graphics-button pattern: OBS-connection
`toggle_scene_item` action (`{scene:"Stint", source:"<Label>", visible:"toggle"}`) + a
`scene_item_active` feedback for the on-air highlight. Authored/imported/click-tested via
the `companion-buttons` skill (import "Preserving Unselected", Tailscale bind, validate by
clicking).

### 4. Sheet Assets tab (league coordination — not code)

The league adds 12 rows `Label | <Drive PNG link>` to the Assets tab, labels byte-matching
the OBS source names above. Graphics that shouldn't appear in the commentator console
Graphics browser can tick the existing **Internal** checkbox. `get-graphics.py` downloads
them automatically. Documented as an operator step (README/wiki Sheet reference), not
shipped code.

### 5. Wiki screenshots (hard rule — same change)

- Director Panel changed → regenerate `src/docs/wiki/images/director-panel.png` via the
  `wiki-screenshots` skill (demo profile + `tools/obs-sim.py`).
- Companion changed → regenerate the affected `companion-page*.png` (incl. the new **GRID**
  page and the extended Page 1) via the `companion-screenshots` skill.

## Files touched

| File | Change |
|------|--------|
| `src/obs/GT_Endurance.json` | +12 `image_source` defs, +12 invisible full-frame scene-items in the **Stint** scene |
| `src/director/director-panel.html` | +2 bus sections + `CONFIG.graphicsPreRace`/`graphicsGrid` (12 toggles) |
| `src/companion/racecast-buttons.companionconfig` | Page 1 → maxRow 4 + 3 info buttons; new Page 5 "GRID" + 9 buttons |
| `src/docs/wiki/images/director-panel.png` | regenerated |
| `src/docs/wiki/images/companion-page*.png` | regenerated (Page 1 + new GRID page) |
| Sheet Assets tab (league) | +12 rows (operator step, doc only) |

**No edit needed:** `src/setup-assets.py`, `src/relay/get-graphics.py`,
`src/relay/racecast-feeds.py` (`/obs/source`, `/graphics`), `src/scripts/obs_ws.py`,
`src/scripts/placeholders.py`, `src/scripts/event.py` — all derive generically from the
Sheet or the OBS collection.

## Verification

- `python3 tools/run-tests.py` — full suite (test_placeholders/test_graphics derive the
  expected set from the collection; new tokens must stay green).
- `python3 tools/lint.py` — CI lint.
- `python3 tools/build.py` — verify step (tokenization, no secrets, no shell scripts).
- `ui-visual-verification` on the Director Panel (render + eyeball the new blocks).
- Companion buttons click-tested live via the `companion-buttons` skill.
- Manual end-to-end sanity: with the demo profile + obs-sim, toggle each new source and
  confirm OBS visibility flips (source names must byte-match, else a silent 503 /
  "scene item not found").

## Risks / notes

- **Name drift** is the main failure mode: OBS scene-item name, panel `source`, Companion
  `source`, and Sheet Assets label must be byte-identical. A mismatch fails silently
  (panel 503 "scene item not found"; Companion no-op). Keep the four in sync.
- **OBS JSON hand-edit** must produce valid unique `uuid`/`id`/`source_uuid` values and
  correct scene-item schema (mirror the `Standings` block precisely). Alternative if
  hand-editing proves error-prone: add the sources+items inside OBS, export, and fold back
  with `tools/tokenize-obs.py`.
- **Companion Page 1 resize** (maxRow 3 → 4): a 4th row is only visible on decks/tablet
  views tall enough; the web-buttons/tablet view scrolls, so it is fine for the intended
  remote use.
- **Grouping is Panel/Buttons only** — OBS layout stays simple/full-frame per the user's
  clarification.

## Out of scope

- No changes to the toggle transport (`/obs/source` stays generic; graphics Companion
  buttons stay on the OBS module).
- No new relay endpoint, no exclusive/reveal logic, no OBS repositioning session.
- Actual PNG artwork is authored by the league and lives in the Sheet, not in the repo.
