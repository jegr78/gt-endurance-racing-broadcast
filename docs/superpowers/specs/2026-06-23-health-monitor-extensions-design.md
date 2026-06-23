# Health Monitor Extensions — Design Spec

**Date:** 2026-06-23
**Builds on:** PR #282 (the original Health Monitor — `src/scripts/health_store.py`,
the relay heartbeat sampler, `/health-monitor`, `src/console/health-monitor.html`).
**Status:** Approved design, ready for implementation plan.

## Goal

Turn the Health Monitor from "is each subsystem reachable?" into a real
broadcast-health dashboard by sampling richer OBS statistics, the relay feeds'
selected stream quality, and the connectivity surfaces the show depends on
(Funnel, Tailscale, Companion, Sheet-push) — with the genuinely
broadcast-critical signals driving the existing green/yellow/red rollup and
Discord alerts, and everything else as observational charts/bands.

## Scope (one cohesive feature, phased)

This is mechanically uniform — every new check is *one column (or a few) +
one sampler block + one band/chart over the existing pipeline* — so it is a
single spec. The implementation plan splits it into independently testable
phases: (1) schema migration + OBS-stats sampling, (2) connectivity checks +
critical-signal logic, (3) feed quality, (4) UI + wiki screenshot.

## Hard constraints (inherited)

- **Pure Python stdlib only** — no new runtime dependencies. OBS data comes
  through the existing `src/scripts/obs_ws.py` v5 client; Tailscale/Funnel via
  the `tailscale` CLI (already a runtime dep); Companion via a stdlib TCP
  connect.
- **Redaction by construction** — every new field is a boolean, a number, or a
  short quality label. No stream URLs, no `sheet_id`, no Funnel hostname is ever
  stored or returned. `_health_snapshot` stays an explicit allowlist. The
  redacted `/console/takeover/status` (live/league/event_title/timer/mode) is
  **unchanged** — health stats never join it.
- **Best-effort sampling** — every new sampler block is wrapped in its own
  `try/except`; a failure sets only its fields to `None` and the heartbeat
  continues (same contract as the existing timer sample and the `obs_ws`
  helpers, which never raise).
- **Tests run on any machine / CI (incl. Windows)** — no real IPs, no machine
  paths; close every SQLite connection in tests (Windows can't delete an open
  file). New pure logic is unit-tested; the heartbeat wiring stays thin.
- **English-only** code and docs.

## Architecture (Approach A — extend the existing pipeline)

One wide `samples` table, one heartbeat sampler, the existing
`BAND_FIELDS`/`NUMERIC_FIELDS`/`STATE_KEY_FIELDS` taxonomy. The migration adds
columns; the heartbeat gains an OBS-stats call and the connectivity probes; the
page gains grouped bands and charts. Export/import and the producer-handover
pull carry the new columns for free (they serialize generically over
`COLUMNS`). Rejected alternatives: a separate long/EAV metrics table (breaks the
wide-table pattern, second query path, no real gain at this field count) and
live-only/no-persistence (kills the historical-trend purpose).

---

## 1. New sampled fields

17 new columns, classified into the three existing display categories.

### Critical bands (can turn the rollup yellow/red → fire Discord alerts)

| Field | Type | Source | Bad when |
|---|---|---|---|
| `stream_active` | INTEGER (0/1) | `GetStreamStatus.outputActive` | OBS reachable & `outputActive=false` |
| `stream_reconnecting` | INTEGER (0/1) | `GetStreamStatus.outputReconnecting` | `true` |
| `funnel_ok` | INTEGER (0/1) | `tailscale funnel status` (local) | expected-on but down (see §3) |
| `sheet_push_ok` | INTEGER (0/1) | existing push `last_error` (passive) | `SHEET_PUSH_URL` set & last push failed |

### Observational bands (green = ok, neutral/blue = down — no alarm)

| Field | Type | Source |
|---|---|---|
| `tailscale_up` | INTEGER (0/1) | `tailscale status` backend state |
| `companion_ok` | INTEGER (0/1) | stdlib TCP connect to the Companion bind port |

### Numeric charts (observational)

| Field | Type | Source | Group |
|---|---|---|---|
| `stream_kbps` | REAL | Δ `outputBytes` / Δt (see §2) | OBS Output |
| `stream_dropped_pct` | REAL | `outputSkippedFrames`/`outputTotalFrames` × 100 | OBS Output |
| `stream_congestion` | REAL | `GetStreamStatus.outputCongestion` (0–1) | OBS Output |
| `obs_cpu_pct` | REAL | `GetStats.cpuUsage` | OBS Resources |
| `obs_mem_mb` | REAL | `GetStats.memoryUsage` | OBS Resources |
| `obs_fps` | REAL | `GetStats.activeFps` | OBS Resources |
| `obs_render_skipped_pct` | REAL | `renderSkippedFrames`/`renderTotalFrames` × 100 | OBS Resources |
| `obs_disk_free_mb` | REAL | `GetStats.availableDiskSpace` | OBS Resources |

### Snapshot text (per-feed card, no chart)

| Field | Type | Source |
|---|---|---|
| `feed_a_quality` | TEXT | selected streamlink quality from feed stdout (e.g. `720p`, `source`) |
| `feed_b_quality` | TEXT | same, Feed B |
| `pov_quality` | TEXT | same, POV |

**Deliberate YAGNI / non-goals:** `obs_disk_free_mb` is only meaningful when
recording but is free from `GetStats`, so it is included. Feed quality is a text
label, not a px chart (Twitch often reports `source`, not a height). **True
per-feed downstream bandwidth/bitrate is out of scope** — each feed is a
single-consumer `streamlink --player-external-http` pipe to OBS; the relay is
not in the byte path, so it cannot be measured without disrupting OBS or fragile
log-parsing.

---

## 2. Sampler mechanics

Today `obs_reachable` is refreshed only in the `/status` handler; the 30 s
heartbeat reads the cached value. To get fresh stats every 30 s the heartbeat
must query OBS itself.

New work inside `_heartbeat_loop` (every `SAMPLE_INTERVAL_S` = 30 s), each block
strictly best-effort in its own `try/except`:

1. **One OBS session** (`obs_ws`, `timeout=2.0`) issues `GetStats` +
   `GetStreamStatus` in a single connect. This becomes the source of truth for
   `obs_reachable` (the heartbeat sets it; `/status` keeps reading the cache).
   OBS down → fast failure, all OBS-derived fields `None`, the OBS band shows
   "unreachable". A new helper in `obs_ws.py` (e.g. `get_health_stats(...)`)
   returns a flat dict + a note, following the same best-effort contract as
   `get_program_screenshot` (never raises; `_connect()` → `None` ⇒ empty result
   + note). Unit-testable parse helpers turn the raw OBS payloads into the flat
   field dict.
2. **`stream_kbps` derivation:** the relay keeps `self._last_output_bytes` and
   `self._last_output_ts`; `kbps = (bytes − last) · 8 / 1000 / dt`. Reset to
   `None` (and re-seed the baseline) when `outputActive=false`, on reconnect, or
   on a byte counter regression — so no ghost spikes appear after a stream
   stop/restart.
3. **Connectivity probes:**
   - `funnel_ok` / `tailscale_up` via `src/scripts/tailscale.py` (where
     detection already lives): parse `tailscale funnel status` and the backend
     state from `tailscale status`. Short subprocess timeout.
   - `companion_ok` via a stdlib TCP connect to the resolved Companion bind
     port (no HTTP needed).
   - `sheet_push_ok` **passively** from the existing push `last_error` /
     `push_status` — no active webhook call (avoids Apps Script load /
     rate-limits). It is "unknown" (`None`) until a push has been attempted in
     this session.
4. **Feed quality:** the feed stdout (streamlink) is already pumped through the
   feed logger. A small parser extracts the `Opening stream: <quality>` token
   and stores it on `feed.quality`; the heartbeat just reads `feed.quality`. The
   parser is a pure function (unit-tested against sample streamlink lines).

**Cost per 30 s:** one short-lived OBS-WS session + two `tailscale`
subprocesses + one TCP connect. Acceptable. If the two `tailscale` subprocesses
prove heavy, the Funnel/Tailscale check may later be throttled to every Nth
round (value held between rounds); the plan starts at "every round".

---

## 3. Critical-signal logic (rollup + alerts)

`aggregate_health(facts)` is stateless per sample. Each critical signal gets a
**gate** so it never false-alarms when the signal is not expected. Severity is
**tiered** (one decision below).

| Signal | Severity | Fires when |
|---|---|---|
| `stream_active=false` | **red** | OBS reachable & not streaming & `stream_expected` |
| `stream_reconnecting` | **yellow** | OBS reachable & `outputReconnecting=true` |
| Funnel down | **yellow** | `funnel_expected` & funnel not configured/up |
| Sheet-push failing | **yellow** | `SHEET_PUSH_URL` set & last push failed |

**Off-air alarm latches on the first stream (`stream_expected`, revised post-UAT):**
the original design fired the off-air red *with no live-gate* (red even pre-show).
UAT showed that pings a confusing `@here` CRITICAL the moment the relay starts
before going live, so it was revised to a `stream_expected` latch (in-memory,
relay-session-scoped, mirroring `funnel_expected`): the relay sets
`stream_expected=true` once OBS is observed streaming (`outputActive=true`), and
`stream_active=false` only escalates to red once that latch is set. Effect: a live
broadcast that drops off air pages the crew; starting the relay pre-show never
alarms. The **Stream active** band still shows the honest current state — only the
aggregate level + Discord alert wait for the latch. (When OBS is fully closed, the
existing `obs_reachable`-red path applies instead, so the two never double-count.)

**`funnel_expected` (in-memory, relay-session-scoped):** once the relay has
observed the Funnel up in this session, it sets `funnel_expected=true`; a later
"down" is then yellow. Before it is ever seen up (installs that never use
Funnel), "funnel off" is simply neutral, not a fault. This flag lives on the
relay (not in `aggregate_health`, which stays stateless); the heartbeat passes
the gated boolean into facts.

**`sheet_push_ok`** is only a fault when a `SHEET_PUSH_URL` is configured *and*
the last push attempt failed. Without a configured webhook it is N/A (`None`,
neutral).

The new reasons are appended to `health_reasons`, so they flow into the existing
Discord health-alert text with **no new alert code** — the debounce from #280
still applies.

**Observational signals never touch the rollup:** `tailscale_up`,
`companion_ok`, and all numeric charts are display-only.

---

## 4. Schema migration, redaction, handover

**Migration v2 → v3** in `health_store.migrate()`: bump `PRAGMA user_version`
2 → 3; one `ALTER TABLE samples ADD COLUMN` per new field (SQLite backfills
existing rows with `NULL`). Extend the module constants:
- `COLUMNS` += all 17 new fields.
- `BAND_FIELDS` += `stream_active`, `stream_reconnecting`, `funnel_ok`,
  `sheet_push_ok`, `tailscale_up`, `companion_ok`.
- `NUMERIC_FIELDS` += the 8 chart fields.
- `STATE_KEY_FIELDS` += the 6 new band fields (so state changes start new band
  segments). The 8 numeric fields are **not** added here (else every micro
  fluctuation would split a segment).

`SCHEMA_VERSION` → 3. Existing DBs migrate losslessly on first open; old rows
carry `NULL` in the new columns (charts/bands render a gap there — correct).

**Redaction:** all 17 fields are booleans/numbers/short labels. `funnel_ok` is a
bool — the Funnel hostname is never stored. `_health_snapshot` remains an
explicit allowlist returning only listed fields.

**Handover/export:** free. `export_jsonl` / `import_jsonl` and `racecast health
pull|export|import` serialize generically over `COLUMNS`; once the new columns
are in `COLUMNS` they travel automatically at producer handover. No new code in
the takeover path; the redacted takeover status is untouched.

---

## 5. UI — dashboard layout

Extends `src/console/health-monitor.html` (and the relay-served
`/health-monitor`). Bands + uPlot charts + incident timeline + time-range
presets (15m/1h/6h/24h/custom) stay. New layout uses grouped sections instead of
one long list:

```
┌─ Health Monitor ──────────────── [15m][1h][6h][24h][custom] ─┐
│ CRITICAL (rollup-relevant)                                    │
│  health  ▏▔▔▔▔▔▔▔▔▔▔ (green/yellow/red)                        │
│  stream-active  stream-reconnect  funnel  sheet-push          │
│                                                               │
│ FEEDS                                                         │
│  Feed A [720p]  Feed B [1080p]  POV [source]   ← quality      │
│  feed_a ▏▔▔▔   feed_b ▏▔▔▔   pov ▏▔▔▔  (bands)               │
│                                                               │
│ CONNECTIVITY (observational, neutral when down)              │
│  obs-reachable  tailscale  companion  cookies  timer-push     │
│                                                               │
│ OBS OUTPUT           │ OBS RESOURCES                          │
│  kbps      ╱╲___     │  CPU %     ___╱╲    FPS    ▔▔▔▔        │
│  dropped % ___╱      │  Memory MB ▔▔╱▔     render-skip %      │
│  congestion ╱╲_      │  disk free MB ▔▔▔▔                     │
│                                                               │
│ RELAY/SCHEDULE                                                │
│  source-last-ok-age   cookies-age-h   (existing)             │
│                                                               │
│ INCIDENTS  ▸ 14:22 red: stream not active (3m)  …            │
└───────────────────────────────────────────────────────────────┘
```

- **Critical row** first: the `health` band + the 4 critical bands (red/yellow
  per §3). "Is the show OK?" at a glance.
- **Feed quality** as a text badge in each feed card, above the feed band.
- **Connectivity** observational: down = neutral blue/grey (no alarm).
- **Charts** in a responsive two-column grid, grouped (OBS Output / OBS
  Resources / Relay-Schedule). uPlot as before; time-range presets apply to all.
- **Incident timeline** still derives from `health_level` transitions (via
  `health_reasons`), so the new critical signals appear automatically and the
  observational ones do not pollute it.
- **Wiki screenshot:** `src/docs/wiki/images/health-monitor.png` and
  `src/docs/wiki/Health-Monitor.md` are refreshed in the same change (CLAUDE.md
  requirement — a plan task), captured from a local dev build.

---

## 6. Testing

- **`health_store`:** migration v2→v3 is lossless (seed a v2 DB, migrate, assert
  `user_version=3`, old rows present with `NULL` new columns, new
  insert/query/band/numeric round-trips). Bands/incidents include the new
  critical fields; observational bands are excluded from incidents. Close every
  connection (Windows).
- **`obs_ws`:** pure parse helpers — raw `GetStats`/`GetStreamStatus` payloads →
  flat field dict, including missing-field tolerance (→ `None`) and the
  dropped/render-skip percentage math (divide-by-zero → `None`).
- **`kbps` derivation:** pure function over (prev_bytes, prev_ts, bytes, ts) +
  reset conditions (reconnect, regression, inactive).
- **Critical-signal logic:** extend `tests/test_pov.py`'s `aggregate_health`
  coverage — each gate (no-live-gate red for `stream_active`; reconnect/funnel/
  push yellow; funnel-expected; sheet-push-configured) and that observational
  signals never change the level.
- **Feed-quality parser:** pure function over sample streamlink stdout lines
  (YouTube `720p`, Twitch `source`, unknown → `None`).
- **Connectivity probes:** pure parsers for `tailscale status` / `tailscale
  funnel status` output; the TCP/subprocess calls themselves stay thin and
  best-effort (no network in tests).
- **e2e (`tools/e2e.py` synthetic):** `/health-monitor/data` returns the new
  fields (as `None` without OBS/Tailscale, which is the synthetic case) and the
  page renders the new groups.

## File map

- `src/scripts/health_store.py` — schema v3, constants, migration.
- `src/scripts/obs_ws.py` — `get_health_stats()` + pure parse helpers.
- `src/scripts/tailscale.py` — `funnel_status()` / backend-state parser.
- `src/relay/racecast-feeds.py` — heartbeat sampling, `funnel_expected`,
  kbps derivation, feed-quality read, `aggregate_health` gates, `_health_snapshot`.
- `src/console/health-monitor.html` — grouped layout, new bands/charts, feed badges.
- `tests/test_health_store.py`, `tests/test_obsws.py`, `tests/test_pov.py`,
  `tests/test_tailscale.py` (+ a new feed-quality parser test) — coverage above.
- `src/docs/wiki/Health-Monitor.md` + `images/health-monitor.png` — refreshed.
