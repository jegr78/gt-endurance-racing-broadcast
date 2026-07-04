# OBS scene-collection auto-switch on `event start`

**Date:** 2026-07-04
**Status:** Design approved — ready for implementation planning

## Problem

The GCP remote-producer box hosts several leagues as `profiles/<name>/`, and each
league has its own OBS scene collection (`GT Endurance Racing — <league>`). OBS keeps
whatever collection was last active. So after producing league A and later starting an
event for league B on the same box, OBS most likely still has **A's** collection loaded
— the wrong sources, the wrong overlay geometry — and nothing forces it to B's before
the stream goes live.

racecast already knows the correct collection per profile and can switch it over
obs-websocket (`racecast obs collection set`), but today `racecast event start` only
**warns** on a mismatch — it never switches. In an unattended/remote bring-up nobody
reads that terminal warning, so the wrong collection silently stays up.

## Goal

At `event start` (and, by inheritance, `event takeover`), automatically switch OBS to
the active profile's scene collection when a different one is loaded. Default-on, with
an env kill-switch that restores today's warn-only behaviour. Keep the existing explicit
manual switch (CLI + Control Center) as the fallback when the auto-switch can't act.

## Why this is safe to automate now

The one reason the switch was kept manual is that `SetCurrentSceneCollection` is
heavyweight — it tears down and rebuilds **all** sources (including the relay feeds), so
doing it mid-broadcast would briefly drop the program. Two facts remove that risk at
`event start`:

1. **OBS refuses a collection switch while an output is active.** `set_scene_collection`
   already surfaces this: the request raises on the failed `requestStatus`, is caught,
   and returns `(False, <obs error>)`. A live stream can therefore never be interrupted
   by the auto-switch — OBS itself blocks it.
2. **At `event start` no output is active yet.** The switch lands during bring-up,
   before anyone is producing, so the source rebuild is free.

Everything stays **best-effort**: OBS unreachable, collection not imported, a renamed
variant (`GT Endurance Racing 2`) → no switch, only a warning; bring-up is never
blocked.

## Design

### 1. Pure decision function (`src/scripts/obs_ws.py`)

Add `scene_collection_action(status, note, switch_enabled)` next to the existing pure
`scene_collection_status`. It performs **no I/O** — it classifies the already-fetched
status into an intent the executor carries out:

| Situation                                             | Return              |
|-------------------------------------------------------|---------------------|
| OBS unreachable / no status (`status is None`)        | `("skip", note)`    |
| already correct (`status["match"]`)                   | `("ok", current)`   |
| mismatch, expected collection present, switch enabled | `("switch", expected)` |
| mismatch, expected present, switch **disabled** (ENV=0)| `("warn_present", status)` |
| mismatch, expected collection **not imported**        | `("warn_absent", status)` |

Note: a renamed-only variant (`expected_present` false but a `renamed_variant` exists)
falls into `warn_absent`/its own warn text — we **never** auto-switch to a renamed
variant, matching the existing `scene_collection_status` contract. `set_scene_collection`
is only ever called with the exact expected name, and independently refuses if that name
isn't in OBS's list.

Unit-tested in `tests/test_obsws.py` across all five branches × enabled/disabled.

### 2. Executor + kill-switch (`src/racecast.py`)

`_check_scene_collection()` changes from *warn-only* to *switch-or-warn*:

```
status, note = obs_ws.get_scene_collection(expected=_active_obs_collection())
action, detail = obs_ws.scene_collection_action(status, note,
                                                 _collection_switch_enabled())
# skip        -> "obs: scene collection check skipped — <note>."
# ok          -> "obs: scene collection '<current>' active — correct."
# switch      -> obs_ws.set_scene_collection(name=detail):
#                  ok  -> "obs: scene collection switched to '<expected>' (was '<current>')."
#                  fail-> WARNING, could not switch — <note>; point to `racecast obs
#                         collection set` / the Control Center OBS row.
# warn_present -> today's exact warn text (unchanged wording)
# warn_absent  -> today's exact "import with `racecast setup`" warn text (unchanged)
```

The `warn_present` / `warn_absent` branches reuse the **current** messages verbatim, so
the disabled-path and not-imported-path output is unchanged from today.

New helper `_collection_switch_enabled()` mirrors the existing feed-fanout convention
(`racecast.py:2198`):

```
_machine_env_value("RACECAST_OBS_COLLECTION_SWITCH").strip().lower() \
    not in {"0", "false", "no", "off"}
```

Absent/empty → enabled (default-on); `0/false/no/off` → warn-only.

### 3. Ordering in `event_start`

A switch rebuilds all sources, so it must run **before** the page-refresh + POV-transform
sync, not after. Today `_check_scene_collection()` sits one line *after*
`_refresh_obs_pages()` (`racecast.py:3221-3222`). Swap them: run the
scene-collection ensure first, then `_refresh_obs_pages()`, so the refresh and the POV
transform land on the **switched-to** collection instead of being overwritten by the
switch.

Placement stays after the "wait for services up" loop (OBS confirmed running — a switch
needs a live obs-websocket).

Known minor: the source rebuild after a switch is asynchronous, so the immediately
following `_refresh_obs_pages()` / POV sync may race it. Both are best-effort and
hash-gated, and browser sources reload themselves on collection load, so no artificial
`sleep` is added up front; a short settle can be introduced later if UAT shows a race.

### 4. Takeover inherits it automatically

`event_takeover` calls `event_start` internally, so the auto-switch flows through the
remote-producer-B path with no extra code. The ENV kill-switch is machine-level, so it
applies uniformly to both.

### 5. Manual fallback — unchanged, on both surfaces

The explicit switch already exists and is **kept as-is**; nothing new is built here:

- **CLI:** `racecast obs collection set` (`racecast.py:2263`).
- **Control Center:** the OBS-view row already renders a **"Switch to `<expected>`"**
  button on a mismatch, wired to the same `obs-collection-set` op
  (`control-center.html:2200-2203`), with the renamed-variant / not-imported warnings.

These stay the deliberate, explicit fallback for when the auto-switch can't act (OBS was
down at bring-up, collection not yet imported, or the operator turned the ENV switch
off). The auto-switch's failure warning routes the operator to exactly these.

Out of scope (unchanged, read-only report surfaces): the `racecast event status`
scene-collection line and the Control-Center Apps status text remain report/warn — they
do not auto-switch.

## Tests

- `tests/test_obsws.py`: `scene_collection_action` — all five branches, enabled and
  disabled; assert the disabled+mismatch case returns `warn_present` (never `switch`).
- `tests/test_obsws.py` or `tests/test_racecast.py`: `_collection_switch_enabled` env
  parse — default-on, and each of `0/false/no/off/1/true` (mirror the existing bool-parse
  tests).
- The existing `get_scene_collection` / `set_scene_collection` tests already cover the
  I/O layer (already-on / not-found / OBS-rejects / unreachable) and are unchanged.

## Docs

- **CLAUDE.md** — correct the OBS-collection paragraph: the "Switching is always an
  explicit producer action … never automatic" line is no longer wholly true. State that
  `event start` auto-switches by default (`RACECAST_OBS_COLLECTION_SWITCH=0` to disable),
  safe because OBS refuses a switch while an output is active; the manual `obs collection
  set` / Control-Center button remain the explicit fallback.
- **.env.example** — document `RACECAST_OBS_COLLECTION_SWITCH` (commented, default-on,
  `=0` to keep the old warn-only behaviour), alongside the other opt-out flags.
- **Remote-producer wiki guide (#395)** — one line: switching profiles between events on
  the box auto-aligns OBS's scene collection at `event start`.

No rendered UI surface changes (event-start output is CLI / Control-Center job log), so
no wiki screenshot regeneration is required.

## Alternatives considered

- **Inline switch inside `_check_scene_collection` without a pure function** — worse
  testability; rejected in favour of the pure `scene_collection_action` + thin executor
  pattern already used by `scene_collection_status`.
- **Auto-switch as a separate earlier step (before the OBS-up wait)** — OBS may not yet
  accept the websocket call, more race surface; rejected. The switch runs after OBS is
  confirmed up.
- **A `--no-collection-switch` CLI flag instead of / in addition to the ENV** — rejected
  as inconsistent with the repo's `RACECAST_FEED_FANOUT` / `RACECAST_PROGRAM_AUDIO`
  env-kill-switch convention and would need threading through the takeover path; the ENV
  applies uniformly.
