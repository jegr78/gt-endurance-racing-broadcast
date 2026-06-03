# Runbook

Step-by-step for an event. Assumes the station is already set up
([Installation](Installation) → [Configuration](Configuration) →
[OBS Setup](OBS-Setup) → [Companion](Companion)).

## Before the event (producer)

1. **Reboot** the machine (clears swap, frees RAM) and close heavy apps.
2. **Update tools:** macOS `brew upgrade streamlink yt-dlp` · Windows
   `pip install -U streamlink yt-dlp`. Confirm FFmpeg and deno.
3. **Update the GPU driver** (the broadcast encodes and the feeds decode on the GPU).
4. **Pre-flight check:** `python3 src/scripts/preflight.py` — resolve any FAIL/WARN
   (tool chain, ports, cookies).
5. **YouTube cookies:** `python3 src/relay/get-cookies.py chrome --runtime-dir runtime`
   (your logged-in browser). `/status` should later show `"cookies": true`.
6. **Tailscale** running; a director confirms they can open
   `http://<producer-tailscale-ip>:8000/tablet`.
7. **OBS WebSocket** on; **Companion** connected (green); scenes/sources loaded.
8. **Start the feeds:** the [relay](Relay-Mode) (`python3 tools/run-relay.py`) or
   [static mode](Static-Mode); confirm each live feed appears in its Media Source.
9. **Test the Discord audio** source (Discord in windowed mode on macOS).
10. **Enter the IRO stream key** in OBS.

## Start

The producer clicks **Start Streaming** in OBS. From here the **director runs the show**.

## During a stint (director)

Keep the **Stint** scene on the active feed, toggle HUD/graphics via Companion, adjust
volumes.

## Driver / lobby change (≈ every 2 h)

1. The incoming streamer goes live on their channel (relay: their watch URL is in the
   `Schedule` tab).
2. Director cuts to **Splitscreen** for the ~10-minute handover window.
3. Press **Feeds Next** (→ `/next`): the off-air feed advances to the next commentator.
4. Once it's serving, cut to **Stint** on the new feed. Nothing to type.

(Edited a cell in the sheet for the current feed? Press **Feeds Reload** → `/reload`.)

## Driver-POV PiP (optional)

Put the driver's watch URL in the `POV` tab cell A2 → **POV Reload** → **POV Toggle** to
show. **POV Toggle** to hide, then **POV Stop** when done. See
[Relay Mode → POV](Relay-Mode#driver-pov-pip-optional).

## Interviews (post-race)

Interviews run at the **end** of the broadcast over Discord voice.

- **Producer (last/only part):** **join the Discord "Interviews" voice channel yourself,
  before race end.** The OBS capture taps your *local* Discord app, so the director cannot
  join for you. You stay muted in OBS until the director cuts to Interview, so joining
  early is harmless. Keep Discord **windowed, not fullscreen** (macOS audio capture).
  Only the final-part producer does this — on an 8 h event that's always you; on
  12 h / 24 h events earlier producers skip Discord entirely.
- **Director:** confirm the producer is joined to the "Interviews" channel **before you
  cut**, then switch to **Interview**, show the lower-third, and manage mutes as guests
  join the voice channel.

## End

Producer clicks **Stop Streaming**; stop the feeds (Ctrl+C the relay, or
`python3 src/scripts/stop-streams.py` in static mode).

If anything misbehaves, see [Troubleshooting](Troubleshooting).
