# Roles &amp; Requirements

Three roles. A printable one-card-per-role version ships as `IRO_cheat_sheets.html` in
the package.

## Streamer / commentator

Streams their stint to their own channel. Hand this list to every streamer:

- **Platform:** your own YouTube channel (or Twitch), stream set to **Unlisted**, always
  the **same channel** each event.
- **Latency setting:** **Low** — *not* "Ultra-low" unless your connection is rock-solid.
  Buffering protection lives on the producer side, so Low gives a responsive feed while
  staying stable.
- **Resolution:** **1080p target.** If your upload can't reliably sustain ~6 Mbps, drop
  to **720p — but never below 720p.**
- **Bitrate (CBR), keyframe interval 2 s:** 1080p60 ≈ 8000 kbps · 1080p30 ≈ 6000 kbps ·
  720p60 ≈ 4500 kbps · 720p30 ≈ 3000 kbps.
- **Audio:** 128–160 kbps AAC, 48 kHz, stereo.
- **Encoder:** hardware (NVENC / QuickSync / AMF) to spare your CPU.
- **No personal overlays/graphics** — those are added centrally by the producer.
- **Provide your watch URL** before your stint (relay mode, unlisted →
  `https://www.youtube.com/watch?v=VIDEOID`), entered into the `Schedule` tab. For static
  public channels, provide your **channel ID once** instead.

## Producer

Runs OBS + the feeds + Companion + Discord + Tailscale on one machine. Live job: only
**start and stop** the IRO broadcast. Responsibilities:

- Set the station up: [Installation](Installation), [Configuration](Configuration),
  [OBS Setup](OBS-Setup), [Companion](Companion).
- Run the [pre-flight check](Runbook#before-the-event-producer) and start the feeds.
- Keep the shared Google Sheet and stagetimer resources intact.
- Hand control to the director once streaming starts.

> **Interviews — join the Discord "Interviews" voice channel yourself (last/only part).**
> Interviews run at the **end** of the broadcast over Discord voice. The OBS capture taps
> **your local Discord app**, so the producer who is on air for that part **must join the
> "Interviews" voice channel personally** — the director can't do this remotely.
> - **Who:** only the producer of the **last** part. An 8 h event = 1 part = always the
>   last part → that producer always joins. On 12 h / 24 h events only the final-part
>   producer joins; earlier producers skip Discord entirely.
> - **When:** join **before race end**. You stay muted in OBS until the director fires
>   `→ INTERVIEW`, so joining early is harmless.
> - **How:** keep **Discord windowed, not fullscreen** (macOS App Audio Capture needs it).

## Director (remote)

Controls scenes, feeds, volume, mute and graphics from a **browser** via Companion over
Tailscale — no software beyond a browser. Multiple directors supported; the producer can
also take this role locally. See [Director (Remote)](Director) and the
[Runbook](Runbook).

---

## Shared production resources

The HUD and graphics pull live data from the **shared Google Sheet** and
**stagetimer.io**. These are shared — changes affect everyone, and the sheet must stay
shared. IDs/URLs are configured per machine via `.env` (see
[Configuration](Configuration)), never hardcoded.
