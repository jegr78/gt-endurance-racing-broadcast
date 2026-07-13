# Report streamer-attribution fix (#500)

**Date:** 2026-07-13
**Issue:** [#500](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/500)
**Scope:** `src/relay/racecast-feeds.py` (sampling), `src/scripts/health_store.py`
(schema v6), `src/scripts/report_build.py` (attribution + surfacing), the report
HTML template, and the matching unit tests. Single PR into `main`.

## Problem

The post-event report's per-streamer breakdown (on-air time + stint count)
mis-attributes, both traced to how the on-air stint is **sampled** into the health
history. Observed in the N24 24h report (2026-07-11): **JeGr listed with 3 stints
instead of 4**.

- `report_build.py::_on_air(sample_groups, name_for_stint)` collapses each health
  sample's `live_stint` into contiguous bands and credits each band's duration **and**
  the stint (into a `set`) to `name_for_stint[live_stint]`. Per-streamer `stints`
  = `len(set)`, `seconds` = summed band duration.
- The sampled field is `_health_snapshot`'s
  **`"live_stint": self.feeds[live_feed()].idx + 1`** — the on-air feed's **physical
  pull index +1**, **not** the display stint (`on_air_row_idx()`).

### Problem 1 — same-URL back-to-back counts as ONE stint (report-side, present)

A same-URL back-to-back continuation (one commentator staying on a single stream
across two stint rows, e.g. N24 stints 7→8) is by design a single pull: the pull
index stays on the slot head (stint 7) while only the **display** row advances to 8
(`on_air_row_idx()`). So `live_stint` samples `7` for the whole 7+8 window → the
streamer's stint `set` is `{7}`, never `{7,8}` → **stint count is under by 1**. Time
is still correct (same streamer). **This reproduces on a perfectly healthy relay** —
it is independent of any desync. It is the JeGr 3-instead-of-4 case.

### Problem 2 — time mis-attribution during a desync (root already fixed)

During the N24 event the on-air **index tracking** was corrupted (the #491 same-URL
double-pull desync + manual sheet surgery + a source collapse + a spontaneous
stint-11 takeover that did not advance the index). The sampled `live_stint` stuck on
one stint while later stints were actually on air → time credited to the wrong
streamer. This is **garbage-in**: the report aggregated corrupted live samples. The
data root (the desync) is **already fixed by #491 (single-pull guard) + #494 (desync
detect/recover)**, both merged. The report cannot retroactively heal already-recorded
history — but it **can** flag a window where a desync was active as unreliable, so a
future confidently-wrong total is surfaced as suspect instead.

## What already exists (so we don't rebuild it)

- **`on_air_row_idx()`** already returns the 0-based schedule row currently ON SCREEN,
  continuation-aware and clamped to the active schedule. In normal operation it equals
  the on-air feed's pull index; during a same-URL back-to-back it sits one row ahead of
  the still-parked pull. Sampling `on_air_row_idx() + 1` is therefore the correct
  "who was on screen" stint.
- **The pull index is not lost** if we repurpose `live_stint`: `feed_a_stint` /
  `feed_b_stint` already record each feed's `f.idx + 1`, and `live_feed` records which
  is on air — so the physical pull index stays reconstructable from the persisted
  sample.
- **`live_stint` is charted nowhere in the Health-Monitor.** It is absent from
  `health_store.BAND_FIELDS`, `NUMERIC_FIELDS`, and `STATE_KEY_FIELDS`. The **only**
  consumer of the column is `report_build._on_air`, whose correct semantic *is* the
  display stint. The change is therefore low-risk and cannot regress the dashboard.
- **`self._desync`** (#494) is a `{"active": bool, ...}` block recomputed each
  heartbeat by `_compute_desync`. In `_heartbeat_loop`, `_refresh_health` (→
  `_compute_desync`) runs **before** `_health_snapshot` on the same `now`, so
  `self._desync["active"]` is fresh at sample time.

## Design

### Component 1 — Core fix (Problem 1): `live_stint` = display stint

In `src/relay/racecast-feeds.py::_health_snapshot`:

```python
- "live_feed": live, "live_stint": self.feeds[live].idx + 1,
+ "live_feed": live, "live_stint": self.on_air_row_idx() + 1,
```

- Semantics move from "physical pull index" to "which stint was on screen"
  (continuation-aware, clamped). In normal operation the value is identical
  (`on_air_row_idx() == feeds[live].idx`), so **no off-by-one and no regression** in the
  common case. Only a same-URL back-to-back differs — the display stint is one row
  ahead of the parked pull, so `collapse_bands` now splits at the handover and the
  streamer's stint `set` becomes `{7, 8}` (count fixed), while the summed duration is
  unchanged (same streamer across both bands → same total).
- `report_build._on_air` is **unchanged** — it reads `live_stint`, now correctly the
  display stint.
- Update the inline comment at the sampling line to document the display-stint
  semantic (who is on screen, back-to-back-aware).

### Component 2 — Desync annotation (AC #4)

**Schema v6 (`src/scripts/health_store.py`):** add an `INTEGER` column
`desync_active`.

- Add `"desync_active"` to `COLUMNS`, add `desync_active INTEGER` to the `_CREATE`
  table, and add a lossless `ALTER TABLE samples ADD COLUMN desync_active INTEGER`
  upgrade path in the same place the v3/v5 columns are added (only-if-missing). A
  pre-v6 DB gets the column as `NULL`, read as "no desync known".

**Sampling (`_health_snapshot`):**

```python
"desync_active": 1 if self._desync.get("active") else 0,
```

placed alongside the existing `live_feed` / `live_stint` fields. (Fresh per the
heartbeat ordering noted above.)

**Report surfacing (`report_build._on_air`):** add one field
`"desync_seconds": float` to the returned dict — the total duration, within the
on-air-clipped sample groups `_on_air` already receives, of bands where
`desync_active == 1`. Computed by collapsing a `[(ts, desync_active)]` band list with
the same `collapse_bands` used for the stint bands and summing the "active" bands'
`to - from`. `None`/missing `desync_active` (old DBs) collapses to a non-active band →
contributes `0`, so old reports simply show no warning.

The report HTML template renders a warning badge **only when `desync_seconds > 0`**,
near the per-commentator on-air table:

> ⚠ A ping-pong desync was active for **Xm Ys** of this event — per-commentator
> attribution during those windows may be unreliable.

KISS: a single total (seconds) drives a boolean badge — no per-window list.

### Backward compatibility

- No column is renamed. Only the **semantic** of `live_stint` changes (single consumer,
  now correct). Old DBs keep their pull-index `live_stint` values; the report cannot
  heal those historical rows (a same-URL back-to-back stays under-counted in an
  already-recorded event) — documented, not fixed.
- `desync_active` is added losslessly and read NULL-tolerantly, so an old DB reports
  cleanly with no desync badge.

## Tests

- **`tests/test_report_build.py`**
  - Back-to-back attribution: samples with `live_stint` 7→8, both resolving to the same
    name via `name_for_stint`, yield **2 stints** for that commentator and the summed
    duration is unchanged/correct.
  - A distinct-name handover (7→8 different names) still attributes each band to its own
    name (no regression).
  - `desync_seconds`: a group containing a `desync_active == 1` band yields
    `desync_seconds > 0` (≈ the band duration); a group with no desync yields `0`; a
    group of old samples missing `desync_active` yields `0`.
- **`tests/test_health_store.py`**
  - v6 migration: opening a pre-v6 DB (no `desync_active`) adds the column losslessly;
    existing rows read `desync_active == None`.
  - Round-trip: a recorded sample with `desync_active = 1` reads back `1`.
- **`tests/test_pov.py`** (`_health_snapshot` shape)
  - `live_stint` equals the display stint (`on_air_row_idx() + 1`), and `desync_active`
    is present in the snapshot dict.

## Explicitly out of scope (follow-up)

- **Spontaneous-takeover awareness** (AC #3 optional): a mid-stint substitution that
  does not advance the stint index is invisible to `name_for_stint[live_stint]`. The
  report trusts the schedule-derived name map. Recording the on-air *streamer* directly
  at sample time (rather than resolving it from a stint index after the fact) is a
  larger, separate change — deferred.

## Acceptance criteria (the #500 items this PR closes)

- [ ] A same-URL back-to-back (two consecutive same-URL stints, one commentator) is
      reported as **two** stints for that commentator, not one, on a healthy relay,
      with the on-air duration still correct.
- [ ] The `live_stint` → display-stint change is verified against `report_build._on_air`
      (fixed) and the Health-Monitor consumers (unaffected — `live_stint` is not
      charted); old-DB backward compat is handled.
- [ ] Unit coverage for the same-URL back-to-back attribution and the duration in
      `report_build._on_air` (pure — synthetic samples).
- [ ] A report window where a #494 desync was active is annotated as
      "attribution may be unreliable" (a `desync_seconds`-driven badge), with unit
      coverage and a lossless health_store v6 migration.
