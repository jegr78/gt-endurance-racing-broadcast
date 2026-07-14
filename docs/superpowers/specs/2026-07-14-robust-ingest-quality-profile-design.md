# Robust Ingest — Quality Profiles (#493) — Design

**Date:** 2026-07-14
**Issue:** #493 — Relay: robust ingest mode for unstable / low-bandwidth sources (quality fallback + robust streamlink profile)
**Status:** design approved (pending spec review)

## Problem

A commentator producing from a **PlayStation over WiFi** (a normal, recurring
condition, not an edge case) kept stalling the YouTube live edge during the N24 24h
event. The relay resolves a **single fixed rendition** (`YTDLP_FORMAT = "b[height<=1080]/b"`
→ itag 301 / 1080p60) and serves it; a constrained uplink cannot sustain that variant,
so it stalls, and every re-resolve returns the **same** high rendition — there is **no
mid-stream step-down** to a lower, sustainable quality. The feed degraded into continuous
stall→reconnect cycling and became unwatchable, with no alternative.

The **fix family** is a set of **quality profiles** the broadcast can run a feed at, with
a lower profile trading resolution for a continuous, sustainable picture — plus a matching
robust streamlink profile (more buffered segments) that rides out short jitter.

## Goals

- A feed can run at one of three quality **profiles**; a lower profile pulls a lower
  rendition a constrained uplink can sustain, bundled with a stall-resistant streamlink
  profile.
- The relay **automatically steps a feed down** one notch (FULL → ROBUST) when the source
  is live but repeatedly failing to sustain the high rendition — capped at a **720p floor**,
  never automatically below it.
- An auto-step-down is **actionable and surfaced**: an `@here` Discord ping, a Director
  Panel alert, and an **incident** record (same telemetry class as a drop/churn).
- The **Director** can switch any feed to any profile at any time from the Director Panel
  (and Companion) — including the emergency sub-720p profile, which is **operator-only**.
- **Step-up is manual only** — the director, watching the source recover on their own
  screen, decides when to climb back. No automatic climb (no oscillation).
- Default behaviour preserved: every feed starts at FULL; a stable source is always
  preferred and served at full quality.

## Non-goals

- **No automatic step-up / auto-climb.** Deliberately excluded (oscillation, visible
  re-probe glitches). The human decides recovery.
- **No automatic descent below 720p.** The sub-720p (EMERGENCY) profile is reachable
  **only** by an explicit operator action.
- **No on-air "source degraded" slate.** That presentation layer is #495's scope; this
  issue only emits the notification/incident signal.
- **No fallback/failover to a backup source URL.** Out of scope (#495 stretch / future).
- **No new source-URL input** on any endpoint (no SSRF surface added).

## The quality-profile model

Two per-`Feed` attributes model quality:
- `self.quality_tier ∈ {"full", "robust", "emergency"}` (default `"full"`) selects, at
  resolve time, both the **rendition** and the **streamlink profile**.
- `self.quality_pinned: bool` (default `False`) records whether the director has
  **manually pinned** the tier. The managed **AUTO** state is `tier="full",
  pinned=False`; a manual pin is `pinned=True` at the chosen tier. **Auto-step-down only
  runs while `pinned` is False** — a pin (including a FULL pin) is the director insisting on
  that profile and suppresses the automatic step-down until they release to AUTO (or a
  new-source reset re-arms it).

The tier applies to **both platforms**, via the platform's own quality lever:

| Profile | YouTube (`yt-dlp -f`) | Twitch (streamlink quality) | Streamlink profile |
|---|---|---|---|
| **FULL** (default) | `b[height<=1080]/b` | `best` | `STREAMLINK_SERVE` (64M / live-edge 4), `STREAMLINK_TWITCH` (64M / live-edge 2) |
| **ROBUST** | `b[height<=720]/b` | `720p60,720p` | robust (128M / live-edge 6) |
| **EMERGENCY** | `b[height<=480]/w` | `480p,360p,worst` | robust (128M / live-edge 6) |

- **YouTube** already threads `self.fmt` through `ytdlp_resolve_cmd(url, cookies, fmt)`
  (racecast-feeds.py:2915) and `resolve_hls(..., self.fmt)` (:3810/:5346). The tier maps to
  the `fmt` string; the `/b` (best) and `/w` (worst) fallbacks let yt-dlp pick the nearest
  available rendition when the exact cap is absent.
- **Twitch** takes no yt-dlp hop — the quality is the streamlink **positional** currently
  hardcoded `"best"` at the end of `streamlink_serve_cmd` / `streamlink_fanout_cmd`
  (:2949/:2970). The tier maps to that positional. **ROBUST uses a strict `720p60,720p`
  list** (never a lower entry) so the "never auto below 720p" invariant holds on Twitch
  too; if a broadcaster offers no 720p variant, ROBUST finds no stream and falls through
  to the existing not-playable/retry path — the director then escalates to EMERGENCY or
  FULL manually. EMERGENCY is the explicit low list `480p,360p,worst`.
- **Streamlink profile** is bundled into the tier: FULL keeps the current
  `STREAMLINK_SERVE`/`STREAMLINK_TWITCH`; ROBUST and EMERGENCY use a **robust variant**
  (`--ringbuffer-size 128M`, `--hls-live-edge 6` for YouTube; a matching robust Twitch
  variant) — more buffered segments to ride out short source jitter, trading latency for
  stability.

Pure helpers (unit-tested, no I/O):
- `quality_ytdlp_fmt(tier) -> str` — tier → yt-dlp format string.
- `quality_twitch_selector(tier) -> str` — tier → Twitch quality positional.
- `streamlink_serve_flags(tier) -> list[str]` / `streamlink_twitch_flags(tier) -> list[str]`
  — tier → the ringbuffer/live-edge flag list. `streamlink_serve_cmd` /
  `streamlink_fanout_cmd` take a `tier` (default `"full"`) and call these instead of the
  hardcoded constants + `"best"`.

## FULL respects the source's current maximum

FULL is **not** "force 1080p" — it is "**best available up to 1080p**". A source that only
offers 720p (a common PS4/console direct-stream ceiling) resolves to 720p on FULL, with no
error: `b[height<=1080]/b` lets yt-dlp pick the nearest available rendition, and Twitch
`best` is by definition the source's top rendition. So **AUTO/FULL always means "max 1080p,
bounded by the source's current maximum"** — exactly the desired behaviour.

The gap is **visibility**: the director must be able to tell that a feed sits at 720p
because the *source* caps there, not because someone pinned ROBUST — otherwise they will
switch to FULL expecting 1080p and get 720p with no explanation.

- The served resolution is already tracked (`self.quality`, e.g. `"720p60"`) and already
  exposed per feed in `/status` (:5210/:7387). The Director Panel shows the **profile**
  (FULL/ROBUST/EMERGENCY) **and** the **served resolution** side by side, so a FULL feed
  serving 720p (source-limited) is visibly distinct from a ROBUST 720p (we-capped).
- **Source-max hint (inference, no extra probe):** while a feed is at **FULL** and the
  served height is **< 1080**, the source demonstrably offers no higher rendition (FULL
  would have taken it) — so the panel shows a hint: *"source max 720p — no 1080p
  available"*. This is the "the source doesn't support 1080p" signal the director needs; it
  is continuously visible, so it also covers the "don't bother switching up" case.
- At **ROBUST/EMERGENCY** the source's maximum *above the cap* is unknown (we capped below
  it). Switching to FULL is always safe — FULL never yields *less* than a lower profile's
  rendition — and it immediately reveals the true max, which the hint then reports. So
  there is no "worse outcome" to warn against before a switch; FULL is the reveal.

Pure helper: `quality_height(token) -> int | None` — `"720p60"` → 720, `"1080p"` → 1080,
`"best"`/`"audio_only"`/`None` → None. The panel composes the hint from `profile == full`
and `quality_height(served) < 1080`; the backend keeps emitting facts (profile + served
quality), not a pre-baked sentence.

## Automatic step-down (FULL → ROBUST only)

**Trigger.** Reuse the existing `dead_serves` signal, which already counts
**connect-then-stall short serves**: a serve exiting before `HEALTH_SERVED_OK_S` (10 s)
increments it (:5433–5435); a stable serve / new source / operator reload reset it
(:5413/:5223/:5230). A genuinely offline/ended source fails at the **resolve** step
(:5350) and takes the separate `source_state` path (`classify_source_state`, #495) —
it does **not** increment `dead_serves`. So `dead_serves` inherently targets the
live-but-degraded case.

- Pure decision helper `quality_step_down_due(tier, pinned, dead_serves, source_state, *, threshold=2) -> bool`:
  `return (not pinned) and tier == "full" and source_state is None and dead_serves >= threshold`.
  - Only while **not pinned** (a manual pin suppresses auto).
  - Only from FULL (never ROBUST → EMERGENCY automatically; 720p is the hard floor).
  - `source_state is None` gate (belt-and-suspenders): don't step down an
    offline/not-live-yet/ended source — a lower rendition cannot help a source with no
    picture at any quality.
- On a `True` decision the feed sets `self.quality_tier = "robust"` (leaving `pinned`
  False — an auto-managed drop, still auto-managed), triggers a re-resolve
  (`self.reload()` → `advance.set()` + kill), and fires the notification/incident path
  below **once** per step-down event.
- **Kill-switch:** `RACECAST_FEED_ROBUST_AUTO` (default `1`; `=0` disables only the
  automatic step-down — manual switching always remains available). Parsed with the
  established `_FANOUT_FALSEY` convention.
- No other threshold knobs shipped (KISS); `threshold` is a constant
  (`ROBUST_STEP_DOWN_AFTER = 2`) exposed to the helper for testability.

## Manual switching (the primary control)

The Director watches the wobbly feed on their own screen (existing Director Panel
preview / program monitor) and switches the broadcast profile deliberately.

- **Endpoint:** `POST /feed/<A|B>/quality` with body/param `tier ∈ {full, robust, emergency, auto}`.
  - `full|robust|emergency` set `quality_tier` and `quality_pinned=True` (a manual pin
    that suppresses auto-step-down); `emergency` is the **only** path below 720p.
  - `auto` releases the pin to the managed state (`quality_tier="full"`,
    `quality_pinned=False`, auto-step-down re-armed for this stint).
- **Effect:** set the tier/pin, then re-resolve via the existing `reload` path
  (relay `reload(which)` :6387 / `Feed.reload` :5227). This causes a brief reconnect
  (~seconds — a new manifest/quality) then serves at the new profile. The glitch is an
  intended director action, not a fault.
- **Authorization:** director-gated via `console_policy.decide(...)`, Funnel-safe under the
  existing `/console` mount (same pattern as the `/obs/*` and `/pov/*` controls); a new
  capability mapping for the `/feed/<A|B>/quality` path in `console_policy`. No new public
  surface, no OBS-WS exposure. The path carries **no URL** — only a feed id and an enum
  tier — so no SSRF/allow-list concern.
- **Companion:** per-feed profile buttons (FULL / ROBUST / EMERGENCY / AUTO) added to the
  exported config.

Pure helper: `parse_quality_tier(value) -> str | None` — validates/normalises the enum
(rejects anything else), so the endpoint can 400 an invalid tier.

## Persistence — reset at a new source

A selected tier (auto-dropped **or** manually pinned) is **not** carried across a
handover to a **new distinct source**:

- On a new source / stint index change (the `set_index` / new-source path :5215/:5223,
  which already resets `dead_serves`), reset to the managed state
  (`self.quality_tier = "full"`, `self.quality_pinned = False`). Every new commentator
  starts at full quality, auto-managed, and earns a fresh auto-step-down if their source is
  also constrained — a previous manual pin does **not** leak onto the next source.
- A commentator holding the **same URL** across consecutive stints is a **continuation**
  (no re-resolve, #491 single-pull) — there is no new-source event, so the tier naturally
  persists for that run. This is the desired behaviour: the same struggling source keeps
  its lower profile; a genuinely new source does not inherit it.

Pure boundary is the existing new-source detection; the reset is a one-line assignment on
that path.

## Notification & incident classification

An **auto**-step-down means the source needs attention and the director must decide the
manual step-up — so it is treated as actionable, not a silent transient:

- **`on_step_down` callback** on `Feed` (relay-set, mirroring `on_recovery` :5165/:5361):
  `callback(feed_name, stint, from_tier, to_tier, source_state)`. Best-effort, wrapped so a
  telemetry failure never breaks the run loop.
- The relay wires it to:
  1. **Discord `@here` ping** — a new `discord_step_down_payload(feed, stint, from_tier, to_tier, event_title, producer)`
     modelled on `discord_failover_payload` (:638) with the top-level `@here` mention
     (:4127 pattern). *Distinct from* the churn `@here`: this is a quality-reduction
     incident, not an outage, but it is `@here` because it is actionable.
  2. **Director Panel alert** — surfaced in the panel status the same way drop/churn
     alerts are, so the on-shift director sees "Feed A → ROBUST (source struggling)".
  3. **Incident record** — recorded in the health history + post-event report incident
     stream, the same class as drop/churn/recovery, so the report reflects that a feed ran
     degraded and when.
- A **manual** switch is **not** an incident and does **not** ping (it is a deliberate
  operator action); it is logged at INFO for the audit trail.

The existing `@here` **churn dampening** (`churn_at_here_suppressed`, #495) is unaffected;
a per-stint step-down ping is informative-but-bounded (at most one per source that
degrades), distinct from rapid churn.

## Front-end surfaces (and required screenshot refreshes)

- **Director Panel** (`src/director/*.html`) gains a per-feed profile control (FULL /
  ROBUST / EMERGENCY / AUTO) with the current profile as a badge and EMERGENCY styled as a
  loud/notfall state; the **served resolution** next to the profile; the **source-max hint**
  when FULL is serving < 1080p; and the auto-step-down alert. **Per the CLAUDE.md hard rule,
  the committed `src/docs/wiki/images/director-panel.png` MUST be regenerated and committed
  in the same change** (wiki-screenshots skill), and the change must pass the
  ui-visual-verification pre-flight look.
- **Companion** buttons (`src/companion/…`) — regenerate the committed
  `companion-page*-*.png` via the companion-screenshots skill in the same change.

## Code touch points

- `src/relay/racecast-feeds.py`:
  - constants: `YTDLP_FORMAT`/`YTDLP_FORMAT_POV` (:133/:134), `STREAMLINK_SERVE` (:135),
    `STREAMLINK_TWITCH` (:186) → add ROBUST variants + the tier→flags helpers.
  - `ytdlp_resolve_cmd` (:2915), `streamlink_serve_cmd`/`streamlink_fanout_cmd`
    (:2926/:2952) → thread a `tier`.
  - `Feed`: `self.quality_tier` (init default `"full"`), `self.on_step_down`; run-loop
    resolve at :5346 uses the tier; step-down decision after the `dead_serves += 1`
    at :5435; tier reset on the new-source path :5215/:5223.
  - `Relay`: `on_step_down` wiring → Discord/report/health; `reload`/`set_index`
    (:6387/:6284) already give the re-resolve mechanism for the manual switch;
    `discord_step_down_payload`; `/feed/<A|B>/quality` route in `do_POST` (:7967) gated by
    `console_policy`.
- `src/scripts/console_policy.py` — path→capability mapping for `/feed/<A|B>/quality`
  (director capability).
- `src/scripts/health_store.py` / the report path — incident record for a step-down.
- `src/director/*.html` — the profile control + alert.
- `src/companion/…` + `export companion` — the buttons.
- `.env.example` — `RACECAST_FEED_ROBUST_AUTO`.
- `tools/fanout-soak.py` — extend to exercise a jittery/low-bandwidth source and a manual
  tier switch (the "documented soak test" AC).

## Testing

Pure helpers (stdlib test files, the repo convention):
- `quality_ytdlp_fmt` / `quality_twitch_selector` / `streamlink_serve_flags` /
  `streamlink_twitch_flags` — tier → correct string/flags, both platforms, all three tiers.
- `quality_step_down_due` — fires only when `not pinned` + FULL + `source_state is None` +
  `dead_serves ≥ 2`; never when pinned; never from ROBUST/EMERGENCY; never when
  `source_state` is set (offline/ended).
- `parse_quality_tier` — accepts the four enums, rejects junk.
- `quality_height` — `"720p60"` → 720, `"1080p"` → 1080, `"best"`/`"audio_only"`/`None`
  → None (drives the source-max hint).
- new-source tier reset (the boundary predicate).
- `discord_step_down_payload` — carries `@here` + the from/to tiers.
- endpoint routing + `console_policy` director-gating for `/feed/<A|B>/quality`.

Soak (`tools/fanout-soak.py`, maintainer, not CI): a manual switch to ROBUST — and an
auto-step-down under a simulated jittery source — hold a continuous 720p picture instead of
stall→reconnect cycling.

## Config summary

- `RACECAST_FEED_ROBUST_AUTO` (default `1`) — enable auto-step-down; `=0` = manual-only.
- Constants (no env): `ROBUST_STEP_DOWN_AFTER = 2`, the robust ringbuffer/live-edge values,
  the per-tier fmt/quality strings.

## Assumptions / open items

- **Twitch ROBUST = strict `720p60,720p`.** If a broadcaster offers no 720p rendition,
  ROBUST yields no stream and the director escalates manually — accepted, to keep the
  "never auto below 720p" invariant honest on Twitch. (Assumption: broadcasters we relay
  generally offer a 720p transcode; confirm operationally.)
- The Director Panel preview is assumed sufficient for the director to judge a source's
  stability before/while switching. If a gap surfaces (e.g. the director cannot preview a
  specific off-air feed at will), that is a follow-up, not part of this slice.
- Step-down pings once per degrading source per stint; if a chronically bad source spans
  many short stints and this proves noisy, dampening is a follow-up (the #495 churn
  dampener is the precedent).
