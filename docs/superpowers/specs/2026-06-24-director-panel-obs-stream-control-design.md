# Director Panel — OBS Stream Start/Stop (relay-mediated)

**Issue:** [#295](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/295)
**Date:** 2026-06-24
**Status:** Approved — ready for implementation plan

## Problem

The Director Panel already remote-controls OBS (scene switches, source visibility,
audio, program monitor) through the relay-mediated OBS-WebSocket layer. The one
remaining "walk over to the OBS machine" step is taking the broadcast **live** and
ending it. This adds a Start/Stop control so a director can go live and stop the
stream from the panel — including over Funnel (`/console/panel`) with only their
per-person token.

## Feasibility (confirmed)

OBS-WebSocket v5 exposes `StartStream`, `StopStream`, `ToggleStream`, and
`GetStreamStatus`. The repo already speaks the protocol and already issues
`GetStreamStatus` for the Health Monitor (`obs_ws.parse_stream_status`,
`get_health_stats`). Start/Stop is the same minimal-client pattern as the existing
scene/source/audio helpers — no new dependency, no new transport.

## Scope

**In scope:** Stream Start/Stop only.

**Out of scope (deliberate, YAGNI):** Recording (`StartRecord`/`StopRecord`),
recording pause/resume, virtual camera. These follow the same shape and can be a
later issue if the team wants them.

## Design decisions (resolved with the user)

1. **Scope:** Stream Start/Stop only.
2. **Stop guardrail:** a `confirm()` dialog on **Stop** only (ending a live
   broadcast is high-consequence). **Start** stays a single click. Consistent with
   the panel's existing `confirm()` dialogs (e.g. Clear URL).
3. **Placement:** inside the existing **"Live Preview"** section, next to the
   Program monitor — where the director already watches the live state.
4. **Status reflection:** the button reflects the **real** OBS stream state, polled
   via the existing `/obs/state` poll (every 2 s), and shows the broadcast
   **duration**. The button cannot show a stale/false state.
5. **Idempotency:** the relay endpoint takes an **explicit** `{"on": true|false}`
   (not a toggle), and the helper is a **no-op success** when OBS is already in the
   requested state — safe under retries / double-clicks.
6. **Reconnecting:** surfaced as its own button state (the relay already reads
   `outputReconnecting`).

## Architecture

Same three-layer, relay-mediated model as the other OBS controls; the
OBS-WebSocket password never crosses the network and OBS-WebSocket is never
funnelled.

```
Director Panel (button) ──POST /obs/stream {on}──▶ relay ──▶ obs_ws.set_stream() ──▶ OBS-WebSocket
Director Panel (poll)   ──POST /obs/state──────────▶ relay ──▶ obs_ws.read_obs_state() ──▶ {…, stream}
```

### 1. `src/scripts/obs_ws.py`

- **`set_stream(active, host=…, port=…, password=…, timeout=…)`** — new helper in
  the existing best-effort style (mirrors `set_current_program_scene`). Opens one
  session, reads `GetStreamStatus`; if `outputActive` already equals `active`,
  returns `(True, "")` without sending anything (idempotent). Otherwise sends
  `StartStream` (active=True) or `StopStream` (active=False) and returns
  `(True, "")`. Any failure → `(False, note)`. Never raises. A `None` session
  (OBS unreachable) → `(False, note)`.
- **`parse_stream_status(payload)`** — extend to also surface
  `stream_timecode` from `outputTimecode` (kept as the raw OBS string, e.g.
  `"00:12:34.567"`; the panel trims milliseconds for display). Existing fields
  (`stream_active`, `stream_reconnecting`, …) are unchanged, so the Health Monitor
  path is unaffected.
- **`read_obs_state(sources, inputs, …)`** — add one `GetStreamStatus` request,
  wrapped in its own `try/except` (same per-item best-effort contract as the
  scene/audio reads). Returns an additional key:
  `"stream": {"active": bool|None, "reconnecting": bool|None, "timecode": str|None}`.
  A failure leaves `stream` as `None` and does not fail the whole read.

### 2. `src/relay/racecast-feeds.py`

- New handler in the OBS block (next to `/obs/scene`, `/obs/source`, `/obs/audio`,
  `/obs/state`, ~line 4731):

  ```
  if p == ["obs", "stream"]:
      if _obs_ws is None:
          return self._send({"error": "obs unavailable"}, 503)
      if "on" not in body:
          return self._send({"ok": False, "error": "stream needs on"}, 400)
      ok, note = _obs_ws.set_stream(bool(body.get("on")))
      return self._send({"ok": True} if ok
                        else {"ok": False, "error": note}, 200 if ok else 503)
  ```
- **Authorization:** no change needed. `console_policy.min_capability` already maps
  every `/obs/*` path to `Requirement(DIRECTOR, False)` (`console_policy.py:77`),
  so `/obs/stream` is director-gated automatically, on the tailnet and over Funnel.
- `/obs/state` automatically returns the new `stream` field (same `read_obs_state`
  handler, line ~4761) — no separate endpoint.

### 3. `src/director/director-panel.html`

- **Markup:** a broadcast button in the "Live Preview" section header (near the
  Program label / `#pvProgramLabel`). States:
  - **OFFLINE** — neutral/grey, label e.g. `OFFLINE — GO LIVE`.
  - **● LIVE `HH:MM:SS`** — red, shows the trimmed `timecode`.
  - **RECONNECTING…** — amber, when `stream.reconnecting` is true.
  - **unknown/disabled** — when OBS is unreachable (`/obs/state` 503).
- **State:** extend the `obsStatePoll()` handler (it already runs every 2 s) to read
  `d.stream` and render the button; store the last `stream` snapshot alongside
  `obsState`. The button is driven purely by the polled real state.
- **Click handler:**
  - If currently OFFLINE → `obsPost("stream", {on:true})`, then `obsStatePoll()`.
  - If currently LIVE/RECONNECTING → `confirm("End the live broadcast?")`; on
    confirm `obsPost("stream", {on:false})`, then `obsStatePoll()`.
  - Reuse the existing `obsPost()` (sets the OBS LED on failure) and `log()` for the
    `note` on error (e.g. "no stream service configured in OBS").
- Add `obsStream = (on) => obsPost("stream", {on})` next to `obsScene`/`obsSource`.

## Error handling / edge cases

- **OBS unreachable:** endpoints return `503`; the button shows the unknown/disabled
  state and the OBS LED goes `err` (existing `obsPost` behavior).
- **No stream service configured in OBS** (`StartStream` fails): `set_stream`
  returns `(False, note)`; the panel logs the note — never a silent failure.
- **Double-click / retry:** idempotent `set_stream` makes a repeated `{on:true}` a
  no-op success; no spurious "output already active" error reaches the user.
- **Reconnecting:** shown as a distinct amber state, not as OFFLINE.

## Testing

- **`tests/test_obsws.py`** (extend the existing fake obs-websocket server, which
  already models `output_active`):
  - `StartStream` / `StopStream` / `GetStreamStatus` handlers in the fake server.
  - `set_stream(True)` when offline → sends `StartStream`, `(True, "")`.
  - `set_stream(False)` when live → sends `StopStream`, `(True, "")`.
  - `set_stream(True)` when already live → **no `StartStream` sent**, `(True, "")`
    (idempotent no-op).
  - `set_stream` when OBS unreachable → `(False, note)`, never raises.
  - `read_obs_state` returns a `stream` dict with `active`/`reconnecting`/`timecode`;
    a `GetStreamStatus` failure leaves `stream` `None` without failing the read.
  - `parse_stream_status` surfaces `stream_timecode`.
- **Relay route test** (`tests/test_racecast.py` or the relay handler test file):
  `POST /obs/stream` → ok (200), missing `on` → 400, OBS unavailable → 503.
- **e2e** (`tools/e2e.py`, synthetic): OBS is not real in synthetic mode, so assert
  the endpoint **shape** (400 on missing `on`, director-gating) rather than a real
  start/stop. Optional and low priority.
- Run `python3 tools/lint.py` and `python3 tools/run-tests.py`.

## Docs

- **Wiki screenshot (mandatory, same PR):** the Director Panel changed, so
  `src/docs/wiki/images/director-panel.png` must be regenerated and committed in the
  same change (CLAUDE.md rule). Capture via Playwright MCP element screenshot of the
  panel, from a local dev build.
- Update the Director-Panel / OBS-control wiki page to mention the Start/Stop
  broadcast button. Publishing the wiki stays a separate `tools/sync-wiki.py` step.

## Non-goals

- Recording / virtual-camera control.
- Any browser→OBS-WebSocket direct connection (stays relay-mediated).
- Exposing stream URLs or OBS-WebSocket over Funnel (unchanged security boundary).
