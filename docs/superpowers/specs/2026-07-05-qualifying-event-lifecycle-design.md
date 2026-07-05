# Qualifying in the Event Start/Stop lifecycle — design

**Date:** 2026-07-05
**Status:** Approved (brainstorming)
**Scope:** One implementation plan.

## Problem

Qualifying (the session run the day before the race, a single stream) is today
wired into the relay **only at the feed layer** — not at the broadcast/parts
lifecycle layer. Two layers carry the name "qualifying":

1. **Feed source (`Relay.mode` ∈ {race, qualifying}).** Which Sheet tab the feeds
   pull from — `Qualifying` tab vs `Schedule` tab, one stream on Feed A, Feed B
   idle. **Already complete:** `--qualifying`, the Director-Panel mode toggle, and
   `/mode/race|qualifying`.

2. **Broadcast/Parts lifecycle (Producer tab → stream key → OBS stream → report →
   last-part auto-stop).** The actual stream start/stop loop. **Has zero qualifying
   awareness.** "Parts" come from the `Producer` tab (`Part | Producer | MagicDNS |
   Stream Key`); each part is a separate YouTube broadcast with its own stream key,
   assigned to a producer machine. The part index (`part.json`) and the feed `mode`
   never cross-reference.

**Consequence today:** `racecast event start --qualifying` switches only the feed
layer. The Director-Panel Parts control still shows the **race** parts (1,2,3) with
the **race** stream keys, so starting a "part" during qualifying would point OBS's
stream output at the wrong (race) YouTube broadcast. There is no clean start/stop
separation between the qualifying broadcast and the race broadcast.

## Decisions (from brainstorming)

- **Model the qualifying broadcast as a `Q` row in the existing `Producer` tab**
  (its own stream key + producer/MagicDNS). No separate tab.
- **The Parts control becomes mode-aware:** in `race` mode it operates on the
  numeric parts (today's behavior, unchanged); in `qualifying` mode it operates on
  the `Q` part(s) only.
- **Qualifying is exactly one part.** We design and test for the single-part case;
  the classifier tolerates more (`Q1`, `Q2`) but that is not a target.
- **End of the qualifying broadcast behaves exactly like the race's last-part end:**
  stop OBS stream → generate report → post to Discord → tear down all racecast
  services. This is a 1:1 reuse of the existing last-part auto-stop (`Q` is always
  the last/only qualifying part). `--no-report` remains the opt-out.
- **Confirmation phrase is label-based:** the type-to-confirm reads `START PART Q`
  (not `START PART 1`) for the qualifying part. Backward-compatible for race
  (`Part 1` → `START PART 1`).
- **Report title gets a `— Qualifying` marker** when the event ran in qualifying
  mode (affects the HTML `<title>`/`<h1>`, the filename slug, and the Discord embed
  title).
- **Control Center gains a qualifying toggle** next to Start Event, so an operator
  can start the event in qualifying mode from the UI (parity with the CLI
  `--qualifying`).
- **The Director Panel shows the schedule editor matching the current mode** — the
  race Schedule editor in race mode, the one-row Qualifying editor in qualifying
  mode. The mode toggle, the Submissions section, and the Parts control stay visible
  in both modes.
- **Cockpit stream-link submissions work in both modes.** A qualifying commentator
  submits from their cockpit; the director approves it into the **Qualifying** tab.
  (The submit path is already mode-aware; only the approve write is race-hardcoded.)

## Architecture

Seven surfaces change. The lifecycle logic (stream-key resolution, start/end
confirmation, last-part auto-stop → report → teardown) is **reused unchanged**, and
the schedule-derived read surfaces (cockpit tally/plan, race-control desk,
`/schedule/data`, submission target resolution) are **already mode-aware** — they read
the mode-aware `relay.source` property. The only new logic is "which subset of
Producer rows is active in this mode", the two presentation touches (confirm phrase,
report-title marker), the UI toggle, the mode-aware panel display, and the one
backend gap: the submission **approve** write.

### A. Data model — the `Q` part (Sheet-side, no migration)

The `Producer` tab gains a qualifying row, e.g.:

| Part | Producer | MagicDNS | Stream Key |
|------|----------|----------|------------|
| Part 1 | A | a.ts.net | ref-race-1 |
| Part 2 | B | b.ts.net | ref-race-2 |
| Q | A | a.ts.net | ref-quali |

The `get_stream_key` webhook resolves `ref-quali` to the dedicated qualifying
broadcast key (same Sheet-side mechanism the numeric parts already use). Convention:
**a part is *qualifying* iff its label, trimmed + uppercased, starts with `Q`;**
otherwise *race* (numeric / `Part N`). Existing Producer tabs without a `Q` row are
unaffected.

### B. Pure logic — `src/scripts/producer.py` + `src/scripts/parts.py`

`producer.py` (pure, no I/O):
- `part_kind(label) -> "qualifying" | "race"` — `Q`-prefix classifier.
- `active_producer_rows(rows, mode) -> [row, ...]` — filter the parsed Producer rows
  to the subset matching `mode` (`qualifying` → Q rows, `race` → the rest). Order
  preserved. This mirrors the feed-layer `active_source()`.

`parts.py` (pure):
- `part_confirm_token(label) -> str` — the token shown in the confirm phrase: strip a
  leading `Part` (case-insensitive) + whitespace. `"Part 1"` → `"1"`, `"Q"` → `"Q"`,
  `"Part Q"` → `"Q"`.
- `parts_intent_phrase(action, token)` now takes the **token** (was the numeric
  index). `parts_view_model` derives the token from the active row's label and puts
  it in `confirm_phrase` (so race stays `START PART 1`, qualifying reads
  `START PART Q`).
- `validate_start` / `validate_end` take the **active rows** (instead of the count)
  so they can recompute the same expected token to compare the typed intent against.
  Count is `len(rows)`; `is_last` stays `index == count`.

### C. Relay — mode-gated parts (`src/relay/racecast-feeds.py`)

- `Relay.active_producer_rows()` — returns
  `producer_mod.active_producer_rows(self.producer_source.get(), self.mode)`, mirroring
  the existing `active_source()` property for feeds.
- `/parts/data`, `/parts/start`, `/parts/end` read the **mode-filtered subset**
  instead of all producer rows. The `PartStore` index is 1-based into the active
  subset; in qualifying the subset is the single `Q` row → index 1. Because `Q` is
  the only (= last) part, `is_last` fires on its `/parts/end` → the existing
  `_spawn_event_stop` path runs → report + Discord + teardown. **No lifecycle code
  changes.**
- `set_mode` resets the part pointer to `{index: 1, live: false}` **when OBS is not
  currently streaming** (never reset a live pointer). This keeps a live panel-toggle
  mode flip coherent — otherwise a stale race index could read as "complete" against
  the single-row qualifying subset. Best-effort; the clean path remains
  `event start --qualifying` (which already resets `part.json` to index 1).

Backward compat: a Producer tab with only numeric parts → in qualifying mode the
subset is empty → the Parts control is disabled (`enabled: false`), exactly like
"no parts configured yet". Race mode is unchanged.

### D. CLI — `racecast event start --qualifying` (`src/racecast.py`)

**No change needed.** `event_start` already runs `_write_part_reset(_part_index(rest))`
(resets `part.json` to index 1) and forwards `--qualifying` to `relay_start`. With the
mode-gating from (C), index 1 in qualifying mode is the `Q` row → `/parts/start` fetches
the qualifying key → OBS streams to the qualifying broadcast. Qualifying day is
`event start --qualifying`; race day is `event start` — two cleanly separated sessions.

### E. Report — `— Qualifying` title marker (`src/racecast.py`)

- New best-effort helper `_relay_mode()` reads the local relay `/status` (the relay is
  still up during report generation) and returns `"race"` / `"qualifying"` / `None`
  (unreachable → `None`, no marker). Precedent: `_report_name_map` already reads the
  local relay during report build.
- `_build_report_file` (title used for `<title>`/`<h1>` + `report_filename` slug) and
  `_send_report_core` (Discord embed title) append `— Qualifying` to the base event
  title when `_relay_mode() == "qualifying"` (empty base title → just `Qualifying`).
- `src/scripts/report_build.py` stays **pure/mode-agnostic** — it receives the already
  marked title via its existing `event_title` argument. No signature change.

Note to verify at implementation: report name-resolution (`_report_name_map` via
`/schedule/data`) should resolve against the **active (qualifying)** schedule in
qualifying mode. The relay's `self.source` is a mode-aware property, so `/schedule/data`
is expected to follow mode already; confirm during implementation (worst case: names
render raw — non-blocking).

### F. Control Center — qualifying toggle (`src/ui/ui_ops.py` + `src/ui/control-center.html`)

- `ui_ops.py`: add `_qualifying_flag(value) -> ["--qualifying"] if value else []`, and
  register it in `PARAMS["event-start"]` alongside `stint`
  (`{"stint": _stint_arg, "qualifying": _qualifying_flag}`).
- `control-center.html`: add a checkbox next to the Start Event control;
  `opEventStart()` includes `qualifying: true` in the op params when checked. The op
  base (`["event", "start"]`) is unchanged; the flag flows through the existing
  `build_argv` param mechanism.
- **UI surface changed → refresh the Control Center screenshot** (`cc-*.png` for the
  view that hosts Start Event) in the same change, per the CLAUDE.md hard rule.

### G. Mode-aware schedule surfaces (Director Panel + submissions)

**Already mode-aware — no change (verify at implementation):** the Commentator
Cockpit (`/cockpit/data`: tally, stint plan, `my_stints`), the Race Control desk
(`/console/race-control/data`), `/schedule/data`, and the cockpit submission **target
resolution** (`POST /cockpit/submit`) all read `relay.source.get_rows()` (the
mode-aware `active_source()` property). In qualifying mode they follow the Qualifying
schedule for free. The plan verifies this rather than changing it.

**G1. Director Panel mode-aware display (`src/director/director-panel.html`).**
`relayPoll()` already GETs `/status` every 2 s and reads `d.mode === "qualifying"`
(line ~1414). Extend that always-on hook to drive section visibility (mirroring the
existing `.hidden` idiom used by `setTab`/the Parts control):
- Race mode → show the race Schedule editor `#urlsBox`; hide the qualifying editor row
  `#qualRow`.
- Qualifying mode → hide `#urlsBox`; show `#qualRow`.
- **Always visible in both modes:** the mode toggle (`#qualOn`/`#qualOff` + badge) so
  live switching stays possible, the Submissions section `#subsBox`, and the Parts
  control `#partControl` (server-gated, not mode-hidden).
- Optional: a small `QUALI` tag on qualifying rows in the submissions list (available
  from the new `mode` field, see G2).

**G2. Submission approve → correct tab (`src/scripts/cockpit_submissions.py` +
`src/relay/racecast-feeds.py`).** This is the only backend gap. A submission is
*created* against the mode-aware active schedule but *approved* into the race Schedule
tab unconditionally, and the stored entry records no tab.
- `cockpit_submissions.py`: add a `mode` field (`"race"` | `"qualifying"`) to the
  entry schema — `add_pending` accepts it (default `"race"`) and `_validate_entry`
  tolerates its absence (old pending files → `"race"`).
- `POST /cockpit/submit` (relay): pass `relay.mode` into `submission_store.add(...)`
  so the entry records the tab it targets. `target_line` is already the row number in
  the active tab, so the pair (`mode`, `target_line`) fully identifies the write.
- `POST /submissions/approve` (relay): branch on the entry's `mode` — call
  `setup_ctl.qualifying_set(target_line, …)` (tab=`Qualifying`, already exists) for a
  qualifying entry, else `schedule_set(...)` (today's path). The approve decision uses
  the entry's recorded mode, **not** the relay's current mode, so a director can
  approve a qualifying submission regardless of the relay's live mode.

Screenshot: the Director Panel's default (race-mode) view changes (the qualifying
editor row is no longer shown alongside the race editor), so
`src/docs/wiki/images/director-panel.png` is refreshed in the same change (CLAUDE.md
hard rule). The Cockpit and Race Control images do not change (no code change there).

## Data flow (qualifying end)

```
event start --qualifying
  _write_part_reset(1); relay_start(--qualifying ...)   # feeds -> Qualifying tab; mode=qualifying
Director Panel Parts control  (mode-gated -> Q subset, index 1)
  START PART Q  --POST /parts/start-->  Relay
     resolve ref-quali -> qualifying key -> OBS SetStreamService; set_stream(True); mark_live(1)
  END PART Q    --POST /parts/end-->    Relay
     set_stream(False); is_last (index==count==1) -> {final:true}; _spawn_event_stop
  event stop (relay still up):
     _build_report_file  (title + " — Qualifying")   # names resolve via /schedule/data
     _send_report_core   (Discord embed "… — Qualifying" + zipped HTML)
     relay_stop / companion_stop / streams_stop
```

## Testing

- `tests/test_parts.py` — `part_kind` (Q-prefix vs numeric), `active_producer_rows`
  (mode filter, order), `part_confirm_token` (`Part 1`→`1`, `Q`→`Q`), `parts_view_model`
  confirm phrase `START PART Q` for a Q row, `validate_start/end` token match against
  active rows, `is_last` true for the single Q part.
- `tests/test_ui_ops.py` — `event-start` builds `--qualifying` when the flag param is
  set; absent/false omits it; `stint` + `qualifying` compose.
- `tests/test_racecast.py` / `tests/test_report.py` — report title carries
  `— Qualifying` when `_relay_mode()` is qualifying (inject the mode reader); race /
  unreachable relay → no marker; filename slug + Discord embed title reflect it.
- `tests/test_racecast.py` — `event start --qualifying` dispatch unchanged (regression
  guard: still resets the part pointer + forwards the flag).
- `tests/test_submissions.py` — the entry `mode` field round-trips (default `"race"`
  when absent); approve of a `qualifying` entry selects `qualifying_set`, a `race`
  entry selects `schedule_set` (inject fake writers, assert which was called + the
  target row); `own_submission_target` against qualifying rows yields a Qualifying-tab
  line (mode-aware submit).
- `tests/test_director_panel.py` — mode-driven section visibility: race mode shows the
  race schedule editor / hides the qualifying row, qualifying mode reverses; the mode
  toggle, submissions, and parts control stay visible in both.

## Out of scope / non-goals

- **Remote-producer takeover for qualifying.** Qualifying is single-machine /
  single-part; the producer rotation is a race concept. (`takeover_plan` can already
  force `--qualifying` if ever needed — not wired here.)
- **Multi-part qualifying (Q1/Q2).** The classifier tolerates it; we build and test
  the single-part case.
- **Cross-mode pre-submission.** A commentator submits from the cockpit against
  whatever schedule the relay is *currently* in (mode-aware). Submitting a qualifying
  stream requires the relay to be in qualifying mode (the natural flow: qualifying is
  its own `event start --qualifying` session). Pre-submitting a qualifying stream while
  the relay is in race mode is out of scope.
- No new HTTP surface, no takeover/Funnel endpoint. `event stop` stays CLI-only; the
  relay spawns it locally (unchanged). The submission approve `/submissions/*` stays
  tailnet-only (unchanged); only its write target becomes mode-correct.

## Backward compatibility

- Producer tabs without a `Q` row: qualifying mode → empty parts subset → Parts
  control disabled (graceful, = "not configured"). Race mode unchanged.
- Old `part.json`: unaffected (index semantics unchanged; still 1-based into the
  active subset, which in race mode is the full list as before).
- Report title marker is best-effort (relay unreachable → no marker); the report still
  generates. `report_build.py` behavior is byte-identical for a non-qualifying title.
- Control Center: the toggle defaults off → `event start` with no `--qualifying`,
  today's behavior.
- Submission entries created before this change have no `mode` field → treated as
  `"race"` → approved via `schedule_set` exactly as today. No pending-file migration.
- Director Panel: with the relay in race mode (the default), the panel shows the race
  schedule editor as before; the qualifying editor simply hides instead of sitting
  permanently alongside it.
