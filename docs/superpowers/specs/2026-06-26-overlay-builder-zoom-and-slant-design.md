# Overlay builder: canvas zoom + slanted (parallelogram) edges

**Date:** 2026-06-26
**Status:** Design (approved scope, pre-implementation)
**Area:** Visual overlay builder — `src/ui/control-center.html` (builder JS/CSS) +
`src/scripts/overlay_build.py` (pure CSS compiler) + `tests/test_overlay.py`.
**Shipping:** a single PR / issue (both enhancements touch the same builder + canvas).

## Motivation

Two operator-facing gaps in the visual overlay builder (issue #114):

1. **No canvas zoom.** The builder canvas always auto-fits the panel width
   (`ovFitCanvas()` → `scale = wrapWidth / 1920`). There is no way to zoom in to
   position a small slot precisely, nor to step back to a fixed reference scale.

2. **No slanted edges.** Slots only support `rotation` (a full `transform: rotate()`).
   League designs like the ERF "Endurance Racing Federation" overlay use
   **parallelogram** boxes — slanted left/right edges with **upright** text (the
   1 / 2 / 3 position boxes, the top-right hashtag tab). The builder cannot produce
   that look today; a league must hand-write `customCss`.

Both are pure builder enhancements. The relay, the served pages, and the layout JSON
schema are otherwise unchanged (two new optional slot properties).

## Part 1 — Canvas zoom (builder UI only, no compiler change)

### Toolbar

Extend the existing `.ovgridbar` toolbar with a zoom group:

```
[ − ]  [ 100% ]  [ + ]   Fit · 50 · 100 · 150 · 200 %
```

(`−`/`+` walk the full ladder below; the labelled buttons are the common subset.)

- `−` / `+` step through the preset ladder.
- The percent readout shows the current effective zoom.
- Preset buttons set an exact zoom; **Fit** restores today's auto-fit behavior.
- Preset ladder: `fit, 25, 50, 75, 100, 125, 150, 200` (%). `100 %` = 1:1
  (one canvas pixel → one screen pixel).

### State + mechanics

- `ovState.zoom`: either the string `'fit'` (the default each time the builder
  opens) or a numeric factor (`1.0` = 100 %). **Session state only** — not persisted
  (the grid settings stay persisted as before; zoom resets to Fit on open). This is a
  deliberate YAGNI: Fit is the right default for almost every session.
- Rename/extend `ovFitCanvas()` → `ovApplyZoom()`:
  - `'fit'` → `scale = (wrap.clientWidth || 1) / OV_CANVAS_W` (unchanged math).
  - numeric → `scale = ovState.zoom`.
  - Always set `ovState.scale = scale` and `#ov-stage`'s `transform: scale(scale)`.
    Because `ovState.scale` carries the *effective* applied factor, the drag/resize
    math (`Math.round(delta / ovState.scale)` in `ovStartDrag` / `ovStartResize`)
    stays correct without change.
- The `ResizeObserver` already wired in `ovFitCanvas()` keeps refitting **only while
  in Fit mode**; in a numeric zoom a wrap resize does not change the scale (it just
  changes how much scrolls into view).

### Scrolling + background (the two real implementation details)

- `.ovcanvas-wrap` changes `overflow:hidden` → `overflow:auto` so a zoomed canvas
  (larger than the wrap) can scroll in both axes.
- **Do not rely on transformed-element overflow** to drive the scrollbars (engine
  quirks for an absolutely-positioned, `transform:scale`d child). Instead add a
  **sizer** element inside the wrap, sized to `1920·scale × 1080·scale`, that defines
  the scrollable area. `#ov-stage` stays `position:absolute; top:0; left:0` and is
  painted over the sizer. In Fit mode the sizer equals the wrap size → no scrollbars
  (today's look).
- **Move the `Overlay.png` backdrop from the wrap onto `#ov-stage`.** Today the
  background lives on `.ovcanvas-wrap` (`background-size:cover`); it only aligns
  because in Fit mode the scaled canvas exactly fills the wrap. Under zoom+scroll a
  wrap-anchored `cover` background would drift out of register with the slots. Setting
  it on the scaled stage (native `1920×1080`, `background-size:100% 100%`) makes it
  scale and scroll in lockstep with the slots — strictly more correct, and required
  for zoom. The existing cache-busting assignment
  (`…parentElement.style.backgroundImage = "url('/api/overlay/bg?t=…')"`) moves to the
  stage element accordingly.

### No compiler / no Python surface

Zoom is entirely builder JS/CSS. It does not touch `overlay_build.py`, the layout
JSON, or any served page, so there is no Python unit to add. It is verified manually
and via the refreshed builder screenshot (see Part 3).

## Part 2 — Slanted edges: two independent slot properties

Two **separate** properties so a designer can pick upright-text parallelograms,
sheared content, or both. Both are added to `KIND_BOX` in `overlay_build.py` (so they
are offered on **box and text** slots, since `KIND_TEXT = KIND_BOX + …`).

### 2a. `slant` — clip-path parallelogram (text stays upright)

- **Value:** a signed integer in **px** (consistent with every other layout prop; the
  whole canvas is a 1920-px space). Sign encodes direction. Default absent = no clip.
- **Geometry** (let `a = |slant|`):
  - `slant > 0` (leans `/`):
    `clip-path: polygon(a 0, 100% 0, calc(100% - a) 100%, 0 100%)`
  - `slant < 0` (leans `\`):
    `clip-path: polygon(0 0, calc(100% - a) 0, 100% 100%, a 100%)`
  - Both vertical edges slant by the same `a` → a true parallelogram. Top and bottom
    edges stay horizontal; text content is **unaffected** (no transform) → upright,
    exactly the ERF look.
- **Border note:** `clip-path` clips the border box, so the two slanted edges carry no
  border (the fill is cut through). This matches the design (the ERF number boxes have
  no border on the slanted edges). Documented, not a bug.
- **Clamp:** `-400 ≤ slant ≤ 400` px (a slot is at most a few hundred px wide; values
  beyond that would collapse or invert the polygon). Out-of-range / non-numeric →
  dropped (no `clip-path` emitted), like every other prop's validation.
- **Compiler:** a new branch in `_declaration` (or a dedicated `_clip_path_decl`)
  returning the `clip-path: …` string. `slant` joins `_PX_PROPS`-style handling but
  emits a `clip-path`, not a single px property — so it is special-cased like
  `textShadow` already is.

### 2b. `shear` — skewX (whole box + text sheared)

- **Value:** a signed number in **degrees** (like `rotation`). Default absent.
- **CSS:** `skewX(Kdeg)`.
- **Clamp:** `-89 ≤ shear ≤ 89` (skewX 90° is degenerate). Out-of-range / non-numeric
  → dropped.

### 2c. Combined transform (the one cross-cutting compiler change)

`shear` and `rotation` both compile to `transform`. Emitting two `transform`
declarations would let the second silently override the first. So **refactor the
rotation handling out of the per-prop `_declaration` path into a single combined
transform step** inside `_slot_rule` (and mirror it in the canvas):

- Collect the present pieces in a fixed order and emit one declaration:
  `transform: rotate(Rdeg) skewX(Kdeg)` (include only the parts that are set and valid).
- Order is fixed (`rotate` then `skewX`) so output is deterministic and unit-testable.
- When neither is set, no `transform` is emitted (today's behavior).
- `rotation` is removed from the generic `_declaration` switch; both `rotation` and
  `shear` are resolved together by the combined builder. `PROP_ORDER` keeps a slot
  entry for `shear` (placed next to `rotation`) so the prop is recognized/allowed, but
  the actual emission is the single combined transform.

### 2d. Live canvas mirror (`ovApplyProp` / `ovStyleSlot`)

The builder's same-origin canvas applies the standard properties inline and must mirror
the compiler so the preview matches the served CSS:

- `slant` → set `el.style.clipPath` to the same polygon (or clear it when absent),
  special-cased like `textShadow`/`visible` (not a simple `OV_CSSNAME` entry).
- `shear` + `rotation` → both must write the **combined** `el.style.transform`
  (`rotate(...) skewX(...)`). The current `rotation` branch in `ovApplyProp` (line
  ~3001, `el.style.transform = 'rotate(' + value + 'deg)'`) is replaced by a small
  `ovApplyTransform(el, ov)` helper that reads both `rotation` and `shear` from the
  slot's overrides and writes the merged transform — invoked from `ovStyleSlot` and
  whenever either prop changes via `ovSetProp`.
- Selection box + drag/resize are unaffected: `clip-path` and `skewX` do not change
  `offsetLeft/Top/Width/Height`, so `ovPositionSel()` keeps framing the layout box —
  identical to how `rotation` already behaves (the marquee does not rotate/shear).

### 2e. Property panel controls

In the box-property section of the panel add:

- **Slant** — a number input (px, signed) with a small direction affordance; range
  hinted `-400…400`. Live-applies via `ovSetProp(id, 'slant', …)`.
- **Shear** — a number input (deg, signed), range hinted `-89…89`.

Both appear for any slot whose `props` include them (i.e. all `box`/`text` slots).

## Part 3 — Tests, docs, packaging

### Tests (`tests/test_overlay.py`)

Pure-compiler additions (the builder JS has no Python unit, matching the existing
split):

- `slant > 0` → exact `clip-path: polygon(a 0, 100% 0, calc(100% - a) 100%, 0 100%)`.
- `slant < 0` → exact mirrored polygon.
- `slant` clamping (just inside / just outside ±400) and non-numeric rejection.
- `shear` → `transform: … skewX(Kdeg)`; clamp ±89; non-numeric rejection.
- **`rotation` + `shear` together → exactly one** `transform: rotate(Rdeg) skewX(Kdeg)`
  (the regression guard for the combine refactor).
- `rotation` alone still emits `transform: rotate(...)` unchanged (no regression).
- `slant`/`shear` are gated by a slot's allowed props (a slot without them in `props`
  drops the override), like every other property.

### Docs / screenshots (CLAUDE.md hard rule)

Both features change the **Overlay builder** Control Center surface, so
`src/docs/wiki/images/cc-overlay-builder.png` is stale and MUST be regenerated and
committed in the same PR via the **`wiki-screenshots`** skill (element shot of the
builder card, dev build so the version badge stays uniform). No other wiki image is
affected.

### Packaging

One PR / issue. Suggested commit slices for review:

1. Compiler: `slant` + `shear` + combined transform in `overlay_build.py`,
   with `tests/test_overlay.py` extended (TDD — failing tests first).
2. Builder: panel controls + `ovApplyProp`/`ovStyleSlot` mirror (clip-path + combined
   transform).
3. Builder: canvas zoom (toolbar, `ovApplyZoom`, sizer, background-on-stage).
4. Refresh `cc-overlay-builder.png`.

Run `python3 tests/test_overlay.py`, `python3 tools/lint.py`, and
`python3 tools/run-tests.py` before opening the PR (per repo norms).

## Out of scope (YAGNI)

- Per-corner chamfer / single-diagonal cut — `slant` is a full parallelogram only.
  Per-corner control can be a later addition if a design needs it.
- Persisting zoom across sessions — Fit-on-open is the sensible default.
- Counter-skew wrappers to keep text upright under `shear` — that is exactly what the
  separate `slant` (clip-path) property is for; `shear` deliberately shears everything.
- Keyboard zoom shortcuts / mouse-wheel zoom — preset buttons + `−`/`+` only for now.
