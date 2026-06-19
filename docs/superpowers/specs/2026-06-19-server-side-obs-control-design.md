# Server-side OBS control — design (relay-mediated Director Panel)

*Design for issue #216. Moves the Director Panel's OBS control (scene switch,
source visibility, audio, program monitor) from the browser's direct
obs-websocket connection to relay HTTP endpoints, so the panel works fully over
the public Funnel with no OBS credentials at the client. Supersedes the deferred
Companion-over-Funnel idea (#236) for the director's core workflow.*

## Problem

The Director Panel (`src/director/director-panel.html`) splits its control into two
transports today:

- **Feeds, Timer, Chat, Status, Event-title** → relay HTTP (`fetch("/...")`). No OBS
  credentials. Works over the tailnet **and** over Funnel (`/console/panel`).
- **OBS scene switch / source visibility / audio (volume+mute) / program monitor** →
  the browser connects **directly to OBS-WebSocket** (`obs.connect("ws://<ip>:<port>",
  pw)`, director-panel.html:969) using `obs-websocket-js` from a CDN. The director types
  the producer's Tailscale IP + port 4455 + the OBS-WebSocket password.

Consequences:
1. **OBS control does not work over Funnel.** A Funnel-only director (no Tailscale
   account) cannot reach `ws://100.x:4455`, so over Funnel only feeds/timer work — the
   scene/audio half of the panel is dead. Exposing OBS-WebSocket over Funnel is **not**
   an option (it would put OBS's full control surface on the public internet).
2. **Credential burden + exposure.** Every director must hold the OBS-WebSocket password
   and type it into their browser; it travels over the tailnet to OBS. That is exactly
   the friction Companion buttons avoid — but Companion-over-Funnel is unbuildable
   (no base-path support; see the phase-8 spike, #236).

The relay already runs **on the producer's machine, next to OBS**, and already speaks
obs-websocket (`src/scripts/obs_ws.py`): it does `set_scene_item_enabled`,
`reflect_feed_state` (auto-cut), `get_program_screenshot`, `probe`, with the OBS
password auto-discovered locally (`find_password`). So the relay is the natural place to
mediate **all** OBS control.

## Locked decisions (from the 2026-06-19 discussion)

1. **Move OBS control server-side**, relay-mediated. The panel calls relay HTTP
   endpoints; the relay talks to its **local** OBS.
2. **Named intent endpoints** (not a generic OBS-request passthrough): exactly the
   operations the panel needs — `scene`, `source`, `audio`, `state`, `program`. A
   compromised director token can trigger only these broadcast ops, not arbitrary OBS
   requests. Matches the epic's per-route capability model.
3. **Remove the browser→OBS-WebSocket path entirely** — in **both** the tailnet `/panel`
   and the Funnel `/console/panel`. Drop the `obs-websocket-js` CDN script and the
   OBS IP/Port/Password card. One code path. OBS control targets the **relay host's OBS**
   (the on-air producer's machine — relay and OBS are co-located). *Trade-off (accepted):
   the panel can no longer point at an OBS on an arbitrary other IP.*
4. **Director-gated, no step-up.** Scene/source/audio are normal director control (like
   `/next`); they map to `Requirement(DIRECTOR, False)` in `console_policy`.
5. **Reuse the existing OBS plumbing** — per-request obs-websocket session,
   locally-discovered password, the existing `get_program_screenshot`. No persistent
   session in v1.

## Architecture

### A. `obs_ws.py` helpers (extend the existing set)

The relay already calls `obs_ws.set_scene_item_enabled`, `get_program_screenshot`,
`probe`. Add, in the same style (each opens a local session via the existing
`_open_session` + `request`, then closes — best-effort, returns `(ok, note)` or data):

- `set_current_program_scene(scene)` → `SetCurrentProgramScene{sceneName}`.
- `set_input_volume(input_name, db)` → `SetInputVolume{inputName, inputVolumeDb}`.
- `set_input_mute(input_name, muted)` → `SetInputMute{inputName, inputMuted}`.
- `read_obs_state(sources, inputs)` → opens **one** session and batches:
  `GetCurrentProgramScene`; per `(scene, source)` a `GetSceneItemId` + `GetSceneItemEnabled`;
  per input a `GetInputMute` + `GetInputVolume`. Returns
  `{"scene": <name>, "sources": [{"scene","source","enabled"}], "audio": [{"input","muted","volumeDb"}]}`.
  One round-trip for the whole panel refresh.

`set_scene_item_enabled(scene, source, on)` and `get_program_screenshot(width)` already
exist and are reused as-is.

Pure request-data builders (the JSON `requestData` dicts) are unit-tested in
`tests/test_obsws.py`, mirroring the existing `screenshot_request_data` test pattern; the
live session calls are not unit-tested (same boundary as today).

### B. Relay endpoints (root paths; the console gate falls through)

Added to `do_GET`/`do_POST` in `src/relay/racecast-feeds.py` as **root** paths
(`["obs", …]`), so they serve the tailnet `/panel` directly and the Funnel
`/console/panel` via the existing `_console_gate` fall-through (the gate authorizes
director, then dispatches the segment list — exactly like `/next`):

| Endpoint | Body / query | OBS action |
|---|---|---|
| `POST /obs/scene` | `{scene}` | `set_current_program_scene` |
| `POST /obs/source` | `{scene, source, on}` | `set_scene_item_enabled` (explicit `on`; the panel sends the negation of its polled state for toggles) |
| `POST /obs/audio` | `{input, db}` **or** `{input, mute}` | `set_input_volume` / `set_input_mute` |
| `POST /obs/state` | `{sources:[{scene,source}], inputs:[name]}` | `read_obs_state` → snapshot |
| `GET /obs/program` | — | the existing `get_program_screenshot` (JPEG) — reused, not new |

Each returns `{ok:true, …}` or `{ok:false, error, note}` when OBS is unreachable/closed
(best-effort; the panel renders the OBS LED from this + `/obs/state`). `/obs/state` is a
POST because it carries the league's scene/source/input vocabulary (which stays in the
panel — the relay never hardcodes league scene names).

### C. Capability (`src/scripts/console_policy.py`)

One row, director, no step-up:

```python
if p and p[0] == "obs":
    return Requirement(DIRECTOR, False)
```

`/obs/program` (the monitor image) may also be served to the cockpit's existing
any-authenticated program path; the panel reuses whichever program endpoint already
exists. Scene/source/audio/state are director-only.

### D. Director Panel changes (`src/director/director-panel.html`)

- **Remove**: the `<script src="…obs-websocket-js…">` CDN tag, the OBS **IP / Port /
  Password** card (the `#ip`/`#port`/`#pw` fields + the Connect flow), `new
  OBSWebSocket()`, `obs.connect(...)`.
- **Rewire** every `obs.call("X", data)` to the matching relay endpoint:
  - `SetCurrentProgramScene` → `POST /obs/scene`.
  - `GetSceneItemId`+`SetSceneItemEnabled` → `POST /obs/source {scene,source,on}` (the
    relay resolves the item id; the panel sends `on`).
  - `SetInputVolume`/`SetInputMute`/`ToggleInputMute` → `POST /obs/audio`.
  - the `refresh()` state poll (current scene + source-enabled + mute/volume) →
    `POST /obs/state` with the panel's configured `{sources, inputs}` → render LEDs/active
    states from the snapshot.
  - the program monitor `<img>` → the program endpoint.
- All `fetch` calls stay **relative**, so they resolve under `/console` (via the existing
  `RC_API_BASE` shim) and at root (tailnet) unchanged.
- The OBS **LED** reflects `/obs/state` success (OBS reachable) instead of the WS
  connection state. The "enter IP + password + Connect" log hint is removed.

### E. Program monitor

Reuse the relay's existing `get_program_screenshot` (already used by the cockpit at
`racecast-feeds.py:3284`). The panel points its program `<img>` at that endpoint; no new
screenshot plumbing.

## Security analysis

- **Strictly more secure than today.** The OBS-WebSocket password never leaves the
  producer's machine (today it is typed into the director's browser and sent to OBS over
  the tailnet). OBS-WebSocket is **never** exposed over Funnel.
- **Bounded blast radius.** Named intent endpoints mean a compromised director token can
  only switch scenes / toggle the configured sources / set audio / read state / view the
  program — not issue arbitrary OBS requests (no recording control, no settings, no
  plugin calls). This is the deliberate choice over a generic passthrough.
- **Boundary unchanged.** Only `/console` is Funnel-mounted; `/obs/*` is reached publicly
  only through the director-gated console gate. Root `/obs/*` stays tailnet/loopback.
- **Trust model.** Director-gated equals the existing panel-over-Funnel director gate; no
  new trust assumption beyond what `/console/panel` already grants.

## Testing

- `tests/test_obsws.py`: request-data builders for the new helpers
  (`SetCurrentProgramScene`, `SetInputVolume`, `SetInputMute`) + the `read_obs_state`
  batching shape (pure; no live OBS).
- `tests/test_console_gate.py`: `/console/obs/{scene,source,audio,state}` require director
  (401 no token, 403 commentator, 200 director); `/obs/program` per its chosen capability.
- `tests/test_console.py` / policy: the `obs` → `Requirement(DIRECTOR, False)` row.
- `tests/test_pov.py`: relay regression (the new root routes don't disturb existing
  dispatch).
- The panel's browser logic is HTML (not unit-tested); the live OBS calls keep the
  existing best-effort boundary.

## UI screenshots (CLAUDE.md hard rule)

The Director Panel loses the OBS IP/Port/Password card and its connection log hint →
**`src/docs/wiki/images/director-panel.png` MUST be refreshed** in the same change (dev
build, driven via Playwright). Companion/Tablet button images are unaffected.

## Phasing — one PR, ships green

A single self-contained change (the obs_ws helpers + relay endpoints + panel rewire +
policy row + tests + the screenshot) is cohesive enough for one phase/PR. Suggested task
split for execution: (1) `obs_ws` helpers + `tests/test_obsws.py`; (2) relay `/obs/*`
endpoints + `console_policy` row + gate/relay tests; (3) panel rewire (remove WS card,
fetch-based control) + `director-panel.png`; (4) docs (CLAUDE.md, wiki) + full gate.

## Out of scope / explicit

- **Companion-over-Funnel** stays deferred (#236) — this design removes the *need* for it
  in the director workflow; physical Companion buttons remain a local/tailnet convenience.
- **Controlling an OBS on a different machine than the relay** — dropped (decision 3);
  relay and OBS are co-located on the on-air producer's machine.
- **A warm persistent OBS session** — a later latency optimization only; v1 is per-request.
- **Recording / streaming / settings control** — intentionally not exposed (bounded
  surface).
