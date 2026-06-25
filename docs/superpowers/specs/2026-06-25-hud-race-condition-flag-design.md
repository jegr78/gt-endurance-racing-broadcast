# HUD race-condition flag (Yellow / Safety Car / FCY / …) — design

Date: 2026-06-25

## Summary

Add a dedicated, **color-coded** race-condition **flag** element to the HUD —
Green / Yellow / Double Yellow / Safety Car / Full Course Yellow / Code 60 / Red /
Checkered — that is hidden unless activated and controllable from the **Google Sheet**,
the **Director Panel**, and **Web/Companion buttons**. It is a **separate** element from
the existing Race Control banner (both can show at once), and it mirrors the Race
Control Setup-field plumbing 1:1, with one addition: the value drives a per-state CSS
color via a `data-state` attribute, with shipped defaults for the canonical states and
a neutral fallback for anything else.

Decisions locked in brainstorming: color-coded per state; separate element (not folded
into Race Control); the flag is **NOT** auto-cleared on stint handover (a track
condition outlives a commentator change); the vocabulary lives in the Sheet and is
fully league-editable (default colors ship for the canonical 8 states).

## Background — the Race Control template

Race Control is a Setup field whose end-to-end chain we mirror (verified anchors):
- **Sheet:** Overlay tab row (current value) + Configuration tab column (dropdown
  vocabulary). `OVERLAY_LABELS` (`racecast-feeds.py:783`) maps the row label → key;
  `VOCAB_COLUMNS` (`:916`) maps the vocab key → Configuration column.
- **Relay:** `SETUP_FIELDS` (`:2944`) maps url-field → (Sheet header, HUD key);
  `build_hud_data` (`:989`) emits the HUD key; `HudSource.EMPTY` (`:2790`) seeds it;
  `SetupControl.set_field` (`:2988`) validates against the vocab, sets an optimistic
  30 s override, and pushes the `{"action":"setup","fields":{<header>:<value>}}` webhook.
  Endpoints (generic): `/setup/set/<field>/<value>`, `/setup/clear/<field>`,
  `/setup/data`.
- **HUD** (`hud.html`): `#race-control` slot, hidden when empty via `.empty`
  (`setText` toggles it), value from `/hud/data`.
- **Panel** (`director-panel.html`): the `SETUP_FIELDS` JS array (`:1154`) data-drives a
  dropdown; the vocab fills its options.
- **Companion** (`racecast-buttons.companionconfig`): Generic-HTTP GET buttons hit
  `/setup/set/racecontrol/<value>` and `/setup/clear/racecontrol`.

Two Race-Control specifics the flag deliberately **diverges** from:
- **Empty allowed:** `set_field` (`:2996`) gates empty with `key != "racecontrol"`. The
  flag must also be clearable → the gate becomes `key not in ("racecontrol", "flag")`.
- **Handover clear:** the `/next` endpoint (`:5157`) clears Race Control on a real
  `obs_cut` (`setup_ctl.set_field("racecontrol","")`). The flag is **not** in that path,
  so it persists across handovers automatically — a regression test will assert this.

## Naming (no collision with the country flag)

The HUD already has a *country* flag (`d.round.flagKey`, slot `#round-flag`, `flags/`
assets). To avoid confusion this feature uses:
- url / vocab / overlay-key: **`flag`**; Sheet header (Configuration column + Overlay
  row label): **`Flag`**; HUD data key: **`flag`** (top-level `d.flag` — no clash with
  the nested `d.round.flagKey`).
- HUD **slot id: `flag-status`** (data-edit label "Flag status") — visually distinct
  from `#round-flag`.
- color selector: a **`data-state="<slug>"`** attribute on `#flag-status`.

## Design

### Relay (`src/relay/racecast-feeds.py`)

- `OVERLAY_LABELS`: add `"flag": "flag"` (Overlay tab row "Flag").
- `VOCAB_COLUMNS`: add `"flag": "flag"` (Configuration column "Flag").
- `SETUP_FIELDS`: add `"flag": ("Flag", "flag")`.
- `build_hud_data`: add `out["flag"] = overlay.get("flag", "")`.
- `HudSource.EMPTY`: add `"flag": ""`.
- `set_field` empty gate: `if not value and key not in ("racecontrol", "flag")`.
- No change to `/next`: the flag is intentionally absent from the cut-clear path → it
  persists across handovers.

### HUD page (`src/obs/hud.html`)

- New text slot: `<div id="flag-status" class="el" data-edit="Flag status"
  data-edit-kind="text"></div>`, builder-positionable, hidden when empty (`.empty`).
- `tick()`: a small `setFlag(id, value)` helper sets `textContent`, toggles `.empty`,
  and sets `el.dataset.state = flagSlug(value)` (empty → remove the attribute).
  `flagSlug` = lowercase, non-alphanumeric runs → `-`, trimmed (e.g. "Full Course
  Yellow" → `full-course-yellow`, "Safety Car" → `safety-car`), then resolved through a
  small **abbreviation alias map** so common short forms land on a canonical slug:
  ```javascript
  const FLAG_ALIASES = {
    "sc": "safety-car",
    "fcy": "full-course-yellow",
    "vsc": "full-course-yellow",   // virtual safety car reuses the FCY amber treatment
  };
  ```
  (A league wanting a distinct VSC look adds a `customCss` rule.) Unaliased slugs pass
  through unchanged.
- Base CSS: a neutral default `#flag-status { … }` plus per-state colors keyed on the
  canonical slugs:
  - `green-flag` → green bg, light text
  - `yellow-flag` → amber bg, dark text
  - `double-yellow` → amber bg, dark text
  - `safety-car` → white/light bg, dark text
  - `full-course-yellow` → amber bg, dark text (distinct accent from yellow-flag)
  - `code-60` → orange bg, dark text
  - `red-flag` → red bg, light text
  - `checkered-flag` → dark bg, light text
  Unknown slugs fall through to the neutral `#flag-status` default. Per-state selectors
  are `#flag-status[data-state="…"]` (id+attr specificity beats a builder-set base
  `#flag-status { background }`, so positioning/restyling in the builder never clobbers
  the active-state color). Leagues add/override colors via the per-league overlay
  `customCss` escape hatch.

### Director Panel (`src/director/director-panel.html`)

- Add `["flag","FLAG"]` to the `SETUP_FIELDS` JS array → the dropdown auto-generates and
  fills from the vocab.
- Include the empty option for `flag` like Race Control: the `setupPoll` option builder
  `(key === "racecontrol" ? [""] : [])` becomes `(["racecontrol","flag"].includes(key)
  ? [""] : [])`, so "— none —" clears the flag. (No separate clear button needed.)

### Companion / Web buttons (`src/companion/racecast-buttons.companionconfig`)

- Add a row/group of Generic-HTTP buttons mirroring the Race Control ones:
  `/setup/set/flag/<state>` for the common states (Green, Yellow, Safety Car, Full
  Course Yellow, Red) plus `/setup/clear/flag`. Re-export via `racecast export companion`
  and re-strip the password (`tools/strip_companion_pass.py` / `build.py` defends).

### Default vocabulary (league-editable)

The Configuration **Flag** column is the source of truth and is fully editable by the
league (blank rows skipped, order preserved, like Race Control). The **shipped default
colors** cover the canonical 8 states above; a league-added state whose wording does not
normalize to a canonical slug shows the neutral default (and can be colored via the
per-league overlay customCss). The default set seeded in the sample Sheet docs:
Green Flag, Yellow Flag, Double Yellow, Safety Car, Full Course Yellow, Code 60, Red
Flag, Checkered Flag.

## Data flow

```
Configuration tab "Flag" column (vocab)  +  Overlay tab "Flag" row (current value)
  -> parse_config_vocab / parse_overlay           # vocab["flag"], overlay["flag"]
  -> build_hud_data -> /hud/data d.flag
  -> hud.html setFlag("flag-status", d.flag)       # text + data-state slug -> color
Panel dropdown / Companion button -> /setup/set/flag/<v> | /setup/clear/flag
  -> SetupControl.set_field -> optimistic override + Sheet webhook
```

## Error / edge handling

- Value not in the vocab → `set_field` rejects (existing behavior).
- Empty value → allowed (clears the flag), now including `flag`.
- Unknown/un-themed state → neutral default style (no error).
- Webhook unconfigured → `set_field` returns the standard error (existing).
- Handover: flag persists (not in the `/next` cut-clear path).

## Testing

- `tests/test_hud.py`: `parse_overlay`/`build_hud_data` carry `flag`; `HudSource.EMPTY`
  has `flag`; vocab includes `flag` from a Configuration "Flag" column.
- `tests/test_setup.py`: `flag` in `SETUP_FIELDS`; `/setup/set/flag/<v>` + the webhook
  payload `{"Flag": v}`; `/setup/clear/flag` allowed (empty); a value not in the vocab
  rejected; **flag survives `/next` with `obs_cut:true`** (mirrors the racecontrol
  handover tests, asserting the opposite for flag); `/setup/data` exposes `options.flag`.
- The `flagSlug` normalization is front-end JS (no JS unit harness) → verified live in a
  browser during review (the controller's Playwright pass), like the builder features.

## Documentation

- Refresh `src/docs/wiki/images/director-panel.png` (new FLAG dropdown) and the
  Companion button board `companion-page*.png` (new flag buttons) via the
  `wiki-screenshots` / `companion-screenshots` skills. The overlay builder gains a
  `flag-status` slot → refresh `cc-overlay-builder.png` if the slot is shown.
- Document the new Configuration **Flag** column + the canonical default states/colors
  on the Sheet wiki page (`Sheet-Template.md` / `Configuration.md`) — mechanism only;
  the league owns the vocabulary.

## Out of scope (YAGNI)

- No flag **graphics/icons** (text + color only).
- No per-state color pickers in the visual builder (colors are base-CSS defaults +
  per-league customCss; the builder controls the slot's position/size/base style).
- No new public/Funnel surface — the flag rides the existing `/setup/*` (tailnet) chain
  exactly like Race Control.

## Files touched

- `src/relay/racecast-feeds.py` — `OVERLAY_LABELS`, `VOCAB_COLUMNS`, `SETUP_FIELDS`,
  `build_hud_data`, `HudSource.EMPTY`, `set_field` empty gate.
- `src/obs/hud.html` — `#flag-status` slot, base + per-state CSS, `setFlag`/`flagSlug` in `tick()`.
- `src/director/director-panel.html` — `SETUP_FIELDS` array entry + empty-option include.
- `src/companion/racecast-buttons.companionconfig` — flag buttons (+ re-export/strip).
- `tests/test_hud.py`, `tests/test_setup.py` — coverage above.
- `src/docs/wiki/images/{director-panel,companion-page*,cc-overlay-builder}.png`
  (+ slides copies) + Sheet wiki page — docs.
