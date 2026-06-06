# Tailscale connect/disconnect control — design

**Date:** 2026-06-06
**Status:** approved

## Problem

`iro event start` launches the Tailscale app when no tailnet IP is found, but it
cannot *connect* a Tailscale that is running-but-disconnected (BackendState
`Stopped` — e.g. the producer toggled it off after the last event). The operator
has to click "Connect" in the Tailscale GUI manually. The CLI can do this
non-interactively: an argument-less `tailscale up` "brings the network online
without changing any settings" (verified against the macOS app-bundle CLI), and
`tailscale down` is its exact opposite.

This builds on the `parse_tailscale_status()` fix (BackendState-aware detection,
branch `fix/tailscale-connected-check`): detection now correctly reports a
stopped Tailscale as disconnected, so `event start` can act on that state.

## Scope decisions

- **`iro event start`** connects a stopped Tailscale automatically (step 1 of
  the bring-up).
- **New command `iro tailscale up|down|status`** for explicit control outside
  the event bring-up.
- **`iro event stop` stays unchanged** — it does not disconnect (philosophy:
  GUI apps keep running; the producer may need remote access after the event).
- `iro relay start` / `iro companion start` stay unchanged; they pick up the
  connected state automatically when started via `event start`.

## Architecture

### New module `src/scripts/tailscale.py`

All Tailscale logic moves here (one module, one purpose — matches the
`scripts/` style):

- `_TAILSCALE_BINS`, `_in_cgnat()`, `parse_tailscale_status()`,
  `detect_tailscale_ip()` — **moved** from `companion_common.py`.
- `parse_tailscale_backend(json_text) -> (state, ip)` — pure: BackendState
  string plus Self's first CGNAT IPv4 (IP only when Running), `(None, None)`
  on garbage. `parse_tailscale_status()` becomes a thin wrapper returning just
  the Running IP.
- `tailscale_backend() -> (binary, state, ip)` — finds the CLI binary and
  queries `status --json`; `(None, None, None)` when no CLI/backend responds.
- `tailscale_up(binary, timeout=15)` / `tailscale_down(binary, timeout=15)` —
  run the argument-less `up`/`down`. The subprocess timeout is a backstop in
  case `up` unexpectedly enters the interactive login flow; the callers never
  invoke `up` in the `NeedsLogin` state.
- `plan_tailscale_up(state) -> action` — pure decision helper (testable):
  `"connected"` (Running), `"run-up"` (Stopped/Starting), `"needs-login"`
  (NeedsLogin/NeedsMachineAuth), `"launch-app"` (no backend).

`companion_common.py` **imports** the detection from `tailscale.py` instead of
duplicating it and keeps only Companion bind/control logic (its name is
accurate again). The relay (`src/relay/iro-feeds.py`) keeps its own documented
copy — it stays a standalone single file. CLAUDE.md's "keep in sync" note now
points at relay ↔ `scripts/tailscale.py`.

### New CLI command (`src/iro.py`)

`iro tailscale up|down|status` dispatches to the module:

| State | `up` | `down` | `status` |
|---|---|---|---|
| Running | "already connected (IP)" | run `down`, confirm | state + IP |
| Stopped | run `up`, re-check, report IP | "not connected." | state + hint `iro tailscale up` |
| NeedsLogin | do **not** run `up` (would trigger interactive browser auth); hint: sign in via the Tailscale app | "not connected." | state + sign-in hint |
| no backend | launch the app (reuse `event.py` launcher), wait briefly, then `up` | "not connected." | "Tailscale not running" + hint |

Platform notes:
- macOS: the app-bundle CLI (`/Applications/Tailscale.app/.../Tailscale`)
  supports `up`/`down`; the backend only runs while the app runs, hence the
  launch-app fallback.
- Linux: `up` typically needs root — pass the CLI's error through and keep the
  existing `sudo tailscale up` hint.
- Windows: `tailscale.exe up` works for the logged-in (operator) user.

### `iro event start` integration

Step 1 becomes: query `tailscale_backend()`; Running → "already connected";
Stopped → `tailscale_up()`; no backend → launch app (existing behaviour), brief
wait, then `up` if the state lands on Stopped; NeedsLogin → existing sign-in
hint. The ~10 s IP poll stays as the final confirmation.

## Error handling

Everything is best-effort like the rest of `event start`: any `up`/`down`
failure prints one line (CLI stderr included) plus the platform hint and never
aborts the bring-up.

## Testing

- `tests/test_tailscale.py` (new): pure parsers (`parse_tailscale_backend`
  state/IP matrix, garbage input) and `plan_tailscale_up` decisions.
- `tests/test_companion.py`: detection smoke now exercises the import from
  `tailscale.py`.
- `tests/test_bind.py`: unchanged (relay copy).
- `tests/test_iro.py`: routing for `iro tailscale up|down|status` (+ rejection
  of unknown subcommands).

## Docs

README command list, CLAUDE.md command block + architecture notes (module move,
new sync pointer), wiki operator pages where `event start`/Tailscale are
described.
