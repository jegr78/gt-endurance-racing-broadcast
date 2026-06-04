# Standby Cover — incident hold graphic in the Stint scene

**Date:** 2026-06-04
**Status:** Design approved, ready for planning

## Problem

When something goes wrong during a race (red flag, technical difficulties), the director
sets the HUD **Race Control** field but the live race picture keeps playing underneath.
There's no quick way to hold/cover the picture without leaving the **Stint** scene (and the
HUD with it). The director wants a one-button cover that hides the live picture **while
keeping the HUD** (Race Control banner + timer) visible, so viewers still see the status.

## Goal

A hidden, toggleable full-screen **Standby Cover** in the Stint scene that, when shown,
hides the live picture (both feeds **and** the POV PiP) but stays **below the HUD**, so the
Overlay frame, Race Control banner, and race timer remain on top. Toggled by a Companion
button. Visual only.

Non-goals (YAGNI): muting feed audio (the director uses the existing MUTE buttons); a
Splitscreen version; a new dedicated graphic; auto-triggering from the sheet.

## Decisions (locked)

- **Graphic:** reuse the existing standby graphic `YT-IRO-Race.png` (the one the Standby
  scene's `Thumbnail` source uses). No new asset.
- **Scope:** the **Stint** scene only.
- **Audio:** none — visual cover only.

## Design

### Z-order (the crux)

The cover must sit **above the live picture but below the HUD**. New Stint scene item
order (back → front):

```
  Discord
  Feed A
  Feed B
  Feed POV          ← moved here from front-most (above feeds, below the cover)
  Standby Cover     ← NEW: hidden full-screen; covers Feed A/B + POV when shown
  HUD group (Overlay frame + HUD Overlay + HUD Race Timer)   ← stays on top
  Standings / Season Schedule / Race Results / Quali Results
```

So when the cover is shown it hides the feeds and the POV PiP, but the HUD group (frame +
Race Control + timer) renders on top and stays visible. Because `Overlay.png` is mostly
transparent, the standby graphic shows through it; only the HUD's opaque elements and text
sit on top — the intended "we have an issue, status still running" look.

Moving **Feed POV** below the HUD does **not** change normal operation: the POV PiP sits at
roughly y 644–860 and the HUD lower-third starts at ~y 864, so no HUD element overlaps the
POV box. The change only matters when the cover is active (now it covers the POV too).

The full-screen graphics inserts (Standings, etc.) stay front-most as today — they
deliberately cover everything including the HUD when the director shows them; the Standby
Cover is the opposite (keeps the HUD), which is why it sits lower.

### Components

- **New OBS source `Standby Cover`** — an `image_source` pointing at the tokenized
  `__IRO_ASSETS__/YT-IRO-Race.png` (same file as the `Thumbnail` source). A dedicated named
  source keeps the Stint source list clear and its visibility independent of the Standby
  scene (visibility is per scene-item anyway).
- **Stint scene item** for `Standby Cover` — full-screen (pos 0,0; bounds-type "fit"
  1920×1080, mirroring the existing full-screen image inserts), **visible = false**,
  inserted at the z-position above, i.e. directly after `Feed POV`.
- **Feed POV reposition** — the existing `Feed POV` scene item is moved from front-most to
  directly after `Feed B` (so it sits below the cover). Its source and PiP transform are
  unchanged — only its z-order in the Stint scene changes.
- **Companion button (operator-built)** — a toggle: *Set Source Visibility* on
  `Stint / Standby Cover`, with a *Source Visible* feedback so the button lights while the
  cover is active. The operator names and builds it (same pattern as the POV buttons); docs
  refer to it neutrally as the "Standby cover" toggle. Audio is unchanged (existing MUTE
  buttons).

### Implementation

A new idempotent maintainer script **`tools/add_standby_cover.py`**, mirroring the existing
`tools/add_pov_source.py`:

1. If `Standby Cover` already exists in the collection → no-op (idempotent).
2. Add the `image_source` object: deep-copy an existing image source (e.g. `Thumbnail` or
   `Standings`) as a template, then set `name = "Standby Cover"`, a fixed new `uuid`, and
   `settings.file = "__IRO_ASSETS__/YT-IRO-Race.png"`.
3. In the **Stint** scene's `settings.items`:
   - Remove the existing `Feed POV` item (if present) and re-insert it directly after
     `Feed B`.
   - Insert a new `Standby Cover` item directly after `Feed POV`: deep-copy a full-screen
     image insert (e.g. the `Standings` scene item) as the transform template, then set
     `name`, `source_uuid`, a unique `id` (max scene id + 1), `visible = false`,
     `locked = false`, pos 0,0, bounds-type "fit" 1920×1080.
   - If `Feed POV` is absent (e.g. a `--no-pov` collection), just insert `Standby Cover`
     directly after `Feed B`.

Run it on `src/obs/IRO_Endurance.json`. The collection stays tokenized
(`__IRO_ASSETS__/...`), so `tools/build.py`'s verify is unaffected.

### Documentation

- **Director guide** — extend the incident cue (in the "Through the broadcast" section):
  "Incident? Set Race Control → Red Flag / Technical Difficulties **and show the Standby
  cover** (the button) to hold the picture; when it's resolved, hide the cover and clear
  Race Control." (The HUD + timer stay visible under the cover.)
- **OBS & scenes** (technical) — a short note: the `Standby Cover` source in the Stint
  scene sits below the HUD group; toggle it with a Companion *Set Source Visibility* button.
- Re-publish the wiki with `tools/sync-wiki.py`.

#### Deferred follow-up (once the Companion button exists)

This first pass documents the cover neutrally (the operator builds the button). Once the
real button is built and named, a second pass must:

- name the button by its real label everywhere it's referenced — Director guide incident
  cue, Companion button table, Run-an-event, and the "If something goes wrong" page;
- **re-take the Companion screenshots** so the button board images show the new toggle;
- re-publish the wiki.

Tracked so it isn't lost between now and when the button lands.

### Verification

- **Structural validation** of `src/obs/IRO_Endurance.json` after running the script:
  `Standby Cover` source exists; the Stint scene has the `Standby Cover` item
  (visible = false, full-screen) positioned **after `Feed POV`** and **before** the HUD
  group items; `Feed POV` now sits directly after `Feed B`; no orphan `source_uuid`
  references; no duplicate scene-item ids; `__IRO_ASSETS__` token intact.
- **Build:** `tools/build.py` passes all verify checks.
- **Manual (operator):** re-localize (`setup-assets.py`), import, add the Companion toggle,
  and confirm: cover hidden by default; toggling it on hides the feeds **and** the POV PiP
  while the Overlay frame, Race Control banner, and timer stay visible; toggling off
  restores the picture.

## Out of scope

- Audio muting / combos.
- Splitscreen (or any scene other than Stint).
- A new/dedicated incident graphic.
- Building the Companion button (operator does this).
