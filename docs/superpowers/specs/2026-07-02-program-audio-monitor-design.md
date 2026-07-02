# On-Air Program-Audio Monitor — Design

**Date:** 2026-07-02
**Status:** Design approved, pending implementation plan
**Scope:** A toggleable audible monitor of the on-air feed's audio, offered next to the
program-preview still on the Director Panel, Commentator Cockpit, and Race Control desk.

## Motivation

The three console previews (Director Panel, Commentator Cockpit, Race Control) currently
show only a **silent** program monitor: a JPEG still re-fetched every ~1.5 s
(`get_program_screenshot` → obs-websocket `GetSourceScreenshot`). The crew cannot *hear*
what is on air. This adds an optional, opt-in audio monitor of the on-air program.

## Decisions locked in brainstorming (2026-07-02)

- **Audio source = on-air feed only, follows the handover** (A↔B) automatically. No
  pre-listen of the incoming/off-air feed, no free feed selection. Matches "the active
  scene" and the `no preview-then-take` domain constraint.
- **Feed-audio, not the full OBS program mix.** The full OBS mix (intro/outro clips,
  Intermission Music, split-screen dual-feed, OBS-side audio) is explicitly **deferred** —
  the only realistic full-mix path couples to OBS's recording slot / a per-OS virtual audio
  device, which fights the cloud-producing direction of issue #395 (eliminate OBS-side
  manual setup). Feed-audio lives entirely in the relay, which sits *with* the feeds in the
  cloud scenario, so it works identically local or cloud. Revisit the full mix only after
  #395 settles the local-vs-cloud + Discord-audio questions. See memory
  `program-audio-monitoring-feed-first`.
- **Available by default, audio default-muted.** Endpoints + toggle are live whenever the
  fan-out is on (the default). The encoder is **on-demand**: it starts on the first
  listener and is idle-reaped when the last one leaves → **zero cost when nobody listens**.
  A kill-switch `RACECAST_PROGRAM_AUDIO=0` disables the feature entirely.
- **Transport = progressive HTTP MP3 stream** played by a bare `<audio>` element. No new
  JS dependency. MP3 chosen over AAC-ADTS for **universal browser decodability** (Firefox,
  esp. on Linux, may lack system AAC codecs). The ffmpeg codec/bitrate is
  **parameterized in a constant**, so switching to AAC later is a one-line change. The
  marginal bandwidth win of AAC (~64 kbps ≈ MP3 ~96 kbps, ~0.15 Mbps saved for 5 listeners)
  does not justify the Firefox decode risk for v1.

## Non-goals (v1)

- No full OBS program mix (see above).
- No pre-listen / free feed selection.
- No fan-out-OFF fallback (no second re-pull streamlink). When fan-out is off the feature
  reports unavailable (404) and the front-end card self-hides. (YAGNI; fan-out is
  default-on and live-verified.)
- No client-side codec negotiation (`canPlayType` dual MP3/AAC). Deferred.
- No persistence, no recording of the monitored audio.

## Architecture

The video preview is unchanged (JPEG stills). Audio is an independent endless MP3 stream
served by the relay, mirroring the existing fan-out / preview architecture:

```
on-air feed's FeedRing  ──►  stdin-pump  ──►  ffmpeg (audio-only → MP3)  ──►  output FeedRing  ──►  HTTP serving loop  ──►  <audio> in browser
     (raw MPEG-TS)                              PROGRAM_AUDIO_FFMPEG_*                                (wfile.write loop)
                                                                                                     N listeners share one encoder
```

### Prior art this builds on (`src/relay/racecast-feeds.py`)

- `FeedRing` (L2699) — bounded byte ring, single writer / many readers, non-blocking
  writer; `read(cursor, timeout)`, `live_offset()`, `write()`, `close()`.
- `_PreviewRingTap` (L2564) — the exact template: subscribe to a `feed.ring` at the live
  edge, pipe bytes into an ffmpeg on stdin. We mirror it but encode audio → MP3 instead of
  MJPEG + ebur128.
- `PreviewManager` (L2811) — reference-counted single worker + idle reaper
  (`run()` idle_timeout, default 8 s), injectable `worker_factory` for tests. We mirror the
  lifecycle.
- `FeedFanoutServer._serve` (L2782) — the only raw endless-write loop in the codebase; the
  template for the new streaming HTTP response.
- `Relay.live_feed()` (L4748) — authoritative on-air feed identity, derived from stint
  index (`"A" if A.idx <= B.idx else "B"`); flips implicitly at handover. Handover mutators:
  `next_auto()` (L4929), `advance()` (L4941), `set_stint()` (L4952), `set_mode()` (L4964),
  all funnel through `_reflect(live, cut)` (L4809).
- `auto_failover_enabled(environ)` (L215) — the default-OFF flag template; we invert it to
  default-ON (kill-switch) for `program_audio_enabled`.

### New component: `ProgramAudioService`

A relay-owned service (constructed alongside `preview_manager`, ~L7047), modeled on
`PreviewManager`:

- **Input:** `relay.feeds[relay.live_feed()].ring`, joined at `ring.live_offset()`. Requires
  `relay.fanout` true (the in-process bytes only exist under fan-out).
- **Encoder:** one ffmpeg per active service. Pure command builder
  `program_audio_ffmpeg_cmd()`:
  ```
  ffmpeg -nostdin -loglevel warning -i pipe:0 -vn -map 0:a:0? \
         -ar 44100 -ac 1 -c:a libmp3lame -b:a 96k -f mp3 pipe:1
  ```
  Codec/rate/bitrate live in module constants (`PROGRAM_AUDIO_CODEC`,
  `PROGRAM_AUDIO_BITRATE`, `PROGRAM_AUDIO_FORMAT`, `PROGRAM_AUDIO_CONTENT_TYPE`) so an
  AAC-ADTS switch is a one-line edit. Fixed `-ar/-ac` guarantees frame compatibility across
  a handover restart (see below).
- **Two pump threads** (like `_PreviewRingTap`): stdin-pump (`ring.read` → `ffmpeg.stdin`)
  and stdout-pump (`ffmpeg.stdout` → output `FeedRing`). streamlink/ffmpeg stderr is pumped
  to the feed logger with a tag (parity with existing workers).
- **Output:** a dedicated output `FeedRing`, re-served to all HTTP consumers. One encoder,
  N listeners → flat encoder cost, N× egress.
- **Handover re-point:** the service polls `relay.live_feed()` on a short interval (~1 s)
  in its own loop — cheap and always current, no coupling into `_reflect`. On a change, stop
  the current ffmpeg + stdin-pump and start fresh ones pointed
  at the new feed's ring, **keeping the same output ring**. Because MP3 frames are
  self-contained and both encoders use identical `-ar/-ac`, the client stream splices
  seamlessly — only a brief (~0.5–1 s) silence gap, no client disconnect. Guard: only
  re-point to a feed that is actually serving (mirror the `cut=True` guard in `next_auto`).
  Pure decision helper `should_retarget(prev_live, cur_live, serving)` for unit testing.
- **Lifecycle:** reference-counted. First listener starts the worker; an idle reaper stops
  ffmpeg after a few seconds with zero listeners (reuse `PreviewManager`'s idle_timeout,
  default 8 s). Best-effort throughout: missing ffmpeg / no audio
  track / OBS unreachable never raises (same contract as `get_program_screenshot`).
- **Flag:** `program_audio_enabled(environ)` — default **ON**, disabled only by an explicit
  falsey `RACECAST_PROGRAM_AUDIO` token (`0/false/no/off`). Pure, unit-tested. Read once in
  `Relay.__init__`.

### Endpoints & auth

Two GET streaming routes; both automatically inherit `Requirement(ANY, False)` from
`console_policy.min_capability` (`/preview/*` at L133, `/console/*` gated by the mount) — no
new public surface:

- `GET /preview/program-audio` — Director Panel (tailnet / loopback).
- `GET /console/cockpit/program-audio` — Cockpit + Race Control (reachable via Funnel under
  the existing `/console` mount).

New streaming response pattern (no fixed Content-Length — the first such helper in the
codebase):

```
send_response(200)
Content-Type: audio/mpeg        # PROGRAM_AUDIO_CONTENT_TYPE
Cache-Control: no-store
Connection: close
# no Content-Length
→ loop: data, cursor = output_ring.read(cursor, timeout); wfile.write(data)  until client disconnects
```

- Feature off (`RACECAST_PROGRAM_AUDIO=0`) **or** fan-out off → **404** (front-end card
  self-hides, like the broadcast-chat card).
- ffmpeg/OBS failure → 503 with a note.
- `ThreadingHTTPServer` → one thread per listener; fine for ~3–8 crew. A dead client socket
  makes `wfile.write` raise `BrokenPipe` → handler exits → refcount −1 → reaper stops ffmpeg
  when the last listener leaves.

### Front-end (three pages)

`director/director-panel.html`, `cockpit/cockpit.html`, `racecontrol/race-control.html` each
gain, next to the program monitor:

- A hidden `<audio>` element + a **speaker toggle** button + a small **volume slider**.
- Toggle ON → `audio.src = RC_API(".../program-audio") + "?ts=" + Date.now(); audio.play()`
  (the user gesture satisfies the browser autoplay-with-sound policy → "default muted" is
  automatic). Director Panel uses `/preview/program-audio`; cockpit + race-control use
  `/console/cockpit/program-audio` via the `RC_API` base shim (tailnet + Funnel identical).
- Toggle OFF → `audio.pause(); audio.src = ""` → drops the connection → relay reaps the
  encoder.
- State is per-session only (a gesture is required anyway). On load, probe the endpoint;
  hide the whole audio control on 404. URL validated client-side in the `bchatUrlOk` style.

## Edge cases

- **Fan-out off:** no in-process ring → 404, card hidden. Documented; no v1 fallback.
- **No audio track in feed** (`0:a:0?` matches nothing): ffmpeg emits no bytes → listener
  hears silence, loop stays stable, reaper cleans up. No crash.
- **Handover gap:** ~0.5–1 s silence on ffmpeg restart; client `<audio>` buffers, no
  disconnect. Accepted.
- **On-air feed byte-stall / drop:** stdin dries up → silence until recovery/handover; ring
  simply yields nothing. No special handling.
- **POV feed:** never on air → never an audio source (matches on-air-only).
- **Qualifying mode:** `live_feed()` returns Feed A (B idle) → unchanged, correct.
- **Intro/Outro/Standby scene:** OBS shows non-feed content, but the on-air *feed* keeps
  streaming → the commentator stays audible (consistent with feed-audio; arguably useful).
- **Multiple profiles:** the relay is a machine singleton; the service lives on the running
  relay instance → no profile collision.

## Testing (stdlib, each file a runnable script — new `tests/test_program_audio.py`)

Pure, net/thread-isolated pieces (same style as fan-out/preview tests):

- `program_audio_enabled(environ)` — default-ON, kill-switch falsey tokens, real-env
  precedence.
- `program_audio_ffmpeg_cmd()` — exact argv (no video, `0:a:0?`, `-ar/-ac`, libmp3lame,
  `-f mp3`); codec constant takes effect.
- `should_retarget(prev_live, cur_live, serving)` — A→B, B→A, unchanged, not-yet-serving
  guard.
- Refcount / idle lifecycle with an injected fake `worker_factory` (mirror
  `PreviewManager`) — start on first listener, stop after idle, no double-start.
- Auth: assert `["preview","program-audio"]` and the `/console` path resolve to
  `Requirement(ANY, False)`, and that the feature-off path yields 404 (fold into
  `test_console.py` / `test_cockpit.py`).
- e2e (`tools/e2e_checks.py`, synthetic): a check asserting `Content-Type: audio/mpeg`
  headers on `/preview/program-audio`, and **404 when the feature is disabled**. With the
  no-op streamlink stubs no real audio flows, so assert headers/status only, not bytes. The
  read-only nature makes it safe for the real-league subset.

## Docs & screenshot impact (hard rule — same change)

Three UI surfaces change:

- **Wiki screenshots regenerated:** `director-panel.png`, plus the cockpit and race-control
  images under `src/docs/wiki/images/` — via the `wiki-screenshots` skill (demo profile +
  `obs-sim`), element screenshots matching the existing framing.
- **`ui-visual-verification`** gate: render + eyeball the toggle + slider (the Stop hook
  requires the marker step).
- **CLAUDE.md** relay section: a short paragraph on the program-audio monitor (endpoints,
  flag, "fan-out only", MP3/parameterized).
- **Wiki prose** (Director-Panel / Cockpit / Race-Control pages): a "enable audio" note;
  then `tools/sync-wiki.py` + `wiki-visual-test` (separate step).
- **`.env.example`:** `RACECAST_PROGRAM_AUDIO` with a comment (kill-switch, default on).

## Open items for the full-mix successor (not this spec)

Tracked for later: whether commentary audio arrives via the pulled feed at all (#395 Stage
2) — if yes, feed-audio *is* the program audio for the commentary portion, and the full mix
only ever adds intro/outro + intermission music + split-screen. Revisit after #395.
