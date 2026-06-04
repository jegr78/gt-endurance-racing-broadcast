# Static Mode

> Technical reference — the public-stream fallback.

The simpler fallback: one Streamlink server per **public** / fixed channel, each on its
own fixed port. Use this only when every feed is a public channel with a permanent live
URL. For the typical endurance flow (one commentator per stint, unlisted streams), use
[Relay Mode](Relay-Mode) instead.

## How it differs from the relay

- **Relay:** two feeds walk a stint schedule, pulls unlisted watch URLs via yt-dlp +
  cookies, controlled live over HTTP.
- **Static:** one long-lived Streamlink server per channel, fed by that channel's
  permanent `…/channel/<ID>/live` URL. No schedule, no handover logic.

Each channel gets its own fixed local port and a loop so it auto-recovers and waits for
the channel to go live. Idle channels (streamer not live yet) use almost no bandwidth —
they just poll.

## Configure the channels

Put each streamer's channel ID and port into the `FEEDS` list in
`src/scripts/start-streams.py`:

```python
FEEDS = [
    ("UCxxxxxxxxxxxxxxxxxxxxxx", 53001),   # Feed A
    ("UCyyyyyyyyyyyyyyyyyyyyyy", 53002),   # Feed B
    # one entry per channel, incrementing the port
]
```

Ports must match the OBS media sources Feed A / Feed B (`http://127.0.0.1:<port>`).

To find a channel's ID: open the channel → the `UC…` string in
`youtube.com/channel/UC…`, or the owner reads it in YouTube Studio → Settings → Channel →
Advanced.

## Start / stop

```bash
python3 src/scripts/start-streams.py     # launches one streamlink server per feed
python3 src/scripts/stop-streams.py      # stops them (validates each PID is really a feed)
```

PID and log files live under `runtime/static/`. `stop-streams.py` verifies a PID actually
belongs to a feed process before killing it, and does **not** broadly `pkill` — so it
won't touch live relay feeds.

## The Streamlink flags (what they do)

The quality selector and buffering flags used per feed:

- `1080p60,1080p,720p60,720p` — prefer 1080p, never drop below 720p.
- `--player-external-http --player-external-http-port <port>` — serve at
  `http://127.0.0.1:<port>` for OBS.
- `--ringbuffer-size 64M` — the memory buffer that absorbs network hiccups.
- `--hls-live-edge 6` — stay several segments behind live for a healthy cushion.
- `--retry-streams 15 --retry-open 5` — poll cheaply until the channel goes live, then
  connect automatically.

For **Twitch** channels add `--twitch-disable-ads` and use the Twitch URL; everything
else is identical.

## yt-dlp fallback (only if Streamlink caps below 1080p)

```bash
yt-dlp -g "https://www.youtube.com/channel/<CHANNEL_ID>/live"
```

This prints a direct HLS URL — put it in that feed's OBS Media Source instead of the
local port. The link expires after a few hours, so re-resolve it at the stint change.
Use this only for the rare channel where Streamlink won't deliver 1080p.

See also: [Relay Mode](Relay-Mode), [If something goes wrong](If-something-goes-wrong).
