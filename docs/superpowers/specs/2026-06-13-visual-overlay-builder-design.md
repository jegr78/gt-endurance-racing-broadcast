# Visual Overlay Builder (WYSIWYG) for league overlays

**Date:** 2026-06-13
**Status:** Implemented (issue #114)
**Area:** Control Center (`src/ui/`), overlay assets (`src/obs/hud.html`,
`src/obs/timer.html`), a new pure overlay compiler (`src/scripts/overlay_build.py`),
profile runtime (`profiles/<name>/overlay/`)

## Problem

Per-league overlay customization today is **hand-written override CSS**
(`profiles/<name>/overlay/{hud,timer}.css`, served by the relay at
`/hud/override.css` / `/timer/override.css`, cascade-wins over the base page).
That is fine for web developers but they are the minority among broadcast
operators. A league owner who wants to move the stint banner, recolor the race
control bar, or drop in a league font has to write CSS by hand.

We want a **WYSIWYG builder** in the Control Center: drag/resize the known
overlay elements on a canvas, style them through a property panel, preview the
result, and have the league's override CSS generated for them — without
touching the relay's live data binding or render path.

## Key insight: the overlay is a fixed set of data-bound slots, not free HTML

`hud.html` renders exactly 10 known, data-bound elements (`#stint`, `#session`,
`#streamer`, `#round-top`, `#round-flag`, `#round-country`, `#team0..2`,
`#race-control`), each filled live from `/hud/data`. `timer.html` renders one
(`#clock`). The customization that varies per league is **position and style of
these known slots**, never the structure or the data binding.

This rules out a generic page builder (e.g. GrapesJS): it is built to produce
arbitrary static HTML, it is heavyweight, and forcing it onto fixed data-bound
slots fights its grain and would break the live binding. The right tool is a
**purpose-built positioner that emits the same `override.css` we already
serve** — at its core a CSS generator for selectors that already exist.

## Architecture (additive — relay untouched)

```
hud.html / timer.html   editable elements carry  data-edit="<Label>"
   (markup is the ONLY slot source — a new selector becomes editable
    automatically, no second list to keep in sync)
        │  builder scans the page, derives the slot list
        ▼
profiles/<name>/overlay/layout-<page>.json   ← the builder OWNS this (source of truth)
        │  pure compiler  compile_overlay_css(layout, slots) -> str
        ▼
profiles/<name>/overlay/hud.css         ← GENERATED; the exact file the relay
profiles/<name>/overlay/timer.css         already serves at /<page>/override.css
```

### Why this fits the existing system

- The relay already serves `override.css` **read fresh per request** from
  `--overlay-dir` (`read_overlay_css`, `racecast-feeds.py`). The builder writes
  that file; the relay needs **zero changes**.
- `hud.css`/`timer.css` (as `/hud/override.css`, `/timer/override.css`) are in
  `OBS_PAGE_PATHS`, so the **existing hash gate auto-triggers the OBS refresh**
  when the builder saves. "Apply in OBS" already exists in the Control Center.
- The compiler is a **pure function** → unit-testable in the repo's stdlib test
  style (`tests/test_overlay.py`).

## Source of truth: `data-edit` markers (single source, no drift)

Editable elements in `hud.html` / `timer.html` carry a marker attribute, e.g.:

```html
<div id="stint" class="el white" data-edit="Stint banner"></div>
```

- The marker's value is the **human label** shown in the builder.
- An optional `data-edit-props` (comma list) restricts which property groups
  apply to that slot (default: the full text-slot set). Team-name slots expose
  the auto-fit bounds (`teamNameMax`/`teamNameMin` → `--team-name-max`/`-min`)
  instead of a fixed font size, so the builder never breaks the shrink-to-fit
  logic; the image-only `#round-flag` exposes position/size only.

This is the explicit decision against a hardcoded slot list or a separate
manifest: those would be a **second place to maintain** when a new element is
added to `hud.html` — the same anti-drift principle as the duplicated
`load_dotenv` copies. A new global element gets a new selector in `hud.html`
plus a `data-edit` marker, and the builder offers it automatically.

> Decorative free-floating elements are **out of scope**: the builder only ever
> edits the known marked slots.

## Data model: `layout-<page>.json`

```jsonc
{
  "version": 1,
  "page": "hud",
  "slots": {
    "stint":        { "left": 800, "top": 30, "fontSize": 44, "color": "#fff",
                      "fontFamily": "League", "align": "center" },
    "race-control": { "background": "#222a2f" }
    // only CHANGED properties per slot; unset = base look
  },
  "fonts": ["League.woff2"],      // uploaded fonts referenced by the layout
  "customCss": "/* raw CSS appended verbatim, last */"
}
```

- Keyed by element id (without `#`). Only overridden properties are stored;
  anything unset falls through to the base page.
- One file per page (`layout-hud.json`, `layout-timer.json`).
- **`customCss`** is appended verbatim after the generated rules — the pro
  escape hatch and the **migration sink** (see below).

## Compiler: `compile_overlay_css(layout, slots) -> css`

`src/scripts/overlay_build.py` (pure, stdlib-only). Maps each slot's properties
to CSS declarations for `#<id>` via a fixed, documented table (e.g.
`fontSize: 44` → `font-size: 44px`), emits `@font-face` blocks for referenced
fonts (family name = the file stem, served by the relay at
`/overlay/fonts/<file>`), then appends `customCss`. This table is the single
canonical CSS source; the live canvas applies the same standard CSS properties
as inline styles, so there is no second CSS generator to drift.

Unit tests (`tests/test_overlay.py`): each property group compiles to the
expected declaration; fonts emit `@font-face`; `customCss` lands last; empty
layout → empty (base look preserved); unknown slot id is ignored; `data-edit`
slot extraction from the real base pages; migration import of existing CSS.

## Builder UI (Control Center, `src/ui/`)

### Same-origin canvas

The Control Center (8089) and the relay/HUD (8088) are **different origins**; a
cross-origin iframe cannot be DOM-manipulated. Resolution: **the Control Center
renders the canvas itself** from the base page's `<style>` + slot markup
(fetched via `/api/overlay/slots`), inside a Shadow-DOM host (style isolation),
filled with **sample data** and the league's `Overlay.png`
(`/api/overlay/bg`) as the background layer. The canvas is therefore same-origin
and fully manipulable, and the operator can lay out offline with the relay down.
Live verification stays the existing path: "Apply in OBS" + `/hud/preview`.

### Interaction (vanilla pointer events — no vendored dependency)

Decided against vendoring a UMD drag/resize lib (Moveable/interact.js): the repo
is deliberately dependency-free (pure stdlib, no npm, no vendoring). A small
vanilla **pointer-events** implementation (drag the slot, eight resize handles)
is enough for absolutely-positioned slots and keeps the zero-dependency posture
(no third-party code through gitleaks/CodeQL).

- Drag/resize a slot → its geometry updates in the in-memory layout model and as
  an inline style on the element (live preview).
- A property panel (right) for the focused slot: position, size, font
  size/family, color, background, alignment — gated by the slot's
  `data-edit-props`.
- Page switch HUD ⇄ Timer (symmetric; `#clock` is the timer's single slot).
- Save → POST the model; the server compiles canonical `override.css`, writes
  `layout-<page>.json` + `<page>.css` atomically, the hash gate refreshes OBS.

### Fonts (in scope)

- Upload endpoint writes into `profiles/<name>/overlay/fonts/`, validating name +
  type against the relay's existing `FONT_NAME_RE` / `FONT_CTYPES` whitelist
  (the constants are duplicated in `overlay_build.py` and pinned byte-identical
  to the relay's by a cross-check test, the repo's anti-drift pattern).
- The builder lists available fonts; a font dropdown per text slot plus a global
  body font. The compiler emits the `@font-face` blocks for referenced fonts.

## Endpoints (Control Center)

Extend the existing overlay surface (`/api/overlay`):

- `GET  /api/overlay/layout?page=hud|timer` → `layout-<page>.json` (or an empty
  model; first read of a profile with hand-written `<page>.css` and no layout
  imports that CSS into `customCss`).
- `POST /api/overlay/layout` → validate, compile, write `layout-<page>.json` +
  `<page>.css` atomically (mirrors today's `overlay_write_data` atomic write).
- `GET  /api/overlay/slots?page=hud|timer` → slot list + labels + allowed props +
  base `<style>` + slot markup + sample data, derived from the marked base page.
- `GET  /api/overlay/fonts` / `POST /api/overlay/fonts?name=<file>` → list /
  upload fonts.
- `GET  /api/overlay/bg` → the active profile's `runtime/<profile>/graphics/Overlay.png`.
- `GET  /api/overlay/font/<name>` → an uploaded font, for canvas preview.

## Migration & coexistence with hand-written CSS

The builder **owns** `hud.css`/`timer.css` (they are generated). To not silently
clobber an existing hand-written override:

- On first builder read for a profile, if `<page>.css` is non-empty and no
  `layout-<page>.json` exists, import the existing CSS **verbatim into
  `customCss`** (never reverse-parsed) and start with an empty slot map. Nothing
  is lost; the operator can then visually move slots, and their changes compile
  **above** the preserved custom block.
- Profiles that never use the builder keep hand-editing CSS exactly as today.

## Out of scope (YAGNI)

- Decorative / free-floating elements not present in the base page.
- Editing the Overlay.png frame itself (a separate OBS graphic).
- Parsing arbitrary hand-written CSS back into the visual model (preserved
  verbatim via `customCss`).
- Animations / timelines. Position + static style only for v1.
