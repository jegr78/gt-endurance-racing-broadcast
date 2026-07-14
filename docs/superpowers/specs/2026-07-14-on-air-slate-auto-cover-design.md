# On-Air Slate — auto-raise the Standby Cover when the on-air source is offline

**Date:** 2026-07-14
**Issue:** #495 (remainder). Core (source-state classification + churn dampening) shipped in #502.
**Status:** Design approved, ready for planning

## Problem

When an on-air feed's source is **offline / not-live-yet / live-ended**, OBS keeps showing
the feed media source, which has no picture — so the broadcast goes **black**. The single
worst N24 24h outage was exactly this: stint 9 (`sgoDA5E4aJ0`), a commentator's PS-over-WiFi
upload collapsed so hard that **YouTube ended the broadcast**, and the relay retried the dead
URL for **~4 minutes of black on air with no fallback**. A second class hit at handovers when
a Twitch channel was **not yet live** (stint 6, `kekko_simracing`, ~4 min).

#502 (#495 core) already **classifies** these states — `Feed.source_state ∈
{"not_live_yet", "ended", None}` — and dampens the `@here` churn for them. What it does not
do is **present an intentional slate** instead of black. That is this issue's remainder, and
the #495 checklist item still open: *"On-air shows an intentional slate (not black/frozen)
while a source is offline/connecting."*

## Goal

Automatically raise the existing **Standby Cover** (built in #378) over the on-air picture
when the **on-air** feed's classified `source_state` says the source is offline/ended, and
lower it again when the source is confirmed live — **keeping the HUD** (Overlay frame, Race
Control banner, race timer) visible on top the whole time. Default-on, opt-out, best-effort,
and it must **never fight the director** (manual RED FLAG button always wins).

## Prior art this reuses (do NOT duplicate)

- **#378 Standby Cover** — an `image_source` named **`Standby Cover`** in the **`Stint`**
  scene, sitting above the feeds/POV but **below** the HUD group, hidden by default, toggled
  today by the Director Panel **RED FLAG** button (`src/director/director-panel.html`, the
  `{scene:"Stint", source:"Standby Cover"}` toggle) and a Companion **Standby Toggle**
  button. The panel's RED FLAG light already reflects **real** OBS visibility via
  `/obs/state`, so it lights when the cover is up regardless of who raised it.
- **#378 auto-failover** — `_maybe_auto_failover(now)` in the relay heartbeat, gated by
  `RACECAST_AUTO_FAILOVER` (**off** by default), switches OBS to the **Intermission** scene
  on a *generic* confirmed-down (`feed_health_state == "down"`, past the 30 s red grace),
  fires once per outage, re-arms on a manual return to the on-air scene. This auto-cover is a
  **different, gentler rung** below it (see Escalation ladder).
- **#502 classification** — `classify_source_state(text)` and `Feed.source_state`, set in the
  feed run loop from streamlink/yt-dlp errors and cleared on a confirmed-live serve.
- **obs-ws source visibility** — `_obs_ws` `SetSceneItemEnabled` (the same call
  `POST /obs/source` and the RED FLAG button use). Best-effort contract: an unreachable OBS
  returns a note, never raises.

## Escalation ladder (how auto-cover coexists with auto-failover)

| Rung | Trigger | Action | Default | HUD |
|---|---|---|---|---|
| **Auto-cover (this issue)** | on-air `source_state ∈ {not_live_yet, ended}`, ~12 s settle | raise `Standby Cover` in `Stint` | **on** (opt-out) | **kept** |
| Auto-failover (#378) | on-air `feed_health_state == "down"`, past 30 s red grace | switch OBS → `Intermission` | off (opt-in) | lost |

In the default config only auto-cover runs. If a producer also opts into failover, the order
is: **cover first** (keep HUD, ~12 s in), then **Intermission** if the feed stays dead past
the red grace. They do not conflict because auto-cover only manages the cover **while OBS is
on the `Stint` scene** — once failover has switched OBS to Intermission, auto-cover is a
no-op (the Stint cover is not visible and is not touched).

## Design

### Trigger & timing

A dedicated lightweight daemon tick (`AUTO_COVER_POLL_S = 5`) evaluates the on-air feed. The
30 s health heartbeat is deliberately **not** reused for this — covering black is
time-sensitive in a way the health cadence is not.

- **`Feed.offline_since`** — a timestamp set when `source_state` transitions
  `None → classified`, and cleared (`None`) when `source_state` returns to `None`. This lets
  any cadence compute the settle with a pure comparison, no per-tick counters.
- **Settle** — raise only once `source_state` has persisted `≥ AUTO_COVER_SETTLE_S = 12` s
  (`now - offline_since >= 12`). `source_state` is itself already specific (set only on the
  classified errors, not on a generic 2 s reconnect blip), so the settle mainly prevents a
  flicker at the exact recovery edge.

Both `AUTO_COVER_POLL_S` and `AUTO_COVER_SETTLE_S` are module constants.

### State machine (fire-once + re-arm, never fights the human)

Modeled on `_maybe_auto_failover`'s proven fire-once/re-arm. Relay-level state:
`_cover_fired` (auto has already raised the cover for the current outage) and
`_cover_auto_owned` (auto raised the cover that is currently shown).

- **Raise** (once per outage): `enabled` AND on-air `source_state ∈ {not_live_yet, ended}`
  AND `now - offline_since >= settle` AND cover **not** currently shown AND **not**
  `_cover_fired` AND OBS program scene `== "Stint"` → raise the cover; set
  `_cover_fired = True`, `_cover_auto_owned = True`.
- **Lower** (auto lowers only what auto raised): cover currently shown AND `_cover_auto_owned`
  AND source recovered (`source_state is None`) → lower the cover; set
  `_cover_auto_owned = False`.
- **Re-arm**: when the on-air source is confirmed live again (`source_state is None`), reset
  `_cover_fired = False` so the **next** offline episode can fire.
- **Manual override wins**: a director who manually lowers an auto-raised cover during the
  *same* outage is respected — `_cover_fired` stays `True`, so auto does **not** re-raise; and
  a cover the director raised manually (auto never owned it) is **never** auto-lowered.
- **Visibility-only**: unlike the manual RED FLAG button, auto does **not** write a
  "Red Flag" HUD Race Control banner — an offline source is not a red flag.

### Pure decision function (unit-tested, no I/O)

```python
def auto_cover_action(enabled, source_state, offline_since, now, settle_s,
                      cover_shown, auto_owned, cover_fired,
                      program_scene, on_air_scene="Stint"):
    """Return "raise", "lower", or None for the auto-cover tick. Pure.
    - "lower": auto lowers ONLY a cover it owns, and only once the source recovered.
    - "raise": once per outage, on-air source offline/ended past the settle, cover not
      shown, OBS still on the on-air scene.
    - None: everything else. When disabled, no NEW raise happens (the manual button still
      works), but a cover auto ALREADY owns is still lowered on recovery — so flipping the
      flag off mid-outage never strands an auto-raised cover."""
    if cover_shown and auto_owned and source_state is None:
        return "lower"          # cleanup runs even when disabled — never strand our cover
    if not enabled:
        return None
    if source_state in ("not_live_yet", "ended") and offline_since is not None \
            and (now - offline_since) >= settle_s \
            and not cover_shown and not cover_fired \
            and program_scene == on_air_scene:
        return "raise"
    return None
```

The Relay owns the flags, reads the on-air feed's `source_state`/`offline_since`, reads the
current cover visibility + program scene from OBS **only when it needs to act**, and performs
the `SetSceneItemEnabled` call. The function owns the logic.

**Tick cost (when OBS is actually touched).** Each tick first checks the on-air feed's
`source_state` in memory (free). OBS is queried (cover visibility + current program scene)
**only** when a decision might be pending — i.e. the on-air source is offline past the settle
and `_cover_fired` is not yet set (a possible raise), or auto owns a shown cover and the
source just recovered (a possible lower). Once `_cover_fired` is set the raise guard
short-circuits with no OBS call, so during a steady outage OBS is not polled every 5 s. On a
healthy on-air source every tick is memory-only.

### Configuration

- **`RACECAST_OBS_AUTO_COVER`** — machine `.env`, **default-on**; a falsey token
  (`0/false/no/off`) disables **only the automatic** raise/lower. The manual RED FLAG /
  Companion toggle is unaffected. Matches the house opt-out pattern
  (`RACECAST_OBS_STANDBY_ON_START`, `RACECAST_FEED_ROBUST_AUTO`). Documented in
  `.env.example`.

### On-air feed & handovers

The on-air feed is determined exactly as `_maybe_auto_failover` does it, so the cover follows
the ping-pong across `/next` handovers automatically. Qualifying mode (single feed on A) is
covered by the same on-air lookup.

### UI

- **No new control.** The RED FLAG light already reflects real cover visibility, so it lights
  when auto raises the cover.
- **One warnline** in `src/director/director-panel.html`, reusing the existing `⚠` warnline
  mechanism (like the `auto-dropped to ROBUST` line): shown while auto owns a raised cover —
  `⚠ On-air source offline — Standby Cover auto-raised`. Gives the director the *why*.
- Because a rendered surface changes, regenerate the committed `director-panel.png`
  (wiki-screenshots skill) and do the `ui-visual-verification` pre-flight look in the same
  change.

## Error handling

Every OBS interaction is best-effort, identical to `get_program_screenshot` /
`_maybe_auto_failover`: `_obs_ws is None` or an unreachable OBS logs one note and the tick
continues; nothing raises into the loop. A failed raise/lower simply retries on the next tick
(the flags only advance on a call that was issued — see plan for the exact ordering so a
failed obs call does not falsely mark `_cover_fired`).

## Testing

- `tests/test_pov.py`:
  - `auto_cover_action` truth table — raise / lower / none across the flag combinations,
    the settle boundary (just-under vs just-over `settle_s`), the `program_scene` guard,
    fire-once-per-outage, re-arm on recovery, and manual-override (auto never lowers a
    manually-raised cover; no re-raise after a manual lower within one outage).
  - `Feed.offline_since` transitions: `None → set` on the first classified error, cleared on
    a confirmed-live serve (alongside `source_state`).
  - `auto_cover_enabled(environ)` default-on / opt-out parsing.
- OBS interaction stays best-effort/inspection like the existing failover tests (no live OBS
  in CI).
- Full suite (`tools/run-tests.py`) + `tools/lint.py` + `tools/build.py` before finish.

## Non-goals (YAGNI)

- Generic drops with **no** classified `source_state` (network loss, the #489 **429**
  blackout) — those are auto-failover / #489 territory, not this cover.
- A Splitscreen-scene cover (#378 was Stint-only; the cover source exists only in `Stint`).
- Audio muting (the director uses the existing MUTE buttons; #378 was visual-only).
- A new graphic or a distinct not-live-yet-vs-ended slate (the generic Standby Cover +
  the director's Race Control banner already carry status).
- A configurable fallback *source* path (the #495 stretch item) — deferred; distinct from
  covering the black.

## Files (anticipated)

- `src/relay/racecast-feeds.py` — `auto_cover_action` + `auto_cover_enabled`, constants,
  `Feed.offline_since`, Relay flags + `_auto_cover_loop`/`_maybe_auto_cover`, wiring in the
  feed run loop (set/clear `offline_since` beside `source_state`).
- `src/director/director-panel.html` — the one auto-cover warnline.
- `.env.example` — `RACECAST_OBS_AUTO_COVER` block.
- `tests/test_pov.py` — the pure-logic tests above.
- `src/docs/wiki/images/director-panel.png` (+ slides copy if applicable) — regenerated.
- Possibly `src/docs/wiki/Director.md` — a line on the auto-cover behavior.
