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

## Architecture

Six surfaces change. The lifecycle logic (stream-key resolution, start/end
confirmation, last-part auto-stop → report → teardown) is **reused unchanged** — the
only new logic is "which subset of Producer rows is active in this mode" plus the
two presentation touches (confirm phrase, report-title marker) and the UI toggle.

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

## Out of scope / non-goals

- **Remote-producer takeover for qualifying.** Qualifying is single-machine /
  single-part; the producer rotation is a race concept. (`takeover_plan` can already
  force `--qualifying` if ever needed — not wired here.)
- **Multi-part qualifying (Q1/Q2).** The classifier tolerates it; we build and test
  the single-part case.
- No new HTTP surface, no takeover/Funnel endpoint. `event stop` stays CLI-only; the
  relay spawns it locally (unchanged).

## Backward compatibility

- Producer tabs without a `Q` row: qualifying mode → empty parts subset → Parts
  control disabled (graceful, = "not configured"). Race mode unchanged.
- Old `part.json`: unaffected (index semantics unchanged; still 1-based into the
  active subset, which in race mode is the full list as before).
- Report title marker is best-effort (relay unreachable → no marker); the report still
  generates. `report_build.py` behavior is byte-identical for a non-qualifying title.
- Control Center: the toggle defaults off → `event start` with no `--qualifying`,
  today's behavior.
