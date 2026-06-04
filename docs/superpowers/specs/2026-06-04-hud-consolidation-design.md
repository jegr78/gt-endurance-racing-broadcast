# HUD Consolidation — Single Relay-Served Overlay

**Date:** 2026-06-04
**Status:** Design approved, ready for planning

## Problem

The OBS scene collection renders the broadcast HUD with **~13 separate browser
sources** (Stint, Streamer, Session, Round Track/Flag/Country, Race Control, and
3× Team Brand + 3× Team Name). Every one of them points at the **full Google
Sheets editor web app** (`https://docs.google.com/spreadsheets/d/<id>/edit`) at
1920×1080 and isolates a single cell via an OBS crop transform plus a
chroma/colour-key filter.

Each browser source is a separate CEF (Chromium) instance — OBS shares nothing
between them, not even for an identical URL. So the producer machine runs ~13
full Google-Sheets-editor SPAs in parallel. The Sheets editor is among the
heaviest web apps in existence (canvas rendering, background sync, workers). On
the producer Mac (16 GB RAM — the documented performance bottleneck) this is the
direct cause of swap thrashing and lag during events.

A prior attempt to collapse everything into a single browser source failed at
**element positioning**, because it tried to CSS-crop the *rendered* Sheets view
— uncontrollable on a foreign SPA.

## Goals

1. **Performance:** replace the ~13 Sheets-editor browser sources with **one
   lightweight browser source**.
2. **Keep central maintainability:** all HUD content stays editable in the same
   Google Sheet — no new editing surface for the operator.
3. **No manual reloads:** sheet edits appear on the overlay automatically.
4. **Solve positioning:** elements are laid out in our own HTML/CSS, freely
   positionable.

Non-goals: changing the Stagetimer source (stays its own lightweight browser
source — it is a real-time countdown page, not sheet data); changing the relay's
feed/ping-pong logic; redesigning the visual look (replicate the current
overlay).

## Key insight

Do **not render Google Sheets at all**. Fetch its *data* and render our own HTML.
The relay already does exactly this for the schedule — it reads the sheet as CSV
with no API key via the gviz endpoint
(`/gviz/tq?tqx=out:csv&sheet=<tab>`, see `src/relay/iro-feeds.py:573-575`) and
already runs an HTTP server (`:8088`) that serves a static HTML page at `/panel`
via `_send_file()` (`iro-feeds.py:451-467`). Half the infrastructure exists.

## Architecture

```
Configuration tab ──┐  (season master data: vocabulary + team→brand text map)
                    ├─► Relay reads both tabs as gviz CSV (one shared fetch)
Overlay tab ────────┘  (live on-air state)
                    │
                    ▼
   GET /hud/data  →  JSON  { streamer, session,
                            round:{ top, country, flagKey },
                            teams:[ {name, brandKey} × 3 ],
                            raceControl }
   GET /hud       →  hud.html  (static file, served like /panel)
                    │  browser polls /hud/data every ~2–3 s
                    ▼
   OBS: ONE browser source → http://127.0.0.1:8088/hud
        (transparent, 1920×1080) — hud.html lays out every element in CSS
```

**Source count:** 13 sheet browser sources → **1**. The ~13 chroma/colour-key
filters are deleted (our HTML renders transparent directly — no greenscreen
trick). The Stagetimer source stays as-is.

### Tab roles

- **Configuration tab** — the season master data / dropdown vocabulary: every
  Stint, Streamer, Session, Round, Country, Team, Brand, and Race-Control phrase.
  Used by the relay as the controlled vocabulary for asset resolution and for the
  **team → brand** text map.
- **Overlay tab** — the live "what is on air right now" state the producer sets
  during the broadcast. Column B holds labels; the value sits in the merged green
  cell to the right. This is the primary source for live HUD values.

### Data contract

`/hud/data` returns JSON shaped from the Overlay tab:

| Overlay label (col B) | JSON field        | Type   | Source           |
|-----------------------|-------------------|--------|------------------|
| Streamer              | `streamer`        | text   | Overlay          |
| Session               | `session`         | text   | Overlay          |
| Round Top             | `round.top`       | text   | Overlay          |
| Round Bottom          | `round.country`   | text   | Overlay          |
| Round Flag            | `round.flagKey`   | key    | derived from country |
| Teams P1/P2/P3        | `teams[].name`    | text   | Overlay          |
| (per team)            | `teams[].brandKey`| key    | Configuration brand map |
| Race Control          | `raceControl`     | text   | Overlay          |

**Overlay read rule:** for each labeled row, `key = normalized text of column B`,
`value = first non-empty cell from column C onward`. This naturally yields team
*names* too (the brand-image cell is empty in CSV, so the name in column E is the
first non-empty value). gviz returns a merged cell's content in its top-left
cell — compatible.

### Images → bundled assets, resolved by text

In-cell images (flags, brand crests) **do not appear in CSV exports** at all, so
they cannot be transported as data. Both are resolved from text against bundled
assets — which also makes them *more* maintainable than inserting images by hand:

- **Flag:** Overlay `Round Bottom` country text (`GERMANY`) → `flags/germany.svg`.
  The asset set mirrors the Country list in the Configuration tab. **No sheet
  change required.**
- **Brand:** A new **text column "Brand"** is added to the Configuration tab's
  Teams table (team name → brand text, e.g. `OVO eSports #111` → `porsche`). The
  relay builds a `{team_name: brandKey}` map from it; the active Overlay team
  names resolve to `brands/porsche.svg`. The brand then follows the team
  automatically — less manual work than today's per-stint image insertion.

Key normalization (country/brand text → asset filename) is defined in one place
(lowercase, trim, spaces→`-`, strip punctuation) and applied identically in the
relay and any tests. Unknown key → element hidden + a one-line warning logged
(never a broken-image icon on air).

**Assets are provided by the operator:** the existing flag and manufacturer-crest
images already live in the sheet and will be exported once into `src/assets/`
(`flags/`, `brands/`) and referenced by key. The spec/plan enumerates the
required Country and Brand vocabulary so the set can be checked for completeness.

## Components (all under `src/` per the build rule)

1. **`HudSource`** (new, in `src/relay/iro-feeds.py`) — analogous to the existing
   `ScheduleSource`: fetches the Overlay tab and Configuration tab as gviz CSV,
   parses them into the contract dict, keeps a "last-good" value with cache +
   fallback (so a brief sheet outage freezes the last frame rather than blanking
   the overlay). Refreshed by the existing `poller()` background thread.

2. **Two routes in `do_GET`** (`iro-feeds.py`):
   - `/hud/data` → `self._send(hud.data())` (JSON).
   - `/hud` → `self._send_file(hud_html_path, "text/html; charset=utf-8")`,
     with path discovery mirroring the existing `panel_path` logic
     (`iro-feeds.py:604-611`), pointed at `src/obs/hud.html` in the repo and the
     package root in the distributed build. A `--no-hud` flag (parallel to
     `--no-panel`) and graceful 404 when disabled.

3. **`src/obs/hud.html`** (new) — a single static page: CSS lays out every HUD
   element at fixed positions (replicating the current overlay), and a small
   vanilla-JS loop polls `/hud/data` every ~2–3 s and fills text nodes + image
   `src` attributes. Empty fields hide their element. Race Control is a plain
   static text line (no ticker/marquee animation). No framework, no build step
   (consistent with the stdlib-only, no-package-manager project rule). Shipped and
   path-discovered the same way as `director-panel.html`.

4. **`src/assets/flags/` + `src/assets/brands/`** — small SVG/PNG sets exported
   from the sheet, keyed by the normalized country/brand vocabulary.

5. **OBS scene collection** (`src/obs/IRO_Endurance.json`) — replace the 13 sheet
   browser sources with one browser source pointing at the relay HUD URL; remove
   the now-unused chroma/colour-key filters. The relay HUD URL stays
   secret/path-free in git (localhost + fixed HTTP port, no `__IRO_SHEET__`
   token needed for the HUD source). Re-fold any in-OBS edits back through the
   existing `tools/tokenize-obs.py` flow.

## Update mechanism

The browser polls `/hud/data` every ~2–3 s. A sheet edit propagates within one
poll interval — no manual reload, satisfying the core requirement. The relay's
own poller refreshes its sheet cache independently, so client polls hit a warm
in-memory value (one shared sheet fetch serves all reads, vs. 13 independent
editor instances today).

Optional future upgrade (out of scope for v1): Server-Sent Events from the relay
for instant push instead of polling.

## Error handling / robustness

- **Sheet unreachable:** `HudSource` serves its last-good cached dict (same
  pattern as `ScheduleSource.load_initial`); the overlay holds the last frame.
- **Unknown country/brand key:** element hidden, one-line warning logged. Never a
  broken image on air.
- **Relay not running:** the HUD source shows nothing (acceptable — the HUD is
  only meaningful while the relay, the producer's main tool, is running). Noted
  in operator docs.
- **Malformed Overlay row:** missing fields simply hide their element; the rest
  of the HUD renders.

## Testing

- **Unit test** (`tests/test_hud.py`, stdlib-only, runnable script like
  `tests/test_pov.py`): feed representative Overlay + Configuration CSV fixtures
  to the parser and assert the resulting JSON contract — including the
  first-non-empty-from-C rule, country→flagKey and team→brandKey resolution, key
  normalization, and unknown-key handling.
- **Build verify** (`tools/build.py`): the HUD html + assets ship in the package;
  no secrets/paths leak; no shell scripts introduced.
- **Manual:** load `http://127.0.0.1:8088/hud` in a browser against a live relay,
  edit a sheet cell, confirm the overlay updates within one poll interval.

## Operator-facing changes

- One-time: add the **Brand** text column in the Configuration tab and fill it per
  team; export flag/brand images into `src/assets/`.
- The Overlay tab editing workflow is otherwise unchanged.
- Docs (`src/docs/`, wiki `OBS-Setup.md`) updated to describe the single HUD
  source and the relay `/hud` endpoint.

## Out of scope

- Stagetimer source (unchanged).
- Relay feed/ping-pong logic (unchanged).
- SSE push (possible later).
- Visual redesign (replicate current look).
