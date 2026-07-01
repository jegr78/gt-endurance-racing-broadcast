# Director Per-Take Transitions — design

**Date:** 2026-07-01
**Status:** approved (brainstorming) → ready for implementation plan
**Persona:** Director — chooses the transition for a scene take from the Director Panel

## Problem

Every scene switch the Director Panel makes today is a hard cut (`SetCurrentProgramScene`
with whatever transition OBS happens to have selected). The director cannot choose a
transition per take. We want a **Cut / Fade / Stinger** selector on the panel so the
director controls how each scene take happens.

## Hard constraint (established during brainstorming)

OBS-WebSocket applies a transition only to a **scene switch**, never to a **source
visibility toggle** (`SetSceneItemEnabled` is a hard on/off with no transition parameter).
So "Fade/Stinger on a source inside a scene" is not achievable via the API and is out of
scope. The feature is per-take transitions on **scene switches**. The shipped OBS
collection has only OBS's default **Cut + Fade** — **no Stinger** (no stinger transition,
no media source); a Stinger requires the producer to create one in OBS. There is **no
transition support anywhere in the codebase today** (client, relay, panel, policy, tests).

## Scope

In scope:
- A **Cut / Fade / Stinger** selector on the Director Panel (fixed three choices).
- Applying the chosen transition to director-initiated **scene switches** (the scene bus
  and the scene step of each macro).
- A best-effort OBS-WS path that sets the transition + duration, then switches.

Explicitly **out of scope** (YAGNI):
- Per-source-toggle transitions (OBS-WS can't).
- Shipping a stinger media asset / auto-provisioning a Stinger into the collection.
- Studio-mode preview/transition (contradicts the crew's no-preview-then-take model).
- Distinct transitions per individual scene button (the sticky selector covers it).

## Key decisions (from brainstorming)

1. **Fixed Cut / Fade / Stinger** buttons (not a dynamic list), resolved server-side to a
   real OBS transition **by kind** (`cut_transition` / `fade_transition` /
   `stinger_transition`) so "Stinger" finds whatever the producer configured.
2. **Sticky (set-and-forget):** the active choice persists across takes until changed;
   it is applied to every director scene switch. **Default active = Fade** (300 ms).
3. **Automated cuts stay hard cuts:** feed A/B handover (`reflect_feed_state`) and
   auto-failover switch with no transition — reliability first. Only director-manual
   switches carry a transition.
4. **Stinger degrades gracefully:** if Stinger is picked but none is configured, the take
   still happens as a **Cut**, with a note surfaced in the panel. The broadcast is never
   blocked.

## Architecture

### `src/scripts/obs_ws.py`
- New pure helper `resolve_transition(choice, transition_list) -> (name | None, note)`:
  given `choice ∈ {"cut","fade","stinger"}` and the `GetSceneTransitionList` payload
  (`transitions: [{transitionName, transitionKind}]`), return the transition **name** to
  use — matched by kind (`cut_transition`/`fade_transition`/`stinger_transition`), falling
  back to a case-insensitive name match ("Cut"/"Fade") for cut/fade. For `stinger` with no
  stinger-kind entry → `(None, "no Stinger configured in OBS; used Cut")`.
- `set_current_program_scene(scene, transition=None, duration_ms=None)` — when `transition`
  is given: `GetSceneTransitionList` → `resolve_transition`; if a name resolved,
  `SetCurrentSceneTransition {transitionName}` then `SetCurrentSceneTransitionDuration
  {transitionDuration: duration_ms}` (duration skipped/0 for cut); if `stinger` resolved to
  None, fall back to the Cut transition and carry the note; finally `SetCurrentProgramScene
  {sceneName}`. Returns `(result, note)` — never raises (the existing best-effort contract).
  Called with no `transition` → today's plain switch (backward compatible).
- Uses the existing single-shot session seam (`_Session.request`); one added request type
  family, no auth/transport change.

### Relay `/obs/scene` (`src/relay/racecast-feeds.py`)
- Accepts optional `{transition, duration}` in the POST body → forwards to
  `set_current_program_scene(scene, transition, duration_ms)`. Director-gated exactly as
  today (`console_policy` `Requirement(DIRECTOR, False)` for any `/obs/*` path — no policy
  change). `duration` clamped to 0–10000 ms; Cut forces 0. Best-effort 200/503 contract
  unchanged; a stinger-fallback note rides in the 200 body (e.g. `{"ok":true,"note":...}`).

### Director Panel (`src/director/director-panel.html`)
- A **transition bar** above the scene bus: three toggle buttons **Cut · Fade · Stinger**
  (one active, highlighted) + a **duration** input (ms, default 300; disabled when Cut is
  active). Sticky front-end state `activeTransition` / `activeDuration`, default
  **Fade / 300**.
- `obsScene(scene)` and the scene step of `runMacro(...)` include the active
  `{transition, duration}` in the `/obs/scene` POST. Source-toggle and audio steps inside
  macros are unchanged (instant). Rendered with the existing `obsPost`/LED conventions; a
  stinger-fallback note surfaces via the same status path.

## Data flow

`click scene / run macro` → panel reads sticky `activeTransition`+`activeDuration` →
`POST /obs/scene {scene, transition, duration}` → relay (director-gated) →
`obs_ws.set_current_program_scene(scene, transition, duration_ms)` →
`GetSceneTransitionList` → `resolve_transition` → set transition + duration → switch scene.

## Edge cases & failure modes

- OBS unreachable → the existing `/obs/scene` 503 path; the transition adds no new failure
  surface.
- `GetSceneTransitionList` fails or a kind isn't found → cut/fade fall back to the literal
  names "Cut"/"Fade"; stinger degrades to Cut + note. Never raises.
- Backward compatibility: `/obs/scene` with no `transition` behaves exactly as today; the
  automated cut paths (`reflect_feed_state`, auto-failover) pass no transition and are
  unchanged.
- `duration` out of range → clamped; Cut → 0.

## Testing

- **`tests/test_obsws.py`** — `resolve_transition` (kind match for each choice; name
  fallback for cut/fade; stinger-absent → `(None, note)`); `set_current_program_scene`
  with `transition="fade"` emits `SetCurrentSceneTransition` + `SetCurrentSceneTransitionDuration`
  + `SetCurrentProgramScene` in order (via `_FakeSession.sent`); `transition="stinger"` with
  a stubbed stinger-kind list resolves it; stinger-absent → falls back to Cut + note; no
  `transition` → only `SetCurrentProgramScene`. Add a `GetSceneTransitionList` branch to the
  fake OBS server.
- **`tests/test_console_gate.py`** — `POST /console/obs/scene` with a `transition` body still
  requires director (policy unchanged) and the param is accepted end-to-end.

## Docs & screenshots

- **Director Panel changed ⇒ screenshot-blocking** (CLAUDE.md hard rule): regenerate
  `src/docs/wiki/images/director-panel.png` in the same PR (transition bar visible), via the
  `wiki-screenshots` skill (demo profile + obs-sim).
- Document the transition bar on the Director-Panel / console wiki page, noting that Cut and
  Fade always work and **Stinger requires the producer to configure one in OBS** (else the
  take falls back to a cut). No new `.env` knob, no CLI verb.

## Out-of-scope follow-ups (not this PR)

- Bundling a stinger media asset + auto-provisioning a Stinger transition.
- Per-source show/hide transition control (needs an OBS capability that doesn't exist over
  WS today).
