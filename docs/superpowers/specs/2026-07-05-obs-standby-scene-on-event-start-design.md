# Auto-switch OBS to the Standby scene at `event start`

**Date:** 2026-07-05
**Status:** Design approved, pending implementation

## Problem

The Director Guide instructs the producer to **start the broadcast on the Standby
scene**, then hit *Start Streaming* and let the director open with the Intro
(`src/docs/wiki/Run-an-event.md:99`, `src/docs/slides/producer.html:74`,
`src/docs/slides/director.html:74`). Today `racecast event start` brings the whole stack
up — Tailscale, relay, OBS, Companion, the scene-collection check/switch, and the forced
OBS browser-source refresh — but leaves OBS on **whatever scene it happened to be on**
(often a Stint/feed scene from the last session). The producer must remember to manually
click the Standby scene before going live.

This is a small but real gap for the **remote-producer (GCP)** setup, where the whole
point is that `event start` leaves the box in a known, ready-to-stream state with minimal
manual OBS interaction.

## Goal

After the existing bring-up steps (scene-collection check → forced OBS refresh), park OBS
on the **Standby** program scene so the producer's OBS is sitting exactly where the
Director Guide says to start. Default-on, with a kill-switch, and — critically — it must
**never cut a live program**.

## Non-goals (YAGNI)

- **No new Director-Panel or Companion UI.** Directors already switch to Standby via the
  panel's `/obs/scene` action and the Companion "Standby Scene" button. This is a
  bring-up convenience only.
- **No configurable scene name.** The scene is `Standby` in the shipped collection
  (`src/obs/GT_Endurance.json`), and localization (`setup-assets.py`) never renames
  scenes. A league that renamed it uses the kill-switch instead. (One constant, no env
  override.)
- **No transition selection.** The switch is a plain program-scene set (implicitly OBS's
  current default transition). Landing on Standby before the stream is live needs no
  director-take semantics.
- **No change to the collection-switch or refresh steps.** They stay exactly as they are;
  this appends one step after them.

## Design

### Ordering

`src/racecast.py`, in `event_start`, the switch is a new call immediately **after** the
forced refresh (current line `3237`):

```python
_check_scene_collection()
_refresh_obs_pages(force=True)
_switch_to_standby()          # NEW — park OBS on Standby, ready to Start Streaming
```

- **After the collection switch** (which rebuilds every source and only takes effect on
  the correct collection) so we land on *this* collection's Standby scene.
- **After the forced refresh** so the Standby scene's browser sources (if any) are already
  fresh when we land on it.
- **`event takeover` inherits it** automatically — it calls `event_start(...)`
  (`src/racecast.py:3429`), so both the tailnet and `--funnel` takeover paths get the same
  behavior. The not-live guard (below) makes a takeover onto an already-streaming OBS a
  no-op, so a mid-event takeover never cuts the live program.

### Part 1 — `obs_ws.switch_to_scene_if_idle()`

`src/scripts/obs_ws.py`, a new best-effort helper next to the other scene helpers
(e.g. after `set_current_program_scene`):

```python
def switch_to_scene_if_idle(scene, host="127.0.0.1", port=None,
                            password=None, timeout=2.0):
    """Switch OBS to `scene` ONLY when no stream output is active — never cut a
    live program. Reads GetStreamStatus first; if the stream is live, leaves the
    program scene untouched. Best effort — never raises (same contract as
    get_program_screenshot). Returns (action, note) where action is one of:
      "switched" — OBS was idle; SetCurrentProgramScene sent
      "live"     — OBS is streaming; NO switch sent (note explains)
      "error"    — could not reach OBS / a request failed (note has the reason)."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return "error", note
    try:
        status = parse_stream_status(session.request("GetStreamStatus", {}))
        if status.get("stream_active"):
            return "live", "OBS is streaming — left the program scene untouched"
        session.request("SetCurrentProgramScene", {"sceneName": scene})
        return "switched", ""
    except Exception as exc:                          # noqa: BLE001 — best-effort contract
        return "error", str(exc) or exc.__class__.__name__
    finally:
        session.close()
```

Notes:
- The guard + switch share **one session** so the status read and the switch cannot race
  each other across connects.
- `parse_stream_status` already returns `stream_active` (a flattened `outputActive`,
  `src/scripts/obs_ws.py:487-501`). A `None` (missing key) is falsey, so an OBS that does
  not report status is treated as idle and the switch proceeds — acceptable for a
  pre-stream bring-up (the caller only runs during `event start`, before Start Streaming).
- Returns a **three-way action** rather than a bare bool so the CLI can print a distinct,
  honest line for the "skipped because live" case vs. a real error.

### Part 2 — `_switch_to_standby()` + the enable flag

`src/racecast.py`:

```python
STANDBY_SCENE = "Standby"   # canonical scene name in src/obs/GT_Endurance.json


def _standby_on_start_enabled():
    """Opt-OUT: `event start` parks OBS on the Standby scene by default. Setting the
    machine flag RACECAST_OBS_STANDBY_ON_START to a falsey value (0/false/no/off)
    disables it; absent/empty means enabled. Mirrors _collection_switch_enabled."""
    return _machine_env_value("RACECAST_OBS_STANDBY_ON_START").strip().lower() \
        not in {"0", "false", "no", "off"}


def _switch_to_standby():
    """After bring-up, park OBS on the Standby scene (Director Guide: start on
    Standby, then Start Streaming). Default-on; RACECAST_OBS_STANDBY_ON_START=0
    disables. Best-effort: never blocks bring-up, and NEVER cuts a live program
    (switch_to_scene_if_idle skips when OBS output is active)."""
    if not _standby_on_start_enabled():
        return
    try:
        import obs_ws
    except Exception as exc:                          # noqa: BLE001 — best effort
        print(f"obs: standby switch skipped ({exc}).")
        return
    action, note = obs_ws.switch_to_scene_if_idle(STANDBY_SCENE)
    if action == "switched":
        print(f"obs: switched to the '{STANDBY_SCENE}' scene — ready to Start Streaming.")
    elif action == "live":
        print(f"obs: '{STANDBY_SCENE}' switch skipped — {note}.")
    else:  # error
        print(f"obs: '{STANDBY_SCENE}' switch skipped — {note}. "
              f"Switch to Standby manually before going live.")
```

Placement: define `_switch_to_standby` and `_standby_on_start_enabled` near
`_check_scene_collection` / `_collection_switch_enabled` (the constant `STANDBY_SCENE`
next to the other module constants). The env helper mirrors `_collection_switch_enabled`
verbatim in shape.

### Part 3 — `.env.example`

Add a commented kill-switch line directly next to the existing collection-switch line
(`.env.example:25`):

```dotenv
# RACECAST_OBS_COLLECTION_SWITCH=0
# RACECAST_OBS_STANDBY_ON_START=0
```

(A short comment above it, matching the file's style, explaining it stops `event start`
from parking OBS on the Standby scene.)

## Testing

`tests/test_obsws.py` — add coverage for `switch_to_scene_if_idle` using the existing
fake-session pattern:

1. **Idle → switched.** Fake `GetStreamStatus` returns `outputActive: false`. Assert the
   return is `("switched", "")` **and** a `SetCurrentProgramScene` request was sent with
   `{"sceneName": "Standby"}`.
2. **Live → no switch.** Fake `GetStreamStatus` returns `outputActive: true`. Assert the
   return action is `"live"`, the note is non-empty, and **no** `SetCurrentProgramScene`
   request was sent (guard against cutting a live program — this is the safety-critical
   assertion).
3. **Unreachable → error.** `_connect` yields no session (mirror the existing
   `t_refresh_browser_inputs_unreachable_is_quiet` setup). Assert the action is `"error"`
   and the call did not raise.

No production change is needed in `parse_stream_status` (already returns `stream_active`).

Full gates: `python3 tools/run-tests.py` and `python3 tools/lint.py`.

## Repo-rule obligations (same change, not a follow-up)

- **CLAUDE.md:** extend the `racecast.py` `event start` description and the `obs_ws.py`
  section to note the new Standby-on-start step and the `RACECAST_OBS_STANDBY_ON_START`
  kill-switch. Mention it in the `racecast event start` CLI line alongside the existing
  `RACECAST_OBS_COLLECTION_SWITCH` note.
- **No UI surface changes** → no wiki screenshot, no `ui-visual-verification`. (Explicitly
  called out so a reviewer does not flag their absence.)

## Security & remote-producer notes

- No new endpoint, no new public surface. `_switch_to_standby()` runs only in the CLI
  bring-up path and speaks OBS-WebSocket **locally** (`127.0.0.1`), exactly like
  `_check_scene_collection` and `_refresh_obs_pages`. OBS-WebSocket is never funnelled.
- The not-live guard is the security-relevant invariant: on a re-run or a mid-event
  takeover where OBS is already streaming, the switch is a no-op — a bring-up command can
  never cut a live broadcast.
