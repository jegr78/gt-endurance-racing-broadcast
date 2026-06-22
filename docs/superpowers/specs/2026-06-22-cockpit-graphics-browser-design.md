# Cockpit Graphics Browser — Design

**Date:** 2026-06-22
**Status:** Approved (brainstorming)

## Problem

Commentators work from the Commentator Cockpit (`/cockpit/*`, reachable over
Tailscale Funnel as `/console/cockpit/*`). During a broadcast they want quick
access to the league's broadcast **graphics** — standings, schedule, results,
weather overlays, standby, etc. — to read information off them while on air.
Today the cockpit exposes the live program monitor, tally, timer, chat, cues and
the stream-link submission form, but no way to look at the graphics themselves.

## Goal

Show the commentator the **full list of broadcast graphics** in the cockpit.
Selecting one **opens that graphic in a new browser tab**. Read-only: the cockpit
never modifies graphics. Only the still graphics are needed (no media/clips).

## Where graphics live

Broadcast graphics are pure runtime, downloaded by `src/relay/get-graphics.py`
from the Sheet **Assets** tab into `runtime/<profile>/graphics/<Label>.png` — the
Sheet label *is* the filename, no mapping table. The relay already resolves this
directory at startup (`graphics_dir = os.path.join(runtime, "graphics")` in
`src/relay/racecast-feeds.py`) and uses it for the overlay preview frame
(`resolve_preview_frame`).

## Design

### Two new token-gated endpoints under `/cockpit/*`

Both live under the existing `/cockpit` namespace, so they are reachable over
Funnel via the `/console/cockpit/*` mount — **no new public surface**. Both
authenticate with the standard cockpit pattern: call `self._console_auth()` at
the top, and `return` immediately if it returns `None` (it already sent 401/429).

1. **`GET /cockpit/graphics`** → JSON list.
   - Reads the `*.png` files in the active profile's `graphics_dir`.
   - Returns `{"graphics": [{"name": "<label>", "file": "<label>.png"}, ...]}`,
     sorted case-insensitively by name. `name` is the filename without the
     `.png` extension (the Sheet label).
   - A missing or empty `graphics_dir` yields `{"graphics": []}` — never an error.
   - Lists **all** `.png` files, including technical frames like `Overlay.png`
     (no exclusion list to maintain).

2. **`GET /cockpit/graphics/<file>`** → serves the PNG.
   - Path safety mirrors the existing `resolve_asset` pattern: a strict filename
     regex (no slashes, no `..`), then `realpath` containment inside
     `graphics_dir` (reject anything that does not start with `graphics_dir +
     os.sep`). On success, serve with `_send_file(path, "image/png")`.
   - Content-Type is the constant `"image/png"` — never derived from the request.
   - Unknown / non-matching file → 404.

### Pure helper

Add a pure, unit-testable resolver alongside the existing asset helpers, e.g.:

- `list_graphics(graphics_dir) -> list[dict]` — directory scan + sort, tolerant of
  a missing dir.
- `resolve_graphic(graphics_dir, name) -> (path, "image/png") | None` — strict
  filename validation + realpath containment.

Wire `graphics_dir` into `make_handler(...)` (a new keyword param, defaulting to
`None`) so the HTTP layer stays thin and the logic is testable without a server.
The relay's startup wiring passes the already-computed `graphics_dir`.

### Cockpit UI (`src/cockpit/cockpit.html`)

- New card **"Graphics"**, styled like the existing sections (e.g. the chat card).
- On page load, fetch `/cockpit/graphics` once and render a compact **clickable
  name list**. Each entry is an
  `<a target="_blank" rel="noopener">` whose `href` is built with
  `RC_API('/cockpit/graphics/' + encodeURIComponent(file))`.
  - **Why `RC_API` explicitly:** the page's fetch shim only rewrites `window.fetch`
    to prepend `RC_API_BASE` (`/console` behind Funnel). An `<a href>` / new tab is
    not `fetch`, so the href must be resolved through `RC_API(...)` by hand or the
    link breaks under the Funnel mount.
  - Auth in the new tab is carried by the `rc_console` cookie (HttpOnly, Secure,
    SameSite=Lax) on a same-origin GET — no token in the URL.
- **Empty state:** render "No graphics available" when the list is empty.
- **Refresh:** a small "Refresh" affordance re-fetches the list (covers a producer
  re-downloading graphics mid-event). No background polling — the graphics set is
  effectively static during an event.

### Security boundary

The graphics are the same assets that go on air; they are no more sensitive than
the already-exposed program monitor (`/cockpit/program`). Both new routes sit
under the existing `/console` mount — no new Funnel surface is added, and feed
stream URLs / OBS-WebSocket remain tailnet-only as before.

### Scope (deliberately excluded)

- Cockpit only (commentators). The Race Control desk could surface the same list
  later trivially, but that was not requested — no added scope now.
- Still graphics only. Intro/Outro media clips (`runtime/<profile>/media/`) are
  out of scope.
- No thumbnails — a clickable name list per the chosen UI.

## Testing (`tests/test_cockpit.py`)

Extend the existing `_cockpit_client()` harness to pass a `graphics_dir` (a temp
dir seeded with a few dummy `.png` files).

- `GET /cockpit/graphics` without a token → 401.
- `GET /cockpit/graphics` with a valid token → 200, sorted list of the seeded
  names, each `{name, file}` with `name` == file minus `.png`.
- Missing/empty `graphics_dir` → 200 with `{"graphics": []}`.
- `GET /cockpit/graphics/<file>` with a valid token → 200, `Content-Type:
  image/png`, body equals the file bytes.
- Path-traversal attempts (`../`, absolute paths, names with slashes) → 404 and
  never escape `graphics_dir`.
- Unknown filename → 404.
- Pure-helper unit tests for `list_graphics` / `resolve_graphic` (sorting, missing
  dir, containment) without standing up a server.

## Files touched

- `src/relay/racecast-feeds.py` — two routes in `do_GET`, two pure helpers,
  `graphics_dir` param on `make_handler`, startup wiring.
- `src/cockpit/cockpit.html` — the "Graphics" card + fetch/render JS.
- `tests/test_cockpit.py` — endpoint + helper tests.

## Wiki / screenshots

The Crew Console (cockpit) is a documented UI surface. Per the repo rule, if the
cockpit's visible appearance changes, refresh the matching wiki screenshot in the
same change. Confirm which image under `src/docs/wiki/images/` shows the cockpit
and recapture it from a local dev build when implementing.
