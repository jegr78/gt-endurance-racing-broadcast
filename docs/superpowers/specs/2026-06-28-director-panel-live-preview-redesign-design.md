# Director Panel live preview — redesign (per-second stills + audio meter)

Date: 2026-06-28
Status: design approved, ready for implementation plan
Supersedes the feed-tile mechanism of `2026-06-16-live-preview-design.md`
(the program tile is kept unchanged).

## Problem

The Director Panel ships a "Live Preview" section (spec `2026-06-16-live-preview-design.md`):
a Program tile (OBS program screenshot, auto-polled ~1.5 s) plus a per-feed tile
(Feed A / B / POV) that grabs a still **on click**. The intent was that a remote
director could verify the **off-air** (upcoming) feed before cutting to Splitscreen and
pressing NEXT.

In practice the feed tiles are unusable for that purpose:

1. **Off-air feed always returns "Unavailable".** Verified root cause: the off-air
   feed's still is grabbed with `ffmpeg -i http://127.0.0.1:5300X` from the feed's
   loopback port (`feed_grab_cmd`, `racecast-feeds.py`). But `streamlink
   --player-external-http` serves **a single consumer**, and OBS's media source holds
   that port open even while the source is off-air (`close_when_inactive=False` in
   `src/obs/GT_Endurance.json`; the `obs_ws.py` module docstring confirms OBS keeps the
   socket while the source is not in the active scene). So the only consumer slot is
   taken by OBS → the preview `ffmpeg` cannot connect → HTTP 503 → "Unavailable", every
   time. The feature therefore works **only** for the feed that is already on air —
   useless for the pre-swap check it was built for.
2. **Stills only, manual refresh.** Feed tiles never auto-update (only the program tile
   polls); one click yields one frame. No sense of motion or readiness.
3. **No audio signal at all.** A still cannot answer "does this feed have audio / is the
   next commentator already talking?". The backend exposes no audio levels either
   (`/obs/state` reports only mute/volume **settings**, not meters).
4. **Confusing controls.** The ↻ buttons refresh the still; there is no way to dismiss a
   single tile except collapsing the whole section.

This is a regression from the league's previous VDO.Ninja multiview, which showed live
moving video + audio of every source at once.

## Goals

- A remote director can, from `/panel` (tailnet) **and** `/console/panel` (Funnel),
  see each feed (A, B, POV) **auto-updating** and judge: is it live, correctly framed,
  and **does it have audio** — specifically the **off-air** feed before a Splitscreen swap.
- **Broadcast safety is paramount:** the preview must never threaten the live broadcast,
  including when 2–3 directors/crew have the panel open at once.
- No new runtime dependency (stdlib + the existing `ffmpeg` / `streamlink` / `yt-dlp`).
- The live-critical feed path (relay ⇄ OBS ping-pong) is **not touched**.

## Non-goals (explicitly deferred)

- **Fluid (multi-fps) video.** Rejected for broadcast safety — see "Why stills, not
  MJPEG" below.
- **Audible audio.** A per-feed **level meter** is sufficient (decided with the user); no
  audio is transported.
- **Sub-second latency.** The feeds are YouTube/Twitch live streams that already carry
  several seconds of platform latency before the relay sees them; the realistic target is
  "live moving-enough picture at OBS-comparable latency".
- **Fixing the ~2 s stale-frame-on-activation glitch** and the underlying single-consumer
  warm-feed model. This is a separate, larger change (relay-side fan-out) and gets its own
  issue (see "Deferred: fan-out issue").

## Why stills, not MJPEG (the broadcast-safety decision)

A continuous MJPEG stream per tile was considered and rejected. The cost splits into two
layers that scale differently:

- **Pull + decode (download/ingress + CPU):** can be kept **flat** by sharing one low-res
  pull per feed regardless of viewer count.
- **Delivery (upload/egress):** MJPEG is a unicast HTTP stream — **each director gets their
  own copy** over the producer's uplink. With 2–3 directors × 2 tiles at 7 fps/360p this
  is ~6–8 Mbps of egress **on top of** the OBS broadcast (~6–8 Mbps) on a ~10 Mbps uplink
  → it can **starve the live broadcast**. There is no multicast over Tailscale/Funnel.

Per-second **stills** collapse the egress: a 360p JPEG (~25 KB) once per second ≈
~0.2 Mbps per tile, so 3 directors × 2 tiles ≈ ~1.2 Mbps — negligible next to the
broadcast. The director loses fluid motion but keeps everything the swap decision needs
(live-ish picture + audio meter). This was an explicit user trade-off: stills are
acceptable **as long as the audio indicator is preserved**.

## Design

### Principle: source each tile the cheapest way; heavy work stays server-side

A feed tile is sourced from **OBS when OBS is already decoding that feed**, and only falls
back to a decoupled low-res pull for the **off-air feed OBS cannot render**. This is the
key cost reduction — see "Source per tile" below. In all cases the relay keeps a per-tile
**latest still (+ level)** cache, refreshed ~1/s, and every director just polls the cache
(so delivery cost is flat in the number of directors).

```
 ON-AIR feed / active POV ─► OBS GetSourceScreenshot (~1/s, cached) ─┐
   (OBS already decodes it; no pull, no audio meter — audible on air) │
                                                                      ├─► per-tile
 OFF-AIR feed ─► ONE decoupled low-res (360p) pull (only this feed)   │   latest-still
   (OBS can't render it; loopback port held single-consumer)          │   (+ level)
        ├─ JPEG snapshot ~1/s ─────────────────────────────────────────┤   cache
        └─ ebur128 audio level (continuous) ───────────────────────────┘     │
                                                                             ▼
 directors ◄── cheap poll (~1 s): <img> still + small JSON levels ◄── relay cache
   (≈0.2 Mbps/tile/director, flat vs. #directors)
```

In steady state only **one** decoupled pull runs — the selector keys off `live_feed()`
(the single on-air feed), so the one non-live feed is the pull. (During the Splitscreen
window OBS is decoding *both* feeds, so a splitscreen-aware selector could drop that pull
too; the current selector does not special-case it, so one pull still runs there — the
single-pull cap and idle-stop bound the cost, and it never affects the live feeds. A
splitscreen-aware optimization is a possible future refinement.) Each shared source (OBS
screenshot or the off-air pull) is fetched once per ~1 s regardless of how many directors
watch.

### Components

1. **Per-tile still cache** (new, in the relay). For each feed tile the relay holds the
   **latest JPEG (+ level, ts)**, refreshed ~1/s from the source chosen by the pure
   `preview_source` selector (extended — see "Source per tile"):
   - **active source (on-air feed / active POV):** an **OBS `GetSourceScreenshot`** of
     `Feed A|B|POV`, taken once per ~1 s and cached. No pull, no audio meter.
   - **off-air feed:** served from the `PreviewPullManager` worker (below).
   The OBS screenshot is also shared/cached (one screenshot per source per ~1 s regardless
   of director count), so OBS load is bounded.

2. **`PreviewPullManager`** (new, in the relay) — runs **only for the off-air feed**
   (the non-`live_feed()` feed; at most one pull at a time). Its worker:
   - resolves + starts a single low-res (360p) decode of that feed (see "Source per tile"),
   - keeps the **latest JPEG frame** (sampled ~1/s) and the **current audio level**
     (continuous `ebur128`/`astats` parse) in memory,
   - is **reference-counted**: started when the first director opens that off-air tile,
     stopped after a short idle (no poll for ~N s) so the pull/decode/bot-check only run
     while someone is actually watching,
   - manages its child process(es) like the feed workers do (no orphan ffmpeg; killed on
     stop), and is **best-effort**: any failure marks the tile "unavailable" and **never**
     affects the real feed.
   When the off-air feed becomes active (a swap/`/next`), the selector flips it to the OBS
   source and the now-redundant pull idles out.

3. **Relay endpoints** (read-only; mirror the existing preview/cockpit auth model):
   - `GET /preview/feed/{A|B|POV}` → latest cached JPEG (still, from OBS or the off-air
     pull as selected), or `503` with a note when unavailable. Polling this (with a
     cache-bust query) marks a viewer "active" and keeps an off-air worker alive.
   - `GET /preview/levels` → small JSON with the current audio level **for the off-air
     feed** (the only one with a pull), e.g. `{ "B": {level, ts} }`; active feeds carry no
     level (audible on air), polled ~1/s.
   - Funnel-reachable equivalents under the existing `/console` mount
     (`GET /console/preview/feed/{…}`, `GET /console/preview/levels`) — **no new public
     surface**; gated like the other `/console` endpoints.
   - The Program tile keeps using the existing `GET /preview/program` (OBS screenshot,
     ~1.5 s poll) unchanged.
   - The current click-grab path (`feed_grab_cmd` / the loopback-port grab) is **removed**
     (it never worked off-air); the OBS-screenshot branch of today's `preview_source` is
     reused for active tiles.

4. **Frontend** (`src/director/director-panel.html`): the feed tiles become
   **auto-polling still tiles** (default ~1 s) with:
   - an **audio level bar** on the **off-air** tile (driven by `/preview/levels`); the
     on-air tile shows an **"ON AIR"** marker instead of a meter (it is audible in the
     program),
   - the existing on-air outline + program label,
   - **per-tile play/pause** (pausing stops that tile's polling → an off-air worker idles
     out), fixing "can't dismiss a single tile",
   - graceful "unavailable" state per tile (source failed) without red-erroring the whole
     section.

### Source per tile (a pure selector, extending today's `preview_source`)

`preview_source(target, live, pov_active, …)` already classifies a tile; it is extended to
return one of:

- **`obs`** — for the **on-air feed** (`target == live`) and the **active POV**: OBS is
  decoding the source, so a cached `GetSourceScreenshot` of `Feed A|B|POV` is the still.
  No pull, no audio level. *(This is the "get it from the normal feed, via OBS" path.)*
- **`pull`** — for the **off-air feed**: OBS isn't decoding it **and** its loopback port is
  held single-consumer by OBS, so the only way to see it is a decoupled low-res pull. This
  is the tile the director most needs (the upcoming feed) and the only one that carries an
  audio meter.
- **`placeholder`** — feed off / POV inactive (unchanged).

The decoupled **off-air pull** is **independent** of the loopback port (that is what fixes
the "Unavailable") and selects a **low rendition at the source**, so we never download
1080p:

- **Twitch feed:** `streamlink <twitch-url> 360p` piped to `ffmpeg` → 360p directly from
  Twitch's named qualities. **No yt-dlp, no bot-check.**
- **YouTube feed:** a **separate** low-res resolve — `yt-dlp -g -f "b[height<=360]/w"
  --cookies …` returns YouTube's 360p rendition URL — then served via the **same
  streamlink context as the real feed** (browser User-Agent + cookies file, the #345
  fix) into `ffmpeg`. This is one extra, **isolated, best-effort** resolve (the one
  bot-check) — run **only when the off-air feed is YouTube and being previewed**, shared
  across directors. A failure shows "unavailable" on the tile and never touches the live
  feed.

`ffmpeg` produces both outputs from the single decode: a ~1 fps JPEG (`-vf fps=1`,
scaled) for the latest-frame cache and an `ebur128` audio measurement (parsed from
stderr) for the level. The heavy MJPEG/decode stays inside the relay process; only the
sampled still + the level number are exposed.

### Multi-director behaviour (the safety contract)

- **Download/CPU is flat:** at most one decoupled pull (the off-air feed), shared across
  all directors; active tiles reuse one cached OBS screenshot per source per ~1 s. Never
  per director.
- **Egress is bounded and tiny:** directors poll cached stills (~0.2 Mbps/tile each).
- A hard cap of one pull per feed plus a per-tile idle-stop keeps resource use bounded; no
  per-director process is ever spawned.

### Security / Funnel

Same boundary as today: only `/console` is Funnel-mounted; the preview endpoints under
`/console/preview/*` are gated like the rest of the console surface. The data is already
public platform video; the relay adds **no write path** and stays read-only/ephemeral.
OBS-WebSocket is never funnelled.

### Error handling

Every preview path is best-effort and **never raises** (same contract as
`get_program_screenshot`): a missing/failed pull → the tile shows "unavailable"; the
program tile shows "OBS unreachable" when OBS is down. None of it can disturb the live
feed workers or the relay.

## Testing

Pure, stdlib, runnable-script tests (the repo convention), e.g. extend
`tests/test_pov.py` / a new `tests/test_preview.py`:

- the extended pure `preview_source` selector (on-air/POV → `obs`, off-air → `pull`,
  off/inactive → `placeholder`, and the flip when a swap makes the off-air feed active),
- argv builders for the Twitch and YouTube 360p off-air pulls (pinned, like `feed_grab_cmd`
  is today),
- `ebur128`/`astats` stderr → level parser,
- `PreviewPullManager` reference-count / idle-stop state machine (start on first viewer,
  stop after idle / after the feed goes on air, never spawn per-director),
- endpoint routing + auth gating (`tests/test_racecast.py` / `tests/test_ui_server.py`
  style) including the `/console/preview/*` Funnel mount and the `503`/"unavailable"
  shape.

Live verification against a real stream via the **`racecast-local-uat`** skill (the
relay's network/OBS behaviour is only fully observable live).

**Wiki/docs:** the Director Panel is a tracked UI surface — its screenshot
(`src/docs/wiki/images/director-panel.png`) MUST be regenerated and committed in the same
change (CLAUDE.md hard rule), via the `wiki-screenshots` skill.

## Risks

- **YouTube low-res resolve = one extra bot-check** — only when the **off-air feed is
  YouTube** and someone is previewing it (memory: "YouTube feed 403 = streamlink
  context"). Mitigation: isolated/best-effort, cookie + UA reuse via the proven streamlink
  path, shared across directors, resolved once and reused until expiry, and a failure
  degrades to "unavailable" without touching the live feed. Twitch has no such cost; active
  tiles use OBS screenshots and incur no resolve at all.
- **Producer CPU:** at most one extra 360p decode (the off-air feed) while previewed, plus
  cheap periodic OBS screenshots for active tiles. Bounded by the idle-stop; acceptable on
  a broadcast machine.
- **Latency:** stills are ~live (platform floor + segment latency); the user accepted that
  a 1 s still is enough for the swap decision.

## Deferred: fan-out issue (separate)

The ~2 s stale-frame-on-activation glitch the user observed live, and a "free" preview
without a second pull, both require decoupling `streamlink`'s lifecycle from OBS — i.e. a
**relay-side fan-out** where the relay is the persistent single consumer and re-serves the
stream to OBS **and** preview. That is a rewrite of the most live-critical, fragile path
(TS passthrough to multiple consumers, keyframe/buffer handling, slow-consumer policy) and
must be planned + live-tested on its own. **Tracked as GitHub issue #358**, not part of
this spec. This spec deliberately leaves the feed/OBS path untouched.
