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

### Principle: heavy decode stays server-side; only cheap stills leave

```
                         (only while ≥1 director is viewing a feed tile)
 upstream (YT/Twitch) ──► ONE shared low-res (360p) pull per feed  ──┐
   (≈1 Mbps/feed,                                                    │  (in-process)
    flat vs. #directors)        ├─ JPEG snapshot ~1/s ─► latest-frame cache ─┐
                                └─ ebur128 audio level (continuous) ─► level  │
                                                                              ▼
 directors  ◄── cheap poll (~1 s): <img> still + small JSON levels ◄── relay cache
   (≈0.2 Mbps/tile/director)
```

The continuous low-res pull and the audio analysis run **once per feed**, shared across
all viewers. Directors only poll the cached latest frame + the current level — so
delivery cost is tiny and multi-director-safe.

### Components

1. **`PreviewPullManager`** (new, in the relay). One worker per **previewed** feed
   (`A`, `B`, and `POV` when the PiP is active). Each worker:
   - resolves + starts a single low-res (360p) decode of the feed (see "Source per
     platform"),
   - keeps the **latest JPEG frame** (sampled ~1/s) in memory,
   - keeps the **current audio level** (continuous `ebur128`/`astats` parse) in memory,
   - is **reference-counted**: started when the first director opens that feed tile,
     stopped after a short idle (no poll for ~N s) so the pull/decode/bot-check only run
     while someone is actually watching.
   - manages its child process(es) like the feed workers do (no orphan ffmpeg; killed on
     stop), and is **best-effort**: any failure marks the tile "unavailable" and **never**
     affects the real feed.

2. **Relay endpoints** (read-only; mirror the existing preview/cockpit auth model):
   - `GET /preview/feed/{A|B|POV}` → latest cached JPEG (still), or `503` with a note when
     unavailable. Polling this (with a cache-bust query) is what marks a viewer "active"
     and keeps the worker alive.
   - `GET /preview/levels` → small JSON `{ "A": {level, ts}, "B": {...}, "POV": {...} }`
     with the current audio level per feed (0..1 or dBFS), polled ~1/s.
   - Funnel-reachable equivalents under the existing `/console` mount
     (`GET /console/preview/feed/{…}`, `GET /console/preview/levels`) — **no new public
     surface**; gated like the other `/console` endpoints.
   - The Program tile keeps using the existing `GET /preview/program` (OBS screenshot,
     ~1.5 s poll) unchanged.
   - The current click-grab path (`/preview/feed/{X}` via `preview_source` →
     `feed_grab_cmd`/OBS screenshot) is **replaced** by the cache-backed endpoint above;
     `feed_grab_cmd` / the loopback-port grab is removed (it never worked off-air).

3. **Frontend** (`src/director/director-panel.html`): the feed tiles become
   **auto-polling still tiles** (default ~1 s) with:
   - an **audio level bar** per tile, driven by `/preview/levels`,
   - the existing on-air outline + program label,
   - **per-tile play/pause** (pausing stops that tile's polling → its worker idles out),
     fixing "can't dismiss a single tile".
   - graceful "unavailable" state per tile (worker not running / source failed) without
     red-erroring the whole section.

### Source per platform (the 360p second view, decoupled from OBS)

The preview pull is **independent** of the feed's OBS loopback port (that is what fixes
the off-air "Unavailable"); it selects a **low rendition at the source**, so we never
download 1080p:

- **Twitch feed:** `streamlink <twitch-url> 360p` piped to `ffmpeg` → 360p directly from
  Twitch's named qualities. **No yt-dlp, no bot-check.**
- **YouTube feed:** a **separate** low-res resolve — `yt-dlp -g -f "b[height<=360]/w"
  --cookies …` returns YouTube's 360p rendition URL — then served via the **same
  streamlink context as the real feed** (browser User-Agent + cookies file, the #345
  fix) into `ffmpeg`. This is one extra, **isolated, best-effort** resolve (the one
  bot-check), run only while the preview is open and shared across directors. A failure
  shows "unavailable" on the tile and never touches the live feed.

`ffmpeg` produces both outputs from the single decode: a ~1 fps JPEG (`-vf fps=1`,
scaled) for the latest-frame cache and an `ebur128` audio measurement (parsed from
stderr) for the level. The heavy MJPEG/decode stays inside the relay process; only the
sampled still + the level number are exposed.

### Multi-director behaviour (the safety contract)

- **Download/CPU is flat:** one shared pull + decode per feed, never per director.
- **Egress is bounded and tiny:** directors poll cached stills (~0.2 Mbps/tile each).
- A modest hard cap on concurrent preview pulls (feeds × 1) and a per-tile idle-stop keep
  resource use bounded; no per-director process is ever spawned.

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

- argv builders for the Twitch and YouTube 360p pulls (pinned, like `feed_grab_cmd` is
  today),
- `ebur128`/`astats` stderr → level parser,
- `PreviewPullManager` reference-count / idle-stop state machine (start on first viewer,
  stop after idle, never spawn per-director),
- endpoint routing + auth gating (`tests/test_racecast.py` / `tests/test_ui_server.py`
  style) including the `/console/preview/*` Funnel mount and the `503`/"unavailable"
  shape.

Live verification against a real stream via the **`racecast-local-uat`** skill (the
relay's network/OBS behaviour is only fully observable live).

**Wiki/docs:** the Director Panel is a tracked UI surface — its screenshot
(`src/docs/wiki/images/director-panel.png`) MUST be regenerated and committed in the same
change (CLAUDE.md hard rule), via the `wiki-screenshots` skill.

## Risks

- **YouTube low-res resolve = one extra bot-check** while preview is open (memory:
  "YouTube feed 403 = streamlink context"). Mitigation: isolated/best-effort, cookie +
  UA reuse via the proven streamlink path, shared across directors, resolved once and
  reused until expiry, and a failure degrades to "unavailable" without touching the live
  feed. Twitch has no such cost.
- **Producer CPU:** one extra 360p decode per previewed feed while open. Bounded by the
  feed count and the idle-stop; acceptable on a broadcast machine.
- **Latency:** stills are ~live (platform floor + segment latency); the user accepted that
  a 1 s still is enough for the swap decision.

## Deferred: fan-out issue (separate)

The ~2 s stale-frame-on-activation glitch the user observed live, and a "free" preview
without a second pull, both require decoupling `streamlink`'s lifecycle from OBS — i.e. a
**relay-side fan-out** where the relay is the persistent single consumer and re-serves the
stream to OBS **and** preview. That is a rewrite of the most live-critical, fragile path
(TS passthrough to multiple consumers, keyframe/buffer handling, slow-consumer policy) and
must be planned + live-tested on its own. **Tracked as a new GitHub issue**, not part of
this spec. This spec deliberately leaves the feed/OBS path untouched.
