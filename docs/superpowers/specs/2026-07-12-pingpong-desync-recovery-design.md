# Ping-pong / cockpit desync detection + recovery (#494)

**Date:** 2026-07-12
**Issue:** [#494](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/494)
**Depends on / follows:** #491 (merged, `89a37d9a`) prevents the same-URL double-pull
that *caused* the N24 desync. This is the **recovery** layer for a desync from **any**
cause.
**Scope:** `src/relay/racecast-feeds.py` (predicate + state + recovery primitive),
`src/director/director-panel.html` (banner + one-click Resync), `src/cockpit/cockpit.html`
(graceful "syncing…"). Single PR into `main`.

## Problem

The on-air feed is derived purely from feed indices — `live_feed()` = the lower-index
feed. If the index-designated on-air feed **drops** while the other feed is the one
actually delivering a picture, `live_feed()` (and everything derived from it: the HUD
stint label, the Commentator Cockpit ON-AIR/UP-NEXT/stint-plan, `/status`) points at the
wrong/dead feed with **no detection and no recovery short of manual sheet surgery**. The
Cockpit and `/next` read the same index-derived state, so one desync poisons both. During
the N24 24h event (post the #491 hiccup) the cockpit's ON AIR went out-of-sync and stayed
wrong.

## Design

Three parts — **detect**, **degrade gracefully**, **recover** — plus one deliberate
non-goal: the heartbeat never mutates feeds/OBS on its own (no surprise black frame,
consistent with the #488 stance).

### 1. Pure detection predicate

```python
def ping_pong_desynced(live_serving, off_serving):
    """True when the index-designated on-air feed is NOT delivering a stable
    picture while the OFF-air feed IS — the feed on screen and the feed derived as
    on-air disagree. Pure; the caller supplies each feed's 'serving a stable
    picture' boolean and applies the settle debounce. Returns False whenever the
    on-air feed is fine, or when the off-air feed is not itself delivering (a plain
    on-air drop with nothing better to show is a health condition, not a desync)."""
    return (not live_serving) and off_serving
```

A feed "serving a stable picture" = `f.is_serving() and not f.dropped and not f.paused`.
The relay computes `live_serving`/`off_serving` from `live_feed()` and the other feed.

### 2. Heartbeat detects → surfaces (never mutates)

`Relay` gains a small desync state block, recomputed each `_heartbeat_loop` tick (and on
the `/status` 2 s refresh):

- The raw predicate is evaluated, then **debounced**: the flag is set only after the
  desynced condition persists for **`HEALTH_CONNECTING_SETTLE_S` (15 s)** — the existing
  constant, below the red grace — so a quick reconnect blip never raises it (alarm-fatigue
  guard, per the #495 concern). It clears immediately when the condition ends.
- On the false→true and true→false transitions, one `LOG.info`/`LOG.warning` line.
- Exposed as its **own field** in `/status` — **not** folded into `health_level`
  (deliberate: no Discord `@here`, no distortion of the health-history DB semantics; this
  is a panel-local operator condition):
  ```json
  "desync": {"active": true, "since_s": 22.4,
             "serving_feed": "B", "suggested_stint": 9}
  ```
  `serving_feed` = the feed actually delivering; `suggested_stint` = the 1-based stint
  that feed is on (the pre-fill for the Resync button). When not desynced:
  `{"active": false}`.

### 3. Graceful degrade (display only)

While the flag is active:

- **Director Panel** (`director-panel.html`, polls `/status`): a persistent **red banner**
  `PING-PONG DESYNC — Resync to stint N` via the existing `setBanner`/`clearBanner` system
  (id `"desync"`), extended so this one banner carries a **one-click Resync button**
  pre-filled with `suggested_stint`. The button calls the recovery endpoint (below). The
  banner renderer gains optional-action support; other banners are unchanged.
- **Cockpit / HUD** (`cockpit.html`): `cockpit_tally` / `cockpit_schedule` gain a
  `desynced` parameter; when true they return a **"syncing…"** marker instead of the
  (index-derived, possibly wrong) ON-AIR data, and the front-end renders "syncing…" rather
  than a confident-but-wrong streamer. The `/cockpit/data` builder passes
  `relay`'s desync flag. Self-heals to real data once reconciled.

`live_feed()` itself is **unchanged** — it stays the pure index invariant that drives the
handover logic (`live_after_next`/`next_auto`); making it "prefer the serving feed" would
risk flipping a handover target on a transient drop. The desync flag is the separate,
display-only signal.

### 4. Recovery primitive — feed-agnostic `resync_to_stint(N)`

`set_stint(N)` is **A-centric** (always parks Feed A on the on-air slot head, Feed B on
the next slot). In valid slot-parity operation the on-air feed alternates A/B, so a
`set_stint(9)` while stint 9 legitimately runs on **Feed B** would re-point B off its own
stream — cutting the live feed. So recovery uses a new, feed-agnostic method; `set_stint`
stays as the pre-live takeover primitive (A-centric is fine there — nothing is serving).

```python
def resync_to_stint(self, stint):
    """Reconcile 'stint <N> is on air NOW' onto whichever feed is ACTUALLY serving
    it, preserving the live picture. Feed-agnostic (unlike set_stint):
      - find the feed whose current URL == stint N's row URL (the serving anchor)
      - if found (via _feed_serving: phase==serving, not dropped/paused): keep it on
        air, set on_air_row = N-1, move the OTHER feed to the next distinct slot after
        max(N-1, anchor.idx) (the #491-safe dedupe placement, keeping the anchor the
        lower index so live_feed names it), reflect OBS visibility to the anchor.
        Non-destructive: the anchor feed is never re-indexed; Feed.set_index no-ops
        (no kill) when the other feed is already at its target.
      - if NO feed serves N: this is a takeover, not a resync -> return an error and
        mutate nothing. A director-tier /resync must NEVER perform the producer+step-up
        gated cut; the operator uses /set/stint (producer+step-up) for a real takeover."""
```

Non-destructiveness falls out of the existing `Feed.set_index` early-return: it kills the
pull only when the target index actually changes. So when reality already matches, nothing
is cut.

**Endpoint:** `GET /resync/stint/<n>` (director-gated like `/set/stint/<n>`) → wraps
`resync_to_stint`; the panel banner button and a manual control both hit it. Mode-aware
via `self.source` like the other stint paths. The HUD auto-write (`_push_live_schedule`)
runs after, same as `/set/stint`.

### 5. Tests

- Pure `ping_pong_desynced`: on-air down + off serving → True; both serving → False;
  on-air serving (off idle) → False; both idle/paused → False.
- `resync_to_stint`: (a) stint N served by **Feed B** → B stays on air, A moves to next
  slot, no B cut (B's pull index/proc untouched), `on_air_row`/`live_feed` consistent;
  (b) stint N served by Feed A → symmetric; (c) N served by **no** feed → falls back to
  `set_stint` (re-point). Assert the already-correct feed's `set_index` returned no kill.
- Desync state + debounce: flag stays false before the 15 s settle, true after, clears on
  recovery; `/status` carries the `desync` block with `serving_feed`/`suggested_stint`.
- Cockpit degrade: `cockpit_tally`/`cockpit_schedule` with `desynced=True` → "syncing…"
  marker, not the wrong ON-AIR row.

Relay/predicate tests in `tests/test_pov.py`; cockpit-tally degrade where the existing
tally tests live (`tests/test_cockpit.py`); the `/status` desync field + endpoint in
`tests/test_racecast.py`/`tests/test_ui_server.py` as fits the existing route tests.

### 6. Visual-surface obligation (CLAUDE.md)

The desync **banner** (Director Panel) and the cockpit **"syncing…"** state are visible
changes to the **Director Panel** and **Crew Console**. Their wiki screenshots
(`src/docs/wiki/images/director-panel.png` and the cockpit image) must be refreshed **in
this change** — which requires forcing a desync state in a local dev build (the `demo`
profile + `tools/obs-sim.py` recipe, via the `wiki-screenshots` skill) so the banner/
"syncing…" are visible in the shot. A dedicated plan task with the UI-visual-verify gate.

## Explicitly out of scope

- Auto-recovery that mutates feeds/OBS from the heartbeat (rejected — no surprise cut).
- Changing `live_feed()`'s control semantics.
- The POV feed's exclusion from the A/B single-pull invariant (a #491 follow-up, unrelated
  to desync).

## Acceptance criteria (from #494)

- [ ] A single "Resync to stint N" action reconciles feed indices + on_air_row + OBS so
      `/next` and the cockpit are both correct afterwards.
- [ ] The resync has a non-destructive path that does not cut an on-air feed already
      serving the target stint — including when that feed is **Feed B**.
- [ ] The heartbeat detects an inconsistent ping-pong state (after the settle) and raises a
      clear operator signal (panel banner + log); it never silently serves wrong ON-AIR
      data and never mutates feeds/OBS on its own.
- [x] The cockpit degrades to "syncing…" instead of wrong data and recovers on reconcile;
      `live_feed()` is unchanged. (Both the big tally AND the stint-plan card's ON-AIR marker
      are gated on `d.syncing`.)
- [x] Unit tests for the desync predicate and the feed-agnostic non-destructive resync.
- [~] `director-panel.png` + cockpit wiki screenshots — **intentionally deferred.** The banner
      and "syncing…" are transient, conditional error states; the panels' DEFAULT documented
      appearance is unchanged, so the canonical shots are not stale. The changed components were
      instead visually verified per-surface (headless render + eyeball, recorded in
      `runtime/ui-visual-verified.json`). Regenerating the wiki images to force an error state
      would make them less representative of normal operation.
