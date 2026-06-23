# Kill stale relay button (Control Center) — design

**Date:** 2026-06-23
**Status:** Approved for planning

## Problem

The Control Center's **Stop Relay** button only acts on the *tracked* relay — the PID
recorded in `runtime/relay.pid` (`relay_stop` in `src/racecast.py`). When a relay
becomes **orphaned** — it is still running and still holding the control port 8088
(plus the feed ports and its streamlink children), but the PID file is gone, stale, or
points elsewhere — Stop Relay reports "relay is not running" and cannot reach it. The
only recovery today is the CLI: `racecast freeport 8088`. Operators should not have to
drop to a terminal for this. They need a button.

The existing Relay card already has **Free feed ports** (`free-ports` → `racecast
freeport`), which clears orphaned holders of 53001–53003 but **does not target the
control port 8088**, so it cannot recover a stale relay.

## Goal

Add a **"Kill stale relay"** button to the Relay card in the Control Center that frees
the relay control port 8088 — recovering an orphaned/untracked relay — without dropping
to the CLI, and without any risk of cutting a live broadcast.

## Design

### Mechanism — reuse `freeport`, no new backend

The button runs `racecast freeport 8088`, the exact CLI operators use today. This needs
**no new racecast verb and no new handler**:

- New op in `src/ui/ui_ops.py`:
  ```python
  "kill-relay": ["freeport", "8088"],
  ```
- It routes through the existing `{"kind": "freeport", "rest": ["8088"]}` path in
  `src/racecast.py` (`parse_freeport_args` / `freeport_cmd`). The literal `"8088"`
  mirrors the documented CLI form (`racecast freeport 8088`); 8088 is the relay's fixed
  control port.

Killing the single PID listening on 8088 also frees the feed ports (53001–53003) and the
relay's streamlink children, because they all belong to that one process and its direct
children (`ports.kill_pid` kills the PID + direct children).

### No `--force`, by design — this is the safety property

The op deliberately does **not** pass `--force`. `freeport`'s owner-check
(`freeport_owner` + `decide_free` in `src/scripts/ports.py`) then yields exactly the
three correct outcomes, all streamed into the Control Center console dock via the normal
`watchJob` flow:

| Situation | `freeport 8088` result | Operator sees |
|---|---|---|
| **Orphaned/untracked relay on 8088** (the target case) | no live tracked relay → frees it | port freed; feed ports + children released too |
| **Port already free** | `clear` | `port 8088: already free` |
| **Healthy, tracked relay running** | `refuse` | `port 8088: held by running relay — stop it or use --force` → steered to **Stop Relay** |

Because a healthy relay is refused, the button is safe to leave **always visible** and
can never accidentally cut a live broadcast.

### Frontend — dedicated row in the Relay card

In `src/ui/control-center.html`, add a row to the Relay `<section>` immediately under the
relay lifecycle row (Start/Stop/Restart), mirroring the existing **Feed ports** row:

- A `danger` button: `onclick="op('kill-relay', true)"`, label **"Kill stale relay"**,
  reusing the same X-in-circle icon as Free feed ports.
- A `dim` explanatory span, e.g. *"control port 8088 — force-free a stale/orphaned relay
  the Stop button can't reach (unknown PID); a healthy relay is left untouched."*
- A `CONFIRM_TEXT['kill-relay']` entry (the `confirmFirst` modal): explains it frees the
  relay control port 8088 for a stale relay the Stop button can't reach, and that a
  healthy running relay is left untouched (use Stop Relay instead).

The op dispatch (`/api/op/<name>` in `src/ui/ui_server.py`) and `build_argv` need no
changes — `kill-relay` flows through the existing registry path like every other op.

### Intentionally NOT done

- **No cleanup of a leftover `runtime/relay.pid` / `runtime/relay.profile`.** This mirrors
  the CLI `freeport`, which does not touch PID files; the next `relay start`/`relay stop`
  already handles a stale PID file (`pid_alive` is false → proceeds / removes it). Least
  surprise, least code.
- **No new status plumbing.** The button is always visible (operator's choice), so no
  foreign-holder detection is added to `/api/status`.
- **No `--force` path from the UI.** If an operator truly needs to kill a *healthy*
  tracked relay, the correct action is Stop Relay; `--force` stays CLI-only.

## Testing

`tests/test_ui_ops.py` (pure registry checks, consistent with the existing
`t_ops_registry_routes_in_rc` pattern):

- `"kill-relay"` is present in `ui_ops.OPS`.
- `ui_ops.build_argv("kill-relay")` == `["freeport", "8088"]`.
- `rc.route(["freeport", "8088"])` resolves to kind `"freeport"` (already covered by the
  generic registry-routing assertion, which iterates every op — verify it still passes).

The underlying gate (`decide_free` refuse/clear/free) and `kill_pid` escalation are
already covered by `tests/test_ports.py`; no changes there.

## Wiki screenshot (same change, per CLAUDE.md)

The Relay card gains a row, so the matching wiki screenshot **`src/docs/wiki/images/cc-relay.png`**
is now stale and MUST be regenerated from a **local dev build** (run `racecast ui`
straight from `src/`, no `VERSION` stamped, so the badge stays "dev build") and committed
alongside the code — an element screenshot of the Relay card framed like the existing
image, not a full-window grab.

## Files touched

- `src/ui/ui_ops.py` — add the `kill-relay` op.
- `src/ui/control-center.html` — Relay-card row (button + dim text) + `CONFIRM_TEXT`.
- `tests/test_ui_ops.py` — registry assertions.
- `src/docs/wiki/images/cc-relay.png` — regenerated screenshot.
