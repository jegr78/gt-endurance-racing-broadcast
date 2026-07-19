# Feed fan-out trailing-cursor prebuffer — design

**Issue:** #533. Builds on the fan-out hub
(`docs/superpowers/specs/2026-06-28-relay-feed-fanout-design.md`).

**Status:** design approved, ready for an implementation plan.

**Source:** Suzuka 8h post-event analysis (2026-07-18). Top-priority resilience
item — direct impact on viewer stream quality.

## Problem

Throughout the Suzuka 8h event the on-air feed hitched — a brief **video freeze**
while **audio mostly stayed smooth** — worst on the two 720p stints (2 & 4, same
commentator source), including a 2.2 s outlier and an ~85 s storm of ~0.5 s hits
near the end of stint 4. The objective fingerprint in the OBS log is:

```
Source Feed X audio is lagging (over by N ms) at max audio buffering. Restarting source audio.
```

28 such events (a **lower bound** — only hitches long enough to break A/V sync
log; pure video hitches, where audio plays on from OBS's buffer, do not). The
post-event report and health monitor rated the event **0 incidents / 959-of-959
on-air samples green** — the whole detection stack is blind to this stall class
(tracked separately in #535).

### Root cause (traced to the line)

It is **not** ring overflow. `FANOUT_RING_BYTES = 16 MB` is ≈ 12 s at 10 Mbps,
but the real commentator feeds ran **~0.5–0.8 Mbps** (low-bitrate, bursty; btop
caught a 55 Mbps momentary burst against a ~0.7 Mbps average). At that rate 16 MB
holds ~150 s, so the consumer never falls behind the retained window and the
`#488` cursor-snap never fires.

The stall is **underflow / starvation**. In `FeedFanoutServer` the OBS consumer
joins at the live edge:

```python
cursor = self.ring.live_offset()    # join at the live edge
```

with **zero prebuffer**. `FeedRing.read` returns `b""` the instant the consumer's
cursor catches the write head. A bursty source delivers in schübe with short
gaps; between bursts the ring stops growing, OBS's cursor reaches the live edge,
`read` returns empty, the fan-out HTTP body stalls, OBS's media-source audio
buffer (capped ~960 ms) drains, and OBS restarts source audio → the visible video
stutter. The ~2 min splitscreen overlaps were short, so this is **not** the #489
multi-feed 429 class — it is single-feed inbound jitter.

This event ran entirely on the home Mac (M3, WiFi) with relay + OBS co-located;
CPU (~24 % avg), memory (~70 %) and the outbound broadcast (0.1 % dropped, ~10
Mbps) were all healthy. The problem is purely on the **input** side: bursty
low-bitrate source arrival + WiFi jitter on the pull, with no smoothing between
the ring and OBS.

## Approach: a trailing read cursor (approach A)

The smoothing data **already exists in the ring** (~150 s retained at these
bitrates). We are only choosing *where* OBS reads from: instead of the live edge,
OBS joins **N seconds behind** it. The reserve then lives in the existing ring,
*between* OBS's cursor and the live write head.

```
   ring:  [ base .......... OBS cursor ==N seconds== live_offset ]  <- streamlink writes here
                              │<------- reserve ------->│
                              └─ OBS reads here (~1x playout)
```

Because OBS reads at ~1× playout (its media source caps buffering at ~960 ms, so
it cannot greedily drain ahead), **TCP back-pressure holds the N-second gap
stable**: the live edge advances at the source's average rate (~1× for a live
stream) and OBS's cursor advances at playout (~1×), so the gap oscillates around
N. When the source stalls for up to N seconds, OBS keeps reading the
already-buffered bytes ahead of its cursor and **never starves**; when the source
resumes with a burst, the gap is restored.

### Why this does not reintroduce the ~2 s stale-frame glitch

The fan-out spec deliberately joined at the live edge to kill a *growing* backlog:
OBS held an idle connection while off-air, bytes backed up, and on activation OBS
drained that variable backlog as stale video. This design is different: a
**fixed, bounded** trailing offset is constant added latency, not a growing
backlog. With `close_when_inactive=True` (the fan-out default) OBS drops its
connection off-air and **reconnects fresh** on activation, rejoining at
`trailing_offset` — so it shows content from a constant N seconds ago, never a
variable catch-up.

### Latency budget

The trailing offset adds N seconds of **input-side** latency (commentator stream →
OBS). Chosen budget: **~3 s default** (covers the observed 0.1–2.2 s gaps incl.
the 2.2 s outlier with ~0.8 s margin). This is independent of and stacks with the
**output-side** YouTube "stream latency" setting (Normal/Low/Ultra-low, OBS →
viewer); switching Low → Ultra-low frees far more than 3 s, so total glass-to-glass
latency can end up *lower* than today while the picture is smoother. The YouTube
setting is OBS/YouTube config, not relay code — see #538.

## Components

### 1. `FeedRing` time index (pure, unit-tested)

`FeedRing` gains a bounded, throttled time index so "N seconds ago" maps to an
absolute offset independent of bitrate:

- On `write()`, append a mark `(live_offset_after_write, monotonic_ts)` — throttled
  to **at most one mark per ~100 ms** to bound the deque. Prune marks whose offset
  `<= self._base` (they have scrolled out of the retained window). `time.monotonic()`
  is used (relay runtime; no wall-clock dependency).
- `offset_at_age(age_s, now)` → the offset that was the live edge ~`age_s` ago, i.e.
  the newest mark whose `ts <= now - age_s` (rounding toward *more* reserve, never
  less), clamped to `[start_offset, live_offset]`; if no mark is that old (cold/short
  ring) it clamps to `start_offset()` (serve whatever is retained, the prebuffer fills
  over the next N seconds). Pure.
- `trailing_offset(prebuffer_s, now)` = `offset_at_age(prebuffer_s, now)` clamped to
  `[start_offset, live_offset]`. `prebuffer_s <= 0` → `live_offset()` (today's
  behaviour, the clean revert).

The writer still never blocks; `read` / overflow / cursor-snap semantics are
unchanged. Ring capacity stays **16 MB** — it holds 3–4 s at any realistic bitrate
and still leaves ~8 s of overflow headroom above the trailing cursor at 10 Mbps
(revisit only if genuinely high-bitrate feeds appear).

### 2. `FeedFanoutServer` join change

The OBS consumer's initial cursor changes from `self.ring.live_offset()` to
`self.ring.trailing_offset(prebuffer_s, now)`. The rest of the serve loop
(`read(cursor, timeout)` → `wfile.write(data)`, cursor-snap accounting) is
unchanged. `prebuffer_s` is passed in from config at consumer construction.

**Per-consumer policy:**

- **OBS** (the broadcast) → trailing.
- **Program-audio monitor** (`ProgramAudioService`, on-air feed tap) → **trailing**,
  the same offset as OBS, so the crew monitor stays in sync with what viewers see.
- **Director-Panel preview** → **live edge** (freshest monitoring; a small A/V
  offset vs. broadcast is acceptable for a preview).

### 3. Config

- `RACECAST_FEED_PREBUFFER_S` — machine `.env` (a transport knob, like
  `RACECAST_FEED_FANOUT`), documented in `.env.example`. **Default 3.0 s.**
- Parsed with the existing config helpers: non-numeric / negative → default; `0` →
  disabled (live-edge join = today's behaviour). Only takes effect under fan-out
  (already default-on); no separate on/off flag.
- Default-on is a deliberate behaviour change, called out in `.env.example` and the
  fan-out spec cross-reference.

### 4. Interactions (verified in design)

- **#488 auto-reconnect / rebuild** (`should_obs_reconnect` on overflow,
  `should_rebuild_on_air` on render-skip): unchanged. A reconnect rejoins at the
  trailing cursor and regains the reserve — strictly better.
- **8 s byte-stall watchdog:** unchanged. It measures streamlink→relay byte flow,
  not OBS, so it still fires on a genuine hard stall. The prebuffer only hides
  sub-N inbound jitter from OBS.
- **Arm-before-handover:** feeds arm ~2–3 min before going on air, so the ring is
  warm and the full reserve is available at the cut. A cold arm builds the reserve
  over the first N seconds (best-effort, no worse than today).
- **Direct-serve fallback (`RACECAST_FEED_FANOUT=0`):** unaffected — there is no
  ring, so no prebuffer; the proven `--player-external-http` path is untouched.

## Fallback B (documented, only if A fails live validation)

If the local back-pressure test (below) shows OBS **draining** the gap rather than
holding it at ~N (i.e. OBS reads faster than 1× and closes the reserve), escalate
to **active paced de-jitter delivery**: the relay rate-limits its writes to OBS to
~1× playout and refills the reserve from bursts. This guarantees the buffer
regardless of OBS's read behaviour, at the cost of deriving "1× playout" from a raw
byte stream (MPEG-TS PCR parsing or a smoothed arrival-rate pacer) and added
hot-path complexity. Not built unless A is disproven.

## Testing

**Unit (CI, stdlib — `tests/`):**

- Time index: `offset_at_age` returns the correct offset across ages; clamps to
  `start_offset` when history < age; prunes marks below `base`; monotonic under
  throttled marks.
- `trailing_offset`: clamps to `[start, live]`; `prebuffer_s <= 0` → `live_offset`.
- **Synthetic bursty-writer starvation test:** drive a `FeedRing` with writes
  separated by 0.5–2.2 s gaps; a reader consuming at ~1× from `trailing_offset(3.0)`
  must never receive `b""` during a gap shorter than N, and `live_offset − cursor`
  must stay ≈ N.
- Config parse: default / `0` / invalid / negative.
- Existing overflow / cursor-snap tests stay green with a trailing initial cursor.

**Local (maintainer, needs ffmpeg, not CI):** the relay serves a paced synthetic
MPEG-TS feed to a real `ffmpeg` reading at 1×; log `live_offset − consumer_cursor`
over several minutes. Holds ≈ N → **A confirmed**; drains → **escalate to B**.

**Controlled live smoke** on one real stream before the next event (never
mid-event — the relay self-heals and outbound probes against a throttled IP make
things worse).

## Risk summary

| # | Risk | Severity | Mitigation |
|---|------|----------|-----------|
| R1 | OBS reads faster than 1× and drains the reserve (A's core assumption) | Medium | Local ffmpeg back-pressure test before shipping; fallback B defined |
| R2 | Default-on adds latency for every producer | Low | 3 s on non-interactive commentary is unnoticeable; `=0` reverts instantly |
| R3 | Overflow headroom above the trailing cursor shrinks at high bitrate | Low | ~8 s headroom left at 10 Mbps; ring bump is a one-line change if needed |
| R4 | Reintroduce the ~2 s stale-frame glitch | Low | Bounded fixed offset ≠ growing backlog; `close_when_inactive=True` reconnects fresh |

## Out of scope (tracked separately)

- Health/DROP detection of the source-stall class + optional auto-resync — #535.
- Displaying the already-sampled `sys_*` host metrics in the report — #536.
- The SPLIT-macro on-air-aware audio fix — #534.
- The YouTube Ultra-low latency switch — operational note only, #538.

## References

- Fan-out hub design: `docs/superpowers/specs/2026-06-28-relay-feed-fanout-design.md`
- `src/relay/racecast-feeds.py` — `FeedRing`, `FeedFanoutServer`, `ProgramAudioService`
