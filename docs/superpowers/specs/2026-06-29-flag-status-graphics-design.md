# Flag Status Graphics — design

Date: 2026-06-29
Status: approved (design phase)

## Problem

The broadcast overlay already shows a **flag/race-control status as text**: the
Setup-tab `Flag` field drives a color-coded condition chip (`#flag-status`) in
`hud.html` (green / yellow / red / safety-car / VSC / FCY / …), and the separate
`Race Control` field drives a free-text banner. Both round-trip Sheet → Overlay
tab → `/hud/data` → HUD, and are controlled from the Director Panel (`#condRow`
dropdown) and the Companion **FLAGS** page (text buttons → `GET /setup/set/flag/…`).

Leagues now want, **as an alternative to the text**, full **flag overlay graphics**
that can be shown in the broadcast: a designed PNG per flag condition, maintained in
the Sheet like every other broadcast graphic, toggled live on air. Required flag set:
**Green, Yellow, Red, Safety Car, Virtual Safety Car**.

## Goal

Add flag graphics as a **separate, parallel control** to the existing flag text —
not a replacement, not coupled to it. A league chooses to use the text chip *or* the
graphics (or, in principle, both). The new control is built into OBS as fixed image
sources in the **Stint** and **Splitscreen** scenes, maintained via the Sheet
**Assets** tab, and toggled from the **Director Panel** and **Companion / Web
Buttons** (and over **Tailscale Funnel** via `/console/panel`, which stays
first-class). A missing Sheet asset falls back to the transparent placeholder PNG, so
nothing breaks.

## Key decisions (locked during brainstorming)

1. **Parallel, independent control** — not a unified/coupled switch. The existing flag
   *text* path (`flag` Setup field, `#flag-status` chip) is untouched (backward
   compatible — racecast is released). The graphic is a brand-new state.
2. **Exactly-one-active logic** — a single state `active ∈ {green, yellow, red,
   safety-car, virtual-safety-car, none}`. Selecting one shows that graphic and hides
   the other four, in **both** scenes; "Clear" hides all five. Flags are mutually
   exclusive by nature, mirroring the single-valued text `flag` field.
3. **Sheet Assets naming** — label = filename = OBS source name, shared `Flag ` prefix
   so they cluster in the Assets tab and the OBS source list:
   - `Flag Green`, `Flag Yellow`, `Flag Red`, `Flag Safety Car`,
     `Flag Virtual Safety Car`
   - → tokens `__RACECAST_GRAPHICS__/Flag Green.png`, etc.
4. **Companion** — a **second row on the existing FLAGS page** (row 0 stays the text
   buttons), graphic buttons backed in the flag's color with a distinguishing prefix,
   so text vs. graphic is unambiguous at a glance. They call a **new endpoint family**
   (`/flag-graphic/…`), never `/setup/set/flag` — separation is enforced
   endpoint-side too.
5. **Funnel is first-class** — the toggle is wired into the existing director-gated
   relay-mediated OBS control surface so the Director Panel works over Funnel
   (`/console/panel`), exactly like the panel's other OBS controls.

## Non-goals (YAGNI / compatibility)

- **No coupling** to the text `flag` field or to program-bus macros. The existing RED
  FLAG macro stays text-only (it toggles `racecontrol` + Standby Cover, unchanged).
- **No HUD-page change.** `hud.html` / `splitscreen.html` are not modified — the flag
  graphic is an OBS image source, not a HUD page element.
- **No new graphics-pipeline code.** `get-graphics.py` / `setup-assets.py` /
  `tokenize-obs.py` already handle arbitrary Assets-labelled image sources and the
  transparent-placeholder fallback; the new sources ride that path unchanged.

## Architecture

### 1. OBS scene collection (`src/obs/GT_Endurance.json`) — hand-authored JSON

- **5 new `image_source` definitions**: `Flag Green`, `Flag Yellow`, `Flag Red`,
  `Flag Safety Car`, `Flag Virtual Safety Car`. Each:
  `settings.file = "__RACECAST_GRAPHICS__/<label>.png"`, `unload:false`,
  `linear_alpha:true`, stable unique `uuid`. Pattern copied from `Standings`.
- **Scene items**: 5 new items in the **Stint** scene and 5 in the **Splitscreen**
  scene, each referencing the matching source `uuid`. Geometry mirrors the existing
  full-screen overlays (`Standings`): `align:5`, `bounds_type:2` (SCALE_INNER),
  `bounds: 1920×1080`, `pos:{0,0}`, `visible:false`, `locked:true`, fade
  show/hide transitions (duration 300). Scene-item integer `id`s must be unique within
  each scene — pick unused values.
- **Re-tokenization**: `tools/tokenize-obs.py` already rewrites any `image_source`
  `settings.file` to `__RACECAST_GRAPHICS__/<basename>` — no tool change. If the
  collection is re-exported from OBS, the new sources fold back automatically.

### 2. Graphics pipeline — no code change

- `src/relay/get-graphics.py` downloads each Sheet **Assets** row by label
  (`Flag Green.png`, …) into `runtime/<profile>/graphics/`. The label IS the filename;
  the new labels contain no `/` and don't collide with `MEDIA_LABELS`.
- Missing asset → transparent placeholder: both `get-graphics.py`
  (`seed_missing_graphics`) and `src/setup-assets.py` (`fill_missing`) scan the OBS
  template via `placeholders.expected_graphics_from_template`, which picks up the 5 new
  `__RACECAST_GRAPHICS__/Flag *.png` tokens automatically and copies
  `transparent-1080p.png` for any not present. So a league that hasn't designed flag
  graphics gets invisible (transparent) sources, never an error.

### 3. Relay flag-graphic controller (`src/relay/racecast-feeds.py`)

A small controller analogous to `SetupControl`:

- **State** `active ∈ {green, yellow, red, safety-car, virtual-safety-car, None}`,
  persisted to `runtime/<profile>/flag-graphic.json`.
- **Pure helpers** (unit-testable, no I/O):
  - `flag_graphic_source(value) -> "Flag Green" | … | None` — value→OBS source name.
  - `flag_graphic_intents(active) -> [(scene, source, enabled), …]` — the
    show/hide intents: for each of the 5 sources × {Stint, Splitscreen}, `enabled`
    is true only for the active source. `active=None` → all hidden.
  - Value validation against the fixed set `{green, yellow, red, safety-car,
    virtual-safety-car}` (+ accept the same aliases as the text flag where sensible:
    `sc`→safety-car, `vsc`→virtual-safety-car).
- **Apply**: walks the intents and calls `obs_ws.set_scene_item_enabled(scene, source,
  enabled)` for each. Best-effort — OBS unreachable or item-not-found yields a note,
  never raises (same contract as `/obs/source`).
- **Re-assert**: the persisted `active` is re-applied on relay start and on
  `obs refresh` / OBS (re)connect, so a scene switch or OBS restart preserves the flag.

### 4. Relay endpoints

New `/flag-graphic/…` namespace (separate from the text `/setup/…`):

- `GET /flag-graphic/data` — `{ "active": "<value>"|"" }` for panel highlight and
  Companion feedback.
- `GET /flag-graphic/set/<value>` — set active flag (validated), apply intents, persist.
- `GET /flag-graphic/clear` — clear (hide all), persist.

GET style mirrors `/setup/…` so Companion's Generic-HTTP module calls them directly;
tailnet/loopback is the trust boundary like the rest of the relay.

**Funnel / `/console`**: the same actions are wired into the existing director-gated
relay-mediated OBS control surface (alongside `/obs/scene`, `/obs/source`, …) so the
Director Panel reaches them over Funnel at `/console/panel`, director-gated. The
exact verb/route under the console mount follows whatever the panel's current OBS
controls do (so the front-end shares the same auth/`RC_API_BASE` shim).

### 5. Director Panel (`src/director/director-panel.html`)

A new, clearly-labelled **FLAG GRAPHIC** row, separate from the existing
flag/racecontrol `#condRow`: five pills (Green / Yellow / Red / SC / VSC) + **CLEAR**,
mutually exclusive, the active flag highlighted from `/flag-graphic/data`. Calls the
new endpoints.

### 6. Companion (`src/companion/racecast-buttons.companionconfig`)

FLAGS page, **row 1** (row 0 = the unchanged text buttons): five graphic buttons +
Clear, backed in the flag's color with a distinguishing prefix (e.g. `GFX\nGREEN`),
calling `GET /flag-graphic/set/<value>` and `/flag-graphic/clear`. The
`.companionconfig` is hand-maintained.

### 7. Docs & screenshots

- Update the wiki Assets / Sheet docs: list the 5 new Assets labels and the
  text-vs-graphic distinction.
- Per the CLAUDE.md rule, refresh the affected wiki screenshots **in the same change**:
  the Companion FLAGS page (`companion-screenshots` skill) and the Director Panel
  (`director-panel.png`, `wiki-screenshots` skill).

## Testing

- New pure-function unit tests: `flag_graphic_source`, `flag_graphic_intents`
  (mutual-exclusion across both scenes, `None` → all hidden), value/alias validation,
  and `/flag-graphic/*` endpoint routing + persistence round-trip. Follows the existing
  stdlib-only `tests/test_*.py` pattern (likely a new `tests/test_flag_graphic.py`,
  plus an assertion in `tests/test_racecast.py` / `tests/test_obsws.py` if the obs_ws
  seam is touched).
- `tools/build.py` verify covers the OBS-collection structure (tokenization, no
  secrets) for the 5 new sources.
- Manual UAT against a real league via the `racecast-local-uat` skill: confirm the
  Director Panel + Companion toggle the graphics in both Stint and Splitscreen, the
  active state survives a scene switch, and a missing asset shows nothing (transparent).

## Data flow summary

**Toggle → OBS (graphic):** Panel pill / Companion button →
`GET /flag-graphic/set/<value>` (or via `/console/panel` director-gated over Funnel) →
controller persists `active` + emits intents → `obs_ws.set_scene_item_enabled` shows
the chosen `Flag <X>` source and hides the other four in Stint **and** Splitscreen.

**Asset maintenance:** Sheet Assets row `Flag Green` (+ Drive PNG) →
`get-graphics.py` → `runtime/<profile>/graphics/Flag Green.png` → `setup-assets.py`
resolves the token into `GT_Endurance.import.json` (missing → transparent placeholder).
