# Unified `iro` Operator CLI — Design

**Date:** 2026-06-04
**Status:** Approved (design), ready for implementation planning
**Scope:** Replace the inconsistent mix of operator entrypoints (foreground
`tools/run-relay.py`, `src/scripts/start-companion.py`/`stop-companion.py`,
`src/scripts/start-streams.py`/`stop-streams.py`) with a single shipped command,
`iro`, exposing a uniform `start | stop | restart | status | logs` verb set per
service plus the existing one-shot operator actions. No change to the relay's pull
pipeline, OBS collection, HUD, or the Tailscale auto dual-bind behaviour.

---

## 1. Goal

Give the producer **one memorable entrypoint** for everything they run, with a
consistent service-management vocabulary:

```
python3 src/iro.py relay start          # repo
python3 iro.py     relay start          # shipped package
```

Today the operator surface is split across `tools/` (maintainer dir) and
`src/scripts/`, and mixes two idioms (a foreground `run` wrapper vs `start`/`stop`
pairs). The split is partly historical: `tools/run-relay.py` is only a repo-dev
wrapper that injects `--runtime-dir runtime`; the real entrypoint is
`src/relay/iro-feeds.py`. The goal is a coherent CLI that hides these details behind
`iro <command> [verb]`, while `tools/` returns to being **maintainer-only**.

## 2. Decisions (locked during brainstorming)

| Topic | Decision |
|---|---|
| Shape | **Single dispatcher** `iro` with subcommands (chosen over start/stop-pairs-everywhere or location-only cleanup) |
| Verb set (services) | **`start` / `stop` / `restart` / `status` / `logs`** |
| Relay run model | **Background-managed by default** (PID + logfile) **plus** a `run` foreground verb for live/debug |
| Scope of `iro` | **Everything**: 3 services + one-shot actions (`preflight`, `cookies`, `graphics`, `media`, `setup`) |
| Entrypoint location | **`src/iro.py`** (top-level in `src/`) → ships as `iro.py` at the package root |
| Internal architecture | **Shared daemon helper** (`services.py`) for relay+streams; **companion is its own adapter** (GUI app, not a PID-spawned daemon) |
| Existing thin entrypoints | **Removed**; their *logic* is preserved in importable modules |
| `tools/run-relay.py` | **Removed** (replaced by `iro relay run` / `iro relay start`) |
| OS support | Cross-platform where the underlying tool is; **companion verbs remain macOS-only** (open/osascript), with a clear message elsewhere |

## 3. Command surface

```
iro relay      start | stop | restart | status | logs | run
iro companion  start | stop | restart | status | logs
iro streams    start | stop | restart | status | logs
iro status                       # aggregate health of all three services
iro preflight                    # one-shot: hardware/tool check
iro cookies [browser]            # one-shot: refresh YouTube cookies
iro graphics                     # one-shot: fetch broadcast graphics
iro media                        # one-shot: fetch intro/outro clips
iro setup [--out PATH]           # one-shot: localize the OBS collection
```

- `relay run` is the only foreground verb (blocking, Ctrl+C) — identical to today's
  `iro-feeds.py` behaviour, for live-watching/debugging.
- Unknown command/verb → argparse usage error (non-zero exit).
- Passing extra/unknown flags to a service verb is forwarded where it makes sense
  (e.g. `iro relay run --no-pov`), otherwise rejected. (Forwarding policy finalised in
  the plan; default: `relay run`/`relay start` forward unrecognised args to
  `iro-feeds.py`.)

## 4. Architecture

```
                         src/iro.py  (dispatcher: parse + route, no logic)
            ┌───────────────┬───────────────┬──────────────────────────┐
            ▼               ▼               ▼                          ▼
     relay adapter    streams adapter   companion adapter        one-shot wrappers
            │               │               │                  preflight/cookies/
            └──── services.py (shared ───┘  companion_common.py  graphics/media/setup
                  daemon helper)                (existing)        → call existing modules
```

### 4.1 `src/iro.py` — dispatcher
Thin. `argparse` with subparsers: level-1 = command, level-2 = verb (services only).
Routes to an adapter function. Self-locates siblings: `relay/iro-feeds.py`,
`scripts/*` are sibling subdirs in **both** repo (`src/`) and package (root). Resolves
the runtime dir with the existing repo-vs-package detection (mirrors `run-relay.py`
for the repo; lets the package self-locate). A pure `route(argv) -> Action` function
(returns the resolved command/verb/target without executing) is the unit-test seam.

### 4.2 `src/scripts/services.py` — shared daemon helper (new)
For **spawned** services (relay, streams). Responsibilities:
- PID file path + read/write; `is_alive(pid)` (signal-0 / process check).
- `start_detached(argv, logfile)` — launch in a new session, stdout/stderr → logfile,
  write the PID file; refuse if already alive.
- `stop(pid, timeout)` — SIGTERM, wait, then SIGKILL fallback; clear the PID file.
- `tail(logfile, follow)` — print/stream the log.
- `status_line(name, pid_alive, port_listening, health_ok)` — one formatted line.

Pure logic (PID parse, alive decision from a process probe, status formatting, the
"already running?" decision) is separated from the side effects so it is unit-tested
without spawning real processes.

### 4.3 Service adapters
- **relay** — uses `services.py`. `start` launches `relay/iro-feeds.py` detached with
  the resolved `--runtime-dir`; PID `runtime/relay.pid`, console log
  `runtime/logs/relay.console.log`. `stop` SIGTERM→SIGKILL. `status` = PID alive **+**
  port 8088 listening **+** `GET /status` ok (prints the dual-bind tailnet URL).
  `logs` tails the console log. `restart` = stop+start. `run` execs `iro-feeds.py` in
  the foreground (today's behaviour, args forwarded).
- **streams** — uses `services.py`, wrapping the **existing** `start-streams` /
  `stop-streams` logic (PID files under `runtime/static/`, incl. the PID-identity
  safety check). Logic is factored into an importable module; no rewrite.
- **companion** — its own adapter over the existing `companion_common.py`:
  `start` = set `bind_ip` (Tailscale auto) + `open -a Companion`; `stop` =
  `osascript quit`; `restart` = stop+start; `status` = running (pgrep) + current bound
  IP + reachability; `logs` = tail Companion's newest log under its config dir.
  macOS-only (already the case); other OSes get a clear "set manually" message.

### 4.4 One-shot wrappers
`preflight/cookies/graphics/media/setup` dispatch to the existing modules
(`scripts/preflight.py`, `relay/get-cookies.py`, `relay/get-graphics.py`,
`relay/get-media.py`, `setup-assets.py`) — thin pass-through (import-and-call or
subprocess), forwarding relevant args.

## 5. Runtime files / data flow

| Service | PID | Log |
|---|---|---|
| relay | `runtime/relay.pid` | `runtime/logs/relay.console.log` (control-server stdout/err) |
| streams | `runtime/static/*.pid` (existing) | existing per-stream logs |
| companion | n/a (GUI app, tracked via pgrep) | Companion's own `…/companion/logs/` |

The relay's per-feed logs under `--logdir` are unchanged; the new console log only
captures the control-server stdout/stderr that `run` prints to the terminal today.

## 6. Error handling

- `start` when already running → print `status`, do **not** double-spawn.
- `stop` when not running → friendly "not running" message, exit 0.
- `status` → one clear line per service (running/stopped + health + URL).
- `restart` → stop (tolerate not-running) then start.
- companion/streams verbs on an unsupported OS → explicit message, non-zero exit.
- relay `start` that fails to bind/launch → surface the tail of the console log.

## 7. Testing (TDD)

- **`tests/test_services.py`** (new) — daemon helper pure logic: PID-file parse,
  alive decision from a probe result, "already running?" decision, status-line
  formatting, log-path resolution.
- **`tests/test_iro.py`** (new) — dispatcher `route(argv)`: each `command verb` maps to
  the expected action; aggregate `iro status`; unknown command/verb errors; one-shot
  routing.
- **`tests/test_companion.py`** (existing) — unchanged.
- All stdlib, each file a runnable script (no pytest), matching the project convention.

## 8. Migration

- **Remove** `tools/run-relay.py`, `src/scripts/start-companion.py`,
  `src/scripts/stop-companion.py`, `src/scripts/start-streams.py`,
  `src/scripts/stop-streams.py` as *entrypoints*.
- **Preserve logic**: companion logic stays in `companion_common.py`; streams logic is
  factored into an importable module (e.g. `streams_service.py`) reused by the adapter.
- `loopstream.py` stays as-is (niche helper), out of the CLI for v1 (YAGNI).
- Direct `python3 src/relay/iro-feeds.py …` still works for power users.

## 9. Build & docs

- **`tools/build.py` verify**: add checks that `iro.py` ships and the removed
  entrypoints are gone; keep the `no .sh/.bat` and existing checks.
- **Docs**: rewrite the README quickstart and the CLAUDE.md "Commands" + relevant
  architecture notes around `iro`; update the wiki later via `tools/sync-wiki.py`.

## 10. Out of scope (YAGNI)

- A native `iro` shell shim (forbidden `.sh`; invocation stays `python3 iro.py …`).
- Folding `loopstream.py` into the CLI.
- Auto-start on boot / service-manager integration (launchd/systemd).
- Tailscale ACL authoring (tracked separately as the Companion admin-isolation step).
- Any change to the relay pull pipeline, OBS collection, HUD, or dual-bind logic.
