# Top-3 Teams — batch apply (design)

Date: 2026-06-29
Status: approved (design phase)

## Problem

The Director Panel has three podium-slot dropdowns **P1 / P2 / P3** (`TEAM_FIELDS`
in `src/director/director-panel.html`). Each dropdown `change` fires **immediately**:
`GET /setup/team/<slot>/<value>` → the relay sets an optimistic `HudSource`
team-override **and** pushes a single-slot Sheet write in the background
(`action:"teams"`, one slot per call).

Because every position is pushed live the instant its dropdown changes, updating more
than one slot produces a transient inconsistent broadcast HUD: the director changes P1
→ the HUD shows the new team in P1 while P2 still holds the old value. If the team now
in P1 was previously P2, it appears **twice** until P2 is corrected. Live feedback from
a real event flagged this duplication.

## Goal

Make Top-3 changes **staged by default**: the director sets P1/P2/P3, then a single
**"Apply Top 3"** action commits all three **atomically in one relay request** (so the
HUD never observes a partial/duplicated standing) and writes them back to the Sheet. A
per-row **Batch** toggle (default **ON**) can be switched **OFF** to restore today's
live per-dropdown behavior — the live path stays first-class for directors who prefer
it.

## Key decisions (locked during brainstorming)

1. **Both modes, batch is the default.** Batch (stage → Apply) is the new default; the
   existing live per-dropdown push remains, reachable by turning the row's Batch toggle
   OFF. Backward compatible — racecast is released and the live path is unchanged.
2. **Atomicity lives in the relay, not the client.** The fix is a single relay request
   that sets all three overrides under **one** `HudSource` lock acquisition. Because
   `/hud/data` reads under the same lock, it can never observe a partial top-3. Sending
   three sequential HTTP calls from the client would still let the HUD poll interleave
   between them, so a batch endpoint is required, not just client-side staging.
3. **No Apps Script change.** The Sheet write-back reuses the **existing** single-slot
   `teams` webhook action (one call per slot, sequentially, in one background thread).
   The broadcast HUD is already correct via the atomic overrides, so the per-slot Sheet
   writes are not time-critical and need no batched protocol — this ships on every
   league immediately without coordinating an Apps Script bump.
4. **Validation is all-or-nothing.** `set_teams` validates all three values against the
   roster first; if any is invalid, nothing is applied and nothing is written.

## Architecture

### 1. `HudSource.set_teams_override(entries, now=None)` (relay, `racecast-feeds.py`)

New method that sets multiple slot overrides under a **single** `self.lock`
acquisition (the existing `set_team_override` takes the lock per call). `entries` maps
slot index `0..2` → a resolved team entry. This single-lock write is the atomicity
guarantee: `/hud/data` (which reads `team_overrides` under the same lock) never renders
a partial top-3, so no duplication frame can occur. `set_team_override` is left in
place for the live single-slot path.

### 2. `SetupControl.set_teams(teams, now=None)` (relay)

- `teams` is a dict `{"p1":<name>, "p2":<name>, "p3":<name>}`. The panel always sends
  all three current selection values (unchanged slots included — idempotent).
- Guards mirror `set_team`: webhook configured? each key in `TEAM_SLOTS`? each value in
  `self.hud.roster_names()`? **Validate all three before applying anything** — any
  failure returns `{"error": …}` and writes nothing.
- On success: build entries via `self.hud.resolve_team(name)` for each slot and call
  `self.hud.set_teams_override(...)` (immediate, atomic). Then spawn **one** background
  thread (`_push_teams`) that writes each slot via the existing single-slot `teams`
  webhook action (`full_team_name` → `{"action":"teams","slot":n,"name":full}`)
  sequentially, then calls `self.hud.refresh()` once at the end.
- Returns `{"ok": True, "slots": ["p1","p2","p3"], "pending": True}`.
- Partial Sheet-write failure behaves exactly like today's single path: overrides are
  already live (broadcast correct), `push_status` becomes `"failed"` and `last_error`
  is set, surfacing the existing red "SHEET SYNC FAILED" panel banner.

### 3. Relay routing (`do_POST`)

Add `POST /setup/teams` next to `POST /pov/set`:

```python
if p == ["setup", "teams"]:
    return self._send(setup_ctl.set_teams(body.get("teams")))
```

The existing `GET /setup/team/<slot>/<value>` (live single-slot) is unchanged.

### 4. Director Panel (`src/director/director-panel.html`)

- A **Batch** toggle (checkbox) on the Top-3 row, persisted in `localStorage`
  (`racecast.top3.batch`), **default ON** when unset.
- **Batch ON:** a dropdown `change` stages locally only — marks the select dirty and
  gives it a distinct **"staged"** style (separate from the existing `pending`
  override style); no fetch. An **"Apply Top 3"** button is enabled whenever any slot
  is staged-dirty; clicking it `POST`s `/setup/teams` with all three current select
  values, then on success clears the dirty flags (the selects move to `pending` until
  the Sheet poll confirms). Turning the toggle OFF discards unapplied staging and
  re-syncs the selects from `/setup/data`.
- **Batch OFF:** a dropdown `change` calls the existing `teamSet` live single-slot push
  — unchanged behavior.
- **Poll guard:** `setupPoll` must not overwrite a staged-dirty select. Extend the
  existing `sel === document.activeElement` guard with a dirty guard, mirroring the
  Schedule rows' `rowBusy` / `SAVE_GUARD_MS` pattern already in the file.
- In read-only (`d.push === "disabled"`), the toggle and Apply button are disabled,
  like the dropdowns today.

## Testing

`tests/test_setup.py` (pure `SetupControl` + a fake push capturing payloads, the
existing pattern):

- `set_teams` rejects an unknown slot key and a value not in the roster → `{"error":…}`
  with **no** override set and **no** webhook push.
- `set_teams` happy path: all three overrides set (`team_pending()` == `{0,1,2}`), three
  `teams` webhook payloads emitted with the `full_team_name` values, response
  `pending: True`.
- Atomicity at the source level: `HudSource.set_teams_override` applied under one lock
  leaves `team_overrides` holding all three entries.
- Routing: `POST /setup/teams` dispatches to `set_teams` (relay handler test, matching
  how existing POST routes are covered).

## Out of scope

- No batched `teams` webhook protocol / Apps Script change (decision 3).
- The **Standings** still-graphic (a Sheet-driven PNG scene) is unrelated; this change
  is only the HUD lower-third P1/P2/P3 overlay slots.
- No change to the live single-slot path beyond it becoming the non-default mode.

## Docs / artifacts

- Director Panel UI surface changes → regenerate `src/docs/wiki/images/director-panel.png`
  in the **same** change via the `wiki-screenshots` skill (CLAUDE.md hard rule).
- Webhook protocol is unchanged, so no `Sheet-Webhook` wiki edit is required; add a brief
  note about batch mode to the panel-facing operator docs if one already documents the
  Top-3 controls.
