# OBS Browser-Source Auto-Refresh — Design

**Date:** 2026-06-07
**Status:** Approved

## Problem

OBS browser sources cache pages aggressively: after `hud.html` or `timer.html`
changes, the source keeps running the old inline JS until someone right-clicks
the source and presses "Refresh cache of current page". Today that is a manual
step documented as a limitation (CLAUDE.md, wiki).

Two scenarios are affected:

1. **Dev iteration** — editing `hud.html`/`timer.html` on the producer machine
   means clicking through OBS after every change.
2. **Producer package update (the important one)** — a producer updates the
   `iro` binary, the package ships a new `hud.html`, and OBS silently keeps
   showing the *old* page. A stale HUD/timer can go on air with nobody aware
   anything is wrong.

The fix must therefore be automatic inside the normal operator flow — a manual
command alone fails scenario 2, because the producer does not know the problem
exists.

## Decisions (settled during brainstorming)

| Question | Decision |
|---|---|
| Refresh mechanism | obs-websocket `PressInputPropertiesButton` with `propertyName: "refreshnocache"` — the exact programmatic equivalent of the manual right-click → Refresh, including cache bypass. Uses the existing minimal client (`src/scripts/obs_ws.py`). |
| Target selection | All `browser_source` inputs whose `url` points at `127.0.0.1:8088` (HUD + Timer today; any future relay-served page automatically). No hardcoded source names. |
| When to refresh | Hash-gated (option 1+3 from brainstorming): only when the page content actually changed since the last successful refresh. The hash is computed over the bytes the relay actually **serves** (`GET /hud` + `/timer`), not the files on disk — a still-running old relay can then never advance the gate past pages OBS has not seen, and the fetch doubles as the "relay is up" probe. A mid-event relay restart (`event start --stint N` takeover) must not flicker the on-air HUD. |
| Hooks | `iro relay start`/`restart` (dev scenario) **and** `iro event start` after OBS is up (producer scenario), plus a manual `iro obs refresh` (always refreshes, no gate). |
| `Cache-Control: no-store` on relay pages | **Rejected.** The cached page is a resilience feature: if OBS starts while the relay is down, the cached page loads, polls, and recovers by itself once the relay is up. With `no-store` the source would show a CEF error page that never recovers. Staleness is busted surgically via `refreshnocache` instead of disabling caching. |
| Error handling | Fully best-effort, same model as `_release_obs_feeds()`: any failure prints one notice and the start continues. The hash is persisted **only on a successful refresh**, so a missed refresh (OBS not running) is retried on the next hook. |

## Architecture

```
iro relay start ──spawn──> relay daemon
      └─ wait until http://127.0.0.1:8088/status responds (poll, ~10 s cap)
           └─ refresh_if_stale()
                ├─ hash(GET /hud + GET /timer) == runtime/obs-pages.hash? → done (no flicker)
                └─ differs →
                     ├─ obs-websocket: GetInputList(browser_source)
                     ├─ filter inputs: settings.url contains "127.0.0.1:8088"
                     ├─ PressInputPropertiesButton(refreshnocache) per input
                     └─ success → write new hash   (failure → keep old hash, notice, retry next hook)

iro event start ── relay start (hook above; OBS may not be running yet)
      └─ launch OBS → wait_until_up() → refresh_if_stale()   (idempotent: hash gate)

iro obs refresh ── refresh always (no hash gate) — the scriptable right-click
```

### 1. Refresh primitive (`src/scripts/obs_ws.py`)

New function `refresh_browser_inputs(host, port, password, needle="127.0.0.1:8088")`
following the `release_feed_inputs()` pattern:

- `GetInputList` with `inputKind: "browser_source"`.
- Pure helper `browser_input_names(inputs, get_settings, needle)` (analogous to
  `feed_input_names`) selects inputs whose `url` setting contains the relay
  address. Pure → unit-testable without a socket.
- For each match: `PressInputPropertiesButton` with
  `{"inputName": <name>, "propertyName": "refreshnocache"}`.
- Password discovery, connection handling, and best-effort semantics are
  shared with the existing feed-release path.

### 2. Staleness gate

- Hash: SHA-256 over the concatenated response bytes of `GET /hud` and
  `GET /timer` from the running relay (the two OBS-source pages; `/panel` is a
  tablet page, not an OBS source). Hashing what the relay *serves* (instead of
  the files on disk) closes an update race: after a binary update with the old
  relay still running, a file hash would refresh OBS against old served pages
  and wrongly persist the new hash. If any page cannot be fetched (relay down,
  `--no-hud`/`--no-timer`), the hook skips with a notice and keeps the hash.
- State file: `runtime/obs-pages.hash` (plain hex digest, one line).
- `refresh_if_stale()`: compare → skip on match; on mismatch attempt the
  refresh and persist the new hash **only if the refresh succeeded**. OBS
  unreachable keeps the old hash so the next hook retries — a pending refresh
  is never lost.
- The decision logic (compare/persist rules) is pure and unit-tested.

### 3. Hooks

- **`iro relay start` / `restart`** (`relay_start()` in `src/iro.py`):
  after spawning the daemon, poll `http://127.0.0.1:8088/status` until it
  responds (cap ~10 s), then `refresh_if_stale()`. The wait is mandatory: a
  refresh against a closed relay port makes the browser source load a CEF
  error page that does not self-recover. If the relay never comes up, skip the
  refresh (the relay failure is the headline problem, and the kept hash
  retries later). `relay run` (foreground/debug) gets no hook.
- **`iro event start`** (`src/iro.py` event path): after launching OBS and the
  existing `wait_until_up()` probe confirms it, call `refresh_if_stale()`
  again. This covers the producer flow where the relay started before OBS
  existed; the hash gate makes the second call a no-op when the first one
  already succeeded.
- **`iro obs refresh`**: new `obs` subcommand group on the CLI. Refreshes all
  relay-pointing browser sources unconditionally (no hash gate, but it does
  write the hash on success). Manual escape hatch; also useful in docs as "the
  scriptable right-click".

### 4. Tests

- `tests/test_obsws.py`: `browser_input_names()` filtering (matching URL,
  non-browser inputs ignored, other URLs ignored), refresh request payloads.
- Staleness logic: hash compare/skip, persist-only-on-success, missing hash
  file (first run → refresh).
- Hook decision logic in the existing styles of `tests/test_services.py` /
  `tests/test_event.py` (wait-for-status gate as a pure decision where
  practical). No test talks to a real OBS or opens real sockets.

### 5. Docs

- CLAUDE.md: replace the "manual refresh needed, auto-reload is not reliable"
  caveat with the new mechanism (manual refresh remains the fallback when OBS
  websocket is unreachable).
- Wiki: update the OBS-import/HUD pages where the manual refresh is mentioned;
  document `iro obs refresh`.

## Out of scope

- Refreshing on sheet/data changes — the pages already poll `/hud/data` and
  `/timer/data` with `cache: "no-store"`; only the HTML document itself goes
  stale.
- Authenticating or hardening the obs-websocket connection (existing
  password-discovery model unchanged).
- Linux/WSL special-casing beyond what `obs_ws.py` already does — the
  websocket is loopback on the same machine as OBS in all supported setups.
