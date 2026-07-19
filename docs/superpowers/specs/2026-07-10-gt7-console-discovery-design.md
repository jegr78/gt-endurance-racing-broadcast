# PlayStation (GT7 console) auto-discovery — explicit CLI + Control Center action

Epic: #300 (Solo mode). Builds on the GT7 telemetry work
([#324](2026-07-08-gt7-telemetry-pov-hud-design.md)). New sub-issue under #300.

## Problem

`RACECAST_GT7_PS_IP` (the PS4/PS5 IP that runs GT7) is today either set by hand or left
empty, in which case the relay's telemetry loop broadcast-discovers the console
passively at runtime (`_telemetry_loop`, `src/relay/racecast-feeds.py:7666`). There is
**no explicit, operator-facing action** to *find* the console and *persist* its IP into
`.env` ahead of time — the operator wanting a pinned IP has to read it off their router
or run the maintainer probe (`tools/gt7-telemetry-probe.py`, not shipped).

This design adds that explicit action on the two shipped surfaces, mirroring the
existing **`device-scan`** feature ("discover hardware → write to `.env`") end-to-end.

## What already exists (reused, not reinvented)

- **Discovery mechanism.** Bind `0.0.0.0:33740` (`SO_BROADCAST`), send heartbeat `b"A"`
  to `255.255.255.255:33739`, latch the responder's source IP. Present in two places:
  `tools/gt7-telemetry-probe.py:44-63` and the relay loop `_telemetry_loop`
  (`racecast-feeds.py:7666-7715`, constants `GT7_RECV_PORT=33740`,
  `GT7_SEND_PORT=33739`, `GT7_HEARTBEAT_S=10.0`).
- **Decrypt/parse.** `src/scripts/gt7_crypto.py::decrypt_packet`,
  `src/scripts/gt7_telemetry.py::parse_packet` / `TelemetryStore`.
- **Env var.** `RACECAST_GT7_PS_IP` (`.env.example:121`), read at
  `racecast-feeds.py:7863` (`--gt7-ps-ip`).
- **`.env` write path.** `env_upsert_data(updates)` (`src/racecast.py:4590`) →
  `env_write_data` (RACECAST_ prefix enforced, comments preserved, atomic tmp+replace).
- **CLI one-shot pattern.** `route(argv)` branch → `<verb>_cmd(rest)` in `main()`
  (`freeport`, `device-scan` are the templates).
- **Control Center data-endpoint pattern.** `/api/devices` + `/api/devices/select` →
  ctx registry entries (`devices_enumerate`, `devices_write`) → `do_POST` route in
  `src/ui/ui_server.py`, persisting via `env_upsert_data`.

## Design

### A. New discovery helper — `src/scripts/gt7_discovery.py`

A small, focused module (network + a pure core), following the `src/scripts/ports.py`
house style (cross-platform-safe, injectable seams for unit tests).

```
GT7_RECV_PORT = 33740      # duplicated constant (relay is import-free; see note)
GT7_SEND_PORT = 33739
GT7_HEARTBEAT = b"A"
BROADCAST_ADDR = "255.255.255.255"

def discover_consoles(timeout=4.0, *, sock_factory=None, decrypt=None,
                      now=None) -> {"consoles": [ip, ...], "note": str}
```

- Opens one UDP socket (`sock_factory` default = real `socket`, overridable in tests),
  `SO_BROADCAST` + `SO_REUSEADDR`, bind `0.0.0.0:33740`, non-blocking with a short
  per-`recv` timeout.
- Sends `GT7_HEARTBEAT` to `BROADCAST_ADDR:33739` once at start (and re-sends every
  ~1 s until `timeout` elapses, so a console that boots into a session mid-scan still
  answers).
- For each received datagram, runs `decrypt` (default `gt7_crypto.decrypt_packet`) and
  **only records the source IP when the packet decrypts** — this is the correctness
  gate: it proves the responder is a real GT7 console emitting valid telemetry, not any
  LAN host that happens to sit on that port. Foreign/undecryptable packets are ignored.
- Collects for the whole `timeout` window (does **not** stop at the first hit) so a
  second console on the LAN is also found; returns the **deduped, sorted** IP list.
- `note`:
  - empty list → `"No PlayStation answered. Make sure GT7 is in an active session
    (menus emit no telemetry) and the console is on this LAN."`
  - non-empty → `""`.
- **Best-effort / never raises** (same contract as `probe_device_options` /
  `release_feed_inputs`): a bind/socket error returns `{"consoles": [], "note": <error>}`.

Constants are duplicated from the relay (not imported) because the relay is
deliberately import-free (`config.py:11-15`); this mirrors the existing duplication of
`GT7_RECV_PORT`/`GT7_SEND_PORT` between the probe and the relay. A one-line comment on
each copy points at the others (the `detect_tailscale_ip` / `STREAMLINK_TWITCH`
precedent).

### B. Two-tier source resolution (avoids the 33740 port conflict)

When the relay is running with telemetry enabled it **already holds** `0.0.0.0:33740`.
Two live listeners on the same UDP port would race over the console's reply. Resolution,
implemented in the CLI/CC callers (not in `discover_consoles`, which stays a pure
scanner):

1. **Relay is up + telemetry latched** → return the already-known console IP with **no
   socket at all** (instant, no conflict). This is the common case during setup: GT7 in
   a session, relay up to preview the HUD.
2. **Otherwise** (relay down, or up but not yet latched) → run
   `discover_consoles()` directly (port is free, or the transient overlap is
   acceptable because the relay hasn't latched anything to protect).

To expose the latched IP:
- `TelemetryStore` (`src/scripts/gt7_telemetry.py:385`) gains a thread-safe
  `set_source(ip)` / `source` accessor; `data()` includes a `"source"` field (the
  latched console IP, or `None`).
- `_telemetry_loop` calls `store.set_source(dest)` at the moment it latches
  (`racecast-feeds.py:7694`).
- The caller reads it over the existing relay telemetry data endpoint
  (`telemetry_store.data()`, `racecast-feeds.py:6919`) via a localhost HTTP GET, guarded
  by a short timeout; any failure falls through to the direct scan (tier 2).

A thin caller-side helper `resolve_console(...)` encapsulates the two tiers and returns
`{"consoles": [...], "note": str, "from_relay": bool}`, so both surfaces share one
resolution path and one set of tests.

### C. CLI — `racecast gt7-discover`

- `route()` branch `cmd == "gt7-discover"` → `{"kind": "gt7-discover", "rest": rest}`;
  `main()` calls `gt7_discover_cmd(rest)`. Help line added near `src/racecast.py:33`.
- Flags (hand-rolled parser like `_parse_device_scan_args`): `--save` (persist without
  prompting — for non-TTY/scripts), `--timeout N` (scan window), `--print` (only print,
  never write).
- Behaviour (mirrors `device_scan_cmd`):
  - 0 consoles → print the `note`; exit without writing.
  - 1 console → print it; on a TTY prompt `Save <ip> to RACECAST_GT7_PS_IP? [Y/n]`;
    `--save`/non-TTY writes directly; `--print` never writes.
  - ≥2 consoles → numbered list + interactive pick (like `device-scan`); non-TTY without
    a selection prints the list and exits (no guess).
  - On confirm → `env_upsert_data({"RACECAST_GT7_PS_IP": ip})`, then the standard
    "restart the relay to apply" reminder.
- IP is validated with the existing `ui_ops._HOST_RE` / `_ip_arg` before writing.

### D. Control Center — General Settings

Next to the GT7/telemetry `.env` fields:
- A **"Discover PlayStation"** button → new POST `/api/ps/discover` route (registered in
  the ctx registry as `ps_discover`, called in `do_POST` like `/api/devices`). Runs
  `resolve_console(...)` synchronously (≤ a few seconds, same as device enumeration).
  Returns `{"ok": true, "consoles": [...], "note": str, "from_relay": bool}`.
- The result renders inline: 0 → the hint; 1 → the IP with a **Save** button; ≥2 → a
  small dropdown + **Save**. **Save** → POST `/api/ps/save` (ctx `ps_write`) →
  `ps_ip_write_data(ip)` → `env_upsert_data({"RACECAST_GT7_PS_IP": ip})`, and refreshes
  the `.env` editor so the persisted value is visible. IP validated server-side
  (`_HOST_RE`) before write.
- A `#ps-hint` element shows `note`/degraded states, exactly like `#dev-hint`.

### E. `.env.example` + docs

- `.env.example`: extend the `RACECAST_GT7_PS_IP` comment — "Set by hand, or use
  `racecast gt7-discover` / the Control Center's *Discover PlayStation* button to find +
  save it automatically." No new key.
- `CLAUDE.md` commands list: add the `racecast gt7-discover` line near the GT7/telemetry
  entries.

## Testing (additive — nothing disabled)

- `tests/test_gt7_discovery.py` (new), fake socket + fake `decrypt`:
  - a decodable reply → its source IP is recorded; an **undecryptable** reply from
    another host is **ignored** (the decrypt gate).
  - two distinct decodable sources → both returned, deduped + sorted.
  - no replies within `timeout` → `consoles == []` and the "active session" note.
  - a bind/socket error → empty list + error note, no raise (best-effort contract).
  - `now`/timeout is injected so the test is deterministic and fast.
- `tests/test_racecast.py`:
  - `route("gt7-discover ...")` maps to the action; `gt7_discover_cmd` selection + write
    path with `discover_consoles`/`resolve_console` and `env_upsert_data` patched.
  - `resolve_console` two-tier: relay-latched source short-circuits (no scan); relay
    absent falls through to the scanner (both injected).
  - `ps_ip_write_data` upserts `RACECAST_GT7_PS_IP` via `env_upsert_data`.
- `tests/test_ui_server.py`: `/api/ps/discover` + `/api/ps/save` shapes via injected
  ctx callables (unchanged-contract, new source), incl. the `_HOST_RE` rejection of a
  bad IP.
- `tests/test_obsws.py` / telemetry tests: `TelemetryStore.set_source`/`data()["source"]`
  round-trip (thread-safe accessor).
- No live PS/OBS in CI; the real broadcast path is validated manually against a live PS5
  + GT7 (the same manual gate #324 already carries), and via
  `tools/gt7-telemetry-probe.py` (which already exercises the identical mechanism).

## Wiki / screenshots

- The **General Settings** view (`src/ui/control-center.html`) gains a button →
  `src/docs/wiki/images/cc-settings.png` is now stale and MUST be regenerated and
  committed in the same change (hard rule), via the `wiki-screenshots` skill against a
  local dev build (no `VERSION` stamped).

## Non-goals / boundaries

- **No generic PlayStation DDP** (UDP 987/9302 SRCH). Chosen mechanism is the GT7
  heartbeat: it reuses proven in-repo code and a hit doubly proves the telemetry path
  works. Cost: discovery only finds the console while GT7 is in an **active session**
  (documented in the zero-found hint).
- **No per-interface / subnet-directed broadcast enumeration.** Limited broadcast
  `255.255.255.255` covers a flat home LAN (what the proven code uses). Per-interface
  directed broadcast is a possible later enhancement, not built now (YAGNI).
- **No change to the relay's runtime passive discovery.** The relay loop keeps
  latch-first-responder; this feature only adds the explicit action + surfaces the
  latched IP. The relay's security pin (ignore non-latched hosts once latched) is
  unchanged.
- No new `.env` key, no new public/Funnel surface (both endpoints are local Control
  Center routes; the relay telemetry read is localhost-only).

## Success criteria

- With GT7 in an active session, `racecast gt7-discover` finds the console and (on
  confirm/`--save`) persists its IP to `RACECAST_GT7_PS_IP` via `env_upsert_data`
  (comments preserved).
- Control Center → General Settings **Discover PlayStation** lists the console(s) and a
  **Save** persists the chosen IP; the `.env` editor reflects it.
- When a relay with telemetry is already running, discovery returns the latched IP
  instantly, with no 33740 port conflict.
- Zero-found and error paths degrade to a one-line hint, never a crash.
- Full suite green; no test disabled; `cc-settings.png` refreshed.
