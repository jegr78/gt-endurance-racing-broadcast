# Director (Remote)

A director controls scenes, feeds, volume, mute and graphics **from a browser** — no OBS,
no Companion, no software beyond a browser. Multiple directors are supported, and the
producer can also take this role locally.

## Reaching Companion over Tailscale

1. The producer and director are on the same tailnet (see
   [Installation → Tailscale](Installation#tailscale-private-network-for-remote-directors)).
2. Director opens **`http://<PRODUCER-TAILSCALE-IP>:8000/tablet`** (producer IP via the
   Tailscale menu or `tailscale ip -4`).
3. That's it — the buttons drive the show. Companion makes any relay HTTP request locally
   on the producer station, so relay control works for remote directors too.

> Same-machine case: if the producer also directs on this PC, use OBS directly or the
> local page `http://localhost:8000/tablet`.

## Backup: the director panel

Companion is the primary surface. The **director panel** is a fallback that talks to OBS
directly — use it only if Companion is unavailable. It is less convenient because each
director must enter the OBS WebSocket password.

Two ways to open it:

- **Served by the relay (recommended):** the relay serves it at
  **`http://<producer-ip>:8088/panel`**. For remote directors, start the relay with
  `--bind <producer-tailscale-ip>` (otherwise it is local-only). `--no-panel` disables it.
- **As a file:** open `director-panel.html` directly (`file://` or `http://`, **not**
  `https://`).

Either way it connects **straight to OBS**, so the director must enter the OBS IP
(`127.0.0.1` locally / the producer Tailscale IP remotely) + port `4455` + the **OBS
WebSocket password**. That password requirement is exactly why Companion is preferred.

> **Security:** prefer binding the relay to the producer's **Tailscale IP**, not
> `0.0.0.0`. The relay control endpoints are unauthenticated and `/status` reveals stream
> URLs. See [Relay Mode → Security note](Relay-Mode#security-note).

## What the director does during a show

See the [Runbook](Runbook) for the full sequence. In short: keep the **Stint** scene on
the active feed, toggle HUD/graphics via Companion, manage volumes; at each driver change
cut to **Splitscreen**, press **Feeds Next**, then cut to **Stint** on the new feed; for
post-race interviews switch to **Interview** and manage Discord mutes.

> Before cutting to **Interview**, confirm the **producer is joined to the Discord
> "Interviews" voice channel** — the audio capture is local to the producer, so you can't
> join for them. See [Runbook → Interviews](Runbook#interviews-post-race).
