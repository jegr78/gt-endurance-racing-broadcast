# HUD Brand-Name element + per-slot visibility toggle — design

Date: 2026-06-25

## Summary

Two related additions to the HUD overlay and its visual builder:

- **A — Brand-Name as a text element (per team).** Today each team has three HUD
  slots (`teamN-name`, `teamN-num`, `teamN-logo`); the manufacturer/brand is only
  shown as a *logo image* (resolved from `brandKey`). This adds three new editable
  **text** slots (`team1-brand`, `team2-brand`, `team3-brand`) that render the brand
  display name, sourced from a new Configuration-tab column **"Brand Name Override"**
  with a fallback to the existing brand text. The brand→logo mapping is unchanged.
- **B — Per-slot visibility toggle in the builder.** Today the only visibility
  control is `opacity` (0–1). This adds a real per-slot `visible` boolean property
  that compiles to `display: none`, plus an eye toggle in the builder. The new brand
  slots compose naturally with this: leagues that don't want the brand name simply
  hide those three slots.

## Background (current state)

- HUD slots are `data-edit`-marked elements in `src/obs/hud.html` (19 today). The
  pure compiler `src/scripts/overlay_build.py` (`extract_slots` + `compile_overlay_css`)
  turns a builder-owned `layout-<page>.json` into the served `<page>.css`. Per-slot
  property sets come from `data-edit-kind` (`KIND_BOX` / `KIND_TEXT`).
- Team data in the `/hud/data` payload is `{name, number, brandKey}`. The brand column
  in the **Configuration** tab is read by `parse_config_roster`
  (`src/relay/racecast-feeds.py`), which normalizes the brand text to a filename-safe
  `brandKey` via `asset_key()` — the **human-readable brand text is currently dropped**.
  `BRAND_TEXT_HEADERS = ("brand key", "brand name", "brand")` locates that column.
- The visual builder lives in `src/ui/control-center.html` (Shadow-DOM canvas:
  `ovBuildCanvas`, `ovApplyProp`, `ovSetProp`, `ovRenderPanel`). Slots are fetched via
  `GET /api/overlay/slots` (carries `sample` data for the canvas preview) and the layout
  round-trips via `GET`/`POST /api/overlay/layout` (handlers `overlay_slots_data`,
  `overlay_layout_read_data`, `overlay_layout_write_data` in `src/racecast.py`).
- The only existing visibility lever is `opacity` (validated 0–1 in
  `overlay_build.py`); there is **no** `visible`/`display`/`hidden` per-slot property.

## Feature A — Brand-Name text element (per team)

### Data layer (`src/relay/racecast-feeds.py`)

- Add `BRAND_NAME_OVERRIDE_HEADERS = ("brand name override",)`. Exact (whole-cell,
  case-insensitive) header match, like the other header sets — it does **not** collide
  with `BRAND_TEXT_HEADERS`'s `"brand name"` because matching is element equality, not
  substring.
- In `parse_config_roster`, additionally locate the override column (`oi`) and capture
  the verbatim brand text before normalization:
  - `brand_raw = row[bi].strip()` (when the brand column is present)
  - `brand_key = asset_key(brand_raw)` — unchanged logo mapping
  - `override = row[oi].strip()` (when the override column is present)
  - `brand_name = override or brand_raw`
  - roster entry becomes `{"number": ..., "brandKey": brand_key, "brandName": brand_name}`
- Propagate `brandName` everywhere a team dict is built or defaulted:
  - the roster→payload merge (`racecast-feeds.py:962`)
  - the second team-dict builder (`racecast-feeds.py:2898`)
  - the empty-team placeholders (`racecast-feeds.py:2777`, `:2871`) → `"brandName": ""`

The override only ever changes the **displayed text**; it never affects `brandKey` /
the logo. A team with no brand column and no override shows an empty brand slot.

### HUD page (`src/obs/hud.html`)

- Add three `data-edit`-marked **text** slots `team1-brand`, `team2-brand`,
  `team3-brand`, each near its team's logo/name. Default base-CSS position: directly
  **under the team name**; leagues reposition in the builder.
- `setTeam()` sets the brand element's `textContent` from `team.brandName`; an empty
  value adds the `.empty` class (same pattern as the logo `<img>`).
- These are plain text slots (no auto-fit). Styling (uppercase, color, font) is left to
  the base CSS default + per-league builder overrides.

### Compiler / builder (no code change required for extraction)

- `extract_slots` parses `data-edit` markers, so the three new slots appear in the
  builder automatically (slot count 19 → 22). No change to `overlay_build.py` for
  Feature A.
- `overlay_slots_data` (`src/racecast.py`) builds the canvas `sample`: add brand-text
  sample values for the three new slots so the builder canvas previews them with
  content.
- The shipped **demo** layout (`profiles/demo/overlay/layout-hud.json`) is **not**
  modified — base `hud.html` CSS covers the default look, so the sync guard
  `t_shipped_demo_overlay_css_matches_its_layout` stays green.

## Feature B — Per-slot visibility toggle

### Compiler (`src/scripts/overlay_build.py`)

- Add `"visible"` to `KIND_BOX` (inherited by `KIND_TEXT`) so every slot accepts it.
- Emit rule: a `visible: false` slot emits `display: none`; `visible: true` or absent
  emits **no** rule (default visible). A non-boolean value is dropped (consistent with
  the other validators that return `None`).
- `display: none` wins regardless of ordering; the override CSS is last in the cascade.

### Builder front-end (`src/ui/control-center.html`)

- Add an **eye toggle** to the property panel (`ovRenderPanel`) and the slot list. Off
  → set `visible: false` in `layout.slots[id]`; on → `visible: true` (or remove the key).
- **Canvas treatment must not be `display:none`.** A hidden slot stays on the canvas
  rendered **dimmed** (reduced opacity) with a **dashed outline** and a small "hidden"
  badge, so it remains selectable and can be toggled back on. Only the **compiled CSS**
  uses `display: none`. Special-case `visible` in `ovApplyProp` (it is not a direct
  `OV_CSSNAME` mapping) to apply the dimmed look on the canvas instead of hiding it.

## Data flow (Brand-Name)

```
Configuration tab (Brand + Brand Name Override columns)
  -> parse_config_roster()         # brandKey = asset_key(brand); brandName = override or brand
  -> /hud/data teams[i].brandName
  -> hud.html setTeam()            # teamN-brand textContent
  -> builder: extract_slots picks teamN-brand as editable text slots
```

## Error / edge handling

- Missing "Brand Name Override" column → fallback to verbatim brand text (graceful, no
  error); missing brand column too → empty brand slot (`.empty`).
- Non-boolean `visible` → dropped by the compiler (slot stays visible).
- Unknown slot ids / props remain silently dropped by `compile_overlay_css` (unchanged).

## Testing

- `tests/test_overlay.py`:
  - slot extraction count 19 → 22 and the three new ids present in document order
    (`t_ob_extract_slots_from_real_hud`).
  - `visible: false` → `display: none`; `visible: true` / absent → no display rule;
    non-bool dropped.
- Relay test (`tests/test_hud.py`):
  - `parse_config_roster` returns `brandName`; override precedence over verbatim brand;
    `brandKey` unaffected by the override; missing override falls back; missing brand
    column → empty `brandName`.
- Sample data: `/api/overlay/slots` `sample` carries brand text for the three new slots
  (extend the existing sample assertions).

## Out of scope (YAGNI)

- No auto-fit / dynamic shrink for the brand text (plain text slot).
- No global (non-team) brand element.
- No new Apps Script writeback for the override column — it is a read-only Sheet input
  (entered by the league admin), like the existing brand column.

## Documentation

- Refresh `src/docs/wiki/images/cc-overlay-builder.png` in the same change (visible
  builder change), via the `wiki-screenshots` skill (local dev build).
- Note the new "Brand Name Override" Configuration column on the Sheet-related wiki page
  (mechanism only — the league decides its content).

## Files touched

- `src/relay/racecast-feeds.py` — override header, `brandName` in roster + payload + placeholders.
- `src/obs/hud.html` — three brand text slots + `setTeam()` population.
- `src/scripts/overlay_build.py` — `visible` property + `display:none` emit.
- `src/racecast.py` — `overlay_slots_data` sample for the new slots.
- `src/ui/control-center.html` — eye toggle + dimmed canvas treatment for hidden slots.
- `tests/test_overlay.py`, `tests/test_hud.py` — coverage above.
- `src/docs/wiki/images/cc-overlay-builder.png` + Sheet wiki page — docs.
