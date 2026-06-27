# Cockpit Stint Plan (read-only) — design

**Date:** 2026-06-27
**Surface:** Commentator Cockpit (`src/cockpit/cockpit.html`, `/cockpit/*`)

## Goal

Show a compact, read-only list of the streamer stint plan (stint number +
streamer name) in the cockpit's right column, directly below the Race Timer,
so a commentator sees the whole running order without leaving the cockpit.

Each row: **stint label + streamer name**. No stream URLs (the data is reachable
over the public Funnel, so it stays inside the same redaction boundary as
`/console/takeover/status` and the Race Control desk).

## Decisions

- **Emphasis:** highlight the on-air stint (green `ON AIR` pill, mirroring the
  Race Control desk) AND this commentator's own stints (subtle accent).
- **Height:** a fixed, small max-height showing ~3 stints at once (~110px), with
  its own scroll; auto-scroll to the on-air row. The Graphics card stays visible
  below it.

## Backend — `src/relay/racecast-feeds.py`

New pure, unit-testable helper next to `race_control_schedule`:

```python
def cockpit_schedule(rows, live_idx, me_key):
    """Redacted stint plan for the cockpit's read-only stint-plan card.
    rows are ScheduleSource 4-tuples (url, streamer, stint, line); live_idx is
    the on-air feed's row index; me_key is the token's streamer_key. NO stream
    URL in the output (same redaction boundary as /console/takeover/status).
    Pure."""
    return [{"stint": st, "streamer": n,
             "on_air": i == live_idx,
             "mine": asset_key(n) == me_key}
            for i, (_u, n, st, _l) in enumerate(rows)]
```

Why a dedicated function instead of reusing `race_control_schedule`: that helper
marks rows via the full `live_map`, so it flags **both** the on-air feed and the
pre-loaded off-air feed's staged row. The cockpit wants exactly the one on-air
row marked, plus the per-row `mine` flag.

In the `/cockpit/data` handler (around line 5093), add to the `tally` payload:

```python
"schedule": cockpit_schedule(rows, live_idx, me),
```

`rows` and `live_idx` are already resolved in that handler — no new reads.
Mode-aware for free: `relay.source` already reflects race vs. qualifying.

## Frontend — `src/cockpit/cockpit.html`

- New card in the right column between the Race-Timer card and the Graphics card:
  `<h2>Stint plan</h2>` + a scrollable container `#stintPlan`
  (`max-height: ~110px; overflow:auto`).
- `renderStintPlan(d)`:
  - One row per `d.schedule` entry: `stint label · streamer name` via
    `textContent` (XSS-safe).
  - On-air row: green `ON AIR` pill + highlight (reuse the Race Control
    `.live` / `.onair` styling idiom).
  - Own rows (`mine`): a subtle left accent border / faint background.
  - After render: `scrollIntoView` the on-air row.
  - Empty `schedule` → "No stints scheduled yet."
- Hook into the existing `pollTally()` loop (2 s): call `renderStintPlan(d)`
  alongside `renderTally(d)` / `renderSubmit(d)`.

## Tests — `tests/test_cockpit.py`

`cockpit_schedule`:
- correct `on_air` flag (only the `live_idx` row) and `mine` flag (asset_key match),
- **no `url`/stream URL key** in any output dict,
- empty rows → `[]`,
- qualifying single-row schedule.

## Docs

- Update the CLAUDE.md cockpit paragraph to mention the read-only stint-plan
  field on `/cockpit/data`.
- UI surface changed → the cockpit wiki screenshot is stale. Regenerate it in the
  same change via the `wiki-screenshots` skill (CLAUDE.md hard rule).
