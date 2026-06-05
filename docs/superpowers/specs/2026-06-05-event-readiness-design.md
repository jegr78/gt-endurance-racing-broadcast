# Event-Day Readiness Check (`iro event`) — Design Spec

**Date:** 2026-06-05
**Status:** Approved (design) — ready for implementation plan

## Purpose

One command family for event day: confirm at a glance that everything the
broadcast needs is **running and present** (OBS, relay, Companion, Tailscale,
Discord; cookies, graphics, intro/outro media, `.env`), and bring the machine
up / down with a single command.

Division of labour with the existing checks:

- **`iro preflight`** — "is this machine set up?" (hardware, tool chain,
  ports, cookies; run once / before the first event). Extended by this spec
  with an **Applications installed** section.
- **`iro event status`** — "is everything up right now?" (run on event day,
  repeatedly).
- **`iro status`** — unchanged; low-level service lines (relay/companion/
  streams) for debugging.

## CLI surface

```
iro event status      # readiness traffic-light report; exit 0 = ready, 1 = not
iro event start       # bring everything up (order below), then print event status
iro event stop        # stop iro-managed services only; GUI apps keep running
```

No `restart`/`logs`/`run` verbs (YAGNI — the per-service groups have them).
Exit code of `event status`: **0 if no FAIL, 1 otherwise** (scriptable; can
back a Companion button later).

## `iro event status` — checks

Output format reuses the preflight reporter (`Result`, colored
`[PASS]/[WARN]/[FAIL]` tags, sections, summary + verdict).

| Section | Check | Method | Not-OK level |
|---|---|---|---|
| Apps | OBS running | process probe (pgrep/tasklist) — NOT port 4455, which only answers when the WebSocket plugin is enabled | FAIL |
| | Discord running | process probe | WARN (interview audio; not broadcast-critical) |
| | Tailscale connected | `companion_common.detect_tailscale_ip()` — an IP in `100.64.0.0/10` means the tailnet is up | WARN (local operation keeps working) |
| Services | Relay running | PID alive **and** control port 8088 responds (`/status`, 3 s timeout) | FAIL |
| | Companion running | existing `_companion_running` probe | WARN (buttons are optional) |
| Assets | cookies.txt | reuse `preflight.cookies_status` (presence, < 12 h, login markers) | WARN |
| | Graphics complete | Assets-tab labels vs. `runtime/graphics/<Label>.png`; every missing file named individually. No network / no `IRO_SHEET_ID` → fallback: directory exists and is non-empty | FAIL (missing file) / WARN (fallback only) |
| | Intro/Outro media | same comparison against `runtime/media/` (Intro Video / Outro Video rows) | WARN |
| Config | `.env` secrets | `IRO_SHEET_ID` and `IRO_TIMER_URL` set (env or `.env`) | FAIL |

Every WARN/FAIL detail names the fixing command (e.g. "run `iro cookies
firefox`", "run `iro graphics`", "run `iro install-apps`").

The report ends with a fixed **go-live reminder** (INFO, same model as
preflight's network advisory): *"Before going LIVE: refresh the HUD overlay
browser source in OBS once (right-click the source → Refresh) — its
auto-refresh is not fully reliable."* It prints in every `event status`, so
it also appears in the closing status after `event start`.

## `iro event start` — orchestration

Each step is **best effort**: a failure is reported and the sequence
continues (never aborts).

1. **Tailscale** — launch the app if `detect_tailscale_ip()` finds no IP;
   then poll up to ~10 s for an IP. First, because step 4 (Companion bind)
   needs the Tailscale IP. Still no IP after the timeout → print "sign in to
   Tailscale / run `tailscale up`" and continue localhost-only.
2. **Discord** — launch if not running (sign-in stays manual).
3. **Relay** — existing `relay_start([])`; skips with a message when already
   running. Before OBS, so the HUD browser source and the feed media sources
   connect against a live relay on OBS's first load instead of showing a
   stale/black page.
4. **OBS** — launch if not running. Windows quirk: `obs64.exe` must be
   spawned with `cwd` set to its `bin` directory or it cannot find its
   resources — handled by the launch helper.
5. **Companion** — existing `companion_start(["auto"])` (stop/bind/start
   logic unchanged).

Afterwards an automatic **`iro event status`** prints the closing picture, so
the operator immediately sees what remains (stale cookies, missing graphics,
…).

Deliberately NOT auto-started: `iro graphics` / `iro media` / `iro cookies`
(may need interaction or time — the status names the exact command instead)
and static-streams mode (fallback mode, not the event standard).

### Launch commands per OS (pure function, unit-tested)

| App | macOS | Windows | Linux |
|---|---|---|---|
| OBS | `open -a OBS` | `obs64.exe` from the `install_apps` path candidates, `cwd` = its `bin` dir | `obs` from PATH |
| Discord | `open -a Discord` | `%LOCALAPPDATA%\Discord\Update.exe --processStart Discord.exe` (Squirrel) | `discord` from PATH |
| Tailscale | `open -a Tailscale` | `tailscale.exe` from Program Files | no GUI launch — print hint `sudo tailscale up` |

App not installed → message pointing at `iro install-apps`, no abort.

## `iro event stop`

Stops iro-managed services only: relay, Companion, and any running static
streams. OBS / Discord / Tailscale are untouched; a closing line states that
explicitly ("OBS/Discord/Tailscale keep running — quit them manually if
needed"). Rationale: programmatically quitting OBS risks killing a live
broadcast on a mistyped command.

## Preflight extension — "Applications" section

New section in `preflight.gather()` (between "Tool chain" and "Ports"),
one check per app via `install_apps.app_present(app, sys.platform)`:

| App | installed | missing |
|---|---|---|
| OBS Studio | PASS | **FAIL** — no broadcast without OBS |
| Companion | PASS | WARN — "Stream Deck buttons unavailable; run `iro install-apps`" |
| Tailscale | PASS | WARN — "no remote access for director/tablet; run `iro install-apps`" |
| Discord | PASS | WARN — "interview audio unavailable; run `iro install-apps`" |

`import install_apps` works in all three run modes: standalone script (its
own dir is on `sys.path`), via `iro` (`scripts/` is injected at import time),
and frozen (same injection against the bundled tree). The existing 4455/8000
port probes stay — they answer "is it running?", the new section "is it
installed?".

## Internal structure

New module **`src/scripts/event.py`** — pure, testable building blocks; no
standalone entrypoint (invoked from `iro.py`):

- `process_running(name, platform)` — generic process probe: macOS/Linux
  `pgrep`, Windows `tasklist /FI` with `errors="replace"` (same OEM-codepage
  caveat as `_companion_running`). A per-app/per-OS process-name table sits
  next to it (`OBS`/`obs64.exe`/`obs`, `Discord`/`Discord.exe`, …). Output
  parsing is a pure function fed by mocked command output in tests.
- `launch_command(app, platform, env)` — returns `(argv, cwd)` or `None`
  plus a hint text (table above); reuses the app-path candidates from
  `install_apps.py`.
- `check_assets(labels, directory)` — pure: required list vs. directory
  contents, returns missing names. The Assets-tab fetch (CSV + label parsing)
  is reused from `get-graphics.py` via an importlib path-load (hyphenated
  filename — same mechanism as `iro.py`'s `_run_module`); fetch failure →
  local fallback.
- `gather_event_status(...)` — orchestrates all probes into
  `(section, [Result])` lists; reuses `preflight.Result`, `fmt_result`,
  `report` (same look, same exit-code logic, no duplication).

Wiring in **`iro.py`**: `event` becomes its own routed group with verbs
`status|start|stop`. `event_start` calls `companion_start` / `relay_start`
directly (in-process), so the frozen binary works unchanged (paths via
`_runtime_dir()` / `resource_path()` as everywhere else).

**Error behaviour:** every probe is wrapped in try/except → a broken probe
reports as WARN "check failed: …", never a traceback. Network timeouts short
(3 s, like `_relay_extra`).

## Out of scope (YAGNI)

- Quitting GUI apps from `event stop`.
- Auto-running `iro graphics` / `iro media` / `iro cookies` from `event start`.
- JSON output, continuous monitoring, a `--strict` mode.
- Starting static-streams mode from `event start`.

## Testing

- **`tests/test_event.py`** (stdlib runnable script, like the rest):
  - `launch_command` per platform (argv/cwd/`None` cases, app missing),
  - `check_assets` (all present / some missing / directory absent),
  - process-name table + pure parsers for pgrep/tasklist output (mocked),
  - readiness aggregation → exit code (FAIL/WARN/PASS combinations).
- **`tests/test_preflight.py`** — new cases for the Applications
  classification with an injectable presence function (`app_present` itself
  is already covered by `test_install_apps.py`).
- **`tests/test_iro.py`** — routing cases for `iro event status|start|stop`
  and the usage error for unknown verbs.
- Register any new test file in `tools/run-tests.py` if the runner lists
  files explicitly.

## Docs / build / delivery

1. Implement `src/scripts/event.py` + preflight "Applications" section.
2. Wire `event` into `src/iro.py` (routing, dispatch, `--help` docstring).
3. Tests as above.
4. Docs: `README.md` quickstart + CLAUDE.md command block (three new
   commands); the event-day wiki page gets the `iro event` workflow as its
   first step, then `python3 tools/sync-wiki.py`.
5. `python3 tools/build.py` — no build-script change expected (`scripts/` is
   copied wholesale); confirm the verify step passes.
