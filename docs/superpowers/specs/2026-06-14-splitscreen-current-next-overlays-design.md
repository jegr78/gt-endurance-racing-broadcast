# Splitscreen current/next feed labels

**Date:** 2026-06-14
**Status:** Approved — ready for implementation
**Issue:** #129 (OBS: Driver Swap Scene: Add current/next overlays)
**Area:** new `src/obs/splitscreen.html`, OBS collection
(`src/obs/GT_Endurance.json`), relay (`src/relay/racecast-feeds.py`),
localizer (`src/setup-assets.py` only if a new tokenized source needs handling),
tests (`tests/test_overlay.py`, `tests/test_racecast.py`).
**Precedes:** #130 (POV box name) reuses the grey-box / white-text label look
established here.

## Problem

The **Splitscreen** scene (used for a driver swap / handover) shows two
commentator feeds side by side — **Feed A is always the left half**, **Feed B
always the right** (in the collection: `Feed A` at pos (0,270), `Feed B` at
(960,270), each a 960×540 band, vertically centred in the 1920×1080 frame).
Nothing on screen tells the viewer which feed is **currently on air** and which
is **about to take over**. The producer wants a small default overlay box on the
top-right corner of each feed labelling them **CURRENT** / **NEXT**, with the
relay deciding which side is which.

## Decisions (confirmed with the producer)

- **Dedicated relay-served overlay page**, served as its **own OBS browser
  source that lives only in the Splitscreen scene.** Rejected: putting the boxes
  in the existing `hud.html`, because the single existing browser source
  (`HUD Overlay` → `/hud`) is present in *both* the `Stint` (single-feed) and
  `Splitscreen` scenes, and a page cannot know which OBS scene is live — so the
  boxes would wrongly appear over the single-feed scene. A separate source scoped
  to the Splitscreen scene solves this geometrically.
- **Box text is role only: `CURRENT` / `NEXT`.** No streamer name — the on-air
  streamer is already shown in the HUD lower-third.
- **Placement:** each box sits at the **top-right of its own feed, flush-right**
  (left box flush to the centre seam at x≈960; right box flush to the screen edge
  at x≈1920) with a **slight overhang above the feed's top edge** (y≈270). No
  crossing of the centre seam. Confirmed against a mockup.
- **Look:** grey rectangle, white text, rounded corners, subtle drop shadow.
- **Per-league restyling via override CSS only.** `splitscreen` joins
  `OVERLAY_PAGES`; the relay serves `/splitscreen/override.css` from
  `profiles/<name>/overlay/splitscreen.css` (same mechanism as `/hud`). The path
  joins `OBS_PAGE_PATHS` so the auto-refresh hash reloads the source on edit.
  **No visual drag-and-drop builder page for splitscreen** in this issue —
  positions and text are fixed, so it would be wasted scope (YAGNI). May follow
  later.

## Architecture

### New page: `src/obs/splitscreen.html`
A transparent full-frame (1920×1080) page, structured like `hud.html`:
- Two absolutely-positioned boxes anchored to the fixed feed geometry:
  - **Left box** (`#splitCur`/`#splitNext` resolved by role at runtime): right
    edge at x=960 (centre seam), top overhanging slightly above y=270.
  - **Right box**: right edge at x=1920 (screen edge), top overhanging slightly
    above y=270.
  - Both boxes use stable element IDs/classes (e.g. `#split-left`, `#split-right`,
    `.split-label`) that a hand-written per-league `profiles/<name>/overlay/splitscreen.css`
    overrides directly. **No `data-edit` markers** (those are builder-only) and
    **no entry in `overlay_build.py`'s page config** — verified that `OVERLAY_PAGES`
    is consumed solely by the relay's `read_overlay_css()`, while the Control
    Center builder enumerates its own page config, so adding `"splitscreen"` to
    `OVERLAY_PAGES` serves the override CSS without creating a builder tab.
- A base `<link>` to `/splitscreen/override.css` last in `<head>` (cascade-wins
  override, same pattern as `hud.html`).
- Polls `GET /splitscreen/data` (reuse the HUD poll interval default); on each
  tick it assigns the **CURRENT** label to the box over the live feed and
  **NEXT** to the other, and hides the **NEXT** box when `next_active` is false.
  No manual reloads; anything that must survive a reload is server-side.

### Relay endpoint: `GET /splitscreen/data`
Returns the minimal state the page needs:
```json
{ "current": "A", "next_active": true, "mode": "race" }
```
- `current`: `"A"` or `"B"`, from `Relay.live_feed()`. Maps directly to
  left/right because Feed A is always left, Feed B always right.
- `next_active`: false in qualifying mode (only Feed A is used; Feed B idles), so
  the page hides the NEXT box. True in race mode.
- `mode`: `"race"` | `"qualifying"` (from `Relay.mode`), for clarity/debug and
  future use.

The relay already exposes `live_feed()` / `live_after_next()` and `mode`; this
endpoint is a thin read-only projection. Unauthenticated like the rest of the
relay (tailnet is the trust boundary).

### Overlay-page registration
- Add `"splitscreen"` to `OVERLAY_PAGES` so `read_overlay_css()` serves
  `/splitscreen/override.css` from the active `--overlay-dir`.
- Add `/splitscreen` and `/splitscreen/override.css` to the served routes.
- Add both `/splitscreen` and `/splitscreen/override.css` to `OBS_PAGE_PATHS`
  (the refresh-hash set) so editing either advances `runtime/obs-pages.hash` and
  OBS auto-reloads the source on `relay start` / `obs refresh`.

### OBS collection: `src/obs/GT_Endurance.json`
- Add a new browser source **`Splitscreen Labels`** → `http://127.0.0.1:8088/splitscreen`,
  full-frame (pos (0,0), bounds 1920×1080), placed **only in the `Splitscreen`
  scene**, layered above the feeds (and above/below `HUD Overlay` as appropriate —
  the boxes are top-of-frame, the HUD is lower-third, so they don't collide).
- The URL is the fixed loopback (no token needed; same as the existing
  `HUD Overlay` source). Existing leagues pick the new source up on their next
  `racecast setup` / collection re-import (the setup is not live yet, so a
  scene-layout change is acceptable — consistent with the #153 timer-merge spec).

## Data flow (handover)

1. Producer is in the Splitscreen scene during a swap. `live_feed()` = the feed
   on air now → its box shows **CURRENT**; the other box shows **NEXT**.
2. Producer presses `/next` (handover). `live_feed()` flips; the page's next poll
   re-labels the boxes live (no reload).
3. In qualifying mode, `next_active:false` → only the CURRENT box (over Feed A)
   shows.

## Testing (TDD — test first)

`tests/test_racecast.py` / `tests/test_overlay.py`:
- `/splitscreen/data` returns `current:"A"` when Feed A is live and `"B"` when
  Feed B is live (drive via the relay's feed indices like the existing status
  tests).
- `next_active` is `false` in qualifying mode, `true` in race mode.
- `"splitscreen"` is in `OVERLAY_PAGES`.
- `/splitscreen` and `/splitscreen/override.css` are in `OBS_PAGE_PATHS`.
- `/splitscreen/override.css` returns the league file's bytes when present and an
  empty body when absent (mirror the existing `/hud/override.css` test).
- The OBS collection contains a `Splitscreen Labels` browser source pointing at
  `http://127.0.0.1:8088/splitscreen`, present in the `Splitscreen` scene only.

## Out of scope / follow-ups

- Visual drag-and-drop builder page for splitscreen (positions/text are fixed).
- Streamer names in the boxes (#130 handles the POV name; splitscreen stays
  role-only).
- Any change to single-feed (`Stint`) scene labelling.
