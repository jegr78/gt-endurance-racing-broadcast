# Live health heartbeat + Discord alerts

## Problem

Once `racecast event start` brings the stack up, the producer has no continuous
"is everything still healthy?" signal. The Director Panel surfaces `RELAY
UNREACHABLE` and (since #186) `FEED DOWN`, but only while someone is watching it.
During an 8–24 h endurance race nobody stares at the panel the whole time, so a
silent failure (a feed drops, cookies go stale, OBS WebSocket falls over) can go
unnoticed until it is visible on the broadcast.

## Goal

A relay-hosted **health heartbeat** that:

1. Continuously evaluates an aggregate health level (green / yellow / red) from
   the facts the relay already holds, and exposes it on `/status`.
2. Surfaces that level in the **Director Panel** (header pill) and the **Control
   Center** dashboard.
3. **Pushes to a Discord webhook on level transitions only** (degradation and
   recovery), configured per league — so the crew is alerted even when no one is
   looking, without spamming a multi-hour race.

Non-goals: paging/SMS, historical health graphs, per-feed webhooks, a generic
(non-Discord) webhook format, a separate monitor daemon.

## Why the relay

The relay is the only component that runs for the whole event and already knows
every fact: feed phases + `down` flags, `cookies_health`, the live OBS-WebSocket
reachability probe (`obs_reachable`), and the Tailscale bind state. The Control
Center is optional (the producer may close it) and a dedicated daemon is overkill.
So health evaluation, the heartbeat tick, and the webhook all live in the relay;
the panel and Control Center are read-only views of `/status`.

## Components

### 1. `aggregate_health(facts)` — pure, in `src/relay/racecast-feeds.py`

Input: a plain dict of already-gathered facts
(`feeds` states + `down`, `cookies_stale`, `obs_reachable`, `tailscale_present`,
per-feed connecting age). Output: `{"level": "green|yellow|red", "reasons":[...]}`
where `reasons` are short human strings (e.g. `"Feed A down"`, `"cookies stale"`).

Rules (confirmed):

- **red** — any feed reports `down` (a live picture was lost).
- **yellow** — OBS WebSocket not reachable · cookies stale · Tailscale not
  detected · a feed has been `connecting` longer than `HEALTH_CONNECTING_S`
  (45 s) without being `down`.
- **green** — none of the above.

`level` is the max severity; `reasons` lists every contributing fact (so a red
state still reports the yellow issues underneath). Pure → unit-tested.

### 2. Heartbeat tick — background thread in the relay

A daemon thread runs every `HEARTBEAT_INTERVAL_S` (30 s). Each tick it:

1. ensures the OBS probe is current (calls the existing throttled probe),
2. gathers the same facts `status()` uses (extracted into `_health_facts()` so
   the tick and `/status` agree),
3. computes `aggregate_health(...)`,
4. stores `level` + `reasons` + the timestamp the current level began
   (`health_since`) for `/status`,
5. on a **level change** vs the previous tick, logs it and — if a webhook URL is
   configured — sends the Discord message.

Anti-spam: the webhook fires only on transitions, both worse (green→yellow/red,
yellow→red) and better (→green "recovered"). No repeat pings while a level holds.
The very first tick establishes the baseline level without a "recovered" ping
(it only pings the baseline if it starts non-green — a degraded start is worth
announcing).

### 3. Discord push — `src/relay/racecast-feeds.py`

- `discord_health_payload(level, reasons, prev_level)` — pure → the Discord
  webhook JSON (`{"content": ...}` or an embed with a color per level). Unit-tested.
- A sender using stdlib `urllib.request` POST, fully best-effort: any failure
  (no URL, network error, non-2xx) logs one line and the relay continues. Never
  raised into the tick loop.

### 4. `/status` exposure

`status()` gains `out["health"] = {"level", "reasons", "since_s"}`. Read by the
panel and Control Center. Version-skew safe: older clients ignore it.

### 5. Director Panel (`src/director/director-panel.html`)

A health pill in the header status strip: green/yellow/red dot + `OK` / `DEGRADED`
/ `CRITICAL`, with the `reasons` joined as the title/tooltip. Reuses the existing
`.st` pill styling (`.st.ok` / `.st.warn` / `.st.air`). When `/status` is
unreachable the pill shows unknown (dim), consistent with the relay LED.

### 6. Control Center (`src/ui/`)

The dashboard already renders relay live data from `/status` (`relay_live_data`);
add the health level + reasons as a status row/badge there.

## Configuration

- New per-league key `DISCORD_WEBHOOK_URL` in `profiles/<name>/profile.env`
  (added to `profiles/example/profile.env`, empty).
- `config.ResolvedConfig` gains `discord_webhook_url` (parsed from `profile.env`).
- `racecast.py::_profile_env_vars` adds
  `("RACECAST_DISCORD_WEBHOOK_URL", rc.discord_webhook_url)`, injected into the
  relay's environment like `RACECAST_SHEET_PUSH_URL`.
- The relay reads `RACECAST_DISCORD_WEBHOOK_URL` from the environment (no new CLI
  flag); empty/unset = push disabled, health evaluation + display still active.

This is a webhook URL (a secret-ish bearer), so it lives in `profile.env`
(gitignored for real leagues; the shipped `example` profile keeps it empty) and
never in committed config — same model as `SHEET_PUSH_URL`.

## Testing

- `aggregate_health`: green / each yellow cause / red (feed down) / red-with-
  underlying-yellows / connecting-age threshold (in `tests/test_health.py`, the
  relay live-failure-visibility suite).
- transition logic: a small pure helper decides "fire?" given (prev, cur) — fires
  on any change, suppresses repeats, suppresses a green baseline.
- `discord_health_payload`: shape + per-level color, no secret leakage.
- `/status` includes `health` with the right level for staged feed/cookie/obs facts.
- config: `discord_webhook_url` resolves from `profile.env`; `_profile_env_vars`
  maps it (in `tests/test_config.py` / `tests/test_racecast.py`).

The background thread itself is not unit-tested (threads + time); its decision
logic is fully covered by the pure helpers above, mirroring how the existing feed
threads are tested via pure helpers.

## UI screenshots (CLAUDE.md hard rule)

The panel header pill and the Control Center dashboard badge are **always
visible**, so both default views change:

- `src/docs/wiki/images/director-panel.png` — re-capture with the health pill.
- the Control Center dashboard `cc-*.png` — re-capture from a local dev build.

Both regenerated and committed in the same change.

## Out of scope / follow-ups

- Companion Stream-Deck feed-down feedback (dropped by decision; panel is the
  primary tool).
- Generic (Slack/custom) webhook format — Discord-only for now.
