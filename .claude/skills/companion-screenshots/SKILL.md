---
name: companion-screenshots
description: Regenerate the wiki's Companion button-board screenshots (src/docs/wiki/images/companion-pageN-*.png) after a button changes. Use when a Companion button was added/renamed/recolored/moved and the wiki screenshots are stale. Drives the running Companion web-buttons view via the Playwright MCP and crops the grid with ffmpeg. Cross-platform (no macOS-only tools).
---

# Companion button-board screenshots

Recreate the wiki screenshots of the Companion button grid for the GT Endurance Racing
Broadcast toolkit. The grid is served by a **running** Companion instance; this skill
screenshots it through a headless browser (Playwright MCP) and crops out the toolbar with
**ffmpeg** (already a project dependency). No pip dependencies, no manual cropping math.

For Control Center / `/console` / cockpit / Director-Panel shots use the sibling
[wiki-screenshots](../wiki-screenshots/SKILL.md) skill instead; this one is **only** for
the Companion button board. Verify the published result with
[wiki-visual-test](../wiki-visual-test/SKILL.md).

## When to use

After a Companion button is added, renamed, recolored, or moved — the wiki images in
`src/docs/wiki/images/` go stale and must be regenerated for the page(s) that changed.

Pages and their files:
- **Page 1** → `companion-page1-show-control.png` (combos, scenes, feeds & POV, graphics)
- **Page 2** → `companion-page2-timer-audio.png` (race timer + mute + per-source volume)

Only regenerate the page(s) you actually changed.

## Prerequisites

- **Companion is running** on `http://localhost:8000` with the current config imported
  (the button you just built must be visible in its web UI). Import the repo config with
  `python3 src/racecast.py export companion` → import the written `.companionconfig`.
- **Playwright MCP** available (the `mcp__plugin_playwright_playwright__*` tools).
- **ffmpeg** + **ffprobe** on PATH (`ffmpeg -version`). Both ship together; `ffprobe`
  replaces the old macOS-only `sips` dimension check, so this skill runs on Windows too.
- Working directory: the repo root.

## The grid geometry (measured, stable)

In the web-buttons view at viewport **1280×720**:
- The top toolbar (fullscreen + configure icons) occupies **y = 0…~56**.
- The button tiles (`.button-control.clickable`) start at **y = 56**, **row pitch ≈ 157 px**,
  full width **1280** (8 columns, 12 px side padding included).
- So **N populated rows** crop to height `N*157 + 4`, starting at `y = 54` (≈2 px top margin).
  The board has **4 rows** per page → crop height **632**.

Do **not** rely on the tile **count** (`.button-control` lazy-renders extra empty rows at
taller viewports) — rely on the fixed top (56) and pitch (157), and the known **4 rows**.

## Procedure

Do this per page that changed. Example shown for **page 1**.

1. **Navigate** to the web-buttons view:
   - Page 1: `mcp__…__browser_navigate` → `http://localhost:8000/tablet`
   - Page N>1: `…/tablet?pages=N`  *(caveat below)*

2. **Resize** the viewport so all 4 rows render:
   `mcp__…__browser_resize` → `width: 1280, height: 720`

3. *(Optional sanity check)* confirm the grid top + pitch with
   `mcp__…__browser_evaluate`:
   ```js
   () => { const t=[...document.querySelectorAll('.button-control.clickable')];
     let y0=1e9; t.forEach(e=>y0=Math.min(y0,e.getBoundingClientRect().top));
     return JSON.stringify({top:Math.round(y0), n:t.length, vp:[innerWidth,innerHeight]}); }
   ```
   Expect `top ≈ 56`.

4. **Screenshot** the viewport (not an element — `.buttons-holder` has zero height and is
   not screenshot-able):
   `mcp__…__browser_take_screenshot` → `type: png`, `filename: companion-vp.png`
   (it lands in the repo root / CWD).

5. **Crop** the toolbar off with ffmpeg — `crop=W:H:X:Y`:
   ```bash
   ffmpeg -y -loglevel error -i companion-vp.png \
     -vf "crop=1280:632:0:54" \
     src/docs/wiki/images/companion-page1-show-control.png
   ```
   (For a page with a different row count R, use `H = R*157 + 4`.)

6. **Verify** visually: Read the output PNG. Check the changed button shows correctly, the
   four rows are fully visible, top/bottom margins look even. Confirm the size is
   `1280×632` cross-platform with ffprobe:
   ```bash
   ffprobe -v error -select_streams v:0 -show_entries stream=width,height \
     -of csv=p=0 src/docs/wiki/images/companion-page1-show-control.png   # -> 1280,632
   ```

7. **Clean up** the scratch viewport PNG(s) from the repo root:
   `rm -f companion-vp.png`

8. **Commit** the updated image(s):
   ```bash
   git add src/docs/wiki/images/companion-page1-show-control.png
   git commit -m "docs(companion): refresh page-1 button-board screenshot"
   ```

9. **Publish** the wiki only on the user's go-ahead: `python3 tools/sync-wiki.py`
   (preview first with `--dry-run`), then verify with the
   [wiki-visual-test](../wiki-visual-test/SKILL.md) skill.

## Caveat: page 2+ has a navigation column

`/tablet` (no params) shows **page 1** with real buttons in column 0 (no nav). Adding
`?pages=N` renders a left **UP / PAGE n / DOWN** navigation column, shifting the buttons one
column right — this matches the existing `companion-page2-timer-audio.png` framing, so it's
the correct view for page 2. Keep using the same URL form that produced the existing image
for that page so the framing stays consistent.

## Notes

- Both pages are shot with this recipe at `1280×632`.
- Companion renders buttons as positioned `div`s (not `<img>`/`<canvas>`), and the
  `.buttons-holder` wrapper has height 0 — that's why we screenshot the **viewport** and
  crop, rather than screenshotting an element.
