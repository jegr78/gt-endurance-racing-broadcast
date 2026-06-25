# Visual builder — Bold / Italic font controls — design

Date: 2026-06-25

## Summary

Add two per-slot typography controls to the visual overlay builder that are
currently missing: **Bold** (`font-weight`) and **Italic** (`font-style`). Both
follow the existing enum-property pattern (`textTransform`, `align`, `valign`,
`borderStyle`) exactly — a CSS-name map + a validated `_declaration` branch in the
pure compiler, plus an `ovSelectField` dropdown in the builder panel. CSS-only; no
font-pipeline change.

## Background (current state)

- Text slots' property set is `KIND_TEXT` in `src/scripts/overlay_build.py:59`
  (`fontSize, lineHeight, letterSpacing, fontFamily, color, align, valign,
  textTransform, textShadow` + the `KIND_BOX` geometry/box props). There is **no**
  `fontWeight` or `fontStyle` property today.
- Enum props are compiled with a two-step pattern: look the value up in a mapping
  dict, emit only on a hit, drop unknown values (the injection gate). Example
  (`overlay_build.py:254`):
  ```python
  if prop == "textTransform":
      mapped = _TEXT_TRANSFORM.get(value) if isinstance(value, str) else None
      return f"text-transform: {mapped}" if mapped else None
  ```
- The builder front-end (`src/ui/control-center.html`) mirrors the compiler maps in
  `OV_CSSNAME` (`:2775`) and builds select controls via `ovSelectField` (`:3128`),
  used for `borderStyle`/`align`/`valign`/`textTransform` in `ovRenderPanel`
  (`:3275-3295`). `ovApplyProp` (`:2923`) applies a prop to the canvas; props that
  are a plain CSS name with a string value fall through its generic
  `el.style.setProperty(name, value)` path — no special-case needed.
- Base HUD CSS already uses both axes: `.el { font-weight: 700 }`
  (`hud.html:16`), `#session`/`#round-top { font-style: italic }`. A builder override
  is loaded last via the per-league `<link>` and wins by cascade/specificity.
- **Font pipeline note:** self-hosted Google fonts download a **single** weight
  (700/bold default — `overlay_build.google_font_css_url`, `tools/fetch-fonts.py`),
  emitted as one weightless `@font-face`. Consequence: `font-weight: bold` renders
  bold (real face or synthetic); going *lighter* than a self-hosted font's one face
  does not truly de-weight (the browser has no lighter face). This is an accepted,
  documented limitation — broadcast overlays tolerate synthetic weight/oblique.

## Design

### Compiler (`src/scripts/overlay_build.py`)

- Add `"fontWeight"` and `"fontStyle"` to `KIND_TEXT` (text-only — not in
  `KIND_BOX`, since weight/style are meaningless on an image/box slot).
- Add them to `PROP_ORDER` (right after `fontFamily`, before `color`).
- Add two enum maps near `_TEXT_TRANSFORM`:
  ```python
  _FONT_WEIGHT = {"normal": "normal", "bold": "bold"}
  _FONT_STYLE = {"normal": "normal", "italic": "italic"}
  ```
- Add two `_declaration` branches mirroring `textTransform`:
  ```python
  if prop == "fontWeight":
      mapped = _FONT_WEIGHT.get(value) if isinstance(value, str) else None
      return f"font-weight: {mapped}" if mapped else None
  if prop == "fontStyle":
      mapped = _FONT_STYLE.get(value) if isinstance(value, str) else None
      return f"font-style: {mapped}" if mapped else None
  ```
- **Scope:** only `normal`/`bold` and `normal`/`italic` (no numeric weight scale,
  no `oblique`) — YAGNI, and sidesteps the de-weight confusion. Unknown values are
  dropped (no injection), like every other enum.

### Builder front-end (`src/ui/control-center.html`)

- Add to `OV_CSSNAME`: `fontWeight: 'font-weight', fontStyle: 'font-style'`.
- In `ovRenderPanel`, near the font-family block, add two `ovSelectField` controls
  (gated by `has('fontWeight')` / `has('fontStyle')`):
  ```javascript
  if (has('fontWeight')) panel.appendChild(ovSelectField('fontWeight', 'Font weight',
    [{v:'', t:'— default —'}, {v:'normal', t:'Normal'}, {v:'bold', t:'Bold'}], ov));
  if (has('fontStyle')) panel.appendChild(ovSelectField('fontStyle', 'Font style',
    [{v:'', t:'— default —'}, {v:'normal', t:'Normal'}, {v:'italic', t:'Italic'}], ov));
  ```
- No `ovApplyProp` change: both are in `OV_CSSNAME`, non-px, non-special → the
  generic `setProperty('font-weight'|'font-style', value)` path applies them live on
  the canvas. `ovStyleSlot` already iterates `OV_CSSNAME`, so load/reset restore them.

### Cascade / rendering

- A builder-set `#slot { font-weight: bold }` overrides the base `.el{font-weight:700}`
  (id beats class); `— default —` (empty) deletes the override → base wins. Same for
  `font-style` over `#session`/`#round-top`.
- `bold`/`italic` always render (real face when the self-hosted/system font provides
  one, synthetic otherwise). `normal` may not de-weight a single-weight self-hosted
  font — documented, acceptable.

## Error / edge handling

- Unknown enum values dropped by the compiler (slot keeps base look).
- `''` deletes the slot prop (reverts to base) via the existing `ovSetProp` delete-set.
- No demo/example overlay files change → the `t_shipped_demo_overlay_css_matches_its_layout`
  sync guard stays green.

## Testing

- `tests/test_overlay.py`:
  - `fontWeight: bold` → `font-weight: bold`; `fontStyle: italic` → `font-style: italic`.
  - unknown values dropped (`fontWeight: "900"` / `"evil; }"` → no rule;
    `fontStyle: "oblique"` → no rule, since only `normal`/`italic` are allowed).
  - `fontWeight`/`fontStyle` are members of `KIND_TEXT` and **not** of `KIND_BOX`.

## Documentation

- Refresh `src/docs/wiki/images/cc-overlay-builder.png` (+ the slides copy) in the
  same change — the builder panel gains two selects (`wiki-screenshots` skill, local
  dev build).

## Out of scope (YAGNI)

- No numeric weight slider, no `oblique`, no per-weight font downloads / multi-weight
  `@font-face` pipeline. Bold/Italic are CSS-only.

## Files touched

- `src/scripts/overlay_build.py` — `_FONT_WEIGHT`/`_FONT_STYLE` maps, `KIND_TEXT`,
  `PROP_ORDER`, two `_declaration` branches.
- `src/ui/control-center.html` — `OV_CSSNAME` entries + two `ovRenderPanel` selects.
- `tests/test_overlay.py` — enum + membership tests.
- `src/docs/wiki/images/cc-overlay-builder.png` (+ slides copy) — refreshed screenshot.
