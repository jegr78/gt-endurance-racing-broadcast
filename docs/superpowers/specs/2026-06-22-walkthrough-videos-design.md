# Narrated Walkthrough Videos — Design

**Date:** 2026-06-22
**Status:** Approved (feasibility + brainstorming)

## Problem

The onboarding material ships as seven role-based Reveal.js decks under
`src/docs/slides/` (`producer`, `director`, `commentator`, `producer-setup`,
`league-admin-setup`, `overlay-designer`, `race-control`). They are read
silently in a browser. We want the same walkthroughs as **narrated MP4 videos**
that can be uploaded to the maintainer's YouTube channel — so a new crew member
can *watch and listen* instead of clicking through slides.

The narration must be **auto-generated** (no manual voice recording) and the
solution must be **free** — no paid text-to-speech.

## Goal

A local, maintainer-only tool that turns each deck into one narrated MP4:

- One MP4 per deck → seven YouTube-ready videos.
- Each slide is shown for exactly as long as its narration takes to speak.
- Narration text is authored as English speaker notes inside the decks.
- Video resolution: the decks' native 1280×720 logical stage, upscaled to 1080p
  for YouTube.

## Decisions (locked with the user)

- **Strictly local. Never CI.** No GitHub Action / workflow ever runs the TTS or
  the video render — same model as `tools/check-slides.py` and
  `tools/sync-wiki.py` (maintainer/pre-publish, not a CI job). The synthesis and
  render are too heavy and too environment-dependent for CI, and the user does
  not want generated audio produced by an Action.
- **Language: English.** Narration matches the on-screen English slides — no
  audio/visual mismatch, international audience.
- **Narration source: speaker notes.** Each `<section>` gets an
  `<aside class="notes">…</aside>` with the spoken script. The `RevealNotes`
  plugin is already initialised in `assets/deck.js`, so notes are first-class and
  are **not** shown in the live presentation. This cleanly separates *what is on
  screen* from *what is spoken* (we never read bullet lists verbatim).
- **TTS engine: swappable layer, both backends implemented.**
  - **Piper** (`--tts piper`): local, open-source, no API key, offline. Was the
    initial default, but on the producer PoC the user found **every** English
    Piper voice (lessac/ryan/amy/hfc/cori/libritts_r/bryce) too artificial for
    public videos. Kept as a free offline fallback, not the chosen engine.
  - **Google Cloud TTS** (`--tts gcloud`, **the chosen engine**): top-tier
    Neural2/Studio/Chirp3-HD voices via the v1 `text:synthesize` REST API.
    Auth is an **API key** (`RACECAST_GCLOUD_TTS_KEY` in `.env`) — simpler than a
    service account and sufficient for a maintainer tool; the request body is
    built by the pure core and the call goes through `http_util.post_json`.
    Free-tier covers this workload (Neural2 ≈1M chars/month; Studio ≈100k/month;
    the whole onboarding is well under that) but requires a billing-enabled GCP
    project. **Chosen voice: `en-US-Studio-Q`** (the new gcloud default), picked
    from a labelled multi-voice comparison render.
  - **edge-tts is explicitly rejected** for these videos: it sounded good in
    testing but relies on an unofficial Microsoft Edge endpoint, which the user
    does not want to use for *public* YouTube content.

## Where things live

- Decks: `src/docs/slides/*.html` — Reveal.js, fixed 1280×720 stage
  (`assets/deck.js`), `transition: 'slide'`, **no fragments** (confirmed: a grep
  for `fragment` matches nothing), so exactly **one screenshot per `<section>`**
  is sufficient. `RevealNotes` is already a registered plugin.
- ffmpeg: already a hard runtime dependency of the project (8.x present) — it is
  the video muxer, no new media tool is introduced.
- Playwright venv: the established headless-browser harness used by
  `tools/check-slides.py` (documented in the `racecast-e2e` skill). We reuse the
  same venv to drive the decks and screenshot slides.

## Design

### Pipeline (per deck)

```
Reveal deck ──Playwright──► one PNG per slide (1280×720)
        │
speaker notes (per slide) ──TTS adapter──► one WAV per slide
        │
        └─► ffmpeg: PNG + WAV ──► slide clip (duration = audio length)
                  │
                  └─► concat all clips of a deck ──► <deck>.mp4   (×7)
```

Per slide:
`ffmpeg -loop 1 -i slide.png -i narration.wav -c:v libx264 -tune stillimage
-pix_fmt yuv420p -vf scale=1920:1080 -c:a aac -b:a 192k -shortest <slide>.mp4`,
then `ffmpeg -f concat` over the deck's slide clips into `<deck>.mp4`. Optional
polish (a short title card per deck, gentle audio fade-in/out, crossfades) is a
v2 concern — v1 ships the straight image+audio concat.

### Swappable TTS layer (the key abstraction)

A narrow interface so "Piper now, Google later" is a backend swap, not a rewrite:

```python
def synthesize(text: str, out_wav: str) -> None: ...   # one backend per engine
```

- `tts_piper.synthesize(...)` — shells out to the local `piper` binary with a
  pinned voice model; v1 default.
- `tts_gcloud.synthesize(...)` — later; Google Cloud TTS REST call. Outbound HTTP
  must go through `src/scripts/http_util.py` per the repo's User-Agent rule (this
  is a covered, non-self-contained module).

Engine selected by flag: `--tts piper` (default) | `--tts gcloud` (later). The
voice/model id is also a flag with a sensible default.

### CLI

`tools/build-walkthrough-videos.py` (maintainer tool, **not shipped**, lives in
`tools/` alongside `check-slides.py`/`build-diagrams.py`):

```
python3 tools/build-walkthrough-videos.py [DECK ...] [--tts piper|gcloud]
        [--voice NAME] [--out DIR] [--keep-intermediates]
```

- No deck args → all seven decks. One or more basenames → just those (useful for
  the proof-of-concept run on a single deck).
- Output: `runtime/walkthroughs/<deck>.mp4` (under `runtime/`, gitignored, local
  only — generated audio/video is never committed).

### Testable core vs. local-only execution (respecting "no CI for TTS")

Mirror the `tools/e2e.py` / `tools/e2e_checks.py` split:

- **`tools/walkthrough_core.py`** — pure, import-testable logic with stdlib-only
  unit tests that run in CI **without ever invoking Piper, Playwright, or
  ffmpeg**: speaker-notes extraction from a deck's HTML, the per-slide ffmpeg
  command builder, the concat-list builder, and the slide-walk/ordering. Tested in
  `tests/test_walkthrough.py`, picked up by `tools/run-tests.py`.
- **`tools/build-walkthrough-videos.py`** — owns the heavy lifecycle (launch
  browser, screenshot, call the TTS adapter, run ffmpeg). This is **local-only**
  and has **no CI job** — the unit suite never executes it.

This keeps the pure logic regression-guarded in CI while honoring the hard
constraint that TTS/rendering never run in an Action.

### Shared intro / outro bumpers

Every video is wrapped with a short (~6 s) **intro** and **outro** title card,
built **once per run and reused for all decks** (`--no-bumpers` to skip,
`--bumper-seconds` to retune). They are plain HTML pages
(`src/docs/slides/walkthrough-{intro,outro}.html`, **not** Reveal decks — no
`class="reveal"`, so excluded from the deck list and the overflow guard) that
reuse the deck design system: white stage, Saira Condensed heading, and an accent
bar made of the **six role colours** (producer/director/commentator/race-control/
league-admin/overlay-designer) to read as "the whole system". The tool screenshots
each card, synthesizes a short voiceover with the same engine/voice, and feeds the
result as a frame-locked `(png, audio, seconds)` segment — identical in shape to a
slide segment — to the front/back of every deck's segment list. Held for at least
`--bumper-seconds` (audio padded with silence via the same frame-lock path), so
intro/outro never drift either. Intro line: "GT Endurance Racing Broadcast.
Onboarding."; outro points at the project wiki.

### Authoring the speaker notes

Add `<aside class="notes">…</aside>` to every `<section>` across the seven decks
(~64 slides total: race-control 7, overlay-designer 7, director 12,
league-admin-setup 9, producer-setup 8, producer 11, commentator 10). The text is
the spoken script — written *for the ear*, not a re-read of the on-screen
bullets. English. Notes are invisible in the live deck (consumed only by
`RevealNotes`), so this is additive and does not change how the decks present.

A slide with **no** notes either: (a) is skipped, or (b) gets a short default
dwell with no audio — TBD; v1 will treat a missing/empty note as "skip with a
warning" so an un-narrated deck is obvious rather than silently producing a
muted clip.

## Non-goals

- No CI/GitHub-Action integration of any kind.
- No paid TTS; edge-tts excluded for public videos.
- No automatic YouTube upload — the tool produces local MP4 files; uploading
  stays a manual step.
- No background music, captions/subtitles, or per-slide transitions in v1
  (possible v2).
- No German narration in v1 (English only, matching the slides). A future German
  pass would be a second run, not a v1 requirement.

## Open questions / future

- **Subtitles/captions** — speaker notes are already plain text, so emitting a
  `.srt`/`.vtt` alongside each MP4 (timed from the per-slide audio durations) is a
  cheap future add and improves YouTube accessibility/SEO.
- **Single-deck proof-of-concept first** — recommended rollout: narrate and render
  one deck (e.g. `producer.html`) end-to-end so the voice and look can be judged
  before authoring notes for all seven.

## Rollout

1. ✅ Build `walkthrough_core.py` + `tests/test_walkthrough.py` (TDD, CI-safe).
2. ✅ Build `tools/build-walkthrough-videos.py` with the Piper **and** Google
   Cloud TTS backends (`--tts piper|gcloud`).
3. ✅ Author English speaker notes for `producer.html`; render the PoC MP4.
   Voice chosen after comparison: **`en-US-Studio-Q`** (gcloud).
4. ✅ Author notes for the remaining six decks and render all seven (1080p, 0 ms
   A/V drift, shared intro/outro on each). Gotcha found: a markdown `---` inside a
   slide template makes Reveal split it into vertical sub-slides, so each half
   needs its own `Note:` — `--list` counts templates and under-reports, but the
   render (Reveal slide count) is authoritative and surfaces any un-narrated slide.
5. Optional: captions (`.srt`/`.vtt`) from the per-slide audio durations.
6. Document the tool in a maintainer skill analogous to `slides-diagrams`.
