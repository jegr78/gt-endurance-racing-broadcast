# POV box name + relay-driven POV PiP toggle

**Date:** 2026-06-14
**Status:** Approved — ready for implementation
**Issue:** #130 (OBS: POV Box: Add name)
**Area:** relay (`src/relay/racecast-feeds.py`), obs-websocket client
(`src/scripts/obs_ws.py`), HUD page (`src/obs/hud.html`), Director Panel
(`src/director/director-panel.html`), Companion config
(`src/companion/racecast-buttons.companionconfig`), Apps Script + wiki
(`src/docs/wiki/Sheet-Webhook.md`), the POV docs, tests.
**Builds on:** #129 — reuses the grey-box / white-text splitscreen label look.

> **Revision (during implementation):** the POV-box *visibility* design changed.
> The first version gated the box on the relay **feed** state (`/pov/reload` ·
> `/pov/stop`). That is the wrong signal — the on-screen PiP is shown/hidden by
> **POV Toggle**, which today is a direct obs-websocket action in the panel and
> Companion, invisible to the relay. The producer chose to make POV Toggle a
> **relay-driven action, modelled on `/next`**: the relay becomes the authority
> on PiP visibility, reflects it to OBS best-effort, and the HUD box follows the
> relay state. This spec reflects that final design.

## Problem

The HUD carries an (invisible-by-default) POV picture-in-picture frame slot
(`#pov`, issue #141) aligned to the OBS `Feed POV` scene item. When a driver POV
is on air there is no way to label *whose* POV it is, and the frame is always
present regardless of whether the PiP is shown. The producer wants:
1. a **free-text name** in the top-right corner of the POV box, and
2. the **whole POV box (frame + name) to appear only while the PiP is on screen**.

## The Sheet (POV name)

There is already a `POV` tab with a header row (`url`, `name`) and one data row
(row 2). The name is written to / read from the `name` column. **No new tabs or
cells**, no other tab touched. The relay reads this tab via `pov_source` (a
`ScheduleSource`); the existing `pov` webhook action writes the `url` cell — this
feature extends it with the `name` column.

## Decisions (confirmed with the producer)

- **POV name** — free text from the POV tab's `name` cell, clamped to 20 chars,
  may be empty (cleared). No Configuration-vocab check. Editable in the Director
  Panel's POV row (one SAVE writes name + URL) and restylable in the visual
  overlay builder (its own `data-edit` slot).
- **PiP visibility is relay-driven**, modelled on `/next`. The relay owns a
  `pov_shown` flag; new endpoints `/pov/toggle`, `/pov/show`, `/pov/hide` flip /
  set it and **reflect it to OBS** (enable/disable the `Feed POV` scene item in
  the `Stint` scene via obs-websocket, best-effort — exactly like `/next`
  reflects feed state). The Director Panel's POV visibility button and the
  Companion **POV Toggle** button both call `/pov/toggle` instead of poking OBS
  directly.
- **The whole POV box follows `pov_shown`.** `/hud/data` `povActive` = the relay's
  `pov_shown`; the HUD hides both `#pov` (frame) and `#pov-name` when it is false,
  shows the frame when true, and the name additionally when a name is set.
- **Feed (Reload/Stop) and PiP visibility (Toggle) stay separate** — same as
  today. `/pov/reload` · `/pov/stop` still control the pull; the new toggle only
  controls on-screen visibility + the HUD box. We only change *where* the toggle
  is handled (relay, not direct OBS).
- **Drift caveat (accepted, same as `/next`):** if someone enables/disables
  `Feed POV` directly in OBS, the relay's `pov_shown` can diverge until the next
  toggle re-asserts it. Documented.

## Architecture

### obs-websocket client (`src/scripts/obs_ws.py`)

Add a focused best-effort setter mirroring `reflect_feed_state`'s show/hide branch
and the `get_scene_collection` contract (returns a value + note, **never raises**):

```python
POV_SOURCE = "Feed POV"   # the Stint-scene PiP scene item (panel/Companion name)

def set_scene_item_enabled(scene, source, enabled, host="127.0.0.1", port=None,
                           password=None, timeout=2.0):
    """Enable/disable a scene item (best effort). Returns (ok, note); (False,
    reason) on any failure — OBS closed, wrong password, item missing — NEVER an
    exception (same contract as release_feed_inputs/get_scene_collection)."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    try:
        sid = session.request("GetSceneItemId",
                              {"sceneName": scene, "sourceName": source}).get("sceneItemId")
        if sid is None:
            return False, f"scene item '{source}' not found in scene '{scene}'"
        session.request("SetSceneItemEnabled",
                        {"sceneName": scene, "sceneItemId": sid,
                         "sceneItemEnabled": bool(enabled)})
        return True, ""
    except Exception as exc:                         # noqa: BLE001 — best-effort contract
        return False, str(exc) or exc.__class__.__name__
    finally:
        session.close()
```
Test it against the existing fake obs-websocket server (mirror
`t_probe_end_to_end_against_fake_server` / `t_release_feed_inputs_*`): the fake
server already handles `GetSceneItemId` is added for this (it currently handles
`SetInputSettings` etc.) — extend it to answer `GetSceneItemId` +
`SetSceneItemEnabled` and assert the enabled flag round-trips; plus an
unreachable-is-quiet test.

### Relay (`src/relay/racecast-feeds.py`)

- **State:** `self.pov_shown = False` in `Relay.__init__` (PiP hidden at start,
  matching today's default).
- **`pov_active()`** (replaces the feed-paused version from the earlier revision):
  ```python
      def pov_active(self):
          """True when the POV PiP is shown on screen (relay-driven, reflected
          to OBS by /pov/toggle|show|hide). Drives the HUD: the whole POV box —
          frame and name — shows only while the PiP is on air."""
          return self.pov_shown
  ```
- **`pov_name()`** unchanged (reads the POV tab `name` column via `pov_source`).
- **Set + reflect** (best-effort OBS reflect like `_reflect`/`reflect_feed_state`;
  isolated in a method so tests can stub it):
  ```python
      def set_pov_shown(self, shown):
          self.pov_shown = bool(shown)
          self._reflect_pov(self.pov_shown)     # best-effort OBS; never raises
          return {"shown": self.pov_shown, "obs": self.obs_note}

      def pov_toggle(self):
          return self.set_pov_shown(not self.pov_shown)
  ```
  `_reflect_pov(shown)` calls `_obs_ws.set_scene_item_enabled(STINT_SCENE,
  POV_SOURCE, shown)` when `_obs_ws` is available, stores the note in
  `self.obs_note`, and swallows everything (mirrors `_reflect`). When `_obs_ws`
  is None (frozen/dev without the module) it is a no-op — `pov_shown` still
  flips so the HUD box still works.
- **Routes:** `/pov/toggle` → `pov_toggle()`; `/pov/show` → `set_pov_shown(True)`;
  `/pov/hide` → `set_pov_shown(False)`. (Sit beside the existing `/pov/reload`,
  `/pov/stop`, `/pov/set`.)
- **`/hud/data`** already merges `povActive = relay.pov_active()` + `povName =
  relay.pov_name()` (unchanged from the earlier tasks; now `povActive` tracks
  `pov_shown`).
- **`/status`** `pov` object: keep `name`, add `"shown": self.pov_shown`.

### HUD page (`src/obs/hud.html`) — unchanged from the earlier task

`tick()` already gates `#pov` + `#pov-name` on `d.povActive` and renders
`d.povName`. No change needed — the page reads the same interface; only the relay
source of `povActive` changed.

### Director Panel (`src/director/director-panel.html`)

The POV visibility button currently lives in `CONFIG.vis` (`{label:"POV",
scene:"Stint", source:"Feed POV"}`) and toggles OBS directly (`toggleSource`),
with its on-air light read from OBS in `refresh()`. Make POV relay-driven:
- Mark the item: `{label:"POV", scene:"Stint", source:"Feed POV", relay:"pov"}`.
- Render (the `CONFIG.vis.forEach` at ~line 568): if `item.relay`, the click calls
  `relayCall("pov/toggle")`; otherwise `toggleSource(item, b)` as before. Keep a
  reference to the POV button (e.g. store it on a `povVisBtn` variable or find it
  in `toggleKeys` by `_item.relay`).
- `refresh()` OBS loop (~line 673): **skip** items whose `_item.relay` is set, so
  the OBS poll never overwrites the POV button's light.
- `relayPoll()` (~line 772, already reads `/status` `d.pov`): set the POV button's
  `.on` class from `d.pov.shown`.
- The POV **name/url row** in the URLs section is unchanged from the earlier task.

### Companion config (`src/companion/racecast-buttons.companionconfig`)

The **POV Toggle** button currently runs an obs-websocket `SetSceneItemEnabled`
action on scene `Stint` / source `Feed POV`. Replace that action with a
Generic-HTTP **GET `http://<relay>:8088/pov/toggle`** (the same module/pattern the
other relay buttons — NEXT, POV Reload, POV Stop — already use). The button
**text/face stays "POV Toggle"** (no screenshot refresh needed). Keep the
existing relay base-URL variable the other relay buttons use.

### Apps Script (`src/docs/wiki/Sheet-Webhook.md`) — done in the earlier task

`writePov` writes the `url` and/or `name` cell (header-aware); response `v: 5`;
action table updated. No further change.

## Data flow

1. Producer enters a POV name (≤20) + URL in the panel POV row → SAVE →
   `/pov/set {url,name}` → POV tab → `pov_source` → `/hud/data` `povName`.
2. Producer presses **POV Toggle** (panel or Companion) → `/pov/toggle` → relay
   flips `pov_shown`, enables/disables `Feed POV` in OBS (best-effort), returns
   the new state → `/hud/data` `povActive` flips → the HUD shows/hides the whole
   box (frame + name). Companion/panel show the same light from `/status`
   `pov.shown`.
3. Feed pull is still managed separately by **POV Reload / POV Stop**.

## Testing (TDD — test first)

- **`tests/test_obsws.py`**: `set_scene_item_enabled` round-trips the enabled flag
  against the fake server (extend the fake server to answer `GetSceneItemId` +
  `SetSceneItemEnabled`); unreachable → `(False, note)`, no raise.
- **`tests/test_pov.py`**:
  - `pov_active()` reflects `pov_shown`; `pov_toggle()` flips it and returns
    `{"shown": …}`; `set_pov_shown(True/False)` sets it. Stub `_reflect_pov` (like
    `_reflect` is stubbed in `_relay`) so the unit test does no OBS I/O.
  - `pov_name()` unchanged tests stay.
  - HUD page string checks (slot + povActive gating) stay.
- **`tests/test_setup.py`**: the `pov_set(url, name)` tests stay.

## Wiki + docs consistency (CLAUDE.md — same change)

Update every POV explanation to match the new behavior:
- **Architecture.md** — POV tab is `url` + `name` (not "cell A2"); add
  `/pov/toggle` (and show/hide) to the control-server endpoint list.
- **Relay-Mode.md** (Driver-POV PiP) — POV Toggle is a relay action; the HUD POV
  box (frame + name) follows it; the POV tab has `url` + `name`.
- **Director.md** — POV Toggle is relay-driven (panel + Companion); the POV name
  can be set in the URLs POV row; the box follows the toggle.
- **HUD-Overlays.md** — add the `#pov-name` slot; note the POV box shows only
  while the PiP is on air.
- **Companion.md** — POV Toggle now hits the relay (`/pov/toggle`).
- **cheat_sheets.html** — POV section: name field + POV Toggle as relay action.
- **Sheet-Webhook.md** — already updated (pov row = url and/or name).

Screenshots: `director-panel.png` (URLs POV name row — already refreshed) and
`cc-overlay-builder.png` (POV name slot — already refreshed). The POV Toggle
button face is unchanged → no Companion screenshot refresh.

## Out of scope / follow-ups

- No obs-websocket polling of PiP state (rejected in favor of relay-driven toggle).
- No coupling of PiP visibility to feed Reload/Stop.
- No POV name in the splitscreen labels (#129 stays role-only).
