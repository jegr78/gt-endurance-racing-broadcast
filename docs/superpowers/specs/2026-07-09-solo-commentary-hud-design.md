# Solo Commentary HUD — Design Spec

**Status:** Draft for review
**Date:** 2026-07-09
**Epic:** #300 (solo mode) — separate PR into `epic/300-solo-mode`, based on the
`feat/324-gt7-telemetry-pov-hud` branch (depends on its box→OBS generalization:
`OVERLAY_SLOT_OBS_SOURCES` with `scene`/`export_scene`, `overlay_build.box_from_css`,
`setup-assets.apply_box_transform(scene=…)`, and `_sync_pov_transform`'s slot loop).

## Goal

Add the three overlay elements a commentary broadcast needs that the current solo
HUD lacks, all managed the same way the rest of the overlay is (visual builder +
per-league override CSS), so a league keeps its look self-contained and portable:

1. **League logo** (top-right) — a builder-positioned image slot fed by the league
   profile's existing `LOGO` asset.
2. **Tyres/Fuel capture** (bottom-left, **Commentary only**) — a second capture card
   cropped to GT7's in-game tyre/fuel/sprint widget, placed by a builder box.
3. **Stream chat** (POV **and** Commentary) — a builder-positioned, CSS-styleable slot
   rendering the existing read-only broadcast chat (#294) onto the program.

**Explicitly out of scope of this spec:** the exact default positions/sizes of the
three slots. Those are set afterwards in the visual dialog (render over Jens's real
commentary streams, iterate to approval) — the same process used for the POV/telemetry
layout. This spec defines the *mechanism* only.

## Architecture context (what already exists)

The solo commentary program is a stack (bottom→top) in the `Program` scene of
`GT_Racing_Solo_Commentary.json`:
- `Solo Capture` — the full-screen GT7 game (capture card, `__RACECAST_CAPTURE__`).
- `Overlay` — the **static per-league branding PNG** (`__RACECAST_GRAPHICS__/Overlay.png`,
  from the Sheet Assets tab). This carries ~95% of the commentary look (leaderboard
  styling, top banner, lower-third frame) and is NOT changed by this spec.
- `HUD Overlay` — the relay-served `hud.html` (`http://127.0.0.1:8088/hud`) browser
  source, full-frame, where the few dynamic slots live (session label etc.). All three
  new elements below are added here or beside it.

The broadcast-chat reader (#294) already mirrors the public YouTube/Twitch chat and is
rendered by `src/obs/intermission.html` (`#ichat`, fed by `/broadcast-chat/data`). It
self-gates: the endpoint 404s when no `Channel` tab is configured.

The box→OBS mechanism (from #324): a `#<slot>` CSS box drives a named OBS scene item's
transform, at export (`apply_box_transform`, optionally scene-scoped via `export_scene`)
and live (`_sync_pov_transform` loop). Currently maps `pov`→"Feed POV",
`webcam`→"Solo Webcam".

## 1. League logo slot (top-right)

**Asset:** reuse the existing `LOGO` field in `profiles/<name>/profile.env` (a filename
in the profile dir; resolved to `ResolvedConfig.logo_path` and injected as
`RACECAST_LOGO`). Travels with `profile export` already. No new asset concept.

**Relay serves it.** Add a route `GET /hud/logo` to the relay that streams the active
profile's logo file (the relay learns the path from a new `--logo PATH` arg the CLI
passes from `RACECAST_LOGO`; mirror how `--overlay-dir` is wired in
`_overlay_relay_args`). Content-type by extension; when unset/missing/non-image, return
404 (the slot then self-hides). Gate the served file by the existing
`servable_logo_path` extension allow-list to avoid serving a non-image someone put in
`LOGO`.

**HUD slot.** Add to `hud.html`, mirroring the team-logo slot pattern
(`<div id="…" class="el …" data-edit-kind="box"><img alt=""></div>`):
```html
<div id="league-logo" class="el" data-edit="League logo" data-edit-kind="box"><img alt="" src="/hud/logo"></div>
```
The `<img>` `onerror` hides the slot (so a 404 logo → invisible; endurance/other profiles
with no logo are unaffected). It is a normal builder box slot (position/size), so
`extract_slots` picks it up and the builder repositions it like any other. Pure overlay —
NOT in `OVERLAY_SLOT_OBS_SOURCES` (no OBS source behind it). Add a `SAMPLE["league-logo"]`
entry (a placeholder brand) so the builder canvas renders it.

**Default position:** top-right (exact box TBD in the visual dialog).

## 2. Tyres/Fuel capture (bottom-left, Commentary only)

A second capture card showing the GT7 screen, cropped to the in-game tyre/fuel/sprint
widget, placed bottom-left — exactly the pattern in Jens's real `D-GT7-M` collection
(`Tyres-Fuel-Capture`, Elgato HD60 X).

**New OBS source** in `GT_Racing_Solo_Commentary.json` ONLY (not the POV collection):
- A `Solo Tyres/Fuel Capture` scene wrapping a `Solo Tyres Capture Device` input
  (`__RACECAST_TYRES_CAPTURE__`), mirroring the `Solo Webcam` / `Solo Webcam Device`
  structure. The device is chosen per-platform exactly like the webcam/capture
  (`av_capture_input`/`dshow_input`, token replaced by `setup-assets.localize_device_sources`).
- Embedded as a `Solo Tyres/Fuel Capture` item in the `Program` scene with a **baked
  default crop** isolating GT7's widget (from Jens's export):
  `crop_left: 258, crop_top: 950, crop_right: 1336, crop_bottom: 18` (→ a 326×112 region
  of the bottom-left game screen). `bounds_type: 2` so the cropped result fits its box.
  The crop is a fixed setup detail (operator fine-tunes in OBS if their capture differs);
  the builder box drives **only** position/size, never the crop.

**Device enumeration / `.env`:** add `Solo Tyres Capture Device` /
`RACECAST_TYRES_CAPTURE` to `setup-assets`'s local-device list (the `LOCAL_DEVICES`
table alongside Solo Capture / Solo Webcam) so `racecast device-scan` (#304) and the
`.env` fill it; a missing device warns like the others (OBS shows black until selected).

**Builder box → OBS transform:** add to `overlay_build.OVERLAY_SLOT_OBS_SOURCES`
(slot id `tyres-capture` used verbatim as the map key, the `hud.html` element id, and the
`#tyres-capture` CSS id — `box_from_css(css, "tyres-capture")` reads `#tyres-capture`):
```python
"tyres-capture": {"scene": "Program", "source": "Solo Tyres/Fuel Capture", "export_scene": "Program"},
```
Because the source exists ONLY in the commentary collection, the export bake and live
sync are automatically no-ops in the POV/endurance collections (scene-scoped
`GetSceneItemId`/tree-walk find nothing) — "commentary only" needs no special casing.
Add a `#tyres-capture` builder box slot to `hud.html` (invisible positioning box, like
`#pov` — the actual video shows from the OBS source beneath `HUD Overlay`) and its
default `#tyres-capture` CSS box.

**Default position:** bottom-left (exact box + crop confirmation TBD in the visual dialog).

## 3. Stream chat slot (POV + Commentary)

Render the read-only broadcast chat (#294) onto the program, freely manageable in the
builder — position/size via the builder box, background/opacity/font/colours via CSS
(builder advanced-CSS + profile override), mirroring the intermission `#ichat` styling.

**HUD slot** in `hud.html`: a `#chat` box slot (`data-edit-kind="box"`) whose JS polls
`/broadcast-chat/data` and renders the last N messages (author + text via `textContent`,
XSS-safe; older messages clip out of the fixed box — reuse the intermission page's render
approach). Self-gates: on 404/empty it hides (so endurance/other profiles and any event
without a `Channel` tab are unaffected). Pure overlay — NOT in `OVERLAY_SLOT_OBS_SOURCES`.
Add a `SAMPLE["chat"]` entry so the builder canvas shows placeholder lines. Base CSS gives
it a sensible default background box (the intermission `--ichat-*` values are the
reference) that a league can override.

**Availability:** because it lives in the shared `hud.html` and self-gates, it is present
in POV and Commentary (positioned per profile) and harmlessly hidden elsewhere.

**Default position/size/background:** TBD in the visual dialog.

## Data flow summary

| Element | Source of data/asset | OBS coupling | Builder-editable |
|---|---|---|---|
| League logo | profile `LOGO` → relay `/hud/logo` | none (pure overlay) | position/size + CSS |
| Tyres/Fuel capture | 2nd capture card (device token) | `Solo Tyres/Fuel Capture` (Program, scoped) | position/size (crop fixed) |
| Stream chat | `/broadcast-chat/data` (#294) | none (pure overlay) | position/size + full CSS |

## Testing

- `tests/test_overlay.py`: slot-extraction list gains `league-logo`, `tyres-capture`,
  `chat`; `OVERLAY_SLOT_OBS_SOURCES` constant gains the `tyres-capture` entry (with
  `export_scene`); `box_from_css` for the `tyres-capture` slot; SAMPLE covers the new
  text/box slots (`t_ob_sample_covers_*`).
- `tests/test_discord_audio.py` (setup-assets transforms): `apply_box_transform` for
  `Solo Tyres/Fuel Capture` scene-scoped to `Program`; localize adds the new device token.
- `tests/test_racecast.py`: `_sync_pov_transform` now also targets
  `(Program, Solo Tyres/Fuel Capture)` when that box resolves; the `/hud/logo` route
  serves the logo / 404s appropriately (relay handler test).
- Relay handler: `/hud/logo` route unit (served bytes + content-type + 404 gate);
  `#chat` rendering is client-side (covered by the visual dialog, not a unit test).
- Endurance byte-identical: the three slots self-hide (logo `onerror`, chat 404-gate) and
  the tyres map entry is a no-op where the source is absent — assert the endurance HUD is
  unchanged.
- Full suite + `tools/lint.py` green; refresh any affected wiki screenshot per the CLAUDE.md
  rule if the Control Center overlay-builder view changes.

## Open decisions deferred to the visual dialog (not blockers for the plan)

- Exact default boxes for all three slots (positions/sizes).
- The chat slot's default background/opacity/font.
- Confirmation of the tyres crop region against a fresh commentary capture.
