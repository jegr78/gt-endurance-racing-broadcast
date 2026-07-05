# Event Stop → Report flow + report fixes — design

**Date:** 2026-07-05
**Status:** Approved (brainstorming)
**Scope:** One implementation plan.

## Problem

Three connected shortcomings around the end of an event, discovered during a live
test (report `2026-07-05-test-event.html`, Discord post screenshots):

1. **No automatic end-of-event.** Ending the last broadcast part in the Director
   Panel stops only that part's OBS stream. The producer must then separately run
   `racecast event stop` and generate/send the report by hand. The desired flow:
   ending the *last* part should end the whole event — generate the report, post it
   to Discord, then tear down the racecast services.

2. **Report inaccuracies.**
   - Incident-log *Window* shows `HH:MM` only — no seconds.
   - The first incident shows `Duration 0s`. A non-green state seen in a single
     ~30s health sample collapses to a zero-width band (`to == from` in
     `health_store.derive_incidents`), so a real ~30s blip reads as `0s`.
   - No broadcast timeline: the `obs_stream_start`/`obs_stream_stop` events are
     recorded in the Health DB but never rendered, so the OBS-downtime figures have
     no reference points.
   - Every period OBS is not streaming (before start, between parts, after the final
     stop) is counted as a RED "off air" incident, tanking Uptime (the test shows
     **50%**) and flooding the incident log with intentional off-air.

3. **Discord post unusable.**
   - Posts under the webhook's *default* identity ("Spidey Bot") instead of
     "GT Racecast", because `_send_report_core` omits `username` from its
     `payload_json` (all other posts go through `notify._payload`, which sets
     `username = "GT Racecast"`).
   - The `.html` attachment renders as an expandable raw-source code block in
     Discord — noise, not a useful preview.

## Decisions (from brainstorming)

- **Last-part flow:** full teardown. A dedicated final-part confirmation, then:
  stop OBS stream → generate report → send to Discord → stop all racecast services.
- **Discord format:** rich embed with headline KPIs + the full HTML attached as a
  `.zip` (download-only), plus the username fix.
- **Incident duration:** measure until recovery (first healthy sample after, or
  window/session end); always display seconds.
- **Off-air handling:** add a broadcast timeline **and** exclude intentional off-air
  (outside the on-air part windows) from Uptime & the incident log.
- `racecast event stop` generates+sends the report **by default** (`--no-report`
  opts out) — for both the panel-triggered and manual terminal path.
- **Backward-compat fallback:** when no `part_*` events exist, fall back to
  `obs_stream_*` windows; when neither exists, keep the current session-wide
  behavior. A released product must not render empty/broken reports on old data.

## Architecture

Five surfaces change. The reporting/Discord logic stays in ONE place (the CLI); the
relay only detects the last part and spawns the CLI.

### A. CLI — `racecast event stop` (`src/racecast.py`)

`event_stop(rest)` gains a report step, default-on, before teardown:

1. Parse `--no-report`.
2. If reporting: `_build_report_file(...)` then `_send_report_core(path)` — run
   **while the relay is still up**, so `_report_name_map` resolves commentator names
   over the local relay `/schedule/data` (this also removes the "names unavailable"
   caveat from the auto path).
3. Then the existing teardown: `relay_stop` / `companion_stop` / `streams_stop`.
   OBS / Discord / Tailscale remain untouched (unchanged safety guard).

Report generation is best-effort: a failure logs a notice and teardown still runs
(never leave services up because a report failed).

### B. Relay — last-part detection + spawn (`src/relay/racecast-feeds.py`)

In the `/parts/end` handler, after the existing `validate_end` →
`set_stream(False)` → `part_store.end()`:

- Determine whether the just-ended part was the **last** one. Before `part_store.end()`,
  the current part is last iff `vm["live"] and vm["index"] == vm["count"]`
  (`parts.parts_view_model`); equivalently, after `end()`, `vm["complete"] == True`.
- If last: return `{ok: true, final: true}` to the panel, then **after flushing the
  response** spawn a detached `racecast event stop` on the producer's machine.
- Entry-point resolution: frozen mode re-invokes the binary (as the relay/streams
  daemons already do); source mode resolves `../racecast.py` relative to the relay
  script. The relay stays dependency-light — it *spawns* the CLI, never imports it.
- The spawned `event stop` generates+sends the report (relay still alive → names
  resolve) and then kills the relay (us) by PID. The panel goes dead afterward
  (expected — the event is over).

Recording of `part_start` / `part_end` (see D) is added to the `/parts/start` and
`/parts/end` handlers.

### C. Director Panel — final-part confirmation (`src/director/director-panel.html`)

`renderPartControl` already knows the view model. When ending the **last** part
(last startable / `index == count`), `openPartModal` shows a distinct final-confirm
copy: "This ends the broadcast — OBS stream stops, the post-event report is generated
and sent to Discord, and all racecast services stop." Normal (non-last) part-end
keeps today's copy. On submit, the same `POST /parts/end`; on a `{final: true}`
response the panel shows a terminal "Event ending — report sent" state.

Wiki screenshot `src/docs/wiki/images/director-panel.png` is refreshed in the same
change (UI surface changed — CLAUDE.md hard rule).

### D. Health store — part events + recovery-based incidents (`src/scripts/health_store.py`)

- **New event types `part_start` / `part_end`** (via the existing `record_event`),
  written by the relay's part endpoints. Metadata carries the 1-based part index and
  the stint/streamer where available. These mark the *intended* on-air windows and
  are the signal that distinguishes an intentional stop from a mid-part OBS crash.
- **`derive_incidents` duration until recovery.** Using the contiguous band list
  from `collapse_bands`, a non-green band's incident spans from its start to the
  **next band's start** (the recovering sample) when that gap is `<= gap_s`; at a
  window/session end with no recovery it extends by one `SAMPLE_INTERVAL_S`. Never
  bridge a hole larger than `gap_s` (mirrors `_fill_gaps`, so a blackout is not
  counted). `inc["end"]` is set to the same recovered/extended timestamp so the
  Window column and Duration stay consistent. Result: a one-tick blip reads as
  ~30s, not 0s.

### E. Report build — windows, seconds, timeline (`src/scripts/report_build.py`)

- **On-air windows** — a pure helper derives on-air windows from events:
  paired `part_start`→`part_end` (preferred), else paired
  `obs_stream_start`→`obs_stream_stop`, else `None` (→ legacy whole-session).
- **Metrics clipped to on-air windows** when windows exist: Uptime, incident log,
  feed reliability, and quality are computed over on-air time only. Intentional
  off-air (outside windows) is excluded. Band/sample intersection is clipped to the
  window bounds for accuracy (boundary error ≤ one sample interval).
- **KPIs:** keep *Session length* = full wall-clock (frm→to); add an **On air** KPI =
  total on-air-window seconds; **Uptime%** = healthy on-air seconds ÷ on-air seconds
  (not full session). Incidents count = incidents intersecting on-air windows.
- **Broadcast timeline (new section)** — a chronological table (Time incl. seconds,
  Event) built from `part_start`/`part_end` (+ any `obs_stream_*` that do not coincide
  with a part boundary, e.g. a mid-part crash/restart, labeled distinctly). Gives the
  downtime figures their reference points. The full-session health SVG strip stays
  (it is the visual timeline over the whole session, off-air visible as context).
- **Seconds everywhere:** `_fmt_clock` → `%H:%M:%S`; `_fmt_dur` includes seconds at
  all scales.
- **Legacy fallback:** when there are no windows, behavior is exactly today's
  (whole-session, off-air counted) — no empty reports on old data.

### F. Discord report post (`src/racecast.py` `_send_report_core` + `src/scripts/notify.py`)

- **Username fix:** `payload_json` includes `"username": notify.USERNAME`
  (and `avatar_url` if the other posts set one) → shows as "GT Racecast".
- **Rich embed:** a report embed builder in `notify.py` (same `_payload`/embed style)
  with headline KPI fields (Uptime, On air, Incidents, Session length, window). This
  is the useful inline content.
- **Zip attachment:** the HTML is zipped in-memory (stdlib `zipfile`) and attached as
  `<slug>.zip` (`text/html` → `application/zip`). Discord shows no source preview for
  `.zip` → download-only. (There is no API flag to suppress the `.html` code preview.)

## Data flow (last-part end)

```
Director Panel  --POST /parts/end-->  Relay
  Relay: validate_end; set_stream(False); record part_end; part_store.end()
  Relay: last part? -> respond {final:true}; spawn detached `racecast event stop`
                       (non-last -> respond {ok:true}, done)
  CLI event stop (relay still up):
     _build_report_file  (names resolve via /schedule/data)
     _send_report_core   (embed + username + zip -> Discord)
     relay_stop / companion_stop / streams_stop
```

## Testing

- `tests/test_health_store.py` — `derive_incidents` recovery duration (singleton →
  ~interval, not 0; multi-sample unchanged; no bridging across a > gap_s hole);
  `part_start`/`part_end` event round-trip.
- `tests/test_report_build.py` — on-air-window derivation (part > obs_stream >
  legacy); metric clipping to windows; On-air KPI + on-air uptime; broadcast timeline
  rows; `_fmt_clock`/`_fmt_dur` seconds; legacy fallback unchanged.
- `tests/test_notify.py` — report embed builder sets `username == "GT Racecast"` and
  KPI fields.
- `tests/test_report.py` — `payload_json` carries `username`; attachment is a `.zip`
  with `application/zip`; embed present.
- `tests/test_parts.py` — last/complete detection used for the `final` branch.
- `tests/test_event.py` — `event stop` runs report by default; `--no-report` skips;
  report failure still tears down.
- `tests/test_racecast.py` — dispatch/flag parse for `--no-report`.
- `tests/test_director_panel.py` — final-part confirmation copy + `{final:true}`
  terminal state.

## Out of scope / non-goals

- No new HTTP surface: `event stop` remains CLI-only; the relay *spawns* it locally.
  No takeover/Funnel endpoint is added.
- OBS / Discord / Tailscale teardown stays out of `event stop` (unchanged guard).
- Report stays a self-contained offline HTML (now zipped for Discord); no hosting.
- No reclassification of severities beyond the intentional-off-air exclusion.

## Backward compatibility

- Old Health DBs (no `part_*` events): report falls back to `obs_stream_*` windows,
  then to whole-session — never empty.
- `racecast event stop` default-on report is opt-out via `--no-report`; Discord post
  is a no-op without a configured webhook (unchanged).
