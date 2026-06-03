# Troubleshooting

Symptom → fix. Run `python3 src/scripts/preflight.py` first — it catches most setup
problems (tool chain, ports, cookies) before they bite you live.

## Feeds

| Symptom | Fix |
|---------|-----|
| Feed fails with *"Sign in to confirm you're not a bot"* | Refresh YouTube cookies (`get-cookies.py`) and confirm **deno** is installed — the relay needs both. `/status` should show `"cookies": true`. |
| A feed won't appear | Confirm the streamer is actually live; check that feed's log for errors; update streamlink/yt-dlp (`brew upgrade` / `pip install -U`). |
| Curling a feed port returns nothing | Expected — each port serves a **single** consumer (OBS), not arbitrary clients. Not a failure. |
| Feed stuck at 720p but should be 1080p | Streamlink's YouTube plugin capped it — use the yt-dlp fallback for that feed ([Static Mode](Static-Mode#yt-dlp-fallback-only-if-streamlink-caps-below-1080p)); confirm the streamer ingests 1080p. |
| Quality dropped below 720p | Streamer's upload can't sustain it — they should lower fps (720p30) but hold 720p; check their encoder. |
| Buffering / stalls | Raise OBS Network Buffering and/or `--ringbuffer-size`; raise `--hls-live-edge`; confirm the streamer is on **Low** latency (not Ultra-low); keep total upload under ~70–80 % of real capacity. |
| Picture artifacts | Enable hardware decoding on the Media Source; check the streamer's source bitrate. |
| Relay handover didn't switch | The off-air feed advances on **`/next`** (Feeds Next) or **`/reload`**, not mid-stint. Press Feeds Next once, after cutting to the new feed. |

## Control / network

| Symptom | Fix |
|---------|-----|
| Director can't reach Companion | Tailscale "Connected" on both machines? Companion running with **GUI Interface = All Interfaces**? Using the **Tailscale** IP (`100.x.y.z`), not a local IP? |
| Companion shows OBS disconnected | OBS open with WebSocket enabled? Port `4455` + correct **password** in the OBS connection? |
| Relay buttons do nothing | The Generic-HTTP connection points at the right host:port (`…:8088`)? For remote control the relay must be bound to the producer's Tailscale IP (`--bind …`), not local-only. |
| Director panel won't connect | It talks to OBS **directly** — enter the OBS IP + `4455` + WebSocket **password**. Use `http://`/`file://`, never `https://`. |

## Audio

| Symptom | Fix |
|---------|-----|
| No Discord audio (macOS) | Discord must run in **windowed** mode (not fullscreen) for App Audio Capture; grant OBS Screen &amp; System Audio Recording permission. |
| Interview audio doubled / echo | Capture Discord only via App/Application Audio Capture, not *also* via desktop audio. |

## Performance

| Symptom | Fix |
|---------|-----|
| One machine overloaded (producer = director) | Hardware-encode the broadcast; current GPU driver; hardware-decode every Media Source; lower a streamer to 720p30 if upload is tight. |
| General lag / slowdowns | RAM is the usual bottleneck (16 GB) — **reboot before the event** to clear swap, close other apps, and run preflight. |

See also: [Relay Mode](Relay-Mode), [Runbook](Runbook).
