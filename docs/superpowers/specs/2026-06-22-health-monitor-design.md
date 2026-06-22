# Health Monitor — Design Spec

**Date:** 2026-06-22
**Status:** Approved (brainstorming) → ready for implementation plan

## Summary

A relay-served **Health Monitor** dashboard (Grafana/AWS-style) that visualizes the
broadcast relay's own health over time. The relay already computes a continuous health
rollup (`green/yellow/red` + reasons) and per-component health (feeds A/B/POV, OBS
reachability, Sheet/schedule source, cookies, timer) and exposes it point-in-time via
`GET /status`. The gap this fills: **there is no time-series history** — nothing to chart
over a time range. We add a self-contained SQLite-backed sampler in the relay, a single
data endpoint, a dashboard page (status bands + uPlot line charts + an incident timeline),
producer-handover carry-over of the history, and CLI/Control-Center export/import.

The page is reachable locally/over the tailnet at `/health-monitor` (unauthenticated, like
`/panel`) and over Funnel at `/console/health-monitor` (token-gated, any authenticated
console subject), via the existing `RC_API_BASE` shim.

## Scope (v1)

**In scope — relay-observable health only.** The relay is the single always-on,
Funnel-reachable component; it samples itself. Signals:

- Aggregate health: `level` (green/yellow/red), `reasons[]`, `since_s`.
- Feeds A/B and POV: `state` (stopped/idle/connecting/serving), `down`, `stint`.
- OBS reachability (throttled WS probe): reachable / unknown.
- Sheet/schedule source: `last_ok_age_s`, `count`.
- Cookies: `present`, `age_h`, `stale`.
- Timer: `mode`, `remaining_s`.
- Context: `mode` (race/qualifying), live feed + stint, event title.

**Out of scope (v1):** host/machine checks (disk, bandwidth/speedtest, Companion,
Tailscale, OBS scene collection, "apps running") and preflight readiness (tools, Sheet
tabs, graphics/media). Those are produced by the CLI/Control Center, not the relay, and
would require the relay to probe the host or the Control Center to push samples — a later
iteration. **No new alerting:** the existing Discord pings on health-level change are
unchanged; the monitor only *visualizes*.

## Security & redaction

- Samples **never** contain stream URLs or `sheet_id` — redaction by construction (same
  boundary as `/console/status` and the race-control desk). The SQLite schema has no URL
  columns, so the DB is safe to expose, export, and pull over Funnel.
- Page + data endpoint: `Requirement(ANY, False)` — any authenticated console subject
  (commentator, director, producer, race_control), read-only, no step-up. Mirrors the
  race-control desk gating.
- The producer-takeover endpoint requires the step-up `X-Console-Secret`
  (producer-level), like the existing `/console/takeover/{status,chat,versions}`.
- Funnel exposes **only** the existing `/console` mount; no new public surface is added.
  OBS-WebSocket is never funnelled.

## Architecture

### A. Pure-logic store — `src/scripts/health_store.py` (new)

Follows the house pure-store pattern (`chat_admin.py`, `cue_admin.py`): all SQLite and
derivation logic lives here and is unit-testable without the relay. The relay wraps it
thread-safely (single connection, `threading.Lock`, WAL mode for concurrent read during
write — `ThreadingHTTPServer` serves data-endpoint reads on request threads while the
heartbeat thread writes).

**Storage:** `runtime/<profile>/health-history.db` (profile-scoped, like the rest of the
profile runtime state). Schema versioned via `PRAGMA user_version` for migrations.

**Wide table `samples`** (fixed, known signals — simpler/faster to query than a generic
`(ts, metric, value)` long table):

```
ts INTEGER                 -- epoch seconds, indexed
kind TEXT                  -- 'periodic' | 'event'
health_level TEXT          -- green|yellow|red
health_reasons TEXT        -- JSON array of strings
feed_a_state TEXT, feed_a_down INT, feed_a_stint INT
feed_b_state TEXT, feed_b_down INT, feed_b_stint INT
pov_state TEXT             -- nullable (NULL when POV not active)
obs_reachable INT          -- nullable (NULL = unknown / not yet probed)
source_last_ok_age_s REAL  -- nullable
source_count INT
cookies_present INT, cookies_age_h REAL, cookies_stale INT
timer_mode TEXT, timer_remaining_s INT  -- nullable
mode TEXT                  -- race|qualifying
live_feed TEXT, live_stint INT
```

**Pure functions (each unit-tested):**

- `open_db(path)` / `migrate(conn)` — create + apply `user_version` migrations.
- `record(conn, snapshot, kind)` — insert one row from a snapshot dict.
- `query_range(conn, frm, to)` — ordered samples in `[frm, to]`.
- `derive_bands(samples)` — collapse consecutive equal states per signal into bands
  `{from, to, state}`; insert **gaps** where the inter-sample distance exceeds a
  threshold (relay was down) — no interpolation across gaps.
- `derive_incidents(samples)` — every non-`green` health band / feed-down band /
  OBS-unreachable band becomes `{ts, end, duration_s, label, severity}`; `label` built
  from `reasons` (e.g. "Feed B down", "Health → yellow: cookies stale").
- `downsample(series, max)` — numeric series only; bucket by time, take last value per
  bucket (≤ ~2000 points). Bands and incidents are never downsampled (bands already
  collapse).
- `prune(conn, retention_days)` — `DELETE WHERE ts < cutoff`.
- `export_jsonl(conn, frm)` → iterator of JSON objects (one sample per line).
- `import_jsonl(conn, lines)` — merge by `ts` union, deduplicated (idempotent).

### B. Sampler — in the relay's existing heartbeat

No new thread. In the 30 s heartbeat (`HEARTBEAT_INTERVAL_S`), after `_refresh_health()`,
the relay records **one row per tick**. The row's `kind` is `'event'` when the categorical
state (health level, per-feed state, OBS reachability) changed since the previous recorded
row, else `'periodic'` — so transitions are marked in the series. Granularity therefore
equals the sample tick (≤30 s); finer per-feed-thread hooking is a documented future
refinement, not v1. `prune()` runs on relay start and once daily. Retention window:
`RACECAST_HEALTH_RETENTION_DAYS` (default 30).

### C. Relay endpoints — `src/relay/racecast-feeds.py`

- **`GET /health-monitor/data?from=&to=&max=`** — everything the page needs in one call:
  ```
  {
    "now": <epoch>,
    "current": { health:{level,reasons,since_s}, feeds:{A,B}, pov, obs,
                 source, cookies, timer, mode, live, event_title },
    "t": [<epoch>, ...],                       // downsampled time axis for charts
    "series": { source_age:[...], cookie_age:[...], timer_remaining:[...] },
    "bands": { health:[{from,to,state}], feed_a:[...], feed_b:[...],
               pov:[...], obs:[...], source:[...], cookies:[...] },
    "incidents": [ {ts, end, duration_s, label, severity}, ... ]
  }
  ```
  No range → live window (last ~15 min). Gated `Requirement(ANY, False)`. Reachable at
  root (tailnet) **and** under `/console/…` (Funnel), via the `RC_API_BASE` shim. Bands
  and incidents are derived server-side so the page only renders.
- **`GET /health/raw?from=`** (root, tailnet) and **`GET /console/takeover/health?from=`**
  (Funnel, **step-up** `X-Console-Secret`) — raw samples (JSON Lines payload) for the
  handover merge. Joins the existing `/console/takeover/{status,chat,versions}` family;
  adds **no** new public surface beyond the already-mounted `/console`.

### D. The page — `src/console/health-monitor.html` (new)

Self-contained vanilla JS (like `console.html`), dark Grafana/AWS dashboard theme,
`__RC_API_BASE__` / `__RC_OAUTH__` shim. Top to bottom:

1. **Status header (live, auto-refresh):** large aggregate badge (green/yellow/red) +
   reasons, event title, mode, live feed/stint, "since `since_s`". Polls
   `/health-monitor/data` in the live window.
2. **Time-range bar:** `Live · 1h · 6h · 24h · 7d` buttons + a free from–to picker. Live
   = short rolling window with auto-refresh; any other selection = static range query
   (no auto-refresh).
3. **Status bands (custom CSS/SVG):** one row each for aggregate health, Feed A, Feed B,
   POV (only when used), OBS, Sheet source, Cookies. Colored bands over the range, with
   **gaps** where the relay was down (no interpolation). Hover → tooltip with state +
   time span.
4. **Numeric line charts (uPlot, shared x-cursor/hover):** Sheet `last_ok_age_s`, cookie
   age (h), timer remaining (when running). Server pre-downsamples (≤ ~2000 points).
5. **Incident timeline:** list from `incidents` — timestamp, label, duration-to-recovery,
   severity color. Statuspage-style, for post-mortems.

This is operations UI, not a broadcast overlay — it does **not** honor per-league overlay
CSS; it uses a fixed neutral dark theme.

### E. Vendoring uPlot

`src/assets/vendor/uplot/uplot.min.js` + `uplot.min.css` + `LICENSE` (MIT, ~50 KB),
relay-served under `/health-monitor/assets/…` (read per request, like the overlay fonts).
`src/` already ships in the build artifact; ensure the vendor folder is copied. This is a
**deliberate** first break of the "no vendored JS" status — recorded here and in the build
notes.

### F. Auth gate — `src/scripts/console_policy.py`

- `["health-monitor"]` and `["health-monitor","data"]` → `Requirement(ANY, False)`
  (any authenticated subject, no step-up) — like the race-control desk.
- `["console","takeover","health"]` → step-up `X-Console-Secret` (producer-level), like
  the other takeover endpoints.

### G. CLI + handover — `src/racecast.py`

- `racecast health export [--from] [--out PATH]` → portable JSON-Lines dump.
- `racecast health import FILE` → merge into the local DB.
- `racecast health pull <ip>` → fetch from another producer's relay (tailnet, via
  `src/scripts/http_util.py` — the covered side, correct User-Agent) and merge. Mirrors
  `chat pull`.
- `event takeover <A-ip>` and `… <host> --funnel` pull the history automatically
  (tailnet: `/health/raw`; Funnel: `/console/takeover/health` + step-up), analogous to
  chat/versions. Network failure falls back to a local bringup without history.
- Pruning is automatic (start + daily); no manual command.

### H. Control Center — `src/ui/` + `src/racecast_ui.py`

A **"Health Monitor" card**: opens the relay-served page (local `/health-monitor`; note
"relay must be running") + **Export/Import buttons** (CLI-backed, routes
`/api/health/export`, `/api/health/import`). No second, native monitor view (DRY).

## Testing (stdlib runner, TDD — failing test first)

- **`tests/test_health_store.py`** (new): schema create/migrate; periodic + event insert;
  `query_range`; `derive_bands` (collapse + gaps); `derive_incidents`
  (start/end/duration/severity); `downsample`; `prune`; `export/import` merge (dedup by
  ts, idempotent); a **redaction guard** asserting no URL/`sheet_id` field is ever stored.
- **`tests/test_console.py` / `tests/test_console_gate.py`**: gate for `/health-monitor`
  (+`/data`) = ANY; `/console/takeover/health` = step-up.
- **`tests/test_racecast.py`**: CLI routing for `health export/import/pull` + takeover
  integration.
- **`tests/test_ui_server.py`**: Control Center routes `/api/health/export|import` + the
  card.
- **Optional `tools/e2e.py`**: a check that `/health-monitor/data` returns the expected
  shape (synthetic mode).

Run `python3 tools/run-tests.py` and `python3 tools/lint.py` before any commit; run
`python3 tools/build.py` (verify step) before shipping.

## Docs & screenshots (CLAUDE.md requirement — same change)

New UI surface → in the **same** change:

- New wiki page for the Health Monitor + `src/docs/wiki/images/` capture (local dev build,
  no `VERSION` stamp, so the version badge stays uniform).
- Control Center changed (new card) → regenerate the matching `cc-*.png`.
- Add `racecast health …` to the README / CLAUDE.md command list.

## Open items / non-goals

- Host-level and preflight metrics over time: explicit non-goal for v1 (see Scope).
- Export format: **JSON Lines only** (robust against schema growth, easy to
  merge/stream); CSV not included.
- Alerting/notifications: unchanged (existing Discord level-change pings).
