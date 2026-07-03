# Graphics browser: "Internal (OBS-only)" asset filter + placement on all three console pages

**Date:** 2026-07-03
**Status:** Design — approved for planning
**Issue:** (to file)

## Motivation

The Commentator Cockpit has a **"Graphics" browser** card (`src/cockpit/cockpit.html`,
`#gfxHead`/`#gfxList`) that lists the broadcast still-graphics as clickable label links;
clicking one opens the full image in a new tab. It is fed by `GET /cockpit/graphics` →
`list_graphics(graphics_dir)` in `src/relay/racecast-feeds.py`, which is a **plain
directory read** of `runtime/<profile>/graphics/` and returns **every** `*.png`.

Those PNGs are downloaded from the Sheet **Assets** tab by `src/relay/get-graphics.py`
(`<Label>.png`, the label *is* the filename). Many of them are **purely OBS-internal**
(Standby, the three weather overlays, backgrounds) — a commentator never needs to browse
them, and they clutter the widget.

Two goals:

1. Give leagues a way to mark an asset as **internal (OBS-only)** in the Sheet so it is
   hidden from the Graphics browser (but still downloaded for OBS).
2. Make the **same** Graphics browser available on the **Director Panel** and the
   **Race Control** desk, not just the cockpit — with one consistent look and a fixed
   max height.

## Core constraint

The "internal" marker lives in the **Sheet**, but the widget only sees the
**filesystem** — and because the Sheet label *is* the filename, there is no per-asset
side-channel today. The design carries the internal-set from the download step to the
relay via a small **sidecar manifest** (chosen over a live Sheet read in the relay,
which would add a network dependency + polling to a non-critical convenience panel).

## 1. Sheet — Assets tab gains a header row + `Internal` checkbox

The Assets tab currently has **no header row** (positional: col A = label, first
Drive-link cell = URL). We introduce a header row:

| Name | Link | Internal |
|------|------|----------|
| Standings | `drive://…` | ☐ |
| Standby | `drive://…` | ☑ |
| Weather Rain | `drive://…` | ☑ |

- **Name** — the asset label (col A, unchanged semantics).
- **Link** — the Google-Drive share link (unchanged; located as today = first non-empty
  Drive-link cell).
- **Internal** — a **Google-Sheets checkbox**, maintained exactly like the Crew-tab role
  boxes. A checkbox exports in the gviz CSV as `TRUE`/`FALSE`.

Backward compatible: a header-less Assets tab (no `Internal` column) → nothing is marked
internal → today's behaviour (all graphics visible). **No Apps Script change** — the
Assets tab is read-only from our side (public gviz CSV), so this is a pure Sheet
convention. Documented in `src/docs/wiki/Sheet-Template.md` (Assets tab section).

**Truthy convention** — mirror the crew set:
`{"x", "yes", "true", "1", "y", "✓"}`, compared as `(v or "").strip().lower() in …`.
So a ticked box (`TRUE`) is internal; unticked (`FALSE`) / empty is not.

## 2. `get-graphics.py` — parse `Internal`, still download, write a manifest

`get-graphics.py` is one of the five self-contained, dependency-light scripts (it must
not import `config.py`); it already reads the Assets CSV. Changes, all local to the
script:

- **Header detection.** If the first CSV row is a header (contains a `Name`/`Label`
  header cell and/or an `Internal` header cell), locate the **Internal** column by header
  name (`ASSET_INTERNAL_HEADERS = ("internal", "obs only", "obs-only")`), mirroring the
  `CREW_*_HEADERS` / `BRAND_TEXT_HEADERS` `header.index(...)` pattern. The **Name** column
  is located by header when present, else falls back to col A (today's behaviour). The
  **Link** column logic is unchanged (first non-empty Drive-link cell).
- **Internal set.** Parse the internal labels **independently of the download link**, so
  a row like `Standby | (empty) | ☑` still marks `Standby` internal even when the image
  is a seeded placeholder or not Drive-hosted. Truthy = the set above.
- **Still download internal assets.** OBS needs Standby/weather; the download loop,
  reset, and seed logic are unchanged. Internal is a *visibility* flag, not a download
  flag.
- **Write the manifest.** After the download pass, write
  `runtime/<profile>/graphics/manifest.json`:
  ```json
  { "internal": ["Standby", "Weather Rain"] }
  ```
  Labels verbatim (the same strings used to derive `<label>.png`). Written on every run,
  so re-running `racecast graphics` refreshes the filter (same cadence as the graphics
  themselves). `manifest.json` is not a `*.png`, so `list_graphics`, `resolve_graphic`,
  and the reset/seed helpers never touch it.

New pure, unit-testable helpers in `get-graphics.py`: header/column location,
`internal_from_csv(rows) -> set[str]`, and the truthy predicate. `graphics_from_csv`
stays functionally identical for header-less sheets.

## 3. Relay `list_graphics()` — filter by the manifest

`list_graphics(graphics_dir)` also reads `graphics_dir/manifest.json` (best-effort:
missing/unreadable/malformed → treat as `{"internal": []}` → filter nothing, fully
backward compatible), builds a case-insensitive internal set, and **omits** any `*.png`
whose label (`fn[:-4]`) is in that set. Everything else (sort, shape
`[{"name","file"}]`) is unchanged.

- **Endpoint unchanged.** `/cockpit/graphics` + `/cockpit/graphics/<file>` stay as they
  are and remain gated by `self._console_auth()` — which is satisfied by **any**
  authenticated console subject, not just commentators. So the Director Panel and Race
  Control pages **reuse the same endpoint**: no new endpoint, no new Funnel/public
  surface. (`resolve_graphic` is unchanged; a directly-fetched internal filename still
  resolves — the filter is a *listing* concern, not an access-control boundary, which is
  correct: the data is not sensitive, we are only decluttering the browse list.)

## 4. Front-end — same widget on all three pages, one look, fixed max height

The widget is the existing structure everywhere: a header **"Graphics"** + a **Refresh**
button + a **scrollable label-link list** (`#gfxList` style), each `<a>` opening the
image in a new tab via `RC_API('/cockpit/graphics/' + file)`. All three get a
`max-height` + `overflow:auto` on the list so a long asset set never blows out the page.

- **Commentator Cockpit** (`src/cockpit/cockpit.html`) — *stays* in the right column
  under "Stint plan". Only change: apply the fixed `max-height` for visual parity.
- **Race Control** (`src/racecontrol/race-control.html`) — the **left column** "Schedule"
  card and a new "Graphics" card share **one row, 50/50**: wrap them in a nested
  `display:grid; grid-template-columns:1fr 1fr; gap:12px` at `race-control.html:185` — no
  new stacked row. (Anchor: replace the single full-width Schedule `.card` with the 2-col
  wrapper containing Schedule + Graphics.)
- **Director Panel** (`src/director/director-panel.html`) — the **right column** is the
  `.panes` sidebar containing `#chatBox` (Crew chat) and `#bchatBox` (Broadcast chat). Add
  the Graphics section **directly below the Broadcast chat**, after `#bchatBox`'s closing
  `</details>` (`director-panel.html:654`, before `</div><!-- /.panes -->` at 656), using
  the sidebar's `<details class="bus">` idiom so it matches the surrounding sidebar look.

"Same look" = identical structure + behaviour + the fixed max-height, styled to each
page's existing card/bus CSS so it reads as native on every page (not a foreign block).
The JS is the same small `loadGraphics()` + Refresh handler, ported to each page's helper
shim (`RC_API`/`j`).

**Not to be confused with** the Director Panel's existing **"Gfx" bus**
(`#gfxBus`, `director-panel.html:552`) — that is a row of OBS scene-item **toggle
buttons** (show/hide overlays), a different feature. The new section is a read-only image
browser; keeping it visually distinct (its own titled section) avoids conflation.

## Backward compatibility (racecast is released — v1.1.0)

Every piece is additive and degrades to today's behaviour:
- No `Internal` column / no header row → nothing internal → all graphics listed.
- No `manifest.json` (old installs, or `racecast graphics` not re-run) → no filtering.
- Endpoint, payload shape, and `resolve_graphic` are unchanged.

## Edge cases / out of scope

- **Non-Sheet seeded graphics.** `seed_missing_graphics` writes transparent placeholders
  for OBS-referenced graphics a league never listed in the Assets tab (e.g. weather
  overlays). Those have no Assets row, so no `Internal` box. To hide such a graphic a
  league adds a row for it with the box ticked (a link is *not* required — the internal
  set is parsed independently of the link). Left as-is otherwise; documented.
- The filter is a **listing** concern only, not access control. A crew member who knows an
  internal filename could still `GET /cockpit/graphics/<name>.png`. Acceptable: the
  graphics are not sensitive; the goal is decluttering, not secrecy. Explicitly noted so a
  future reviewer does not mistake it for a security control.

## Testing

- **Pure (get-graphics):** header/column location; `internal_from_csv` truthy parsing
  (`TRUE`/`FALSE`, `x`, `✓`, empty, header-less sheet → empty set); manifest content.
  Link parsing (`graphics_from_csv`) unchanged for header-less input (regression guard).
- **Pure (relay):** `list_graphics` with a manifest (omits internal), without a manifest
  (all), with a malformed/absent manifest (all), case-insensitive label match.
- **Front-end:** the existing `tests/test_racecast.py` / `tests/test_ui_server.py` route
  coverage is unaffected (endpoint unchanged); verify no page-specific JS regressions.
- **Wiki screenshots:** the three surfaces change → refresh `director-panel.png`, the
  race-control image, and `cockpit.html` shots via the `wiki-screenshots` skill, and run
  the `ui-visual-verification` gate for the rendered look.

## Files touched

- `src/relay/get-graphics.py` — header/column location, `internal_from_csv`, manifest
  write; new pure helpers.
- `src/relay/racecast-feeds.py` — `list_graphics` reads the manifest and filters.
- `src/cockpit/cockpit.html` — fixed max-height on the existing Graphics list.
- `src/racecontrol/race-control.html` — Schedule + new Graphics card in a 50/50 row.
- `src/director/director-panel.html` — new Graphics section under `#bchatBox` in the
  sidebar.
- `src/docs/wiki/Sheet-Template.md` — document the Assets `Internal` checkbox column.
- `tests/` — new pure tests for get-graphics internal parsing + `list_graphics` filter.
- `src/docs/wiki/images/…` — refreshed screenshots.

## Addendum (implementation): tailnet-open `/graphics` endpoint

During implementation, live verification surfaced a gap the original design missed: the
Director Panel is served **both** at the authed `/console/panel` (Funnel, per-person
token) **and** at the token-less `/panel` (tailnet). `/cockpit/graphics` requires console
auth unconditionally, so on the tailnet `/panel` the new director widget got a `401`.

Resolution (chosen by the operator): add a **tailnet-open root endpoint** rather than
degrade the widget — mirroring the broadcast-chat pattern (root `/broadcast-chat/data`
open on the tailnet + `/console/broadcast-chat/data` gated under the mount):

- **Relay:** new root `GET /graphics` (list) and `GET /graphics/<file>` (PNG) in
  `racecast-feeds.py`, served **without** console auth — the tailnet is the trust boundary
  (like `/status`, `/schedule/data`). They reuse the same `list_graphics` / `resolve_graphic`
  (so the `Internal` manifest filter still applies) and are **never funnelled** (only
  `/console` is), so nothing new is exposed publicly.
- **Policy:** `console_policy.py` classifies `["graphics"]` and `["graphics", <file>]` as
  `Requirement(ANY, False)`, so `/console/graphics` also works for any authenticated
  subject via the gate's generic ALLOW fall-through (the Funnel path).
- **Front-end:** all three pages now fetch `/graphics` (the global `window.fetch`→`RC_API`
  patch resolves it to `/graphics` on the tailnet and `/console/graphics` under the mount);
  the `<a href>` uses `RC_API('/graphics/<file>')`. The interim director self-hide-on-401
  is removed — the widget now loads in every context.
- Tests: `tests/test_console.py` asserts the two new routes are ANY-authenticated.

**Security note (extends the "Edge cases" section above).** `Internal` hides an asset from
the browse *list*, not from direct file serve: `resolve_graphic` does not consult the
manifest, so an internal graphic remains fetchable by its exact `<label>.png` — and via the
new root `GET /graphics/<file>` that fetch is **unauthenticated on the tailnet**. This is
acceptable and consistent with the design: the payload is broadcast-overlay PNG imagery (not
secret), the tailnet is invited-members-only (the same trust boundary that already serves
`/status` with stream URLs), and the route is never funnelled. `Internal` is a decluttering
convenience, not an access-control boundary — as already stated for the authed
`/cockpit/graphics/<file>` route.
