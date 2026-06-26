# Overlay Builder — editable preview data ("Preview-Daten" panel)

Date: 2026-06-26
Status: Design (approved pending spec review)
Scope: Control Center visual overlay builder (`hud` page only)

## Problem

The visual overlay builder renders its canvas with **hardcoded** sample text from
`SAMPLE["hud"]` in `src/scripts/overlay_build.py` (lines 78–93). The operator
cannot change those placeholder values, so they cannot judge how the layout reacts
to *their* content — a long team name, their real POV name, a particular flag
state. Worse, several slots have **no** sample at all and therefore render blank
on the canvas:

- `pov-name` — no SAMPLE entry → blank.
- `flag-status` — no SAMPLE entry → blank, and its colour (driven by a
  `data-state` attribute) is never shown.
- `pov` — box slot, shown/hidden at runtime by `povActive`; on the canvas it just
  sits empty.

Additionally, the canvas does **not** mirror three runtime behaviours, so even the
slots that do have samples can mislead:

1. **Flag colour** — runtime sets `#flag-status[data-state="…"]` (green/yellow/SC/
   code-60/red/checkered); the canvas never sets `data-state`, so the flag is
   always uncoloured.
2. **POV visibility** — runtime shows `#pov` + `#pov-name` only when `povActive`;
   the canvas has no notion of this.
3. **Team-name auto-fit** — runtime shrinks an overflowing team name between
   `--team-name-max` and `--team-name-min` (`fitName` in `hud.html`); the canvas
   renders raw text, so a long name *looks* clipped when it would actually shrink.

## Goal

Give the operator a **session-only, builder-local** way to:

- type their own preview text per slot (incl. the gap slots),
- switch dynamic states that are otherwise invisible (flag state, POV on/off,
  race-control on/off — the last via empty text), and
- see every slot rendered with something meaningful,

so they can preview *how a change looks* before the final check in OBS. The
standalone `/hud/preview` page (real `/hud/data` over the Overlay.png frame in OBS)
is the later, authoritative check and is **unchanged**.

Non-goals (explicitly out of scope for this change):
- Persisting preview values into the profile (`overlay/`), or feeding `/hud/preview`.
- Editing image/box slot keys (logos, round flag) in the panel — deferred as a
  future nice-to-have; box image slots keep showing their fixed sample asset.
- The `splitscreen` page — not in focus; `hud` only.

## Approach (chosen)

**Editable preview-data model in the front-end, seeded from extended Python
defaults.** `SAMPLE["hud"]` stays the single source of *default* values (so it
stays unit-testable); the builder holds an **editable copy** that the canvas
renders. This keeps the backend change tiny and puts the interaction where it
belongs (the builder JS).

Rejected alternatives:
- *Defaults only, no editor* — text would still be non-editable (the core ask).
- *Pull live `/hud/data` into the builder* — needs a running relay + real league;
  defeats the offline builder.

## Design

### A. Backend — `src/scripts/overlay_build.py`

1. **Complete `SAMPLE["hud"]`** so every **text-kind** slot has a non-empty entry.
   Add:
   - `"pov-name": "John Doe"`
   - `"flag-status": "Safety Car"` (the canvas overrides this from the flag picker,
     but the entry keeps the completeness invariant simple)
   Box-kind slots are exempt: image boxes (`round-flag`, `teamN-logo`) keep their
   `{flag|brand: key}` asset sample; `pov` is a frame with no text/asset.

2. **New `FLAG_PRESETS`** — the curated flag states offered in the picker, each
   `{"state": <css-state>, "label": <display text>}`, e.g.:
   `Green Flag/green-flag`, `Yellow Flag/yellow-flag`, `Double Yellow/double-yellow`,
   `Safety Car/safety-car`, `Virtual SC/virtual-safety-car`, `FCY/full-course-yellow`,
   `Code 60/code-60`, `Red Flag/red-flag`, `Checkered/checkered-flag`.
   Each `state` MUST exist as a `data-state="…"` rule in `hud.html` (drift guard,
   see Testing). The picker also offers an explicit **"Off"** that clears the slot.

3. `overlay_slots_data()` (in `src/racecast.py`, served at `/api/overlay/slots`)
   adds `flagPresets` to its JSON payload (alongside the existing `slots`, `css`,
   `body`, `sample`). No other endpoint changes; no new endpoint.

### B. Front-end — `src/ui/control-center.html` (builder)

1. **`ovPreview` state** (replaces direct reads of `ovState.sample`):
   ```
   ovPreview = {
     values: { ...deep copy of ovState.sample... },  // slotId -> string | {flag|brand}
     flagState: '',        // '' = Off, else a FLAG_PRESETS state
     povActive: true,
   }
   ```
   Seeded from `ovState.sample` + `flagPresets` on load. Mirrored to
   **`localStorage`** under `overlay-preview:<profile>:hud` so it survives a reload
   *within the session*; it is never written to profile files. A **"Reset"** button
   restores the seeded defaults (and clears that localStorage key).

2. **`ovFillSample()` → reads `ovPreview`** instead of the static map, and gains the
   three fidelity behaviours (each a small mirror of existing logic, matching the
   repo's `ovSlantClip`/`ovApplyTransform` mirroring pattern):
   - **Flag:** if `ovPreview.flagState` is set, `#flag-status` gets the preset
     `label` as text and `el.dataset.state = flagState` (colour appears); else the
     slot is emptied and `data-state` removed. (No need to port `flagSlug` — the
     preset carries the canonical state.)
   - **POV:** `#pov` and `#pov-name` follow `ovPreview.povActive` (toggle the
     `empty` class as runtime does); `#pov-name` text from `values['pov-name']`.
   - **Team-name auto-fit:** after setting a `teamN-name`'s text, run a faithful
     mirror of `fitName` (shrink from `teamNameMax`→`teamNameMin`) so a long name
     previews the way it renders live.
   - Race-control: plain text from `values['race-control']`; empty → hidden (the
     existing `empty` behaviour), which *is* the "race control off" state.

3. **The "Preview-Daten" panel** — a new collapsible section in the builder
   sidebar (sibling of the existing slot-property panel), rendered once on load:
   - **State controls (top):**
     - *Flagge* — a `<select>` built from `flagPresets` (+ "Off").
     - *POV aktiv* — a checkbox bound to `ovPreview.povActive`.
     - (Race control on/off is implicit via its text field being empty/non-empty;
       a short hint says so. No extra checkbox.)
   - **Per-slot text fields (below):** one labelled input per **text** slot
     (using `slot.label` from `extract_slots`), grouped for readability
     (Stint/Session/Streamer · Round · Team 1/2/3 · POV · Flag). Box image slots
     are not listed (deferred). The `flag-status` field is replaced by the picker
     above; `clock` may be listed as text too (it has a sample).
   - Any edit updates `ovPreview`, persists to localStorage, and re-runs
     `ovFillSample()` (and re-applies slot styles so auto-fit re-computes).

4. The panel and its controls follow the builder's existing styling; the help line
   near line 765 ("The canvas shows sample data…") is updated to mention the panel.

### C. Data flow (unchanged spine, new editable layer)

```
/api/overlay/slots  ->  ovState.sample (+ flagPresets)   [defaults]
                         │
                         ▼  (seed, once)
                       ovPreview  ◄── panel edits ──► localStorage (session)
                         │
                         ▼
                   ovFillSample()  ──► Shadow-DOM canvas (text + flag colour +
                                        POV visibility + team auto-fit)
```

The layout model (`layout-hud.json`), `compile_overlay_css`, the served
`/hud/override.css`, and the live `/hud` page are **untouched** — this only changes
what *content* the offline canvas shows, never the produced CSS.

## Error handling / edge cases

- Malformed/older `localStorage` value → ignored; fall back to seeded defaults.
- `flagPresets` absent (older backend) → flag picker hidden, rest works.
- A future new slot with no SAMPLE entry → text input shows empty; the completeness
  test (below) prevents that for shipped slots.

## Testing

- `tests/test_overlay.py`:
  - **Completeness:** every `text`-kind slot from `extract_slots(hud.html)` has a
    non-empty `SAMPLE["hud"]` entry (box slots exempt; `pov` exempt).
  - **Flag-preset drift guard:** every `FLAG_PRESETS[i]["state"]` appears as a
    `data-state="<state>"` substring in `src/obs/hud.html` (mirrors the repo's
    byte-identical cross-check pattern, e.g. `STREAMLINK_TWITCH`).
- `tests/test_racecast.py` / `tests/test_ui_server.py`: `/api/overlay/slots`
  response includes `flagPresets` (non-empty list of `{state,label}`).
- `python3 tools/lint.py` after the Python change.

## Mandatory follow-up (CLAUDE.md hard rule)

The Control Center overlay-builder UI changes, so its wiki screenshot
`src/docs/wiki/images/cc-overlay-builder.png` is now stale and MUST be regenerated
**in the same change** via the `wiki-screenshots` skill (element shot of the
builder card, captured from a local dev build so the version badge stays uniform).

## Files touched

- `src/scripts/overlay_build.py` — extend `SAMPLE["hud"]`, add `FLAG_PRESETS`.
- `src/racecast.py` — add `flagPresets` to `overlay_slots_data()`.
- `src/ui/control-center.html` — `ovPreview` state, panel, `ovFillSample()` rewrite
  + fidelity mirrors, help text.
- `tests/test_overlay.py`, `tests/test_racecast.py` / `tests/test_ui_server.py` — tests.
- `src/docs/wiki/images/cc-overlay-builder.png` — refreshed screenshot.
